"""Original decisions and append-only reviewer history in a local SQLite database."""

from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3

from engine import ROUTES, decide
from engine.batch import read_claims
from engine.policy import FIELDS


class RequestError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def connect(database: Path) -> sqlite3.Connection:
    db = sqlite3.connect(database, timeout=5)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db


def initialize(database: Path, sources: list) -> None:
    database.parent.mkdir(parents=True, exist_ok=True)
    with closing(connect(database)) as db, db:
        db.execute("PRAGMA journal_mode = WAL")
        db.executescript("""
            CREATE TABLE IF NOT EXISTS claims (
                case_id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                claim_json TEXT NOT NULL,
                decision_json TEXT NOT NULL,
                original_route TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS corrections (
                case_id TEXT NOT NULL REFERENCES claims(case_id),
                revision INTEGER NOT NULL,
                request_id TEXT NOT NULL,
                reviewer TEXT NOT NULL,
                reason TEXT NOT NULL,
                policy_version TEXT NOT NULL,
                previous_recommendation TEXT NOT NULL,
                recommendation TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                PRIMARY KEY (case_id, revision),
                UNIQUE (case_id, request_id)
            );
        """)
        from .policies import initialize_registry, register
        from engine.runtime import load_policy
        initialize_registry(db)
        register(db, load_policy())
        from . import changes, adaptation
        changes.initialize(db)
        adaptation.initialize(db)
        db.executescript("""
            CREATE TRIGGER IF NOT EXISTS claims_no_update BEFORE UPDATE ON claims
            BEGIN SELECT RAISE(ABORT, 'Original machine decisions are immutable'); END;
            CREATE TRIGGER IF NOT EXISTS claims_no_delete BEFORE DELETE ON claims
            BEGIN SELECT RAISE(ABORT, 'Original machine decisions are immutable'); END;
            CREATE TRIGGER IF NOT EXISTS corrections_no_update BEFORE UPDATE ON corrections
            BEGIN SELECT RAISE(ABORT, 'Corrections are append-only'); END;
            CREATE TRIGGER IF NOT EXISTS corrections_no_delete BEFORE DELETE ON corrections
            BEGIN SELECT RAISE(ABORT, 'Corrections are append-only'); END;
        """)
        for path in sources:
            for row in read_claims(path):
                result = decide(row)
                result["created_at"] = datetime.now(timezone.utc).isoformat()
                claim = {k: row.get(k) for k in ("case_id", "case_status", "claim_summary", *FIELDS)}
                added = db.execute("""INSERT INTO claims VALUES (?, ?, ?, ?, ?)
                                      ON CONFLICT(case_id) DO NOTHING""",
                           (result["case_id"], result["case_status"], json.dumps(claim),
                            json.dumps(result), result["recommendation"]))
                if added.rowcount == 0:
                    stored = db.execute("SELECT claim_json FROM claims WHERE case_id = ?",
                                        (result["case_id"],)).fetchone()
                    if json.loads(stored["claim_json"]) != claim:
                        raise ValueError(f"{result['case_id']}: input differs from its saved snapshot. "
                                         "Use the original CSV or start with a new --db path.")
                else:
                    changes.event(db, "claim_created", "csv_import", {"claim": claim, "recommendation": result["recommendation"]},
                                  result["case_id"], result["policy_version"])


def claim_list(db):
    rows = db.execute("""
        SELECT c.case_id, c.status AS case_status, c.original_route AS recommendation,
               COALESCE(h.recommendation, c.original_route) AS effective_recommendation,
               COALESCE(h.revision, 0) AS revision
        FROM claims c LEFT JOIN corrections h
          ON h.case_id = c.case_id AND h.revision = (
             SELECT MAX(revision) FROM corrections WHERE case_id = c.case_id)
        ORDER BY c.case_id
    """)
    return {"claims": [dict(row) for row in rows]}


def case_detail(db, case_id):
    claim = db.execute("SELECT * FROM claims WHERE case_id = ?", (case_id,)).fetchone()
    if claim is None:
        raise RequestError(404, "Unknown case_id.")
    history = [dict(row) for row in db.execute(
        """SELECT revision, request_id, reviewer, reason, policy_version, previous_recommendation,
                  recommendation, created_at FROM corrections WHERE case_id = ? ORDER BY revision""",
        (case_id,))]
    return {
        "claim": json.loads(claim["claim_json"]),
        "decision": json.loads(claim["decision_json"]),
        "effective_recommendation": history[-1]["recommendation"] if history else claim["original_route"],
        "revision": len(history),
        "history": history,
    }


def save_correction(db, case_id, body):
    if not isinstance(body, dict):
        raise RequestError(400, "Expected a JSON object.")
    values = {}
    for field in ("request_id", "recommendation", "reviewer", "reason", "policy_version"):
        raw = body.get(field)
        if not isinstance(raw, str) or not raw.strip():
            raise RequestError(400, f"{field} must be a nonempty string.")
        values[field] = raw.strip()
    expected = body.get("expected_revision")
    if type(expected) is not int or expected < 0:
        raise RequestError(400, "expected_revision must be a nonnegative integer.")
    if values["recommendation"] not in ROUTES:
        raise RequestError(400, "Unknown recommendation.")

    with db:
        # Serialize revision check, idempotency check and audit insert across writers.
        db.execute("BEGIN IMMEDIATE")
        detail = case_detail(db, case_id)
        prior = db.execute("SELECT * FROM corrections WHERE case_id = ? AND request_id = ?",
                           (case_id, values["request_id"])).fetchone()
        if prior is not None:
            if prior["revision"] == expected + 1 and all(prior[k] == v for k, v in values.items()):
                return 200, detail
            raise RequestError(409, "request_id already belongs to a different correction.")
        if detail["decision"]["case_status"] == "closed":
            raise RequestError(409, "Closed claims retain their original decision.")
        if values["policy_version"] != detail["decision"]["policy_version"]:
            raise RequestError(409, "Policy version mismatch. Reload this claim.")
        if detail["revision"] != expected:
            raise RequestError(409, "Another reviewer updated this claim. Reload before saving.")
        if values["recommendation"] == detail["effective_recommendation"]:
            raise RequestError(400, "Choose a different recommendation for a correction.")
        db.execute("""INSERT INTO corrections
            (case_id, revision, request_id, reviewer, reason, policy_version, previous_recommendation,
             recommendation) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (case_id, expected + 1, values["request_id"], values["reviewer"], values["reason"],
             values["policy_version"], detail["effective_recommendation"], values["recommendation"]))
        from .changes import event
        event(db, "reviewer_override_recorded", values["reviewer"], values, case_id, values["policy_version"])
        return 201, case_detail(db, case_id)


def preview(db):
    counts = dict(db.execute("SELECT status, COUNT(*) FROM claims GROUP BY status"))
    return {"status": "awaiting_v2", "from_version": "v1", "to_version": "v2",
            "open_claims": counts.get("open", 0), "closed_claims": counts.get("closed", 0),
            "changes": None}
