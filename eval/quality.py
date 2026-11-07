"""Score labelled development claims with the same decision function used by the API."""

import argparse
from collections import Counter
import csv
import json
from pathlib import Path

from engine import decide
from engine.batch import read_claims
from engine.policy import FIELDS

ROUTES = ("routine_processing", "request_information", "human_review")


def score(source: Path) -> dict:
    confusion = {label: {prediction: 0 for prediction in ROUTES} for label in ROUTES}
    errors = []
    blank_case_ids = []
    counts = Counter()
    for row in read_claims(source):
        expected = row.get("expected_v1")
        if expected not in ROUTES:
            raise ValueError(f"{row['case_id']}: a valid expected_v1 label is required to measure accuracy.")
        decision = decide(row)
        actual = decision["recommendation"]
        if any(not (row.get(field) or "").strip() for field in FIELDS):
            blank_case_ids.append(decision["case_id"])
            counts["correct_with_blanks"] += int(actual == expected)
        counts["cases"] += 1
        confusion[expected][actual] += 1
        if expected == actual:
            counts["correct"] += 1
        else:
            errors.append({"case_id": decision["case_id"], "expected": expected,
                           "actual": actual, "matched_rule": decision["matched_rule"]})
            counts[actual] += 1

    total = counts["cases"]
    if not total:
        raise ValueError("No labelled cases to score.")

    def metric(count: int) -> dict:
        return {"count": count, "denominator": total, "rate": count / total}

    return {
        "policy_version": "v1",
        "label_column": "expected_v1",
        "accuracy": metric(counts["correct"]),
        "incorrect_routine_processing": metric(counts["routine_processing"]),
        "unnecessary_human_review": metric(counts["human_review"]),
        "cases_with_blank_facts": {
            "case_ids": blank_case_ids,
            "correct": counts["correct_with_blanks"],
            "denominator": len(blank_case_ids),
        },
        "confusion_expected_by_predicted": confusion,
        "errors": errors,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(score(args.input), indent=2))
    except (OSError, ValueError, csv.Error) as error:
        parser.exit(1, f"error: {error}\n")


if __name__ == "__main__":
    main()
