"""Claimant journeys through the same HTTP endpoints used by the browser."""
import base64
from contextlib import closing
from http.client import HTTPConnection
from pathlib import Path
import secrets
from tempfile import TemporaryDirectory
import unittest
from uuid import uuid4

from backend.tests.test_reviewer import call, running_api


class DocumentFirstHTTPTests(unittest.TestCase):
    def test_sample_can_be_downloaded_and_imported_without_submitting(self):
        with TemporaryDirectory() as folder, running_api(Path(folder) / 'db') as port:
            with closing(HTTPConnection('127.0.0.1', port, timeout=10)) as http:
                http.request('GET', '/sample-accident-report.pdf')
                response = http.getresponse()
                data = response.read()
                self.assertEqual(response.status, 200)
                self.assertEqual(response.getheader('Content-Type'), 'application/pdf')
                self.assertIn('attachment', response.getheader('Content-Disposition'))
                self.assertTrue(data.startswith(b'%PDF-'))
            body = {'name': 'sample.pdf', 'content_base64': base64.b64encode(data).decode('ascii')}
            status, parsed, _ = call(port, 'POST', '/api/intakes/import-pdf', body)
            self.assertEqual(status, 200, parsed)
            self.assertIn('suggestions', parsed)
            self.assertNotIn('reference', parsed)
            self.assertNotIn('injury_status', {s['field'] for s in parsed['suggestions']})

    def test_private_draft_resumes_after_restart_and_receipt_accepts_a_missing_file(self):
        token = secrets.token_hex(32)
        values = {'description': 'A parked vehicle was scraped.', 'location': 'Munich',
                  'incident_date': '2024-01-01', 'policy_number': 'TEST-123',
                  'email': 'claimant@example.invalid'}
        report = {'kind': 'incident_report', 'name': 'report.pdf',
                  'content_base64': base64.b64encode(b'%PDF-1.4\nTest report\n%%EOF').decode('ascii')}
        draft = {'values': values, 'documents': [report], 'step': 5,
                 'sources': {'location': {'name': 'report.pdf', 'page': 1}}}
        with TemporaryDirectory() as folder:
            database = Path(folder) / 'db'
            with running_api(database) as port:
                status, saved, _ = call(port, 'POST', '/api/intakes/save-draft',
                                        {'token': token, 'expected_revision': 0, 'draft': draft})
                self.assertEqual(status, 200, saved)
                self.assertEqual(saved['status'], 'draft')
            with running_api(database) as port:
                def post(action, body):
                    return call(port, 'POST', '/api/intakes/' + action, body)[:2]

                status, resumed = post('resume', {'token': token})
                self.assertEqual(status, 200, resumed)
                self.assertEqual(resumed['draft'], draft)
                self.assertEqual(post('resume', {'token': secrets.token_hex(32)})[0], 404)
                payload = dict(values, injury_status='unknown', request_id=str(uuid4()), documents=[report])
                submit = {'token': token, 'expected_revision': saved['revision'], 'payload': payload}
                status, receipt = post('submit', submit)
                self.assertEqual(status, 200, receipt)
                self.assertEqual(receipt['missing_documents'], ['itemized_quote'])
                self.assertEqual(receipt['documents'], [{'kind': 'incident_report', 'name': 'report.pdf'}])
                quote = dict(report, kind='itemized_quote', name='quote.pdf')
                follow = {'token': token, 'request_id': str(uuid4()), 'documents': [quote]}
                status, updated = post('add-documents', follow)
                self.assertEqual(status, 200, updated)
                self.assertEqual(updated['missing_documents'], [])
                self.assertEqual(updated['document_count'], 2)
                self.assertEqual([d['name'] for d in updated['documents']], ['report.pdf', 'quote.pdf'])
                self.assertEqual(post('add-documents', follow), (200, updated))
                self.assertEqual(post('resume', {'token': token}), (200, updated))
                self.assertNotIn('draft', updated)
                self.assertNotIn('content_base64', str(updated))
                self.assertEqual(call(port, 'GET', '/api/claims/' + receipt['reference'])[0], 404)
