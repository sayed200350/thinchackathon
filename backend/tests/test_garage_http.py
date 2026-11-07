"""Two separate HTTP clients hand off a revised estimate on the same saved claim."""

from contextlib import ExitStack
from pathlib import Path
import secrets
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit
from urllib.request import urlopen

from backend.tests.test_reviewer import call, running_api
from backend.tests.test_intake import attachment, claim


class GarageHTTPTests(unittest.TestCase):
    def setUp(self):
        setup = ExitStack()
        self.addCleanup(setup.close)
        self.db = Path(setup.enter_context(tempfile.TemporaryDirectory())) / 'claim.db'
        self.token = secrets.token_hex(32)
        self.staff = secrets.token_hex(32)
        setup.enter_context(
            patch.dict(
                'os.environ',
                {
                    'GARAGE_PUBLIC_ORIGIN': 'https://garage.example.org',
                    'CLAIM_REVIEWER_KEY': self.staff,
                },
            )
        )
        self.port = setup.enter_context(running_api(self.db))

    def post(self, path, payload, expected=200):
        code, response, _ = call(self.port, 'POST', path, payload)
        self.assertEqual(code, expected, response.get('error'))
        return response

    def quote(self, filename):
        path = Path(__file__).resolve().parents[1] / 'fixtures/quotes' / filename
        return attachment(filename, 'itemized_quote', path.read_bytes())

    def test_phone_handoff_replays_only_one_revision_and_preserves_both_originals(self):
        first, revised = self.quote('total-only-890.pdf'), self.quote('itemized-890.pdf')
        receipt = self.post(
            '/api/intakes/submit',
            {
                'token': self.token,
                'evidence_version': 1,
                'expected_revision': 0,
                'payload': claim(documents=[first], injury_status='no', demo_case='DEV-003'),
            },
        )
        details = self.post('/api/intakes/garage-link', {'token': self.token})
        link = urlsplit(details['url'])
        self.assertEqual(
            (link.scheme, link.netloc, link.path, link.query), ('https', 'garage.example.org', '/garage', '')
        )
        self.assertTrue(link.fragment.startswith('upload='))
        token = link.fragment[len('upload=') :]
        self.assertNotIn(self.token, str(details))
        self.assertIn('<svg', details['qr_svg'])
        self.assertEqual(self.post('/api/garage/status', {'token': token}), {'status': 'open', 'demo': True})
        body = {'token': token, 'document': revised}
        for _ in range(2):
            self.assertEqual(self.post('/api/garage/upload', body), {'status': 'received'})
        self.assertEqual(self.post('/api/garage/status', {'token': token}), {'status': 'received'})
        current = self.post('/api/intakes/resume', {'token': self.token, 'evidence_version': 1})
        self.assertEqual(receipt['reference'], current['reference'])
        self.assertEqual(current['document_count'], 2)
        self.assertEqual(current['evidence']['quotes'][-1].get('source'), 'garage')
        self.assertNotIn('source', current['evidence']['quotes'][0])
        self.assertEqual(current['evidence']['decision']['recommendation'], 'routine_processing')
        staff = {'reference': receipt['reference'], 'reviewer_key': self.staff}
        history = self.post('/api/evidence/reviewer', staff)['evidence']['history']
        self.assertEqual(len(history), 2)
        self.assertEqual(history[1]['source'], 'garage')
        for position, original in enumerate([first, revised]):
            saved = self.post('/api/evidence/document', dict(staff, position=position))
            self.assertEqual(saved['content_base64'], original['content_base64'])

    def test_invalid_body_and_unknown_token_do_not_return_a_claim(self):
        self.post('/api/garage/status', [], 400)
        self.post('/api/garage/status', {'token': self.token}, 403)
        self.post('/api/garage/other', {'token': self.token}, 404)
        with urlopen(f'http://127.0.0.1:{self.port}/garage') as response:
            self.assertEqual(response.getheader('Referrer-Policy'), 'no-referrer')
            self.assertEqual(response.getheader('Cache-Control'), 'no-store')

    def test_missing_public_origin_does_not_offer_a_localhost_qr(self):
        with patch.dict('os.environ', {'GARAGE_PUBLIC_ORIGIN': ''}), running_api(self.db) as port:
            code, out, _ = call(port, 'POST', '/api/intakes/garage-link', {'token': self.token})
            self.assertEqual(code, 503, out)
            self.assertNotIn('url', out)
