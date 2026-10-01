"""Shared S7 scenario steps (`delivery.managed_runtime`): the M7 managed Fleet host target, recorded BEFORE the move
(DESIGN-s7 §2 row `delivery.managed_runtime`; TRACE-s7 §5.6).

Seven case groups, each case labelled in the result and mirroring one M7 test of `tests/test_managed_runtime.py`
(273-1077; the mapping is in `MIRRORS`):
- `seal`: the `Materializer`: one seal of an exact reviewed revision, the lost-response revalidation, the
  interrupted seal and its evidence, a linked worktree source.
- `refuse`: a changed or foreign directory, an unresolved revision, an unqualified environment, a tracked symlink,
  the fence checked before any write, the registry and runtime-path grammar, and a bad runtime before the running
  instance is touched.
- `launch`: a clean start, a restart and a repeated start (exactly one fixture workload runtime), a child that
  outlives its killed launcher, two owners at once, and the in-process entry points (`entry`, `launch`,
  `RuntimeControl`, `FixtureLauncher`, `run_fixture`).
- `drain_stop`: drain and stop against active, owned, unknown and absent work and heartbeat (`work_verdict`).
- `gate`: the activation gate over a labelled Fleet authority for a first start (failed reads, an unconfigured
  authority, every answer `gate_refusal` names) and the launch-request grammar.
- `rollback`: forward activation over two sealed revisions, the predecessor restored and its old code, and the
  restoration over held, unknown and settled Fleet debt (the gate between the stop and the launch).
- `scan`: the physical-byte identity of a listing and the refusal of a symlink.

**Fixtures (all LABELLED).**
- The source repository `<root>/source` is a git repository holding a COPY of SOURCE `src/codex_harness`
  (`api.SOURCE_PACKAGE`, no bytecode), a labelled `uv.lock` and a README, with revision A; revision B appends one
  labelled comment line to `adapters/managed_runtime.py`. Commits are made under the pinned `GIT_*` author,
  committer and dates of `s7_host_targets.GIT_FIXED` and empty git configuration files, so both revisions are
  deterministic. The source is built twice and both revisions must be identical; they are recorded literally.
  `s7_host_targets` builds only ONE attested commit, so it cannot be imported for this; its pinned identity is.
- The sealed runtimes, their digests and the launched fixture-workload children are therefore IDENTICAL INPUTS on
  both sides: the code under test is the side's controller-side classes (`Materializer`, `ManagedFleetTarget`,
  the launch-request validation) and the side's own `Fleet` over its `MemoryStore`.
- The launcher is the side's own trusted launcher (`python -m <MODULE> launch`); the child imports only the sealed
  SOURCE copy. The workload is the labelled `fixture` workload: a real `FleetRunner` over an in-memory Fleet whose
  jobs are real children waiting for a release marker. No model, provider, systemd, docker or network is used.
- The Fleet authority of the gate is a labelled registered in-memory Fleet (`fixture_fleet`), never PostgreSQL.
  `FaultStore` is the labelled fault injection of `tests/test_fleet.py` over the side's `MemoryStore`.
- `determinism.install` freezes the wall clock and `time.monotonic`; the live children write real heartbeats, so a
  labelled synchroniser keeps the fake clock on the real wall time while a case runs (`api.sync_clock`). Times are
  never recorded. Stage names draw ids from `SpreadIds` (reset at every case), which vary in the first eight hex
  digits, unlike `determinism.FakeIds`.
- Every child a case starts is ended before the case ends (M7's `end_tree`/`teardown`); a sweep after each case
  fails the run on any live child and records `live_children: 0`.
- Cases unreachable without a real PostgreSQL/Redis (`run_fleet`), systemd or the coordinator are recorded as
  `{"unreachable": "<why>"}`; the coordinator-driven M7 tests are mirrored at the target, see `MIRRORS`.

`api` supplies `ManagedFleetTarget`, `Materializer`, `scan`, `owner_target`, `gate_refusal`,
`validate_launch_request`, `runtime_image`, `RuntimeControl`, `FixtureLauncher`, `fixture_config`,
`fixture_manifest`, `run_fixture`, `entry`, `launch`, `FIXTURE_JOBS_FILE`, `TARGET_FILE`, `LAUNCHER_JOURNAL`,
`MODULE`, `EXIT_REFUSED`, `LAUNCH_REQUEST_SCHEMA`, `DESCRIPTOR_FILE`, `RECEIPT_FILE`, `STATE_FILE`, `PAUSE_FILE`,
`STOP_FILE`, `alive`, `checkout_revision`, `runtime_revision`, `host_ports`, `effective_profile_digest`,
`DESCRIPTOR_SCHEMA`, `RECEIPT_SCHEMA`, `REGISTRY_SCHEMA`, `KIND_MANAGED`, `DeliveryRefused`, `consumption_verdict`,
`descriptor_digest`, `managed_runtime_root`, `same_path`, `within_path`, `validate_targets`, `HEARTBEAT_SCHEMA`,
`LISTING_FILE`, `MANIFEST_FILE`, `STAGE_PREFIX`, `EnvironmentUnqualified`, `check_runtime_path`,
`validate_manifest`, `work_verdict`, `Fleet`, `FleetRefused`, `MemoryStore`, `ACTIVATION_HOLD`, `BUCKET_CONTROL`,
`BUCKET_JOBS`, `BUCKET_UNITS`, `CONTROL_KEY`, `UNIT_CONDUCTOR`, `SOURCE_PACKAGE`, `PACKAGE_DIR`, `sync_clock()` and
`reset_ids()`.

**Normalization is explicit, done here and identical on both sides** (the rules of `s7_host_targets`, extended):
- `sys.executable` → `<python>`;
- this run's temporary root → `<root>`;
- the side's package directory → `<package>`; its parent directory (M7 `launcher_environment`'s `PYTHONPATH`) →
  `<package-parent>`; and the root its `loaded_runtime` derives from → `<package-root>`. In a wheel layout the
  parent and the root are the same directory, and the parent label wins. In the target's `src` layout they differ;
  the owner fixed this on 2026-10-01 after pilot 43 found the layout assumption;
- pids (every key `pid` or ending in `pid`) → `<pid>`;
- `instance_id`, and any 32-hex string or UUID → `<instance>`;
- ISO times → `<time>`;
- the unit invocation id (`INVOCATION_ID`) → `<invocation>`;
- a 64-hex descriptor digest the FIXTURE built → `<digest:NAME>` (a descriptor names `<root>/...`, so its digest
  differs per run); NAME is the fixture's own label of that descriptor, never derived from the observed value.
Revisions, manifest, listing and content digests and sealed-tree identities are NOT normalized: they are
deterministic by construction. Replacements run longest-first, and nothing else is masked.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import shutil
import signal
import stat
import subprocess
import tempfile
import threading
import time
import uuid
from pathlib import Path
from unittest import mock

import s7_host_targets as ht

PY, GIT_FIXED, proc_alive, until = ht.PY, ht.GIT_FIXED, ht.proc_alive, ht.until
LOCK = b"# labelled fixture lockfile: the qualified environment of these tests\n"
LOCK_SHA = hashlib.sha256(LOCK).hexdigest()
MARKER = "# labelled fixture revision B: the candidate's code differs from its predecessor\n"
MODULE_PATH = "src/codex_harness/adapters/managed_runtime.py"
TARGET_ID = "managed-fleet"
UNIT = "c" * 64
FENCED = {"kind": "fenced", "launch": UNIT, "claim": "fenced"}  # labelled fixture fence proof
GOAL_FIXTURE = {"path": "docs/GOAL.md", "sha256": "b" * 64, "criterion": "fixture", "base_revision": "a" * 40,
                "bytes": 7}
HEX32 = re.compile(r"^[0-9a-f]{32}$")
UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
INVOCATION = os.environ.get("INVOCATION_ID")
# Which M7 test (tests/test_managed_runtime.py) each case mirrors, and what differs.
MIRRORS = {
    "seal.seal_once_and_revalidate": "test_the_exact_revision_is_sealed_once_and_a_lost_response_revalidates_it",
    "seal.interrupted_seal": "test_an_interrupted_seal_leaves_named_evidence_and_the_retry_seals_once",
    "seal.lost_response": "test_a_lost_materialize_response_is_revalidated_and_projected_without_paths (target level)",
    "seal.linked_worktree": "test_a_linked_worktree_resolves_through_git_and_its_checkout_revision_through_commondir",
    "refuse.changed_or_foreign": "test_a_changed_or_foreign_directory_is_refused_and_never_overwritten",
    "refuse.unresolved_or_unqualified": "test_an_unresolved_revision_or_unqualified_environment_writes_nothing; "
                                        "test_an_unqualified_environment_is_a_named_unavailable_gate (target level)",
    "refuse.target_registry": "test_only_the_managed_kind_carries_owner_runtime_fields (registry part)",
    "refuse.runtime_path": "test_a_descriptor_may_name_only_the_sealed_directory_of_its_own_revision",
    "refuse.bad_runtime": "test_a_bad_runtime_is_refused_before_the_running_instance_is_touched",
    "launch.clean_start_restart_repeat": "test_a_clean_start_a_restart_and_a_repeated_start_launch_exactly_once",
    "launch.killed_launcher": "test_a_child_that_outlives_its_killed_launcher_is_still_running_and_stops_gracefully",
    "launch.two_owners": "test_two_owners_starting_at_once_launch_a_single_runtime",
    "drain_stop.active_work": "test_active_owned_work_prevents_the_drain_and_the_stop_until_it_finishes",
    "drain_stop.unavailable_heartbeat": "test_an_unavailable_heartbeat_prevents_idle_and_the_stop",
    "drain_stop.heartbeat_verdict": "test_an_absent_stale_or_foreign_heartbeat_is_unknown_and_never_idle",
    "gate.first_start_reads": "test_a_first_managed_start_refuses_on_a_failed_debt_read_or_pause_commit",
    "gate.no_authority": "test_a_managed_start_without_a_fleet_authority_refuses_before_any_effect",
    "rollback.forward_activation": "test_forward_activation_consumes_two_sealed_revisions (target level)",
    "rollback.predecessor_restored": "test_a_failed_candidate_restores_the_predecessor (target level)",
    "rollback.held_or_unknown_debt": "test_a_rollback_over_held_or_unknown_fleet_debt_never_starts_the_predecessor",
    "rollback.settled_rollback": "test_a_settled_rollback_starts_the_exact_predecessor_once",
    "rollback.first_gate_unknown": "test_a_first_rollback_gate_whose_debt_read_fails_after_the_pause",
    "scan.physical_bytes": "test_the_scan_ids_the_physical_bytes_of_lf_and_crlf_files",
    "scan.symlink": "test_the_scan_refuses_a_symlink_inside_a_runtime",
}
SKIPPED = ("test_a_lost_materialize_response_is_revalidated_and_projected_without_paths, "
           "test_forward_activation_..., test_a_failed_candidate_restores_... and the three rollback gate tests "
           "drive the HostDelivery coordinator (plans, releases, canaries, FakeGitHub): that is the stages family; "
           "they are mirrored at the target; the plan/resolve_descriptor and controller()-wiring parts of "
           "test_only_the_managed_kind... and test_a_managed_start_without_a_fleet_authority... are not mirrored")


class SpreadIds:
    """LABELLED id source: `uuid4` varies in its first eight hex digits (`determinism.FakeIds` does not), so stage
    names of repeated seals in one directory differ, exactly as real random ids would."""

    def __init__(self):
        self.counter = 1

    def reset(self):
        self.counter = 1

    def uuid4(self):
        value = uuid.UUID(int=(self.counter << 96) | (0x5EED << 80), version=4)
        self.counter += 1
        return value


def git_environment(base: Path) -> dict:
    empty = base / "empty-gitconfig"
    empty.write_text("", encoding="utf-8")
    return {**os.environ, **GIT_FIXED, "GIT_CONFIG_GLOBAL": str(empty), "GIT_CONFIG_SYSTEM": str(empty)}


def blob_sha1(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()  # noqa: S324 - git's own blob id


def procs_mentioning(needle: str) -> list:
    """The pids of live processes whose argv mentions `needle` (a case's own directory)."""
    found = []
    for name in os.listdir("/proc"):
        if name.isdigit() and int(name) != os.getpid():
            try:
                argv = (Path("/proc") / name / "cmdline").read_bytes()
            except OSError:
                continue
            if needle.encode() in argv and proc_alive(int(name)):
                found.append(int(name))
    return sorted(found)


class Managed(ht.Fixture):
    """One run: the temporary root, the labelled source, the digest labels and the targets of the current case.

    It reuses `s7_host_targets.Fixture.n` (the pid, instance, time, digest and substitution rules) and `attempt`,
    and adds the extensions named in the module docstring."""

    def __init__(self, api, base: Path):
        self.api, self.base = api, base
        self.digests, self.live, self.case_dir = {}, [], base
        loaded = Path(api.PACKAGE_DIR).resolve()
        loaded_root = loaded.parent.parent if loaded.parent.name == "src" else loaded.parent
        pairs = [(str(loaded), "<package>"), (str(api.PACKAGE_DIR), "<package>"), (PY, "<python>"),
                 (str(loaded.parent), "<package-parent>"), (str(loaded_root), "<package-root>"), (str(base), "<root>")]
        self.substitutions = sorted(pairs, key=lambda pair: -len(pair[0]))
        self.profile = api.effective_profile_digest() or "e" * 64
        self.git_env = git_environment(base)
        self.source = None

    # --- normalization -------------------------------------------------------------------------------
    def n(self, value):
        if isinstance(value, dict):
            # Idempotent: a document normalized once (a listing) may be normalized again as part of a larger one.
            out = {}
            for key, item in value.items():
                if isinstance(key, str) and key.endswith("pid") and type(item) is int:
                    out[key] = "<pid>"
                elif key == "instance_id" and isinstance(item, str):
                    out[key] = "<instance>"
                elif key == "worker_image" and isinstance(item, str):
                    out[key] = item if item in (ht.IMAGE, "<absent>", "<present>") else (
                        "<absent>" if item == "none" else "<present>")
                else:
                    out[self.n(key)] = self.n(item)
            return out
        if isinstance(value, str):
            if INVOCATION and value == INVOCATION:
                return "<invocation>"
            if HEX32.match(value) or UUID.match(value):
                return "<instance>"
        return super().n(value)

    # --- git and the source repository ---------------------------------------------------------------
    def git(self, root, *args) -> str:
        done = subprocess.run(["git", "-c", "core.autocrlf=false", "-c", "core.eol=lf", "-c", "commit.gpgsign=false",
                               *args], cwd=str(root), env=self.git_env, capture_output=True, text=True, timeout=120)
        assert done.returncode == 0, done.stderr[-500:]
        return done.stdout.strip()

    def build_source(self, name: str) -> dict:
        """LABELLED: `<root>/<name>` with revisions A and B of SOURCE's code, pinned identity and dates."""
        root = self.base / name
        shutil.copytree(self.api.SOURCE_PACKAGE, root / "src" / "codex_harness",
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        (root / "uv.lock").write_bytes(LOCK)
        (root / "README.md").write_text("labelled fixture: not part of any runtime\n", encoding="utf-8")
        self.git(root, "init", "-q", "-b", "main")
        self.git(root, "add", "--all")
        self.git(root, "commit", "-q", "--no-verify", "-m", "labelled fixture revision A")
        first = self.git(root, "rev-parse", "HEAD")
        module = root / MODULE_PATH
        module.write_bytes(module.read_bytes() + MARKER.encode("utf-8"))
        self.git(root, "add", "--all")
        self.git(root, "commit", "-q", "--no-verify", "-m", "labelled fixture revision B")
        return {"root": root, "a": first, "b": self.git(root, "rev-parse", "HEAD")}

    def shared_source(self) -> dict:
        """Built once per run; a second build in another directory must give identical revisions."""
        if self.source is None:
            self.source = self.build_source("source")
            check = self.build_source("source-rebuild")
            assert (self.source["a"], self.source["b"]) == (check["a"], check["b"]), "a fixture revision varies"
            shutil.rmtree(check["root"])
        return self.source

    def git_state(self, root) -> tuple:
        return self.git(root, "rev-parse", "HEAD"), self.git(root, "status", "--porcelain")

    # --- targets, descriptors, receipts --------------------------------------------------------------
    def target(self, source=None, *, lock=LOCK_SHA, target_id=TARGET_ID, **overrides) -> dict:
        source = source or self.shared_source()["root"]
        entry = {"target_id": target_id, "kind": self.api.KIND_MANAGED, "root": str(self.case_dir / "managed"),
                 "state_dir": str(self.case_dir / ("state-" + target_id)), "service": "zeus-fleet",
                 "source": str(source), "python": PY, "environment_lock": lock, **overrides}
        target = self.api.validate_targets({"schema": self.api.REGISTRY_SCHEMA, "targets": [entry]})["targets"][0]
        self.live.append(target)
        return target

    def desc(self, target, label, revision, **overrides) -> dict:
        """A descriptor of the managed runtime of `revision`; its digest is labelled `label`."""
        source = self.shared_source()
        revision = source.get(revision, revision)
        image = self.api.runtime_image(target, dict(os.environ))
        document = {"schema": self.api.DESCRIPTOR_SCHEMA, "target_id": target["target_id"],
                    "root": self.api.managed_runtime_root(target, revision), "revision": revision,
                    "worker_image": image, "profile_digest": self.profile, "predecessor": None, **overrides}
        self.digests[self.api.descriptor_digest(document)] = label
        return document

    def digest(self, descriptor) -> str:
        return self.api.descriptor_digest(descriptor)

    def fleet(self, store=None):
        """LABELLED fixture authority of the activation gate: a registered in-memory Fleet."""
        authority = self.api.Fleet(store if store is not None else self.api.MemoryStore())
        authority.register(self.api.fixture_config(Path(Path.cwd().anchor) / "labelled-fixture"))
        return authority

    def host(self, *, fleet=None, **kwargs):
        return self.api.ManagedFleetTarget(workload="fixture", fleet=fleet if fleet is not None else self.fleet(),
                                           **kwargs)

    def state(self, target, name) -> Path:
        return Path(target["state_dir"]) / name

    def read(self, path):
        return json.loads(Path(path).read_text("utf-8"))

    def read_state(self, target, name):
        path = self.state(target, name)
        try:
            return json.loads(path.read_text("utf-8"))
        except (OSError, ValueError):
            return None

    def authority(self, descriptor, receipt, launch) -> dict:
        """What the coordinator would durably name as the instance this start may replace."""
        return {"descriptor_sha256": self.digest(descriptor), "instance_id": receipt["instance_id"],
                "launch": launch}

    # --- snapshots -----------------------------------------------------------------------------------
    def tree_identity(self, root: Path) -> dict:
        """A sealed tree by what is on disk: file count, modes, and one digest over every path, mode and blob."""
        rows, modes = [], {}
        for directory, _, names in os.walk(root):
            for name in names:
                path = Path(directory) / name
                mode = oct(stat.S_IMODE(path.lstat().st_mode))
                modes[mode] = modes.get(mode, 0) + 1
                rows.append(f"{path.relative_to(root).as_posix()}\t{mode}\t{blob_sha1(path.read_bytes())}")
        rows.sort()
        return {"files": len(rows), "modes": dict(sorted(modes.items())),
                "sha256": hashlib.sha256("\n".join(rows).encode()).hexdigest(),
                "top": sorted(entry.name for entry in root.iterdir())}

    def runtimes(self, target) -> dict:
        """The managed root's `runtimes` directory: each entry by name and identity."""
        directory = Path(target["root"]) / "runtimes"
        if not directory.is_dir():
            return {"runtimes": None}
        return {"runtimes": {entry.name: (self.tree_identity(entry) if entry.is_dir() else "<file>")
                             for entry in sorted(directory.iterdir())}}

    def state_listing(self, target) -> dict:
        """The state directory: each file with its normalized content; a journal by its event names."""
        out, directory = {}, Path(target["state_dir"])
        for path in sorted(directory.iterdir()) if directory.is_dir() else []:
            if path.is_dir():
                out[path.name] = sorted(entry.name for entry in path.iterdir())
                continue
            text = path.read_text(encoding="utf-8")
            if path.suffix == ".jsonl":
                events = [json.loads(line) for line in text.splitlines()]
                out[path.name] = {"events": [event.get("event") for event in events],
                                  "final_exit_code": events[-1].get("final_exit_code") if events else None}
                continue
            try:
                out[path.name] = self.n(json.loads(text))
            except ValueError:
                out[path.name] = {"text": self.n(text)}
        return out

    # --- processes -----------------------------------------------------------------------------------
    def pids(self, target) -> dict:
        launch, receipt = self.read_state(target, self.api.STATE_FILE), self.read_state(target, self.api.RECEIPT_FILE)
        return {"launcher": launch.get("pid") if isinstance(launch, dict) else None,
                "child": receipt.get("pid") if isinstance(receipt, dict) else None}

    def alive(self, target) -> dict:
        return {role: (None if pid is None else bool(self.api.alive(pid))) for role, pid in self.pids(target).items()}

    def proc_facts(self, pid) -> dict:
        """What a launched process really is, read from /proc: argv, cwd, stdio, group and the bound environment."""
        proc = Path(f"/proc/{pid}")
        try:
            environment = dict(item.split("=", 1) for item in (proc / "environ").read_bytes().decode().split("\0")
                               if "=" in item)
            facts = {"argv": (proc / "cmdline").read_bytes().decode().rstrip("\0").split("\0"),
                     "cwd": os.readlink(proc / "cwd"),
                     "stdio": [os.readlink(proc / "fd" / str(n)) for n in (0, 1, 2)],
                     "own_group": os.getpgid(pid) == pid,
                     "environment": {key: environment.get(key) for key in (
                         "PYTHONPATH", "PYTHONDONTWRITEBYTECODE", "PYTHONNOUSERSITE", "ZEUS_REPOSITORY",
                         "HARNESS_REPOSITORY")}}
        except OSError:
            return {"gone": True}
        return self.n(facts)

    def await_receipt(self, target, digest=None, timeout=60.0):
        def appeared():
            document = self.read_state(target, self.api.RECEIPT_FILE)
            return isinstance(document, dict) and (digest is None or document.get("descriptor_sha256") == digest)

        assert until(appeared, timeout), "the launched child wrote no startup receipt"
        return self.read_state(target, self.api.RECEIPT_FILE)

    def await_work(self, host, target, expected, *, require_paused=False, timeout=60.0):
        """The instance's OWN heartbeat verdict, waited for within a bound."""
        holder = []

        def reached():
            holder[:] = [host.work(target, require_paused=require_paused)]
            return holder[0]["state"] == expected

        assert until(reached, timeout), "heartbeat never reached " + expected + ": " + repr(holder)
        return holder[0]

    def start_live(self, host, target, desc, *, jobs=None, expected=None):
        """Seal, switch and start one real managed instance; returns its own startup receipt."""
        host.materialize(target, desc)
        if jobs is not None:
            self.state(target, self.api.FIXTURE_JOBS_FILE).parent.mkdir(parents=True, exist_ok=True)
            self.state(target, self.api.FIXTURE_JOBS_FILE).write_text(json.dumps(jobs), encoding="utf-8")
        host.switch(target, desc, expected=expected)
        host.start(target, desc)
        return self.await_receipt(target, self.digest(desc))

    def release_jobs(self, target):
        jobs = self.state(target, self.api.FIXTURE_JOBS_FILE)
        for job in (self.read(jobs) if jobs.exists() else []):
            (self.state(target, "fixture") / ("release-" + job)).touch()

    def end_tree(self, pid):
        """Test cleanup only: SIGTERM reaches the incumbent `run_owned` owner, which reclaims its whole tree."""
        os.kill(pid, signal.SIGTERM)

    def teardown(self, target):
        """Test cleanup only: release every fixture job, then end the owned launcher tree (never the target's
        own stop path, which sends no signal)."""
        self.release_jobs(target)
        pids = self.pids(target)
        pid, child = pids["launcher"], pids["child"]
        if pid is not None and self.api.alive(pid):
            self.end_tree(pid)
        until(lambda: not ((pid is not None and self.api.alive(pid)) or (child is not None
                                                                         and self.api.alive(child))), 20)
        survivors = [p for p in (pid, child) if p is not None and self.api.alive(p)]
        for survivor in survivors:
            self.end_tree(survivor)
        assert not survivors, survivors

    def sweep(self, case: str) -> int:
        """Fail the run on any process still mentioning this case's directory, after ending it."""
        leaked = procs_mentioning(str(self.case_dir))
        for pid in leaked:
            with contextlib.suppress(OSError):
                os.kill(pid, signal.SIGKILL)
        for pid in leaked:
            until(lambda pid=pid: not proc_alive(pid), 30)
        assert not leaked, f"case {case} left live children"
        return len(leaked)


def fault_store(api):
    """LABELLED fault injection over the side's real `MemoryStore` (tests/test_fleet.py `FaultStore`): each armed
    fault fires once - `scan_faults` on the next scan of a bucket, `put_faults` on the next write, `lost_acks`
    raises after a commit that DID happen."""

    class FaultTransaction:
        def __init__(self, store, tx):
            self.store, self.tx = store, tx

        def scan(self, bucket):
            if bucket in self.store.scan_faults:
                self.store.scan_faults.discard(bucket)
                raise ConnectionError("labelled injected failed debt read: " + bucket)
            return self.tx.scan(bucket)

        def put(self, bucket, key, body):
            if bucket in self.store.put_faults:
                self.store.put_faults.discard(bucket)
                raise ConnectionError("labelled injected failed write: " + bucket)
            return self.tx.put(bucket, key, body)

        def __getattr__(self, name):
            return getattr(self.tx, name)

    class FaultStore(api.MemoryStore):
        def __init__(self):
            super().__init__()
            self.scan_faults, self.put_faults, self.lost_acks = set(), set(), 0

        @contextlib.contextmanager
        def transaction(self):
            with super().transaction() as tx:
                yield FaultTransaction(self, tx)
            if self.lost_acks:
                self.lost_acks -= 1
                raise ConnectionError("labelled injected lost commit acknowledgement")

    return FaultStore()


class UnreachableStore:
    """Labelled injected fault: the Fleet authority's store refuses every transaction."""

    def transaction(self):
        raise ConnectionError("labelled injected unreachable Fleet store")


class AnswerFleet:
    """LABELLED Fleet authority whose `activation_gate` answers a fixed document or raises."""

    def __init__(self, answer):
        self.answer = answer

    def activation_gate(self, target_id, descriptor_sha256):
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


def control_row(api, authority):
    with authority.store.transaction() as tx:
        return tx.get(api.BUCKET_CONTROL, api.CONTROL_KEY)


# ======================================================================================================
# 1. seal
# ======================================================================================================
def case_seal_once_and_revalidate(fx):
    api, source = fx.api, fx.shared_source()
    target, out = fx.target(), {}
    before = fx.git_state(source["root"])
    first = fx.desc(target, "seal_once.A", "a")
    sealed = api.Materializer(target).materialize(first)
    root = Path(first["root"])
    manifest = api.validate_manifest(fx.read(root / api.MANIFEST_FILE))
    listed = [path for path, _ in fx.read(root / api.LISTING_FILE)]
    out["sealed"] = sealed
    out["manifest"] = manifest
    out["tree_is_the_git_tree"] = manifest["tree"] == fx.git(source["root"], "rev-parse", source["a"] + "^{tree}")
    out["listing"] = {"files": len(listed), "has_uv_lock": "uv.lock" in listed, "has_readme": "README.md" in listed,
                      "only_src_and_lock": all(path == "uv.lock" or path.startswith("src/") for path in listed)}
    out["runtime_revision"] = api.runtime_revision(root)
    out["modes"] = {"module": oct(stat.S_IMODE((root / MODULE_PATH).stat().st_mode)),
                    "manifest": oct(stat.S_IMODE((root / api.MANIFEST_FILE).stat().st_mode))}
    mtime = (root / api.MANIFEST_FILE).stat().st_mtime_ns
    again = api.Materializer(target).materialize(first)
    out["revalidated"] = {"result": again, "manifest_unchanged": (root / api.MANIFEST_FILE).stat().st_mtime_ns == mtime,
                          "same_manifest_digest": again["manifest_sha256"] == sealed["manifest_sha256"]}
    second = fx.desc(target, "seal_once.B", "b")
    other = api.Materializer(target).materialize(second)
    out["second_revision"] = {"result": other, "different_manifest": other["manifest_sha256"] != sealed["manifest_sha256"],
                              "marker_in_b": MARKER in (Path(second["root"]) / MODULE_PATH).read_text("utf-8"),
                              "marker_in_a": MARKER in (root / MODULE_PATH).read_text("utf-8"),
                              "first_still_verifies": api.Materializer(target).verify(first)["revision"]}
    out["source_unchanged"] = fx.git_state(source["root"]) == before
    out["managed_root"] = fx.runtimes(target)
    return fx.n(out)


def case_interrupted_seal(fx):
    api = fx.api
    target, out = fx.target(), {}
    desc = fx.desc(target, "interrupted.A", "a")

    def interrupted(src, dst):
        raise OSError("labelled injected interruption between stage and seal")

    with mock.patch.object(os, "rename", interrupted):
        out["interrupted"] = fx.attempt(lambda: api.Materializer(target).materialize(desc))
    out["after_interruption"] = {**fx.runtimes(target), "sealed_directory_exists": Path(desc["root"]).exists()}
    out["verify_unsealed"] = fx.attempt(lambda: api.Materializer(target).verify(desc))
    out["retry"] = fx.attempt(lambda: api.Materializer(target).materialize(desc))
    out["after_retry"] = fx.runtimes(target)
    out["verify_sealed"] = fx.attempt(lambda: api.Materializer(target).verify(desc))
    return fx.n(out)


def case_lost_response(fx):
    api = fx.api

    class LostMaterializeResponse(api.ManagedFleetTarget):
        """Labelled injection: the first seal HAPPENS, and then its response is lost."""

        lost = 1

        def materialize(self, target, descriptor, *, authorize=None):
            sealed = super().materialize(target, descriptor, authorize=authorize)
            if self.lost:
                self.lost -= 1
                raise RuntimeError("labelled injected lost materialize response")
            return sealed

    target, out = fx.target(), {}
    desc = fx.desc(target, "lost.A", "a")
    host = LostMaterializeResponse(workload="fixture")
    out["first"] = fx.attempt(lambda: host.materialize(target, desc))
    out["after_first"] = fx.runtimes(target)
    out["second"] = fx.attempt(lambda: host.materialize(target, desc))
    out["after_second"] = fx.runtimes(target)
    out["verify"] = fx.attempt(lambda: host.verify(target, desc))
    out["paths_in_result"] = str(fx.case_dir) in json.dumps(out["second"])
    return fx.n(out)


def case_linked_worktree(fx):
    api = fx.api
    repository = fx.build_source("linked-source")
    worktree = fx.case_dir / "linked-worktree"
    worktree.parent.mkdir(parents=True, exist_ok=True)
    fx.git(repository["root"], "worktree", "add", "-q", "-b", "fixture-linked", str(worktree), repository["a"])
    target = fx.target(worktree)
    out = {"worktree_checkout_revision_is_a": api.checkout_revision(worktree) == repository["a"],
           "source_checkout_revision_is_b": api.checkout_revision(repository["root"]) == repository["b"],
           "revisions": {"a": repository["a"], "b": repository["b"]}}
    desc = fx.desc(target, "linked.B", repository["b"])
    out["sealed"] = fx.attempt(lambda: api.Materializer(target).materialize(desc))
    return fx.n(out)


# ======================================================================================================
# 2. refuse
# ======================================================================================================
def case_changed_or_foreign(fx):
    api, source = fx.api, fx.shared_source()
    target, out = fx.target(), {}
    desc = fx.desc(target, "changed.A", "a")
    api.Materializer(target).materialize(desc)
    module = Path(desc["root"]) / MODULE_PATH
    module.chmod(0o644)
    module.write_bytes(module.read_bytes() + b"# labelled injected tampering\n")
    out["verify"] = fx.attempt(lambda: api.Materializer(target).verify(desc))
    out["materialize"] = fx.attempt(lambda: api.Materializer(target).materialize(desc))
    out["nothing_overwritten"] = module.read_bytes().endswith(b"# labelled injected tampering\n")
    foreign = Path(api.managed_runtime_root(target, source["b"]))
    foreign.mkdir(parents=True)
    (foreign / "owner-file.txt").write_text("labelled unowned evidence", encoding="utf-8")
    out["foreign"] = fx.attempt(lambda: api.Materializer(target).materialize(fx.desc(target, "changed.B", "b")))
    out["foreign_listing"] = sorted(entry.name for entry in foreign.iterdir())
    return fx.n(out)


def case_unresolved_or_unqualified(fx):
    api = fx.api
    target, out = fx.target(), {}
    out["unresolved"] = fx.attempt(lambda: api.Materializer(target).materialize(fx.desc(target, "unres.0", "0" * 40)))
    requalified = fx.target(lock="9" * 64)
    desc = fx.desc(requalified, "unqual.A", "a")
    out["unqualified"] = fx.attempt(lambda: api.Materializer(requalified).materialize(desc))
    runtimes = Path(target["root"]) / "runtimes"
    out["nothing_written"] = not runtimes.exists() or list(runtimes.iterdir()) == []
    host = fx.host()
    out["unqualified_through_target"] = fx.attempt(lambda: host.materialize(requalified, desc))
    out["state_dir_created"] = Path(target["state_dir"]).exists()
    return fx.n(out)


def case_tracked_symlink_and_fence(fx):
    api = fx.api
    root = fx.base / "symlink-source"
    (root / "src").mkdir(parents=True)
    (root / "src" / "a.py").write_bytes(b"x = 1\n")
    (root / "src" / "link.py").symlink_to("a.py")
    (root / "uv.lock").write_bytes(LOCK)
    fx.git(root, "init", "-q", "-b", "main")
    fx.git(root, "add", "--all")
    fx.git(root, "commit", "-q", "--no-verify", "-m", "labelled fixture: a tracked symlink")
    revision = fx.git(root, "rev-parse", "HEAD")
    target, out = fx.target(root), {}
    desc = fx.desc(target, "symlink.A", revision)
    out["tracked_symlink"] = fx.attempt(lambda: api.Materializer(target).materialize(desc))
    out["nothing_written"] = not (Path(target["root"]) / "runtimes").exists()
    # The fence runs before anything is sealed: a superseded controller writes nothing.
    other = fx.target(fx.shared_source()["root"], target_id="fenced-target")
    fenced = fx.desc(other, "fence.A", "a")

    def lost_fence():
        raise api.DeliveryRefused("owner_fence_lost", "authorize")

    out["fence"] = fx.attempt(lambda: fx.host().materialize(other, fenced, authorize=lost_fence))
    out["fence_wrote_nothing"] = not (Path(other["root"]) / "runtimes").exists()
    return fx.n(out)


def case_target_registry(fx):
    api = fx.api
    source = fx.shared_source()["root"]
    target, out = fx.target(), {}
    out["managed"] = {"kind": target["kind"], "environment_lock": target["environment_lock"] == LOCK_SHA,
                      "owner_fields": api.owner_target(target)}
    legacy = {"target_id": "legacy", "kind": "process", "root": str(fx.case_dir / "legacy"),
              "state_dir": str(fx.case_dir / "legacy-state"), "service": "svc"}
    registry = {"schema": api.REGISTRY_SCHEMA, "targets": [legacy]}
    out["legacy_unchanged"] = api.validate_targets(registry)["targets"][0] == legacy
    out["legacy_with_source"] = fx.attempt(lambda: api.validate_targets(
        {"schema": api.REGISTRY_SCHEMA, "targets": [{**legacy, "source": str(source)}]}))
    refusals = {"bad_lock": {"environment_lock": "not-a-digest"}, "bare_python": {"python": "python3"},
                "root_in_source": {"root": str(source / "managed")},
                "state_in_root": {"state_dir": str(fx.case_dir / "managed" / "state")},
                "source_is_state": {"source": str(fx.case_dir / ("state-" + TARGET_ID))}}
    out["refusals"] = {}
    for name, overrides in refusals.items():
        result = fx.attempt(lambda o=overrides: fx.target(**o))
        out["refusals"][name] = {**result, "names_no_root": str(fx.case_dir) not in json.dumps(result)
                                 if "raised" in result else None}
    out["host_ports_managed"] = {"is_managed_target": isinstance(api.host_ports()[api.KIND_MANAGED],
                                                                 api.ManagedFleetTarget),
                                 "fleet": api.host_ports()[api.KIND_MANAGED].fleet}
    return fx.n(out)


def case_runtime_path(fx):
    api, source = fx.api, fx.shared_source()
    target, out = fx.target(), {}
    good = fx.desc(target, "path.A", "a")
    out["good"] = api.same_path(api.check_runtime_path(target, good), good["root"])
    foreign = {"source_checkout": str(source["root"]), "other_revision": api.managed_runtime_root(target, source["b"]),
               "stage_directory": str(Path(target["root"]) / "runtimes" / (api.STAGE_PREFIX + source["a"] + "-x")),
               "another_root": str(fx.case_dir / "elsewhere" / "runtimes" / source["a"]),
               "managed_root": target["root"]}
    out["foreign"] = {name: fx.attempt(lambda r=root: api.check_runtime_path(target, {**good, "root": r}))
                      for name, root in foreign.items()}
    out["other_target"] = fx.attempt(lambda: api.check_runtime_path(target, {**good, "target_id": "another-target"}))
    return fx.n(out)


def case_bad_runtime(fx):
    api, source = fx.api, fx.shared_source()
    target, host, out = fx.target(), fx.host(), {}
    good = fx.desc(target, "bad.A", "a")
    receipt = fx.start_live(host, target, good)
    launch = fx.read_state(target, api.STATE_FILE)
    api.Materializer(target).materialize(fx.desc(target, "bad.B", "b"))
    tampered = Path(target["root"]) / "runtimes" / source["b"] / "src" / "codex_harness" / "extra.py"
    cases = [("foreign_path", fx.desc(target, "bad.foreign", "a", root=str(source["root"]))),
             ("unsealed_revision", fx.desc(target, "bad.unsealed", "0" * 40)),
             ("image_mismatch", fx.desc(target, "bad.image", "a", worker_image="another-image")),
             ("tampered_runtime", fx.desc(target, "bad.tampered", "b"))]
    tampered.write_text("# labelled injected foreign file\n", encoding="utf-8")
    current, out["cases"] = good, {}
    for name, bad in cases:
        host.switch(target, bad, expected=fx.digest(current))
        current = bad
        refused = fx.attempt(lambda b=bad: host.start(
            target, b, authorize=lambda: None,
            replaces={"descriptor_sha256": fx.digest(good), "instance_id": receipt["instance_id"], "launch": launch}))
        out["cases"][name] = {"result": refused, "running": host.running(target),
                              "launch_unchanged": fx.read_state(target, api.STATE_FILE) == launch,
                              "receipt_unchanged": fx.read_state(target, api.RECEIPT_FILE) == receipt,
                              "stop_requested": fx.state(target, "stop.json").exists()}
    out["alive"] = fx.alive(target)
    return fx.n(out)


# ======================================================================================================
# 3. launch
# ======================================================================================================
def case_clean_start_restart_repeat(fx):
    api = fx.api
    target, host, out = fx.target(), fx.host(), {}
    desc = fx.desc(target, "clean.A", "a")
    receipt = fx.start_live(host, target, desc)
    verdict = api.consumption_verdict(desc, receipt)
    out["consumed"] = {"consumed": verdict["consumed"], "reason_code": verdict["reason_code"]}
    out["receipt"] = {"runtime_root_is_sealed": api.same_path(receipt["runtime_root"], desc["root"]),
                      "module_root_within": api.within_path(receipt["module_root"], desc["root"]),
                      "revision_is_a": receipt["revision"] == fx.shared_source()["a"], "record": receipt}
    out["target_file"] = fx.read_state(target, api.TARGET_FILE)
    fx.await_work(host, target, "idle")
    first = fx.read_state(target, api.STATE_FILE)
    pids = fx.pids(target)
    out["launcher"], out["child"] = fx.proc_facts(pids["launcher"]), fx.proc_facts(pids["child"])
    mentioning = procs_mentioning(target["state_dir"])
    out["processes"] = {"mentioning_the_state_dir": len(mentioning),
                        "entry": sum(1 for p in mentioning if b"\0entry\0" in Path(f"/proc/{p}/cmdline").read_bytes()),
                        "launch": sum(1 for p in mentioning
                                      if b"\0launch\0" in Path(f"/proc/{p}/cmdline").read_bytes())}
    out["alive_after_start"] = fx.alive(target)
    out["state_dir_running"] = fx.state_listing(target)
    again = fx.attempt(lambda: fx.host(fleet=host.fleet).start(target, desc))
    out["repeated_start"] = {"result": again, "launch_unchanged": fx.read_state(target, api.STATE_FILE) == first}
    stopped = host.stop(target)
    out["stop"] = {"result": stopped, "alive": fx.alive(target)}
    out["journal_after_stop"] = fx.state_listing(target)["launcher-journal.jsonl"]
    restarted = host.start(target, desc)
    fresh = fx.await_receipt(target, fx.digest(desc))
    until(lambda: fresh["instance_id"] != receipt["instance_id"] or fx.read_state(
        target, api.RECEIPT_FILE)["instance_id"] != receipt["instance_id"], 60)
    fresh = fx.read_state(target, api.RECEIPT_FILE)
    out["restart"] = {"started": restarted["started"], "new_launcher": restarted["pid"] != first["pid"],
                      "new_instance": fresh["instance_id"] != receipt["instance_id"],
                      "consumed": api.consumption_verdict(desc, fresh)["consumed"],
                      "revision_is_a": fresh["revision"] == fx.shared_source()["a"],
                      "alive": fx.alive(target), "launch": fx.read_state(target, api.STATE_FILE)}
    out["runtime_dirs"] = fx.runtimes(target)
    return fx.n(out)


def case_killed_launcher(fx):
    api = fx.api
    target, host, out = fx.target(), fx.host(), {}
    desc = fx.desc(target, "killed.A", "a")
    receipt = fx.start_live(host, target, desc)
    fx.await_work(host, target, "idle")
    launcher = fx.read_state(target, api.STATE_FILE)["pid"]
    os.kill(launcher, signal.SIGKILL)  # labelled injected outright kill of the owner
    until(lambda: not api.alive(launcher), 10)
    out["after_kill"] = {"alive": fx.alive(target), "running": host.running(target)}
    drained = host.drain(target)
    out["drain_running"] = {"running": drained["running"]}
    out["paused_idle"] = fx.await_work(host, target, "idle", require_paused=True)
    out["drain_settled"] = host.drain(target)["drained"]
    stopped = host.stop(target)
    out["stop"] = {"result": stopped, "child_alive": bool(api.alive(receipt["pid"]))}
    return fx.n(out)


def case_two_owners(fx):
    api = fx.api
    target = fx.target()
    desc = fx.desc(target, "owners.A", "a")
    authority = fx.fleet()
    owners = [fx.host(fleet=authority), fx.host(fleet=authority)]
    owners[0].materialize(target, desc)
    owners[0].switch(target, desc, expected=None)
    barrier, results = threading.Barrier(2), []

    def start(owner):
        barrier.wait()
        try:
            results.append(owner.start(target, desc))
        except api.DeliveryRefused as exc:
            results.append({"started": False, "refused": exc.reason_code})

    threads = [threading.Thread(target=start, args=(owner,)) for owner in owners]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(120)
    started = sorted(bool(result.get("started")) for result in results)
    loser = next(result for result in results if not result.get("started"))
    winner = next(result for result in results if result.get("started"))
    allowed = ["instance_unidentified", "recovered", "target_lock_held"]
    observed = "recovered" if loser.get("recovered") else loser.get("refused")
    receipt = fx.await_receipt(target, fx.digest(desc))
    return fx.n({"started": started, "loser_outcome_is_one_of": allowed, "loser_outcome_allowed": observed in allowed,
                 "winner_is_the_launch_record": fx.read_state(target, api.STATE_FILE)["pid"] == winner["pid"],
                 "consumed": api.consumption_verdict(desc, receipt)["consumed"],
                 "entry_runtimes": sum(1 for p in procs_mentioning(target["state_dir"])
                                       if b"\0entry\0" in Path(f"/proc/{p}/cmdline").read_bytes()),
                 "alive": fx.alive(target), "launch": fx.read_state(target, api.STATE_FILE)})


def prepared_state(fx, tag):
    """A target with a sealed runtime A, its descriptor and its owner registry file, and no instance."""
    api = fx.api
    target = fx.target()
    desc = fx.desc(target, tag + ".A", "a")
    fx.host().materialize(target, desc)
    fx.host().switch(target, desc, expected=None)
    Path(target["state_dir"]).mkdir(parents=True, exist_ok=True)
    fx.state(target, api.TARGET_FILE).write_text(json.dumps(api.owner_target(target), sort_keys=True),
                                                 encoding="utf-8")
    return target, desc


def case_entry_and_launch_refusals(fx):
    api = fx.api
    out = {}
    target, desc = prepared_state(fx, "entry")
    state_dir = target["state_dir"]
    out["entry_unknown_workload"] = api.entry(state_dir, "no-such-workload")
    empty = fx.case_dir / "empty-state"
    empty.mkdir()
    out["entry_no_descriptor"] = api.entry(str(empty), "fixture")
    out["exit_refused"] = api.EXIT_REFUSED
    digest = fx.digest(desc)
    out["launch"] = {
        "no_files": api.launch(str(empty), digest, "fixture"),
        "unknown_workload": api.launch(state_dir, digest, "no-such-workload"),
        "digest_mismatch": api.launch(state_dir, "f" * 64, "fixture"),
    }
    moved = fx.case_dir / "moved-state"
    shutil.copytree(state_dir, moved)
    out["launch"]["state_dir_not_the_targets"] = api.launch(str(moved), digest, "fixture")
    # An unqualified environment is refused the same way, before anything is started.
    fx.state(target, api.TARGET_FILE).write_text(
        json.dumps({**api.owner_target(target), "environment_lock": "9" * 64}, sort_keys=True), encoding="utf-8")
    out["launch"]["environment_unqualified"] = api.launch(state_dir, digest, "fixture")
    fx.state(target, api.TARGET_FILE).write_text(json.dumps(api.owner_target(target), sort_keys=True),
                                                 encoding="utf-8")
    shutil.rmtree(Path(target["root"]) / "runtimes" / fx.shared_source()["a"])
    out["launch"]["runtime_unsealed"] = api.launch(state_dir, digest, "fixture")
    out["state_dir_files"] = sorted(entry.name for entry in Path(state_dir).iterdir())
    out["run_fleet"] = {"unreachable": "run_fleet builds the host bootstrap over the real PostgreSQL store and "
                                       "Redis; no real store exists in the compare environment"}
    return fx.n(out)


def case_runtime_control_and_fixture(fx):
    from datetime import datetime, timezone

    api = fx.api
    state = fx.case_dir / "control-state"
    state.mkdir(parents=True)
    receipt = {"schema": api.RECEIPT_SCHEMA, "target_id": TARGET_ID, "instance_id": "1" * 32, "pid": 4242,
               "started_at": "2026-09-23T00:00:00+00:00", "runtime_root": "/managed/runtimes/x",
               "module_root": "/managed/runtimes/x/src/codex_harness", "descriptor_sha256": "d" * 64,
               "revision": "a" * 40, "worker_image": "none", "profile_digest": "e" * 64}
    control, out = api.RuntimeControl(state, receipt), {}
    out["open"] = {"admission_open": control.admission_open(), "stop_requested": control.stop_requested(),
                   "activation_is_the_receipts": control.activation() == receipt["descriptor_sha256"]}
    (state / (api.PAUSE_FILE + ".json")).write_text("{ unreadable", encoding="utf-8")  # an unknown pause is a pause
    out["paused_unreadable"] = control.admission_open()
    (state / (api.STOP_FILE + ".json")).write_text("{}", encoding="utf-8")
    out["stop_requested"] = control.stop_requested()
    control.heartbeat({"admission": "paused", "active": 2, "unresolved": 1})
    out["heartbeat"] = fx.read(state / "heartbeat.json")
    out["heartbeat_verdict"] = api.work_verdict(out["heartbeat"], receipt, now=datetime.now(timezone.utc), require_paused=True)
    # The fixture workload in this process: the stop request is already there, so the runner stops at once.
    (state / api.FIXTURE_JOBS_FILE).write_text(json.dumps(["job-q"]), encoding="utf-8")
    summary = api.run_fixture(state, control)
    out["run_fixture"] = {"summary": summary, "files": sorted(entry.name for entry in state.iterdir()),
                          "fixture_dir": sorted(entry.name for entry in (state / "fixture").iterdir()),
                          "heartbeat_after": fx.read(state / "heartbeat.json")}
    # The fixture launcher: a real child waiting for its release marker.
    root = fx.case_dir / "launcher-root"
    root.mkdir()
    launcher = api.FixtureLauncher(root)
    handle = launcher.launch({"id": "job-w"})
    out["fixture_launcher"] = {"budget_exhausted": launcher.budget_exhausted({}),
                               "handle_keys": sorted(handle), "finished_before_release": len(
                                   launcher.wait([handle], 0.2))}
    (root / "release-job-w").touch()
    done = launcher.wait([handle], 30)
    out["fixture_launcher"]["finished_after_release"] = len(done)
    out["fixture_launcher"]["outcome"] = launcher.outcome(handle, {"id": "job-w"})
    out["fixture_launcher"]["listing"] = sorted(entry.name for entry in root.iterdir())
    crashed = launcher.launch({"id": "job-x"})
    crashed["process"].kill()
    crashed["process"].wait(30)
    out["fixture_launcher"]["killed_outcome"] = launcher.outcome(crashed, {"id": "job-x"})
    # The fixture's labelled configuration and manifest.
    config = api.fixture_config(Path("/labelled-root"))
    out["fixture_config"] = config
    manifest = api.fixture_manifest("job-m")
    out["fixture_manifest"] = {"id": manifest["id"], "keys": sorted(manifest),
                               "sha256": hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()}
    return fx.n(out)


# ======================================================================================================
# 4. drain_stop
# ======================================================================================================
def case_active_work(fx):
    api = fx.api
    target, host, out = fx.target(), fx.host(stop_timeout=1.0), {}
    good = fx.desc(target, "active.A", "a")
    receipt = fx.start_live(host, target, good, jobs=["job-1"])
    out["busy"] = fx.await_work(host, target, "busy")
    drained = host.drain(target)
    out["drain"] = drained
    stopped = host.stop(target)
    out["stop"] = {"result": stopped, "running": host.running(target),
                   "stop_file": fx.state(target, "stop.json").exists()}
    successor = fx.desc(target, "active.B", "b", predecessor=fx.digest(good))
    host.materialize(target, successor)
    host.switch(target, successor, expected=fx.digest(good))
    out["replacement"] = {"result": fx.attempt(lambda: host.start(
        target, successor, authorize=lambda: None,
        replaces={"descriptor_sha256": fx.digest(good), "instance_id": receipt["instance_id"],
                  "launch": fx.read_state(target, api.STATE_FILE)})),
        "receipt_unchanged": fx.read_state(target, api.RECEIPT_FILE) == receipt, "running": host.running(target)}
    out["alive_while_busy"] = fx.alive(target)
    fx.release_jobs(target)
    out["idle_after_release"] = fx.await_work(host, target, "idle", require_paused=True)
    out["drain_after_release"] = host.drain(target)
    stopped = host.stop(target)
    out["stop_after_release"] = {"result": stopped, "alive": fx.alive(target)}
    return fx.n(out)


def case_unavailable_heartbeat(fx):
    api = fx.api
    target, host, out = fx.target(), fx.host(), {}
    desc = fx.desc(target, "hb.A", "a")
    receipt = fx.start_live(host, target, desc)
    fx.await_work(host, target, "idle")
    strict = fx.host(fleet=host.fleet, heartbeat_max_age=0.0, stop_timeout=0.5)
    time.sleep(0.05)
    drained = strict.drain(target)
    out["strict_drain"] = {"drained": drained["drained"], "unconfirmed": drained["unconfirmed"],
                           "reason_is_stale_or_future": drained["work"]["reason_code"] in {"heartbeat_stale",
                                                                                           "heartbeat_future"}}
    refused = strict.stop(target)
    out["strict_stop"] = {"stopped": refused["stopped"], "reason_code": refused["reason_code"],
                          "work_state": refused["work"]["state"]}
    fx.state(target, api.RECEIPT_FILE).unlink()  # labelled injected loss of the receipt
    out["receipt_lost"] = {"work": host.work(target, require_paused=True), "drain": host.drain(target)["unconfirmed"],
                           "running": host.running(target)}
    fx.state(target, api.RECEIPT_FILE).write_text(json.dumps(receipt), encoding="utf-8")
    out["receipt_restored"] = host.drain(target)["drained"]
    return fx.n(out)


def case_heartbeat_verdict(fx):
    api = fx.api
    from datetime import datetime, timedelta, timezone

    now = datetime(2026, 9, 23, tzinfo=timezone.utc)
    receipt = {"schema": api.RECEIPT_SCHEMA, "target_id": TARGET_ID, "instance_id": "1" * 32, "pid": 4242,
               "started_at": "2026-09-23T00:00:00+00:00", "runtime_root": "/managed/runtimes/x",
               "module_root": "/managed/runtimes/x/src/codex_harness", "descriptor_sha256": "d" * 64,
               "revision": "a" * 40, "worker_image": "none", "profile_digest": "e" * 64}
    beat = {"schema": api.HEARTBEAT_SCHEMA, "instance_id": "1" * 32, "descriptor_sha256": "d" * 64, "pid": 4242,
            "at": now.isoformat(), "admission": "paused", "active": 0, "unresolved": 0}
    rows = [("missing", None, receipt), ("unreadable", "unreadable", receipt), ("extra_field", {**beat, "extra": 1}, receipt),
            ("negative_count", {**beat, "active": -1}, receipt),
            ("other_instance", {**beat, "instance_id": "2" * 32}, receipt),
            ("other_descriptor", {**beat, "descriptor_sha256": "f" * 64}, receipt),
            ("other_pid", {**beat, "pid": 1}, receipt),
            ("stale", {**beat, "at": (now - timedelta(seconds=31)).isoformat()}, receipt),
            ("future", {**beat, "at": (now + timedelta(seconds=60)).isoformat()}, receipt),
            ("not_a_time", {**beat, "at": "yesterday"}, receipt), ("no_receipt", beat, None),
            ("receipt_unreadable", beat, {**receipt, "pid": "x"})]
    out = {"unknown": {name: api.work_verdict(heartbeat, owner, now=now, require_paused=True)
                       for name, heartbeat, owner in rows}}
    out["busy"] = {"active": api.work_verdict({**beat, "active": 2}, receipt, now=now),
                   "unresolved": api.work_verdict({**beat, "unresolved": 1}, receipt, now=now),
                   "pause_unacknowledged": api.work_verdict({**beat, "admission": "open"}, receipt, now=now,
                                                            require_paused=True)}
    out["idle"] = {"open_without_pause_required": api.work_verdict({**beat, "admission": "open"}, receipt, now=now),
                   "paused": api.work_verdict(beat, receipt, now=now, require_paused=True)}
    return fx.n(out)


def case_not_running(fx):
    target, host = fx.target(), fx.host()
    desc = fx.desc(target, "idle.A", "a")
    host.materialize(target, desc)
    host.switch(target, desc, expected=None)
    return fx.n({"drain": host.drain(target), "stop": host.stop(target), "running": host.running(target),
                 "state_dir": fx.state_listing(target)})


# ======================================================================================================
# 5. gate
# ======================================================================================================
def case_first_start_reads(fx):
    api = fx.api
    target, out = fx.target(), {"buckets": {}}
    desc = fx.desc(target, "first.A", "a")
    setup = fx.host()
    setup.materialize(target, desc)
    setup.switch(target, desc, expected=None)
    for bucket in (api.BUCKET_JOBS, api.BUCKET_UNITS):
        authority = fx.fleet(fault_store(api))
        host = fx.host(fleet=authority)
        before = control_row(api, authority)["paused"]
        authority.store.scan_faults.add(bucket)  # LABELLED injected failure of the first debt read
        refused = fx.attempt(lambda: host.start(target, desc))
        row = control_row(api, authority)
        gap = fx.attempt(lambda: api.Fleet(authority.store).reserve_unit(UNIT, api.UNIT_CONDUCTOR, "fixture",
                                                                         "labelled-gap"))
        out["buckets"][bucket] = {"paused_before": before, "result": refused,
                                  "launch_record": fx.state(target, api.STATE_FILE).exists(), "running": host.running(target),
                                  "control": row, "hold_is_this_descriptor": row[api.ACTIVATION_HOLD][
                                      "descriptor_sha256"] == fx.digest(desc), "reservation": gap}
    authority = fx.fleet(fault_store(api))
    authority.store.put_faults.add(api.BUCKET_CONTROL)  # LABELLED injected failed pause write
    refused = fx.attempt(lambda: fx.host(fleet=authority).start(target, desc))
    out["pause_write_fails"] = {"result": refused, "paused": control_row(api, authority)["paused"],
                                "launch_record": fx.state(target, api.STATE_FILE).exists()}
    authority.store.lost_acks = 1  # LABELLED injected lost acknowledgement of a committed pause
    refused = fx.attempt(lambda: fx.host(fleet=authority).start(target, desc))
    row = control_row(api, authority)
    out["lost_acknowledgement"] = {"result": refused, "hold_is_this_descriptor": row[api.ACTIVATION_HOLD][
        "descriptor_sha256"] == fx.digest(desc), "launch_record": fx.state(target, api.STATE_FILE).exists(),
        "running": fx.host(fleet=authority).running(target)}
    out["state_dir"] = fx.state_listing(target)
    return fx.n(out)


def case_no_authority(fx):
    api = fx.api
    target, out = fx.target(), {}
    host = api.ManagedFleetTarget(workload="fixture")  # no authority: never read as "no debt"
    desc = fx.desc(target, "noauth.A", "a")
    host.materialize(target, desc)
    host.switch(target, desc, expected=None)
    out["start"] = fx.attempt(lambda: host.start(target, desc))
    out["launch_record"] = fx.state(target, api.STATE_FILE).exists()
    out["running"] = host.running(target)
    out["default_port_fleet"] = api.host_ports()[api.KIND_MANAGED].fleet
    out["unknown_workload"] = fx.attempt(lambda: api.ManagedFleetTarget(workload="no-such-workload"))
    out["coordinator_wiring"] = {"unreachable": "controller() needs the HostDelivery coordinator and the "
                                                "organization bootstrap: the stages family"}
    return fx.n(out)


def case_gate_answers(fx):
    api = fx.api
    target = fx.target()
    desc = fx.desc(target, "answers.A", "a")
    setup = fx.host()
    setup.materialize(target, desc)
    setup.switch(target, desc, expected=None)
    answers = {"debt_unknown": {"reason_code": "debt_unknown", "paused": True, "settled": False},
               "control_changed": {"reason_code": "control_changed", "paused": False, "settled": False},
               "not_paused": {"paused": False, "settled": True}, "not_settled": {"paused": True, "settled": False},
               "settled_is_unknown": {"paused": True, "settled": None}, "empty": {},
               "raises": ConnectionError("labelled injected unreachable authority")}
    out = {"through_start": {}, "gate_refusal": {}}
    for name, answer in answers.items():
        host = fx.host(fleet=AnswerFleet(answer))
        out["through_start"][name] = {"result": fx.attempt(lambda h=host: h.start(target, desc)),
                                      "launch_record": fx.state(target, api.STATE_FILE).exists()}
        if not isinstance(answer, Exception):
            out["gate_refusal"][name] = api.gate_refusal(answer)
    out["gate_refusal"]["settled_and_paused"] = api.gate_refusal({"paused": True, "settled": True})
    request = {"schema": api.LAUNCH_REQUEST_SCHEMA, "target_id": TARGET_ID, "descriptor_sha256": "a" * 64,
               "manifest_sha256": "b" * 64, "workload": "fixture", "requested_at": "2026-09-23T00:00:00+00:00"}
    rows = {"valid": request, "missing_field": {k: v for k, v in request.items() if k != "requested_at"},
            "extra_field": {**request, "argv": ["sh"]}, "other_schema": {**request, "schema": "urn:other"},
            "unknown_workload": {**request, "workload": "shell"},
            "bad_digest": {**request, "descriptor_sha256": "xyz"},
            "digest_not_str": {**request, "manifest_sha256": 7}, "target_not_str": {**request, "target_id": None},
            "not_a_dict": ["request"]}
    out["launch_request"] = {name: fx.attempt(lambda d=document: api.validate_launch_request(d))
                             for name, document in rows.items()}
    return fx.n(out)


# ======================================================================================================
# 6. rollback
# ======================================================================================================
def two_active(fx, tag, *, fleet=None):
    """Predecessor A active, then candidate B active over it (forward activation at the target)."""
    api = fx.api
    target, authority = fx.target(), fleet or fx.fleet()
    host = fx.host(fleet=authority)
    good = fx.desc(target, tag + ".A", "a")
    first = fx.start_live(host, target, good)
    fx.await_work(host, target, "idle")
    launch_a = fx.read_state(target, api.STATE_FILE)
    candidate = fx.desc(target, tag + ".B", "b", predecessor=fx.digest(good))
    host.materialize(target, candidate)
    host.switch(target, candidate, expected=fx.digest(good))
    return {"target": target, "authority": authority, "host": host, "good": good, "first": first,
            "launch_a": launch_a, "candidate": candidate}


def activate_candidate(fx, s):
    api = fx.api
    started = s["host"].start(s["target"], s["candidate"], authorize=lambda: None,
                              replaces=fx.authority(s["good"], s["first"], s["launch_a"]))
    second = fx.await_receipt(s["target"], fx.digest(s["candidate"]))
    s["second"], s["launch_b"], s["started_b"] = second, fx.read_state(s["target"], api.STATE_FILE), started
    return started


def case_forward_activation(fx):
    api = fx.api
    s, out = two_active(fx, "forward"), {}
    target, source = s["target"], fx.shared_source()
    out["first"] = {"revision_is_a": s["first"]["revision"] == source["a"],
                    "runtime_root_is_a": api.same_path(s["first"]["runtime_root"],
                                                       api.managed_runtime_root(target, source["a"]))}
    started = activate_candidate(fx, s)
    second = s["second"]
    out["started"] = {"started": started["started"], "launch": started["launch"]}
    out["second"] = {"revision_is_b": second["revision"] == source["b"],
                     "runtime_root_is_b": api.same_path(second["runtime_root"],
                                                       api.managed_runtime_root(target, source["b"])),
                     "module_within_b": api.within_path(second["module_root"],
                                                        api.managed_runtime_root(target, source["b"])),
                     "new_instance": second["instance_id"] != s["first"]["instance_id"],
                     "marker_in_running_code": MARKER in (Path(second["module_root"]) / "adapters" /
                                                          "managed_runtime.py").read_text("utf-8"),
                     "consumed": api.consumption_verdict(s["candidate"], second)["consumed"]}
    out["predecessor_gone"] = not api.alive(s["first"]["pid"])
    out["predecessor_runtime_retained"] = fx.attempt(lambda: api.Materializer(target).verify(s["good"]))
    out["descriptor_predecessor_is_a"] = fx.read_state(target, api.DESCRIPTOR_FILE)["predecessor"] == fx.digest(
        s["good"])
    out["authority_control"] = control_row(api, s["authority"])
    out["alive"] = fx.alive(target)
    out["runtime_dirs"] = fx.runtimes(target)
    return fx.n(out)


def restore_predecessor(fx, s):
    """The exact predecessor restored over the failed candidate: the descriptor switched back, then started."""
    s["host"].switch(s["target"], s["good"], expected=fx.digest(s["candidate"]))
    return s["host"].start(s["target"], s["good"], authorize=lambda: None,
                           replaces=fx.authority(s["candidate"], s["second"], s["launch_b"]))


def case_predecessor_restored(fx):
    api = fx.api
    s, out = two_active(fx, "restore"), {}
    target, host, source = s["target"], s["host"], fx.shared_source()
    activate_candidate(fx, s)
    fx.await_work(host, target, "idle")
    restored = restore_predecessor(fx, s)
    receipt = fx.await_receipt(target, fx.digest(s["good"]))
    code = (Path(receipt["module_root"]) / "adapters" / "managed_runtime.py").read_text("utf-8")
    out["restored"] = {"started": restored["started"], "new_instance": receipt["instance_id"] != s["second"]["instance_id"],
                       "revision_is_a": receipt["revision"] == source["a"],
                       "runtime_root_is_a": api.same_path(receipt["runtime_root"],
                                                          api.managed_runtime_root(target, source["a"])),
                       "old_code": MARKER not in code,
                       "consumed": api.consumption_verdict(s["good"], receipt)["consumed"],
                       "running": host.running(target),
                       "descriptor_is_the_predecessor": fx.read_state(target, api.DESCRIPTOR_FILE) == s["good"],
                       "candidate_gone": not api.alive(s["second"]["pid"])}
    out["candidate_runtime_retained"] = fx.attempt(lambda: api.Materializer(target).verify(s["candidate"]))
    out["alive"] = fx.alive(target)
    out["runtime_dirs"] = fx.runtimes(target)
    return fx.n(out)


def hold_debt(fx, authority):
    """LABELLED debt: the owner resumed admission and the candidate era reserved a conductor unit whose guardian
    cleanup is not settled (no guardian runs here; the unit alone is the debt)."""
    authority.resume()
    return authority.reserve_unit(UNIT, fx.api.UNIT_CONDUCTOR, "fixture", "labelled-candidate-conductor")["token"]


def rolling_back(fx, tag, store=None):
    s = two_active(fx, tag, fleet=fx.fleet(store))
    activate_candidate(fx, s)
    fx.await_work(s["host"], s["target"], "idle")
    return s


def refused_restore(fx, s):
    """One attempt to restore A over the candidate; records that nothing on the target moved."""
    api = fx.api
    target, host = s["target"], s["host"]
    launch, receipt = fx.read_state(target, api.STATE_FILE), fx.read_state(target, api.RECEIPT_FILE)
    result = fx.attempt(lambda: host.start(target, s["good"], authorize=lambda: None,
                                           replaces=fx.authority(s["candidate"], s["second"], s["launch_b"])))
    row = control_row(api, s["authority"])
    return {"result": result, "launch_unchanged": fx.read_state(target, api.STATE_FILE) == launch,
            "receipt_unchanged": fx.read_state(target, api.RECEIPT_FILE) == receipt,
            "stop_requested": fx.state(target, "stop.json").exists(), "paused": row["paused"],
            "hold_is_the_predecessor": (row.get(api.ACTIVATION_HOLD) or {}).get("descriptor_sha256") == fx.digest(
                s["good"]), "alive": fx.alive(target)}


def case_held_or_unknown_debt(fx):
    api = fx.api
    s, out = rolling_back(fx, "held"), {}
    target, host, authority = s["target"], s["host"], s["authority"]
    hold_debt(fx, authority)
    # LABELLED lost acknowledgement: the predecessor descriptor is restored, and the record of it is lost.
    host.switch(target, s["good"], expected=fx.digest(s["candidate"]))
    out["held_while_candidate_runs"] = refused_restore(fx, s)
    out["candidate_still_running"] = host.running(target)
    # LABELLED injected controller exit: the candidate's launcher tree is ended outright.
    fx.end_tree(s["launch_b"]["pid"])
    until(lambda: not host.running(target), 30)
    out["candidate_ended"] = {"running": host.running(target), "alive": fx.alive(target)}
    out["held_after_controller_exit"] = refused_restore(fx, s)
    host.fleet = api.Fleet(UnreachableStore())  # LABELLED injected unreachable authority
    out["unreachable_authority"] = refused_restore(fx, s)
    host.fleet = authority
    out["pause_survived"] = control_row(api, authority)["paused"]
    out["held_again"] = refused_restore(fx, s)
    out["held_units_are_the_unit"] = authority.held_units() == [UNIT]
    out["state_dir"] = fx.state_listing(target)
    return fx.n(out)


def case_settled_rollback(fx):
    api = fx.api
    s, out = rolling_back(fx, "settled"), {}
    target, host, authority = s["target"], s["host"], s["authority"]
    token = hold_debt(fx, authority)
    host.switch(target, s["good"], expected=fx.digest(s["candidate"]))
    out["held"] = refused_restore(fx, s)
    # An independent controller in the gap: the durable pause refuses its reservation and admission.
    authority.enqueue("fixture", api.fixture_manifest("job-gap"), GOAL_FIXTURE, [])
    out["gap"] = {"admission": authority.admit_one()["job"],
                  "reservation": fx.attempt(lambda: authority.reserve_unit("d" * 64, api.UNIT_CONDUCTOR, "fixture",
                                                                           "labelled-gap"))}
    authority.settle_unit(UNIT, token, FENCED)
    restored = host.start(target, s["good"], authorize=lambda: None,
                          replaces=fx.authority(s["candidate"], s["second"], s["launch_b"]))
    receipt = fx.await_receipt(target, fx.digest(s["good"]))
    launch = fx.read_state(target, api.STATE_FILE)
    row = control_row(api, authority)
    out["restored"] = {"started": restored["started"], "new_instance": receipt["instance_id"] != s["second"]["instance_id"],
                       "revision_is_a": receipt["revision"] == fx.shared_source()["a"],
                       "consumed": api.consumption_verdict(s["good"], receipt)["consumed"],
                       "running": host.running(target), "new_launcher": launch["pid"] != s["launch_b"]["pid"],
                       "launch_is_the_predecessors": launch["descriptor_sha256"] == fx.digest(s["good"]),
                       "launch": launch}
    out["control_after"] = {"paused": row["paused"], "hold_is_the_predecessor": row[api.ACTIVATION_HOLD][
        "descriptor_sha256"] == fx.digest(s["good"])}
    out["jobs"] = {job["id"]: job["status"] for job in authority.status()["jobs"]}
    out["held_units"] = authority.held_units()
    again = fx.attempt(lambda: fx.host(fleet=authority).start(target, s["good"]))
    out["replayed_start"] = {"result": again, "launch_unchanged": fx.read_state(target, api.STATE_FILE) == launch}
    out["alive"] = fx.alive(target)
    return fx.n(out)


def case_first_gate_unknown(fx):
    api = fx.api
    store = fault_store(api)
    s, out = rolling_back(fx, "unknown", store), {}
    target, host, authority = s["target"], s["host"], s["authority"]
    token = hold_debt(fx, authority)
    host.switch(target, s["good"], expected=fx.digest(s["candidate"]))
    out["admission_open_before"] = control_row(api, authority)["paused"] is False
    store.scan_faults.add(api.BUCKET_UNITS)  # LABELLED injected failure of the FIRST gate's debt read
    out["read_fails"] = refused_restore(fx, s)
    out["fault_fired"] = not store.scan_faults
    other = api.Fleet(store)
    other.enqueue("fixture", api.fixture_manifest("job-gap"), GOAL_FIXTURE, [])
    out["other_owner"] = {"admission": other.admit_one()["job"],
                          "reservation": fx.attempt(lambda: other.reserve_unit("d" * 64, api.UNIT_CONDUCTOR, "fixture",
                                                                               "labelled-gap"))}
    authority.settle_unit(UNIT, token, FENCED)
    restored = host.start(target, s["good"], authorize=lambda: None,
                          replaces=fx.authority(s["candidate"], s["second"], s["launch_b"]))
    receipt = fx.await_receipt(target, fx.digest(s["good"]))
    out["recovered"] = {"started": restored["started"], "new_instance": receipt["instance_id"] != s["second"]["instance_id"],
                        "revision_is_a": receipt["revision"] == fx.shared_source()["a"],
                        "consumed": api.consumption_verdict(s["good"], receipt)["consumed"],
                        "running": host.running(target),
                        "launch_is_the_predecessors": fx.read_state(target, api.STATE_FILE)["descriptor_sha256"]
                        == fx.digest(s["good"])}
    out["jobs"] = {job["id"]: job["status"] for job in authority.status()["jobs"]}
    return fx.n(out)


# ======================================================================================================
# 7. scan
# ======================================================================================================
def hash_object(path, *, autocrlf=False):
    """Git's own blob id of a file, with no global or system configuration read; `--no-filters` hashes the
    PHYSICAL bytes. `autocrlf=True` is only the discriminating control."""
    argv = (["git", "-c", "core.autocrlf=true", "hash-object", str(path)] if autocrlf
            else ["git", "hash-object", "--no-filters", str(path)])
    return subprocess.run(argv, capture_output=True, text=True, check=True, timeout=60,
                          env={**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}).stdout.strip()


def case_physical_bytes(fx):
    api = fx.api
    root = fx.case_dir / "runtime"
    (root / "src").mkdir(parents=True)
    lf, crlf = root / "src" / "lf.py", root / "src" / "crlf.py"
    lf.write_bytes(b"x = 1\ny = 2\n")
    crlf.write_bytes(b"x = 1\r\ny = 2\r\n")
    listing = api.scan(root)
    out = {"scan": listing, "matches_git_no_filters": listing == [["src/crlf.py", hash_object(crlf)],
                                                                   ["src/lf.py", hash_object(lf)]],
           "lf_and_crlf_differ": hash_object(crlf) != hash_object(lf),
           "normalizing_filter_gives_the_lf_id": hash_object(crlf, autocrlf=True) == hash_object(lf),
           "scan_has_the_normalized_id": ["src/crlf.py", hash_object(crlf, autocrlf=True)] in listing}
    (root / api.MANIFEST_FILE).write_text("{}", encoding="utf-8")
    (root / api.LISTING_FILE).write_text("[]", encoding="utf-8")
    out["seal_files_excluded"] = api.scan(root) == listing
    return fx.n(out)


def case_symlink(fx):
    api = fx.api
    root = fx.case_dir / "runtime"
    (root / "src" / "pkg").mkdir(parents=True)
    (root / "src" / "a.py").write_bytes(b"x = 1\n")
    out = {"plain": api.scan(root)}
    (root / "src" / "link.py").symlink_to(root / "src" / "a.py")
    out["file_symlink"] = api.scan(root)
    (root / "src" / "link.py").unlink()
    out["after_unlink"] = api.scan(root)
    (root / "src" / "linked-dir").symlink_to(root / "src" / "pkg", target_is_directory=True)
    out["directory_symlink"] = api.scan(root)
    (root / "src" / "linked-dir").unlink()
    os.mkfifo(root / "src" / "fifo")
    out["not_a_plain_file"] = api.scan(root)
    return fx.n(out)


GROUPS = [
    ("seal", [("seal_once_and_revalidate", case_seal_once_and_revalidate), ("interrupted_seal", case_interrupted_seal),
              ("lost_response", case_lost_response), ("linked_worktree", case_linked_worktree)]),
    ("refuse", [("changed_or_foreign", case_changed_or_foreign),
                ("unresolved_or_unqualified", case_unresolved_or_unqualified),
                ("tracked_symlink_and_fence", case_tracked_symlink_and_fence),
                ("target_registry", case_target_registry), ("runtime_path", case_runtime_path),
                ("bad_runtime", case_bad_runtime)]),
    ("launch", [("clean_start_restart_repeat", case_clean_start_restart_repeat),
                ("killed_launcher", case_killed_launcher), ("two_owners", case_two_owners),
                ("entry_and_launch_refusals", case_entry_and_launch_refusals),
                ("runtime_control_and_fixture", case_runtime_control_and_fixture)]),
    ("drain_stop", [("active_work", case_active_work), ("unavailable_heartbeat", case_unavailable_heartbeat),
                    ("heartbeat_verdict", case_heartbeat_verdict), ("not_running", case_not_running)]),
    ("gate", [("first_start_reads", case_first_start_reads), ("no_authority", case_no_authority),
              ("gate_answers", case_gate_answers)]),
    ("rollback", [("forward_activation", case_forward_activation),
                  ("predecessor_restored", case_predecessor_restored),
                  ("held_or_unknown_debt", case_held_or_unknown_debt), ("settled_rollback", case_settled_rollback),
                  ("first_gate_unknown", case_first_gate_unknown)]),
    ("scan", [("physical_bytes", case_physical_bytes), ("symlink", case_symlink)]),
]


def synchronised(api):
    """LABELLED: keep the fake clock on the real wall time, because the live children write real heartbeats."""
    stop = threading.Event()

    def run():
        while not stop.is_set():
            api.sync_clock()
            time.sleep(0.01)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return stop, thread


def run(api) -> dict:
    result, counts, live = {}, {}, 0
    stop, thread = synchronised(api)
    try:
        with tempfile.TemporaryDirectory(prefix="s7-managed-runtime-") as raw:
            fx = Managed(api, Path(raw).resolve())
            source = fx.shared_source()
            result["revisions"] = {"a": source["a"], "b": source["b"], "identical_on_rebuild": True}
            for name, cases in GROUPS:
                result[name] = {}
                for case, function in cases:
                    api.reset_ids()
                    fx.case_dir = fx.base / f"{name}-{case}"
                    fx.case_dir.mkdir()
                    try:
                        result[name][case] = function(fx)
                    finally:
                        targets, fx.live = fx.live, []
                        failure = None
                        for target in targets:
                            try:
                                fx.teardown(target)
                            except Exception as exc:  # the sweep below still runs
                                failure = failure or exc
                        live += fx.sweep(f"{name}.{case}")
                        if failure is not None:
                            raise failure
                counts[name] = len(result[name])
            result["live_children"] = live
            result["cases_per_group"] = counts
    finally:
        stop.set()
        thread.join(10)
    return result
