"""Atomic evidence snapshots with append-only file bytes and idempotent upload requests."""

import base64
from contextlib import closing
import json
import os
import sqlite3

from .intake import write_intake_sqlite
from .intake_links import _key, _row, _receipt, _start_write, _canonical, _read_snapshot
from .store import RequestError, connect


def initialize(path):
    from . import staff_corrections
    staff_corrections.initialize(path)
    with closing(connect(path)) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS intake_evidence (
          reference TEXT PRIMARY KEY REFERENCES intake_submissions(reference),
          initial_hash TEXT NOT NULL, state TEXT NOT NULL)""")


def _record(db, ref):
    row = db.execute('SELECT state FROM intake_evidence WHERE reference=?', (ref,)).fetchone()
    return {'receipt': _receipt(db, ref), 'state': json.loads(row['state']) if row else None}


def _read(db, action, token, data):
    if action == 'open':
        link = _row(db, _key(token))
        if not link:
            raise RequestError(404, 'Private link not found.')
        if link['reference']:
            return _record(db, link['reference'])
        return {
            'receipt': {'status': 'draft', 'revision': link['revision'], 'draft': json.loads(link['draft'])}
        }
    ref = data['reference']
    if not db.execute('SELECT 1 FROM intake_evidence WHERE reference=?', (ref,)).fetchone():
        raise RequestError(404, 'Claim evidence not found.')
    if action == 'file':
        row = db.execute(
            'SELECT name,content FROM intake_documents WHERE reference=? AND position=?',
            (ref, data['position']),
        ).fetchone()
        if not row:
            raise RequestError(404, 'File not found.')
        return {'name': row['name'], 'content_base64': base64.b64encode(row['content']).decode()}
    incident = db.execute('SELECT incident_date FROM intake_submissions WHERE reference=?', (ref,)).fetchone()
    return dict(_record(db, ref), incident_date=incident['incident_date'])


def exchange(store, action, token, data):
    if not isinstance(store, sqlite3.Connection):
        key = os.getenv('CLAIM_EVIDENCE_SERVICE_KEY')
        if not key:
            raise RequestError(503, 'The private evidence store has not been configured.')
        out, _ = store._request(
            'rpc/claim_evidence_io',
            body={'p_service': key, 'p_action': action, 'p_token': token, 'p_data': data},
            max_response=66 * 1024 * 1024,
        )
        if not isinstance(out, dict):
            raise RequestError(503, 'Could not confirm the private evidence operation.')
        return out
    db = store
    if action in ('staff', 'file', 'open'):
        with _read_snapshot(db):
            return _read(db, action, token, data)
    key = _key(token)
    with db:
        link = _start_write(db, key)
        ref = link['reference']
        if action == 'save':
            encoded = _canonical(data['draft'])
            revision = link['revision']
            if ref:
                raise RequestError(409, 'The claim has already been submitted.')
            if encoded == link['draft'] and data['revision'] in (revision, revision - 1):
                return {'receipt': {'status': 'draft', 'revision': revision}}
            if revision != data['revision']:
                raise RequestError(409, 'This draft changed. Reopen the private link.')
            db.execute(
                'UPDATE intake_links SET revision=revision+1,draft=? WHERE token_hash=?', (encoded, key)
            )
            return {'receipt': {'status': 'draft', 'revision': revision + 1}}
        if action == 'submit':
            packet = data['payload']
            existing = db.execute(
                'SELECT reference FROM intake_submissions WHERE request_id=?', (packet['request_id'],)
            ).fetchone()
            if existing or ref:
                if existing and existing[0] == ref:
                    match = db.execute(
                        'SELECT 1 FROM intake_evidence WHERE reference=? AND initial_hash=?',
                        (ref, data['hash']),
                    ).fetchone()
                    if match:
                        return _record(db, ref)
                raise RequestError(409, 'This submission conflicts with an existing claim.')
            if data['revision'] != link['revision']:
                raise RequestError(409, 'This draft changed. Reopen the private link.')
            ref = write_intake_sqlite(db, packet, data['reference'])['reference']
            db.execute(
                'INSERT INTO intake_evidence VALUES(?,?,?)', (ref, data['hash'], _canonical(data['state']))
            )
            db.execute('UPDATE intake_links SET reference=?,draft=NULL WHERE token_hash=?', (ref, key))
            return _record(db, ref)
        if not ref:
            raise RequestError(409, 'Submit the claim before adding paperwork.')
        prior = db.execute(
            'SELECT payload_hash FROM intake_addition_requests WHERE reference=? AND request_id=?',
            (ref, data['request_id']),
        ).fetchone()
        if prior:
            if prior[0] != data['hash']:
                raise RequestError(409, 'This request was used for different files.')
            return _record(db, ref)
        receipt = _receipt(db, ref)
        docs = data['documents']
        if data['offset'] != receipt['document_count']:
            raise RequestError(409, 'The receipt changed. Reopen it before adding paperwork.')
        if data['offset'] + len(docs) > 40:
            raise RequestError(400, 'The claim already contains the maximum number of evidence files.')
        if (
            any(d['kind'] == 'incident_report' for d in docs)
            and 'incident_report' not in receipt['missing_documents']
        ):
            raise RequestError(409, 'The incident report has already been received.')
        updated = db.execute(
            'UPDATE intake_evidence SET state=? WHERE reference=?', (_canonical(data['state']), ref)
        )
        if updated.rowcount != 1:
            raise RequestError(409, 'No evidence history found.')
        for pos, doc in enumerate(docs, data['offset']):
            db.execute(
                'INSERT INTO intake_documents VALUES(?,?,?,?,?)',
                (ref, pos, doc['kind'], doc['name'], base64.b64decode(doc['content_base64'])),
            )
        db.execute(
            'INSERT INTO intake_addition_requests VALUES(?,?,?)', (ref, data['request_id'], data['hash'])
        )
        return _record(db, ref)
