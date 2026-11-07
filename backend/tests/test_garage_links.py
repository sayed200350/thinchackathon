"""A garage can contribute one original quote document to the requested revision."""

import base64
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime
import os
from pathlib import Path
from secrets import token_hex
import struct
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from uuid import uuid4
import zlib

from backend import evidence_storage, garage_links as garage
from backend.evidence_cases import claimant_action, staff_action
from backend.intake import initialize_intakes
from backend.intake_links import initialize_intake_links, submit_linked
from backend.store import RequestError, connect, initialize
from backend.tests.test_evidence_postgres import PostgresTransport
from backend.tests.test_intake import attachment, claim, PNG


def quote(filename):
    contents = (Path(__file__).resolve().parents[1] / 'fixtures' / 'quotes' / filename).read_bytes()
    return attachment(filename, 'itemized_quote', contents)


def original_png():
    # A real, decodable 1024x768 RGB image. Stored DEFLATE blocks keep it over 2 MiB.
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))
    header = struct.pack('>IIBBBBB', 1024, 768, 8, 2, 0, 0, 0)
    pixels = (b'\0' + b'\x18\x42\x63' * 1024) * 768
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', header) + chunk(b'IDAT', zlib.compress(pixels, 0)) + chunk(b'IEND', b'')


class GarageFlow:
    def setUp(self):
        self.secret = token_hex(32)
        self.claimant = token_hex(32)
        self.revised = quote('itemized-890.pdf')

    def submit(self, demo=True):
        packet = claim(injury_status='no', documents=[quote('total-only-890.pdf')])
        if demo:
            packet['demo_case'] = 'DEV-003'
        return claimant_action(
            self.db, 'submit', {'token': self.claimant, 'expected_revision': 0, 'payload': packet}
        )

    def test_only_one_original_and_one_history_event_across_reissued_links(self):
        receipt = self.submit()
        grant = garage.issue(self.db, self.claimant, self.secret)
        self.assertEqual(set(grant), {'token', 'expires_at'})
        token = grant['token']
        self.assertLessEqual(len(token), 150)
        self.assertNotIn(bytes.fromhex(self.claimant), base64.urlsafe_b64decode(token))
        second = garage.issue(self.db, self.claimant, self.secret)['token']
        self.assertEqual(garage.status(self.db, token, self.secret), {'status': 'open', 'demo': True})
        for link in (token, second):
            self.assertEqual(garage.upload(self.db, link, self.revised, self.secret), {'status': 'received'})
        self.assertEqual(garage.status(self.db, second, self.secret), {'status': 'received'})
        staff = {'reference': receipt['reference'], 'reviewer_key': self.secret}
        detail = staff_action(self.db, 'reviewer', staff, self.secret)
        self.assertEqual(len(detail['documents']), 2)
        self.assertEqual([q['version'] for q in detail['evidence']['quotes']], [1, 2])
        self.assertEqual(detail['evidence']['quotes'][-1]['source'], 'garage')
        resumed = claimant_action(self.db, 'resume', {'token': self.claimant})
        self.assertEqual(resumed['evidence']['quotes'][-1]['source'], 'garage')
        self.assertEqual(detail['evidence']['history'][-1]['source'], 'garage')
        self.assertEqual(detail['evidence']['decision']['recommendation'], 'routine_processing')
        original = staff_action(self.db, 'document', dict(staff, position=1), self.secret)
        self.assertEqual(original['content_base64'], self.revised['content_base64'])
        fresh = garage.issue(self.db, self.claimant, self.secret)['token']
        self.assertEqual(
            garage.upload(self.db, fresh, quote('itemized-1800.pdf'), self.secret), {'status': 'received'}
        )
        self.assertEqual(garage.upload(self.db, token, self.revised, self.secret), {'status': 'received'})

    def test_garage_photo_originals_reach_staff_byte_for_byte(self):
        receipt = self.submit()
        samples = [
            ('Werkstatt.PNG', original_png()),
            ('Werkstatt.jpeg', (Path(__file__).resolve().parents[1] / 'fixtures/photo-guide/close-up.jpg').read_bytes()),
        ]
        self.assertGreater(len(samples[0][1]), 2 * 1024 * 1024)
        staff = {'reference': receipt['reference'], 'reviewer_key': self.secret}
        for position, (filename, content) in enumerate(samples, start=1):
            with self.subTest(filename=filename):
                token = garage.issue(self.db, self.claimant, self.secret)['token']
                photo = attachment(filename, 'itemized_quote', content)
                self.assertEqual(garage.upload(self.db, token, photo, self.secret), {'status': 'received'})
                self.assertEqual(garage.upload(self.db, token, photo, self.secret), {'status': 'received'})
                evidence = staff_action(self.db, 'reviewer', staff, self.secret)['evidence']
                self.assertTrue(evidence['quotes'][-1]['review_required'])
                self.assertEqual(len(evidence['history']), position + 1)
                self.assertNotEqual(evidence['decision']['recommendation'], 'routine_processing')
                original = staff_action(self.db, 'document', dict(staff, position=position), self.secret)
                self.assertEqual(original['name'], filename)
                self.assertTrue(base64.b64decode(original['content_base64']) == content)


class SQLiteGarageTests(GarageFlow, unittest.TestCase):
    def setUp(self):
        super().setUp()
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / 'claims.sqlite'
        initialize(self.path, [])
        initialize_intakes(self.path)
        initialize_intake_links(self.path)
        evidence_storage.initialize(self.path)
        self.db = connect(self.path)
        self.addCleanup(self.db.close)

    def fails(self, status, operation, *args):
        with self.assertRaises(RequestError) as caught:
            operation(*args)
        self.assertEqual(caught.exception.status, status)

    def test_link_requires_submitted_enhanced_claim_and_cannot_be_used_as_claimant(self):
        self.fails(404, garage.issue, self.db, self.claimant, self.secret)
        body = {
            'token': self.claimant,
            'expected_revision': 0,
            'draft': {'values': {}, 'documents': [], 'step': 0, 'sources': {}},
        }
        claimant_action(self.db, 'save-draft', body)
        self.fails(409, garage.issue, self.db, self.claimant, self.secret)
        legacy = token_hex(32)
        submit_linked(self.db, legacy, claim(documents=[]))
        self.fails(409, garage.issue, self.db, legacy, self.secret)
        self.claimant = token_hex(32)
        self.submit(demo=False)
        token = garage.issue(self.db, self.claimant, self.secret)['token']
        self.assertEqual(garage.status(self.db, token, self.secret), {'status': 'open', 'demo': False})
        self.fails(400, claimant_action, self.db, 'resume', {'token': token})
        self.fails(400, garage.issue, self.db, token, self.secret)
        self.fails(403, garage.status, self.db, self.claimant, self.secret)
        self.fails(403, garage.status, self.db, token, token_hex(32))
        self.fails(403, garage.upload, self.db, token[:12] + '!' + token[13:], self.revised, self.secret)

    def test_expiry_matches_authenticated_issue_time_and_disallows_late_upload(self):
        self.submit()
        with patch('time.time', return_value=1_800_000_000):
            grant = garage.issue(self.db, self.claimant, self.secret)
        expiry = int(datetime.fromisoformat(grant['expires_at']).timestamp())
        self.assertEqual(expiry - 1_800_000_000, 7 * 24 * 60 * 60)
        with patch('time.time', return_value=expiry - 1):
            self.assertEqual(garage.status(self.db, grant['token'], self.secret)['status'], 'open')
        with patch('time.time', return_value=expiry):
            self.fails(403, garage.status, self.db, grant['token'], self.secret)
            self.fails(403, garage.upload, self.db, grant['token'], self.revised, self.secret)

    def test_invalid_quote_rejected_and_claimant_quote_closes_old_slot(self):
        self.submit()
        token = garage.issue(self.db, self.claimant, self.secret)['token']
        for doc in [
            attachment(),
            attachment('piece.jpeg', 'itemized_quote', PNG),
            dict(self.revised, role='garage'),
            dict(self.revised, kind=[]),
        ]:
            self.fails(400, garage.upload, self.db, token, doc, self.secret)
        claimant_action(
            self.db,
            'add-documents',
            {'token': self.claimant, 'request_id': str(uuid4()), 'documents': [self.revised]},
        )
        self.assertEqual(garage.status(self.db, token, self.secret), {'status': 'closed'})
        self.fails(409, garage.upload, self.db, token, self.revised, self.secret)
        self.assertEqual(self.db.execute('SELECT count(*) FROM intake_documents').fetchone()[0], 2)

    def test_parallel_remints_compete_for_one_slot_and_keep_intervening_report(self):
        self.submit(demo=False)
        tokens = [garage.issue(self.db, self.claimant, self.secret)['token'] for _ in range(2)]
        claimant_action(
            self.db,
            'add-documents',
            {'token': self.claimant, 'request_id': str(uuid4()), 'documents': [attachment()]},
        )

        def send(pair):
            link, doc = pair
            with closing(connect(self.path)) as db:
                try:
                    return garage.upload(db, link, doc, self.secret)['status']
                except RequestError as exc:
                    return exc.status

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(send, zip(tokens, [self.revised, quote('itemized-1800.pdf')])))
        self.assertCountEqual(results, ['received', 409])
        self.assertEqual(self.db.execute('SELECT count(*) FROM intake_documents').fetchone()[0], 3)
        self.assertEqual(
            [garage.status(self.db, link, self.secret) for link in tokens], [{'status': 'received'}] * 2
        )


@unittest.skipUnless(os.getenv('CLAIM_TEST_PG_DSN'), 'Requires disposable PostgreSQL with intake migrations')
class PostgresGarageTests(GarageFlow, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.db = PostgresTransport()
