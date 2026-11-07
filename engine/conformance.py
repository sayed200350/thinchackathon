"""Synthetic checks of declared predicates, separate from independent accuracy."""
from decimal import Decimal
from .runtime import UNKNOWN, evaluate, parse_claim, predicate, serial, _literal

BASE = dict(case_id="SYNTHETIC", case_status="open", claim_summary="Synthetic conformance input",
            policy_active_on_incident="true", claim_type="motor_own_damage", repair_type="standard",
            quote_eur="650", incident_report_present="true", itemized_quote_present="true",
            injury_reported="false", liability_disputed="false", duplicate_flag="false", evidence_conflict="false")


def leaves(node):
    if "not" in node:
        yield from leaves(node["not"])
    elif "all" in node or "any" in node:
        for child in node.get("all", node.get("any")):
            yield from leaves(child)
    else:
        yield node


def variants(node):
    """Expected leaf truth tables are computed without calling the interpreter."""
    field, op = node["field"], node["op"]
    if op in ("is_known", "is_missing"):
        yield BASE[field], op == "is_known"
        yield "", op == "is_missing"
        return
    yield "", UNKNOWN
    targets = node["value"] if op == "in" else [node["value"]]
    target = _literal(field, targets[0])
    if field == "quote_eur":
        step = min(Decimal("0.01"), Decimal(1).scaleb(target.as_tuple().exponent))
        if op in ("gt", "ge", "lt", "le"):
            truth = {"gt": [False, False, True], "ge": [False, True, True],
                     "lt": [True, False, False], "le": [True, True, False]}[op]
            for amount, expected in zip([target-step, target, target+step], truth):
                yield str(amount), UNKNOWN if amount < 0 else expected
            return
        other = max([_literal(field, x) for x in targets]) + 1
    elif isinstance(target, bool):
        other = not target
    else:
        other = "synthetic_nonmatching_category"
        while other in [_literal(field, x) for x in targets]:
            other += "_other"
    for value in (target, other):
        match = value in [_literal(field, x) for x in targets]
        yield serial(value), not match if op == "ne" else match


def run_checks(policy):
    checks = []
    for rule in policy.config["rules"]:
        for index, node in enumerate(leaves(rule["if"])):
            for raw, expected in variants(node):
                claim = parse_claim(dict(BASE, **{node["field"]: raw}))
                actual = predicate(node, claim.facts)
                checks.append(dict(rule_id=rule["id"], leaf=index, field=node["field"], raw=raw,
                                   expected=serial(expected), actual=serial(actual), passed=actual is expected))
                # A known matching review predicate must outrank missing facts,
                # including when it is part of a compound expression.
                if rule["then"] == "human_review" and predicate(rule["if"], claim.facts) is True:
                    for missing in ("incident_report_present", "itemized_quote_present"):
                        conflict = parse_claim(dict(claim.raw, **{missing: ""}))
                        if predicate(rule["if"], conflict.facts) is True:
                            result = evaluate(conflict, policy)
                            checks.append(dict(rule_id=rule["id"], check="review_precedence", missing=missing,
                                               passed=result["recommendation"] == "human_review"))
    return dict(evidence_type="synthetic_policy_conformance", policy_version=policy.version,
                total=len(checks), failed=sum(not c["passed"] for c in checks), checks=checks,
                limitation="Leaf boundaries and selected precedence interactions, not exhaustive compound-rule coverage or independent accuracy.")
