"""Public receipts and staff-only wording for real claimant submissions."""
from contextlib import ExitStack, closing
import json
from pathlib import Path
import secrets
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from backend.tests.test_intake import attachment, claim
from backend.tests.test_reviewer import call, running_api


class EvidencePriorityTests(unittest.TestCase):
    def setUp(self):
        resources = ExitStack()
        self.addCleanup(resources.close)
        folder = resources.enter_context(tempfile.TemporaryDirectory())
        self.db = Path(folder) / 'claims.sqlite'
        self.key = secrets.token_hex(32)
        resources.enter_context(patch.dict('os.environ', {'CLAIM_REVIEWER_KEY': self.key}))
        self.port = resources.enter_context(running_api(self.db))
        self.token = secrets.token_hex(32)

    def post(self, path, **body):
        code, result, _ = call(self.port, 'POST', '/api/' + path, body)
        self.assertEqual(code, 200, result)
        return result

    def action(self, action, **body):
        return self.post('intakes/' + action, token=self.token, evidence_version=1, **body)

    def submit(self, **fields):
        return self.action('submit', expected_revision=0, payload=claim(**fields))

    def review(self, receipt):
        return self.post('evidence/reviewer', reference=receipt['reference'], reviewer_key=self.key)['evidence']

    def test_injury_review_keeps_ownership_when_the_claimant_can_add_paperwork(self):
        receipt = self.submit(documents=[], injury_status='yes')
        self.assertEqual(receipt['missing_documents'], ['incident_report', 'itemized_quote'])
        self.assertEqual(self.review(receipt)['decision']['supporting_facts'], {'injury_reported': True})
        for submitted in (receipt, self.action('resume')):
            action = submitted['evidence']['next_action']
            self.assertEqual(action['owner'], 'claims_team')
            self.assertIn('review', action['message'])
            self.assertNotRegex(action['message'].lower(), r'approved|payout|settled|payment')
            self.assertNotIn('injury', json.dumps(submitted))
        quote = Path(__file__).resolve().parents[1] / 'fixtures/quotes/total-only-890.pdf'
        updated = self.action('add-documents', request_id=str(uuid4()), documents=[
            attachment(), attachment(quote.name, 'itemized_quote', quote.read_bytes())])
        self.assertEqual(updated['missing_documents'], ['itemized_quote'])
        self.assertEqual(updated['evidence']['next_action']['owner'], 'claims_team')

    def test_unknown_injury_requests_paperwork_without_claiming_human_review(self):
        receipt = self.submit(documents=[], injury_status='unknown')
        self.assertEqual(receipt['evidence']['next_action']['owner'], 'claimant')
        self.assertEqual(self.review(receipt)['decision']['recommendation'], 'request_information')

    def test_existing_receipts_derive_owner_from_the_recorded_decision(self):
        receipt = self.submit(documents=[], injury_status='yes')
        with closing(sqlite3.connect(self.db)) as db, db:
            state, = db.execute('SELECT state FROM intake_evidence WHERE reference=?', (receipt['reference'],)).fetchone()
            previous = json.loads(state)
            previous['next_action'] = {'owner': 'claimant', 'message': 'Please add the incident report using this link.'}
            db.execute('UPDATE intake_evidence SET state=? WHERE reference=?', (json.dumps(previous), receipt['reference']))
        self.assertEqual(self.action('resume')['evidence']['next_action']['owner'], 'claims_team')
        self.assertEqual(self.review(receipt)['next_action']['owner'], 'claims_team')

    def test_reviewer_sees_only_the_report_wording_the_claimant_selected(self):
        report = Path(__file__).resolve().parents[1] / 'fixtures/photo-guide/accident-report-de.pdf'
        original = 'Ein Lieferwagen streifte die linke hintere Tür meines geparkten Autos. Die Fahrertür blieb unbeschädigt.'
        candidate = 'A van scraped the left rear door of my parked car. The driver’s door was undamaged.'
        for confirmed in (True, False):
            with self.subTest(confirmed=confirmed):
                self.token = secrets.token_hex(32)
                note = {'position': 0, 'original': original, 'english': candidate, 'page': 1,
                        'source': 'manual', 'confirmed': confirmed, 'use_original': not confirmed}
                receipt = self.submit(documents=[attachment(report.name, content=report.read_bytes())],
                                      notes={'translations': [note]})
                saved, = self.review(receipt)['notes']['translations']
                self.assertEqual((saved['original'], saved['confirmed'], saved['use_original']),
                                 (original, confirmed, not confirmed))
                self.assertEqual(saved['english'], candidate if confirmed else '')
                self.assertNotIn(candidate, json.dumps(receipt))
