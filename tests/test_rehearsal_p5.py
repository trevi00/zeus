"""RH-2 P5b-2: Phase P step P5 (`compare/rehearsal/phase_p.py`) over SYNTHETIC stand-ins, SyntheticHost docker and the real gnucp.

Layer: harness tooling tests. Expected results come from the task spec (rh2-p5b2-phase-p-step, Examples 1-3 and Expected
results 1-5) and E9 (Placement, run lock, Seal and validity): P5 sits between P2b and P4; a failed or interrupted P5 never
carries `ok` and leaves a seal `verify_seal` refuses; the P5 entry is bounded under the modelled unit environment; the
step ceilings sum the Host.run timeouts the code passes. A tripwire audit hook (gated, one per module) fails any
open/scandir/listdir/subprocess argv naming the real `/srv/zeus`; the production lock name is never bound.
"""

from __future__ import annotations

import dataclasses
import json
import os
import signal
import subprocess
import sys
import uuid

import pytest
from _layout import REPO
from test_rehearsal_phase_p import RUN8, SHIPPED, SyntheticHost, attempt, kinds

sys.path.insert(0, str(REPO / "compare"))
from rehearsal import (
    Refused,  # noqa: E402
    fileroots,  # noqa: E402
)
from rehearsal import phase_p as pp  # noqa: E402
from rehearsal import phase_p_controls as pc  # noqa: E402
from rehearsal.constants import create_root  # noqa: E402
from rehearsal.evidence import check_facts  # noqa: E402

REAL = "/srv/zeus"
ACTIVITY = "zeus_aibox|app|3"  # the SyntheticHost's pg_stat_activity line
_state = {"active": False, "hits": []}


def _hook(event, args):
    if not _state["active"]:
        return
    if event == "subprocess.Popen":
        scanned = [str(a) for a in (args[0], *args[1], *args[2:3])]
    elif event in ("open", "os.scandir", "os.listdir"):
        scanned = [str(args[0])] if args else []
    else:
        return
    if any(REAL in text for text in scanned):
        _state["hits"].append((event, scanned))
        raise AssertionError(f"tripwire: {event} names the real {REAL}")


sys.addaudithook(_hook)


@pytest.fixture(autouse=True)
def standin_srv(tmp_path, monkeypatch):
    srv = tmp_path / "standin-srv"
    pc.build_standin_srv(srv)
    monkeypatch.setattr(pp, "DEFAULT_TARGETS", dataclasses.replace(SHIPPED, srv=str(srv)))
    monkeypatch.setattr(pp, "RUN_LOCK", f"zeus-rehearsal-test-{uuid.uuid4().hex}")
    real_acquire = fileroots.acquire

    def acquire(host, source, *args, **kwargs):
        if os.path.normpath(str(source)) == REAL or os.path.normpath(str(source)).startswith(REAL + "/"):
            _state["hits"].append(("acquire", str(source)))
            raise AssertionError("acquire refused: the srv names the real /srv/zeus")
        return real_acquire(host, source, *args, **kwargs)

    monkeypatch.setattr(fileroots, "acquire", acquire)
    _state.update(active=True, hits=[])
    yield srv
    _state["active"] = False
    assert _state["hits"] == []


def step_of(rec, name):
    return next((s for s in rec["steps"] if s["step"] == name), None)


def new_file_in_repo(srv):
    (srv / "repo" / "late.txt").write_text("late")


class Hooked(SyntheticHost):
    """A SyntheticHost whose first cp runs `before` (it may raise)."""

    def __init__(self, before=None, **kw):
        super().__init__(**kw)
        self.before, self.fired = before, False

    def run(self, argv, **kw):
        if argv[0] == fileroots.CP and self.before and not self.fired:
            self.fired = True
            self.before()
        return super().run(argv, **kw)


def assert_p5_failed(code, rec, root, reason, **extra):
    """A failed P5: nothing after it, no `ok`, a receipt of this reason (never an `exception:` receipt), no valid seal."""
    assert code == 1 and rec["verdict"].startswith("STOP:")
    assert rec["failed_step"] == {"step": "P5", "reason": reason, **extra}
    assert not rec["failed_step"]["reason"].startswith("exception:")
    assert "P4" not in [s["step"] for s in rec["steps"]]
    entry = step_of(rec, "P5")
    assert "ok" not in entry
    with pytest.raises(Refused) as refused:
        fileroots.verify_seal(root / "seal", entry, RUN8)
    assert refused.value.code == "seal_invalid"
    return entry


# ---- positive (Example 1) ----

def test_a_full_stand_in_run_acquires_p5_between_p2b_and_p4(tmp_path):
    old = os.umask(0o022)
    try:
        host = SyntheticHost()
        code, rec, root, evidence = attempt(tmp_path, host)
    finally:
        os.umask(old)
    assert code == 0 and rec["verdict"] == "ok" and rec["schema"].endswith(":phase-p:3")
    assert [s["step"] for s in rec["steps"]] == ["P0", "P1", "P2a", "P3", "P2b", "P5", "P4"]
    p5 = step_of(rec, "P5")
    assert p5["input_kind"] == "synthetic" and p5["symlinks"]["allowed"] == 1 and p5["ok"] is True
    assert sorted(p5["roots"]) == sorted(i for i, _r in fileroots.STABLE_ROOTS) and all(r["ok"] for r in p5["roots"].values())
    assert p5["activity_start"] == [ACTIVITY] and p5["activity_end"] == [ACTIVITY]
    assert set(p5["skew"]) == {"d0b_finished_at", "p5_started_at", "p5_finished_at", "volatile_read_span_ns"}
    p2b = step_of(rec, "P2b")
    assert p5["skew"]["d0b_finished_at"] == p2b["finished_at"] and p5["skew"]["p5_started_at"] == p5["started_at"]
    assert p5["skew"]["p5_finished_at"] == p5["finished_at"]
    assert p2b["finished_at"] <= p5["started_at"] <= p5["finished_at"]
    for name in ("P2a", "P3", "P2b"):
        assert step_of(rec, name)["started_at"] and step_of(rec, name)["finished_at"]
    assert all(d["started_at"] <= d["finished_at"] for n in ("P2a", "P2b") for d in step_of(rec, n)["dumps"])
    complete = json.loads((root / "seal/meta/complete.json").read_text())
    assert len(complete["files"]) == 18
    assert fileroots.verify_seal(root / "seal", p5, rec["run8"])["files"] == 18
    # P5's host calls are exactly psql, eight cp, psql; both psql texts equal P1's
    seq = kinds(host)
    first = seq.index("cp")
    assert seq[first - 1:first + 9] == ["psql"] + ["cp"] * 8 + ["psql"] and seq[first + 9] == "inspect"
    sql = lambda argv: argv[argv.index("-c") + 1]  # noqa: E731
    psqls = [c for c in host.calls if host._kind(c) == "psql"]
    assert len(psqls) == 4 and sql(psqls[1]) == sql(psqls[2]) == sql(psqls[3])


# ---- negatives (Examples 2, Expected results 4) ----

def test_a_new_file_in_srv_repo_at_the_first_cp_is_volatile_undeclared(tmp_path, standin_srv):
    host = Hooked(before=lambda: new_file_in_repo(standin_srv))
    code, rec, root, _ = attempt(tmp_path, host)
    entry = assert_p5_failed(code, rec, root, "volatile_undeclared", count=1, paths=["repo/late.txt"])
    assert set(entry) == {"step", "started_at"}
    assert not (root / "seal/meta/complete.json").exists()


def test_a_cp_that_hangs_stops_p5_with_its_timeout(tmp_path):
    code, rec, root, _ = attempt(tmp_path, SyntheticHost(hang={"cp#1"}))
    assert_p5_failed(code, rec, root, "timeout", timeout_s=1800)


def test_a_cp_exiting_nonzero_stops_p5_without_its_output(tmp_path):
    code, rec, root, evidence = attempt(tmp_path, SyntheticHost(fail={"cp#1": 1}))
    assert rec["failed_step"]["step"] == "P5" and rec["failed_step"]["reason"].endswith("_exit_1")
    assert "ok" not in step_of(rec, "P5") and "SECRET-STDERR" not in (evidence / "phase-p.json").read_text()


def test_an_env_value_equal_to_the_cp_version_is_an_acquire_path_evidence_refusal(tmp_path, monkeypatch):
    first = subprocess.run([fileroots.CP, "--version"], capture_output=True, text=True, check=True).stdout.splitlines()[0]
    monkeypatch.setenv("P5_TEST_CP_VERSION", first)
    code, rec, root, _ = attempt(tmp_path, SyntheticHost())
    entry = assert_p5_failed(code, rec, root, "evidence_unbounded", rule="env_value_fact")
    assert set(entry) == {"step", "started_at"}


def test_an_env_value_equal_to_the_activity_line_is_refused_by_p5_itself_before_ok(tmp_path, monkeypatch):
    """Only P5's own activity samples carry this string (acquire's facts do not): it kills `ok` set before check_facts."""
    monkeypatch.setenv("P5_TEST_ACTIVITY", ACTIVITY)
    code, rec, root, _ = attempt(tmp_path, SyntheticHost())
    entry = assert_p5_failed(code, rec, root, "evidence_unbounded", rule="env_value_fact")
    assert set(entry) == {"step", "started_at"} and (root / "seal/meta/complete.json").exists()


def test_paused_false_leaves_no_seal(tmp_path):
    code, rec, root, _ = attempt(tmp_path, SyntheticHost(paused=False))
    assert code == 1 and not (root / "seal").exists() and step_of(rec, "P5") is None


def test_a_root_or_evidence_dir_overlapping_the_source_is_refused_before_any_effect(tmp_path, standin_srv):
    host = SyntheticHost()
    (tmp_path / "link").symlink_to(standin_srv)  # a symlinked parent still lands inside the source
    for root, evidence in ((standin_srv / "root", tmp_path / "ev"), (tmp_path / "root", standin_srv / "ev"),
                           (tmp_path / "link" / "root", tmp_path / "ev2")):
        with pytest.raises(Refused) as caught:
            pp.main(str(root), str(evidence), RUN8, host)
        assert caught.value.code == "seal_overlaps_source" and host.calls == []
    assert not (standin_srv / "root").exists() and not (tmp_path / "ev").exists() and not (tmp_path / "ev2").exists()
    with pytest.raises(Refused) as caught:  # PhaseP.run refuses its own paths too, before the lock
        pp.PhaseP(str(standin_srv / "x"), str(tmp_path / "e"), RUN8, host).run()
    assert caught.value.code == "seal_overlaps_source" and host.calls == []


# ---- interruption, lock, signals (D4, D5) ----

def test_a_keyboard_interrupt_in_p5_is_receipted_settled_and_releases_the_lock(tmp_path):
    def interrupt():
        raise KeyboardInterrupt

    old = os.umask(0o022)
    try:
        code, rec, root, evidence = attempt(tmp_path, Hooked(before=interrupt))
        assert os.umask(0o022) == 0o022  # restored
    finally:
        os.umask(old)
    entry = assert_p5_failed(code, rec, root, "interrupted")
    assert rec["verdict"] == "STOP: P5 interrupted" and rec["helpers_after"] == {"removed": 0, "residue": []}
    assert (evidence / "phase-p.json").exists() and set(entry) == {"step", "started_at"}
    (tmp_path / "two").mkdir()
    code, rec, _, _ = attempt(tmp_path / "two", SyntheticHost())  # the same lock name: released
    assert code == 0 and rec["verdict"] == "ok"


def test_a_keyboard_interrupt_while_settling_after_is_a_hold_naming_the_last_step(tmp_path):
    class Interrupts(SyntheticHost):
        def run(self, argv, **kw):
            if self._kind(argv) == "ps" and self.counts.get("ps", 0) == 2:  # the third listing: the after-settle's first
                raise KeyboardInterrupt
            return super().run(argv, **kw)

    code, rec, _, evidence = attempt(tmp_path, Interrupts())
    assert code == 1 and rec["helpers_after"] == {"residue": ["settle-interrupted"]}
    assert rec["verdict"].startswith("HOLD:") and "after P4" in rec["verdict"] and (evidence / "phase-p.json").exists()


def test_a_held_lock_stops_before_any_command_and_a_killed_holder_releases_it(tmp_path):
    child = subprocess.Popen(
        ["/usr/bin/python3", "-c", "import socket, sys, time\ns = socket.socket(socket.AF_UNIX)\n"
         "s.bind('\\0' + sys.argv[1])\nprint('ready', flush=True)\ntime.sleep(300)", pp.RUN_LOCK],
        stdout=subprocess.PIPE, text=True)
    try:
        assert child.stdout.readline().strip() == "ready"
        host = SyntheticHost()
        code, rec, root, _ = attempt(tmp_path, host)
        assert code == 1 and rec["failed_step"] == {"step": "lock", "reason": "phase_p_lock_held"}
        assert rec["verdict"] == "STOP: lock failed: phase_p_lock_held" and rec["steps"] == [] and host.calls == []
    finally:
        child.kill()  # only this test's own child, through its handle
        child.wait(timeout=30)
        child.stdout.close()
    (tmp_path / "two").mkdir()
    code, rec, _, _ = attempt(tmp_path / "two", SyntheticHost())  # A2: an abstract socket dies with its holder
    assert code == 0 and rec["verdict"] == "ok"


def test_no_signal_handler_is_installed(tmp_path):
    before = signal.getsignal(signal.SIGTERM), signal.getsignal(signal.SIGINT)
    attempt(tmp_path, SyntheticHost())
    assert (signal.getsignal(signal.SIGTERM), signal.getsignal(signal.SIGINT)) == before


# ---- ceilings (D11) ----

class Recording(SyntheticHost):
    """Attributes every Host.run timeout (the default included) to the PhaseP's step at the moment of the call."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.phase, self.timeouts = None, []

    def run(self, argv, *, timeout=120, stdout=None):
        self.timeouts.append((self.phase.step, self._kind(list(argv)), timeout))
        return super().run(argv, timeout=timeout, stdout=stdout)


def recorded_run(tmp_path, host):
    root, evidence = tmp_path / "root", tmp_path / "evidence"
    create_root(root, RUN8)
    os.makedirs(root / "p", mode=0o700)
    os.makedirs(evidence)
    host.phase = pp.PhaseP(str(root), str(evidence), RUN8, host)
    assert host.phase.run() == 0
    return host.timeouts


@pytest.mark.parametrize("owned", [False, True])
def test_the_recorded_timeouts_of_each_step_stay_within_its_ceiling(tmp_path, owned):
    labels = [pc.provider_guard.FIXTURE_LABEL, f"zeus.rehearsal.run={RUN8}"]
    containers = {pp.helper_name(RUN8, role): ("id-" + role, labels) for role in pp.HELPER_ROLES} if owned else {}
    timeouts = recorded_run(tmp_path, Recording(containers=containers))
    sums = {}
    for step, _kind, timeout in timeouts:
        sums[step] = sums.get(step, 0) + timeout
    assert set(sums) <= set(pp.CEILINGS_S)
    for step, total in sums.items():
        if step != "P5":
            assert total <= pp.CEILINGS_S[step], (step, total)
    p5 = [(kind, timeout) for step, kind, timeout in timeouts if step == "P5"]
    assert {kind for kind, _t in p5} == {"psql", "cp"}
    assert all(t == fileroots.CP_TIMEOUT_S for kind, t in p5 if kind == "cp") and sum(1 for k, _t in p5 if k == "cp") == 8
    assert [t for kind, t in p5 if kind == "psql"] == [120, 120]
    if owned:
        assert sums["settle"] == pp.CEILINGS_S["settle"]


def test_the_ceilings_are_the_nine_documented_steps_and_sum_to_the_derived_total():
    assert list(pp.CEILINGS_S) == ["settle", "P0", "P1", "P2a", "P3", "P2b", "P5", "P4", "settle_after"]
    assert pp.CEILINGS_S["P5"] == 2 * 120 + 10 + fileroots.DEADLINE_S + fileroots.CP_TIMEOUT_S
    assert pp.CEILING_S == 22870  # the owner's derivation from the timeouts the code passes


# ---- the evidence bound under the real unit environment (A-F13, S6) ----

@pytest.mark.parametrize("extra", [{}, {"OLDPWD": "SRV"}])
def test_the_p5_entry_passes_check_facts_under_the_modelled_unit_environment(tmp_path, standin_srv, monkeypatch, extra):
    code, rec, root, _ = attempt(tmp_path, SyntheticHost())
    assert code == 0
    env = {"TMPDIR": str(root / "t"), "PATH": "/home/trevi/.local/bin:/usr/local/bin:/usr/bin:/bin", "HOME": "/home/trevi",
           "USER": "trevi", "LOGNAME": "trevi", "SHELL": "/bin/bash", "INVOCATION_ID": uuid.uuid4().hex,
           "SYSTEMD_EXEC_PID": "4242", **{k: str(standin_srv) for k in extra}}
    with monkeypatch.context() as patched:
        patched.setattr(os, "environ", env)
        check_facts(step_of(rec, "P5"))


# ---- guard-free import chain ----

def test_phase_p_controls_and_fileroots_load_in_a_fresh_interpreter_without_the_guard():
    probe = ("import sys\nfrom guard import provider_guard as g\nbefore = g.installed()\n"
             "import rehearsal.phase_p_controls, rehearsal.phase_p, rehearsal.fileroots as fr\n"
             "from pathlib import Path\nrepo = Path.cwd().parent\nfr.load_aibox_data(repo)\n"
             "origins = [Path(sys.modules[m].__spec__.origin).resolve().is_relative_to(repo.resolve())"
             " for m in ('aibox_data', 'aibox_data.inventory', 'codex_harness', 'codex_harness.kernel.ids')]\n"
             "print(before, g.installed(), sorted(m for m in sys.modules if m in "
             "('rehearsal.copies', 'rehearsal.sweep', 'rehearsal_compare_run')), all(origins))")
    done = subprocess.run(["/usr/bin/python3", "-B", "-c", probe], cwd=REPO / "compare", capture_output=True, text=True,
                          timeout=120)
    assert done.returncode == 0, done.stderr[-400:]
    assert done.stdout.strip() == "False False [] True"


# ---- the control runner's srv refusal (before any effect) ----

class NoEffects:
    def __init__(self):
        self.calls = []

    def run(self, argv, **kw):
        self.calls.append(argv)
        raise AssertionError("an effect before the refusal")


def test_validate_targets_admits_the_stand_in_srv_and_refuses_production_or_foreign_paths(tmp_path, monkeypatch):
    scratch = tmp_path / "scratch"
    good = pc.standin_targets(RUN8, scratch)
    pc.validate_targets(good, RUN8, scratch)
    assert good.srv == str(scratch / "srv")
    host = NoEffects()

    def refused(srv, code):
        with pytest.raises(Refused) as caught:
            pc.StandIns(host, RUN8, scratch, dataclasses.replace(good, srv=str(srv)))
        assert caught.value.code == code and host.calls == []

    refused(fileroots.SRV, "production_path")
    refused(REAL + "/runtime", "production_path")
    refused(tmp_path / "elsewhere", "standin_path")
    with monkeypatch.context() as patched:  # a lexical match refuses before any resolve is attempted
        patched.setattr(os.path, "realpath", lambda *_a, **_k: pytest.fail("resolved before the lexical refusal"))
        refused(REAL + "/x", "production_path")
    fake_prod = tmp_path / "fake-prod"  # a symlink to a production root (the root itself monkeypatched to a tmp dir)
    fake_prod.mkdir()
    scratch.mkdir()
    (scratch / "link").symlink_to(fake_prod)
    monkeypatch.setattr(fileroots, "SRV", str(fake_prod))
    refused(scratch / "link", "production_path")
