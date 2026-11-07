"""Browser voice claims and private upload links sent to the verified Vonage demo phone."""
import base64
from contextlib import closing
import hashlib
import hmac
import http.client
import ipaddress
import json
import logging
import os
from pathlib import Path
import re
import secrets
import sqlite3
import ssl
import sys
import threading
import time
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from .intake import validate_intake
from .intake_links import submit_linked
from .store import RequestError

SETTINGS = {"ELEVENLABS_AGENT_ID", "ELEVENLABS_WEBHOOK_SECRET", "CLAIM_PUBLIC_ORIGIN",
            "VONAGE_API_KEY", "VONAGE_API_SECRET", "VONAGE_SMS_FROM", "VOICE_DEMO_PHONE", "VOICE_QUEUE_PATH"}
PHONE = re.compile(r"\+[1-9][0-9]{6,14}")
LABELS = {"incident_report": "incident report", "itemized_quote": "itemized repair quote"}
LOG = logging.getLogger(__name__)


def public_origin(value):
    parts = urlsplit(value)
    host = parts.hostname or ""
    port = parts.port  # Reject malformed and out-of-range ports.
    if (parts.scheme != "https" or not host or parts.username is not None or parts.password is not None
            or parts.path not in ("", "/") or parts.query or parts.fragment
            or re.search(r"[\s\\?#]", value) or parts.netloc.endswith(":") or port == 0):
        raise ValueError("CLAIM_PUBLIC_ORIGIN must be a public HTTPS origin serving the claimant chat.")
    try:
        public = ipaddress.ip_address(host).is_global
    except ValueError:
        public = (bool(re.fullmatch(r"(?:[a-z0-9-]+\.)+[a-z]{2,63}", host))
                  and not host.endswith((".localhost", ".local", ".internal")))
    if not public:
        raise ValueError("CLAIM_PUBLIC_ORIGIN must be reachable from the caller's phone.")
    return value.rstrip("/")


def verify_signature(body, header, secret):
    parts = [item.strip().partition("=") for item in (header or "").split(",")]
    timestamps = [value for key, _, value in parts if key == "t"]
    if len(timestamps) == 1 and re.fullmatch(r"[0-9]{1,12}", timestamps[0]):
        timestamp = timestamps[0]
        if abs(time.time() - int(timestamp)) <= 300:
            expected = hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
            if any(key == "v0" and re.fullmatch(r"[a-f0-9]{64}", value)
                   and hmac.compare_digest(expected, value) for key, _, value in parts):
                return
    raise RequestError(401, "Invalid webhook signature.")


def fields_from_analysis(analysis):
    # Recent agents can return a list with opaque item IDs and human-configured field names.
    values = {}
    results = analysis.get("data_collection_results") or {}
    items = list(results.items()) if isinstance(results, dict) else []
    listed = analysis.get("data_collection_results_list")
    if isinstance(listed, list):
        items.extend((None, item) for item in listed)
    for key, item in items:
        if isinstance(item, dict):
            for name in (key, item.get("name"), item.get("data_collection_id")):
                if isinstance(name, str):
                    values[name] = item.get("value")
    return values


def claim_from_event(event, agent_id, demo_phone):
    if not isinstance(event, dict) or event.get("type") != "post_call_transcription":
        return None
    data = event.get("data")
    if not isinstance(data, dict) or data.get("agent_id") != agent_id or data.get("status") != "done":
        return None
    metadata, analysis = data.get("metadata"), data.get("analysis")
    if not isinstance(metadata, dict) or not isinstance(analysis, dict):
        return None
    if metadata.get("conversation_initiation_source") not in ("widget", "js_sdk", "react_sdk"):
        return None
    text_only = metadata.get("text_only")
    if text_only is not False and (text_only is not None or data.get("has_user_audio") is not True):
        return None
    if any(metadata.get(k) is not None for k in ("phone_call", "batch_call", "whatsapp", "sms")):
        return None
    conversation = data.get("conversation_id")
    if not isinstance(conversation, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,150}", conversation):
        return None
    fields = fields_from_analysis(analysis)
    if fields.get("confirmed") is not True:
        return None
    payload = {key: fields.get(key) for key in ("description", "incident_date", "location",
                                                "policy_number", "email", "injury_status")}
    try:
        payload = validate_intake(dict(payload, request_id=str(uuid4()), documents=[]))
    except RequestError:
        LOG.warning("Confirmed phone intake lacked valid claim fields. Check agent data collection.")
        return None
    phone = demo_phone if fields.get("demo_sms_consent") is True else None
    return conversation, payload, phone


class SMSRejected(Exception):
    def __init__(self, status):
        super().__init__(f"SMS provider returned HTTP {status}")
        self.status = status


def vonage_sender(api_key, api_secret, sender):
    sender = sender.removeprefix("+") if PHONE.fullmatch(sender) else sender
    if not (re.fullmatch(r"[1-9][0-9]{0,14}", sender)
            or re.fullmatch(r"(?=[A-Za-z0-9]*[A-Za-z])[A-Za-z0-9]{1,11}", sender)):
        raise ValueError("Set VONAGE_SMS_FROM to an allowed international number or alphanumeric sender ID.")
    authorization = "Basic " + base64.b64encode(f"{api_key}:{api_secret}".encode()).decode()
    tls = ssl.create_default_context()
    if (sys.platform == "darwin" and not tls.get_ca_certs() and os.path.isfile("/etc/ssl/cert.pem")
            and not (os.environ.get("SSL_CERT_FILE") or os.environ.get("SSL_CERT_DIR"))):
        tls.load_verify_locations(cafile="/etc/ssl/cert.pem")

    def send(phone, message):
        connection = http.client.HTTPSConnection("api.nexmo.com", timeout=10, context=tls)
        try:
            connection.request("POST", "/v1/messages",
                               body=json.dumps({"channel": "sms", "message_type": "text", "from": sender,
                                                "to": phone.removeprefix("+"), "text": message}),
                               headers={"Authorization": authorization,
                                        "Content-Type": "application/json", "Accept": "application/json"})
            response = connection.getresponse()
            if response.status != 202:
                raise SMSRejected(response.status)
            result = json.loads(response.read(16384))
            if not isinstance(result, dict) or not isinstance(result.get("message_uuid"), str):
                raise ValueError("Unconfirmed SMS acceptance.")
            return str(UUID(result["message_uuid"]))
        finally:
            connection.close()
    return send


class VoiceIntake:
    def __init__(self, queue, agent, secret, origin, open_store, send, demo_phone):
        if not PHONE.fullmatch(demo_phone):
            raise ValueError("Set VOICE_DEMO_PHONE to the verified team mobile in +countrycode format.")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,150}", agent):
            raise ValueError("Set a valid ELEVENLABS_AGENT_ID.")
        self.demo_phone = demo_phone
        self.queue, self.agent, self.secret = queue, agent, secret
        self.origin, self.open_store, self.send = public_origin(origin), open_store, send
        queue.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.close(os.open(queue, os.O_CREAT | os.O_WRONLY, 0o600))
        if queue.stat().st_mode & 0o077:
            raise ValueError("VOICE_QUEUE_PATH must be a private file (mode 0600).")
        with closing(self.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("""CREATE TABLE IF NOT EXISTS voice_claims (
                conversation TEXT PRIMARY KEY, payload TEXT, token TEXT, phone TEXT,
                state TEXT NOT NULL DEFAULT 'queued', due INTEGER NOT NULL DEFAULT 0,
                attempts INTEGER NOT NULL DEFAULT 0, reference TEXT, sms_sid TEXT, sms_provider TEXT)""")
            if "sms_provider" not in {col["name"] for col in db.execute("PRAGMA table_info(voice_claims)")}:
                db.execute("ALTER TABLE voice_claims ADD COLUMN sms_provider TEXT")

    def connect(self):
        db = sqlite3.connect(self.queue)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA secure_delete=ON")
        return db

    def receive(self, body, signature):
        verify_signature(body, signature, self.secret)
        try:
            event = json.loads(body)
        except (ValueError, UnicodeError, RecursionError):
            raise RequestError(400, "Malformed webhook JSON.") from None
        claim = claim_from_event(event, self.agent, self.demo_phone)
        if claim:
            conversation, payload, phone = claim
            with closing(self.connect()) as db, db:
                db.execute("""INSERT INTO voice_claims(conversation, payload, token, phone, sms_provider)
                            VALUES(?,?,?,?,'vonage') ON CONFLICT(conversation) DO NOTHING""",
                           (conversation, json.dumps(payload), secrets.token_hex(32), phone))
        return {"received": True}

    def work_one(self):
        now = int(time.time())
        with closing(self.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("""SELECT * FROM voice_claims WHERE state='queued' AND due<=?
                                ORDER BY due, rowid LIMIT 1""", (now,)).fetchone()
            if row is None:
                return False
            # A restart can safely retry filing with the original request ID and private token.
            attempt = row["attempts"] + 1
            db.execute("UPDATE voice_claims SET due=?, attempts=? WHERE conversation=?",
                       (now + 120, attempt, row["conversation"]))
        key = (row["conversation"], attempt)

        def transition(state, *, reference=None, sid=None, retry=False):
            done = state in ("accepted", "filed")
            with closing(self.connect()) as db, db:
                changed = db.execute("""UPDATE voice_claims SET state=?, due=?, reference=coalesce(?,reference),
                        sms_sid=?, payload=CASE WHEN ? THEN NULL ELSE payload END,
                        phone=CASE WHEN ? THEN NULL ELSE phone END, token=CASE WHEN ? THEN NULL ELSE token END
                        WHERE conversation=? AND attempts=?""",
                        (state, int(time.time()) + (min(1800, 5 * 2 ** min(attempt, 9)) if retry else 0),
                         reference, sid, done, done, done, *key))
                return changed.rowcount == 1

        try:
            with self.open_store() as store:
                receipt = submit_linked(store, row["token"], json.loads(row["payload"]))
        except (RequestError, sqlite3.Error) as error:
            if isinstance(error, RequestError) and error.status < 500:
                transition("review_claim")
                LOG.error("Phone claim needs review in the private voice queue.")
            else:
                transition("queued", retry=True)
                LOG.warning("Claim store unavailable. Phone claim queued for retry.")
            return True
        ref = receipt["reference"]
        missing = receipt["missing_documents"]
        # Legacy callers consented to receiving texts on their own phone, never the team's handset.
        if row["sms_provider"] != "vonage" or row["phone"] != self.demo_phone or not missing:
            transition("filed", reference=ref)
            return True
        kinds = " and ".join(LABELS.get(kind, kind.replace("_", " ")) for kind in missing)
        message = (f"Policy Replay received claim {ref}. Upload your {kinds}: "
                   f"{self.origin}/chat#claim={row['token']} Keep this link private.")
        # Commit before contacting the carrier. A crash or timeout must not trigger a second SMS.
        if not transition("sending", reference=ref):
            return True
        try:
            sid = self.send(row["phone"], message)
        except SMSRejected as error:
            if error.status == 429:
                transition("queued", retry=True)
            else:
                transition("review_sms")
            LOG.warning("Claim SMS provider returned HTTP %d.", error.status)
        except (OSError, http.client.HTTPException, ValueError):
            transition("review_sms")
            LOG.warning("Claim SMS acceptance is unknown. Check the provider before retrying.")
        else:
            transition("accepted", sid=sid)
        return True

    def start(self):
        stopped = threading.Event()

        def run():
            while not stopped.is_set():
                try:
                    if self.work_one():
                        continue
                except Exception:
                    # Log no message bodies, tokens or claim details in the background worker.
                    LOG.error("Phone claim queue encountered an internal error.")
                stopped.wait(1)

        threading.Thread(target=run, name="phone-claims", daemon=True).start()
        return stopped


def configured_voice(open_store, default_queue):
    if not os.getenv("ELEVENLABS_AGENT_ID"):
        return None
    values = {key: os.getenv(key, "").strip() for key in SETTINGS - {"VOICE_QUEUE_PATH"}}
    values["VONAGE_API_KEY"] = values["VONAGE_API_KEY"] or os.getenv("Vonage_API_Key", "").strip()
    missing = sorted(key for key, value in values.items() if not value)
    if missing:
        raise ValueError("Missing phone claim settings: " + ", ".join(missing))
    send = vonage_sender(values["VONAGE_API_KEY"], values["VONAGE_API_SECRET"], values["VONAGE_SMS_FROM"])
    return VoiceIntake(Path(os.getenv("VOICE_QUEUE_PATH") or default_queue),
                       values["ELEVENLABS_AGENT_ID"], values["ELEVENLABS_WEBHOOK_SECRET"],
                       values["CLAIM_PUBLIC_ORIGIN"], open_store, send, values["VOICE_DEMO_PHONE"])
