"""Claimant actions and staff evidence projections; decisions always use the policy engine."""

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import hmac
import json
from uuid import uuid4

from engine.policy import decide
from .intake import UUID_V4, validate_intake
from .intake_links import _documents, _draft, _key, _revision, append_documents
from .quote_evidence import assess_quote, demo_facts
from .store import RequestError
from .evidence_storage import exchange


def digest(data):
    return hashlib.sha256(
        json.dumps(data, ensure_ascii=True, sort_keys=True, separators=(',', ':')).encode()
    ).hexdigest()


def _with_notes(packet, draft=False):
    if not isinstance(packet, dict):
        raise RequestError(400, 'Invalid claim packet.')
    base = {k: v for k, v in packet.items() if k not in ('notes', 'demo_case')}
    clean = _draft(base, enhanced=True) if draft else validate_intake(base, enhanced=True)
    if 'demo_case' in packet:
        if packet['demo_case'] != 'DEV-003':
            raise RequestError(400, 'Unknown fictional case.')
        clean['demo_case'] = 'DEV-003'
    clean['notes'] = _notes(packet.get('notes', {}), clean['documents'], draft)
    return clean


def _notes(notes, docs, draft):
    if not isinstance(notes, dict) or notes.keys() - {'photos', 'translations'}:
        raise RequestError(400, 'Invalid evidence notes.')
    result = {'photos': [], 'translations': []}
    for group, kind in [('photos', 'damage_photo'), ('translations', 'incident_report')]:
        entries = notes.get(group, [])
        if not isinstance(entries, list) or len(entries) > len(docs):
            raise RequestError(400, 'Invalid evidence positions.')
        mapped = {}
        for entry in entries:
            if not isinstance(entry, dict):
                raise RequestError(400, 'Invalid evidence note.')
            i = entry.get('position')
            if type(i) is not int or not 0 <= i < len(docs) or docs[i]['kind'] != kind or i in mapped:
                raise RequestError(400, 'Invalid evidence position.')
            mapped[i] = {k: v for k, v in entry.items() if k != 'position'}
        for i, doc in enumerate(docs):
            if doc['kind'] != kind or (group == 'translations' and i not in mapped):
                continue
            from .claim_assistance import clean_assistance

            raw = mapped.get(i, {})
            data = clean_assistance(dict(doc, assistance=raw if group == 'photos' else {'translation': raw}))
            note = data if group == 'photos' else data.get('translation')
            if note:
                if (
                    group == 'translations'
                    and not draft
                    and not (note.get('confirmed') or note.get('use_original'))
                ):
                    raise RequestError(400, 'Confirm the translation or remove it before submitting.')
                result[group].append(dict(note, position=i))
    return result


def _initial_state(ref, payload):
    demo = payload.get('demo_case')
    facts = dict(demo_facts()) if demo else {}
    facts.update(
        case_id=ref,
        case_status='open',
        injury_reported={'yes': True, 'no': False, 'unknown': None}[payload['injury_status']],
    )
    # Only the publicly labelled fixture has policy, repair and dispute facts on file.
    facts.update(quote_eur=None, itemized_quote_present=False, incident_report_present=bool(demo))
    return {
        'demo_case': demo,
        'facts': facts,
        'notes': {'photos': [], 'translations': []},
        'quotes': [],
        'history': [],
    }


def _submitted_notes(notes):
    # A claimant can keep editing both texts in a draft. Once they choose the
    # German original, the proposed English wording is outside their submission.
    return dict(
        notes,
        translations=[
            dict(entry, english='') if entry['use_original'] else entry for entry in notes['translations']
        ],
    )


def _next_action(state):
    latest = state['quotes'][-1] if state['quotes'] else {}
    if state['decision']['recommendation'] == 'human_review':
        owner, message = 'claims_team', 'The claims team will review your claim.'
    elif latest.get('review_required'):
        owner, message = 'claims_team', 'The claims team will read the photographed estimate.'
    elif not state['facts']['incident_report_present']:
        owner, message = 'claimant', 'Please add the incident report using this link.'
    elif latest.get('status') != 'verified':
        owner = 'garage' if latest.get('amount_eur') is not None else 'claimant'
        message = (
            'Ask the garage for an itemized repair quote and add the revised file here.'
            if owner == 'garage'
            else 'Please add a readable itemized repair quote using this link.'
        )
    else:
        owner, message = (
            'claims_team',
            'The claims team has the requested paperwork and will review the claim.',
        )
    return {'owner': owner, 'message': message}


def _extend(state, documents, notes, offset):
    state = deepcopy(state)
    facts = state['facts']
    facts['incident_report_present'] = facts['incident_report_present'] or any(
        d['kind'] == 'incident_report' for d in documents
    )
    for key, entries in _submitted_notes(notes).items():
        state['notes'][key].extend(dict(e, position=e['position'] + offset) for e in entries)
    timestamp = datetime.now(timezone.utc).isoformat(timespec='seconds')
    quotes = [(i, d) for i, d in enumerate(documents, offset) if d['kind'] == 'itemized_quote']
    for pos, doc in quotes:
        quote = dict(assess_quote(doc), version=len(state['quotes']) + 1, position=pos)
        state['quotes'].append(quote)
        facts.update(quote_eur=quote['amount_eur'], itemized_quote_present=quote['itemized'])
        decision = decide(facts)
        state['history'].append(dict(quote_version=quote['version'], decision=decision, created_at=timestamp))
    state['decision'] = decide(facts)
    if not quotes:
        state['history'].append(
            dict(quote_version=len(state['quotes']), decision=state['decision'], created_at=timestamp)
        )
    state['next_action'] = _next_action(state)
    return state


def _public(record):
    receipt = dict(record['receipt'])
    state = record.get('state')
    if not state:
        return receipt
    # Only a receipt and filing guidance are available after submission. Original
    # files, narratives, photo metadata and translation pairs are staff-only.
    quotes = [
        {
            k: q[k]
            for k in (
                'version',
                'position',
                'name',
                'status',
                'amount_eur',
                'itemized',
                'page',
                'reason',
                'garage_request',
                'source',
                'review_required',
            )
            if k in q
        }
        for q in state['quotes']
    ]
    evidence = {'next_action': _next_action(state), 'quotes': quotes}
    if state['demo_case']:
        evidence.update(demo_case=state['demo_case'], decision=state['decision'])
    receipt['evidence'] = evidence
    missing = []
    if not state['facts']['incident_report_present']:
        missing.append('incident_report')
    if not quotes or (quotes[-1]['status'] != 'verified' and not quotes[-1].get('review_required')):
        missing.append('itemized_quote')
    receipt['missing_documents'] = missing
    return receipt


def claimant_action(store, action, body):
    token = body.get('token')
    _key(token)
    if action == 'resume':
        return _public(exchange(store, 'open', token, {}))
    if action in ('save-draft', 'submit'):
        revision = body.get('expected_revision')
        _revision(revision)
        if action == 'save-draft':
            return exchange(
                store, 'save', token, {'draft': _with_notes(body.get('draft'), True), 'revision': revision}
            )['receipt']
        payload = _with_notes(body.get('payload'))
        ref = 'CLM-' + str(uuid4())
        state = _extend(_initial_state(ref, payload), payload['documents'], payload['notes'], 0)
        data = {
            'payload': {k: v for k, v in payload.items() if k not in ('demo_case', 'notes')},
            'state': state,
            'revision': revision,
            'reference': ref,
            'hash': digest(payload),
        }
        return _public(exchange(store, 'submit', token, data))
    request_id = body.get('request_id')
    if not isinstance(request_id, str) or not UUID_V4.fullmatch(request_id):
        raise RequestError(400, 'A version 4 request ID is required.')
    docs = _documents(body.get('documents'), minimum=1, enhanced=True)
    types = [d['kind'] for d in docs]
    if len(set(types)) != len(types) or not set(types) <= {'incident_report', 'itemized_quote'}:
        raise RequestError(400, 'Add one revised quote or one missing report per type.')
    notes = _notes(body.get('notes', {}), docs, False)
    record = exchange(store, 'open', token, {})
    if record['receipt']['status'] != 'submitted':
        raise RequestError(409, 'Submit the claim before adding paperwork.')
    if not record.get('state'):
        return append_documents(store, token, request_id, docs)
    offset = record['receipt']['document_count']
    state = _extend(record['state'], docs, notes, offset)
    return _public(
        exchange(
            store,
            'append',
            token,
            {
                'documents': docs,
                'request_id': request_id.lower(),
                'hash': digest([docs, notes]),
                'offset': offset,
                'state': state,
            },
        )
    )


def staff_action(store, action, body, key):
    supplied = body.get('reviewer_key')
    if not key or not isinstance(supplied, str) or not hmac.compare_digest(supplied.encode(), key.encode()):
        raise RequestError(403, 'A valid staff access key is required.')
    ref = body.get('reference')
    if not isinstance(ref, str) or not ref.startswith('CLM-') or not UUID_V4.fullmatch(ref[4:]):
        raise RequestError(400, 'Enter a claim reference.')
    if action == 'document':
        i = body.get('position')
        if type(i) is not int or i < 0 or i >= 40:
            raise RequestError(400, 'Invalid attachment position.')
        return exchange(store, 'file', '', {'reference': ref, 'position': i})
    record = exchange(store, 'staff', '', {'reference': ref})
    state = record['state']
    evidence = {k: v for k, v in state.items() if k != 'facts'}
    evidence.update(next_action=_next_action(state), notes=_submitted_notes(state['notes']))
    return {
        'reference': ref,
        'incident_date': record['incident_date'],
        'documents': record['receipt']['documents'],
        'evidence': evidence,
    }
