"""Cutover RH-8 F1/F2/F4 for Phase P (`compare/rehearsal/phase_p.py`): fail-closed admission, helper settlement, private ROOT.

Layer: harness tooling tests (never shipped). Expected results come from FLEET-RH8-REVIEW.md F1/F2/F4 "Verification"
and the spec's Expected results: each required command failing => nonzero verdict and no dependent step; a corrupt or
missing AOF => refusal; the positive path passes; paused=false => refusal; a helper that survives its client timeout
is found and removed while foreign and one-label controls survive; a removal failure is reported as residue and
blocks; ROOT is 0700 under umask 022. The production interfaces are replaced by a synthetic `Host`: NO production
container, volume, socket or path is touched. The one real-Docker test uses a labelled fixture through the guard's
opt-in forms and needs `ZEUS_TEST_DOCKER=1`; a skip under that opt-in is a failure.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import subprocess
import sys

import pytest
from _layout import REPO

sys.path.insert(0, str(REPO / "compare"))
from rehearsal import Refused  # noqa: E402
from rehearsal import copies as cp  # noqa: E402
from rehearsal import phase_p as pp  # noqa: E402
from rehearsal.sweep import sweep  # noqa: E402

guard = cp.provider_guard
DOCKER = os.environ.get(guard.DOCKER_OPT_IN_ENV) == "1"
needs_docker = pytest.mark.skipif(not DOCKER, reason="needs ZEUS_TEST_DOCKER=1 (real Docker)")
RUN8, OTHER8 = "9a8b7c6d", "11223344"
SOURCE = {"./appendonlydir/appendonly.aof.1.base.rdb": b"rdb-bytes", "./appendonlydir/appendonly.aof.1.incr.aof": b"incr",
          "./appendonlydir/appendonly.aof.manifest": b"file appendonly.aof.1.base.rdb seq 1 type b\n",
          "./dump.rdb": b"dump-bytes"}
MTIME = 1_700_000_000
SECRET = "SECRET-STDERR-BODY"


class SyntheticHost:
    """Models the production interfaces Phase P uses. `fail`/`hang` are keyed `<kind>#<n>` (n counts that kind)."""

    def __init__(self, *, paused=True, active=0, fail=None, hang=(), source=None, rm_fails=False, containers=None):
        self.paused, self.active, self.fail, self.hang = paused, active, dict(fail or {}), set(hang)
        self.source, self.rm_fails = dict(SOURCE if source is None else source), rm_fails
        self.containers = dict(containers or {})  # name -> (id, labels)
        self.calls, self.counts, self.snapped = [], {}, False
        self.bracket_change = self.copy_corrupt = self.copy_missing = self.production_changes = False
        self.guard_env = {guard.DOCKER_OPT_IN_ENV: "1"}

    # -- the Host interface --
    def open(self, path, mode="r"):
        path = str(path)
        if path == pp.MONITORING:
            return io.StringIO(json.dumps({"sources": {"fleet": {"data": {"paused": self.paused}}}}))
        if path == pp.HEARTBEAT:
            return io.StringIO(json.dumps({"active": self.active, "unresolved": 0, "instance_id": "inst-1"}))
        return pp.Host().open(path, mode)

    def run(self, argv, *, timeout=120, stdout=None):
        argv = list(argv)
        self.calls.append(argv)
        kind = self._kind(argv)
        self.counts[kind] = self.counts.get(kind, 0) + 1
        key = f"{kind}#{self.counts[kind]}"
        if kind in ("snap", "check"):
            self._start_helper(argv)
        if key in self.hang:
            raise subprocess.TimeoutExpired(argv, timeout)  # the client times out; a started helper survives
        rc = self.fail.get(key, 0)
        err = f"{SECRET} {kind}" if rc else ""
        done = lambda out="": subprocess.CompletedProcess(argv, rc, out if rc == 0 else "", err)  # noqa: E731
        if kind == "inspect":
            moved = self.production_changes and self.snapped
            return done(json.dumps({"Id": "id-" + argv[-1], "Image": "img", "RestartCount": 0, "ExecIDs": [],
                                    "StartedAt": "t2" if moved else "t1"}))
        if kind == "diff":
            return done("C /etc\nA /etc/x\n" + ("A /changed\n" if self.production_changes and self.snapped else ""))
        if kind == "psql":
            sql = argv[argv.index("-c") + 1]
            return done("postgres\nzeus_aibox\nzeus_aibox_migration\nzeus_canary_1\n" if "pg_database" in sql
                        else "zeus_aibox|app|3\n")
        if kind == "dump":
            if rc == 0:
                stdout.write(b"PGDMP" + hashlib.sha256(" ".join(argv).encode()).digest())
            proc = done()
            proc.stderr = err.encode()
            return proc
        if kind == "snap":
            if rc == 0:
                self._snap(argv)
            self.snapped = True
            return self._finish_helper(argv, done())
        if kind == "check":
            return self._finish_helper(argv, done())
        if kind == "ps":
            return self._ps(argv, done)
        if kind == "rm":
            name = argv[3]
            if self.rm_fails:
                return subprocess.CompletedProcess(argv, 1, "", "cannot remove")
            self.containers.pop(name, None)
            return done()
        raise AssertionError(f"unexpected command {argv}")

    # -- internals --
    @staticmethod
    def _kind(argv):
        if argv[1] in ("inspect", "diff", "ps", "rm"):
            return argv[1]
        if argv[1] == "exec":
            return "dump" if "pg_dump" in argv else "psql"
        if argv[1] == "run":
            return "check" if any("redis-check-aof" in a for a in argv) else "snap"  # the check runs inside sh -c (owner, 67cbf0c4+)
        raise AssertionError(f"unexpected command {argv}")

    def _start_helper(self, argv):
        labels = [argv[i + 1] for i, a in enumerate(argv) if a == "--label"]
        self.containers[argv[argv.index("--name") + 1]] = ("id-" + argv[argv.index("--name") + 1], labels)

    def _finish_helper(self, argv, proc):
        self.containers.pop(argv[argv.index("--name") + 1], None)  # --rm: the helper is gone when its client returns
        return proc

    def _ps(self, argv, done):
        guard.docker_policy(argv, self.guard_env)  # the settle listing form is one the real guard admits
        wanted = [a.split("=", 2)[2] for a in argv if a.startswith("label=zeus.rehearsal.run=")]
        rows = [(n, i) for n, (i, labels) in self.containers.items()
                if f"zeus.rehearsal.run={wanted[0]}" in labels and guard.FIXTURE_LABEL in labels]
        return done("".join(f"{n if argv[-1] == '{{.Names}}' else i}\n" for n, i in rows))

    def _snap(self, argv):
        mounts = {m.split("dst=")[1].split(",")[0]: m.split("src=")[1].split(",")[0]
                  for m in (argv[i + 1] for i, a in enumerate(argv) if a == "--mount") if "type=bind" in m}
        out, meta = mounts["/out"], mounts["/meta"]
        lines = [f"{p} {len(b)} {MTIME} {hashlib.sha256(b).hexdigest()}" for p, b in sorted(self.source.items())]
        for p, b in self.source.items():
            if self.copy_missing and p.endswith(".incr.aof"):
                continue
            target = os.path.join(out, p[2:])
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, "wb") as fh:
                fh.write(b + (b"X" if self.copy_corrupt and p == "./dump.rdb" else b""))
        with open(os.path.join(meta, "before"), "w") as fh:
            fh.write("\n".join(lines) + "\n")
        after = [re.sub(r"[0-9a-f]{64}$", "0" * 64, lines[0])] + lines[1:] if self.bracket_change else lines
        with open(os.path.join(meta, "after"), "w") as fh:
            fh.write("\n".join(after) + "\n")


def attempt(tmp_path, host, run8=RUN8):
    root, evidence = tmp_path / "root", tmp_path / "evidence"
    code = pp.main(str(root), str(evidence), run8, host)
    rec = json.loads((evidence / "phase-p.json").read_text())
    return code, rec, root, evidence


def kinds(host):
    return [host._kind(c) for c in host.calls]


def test_the_positive_path_passes_and_records_size_mtime_sha256_and_zero_helpers(tmp_path):
    old = os.umask(0o022)
    try:
        host = SyntheticHost()
        code, rec, root, evidence = attempt(tmp_path, host)
    finally:
        os.umask(old)
    assert code == 0 and rec["verdict"] == "ok"
    assert (os.lstat(root).st_mode & 0o777) == 0o700 and (os.lstat(root / "p").st_mode & 0o777) == 0o700  # F4
    assert (root / cp.MARKER).read_text().strip() == RUN8
    p3 = next(s for s in rec["steps"] if s["step"] == "P3")
    assert p3["ok"] and p3["manifest_equal"] and p3["copy_equals_manifest"] and p3["aof_check_exit"] == 0
    assert p3["manifest_fields"] == ["path", "size", "mtime", "sha256"] and p3["files"] == len(SOURCE)
    before = (root / "p" / "redis-meta" / "before").read_text().splitlines()
    want = "./dump.rdb %d %d %s" % (len(SOURCE["./dump.rdb"]), MTIME, hashlib.sha256(SOURCE["./dump.rdb"]).hexdigest())
    assert want in before  # size, mtime and sha256 per file (oracle: the synthetic source bytes)
    assert rec["helpers_before"] == {"removed": 0, "residue": []} and rec["helpers_after"] == {"removed": 0, "residue": []}
    assert host.containers == {} and [d["bytes"] > 0 for s in rec["steps"] if s["step"] in ("P2a", "P2b")
                                      for d in s["dumps"]] == [True] * 4
    dump = root / "p" / "zeus_aibox.d0a.dump"
    assert (os.lstat(dump).st_mode & 0o777) == 0o600 and dump.read_bytes().startswith(b"PGDMP")


@pytest.mark.parametrize("key,step", [("inspect#1", "P0"), ("diff#2", "P0"), ("psql#1", "P1"), ("psql#2", "P1"),
                                      ("dump#1", "P2a"), ("dump#2", "P2a"), ("snap#1", "P3"), ("check#1", "P3"),
                                      ("dump#3", "P2b"), ("dump#4", "P2b"), ("inspect#3", "P4"), ("diff#4", "P4")])
def test_each_required_command_failing_stops_with_a_receipt_and_no_dependent_step(tmp_path, key, step):
    host = SyntheticHost(fail={key: 1})
    code, rec, root, evidence = attempt(tmp_path, host)
    assert code == 1 and rec["verdict"].startswith("STOP:") and step in rec["verdict"]
    assert rec["failed_step"]["step"] == step and ("_exit_1" in rec["failed_step"]["reason"] or "failed" in rec["failed_step"]["reason"])
    order = ["P0", "P1", "P2a", "P3", "P2b", "P4"]
    done = [s["step"] for s in rec["steps"]]
    assert not any(order.index(s) > order.index(step) for s in done), done  # nothing dependent ran
    assert SECRET not in (evidence / "phase-p.json").read_text()  # stderr bodies are never recorded
    if key == "dump#1":
        assert "snap" not in kinds(host) and (root / "p" / "zeus_aibox.d0a.dump").exists()  # failed raw file kept
    assert host.containers == {}


@pytest.mark.parametrize("flag,reason", [("bracket_change", "redis_bracket_unequal"), ("copy_corrupt", "redis_copy_unequal"),
                                         ("copy_missing", "redis_copy_unequal")])
def test_an_unequal_redis_bracket_or_copy_stops_before_the_second_dump(tmp_path, flag, reason):
    host = SyntheticHost()
    setattr(host, flag, True)
    code, rec, _, _ = attempt(tmp_path, host)
    assert code == 1 and rec["failed_step"]["reason"] == reason and "check" not in kinds(host)
    assert [s["step"] for s in rec["steps"]] == ["P0", "P1", "P2a", "P3"]


def test_a_missing_aof_manifest_refuses_and_a_corrupt_aof_check_stops(tmp_path):
    no_manifest = {k: v for k, v in SOURCE.items() if not k.endswith(".manifest")}
    (tmp_path / "a").mkdir()
    code, rec, _, _ = attempt(tmp_path / "a", SyntheticHost(source=no_manifest))
    assert code == 1 and rec["failed_step"]["reason"] == "aof_manifest_missing_or_ambiguous"
    (tmp_path / "b").mkdir()
    code, rec, _, _ = attempt(tmp_path / "b", SyntheticHost(fail={"check#1": 1}))  # redis-check-aof exits nonzero
    assert code == 1 and rec["failed_step"]["reason"] == "aof_check_exit_1" and rec["verdict"] != "ok"


def test_a_dump_that_exits_zero_but_is_empty_or_not_an_archive_stops(tmp_path):
    class Empty(SyntheticHost):
        def run(self, argv, **kw):
            if self._kind(argv) == "dump":
                self.calls.append(argv)
                return subprocess.CompletedProcess(argv, 0, "", b"")
            return super().run(argv, **kw)

    code, rec, _, _ = attempt(tmp_path, Empty())
    assert code == 1 and rec["failed_step"]["reason"] == "dump_zeus_aibox_failed" and rec["steps"][-1]["dumps"][0]["bytes"] == 0


def test_a_missing_scope_database_stops_at_p1(tmp_path):
    class NoMigration(SyntheticHost):
        def run(self, argv, **kw):
            done = super().run(argv, **kw)
            if self._kind(argv) == "psql" and "pg_database" in argv[-1]:
                done.stdout = "postgres\nzeus_aibox\n"
            return done

    code, rec, _, _ = attempt(tmp_path, NoMigration())
    assert code == 1 and rec["failed_step"]["reason"] == "scope_database_missing"


def test_paused_false_or_not_quiet_is_refused_before_any_acquisition(tmp_path):
    for n, host in enumerate((SyntheticHost(paused=False), SyntheticHost(active=1))):
        (tmp_path / str(n)).mkdir()
        code, rec, root, _ = attempt(tmp_path / str(n), host)
        assert code == 1 and rec["verdict"].startswith("refused")
        assert set(kinds(host)) <= {"ps", "inspect", "diff"} and not (root / "p" / "redis").exists()


def test_production_changing_during_the_bracket_is_a_stop_not_ok(tmp_path):
    host = SyntheticHost()
    host.production_changes = True
    code, rec, _, _ = attempt(tmp_path, host)
    assert code == 1 and rec["verdict"] == "STOP: production changed during Phase P"


def test_an_unreadable_gate_input_leaves_a_bounded_receipt(tmp_path):
    class NoMonitoring(SyntheticHost):
        def open(self, path, mode="r"):
            if str(path) == pp.MONITORING:
                raise FileNotFoundError(f"{SECRET} {path}")
            return super().open(path, mode)

    code, rec, _, evidence = attempt(tmp_path, NoMonitoring())
    assert code == 1 and rec["failed_step"] == {"step": "P0", "reason": "exception:FileNotFoundError"}
    assert SECRET not in (evidence / "phase-p.json").read_text()


# ---- F2: helper lifetime ----

def test_helpers_carry_both_labels_and_the_run_owned_names_and_the_sweep_sees_them(tmp_path):
    host = SyntheticHost(hang={"check#1"})  # the aof-check client times out and its helper survives
    code, rec, _, _ = attempt(tmp_path, host)
    helper_runs = [c for c in host.calls if c[1] == "run"]
    assert len(helper_runs) == 2
    for argv in helper_runs:
        labels = [argv[i + 1] for i, a in enumerate(argv) if a == "--label"]
        name = argv[argv.index("--name") + 1]
        assert labels == [guard.FIXTURE_LABEL, f"zeus.rehearsal.run={RUN8}"]
        assert re.fullmatch(rf"zeus-test-fixture-rh-{RUN8}-p-[a-z-]+", name)
        assert "--network" in argv and argv[argv.index("--network") + 1] == "none"
    assert code == 1 and rec["failed_step"] == {"step": "P3", "reason": "timeout", "timeout_s": 900}
    # settled: the surviving helper was removed by name and absence proven
    assert rec["helpers_after"] == {"removed": 1, "residue": []} and host.containers == {}


def test_the_run_owned_sweep_selects_a_surviving_phase_p_helper(tmp_path):
    host = SyntheticHost()
    host._start_helper(["docker", "run", *pp.helper_labels(RUN8), "--name", pp.helper_name(RUN8, "redis-snap")])
    docker = lambda *args, timeout=120: host.run(["docker", *args], timeout=timeout)  # noqa: E731
    assert sweep(RUN8, docker=docker) == {"removed": 1, "residue": [], "root_removed": None}
    assert host.containers == {}


def foreign_controls():
    one_label = (f"zeus-test-fixture-rh-{RUN8}-p-redis-snap-ctl", ("id-ctl", [guard.FIXTURE_LABEL]))
    other_run = (f"zeus-test-fixture-rh-{OTHER8}-p-redis-snap", ("id-other", [guard.FIXTURE_LABEL, f"zeus.rehearsal.run={OTHER8}"]))
    return dict([one_label, other_run])


def test_settle_removes_only_this_attempts_owned_helper_and_spares_foreign_and_one_label_controls():
    mine = pp.helper_name(RUN8, "redis-snap")
    host = SyntheticHost(containers={mine: ("id-mine", [guard.FIXTURE_LABEL, f"zeus.rehearsal.run={RUN8}"]),
                                     **foreign_controls()})
    assert pp.settle_helpers(host, RUN8) == {"removed": 1, "residue": []}
    assert set(host.containers) == set(foreign_controls())
    removals = [c for c in host.calls if c[1] == "rm"]
    assert removals == [["docker", "rm", "-f", mine]]  # by name; never a pattern or a bulk removal


def test_an_unknown_labelled_container_holds_and_is_not_removed():
    stranger = f"zeus-test-fixture-rh-{RUN8}-S-pg"  # carries both labels, but is not a Phase P helper of this attempt
    host = SyntheticHost(containers={stranger: ("id-s", [guard.FIXTURE_LABEL, f"zeus.rehearsal.run={RUN8}"])})
    with pytest.raises(pp.HoldError) as caught:
        pp.settle_helpers(host, RUN8)
    assert caught.value.ids == ["id-s"] and stranger in host.containers
    assert [c for c in host.calls if c[1] == "rm"] == []


def test_a_removal_failure_reports_residue_and_blocks_the_attempt(tmp_path):
    mine = pp.helper_name(RUN8, "redis-snap")
    host = SyntheticHost(containers={mine: ("id-mine", [guard.FIXTURE_LABEL, f"zeus.rehearsal.run={RUN8}"])}, rm_fails=True)
    code, rec, root, _ = attempt(tmp_path, host)
    assert code == 1 and rec["verdict"].startswith("HOLD") and rec["failed_step"]["reason"] == "helper_residue"
    assert rec["failed_step"]["ids"] == ["id-mine"] and "P0" not in [s["step"] for s in rec["steps"]]
    assert not (root / "p" / "redis").exists()  # no acquisition while an owned helper could not be settled


def test_a_residue_after_an_otherwise_ok_attempt_still_blocks(tmp_path):
    class Leaves(SyntheticHost):
        def _finish_helper(self, argv, proc):
            return proc  # the helper survives even a normal completion

    code, rec, _, _ = attempt(tmp_path, Leaves(rm_fails=True))
    assert code == 1 and rec["verdict"].startswith("HOLD") and rec["helpers_after"]["residue"]


# ---- F4: ROOT ----

def test_phase_p_refuses_an_existing_root_or_evidence_dir_before_any_effect(tmp_path):
    (tmp_path / "root").mkdir()
    host = SyntheticHost()
    with pytest.raises(Refused) as caught:
        pp.main(str(tmp_path / "root"), str(tmp_path / "evidence"), RUN8, host)
    assert caught.value.code == "path_exists" and host.calls == [] and not (tmp_path / "evidence").exists()


# ---- the target seam (RH-2b): production defaults, stand-ins only from code ----

STANDINS = pp.Targets(pg=f"zeus-test-fixture-rh-{RUN8}-prod-pg", redis=f"zeus-test-fixture-rh-{RUN8}-prod-redis",
                      redis_volume=f"zeus-test-fixture-rh-{RUN8}-prod-redisdata", monitoring="/stand-in/monitoring.json",
                      heartbeat="/stand-in/heartbeat.json")


def test_the_default_targets_are_exactly_the_production_names_and_paths():
    """Expected values are the literal production names (spec What 1), not read from the module's constants."""
    assert pp.DEFAULT_TARGETS == pp.Targets("zeus-aibox-postgres", "zeus-aibox-redis", "zeus-aibox-redisdata",
                                            "/srv/zeus/runtime/control/monitoring.json",
                                            "/srv/zeus/runtime/managed-fleet/heartbeat.json")
    assert pp.PhaseP("/r", "/e", RUN8).targets == pp.DEFAULT_TARGETS


def test_main_takes_no_target_override():
    """Structural contract (spec What 1: `main` never accepts other targets): the public signature has no such name."""
    import inspect

    assert list(inspect.signature(pp.main).parameters) == ["root", "evidence", "run8", "host"]
    with pytest.raises(TypeError):
        pp.main("/r", "/e", RUN8, None, targets=STANDINS)  # noqa


def test_a_phase_p_run_over_stand_in_targets_names_only_those_and_never_a_production_resource(tmp_path):
    class StandInHost(SyntheticHost):
        def open(self, path, mode="r"):
            mapped = {STANDINS.monitoring: pp.MONITORING, STANDINS.heartbeat: pp.HEARTBEAT}
            assert str(path) not in (pp.MONITORING, pp.HEARTBEAT)  # a production path is never opened
            return super().open(mapped.get(str(path), path), mode)

    host = StandInHost()
    root, evidence = tmp_path / "root", tmp_path / "evidence"
    cp.create_root(root, RUN8)
    os.makedirs(root / "p", mode=0o700)
    os.makedirs(evidence)
    assert pp.PhaseP(str(root), str(evidence), RUN8, host, STANDINS).run() == 0
    flat = " ".join(" ".join(c) for c in host.calls)
    assert "zeus-aibox" not in flat
    assert f"src={STANDINS.redis_volume},dst=/src,readonly,volume-nocopy" in flat
    named = {c[c.index("inspect") + 3] if c[1] == "inspect" else c[2] for c in host.calls if c[1] in ("inspect", "diff")}
    assert named == {STANDINS.pg, STANDINS.redis}
    assert any(c[1] == "exec" and c[2] == STANDINS.pg for c in host.calls)


# ---- real Docker (ZEUS_TEST_DOCKER=1): a real labelled fixture helper that outlives its client ----

class DockerHost(pp.Host):
    def run(self, argv, *, timeout=120, stdout=None):
        assert argv[0] == "docker"
        return cp.guarded_docker(argv[1:], timeout=timeout)


def _inspect(name):
    return cp.guarded_docker(["inspect", "--format", "{{.Id}}", name])


@needs_docker
def test_real_docker_a_helper_outliving_its_client_is_settled_and_a_one_label_control_survives():
    mine, control = pp.helper_name(RUN8, "aof-check"), f"zeus-test-fixture-rh-{RUN8}-p-ctl"
    common = dict(image=cp.REDIS_IMAGE, mounts=[], uid=os.getuid(), gid=os.getgid(), memory="256m",
                  command=["redis-server", "--port", "0", "--unixsocket", "/tmp/c.sock", "--save", ""])
    owned = cp.run_argv(mine, labels=[guard.FIXTURE_LABEL, f"{cp.RUN_LABEL}={RUN8}"], **common)
    ctl = cp.run_argv(control, labels=[guard.FIXTURE_LABEL], **common)
    try:
        for argv in (owned, ctl):
            started = cp.guarded_docker(argv)
            assert started.returncode == 0, started.stderr
        host = DockerHost()
        assert pp._list_helpers(host, RUN8, "{{.Names}}") == [mine]  # still running: its client is long gone
        assert pp.settle_helpers(host, RUN8) == {"removed": 1, "residue": []}
        assert _inspect(mine).returncode != 0 and _inspect(control).returncode == 0
        assert pp._list_helpers(host, RUN8, "{{.ID}}") == []
    finally:
        for name in (mine, control):
            cp.guarded_docker(["rm", "-f", name])
    assert _inspect(mine).returncode != 0 and _inspect(control).returncode != 0
