"""Shared S7 scenario steps (`delivery.fleet_recovery_collectors`): M7 `adapters/fleet_recovery.py`, the host-side proofs
of the two storage-recovery owner operations and of the host migration (INV-FLEET-001; DESIGN-s7 §0 and the step-6
family plan; S5-PACKET G4), recorded BEFORE the move.

Layer: harness (never shipped). Never imports `codex_harness`.

Seven case groups, each case labelled in the result (`{group: {case: {...}}}`), plus `carried`:
- `recovery`: `collect_recovery_proof` (the observation; every refusal of M7's `test_missing_unreadable_or_live_proof_refuses`
  and the adapter's other branches), the Docker state answers, `LaneReader` over a LABELLED `connect=` double and
  `docker_state` over LABELLED fake `docker` executables, `_run_record`'s bindings and `run_root`.
- `slots`: `_recorded_slots` and `_machine_slot` (the ledger `purpose` and the operation's recorded `calls.slots[]`).
- `runner`: `runner_state` over service journals, `listed_runs` and `_active_runs` over retained isolation runs.
- `checkouts`: `checkout_identity`, `_independent`, `_writable`, `_queued_bindings` and `_resolved_directory` over
  deterministic pinned git fixtures.
- `copy_manifest`: `verify_copy_manifest` and the physical ownership chain (`_relative`, `_move_roots`, `_bind_entry`,
  `_link_entry`, `_linked`, `_actual`, `_actual_root`, `_declared_parts`, `_own_chain`, `_owned_copy`), `_hash_file` and
  `_hash_bounded`.
- `relocation`: `collect_relocation_proof`.
- `host_migration`: `_schema_provisioned` and `collect_host_migration_proof`.

**Fixtures (all LABELLED).**
- Docker is ONLY the `state=` double (a callable recording the container ids it is asked about) or a fake `docker`
  executable (`#!/bin/sh`, one per case, recording every argv into a file under the case's temporary root and printing a
  scripted answer) given through `docker_state(..., docker=path)`. The real docker is never run; a daemon timeout (60 s) is
  not exercised.
- Lane reads are the tests' `LaneDouble` (copied, recording every `get`/`scan`), `Ledger` (copied, recording `slots()` and
  failing on `reserve`), and for `LaneReader` a `connect=` double recording the DSN, the connect keywords, every statement
  and its parameters. No PostgreSQL. The default `budget=None` (a `CallBudget()` over the host's machine ledger) is
  unreachable here and is not exercised.
- Checkouts are real git repositories built under `T.pinned_environment`/`T.pinned_git` (pinned identity, dates and empty
  git configuration files, newline normalization declared in the repository's own config, as M7's `repository`/`clone`
  do), so their commit ids are identical on every run and stay LITERAL in the result.
- Symlinks, permissions, sizes and journals are real files under the case's temporary root. Permission cases assert
  `os.geteuid() != 0` and record `not_root: true`. The case-distinct cases record whether this filesystem distinguishes
  `rt` from `RT` and run only where it does.
- Evidence, request, config and job documents are hand-built dicts of the shape M7's domain validators return; the
  collectors read only the fields used here. The fleet application (`Fleet.reconcile_interrupted/relocate/migrate_host`)
  is the S5 families', and the CLI commands are S10's.

**Windows (W-B).** `_link_entry`'s `st_file_attributes` reparse-point branch is exercised through a LABELLED attribute
double on POSIX (no real junction or reparse point exists here): the branch's arithmetic is recorded, the platform
behaviour is not. M7's own Windows-only skips (symlink privilege, junction) are carried below.

`api` supplies (names of the adapter module `adapters.fleet_recovery`, privates without the underscore): the functions
`collect_recovery_proof`, `collect_relocation_proof`, `collect_host_migration_proof`, `verify_copy_manifest`,
`runner_state`, `listed_runs`, `checkout_identity`, `docker_state`, `run_root`, the class `LaneReader`, `hash_file`,
`hash_bounded`, `resolved_directory`, `run_record`, `recorded_slots`, `machine_slot`, `active_runs`, `independent`,
`writable`, `queued_bindings`, `relative`, `move_roots`, `bind_entry`, `link_entry`, `linked`, `actual`, `actual_root`,
`declared_parts`, `own_chain`, `owned_copy`, `schema_provisioned`, the constants `RUN_ROOT`, `COPY_ENTRY_FIELDS`,
`READ_BYTES`, `MAX_COPY_BYTES`, `JOURNAL_LINES`; from `domain.fleet_recovery` `CLOSED_INVOCATIONS`, `STOPPED_STATES`,
`COPY_MANIFEST_SCHEMA`, `COPY_OWNERSHIP`, `MOVABLE`, `PROOF_SCHEMA`, `RELOCATION_PROOF_SCHEMA`,
`HOST_MIGRATION_PROOF_SCHEMA`; `FleetRefused`, `LaunchRefused`, `repository_identity`, `normalize_path`, `RESOLVED`,
`digest`; and the hook `patched(**attrs)` (adapter attributes replaced for the block: the tests' pre-fix controls).

**Normalization is explicit, done here and identical on both sides** (pilot 33's `Fixture.n`/`Fixture.attempt`, IMPORTED):
`sys.executable` → `<python>`, this case's temporary root → `<root>`, ISO times → `<time>`, `pid` keys → `<pid>`; the
digest of a fixture path (the proof's `worktree_digest`, `path_identity`, `prior_path_identity`) is replaced by
`<digest:NAME>` with the fixture's own label (`T.Fixture.digests`). A refusal is recorded as its type, its message (a fixed
reason code and at most a field name) and its `reason_code`/`field`, plus `value_in_message`: whether the message holds the
temporary root or the canary. The fixture repository revisions stay literal. Durations are never recorded and nothing
else is masked.

M7 tests mirrored (their DIRECT collector calls; the application halves are carried):
tests/test_fleet_recovery.py: test_proof_reads_every_store_and_preserves_unknown_usage,
test_missing_unreadable_or_live_proof_refuses (x19; `open_slot` records the adapter half: the policy gate refusal is S5),
test_an_unavailable_or_wrong_lane_source_is_a_refusal_not_an_absence,
test_a_call_slot_must_be_bound_to_this_operation_by_a_record_the_host_wrote (adapter half),
test_container_name_without_a_recorded_binding_is_not_proof, test_recovery_reads_no_repository_and_reserves_no_call
(adapter half: no reserve, no repository read).
tests/test_fleet_relocation.py: test_the_runner_must_be_proven_stopped_by_its_own_journal,
test_a_retained_lane_run_refuses_unless_docker_proves_it_is_not_running,
test_runs_that_cannot_be_enumerated_are_a_refusal_not_an_empty_lane,
test_the_target_must_be_an_independent_checkout_of_the_same_repository (observation half),
test_a_symlinked_target_is_refused_rather_than_followed, test_queued_bases_and_goal_blobs_must_exist_in_the_target
(observation half), test_the_copy_manifest_must_hash_to_what_was_actually_copied,
test_a_manifest_entry_must_prove_a_file_this_request_actually_moves (x9),
test_a_child_link_to_the_source_is_refused_even_though_the_bytes_read_back,
test_a_destination_that_links_outside_the_target_is_refused, test_a_source_side_redirection_is_refused_as_well,
test_a_case_distinct_sibling_is_not_this_target_even_though_names_casefold_equal,
test_the_owners_case_distinct_symlink_reproduction_refuses,
test_a_child_link_is_refused_even_when_it_leads_to_a_contained_file (x2),
test_mixed_case_nested_copies_pass_without_lowercasing_real_path_names,
test_a_manifest_path_whose_resolution_is_inaccessible_refuses (x3), test_a_nested_ordinary_copy_below_the_target_commits
(the collector half of each).
tests/test_fleet_host_migration.py: no test calls a collector directly (they reach `collect_host_migration_proof` only
through `zeus fleet migrate-host`); the collector is characterized directly with no M7 test.
Characterized directly (no M7 test): `_hash_file`, `_hash_bounded`, `_resolved_directory`, `_run_record`'s other bindings,
`docker_state`, `_recorded_slots`, `_machine_slot`'s other branches, `listed_runs`, `_active_runs`, `checkout_identity`,
`_independent`, `_writable`, `_queued_bindings`, the copy-ownership chain helpers, `_schema_provisioned` and
`collect_host_migration_proof`.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import s7_host_targets as T

A = None  # the api of this run
CANARY = "CANARY-must-never-be-emitted"
TASK, OPERATION = "task-92b13b20", "op-1"
CORRELATION = "operation:" + OPERATION
RUN, CONTAINER, RESERVATION = "1a" * 16, "c7" * 32, "d4" * 32
SLOT, OTHER_SLOT = "e9" * 16, "b3" * 16
PAST, NOW = "2026-09-20T00:00:00+00:00", "2026-09-21T00:00:00+00:00"
GOAL_BYTES = b"# Goal\nrecover the storage\n"
NORMALIZATION = (("core.autocrlf", "false"), ("core.eol", "lf"), ("core.safecrlf", "false"))
NORMALIZATION_ARGS = [arg for key, value in NORMALIZATION for arg in ("--config", key + "=" + value)]

CARRIED = {
    "tests/test_fleet_recovery.py: the Fleet application and CLI halves":
        "test_evidence_document_is_strict_and_never_echoes_values, test_reconcile_settles_one_reservation_and_preserves_the_history, "
        "test_identical_replay_is_idempotent_and_changed_evidence_conflicts, test_a_concurrent_second_owner_finds_the_reservation_already_settled, "
        "test_the_transaction_refuses_anything_it_was_not_shown, test_proof_that_changed_between_the_reads_refuses_before_commit, "
        "test_a_proof_from_another_observation_is_refused, test_the_owner_command_exists_on_the_cli_and_carries_only_codes, "
        "test_the_cli_*, test_the_non_reentrant_regression_catches_the_pre_fix_observation: reach the collector only through "
        "Fleet.reconcile_interrupted or the S10 CLI: the S5 coordination.fleet_recovery family and the S10 CLI",
    "tests/test_fleet_relocation.py: the Fleet application and CLI halves":
        "test_request_document_is_strict_and_never_echoes_values, test_only_the_named_paths_change_and_everything_else_must_match, "
        "test_a_proof_that_only_compared_names_cannot_commit, test_relocation_rewrites_only_the_registry_paths_and_keeps_the_history, "
        "test_identical_relocation_replays_and_a_conflicting_one_refuses, test_a_fleet_that_is_not_paused_and_idle_refuses_the_cutover, "
        "test_a_proof_that_does_not_cover_this_request_refuses, test_a_proof_that_changed_between_the_reads_refuses_before_commit, "
        "test_the_owner_command_exists_on_the_cli_and_requires_the_runner_journal, test_admission_after_a_move_still_excludes_conflicting_paths, "
        "test_a_repository_that_moved_and_came_back_is_still_one_repository, "
        "test_a_repository_moved_twice_resolves_to_its_current_path_from_either_identity, test_the_cli_*, "
        "test_the_non_reentrant_regression_catches_the_pre_fix_observation: Fleet.relocate / S10 CLI: the S5 coordination.fleet_relocation family",
    "tests/test_fleet_relocation.py: fixture portability regressions of the test file itself":
        "test_the_fixture_checkouts_hold_the_committed_goal_bytes_under_inherited_normalization (Windows autocrlf, W-B), "
        "test_retiring_a_checkout_does_not_depend_on_deleting_read_only_git_objects (the test's own `retire` helper): "
        "no collector is called; the driver's fixtures pin their own normalization and never retire a checkout",
    "tests/test_fleet_host_migration.py":
        "test_d2_rebinds_every_lane_keeps_identities_and_resolves_frozen_history, test_invalid_requests_refuse_without_a_write, "
        "test_target_observation_failures_refuse, test_unpaused_fleet_or_running_runner_refuses (fabricated proofs into "
        "Fleet.migrate_host: the S5 fleet families); the migrate-host CLI tests (S10 CLI)",
    "tests/test_fleet_recovery_postgres.py": "real isolated PostgreSQL store: owner family delivery.restore(.pg)",
    "collect_recovery_proof(budget=None)": "a CallBudget() reads the host's machine call ledger: not a fixture-reachable service",
    "_schema_provisioned default verify with a DSN": "verify_lane_schema opens a psycopg connection: needs PostgreSQL (unreachable); "
        "the empty-DSN refusal of lane_dsn before any connection is recorded",
    "docker_state daemon timeout": "LIMITS['docker_command_seconds'] is 60 s: a hung daemon is not waited for here",
    "Windows reparse points and junctions": "W-B: a real junction needs Windows; the attribute branch is recorded through a labelled double",
}


# ---- the per-case workspace and normalization ----------------------------------------------------------------------

class Ws:
    """One case's temporary root, the imported pilot-33 normalizer bound to it and the pinned git environment."""

    def __init__(self):
        self.root = Path(tempfile.mkdtemp(prefix="s7frc-")).resolve()
        norm = object.__new__(T.Fixture)
        norm.digests = {}
        norm.substitutions = sorted([(str(self.root), "<root>"), (T.PY, "<python>")], key=lambda pair: -len(pair[0]))
        self.norm = norm
        self.env = T.pinned_environment(self.root)

    def n(self, value):
        return self.norm.n(value)

    def label(self, digest: str, name: str):
        self.norm.digests[digest] = name

    def label_paths(self):
        """Register, under the fixture's own label, the digest the adapter derives from every path below this case's
        root (`digest(path)` and `repository_identity(path)`): those digests embed the random temporary root."""
        paths = [self.root]
        for directory, names, files in os.walk(self.root):
            paths.extend(Path(directory) / name for name in names + files)
        for path in paths:
            self.label_path(path)

    def label_path(self, path):
        path = Path(path)
        relative = "." if path == self.root else str(path.relative_to(self.root))
        self.label(A.digest(str(path)), "path:" + relative)
        self.label(A.repository_identity(str(path)), "identity:" + relative)

    def att(self, call):
        self.label_paths()
        result = self.norm.attempt(call)
        raised = result.get("raised")
        if raised is not None:
            raised["value_in_message"] = "<root>" in raised["message"] or CANARY in raised["message"]
        return result

    def close(self):
        for directory, _, files in os.walk(self.root):
            with contextlib.suppress(OSError):
                os.chmod(directory, 0o700)
            for name in files:
                path = os.path.join(directory, name)
                if not os.path.islink(path):
                    with contextlib.suppress(OSError):
                        os.chmod(path, 0o600)
        shutil.rmtree(self.root, ignore_errors=True)


@contextlib.contextmanager
def case_ws():
    ws = Ws()
    try:
        yield ws
    finally:
        ws.close()


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def not_root() -> bool:
    assert os.geteuid() != 0, "the permission cases need a process that is not root"
    return True


def write(path, data: bytes | str = b""):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data.encode("utf-8") if isinstance(data, str) else data)
    return path


def symlink(target, name, *, directory: bool = True):
    os.symlink(str(target), str(name), target_is_directory=directory)
    return Path(name)


def case_sensitive(parent: Path) -> bool:
    """Whether this filesystem keeps `case-probe` and `CASE-PROBE` apart (recorded, never assumed)."""
    probe = Path(parent)
    probe.mkdir(parents=True, exist_ok=True)
    (probe / "case-probe").write_bytes(b"")
    return not (probe / "CASE-PROBE").exists()


def after(action, **kwargs):
    """Run a fixture `action`, then hand the case builder `(request, options)` with no request of its own."""
    action()
    return None, kwargs


def sorted_tree(directory: Path) -> list:
    """Every name below `directory`; the probe file's own name (a digest of the temporary root) is recorded as `<probe>`."""
    return sorted(re.sub(r"^\.zeus-relocation-probe-[0-9a-f]{16}$", "<probe>", str(path.relative_to(directory)))
                  for path in Path(directory).rglob("*"))


# ---- git fixtures ---------------------------------------------------------------------------------------------------

def git(ws, path, *args) -> str:
    return T.pinned_git(Path(path), ws.env, *args)


def make_repo(ws, path: Path, *, goal: bytes = GOAL_BYTES, mode_files=()) -> str:
    """A repository of one commit under the pinned identity and dates; `mode_files` are extra committed files."""
    path.mkdir(parents=True)
    git(ws, path, "init", "-q", "-b", "main")
    for key, value in NORMALIZATION:
        git(ws, path, "config", "--local", key, value)
    write(path / "docs" / "GOAL.md", goal)
    for name, data, executable in mode_files:
        write(path / name, data)
        if executable:
            os.chmod(path / name, 0o755)
    git(ws, path, "add", ".")
    git(ws, path, "commit", "-q", "-m", "Initial fixture")
    return git(ws, path, "rev-parse", "HEAD")


def clone(ws, source: Path, target: Path, *shared) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    git(ws, target.parent, "clone", "--quiet", *NORMALIZATION_ARGS, *shared, str(source), str(target))
    return target


def goal_of(base: str, data: bytes = GOAL_BYTES) -> dict:
    return {"path": "docs/GOAL.md", "sha256": sha(data), "criterion": "c", "base_revision": base, "bytes": len(data)}


def job(name: str, lane: str, status: str, goal: dict) -> dict:
    return {"id": name, "lane": lane, "status": status, "goal": goal}


# ---- doubles (LABELLED copies of M7's test helpers, tests/test_fleet_recovery.py) -----------------------------------

class Docker:
    """A `state=` double: answers every container id with `answer` (a dict, None, or a callable) and records the ids."""

    def __init__(self, answer):
        self.answer, self.calls = answer, []

    def __call__(self, container_id):
        self.calls.append(container_id)
        return self.answer(container_id) if callable(self.answer) else deepcopy(self.answer)


EXITED = {"status": "exited", "exit_code": 255}
RUNNING = {"status": "running", "exit_code": None}


class Lane:
    """M7's `LaneDouble`: the lane schema's `documents` rows; every read is recorded."""

    def __init__(self, documents):
        self.documents, self.reads = documents, []

    def get(self, bucket, key):
        self.reads.append(["get", bucket, key])
        return deepcopy(self.documents.get(bucket, {}).get(key))

    def scan(self, bucket):
        self.reads.append(["scan", bucket])
        return [deepcopy(row) for _, row in sorted(self.documents.get(bucket, {}).items())]


class Ledger:
    """M7's `Ledger`: the machine call budget as the file ledger reads back; `slots()` reads and `reserve` are recorded."""

    def __init__(self, rows):
        self.rows, self.reads, self.reserved = rows, 0, 0

    def slots(self):
        self.reads += 1
        return [dict(row) for row in self.rows]

    def reserve(self, **_):
        self.reserved += 1
        raise AssertionError("owner recovery must never reserve a provider call slot")


def ledger(**overrides) -> Ledger:
    """This operation's slot beside an unrelated settled slot of other work (same shape, only `purpose` differs)."""
    mine = {"id": SLOT, "host": "h", "status": "used", "purpose": CORRELATION + ":task", "provider": "claude",
            "model": "claude-fixture-model", "outcome": "interrupted_unknown", **overrides}
    unrelated = {"id": OTHER_SLOT, "host": "h", "status": "used", "purpose": "operation:op-other:task",
                 "provider": "claude", "model": "claude-fixture-model", "outcome": "accepted"}
    return Ledger([unrelated, mine])


def lane_documents(worktree: str) -> dict:
    return {
        "operations": {OPERATION: {"id": OPERATION, "correlation_id": CORRELATION, "cycle_id": CORRELATION,
                                   "assignment_message_id": "msg-1", "status": "running"}},
        "tasks": {TASK: {"id": TASK, "status": "cancelled", "generation": 2, "attempt": 1, "lease_owner": None,
                         "lease_until": PAST, "message": {"correlation_id": CORRELATION}}},
        "execution_progress": {TASK: {"id": TASK, "worktree": worktree, "generation": 1, "attempt": 1}},
        "invocation_reservations": {RESERVATION: {"id": RESERVATION, "task_id": TASK, "bucket": "tasks",
                                                  "generation": 1, "attempt": 1, "status": "unsettled_unknown",
                                                  "usage": {"source": "unknown", "total_tokens": None}}}}


def evidence(**overrides) -> dict:
    document = {"schema": "urn:zeus:fleet-recovery-evidence:1", "job_id": OPERATION, "operator": "owner",
                "lane_operation": {"id": OPERATION, "correlation_id": CORRELATION, "task_id": TASK, "generation": 2},
                "container": {"run_id": RUN, "role": "worker", "name": "zeus-worker-" + RUN, "id": CONTAINER},
                "invocation": {"reservation_id": RESERVATION, "status": "unsettled_unknown"},
                "machine_slot": {"id": SLOT, "outcome": "interrupted_unknown"}, "recorded_at": NOW}
    for key, value in overrides.items():
        outer, _, inner = key.partition(".")
        document[outer] = {**document[outer], inner: value} if inner else value
    return document


def run_record(runtime: Path, worktree: str, **overrides) -> Path:
    """One retained isolation run record as `bootstrap.isolated_worker` writes it (M7 `write_run_record`)."""
    record = {"run_id": RUN, "role": "worker", "workspace": worktree, "container": CONTAINER,
              "container_name": "zeus-worker-" + RUN, "image": "sha256:" + "f" * 64,
              "label": "zeus.isolated.run=" + RUN, "state": "stop_unconfirmed", "lifecycle": [], **overrides}
    directory = Path(runtime).joinpath(*A.RUN_ROOT) / record["run_id"]
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "run.json").write_text(json.dumps(record, sort_keys=True), encoding="utf-8")
    return directory / "run.json"


class Recovery:
    """One interrupted job's host world: the lane documents, the retained run record, the Docker and ledger doubles."""

    def __init__(self, ws):
        self.ws = ws
        self.runtime = ws.root / "rt-a"
        self.worktree = str(ws.root / "worktree")
        self.lane = {"id": "a", "runtime": str(self.runtime)}
        self.docs = lane_documents(self.worktree)
        self.state, self.slots, self.document = Docker(EXITED), ledger(), evidence()
        self.record = run_record(self.runtime, self.worktree)
        ws.label_path(self.worktree)  # the recorded worktree need not exist on disk

    def run(self, clock="fixed"):
        reader = Lane(self.docs)
        kwargs = {"reader": reader, "budget": self.slots, "state": self.state}
        if clock == "fixed":
            kwargs["clock"] = lambda: NOW
        elif clock is not None:
            kwargs["clock"] = clock
        result = self.ws.att(lambda: A.collect_recovery_proof(self.document, self.lane, **kwargs))
        return {"result": result, "reads": reader.reads, "docker_ids": self.state.calls,
                "ledger": {"slot_reads": self.slots.reads, "reserved": self.slots.reserved}}


def recovery_case(out, name, setup=None, clock="fixed"):
    with case_ws() as ws:
        world = Recovery(ws)
        if setup:
            setup(world)
        out[name] = world.run(clock)


# ---- group recovery -------------------------------------------------------------------------------------------------

def set_task(**fields):
    return lambda w: w.docs["tasks"][TASK].update(fields)


def set_reservation(**fields):
    return lambda w: w.docs["invocation_reservations"][RESERVATION].update(fields)


def group_recovery() -> dict:
    out: dict = {}
    recovery_case(out, "proof_observation")
    recovery_case(out, "proof_default_clock_reads_the_installed_clock", set_task(lease_until="2025-01-01T00:00:00+00:00"), clock=None)
    recovery_case(out, "refuses_default_clock_before_the_lease", clock=None)
    recovery_case(out, "proof_naive_clock_read_as_utc", clock=lambda: "2026-09-21T00:00:00")

    def setup_settled(w):
        w.docs["invocation_reservations"][RESERVATION].update(
            status="settled", usage={"source": "provider", "total_tokens": 12, "input_tokens": 5})
    recovery_case(out, "proof_settled_usage_preserved_as_recorded", setup_settled)
    recovery_case(out, "proof_usage_absent_stays_unknown", lambda w: w.docs["invocation_reservations"][RESERVATION].pop("usage"))
    recovery_case(out, "proof_usage_not_a_document", set_reservation(usage="12"))
    recovery_case(out, "proof_lease_none_is_not_live", set_task(lease_until=None))
    recovery_case(out, "proof_lease_naive_is_unknown", set_task(lease_until="2026-09-20T00:00:00"))
    recovery_case(out, "proof_lease_equal_to_now_is_not_live", set_task(lease_until=NOW))
    recovery_case(out, "proof_other_reservation_of_other_task_is_ignored",
                  lambda w: w.docs["invocation_reservations"].update(
                      {"b" * 64: {"id": "b" * 64, "task_id": "task-other", "status": "reserved"}}))
    recovery_case(out, "proof_run_record_of_another_workspace_is_ignored",
                  lambda w: run_record(w.runtime, str(w.ws.root / "elsewhere"), run_id="9b" * 16,
                                       container_name="zeus-worker-" + "9b" * 16))
    recovery_case(out, "proof_resolved_run_record_is_still_the_binding", lambda w: run_record(w.runtime, w.worktree, state="removed"))
    recovery_case(out, "proof_extra_operation_calls_recorded",
                  lambda w: w.docs["operations"][OPERATION].update(calls={"reserved": 1, "settled": 0, "slots": []}))
    # the docker answers: every state
    for state in ("exited", "dead", "created", "running", "paused", "restarting", "removing", ""):
        recovery_case(out, "docker_state_" + (state or "empty"),
                      lambda w, s=state: setattr(w, "state", Docker({"status": s, "exit_code": 3})))
    recovery_case(out, "docker_state_answer_not_a_document", lambda w: setattr(w, "state", Docker("exited")))
    recovery_case(out, "docker_state_missing_status", lambda w: setattr(w, "state", Docker({"exit_code": 0})))
    recovery_case(out, "docker_state_exit_code_absent_is_none", lambda w: setattr(w, "state", Docker({"status": "exited"})))
    # M7 test_missing_unreadable_or_live_proof_refuses (x19) and the adapter's other branches
    recovery_case(out, "refuses_live_container", lambda w: setattr(w, "state", Docker(RUNNING)))
    recovery_case(out, "refuses_docker_unavailable", lambda w: setattr(w, "state", Docker(None)))
    recovery_case(out, "refuses_task_running", set_task(status="running", lease_until=PAST))
    recovery_case(out, "refuses_task_generation", set_task(generation=3))
    recovery_case(out, "refuses_task_generation_absent", lambda w: w.docs["tasks"][TASK].pop("generation"))
    recovery_case(out, "refuses_lease_live", set_task(lease_until="2099-01-01T00:00:00+00:00"))
    recovery_case(out, "refuses_lease_unparsable", set_task(lease_until="not-a-time"))
    recovery_case(out, "refuses_lease_not_a_string", set_task(lease_until=12))
    recovery_case(out, "refuses_foreign_task", set_task(message={"correlation_id": "operation:other"}))
    recovery_case(out, "refuses_task_message_not_a_document", set_task(message="x"))
    recovery_case(out, "refuses_missing_task", lambda w: w.docs.update(tasks={}))
    recovery_case(out, "refuses_task_not_a_document", lambda w: w.docs["tasks"].update({TASK: "x"}))
    recovery_case(out, "refuses_task_with_another_id", set_task(id="task-other"))
    recovery_case(out, "refuses_unbound_operation", lambda w: w.docs["operations"][OPERATION].update(cycle_id="operation:other"))
    recovery_case(out, "refuses_operation_without_assignment_message",
                  lambda w: w.docs["operations"][OPERATION].pop("assignment_message_id"))
    recovery_case(out, "refuses_operation_row_absent", lambda w: w.docs.update(operations={}))
    recovery_case(out, "refuses_evidence_operation_id_differs",
                  lambda w: setattr(w, "document", evidence(**{"lane_operation.id": "op-2"})))
    recovery_case(out, "refuses_correlation_without_the_operation_prefix",
                  lambda w: setattr(w, "document", evidence(**{"lane_operation.correlation_id": "other:op-1"})))
    recovery_case(out, "refuses_no_worktree", lambda w: w.docs.update(execution_progress={}))
    recovery_case(out, "refuses_worktree_empty", lambda w: w.docs["execution_progress"][TASK].update(worktree=""))
    recovery_case(out, "refuses_progress_not_a_document", lambda w: w.docs["execution_progress"].update({TASK: "x"}))
    recovery_case(out, "refuses_container_name_without_a_recorded_binding",
                  lambda w: w.docs["execution_progress"][TASK].update(worktree=str(w.ws.root / "somewhere-else")))
    recovery_case(out, "refuses_no_run_record_at_all", lambda w: w.record.unlink())
    recovery_case(out, "refuses_run_root_absent", lambda w: shutil.rmtree(w.runtime))
    recovery_case(out, "refuses_ambiguous_runs",
                  lambda w: run_record(w.runtime, w.worktree, run_id="9b" * 16, container_name="zeus-worker-" + "9b" * 16))
    recovery_case(out, "refuses_other_container", lambda w: run_record(w.runtime, w.worktree, container="a" * 64))
    recovery_case(out, "refuses_other_container_name", lambda w: run_record(w.runtime, w.worktree, container_name="zeus-worker-x"))
    recovery_case(out, "refuses_other_run_id", lambda w: setattr(w, "document", evidence(**{"container.run_id": "2b" * 16})))
    recovery_case(out, "refuses_record_state_unreadable_in_the_document",
                  lambda w: run_record(w.runtime, w.worktree, state="unreadable"))
    recovery_case(out, "refuses_run_record_not_json_is_no_binding", lambda w: w.record.write_text("{ not json", encoding="utf-8"))
    recovery_case(out, "refuses_reservation_unknown", lambda w: w.docs.update(invocation_reservations={}))
    recovery_case(out, "refuses_reservation_of_another_task", set_reservation(task_id="task-other"))
    recovery_case(out, "refuses_reservation_not_a_document", lambda w: w.docs["invocation_reservations"].update({RESERVATION: "x"}))
    recovery_case(out, "refuses_open_reservation", set_reservation(status="reserved"))
    recovery_case(out, "refuses_reservation_status_not_closed", set_reservation(status="weird"))
    recovery_case(out, "refuses_second_open_reservation",
                  lambda w: w.docs["invocation_reservations"].update(
                      {"b" * 64: {"id": "b" * 64, "task_id": TASK, "status": "reserved", "usage": {"source": "unknown"}}}))
    recovery_case(out, "refuses_missing_slot", lambda w: setattr(w, "slots", Ledger([])))
    recovery_case(out, "refuses_unreadable_slot", lambda w: setattr(w, "slots", ledger(unreadable="ValueError")))
    recovery_case(out, "refuses_unrelated_slot",
                  lambda w: setattr(w, "document", evidence(**{"machine_slot": {"id": OTHER_SLOT, "outcome": "accepted"}})))
    recovery_case(out, "refuses_legacy_slot",
                  lambda w: setattr(w, "slots", Ledger([{"id": SLOT, "host": "h", "status": "used", "outcome": "interrupted_unknown"}])))
    # `open_slot`: a reserved slot passes the adapter (it exists and is readable); the policy gate refuses it (S5).
    recovery_case(out, "open_slot_passes_the_adapter", lambda w: setattr(w, "slots", ledger(status="reserved")))
    # order of the refusals
    recovery_case(out, "order_operation_before_task",
                  lambda w: (w.docs["operations"][OPERATION].update(cycle_id="x"), w.docs.update(tasks={})))
    recovery_case(out, "order_docker_before_invocation",
                  lambda w: (setattr(w, "state", Docker(RUNNING)), w.docs["invocation_reservations"][RESERVATION].update(status="reserved")))
    recovery_case(out, "order_lease_before_worktree",
                  lambda w: (w.docs["tasks"][TASK].update(lease_until="2099-01-01T00:00:00+00:00"), w.docs.update(execution_progress={})))
    recovery_case(out, "order_binding_before_docker",
                  lambda w: (w.record.unlink(), setattr(w, "state", Docker(None))))
    recovery_case(out, "order_open_reservation_before_slot",
                  lambda w: (w.docs["invocation_reservations"][RESERVATION].update(status="reserved"), setattr(w, "slots", Ledger([]))))
    out["constants"] = {"closed_invocations": sorted(A.CLOSED_INVOCATIONS), "stopped_states": sorted(A.STOPPED_STATES),
                        "proof_schema": A.PROOF_SCHEMA, "run_root": list(A.RUN_ROOT)}
    with case_ws() as ws:
        out["run_root_joins_under_the_runtime"] = ws.n(str(A.run_root(str(ws.root / "rt"))))
    out["lane_reader"] = lane_reader_cases()
    out["docker_state"] = docker_state_cases()
    return out


class Rows:
    def __init__(self, rows):
        self.rows = rows

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows


class Connection:
    """M7's lane connection stand-in: answers `current_schema()` and one document query; records everything."""

    def __init__(self, schema, rows, events, fail_on=None):
        self.schema, self.rows, self.events, self.fail_on = schema, rows, events, fail_on

    def __enter__(self):
        self.events.append("enter")
        return self

    def __exit__(self, *_):
        self.events.append("exit")
        return False

    def execute(self, statement, parameters=None):
        self.events.append(["execute", statement, list(parameters) if parameters is not None else None])
        if self.fail_on is not None and self.fail_on in statement:
            raise OSError("statement failed")
        return Rows([(self.schema,)]) if "current_schema" in statement else Rows(self.rows)


def lane_reader_cases() -> dict:
    out: dict = {}
    body = {"id": TASK, "status": "cancelled"}

    def reader_case(name, schema, rows, call, *, fail_on=None, connect_error=None):
        with case_ws() as ws:
            events: list = []

            def connect(dsn, **kwargs):
                events.append(["connect", dsn, kwargs])
                if connect_error is not None:
                    raise connect_error
                return Connection(schema, rows, events, fail_on)
            reader = A.LaneReader("dsn", "lane_a", connect=connect)
            out[name] = {"result": ws.att(lambda: call(reader)), "events": events}

    reader_case("get_returns_the_first_body", "lane_a", [(body,)], lambda r: r.get("tasks", TASK))
    reader_case("get_absent_is_none", "lane_a", [], lambda r: r.get("tasks", TASK))
    reader_case("scan_returns_every_body", "lane_a", [(body,), ({"id": "t2"},)], lambda r: r.scan("tasks"))
    reader_case("scan_of_nothing_is_empty", "lane_a", [], lambda r: r.scan("tasks"))
    reader_case("wrong_schema_refuses", "public", [(body,)], lambda r: r.get("tasks", TASK))
    reader_case("wrong_schema_refuses_scan", "public", [(body,)], lambda r: r.scan("tasks"))
    reader_case("unreachable_lane_is_unreadable", "lane_a", [], lambda r: r.get("tasks", TASK),
                connect_error=OSError("connection refused"))
    reader_case("statement_failure_is_unreadable", "lane_a", [(body,)], lambda r: r.scan("tasks"), fail_on="documents")
    reader_case("schema_probe_failure_is_unreadable", "lane_a", [], lambda r: r.get("tasks", TASK), fail_on="current_schema")
    reader_case("a_refusal_from_connect_passes_through", "lane_a", [], lambda r: r.get("tasks", TASK),
                connect_error=A.FleetRefused("lane_custom", "f"))
    reader = A.LaneReader("dsn", "lane_a", connect=lambda *_a, **_k: None)
    out["constructor_keeps_its_arguments"] = {"dsn": reader.dsn, "schema": reader.schema,
                                              "connect_is_the_given_one": callable(reader.connect)}
    default = A.LaneReader("dsn", "lane_a")
    out["default_connect_is_psycopgs"] = {"qualname": default.connect.__qualname__,
                                          "module": default.connect.__module__.split(".")[0]}
    return out


def fake_docker(ws, name: str, *, stdout: str = "", code: int = 0) -> Path:
    """A LABELLED `docker` executable: appends its argv (one line per argument, `--call--` between calls) to
    `<name>.argv`, prints `stdout` and exits `code`. It uses only shell builtins; nothing is started or queried."""
    path, log = ws.root / ("docker-" + name), ws.root / (name + ".argv")
    path.write_text("#!/bin/sh\nprintf '%s\\n' \"$@\" >> '" + str(log) + "'\nprintf '%s\\n' '--call--' >> '" + str(log)
                    + "'\nprintf '%s\\n' '" + stdout + "'\nexit " + str(code) + "\n", encoding="utf-8")
    os.chmod(path, 0o755)
    return path


def docker_argv(ws, name: str) -> list:
    log = ws.root / (name + ".argv")
    if not log.exists():
        return []
    calls, current = [], []
    for line in log.read_text(encoding="utf-8").splitlines():
        if line == "--call--":
            calls.append(current)
            current = []
        else:
            current.append(line)
    return calls


def docker_state_cases() -> dict:
    out: dict = {}
    scripted = {"exited_255": ("exited 255", 0), "running_zero": ("running 0", 0), "negative_exit_code": ("exited -1", 0),
                "exit_code_not_a_number": ("exited abc", 0), "one_token": ("exited", 0),
                "three_tokens": ("exited 1 extra", 0), "empty_output": ("", 0), "nonzero_return_with_output": ("exited 1", 1),
                "nonzero_return_no_output": ("", 125), "extra_spaces": ("   dead    137   ", 0)}
    for name, (stdout, code) in scripted.items():
        with case_ws() as ws:
            path = fake_docker(ws, name, stdout=stdout, code=code)
            out[name] = {"result": ws.att(lambda: A.docker_state(CONTAINER, docker=str(path))), "argv": ws.n(docker_argv(ws, name))}
    with case_ws() as ws:
        missing = ws.root / "no-such-docker"
        out["missing_executable"] = {"result": ws.att(lambda: A.docker_state(CONTAINER, docker=str(missing)))}
    with case_ws() as ws:
        path = ws.root / "docker-not-executable"
        path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        out["not_executable"] = {"result": ws.att(lambda: A.docker_state(CONTAINER, docker=str(path)))}
    return out


# ---- group slots ----------------------------------------------------------------------------------------------------

def group_slots() -> dict:
    out: dict = {}
    operation = {"id": OPERATION, "correlation_id": CORRELATION}

    def recorded(name, calls):
        with case_ws() as ws:
            out["recorded_" + name] = ws.att(lambda: A.recorded_slots({**operation, "calls": calls} if calls is not _ABSENT else operation))

    _ABSENT = object()
    recorded("absent", _ABSENT)
    recorded("calls_not_a_document", "x")
    recorded("slots_not_a_list", {"slots": {"id": SLOT}})
    recorded("slots_empty", {"slots": []})
    recorded("two_slots", {"slots": [{"id": SLOT, "kind": "task", "provider": "claude"}, {"id": OTHER_SLOT, "kind": "review"}]})
    recorded("non_document_and_non_string_ids_dropped", {"slots": ["x", {"id": 7}, {"id": None}, {"kind": "task"}, {"id": SLOT, "kind": "task"}]})
    recorded("duplicate_ids_keep_the_last", {"slots": [{"id": SLOT, "kind": "a"}, {"id": SLOT, "kind": "b"}]})
    out["recorded_operation_not_a_document_raises"] = _direct(lambda: A.recorded_slots("x"))

    def slot(name, budget, *, document=None, calls=None, correlation=CORRELATION):
        document = document or evidence()
        op = {**operation, **({"calls": calls} if calls is not None else {})}
        with case_ws() as ws:
            out["slot_" + name] = {"result": ws.att(lambda: A.machine_slot(document, budget, op)), "slot_reads": budget.reads}

    slot("bound_by_ledger_purpose", ledger())
    slot("purpose_with_a_kind_with_colons", ledger(purpose=CORRELATION + ":task:retry"))
    slot("purpose_is_the_bare_correlation_prefix", ledger(purpose=CORRELATION + ":"))
    slot("purpose_equals_the_correlation", ledger(purpose=CORRELATION))
    slot("purpose_of_other_work", ledger(purpose="operation:op-other:task"))
    slot("purpose_of_a_longer_correlation", ledger(purpose="operation:op-10:task"))
    slot("purpose_not_a_string_and_no_record", ledger(purpose=None))
    slot("purpose_number_and_no_record", ledger(purpose=7))
    slot("unknown_id", Ledger([]))
    slot("duplicate_rows", Ledger([ledger().rows[1], ledger().rows[1]]))
    slot("unreadable", ledger(unreadable="ValueError"))
    slot("unreadable_false_is_readable", ledger(unreadable=False))
    slot("legacy_row_unbound", Ledger([{"id": SLOT, "host": "h", "status": "used", "outcome": "interrupted_unknown"}]))
    legacy = Ledger([{"id": SLOT, "host": "h", "status": "used", "outcome": "interrupted_unknown", "provider": "claude",
                      "model": "m"}])
    slot("bound_by_operation_calls", legacy, calls={"slots": [{"id": SLOT, "kind": "task", "provider": "claude"}]})
    slot("operation_calls_provider_absent", legacy, calls={"slots": [{"id": SLOT, "kind": "task"}]})
    slot("operation_calls_kind_absent", legacy, calls={"slots": [{"id": SLOT, "provider": "claude"}]})
    slot("operation_calls_provider_from_the_record_not_the_row",
         Ledger([{"id": SLOT, "status": "used", "provider": "claude"}]), calls={"slots": [{"id": SLOT, "kind": "k", "provider": "other"}]})
    slot("both_agree_on_the_provider", ledger(), calls={"slots": [{"id": SLOT, "kind": "task", "provider": "claude"}]})
    slot("both_disagree_on_the_provider", ledger(), calls={"slots": [{"id": SLOT, "kind": "task", "provider": "another-provider"}]})
    slot("both_present_record_provider_absent_is_fine", ledger(), calls={"slots": [{"id": SLOT, "kind": "task"}]})
    slot("record_present_row_provider_absent_and_record_names_one",
         ledger(provider=None), calls={"slots": [{"id": SLOT, "kind": "task", "provider": "claude"}]})
    slot("foreign_purpose_beats_a_recorded_slot", ledger(purpose="operation:op-other:task"),
         calls={"slots": [{"id": SLOT, "kind": "task", "provider": "claude"}]})
    slot("a_reserved_row_passes_the_adapter", ledger(status="reserved", outcome=None))
    slot("recorded_slot_of_another_id_is_not_a_binding", legacy, calls={"slots": [{"id": OTHER_SLOT, "kind": "task"}]})
    slot("evidence_names_the_unrelated_slot", ledger(), document=evidence(**{"machine_slot": {"id": OTHER_SLOT, "outcome": "accepted"}}))
    return out


def _direct(call):
    """The exception type of a direct call that raises something other than a refusal (recorded by type only)."""
    try:
        return {"returned": call()}
    except Exception as exc:  # the failure type is the characterized result
        return {"raised_type": type(exc).__name__}


# ---- group runner ---------------------------------------------------------------------------------------------------

def journal_lines(*lines) -> bytes:
    return ("\n".join(json.dumps(line, sort_keys=True) for line in lines) + "\n").encode("utf-8")


def start(run_id):
    return {"event": "start", "run_id": run_id, "timestamp": NOW}


def exit_(run_id):
    return {"event": "exit", "run_id": run_id, "final_exit_code": 0, "timestamp": NOW}


FINISHED = journal_lines(start("0" * 32), exit_("0" * 32), start("1" * 32),
                         {"event": "finish", "run_id": "1" * 32, "reason": "ok", "timestamp": NOW}, exit_("1" * 32))
OPEN = journal_lines(start("0" * 32), exit_("0" * 32), start("1" * 32))


def group_runner() -> dict:
    out: dict = {}

    def journal_case(name, data=None, *, path=None, prepare=None):
        with case_ws() as ws:
            target = path(ws) if path else ws.root / "fleet-journal.log"
            if data is not None:
                write(target, data)
            facts = prepare(ws, target) if prepare else {}
            out["journal_" + name] = {"result": ws.att(lambda: A.runner_state(target)), **(facts or {})}

    journal_case("finished_run_is_stopped", FINISHED)
    journal_case("open_run_is_running", OPEN)
    journal_case("missing_file_is_unknown", path=lambda ws: ws.root / "absent.log")
    journal_case("empty_file_has_no_recorded_run", b"")
    journal_case("binary_file_is_unreadable", b"\xff\xfe\x00")
    journal_case("only_blank_lines", b"\n\n\n")
    journal_case("garbage_lines_are_skipped", b"{ nope\n" + FINISHED + b"\n[1,2]\n\"x\"\n")
    journal_case("non_document_lines_only", b"[1]\n2\n\"x\"\nnull\n")
    journal_case("run_id_not_a_string_is_skipped", journal_lines({"event": "start", "run_id": 7}, start("1" * 32), exit_("1" * 32)))
    journal_case("exit_only_is_no_recorded_run", journal_lines(exit_("1" * 32)))
    journal_case("newest_start_decides", journal_lines(start("a"), exit_("a"), start("b")))
    journal_case("an_exit_of_an_earlier_run_does_not_close_the_newest", journal_lines(start("a"), start("b"), exit_("a")))
    journal_case("an_exit_before_its_start_still_closes_it", journal_lines(exit_("a"), start("a")))
    journal_case("unknown_events_ignored", journal_lines({"event": "finish", "run_id": "a"}, {"event": "weird", "run_id": "a"}))
    journal_case("duplicate_start_of_one_run", journal_lines(start("a"), start("a"), exit_("a")))
    journal_case("crlf_lines", b'{"event": "start", "run_id": "a"}\r\n{"event": "exit", "run_id": "a"}\r\n')
    journal_case("the_path_is_a_directory", path=lambda ws: ws.root / "a-directory",
                 prepare=lambda ws, target: target.mkdir())
    journal_case("the_path_is_a_symlink_to_a_journal", path=lambda ws: ws.root / "link.log",
                 prepare=lambda ws, target: (write(ws.root / "real.log", FINISHED), symlink(ws.root / "real.log", target, directory=False), None)[-1])

    def unreadable(ws, target):
        write(target, FINISHED)
        os.chmod(target, 0)
        return {"not_root": not_root()}
    journal_case("unreadable_file_is_unknown_without_a_digest", path=lambda ws: ws.root / "locked.log", prepare=unreadable)
    # the journal window: only the newest JOURNAL_LINES lines are read
    journal_case("the_start_beyond_the_window_is_not_read",
                 journal_lines(start("a"), exit_("a")) + b"{}\n" * A.JOURNAL_LINES)
    journal_case("a_start_inside_the_window_is_read",
                 b"{}\n" * (A.JOURNAL_LINES - 1) + journal_lines(start("a")))
    journal_case("a_start_at_the_window_edge",
                 journal_lines(start("a")) + b"{}\n" * (A.JOURNAL_LINES - 1))
    with case_ws() as ws:
        out["journal_none_is_unknown"] = {"result": ws.att(lambda: A.runner_state(None))}
        out["journal_given_as_a_string_path"] = {"result": ws.att(lambda: A.runner_state(str(write(ws.root / "s.log", FINISHED))))}
    out["journal_window"] = {"lines": A.JOURNAL_LINES}
    out["listed_runs"] = group_listed_runs()
    out["active_runs"] = group_active_runs()
    return out


def runs_world(ws):
    runtime = ws.root / "rt-a"
    (runtime.joinpath(*A.RUN_ROOT)).mkdir(parents=True)
    return runtime


def group_listed_runs() -> dict:
    out: dict = {}

    def listed(name, prepare=None):
        with case_ws() as ws:
            runtime = runs_world(ws)
            facts = prepare(ws, runtime) if prepare else None
            view = ws.att(lambda: A.listed_runs(str(runtime), "moves[].a"))
            out[name] = {"result": view, "runs_root_exists_after": runtime.joinpath(*A.RUN_ROOT).exists(), **(facts or {})}

    listed("initialized_and_empty")
    listed("one_record", lambda ws, rt: run_record(rt, "/w1", run_id="a" * 32, container_name="n1") and None)
    listed("two_records_are_returned_in_name_order",
           lambda ws, rt: (run_record(rt, "/w2", run_id="b" * 32), run_record(rt, "/w1", run_id="a" * 32), None)[-1])
    listed("a_file_beside_the_runs_is_not_a_run", lambda ws, rt: write(rt.joinpath(*A.RUN_ROOT) / "stray.txt", b"x") and None)
    listed("a_run_directory_without_a_record",
           lambda ws, rt: rt.joinpath(*A.RUN_ROOT, "ab" * 16).mkdir() or None)
    listed("a_record_that_is_not_json_is_returned_unreadable",
           lambda ws, rt: write(rt.joinpath(*A.RUN_ROOT, "ab" * 16, "run.json"), b"{ not json") and None)
    listed("a_record_that_is_unreadable_by_permission",
           lambda ws, rt: (run_record(rt, "/w1", run_id="a" * 32), os.chmod(rt.joinpath(*A.RUN_ROOT, "a" * 32, "run.json"), 0),
                           {"not_root": not_root()})[-1])
    listed("the_runs_directory_cannot_be_enumerated",
           lambda ws, rt: (os.chmod(rt.joinpath(*A.RUN_ROOT), 0), {"not_root": not_root()})[-1])
    listed("the_runs_root_is_missing", lambda ws, rt: shutil.rmtree(rt.joinpath(*A.RUN_ROOT)) or None)
    listed("the_runs_root_is_a_file",
           lambda ws, rt: (shutil.rmtree(rt.joinpath(*A.RUN_ROOT)), write(rt.joinpath(*A.RUN_ROOT), b"x"), None)[-1])
    listed("the_runtime_is_missing", lambda ws, rt: shutil.rmtree(rt) or None)
    listed("the_runtime_is_a_file", lambda ws, rt: (shutil.rmtree(rt), write(rt, b"x"), None)[-1])
    with case_ws() as ws:
        runtime = runs_world(ws)
        out["the_runtime_is_a_symlink_to_a_runtime"] = {"result": ws.att(
            lambda: A.listed_runs(str(symlink(runtime, ws.root / "alias")), "f"))}
    return out


def group_active_runs() -> dict:
    out: dict = {}

    def active(name, state, prepare=None):
        with case_ws() as ws:
            runtime = runs_world(ws)
            if prepare:
                prepare(runtime)
            docker = Docker(state)
            out[name] = {"result": ws.att(lambda: A.active_runs(str(runtime), "a", docker)), "docker_ids": docker.calls}

    def records(*specs):
        def build(runtime):
            for index, (run_id, overrides) in enumerate(specs):
                run_record(runtime, "/w%d" % index, run_id=run_id, **overrides)
        return build

    active("no_runs", EXITED)
    active("one_stopped_run", EXITED, records(("a" * 32, {})))
    active("one_running_run", RUNNING, records(("a" * 32, {})))
    active("a_dead_and_a_created_run_are_stopped", lambda cid: {"status": "dead" if cid == "c1" else "created"},
           records(("a" * 32, {"container": "c1"}), ("b" * 32, {"container": "c2"})))
    active("one_running_of_two", lambda cid: RUNNING if cid == "c2" else EXITED,
           records(("a" * 32, {"container": "c1"}), ("b" * 32, {"container": "c2"})))
    active("two_running_runs_are_two", RUNNING,
           records(("a" * 32, {"container": "c1"}), ("b" * 32, {"container": "c2"})))
    active("removed_and_refused_runs_are_never_asked", RUNNING,
           records(("a" * 32, {"state": "removed"}), ("b" * 32, {"state": "refused", "container": ""}), ("c" * 32, {})))
    active("a_removed_run_with_no_container_needs_no_answer", None, records(("a" * 32, {"state": "removed", "container": None})))
    active("docker_cannot_answer", None, records(("a" * 32, {})))
    active("docker_answers_none_for_the_second_run_only", lambda cid: None if cid == "c2" else EXITED,
           records(("a" * 32, {"container": "c1"}), ("b" * 32, {"container": "c2"})))
    active("record_without_a_container", EXITED, records(("a" * 32, {"container": None})))
    active("record_with_an_empty_container", EXITED, records(("a" * 32, {"container": ""})))
    active("record_with_a_non_string_container", EXITED, records(("a" * 32, {"container": 7})))
    active("record_state_unreadable_in_the_document", EXITED, records(("a" * 32, {"state": "unreadable"})))
    active("a_status_outside_the_stopped_states_counts", {"status": "paused"}, records(("a" * 32, {})))
    active("an_answer_without_a_status_counts", {}, records(("a" * 32, {})))

    def broken(runtime):
        write(runtime.joinpath(*A.RUN_ROOT, "ab" * 16, "run.json"), b"{ not json")
    active("an_unreadable_record", EXITED, broken)
    active("a_run_directory_without_a_record", EXITED, lambda rt: rt.joinpath(*A.RUN_ROOT, "ab" * 16).mkdir())
    with case_ws() as ws:
        docker = Docker(EXITED)
        out["the_runtime_is_missing"] = {"result": ws.att(lambda: A.active_runs(str(ws.root / "absent"), "a", docker)),
                                         "docker_ids": docker.calls}
    return out


# ---- group checkouts ------------------------------------------------------------------------------------------------

@contextlib.contextmanager
def ceiling(ws):
    """Git discovery never climbs above this case's root (the not-a-repository cases must not find an outer repository)."""
    saved = os.environ.get("GIT_CEILING_DIRECTORIES")
    os.environ["GIT_CEILING_DIRECTORIES"] = str(ws.root.parent)
    try:
        yield
    finally:
        if saved is None:
            os.environ.pop("GIT_CEILING_DIRECTORIES", None)
        else:
            os.environ["GIT_CEILING_DIRECTORIES"] = saved


class Source:
    """A `source=` double for `checkout_identity`: answers `_run("rev-list", ...)` with a scripted process."""

    def __init__(self, stdout, code=0):
        self.stdout, self.code, self.calls = stdout, code, []

    def _run(self, *args):
        self.calls.append(list(args))
        return subprocess.CompletedProcess(list(args), self.code, self.stdout, b"")


def group_checkouts() -> dict:
    out: dict = {}
    with case_ws() as ws, ceiling(ws):
        repo = ws.root / "old" / "repo"
        base = make_repo(ws, repo, mode_files=[("bin/tool.sh", b"#!/bin/sh\n", True), ("docs/plain.md", b"plain\n", False)])
        copy = clone(ws, repo, ws.root / "new" / "clone")
        shared = clone(ws, repo, ws.root / "new" / "shared", "--shared")
        stranger = ws.root / "new" / "stranger"
        make_repo(ws, stranger, goal=b"another history\n")
        worktree = ws.root / "new" / "worktree"
        git(ws, repo, "worktree", "add", "-q", "--detach", str(worktree))
        plain = ws.root / "new" / "not-a-repo"
        plain.mkdir(parents=True)
        empty = ws.root / "new" / "empty-repo"
        empty.mkdir()
        git(ws, empty, "init", "-q", "-b", "main")
        two_roots = ws.root / "new" / "two-roots"
        clone(ws, repo, two_roots)
        git(ws, two_roots, "checkout", "-q", "--orphan", "other")
        write(two_roots / "other.txt", b"other\n")
        git(ws, two_roots, "add", "other.txt")
        git(ws, two_roots, "commit", "-q", "-m", "Second root")
        second = git(ws, two_roots, "rev-parse", "HEAD")
        out["fixture"] = {"base_revision": base, "second_root": second}
        ident = {}
        for name, path in (("original", repo), ("clone", copy), ("shared_clone", shared), ("stranger", stranger),
                           ("worktree", worktree), ("two_roots", two_roots), ("not_a_repository", plain), ("empty_repository", empty),
                           ("missing_path", ws.root / "absent")):
            ident[name] = ws.att(lambda p=path: A.checkout_identity(str(p)))
        out["checkout_identity"] = ident
        out["checkout_identity"]["relationships"] = {
            "original_equals_clone": ident["original"] == ident["clone"],
            "original_equals_shared_clone": ident["original"] == ident["shared_clone"],
            "original_equals_worktree": ident["original"] == ident["worktree"],
            "original_equals_stranger": ident["original"] == ident["stranger"],
            "two_roots_differs": ident["two_roots"] != ident["original"]}
        doubles = {}
        for name, source in (("sorted_roots", Source(b"bb\naa\n")), ("same_roots_another_order", Source(b"aa\nbb\n")),
                             ("duplicates_are_kept", Source(b"aa\naa\n")), ("non_ascii_is_replaced", Source(b"\xff\xfe\n")),
                             ("nonzero_with_output", Source(b"aa\n", 128)), ("no_output", Source(b"")),
                             ("whitespace_only", Source(b" \n \n"))):
            doubles[name] = {"result": ws.att(lambda s=source: A.checkout_identity("ignored", s)), "argv": source.calls}
        out["checkout_identity_source_double"] = doubles
        out["independent"] = {name: ws.att(lambda p=path: A.independent(p)) for name, path in (
            ("original", repo), ("clone", copy), ("shared_clone", shared), ("worktree", worktree), ("stranger", stranger),
            ("not_a_repository", plain), ("a_subdirectory_of_the_repository", repo / "docs"),
            ("a_missing_path", ws.root / "absent"))}
        bare = ws.root / "new" / "bare.git"
        git(ws, ws.root, "clone", "--quiet", "--bare", str(repo), str(bare))
        out["independent"]["a_bare_repository"] = ws.att(lambda: A.independent(bare))
        alternates = ws.root / "new" / "alternates"
        clone(ws, repo, alternates)
        write(alternates / ".git" / "objects" / "info" / "alternates", str(repo / ".git" / "objects") + "\n")
        out["independent"]["a_clone_that_names_alternates"] = ws.att(lambda: A.independent(alternates))
        out["writable"] = group_writable(ws)
        bindings = {}
        good = goal_of(base)
        jobs = {
            "matching_goal": [job("op-1", "a", "queued", good)],
            "sorted_by_job_id": [job("op-2", "a", "queued", good), job("op-1", "a", "queued", good)],
            "no_jobs": [],
            "base_missing": [job("op-1", "a", "queued", goal_of("9" * 40))],
            "goal_path_missing_at_base": [job("op-1", "a", "queued", {**good, "path": "docs/none.md"})],
            "goal_sha_mismatch": [job("op-1", "a", "queued", {**good, "sha256": "0" * 64})],
            "goal_is_an_executable_file": [job("op-1", "a", "queued", {**good, "path": "bin/tool.sh", "sha256": sha(b"#!/bin/sh\n")})],
            "goal_is_a_directory": [job("op-1", "a", "queued", {**good, "path": "docs", "sha256": sha(b"")})],
            "another_plain_file": [job("op-1", "a", "queued", {**good, "path": "docs/plain.md", "sha256": sha(b"plain\n")})],
            "base_revision_not_a_commit_name": [job("op-1", "a", "queued", {**good, "base_revision": "main"})],
            "base_revision_abbreviated": [job("op-1", "a", "queued", {**good, "base_revision": base[:12]})],
            "mixed": [job("op-1", "a", "queued", good), job("op-2", "a", "queued", goal_of("9" * 40)),
                      job("op-3", "a", "queued", {**good, "sha256": "1" * 64})]}
        for name, rows in jobs.items():
            bindings[name] = ws.att(lambda r=rows: A.queued_bindings(str(repo), r))
        bindings["read_from_the_clone"] = ws.att(lambda: A.queued_bindings(str(copy), jobs["matching_goal"]))
        bindings["read_from_the_stranger"] = ws.att(lambda: A.queued_bindings(str(stranger), jobs["matching_goal"]))
        bindings["read_from_a_non_repository"] = ws.att(lambda: A.queued_bindings(str(plain), jobs["matching_goal"]))
        bindings["read_from_a_missing_path"] = ws.att(lambda: A.queued_bindings(str(ws.root / "absent"), jobs["matching_goal"]))
        bindings["job_without_a_goal_raises"] = _direct(lambda: A.queued_bindings(str(repo), [{"id": "op-1"}]))
        out["queued_bindings"] = bindings
        out["resolved_directory"] = group_resolved_directory(ws, repo)
    return out


def group_writable(ws) -> dict:
    out: dict = {}
    base = ws.root / "writable"
    base.mkdir()
    plain = base / "plain"
    plain.mkdir()
    out["a_writable_directory"] = {"result": A.writable(plain), "left_behind": sorted_tree(plain)}
    locked = base / "locked"
    locked.mkdir()
    os.chmod(locked, 0o500)
    out["a_read_only_directory"] = {"result": A.writable(locked), "left_behind": sorted_tree(locked), "not_root": not_root()}
    os.chmod(locked, 0o700)
    out["a_missing_directory"] = {"result": A.writable(base / "absent")}
    out["a_file_is_not_writable_into"] = {"result": A.writable(write(base / "file", b"x"))}
    blocked = base / "blocked"
    blocked.mkdir()
    probe = blocked / (".zeus-relocation-probe-" + A.digest(str(blocked))[:16])
    probe.mkdir()
    out["the_probe_name_is_a_directory"] = {"result": A.writable(blocked), "left_behind": sorted_tree(blocked)}
    return out


def group_resolved_directory(ws, repo: Path) -> dict:
    out: dict = {}
    base = ws.root / "resolved"
    base.mkdir()
    real = base / "real"
    real.mkdir()
    link = symlink(real, base / "link")
    file = write(base / "file", b"x")
    cases = {"a_real_directory": real, "a_symlink_to_a_directory": link, "a_missing_path": base / "absent", "a_file": file,
             "a_dotdot_spelling": base / "real" / ".." / "real", "a_trailing_slash_spelling": str(real) + "/",
             "a_relative_path": "relative/dir", "an_empty_string": ""}
    for name, value in cases.items():
        out[name] = ws.att(lambda v=value: A.resolved_directory(str(v), "moves[].a.repository.to"))
    out["a_symlink_inside_the_path"] = ws.att(
        lambda: A.resolved_directory(str(symlink(base, ws.root / "alias-of-base") / "real"), "f"))
    out["the_source_repository"] = ws.att(lambda: A.resolved_directory(str(repo), "f"))
    return out


# ---- group copy_manifest --------------------------------------------------------------------------------------------

class Copy:
    """One runtime move: `old/rt-a` -> `new/rt-a`, rows written for real on both ends (M7 `copy_manifest`)."""

    def __init__(self, ws):
        self.ws = ws
        self.old, self.new = ws.root / "old" / "rt-a", ws.root / "new" / "rt-a"
        self.old.mkdir(parents=True, exist_ok=True)
        self.new.mkdir(parents=True, exist_ok=True)
        self.serial = 0

    def entry(self, relative: str, data: bytes = b"copied evidence\n", *, source_root=None, target_root=None, write_source=True,
              write_destination=True) -> dict:
        source = Path(source_root or self.old).joinpath(*relative.split("/"))
        destination = Path(target_root or self.new).joinpath(*relative.split("/"))
        if write_source:
            write(source, data)
        if write_destination:
            write(destination, data)
        return {"source": str(source), "destination": str(destination), "sha256": sha(data), "bytes": len(data)}

    def manifest(self, entries, *, schema=None, raw: bytes | None = None, count=None, name=None) -> dict:
        self.serial += 1
        path = self.ws.root / (name or "copy-manifest-%d.json" % self.serial)
        if raw is None:
            document = {"schema": schema or A.COPY_MANIFEST_SCHEMA, "entries": entries}
            raw = json.dumps(document, sort_keys=True).encode("utf-8")
        path.write_bytes(raw)
        self.ws.label(sha(raw), "manifest:" + path.name)  # the document names the temporary root: its digest varies
        return {"path": str(path), "sha256": sha(raw), "entries": len(entries) if count is None else count}

    def request(self, declared: dict, *, runtime="default", repository=None, lane="a") -> dict:
        runtime = {"from": str(self.old), "to": str(self.new)} if runtime == "default" else runtime
        return {"schema": "urn:zeus:fleet-relocation:1", "fleet": "fleet-1", "operator": "owner",
                "moves": [{"lane": lane, "repository": repository, "runtime": runtime}], "copy_manifest": declared}

    def simple(self, entries, **kwargs) -> dict:
        return self.request(self.manifest(entries), **kwargs)


def copy_case(out, name, build, *, before=None):
    """`build(copy)` returns the request (and may return `(request, facts)`); the verification is recorded."""
    with case_ws() as ws:
        world = Copy(ws)
        built = build(world)
        request, facts = built if isinstance(built, tuple) else (built, {})
        view = ws.att(lambda: A.verify_copy_manifest(request))
        out[name] = {"result": view, **facts}


def group_copy_manifest() -> dict:
    out: dict = {}
    # --- valid manifests
    copy_case(out, "ok_single_entry", lambda w: w.simple([w.entry("artifacts/evidence.json")]))
    copy_case(out, "ok_mixed_case_nested", lambda w: w.simple([w.entry("Artifacts/F2H/Deep/Evidence.JSON")]))
    copy_case(out, "ok_deeply_nested", lambda w: w.simple([w.entry("artifacts/f2h/artifacts/deep/evidence.json")]))
    copy_case(out, "ok_zero_byte_file", lambda w: w.simple([w.entry("artifacts/empty.json", b"")]))
    copy_case(out, "ok_two_entries_in_one_root", lambda w: w.simple([w.entry("a.json", b"one"), w.entry("b.json", b"two")]))
    copy_case(out, "ok_a_file_longer_than_one_read", lambda w: w.simple([w.entry("big.bin", b"x" * (A.READ_BYTES + 5))]))

    def repo_and_runtime(w):
        repo_old, repo_new = w.ws.root / "old" / "repo", w.ws.root / "new" / "repo"
        entries = [w.entry("runtime.json"), w.entry("docs/GOAL.md", b"goal", source_root=repo_old, target_root=repo_new)]
        return w.simple(entries, repository={"from": str(repo_old), "to": str(repo_new)})
    copy_case(out, "ok_repository_and_runtime_both_covered", repo_and_runtime)

    def repository_only(w):
        repo_old, repo_new = w.ws.root / "old" / "repo", w.ws.root / "new" / "repo"
        return w.simple([w.entry("docs/GOAL.md", b"goal", source_root=repo_old, target_root=repo_new)], runtime=None,
                        repository={"from": str(repo_old), "to": str(repo_new)})
    copy_case(out, "ok_repository_only_needs_no_runtime_coverage", repository_only)
    copy_case(out, "ok_no_entries_when_no_runtime_moves",
              lambda w: w.simple([], runtime=None, repository={"from": str(w.old), "to": str(w.new)}))
    copy_case(out, "refuses_no_entries_when_a_runtime_moves", lambda w: w.simple([]))

    def two_moves(w):
        second_old, second_new = w.ws.root / "old" / "rt-b", w.ws.root / "new" / "rt-b"
        entries = [w.entry("a.json"), w.entry("b.json", source_root=second_old, target_root=second_new)]
        request = w.simple(entries)
        request["moves"].append({"lane": "b", "repository": None, "runtime": {"from": str(second_old), "to": str(second_new)}})
        return request
    copy_case(out, "ok_two_lanes_each_covered", two_moves)

    def second_uncovered(w):
        request = w.simple([w.entry("a.json")])
        second_old, second_new = w.ws.root / "old" / "rt-b", w.ws.root / "new" / "rt-b"
        second_old.mkdir()
        second_new.mkdir()
        request["moves"].append({"lane": "b", "repository": None, "runtime": {"from": str(second_old), "to": str(second_new)}})
        return request
    copy_case(out, "refuses_a_second_lane_runtime_uncovered", second_uncovered)
    # --- the manifest document
    copy_case(out, "refuses_manifest_missing", lambda w: w.request({"path": str(w.ws.root / "absent.json"), "sha256": "a" * 64, "entries": 1}))
    copy_case(out, "refuses_manifest_digest_mismatch", lambda w: w.request({**w.manifest([w.entry("a.json")]), "sha256": "0" * 64}))
    copy_case(out, "refuses_manifest_not_json", lambda w: w.request(w.manifest([], raw=b"{ not json", count=0)))
    copy_case(out, "refuses_manifest_not_utf8", lambda w: w.request(w.manifest([], raw=b"\xff\xfe", count=0)))
    copy_case(out, "refuses_manifest_not_an_object", lambda w: w.request(w.manifest([], raw=b"[1, 2]", count=0)))
    copy_case(out, "refuses_manifest_wrong_schema", lambda w: w.request(
        w.manifest([w.entry("a.json")], schema="urn:zeus:copy-manifest:0")))
    copy_case(out, "refuses_manifest_entries_not_a_list", lambda w: w.request(
        w.manifest([], raw=json.dumps({"schema": A.COPY_MANIFEST_SCHEMA, "entries": {}}).encode(), count=0)))
    copy_case(out, "refuses_manifest_entry_count_differs", lambda w: w.request(w.manifest([w.entry("a.json")], count=2)))
    copy_case(out, "refuses_manifest_path_is_a_directory", lambda w: w.request(
        {"path": str(w.ws.root), "sha256": "a" * 64, "entries": 1}))
    copy_case(out, "refuses_manifest_unreadable_by_permission", lambda w: _locked_manifest(w))
    # --- the entries
    copy_case(out, "refuses_entry_not_an_object", lambda w: w.request(w.manifest(["x"])))
    copy_case(out, "refuses_entry_extra_field", lambda w: w.simple([{**w.entry("a.json"), "mode": "644"}]))
    copy_case(out, "refuses_entry_missing_field", lambda w: w.simple([{k: v for k, v in w.entry("a.json").items() if k != "bytes"}]))
    copy_case(out, "refuses_null_digest_beside_a_missing_file", lambda w: w.simple([{**w.entry("never.json", write_destination=False), "sha256": None}]))
    copy_case(out, "refuses_digest_uppercase", lambda w: w.simple([{**w.entry("a.json"), "sha256": sha(b"copied evidence\n").upper()}]))
    copy_case(out, "refuses_digest_short", lambda w: w.simple([{**w.entry("a.json"), "sha256": "abc"}]))
    copy_case(out, "refuses_digest_not_a_string", lambda w: w.simple([{**w.entry("a.json"), "sha256": 7}]))
    copy_case(out, "refuses_bytes_a_string", lambda w: w.simple([{**w.entry("a.json"), "bytes": "16"}]))
    copy_case(out, "refuses_bytes_a_boolean", lambda w: w.simple([{**w.entry("a.json"), "bytes": True}]))
    copy_case(out, "refuses_bytes_negative", lambda w: w.simple([{**w.entry("a.json"), "bytes": -1}]))
    copy_case(out, "refuses_bytes_above_the_limit", lambda w: w.simple([{**w.entry("a.json"), "bytes": A.MAX_COPY_BYTES + 1}]))
    copy_case(out, "refuses_bytes_a_float", lambda w: w.simple([{**w.entry("a.json"), "bytes": 16.0}]))
    copy_case(out, "refuses_relative_source", lambda w: w.simple([{**w.entry("a.json"), "source": "a.json"}]))
    copy_case(out, "refuses_relative_destination", lambda w: w.simple([{**w.entry("a.json"), "destination": "a.json"}]))
    copy_case(out, "refuses_unnormalized_source", lambda w: w.simple([{**w.entry("a.json"), "source": str(w.old) + "/x/../a.json"}]))
    copy_case(out, "refuses_trailing_separator_destination", lambda w: w.simple([{**w.entry("a.json"), "destination": str(w.new / "a.json") + "/"}]))
    copy_case(out, "refuses_destination_not_a_string", lambda w: w.simple([{**w.entry("a.json"), "destination": 7}]))
    copy_case(out, "refuses_outside_the_move", lambda w: w.simple([w.entry("a.json"), w.entry("b.txt", source_root=w.ws.root / "elsewhere", target_root=w.ws.root / "elsewhere2")]))
    copy_case(out, "refuses_renamed_copy", lambda w: w.simple([{**w.entry("a.json"), "destination": str(w.new / "other.json")}]))
    copy_case(out, "refuses_destination_below_another_relative_path", lambda w: w.simple([{**w.entry("a/x.json"), "destination": str(w.new / "b" / "x.json")}]))
    copy_case(out, "refuses_the_root_itself_as_a_destination", lambda w: w.simple([{**w.entry("a.json"), "destination": str(w.new)}]))
    copy_case(out, "refuses_duplicate_entry", lambda w: w.simple([w.entry("a.json"), w.entry("a.json")]))
    copy_case(out, "refuses_duplicate_source_under_another_destination", lambda w: _same_source_twice(w))

    def case_duplicate(w):
        facts = {"case_sensitive": case_sensitive(w.ws.root / "probe")}
        return w.simple([w.entry("a.json", b"one"), w.entry("A.json", b"two")]), facts
    copy_case(out, "refuses_names_that_differ_only_in_case_as_duplicates", case_duplicate)
    copy_case(out, "refuses_runtime_uncovered_by_a_repository_entry", lambda w: _repo_entry_only(w))
    # --- the bytes
    copy_case(out, "refuses_missing_destination", lambda w: w.simple([w.entry("never.json", write_destination=False)]))
    copy_case(out, "refuses_destination_directory_missing_below_the_root",
              lambda w: w.simple([w.entry("a/b/never.json", write_destination=False)]))
    copy_case(out, "refuses_destination_is_a_directory", lambda w: _destination_directory(w))
    copy_case(out, "refuses_destination_unreadable_by_permission", lambda w: _destination_locked(w))
    copy_case(out, "refuses_short_declared_bytes", lambda w: w.simple([{**w.entry("a.json"), "bytes": 2}]))
    copy_case(out, "refuses_longer_declared_bytes", lambda w: w.simple([{**w.entry("a.json"), "bytes": 100}]))
    copy_case(out, "refuses_tampered_destination", lambda w: w.simple([{**w.entry("a.json"), "destination": str(write(w.new / "a.json", b"copied evidence\ntampered"))}]))
    copy_case(out, "refuses_same_length_other_bytes", lambda w: w.simple([{**w.entry("a.json"), "destination": str(write(w.new / "a.json", b"copied EVIDENCE\n"))}]))
    copy_case(out, "refuses_zero_declared_with_content", lambda w: w.simple([{**w.entry("a.json"), "bytes": 0, "sha256": sha(b"")}]))
    copy_case(out, "ok_zero_declared_empty_destination", lambda w: w.simple([w.entry("a.json", b"")]))
    # --- physical ownership: links, roots, case, resolution
    copy_case(out, "refuses_child_link_to_the_source", lambda w: _child_link_to_source(w))
    copy_case(out, "refuses_destination_file_link_outside_the_target", lambda w: _file_link_outside(w))
    copy_case(out, "refuses_source_side_directory_link", lambda w: _source_side_link(w))
    copy_case(out, "refuses_source_root_alias", lambda w: _root_alias(w, "source"))
    copy_case(out, "refuses_destination_root_alias", lambda w: _root_alias(w, "destination"))
    copy_case(out, "refuses_dangling_destination_link", lambda w: _dangling(w))
    copy_case(out, "refuses_destination_link_to_a_contained_file", lambda w: _contained_file_link(w))
    copy_case(out, "refuses_destination_link_to_a_contained_directory", lambda w: _contained_dir_link(w))
    for side in ("source", "destination"):
        copy_case(out, "refuses_a_contained_redirection_on_the_" + side + "_side", lambda w, s=side: _contained_case_link(w, s))
    copy_case(out, "refuses_a_case_distinct_sibling_as_the_target", lambda w: _case_sibling(w))
    copy_case(out, "refuses_the_owners_case_distinct_symlink_reproduction", lambda w: _case_repro(w))
    copy_case(out, "refuses_missing_source", lambda w: w.simple([w.entry("a.json", write_source=False)]))
    copy_case(out, "refuses_source_root_missing", lambda w: _root_missing(w, "source"))
    copy_case(out, "refuses_destination_root_missing", lambda w: _root_missing(w, "destination"))
    copy_case(out, "refuses_source_root_is_a_file", lambda w: _root_file(w))
    copy_case(out, "refuses_a_looping_destination_chain", lambda w: _looping(w))
    copy_case(out, "refuses_a_looping_source_chain", lambda w: _looping_source(w))
    copy_case(out, "refuses_a_destination_under_a_file", lambda w: _under_a_file(w))
    # the pre-fix controls: with the physical check removed the lexical rules credit the redirection
    copy_case(out, "control_child_link_credited_without_the_ownership_check", lambda w: _control(w, _child_link_to_source))
    copy_case(out, "control_outside_file_link_credited_without_the_ownership_check", lambda w: _control(w, _file_link_outside))
    copy_case(out, "control_source_link_credited_without_the_ownership_check", lambda w: _control(w, _source_side_link))
    copy_case(out, "control_case_sibling_credited_without_the_ownership_check", lambda w: _control(w, _case_sibling))
    copy_case(out, "control_case_repro_credited_without_the_ownership_check", lambda w: _control(w, _case_repro))
    out["direct"] = group_direct_helpers()
    out["hashing"] = group_hashing()
    out["constants"] = {"ownership": A.COPY_OWNERSHIP, "schema": A.COPY_MANIFEST_SCHEMA, "entry_fields": sorted(A.COPY_ENTRY_FIELDS),
                        "movable": list(A.MOVABLE), "read_bytes": A.READ_BYTES, "max_copy_bytes": A.MAX_COPY_BYTES}
    return out


def _same_source_twice(w):
    """One source file claimed by two lanes' targets: the second row repeats the first row's source."""
    second_new = w.ws.root / "new" / "rt-b"
    first = w.entry("a.json")
    second = w.entry("a.json", target_root=second_new, write_source=False)
    request = w.simple([first, second])
    request["moves"].append({"lane": "b", "repository": None, "runtime": {"from": str(w.old), "to": str(second_new)}})
    return request


def _locked_manifest(w):
    request = w.simple([w.entry("a.json")])
    os.chmod(request["copy_manifest"]["path"], 0)
    return request, {"not_root": not_root()}


def _repo_entry_only(w):
    repo_old, repo_new = w.ws.root / "old" / "repo", w.ws.root / "new" / "repo"
    entry = w.entry("docs/GOAL.md", b"goal", source_root=repo_old, target_root=repo_new)
    return w.request(w.manifest([entry]), repository={"from": str(repo_old), "to": str(repo_new)})


def _destination_directory(w):
    entry = w.entry("a.json", write_destination=False)
    Path(entry["destination"]).mkdir()
    return w.simple([entry])


def _destination_locked(w):
    entry = w.entry("a.json")
    os.chmod(entry["destination"], 0)
    return w.simple([entry]), {"not_root": not_root()}


def _child_link_to_source(w):
    data = b"interrupted evidence\n"
    write(w.old / "artifacts" / "interrupted.json", data)
    symlink(w.old / "artifacts", w.new / "artifacts")
    entry = w.entry("artifacts/interrupted.json", data, write_source=False, write_destination=False)
    return w.simple([entry]), {"destination_reads_the_source": Path(entry["destination"]).resolve() == Path(entry["source"]).resolve(),
                               "destination_digest_matches": A.hash_bounded(Path(entry["destination"]), entry["bytes"]) ==
                                                              {"sha256": entry["sha256"], "bytes": entry["bytes"]}}


def _file_link_outside(w):
    data = b"stored somewhere this request never moves\n"
    outside = write(w.ws.root / "elsewhere" / "evidence.json", data)
    write(w.old / "artifacts" / "escape.json", data)
    (w.new / "artifacts").mkdir()
    symlink(outside, w.new / "artifacts" / "escape.json", directory=False)
    return w.simple([w.entry("artifacts/escape.json", data, write_source=False, write_destination=False)])


def _source_side_link(w):
    data = b"only ever on the target\n"
    write(w.new / "staged" / "evidence.json", data)
    symlink(w.new / "staged", w.old / "staged")
    return w.simple([w.entry("staged/evidence.json", data, write_source=False, write_destination=False)])


def _root_alias(w, side):
    data = b"aliased\n"
    if side == "source":
        write(w.old / "staged" / "evidence.json", data)
        write(w.new / "staged" / "evidence.json", data)
        alias = symlink(w.old, w.ws.root / "old" / "rt-a-alias")
        entry = w.entry("staged/evidence.json", data, source_root=alias, write_source=False, write_destination=False)
        return w.simple([entry], runtime={"from": str(alias), "to": str(w.new)})
    write(w.old / "staged" / "evidence.json", data)
    write(w.new / "staged" / "evidence.json", data)
    alias = symlink(w.new, w.ws.root / "new" / "rt-a-alias")
    entry = w.entry("staged/evidence.json", data, target_root=alias, write_source=False, write_destination=False)
    return w.simple([entry], runtime={"from": str(w.old), "to": str(alias)})


def _dangling(w):
    data = b"dangling\n"
    write(w.old / "a.json", data)
    symlink(w.new / "never-made.json", w.new / "a.json", directory=False)
    return w.simple([w.entry("a.json", data, write_source=False, write_destination=False)])


def _contained_file_link(w):
    data = b"real file inside the root\n"
    write(w.old / "a.json", data)
    write(w.new / "real.json", data)
    symlink(w.new / "real.json", w.new / "a.json", directory=False)
    return w.simple([w.entry("a.json", data, write_source=False, write_destination=False)])


def _contained_dir_link(w):
    data = b"real directory inside the root\n"
    write(w.old / "d" / "a.json", data)
    write(w.new / "real" / "a.json", data)
    symlink(w.new / "real", w.new / "d")
    return w.simple([w.entry("d/a.json", data, write_source=False, write_destination=False)])


def _contained_case_link(w, side):
    data = b"contained but redirected\n"
    facts = {"case_sensitive": case_sensitive(w.ws.root / "probe")}
    root, other = (w.old, w.new) if side == "source" else (w.new, w.old)
    write(other / "artifacts" / "Carried.json", data)
    write(root / "artifacts" / "carried.json", data)
    symlink(root / "artifacts" / "carried.json", root / "artifacts" / "Carried.json", directory=False)
    if not facts["case_sensitive"]:
        return w.simple([w.entry("artifacts/carried.json", data, write_source=False, write_destination=False)]), facts
    return w.simple([w.entry("artifacts/Carried.json", data, write_source=False, write_destination=False)]), facts


def _case_roots(w, parent: Path):
    facts = {"case_sensitive": case_sensitive(parent)}
    return facts


def _case_sibling(w):
    parent = w.ws.root / "new" / "case"
    facts = _case_roots(w, parent)
    target, sibling = parent / "rt", parent / "RT"
    target.mkdir(exist_ok=True)
    sibling.mkdir(exist_ok=True)
    data = b"synthetic equal bytes\n"
    write(sibling / "artifacts" / "evidence.json", data)
    entry = w.entry("artifacts/evidence.json", data, target_root=sibling, write_destination=False)
    return w.simple([entry], runtime={"from": str(w.old), "to": str(target)}), facts


def _case_repro(w):
    parent = w.ws.root / "new" / "repro"
    facts = _case_roots(w, parent)
    target, sibling = parent / "rt", parent / "RT"
    target.mkdir(exist_ok=True)
    sibling.mkdir(exist_ok=True)
    data = b"synthetic equal bytes\n"
    write(sibling / "artifacts" / "evidence.json", data)
    if facts["case_sensitive"]:
        symlink(sibling / "artifacts", target / "artifacts")
    entry = w.entry("artifacts/evidence.json", data, target_root=target, write_destination=False)
    return w.simple([entry], runtime={"from": str(w.old), "to": str(target)}), facts


def _root_missing(w, side):
    entry = w.entry("a.json")
    missing = w.ws.root / "gone"
    runtime = {"from": str(missing), "to": str(w.new)} if side == "source" else {"from": str(w.old), "to": str(missing)}
    row = {**entry, side: str(missing / "a.json")}
    return w.simple([row], runtime=runtime)


def _root_file(w):
    entry = w.entry("a.json")
    file = write(w.ws.root / "old" / "rt-file", b"x")
    return w.simple([{**entry, "source": str(file / "a.json")}], runtime={"from": str(file), "to": str(w.new)})


def _looping(w):
    data = b"resolution evidence\n"
    write(w.old / "artifacts" / "loop" / "evidence.json", data)
    (w.new / "artifacts").mkdir()
    symlink(w.new / "artifacts" / "loop-b", w.new / "artifacts" / "loop")
    symlink(w.new / "artifacts" / "loop", w.new / "artifacts" / "loop-b")
    return w.simple([w.entry("artifacts/loop/evidence.json", data, write_source=False, write_destination=False)])


def _looping_source(w):
    data = b"resolution evidence\n"
    write(w.new / "artifacts" / "loop" / "evidence.json", data)
    (w.old / "artifacts").mkdir()
    symlink(w.old / "artifacts" / "loop-b", w.old / "artifacts" / "loop")
    symlink(w.old / "artifacts" / "loop", w.old / "artifacts" / "loop-b")
    return w.simple([w.entry("artifacts/loop/evidence.json", data, write_source=False, write_destination=False)])


def _under_a_file(w):
    data = b"x"
    write(w.old / "a" / "b.json", data)
    write(w.new / "a", b"a file, not a directory")
    return w.simple([w.entry("a/b.json", data, write_source=False, write_destination=False)])


def _control(w, build):
    """The same request, verified with `_owned_copy` replaced by a no-op (the tests' `monkeypatch.setattr` control)."""
    built = build(w)
    request, facts = built if isinstance(built, tuple) else (built, {})
    with A.patched(_owned_copy=lambda *_a, **_k: None):
        try:
            verified = A.verify_copy_manifest(request)
        except Exception as exc:  # recorded by type and reason
            verified = {"raised": type(exc).__name__, "reason_code": getattr(exc, "reason_code", None)}
    return request, {**facts, "without_the_ownership_check": w.ws.n(verified)}


def group_hashing() -> dict:
    out: dict = {}
    with case_ws() as ws:
        base = ws.root / "hash"
        base.mkdir()
        files = {"empty": b"", "short": b"abc", "one_read": b"x" * A.READ_BYTES, "one_read_plus_five": b"y" * (A.READ_BYTES + 5),
                 "two_reads": b"z" * (2 * A.READ_BYTES)}
        for name, data in files.items():
            write(base / name, data)
        out["hash_file"] = {name: A.hash_file(base / name) for name in files}
        out["hash_file"]["matches_hashlib"] = {name: A.hash_file(base / name) == sha(data) for name, data in files.items()}
        out["hash_file"]["missing"] = A.hash_file(base / "absent")
        out["hash_file"]["directory"] = A.hash_file(base)
        locked = write(base / "locked", b"secret")
        os.chmod(locked, 0)
        out["hash_file"]["unreadable"] = A.hash_file(locked)
        out["hash_file"]["not_root"] = not_root()
        bounded = {}
        for name, limit in (("empty", 0), ("empty", 5), ("short", 3), ("short", 2), ("short", 0), ("short", 10),
                            ("one_read", A.READ_BYTES), ("one_read", A.READ_BYTES - 1), ("one_read_plus_five", A.READ_BYTES + 5),
                            ("one_read_plus_five", A.READ_BYTES), ("one_read_plus_five", 4), ("two_reads", 2 * A.READ_BYTES),
                            ("two_reads", A.READ_BYTES + 1)):
            bounded["%s_limit_%d" % (name, limit)] = A.hash_bounded(base / name, limit)
        bounded["missing"] = A.hash_bounded(base / "absent", 5)
        bounded["directory"] = A.hash_bounded(base, 5)
        bounded["unreadable"] = A.hash_bounded(locked, 6)
        bounded["reads_at_most_one_byte_past_the_limit"] = {
            "limit_2_reports_bytes": A.hash_bounded(base / "short", 2)["bytes"],
            "sha_is_of_the_bytes_read": A.hash_bounded(base / "short", 2)["sha256"] == sha(b"abc")}
        out["hash_bounded"] = bounded
    return out


def fake_info(mode, attributes=None):
    info = SimpleNamespace(st_mode=mode)
    if attributes is not None:
        info.st_file_attributes = attributes
    return info


def group_direct_helpers() -> dict:
    out: dict = {}
    # _relative: the casefolded comparison form (scheduling identity, not a filesystem rule)
    out["relative"] = {name: A.relative(inner, outer) for name, (inner, outer) in {
        "below": ("/a/b/c", "/a/b"), "equal": ("/a/b", "/a/b"), "not_below": ("/a/x", "/a/b"),
        "prefix_but_not_a_path_boundary": ("/a/bc", "/a/b"), "case_folded": ("/A/B/C", "/a/b"),
        "trailing_separators": ("/a/b/c/", "/a/b/"), "double_separators": ("/a//b//c", "/a/b"), "root": ("/a", "/"),
        "backslash_spelling": ("\\a\\b\\c", "/a/b"), "outer_is_below_inner": ("/a", "/a/b")}.items()}
    # _link_entry: a symlink, a Windows reparse point (attribute double) or neither
    REPARSE = 0x400
    out["link_entry"] = {
        "regular_file": A.link_entry(fake_info(stat.S_IFREG | 0o644)),
        "directory": A.link_entry(fake_info(stat.S_IFDIR | 0o755)),
        "symlink": A.link_entry(fake_info(stat.S_IFLNK | 0o777)),
        "w_b_reparse_attribute_on_a_directory": A.link_entry(fake_info(stat.S_IFDIR | 0o755, REPARSE)),
        "w_b_reparse_attribute_with_other_bits": A.link_entry(fake_info(stat.S_IFREG | 0o644, REPARSE | 0x20)),
        "w_b_directory_attribute_only": A.link_entry(fake_info(stat.S_IFDIR | 0o755, 0x10)),
        "w_b_no_attribute_field": A.link_entry(fake_info(stat.S_IFREG | 0o644, None)),
        "w_b_zero_attributes": A.link_entry(fake_info(stat.S_IFREG | 0o644, 0)),
        "reparse_constant_is_1024": getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", None)}
    with case_ws() as ws:
        base = ws.root / "chain"
        (base / "d").mkdir(parents=True)
        write(base / "d" / "f.txt", b"x")
        symlink(base / "d", base / "dlink")
        symlink(base / "d" / "f.txt", base / "flink", directory=False)
        symlink(base / "nowhere", base / "dangling")
        out["linked"] = {name: A.linked(path) for name, path in (
            ("a_real_file", base / "d" / "f.txt"), ("a_real_directory", base / "d"), ("a_directory_symlink", base / "dlink"),
            ("a_file_symlink", base / "flink"), ("a_dangling_symlink", base / "dangling"), ("a_missing_path", base / "absent"),
            ("below_a_symlink_directory_is_not_itself_linked", base / "dlink" / "f.txt"))}
        out["actual"] = {name: ws.att(lambda p=path: A.actual(p, "f")) for name, path in (
            ("a_real_file", base / "d" / "f.txt"), ("a_symlink_is_resolved", base / "flink"),
            ("a_directory_symlink", base / "dlink"), ("missing", base / "absent"), ("dangling", base / "dangling"))}
        looped = base / "loop"
        symlink(base / "loop-b", looped)
        symlink(looped, base / "loop-b")
        out["actual"]["looping"] = ws.att(lambda: A.actual(looped, "f"))
        out["actual"]["a_nul_byte"] = ws.att(lambda: A.actual(Path("/tmp/x\x00y"), "f"))
        out["actual_root"] = {name: ws.att(lambda v=value: A.actual_root(str(v), "copy_manifest.entries[0].source")) for name, value in (
            ("a_real_directory", base / "d"), ("a_symlink_root", base / "dlink"), ("a_missing_root", base / "absent"),
            ("a_file_root", base / "d" / "f.txt"), ("a_symlink_to_a_file", base / "flink"), ("dangling", base / "dangling"))}
        out["own_chain"] = {
            "all_real_components": ws.att(lambda: A.own_chain(str(base), ("d", "f.txt"), "f", leaf_absent=False)),
            "a_linked_intermediate_component": ws.att(lambda: A.own_chain(str(base), ("dlink", "f.txt"), "f", leaf_absent=False)),
            "a_linked_leaf": ws.att(lambda: A.own_chain(str(base), ("flink",), "f", leaf_absent=False)),
            "a_dangling_leaf_is_a_link": ws.att(lambda: A.own_chain(str(base), ("dangling",), "f", leaf_absent=True)),
            "an_absent_leaf_where_allowed": ws.att(lambda: A.own_chain(str(base), ("d", "absent.txt"), "f", leaf_absent=True)),
            "an_absent_leaf_where_not_allowed": ws.att(lambda: A.own_chain(str(base), ("d", "absent.txt"), "f", leaf_absent=False)),
            "an_absent_intermediate_where_leaf_absence_is_allowed": ws.att(lambda: A.own_chain(str(base), ("gone", "x.txt"), "f", leaf_absent=True)),
            "no_parts": ws.att(lambda: A.own_chain(str(base), (), "f", leaf_absent=False))}
        out["declared_parts"] = {name: ws.att(lambda v=value, r=root: A.declared_parts(str(v), str(r), "copy_manifest.entries[0].source")) for name, (value, root) in {
            "below": (base / "d" / "f.txt", base), "the_root_itself": (base, base), "not_below": (ws.root / "x", base),
            "case_distinct_is_not_below": (Path(str(base).rsplit("/", 1)[0]) / (base.name.upper() + "X") / "f", base),
            "a_sibling_with_the_root_as_prefix": (Path(str(base) + "-2") / "f", base),
            "nested": (base / "a" / "b" / "c", base)}.items()}
        move = {"lane": "a", "repository": {"from": "/src/repo", "to": "/dst/repo"}, "runtime": {"from": "/src/rt", "to": "/dst/rt"}}
        out["move_roots"] = {
            "both_movables": A.move_roots({"moves": [move]}),
            "runtime_only": A.move_roots({"moves": [{**move, "repository": None}]}),
            "repository_only": A.move_roots({"moves": [{**move, "runtime": None}]}),
            "neither": A.move_roots({"moves": [{**move, "repository": None, "runtime": None}]}),
            "two_lanes_in_order": A.move_roots({"moves": [move, {**move, "lane": "b", "repository": None}]}),
            "no_moves": A.move_roots({"moves": []}),
            "a_missing_key_raises": _direct(lambda: A.move_roots({"moves": [{"lane": "a"}]}))}
        roots = A.move_roots({"moves": [move, {**move, "lane": "b", "repository": {"from": "/src/repo/sub", "to": "/dst/repo/sub"}, "runtime": None}]})
        out["bind_entry"] = {name: ws.att(lambda e=entry: A.bind_entry(e, roots, "copy_manifest.entries[0]")) for name, entry in {
            "runtime_file": {"source": "/src/rt/a.json", "destination": "/dst/rt/a.json"},
            "repository_file": {"source": "/src/repo/docs/a.md", "destination": "/dst/repo/docs/a.md"},
            "first_matching_root_wins": {"source": "/src/repo/sub/a.md", "destination": "/dst/repo/sub/a.md"},
            "relative_path_differs": {"source": "/src/rt/a.json", "destination": "/dst/rt/b.json"},
            "case_folded_names_bind": {"source": "/SRC/RT/A.json", "destination": "/DST/rt/a.JSON"},
            "destination_outside_every_target": {"source": "/src/rt/a.json", "destination": "/elsewhere/a.json"},
            "destination_is_the_root_itself": {"source": "/src/rt/a.json", "destination": "/dst/rt"},
            "source_outside_its_root_but_the_relative_form_matches": {"source": "/other/rt/a.json", "destination": "/dst/rt/a.json"}}.items()}
        out["bind_entry_no_roots"] = ws.att(lambda: A.bind_entry({"source": "/a", "destination": "/b"}, [], "copy_manifest.entries[3]"))
    return out


# ---- group relocation -----------------------------------------------------------------------------------------------

class Relocation:
    """M7's `setup`: two lanes with source checkouts, the prepared copies (a clone, a target runtime, a copy manifest) and a
    service journal; hand-built request/config/jobs documents."""

    def __init__(self, ws, *, queued=("op-1",), shared_repository=False):
        self.ws, self.facts = ws, {}
        old, new = ws.root / "old", ws.root / "new"
        self.source, self.other = old / "repo-a", old / "repo-b"
        self.base = make_repo(ws, self.source)
        if not shared_repository:
            make_repo(ws, self.other)
        self.runtime, self.runtime_b = old / "rt-a", old / "rt-b"
        lane_b_repository = self.source if shared_repository else self.other
        self.config = {"lanes": [
            {"id": "a", "team": "alpha", "repository": str(self.source), "schema": "lane_a", "redis_namespace": "fleet-a", "runtime": str(self.runtime)},
            {"id": "b", "team": "beta", "repository": str(lane_b_repository), "schema": "lane_b", "redis_namespace": "fleet-b", "runtime": str(self.runtime_b)}]}
        for runtime in (self.runtime, self.runtime_b):
            Path(runtime).joinpath(*A.RUN_ROOT).mkdir(parents=True)
        self.jobs = [job(op, "a", "queued", goal_of(self.base)) for op in queued]
        self.target = clone(ws, self.source, new / "repo-a")
        self.target_runtime = new / "rt-a"
        self.target_runtime.mkdir(parents=True)
        self.copy = Copy(ws)
        self.entry = self.copy.entry("artifacts/evidence.json", b"copied evidence 0\n")
        self.declared = self.copy.manifest([self.entry], name="copy-manifest.json")
        self.journal = ws.root / "fleet-journal.log"
        write(self.journal, FINISHED)

    def move(self, **overrides) -> dict:
        move = {"lane": "a", "repository": {"from": str(self.source), "to": str(self.target)},
                "runtime": {"from": str(self.runtime), "to": str(self.target_runtime)}}
        move.update(overrides)
        return move

    def request(self, moves=None, declared=None) -> dict:
        return {"schema": "urn:zeus:fleet-relocation:1", "fleet": "fleet-1", "operator": "owner",
                "moves": moves if moves is not None else [self.move()], "copy_manifest": declared or self.declared}

    def collect(self, request=None, *, docker=None, journal="default", clock="fixed", jobs=None):
        docker = docker if docker is not None else Docker(EXITED)
        kwargs = {"journal": self.journal if journal == "default" else journal, "state": docker}
        if clock == "fixed":
            kwargs["clock"] = lambda: NOW
        result = self.ws.att(lambda: A.collect_relocation_proof(request or self.request(), self.config,
                                                                 self.jobs if jobs is None else jobs, **kwargs))
        return {"result": result, "docker_ids": docker.calls, **self.facts}


def relocation_case(out, name, build=None, **options):
    with case_ws() as ws:
        world = Relocation(ws, **options)
        request = None
        kwargs = {}
        if build:
            built = build(world)
            if isinstance(built, tuple):
                request, kwargs = built
            else:
                request = built
        out[name] = world.collect(request, **kwargs)


def group_relocation() -> dict:
    out: dict = {}
    relocation_case(out, "observation_repository_and_runtime")
    relocation_case(out, "observation_default_clock", lambda w: (None, {"clock": None}))
    relocation_case(out, "observation_two_queued_jobs_sorted", queued=("op-2", "op-1"))
    relocation_case(out, "observation_no_queued_jobs", queued=())
    relocation_case(out, "observation_other_lane_and_unqueued_jobs_are_ignored", lambda w: (
        None, {"jobs": w.jobs + [job("op-b", "b", "queued", goal_of(w.base)), job("op-r", "a", "running", goal_of("9" * 40)),
                                 job("op-d", "a", "accepted", goal_of("9" * 40))]}))
    relocation_case(out, "observation_runtime_only_reads_the_lane_repository", lambda w: w.request([w.move(repository=None)]))
    relocation_case(out, "observation_repository_only", lambda w: _repo_only_request(w))
    relocation_case(out, "observation_neither_moves_reads_the_lane_repository",
                    lambda w: w.request([{"lane": "a", "repository": None, "runtime": None}], declared=_no_entries(w)))
    relocation_case(out, "observation_two_lanes", lambda w: _two_lanes(w))
    relocation_case(out, "observation_retained_runs_all_stopped", lambda w: after(lambda: run_record(w.runtime, "/w1")))
    relocation_case(out, "observation_target_runtime_with_existing_runs", lambda w: after(lambda: (
        run_record(w.target_runtime, "/t1", run_id="a" * 32), run_record(w.target_runtime, "/t2", run_id="b" * 32),
        write(w.target_runtime.joinpath(*A.RUN_ROOT, "c" * 32, "run.json"), b"{ not json"))))
    relocation_case(out, "observation_target_runtime_with_an_initialized_empty_run_root",
                    lambda w: after(lambda: w.target_runtime.joinpath(*A.RUN_ROOT).mkdir(parents=True)))
    relocation_case(out, "observation_target_runtime_read_only", lambda w: _readonly_target(w))
    relocation_case(out, "observation_stranger_repository_as_the_target", lambda w: _stranger_target(w))
    relocation_case(out, "observation_shared_clone_is_not_independent", lambda w: _shared_target(w))
    relocation_case(out, "observation_target_clone_lacks_the_queued_base", lambda w: _later_base(w))
    relocation_case(out, "observation_goal_bytes_differ_in_the_target", lambda w: (None, {"jobs": [job("op-1", "a", "queued", {**goal_of(w.base), "sha256": "0" * 64})]}))
    # runner: the owner's idle claim is never read as a fact
    relocation_case(out, "refuses_runner_open_run", lambda w: (None, {"journal": write(w.ws.root / "open.log", OPEN)}))
    relocation_case(out, "refuses_runner_journal_without_the_finished_run_line", lambda w: (None, {"journal": write(w.ws.root / "started.log", journal_lines(start("1" * 32)))}))
    relocation_case(out, "refuses_runner_journal_missing", lambda w: (None, {"journal": w.ws.root / "absent.log"}))
    relocation_case(out, "refuses_runner_journal_none", lambda w: (None, {"journal": None}))
    relocation_case(out, "refuses_runner_journal_empty", lambda w: (None, {"journal": write(w.ws.root / "empty.log", b"")}))
    relocation_case(out, "refuses_runner_journal_binary", lambda w: (None, {"journal": write(w.ws.root / "binary.log", b"\xff\xfe\x00")}))
    relocation_case(out, "order_runner_before_anything_else", lambda w: (w.request([w.move(lane="zz")]), {"journal": w.ws.root / "absent.log"}))
    # lanes and retained runs
    relocation_case(out, "refuses_lane_unknown", lambda w: w.request([w.move(lane="zz")]))
    relocation_case(out, "refuses_lane_run_active", lambda w: after(lambda: run_record(w.runtime, "/w1"), docker=Docker(RUNNING)))
    relocation_case(out, "refuses_lane_run_unknown_docker_unavailable", lambda w: after(lambda: run_record(w.runtime, "/w1"), docker=Docker(None)))
    relocation_case(out, "refuses_lane_run_unreadable_record", lambda w: after(lambda: write(w.runtime.joinpath(*A.RUN_ROOT, "ab" * 16, "run.json"), b"{ not json")))
    relocation_case(out, "refuses_lane_runs_unavailable", lambda w: after(lambda: shutil.rmtree(w.runtime.joinpath(*A.RUN_ROOT))))
    relocation_case(out, "refuses_lane_runs_unreadable_a_run_without_a_record", lambda w: after(lambda: w.runtime.joinpath(*A.RUN_ROOT, "ab" * 16).mkdir()))
    relocation_case(out, "refuses_lane_runtime_unavailable", lambda w: after(lambda: shutil.rmtree(w.runtime)))
    relocation_case(out, "order_lane_before_the_repository", _lane_before_repository)
    # targets
    relocation_case(out, "refuses_target_repository_absent",
                    lambda w: w.request([w.move(repository={"from": str(w.source), "to": str(w.ws.root / "new" / "absent")})]))
    relocation_case(out, "refuses_target_repository_a_symlink", lambda w: _symlinked_target(w))
    relocation_case(out, "refuses_target_repository_a_file", lambda w: w.request([w.move(repository={"from": str(w.source), "to": str(write(w.ws.root / "new" / "file", b"x"))})]))
    relocation_case(out, "refuses_target_repository_not_a_repository", lambda w: _plain_target(w))
    relocation_case(out, "refuses_source_repository_not_a_repository", lambda w: _plain_source(w))
    relocation_case(out, "refuses_target_runtime_absent", lambda w: w.request([w.move(runtime={"from": str(w.runtime), "to": str(w.ws.root / "new" / "absent-rt")})]))
    relocation_case(out, "refuses_target_runtime_a_symlink", lambda w: w.request([w.move(runtime={"from": str(w.runtime), "to": str(symlink(w.target_runtime, w.ws.root / "new" / "rt-link"))})]))
    # the copy manifest is verified last
    relocation_case(out, "refuses_copy_manifest_link_through_the_collector", lambda w: _link_manifest(w))
    relocation_case(out, "refuses_copy_manifest_corrupt_through_the_collector", lambda w: _corrupt_manifest(w))
    relocation_case(out, "order_lane_refusal_before_the_manifest", lambda w: (w.request([w.move(lane="zz")], declared={"path": str(w.ws.root / "absent.json"), "sha256": "a" * 64, "entries": 1}), {})[0:2])
    relocation_case(out, "order_manifest_after_the_lane_observations", lambda w: (w.request(declared={"path": str(w.ws.root / "absent.json"), "sha256": "a" * 64, "entries": 1}), {"docker": Docker(EXITED)})[0:2])
    relocation_case(out, "default_state_reads_docker_only_for_retained_runs_none_here")
    # docker through a labelled fake executable, as M7's `docker=` argument
    with case_ws() as ws:
        world = Relocation(ws)
        run_record(world.runtime, "/w1")
        path = fake_docker(ws, "relocate", stdout="exited 0")
        docker = Docker(lambda cid: A.docker_state(cid, docker=str(path)))
        out["fake_docker_executable_answers_a_retained_run"] = {**world.collect(docker=docker), "argv": ws.n(docker_argv(ws, "relocate"))}
    with case_ws() as ws:
        world = Relocation(ws)
        run_record(world.runtime, "/w1")
        path = fake_docker(ws, "running", stdout="running 0")
        docker = Docker(lambda cid: A.docker_state(cid, docker=str(path)))
        out["fake_docker_executable_reports_a_running_run"] = {**world.collect(docker=docker), "argv": ws.n(docker_argv(ws, "running"))}
    out["constants"] = {"proof_schema": A.RELOCATION_PROOF_SCHEMA}
    return out


def _no_entries(w):
    return w.copy.manifest([], name="no-entries.json")


def _repo_only_request(w):
    entry = w.copy.entry("docs/GOAL.md", b"goal", source_root=w.source, target_root=w.target, write_source=False, write_destination=False)
    data = (w.source / "docs" / "GOAL.md").read_bytes()
    row = {**entry, "sha256": sha(data), "bytes": len(data)}
    return w.request([w.move(runtime=None)], declared=w.copy.manifest([row], name="repo-only.json"))


def _two_lanes(w):
    second = w.ws.root / "new" / "rt-b"
    second.mkdir()
    entry = w.copy.entry("b.json", source_root=w.runtime_b, target_root=second)
    declared = w.copy.manifest([w.entry, entry], name="two-lanes.json")
    moves = [w.move(), {"lane": "b", "repository": None, "runtime": {"from": str(w.runtime_b), "to": str(second)}}]
    return w.request(moves, declared=declared)


def _readonly_target(w):
    os.chmod(w.target_runtime, 0o500)
    w.facts["not_root"] = not_root()
    return None, {}


def _stranger_target(w):
    stranger = w.ws.root / "new" / "stranger"
    make_repo(w.ws, stranger, goal=b"another history\n")
    return w.request([w.move(repository={"from": str(w.source), "to": str(stranger)})])


def _shared_target(w):
    shared = clone(w.ws, w.source, w.ws.root / "new" / "borrowed", "--shared")
    return w.request([w.move(repository={"from": str(w.source), "to": str(shared)})])


def _later_base(w):
    git(w.ws, w.source, "checkout", "-q", "-b", "later")
    write(w.source / "docs" / "GOAL.md", b"changed goal\n")
    git(w.ws, w.source, "add", ".")
    git(w.ws, w.source, "commit", "-q", "-m", "Later base")
    later = git(w.ws, w.source, "rev-parse", "HEAD")
    jobs = w.jobs + [job("op-3", "a", "queued", goal_of(later, b"changed goal\n"))]
    return None, {"jobs": jobs}


def _lane_before_repository(w):
    run_record(w.runtime, "/w1")
    absent = w.ws.root / "new" / "absent"
    return w.request([w.move(repository={"from": str(w.source), "to": str(absent)})]), {"docker": Docker(RUNNING)}


def _symlinked_target(w):
    link = symlink(w.target, w.ws.root / "new" / "linked-repo")
    return w.request([w.move(repository={"from": str(w.source), "to": str(link)})])


def _plain_target(w):
    plain = w.ws.root / "new" / "plain"
    plain.mkdir()
    return w.request([w.move(repository={"from": str(w.source), "to": str(plain)})])


def _plain_source(w):
    plain = w.ws.root / "old" / "plain"
    plain.mkdir()
    return w.request([w.move(repository={"from": str(plain), "to": str(w.target)})])


def _link_manifest(w):
    data = b"interrupted evidence\n"
    write(w.runtime / "artifacts2" / "interrupted.json", data)
    target = w.ws.root / "new" / "rt-junction"
    target.mkdir()
    symlink(w.runtime / "artifacts2", target / "artifacts2")
    entry = w.copy.entry("artifacts2/interrupted.json", data, target_root=target, write_source=False, write_destination=False)
    declared = w.copy.manifest([entry], name="junction.json")
    return w.request([w.move(repository=None, runtime={"from": str(w.runtime), "to": str(target)})], declared=declared)


def _corrupt_manifest(w):
    entry = w.copy.entry("artifacts/broken.json", b"data", write_destination=False)
    write(entry["destination"], b"datatampered")
    return w.request(declared=w.copy.manifest([entry], name="corrupt.json"))


# ---- group host_migration -------------------------------------------------------------------------------------------

LANES = ("harness", "interface")
SCHEMAS = {"harness": "zeus_aibox_harness", "interface": "zeus_aibox_interface"}


class Verify:
    """A `verify_schema=` double: records `(dsn, schema)`; `outcome` is returned, or raised when an exception."""

    def __init__(self, outcome=None):
        self.outcome, self.calls = outcome, []

    def __call__(self, dsn, schema):
        self.calls.append([dsn, schema])
        outcome = self.outcome(schema) if callable(self.outcome) else self.outcome
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class Host:
    """M7's `cli_state` without the store: a target host tree (one repository, per-lane runtimes, a stopped journal)."""

    def __init__(self, ws, *, queued=True):
        self.ws, self.facts = ws, {}
        root = ws.root / "srv"
        self.repo = root / "repo"
        self.head = make_repo(ws, self.repo)
        self.runtimes = {lane: root / "runtime" / lane for lane in LANES}
        for path in self.runtimes.values():
            path.joinpath(*A.RUN_ROOT).mkdir(parents=True)
        self.journal = root / "journal.jsonl"
        write(self.journal, journal_lines({"event": "start", "run_id": "r1"}, {"event": "exit", "run_id": "r1"}))
        self.jobs = [job("op-q", "harness", "queued", goal_of(self.head))] if queued else []

    def request(self, **overrides) -> dict:
        lanes = [{"lane": lane, "repository": {"from": "/old/repo", "to": str(self.repo)},
                  "runtime": {"from": "/old/" + lane, "to": str(self.runtimes[lane])},
                  "schema": {"from": "zeus_fleet_" + lane, "to": SCHEMAS[lane]}} for lane in LANES]
        return {"schema": "urn:zeus:fleet-host-migration:1", "fleet": "zeus-local-fleet", "operator": "owner",
                "lanes": lanes, **overrides}

    def collect(self, request=None, *, docker=None, verify="default", journal="default", host_dsn="host=db.invalid dbname=zeus",
                clock="fixed", jobs=None):
        docker = docker if docker is not None else Docker(EXITED)
        verifier = Verify() if verify == "default" else verify
        kwargs = {"journal": self.journal if journal == "default" else journal, "host_dsn": host_dsn, "state": docker,
                  "verify_schema": verifier}
        if clock == "fixed":
            kwargs["clock"] = lambda: NOW
        result = self.ws.att(lambda: A.collect_host_migration_proof(request or self.request(), self.jobs if jobs is None else jobs, **kwargs))
        return {"result": result, "docker_ids": docker.calls, "verified": getattr(verifier, "calls", None), **self.facts}


def host_case(out, name, build=None, **options):
    with case_ws() as ws:
        host = Host(ws, **{k: v for k, v in options.items() if k == "queued"})
        request, kwargs = None, {k: v for k, v in options.items() if k != "queued"}
        if build:
            built = build(host)
            if isinstance(built, tuple):
                request, extra = built
                kwargs.update(extra)
            else:
                request = built
        out[name] = host.collect(request, **kwargs)


def group_host_migration() -> dict:
    out: dict = {}
    out["schema_provisioned"] = group_schema_provisioned()
    host_case(out, "observation_both_lanes")
    host_case(out, "observation_default_clock", clock=None)
    host_case(out, "observation_no_queued_jobs", queued=False)
    host_case(out, "observation_no_lanes", lambda h: {**h.request(), "lanes": []})
    host_case(out, "observation_one_lane", lambda h: {**h.request(), "lanes": h.request()["lanes"][:1]})
    host_case(out, "observation_other_lane_and_unqueued_jobs_are_ignored", lambda h: (None, {"jobs": h.jobs + [
        job("op-i", "interface", "queued", goal_of("9" * 40)), job("op-r", "harness", "running", goal_of("9" * 40))]}))
    host_case(out, "observation_retained_run_running_is_counted_not_refused",
              lambda h: after(lambda: run_record(h.runtimes["interface"], "/w1"), docker=Docker(RUNNING)))
    host_case(out, "observation_retained_run_stopped", lambda h: after(lambda: run_record(h.runtimes["interface"], "/w1")))
    host_case(out, "observation_runtime_read_only", _host_read_only)
    host_case(out, "observation_repository_shared_clone_not_independent", lambda h: _host_shared(h))
    host_case(out, "observation_repository_stranger_identity_differs", lambda h: _host_stranger(h))
    host_case(out, "observation_queued_base_missing_in_the_target", lambda h: (None, {"jobs": [job("op-q", "harness", "queued", goal_of("9" * 40))]}))
    host_case(out, "observation_schema_not_provisioned", lambda h: (None, {"verify": Verify(lambda schema: A.FleetRefused("lane_schema_unprovisioned") if schema.endswith("interface") else None)}))
    host_case(out, "observation_schema_verify_launch_refused_is_unprovisioned", lambda h: (None, {"verify": Verify(A.LaunchRefused("lane_unavailable"))}))
    host_case(out, "observation_schema_verify_other_error_propagates", lambda h: (None, {"verify": Verify(OSError("boom"))}))
    host_case(out, "observation_empty_host_dsn_is_not_provisioned", lambda h: (None, {"host_dsn": ""}))
    host_case(out, "refuses_runner_open", lambda h: (None, {"journal": write(h.ws.root / "open.log", OPEN)}))
    host_case(out, "refuses_runner_journal_missing", lambda h: (None, {"journal": h.ws.root / "absent.log"}))
    host_case(out, "refuses_runner_journal_none", lambda h: (None, {"journal": None}))
    host_case(out, "order_runner_before_the_target_paths", lambda h: ({**h.request(), "lanes": [{**h.request()["lanes"][0], "repository": {"from": "/old", "to": str(h.ws.root / "absent")}}]}, {"journal": h.ws.root / "absent.log"}))
    host_case(out, "refuses_repository_target_absent", lambda h: {**h.request(), "lanes": [{**h.request()["lanes"][0], "repository": {"from": "/old/repo", "to": str(h.ws.root / "absent")}}]})
    host_case(out, "refuses_repository_target_a_symlink", lambda h: {**h.request(), "lanes": [{**h.request()["lanes"][0], "repository": {"from": "/old/repo", "to": str(symlink(h.repo, h.ws.root / "srv" / "repo-link"))}}]})
    host_case(out, "refuses_runtime_target_absent", lambda h: {**h.request(), "lanes": [{**h.request()["lanes"][0], "runtime": {"from": "/old/x", "to": str(h.ws.root / "absent-rt")}}]})
    host_case(out, "refuses_runtime_target_a_symlink", lambda h: {**h.request(), "lanes": [{**h.request()["lanes"][0], "runtime": {"from": "/old/x", "to": str(symlink(h.runtimes["harness"], h.ws.root / "srv" / "rt-link"))}}]})
    host_case(out, "order_repository_before_runtime", lambda h: {**h.request(), "lanes": [{**h.request()["lanes"][0], "repository": {"from": "/o", "to": str(h.ws.root / "absent")}, "runtime": {"from": "/o", "to": str(h.ws.root / "absent-rt")}}]})
    host_case(out, "refuses_lane_run_unknown", lambda h: after(lambda: run_record(h.runtimes["interface"], "/w1"), docker=Docker(None)))
    host_case(out, "refuses_lane_runs_unavailable", lambda h: after(lambda: shutil.rmtree(h.runtimes["interface"].joinpath(*A.RUN_ROOT))))
    host_case(out, "refuses_lane_runs_unreadable", lambda h: after(lambda: h.runtimes["harness"].joinpath(*A.RUN_ROOT, "ab" * 16).mkdir()))
    host_case(out, "refuses_not_a_repository_target", lambda h: _host_plain(h))
    host_case(out, "verify_is_called_once_per_lane_in_request_order")
    out["constants"] = {"proof_schema": A.HOST_MIGRATION_PROOF_SCHEMA}
    return out


def group_schema_provisioned() -> dict:
    out: dict = {}
    dsn = "host=db.invalid dbname=zeus"

    def provisioned(name, host_dsn, verify):
        with case_ws() as ws:
            calls = []

            def recording(target_dsn, schema):
                calls.append([target_dsn, schema])
                if isinstance(verify, BaseException):
                    raise verify
                return verify
            out[name] = {"result": ws.att(lambda: A.schema_provisioned(host_dsn, "zeus_aibox_harness", recording)), "verify_calls": calls}

    provisioned("verify_returns_none_is_provisioned", dsn, None)
    provisioned("verify_returns_a_value_is_still_provisioned", dsn, False)
    provisioned("fleet_refusal_is_not_provisioned", dsn, A.FleetRefused("lane_schema_unprovisioned"))
    provisioned("launch_refusal_is_not_provisioned", dsn, A.LaunchRefused("lane_unavailable"))
    provisioned("other_exceptions_propagate", dsn, OSError("boom"))
    provisioned("a_url_dsn", "postgresql://zeus@db.invalid/zeus", None)
    provisioned("an_empty_dsn_refuses_before_verify", "", None)
    provisioned("a_blank_dsn_refuses_before_verify", "   ", None)
    provisioned("a_none_dsn_refuses_before_verify", None, None)
    with case_ws() as ws:
        out["default_verify_with_an_empty_dsn_needs_no_database"] = {"result": ws.att(lambda: A.schema_provisioned("", "zeus_aibox_harness"))}
        out["default_verify_with_a_none_dsn_needs_no_database"] = {"result": ws.att(lambda: A.schema_provisioned(None, "zeus_aibox_harness"))}
    return out


def _host_read_only(h):
    os.chmod(h.runtimes["interface"], 0o500)
    h.facts["not_root"] = not_root()
    return None, {}


def _host_shared(h):
    shared = clone(h.ws, h.repo, h.ws.root / "srv" / "borrowed", "--shared")
    lanes = h.request()["lanes"]
    lanes[0] = {**lanes[0], "repository": {"from": "/old/repo", "to": str(shared)}}
    return {**h.request(), "lanes": lanes}


def _host_stranger(h):
    stranger = h.ws.root / "srv" / "stranger"
    make_repo(h.ws, stranger, goal=b"another history\n")
    lanes = h.request()["lanes"]
    lanes[0] = {**lanes[0], "repository": {"from": "/old/repo", "to": str(stranger)}}
    return {**h.request(), "lanes": lanes}


def _host_plain(h):
    plain = h.ws.root / "srv" / "plain"
    plain.mkdir()
    lanes = h.request()["lanes"]
    lanes[0] = {**lanes[0], "repository": {"from": "/old/repo", "to": str(plain)}}
    return {**h.request(), "lanes": lanes}


GROUPS = (("recovery", group_recovery), ("slots", group_slots), ("runner", group_runner), ("checkouts", group_checkouts),
          ("copy_manifest", group_copy_manifest), ("relocation", group_relocation), ("host_migration", group_host_migration))


NOT_CASES = {"constants", "fixture", "journal_window", "run_root_joins_under_the_runtime"}
SUBGROUPS = {"lane_reader", "docker_state", "listed_runs", "active_runs", "writable", "resolved_directory", "queued_bindings",
             "independent", "checkout_identity", "checkout_identity_source_double", "schema_provisioned"}
TABLES = {"direct", "hashing"}  # each entry is a table of small checks, counted one per row


def count(group: dict) -> int:
    """Labelled cases of one group: a nested sub-group counts its own cases, a table counts its rows."""
    total = 0
    for name, value in group.items():
        if name in NOT_CASES:
            continue
        if name in SUBGROUPS:
            total += len(value)
        elif name in TABLES:
            total += sum(len(table) for table in value.values() if isinstance(table, dict))
        else:
            total += 1
    return total


def run(api) -> dict:
    global A
    A = api
    result, counts = {}, {}
    for name, group in GROUPS:
        result[name] = group()
        counts[name] = count(result[name])
    result["cases_per_group"] = counts
    result["carried"] = CARRIED
    return result
