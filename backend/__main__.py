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
from .store import RequestError, connect, initialize


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCES = [ROOT / "data/taktile" / name for name in
                   ("labelled_development_cases.csv", "unlabelled_practice_cases.csv")]
SERVER_SETTINGS = {"JEV_API_KEY", "JEV_MODEL", "OPENAI_API_KEY", "OPENAI_MODEL",
                   "SUPABASE_URL", "SUPABASE_ANON_KEY", "SUPABASE_PUBLISHABLE_KEY"}


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
    return "SQLite", lambda: closing(connect(path))


class Handler(BaseHTTPRequestHandler):
    def reply(self, status, payload=None):
        if isinstance(payload, bytes):
            data, media_type = payload, "text/html"
        else:
            data = b"" if payload is None else json.dumps(payload, ensure_ascii=False, allow_nan=False).encode()
            media_type = "application/json"
        self.send_response(status)
        if self.server.ui_origin and self.headers.get("Origin") == self.server.ui_origin:
            self.send_header("Access-Control-Allow-Origin", self.server.ui_origin)
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Vary", "Origin")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Type", media_type + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if data:
            self.wfile.write(data)

    def read_json(self):
        if self.headers.get_content_type() != "application/json":
            raise RequestError(415, "Send Content-Type: application/json.")
        try:
            size = int(self.headers.get("Content-Length", ""))
        except ValueError:
            raise RequestError(411, "A Content-Length header is required.")
        if not 0 < size <= 65536:
            raise RequestError(413, "Expected a JSON body of at most 64 KiB.")
        try:
            return json.loads(self.rfile.read(size).decode("utf-8"))
        except (UnicodeError, ValueError):
            raise RequestError(400, "Malformed JSON.")

    def dispatch_request(self):
        parts = [unquote(p) for p in urlsplit(self.path).path.strip("/").split("/")]
        if self.command == "GET" and parts in ([""], ["chat"]):
            return 200, self.server.chat_page
        with self.server.open_store() as store:
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

    do_GET = handle_api
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
            server.chat_page = Path(__file__).with_name("chat.html").read_bytes()
            server.ui_origin = args.ui_origin
            print(f"Reviewer data source: {storage}", file=sys.stderr, flush=True)
            print(f"Serving Policy Replay at http://127.0.0.1:{server.server_port}", flush=True)
            server.serve_forever()
    except KeyboardInterrupt:
        return
    except (ValueError, OSError, csv.Error, sqlite3.Error) as error:
        sys.exit(f"error: {error}")


if __name__ == "__main__":
    main()
