"""Append-only claim revisions. All routing remains in engine.runtime."""
import json
from uuid import uuid4

from engine.policy import FIELDS
from engine.runtime import evaluate, parse_claim, load_policy, policy_from_json, fingerprint
from engine.conformance import leaves
from .store import RequestError

CLAIM_KEYS = {"case_id", "case_status", "claim_summary", *FIELDS}


def initialize(db):
    db.executescript("""
        CREATE TABLE IF NOT EXISTS change_events (
            sequence INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT UNIQUE NOT NULL,
            event_type TEXT NOT NULL, actor TEXT NOT NULL, case_id TEXT, policy_version TEXT,
            payload TEXT NOT NULL, occurred_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')));
        CREATE TABLE IF NOT EXISTS claim_evaluations (
            case_id TEXT NOT NULL REFERENCES claims(case_id), revision INTEGER NOT NULL,
            request_id TEXT NOT NULL, request_hash TEXT NOT NULL,
            claim_json TEXT NOT NULL, decision_json TEXT NOT NULL, change_json TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
            PRIMARY KEY(case_id, revision), UNIQUE(case_id, request_id));
        CREATE TABLE IF NOT EXISTS policy_activations (
            sequence INTEGER PRIMARY KEY AUTOINCREMENT, proposal_id TEXT UNIQUE NOT NULL,
            policy_document TEXT NOT NULL, document_text TEXT NOT NULL, actor TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')));
    """)
    for table in ("change_events", "claim_evaluations", "policy_activations"):
        for operation in ("UPDATE", "DELETE"):
            db.execute(f"CREATE TRIGGER IF NOT EXISTS {table}_no_{operation} BEFORE {operation} ON {table} "
                       "BEGIN SELECT RAISE(ABORT, 'History is append-only'); END")


def event(db, kind, actor, payload, case_id=None, version=None):
    db.execute("INSERT INTO change_events(event_id,event_type,actor,case_id,policy_version,payload) VALUES(?,?,?,?,?,?)",
               (str(uuid4()), kind, actor, case_id, version, json.dumps(payload, allow_nan=False)))


def active_policy(db):
    row = db.execute("SELECT policy_document FROM policy_activations ORDER BY sequence DESC LIMIT 1").fetchone()
    return policy_from_json(row[0]) if row else load_policy()


def current(db, case_id):
    original = db.execute("SELECT claim_json,decision_json FROM claims WHERE case_id=?", (case_id,)).fetchone()
    if original is None:
        raise RequestError(404, "Unknown case_id.")
    row = db.execute("SELECT * FROM claim_evaluations WHERE case_id=? ORDER BY revision DESC LIMIT 1", (case_id,)).fetchone()
    return dict(claim=json.loads(row["claim_json"] if row else original[0]),
                decision=json.loads(row["decision_json"] if row else original[1]), revision=row["revision"] if row else 0)


def history(db, case_id):
    result = current(db, case_id)
    original = db.execute("SELECT decision_json FROM claims WHERE case_id=?", (case_id,)).fetchone()
    result["original_decision"] = json.loads(original[0])
    result["history"] = [dict(revision=r["revision"], created_at=r["created_at"],
                             claim=json.loads(r["claim_json"]), decision=json.loads(r["decision_json"]),
                             change=json.loads(r["change_json"])) for r in db.execute(
        "SELECT * FROM claim_evaluations WHERE case_id=? ORDER BY revision", (case_id,))]
    return result


def validate_claim(raw):
    if not isinstance(raw, dict) or set(raw) - CLAIM_KEYS:
        raise ValueError("Only supported structured claim fields and claim_summary are accepted.")
    for value in raw.values():
        if value is not None and type(value) not in (str, int, float, bool):
            raise ValueError("Claim fields must be scalar values.")
        if isinstance(value, str) and len(value) > 4000:
            raise ValueError("Claim field exceeds 4000 characters.")
    json.dumps(raw, allow_nan=False)
    parsed = parse_claim(raw)
    if raw.get("case_id") != parsed.case_id or raw.get("case_status") != parsed.case_status:
        raise ValueError("Use a trimmed case_id and lowercase open/closed case_status.")
    return parsed


def compare(before, after, previous, policy):
    claim = validate_claim(after)
    if before and before["case_id"] != after["case_id"]:
        raise ValueError("Claim identity cannot change.")
    referenced = set(policy.config["unknown_handling"]["required_fields"])
    for rule in policy.config["rules"]:
        referenced.update(n["field"] for n in leaves(rule["if"]))
    changes = [dict(field=k, old=before.get(k), new=after.get(k), relevant=k in referenced or k == "case_status")
               for k in sorted(CLAIM_KEYS) if before and (type(before.get(k)) != type(after.get(k)) or before.get(k) != after.get(k))]
    decision = evaluate(claim, policy)
    if previous and previous.get("case_status") == "closed":
        decision = previous
    prior_rules = set(previous.get("reason_codes", [])) if previous else set()
    return dict(changes=changes, previous_recommendation=previous["recommendation"] if previous else None,
                recommendation=decision["recommendation"], decision=decision,
                newly_triggered_rules=[r for r in decision["reason_codes"] if r not in prior_rules],
                explanation=decision["concise_explanation"],
                what_changed="; ".join(f"{c['field']}: {c['old']} -> {c['new']}" for c in changes) or "No field changes.",
                needs_recheck=False if decision["case_status"] == "closed" else any(c["relevant"] for c in changes),
                validation={"valid_record": True, "unresolved_fields": decision["missing_or_invalid_fields"],
                            "warnings": decision["validation_warnings"]})


def preview(db, body):
    raw = body.get("claim")
    validate_claim(raw)
    saved = db.execute("SELECT 1 FROM claims WHERE case_id=?", (raw["case_id"],)).fetchone()
    prior = current(db, raw["case_id"]) if saved else None
    before = prior["claim"] if prior else body.get("before")
    policy = active_policy(db)
    previous = prior["decision"] if prior else evaluate(validate_claim(before), policy) if before else None
    result = compare(before, raw, previous, policy)
    result.update(revision=prior["revision"] if prior else -1, active_policy_hash=policy.fingerprint, preview=True)
    return result


def append_evaluation(db, case_id, revision, request_id, request_hash, raw, result, actor, reason):
    db.execute("INSERT INTO claim_evaluations(case_id,revision,request_id,request_hash,claim_json,decision_json,change_json) VALUES(?,?,?,?,?,?,?)",
               (case_id, revision, request_id, request_hash, json.dumps(raw), json.dumps(result["decision"]),
                json.dumps({**{k: v for k, v in result.items() if k != "decision"}, "reason": reason})))
    payload = {k: v for k, v in result.items() if k != "decision"}
    payload.update(revision=revision, reason=reason, triggered_rule_ids=result["decision"]["reason_codes"])
    if result["changes"]:
        event(db, "claim_modified", actor, payload, case_id, result["decision"]["policy_version"])
    event(db, "claim_reevaluated", actor, payload, case_id, result["decision"]["policy_version"])
    if result["previous_recommendation"] != result["recommendation"]:
        event(db, "recommendation_changed", actor, payload, case_id, result["decision"]["policy_version"])


def save(db, body):
    raw = body.get("claim")
    parsed = validate_claim(raw)
    for key in ("request_id", "actor", "reason", "expected_policy_hash"):
        if not isinstance(body.get(key), str) or not body[key].strip() or len(body[key]) > 2000:
            raise ValueError(f"{key} is required (at most 2000 characters).")
    expected = body.get("expected_revision")
    if type(expected) is not int or expected < -1:
        raise ValueError("expected_revision must be -1 for a new claim, otherwise the saved revision.")
    request_hash = fingerprint(body)
    with db:
        db.execute("BEGIN IMMEDIATE")
        duplicate = db.execute("SELECT request_hash FROM claim_evaluations WHERE case_id=? AND request_id=?", (parsed.case_id, body["request_id"])).fetchone()
        if duplicate:
            if duplicate[0] != request_hash:
                raise RequestError(409, "request_id was already used for a different change.")
            return history(db, parsed.case_id)
        policy = active_policy(db)
        if policy.fingerprint != body["expected_policy_hash"]:
            raise RequestError(409, "The active policy changed. Preview again before saving.")
        exists = db.execute("SELECT 1 FROM claims WHERE case_id=?", (parsed.case_id,)).fetchone()
        prior = current(db, parsed.case_id) if exists else None
        if expected != (prior["revision"] if prior else -1):
            raise RequestError(409, "A newer claim revision exists. Reload before saving.")
        if prior and prior["decision"]["case_status"] == "closed":
            raise RequestError(409, "Closed claims retain their historical evidence and decision.")
        result = compare(prior["claim"] if prior else None, raw, prior["decision"] if prior else None, policy)
        # Unknown scalar facts can be saved as unresolved; the engine cannot route them routinely.
        if not prior:
            db.execute("INSERT INTO claims VALUES(?,?,?,?,?)", (parsed.case_id, parsed.case_status, json.dumps(raw),
                       json.dumps(result["decision"]), result["recommendation"]))
            event(db, "claim_created", body["actor"], {"claim": raw, "recommendation": result["recommendation"]}, parsed.case_id, policy.version)
        append_evaluation(db, parsed.case_id, expected + 1, body["request_id"], request_hash, raw, result, body["actor"], body["reason"])
        return history(db, parsed.case_id)
