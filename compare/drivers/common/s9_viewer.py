"""Shared S9 scenario steps (`observation.viewer`): M7 `adapters/monitoring_web.py` (the loopback read-only viewer, U8; OWNER-DECISIONS-S9 D2.1).

Layer: harness (never shipped)

`api.web` is the side's viewer module (`handler`, `serve`, `resource`, `asset`, `index_page`, `readiness`, `ThreadingHTTPServer`, the constants).
The desk-free matrix of M7 `tests/test_monitoring.py` (`test_http_rejects_mutations_hosts_and_unavailable_snapshot`,
`test_web_json_route_preserves_the_backlog_envelope`, `test_index_falls_back_to_legacy_without_build_and_assets_are_strict`) and the HTTP tests of
`tests/test_monitor_readiness.py` (`test_liveness_and_snapshot_api_keep_their_own_contracts`, `test_host_guard_and_read_only_refusal_cover_the_new_route`,
`test_stale_snapshot_recovers_on_the_same_server_without_restart`, the fresh/stale `/ready` answers) runs against a REAL `ThreadingHTTPServer` built
from `handler(snapshot_path)` on `127.0.0.1` with an ephemeral port, served from a thread and driven with `http.client`. The desk routes are S10's
(`entry.http.desk`): no desk is injected here, except that `serve` refuses a desk on the viewer port before it binds.

Declared normalization (driver-side; no mask-list entry): the ephemeral port appears in a request's Host header only as the symbol `<port>`; the
`Date` and `Server` response headers are dropped and counted (`MASKED_HEADERS`); the scenario temp directory never appears in a result. The clock is
fixed by wrapping the module's `readiness` with an explicit `now`. A body of at most 4096 bytes that is valid UTF-8 is recorded as text, any other
body as its size and sha256.

This module never imports `codex_harness`: everything from the product arrives through `api`. Nothing here touches a database, a provider or any
address but `127.0.0.1`.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from datetime import datetime, timedelta, timezone
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Thread

NOW = datetime(2026, 9, 19, 12, tzinfo=timezone.utc)
MASKED_HEADERS = {"Date": 0, "Server": 0}
REAL_ASSETS = ("index-BXzOlXIh.js", "index-qm7Y6T2g.css")
MAX = 5_000_000


def call(fn, *args, **kwargs):
    try:
        return {"value": fn(*args, **kwargs)}
    except Exception as exc:  # the refusal is the characterized result
        return {"refused": type(exc).__name__, "message": str(exc)[:200]}


def body_view(body: bytes):
    if len(body) <= 4096:
        try:
            return body.decode("utf-8")
        except UnicodeDecodeError:
            pass
    return {"size": len(body), "sha256": hashlib.sha256(body).hexdigest()}


def document(collected=1.0, ages=None):
    ages = {"database": 1.0, "docker": 1.0, "redis": 1.0} if ages is None else ages
    return {"schema": "harness-monitor.v1", "collected_at": (NOW - timedelta(seconds=collected)).isoformat(),
            "scope": {"label": "repository zeus", "docker": "compose", "containers": None},
            "sources": {n: {"status": "ok", "observed_at": (NOW - timedelta(seconds=a)).isoformat(), "data": []} for n, a in ages.items()}}


class Viewer:
    """One real server over one snapshot path, on 127.0.0.1 and an ephemeral port; closed by `close`."""

    def __init__(self, api, root: Path):
        self.api = api
        self.path = root / "monitoring.json"
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), api.web.handler(self.path))
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_port

    def request(self, method, target, headers=None, host="own"):
        """`host`: "own" (http.client's own Host header), "none" (no Host header at all) or the explicit headers."""
        connection = HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            if host == "none":
                connection.putrequest(method, target, skip_host=True, skip_accept_encoding=True)
                for k, v in (headers or {}).items():
                    connection.putheader(k, v)
                connection.endheaders()
            else:
                connection.request(method, target, headers=headers or {})
            response = connection.getresponse()
            body = response.read()
            pairs = response.getheaders()
        finally:
            connection.close()
        kept = []
        for name, value in pairs:
            if name in MASKED_HEADERS:
                MASKED_HEADERS[name] += 1
            else:
                kept.append([name, value])
        return {"status": response.status, "headers": kept, "body": body_view(body)}

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


class Scratch:
    def __init__(self):
        self.root = Path(tempfile.mkdtemp(prefix="s9v-")).resolve()

    def close(self):
        shutil.rmtree(self.root, ignore_errors=True)


def fix_clock(api):
    real = api.web.readiness
    api.web.readiness = lambda path, **kw: real(path, now=NOW, **kw)
    return real


def s1_routes(api, scratch) -> dict:
    """GET / and /legacy over the packaged resources, the strict /assets matrix, 404s, query strings (the strict-asset and route tests)."""
    v = Viewer(api, scratch.root)
    try:
        out = {"index": v.request("GET", "/"), "legacy": v.request("GET", "/legacy"), "index_query": v.request("GET", "/?x=1"),
               "legacy_slash": v.request("GET", "/legacy/"), "unknown": v.request("GET", "/.env"), "empty_path": v.request("GET", "/x")}
        out["assets_valid"] = {name: v.request("GET", "/assets/" + name) for name in REAL_ASSETS}
        out["assets_valid_query"] = v.request("GET", "/assets/" + REAL_ASSETS[0] + "?x=1")
        bad = ["/assets/", "/assets/../monitor.html", "/assets/..%2fmonitor.html", "/assets/x/y.js", "/assets/monitor.html", "/assets/index.json",
               "/assets/.hidden.js", "/assets/missing.js", "/assets/index.js?x=1", "/assets/" + "x" * 130 + ".js", "/assets/..", "/assets/a..b.js",
               "/assets/index-abc.js/", "/assets/-lead.js", "/assets/vite.svg", "/assets/observatory", "/assets/" + REAL_ASSETS[0] + "/"]
        out["assets_refused"] = {t: v.request("GET", t) for t in bad}
        return out
    finally:
        v.close()


def s2_hosts_methods(api, scratch) -> dict:
    """The Host check before routing (403), and POST (405) before the Host check; every route and both loopback authorities."""
    v = Viewer(api, scratch.root)
    try:
        v.path.write_text(json.dumps({"sources": {}}))
        routes = ["/", "/legacy", "/assets/" + REAL_ASSETS[0], "/api/status", "/health", "/ready", "/.env", "/assets/missing.js"]
        wrong = {"untrusted.example": {"Host": "untrusted.example"}, "empty": {"Host": ""}, "no_port": {"Host": "127.0.0.1"},
                 "other_port": {"Host": "127.0.0.1:1"}, "localhost_no_port": {"Host": "localhost"}, "upper": {"Host": "LOCALHOST:%d" % v.port},
                 "ipv6": {"Host": "[::1]:%d" % v.port}, "zero": {"Host": "0.0.0.0:%d" % v.port}}
        out = {"wrong_host": {n: {r: v.request("GET", r, h) for r in routes} for n, h in wrong.items() if n not in ("upper", "ipv6", "zero")},
               "wrong_host_other_forms": {n: v.request("GET", "/api/status", h) for n, h in wrong.items() if n in ("upper", "ipv6", "zero")},
               "missing_host": {r: v.request("GET", r, host="none") for r in routes},
               "localhost_authority": {r: v.request("GET", r, {"Host": "localhost:%d" % v.port}) for r in routes},
               "own_authority": {r: v.request("GET", r, {"Host": "127.0.0.1:%d" % v.port}) for r in routes}}
        post = ["/api/status", "/ready", "/", "/anything", "/api/desk/sessions", "/api/desk/intents", "/health?x=1"]
        out["post"] = {r: v.request("POST", r) for r in post}
        out["post_wrong_host"] = {r: v.request("POST", r, {"Host": "untrusted.example"}) for r in post}
        out["post_missing_host"] = {r: v.request("POST", r, host="none") for r in post}
        out["post_with_body"] = v.request("POST", "/api/status", {"Content-Length": "2", "Content-Type": "application/json"})
        return out
    finally:
        v.close()


def s3_status(api, scratch) -> dict:
    """/api/status over a missing, valid, oversized, non-JSON, truncated, empty, binary and directory snapshot (the 503 contract), and /health."""
    v = Viewer(api, scratch.root)
    try:
        out = {"missing": v.request("GET", "/api/status")}
        cases = [("valid", json.dumps({"sources": {}}).encode()), ("valid_unicode", json.dumps({"label": "관측"}, ensure_ascii=False).encode()),
                 ("envelope", json.dumps(document()).encode()), ("truncated", b'{"sources": '), ("not_json", b"hello"), ("empty", b""),
                 ("binary_utf8", b"\xff\xfe\x00"), ("json_scalar", b"5"), ("json_null", b"null"),
                 ("at_limit", b'{"a":"' + b"x" * (MAX - 8) + b'"}'), ("over_limit", b'{"a":"' + b"x" * (MAX - 7) + b'"}'),
                 ("padded_at_limit", b"{}" + b" " * (MAX - 2)), ("padded_over_limit", b"{}" + b" " * (MAX - 1))]
        out["files"] = {}
        for name, body in cases:
            v.path.write_bytes(body)
            out["files"][name] = {"size": len(body), "response": v.request("GET", "/api/status")}
        v.path.unlink()
        v.path.mkdir()
        out["directory"] = v.request("GET", "/api/status")
        v.path.rmdir()
        v.path.write_text(json.dumps({"sources": {}}))
        out["recovered"] = v.request("GET", "/api/status")
        out["query"] = v.request("GET", "/api/status?x=1")
        out["slash"] = v.request("GET", "/api/status/")
        out["health"] = v.request("GET", "/health")
        out["health_missing_snapshot"] = (v.path.unlink(), v.request("GET", "/health"))[1]
        out["health_query"] = v.request("GET", "/health?x=1")
        out["health_slash"] = v.request("GET", "/health/")
        return out
    finally:
        v.close()


def s4_ready(api, scratch) -> dict:
    """/ready over fresh, stale, missing and undecodable snapshots (the readiness HTTP tests; `run` fixes the viewer's `readiness` clock at NOW for every group)."""
    v = Viewer(api, scratch.root)
    try:
        out = {"missing": v.request("GET", "/ready")}
        for name, body in [("fresh", document()), ("stale", document(collected=300, ages=dict.fromkeys(("database", "docker", "redis"), 300.0))),
                           ("stale_source", document(ages={"database": 1.0, "docker": 300.0, "redis": 1.0})),
                           ("future", document(collected=-60)), ("no_sources", {"schema": "harness-monitor.v1", "collected_at": NOW.isoformat(), "sources": {}})]:
            v.path.write_text(json.dumps(body))
            out[name] = v.request("GET", "/ready")
        out["recovered_on_same_server"] = (v.path.write_text(json.dumps(document())), v.request("GET", "/ready"))[1]
        for name, body in [("garbage", b"{"), ("empty", b""), ("list", b"[]")]:
            v.path.write_bytes(body)
            out[name] = v.request("GET", "/ready")
        v.path.write_text(json.dumps(document()))
        out["query"] = v.request("GET", "/ready?x=1")
        out["slash"] = v.request("GET", "/ready/")
        out["wrong_host"] = v.request("GET", "/ready", {"Host": "untrusted.example"})
        out["post"] = v.request("POST", "/ready")
        out["status_still_the_snapshot"] = v.request("GET", "/api/status")
        return out
    finally:
        v.close()


def s5_packaged_resources(api, scratch) -> dict:
    """The index fallback and the asset size bound over a substituted `resource` directory (`test_index_falls_back_to_legacy...`)."""
    web, tmp = api.web, scratch.root / "res"
    assets = tmp / "observatory" / "assets"
    assets.mkdir(parents=True)
    legacy = b"<!doctype html><title>legacy</title><script>1</script>"
    (tmp / "monitor.html").write_bytes(legacy)
    for name, body in [("index-abc.js", b"console.log(1)"), ("index-abc.css", b"body{}"), ("big.js", b"x" * (MAX + 1)), ("limit.js", b"x" * MAX),
                       ("secret.json", b"{}"), ("font.woff2", b"\x00w2"), ("font.woff", b"\x00w1"), ("pic.svg", b"<svg/>"), ("noext", b"x"),
                       ("UPPER.JS", b"1"), ("a.map", b"{}"), ("dot.", b"x"), ("empty.js", b""), ("x" * 125 + ".js", b"1")]:
        (assets / name).write_bytes(body)
    (assets / "dir.js").mkdir()
    real = web.resource
    web.resource = lambda *parts: tmp.joinpath(*parts)
    v = Viewer(api, scratch.root)
    try:
        out = {"index_legacy_fallback": v.request("GET", "/"), "index_legacy_equal": None}
        out["index_legacy_equal"] = out["index_legacy_fallback"]["body"] == legacy.decode()
        (tmp / "observatory" / "index.html").write_bytes(b'<!doctype html><div id="root"></div>')
        out["index_built"] = v.request("GET", "/")
        out["legacy_route"] = v.request("GET", "/legacy")
        names = ["index-abc.js", "index-abc.css", "big.js", "limit.js", "secret.json", "font.woff2", "font.woff", "pic.svg", "noext", "UPPER.JS",
                 "a.map", "dot.", "empty.js", "dir.js", "index-abc.js/", ".hidden.js", "x" * 125 + ".js", "x" * 126 + ".js"]
        out["assets"] = {n: v.request("GET", "/assets/" + n) for n in names}
        out["direct"] = {"asset": {n: call(web.asset, n) for n in ["index-abc.js", "big.js", "secret.json", "..", "../legacy/monitor.html", "dir.js", "a" * 129,
                                                                    "limit.js"]}}
        out["direct"]["asset"] = {n: ({"refused": r["refused"]} if "refused" in r else {"none": r["value"] is None,
                                                                                      "typed": None if r["value"] is None else [body_view(r["value"][0]), r["value"][1]]})
                                  for n, r in out["direct"]["asset"].items()}
        out["direct"]["index_page"] = body_view(web.index_page())
        out["direct"]["constants"] = {"ASSET_TYPES": web.ASSET_TYPES, "MAX_ASSET_BYTES": web.MAX_ASSET_BYTES, "ASSET_NAME": web.ASSET_NAME.pattern,
                                      "CSP": web.CSP, "VIEWER_PORT": web.VIEWER_PORT}
        return out
    finally:
        web.resource = real
        v.close()


def s6_serve(api, scratch) -> dict:
    """`serve`: a desk on the viewer port is refused with ValueError before any bind; the desk-free bind is 127.0.0.1 only, on the given port."""
    web = api.web
    real = web.ThreadingHTTPServer
    made = []

    class Recorder:
        def __init__(self, address, handler_class):
            made.append({"address": list(address), "handler_is_class": isinstance(handler_class, type)})

        def serve_forever(self):
            made[-1]["served"] = True
    web.ThreadingHTTPServer = Recorder
    try:
        path = scratch.root / "monitoring.json"
        out = {"desk_on_default_port": call(web.serve, path, desk=object()),
               "desk_on_explicit_viewer_port": call(web.serve, path, 9911, desk=object(), viewer_port=9911),
               "desk_on_viewer_port_positional": call(web.serve, path, web.VIEWER_PORT, object()),
               "desk_on_overridden_viewer_port": call(web.serve, path, 8787, object(), viewer_port=8787),
               "binds_before_refusal": list(made)}
        made.clear()
        out["web_mode_default_port"] = (call(web.serve, path), list(made))
        made.clear()
        out["web_mode_explicit_port"] = (call(web.serve, path, 9912), list(made))
        made.clear()
        out["web_mode_viewer_port_override"] = (call(web.serve, path, 9913, None, viewer_port=9913), list(made))
        return out
    finally:
        web.ThreadingHTTPServer = real


def run(api) -> dict:
    scratch = Scratch()
    real = fix_clock(api)
    try:
        groups = {"routes": s1_routes, "hosts_methods": s2_hosts_methods, "status": s3_status, "ready": s4_ready,
                  "packaged_resources": s5_packaged_resources, "serve": s6_serve}
        out = {name: fn(api, scratch) for name, fn in groups.items()}
        text = json.dumps(out)
        out["masked_headers"] = dict(MASKED_HEADERS)
        out["tmp_dir_in_result"] = str(scratch.root) in text
        return out
    finally:
        api.web.readiness = real
        scratch.close()
