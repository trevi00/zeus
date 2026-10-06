"""Cutover RH-6a: the rehearsal R7a restore runner (`compare/rehearsal/r7a.py`) and its fakebin docker shim.

Layer: harness tooling tests (never shipped). Expected results come from the task spec, the rehearsal design "9. R7" / AC10
(PASS = the receipt reaches renamed/verified, the R7 catalog equals D0, compare-redis equal; the restore uses the PINNED
tooling) and critique #10 (the shim forwards only `docker exec <R7 pg> {pg_restore|sha256sum}` after the label check and
refuses everything else with exit 97): the SOURCE copy's own catalog digest and Redis facts, taken before the run, are the
D0 oracle; the shim's accepted and refused forms are the critique's list. The pinned release is a fixture directory whose
`.venv/bin/python` runs this repository's `codex_harness.adapters.host_migration` (the tool of the target tree). The shim tests
need no Docker (a stub stands in for the real `docker`); the restore tests need `ZEUS_TEST_DOCKER=1` and
`ZEUS_TEST_DOCKER_PGEXEC=1`, and a skip under those opt-ins is a failure.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys

import pytest
from _layout import REPO

sys.path.insert(0, str(REPO / "compare"))
from rehearsal import copies as cp  # noqa: E402
from rehearsal import d0, r7a  # noqa: E402
from rehearsal.sweep import sweep  # noqa: E402

guard = cp.provider_guard
DOCKER = os.environ.get(guard.DOCKER_OPT_IN_ENV) == "1" and os.environ.get(guard.DOCKER_PGEXEC_ENV) == "1"
needs_docker = pytest.mark.skipif(not DOCKER, reason="needs ZEUS_TEST_DOCKER=1 and ZEUS_TEST_DOCKER_PGEXEC=1")
RUN8, TAMPER8, DATABASE = "7a1c5e93", "7a1c5e94", "rhdb"
PG = cp.PG_SOCKET_DIR

# ---- the shim (pure: a stub stands in for the real docker) ----

STUB = '''#!/usr/bin/python3
import json, os, sys
with open(os.environ["STUB_LOG"], "a") as handle:
    handle.write(json.dumps(sys.argv[1:]) + "\\n")
if sys.argv[1] == "inspect":
    labels = json.load(open(os.environ["STUB_LABELS"]))
    name = sys.argv[-1]
    if name not in labels:
        sys.exit(1)
    print(labels[name])
    sys.exit(0)
print("stub-exec-ok")
'''


class Shim:
    def __init__(self, tmp_path, run8=RUN8, labels=None):
        self.work = tmp_path / "r7"
        self.work.mkdir()
        self.stub, self.calls, self.labels = tmp_path / "realdocker", tmp_path / "stub.log", tmp_path / "labels.json"
        self.stub.write_text(STUB)
        self.stub.chmod(0o700)
        self.name = cp.fixture_name(run8, "R7", "pg")
        self.labels.write_text(json.dumps({self.name: f"{run8}|1"} if labels is None else labels))
        self.log = self.work / "fakebin.log"
        self.path = r7a.write_shim(self.work / "fakebin", run8, str(self.stub), self.log)

    def run(self, *args):
        # the shim IS the fixture `docker` binary: the in-process provider guard (R-P) admits it from its own directory
        env = {"PATH": "/usr/bin:/bin", "STUB_LOG": str(self.calls), "STUB_LABELS": str(self.labels),
               guard.FIXTURE_DIR_ENV: str(self.path.parent)}
        return subprocess.run([str(self.path), *args], env=env, capture_output=True, text=True, timeout=60)

    def forwarded(self):
        return [json.loads(line) for line in self.calls.read_text().splitlines()] if self.calls.exists() else []


@pytest.fixture
def shim(tmp_path):
    return Shim(tmp_path)


def test_the_shim_is_generated_owner_only_and_exclusively(tmp_path):
    made = Shim(tmp_path)
    assert stat.S_IMODE(made.path.stat().st_mode) == 0o700 and made.path.name == "docker"
    assert made.path.parent == made.work / "fakebin"
    with pytest.raises(FileExistsError):  # never overwritten
        r7a.write_shim(made.work / "fakebin", RUN8, str(made.stub), made.log)


def test_the_shim_forwards_the_tools_pg_restore_and_sha256sum_forms_after_the_label_check(shim):
    listing = shim.run("exec", shim.name, "pg_restore", "-U", "zeus", "-h", PG, "-l", "/dump/rhdb.dump")
    checksum = shim.run("exec", shim.name, "sha256sum", "/dump/rhdb.dump")
    restore = shim.run("exec", shim.name, "pg_restore", "-U", "zeus", "-h", PG, "--exit-on-error", "--single-transaction",
                       "-d", "rhdb", "/dump/rhdb.dump")
    assert [r.returncode for r in (listing, checksum, restore)] == [0, 0, 0]
    assert listing.stdout.strip() == "stub-exec-ok"
    inspect = ["inspect", "--format", '{{index .Config.Labels "zeus.rehearsal.run"}}|{{index .Config.Labels '
               '"zeus.test.fixture"}}', shim.name]
    assert shim.forwarded() == [inspect, ["exec", shim.name, "pg_restore", "-U", "zeus", "-h", PG, "-l", "/dump/rhdb.dump"],
                                inspect, ["exec", shim.name, "sha256sum", "/dump/rhdb.dump"], inspect,
                                ["exec", shim.name, "pg_restore", "-U", "zeus", "-h", PG, "--exit-on-error",
                                 "--single-transaction", "-d", "rhdb", "/dump/rhdb.dump"]]
    rows = r7a.read_shim_log(shim.log)
    assert [(r["verdict"], r["reason"]) for r in rows] == [("forward", "pg_restore"), ("forward", "sha256sum"),
                                                           ("forward", "pg_restore")]


@pytest.mark.parametrize("name", ["zeus-aibox-postgres", "zeus-aibox-redis", "zeus-test-fixture-rh-deadbeef-R7-pg",
                                  "zeus-test-fixture-rh-7a1c5e93-R7-redis", "zeus-test-fixture-rh-7a1c5e93-S-pg"])
def test_the_shim_refuses_a_production_name_and_any_other_container_with_exit_97_logged_and_never_calls_docker(shim, name):
    done = shim.run("exec", name, "pg_restore", "-U", "zeus", "-h", PG, "-l", "/dump/rhdb.dump")
    assert done.returncode == 97 and "refused (container_name)" in done.stderr and done.stdout == ""
    assert shim.forwarded() == []  # not even the label inspection: refused first
    rows = r7a.read_shim_log(shim.log)
    assert len(rows) == 1 and rows[0]["verdict"] == "refuse" and rows[0]["reason"] == "container_name"
    assert rows[0]["argv"][1] == name


@pytest.mark.parametrize("labels", [{}, {"__": "x"}], ids=["unknown-container", "label-lookup-fails"])
def test_the_shim_refuses_a_fixture_named_container_whose_inspection_fails(tmp_path, labels):
    made = Shim(tmp_path, labels=labels)
    done = made.run("exec", made.name, "sha256sum", "/dump/rhdb.dump")
    assert done.returncode == 97 and "refused (label)" in done.stderr
    assert [call[0] for call in made.forwarded()] == ["inspect"]  # inspected, never exec'd


@pytest.mark.parametrize("value", ["|1", "7a1c5e93|", "7a1c5e94|1", "7a1c5e93|0", "x"])
def test_the_shim_refuses_an_unlabelled_or_wrongly_labelled_fixture_container(tmp_path, value):
    made = Shim(tmp_path)
    made.labels.write_text(json.dumps({made.name: value}))
    done = made.run("exec", made.name, "pg_restore", "-U", "zeus", "-h", PG, "-l", "/dump/rhdb.dump")
    assert done.returncode == 97 and "refused (label)" in done.stderr
    assert all(call[0] != "exec" for call in made.forwarded())
    assert r7a.read_shim_log(made.log)[-1] == {"argv": ["exec", made.name, "pg_restore", "-U", "zeus", "-h", PG, "-l",
                                                          "/dump/rhdb.dump"], "reason": "label", "verdict": "refuse"}


@pytest.mark.parametrize("argv,reason", [
    (["ps", "-a"], "form"), (["run", "-d", "alpine"], "form"), ([], "form"), (["exec"], "form"),
    (["exec", "-it", "NAME", "pg_restore"], "container_name"),
    (["exec", "NAME", "psql", "-U", "zeus"], "program"), (["exec", "NAME", "sh", "-c", "id"], "program"),
    (["exec", "NAME", "pg_dump", "-U", "zeus", "-h", PG, "x"], "program"),
    (["exec", "NAME", "sha256sum", "/etc/passwd"], "sha256sum_operand"),
    (["exec", "NAME", "sha256sum", "/dump/a", "/dump/b"], "sha256sum_operand"),
    (["exec", "NAME", "pg_restore", "-l", "/dump/a.dump"], "pg_tool_prefix"),
    (["exec", "NAME", "pg_restore", "-U", "zeus", "-h", "/tmp", "/dump/a.dump"], "pg_tool_prefix"),
    (["exec", "NAME", "pg_restore", "-U", "zeus", "-h", PG, "-d", "x", "/etc/passwd"], "pg_tool_path"),
    (["exec", "NAME", "pg_restore", "-U", "zeus", "-h", PG, "--file=/tmp/out"], "pg_tool_path"),
    (["exec", "NAME", "pg_restore", "-U", "zeus", "-h", PG, "-d", "..x"], "pg_tool_dotdot"),
])
def test_the_shim_refuses_every_other_form_with_exit_97_and_a_logged_line(shim, argv, reason):
    argv = [shim.name if a == "NAME" else a for a in argv]
    done = shim.run(*argv)
    assert done.returncode == 97 and f"refused ({reason}" in done.stderr
    assert shim.forwarded() == [] or all(call[0] == "inspect" for call in shim.forwarded())
    rows = r7a.read_shim_log(shim.log)
    assert len(rows) == 1 and rows[0]["verdict"] == "refuse" and rows[0]["reason"].startswith(reason)


def test_the_shim_is_on_the_path_of_the_pg_restore_child_only_never_in_this_process_or_the_redis_child(tmp_path):
    made = Shim(tmp_path)
    before = os.environ["PATH"]
    with_shim = r7a.tool_env(made.work, shim=made.path, pg_dsn_value="host=x")
    without = r7a.tool_env(made.work, shim=None)
    assert with_shim["PATH"] == f"{made.path.parent}:/usr/bin:/bin" and with_shim[r7a.DSN_ENV] == "host=x"
    assert without["PATH"] == "/usr/bin:/bin" and r7a.DSN_ENV not in without
    assert os.environ["PATH"] == before and str(made.path.parent) not in os.environ["PATH"]
    found = shutil.which("docker")
    assert found is None or not found.startswith(str(tmp_path))  # this process still resolves the real docker


def test_a_release_without_the_pinned_tooling_is_refused_before_anything_starts(tmp_path):
    with pytest.raises(r7a.Refused) as caught:
        r7a.run_r7a(cp.Copies(RUN8, tmp_path / "root"), release=tmp_path / "no-release", dump="rhdb.dump",
                    database=DATABASE, d0_record={"facts": {}}, out=tmp_path / "out")
    assert caught.value.code == "tooling_missing" and not (tmp_path / "root").exists()


# ---- the restore over real copies ----

class World:
    pass


def _seed(world):
    import psycopg
    import redis

    s = world.copies.copies["S"]
    with psycopg.connect(cp.pg_dsn(s.pg_socket), autocommit=True) as conn:
        conn.execute("CREATE ROLE rh_owner NOLOGIN")
        conn.execute(f"CREATE DATABASE {DATABASE}")
    with psycopg.connect(cp.pg_dsn(s.pg_socket, DATABASE), autocommit=True) as conn:
        conn.execute("CREATE SCHEMA app AUTHORIZATION rh_owner")
        conn.execute("CREATE TABLE app.items (id integer PRIMARY KEY, name text NOT NULL, qty numeric(8,2))")
        conn.execute("INSERT INTO app.items SELECT g, 'item-' || g, g * 1.5 FROM generate_series(1, 25) g")
        conn.execute("CREATE INDEX items_name ON app.items (name)")
        conn.execute("ALTER TABLE app.items OWNER TO rh_owner")
    client = redis.Redis(unix_socket_path=str(s.redis_socket / "redis.sock"))
    client.set("rh:string:1", "v")
    client.hset("rh:hash:1", mapping={"a": "1", "b": "2"})
    client.rpush("rh:list:1", "x", "y", "z")
    for i in range(1, 4):
        client.xadd(f"rh:stream:{i}", {"k": "v"})
    client.close()


def _build(tmp_path_factory, run8):
    w = World()
    w.root, w.out = tmp_path_factory.mktemp("r7") / "root", tmp_path_factory.mktemp("r7out")
    w.run8 = run8
    w.copies = cp.Copies(run8, w.root)
    w.cleanup = lambda: sweep(run8, w.root)
    try:
        w.copies.start("S")
        _seed(w)
        argv = ["docker", "exec", w.copies.copies["S"].pg_name, "pg_dump", "-U", "zeus", "-h", PG, "-Fc", DATABASE]
        opt_in = {guard.DOCKER_OPT_IN_ENV: "1", guard.DOCKER_PGEXEC_ENV: "1"}
        guard.docker_policy(argv, opt_in)  # the guard admits this exact form before it is spawned
        dump = subprocess.run(argv, capture_output=True, timeout=300, env={**os.environ, **opt_in})
        assert dump.returncode == 0, dump.stderr[-300:]
        (w.copies.source / "rhdb.dump").write_bytes(dump.stdout)
        (w.copies.source / "redis" / "stray-aof-marker").mkdir(parents=True)  # an AOF directory a seeded R7 would inherit
        # D0 = the source copy's own digest and Redis facts, taken BEFORE the restore (the oracle of the run)
        s = w.copies.copies["S"]
        dbs, prefixes, failures = d0.redis_facts(s.redis_socket / "redis.sock")
        assert failures == []
        w.digest = cp.catalog_sha256(s.pg_socket, DATABASE)
        w.d0 = {"facts": {"catalog_sha256": w.digest, "redis_dbs": dbs, "redis_prefixes": prefixes}}
        release = w.out / "pinned-release"
        (release / ".venv" / "bin").mkdir(parents=True)
        (release / ".venv" / "bin" / "python").write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n')
        (release / ".venv" / "bin" / "python").chmod(0o755)
        w.release = release
        w.sha = __import__("hashlib").sha256((w.copies.source / "rhdb.dump").read_bytes()).hexdigest()
        return w
    except BaseException:
        w.cleanup()
        raise


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    if not DOCKER:
        pytest.skip("needs ZEUS_TEST_DOCKER=1 and ZEUS_TEST_DOCKER_PGEXEC=1")
    w = _build(tmp_path_factory, RUN8)
    try:
        yield w
    finally:
        w.cleanup()


@pytest.fixture(scope="module")
def tampered(tmp_path_factory):
    if not DOCKER:
        pytest.skip("needs ZEUS_TEST_DOCKER=1 and ZEUS_TEST_DOCKER_PGEXEC=1")
    w = _build(tmp_path_factory, TAMPER8)
    try:
        yield w
    finally:
        w.cleanup()


@pytest.fixture(scope="module")
def restored(world):
    """One real R7a run (the module's R7 copy is fresh once); every test below reads its record or its R7 copy."""
    calls = []

    def recording(argv, env, timeout):
        calls.append((argv[3], env["PATH"]))
        return r7a._spawn(argv, env, timeout)

    before = os.environ["PATH"]
    document = r7a.run_r7a(world.copies, release=world.release, dump="rhdb.dump", database=DATABASE, d0_record=world.d0,
                           out=world.out / "r7a", spawn=recording)
    assert os.environ["PATH"] == before
    return document, calls


@needs_docker
def test_the_d0_archive_restores_with_the_pinned_tooling_and_the_catalog_and_redis_equal_d0(world, restored):
    import psycopg
    import redis

    document, _ = restored
    facts = document["facts"]
    assert document["status"] == "ok" and facts["failures"] == []
    assert facts["receipt"]["state"] == "renamed" and facts["receipt"]["verified"] is True
    assert facts["catalog_sha256_r7"] == facts["catalog_sha256_d0"] == world.digest and facts["catalog_equals_d0"] is True
    assert facts["redis"]["equals_d0"] is True and facts["redis_copy"]["exit"] == 0 and facts["pg_restore_db"]["exit"] == 0
    # independently of the record: the fixture's own constants (25 item rows, 3+1+1+1+... keys) are on the R7 server
    r7 = world.copies.copies["R7"]
    with psycopg.connect(cp.pg_dsn(r7.pg_socket, DATABASE)) as conn:
        assert conn.execute("SELECT count(*), max(id) FROM app.items").fetchone() == (25, 25)
    assert redis.Redis(unix_socket_path=str(r7.redis_socket / "redis.sock")).dbsize() == 6  # string, hash, list, 3 streams
    assert facts["release"] == "pinned-release" and facts["tooling_module"] == "codex_harness.adapters.host_migration"
    receipt = json.loads((world.root / "r7" / "receipt.json").read_text())
    assert receipt["state"] == "renamed" and receipt["archive_sha256"] == world.sha
    assert facts["roles"]["roles_created_nologin"] == ["rh_owner"]  # the declared preflight, on the disposable server only


@needs_docker
def test_the_record_declares_the_non_namespace_step_and_the_shim_log_and_is_private_and_body_free(world, restored):
    document, _ = restored
    facts = document["facts"]
    assert facts["non_namespace_step"] is True and facts["shim"]["declared_non_namespace"] is True
    assert facts["shim"]["forwarded"] == 3 and facts["shim"]["refused"] == 0  # pg_restore -l, sha256sum, restore
    assert set(facts["shim"]["programs"]) == {"pg_restore", "sha256sum"}
    rows = r7a.read_shim_log(world.root / "r7" / "fakebin.log")
    assert all(r["verdict"] == "forward" for r in rows) and len(rows) == facts["shim"]["forwarded"]
    path = world.out / "r7a" / "r7.json"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert "item-" not in path.read_text() and "rh_owner" in path.read_text()  # facts name roles, never a row body


@needs_docker
def test_the_shim_is_on_the_path_of_pg_restore_db_only_and_r7_started_without_the_seeded_aof(world, restored):
    _, calls = restored
    shim_dir = str(world.root / "r7" / "fakebin")
    assert calls == [("pg-restore-db", f"{shim_dir}:/usr/bin:/bin"), ("redis-copy", "/usr/bin:/bin")]
    assert shim_dir not in os.environ["PATH"]
    assert not (world.root / "R7" / "redis" / "stray-aof-marker").exists()  # `empty_redis`: no seed from ROOT/p/redis
    assert (world.root / "S" / "redis").is_dir() and not (world.root / "S" / "redis" / "stray-aof-marker").exists()
    assert (world.copies.source / "redis" / "stray-aof-marker").is_dir()  # the source directory itself is untouched


@needs_docker
def test_a_second_run_never_overwrites_the_work_directory_or_the_record(world, restored):
    with pytest.raises(FileExistsError):
        r7a.run_r7a(world.copies, release=world.release, dump="rhdb.dump", database=DATABASE, d0_record=world.d0,
                    out=world.out / "again")


@needs_docker
def test_a_tampered_archive_sha_makes_the_pinned_tool_refuse_and_the_run_fails_with_the_evidence_written(tampered):
    with pytest.raises(r7a.R7aFailed) as caught:
        r7a.run_r7a(tampered.copies, release=tampered.release, dump="rhdb.dump", database=DATABASE,
                    d0_record=tampered.d0, out=tampered.out / "r7a", archive_sha256="0" * 64)
    assert caught.value.failures == ["r7a_catalog_unreadable:OperationalError", "r7a_pg_restore_db_exit:1",
                                     "r7a_receipt_state:None"]
    written = json.loads((tampered.out / "r7a" / "r7.json").read_text())
    facts = written["facts"]
    assert written["status"] == "failed" and facts["pg_restore_db"]["refused"] == "archive_digest_mismatch"
    assert facts["catalog_equals_d0"] is False and facts["shim"]["refused"] == 0  # the tool refused; the shim did not
    assert not (tampered.root / "r7" / "receipt.json").exists()  # nothing was created before the digest check
