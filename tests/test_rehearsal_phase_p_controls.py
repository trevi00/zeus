"""Cutover RH-2b: the owner-run Phase P control runner (`compare/rehearsal/phase_p_controls.py`), its pure parts only.

Layer: harness tooling tests (never shipped). The real-docker controls are NOT pytest tests (the test guard admits none of
their forms and is not widened); the owner runs the runner once, recorded. Here: the refusal logic (every target must be
this run's labelled stand-in; production names refused before any effect), the shape of the commands that create the
stand-ins, and the control sequencing/outcome judgement through the `Host` stub with a recording fake stand-in. RH-2c adds the
no-guard-bypass contract: the runner's import chain installs no audit hook (the CL2 controls live in
tests/test_rehearsal_cl2_controls.py, guarded).
Expected outcomes come from the spec's Examples and What 2 (step/reason per control), written literally below.
"""

from __future__ import annotations

import json
import subprocess
import sys

import pytest
from _layout import REPO
from test_rehearsal_phase_p import SyntheticHost

sys.path.insert(0, str(REPO / "compare"))
from rehearsal import Refused  # noqa: E402
from rehearsal import phase_p as pp  # noqa: E402
from rehearsal import phase_p_controls as pc  # noqa: E402

RUN8 = "9a8b7c6d"
ABSENT = {"containers_left": 0, "volumes_left": 0, "absent": True}


class ControlHostStub(SyntheticHost):
    """SyntheticHost plus the two real-docker effects the controls cause: a planted file (diff) and a restart (StartedAt)."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.planted = self.restarted = False

    def run(self, argv, **kw):
        done = super().run(argv, **kw)
        kind = self._kind(argv)
        if kind == "inspect" and self.restarted:
            done.stdout = json.dumps({**json.loads(done.stdout), "StartedAt": "t2"})
        if kind == "diff" and self.planted:
            done.stdout += "A /tmp/rh-planted\n"
        return done


class FakeStand(pc.StandIns):
    registry: list = []
    effective = True  # a mutation that takes effect; False models a control whose mutation did nothing

    def __init__(self, host, run8, scratch):
        super().__init__(host, run8, scratch)
        self.events = []
        FakeStand.registry.append(self)

    def create(self):
        self.events.append("create")
        self.host.planted = self.host.restarted = self.host.bracket_change = False  # fresh stand-ins per control
        self.host.inspects = 0
        self.set_paused(True)

    def plant_file(self):
        self.events.append(("plant_file", len(self.host.calls)))
        self.host.planted = self.effective

    def restart(self):
        self.events.append(("restart", len(self.host.calls)))
        self.host.restarted = self.effective

    def start_writer(self):
        self.events.append(("start_writer", len(self.host.calls)))
        self.host.bracket_change = self.effective

    def stop_writer(self):
        self.events.append("stop_writer")

    def toc(self, dump_path):
        return ["entry"]

    def remove(self):
        self.events.append("remove")
        return dict(ABSENT)


def runner(tmp_path):
    FakeStand.registry = []
    host = ControlHostStub()
    return pc.Runner(host, RUN8, tmp_path / "scratch", stand_factory=FakeStand), host


def test_every_control_reaches_its_expected_step_and_reason_and_each_tears_down(tmp_path):
    run, _ = runner(tmp_path)
    result = run.run_all()
    got = {r["control"]: r["outcome"] for r in result["controls"]}
    assert got == {"positive": {"step": "P4", "reason": "ok"},
                   "docker_diff": {"step": "P4", "reason": "docker_diff_changed"},
                   "redis_write_during_copy": {"step": "P3", "reason": "redis_bracket_unequal"},
                   "restart": {"step": "P4", "reason": "container_restarted"},
                   "paused_false": {"step": "P0", "reason": "not_paused_or_not_quiet"}}
    assert result["all_matched"] and [r["control"] for r in result["controls"]] == list(pc.CONTROLS)
    assert all(r["teardown"] == ABSENT and s.events[0] == "create" and s.events[-1] == "remove"
               for r, s in zip(result["controls"], FakeStand.registry))


def test_each_mutation_is_applied_at_its_point_in_the_phase_sequence(tmp_path):
    run, host = runner(tmp_path)
    run.run_all()
    by = {s.scratch.name: s for s in FakeStand.registry}
    assert not [e for e in by["positive"].events if isinstance(e, tuple)]  # the positive control mutates nothing
    for name, kind in (("docker_diff", "plant_file"), ("restart", "restart")):
        (_, at), = [e for e in by[name].events if isinstance(e, tuple)]
        assert at > 0 and host.calls[at][1] == "inspect"  # just before P4's first inspect
    (_, at), = [e for e in by["redis_write_during_copy"].events if isinstance(e, tuple)]
    assert host.calls[at][1] == "run" and "redis-snap" in host.calls[at][host.calls[at].index("--name") + 1]
    assert [e if isinstance(e, str) else e[0] for e in by["redis_write_during_copy"].events] == [
        "create", "start_writer", "stop_writer", "remove"]
    assert by["paused_false"].events == ["create", "remove"]


def test_the_redis_write_control_stops_before_p2b_and_paused_false_acquires_nothing(tmp_path):
    run, _ = runner(tmp_path)
    by = {r["control"]: r for r in run.run_all()["controls"]}
    assert by["redis_write_during_copy"]["facts"] == {"stopped_before_p2b": True}
    assert by["paused_false"]["facts"] == {"no_acquisition": True}
    assert by["positive"]["facts"] == {"dumps_equal": True, "redis_bracket_identical": True, "helpers_settled": True}


@pytest.mark.parametrize("control", ["docker_diff", "redis_write_during_copy", "restart"])
def test_a_control_whose_mutation_has_no_effect_is_not_matched(tmp_path, control, monkeypatch):
    """Negative control: if the planted change did nothing, Phase P passes and the control must NOT count as matched."""
    monkeypatch.setattr(FakeStand, "effective", False)
    run, _ = runner(tmp_path)
    result = run.control(control)
    assert result["matched"] is False and result["outcome"] == {"step": "P4", "reason": "ok"}


def test_a_failed_create_still_tears_down_and_is_not_matched(tmp_path, monkeypatch):
    def boom(self):
        self.events.append("create")
        raise RuntimeError("x")

    monkeypatch.setattr(FakeStand, "create", boom)
    run, _ = runner(tmp_path)
    result = run.control("positive")
    assert result["matched"] is False and result["facts"] == {"error": "RuntimeError"} and FakeStand.registry[-1].events == ["create", "remove"]


# ---- refusal logic ----

def test_the_production_targets_are_refused_before_any_effect(tmp_path):
    host = ControlHostStub()
    with pytest.raises(Refused) as caught:
        pc.StandIns(host, RUN8, tmp_path, pp.DEFAULT_TARGETS)
    assert caught.value.code == "production_name" and host.calls == []


@pytest.mark.parametrize("change", [
    dict(pg="zeus-aibox-postgres"), dict(redis="zeus-aibox-redis"), dict(redis_volume="zeus-aibox-redisdata"),
    dict(pg="zeus-test-fixture-rh-11223344-prod-pg"), dict(pg="zeus-test-fixture-rh-9a8b7c6d-prod-redis"),
    dict(pg="zeus-test-fixture-rh-9a8b7c6d-p-redis-snap"), dict(redis="anything"),
    dict(monitoring=pp.MONITORING), dict(heartbeat=pp.HEARTBEAT), dict(monitoring="/etc/monitoring.json")])
def test_any_single_non_stand_in_target_is_refused(tmp_path, change):
    targets = pc.standin_targets(RUN8, tmp_path)
    pc.validate_targets(targets, RUN8, tmp_path)  # the stand-in set itself is admitted
    bad = pp.Targets(**{**targets.__dict__, **change})
    with pytest.raises(Refused):
        pc.validate_targets(bad, RUN8, tmp_path)


def test_main_refuses_existing_paths_before_any_effect(tmp_path):
    (tmp_path / "s").mkdir()
    with pytest.raises(Refused) as caught:
        pc.main(RUN8, str(tmp_path / "s"), str(tmp_path / "out.json"))
    assert caught.value.code == "path_exists"
    with pytest.raises(Refused):
        pc.main("nothex", str(tmp_path / "t"), str(tmp_path / "o.json"))


class Recorder:
    """Records every docker argv `StandIns.create` issues and answers like a healthy daemon."""

    def __init__(self, run8):
        self.calls, self.labels = [], json.dumps({"zeus.test.fixture": "1", pc.STANDIN_LABEL: run8})

    def run(self, argv, *, timeout=120, stdout=None):
        self.calls.append(list(argv))
        out = ""
        if argv[1] == "logs":
            out = "PostgreSQL init process complete; ready to accept connections\nReady to accept connections\n"
        elif argv[1] == "inspect":
            out = self.labels
        return subprocess.CompletedProcess(argv, 0, out, "")


def test_create_issues_only_labelled_network_none_never_pulled_stand_in_commands(tmp_path):
    host = Recorder(RUN8)
    stand = pc.StandIns(host, RUN8, tmp_path / "w")
    stand.create()
    runs = [c for c in host.calls if c[1] == "run"]
    assert len(runs) == 2
    names = {stand.targets.pg, stand.targets.redis}
    for argv in runs:
        assert argv[argv.index("--network") + 1] == "none" and argv[argv.index("--pull") + 1] == "never"
        labels = [argv[i + 1] for i, a in enumerate(argv) if a == "--label"]
        assert labels == ["zeus.test.fixture=1", f"zeus.rehearsal.standin={RUN8}"]  # not the run label (settle would HOLD)
        assert argv[argv.index("--name") + 1] in names
    volume = [c for c in host.calls if c[1] == "volume"]
    assert volume == [["docker", "volume", "create", "--label", "zeus.test.fixture=1", "--label",
                       f"zeus.rehearsal.standin={RUN8}", stand.targets.redis_volume]]
    assert not any("zeus-aibox" in " ".join(c) for c in host.calls)
    assert json.loads(open(stand.targets.monitoring).read())["sources"]["fleet"]["data"]["paused"] is True


def test_an_unlabelled_stand_in_is_refused_before_phase_p(tmp_path):
    host = Recorder(RUN8)
    host.labels = json.dumps({"zeus.test.fixture": "1"})
    with pytest.raises(Refused) as caught:
        pc.StandIns(host, RUN8, tmp_path / "w").create()
    assert caught.value.code == "standin_unlabelled"


def test_remove_names_only_the_stand_ins_and_proves_absence_by_label(tmp_path):
    host = Recorder(RUN8)
    stand = pc.StandIns(host, RUN8, tmp_path / "w")
    assert stand.remove() == ABSENT
    removals = [c for c in host.calls if c[1] in ("rm", "volume") and "rm" in c]
    assert removals == [["docker", "rm", "-f", "-v", stand.targets.pg], ["docker", "rm", "-f", "-v", stand.targets.redis],
                        ["docker", "volume", "rm", "-f", stand.targets.redis_volume]]
    assert [f"label={pc.STANDIN_LABEL}={RUN8}" in c for c in host.calls[-2:]] == [True, True]


# ---- RH-2c: the runner never imports a guard-installing module (D-RH2-RUNNER-GUARD) ----

def _fresh(code: str) -> str:
    done = subprocess.run([sys.executable, "-B", "-c", code], cwd=REPO / "compare", capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr[-400:]
    return done.stdout.strip()


def test_importing_the_runner_installs_no_audit_hook_and_loads_no_guard_installer():
    """Behavioural, in a fresh interpreter: the runner (and phase_p) leave the provider guard uninstalled."""
    probe = ("import sys; hooks=[]; sys.addaudithook(lambda e, a: None)\n"
             "from guard import provider_guard as g\n"
             "before = g.installed()\n"
             "import rehearsal.phase_p_controls, rehearsal.phase_p\n"
             "print(before, g.installed(), sorted(m for m in sys.modules if m in "
             "('rehearsal.copies', 'rehearsal.sweep', 'rehearsal_compare_run')))")
    assert _fresh(probe) == "False False []"


def test_the_guard_installing_path_is_the_control_here_importing_copies_does_install_it():
    """Positive control for the probe above: the same probe over `rehearsal.copies` reports the guard installed."""
    probe = ("from guard import provider_guard as g\nimport rehearsal.copies\nprint(g.installed())")
    assert _fresh(probe) == "True"


def test_the_guard_free_constants_equal_the_copies_values_they_stand_in_for():
    """STRUCTURAL (drift contract): constants.py mirrors run.py's image pins (it cannot import run.py) and `copies` re-exports it."""
    from rehearsal import constants as k
    from rehearsal import copies as cp

    assert (k.PG_IMAGE, k.REDIS_IMAGE) == (cp.PG_IMAGE, cp.REDIS_IMAGE)
    assert (k.PRODUCTION_PREFIX, k.RUN_LABEL, k.MARKER, k.create_root) == (
        cp.PRODUCTION_PREFIX, cp.RUN_LABEL, cp.MARKER, cp.create_root)
