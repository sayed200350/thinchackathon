"""Minimal literal dotenv loader: no expansion, execution, logging or dependencies."""
import os
from pathlib import Path

ALLOWED = {"AI_API_KEY", "AI_PROVIDER", "AI_BASE_URL", "AI_MODEL", "AI_TIMEOUT_SECONDS",
           "POLICY_TWIN_OWNER_TOKEN", "POLICY_TWIN_OWNER_NAME", "CLAIM_REVIEWER_KEY"}


def load_environment(path=None):
    path = path or Path(__file__).resolve().parents[1] / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, sep, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if sep and key in ALLOWED:
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            os.environ.setdefault(key, value)
