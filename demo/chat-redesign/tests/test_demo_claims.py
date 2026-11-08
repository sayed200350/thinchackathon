"""The phone's fictional history persists without touching the live insurer store."""
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from uuid import uuid4

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE), str(HERE.parents[1])]
from demo_claims import PhoneDemoStore
from backend.store import RequestError


class DemoHistoryTests(unittest.TestCase):
    def test_seed_is_idempotent_and_submitted_claims_are_locked(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'phone-demo.sqlite3'
            demo = PhoneDemoStore(path)
            records = demo.records()['claims']
            self.assertEqual([c['status'] for c in records].count('submitted'), 3)
            self.assertEqual([c['status'] for c in records].count('draft'), 1)
            self.assertEqual(records, PhoneDemoStore(path).records()['claims'])
            for record in records[1:]:
                with self.assertRaises(RequestError) as caught:
                    demo.action('save-draft', {'token': record['token'], 'expected_revision': 0,
                        'draft': {'values':record['values'], 'documents':[], 'sources':{}, 'notes':{}, 'step':7}})
                self.assertEqual(caught.exception.status, 409)
                self.assertEqual(demo.action('resume', {'token':record['token']})['status'], 'submitted')

    def test_unfinished_claim_keeps_edits_and_cannot_send_without_quote(self):
        with TemporaryDirectory() as folder:
            demo = PhoneDemoStore(Path(folder) / 'phone-demo.sqlite3')
            record = next(c for c in demo.records()['claims'] if c['status']=='draft')
            token = record['token']
            original = demo.action('resume', {'token':token})
            draft = original['draft']
            self.assertEqual(record['missing_documents'], ['itemized_quote'])
            draft['values']['policy_number'] = 'DEMO-CORRECTED'
            saved = demo.action('save-draft', {'token':token, 'expected_revision':original['revision'], 'draft':draft})
            self.assertEqual(demo.action('resume', {'token':token})['draft']['values']['policy_number'], 'DEMO-CORRECTED')
            payload = dict(draft['values'], request_id=str(uuid4()), documents=draft['documents'], notes={})
            with self.assertRaises(RequestError) as caught:
                demo.action('submit', {'token':token, 'expected_revision':saved['revision'], 'payload':payload})
            self.assertEqual(caught.exception.status, 422)
            payload['documents'].append(demo.document('itemized_quote','quotes/itemized-890.pdf','quote.pdf'))
            receipt = demo.action('submit', {'token':token, 'expected_revision':saved['revision'], 'payload':payload})
            self.assertEqual(receipt['status'], 'submitted')
            self.assertEqual(receipt['missing_documents'], [])
            self.assertEqual([c['status'] for c in demo.records()['claims']].count('submitted'), 4)
            self.assertEqual(PhoneDemoStore(demo.path).records()['claims'][0]['status'], 'submitted')


if __name__ == '__main__':
    unittest.main()
