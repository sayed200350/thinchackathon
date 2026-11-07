"""Deterministic, factual rule evidence and explanations; no model-generated rationale."""
COMPARATORS = {"eq": "==", "ne": "!=", "gt": ">", "ge": ">=", "lt": "<", "le": "<=", "in": "in"}


def display(value):
    if value is None:
        return "UNKNOWN"
    if isinstance(value, bool):
        return str(value)
    return str(value)


def condition_trace(node, facts, evidence):
    from .runtime import predicate, serial, _literal
    value = serial(predicate(node, facts))
    result = "UNKNOWN" if value is None else "MATCH" if value else "NO_MATCH"
    record = {"condition": node, "result": value, "status": result}
    logical = next((op for op in ("all", "any", "not") if op in node), None)
    if logical:
        children = [node[logical]] if logical == "not" else node[logical]
        record["children"] = [condition_trace(child, facts, evidence) for child in children]
        record["expression"] = f"{logical}(" + ", ".join(c["expression"] for c in record["children"]) + ")"
        record["observed"] = {k: v for child in record["children"] for k, v in child["observed"].items()}
    else:
        field, op = node["field"], node["op"]
        observed = serial(facts[field])
        record["observed"] = {field: evidence[field]}
        if op in ("is_known", "is_missing"):
            expression = f"{op}({display(observed)})"
        else:
            target = node["value"]
            parsed = [serial(_literal(field, x)) for x in target] if op == "in" else serial(_literal(field, target))
            record["comparator"], record["threshold_or_value"] = COMPARATORS[op], parsed
            expression = f"{display(observed)} {COMPARATORS[op]} {display(parsed)}"
        record["expression"] = f"{field}: {expression} = {display(value)}"
    return record


def source_reference(policy, rule):
    if "source" in rule:
        return rule["source"]
    if policy.version == "v1":
        clause = "1" if rule["then"] == "human_review" else "2"
        return f"Fictional motor claims policy v1 / decision order / rule {clause} / {rule['id']}"
    return f"Candidate {policy.version} / {rule['id']} (configuration; not an official policy attribution)"


def explain(audit):
    outcome = audit["recommendation"]
    checks = audit["rule_evaluations"]
    matched = [c for c in checks if c["status"] == "MATCH"]
    reasons = [f"{c['expression']} [{c['rule_id']}; {c['source']}]" for c in matched]
    gaps = audit["missing_information"]
    for gap in gaps:
        reasons.append(f"{gap['field']}={display(gap['parsed_value'])} ({gap['state']}; {gap['issue']})")
    if outcome == "routine_processing":
        reasons = [f"{c['expression']} [{c['rule_id']}]" for c in checks]
        reasons.append("All review triggers were tested; none matched. All required structured facts and both documents are present")
    text = f"Recommendation: {outcome}; policy {audit['policy_version']}; primary rule {audit['rule_id']}. "
    text += "; ".join(reasons) + ". " + audit["priority_resolution"] + " "
    text += " ".join(f"{route} excluded: {reason}" for route, reason in audit["alternatives_excluded"].items())
    return text + " This is a next-handling-step recommendation, not payment approval."


def build_audit(claim, policy, primary, outcome, trace, evidence):
    gaps = [{"field": field, **item, "issue": item.get("issue") or "Required document is explicitly absent"}
            for field, item in evidence.items()
            if item["state"] != "known" or (field in ("incident_report_present", "itemized_quote_present") and item["parsed_value"] is False)]
    for gap in gaps:
        gap["source"] = ("Fictional motor claims policy v1 / absent or unreadable input instruction"
                         if policy.version == "v1" else f"Candidate {policy.version} / unknown_handling and required-document rules")
    if outcome == "human_review":
        priority = "Known human-review triggers take precedence over information requests."
        if gaps:
            priority += " The listed information gaps remain unresolved and are retained for the reviewer."
        alternatives = {"request_information": "A known review trigger has higher precedence.",
                        "routine_processing": "At least one known human-review rule matches."}
    elif outcome == "request_information":
        priority = "No known human-review trigger matched; an information-request rule or missing/invalid required evidence takes precedence over routine processing."
        alternatives = {"human_review": "No known review trigger matches; UNKNOWN does not prove a trigger false.",
                        "routine_processing": "An information-request condition matches or required evidence is missing/invalid."}
    else:
        priority = "No review trigger or information gap remains; the policy's routine fallback applies."
        alternatives = {"human_review": "Every review predicate was tested and returned NO_MATCH.",
                        "request_information": "All required facts are known and required documents are present."}
    return {"case_id": claim.case_id, "case_status": claim.case_status, "policy_version": policy.version,
            "policy_hash": policy.fingerprint, "recommendation": outcome, "rule_id": primary,
            "observed_evidence": evidence, "rule_evaluations": trace, "missing_information": gaps,
            "priority_resolution": priority, "alternatives_excluded": alternatives,
            "source_policy": policy.config.get("source", "Fictional motor claims policy v1" if policy.version == "v1" else "Candidate configuration; official status not asserted"),
            "validation_issues": list(claim.schema_issues) + [f"{g['field']}: {g['issue']}" for g in gaps if g["state"] != "known"]}
