"""Verify insurer discovery through the HTTP API, including existing submissions."""
from contextlib import closing
from pathlib import Path
import secrets
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from uuid import uuid4

from backend.tests.test_intake import attachment, claim
from backend.tests.test_reviewer import call, running_api


class StaffInboxTests(unittest.TestCase):
    def setUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.db = Path(folder.name) / 'intakes.sqlite'
        self.key = secrets.token_hex(32)
        config = patch.dict('os.environ', {'CLAIM_REVIEWER_KEY': self.key})
        config.start()
        self.addCleanup(config.stop)
        process = running_api(self.db)
        self.port = process.__enter__()
        self.addCleanup(process.__exit__, None, None, None)

    def post(self, path, body, status=200):
        code, result, _ = call(self.port, 'POST', '/api/' + path, body)
        self.assertEqual(code, status, result)
        return result

    def staff(self, path='staff/inbox', **body):
        return self.post(path, dict(body, reviewer_key=self.key))

    def test_key_required_and_pagination_validated(self):
        for secret in (None, 'wrong', 27):
            self.post('staff/inbox', {'reviewer_key':secret, 'limit':-1}, 403)
        self.assertEqual(self.staff(), {'claims':[], 'next_cursor':None})
        for params in ({'limit':0}, {'limit':True}, {'limit':101}, {'cursor':'broken'}, {'cursor':{}},
                       {'cursor':'W10'}, {'cursor':'A'*700}):
            self.post('staff/inbox', dict(params, reviewer_key=self.key), 400)
        self.assertEqual(call(self.port,'GET','/api/staff/inbox')[0],404)

    def test_real_submissions_once_even_after_retries_and_new_evidence(self):
        token = secrets.token_hex(32)
        auth = {'token': token, 'evidence_version':1}
        draft = {'step':0, 'documents':[], 'values':{}, 'sources':{}}
        self.post('intakes/save-draft', dict(auth, expected_revision=0, draft=draft))
        self.assertEqual(self.staff()['claims'], [])
        body = dict(auth, expected_revision=1, payload=claim(documents=[attachment()]))
        receipt = self.post('intakes/submit',body)
        self.assertEqual(self.post('intakes/submit',body),receipt)
        ref = receipt['reference']
        row, = self.staff()['claims']
        self.assertEqual(row['reference'], ref)
        self.assertEqual(row['claimant']['policy_number'], 'P-123')
        self.assertEqual(row['missing_documents'], ['itemized_quote'])
        self.assertEqual(set(row), {'reference','submitted_at','status','claimant','document_count',
                                    'missing_documents','quote_versions','next_action','category'})
        quote = attachment('estimate.jpg','itemized_quote',b'\xff\xd8\xffexample')
        addition = dict(auth,request_id=str(uuid4()),documents=[quote])
        updated = self.post('intakes/add-documents', addition)
        self.post('intakes/add-documents', addition)
        latest, = self.staff()['claims']
        self.assertEqual((latest['document_count'],latest['quote_versions'],latest['missing_documents']), (2,1,[]))
        self.assertEqual(latest['submitted_at'], row['submitted_at'])
        self.assertEqual(latest['next_action'], updated['evidence']['next_action'])
        self.assertGreater(latest['category']['revision'], row['category']['revision'])
        detail=self.staff('evidence/reviewer',reference=ref)
        self.assertEqual((detail['category'],detail['claimant']), (latest['category'],latest['claimant']))
        self.assertEqual(latest['category']['rule_id'],detail['evidence']['decision']['matched_rule'])
        self.assertEqual(self.staff('evidence/document',reference=ref,position=1)['content_base64'],quote['content_base64'])
        self.assertNotIn('content_base64', str(latest))
        self.assertNotIn(token, str(latest))
        self.assertNotIn('category',updated)

    def test_time_ties_and_new_arrivals_between_pages_include_legacy_detail(self):
        refs = [self.post('intakes',claim())['reference'] for _ in range(3)]
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute("update intake_submissions set received_at='2025-09-11T10:00:00.000Z'")
        first=self.staff(limit=2)
        self.assertIsInstance(first['next_cursor'],str)
        self.post('intakes',claim())
        second=self.staff(limit=2,cursor=first['next_cursor'])
        self.assertIsNone(second['next_cursor'])
        rows=first['claims']+second['claims']
        self.assertEqual([r['reference'] for r in rows],sorted(refs,reverse=True))
        legacy=rows[0]
        self.assertIsNone(legacy['category']['recommendation'])
        detail=self.staff('evidence/reviewer',reference=legacy['reference'])
        self.assertIsNone(detail['evidence']['decision'])
        self.assertEqual(self.staff('evidence/document',reference=legacy['reference'],position=0)['name'],'report.pdf')

    def test_staff_only_correction_then_new_evidence(self):
        auth={'token':secrets.token_hex(32),'evidence_version':1}
        ref=self.post('intakes/submit',dict(auth,expected_revision=0,payload=claim(documents=[])))['reference']
        start,=self.staff()['claims']
        correction=dict(reference=ref, request_id=str(uuid4()), reason='Staff verified the incident facts.',
                        reviewer='Demo reviewer', recommendation='human_review', policy_version='v1',
                        expected_revision=start['category']['revision'])
        self.post('staff/corrections',correction,403)
        created=self.post('staff/corrections',dict(correction,reviewer_key=self.key),201)
        self.assertEqual(self.staff('staff/corrections',**correction),created)
        row,=self.staff()['claims']
        self.assertEqual(row['category']['effective_recommendation'],'human_review')
        self.assertEqual(row['category']['recommendation'],start['category']['recommendation'])
        self.assertEqual(row['category']['revision'],created['revision'])
        self.post('intakes/add-documents',dict(auth,documents=[attachment()],request_id=str(uuid4())))
        current,=self.staff()['claims']
        self.assertEqual(current['category']['effective_recommendation'],current['category']['recommendation'])
        details=self.staff('evidence/reviewer',reference=ref)
        self.assertEqual([e['request_id'] for e in details['corrections']],[correction['request_id']])
        self.post('staff/corrections',dict(correction,request_id=str(uuid4()),reviewer_key=self.key),409)
