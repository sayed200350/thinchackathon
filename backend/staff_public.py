"""Server-to-server demonstration gateway for the insurer's authenticated claim routes."""

import argparse
from http.client import HTTPConnection, HTTPException
import json
import re

from .garage_public import GarageHandler, create_server as create_bounded_server
from .intake import EVIDENCE_FILE_REQUEST_LIMIT


ROUTES = frozenset({
    '/api/staff/inbox', '/api/staff/policy-replay', '/api/staff/corrections', '/api/evidence/reviewer', '/api/evidence/document',
})
REQUEST_LIMIT = 64 * 1024
SUMMARY_LIMIT = 2 * 1024 * 1024
DOCUMENT_LIMIT = EVIDENCE_FILE_REQUEST_LIMIT


class StaffHandler(GarageHandler):
    """Use the gateway's nonlogging JSON responses and exact-path dispatch."""

    def do_GET(self):
        self.error_reply(405 if self.requestline.split()[1] in self.server.staff_routes else 404)

    def do_POST(self):
        path = self.requestline.split()[1]
        if path not in self.server.staff_routes:
            return self.error_reply(404)
        if self.headers.get('Origin') is not None or self.headers.get('Sec-Fetch-Site') is not None:
            return self.error_reply(403)
        if self.headers.get('Transfer-Encoding') or self.headers.get('Content-Encoding'):
            return self.error_reply(400)
        if self.headers.get_content_type() != 'application/json':
            return self.error_reply(415)
        lengths = self.headers.get_all('Content-Length', [])
        if not lengths:
            return self.error_reply(411)
        if len(lengths) != 1 or not re.fullmatch(r'[0-9]{1,10}', lengths[0]):
            return self.error_reply(400)
        size = int(lengths[0])
        if not 0 < size <= REQUEST_LIMIT:
            return self.error_reply(413)
        raw = self.rfile.read(size)
        if len(raw) != size:
            return self.error_reply(400)
        try:
            body = json.loads(raw)
        except (ValueError, RecursionError):
            return self.error_reply(400)
        if not isinstance(body, dict):
            return self.error_reply(400)
        if not isinstance(body.get('reviewer_key'), str) or not body['reviewer_key']:
            return self.error_reply(403)
        # Only the backend validates the secret. Do not source one from the host
        # or attach any client headers, cookies or browser credentials.
        self.forward_staff(path, raw)

    def forward_staff(self, path, raw):
        upstream = HTTPConnection(*self.server.upstream, timeout=15)
        try:
            upstream.request('POST', path, body=raw, headers={'Content-Type': 'application/json'})
            response = upstream.getresponse()
            if 400 <= response.status < 500 or response.status == 503:
                return self.error_reply(response.status)
            limit = DOCUMENT_LIMIT if path == '/api/evidence/document' else SUMMARY_LIMIT
            if response.status not in (200, 201) or response.headers.get_content_type() != 'application/json':
                return self.error_reply(502)
            if response.length is not None and response.length > limit:
                return self.error_reply(502)
            data = response.read(limit + 1)
            if len(data) > limit or (response.length is not None and response.length > 0):
                return self.error_reply(502)
            if not isinstance(json.loads(data), dict):
                return self.error_reply(502)
            self.reply(response.status, data)
        except (OSError, HTTPException, ValueError, RecursionError):
            self.error_reply(502)
        finally:
            upstream.close()


def create_server(port, upstream, *, read_only=False):
    # Reuse loopback validation, bounded connections and connection deadlines.
    server = create_bounded_server('127.0.0.1', port, upstream, max_workers=4)
    server.staff_routes = ROUTES - {'/api/staff/corrections'} if read_only else ROUTES
    server.RequestHandlerClass = StaffHandler
    return server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8774)
    parser.add_argument('--upstream', default='http://127.0.0.1:8766')
    parser.add_argument('--read-only', action='store_true', help='expose only insurer reads and policy previews')
    args = parser.parse_args()
    try:
        with create_server(args.port, args.upstream, read_only=args.read_only) as server:
            print(f'Staff gateway listening on 127.0.0.1:{server.server_port}', flush=True)
            server.serve_forever()
    except KeyboardInterrupt:
        return
    except (ValueError, OSError) as error:
        parser.exit(1, str(error) + '\n')


if __name__ == '__main__':
    main()
