"""Loopback-only read-only HTTP adapter; reads a sanitized collector snapshot.

Routes: `/` serves the packaged React observatory (falls back to the legacy page while no build
output is packaged), `/legacy` the previous static page, `/assets/<file>` fixed packaged assets by
exact name with a strict MIME allow-list, `/api/status` the snapshot, `/health` liveness,
`/ready` current observation freshness (monitor-readiness-001).
"""
import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files

from codex_harness.adapters.monitoring_readiness import readiness

ASSET_NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}')
ASSET_TYPES = {'.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8',
               '.svg': 'image/svg+xml', '.woff2': 'font/woff2', '.woff': 'font/woff'}
MAX_ASSET_BYTES = 5_000_000
CSP = ("default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
       "connect-src 'self'; img-src 'self' data:; font-src 'self'; frame-ancestors 'none'")


def resource(*parts):
    return files('codex_harness.resources').joinpath(*parts)


def asset(name):
    """Bytes and MIME of one packaged asset, or None: exact file names only, no directories."""
    if '..' in name or not ASSET_NAME.fullmatch(name):
        return None
    suffix = name[name.rfind('.'):] if '.' in name else ''
    content_type = ASSET_TYPES.get(suffix)
    if content_type is None:
        return None
    target = resource('observatory', 'assets', name)
    try:
        if not target.is_file():
            return None
        body = target.read_bytes()
    except OSError:
        return None
    if len(body) > MAX_ASSET_BYTES:
        return None
    return body, content_type


def index_page():
    """Packaged observatory index when built; otherwise the legacy page, never a placeholder."""
    target = resource('observatory', 'index.html')
    try:
        if target.is_file():
            return target.read_bytes()
    except OSError:
        pass
    return resource('monitor.html').read_bytes()


def handler(snapshot_path):
    class Handler(BaseHTTPRequestHandler):
        def respond(self, status, body, content_type):
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', CSP)
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            authority = self.headers.get('Host', '')
            if authority not in {f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'}:
                self.respond(403, b'Forbidden host', 'text/plain')
                return
            path = self.path.split('?', 1)[0]
            if path == '/':
                self.respond(200, index_page(), 'text/html; charset=utf-8')
            elif path == '/legacy':
                self.respond(200, resource('monitor.html').read_bytes(), 'text/html; charset=utf-8')
            elif path.startswith('/assets/'):
                found = asset(path[len('/assets/'):])
                if found is None:
                    self.respond(404, b'Not found', 'text/plain')
                else:
                    self.respond(200, found[0], found[1])
            elif path == '/api/status':
                try:
                    body = snapshot_path.read_bytes()
                    if len(body) > 5_000_000:
                        raise ValueError('Snapshot too large')
                    json.loads(body)
                    self.respond(200, body, 'application/json; charset=utf-8')
                except (OSError, ValueError):
                    self.respond(503, b'{"error":"snapshot_unavailable"}', 'application/json')
            elif path == '/health':
                self.respond(200, b'{"service":"harness-monitor"}', 'application/json')
            elif path == '/ready':
                # Liveness above stays 200 without reading the snapshot; readiness answers only
                # whether the observation delivered right now is fresh (monitor-readiness-001).
                # The assessment is total and carries fixed codes only, so it needs no sanitizing.
                report = readiness(snapshot_path)
                body = json.dumps(report).encode('utf-8')
                self.respond(200 if report['ready'] else 503, body, 'application/json; charset=utf-8')
            else:
                self.respond(404, b'Not found', 'text/plain')

        def do_POST(self):
            self.respond(405, b'Read only', 'text/plain')

        def log_message(self, *args):
            pass
    return Handler


def serve(snapshot_path, port=8787):
    ThreadingHTTPServer(('127.0.0.1', port), handler(snapshot_path)).serve_forever()
