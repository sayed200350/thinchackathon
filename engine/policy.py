"""Deterministic triage for the supplied fictional motor-claims policy."""

from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
import re
from typing import Optional, TypedDict, Union


class Decision(TypedDict):
    case_id: str
    case_status: str
    policy_version: str
    recommendation: str
    matched_rule: str
    supporting_facts: dict[str, Union[str, bool, int, float, None]]
    explanation: str


# The CSV's structured fields decide the route. case_id and case_status identify
# the record; neither the free-text summary nor the development label is evidence.
FIELDS = {
    "policy_active_on_incident": "policy active on the incident date",
    "claim_type": "claim type",
    "repair_type": "repair type",
    "quote_eur": "repair quote",
    "incident_report_present": "incident report",
    "itemized_quote_present": "itemized quote",
    "injury_reported": "injury status",
    "liability_disputed": "liability dispute status",
    "duplicate_flag": "duplicate claim flag",
    "evidence_conflict": "evidence conflict status",
}
ROUTES = ("routine_processing", "request_information", "human_review")
REVIEW_FLAGS = {
    "injury_reported": "an injury was reported",
    "liability_disputed": "liability is disputed",
    "duplicate_flag": "the claim was flagged as a duplicate",
    "evidence_conflict": "the evidence conflicts",
}
DOCUMENTS = ("incident_report_present", "itemized_quote_present")
UNKNOWN = {"", "n/a", "na", "unknown", "unreadable", "null", "none", "nan", "?",
           "-", "not available", "not provided", "#value!", "#n/a", "#ref!", "#num!",
           "#name?", "#div/0!", "#null!"}
PLAIN_AMOUNT = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)")
BOOLEAN = {"true": True, "false": False}


def _text(value: object) -> str:
    return "" if value is None else str(value).strip()


Fact = Optional[Union[str, bool, Decimal]]


def _fact(field: str, raw: object) -> Fact:
    text = _text(raw)
    if not isinstance(raw, (str, bool, int, float, Decimal)) or text.casefold() in UNKNOWN:
        return None
    if field == "quote_eur":
        if isinstance(raw, str) and not PLAIN_AMOUNT.fullmatch(text):
            return None
        try:
            amount = Decimal(text)
        except InvalidOperation:
            return None
        return amount if amount.is_finite() and amount >= 0 else None
    if field in ("claim_type", "repair_type"):
        return text if isinstance(raw, str) and re.fullmatch(r"[A-Za-z][A-Za-z0-9_ -]*", text) else None
    return BOOLEAN.get(text.casefold())


def _evidence_value(value: Fact) -> Union[str, bool, int, float, None]:
    # Keep exact decimal cents when the value cannot round-trip as a JSON number.
    if isinstance(value, Decimal):
        if value == value.to_integral_value() and value <= 2**53 - 1:
            return int(value)
        number = float(value)
        if Decimal(str(number)) == value:
            return number
        return str(value)
    return value


def decide(claim: Mapping, policy_version: str = "v1") -> Decision:
    """Return the JSON-ready shared result for a raw CSV row or API record."""
    if policy_version != "v1":
        raise ValueError(f"Unsupported policy version: {policy_version}. Available: v1.")
    from .runtime import evaluate, load_policy, parse_claim
    assessment = evaluate(parse_claim(claim), load_policy())
    route = assessment["recommendation"]
    rule = ("v1.1" if route == "human_review" else "v1.3" if route == "routine_processing"
            else "v1.2" if assessment["primary_rule_id"] != "INFO_UNKNOWN_REQUIRED_FACT" else "v1.missing")
    # Legacy keys remain, with the same factual audit as the primary API.
    return dict(assessment, matched_rule=rule,
                supporting_facts=assessment["normalized_facts"])
