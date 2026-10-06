"""S9 batch L2-B6: the source collectors (U7) move out of M7 `adapters/monitoring.py` into `observation.adapters.collectors` with the OWNER-DECISIONS-S9 D1.1 seams.

The module now holds EVERY M7 top-level definition in M7's order. U6 (L2-B5) is unchanged; U7's `docker_stats`, `docker_facts`, `redis_facts`, the eight `*_facts`,
`LANE_SNAPSHOT_BEGIN`, `LaneSnapshotStore`, `LaneSnapshotTransaction`, `lane_resolver`, `lane_session_facts`, `discovery_pressure_facts` and `collect` are M7's except R-u1..R-u6
(every port keyword-only with default None, refused through `require` at first use; `collect` is given `ports=CollectorPorts(...)`). M7 is read only as text through
`git show e38aa722:...` and compared by AST, never imported: both packages are named `codex_harness`. Behaviour is compared by the recorded `observation.collectors_sources`
golden (target-equal); this file pins what a golden cannot: the AST against M7 modulo D1.1, the order, the import homes, the refusals (no effect before the refusal), the
`CollectorPorts` fields against what `collect` reads, the call shapes, the six uninjected clock calls, no new spawn site and the layer rules.

M7 tests this batch does NOT port yet (the S9 ported suite is a later step; the real-PostgreSQL lane-store case is the S9 units/.pg step): from `test_monitoring.py`
`test_read_only_store_and_reader_refuse_writes_while_collection_works`, `test_container_scope_unset_keeps_compose_and_named_mode_is_exact`,
`test_collect_keeps_source_failures_independent`, `test_backlog_source_shows_selection_progress_without_ticking_or_leaking_manifests`,
`test_web_json_route_preserves_the_backlog_envelope` and `test_collector_entrypoint_is_read_only_and_needs_no_executor` (the monitor CLI is S10);
from `test_monitoring_lane_sessions.py` every PostgreSQL-free and `.pg` test over `lane_session_facts` and `LaneSnapshotStore` (the lane fixtures over real lane stores and the
`.pg` snapshot-isolation cases); from `test_monitoring_activity.py` `test_one_unreadable_lane_root_leaves_the_other_lane_and_every_session_fact_intact`,
`test_a_bad_ref_and_a_bad_receipt_between_good_ones_keep_the_lane_and_its_session_facts` and
`test_a_row_whose_activity_cannot_be_projected_is_unavailable_and_keeps_its_session_facts`; and the owner-class source tests of `test_fleet.py`, `test_portfolio.py`,
`test_research_program.py`, `test_worker_sessions.py`, `test_discovery_pressure.py` and `test_host_delivery_lane_routing.py` (they belong to their owners' families; here the
wrapper-level cases are in the golden).
"""

from __future__ import annotations

import ast
import copy
import dataclasses
import difflib
import inspect
import re
import subprocess
from pathlib import Path
from types import SimpleNamespace

import import_rules
import pytest
from _layout import REPO, TARGET

from codex_harness.coordination.domain import fleet as coordination_fleet
from codex_harness.kernel.errors import ContractError
from codex_harness.observation.adapters import collectors, monitoring_observations
from codex_harness.observation.application import monitoring as application_monitoring
from codex_harness.observation.ports import CollectorPorts
from codex_harness.storage.adapters.memory_store import MemoryStore

SOURCE = "e38aa722"
M7_MON = "src/codex_harness/adapters/monitoring.py"
TEXT = Path(collectors.__file__).read_text(encoding="utf-8")
U6_NAMES = ["CONTAINER_NAME", "MAX_CONTAINERS", "safe_text", "ReadOnlyTransaction", "ReadOnlyStore", "ReadOnlyArtifacts", "ReadOnlyService", "read_only",
            "container_scope", "parse_observed", "persisted_measurements", "DatabaseFacts", "audit_progress",
            "LANE_SESSIONS_SCHEMA", "LANE_SESSION_LIMIT", "ACTIVE_EXECUTION", "UNINSTRUMENTED",
            "ACTIVITY_REFS", "ACTIVITY_BODY_BYTES", "RECENT_TERMINAL_SECONDS", "TERMINAL_EXECUTION", "ARTIFACT_REF", "CLAUDE_LABELS", "CODEX_LABELS", "PLAIN_STATUSES",
            "ENVELOPE_KEYS", "_optional_strings", "ArtifactReader", "_strict_json", "_epoch_ms", "project_receipt", "_aware", "execution_activity", "COMPACT_ONLY",
            "_failed_entry", "_compact_selected", "_compact_activity", "lane_artifact_resolver", "_execution_view", "lane_view", "scope_label"]
U7_NAMES = ["docker_stats", "docker_facts", "redis_facts", "fleet_facts", "research_program_facts", "portfolio_facts", "fleet_backlog_facts", "host_delivery_facts",
            "worker_session_facts", "continuation_facts", "LANE_SNAPSHOT_BEGIN", "LaneSnapshotStore", "LaneSnapshotTransaction", "lane_resolver", "lane_session_facts",
            "discovery_pressure_facts", "collect"]
# wrapper -> (its D1.1 label, the M7 owner call it replaced, the CollectorPorts field `collect` passes it)
WRAPPERS = {"fleet_facts": ("fleet", "Fleet(store).status()", "fleet"),
            "research_program_facts": ("research_program", "ResearchProgram(store).monitor()", "research_program"),
            "portfolio_facts": ("portfolio", "portfolio(store).status()", "portfolio"),
            "fleet_backlog_facts": ("fleet_backlog", "FleetBacklog(store).status()", "fleet_backlog"),
            "host_delivery_facts": ("host_delivery", "HostDelivery(store).status()", "host_delivery"),
            "worker_session_facts": ("worker_session", "WorkerSessions(store, None).status()", "worker_session"),
            "continuation_facts": ("continuation", "Continuation(store).status()", "continuation"),
            "discovery_pressure_facts": ("discovery_pressure", "status(store)", "discovery_pressure")}
KWONLY = {"docker_stats": ["run_process"], "docker_facts": ["run_process"], "redis_facts": ["bus_factory"], "lane_resolver": ["dsn_for"],
          "lane_session_facts": ["registered"], "collect": ["ports"], **{name: ["project"] for name in WRAPPERS}}
FORBIDDEN_HOMES = ("codex_harness.adapters", "codex_harness.domain", "codex_harness.application", "codex_harness.ports", "codex_harness.entry", "codex_harness.intake",
                   "codex_harness.evidence", "codex_harness.delivery")


def show(rev, path):
    return subprocess.run(["git", "-C", str(REPO), "show", f"{rev}:{path}"], check=True, capture_output=True, text=True).stdout


def names_of(node):
    if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
        return (node.name,)
    if isinstance(node, ast.Assign):
        return tuple(n.id for t in node.targets for n in ast.walk(t) if isinstance(n, ast.Name))
    return ()


def statements(src):
    out = {}
    for node in ast.parse(src).body:
        if names_of(node):
            out[names_of(node)[0]] = node
    return out


def from_imports(tree):
    return {n.module: sorted(a.name for a in n.names) for n in tree.body if isinstance(n, ast.ImportFrom)}


def is_call_to(node, name):
    return isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == name


OURS, THEIRS = statements(TEXT), statements(show(SOURCE, M7_MON))


class InverseOfD11(ast.NodeTransformer):
    """The inverse of R-c1 and R-u1..R-u6 on a target function's AST (the eight wrappers are checked by their own shape, below)."""

    def __init__(self, fn):
        self.fn, self.removed, self.dropped = fn, [], []

    def visit_Assign(self, node):
        self.generic_visit(node)
        if len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) and node.targets[0].id == "SESSIONS" and self.fn == "lane_view":
            return ast.parse("from codex_harness.application.worker_sessions import BUCKET as SESSIONS").body[0]
        return node

    def visit_ImportFrom(self, node):
        if node.module == "codex_harness.execution.domain.worker_sessions":
            node.module = "codex_harness.domain.worker_sessions"
        return node

    def visit_Expr(self, node):
        if is_call_to(node.value, "require"):
            self.removed.append((ast.unparse(node.value.args[0]), ast.literal_eval(node.value.args[1])))
            return None
        return node

    def visit_Call(self, node):
        self.generic_visit(node)
        if is_call_to(node, "bus_factory"):
            return ast.Call(func=ast.Name("RedisBus", ast.Load()), args=node.args, keywords=node.keywords)
        if is_call_to(node, "dsn_for"):
            return ast.Call(func=ast.Name("lane_dsn", ast.Load()), args=node.args, keywords=node.keywords)
        if is_call_to(node, "registered"):
            return ast.parse("Fleet(store).registered()", mode="eval").body
        kept = []
        for kw in node.keywords:
            if kw.arg in ("run_process", "bus_factory", "project", "registered"):
                self.dropped.append((node.func.id, kw.arg, ast.unparse(kw.value)))
            else:
                kept.append(kw)
        node.keywords = kept
        return node


def inverse(name):
    node = copy.deepcopy(OURS[name])
    walker = InverseOfD11(name)
    assert [a.arg for a in node.args.kwonlyargs] == KWONLY.get(name, []) or name == "lane_view"
    assert all(isinstance(d, ast.Constant) and d.value is None for d in node.args.kw_defaults)
    node.args.kwonlyargs, node.args.kw_defaults = [], []
    return walker.visit(node), walker


# ---- the statements ----------------------------------------------------------------------------

def test_the_module_holds_every_m7_definition_in_m7s_order():
    assert list(OURS) == list(THEIRS)
    assert [n for n in THEIRS if n in U6_NAMES] == U6_NAMES and [n for n in THEIRS if n in U7_NAMES] == U7_NAMES
    assert len(THEIRS) == len(U6_NAMES) + len(U7_NAMES)
    assert {n for n in dir(collectors) if not n.startswith("__")} >= set(U6_NAMES) | set(U7_NAMES)


def test_u6_is_unchanged_from_the_previous_batch_modulo_r_c1():
    changed = [n for n in U6_NAMES if ast.dump(OURS[n]) != ast.dump(THEIRS[n])]
    assert changed == ["lane_view"]
    back, walker = inverse("lane_view")
    assert ast.dump(back) == ast.dump(THEIRS["lane_view"])
    assert walker.removed == [] and walker.dropped == []


def test_unchanged_u7_statements_are_m7s_and_the_changed_ones_differ_by_d1_1_alone():
    changed = [n for n in U7_NAMES if ast.dump(OURS[n]) != ast.dump(THEIRS[n])]
    assert changed == [n for n in U7_NAMES if n not in ("LANE_SNAPSHOT_BEGIN", "LaneSnapshotStore", "LaneSnapshotTransaction")]
    assert [n for n in U7_NAMES if n not in changed] == ["LANE_SNAPSHOT_BEGIN", "LaneSnapshotStore", "LaneSnapshotTransaction"]
    for name in changed:
        if name in WRAPPERS:
            continue
        back, _ = inverse(name)
        ast.fix_missing_locations(back)
        # lane_resolver's guard replaces M7's lazy `lane_dsn` import: put the import back where the guard stood
        if name == "lane_resolver":
            doc = 1 if isinstance(THEIRS[name].body[0], ast.Expr) else 0
            back.body.insert(doc, THEIRS[name].body[doc])
        assert ast.dump(back) == ast.dump(THEIRS[name]), name


def test_each_wrapper_is_the_guard_and_the_port_call_where_m7_had_the_lazy_import_and_the_owner_call():
    for name, (label, owner_call, _) in WRAPPERS.items():
        ours, theirs = OURS[name].body, THEIRS[name].body
        assert ast.dump(ours[0]) == ast.dump(theirs[0])  # the contract docstring is verbatim
        assert len(ours) == 3 and len(theirs) == 3 or (name == "fleet_facts" and len(theirs) == 2 and len(ours) == 3)
        assert [a.arg for a in OURS[name].args.args] == ["store"] and [a.arg for a in OURS[name].args.kwonlyargs] == ["project"]
        assert ast.unparse(ours[1]) == f"require(project is not None, '{label} projection is not wired')"
        assert ast.unparse(ours[2]) == "return project(store)"
        assert ast.unparse(theirs[-1]) == f"return {owner_call}"
        if name != "fleet_facts":  # `fleet_facts` used the module-level `Fleet`; the rest imported their owner lazily
            assert isinstance(theirs[1], ast.ImportFrom) and theirs[1].module.startswith("codex_harness.") and "." in theirs[1].module


def test_every_changed_line_is_a_d1_1_or_r_c1_line_and_nothing_else_moved():
    lines = show(SOURCE, M7_MON).split("\n")
    theirs = lines[31:1025]
    ours = TEXT[TEXT.index("CONTAINER_NAME = "):].rstrip("\n").split("\n")
    added, removed = [], []
    for tag, a0, a1, b0, b1 in difflib.SequenceMatcher(None, theirs, ours, autojunk=False).get_opcodes():
        if tag != "equal":
            removed += theirs[a0:a1]
            added += ours[b0:b1]
    allowed_added = re.compile(r"^\s*(require\(|def (docker_stats|docker_facts|redis_facts|\w+_facts|lane_resolver|lane_session_facts)\(.*\*, \w+=None\)|"
                               r"lane_artifacts=None, \*, ports=None\):|bus = bus_factory\(url\)|return project\(store\)|SESSIONS = 'worker_sessions'|"
                               r"from codex_harness\.execution\.domain\.worker_sessions import status_view|lookup = docker_stats\(.*run_process=run_process\)|"
                               r"cache\[key\] = ReadOnlyStore\(store_factory\(dsn_for\(|lanes = registered\(store\)|'(docker|redis|\w+)': lambda: \w+\(.*(ports\.\w+)\)[,}]?$|"
                               r"jobs\['lane_sessions'\] = lambda: lane_session_facts\(.*registered=ports\.registered\))")
    allowed_removed = re.compile(r"^\s*(def (docker_stats|docker_facts|redis_facts|\w+_facts|lane_resolver|lane_session_facts)\(\w+(, \w+(=None)?)*\):|lane_artifacts=None\):|"
                                 r"bus = RedisBus\(url\)|return (Fleet|ResearchProgram|portfolio|FleetBacklog|HostDelivery|WorkerSessions|Continuation)\(store.*\)\.\w+\(\)|"
                                 r"return status\(store\)|from codex_harness\.(application|adapters|domain)\.\w+ import .*|lookup = docker_stats\(.*\)|"
                                 r"cache\[key\] = ReadOnlyStore\(store_factory\(lane_dsn\(|lanes = Fleet\(store\)\.registered\(\)\['config'\]\['lanes'\]|"
                                 r"'(docker|redis|\w+)': lambda: \w+\(.*\)[,}]?$|jobs\['lane_sessions'\] = lambda: lane_session_facts\(.*\))")
    assert [ln for ln in added if not allowed_added.match(ln)] == []
    assert [ln for ln in removed if not allowed_removed.match(ln)] == []
    # exactly the guards D1.1 introduces: docker_stats 1, docker_facts 2 (one per run_process call), redis_facts 1, the eight wrappers, lane_resolver, lane_session_facts, collect
    guards = [ln.strip() for ln in ours if ln.lstrip().startswith("require(")]
    assert len(guards) == 15 and len(set(guards)) == 13  # `run_process is not wired` is three guards: docker_stats and the two docker_facts branches
    assert sum("run_process is not wired" in ln for ln in guards) == 3
    assert [ln for ln in added if ln.lstrip().startswith("require(")] == [ln for ln in ours if ln.lstrip().startswith("require(")]


# ---- the header ---------------------------------------------------------------------------------

def test_the_header_keeps_m7s_docstring_first_and_names_every_collector():
    doc = ast.get_docstring(ast.parse(TEXT))
    assert doc.startswith(ast.get_docstring(ast.parse(show(SOURCE, M7_MON))) + "\n\nLayer: adapters\nContext: observation\n")
    for field in ("Owns:", "Does not own:", "Entry points:", "Contracts: INV-OBSERVATION-001", "Moved from M7", SOURCE, "R-c0", "R-c1", "R-u1..R-u6", "R-ch", "D1.1"):
        assert field in doc, field
    entry_points = doc.split("Entry points:")[1].split("\n")[0]
    for name in U6_NAMES[:0] + U7_NAMES + ["ReadOnlyStore", "DatabaseFacts", "lane_view", "scope_label"]:
        assert name in entry_points, name


# ---- the import homes ---------------------------------------------------------------------------

def test_the_import_homes_resolve_in_the_target_alone_and_none_is_a_forbidden_one():
    tree = ast.parse(TEXT)
    assert from_imports(tree) == {
        "collections": ["Counter"], "concurrent.futures": ["ThreadPoolExecutor"], "contextlib": ["contextmanager"], "dataclasses": ["asdict"], "datetime": ["datetime", "timezone"],
        "pathlib": ["Path"], "codex_harness.coordination.domain.fleet": ["FleetRefused"],
        "codex_harness.execution.domain.progress_activity": ["BUILTIN_TOOLS", "CODEX_ITEM_TYPES", "fixed_completed_status", "fixed_completed_type", "fixed_last_event",
                                                             "validate_receipt"],
        "codex_harness.kernel.errors": ["ContractError", "require"],
        "codex_harness.observation.adapters.monitoring_observations": ["observation_facts"],
        "codex_harness.observation.application.monitoring": ["Monitoring"], "codex_harness.research.domain.council": ["TASK_STATUSES"]}
    assert sorted(a.name for n in tree.body if isinstance(n, ast.Import) for a in n.names) == ["json", "re"]
    modules = [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
    assert not [m for m in modules if m.startswith(FORBIDDEN_HOMES)]
    assert not [m for m in modules if "fleet_runtime" in m or "application" in m.split(".")[:2]]
    imported = {a.asname or a.name for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom)) for a in n.names}
    assert not {"RedisBus", "run_process", "Fleet", "lane_dsn", "ResearchProgram", "WorkerSessions", "Continuation", "FleetBacklog", "HostDelivery", "portfolio",
                "status"} & imported
    used = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    assert not {"RedisBus", "Fleet", "lane_dsn"} & used
    lazy = sorted(n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n not in tree.body)
    assert lazy == ["codex_harness.execution.domain.worker_sessions"]
    lazy_plain = sorted(a.name for n in ast.walk(tree) if isinstance(n, ast.Import) and n not in tree.body for a in n.names)
    assert lazy_plain == ["hashlib", "os", "psycopg", "stat"]
    assert collectors.FleetRefused is coordination_fleet.FleetRefused and collectors.Monitoring is application_monitoring.Monitoring
    assert collectors.observation_facts is monitoring_observations.observation_facts and collectors.ContractError is ContractError


# ---- each unwired port is refused at first use, with no effect ----------------------------------

class Untouched:
    """Any use at all is a failure: a refusal must come before the store, the resolver or a process is touched."""

    def __getattr__(self, name):
        raise AssertionError(f"touched {name} before the refusal")

    def __call__(self, *args, **kwargs):
        raise AssertionError("called before the refusal")


class Recorder:
    def __init__(self):
        self.calls = []

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        raise AssertionError("an unwired port must never reach its collaborator")


def test_an_unwired_run_process_is_refused_at_the_first_call_and_the_empty_names_return_stays_first():
    assert collectors.docker_stats([]) == {} and collectors.docker_stats(None) == {}
    for call in (lambda: collectors.docker_stats(["c1"]), lambda: collectors.docker_facts("/zeus-fixture/repo"),
                 lambda: collectors.docker_facts("/zeus-fixture/repo", ["c1"]), lambda: collectors.docker_facts("/zeus-fixture/repo", [])):
        with pytest.raises(ContractError, match="run_process is not wired"):
            call()


def test_run_process_is_called_only_by_the_wired_port_with_m7s_arguments():
    seen = []

    def run(argv, cwd=None, timeout=None, **kwargs):
        seen.append((list(argv), cwd, timeout, kwargs))
        if argv[:2] == ["docker", "ps"]:
            return SimpleNamespace(returncode=0, stdout='{"Names": "c1", "State": "exited", "Image": "img"}')
        return SimpleNamespace(returncode=0, stdout="")
    assert collectors.docker_facts("/zeus-fixture/repo", run_process=run) == []
    assert collectors.docker_facts("/zeus-fixture/repo", ["c1"], run_process=run) == [{"service": "c1", "name": "c1", "state": "exited", "image": "img", "cpu": None,
                                                                                         "memory": None}]
    assert seen == [(["docker", "compose", "ps", "--all", "--format", "json"], "/zeus-fixture/repo", 15, {}),
                    (["docker", "ps", "--all", "--format", "{{json .}}", "--filter", "name=c1"], None, 15, {})]


def test_an_unwired_bus_factory_is_refused_before_any_bus_is_built():
    with pytest.raises(ContractError, match="bus_factory is not wired"):
        collectors.redis_facts("redis-fixture://a", ["conductor"])
    recorder = Recorder()
    with pytest.raises(AssertionError):  # wired: it IS called, with the url alone
        collectors.redis_facts("redis-fixture://a", ["conductor"], bus_factory=recorder)
    assert recorder.calls == [(("redis-fixture://a",), {})]


@pytest.mark.parametrize("name", list(WRAPPERS))
def test_an_unwired_projection_is_refused_before_the_store_is_read(name):
    label = WRAPPERS[name][0]
    with pytest.raises(ContractError, match=f"{label} projection is not wired"):
        getattr(collectors, name)(Untouched())
    store, seen = MemoryStore(), []
    assert getattr(collectors, name)(store, project=lambda s: seen.append(s) or {"ok": name}) == {"ok": name} and seen == [store]


def test_an_unwired_dsn_for_is_refused_when_the_resolver_is_built_not_when_a_lane_is_resolved():
    with pytest.raises(ContractError, match="dsn_for is not wired"):
        collectors.lane_resolver("host-dsn-fixture")
    with pytest.raises(ContractError, match="dsn_for is not wired"):
        collectors.lane_resolver("host-dsn-fixture", lambda dsn, schema: Untouched())
    asked = []
    resolve = collectors.lane_resolver("host", lambda dsn, schema: MemoryStore(), dsn_for=lambda host, schema: asked.append((host, schema)) or "dsn")
    resolve({"id": "a", "schema": "lane_a"})
    resolve({"id": "a", "schema": "lane_a"})
    assert asked == [("host", "lane_a")]


def test_an_unwired_registered_is_refused_before_the_store_or_a_lane_is_touched():
    with pytest.raises(ContractError, match="registered is not wired"):
        collectors.lane_session_facts(Untouched(), Untouched())
    seen = []
    result = collectors.lane_session_facts(MemoryStore(), Untouched(), registered=lambda s: seen.append(s) or {"config": {"lanes": []}})
    assert result["registered"] is True and result["lanes"] == [] and len(seen) == 1


def test_collect_without_ports_is_refused_before_any_thread_or_source_starts(monkeypatch):
    class NoPool:
        def __init__(self, *args, **kwargs):
            raise AssertionError("a thread pool was started")
    monkeypatch.setattr(collectors, "ThreadPoolExecutor", NoPool)
    with pytest.raises(ContractError, match="collector ports are not wired"):
        collectors.collect(Untouched(), Untouched(), "/zeus-fixture/repo", "redis-fixture://a")
    with pytest.raises(ContractError, match="collector ports are not wired"):
        collectors.collect(Untouched(), None, "/zeus-fixture/repo", "redis-fixture://a", ["c"], "scope", "/runtime", lambda lane: None, lambda lane: None)


def collector_ports(**override):
    log = {}

    def recording(name, result):
        def call(*args, **kwargs):
            log.setdefault(name, []).append((args, kwargs))
            return result
        return call
    bus = SimpleNamespace(client=SimpleNamespace(connection_pool=SimpleNamespace(connection_kwargs={})), stream=lambda agent: agent)
    fields = {"run_process": recording("run_process", SimpleNamespace(returncode=0, stdout="")), "bus_factory": recording("bus_factory", bus),
              "registered": recording("registered", {"config": {"lanes": []}})}
    fields.update({name: recording(name, {"port": name}) for name in ("fleet", "research_program", "portfolio", "fleet_backlog", "host_delivery", "worker_session",
                                                                        "continuation", "discovery_pressure")})
    fields.update(override)
    assert set(fields) == {f.name for f in dataclasses.fields(CollectorPorts)}
    return CollectorPorts(**fields), log


def test_collect_passes_each_job_its_own_port_and_the_registered_port_only_with_lanes():
    ports, log = collector_ports()
    service, _ = collectors.read_only(SimpleNamespace(store=MemoryStore(), org=SimpleNamespace(agents={})), None)
    snapshot = collectors.collect(service, None, "/zeus-fixture/repo", "redis-fixture://a", ports=ports, lanes=lambda lane: service.store)
    assert list(snapshot["sources"]) == ["database", "docker", "redis", "fleet", "research_programs", "portfolio", "fleet_backlog", "host_delivery", "worker_sessions",
                                         "continuation", "discovery_pressure", "lane_sessions"]
    assert {name: env["status"] for name, env in snapshot["sources"].items()} == {name: "ok" for name in snapshot["sources"]}
    assert {name: len(calls) for name, calls in log.items()} == {"run_process": 1, "bus_factory": 1, "fleet": 1, "research_program": 1, "portfolio": 1, "fleet_backlog": 1,
                                                                  "host_delivery": 1, "worker_session": 1, "continuation": 1, "discovery_pressure": 1, "registered": 1}
    assert log["run_process"][0][0][0][:3] == ["docker", "compose", "ps"] and log["bus_factory"][0] == (("redis-fixture://a",), {})
    for name in ("fleet", "research_program", "portfolio", "fleet_backlog", "host_delivery", "worker_session", "continuation", "discovery_pressure", "registered"):
        (args, kwargs), = log[name]
        assert kwargs == {} and len(args) == 1 and type(args[0]).__name__ == "ReadOnlyStore", name
    assert snapshot["sources"]["fleet"]["data"] == {"port": "fleet"} and snapshot["sources"]["discovery_pressure"]["data"] == {"port": "discovery_pressure"}
    without, log2 = collector_ports()
    collectors.collect(service, None, "/zeus-fixture/repo", "redis-fixture://a", ports=without)
    assert "registered" not in log2


def test_a_failing_port_is_one_unavailable_source_and_never_the_whole_collect():
    def fails(store):
        raise RuntimeError("injected projection failure")
    ports, _ = collector_ports(fleet=fails)
    service, _ = collectors.read_only(SimpleNamespace(store=MemoryStore(), org=SimpleNamespace(agents={})), None)
    sources = collectors.collect(service, None, "/zeus-fixture/repo", "redis-fixture://a", ports=ports)["sources"]
    assert (sources["fleet"]["status"], sources["fleet"]["error"], sources["fleet"]["data"]) == ("unavailable", "RuntimeError", None)
    assert sources["portfolio"]["status"] == "ok" and sources["database"]["status"] == "ok"


# ---- CollectorPorts against what `collect` reads ------------------------------------------------

def test_collector_ports_fields_equal_the_names_collect_and_its_jobs_use():
    collect = next(n for n in ast.parse(TEXT).body if isinstance(n, ast.FunctionDef) and n.name == "collect")
    used = {n.attr for n in ast.walk(collect) if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == "ports"}
    fields = [f.name for f in dataclasses.fields(CollectorPorts)]
    assert used == set(fields) and len(fields) == 11
    triples = sorted((n.func.id, kw.arg, kw.value.attr) for n in ast.walk(collect) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                     for kw in n.keywords if isinstance(kw.value, ast.Attribute) and isinstance(kw.value.value, ast.Name) and kw.value.value.id == "ports")
    assert triples == sorted([("docker_facts", "run_process", "run_process"), ("redis_facts", "bus_factory", "bus_factory"), ("lane_session_facts", "registered", "registered"),
                              *[(name, "project", port) for name, (_, _, port) in WRAPPERS.items()]])
    assert dataclasses.is_dataclass(CollectorPorts) and CollectorPorts.__dataclass_params__.frozen


# ---- call shapes ---------------------------------------------------------------------------------

def test_positional_shapes_are_m7s_and_every_port_is_keyword_only_with_default_none():
    expected = {"docker_stats": ["names"], "docker_facts": ["repository", "containers"], "redis_facts": ["url", "agents"], "lane_resolver": ["host_dsn", "store_factory"],
                "lane_session_facts": ["store", "resolve", "artifacts", "now"],
                "collect": ["service", "artifacts", "repository", "redis_url", "containers", "scope", "runtime", "lanes", "lane_artifacts"],
                **{name: ["store"] for name in WRAPPERS}}
    for name, positional in expected.items():
        signature = inspect.signature(getattr(collectors, name))
        params = list(signature.parameters.values())
        assert [p.name for p in params if p.kind is p.POSITIONAL_OR_KEYWORD] == positional, name
        keyword_only = [p for p in params if p.kind is p.KEYWORD_ONLY]
        assert [p.name for p in keyword_only] == KWONLY[name] and all(p.default is None for p in keyword_only), name
        assert len(params) == len(positional) + len(keyword_only), name
    old = {n: [a.arg for a in THEIRS[n].args.args] for n in expected}
    assert old == expected
    assert {n: [d.value for d in THEIRS[n].args.defaults] for n in ("docker_facts", "lane_resolver", "lane_session_facts", "collect")} == {
        "docker_facts": [None], "lane_resolver": [None], "lane_session_facts": [None, None], "collect": [None] * 5}
    assert inspect.signature(collectors.LaneSnapshotStore.__init__).parameters["statement_timeout_ms"].default == 5000
    assert collectors.LANE_SNAPSHOT_BEGIN == "BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY"


def test_the_clock_calls_stay_the_six_uninjected_datetime_now_calls_of_m7():
    def clock_calls(src):
        tree = ast.parse(src)
        top = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
        out = []
        for name, fn in top.items():
            out += [name for n in ast.walk(fn) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "now"]
        return sorted(out)
    assert clock_calls(TEXT) == clock_calls(show(SOURCE, M7_MON)) == sorted(["lane_view", "persisted_measurements", "lane_session_facts", "collect", "collect", "collect"])
    assert "utcnow" not in TEXT and "Clock" not in TEXT


# ---- no new spawn site, the layer rules -----------------------------------------------------------

def test_no_new_spawn_site_the_only_pool_is_m7s_one_inside_collect():
    tree = ast.parse(TEXT)
    for banned in ("subprocess", "Popen", "multiprocessing", "os.system", "os.popen", "os.exec", "os.spawn", "os.fork"):
        assert banned not in TEXT, banned
    imported = {n.module if isinstance(n, ast.ImportFrom) else a.name for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom)) for a in
                (n.names if isinstance(n, ast.Import) else [None])}
    assert not imported & {"subprocess", "multiprocessing", "threading", "socket", "asyncio", "redis"}
    spawn = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and isinstance(n.func.value, ast.Name)
             and n.func.value.id == "os" and re.match(r"(exec|spawn|posix_spawn|system|popen|fork)", n.func.attr)]
    assert spawn == []
    pools = [(f.name, n.lineno) for f in tree.body if isinstance(f, ast.FunctionDef) for n in ast.walk(f) if is_call_to(n, "ThreadPoolExecutor")]
    assert [p[0] for p in pools] == ["collect"]
    theirs = [f.name for f in ast.parse(show(SOURCE, M7_MON)).body if isinstance(f, ast.FunctionDef) for n in ast.walk(f) if is_call_to(n, "ThreadPoolExecutor")]
    assert theirs == ["collect"]
    assert [n.keywords[0].value.value for n in ast.walk(tree) if is_call_to(n, "ThreadPoolExecutor")] == [4]
    # `run_process` is only ever a parameter here: never a module-level name, never assigned or imported
    assert not [n for n in tree.body if "run_process" in names_of(n)]
    assert "psycopg" in TEXT and TEXT.count("import psycopg") == 1


def test_no_layer_or_cycle_violation_touches_the_module():
    violations = import_rules.check(TARGET / "src")
    assert [v for v in violations if "observation.adapters.collectors" in v.module] == []
    assert violations == []
    assert not re.search(r"(?m)^(?:from|import) codex_harness\.(?!kernel|execution\.domain|research\.domain|coordination\.domain|observation\.)", TEXT)
