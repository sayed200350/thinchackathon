"""Claimant-to-garage handoff in two independent mobile browser contexts."""
import base64
from contextlib import ExitStack
import os
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
from threading import Thread
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

from backend.garage_public import create_server

from backend.tests.test_reviewer import running_api

try:
    from playwright.sync_api import expect, sync_playwright
except ImportError:
    sync_playwright = None


QUOTES = Path(__file__).resolve().parents[1] / 'fixtures/quotes'


@unittest.skipUnless(sync_playwright, 'Browser tests require Playwright and Chromium.')
class GarageHandoffUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        stack = ExitStack()
        cls.addClassCleanup(stack.close)
        folder = stack.enter_context(TemporaryDirectory())
        # Bind the gateway before announcing its port to the internal API.
        gateway = stack.enter_context(create_server('127.0.0.1', 0, 'http://127.0.0.1:1'))
        with patch.dict(os.environ, {'GARAGE_PUBLIC_ORIGIN': f'http://garage-device.local:{gateway.server_port}'}):
            port = stack.enter_context(running_api(Path(folder) / 'handshake.sqlite'))
        gateway.upstream = ('127.0.0.1', port)
        thread = Thread(target=gateway.serve_forever, kwargs={'poll_interval':0.02}, daemon=True)
        thread.start()
        stack.callback(thread.join, 2)
        stack.callback(gateway.shutdown)
        cls.origin = f'http://127.0.0.1:{port}'
        driver = stack.enter_context(sync_playwright())
        cls.browser = driver.chromium.launch(executable_path=os.getenv('CLAIM_TEST_BROWSER'),
                                             args=['--no-proxy-server', '--host-resolver-rules=MAP garage-device.local 127.0.0.1'])
        stack.callback(cls.browser.close)

    def phone(self):
        context = self.browser.new_context(viewport={'width': 390, 'height': 844})
        self.addCleanup(context.close)
        page = context.new_page()
        page.set_default_timeout(5500)
        return page

    def test_two_devices_exchange_a_revision_without_sharing_the_claimant_link(self):
        driver, garage = self.phone(), self.phone()
        driver.goto(self.origin + '/chat?demo=DEV-003')
        driver.get_by_role('button', name='Start sample claim').click()
        driver.locator('#doc-files').set_input_files(QUOTES / 'total-only-890.pdf')
        driver.get_by_role('button', name='Review claim').click()
        driver.get_by_role('button', name='Submit claim').click()
        ask = driver.get_by_role('button', name='Request breakdown from garage', exact=True)
        expect(ask).to_be_visible()
        ask.click()
        link = driver.get_by_role('textbox', name='Garage upload link', exact=True)
        expect(link).to_be_visible()
        url = link.input_value()
        claimant_token = urlsplit(driver.url).fragment.removeprefix('claim=')
        self.assertNotIn(claimant_token, url)
        self.assertTrue(urlsplit(url).fragment.startswith('upload='))
        img = driver.get_by_role('img', name='Scan to send a garage quote')
        self.assertTrue(img.get_attribute('src').startswith('data:image/svg+xml'))
        driver.context.grant_permissions(['clipboard-read', 'clipboard-write'], origin=self.origin)
        driver.get_by_role('button', name='Copy garage link').click()
        self.assertEqual(driver.evaluate('navigator.clipboard.readText()'), url)
        driver.get_by_text('Add documents to this claim', exact=True).click()
        driver.locator('#doc-files').set_input_files(QUOTES / 'unreadable-total.pdf')
        expect(driver.get_by_role('button', name='Send additional documents')).to_be_visible()

        garage.goto(url)
        expect(garage.get_by_role('heading', name='Send an itemized quote')).to_be_visible()
        expect(garage.get_by_role('link', name='€890 itemized PDF')).to_be_visible()
        expect(garage.get_by_role('link', name='€1,800 itemized PDF')).to_be_visible()
        for private_text in ('DEV-003', 'driver@example.invalid', 'CLM-', claimant_token):
            self.assertNotIn(private_text, garage.locator('body').inner_text())
        garage.get_by_label('Choose a file or gallery photo').set_input_files(QUOTES / 'itemized-890.pdf')
        with garage.expect_response('**/api/garage/upload') as sent:
            garage.get_by_role('button', name='Send quote', exact=True).click()
        self.assertEqual(set(sent.value.request.post_data_json), {'token', 'document'})
        self.assertEqual(base64.b64decode(sent.value.request.post_data_json['document']['content_base64']),
                         (QUOTES / 'itemized-890.pdf').read_bytes())
        expect(garage.get_by_role('heading', name='Quote received')).to_be_visible()
        driver.bring_to_front()
        expect(driver.get_by_role('list', name='Received attachments')).to_contain_text('itemized-890.pdf', timeout=15000)
        expect(driver.get_by_role('button', name='Send additional documents')).to_be_visible()
        expect(driver.get_by_role('list', name='Attachments to send')).to_contain_text('unreadable-total.pdf')
        expect(driver.get_by_role('region', name='Quote check for itemized-890.pdf')).to_contain_text('Received from garage')
        driver.get_by_role('button', name='Refresh receipt').click()
        expect(driver.get_by_role('list', name='Attachments to send')).to_contain_text('unreadable-total.pdf')
        expect(driver.get_by_role('button', name='Request breakdown from garage')).to_be_visible()
        garage.reload()
        expect(garage.get_by_role('heading', name='Quote received')).to_be_visible()

    def test_phone_validates_the_pdf_and_hides_demo_files_on_an_ordinary_request(self):
        garage = self.phone()
        garage.route('**/api/garage/status', lambda route: route.fulfill(json={'status':'open', 'demo':False}))
        garage.goto(self.origin + '/garage#upload=valid-test-token')
        picker = garage.get_by_label('Choose a file or gallery photo')
        expect(picker).to_be_visible()
        expect(garage.get_by_role('link', name='€890 itemized PDF')).to_have_count(0)
        expect(garage.get_by_role('button', name='Use €890 example')).to_have_count(0)
        expect(garage.get_by_role('button', name='Use €1,800 example')).to_have_count(0)
        for name, data in [('notes.txt', b'hello'), ('renamed.pdf', b'no PDF here'),
                           ('oversized.pdf', b'%PDF-' + b'a' * (2*1024*1024))]:
            picker.set_input_files({'name':name, 'mimeType':'application/pdf', 'buffer':data})
            expect(garage.get_by_role('alert')).to_be_visible()
            expect(garage.get_by_role('button', name='Send quote', exact=True)).to_be_disabled()
        picker.set_input_files(QUOTES / 'itemized-1800.pdf')
        expect(garage.get_by_role('button', name='Send quote', exact=True)).to_be_enabled()
        garage.route('**/api/garage/upload', lambda route: route.abort())
        garage.get_by_role('button', name='Send quote').click()
        expect(garage.get_by_role('alert')).to_be_visible()
        expect(garage.get_by_role('button', name='Send quote', exact=True)).to_be_enabled()
        self.assertIn('itemized-1800.pdf', picker.input_value())
        self.assertTrue(garage.evaluate('document.documentElement.scrollWidth <= innerWidth'))

    def test_camera_and_gallery_can_retake_replace_remove_and_retry_the_original_photo(self):
        garage = self.phone()
        garage.route('**/api/garage/status', lambda route: route.fulfill(json={'status':'open', 'demo':False}))
        garage.goto(self.origin + '/garage#upload=phone-test')
        camera = garage.get_by_role('button', name='Take a photo', exact=True)
        picker = garage.get_by_label('Choose a file or gallery photo')
        self.assertIsNone(picker.get_attribute('capture', timeout=1500))
        self.assertIn('image/png', picker.get_attribute('accept'))
        quote_image = (QUOTES.parent / 'photo-guide/wide.jpg').read_bytes()
        close_image = (QUOTES.parent / 'photo-guide/close-up.jpg').read_bytes()
        photo = {'name':'page.jpeg', 'mimeType':'image/jpeg', 'buffer':quote_image}
        with garage.expect_file_chooser() as chooser:
            camera.click()
        self.assertEqual(chooser.value.element.get_attribute('capture'), 'environment')
        chooser.value.set_files(photo)
        preview = garage.get_by_role('img', name='Quote photo preview')
        expect(preview).to_be_visible()
        self.assertGreater(preview.evaluate('image => image.naturalWidth'), 20)
        with garage.expect_file_chooser() as retake:
            garage.get_by_role('button', name='Retake photo').click()
        self.assertEqual(retake.value.element.get_attribute('capture'), 'environment')
        retake.value.set_files({'name':'closer.jpg','mimeType':'image/jpeg','buffer':close_image})
        expect(garage.get_by_text('Ready to send · closer.jpg')).to_be_visible()
        with garage.expect_file_chooser() as replace:
            garage.get_by_role('button', name='Replace file').click()
        self.assertIsNone(replace.value.element.get_attribute('capture'))
        png = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScLbtAAAAABJRU5ErkJggg==')
        replace.value.set_files({'name':'page.png','mimeType':'image/png','buffer':png})
        expect(garage.get_by_text('Ready to send · page.png')).to_be_visible()
        self.assertTrue(preview.get_attribute('src').startswith('data:image/png'))
        garage.get_by_role('button', name='Remove file').click()
        expect(preview).to_be_hidden()
        expect(garage.get_by_role('button', name='Send quote')).to_be_disabled()
        self.assertFalse(picker.input_value())

        # Original bytes, including metadata/trailing bytes, survive preview and retries.
        maximum_photo = quote_image.ljust(12 * 1024 * 1024, b'x')
        picker.set_input_files({'name':'garage-camera.JPG','mimeType':'image/jpeg','buffer':maximum_photo})
        expect(garage.get_by_text('Ready to send · garage-camera.JPG')).to_be_visible()
        send = garage.get_by_role('button', name='Send quote')
        garage.route('**/api/garage/upload', lambda route: route.fulfill(status=503))
        send.click()
        expect(garage.get_by_role('alert')).to_contain_text('try', ignore_case=True)
        expect(send).to_be_enabled()
        expect(preview).to_be_visible()
        received = []
        garage.unroute('**/api/garage/upload')
        def capture(route):
            document = route.request.post_data_json['document']
            received.append((document['name'], document['kind'], base64.b64decode(document['content_base64'])))
            route.fulfill(json={'status':'received'})
        garage.route('**/api/garage/upload', capture)
        send.click()
        expect(garage.get_by_role('heading', name='Quote received')).to_be_visible()
        self.assertEqual(received, [('garage-camera.JPG','itemized_quote',maximum_photo)])
        self.assertNotIn('Your PDF', garage.locator('main').inner_text())

    def test_wrong_photo_signatures_and_oversize_photos_cannot_be_sent(self):
        garage = self.phone()
        garage.route('**/api/garage/status', lambda route: route.fulfill(json={'status':'open', 'demo':False}))
        garage.goto(self.origin + '/garage#upload=phone-test')
        picker = garage.get_by_label('Choose a file or gallery photo')
        jpeg = (QUOTES.parent / 'photo-guide/wide.jpg').read_bytes()
        for name, data in [('wrong.png',jpeg), ('wrong.jpg',b'%PDF-fake'), ('unreadable.jpg',jpeg[:9]),
                           ('camera.heic',jpeg), ('oversized.jpeg',jpeg.ljust(12*1024*1024 + 1, b'x'))]:
            with self.subTest(name=name):
                picker.set_input_files({'name':name, 'mimeType':'image/jpeg', 'buffer':data})
                expect(garage.get_by_role('alert')).to_be_visible()
                expect(garage.get_by_role('img', name='Quote photo preview')).to_be_hidden()
                expect(garage.get_by_role('button', name='Send quote')).to_be_disabled()
        self.assertTrue(garage.evaluate('document.documentElement.scrollWidth <= innerWidth'))

    @unittest.skipUnless(shutil.which('pdftoppm'), 'Rendering the photographed estimate requires Poppler.')
    def test_four_mib_camera_quote_reaches_the_claim_through_the_phone_gateway(self):
        driver, phone = self.phone(), self.phone()
        driver.goto(self.origin + '/chat?demo=DEV-003')
        for step in ('Start sample claim', 'Review claim', 'Submit claim', 'Request breakdown from garage'):
            driver.get_by_role('button', name=step, exact=True).click()
        phone.goto(driver.get_by_role('textbox', name='Garage upload link').input_value())
        with phone.expect_file_chooser() as camera:
            phone.get_by_role('button', name='Take a photo').click()
        rendered = subprocess.check_output(['pdftoppm', '-f', '1', '-l', '1', '-scale-to', '800',
                                            '-jpeg', str(QUOTES / 'itemized-890.pdf')], timeout=10)
        photo = rendered.ljust(4 * 1024**2, b'\0')
        camera.value.set_files({'name':'photographed-estimate.jpg', 'mimeType':'image/jpeg', 'buffer':photo})
        expect(phone.get_by_role('img', name='Quote photo preview')).to_be_visible()
        with phone.expect_response('**/api/garage/upload') as result:
            phone.get_by_role('button', name='Send quote').click()
        self.assertEqual(result.value.status, 200)
        expect(phone.get_by_role('heading', name='Quote received')).to_be_visible()
        driver.get_by_role('button', name='Refresh receipt').click()
        expect(driver.get_by_role('list', name='Received attachments')).to_contain_text('photographed-estimate.jpg')
        expect(driver.get_by_role('region', name='Quote check for photographed-estimate.jpg')).to_contain_text('Received from garage')

    def test_phone_closes_expired_urls_and_does_not_use_query_parameters(self):
        garage = self.phone()
        posts = []
        def closed(route):
            posts.append(route.request.post_data_json)
            route.fulfill(json={'status':'closed', 'demo':False})
        garage.route('**/api/garage/status', closed)
        garage.goto(self.origin + '/garage?upload=from-query-only')
        expect(garage.get_by_role('heading', name='Upload link unavailable')).to_be_visible()
        self.assertEqual(posts, [])
        garage.goto(self.origin + '/garage#upload=expired-test-token')
        expect(garage.get_by_role('heading', name='Upload link unavailable')).to_be_visible()
        self.assertEqual(posts, [{'token':'expired-test-token'}])
        expect(garage.get_by_label('Choose a file or gallery photo')).to_be_hidden()

    def test_reopened_receipt_labels_garage_provenance_on_the_correct_version(self):
        page = self.phone()
        def quote(name, version, source=None):
            row = {'name':name, 'version':version, 'page':1, 'reason':'Checked the quote.',
                   'status':'verified', 'amount_eur':890, 'garage_request':''}
            if source:
                row['source'] = source
            return row
        doc_names = ['driver-estimate.pdf', 'garage-estimate.pdf']
        receipt = {'reference':'CLM-example', 'document_count':2, 'status':'submitted', 'missing_documents':[],
                   'documents':[{'name':name, 'kind':'itemized_quote'} for name in doc_names],
                   'evidence':{'next_action':{'owner':'claims_team','message':'Review the claim.'},
                               'quotes':[quote(doc_names[0],1), quote(doc_names[1],2,'garage')]}}
        page.route('**/api/intakes/resume', lambda route: route.fulfill(json=receipt))
        page.goto(self.origin + '/chat#claim=' + 'a' * 64)
        expect(page.get_by_role('region', name='Quote check for garage-estimate.pdf')).to_contain_text('Received from garage')
        expect(page.get_by_role('region', name='Quote check for driver-estimate.pdf')).not_to_contain_text('Received from garage')

    def test_judges_can_stage_and_send_either_actual_example_pdf_from_the_phone(self):
        driver, garage = self.phone(), self.phone()
        driver.goto(self.origin + '/chat?demo=DEV-003')
        for step in ('Start sample claim', 'Review claim', 'Submit claim'):
            driver.get_by_role('button', name=step, exact=True).click()
        for amount, name in [('€890','itemized-890.pdf'), ('€1,800','itemized-1800.pdf')]:
            driver.get_by_role('button', name='Request breakdown from garage').click()
            field = driver.get_by_role('textbox', name='Garage upload link')
            expect(field).to_be_visible()
            garage.goto(field.input_value())
            send = garage.get_by_role('button', name='Send quote', exact=True)
            expect(send).to_be_disabled()
            garage.get_by_role('button', name=f'Use {amount} example', exact=True).click()
            expect(send).to_be_enabled()
            self.assertIn(name, garage.get_by_label('Choose a file or gallery photo').input_value())
            expect(garage.get_by_text(f'Ready to send · {name}', exact=True)).to_be_visible()
            with garage.expect_response('**/api/garage/upload') as upload:
                send.click()
            doc = upload.value.request.post_data_json['document']
            self.assertTrue(upload.value.ok)
            self.assertEqual(doc['name'], name)
            self.assertEqual(base64.b64decode(doc['content_base64']), (QUOTES / name).read_bytes())
            expect(garage.get_by_role('heading', name='Quote received')).to_be_visible()
            driver.bring_to_front()
            driver.get_by_role('button', name='Refresh receipt').click()
            expect(driver.get_by_role('list', name='Received attachments')).to_contain_text(name)

    def test_enlarged_projector_qr_reuses_the_link_and_restores_the_receipt(self):
        driver = self.phone()
        driver.set_viewport_size({'width': 1440, 'height': 900})
        issued = []
        driver.on('request', lambda req: issued.append(req.url) if req.url.endswith('/api/intakes/garage-link') else None)
        driver.goto(self.origin + '/chat?demo=DEV-003')
        for step in ('Start sample claim', 'Review claim', 'Submit claim', 'Request breakdown from garage'):
            driver.get_by_role('button', name=step, exact=True).click()
        original = driver.get_by_role('img', name='Scan to send a garage quote')
        expect(original).to_be_visible()
        inline_size, svg = original.bounding_box()['width'], original.get_attribute('src')
        url = driver.get_by_role('textbox', name='Garage upload link').input_value()
        enlarge = driver.get_by_role('button', name='Enlarge QR code')
        dialog = driver.get_by_role('dialog', name='Scan to send a garage quote')
        for dismiss in ('Escape', 'Close'):
            enlarge.click()
            expect(dialog).to_be_visible()
            image = dialog.get_by_role('img', name='Garage upload QR code')
            self.assertEqual(image.get_attribute('src'), svg)
            self.assertGreaterEqual(image.bounding_box()['width'], max(500, 1.5*inline_size))
            self.assertEqual(dialog.get_by_role('link', name='Open garage upload').get_attribute('href'), url)
            if dismiss == 'Escape':
                driver.keyboard.press('Escape')
            else:
                dialog.get_by_role('button', name='Close', exact=True).click()
            expect(dialog).to_be_hidden()
            expect(enlarge).to_be_focused()
        driver.get_by_role('button', name='Refresh receipt').click()
        expect(driver.get_by_role('textbox', name='Garage upload link')).to_have_value(url)
        self.assertEqual(len(issued), 1)
