"""Cutover RH-2/RH-8 (owner): rehearsal Phase P, the ONLY code that names production resources.

Every production touch is a READ, and every required command's success is part of admission (RH-8 F1):
- P0  pause + quiet gate: monitoring.json sources.fleet.data.paused is true; managed heartbeat active 0 / unresolved 0;
      the pg/redis container facts (allowlisted --format, never Env); the docker diff digest. A failed inspect or
      diff is a STOP, never an empty digest.
- P1  read-only SQL via local trust in the production container: database names (both scope databases must exist);
      pg_stat_activity counts by datname/application_name (no query text).
- P2a per DB in scope (zeus_aibox, zeus_aibox_migration): `pg_dump -Fc` to STDOUT, captured on the host into
      ROOT/p/<db>.d0a.dump (O_EXCL, 0600, 0700 dir). Never `-f` inside the production container. The dump must exit 0,
      be non-empty and carry the custom-archive magic.
- P3  the Redis-a helper: a labelled `--network none` container with the redis volume mounted READONLY + volume-nocopy,
      copying appendonlydir (+ dump.rdb when present) out. Before/after manifests record path, size, mtime and sha256
      and must be identical; the copied file set and digests must equal the manifest; then `redis-check-aof` (no
      --fix) on the COPY's single manifest, whose exit must be 0.
- P2b dump again as d0b (the quiescence bracket around P3).
- P5  (between P2b and P4, so P4's gate brackets it) the four file roots acquired into ROOT/seal by
      `fileroots.acquire` (E9; layout, closed reason list and bounds are in fileroots' docstring), with
      pg_stat_activity samples at its start and end and a declared PG-to-file skew.
- P4  repeat P0: container Id/StartedAt/RestartCount equal and docker-diff digest equal.
P5 reads: the METADATA of `srv/<4 tops>` minus runtime/tokobs (never `srv` itself); the CONTENT of the stable roots, the
stable single files and the volatile files (atime may move). Nothing is written under srv; writes go only under ROOT/seal.
P5 commands: 8 `CP -a -T` argvs, one `CP --version` (inside acquire), and 2 psql (the P1 activity SQL, byte-identical).
Never: record_run (it buffers stdout into evidence), a secret read, an environment value, a write to production.
Evidence (names, counts, digests, exit codes; no stderr bodies, no dump bytes) goes to the evidence dir; raw copies and
failed raw files stay under ROOT, a 0700 directory this tool creates (F4).

A failure or timeout writes a bounded failed-step receipt. Helper containers carry BOTH `zeus.test.fixture=1` and
`zeus.rehearsal.run=<run8>` and the names `zeus-test-fixture-rh-<run8>-p-<role>` (F2), so the run-owned sweep sees
them; `settle_helpers` removes only this attempt's named helpers and proves absence, else HOLDs.

Run lock (E9, D5): `PhaseP.run` holds an abstract AF_UNIX socket bound to `"\\0" + RUN_LOCK` for the whole run; a second
run gets `failed_step {step: lock, reason: phase_p_lock_held}` (another bind error: `phase_p_lock_failed`) and runs no
command. The socket is released by the kernel when its holder dies (unix(7)); it is network-namespace scoped.
Interruption (D4): no signal handler. `KeyboardInterrupt` is caught into the receipt (`interrupted`); SIGKILL, OOM and
RuntimeMaxSec cannot be receipted. VALIDITY: a ROOT whose phase-p.json lacks verdict `ok`, or whose
`seal/meta/complete.json` is missing or fails `fileroots.verify_seal`, is INVALID and is kept for diagnosis.
Ceilings (D11): `CEILINGS_S` is, per step, the sum of the `Host.run` timeouts attributed to the step at call time (the
after-settle is its own `settle_after` key); `CEILING_S` is their sum (22870). P5 is "deadline-bounded; the verify after the
last admitted cp and the tail are outside; RH-9 adds margin" (its cp_identity probe is 10 s; the 8 cp timeouts are not summed).
New reasons: phase_p_lock_held, phase_p_lock_failed, interrupted, evidence_unbounded, seal_overlaps_source (ROOT or
EVIDENCE_DIR overlaps `Targets.srv`, refused before any effect), sql_activity_{start,end}_exit_<n>; acquire's are in fileroots.

All external interfaces go through a `Host` (`run`, `open`) so tests drive synthetic failures without docker.
usage (cwd compare/): python3 -m rehearsal.phase_p ROOT EVIDENCE_DIR RUN8   (ROOT and EVIDENCE_DIR must not exist)
"""

from __future__ import annotations

import datetime
import errno
import hashlib
import json
import os
import re
import socket
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from . import Refused, check_run8, fileroots
from .constants import PRODUCTION_PREFIX, RUN_LABEL, create_root, provider_guard
from .evidence import check_facts

PG, REDIS = "zeus-aibox-postgres", "zeus-aibox-redis"
REDIS_VOLUME = "zeus-aibox-redisdata"
REDIS_IMAGE = "redis@sha256:858f009f9709ce576febc734aa78b8f6d624b82571f9ddb6bda4377c833b3499"
DB_SCOPE = ("zeus_aibox", "zeus_aibox_migration")  # AMD-1 C.5; zeus_canary_* inventoried by name only
MONITORING = "/srv/zeus/runtime/control/monitoring.json"
HEARTBEAT = "/srv/zeus/runtime/managed-fleet/heartbeat.json"
INSPECT = ('{"Id":{{json .Id}},"Image":{{json .Image}},"StartedAt":{{json .State.StartedAt}},'
           '"RestartCount":{{json .RestartCount}},"ExecIDs":{{json .ExecIDs}}}')
HELPER_ROLES = ("redis-snap", "aof-check")
DUMP_MAGIC = b"PGDMP"
MANIFEST_LINE = re.compile(r"^(\./.+) (\d+) (\d+) ([0-9a-f]{64})$")
AOF_MANIFEST_NAME = re.compile(r"^[A-Za-z0-9._-]+\.manifest$")
SCHEMA = "zeus:aibox-migration-001:rehearsal:phase-p:3"
RUN_LOCK = "zeus-rehearsal-phase-p"
ACTIVITY_SQL = ("SELECT coalesce(datname,''), coalesce(application_name,''), count(*) "
                "FROM pg_stat_activity GROUP BY 1,2 ORDER BY 1,2")
CEILINGS_S = {  # D11: the Host.run timeouts the code passes, per step (settle: two lists and two removals)
    "settle": 60 + 2 * 120 + 60,
    "P0": 2 * (120 + 120),
    "P1": 2 * 120,
    "P2a": 2 * 3600,
    "P3": 900 + 900,
    "P2b": 2 * 3600,
    "P5": 2 * 120 + 10 + fileroots.DEADLINE_S + fileroots.CP_TIMEOUT_S,  # deadline-bounded (see the docstring)
    "P4": 2 * (120 + 120),
    "settle_after": 60 + 2 * 120 + 60,
}
CEILING_S = sum(CEILINGS_S.values())


@dataclass(frozen=True)
class Targets:
    """The resources Phase P reads. The default is exactly the production set; only a caller in code (the owner-run
    control runner, over labelled stand-ins) passes another, and `main` never accepts one from the command line."""

    pg: str = PG
    redis: str = REDIS
    redis_volume: str = REDIS_VOLUME
    monitoring: str = MONITORING
    heartbeat: str = HEARTBEAT
    srv: str = fileroots.SRV


DEFAULT_TARGETS = Targets()


class StepFailed(Exception):
    """A required command or check failed: the attempt STOPs. `detail` is bounded facts only (never output bodies)."""

    def __init__(self, step: str, reason: str, **detail):
        super().__init__(f"{step}: {reason}")
        self.step, self.reason, self.detail = step, reason, detail


class HoldError(RuntimeError):
    """A helper container of unknown ownership or residue remains: nothing may continue."""

    def __init__(self, ids: list[str]):
        super().__init__("helper containers remain: " + ", ".join(ids))
        self.ids = ids


class Host:
    """The external interfaces Phase P uses; production code uses this one, tests substitute a synthetic one."""

    def run(self, argv, *, timeout=120, stdout=None):
        if stdout is None:
            return subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        return subprocess.run(argv, stdout=stdout, stderr=subprocess.PIPE, timeout=timeout)

    def open(self, path, mode="r"):
        if "x" in mode or "w" in mode:  # a file this tool creates is owner-only
            return open(path, mode, opener=lambda p, flags: os.open(p, flags, 0o600))
        return open(path, mode)


def now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def helper_name(run8: str, role: str) -> str:
    return f"{provider_guard.FIXTURE_NAME_PREFIX}rh-{run8}-p-{role}"


def helper_labels(run8: str) -> list[str]:
    return ["--label", provider_guard.FIXTURE_LABEL, "--label", f"{RUN_LABEL}={run8}"]


def _lines(stream) -> int:
    return len(stream.splitlines()) if stream else 0


def need(step: str, what: str, proc) -> None:
    if proc.returncode != 0:
        raise StepFailed(step, f"{what}_exit_{proc.returncode}", exit=proc.returncode, stderr_lines=_lines(proc.stderr))


def _list_helpers(host, run8: str, field: str) -> list[str]:
    done = host.run(["docker", "ps", "-a", "--filter", f"label={RUN_LABEL}={run8}", "--filter",
                     f"label={provider_guard.FIXTURE_LABEL}", "--format", field], timeout=60)
    if done.returncode != 0:
        raise HoldError(["listing-failed"])  # absence cannot be proven
    return [line for line in done.stdout.split() if line]


def settle_helpers(host, run8: str) -> dict:
    """Remove ONLY this attempt's named helpers (both labels and a `-p-<role>` name of this run), then prove absence.

    A labelled container of any other name (unknown ownership, a production name included) is not touched and, like a
    failed removal, is residue: it raises `HoldError`. The root-deleting sweep option is never called here."""
    check_run8(run8)
    owned = {helper_name(run8, role) for role in HELPER_ROLES}
    removed = 0
    for name in _list_helpers(host, run8, "{{.Names}}"):
        if name.startswith(PRODUCTION_PREFIX) or name not in owned:
            continue
        done = host.run(["docker", "rm", "-f", name], timeout=120)
        if done.returncode != 0 and "no such container" not in (done.stderr or "").lower():
            continue  # the residue listing below reports it
        removed += 1
    residue = _list_helpers(host, run8, "{{.ID}}")
    if residue:
        raise HoldError(residue)
    return {"removed": removed, "residue": []}


def parse_manifest(text: str, step: str, which: str) -> dict:
    """`./path size mtime sha256` lines -> {path: (size, mtime, sha256)}; any malformed line is a STOP."""
    out = {}
    for line in text.splitlines():
        match = MANIFEST_LINE.match(line)
        if match is None:
            raise StepFailed(step, f"{which}_manifest_malformed")
        out[match[1]] = (int(match[2]), int(match[3]), match[4])
    return out


def sha256_file(path) -> tuple[int, str]:
    digest, size = hashlib.sha256(), 0
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
            size += len(chunk)
    return size, digest.hexdigest()


def copied_files(out: Path) -> dict:
    """{./relative/path: (size, sha256)} of every regular file under `out` (symlinks are not followed or admitted)."""
    found = {}
    for dirpath, dirnames, filenames in os.walk(out, followlinks=False):
        for name in filenames:
            full = os.path.join(dirpath, name)
            if os.path.islink(full):
                raise StepFailed("P3", "copy_symlink")
            found["./" + os.path.relpath(full, out).replace(os.sep, "/")] = sha256_file(full)
    return found


def redis_script(uid: int, gid: int) -> str:
    return ("set -euo pipefail\n"
            "manifest() { cd /src && find . -type f | LC_ALL=C sort | while IFS= read -r f; do "
            "printf '%s %s %s %s\\n' \"$f\" \"$(stat -c %s \"$f\")\" \"$(stat -c %Y \"$f\")\" "
            "\"$(sha256sum \"$f\" | cut -d' ' -f1)\"; done; }\n"
            "(manifest) > /meta/before\n"
            "cp -a /src/appendonlydir /out/\n"
            "if [ -e /src/dump.rdb ]; then cp -a /src/dump.rdb /out/; fi\n"
            "(manifest) > /meta/after\n"
            f"chown -R {uid}:{gid} /out /meta\n")


class PhaseP:
    def __init__(self, root, evidence, run8, host=None, targets=None):
        self.targets = targets or DEFAULT_TARGETS
        self.root, self.evidence, self.run8 = str(root), str(evidence), check_run8(run8)
        self.host = host or Host()
        self.step = "init"
        self.rec = {"schema": SCHEMA, "run8": run8, "steps": []}

    # -- production reads (every command's success is required) --

    def gate(self, step: str) -> dict:
        with self.host.open(self.targets.monitoring) as fh:
            mon = json.load(fh)
        paused = (((mon.get("sources") or {}).get("fleet") or {}).get("data") or {}).get("paused") is True
        with self.host.open(self.targets.heartbeat) as fh:
            hb = json.load(fh)
        quiet = hb.get("active") == 0 and hb.get("unresolved") == 0
        facts = {}
        for name in (self.targets.pg, self.targets.redis):
            inspected = self.host.run(["docker", "inspect", "--format", INSPECT, name])
            need(step, f"inspect_{name}", inspected)
            raw = json.loads(inspected.stdout)
            raw["ExecIDs"] = len(raw.get("ExecIDs") or [])
            diffed = self.host.run(["docker", "diff", name])
            need(step, f"diff_{name}", diffed)
            diff = sorted(diffed.stdout.splitlines())
            raw["diff_sha256"] = hashlib.sha256("\n".join(diff).encode()).hexdigest()
            facts[name] = raw
        return {"at": now(), "paused": paused, "quiet": quiet, "heartbeat_instance": hb.get("instance_id"),
                "containers": facts}

    def psql(self, step: str, what: str, sql: str):
        done = self.host.run(["docker", "exec", self.targets.pg, "psql", "-U", "zeus", "-h", "/var/run/postgresql", "-d", "postgres",
                              "-XAtq", "-v", "ON_ERROR_STOP=1", "-c", sql])
        need(step, what, done)
        return done

    def dump(self, db: str, tag: str) -> dict:
        path = os.path.join(self.root, "p", f"{db}.{tag}.dump")
        started = now()
        with self.host.open(path, "xb") as out:
            proc = self.host.run(["docker", "exec", self.targets.pg, "pg_dump", "-U", "zeus", "-h", "/var/run/postgresql", "-d", db,
                                  "-Fc", "--lock-wait-timeout=30000", "--no-password"], timeout=3600, stdout=out)
        size, digest = sha256_file(path)
        with open(path, "rb") as fh:
            magic = fh.read(len(DUMP_MAGIC)) == DUMP_MAGIC
        return {"db": db, "exit": proc.returncode, "bytes": size, "sha256": digest, "archive_magic": magic,
                "stderr_lines": _lines(proc.stderr), "ok": proc.returncode == 0 and size > 0 and magic,
                "started_at": started, "finished_at": now()}

    def dumps(self, step: str, tag: str) -> None:
        entry = {"step": step, "started_at": now(), "dumps": []}
        self.rec["steps"].append(entry)
        for db in DB_SCOPE:
            fact = self.dump(db, tag)
            entry["dumps"].append(fact)
            if not fact["ok"]:  # the raw file stays under ROOT/p; only its size/digest/exit are recorded
                raise StepFailed(step, f"dump_{db}_failed", exit=fact["exit"], bytes=fact["bytes"])
        entry["finished_at"] = now()

    # -- P3 --

    def redis_copy(self) -> dict:
        step = self.step = "P3"
        out, meta = os.path.join(self.root, "p", "redis"), os.path.join(self.root, "p", "redis-meta")
        for directory in (out, meta):
            os.makedirs(directory, mode=0o700)
            os.chmod(directory, 0o700)
        facts = {"step": step, "started_at": now()}
        self.rec["steps"].append(facts)
        proc = self.host.run(
            ["docker", "run", "--rm", "--network", "none", *helper_labels(self.run8),
             "--name", helper_name(self.run8, "redis-snap"), "--memory", "1g",
             "--mount", f"type=volume,src={self.targets.redis_volume},dst=/src,readonly,volume-nocopy",
             "--mount", f"type=bind,src={out},dst=/out", "--mount", f"type=bind,src={meta},dst=/meta",
             "--entrypoint", "sh", REDIS_IMAGE, "-c", redis_script(os.getuid(), os.getgid())], timeout=900)
        facts["exit"] = proc.returncode
        need(step, "redis_copy", proc)
        with open(os.path.join(meta, "before")) as fh:
            before = parse_manifest(fh.read(), step, "before")
        with open(os.path.join(meta, "after")) as fh:
            after = parse_manifest(fh.read(), step, "after")
        facts["manifest_equal"] = before == after
        facts["files"] = len(before)
        facts["manifest_fields"] = ["path", "size", "mtime", "sha256"]
        if before != after:
            raise StepFailed(step, "redis_bracket_unequal")
        expected = {path: (v[0], v[2]) for path, v in before.items()
                    if path.startswith("./appendonlydir/") or path == "./dump.rdb"}
        copied = copied_files(Path(out))
        facts["copy_equals_manifest"] = copied == expected
        facts["dump_rdb_present"] = "./dump.rdb" in expected
        if not any(path.startswith("./appendonlydir/") for path in expected) or copied != expected:
            raise StepFailed(step, "redis_copy_unequal")
        manifests = sorted(path for path in copied if re.fullmatch(r"\./appendonlydir/[^/]+\.manifest", path))
        facts["aof_manifests"] = len(manifests)
        if len(manifests) != 1 or not AOF_MANIFEST_NAME.match(manifests[0].rsplit("/", 1)[1]):
            raise StepFailed(step, "aof_manifest_missing_or_ambiguous", count=len(manifests))
        check = self.host.run(
            ["docker", "run", "--rm", "--network", "none", *helper_labels(self.run8),
             "--name", helper_name(self.run8, "aof-check"), "--memory", "1g",
             # redis-check-aof opens the BASE file read-write even without --fix, so it aborts on the read-only copy:
             # it checks a byte-identical duplicate in the helper's tmpfs, and the sealed copy stays read-only. The
             # manifest name is AOF_MANIFEST_NAME-validated above, so it is safe in the sh -c string.
             "--tmpfs", "/tmp", "--mount", f"type=bind,src={out},dst=/c,readonly", "--entrypoint", "sh", REDIS_IMAGE,
             "-c", "cp -a /c /tmp/k && exec redis-check-aof /tmp/k/appendonlydir/" + manifests[0][2:].rsplit("/", 1)[1]],
            timeout=900)
        facts["aof_check_exit"] = check.returncode
        need(step, "aof_check", check)
        facts["finished_at"] = now()
        facts["ok"] = True
        return facts

    # -- P5 --

    def p5(self) -> None:
        step = self.step = "P5"
        entry = {"step": step, "started_at": now()}
        self.rec["steps"].append(entry)
        start = self.psql(step, "sql_activity_start", ACTIVITY_SQL)
        try:
            facts = fileroots.acquire(self.host, self.targets.srv, Path(self.root) / "seal", self.run8)
        except fileroots.RefusedFacts as error:
            raise StepFailed(step, error.code, **error.facts) from None
        except Refused as error:
            raise StepFailed(step, error.code, detail=fileroots._redact(error.detail)) from None
        end = self.psql(step, "sql_activity_end", ACTIVITY_SQL)
        finished = now()
        d0b = next(s for s in self.rec["steps"] if s["step"] == "P2b")["finished_at"]
        candidate = {**entry, **{k: v for k, v in facts.items() if k != "ok"},
                     "activity_start": start.stdout.splitlines()[:64], "activity_end": end.stdout.splitlines()[:64],
                     "skew": {"d0b_finished_at": d0b, "p5_started_at": entry["started_at"], "p5_finished_at": finished,
                              "volatile_read_span_ns": facts["volatile_read_span_ns"]},
                     "finished_at": finished}
        try:
            check_facts(candidate)  # E9: the entry is bounded as a whole before it may carry `ok` (A-F12)
        except Refused as error:
            raise StepFailed(step, "evidence_unbounded", rule=error.code) from None
        entry.update(candidate)
        entry["ok"] = True

    # -- the attempt --

    def attempt(self) -> int:
        self.step = "settle"
        self.rec["helpers_before"] = settle_helpers(self.host, self.run8)
        self.step = "P0"
        p0 = self.gate("P0")
        self.rec["steps"].append({"step": "P0", **p0})
        if not (p0["paused"] and p0["quiet"]):
            self.rec["verdict"] = "refused: Fleet not paused or not quiet"
            return 1
        self.step = "P1"
        dbs = self.psql("P1", "sql_databases", "SELECT datname FROM pg_database ORDER BY 1")
        act = self.psql("P1", "sql_activity", ACTIVITY_SQL)
        names = dbs.stdout.split()
        self.rec["steps"].append({"step": "P1", "databases": names, "activity": act.stdout.splitlines(),
                                  "exit": [dbs.returncode, act.returncode]})
        missing = [db for db in DB_SCOPE if db not in names]
        if missing:
            raise StepFailed("P1", "scope_database_missing", missing=missing)
        self.step = "P2a"
        self.dumps("P2a", "d0a")
        self.redis_copy()
        self.step = "P2b"
        self.dumps("P2b", "d0b")
        self.p5()
        self.step = "P4"
        p4 = self.gate("P4")
        self.rec["steps"].append({"step": "P4", **p4})
        same = all(p0["containers"][n][k] == p4["containers"][n][k] for n in (self.targets.pg, self.targets.redis)
                   for k in ("Id", "StartedAt", "RestartCount", "diff_sha256"))
        self.rec["verdict"] = "ok" if same and p4["paused"] and p4["quiet"] else "STOP: production changed during Phase P"
        return 0 if self.rec["verdict"] == "ok" else 1

    def run(self) -> int:
        refuse_overlap((self.root, self.evidence), self.targets.srv)  # before the lock and any effect (D18)
        lock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)  # non-inheritable: no child holds it (D5)
        try:
            try:
                lock.bind("\0" + RUN_LOCK)
            except OSError as exc:
                reason = "phase_p_lock_held" if exc.errno == errno.EADDRINUSE else "phase_p_lock_failed"
                self.rec["failed_step"] = {"step": "lock", "reason": reason}
                self.rec["verdict"] = f"STOP: lock failed: {reason}"
                return self.finish(1)
            code = 1
            try:
                code = self.attempt_settled()
            finally:
                self.finish(code)
            return code
        finally:
            lock.close()

    def attempt_settled(self) -> int:
        try:
            code = self.attempt()
        except StepFailed as exc:
            self.rec["failed_step"] = {"step": exc.step, "reason": exc.reason, **exc.detail}
            self.rec["verdict"], code = f"STOP: {exc.step} failed: {exc.reason}", 1
        except HoldError as exc:
            self.rec["failed_step"] = {"step": self.step, "reason": "helper_residue", "ids": exc.ids}
            self.rec["verdict"], code = f"HOLD: helper residue before or during {self.step}", 1
        except subprocess.TimeoutExpired as exc:
            self.rec["failed_step"] = {"step": self.step, "reason": "timeout", "timeout_s": exc.timeout}
            self.rec["verdict"], code = f"STOP: {self.step} timed out", 1
        except KeyboardInterrupt:  # D4: no signal handler; a receipt for the one interruption Python can see
            self.rec["failed_step"] = {"step": self.step, "reason": "interrupted"}
            self.rec["verdict"], code = f"STOP: {self.step} interrupted", 1
        except Exception as exc:  # a bounded receipt: the exception type only, never its message
            self.rec["failed_step"] = {"step": self.step, "reason": f"exception:{type(exc).__name__}"}
            self.rec["verdict"], code = f"STOP: {self.step} raised {type(exc).__name__}", 1
        last = self.step
        self.step = "settle_after"  # its Host.run timeouts are attributed here (D11)
        try:  # the attempt is settled whatever happened: only this attempt's named helpers, absence proven
            self.rec["helpers_after"] = settle_helpers(self.host, self.run8)
        except HoldError as exc:
            self.rec["helpers_after"] = {"residue": exc.ids}
            self.rec["verdict"], code = f"HOLD: helper residue after {last}; {self.rec.get('verdict', '')}", 1
        except KeyboardInterrupt:
            self.rec["helpers_after"] = {"residue": ["settle-interrupted"]}
            self.rec["verdict"], code = f"HOLD: helper settlement interrupted after {last}; {self.rec.get('verdict', '')}", 1
        except Exception as exc:
            self.rec["helpers_after"] = {"residue": [f"settle-failed:{type(exc).__name__}"]}
            self.rec["verdict"], code = f"HOLD: helper settlement failed; {self.rec.get('verdict', '')}", 1
        return code

    def finish(self, code: int) -> int:
        self.rec.setdefault("verdict", f"STOP: {self.step} aborted")
        with self.host.open(os.path.join(self.evidence, "phase-p.json"), "x") as fh:
            json.dump(self.rec, fh, indent=1, sort_keys=True)
            fh.write("\n")
        print(json.dumps({"verdict": self.rec["verdict"]}))
        return code


def refuse_overlap(paths, srv) -> None:
    """D18: ROOT and EVIDENCE_DIR must not equal, contain or lie inside the source (realpath reads only path metadata)."""
    real_srv = Path(os.path.realpath(srv))
    for path in paths:
        real = Path(os.path.realpath(path))
        if real == real_srv or real.is_relative_to(real_srv) or real_srv.is_relative_to(real):
            raise Refused("seal_overlaps_source", "ROOT and EVIDENCE_DIR must not overlap the source")


def main(root, evidence, run8, host=None) -> int:
    check_run8(run8)
    if os.path.lexists(root) or os.path.lexists(evidence):
        raise Refused("path_exists", "ROOT and EVIDENCE_DIR must not exist")
    refuse_overlap((root, evidence), DEFAULT_TARGETS.srv)  # D18: before anything is created
    create_root(Path(root), run8)  # F4: ROOT itself, exclusive 0700, before any child
    os.makedirs(os.path.join(root, "p"), mode=0o700)
    os.chmod(os.path.join(root, "p"), 0o700)
    os.makedirs(evidence, mode=0o700, exist_ok=False)
    return PhaseP(root, evidence, run8, host).run()


if __name__ == "__main__":
    if len(sys.argv) != 4:
        raise SystemExit("usage: python3 -m rehearsal.phase_p ROOT EVIDENCE_DIR RUN8")
    try:
        sys.exit(main(*sys.argv[1:]))
    except Refused as refusal:
        raise SystemExit(str(refusal))
