"""Exercise the public claimant entry point against a real offline service."""
import base64
from contextlib import closing
from http.client import HTTPConnection
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from uuid import uuid4

from backend.tests.test_reviewer import call, running_api
from backend.tests.test_intake import attachment


class ClaimIntakeHTTPTests(unittest.TestCase):
    def test_confirm_retry_restart_and_private_queue(self):
        # The JSON file upload exceeds the standard 64 KiB reviewer request limit.
        content = b'%PDF-1.4\n' + b' ' * 70000 + b'\n%%EOF\n'
        submission = {
            'request_id': str(uuid4()), 'description': 'The parked car door was scraped.',
            'incident_date': '2025-01-01', 'location': 'Munich', 'policy_number': 'TEST-123',
            'email': 'claimant@example.invalid', 'injury_status': 'no',
            'documents': [{'kind': 'incident_report', 'name': 'incident.pdf',
                           'content_base64': base64.b64encode(content).decode('ascii')},
                          attachment('quote.pdf', 'itemized_quote')],
        }
        with TemporaryDirectory() as directory:
            db_path = Path(directory) / 'server.sqlite'
            with running_api(db_path) as port:
                for path in ('/', '/chat'):
                    with closing(HTTPConnection('127.0.0.1', port)) as http:
                        http.request('GET', path)
                        page = http.getresponse()
                        self.assertEqual(page.status, 200)
                        self.assertIn(b'/api/intakes', page.read())
                status, receipt, _ = call(port, 'POST', '/api/intakes', submission)
                self.assertEqual(status, 200, receipt)
                self.assertEqual(set(receipt), {'reference', 'document_count', 'missing_documents'})
                self.assertEqual(receipt['document_count'], 2)
                self.assertEqual(receipt['missing_documents'], [])
            with running_api(db_path) as port:
                self.assertEqual(call(port, 'POST', '/api/intakes', submission)[:2], (200, receipt))
                self.assertEqual(call(port, 'POST', '/api/intakes', dict(submission, location='Changed'))[0], 409)
                self.assertEqual(call(port, 'GET', '/api/intakes/' + receipt['reference'])[0], 404)
                self.assertEqual(call(port, 'GET', '/api/claims/' + receipt['reference'])[0], 404)
                self.assertEqual(len(call(port, 'GET', '/api/claims')[1]['claims']), 26)
