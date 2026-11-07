"""Run the local Policy Replay HTTP service."""

import argparse
from contextlib import closing
import csv
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sqlite3
import sys
from urllib.parse import unquote, urlsplit

from .store import RequestError, case_detail, claim_list, connect, initialize, preview, save_correction


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCES = [ROOT / "data/taktile" / name for name in
                   ("labelled_development_cases.csv", "unlabelled_practice_cases.csv")]


class Handler(BaseHTTPRequestHandler):
    def reply(self, status, payload=None):
        data = b"" if payload is None else json.dumps(payload, ensure_ascii=False, allow_nan=False).encode()
        self.send_response(status)
        if self.server.ui_origin and self.headers.get("Origin") == self.server.ui_origin:
            self.send_header("Access-Control-Allow-Origin", self.server.ui_origin)
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Vary", "Origin")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Type", "application/json; charset=utf-8")
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
        with closing(connect(self.server.database)) as db:
            if self.command == "GET":
                if parts == ["api", "claims"]:
                    return 200, claim_list(db)
                if parts == ["api", "policy-preview"]:
                    return 200, preview(db)
                if len(parts) == 3 and parts[:2] == ["api", "claims"]:
                    return 200, case_detail(db, parts[2])
            if (self.command == "POST" and len(parts) == 4 and
                    parts[:2] == ["api", "claims"] and parts[3] == "corrections"):
                return save_correction(db, parts[2], self.read_json())
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
    parser.add_argument("--db", type=Path, default=ROOT / "backend/.local/reviewer.sqlite3")
    parser.add_argument("--claims", type=Path, nargs="+", default=DEFAULT_SOURCES)
    parser.add_argument("--ui-origin", help="permitted browser origin, e.g. http://localhost:5173")
    args = parser.parse_args()
    try:
        initialize(args.db, args.claims)
        with ThreadingHTTPServer(("127.0.0.1", args.port), Handler) as server:
            server.database = args.db
            server.ui_origin = args.ui_origin
            print(f"Serving Policy Replay at http://127.0.0.1:{server.server_port}", flush=True)
            server.serve_forever()
    except KeyboardInterrupt:
        return
    except (ValueError, OSError, csv.Error, sqlite3.Error) as error:
        sys.exit(f"error: {error}")


if __name__ == "__main__":
    main()
