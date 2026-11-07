"""A garage share can be scanned offline and reaches only the garage endpoints."""

import base64
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
import json
import os
from pathlib import Path
import secrets
from threading import Event, Thread
import unittest
from urllib.parse import parse_qs, urlsplit

from backend.garage_public import create_server, make_share_details, public_share_origin
from backend.store import RequestError

try:
    import qrcode
    import zxingcpp
    from PIL import Image
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None


class ShareQRTests(unittest.TestCase):
    def test_an_origin_must_be_reachable_by_the_phone(self):
        for origin in (
            '',
            None,
            'http://localhost:8770',
            'http://127.0.0.1',
            'https://[::1]',
            'https://0.0.0.0',
            'http://garage.example.org',
            'https://u:p@garage.example.org',
            'https://garage.example.org/claims',
            'https://garage.example.org?a=b',
            'https://garage.example.org/#a',
            'https://127.1',
            'https://2130706433',
            'https://garage.example.org:0',
            'https://[fd00::1]typo:8770',
        ):
            with self.subTest(origin=origin), self.assertRaisesRegex(RequestError, 'garage') as failure:
                public_share_origin(origin)
            self.assertEqual(failure.exception.status, 503)
        for origin in ('https://garage.example.org', 'http://192.168.1.5:8770', 'http://laptop.local:8770'):
            self.assertEqual(public_share_origin(origin + '/'), origin)

    @unittest.skipUnless(
        sync_playwright, 'Install garage dependencies, Playwright/Chromium, Pillow and zxing-cpp.'
    )
    def test_a_separate_scanner_reads_the_rendered_svg_at_phone_and_stage_sizes(self):
        # A nonrepeating, padded URL-safe value has the same density as an encrypted capability.
        token = base64.urlsafe_b64encode(secrets.token_bytes(176)).decode()
        expiry = '2040-11-07T19:00:00Z'
        result = make_share_details('https://garage.example.org', token, expiry)
        self.assertEqual(set(result), {'url', 'qr_svg', 'expires_at'})
        self.assertEqual(result['expires_at'], expiry)
        url = urlsplit(result['url'])
        self.assertEqual((url.path, url.query), ('/garage', ''))
        self.assertEqual(parse_qs(url.fragment), {'upload': [token]})
        with sync_playwright() as driver:
            browser = driver.chromium.launch(executable_path=os.getenv('CLAIM_TEST_BROWSER'))
            page = browser.new_page()
            requests = []
            page.on('request', lambda request: requests.append(request.url))
            page.set_content(result['qr_svg'])
            for size in (280, 480):
                with self.subTest(size=size):
                    image = page.locator('svg')
                    image.evaluate("(svg, size) => {svg.style.width = svg.style.height = size + 'px'}", size)
                    png = Image.open(BytesIO(image.screenshot()))
                    decoded = zxingcpp.read_barcodes(png)
                    self.assertEqual([code.text for code in decoded], [result['url']])
            self.assertEqual(requests, [])
            browser.close()


@contextmanager
def serve(server):
    with server:
        thread = Thread(target=server.serve_forever, kwargs={'poll_interval': 0.02}, daemon=True)
        thread.start()
        try:
            yield server
        finally:
            server.shutdown()
            thread.join(timeout=3)


class Upstream(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self):
        data = self.rfile.read(int(self.headers.get('Content-Length', '0')))
        self.server.seen.append((self.command, self.path, dict(self.headers), data))
        self.server.arrived.set()
        self.server.proceed.wait(timeout=4)
        body = self.server.body
        self.send_response(self.server.status)
        self.send_header('Content-Type', 'application/json' if self.command == 'POST' else 'text/html')
        self.send_header('Set-Cookie', 'private=1')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Location', '/reviewer')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass  # An over-limit upstream response is rejected immediately.

    do_GET = do_POST = reply


class GarageGatewayTests(unittest.TestCase):
    def setUp(self):
        self.up = ThreadingHTTPServer(('127.0.0.1', 0), Upstream)
        self.up.body, self.up.status, self.up.seen = b'{}', 200, []
        self.up.arrived, self.up.proceed = Event(), Event()
        self.up.proceed.set()
        self.addCleanup(self.up.proceed.set)
        self.start(self.up)
        self.upstream = 'http://127.0.0.1:' + str(self.up.server_port)
        self.proxy = create_server('127.0.0.1', 0, self.upstream)
        self.start(self.proxy)

    def start(self, server):
        ctx = serve(server)
        ctx.__enter__()
        self.addCleanup(ctx.__exit__, None, None, None)

    def request(self, method, path, data=None, headers=None):
        with closing(HTTPConnection('127.0.0.1', self.proxy.server_port, timeout=4)) as conn:
            conn.request(method, path, body=data, headers=headers or {})
            response = conn.getresponse()
            return response.status, response.headers, response.read()

    def test_route_and_header_allowlists_and_no_caching(self):
        for method, path in (
            ('GET', '/garage'),
            ('GET', '/examples/quotes/itemized-890.pdf'),
            ('GET', '/examples/quotes/itemized-1800.pdf'),
            ('POST', '/api/garage/status'),
            ('POST', '/api/garage/upload'),
        ):
            with self.subTest(path=path):
                headers = {
                    'Cookie': 'session=private',
                    'Authorization': 'Bearer private',
                    'X-Forwarded-For': 'example',
                }
                body = None
                if method == 'POST':
                    headers['Content-Type'] = 'application/json'
                    body = b'{"token":"example"}'
                    self.up.body = b'{"status":"received"}'
                else:
                    self.up.body = b'{}'
                code, received, content = self.request(method, path, body, headers)
                self.assertEqual((code, json.loads(content)), (200, json.loads(self.up.body)))
                self.assertEqual(received.get('Cache-Control'), 'no-store')
                self.assertEqual(received.get('Referrer-Policy'), 'no-referrer')
                self.assertIsNone(received.get('Access-Control-Allow-Origin'))
                self.assertIsNone(received.get('Set-Cookie'))
                self.assertIsNone(received.get('Location'))
                command, route, forwarded, raw = self.up.seen[-1]
                self.assertEqual((command, route, raw), (method, path, body or b''))
                self.assertFalse(
                    {'authorization', 'cookie', 'x-forwarded-for'} & {key.lower() for key in forwarded}
                )
        for method, path in (
            ('GET', '/'),
            ('GET', '/reviewer'),
            ('POST', '/api/intakes/resume'),
            ('POST', '/api/evidence/document'),
            ('GET', '/garage?upload=example'),
            ('GET', '/examples/quotes/total-only-890.pdf'),
            ('GET', '/api/garage/upload'),
            ('OPTIONS', '/api/garage/upload'),
            ('POST', '/garage'),
            ('HEAD', '/garage'),
        ):
            with self.subTest(method=method, path=path):
                status, headers, body = self.request(method, path)
                self.assertIn(status, (404, 405))
                self.assertIsNone(headers.get('Access-Control-Allow-Origin'))
                self.assertNotIn(b'upload=example', body)
        self.assertEqual(len(self.up.seen), 5)

    def test_upload_limits_and_cross_site_posts_are_rejected_before_upstream(self):
        for route, size in (('status', 8193), ('upload', 3 * 1024 * 1024 + 1)):
            code, _, _ = self.request(
                'POST',
                '/api/garage/' + route,
                headers={'Content-Type': 'application/json', 'Content-Length': str(size)},
            )
            self.assertEqual(code, 413)
        code, _, _ = self.request('POST', '/api/garage/upload', b'{}', {'Content-Type': 'text/plain'})
        self.assertEqual(code, 415)
        code, _, _ = self.request(
            'POST',
            '/api/garage/upload',
            b'{}',
            {'Content-Type': 'application/json', 'Sec-Fetch-Site': 'cross-site'},
        )
        self.assertEqual(code, 403)
        self.assertFalse(self.up.seen)

    def test_slow_request_does_not_queue_unbounded_workers(self):
        self.proxy = create_server('127.0.0.1', 0, self.upstream, max_workers=1)
        self.start(self.proxy)
        self.up.proceed.clear()
        with ThreadPoolExecutor(max_workers=1) as pool:
            active = pool.submit(self.request, 'GET', '/garage')
            try:
                self.assertTrue(self.up.arrived.wait(3))
                code, _, _ = self.request('GET', '/garage')
                self.assertEqual(code, 503)
            finally:
                self.up.proceed.set()
            self.assertEqual(active.result(timeout=3)[0], 200)
        with self.proxy.workers:
            pass  # The completed connection's worker has returned to the pool.
        self.assertEqual(self.request('GET', '/garage')[0], 200)

    def test_phone_can_send_full_size_pdf_and_receives_only_garage_status(self):
        sample = Path(__file__).resolve().parents[1] / 'fixtures/quotes/itemized-890.pdf'
        # PDF permits whitespace before its final EOF marker without moving its
        # cross-reference table. This creates an actual, exactly 2 MiB quote.
        head, marker, tail = sample.read_bytes().rpartition(b'%%EOF')
        self.assertTrue(marker)
        pdf = head + b' ' * (2 * 1024 * 1024 - sample.stat().st_size) + marker + tail
        packet = {
            'token': 'example',
            'document': {
                'name': 'itemized.pdf',
                'kind': 'itemized_quote',
                'content_base64': base64.b64encode(pdf).decode(),
            },
        }
        body = json.dumps(packet).encode()
        self.assertGreater(len(body), 2 * 1024 * 1024)
        self.up.body = b'{"status":"received","reference":"private"}'
        code, _, content = self.request(
            'POST',
            '/api/garage/upload',
            body,
            {'Content-Type': 'application/json; charset=utf-8', 'Cookie': 'session=private'},
        )
        self.assertEqual((code, json.loads(content)), (200, {'status': 'received'}))
        _, _, headers, uploaded = self.up.seen[-1]
        self.assertEqual(headers['Content-Type'], 'application/json')
        self.assertEqual(headers['Content-Length'], str(len(body)))
        self.assertNotIn('Cookie', headers)
        self.assertEqual(
            base64.b64decode(json.loads(uploaded)['document']['content_base64'], validate=True), pdf
        )
        self.up.body = b'{"status":"open","demo":true,"reference":"private"}'
        code, _, content = self.request(
            'POST', '/api/garage/status', b'{"token":"example"}', {'Content-Type': 'application/json'}
        )
        self.assertEqual((code, json.loads(content)), (200, {'status': 'open', 'demo': True}))
        self.up.status = 403
        self.up.body = b'{"error":"private diagnostic"}'
        code, _, content = self.request(
            'POST', '/api/garage/status', b'{}', {'Content-Type': 'application/json'}
        )
        self.assertEqual(code, 403)
        self.assertNotIn(b'private', content)

    def test_no_remote_upstreams_redirects_or_unbounded_responses(self):
        for upstream in (
            'https://garage.example.org',
            'http://192.168.1.3:8766',
            'http://127.0.0.1:8766/foo',
        ):
            with self.subTest(upstream=upstream), self.assertRaises(ValueError):
                create_server('127.0.0.1', 0, upstream)
        self.up.status = 302
        self.assertEqual(self.request('GET', '/garage')[0], 502)
        self.up.status = 200
        self.up.body = b'x' * (1024 * 1024 + 1)
        self.assertEqual(self.request('GET', '/garage')[0], 502)
