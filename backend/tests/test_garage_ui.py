"""Claimant-to-garage handoff in two independent mobile browser contexts."""
import base64
from contextlib import ExitStack
import os
from pathlib import Path
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
        garage.get_by_label('Choose quote PDF').set_input_files(QUOTES / 'itemized-890.pdf')
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
        picker = garage.get_by_label('Choose quote PDF')
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
        expect(garage.get_by_label('Choose quote PDF')).to_be_hidden()

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
            self.assertIn(name, garage.get_by_label('Choose quote PDF').input_value())
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
