"""Append-only staff decisions on submitted intake references."""
from contextlib import closing
import os
import sqlite3

from .store import RequestError, connect, validate_correction


def initialize(path):
    with closing(connect(path)) as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS intake_staff_corrections (
                reference TEXT NOT NULL REFERENCES intake_submissions(reference),
                ordinal INTEGER NOT NULL CHECK (ordinal > 0),
                document_count INTEGER NOT NULL CHECK (document_count >= 0),
                revision INTEGER NOT NULL CHECK (revision = document_count + ordinal),
                request_id TEXT NOT NULL,
                reviewer TEXT NOT NULL,
                reason TEXT NOT NULL,
                policy_version TEXT NOT NULL,
                previous_recommendation TEXT,
                recommendation TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                PRIMARY KEY(reference, ordinal),
                UNIQUE(reference, request_id)
            );
            CREATE INDEX IF NOT EXISTS intake_submissions_staff_page
                ON intake_submissions(received_at DESC, reference DESC);
        """)


def save_staff_correction(store, reference, body):
    """The HTTP handler authenticates the reviewer before calling this storage operation."""
    values, expected = validate_correction(body)
    for field, limit in [('request_id', 128), ('reviewer', 128), ('reason', 2000), ('policy_version', 32)]:
        value = values[field]
        try:
            value.encode('utf-8')
        except UnicodeEncodeError:
            raise RequestError(400, f'Invalid text in {field}.') from None
        if len(value) > limit or '\0' in value:
            raise RequestError(400, f'Invalid {field}. Maximum length is {limit}.')
    if expected > 999999999:
        raise RequestError(400, 'Invalid expected_revision.')
    if not isinstance(store, sqlite3.Connection):
        key = os.getenv('CLAIM_EVIDENCE_SERVICE_KEY')
        if not key:
            raise RequestError(503, 'The private evidence store has not been configured.')
        result, _ = store._request(
            'rpc/claim_staff_correct',
            body={'p_service': key, 'p_reference': reference, 'p_data': dict(values, expected_revision=expected)},
            max_response=65536,
        )
        if (not isinstance(result, dict) or result.get('status') not in (200, 201)
                or not isinstance(result.get('correction'), dict)):
            raise RequestError(503, 'The staff correction could not be confirmed.')
        return result.pop('status'), result
    with store:
        # The existing evidence appenders take this same write lock.
        store.execute('BEGIN IMMEDIATE')
        decision = store.execute("""
            SELECT json_extract(e.state,'$.decision.recommendation') AS recommendation,
                   COALESCE(json_extract(e.state,'$.decision.policy_version'),'v1') AS policy_version,
                   (SELECT count(*) FROM intake_documents d WHERE d.reference=s.reference) AS document_count
            FROM intake_submissions s LEFT JOIN intake_evidence e ON e.reference=s.reference
            WHERE s.reference=?
        """, (reference,)).fetchone()
        if decision is None:
            raise RequestError(404, 'Unknown submitted claim.')
        docs = decision['document_count']
        latest = store.execute("""SELECT ordinal, document_count, recommendation FROM intake_staff_corrections
                                  WHERE reference=? ORDER BY ordinal DESC LIMIT 1""", (reference,)).fetchone()
        ordinal = latest['ordinal'] if latest else 0
        current = docs + ordinal
        by_id = 'SELECT * FROM intake_staff_corrections WHERE reference=? AND request_id=?'
        request = (reference, values['request_id'])
        prior = store.execute(by_id, request).fetchone()
        if prior is not None:
            if prior['revision'] != expected + 1 or any(prior[k] != value for k, value in values.items()):
                raise RequestError(409, 'That request ID belongs to a different correction.')
            return 200, {'reference': reference, 'revision': current, 'correction': dict(prior)}
        if expected != current or decision['policy_version'] != values['policy_version']:
            raise RequestError(409, 'The evidence, policy or staff decision changed. Reload this claim.')
        previous = (latest['recommendation'] if latest and latest['document_count'] == docs
                    else decision['recommendation'])
        if previous == values['recommendation']:
            raise RequestError(400, 'Choose a different recommendation for a correction.')
        store.execute("""INSERT INTO intake_staff_corrections
            (reference,ordinal,document_count,revision,request_id,reviewer,reason,policy_version,previous_recommendation,recommendation)
            VALUES (:ref,:ordinal,:docs,:revision,:request_id,:reviewer,:reason,:policy_version,:previous,:recommendation)""",
            dict(values, ref=reference, ordinal=ordinal + 1, docs=docs, revision=current + 1, previous=previous))
        saved = store.execute(by_id, request).fetchone()
        return 201, {'reference': reference, 'revision': current + 1, 'correction': dict(saved)}
