"""Independent labelled quality, never policy-generated ground truth."""
from collections import Counter
from .runtime import ROUTES, evaluate, parse_claim


def measure(claims, policy, label_column="expected_v1"):
    if label_column == "expected_v1" and policy.version != "v1":
        raise ValueError("expected_v1 labels cannot measure another policy version's independent accuracy.")
    counts, predictions, errors, missing_cases, information_gaps = Counter(), Counter(), [], [], []
    confusion = {a: {b: 0 for b in ROUTES} for a in ROUTES}
    for row in claims:
        truth = row.get(label_column)
        if truth not in ROUTES:
            raise ValueError(f"{row.get('case_id')}: independent {label_column} label required.")
        decision = evaluate(parse_claim(row), policy)
        actual = decision["recommendation"]
        if decision["missing_or_invalid_fields"]:
            missing_cases.append(dict(case_id=decision["case_id"], fields=decision["missing_or_invalid_fields"],
                                      recommendation=actual, primary_rule=decision["primary_rule_id"]))
        if decision["audit"]["missing_information"]:
            information_gaps.append(dict(case_id=decision["case_id"],
                                         fields=[g["field"] for g in decision["audit"]["missing_information"]],
                                         recommendation=actual))
        counts["total"] += 1
        counts["correct"] += actual == truth
        counts["incorrect_routine"] += actual == "routine_processing" and truth != actual
        counts["unnecessary_human"] += actual == "human_review" and truth != actual
        predictions[actual] += 1
        confusion[truth][actual] += 1
        if actual != truth:
            errors.append(dict(case_id=decision["case_id"], expected=truth, actual=actual,
                               primary_rule=decision["primary_rule_id"], cause=decision["concise_explanation"]))
    total = counts["total"]
    if not total:
        raise ValueError("No labelled cases to score.")
    def metric(key):
        return dict(count=counts[key], denominator=total, rate=counts[key] / total)
    return dict(policy_version=policy.version, policy_fingerprint=policy.fingerprint,
                label_column=label_column, accuracy=metric("correct"),
                incorrect_routine_processing=metric("incorrect_routine"),
                unnecessary_human_review=metric("unnecessary_human"),
                recommendation_counts=dict(predictions), confusion=confusion, errors=errors,
                missing_inputs={"count": len(missing_cases), "denominator": total, "cases": missing_cases},
                information_gaps_including_absent_documents={"count": len(information_gaps), "denominator": total, "cases": information_gaps},
                limitation=f"Only {total} labelled examples; this does not establish production accuracy.")
