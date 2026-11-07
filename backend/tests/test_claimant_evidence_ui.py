"""Claimant evidence journeys through the real HTTP service at phone size."""
from contextlib import ExitStack
import base64
import os
import struct
import zlib
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from backend.tests.test_reviewer import running_api

try:
    from playwright.sync_api import expect, sync_playwright
except ImportError:
    sync_playwright = None


FIXTURES = Path(__file__).resolve().parents[1] / 'fixtures'


def original_png(width=1100, height=1100):
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))
    png = (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)) +
           chunk(b'IDAT', zlib.compress((b'\x00' + b'\xab' * (width * 3)) * height, 0)) + chunk(b'IEND', b''))
    return png


@unittest.skipUnless(sync_playwright, 'Browser tests require Playwright and Chromium.')
class ClaimantEvidenceUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        stack = ExitStack()
        cls.addClassCleanup(stack.close)
        folder = stack.enter_context(TemporaryDirectory())
        port = stack.enter_context(running_api(Path(folder) / 'claims.sqlite'))
        cls.origin = f'http://127.0.0.1:{port}'
        driver = stack.enter_context(sync_playwright())
        cls.browser = driver.chromium.launch(executable_path=os.getenv('CLAIM_TEST_BROWSER'))
        stack.callback(cls.browser.close)

    def setUp(self):
        self.page = self.browser.new_page(viewport={'width': 390, 'height': 844})
        self.addCleanup(self.page.close)
        self.page.context.grant_permissions(['clipboard-read', 'clipboard-write'], origin=self.origin)
        self.page.set_default_timeout(7000)
        self.page.goto(self.origin + '/chat')

    def button(self, name):
        return self.page.get_by_role('button', name=name, exact=True)

    def documents(self):
        self.button('Tell me what happened').click()
        for answer in ['A van scraped my parked car.', '2025-10-18', 'Demo car park',
                       'MOTOR-123', 'demo@example.invalid']:
            self.page.locator('#answer').fill(answer)
            self.button('Continue').click()
        self.button('No').click()

    def upload(self, kind, path):
        self.page.get_by_label('Paperwork type').select_option(kind)
        self.page.locator('#doc-files').set_input_files(path)

    def submit(self):
        self.button('Review claim').click()
        self.button('Submit claim').click()
        expect(self.page.get_by_role('heading', name='Claim received', exact=True)).to_be_visible()

    def test_receipt_names_next_actor_and_remains_available_from_private_link(self):
        self.documents()
        self.upload('incident_report', FIXTURES / 'sample-accident-report.pdf')
        self.submit()
        next_action = self.page.get_by_role('region', name='Who acts next')
        expect(next_action).to_contain_text('quote')
        expect(next_action).to_contain_text('sample-accident-report.pdf')
        self.page.reload()
        expect(next_action).to_contain_text('quote')

    def test_quote_evidence_and_request_survive_draft_and_revised_uploads(self):
        self.documents()
        quote_files = FIXTURES / 'quotes'
        total = quote_files / 'total-only-890.pdf'
        self.upload('itemized_quote', total)
        expect(self.page.get_by_role('list', name='Document checklist')).to_contain_text('Needs clarification')
        self.button('Copy request for garage').click()
        request = self.page.evaluate('navigator.clipboard.readText()')
        self.assertIn('890', request)
        self.assertIn('itemized', request.lower())
        self.button('Save and continue later').click()
        expect(self.page.get_by_role('textbox', name='Draft saved · private resume link')).to_be_visible()
        self.page.reload()
        expect(self.button('Copy request for garage')).to_be_visible()
        self.upload('incident_report', FIXTURES / 'sample-accident-report.pdf')
        self.submit()
        self.page.reload()
        expect(self.page.get_by_role('region', name='Who acts next')).to_contain_text('quote')
        for name, expected_count in [('itemized-890.pdf', 3), ('itemized-1800.pdf', 4)]:
            self.page.get_by_text('Add documents to this claim', exact=True).click()
            self.upload('itemized_quote', quote_files / name)
            self.button('Send additional documents').click()
            expect(self.page.get_by_role('heading', name=f'Files received ({expected_count})')).to_be_visible()
            self.page.reload()
            expect(self.page.get_by_role('list', name='Received attachments')).to_contain_text(name)
        attachments = self.page.get_by_role('list', name='Received attachments')
        for name in ['total-only-890.pdf', 'itemized-890.pdf', 'itemized-1800.pdf']:
            expect(attachments).to_contain_text(name)

    def test_photo_walkthrough_is_available_without_using_any_attachment_slots(self):
        self.documents()
        expect(self.page.locator('.photo-guide')).to_contain_text('Wide shot')
        expect(self.page.locator('.photo-guide')).to_contain_text('Damage close-up')
        self.button('Review claim').click()
        expect(self.page.get_by_text('No documents attached', exact=True)).to_be_visible()

    def test_large_original_photo_date_explanation_survives_save_review_and_submission(self):
        png = original_png()
        self.assertGreater(len(png), 2 * 1024 * 1024)
        self.documents()
        self.page.locator('#gallery-files').set_input_files({'name': 'door.png', 'mimeType': 'image/png', 'buffer': png})
        self.page.get_by_label('Photo date supplied by you').fill('2025-10-19')
        explanation = 'I took this picture the next morning after the rain stopped.'
        self.page.get_by_label('Explain the difference').fill(explanation)
        with self.page.expect_response('**/api/intakes/save-draft') as saved:
            self.button('Save and continue later').click()
        self.assertEqual(saved.value.request.post_data_json['draft']['notes']['photos'][0]['explanation'],
                         explanation)
        self.page.reload()
        expect(self.page.get_by_label('Explain the difference')).to_have_value(explanation)
        self.button('Review claim').click()
        expect(self.page.get_by_text(explanation, exact=False)).to_be_visible()
        with self.page.expect_response('**/api/intakes/submit') as sent:
            self.button('Submit claim').click()
        self.assertEqual(base64.b64decode(sent.value.request.post_data_json['payload']['documents'][0]['content_base64']), png)
        expect(self.page.get_by_role('heading', name='Claim received', exact=True)).to_be_visible()
        self.page.reload()
        expect(self.page.get_by_role('heading', name='Claim received', exact=True)).to_be_visible()
        expect(self.page.get_by_text(explanation, exact=False)).to_have_count(0)

    def test_german_import_requires_a_choice_and_retains_both_versions(self):
        german = FIXTURES / 'photo-guide/accident-report-de.pdf'
        self.page.locator('#import-file').set_input_files(german)
        english = self.page.get_by_label('English translation')
        expect(english).to_be_visible()
        self.button('Confirm details and continue').click()
        expect(english).to_be_visible()
        accepted = 'A van scraped the car while it was parked.'
        english.fill(accepted)
        self.button('Confirm English translation').click()
        self.button('Confirm details and continue').click()
        with self.page.expect_response('**/api/intakes/save-draft') as saved:
            self.button('Save and continue later').click()
        draft = saved.value.request.post_data_json['draft']
        self.assertEqual(draft['values']['description'], accepted)
        translation = draft['notes']['translations'][0]
        self.assertTrue(translation['confirmed'])
        self.assertEqual(translation['english'], accepted)
        self.assertNotEqual(translation['original'], accepted)

    def test_example_claim_is_opt_in_and_delivers_private_link_and_reviewer_handoff(self):
        expect(self.button('Start sample claim')).to_have_count(0)
        self.page.goto(self.origin + '/chat?demo=DEV-003')
        self.button('Start sample claim').click()
        self.upload('itemized_quote', FIXTURES / 'quotes/total-only-890.pdf')
        self.button('Review claim').click()
        with self.page.expect_response('**/api/intakes/submit') as sent:
            self.button('Submit claim').click()
        self.assertEqual(sent.value.request.post_data_json['payload']['demo_case'], 'DEV-003')
        expect(self.page.get_by_role('heading', name='Claim received', exact=True)).to_be_visible()
        viewer = self.page.get_by_role('link', name='Open reviewer evidence')
        expect(viewer).to_be_visible()
        href = viewer.get_attribute('href')
        self.assertTrue(href.startswith('/reviewer/evidence'))
        self.assertNotIn('#claim=', href)

    def test_can_file_using_original_german_without_an_approved_english_translation(self):
        self.page.locator('#import-file').set_input_files(FIXTURES / 'photo-guide/accident-report-de.pdf')
        self.button('Continue with original German').click()
        self.button('Confirm details and continue').click()
        self.button('No').click()
        self.button('Review claim').click()
        expect(self.page.get_by_text('Original German retained.', exact=True)).to_be_visible()
        with self.page.expect_response('**/api/intakes/submit') as response:
            self.button('Submit claim').click()
        self.assertTrue(response.value.ok)
        claim = response.value.request.post_data_json['payload']
        note = claim['notes']['translations'][0]
        self.assertFalse(note['confirmed'])
        self.assertTrue(note['use_original'])
        self.assertEqual(claim['description'], note['original'])

    def test_imported_quote_explains_the_missing_breakdown_before_confirming(self):
        self.page.locator('#import-file').set_input_files(FIXTURES / 'quotes/total-only-890.pdf')
        expect(self.page.get_by_role('heading', name='Check your PDF details')).to_be_visible()
        expect(self.button('Copy request for garage')).to_be_visible()
        expect(self.page.get_by_role('region', name='Quote check for total-only-890.pdf')).to_contain_text('890')

    def test_open_with_a_report_image_preserves_original_through_draft_and_submission(self):
        png = original_png(960, 1000)
        self.assertGreater(len(png), 2 * 1024 * 1024)
        pdf_reads = []
        self.page.on('request', lambda r: pdf_reads.append(r.url) if r.url.endswith('/import-pdf') else None)
        with self.page.expect_file_chooser() as chooser:
            self.button('Choose a photo or PDF').click()
        chooser.value.set_files({'name':'report.png','mimeType':'image/png','buffer':png})
        preview = self.page.get_by_role('img', name='Preview of report.png')
        expect(preview).to_be_visible()
        self.assertTrue(preview.evaluate('(img) => img.complete && img.naturalWidth > 0'))
        self.page.get_by_label('What does this image show?').select_option('incident_report')
        self.button('Attach image and continue').click()
        expect(self.page.locator('#answer')).to_have_value('')
        self.button('Save and continue later').click()
        expect(self.page.get_by_role('textbox', name='Draft saved · private resume link')).to_be_visible()
        self.page.reload()
        for answer in ['A van scraped my car.', '2025-10-18', 'Demo car park', 'MOTOR-123', 'demo@example.invalid']:
            self.page.locator('#answer').fill(answer)
            self.button('Continue').click()
        self.button('No').click()
        expect(self.page.get_by_role('list', name='Attachments to send')).to_contain_text('report.png')
        self.button('Review claim').click()
        with self.page.expect_response('**/api/intakes/submit') as result:
            self.button('Submit claim').click()
        self.assertTrue(result.value.ok)
        doc, = result.value.request.post_data_json['payload']['documents']
        self.assertEqual((doc['kind'], base64.b64decode(doc['content_base64'])), ('incident_report', png))
        self.assertEqual(pdf_reads, [])
        expect(self.page.get_by_role('heading', name='Claim received', exact=True)).to_be_visible()

    def test_camera_preview_can_be_replaced_reclassified_or_cancelled(self):
        camera = self.page.locator('input[capture=environment]')
        self.assertEqual(camera.count(), 1)
        camera.set_input_files(FIXTURES / 'photo-guide/wide.jpg')
        expect(self.page.get_by_role('img', name='Preview of wide.jpg')).to_be_visible()
        with self.page.expect_file_chooser() as chooser:
            self.button('Replace file').click()
        chooser.value.set_files(FIXTURES / 'photo-guide/close-up.jpg')
        expect(self.page.get_by_role('img', name='Preview of close-up.jpg')).to_be_visible()
        expect(self.page.get_by_role('img', name='Preview of wide.jpg')).to_have_count(0)
        self.page.get_by_label('What does this image show?').select_option('itemized_quote')
        self.button('Cancel').click()
        expect(self.page.get_by_role('heading', name='How would you like to start?')).to_be_visible()
        self.documents()
        self.button('Review claim').click()
        expect(self.page.get_by_text('No documents attached', exact=True)).to_be_visible()

    def test_dropped_camera_image_can_be_filed_as_damage_or_quote(self):
        jpeg = base64.b64encode((FIXTURES / 'photo-guide/wide.jpg').read_bytes()).decode()
        for kind in ('damage_photo', 'itemized_quote'):
            with self.subTest(kind=kind):
                self.page.goto(self.origin + '/chat')
                self.page.locator('.drop-zone').evaluate("""(area, encoded) => {
                    const bytes = Uint8Array.from(atob(encoded), c => c.charCodeAt(0));
                    const transfer = new DataTransfer();
                    transfer.items.add(new File([bytes], 'evidence.jpeg', {type:'image/jpeg'}));
                    area.dispatchEvent(new DragEvent('drop', {bubbles:true, cancelable:true, dataTransfer:transfer}));
                }""", jpeg)
                expect(self.page.get_by_role('img', name='Preview of evidence.jpeg')).to_be_visible()
                self.page.get_by_label('What does this image show?').select_option(kind)
                if kind == 'itemized_quote':
                    expect(self.page.get_by_role('region', name='Quote check for evidence.jpeg')).to_contain_text('Photo received for review')
                    expect(self.button('Copy request for garage')).to_have_count(0)
                self.button('Attach image and continue').click()
                with self.page.expect_response('**/api/intakes/save-draft') as saved:
                    self.button('Save and continue later').click()
                self.assertTrue(saved.value.ok)
                draft = saved.value.request.post_data_json['draft']
                doc, = draft['documents']
                self.assertEqual((doc['kind'],doc['content_base64']), (kind, jpeg))
                self.assertFalse(draft['values'].get('description'))
                if kind == 'damage_photo':
                    self.assertEqual(draft['notes']['photos'][0]['position'], 0)

    def test_opening_rejects_invalid_signatures_and_pdf_size_and_keeps_the_prior_image(self):
        picker = self.page.locator('#import-file')
        picker.set_input_files({'name':'mislabeled.jpg','mimeType':'image/jpeg','buffer':b'not a JPEG'})
        expect(self.page.get_by_role('alert')).to_be_visible()
        expect(self.page.get_by_role('img', name='Preview of mislabeled.jpg')).to_have_count(0)
        picker.set_input_files({'name':'large.pdf','mimeType':'application/pdf','buffer':b'%PDF-' + b'x' * (2*1024*1024)})
        expect(self.page.get_by_role('alert')).to_contain_text('2 MiB')
        picker.set_input_files(FIXTURES / 'photo-guide/wide.jpg')
        expect(self.page.get_by_role('img', name='Preview of wide.jpg')).to_be_visible()
        with self.page.expect_file_chooser() as chooser:
            self.button('Replace file').click()
        chooser.value.set_files({'name':'too-large.png','mimeType':'image/png','buffer':b'x' * (12*1024*1024 + 1)})
        expect(self.page.get_by_role('alert')).to_contain_text('12 MiB')
        expect(self.page.get_by_role('img', name='Preview of wide.jpg')).to_be_visible()

    def test_receipt_assigns_a_submitted_camera_quote_to_review_without_requesting_it_again(self):
        self.page.goto(self.origin + '/chat?demo=DEV-003')
        self.button('Start sample claim').click()
        self.upload('itemized_quote', FIXTURES / 'photo-guide/wide.jpg')
        self.submit()
        for _ in range(2):
            expect(self.page.get_by_role('region', name='Quote check for wide.jpg')).to_contain_text('Photo received for review')
            expect(self.page.get_by_role('region', name='Who acts next')).to_contain_text('Claims team')
            expect(self.button('Copy request for garage')).to_have_count(0)
            expect(self.button('Request a revised quote (optional)')).to_be_visible()
            expect(self.button('Request breakdown from garage')).to_have_count(0)
            self.page.reload()

    def test_legacy_receipt_keeps_its_original_two_mib_limit(self):
        receipt = {'status':'submitted', 'document_count':0, 'reference':'CLM-legacy-test',
                   'documents':[], 'missing_documents':['incident_report','itemized_quote']}
        self.page.route('**/api/intakes/resume', lambda route: route.fulfill(json=receipt))
        self.page.goto(self.origin + '/chat#claim=' + 'f' * 64)
        self.page.get_by_text('Add documents to this claim', exact=True).click()
        self.page.locator('#doc-files').set_input_files({'name':'report.jpg','mimeType':'image/jpeg',
                                                         'buffer':b'\xff\xd8\xff' + b'X' * (2*1024*1024)})
        expect(self.page.get_by_role('alert')).to_contain_text('2 MiB')
        expect(self.button('Send additional documents')).to_have_count(0)

    def test_followup_accepts_a_large_camera_quote_as_original_evidence(self):
        self.page.goto(self.origin + '/chat?demo=DEV-003')
        self.button('Start sample claim').click()
        self.submit()
        self.page.get_by_text('Add documents to this claim', exact=True).click()
        png = original_png()
        self.upload('itemized_quote', {'name':'garage-photo.png', 'mimeType':'image/png', 'buffer':png})
        staged = self.page.get_by_role('region', name='Quote check for garage-photo.png')
        expect(staged).to_contain_text('Photo received for review')
        with self.page.expect_response('**/api/intakes/add-documents') as sent:
            self.button('Send additional documents').click()
        self.assertTrue(sent.value.ok)
        self.assertEqual(base64.b64decode(sent.value.request.post_data_json['documents'][0]['content_base64']), png)
        expect(self.page.get_by_role('list', name='Received attachments')).to_contain_text('garage-photo.png')
