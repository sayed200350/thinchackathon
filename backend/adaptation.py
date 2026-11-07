"""Untrusted policy extraction -> validated preview -> authenticated, atomic activation."""
import base64
import hmac
import json
import os
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from engine.runtime import evaluate, parse_claim, policy_from_dict, load_policy, fingerprint
from engine.impact import policy_diff
from engine.conformance import run_checks, leaves, BASE
from engine.metrics import measure
from engine.batch import read_claims, OUTPUT_COLUMNS
from engine.docx_policy import _paragraphs
from . import changes
from .ai_service import configured_interpreter, validate_output, strict_json, AIUnavailable
from .store import RequestError

ROOT = Path(__file__).resolve().parents[1]


def initialize(db):
    db.executescript("""
        CREATE TABLE IF NOT EXISTS policy_proposals (
            proposal_id TEXT PRIMARY KEY, request_id TEXT UNIQUE NOT NULL, request_hash TEXT NOT NULL,
            baseline_hash TEXT NOT NULL, version TEXT NOT NULL, old_text TEXT NOT NULL, new_text TEXT NOT NULL,
            interpretation_json TEXT NOT NULL, validation_json TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')));
        CREATE TABLE IF NOT EXISTS proposal_reviews (
            proposal_id TEXT PRIMARY KEY REFERENCES policy_proposals(proposal_id),
            action TEXT NOT NULL, actor TEXT NOT NULL, reason TEXT NOT NULL, checks_json TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')));
    """)
    for table in ("policy_proposals", "proposal_reviews"):
        for operation in ("UPDATE", "DELETE"):
            db.execute(f"CREATE TRIGGER IF NOT EXISTS {table}_no_{operation} BEFORE {operation} ON {table} "
                       "BEGIN SELECT RAISE(ABORT, 'Policy proposals and reviews are immutable'); END")


def owner(token):
    expected = os.environ.get("POLICY_TWIN_OWNER_TOKEN", "")
    if not expected or not isinstance(token, str) or not hmac.compare_digest(expected, token):
        raise RequestError(403, "This action requires the configured policy-owner credential.")
    return os.environ.get("POLICY_TWIN_OWNER_NAME", "Policy owner") or "Policy owner"


def nonempty(body, key, maximum=2000):
    value = body.get(key)
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f"{key} must contain 1 to {maximum} characters.")
    return value.strip()


def active_document(db):
    row = db.execute("SELECT document_text FROM policy_activations ORDER BY sequence DESC LIMIT 1").fetchone()
    return row[0] if row else "\n".join(_paragraphs((ROOT / "data/taktile/policy_v1.docx").read_bytes()))


def targets(diff):
    return {r["id"] for key in ("added_rules", "removed_rules", "changed_rules") for r in diff[key]} | {
        "setting:" + name for name in diff["settings"] if name != "source"}


def validate_interpretation(value, baseline, version, old_text, new_text):
    errors = []
    validate_output(value)
    candidate, diff = None, None
    if value["ambiguities"]:
        errors.append("Unresolved ambiguities require a revised proposal and human review.")
    if not value["config_json"]:
        errors.append("No reliable configuration was extracted.")
    else:
        try:
            candidate = policy_from_dict(strict_json(value["config_json"]))
            if candidate.version != version or version == baseline.version or version == "v1":
                raise ValueError("A distinct requested candidate version is required; v1 is immutable.")
            if candidate.config["policy_id"] != baseline.config["policy_id"]:
                raise ValueError("Policy family cannot change.")
            diff = policy_diff(baseline, candidate)
            required = targets(diff)
            citations = {c["target"]: c for c in value["citations"]}
            if len(citations) != len(value["citations"]) or set(citations) != required:
                errors.append("Every changed rule/setting requires exactly one supporting citation.")
            old_rules = {r["id"] for r in baseline.config["rules"]}
            for target, citation in citations.items():
                if not citation["new_quote"].strip() or citation["new_quote"] not in new_text:
                    errors.append(f"{target}: supporting new text was not found verbatim.")
                if (target in old_rules or target.startswith("setting:")) and not citation["old_quote"].strip():
                    errors.append(f"{target}: supporting old text is required.")
                if citation["old_quote"] and citation["old_quote"] not in old_text:
                    errors.append(f"{target}: supporting old text was not found verbatim.")
            predicates = {}
            for rule in candidate.config["rules"]:
                key = fingerprint(rule["if"])
                if key in predicates:
                    errors.append("Duplicate/conflicting predicates: " + predicates[key] + " and " + rule["id"])
                predicates[key] = rule["id"]
            if not required:
                errors.append("No supported rule or setting changes were identified.")
        except (ValueError, TypeError, RecursionError):
            # Never relay model-controlled configuration strings in validation exceptions.
            errors.append("Candidate failed the engine's strict configuration validation (version, types, fields or operators).")
            candidate = None
    return dict(valid=not errors, errors=errors, policy_diff=diff,
                limitation="Verbatim citations establish provenance, not semantic correctness. Owner review and independent expectations are required."), candidate


def proposal(db, identifier):
    row = db.execute("SELECT * FROM policy_proposals WHERE proposal_id=?", (identifier,)).fetchone()
    if not row:
        raise RequestError(404, "Unknown policy proposal.")
    return dict(row)


def propose(db, body, token, interpreter=None):
    actor = owner(token)
    version = nonempty(body, "version", 100)
    request_id = nonempty(body, "request_id", 100)
    if "document_docx" in body:
        try:
            text = "\n".join(_paragraphs(base64.b64decode(body["document_docx"], validate=True)))
        except (ValueError, TypeError):
            raise ValueError("Invalid Word policy upload.") from None
    else:
        text = nonempty(body, "document_text", 50000)
    if len(text) > 50000:
        raise ValueError("Policy text exceeds 50,000 characters.")
    baseline = changes.active_policy(db)
    if body.get("expected_policy_hash") != baseline.fingerprint:
        raise RequestError(409, "Active policy changed. Reload before proposing.")
    request_hash = fingerprint(dict(version=version, text=text, baseline=baseline.fingerprint))
    prior = db.execute("SELECT proposal_id,request_hash FROM policy_proposals WHERE request_id=?", (request_id,)).fetchone()
    if prior:
        if prior["request_hash"] != request_hash:
            raise RequestError(409, "request_id already belongs to another policy document.")
        return describe(db, prior["proposal_id"])
    old_text = active_document(db)
    with db:
        changes.event(db, "policy_document_uploaded", actor, {"document_hash": fingerprint(text), "requested_version": version}, version=baseline.version)
    try:
        value = validate_output((interpreter or configured_interpreter()).interpret(old_text, text, baseline.config, version))
        validation, candidate = validate_interpretation(value, baseline, version, old_text, text)
    except AIUnavailable:
        with db:
            changes.event(db, "ai_interpretation_failed", "ai_service", {"reason": "Provider unavailable or invalid structured output"}, version=version)
        raise
    except ValueError:
        with db:
            changes.event(db, "ai_interpretation_failed", "ai_service", {"reason": "Invalid structured output"}, version=version)
        raise AIUnavailable("Policy interpretation unavailable or invalid. Deterministic claims evaluation remains available.") from None
    identifier = str(uuid4())
    with db:
        db.execute("BEGIN IMMEDIATE")
        if changes.active_policy(db).fingerprint != baseline.fingerprint:
            raise RequestError(409, "Active policy changed during interpretation. Propose again against the current version.")
        prior = db.execute("SELECT proposal_id,request_hash FROM policy_proposals WHERE request_id=?", (request_id,)).fetchone()
        if prior:
            if prior["request_hash"] != request_hash:
                raise RequestError(409, "request_id conflict.")
            return describe(db, prior["proposal_id"])
        db.execute("INSERT INTO policy_proposals VALUES(?,?,?,?,?,?,?,?,?,strftime('%Y-%m-%dT%H:%M:%fZ','now'))",
                   (identifier, request_id, request_hash, baseline.fingerprint, version, old_text, text,
                    json.dumps(value), json.dumps(validation)))
        # Explicit columns avoid ambiguity if the schema grows.
        changes.event(db, "ai_interpretation_generated", "ai_service", {"proposal_id": identifier, "interpretation": value}, version=version)
        changes.event(db, "policy_change_proposed", actor, {"proposal_id": identifier, "baseline_hash": baseline.fingerprint}, version=version)
        changes.event(db, "policy_configuration_validated", "validator", validation, version=version)
    return describe(db, identifier)


def snapshots(db):
    return [changes.current(db, row[0]) for row in db.execute("SELECT case_id FROM claims ORDER BY case_id")]


def impact(db, candidate):
    current_policy = changes.active_policy(db)
    diff = policy_diff(current_policy, candidate)
    changed = targets(diff)
    rows = []
    for snapshot in snapshots(db):
        raw, before = snapshot["claim"], snapshot["decision"]
        closed = before["case_status"] == "closed"
        after = before if closed else evaluate(parse_claim(raw), candidate)
        old_trace = {r["rule_id"]: r["result"] for r in before["trace"]}
        new_trace = {r["rule_id"]: r["result"] for r in after["trace"]}
        relevant = [k for k in changed if k.startswith("setting:") or old_trace.get(k) is True or new_trace.get(k) is True or old_trace.get(k) != new_trace.get(k)]
        route_changed = before["recommendation"] != after["recommendation"]
        recheck = not closed and (bool(relevant) or route_changed or before["primary_rule_id"] != after["primary_rule_id"])
        explanation = "Closed claim: historical decision retained." if closed else (
            before["concise_explanation"] + " Proposed: " + after["concise_explanation"])
        rows.append(dict(case_id=raw["case_id"], current_policy_version=before["policy_version"], proposed_policy_version=candidate.version,
                         recommendation_v1=before["recommendation"], recommendation_v2=after["recommendation"],
                         rule_v1=before["primary_rule_id"], rule_v2=after["primary_rule_id"], explanation=explanation,
                         recommendation_changed=route_changed, needs_recheck=recheck, revision=snapshot["revision"]))
    return dict(rows=rows, policy_diff=diff, affected_open_claims=sum(r["needs_recheck"] for r in rows),
                recommendations_changed=sum(r["recommendation_changed"] for r in rows),
                closed_retained=sum(s["decision"]["case_status"] == "closed" for s in snapshots(db)))


def safety(candidate, baseline, tests, document):
    """Expectations are supplied and signed off by the owner, never generated by the model."""
    conformance = run_checks(candidate)
    blockers, outcomes, coverage = [], [], {}
    if not isinstance(tests, list) or len(tests) > 300:
        raise ValueError("Supply at most 300 independently authored acceptance tests.")
    required = targets(policy_diff(baseline, candidate))
    candidate_rules = {r["id"]: r for r in candidate.config["rules"]}
    baseline_rules = {r["id"]: r for r in baseline.config["rules"]}
    for test in tests:
        if not isinstance(test, dict) or set(test) != {"claim", "expected", "target", "source_quote"}:
            raise ValueError("Acceptance tests require claim, expected, target and source_quote only.")
        if test["expected"] not in ("routine_processing", "request_information", "human_review"):
            raise ValueError("Unsupported expected recommendation.")
        if not isinstance(test["target"], str) or test["target"] not in required:
            raise ValueError("Acceptance-test target must identify a changed rule/setting.")
        if not isinstance(test["source_quote"], str) or not test["source_quote"].strip() or test["source_quote"] not in document:
            raise ValueError("Acceptance expectations require a verbatim source quotation.")
        claim = changes.validate_claim(test["claim"])
        actual = evaluate(claim, candidate)
        previous = evaluate(claim, baseline)
        outcomes.append(dict(case_id=claim.case_id, target=test["target"], expected=test["expected"],
                             actual=actual["recommendation"], before=previous["recommendation"],
                             passed=actual["recommendation"] == test["expected"], source_quote=test["source_quote"]))
        coverage.setdefault(test["target"], []).append(claim)
    if conformance["failed"]:
        blockers.append("Generated boundary or precedence checks failed.")
    if any(not r["passed"] for r in outcomes):
        blockers.append("Mandatory owner-authored acceptance tests failed.")
    from engine.runtime import predicate, UNKNOWN
    for target in required:
        examples = coverage.get(target, [])
        if len(examples) < 2:
            blockers.append(f"Insufficient independent coverage for {target}: at least two examples required.")
        rule = candidate_rules.get(target) or baseline_rules.get(target)
        if not rule:
            continue
        truths = [predicate(rule["if"], c.facts) for c in examples]
        if True not in truths or False not in truths:
            blockers.append(f"{target}: independently labelled matching and nonmatching examples required.")
        for leaf in leaves(rule["if"]):
            if leaf["field"] == "quote_eur" and leaf["op"] in ("gt", "ge", "lt", "le"):
                threshold = Decimal(leaf["value"])
                amounts = [c.facts["quote_eur"] for c in examples if c.facts["quote_eur"] is not UNKNOWN]
                if not (any(a < threshold for a in amounts) and threshold in amounts and any(a > threshold for a in amounts)):
                    blockers.append(f"{target}: independent below/equal/above-threshold expectations required.")
    # Safety invariant independent of any particular policy threshold.
    for field in candidate.config["unknown_handling"]["required_fields"]:
        result = evaluate(parse_claim(dict(BASE, **{field: None})), candidate)
        if result["recommendation"] == "routine_processing":
            blockers.append(f"Missing {field} incorrectly routed routinely.")
    labelled = list(read_claims(ROOT / "data/taktile/labelled_development_cases.csv"))
    v1_quality = measure(labelled, load_policy())
    if v1_quality["errors"]:
        blockers.append("Official v1 labelled development regression failed.")
    transitions = []
    for raw in labelled:
        before, after = evaluate(parse_claim(raw), baseline), evaluate(parse_claim(raw), candidate)
        if before["recommendation"] != after["recommendation"]:
            transitions.append(dict(case_id=raw["case_id"], before=before["recommendation"], after=after["recommendation"],
                                    newly_routine=after["recommendation"] == "routine_processing"))
    total = len(outcomes)
    return dict(passed=not blockers, blockers=blockers, conformance=conformance, acceptance_tests=outcomes,
                regressions=[r for r in outcomes if not r["passed"]],
                quality=dict(denominator=total, before_correct=sum(r["before"] == r["expected"] for r in outcomes),
                             after_correct=sum(r["passed"] for r in outcomes),
                             incorrect_routine=[r for r in outcomes if r["actual"] == "routine_processing" and not r["passed"]]),
                v1_labelled_quality=v1_quality, development_prediction_changes=transitions,
                limitation="Candidate quality uses only owner-authored expectations. V1 labels are not candidate truth. Compound interactions are not exhaustively covered.")


def describe(db, identifier):
    row = proposal(db, identifier)
    review = db.execute("SELECT * FROM proposal_reviews WHERE proposal_id=?", (identifier,)).fetchone()
    interpretation = json.loads(row["interpretation_json"])
    validation = json.loads(row["validation_json"])
    result = dict(proposal_id=identifier, version=row["version"], baseline_hash=row["baseline_hash"],
                  status=review["action"] if review else "pending_approval", interpretation=interpretation,
                  validation=validation, created_at=row["created_at"], stale=changes.active_policy(db).fingerprint != row["baseline_hash"])
    old_version = db.execute("SELECT version FROM policy_versions WHERE policy_hash=?", (row["baseline_hash"],)).fetchone()
    result["old_version"] = old_version[0] if old_version else "unknown"
    if validation["valid"] and not result["stale"]:
        candidate = policy_from_dict(strict_json(interpretation["config_json"]))
        result["impact"] = impact(db, candidate)
    if review:
        result["review"] = {**dict(review), "checks": json.loads(review["checks_json"])}
    return result


def check(db, identifier, body, token):
    actor = owner(token)
    row = proposal(db, identifier)
    baseline = changes.active_policy(db)
    value = json.loads(row["interpretation_json"])
    validation, candidate = validate_interpretation(value, baseline, row["version"], row["old_text"], row["new_text"])
    if baseline.fingerprint != row["baseline_hash"] or not validation["valid"]:
        raise RequestError(409, "Proposal is stale or invalid. Create a revised proposal.")
    checks = safety(candidate, baseline, body.get("tests", []), row["new_text"])
    with db:
        changes.event(db, "policy_safety_checked", actor, {"proposal_id": identifier, "checks": checks}, version=candidate.version)
    report = impact(db, candidate)
    return dict(checks=checks, impact=report, impact_hash=fingerprint(report), validation=validation)


def review(db, identifier, body, token):
    actor = owner(token)
    reason = nonempty(body, "reason")
    action = body.get("action")
    if action not in ("approve", "reject"):
        raise ValueError("Review action must be approve or reject.")
    with db:
        db.execute("BEGIN IMMEDIATE")
        row = proposal(db, identifier)
        existing = db.execute("SELECT * FROM proposal_reviews WHERE proposal_id=?", (identifier,)).fetchone()
        if existing:
            if existing["action"] == ("activated" if action == "approve" else "rejected"):
                return describe(db, identifier)
            raise RequestError(409, "This proposal already has an immutable review.")
        baseline = changes.active_policy(db)
        checks = {}
        candidate = None
        if action == "approve":
            if body.get("acknowledge_limitations") is not True:
                raise ValueError("Explicitly acknowledge the documented test-coverage limitations.")
            if baseline.fingerprint != row["baseline_hash"]:
                raise RequestError(409, "Active policy changed. A fresh proposal is required.")
            validation, candidate = validate_interpretation(json.loads(row["interpretation_json"]), baseline,
                                                           row["version"], row["old_text"], row["new_text"])
            if not validation["valid"]:
                raise RequestError(409, "Invalid or ambiguous proposal cannot be activated.")
            checks = safety(candidate, baseline, body.get("tests", []), row["new_text"])
            if not checks["passed"]:
                changes.event(db, "policy_activation_blocked", actor, {"proposal_id": identifier, "checks": checks}, version=row["version"])
                return {"status": "blocked", "checks": checks}
            prior_version = db.execute("SELECT policy_hash FROM policy_versions WHERE policy_id=? AND version=?",
                                      (candidate.config["policy_id"], candidate.version)).fetchone()
            if prior_version and prior_version[0] != candidate.fingerprint:
                raise RequestError(409, "Immutable policy version already has different content.")
            report = impact(db, candidate)
            expected_impact = body.get("expected_impact_hash")
            if expected_impact != fingerprint(report):
                raise RequestError(409, "Claim population or impact changed. Run safety checks and review the impact again.")
            db.execute("INSERT OR IGNORE INTO policy_versions(policy_id,version,policy_hash,document) VALUES(?,?,?,?)",
                       (candidate.config["policy_id"], candidate.version, candidate.fingerprint, candidate.document))
            db.execute("INSERT INTO policy_activations(proposal_id,policy_document,document_text,actor) VALUES(?,?,?,?)",
                       (identifier, candidate.document, row["new_text"], actor))
            changes.event(db, "policy_change_approved", actor, {"proposal_id": identifier, "reason": reason, "checks": checks}, version=candidate.version)
            for snapshot in snapshots(db):
                raw = snapshot["claim"]
                if snapshot["decision"]["case_status"] == "closed":
                    continue
                result = changes.compare(raw, raw, snapshot["decision"], candidate)
                changes.append_evaluation(db, raw["case_id"], snapshot["revision"] + 1, "policy:" + identifier,
                                          candidate.fingerprint, raw, result, actor, "Approved policy activation: " + reason)
            changes.event(db, "policy_activated", actor, {"proposal_id": identifier, "reason": reason, "impact": report,
                                                        "previous_policy_hash": baseline.fingerprint}, version=candidate.version)
        else:
            changes.event(db, "policy_change_rejected", actor, {"proposal_id": identifier, "reason": reason}, version=row["version"])
        db.execute("INSERT INTO proposal_reviews(proposal_id,action,actor,reason,checks_json) VALUES(?,?,?,?,?)",
                   (identifier, "activated" if action == "approve" else "rejected", actor, reason, json.dumps(checks)))
    return describe(db, identifier)


def workspace(db):
    policy = changes.active_policy(db)
    return dict(policy=policy.config, active_policy_hash=policy.fingerprint, document_text=active_document(db),
                claims=snapshots(db), proposals=[describe(db, r[0]) for r in db.execute("SELECT proposal_id FROM policy_proposals ORDER BY created_at DESC LIMIT 20")],
                event_sequence=db.execute("SELECT COALESCE(MAX(sequence),0) FROM change_events").fetchone()[0])
