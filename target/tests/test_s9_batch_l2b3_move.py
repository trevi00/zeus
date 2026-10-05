"""S9 batch L2-B3: the viewer (U8) moves out of M7 `adapters/monitoring_web.py` into `observation.adapters.viewer_http`.

The module is M7's whole, in M7's order, with only its import block (R-v0), the `desk_http` injection (R-v1, R-v2) and its header changed
(OWNER-DECISIONS-S9 D2.1). M7 is read only as text through `git show e38aa722:...` and compared by AST (never imported: both packages are named
`codex_harness`). Desk-free behaviour is compared by the recorded `observation.viewer` golden (the moved module is target-equal to it); this file pins
what a golden cannot: the AST modulo R-v0..R-v2, the import homes, the R-v1 refusal, and the injected desk branch driven by a recording fake
`DeskHttp` (each call made with M7's arguments in M7's order, the read timeout applied, `desk_http` never read when `desk` is None), the R-v2 order and
the 127.0.0.1-only bind.

M7 tests this unit does NOT port yet (the S9 ported suite is a later step): from `test_monitoring.py`
`test_http_rejects_mutations_hosts_and_unavailable_snapshot`, `test_web_json_route_preserves_the_backlog_envelope` (needs the monitoring collector, U6) and
`test_index_falls_back_to_legacy_without_build_and_assets_are_strict`; from `test_monitor_readiness.py` the twelve tests over the `monitor` fixture
(`test_fresh_snapshot_is_ready_over_http_with_the_fixed_contract`, `test_present_optional_envelopes_are_assessed_and_absent_ones_omitted`,
`test_undecodable_snapshots_answer_503_with_no_sources_and_no_crash`, `test_missing_and_unreadable_snapshot_paths_are_unavailable`,
`test_oversized_snapshot_is_refused_before_parsing`, `test_liveness_and_snapshot_api_keep_their_own_contracts`,
`test_payload_content_is_never_read_as_health`, `test_stale_snapshot_recovers_on_the_same_server_without_restart`,
`test_readiness_never_reflects_snapshot_values_keys_paths_or_errors`, `test_readiness_writes_nothing_and_creates_no_file`,
`test_host_guard_and_read_only_refusal_cover_the_new_route`, `test_each_request_is_one_complete_view_or_a_refused_open_while_the_file_is_replaced`);
`test_frontdesk_http.py` (the desk routes over `handler(snapshot_path, desk)`: S10 `entry.http.desk`) and the `monitoring_web` mention in
`test_role_containers.py`.
"""

from __future__ import annotations

import ast
import copy
import inspect
import subprocess
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import pytest
from _layout import REPO, TARGET

from codex_harness.kernel.errors import ContractError
from codex_harness.observation import ports
from codex_harness.observation.adapters import viewer_http as viewer

SRC = TARGET / "src" / "codex_harness"
SOURCE = "e38aa722"
M7 = "src/codex_harness/adapters/monitoring_web.py"
TEXT = Path(viewer.__file__).read_text()
FORBIDDEN_HOMES = ("codex_harness.adapters", "codex_harness.domain", "codex_harness.application", "codex_harness.ports", "codex_harness.entry",
                   "codex_harness.intake")
DESK_POST = "/api/desk/sessions"


def show(rev, path):
    return subprocess.run(["git", "-C", str(REPO), "show", f"{rev}:{path}"], check=True, capture_output=True, text=True).stdout


def statements(src):
    out = {}
    for i, node in enumerate(ast.parse(src).body):
        if isinstance(node, (ast.Import, ast.ImportFrom)) or (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)):
            continue
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            name = node.name
        elif isinstance(node, ast.Assign):
            name = node.targets[0].id
        else:
            name = i
        out[name] = node
    return out


class InverseOfRules(ast.NodeTransformer):
    """The inverse of R-v1, R-v2, R-v3 (S11 XC-1 A4: `Handler.timeout = 5`) and R-v4 (S11 XC-2b B2: the keyword-only `observer`, `Handler.refused` and the one `self.refused(...)` call opening `respond`) on the target AST: M7's `frontdesk_http`, no `desk_http` parameter, no `require`, no forwarded keyword."""

    def visit_Attribute(self, node):
        self.generic_visit(node)
        if isinstance(node.value, ast.Name) and node.value.id == "desk_http":
            node.value.id = "frontdesk_http"
        return node

    def visit_FunctionDef(self, node):
        if node.name in ("handler", "serve"):
            node.args.kwonlyargs = [a for a in node.args.kwonlyargs if a.arg not in ("desk_http", "observer")]
            node.args.kw_defaults = node.args.kw_defaults[:len(node.args.kwonlyargs)]
        if node.name == "respond":
            node.body = [s for s in node.body if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Call)
                                                      and getattr(s.value.func, "attr", "") == "refused")]
        if node.name == "handler":
            node.body = [s for s in node.body if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Call) and getattr(s.value.func, "id", "") == "require")]
        self.generic_visit(node)
        return node

    def visit_ClassDef(self, node):
        # R-v3 (S11 XC-1 A4): `Handler.timeout`, one class attribute, is the only addition to the class body.
        if node.name == "Handler":
            node.body = [s for s in node.body if not (isinstance(s, ast.Assign) and [t.id for t in s.targets] == ["timeout"])
                         and not (isinstance(s, ast.FunctionDef) and s.name == "refused")]  # R-v4
        self.generic_visit(node)
        return node

    def visit_Call(self, node):
        self.generic_visit(node)
        node.keywords = [k for k in node.keywords if k.arg not in ("desk_http", "observer")]
        return node


def test_the_module_is_m7s_in_m7s_order_modulo_r_v0_to_r_v2():
    ours, theirs = statements(TEXT), statements(show(SOURCE, M7))
    assert list(ours) == list(theirs)
    assert list(ours) == ["ASSET_NAME", "ASSET_TYPES", "MAX_ASSET_BYTES", "CSP", "resource", "asset", "index_page", "handler", "VIEWER_PORT", "serve"]
    changed = []
    for name, node in theirs.items():
        if ast.dump(ours[name]) == ast.dump(node):
            continue
        changed.append(name)
        assert ast.dump(InverseOfRules().visit(copy.deepcopy(ours[name]))) == ast.dump(node), name
    assert changed == ["handler", "serve"]


def test_the_first_header_paragraphs_are_m7s_module_docstring():
    m7 = ast.get_docstring(ast.parse(show(SOURCE, M7)))
    doc = ast.get_docstring(ast.parse(TEXT))
    assert doc.startswith(m7 + "\n\nLayer: adapters\nContext: observation\n")
    for field in ("Owns:", "Does not own:", "Entry points:", "Contracts: INV-MONITOR-VIEWER-001", "Moved from M7", SOURCE, "named rules", "D2.1"):
        assert field in doc, field
    entry_points = doc.split("Entry points:")[1].split("\n")[0]
    for name in ("handler", "serve", "resource", "asset", "index_page", "VIEWER_PORT", "CSP"):
        assert name in entry_points


def test_import_homes_and_no_frontdesk_entry_or_intake_import():
    tree = ast.parse(TEXT)
    from_imports = {n.module: sorted(a.name for a in n.names) for n in tree.body if isinstance(n, ast.ImportFrom)}
    assert from_imports == {"http.server": ["BaseHTTPRequestHandler", "ThreadingHTTPServer"], "importlib.resources": ["files"],
                            "codex_harness.kernel.errors": ["require"],
                            "codex_harness.observation.adapters.monitoring_readiness": ["readiness"]}
    assert sorted(a.name for n in tree.body if isinstance(n, ast.Import) for a in n.names) == ["json", "re"]
    modules = [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
    assert not [m for m in modules if m.startswith(FORBIDDEN_HOMES)]
    imported = {a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names}
    assert "frontdesk_http" not in imported
    code_names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert "frontdesk_http" not in code_names and "entry" not in code_names and "intake" not in code_names
    assert "subprocess" not in TEXT and "multiprocessing" not in TEXT and "Popen" not in TEXT
    assert viewer.readiness.__module__ == "codex_harness.observation.adapters.monitoring_readiness"


def test_names_and_call_shapes_are_m7s_with_desk_http_keyword_only():
    assert not hasattr(viewer, "ViewerHandler")
    handler_params = inspect.signature(viewer.handler).parameters
    assert list(handler_params) == ["snapshot_path", "desk", "desk_http", "observer"]  # R-v4: observer is keyword-only, default None
    assert handler_params["desk"].default is None and handler_params["desk_http"].default is None
    assert handler_params["desk_http"].kind is inspect.Parameter.KEYWORD_ONLY
    serve_params = inspect.signature(viewer.serve).parameters
    assert list(serve_params) == ["snapshot_path", "port", "desk", "viewer_port", "desk_http", "observer"]
    assert serve_params["port"].default == viewer.VIEWER_PORT == 8787 and serve_params["viewer_port"].default == viewer.VIEWER_PORT
    assert serve_params["viewer_port"].kind is serve_params["desk_http"].kind is inspect.Parameter.KEYWORD_ONLY
    # M7 monitor.py:176-182 (S10): web mode `serve(snapshot, port)`, desk mode `serve(snapshot, port, desk=..., viewer_port=...)`.
    signature = inspect.signature(viewer.serve)
    signature.bind("snapshot", 9000)
    signature.bind("snapshot", 9000, desk=object(), viewer_port=8787)
    signature.bind("snapshot", 9000, desk=object(), viewer_port=8787, desk_http=object())
    with pytest.raises(TypeError):
        signature.bind("snapshot", 9000, None, 8787)  # viewer_port and desk_http are keyword-only


def test_the_desk_port_members_are_exactly_what_the_viewer_reads():
    members = {n for n in vars(ports.DeskHttp).get("__annotations__", {})} | {
        n for n, v in vars(ports.DeskHttp).items() if inspect.isfunction(v) and not n.startswith("_")}
    assert members == {"JSON", "READ_TIMEOUT_SECONDS", "ROUTES_POST", "handle_get", "check_intent", "read_body", "handle_post", "error"}
    read = {n.attr for n in ast.walk(ast.parse(TEXT)) if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == "desk_http"}
    assert read == members
    assert len([n for n in members if inspect.isfunction(vars(ports.DeskHttp).get(n))]) <= 6  # MAX_PORT_METHODS


class FakeDeskHttp:
    """A recording `DeskHttp`: every call is logged as (name, args); results are scripted per test."""
    JSON = "application/x-fake-desk"
    READ_TIMEOUT_SECONDS = 1.25
    ROUTES_POST = {DESK_POST}

    def __init__(self):
        self.calls = []
        self.get = {}
        self.intent = None
        self.body = ({"k": "v"}, None)
        self.post = (201, b'{"posted":true}')
        self.timeouts = []

    def handle_get(self, desk, path):
        self.calls.append(("handle_get", desk, path))
        return self.get.get(path)

    def check_intent(self, handler, authority):
        self.calls.append(("check_intent", handler.__class__.__name__, authority))
        self.timeouts.append(handler.connection.gettimeout())
        return self.intent

    def read_body(self, handler):
        self.calls.append(("read_body", handler.__class__.__name__))
        return self.body

    def handle_post(self, desk, path, document):
        self.calls.append(("handle_post", desk, path, document))
        return self.post

    def error(self, code):
        self.calls.append(("error", code))
        return b'{"error":"' + code.encode() + b'"}'


class Strict:
    """Any read of an attribute is a failure: `desk_http` must never be read when `desk` is None."""

    def __getattribute__(self, name):
        raise AssertionError(f"desk_http.{name} was read")


class Viewer:
    def __init__(self, tmp_path, desk=None, desk_http=None, **kwargs):
        self.path = tmp_path / "monitoring.json"
        self.path.write_text('{"sources": {}}')
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), viewer.handler(self.path, desk, desk_http=desk_http, **kwargs))
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_port

    def request(self, method, target, headers=None, body=None):
        connection = HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            connection.request(method, target, body=body, headers=headers or {})
            response = connection.getresponse()
            return response.status, response.read(), dict(response.getheaders())
        finally:
            connection.close()

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


@pytest.fixture
def served(tmp_path):
    made = []

    def make(desk=None, desk_http=None, **kwargs):
        made.append(Viewer(tmp_path, desk, desk_http, **kwargs))
        return made[-1]
    yield make
    for each in made:
        each.close()


def test_a_desk_without_desk_http_is_refused_before_any_class_or_socket(tmp_path, monkeypatch):
    binds = []
    monkeypatch.setattr(viewer, "ThreadingHTTPServer", lambda *a: binds.append(a))
    with pytest.raises(ContractError, match="desk_http is not wired"):
        viewer.handler(tmp_path / "s.json", object())
    with pytest.raises(ContractError, match="desk_http is not wired"):
        viewer.serve(tmp_path / "s.json", 9001, object())
    assert binds == []
    # With the port injected, or without a desk, the class is built.
    assert isinstance(viewer.handler(tmp_path / "s.json", object(), desk_http=FakeDeskHttp()), type)
    assert isinstance(viewer.handler(tmp_path / "s.json"), type)
    assert isinstance(viewer.handler(tmp_path / "s.json", desk_http=FakeDeskHttp()), type)  # a port without a desk is inert
    # The refusal is the first statement after the docstring.
    body = [n for n in ast.parse(TEXT).body if isinstance(n, ast.FunctionDef) and n.name == "handler"][0].body
    assert isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant)
    assert ast.unparse(body[1]) == "require(desk is None or desk_http is not None, 'desk_http is not wired')"
    assert isinstance(body[2], ast.ClassDef)


def test_the_viewer_port_refusal_precedes_everything_in_serve(tmp_path, monkeypatch):
    binds = []
    monkeypatch.setattr(viewer, "ThreadingHTTPServer", lambda *a: binds.append(a))
    # No desk_http either: the ValueError, not the R-v1 ContractError, is what the caller sees.
    with pytest.raises(ValueError, match="The desk is never served on the viewer listener 8787") as caught:
        viewer.serve(tmp_path / "s.json", desk=object())
    assert not isinstance(caught.value, ContractError)
    with pytest.raises(ValueError, match="listener 9911"):
        viewer.serve(tmp_path / "s.json", 9911, object(), viewer_port=9911, desk_http=FakeDeskHttp())
    assert binds == []
    first = [n for n in ast.parse(TEXT).body if isinstance(n, ast.FunctionDef) and n.name == "serve"][0].body[0]
    assert isinstance(first, ast.If) and ast.unparse(first.test) == "desk is not None and port == viewer_port"
    assert isinstance(first.body[0], ast.Raise)


def test_serve_binds_127_0_0_1_only_and_forwards_the_port(tmp_path, monkeypatch):
    made = []

    class Recorder:
        def __init__(self, address, handler_class):
            made.append((address, handler_class))

        def serve_forever(self):
            made.append("served")
    monkeypatch.setattr(viewer, "ThreadingHTTPServer", Recorder)
    fake = FakeDeskHttp()
    viewer.serve(tmp_path / "s.json", 9020)
    viewer.serve(tmp_path / "s.json", 9021, desk="DESK", viewer_port=8787, desk_http=fake)
    assert [m[0] for m in made if m != "served"] == [("127.0.0.1", 9020), ("127.0.0.1", 9021)]
    assert made.count("served") == 2
    constants = [n.value for n in ast.walk(ast.parse(TEXT)) if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    assert "0.0.0.0" not in constants and "::" not in constants and "::1" not in constants
    binds = [n for n in ast.walk(ast.parse(TEXT)) if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "ThreadingHTTPServer"]
    assert len(binds) == 1 and ast.unparse(binds[0].args[0]) == "('127.0.0.1', port)"
    # The handler class built for the desk call carries the injected port (the desk route answers through the fake).
    assert made[2][1].__name__ == "Handler"


def test_the_real_listener_is_loopback_only_and_serves_the_desk_free_routes(served):
    v = served(desk=None, desk_http=Strict())
    assert v.server.server_address[0] == "127.0.0.1"
    assert v.request("GET", "/health")[:2] == (200, b'{"service":"harness-monitor"}')
    assert v.request("POST", DESK_POST)[:2] == (405, b"Read only")  # a desk route is not served without a desk
    assert v.request("GET", "/api/desk/anything")[0] == 404


def test_desk_http_is_never_read_when_the_desk_is_none(served):
    v = served(desk=None, desk_http=Strict())  # any attribute read raises AssertionError inside the request thread: it would drop the connection
    for method, target in [("GET", "/"), ("GET", "/legacy"), ("GET", "/api/status"), ("GET", "/health"), ("GET", "/ready"), ("GET", "/nope"),
                           ("GET", "/api/desk/sessions"), ("POST", DESK_POST), ("POST", "/anything")]:
        status, _body, _headers = v.request(method, target)
        assert status in (200, 404, 405, 503), (method, target)
    assert v.request("GET", "/", {"Host": "untrusted.example"})[0] == 403
    assert v.request("POST", DESK_POST, {"Host": "untrusted.example"})[0] == 405


def test_the_injected_get_branch_calls_handle_get_first_with_m7s_arguments(served):
    fake = FakeDeskHttp()
    fake.get = {"/api/desk/sessions": (200, b'{"desk":"get"}'), "/api/desk/gone": (404, b'{"error":"gone"}')}
    desk = object()
    v = served(desk=desk, desk_http=fake)
    status, body, headers = v.request("GET", "/api/desk/sessions?x=1")
    assert (status, body) == (200, b'{"desk":"get"}')
    assert headers["Content-Type"] == FakeDeskHttp.JSON and headers["Cache-Control"] == "no-store"
    assert headers["Content-Security-Policy"] == viewer.CSP
    assert fake.calls == [("handle_get", desk, "/api/desk/sessions")]  # the query is stripped; the desk object itself is passed
    fake.calls.clear()
    assert v.request("GET", "/api/desk/gone")[:2] == (404, b'{"error":"gone"}')
    assert fake.calls == [("handle_get", desk, "/api/desk/gone")]
    fake.calls.clear()
    # None from the port falls through to the viewer routes, which stay M7's.
    assert v.request("GET", "/health")[:2] == (200, b'{"service":"harness-monitor"}')
    assert v.request("GET", "/nope")[:2] == (404, b"Not found")
    assert fake.calls == [("handle_get", desk, "/health"), ("handle_get", desk, "/nope")]
    fake.calls.clear()
    # The loopback Host check precedes the desk branch: the port is not called for a refused host.
    assert v.request("GET", "/api/desk/sessions", {"Host": "untrusted.example"})[:2] == (403, b"Forbidden host")
    assert fake.calls == []


def test_the_injected_post_branch_calls_in_m7s_order_with_m7s_arguments_and_the_read_timeout(served):
    fake = FakeDeskHttp()
    desk = object()
    v = served(desk=desk, desk_http=fake)
    status, body, headers = v.request("POST", DESK_POST + "?q=1", {"Content-Type": "application/json"}, b"{}")
    assert (status, body) == (201, b'{"posted":true}')
    assert headers["Content-Type"] == FakeDeskHttp.JSON
    authority = f"127.0.0.1:{v.port}"
    assert fake.calls == [("check_intent", "Handler", authority), ("read_body", "Handler"), ("handle_post", desk, DESK_POST, {"k": "v"})]
    assert fake.timeouts == [FakeDeskHttp.READ_TIMEOUT_SECONDS]  # settimeout(desk_http.READ_TIMEOUT_SECONDS) precedes check_intent
    # The authority handed to the port is the request's own Host value, for either loopback name.
    fake.calls.clear()
    v.request("POST", DESK_POST, {"Host": f"localhost:{v.port}"})
    assert fake.calls[0] == ("check_intent", "Handler", f"localhost:{v.port}")


def test_an_intent_refusal_and_a_body_failure_stop_the_post_at_their_step(served):
    fake = FakeDeskHttp()
    v = served(desk=object(), desk_http=fake)
    fake.intent = (403, "intent_refused")
    status, body, headers = v.request("POST", DESK_POST)
    assert (status, body, headers["Content-Type"]) == (403, b'{"error":"intent_refused"}', FakeDeskHttp.JSON)
    assert [c[0] for c in fake.calls] == ["check_intent", "error"] and fake.calls[1] == ("error", "intent_refused")
    fake.calls.clear()
    fake.intent, fake.body = None, (None, (413, "too_large"))
    status, body, _ = v.request("POST", DESK_POST)
    assert (status, body) == (413, b'{"error":"too_large"}')
    assert [c[0] for c in fake.calls] == ["check_intent", "read_body", "error"] and fake.calls[2] == ("error", "too_large")


def test_a_post_the_port_does_not_route_or_a_foreign_host_never_reaches_it(served):
    fake = FakeDeskHttp()
    v = served(desk=object(), desk_http=fake)
    assert v.request("POST", "/api/status")[:2] == (405, b"Read only")
    assert v.request("POST", DESK_POST + "/")[:2] == (405, b"Read only")
    assert v.request("POST", DESK_POST, {"Host": "untrusted.example"})[:2] == (403, b"Forbidden host")
    assert fake.calls == []


def test_the_ten_desk_call_sites_are_m7s_in_m7s_order():
    ours = [(n.attr, n.lineno) for n in ast.walk(ast.parse(TEXT)) if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == "desk_http"]
    theirs = [(n.attr, n.lineno) for n in ast.walk(ast.parse(show(SOURCE, M7)))
              if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == "frontdesk_http"]
    assert [a for a, _ in sorted(ours, key=lambda x: x[1])] == [a for a, _ in sorted(theirs, key=lambda x: x[1])]
    assert len(ours) == 12 and len({line for _, line in ours}) == 10
