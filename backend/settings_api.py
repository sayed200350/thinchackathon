"""Reviewer settings: the API key the AI models use (policy apply and chat).

GET  /api/settings/ai -> provider, model and a masked key; the key itself never leaves the server.
POST /api/settings/ai {"api_key": "..."} -> verified with the provider, applied at once (both the
policy interpreter and the chat read AI_API_KEY per request) and written to the server's .env.
The provider follows the key: an Anthropic key (sk-ant-...) switches to Claude, a Google key
(AIza... / AQ....) to Gemini, together with that provider's API root and default model.
The server only listens on 127.0.0.1 and JSON POSTs need the CORS preflight that only the
configured UI origin passes, so other websites cannot change the key.
"""
import os
import re
import tempfile
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request

from .store import RequestError

KEY_PATTERN = re.compile(r"[A-Za-z0-9._\-]{20,200}")


# Provider defaults applied when a key of another provider is saved.
PROVIDERS = {
    "anthropic": {"AI_BASE_URL": "https://api.anthropic.com/v1", "AI_MODEL": "claude-opus-5-5"},
    "gemini": {"AI_BASE_URL": "https://generativelanguage.googleapis.com/v1beta", "AI_MODEL": "gemini-3.5-flash"},
}


def provider_for(key):
    """Provider implied by the key format, or None to keep the configured one."""
    if key.startswith("sk-ant-"):
        return "anthropic"
    if key.startswith(("AIza", "AQ.")):
        return "gemini"
    return None


def masked(key):
    return f"…{key[-4:]}" if len(key) >= 8 else ("set" if key else "")


def ai_settings():
    key = os.environ.get("AI_API_KEY", "").strip()
    return {"provider": os.environ.get("AI_PROVIDER", "disabled").strip() or "disabled",
            "model": os.environ.get("AI_MODEL", "").strip(),
            "base_url": os.environ.get("AI_BASE_URL", "").strip(),
            "key_set": bool(key), "key_hint": masked(key)}


def _open(request, timeout):
    from .ai_service import NoRedirect  # same redirect-free opener the model calls use
    from urllib.request import build_opener
    return build_opener(NoRedirect).open(request, timeout=timeout)


def target_settings(key):
    """AI_PROVIDER/AI_BASE_URL/AI_MODEL to use with this key (unchanged unless the key names another provider)."""
    current = {name: os.environ.get(name, "").strip() for name in ("AI_PROVIDER", "AI_BASE_URL", "AI_MODEL")}
    provider = provider_for(key)
    if provider and provider != current["AI_PROVIDER"]:
        return {"AI_PROVIDER": provider, **PROVIDERS[provider]}
    return current


def verify_key(key, opener=_open, settings=None):
    """Ask the provider whether the key is accepted. Listing models costs no generation quota.

    Returns a warning string (key accepted with a caveat) or None; raises RequestError if refused.
    """
    settings = settings or target_settings(key)
    provider = settings["AI_PROVIDER"]
    base = settings["AI_BASE_URL"].rstrip("/")
    if provider not in ("gemini", "anthropic", "openai_compatible"):
        raise RequestError(409, "AI is disabled on this server. Set AI_PROVIDER in .env first.")
    if urlsplit(base).scheme != "https":
        raise RequestError(409, "AI_BASE_URL must be an https URL before a key can be checked.")
    if provider == "gemini":
        headers = {"x-goog-api-key": key}
    elif provider == "anthropic":
        headers = {"x-api-key": key, "anthropic-version": "2026-10-21"}
    else:
        headers = {"Authorization": f"Bearer {key}"}
    try:
        with opener(Request(base + "/models", headers=headers), 15) as response:
            response.read(1)
    except HTTPError as error:
        if error.code == 429:
            return "The provider accepted the key but reports its quota as exhausted (HTTP 429)."
        if error.code in (400, 401, 403):
            raise RequestError(422, "The provider rejected this API key.") from None
        raise RequestError(502, f"The provider answered HTTP {error.code}; the key was not saved.") from None
    except (URLError, TimeoutError, OSError):
        raise RequestError(502, "The provider could not be reached; the key was not saved.") from None
    return None


def write_env(path, name, value):
    """Replace or append one NAME=value line, keeping every other line, atomically, mode 600."""
    path = Path(path)
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    out, done = [], False
    for line in lines:
        if line.partition("=")[0].strip() == name:
            if not done:
                out.append(f"{name}={value}")
                done = True
            continue
        out.append(line)
    if not done:
        out.append(f"{name}={value}")
    handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=".env.")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write("\n".join(out) + "\n")
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def update_ai_key(body, env_path, opener=_open):
    if not isinstance(body, dict) or set(body) != {"api_key"} or not isinstance(body["api_key"], str):
        raise RequestError(400, 'Send {"api_key": "..."}.')
    key = body["api_key"].strip()
    if not KEY_PATTERN.fullmatch(key):
        raise RequestError(400, "That does not look like an API key (20-200 letters, digits, . _ -).")
    settings = target_settings(key)
    warning = verify_key(key, opener, settings)
    changed = {name: value for name, value in settings.items() if os.environ.get(name, "").strip() != value}
    if env_path:
        for name, value in changed.items():
            write_env(env_path, name, value)
        write_env(env_path, "AI_API_KEY", key)
    os.environ.update(changed)
    os.environ["AI_API_KEY"] = key  # live for the next policy apply and chat request
    return dict(ai_settings(), saved=True, persisted=bool(env_path), warning=warning)


def handle(method, body_reader, env_path):
    if method == "GET":
        return 200, ai_settings()
    return 200, update_ai_key(body_reader(), env_path)

