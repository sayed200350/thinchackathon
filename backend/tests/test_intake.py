import base64
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import date, timedelta
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock
from uuid import uuid4

from backend.intake import (MAX_FILE_BYTES, initialize_intakes, save_intake_sqlite, save_intake_supabase,
                            validate_intake)
from backend.store import RequestError, connect


PDF = b'%PDF-1.4\nFictional incident report\n%%EOF'
PNG = b'\x89PNG\r\n\x1a\nDEMO'
JPEG = b'\xff\xd8\xff\xe0DEMO'


def attachment(name='report.pdf', kind='incident_report', content=PDF):
    return {'kind': kind, 'name': name, 'content_base64': base64.b64encode(content).decode('ascii')}


def claim(**changes):
    data = {'request_id': str(uuid4()), 'description': 'A parked car was scratched.',
            'incident_date': '2024-02-29', 'location': 'München', 'policy_number': ' P-123 ',
            'email': 'demo@example.org', 'injury_status': 'unknown',
            'documents': [attachment(), attachment('damage.JPEG', 'damage_photo', JPEG)]}
    data.update(changes)
    return data


class ValidationTests(unittest.TestCase):
    def test_enhanced_image_limits_cover_every_document_kind_and_keep_pdf_and_legacy_limits(self):
        max_photo = 12 * 1024 * 1024
        png = PNG.ljust(max_photo, b'p')
        jpeg = JPEG.ljust(MAX_FILE_BYTES + 1, b'j')
        for kind in ('damage_photo', 'itemized_quote', 'incident_report'):
            for name, content in (('scan.PNG', png), ('scan.JPEG', jpeg)):
                with self.subTest(kind=kind, name=name):
                    doc = attachment(name, kind, content)
                    packet = claim(documents=[doc])
                    self.assertTrue(validate_intake(packet, enhanced=True)['documents'] == [doc])
                    with self.assertRaises(RequestError):
                        validate_intake(packet)
        for name, content in (('over.png', png + b'!'), ('over.pdf', PDF.ljust(MAX_FILE_BYTES + 1, b'p'))):
            with self.subTest(name=name), self.assertRaises(RequestError):
                validate_intake(claim(documents=[attachment(name, 'itemized_quote', content)]), enhanced=True)

    def test_normalized_fields_and_supported_documents(self):
        original = claim(documents=[attachment(), attachment('quote.PNG', 'itemized_quote', PNG),
                                    attachment('damage.jpg', 'damage_photo', JPEG)])
        original['request_id'] = original['request_id'].upper()
        result = validate_intake(original)
        self.assertEqual((result['request_id'], result['policy_number']), (original['request_id'].lower(), 'P-123'))
        self.assertEqual(result['documents'], original['documents'])
        self.assertEqual(validate_intake(claim(documents=[]))['documents'], [])
        self.assertEqual(original['policy_number'], ' P-123 ')

    def test_reject_incomplete_or_invalid_details(self):
        for change in [{'request_id': 'not-a-uuid'}, {'request_id': '00000000-0000-0000-0000-000000000000'},
                       {'description': ' too short '}, {'description': 'x' * 2001},
                       {'incident_date': '2025-02-29'}, {'incident_date': '2024-2-29'},
                       {'incident_date': (date.today() + timedelta(days=2)).isoformat()}, {'email': 'no-domain'},
                       {'email': 'a@domain..test'}, {'location': '\x00'}, {'policy_number': '  '},
                       {'injury_status': []}, {'unexpected': 'field'}]:
            with self.subTest(field=list(change)), self.assertRaises(RequestError) as exc:
                validate_intake(claim(**change))
            self.assertEqual(exc.exception.status, 400)
        incomplete = claim()
        del incomplete['email']
        with self.assertRaises(RequestError):
            validate_intake(incomplete)

    def test_reject_bad_files_before_storage(self):
        docs = [attachment('../quote.pdf'), attachment('damage.png', content=PDF), attachment('note.txt'),
                attachment('quote.pdf', content=b''), attachment('quote.pdf', 'unrecognized'),
                attachment('long' * 46 + '.pdf'), dict(attachment(), content_base64='bad=invalid'),
                dict(attachment(), content_base64='JQ='), dict(attachment(), other='extra'),
                attachment('a\x01.pdf'), attachment(' a.pdf'), attachment('a.pdf '),
                attachment(content=PDF + b'x' * MAX_FILE_BYTES)]
        for doc in docs:
            with self.subTest(name=doc['name']), self.assertRaises(RequestError) as exc:
                validate_intake(claim(documents=[doc]))
            self.assertEqual(exc.exception.status, 400)
        for invalid in [None, {}, [attachment()] * 4]:
            with self.assertRaises(RequestError):
                validate_intake(claim(documents=invalid))

    def test_file_size_limit_accepts_exactly_two_mib(self):
        doc = attachment(content=PDF + b'x' * (MAX_FILE_BYTES - len(PDF)))
        self.assertEqual(validate_intake(claim(documents=[doc]))['documents'][0], doc)


class IntakeStorageTests(unittest.TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / 'intake.db'
        initialize_intakes(self.path)
        self.payload = validate_intake(claim())

    def save(self, payload):
        with closing(connect(self.path)) as db:
            return save_intake_sqlite(db, payload)

    def test_bytes_and_receipt_survive_restart_conflicting_replay_fails(self):
        receipt = self.save(self.payload)
        self.assertEqual(receipt['document_count'], 2)
        self.assertEqual(receipt['missing_documents'], ['itemized_quote'])
        self.assertTrue(receipt['reference'].startswith('CLM-'))
        self.assertNotIn(self.payload['request_id'], receipt['reference'])
        initialize_intakes(self.path)
        self.assertEqual(self.save(self.payload), receipt)
        with self.assertRaises(RequestError) as exc:
            self.save(dict(self.payload, documents=[attachment(content=PDF + b'updated')]))
        self.assertEqual(exc.exception.status, 409)
        with closing(connect(self.path)) as db:
            rows = db.execute('SELECT name, content FROM intake_documents WHERE reference = ? ORDER BY position',
                              (receipt['reference'],))
            self.assertEqual([tuple(row) for row in rows], [('report.pdf', PDF), ('damage.JPEG', JPEG)])
            self.assertEqual(db.execute('SELECT COUNT(*) FROM intake_submissions').fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT email FROM intake_submissions').fetchone()[0], self.payload['email'])

    def test_conflicting_writes_roll_back_all_files_and_submission(self):
        with closing(connect(self.path)) as db:
            db.execute("""CREATE TRIGGER test_abort BEFORE INSERT ON intake_documents WHEN NEW.position = 1
                          BEGIN SELECT RAISE(ABORT, 'fixture'); END""")
            with self.assertRaises(sqlite3.IntegrityError):
                save_intake_sqlite(db, self.payload)
            for table in ['intake_submissions', 'intake_documents']:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0], 0)

    def test_simultaneous_retries_create_one_submission(self):
        with ThreadPoolExecutor(max_workers=3) as threads:
            receipts = list(threads.map(self.save, [self.payload] * 3))
        self.assertEqual(receipts, [receipts[0]] * 3)
        with closing(connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM intake_documents').fetchone()[0], 2)

    def test_document_free_claim_can_be_received(self):
        receipt = self.save(dict(self.payload, documents=[]))
        self.assertEqual((receipt['document_count'], receipt['missing_documents']),
                         (0, ['incident_report', 'itemized_quote']))

    def test_hosted_rpc_receipt_is_verified(self):
        store = Mock()
        receipt = {'reference': 'CLM-' + str(uuid4()), 'document_count': 2, 'missing_documents': ['itemized_quote']}
        store._request.return_value = (receipt, None)
        self.assertEqual(save_intake_supabase(store, self.payload), receipt)
        store._request.assert_called_once_with('rpc/submit_claim_intake', body={'p_payload': self.payload})
        for malformed in [None, {'reference': ''}, dict(receipt, document_count=1),
                          dict(receipt, reference='CLM-x'), dict(receipt, claimant_email='demo@example.org')]:
            store._request.return_value = (malformed, None)
            with self.assertRaises(RequestError) as exc:
                save_intake_supabase(store, self.payload)
            self.assertEqual(exc.exception.status, 503)


if __name__ == '__main__':
    unittest.main()
