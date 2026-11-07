"""CSV input and replay output used by the judges' batch workflow."""

from __future__ import annotations

import csv
from collections.abc import Callable, Iterator, Mapping
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

from .policy import Decision, decide

OUTPUT_COLUMNS = (
    "case_id", "recommendation_v1", "recommendation_v2", "needs_recheck",
    "rule_v1", "rule_v2", "explanation",
)


def read_claims(path: Path) -> Iterator[dict]:
    seen = set()
    with path.open(encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source, strict=True)
        fields = reader.fieldnames or []
        if not {"case_id", "case_status"}.issubset(fields):
            raise ValueError("The CSV header must include case_id and case_status.")
        if len(fields) != len(set(fields)):
            raise ValueError("The CSV contains duplicate column names.")
        for row in reader:
            if None in row:
                raise ValueError(f"CSV line {reader.line_num} has more values than columns.")
            case_id = (row["case_id"] or "").strip()
            if not case_id or case_id in seen:
                raise ValueError(f"CSV line {reader.line_num} has an empty or duplicate case_id: {case_id!r}.")
            seen.add(case_id)
            yield row


def replay_row(claim: Mapping, updated_policy: Callable[[Mapping], Decision] | None = None) -> dict:
    original = decide(claim)
    updated = None
    recheck = None
    explanation = original["explanation"]
    if original["case_status"] == "closed":
        updated = original
        recheck = False
        explanation = f"Closed claim: retained its v1 decision. {explanation}"
    elif updated_policy is not None:
        updated = updated_policy(claim)
        recheck = original["recommendation"] != updated["recommendation"]
        explanation = f"v1: {explanation} v2: {updated['explanation']}"
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
    if source.resolve() == destination.resolve() or (destination.exists() and source.samefile(destination)):
        raise ValueError("Choose an output path different from the input CSV.")
    count = 0
    temporary = None
    try:
        with NamedTemporaryFile(mode="w", encoding="utf-8", newline="", dir=destination.parent,
                                prefix=f".{destination.name}.", delete=False) as output:
            temporary = Path(output.name)
            writer = csv.DictWriter(output, fieldnames=OUTPUT_COLUMNS)
            writer.writeheader()
            for claim in read_claims(source):
                writer.writerow(replay_row(claim))
                count += 1
        os.replace(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return count
