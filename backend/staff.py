"""Insurer-only inbox, original documents and audited intake decisions."""
import base64
from datetime import datetime
import hmac
import json

from .evidence_cases import _next_action, _public, _submitted_notes
from .intake import UUID_V4
from .staff_storage import read_staff
from .store import RequestError


def _reference(value):
    if not isinstance(value, str) or not value.startswith('CLM-') or not UUID_V4.fullmatch(value[4:]):
        raise RequestError(400, 'Enter a claim reference.')
    return value


def _authenticate(body, key):
    supplied = body.get('reviewer_key') if isinstance(body, dict) else None
    if not key or not isinstance(supplied, str) or not hmac.compare_digest(
        supplied.encode('utf-8', 'surrogatepass'), key.encode()
    ):
        raise RequestError(403, 'A valid staff access key is required.')


def _encode_cursor(row):
    data = json.dumps([row['submitted_at'], row['reference']], separators=(',', ':')).encode()
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode('ascii')


def _page(body):
    limit = body.get('limit', 25)
    if type(limit) is not int or not 1 <= limit <= 100:
        raise RequestError(400, 'Choose a page size between 1 and 100.')
    data = {'fetch_limit': limit + 1}
    cursor = body.get('cursor')
    if cursor is not None:
        try:
            if not isinstance(cursor, str) or len(cursor) > 256:
                raise ValueError
            raw = base64.b64decode(cursor + '=' * (-len(cursor) % 4), altchars=b'-_', validate=True)
            pair = json.loads(raw.decode('ascii'))
            if not isinstance(pair, list) or len(pair) != 2 or not all(isinstance(p, str) for p in pair):
                raise ValueError
            timestamp, ref = pair
            parsed = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
            if parsed.tzinfo is None or _encode_cursor({'submitted_at':timestamp,'reference':ref}) != cursor:
                raise ValueError
            data.update(before_time=timestamp, before_ref=_reference(ref))
        except (ValueError, RequestError):
            raise RequestError(400, 'Invalid inbox cursor.') from None
    return limit, data


def _summary(record):
    receipt = _public(record)
    decision = (record.get('state') or {}).get('decision') or {}
    latest = record.get('latest_correction') or {}
    size = receipt['document_count']
    machine = decision.get('recommendation')
    next_action = receipt.get('evidence', {}).get('next_action')
    if next_action is None:
        next_action = {'owner':'claims_team', 'message':'Review the submitted claim and its paperwork.'}
    return {
        'reference': record['reference'], 'submitted_at': record['submitted_at'], 'status': 'submitted',
        'claimant': record['claimant'], 'document_count': size, 'missing_documents': receipt['missing_documents'],
        'quote_versions': record['quote_versions'], 'next_action': next_action,
        'category': {
            'recommendation': machine,
            'effective_recommendation': latest['recommendation'] if latest.get('document_count') == size else machine,
            'policy_version': decision.get('policy_version') or latest.get('policy_version') or 'v1',
            'rule_id': decision.get('matched_rule'), 'revision': size + latest.get('ordinal', 0)
        }
    }


def staff_action(store, action, body, key):
    _authenticate(body, key)
    if action == 'inbox':
        limit, query = _page(body)
        records = read_staff(store, 'inbox', query)['records']
        return {'claims': [_summary(record) for record in records[:limit]],
                'next_cursor': _encode_cursor(records[limit - 1]) if len(records) > limit else None}
    ref = _reference(body.get('reference'))
    if action == 'document':
        position = body.get('position')
        if type(position) is not int or not 0 <= position < 40:
            raise RequestError(400, 'Invalid attachment position.')
        return read_staff(store, 'file', {'reference': ref, 'position': position})
    if action != 'reviewer':
        raise RequestError(404, 'Unknown staff read operation.')
    record = read_staff(store, 'detail', {'reference': ref})
    result = _summary(record)
    state = record.get('state')
    if state is None:
        evidence = {'decision':None, 'quotes':[], 'history':[], 'notes':{'photos':[], 'translations':[]},
                    'next_action':result['next_action']}
    else:
        evidence = {k: v for k, v in state.items() if k != 'facts'}
        evidence.update(next_action=_next_action(state), notes=_submitted_notes(state['notes']))
    return dict(result, evidence=evidence, documents=record['receipt']['documents'], corrections=record['corrections'],
                incident_date=record['claimant']['incident_date'])


def staff_correction(store, body, key):
    from .staff_corrections import save_staff_correction

    _authenticate(body, key)
    return save_staff_correction(store, _reference(body.get('reference')), body)
