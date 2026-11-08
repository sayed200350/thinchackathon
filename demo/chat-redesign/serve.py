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
STATIC = {"/retakt.css": "text/css; charset=utf-8", "/mobile.html": "text/html; charset=utf-8", "/index.html": "text/html; charset=utf-8"}
HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailers", "transfer-encoding", "upgrade", "content-length", "host"}

ROOT = HERE.parent.parent
FIELDS = ("description", "incident_date", "location", "policy_number", "email", "injury_status")
CHAT_SYSTEM = """You are Retakt's claim intake assistant for motor insurance, chatting with a policyholder who reports a new claim.
Collect exactly these six facts, conversationally, one or two questions at a time, short friendly sentences, always in English (even if the user writes another language):
- description: what happened and what part of the vehicle was damaged (e.g. "rear bumper dented while parked"); if the user only says something vague like "my car got hit", ask what was damaged and how before you record it
- incident_date: the day it happened, as YYYY-MM-DD, never in the future (today is {today})
- location: where it happened (street, town or landmark)
- policy_number: the policy reference from their insurance documents
- email: a contact email for claim updates
- injury_status: yes, no or unknown (was anyone injured?)
Rules: Never invent facts. Fill a field only from what the user actually said; keep already known values unless the user corrects them.
Resolve relative dates ("yesterday") using today's date. Ask for what is still missing. If an answer is unclear, ask again.
Write plain text only: no Markdown, no asterisks, no bullet symbols; put each summary item on its own line as "Label: value".
Once all six are known, summarize them briefly and tell the user the next step is attaching documents (incident report and itemized repair quote are needed; a damage photo is optional). Do not ask for documents in the chat itself.
Always call the tool update_claim with your reply and every field you know so far (omit unknown fields).
Known so far: {known}"""
TOOL = {"name": "update_claim", "description": "Reply to the user and record the facts known so far.",
        "input_schema": {"type": "object", "required": ["reply"], "properties": {
            "reply": {"type": "string"},
            **{k: {"type": "string"} for k in FIELDS}}}}

def dotenv():
    env = {}
    try:
        for line in (ROOT / ".env").read_text().splitlines():
            m = re.match(r"\s*([A-Z_]+)\s*=\s*(.*?)\s*$", line)
            if m: env[m[1]] = m[2].strip("'\"")
    except OSError:
        pass
    return {**env, **{k: v for k, v in os.environ.items() if k.startswith("AI_")}}

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
    env = dotenv(); key = env.get("AI_API_KEY")
    if env.get("AI_PROVIDER") != "anthropic" or not key:
        return 503, {"error": "The AI assistant is not configured (AI_PROVIDER=anthropic and AI_API_KEY in .env)."}
    msgs = [{"role": m["role"], "content": m["content"].strip()[:2000]} for m in (payload.get("messages") or [])[-30:]
            if isinstance(m, dict) and m.get("role") in ("user", "assistant") and isinstance(m.get("content"), str) and m["content"].strip()]
    if not msgs or msgs[-1]["role"] != "user":
        return 400, {"error": "Send a message first."}
    today = datetime.datetime.now(ZoneInfo("Europe/Berlin")).date().isoformat()
    known = clean_values(payload.get("values") or {}, today)
    body = {"model": env.get("AI_MODEL") or "claude-opus-5-5", "max_tokens": 600,
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

    def handle_any(self):
        target = urlsplit(self.path)
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
            if self.judge_backend and local[0].name == "intake.html":
                data = data.replace(b'<body data-voice-agent=', b'<body data-judge-room="enabled" data-voice-agent=', 1)
            self.send_response(200)
            self.send_header("Content-Type", local[1]); self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store"); self.end_headers(); self.wfile.write(data)
            return
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else None
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
    ap.add_argument("--judge-port", type=int, help="port of the separate local judge room")
    ap.add_argument("--intake-backend", default="http://127.0.0.1:8766",
                    help="backend that stores new claim reports (SQLite, its staff inbox feeds the reviewer app); 'none' = main backend")
    a = ap.parse_args(); u = urlsplit(a.backend); Handler.backend = (u.hostname, u.port or 80)
    if a.judge_port:
        Handler.judge_backend = ("127.0.0.1", a.judge_port)
    if a.intake_backend == "none": Handler.intake_backend = None
    else: iu = urlsplit(a.intake_backend); Handler.intake_backend = (iu.hostname, iu.port or 80)
    print(f"Retakt preview on http://127.0.0.1:{a.port}  ->  backend {a.backend}")
    ThreadingHTTPServer(("127.0.0.1", a.port), Handler).serve_forever()
