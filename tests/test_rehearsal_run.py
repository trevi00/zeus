"""Cutover RH-1b: the rehearsal run driver (`compare/rehearsal/run.py`).

Layer: harness tooling tests (never shipped); no systemd, no docker (the executor and the JSON reader are injected).
Expected results come from the rehearsal design "0. RUN FRAME" (the systemd-run argv, the pause gate before AND after)
and EVIDENCE FORMAT (plan.json, a fsynced 'started' row before each child then 'finished', run-exit.json in `finally`,
0600): the argv below is the design's text, written out literally and never built from the driver's own constants.
"""

from __future__ import annotations

import json
import os
import stat
import sys

import pytest
from _layout import REPO

sys.path.insert(0, str(REPO / "compare"))
from rehearsal import Refused  # noqa: E402
from rehearsal import run as rn  # noqa: E402
from rehearsal.phase_p import HEARTBEAT, MONITORING  # noqa: E402

RUN8 = "7c1e5a90"
IDENTITIES = {"B": {"commit": "b" * 40, "wheel_sha256": "w" * 64, "uv_lock_sha256": "u" * 64, "release": "/r/B"},
              "A": {"venv": "/r/A/.venv"}, "D": {"releases": ["08bb9a44", "5aa220fd"]}}
PAUSED = {"sources": {"fleet": {"data": {"paused": True}}}}
QUIET = {"active": 0, "unresolved": 0, "instance_id": "i1"}


def design_argv(root: str, phase: str, command=()) -> list[str]:
    """The design's text, token by token."""
    return ["sudo", "-n", "systemd-run", "--uid=trevi", "--collect", "-p", "MemoryMax=12G", "-p", "MemorySwapMax=0",
            "-p", "OOMPolicy=continue", "--setenv", f"TMPDIR={root}/t", "--setenv",
            "PATH=/home/trevi/.local/bin:/usr/local/bin:/usr/bin:/bin", "--unit", f"zeus-rehearsal-{RUN8}-{phase}", *command]


class Fake:
    """An executor: records every argv; `steps` is the evidence steps file, read at call time to prove ordering."""

    def __init__(self, evidence_dir, *, exits=None):
        self.calls, self.dir, self.exits, self.seen = [], evidence_dir, exits or {}, []

    def __call__(self, argv, *, timeout=None):
        argv = list(argv)
        self.calls.append(argv)
        if argv[0] == "systemctl":
            return rn.Result(0, b"123456\n")
        unit = argv[argv.index("--unit") + 1]
        steps = (self.dir / "steps.jsonl").read_text().splitlines() if (self.dir / "steps.jsonl").exists() else []
        self.seen.append((unit, [json.loads(line)["status"] + ":" + json.loads(line)["step"] for line in steps]))
        return rn.Result(self.exits.get(unit, 0), f"out of {unit}".encode(), b"err")


def reader(monitoring=PAUSED, heartbeat=QUIET, flip_after=None):
    state = {"n": 0}

    def read(path):
        if path == MONITORING:
            state["n"] += 1
            if flip_after is not None and state["n"] > flip_after:
                return {"sources": {"fleet": {"data": {"paused": False}}}}
            return monitoring
        assert path == HEARTBEAT
        return heartbeat

    return read


def make(tmp_path, **kwargs):
    root, ev = tmp_path / "rh", tmp_path / "ev"
    fake = Fake(ev, exits=kwargs.pop("exits", None))
    driver = rn.RunDriver(RUN8, root, ev, executor=fake, read_json=kwargs.pop("read_json", reader()),
                          clock=lambda: "2026-10-06T00:00:00.000+00:00")
    return driver, fake, root, ev


def rows(ev):
    return [json.loads(line) for line in (ev / "steps.jsonl").read_text().splitlines()]


COMMANDS = {c: ["/bin/true", c] for c in ("S", "A", "B", "D", "R7", "seal-b")}


def test_the_phase_argv_is_the_designs_systemd_run_command(tmp_path):
    root = tmp_path / "rh"
    assert rn.phase_argv(RUN8, root, "copy-s", ["/bin/echo", "x"]) == design_argv(str(root), "copy-s", ["/bin/echo", "x"])
    assert rn.phase_argv(RUN8, root, "r3") == design_argv(str(root), "r3")


@pytest.mark.parametrize("phase", ["", "A B", "../x", "Upper", "x" * 60])
def test_a_bad_phase_name_is_refused(tmp_path, phase):
    with pytest.raises(Refused) as info:
        rn.phase_argv(RUN8, tmp_path, phase)
    assert info.value.code == "bad_phase"


def test_the_launched_argv_keeps_every_design_token_and_only_adds_wait_and_pipe(tmp_path):
    driver, fake, root, ev = make(tmp_path)
    driver.run(IDENTITIES, lambda d: d.run_phase("r3", ["/bin/true"]), tools={})
    launched = next(c for c in fake.calls if c[0] == "sudo")
    wanted = design_argv(str(root), "r3", ["/bin/true"])
    assert [t for t in launched if t not in ("--wait", "--pipe")] == wanted
    assert launched[launched.index("--collect") + 1: launched.index("--collect") + 3] == ["--wait", "--pipe"]


def test_each_child_has_a_started_row_on_disk_before_it_runs_then_a_finished_row(tmp_path):
    driver, fake, root, ev = make(tmp_path)
    driver.run(IDENTITIES, lambda d: (d.run_phase("r3", ["/bin/true"]), d.run_phase("r4", ["/bin/true"])), tools={})
    assert fake.seen[0] == (f"zeus-rehearsal-{RUN8}-r3", ["ok:pause-gate-before", "started:r3"])
    assert fake.seen[1][1] == ["ok:pause-gate-before", "started:r3", "finished:r3", "started:r4"]
    order = [(r["step"], r["status"]) for r in rows(ev)]
    assert order == [("pause-gate-before", "ok"), ("r3", "started"), ("r3", "finished"), ("r4", "started"),
                     ("r4", "finished"), ("pause-gate-after", "ok")]
    finished = rows(ev)[2]["facts"]
    out = b"out of zeus-rehearsal-" + RUN8.encode() + b"-r3"
    import hashlib
    assert finished["exit"] == 0 and finished["stdout_bytes"] == len(out) and finished["stderr_bytes"] == 3
    assert finished["stdout_sha256"] == hashlib.sha256(out).hexdigest() and finished["memory_peak_bytes"] == 123456
    assert (ev / "logs" / "r3.stdout").read_bytes() == out


def test_a_failing_child_is_recorded_with_its_exit_and_fails_the_run(tmp_path):
    driver, fake, root, ev = make(tmp_path, exits={f"zeus-rehearsal-{RUN8}-r3": 7})
    with pytest.raises(Refused) as info:
        driver.run(IDENTITIES, lambda d: d.run_phase("r3", ["/bin/false"]), tools={})
    assert info.value.code == "phase_failed"
    assert [r for r in rows(ev) if r["step"] == "r3" and r["status"] == "finished"][0]["facts"]["exit"] == 7
    exit_record = json.loads((ev / "run-exit.json").read_text())
    assert exit_record["status"] == "failed" and exit_record["facts"]["code"] == "phase_failed"


def test_run_exit_is_written_when_the_work_raises_and_sha256sums_comes_last(tmp_path):
    driver, fake, root, ev = make(tmp_path)

    def boom(d):
        raise RuntimeError("the work blew up")

    with pytest.raises(RuntimeError):
        driver.run(IDENTITIES, boom, tools={})
    exit_record = json.loads((ev / "run-exit.json").read_text())
    assert exit_record["status"] == "failed" and exit_record["facts"]["error"] == "RuntimeError"
    assert [r["step"] for r in rows(ev)] == ["pause-gate-before", "pause-gate-after"]  # the second gate still ran
    assert "run-exit.json" in (ev / "SHA256SUMS").read_text() and (ev / "SHA256SUMS").stat().st_mtime_ns >= (
        ev / "run-exit.json").stat().st_mtime_ns


@pytest.mark.parametrize("monitoring,heartbeat,code", [
    ({"sources": {"fleet": {"data": {"paused": False}}}}, QUIET, "fleet_not_paused"),
    ({"sources": {}}, QUIET, "fleet_not_paused"),
    (PAUSED, {"active": 1, "unresolved": 0}, "fleet_not_quiet"),
    (PAUSED, {"active": 0, "unresolved": 2}, "fleet_not_quiet")])
def test_the_pause_precheck_refuses_before_any_child_runs(tmp_path, monitoring, heartbeat, code):
    ran = []
    driver, fake, root, ev = make(tmp_path, read_json=reader(monitoring, heartbeat))
    with pytest.raises(Refused) as info:
        driver.run(IDENTITIES, lambda d: ran.append(d.run_phase("r3", ["/bin/true"])), tools={})
    assert info.value.code == code and ran == [] and fake.calls == []
    assert json.loads((ev / "run-exit.json").read_text())["facts"]["code"] == code


def test_a_fleet_resumed_during_the_work_fails_the_post_check(tmp_path):
    driver, fake, root, ev = make(tmp_path, read_json=reader(flip_after=1))
    with pytest.raises(Refused) as info:
        driver.run(IDENTITIES, lambda d: d.run_phase("r3", ["/bin/true"]), tools={})
    assert info.value.code == "fleet_not_paused"
    assert [(r["step"], r["status"]) for r in rows(ev)][-1] == ("pause-gate-after", "refused")
    assert json.loads((ev / "run-exit.json").read_text())["status"] == "failed"


def test_the_copy_sequence_runs_s_seal_b_bracket_a_b_d_r7_with_a_peak_per_copy(tmp_path):
    driver, fake, root, ev = make(tmp_path)
    removed = []
    verdict = {"quiescent": False, "d0": "d0a", "cross_store_skew": True, "catalog_sha256": {"d0a": "1" * 64, "d0b": "2" * 64},
               "differing": [f"app.rel{i}" for i in range(100)], "pel_owner_checks": "informational"}
    driver.run(IDENTITIES, lambda d: d.run_copies(COMMANDS, bracket=lambda: verdict,
                                                  remove_seal_b=lambda: removed.append(1)), tools={})
    assert driver.sequence == ["S", "seal-b", "A", "B", "D", "R7"] and removed == [1]
    order = [(r["step"], r["status"]) for r in rows(ev)]
    assert order[1:-1] == [("copy-S", "started"), ("copy-S", "finished"), ("copy-seal-b", "started"),
                           ("copy-seal-b", "finished"), ("bracket", "finished"), ("seal-b-removed", "finished"),
                           *[(f"copy-{c}", s) for c in ("A", "B", "D", "R7") for s in ("started", "finished")]]
    bracket = next(r for r in rows(ev) if r["step"] == "bracket")["facts"]
    assert bracket["differing_total"] == 100 and len(bracket["differing"]) == 32 and bracket["quiescent"] is False
    exit_facts = json.loads((ev / "run-exit.json").read_text())["facts"]
    assert exit_facts["peaks"] == {f"copy-{c}": 123456 for c in ("S", "seal-b", "A", "B", "D", "R7")}
    assert [c[c.index("--unit") + 1] for c in fake.calls if c[0] == "sudo"][:2] == [
        f"zeus-rehearsal-{RUN8}-copy-s", f"zeus-rehearsal-{RUN8}-copy-seal-b"]


def test_a_copy_sequence_with_a_copy_missing_or_a_lone_seal_b_is_refused(tmp_path):
    driver, fake, root, ev = make(tmp_path)
    with pytest.raises(Refused) as info:
        driver.run(IDENTITIES, lambda d: d.run_copies({k: v for k, v in COMMANDS.items() if k != "D"}), tools={})
    assert info.value.code == "copy_sequence" and fake.calls == []
    driver, fake, root, ev = make(tmp_path / "two")
    with pytest.raises(Refused) as info:
        driver.run(IDENTITIES, lambda d: d.run_copies(COMMANDS), tools={})  # seal-b without a bracket
    assert info.value.code == "copy_sequence"


def test_plan_json_names_the_run_identities_root_labels_images_and_tool_digests_owner_only(tmp_path):
    driver, fake, root, ev = make(tmp_path)
    driver.run(IDENTITIES, lambda d: None, extra_images={"worker": "worker@sha256:" + "9" * 64})
    plan = json.loads((ev / "plan.json").read_text())["facts"]
    assert plan["run8"] == RUN8 and plan["root"] == str(root) and plan["identities"] == IDENTITIES
    assert plan["labels"] == [f"zeus.rehearsal.run={RUN8}"]
    assert plan["images"]["worker"].endswith("9" * 64) and "@sha256:" in plan["images"]["postgres"]
    assert "compare/rehearsal/run.py" in plan["tool_sha256"] and "compare/rehearsal/volatile.json" in plan["tool_sha256"]
    assert all(len(v) == 64 for v in plan["tool_sha256"].values())
    for name in ("plan.json", "run-start.json", "steps.jsonl", "run-exit.json", "SHA256SUMS"):
        assert stat.S_IMODE(os.stat(ev / name).st_mode) == 0o600, name


def test_identities_without_the_exact_b_commit_wheel_and_lock_digests_are_refused(tmp_path):
    for broken in ({"A": {"x": 1}, "D": {"y": 1}}, {**IDENTITIES, "B": {"commit": "b" * 40}}):
        driver, fake, root, ev = make(tmp_path / str(len(broken)) / str(len(broken["B"]) if "B" in broken else 0))
        with pytest.raises(Refused) as info:
            driver.run(broken, lambda d: None, tools={})
        assert info.value.code == "identity_missing" and fake.calls == []
