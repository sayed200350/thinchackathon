"""Run the policy adaptation workbench on a separate loopback port and SQLite database."""

import argparse
from contextlib import closing
import csv
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import sqlite3
import sys
from threading import Condition
from urllib.parse import unquote, urlsplit

from .store import RequestError, case_detail, claim_list, connect, initialize, preview, save_correction
from . import workbench, changes, adaptation, workbench_inbox
from .ai_service import AIUnavailable


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCES = []  # No claims are preloaded; users upload their own CSV in the browser.


class Handler(BaseHTTPRequestHandler):
    def reply(self, status, payload=None):
        data = b"" if payload is None else json.dumps(payload, ensure_ascii=False, allow_nan=False).encode()
        self.send_response(status)
        if (not urlsplit(self.path).path.startswith("/api/incoming/") and self.server.ui_origin
                and self.headers.get("Origin") == self.server.ui_origin):
            self.send_header("Access-Control-Allow-Origin", self.server.ui_origin)
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Policy-Owner-Token")
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
        limit = 2 * 1024 * 1024 if urlsplit(self.path).path in ("/api/workbench/run", "/api/adaptation/proposals") else 512000
        if not 0 < size <= limit:
            raise RequestError(413, f"Expected a JSON body of at most {limit} bytes.")
        try:
            def unique(pairs):
                result = {}
                for key, value in pairs:
                    if key in result:
                        raise ValueError("Duplicate JSON key")
                    result[key] = value
                return result
            return json.loads(self.rfile.read(size).decode("utf-8"), object_pairs_hook=unique)
        except (UnicodeError, ValueError):
            raise RequestError(400, "Malformed JSON.")

    def dispatch_request(self):
        parts = [unquote(p) for p in urlsplit(self.path).path.strip("/").split("/")]
        if self.command == "POST" and len(parts) == 3 and parts[:2] == ["api", "incoming"]:
            port = self.server.server_port
            host = self.headers.get("Host")
            if host not in (f"127.0.0.1:{port}", f"localhost:{port}") or self.headers.get("Origin") != f"http://{host}":
                raise RequestError(403, "Open the inbox from the local workbench.")
            return 200, workbench_inbox.incoming(self.server.intake_port, parts[2], self.read_json(),
                                                 self.server.reviewer_key)
        with closing(connect(self.server.database)) as db:
            if self.command == "GET":
                if parts == ["api", "adaptation"]:
                    return 200, adaptation.workspace(db)
                if len(parts) == 4 and parts[:3] == ["api", "adaptation", "claims"]:
                    return 200, changes.history(db, parts[3])
                if len(parts) == 4 and parts[:3] == ["api", "adaptation", "proposals"]:
                    return 200, adaptation.describe(db, parts[3])
                if parts == ["api", "adaptation", "audit"]:
                    return 200, {"events": [{**dict(r), "payload": json.loads(r["payload"])} for r in db.execute("SELECT * FROM change_events ORDER BY sequence")]}
                if parts == ["api", "workbench"]:
                    return 200, workbench.workspace(db)
                if parts == ["api", "claims"]:
                    return 200, claim_list(db)
                if parts == ["api", "policy-preview"]:
                    return 200, preview(db)
                if len(parts) == 3 and parts[:2] == ["api", "claims"]:
                    return 200, case_detail(db, parts[2])
            if self.command == "POST" and parts == ["api", "workbench", "run"]:
                return 200, workbench.run(self.read_json(), db)
            if self.command == "POST" and parts[:2] == ["api", "adaptation"]:
                body = self.read_json()
                if not isinstance(body, dict):
                    raise ValueError("Expected a JSON object.")
                token = self.headers.get("X-Policy-Owner-Token")
                if parts == ["api", "adaptation", "preview"]:
                    return 200, changes.preview(db, body)
                if parts == ["api", "adaptation", "claims"]:
                    return 201, changes.save(db, body)
                if parts == ["api", "adaptation", "proposals"]:
                    return 201, adaptation.propose(db, body, token)
                if len(parts) == 5 and parts[2] == "proposals":
                    if parts[4] == "check":
                        return 200, adaptation.check(db, parts[3], body, token)
                    if parts[4] == "review":
                        return 200, adaptation.review(db, parts[3], body, token)
            if self.command == "POST" and parts == ["api", "policies", "approve"]:
                from .policies import approve
                return 201, approve(db, self.read_json(), self.headers.get("X-Policy-Owner-Token"))
            if (self.command == "POST" and len(parts) == 4 and
                    parts[:2] == ["api", "claims"] and parts[3] == "corrections"):
                return save_correction(db, parts[2], self.read_json(), workbench=True)
        raise RequestError(404, "Unknown endpoint.")

    def handle_api(self):
        try:
            status, result = self.dispatch_request()
        except RequestError as error:
            status, result = error.status, {"error": str(error)}
        except AIUnavailable as error:
            status, result = 503, {"error": str(error)}
        except (ValueError, csv.Error, RecursionError) as error:
            status, result = 400, {"error": str(error)}
        except sqlite3.Error as error:
            self.log_error("database error: %s", error)
            status, result = 503, {"error": "Database unavailable. Please retry."}
        self.reply(status, result)
        if self.command == "POST" and 200 <= status < 300 and hasattr(self.server, "updates"):
            with self.server.updates:
                self.server.updates.notify_all()

    def stream_events(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        try:
            last = int(self.headers.get("Last-Event-ID", "0"))
        except ValueError:
            last = 0
        try:
            while True:
                # Condition notifications wake readers immediately; the timeout is a connection heartbeat.
                with self.server.updates:
                    with closing(connect(self.server.database)) as db:
                        latest = db.execute("SELECT COALESCE(MAX(sequence),0) FROM change_events").fetchone()[0]
                    if latest > last:
                        self.wfile.write(f"id: {latest}\nevent: change\ndata: {{\"sequence\":{latest}}}\n\n".encode())
                        last = latest
                    else:
                        self.wfile.write(b": heartbeat\n\n")
                    self.wfile.flush()
                    self.server.updates.wait(timeout=15)
        except (BrokenPipeError, ConnectionResetError, OSError):
            return

    def do_GET(self):
        if urlsplit(self.path).path == "/api/adaptation/events":
            return self.stream_events()
        assets = {"/incoming": ("incoming.html", "text/html"), "/incoming.js": ("incoming.js", "text/javascript"),
                  "/": ("index.html", "text/html"), "/workbench.js": ("workbench.js", "text/javascript"),
                  "/workbench.css": ("workbench.css", "text/css"),
                  "/explain.js": ("explain.js", "text/javascript"),
                  "/adaptation.js": ("adaptation.js", "text/javascript")}
        asset = assets.get(urlsplit(self.path).path)
        if asset:
            data = (Path(__file__).parent / "web" / asset[0]).read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", asset[1] + "; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            if asset[0] == "incoming.html":
                self.send_header("Content-Security-Policy", "frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(data)
            return
        self.handle_api()
    do_POST = handle_api

    def do_OPTIONS(self):
        self.reply(204)


def main():
    from .environment import load_environment
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, help="server settings, including the staff connection credential")
    parser.add_argument("--port", type=int, default=8767)
    parser.add_argument("--intake-port", type=int, default=8765, help="local claimant API port for submitted claims")
    parser.add_argument("--db", type=Path, default=ROOT / "backend/.local/workbench.sqlite3")
    parser.add_argument("--claims", type=Path, nargs="*", default=DEFAULT_SOURCES)
    parser.add_argument("--ui-origin", help="permitted browser origin, e.g. http://localhost:5173")
    parser.add_argument("--open", action="store_true", help="open the workbench in your default browser")
    args = parser.parse_args()
    try:
        load_environment(args.env_file)
        initialize(args.db, args.claims, workbench=True)
        with ThreadingHTTPServer(("127.0.0.1", args.port), Handler) as server:
            server.intake_port = args.intake_port
            server.reviewer_key = os.getenv("CLAIM_REVIEWER_KEY")
            server.database = args.db
            server.ui_origin = args.ui_origin
            server.updates = Condition()
            print(f"Serving Policy Replay at http://127.0.0.1:{server.server_port}", flush=True)
            if args.open:
                import webbrowser
                webbrowser.open(f"http://127.0.0.1:{server.server_port}")
            server.serve_forever()
    except KeyboardInterrupt:
        return
    except (ValueError, OSError, csv.Error, sqlite3.Error) as error:
        sys.exit(f"error: {error}")


if __name__ == "__main__":
    main()
