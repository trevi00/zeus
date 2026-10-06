"""`zeus host-delivery --lane` routing (INV-HOST-DELIVERY-001).

A delivery's records (targets, plans, intents, descriptors, Releases, the ReleaseQueue fence, the
collect canary and the tick observer) live in the store of the ONE Fleet lane the owner names;
the managed target's activation gate is always the Fleet of the CONTROL store. Without `--lane`
every command is exactly what it was.

The unit tests use in-memory stores for control and lanes (labelled; not PostgreSQL) and a real
disposable Git repository at the lane's registered path. No `gh`, no network, no systemctl, no
managed launcher and no model runs: the activation gate is exercised directly, which is the call
`ManagedFleetTarget.start` makes before its stop and again before its launch.

The PostgreSQL tests run only under `HARNESS_INTEGRATION=1` (the same gate as `isolated_pgstore`)
and create, migrate and drop their own uniquely named control and lane schemas.
"""
import functools
import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from codex_harness import cli
from codex_harness.adapters import host_delivery
from codex_harness.adapters.host_delivery import (
    ENABLED_SETTING,
    canary_receipt_file,
    controller,
    execute,
    lane_git,
    owner_qualified_canary,
    resolve_lane,
)
from codex_harness.adapters.managed_runtime import launcher_environment
from codex_harness.adapters.store import MemoryStore
from codex_harness.application.fleet import (
    ACTIVATION_HOLD,
    BUCKET_CONTROL,
    BUCKET_JOBS,
    CONTROL_KEY,
    Fleet,
    LaunchRefused,
)
from codex_harness.application.host_delivery import (
    BUCKET_DESCRIPTORS,
    BUCKET_INTENTS,
    BUCKET_PLANS,
    BUCKET_TARGETS,
)
from codex_harness.bootstrap import organization
from codex_harness.domain.fleet import DISPATCHING, UNIT_CONDUCTOR
from codex_harness.domain.host_delivery import (
    CANARY_COLLECT,
    CANARY_FLEET,
    CANARY_STARTUP,
    DESCRIPTOR_SCHEMA,
    KIND_MANAGED,
    KIND_MANAGED_SYSTEMD,
    PLAN_SCHEMA,
    REGISTRY_SCHEMA,
    DeliveryRefused,
    descriptor_digest,
)

CONTROL_DSN = "postgresql://fixture@fixture-host/control"  # a label: nothing connects to it
LANES = {"harness": "zeus_fleet_harness", "interface": "zeus_fleet_interface"}
DELIVERY_BUCKETS = (BUCKET_TARGETS, BUCKET_PLANS, BUCKET_INTENTS, BUCKET_DESCRIPTORS)
REVISION = "a" * 40
PLAN_PATH = "docs/zeus/operations/delivery.json"


# ----- fixtures ------------------------------------------------------------------------------
def git(root, *argv) -> str:
    return subprocess.run(["git", "-C", str(root), *argv], check=True, capture_output=True,
                          text=True).stdout.strip()


def fleet_config(tmp_path, schemas=None) -> dict:
    schemas = schemas or LANES
    return {"schema": "urn:zeus:fleet:1", "id": "routing-fixture", "max_parallel": 1,
            "budget": {"per_host": 4, "total": 8},
            "lanes": [{"id": lane, "team": lane, "repository": str(tmp_path / ("repo-" + lane)),
                       "schema": schema, "redis_namespace": "routing-" + lane,
                       "runtime": str(tmp_path / ("runtime-" + lane))}
                      for lane, schema in schemas.items()]}


def control_service(tmp_path, *, register=True, schemas=None):
    service = SimpleNamespace(store=MemoryStore(), org=organization())
    if register:
        Fleet(service.store).register(fleet_config(tmp_path, schemas))
    return service


class LaneStores:
    """LABELLED in-memory lane stores, keyed by the schema the lane DSN selects. A factory call for a
    DSN that names no known schema is a test failure, so every store here came through `lane_dsn`."""

    def __init__(self, schemas=LANES):
        self.by_schema = {schema: MemoryStore() for schema in schemas.values()}
        self.dsns = []

    def __call__(self, dsn):
        self.dsns.append(dsn)
        matches = [schema for schema in self.by_schema if "search_path=" + schema in dsn]
        assert len(matches) == 1, "lane store built from a DSN without exactly one lane schema"
        return self.by_schema[matches[0]]

    def lane(self, lane_id):
        return self.by_schema[LANES[lane_id]]


def verified(calls):
    def verify(dsn, schema):
        calls.append(schema)
    return verify


def routed_resolver(stores, *, host=None, verify=None, control_schema=lambda _store: "control"):
    """The real `resolve_lane` with only its I/O ports replaced (labelled)."""
    return functools.partial(resolve_lane, host=host or {"HARNESS_DATABASE_URL": CONTROL_DSN},
                             store_factory=stores, verify=verify or verified([]),
                             control_schema=control_schema)


def args(command, **fields):
    return SimpleNamespace(delivery_command=command, **fields)


def rows(store, bucket):
    with store.transaction() as tx:
        return tx.scan(bucket)


def delivery_rows(store) -> dict:
    return {bucket: rows(store, bucket) for bucket in DELIVERY_BUCKETS}


def empty(store) -> bool:
    return all(not found for found in delivery_rows(store).values())


def targets_document(tmp_path, target_id="aibox-managed-fleet") -> dict:
    return {"schema": REGISTRY_SCHEMA,
            "targets": [{"target_id": target_id, "kind": "process", "root": str(tmp_path / "root"),
                         "state_dir": str(tmp_path / "state" / target_id), "service": "zeus-canary"}]}


def plan_document(**overrides) -> dict:
    return {"schema": PLAN_SCHEMA, "plan_id": "lane-plan-1", "release_id": "release-1",
            "revision": REVISION, "tree": "c" * 64, "policy_hash": "1" * 64,
            "repository": "github:zeus-owner/zeus-harness", "required_checks": ["ci / required"],
            "target_id": "aibox-managed-fleet", "expected_descriptor": None,
            "target_descriptor": {"revision": REVISION, "worker_image": "zeus-worker@sha256:" + "d" * 64,
                                  "profile_digest": "e" * 64},
            "canary_check_id": CANARY_STARTUP, "ci_timeout_seconds": 300,
            "consumption_timeout_seconds": 120, **overrides}


def commit_plan(repository: Path, document: dict) -> str:
    repository.mkdir(parents=True, exist_ok=True)
    git(repository, "init", "-q", "-b", "main")
    for key, value in {"core.autocrlf": "false", "core.eol": "lf"}.items():
        git(repository, "config", "--local", key, value)
    path = repository / PLAN_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(json.dumps(document, sort_keys=True).encode("utf-8"))
    git(repository, "add", "--all")
    git(repository, "-c", "user.name=t", "-c", "user.email=t@localhost", "commit", "-q", "-m", "plan")
    return git(repository, "rev-parse", "HEAD")


def descriptor(target_id="aibox-managed-fleet") -> dict:
    return {"schema": DESCRIPTOR_SCHEMA, "target_id": target_id, "root": "/labelled/runtime",
            "revision": REVISION, "worker_image": "zeus-worker@sha256:" + "d" * 64,
            "profile_digest": "e" * 64, "predecessor": None}


def forbid(name):
    def refuse(*_args, **_kwargs):
        raise AssertionError(name + " must not be reached on this path")
    return refuse


class Unavailable:
    """LABELLED control store outage: every transaction fails to open."""

    def transaction(self):
        raise OSError("labelled control store outage")


# ----- the parser ------------------------------------------------------------------------------
def test_every_owner_command_takes_an_optional_lane_and_defaults_to_none():
    parse = cli.parser().parse_args
    for argv in (["register-targets", "--file", "t.json"],
                 ["register", "--revision", REVISION, "--path", PLAN_PATH],
                 ["status"], ["tick"], ["run", "--once"]):
        assert parse(["host-delivery", *argv]).lane is None
        assert parse(["host-delivery", *argv, "--lane", "harness"]).lane == "harness"


# ----- default: unchanged ------------------------------------------------------------------------
def test_without_a_lane_every_command_stays_on_the_control_store(tmp_path, monkeypatch):
    # No Fleet is registered: any lane resolution would refuse, so success proves none happened.
    service = control_service(tmp_path, register=False)
    monkeypatch.setattr(host_delivery, "resolve_lane", forbid("resolve_lane"))
    registry = tmp_path / "targets.json"
    registry.write_text(json.dumps(targets_document(tmp_path)), encoding="utf-8")
    receipt = execute(service, args("register-targets", file=registry))
    assert receipt["exit_code"] == 0 and "lane" not in receipt
    assert [row["id"] for row in rows(service.store, BUCKET_TARGETS)] == ["aibox-managed-fleet"]
    monkeypatch.setattr(host_delivery, "_git", lambda _service: SimpleNamespace(repository=tmp_path))
    monkeypatch.setattr(host_delivery, "_observer", lambda _service: None)
    monkeypatch.delenv(ENABLED_SETTING, raising=False)
    idle = execute(service, args("tick", plan=None, lane=None))
    assert idle["exit_code"] == 0 and idle["outcome"] == "idle" and "lane" not in idle
    status = execute(service, args("status", plan=None, lane=None))
    assert status["exit_code"] == 0 and "lane" not in status
    # The default controller keeps the control store for records AND for the activation gate.
    wired = controller(service, enabled=False)
    assert wired.store is service.store and wired.hosts[KIND_MANAGED].fleet.store is service.store


# ----- routing -------------------------------------------------------------------------------------
def test_registration_plan_and_status_route_to_the_named_lane_only(tmp_path, monkeypatch):
    service = control_service(tmp_path)
    stores = LaneStores()
    monkeypatch.setattr(host_delivery, "resolve_lane", routed_resolver(stores))
    monkeypatch.setattr(host_delivery, "_git", forbid("the control workspace"))
    registry = tmp_path / "targets.json"
    registry.write_text(json.dumps(targets_document(tmp_path)), encoding="utf-8")
    receipt = execute(service, args("register-targets", file=registry, lane="harness"))
    assert receipt["exit_code"] == 0 and receipt["lane"] == "harness"
    # The plan is read from the lane's OWN registered repository at the pinned commit.
    revision = commit_plan(tmp_path / "repo-harness", plan_document())
    registered = execute(service, args("register", revision=revision, path=PLAN_PATH, lane="harness"))
    assert registered["exit_code"] == 0 and registered["lane"] == "harness"
    assert registered["pin"]["revision"] == revision
    harness = stores.lane("harness")
    assert [row["id"] for row in rows(harness, BUCKET_TARGETS)] == ["aibox-managed-fleet"]
    assert [row["id"] for row in rows(harness, BUCKET_PLANS)] == ["lane-plan-1"]
    monkeypatch.delenv(ENABLED_SETTING, raising=False)
    projection = execute(service, args("status", plan="lane-plan-1", lane="harness"))
    assert projection["exit_code"] == 0 and projection["deliveries"][0]["stage"] == "registered"
    # No cross-lane update: the control store and the other lane hold no delivery row at all, and the
    # control store's Fleet registry is exactly what it was.
    assert empty(service.store) and empty(stores.lane("interface"))
    assert execute(service, args("status", plan="lane-plan-1", lane="interface"))["exit_code"] == 1


def test_a_lane_plan_is_never_read_from_another_lanes_repository(tmp_path, monkeypatch):
    service = control_service(tmp_path)
    stores = LaneStores()
    monkeypatch.setattr(host_delivery, "resolve_lane", routed_resolver(stores))
    execute(service, args("register-targets", file=_write(tmp_path, targets_document(tmp_path)),
                          lane="harness"))
    revision = commit_plan(tmp_path / "repo-interface", plan_document())
    (tmp_path / "repo-harness").mkdir()
    git(tmp_path / "repo-harness", "init", "-q", "-b", "main")
    with pytest.raises(DeliveryRefused) as refused:
        execute(service, args("register", revision=revision, path=PLAN_PATH, lane="harness"))
    assert refused.value.reason_code == "plan_revision_missing"
    assert rows(stores.lane("harness"), BUCKET_PLANS) == []


def _write(tmp_path, document) -> Path:
    path = tmp_path / ("document-" + uuid4().hex[:8] + ".json")
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def test_a_lane_controller_owns_lane_records_but_gates_on_the_control_fleet(tmp_path):
    service = control_service(tmp_path)
    stores = LaneStores()
    route = routed_resolver(stores)(service, "harness")
    lane = route["store"]
    assert lane is stores.lane("harness")
    host = {"HARNESS_DATABASE_URL": CONTROL_DSN, "HARNESS_GITHUB_REPO": "zeus-owner/zeus-harness"}
    wired = controller(service, enabled=False, store=lane, git=lane_git(route["lane"], host))
    assert wired.store is lane and wired.releases.store is lane and wired.queue.store is lane
    for kind in (KIND_MANAGED, KIND_MANAGED_SYSTEMD):
        assert isinstance(wired.hosts[kind].fleet, Fleet) and wired.hosts[kind].fleet.store is service.store
    workspace = wired.github.workspace
    assert workspace.repository == (tmp_path / "repo-harness").resolve()
    assert workspace.workspaces == (tmp_path / "runtime-harness" / "workspaces").resolve()
    assert workspace.remote == "zeus-owner/zeus-harness"


@pytest.mark.parametrize("debt", ["unit_held", "job_reserving", "owner_paused_with_unit"])
def test_control_debt_refuses_a_managed_activation_even_when_the_lane_is_empty(tmp_path, debt):
    service = control_service(tmp_path)
    fleet = Fleet(service.store)
    if debt in ("unit_held", "owner_paused_with_unit"):
        fleet.reserve_unit("c" * 64, UNIT_CONDUCTOR, "harness", "labelled-held-conductor")
    if debt == "owner_paused_with_unit":
        fleet.pause()
    if debt == "job_reserving":
        with service.store.transaction() as tx:  # LABELLED fixture row: a job mid-dispatch
            tx.put(BUCKET_JOBS, "job-dispatching", {"id": "job-dispatching", "lane": "harness",
                                                    "status": DISPATCHING})
    lane = LaneStores().lane("harness")
    assert rows(lane, BUCKET_JOBS) == [] and rows(lane, BUCKET_CONTROL) == []
    for kind in (KIND_MANAGED, KIND_MANAGED_SYSTEMD):
        host = controller(service, enabled=False, store=lane).hosts[kind]
        with pytest.raises(DeliveryRefused) as refused:
            host._activation_gate({"target_id": "aibox-managed-fleet"}, descriptor())
        assert refused.value.reason_code == "fleet_debt_held"
    # The pause and its hold are the CONTROL store's; nothing was written into the lane.
    with service.store.transaction() as tx:
        assert tx.get(BUCKET_CONTROL, CONTROL_KEY)["paused"] is True
    assert rows(lane, BUCKET_CONTROL) == [] and empty(lane)


def test_a_settled_control_fleet_is_what_lets_a_lane_activation_through(tmp_path):
    # The discriminating control: the lane has NO Fleet registry, so the pre-fix gate (Fleet over the
    # lane store) refused here as `fleet_pause_unknown` whatever the real debt was.
    service = control_service(tmp_path)
    lane = LaneStores().lane("harness")
    host = controller(service, enabled=False, store=lane).hosts[KIND_MANAGED_SYSTEMD]
    assert host._activation_gate({"target_id": "aibox-managed-fleet"}, descriptor()) is None
    with service.store.transaction() as tx:
        hold = tx.get(BUCKET_CONTROL, CONTROL_KEY)[ACTIVATION_HOLD]
    assert hold["descriptor_sha256"] == descriptor_digest(descriptor())
    with pytest.raises(DeliveryRefused) as refused:
        controller(SimpleNamespace(store=lane, org=organization()), enabled=False).hosts[
            KIND_MANAGED_SYSTEMD]._activation_gate({"target_id": "aibox-managed-fleet"}, descriptor())
    assert refused.value.reason_code == "fleet_pause_unknown"


def test_an_unavailable_control_fleet_refuses_the_activation_and_the_lane_resolution(tmp_path):
    lane = LaneStores().lane("harness")
    down = SimpleNamespace(store=Unavailable(), org=organization())
    host = controller(down, enabled=False, store=lane).hosts[KIND_MANAGED]
    with pytest.raises(DeliveryRefused) as refused:
        host._activation_gate({"target_id": "aibox-managed-fleet"}, descriptor())
    assert refused.value.reason_code == "fleet_pause_unknown"
    with pytest.raises(DeliveryRefused) as unresolved:
        routed_resolver(LaneStores())(down, "harness")
    assert unresolved.value.reason_code == "lane_registry_unavailable"


# ----- refusals: no fallback -----------------------------------------------------------------------
@pytest.mark.parametrize("case, reason", [
    ("unknown", "lane_unknown"), ("empty", "lane_invalid"), ("unregistered", "lane_registry_unregistered"),
    ("ambiguous", "lane_ambiguous"), ("unprovisioned", "lane_schema_unprovisioned"),
    ("mismatch", "lane_schema_mismatch"), ("unreachable", "lane_unavailable"),
    ("no_dsn", "lane_database_url_missing"), ("is_control", "lane_is_control")])
def test_a_wrong_missing_or_ambiguous_lane_refuses_before_any_store_is_touched(tmp_path, monkeypatch,
                                                                                case, reason):
    service = control_service(tmp_path, register=case != "unregistered")
    stores = LaneStores()
    lane_id = {"unknown": "no-such-lane", "empty": ""}.get(case, "harness")
    host = {} if case == "no_dsn" else None
    verify = None
    if case in ("unprovisioned", "mismatch", "unreachable"):
        code = {"unprovisioned": "lane_schema_unprovisioned", "mismatch": "lane_schema_mismatch",
                "unreachable": "lane_unavailable"}[case]

        def verify(dsn, schema):
            raise LaunchRefused(code)
    if case == "ambiguous":
        config = fleet_config(tmp_path)
        duplicated = {**config, "lanes": [config["lanes"][0], dict(config["lanes"][0])]}
        # LABELLED: a registry row validation would never store, read back as if it had been.
        monkeypatch.setattr(Fleet, "registered", lambda self: {"config": duplicated})
    control_schema = (lambda _store: LANES["harness"]) if case == "is_control" else (lambda _store: "control")
    resolver = functools.partial(resolve_lane, host=host if host is not None else {"HARNESS_DATABASE_URL": CONTROL_DSN},
                                 store_factory=stores, verify=verify or verified([]),
                                 control_schema=control_schema)
    monkeypatch.setattr(host_delivery, "resolve_lane", resolver)
    monkeypatch.setattr(host_delivery, "_git", forbid("the control workspace"))
    monkeypatch.setattr(host_delivery, "_observer", forbid("the control observer"))
    registry = _write(tmp_path, targets_document(tmp_path))
    for command in (args("register-targets", file=registry, lane=lane_id),
                    args("status", plan=None, lane=lane_id), args("tick", plan=None, lane=lane_id)):
        with pytest.raises(DeliveryRefused) as refused:
            execute(service, command)
        assert refused.value.reason_code == reason and refused.value.field == "lane"
    assert stores.dsns == [], "no lane store may be built for a refused lane"
    assert empty(service.store), "a refused lane never falls back to the control store"


def test_the_real_control_schema_probe_skips_a_store_without_a_dsn():
    assert host_delivery._control_schema(MemoryStore()) is None


# ----- canaries --------------------------------------------------------------------------------------
def test_the_collect_canary_reads_the_lane_and_the_owner_canary_stays_file_bound(tmp_path, monkeypatch):
    service = control_service(tmp_path)
    lane = LaneStores().lane("harness")
    read = []

    def facts(store):
        read.append(store)
        return {"targets": []}
    monkeypatch.setattr("codex_harness.adapters.monitoring.host_delivery_facts", facts)
    wired = controller(service, enabled=False, store=lane)
    target = {"target_id": "aibox-managed-fleet", "state_dir": str(tmp_path / "state")}
    verdict = wired.canaries[CANARY_COLLECT](target, descriptor(), {"instance_id": "i-1"})
    assert verdict["reason_code"] == "canary_target_unobserved" and read == [lane]
    # The owner-qualified canary is the incumbent file check: bound to the target's descriptor
    # receipt file, never to either store.
    assert wired.canaries[CANARY_FLEET] is owner_qualified_canary
    plan = {"plan_id": "plan-1"}
    assert wired.canaries[CANARY_FLEET](target, descriptor(), {"instance_id": "i-1"}, plan=plan)["reason_code"] \
        == "canary_owner_receipt_missing"
    Path(target["state_dir"]).mkdir(parents=True)
    (Path(target["state_dir"]) / canary_receipt_file("plan-1")).write_text(json.dumps(
        {"descriptor_sha256": descriptor_digest(descriptor()), "instance_id": "i-1", "passed": True,
         "evidence": "owner-evidence"}), encoding="utf-8")
    passed = wired.canaries[CANARY_FLEET](target, descriptor(), {"instance_id": "i-1"}, plan=plan)
    assert passed["passed"] is True and passed["evidence"] == "owner-evidence"


# ----- process environment and observer ----------------------------------------------------------
def test_a_lane_tick_leaves_the_process_environment_and_closes_its_lane_observer(tmp_path, monkeypatch):
    service = control_service(tmp_path)
    stores = LaneStores()
    monkeypatch.setenv("HARNESS_DATABASE_URL", CONTROL_DSN)
    monkeypatch.delenv(ENABLED_SETTING, raising=False)
    monkeypatch.setattr(host_delivery, "resolve_lane", routed_resolver(stores))
    monkeypatch.setattr(host_delivery, "_observer", forbid("the control observer"))
    monkeypatch.setattr(host_delivery, "_git", forbid("the control workspace"))
    monkeypatch.setattr(host_delivery, "_settings", lambda: {"HARNESS_DATABASE_URL": CONTROL_DSN})
    observed = []

    class Recorder:
        closed = 0

        def emit(self, *_args, **_kwargs):
            return None

        def close(self):
            Recorder.closed += 1

    def lane_observer(route):
        observed.append((route["store"], route["lane"]["runtime"]))
        return Recorder()
    monkeypatch.setattr(host_delivery, "_lane_observer", lane_observer)
    before = dict(os.environ)
    idle = execute(service, args("tick", plan=None, lane="harness"))
    ran = execute(service, args("run", once=True, interval=1, max_ticks=1, lane="harness"))
    assert idle["exit_code"] == 0 and idle["outcome"] == "idle" and idle["lane"] == "harness"
    assert ran["exit_code"] == 0 and ran["ticks"] == 1 and ran["lane"] == "harness"
    assert dict(os.environ) == before, "a lane command never mutates the process environment"
    # A managed or systemd child therefore inherits the control DSN, exactly as before.
    assert launcher_environment()["HARNESS_DATABASE_URL"] == CONTROL_DSN
    assert observed == [(stores.lane("harness"), str(tmp_path / "runtime-harness"))] * 2
    assert Recorder.closed == 2


def test_the_real_lane_observer_uses_the_lane_store_and_the_lane_runtime_spool(tmp_path):
    lane = LaneStores().lane("harness")
    runtime = tmp_path / "runtime-harness"
    observer = host_delivery._lane_observer({"store": lane, "lane": {"runtime": str(runtime)}})
    try:
        assert observer.store is lane
        assert Path(observer.directory.root) == runtime / "observations"
    finally:
        observer.close()


# ----- PostgreSQL: segregated control and lane schemas --------------------------------------------
@pytest.fixture
def segregated_pg(tmp_path):
    """A control schema holding the Fleet registry and two lane schemas, each migrated alone and
    reached through `lane_dsn`'s single search path, plus one unprovisioned lane and one lane that
    names the control schema itself. Everything is created and dropped here."""
    if os.environ.get("HARNESS_INTEGRATION") != "1":
        pytest.skip("Integration environment required")
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import make_conninfo

    from codex_harness.adapters.fleet_runtime import lane_dsn
    from codex_harness.adapters.store import PostgresStore
    from codex_harness.bootstrap import database_url

    base = database_url()
    suffix = uuid4().hex[:12]
    control, harness, interface = ("t_ctl_" + suffix, "t_harness_" + suffix, "t_iface_" + suffix)
    with psycopg.connect(base) as connection:
        for schema in (control, harness, interface):
            connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    try:
        control_dsn = make_conninfo(base, options="-c search_path=" + control)
        control_store = PostgresStore(control_dsn)
        control_store.migrate()
        for schema in (harness, interface):
            PostgresStore(lane_dsn(control_dsn, schema)).migrate()
        schemas = {"harness": harness, "interface": interface, "ghost": "t_ghost_" + suffix,
                   "self": control}
        Fleet(control_store).register(fleet_config(tmp_path, schemas))
        yield {"service": SimpleNamespace(store=control_store, org=organization()),
               "host": {"HARNESS_DATABASE_URL": control_dsn}, "schemas": schemas,
               "stores": {name: PostgresStore(lane_dsn(control_dsn, schema))
                          for name, schema in schemas.items() if name in ("harness", "interface")}}
    finally:
        with psycopg.connect(base) as connection:
            for schema in (control, harness, interface):
                connection.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema)))


def test_pg_lane_commands_write_only_the_lane_schema(segregated_pg, tmp_path, monkeypatch):
    service, host, stores = segregated_pg["service"], segregated_pg["host"], segregated_pg["stores"]
    monkeypatch.setattr(host_delivery, "_settings", lambda: dict(host))
    monkeypatch.setattr(host_delivery, "_git", forbid("the control workspace"))
    monkeypatch.delenv(ENABLED_SETTING, raising=False)
    registry = _write(tmp_path, targets_document(tmp_path))
    assert execute(service, args("register-targets", file=registry, lane="harness"))["lane"] == "harness"
    revision = commit_plan(tmp_path / "repo-harness", plan_document())
    assert execute(service, args("register", revision=revision, path=PLAN_PATH, lane="harness"))["exit_code"] == 0
    projection = execute(service, args("status", plan="lane-plan-1", lane="harness"))
    assert projection["exit_code"] == 0 and projection["deliveries"][0]["stage"] == "registered"
    assert [row["id"] for row in rows(stores["harness"], BUCKET_PLANS)] == ["lane-plan-1"]
    assert empty(service.store) and empty(stores["interface"])
    # The same default command, without a lane, still writes the control schema.
    execute(service, args("register-targets", file=_write(tmp_path, targets_document(tmp_path, "control-t"))))
    assert [row["id"] for row in rows(service.store, BUCKET_TARGETS)] == ["control-t"]
    assert [row["id"] for row in rows(stores["harness"], BUCKET_TARGETS)] == ["aibox-managed-fleet"]


def test_pg_wrong_lanes_refuse_and_the_gate_reads_the_control_schema(segregated_pg):
    service, host, stores = segregated_pg["service"], segregated_pg["host"], segregated_pg["stores"]
    for lane_id, reason in (("ghost", "lane_schema_mismatch"), ("self", "lane_is_control"),
                            ("missing", "lane_unknown")):
        with pytest.raises(DeliveryRefused) as refused:
            resolve_lane(service, lane_id, host=host)
        assert refused.value.reason_code == reason
    route = resolve_lane(service, "harness", host=host)
    assert route["store"].dsn == stores["harness"].dsn
    Fleet(service.store).reserve_unit("c" * 64, UNIT_CONDUCTOR, "harness", "labelled-held-conductor")
    gate = controller(service, enabled=False, store=route["store"]).hosts[KIND_MANAGED_SYSTEMD]
    with pytest.raises(DeliveryRefused) as refused:
        gate._activation_gate({"target_id": "aibox-managed-fleet"}, descriptor())
    assert refused.value.reason_code == "fleet_debt_held"
    with service.store.transaction() as tx:
        assert tx.get(BUCKET_CONTROL, CONTROL_KEY)[ACTIVATION_HOLD]["target_id"] == "aibox-managed-fleet"
    assert rows(route["store"], BUCKET_CONTROL) == [] and rows(stores["interface"], BUCKET_CONTROL) == []
