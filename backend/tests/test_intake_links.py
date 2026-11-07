"""Private link behavior with the offline store and hosted transport."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from secrets import token_hex
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock
from uuid import uuid4

from backend.intake import initialize_intakes, save_intake_sqlite, validate_intake
from backend.intake_links import append_documents, initialize_intake_links, resolve_link, save_draft, submit_linked
from backend.store import RequestError, connect
from backend.tests.test_intake import attachment, claim, PNG


def draft(photos=None):
    return {'values': {'description': 'Started'}, 'step': 0, 'documents': photos or [],
            'sources': {'description': {'name': 'report.pdf', 'page': 1}}}


class LinkTests(unittest.TestCase):
    def setUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / 'claims.db'
        initialize_intakes(self.path)
        initialize_intake_links(self.path)
        self.token = token_hex(32)
        self.db = connect(self.path)
        self.addCleanup(self.db.close)

    def fails(self, status, func, *args):
        with self.assertRaises(RequestError) as raised:
            func(*args)
        self.assertEqual(raised.exception.status, status)

    def test_draft_restores_private_bytes_and_refuses_stale_edits(self):
        packet = draft([attachment()])
        first = save_draft(self.db, self.token, packet, 0)
        self.assertEqual(first, {'status': 'draft', 'revision': 1})
        self.assertEqual(save_draft(self.db, self.token, packet, 0), first)
        with closing(connect(self.path)) as another:
            self.assertEqual(resolve_link(another, self.token), dict(first, draft=packet))
            updated = dict(packet, step=2)
            self.assertEqual(save_draft(another, self.token, updated, 1)['revision'], 2)
        self.fails(409, save_draft, self.db, self.token, dict(packet, step=3), 1)
        self.fails(409, submit_linked, self.db, self.token, claim(), 1)
        self.fails(404, resolve_link, self.db, token_hex(32))
        stored, = self.db.execute('SELECT token_hash FROM intake_links').fetchone()
        self.assertEqual(len(stored), 32)
        self.assertNotEqual(stored.hex(), self.token)
        for invalid in [dict(packet, step=True), dict(packet, values={'email':None}),
                        dict(packet, sources={'email': {'page':1, 'name':'../mail.pdf'}}),
                        dict(packet, extra=True), dict(packet, documents=[attachment()]*4)]:
            self.fails(400, save_draft, self.db, self.token, invalid, 2)

    def test_submit_wipes_draft_and_token_cannot_adopt_an_existing_packet(self):
        packet = claim()
        saved = save_draft(self.db, self.token, draft(), 0)
        receipt = submit_linked(self.db, self.token, packet, saved['revision'])
        self.assertEqual(set(receipt), {'status','reference','document_count','documents','missing_documents'})
        self.assertEqual(resolve_link(self.db, self.token), receipt)
        self.assertIsNone(self.db.execute('SELECT draft FROM intake_links').fetchone()[0])
        self.fails(409, save_draft, self.db, self.token, draft(), 1)
        self.fails(409, submit_linked, self.db, token_hex(32), packet, 0)
        self.fails(409, submit_linked, self.db, self.token, dict(packet, location='Elsewhere'), 1)
        self.fails(409, submit_linked, self.db, self.token, claim(), 1)
        old = claim()
        save_intake_sqlite(self.db, validate_intake(old))
        self.fails(409, submit_linked, self.db, token_hex(32), old, 0)
        self.fails(400, resolve_link, self.db, receipt['reference'])

    def test_initial_three_photos_still_allow_two_outstanding_files(self):
        photo = attachment('bumper.png','damage_photo',PNG)
        packet = claim(documents=[photo]*3)
        submit_linked(self.db,self.token,packet)
        extra = [attachment(), attachment('quote.pdf','itemized_quote')]
        request = str(uuid4())
        self.fails(409, append_documents, self.db, self.token, request, [extra[0]]*2)
        self.assertEqual(resolve_link(self.db,self.token)['document_count'],3)
        receipt = append_documents(self.db,self.token,request,extra)
        self.assertEqual((receipt['document_count'],receipt['missing_documents']), (5,[]))
        self.assertEqual(receipt['documents'][-1], {'kind':'itemized_quote','name':'quote.pdf'})
        self.assertEqual(append_documents(self.db,self.token,request,extra),receipt)
        self.assertEqual(submit_linked(self.db,self.token,packet),receipt)
        self.fails(409, append_documents, self.db, self.token, request, [extra[0]])
        self.fails(409, append_documents, self.db, self.token, str(uuid4()),[extra[1]])
        self.fails(404, append_documents, self.db, token_hex(32), str(uuid4()), extra)
        self.fails(400, append_documents, self.db, self.token, str(uuid4()), [])
        self.assertEqual(self.db.execute('SELECT count(*) FROM intake_documents').fetchone()[0],5)

    def test_competing_submission_and_addition_retries_write_under_one_token(self):
        packet = claim(documents=[])
        tokens = [self.token,token_hex(32)]
        def send(token):
            with closing(connect(self.path)) as db:
                try:
                    return submit_linked(db,token,packet)['reference']
                except RequestError as e:
                    return e.status
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(send,tokens))
        self.assertEqual(sum(isinstance(x,str) for x in results),1)
        winner = tokens[next(i for i,x in enumerate(results) if isinstance(x,str))]
        self.assertIn(409,results)
        addition_id = str(uuid4())
        def add(_):
            with closing(connect(self.path)) as db:
                return append_documents(db,winner,addition_id,[attachment()])
        with ThreadPoolExecutor(max_workers=2) as pool:
            first,second=pool.map(add,range(2))
        self.assertEqual(first, second)
        self.assertEqual(first['document_count'],1)

    def test_unknown_input_rejected_without_request_and_hosted_open_contract(self):
        hosted = Mock()
        self.fails(400, save_draft, hosted, self.token, draft(), True)
        self.fails(400, resolve_link, hosted, 'x')
        self.fails(400, submit_linked, hosted, self.token, {},0)
        hosted._request.assert_not_called()
        hosted._request.return_value = ({'status':'draft','draft':draft(),'revision':1},None)
        self.assertEqual(resolve_link(hosted,self.token)['draft'],draft())
        hosted._request.assert_called_once_with('rpc/claim_intake_link',
            body={'p_action':'open','p_token':self.token,'p_data':{}})
