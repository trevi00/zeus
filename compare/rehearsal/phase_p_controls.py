"""Cutover RH-2b (owner-run, NOT a pytest test): real-docker controls for Phase P over labelled stand-ins.

The test guard admits none of the forms these controls need (`docker diff`, `exec touch`, `restart`, a volume mount), and
it is not widened: the owner runs this module once, recorded, as AC2 evidence. It spawns docker through `phase_p.Host`
and imports no guard-installing module (`copies`, `sweep`, `r5_drivers`, `run.py`: RH-2c, D-RH2-RUNNER-GUARD); the
CL2 disposable-copy controls are a guarded fixture test (tests/test_rehearsal_cl2_controls.py), not part of this runner. Pytest drives only its refusal logic and sequencing (stubs).

Stand-ins are `zeus-test-fixture-rh-<run8>-prod-{pg,redis}` and the volume `...-prod-redisdata`, labelled
`zeus.test.fixture=1` and `zeus.rehearsal.standin=<run8>` (NOT the run label: a run-labelled container that is not a Phase P
helper is residue to `settle_helpers`), `--network none`, the pinned images, `--pull never`. Every target is refused,
before any effect, unless its name matches that pattern; the production names are refused explicitly.

Controls (each its own stand-ins, torn down by name and proven absent): positive; docker_diff (a file planted in the
stand-in pg before P4); redis_write_during_copy (a bounded writer on the stand-in Redis while P3's helper copies);
restart (the stand-in pg restarted before P4); paused_false. Outcomes are step, reason and
booleans only.

usage (cwd compare/): python3 -m rehearsal.phase_p_controls RUN8 SCRATCH_DIR OUT_JSON   (SCRATCH_DIR and OUT_JSON must not exist;
SCRATCH_DIR should be short: the disposable copy's sockets live under it)
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

from . import Refused, check_run8
from . import phase_p as pp
from .constants import PG_IMAGE, PRODUCTION_PREFIX, REDIS_IMAGE, create_root, provider_guard

STANDIN_LABEL = "zeus.rehearsal.standin"
NAME = re.compile(r"^zeus-test-fixture-rh-([0-9a-f]{8})-prod-(pg|redis|redisdata)$")
CONTROLS = ("positive", "docker_diff", "redis_write_during_copy", "restart", "paused_false")
EXPECTED = {
    "positive": {"step": "P4", "reason": "ok"},
    "docker_diff": {"step": "P4", "reason": "docker_diff_changed"},
    "redis_write_during_copy": {"step": "P3", "reason": "redis_bracket_unequal"},
    "restart": {"step": "P4", "reason": "container_restarted"},
    "paused_false": {"step": "P0", "reason": "not_paused_or_not_quiet"},
}
PSQL = ["psql", "-U", "zeus", "-h", "/var/run/postgresql", "-XAtq", "-v", "ON_ERROR_STOP=1"]


def standin_targets(run8: str, scratch) -> pp.Targets:
    prefix = f"{provider_guard.FIXTURE_NAME_PREFIX}rh-{check_run8(run8)}-prod-"
    return pp.Targets(pg=prefix + "pg", redis=prefix + "redis", redis_volume=prefix + "redisdata",
                      monitoring=str(Path(scratch) / "monitoring.json"), heartbeat=str(Path(scratch) / "heartbeat.json"))


def validate_targets(targets: pp.Targets, run8: str, scratch) -> None:
    """Refuse (before any effect) any target that is not this run's labelled stand-in; production names explicitly."""
    check_run8(run8)
    for name, kind in ((targets.pg, "pg"), (targets.redis, "redis"), (targets.redis_volume, "redisdata")):
        if name in (pp.PG, pp.REDIS, pp.REDIS_VOLUME) or name.startswith(PRODUCTION_PREFIX):
            raise Refused("production_name", name)
        match = NAME.match(name)
        if match is None or match[1] != run8 or match[2] != kind:
            raise Refused("standin_name", name)
    for path in (targets.monitoring, targets.heartbeat):
        if path in (pp.MONITORING, pp.HEARTBEAT) or not Path(path).resolve().is_relative_to(Path(scratch).resolve()):
            raise Refused("standin_path", path)


def need(what: str, proc) -> None:
    if proc.returncode != 0:
        raise RuntimeError(f"{what} failed (exit {proc.returncode})")  # never an output body


class StandIns:
    """The labelled stand-in production for one control: created, mutated and removed by exact name."""

    def __init__(self, host, run8: str, scratch, targets: pp.Targets | None = None):
        self.host, self.run8, self.scratch = host, check_run8(run8), Path(scratch)
        self.targets = targets or standin_targets(run8, scratch)
        validate_targets(self.targets, run8, scratch)  # before any effect
        self.writer = None

    def docker(self, *args, timeout=120):
        return self.host.run(["docker", *args], timeout=timeout)

    def labels(self) -> list[str]:
        return ["--label", provider_guard.FIXTURE_LABEL, "--label", f"{STANDIN_LABEL}={self.run8}"]

    def set_paused(self, paused: bool) -> None:
        self.scratch.mkdir(parents=True, exist_ok=True)
        Path(self.targets.monitoring).write_text(json.dumps({"sources": {"fleet": {"data": {"paused": paused}}}}))
        Path(self.targets.heartbeat).write_text(json.dumps({"active": 0, "unresolved": 0, "instance_id": "standin"}))

    def _wait(self, name: str, ready, seconds: int = 120) -> None:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            logs = self.docker("logs", name)
            if ready(logs.stdout + logs.stderr):
                return
            time.sleep(1)
        raise RuntimeError(f"{name} did not become ready")

    def sql(self, sql: str, db: str = "postgres"):
        done = self.docker("exec", self.targets.pg, *PSQL, "-d", db, "-c", sql)
        need("stand-in sql", done)
        return done

    def create(self) -> None:
        for image in (PG_IMAGE, REDIS_IMAGE):
            need("pinned image present (never pulled)", self.docker("image", "inspect", "--format", "{{.Id}}", image))
        need("volume create", self.docker("volume", "create", *self.labels(), self.targets.redis_volume))
        common = ["run", "-d", "--pull", "never", "--network", "none", *self.labels()]
        need("redis stand-in", self.docker(*common, "--name", self.targets.redis, "--memory", "512m", "--mount",
                                           f"type=volume,src={self.targets.redis_volume},dst=/data", REDIS_IMAGE,
                                           "redis-server", "--appendonly", "yes", "--save", "", "--dir", "/data"))
        need("pg stand-in", self.docker(*common, "--name", self.targets.pg, "--memory", "1g", "-e", "POSTGRES_USER=zeus",
                                        "-e", "POSTGRES_HOST_AUTH_METHOD=trust", PG_IMAGE, "-c", "listen_addresses="))
        self.verify_labels()
        self._wait(self.targets.redis, lambda text: "Ready to accept connections" in text)
        self._wait(self.targets.pg, lambda text: (lambda i: i >= 0 and "ready to accept connections" in text[i:])(
            text.find("PostgreSQL init process complete")))
        for db in pp.DB_SCOPE:
            self.sql(f"CREATE DATABASE {db}")
        # Every scope database is seeded, as production's are non-empty: the positive judge needs a non-empty
        # catalog TOC per database (an empty zeus_aibox_migration made `all(toc)` false; owner, run 5).
        for db in pp.DB_SCOPE:
            self.sql("CREATE TABLE rh_ctl(x text); INSERT INTO rh_ctl VALUES ('seed')", db)
        self.set_paused(True)

    def verify_labels(self) -> None:
        for name in (self.targets.pg, self.targets.redis):
            done = self.docker("inspect", "--format", "{{json .Config.Labels}}", name)
            need("label inspect", done)
            labels = json.loads(done.stdout)
            if labels.get("zeus.test.fixture") != "1" or labels.get(STANDIN_LABEL) != self.run8:
                raise Refused("standin_unlabelled", name)

    # -- mutations (stand-in only) --
    def plant_file(self) -> None:
        need("plant file", self.docker("exec", self.targets.pg, "touch", "/tmp/rh-planted"))

    def restart(self) -> None:
        need("restart", self.docker("restart", self.targets.pg, timeout=120))

    def start_writer(self) -> None:
        """A bounded writer (about 5 s at most) on the stand-in Redis; its docker client's pid is the only one stopped."""
        self.writer = subprocess.Popen(["docker", "exec", self.targets.redis, "redis-cli", "-r", "5000", "-i", "0.001",
                                        "SET", "rh:k", "v"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def stop_writer(self) -> None:
        if self.writer is not None:
            self.writer.terminate()
            self.writer.wait(timeout=30)
            self.writer = None

    # -- reads --
    def toc(self, dump_path) -> list[str]:
        """`pg_restore -l` of a dump with the header comment lines (which carry the dump time) dropped."""
        with open(dump_path, "rb") as fh:
            done = subprocess.run(["docker", "exec", "-i", self.targets.pg, "pg_restore", "-l"], stdin=fh,
                                  capture_output=True, text=True, timeout=300)
        need("pg_restore -l", done)
        return [line for line in done.stdout.splitlines() if not line.startswith(";")]

    # -- teardown --
    def remove(self) -> dict:
        """Remove exactly the stand-ins by name (never a pattern), then prove absence by label."""
        self.stop_writer()
        for name in (self.targets.pg, self.targets.redis):
            self.docker("rm", "-f", "-v", name)
        self.docker("volume", "rm", "-f", self.targets.redis_volume)
        left_c = self.docker("ps", "-a", "--filter", f"label={STANDIN_LABEL}={self.run8}", "--format", "{{.ID}}")
        left_v = self.docker("volume", "ls", "-q", "--filter", f"label={STANDIN_LABEL}={self.run8}")
        ok = left_c.returncode == 0 and left_v.returncode == 0 and not left_c.stdout.split() and not left_v.stdout.split()
        return {"containers_left": len(left_c.stdout.split()), "volumes_left": len(left_v.stdout.split()), "absent": ok}


class ControlHost:
    """Wraps the real (or stub) host and applies one control's mutation at its point in the Phase P sequence."""

    def __init__(self, host, stand, plan: str | None):
        self.host, self.stand, self.plan, self.inspects = host, stand, plan, 0

    def open(self, path, mode="r"):
        return self.host.open(path, mode)

    def run(self, argv, *, timeout=120, stdout=None):
        argv = list(argv)
        if argv[1] == "inspect":
            self.inspects += 1
            if self.inspects == 3:  # P4's first inspect: after P0 (two) and everything between
                {"docker_diff": self.stand.plant_file, "restart": self.stand.restart}.get(self.plan, lambda: None)()
        copying = self.plan == "redis_write_during_copy" and argv[1] == "run" and "redis-snap" in argv[argv.index("--name") + 1]
        if copying:
            self.stand.start_writer()
        try:
            return self.host.run(argv, timeout=timeout, stdout=stdout)
        finally:
            if copying:
                self.stand.stop_writer()


def classify(code: int, rec: dict) -> dict:
    steps = {s["step"]: s for s in rec["steps"]}
    failed = rec.get("failed_step")
    if failed:
        return {"step": failed["step"], "reason": failed["reason"]}
    verdict = rec.get("verdict", "")
    if verdict.startswith("refused"):
        return {"step": "P0", "reason": "not_paused_or_not_quiet"}
    if verdict.startswith("STOP: production changed"):
        p0, p4 = steps["P0"]["containers"], steps["P4"]["containers"]
        if any(p0[n][k] != p4[n][k] for n in p0 for k in ("Id", "StartedAt", "RestartCount")):
            return {"step": "P4", "reason": "container_restarted"}
        if any(p0[n]["diff_sha256"] != p4[n]["diff_sha256"] for n in p0):
            return {"step": "P4", "reason": "docker_diff_changed"}
        return {"step": "P4", "reason": "gate_not_paused_or_quiet"}
    if code == 0 and verdict == "ok":
        return {"step": "P4", "reason": "ok"}
    return {"step": "?", "reason": "unclassified"}


class Runner:
    def __init__(self, host, run8: str, scratch, *, stand_factory=StandIns):
        self.host, self.run8, self.scratch = host, check_run8(run8), Path(scratch)
        self.stand_factory = stand_factory

    def phase(self, work: Path, stand, plan):
        root, evidence = work / "root", work / "evidence"
        create_root(root, self.run8)
        os.makedirs(root / "p", mode=0o700)
        os.makedirs(evidence, mode=0o700)
        phase = pp.PhaseP(str(root), str(evidence), self.run8, ControlHost(self.host, stand, plan), stand.targets)
        code = phase.run()
        return phase, code, json.loads((evidence / "phase-p.json").read_text())

    def positive_facts(self, stand, root: Path, rec: dict) -> dict:
        steps = {s["step"]: s for s in rec["steps"]}
        toc = {tag: [stand.toc(root / "p" / f"{db}.{tag}.dump") for db in pp.DB_SCOPE] for tag in ("d0a", "d0b")}
        return {"dumps_equal": toc["d0a"] == toc["d0b"] and all(toc["d0a"]),
                "redis_bracket_identical": steps["P3"].get("manifest_equal") is True and steps["P3"].get("ok") is True,
                "helpers_settled": rec.get("helpers_before") == {"removed": 0, "residue": []}
                and rec.get("helpers_after") == {"removed": 0, "residue": []}}

    def control(self, name: str) -> dict:
        work = self.scratch / name
        stand = self.stand_factory(self.host, self.run8, work)
        outcome, facts = {}, {}
        try:
            stand.create()
            if name == "paused_false":
                stand.set_paused(False)
            plan = name if name in ("docker_diff", "redis_write_during_copy", "restart") else None
            _phase, code, rec = self.phase(work, stand, plan)
            outcome = classify(code, rec)
            steps = [s["step"] for s in rec["steps"]]
            root = work / "root"
            if name == "positive":
                facts = self.positive_facts(stand, root, rec)
            elif name == "redis_write_during_copy":
                facts = {"stopped_before_p2b": "P2b" not in steps}
            elif name == "paused_false":
                facts = {"no_acquisition": steps == ["P0"] and not (root / "p" / "redis").exists()
                         and not list((root / "p").glob("*.dump"))}
            matched = self.judge(name, outcome, facts)
        except Exception as exc:  # bounded: the type only
            matched, facts = False, {**facts, "error": type(exc).__name__}
        torn = stand.remove()
        return {"control": name, "outcome": outcome, "facts": facts, "matched": matched and torn["absent"], "teardown": torn}

    @staticmethod
    def judge(name: str, outcome: dict, facts: dict) -> bool:
        return outcome == EXPECTED[name] and all(v is True for v in facts.values())

    def run_all(self) -> dict:
        results = [self.control(name) for name in CONTROLS]
        return {"run8": self.run8, "controls": results, "all_matched": all(r["matched"] for r in results)}


def main(run8: str, scratch, out) -> int:
    check_run8(run8)
    if os.path.lexists(scratch) or os.path.lexists(out):
        raise Refused("path_exists", "SCRATCH_DIR and OUT_JSON must not exist")
    validate_targets(standin_targets(run8, scratch), run8, scratch)  # before any effect
    os.makedirs(scratch, mode=0o700)
    result = Runner(pp.Host(), run8, scratch).run_all()
    with pp.Host().open(out, "x") as fh:
        json.dump(result, fh, indent=1, sort_keys=True)
        fh.write("\n")
    print(json.dumps({"all_matched": result["all_matched"], "controls": {r["control"]: r["matched"] for r in result["controls"]}}))
    return 0 if result["all_matched"] else 1


if __name__ == "__main__":
    if len(sys.argv) != 4:
        raise SystemExit("usage: python3 -m rehearsal.phase_p_controls RUN8 SCRATCH_DIR OUT_JSON")
    try:
        sys.exit(main(*sys.argv[1:]))
    except Refused as refusal:
        raise SystemExit(str(refusal))
