"""Offline QR shares and a narrow HTTP gateway for the garage upload page."""

import argparse
from http.client import HTTPConnection, HTTPException
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from ipaddress import ip_address, ip_network
import json
import re
import socket
from threading import BoundedSemaphore, Timer
from urllib.parse import urlsplit

from .intake import EVIDENCE_FILE_REQUEST_LIMIT
from .store import RequestError


PAGES = {
    '/garage': 'text/html; charset=utf-8',
    '/examples/quotes/itemized-890.pdf': 'application/pdf',
    '/examples/quotes/itemized-1800.pdf': 'application/pdf',
}
POST_LIMITS = {'/api/garage/status': 4 * 1024, '/api/garage/upload': EVIDENCE_FILE_REQUEST_LIMIT}
REPLY_LIMIT = 1024 * 1024
LAN_NETWORKS = tuple(map(ip_network, ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16', 'fc00::/7')))
ORIGIN_HELP = (
    'Set GARAGE_PUBLIC_ORIGIN to a phone-accessible HTTPS garage address or the '
    'garage gateway’s HTTP address on the same private Wi-Fi network.'
)
DNS_LABEL = re.compile(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', re.ASCII)


def _origin_parts(value):
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 320
        or not value.isascii()
        or re.search(r'[\s\x00-\x1f\x7f\\%?#@]', value)
    ):
        raise ValueError('Expected an origin.')
    parts = urlsplit(value)
    if (
        parts.scheme not in ('http', 'https')
        or parts.path not in ('', '/')
        or not parts.hostname
        or parts.port == 0
        or parts.netloc.endswith(':')
    ):
        raise ValueError('Expected an HTTP origin.')
    return parts


def public_share_origin(value):
    """Validate the configured phone destination without reading client headers."""
    try:
        parts = _origin_parts(value)
        host = parts.hostname
        try:
            address = ip_address(host)
        except ValueError:
            labels = host.split('.')
            # Browsers accept numeric shorthand as IPv4. Require an actual DNS name.
            if (
                len(labels) < 2
                or len(host) > 253
                or not all(DNS_LABEL.fullmatch(label) for label in labels)
                or labels[-1] == 'localhost'
                or re.fullmatch(r'(?:[0-9]+|0x[0-9a-f]+)', labels[-1])
            ):
                raise ValueError()
            local = labels[-1] == 'local'
        else:
            address = getattr(address, 'ipv4_mapped', None) or address
            if address.is_loopback or address.is_unspecified or address.is_multicast or address.is_link_local:
                raise ValueError()
            local = any(address in network for network in LAN_NETWORKS)
        if parts.scheme == 'http' and not local:
            raise ValueError()
    except (ValueError, UnicodeError):
        raise RequestError(503, ORIGIN_HELP) from None
    return parts.scheme + '://' + parts.netloc.lower()


def make_share_details(public_origin, token, expires_at):
    origin = public_share_origin(public_origin)
    if not isinstance(token, str) or not re.fullmatch(r'[A-Za-z0-9._-]{1,2048}={0,2}', token):
        raise ValueError('Expected an encoded garage share.')
    try:
        import qrcode
        from qrcode.image.svg import SvgPathFillImage
    except ImportError:
        raise RequestError(
            503, 'Install backend/requirements-garage.txt to enable garage QR codes.'
        ) from None
    url = origin + '/garage#upload=' + token
    code = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_Q, border=4)
    code.add_data(url, optimize=0)
    try:
        image = code.make_image(image_factory=SvgPathFillImage)
    except qrcode.exceptions.DataOverflowError:
        raise ValueError('This garage link is too long for a QR code.') from None
    return {'url': url, 'qr_svg': image.to_string(encoding='unicode'), 'expires_at': expires_at}


class GarageHandler(BaseHTTPRequestHandler):
    """One request per connection; route and headers are selected by the gateway."""

    def log_message(self, *args):
        # Including rejected paths or header diagnostics could record a capability.
        pass

    def send_error(self, code, message=None, explain=None):
        self.error_reply(405 if code == 501 else code)

    def error_reply(self, status):
        message = self.responses.get(status, ('Request failed',))[0]
        self.reply(status, json.dumps({'error': message}).encode())

    def reply(self, status, data, media_type='application/json; charset=utf-8'):
        self.send_response_only(status)
        self.send_header('Content-Type', media_type)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Connection', 'close')
        if media_type.startswith('text/html'):
            self.send_header(
                'Content-Security-Policy',
                "default-src 'none'; script-src 'unsafe-inline'; "
                "style-src 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; "
                "frame-ancestors 'none'; base-uri 'none'; form-action 'none'",
            )
        if media_type == 'application/pdf':
            filename = self.path.rsplit('/', 1)[1]
            self.send_header('Content-Disposition', f'attachment; filename="{filename}"')
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(data)

    def forward(self):
        # BaseHTTPRequestHandler normalizes a leading double slash. Dispatch on
        # the exact request target to keep query strings and alternate paths out.
        path = self.requestline.split()[1]
        permitted = PAGES if self.command == 'GET' else POST_LIMITS
        if path not in permitted:
            self.error_reply(405 if path in PAGES or path in POST_LIMITS else 404)
            return
        if self.headers.get('Transfer-Encoding') or self.headers.get('Content-Encoding'):
            self.error_reply(400)
            return
        lengths = self.headers.get_all('Content-Length', [])
        if len(lengths) > 1 or (lengths and not re.fullmatch(r'[0-9]{1,10}', lengths[0])):
            self.error_reply(400)
            return
        size = int(lengths[0]) if lengths else 0
        data, headers = None, {}
        if self.command == 'POST':
            if self.headers.get('Sec-Fetch-Site') == 'cross-site' or self.headers.get('Origin') == 'null':
                self.error_reply(403)
                return
            if self.headers.get_content_type() != 'application/json':
                self.error_reply(415)
                return
            if not lengths:
                self.error_reply(411)
                return
            if not 0 < size <= POST_LIMITS[path]:
                self.error_reply(413)
                return
            data = self.rfile.read(size)
            if len(data) != size:
                self.error_reply(400)
                return
            headers = {'Content-Type': 'application/json'}
        elif size:
            self.error_reply(400)
            return

        upstream = HTTPConnection(*self.server.upstream, timeout=12)
        try:
            upstream.request(self.command, path, body=data, headers=headers)
            response = upstream.getresponse()
            if 400 <= response.status < 500:
                self.error_reply(response.status)
                return
            if not 200 <= response.status < 300 or (
                response.length is not None and response.length > REPLY_LIMIT
            ):
                self.error_reply(502)
                return
            content = response.read(REPLY_LIMIT + 1)
            if len(content) > REPLY_LIMIT or (response.length is not None and response.length > 0):
                self.error_reply(502)
                return
            if self.command == 'POST':
                try:
                    reply = json.loads(content)
                    stage = reply['status']
                    allowed = ('received',) if path.endswith('/upload') else ('open', 'received', 'closed')
                    if stage not in allowed:
                        raise ValueError()
                    result = {'status': stage}
                    if stage == 'open':
                        result['demo'] = reply.get('demo') is True
                except (KeyError, TypeError, UnicodeError, ValueError, RecursionError):
                    self.error_reply(502)
                    return
                self.reply(response.status, json.dumps(result).encode())
            else:
                self.reply(response.status, content, PAGES[path])
        except (HTTPException, OSError):
            self.error_reply(502)
        finally:
            upstream.close()

    do_GET = do_POST = forward


class GarageServer(ThreadingHTTPServer):
    """Bound memory, threads and lifetime before a public connection can upload."""

    request_queue_size = 16

    def __init__(self, address, upstream, max_workers):
        self.upstream = upstream
        self.workers = BoundedSemaphore(max_workers)
        super().__init__(address, GarageHandler)

    def handle_error(self, request, client_address):
        # A visitor may disconnect while a request is being read or answered.
        pass

    def process_request(self, request, client_address):
        request.settimeout(15)
        if not self.workers.acquire(blocking=False):
            try:
                request.settimeout(0.25)
                request.sendall(
                    b'HTTP/1.0 503 Service Unavailable\r\nContent-Length: 0\r\n'
                    b'Cache-Control: no-store\r\nConnection: close\r\n\r\n'
                )
            except OSError:
                pass
            finally:
                self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.workers.release()
            raise

    def process_request_thread(self, request, client_address):
        # The inactivity timeout alone would let a trickle of bytes monopolize a worker.
        def deadline():
            try:
                request.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

        timer = Timer(60, deadline)
        timer.daemon = True
        timer.start()
        try:
            super().process_request_thread(request, client_address)
        finally:
            timer.cancel()
            self.workers.release()


def create_server(bind, port, upstream, max_workers=8):
    try:
        parts = _origin_parts(upstream)
        host = '127.0.0.1' if parts.hostname == 'localhost' else parts.hostname
        if parts.scheme != 'http' or not ip_address(host).is_loopback:
            raise ValueError()
    except ValueError:
        raise ValueError('Use an HTTP loopback upstream, such as http://127.0.0.1:8766.') from None
    return GarageServer((bind, port), (host, parts.port or 80), max_workers)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bind', default='127.0.0.1', help='listen address (0.0.0.0 for private Wi-Fi)')
    parser.add_argument('--port', type=int, default=8770)
    parser.add_argument('--upstream', default='http://127.0.0.1:8766', help='loopback claim service')
    args = parser.parse_args()
    try:
        with create_server(args.bind, args.port, args.upstream) as server:
            print(f'Garage gateway listening on {args.bind}:{server.server_port}', flush=True)
            server.serve_forever()
    except KeyboardInterrupt:
        return
    except (ValueError, OSError) as error:
        parser.exit(1, str(error) + '\n')


if __name__ == '__main__':
    main()
