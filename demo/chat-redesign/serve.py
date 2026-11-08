"""Lokaler Vorschau-Server fuer das Retakt-Redesign.

Liefert die neu gestalteten Seiten unter denselben Adressen wie das Backend aus
(/, /chat, /reviewer, /reviewer/evidence, /garage) und leitet alles andere unveraendert an
das Backend weiter (Standard 127.0.0.1:8765). Die Originale in backend/ bleiben unberuehrt;
die Seiten sind 1:1 Ersatz (gleiche relative URLs, gleiche Origin, kein CORS noetig).
Start: python3 demo/chat-redesign/serve.py [--port 8090] [--backend http://127.0.0.1:8765]
"""
import argparse, datetime, http.client, json, os, re, sys, urllib.request
from zoneinfo import ZoneInfo
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

HERE = Path(__file__).resolve().parent
PAGES = {  # Pfad -> Datei im Redesign-Ordner (nur wenn die Datei existiert, sonst Backend-Original)
    "/": "mobile.html", "/chat": "intake.html",  # "/" = the app inside the phone wrapper
    "/app": "app.html", "/reviewer": "index.html", "/reviewer/evidence": "evidence.html", "/garage": "garage.html",
}
STATIC = {"/retakt.css": "text/css; charset=utf-8", "/mobile.html": "text/html; charset=utf-8", "/index.html": "text/html; charset=utf-8",
          "/client.js": "text/javascript; charset=utf-8", "/profile.js": "text/javascript; charset=utf-8", "/rico.svg": "image/svg+xml"}
HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailers", "transfer-encoding", "upgrade", "content-length", "host"}

ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))
from demo_claims import PhoneDemoStore
from backend.store import RequestError
PHONE_DEMO = PhoneDemoStore(ROOT / 'backend/.local/phone-demo.sqlite3')
FIELDS = ("description", "incident_date", "location", "policy_number", "email", "injury_status")
CHAT_SYSTEM = """You are Retakt's friendly claim intake assistant, chatting with a policyholder who reports a new claim.
Collect exactly these six facts, conversationally, one or two questions at a time, short friendly sentences, always in English (even if the user writes another language):
- description: what happened; ask a short clarifying question only when needed
- incident_date: the day it happened, as YYYY-MM-DD, never in the future (today is {today})
- location: where it happened (street, town or landmark)
- policy_number: their insurance number; always call it insurance number in customer-facing replies
- email: a contact email for claim updates
- injury_status: yes, no or unknown (was anyone injured?)
Rules: Never invent facts. Fill a field only from what the user actually said; keep already known values unless the user corrects them.
Resolve relative dates ("yesterday") using today's date. Ask for what is still missing. If an answer is unclear, ask again.
Keep replies kind and brief: usually 5–18 words, one question at a time. Do not recite captured details; they are shown on screen. Accept corrections to known fields. Write plain text only, without Markdown.
Once all six are known, say the upload screen is ready. The current checklist requires an incident report and itemized repair quote before submission; a photo is optional. Missing documents mean Save and continue later, never submit incomplete.
Always call the tool update_claim with your reply and every field you know so far (omit unknown fields).
Known so far: {known}"""
TOOL = {"name": "update_claim", "description": "Reply to the user and record the facts known so far.",
        "input_schema": {"type": "object", "required": ["reply"], "properties": {
            "reply": {"type": "string"},
            **{k: {"type": "string"} for k in FIELDS}}}}

def dotenv():
    env = {}
    try:
        for line in ENV_FILE.read_text().splitlines():
            m = re.match(r"\s*([A-Z_]+)\s*=\s*(.*?)\s*$", line)
            if m: env[m[1]] = m[2].strip("'\"")
    except OSError:
        pass
    return {**env, **{k: v for k, v in os.environ.items() if k.startswith("AI_")}}

ENV_FILE = ROOT / ".env"

def guided_chat(msgs, known, today):
    """Keep claim intake usable without an external model; never invent a missing fact."""
    values = dict(known)
    text = msgs[-1]["content"].strip()
    missing = next((key for key in FIELDS if key not in values), None)
    handled = False
    correction = re.search(r"(?:my\s+)?(?:insurance(?:\s+number)?|policy number)\s*(?:is|should be|:)\s*(.+)", text, re.I)
    if correction:
        values.update(clean_values({"policy_number": correction[1].strip().rstrip(".")}, today)); handled = True
    email = re.search(r"[^\s<>]+@[^\s<>]+\.[^\s<>.,]+", text)
    if email:
        values.update(clean_values({"email": email[0].rstrip(".,;")}, today)); handled = True
    date = re.search(r"\b\d{4}-\d{2}-\d{2}\b", text)
    if date:
        values.update(clean_values({"incident_date": date[0]}, today)); handled = True
    elif missing == "incident_date" and text.lower() in ("today", "yesterday"):
        day = datetime.date.fromisoformat(today) - datetime.timedelta(days=text.lower() == "yesterday")
        values["incident_date"] = day.isoformat(); handled = True
    answer = text.lower().strip(" .!")
    choices = {"no": "no", "no one was injured": "no", "nobody was injured": "no", "no injuries": "no", "yes": "yes", "someone was injured": "yes", "unknown": "unknown", "not sure": "unknown", "i don't know": "unknown"}
    if answer in choices and (missing == "injury_status" or "injury_status" in values):
        values["injury_status"] = choices[answer]; handled = True
    if missing == "description" and not handled:
        values.update(clean_values({"description": text}, today))
    elif missing in ("location", "policy_number") and not handled:
        values.update(clean_values({missing: text}, today))
    prompts = {
        "description": "Could you briefly tell me what happened?",
        "incident_date": "When did it happen? You can use YYYY-MM-DD.",
        "location": "Where did it happen? Tell me the street, town or landmark.",
        "policy_number": "What is your insurance number?",
        "email": "What email address should we use for updates about this claim?",
        "injury_status": "Was anyone injured? Say yes, no, or unknown.",
    }
    missing = next((key for key in FIELDS if key not in values), None)
    reply = prompts[missing] if missing else "Your details are ready. Continue to upload your incident report and itemized repair quote."
    return 200, {"reply": reply, "values": values, "ready": missing is None}

def clean_values(raw, today):
    out = {}
    for k in FIELDS:
        v = raw.get(k)
        if not isinstance(v, str): continue
        v = v.strip()
        ok = {"description": 10 <= len(v) <= 2000, "location": 1 <= len(v) <= 160, "policy_number": 1 <= len(v) <= 80,
              "email": bool(re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", v)) and len(v) <= 254,
              "injury_status": v in ("yes", "no", "unknown"),
              "incident_date": bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", v)) and v <= today}[k]
        if k == "incident_date" and ok:
            try: datetime.date.fromisoformat(v)
            except ValueError: ok = False
        if ok: out[k] = v
    return out

def intake_chat(payload):
    msgs = [{"role": m["role"], "content": m["content"].strip()[:2000]} for m in (payload.get("messages") or [])[-30:]
            if isinstance(m, dict) and m.get("role") in ("user", "assistant") and isinstance(m.get("content"), str) and m["content"].strip()]
    if not msgs or msgs[-1]["role"] != "user":
        return 400, {"error": "Send a message first."}
    today = datetime.datetime.now(ZoneInfo("Europe/Berlin")).date().isoformat()
    known = clean_values(payload.get("values") or {}, today)
    env = dotenv(); key = env.get("AI_API_KEY")
    if env.get("AI_PROVIDER") != "anthropic" or not key:
        return guided_chat(msgs, known, today)
    body = {"model": env.get("AI_MODEL") or "claude-opus-5-5", "max_tokens": 350,
            "system": CHAT_SYSTEM.format(today=today, known=json.dumps(known) if known else "nothing yet"),
            "messages": msgs, "tools": [TOOL]}
    base = (env.get("AI_BASE_URL") or "https://api.anthropic.com/v1").rstrip("/")
    req = urllib.request.Request(base + "/messages", json.dumps(body).encode(), {
        "content-type": "application/json", "x-api-key": key, "anthropic-version": "2023-06-01"})
    try:
        with urllib.request.urlopen(req, timeout=40) as r: data = json.load(r)
    except Exception as e:
        sys.stderr.write("intake-chat AI error: %s\n" % type(e).__name__)
        return 502, {"error": "The AI assistant is not reachable right now."}
    call = next((b.get("input") for b in data.get("content", []) if b.get("type") == "tool_use"), None) or {}
    values = {**known, **clean_values(call, today)}
    text = " ".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text").strip()
    if not call.get("reply") and text: call = {**call, "reply": text}
    reply = call.get("reply") if isinstance(call.get("reply"), str) and call["reply"].strip() else "Could you say that again?"
    return 200, {"reply": reply.strip(), "values": values, "ready": all(k in values for k in FIELDS)}

class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    backend = ("127.0.0.1", 8765)

    judge_backend = None
    # Mobile claim reports (/api/intakes/*) go to a local SQLite backend whose staff inbox the reviewer app reads.
    intake_backend = ("127.0.0.1", 8766)

    def local_file(self):
        path = urlsplit(self.path).path
        if self.command == "GET":
            name = "intake.html" if path == "/judge/chat" and self.judge_backend else PAGES.get(path)
            if name and (HERE / name).is_file():
                return HERE / name, "text/html; charset=utf-8"
            if path in STATIC and (HERE / path[1:]).is_file():
                return HERE / path[1:], STATIC[path]
        return None

    def json_response(self, status, payload):
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(data)

    def handle_any(self):
        target = urlsplit(self.path)
        if self.command == 'GET' and target.path == '/api/phone-demo/claims':
            try:
                return self.json_response(200, PHONE_DEMO.records())
            except (OSError, ValueError, RequestError) as error:
                return self.json_response(503, {'error': 'Could not load the demo claims.'})
        if self.command == 'POST' and target.path.startswith('/api/intakes/'):
            length = int(self.headers.get('Content-Length') or 0)
            if length > 68 * 1024 * 1024:
                return self.json_response(413, {'error': 'The files are too large.'})
            raw = self.rfile.read(length)
            try:
                body = json.loads(raw)
            except ValueError:
                return self.json_response(400, {'error': 'Invalid request.'})
            if isinstance(body, dict) and PHONE_DEMO.handles(body.get('token')):
                try:
                    return self.json_response(200, PHONE_DEMO.action(target.path.rsplit('/', 1)[-1], body))
                except RequestError as error:
                    return self.json_response(error.status, {'error': str(error)})
            # Keep the body for the normal backend proxy; it has already been read once.
            self.forwarded_body = raw
        if (self.judge_backend and self.command == "GET" and target.path == "/chat"
                and parse_qs(target.query).get("demo") == ["DEV-003"]):
            self.send_response(302)
            self.send_header("Location", "/judge/chat")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if self.command == "POST" and target.path == "/api/intake-chat":
            length = int(self.headers.get("Content-Length") or 0)
            try: payload = json.loads(self.rfile.read(min(length, 100000)) or b"{}")
            except ValueError: payload = {}
            status, out = intake_chat(payload if isinstance(payload, dict) else {})
            data = json.dumps(out).encode()
            self.send_response(status); self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data))); self.send_header("Cache-Control", "no-store")
            self.end_headers(); self.wfile.write(data)
            return
        upstream = self.backend
        if target.path.startswith("/judge/") and target.path != "/judge/chat":
            if (not self.judge_backend or self.command != "POST" or
                    target.path not in {"/judge/api/intakes/" + op for op in
                    ("save-draft", "submit", "add-documents", "resume", "garage-link", "import-pdf")}
                    | {"/judge/api/evidence/quote"}):
                self.send_error(404)
                return
            upstream = self.judge_backend
        if self.judge_backend and self.command == "GET" and target.path == "/examples/quotes/itemized-1300.pdf":
            upstream = self.judge_backend
        # Claim reports and the staff inbox that lists them live in the intake backend.
        if self.intake_backend and (target.path.startswith(("/api/intakes/", "/api/staff/"))
                                    or target.path in ("/api/evidence/reviewer", "/api/evidence/document")):
            upstream = self.intake_backend
        local = self.local_file()
        if local:
            data = local[0].read_bytes()
            if local[0].name == "intake.html" and parse_qs(target.query).get("embedded") == ["1"]:
                data = data.replace(b'<body data-voice-agent=', b'<body class="embedded" data-voice-agent=', 1)
            if self.judge_backend and local[0].name == "intake.html":
                data = data.replace(b'<body data-voice-agent=', b'<body data-judge-room="enabled" data-voice-agent=', 1)
            self.send_response(200)
            self.send_header("Content-Type", local[1]); self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store"); self.end_headers(); self.wfile.write(data)
            return
        length = int(self.headers.get("Content-Length") or 0)
        body = self.forwarded_body if hasattr(self, 'forwarded_body') else self.rfile.read(length) if length else None
        if hasattr(self, 'forwarded_body'): del self.forwarded_body
        headers = {k: v for k, v in self.headers.items() if k.lower() not in HOP}
        try:
            conn = http.client.HTTPConnection(*upstream, timeout=30)
            conn.request(self.command, self.path, body=body, headers=headers)
            resp = conn.getresponse(); data = resp.read()
        except OSError:
            data = b'{"error":"Backend not reachable on %s:%d."}' % (upstream[0].encode(), upstream[1])
            self.send_response(502); self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
            return
        self.send_response(resp.status)
        for k, v in resp.getheaders():
            if k.lower() not in HOP: self.send_header(k, v)
        self.send_header("Content-Length", str(len(data))); self.end_headers()
        if self.command != "HEAD": self.wfile.write(data)
        conn.close()

    do_GET = do_POST = do_OPTIONS = do_HEAD = do_PUT = do_DELETE = handle_any
    def log_message(self, fmt, *args): sys.stderr.write("%s %s\n" % (self.command, self.path))

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--port", type=int, default=8090); ap.add_argument("--backend", default="http://127.0.0.1:8765")
    ap.add_argument("--demo-db", type=Path, help="isolated database for the fictional phone claims")
    ap.add_argument("--judge-port", type=int, help="port of the separate local judge room")
    ap.add_argument("--intake-backend", default="http://127.0.0.1:8766",
                    help="backend that stores new claim reports (SQLite, its staff inbox feeds the reviewer app); 'none' = main backend")
    ap.add_argument("--env-file", type=Path, default=ENV_FILE, help="Optional server-side AI settings")
    a = ap.parse_args(); ENV_FILE = a.env_file; u = urlsplit(a.backend); Handler.backend = (u.hostname, u.port or 80)
    if a.demo_db:
        PHONE_DEMO = PhoneDemoStore(a.demo_db)
    if a.judge_port:
        Handler.judge_backend = ("127.0.0.1", a.judge_port)
    if a.intake_backend == "none": Handler.intake_backend = None
    else: iu = urlsplit(a.intake_backend); Handler.intake_backend = (iu.hostname, iu.port or 80)
    print(f"Retakt preview on http://127.0.0.1:{a.port}  ->  backend {a.backend}")
    ThreadingHTTPServer(("127.0.0.1", a.port), Handler).serve_forever()
