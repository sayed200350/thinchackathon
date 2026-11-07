"""Exercise the public claimant and protected reviewer entry points with one claim."""

import base64
from pathlib import Path
import secrets
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from backend.tests.test_intake import claim, attachment
from backend.tests.test_reviewer import call, running_api


class EvidenceCases(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        key = secrets.token_hex(32)
        self.reviewer = key
        settings = patch.dict('os.environ', {'CLAIM_REVIEWER_KEY': key})
        settings.start()
        self.addCleanup(settings.stop)
        server = running_api(Path(folder.name) / 'test.sqlite')
        self.port = server.__enter__()
        self.addCleanup(server.__exit__, None, None, None)
        self.token = secrets.token_hex(32)

    def post(self, path, body, status=200):
        code, out, _ = call(self.port, 'POST', '/api/' + path, body)
        self.assertEqual(code, status, out)
        return out

    def action(self, name, status=200, **data):
        return self.post('intakes/' + name, dict(token=self.token, evidence_version=1, **data), status)

    def file(self, name):
        fixture = Path(__file__).resolve().parents[1] / 'fixtures/quotes' / name
        return attachment(name, 'itemized_quote', fixture.read_bytes())

    def test_quote_versions_receipt_owner_reviewer_and_original_bytes(self):
        self.assertTrue((Path(__file__).resolve().parents[1] / 'fixtures/quotes/total-only-890.pdf').exists())
        first = self.file('total-only-890.pdf')
        body = claim(demo_case='DEV-003', injury_status='no', documents=[attachment(), first])
        out = self.action('submit', payload=body, expected_revision=0)
        self.assertEqual(out['evidence']['next_action']['owner'], 'garage')
        self.assertIn('itemized_quote', out['missing_documents'])
        self.assertEqual(out, self.action('submit', payload=body, expected_revision=0))
        ref = out['reference']
        self.post('evidence/reviewer', {'reference': ref, 'reviewer_key': 'bad'}, 403)
        self.post('evidence/document', {'reference': ref, 'position': 1, 'reviewer_key': self.token}, 403)
        for name, route in [
            ('itemized-890.pdf', 'routine_processing'),
            ('itemized-1800.pdf', 'human_review'),
            ('unreadable-total.pdf', 'request_information'),
        ]:
            doc = self.file(name)
            req = str(uuid4())
            out = self.action('add-documents', documents=[doc], request_id=req)
            self.assertEqual(out, self.action('add-documents', documents=[doc], request_id=req))
            self.assertEqual(out['evidence']['decision']['recommendation'], route)
        staff = self.post('evidence/reviewer', {'reference': ref, 'reviewer_key': self.reviewer})
        self.assertEqual(
            [r['decision']['recommendation'] for r in staff['evidence']['history']],
            ['request_information', 'routine_processing', 'human_review', 'request_information'],
        )
        self.assertEqual([q['version'] for q in staff['evidence']['quotes']], [1, 2, 3, 4])
        self.assertEqual(
            self.post('evidence/document', {'reference': ref, 'position': 1, 'reviewer_key': self.reviewer})[
                'content_base64'
            ],
            first['content_base64'],
        )
        self.assertEqual(len(staff['documents']), 5)

    def test_real_claim_does_not_inherit_sample_facts_or_leak_notes(self):
        doc = self.file('itemized-890.pdf')
        out = self.action(
            'submit', payload=claim(documents=[attachment(), doc], injury_status='no'), expected_revision=0
        )
        staff = self.post('evidence/reviewer', {'reference': out['reference'], 'reviewer_key': self.reviewer})
        self.assertNotEqual(staff['evidence']['decision']['recommendation'], 'routine_processing')
        self.assertNotIn('decision', out['evidence'])
        reopened = self.action('resume')
        self.assertNotIn('notes', reopened['evidence'])
        self.assertNotIn('content_base64', str(reopened))
        self.post('intakes/resume', {'token': secrets.token_hex(32), 'evidence_version': 1}, 404)
