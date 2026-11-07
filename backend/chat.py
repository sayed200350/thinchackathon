"""Reviewer conversation grounded in immutable decisions and the real v1 engine."""

import re
from decimal import Decimal

from engine import decide
from engine.policy import FIELDS
from . import chat_providers
from .store import RequestError, case_detail, claim_list, preview
from .supabase_seed import CLAUSES


INTENTS = {
    "decision": "Explain the selected claim's recommendation and its reason.",
    "evidence": "Inspect supporting facts, missing documents, or the applicable written clause.",
    "what_if": "Simulate one hypothetical change to the claim: a repair quote amount or receiving a missing document.",
    "history": "Read recorded reviewer corrections and the current effective recommendation.",
    "correct": "Open the human review form to record a correction.",
    "replay": "Ask about the official policy change, v2, or cases needing a recheck.",
    "queue": "Count or list the claims in the review queue.",
    "help": "Greetings, unsupported questions, or help with the chat.",
}
ROUTE_LABEL = {"human_review": "human review", "request_information": "request more information",
               "routine_processing": "routine processing"}
CASE = re.compile(r"\b(DEV|PRA)[-\s]?(\d+)\b", re.I)
NUMBER = re.compile(r"[-+]?\d+(?:[,.]\d+)*")
STARTERS = ["Why does DEV-002 need more information?", "Explain DEV-001", "What changed in v2?"]


def validate_request(body):
    if not isinstance(body, dict):
        raise RequestError(400, "Send a JSON object with a message.")
    message = body.get("message")
    if not isinstance(message, str) or not 1 <= len(message.strip()) <= 2000:
        raise RequestError(400, "Use a message between 1 and 2,000 characters.")
    active = body.get("case_id")
    if active is not None and (not isinstance(active, str) or not 1 <= len(active.strip()) <= 128):
        raise RequestError(400, "case_id must be a nonempty case ID or null.")
    history = body.get("history", [])
    if not isinstance(history, list) or len(history) > 16:
        raise RequestError(400, "Send at most 16 previous chat turns.")
    cleaned = []
    for turn in history:
        if (not isinstance(turn, dict) or turn.get("role") not in ("user", "assistant")
                or not isinstance(turn.get("content"), str) or len(turn["content"]) > 4000):
            raise RequestError(400, "Each turn needs a role and message text.")
        cleaned.append({"role": turn["role"], "content": turn["content"]})
    return message.strip(), active.strip() if active else None, cleaned[-8:]


def local_intent(message, history):
    text = message.casefold()
    if re.search(r"\b(v2|replay|policy change|second look|recheck)\b", text):
        return "replay"
    if re.search(r"\b(what if|hypothetical|simulate|instead|were the quote)\b", text) or (
            NUMBER.search(CASE.sub("", text)) and re.search(r"\b(what about|quote|estimate|amount|eur|euros?)\b|€", text)
            and not re.search(r"^\s*(why|how many|explain)\b", text)):
        return "what_if"
    if re.search(r"\b(history|audit|overrides|corrections|who changed|last correction|saved reason)\b", text):
        return "history"
    if re.search(r"\b(override|correct|save a correction|change (?:the |this )?(?:decision|route|recommendation)|send (?:it|this) to|escalate (?:it|this))\b", text):
        return "correct"
    if re.search(r"\b(how many|queue|(?:list|which|show) (?:all |the )?(?:open |closed )?claims)\b", text):
        return "queue"
    if re.search(r"\b(evidence|clause|rules?|proof|missing|documents?|facts?|paperwork)\b", text):
        return "evidence"
    if CASE.search(message) or re.search(r"\b(why|reason|explain|route|decision|recommendation|case|claim|next step)\b", text):
        return "decision"
    if history and text in ("tell me more", "more detail", "show me more", "go on"):
        return "evidence"
    return "help"


def quoted_amount(message):
    # Accept an unambiguous euro amount; exclude claim IDs and never interpret another currency as EUR.
    cleaned = CASE.sub("", message)
    if not re.search(r"€|\b(eur|euros?|quote|estimate|amount)\b", cleaned, re.I):
        return None
    if re.search(r"[$£¥₹]|\b(usd|gbp|chf|aud|cad|dollars?|pounds?|francs?|threshold|limit|increase by|decrease by|higher|lower|more than|less than|extra)\b|%", cleaned, re.I):
        return None
    numbers = list(NUMBER.finditer(cleaned))
    if len(numbers) != 1:
        return None
    token, = numbers
    before = cleaned[:token.start()].rstrip()
    after = cleaned[token.end():].strip()
    if before.endswith((".", ",")) or re.search(r"\bby\s*(?:€|eur)?$", before, re.I):
        return None
    if not re.fullmatch(r"(?:€|eur|euros?)?(?:\s+(?:instead|for this (?:case|claim)))?[?!.\s]*", after, re.I):
        return None
    last_word = re.search(r"([A-Za-z]+)\s*$", before)
    if last_word and last_word[1].casefold() not in {
        "eur", "euros", "quote", "estimate", "amount", "be", "is", "was", "were", "at", "of", "to",
        "cost", "costs", "total", "totals", "about", "for", "exactly",
    }:
        return None
    raw = token.group()
    if re.fullmatch(r"\+?\d{1,3}(,\d{3})+(\.\d{1,2})?", raw):
        raw = raw.replace(",", "")
    elif re.fullmatch(r"\+?\d{1,3}(\.\d{3})+(,\d{1,2})?", raw):
        raw = raw.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\+?\d+(?:[.,]\d{1,2})?", raw):
        raw = raw.replace(",", ".")
    else:
        return None
    if len(raw) > 15:
        return None
    return format(Decimal(raw), "f")


def scenario_change(message):
    text = CASE.sub("", message.casefold())
    # Compound assumptions must never be silently reduced to one edit.
    if re.search(r"\b(and|plus|without|unless|except|injur\w*|liabilit\w*|duplicate|coverage|inactive|conflict\w*)\b", text):
        return None
    documents = [field for name, field in (
        (r"\bincident report\b", "incident_report_present"),
        (r"\bitemi[sz]ed (?:quote|estimate)\b", "itemized_quote_present"),
    ) if re.search(name, text)]
    if len(documents) == 1 and not NUMBER.search(text) and re.search(
        r"\b(receive[ds]?|submit(?:s|ted)?|upload(?:s|ed)?|arrive[ds]?|provide[ds]?|had|now available)\b", text
    ) and not re.search(r"\b(no|never|absent|still|not)\b|n['’]t", text):
        field, = documents
        return field, "True", FIELDS[field].capitalize() + " received"
    amount = quoted_amount(text)
    if amount is not None and not any(word in text for word in ("report", "document", "paperwork")):
        return "quote_eur", amount, "Repair quote €" + amount
    return None


def fact_value(value):
    if value is None:
        return "Unknown"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    return str(value)


def answer(db, body):
    message, active, history = validate_request(body)
    ids = list(dict.fromkeys(f"{p.upper()}-{n.zfill(3)}" for p, n in CASE.findall(message)))
    response = {"case_id": active, "answer": "", "evidence": [], "suggestions": STARTERS.copy(),
                "model_usage": {"intent": "local", "answer": "policy engine"}}
    if len(ids) > 1:
        response.update(answer="Which claim should we look at first?", suggestions=[f"Explain {k}" for k in ids[:4]])
        return response
    selected = ids[0] if ids else active
    detail = None
    if selected:
        try:
            detail = case_detail(db, selected)
        except RequestError as error:
            if error.status != 404:
                raise
            response.update(case_id=None, answer=f"I couldn’t find {selected} in this queue. Which claim should I open?")
            return response
    response["case_id"] = selected
    intent = chat_providers.classify_intent(message, history, INTENTS)
    if intent in INTENTS:
        response["model_usage"]["intent"] = "Jev"
    else:
        intent = local_intent(message, history)
    scenario_message = message
    # Recompute the preceding hypothetical for a short "why?" follow-up. Accept
    # only the previous user question as input and re-read every fact from the store.
    if detail and not ids and re.fullmatch(
        r"(?:why(?: is that)?|how come|which (?:rule|clause)(?: applies)?|show (?:me )?the (?:applicable )?clause)[?!. ]*",
        message, re.I
    ):
        previous = next((turn["content"] for turn in reversed(history) if turn["role"] == "user"), "")
        previous_ids = {f"{p.upper()}-{n.zfill(3)}" for p, n in CASE.findall(previous)}
        if previous_ids.issubset({selected}) and local_intent(previous, []) == "what_if" and scenario_change(previous):
            intent, scenario_message = "what_if", previous
            response["model_usage"]["intent"] = "local"
    if intent in ("help", "queue", "replay"):
        if intent == "queue":
            rows = claim_list(db)["claims"]
            text = message.casefold()
            status = next((s for s in ("open", "closed") if re.search(r"\b" + s + r"\b", text)), None)
            route = next((key for key, expression in (
                ("human_review", r"human review|escalat"), ("routine_processing", r"routine"),
                ("request_information", r"information|missing doc")
            ) if re.search(expression, text)), None)
            matching = [r["case_id"] for r in rows if (not status or r["case_status"] == status)
                        and (not route or r["effective_recommendation"] == route)]
            scope = " ".join(filter(None, (status, "claims", "routed to " + ROUTE_LABEL[route] if route else "")))
            response["answer"] = f"{len(matching)} {scope} in the queue."
            if matching and (status or route or re.search(r"which|list", text)):
                response["answer"] += " " + ", ".join(matching) + "."
                response["suggestions"] = [f"Explain {k}" for k in matching[:3]]
            elif not status and not route:
                counts = preview(db)
                response["answer"] += f' {counts["open_claims"]} open and {counts["closed_claims"]} closed.'
            response["evidence"] = [{"label": "Source", "value": "Current claims queue"}]
        elif intent == "replay":
            counts = preview(db)
            response["answer"] = (f'The official {counts["to_version"]} policy change is pending. '
                                  'There is no measured before-and-after result yet. '
                                  'I can run a hypothetical repair quote using v1.')
            response["evidence"] = [{"label": "Policy preview", "value": counts["status"]}]
        else:
            response["answer"] = "I can explain a claim, show its evidence, test a repair quote or newly received document, or open a reviewer correction."
        return response
    if detail is None:
        response["answer"] = "Which claim should I use? Enter a case ID such as DEV-001 or PRA-005."
        return response

    decision = detail["decision"]
    rule = decision["matched_rule"]
    route = ROUTE_LABEL[decision["recommendation"]]
    effective = ROUTE_LABEL[detail["effective_recommendation"]]
    base_evidence = [{"label": "Decision", "value": f"{selected} · {decision['policy_version']} · {rule}"}]
    for key, value in decision["supporting_facts"].items():
        base_evidence.append({"label": FIELDS.get(key, key).capitalize(), "value": fact_value(value)})
    response["evidence"] = base_evidence
    response["suggestions"] = ["Show the applicable clause", "What if the quote were €1,501?", "Show review history"]
    if rule == "v1.2":
        missing_doc = next((key for key in ("incident_report_present", "itemized_quote_present")
                            if decision["supporting_facts"].get(key) is False), None)
        if missing_doc:
            response["suggestions"][1] = f"What if we received the {FIELDS[missing_doc]}?"
    if decision["case_status"] == "open":
        response["suggestions"].append("Correct this decision")

    if intent == "correct":
        if decision["case_status"] == "closed":
            response["answer"] = f"{selected} is closed. Its recorded decision is retained."
        else:
            response["answer"] = f"The current route for {selected} is {effective}. Choose the corrected route and record your reason below."
            response["action"] = {"type": "review_correction", "case_id": selected,
                                  "policy_version": decision["policy_version"], "revision": detail["revision"],
                                  "current_recommendation": detail["effective_recommendation"]}
        return response
    if intent == "history":
        audit = detail["history"]
        if not audit:
            response["answer"] = f"{selected} has no saved reviewer corrections. The original recommendation is {route}."
        else:
            entry = audit[-1]
            response["answer"] = (f"{selected} originally went to {route}. Its current route is {effective}. "
                                  f"The latest of {len(audit)} saved corrections was recorded by {entry['reviewer']}: {entry['reason']}")
            response["evidence"] += [{"label": "Audit revision", "value": str(entry["revision"])},
                                     {"label": "Recorded", "value": entry["created_at"]}]
        return response
    if intent == "what_if":
        change = scenario_change(scenario_message)
        if change is None:
            response["answer"] = (f"Which single change should I test for {selected}? Give me a replacement repair quote "
                                  "in euros, or name a document that arrived, such as the incident report.")
            return response
        field, value, description = change
        trial = decide(dict(detail["claim"], **{field: value}), decision["policy_version"])
        hypothetical = ROUTE_LABEL[trial["recommendation"]]
        response["answer"] = (f"Hypothetical for {selected} ({description}). {trial['explanation']} "
                              f"The recorded engine recommendation is {route}.")
        response["evidence"] = [
            {"label": "Scenario only", "value": "No saved decision was changed"},
            {"label": "Changed fact", "value": description},
            {"label": "Scenario route", "value": hypothetical},
            {"label": "Scenario rule", "value": trial["matched_rule"]},
            {"label": "Clause", "value": CLAUSES[trial["matched_rule"]]},
        ]
        response["suggestions"] = ["Show the recorded decision", "What if the quote were €1,501?", "Show review history"]
        return response

    # The model can select from statements already grounded in this claim. The route, rule,
    # missing facts and any human correction are always supplied by the application.
    mandatory = [decision["explanation"]]
    if detail["revision"]:
        mandatory.append(f"The reviewer's current route is {effective}.")
    clause = CLAUSES.get(rule)
    if intent == "evidence" and clause:
        mandatory.append(clause)
    options = {"summary": f"Claim summary: {detail['claim']['claim_summary']}",
               "status": f"The case is {decision['case_status']}.",
               "rule": f"The engine matched rule {rule}."}
    if clause and intent != "evidence":
        options["clause"] = clause
    picked = chat_providers.compose_answer(message, history, options)
    if picked and all(key in options for key in picked):
        optional = [options[key] for key in picked]
        response["model_usage"]["answer"] = "GPT"
    else:
        optional = [options["rule"]]
    response["answer"] = f"{selected} — " + " ".join(mandatory + optional)
    return response
