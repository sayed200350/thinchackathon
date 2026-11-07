"""Validated declarative policies and pure, three-valued claim evaluation."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import Enum
import hashlib
import json
from pathlib import Path
from collections.abc import Mapping

from .policy import FIELDS, ROUTES, _fact

ENGINE_VERSION = "0.2.0"
DEFAULT_POLICY = Path(__file__).parent / "configs" / "policy_v1.json"
PRECEDENCE = ["human_review", "request_information", "routine_processing"]
V1_FINGERPRINT = "5421f441d3f296fb6951661922d106b77078c59b54b4a2815b42218c7e1fa38a"
REPAIR_TYPES = ["standard", "ev_high_voltage_battery"]


class Unknown(Enum):
    VALUE = "unknown"


UNKNOWN = Unknown.VALUE


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def serial(value):
    if value is UNKNOWN:
        return None
    if isinstance(value, Decimal):
        return format(value, "f")
    return value


@dataclass(frozen=True)
class Claim:
    case_id: str
    case_status: str
    facts: Mapping
    raw: Mapping
    warnings: tuple[str, ...]
    evidence: Mapping
    schema_issues: tuple[str, ...]


class RecordValidationError(ValueError):
    def __init__(self, issues, case_id=None):
        self.issues, self.case_id = issues, case_id
        super().__init__("; ".join(issues))

    def as_dict(self):
        return {"code": "invalid_record", "case_id": self.case_id, "issues": self.issues}


@dataclass(frozen=True)
class Policy:
    # Store canonical JSON, rather than a mutable caller-owned dictionary.
    document: str
    source_fingerprint: str

    @property
    def config(self):
        return json.loads(self.document)

    @property
    def version(self):
        return self.config["version"]

    @property
    def fingerprint(self):
        return fingerprint(self.config)


def parse_claim(raw: Mapping) -> Claim:
    from types import MappingProxyType
    if not isinstance(raw, Mapping):
        raise RecordValidationError(["Claim must be an object."])
    case_id = raw.get("case_id")
    case_id = case_id.strip() if isinstance(case_id, str) else ""
    status = raw.get("case_status")
    status = status.strip().lower() if isinstance(status, str) else ""
    issues = []
    if not case_id:
        issues.append("case_id must be a nonempty string.")
    if status not in ("open", "closed"):
        issues.append("case_status must be open or closed.")
    if issues:
        raise RecordValidationError(issues, case_id or None)
    if getattr(raw, "record_errors", ()):
        raise RecordValidationError(list(raw.record_errors), case_id)
    facts, evidence = {}, {}
    for field in FIELDS:
        value = _fact(field, raw.get(field))
        if field in ("claim_type", "repair_type") and value is not None:
            value = value.casefold()
        facts[field] = UNKNOWN if value is None else value
        raw_value = raw.get(field)
        missing = raw_value is None or (isinstance(raw_value, str) and not raw_value.strip())
        state = "known" if value is not None else "missing" if missing else "invalid"
        evidence[field] = {"raw_value": _safe_raw(raw_value), "parsed_value": serial(facts[field]), "state": state,
                           "issue": None if state == "known" else "Absent structured fact" if missing else "Unsupported or unreadable structured value"}
    warnings = tuple(f"{field}: missing or unreadable structured fact"
                     for field, value in facts.items() if value is UNKNOWN)
    # Labels, narrative and arbitrary extra columns are not decision evidence.
    clean = {field: _safe_raw(raw.get(field)) for field in ("case_id", "case_status", *FIELDS)}
    schema = tuple(getattr(raw, "schema_issues", ()))
    return Claim(case_id, status, MappingProxyType(facts), MappingProxyType(clean), warnings,
                 MappingProxyType({field: MappingProxyType(item) for field, item in evidence.items()}), schema)


def _safe_raw(value):
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, (float, Decimal)):
        return str(value)
    return f"<unsupported {type(value).__name__}>"


def _literal(field, value):
    if field == "quote_eur":
        if isinstance(value, bool) or not isinstance(value, (str, int)):
            raise ValueError("Policy amounts must be decimal strings or integers.")
        try:
            amount = Decimal(value)
        except InvalidOperation as error:
            raise ValueError("Invalid policy amount.") from error
        if not amount.is_finite() or amount < 0:
            raise ValueError("Policy amounts must be finite and nonnegative.")
        return amount
    if field in ("claim_type", "repair_type"):
        if not isinstance(value, str) or not value.strip() or _fact(field, value) is None:
            raise ValueError("Category predicates require known, nonempty strings.")
        return value.strip().casefold()
    if type(value) is not bool:
        raise ValueError(f"{field} requires a Boolean policy value.")
    return value


def validate_predicate(node, depth=0):
    if depth > 20:
        raise ValueError("Policy predicates exceed maximum nesting depth 20.")
    if not isinstance(node, dict):
        raise ValueError("A predicate must be an object.")
    for operator in ("all", "any", "not"):
        if operator in node:
            if set(node) != {operator}:
                raise ValueError("Logical predicates must have exactly one operator.")
            children = [node[operator]] if operator == "not" else node[operator]
            if not isinstance(children, list) or not children:
                raise ValueError("Logical predicates require nonempty children.")
            for child in children:
                validate_predicate(child, depth + 1)
            return
    field, op = node.get("field"), node.get("op")
    if not isinstance(field, str) or field not in FIELDS:
        raise ValueError(f"Unknown policy field: {field!r}")
    if op not in ("eq", "ne", "gt", "ge", "lt", "le", "in", "is_known", "is_missing"):
        raise ValueError(f"Unsupported operator: {op!r}")
    expected = {"field", "op"} if op in ("is_known", "is_missing") else {"field", "op", "value"}
    if set(node) != expected:
        raise ValueError("Unexpected or missing predicate keys.")
    if op in ("is_known", "is_missing"):
        return
    if op in ("gt", "ge", "lt", "le") and field != "quote_eur":
        raise ValueError("Ordering operators only support quote_eur.")
    values = node["value"] if op == "in" else [node["value"]]
    if not isinstance(values, list) or not values:
        raise ValueError("Membership requires a nonempty list.")
    for value in values:
        _literal(field, value)


def validate_policy(config):
    required = {"policy_id", "version", "precedence", "rules", "unknown_handling", "fallback"}
    if not isinstance(config, dict) or not required.issubset(config) or set(config) - required - {"source", "enumerations"}:
        raise ValueError(f"Policy must contain exactly: {sorted(required)}")
    for name in ("policy_id", "version"):
        if not isinstance(config[name], str) or not config[name].strip():
            raise ValueError(f"Policy requires {name}.")
    if config["version"] == "v1" and fingerprint(config) != V1_FINGERPRINT:
        raise ValueError("Policy v1 is immutable. Changed content requires a distinct version.")
    if "source" in config and (not isinstance(config["source"], str) or not config["source"].strip()):
        raise ValueError("Policy source must be a nonempty attribution string.")
    enums = config.get("enumerations", {"repair_type": REPAIR_TYPES})
    if not isinstance(enums, dict) or set(enums) != {"repair_type"}:
        raise ValueError("enumerations must define repair_type.")
    values = enums["repair_type"]
    if not isinstance(values, list) or not values or any(not isinstance(v, str) or _fact("repair_type", v) is None for v in values):
        raise ValueError("repair_type enumeration must contain readable strings.")
    if config["precedence"] != PRECEDENCE or config["fallback"] != "routine_processing":
        raise ValueError("Policy must preserve human-review precedence and routine fallback.")
    unknown = config["unknown_handling"]
    if not isinstance(unknown, dict) or set(unknown) != {"required_fields", "outcome"}:
        raise ValueError("Explicit unknown handling is required.")
    if unknown["outcome"] != "request_information" or not isinstance(unknown["required_fields"], list):
        raise ValueError("Unknown required facts must request information.")
    fields = unknown["required_fields"]
    if any(not isinstance(f, str) or f not in FIELDS for f in fields) or len(fields) != len(set(fields)):
        raise ValueError("Required fields must be unique recognized fields.")
    if set(fields) != set(FIELDS):
        raise ValueError("All supplied structured facts are required for safe assessment.")
    if not isinstance(config["rules"], list) or not config["rules"]:
        raise ValueError("Policy rules must be a nonempty list.")
    ids, priorities = set(), set()
    for rule in config["rules"]:
        if not isinstance(rule, dict) or not {"id", "priority", "if", "then", "reason"}.issubset(rule) or set(rule) - {"id", "priority", "if", "then", "reason", "source"}:
            raise ValueError("Rules require id, priority, if, then and reason.")
        identifier, priority = rule["id"], rule["priority"]
        if not isinstance(identifier, str) or not identifier.strip() or identifier in ids or identifier in {"INFO_UNKNOWN_REQUIRED_FACT", "ROUTINE_ALL_CHECKS_PASSED"}:
            raise ValueError("Rule IDs must be unique nonempty strings, excluding reserved IDs.")
        if type(priority) is not int or priority in priorities:
            raise ValueError("Rule priorities must be unique integers; ties are rejected.")
        if rule["then"] not in ("human_review", "request_information"):
            raise ValueError("Explicit rules may only review or request information.")
        if not isinstance(rule["reason"], str) or not rule["reason"].strip():
            raise ValueError("Each rule requires a readable reason.")
        if "source" in rule and (not isinstance(rule["source"], str) or not rule["source"].strip()):
            raise ValueError("Rule source must be a nonempty attribution string.")
        validate_predicate(rule["if"])
        ids.add(identifier)
        priorities.add(priority)


def policy_from_dict(config, source_fingerprint=None):
    validate_policy(config)
    document = json.dumps(config, sort_keys=True)
    return Policy(document, source_fingerprint or fingerprint(config))


def load_policy(path=DEFAULT_POLICY):
    data = Path(path).read_bytes()
    return policy_from_json(data.decode("utf-8-sig"), hashlib.sha256(data).hexdigest())


def policy_from_json(text, source_fingerprint=None):
    if not isinstance(text, str):
        raise ValueError("Policy JSON must be text.")
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"Duplicate JSON key: {key}")
            result[key] = value
        return result
    return policy_from_dict(json.loads(text.lstrip("\ufeff"), object_pairs_hook=unique),
                            source_fingerprint or hashlib.sha256(text.encode("utf-8")).hexdigest())


def predicate(node, facts):
    """Kleene three-valued logic: NOT unknown remains unknown."""
    if "not" in node:
        result = predicate(node["not"], facts)
        return UNKNOWN if result is UNKNOWN else not result
    for op in ("all", "any"):
        if op in node:
            results = [predicate(child, facts) for child in node[op]]
            decisive = False if op == "all" else True
            if any(value is decisive for value in results):
                return decisive
            return UNKNOWN if UNKNOWN in results else not decisive
    field, op = node["field"], node["op"]
    value = facts[field]
    if op == "is_known":
        return value is not UNKNOWN
    if op == "is_missing":
        return value is UNKNOWN
    if value is UNKNOWN:
        return UNKNOWN
    target = node.get("value")
    if op == "in":
        return value in [_literal(field, item) for item in target]
    target = _literal(field, target)
    if op == "eq": return value == target
    if op == "ne": return value != target
    if op == "gt": return value > target
    if op == "ge": return value >= target
    if op == "lt": return value < target
    if op == "le": return value <= target
    raise ValueError(f"Unsupported operator: {op}")


def evaluate(claim: Claim, policy: Policy, _detail: bool = True):
    from .audit import condition_trace, source_reference, build_audit, explain
    config = policy.config
    validate_policy(config)
    facts = dict(claim.facts)
    evidence = {field: dict(item) for field, item in claim.evidence.items()}
    allowed = config.get("enumerations", {"repair_type": REPAIR_TYPES})["repair_type"]
    if facts["repair_type"] is not UNKNOWN and facts["repair_type"] not in [v.strip().casefold() for v in allowed]:
        facts["repair_type"] = UNKNOWN
        evidence["repair_type"].update(parsed_value=None, state="invalid", issue="Unrecognized repair_type; cannot establish a complete assessment")
    rules = sorted(config["rules"], key=lambda r: (PRECEDENCE.index(r["then"]), r["priority"]))
    trace = [dict(condition_trace(r["if"], facts, evidence), rule_id=r["id"], outcome=r["then"],
                  priority=r["priority"], source=source_reference(policy, r)) for r in rules]
    matched = [r for r, t in zip(rules, trace) if t["result"] is True]
    missing = [field for field in config["unknown_handling"]["required_fields"] if facts[field] is UNKNOWN]
    reasons = [r["id"] for r in matched]
    if missing:
        reasons.append("INFO_UNKNOWN_REQUIRED_FACT")
    if matched:
        primary, outcome = matched[0]["id"], matched[0]["then"]
    elif missing:
        primary, outcome = "INFO_UNKNOWN_REQUIRED_FACT", "request_information"
    else:
        primary, outcome = "ROUTINE_ALL_CHECKS_PASSED", "routine_processing"
        reasons.append(primary)
    audit = build_audit(claim, policy, primary, outcome, trace, evidence)
    explanation = explain(audit)
    audit["conclusion"] = explanation
    if _detail:  # reviewer-facing explanation, formatted only from the trace recorded above
        from .explain import build_detail
        audit["detail"] = build_detail(claim, policy, config, rules, trace, outcome, primary, missing, evidence)
    facts = {field: serial(value) for field, value in facts.items()}
    result = {"case_id": claim.case_id, "case_status": claim.case_status,
            "policy_version": policy.version, "recommendation": outcome,
            "primary_rule_id": primary, "rule_id": primary, "reason_codes": reasons,
            "missing_or_invalid_fields": missing, "validation_warnings": audit["validation_issues"],
            "explanation": explanation, "trace": trace, "audit": audit,
            "concise_explanation": f"{outcome} ({policy.version}, {primary}); " +
                ("; ".join(t["expression"] for t in trace if t["status"] == "MATCH") or "no known review trigger") +
                f"; unresolved: {', '.join(missing) or 'none'}. Next handling step only.",
            "normalized_facts": facts, "raw_evidence": dict(claim.raw),
            "input_fingerprint": fingerprint({"case_id": claim.case_id, "case_status": claim.case_status,
                                                **{field: serial(value) for field, value in claim.facts.items()}}),
            "policy_fingerprint": policy.fingerprint, "policy_hash": policy.fingerprint, "source_policy_fingerprint": policy.source_fingerprint,
            "engine_version": ENGINE_VERSION}
    if _detail:  # what-if checks re-run this same engine on in-memory copies; real evidence is never edited
        from .explain import counterfactuals
        employee = audit["detail"]["employee"]
        result["concise_explanation"] = " ".join([
            employee["policy_basis"] + ":", employee["why"], employee["next_step"], *employee["notes"]])
        audit["detail"]["counterfactuals"] = counterfactuals(claim, policy, result)
    return result
