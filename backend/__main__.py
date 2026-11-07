"""Run the local Policy Replay HTTP service."""

import argparse
from contextlib import closing, nullcontext
import csv
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import sqlite3
import sys
from urllib.parse import unquote, urlsplit

from .chat import answer
from .intake import initialize_intakes, validate_intake
from .intake_links import append_documents, initialize_intake_links, resolve_link, save_draft, submit_linked
from .intake_pdf import extract_pdf
from .store import RequestError, connect, initialize
from .voice import SETTINGS as VOICE_SETTINGS, configured_voice


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCES = [ROOT / "data/taktile" / name for name in
                   ("labelled_development_cases.csv", "unlabelled_practice_cases.csv")]
SERVER_SETTINGS = {"JEV_API_KEY", "JEV_MODEL", "OPENAI_API_KEY", "OPENAI_MODEL", "Vonage_API_Key",
                   "SUPABASE_URL", "SUPABASE_ANON_KEY", "SUPABASE_PUBLISHABLE_KEY"} | VOICE_SETTINGS
INTAKE_REQUEST_LIMIT = 9 * 1024 * 1024  # Three 2 MiB files after base64 encoding, plus form fields.


def load_settings(path):
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        name, equals, value = line.partition("=")
        name, value = name.strip(), value.strip()
        if equals and name in SERVER_SETTINGS:
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
                value = value[1:-1]
            os.environ.setdefault(name, value)


def open_store_factory(mode, database, sources):
    """Configure one data source for every route. Open SQLite per request."""
    url = os.environ.get("SUPABASE_URL", "").strip()
    key = (os.environ.get("SUPABASE_PUBLISHABLE_KEY") or os.environ.get("SUPABASE_ANON_KEY") or "").strip()
    local_args = database is not None or sources is not None
    if mode == "supabase" and local_args:
        raise ValueError("--db and --claims select an offline SQLite database.")
    if mode == "supabase" or (mode == "auto" and not local_args and (url or key)):
        if not url or not key:
            raise ValueError("Set SUPABASE_URL and SUPABASE_PUBLISHABLE_KEY (or SUPABASE_ANON_KEY).")
        from .supabase_store import SupabaseStore
        store = SupabaseStore(url, key)
        return "Supabase", lambda: nullcontext(store)
    path = database or ROOT / "backend/.local/reviewer.sqlite3"
    initialize(path, sources or DEFAULT_SOURCES)
    initialize_intakes(path)
    initialize_intake_links(path)
    return "SQLite", lambda: closing(connect(path))


class Handler(BaseHTTPRequestHandler):
    def reply(self, status, payload=None, media_type=None):
        if isinstance(payload, bytes):
            data = payload
            media_type = media_type or "text/html; charset=utf-8"
        else:
            data = b"" if payload is None else json.dumps(payload, ensure_ascii=False, allow_nan=False).encode()
            media_type = "application/json; charset=utf-8"
        self.send_response(status)
        if self.server.ui_origin and self.headers.get("Origin") == self.server.ui_origin:
            self.send_header("Access-Control-Allow-Origin", self.server.ui_origin)
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Vary", "Origin")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Type", media_type)
        if media_type == "application/pdf":
            self.send_header("Content-Disposition", 'attachment; filename="sample-accident-report.pdf"')
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if data:
            self.wfile.write(data)

    def read_json_bytes(self, max_bytes):
        if self.headers.get_content_type() != "application/json":
            raise RequestError(415, "Send Content-Type: application/json.")
        try:
            size = int(self.headers.get("Content-Length", ""))
        except ValueError:
            raise RequestError(411, "A Content-Length header is required.")
        if not 0 < size <= max_bytes:
            raise RequestError(413, f"Expected a JSON body of at most {max_bytes // 1024} KiB.")
        return self.rfile.read(size)

    def read_json(self, max_bytes=65536):
        try:
            return json.loads(self.read_json_bytes(max_bytes).decode("utf-8"))
        except (UnicodeError, ValueError, RecursionError):
            raise RequestError(400, "Malformed JSON.")

    def dispatch_request(self):
        parts = [unquote(p) for p in urlsplit(self.path).path.strip("/").split("/")]
        if self.command == "POST" and parts == ["api", "voice", "post-call"]:
            voice = getattr(self.server, "voice", None)
            if voice is None:
                raise RequestError(404, "Phone intake is disabled.")
            return 200, voice.receive(self.read_json_bytes(2 * 1024 * 1024),
                                      self.headers.get("ElevenLabs-Signature"))
        if self.command == "GET" and parts in ([""], ["chat"]):
            return 200, self.server.intake_page
        if self.command == "GET" and parts == ["reviewer"]:
            return 200, self.server.reviewer_page
        if self.command == "POST" and parts == ["api", "intakes", "import-pdf"]:
            return 200, extract_pdf(self.read_json(3 * 1024 * 1024))
        with self.server.open_store() as store:
            if self.command == "POST" and len(parts) == 3 and parts[:2] == ["api", "intakes"]:
                action = parts[2]
                if action not in ("save-draft", "resume", "submit", "add-documents"):
                    raise RequestError(404, "Unknown intake endpoint.")
                limit = 65536 if action == "resume" else INTAKE_REQUEST_LIMIT
                body = self.read_json(limit)
                if not isinstance(body, dict):
                    raise RequestError(400, "Send a JSON object.")
                token = body.get("token")
                if action == "resume":
                    return 200, resolve_link(store, token)
                if action == "save-draft":
                    return 200, save_draft(store, token, body.get("draft"), body.get("expected_revision"))
                if action == "submit":
                    return 200, submit_linked(store, token, body.get("payload"), body.get("expected_revision"))
                return 200, append_documents(store, token, body.get("request_id"), body.get("documents"))
            if self.command == "POST" and parts == ["api", "intakes"]:
                payload = validate_intake(self.read_json(INTAKE_REQUEST_LIMIT))
                return 200, store.save_intake(payload)
            if self.command == "GET":
                if parts == ["api", "claims"]:
                    return 200, store.claim_list()
                if parts == ["api", "policy-preview"]:
                    return 200, store.preview()
                if len(parts) == 3 and parts[:2] == ["api", "claims"]:
                    return 200, store.case_detail(parts[2])
            if self.command == "POST" and parts == ["api", "chat"]:
                return 200, answer(store, self.read_json())
            if (self.command == "POST" and len(parts) == 4 and
                    parts[:2] == ["api", "claims"] and parts[3] == "corrections"):
                return store.save_correction(parts[2], self.read_json())
        raise RequestError(404, "Unknown endpoint.")

    def handle_api(self):
        try:
            status, result = self.dispatch_request()
        except RequestError as error:
            status, result = error.status, {"error": str(error)}
        except sqlite3.Error as error:
            self.log_error("database error: %s", error)
            status, result = 503, {"error": "Database unavailable. Please retry."}
        self.reply(status, result)

    def do_GET(self):
        if urlsplit(self.path).path == "/sample-accident-report.pdf":
            self.reply(200, self.server.sample_pdf, "application/pdf")
            return
        self.handle_api()

    do_POST = handle_api

    def do_OPTIONS(self):
        self.reply(204)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env", help="server settings")
    parser.add_argument("--store", choices=("auto", "supabase", "sqlite"), default="auto",
                        help="use configured Supabase by default, or select offline SQLite")
    parser.add_argument("--db", type=Path, help="offline SQLite database path")
    parser.add_argument("--claims", type=Path, nargs="+", help="CSV inputs for offline SQLite")
    parser.add_argument("--ui-origin", help="permitted browser origin, e.g. http://localhost:5173")
    args = parser.parse_args()
    try:
        load_settings(args.env_file)
        storage, open_store = open_store_factory(args.store, args.db, args.claims)
        with ThreadingHTTPServer(("127.0.0.1", args.port), Handler) as server:
            server.open_store = open_store
            if storage == "SQLite":
                claims_path = args.db or ROOT / "backend/.local/reviewer.sqlite3"
                voice_queue = claims_path.with_name(claims_path.name + ".voice-queue")
            else:
                host = urlsplit(os.environ["SUPABASE_URL"]).hostname
                voice_queue = ROOT / "backend/.local" / f"voice-{host}.sqlite3"
            server.voice = configured_voice(open_store, voice_queue)
            server.intake_page = Path(__file__).with_name("intake.html").read_bytes()
            if server.voice:
                agent = server.voice.agent.encode("ascii")
                server.intake_page = server.intake_page.replace(b'data-voice-agent=""',
                                                                 b'data-voice-agent="' + agent + b'"', 1)
            server.sample_pdf = (ROOT / "backend/fixtures/sample-accident-report.pdf").read_bytes()
            server.reviewer_page = Path(__file__).with_name("chat.html").read_bytes()
            server.ui_origin = args.ui_origin
            print(f"Reviewer data source: {storage}", file=sys.stderr, flush=True)
            print(f"Serving Policy Replay at http://127.0.0.1:{server.server_port}", flush=True)
            stopped = server.voice.start() if server.voice else None
            try:
                server.serve_forever()
            finally:
                if stopped:
                    stopped.set()
    except KeyboardInterrupt:
        return
    except (ValueError, OSError, csv.Error, sqlite3.Error) as error:
        sys.exit(f"error: {error}")


if __name__ == "__main__":
    main()
