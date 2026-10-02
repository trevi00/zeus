"""Shared S9 scenario steps (`observation.collectors_sources`): M7 `adapters/monitoring.py` U7, the source collectors (docker, redis, the eight `*_facts`, the lane snapshot store and resolver, `lane_session_facts` and `collect`).

Layer: harness (never shipped)

`api.module` is the side's collectors module; `api.MemoryStore` its store; `api.FleetRefused`/`api.ContractError` the side's exception classes. `api.bind(doubles)` is a context
manager that yields the SIDE-NEUTRAL callables `docker_stats(names)`, `docker_facts(repository, containers=None)`, `redis_facts(url, agents)`, `fleet_facts(store)`,
`research_program_facts(store)`, `portfolio_facts(store)`, `fleet_backlog_facts(store)`, `host_delivery_facts(store)`, `worker_session_facts(store)`, `continuation_facts(store)`,
`discovery_pressure_facts(store)`, `lane_resolver(host_dsn, store_factory=None)`, `lane_session_facts(store, resolve, artifacts=None, now=None)` and `collect(service, artifacts,
repository, redis_url, containers=None, scope=None, runtime=None, lanes=None, lane_artifacts=None)` with the scripted `Doubles` wired in:
- reference: the doubles sit where M7's names are (`monitoring.run_process`, `monitoring.RedisBus`, `monitoring.Fleet` and the lazily imported `ResearchProgram`, `portfolio`,
  `FleetBacklog`, `HostDelivery`, `WorkerSessions`, `Continuation`, `discovery_pressure.status` and `fleet_runtime.lane_dsn`), restored afterwards;
- target: the same doubles are injected (D1.1 `run_process=`, `bus_factory=`, `project=`, `dsn_for=`, `registered=`, `ports=`).
Mirrors `tests/test_monitoring.py` (`test_container_scope_unset_keeps_compose_and_named_mode_is_exact`'s docker half, `test_read_only_store_and_reader_refuse_writes_while_collection_works`'
collect half, `test_collect_keeps_source_failures_independent` and the two backlog envelope tests at the wrapper level), the source-collector tests of `tests/test_fleet.py`,
`test_portfolio.py`, `test_research_program.py`, `test_worker_sessions.py`, `test_discovery_pressure.py` and `test_host_delivery_lane_routing.py` as wrapper-level cases (the doubles
stand for the owner classes, whose own behaviour belongs to their families) and `tests/test_monitoring_lane_sessions.py` without PostgreSQL (a `connect` double drives the lane
snapshot store; the real-PostgreSQL case is the S9 `.pg` step).

Declared nondeterministic fields, normalized HERE and never by the mask list (`compare/masks.json` is untouched): `collect`/`lane_session_facts` read the uninjected
`datetime.now` (PREP-S9 §1.3), so `collected_at`, each source envelope's `observed_at`, each lane's `observed_at`, the database and observations sources' own `observed_at` and the
persisted measurement's default-`now` `age_seconds` are replaced by `<now>` / a boolean after being PROVEN to lie between the wall-clock bounds taken around the call (a value
outside them, or a naive one, is reported as `<out-of-bounds>` and cannot equal the golden). No process, container, network, Redis or database runs.
"""

from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

CANARY = "CANARY-collectors-sources-5e4d3c2b1a09f8e7d6c5"
HOST = "host-dsn-fixture"
LEGACY = ["database", "docker", "redis"]
ADDITIVE = ["fleet", "research_programs", "portfolio", "fleet_backlog", "host_delivery", "worker_sessions", "continuation", "discovery_pressure"]
SOURCES = LEGACY + ADDITIVE


def norm(value):
    return json.loads(json.dumps(value, default=str, ensure_ascii=False))


def call(fn, *args, **kwargs):
    try:
        return {"value": norm(fn(*args, **kwargs))}
    except Exception as exc:  # the refusal is the characterized result
        return {"refused": type(exc).__name__, "message": str(exc)[:200]}


def desc(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return type(value).__name__


class Doubles:
    """The scripted stand-ins for every name M7's collectors take from other layers. `log` is per double (a thread pool interleaves sources, never one source's calls)."""

    def __init__(self, docker=None, redis=None, results=None):
        self.docker, self.redis, self.results = docker, redis if redis is not None else {}, results or {}
        self.log, self.stores, self.buses = {}, {}, []
        self.run_process = self._run_process
        self.RedisBus = self._make_bus()
        self.Fleet = self._make_class("Fleet", "status", "registered")
        self.ResearchProgram = self._make_class("ResearchProgram", "monitor")
        self.portfolio = self._make_class("portfolio", "status")
        self.FleetBacklog = self._make_class("FleetBacklog", "status")
        self.HostDelivery = self._make_class("HostDelivery", "status")
        self.WorkerSessions = self._make_class("WorkerSessions", "status")
        self.Continuation = self._make_class("Continuation", "status")

    def note(self, name, *entry):
        self.log.setdefault(name, []).append(norm(entry))

    def produce(self, key):
        self.note(key, "call")
        value = self.results.get(key, {"double": key})
        if isinstance(value, Exception):
            raise value
        return value

    def _make_class(self, name, *methods):
        doubles = self

        def init(self, store, *rest):
            doubles.note(name, "init", desc(store), *[desc(r) for r in rest])
            doubles.stores.setdefault(name, []).append(store)

        namespace = {"__init__": init}
        for method in methods:
            namespace[method] = (lambda m: lambda self: doubles.produce(name + "." + m))(method)
        return type(name, (), namespace)

    def discovery_status(self, store):
        self.note("discovery_pressure.status", desc(store))
        self.stores.setdefault("discovery_pressure.status", []).append(store)
        return self.produce("discovery_pressure.status.result")

    def lane_dsn(self, host_dsn, schema):
        self.note("lane_dsn", host_dsn, schema)
        result = self.results.get("lane_dsn")
        if isinstance(result, Exception):
            raise result
        return "dsn:" + str(host_dsn) + "#" + str(schema)

    def _run_process(self, argv, cwd=None, timeout=None, **kwargs):
        self.note("run_process", list(argv), None if cwd is None else str(cwd), timeout, sorted(kwargs))
        result = self.docker(list(argv))
        if isinstance(result, Exception):
            raise result
        return result

    def _make_bus(self):
        doubles = self

        class Client:
            def __init__(self, bus):
                self.bus = bus
                self.connection_pool = SimpleNamespace(connection_kwargs={"host": "fixture"})

            def _agent(self, key):
                return key.split(":", 1)[1]

            def _fault(self, method, key):
                fail = doubles.redis.get(self._agent(key), {}).get("fail")
                if fail and fail[0] == method:
                    raise fail[1]

            def exists(self, key):
                doubles.note("redis.exists", key)
                self._fault("exists", key)
                return int(doubles.redis.get(self._agent(key), {}).get("exists", 0))

            def xinfo_groups(self, key):
                doubles.note("redis.xinfo_groups", key)
                self._fault("xinfo_groups", key)
                return doubles.redis.get(self._agent(key), {}).get("groups", [])

            def xlen(self, key):
                doubles.note("redis.xlen", key)
                self._fault("xlen", key)
                return doubles.redis.get(self._agent(key), {}).get("len", 0)

        class RedisBus:
            def __init__(self, url):
                doubles.note("redis.bus", url)
                if "bus" in doubles.results:
                    raise doubles.results["bus"]
                self.client = Client(self)
                doubles.buses.append(self)

            def stream(self, agent):
                doubles.note("redis.stream", agent)
                return "stream:" + agent

        return RedisBus


class DockerWorld:
    """A labelled simulated Docker CLI (fixture, not a Docker run): `compose ps`, `ps --all` with the CLI's substring name filter, and `stats`."""

    def __init__(self, compose=None, listing=None, stats=None, compose_rc=0, ps_rc=0, stats_rc=0, junk=False, raises=None):
        self.compose = compose if compose is not None else [{"Service": "redis", "Name": "zeus-redis-1", "State": "running", "Image": "redis"}]
        self.listing = listing if listing is not None else {}
        self.stats = stats if stats is not None else {}
        self.compose_rc, self.ps_rc, self.stats_rc, self.junk, self.raises = compose_rc, ps_rc, stats_rc, junk, raises

    def lines(self, rows):
        out = [json.dumps(r) for r in rows]
        return "\n".join((["WARNING not json"] if self.junk else []) + out + (["trailing text"] if self.junk else []))

    def __call__(self, argv):
        if self.raises is not None:
            return self.raises
        if argv[:2] == ["docker", "compose"]:
            return SimpleNamespace(returncode=self.compose_rc, stdout=self.lines(self.compose))
        if argv[:2] == ["docker", "ps"]:
            wanted = [a[5:] for a in argv if a.startswith("name=")]
            rows = [{"Names": n, "State": s, "Image": "img-" + n} for n, s in self.listing.items() if not wanted or any(w in n for w in wanted)]
            return SimpleNamespace(returncode=self.ps_rc, stdout=self.lines(rows))
        assert argv[:2] == ["docker", "stats"], argv
        names = argv[5:]
        return SimpleNamespace(returncode=self.stats_rc, stdout=self.lines([{"Name": n, "CPUPerc": self.stats[n][0], "MemUsage": self.stats[n][1]} for n in names if n in self.stats]))


def snapshot(store):
    return json.dumps({str(k): v for k, v in store.data.items()}, sort_keys=True, default=str)


def window():
    return datetime.now(timezone.utc)


def stamp(text, lo, hi):
    """Prove a `datetime.now` value lies inside the bounds around the call, then declare it `<now>`."""
    try:
        parsed = datetime.fromisoformat(text)
    except (TypeError, ValueError):
        return "<out-of-bounds>"
    if parsed.tzinfo is None or not lo <= parsed <= hi:
        return "<out-of-bounds>"
    return "<now>"


def restamp(holder, key, lo, hi):
    if isinstance(holder, dict) and key in holder:
        holder[key] = stamp(holder[key], lo, hi)


def normalized(result, lo, hi):
    """`collect`'s declared nondeterministic fields (see the module docstring)."""
    result = json.loads(json.dumps(result, default=str))
    restamp(result, "collected_at", lo, hi)
    for name, envelope in result["sources"].items():
        restamp(envelope, "observed_at", lo, hi)
        data = envelope.get("data")
        if name in ("database", "observations"):
            restamp(data, "observed_at", lo, hi)
        if name == "database" and data:
            for row in data.get("measurements", []):
                if "age_seconds" in row:
                    row["age_seconds"] = row["age_seconds"] > 20
        if name == "lane_sessions" and data:
            for lane in data["lanes"]:
                restamp(lane, "observed_at", lo, hi)
    return result


def shape(result):
    """The envelope's keys and order, per source: the contract `monitor.html` reads."""
    return {"top": list(result), "sources": list(result["sources"]),
            "envelopes": {name: list(env) for name, env in result["sources"].items()}}


@dataclass
class Agent:
    id: str
    role: str
    capabilities: tuple = ()


def service_over(api, rows=True, broken=False):
    """A read-only service over a MemoryStore (or an injected outage) like `monitor.py` builds."""
    m = api.module
    if broken:
        class Broken:
            def transaction(self):
                raise RuntimeError("injected database outage")
        store = Broken()
    else:
        store = api.MemoryStore()
        if rows:
            with store.transaction() as tx:
                tx.put("tasks", "one", {"id": "one", "agent": "implementer", "status": "queued"})
                tx.put("metric_observations", "m1", {"id": "m1-old", "metric_id": "first_attempt_success", "value": 1, "status": "pass", "reason": "fixture",
                                                       "observed_at": "2026-01-01T00:00:00+00:00", "window_start": "2026-01-01T00:00:00+00:00",
                                                       "window_end": "2026-01-01T00:00:00+00:00", "evidence_refs": ["sha256:" + "a" * 64],
                                                       "definition": {"metric_id": "first_attempt_success"}})
    service = SimpleNamespace(store=store, org=SimpleNamespace(agents={"implementer": Agent("implementer", "worker", ("code",)), "reviewer": Agent("reviewer", "review")}))
    return m.read_only(service, None)[0], store


def lane_store_fixture(api, rows=True):
    store = api.MemoryStore()
    if rows:
        with store.transaction() as tx:
            tx.put("tasks", "task-1", {"id": "task-1", "agent": "implementer", "status": "succeeded", "generation": 1, "attempt": 1,
                                       "created_at": "2026-09-27T20:00:00+00:00", "completed_at": "2026-09-27T20:20:00+00:00", "error": CANARY})
    return store


LANES = [{"id": "a", "team": "alpha", "repository": "/zeus-fixture/" + CANARY + "-a", "schema": "lane_a", "redis_namespace": "fleet-a", "runtime": "/zeus-fixture/rt-a"},
         {"id": "b", "team": "beta", "repository": "/zeus-fixture/" + CANARY + "-b", "schema": "lane_b", "redis_namespace": "fleet-b", "runtime": "/zeus-fixture/rt-b"},
         {"id": "c", "schema": "lane_c"}]


def registration(lanes):
    return {"config": {"lanes": lanes}, "digest": "sha256:" + "0" * 64}


# ----- docker -----------------------------------------------------------------------------------------------------------------------------------

def docker_cases(api):
    out = {}

    def run(world, fn, *args, **kwargs):
        doubles = Doubles(docker=world)
        with api.bind(doubles) as ns:
            result = call(getattr(ns, fn), *args, **kwargs)
        return {"result": result, "log": doubles.log}

    stats_world = DockerWorld(stats={"c1": ("1%", "1MiB / 2MiB"), "c2": ("5.5%", "9MiB / 10MiB")})
    out["stats_empty_names_run_nothing"] = run(stats_world, "docker_stats", [])
    out["stats_none_names"] = run(stats_world, "docker_stats", None)
    out["stats_ok"] = run(stats_world, "docker_stats", ["c1", "c2"])
    out["stats_unknown_name_dropped"] = run(stats_world, "docker_stats", ["c1", "ghost"])
    out["stats_junk_lines_ignored"] = run(DockerWorld(stats={"c1": ("1%", "1MiB / 2MiB")}, junk=True), "docker_stats", ["c1"])
    out["stats_nonzero_returncode"] = run(DockerWorld(stats_rc=1, stats={"c1": ("1%", "1MiB / 2MiB")}), "docker_stats", ["c1"])
    out["stats_process_raises"] = run(DockerWorld(raises=FileNotFoundError("no docker")), "docker_stats", ["c1"])
    out["stats_generator_names"] = run(stats_world, "docker_stats", (n for n in ["c2"]))

    compose = DockerWorld(compose=[{"Service": "redis", "Name": "zeus-redis-1", "State": "running", "Image": "redis"},
                                   {"Service": "pg", "Name": "zeus-pg-1", "State": "exited", "Image": "pgvector"}],
                          stats={"zeus-redis-1": ("1%", "1MiB / 2MiB"), "zeus-pg-1": ("9%", "9MiB / 9MiB")})
    out["compose_ok_stats_only_for_running"] = run(compose, "docker_facts", "/zeus-fixture/repo")
    out["compose_junk_lines"] = run(DockerWorld(junk=True, stats={"zeus-redis-1": ("1%", "1MiB / 2MiB")}), "docker_facts", "/zeus-fixture/repo")
    out["compose_missing_stats_row"] = run(DockerWorld(), "docker_facts", "/zeus-fixture/repo")
    out["compose_empty"] = run(DockerWorld(compose=[]), "docker_facts", "/zeus-fixture/repo")
    out["compose_nonzero_returncode"] = run(DockerWorld(compose_rc=1), "docker_facts", "/zeus-fixture/repo")
    out["compose_row_missing_key"] = run(DockerWorld(compose=[{"Service": "redis"}]), "docker_facts", "/zeus-fixture/repo")
    out["compose_stats_fail"] = run(DockerWorld(stats_rc=1), "docker_facts", "/zeus-fixture/repo")
    out["compose_process_raises"] = run(DockerWorld(raises=OSError("boom")), "docker_facts", "/zeus-fixture/repo")
    out["compose_pathlike_repository"] = run(DockerWorld(), "docker_facts", Path("/zeus-fixture/path-repo"))

    listing = {"zeus-local-ops-redis": "running", "zeus-local-ops-redis-2": "running", "flexday": "running", "zeus_pg.1": "exited"}
    named = DockerWorld(listing=listing, stats={"zeus-local-ops-redis": ("1%", "1MiB / 2MiB"), "zeus_pg.1": ("2%", "2MiB / 2MiB")})
    out["named_exact_names_substring_dropped"] = run(named, "docker_facts", ".", ["zeus-local-ops-redis", "zeus_pg.1"])
    out["named_missing_container"] = run(named, "docker_facts", ".", ["zeus-local-ops-redis", "absent"])
    out["named_all_exited_no_stats"] = run(named, "docker_facts", ".", ["zeus_pg.1"])
    out["named_empty_list_is_named_scope"] = run(named, "docker_facts", ".", [])
    out["named_ps_nonzero"] = run(DockerWorld(ps_rc=2, listing=listing), "docker_facts", ".", ["flexday"])
    out["named_stats_nonzero"] = run(DockerWorld(stats_rc=2, listing=listing), "docker_facts", ".", ["flexday"])
    out["named_junk_lines"] = run(DockerWorld(junk=True, listing=listing, stats={"flexday": ("3%", "3MiB / 3MiB")}), "docker_facts", ".", ["flexday"])
    out["named_tuple_scope"] = run(named, "docker_facts", ".", ("flexday",))
    out["named_names_with_missing_state"] = run(DockerWorld(listing={"x": None}), "docker_facts", ".", ["x"])
    out["named_keyword_containers"] = run(named, "docker_facts", ".", containers=["flexday"])
    verbs = Doubles(docker=named)
    with api.bind(verbs) as ns:
        ns.docker_facts(".", ["zeus-local-ops-redis", "zeus_pg.1"])
        ns.docker_facts(".")
    out["only_compose_ps_stats_verbs_are_run"] = sorted({entry[0][1] for entry in verbs.log["run_process"]})
    return out


# ----- redis ------------------------------------------------------------------------------------------------------------------------------------

def redis_cases(api):
    out = {}

    def run(url, agents, redis=None, results=None):
        doubles = Doubles(redis=redis, results=results)
        with api.bind(doubles) as ns:
            result = call(ns.redis_facts, url, agents)
        return {"result": result, "log": doubles.log, "connection_kwargs": [b.client.connection_pool.connection_kwargs for b in doubles.buses]}

    out["no_agents"] = run("redis-fixture://a", [])
    out["absent_stream"] = run("redis-fixture://a", ["conductor"])
    out["entries_without_groups"] = run("redis-fixture://a", ["conductor"], {"conductor": {"exists": 1, "len": 7, "groups": []}})
    out["groups_sum"] = run("redis-fixture://a", ["conductor", "worker"], {
        "conductor": {"exists": 1, "len": 9, "groups": [{"pending": 2, "lag": 3}, {"pending": 1, "lag": 4}]},
        "worker": {"exists": 1, "len": 0, "groups": [{"pending": 0, "lag": 0}]}})
    out["lag_unknown_wins"] = run("redis-fixture://a", ["conductor"], {"conductor": {"exists": 1, "len": 9, "groups": [{"pending": 2, "lag": None}, {"pending": 1, "lag": 4}]}})
    out["group_keys_missing"] = run("redis-fixture://a", ["conductor"], {"conductor": {"exists": 1, "len": 3, "groups": [{}, {"pending": 5}]}})
    out["group_lag_key_absent_is_unknown"] = run("redis-fixture://a", ["conductor"], {"conductor": {"exists": 1, "len": 3, "groups": [{"pending": 1}]}})
    out["mixed_agents_order"] = run("redis-fixture://a", ["b", "a", "c"], {"a": {"exists": 1, "len": 1, "groups": []}})
    out["exists_fails"] = run("redis-fixture://a", ["conductor"], {"conductor": {"fail": ("exists", ConnectionError("down"))}})
    out["xinfo_fails"] = run("redis-fixture://a", ["conductor"], {"conductor": {"exists": 1, "fail": ("xinfo_groups", TimeoutError("slow"))}})
    out["xlen_fails"] = run("redis-fixture://a", ["conductor"], {"conductor": {"exists": 1, "len": 1, "fail": ("xlen", RuntimeError("x"))}})
    out["second_agent_fails_after_first"] = run("redis-fixture://a", ["a", "b"], {"a": {"exists": 1, "len": 1}, "b": {"fail": ("exists", ConnectionError("down"))}})
    out["bus_construction_fails"] = run("redis-fixture://a", ["conductor"], results={"bus": ConnectionError("no route")})
    out["agents_dict_keys"] = run("redis-fixture://a", {"x": object(), "y": object()}, {"x": {"exists": 1, "len": 2}})
    return out


# ----- the eight wrapper sources ----------------------------------------------------------------------------------------------------------------

WRAPPERS = [("fleet_facts", "Fleet", "Fleet.status"), ("research_program_facts", "ResearchProgram", "ResearchProgram.monitor"),
            ("portfolio_facts", "portfolio", "portfolio.status"), ("fleet_backlog_facts", "FleetBacklog", "FleetBacklog.status"),
            ("host_delivery_facts", "HostDelivery", "HostDelivery.status"), ("worker_session_facts", "WorkerSessions", "WorkerSessions.status"),
            ("continuation_facts", "Continuation", "Continuation.status"), ("discovery_pressure_facts", "discovery_pressure.status", "discovery_pressure.status.result")]


def wrapper_cases(api):
    out = {}
    store_value = api.MemoryStore()
    for fn, cls, key in WRAPPERS:
        payload = {"schema": "urn:zeus:" + fn + ":1", "registered": True, "plans": [{"id": "p1"}], "truncated": False}
        doubles = Doubles(results={key: payload})
        with api.bind(doubles) as ns:
            ok = call(getattr(ns, fn), store_value)
            returned = getattr(ns, fn)(store_value)
        broken = Doubles(results={key: RuntimeError("injected " + fn)})
        with api.bind(broken) as ns:
            failing = call(getattr(ns, fn), store_value)
        cheap = Doubles()
        with api.bind(cheap) as ns:
            default = call(getattr(ns, fn), store_value)
        out[fn] = {"ok": ok, "returns_owner_result_unchanged": returned == payload and returned is payload, "log": doubles.log, "store_passed_through": doubles.stores[cls][-1] is store_value,
                   "failing": failing, "failing_log": broken.log, "default_double_result": default}
    return out


# ----- lane snapshot store (over an injected connect double) ------------------------------------------------------------------------------------

class ConnectWorld:
    """A labelled `connect` double (fixture, not PostgreSQL): records connect arguments and every statement, answers the three statements the store issues."""

    def __init__(self, schema="lane_a", documents=None, connect_error=None, begin_error=None, set_error=None):
        self.schema, self.documents = schema, documents if documents is not None else {}
        self.connect_error, self.begin_error, self.set_error = connect_error, begin_error, set_error
        self.log = []

    def connect(self, dsn, **kwargs):
        self.log.append(["connect", dsn, kwargs])
        if self.connect_error is not None:
            raise self.connect_error
        return Conn(self)


class Cursor:
    def __init__(self, rows):
        self.rows = rows

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return list(self.rows)


class Conn:
    def __init__(self, world):
        self.world = world

    def __enter__(self):
        self.world.log.append(["enter"])
        return self

    def __exit__(self, kind, value, trace):
        self.world.log.append(["exit", None if kind is None else kind.__name__])
        return False

    def execute(self, sql, params=None):
        w = self.world
        w.log.append(["execute", sql, None if params is None else list(params)])
        if sql.startswith("BEGIN") and w.begin_error is not None:
            raise w.begin_error
        if sql.startswith("SET LOCAL") and w.set_error is not None:
            raise w.set_error
        if sql == "SELECT current_schema()":
            return Cursor([(w.schema,)])
        if sql.startswith("SELECT body FROM documents WHERE bucket=%s AND id=%s"):
            body = w.documents.get(params[0], {}).get(params[1])
            return Cursor([] if body is None else [(body,)])
        if sql.startswith("SELECT body FROM documents WHERE bucket=%s ORDER BY id"):
            return Cursor([(w.documents.get(params[0], {})[k],) for k in sorted(w.documents.get(params[0], {}))])
        return Cursor([])


def snapshot_cases(api):
    m, out = api.module, {}
    out["begin_statement"] = m.LANE_SNAPSHOT_BEGIN
    out["classes"] = [m.LaneSnapshotStore.__name__, m.LaneSnapshotTransaction.__name__]

    def session(world, body, **options):
        store = m.LaneSnapshotStore("dsn-fixture", "lane_a", connect=world.connect, **options)
        attrs = [store.dsn, store.schema, store.statement_timeout_ms, store.connect == world.connect]
        try:
            with store.transaction() as tx:
                result = {"value": norm(body(tx)), "tx_type": type(tx).__name__}
        except Exception as exc:
            result = {"refused": type(exc).__name__, "message": str(exc)[:200]}
        return {"attrs": attrs, "result": result, "log": world.log}

    docs = {"tasks": {"b": {"id": "b"}, "a": {"id": "a"}, "c": {"id": "c"}}, "operations": {"op-1": {"id": "op-1", "status": "running"}}}
    out["get_present"] = session(ConnectWorld(documents=docs), lambda tx: tx.get("operations", "op-1"))
    out["get_absent_is_none"] = session(ConnectWorld(documents=docs), lambda tx: tx.get("operations", "nope"))
    out["scan_ordered_by_id"] = session(ConnectWorld(documents=docs), lambda tx: tx.scan("tasks"))
    out["scan_empty_bucket"] = session(ConnectWorld(documents=docs), lambda tx: tx.scan("none"))
    out["put_refused"] = session(ConnectWorld(documents=docs), lambda tx: tx.put("tasks", "x", {"id": "x"}))
    out["put_refused_with_keywords"] = session(ConnectWorld(documents=docs), lambda tx: tx.put("tasks", "x", body={"id": "x"}))
    out["no_graph_method"] = session(ConnectWorld(documents=docs), lambda tx: hasattr(tx, "graph"))
    out["schema_mismatch_refused_and_rolled_back"] = session(ConnectWorld(schema="public", documents=docs), lambda tx: tx.get("tasks", "a"))
    out["custom_statement_timeout"] = session(ConnectWorld(documents=docs), lambda tx: tx.get("tasks", "a"), statement_timeout_ms=250)
    out["body_failure_rolls_back_and_propagates"] = session(ConnectWorld(documents=docs), lambda tx: (_ for _ in ()).throw(RuntimeError("injected body failure")))
    out["set_local_failure_rolls_back"] = session(ConnectWorld(documents=docs, set_error=RuntimeError("injected set failure")), lambda tx: tx.get("tasks", "a"))
    out["begin_failure_never_rolls_back"] = session(ConnectWorld(documents=docs, begin_error=RuntimeError("injected begin failure")), lambda tx: tx.get("tasks", "a"))
    out["connect_failure"] = session(ConnectWorld(documents=docs, connect_error=ConnectionError("no database")), lambda tx: tx.get("tasks", "a"))
    out["two_transactions_two_snapshots"] = (lambda w: {"values": [session(w, lambda tx: tx.get("tasks", "a"))["result"], session(w, lambda tx: tx.get("tasks", "b"))["result"]], "log": w.log})(
        ConnectWorld(documents=docs))
    # the transaction class alone, over a bare connection double
    world = ConnectWorld(documents=docs)
    tx = m.LaneSnapshotTransaction(Conn(world))
    out["transaction_alone"] = {"get": norm(tx.get("tasks", "a")), "scan": norm(tx.scan("tasks")), "put": call(tx.put, "tasks", "z", {}), "log": world.log}
    out["transaction_conn_attribute"] = isinstance(tx._conn, Conn)
    return out


# ----- lane resolver ----------------------------------------------------------------------------------------------------------------------------

def _put_through(store):
    with store.transaction() as tx:
        return tx.put("tasks", "x", {"id": "x"})


def resolver_cases(api):
    out = {}

    def factory_log(doubles, store_marker):
        def factory(dsn, schema):
            doubles.note("store_factory", dsn, schema)
            return store_marker(dsn, schema)
        return factory

    doubles = Doubles()
    made = []

    def make(dsn, schema):
        store = api.MemoryStore()
        made.append(store)
        return store
    with api.bind(doubles) as ns:
        resolve = ns.lane_resolver(HOST, factory_log(doubles, make))
        first = resolve(LANES[0])
        again = resolve(LANES[0])
        other = resolve(LANES[1])
        changed = resolve({"id": "a", "schema": "lane_a2"})
        changed_again = resolve({"id": "a", "schema": "lane_a2"})
        out["cache"] = {"types": [type(x).__name__ for x in (first, other, changed)], "same_lane_same_object": first is again, "same_key_second_schema_same": changed is changed_again,
                        "changed_schema_is_new": changed is not first, "distinct_lanes_distinct": first is not other, "wraps_factory_store": first._store is made[0],
                        "factory_calls": doubles.log["store_factory"], "dsn_calls": doubles.log["lane_dsn"], "made": len(made)}
        out["lane_missing_schema"] = call(resolve, {"id": "z"})
        out["lane_missing_id"] = call(resolve, {"schema": "s"})
        out["lane_extra_keys_ignored"] = call(lambda: type(resolve({**LANES[1], "team": "other", "repository": "/elsewhere"})).__name__)
        out["resolver_store_writes_refused"] = call(_put_through, resolve(LANES[0]))
    doubles = Doubles(results={"lane_dsn": RuntimeError("injected dsn failure")})
    with api.bind(doubles) as ns:
        resolve = ns.lane_resolver(HOST, lambda dsn, schema: api.MemoryStore())
        out["dsn_failure_at_resolve"] = {"result": call(resolve, LANES[0]), "retry_not_cached": call(resolve, LANES[0]), "dsn_calls": doubles.log["lane_dsn"]}
    doubles = Doubles()
    with api.bind(doubles) as ns:
        resolve = ns.lane_resolver(HOST)
        store = resolve(LANES[0])
        inner = store._store
        out["default_factory_is_the_lock_free_lane_snapshot_store"] = {"read_only": type(store).__name__, "inner": type(inner).__name__, "dsn": inner.dsn, "schema": inner.schema,
                                                                       "timeout_ms": inner.statement_timeout_ms, "connect_is_psycopg": getattr(inner.connect, "__module__", "").startswith("psycopg"),
                                                                       "dsn_calls": doubles.log["lane_dsn"]}
        out["default_factory_cached"] = resolve(LANES[0]) is store
    doubles = Doubles()
    with api.bind(doubles) as ns:
        out["store_factory_failure"] = call(ns.lane_resolver(HOST, lambda dsn, schema: (_ for _ in ()).throw(RuntimeError("injected factory failure"))), LANES[0])
        out["resolver_is_lazy"] = call(lambda: (ns.lane_resolver(HOST, lambda *a: (_ for _ in ()).throw(AssertionError("never")))) and "built, nothing resolved")
    return out


# ----- lane_session_facts -----------------------------------------------------------------------------------------------------------------------

def lane_session_cases(api):
    m, out = api.module, {}
    now = datetime(2026, 9, 28, 1, 0, tzinfo=timezone.utc)
    control = m.ReadOnlyStore(api.MemoryStore())

    def run(results, resolve, artifacts=None, now_value=None):
        doubles = Doubles(results=results)
        lo = window()
        with api.bind(doubles) as ns:
            result = call(ns.lane_session_facts, control, resolve, artifacts, now_value)
        hi = window()
        if "value" in result:
            for lane in result["value"].get("lanes", []):
                restamp(lane, "observed_at", lo, hi)
        return {"result": result, "log": doubles.log}

    stores = {"a": m.ReadOnlyStore(lane_store_fixture(api)), "b": m.ReadOnlyStore(lane_store_fixture(api, rows=False)), "c": m.ReadOnlyStore(lane_store_fixture(api, rows=False))}
    resolved = []

    def resolver(lane):
        resolved.append(lane["id"])
        return stores[lane["id"]]

    out["unregistered"] = run({"Fleet.registered": api.FleetRefused("unregistered")}, resolver, now_value=now)
    out["registered_other_refusal_propagates"] = run({"Fleet.registered": api.FleetRefused("corrupt", "config")}, resolver, now_value=now)
    out["registered_other_error_propagates"] = run({"Fleet.registered": RuntimeError("injected store outage")}, resolver, now_value=now)
    out["registered_no_lanes"] = run({"Fleet.registered": registration([])}, resolver, now_value=now)
    out["registered_lanes_none"] = run({"Fleet.registered": {"config": {"lanes": None}}}, resolver, now_value=now)
    out["registered_config_without_lanes"] = run({"Fleet.registered": {"config": {}}}, resolver, now_value=now)
    resolved.clear()
    out["ok_lanes"] = run({"Fleet.registered": registration(LANES)}, resolver, now_value=now)
    out["ok_lanes_resolution_order"] = list(resolved)
    asked = []

    def artifacts(lane):
        asked.append(lane["id"])
        return None
    out["artifacts_callable_per_lane"] = run({"Fleet.registered": registration(LANES[:2])}, resolver, artifacts=artifacts, now_value=now)
    out["artifacts_asked_for"] = list(asked)

    def failing(lane):
        if lane["id"] == "b":
            raise RuntimeError("injected lane outage " + CANARY)
        return resolver(lane)
    out["one_lane_failing_alone"] = run({"Fleet.registered": registration(LANES)}, failing, now_value=now)

    def all_failing(lane):
        raise OSError("down")
    out["every_lane_failing"] = run({"Fleet.registered": registration(LANES)}, all_failing, now_value=now)

    def artifacts_failing(lane):
        raise ValueError("artifact root " + CANARY)
    out["artifact_resolver_failing_is_lane_failure"] = run({"Fleet.registered": registration(LANES[:2])}, resolver, artifacts=artifacts_failing, now_value=now)
    out["lane_without_id_propagates"] = run({"Fleet.registered": registration([{"team": "x", "schema": "s"}])}, resolver, now_value=now)
    seen = Doubles(results={"Fleet.registered": registration([])})
    with api.bind(seen) as ns:
        ns.lane_session_facts(control, resolver)
    out["registered_receives_the_store_unchanged"] = seen.stores["Fleet"][-1] is control
    return out


# ----- collect ----------------------------------------------------------------------------------------------------------------------------------

def collect_run(api, doubles, *, repository="/zeus-fixture/some-repo", redis_url="redis-fixture://a", broken=False, rows=True, **kwargs):
    service, store = service_over(api, rows=rows, broken=broken)
    before = None if broken else snapshot(store)
    lo = window()
    with api.bind(doubles) as ns:
        try:
            result = ns.collect(service, kwargs.pop("artifacts", None), repository, redis_url, **kwargs)
        except Exception as exc:
            return {"refused": type(exc).__name__, "message": str(exc)[:200]}
    hi = window()
    return {"shape": shape(result), "result": normalized(result, lo, hi), "store_unchanged": broken or snapshot(store) == before}


def healthy_world():
    return DockerWorld(compose=[{"Service": "redis", "Name": "zeus-redis-1", "State": "running", "Image": "redis"}], stats={"zeus-redis-1": ("1%", "1MiB / 2MiB")})


def healthy_results():
    keys = {"fleet": "Fleet.status", "research_programs": "ResearchProgram.monitor", "portfolio": "portfolio.status", "fleet_backlog": "FleetBacklog.status",
            "host_delivery": "HostDelivery.status", "worker_sessions": "WorkerSessions.status", "continuation": "Continuation.status", "discovery_pressure": "discovery_pressure.status.result"}
    return {key: {"schema": "urn:zeus:" + name + ":1", "source": name} for name, key in keys.items()}


def collect_cases(api):
    out = {}
    redis = {"conductor": {"exists": 1, "len": 2, "groups": [{"pending": 1, "lag": 0}]}}

    def doubles(results=None, world=None, redis_state=None):
        return Doubles(docker=world or healthy_world(), redis=redis if redis_state is None else redis_state, results={**healthy_results(), **(results or {})})

    d = doubles()
    out["all_ok"] = collect_run(api, d)
    out["all_ok_doubles_log"] = {k: v for k, v in sorted(d.log.items())}
    out["all_ok_empty_store"] = collect_run(api, doubles(), rows=False)
    out["docker_fails_alone"] = collect_run(api, doubles(world=DockerWorld(raises=FileNotFoundError("no docker"))))
    out["docker_returncode_fails_alone"] = collect_run(api, doubles(world=DockerWorld(compose_rc=1)))
    out["redis_fails_alone"] = collect_run(api, doubles(results={"bus": ConnectionError("down")}))
    out["database_fails_alone"] = collect_run(api, doubles(), broken=True)
    for name, key in {"fleet": "Fleet.status", "research_programs": "ResearchProgram.monitor", "portfolio": "portfolio.status", "fleet_backlog": "FleetBacklog.status",
                      "host_delivery": "HostDelivery.status", "worker_sessions": "WorkerSessions.status", "continuation": "Continuation.status",
                      "discovery_pressure": "discovery_pressure.status.result"}.items():
        out["only_" + name + "_fails"] = collect_run(api, doubles(results={key: KeyError("injected " + name)}))
    every = {key: RuntimeError("injected " + key) for key in ("Fleet.status", "ResearchProgram.monitor", "portfolio.status", "FleetBacklog.status", "HostDelivery.status",
                                                               "WorkerSessions.status", "Continuation.status", "discovery_pressure.status.result")}
    out["every_source_fails_independently"] = collect_run(api, doubles(results={**every, "bus": ConnectionError("down")}, world=DockerWorld(raises=OSError("down"))), broken=True)
    out["distinct_error_types_kept"] = collect_run(api, doubles(results={"Fleet.status": ValueError("a"), "portfolio.status": LookupError("b"), "Continuation.status": api.ContractError("c"),
                                                                       "HostDelivery.status": api.FleetRefused("unregistered")}))
    out["containers_named_scope"] = collect_run(api, doubles(world=DockerWorld(listing={"flexday": "running"}, stats={"flexday": ("3%", "3MiB / 3MiB")})), containers=["flexday"])
    out["containers_named_missing_is_docker_unavailable"] = collect_run(api, doubles(world=DockerWorld(listing={})), containers=["flexday"])
    out["containers_empty_named"] = collect_run(api, doubles(world=DockerWorld(listing={})), containers=[])
    out["scope_label_given"] = collect_run(api, doubles(), scope="Zeus 고정 운영 원장 password=" + CANARY)
    out["scope_label_blank"] = collect_run(api, doubles(), scope="   ", repository="/zeus-fixture/blank-label-repo")
    out["agents_order_drives_redis"] = collect_run(api, doubles(redis_state={"implementer": {"exists": 1, "len": 1}, "reviewer": {"exists": 0}}))
    with tempfile.TemporaryDirectory(prefix="s9-collectors-sources-") as runtime:
        d = doubles()
        out["runtime_adds_observations"] = collect_run(api, d, runtime=Path(runtime))
        out["runtime_leaves_no_file"] = sorted(p.name for p in Path(runtime).rglob("*"))
    d = doubles()
    out["lanes_add_lane_sessions"] = collect_run(api, d, lanes=_lane_resolver(api, d))
    out["lanes_doubles_log"] = {k: v for k, v in sorted(d.log.items()) if k.startswith(("Fleet", "lane_dsn"))}
    d = doubles(results={"Fleet.registered": api.FleetRefused("unregistered")})
    out["lanes_unregistered_fleet"] = collect_run(api, d, lanes=_lane_resolver(api, d))
    d = doubles(results={"Fleet.registered": RuntimeError("injected store outage")})
    out["lanes_store_outage_is_source_unavailable"] = collect_run(api, d, lanes=_lane_resolver(api, d))
    seen = []
    d = doubles(results={"Fleet.registered": registration(LANES[:2])})
    out["lane_artifacts_passed_per_lane"] = collect_run(api, d, lanes=_lane_resolver(api, d), lane_artifacts=lambda lane: seen.append(lane["id"]))
    out["lane_artifacts_seen"] = sorted(seen)
    d = doubles()
    out["both_runtime_and_lanes_order"] = collect_run(api, d, runtime=Path("/zeus-fixture/no-such-runtime"), lanes=_lane_resolver(api, d))
    out["fleet_backlog_envelope_passthrough"] = _backlog(api, doubles)
    out["read_only_store_and_artifacts_untouched"] = _readonly(api, doubles)
    return out


def _lane_resolver(api, d):
    stores = {"a": api.module.ReadOnlyStore(lane_store_fixture(api, rows=False)), "b": api.module.ReadOnlyStore(lane_store_fixture(api, rows=False)),
              "c": api.module.ReadOnlyStore(lane_store_fixture(api, rows=False))}
    d.results.setdefault("Fleet.registered", registration(LANES))
    return lambda lane: stores[lane["id"]]


def _backlog(api, doubles):
    plan = {"plan_id": "plan-1", "enabled": True, "outcome": "blocked", "next_action": "owner_review", "blocked": {"two": "deferred_input_unavailable"},
            "counts": {"pending": 0, "open": 1, "enqueued": 1, "blocked": 0, "conflict": 1, "unknown": 1, "accepted": 0, "unlinked": 0}}
    status = {"schema": "urn:zeus:fleet-backlog-status:1", "registered": True, "fleet_paused": False, "plans": [plan]}
    paused = {"schema": "urn:zeus:fleet-backlog-status:1", "registered": True, "fleet_paused": True, "plans": [{**plan, "outcome": "fleet_paused", "next_action": "resume_fleet", "blocked": {}}]}
    unregistered = {"schema": "urn:zeus:fleet-backlog-status:1", "registered": False, "fleet_paused": False, "plans": []}
    envelopes = {}
    for name, value in (("registered", status), ("paused", paused), ("unregistered", unregistered)):
        result = collect_run(api, doubles(results={"FleetBacklog.status": value}))
        envelopes[name] = {"fleet_backlog": result["result"]["sources"]["fleet_backlog"], "database_status": result["result"]["sources"]["database"]["status"],
                           "canary_free": CANARY not in json.dumps(result)}
    return envelopes


def _readonly(api, doubles):
    with tempfile.TemporaryDirectory(prefix="s9-collectors-sources-") as root:
        service, store = service_over(api)
        before = snapshot(store)
        with api.bind(doubles()) as ns:
            ns.collect(service, None, root, "redis-fixture://a")
            ns.collect(service, None, root, "redis-fixture://a")
        return {"store_unchanged_after_two_collects": snapshot(store) == before, "root_still_empty": sorted(p.name for p in Path(root).rglob("*"))}


def run(api) -> dict:
    return {"docker": docker_cases(api), "redis": redis_cases(api), "wrappers": wrapper_cases(api), "lane_snapshot_store": snapshot_cases(api), "lane_resolver": resolver_cases(api),
            "lane_session_facts": lane_session_cases(api), "collect": collect_cases(api)}
