"""Append-only version bindings for CLI previews; evaluation itself remains pure."""
import sqlite3
from pathlib import Path


def bind_versions(path, *policies):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    try:
        connection.executescript("""
            CREATE TABLE IF NOT EXISTS versions (
                policy_id TEXT NOT NULL, version TEXT NOT NULL, fingerprint TEXT NOT NULL,
                document TEXT NOT NULL, PRIMARY KEY(policy_id, version));
            CREATE TRIGGER IF NOT EXISTS versions_no_update BEFORE UPDATE ON versions
            BEGIN SELECT RAISE(ABORT, 'Immutable policy version'); END;
            CREATE TRIGGER IF NOT EXISTS versions_no_delete BEFORE DELETE ON versions
            BEGIN SELECT RAISE(ABORT, 'Immutable policy version'); END;
        """)
        with connection:
            for policy in policies:
                key = policy.config["policy_id"], policy.version
                connection.execute("INSERT OR IGNORE INTO versions VALUES(?,?,?,?)", (*key, policy.fingerprint, policy.document))
                prior = connection.execute("SELECT fingerprint FROM versions WHERE policy_id=? AND version=?", key).fetchone()
                if prior[0] != policy.fingerprint:
                    raise ValueError(f"Version {policy.version} has different registered content. Choose a new version.")
    finally:
        connection.close()
