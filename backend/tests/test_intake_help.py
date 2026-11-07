"""Browser regressions for keeping help questions out of a claimant's answers."""
from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
import os
import shutil
import unittest

from backend.tests.test_reviewer import running_api

try:
    from playwright.sync_api import expect, sync_playwright
except ImportError:
    sync_playwright = None


@unittest.skipUnless(sync_playwright, 'Browser tests require Playwright and Chromium.')
class IntakeHelpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        stack = ExitStack()
        cls.addClassCleanup(stack.close)
        folder = stack.enter_context(TemporaryDirectory())
        port = stack.enter_context(running_api(Path(folder) / 'claims.sqlite'))
        cls.url = f'http://127.0.0.1:{port}/chat'
        driver = stack.enter_context(sync_playwright())
        cls.browser = driver.chromium.launch(executable_path=os.getenv('CLAIM_TEST_BROWSER'))
        stack.callback(cls.browser.close)

    def setUp(self):
        self.page = self.browser.new_page(viewport={'width': 390, 'height': 844})
        self.addCleanup(self.page.close)
        self.page.goto(self.url)
        self.button('Tell me what happened').click()
        self.answer = self.page.locator('#answer')
        self.dialog = self.page.get_by_role('dialog')

    def button(self, name):
        return self.page.get_by_role('button', name=name, exact=True)

    def ask(self, question):
        self.button('Ask a question').click()
        self.dialog.get_by_label('Your question').fill(question)
        self.button('Ask').click()

    def test_question_in_answer_stays_off_draft_review_and_submission(self):
        detail = 'A van scraped my parked car.'
        question = 'Can I file this claim before I get a repair quote?'
        self.answer.fill(detail + ' ' + question + ' The repair shop is closed.')
        self.button('Continue').click()
        expect(self.dialog).to_contain_text('You can submit before')
        expect(self.button('Use this text as my claim answer')).to_have_count(0)
        self.button('Back to claim').click()
        expect(self.answer).to_be_focused()
        expect(self.answer).to_have_value(detail)
        with self.page.expect_response('**/api/intakes/save-draft') as saved:
            self.button('Save and continue later').click()
        self.assertEqual(saved.value.request.post_data_json['draft']['values']['description'], detail)
        self.page.reload()
        expect(self.answer).to_have_value(detail)
        for value in [detail, '2025-10-18', 'Demo car park', 'TEST-123', 'audit@example.invalid']:
            self.answer.fill(value)
            self.button('Continue').click()
        self.ask('Can I send the quote later?')
        self.button('Back to claim').click()
        self.button('I don’t know').click()
        self.button('Review claim').click()
        expect(self.page.get_by_text(detail, exact=True)).to_be_visible()
        expect(self.page.get_by_text(question, exact=True)).to_have_count(0)
        with self.page.expect_response('**/api/intakes/submit') as submitted:
            self.button('Submit claim').click()
        payload = submitted.value.request.post_data_json['payload']
        self.assertEqual(payload['description'], detail)
        self.assertNotIn(question, str(payload))
        self.ask('How do I add my missing quote?')
        expect(self.dialog).to_contain_text('Send additional documents')

    def test_explicit_help_preserves_unfinished_input_and_handles_unknowns(self):
        detail = 'The other driver asked, “Are you okay?”'
        self.answer.fill(detail)
        self.ask('Who paints the moon purple?')
        expect(self.dialog).to_contain_text('I can help with filing steps')
        self.page.keyboard.press('Escape')
        expect(self.answer).to_be_focused()
        expect(self.answer).to_have_value(detail)
        self.button('Continue').click()
        expect(self.page.get_by_role('heading', name='When did the incident happen?')).to_be_visible()

    @unittest.skipUnless(shutil.which('pdftotext'), 'PDF import suggestions require Poppler.')
    def test_help_during_pdf_review_keeps_unconfirmed_edits_and_attachment(self):
        self.page.goto(self.url)
        sample = Path(__file__).resolve().parents[1] / 'fixtures/sample-accident-report.pdf'
        with self.page.expect_file_chooser() as chooser:
            self.button('Choose a photo or PDF').click()
        chooser.value.set_files(sample)
        location = self.page.get_by_role('textbox', name='Incident location')
        location.fill('West entrance at the demo car park')
        self.ask('How do I correct an imported location?')
        expect(self.dialog).to_contain_text('correct imported details')
        self.button('Back to claim').click()
        expect(location).to_have_value('West entrance at the demo car park')
        description = self.page.get_by_role('textbox', name='What happened')
        imported = description.input_value()
        description.fill('Can I send the repair quote later?')
        self.button('Confirm details and continue').click()
        expect(self.dialog).to_contain_text('You can submit before')
        expect(self.button('Use this text as my claim answer')).to_have_count(0)
        self.button('Back to claim').click()
        expect(description).to_have_value(imported)
        expect(location).to_have_value('West entrance at the demo car park')
        self.button('Confirm details and continue').click()
        self.button('No').click()
        expect(self.page.get_by_text(sample.name, exact=True)).to_be_visible()

    def test_save_intercepts_standalone_question_and_edit_keeps_original(self):
        self.answer.fill('Can I send the estimate later')
        self.button('Save and continue later').click()
        expect(self.dialog).to_contain_text('private link')
        self.button('Back to claim').click()
        expect(self.answer).to_have_value('')
        self.assertEqual(self.page.url, self.url)
        self.answer.fill('Where can I park?')
        self.button('Continue').click()
        self.button('Use this text as my claim answer').click()
        expect(self.page.get_by_role('heading', name='When did the incident happen?')).to_be_visible()
        self.button('Back').click()
        self.answer.fill('Can I save my claim?')
        self.button('Continue').click()
        self.button('Back to claim').click()
        expect(self.answer).to_have_value('Where can I park?')
