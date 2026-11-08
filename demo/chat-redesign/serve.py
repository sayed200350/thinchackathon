"""Lokaler Vorschau-Server fuer das Retakt-Redesign.

Liefert die neu gestalteten Seiten unter denselben Adressen wie das Backend aus
(/, /chat, /reviewer, /reviewer/evidence, /garage) und leitet alles andere unveraendert an
das Backend weiter (Standard 127.0.0.1:8765). Die Originale in backend/ bleiben unberuehrt;
die Seiten sind 1:1 Ersatz (gleiche relative URLs, gleiche Origin, kein CORS noetig).
Start: python3 demo/chat-redesign/serve.py [--port 8090] [--backend http://127.0.0.1:8765]
"""
import argparse, http.client, sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

HERE = Path(__file__).resolve().parent
PAGES = {  # Pfad -> Datei im Redesign-Ordner (nur wenn die Datei existiert, sonst Backend-Original)
    "/": "intake.html", "/chat": "intake.html",
    "/app": "app.html", "/reviewer": "index.html", "/reviewer/evidence": "evidence.html", "/garage": "garage.html",
}
STATIC = {"/retakt.css": "text/css; charset=utf-8", "/mobile.html": "text/html; charset=utf-8", "/index.html": "text/html; charset=utf-8"}
HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailers", "transfer-encoding", "upgrade", "content-length", "host"}

class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    backend = ("127.0.0.1", 8765)

    judge_backend = None

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
    a = ap.parse_args(); u = urlsplit(a.backend); Handler.backend = (u.hostname, u.port or 80)
    if a.judge_port:
        Handler.judge_backend = ("127.0.0.1", a.judge_port)
    print(f"Retakt preview on http://127.0.0.1:{a.port}  ->  backend {a.backend}")
    ThreadingHTTPServer(("127.0.0.1", a.port), Handler).serve_forever()
