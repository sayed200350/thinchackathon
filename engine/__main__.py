import argparse
import csv
import json
from pathlib import Path
import sys
import sqlite3

from .batch import read_claims, write_batch
from .policy import decide
from .runtime import DEFAULT_POLICY, evaluate, load_policy, parse_claim
from .impact import compare_policies, export_required_csv, baseline_report, export_audit_jsonl
from .metrics import measure


def distinct_output(output, inputs):
    for source in inputs:
        if output.resolve() == source.resolve() or (output.exists() and source.exists() and output.samefile(source)):
            raise ValueError("Choose an output path different from all input and policy files.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Policy Replay motor-claims triage")
    commands = parser.add_subparsers(dest="action", required=True)
    show = commands.add_parser("decide", help="show one claim's v1 decision as JSON")
    show.add_argument("input", type=Path)
    show.add_argument("case_id")
    show.add_argument("--policy", type=Path, help="JSON policy; returns a detailed decision passport")
    batch = commands.add_parser("batch", help="write the seven-column v1 preview CSV")
    batch.add_argument("input", type=Path)
    batch.add_argument("output", type=Path)
    batch.add_argument("--audit", type=Path, help="companion detailed audit JSONL")
    validate = commands.add_parser("validate-v1", help="score independent development labels")
    validate.add_argument("--input", type=Path, default=Path("data/taktile/labelled_development_cases.csv"))
    validate.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    compare = commands.add_parser("compare", help="preview a candidate policy and export seven judge columns")
    compare.add_argument("--input", type=Path, required=True)
    compare.add_argument("--v1", type=Path, default=DEFAULT_POLICY)
    compare.add_argument("--v2", type=Path, required=True, help="explicit candidate JSON; no official v2 is bundled")
    compare.add_argument("--output", type=Path, required=True)
    compare.add_argument("--report", type=Path, help="optional detailed JSON impact report")
    compare.add_argument("--audit", type=Path, help="companion detailed audit JSONL")
    compare.add_argument("--registry", type=Path, default=Path(__file__).parent / ".local/policy-registry.sqlite3",
                         help="append-only local version registry")
    check = commands.add_parser("check-policy", help="validate a policy and print its fingerprints")
    check.add_argument("policy", type=Path)
    generated = commands.add_parser("test-policy", help="run generated predicate boundary and safety checks")
    generated.add_argument("policy", type=Path)
    args = parser.parse_args()

    try:
        if args.action == "test-policy":
            from .conformance import run_checks
            report = run_checks(load_policy(args.policy))
            print(json.dumps(report, indent=2))
            if report["failed"]:
                parser.exit(1)
        elif args.action == "check-policy":
            policy = load_policy(args.policy)
            print(json.dumps(dict(version=policy.version, valid=True, fingerprint=policy.fingerprint,
                                  source_fingerprint=policy.source_fingerprint), indent=2))
        elif args.action == "validate-v1":
            policy = load_policy(args.policy)
            if policy.version != "v1":
                raise ValueError("expected_v1 labels can only validate policy v1.")
            report = measure(read_claims(args.input, strict_schema=True), policy)
            print(json.dumps(report, indent=2))
            if report["errors"]:
                parser.exit(1)
        elif args.action == "compare":
            inputs = [args.input, args.v1, args.v2]
            distinct_output(args.output, inputs)
            if args.report:
                distinct_output(args.report, inputs + [args.output])
            if args.audit:
                distinct_output(args.audit, inputs + [args.output] + ([args.report] if args.report else []))
            distinct_output(args.registry, inputs + [args.output] + ([args.audit] if args.audit else []) + ([args.report] if args.report else []))
            from .registry import bind_versions
            v1, v2 = load_policy(args.v1), load_policy(args.v2)
            bind_versions(args.registry, v1, v2)
            report = compare_policies(v1, v2,
                                      read_claims(args.input, strict_schema=True))
            export_required_csv(report, args.output)
            if args.audit:
                export_audit_jsonl(report, args.audit)
            if args.report:
                args.report.parent.mkdir(parents=True, exist_ok=True)
                args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            print(f"Wrote {len(report['rows'])} claims to {args.output}; "
                  f"{report['affected_open_cases']} open claims need recheck; "
                  f"{report['closed_retained']} closed results retained. Candidate preview only.", file=sys.stderr)
            if report["errors"]:
                parser.exit(1, f"{len(report['errors'])} invalid rows were exported with VALIDATION_ERROR; inspect the audit.\n")
        elif args.action == "batch":
            distinct_output(args.output, [args.input, DEFAULT_POLICY])
            if args.audit:
                distinct_output(args.audit, [args.input, args.output, DEFAULT_POLICY])
            report = baseline_report(load_policy(), read_claims(args.input))
            export_required_csv(report, args.output)
            if args.audit:
                export_audit_jsonl(report, args.audit)
            count = len(report["rows"])
            print(f"Wrote {count} claims to {args.output}. Open claims await policy v2.", file=sys.stderr)
            if report["errors"]:
                parser.exit(1, f"{len(report['errors'])} invalid rows were exported with VALIDATION_ERROR; inspect the audit.\n")
        else:
            selected = None
            for claim in read_claims(args.input):
                if claim["case_id"].strip() == args.case_id:
                    selected = claim
            if selected is None:
                raise ValueError(f"Unknown case_id: {args.case_id}")
            result = evaluate(parse_claim(selected), load_policy(args.policy)) if args.policy else decide(selected)
            print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    except (OSError, ValueError, csv.Error, sqlite3.Error, RecursionError) as error:
        parser.exit(1, f"error: {error}\n")


if __name__ == "__main__":
    main()
