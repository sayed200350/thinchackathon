"""Claimant submissions and private supporting documents for the intake flow."""

import base64
import binascii
from contextlib import closing
from datetime import date, datetime
import hashlib
import json
import re
from uuid import uuid4
from zoneinfo import ZoneInfo

from .store import RequestError, connect


MAX_FILE_BYTES = 2 * 1024 * 1024
REQUIRED_DOCUMENTS = ('incident_report', 'itemized_quote')
DOCUMENT_KINDS = (*REQUIRED_DOCUMENTS, 'damage_photo')
FORM_FIELDS = {'request_id', 'description', 'incident_date', 'location', 'policy_number',
               'email', 'injury_status', 'documents'}
UUID_V4 = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}', re.I)
FILE_SIGNATURES = {'.pdf': b'%PDF-', '.png': b'\x89PNG\r\n\x1a\n',
                   '.jpg': b'\xff\xd8\xff', '.jpeg': b'\xff\xd8\xff'}


def _text(value, field, minimum, maximum):
    if not isinstance(value, str):
        raise RequestError(400, f'{field} must be text.')
    text = value.strip()
    if not minimum <= len(text) <= maximum:
        raise RequestError(400, f'{field} must contain {minimum} to {maximum} characters.')
    if re.search(r'[\x00\ud800-\udfff]', text):
        raise RequestError(400, f'{field} contains an invalid character.')
    return text


def _validate_document(doc, *, enhanced=False):
    if not isinstance(doc, dict) or set(doc) != {'kind', 'name', 'content_base64'}:
        raise RequestError(400, 'Each attachment needs a kind, filename and file contents.')
    if doc['kind'] not in DOCUMENT_KINDS:
        raise RequestError(400, 'Choose an available document type.')
    name = _text(doc['name'], 'Filename', 1, 180)
    if name != doc['name'] or re.search(r'[/\\\x00-\x1f\x7f-\x9f]', name):
        raise RequestError(400, 'Use a plain filename without paths or control characters.')
    _, separator, extension = name.rpartition('.')
    signature = FILE_SIGNATURES.get(separator + extension.lower())
    if signature is None:
        raise RequestError(400, 'Attach a PDF, PNG or JPEG file.')

    large_photo = enhanced and doc['kind'] == 'damage_photo' and extension.lower() in ('png', 'jpg', 'jpeg')
    maximum = 12 * 1024 * 1024 if large_photo else MAX_FILE_BYTES
    encoded = doc['content_base64']
    if not isinstance(encoded, str) or not 0 < len(encoded) <= 4 * ((maximum + 2) // 3):
        raise RequestError(400, f'Each attachment must contain a file of at most {maximum // (1024*1024)} MiB.')
    try:
        content = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        raise RequestError(400, 'The attachment could not be decoded.') from None
    if len(content) > maximum or base64.b64encode(content).decode('ascii') != encoded:
        raise RequestError(400, f'Use a valid base64 attachment of at most {maximum // (1024*1024)} MiB.')
    if not content.startswith(signature):
        raise RequestError(400, 'The file contents and extension must match.')
    return {'kind': doc['kind'], 'name': name, 'content_base64': encoded}


def validate_intake(body, *, enhanced=False):
    if not isinstance(body, dict) or set(body) != FORM_FIELDS:
        raise RequestError(400, 'Provide the claim details and an attachment list.')
    request_id = body['request_id']
    if not isinstance(request_id, str) or not UUID_V4.fullmatch(request_id):
        raise RequestError(400, 'Use a version 4 UUID for the request ID.')
    normalized = {'request_id': request_id.lower()}
    for field, minimum, maximum in [('description', 10, 2000), ('location', 1, 160),
                                    ('policy_number', 1, 80), ('email', 3, 254)]:
        normalized[field] = _text(body[field], field, minimum, maximum)
    if not re.fullmatch(r'[^\s@]+@[^\s@.]+(?:\.[^\s@.]+)+', normalized['email']):
        raise RequestError(400, 'Enter a valid contact email address.')
    day = body['incident_date']
    if not isinstance(day, str) or not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', day):
        raise RequestError(400, 'Enter the incident date as YYYY-MM-DD.')
    try:
        incident_date = date.fromisoformat(day)
    except ValueError:
        raise RequestError(400, 'Enter a valid calendar date.') from None
    if incident_date > datetime.now(ZoneInfo('Europe/Berlin')).date():
        raise RequestError(400, 'The incident date cannot be in the future.')
    normalized['incident_date'] = day
    if body['injury_status'] not in ('yes', 'no', 'unknown'):
        raise RequestError(400, 'Choose yes, no or unknown for injuries.')
    normalized['injury_status'] = body['injury_status']
    docs = body['documents']
    limit = 4 if enhanced else 3
    if not isinstance(docs, list) or len(docs) > limit:
        raise RequestError(400, 'Attach up to four documents.' if enhanced else 'Attach up to three documents.')
    normalized['documents'] = [_validate_document(doc, enhanced=enhanced) for doc in docs]
    return normalized


def initialize_intakes(sqlite_path):
    sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    with closing(connect(sqlite_path)) as db:
        db.executescript("""
            BEGIN;
            CREATE TABLE IF NOT EXISTS intake_submissions (
                reference TEXT PRIMARY KEY,
                request_id TEXT NOT NULL UNIQUE,
                payload_hash TEXT NOT NULL,
                description TEXT NOT NULL,
                incident_date TEXT NOT NULL,
                location TEXT NOT NULL,
                policy_number TEXT NOT NULL,
                email TEXT NOT NULL,
                injury_status TEXT NOT NULL,
                received_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
            );
            CREATE TABLE IF NOT EXISTS intake_documents (
                reference TEXT NOT NULL REFERENCES intake_submissions(reference),
                position INTEGER NOT NULL,
                kind TEXT NOT NULL,
                name TEXT NOT NULL,
                content BLOB NOT NULL,
                PRIMARY KEY(reference, position)
            );
            COMMIT;
        """)


def _receipt(reference, documents):
    kinds = {doc['kind'] for doc in documents}
    return {'reference': reference, 'document_count': len(documents),
            'missing_documents': [kind for kind in REQUIRED_DOCUMENTS if kind not in kinds]}


def save_intake_sqlite(db, payload):
    """Save a validated submission and all bytes in one transaction."""
    with db:
        db.execute('BEGIN IMMEDIATE')
        return write_intake_sqlite(db, payload)


def write_intake_sqlite(db, payload, reference=None):
    """Write or replay a validated intake inside the caller's transaction."""
    canonical = json.dumps(payload, sort_keys=True, separators=(',', ':')).encode('utf-8')
    digest = hashlib.sha256(canonical).hexdigest()
    existing = db.execute('SELECT reference, payload_hash FROM intake_submissions WHERE request_id = ?',
                          (payload['request_id'],)).fetchone()
    if existing:
        if existing[1] != digest:
            raise RequestError(409, 'This request ID already belongs to a different submission.')
        return _receipt(existing[0], payload['documents'])
    reference = reference or 'CLM-' + str(uuid4())
    db.execute("""INSERT INTO intake_submissions (reference, request_id, payload_hash, description,
               incident_date, location, policy_number, email, injury_status)
               VALUES (:reference, :request_id, :payload_hash, :description, :incident_date,
                       :location, :policy_number, :email, :injury_status)""",
               {**payload, 'reference': reference, 'payload_hash': digest})
    for position, doc in enumerate(payload['documents']):
        db.execute('INSERT INTO intake_documents (reference, position, kind, name, content) VALUES (?, ?, ?, ?, ?)',
                   (reference, position, doc['kind'], doc['name'], base64.b64decode(doc['content_base64'])))
    return _receipt(reference, payload['documents'])


def save_intake_supabase(store, payload):
    data, _ = store._request('rpc/submit_claim_intake', body={'p_payload': payload})
    if isinstance(data, dict) and isinstance(data.get('reference'), str):
        reference = data['reference']
        if (reference.startswith('CLM-') and UUID_V4.fullmatch(reference[4:])
                and type(data.get('document_count')) is int and data == _receipt(reference, payload['documents'])):
            return data
    raise RequestError(503, 'The receipt could not be confirmed. Retry with the same request ID.')
