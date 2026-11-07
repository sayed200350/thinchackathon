"""Hosted reviewer store using the Supabase Data API and the browser-role grants."""

import base64
import http.client
import json
import os
import ssl
import sys
from urllib.parse import urlencode, urlsplit

from .store import RequestError, validate_correction


PAGE_SIZE = 100
REVIEW_VERSION = 'v1'
DECISION_COLUMNS = 'case_id,case_status,policy_version,recommendation,matched_rule,supporting_facts,explanation'
LATEST_OVERRIDE = 'overrides(revision,corrected_recommendation)'
AUDIT_COLUMNS = 'revision,request_id,reviewer,reason,policy_version,corrected_recommendation,created_at'


def _public_key(key):
    if key.startswith('sb_publishable_'):
        return True
    # Older projects may use a legacy anon JWT. The Supabase gateway validates its signature.
    try:
        _, payload, _ = key.split('.')
        claims = json.loads(base64.urlsafe_b64decode(payload + '=' * (-len(payload) % 4)))
        return isinstance(claims, dict) and claims.get('role') == 'anon'
    except (ValueError, UnicodeError):
        return False


class SupabaseStore:
    def __init__(self, url, key):
        location = urlsplit(url.strip())
        if (location.scheme != 'https' or not location.hostname or location.username is not None
                or location.password is not None or location.path not in ('', '/')
                or location.query or location.fragment):
            raise ValueError('SUPABASE_URL must be an HTTPS project URL.')
        self.host, self.port = location.hostname, location.port
        self._key = key.strip()
        if not _public_key(self._key) or any(char.isspace() for char in self._key):
            raise ValueError('Set a Supabase publishable key or legacy anon key for the reviewer backend.')
        self._tls = ssl.create_default_context()
        if (sys.platform == 'darwin' and not self._tls.get_ca_certs() and os.path.isfile('/etc/ssl/cert.pem')
                and not (os.environ.get('SSL_CERT_FILE') or os.environ.get('SSL_CERT_DIR'))):
            self._tls.load_verify_locations(cafile='/etc/ssl/cert.pem')

    def _request(self, resource, params=None, *, body=None):
        path = '/rest/v1/' + resource
        if params:
            path += '?' + urlencode(params)
        headers = {'apikey': self._key, 'Accept': 'application/json'}
        if body is None:
            headers['Prefer'] = 'count=exact'
        else:
            headers['Content-Type'] = 'application/json'
        connection = http.client.HTTPSConnection(self.host, self.port, timeout=10, context=self._tls)
        try:
            connection.request('GET' if body is None else 'POST', path, headers=headers,
                               body=None if body is None else json.dumps(body).encode('utf-8'))
            response = connection.getresponse()
            raw = response.read(16 * 1024 * 1024 + 1)
            if len(raw) > 16 * 1024 * 1024:
                raise RequestError(503, 'Supabase response exceeded the page limit.')
            data = json.loads(raw)
            if response.status not in (200, 206):
                # Only expected business errors raised by the RPC may pass through to reviewers.
                if (body is not None and isinstance(data, dict) and response.status in (400, 404, 409)
                        and data.get('code') == f'PT{response.status}'):
                    raise RequestError(response.status, data.get('message') or 'Correction rejected.')
                raise RequestError(503, 'Supabase could not complete the request. Check the connection and reviewer schema.')
            total = response.getheader('Content-Range', '').rsplit('/', 1)[-1]
            return data, int(total) if total.isdigit() else None
        except (ValueError, RecursionError, OSError, http.client.HTTPException) as error:
            raise RequestError(503, 'Supabase is unavailable. Please retry.') from error
        finally:
            connection.close()

    def _rows(self, resource, params, order_key):
        # Every cursor uses the last unique key rather than an offset that concurrent inserts can shift.
        query = dict(params, order=order_key + '.asc', limit=PAGE_SIZE)
        while True:
            page, total = self._request(resource, query)
            if not isinstance(page, list) or not all(isinstance(row, dict) for row in page):
                raise RequestError(503, 'Supabase returned an invalid row set.')
            yield from page
            if not page or (total is not None and len(page) >= total):
                return
            query[order_key] = 'gt.' + str(page[-1][order_key])

    def _decisions(self, columns, **filters):
        params = {'select': columns + ',' + LATEST_OVERRIDE, 'policy_version': 'eq.' + REVIEW_VERSION,
                  'overrides.order': 'revision.desc', 'overrides.limit': 1, **filters}
        return self._rows('decisions', params, 'case_id')

    def claim_list(self):
        claims = []
        for row in self._decisions('case_id,case_status,recommendation'):
            latest = row.pop('overrides')
            row['effective_recommendation'] = latest[0]['corrected_recommendation'] if latest else row['recommendation']
            row['revision'] = latest[0]['revision'] if latest else 0
            claims.append(row)
        return {'claims': claims}

    def case_detail(self, case_id):
        claims = self._rows('claims', {'select': 'source_fields', 'case_id': 'eq.' + case_id}, 'case_id')
        claim = next(claims, None)
        if claim is None:
            raise RequestError(404, 'Unknown case_id.')
        decision = next(self._decisions(DECISION_COLUMNS, case_id='eq.' + case_id), None)
        if decision is None:
            raise RequestError(503, 'The saved claim has no v1 policy decision.')
        latest = decision.pop('overrides')
        revision = latest[0]['revision'] if latest else 0
        previous = decision['recommendation']
        history = []
        if latest:
            # Capture a single audit snapshot even if more corrections arrive while pages are read.
            filters = {'select': AUDIT_COLUMNS, 'case_id': 'eq.' + case_id, 'policy_version': 'eq.' + REVIEW_VERSION,
                       'and': f'(revision.lte.{revision})'}
            for entry in self._rows('overrides', filters, 'revision'):
                entry['previous_recommendation'] = previous
                previous = entry['recommendation'] = entry.pop('corrected_recommendation')
                if entry['created_at'].endswith('+00:00'):
                    entry['created_at'] = entry['created_at'][:-6] + 'Z'
                history.append(entry)
            if len(history) != revision or previous != latest[0]['corrected_recommendation']:
                raise RequestError(503, 'The saved correction history is incomplete. Please reload the claim.')
        return {'claim': claim['source_fields'], 'decision': decision, 'history': history,
                'effective_recommendation': previous, 'revision': revision}

    def preview(self):
        statuses = [row['case_status'] for row in self._rows('claims', {'select': 'case_id,case_status'}, 'case_id')]
        return {'status': 'awaiting_v2', 'from_version': 'v1', 'to_version': 'v2',
                'open_claims': statuses.count('open'), 'closed_claims': statuses.count('closed'), 'changes': None}

    def save_correction(self, case_id, body):
        values, expected = validate_correction(body)
        if values['policy_version'] != REVIEW_VERSION:
            raise RequestError(409, 'Policy version mismatch. Reload this claim.')
        params = {'p_case_id': case_id, 'p_expected_revision': expected,
                  **{'p_' + field: value for field, value in values.items()}}
        result, _ = self._request('rpc/reviewer_save_correction', body=params)
        if result not in ('created', 'replayed'):
            raise RequestError(503, 'Supabase returned an unknown correction receipt. Retry with the same request ID.')
        return (201 if result == 'created' else 200), self.case_detail(case_id)

    def save_intake(self, payload):
        from .intake import save_intake_supabase
        return save_intake_supabase(self, payload)
