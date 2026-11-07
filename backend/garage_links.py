"""One expiring garage capability grants a single original repair-quote upload."""

import base64
from datetime import datetime, timezone
import hmac
import re
import time
from uuid import UUID

from cryptography.fernet import Fernet, InvalidToken

from .evidence_cases import _extend, digest
from .evidence_storage import exchange
from .intake import _validate_document
from .intake_links import _key
from .store import RequestError


_TTL_SECONDS = 7 * 24 * 60 * 60
_SCOPE = b'\x01'
_CONTEXT = b'thinc/garage/quote-upload/v1/'
_TOKEN = re.compile(r'[A-Za-z0-9_-]+={0,2}')


def _derive(secret, label):
    if not isinstance(secret, str) or len(secret) < 32:
        raise RequestError(503, 'Garage uploads are unavailable.')
    return hmac.digest(secret.encode('utf-8'), _CONTEXT + label, 'sha256')


def _cipher(secret):
    return Fernet(base64.urlsafe_b64encode(_derive(secret, b'encryption')))


def issue(store, claimant_token, secret):
    _key(claimant_token)
    cipher = _cipher(secret)
    record = exchange(store, 'open', claimant_token, {})
    if record['receipt']['status'] != 'submitted' or not record.get('state'):
        raise RequestError(409, 'Submit a claim with evidence support before requesting a garage quote.')
    revision = len(record['state']['quotes'])
    if record['receipt']['document_count'] >= 40:
        raise RequestError(409, 'This claim has reached its evidence file limit.')
    # The database binds the claimant capability permanently to its submitted claim.
    payload = _SCOPE + bytes.fromhex(claimant_token) + bytes([revision])
    now = int(time.time())
    token = cipher.encrypt_at_time(payload, now)
    expires = datetime.fromtimestamp(now + _TTL_SECONDS, timezone.utc)
    return {'token': token.decode('ascii'), 'expires_at': expires.isoformat()}


def _resolve(store, garage_token, secret):
    cipher = _cipher(secret)
    if not isinstance(garage_token, str) or len(garage_token) > 160 or not _TOKEN.fullmatch(garage_token):
        raise RequestError(403, 'This garage link is invalid or expired.')
    try:
        # Fernet uses integer seconds and an inclusive TTL. expires_at is the
        # first second when a garage can no longer use the link.
        payload = cipher.decrypt(garage_token.encode('ascii'), ttl=_TTL_SECONDS - 1)
    except InvalidToken:
        raise RequestError(403, 'This garage link is invalid or expired.') from None
    if len(payload) != 34 or payload[:1] != _SCOPE:
        raise RequestError(403, 'This garage link is invalid or expired.')
    claimant, revision = payload[1:33].hex(), payload[33]
    try:
        record = exchange(store, 'open', claimant, {})
    except RequestError as exc:
        if exc.status == 404:
            return claimant, revision, {}, 'closed'
        raise RequestError(503, 'Garage uploads are temporarily unavailable.') from None
    state = record.get('state')
    stage = 'closed'
    if state:
        quotes = state['quotes']
        if len(quotes) == revision and record['receipt']['document_count'] < 40:
            stage = 'open'
        elif len(quotes) > revision and quotes[revision].get('source') == 'garage':
            stage = 'received'
    return claimant, revision, record, stage


def status(store, garage_token, secret):
    _, _, record, stage = _resolve(store, garage_token, secret)
    if stage == 'open':
        return {'status': 'open', 'demo': record['state'].get('demo_case') == 'DEV-003'}
    return {'status': stage}


def upload(store, garage_token, document, secret):
    """Accept one original PDF, JPEG or PNG as an itemized_quote attachment."""
    claimant, revision, record, stage = _resolve(store, garage_token, secret)
    if stage == 'closed':
        raise RequestError(409, 'This garage link is closed.')
    if not isinstance(document, dict) or document.get('kind') != 'itemized_quote':
        raise RequestError(400, 'Choose a repair quote as a PDF, JPEG or PNG.')
    doc = _validate_document(document, enhanced=True)
    state = record['state']
    if stage == 'received':
        # All files are append-only. This historical offset cannot authorize a new
        # insert; the storage layer can only replay the original matching request.
        offset = state['quotes'][revision]['position']
    else:
        offset = record['receipt']['document_count']
        state = _extend(state, [doc], {'photos': [], 'translations': []}, offset)
        state['quotes'][-1]['source'] = 'garage'
        state['history'][-1]['source'] = 'garage'

    # Every remint of this claim/revision uses the same atomic database request ID.
    # The authenticated encrypted grant itself stays short and independently random.
    slot = bytes.fromhex(claimant) + bytes([revision])
    request_id = UUID(bytes=_derive(secret, b'request-id/' + slot)[:16], version=4)
    try:
        exchange(
            store,
            'append',
            claimant,
            {
                'documents': [doc],
                'request_id': str(request_id),
                'hash': digest(doc),
                'offset': offset,
                'state': state,
            },
        )
    except RequestError as exc:
        if exc.status == 409:
            raise RequestError(
                409, 'The request changed or a different file was already received. Reopen the garage link.'
            ) from None
        raise RequestError(503, 'Garage uploads are temporarily unavailable.') from None
    return {'status': 'received'}
