"""Read-only policy replay; closed decisions retain their original result."""
from collections import Counter
import csv
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

from .batch import OUTPUT_COLUMNS
from .runtime import Claim, RecordValidationError, evaluate, parse_claim, fingerprint, serial


def invalid_record(raw, error, row_number):
    case_id = raw.get("case_id", "") if isinstance(raw, dict) else ""
    case_id = case_id.strip() if isinstance(case_id, str) else ""
    issue = dict(error.as_dict(), row_number=row_number)
    row = dict.fromkeys(OUTPUT_COLUMNS, "")
    row.update(case_id=case_id, explanation="VALIDATION_ERROR: " + str(error))
    return row, {"case_id": case_id, "validation_error": issue}


def baseline_report(policy, claims, historical=None):
    rows, cases, errors, seen = [], [], [], set()
    for raw in claims:
        try:
            claim = parse_claim(raw)
            if claim.case_id in seen:
                raise RecordValidationError(["Duplicate case_id"], claim.case_id)
            seen.add(claim.case_id)
            closed = claim.case_status == "closed"
            saved = (historical or {}).get(claim.case_id) if closed else None
            if saved:
                identity = fingerprint({"case_id": claim.case_id, "case_status": claim.case_status,
                                       **{k: serial(v) for k, v in claim.facts.items()}})
                expected = {"case_id": claim.case_id, "case_status": "closed", "policy_version": policy.version,
                            "policy_fingerprint": policy.fingerprint, "input_fingerprint": identity}
                for key, value in expected.items():
                    if saved.get(key) != value:
                        raise RecordValidationError(["Historical decision identity, input or policy hash mismatch"], claim.case_id)
                decision = saved
            else:
                decision = evaluate(claim, policy)
            retained = "persisted immutable machine decision" if saved else "v1 classification computed for this exercise; no historical record supplied"
            explanation = ("Closed claim: retained " + retained + ". " if closed else "Official v2 unavailable. ") + decision.get("concise_explanation", decision["explanation"])
            rows.append(dict(case_id=claim.case_id, recommendation_v1=decision["recommendation"],
                recommendation_v2=decision["recommendation"] if closed else "", needs_recheck=False if closed else "",
                rule_v1=decision["primary_rule_id"], rule_v2=decision["primary_rule_id"] if closed else "", explanation=explanation))
            cases.append({"case_id": claim.case_id, "original": decision,
                          "retention_source": ("persisted_history" if saved else "computed_exercise_v1") if closed else None})
        except RecordValidationError as error:
            row, detail = invalid_record(raw, error, len(rows) + 1)
            rows.append(row)
            cases.append(detail)
            errors.append(detail["validation_error"])
    return {"rows": rows, "cases": cases, "errors": errors, "v2_independent_quality": "not measured"}


def export_audit_jsonl(report, path):
    import json
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        for case in report["cases"]:
            stream.write(json.dumps(case, ensure_ascii=False, allow_nan=False) + "\n")


def policy_diff(before, after):
    a, b = before.config, after.config
    old = {r["id"]: r for r in a["rules"]}
    new = {r["id"]: r for r in b["rules"]}
    return {
        "added_rules": [new[k] for k in sorted(new.keys() - old.keys())],
        "removed_rules": [old[k] for k in sorted(old.keys() - new.keys())],
        "changed_rules": [{"id": k, "before": old[k], "after": new[k]}
                          for k in sorted(old.keys() & new.keys()) if old[k] != new[k]],
        "settings": {k: {"before": a.get(k), "after": b.get(k)}
                     for k in ("precedence", "unknown_handling", "fallback", "enumerations", "source") if a.get(k) != b.get(k)},
    }


def compare_policies(v1, v2, claims, historical=None):
    if v1.config["policy_id"] != v2.config["policy_id"]:
        raise ValueError("Cannot compare unrelated policy IDs.")
    if v1.version == v2.version:
        raise ValueError("Candidate policy must use a distinct version identifier.")
    diff = policy_diff(v1, v2)
    changed = {r["id"] for r in diff["added_rules"] + diff["removed_rules"] + diff["changed_rules"]}
    rows, details, transitions, seen, errors = [], [], Counter(), set(), []
    for raw in claims:
        try:
            claim = raw if isinstance(raw, Claim) else parse_claim(raw)
            if claim.case_id in seen:
                raise RecordValidationError(["Duplicate case_id"], claim.case_id)
            seen.add(claim.case_id)
            closed = claim.case_status == "closed"
            saved = (historical or {}).get(claim.case_id) if closed else None
            if saved:
                identity = fingerprint({"case_id": claim.case_id, "case_status": claim.case_status,
                    **{k: serial(v) for k, v in claim.facts.items()}})
                if (saved.get("case_id") != claim.case_id or saved.get("case_status") != "closed"
                    or saved.get("policy_version") != v1.version or saved.get("policy_fingerprint") != v1.fingerprint
                    or saved.get("input_fingerprint") != identity
                    or saved.get("recommendation") not in ("human_review", "request_information", "routine_processing")
                    or not saved.get("primary_rule_id")):
                    raise RecordValidationError(["Historical decision identity, input or policy hash mismatch"], claim.case_id)
                before = saved
            else:
                before = evaluate(claim, v1)
        except RecordValidationError as error:
            error_row, detail = invalid_record(raw, error, len(rows) + 1)
            rows.append(error_row)
            details.append(detail)
            errors.append(detail["validation_error"])
            continue
        after = before if closed else evaluate(claim, v2)
        recommendation_changed = before["recommendation"] != after["recommendation"]
        old_trace = {r["rule_id"]: r["result"] for r in before["trace"]}
        new_trace = {r["rule_id"]: r["result"] for r in after["trace"]}
        # An amendment is relevant if its predicate matched before/after, or
        # its truth/unknown state changed. False in both versions is unaffected.
        relevant = [] if closed else sorted(k for k in changed
            if old_trace.get(k, False) is True or new_trace.get(k, False) is True
            or old_trace.get(k, False) != new_trace.get(k, False))
        impacted = not closed and (bool(relevant) or before["primary_rule_id"] != after["primary_rule_id"]
                                   or before["missing_or_invalid_fields"] != after["missing_or_invalid_fields"])
        recheck = not closed and (recommendation_changed or impacted)
        if closed:
            retention = "persisted immutable machine decision" if saved else "v1 classification computed for this exercise; no historical record supplied"
            explanation = "Closed claim: retained " + retention + ". " + before.get("concise_explanation", before["explanation"])
        else:
            transitions[f"{before['recommendation']} -> {after['recommendation']}"] += 1
            explanation = f"{v1.version}: {before.get('concise_explanation', before['explanation'])} {v2.version}: {after.get('concise_explanation', after['explanation'])} "
            explanation += ("Recheck: amended rules or validation affect this claim: " + (", ".join(relevant) or "required evidence eligibility changed") + "."
                            if recheck else "No material rule impact; no recheck needed.")
        rows.append(dict(case_id=claim.case_id, recommendation_v1=before["recommendation"],
                         recommendation_v2=after["recommendation"], needs_recheck=recheck,
                         rule_v1=before["primary_rule_id"], rule_v2=after["primary_rule_id"], explanation=explanation))
        details.append(dict(case_id=claim.case_id, original=before, candidate=after,
                            closed_retained=closed, recommendation_changed=recommendation_changed,
                            rule_impacted=impacted, impacted_rule_ids=relevant, needs_recheck=recheck,
                            retention_source=("persisted_history" if saved else "computed_exercise_v1") if closed else None,
                            version_differences={"changed_rules": [r for r in diff["changed_rules"] if r["id"] in relevant],
                                "added_rules": [r for r in diff["added_rules"] if r["id"] in relevant],
                                "removed_rules": [r for r in diff["removed_rules"] if r["id"] in relevant],
                                "settings": diff["settings"],
                                "reason": explanation}))
    return dict(v1_version=v1.version, v2_version=v2.version,
                v1_fingerprint=v1.fingerprint, v2_fingerprint=v2.fingerprint,
                policy_diff=diff, rows=rows, cases=details, open_transition_matrix=dict(transitions),
                affected_open_cases=sum(row["needs_recheck"] is True for row in rows),
                closed_retained=sum(case.get("closed_retained", False) for case in details), errors=errors,
                v2_independent_quality="not measured",
                quality_note="Replay predictions are not independently labelled v2 accuracy.")


def export_required_csv(report, path):
    """Atomically replace an output only after a complete, valid replay."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with NamedTemporaryFile(mode="w", encoding="utf-8", newline="", dir=path.parent,
                                prefix=f".{path.name}.", delete=False) as stream:
            temporary = Path(stream.name)
            writer = csv.DictWriter(stream, fieldnames=OUTPUT_COLUMNS)
            writer.writeheader()
            count = 0
            for row in report["rows"]:
                writer.writerow(row)
                count += 1
        os.replace(temporary, path)
        return count
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
