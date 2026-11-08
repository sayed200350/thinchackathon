"""Read-only full-policy comparison against a submitted claim's recorded evidence."""
from pathlib import Path

from engine import compare_policies, load_policy
from .store import RequestError


def replay_versions(detail, body):
    if body.get('target_version') != 'v2':
        raise RequestError(400, 'Select the supplied v2 policy for this preview.')
    revision = detail['category']['revision']
    if type(body.get('expected_revision')) is not int or body['expected_revision'] != revision:
        raise RequestError(409, 'The claim changed. Open its latest revision before replaying.')
    reference = detail['reference']
    saved = detail['evidence'].get('decision') or {}
    baseline = load_policy()
    if (not saved.get('raw_evidence') or saved.get('case_id') != reference
            or saved['raw_evidence'].get('case_id') != reference
            or saved.get('policy_hash') != baseline.fingerprint):
        raise RequestError(409, 'No reproducible v1 decision is available for this claim.')
    candidate = load_policy(Path(__file__).resolve().parents[1] / 'engine/configs/policy_v2.json')
    report = compare_policies(baseline, candidate, [saved['raw_evidence']], historical={reference: saved})
    case = report['cases'][0]
    identity = ('input_fingerprint', 'policy_version', 'case_status', 'recommendation', 'primary_rule_id')
    if report['errors'] or any(case['original'].get(k) != saved.get(k) for k in identity):
        raise RequestError(409, 'The recorded evidence and decision do not match this revision.')

    def summary(decision):
        return {'version': decision['policy_version'], 'recommendation': decision['recommendation'],
                'rule': decision['primary_rule_id'], 'why': decision['audit']['detail']['employee']['why']}

    return {'reference': reference, 'revision': revision, 'target_version': candidate.version,
            'recorded': summary(saved), 'proposed': summary(case['candidate']),
            'closed_retained': case['closed_retained'], 'needs_recheck': case['needs_recheck'],
            'recommendation_changed': case['recommendation_changed'], 'impacted_rules': case['impacted_rule_ids']}
