"""S8 pilot 84: the M7 front door split by owner (V16): `FrontDesk` -> `intake.application.frontdesk`, `DeskRunner` ->
`coordination.application.desk_runner`, VERBATIM through named rules (A/evidence/rebuild/s8/frontdesk-move/transcribe.py;
DESIGN-s8 §11 V16: R-f0..R-f3, R-d0..R-d3).

M7 is read only as text through `git show e38aa722:...` and compared by AST (never imported: both packages are named
`codex_harness`). Behaviour is checked on the TARGET only, against literals; the recorded comparison is the `intake.frontdesk` golden.
"""
import ast
import importlib
import inspect
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from codex_harness.kernel.errors import ContractError

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "target" / "src" / "codex_harness"
SOURCE = "e38aa722"
M7_PATH = "src/codex_harness/application/frontdesk.py"
FRONT = "codex_harness.intake.application.frontdesk"
RUNNER = "codex_harness.coordination.application.desk_runner"
DOMAIN = "codex_harness.intake.domain.frontdesk"
DESK_BUCKETS = ("desk_sessions", "desk_requests", "desk_events", "desk_receipts")
RUNNER_CONSTANTS = {("TASK_DEADLINE_SECONDS",), ("MAX_ATTEMPTS",), ("SUMMARY_TURNS",)}
MOVED_AHEAD = ("CONDUCTOR", "LEAD")  # R-f2
DESK_QUEUE = ["claim_next", "dispatching", "finalize", "receipt", "record_receipt"]
REVISION = "0" * 39 + "a"


def m7_text():
    return subprocess.run(["git", "-C", str(REPO), "show", f"{SOURCE}:{M7_PATH}"], check=True, capture_output=True,
                          text=True).stdout


def target_text(module):
    return Path(importlib.import_module(module).__file__).read_text()


def defined(node):
    if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
        return (node.name,)
    if isinstance(node, ast.Assign):
        return tuple(n.id for t in node.targets for n in ast.walk(t) if isinstance(n, ast.Name))
    return ()


def statements(src):
    out = {}
    for i, node in enumerate(ast.parse(src).body):
        if isinstance(node, (ast.Import, ast.ImportFrom)) or (
                isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)):
            continue
        key = defined(node) or ("expr", i)
        assert key not in out
        out[key] = node
    return out


def methods(src, name):
    klass = next(n for n in ast.parse(src).body if isinstance(n, ast.ClassDef) and n.name == name)
    return {n.name: n for n in klass.body if isinstance(n, ast.FunctionDef)}


def imported(module):
    return {n.module for n in ast.walk(ast.parse(target_text(module))) if isinstance(n, ast.ImportFrom)
            and n.module.startswith("codex_harness.")}


def test_the_two_modules_partition_m7_in_order_and_everything_but_the_named_rules_is_m7():
    ref, front, runner = statements(m7_text()), statements(target_text(FRONT)), statements(target_text(RUNNER))
    assert len(ref) == 14
    runner_keys = RUNNER_CONSTANTS | {("DeskRunner",)}
    moved = {MOVED_AHEAD}
    assert set(front) - {("__all__",)} == set(ref) - runner_keys - moved - {("__all__",)}
    assert set(runner) - {("__all__",)} == runner_keys
    for ours in (front, runner):
        assert [k for k in ours if k != ("__all__",)] == [k for k in ref if k in ours and k != ("__all__",)]  # M7 order
    for key, node in front.items():
        if key not in {("FrontDesk",), ("__all__",)}:
            assert ast.dump(node) == ast.dump(ref[key]), key
    for key, node in runner.items():
        if key not in {("DeskRunner",), ("__all__",)}:
            assert ast.dump(node) == ast.dump(ref[key]), key
    assert len(front) == 9 and len(runner) == 5


def test_only_the_named_methods_differ_from_m7():
    ref = m7_text()
    for module, name, rewritten, count in ((FRONT, "FrontDesk", ["__init__", "submit"], 16),
                                           (RUNNER, "DeskRunner", ["__init__", "_flush"], 15)):
        theirs, mine = methods(ref, name), methods(target_text(module), name)
        assert list(mine) == list(theirs) and len(theirs) == count
        assert [k for k in theirs if ast.dump(mine[k]) != ast.dump(theirs[k])] == rewritten


def test_rule_sites_pinned_by_name():
    m7, front, runner = m7_text(), target_text(FRONT), target_text(RUNNER)
    for old, new, count in (
            ('tx.put("outbox", message["message_id"], {"message": message, "sent": False})', "self.outbox.append(tx, message)", 1),
            ("token=lambda: uuid4().hex):", "token=lambda: uuid4().hex, *, outbox=None):", 1)):
        assert m7.count(old) == count and front.count(new) == count and old not in front, old
    assert "tx.put(\"outbox\"" not in front
    for old, new in (("desk: FrontDesk,", "desk: DeskQueue,"),
                     ("flush_outbox(self.service, self.bus,", "flush_outbox(self.service.flusher, self.bus,")):
        assert m7.count(old) == 1 and runner.count(new) == 1 and old not in runner, old
    assert "from codex_harness.coordination.application.local_cycle import flush_outbox" in runner


def test_imports_are_only_homes_each_context_may_use():
    assert imported(FRONT) == {"codex_harness.intake.domain.frontdesk", "codex_harness.kernel.errors",
                               "codex_harness.kernel.ids", "codex_harness.kernel.message"}
    assert imported(RUNNER) == {"codex_harness.coordination.application.local_cycle", "codex_harness.coordination.ports",
                                "codex_harness.intake.domain.frontdesk", "codex_harness.kernel.ids"}
    for module in (FRONT, RUNNER):
        assert "codex_harness.domain" not in target_text(module).replace("codex_harness.intake.domain", "")
        assert "outbox import" not in target_text(module)


def test_headers_name_context_layer_and_the_split():
    for module, context, owner in ((FRONT, "intake", "FrontDesk"), (RUNNER, "coordination", "DeskRunner")):
        head = target_text(module).split('"""')[1]
        assert f"Layer: application\nContext: {context}\n" in head and "Contracts: local-operations-desk-001" in head
        assert "SOURCE e38aa722" in head and "V16" in head and "frontdesk-move/transcribe.py" in head
        assert f"Entry points: {owner}" in head


def test_r_f2_conductor_and_lead_live_in_the_domain_and_are_re_exported():
    domain, front = importlib.import_module(DOMAIN), importlib.import_module(FRONT)
    assert (domain.CONDUCTOR, domain.LEAD) == ("conductor", "lead:frontdesk")
    assert front.CONDUCTOR is domain.CONDUCTOR and front.LEAD is domain.LEAD
    assert importlib.import_module(RUNNER).LEAD is domain.LEAD
    ref = statements(m7_text())[MOVED_AHEAD]
    assert ast.dump(statements(target_text(DOMAIN))[MOVED_AHEAD]) == ast.dump(ref)


def test_the_runner_constants_move_with_deskrunner():
    runner, front = importlib.import_module(RUNNER), importlib.import_module(FRONT)
    assert (runner.TASK_DEADLINE_SECONDS, runner.MAX_ATTEMPTS, runner.SUMMARY_TURNS) == (180, 1, 50)
    assert not any(hasattr(front, name) for name in ("TASK_DEADLINE_SECONDS", "MAX_ATTEMPTS", "SUMMARY_TURNS", "DeskRunner"))
    assert not any(hasattr(runner, name) for name in ("FrontDesk", "correlation_of", "message_id_of", "ACTION", "OBJECTIVE"))
    assert front.__all__ == ["ACTION", "BUCKET_EVENTS", "BUCKET_RECEIPTS", "BUCKET_REQUESTS", "BUCKET_SESSIONS", "CONDUCTOR",
                             "FrontDesk", "LEAD", "correlation_of", "message_id_of"]
    assert runner.__all__ == ["SUMMARY_TURNS", "DeskRunner"]
    assert (front.BUCKET_SESSIONS, front.BUCKET_REQUESTS, front.BUCKET_EVENTS, front.BUCKET_RECEIPTS) == DESK_BUCKETS


def _service(org=True):
    from codex_harness.routing.adapters.organization_source import packaged_organization
    from codex_harness.storage.adapters.memory_store import MemoryStore

    return SimpleNamespace(store=MemoryStore(), org=packaged_organization() if org else None)


def _session(desk):
    session_id = "123e4567-e89b-42d3-a456-426614174000"
    desk.create_session({"session_id": session_id, "title": "t"})
    return session_id


def _submission(session_id, request_id="223e4567-e89b-42d3-a456-426614174000"):
    return {"session_id": session_id, "request_id": request_id, "intent": "consult", "text": "hello"}


def test_r_f1_the_port_is_keyword_only_optional_and_checked_by_one_require_first_in_submit():
    front = importlib.import_module(FRONT)
    args = methods(target_text(FRONT), "FrontDesk")["__init__"].args
    assert [a.arg for a in args.args] == ["self", "service", "base_revision", "clock", "token"]
    assert [a.arg for a in args.kwonlyargs] == ["outbox"]
    assert [d.value for d in args.kw_defaults] == [None]
    submit = methods(target_text(FRONT), "FrontDesk")["submit"]
    requires = [n for n in ast.walk(submit) if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "require"]
    assert len(requires) == 1 and "self.outbox is not None" in ast.unparse(requires[0])
    first = [n for n in submit.body if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant))][0]
    assert isinstance(first, ast.Expr) and first.value is requires[0]  # the port is checked at first use, before any state
    assert front.FrontDesk(_service(), REVISION).outbox is None  # building the desk needs no port


def test_a_desk_without_the_outbox_port_refuses_at_first_use_and_writes_nothing():
    front = importlib.import_module(FRONT)
    service = _service()
    desk = front.FrontDesk(service, REVISION)
    session_id = _session(desk)
    with service.store.transaction() as tx:
        before = tx.records()
    with pytest.raises(ContractError, match="outbox port"):
        desk.submit(_submission(session_id))
    with service.store.transaction() as tx:
        assert tx.records() == before and tx.scan("desk_requests") == [] and tx.scan("outbox") == []
    assert desk.sessions()["sessions"][0]["request_count"] == 0  # other methods never need the port


def test_submit_commits_the_assignment_through_the_port_inside_the_users_transaction():
    front = importlib.import_module(FRONT)
    service, seen = _service(), []

    class Port:
        def append(self, tx, message):
            seen.append((tx, message))
            tx.put("outbox", message["message_id"], {"message": message, "sent": False})

    desk = front.FrontDesk(service, REVISION, outbox=Port())
    session_id = _session(desk)
    request_id = "223e4567-e89b-42d3-a456-426614174000"
    accepted = desk.submit(_submission(session_id, request_id))
    assert accepted["cached"] is False and accepted["request"]["status"] == "queued"
    (tx, message), = seen
    assert message["message_id"] == "desk-" + request_id and message["who"]["recipient"] == "lead:frontdesk"
    assert message["who"]["sender"] == "conductor" and message["correlation_id"] == "frontdesk:" + request_id
    with service.store.transaction() as read:
        assert read.get("outbox", "desk-" + request_id) == {"message": message, "sent": False}
        assert read.get("desk_requests", request_id)["message_sha256"]
    replay = desk.submit(_submission(session_id, request_id))
    assert replay["cached"] is True and len(seen) == 1  # a replay never reaches the port again


def test_the_real_outbox_owner_satisfies_the_intake_port():
    from codex_harness.coordination.application.outbox import Outbox
    from codex_harness.intake.ports import OutboxAppend

    declared = {n: f for n, f in vars(OutboxAppend).items() if inspect.isfunction(f) and not n.startswith("_")}
    assert sorted(declared) == ["append"]
    assert list(inspect.signature(declared["append"]).parameters) == list(inspect.signature(Outbox.append).parameters)
    front = importlib.import_module(FRONT)
    service = _service()
    desk = front.FrontDesk(service, REVISION, outbox=Outbox())
    desk.submit(_submission(_session(desk)))
    with service.store.transaction() as tx:
        (row,) = tx.scan("outbox")
    assert row["sent"] is False and row["message"]["what"]["action"] == "frontdesk"


def test_r_d1_the_desk_queue_holds_exactly_the_methods_deskrunner_calls():
    from codex_harness.coordination import ports

    runner = next(n for n in ast.parse(target_text(RUNNER)).body if isinstance(n, ast.ClassDef) and n.name == "DeskRunner")
    calls = sorted({n.attr for n in ast.walk(runner) if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Attribute)
                    and n.value.attr == "desk" and isinstance(n.value.value, ast.Name) and n.value.value.id == "self"})
    declared = {n: f for n, f in vars(ports.DeskQueue).items() if inspect.isfunction(f) and not n.startswith("_")}
    assert calls == DESK_QUEUE == sorted(declared)
    front = importlib.import_module(FRONT)
    for name, fn in declared.items():  # FrontDesk satisfies the shape: same parameter names, kinds and defaults
        mine = [(p.name, p.kind, p.default) for p in inspect.signature(getattr(front.FrontDesk, name)).parameters.values()]
        assert mine == [(p.name, p.kind, p.default) for p in inspect.signature(fn).parameters.values()], name
    init = methods(target_text(RUNNER), "DeskRunner")["__init__"]
    annotations = {a.arg: ast.unparse(a.annotation) for a in init.args.args if a.annotation is not None}
    assert annotations["desk"] == "DeskQueue"
    assert not [m for m in imported(RUNNER) if m.startswith("codex_harness.intake.application")]  # FrontDesk is never imported


def test_r_d2_flush_goes_through_the_services_flusher(monkeypatch):
    from codex_harness.coordination.application import local_cycle

    runner_module = importlib.import_module(RUNNER)
    flusher, bus, observer, calls = object(), object(), object(), []

    def fake(flusher_arg, bus_arg, observer_arg=None, correlation_id=None):
        calls.append((flusher_arg, bus_arg, observer_arg, correlation_id))
        return {"complete": True}

    monkeypatch.setattr(local_cycle, "flush_outbox", fake)
    service = SimpleNamespace(flusher=flusher)
    runner = runner_module.DeskRunner(service, desk=None, bus=bus, observer=observer)
    assert runner._flush("frontdesk:x") == {"complete": True}
    assert calls == [(flusher, bus, observer, "frontdesk:x")]
    assert runner_module.DeskRunner(service, desk=None)._flush("frontdesk:x") is None and len(calls) == 1


def test_the_four_desk_buckets_are_intakes_alone_and_only_the_front_desk_module_writes_them():
    from codex_harness.intake import ports as intake_ports

    assert all(intake_ports.OWNED_BUCKETS.count(b) == 1 for b in DESK_BUCKETS)
    assert intake_ports.OWNED_BUCKETS[:4] == ("portfolio_bindings", "portfolio_acceptances", "portfolio_investigations",
                                              "portfolio_followups")
    for path in sorted(SRC.glob("*/ports.py")):
        if path.parent.name != "intake":
            owned = getattr(importlib.import_module(f"codex_harness.{path.parent.name}.ports"), "OWNED_BUCKETS", ())
            assert not set(DESK_BUCKETS) & set(owned), path
    def literals(path):  # the bucket names as code literals (the module docstrings only talk about them)
        tree = ast.parse(path.read_text())
        docs = {id(tree.body[0].value)} if tree.body and isinstance(tree.body[0], ast.Expr) else set()
        return {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)
                and id(n) not in docs} & set(DESK_BUCKETS)

    mentions = sorted(p.relative_to(SRC).as_posix() for p in SRC.rglob("*.py") if literals(p))
    assert mentions == ["intake/application/frontdesk.py", "intake/ports.py"]
    # the coordination runner never writes a desk bucket (it goes through the DeskQueue port) and writes only `tasks`
    puts = [ast.unparse(n.args[0]) for n in ast.walk(ast.parse(target_text(RUNNER))) if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute) and n.func.attr == "put" and n.args]
    assert puts == ["'tasks'"]


def test_the_runner_and_the_desk_run_a_turn_over_literals():
    """One consult turn on the TARGET with the real outbox owner, a stub bus/executor: the answer binds to the request."""
    from codex_harness.coordination.application.desk_runner import DeskRunner

    front = importlib.import_module(FRONT)
    from codex_harness.coordination.application.outbox import Outbox

    service = _service()
    service.flusher = SimpleNamespace(flush=lambda bus, **kw: {"complete": True, "remaining": 0})
    desk = front.FrontDesk(service, REVISION, outbox=Outbox())
    request_id = desk.submit(_submission(_session(desk)))["request"]["id"]
    runner = DeskRunner(service, desk)  # no bus, no workflow, no executor: nothing is delivered or executed
    assert runner.recover() == {"finalized": [], "needs_reconciliation": []}
    claimed = desk.claim_next()
    assert claimed["id"] == request_id and claimed["status"] == "dispatching"
    assert runner._classify_result(claimed, None) == {"status": "failed", "reason_code": "no_execution_claimed"}
    assert runner.step() == {"action": "idle"}
    assert runner.recover() == {"finalized": [], "needs_reconciliation": [request_id]}
    assert desk.request(request_id)["status"] == "needs_reconciliation"
    assert desk.request(request_id)["reason_code"] == "interrupted_owner"
