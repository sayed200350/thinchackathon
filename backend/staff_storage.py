"""Private, paginated staff reads for submitted intake claims."""

import base64
import json
import os
import sqlite3

from .intake_links import _read_snapshot, _receipt
from .store import RequestError


CLAIMANT_FIELDS = ('policy_number', 'incident_date', 'location', 'description', 'email', 'injury_status')
CORRECTION_SUMMARY = 'ordinal, document_count, recommendation, policy_version'
CORRECTION_DETAIL = (CORRECTION_SUMMARY +
                     ', revision, request_id, reviewer, reason, previous_recommendation, created_at')


def _record(db, row, *, summary):
    ref = row['reference']
    receipt = _receipt(db, ref)
    state = json.loads(row['state']) if row['state'] is not None else None
    if summary and state is not None:
        state['quotes'] = [json.loads(row['latest_quote'])] if row['latest_quote'] else []
    count = row['quote_count'] if state is not None else sum(
        doc['kind'] == 'itemized_quote' for doc in receipt['documents'])
    result = {
        'reference': ref, 'submitted_at': row['received_at'],
        'claimant': {field: row[field] for field in CLAIMANT_FIELDS},
        'state': state, 'receipt': receipt, 'quote_versions': count,
    }
    if summary:
        latest = db.execute(f'SELECT {CORRECTION_SUMMARY} FROM intake_staff_corrections '
                            'WHERE reference=? ORDER BY ordinal DESC LIMIT 1', (ref,)).fetchone()
        result['latest_correction'] = dict(latest) if latest else None
    else:
        corrections = [dict(c) for c in db.execute(
            f'SELECT {CORRECTION_DETAIL} FROM intake_staff_corrections WHERE reference=? ORDER BY ordinal',
            (ref,))]
        result.update(latest_correction=corrections[-1] if corrections else None, corrections=corrections)
    return result


def _sqlite_read(db, action, data):
    if action == 'file':
        row = db.execute('SELECT name, content FROM intake_documents WHERE reference=? AND position=?',
                         (data['reference'], data['position'])).fetchone()
        if row is None:
            raise RequestError(404, 'File not found.')
        return {'name': row['name'], 'content_base64': base64.b64encode(row['content']).decode('ascii')}

    summary = action == 'inbox'
    state_columns = (
        "json_remove(e.state, '$.notes', '$.history', '$.quotes') AS state, "
        "json_remove(json_extract(e.state, '$.quotes[#-1]'), '$.lines') AS latest_quote"
        if summary else 'e.state AS state'
    )
    sql = (f"SELECT s.reference, s.received_at, {', '.join(CLAIMANT_FIELDS)}, {state_columns}, "
           "json_array_length(e.state, '$.quotes') AS quote_count FROM intake_submissions s "
           "LEFT JOIN intake_evidence e ON e.reference = s.reference")
    if not summary:
        row = db.execute(sql + ' WHERE s.reference=?', (data['reference'],)).fetchone()
        if row is None:
            raise RequestError(404, 'Submitted claim not found.')
        return _record(db, row, summary=False)

    params = []
    if data.get('before_time') is not None:
        sql += ' WHERE (s.received_at, s.reference) < (?, ?)'
        params.extend((data['before_time'], data['before_ref']))
    sql += ' ORDER BY s.received_at DESC, s.reference DESC LIMIT ?'
    rows = db.execute(sql, (*params, data['fetch_limit']))
    return {'records': [_record(db, row, summary=True) for row in rows]}


def read_staff(store, action, data):
    """Read on one database snapshot after the HTTP layer has authenticated staff."""
    if action not in ('inbox', 'detail', 'file'):
        raise RequestError(400, 'Unknown staff read operation.')
    if action == 'inbox':
        limit = data.get('fetch_limit')
        if type(limit) is not int or not 1 <= limit <= 101:
            raise RequestError(400, 'Invalid page size.')
        if (data.get('before_time') is None) != (data.get('before_ref') is None):
            raise RequestError(400, 'Invalid inbox cursor.')
    if isinstance(store, sqlite3.Connection):
        with _read_snapshot(store):
            return _sqlite_read(store, action, data)

    key = os.environ.get('CLAIM_EVIDENCE_SERVICE_KEY')
    if not key:
        raise RequestError(503, 'The private evidence store has not been configured.')
    out, _ = store._request('rpc/claim_staff_read',
                            body={'p_service': key, 'p_action': action, 'p_data': data},
                            max_response=32 * 1024 * 1024)
    if not isinstance(out, dict):
        raise RequestError(503, 'Invalid response from the private staff store.')
    return out
