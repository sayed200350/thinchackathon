"""CSV input and replay output used by the judges' batch workflow."""

from __future__ import annotations

import csv
import itertools
from collections.abc import Callable, Iterator, Mapping
from pathlib import Path

from .policy import Decision, decide

OUTPUT_COLUMNS = (
    "case_id", "recommendation_v1", "recommendation_v2", "needs_recheck",
    "rule_v1", "rule_v2", "explanation",
)


class ClaimRow(dict):
    schema_issues = ()
    record_errors = ()


def read_claims(path: Path, *, recover_invalid: bool = False) -> Iterator[dict]:
    with path.open(encoding="utf-8-sig", newline="") as source:
        yield from read_claim_stream(source, recover_invalid=recover_invalid)


def read_claim_stream(source, *, recover_invalid=True):
    from .policy import FIELDS
    # Excel in many locales exports semicolon- or tab-delimited "CSV"; detect it from the header line.
    header = source.readline()
    counts = {d: header.count(d) for d in (",", ";", "\t")}
    delimiter = max(counts, key=counts.get) if any(counts.values()) else ","
    reader = csv.DictReader(itertools.chain([header], source), delimiter=delimiter, strict=True)
    fields = reader.fieldnames or []
    if not fields or len(fields) != len(set(fields)):
        raise ValueError("CSV headers must be nonempty and unique.")
    if not recover_invalid and not {"case_id", "case_status"}.issubset(fields):
        raise ValueError("The CSV header must include case_id and case_status.")
    seen = set()
    missing = {"case_id", "case_status", "claim_summary", *FIELDS} - set(fields)
    extra = set(fields) - {"case_id", "case_status", "claim_summary", "expected_v1", *FIELDS}
    schema = [f"Missing CSV header: {f}" for f in sorted(missing)]
    schema += [f"Ignored extra CSV column: {f}" for f in sorted(extra)]
    for row in reader:
        result = ClaimRow({key: value for key, value in row.items() if key is not None})
        result.schema_issues = tuple(schema)
        result.record_errors = (f"CSV line {reader.line_num}: more values than headers",) if None in row else ()
        if any(value is None for value in row.values()):
            result.schema_issues += (f"CSV line {reader.line_num}: missing trailing values",)
        if not recover_invalid:
            if result.record_errors:
                raise ValueError(result.record_errors[0])
            case_id = (result["case_id"] or "").strip()
            if not case_id or case_id in seen:
                raise ValueError(f"CSV line {reader.line_num} has an empty or duplicate case_id: {case_id!r}.")
            seen.add(case_id)
        yield result


def replay_row(claim: Mapping, updated_policy: Callable[[Mapping], Decision] | None = None) -> dict:
    original = decide(claim)
    updated = None
    recheck = None
    explanation = original.get("concise_explanation", original["explanation"])
    if original["case_status"] == "closed":
        updated = original
        recheck = False
        explanation = f"Closed claim: retained its v1 decision. {explanation}"
    elif updated_policy is not None:
        updated = updated_policy(claim)
        recheck = original["recommendation"] != updated["recommendation"]
        explanation = f"v1: {explanation} v2: {updated.get('concise_explanation', updated['explanation'])}"
    else:
        explanation += " Awaiting the official v2 policy."

    return {
        "case_id": original["case_id"],
        "recommendation_v1": original["recommendation"],
        "recommendation_v2": updated["recommendation"] if updated else None,
        "needs_recheck": recheck,
        "rule_v1": original["matched_rule"],
        "rule_v2": updated["matched_rule"] if updated else None,
        "explanation": explanation,
    }


def write_batch(source: Path, destination: Path) -> int:
    from .impact import export_required_csv
    if source.resolve() == destination.resolve() or (destination.exists() and source.samefile(destination)):
        raise ValueError("Choose an output path different from the input CSV.")
    return export_required_csv({"rows": (replay_row(claim) for claim in read_claims(source))}, destination)
