"""Follow one synthetic claim from the claimant chatbot to the insurer's recorded decision."""
from contextlib import ExitStack, contextmanager
import os
from pathlib import Path
import secrets
import selectors
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from uuid import uuid4

from backend.tests.test_intake import claim
from backend.tests.test_reviewer import call

try:
    from playwright.sync_api import expect, sync_playwright
except ImportError:
    sync_playwright = None


ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / 'backend/fixtures'


@contextmanager
def service(module, folder, key, *args):
    command = [sys.executable, '-m', module, '--port', '0', '--env-file', str(folder / 'empty.env'), *args]
    env = dict(os.environ, CLAIM_REVIEWER_KEY=key, ELEVENLABS_AGENT_ID='', GARAGE_PUBLIC_ORIGIN='')
    with subprocess.Popen(command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          env=env, text=True) as process:
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                if not selector.select(15):
                    raise RuntimeError(f'{module} did not start in time')
                line = process.stdout.readline()
                if not line:
                    raise RuntimeError(process.stderr.read())
            yield int(line.strip().rsplit(':', 1)[1])
        finally:
            process.terminate()
            process.communicate(timeout=5)


@unittest.skipUnless(sync_playwright, 'Requires Playwright and Chromium')
class InsurerQueueUITests(unittest.TestCase):
    def setUp(self):
        stack = ExitStack()
        self.addCleanup(stack.close)
        folder = Path(stack.enter_context(TemporaryDirectory()))
        (folder / 'empty.env').touch()
        self.key = secrets.token_hex(32)
        self.intake = stack.enter_context(service('backend', folder, self.key, '--db', str(folder / 'intake.db'),
                                                  '--claims', str(ROOT / 'engine/tests/fixtures/synthetic_claims.csv')))
        port = stack.enter_context(service('backend.workbench_server', folder, self.key, '--db', str(folder / 'workbench.db'),
                                           '--intake-port', str(self.intake)))
        self.workbench = f'http://127.0.0.1:{port}'
        driver = stack.enter_context(sync_playwright())
        browser = driver.chromium.launch(executable_path=os.getenv('CLAIM_TEST_BROWSER'))
        stack.callback(browser.close)
        self.page = browser.new_page()

    def test_chatbot_quote_matches_workbench_and_original_download(self):
        page = self.page
        page.goto(f'http://127.0.0.1:{self.intake}/chat')
        page.get_by_role('button', name='Tell me what happened').click()
        for answer in ['A van scraped my parked car.', '2025-10-18', 'Demo car park',
                       'MOTOR-123', 'demo@example.invalid']:
            page.locator('#answer').fill(answer)
            page.get_by_role('button', name='Continue', exact=True).click()
        page.get_by_role('button', name='No', exact=True).click()
        quote = FIXTURES / 'quotes/itemized-1800.pdf'
        page.get_by_label('Paperwork type').select_option('itemized_quote')
        page.locator('#doc-files').set_input_files(quote)
        page.get_by_role('button', name='Review claim', exact=True).click()
        with page.expect_response('**/api/intakes/submit') as submission:
            page.get_by_role('button', name='Submit claim', exact=True).click()
        reference = submission.value.json()['reference']
        expect(page.get_by_role('heading', name='Claim received', exact=True)).to_be_visible()

        # Run the same submitted facts through the independent workbench entry point.
        status, saved, _ = call(self.intake, 'POST', '/api/evidence/reviewer',
                                {'reference': reference, 'reviewer_key': self.key})
        self.assertEqual(status, 200)
        recorded = saved['evidence']['decision']
        result = page.request.post(self.workbench + '/api/workbench/run', data={'claims': [recorded['raw_evidence']]})
        self.assertTrue(result.ok, result.text())
        decision, = result.json()['decisions']
        self.assertEqual(decision['recommendation'], 'human_review')
        self.assertEqual(decision['primary_rule_id'], 'HR_QUOTE_LIMIT')
        for field in ('primary_rule_id', 'policy_version', 'recommendation', 'input_fingerprint'):
            self.assertEqual(decision[field], recorded[field])

        page.goto(self.workbench + '/incoming')
        row = page.get_by_role('row').filter(has_text=reference)
        expect(row).to_have_count(1)
        expect(row).to_contain_text('Human review')
        row.get_by_role('button', name=reference).click()
        expect(page.get_by_role('heading', name=reference)).to_be_visible()
        panel = page.get_by_role('article').filter(has=page.get_by_role('heading', name='Recorded engine decision'))
        for text in ('Human review', '€1,800', decision['primary_rule_id'], decision['policy_version'],
                     decision['audit']['detail']['employee']['why']):
            expect(panel).to_contain_text(text)
        access, _, _ = call(self.intake, 'POST', '/api/staff/policy-replay', {'reference': reference})
        self.assertEqual(access, 403)
        args = {'reference': reference, 'expected_revision': saved['category']['revision'], 'target_version': 'v2'}
        status, replay, _ = call(self.intake, 'POST', '/api/staff/policy-replay', dict(args, reviewer_key=self.key))
        self.assertEqual(status, 200)
        page.get_by_role('button', name='Compare recorded V1 with V2').click()
        for item in (replay['recorded'], replay['proposed']):
            expect(page.locator('#versions-result')).to_contain_text(item['why'])
        page.get_by_text('Simulate a different quote limit', exact=True).click()
        page.get_by_role('button', name='Replay this claim').click()
        expect(page.locator('#comparison')).to_contain_text('HR_QUOTE_LIMIT')
        expect(page.locator('#comparison')).to_contain_text('Simulated policy')
        expect(panel).to_contain_text('Human review')
        with page.expect_download() as downloaded:
            page.get_by_role('button', name='Download ' + quote.name).click()
        self.assertEqual(downloaded.value.suggested_filename, quote.name)
        self.assertEqual(Path(downloaded.value.path()).read_bytes(), quote.read_bytes())
        page.get_by_role('button', name='Back to claims queue').click()
        expect(row).to_have_count(1)

        correction = {'reference': reference, 'reviewer_key': self.key, 'request_id': str(uuid4()),
                      'policy_version': recorded['policy_version'], 'expected_revision': saved['category']['revision'],
                      'recommendation': 'request_information', 'reviewer': 'Demo reviewer',
                      'reason': 'Please confirm the repair address.'}
        self.assertEqual(call(self.intake, 'POST', '/api/staff/corrections', correction)[0], 201)
        page.get_by_role('button', name='Refresh inbox').click()
        expect(row).to_contain_text('Request information')
        row.get_by_role('button', name=reference).click()
        expect(panel).to_contain_text('Human review')
        history = page.get_by_role('article').filter(has=page.get_by_role('heading', name='Reviewer corrections'))
        expect(history).to_contain_text(correction['reason'])
        expect(history).to_contain_text('Demo reviewer')

    def test_exact_reference_outside_first_page_on_mobile(self):
        status, receipt, _ = call(self.intake, 'POST', '/api/intakes', claim())
        self.assertEqual(status, 200)
        for _ in range(25):
            self.assertEqual(call(self.intake, 'POST', '/api/intakes', claim())[0], 200)
        page = self.page
        page.set_viewport_size({'width': 390, 'height': 844})
        page.goto(self.workbench + '/incoming')
        expect(page.get_by_role('button', name='Load more claims')).to_be_visible()
        reference = receipt['reference']
        self.assertTrue(page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'))
        expect(page.get_by_role('button', name=reference)).to_have_count(0)
        page.get_by_label('Open by claim reference').fill(reference)
        page.get_by_role('button', name='Open claim', exact=True).click()
        expect(page.get_by_role('heading', name=reference)).to_be_visible()
        expect(page.get_by_text('No engine decision was recorded for this submission.')).to_be_visible()
        self.assertTrue(page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'))
        page.get_by_role('button', name='Back to claims queue').click()
        page.get_by_role('button', name='Load more claims').click()
        expect(page.get_by_role('button', name=reference)).to_have_count(1)
