"""Loopback-only read-only HTTP adapter; reads a sanitized collector snapshot.

Routes: `/` serves the packaged React observatory (falls back to the legacy page while no build
output is packaged), `/legacy` the previous static page, `/assets/<file>` fixed packaged assets by
exact name with a strict MIME allow-list, `/api/status` the snapshot, `/health` liveness,
`/ready` current observation freshness (monitor-readiness-001).

Layer: adapters
Context: observation
Owns: the loopback-only read-only HTTP viewer (`handler`, `serve`, `resource`, `asset`, `index_page`, `VIEWER_PORT`, `CSP`, the asset allow-list): the routes `/`, `/legacy`, `/assets/<file>`, `/api/status`, `/health`, `/ready`, the exact loopback Host check before routing and the read-only 405; the desk routes only when a desk and the `DeskHttp` port are injected (the viewer-port refusal precedes everything)
Does not own: the desk HTTP routes themselves (`frontdesk_http`, S10 `entry.http.desk`), the CLI that picks web or desk mode (S10 `monitor`), the readiness assessment (`observation.adapters.monitoring_readiness`), the packaged frontend bytes (resources)
Entry points: handler, serve, resource, asset, index_page, VIEWER_PORT, ASSET_NAME, ASSET_TYPES, MAX_ASSET_BYTES, CSP
Contracts: INV-MONITOR-VIEWER-001

Moved from M7 `adapters/monitoring_web.py` (SOURCE e38aa722) through named rules (S9 batch L2-B3, A/evidence/rebuild/s9/l2-b3/transcribe.py, OWNER-DECISIONS-S9 D2.1): R-v0 (imports; `frontdesk_http` is replaced by the injected `observation.ports.DeskHttp`), R-v1 (`handler` takes the keyword-only `desk_http` and refuses a desk without it first; each `frontdesk_http.` becomes `desk_http.`), R-v2 (`serve` forwards it), R-v3 (S11 XC-1 A4: `Handler.timeout = 5`), R-v4 (S11 XC-2b B2: `handler` and `serve` take the keyword-only `observer`, `Handler.respond` begins with `self.refused(status, body)`, before the response is written and `Handler.refused` emits `operations.http_request_refused` through it, `observation.adapters.http_refusal`); every other statement is M7's and in M7's order. With no desk the behaviour is M7's byte for byte and `desk_http` is never read. The first paragraphs are M7's module docstring.
"""
import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files

from codex_harness.kernel.errors import require
from codex_harness.observation.adapters.monitoring_readiness import readiness

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


def handler(snapshot_path, desk=None, *, desk_http=None, observer=None):
    """`desk` is the opt-in local front-door service (local-operations-desk-001, part B).

    Without it this handler is exactly what it was: every GET route below is read-only, unknown
    paths are 404 and every POST is 405. With it, and only with it, the four `/api/desk` routes
    exist; the loopback Host check above still applies to them first.
    """
    require(desk is None or desk_http is not None, "desk_http is not wired")
    class Handler(BaseHTTPRequestHandler):
        # XC-1 A4: a socket timeout for every request, so an idle connection frees its thread. The value is the
        # desk POST read timeout (`entry/http/desk.py:32` READ_TIMEOUT_SECONDS; observation may not import entry).
        timeout = 5

        def respond(self, status, body, content_type):
            self.refused(status, body)
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', CSP)
            self.end_headers()
            self.wfile.write(body)

        def refused(self, status, body):
            """S11 XC-2b B2: a refusal (status >= 400) is one `operations.http_request_refused` through the injected observer."""
            if observer is not None and status >= 400:
                from codex_harness.observation.adapters.http_refusal import emit_refusal
                emit_refusal(observer, self.path, status, body)

        def authority(self):
            """The existing exact loopback authority; every desk route reuses it unchanged."""
            value = self.headers.get('Host', '')
            allowed = {f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'}
            return value if value in allowed else None

        def do_GET(self):
            if self.authority() is None:
                self.respond(403, b'Forbidden host', 'text/plain')
                return
            path = self.path.split('?', 1)[0]
            if desk is not None and (result := desk_http.handle_get(desk, path)) is not None:
                self.respond(result[0], result[1], desk_http.JSON)
            elif path == '/':
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
            path = self.path.split('?', 1)[0]
            if desk is None or path not in desk_http.ROUTES_POST:
                # Unrelated POST, and every POST at all while the desk is not injected.
                self.respond(405, b'Read only', 'text/plain')
                return
            host = self.authority()
            if host is None:
                self.respond(403, b'Forbidden host', 'text/plain')
                return
            try:
                self.connection.settimeout(desk_http.READ_TIMEOUT_SECONDS)
            except OSError:
                pass
            refusal = desk_http.check_intent(self, host)
            if refusal is not None:
                self.respond(refusal[0], desk_http.error(refusal[1]), desk_http.JSON)
                return
            document, failure = desk_http.read_body(self)
            if failure is not None:
                self.respond(failure[0], desk_http.error(failure[1]), desk_http.JSON)
                return
            status, body = desk_http.handle_post(desk, path, document)
            self.respond(status, body, desk_http.JSON)

        def log_message(self, *args):
            pass
    return Handler


# INV-MONITOR-VIEWER-001 (D6): the viewer listener. The authorized observer identity can forward only to
# this port, so no desk route or POST handler is ever served on it; a local-operator desk uses its own
# separately bound listener that the observer cannot open.
VIEWER_PORT = 8787


def serve(snapshot_path, port=VIEWER_PORT, desk=None, *, viewer_port=VIEWER_PORT, desk_http=None, observer=None):
    if desk is not None and port == viewer_port:
        raise ValueError('The desk is never served on the viewer listener ' + str(viewer_port))
    ThreadingHTTPServer(('127.0.0.1', port), handler(snapshot_path, desk, desk_http=desk_http, observer=observer)).serve_forever()
