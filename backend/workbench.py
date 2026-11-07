"""Browser workbench endpoints. Uploaded data is evaluated, never persisted."""
import base64
import binascii
import csv
import io
import json
from pathlib import Path

from engine import compare_policies, load_policy
from engine.batch import OUTPUT_COLUMNS, read_claim_stream, ClaimRow
from engine.docx_policy import PolicyDocumentError, policy_from_docx
from engine.impact import baseline_report
from .policies import register
from engine.policy import FIELDS
from engine.runtime import policy_from_dict, policy_from_json

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "engine/tests/fixtures"


def get_candidate(body):
    choice = body.get("candidate", "none")
    if not isinstance(choice, str):
        raise ValueError("Candidate selection must be a string.")
    if choice == "none":
        return None
    fixtures = {"threshold": "v2_hypothetical_threshold.json", "ev": "v2_hypothetical_ev.json"}
    if choice in fixtures:
        return load_policy(FIXTURES / fixtures[choice])
    if choice == "custom":
        if "policy_text" in body:
            return policy_from_json(body["policy_text"])
        return policy_from_dict(body.get("policy"))
    raise ValueError("Choose a recognized candidate policy.")


def workspace(db):
    claims = [json.loads(row[0]) for row in db.execute("SELECT claim_json FROM claims ORDER BY case_id")]
    return {"claims": claims, "policy": load_policy().config}


def parse_csv(text):
    if not isinstance(text, str):
        raise ValueError("CSV upload must contain text.")
    return list(read_claim_stream(io.StringIO(text.lstrip("\ufeff"))))


def convert_docx(body):
    """Turn an uploaded Word policy into policy JSON plus a readable rule list for the user to check."""
    encoded, name, expected = body["policy_docx"], body.get("filename"), body.get("expected_policy_id")
    if not isinstance(encoded, str) or not (name is None or isinstance(name, str)) or not (expected is None or isinstance(expected, str)):
        raise ValueError("Invalid Word policy upload.")
    try:
        data = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        raise ValueError("The Word policy upload is not valid base64.")
    try:
        config, rules, notes = policy_from_docx(data, policy_id=expected or None, filename=name)
        policy = policy_from_dict(config)
    except PolicyDocumentError as error:
        raise ValueError(f"Could not read the Word policy: {error}")
    return {"policy_text": json.dumps(config, indent=2), "version": policy.version, "policy_id": config["policy_id"],
            "rules": rules, "notes": notes}


def get_baseline(body):
    """The policy under test. The browser always uploads it; API callers may omit it to use the bundled v1."""
    if "baseline_text" in body:
        return policy_from_json(body["baseline_text"])
    return load_policy()


def run(body, db=None):
    if not isinstance(body, dict):
        raise ValueError("Expected a JSON object.")
    if body.get("policy_only") is True:
        # Convert (Word) or validate (JSON) uploaded policy files without needing any claims.
        if "policy_docx" in body:
            return convert_docx(body)
        baseline = get_baseline(body) if "baseline_text" in body else None
        candidate = get_candidate(body)
        if baseline is None and candidate is None:
            raise ValueError("Supply a policy to validate.")
        return {"baseline_version": baseline.version if baseline else None,
                "baseline_policy_id": baseline.config["policy_id"] if baseline else None,
                "candidate_version": candidate.version if candidate else None}
    rows = parse_csv(body["csv"]) if "csv" in body else body.get("claims")
    if not isinstance(rows, list) or not rows or len(rows) > 2000 or any(not isinstance(row, dict) for row in rows):
        raise ValueError("Supply between 1 and 2000 claim objects.")
    inherited = body.get("input_issues")
    if inherited is not None and "csv" not in body:
        if not isinstance(inherited, list) or len(inherited) != len(rows):
            raise ValueError("Input issue metadata must align with the input rows.")
        restored = []
        for raw, issue in zip(rows, inherited):
            if not isinstance(issue, dict) or any(not isinstance(issue.get(key, []), list) or any(not isinstance(x, str) for x in issue.get(key, [])) for key in ("schema", "record")):
                raise ValueError("Invalid input issue metadata.")
            row = ClaimRow(raw)
            row.schema_issues = tuple(issue.get("schema", []))
            row.record_errors = tuple(issue.get("record", []))
            restored.append(row)
        rows = restored
    input_issues = [{"schema": list(getattr(row, "schema_issues", ())), "record": list(getattr(row, "record_errors", ()))} for row in rows]
    baseline = get_baseline(body)
    candidate = get_candidate(body)
    if db is not None and candidate:
        register(db, candidate)
    historical = {}
    if body.get("use_saved") is True and db is not None:
        historical = {row[0]: json.loads(row[1]) for row in db.execute("SELECT case_id, decision_json FROM claims WHERE status='closed'")}
    report = compare_policies(baseline, candidate, rows, historical) if candidate else baseline_report(baseline, rows, historical)
    export_rows = report["rows"]
    decisions = [case.get("original") for case in report["cases"]]
    # Preserve only the supplied schema; never return labels or arbitrary extra columns.
    clean_rows = [{key: row.get(key) for key in ("case_id", "case_status", "claim_summary", *FIELDS)} for row in rows]
    for raw, result, decision in zip(clean_rows, export_rows, decisions):
        raw["case_id"] = result["case_id"]
        if decision:
            raw["case_status"] = decision["case_status"]
    rows = clean_rows
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=OUTPUT_COLUMNS)
    writer.writeheader()
    writer.writerows(export_rows)
    return {"claims": rows, "input_issues": input_issues, "decisions": decisions, "comparison": report if candidate else None, "audit_cases": report["cases"], "errors": report["errors"],
            "rows": export_rows, "csv": output.getvalue(), "candidate_version": candidate.version if candidate else None,
            "baseline_version": baseline.version}
