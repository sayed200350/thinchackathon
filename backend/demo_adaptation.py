"""Reproducible fictional demo in a temporary database; --live calls the configured AI."""
import argparse
import json
import os
from pathlib import Path
import secrets
from tempfile import TemporaryDirectory

from .environment import load_environment
from .store import initialize, connect
from . import changes, adaptation
from .ai_service import AIUnavailable
from engine.conformance import BASE


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true', help='Send fictional policy documents to the configured provider once')
    parser.add_argument('--output', type=Path, help='Write the demonstration report')
    args = parser.parse_args()
    load_environment()
    if not os.environ.get('POLICY_TWIN_OWNER_TOKEN'):
        os.environ['POLICY_TWIN_OWNER_TOKEN'] = secrets.token_urlsafe(32)
    token = os.environ['POLICY_TWIN_OWNER_TOKEN']
    report = {'mode': 'live AI policy extraction' if args.live else 'mock provider; no AI network request', 'hypothetical': True}
    with TemporaryDirectory() as temporary:
        path = Path(temporary) / 'demo.sqlite3'
        initialize(path, [], workbench=True)
        db = connect(path)
        try:
            def save(raw):
                preview = changes.preview(db, {'claim': raw})
                return changes.save(db, dict(claim=raw, expected_revision=preview['revision'], expected_policy_hash=preview['active_policy_hash'],
                                            request_id=secrets.token_hex(12), actor='Fictional demo', reason='Demonstration evidence update'))
            raw = dict(BASE, case_id='DEMO-AMOUNT', quote_eur='1200')
            before = save(raw)
            after = save(dict(raw, quote_eur='1800'))
            report['claim_change'] = dict(before=before['decision']['recommendation'], after=after['decision']['recommendation'],
                                          change=after['history'][-1]['change'], history_length=len(after['history']))
            save(dict(BASE, case_id='DEMO-POLICY-OPEN', quote_eur='1300'))
            save(dict(BASE, case_id='DEMO-POLICY-CLOSED', case_status='closed', quote_eur='1300'))
            old = adaptation.active_document(db)
            new = old.replace('1,500', '1,200').replace('v1', 'v2-hypothetical-demo')
            if args.live:
                interpreter = None
            else:
                from .tests.test_adaptation import FixtureInterpreter
                interpreter = FixtureInterpreter()
            try:
                proposal = adaptation.propose(db, dict(version='v2-hypothetical-demo', document_text=new,
                    expected_policy_hash=changes.active_policy(db).fingerprint, request_id='demo-proposal'), token, interpreter)
                report['policy_proposal'] = proposal
                report['active_policy_after_proposal'] = changes.active_policy(db).version
                report['proposal_did_not_activate'] = changes.active_policy(db).version == 'v1'
                if proposal['validation']['valid']:
                    quote = next(c['new_quote'] for c in proposal['interpretation']['citations'] if c['target'] == 'HR_QUOTE_LIMIT')
                    tests = [dict(claim=dict(BASE,case_id='DEMO-BOUND-'+amount,quote_eur=amount),target='HR_QUOTE_LIMIT',source_quote=quote,expected=expected)
                             for amount,expected in [('1199.99','routine_processing'),('1200','routine_processing'),('1200.01','human_review')]]
                    report['safety_preview'] = adaptation.check(db, proposal['proposal_id'], dict(tests=tests), token)
                    report['acceptance_tests'] = tests
            except AIUnavailable as error:
                report['ai_error'] = str(error)
                report['deterministic_engine_still_available'] = changes.preview(db,dict(claim=dict(BASE)))['recommendation']
        finally:
            db.close()
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8')
    summary = {k:v for k,v in report.items() if k not in ('policy_proposal','safety_preview','acceptance_tests','claim_change')}
    summary['claim_change'] = report['claim_change']['before'] + ' -> ' + report['claim_change']['after']
    if 'policy_proposal' in report:
        p=report['policy_proposal']
        summary.update(proposal_status=p['status'],validation=p['validation'],impact=p.get('impact'))
    print(json.dumps(summary,indent=2,ensure_ascii=True))


if __name__ == '__main__':
    main()
