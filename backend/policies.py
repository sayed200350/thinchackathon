"""Immutable local policy registry and authenticated policy-owner review events."""
import hmac
import json
import os

from engine.conformance import run_checks
from engine.runtime import policy_from_dict
from .store import RequestError


def initialize_registry(db):
    db.executescript("""
        CREATE TABLE IF NOT EXISTS policy_versions (
            policy_id TEXT NOT NULL, version TEXT NOT NULL, policy_hash TEXT NOT NULL,
            document TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
            PRIMARY KEY(policy_id, version));
        CREATE TABLE IF NOT EXISTS policy_reviews (
            event_id INTEGER PRIMARY KEY AUTOINCREMENT, policy_id TEXT NOT NULL,
            version TEXT NOT NULL, policy_hash TEXT NOT NULL, actor TEXT NOT NULL, reason TEXT NOT NULL,
            previous_policy_hash TEXT NOT NULL, conformance_json TEXT NOT NULL,
            occurred_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')));
        CREATE TRIGGER IF NOT EXISTS policy_versions_no_update BEFORE UPDATE ON policy_versions
        BEGIN SELECT RAISE(ABORT, 'Policy versions are immutable'); END;
        CREATE TRIGGER IF NOT EXISTS policy_versions_no_delete BEFORE DELETE ON policy_versions
        BEGIN SELECT RAISE(ABORT, 'Policy versions are immutable'); END;
        CREATE TRIGGER IF NOT EXISTS policy_reviews_no_update BEFORE UPDATE ON policy_reviews
        BEGIN SELECT RAISE(ABORT, 'Policy reviews are append-only'); END;
        CREATE TRIGGER IF NOT EXISTS policy_reviews_no_delete BEFORE DELETE ON policy_reviews
        BEGIN SELECT RAISE(ABORT, 'Policy reviews are append-only'); END;
    """)


def register(db, policy):
    with db:
        db.execute("INSERT OR IGNORE INTO policy_versions(policy_id,version,policy_hash,document) VALUES (?,?,?,?)",
                   (policy.config["policy_id"], policy.version, policy.fingerprint, policy.document))
        prior = db.execute("SELECT policy_hash FROM policy_versions WHERE policy_id=? AND version=?",
                           (policy.config["policy_id"], policy.version)).fetchone()
        if prior[0] != policy.fingerprint:
            raise RequestError(409, "This version already has different immutable content. Use a new version identifier.")


def approve(db, body, token):
    expected = os.environ.get("POLICY_TWIN_OWNER_TOKEN", "")
    if not expected or not isinstance(token, str) or not hmac.compare_digest(expected, token):
        raise RequestError(403, "Policy approval requires the configured policy-owner credential.")
    if not isinstance(body, dict):
        raise RequestError(400, "Expected a review object.")
    for field in ("actor", "reason"):
        if not isinstance(body.get(field), str) or not body[field].strip():
            raise RequestError(400, f"{field} is required.")
    policy = policy_from_dict(body.get("policy"))
    from engine.runtime import load_policy
    baseline = load_policy()
    if policy.config["policy_id"] != baseline.config["policy_id"]:
        raise RequestError(400, "Candidate must belong to the original policy family.")
    if policy.version == "v1" or "hypothetical" in policy.version.lower():
        raise RequestError(400, "Only a genuinely supplied candidate version can be approved; test fixtures cannot be released.")
    if not policy.config.get("source"):
        raise RequestError(400, "A supplied policy source attribution is required for approval.")
    checks = run_checks(policy)
    if checks["failed"]:
        raise RequestError(400, "Generated conformance checks failed.")
    register(db, policy)
    with db:
        cursor = db.execute("""INSERT INTO policy_reviews(policy_id,version,policy_hash,actor,reason,previous_policy_hash,conformance_json)
                            VALUES (?,?,?,?,?,?,?)""", (policy.config["policy_id"], policy.version, policy.fingerprint,
                            body["actor"].strip(), body["reason"].strip(), baseline.fingerprint,
                            json.dumps({"total": checks["total"], "failed": checks["failed"]})))
    event = dict(db.execute("SELECT * FROM policy_reviews WHERE event_id=?", (cursor.lastrowid,)).fetchone())
    return {"review": event, "status": "owner_approved", "activation": "Preview only; no automated deployment or historical rewrite.",
            "independent_v2_quality": "not measured"}
