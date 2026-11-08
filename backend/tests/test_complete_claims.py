"""A document-free draft is valid; a document-free submitted claim is not."""
from pathlib import Path
from secrets import token_hex
from tempfile import TemporaryDirectory
import unittest

from backend.intake import validate_submission
from backend.store import RequestError
from backend.tests.test_intake import claim, attachment
from backend.tests.test_reviewer import call, running_api


class CompleteClaimTests(unittest.TestCase):
    def test_both_required_types_are_checked_before_submission(self):
        report = attachment()
        quote = attachment('quote.pdf', 'itemized_quote')
        for documents in ([], [report], [quote], [attachment('photo.png', 'damage_photo', b'\x89PNG\r\n\x1a\nphoto')]):
            with self.subTest(types=[d['kind'] for d in documents]), self.assertRaises(RequestError) as caught:
                validate_submission(claim(documents=documents))
            self.assertEqual(caught.exception.status, 422)
            self.assertIn('save a draft', str(caught.exception).lower())
        self.assertEqual(len(validate_submission(claim(documents=[report, quote]))['documents']), 2)

    def test_all_public_submission_paths_refuse_missing_documents_and_drafts_resume(self):
        with TemporaryDirectory() as folder, running_api(Path(folder) / 'claims.sqlite3') as port:
            token = token_hex(32)
            incomplete = claim(documents=[])
            requests = [
                ('/api/intakes', incomplete),
                ('/api/intakes/submit', {'token': token, 'expected_revision': 0, 'payload': incomplete}),
                ('/api/intakes/submit', {'token': token, 'expected_revision': 0, 'evidence_version': 1, 'payload': incomplete}),
            ]
            for path, body in requests:
                code, out, _ = call(port, 'POST', path, body)
                self.assertEqual(code, 422, out)
            draft = {'values': {k: incomplete[k] for k in ('description', 'incident_date', 'location', 'policy_number', 'email', 'injury_status')}, 'documents': [], 'sources': {}, 'step': 6}
            code, saved, _ = call(port, 'POST', '/api/intakes/save-draft', {'token': token, 'expected_revision': 0, 'evidence_version': 1, 'draft': draft})
            self.assertEqual(code, 200, saved)
            code, reopened, _ = call(port, 'POST', '/api/intakes/resume', {'token': token, 'evidence_version': 1})
            self.assertEqual(code, 200, reopened)
            self.assertEqual(reopened['status'], 'draft')
            self.assertEqual(reopened['draft']['documents'], [])
            complete = claim(documents=[attachment(), attachment('quote.pdf', 'itemized_quote')])
            code, result, _ = call(port, 'POST', '/api/intakes/submit', {'token': token, 'expected_revision': saved['revision'], 'payload': complete})
            self.assertEqual(code, 200, result)
            self.assertEqual(result['missing_documents'], [])


if __name__ == '__main__':
    unittest.main()
