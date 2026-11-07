"""Verify the hosted storage contract without writing to the shared demo database."""

import json
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from backend.store import RequestError
from backend.supabase_store import SupabaseStore


URL = 'https://team.supabase.co'
KEY = 'sb_publishable_test'
SOURCE = {'case_id': 'DEV-001', 'case_status': 'open', 'claim_summary': 'Parking scrape', 'quote_eur': '650'}
DECISION = {'case_id': 'DEV-001', 'case_status': 'open', 'policy_version': 'v1', 'recommendation': 'routine_processing',
            'matched_rule': 'v1.3', 'supporting_facts': {'quote_eur': 650}, 'explanation': 'Documents complete.'}
CORRECTION = {'request_id': 'req-1', 'recommendation': 'human_review', 'reason': 'Look again.',
              'reviewer': 'Sayed', 'policy_version': 'v1', 'expected_revision': 0}


class Reply:
    def __init__(self, data, total=None, status=200):
        self.data, self.total, self.status = data, total, status

    def getheader(self, name, default):
        if name == 'Content-Range' and self.total is not None:
            return f'0-0/{self.total}' if self.total else '*/0'
        return default

    def read(self, size):
        return json.dumps(self.data).encode('utf-8')


class TestSupabaseStore(unittest.TestCase):
    def setUp(self):
        self.store = SupabaseStore(URL, KEY)
        transport = patch('backend.supabase_store.http.client.HTTPSConnection')
        self.connection = transport.start().return_value
        self.addCleanup(transport.stop)

    def get_queries(self):
        return [parse_qs(urlsplit(c.args[1]).query) for c in self.connection.request.call_args_list]

    def test_queue_uses_version_scoped_latest_revision_and_pages_by_key(self):
        self.connection.getresponse.side_effect = [
            Reply([{'case_id': 'DEV-001', 'case_status': 'open', 'recommendation': 'routine_processing',
                    'overrides': [{'revision': 7, 'corrected_recommendation': 'human_review'}]}], 2),
            Reply([{'case_id': 'DEV-002', 'case_status': 'open', 'recommendation': 'request_information',
                    'overrides': []}], 1),
        ]
        first, second = self.store.claim_list()['claims']
        self.assertEqual((first['recommendation'], first['effective_recommendation'], first['revision']),
                         ('routine_processing', 'human_review', 7))
        self.assertEqual((second['effective_recommendation'], second['revision']), ('request_information', 0))
        query, next_page = self.get_queries()
        self.assertEqual((query['policy_version'], query['overrides.order'], query['overrides.limit']),
                         (['eq.v1'], ['revision.desc'], ['1']))
        self.assertEqual(next_page['case_id'], ['gt.DEV-001'])
        self.assertEqual(self.connection.request.call_args.kwargs['headers']['apikey'], KEY)
        self.assertNotIn(KEY, self.connection.request.call_args.args[1])

    def test_audit_snapshot_includes_old_and_direct_inserts_and_preserves_engine(self):
        first = {'revision': 1, 'request_id': None, 'reviewer': 'Rafik', 'reason': 'Follow up', 'policy_version': 'v1',
                 'corrected_recommendation': 'human_review', 'created_at': '2026-11-07T14:00:00+00:00'}
        second = dict(first, revision=2, request_id='req-2', corrected_recommendation='routine_processing')
        self.connection.getresponse.side_effect = [Reply([{'source_fields': SOURCE}], 1),
            Reply([dict(DECISION, overrides=[{'revision': 2, 'corrected_recommendation': 'routine_processing'}])], 1),
            Reply([first], 2), Reply([second], 1)]
        detail = self.store.case_detail('DEV-001')
        self.assertEqual(detail['claim'], SOURCE)
        self.assertEqual(detail['decision'], DECISION)
        self.assertTrue(detail['history'][0]['created_at'].endswith('Z'))
        self.assertEqual((detail['effective_recommendation'], detail['revision']), ('routine_processing', 2))
        self.assertEqual([(row['previous_recommendation'], row['recommendation']) for row in detail['history']],
                         [('routine_processing', 'human_review'), ('human_review', 'routine_processing')])
        queries = self.get_queries()
        self.assertEqual(queries[-1]['revision'], ['gt.1'])
        self.assertEqual([q['and'] for q in queries[-2:]], [['(revision.lte.2)'], ['(revision.lte.2)']])

    def test_missing_case_and_snapshot(self):
        self.connection.getresponse.side_effect = [Reply([], 0), Reply([{'source_fields': SOURCE}], 1), Reply([], 0)]
        for status in (404, 503):
            with self.assertRaises(RequestError) as raised:
                self.store.case_detail('DEV-999&select=*')
            self.assertEqual(raised.exception.status, status)
        first = self.get_queries()[0]
        self.assertEqual(first['case_id'], ['eq.DEV-999&select=*'])
        self.assertEqual(first['select'], ['source_fields'])

    def test_atomic_write_and_idempotent_retry(self):
        self.connection.getresponse.side_effect = [Reply('created'), Reply('replayed')]
        with patch.object(self.store, 'case_detail', return_value={'revision': 1}):
            for expected_status in (201, 200):
                status, detail = self.store.save_correction('DEV-001', CORRECTION)
                self.assertEqual((status, detail['revision']), (expected_status, 1))
        for call in self.connection.request.call_args_list:
            self.assertEqual(call.args, ('POST', '/rest/v1/rpc/reviewer_save_correction'))
            self.assertEqual(json.loads(call.kwargs['body']),
                             {'p_case_id': 'DEV-001', **{'p_' + k: v for k, v in CORRECTION.items()}})

    def test_errors_fail_closed_and_no_automatic_write_retry(self):
        errors = [Reply({'code': 'PT409', 'message': 'Reload claim.'}, status=409),
                  Reply({'code': 'PGRST202', 'message': 'Missing function'}, status=404),
                  Reply({'code': '42501'}, status=403), Reply({}, status=302), TimeoutError()]
        self.connection.getresponse.side_effect = errors
        for status in (409, 503, 503, 503, 503):
            with self.assertRaises(RequestError) as raised:
                self.store.save_correction('DEV-001', CORRECTION)
            self.assertEqual(raised.exception.status, status)
        with self.assertRaises(RequestError) as raised:
            self.store.save_correction('DEV-001', dict(CORRECTION, expected_revision=True))
        self.assertEqual(raised.exception.status, 400)
        self.assertEqual(self.connection.request.call_count, 5)
        self.assertEqual(self.connection.close.call_count, 5)

    def test_preview_and_credential_scoping(self):
        self.connection.getresponse.return_value = Reply([{'case_id': 'DEV-001', 'case_status': 'open'},
                                                          {'case_id': 'PRA-009', 'case_status': 'closed'}], 2)
        self.assertEqual(self.store.preview(), {'status': 'awaiting_v2', 'from_version': 'v1', 'to_version': 'v2',
                                               'open_claims': 1, 'closed_claims': 1, 'changes': None})
        for url, key in [('http://example.com', KEY), ('https://x@example.com', KEY), (URL, 'sb_secret_test'),
                         (URL, 'header.eyJyb2xlIjoic2VydmljZV9yb2xlIn0.sig')]:
            with self.subTest(url=url), self.assertRaises(ValueError):
                SupabaseStore(url, key)


if __name__ == '__main__':
    unittest.main()
