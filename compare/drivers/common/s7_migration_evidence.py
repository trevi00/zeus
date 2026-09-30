"""Shared S7 scenario steps (`delivery.migration_evidence`): the M7 read-only producer of the managed
`limited_active` evidence, `adapters/host_migration_evidence.py` (`HostReader`, `bounded_run`, `observe`, the capture
and its recheck, the PH4-13 comparison and the F1 typed output), recorded BEFORE the move (DESIGN-s7 §2 row
`delivery.migration_evidence`; TRACE-s7 §5.6; INV-HOST-MIGRATION-001).

Seven case groups, each case labelled in the result and mirroring one M7 test (or one parametrization) of
`tests/test_host_migration_evidence.py` (440-1753; the mapping is `mirrored_tests` in the result):
- `capture`: a genuine launch and managed consumption (three bound receipts and the draft), the previous-instance
  binding, the activation file equal as an object, and the CLI printing the observation, evidence and draft.
- `refuse`: every refusal the tests name: the owner canary (19), the consumption controls (17), the process chain,
  launch provenance and journal (26), the activation file, `current`, the fence and the coordinator (8), the
  expected id, unreadable sources (17), an unavailable store (3), identity changes during the capture (12), a source
  gone at the recheck (12), an unreadable recheck, an invalid request (7), the stricter-than-incumbent canary rule
  and the arguments the CLI refuses.
- `read_only`: the producer writes, locks, spawns and signals nothing on success and on failure (6), every host file
  is opened `O_RDONLY | O_NOFOLLOW | O_NONBLOCK`, and the lane path reads every store through read-only snapshots.
- `archive`: every source hash and the common digest recompute from the archive, the strict observation document,
  the nine archives `--expect` refuses before any read and the unreadable archive files.
- `host_reader`: the absolute, filtered, minimal-environment commands; `bounded_run` with its byte cap, deadline
  and exact environment over REAL fixture children; a FIFO or a link in place of a file; the monotonic comparison
  after a suspend; a reused pid keeps only an argv digest; the `HostReader.file` primitives.
- `ph4_13`: the pre-submit comparison (unchanged, 8 refused changes), the post-check after the recorded managed
  transition (passing, 8 refused differences), the read-only CLI comparison and its verdict exit.
- `f1`: no excluded key or untyped value reaches the result or the CLI (37 leak cases), a rejected host document
  keeps its raw digest, shape and typed identifiers only, an accepted source is its complete typed document, the
  stable capture still compares raw bytes, and a credential typed where an environment name belongs is never echoed.

**Fixtures (all LABELLED; M7's `World`, its store, runner and clock doubles, host files and constants, copied here,
the test module is never imported).** One temporary `ZEUS_AIBOX_ROOT` per case with labelled release and sealed-runtime
fixtures, a fixture `/proc` read through the accepted `HostFacts`, `MemoryStore` behind a read-only wrapper
(`ReadOnly`), a fake `systemctl show`/`journalctl` runner (`Runner`: the recorded argv and environment) and a ticking
`Clock` (the producer's clock; nothing reads the wall clock). The journal lines are produced by the unchanged
deploy/aibox launcher's own `emit` (`api.launcher_emit`). The CLI is driven IN PROCESS through `api.main(argv)`
with the doubles M7 supplies by monkeypatch, each supplied by an `api` hook and restored after the case:
`api.patched(**attributes)` (attributes of the producer module), `api.environ(values)` (the process environment),
`api.patch_connect(function)` (`psycopg.connect`) and `api.forbid_writer_store(record)` (the writer store constructor).
The fake monotonic clock of `determinism.install` freezes `bounded_run`'s deadline, so the one deadline case keeps
it moving from a labelled helper thread (`api.advance(seconds)`). Only local interpreters (`sys.executable -c ...`)
run as real children: no `systemctl`, `journalctl`, PostgreSQL, network or production `/proc` is ever used.

**What is recorded.** Per case: the result or refusal code, the observation (checks, sources, lineage, activation),
the projections that differ from the labelled baseline capture (all of them for the baseline), the evidence and draft,
the recorded commands (the argv joined, and the environment key sets), the files read (relative, through `os.open`
with its flags, or through `open`) and the write attempts (every write, lock, spawn and signal primitive is guarded
during the producer's run and raises; the attempts are listed, always empty). Every refusal also records the M7
shape checks (`refused()`: failed receipts bound to the observation digest, no draft, a valid observation, a
digest that recomputes).

`api` supplies: `observe`, `Ports`, `HostReader`, `bounded_run`, `boottime_offset_usec`, `Unreadable`,
`validate_request`, `cli_ports`, `SYSTEMCTL`, `JOURNALCTL`, `COMMAND_ENV`, `MAX_COMMAND_BYTES` (the producer module),
`main`, `parser`, `document_bytes` (M7 `host_migration._document_bytes`), `owner_qualified_canary`,
`launcher_emit`, `launcher_path`, `MANIFEST_SCHEMA`, `HostFacts`, `MemoryStore`, `HostMigrations`, `LaneSnapshotStore`,
`conninfo_to_dict`, `OperationalError`, `BUCKET`, `BUCKET_TARGETS`, `BUCKET_PLANS`, `BUCKET_INTENTS`,
`BUCKET_DESCRIPTORS`, `policy` (M7 `domain.host_migration_evidence`: `CHECKS`, `SOURCES`, `OBSERVATION_FIELDS`,
`STARTUP_DOCUMENT`, `HISTORY_ENTRY`, `UNAVAILABLE`, `DOCUMENT`, `LAUNCH`, `PROCESS`, `CONSUMPTION`, `CANARY`,
`CHANGED`, `validate_observation`, `observation_digest`, `observation_receipts`, `transition_draft`),
`migration` (M7 `domain.host_migration`: `EVIDENCE_SCHEMA`, `INTENT_SCHEMA`, `SUCCESSOR_SCHEMA`, `ACTIVATION_SCHEMA`,
`OBSERVATION`, `RESTORED_PAUSED`, `LIMITED_ACTIVE`, `MigrationRefused`, `validate_transition`, `transition_id`,
`managed_consumption_subject`, `managed_canary_subject`), `ACTIVE`, `DESCRIPTOR_SCHEMA`, `PLAN_SCHEMA`,
`RECEIPT_SCHEMA`, `descriptor_digest`, `new_intent`, `plan_digest`, `validate_plan`, `validate_targets`,
`blob_id`, `new_manifest`, `digest`, `DELIVERY_CANARY`, `action_id`, `canary_receipt`, `canary_request` and
`advance(seconds)` (the fake clock).

**Normalization is explicit, done here and identical on both sides** (the rules of `s7_host_targets`, reduced):
- `sys.executable` → `<python>`; this run's temporary root → `<root>` and the case's own root → `<world>`;
- the digests that embed a run path, each replaced by a fixture label computed by the FIXTURE itself from what it
  built or from the output by the side's own `digest`: the descriptor digest (`<sha:descriptor_sha256>`), the
  canary action id and binding digest, the sha256 of every fixture file (`<sha:file.RELATIVE_PATH>`, the `#2` label
  when the same file holds other bytes), the observation digest (`<sha:result>`), each source projection digest
  (`<sha:source.NAME>`) and the transition id. The same digest keeps one label in a case, and a label never
  depends on the observed value, only on the order in which the fixture first saw it;
- a projection's `raw_sha256` (the digest of the object as read, which embeds the run path for the process,
  delivery and canary-record sources and cannot be recomputed from the output) → `<sha:raw.SOURCE>`, with the
  `#2` label for another value of it in the same case; the coordinator's `history_sha256` and
  `previous_history_sha256` (they cover the recorded transition's lineage), computed by the fixture from the row;
  the canary job and operation ids, which carry the first 24 hex
  digits of the action id → `<action_id[:24]>`;
- the boottime offset of the REAL `boottime_offset_usec` → `<boottime-offset>` (only its type and sign are recorded);
  no other real measurement is recorded: the real monotonic readings only move `bounded_run`'s deadline, the real pid
  of this process appears only in the fixture `/proc/self/stat`, and the real children's pids and output are
  reduced to booleans and the `Unreadable` reason.
A projection's `raw_sha256` is labelled, not masked blind: every summarized case records `raw_digests`, the booleans
"this raw digest equals the sha256 of the exact bytes the fixture wrote" (file-backed sources and the host
configuration) or "equals the digest of the view the producer hashes, recomputed from the same store rows" (delivery,
canary record), both taken before the run. `raw_digest_covers` states what each source hashes; the launch and process
sources hash an object the producer builds and are not recomputed.
The M7 fixture constants (revisions, instance ids, pids, tick counts, cursors, timestamps) stay literal, and nothing
else is masked. No secret-shaped test value is ever written to the result: each is assembled at run time and the
run fails when one reaches the result (M7 test 1032 asserts the same of the output).

Carried: none of the 46 M7 tests needs a real PostgreSQL connection, a real host command or the harness's own
environment, so all 46 are mirrored (the CLI ones through the `api` hooks above). Unreachable without the real host
(recorded, never attempted): `unreachable.real_systemd` (the real `systemctl show` and `journalctl` answers),
`unreachable.real_proc` (the `/proc` of a production process) and `unreachable.real_postgresql` (the real
`LaneSnapshotStore` session).
"""

from __future__ import annotations

import builtins
import contextlib
import copy
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

PY = sys.executable
HEX64 = re.compile(r"[0-9a-f]{64}")
MID = "aibox-migration-001"
INTENT_REV = "c" * 40      # the recorded intent (ced20281 analogue); also the registered interpreter's release
ACT_REV = "5" * 40         # the effective successor: launch authority and `current` (5aa220f analogue)
PAYLOAD = "e" * 40         # the consumed managed descriptor's payload revision (ec8aa0a2 analogue)
IMAGE = "sha256:" + "9" * 64
PROFILE = "c" * 64
HOST_ID = "machine-id-sha256:" + "d" * 64
TARGET = "aibox-managed-fleet"
PLAN = "own-976435bd1700ceeafbebbd47"
OTHER_PLAN = "own-8b007c5414d93fe96982ac09"
INSTANCE = "c58b78dd8c7b4f0e917900a2bb640e44"
PREVIOUS = "aae814ee74a94fdaa4aa04983cf456ba"
PREDECESSOR = "e2" * 32
INVOCATION = "e304d7b2fdc64f5bb667b3d4d6569e1a"
OLD_INVOCATION = "aa68d1857e754ebf9a363a9802de2587"
BOOT = "673e87db-d2a0-433c-895d-e069a3b97ccd"
BOOT_HEX = BOOT.replace("-", "")
UNIT = "zeus-aibox-managed-fleet.service"
CGROUP = "/system.slice/zeus-aibox-managed-fleet.service"
SUP_PID, ENTRY_PID = 2354473, 2354522
EXEC_MAIN = 49818378056
SUP_TICKS, ENTRY_TICKS = 4981837, 4981866
LAUNCH_MONO, LAUNCH_REAL = 49818434928, 1790544287458722
STARTED_AT = "2026-09-27T21:24:47.781597+00:00"
RECORDED_AT = "2026-09-27T21:26:43.421597+00:00"
LOCK = b"# labelled uv.lock fixture\n"
MODULE = "codex_harness.adapters.managed_runtime"
STREAM = "aab17a6192c242018273c435b78ae485"
RECEIPT_NAME = "owner-canary-receipt." + PLAN + ".json"
REQUEST_NAME = "owner-canary-request." + PLAN + ".json"
SUSPENDED_USEC = 3_600_000_000  # the host slept an hour before this unit started
MARKER = "F1-canary-7c1e"
SECRET = "password=" + MARKER + " free text"  # fits no declared type
MARKER_PATH = "/srv/" + MARKER                 # path-shaped: withheld until the document's check accepts it
PW = "hunter" + "2"                            # assembled: no secret-shaped literal in this source
WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
ENGINE_IMAGE = "sha256:" + "c" * 64
H = "a" * 64


def dsn(password: str, host: str = "127.0.0.1/zeus") -> str:
    """A labelled secret-shaped connection string, assembled at run time."""
    return "postgresql://zeus:" + password + "@" + host


# ---- fixtures (M7 tests/test_host_migration.py module helpers, LABELLED) --------------------------------------------
def engine(kind: str, host: str) -> dict:
    if kind == "postgres":
        return {"image": "pgvector/pgvector:pg17", "image_digest": ENGINE_IMAGE, "major": 17, "database": "zeus",
                "endpoint": {"kind": "docker_exec", "name": host + "-postgres"}, "extensions": ["plpgsql", "vector"]}
    return {"image": "redis:7.4-alpine", "image_digest": ENGINE_IMAGE, "major": 7,
            "instance": "dedicated", "endpoint": {"kind": "docker_exec", "name": host + "-redis"},
            "namespaces": ["zeus-fleet-harness", "zeus-fleet-interface"]}


def manifest(api) -> dict:
    return {
        "schema": api.MANIFEST_SCHEMA, "migration_id": MID, "created_at": "2026-09-25T05:00:00Z",
        "source": {"host_id": "windows-pc", "platform": "windows",
                   "postgres": engine("postgres", "src"), "redis": engine("redis", "src")},
        "target": {"host_id": "aibox", "platform": "linux",
                   "postgres": engine("postgres", "dst"), "redis": engine("redis", "dst")},
        "schema_map": {"public": "zeus_aibox_control", "zeus_fleet_harness": "zeus_aibox_harness"},
        "path_map": [{"id": "artifacts", "from": "D:/workspaces/zeus/artifacts", "to": "/srv/zeus/artifacts"},
                     {"id": "backups", "from": "D:/workspaces/zeus/backups", "to": "/srv/zeus/backups"}],
        "repository": {"commit": "b" * 40, "dirty_count": 0, "dirty_sha256": H, "ignored_preserved": [".venv-notes"]},
        "artifact_roots": [{"id": "evidence", "path_id": "artifacts", "entries": 3, "bytes": 10, "tree_sha256": H}],
        "pg_buckets": [{"schema": "public", "bucket": "fleet_registry", "count": 1, "sha256": H},
                       {"schema": "zeus_fleet_harness", "bucket": "operations", "count": 2, "sha256": H}],
        "redis_keys": [{"key": "zeus-fleet-harness:stream:worker", "type": "stream", "sha256": H,
                        "expires_at_ms": None,
                        "stream": {"length": 2, "last_generated_id": "1-1",
                                   "groups": [{"name": "workers", "last_delivered_id": "1-0",
                                               "pending": 1, "consumers": 1}]}}],
        "writers": [{"id": "zeusfleet-run", "kind": "scheduled_task", "owner": "zeus",
                     "zeus_owned": True, "disposition": "stop_and_fence"},
                    {"id": "baldrix-cron", "kind": "scheduled_task", "owner": "user",
                     "zeus_owned": False, "disposition": "leave_untouched_not_zeus"}],
        "fence": {"kind": "admission_pause_and_marker", "marker_id": "aibox-migration-001"},
        "rollback": {"location_id": "backups", "reverse_supported": True, "source_retained": True},
    }


def receipt(api, check: str, subject: str) -> dict:
    return {"schema": api.migration.EVIDENCE_SCHEMA, "check": check, "subject": subject, "exit_code": 0, "ok": True,
            "result_sha256": "a" * 64}


def launch_event(**overrides) -> dict:
    return {"event": "launch", "role": "managed-fleet", "revision": ACT_REV, "migration_id": MID, **overrides}


def main_line(message: str, *, index: int = 0) -> dict:
    """One later line of the main pid's stream, as journald attributes it."""
    return {"MESSAGE": message, "_PID": str(SUP_PID), "_STREAM_ID": STREAM,
            "_BOOT_ID": BOOT_HEX, "_SYSTEMD_INVOCATION_ID": INVOCATION, "_SYSTEMD_UNIT": UNIT, "_TRANSPORT": "stdout",
            "__CURSOR": "s=088ada45;i=" + format(145000 + index, "x"),
            "__MONOTONIC_TIMESTAMP": str(LAUNCH_MONO + 900_000 + index),
            "__REALTIME_TIMESTAMP": str(LAUNCH_REAL + 900_000 + index)}


def stat_line(pid: int, ppid: int, ticks: int, name: str = "python") -> str:
    fields = ["S", str(ppid), str(pid), str(pid), "0", "-1", "4194560"] + ["0"] * 12 + [str(ticks), "92794880", "11498"]
    return str(pid) + " (" + name + ") " + " ".join(fields) + "\n"


class ReadOnly:
    """A store view whose transactions can read and never write; it counts what it was asked."""

    def __init__(self, store):
        self.store, self.transactions, self.fail, self.puts = store, 0, None, []

    @contextlib.contextmanager
    def transaction(self):
        self.transactions += 1
        if self.fail is not None:
            raise self.fail
        with self.store.transaction() as tx:
            yield _ReadTx(tx, self.puts)


class _ReadTx:
    def __init__(self, tx, puts):
        self.tx, self.puts = tx, puts

    def get(self, bucket, key):
        return self.tx.get(bucket, key)

    def scan(self, bucket):
        return self.tx.scan(bucket)

    def put(self, bucket, *args, **kwargs):
        self.puts.append(bucket)
        raise AssertionError("store write attempted")


class Runner:
    """`systemctl show` and `journalctl` answers (bytes, as `bounded_run` returns them); anything else is an
    unexpected command. Each call's argv and environment are kept. The recheck hook runs with the write guard paused
    (it is the fixture mutating the host between the capture and the recheck, never the producer)."""

    def __init__(self, api, world):
        self.api, self.world, self.calls, self.envs, self.shows, self.on_recheck = api, world, [], [], 0, None

    def __call__(self, argv, timeout=None, env=None, limit=None):
        self.calls.append(list(argv))
        self.envs.append(env)
        if argv[:2] == [self.api.SYSTEMCTL, "show"]:
            self.shows += 1
            if self.shows == 2 and self.on_recheck is not None:
                with self.world.guard.paused():
                    self.on_recheck()
            text = "".join(key + "=" + value + "\n" for key, value in self.world.unit.items())
            rc = self.world.show_rc if self.shows == 1 else self.world.recheck_show_rc
            return subprocess.CompletedProcess(argv, rc, text.encode(), b"")
        if argv[:1] == [self.api.JOURNALCTL]:
            text = "".join(json.dumps(entry) + "\n" for entry in self.world.journal)
            return subprocess.CompletedProcess(argv, self.world.journal_rc, text.encode(),
                                               self.world.journal_stderr)
        raise AssertionError("unexpected command")


class Clock:
    def __init__(self):
        self.ticks = 0

    def __call__(self) -> str:
        self.ticks += 1
        return (datetime(2026, 9, 28, 11, 30, tzinfo=timezone.utc) + timedelta(milliseconds=self.ticks)).isoformat()


class Guard:
    """M7's `no_effects`: every write, lock, process, signal and network primitive records the attempt and raises,
    and every open is recorded. `paused()` lets the FIXTURE mutate the host during the producer's run."""

    def __init__(self, world):
        self.world, self.attempts, self.os_opens, self.opens, self.suspended = world, [], {}, set(), False

    def _relative(self, path):
        text = str(path)
        prefix = str(self.world.tmp) + os.sep
        return text[len(prefix):] if text.startswith(prefix) else None

    @contextlib.contextmanager
    def paused(self):
        before, self.suspended = self.suspended, True
        try:
            yield
        finally:
            self.suspended = before

    @contextlib.contextmanager
    def active(self):
        real_open, real_os_open = builtins.open, os.open
        guard = self

        def refuse(name, original):
            def refused_effect(*args, **kwargs):
                if guard.suspended:
                    return original(*args, **kwargs)
                guard.attempts.append(name)
                raise AssertionError("side effect: " + name)
            return refused_effect

        def guarded_open(file, mode="r", *args, **kwargs):
            if guard.suspended:
                return real_open(file, mode, *args, **kwargs)
            if any(flag in mode for flag in "wax+"):
                guard.attempts.append("open:" + mode)
                raise AssertionError("side effect: open:" + mode)
            relative = guard._relative(file)
            if relative is not None:
                guard.opens.add(relative)
            return real_open(file, mode, *args, **kwargs)

        def guarded_os_open(path, flags, *args, **kwargs):
            if guard.suspended:
                return real_os_open(path, flags, *args, **kwargs)
            if flags & WRITE_FLAGS:
                guard.attempts.append("os.open")
                raise AssertionError("side effect: os.open")
            relative = guard._relative(path)
            if relative is not None:
                guard.os_opens[relative] = (bool(flags & os.O_NOFOLLOW), bool(flags & os.O_NONBLOCK))
            return real_os_open(path, flags, *args, **kwargs)

        import fcntl
        import socket

        with contextlib.ExitStack() as stack:
            stack.enter_context(_patch(builtins, "open", guarded_open))
            stack.enter_context(_patch(io, "open", guarded_open))
            stack.enter_context(_patch(os, "open", guarded_os_open))
            for name in ("replace", "rename", "remove", "unlink", "rmdir", "mkdir", "makedirs", "symlink", "link",
                         "chmod", "chown", "truncate", "utime", "mkfifo", "kill", "killpg", "execv", "execve",
                         "system", "fork", "posix_spawn", "posix_spawnp"):
                stack.enter_context(_patch(os, name, refuse("os." + name, getattr(os, name))))
            for module, names in ((shutil, ("rmtree", "move", "copy", "copy2", "copyfile", "copytree")),
                                  (tempfile, ("mkstemp", "mkdtemp", "NamedTemporaryFile", "TemporaryDirectory")),
                                  (subprocess, ("Popen", "run", "call", "check_call", "check_output")),
                                  (socket, ("socket", "create_connection")), (fcntl, ("flock", "lockf"))):
                for name in names:
                    stack.enter_context(_patch(module, name, refuse(module.__name__ + "." + name,
                                                                    getattr(module, name))))
            yield


@contextlib.contextmanager
def _patch(owner, name, value):
    original = getattr(owner, name)
    setattr(owner, name, value)
    try:
        yield
    finally:
        setattr(owner, name, original)


class Labels:
    """Fixture labels of the digests that embed a run path: the first digest of a base is `<sha:BASE>`, the next
    distinct one `<sha:BASE#2>`."""

    def __init__(self):
        self.by_value, self.count = {}, {}

    def add(self, value, base: str) -> None:
        if not (isinstance(value, str) and HEX64.fullmatch(value)) or value in self.by_value:
            return
        number = self.count.get(base, 0) + 1
        self.count[base] = number
        self.by_value[value] = "<sha:" + (base if number == 1 else base + "#" + str(number)) + ">"


class Lab:
    """One run: the temporary root and the case worlds."""

    def __init__(self, api, base: Path):
        self.api, self.base, self.serial, self.mirrors = api, base, 0, {}
        self.baseline = self.baseline_facts = None

    def world(self) -> "World":
        self.serial += 1
        world = World(self, self.base / ("w%03d" % self.serial))
        if self.baseline is None:
            self.baseline, self.baseline_facts = world.baseline_projections, world.baseline_facts
            assert world.baseline_facts["files"], "the baseline capture read no file"
        else:
            assert world.baseline_facts == self.baseline_facts, "the baseline host facts differ between worlds"
            assert world.baseline_projections == self.baseline, "a path-bearing digest of the baseline is unlabelled: " + \
                json.dumps(diff(self.baseline, world.baseline_projections))[:1500]
        return world

    def mirror(self, test: str, key: str) -> None:
        self.mirrors.setdefault(test, []).append(key)


class World:
    """One consistent host: coordinator in restored_paused with a successor, the launcher files, the managed state
    directory, the delivery lane, the owner-action record, `/proc` and the unit (M7 `World`)."""

    def __init__(self, lab: Lab, tmp: Path):
        self.lab, self.api, self.tmp = lab, lab.api, tmp
        api = self.api
        self.labels, self.guard = Labels(), Guard(self)
        self.substitutions = [(str(tmp), "<world>"), (str(lab.base), "<root>"), (PY, "<python>")]
        self.root = tmp / "srv"
        self.control = self.root / "runtime" / "control"
        self.state = self.root / "runtime" / "managed-fleet"
        self.releases = self.root / "releases"
        self.managed = self.root / "managed-fleet"
        self.proc = tmp / "proc"
        for path in (self.control, self.state, self.root / "repo", self.root / "config", self.proc / "self"):
            path.mkdir(parents=True)
        for revision in (INTENT_REV, ACT_REV):
            python = self.releases / revision / ".venv" / "bin" / "python"
            python.parent.mkdir(parents=True)
            python.write_text("# labelled release fixture\n")
        os.symlink(ACT_REV, self.releases / "current")
        self.config = self.root / "config" / "zeus-aibox.env"
        self.config.write_text("ZEUS_AIBOX_ROOT=" + str(self.root) + "\n")
        self._seal()
        self.target = api.validate_targets({"schema": "urn:zeus:host-delivery-targets:1", "targets": [{
            "target_id": TARGET, "kind": "managed_fleet_systemd", "root": str(self.managed),
            "state_dir": str(self.state), "service": "zeus-aibox-managed-fleet", "source": str(self.root / "repo"),
            "python": str(self.releases / INTENT_REV / ".venv" / "bin" / "python"),
            "environment_lock": hashlib.sha256(LOCK).hexdigest()}]})["targets"][0]
        self.descriptor = {"schema": api.DESCRIPTOR_SCHEMA, "target_id": TARGET,
                           "root": str(self.managed / "runtimes" / PAYLOAD), "revision": PAYLOAD,
                           "worker_image": IMAGE, "profile_digest": PROFILE, "predecessor": PREDECESSOR}
        self.descriptor_sha256 = api.descriptor_digest(self.descriptor)
        self.labels.add(self.descriptor_sha256, "descriptor_sha256")
        self._coordinator()
        self._delivery()
        self._host()
        self.archive = self.good = None
        self.snapshots = {}
        self._baseline()

    # --- builders -------------------------------------------------------------------------------
    def _seal(self):
        api = self.api
        final = self.managed / "runtimes" / PAYLOAD
        files = {"pyproject.toml": b"[project]\nname = 'fixture'\n",
                 "src/codex_harness/__init__.py": b"# labelled sealed runtime fixture\n", "uv.lock": LOCK}
        for relative, data in files.items():
            (final / relative).parent.mkdir(parents=True, exist_ok=True)
            (final / relative).write_bytes(data)
        sealed, listing = api.new_manifest(PAYLOAD, "b" * 40, [(path, api.blob_id(data)) for path, data in files.items()],
                                           hashlib.sha256(LOCK).hexdigest())
        (final / "runtime-files.json").write_text(json.dumps(listing))
        (final / "runtime.json").write_text(json.dumps(sealed))

    def _coordinator(self):
        api, M = self.api, self.api.migration
        self.coordinator = api.MemoryStore()
        coordinator = api.HostMigrations(self.coordinator)
        self.manifest_sha256 = coordinator.plan(manifest(api))["manifest_sha256"]
        with self.coordinator.transaction() as tx:
            row = tx.get(api.BUCKET, MID)
            row["state"] = M.RESTORED_PAUSED
            tx.put(api.BUCKET, MID, row)
        intent_id = coordinator.intend_activation({
            "schema": M.INTENT_SCHEMA, "migration_id": MID, "host_id": HOST_ID,
            "release_revision": INTENT_REV, "image": IMAGE, "profile_sha256": PROFILE, "actor": "owner",
            "at": "2026-09-25T06:00:00Z"})["intent_id"]
        self.effective_id = coordinator.record_successor({
            "schema": M.SUCCESSOR_SCHEMA, "migration_id": MID, "host_id": HOST_ID,
            "predecessor_id": intent_id, "release_revision": ACT_REV, "image": IMAGE, "profile_sha256": PROFILE,
            "environment_lock": "f" * 64, "reason_code": "bootstrap-recovery",
            "evidence": {"release_identity": receipt(api, M.OBSERVATION, "revision=" + ACT_REV),
                         "worker_compatibility": receipt(api, M.OBSERVATION, "image=" + IMAGE),
                         "admission_drained": receipt(api, M.OBSERVATION, "fleet=paused-settled")},
            "actor": "owner", "at": "2026-09-26T14:09:55Z"})["successor_id"]
        self.activation_document = coordinator.activation_document(MID)
        (self.control / "host-activation.json").write_bytes(api.document_bytes(self.activation_document))

    def _delivery(self):
        api = self.api
        plan = api.validate_plan({
            "schema": api.PLAN_SCHEMA, "plan_id": PLAN, "release_id": "7" * 64, "revision": PAYLOAD, "tree": "f" * 40,
            "policy_hash": "a" * 64, "repository": "github:trevi00/zeus", "required_checks": ["test"],
            "target_id": TARGET, "expected_descriptor": PREDECESSOR,
            "target_descriptor": {"revision": PAYLOAD, "worker_image": "unchanged", "profile_digest": "unchanged"},
            "canary_check_id": "fleet_worker_operation", "ci_timeout_seconds": 3600,
            "consumption_timeout_seconds": 900})
        self.plan, self.plan_sha256 = plan, api.plan_digest(plan)
        binding = {"plan_id": PLAN, "plan_sha256": self.plan_sha256, "target_id": TARGET,
                   "descriptor_sha256": self.descriptor_sha256, "instance_id": INSTANCE}
        self.action_id = api.action_id(api.DELIVERY_CANARY, binding)
        self.labels.add(self.action_id, "action_id")
        self.substitutions.append((self.action_id[:24], "<action_id[:24]>"))  # the canary job and operation ids
        self.labels.add(api.digest(binding), "binding_sha256")
        outcome = {"state": "accepted", "reason_code": "canary_accepted",
                   "evidence": {"job_id": "canary-" + self.action_id[:24], "operation_id": "canary-" + self.action_id[:24],
                                "decision_id": "9ba9669e-59f6-4e8a-a2e0-a1deded4d5fd",
                                "execution_ref": "sha256:" + "cb" * 32}}
        self.record = {"id": self.action_id, "kind": api.DELIVERY_CANARY, "state": "completed", "binding": binding,
                       "binding_sha256": api.digest(binding), "policy_id": "aibox-owner", "policy_sha256": "ab" * 32,
                       "subject": {"intent_id": "intent"}, "reason_code": "canary_accepted",
                       "job_id": "canary-" + self.action_id[:24], "outcome": outcome, "version": 3,
                       "created_at": "2026-09-27T20:35:08+00:00", "updated_at": RECORDED_AT, "history": []}
        self.control_store = api.MemoryStore()
        with self.control_store.transaction() as tx:
            tx.put("owner_actions", self.action_id, self.record)
        canary = api.canary_receipt(self.record, outcome, RECORDED_AT)
        intent = api.new_intent(plan, self.plan_sha256, "2026-09-27T20:30:00+00:00")
        intent.update(stage=api.ACTIVE, previous_stage="awaiting_consumption", descriptor=self.descriptor,
                      descriptor_sha256=self.descriptor_sha256, previous_descriptor_sha256=PREDECESSOR,
                      previous_instance_id=PREVIOUS, candidate_instance_id=INSTANCE, instance_id=INSTANCE,
                      canary={"passed": True, "evidence": canary["evidence"], "reason_code": None,
                              "check_id": "fleet_worker_operation"})
        self.delivery = api.MemoryStore()
        with self.delivery.transaction() as tx:
            tx.put(api.BUCKET_TARGETS, TARGET, {"id": TARGET, **self.target, "registered_at": "2026-09-26T10:00:00+00:00",
                                                "updated_at": "2026-09-26T10:00:00+00:00"})
            tx.put(api.BUCKET_PLANS, PLAN, {"id": PLAN, "plan_id": PLAN, "plan": plan, "plan_sha256": self.plan_sha256,
                                            "pin": {"revision": "1" * 40, "path": "deploy/aibox/owner-plans/p.json",
                                                    "sha256": "2" * 64}, "target_id": TARGET})
            tx.put(api.BUCKET_INTENTS, PLAN, intent)
            tx.put(api.BUCKET_INTENTS, OTHER_PLAN, {"id": OTHER_PLAN, "plan_id": OTHER_PLAN, "target_id": TARGET,
                                                    "stage": api.ACTIVE})
            tx.put(api.BUCKET_DESCRIPTORS, TARGET, {
                "id": TARGET, "target_id": TARGET, "descriptor": self.descriptor,
                "descriptor_sha256": self.descriptor_sha256, "consumed": True, "startup_observed": True,
                "observed_instance_id": INSTANCE, "observed_revision": PAYLOAD,
                "observed_runtime_root": self.descriptor["root"], "instance_id": INSTANCE, "plan_id": PLAN,
                "release_id": "7" * 64, "rolled_back": False, "history": [], "updated_at": RECORDED_AT})
        self.write(self.state / "descriptor.json", self.descriptor)
        # What `managed_runtime.supervise` journals on each unit (re)start: an older invocation, then this one.
        self.supervisor_journal([{"event": "launch", "descriptor_sha256": PREDECESSOR, "workload": "fleet",
                                  "invocation_id": OLD_INVOCATION, "at": "2026-09-27T12:08:03+00:00"},
                                 {"event": "launch", "descriptor_sha256": self.descriptor_sha256,
                                  "workload": "fleet", "invocation_id": INVOCATION,
                                  "at": "2026-09-27T21:24:47.671458+00:00"}])
        self.write(self.state / "startup-receipt.json", {
            "schema": api.RECEIPT_SCHEMA, "target_id": TARGET, "instance_id": INSTANCE, "pid": ENTRY_PID,
            "started_at": STARTED_AT, "runtime_root": self.descriptor["root"],
            "module_root": self.descriptor["root"] + "/src/codex_harness", "descriptor_sha256": self.descriptor_sha256,
            "revision": PAYLOAD, "worker_image": IMAGE, "profile_digest": PROFILE})
        self.write(self.state / ("owner-canary-receipt." + PLAN + ".json"), canary)
        self.write(self.state / ("owner-canary-request." + PLAN + ".json"),
                   api.canary_request({"id": "0" * 64}, plan, self.plan_sha256, "2026-09-27T20:35:08+00:00"))

    def _host(self):
        (self.proc / "self" / "stat").write_text(stat_line(os.getpid(), 1, 100, "pytest"))
        (self.proc / "sys" / "kernel" / "random").mkdir(parents=True)
        (self.proc / "sys" / "kernel" / "random" / "boot_id").write_text(BOOT + "\n")
        self.process(SUP_PID, 1, SUP_TICKS, self.supervisor_argv())
        self.process(ENTRY_PID, SUP_PID, ENTRY_TICKS, [self.target["python"], "-m", MODULE, "entry", "--state-dir",
                                                      str(self.state), "--workload", "fleet"])
        self.unit = {"ActiveState": "active", "SubState": "running", "MainPID": str(SUP_PID),
                     "ExecMainPID": str(SUP_PID), "InvocationID": INVOCATION, "ControlGroup": CGROUP,
                     "ExecMainStartTimestampMonotonic": str(EXEC_MAIN)}
        # The launcher's own lines, then a later plain line on the SAME stream. journald gives it the main pid
        # whichever process of the unit wrote it; it is no document and is ignored.
        self.journal = self.lines(launch_event()) + [main_line("UserWarning: fleet runner started")]
        self.show_rc = self.recheck_show_rc = self.journal_rc = 0
        self.journal_stderr = b""
        self.offset_usec = 0  # CLOCK_BOOTTIME - CLOCK_MONOTONIC: never suspended
        self.output_limit = self.api.MAX_COMMAND_BYTES
        self.runner = Runner(self.api, self)

    def supervisor_argv(self) -> list:
        return [str((self.releases / ACT_REV).resolve() / ".venv" / "bin" / "python"), "-m", MODULE, "supervise",
                "--state-dir", str(self.state)]

    def lines(self, event: dict, *, pid=SUP_PID, invocation=INVOCATION, boot=BOOT_HEX, mono=LAUNCH_MONO,
              real=LAUNCH_REAL, stream=STREAM, start=144755) -> list:
        """One launcher document exactly as journald stores it: one entry per emitted line."""
        out = io.StringIO()
        self.api.launcher_emit(event, out)
        return [{"MESSAGE": line, "_PID": str(pid), "_STREAM_ID": stream, "_BOOT_ID": boot,
                 "_SYSTEMD_INVOCATION_ID": invocation, "_SYSTEMD_UNIT": UNIT, "_TRANSPORT": "stdout",
                 "__CURSOR": "s=088ada45;i=" + format(start + index, "x") + ";b=" + boot,
                 "__MONOTONIC_TIMESTAMP": str(mono), "__REALTIME_TIMESTAMP": str(real), "__SEQNUM": str(start + index)}
                for index, line in enumerate(out.getvalue().splitlines())]

    # --- mutation helpers ------------------------------------------------------------------------
    @staticmethod
    def write(path: Path, document) -> None:
        path.write_text(json.dumps(document, sort_keys=True))

    @staticmethod
    def read(path: Path):
        return json.loads(path.read_text())

    def edit(self, name: str, **changes) -> None:
        path = self.state / name
        self.write(path, {**self.read(path), **changes})

    def row(self, store, bucket: str, key: str, **changes) -> None:
        with store.transaction() as tx:
            tx.put(bucket, key, {**tx.get(bucket, key), **changes})

    def supervisor_journal(self, lines: list) -> None:
        (self.state / "supervisor-journal.jsonl").write_text("".join(json.dumps(line) + "\n" for line in lines))

    def read_cmdline(self, pid: int) -> list:
        return [word.decode() for word in (self.proc / str(pid) / "cmdline").read_bytes().split(b"\0") if word]

    def process(self, pid: int, ppid: int, ticks: int, argv: list, cgroup: str = CGROUP) -> None:
        directory = self.proc / str(pid)
        directory.mkdir(exist_ok=True)
        (directory / "stat").write_text(stat_line(pid, ppid, ticks))
        (directory / "cmdline").write_bytes(b"\0".join(word.encode() for word in argv) + b"\0")
        (directory / "cgroup").write_text("0::" + cgroup + "\n")

    def submit(self, archive: dict) -> dict:
        """The operator's ordinary coordinator advance of the archived draft (outside the producer)."""
        draft = copy.deepcopy(archive["transition_draft"])
        self.labels.add(self.api.migration.transition_id(draft), "transition_id")
        return self.api.HostMigrations(self.coordinator).advance(draft)

    # --- the producer ----------------------------------------------------------------------------
    def request(self, **overrides) -> dict:
        return {"migration_id": MID, "expected_id": self.effective_id, "target_id": TARGET, "plan_id": PLAN,
                "actor": "claude-ph4", "root": str(self.root), "config_file": None, **overrides}

    def _ports(self, runner):
        stores = {"coordinator": ReadOnly(self.coordinator), "control": ReadOnly(self.control_store),
                  "delivery": ReadOnly(self.delivery)}
        return stores, self.api.Ports(coordinator=stores["coordinator"], control=stores["control"],
                                      delivery=lambda control: stores["delivery"], host=self.host(runner),
                                      clock=Clock())

    def ports(self):
        self.stores, ports = self._ports(self.runner)
        return ports

    def host(self, runner=None):
        api = self.api
        return api.HostReader(runner=runner or self.runner,
                              facts=api.HostFacts(proc=self.proc, cgroup_root=self.proc / "no-cgroup"), clk_tck=100,
                              boottime_offset=lambda: self.offset_usec, output_limit=self.output_limit)

    def snapshot(self) -> dict:
        """What the capture is about to read, as the fixture wrote it: the sha256 of the exact bytes of every
        file-backed source, and the digests of the delivery and canary-record views the producer hashes (taken
        through the same stores, before the run, so a mutation during the recheck cannot disturb them)."""
        api = self.api

        def sha(path):
            if path.is_symlink() or not path.is_file():
                return None
            return hashlib.sha256(path.read_bytes()).hexdigest()

        snap = {"activation_file": sha(self.control / "host-activation.json"),
                "descriptor": sha(self.state / "descriptor.json"), "startup": sha(self.state / "startup-receipt.json"),
                "canary_receipt.receipt": sha(self.state / RECEIPT_NAME),
                "canary_receipt.request": sha(self.state / REQUEST_NAME), "migration.config_sha256": sha(self.config)}
        try:
            with self.delivery.transaction() as tx:
                rows = (tx.get(api.BUCKET_TARGETS, TARGET), tx.get(api.BUCKET_PLANS, PLAN),
                        tx.get(api.BUCKET_INTENTS, PLAN), tx.get(api.BUCKET_DESCRIPTORS, TARGET),
                        tx.scan(api.BUCKET_INTENTS))
            snap["delivery"] = api.digest(api.policy.delivery_view(*rows, target_id=TARGET, plan_id=PLAN))
        except Exception:  # a row the case removed: the projection is absent too
            snap["delivery"] = None
        try:
            with self.control_store.transaction() as tx:
                snap["canary_record"] = api.digest(api.policy.record_view(tx.get("owner_actions", self.action_id)))
        except Exception:
            snap["canary_record"] = None
        return snap

    def observe(self, *, expect=None, post_transition=False, ports=None, **overrides) -> dict:
        ports = ports or self.ports()
        snap = self.snapshot()
        with self.guard.active():
            result = self.api.observe(self.request(**overrides), ports, expect=expect,
                                      post_transition=post_transition)
        self.snapshots[id(result)] = (result, snap)
        return result

    def cli_argv(self, *extra) -> list:
        return ["observe-limited-active", "--migration-id", MID, "--expected-id", self.effective_id,
                "--target-id", TARGET, "--plan-id", PLAN, "--actor", "claude-ph4", "--root", str(self.root),
                "--schema", "zeus_aibox_migration", "--control-schema", "zeus_aibox_control", *extra]

    def cli(self, *extra, ports=None, patches=None, env=None) -> dict:
        """`main(argv)` in this process, its stdout and stderr captured, under the write guard."""
        api, out, err = self.api, io.StringIO(), io.StringIO()
        attributes = dict(patches or {})
        if ports is not None:
            attributes["cli_ports"] = lambda args: ports
        with contextlib.ExitStack() as stack:
            if attributes:
                stack.enter_context(api.patched(**attributes))
            if env is not None:
                stack.enter_context(api.environ(env))
            stack.enter_context(contextlib.redirect_stdout(out))
            stack.enter_context(contextlib.redirect_stderr(err))
            stack.enter_context(self.guard.active())
            try:
                code = api.main(self.cli_argv(*extra))
            except SystemExit as exc:
                code = ["exit", exc.code]
        run = {"code": code, "stdout": out.getvalue(), "stderr": err.getvalue()}
        body = printed(run)
        if isinstance(body, dict) and "projections" in body:
            self.learn(body)
        return run

    # --- labels and normalization ---------------------------------------------------------------
    def scan(self) -> None:
        for path in sorted(self.tmp.rglob("*")):
            if path.is_symlink() or not path.is_file():
                continue
            try:
                data = path.read_bytes()
            except OSError:
                continue
            self.labels.add(hashlib.sha256(data).hexdigest(), "file." + str(path.relative_to(self.tmp)))

    def learn(self, result: dict) -> None:
        """The digests of one output that the fixture recomputes itself, by the side's own `digest`."""
        api = self.api
        self.scan()
        if "observation" in result:
            self.labels.add(api.policy.observation_digest(result["observation"]), "result")
            for name in api.policy.SOURCES:
                if result["projections"].get(name) is not None:
                    self.labels.add(api.digest(result["projections"][name]), "source." + name)
        row = self.coordinator.data.get((api.BUCKET, MID))
        if isinstance(row, dict):  # the history digests cover the transition's lineage, which names the run path
            history = list(row.get("history") or [])
            self.labels.add(api.digest(history), "history_sha256")
            self.labels.add(api.digest(history[:-1]), "previous_history_sha256")
        if isinstance(result.get("projections"), dict):
            for name, projection in result["projections"].items():
                self._raw(projection, name)
            last = (result["projections"].get("migration") or {}).get("last_transition")
            if isinstance(last, dict):
                self.labels.add(last.get("id"), "transition_id")

    def _raw(self, value, path: str) -> None:
        """A projection's `raw_sha256` is the digest of the object as read; for the process, delivery and canary
        record sources it embeds the run path and cannot be recomputed from the output, so it is labelled by the
        source it belongs to (first-seen order within the case), which keeps equality and change visible."""
        if isinstance(value, dict):
            for key, item in value.items():
                if key == "raw_sha256":
                    self.labels.add(item, "raw." + path)
                else:
                    self._raw(item, path + "." + key)

    def n(self, value):
        if isinstance(value, dict):
            return {self.n(key): self.n(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [self.n(item) for item in value]
        if isinstance(value, Path):
            return self.n(str(value))
        if isinstance(value, bytes):
            return self.n(value.decode("utf-8", errors="replace"))
        if isinstance(value, str):
            value = HEX64.sub(lambda match: self.labels.by_value.get(match.group(0), match.group(0)), value)
            for old, new in self.substitutions:
                value = value.replace(old, new)
            return value
        return value

    def _baseline(self) -> None:
        """The labelled baseline capture: its digests are named before any mutation, and its projections are what
        every case's `projections_changed` is compared with."""
        runner, guard = Runner(self.api, self), Guard(self)
        _, ports = self._ports(runner)
        with guard.active():
            result = self.api.observe(self.request(), ports)
        assert result["observation"]["ok"] is True, result["diagnostic"]
        self.learn(result)
        self.baseline_projections = self.n(result["projections"])
        observation = result["observation"]
        self.baseline_facts = self.n({"lineage": observation["lineage"], "activation": observation["activation"],
                                      "files": self.opened(guard), "draft": result["transition_draft"],
                                      "commands": [" ".join(call) for call in runner.calls]})

    # --- views ----------------------------------------------------------------------------------
    def recompute(self, result: dict) -> bool:
        api, observation = self.api, result["observation"]
        held = api.policy.observation_digest(observation) == api.digest(observation) == result["result_sha256"]
        for name in api.policy.SOURCES:
            entry, projection = observation["sources"][name], result["projections"][name]
            held = held and (projection is None if entry is None else entry["sha256"] == api.digest(projection))
        return held

    def summary(self, result: dict, *, code=None, detail=None, full: bool = False) -> dict:
        """One observation as a compact, normalized view, with M7's shape checks as recorded booleans."""
        api = self.api
        P = api.policy
        self.learn(result)
        observation = result["observation"]
        facts = self.lab.baseline_facts
        diagnostic = result["diagnostic"]
        view = {"ok": observation["ok"], "reason_code": observation["reason_code"],
                "diagnostic": None if diagnostic is None else diagnostic["reason_code"] + " / " + str(
                    diagnostic["detail"]),
                "as_expected": (observation["reason_code"] == code and (detail is None or (
                    diagnostic or {}).get("detail") == detail)) if code is not None else None,
                "checks_failed": ",".join(name for name, held in observation["checks"].items() if not held),
                "checks_all_present": set(observation["checks"]) == set(P.CHECKS),
                "sources_not_recorded": ",".join(name for name, entry in observation["sources"].items()
                                                 if entry is None),
                "observed": observation["observed_from"] + " .. " + observation["observed_to"],
                "manifest_sha256": observation["manifest_sha256"],
                "activation": "baseline" if self.n(observation["activation"]) == facts["activation"]
                else observation["activation"],
                "lineage": "baseline" if self.n(observation["lineage"]) == facts["lineage"]
                else observation["lineage"],
                "valid_observation": P.validate_observation(observation) == observation,
                "digest_recomputes": self.recompute(result),
                "projections_changed": {name: self.n(projection) for name, projection in result["projections"].items()
                                        if self.n(projection) != self.lab.baseline.get(name)},
                "keys": "output" if set(result) == {"observation", "result_sha256", "projections", "diagnostic",
                                                    "evidence", "transition_draft"} else sorted(result)}
        if "evidence" in result:
            view["evidence"] = [" ".join((name, str(item["check"]), str(item["subject"]), "exit=" + str(
                item["exit_code"]), "ok=" + str(item["ok"]), "bound=" + str(item["result_sha256"] == result[
                    "result_sha256"]))) for name, item in result["evidence"].items()]
            view["subjects_unknown"] = (lambda r: r["service_consumption"]["subject"] is None
                                        and r["canary_admission"]["subject"] is None)(
                P.observation_receipts(observation, "0" * 64, "e" * 64))
            draft = None if result["transition_draft"] is None else self.n(result["transition_draft"])
            view["draft"] = "baseline" if draft == facts["draft"] else draft
            if not observation["ok"]:
                view["failed_receipts_bound"] = all(
                    item["exit_code"] == 1 and item["ok"] is False and item["result_sha256"] == result["result_sha256"]
                    for item in result["evidence"].values())
        pair = self.snapshots.get(id(result))
        if pair is not None and pair[0] is result:
            view["raw_digests"] = self.raw_checks(result, pair[1])
        if "comparison" in result:
            view["comparison"] = result["comparison"]
        if full:
            view["full"] = result
        return self.n(view)

    @staticmethod
    def opened(guard) -> list:
        """The files a guarded run read: the relative path and how (`os.open` with its flags, or `open`)."""
        opens = {relative: "os.open" + (":nofollow" if flags[0] else "") + (":nonblock" if flags[1] else "")
                 for relative, flags in guard.os_opens.items()}
        for relative in guard.opens:
            opens.setdefault(relative, "open")
        return [relative + " " + how for relative, how in sorted(opens.items())]

    @staticmethod
    def raw_checks(result: dict, snap: dict) -> str:
        """For each source present, whether its `raw_sha256` equals the digest of what the fixture wrote: the exact
        file bytes (file-backed sources and the host configuration) or the view the producer hashes (delivery and
        canary record). The process and launch sources hash an object the producer builds (see `RAW_DIGEST_COVERS`)
        and are not recomputed."""
        projections, found = result["projections"], []
        for name in ("activation_file", "descriptor", "startup"):
            if projections.get(name) is not None:
                found.append((name, projections[name]["raw_sha256"] == snap[name]))
        receipts = projections.get("canary_receipt") or {}
        for name in ("receipt", "request"):
            if receipts.get(name) is not None:
                found.append(("canary_receipt." + name, receipts[name]["raw_sha256"] == snap["canary_receipt." + name]))
        if projections.get("migration") is not None:
            found.append(("migration.config_sha256", projections["migration"]["config_sha256"]
                          == snap["migration.config_sha256"]))
        for name in ("delivery", "canary_record"):
            if projections.get(name) is not None:
                found.append((name, projections[name]["raw_sha256"] == snap[name]))
        return ",".join(name + "=" + str(held) for name, held in sorted(found))

    def wrap(self, record: dict) -> dict:
        """The record of one case with what the host saw: the commands, the files read and the write attempts.
        Whatever equals the labelled baseline capture is recorded as `baseline`; a difference is listed."""
        self.scan()
        facts = self.lab.baseline_facts
        files = self.n(self.opened(self.guard))
        commands = self.n([" ".join(call) for call in self.runner.calls])
        environments = {tuple(sorted(env)) for env in self.runner.envs if env is not None}
        record = {**record, "commands": "baseline" if commands == facts["commands"] else commands,
                  "command_environment_keys": "minimal" if environments <= {tuple(sorted(self.api.COMMAND_ENV))}
                  else sorted(environments),
                  "files_read": "none" if not files else "baseline" if files == facts["files"] else {
                      "added": sorted(set(files) - set(facts["files"])),
                      "removed": sorted(set(facts["files"]) - set(files))},
                  "write_attempts": sorted(set(self.guard.attempts))}
        return self.n(record)

    def attempt(self, call):
        """The outcome of one call: what it returned, or the refusal and its reason fields."""
        try:
            return {"returned": self.n(call())}
        except Exception as exc:  # the refusal is the characterized result
            view = {"type": type(exc).__name__}
            for name in ("reason_code", "field"):
                if getattr(exc, name, None) is not None:
                    view[name] = getattr(exc, name)
            return {"raised": view}


def archived(result: dict) -> dict:
    """What the operator archived: the printed output, read back."""
    return json.loads(json.dumps(result, sort_keys=True, indent=2))


def tree(*roots) -> dict:
    snapshot = {}
    for root in roots:
        for path in sorted(Path(root).rglob("*")):
            snapshot[str(path)] = (os.readlink(path) if path.is_symlink() else
                                   path.read_bytes() if path.is_file() else "dir", path.lstat().st_mode)
    return snapshot


def diff(left, right, path="") -> list:
    """The paths at which two normalized values differ (a diagnostic of the self-check above)."""
    if isinstance(left, dict) and isinstance(right, dict):
        return [found for key in sorted(set(left) | set(right))
                for found in diff(left.get(key), right.get(key), path + "/" + str(key))]
    if isinstance(left, list) and isinstance(right, list) and len(left) == len(right):
        return [found for index, pair in enumerate(zip(left, right)) for found in diff(pair[0], pair[1], path + "/" + str(index))]
    return [] if left == right else [[path, left, right]]


def printed(run: dict):
    try:
        return json.loads(run["stdout"])
    except ValueError:
        return None


# ---- the case tables (M7 module tables, LABELLED) --------------------------------------------------------------------
def tables(api) -> SimpleNamespace:
    P, M = api.policy, api.migration
    t = SimpleNamespace()

    def _evidence(w, **changes):
        document = w.read(w.state / RECEIPT_NAME)
        w.edit(RECEIPT_NAME, evidence={**document["evidence"], **changes})

    def _move_receipt_to_other_plan(w):
        (w.state / RECEIPT_NAME).rename(w.state / ("owner-canary-receipt." + OTHER_PLAN + ".json"))
        (w.state / REQUEST_NAME).unlink()

    t.canary = {
        "other_plan_receipt_only": (_move_receipt_to_other_plan, "canary_owner_receipt_missing"),
        "receipt_names_other_plan": (lambda w: _evidence(w, plan_id=OTHER_PLAN), "canary_evidence"),
        "other_target_record": (lambda w: w.row(w.control_store, "owner_actions", w.action_id,
                                                binding={**w.record["binding"], "target_id": "other-target"}),
                                "canary_record_binding"),
        "other_instance": (lambda w: w.edit(RECEIPT_NAME, instance_id=PREVIOUS), "canary_owner_receipt_stale"),
        "other_descriptor": (lambda w: w.edit(RECEIPT_NAME, descriptor_sha256="0" * 64), "canary_owner_receipt_stale"),
        "null_instance": (lambda w: w.edit(RECEIPT_NAME, instance_id=None), "canary_instance_missing"),
        "false_passed": (lambda w: w.edit(RECEIPT_NAME, passed=False), "canary_owner_receipt_failed"),
        "string_passed": (lambda w: w.edit(RECEIPT_NAME, passed="true"), "canary_not_passed"),
        "pending_request_only": (lambda w: (w.state / RECEIPT_NAME).unlink(), "canary_owner_receipt_pending"),
        "missing_receipt": (lambda w: [(w.state / name).unlink() for name in (RECEIPT_NAME, REQUEST_NAME)],
                            "canary_owner_receipt_missing"),
        "record_missing": (lambda w: _evidence(w, action_id="0" * 64), "canary_record_missing"),
        "record_not_completed": (lambda w: w.row(w.control_store, "owner_actions", w.action_id, state="requested"),
                                 "canary_record_state"),
        "record_other_plan_digest": (lambda w: w.row(w.control_store, "owner_actions", w.action_id,
                                                     binding={**w.record["binding"], "plan_sha256": "0" * 64}),
                                     "canary_record_binding"),
        "record_rejected": (lambda w: w.row(w.control_store, "owner_actions", w.action_id,
                                            outcome={**w.record["outcome"], "state": "rejected"}),
                            "canary_record_outcome"),
        "receipt_evidence_not_the_record": (lambda w: _evidence(w, execution_ref="sha256:" + "0" * 64),
                                            "canary_record_evidence"),
        "delivery_consumed_other_evidence": (lambda w: w.row(w.delivery, api.BUCKET_INTENTS, PLAN, canary={
            "passed": True, "evidence": {"action_id": "1" * 64}, "reason_code": None,
            "check_id": "fleet_worker_operation"}), "delivery_canary"),
        "receipt_before_startup": (lambda w: w.edit(RECEIPT_NAME, recorded_at="2026-09-27T21:00:00+00:00"),
                                   "canary_before_startup"),
        "request_other_plan_digest": (lambda w: w.edit(REQUEST_NAME, plan_sha256="0" * 64), "canary_request"),
        "receipt_extra_key": (lambda w: w.edit(RECEIPT_NAME, note="x"), "canary_receipt_shape"),
    }

    def _seal_tampered(w):
        path = w.managed / "runtimes" / PAYLOAD / "src" / "codex_harness" / "__init__.py"
        path.chmod(0o644)
        path.write_bytes(b"# edited after sealing\n")

    t.consumption = {
        "stale_prior_instance": (lambda w: w.edit("startup-receipt.json", instance_id=PREVIOUS),
                                 "receipt_stale_instance"),
        "foreign_runtime_root": (lambda w: w.edit("startup-receipt.json", runtime_root=str(w.releases / ACT_REV),
                                                  module_root=str(w.releases / ACT_REV / "src" / "codex_harness")),
                                 "receipt_runtime_root_mismatch"),
        "foreign_module_root": (lambda w: w.edit("startup-receipt.json", module_root=str(w.root / "repo" / "src")),
                                "receipt_module_root_foreign"),
        "revision_mismatch": (lambda w: w.edit("startup-receipt.json", revision=ACT_REV),
                              "receipt_revision_mismatch"),
        "image_mismatch": (lambda w: w.edit("startup-receipt.json", worker_image="sha256:" + "8" * 64),
                           "receipt_worker_image_mismatch"),
        "profile_mismatch": (lambda w: w.edit("startup-receipt.json", profile_digest="0" * 64),
                             "receipt_profile_digest_mismatch"),
        "digest_mismatch": (lambda w: w.edit("startup-receipt.json", descriptor_sha256="0" * 64),
                            "receipt_descriptor_sha256_mismatch"),
        "descriptor_identity_drift": (lambda w: w.edit("descriptor.json", worker_image="sha256:" + "8" * 64),
                                      "descriptor_identity"),
        "descriptor_relabelled_to_launcher_revision": (lambda w: w.edit("descriptor.json", revision=ACT_REV),
                                                       "runtime_path_foreign"),
        "sealed_runtime_tampered": (_seal_tampered, "runtime_content_mismatch"),
        "environment_unqualified": (lambda w: w.row(w.delivery, api.BUCKET_TARGETS, TARGET,
                                                    environment_lock="0" * 64), "environment_unqualified"),
        "delivery_not_active": (lambda w: w.row(w.delivery, api.BUCKET_INTENTS, PLAN, stage="awaiting_consumption"),
                                "delivery_not_active"),
        "delivery_bound_other_instance": (lambda w: w.row(w.delivery, api.BUCKET_DESCRIPTORS, TARGET,
                                                          instance_id=PREVIOUS), "instance_binding"),
        "delivery_rolled_back": (lambda w: w.row(w.delivery, api.BUCKET_DESCRIPTORS, TARGET, rolled_back=True),
                                 "instance_binding"),
        "delivery_in_flight": (lambda w: w.row(w.delivery, api.BUCKET_INTENTS, OTHER_PLAN, stage="switching"),
                               "delivery_in_flight"),
        "plan_digest_mismatch": (lambda w: w.row(w.delivery, api.BUCKET_PLANS, PLAN, plan_sha256="0" * 64),
                                 "plan_binding"),
        "target_not_the_managed_unit": (lambda w: w.row(w.delivery, api.BUCKET_TARGETS, TARGET, kind="managed_fleet"),
                                        "target_binding"),
    }

    def _bootstrap_receipt(w):
        """The retired bootstrap Fleet's receipt: the release checkout, `revision=5aa`, its own pid."""
        w.edit("startup-receipt.json", runtime_root=str(w.releases / ACT_REV),
               module_root=str(w.releases / ACT_REV / "src" / "codex_harness"), revision=ACT_REV,
               instance_id="d89f34e0" + "0" * 24, pid=4242)

    def _entry_pid_reused(w):
        # Same pid, same argv and parent, but started long after the receipt it would claim.
        w.process(ENTRY_PID, SUP_PID, ENTRY_TICKS + 100_000, w.read_cmdline(ENTRY_PID))

    def _launcher_argv(*extra):
        return lambda w: w.process(SUP_PID, 1, SUP_TICKS, ["/usr/bin/python3", api.launcher_path, "launch",
                                                           "--role", "managed-fleet", *extra])

    def _two_launches(w):
        w.journal = w.lines(launch_event()) + w.lines(launch_event(), start=144800)

    t.process = {
        "retired_bootstrap_receipt": (_bootstrap_receipt, P.CONSUMPTION, "receipt_runtime_root_mismatch"),
        "stopped_entry_pid": (lambda w: shutil.rmtree(w.proc / str(ENTRY_PID)), P.PROCESS, "entry_absent"),
        "reused_entry_pid": (_entry_pid_reused, P.PROCESS, "entry_after_startup"),
        "entry_not_supervisor_child": (lambda w: w.process(ENTRY_PID, 1, ENTRY_TICKS, w.read_cmdline(ENTRY_PID)),
                                       P.PROCESS, "entry_parent"),
        "entry_other_cgroup": (lambda w: w.process(ENTRY_PID, SUP_PID, ENTRY_TICKS, w.read_cmdline(ENTRY_PID),
                                                   "/user.slice/session.scope"), P.PROCESS, "entry_cgroup"),
        "entry_other_workload": (lambda w: w.process(ENTRY_PID, SUP_PID, ENTRY_TICKS,
                                                     w.read_cmdline(ENTRY_PID)[:-1] + ["fixture"]),
                                 P.PROCESS, "entry_argv"),
        "supervisor_gone": (lambda w: shutil.rmtree(w.proc / str(SUP_PID)), P.PROCESS, "supervisor_absent"),
        "supervisor_pid_reused": (lambda w: w.process(SUP_PID, 1, SUP_TICKS + 1_000, w.supervisor_argv()),
                                  P.PROCESS, "supervisor_start"),
        "supervisor_other_cgroup": (lambda w: w.process(SUP_PID, 1, SUP_TICKS, w.supervisor_argv(), "/other.scope"),
                                    P.PROCESS, "supervisor_cgroup"),
        "supervisor_other_release": (lambda w: w.process(SUP_PID, 1, SUP_TICKS, [
            str(w.releases / INTENT_REV / ".venv" / "bin" / "python"), *w.supervisor_argv()[1:]]),
            P.PROCESS, "supervisor_argv"),
        "launcher_not_execd": (_launcher_argv(), P.PROCESS, "supervisor_argv"),
        "unit_not_running": (lambda w: w.unit.update(SubState="stop-sigterm"), P.PROCESS, "unit_not_running"),
        "supervisor_never_launched_this_invocation": (lambda w: w.supervisor_journal([]), P.PROCESS,
                                                      "supervisor_launch_missing"),
        "supervisor_launched_other_descriptor": (lambda w: w.supervisor_journal([{
            "event": "launch", "descriptor_sha256": PREDECESSOR, "workload": "fleet", "invocation_id": INVOCATION}]),
            P.PROCESS, "supervisor_descriptor"),
        "supervisor_refused_this_invocation": (lambda w: w.supervisor_journal([
            {"event": "refused", "reason_code": "descriptor_changed", "invocation_id": INVOCATION},
            {"event": "launch", "descriptor_sha256": w.descriptor_sha256, "workload": "fleet",
             "invocation_id": INVOCATION}]), P.PROCESS, "supervisor_refused"),
        "wrong_boot": (lambda w: setattr(w, "journal", w.lines(launch_event(), boot="0" * 32)),
                       P.LAUNCH, "launch_boot"),
        "wrong_invocation": (lambda w: setattr(w, "journal", w.lines(launch_event(), invocation=OLD_INVOCATION)),
                             P.LAUNCH, "launch_invocation"),
        "no_launch_in_invocation": (lambda w: setattr(w, "journal", w.lines({"event": "supervisor_started"})),
                                    P.LAUNCH, "launch_missing"),
        "dry_run_launch_only": (_launcher_argv("--dry-run"), P.PROCESS, "supervisor_argv"),
        # A descendant's document on the inherited stream carries the main pid too: a second event is ambiguous.
        "child_document_on_main_stream": (lambda w: w.journal.append(main_line(json.dumps(
            {"event": "launch", "job": "fleet-job"}), index=1)), P.LAUNCH, "launch_ambiguous"),
        "wrong_launch_revision": (lambda w: setattr(w, "journal", w.lines(launch_event(revision=INTENT_REV))),
                                  P.LAUNCH, "launch_revision"),
        "wrong_launch_migration": (lambda w: setattr(w, "journal", w.lines(launch_event(migration_id="other"))),
                                   P.LAUNCH, "launch_migration"),
        "wrong_launch_role": (lambda w: setattr(w, "journal", w.lines(launch_event(role="fleet"))),
                              P.LAUNCH, "launch_role"),
        "launch_refused": (lambda w: setattr(w, "journal", w.lines({"event": "launch_refused",
                                                                    "role": "managed-fleet", "reason": "host_fenced"})),
                           P.LAUNCH, "launch_refused"),
        "two_launches": (_two_launches, P.LAUNCH, "launch_ambiguous"),
        "launch_before_invocation": (lambda w: setattr(w, "journal", w.lines(launch_event(), mono=EXEC_MAIN - 1)),
                                     P.LAUNCH, "launch_before_invocation"),
    }

    def _activation(w, **changes):
        w.write(w.control / "host-activation.json", {**w.activation_document, **changes})

    def _current(w, revision):
        (w.releases / "current").unlink()
        os.symlink(revision, w.releases / "current")

    t.activation, t.current = _activation, _current
    t.document = {
        "state_limited_active": (lambda w: _activation(w, state="limited_active"), "activation_file"),
        "superseded_intent": (lambda w: _activation(w, intent_id="0" * 64), "activation_file"),
        "extra_key": (lambda w: _activation(w, note="relabelled"), "activation_file"),
        "revision_only_equal": (lambda w: w.write(w.control / "host-activation.json", {
            "schema": M.ACTIVATION_SCHEMA, "release_revision": ACT_REV, "state": "restored_paused"}),
            "activation_file"),
        "current_other_revision": (lambda w: _current(w, INTENT_REV), "current"),
        "current_missing": (lambda w: (w.releases / "current").unlink(), "current"),
        "host_fenced": (lambda w: w.write(w.control / "host-fence.json", {"migration_id": MID}), "host_fenced"),
        "coordinator_not_restored_paused": (lambda w: w.row(w.coordinator, api.BUCKET, MID, state="limited_active"),
                                            "migration_state"),
    }
    t.unreadable = {
        "activation_file_missing": (lambda w: (w.control / "host-activation.json").unlink(), "activation_file"),
        "activation_file_not_json": (lambda w: (w.control / "host-activation.json").write_text("{"),
                                     "activation_file"),
        "config_missing": (lambda w: w.config.unlink(), "config"),
        "unit_unreadable": (lambda w: setattr(w, "show_rc", 1), "unit"),
        "journal_unreadable": (lambda w: setattr(w, "journal_rc", 1), "journal"),
        # An empty answer for a unit with a current invocation is what an unprivileged reader sees, not
        # `launch_missing`; so is any stderr, even beside entries, and an answer over the byte cap.
        "journal_empty": (lambda w: setattr(w, "journal", []), "journal"),
        "journal_permission_hint": (lambda w: (setattr(w, "journal", []), setattr(
            w, "journal_stderr", b"No journal files were opened due to insufficient permissions.\n")), "journal"),
        "journal_stderr_beside_entries": (lambda w: setattr(w, "journal_stderr", b"Hint: some entries hidden\n"),
                                          "journal"),
        "journal_over_cap": (lambda w: setattr(w, "output_limit", 1024), "journal"),
        "main_pid_document_unparseable": (lambda w: w.journal.append(main_line("{not json}", index=1)),
                                          "journal_entry"),
        "main_pid_document_unterminated": (lambda w: setattr(w, "journal", w.lines(launch_event())[:-1]),
                                           "journal_entry"),
        "boot_unreadable": (lambda w: (w.proc / "sys" / "kernel" / "random" / "boot_id").unlink(), "boot"),
        "supervisor_stat_garbage": (lambda w: (w.proc / str(SUP_PID) / "stat").write_text("garbage"), "supervisor"),
        "supervisor_journal_missing": (lambda w: (w.state / "supervisor-journal.jsonl").unlink(),
                                       "supervisor_journal"),
        "descriptor_missing": (lambda w: (w.state / "descriptor.json").unlink(), "descriptor"),
        "startup_not_json": (lambda w: (w.state / "startup-receipt.json").write_text("{"), "startup"),
        "delivery_row_missing": (lambda w: w.delivery.data.pop((api.BUCKET_DESCRIPTORS, TARGET)),
                                 "delivery_descriptor"),
    }

    def _successor_recorded(w):
        with w.coordinator.transaction() as tx:
            row = tx.get(api.BUCKET, MID)
            row["history"].append({"event": "activation_successor", "successor_id": "0" * 64})
            tx.put(api.BUCKET, MID, row)

    def _restarted_entry(w):
        w.process(ENTRY_PID, SUP_PID, ENTRY_TICKS + 5, w.read_cmdline(ENTRY_PID))

    t.successor_recorded, t.restarted_entry = _successor_recorded, _restarted_entry
    t.change = {
        "unit_restarted": (lambda w: w.unit.update(InvocationID="f" * 32), "unit"),
        "startup_rewritten": (lambda w: w.edit("startup-receipt.json", instance_id="f" * 32), "startup"),
        "descriptor_switched": (lambda w: w.edit("descriptor.json", predecessor="0" * 64), "descriptor"),
        "coordinator_moved": (_successor_recorded, "migration"),
        "activation_file_rewritten": (lambda w: _activation(w, state="limited_active"), "activation_file"),
        "current_switched": (lambda w: _current(w, INTENT_REV), "activation_file"),
        "entry_restarted": (_restarted_entry, "entry"),
        "delivery_row_updated": (lambda w: w.row(w.delivery, api.BUCKET_DESCRIPTORS, TARGET, updated_at="later"),
                                 "delivery"),
        "canary_record_updated": (lambda w: w.row(w.control_store, "owner_actions", w.action_id, version=4),
                                  "canary_record"),
        "canary_receipt_rewritten": (lambda w: w.edit(RECEIPT_NAME, recorded_at=RECORDED_AT.replace("43.4", "44.4")),
                                     "canary_receipt"),
        "config_changed": (lambda w: w.config.write_text("ZEUS_AIBOX_ROOT=elsewhere\n"), "config"),
        "supervisor_relaunched": (lambda w: w.supervisor_journal([{
            "event": "launch", "descriptor_sha256": w.descriptor_sha256, "workload": "fleet",
            "invocation_id": INVOCATION},
            {"event": "launch", "descriptor_sha256": w.descriptor_sha256, "workload": "fleet",
             "invocation_id": INVOCATION}]), "supervisor_journal"),
    }
    t.vanish = {
        "migration_row_gone": (lambda w: w.coordinator.data.pop((api.BUCKET, MID)), "migration"),
        "config_gone": (lambda w: w.config.unlink(), "config"),
        "activation_file_gone": (lambda w: (w.control / "host-activation.json").unlink(), "activation_file"),
        "unit_stopped": (lambda w: w.unit.update(ActiveState="inactive", SubState="dead", MainPID="0",
                                                 ExecMainPID="0", InvocationID=""), "unit"),
        "supervisor_gone": (lambda w: shutil.rmtree(w.proc / str(SUP_PID)), "supervisor"),
        "supervisor_journal_gone": (lambda w: (w.state / "supervisor-journal.jsonl").unlink(), "supervisor_journal"),
        "delivery_row_gone": (lambda w: w.delivery.data.pop((api.BUCKET_DESCRIPTORS, TARGET)), "delivery"),
        "descriptor_gone": (lambda w: (w.state / "descriptor.json").unlink(), "descriptor"),
        "startup_gone": (lambda w: (w.state / "startup-receipt.json").unlink(), "startup"),
        "entry_gone": (lambda w: shutil.rmtree(w.proc / str(ENTRY_PID)), "entry"),
        "canary_receipt_gone": (lambda w: (w.state / RECEIPT_NAME).unlink(), "canary_receipt"),
        "canary_record_gone": (lambda w: w.control_store.data.pop(("owner_actions", w.action_id)), "canary_record"),
    }

    def _history(w, **changes):
        with w.coordinator.transaction() as tx:
            row = tx.get(api.BUCKET, MID)
            row["history"][-1] = {**row["history"][-1], **changes}
            tx.put(api.BUCKET, MID, row)

    def _later_entry(w):
        with w.coordinator.transaction() as tx:
            row = tx.get(api.BUCKET, MID)
            row["history"].append({"event": "note"})
            tx.put(api.BUCKET, MID, row)

    t.history, t.later_entry = _history, _later_entry
    t.pre_submit = {
        "entry_restarted": (_restarted_entry, P.CHANGED, "entry"),
        "delivery_row_updated": (lambda w: w.row(w.delivery, api.BUCKET_DESCRIPTORS, TARGET, updated_at="later"),
                                 P.CHANGED, "delivery"),
        "coordinator_moved": (_successor_recorded, P.CHANGED, "migration"),
        "configuration_changed": (lambda w: w.config.write_text("ZEUS_AIBOX_ROOT=elsewhere\n"), P.CHANGED,
                                  "migration"),
        "canary_receipt_rewritten": (lambda w: w.edit(RECEIPT_NAME, recorded_at=RECORDED_AT.replace("43.4", "44.4")),
                                     P.CHANGED, "canary_receipt"),
        "canary_record_updated": (lambda w: w.row(w.control_store, "owner_actions", w.action_id, version=4),
                                  P.CHANGED, "canary_record"),
        "unit_restarted": (lambda w: w.unit.update(InvocationID="f" * 32), P.LAUNCH, "launch_invocation"),
        "already_advanced": (lambda w: w.submit(w.archive), P.DOCUMENT, "migration_state"),
    }
    t.post_check = {
        "not_yet_recorded": (False, lambda w: None, P.DOCUMENT, "migration_state"),
        "recorded_lineage_differs": (True, lambda w: _history(w, lineage={**w.archive["observation"]["lineage"],
                                                                          "instance_id": "f" * 32}),
                                     P.CHANGED, "transition_lineage"),
        "another_transition_recorded": (True, lambda w: _history(w, id="0" * 64), P.CHANGED, "transition_id"),
        "a_later_history_entry": (True, _later_entry, P.DOCUMENT, "transition_last"),
        "entry_restarted": (True, _restarted_entry, P.CHANGED, "entry"),
        "canary_record_updated": (True, lambda w: w.row(w.control_store, "owner_actions", w.action_id, version=4),
                                  P.CHANGED, "canary_record"),
        "configuration_changed": (True, lambda w: w.config.write_text("ZEUS_AIBOX_ROOT=elsewhere\n"),
                                  P.CHANGED, "migration"),
        "launcher_file_rewritten": (True, lambda w: _activation(w, state="limited_active"), P.DOCUMENT,
                                    "activation_file"),
    }

    def _failed_archive(w):
        w.edit(RECEIPT_NAME, instance_id=None)
        result = archived(w.observe())
        w.edit(RECEIPT_NAME, instance_id=INSTANCE)
        return result

    t.archive = {
        "failed_observation": (_failed_archive, {}, "observation"),
        "tampered_observation": (lambda w: {**w.good, "observation": {**w.good["observation"],
                                                                      "observed_to": "2026-09-28T11:31:00+00:00"}},
                                 {}, "result_sha256"),
        "tampered_projection": (lambda w: {**w.good, "projections": {**w.good["projections"], "startup": {}}}, {},
                                "projections"),
        "receipt_swapped": (lambda w: {**w.good, "evidence": {**w.good["evidence"], "host_activation": {
            **w.good["evidence"]["host_activation"], "subject": "0" * 64}}}, {}, "evidence"),
        "draft_without_lineage": (lambda w: {**w.good, "transition_draft": {
            key: value for key, value in w.good["transition_draft"].items() if key != "lineage"}}, {},
            "transition_draft"),
        "comparison_output": (lambda w: archived(w.observe(expect=w.good)), {}, "archive"),
        "uncanonical_content": (lambda w: {**w.good, "projections": {**w.good["projections"], "startup": "\ud800"}},
                                {}, "archive"),
        "other_plan": (lambda w: w.good, {"plan_id": OTHER_PLAN}, "lineage"),
        "other_activation": (lambda w: w.good, {"expected_id": "0" * 64}, "expected_id"),
    }

    def _supervisor_line(w, **changes):
        w.supervisor_journal([{"event": "launch", "descriptor_sha256": w.descriptor_sha256, "workload": "fleet",
                               "invocation_id": INVOCATION, "at": "2026-09-27T21:24:47.671458+00:00", **changes}])

    def _history_entry(w, entry: dict):
        with w.coordinator.transaction() as tx:
            row = tx.get(api.BUCKET, MID)
            row["history"].append(entry)
            tx.put(api.BUCKET, MID, row)

    def _outcome_evidence(w, **changes):
        outcome = w.record["outcome"]
        w.row(w.control_store, "owner_actions", w.action_id,
              outcome={**outcome, "evidence": {**outcome["evidence"], **changes}})

    def _intent_canary_evidence(w, **changes):
        with w.delivery.transaction() as tx:
            canary = tx.get(api.BUCKET_INTENTS, PLAN)["canary"]
        w.row(w.delivery, api.BUCKET_INTENTS, PLAN, canary={**canary, "evidence": {**canary["evidence"], **changes}})

    def _open_plan_named(w, plan_id: str):
        with w.delivery.transaction() as tx:
            tx.put(api.BUCKET_INTENTS, "open-" + MARKER, {"id": "open", "plan_id": plan_id, "target_id": TARGET,
                                                          "stage": "switching"})

    t.supervisor_line, t.history_entry, t.outcome_evidence = _supervisor_line, _history_entry, _outcome_evidence
    # (mutation, expected refusal code or None for a success, fixed detail).
    t.leak = {
        "activation_excluded_key": (lambda w: _activation(w, password=SECRET), P.DOCUMENT, "activation_file"),
        "activation_marker_named_key": (lambda w: _activation(w, **{MARKER: 1}), P.DOCUMENT, "activation_file"),
        "activation_wrong_type": (lambda w: _activation(w, release_revision=SECRET), P.DOCUMENT, "activation_file"),
        "activation_not_an_object": (lambda w: w.write(w.control / "host-activation.json", SECRET), P.DOCUMENT,
                                     "activation_file"),
        "launch_event_excluded_key": (lambda w: setattr(w, "journal", w.lines(launch_event(password=SECRET))),
                                      P.LAUNCH, "launch_fields"),
        "launch_event_wrong_type": (lambda w: setattr(w, "journal", w.lines(launch_event(revision=SECRET))),
                                    P.LAUNCH, "launch_revision"),
        "unit_free_text_state": (lambda w: w.unit.update(SubState=SECRET), P.PROCESS, "unit_not_running"),
        "supervisor_line_excluded_key": (lambda w: _supervisor_line(w, password=SECRET), None, None),
        "supervisor_line_wrong_type": (lambda w: w.supervisor_journal([
            {"event": "refused", "reason_code": SECRET, "invocation_id": INVOCATION},
            {"event": "launch", "descriptor_sha256": w.descriptor_sha256, "workload": "fleet",
             "invocation_id": INVOCATION}]), P.PROCESS, "supervisor_refused"),
        "entry_free_text_cgroup": (lambda w: w.process(ENTRY_PID, SUP_PID, ENTRY_TICKS, w.read_cmdline(ENTRY_PID),
                                                       "/user.slice/" + SECRET), P.PROCESS, "entry_cgroup"),
        "descriptor_excluded_key": (lambda w: w.edit("descriptor.json", password=SECRET), P.CONSUMPTION,
                                    "descriptor_fields"),
        "descriptor_wrong_type": (lambda w: w.edit("descriptor.json", worker_image=SECRET), P.CONSUMPTION,
                                  "descriptor_invalid"),
        "descriptor_path_marker": (lambda w: w.edit("descriptor.json", root=MARKER_PATH), P.CONSUMPTION,
                                   "runtime_path_foreign"),
        "startup_excluded_key": (lambda w: w.edit("startup-receipt.json", password=SECRET), P.CONSUMPTION,
                                 "receipt_fields"),
        "startup_marker_named_key": (lambda w: w.edit("startup-receipt.json", **{MARKER: 1}), P.CONSUMPTION,
                                     "receipt_fields"),
        "startup_wrong_type": (lambda w: w.edit("startup-receipt.json", pid=SECRET), P.CONSUMPTION,
                               "receipt_invalid"),
        "startup_path_marker": (lambda w: w.edit("startup-receipt.json", runtime_root=MARKER_PATH,
                                                 module_root=MARKER_PATH + "/src"), P.CONSUMPTION,
                                "receipt_runtime_root_mismatch"),
        "startup_not_an_object": (lambda w: w.write(w.state / "startup-receipt.json", SECRET), P.CONSUMPTION,
                                  "receipt_schema"),
        "canary_receipt_excluded_key": (lambda w: w.edit(RECEIPT_NAME, password=SECRET), P.CANARY,
                                        "canary_receipt_shape"),
        "canary_receipt_wrong_type": (lambda w: w.edit(RECEIPT_NAME, recorded_at=SECRET), P.CANARY,
                                      "canary_before_startup"),
        "canary_evidence_excluded_key": (lambda w: _evidence(w, password=SECRET), P.CANARY,
                                         "canary_record_evidence"),
        "canary_evidence_wrong_type": (lambda w: _evidence(w, execution_ref=SECRET), P.CANARY,
                                       "canary_record_evidence"),
        "canary_request_excluded_key": (lambda w: w.edit(REQUEST_NAME, password=SECRET), P.CANARY,
                                        "canary_request"),
        "canary_request_wrong_type": (lambda w: w.edit(REQUEST_NAME, requested_at=SECRET), None, None),
        "canary_request_wrong_type_bound_field": (lambda w: w.edit(REQUEST_NAME, plan_sha256=SECRET), P.CANARY,
                                                  "canary_request"),
        "record_excluded_key": (lambda w: w.row(w.control_store, "owner_actions", w.action_id, password=SECRET),
                                None, None),
        "record_wrong_type": (lambda w: w.row(w.control_store, "owner_actions", w.action_id, updated_at=SECRET),
                              None, None),
        "record_outcome_excluded_key": (lambda w: _outcome_evidence(w, password=SECRET), P.CANARY,
                                        "canary_record_evidence"),
        "record_outcome_wrong_type": (lambda w: w.row(w.control_store, "owner_actions", w.action_id, outcome={
            **w.record["outcome"], "reason_code": SECRET}), P.CANARY, "canary_record_evidence"),
        "history_excluded_key": (lambda w: _history_entry(w, {"event": "note", "password": SECRET}), None, None),
        "history_wrong_type": (lambda w: _history_entry(w, {"event": SECRET, "at": SECRET, "lineage": SECRET}),
                               None, None),
        "migration_wrong_type_state": (lambda w: w.row(w.coordinator, api.BUCKET, MID, state=SECRET), P.DOCUMENT,
                                       "migration_state"),
        "delivery_canary_evidence_excluded_key": (lambda w: _intent_canary_evidence(w, password=SECRET),
                                                  P.CANARY, "delivery_canary"),
        "delivery_plan_excluded_key": (lambda w: w.row(w.delivery, api.BUCKET_PLANS, PLAN,
                                                       plan={**w.plan, "password": SECRET}),
                                       P.CONSUMPTION, "plan_invalid"),
        "delivery_target_free_text_path": (lambda w: w.row(w.delivery, api.BUCKET_TARGETS, TARGET,
                                                           python="/opt/" + SECRET), P.PROCESS, "entry_argv"),
        "delivery_descriptor_row_wrong_type": (lambda w: w.row(w.delivery, api.BUCKET_DESCRIPTORS, TARGET,
                                                               observed_revision=SECRET), None, None),
        "delivery_open_plan_free_text": (lambda w: _open_plan_named(w, SECRET), P.CONSUMPTION,
                                         "delivery_in_flight"),
    }
    t.recheck_raw = {
        "startup_excluded_key": (lambda w: w.edit("startup-receipt.json", password=SECRET), "startup"),
        "descriptor_excluded_key": (lambda w: w.edit("descriptor.json", password=SECRET), "descriptor"),
        "activation_excluded_key": (lambda w: _activation(w, password=SECRET), "activation_file"),
        "canary_request_excluded_key": (lambda w: w.edit(REQUEST_NAME, password=SECRET), "canary_receipt"),
        "supervisor_line_excluded_key": (lambda w: _supervisor_line(w, password=SECRET), "supervisor_journal"),
        "record_outcome_excluded_key": (lambda w: _outcome_evidence(w, password=SECRET), "canary_record"),
    }
    t.pre_submit_raw = {
        "supervisor_line_excluded_key": (lambda w: _supervisor_line(w, password=SECRET), "supervisor"),
        "canary_request_untyped_value": (lambda w: w.edit(REQUEST_NAME, requested_at=SECRET), "canary_receipt"),
        "record_untyped_value": (lambda w: w.row(w.control_store, "owner_actions", w.action_id, updated_at=SECRET),
                                 "canary_record"),
        "descriptor_row_untyped_value": (lambda w: w.row(w.delivery, api.BUCKET_DESCRIPTORS, TARGET,
                                                         observed_revision=SECRET), "delivery"),
        "history_excluded_key": (lambda w: _history_entry(w, {"event": "note", "password": SECRET}), "migration"),
    }
    return t


# ---- groups -------------------------------------------------------------------------------------------------------
def put(lab: Lab, out: dict, group: str, test: str, key: str, record: dict) -> None:
    out[key] = record
    lab.mirror(test, group + "." + key)


def refusal(lab, w, result, code, detail, *, full=False) -> dict:
    return w.wrap(w.summary(result, code=code, detail=detail, full=full))


def group_capture(lab: Lab) -> dict:
    api, out = lab.api, {}
    P, M = api.policy, api.migration

    w = lab.world()
    result = w.observe()
    record = w.summary(result, full=True)
    observation, evidence, draft = result["observation"], result["evidence"], result["transition_draft"]
    record["relations"] = {
        "lineage_descriptor_is_payload_not_launcher": observation["lineage"]["descriptor"]["revision"] == PAYLOAD != ACT_REV,
        "activation_document_sha256": observation["activation"]["document_sha256"] == api.digest(w.activation_document),
        "draft_valid": M.validate_transition(draft) == draft,
        "draft_fields": [draft["from"], draft["to"], draft["host"], draft["actor"], draft["at"] == observation["observed_to"]],
        "draft_identity_config_is_file_digest": draft["identity"]["config_sha256"] == hashlib.sha256(
            w.config.read_bytes()).hexdigest(),
        "config_committed_in_migration_source": result["projections"]["migration"]["config_sha256"]
        == draft["identity"]["config_sha256"] and observation["sources"]["migration"]["sha256"] == api.digest(
            result["projections"]["migration"]),
        "draft_lineage_and_manifest": draft["lineage"] == observation["lineage"] and draft["manifest_sha256"] == w.manifest_sha256,
        "draft_evidence_is_the_receipts": draft["evidence"] == {gate: [item] for gate, item in evidence.items()},
        "subjects_match_the_domain": [M.managed_consumption_subject(observation["lineage"]) == evidence[
            "service_consumption"]["subject"], M.managed_canary_subject(observation["lineage"]) == evidence[
            "canary_admission"]["subject"]],
        "observation_fields_in_order": list(observation) == list(P.OBSERVATION_FIELDS),
        "all_checks_held": all(observation["checks"].values()),
        "only_the_two_read_commands_ran": [call[:2] for call in w.runner.calls] == [
            [api.SYSTEMCTL, "show"], [api.JOURNALCTL, "--no-pager"], [api.SYSTEMCTL, "show"]]}
    put(lab, out, "capture", "test_genuine_launch_and_managed_consumption_produce_three_bound_receipts_and_draft",
        "genuine_launch_and_consumption", w.wrap(record))

    w = lab.world()
    first = w.observe()
    w.row(w.delivery, api.BUCKET_INTENTS, PLAN, previous_instance_id=INSTANCE)
    second = w.observe()
    put(lab, out, "capture", "test_consumption_uses_the_previous_instance_and_binds_the_current_one_separately",
        "previous_instance_binding", w.wrap({"before": w.summary(first), "after": w.summary(
            second, code=P.CONSUMPTION, detail="receipt_stale_instance")}))

    w = lab.world()
    (w.control / "host-activation.json").write_text(json.dumps(w.activation_document, separators=(",", ":")))
    put(lab, out, "capture", "test_activation_file_equality_is_as_an_object_not_as_bytes",
        "activation_file_equal_as_an_object", w.wrap(w.summary(w.observe())))

    w = lab.world()
    ports = w.ports()
    run = w.cli(ports=ports)
    body = printed(run)
    first = {"code": run["code"], "keys_include": sorted({"observation", "evidence", "transition_draft"} & set(body)),
             "ok": body["observation"]["ok"]}
    w.edit(RECEIPT_NAME, instance_id=None)
    ports = w.ports()
    run = w.cli(ports=ports)
    second = {"code": run["code"], "reason_code": printed(run)["observation"]["reason_code"]}
    put(lab, out, "capture", "test_cli_prints_observation_evidence_and_draft_and_exits_by_ok",
        "cli_prints_and_exits_by_ok", w.wrap({"success": first, "canary_failure": second}))
    return out


def group_refuse(lab: Lab) -> dict:
    api, out, T = lab.api, {}, tables(lab.api)
    P = api.policy

    def standard(test, table, prefix, code, *, recheck=False, extra=None):
        for case in sorted(table):
            entry = table[case]
            mutate, detail = entry[0], entry[-1]
            expected = code if code is not None else entry[1]
            w = lab.world()
            if recheck:
                w.runner.on_recheck = lambda: mutate(w)
            else:
                mutate(w)
            result = w.observe()
            record = refusal(lab, w, result, expected, detail)
            if extra is not None:
                record["extra"] = extra(w, result)
            put(lab, out, "refuse", test, prefix + case, record)

    standard("test_canary_other_plan_target_instance_descriptor_null_false_pending_or_missing_refuses",
             T.canary, "canary.", P.CANARY)
    w = lab.world()
    w.edit(RECEIPT_NAME, instance_id=None, passed="yes")
    weak = api.owner_qualified_canary(w.target, w.descriptor, {"instance_id": INSTANCE}, plan=w.plan)
    result = w.observe()
    put(lab, out, "refuse", "test_incumbent_owner_canary_is_weaker_and_unchanged", "incumbent_canary_is_weaker",
        w.wrap({"incumbent_passed": weak["passed"], "producer": w.summary(result, code=P.CANARY,
                                                                          detail="canary_not_passed")}))
    consumption = {case: (entry[0], entry[1]) for case, entry in T.consumption.items()}
    standard("test_consumption_stale_foreign_revision_image_profile_digest_mismatch_refuses",
             consumption, "consumption.", P.CONSUMPTION)
    standard("test_retired_receipt_stopped_or_reused_pid_wrong_boot_invocation_dry_run_or_revision_refuses",
             T.process, "process.", None)
    standard("test_activation_file_must_equal_the_derived_receipt_and_current_and_no_fence",
             T.document, "document.", P.DOCUMENT)
    w = lab.world()
    result = w.observe(expected_id="0" * 64)
    put(lab, out, "refuse", "test_expected_id_must_be_the_effective_head", "expected_id_must_be_the_head",
        refusal(lab, w, result, P.DOCUMENT, "activation_head_moved"))
    standard("test_unreadable_source_refuses_as_unavailable", T.unreadable, "unreadable.", P.UNAVAILABLE)

    for store, detail in (("coordinator", "migration"), ("delivery", "delivery"), ("control", "canary_record")):
        w = lab.world()
        ports = w.ports()
        w.stores[store].fail = RuntimeError("connection to " + dsn(PW, "db/zeus") + " failed")
        with w.guard.active():
            result = api.observe(w.request(), ports)
        record = refusal(lab, w, result, P.UNAVAILABLE, detail)
        record["error_text_absent"] = PW not in json.dumps(result)
        put(lab, out, "refuse", "test_unavailable_store_refuses_without_error_text", "unavailable_store." + store,
            record)

    standard("test_any_identity_change_during_capture_refuses_changed", T.change, "change.", P.CHANGED, recheck=True,
             extra=lambda w, result: {"only_stable_capture_failed": [
                 name for name, held in result["observation"]["checks"].items() if not held] == ["stable_capture"],
                 "all_sources_recorded": all(entry is not None for entry in result["observation"]["sources"].values())})
    standard("test_a_source_gone_during_the_recheck_refuses_changed_not_unavailable", T.vanish, "vanish.", P.CHANGED,
             recheck=True, extra=lambda w, result: {"only_stable_capture_failed": [
                 name for name, held in result["observation"]["checks"].items() if not held] == ["stable_capture"]})

    w = lab.world()
    w.recheck_show_rc = 1
    first = w.summary(w.observe(), code=P.UNAVAILABLE, detail="unit")
    w.runner = Runner(api, w)
    w.runner.on_recheck = lambda: w.edit("descriptor.json", predecessor="0" * 64)
    second = w.summary(w.observe(), code=P.CHANGED, detail="descriptor")
    put(lab, out, "refuse", "test_an_unreadable_recheck_is_unknown_but_a_change_beside_it_is_a_change",
        "unreadable_recheck_versus_change", w.wrap({"unreadable": first, "change_beside_it": second}))

    for field, value in (("migration_id", "Bad Id"), ("expected_id", "x"), ("plan_id", "../p"), ("target_id", ""),
                         ("actor", "Actor!"), ("root", "relative/root"), ("config_file", "relative.env")):
        w = lab.world()
        ports = w.ports()
        outcome = w.attempt(lambda: api.observe(w.request(**{field: value}), ports))
        record = {"outcome": outcome, "no_command_ran": w.runner.calls == [],
                  "no_store_transaction": all(store.transactions == 0 for store in w.stores.values())}
        put(lab, out, "refuse", "test_invalid_request_refuses_before_any_read", "invalid_request." + field,
            w.wrap(record))

    for argv in (["--consumed", "true"], ["--passed", "true"], ["--receipt", "r.json"], ["--apply"]):
        w = lab.world()
        out_io, err_io = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(out_io), contextlib.redirect_stderr(err_io):
                api.parser().parse_args(w.cli_argv(*argv))
            outcome = "accepted"
        except SystemExit as exc:
            outcome = {"exit": exc.code}
        put(lab, out, "refuse", "test_cli_accepts_no_claim_substitute_receipt_or_apply_argument",
            "cli_argument." + argv[0].lstrip("-"), w.wrap({"outcome": outcome,
                                                          "printed_to_stdout": out_io.getvalue() != ""}))
    return out


def group_read_only(lab: Lab) -> dict:
    api, out, T = lab.api, {}, tables(lab.api)
    mutations = {"success": None, "canary_missing": T.canary["missing_receipt"][0],
                 "consumption_stale": T.consumption["stale_prior_instance"][0],
                 "launch_dry_run": T.process["dry_run_launch_only"][0],
                 "document_fence": T.document["host_fenced"][0],
                 "journal_unreadable": T.unreadable["journal_unreadable"][0]}
    for case, mutate in mutations.items():
        w = lab.world()
        if mutate is not None:
            mutate(w)
        ports = w.ports()
        before = (tree(w.root, w.proc), copy.deepcopy(w.coordinator.data), copy.deepcopy(w.control_store.data),
                  copy.deepcopy(w.delivery.data))
        result = w.observe(ports=ports)
        after = (tree(w.root, w.proc), w.coordinator.data, w.control_store.data, w.delivery.data)
        record = w.summary(result)
        record["read_only"] = {
            "no_write_attempt": w.guard.attempts == [], "no_store_put": all(s.puts == [] for s in w.stores.values()),
            "filesystem_and_stores_unchanged": after == before,
            "only_systemctl_show_or_journalctl": all(call[:2] == [api.SYSTEMCTL, "show"] or call[:1] == [api.JOURNALCTL]
                                                     for call in w.runner.calls),
            "minimal_environment_only": all(env == api.COMMAND_ENV for env in w.runner.envs),
            "ok_is_success": result["observation"]["ok"] is (case == "success"), "recomputes": w.recompute(result)}
        put(lab, out, "read_only", "test_producer_is_read_only_on_success_and_failure", "producer." + case,
            w.wrap(record))

    w = lab.world()
    result = w.observe()
    opened = {relative: flags for relative, flags in w.guard.os_opens.items()}
    names = {Path(relative).name for relative in opened}
    wanted = {"host-activation.json", "zeus-aibox.env", "descriptor.json", "startup-receipt.json", "cmdline",
              "supervisor-journal.jsonl", RECEIPT_NAME, REQUEST_NAME}
    put(lab, out, "read_only", "test_every_host_file_is_opened_read_only_without_following_or_blocking",
        "every_host_file_opened_read_only", w.wrap({
            "ok": result["observation"]["ok"], "named_files_opened": sorted(wanted & names),
            "missing_named_files": sorted(wanted - names),
            "every_open_nofollow_and_nonblock": all(flags == (True, True) for flags in opened.values()),
            "no_write_flag_or_attempt": w.guard.attempts == [], "opens": len(opened)}))

    # The lane path: every store read through a read-only snapshot, exactly this SQL shape.
    class Rows:
        def __init__(self, rows):
            self.rows = rows

        def fetchone(self):
            return self.rows[0] if self.rows else None

        def fetchall(self):
            return list(self.rows)

    class Connection:
        """A psycopg connection double serving the fixture store of the connection's search path."""

        def __init__(self, stores, connection, kwargs, log):
            options = api.conninfo_to_dict(connection)["options"]
            assert options.startswith("-c search_path=")
            self.schema = options.split("=", 1)[1]
            self.store, self.statements = stores[self.schema], []
            log.append({"schema": self.schema, "kwargs": kwargs, "statements": self.statements})

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def execute(self, sql, params=()):
            self.statements.append(sql)
            if sql == "SELECT current_schema()":
                return Rows([(self.schema,)])
            if sql == "SELECT body FROM documents WHERE bucket=%s AND id=%s":
                body = self.store.data.get(tuple(params))
                return Rows([] if body is None else [(copy.deepcopy(body),)])
            if sql == "SELECT body FROM documents WHERE bucket=%s ORDER BY id":
                return Rows([(copy.deepcopy(body),) for (bucket, _), body in sorted(self.store.data.items())
                             if bucket == params[0]])
            return Rows([])

    w = lab.world()
    with w.control_store.transaction() as tx:
        tx.put("fleet_registry", "fleet", {"id": "fleet", "config": {"lanes": [
            {"id": "harness", "schema": "zeus_lane_harness"}, {"id": "other", "schema": "zeus_lane_other"}]}})
    stores = {"zeus_aibox_migration": w.coordinator, "zeus_aibox_control": w.control_store,
              "zeus_lane_harness": w.delivery}
    before = {name: copy.deepcopy(store.data) for name, store in stores.items()}
    log: list = []
    host = w.host()
    env = {"ZEUS_TEST_MIGRATION_DSN": "postgresql://zeus@127.0.0.1:1/zeus",
           "ZEUS_TEST_CONTROL_DSN": "postgresql://zeus@127.0.0.1:1/zeus"}
    with api.patch_connect(lambda connection, **kwargs: Connection(stores, connection, kwargs, log)):
        run = w.cli("--dsn-env", "ZEUS_TEST_MIGRATION_DSN", "--control-dsn-env", "ZEUS_TEST_CONTROL_DSN",
                    "--lane", "harness", patches={"HostReader": lambda **kwargs: host}, env=env)
    body = printed(run)
    connections = []
    for entry in log:
        statements = entry["statements"]
        connections.append({
            "schema": entry["schema"], "kwargs": entry["kwargs"], "head": statements[:3], "tail": statements[-1],
            "statements": len(statements), "middle_only_selects": all(sql in (
                "SELECT body FROM documents WHERE bucket=%s AND id=%s",
                "SELECT body FROM documents WHERE bucket=%s ORDER BY id") for sql in statements[3:-1]),
            "advisory_lock": any("pg_advisory" in sql.lower() for sql in statements)})
    put(lab, out, "read_only", "test_lane_path_reads_every_store_through_read_only_snapshots_with_the_exact_sql_shape",
        "lane_path_through_read_only_snapshots", w.wrap({
            "code": run["code"], "ok": body["observation"]["ok"], "stderr_empty": run["stderr"] == "",
            "schemas": sorted({entry["schema"] for entry in log}), "connections": connections,
            "lane_reads": len([entry for entry in log if entry["schema"] == "zeus_lane_harness"]),
            "stores_unchanged": {name: store.data for name, store in stores.items()} == before}))

    w = lab.world()
    connected = []
    stored = []
    with contextlib.ExitStack() as stack:
        stack.enter_context(api.environ({"ZEUS_TEST_DSN": "postgresql://zeus@127.0.0.1:1/zeus"}))
        stack.enter_context(api.patch_connect(lambda *a, **k: connected.append(1) or (_ for _ in ()).throw(
            AssertionError("connected"))))
        stack.enter_context(api.forbid_writer_store(stored))
        args = api.parser().parse_args(["observe-limited-active", "--migration-id", MID, "--expected-id", "a" * 64,
                                        "--target-id", TARGET, "--plan-id", PLAN, "--actor", "a", "--root", "/r",
                                        "--dsn-env", "ZEUS_TEST_DSN", "--schema", "zeus_aibox_migration",
                                        "--control-dsn-env", "ZEUS_TEST_DSN", "--control-schema",
                                        "zeus_aibox_control"])
        ports = api.cli_ports(args)
        snapshot = {"coordinator_is_snapshot": isinstance(ports.coordinator, api.LaneSnapshotStore),
                    "control_is_snapshot": isinstance(ports.control, api.LaneSnapshotStore),
                    "schemas": [ports.coordinator.schema, ports.control.schema],
                    "delivery_is_control": ports.delivery(ports.control) is ports.control}
        args.schema = "public"
        public = w.attempt(lambda: api.cli_ports(args))
    put(lab, out, "read_only", "test_cli_ports_are_read_only_snapshots_and_connect_nothing",
        "cli_ports_are_read_only_snapshots", w.wrap({
            **snapshot, "public_schema": public, "connections_opened": len(connected),
            "writer_store_constructed": len(stored)}))
    return out


def group_archive(lab: Lab) -> dict:
    api, out, T = lab.api, {}, tables(lab.api)
    P = api.policy

    w = lab.world()
    result = w.observe()
    archive = archived(result)
    record = {"recomputes": w.recompute(result), "archive_round_trips": archive == result,
              "archive_recomputes": w.recompute(archive)}
    projections = result["projections"]
    supervisor, entry = projections["supervisor"], projections["entry"]
    record["launch"] = {"event_is_the_launch_event": projections["launch"]["event"] == launch_event(),
                        "cursor_shape": projections["launch"]["cursor"].startswith("s=")}
    record["processes"] = {
        "supervisor": [supervisor["role"], supervisor["pid"], supervisor["start_ticks"], supervisor["invocation_id"]],
        "entry": [entry["role"], entry["pid"], entry["start_ticks"], entry["boot_id"]],
        "supervisor_validated": supervisor["validated"], "entry_validated": entry["validated"],
        "argv_match": [supervisor["argv_match"], entry["argv_match"]],
        "no_raw_argv": "argv" not in supervisor and "argv" not in entry,
        "entry_digest_is_the_cmdline_digest": entry["argv_sha256"] == hashlib.sha256(
            (w.proc / str(ENTRY_PID) / "cmdline").read_bytes()).hexdigest(),
        "third_release_absent_from_entry": str(w.releases / INTENT_REV) not in json.dumps(entry)}
    record["sealed_runtime_revision"] = projections["descriptor"]["runtime"]["revision"]
    put(lab, out, "archive", "test_every_source_hash_and_the_common_digest_recompute_from_the_archive",
        "every_hash_recomputes_from_the_archive", w.wrap(record))

    w = lab.world()
    good = w.observe()["observation"]
    cases = {
        "extra_key": {**good, "extra": 1},
        "canary_bound_false_while_ok": {**good, "checks": {**good["checks"], "canary_bound": False}},
        "canary_record_source_none": {**good, "sources": {**good["sources"], "canary_record": None}},
        "reason_code_while_ok": {**good, "reason_code": P.CANARY},
        "made_up_reason_code": {**good, "ok": False, "reason_code": "made_up"},
        "lineage_owner_bootstrap": {**good, "lineage": {**good["lineage"], "owner": "bootstrap"}},
        "lineage_descriptor_other_image": {**good, "lineage": {**good["lineage"], "descriptor": {
            **good["lineage"]["descriptor"], "worker_image": "sha256:" + "8" * 64}}},
        "observed_to_before_observed_from": {**good, "observed_to": "2026-09-28T11:29:00+00:00"},
        "source_digest_not_hex": {**good, "sources": {**good["sources"], "launch": {
            "sha256": "X" * 64, "observed_at": good["observed_to"]}}}}
    record = {"good_is_valid": P.validate_observation(good) == good}
    for name, broken in cases.items():
        record[name] = w.attempt(lambda: P.validate_observation(broken))
    record["draft_from_a_failed_observation"] = w.attempt(lambda: P.transition_draft(
        {**good, "ok": False}, {}, host="aibox", actor="a", config_sha256="0" * 64))
    put(lab, out, "archive", "test_observation_validation_is_strict_and_ok_means_everything_held",
        "observation_validation_is_strict", w.wrap(record))

    for case in sorted(T.archive):
        build, overrides, field_name = T.archive[case]
        w = lab.world()
        w.good = archived(w.observe())
        archive = build(w)
        ports = w.ports()
        w.runner.calls.clear()
        outcome = w.attempt(lambda: api.observe(w.request(**overrides), ports, expect=archive))
        record = {"outcome": outcome, "expected_field": field_name,
                  "no_command_ran": w.runner.calls == [],
                  "no_store_transaction": all(store.transactions == 0 for store in w.stores.values())}
        put(lab, out, "archive", "test_ph4_13_an_archive_that_is_not_this_producers_complete_success_is_refused_before_any_read",
            "refused_archive." + case, w.wrap(record))

    for content in (None, "{not json", "[]", "NaN"):
        w = lab.world()
        (w.tmp / "archive").mkdir()
        path = w.tmp / "archive" / "archived-observation.json"
        if content is not None:
            path.write_text(content)
        built = []
        patches = {"cli_ports": lambda args: built.append(1) or (_ for _ in ()).throw(AssertionError("ports built"))}
        first = w.cli("--expect", str(path), patches=patches)
        second = w.cli("--expect", "relative/archive.json", patches=patches)
        put(lab, out, "archive", "test_ph4_13_an_unreadable_archive_file_is_refused_naming_the_argument_only",
            "unreadable_archive_file." + ("missing" if content is None else {"{not json": "not_json", "[]": "array",
                                                                             "NaN": "nan"}[content]),
            w.wrap({"absolute_path": {"code": first["code"], "printed": printed(first)},
                    "relative_path": {"code": second["code"], "printed": printed(second)},
                    "ports_built": len(built)}))
    return out


def group_host_reader(lab: Lab) -> dict:
    api, out = lab.api, {}
    P = api.policy

    w = lab.world()
    with api.environ({"HARNESS_DATABASE_URL": dsn(PW, "db/zeus")}):
        result = w.observe()
    calls = w.runner.calls
    put(lab, out, "host_reader", "test_host_commands_are_absolute_filtered_and_get_only_a_minimal_environment",
        "commands_absolute_filtered_minimal_environment", w.wrap({
            "ok": result["observation"]["ok"], "calls": [[word for word in call] for call in calls],
            "call_count": len(calls), "environment_is_the_minimal_one_each_time": w.runner.envs == [api.COMMAND_ENV] * 3,
            "COMMAND_ENV": api.COMMAND_ENV, "SYSTEMCTL": api.SYSTEMCTL, "JOURNALCTL": api.JOURNALCTL,
            "systemctl_head": calls[0][:4]}))

    env = dict(api.COMMAND_ENV)
    with api.environ({"HARNESS_DATABASE_URL": dsn(PW, "db/zeus")}):
        shown = api.bounded_run([PY, "-c", "import json, os; print(json.dumps(sorted(os.environ)))"],
                                timeout=30, env=env, limit=4096)
    record = {"echo": {"returncode": shown.returncode, "stderr_empty": shown.stderr == b"",
                       "stdout_is_bytes": isinstance(shown.stdout, bytes),
                       "environment_is_exactly_the_given_one": set(json.loads(shown.stdout)) - {"LC_CTYPE"} == set(
                           api.COMMAND_ENV)}}
    flood = "import sys, time; sys.stdout.write('x' * 100000); sys.stdout.flush(); time.sleep(30)"
    try:
        api.bounded_run([PY, "-c", flood], timeout=30, env=env, limit=1000)
        record["flood"] = "returned"
    except api.Unreadable as exc:
        record["flood"] = {"raised": "Unreadable", "message": str(exc)}
    stop, ticks = threading.Event(), []

    def tick():  # the fake monotonic clock only moves when told to: keep it moving until the deadline is crossed
        while not stop.wait(0.2):
            api.advance(5)
            ticks.append(5)

    thread = threading.Thread(target=tick)
    thread.start()
    try:
        api.bounded_run([PY, "-c", "import time; time.sleep(30)"], timeout=0.5, env=env, limit=1000)
        record["deadline"] = "returned"
    except api.Unreadable as exc:
        record["deadline"] = {"raised": "Unreadable", "message": str(exc)}
    finally:
        stop.set()
        thread.join()
        api.advance(-sum(ticks))  # however many ticks it took, the fake clock ends exactly where it began
    # stderr is capped far lower than stdout and is itself an unknown.
    noisy = "import sys; sys.stderr.write('e' * 100000)"
    try:
        api.bounded_run([PY, "-c", noisy], timeout=30, env=env, limit=4096)
        record["stderr_flood"] = "returned"
    except api.Unreadable as exc:
        record["stderr_flood"] = {"raised": "Unreadable", "message": str(exc)}
    offset = api.boottime_offset_usec()
    record["measured_boottime_offset"] = {"type": type(offset).__name__, "non_negative": offset >= 0,
                                          "value": "<boottime-offset>"}
    put(lab, out, "host_reader",
        "test_bounded_run_caps_output_kills_on_the_deadline_and_passes_only_the_given_environment",
        "bounded_run_caps_deadline_and_environment", record)

    w = lab.world()
    descriptor = w.state / "descriptor.json"
    descriptor.unlink()
    os.mkfifo(descriptor)
    put(lab, out, "host_reader", "test_a_fifo_in_place_of_a_file_is_unknown_and_never_blocks", "fifo_in_place_of_a_file",
        refusal(lab, w, w.observe(), P.UNAVAILABLE, "descriptor"))

    w = lab.world()
    startup = w.state / "startup-receipt.json"
    startup.rename(w.state / "elsewhere.json")
    os.symlink(w.state / "elsewhere.json", startup)
    put(lab, out, "host_reader", "test_a_link_in_place_of_a_file_is_unknown", "link_in_place_of_a_file",
        refusal(lab, w, w.observe(), P.UNAVAILABLE, "startup"))

    w = lab.world()
    w.offset_usec = SUSPENDED_USEC
    shift = SUSPENDED_USEC // 10_000  # boottime ticks at 100 Hz include the suspension
    w.process(SUP_PID, 1, SUP_TICKS + shift, w.supervisor_argv())
    w.process(ENTRY_PID, SUP_PID, ENTRY_TICKS + shift, w.read_cmdline(ENTRY_PID))
    suspended = w.observe()
    supervisor = suspended["projections"]["supervisor"]
    first = w.summary(suspended)
    first["supervisor_clock"] = {"boottime_offset_ticks": supervisor["boottime_offset_ticks"],
                                 "start_usec": supervisor["start_usec"], "shift_ticks": shift,
                                 "start_usec_is_the_monotonic_start": supervisor["start_usec"] == SUP_TICKS * 10_000}
    w.offset_usec = 0  # the same host read without the offset: the boottime start looks an hour late
    second = w.summary(w.observe(), code=P.PROCESS, detail="supervisor_start")
    put(lab, out, "host_reader", "test_process_starts_are_compared_on_the_monotonic_clock_after_a_suspend",
        "monotonic_comparison_after_a_suspend", w.wrap({"with_the_offset": first, "without_the_offset": second}))

    for role in ("supervisor", "entry"):
        w = lab.world()
        secret = "--password=" + PW + "-argv-secret"
        pid, ppid, ticks = (SUP_PID, 1, SUP_TICKS) if role == "supervisor" else (ENTRY_PID, SUP_PID, ENTRY_TICKS)
        w.process(pid, ppid, ticks, ["/usr/bin/other-tool", secret])
        ports = w.ports()
        run = w.cli(ports=ports)
        body = printed(run)
        projection = body["projections"][role]
        put(lab, out, "host_reader",
            "test_a_reused_pid_keeps_only_an_argv_digest_and_its_arguments_never_reach_the_output",
            "reused_pid_keeps_only_an_argv_digest." + role, w.wrap({
                "code": run["code"], "argument_absent_from_output": PW not in run["stdout"] + run["stderr"],
                "diagnostic": body["diagnostic"], "projection": projection,
                "no_raw_argv": "argv" not in projection, "argv_match": projection["argv_match"],
                "validated": projection["validated"],
                "digest_is_the_cmdline_digest": projection["argv_sha256"] == hashlib.sha256(
                    b"/usr/bin/other-tool\0" + secret.encode() + b"\0").hexdigest()}))

    # HostReader primitives (not M7 tests): `file`, `exists`, `current`, `release_present`.
    w = lab.world()
    root = w.tmp / "primitives"
    root.mkdir()
    (root / "regular").write_bytes(b"abc")
    (root / "directory").mkdir()
    os.mkfifo(root / "fifo")
    os.symlink(root / "regular", root / "link")
    release = w.tmp / "primitive-releases"
    (release / ("d" * 40)).mkdir(parents=True)
    os.symlink("d" * 40, release / "current")
    os.symlink(w.tmp / "primitives", release / ("e" * 40))
    Reader = api.HostReader
    record = {"regular": Reader.file(root / "regular"), "missing": Reader.file(root / "missing"),
              "oversized": w.attempt(lambda: Reader.file(root / "regular", 2)),
              "exactly_the_limit": Reader.file(root / "regular", 3),
              "directory": w.attempt(lambda: Reader.file(root / "directory")),
              "fifo": w.attempt(lambda: Reader.file(root / "fifo")),
              "link": w.attempt(lambda: Reader.file(root / "link")),
              "exists": [Reader.exists(root / "regular"), Reader.exists(root / "link"),
                         Reader.exists(root / "missing")],
              "current": Reader.current(release), "release_present": [
                  Reader.release_present(release, "d" * 40), Reader.release_present(release, "e" * 40),
                  Reader.release_present(release, "f" * 40)]}
    record["regular"] = "abc" if record["regular"] == b"abc" else record["regular"]
    record["exactly_the_limit"] = "abc" if record["exactly_the_limit"] == b"abc" else record["exactly_the_limit"]
    out["extra.primitives"] = w.n(record)
    return out


def group_ph4_13(lab: Lab) -> dict:
    api, out, T = lab.api, {}, tables(lab.api)
    M = api.migration

    def comparison(w, result, mode, ok, code=None, detail=None):
        compared = result["comparison"]
        record = w.summary(result)
        record["relations"] = {
            "keys_are_the_comparison_output": set(result) == {"observation", "result_sha256", "projections",
                                                              "diagnostic", "comparison"},
            "mode": compared["mode"] == mode, "ok": compared["ok"] is ok,
            "code_and_detail": [compared["reason_code"], compared["detail"]] == [code, detail],
            "post_check": compared["post_check"] == ("ok" if ok and mode == "post_transition" else None),
            "recomputes": w.recompute(result)}
        return record

    w = lab.world()
    archive = archived(w.observe())
    result = w.observe(expect=archive)
    record = comparison(w, result, "pre_submit", True)
    record["expected_result_sha256_is_the_archive"] = result["comparison"]["expected_result_sha256"] == archive[
        "result_sha256"]
    record["source_digests_equal_the_archive"] = {name: entry["sha256"] for name, entry in result["observation"][
        "sources"].items()} == {name: entry["sha256"] for name, entry in archive["observation"]["sources"].items()}
    put(lab, out, "ph4_13", "test_ph4_13_an_unchanged_capture_passes_the_pre_submit_comparison_and_emits_no_draft",
        "unchanged_capture_passes_pre_submit", w.wrap(record))

    for case in sorted(T.pre_submit):
        mutate, code, detail = T.pre_submit[case]
        w = lab.world()
        w.archive = archived(w.observe())
        mutate(w)
        result = w.observe(expect=w.archive)
        put(lab, out, "ph4_13", "test_ph4_13_a_pre_submit_tuple_change_is_refused", "pre_submit." + case,
            w.wrap(comparison(w, result, "pre_submit", False, code, detail)))

    w = lab.world()
    archive = archived(w.observe())
    launcher_bytes = (w.control / "host-activation.json").read_bytes()
    advanced = w.submit(archive)
    result = w.observe(expect=archive, post_transition=True)
    record = comparison(w, result, "post_transition", True)
    projection = result["projections"]["migration"]
    record["relations"].update({
        "recorded_state_is_limited_active": advanced["state"] == M.LIMITED_ACTIVE,
        "observation_ok_and_no_diagnostic": result["observation"]["ok"] is True and result["diagnostic"] is None,
        "projection_state": projection["state"] == M.LIMITED_ACTIVE,
        "last_transition_lineage_is_the_archive": projection["last_transition"]["lineage"] == archive[
            "observation"]["lineage"],
        "last_transition_id_is_the_draft_id": projection["last_transition"]["id"] == M.transition_id(
            archive["transition_draft"]),
        "launcher_file_not_rewritten": (w.control / "host-activation.json").read_bytes() == launcher_bytes,
        "activation_unchanged": result["observation"]["activation"] == archive["observation"]["activation"]})
    put(lab, out, "ph4_13", "test_ph4_13_the_post_check_passes_only_after_the_recorded_managed_transition",
        "post_check_passes_after_the_recorded_transition", w.wrap(record))

    for case in sorted(T.post_check):
        record_first, mutate, code, detail = T.post_check[case]
        w = lab.world()
        w.archive = archived(w.observe())
        if record_first:
            w.submit(w.archive)
        mutate(w)
        result = w.observe(expect=w.archive, post_transition=True)
        put(lab, out, "ph4_13", "test_ph4_13_a_post_check_difference_is_refused", "post_check." + case,
            w.wrap(comparison(w, result, "post_transition", False, code, detail)))

    w = lab.world()
    ports = w.ports()
    outcome = w.attempt(lambda: api.observe(w.request(), ports, post_transition=True))
    built = []
    run = w.cli("--post-transition", patches={
        "cli_ports": lambda args: built.append(1) or (_ for _ in ()).throw(AssertionError("ports built"))})
    put(lab, out, "ph4_13", "test_ph4_13_post_transition_without_an_archive_is_refused_before_any_read",
        "post_transition_without_an_archive", w.wrap({
            "outcome": outcome, "no_command_ran": w.runner.calls == [],
            "no_store_transaction": all(store.transactions == 0 for store in w.stores.values()),
            "cli": {"code": run["code"], "printed": printed(run), "ports_built": len(built)}}))

    for post in (False, True):
        w = lab.world()
        archive = archived(w.observe())
        (w.tmp / "archive").mkdir()
        path = w.tmp / "archive" / "archived-observation.json"
        path.write_text(json.dumps(archive, sort_keys=True, indent=2))
        if post:
            w.submit(archive)
        ports = w.ports()
        before = (tree(w.root, w.proc), copy.deepcopy(w.coordinator.data), copy.deepcopy(w.control_store.data),
                  copy.deepcopy(w.delivery.data))
        extra = ["--expect", str(path)] + (["--post-transition"] if post else [])
        w.runner.calls.clear()
        w.runner.envs.clear()
        w.guard.os_opens.clear()
        w.guard.opens.clear()
        run = w.cli(*extra, ports=ports)
        after = (tree(w.root, w.proc), w.coordinator.data, w.control_store.data, w.delivery.data)
        body = printed(run)
        record = {"code": run["code"], "no_draft_or_evidence": "transition_draft" not in body and "evidence" not in body,
                  "post_check": body["comparison"]["post_check"], "comparison": body["comparison"],
                  "no_write_attempt": w.guard.attempts == [], "no_store_put": all(s.puts == [] for s in w.stores.values()),
                  "filesystem_and_stores_unchanged": after == before, "stderr_empty": run["stderr"] == ""}
        w.learn(body)
        ports = w.ports()
        opposite = w.cli("--expect", str(path), *([] if post else ["--post-transition"]), ports=ports)
        record["opposite_mode"] = {"code": opposite["code"],
                                   "reason_code": printed(opposite)["comparison"]["reason_code"]}
        put(lab, out, "ph4_13", "test_ph4_13_the_comparison_is_read_only_and_exits_by_its_verdict",
            "cli_comparison_read_only." + ("post_transition" if post else "pre_submit"), w.wrap(record))
    return out


def group_f1(lab: Lab) -> dict:
    api, out, T = lab.api, {}, tables(lab.api)
    P = api.policy

    for case in sorted(T.leak):
        mutate, code, detail = T.leak[case]
        w = lab.world()
        mutate(w)
        result = w.observe()
        record = refusal(lab, w, result, code, detail) if code is not None else w.wrap(w.summary(result))
        record["marker_absent_from_the_result"] = MARKER not in json.dumps(result, sort_keys=True)
        record["success_keeps_its_draft"] = (result["observation"]["ok"] is True
                                             and result["transition_draft"] is not None) if code is None else None
        ports = w.ports()
        run = w.cli(ports=ports)
        body = printed(run)
        record["cli"] = {"code": run["code"], "exit_expected": run["code"] == (0 if code is None else 1),
                         "marker_absent": MARKER not in run["stdout"] + run["stderr"], "stderr_empty": run["stderr"] == "",
                         "same_digest": body["result_sha256"] == result["result_sha256"],
                         "recomputes": w.recompute(body)}
        put(lab, out, "f1", "test_f1_no_excluded_key_or_untyped_value_reaches_the_result_or_the_cli", "leak." + case,
            w.n(record))

    w = lab.world()
    original = (w.state / "startup-receipt.json").read_bytes()
    w.edit("startup-receipt.json", password=SECRET, **{MARKER: 1})
    raw = (w.state / "startup-receipt.json").read_bytes()
    result = w.observe()
    first = w.summary(result, code=P.CONSUMPTION, detail="receipt_fields")
    startup, descriptor = result["projections"]["startup"], result["projections"]["descriptor"]
    first["startup"] = {
        "keys": sorted(startup), "raw_digest_is_the_file_digest": startup["raw_sha256"] == hashlib.sha256(raw).hexdigest(),
        "accepted": startup["accepted"], "shape": startup["shape"],
        "document_keys_are_the_allowlist": set(startup["document"]) == set(P.STARTUP_DOCUMENT),
        "instance_and_pid": [startup["document"]["instance_id"], startup["document"]["pid"]],
        "paths_withheld": [startup["document"]["runtime_root"], startup["document"]["module_root"]]}
    first["descriptor"] = {"accepted": descriptor["accepted"], "root": descriptor["document"]["root"],
                           "revision": descriptor["document"]["revision"], "runtime": descriptor["runtime"]}
    (w.state / "startup-receipt.json").write_bytes(original)
    w.edit(RECEIPT_NAME, password=SECRET, passed="yes")
    raw = (w.state / RECEIPT_NAME).read_bytes()
    result = w.observe()
    second = w.summary(result, code=P.CANARY, detail="canary_receipt_shape")
    canary = result["projections"]["canary_receipt"]["receipt"]
    second["receipt"] = {"raw_digest_is_the_file_digest": canary["raw_sha256"] == hashlib.sha256(raw).hexdigest(),
                         "accepted": canary["accepted"], "shape": canary["shape"],
                         "passed_withheld": canary["document"]["passed"],
                         "instance_id": canary["document"]["instance_id"],
                         "marker_absent": MARKER not in json.dumps(result)}
    put(lab, out, "f1", "test_f1_a_rejected_host_document_keeps_its_raw_digest_shape_and_typed_identifiers_only",
        "rejected_host_document_keeps_digest_shape_identifiers", w.wrap({"startup_receipt": first,
                                                                          "canary_receipt": second}))

    w = lab.world()
    result = w.observe()
    projections = result["projections"]
    documents = {"activation_file": (projections["activation_file"], w.activation_document),
                 "descriptor": (projections["descriptor"], w.descriptor),
                 "startup": (projections["startup"], w.read(w.state / "startup-receipt.json")),
                 "receipt": (projections["canary_receipt"]["receipt"], w.read(w.state / RECEIPT_NAME)),
                 "request": (projections["canary_receipt"]["request"], w.read(w.state / REQUEST_NAME))}
    put(lab, out, "f1", "test_f1_an_accepted_source_is_its_complete_typed_document", "accepted_source_is_complete",
        w.wrap({"ok": result["observation"]["ok"], "sources": {name: {
            "accepted": projection["accepted"], "document_equals_the_document_read": projection["document"] == document,
            "invalid": projection["shape"]["invalid"], "extra": projection["shape"]["extra"]}
            for name, (projection, document) in documents.items()}}))

    for case in sorted(T.recheck_raw):
        mutate, detail = T.recheck_raw[case]
        w = lab.world()
        w.runner.on_recheck = lambda: mutate(w)
        result = w.observe()
        record = refusal(lab, w, result, P.CHANGED, detail)
        record["marker_absent"] = MARKER not in json.dumps(result)
        record["recomputes"] = w.recompute(result)
        put(lab, out, "f1", "test_f1_the_stable_capture_still_compares_raw_bytes", "recheck_raw." + case, record)

    for case in sorted(T.pre_submit_raw):
        mutate, detail = T.pre_submit_raw[case]
        w = lab.world()
        archive = archived(w.observe())
        mutate(w)
        result = w.observe(expect=archive)
        compared = result["comparison"]
        record = w.summary(result)
        record["relations"] = {"observation_ok": result["observation"]["ok"] is True,
                               "refused_as_changed": [compared["ok"], compared["mode"], compared["reason_code"],
                                                      compared["detail"]] == [False, "pre_submit", P.CHANGED, detail],
                               "marker_absent": MARKER not in json.dumps(result), "recomputes": w.recompute(result)}
        put(lab, out, "f1", "test_f1_a_pre_submit_change_only_in_dropped_content_is_still_refused",
            "pre_submit_raw." + case, w.wrap(record))

    for changes, ok, detail, name in (({"password": SECRET}, True, None, "excluded_key_is_dropped"),
                                      ({"id": SECRET, MARKER: 1}, False, "transition_id", "wrong_typed_id_refuses")):
        w = lab.world()
        archive = archived(w.observe())
        w.submit(archive)
        T.history(w, **changes)
        result = w.observe(expect=archive, post_transition=True)
        compared = result["comparison"]
        last = result["projections"]["migration"]["last_transition"]
        record = w.summary(result)
        record["relations"] = {
            "comparison": [compared["mode"], compared["ok"], compared["reason_code"], compared["detail"]] == [
                "post_transition", ok, None if ok else P.CHANGED, detail],
            "marker_absent": MARKER not in json.dumps(result),
            "last_transition_within_the_allowlist": set(last) <= set(P.HISTORY_ENTRY),
            "last_transition_lineage_is_the_archive": last["lineage"] == archive["observation"]["lineage"]}
        put(lab, out, "f1", "test_f1_the_recorded_history_entry_reaches_the_post_check_only_through_its_allowlist",
            "history_entry_through_the_allowlist." + name, w.wrap(record))

    # A credential typed where an environment name belongs, and a malformed DSN, are refused without its value.
    for option in ("--dsn", "--dsn-env", "--control-dsn-env"):
        w = lab.world()
        secret = dsn(PW)
        built = []
        run = w.cli(option, secret, patches={"HostReader": lambda **kwargs: built.append(1) or (_ for _ in ()).throw(
            AssertionError("host reader built"))}, env={"HARNESS_DATABASE_URL": "postgresql://zeus@127.0.0.1:1/zeus"})
        put(lab, out, "f1", "test_a_credential_given_as_an_env_name_is_refused_and_never_echoed",
            "credential_as_env_name." + option.lstrip("-"), w.wrap({
                "code": run["code"], "secret_absent": PW not in run["stdout"] + run["stderr"],
                "printed": printed(run), "host_reader_built": len(built)}))

    values = {"malformed_percent_escape": "postgresql://zeus:" + "hun%zz" + "ter2@127.0.0.1/zeus",
              "secret_token": "sk-live-" + PW + "-secret",
              "unterminated_host": "postgresql://zeus:" + PW + "@[unterminated/zeus"}
    for name, value in values.items():
        for option in ("--dsn-env", "--control-dsn-env"):
            w = lab.world()
            built = []
            other = "--control-dsn-env" if option == "--dsn-env" else "--dsn-env"
            run = w.cli(option, "ZEUS_TEST_SECRET", other, "ZEUS_TEST_DSN", patches={
                "HostReader": lambda **kwargs: built.append(1) or (_ for _ in ()).throw(AssertionError("built"))},
                env={"ZEUS_TEST_DSN": "postgresql://zeus@127.0.0.1:1/zeus", "ZEUS_TEST_SECRET": value})
            put(lab, out, "f1", "test_a_malformed_dsn_or_a_secret_variable_is_refused_without_its_value",
                "malformed_dsn." + name + "." + option.lstrip("-"), w.wrap({
                    "code": run["code"], "secret_absent": PW not in run["stdout"] + run["stderr"],
                    "no_traceback": "Traceback" not in run["stderr"], "printed": printed(run),
                    "host_reader_built": len(built)}))

    # A store failure through the real snapshot store with a failing connection: no credential, no host command.
    w = lab.world()
    host_calls = []

    def connect(connection, **kwargs):
        raise api.OperationalError("connection to " + connection + " failed: password " + PW + "-credential")

    with api.patch_connect(connect):
        run = w.cli("--dsn-env", "ZEUS_TEST_MIGRATION_DSN", "--control-dsn-env", "ZEUS_TEST_CONTROL_DSN", "--lane",
                    "harness", patches={"bounded_run": lambda *a, **k: host_calls.append(1) or (_ for _ in ()).throw(
                        AssertionError("host command"))},
                    env={"ZEUS_TEST_MIGRATION_DSN": dsn(PW + "-credential", "127.0.0.1:1/zeus"),
                         "ZEUS_TEST_CONTROL_DSN": dsn(PW + "-credential", "127.0.0.1:1/zeus")})
    body = printed(run)
    put(lab, out, "f1", "test_cli_store_failure_leaks_no_credential_and_reads_no_host",
        "cli_store_failure_leaks_no_credential", w.wrap({
            "code": run["code"], "credential_absent": PW not in run["stdout"] + run["stderr"],
            "diagnostic": body["diagnostic"], "draft_none": body["transition_draft"] is None,
            "host_commands": len(host_calls)}))
    return out


# What each projection's `raw_sha256` covers, read from SOURCE (`domain.host_migration_evidence._PROJECTIONS`).
RAW_DIGEST_COVERS = {
    "activation_file": "sha256 of the exact bytes of host-activation.json (as read by HostReader.file)",
    "descriptor": "sha256 of the exact bytes of the managed state directory's descriptor.json",
    "startup": "sha256 of the exact bytes of the startup-receipt.json",
    "canary_receipt.receipt": "sha256 of the exact bytes of the plan-scoped owner-canary-receipt file",
    "canary_receipt.request": "sha256 of the exact bytes of the plan-scoped owner-canary-request file",
    "migration.config_sha256": "sha256 of the exact bytes of the host configuration file (not a raw_sha256 key)",
    "delivery": "digest (canonical JSON) of delivery_view(target, plan, intent, descriptor row, intents), the "
                "view derived from the store rows; recomputed here from the same rows before the run",
    "canary_record": "digest (canonical JSON) of record_view(the owner-action record row); recomputed here "
                     "from the same row before the run",
    "launch": "digest of the launch-record object the producer builds from the journal (not the journal bytes); "
              "not recomputed",
    "supervisor": "digest of the process-projection facts object (identity, parent, cgroup, argv digest, unit, "
                  "launches) the producer builds, not file bytes; not recomputed",
    "entry": "digest of the process-projection facts object (identity, parent, cgroup, argv digest) the producer "
             "builds, not file bytes; not recomputed",
    "supervisor_journal": "no projection carries a raw digest of supervisor-journal.jsonl: only digest(launches) of "
                          "the parsed lines enters the identity tuple (not archived)"}

GROUPS = (("capture", group_capture), ("refuse", group_refuse), ("read_only", group_read_only),
          ("archive", group_archive), ("host_reader", group_host_reader), ("ph4_13", group_ph4_13),
          ("f1", group_f1))
M7_TESTS = 46


def run(api) -> dict:
    result, counts = {}, {}
    with tempfile.TemporaryDirectory(prefix="s7-migration-evidence-") as raw:
        lab = Lab(api, Path(raw).resolve())
        for name, group in GROUPS:
            result[name] = group(lab)
            counts[name] = len(result[name])
        result["mirrored_tests"] = {test: sorted(keys) for test, keys in sorted(lab.mirrors.items())}
        assert len(result["mirrored_tests"]) == M7_TESTS, sorted(result["mirrored_tests"])
    result["raw_digest_covers"] = RAW_DIGEST_COVERS
    result["carried"] = {}
    result["unreachable"] = {
        "real_systemd": "the real `systemctl show` and `journalctl` answers need a live unit and journal; the runner "
                        "is the labelled double the M7 tests use",
        "real_proc": "the /proc of a production process is never read; the fixture /proc is read through HostFacts",
        "real_postgresql": "the real LaneSnapshotStore session needs a PostgreSQL server; its connection is the "
                           "labelled double"}
    result["cases_per_group"] = counts
    text = json.dumps(result, sort_keys=True)
    for secret in (PW, "sk-live", MARKER, "postgresql://zeus:"):
        assert secret not in text, "a secret-shaped test value reached the result"
    return result
