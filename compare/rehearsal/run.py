"""The rehearsal run driver (RH-1b; rehearsal design "0. RUN FRAME" and EVIDENCE FORMAT).

`RunDriver` owns one run's evidence directory and the way a phase is launched; it never names a production resource
itself (the pause gate reads the two files `phase_p` already names, through an injected reader):

- `plan.json`: run, the B/A/D identities, ROOT, labels, image digests and the sha256 of every tool (written first,
  0600, never overwritten);
- every phase runs as `sudo -n systemd-run --uid=trevi --collect -p MemoryMax=12G -p MemorySwapMax=0 -p OOMPolicy=continue
  --setenv TMPDIR=ROOT/t --setenv PATH=... --unit zeus-rehearsal-<run8>-<phase> <command>` (`phase_argv`; the driver adds
  `--wait --pipe` right after `--collect` so the exit status and the child's output come back; see `run_phase`);
- `steps.jsonl` gets a fsynced `started` row BEFORE each child and a `finished` row (exit, stdout/stderr bytes and
  sha256, the unit's `MemoryPeak`); the outputs go to `logs/<step>.stdout|stderr` (0600);
- the pause gate (monitoring `fleet.paused` true, heartbeat `active` 0 / `unresolved` 0) runs before AND after the work;
- the copy sequence is S -> seal-b (bracket, then seal-b removed) -> A -> B -> D -> R7; peak memory is recorded per copy
  (each copy is one phase unit, `MemoryPeak` read through the executor);
- `run-exit.json` is written in `finally`, success or not (exit status, the failing rule's code), then `SHA256SUMS`.

The B builder stays outside (CUT-TOOLS): its release directory is an input of the plan. The executor and the JSON reader
are injected, so tests never call systemd. Evidence files are created under umask 0077 (0600), the design's mode.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from . import Refused, check_run8, fileroots
from .copies import COMPARE, COPY_NAMES, PG_IMAGE, REDIS_IMAGE, RUN_LABEL
from .evidence import Evidence, _utc_now, write_record
from .phase_p import HEARTBEAT, MONITORING

UID = "trevi"
PATH_ENV = "/home/trevi/.local/bin:/usr/local/bin:/usr/bin:/bin"
COPY_SEQUENCE = ("S", "A", "B", "D", "R7")  # seal-b sits between S and A, for the bracket only
SEAL_B = "seal-b"
PHASE = re.compile(r"^[a-z0-9][a-z0-9-]{0,40}$")
IDENTITY_B_FIELDS = ("commit", "wheel_sha256", "uv_lock_sha256", "release")
MAX_RECORD_ITEMS = 256


@dataclass(frozen=True)
class Result:
    returncode: int
    stdout: bytes = b""
    stderr: bytes = b""


def subprocess_executor(argv: Sequence[str], *, timeout: int | None = None) -> Result:
    """The real executor (never used by tests): run `argv` and return its exit status and raw output."""
    done = subprocess.run(list(argv), capture_output=True, timeout=timeout)
    return Result(done.returncode, done.stdout, done.stderr)


def read_json_file(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def unit_name(run8: str, phase: str) -> str:
    if not PHASE.fullmatch(phase):
        raise Refused("bad_phase", phase)
    return f"zeus-rehearsal-{check_run8(run8)}-{phase}"


def phase_argv(run8: str, root, phase: str, command: Sequence[str] = ()) -> list[str]:
    """The design's systemd-run argv for one phase, exactly (the child's `command` follows the unit name)."""
    return ["sudo", "-n", "systemd-run", f"--uid={UID}", "--collect", "-p", "MemoryMax=12G", "-p", "MemorySwapMax=0",
            "-p", "OOMPolicy=continue", "--setenv", f"TMPDIR={Path(root) / 't'}", "--setenv", f"PATH={PATH_ENV}",
            "--unit", unit_name(run8, phase), *command]


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def tool_sha256s(paths: Sequence[Path] | None = None) -> dict[str, str]:
    """`{repo-relative path: sha256}` of the tool identity (D13): every `compare/rehearsal/**/*.py` and `*.json` at its top,
    the guard, and the seven aibox_data files P5 imports (`fileroots.AIBOX_FILES`)."""
    repo = COMPARE.parent
    if paths is None:
        rehearsal = COMPARE / "rehearsal"
        paths = [*sorted(rehearsal.rglob("*.py")), *sorted(rehearsal.glob("*.json")), COMPARE / "guard" / "provider_guard.py",
                 *(repo / rel for rel in fileroots.AIBOX_FILES)]
    return {Path(p).relative_to(repo).as_posix(): _sha(Path(p).read_bytes()) for p in paths}


def check_identities(identities: dict) -> dict:
    """B is exact commit + wheel sha256 + uv.lock sha256 (+ its release dir); A and D must be named too."""
    if set(identities) != {"B", "A", "D"} or not all(isinstance(v, dict) and v for v in identities.values()):
        raise Refused("identity_missing", "B, A and D identities are required")
    missing = [f for f in IDENTITY_B_FIELDS if not identities["B"].get(f)]
    if missing:
        raise Refused("identity_missing", "B lacks " + ",".join(missing))
    return identities


def bracket_summary(facts: dict) -> dict:
    """The bounded step form of the bracket verdict (the whole verdict is `d0.json`'s `facts.bracket`)."""
    return {"quiescent": facts["quiescent"], "d0": facts["d0"], "cross_store_skew": facts["cross_store_skew"],
            "catalog_sha256": facts["catalog_sha256"], "differing_total": len(facts["differing"]),
            "differing": facts["differing"][:32], "pel_owner_checks": facts["pel_owner_checks"]}


def parse_peak(text: str) -> int | None:
    """`systemctl show -p MemoryPeak --value` output -> bytes, or None when the unit no longer reports one."""
    text = text.strip()
    return int(text) if text.isdigit() else None


class RunDriver:
    def __init__(self, run8: str, root, evidence_dir, *, executor=subprocess_executor, read_json=read_json_file,
                 clock: Callable[[], str] = _utc_now, phase_timeout: int = 3600):
        self.run8, self.root, self.dir = check_run8(run8), Path(root), Path(evidence_dir)
        self.executor, self.read_json, self.clock, self.timeout = executor, read_json, clock, phase_timeout
        self.evidence = Evidence(run8, self.dir, clock=clock)
        self.peaks: dict[str, int | None] = {}
        self.sequence: list[str] = []

    # -- the pause gate --

    def pause_gate(self, when: str) -> dict:
        """Monitoring `fleet.paused` must be true and the heartbeat `active` 0 / `unresolved` 0; else a refusal."""
        monitoring, heartbeat = self.read_json(MONITORING), self.read_json(HEARTBEAT)
        paused = (((monitoring.get("sources") or {}).get("fleet") or {}).get("data") or {}).get("paused") is True
        quiet = heartbeat.get("active") == 0 and heartbeat.get("unresolved") == 0
        facts = {"when": when, "paused": paused, "quiet": quiet, "active": heartbeat.get("active"),
                 "unresolved": heartbeat.get("unresolved")}
        self.evidence.step(f"pause-gate-{when}", "ok" if paused and quiet else "refused", facts)
        if not paused:
            raise Refused("fleet_not_paused", when)
        if not quiet:
            raise Refused("fleet_not_quiet", when)
        return facts

    # -- one phase = one systemd unit --

    def _log(self, step: str, kind: str, data: bytes) -> None:
        logs = self.dir / "logs"
        logs.mkdir(exist_ok=True)
        with open(logs / f"{step}.{kind}", "xb") as handle:
            handle.write(data)

    def memory_peak(self, unit: str) -> int | None:
        found = self.executor(["systemctl", "show", unit, "-p", "MemoryPeak", "--value"], timeout=30)
        return parse_peak(found.stdout.decode("utf-8", "replace")) if found.returncode == 0 else None

    def run_phase(self, phase: str, command: Sequence[str], *, step: str | None = None) -> dict:
        """Run `command` as the unit of `phase`: a fsynced `started` row, the child, then a `finished` row."""
        step = step or phase
        argv = phase_argv(self.run8, self.root, phase, command)
        # `--wait --pipe` only add the exit status and the child's output; the design's options are untouched.
        launch = [*argv[: argv.index("--collect") + 1], "--wait", "--pipe", *argv[argv.index("--collect") + 1:]]
        unit = unit_name(self.run8, phase)
        self.evidence.step(step, "started", {"unit": unit, "argv_sha256": _sha("\0".join(launch).encode())})
        done = self.executor(launch, timeout=self.timeout)
        peak = self.memory_peak(unit)
        self.peaks[step] = peak
        self._log(step, "stdout", done.stdout)
        self._log(step, "stderr", done.stderr)
        facts = {"unit": unit, "exit": done.returncode, "stdout_bytes": len(done.stdout), "stdout_sha256": _sha(done.stdout),
                 "stderr_bytes": len(done.stderr), "stderr_sha256": _sha(done.stderr), "memory_peak_bytes": peak}
        self.evidence.step(step, "finished", facts)
        if done.returncode != 0:
            raise Refused("phase_failed", f"{phase} exited {done.returncode}")
        return facts

    # -- the copy sequence --

    def run_copies(self, commands: dict[str, Sequence[str]], *, bracket: Callable[[], dict] | None = None,
                   remove_seal_b: Callable[[], None] | None = None) -> None:
        """S -> (seal-b, bracket, seal-b removed) -> A -> B -> D -> R7, one unit and one peak per copy."""
        unknown = [c for c in commands if c not in COPY_NAMES]
        if unknown or any(c not in commands for c in COPY_SEQUENCE):
            raise Refused("copy_sequence", f"need {','.join(COPY_SEQUENCE)}; got {','.join(sorted(commands))}")
        if (SEAL_B in commands) != (bracket is not None):
            raise Refused("copy_sequence", "seal-b and the bracket go together")
        for copy in COPY_SEQUENCE:
            self.run_phase(f"copy-{copy.lower()}", commands[copy], step=f"copy-{copy}")
            self.sequence.append(copy)
            if copy == "S" and bracket is not None:
                self.run_phase("copy-seal-b", commands[SEAL_B], step=f"copy-{SEAL_B}")
                self.sequence.append(SEAL_B)
                self.evidence.step("bracket", "finished", bracket_summary(bracket()))
                if remove_seal_b is not None:
                    remove_seal_b()
                self.evidence.step(f"{SEAL_B}-removed", "finished", {})

    # -- the run --

    def write_plan(self, identities: dict, *, extra_images: dict | None = None, tools: dict | None = None) -> dict:
        facts = {"run8": self.run8, "root": str(self.root), "identities": check_identities(identities),
                 "labels": [f"{RUN_LABEL}={self.run8}"], "images": {"postgres": PG_IMAGE, "redis": REDIS_IMAGE,
                                                                    **(extra_images or {})},
                 "tool_sha256": tools if tools is not None else tool_sha256s(), "unit_prefix": f"zeus-rehearsal-{self.run8}-"}
        write_record(self.dir / "plan.json", {"run8": self.run8, "at": self.clock(), "facts": facts},
                     max_items=MAX_RECORD_ITEMS, mode=0o600)
        return facts

    def _after_failed_work(self) -> None:
        try:
            self.pause_gate("after")
        except Exception:  # noqa: BLE001 - already recorded as a step; the work's own error is the one raised
            pass

    def run(self, identities: dict, work: Callable[["RunDriver"], None], *, extra_images: dict | None = None,
            tools: dict | None = None) -> None:
        """plan.json, run-start.json, pause gate, `work(self)`, pause gate; `run-exit.json` in `finally`."""
        previous = os.umask(0o077)
        status, facts = "failed", {}
        try:
            self.evidence.start({"unit_prefix": f"zeus-rehearsal-{self.run8}-"})
            try:
                self.write_plan(identities, extra_images=extra_images, tools=tools)
                self.pause_gate("before")
                try:
                    work(self)
                except BaseException:
                    self._after_failed_work()  # the second gate still runs and is recorded; the original error wins
                    raise
                self.pause_gate("after")
                status = "ok"
            except BaseException as error:
                facts = {"error": type(error).__name__, "code": getattr(error, "code", None)}
                raise
            finally:
                facts["peaks"] = {step: peak for step, peak in self.peaks.items()}
                facts["copies"] = list(self.sequence)
                self.evidence.finish(status, facts)
        finally:
            os.umask(previous)
