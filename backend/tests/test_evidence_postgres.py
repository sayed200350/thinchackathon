"""Opt-in parity check on a disposable PostgreSQL database with all migrations applied."""

import json
import os
from pathlib import Path
import secrets
import subprocess
import unittest
from uuid import uuid4

from backend.evidence_cases import claimant_action, staff_action
from backend.tests.test_intake import attachment, claim


class PostgresTransport:
    def _request(self, resource, *, body, max_response):
        # Dollar-quoted JSON, with a fresh delimiter checked against the payload.
        encoded = json.dumps(body, ensure_ascii=True)
        tag = '$' + 'args' + secrets.token_hex(15) + '$'
        assert tag not in encoded and resource == 'rpc/claim_evidence_io'
        sql = (
            f'with args as (select {tag}{encoded}{tag}::jsonb x) select public.claim_evidence_io('
            "x->>'p_service',x->>'p_action',x->>'p_token',x->'p_data') from args;"
        )
        result = subprocess.run(
            ['psql', '-XAtq', '-v', 'ON_ERROR_STOP=1', os.environ['CLAIM_TEST_PG_DSN']],
            input='set role anon;\n' + sql,
            text=True,
            capture_output=True,
        )
        if result.returncode:
            raise RuntimeError(result.stderr.splitlines()[0])
        return json.loads(result.stdout), {}


@unittest.skipUnless(
    os.getenv('CLAIM_TEST_PG_DSN'), 'Set a disposable PostgreSQL DSN to run the migration integration.'
)
class HostedEvidenceTests(unittest.TestCase):
    def test_private_files_and_revision_chain(self):
        store = PostgresTransport()
        token = secrets.token_hex(32)
        fixtures = Path(__file__).resolve().parents[1] / 'fixtures/quotes'
        first = attachment('garage.pdf', 'itemized_quote', (fixtures / 'total-only-890.pdf').read_bytes())
        second = attachment('garage.pdf', 'itemized_quote', (fixtures / 'itemized-890.pdf').read_bytes())

        def action(name, **kwargs):
            return claimant_action(store, name, dict(token=token, **kwargs))

        d = {
            'step': 0,
            'values': {},
            'sources': {},
            'documents': [first],
            'notes': {},
            'demo_case': 'DEV-003',
        }
        self.assertEqual(action('save-draft', draft=d, expected_revision=0)['revision'], 1)
        self.assertEqual(action('resume')['draft']['documents'], [first])
        payload = claim(documents=[first], demo_case='DEV-003', injury_status='no')
        out = action('submit', payload=payload, expected_revision=1)
        self.assertEqual(out['evidence']['decision']['recommendation'], 'request_information')
        self.assertEqual(out, action('submit', payload=payload, expected_revision=1))
        req = str(uuid4())
        receipt = action('add-documents', documents=[second], request_id=req)
        self.assertEqual(receipt, action('add-documents', documents=[second], request_id=req))
        self.assertEqual(receipt['evidence']['decision']['recommendation'], 'routine_processing')
        staff = {'reference': out['reference'], 'reviewer_key': 'test-staff'}
        notes = staff_action(store, 'reviewer', staff, 'test-staff')
        self.assertEqual(len(notes['evidence']['history']), 2)
        self.assertEqual(
            staff_action(store, 'document', dict(staff, position=0), 'test-staff')['content_base64'],
            first['content_base64'],
        )
