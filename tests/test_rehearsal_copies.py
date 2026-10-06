"""Cutover RH-1a: the rehearsal evidence writer, disposable PG/Redis copies, the role preflight and the sweep.

Layer: harness tooling tests (`compare/rehearsal/`, never shipped). Expected results come from the task spec's
acceptance criteria and the rehearsal design (Restore steps: "Every copy must show catalog sha256 == D0 and Redis
inventory == D0 before use"): the source's own digest/inventory, computed on the source server, is the oracle.
The negative controls need no Docker; the real-Docker tests skip unless `ZEUS_TEST_DOCKER=1`.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time

import pytest
from _layout import REPO

sys.path.insert(0, str(REPO / "compare"))
from rehearsal import Refused  # noqa: E402
from rehearsal import copies as cp  # noqa: E402
from rehearsal.evidence import Evidence  # noqa: E402
from rehearsal.sweep import SweepResidue, sweep  # noqa: E402

guard = cp.provider_guard
DOCKER = os.environ.get(guard.DOCKER_OPT_IN_ENV) == "1"
needs_docker = pytest.mark.skipif(not DOCKER, reason="needs ZEUS_TEST_DOCKER=1 (real Docker)")
RUN8, SRC8 = "1a2b3c4d", "5e6f7a8b"


class FakeDocker:
    """Models labelled containers; every argv it receives must be admitted by the real guard policy."""

    def __init__(self, containers=None, *, keeps=()):
        self.containers = dict(containers or {})  # name -> (id, labels)
        self.keeps, self.calls = set(keeps), []
        self.env = {guard.DOCKER_OPT_IN_ENV: "1"}

    def __call__(self, *args, timeout=120):
        self.calls.append(args)
        guard.docker_policy(["docker", *args], self.env)
        ok = lambda out="": subprocess.CompletedProcess(args, 0, out, "")  # noqa: E731
        if args[0] == "ps":
            wanted = {a.rsplit("=", 1)[1] for a in args if a.startswith("label=zeus.rehearsal.run=")}
            fixture = "label=zeus.test.fixture=1" in args
            rows = [(name, cid) for name, (cid, labels) in self.containers.items()
                    if f"{cp.RUN_LABEL}={next(iter(wanted))}" in labels and (not fixture or guard.FIXTURE_LABEL in labels)]
            return ok("".join(f"{name if args[-1] == '{{.Names}}' else cid}\n" for name, cid in rows))
        if args[0] == "rm":
            for name in args[2:]:
                if name not in self.keeps:
                    self.containers.pop(name, None)
            return ok()
        raise AssertionError(f"unexpected docker call {args}")


def labelled(run8, *, fixture=True, rehearsal=True):
    return [*([guard.FIXTURE_LABEL] if fixture else []), *([f"{cp.RUN_LABEL}={run8}"] if rehearsal else [])]


# ---- negative controls: refused with their named error, before any docker call (no Docker needed) ----

def test_unknown_copy_names_are_refused_before_any_docker_call(tmp_path):
    fake = FakeDocker()
    copies = cp.Copies(RUN8, tmp_path / "r", docker=fake)
    for name in ("zeus-aibox-postgres", "X", "s", "", "S/../A", "seal_b"):
        with pytest.raises(Refused) as caught:
            copies.start(name)
        assert caught.value.code == "unknown_copy", name
    assert fake.calls == [] and not (tmp_path / "r").exists()


@pytest.mark.parametrize("kwargs,code", [({"publish": ["127.0.0.1:5432:5432"]}, "published_port"),
                                         ({"volumes": ["pgdata:/var/lib/postgresql/data"]}, "named_volume")])
def test_a_published_port_and_a_named_volume_are_refused_before_any_docker_call(tmp_path, kwargs, code):
    fake = FakeDocker()
    with pytest.raises(Refused) as caught:
        cp.Copies(RUN8, tmp_path / "r", docker=fake).start("S", **kwargs)
    assert caught.value.code == code and fake.calls == []


def test_run_argv_refuses_a_production_name_a_foreign_name_and_a_non_absolute_mount():
    base = dict(image=cp.PG_IMAGE, labels=[guard.FIXTURE_LABEL], mounts=[], uid=1000, gid=1000, memory="1g")
    for name, code in (("zeus-aibox-postgres", "production_name"), ("zeus-aibox-redis", "production_name"),
                       ("postgres", "not_fixture_name"), ("zeus-test-fixture-s0-pg-1", "not_fixture_name")):
        with pytest.raises(Refused) as caught:
            cp.run_argv(name, **base)
        assert caught.value.code == code, name
    with pytest.raises(Refused) as caught:
        cp.run_argv("zeus-test-fixture-rh-1a2b3c4d-S-pg", **{**base, "mounts": [("pgdata", "/data", False)]})
    assert caught.value.code == "named_volume"


def test_trace_mode_is_off_by_default_and_opt_in_adds_only_the_statement_log_in_the_pgdata(tmp_path):
    """RH-4c: the default postgres command is the pre-trace one; the opt-in adds the collector, a log directory INSIDE the
    bind-mounted pgdata (the host reads it from ROOT, never `docker logs`) and statement logging; the guard admits it."""
    assert cp.pg_command() == cp.pg_command(False) == ["-c", "listen_addresses="]
    traced = cp.pg_command(True)
    assert traced[:2] == ["-c", "listen_addresses="]
    assert traced[2:] == ["-c", "logging_collector=on", "-c", f"log_directory={cp.PGDATA}/{cp.TRACE_LOG_DIR}",
                          "-c", "log_statement=all"]
    assert cp.TRACE_LOG_DIR and not cp.TRACE_LOG_DIR.startswith("/") and ".." not in cp.TRACE_LOG_DIR
    for trace in (False, True):
        argv = cp.run_argv(cp.fixture_name(RUN8, "S", "pg"), image=cp.PG_IMAGE, labels=[guard.FIXTURE_LABEL, f"{cp.RUN_LABEL}={RUN8}"],
                           mounts=[(tmp_path / "pgdata", cp.PGDATA, False)], uid=1000, gid=1000, memory="4g",
                           command=cp.pg_command(trace))
        guard.docker_policy(["docker", *argv], {guard.DOCKER_OPT_IN_ENV: "1", guard.DOCKER_BIND_ROOT_ENV: str(tmp_path)})
    assert cp.Copy("S", "p", "r", tmp_path, tmp_path).trace_dir is None  # a copy without trace mode has no log directory


@pytest.mark.parametrize("run8", ["", "1A2B3C4D", "1a2b3c4", "1a2b3c4d5", "1a2b3c4g", "../../etc", None, 12345678])
def test_a_bad_run8_is_refused_everywhere(tmp_path, run8):
    for build in (lambda: Evidence(run8, tmp_path / "e"), lambda: cp.Copies(run8, tmp_path / "r"),
                  lambda: sweep(run8, docker=FakeDocker())):
        with pytest.raises(Refused) as caught:
            build()
        assert caught.value.code == "bad_run8"


def test_an_existing_evidence_file_is_refused_and_left_untouched(tmp_path):
    root = tmp_path / "e"
    root.mkdir()
    (root / "run-start.json").write_text("precious", encoding="utf-8")
    with pytest.raises(Refused) as caught:
        Evidence(RUN8, root).start({"a": 1})
    assert caught.value.code == "evidence_exists" and (root / "run-start.json").read_text() == "precious"
    # the other files too: a pre-existing steps.jsonl / run-exit.json / SHA256SUMS is never overwritten or appended
    for name in ("steps.jsonl", "run-exit.json", "SHA256SUMS"):
        other = tmp_path / ("e-" + name)
        other.mkdir()
        (other / name).write_text("precious", encoding="utf-8")
        run = Evidence(RUN8, other)
        run.start()
        with pytest.raises(Refused) as caught:
            run.step("s", "ok") if name == "steps.jsonl" else run.finish("ok")
        assert caught.value.code == "evidence_exists", name
        assert (other / name).read_text() == "precious"


@pytest.mark.parametrize("facts,code", [
    ({"digest_of": "/srv/zeus/secrets/token.txt"}, "secret_path_fact"),
    ({"/srv/zeus/secrets/token.txt": "ab" * 32}, "secret_path_fact"),
    ({"nested": {"files": ["a/secrets/b"]}}, "secret_path_fact"),
    ({"env": {"HOME": "x"}}, "env_value_fact"), ({"environment": []}, "env_value_fact"),
    ({"rows": [1, 2]}, "record_body_fact"), ({"body": "x"}, "record_body_fact"),
    ({"note": "x" * 5000}, "record_body_fact"), ({"object": object()}, "fact_type"),
    ({"a": {"b": {"c": {"d": {"e": {"f": 1}}}}}}, "fact_too_deep"),
])
def test_an_unbounded_secret_or_body_fact_is_refused_with_a_named_error(tmp_path, facts, code):
    run = Evidence(RUN8, tmp_path / "e")
    run.start()
    with pytest.raises(Refused) as caught:
        run.step("probe", "ok", facts)
    assert caught.value.code == code
    assert not (tmp_path / "e" / "steps.jsonl").exists()  # nothing was written for the refused fact


def test_an_environment_value_is_refused_as_a_fact(tmp_path, monkeypatch):
    monkeypatch.setenv("RH_TEST_ODD_VALUE", "sentinel-env-value-1234")
    run = Evidence(RUN8, tmp_path / "e")
    with pytest.raises(Refused) as caught:
        run.start({"copied": "sentinel-env-value-1234"})
    assert caught.value.code == "env_value_fact"


def test_the_evidence_lifecycle_writes_each_file_once_and_the_sums_last(tmp_path):
    ticks = iter(range(100))
    run = Evidence(RUN8, tmp_path / "e" / RUN8, clock=lambda: f"t{next(ticks)}")
    with pytest.raises(Refused) as caught:
        run.step("early", "ok")
    assert caught.value.code == "evidence_order"
    run.start({"purpose": "synthetic"})
    run.step("copy-S", "ok", {"roles": 1})
    run.step("restore-S", "failed", {"reason": "synthetic"})
    run.finish("failed", {"steps": 2})
    root = tmp_path / "e" / RUN8
    assert sorted(p.name for p in root.iterdir()) == ["SHA256SUMS", "run-exit.json", "run-start.json", "steps.jsonl"]
    rows = [json.loads(line) for line in (root / "steps.jsonl").read_text().splitlines()]
    assert rows == [{"at": "t1", "step": "copy-S", "status": "ok", "facts": {"roles": 1}},
                    {"at": "t2", "step": "restore-S", "status": "failed", "facts": {"reason": "synthetic"}}]
    assert json.loads((root / "run-start.json").read_text())["run8"] == RUN8
    assert json.loads((root / "run-exit.json").read_text())["status"] == "failed"
    sums = dict(line.split("  ")[::-1] for line in (root / "SHA256SUMS").read_text().splitlines())
    assert set(sums) == {"run-start.json", "steps.jsonl", "run-exit.json"}
    for name, digest in sums.items():
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == digest
    assert (root / "SHA256SUMS").stat().st_mtime_ns >= (root / "run-exit.json").stat().st_mtime_ns
    for late in (lambda: run.step("late", "ok"), lambda: run.finish("ok"), lambda: run.start()):
        with pytest.raises(Refused):
            late()


def test_the_toc_owner_field_is_the_role_source():
    listing = "\n".join([
        ";", "; Archive created at 2026-10-06", "; Selected TOC Entries:", ";",
        "3; 2615 2200 SCHEMA - public pg_database_owner",
        "216; 2615 16390 SCHEMA - app rh_owner",
        "217; 1259 16391 TABLE app items rh_owner",
        "3300; 0 0 ACL - TABLE app items rh_owner",
        "5; 0 0 ENCODING - ENCODING ",  # an entry without an owner ends in a space: its tag is not a role
        "6; 2606 16400 CONSTRAINT app items items_pkey zeus",
        "7; 0 0 COMMENT - SCHEMA app -"])
    assert cp.toc_roles(listing) == ["pg_database_owner", "rh_owner", "zeus"]


def test_the_sweep_removes_only_containers_with_both_labels_and_proves_absence():
    both = ("zeus-test-fixture-rh-" + RUN8 + "-S-pg", ("id-1", labelled(RUN8)))
    both2 = ("zeus-test-fixture-rh-" + RUN8 + "-S-redis", ("id-2", labelled(RUN8)))
    fixture_only = ("zeus-test-fixture-rh-" + RUN8 + "-ctl-pg", ("id-3", labelled(RUN8, rehearsal=False)))
    other_run = ("zeus-test-fixture-rh-aaaaaaaa-S-pg", ("id-4", labelled("aaaaaaaa")))
    fake = FakeDocker(dict([both, both2, fixture_only, other_run]))
    assert sweep(RUN8, docker=fake) == {"removed": 2, "residue": [], "root_removed": None}
    assert set(fake.containers) == {fixture_only[0], other_run[0]}
    removals = [c for c in fake.calls if c[0] == "rm"]
    assert sorted(c[2] for c in removals) == sorted([both[0], both2[0]])  # by name, from the admitted listing


def test_the_sweep_refuses_a_labelled_production_name_and_removes_nothing():
    fake = FakeDocker({"zeus-aibox-postgres": ("id-9", labelled(RUN8)),
                       "zeus-test-fixture-rh-" + RUN8 + "-S-pg": ("id-1", labelled(RUN8))})
    with pytest.raises(Refused) as caught:
        sweep(RUN8, docker=fake)
    assert caught.value.code == "production_name"
    assert [c for c in fake.calls if c[0] == "rm"] == [] and len(fake.containers) == 2


def test_the_sweep_raises_with_the_residue_ids_when_removal_does_not_hold(tmp_path):
    name = "zeus-test-fixture-rh-" + RUN8 + "-S-pg"
    fake = FakeDocker({name: ("id-stuck", labelled(RUN8))}, keeps={name})
    root = tmp_path / "r"
    root.mkdir()
    (root / cp.MARKER).write_text(RUN8 + "\n")
    with pytest.raises(SweepResidue) as caught:
        sweep(RUN8, root, docker=fake)
    assert caught.value.ids == ["id-stuck"] and root.exists()  # ROOT goes last: never while residue remains


def test_the_sweep_leaves_a_labelled_name_outside_the_run_naming_as_residue():
    fake = FakeDocker({"zeus-test-fixture-other-name": ("id-5", labelled(RUN8))})
    with pytest.raises(SweepResidue) as caught:
        sweep(RUN8, docker=fake)
    assert caught.value.ids == ["id-5"] and "zeus-test-fixture-other-name" in fake.containers


def test_the_sweep_removes_only_a_root_this_run_marked(tmp_path):
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    (foreign / "keep.txt").write_text("x")
    with pytest.raises(Refused) as caught:
        sweep(RUN8, foreign, docker=FakeDocker())
    assert caught.value.code == "root_not_owned" and (foreign / "keep.txt").exists()
    mine = tmp_path / "mine"
    (mine / "p" / "redis").mkdir(parents=True)
    (mine / cp.MARKER).write_text(RUN8 + "\n")
    assert sweep(RUN8, mine, docker=FakeDocker()) == {"removed": 0, "residue": [], "root_removed": True}
    assert not mine.exists()
    assert sweep(RUN8, mine, docker=FakeDocker())["root_removed"] is True  # already gone: still proven absent


# ---- RH-8 F4: ROOT itself is a private 0700 directory (source: FLEET-RH8-REVIEW.md F4 "Verification") ----

def _mode(path):
    return os.lstat(path).st_mode & 0o777


def test_root_is_created_0700_under_a_022_umask_and_continuation_is_supported(tmp_path):
    old = os.umask(0o022)
    try:
        root = tmp_path / "parent" / "r"
        copies = cp.Copies(RUN8, root, docker=FakeDocker())
        copies.prepare_root()
        assert _mode(root) == 0o700 and _mode(copies.source) == 0o700
        assert (root / cp.MARKER).read_text().strip() == RUN8
        copies.prepare_root()  # an existing safe owned root: continuation still works
        assert _mode(root) == 0o700
    finally:
        os.umask(old)


@pytest.mark.parametrize("kind,code", [("permissive", "root_mode"), ("symlink", "root_symlink"),
                                       ("file", "root_not_directory")])
def test_an_unsafe_pre_existing_root_is_refused_before_any_effect(tmp_path, kind, code):
    root, real = tmp_path / "r", tmp_path / "real"
    real.mkdir()
    if kind == "permissive":
        root.mkdir()
        root.chmod(0o755)
    elif kind == "symlink":
        os.symlink(real, root)
    else:
        root.write_text("x")
    fake = FakeDocker()
    with pytest.raises(Refused) as caught:
        cp.Copies(RUN8, root, docker=fake).start("S")
    assert caught.value.code == code and fake.calls == []
    assert not (real / cp.MARKER).exists() and not (real / "p").exists()  # nothing was adopted through the link
    if kind == "permissive":
        assert not (root / cp.MARKER).exists() and not (root / "p").exists()


def test_a_root_owned_by_another_uid_is_refused(tmp_path, monkeypatch):
    root = tmp_path / "r"
    root.mkdir(mode=0o700)
    real_uid = os.getuid()
    monkeypatch.setattr(cp.os, "getuid", lambda: real_uid + 1)
    with pytest.raises(Refused) as caught:
        cp.Copies(RUN8, root, docker=FakeDocker()).prepare_root()
    assert caught.value.code == "root_foreign_owner" and not (root / cp.MARKER).exists()


def test_a_root_marked_for_another_run_is_still_refused(tmp_path):
    root = tmp_path / "r"
    cp.create_root(root, SRC8)
    with pytest.raises(Refused) as caught:
        cp.Copies(RUN8, root, docker=FakeDocker()).prepare_root()
    assert caught.value.code == "root_foreign"


# ---- real Docker (ZEUS_TEST_DOCKER=1): copies, restore, inventory, sweep ----

DATABASE = "rhdb"


def _docker_bytes(root, *args):
    env = {**os.environ, guard.DOCKER_OPT_IN_ENV: "1", guard.DOCKER_PGEXEC_ENV: "1",
           guard.DOCKER_BIND_ROOT_ENV: str(root)}
    guard.docker_policy(["docker", *args], env)
    return subprocess.run(["docker", *args], env=env, capture_output=True, timeout=300)


def _labelled_ids(run8):
    done = cp.guarded_docker(["ps", "-a", "--filter", f"label={cp.RUN_LABEL}={run8}", "--format", "{{.ID}}"])
    assert done.returncode == 0, done.stderr
    return done.stdout.split()


def _seed_postgres(src):
    import psycopg

    with psycopg.connect(cp.pg_dsn(src.copies["A"].pg_socket), autocommit=True) as conn:
        conn.execute("CREATE ROLE rh_owner NOLOGIN")
        conn.execute(f"CREATE DATABASE {DATABASE}")
    with psycopg.connect(cp.pg_dsn(src.copies["A"].pg_socket, DATABASE), autocommit=True) as conn:
        conn.execute("CREATE SCHEMA app AUTHORIZATION rh_owner")
        conn.execute("CREATE TABLE app.items (id integer PRIMARY KEY, name text NOT NULL, qty numeric(8,2))")
        conn.execute("INSERT INTO app.items SELECT g, 'item-' || g, g * 1.5 FROM generate_series(1, 25) g")
        conn.execute("CREATE INDEX items_name ON app.items (name)")
        conn.execute("CREATE VIEW app.big AS SELECT id FROM app.items WHERE qty > 10")
        conn.execute("ALTER TABLE app.items OWNER TO rh_owner")
        conn.execute("GRANT SELECT ON app.items TO rh_owner")


def _seed_redis(src):
    import redis

    client = redis.Redis(unix_socket_path=str(src.copies["A"].redis_socket / "redis.sock"))
    client.set("rh:string:1", "v")
    client.hset("rh:hash:1", mapping={"a": "1", "b": "2"})
    client.rpush("rh:list:1", "x", "y", "z")
    client.sadd("rh:set:1", "m", "n")
    client.zadd("rh:zset:1", {"p": 1, "q": 2})
    for i in range(1, 4):
        client.xadd(f"rh:stream:{i}", {"k": "v"})
    for _ in range(4):
        client.xadd("rh:stream:3", {"k": "w"})
    client.xadd("rh:other:abcdef0123456789", {"k": "v"})
    inventory = cp.redis_inventory(src.copies["A"].redis_socket / "redis.sock")
    client.shutdown(save=False)  # a clean shutdown flushes the AOF; the container (--rm) then disappears
    client.close()
    deadline = time.monotonic() + 30
    while src.docker("inspect", "--format", "{{.Id}}", src.copies["A"].redis_name).returncode == 0:
        assert time.monotonic() < deadline, "source redis did not stop"
        time.sleep(0.5)
    return inventory


class World:
    pass


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    if not DOCKER:
        pytest.skip("needs ZEUS_TEST_DOCKER=1 (real Docker)")
    base = tmp_path_factory.mktemp("rh")
    w = World()
    w.src_root, w.root = base / "s", base / "t"
    w.src, w.dst = cp.Copies(SRC8, w.src_root), cp.Copies(RUN8, w.root)
    try:
        w.src.start("A")
        _seed_postgres(w.src)
        w.source_digest = cp.catalog_sha256(w.src.copies["A"].pg_socket, DATABASE)
        w.dst.prepare_root()
        dump = _docker_bytes(w.src_root, "exec", w.src.copies["A"].pg_name, "pg_dump", "-U", "zeus", "-h",
                             cp.PG_SOCKET_DIR, "-Fc", DATABASE)
        assert dump.returncode == 0, dump.stderr[-300:]
        (w.dst.source / "rhdb.dump").write_bytes(dump.stdout)
        w.source_inventory = _seed_redis(w.src)
        shutil.copytree(w.src_root / "A" / "redis", w.dst.source / "redis")
        w.handle = w.dst.start("S")
        w.restored = w.dst.restore("S", "rhdb.dump", DATABASE)
        yield w
    finally:
        for run8, root in ((SRC8, w.src_root), (RUN8, w.root)):
            sweep(run8, root)


@needs_docker
def test_the_restored_copy_has_the_source_catalog_digest(world):
    assert len(world.source_digest) == 64
    assert world.restored["catalog_sha256"] == world.source_digest
    assert world.dst.catalog_sha256("S", DATABASE) == world.source_digest
    assert world.restored["catalog_digest_source"].endswith("host_migration.catalog_digest")


@needs_docker
def test_the_copy_redis_inventory_equals_the_source_aof_inventory(world):
    inventory = world.dst.redis_inventory("S")
    assert world.source_inventory["keys"] == 9 and set(world.source_inventory["types"]) == {
        "string", "hash", "list", "set", "zset", "stream"}  # the seeded data, so equality is not vacuous
    assert inventory == world.source_inventory
    assert world.source_inventory["streams"] == {  # the seeded streams: 1+1+5 entries, and the hex-id key
        "rh:other:*": {"keys": 1, "entries": 1}, "rh:stream:*": {"keys": 3, "entries": 7}}
    # this copy runs over its OWN working copy of the AOF, not the source's directory
    assert (world.root / "S" / "redis" / "appendonlydir").is_dir()
    assert (world.root / "S" / "redis") != (world.dst.source / "redis")


@needs_docker
def test_the_role_preflight_creates_the_missing_owner_role_nologin_and_declares_it(world):
    import psycopg

    assert world.restored["roles_created_nologin"] == ["rh_owner"]
    assert "zeus" in world.restored["roles_in_toc"] and "zeus" not in world.restored["roles_created_nologin"]
    with psycopg.connect(cp.pg_dsn(world.handle.pg_socket)) as conn:
        assert conn.execute("SELECT rolcanlogin, rolsuper FROM pg_roles WHERE rolname = 'rh_owner'").fetchone() \
            == (False, False)
    # a second preflight on the same server finds the role present and creates nothing
    assert world.dst.role_preflight("S", "rhdb.dump")["roles_created_nologin"] == []


@needs_docker
def test_the_copy_containers_are_labelled_networkless_capped_and_unpublished(world):
    uid, gid = os.getuid(), os.getgid()
    for kind, memory in (("pg", 4 << 30), ("redis", 1 << 30)):
        name = f"zeus-test-fixture-rh-{RUN8}-S-{kind}"
        done = cp.guarded_docker(["inspect", "--format", "{{json .}}", name])
        assert done.returncode == 0, done.stderr
        info = json.loads(done.stdout)
        labels = info["Config"]["Labels"]
        assert labels["zeus.test.fixture"] == "1" and labels[cp.RUN_LABEL] == RUN8 and labels[cp.COPY_LABEL] == "S"
        assert cp.OWNER_KEY in labels
        host = info["HostConfig"]
        assert host["NetworkMode"] == "none" and host["Memory"] == memory
        assert host["MemorySwap"] == (memory if kind == "pg" else host["MemorySwap"])
        assert not host["PortBindings"] and info["Config"]["User"] == f"{uid}:{gid}"
        assert info["Image"] and info["Config"]["Image"] == (cp.PG_IMAGE if kind == "pg" else cp.REDIS_IMAGE)
        assert all(m["Type"] == "bind" for m in info["Mounts"])
        sources = {m["Destination"]: (m["Source"], m["RW"]) for m in info["Mounts"]}
        if kind == "pg":
            assert sources["/dump"] == (str(world.dst.source), False)
    assert len(str(world.handle.pg_socket)) + len("/.s.PGSQL.5432") < 107


@needs_docker
def test_the_sweep_leaves_no_labelled_container_and_no_root_and_spares_a_one_label_container(world):
    run8 = RUN8
    control = f"zeus-test-fixture-rh-{run8}-ctl-redis"  # the run's own naming, but only the fixture label
    argv = cp.run_argv(control, image=cp.REDIS_IMAGE, labels=[guard.FIXTURE_LABEL, f"{cp.OWNER_KEY}=ctl"], mounts=[],
                       uid=os.getuid(), gid=os.getgid(), memory="256m",
                       command=["redis-server", "--port", "0", "--unixsocket", "/tmp/c.sock", "--save", ""])
    started = cp.guarded_docker(argv, root=world.root)
    assert started.returncode == 0, started.stderr
    control_id = started.stdout.strip()
    try:
        assert cp.guarded_docker(["inspect", "--format", "{{.Id}}", control]).stdout.strip() == control_id
        before = _labelled_ids(run8)
        assert len(before) == 2 and control_id not in " ".join(before)  # listing needs the rehearsal label
        result = sweep(run8, world.root)
        assert result == {"removed": 2, "residue": [], "root_removed": True}
        assert _labelled_ids(run8) == [] and not world.root.exists()
        still = cp.guarded_docker(["inspect", "--format", "{{.Id}}", control])
        assert still.returncode == 0 and still.stdout.strip() == control_id  # NOT removed: one label is not enough
    finally:
        cp.guarded_docker(["rm", "-f", control])  # by name: the guard admits no id removal
    gone = cp.guarded_docker(["inspect", "--format", "{{.Id}}", control])
    assert gone.returncode != 0
    assert sweep(run8, world.root) == {"removed": 0, "residue": [], "root_removed": True}


# ---- RH-1b: the closed, evidence-derived volatile list and its fail-closed snapshot ----
# Expected results: RH-8's review ("RH integration must supply the actual paths, stable-subtree verification and declared
# skew") and the rehearsal design R1 file roots. The observed names are the two read-only listings of 2026-10-06 (60 s
# apart): `runtime/control/monitoring.json`, new `runtime/control/observations/health/<id>.json` files and
# `runtime/managed-fleet/heartbeat.json` changed.

OBSERVED_CHANGING = ("runtime/control/monitoring.json", "runtime/control/observations/health/0123456789abcdef.json",
                     "runtime/managed-fleet/heartbeat.json")


def volatile_fixture(tmp_path):
    src = tmp_path / "prod"
    for rel, text in (("runtime/control/monitoring.json", "m0"), ("runtime/managed-fleet/heartbeat.json", "h0"),
                      ("runtime/control/observations/health/a.json", "a0"), ("runtime/tokobs/ledger.sqlite3", "t0"),
                      ("runtime/control/stable.json", "s0"), ("runtime/lanes/harness/x.txt", "x0"),
                      ("managed-fleet/runtimes/r1/file", "r0")):
        path = src / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="ascii")
    return src


def test_every_observed_changing_path_is_in_the_closed_list():
    for path in OBSERVED_CHANGING:
        assert cp._covered(path, cp.VOLATILE_PATHS), path
    assert cp.undeclared_changes({}, {p: (1, 1) for p in OBSERVED_CHANGING}) == []
    assert cp._covered("runtime/tokobs/ledger.sqlite3", cp.EXCLUDED_PATHS)


def test_each_volatile_entry_cites_a_writer_that_resolves_in_its_r0_tree():
    document = cp.load_volatile()
    assert set(document["r0_revisions"]) == {"5aa220fd", "ced20281", "08bb9a44", "1b9d746c", "5c67f099"}
    for entry in document["volatile"]:
        assert entry["writers"], entry["path"]
        for writer in entry["writers"]:
            shown = subprocess.run(["git", "show", f"{writer['rev']}:{writer['file']}"], cwd=REPO, capture_output=True,
                                   text=True)
            assert shown.returncode == 0, f"{writer['rev']}:{writer['file']} does not resolve"
            lines = shown.stdout.splitlines()
            assert 1 <= writer["line"] <= len(lines) and writer["text"] in lines[writer["line"] - 1], (entry["path"], writer)
    assert {e["path"] for e in document["volatile"]} == set(cp.VOLATILE_PATHS)


def test_an_entry_without_a_writer_citation_is_refused(tmp_path):
    document = cp.load_volatile()
    document["volatile"][0]["writers"] = []
    bad = tmp_path / "volatile.json"
    bad.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(Refused) as info:
        cp.load_volatile(bad)
    assert info.value.code == "volatile_entry_bad"


def test_an_undeclared_changing_path_refuses_volatile_undeclared(tmp_path):
    src = volatile_fixture(tmp_path)

    def rewrite_a_stable_file():
        (src / "runtime/control/stable.json").write_text("s1-changed", encoding="ascii")

    with pytest.raises(Refused) as info:
        cp.snapshot_volatile(src, tmp_path / "dst", during=rewrite_a_stable_file)
    assert info.value.code == "volatile_undeclared" and "runtime/control/stable.json" in info.value.detail
    # a new file and a vanished file are changes too
    with pytest.raises(Refused) as info:
        cp.snapshot_volatile(src, tmp_path / "dst2", during=lambda: (src / "runtime/lanes/harness/new.txt").write_text("n"))
    assert info.value.code == "volatile_undeclared" and "runtime/lanes/harness/new.txt" in info.value.detail
    with pytest.raises(Refused) as info:
        cp.snapshot_volatile(src, tmp_path / "dst3", during=lambda: (src / "managed-fleet/runtimes/r1/file").unlink())
    assert info.value.code == "volatile_undeclared"


def test_a_declared_path_changing_during_the_snapshot_is_snapshotted_once_and_an_excluded_one_is_skipped(tmp_path, monkeypatch):
    src, dst = volatile_fixture(tmp_path), tmp_path / "dst"
    reads = []
    original = cp.Path.read_bytes

    def counting(self):
        reads.append(self.name)
        return original(self)

    def writers():
        (src / "runtime/control/monitoring.json").write_text("m1-after-the-read", encoding="ascii")
        (src / "runtime/managed-fleet/heartbeat.json").write_text("h1-after-the-read", encoding="ascii")
        (src / "runtime/control/observations/health/b.json").write_text("b", encoding="ascii")
        (src / "runtime/tokobs/ledger.sqlite3").write_text("t1-excluded", encoding="ascii")

    monkeypatch.setattr(cp.Path, "read_bytes", counting)
    manifest = cp.snapshot_volatile(src, dst, during=writers)
    assert reads.count("monitoring.json") == 1 and reads.count("heartbeat.json") == 1 and reads.count("a.json") == 1
    assert (dst / "runtime/control/monitoring.json").read_text() == "m0"  # the single read, before the change
    assert not (dst / "runtime/control/observations/health/b.json").exists()
    assert not (dst / "runtime/tokobs").exists() and manifest["excluded"] == ["runtime/tokobs"]
    stable = manifest["stable"]
    assert stable["unchanged"] and stable["sha256"] == stable["sha256_after"] and stable["files"] == 3  # stable.json, x.txt, r1/file


def test_the_stable_digest_covers_only_stable_files_and_moves_when_one_changes(tmp_path):
    src = volatile_fixture(tmp_path)
    first = cp.scan_tree(src)
    (src / "runtime/control/monitoring.json").write_text("m-different-length", encoding="ascii")
    assert cp.stable_sha256(cp.scan_tree(src)) == cp.stable_sha256(first)
    (src / "runtime/control/stable.json").write_text("longer-stable", encoding="ascii")
    assert cp.stable_sha256(cp.scan_tree(src)) != cp.stable_sha256(first)
