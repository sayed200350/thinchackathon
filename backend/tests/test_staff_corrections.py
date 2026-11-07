"""Check revision safety and retry behavior across intake evidence and staff decisions."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import os
from pathlib import Path
import secrets
from tempfile import TemporaryDirectory
from threading import Barrier
import unittest
from uuid import uuid4

from backend import evidence_storage, staff_corrections
from backend.evidence_cases import claimant_action
from backend.intake import initialize_intakes, save_intake_sqlite, validate_intake
from backend.intake_links import initialize_intake_links
from backend.store import RequestError, connect
from backend.tests.test_evidence_postgres import PostgresTransport
from backend.tests.test_intake import attachment, claim


def correction(revision, route='human_review', **changes):
    return dict({'request_id': str(uuid4()), 'expected_revision': revision, 'policy_version': 'v1',
                 'recommendation': route, 'reason': 'The garage confirmed further damage.',
                 'reviewer': 'Demo reviewer'}, **changes)


class StaffCorrectionTests(unittest.TestCase):
    def setUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / 'claims.db'
        initialize_intakes(self.path)
        initialize_intake_links(self.path)
        evidence_storage.initialize(self.path)
        staff_corrections.initialize(self.path)
        self.db = connect(self.path)
        self.addCleanup(self.db.close)

    def test_legacy_claim_can_receive_its_first_manual_category(self):
        ref = save_intake_sqlite(self.db, validate_intake(claim(documents=[])))['reference']
        body = correction(0)
        status, result = staff_corrections.save_staff_correction(self.db, ref, body)
        self.assertEqual((status, result['revision'], result['reference']), (201, 1, ref))
        self.assertIsNone(result['correction']['previous_recommendation'])
        self.assertEqual(result['correction']['document_count'], 0)
        self.assertEqual(staff_corrections.save_staff_correction(self.db, ref, body), (200, result))
        with self.assertRaises(RequestError) as caught:
            staff_corrections.save_staff_correction(self.db, ref, dict(body, reason='A different reason'))
        self.assertEqual(caught.exception.status, 409)
        with self.assertRaises(RequestError) as caught:
            staff_corrections.save_staff_correction(self.db, ref, correction(1))
        self.assertEqual(caught.exception.status, 400)

    def test_competing_reviewers_cannot_overwrite_and_bad_values_do_not_write(self):
        ref = save_intake_sqlite(self.db, validate_intake(claim(documents=[])))['reference']
        for info, status in [(correction(0, reason='x' * 2001), 400), (correction(0, policy_version='v2'), 409)]:
            with self.subTest(info=info['policy_version']), self.assertRaises(RequestError) as caught:
                staff_corrections.save_staff_correction(self.db, ref, info)
            self.assertEqual(caught.exception.status, status)
        fence = Barrier(2)
        def review(route):
            with closing(connect(self.path)) as db:
                fence.wait(timeout=5)
                try:
                    return staff_corrections.save_staff_correction(db, ref, correction(0,route))[0]
                except RequestError as exc:
                    return exc.status
        with ThreadPoolExecutor(2) as workers:
            self.assertEqual(sorted(workers.map(review, ['human_review','routine_processing'])), [201,409])
        self.assertEqual(self.db.execute('select count(*) from intake_staff_corrections').fetchone()[0], 1)

    def test_new_evidence_expires_old_override_and_old_retry_keeps_history(self):
        verify_evidence_edits(self, self.db)


def verify_evidence_edits(test, store):
    private = secrets.token_hex(32)
    first = claimant_action(store, 'submit', {'token':private, 'expected_revision':0,
                            'payload':claim(documents=[], demo_case='DEV-003', injury_status='no')})
    ref = first['reference']
    body = correction(0)

    def save(values):
        return staff_corrections.save_staff_correction(store, ref, values)

    status, override = save(body)
    test.assertEqual((status, override['correction']['previous_recommendation']), (201, 'request_information'))
    fixture = Path(__file__).resolve().parents[1] / 'fixtures/quotes/itemized-890.pdf'
    doc = attachment(fixture.name, 'itemized_quote', fixture.read_bytes())
    receipt = claimant_action(store,'add-documents',{'token':private,'request_id':str(uuid4()),'documents':[doc]})
    test.assertEqual(receipt['evidence']['decision']['recommendation'], 'routine_processing')
    test.assertNotIn('correction', str(receipt))
    status, replay = save(body)
    test.assertEqual((status, replay['revision'], replay['correction']), (200, 2, override['correction']))
    with test.assertRaises(RequestError) as caught:
        save(correction(1, 'request_information'))
    test.assertEqual(caught.exception.status, 409)
    status, next_override = save(correction(2, 'request_information'))
    test.assertEqual((status, next_override['revision'], next_override['correction']['previous_recommendation']),
                     (201,3,'routine_processing'))


@unittest.skipUnless(os.getenv('CLAIM_TEST_PG_DSN'), 'Set a disposable PostgreSQL DSN with staff migrations.')
class HostedStaffCorrectionTests(unittest.TestCase):
    def test_hosted_stale_reviews_and_retries(self):
        verify_evidence_edits(self, PostgresTransport())

    def test_publishable_role_requires_separate_service_secret(self):
        with self.assertRaises(RequestError) as caught:
            PostgresTransport()._request('rpc/claim_staff_correct', max_response=65536,
                body={'p_service':'wrong-key','p_reference':'CLM-'+str(uuid4()),'p_data':correction(0)})
        self.assertEqual(caught.exception.status, 403)
