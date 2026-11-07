"""Evidence files and their derived history move together across SQLite clients."""
from pathlib import Path
from secrets import token_hex
from tempfile import TemporaryDirectory
import unittest
from uuid import uuid4

from backend import evidence_storage
from backend.evidence_cases import claimant_action
from backend.intake import initialize_intakes
from backend.intake_links import append_documents, initialize_intake_links, resolve_link, submit_linked
from backend.store import RequestError, connect, initialize
from backend.tests.test_intake import attachment, claim


class SQLiteEvidenceConsistencyTests(unittest.TestCase):
    def setUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        path = Path(folder.name) / 'claims.db'
        initialize(path, [])
        initialize_intakes(path)
        initialize_intake_links(path)
        evidence_storage.initialize(path)
        self.reader = connect(path)
        self.writer = connect(path)
        self.addCleanup(self.reader.close)
        self.addCleanup(self.writer.close)
        self.token = token_hex(32)

    def submit_with_history(self):
        receipt = claimant_action(self.writer, 'submit', {
            'token': self.token, 'expected_revision': 0, 'payload': claim(documents=[])})
        return receipt['reference']

    def test_legacy_upload_cannot_bypass_an_enhanced_claim_history(self):
        ref = self.submit_with_history()
        upload = str(uuid4())
        with self.assertRaises(RequestError) as caught:
            append_documents(self.writer, self.token, upload, [attachment()])
        self.assertEqual(caught.exception.status, 409)
        original = evidence_storage.exchange(self.reader, 'staff', '', {'reference': ref})
        self.assertEqual(original['receipt']['document_count'], 0)
        self.assertEqual(len(original['state']['history']), 1)

        # A rejected attempt must not reserve the request ID on the correct endpoint.
        receipt = claimant_action(self.writer, 'append', {
            'token': self.token, 'request_id': upload, 'documents': [attachment()]})
        self.assertEqual(receipt['document_count'], 1)
        current = evidence_storage.exchange(self.reader, 'staff', '', {'reference': ref})
        self.assertTrue(current['state']['facts']['incident_report_present'])
        self.assertEqual(len(current['state']['history']), 2)

    def test_evidence_write_against_legacy_claim_rolls_back_all_changes(self):
        submit_linked(self.writer, self.token, claim(documents=[]))
        upload = str(uuid4())
        with self.assertRaises(RequestError) as caught:
            evidence_storage.exchange(self.writer, 'append', self.token, {
                'request_id': upload, 'documents': [attachment()], 'state': {},
                'offset': 0, 'hash': '1' * 64})
        self.assertEqual(caught.exception.status, 409)
        self.assertEqual(resolve_link(self.reader, self.token)['document_count'], 0)
        self.assertEqual(append_documents(self.writer, self.token, upload, [attachment()])['document_count'], 1)

    def read_during_upload(self, read, upload):
        completed = []
        errors = []

        # Commit from another WAL connection after a link/history read and before the file list.
        # SQLite trace callbacks swallow exceptions, so surface any writer error here.
        def upload_while_reading(statement):
            if statement.startswith('SELECT kind, name FROM intake_documents') and not completed:
                try:
                    upload()
                    completed.append(True)
                except Exception as exc:
                    errors.append(exc)

        self.reader.set_trace_callback(upload_while_reading)
        try:
            snapshot = read()
        finally:
            self.reader.set_trace_callback(None)
        self.assertEqual(errors, [])
        self.assertEqual(completed, [True])
        return snapshot, read()

    def assert_consistent_read_during_upload(self, action):
        ref = self.submit_with_history()
        snapshot, following = self.read_during_upload(
            lambda: evidence_storage.exchange(self.reader, action, self.token, {'reference': ref}),
            lambda: claimant_action(self.writer, 'append', {
                'token': self.token, 'request_id': str(uuid4()), 'documents': [attachment()]}))
        for record, count in ((snapshot, 0), (following, 1)):
            self.assertEqual(record['receipt']['document_count'], count)
            self.assertEqual(record['state']['facts']['incident_report_present'], bool(count))

    def test_claimant_reads_a_single_snapshot_during_upload(self):
        self.assert_consistent_read_during_upload('open')

    def test_staff_reads_a_single_snapshot_during_upload(self):
        self.assert_consistent_read_during_upload('staff')

    def test_legacy_receipt_reads_a_single_snapshot_during_upload(self):
        submit_linked(self.writer, self.token, claim(documents=[]))
        snapshot, following = self.read_during_upload(
            lambda: resolve_link(self.reader, self.token),
            lambda: append_documents(self.writer, self.token, str(uuid4()), [attachment()]))
        self.assertEqual(snapshot['document_count'], 0)
        self.assertEqual(following['document_count'], 1)


if __name__ == '__main__':
    unittest.main()
