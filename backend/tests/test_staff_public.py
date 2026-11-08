"""HTTP tests for the four routes exposed to the insurer's trusted server."""

from contextlib import closing
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import unittest
from unittest.mock import patch

from backend import staff_public
from backend.tests.test_garage_public import serve


class TestBackend(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        data = self.rfile.read(int(self.headers.get('Content-Length', '0')))
        self.server.seen.append((self.path, self.headers, data))
        if json.loads(data).get('reviewer_key') != 'authorized-staff':
            status, body = 403, b'{"error":"private upstream diagnostic"}'
        else:
            status, body = self.server.result
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Set-Cookie', 'private=1')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(body)


class StaffPublicTests(unittest.TestCase):
    def setUp(self):
        self.backend = ThreadingHTTPServer(('127.0.0.1', 0), TestBackend)
        self.backend.result = (200, b'{"claims":[],"next_cursor":null}')
        self.backend.seen = []
        self.enter_server(self.backend)
        self.gateway = staff_public.create_server(0, 'http://127.0.0.1:' + str(self.backend.server_port))
        self.enter_server(self.gateway)
        self.authorized = b'{"reviewer_key":"authorized-staff"}'

    def enter_server(self, server):
        context = serve(server)
        context.__enter__()
        self.addCleanup(context.__exit__, None, None, None)

    def call(self, method, path, data=None, headers=None):
        with closing(HTTPConnection('127.0.0.1', self.gateway.server_port, timeout=3)) as conn:
            conn.request(method, path, body=data, headers={'Content-Type': 'application/json', **(headers or {})})
            res = conn.getresponse()
            return res.status, res.headers, res.read()

    def test_forward_staff_json_only_and_no_cache_cookies_or_cors(self):
        for path, status, payload in (
            ('/api/staff/inbox', 200, b'{"claims":[],"next_cursor":null}'),
            ('/api/staff/corrections', 201, b'{"revision":3}'),
            ('/api/evidence/reviewer', 200, b'{"reference":"synthetic"}'),
            ('/api/evidence/document', 200, b'{"name":"report.png","content_base64":"YWJj"}'),
        ):
            with self.subTest(path=path):
                self.backend.result = (status, payload)
                got, headers, data = self.call('POST', path, self.authorized, {'Cookie':'example=1'})
                self.assertEqual((got, data), (status, payload))
                self.assertEqual(headers['Cache-Control'], 'no-store')
                self.assertNotIn('Set-Cookie', headers)
                self.assertNotIn('Access-Control-Allow-Origin', headers)
                route, forwarded, body = self.backend.seen[-1]
                self.assertEqual((route, body), (path, self.authorized))
                self.assertNotIn('Cookie', forwarded)

    def test_forbidden_methods_routes_browsers_or_ambiguous_bodies_stay_local(self):
        for method, path, data, headers, expected in (
            ('GET', '/api/staff/inbox', None, {}, 405),
            ('OPTIONS', '/api/staff/inbox', None, {}, 405),
            ('POST', '/api/intakes/submit', b'{}', {}, 404),
            ('POST', '/api/voice/post-call', b'{}', {}, 404),
            ('POST', '/api/garage/status', b'{}', {}, 404),
            ('GET', '/reviewer', None, {}, 404),
            ('GET', '/', None, {}, 404),
            ('POST', '/api/staff/inbox?cursor=a', b'{}', {}, 404),
            ('POST', '/api/staff/inbox', b'[]', {}, 400),
            ('POST', '/api/staff/inbox', b'not json', {}, 400),
            ('POST', '/api/staff/inbox', self.authorized, {'Content-Type':'text/plain'}, 415),
            ('POST', '/api/staff/inbox', self.authorized, {'Content-Encoding':'gzip'}, 400),
            ('POST', '/api/staff/inbox', self.authorized, {'Origin':'https://demo.example'}, 403),
            ('POST', '/api/staff/inbox', b'{}', {'Content-Length':str(65537)}, 413),
            ('POST', '/api/staff/inbox', b'{}', {}, 403),
        ):
            with self.subTest(method=method, path=path, expected=expected, headers=headers):
                self.assertEqual(self.call(method, path, data, headers)[0], expected)
        self.assertFalse(self.backend.seen)

    def test_hosted_read_only_gateway_excludes_corrections(self):
        with staff_public.create_server(0, f'http://127.0.0.1:{self.backend.server_port}', read_only=True) as gateway:
            self.assertIn('/api/staff/policy-replay', gateway.staff_routes)
            self.assertNotIn('/api/staff/corrections', gateway.staff_routes)
            with serve(gateway), closing(HTTPConnection('127.0.0.1', gateway.server_port, timeout=3)) as conn:
                conn.request('POST', '/api/staff/corrections', body=self.authorized,
                             headers={'Content-Type':'application/json'})
                self.assertEqual(conn.getresponse().status, 404)
        self.assertFalse(self.backend.seen)

    def test_upstream_rejects_incorrect_credentials_even_for_allowed_routes(self):
        for route in staff_public.ROUTES:
            status, _, body = self.call('POST', route, b'{"reviewer_key":"wrong"}')
            self.assertEqual(status, 403)
            self.assertNotIn(b'private upstream', body)
        self.assertEqual(len(self.backend.seen), len(staff_public.ROUTES))

    def test_document_and_summary_have_bounded_distinct_reply_limits(self):
        self.backend.result = 200, b'{"content_base64":"' + b'A' * 1000 + b'"}'
        with patch.object(staff_public, 'SUMMARY_LIMIT', 500), patch.object(staff_public, 'DOCUMENT_LIMIT', 1200):
            self.assertEqual(self.call('POST', '/api/staff/inbox', self.authorized)[0], 502)
            self.assertEqual(self.call('POST', '/api/evidence/document', self.authorized)[0], 200)
            self.backend.result = 200, b'{"content_base64":"' + b'A' * 1800 + b'"}'
            self.assertEqual(self.call('POST', '/api/evidence/document', self.authorized)[0], 502)
        with self.assertRaises(ValueError):
            staff_public.create_server(0, 'http://10.0.0.3:8766')
