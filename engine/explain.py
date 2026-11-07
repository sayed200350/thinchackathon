"""Deterministic reviewer-facing explanation of one engine decision.

Architecture: decision engine -> evaluation trace -> this formatter -> UI.

This module never decides anything and holds no policy rules or thresholds. Everything it
states is read from (a) the evaluation trace the engine recorded while deciding and (b) the
versioned policy configuration that was used. "What could change the outcome" examples are
produced by re-running the SAME engine on an in-memory copy of the claim; real evidence is
never edited. This is rule-based explanation, not AI reasoning.
"""
from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from types import MappingProxyType

from .policy import FIELDS

ROUTE_LABEL = {"routine_processing": "Routine processing", "request_information": "Request information",
               "human_review": "Human review"}
ROUTE_MEANING = {
    "routine_processing": "The claim continues to normal downstream handling. This is not approval to pay.",
    "request_information": "More information is needed before the claim can move on.",
    "human_review": "A person needs to look at this claim before any further handling step.",
}
STATUS_LABEL = {"MATCH": "Triggered", "NO_MATCH": "Not triggered", "UNKNOWN": "Unknown — information needed", None: "Not evaluated"}
RESULT_WORD = {"MATCH": "matched", "NO_MATCH": "not_matched", "UNKNOWN": "unknown"}
ROLE_LABEL = {"decisive": "Decisive", "corroborating": "Also matched (corroborating)",
              "lower_priority": "Matched, lower priority", "unresolved": "Unresolved — information needed",
              "not_applicable": "Not applicable (not triggered)"}
ORDER_OPS = {">", ">=", "<", "<="}
DISCLAIMER = "A recommendation is a next handling step, not an approval or rejection of payment."
EVALUATION_MODE = ("Every policy rule is evaluated for every claim (no short-circuiting), so none of the rules below "
                   "is 'not evaluated'. Route precedence then decides which result is selected.")
PSEUDO_UNKNOWN, PSEUDO_ROUTINE = "INFO_UNKNOWN_REQUIRED_FACT", "ROUTINE_ALL_CHECKS_PASSED"


def money(value) -> str:
    amount = Decimal(str(value))
    return f"€{amount:,.0f}" if amount == amount.to_integral() else f"€{amount:,.2f}"


def show(field, value) -> str:
    if value is None:
        return "unknown"
    if field == "quote_eur":
        return money(value)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        return ", ".join(show(field, v) for v in value)
    return str(value)


def label(field) -> str:
    return FIELDS.get(field, field.replace("_", " "))


def lower_first(text: str) -> str:
    return text[:1].lower() + text[1:] if text and not text[:2].isupper() else text


def _leaves(entry):
    """Flatten a recorded condition trace into its simple field comparisons (logic nodes recurse)."""
    if "children" in entry:
        for child in entry["children"]:
            yield from _leaves(child)
        return
    field = next(iter(entry["observed"]))
    evidence = entry["observed"][field]
    node = entry["condition"]
    op = node["op"]
    expected = entry.get("threshold_or_value")
    comparator = entry.get("comparator") or {"is_known": "is known", "is_missing": "is missing"}.get(op, op)
    yield {"field": field, "label": label(field), "actual": evidence["parsed_value"], "actual_display": show(field, evidence["parsed_value"]),
           "original_value": evidence["raw_value"], "state": evidence["state"], "issue": evidence.get("issue"),
           "operator": comparator, "op": op, "expected": expected, "expected_display": show(field, expected) if expected is not None else None,
           "status": entry["status"], "status_label": STATUS_LABEL[entry["status"]]}


def _phrase(leaf) -> str:
    """One readable comparison, built only from the recorded leaf."""
    actual, op = leaf["actual_display"], leaf["operator"]
    if leaf["actual"] is None:
        return f"{leaf['field']} is unknown"
    if op in ORDER_OPS:
        return f"{leaf['field']}: {actual} {op} {leaf['expected_display']}"
    if op == "==":
        return f"{leaf['field']} is {actual}"
    if op == "!=":
        return f"{leaf['field']} is {actual}, not {leaf['expected_display']}"
    return f"{leaf['field']} {op} {leaf['expected_display']}" if leaf["expected_display"] is not None else f"{leaf['field']} {op}"


def _routes_text(precedence):
    return " → ".join(ROUTE_LABEL[r] for r in precedence)


def _employee_reason(row):
    """Use policy wording, with exact amounts from a simple recorded comparison.

    Do not flatten compound rules: a matched OR branch does not prove every branch.
    """
    if len(row["conditions"]) == 1:
        c = row["conditions"][0]
        words = {">": "above", ">=": "at or above", "<": "below", "<=": "at or below"}
        if c["operator"] in words and c["status"] == "MATCH":
            return f"The {c['label']} is {c['actual_display']}, {words[c['operator']]} the policy's {c['expected_display']} limit."
    return row["description"].rstrip(". ") + "."


def employee_summary(rows, outcome, missing, version, case_status):
    """Short employee copy; classification and thresholds stay in the engine."""
    selected = [r for r in rows if r["status"] == "MATCH" and not r["built_in"] and r["route"] == outcome]
    notes = []
    gaps = list(dict.fromkeys(
        [c["label"] for r in rows if r["status"] == "MATCH" and r["route"] == "request_information" and not r["built_in"]
         for c in r["conditions"] if c["status"] == "MATCH"] + [label(f) for f in missing]))
    if selected:
        why = " ".join(_employee_reason(r) for r in selected[:2])
        if len(selected) > 2:
            notes.append(f"{len(selected) - 2} more reasons are listed in the policy checks below.")
    elif missing:
        why = "Required information is missing or unreadable: " + ", ".join(label(f) for f in missing) + "."
    else:
        why = "Required information is complete and no policy rule requires review or more information."
        # Only a simple upper-limit check supports this reassuring comparison.
        for r in rows:
            if r["status"] != "NO_MATCH" or len(r["conditions"]) != 1:
                continue
            c = r["conditions"][0]
            if c["field"] == "quote_eur" and c["operator"] in (">", ">=") and c["status"] == "NO_MATCH":
                relation = "within" if c["operator"] == ">" else "below"
                why = f"The repair quote is {c['actual_display']}, {relation} the policy's {c['expected_display']} limit. " + why
                break
    if outcome == "human_review":
        next_step = "Send the claim to a claims reviewer."
        if gaps:
            notes.append("Also obtain or confirm: " + ", ".join(gaps) + ". Human review is still required.")
    elif outcome == "request_information":
        next_step = ("Obtain or confirm: " + ", ".join(gaps) + ". Then reassess the claim." if gaps
                     else "Obtain the information required by the policy, then reassess the claim.")
        if selected and missing:
            notes.append("Also missing or unreadable: " + ", ".join(label(f) for f in missing) + ".")
    else:
        next_step = "Continue normal claims processing. This is not payment approval."
    if case_status == "closed":
        next_step = "Keep the recorded decision. This claim is closed."
    basis = {"human_review": "Human review conditions", "request_information": "Required information",
             "routine_processing": "Routine processing conditions"}
    return {"why": why, "next_step": next_step, "notes": notes,
            "policy_basis": f"Policy {version} · {basis[outcome]}"}


def build_detail(claim, policy, config, rules, trace, outcome, primary, missing, evidence):
    version = policy.version
    rule_by_id = {r["id"]: r for r in rules}
    precedence = config["precedence"]

    rows = []
    for rule, entry in zip(rules, trace):
        rows.append({"rule_id": rule["id"], "policy_version": version, "description": rule["reason"],
                     "route": rule["then"], "priority": rule["priority"], "status": entry["status"],
                     "status_label": STATUS_LABEL[entry["status"]], "result": RESULT_WORD[entry["status"]],
                     "evaluated": True, "expression": entry["expression"], "source": entry["source"],
                     "conditions": list(_leaves(entry)), "built_in": False})
    matched = [row for row in rows if row["status"] == "MATCH"]
    for row in rows:
        if row["status"] == "MATCH":
            row["role"] = ("decisive" if row["rule_id"] == primary else
                           "corroborating" if row["route"] == outcome else "lower_priority")
        elif row["status"] == "UNKNOWN":
            row["role"] = "unresolved"
        else:
            row["role"] = "not_applicable"
    if missing:  # the engine's built-in 'required facts must be known' step
        gap_conditions = [{"field": f, "label": label(f), "actual": None, "actual_display": "unknown", "original_value": evidence[f]["raw_value"],
                           "state": evidence[f]["state"], "issue": evidence[f].get("issue"), "operator": "is known", "op": "is_known",
                           "expected": None, "expected_display": None, "status": "UNKNOWN", "status_label": STATUS_LABEL["UNKNOWN"]} for f in missing]
        rows.append({"rule_id": PSEUDO_UNKNOWN, "policy_version": version, "route": "request_information", "priority": None,
                     "description": "Every required fact must be known; an absent or unreadable value is never assumed",
                     "status": "MATCH", "status_label": STATUS_LABEL["MATCH"], "result": "matched", "evaluated": True,
                     "expression": "required facts known? no: " + ", ".join(missing), "source": "Policy unknown_handling",
                     "conditions": gap_conditions, "built_in": True,
                     "role": "decisive" if primary == PSEUDO_UNKNOWN else "corroborating" if outcome == "request_information" else "lower_priority"})
    if primary == PSEUDO_ROUTINE:
        rows.append({"rule_id": PSEUDO_ROUTINE, "policy_version": version, "route": "routine_processing", "priority": None,
                     "description": "No rule was triggered and every required fact is known: the policy's routine fallback applies",
                     "status": "MATCH", "status_label": "Applies", "result": "matched", "evaluated": True,
                     "expression": f"{len(rules)} rules evaluated, none triggered; required facts all known",
                     "source": "Policy fallback", "conditions": [], "built_in": True, "role": "decisive"})

    triggered = [r for r in rows if r["status"] == "MATCH" and not r["built_in"]]
    unresolved = [r for r in rows if r["status"] == "UNKNOWN"]
    decisive_ids = [primary]
    also = [r["rule_id"] for r in rows if r["role"] == "corroborating"]

    # ---- B. key decision factors -------------------------------------------------------------
    factors = []
    for row in triggered:
        factors.append({"status": "Triggered", "kind": "triggered", "rule_id": row["rule_id"], "role": row["role"],
                        "title": row["description"], "facts": [{"field": c["field"], "label": c["label"], "value": c["actual_display"],
                                                                "comparison": _phrase(c)} for c in row["conditions"] if c["status"] == "MATCH"]})
    for field in missing:
        item = evidence[field]
        blocked = [r["rule_id"] for r in rows if not r["built_in"] and r["status"] == "UNKNOWN"
                   and any(c["field"] == field for c in r["conditions"])]
        factors.append({"status": "Missing / Unknown", "kind": "unknown", "field": field, "title": f"{label(field).capitalize()} is not known",
                        "facts": [{"field": field, "label": label(field), "value": "Unknown — information needed",
                                   "comparison": f"{item.get('issue') or 'Absent structured fact'}; not treated as false, zero, present or safe"}],
                        "blocks_rule_ids": blocked})
    for row in rows:  # numerical limits that were checked and not reached are the most useful 'satisfied' facts
        if row["status"] == "NO_MATCH" and not row["built_in"]:
            for c in row["conditions"]:
                if c["operator"] in ORDER_OPS and c["status"] == "NO_MATCH":
                    factors.append({"status": "Satisfied / Not triggered", "kind": "satisfied", "rule_id": row["rule_id"],
                                    "title": f"Not the case: {lower_first(row['description'])}", "facts": [{"field": c["field"], "label": c["label"], "value": c["actual_display"],
                                                                            "comparison": f"{c['actual_display']} {c['operator']} {c['expected_display']} is false"}]})
    groups = {}
    for row in rows:
        if not row["built_in"]:
            groups.setdefault(row["route"], []).append(row)
    for route in (r for r in precedence if r in groups and r != outcome):
        group = groups[route]
        clear = [r for r in group if r["status"] == "NO_MATCH"]
        if clear and not any(r["status"] == "MATCH" for r in group):
            unk = sum(r["status"] == "UNKNOWN" for r in group)
            text = f"{len(clear)} of {len(group)} {ROUTE_LABEL[route].lower()} checks not triggered" + (f"; {unk} could not be evaluated" if unk else "")
            factors.append({"status": "Satisfied / Not triggered", "kind": "satisfied_group", "route": route, "title": text, "facts": []})

    # ---- A. summary ---------------------------------------------------------------------------
    gaps_note = "" if not missing else (" The missing information (" + ", ".join(label(f) for f in missing) + ") is still listed for the reviewer.")
    if outcome == "human_review":
        reasons = [f"{lower_first(r['description'])} ({'; '.join(_phrase(c) for c in r['conditions'] if c['status'] == 'MATCH')})" for r in triggered[:3]]
        more = f" and {len(triggered) - 3} more" if len(triggered) > 3 else ""
        sentence1 = "Human review is required because " + "; also ".join(reasons) + more + "."
        sentence2 = ("A known trigger outranks missing or absent information." + gaps_note) if (missing or any(r["route"] == "request_information" for r in triggered)) else \
                    "A known review trigger means routine handling cannot be used."
    elif outcome == "request_information":
        parts = [f"{lower_first(r['description'])} ({'; '.join(_phrase(c) for c in r['conditions'] if c['status'] == 'MATCH')})" for r in triggered]
        for field in missing:
            blocked = [lower_first(r["description"]) for r in unresolved if not r["built_in"] and any(c["field"] == field for c in r["conditions"])]
            parts.append(f"the {label(field)} is not known" + (f", so these checks cannot be evaluated: {'; '.join(blocked)}" if blocked else ""))
        sentence1 = "More information is needed before routine processing can be considered: " + "; ".join(parts) + "."
        sentence2 = "No known review trigger matched. Unknown values are not treated as zero, false or safe." if missing else "No known review trigger matched."
    else:
        sentence1 = f"No review condition matched and every required fact and document is present ({len(rules)} policy checks evaluated, none triggered)."
        sentence2 = "The claim continues to normal downstream handling. Routine processing is not approval to pay."

    # ---- D. why not the other outcomes --------------------------------------------------------
    why_not = []
    for route in precedence:
        if route == outcome:
            continue
        hr_hits = [r["rule_id"] for r in triggered if r["route"] == "human_review"]
        info_gaps = sorted({c["field"] for r in rows if r["route"] == "request_information" and r["status"] != "NO_MATCH"
                            for c in r["conditions"] if c["status"] != "NO_MATCH"})
        if route == "human_review":
            checked = [r for r in rows if r["route"] == "human_review" and not r["built_in"]]
            clear = sum(r["status"] == "NO_MATCH" for r in checked)
            hr_unknown = [r for r in checked if r["status"] == "UNKNOWN"]
            text = f"No known escalation trigger matched ({clear} of {len(checked)} checks not triggered)."
            if hr_unknown:
                fields = sorted({c["field"] for r in hr_unknown for c in r["conditions"] if c["status"] == "UNKNOWN"})
                text += (f" {len(hr_unknown)} escalation check(s) could not be evaluated because information is missing "
                         f"({', '.join(fields)}); an unknown value is neither a trigger nor evidence of safety.")
        elif route == "request_information":
            if outcome == "human_review":
                text = (f"A known escalation trigger ({', '.join(hr_hits)}) outranks the information request "
                        f"in the policy's precedence ({_routes_text(precedence)}).")
                if info_gaps:
                    text += f" The information gaps are still reported: {', '.join(info_gaps)}."
            else:
                text = f"No information-request condition was triggered and all {len(FIELDS)} required facts are known."
        else:  # routine_processing
            if outcome == "human_review":
                text = f"Routine processing requires that no known review trigger matches, but {', '.join(hr_hits)} matched."
            else:
                needs = [r["rule_id"] for r in triggered if r["route"] == "request_information"] + (["unknown " + ", ".join(missing)] if missing else [])
                text = "Routine processing requires all facts known and no information-request condition, but: " + "; ".join(needs) + "."
        why_not.append({"route": route, "label": ROUTE_LABEL[route], "text": text})

    detail = {
        "schema": "decision-explanation/1", "case_id": claim.case_id, "case_status": claim.case_status, "policy_version": version,
        "policy_hash": policy.fingerprint, "recommendation": outcome, "recommendation_label": ROUTE_LABEL[outcome],
        "meaning": ROUTE_MEANING[outcome], "summary": f"{sentence1} {sentence2}", "summary_sentences": [sentence1, sentence2],
        "disclaimer": DISCLAIMER, "decisive_rule_ids": decisive_ids, "corroborating_rule_ids": also,
        "unknown_fields": list(missing), "factors": factors, "rules": rows, "evaluation_mode": EVALUATION_MODE,
        "precedence": {"order": list(precedence), "text": (f"Policy {version} applies routes in this order: {_routes_text(precedence)}. "
                                                              "Within a route, rules are ordered by priority. "
                                                              f"The first route with a match wins, so a known trigger outranks missing information; selected by {primary}.")},
        "why_not": why_not, "counterfactuals": [],
        "employee": employee_summary(rows, outcome, missing, version, claim.case_status),
    }
    return detail


def _hypothetical_claim(claim, field, value):
    from .runtime import serial
    facts = dict(claim.facts)
    facts[field] = value
    evidence = {name: dict(item) for name, item in claim.evidence.items()}
    evidence[field].update(raw_value=str(serial(value)), parsed_value=serial(value), state="known", issue=None)
    return replace(claim, facts=MappingProxyType(facts), evidence=MappingProxyType({k: MappingProxyType(v) for k, v in evidence.items()}))


def counterfactuals(claim, policy, decision):
    """Verified what-if examples. Each one re-runs the same engine on an in-memory copy of the claim."""
    from .runtime import evaluate
    detail = decision["audit"]["detail"]
    current = decision["recommendation"]
    levers, seen = [], set()
    for row in detail["rules"]:
        if row["built_in"] or len(row["conditions"]) != 1:
            continue
        cond = row["conditions"][0]
        field, op = cond["field"], cond["op"]
        if field == "quote_eur" and op in ("gt", "ge") and cond["status"] in ("MATCH", "UNKNOWN") and cond["expected"] is not None:
            limit = Decimal(str(cond["expected"]))
            value = limit if op == "gt" else limit - Decimal("0.01")
            lead = (f"If a verified repair estimate of {money(value)} or less were supplied" if cond["status"] == "MATCH"
                    else f"If the repair quote were provided at {money(value)} or less")
            levers.append((row, field, value, lead))
        elif row["route"] == "request_information" and op == "eq" and cond["expected"] is False and cond["status"] == "MATCH" \
                and field not in ("claim_type", "repair_type", "quote_eur"):
            levers.append((row, field, True, f"If the {cond['label']} were supplied"))
    results = []
    for row, field, value, lead in levers:
        if (field, str(value)) in seen:
            continue
        seen.add((field, str(value)))
        after = evaluate(_hypothetical_claim(claim, field, value), policy, _detail=False)
        if row["rule_id"] in after["reason_codes"]:
            continue  # this change would not remove the condition; nothing to show
        remaining = [rid for rid in after["reason_codes"] if rid not in (PSEUDO_ROUTINE,)]
        remaining_text = [f"{rid}" for rid in remaining] + [f"unknown {f}" for f in after["missing_or_invalid_fields"] if PSEUDO_UNKNOWN not in remaining]
        new = after["recommendation"]
        removed = lower_first(row["description"])
        if new != current:
            text = f"{lead}, the engine would recommend {ROUTE_LABEL[new].lower()} instead of {ROUTE_LABEL[current].lower()}"
            text += f" (condition removed: {removed})." if new == "routine_processing" else f"; still outstanding: {', '.join(remaining_text)}."
            if new == "routine_processing":
                text += " That would be routine handling only, not approval to pay."
        else:
            text = (f"{lead}, only the condition “{removed}” would be removed. The recommendation would still be "
                    f"{ROUTE_LABEL[new].lower()} because: {', '.join(remaining_text) or 'other conditions remain'}.")
        results.append({"verified": True, "hypothetical_only": True, "removes_rule_id": row["rule_id"], "field": field,
                        "hypothetical_value": show(field, value), "current_recommendation": current, "resulting_recommendation": new,
                        "changes_recommendation": new != current, "remaining_blockers": remaining, "text": text,
                        "caution": "Hypothetical only: re-checked by the same engine on a copy; the claim's evidence is unchanged."})
    return results
