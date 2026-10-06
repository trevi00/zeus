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
from pathlib import Path

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
