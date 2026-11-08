"""Run one loopback-only, temporary judge room using the real intake and policy engine."""
import argparse
import base64
from hashlib import sha256
import os
from pathlib import Path
import secrets
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit

from .__main__ import Handler, ROOT, ThreadingHTTPServer, open_store_factory
from .intake_replay import replay_versions
from .staff import staff_action
from .store import RequestError

FIXTURES = ROOT / "backend/fixtures"
SAMPLES = {sha256(p.read_bytes()).digest(): p.name for p in FIXTURES.rglob("*") if p.is_file()}
PERSONA = {
    "description": "My bumper was damaged in a parking incident.", "incident_date": "2025-10-18",
    "location": "Demo car park, Munich", "policy_number": "DEMO-003",
    "email": "driver@example.invalid", "injury_status": "no",
}
INTAKE = {"/api/intakes/" + name for name in
          ("save-draft", "submit", "add-documents", "resume", "garage-link", "import-pdf")}


def sample_document(doc):
    if isinstance(doc, dict) and isinstance(doc.get("content_base64"), str):
        try:
            name = SAMPLES.get(sha256(base64.b64decode(doc["content_base64"], validate=True)).digest())
        except ValueError:
            name = None
        if name:
            doc["name"] = name  # Phones can rename a downloaded file.
            return
    raise RequestError(400, "Choose one of the sample documents provided for the judge demo.")


class JudgeHandler(Handler):
    def read_json(self, max_bytes=65536):
        body = super().read_json(max_bytes)
        if not isinstance(body, dict):
            raise RequestError(400, "Expected an object.")
        action = self.path.rsplit("/", 1)[-1]
        if action in ("submit", "save-draft"):
            packet = body.get("payload" if action == "submit" else "draft")
            values = packet.get("values", packet) if isinstance(packet, dict) else {}
            if (not isinstance(packet, dict) or packet.get("demo_case") != "DEV-003"
                    or body.get("evidence_version") != 1 or not isinstance(values, dict)
                    or any(values.get(k, v if action == "save-draft" else None) != v for k, v in PERSONA.items())):
                raise RequestError(400, "Start the sample claim and keep its fictional incident details.")
        else:
            packet = body
        docs = packet.get("documents", [])
        if not isinstance(docs, list):
            raise RequestError(400, "Expected a list of sample documents.")
        for doc in docs:
            sample_document(doc)
        if action in ("quote", "upload"):
            sample_document(body.get("document"))
        return body

    def dispatch_request(self):
        path = urlsplit(self.path).path
        if self.command == "POST" and path.startswith("/api/judge/"):
            action = path.removeprefix("/api/judge/")
            if action in ("inbox", "reviewer", "document", "replay"):
                body = self.read_json()
                with self.server.open_store() as store:
                    result = staff_action(store, "reviewer" if action == "replay" else action,
                                          body, self.server.judge_key)
                    return 200, replay_versions(result, body) if action == "replay" else result
        if self.command == "POST" and path.startswith("/judge/"):
            inner = path.removeprefix("/judge")
            if inner in INTAKE or inner == "/api/evidence/quote":
                self.path = inner
                return super().dispatch_request()
        if self.command == "POST" and path in ("/api/garage/status", "/api/garage/upload"):
            return super().dispatch_request()
        raise RequestError(404, "Unknown judge demo operation.")

    def do_GET(self):
        if self.path == "/garage":
            html = (ROOT / "backend/garage.html").read_bytes()
            self.reply(200, html.replace(b"<main>", b"<main><p>Judge demo. Use the sample quote below. "
                                         b"Insurer demo viewers can open it.</p>"))
        else:
            super().do_GET()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8782)
    parser.add_argument("--garage-public-origin", required=True)
    args = parser.parse_args()
    key = os.getenv("JUDGE_DEMO_KEY", "")
    if len(key) < 32:
        parser.error("Set a dedicated JUDGE_DEMO_KEY of at least 32 characters.")
    with TemporaryDirectory(prefix="retakt-judge-") as room:
        _, factory = open_store_factory("sqlite", Path(room) / "claims.sqlite", None)
        with ThreadingHTTPServer(("127.0.0.1", args.port), JudgeHandler) as server:
            server.open_store = factory
            server.judge_key = key
            server.garage_key = secrets.token_hex(32)
            server.garage_origin = args.garage_public_origin
            server.sample_pdf = (FIXTURES / "sample-accident-report.pdf").read_bytes()
            server.ui_origin = None
            print(f"Judge room listening on 127.0.0.1:{server.server_port}", flush=True)
            server.serve_forever()


if __name__ == "__main__":
    main()
