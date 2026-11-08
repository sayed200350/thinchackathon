"""Read submitted claims through the local intake API, and simulate a quote-limit change."""
from http.client import HTTPConnection, HTTPException
import json

from engine import evaluate, load_policy, parse_claim
from engine.runtime import policy_from_dict
from .intake import EVIDENCE_FILE_REQUEST_LIMIT
from .store import RequestError
from .intake_replay import replay_versions


READS = {
    'list': ('/api/staff/inbox', ('limit', 'cursor')),
    'detail': ('/api/evidence/reviewer', ('reference',)),
    'document': ('/api/evidence/document', ('reference', 'position')),
}


def incoming(port, action, body, reviewer_key):
    if action not in (*READS, 'replay', 'policy-replay'):
        raise RequestError(404, 'Unknown inbox action.')
    if not isinstance(body, dict):
        raise RequestError(400, 'Expected a JSON object.')
    if not reviewer_key:
        raise RequestError(503, 'The workbench is missing its connection to the staff inbox.')
    path, fields = READS['detail' if action in ('replay', 'policy-replay') else action]
    payload = {key: body[key] for key in fields if key in body}
    payload['reviewer_key'] = reviewer_key
    connection = HTTPConnection('127.0.0.1', port, timeout=12)
    try:
        connection.request('POST', path, json.dumps(payload), {'Content-Type': 'application/json'})
        response = connection.getresponse()
        if response.status == 403:
            raise RequestError(403, 'Reviewer access was denied.')
        if response.status == 404:
            raise RequestError(404, 'Submitted claim or document was not found.')
        if response.status == 400:
            raise RequestError(400, 'Invalid inbox request.')
        if response.status != 200 or response.headers.get_content_type() != 'application/json':
            raise RequestError(503, 'The claim intake service is unavailable.')
        limit = EVIDENCE_FILE_REQUEST_LIMIT if action == 'document' else 8 * 1024 * 1024
        raw = response.read(limit + 1)
        if len(raw) > limit:
            raise RequestError(502, 'This claim exceeds the workbench display limit.')
        result = json.loads(raw)
        if not isinstance(result, dict):
            raise ValueError
    except (OSError, HTTPException, ValueError, RecursionError):
        raise RequestError(503, 'The claim intake service is unavailable.') from None
    finally:
        connection.close()
    if action == 'policy-replay':
        return replay_versions(result, body)
    return replay(result, body) if action == 'replay' else result


def replay(detail, body):
    saved = detail['evidence'].get('decision') or {}
    if not saved.get('raw_evidence') or not saved.get('input_fingerprint'):
        raise RequestError(409, 'This claim has no saved engine evidence for policy replay.')
    revision = body.get('expected_revision')
    if type(revision) is not int or revision != detail['category']['revision']:
        raise RequestError(409, 'The claim changed. Reopen it to load its latest assessment.')
    baseline = load_policy()
    if saved.get('policy_hash') != baseline.fingerprint:
        raise RequestError(409, 'The recorded policy is unavailable for this quote-limit proposal.')
    limit = body.get('quote_limit_eur')
    if type(limit) is not int or not 1 <= limit <= 1_000_000:
        raise RequestError(400, 'Enter a whole-euro quote limit between 1 and 1,000,000.')
    config = baseline.config
    rule = next(rule for rule in config['rules'] if rule['id'] == 'HR_QUOTE_LIMIT')
    previous_limit = int(rule['if']['value'])
    if limit == previous_limit:
        raise RequestError(400, 'Choose a limit different from the recorded policy.')
    config['version'] = f'proposal-limit-{limit}'
    rule['if']['value'] = str(limit)
    rule['reason'] = f'The repair quote exceeds EUR {limit}'
    proposed = evaluate(parse_claim(saved['raw_evidence']), policy_from_dict(config))
    if proposed['input_fingerprint'] != saved['input_fingerprint']:
        raise RequestError(409, 'The saved evidence could not be reproduced.')

    def summary(decision):
        return {'recommendation': decision['recommendation'], 'rule': decision['primary_rule_id'],
                'version': decision['policy_version'], 'why': decision['audit']['detail']['employee']['why']}

    return {'reference': detail['reference'], 'revision': revision, 'recorded_limit_eur': previous_limit,
            'proposed_limit_eur': limit, 'recorded': summary(saved), 'proposed': summary(proposed)}
