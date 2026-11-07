"""Simulate a signed phone call through to a private document upload."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import hashlib
import hmac
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import sqlite3
from tempfile import TemporaryDirectory
import threading
import time
import unittest
from unittest.mock import ANY, MagicMock, Mock, patch
from uuid import uuid4

from backend.__main__ import Handler
from backend.intake import initialize_intakes
from backend.intake_links import initialize_intake_links
from backend.store import RequestError, connect
from backend.tests.test_intake import attachment, claim
from backend.tests.test_reviewer import running_api
from backend.voice import SMSRejected, VoiceIntake, public_origin, vonage_sender


AGENT = "agent_test"
PHONE = "+12025550142"
SECRET = "offline-test-only"
SID = "aaaaaaaa-1111-4444-8888-000000000001"


def event(**updates):
    fields = claim()
    del fields["documents"], fields["request_id"]
    fields.update(confirmed=True, demo_sms_consent=True)
    fields.update(updates)
    return {"type": "post_call_transcription", "data": {
        "agent_id": AGENT, "conversation_id": "conv_demo", "status": "done",
        "metadata": {"conversation_initiation_source": "widget", "phone_call": None, "text_only": False},
        "analysis": {"data_collection_results_list": [
            {"data_collection_id": f"aitem_{i}", "name": k, "value": v}
            for i, (k, v) in enumerate(fields.items())]}}}


def sign(body, timestamp=None):
    stamp = str(int(time.time()) if timestamp is None else timestamp)
    digest = hmac.new(SECRET.encode(), stamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    return f"t={stamp},v0={digest}"


class VoiceTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        path = root / "claims.sqlite3"
        initialize_intakes(path)
        initialize_intake_links(path)
        self.open_store = lambda: closing(connect(path))
        self.send = Mock(return_value=SID)
        self.voice = VoiceIntake(root / "queue", AGENT, SECRET, "https://claims.example.org",
                                 self.open_store, self.send, PHONE)

    def deliver(self, evt):
        body = json.dumps(evt).encode()
        return self.voice.receive(body, sign(body))

    def row(self):
        with closing(self.voice.connect()) as db:
            return db.execute("SELECT * FROM voice_claims").fetchone()

    def test_call_to_upload_over_http(self):
        with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
            server.voice = self.voice
            server.open_store = self.open_store
            server.ui_origin = None
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            self.addCleanup(worker.join, 2)

            def post(endpoint, payload, headers=None):
                with closing(HTTPConnection("127.0.0.1", server.server_port, timeout=5)) as http:
                    http.request("POST", "/api/" + endpoint, body=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json", **(headers or {})})
                    response = http.getresponse()
                    return response.status, json.loads(response.read())

            try:
                evt = event(phone_number="+12025550136", sms_recipient="+12025550137")
                self.assertEqual(post("voice/post-call", evt)[0], 401)
                headers = {"ElevenLabs-Signature": sign(json.dumps(evt).encode())}
                for _ in range(2):
                    self.assertEqual(post("voice/post-call", evt, headers), (200, {"received": True}))
                self.send.assert_not_called()
                with ThreadPoolExecutor(4) as pool:
                    self.assertEqual(list(pool.map(lambda _: self.voice.work_one(), range(4))).count(True), 1)
                phone, body = self.send.call_args.args
                self.assertEqual(phone, PHONE)
                self.assertIn("incident report and itemized repair quote", body)
                token = re.search(r"https://claims.example.org/chat#claim=([a-f0-9]{64})", body)[1]
                status, receipt = post("intakes/resume", {"token": token})
                self.assertEqual(status, 200)
                self.assertIn(receipt["reference"], body)
                status, updated = post("intakes/add-documents", {
                    "token": token, "request_id": str(uuid4()),
                    "documents": [attachment(), attachment("quote.pdf", "itemized_quote")]})
                self.assertEqual(status, 200)
                self.assertEqual(updated["reference"], receipt["reference"])
                self.assertEqual(updated["missing_documents"], [])
                self.assertEqual(post("voice/post-call", evt, headers)[0], 200)
                self.assertFalse(self.voice.work_one())
                self.send.assert_called_once()
                row = self.row()
                self.assertEqual((row["state"], row["sms_sid"]), ("accepted", SID))
                for key in ["phone", "token", "payload"]:
                    self.assertIsNone(row[key])
            finally:
                server.shutdown()

    def test_ignores_incomplete_unconfirmed_other_agent_and_non_browser_voice_events(self):
        cases = [event(confirmed=False), event(confirmed="true"), event(email="missing"), event(location=None)]
        for key, value in [("agent_id", "unrelated"), ("status", "failed")]:
            case = event()
            case["data"][key] = value
            cases.append(case)
        for metadata in [{"text_only": True}, {"phone_call": {"direction": "inbound"}},
                         {"conversation_initiation_source": "twilio"}, {"conversation_initiation_source": "python_sdk"},
                         {"conversation_initiation_source": None}, {"batch_call": {}}, {"whatsapp": {}},
                         {"sms": {}}, {"text_only": None}]:
            case = event()
            case["data"]["metadata"].update(metadata)
            cases.append(case)
        for case in cases:
            self.deliver(case)
            self.assertIsNone(self.row())
        self.send.assert_not_called()

    def test_files_without_text_when_consent_to_team_phone_is_absent(self):
        for i, value in enumerate([False, "true", None]):
            evt = event(demo_sms_consent=value, sms_consent=True, mobile_last_four=PHONE[-4:])
            evt["data"]["conversation_id"] += str(i)
            self.deliver(evt)
            self.assertTrue(self.voice.work_one())
        self.send.assert_not_called()
        with self.open_store() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM intake_submissions").fetchone()[0], 3)

    def test_legacy_queue_migrates_without_redirecting_private_links(self):
        path = self.voice.queue.with_name("old-queue")
        path.touch(mode=0o600)
        with closing(sqlite3.connect(path)) as db, db:
            db.execute("""CREATE TABLE voice_claims (
                conversation TEXT PRIMARY KEY, payload TEXT, token TEXT, phone TEXT,
                state TEXT DEFAULT 'queued', due INTEGER DEFAULT 0, attempts INTEGER DEFAULT 0,
                reference TEXT, sms_sid TEXT)""")
            db.execute("INSERT INTO voice_claims(conversation,payload,token,phone) VALUES (?,?,?,?)",
                       ("legacy", json.dumps(claim(documents=[])), "1" * 64, PHONE))
        migrated = VoiceIntake(path, AGENT, SECRET, self.voice.origin, self.open_store, self.send, PHONE)
        self.assertTrue(migrated.work_one())
        self.send.assert_not_called()
        with closing(migrated.connect()) as db:
            self.assertEqual(db.execute("SELECT state FROM voice_claims").fetchone()[0], "filed")

    def test_changed_demo_handset_does_not_receive_a_queued_link(self):
        self.deliver(event())
        restarted = VoiceIntake(self.voice.queue, AGENT, SECRET, self.voice.origin,
                                self.open_store, self.send, "+12025550136")
        self.assertTrue(restarted.work_one())
        self.send.assert_not_called()
        self.assertEqual(self.row()["state"], "filed")

    def test_rejects_tampering_stale_and_future_signatures(self):
        body = json.dumps(event()).encode()
        for header in [None, sign(body + b"!"), sign(body, int(time.time()) - 350),
                       sign(body, int(time.time()) + 350)]:
            with self.assertRaises(RequestError) as caught:
                self.voice.receive(body, header)
            self.assertEqual(caught.exception.status, 401)
        self.assertIsNone(self.row())

    def test_restart_and_retry_on_rate_limit_but_hold_ambiguous_acceptance(self):
        evt = event()
        extracted = evt["data"]["analysis"].pop("data_collection_results_list")
        evt["data"]["analysis"]["data_collection_results"] = {v["name"]: {"value": v["value"]} for v in extracted}
        self.deliver(evt)
        self.send.side_effect = [SMSRejected(429), TimeoutError()]
        self.voice.work_one()
        before = self.row()
        self.assertEqual(before["state"], "queued")
        self.assertGreater(before["due"], time.time())
        with closing(self.voice.connect()) as db, db:
            db.execute("UPDATE voice_claims SET due=0")
        restarted = VoiceIntake(self.voice.queue, AGENT, SECRET, self.voice.origin, self.open_store, self.send, PHONE)
        restarted.work_one()
        self.assertEqual(self.row()["state"], "review_sms")
        self.assertEqual(self.send.call_args_list[0], self.send.call_args_list[1])
        self.deliver(evt)
        self.assertFalse(restarted.work_one())
        with self.open_store() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM intake_submissions").fetchone()[0], 1)

    def test_store_outage_defers_text_until_filing_succeeds(self):
        self.deliver(event())
        with patch.object(self.voice, "open_store", side_effect=RequestError(503, "unavailable")):
            self.voice.work_one()
        self.assertEqual(self.row()["state"], "queued")
        self.send.assert_not_called()
        with closing(self.voice.connect()) as db, db:
            db.execute("UPDATE voice_claims SET due=0")
        self.voice.work_one()
        self.assertEqual(self.row()["state"], "accepted")
        self.send.assert_called_once()

    def test_upload_origin_is_public_https(self):
        for value in ["http://claims.example.org", "https://127.0.0.1", "https://localhost",
                      "https://host.local", "https://user@claims.example.org", "https://claims.example.org/path"]:
            with self.assertRaises(ValueError):
                public_origin(value)

    def test_normal_startup_exposes_browser_agent_and_files_confirmed_call_in_background(self):
        root = self.voice.queue.parent
        env = {"ELEVENLABS_AGENT_ID": AGENT, "ELEVENLABS_WEBHOOK_SECRET": SECRET,
               "CLAIM_PUBLIC_ORIGIN": self.voice.origin, "VOICE_QUEUE_PATH": str(root / "cli-queue"),
               "VONAGE_SMS_FROM": "ClaimDemo", "VONAGE_API_KEY": "test-user",
               "VONAGE_API_SECRET": "test-secret", "VOICE_DEMO_PHONE": PHONE}
        with patch.dict(os.environ, env), running_api(root / "cli-claims") as port:
            with closing(HTTPConnection("127.0.0.1", port, timeout=5)) as http:
                http.request("GET", "/chat")
                page = http.getresponse().read()
                self.assertIn(f'data-voice-agent="{AGENT}"'.encode(), page)
                self.assertIn(b"https://elevenlabs.io/app/talk-to", page)
                self.assertNotIn(PHONE.encode(), page)
                body = json.dumps(event(demo_sms_consent=False)).encode()
                http.request("POST", "/api/voice/post-call", body,
                             {"Content-Type": "application/json", "ElevenLabs-Signature": sign(body)})
                result = http.getresponse()
                self.assertEqual(result.status, 200, result.read())
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                with closing(connect(root / "cli-claims")) as db:
                    if db.execute("SELECT COUNT(*) FROM intake_submissions").fetchone()[0] == 1:
                        break
                time.sleep(.05)
            else:
                self.fail("The background worker did not file the phone claim.")

    @patch("backend.voice.http.client.HTTPSConnection")
    def test_vonage_acceptance_request_and_error_handling(self, mock_https):
        response = MagicMock(status=202)
        response.read.return_value = json.dumps({"message_uuid": SID}).encode()
        connection = mock_https.return_value
        connection.getresponse.return_value = response
        send = vonage_sender("key", "secret", "ClaimDemo")
        self.assertEqual(send(PHONE, "https://claims.example.org/chat#claim=abc"), SID)
        mock_https.assert_called_once_with("api.nexmo.com", timeout=10, context=ANY)
        args, kwargs = connection.request.call_args
        self.assertEqual(args, ("POST", "/v1/messages"))
        self.assertEqual(kwargs["headers"]["Authorization"], "Basic a2V5OnNlY3JldA==")
        self.assertEqual(json.loads(kwargs["body"]), {"to": PHONE[1:], "from": "ClaimDemo", "channel": "sms",
                         "message_type": "text", "text": "https://claims.example.org/chat#claim=abc"})
        for status in [401, 429]:
            response.status = status
            with self.assertRaises(SMSRejected) as caught:
                send(PHONE, "test")
            self.assertEqual(caught.exception.status, status)
        response.status = 202
        response.read.return_value = b'{"message_uuid":"unknown"}'
        with self.assertRaises(ValueError):
            send(PHONE, "test")
