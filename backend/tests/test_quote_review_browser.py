"""Reviewer evidence replay through the real browser entry point."""
from contextlib import ExitStack
from pathlib import Path
from secrets import token_hex
from tempfile import TemporaryDirectory
from urllib.parse import urljoin
import os
import shutil
import unittest

from backend.tests.test_reviewer import running_api
from backend.tests.test_intake import claim

try:
    from playwright.sync_api import expect, sync_playwright
except ImportError:
    sync_playwright = None


@unittest.skipUnless(sync_playwright and shutil.which('pdftotext'), 'Playwright, Chromium and Poppler required')
class EvidenceReplayUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        stack = ExitStack()
        cls.addClassCleanup(stack.close)
        folder = stack.enter_context(TemporaryDirectory())
        port = stack.enter_context(running_api(Path(folder) / 'review.sqlite'))
        cls.url = f'http://127.0.0.1:{port}/reviewer/evidence'
        driver = stack.enter_context(sync_playwright())
        cls.browser = driver.chromium.launch(executable_path=os.getenv('CLAIM_TEST_BROWSER'))
        stack.callback(cls.browser.close)

    def setUp(self):
        self.page = self.browser.new_page(viewport={'width': 390, 'height': 844})
        self.addCleanup(self.page.close)
        self.page.set_default_timeout(4000)
        self.page.goto(self.url)

    def test_judge_uploads_four_versions_and_opens_every_original(self):
        expected = [('total-only-890.pdf','Request information'),('itemized-890.pdf','Routine processing'),
                    ('itemized-1800.pdf','Human review'),('unreadable-total.pdf','Request information')]
        for index, (name, route) in enumerate(expected):
            sample = self.page.get_by_role('link', name=name)
            self.assertTrue(self.page.request.get(urljoin(self.url, sample.get_attribute('href'))).body().startswith(b'%PDF'))
            with self.page.expect_file_chooser() as picker:
                self.page.get_by_role('button', name='Upload garage quote').click()
            picker.value.set_files(Path(__file__).resolve().parents[1] / 'fixtures' / 'quotes' / name)
            record = self.page.get_by_role('article',name=f'Quote version {index+1}',exact=True)
            expect(record.get_by_text(route, exact=True)).to_be_visible()
            expect(record.get_by_role('link', name='Download original')).to_have_attribute('download',name)
        expect(self.page.get_by_role('article')).to_have_count(4)
        expect(self.page.get_by_text('Original recommendation', exact=True)).to_be_visible()
        for version, (name, _) in enumerate(expected, start=1):
            record = self.page.get_by_role('article', name=f'Quote version {version}', exact=True)
            with self.page.expect_download() as download:
                record.get_by_role('link', name='Download original').click()
            self.assertEqual(download.value.suggested_filename, name)
            self.assertEqual(download.value.path().read_bytes(), (Path(__file__).resolve().parents[1] /
                             'fixtures' / 'quotes' / name).read_bytes())

    def test_staff_lookup_renders_saved_evidence_and_clears_key_on_reload(self):
        requests = []
        def fake_result(route):
            requests.append(route.request.post_data_json)
            data = {'reference':'CLM-TEST','incident_date':'2025-10-11','documents':[{'kind':'damage_photo','name':'garage.png'}],
                    'evidence':{'quotes':[], 'notes':{
                        'photos':[{'position':0,'view':'wide','exif_date':'2025-10-12','manual_date':'2025-10-13','explanation':'Taken after pickup.'}],
                        'translations':[{'position':0,'original':'Das Auto war geparkt.','english':'The car was parked.','page':1,
                                         'source':'Local phrase','confirmed':True}]}, 'history':[],
                                'decision':{'recommendation':'request_information','matched_rule':'v1.missing','policy_version':'v1',
                                            'explanation':'Missing claim details.'},
                                'next_action':{'owner':'Claimant','message':'Send the quote.'}}}
            route.fulfill(json=data)
        self.page.route('**/api/evidence/reviewer',fake_result)
        self.page.get_by_text('Open submitted claim',exact=True).click()
        self.page.get_by_label('Claim reference').fill('CLM-TEST')
        self.page.get_by_label('Reviewer key').fill('test-only')
        self.page.get_by_role('button',name='Open claim').click()
        expect(self.page.get_by_text('garage.png',exact=True)).to_be_visible()
        expect(self.page.get_by_text('Send the quote.',exact=True)).to_be_visible()
        for text in ['Taken after pickup.', 'Capture date in file: 2025-10-12', 'Date given by claimant: 2025-10-13',
                     'Das Auto war geparkt.','The car was parked.','Confirmed by claimant']:
            expect(self.page.get_by_text(text,exact=True)).to_be_visible()
        self.assertEqual(requests,[{'reference':'CLM-TEST','reviewer_key':'test-only'}])
        self.page.reload()
        self.page.get_by_text('Open submitted claim',exact=True).click()
        expect(self.page.get_by_label('Reviewer key')).to_have_value('')

    def test_claimant_receipt_opens_prefilled_staff_lookup_without_sharing_access(self):
        token = token_hex(32)
        filed = self.page.request.post(urljoin(self.url, '/api/intakes/submit'), data={
            'token': token, 'expected_revision': 0, 'evidence_version': 1,
            'payload': claim(documents=[], demo_case='DEV-003')})
        self.assertTrue(filed.ok)
        ref = filed.json()['reference']
        self.page.goto(urljoin(self.url, '/chat#claim=' + token))
        handoff = self.page.get_by_role('link', name='Open reviewer evidence')
        expect(handoff).to_have_attribute('href', '/reviewer/evidence?reference=' + ref)
        requests = []
        self.page.on('request', lambda request: requests.append(request.url))
        handoff.click()
        expect(self.page).to_have_url(self.url + '?reference=' + ref)
        field = self.page.get_by_label('Claim reference')
        expect(field).to_be_visible()
        expect(field).to_have_value(ref)
        expect(self.page.get_by_label('Reviewer key')).to_have_value('')
        self.assertFalse(any('/api/evidence/reviewer' in url or token in url for url in requests))

    def test_unrecognized_reference_does_not_open_staff_lookup(self):
        self.page.goto(self.url + '?reference=CLM-incomplete')
        field = self.page.get_by_label('Claim reference')
        expect(field).to_be_hidden()
        expect(field).to_have_value('')
