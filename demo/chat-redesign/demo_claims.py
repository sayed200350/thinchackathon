"""Fictional phone history, isolated from the live insurer's claim store."""
import base64
from contextlib import closing
from datetime import datetime, timezone
import hashlib
from pathlib import Path
from threading import Lock
from uuid import uuid4

from backend import evidence_storage
from backend.evidence_cases import claimant_action
from backend.intake import initialize_intakes
from backend.intake_links import initialize_intake_links
from backend.store import RequestError, connect

ROOT = Path(__file__).resolve().parents[2]
PERSON = {'name': 'Anna Becker', 'email': 'anna.becker@example.com',
          'phone': '+49 30 00000000', 'address': 'Example Street 12, 10115 Berlin',
          'insurance_number': 'DEMO-INS-48291', 'demo': True}
CASES = [
    ('parking', 'Scratched bumper in a car park', '2026-11-06', 'Example Street, Berlin', None),
    ('glass', 'Chipped windscreen on the motorway', '2026-09-23', 'Example Motorway, Berlin', '2026-09-24T10:00:00Z'),
    ('mirror', 'Damaged wing mirror while parked', '2026-06-18', 'Example Avenue, Berlin', '2026-06-19T09:00:00Z'),
    ('door', 'Scratched rear door in a garage', '2026-02-14', 'Example Garage, Berlin', '2026-02-16T11:00:00Z'),
]
TOKENS = {hashlib.sha256(('retakt-phone-demo-v1:' + case[0]).encode()).hexdigest(): case for case in CASES}


class PhoneDemoStore:
    def __init__(self, path):
        self.path = Path(path)
        self.lock = Lock()
        self.ready = False

    def handles(self, token):
        return isinstance(token, str) and token in TOKENS

    def ensure_seeded(self):
        with self.lock:
            if self.ready:
                return
            initialize_intakes(self.path)
            initialize_intake_links(self.path)
            evidence_storage.initialize(self.path)
            with closing(connect(self.path)) as db:
                for token, case in TOKENS.items():
                    try:
                        claimant_action(db, 'resume', {'token': token})
                        continue
                    except RequestError as err:
                        if err.status != 404:
                            raise
                    key, description, day, location, sent = case
                    values = dict(description=description, incident_date=day, location=location,
                                  policy_number=PERSON['insurance_number'], email=PERSON['email'], injury_status='no')
                    report = self.document('incident_report', 'sample-accident-report.pdf', 'incident-report.pdf')
                    if sent:
                        quote = self.document('itemized_quote', 'quotes/itemized-890.pdf', 'itemized-repair-quote.pdf')
                        claimant_action(db, 'submit', {'token': token, 'expected_revision': 0,
                            'payload': dict(values, request_id=str(uuid4()),
                                            documents=[report, quote], notes={})})
                    else:
                        claimant_action(db, 'save-draft', {'token': token, 'expected_revision': 0,
                            'draft': dict(values=values, documents=[report], notes={}, sources={}, step=7)})
            self.ready = True

    @staticmethod
    def document(kind, fixture, name):
        return {'kind': kind, 'name': name, 'content_base64': base64.b64encode(
            (ROOT / 'backend/fixtures' / fixture).read_bytes()).decode('ascii')}

    def action(self, action, body):
        if not self.handles(body.get('token')) or action not in ('resume', 'save-draft', 'submit'):
            raise RequestError(404, 'Demo claim action not found.')
        self.ensure_seeded()
        with closing(connect(self.path)) as db:
            return claimant_action(db, action, body)

    def records(self):
        self.ensure_seeded()
        records = []
        with closing(connect(self.path)) as db:
            for token, case in TOKENS.items():
                _, _, _, _, sent = case
                out = claimant_action(db, 'resume', {'token': token})
                if out['status'] == 'draft':
                    values = out['draft']['values']
                    missing = [kind for kind in ('incident_report', 'itemized_quote')
                               if not any(doc['kind'] == kind for doc in out['draft']['documents'])]
                    submitted_at = None
                else:
                    row = db.execute('SELECT * FROM intake_submissions WHERE reference=?', (out['reference'],)).fetchone()
                    values = {key: row[key] for key in ('description', 'incident_date', 'location', 'policy_number', 'email', 'injury_status')}
                    missing = out['missing_documents']
                    submitted_at = sent or row['received_at'] + 'Z'
                records.append(dict(token=token, status=out['status'], reference=out.get('reference', ''),
                    title=values['description'], incident_date=values['incident_date'], values=values,
                    contact=PERSON, demo=True, missing_documents=missing, ready=not missing,
                    submitted_at=submitted_at, updated_at=submitted_at or '2026-11-07T10:00:00Z'))
        return {'claims': records, 'profile': PERSON}
