"""Capability-protected claim drafts, submission receipts and additional uploads."""
import base64
from contextlib import closing
import hashlib
import json
import re
import sqlite3

from .intake import REQUIRED_DOCUMENTS, UUID_V4, _validate_document, validate_intake
from .store import RequestError, connect


FIELD_LIMITS = {'description': 2000, 'incident_date': 10, 'location': 160, 'policy_number': 80,
                'email': 254, 'injury_status': 7}
TOKEN = re.compile('[0-9a-f]{64}')


def _canonical(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(',', ':'))


def _key(token):
    if not isinstance(token, str) or not TOKEN.fullmatch(token):
        raise RequestError(400, 'Invalid private link.')
    return hashlib.sha256(token.encode('ascii')).digest()


def _revision(value):
    if type(value) is not int or not 0 <= value < 1_000_000_000:
        raise RequestError(400, 'A valid draft revision is required.')


def _documents(value, minimum=0):
    if not isinstance(value, list) or not minimum <= len(value) <= 3:
        raise RequestError(400, 'Choose up to three documents.')
    return [_validate_document(document) for document in value]


def _draft(draft):
    if not isinstance(draft, dict) or set(draft) != {'values', 'step', 'documents', 'sources'}:
        raise RequestError(400, 'Invalid draft.')
    values, sources, step = draft['values'], draft['sources'], draft['step']
    if type(step) is not int or not 0 <= step <= 16:
        raise RequestError(400, 'Invalid draft step.')
    if not isinstance(values, dict) or values.keys() - FIELD_LIMITS.keys():
        raise RequestError(400, 'Invalid draft fields.')
    for field, value in values.items():
        if (not isinstance(value, str) or len(value) > FIELD_LIMITS[field]
                or re.search(r'[\x00\ud800-\udfff]', value)):
            raise RequestError(400, 'Invalid draft field value.')
    if not isinstance(sources, dict) or sources.keys() - FIELD_LIMITS.keys():
        raise RequestError(400, 'Invalid draft sources.')
    for source in sources.values():
        if not isinstance(source, dict) or set(source) != {'name', 'page'}:
            raise RequestError(400, 'Invalid source citation.')
        name, page = source['name'], source['page']
        if (not isinstance(name, str) or not 1 <= len(name) <= 180
                or re.search(r'[/\\\x00-\x1f\x7f-\x9f\ud800-\udfff]', name)
                or type(page) is not int or not 1 <= page <= 1000):
            raise RequestError(400, 'Invalid source filename or page.')
    return dict(draft, documents=_documents(draft['documents']))


def initialize_intake_links(path):
    with closing(connect(path)) as db:
        db.executescript("""
            BEGIN;
            CREATE TABLE IF NOT EXISTS intake_links (
                token_hash BLOB PRIMARY KEY NOT NULL,
                revision INTEGER NOT NULL DEFAULT 0,
                draft TEXT,
                reference TEXT UNIQUE REFERENCES intake_submissions(reference),
                CHECK (reference IS NULL OR draft IS NULL)
            );
            CREATE TABLE IF NOT EXISTS intake_addition_requests (
                reference TEXT NOT NULL REFERENCES intake_submissions(reference),
                request_id TEXT NOT NULL,
                payload_hash TEXT NOT NULL,
                PRIMARY KEY (reference, request_id)
            );
            COMMIT;
        """)


def _rpc(store, action, token, data):
    result, _ = store._request('rpc/claim_intake_link',
                               body={'p_action': action, 'p_token': token, 'p_data': data})
    if not isinstance(result, dict) or result.get('status') not in ('submitted', 'draft'):
        raise RequestError(503, 'Could not confirm the claim link response. Please retry.')
    return result


def _row(db, key):
    return db.execute('SELECT * FROM intake_links WHERE token_hash=?', (key,)).fetchone()


def _start_write(db, key):
    db.execute('BEGIN IMMEDIATE')
    db.execute('INSERT INTO intake_links(token_hash) VALUES (?) ON CONFLICT DO NOTHING', (key,))
    return _row(db, key)


def _receipt(db, reference):
    documents = [dict(row) for row in db.execute(
        'SELECT kind, name FROM intake_documents WHERE reference=? ORDER BY position', (reference,))]
    present = {d['kind'] for d in documents}
    return {'status': 'submitted', 'reference': reference, 'document_count': len(documents),
            'documents': documents, 'missing_documents': [k for k in REQUIRED_DOCUMENTS if k not in present]}


def save_draft(store, token, draft, expected_revision):
    key = _key(token)
    _revision(expected_revision)
    draft = _draft(draft)
    if not isinstance(store, sqlite3.Connection):
        return _rpc(store, 'save', token, {'draft': draft, 'expected_revision': expected_revision})
    encoded = _canonical(draft)
    with store:
        row = _start_write(store, key)
        rev = row['revision']
        if row['reference'] is not None:
            raise RequestError(409, 'This claim has already been submitted.')
        if encoded == row['draft'] and expected_revision in (rev, rev - 1):
            return {'status': 'draft', 'revision': rev}
        if expected_revision != rev:
            raise RequestError(409, 'This draft changed. Reopen the private link.')
        store.execute('UPDATE intake_links SET revision=?, draft=? WHERE token_hash=?',
                      (rev + 1, encoded, key))
    return {'status': 'draft', 'revision': rev + 1}


def resolve_link(store, token):
    key = _key(token)
    if not isinstance(store, sqlite3.Connection):
        return _rpc(store, 'open', token, {})
    row = _row(store, key)
    if row is None:
        raise RequestError(404, 'Private link not found.')
    if row['reference']:
        return _receipt(store, row['reference'])
    return {'status': 'draft', 'revision': row['revision'], 'draft': json.loads(row['draft'])}


def submit_linked(store, token, payload, expected_revision=0):
    key = _key(token)
    _revision(expected_revision)
    normalized = validate_intake(payload)
    if not isinstance(store, sqlite3.Connection):
        return _rpc(store, 'submit', token, {'payload': normalized, 'expected_revision': expected_revision})

    from .intake import write_intake_sqlite
    with store:
        row = _start_write(store, key)
        packet = store.execute('SELECT reference FROM intake_submissions WHERE request_id=?',
                               (normalized['request_id'],)).fetchone()
        # Only the original token can ever bind or replay this particular submission.
        if (packet and packet['reference'] != row['reference']) or (row['reference'] and not packet):
            raise RequestError(409, 'This submission conflicts with the existing claim.')
        if not row['reference'] and expected_revision != row['revision']:
            raise RequestError(409, 'This draft changed. Reopen the private link.')
        reference = write_intake_sqlite(store, normalized)['reference']
        store.execute('UPDATE intake_links SET draft=NULL, reference=? WHERE token_hash=?', (reference, key))
        return _receipt(store, reference)


def append_documents(store, token, request_id, documents):
    key = _key(token)
    if not isinstance(request_id, str) or not UUID_V4.fullmatch(request_id):
        raise RequestError(400, 'Use a version 4 UUID for the upload request.')
    request_id = request_id.lower()
    documents = _documents(documents, minimum=1)
    if not isinstance(store, sqlite3.Connection):
        return _rpc(store, 'append', token, {'request_id': request_id, 'documents': documents})
    digest = hashlib.sha256(_canonical(documents).encode()).hexdigest()
    with store:
        store.execute('BEGIN IMMEDIATE')
        row = _row(store, key)
        if row is None:
            raise RequestError(404, 'Private link not found.')
        reference = row['reference']
        if not reference:
            raise RequestError(409, 'Submit the claim before adding follow-up documents.')
        prior = store.execute('SELECT payload_hash FROM intake_addition_requests WHERE reference=? AND request_id=?',
                              (reference, request_id)).fetchone()
        if prior:
            if prior['payload_hash'] != digest:
                raise RequestError(409, 'This upload request was already used for different files.')
            return _receipt(store, reference)
        receipt = _receipt(store, reference)
        kinds = [doc['kind'] for doc in documents]
        if len(kinds) != len(set(kinds)) or not set(kinds) <= set(receipt['missing_documents']):
            raise RequestError(409, 'Only one file per outstanding document type can be added. Reopen the link.')
        for position, doc in enumerate(documents, start=receipt['document_count']):
            store.execute('INSERT INTO intake_documents (reference,position,kind,name,content) VALUES (?,?,?,?,?)',
                          (reference, position, doc['kind'], doc['name'], base64.b64decode(doc['content_base64'])))
        store.execute('INSERT INTO intake_addition_requests VALUES (?,?,?)', (reference, request_id, digest))
        return _receipt(store, reference)
