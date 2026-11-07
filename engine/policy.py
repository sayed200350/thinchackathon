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


def decision_summary(assessment: Mapping) -> Decision:
    """Render the stable v1 HTTP contract from an already evaluated decision."""
    if assessment["policy_version"] != "v1":
        raise ValueError("The original decision contract requires policy v1.")
    outcome = assessment["recommendation"]
    facts = assessment["normalized_facts"]
    quote = facts["quote_eur"]
    matched = [
        field for check in assessment["trace"]
        if check["result"] is True and check["outcome"] == outcome
        for field in check["observed"]
    ]
    if outcome == "human_review":
        clause = "v1.1"
        fields = matched
        reasons = {
            **REVIEW_FLAGS,
            "policy_active_on_incident": "the policy was inactive on the incident date",
            "claim_type": "the claim falls outside motor own-damage cover",
            "quote_eur": f"the €{quote} quote exceeds €1500",
        }
        explanation = "Human review required because " + " and ".join(reasons[key] for key in fields) + "."
    elif outcome == "request_information":
        missing = assessment["missing_or_invalid_fields"]
        clause = "v1.2" if matched else "v1.missing"
        fields = matched + missing
        reasons = ["missing " + FIELDS[field] for field in matched]
        reasons += ["missing or unreadable " + FIELDS[field] for field in missing]
        explanation = "Request information: " + ", ".join(reasons) + "."
    else:
        clause = "v1.3"
        fields = facts.keys()
        explanation = (f"The €{quote} own-damage claim has active cover, both required "
                       "documents and no review trigger, so it can enter routine processing.")

    support = {field: facts[field] for field in fields}
    if "quote_eur" in support and quote is not None:
        support["quote_eur"] = _evidence_value(Decimal(quote))
    return Decision(case_id=assessment["case_id"], case_status=assessment["case_status"],
                    policy_version="v1", recommendation=outcome, matched_rule=clause,
                    supporting_facts=support, explanation=explanation)


def _assess(claim: Mapping, policy_version: str, *, detail: bool) -> dict:
    from .runtime import evaluate, load_policy, parse_claim

    if policy_version != "v1":
        raise ValueError(f"Unsupported policy version: {policy_version}. Available: v1.")
    return evaluate(parse_claim(claim), load_policy(), _detail=detail)


def assess_v1(claim: Mapping, policy_version: str = "v1") -> dict:
    """Assess v1 with its full private audit, source references and counterfactuals."""
    assessment = _assess(claim, policy_version, detail=True)
    summary = decision_summary(assessment)
    return dict(assessment, matched_rule=summary["matched_rule"], supporting_facts=summary["supporting_facts"])


def decide(claim: Mapping, policy_version: str = "v1") -> Decision:
    """Return the original seven-key decision without exposing the private audit."""
    return decision_summary(_assess(claim, policy_version, detail=False))
