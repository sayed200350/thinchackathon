"""The judge room can only serve fictional intake from its own temporary store."""
import base64
from contextlib import ExitStack
from pathlib import Path
import secrets
from tempfile import TemporaryDirectory
from threading import Thread
import unittest
from uuid import uuid4

from backend.__main__ import Handler, ThreadingHTTPServer, open_store_factory
from backend.judge_demo import FIXTURES, JudgeHandler, PERSONA
from backend.tests.test_reviewer import call


class JudgeRoomTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.key = secrets.token_hex(32)
        self.port = self.server(JudgeHandler)

    def server(self, handler):
        directory = Path(self.stack.enter_context(TemporaryDirectory()))
        _, factory = open_store_factory("sqlite", directory / "claims.db", None)
        server = self.stack.enter_context(ThreadingHTTPServer(("127.0.0.1", 0), handler))
        server.open_store = factory
        server.ui_origin = None
        server.judge_key = self.key
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.stack.callback(thread.join)
        self.stack.callback(server.shutdown)
        return server.server_port

    def test_each_session_has_a_separate_inbox_and_original_document(self):
        doc = (FIXTURES / "quotes/itemized-1300.pdf").read_bytes()
        packet = {"evidence_version": 1, "expected_revision": 0, "token": secrets.token_hex(32),
                  "payload": {**PERSONA, "demo_case": "DEV-003", "request_id": str(uuid4()),
                              "documents": [{"kind": "itemized_quote", "name": "phone-copy.pdf",
                                             "content_base64": base64.b64encode(doc).decode()}]}}
        status, receipt, _ = call(self.port, "POST", "/judge/api/intakes/submit", packet)
        self.assertEqual(status, 200, receipt)
        key = {"reviewer_key": self.key}
        rows = call(self.port, "POST", "/api/judge/inbox", key)[1]["claims"]
        self.assertEqual([r["reference"] for r in rows], [receipt["reference"]])
        self.assertEqual(call(self.server(JudgeHandler), "POST", "/api/judge/inbox", key)[1]["claims"], [])
        file = call(self.port, "POST", "/api/judge/document", {**key, "reference": receipt["reference"], "position": 0})[1]
        self.assertEqual(file["name"], "itemized-1300.pdf")
        self.assertEqual(base64.b64decode(file["content_base64"]), doc)
        packet["payload"]["email"] = "person@example.org"
        self.assertEqual(call(self.port, "POST", "/judge/api/intakes/submit", packet)[0], 400)

    def test_routes_and_uploads_fail_closed(self):
        normal = self.server(Handler)
        for port, path, expected in [
            (normal, "/api/judge/inbox", 404), (normal, "/judge/api/intakes/submit", 404),
            (self.port, "/api/staff/inbox", 404), (self.port, "/api/judge/corrections", 404),
            (self.port, "/api/judge/inbox", 403),
        ]:
            with self.subTest(path=path):
                self.assertEqual(call(port, "POST", path, {})[0], expected)
        for endpoint in ("/api/garage/upload", "/judge/api/intakes/add-documents"):
            doc = {"name": "personal.pdf", "content_base64": "dGVzdA=="}
            body = {"document": doc} if endpoint.endswith("upload") else {"documents": [doc]}
            status, result, _ = call(self.port, "POST", endpoint, body)
            self.assertEqual(status, 400)
            self.assertIn("sample documents", result["error"])
