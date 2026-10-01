"""`tokobs serve`: the periodic scan plus a read-only `/metrics` endpoint (stdlib `http.server`).

Purpose: the collector container's entry (DESIGN §3, §7). Layer: tooling. Owns: the 60 s scan loop under the
single-instance flock (held for the life of the service, so a second `serve` exits 75), the `/metrics` body
(`data.prom` + `health.prom`, both always served so a render refusal stays visible), the `--listen` check
(an IP:port only, never a hostname), and the `--fixture` mode.
Does-not-own: scanning or rendering logic, any file outside the data directory.
Implements: ACCEPTANCE A43 (exporter serves both files), A56 (fixture mode for W2's connectivity test), A18.

`--fixture` serves one static sample, opens no ledger, takes no lock and reads no worker input.
"""

from __future__ import annotations

import ipaddress
import threading
import time
from collections.abc import Callable
from contextlib import ExitStack
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .collector import scan_locked
from .config import TaskClassRegistry
from .ledger import collector_lock, open_ledger
from .render import DATA_NAME, HEALTH_NAME, render

SCAN_INTERVAL_SECONDS = 60
CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"
FIXTURE_SAMPLE = (
    "# HELP zeus_tokobs_fixture_sample Static sample served by `tokobs serve --fixture`\n"
    "# TYPE zeus_tokobs_fixture_sample gauge\n"
    "zeus_tokobs_fixture_sample 42\n")


def parse_listen(text: str) -> tuple[str, int]:
    """`ADDR:PORT` with ADDR an IPv4/IPv6 literal (IPv6 in brackets). A hostname or a bare port is refused."""
    if not isinstance(text, str) or ":" not in text:
        raise ValueError("--listen must be ADDR:PORT with an IP address")
    host, _, port = text.rpartition(":")
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        raise ValueError("--listen host must be an IP address, not a name") from None
    if not port.isascii() or not port.isdigit() or int(port) > 65535:
        raise ValueError("--listen port must be 0-65535")
    return str(address), int(port)


class _Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, family_host: str, body: Callable[[], bytes | None]):
        import socket
        if ":" in family_host:
            self.address_family = socket.AF_INET6
        self.body = body
        super().__init__(address, _Handler)


class _Handler(BaseHTTPRequestHandler):
    server: _Server

    def _send(self, code: int, payload: bytes, content_type: str = "text/plain; charset=utf-8") -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(payload)

    def do_GET(self) -> None:  # noqa: N802 (http.server API)
        if self.path.split("?", 1)[0] != "/metrics":
            self._send(404, b"not found\n")
            return
        body = self.server.body()
        if body is None:
            self._send(503, b"no exposition yet\n")
        else:
            self._send(200, body, CONTENT_TYPE)

    do_HEAD = do_GET  # noqa: N815

    def _refuse(self) -> None:
        self._send(405, b"method not allowed\n")

    do_POST = do_PUT = do_DELETE = do_PATCH = _refuse  # noqa: N815

    def log_message(self, format: str, *args) -> None:  # noqa: A002 (no per-request log lines)
        return


class Service:
    """The collector service. Tests drive it with `scan_now()` and an effectively infinite interval."""

    def __init__(self, listen: str, *, data: Path | None = None, source_root: Path | None = None,
                 fixture: bool = False, interval: float = SCAN_INTERVAL_SECONDS,
                 clock: Callable[[], float] = time.time, registry: TaskClassRegistry | None = None,
                 live_since: int | None = None, s9_dir: Path | None = None, deferred_file: Path | None = None):
        self.host, self.port = parse_listen(listen)
        if not fixture and (data is None or source_root is None):
            raise ValueError("serve needs --data and --source-root (or --fixture)")
        self.data, self.source_root, self.fixture = data, source_root, fixture
        self.interval, self.clock, self.registry = interval, clock, registry
        self.live_since, self.s9_dir, self.deferred_file = live_since, s9_dir, deferred_file
        self._stack = ExitStack()
        self._stop = threading.Event()
        self._scan_lock = threading.Lock()
        self._server: _Server | None = None
        self._threads: list[threading.Thread] = []
        self.started_at = 0

    def body(self) -> bytes | None:
        if self.fixture:
            return FIXTURE_SAMPLE.encode()
        parts = []
        for name in (DATA_NAME, HEALTH_NAME):
            try:
                parts.append((Path(self.data) / name).read_bytes())  # type: ignore[arg-type]
            except OSError:
                continue
        return b"".join(parts) if parts else None

    def scan_now(self) -> bool:
        """One scan + render under the held flock. Returns True when the render was accepted."""
        if self.fixture:
            return True
        with self._scan_lock:
            now = int(self.clock())
            ledger = open_ledger(Path(self.data))  # type: ignore[arg-type]
            try:
                scan_locked(ledger, Path(self.source_root), now=now, registry=self.registry,  # type: ignore[arg-type]
                            live_since=self.live_since if self.live_since is not None else self.started_at,
                            s9_dir=self.s9_dir, deferred_file=self.deferred_file)
                return not render(ledger, Path(self.data), now).refused  # type: ignore[arg-type]
            finally:
                ledger.close()

    def start(self) -> int:
        """Take the lock (CollectorBusy when held elsewhere), bind, and start the scan loop. Returns the port."""
        if not self.fixture:
            self._stack.enter_context(collector_lock(Path(self.data)))  # type: ignore[arg-type]
        self.started_at = int(self.clock())
        try:
            self._server = _Server((self.host, self.port), self.host, self.body)
        except BaseException:
            self._stack.close()
            raise
        self.port = self._server.server_address[1]
        self._threads.append(threading.Thread(target=self._server.serve_forever, name="tokobs-http", daemon=True))
        if not self.fixture:
            self._threads.append(threading.Thread(target=self._loop, name="tokobs-scan", daemon=True))
        for thread in self._threads:
            thread.start()
        return self.port

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.scan_now()
            except Exception as exc:  # a failed scan must not stop serving the last good files
                import sys
                print(f"tokobs: scan failed: {type(exc).__name__}", file=sys.stderr)
            if self._stop.wait(self.interval):
                return

    def stop(self) -> None:
        self._stop.set()
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        for thread in self._threads:
            thread.join(timeout=10)
        self._stack.close()
        self._threads.clear()

    def wait(self) -> None:
        try:
            while not self._stop.wait(1.0):
                pass
        except KeyboardInterrupt:
            pass
