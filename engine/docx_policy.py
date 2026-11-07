"""Read a policy written as a Word (.docx) document into the engine's policy configuration.

The converter is deliberately strict. It understands the decision-order wording used by the
supplied policy ("Send to <route> if <conditions>." / "Otherwise, send to <route>.") and rejects
any rule sentence it cannot interpret completely, instead of guessing. Standard-library only.
"""
from __future__ import annotations

import io
import re
import zipfile
from decimal import Decimal, InvalidOperation
import xml.etree.ElementTree as ET

from .policy import FIELDS, ROUTES

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
MAX_XML_BYTES = 5 * 1024 * 1024
BOOLEAN_FIELDS = set(FIELDS) - {"claim_type", "repair_type", "quote_eur"}
ROUTE_PREFIX = {"human_review": "HR", "request_information": "INFO"}

# Recognised rules keep the identifiers, priorities and wording of the bundled v1 policy so the
# same rule has the same identity across versions (this is what makes "changed rule" comparison
# meaningful). Keyed by (route, field, operator, value); amounts match any value.
_ANY = object()
KNOWN_RULES = {
    ("human_review", "policy_active_on_incident", "eq", False): ("HR_POLICY_INACTIVE", 10, "The policy was inactive on the incident date"),
    ("human_review", "claim_type", "ne", "motor_own_damage"): ("HR_CLAIM_TYPE", 20, "The claim falls outside motor own-damage cover"),
    ("human_review", "injury_reported", "eq", True): ("HR_INJURY", 30, "An injury was reported"),
    ("human_review", "liability_disputed", "eq", True): ("HR_LIABILITY", 40, "Liability is disputed"),
    ("human_review", "duplicate_flag", "eq", True): ("HR_DUPLICATE", 50, "The claim is flagged as a duplicate"),
    ("human_review", "evidence_conflict", "eq", True): ("HR_EVIDENCE_CONFLICT", 60, "The evidence conflicts"),
    ("human_review", "quote_eur", "gt", _ANY): ("HR_QUOTE_LIMIT", 70, "The repair quote exceeds EUR {value}"),
    ("request_information", "incident_report_present", "eq", False): ("INFO_INCIDENT_REPORT_MISSING", 80, "The incident report is absent"),
    ("request_information", "itemized_quote_present", "eq", False): ("INFO_ITEMIZED_QUOTE_MISSING", 90, "The itemized quote is absent"),
}

ORDERING = {
    "greater than": "gt", "more than": "gt", "above": "gt", "over": "gt", "exceeds": "gt", "exceed": "gt",
    "at least": "ge", "no less than": "ge", "not less than": "ge",
    "less than": "lt", "below": "lt", "under": "lt",
    "at most": "le", "no more than": "le", "not more than": "le",
}
ORDER_WORDS = "|".join(sorted(map(re.escape, ORDERING), key=len, reverse=True))
RULE_LINE = re.compile(r"^(?:\d+\s*[.)]\s*)?(?:otherwise,?\s*)?send\s+to\s+([a-z_]+)\b(.*)$", re.I)
SUBJECT = re.compile(r"^(?P<fields>[a-z_]+(?:\s*(?:,|\bor\b)\s*[a-z_]+)*)\s+(?P<rest>.+)$", re.I)
POLICY_ACTIVE = re.compile(r"^(?:the\s+)?policy\s+(?:was|is)\s+(not\s+)?active(?:\s+on\s+the\s+incident(?:\s+date)?)?$", re.I)
VERSION = re.compile(r"\bv\d+(?:\.\d+)*\b", re.I)


class PolicyDocumentError(ValueError):
    pass


def _paragraphs(data: bytes) -> list[str]:
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
        info = archive.getinfo("word/document.xml")
    except (zipfile.BadZipFile, KeyError):
        raise PolicyDocumentError("This is not a Word (.docx) document.")
    if info.file_size > MAX_XML_BYTES:
        raise PolicyDocumentError("The Word document is too large.")
    xml = archive.read(info)
    if b"<!DOCTYPE" in xml or b"<!ENTITY" in xml:
        raise PolicyDocumentError("The Word document contains unsupported XML declarations.")
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        raise PolicyDocumentError("The Word document could not be read.")
    result = []
    for paragraph in root.iter(W + "p"):
        parts = []
        for node in paragraph.iter():
            if node.tag == W + "t":
                parts.append(node.text or "")
            elif node.tag in (W + "tab", W + "br"):
                parts.append(" ")
        text = " ".join("".join(parts).split())
        if text:
            result.append(text)
    return result


def _amount(text: str) -> str:
    cleaned = re.sub(r"(?i)\b(?:eur|euros?)\b|€", "", text).replace(",", "").strip().rstrip(".").strip()
    if not re.fullmatch(r"\d+(?:\.\d+)?", cleaned):
        raise PolicyDocumentError(f"Could not read the amount {text.strip()!r}.")
    try:
        return format(Decimal(cleaned).normalize(), "f")
    except InvalidOperation:
        raise PolicyDocumentError(f"Could not read the amount {text.strip()!r}.")


def _conditions(clause: str):
    """Return [(field, op, value)] for one clause; several fields in a clause mean 'any of'."""
    text = clause.strip().rstrip(".").strip()
    active = POLICY_ACTIVE.match(text)
    if active:
        return [("policy_active_on_incident", "eq", active.group(1) is None)]
    match = SUBJECT.match(text)
    if not match:
        raise PolicyDocumentError(f"Could not understand the condition {clause.strip()!r}.")
    fields = [f.lower() for f in re.split(r"\s*(?:,|\bor\b)\s*", match["fields"], flags=re.I) if f]
    unknown = [f for f in fields if f not in FIELDS]
    if unknown:
        raise PolicyDocumentError(f"Unknown field {unknown[0]!r} in {clause.strip()!r}. Use the field names from the claims CSV.")
    rest = match["rest"].strip()

    ordering = re.fullmatch(rf"(?:(?:is|are)\s+)?({ORDER_WORDS})\s+(.+)", rest, re.I)
    if ordering:
        if fields != ["quote_eur"]:
            raise PolicyDocumentError(f"Amount comparisons are only supported for quote_eur: {clause.strip()!r}.")
        return [("quote_eur", ORDERING[ordering.group(1).lower()], _amount(ordering.group(2)))]

    value = re.fullmatch(r"(?:is|are)\s+(not\s+)?([a-z0-9_]+)", rest, re.I)
    if not value:
        raise PolicyDocumentError(f"Could not understand the condition {clause.strip()!r}.")
    negated, token = value.group(1) is not None, value.group(2).lower()
    result = []
    for field in fields:
        if field in BOOLEAN_FIELDS:
            if token not in ("true", "false"):
                raise PolicyDocumentError(f"{field} must be compared with true or false: {clause.strip()!r}.")
            result.append((field, "eq", (token == "true") != negated))
        elif field == "quote_eur":
            raise PolicyDocumentError(f"quote_eur needs an amount comparison such as 'greater than €1,500': {clause.strip()!r}.")
        else:
            result.append((field, "ne" if negated else "eq", token))
    return result


def _describe(field, op, value) -> str:
    words = {"eq": "is", "ne": "is not", "gt": "is greater than", "ge": "is at least", "lt": "is less than", "le": "is at most"}
    shown = (str(value).lower() if isinstance(value, bool) else f"EUR {value}" if field == "quote_eur" else value)
    return f"{field} {words[op]} {shown}"


def policy_from_docx(data: bytes, *, policy_id: str | None = None, filename: str | None = None):
    """Return (config, rule_summary, notes). Raises PolicyDocumentError when anything is unclear."""
    paragraphs = _paragraphs(data)
    if not paragraphs:
        raise PolicyDocumentError("The Word document is empty.")
    title = paragraphs[0]
    found = VERSION.search(title) or next((m for m in map(VERSION.search, paragraphs) if m), None)
    if not found:
        raise PolicyDocumentError("No policy version (for example 'v1') found in the document title.")
    version = found.group(0).lower()
    if policy_id is None:
        words = re.sub(r"(?i)\bpolic(?:y|ies)\b", " ", VERSION.sub(" ", title))
        policy_id = "_".join(re.findall(r"[a-z0-9]+", words.lower()))
        if not policy_id:
            raise PolicyDocumentError("Could not derive a policy name from the document title.")

    rules, summary, fallback_seen = [], [], False
    used_ids, used_priorities, last_priority = set(), set(), 0
    reserved = {priority for _, priority, _ in KNOWN_RULES.values()}
    order = []
    for paragraph in paragraphs:
        line = RULE_LINE.match(paragraph)
        if not line or line.group(1).lower() not in ROUTES:
            continue
        route, tail = line.group(1).lower(), line.group(2).strip()
        condition = re.fullmatch(r"if\s+(.+?)\.?", tail, re.I | re.S)
        if route == "routine_processing":
            if condition:
                raise PolicyDocumentError("routine_processing can only be the final 'Otherwise' step, not a conditional rule.")
            if tail and not tail.startswith("."):  # explanatory sentences may follow the first full stop
                raise PolicyDocumentError(f"Could not understand: {paragraph!r}.")
            fallback_seen = True
            continue
        if not condition:
            raise PolicyDocumentError(f"Rule for {route} needs an 'if ...' condition: {paragraph!r}.")
        for clause in re.split(r";", condition.group(1)):
            clause = re.sub(r"^\s*(?:or|and)\s+", "", clause.strip(), flags=re.I)
            if re.match(r"(?i)and\b", clause) or re.search(r"(?i)\band\b", clause):
                raise PolicyDocumentError(f"'and' conditions are not supported; list alternatives with 'or': {clause!r}.")
            if clause:
                for field, op, value in _conditions(clause):
                    order.append((route, field, op, value, clause))
    if not order:
        raise PolicyDocumentError("No decision rules ('Send to human_review if ...') were found in the document.")

    for route, field, op, value, clause in order:
        known = KNOWN_RULES.get((route, field, op, value)) or KNOWN_RULES.get((route, field, op, _ANY))
        if known:
            rule_id, priority, reason = known[0], known[1], known[2].format(value=value)
        else:
            suffix = f"_{value}" if field in ("claim_type", "repair_type") else ""
            rule_id = f"{ROUTE_PREFIX[route]}_{field}_{op}{suffix}".upper()
            priority = last_priority + 5
            while priority in used_priorities or priority in reserved:
                priority += 1
            reason = f"Rule from document: {clause.strip().rstrip('.')}"
        base, counter = rule_id, 2
        while rule_id in used_ids:
            rule_id, counter = f"{base}_{counter}", counter + 1
        if priority in used_priorities:
            raise PolicyDocumentError(f"The same condition appears twice: {clause!r}.")
        used_ids.add(rule_id)
        used_priorities.add(priority)
        last_priority = priority
        rules.append({"id": rule_id, "priority": priority, "then": route, "reason": reason,
                      "if": {"field": field, "op": op, "value": value}})
        summary.append({"id": rule_id, "route": route, "priority": priority, "condition": _describe(field, op, value)})

    notes = []
    if not fallback_seen:
        notes.append("The document has no final 'Otherwise, send to routine_processing' step; the engine default (routine_processing) is used.")
    body = " ".join(paragraphs).lower()
    if not re.search(r"(absent|blank|unreadable|missing).{0,150}request information", body):
        notes.append("The document does not say how missing fields are handled; the engine default (request information) is used.")

    config = {
        "policy_id": policy_id,
        "version": version,
        "precedence": list(ROUTES[::-1]),
        "fallback": "routine_processing",
        "unknown_handling": {"required_fields": list(FIELDS), "outcome": "request_information"},
        "rules": sorted(rules, key=lambda r: r["priority"]),
    }
    if version != "v1":
        label = re.sub(r"[^\w .()-]", "", (filename or "").replace("\\", "/").rsplit("/", 1)[-1])[:120]
        config["source"] = f"Converted from uploaded Word document {label}".strip()
    return config, summary, notes
