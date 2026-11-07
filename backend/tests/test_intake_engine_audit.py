"""Verify the engine snapshots on a private submitted claim and each quote revision."""
from contextlib import closing
import json
from pathlib import Path
import secrets
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from uuid import uuid4

from backend import evidence_storage
from backend.evidence_cases import claimant_action
from backend.intake import initialize_intakes
from backend.intake_links import initialize_intake_links
from backend.staff import staff_action
from backend.store import connect
from backend.tests.test_intake import attachment, claim


class IntakeEngineAuditTests(unittest.TestCase):
    def setUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / 'evidence.sqlite3'
        initialize_intakes(self.path)
        initialize_intake_links(self.path)
        evidence_storage.initialize(self.path)
        self.token = secrets.token_hex(32)
        self.key = secrets.token_hex(32)

    def quote(self, filename):
        pdf = Path(__file__).resolve().parents[1] / 'fixtures/quotes' / filename
        return attachment(filename, 'itemized_quote', pdf.read_bytes())

    def act(self, action, **body):
        with closing(connect(self.path)) as db:
            return claimant_action(db, action, dict(token=self.token, **body))

    def detail(self, ref):
        with closing(connect(self.path)) as db:
            return staff_action(db, 'reviewer', {'reference': ref, 'reviewer_key': self.key}, self.key)

    def test_saved_quote_assessments_keep_rule_trace_and_employee_explanation_private(self):
        packet = claim(documents=[attachment(), self.quote('total-only-890.pdf')], injury_status='no')
        receipt = self.act('submit', expected_revision=0, payload=packet)
        ref = receipt['reference']
        self.assertEqual(self.act('submit', expected_revision=0, payload=packet), receipt)
        self.assertNotIn('decision', receipt['evidence'])
        initial = self.detail(ref)['evidence']['decision']
        self.assertEqual(initial['audit']['rule_id'], 'INFO_ITEMIZED_QUOTE_MISSING')
        self.assertTrue(initial['audit']['detail']['employee']['why'])
        self.assertTrue(initial['audit']['rule_evaluations'])

        change = {'request_id': str(uuid4()), 'documents': [self.quote('itemized-1800.pdf')]}
        updated = self.act('add-documents', **change)
        self.assertEqual(self.act('add-documents', **change), updated)
        self.assertEqual(self.act('resume'), updated)
        self.assertNotIn('decision', updated['evidence'])
        self.assertNotIn('rule_evaluations', json.dumps(updated))
        # Reading opens a new connection and must use the recorded decision.
        with patch('backend.evidence_cases.assess_v1', side_effect=AssertionError('unexpected replay')):
            staff = self.detail(ref)
        latest = staff['evidence']['decision']
        old, new = staff['evidence']['history']
        self.assertEqual(old['decision'], initial)
        self.assertEqual(new['decision'], latest)
        self.assertEqual([old['quote_version'], new['quote_version']], [1, 2])
        self.assertEqual(latest['audit']['rule_id'], 'HR_QUOTE_LIMIT')
        self.assertIn('1,800', latest['audit']['detail']['employee']['why'])
        self.assertNotEqual(latest['input_fingerprint'], initial['input_fingerprint'])
        self.assertEqual(latest['policy_hash'], initial['policy_hash'])
        self.assertEqual(staff['category']['recommendation'], 'human_review')
        self.assertEqual(staff['document_count'], 3)

    def test_public_demo_summary_and_pre_merge_evidence_keep_the_original_contract(self):
        receipt = self.act('submit', expected_revision=0, payload=claim(
            demo_case='DEV-003', injury_status='no', documents=[self.quote('itemized-890.pdf')]))
        ref = receipt['reference']
        original = receipt['evidence']['decision']
        self.assertEqual(set(original), {'case_id','case_status','policy_version','recommendation',
                                         'matched_rule','supporting_facts','explanation'})
        self.assertEqual(original['matched_rule'], 'v1.3')
        # This is the actual record shape written before the engine stored audits.
        with closing(connect(self.path)) as db, db:
            state = json.loads(db.execute('SELECT state FROM intake_evidence WHERE reference=?', (ref,)).fetchone()[0])
            state['decision'] = original
            state['history'][-1]['decision'] = original
            db.execute('UPDATE intake_evidence SET state=? WHERE reference=?', (json.dumps(state), ref))
        self.assertEqual(self.detail(ref)['evidence']['decision'], original)
        self.assertEqual(self.act('resume')['evidence']['decision'], original)
        self.act('add-documents', request_id=str(uuid4()), documents=[self.quote('itemized-1800.pdf')])
        history = self.detail(ref)['evidence']['history']
        self.assertEqual(history[0]['decision'], original)
        self.assertEqual(history[1]['decision']['audit']['rule_id'], 'HR_QUOTE_LIMIT')
