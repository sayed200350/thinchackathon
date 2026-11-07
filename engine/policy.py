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
BOOLEAN = {"true": True, "false": False, "1": True, "0": False,
           "yes": True, "no": False}


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
        return text if isinstance(raw, str) else None
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
    case_id = _text(claim.get("case_id"))
    status = _text(claim.get("case_status")).lower()
    if not case_id:
        raise ValueError("A claim requires a nonempty case_id.")
    if status not in ("open", "closed"):
        raise ValueError(f"{case_id}: case_status must be open or closed.")

    facts = {field: _fact(field, claim.get(field)) for field in FIELDS}
    triggers = {}
    if facts["policy_active_on_incident"] is False:
        triggers["policy_active_on_incident"] = "the policy was inactive on the incident date"
    if facts["claim_type"] is not None and facts["claim_type"].casefold() != "motor_own_damage":
        triggers["claim_type"] = "the claim falls outside motor own-damage cover"
    for field, reason in REVIEW_FLAGS.items():
        if facts[field] is True:
            triggers[field] = reason
    quote = facts["quote_eur"]
    if quote is not None and quote > 1500:
        triggers["quote_eur"] = f"the €{quote} quote exceeds €1500"

    missing = [field for field, value in facts.items() if value is None]
    absent_docs = [field for field in DOCUMENTS if facts[field] is False]
    if triggers:
        route, rule = "human_review", "v1.1"
        evidence = list(triggers)
        explanation = "Human review required because " + " and ".join(triggers.values()) + "."
    elif missing or absent_docs:
        route = "request_information"
        rule = "v1.2" if absent_docs else "v1.missing"
        evidence = absent_docs + missing
        reasons = ["missing " + FIELDS[field] for field in absent_docs]
        reasons += ["missing or unreadable " + FIELDS[field] for field in missing]
        explanation = "Request information: " + ", ".join(reasons) + "."
    else:
        route, rule = "routine_processing", "v1.3"
        evidence = list(facts)
        explanation = (f"The €{quote} own-damage claim has active cover, both required "
                       "documents and no review trigger, so it can enter routine processing.")

    return Decision(case_id=case_id, case_status=status, policy_version=policy_version,
                    recommendation=route, matched_rule=rule,
                    supporting_facts={key: _evidence_value(facts[key]) for key in evidence},
                    explanation=explanation)
