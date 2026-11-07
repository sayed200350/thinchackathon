"""Keyboard and original-file regressions for the claimant assistance widgets."""
import base64
import os
from pathlib import Path
import unittest

from backend.tests.test_claim_assistance import dated_photo

try:
    from playwright.sync_api import expect, sync_playwright
except ImportError:
    sync_playwright = None


@unittest.skipUnless(sync_playwright, 'Browser tests require Playwright and Chromium.')
class ClaimAssistanceBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        driver = sync_playwright().start()
        cls.addClassCleanup(driver.stop)
        cls.browser = driver.chromium.launch(executable_path=os.getenv('CLAIM_TEST_BROWSER'))
        cls.addClassCleanup(cls.browser.close)

    def setUp(self):
        self.page = self.browser.new_page(viewport={'width':390,'height':844})
        self.addCleanup(self.page.close)
        self.page.set_content('<main><section id="widget"></section></main>')
        self.page.add_script_tag(path=str(Path(__file__).resolve().parents[1]/'claim_assistance.js'))

    def test_photo_dates_preserve_both_origins_and_optional_explanation(self):
        raw = base64.b64encode(dated_photo() + bytes(3*1024**2)).decode()
        date = self.page.evaluate("""async (encoded) => {
          const bytes=Uint8Array.from(atob(encoded), c=>c.charCodeAt(0));
          const file=new File([bytes], 'damage.jpg', {type:'image/jpeg',lastModified:0});
          return ClaimAssistance.photoCaptureDate(file);
        }""", raw)
        self.assertEqual(date, '2025-10-19')
        self.page.evaluate("""d => ClaimAssistance.photoDetails(document.querySelector('#widget'),
              {name:'damage.jpg', assistance:{exif_date:d,view:'wide'}}, '2025-10-18', n=>window.saved=n)""",date)
        expect(self.page.get_by_text('2025-10-19',exact=True)).to_be_visible()
        expect(self.page.get_by_text('2025-10-18',exact=True)).to_be_visible()
        self.page.get_by_label('Explain the difference').fill('Photographed the next morning.')
        self.assertEqual(self.page.evaluate('saved.explanation'), 'Photographed the next morning.')
        self.assertEqual(self.page.evaluate('saved.exif_date'), '2025-10-19')

    def test_no_photo_metadata_and_guided_examples(self):
        self.page.evaluate("""() => {
          ClaimAssistance.photoGuide(document.querySelector('#widget'));
          ClaimAssistance.photoDetails(document.querySelector('#widget'),
              {name:'photo.png'}, '2025-10-18', n=>window.saved=n);
        }""")
        self.assertEqual(self.page.get_by_role('img').count(), 2)
        expect(self.page.locator('figcaption').get_by_text('Wide shot', exact=True)).to_be_visible()
        expect(self.page.get_by_label('Explain the difference')).to_be_hidden()
        self.page.get_by_label('Photo date supplied by you').fill('2025-10-20')
        self.page.get_by_label('Explain the difference').fill('Taken after repairs.')
        self.assertEqual(self.page.evaluate('saved.manual_date'), '2025-10-20')
        self.assertIsNone(self.page.evaluate('saved.exif_date'))
        self.page.get_by_label('Photo date supplied by you').fill('')
        self.assertEqual(self.page.evaluate('saved.manual_date'), '')

    def test_translation_requires_confirmation_again_after_edit_or_can_use_original(self):
        self.page.evaluate("""() => ClaimAssistance.translationReview(document.querySelector('#widget'),
            {original:'Mein Auto war geparkt.',english:'My car was parked.',page:2,
             confirmed:false,source:'local_model'}, n=>window.saved=n)""")
        expect(self.page.get_by_text('Mein Auto war geparkt.',exact=True)).to_be_visible()
        self.page.get_by_role('button',name='Confirm English translation').click()
        self.assertTrue(self.page.evaluate('saved.confirmed'))
        self.page.get_by_label('English translation',exact=True).fill('My vehicle was parked.')
        self.assertFalse(self.page.evaluate('saved.confirmed'))
        self.assertEqual(self.page.evaluate('saved.source'), 'manual')
        self.page.get_by_role('button',name='Continue with original German').click()
        self.assertTrue(self.page.evaluate('saved.use_original'))
        self.assertFalse(self.page.evaluate('saved.confirmed'))
