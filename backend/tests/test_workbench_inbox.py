import copy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from backend.store import RequestError
from backend.workbench_inbox import incoming, replay
from backend.workbench_server import Handler
from engine import assess_v1
from engine.tests.synthetic import BASE


class WorkbenchInboxTests(unittest.TestCase):
    def setUp(self):
        evidence = dict(BASE, quote_eur='1800', policy_active_on_incident=None)
        self.saved = assess_v1(evidence)
        self.detail = {'reference': 'synthetic', 'category': {'revision': 3},
                       'evidence': {'decision': self.saved}}
        self.proposal = {'expected_revision': 3, 'quote_limit_eur': 2000}

    def test_replay_preserves_historical_evidence_and_explains_change(self):
        original = copy.deepcopy(self.detail)
        result = replay(self.detail, self.proposal)
        self.assertEqual(result['recorded']['rule'], 'HR_QUOTE_LIMIT')
        self.assertEqual(result['proposed']['recommendation'], 'request_information')
        self.assertIn('policy active', result['proposed']['why'].lower())
        self.assertEqual(result['recorded_limit_eur'], 1500)
        self.assertEqual(self.detail, original)

    def test_rejects_changed_revision_and_legacy_evidence(self):
        with self.assertRaises(RequestError) as context:
            replay(self.detail, dict(self.proposal, expected_revision=2))
        self.assertEqual(context.exception.status, 409)
        self.saved.pop('raw_evidence')
        with self.assertRaises(RequestError) as context:
            replay(self.detail, self.proposal)
        self.assertEqual(context.exception.status, 409)

    def test_rejects_invalid_or_unchanged_proposal(self):
        for limit in (True, 0, 1500, 1000001):
            with self.subTest(limit=limit), self.assertRaises(RequestError) as context:
                replay(self.detail, dict(self.proposal, quote_limit_eur=limit))
            self.assertEqual(context.exception.status, 400)

    def test_workbench_needs_a_server_credential_and_only_reads(self):
        for action in ('list', 'detail', 'document', 'replay'):
            with self.assertRaises(RequestError) as context:
                incoming(1, action, {'reviewer_key': 'browser-input'}, None)
            self.assertEqual(context.exception.status, 503)
        with self.assertRaises(RequestError) as context:
            incoming(1, 'corrections', {}, 'example')
        self.assertEqual(context.exception.status, 404)

    def test_inbox_supplies_only_the_server_key(self):
        with patch('backend.workbench_inbox.HTTPConnection') as connection:
            upstream = connection.return_value
            response = upstream.getresponse.return_value
            response.status = 200
            response.headers.get_content_type.return_value = 'application/json'
            response.read.return_value = b'{"claims":[],"next_cursor":null}'
            for body in ({}, {'reviewer_key': 'browser-input'}):
                result = incoming(8766, 'list', body, 'server-only')
                self.assertEqual(result['claims'], [])
                self.assertEqual(json.loads(upstream.request.call_args.args[2]), {'reviewer_key': 'server-only'})

    def test_credentialed_reads_require_the_workbench_origin_and_loopback_host(self):
        server = SimpleNamespace(server_port=8767, intake_port=8766, reviewer_key='server-only')
        handler = SimpleNamespace(server=server, path='/api/incoming/list', command='POST', read_json=Mock(return_value={}))
        with patch('backend.workbench_inbox.incoming', return_value={'claims': []}) as upstream:
            for host, origin in [('localhost:8767', 'https://example.org'), ('example.org:8767', 'http://example.org:8767'),
                                 ('127.0.0.1:8767', None)]:
                handler.headers = {'Host': host, 'Origin': origin}
                with self.assertRaises(RequestError) as error:
                    Handler.dispatch_request(handler)
                self.assertEqual(error.exception.status, 403)
            upstream.assert_not_called()
            handler.headers = {'Host': '127.0.0.1:8767', 'Origin': 'http://127.0.0.1:8767'}
            self.assertEqual(Handler.dispatch_request(handler), (200, {'claims': []}))
            upstream.assert_called_once_with(8766, 'list', {}, 'server-only')


class FullPolicyReplayTests(unittest.TestCase):
    def preview(self, **facts):
        from backend.intake_replay import replay_versions
        record = {**BASE, 'quote_eur': '1300', **facts}
        saved = assess_v1(record)
        detail = {'reference': saved['case_id'], 'category': {'revision': 1}, 'evidence': {'decision': saved}}
        return replay_versions(detail, {'target_version': 'v2', 'expected_revision': 1})

    def test_full_notice_covers_threshold_battery_and_closed_retention(self):
        for amount, repair, expected in [('1300', 'standard', 'HR_QUOTE_LIMIT'),
                                          ('900', 'ev_high_voltage_battery', 'HR_EV_BATTERY')]:
            result = self.preview(quote_eur=amount, repair_type=repair)
            self.assertEqual(result['recorded']['recommendation'], 'routine_processing')
            self.assertEqual(result['proposed']['rule'], expected)
            self.assertIn(expected, result['impacted_rules'])
            self.assertTrue(result['needs_recheck'])
        closed = self.preview(case_status='closed')
        self.assertTrue(closed['closed_retained'])
        self.assertFalse(closed['needs_recheck'])
        self.assertEqual(closed['proposed'], closed['recorded'])

    def test_rejects_stale_mismatched_or_unrecorded_evidence(self):
        from backend.intake_replay import replay_versions
        saved = assess_v1(dict(BASE, quote_eur='1300'))
        detail = {'reference': saved['case_id'], 'category': {'revision': 2}, 'evidence': {'decision': saved}}
        body = {'target_version': 'v2', 'expected_revision': 2}
        for change in ({'target_version': '../v1'}, {'expected_revision': 1}):
            with self.assertRaises(RequestError):
                replay_versions(detail, dict(body, **change))
        for key in ('input_fingerprint','policy_hash','case_id','primary_rule_id'):
            with self.subTest(key=key), self.assertRaises(RequestError):
                replay_versions(dict(detail, evidence={'decision': dict(saved, **{key: 'wrong'})}), body)
