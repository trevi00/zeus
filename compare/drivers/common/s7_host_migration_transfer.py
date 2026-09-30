"""Shared S7 scenario steps (`delivery.host_migration_transfer`): M7 `adapters/host_migration.py` WITHOUT the
PostgreSQL/Redis transfer (INV-HOST-MIGRATION-001; DESIGN-s7 §2 row `delivery.host_migration_transfer`; TRACE-s7 §5.6),
recorded BEFORE the move.

Layer: harness (never shipped). Never imports `codex_harness`.

Eight case groups, each case labelled in the result (`{group: {case: {...}}}`), plus `carried`:
- `files`: the launcher files (`_document_bytes`, `_atomic_write`, `write_activation`, `write_fence`), `current_revision`,
  `classify_activation_files`, `release_ready`, and the launcher accepting exactly the coordinator-written receipt.
- `switch`: `switch_effect` (a1 receipt then `current` with both directories fsynced; a2 the crash window; a3 cached; a4
  foreign bytes; a5 fence/unready; a6 own temporary link; a7 stale reader), the PH4-11 files, the non-POSIX refusal, the
  CLI `activation-switch` in process, and the launcher as a real `--dry-run` process.
- `recovery`: `recovery_preconditions` (every violation), `runner_processes` over a LABELLED proc root, `_runner_argv`.
- `interleave`: the switch/switch and record/switch interleavings over the tests' own thread/event choreography.
- `systemd`: `SystemdHostTarget` through a LABELLED systemctl double.
- `layout`: `prepare_layout`.
- `canonical`: `canonical_tool`, `canonical_module`, `run_canonical` and the wrapper exit rule.
- `compare`: `pg_compare_schema` (real canonical tool), `pg_coverage_receipt`, `rename_plan`, `compare_catalogs`,
  `catalog_digest`.

**Fixtures (all LABELLED).** The world is pilot 28's `s7_host_migrations` (IMPORTED: `HM.paused`, `HM.successor`,
`HM.walk`, `HM.manifest`, `HM.SwitchEffect` and the constants; `HM.A` is set to this run's api). `release`, `host`,
`idle_systemctl`, `systemctl`, `fake_process`, `tree`, `Paused`, `run_thread`, `canonical_inventory`, `catalog`,
`source_catalog` are copies of M7's test helpers (tests/test_host_migration.py, tests/test_host_migration_successor.py).
- Every case runs in its own temporary root; a sealed release (read-only tree) is made writable again before removal.
- `releases/<rev>` are LABELLED stub releases (a stub interpreter, a package marker, `runtime.json`), not built releases.
- `/proc` is a LABELLED fixture proc root (the tests' `proc=` argument): the real `/proc` of other processes is never read.
- `systemctl` is a LABELLED double answering `show` and recording every argv; nothing starts, stops or queries systemd.
- Launcher cases import the unchanged deploy/aibox launcher (`api.launcher`, loaded from the SOURCE tree); the fixture
  machine id is a file under the temporary root. The one process case (`launcher_process`) reads the host's
  `/etc/machine-id` itself, so it records exit codes and events only, never a value derived from that file.
- The canonical tool is a COPY of SOURCE `scripts/aibox_data` under `<root>/checkout/scripts`, made visible to the adapter by
  `api.checkout(path)` (the package then appears to live at `<path>/src/codex_harness`). The installed wheel has no
  `scripts/aibox_data` beside it, so the adapter's own resolution is recorded through that labelled layout only.
- Interleavings start real threads, hold one inside the coordinator transaction with an Event, and record outcomes and files
  only: `blocked` is whether the second call was still waiting after a bounded join, never a duration.

**fsync observation.** `api.trace()` is a context manager the reference driver implements as M7's test does
(`spied`): it wraps `write_activation`, `_replace_current` and `_fsync_directory` of the adapter AND `os.fsync`, appends to
one ordered `events` list (`receipt`, `current`, `fsync:<directory name>`, `os.fsync:file`, `os.fsync:dir`), and restores every
name afterwards. M7's own spy list is the `events` without the `os.fsync:` entries.

`api` supplies (names of the adapter module `adapters.host_migration` unless said otherwise): `write_activation`,
`write_fence`, `current_revision`, `classify_activation_files`, `release_ready`, `recovery_preconditions`,
`runner_processes`, `runner_argv` (`_runner_argv`), `switch_effect`, `SystemdHostTarget`, `prepare_layout`,
`pg_compare_schema`, `pg_coverage_receipt`, `run_canonical`, `canonical_tool`, `canonical_module`, `catalog_digest`,
`document_bytes` (`_document_bytes`), `atomic_write` (`_atomic_write`), `main`, the constants `ACTIVATION_FILE`,
`FENCE_FILE`, `RECORDED_NOT_SWITCHED`, `RECEIPT_WRITTEN`, `SWITCHED`, `INCONSISTENT`, `POSIX_ONLY`, `SWITCH_UNITS`, `LAYOUT`;
`MigrationRefused`; pilot 28's `MemoryStore`, `HostMigrations`, `BUCKET`, `BUCKET_TRANSITIONS`, `BUCKET_CHECKPOINTS`, `policy`,
`DESCRIPTOR_SCHEMA`, `descriptor_digest`, `digest`; `validate_targets` and `KIND_SYSTEMD` (domain.host_delivery);
`launcher` (the launcher module) and `launcher_path`; `SOURCE_ROOT`; and the hooks `trace()`, `os_replace(factory)`
(`adapter.os.replace` becomes `factory(real)` for the block), `patched(**attrs)` (adapter attributes replaced for the block)
and `checkout(path)`.

**Normalization is explicit, done here and identical on both sides** (pilot 33's `Fixture.n`/`Fixture.attempt`, IMPORTED):
`sys.executable` → `<python>`, this case's temporary root → `<root>`, ISO times → `<time>`, `pid` keys → `<pid>`; the
`result_sha256` of a receipt whose digested stdout names the temporary root is replaced by whether it equals the digest of
that stdout (two `wrapper_exit_rule` cases). The
adapter's own random temporary names (`.current.<16 hex>`, `.host-activation.json.<8>`) are recorded as `<random>`. The
fixture revisions stay literal. Durations and waits are never recorded, and nothing else is masked.

M7 tests mirrored: test_writer_start_receipt_gap_is_reconciled_by_r1_never_r0,
test_the_linux_launcher_accepts_exactly_the_coordinator_written_receipt, test_fence_refuses_every_launcher_role_including_monitors,
test_a_wrapper_never_promotes_exit_zero_beside_a_failing_typed_result, test_per_schema_comparison_with_registry_delta_only_on_public,
test_systemd_target_controls_only_the_registered_zeus_aibox_unit, test_rename_plan_is_total_and_allows_public_only_as_the_control_ledger,
test_catalog_comparison_maps_names_but_keeps_extension_references, test_prepare_layout_is_dry_run_by_default_and_idempotent,
test_canonical_tool_is_resolved_from_this_checkout, test_canonical_tool_runs_under_this_interpreter_with_its_checkout_path;
and, of test_host_migration_successor.py: t3, ph4_11_recording_limited_active_writes_no_current, a1..a7 (a4 x5 and a5 x6
damages), every_recovery_precondition (x12), an_idle_host_passes_and_an_unreadable_process_table_is_a_violation,
switch_switch_interleaving, record_switch_interleaving, a_successor_recorded_before_the_first_switch,
portable_a_second_switch_then_a_record, switch_refuses_on_non_posix (store, files and the in-process CLI),
cli_records_a_successor_and_switches_only_with_an_expected_head, the_launcher_process_refuses_the_mixed_pair.
Characterized directly (no M7 test): `_document_bytes`, `_atomic_write`, `write_activation`/`write_fence` edges,
`current_revision`, `classify_activation_files`, `release_ready`, `_runner_argv`, `runner_processes`, the unit allow-list,
`running` states and `_launch` refusals of `SystemdHostTarget`, `catalog_digest`.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from types import SimpleNamespace

import s7_host_migrations as HM
import s7_host_targets as T

A = None  # the api of this run
MID, COMMIT, NEXT, LATER, H = HM.MID, HM.COMMIT, HM.NEXT, HM.LATER, HM.H
ROOT_ENV = {"PATH": "/usr/bin:/bin"}
OWN_TEMP = re.compile(r"^(\.current\.[0-9a-f]{16}|\.(?:host-activation|host-fence)\.json\.[a-z0-9_]{8})$")

CARRIED = {
    "test_postgres_record_waits_for_a_switch_holding_the_coordinator_lock":
        "PostgreSQL (HARNESS_INTEGRATION, isolated_pgstore): the owner-recorded delivery.restore(.pg) family; docker is denied here",
    "test_postgres_a_waiter_past_the_10s_lock_timeout_is_refused_and_writes_nothing":
        "PostgreSQL: the owner-recorded delivery.restore(.pg) family",
    "test_postgres_two_successors_of_one_head_race_to_exactly_one_record":
        "PostgreSQL: the owner-recorded delivery.restore(.pg) family",
    "test_whole_database_dump_runs_in_the_container_without_a_dsn_and_refuses_an_empty_archive":
        "PG dump over a docker double: owner family delivery.restore(.pg)",
    "test_source_pg_export_is_one_read_only_snapshot_scoped_to_the_schema_with_lf_bytes":
        "PG export over a psycopg connection double: owner family delivery.restore(.pg)",
    "test_source_pg_catalog_reads_one_snapshot_with_pg_catalog_search_path":
        "PG catalog over a psycopg connection double: owner family delivery.restore(.pg)",
    "test_source_dump_argv_keeps_the_container_path_and_parses_crlf_output_identically":
        "PG dump argv over a docker double: owner family delivery.restore(.pg)",
    "tests/test_host_migration_pg_rehearsal.py": "PG dump/restore rehearsal against a disposable PostgreSQL: owner family delivery.restore(.pg)",
    "test_redis_copy_is_verified_by_the_canonical_comparison":
        "needs two disposable Redis servers (ZEUS_MIGRATION_TEST_REDIS_SOURCE/TARGET): owner family",
    "test_unreadable_nested_directory_is_a_failed_inventory_not_an_empty_one":
        "CLI artifact-inventory through main(argv) over the real tool and a chmod-0 directory: S10 CLI",
    "test_stage_refuses_preexisting_destination_ancestor_symlink_and_writes_nothing_outside":
        "CLI artifact-stage through main(argv): S10 CLI",
    "test_verify_mismatch_exits_nonzero_and_match_exits_zero": "CLI artifact-inventory/stage/verify through main(argv): S10 CLI",
    "test_pg_compare_cli_mismatch_exits_nonzero":
        "CLI pg-compare-schema through main(argv): S10 CLI (the per-schema comparison itself is the `compare` group)",
    "test_cli_validate_reports_digest_and_never_echoes_a_secret": "CLI validate through main(argv) and the parser: S10 CLI",
    "test_controller_wires_the_configured_control_dir_into_the_systemd_start":
        "host_delivery.controller wiring reads the host settings SSOT and a HostDelivery world: delivery.host_targets/canaries owner",
    "test_controller_without_a_valid_control_dir_refuses_the_systemd_start_by_name[x3]":
        "host_delivery.controller wiring (settings(), ZEUS_AIBOX_ROOT environment): delivery.host_targets/canaries owner",
    "test_a_closed_runtime_control_only_drains_and_its_reopening_admits_the_requalification":
        "drives the real FleetRunner over a Fleet world, not the host migration adapter: the S5/S6 fleet/continuation families",
    "test_s6_the_control_less_bootstrap_on_a_db_paused_fleet_moves_state_but_starts_nothing":
        "drives FleetRunner and Continuation (test_continuation world), not the host migration adapter: the S5/S6 families",
    "test_rollback_without_any_intent_is_r0_with_its_own_gate":
        "store only, no file: covered by delivery.host_migrations (rollback_without_intent)",
}


# ---- the per-case workspace and normalization ----------------------------------------------------------------------

class Ws:
    """One case's temporary root, and the imported pilot-33 normalizer bound to it."""

    def __init__(self):
        self.root = Path(tempfile.mkdtemp(prefix="s7hmt-")).resolve()
        norm = object.__new__(T.Fixture)
        norm.digests = {}
        norm.substitutions = sorted([(str(self.root), "<root>"), (T.PY, "<python>")], key=lambda pair: -len(pair[0]))
        self.norm = norm

    def n(self, value):
        return self.norm.n(value)

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


def att(ws, call):
    return ws.norm.attempt(call)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def link_of(path: Path):
    return os.readlink(path) if os.path.islink(path) else None


def entries(ws, directory: Path) -> dict:
    """The names, link targets, directory modes and file digests with normalized JSON contents of one directory."""
    out = {}
    for path in sorted(directory.iterdir(), key=lambda item: item.name):
        name = OWN_TEMP.sub(lambda m: m.group(0).rsplit(".", 1)[0] + ".<random>", path.name)
        if path.is_symlink():
            out[name] = {"link": ws.n(os.readlink(path))}
        elif path.is_dir():
            out[name] = {"dir": oct(stat.S_IMODE(path.stat().st_mode))}
        else:
            data = path.read_bytes()
            view = {"sha256": sha(data)}
            try:
                view["json"] = ws.n(json.loads(data))
            except ValueError:
                view["text"] = ws.n(data.decode("utf-8", "replace"))
            out[name] = view
    return out


# ---- fixtures (M7 tests/test_host_migration_successor.py module helpers, LABELLED) ---------------------------------

def release(root: Path, revision: str, *, seal: bool = True) -> Path:
    """LABELLED fixture release: stub interpreter, package marker, runtime.json; read-only."""
    path = root / "releases" / revision
    (path / ".venv" / "bin").mkdir(parents=True)
    (path / ".venv" / "bin" / "python").write_text("#!/bin/sh\nexit 0\n")
    (path / ".venv" / "bin" / "python").chmod(0o755)
    (path / "src" / "codex_harness").mkdir(parents=True)
    (path / "src" / "codex_harness" / "__init__.py").write_text("")
    (path / "runtime.json").write_text(json.dumps({"schema": "urn:zeus:runtime-attestation:1", "revision": revision}))
    if seal:
        release_seal(path)
    return path


def release_seal(path: Path) -> None:
    for directory, names, files in os.walk(path, topdown=False):
        for name in files:
            Path(directory, name).chmod(0o555 if name == "python" else 0o444)
        Path(directory).chmod(0o555)


def release_unseal(path: Path, python: int = 0o755) -> None:
    for directory, names, files in os.walk(path):
        os.chmod(directory, 0o755)
        for name in files:
            os.chmod(os.path.join(directory, name), python if name == "python" else 0o644)


def host(ws, coordinator, *, owner: bool = True) -> SimpleNamespace:
    """The fixture host after the paused activation: receipt of the intent, current -> COMMIT, the managed owner record
    present, the managed state dir holding only a canary request."""
    root = ws.root
    control = root / "runtime" / "control"
    control.mkdir(parents=True)
    managed = root / "runtime" / "managed-fleet"
    managed.mkdir(parents=True)
    (managed / "owner-canary-request.json").write_text("{}")
    for revision in (COMMIT, NEXT, LATER):
        release(root, revision)
    os.symlink(COMMIT, root / "releases" / "current")
    A.write_activation(control, coordinator.activation_document(MID))
    if owner:
        (control / "fleet-owner.json").write_text(json.dumps({"schema": "urn:zeus:aibox-fleet-owner:1",
                                                              "owner": "managed-fleet",
                                                              "unit": "zeus-aibox-managed-fleet.service"}))
    (root / "machine-id").write_text("fixture-machine\n")
    return SimpleNamespace(root=root, control=control, releases=root / "releases", managed=managed, proc=root / "proc",
                           calls=[])


def idle_systemctl(argv, timeout=None):
    """Fixture `systemctl show`: every unit inactive with MainPID 0."""
    return SimpleNamespace(returncode=0, stdout="ActiveState=inactive\nMainPID=0\n", stderr="")


def systemctl(states: dict):
    def run(argv, timeout=None):
        answer = states.get(argv[2], ("inactive", "0"))
        if answer is None:
            return SimpleNamespace(returncode=1, stdout="", stderr="")
        return SimpleNamespace(returncode=0, stdout="ActiveState=%s\nMainPID=%s\n" % answer, stderr="")
    return run


def idle(h, runner=idle_systemctl):
    """The precondition observer of the tests, recording every systemctl argv it runs into `h.calls`."""
    h.proc.mkdir(exist_ok=True)

    def recording(argv, timeout=None):
        h.calls.append(list(argv))
        return runner(argv, timeout)
    return lambda control, managed: A.recovery_preconditions(control, managed, runner=recording, proc=h.proc)


def switch(coordinator, h, *, expected=None, check=False, preconditions=None):
    effect = A.switch_effect(h.control, h.releases, h.managed, check=check, preconditions=preconditions or idle(h))
    return coordinator.activation_switch(MID, effect, expected_id=expected)


def fixture_host_id() -> str:
    return "machine-id-sha256:" + hashlib.sha256(b"fixture-machine").hexdigest()


def launcher_world(ws, *, owner: bool = True):
    """The coordinator in restored_paused with an intent bound to the fixture machine id, and the fixture host."""
    coordinator = HM.coordinator()
    manifest_sha = coordinator.plan(HM.manifest())["manifest_sha256"]
    HM.walk(coordinator, manifest_sha, A.policy.RESTORED_PAUSED)
    intent = {**HM.intent_document(), "host_id": fixture_host_id()}
    intent_id = coordinator.intend_activation(intent)["intent_id"]
    return coordinator, manifest_sha, intent, intent_id, host(ws, coordinator, owner=owner)


def launch_outcome(service, h, role="fleet"):
    """What the unchanged launcher decides for `role`: the plan's identity or the refusal reason."""
    try:
        plan = service.launch_plan(role, {"ZEUS_AIBOX_ROOT": str(h.root), **ROOT_ENV},
                                   machine_id_path=h.root / "machine-id")
    except service.Refused as refusal:
        return {"refused": refusal.reason}
    return {"plan": {"revision": plan["revision"], "argv_tail": plan["argv"][1:], "migration_id": plan["migration_id"]}}


def tree(ws, h) -> dict:
    """Every name, link target and file digest under the control and releases directories."""
    state = {}
    for label, base in (("control", h.control), ("releases", h.releases)):
        for path in sorted(base.iterdir()):
            key = label + "/" + path.name
            if path.is_symlink():
                state[key] = "->" + os.readlink(path)
            elif path.is_file():
                state[key] = sha(path.read_bytes())
            else:
                state[key] = "dir"
    return state


def view(ws, h) -> dict:
    """The recorded host: both directory listings, the `current` target and every systemctl argv observed."""
    return {"control": entries(ws, h.control), "releases": entries(ws, h.releases),
            "current": ws.n(link_of(h.releases / "current")), "systemctl_argv": h.calls}


def own_temp_links(h) -> list:
    return sorted(p.name for p in h.releases.iterdir() if p.name.startswith(".current."))


def anonymous(name: str) -> str:
    """A temporary name of the adapter (`.current.<16 hex>`, `.<name>.<8>`) without its random part."""
    return re.sub(r"^(\.(?:current|.+?))\.(?:[0-9a-f]{16}|[a-z0-9_]{8})$", r"\1.<random>", name)


def failing_replace(name: str, seen=None, error=OSError):
    """LABELLED injected failure of `os.replace` whose destination is named `name` (the test's own `fail`/`crash`)."""
    def factory(real):
        def replace(source, destination):
            if Path(destination).name == name:
                if seen is not None:
                    seen.append({"source_is_link": os.path.islink(source), "source": anonymous(Path(source).name)})
                raise error("LABELLED injected failure")
            return real(source, destination)
        return replace
    return factory


def current_plan(coordinator, expected=None) -> dict:
    """The plan `activation_switch` hands its effect (recorded through pilot 28's SwitchEffect)."""
    effect = HM.SwitchEffect()
    coordinator.activation_switch(MID, effect, expected_id=expected)
    return effect.plans[0]


def outcome(ws, box: dict) -> dict:
    if "error" in box:
        exc = box["error"]
        return {"raised": type(exc).__name__, **{k: getattr(exc, k) for k in ("reason_code", "field") if hasattr(exc, k)}}
    return {"returned": ws.n(box["result"])}


class Paused:
    """Wrap a switch effect so it stops inside the coordinator transaction until the test releases it (M7 `Paused`)."""

    def __init__(self, effect, timeout=10):
        self.effect, self.entered, self.release = effect, threading.Event(), threading.Event()
        self.timeout = timeout

    def __call__(self, plan):
        self.entered.set()
        assert self.release.wait(self.timeout)
        return self.effect(plan)


def run_thread(target) -> tuple[threading.Thread, dict]:
    box = {}

    def body():
        try:
            box["result"] = target()
        except BaseException as exc:  # noqa: BLE001 - reported to the test thread
            box["error"] = exc
    thread = threading.Thread(target=body, daemon=True)
    thread.start()
    return thread, box


def blocked(thread) -> bool:
    """Whether the thread was still waiting after a bounded join (an outcome, never a duration)."""
    thread.join(0.3)
    return thread.is_alive()


# ============================== files =============================================================================

def files_writer_gap(ws):
    """test_writer_start_receipt_gap_is_reconciled_by_r1_never_r0 (files and coordinator transitions)."""
    p = A.policy
    store = HM.new_store()
    first = HM.coordinator(store)
    manifest_sha = first.plan(HM.manifest())["manifest_sha256"]
    HM.walk(first, manifest_sha, p.RESTORED_PAUSED)
    out = {"mode_without_intent": first.rollback_plan(MID)["mode"]}
    control = ws.root / "runtime" / "control"
    control.mkdir(parents=True)
    out["document_without_intent"] = att(ws, lambda: first.activation_document(MID))
    out["invalid_receipt"] = att(ws, lambda: A.write_activation(control, {"schema": p.ACTIVATION_SCHEMA}))
    out["control_after_invalid"] = entries(ws, control)
    first.intend_activation(HM.intent_document())
    written = A.write_activation(control, first.activation_document(MID))
    accepted = json.loads((control / "host-activation.json").read_text("utf-8"))
    out["written"] = ws.n(written)
    out["accepted_equals_document"] = accepted == first.activation_document(MID)
    out["accepted_state_and_intent"] = [accepted["state"], accepted["intent_id"] == written["intent_id"]]
    out["sha_is_file_digest"] = written["sha256"] == sha((control / "host-activation.json").read_bytes())
    second = HM.coordinator(store)  # the crash: a new coordinator over the same store
    out["state_after_crash"] = second.status(MID)["state"]
    plan = second.rollback_plan(MID)
    out["rollback_after_crash"] = {"mode": plan["mode"],
                                   "forbids_source_restart": "restart_source_from_original_snapshot" in plan["forbidden"]}
    out["forward_checkpoint"] = att(ws, lambda: second.checkpoint(HM.checkpoint("artifact_copy")))
    out["failure"] = att(ws, lambda: brief(second.advance(HM.failure(manifest_sha, p.RESTORED_PAUSED, p.ROLLBACK_REQUIRED,
                                                                     "writer-start-unknown"))))
    out["document_while_rolling_back"] = att(ws, lambda: second.activation_document(MID))
    fenced = A.write_fence(control, MID, "rollback-r1")
    out["fence"] = ws.n(fenced)
    out["write_behind_fence"] = att(ws, lambda: A.write_activation(control, {**accepted}))
    r0 = HM.transition(manifest_sha, p.ROLLBACK_REQUIRED, p.ROLLED_BACK, evidence={"rollback_gate": HM.receipt("gate-r0")})
    out["r0_gate"] = att(ws, lambda: second.advance(r0))
    r1 = HM.transition(manifest_sha, p.ROLLBACK_REQUIRED, p.ROLLED_BACK, evidence={"rollback_gate": HM.receipt("gate-r1")})
    out["r1_without_steps"] = att(ws, lambda: second.advance(r1))
    for step in p.REVERSE_STEPS:
        second.checkpoint(HM.checkpoint(step))
    out["rolled_back"] = second.advance(r1)["state"]
    out["control"] = entries(ws, control)
    return out


def brief(view_: dict) -> dict:
    return {k: view_[k] for k in ("state", "transitions", "cached") if k in view_}


def files_launcher_accepts_receipt(ws):
    """test_the_linux_launcher_accepts_exactly_the_coordinator_written_receipt."""
    service = A.launcher
    coordinator = HM.coordinator()
    manifest_sha = coordinator.plan(HM.manifest())["manifest_sha256"]
    HM.walk(coordinator, manifest_sha, A.policy.RESTORED_PAUSED)
    coordinator.intend_activation(HM.intent_document())
    control = ws.root / "runtime" / "control"
    control.mkdir(parents=True)
    written = A.write_activation(control, coordinator.activation_document(MID))

    def check(revision):
        try:
            accepted = service.check_activation(control, ws.root / "releases" / revision, HM.HOST_ID)
        except service.Refused as refusal:
            return {"refused": refusal.reason}
        return {"accepted": {"state": accepted["state"], "intent_id_matches": accepted["intent_id"] == written["intent_id"]}}
    return {"same_revision": check(COMMIT), "other_revision": check("9" * 40)}


def files_fence_refuses_every_role(ws):
    """test_fence_refuses_every_launcher_role_including_monitors."""
    service = A.launcher
    control = ws.root / "runtime" / "control"
    control.mkdir(parents=True)
    fence = A.write_fence(control, MID, "rollback-r0")
    out = {"fence": ws.n(fence), "control": entries(ws, control), "roles": {}}
    for role in ("fleet", "monitor-collect", "monitor-web"):
        try:
            service.launch_plan(role, {"ZEUS_AIBOX_ROOT": str(ws.root), **ROOT_ENV})
            out["roles"][role] = "launched"
        except service.Refused as refusal:
            out["roles"][role] = refusal.reason
    return out


def files_t3_successor_receipt(ws):
    """t3: the successor receipt adds two fields and the unchanged launcher accepts it."""
    service = A.launcher
    coordinator, _, intent, intent_id, h = launcher_world(ws, owner=False)
    original = coordinator.activation_document(MID)
    out = {"launch_on_the_intent": launch_outcome(service, h)}
    recorded = coordinator.record_successor(HM.successor(intent_id, host_id=intent["host_id"]))
    document = coordinator.activation_document(MID)
    out["added_fields"] = sorted(set(document) - set(original))
    out["removed_fields"] = sorted(set(original) - set(document))
    keep = [k for k in original if k not in ("intent_id", "release_revision")]
    out["other_fields_unchanged"] = all(document[k] == original[k] for k in keep)
    out["supersedes_and_kind"] = [document["supersedes"] == intent_id, document["activation_kind"]]
    switched = switch(coordinator, h, expected=recorded["successor_id"], preconditions=lambda c, m: [])
    out["switch_revision"] = switched["revision"]
    out["launch_on_the_successor"] = launch_outcome(service, h)
    out["view"] = view(ws, h)
    return out


def files_document_bytes(ws):
    """`_document_bytes`: sorted keys, indent 1, one trailing newline, UTF-8."""
    document = {"b": [1, {"d": None, "c": "é"}], "a": True}
    data = A.document_bytes(document)
    return {"bytes": data.decode("utf-8"), "sha256": sha(data), "ends_with_newline": data.endswith(b"\n"),
            "empty": A.document_bytes({}).decode("utf-8")}


def files_atomic_write(ws):
    """`_atomic_write`: temporary file, fsync, rename, directory fsync; a failure removes only its own temporary file."""
    directory = ws.root / "dir"
    directory.mkdir()
    document = {"k": 1}
    out = {}
    with A.trace() as events:
        out["digest_is_bytes_digest"] = A.atomic_write(directory, "x.json", document) == sha(A.document_bytes(document))
    out["events"] = list(events)
    out["entries"] = entries(ws, directory)
    first_inode = os.stat(directory / "x.json").st_ino
    A.atomic_write(directory, "x.json", {"k": 2})
    out["rewrite"] = {"inode_changed": os.stat(directory / "x.json").st_ino != first_inode,
                      "entries": entries(ws, directory)}
    seen = []
    with A.os_replace(failing_replace("x.json", seen)):
        out["failed_replace"] = att(ws, lambda: A.atomic_write(directory, "x.json", {"k": 3}))
    out["after_failed_replace"] = {"seen": seen, "entries": entries(ws, directory)}
    with A.os_replace(failing_replace("x.json", error=KeyboardInterrupt)):
        try:
            A.atomic_write(directory, "x.json", {"k": 4})
            out["interrupted"] = "returned"
        except KeyboardInterrupt:
            out["interrupted"] = "KeyboardInterrupt"
    out["after_interrupt"] = entries(ws, directory)
    (ws.root / "file").write_text("x")
    (ws.root / "real").mkdir()
    (ws.root / "linked").symlink_to(ws.root / "real")
    out["unavailable"] = {name: att(ws, lambda name=name: A.atomic_write(ws.root / name, "x.json", {}))
                          for name in ("absent", "file", "linked")}
    out["nothing_written_through_the_link"] = entries(ws, ws.root / "real")
    return out


def files_write_activation_edges(ws):
    """`write_activation`: validation order, the fence, and a valid-looking document without `state`."""
    p = A.policy
    control = ws.root / "control"
    control.mkdir()
    out = {"invalid": {}}
    for label, document in (("not_a_dict", ["x"]), ("wrong_schema", {"schema": "urn:other", "intent_id": "i"}),
                            ("no_intent_id", {"schema": p.ACTIVATION_SCHEMA}),
                            ("empty_intent_id", {"schema": p.ACTIVATION_SCHEMA, "intent_id": ""})):
        out["invalid"][label] = att(ws, lambda document=document: A.write_activation(control, document))
    out["control_after_invalid"] = entries(ws, control)
    good = {"schema": p.ACTIVATION_SCHEMA, "intent_id": "i-1", "state": "restored_paused"}
    out["written"] = att(ws, lambda: A.write_activation(control, good))
    out["control_after_write"] = entries(ws, control)
    A.write_fence(control, MID, "fixture")
    out["behind_a_fence"] = att(ws, lambda: A.write_activation(control, {**good, "intent_id": "i-2"}))
    out["activation_after_fence_refusal"] = entries(ws, control)["host-activation.json"]["json"]["intent_id"]
    bare = ws.root / "bare"
    bare.mkdir()
    out["without_state_key"] = att(ws, lambda: A.write_activation(bare, {"schema": p.ACTIVATION_SCHEMA, "intent_id": "i-3"}))
    out["without_state_key_file"] = entries(ws, bare)  # the file is written before `state` is read
    return out


def files_write_fence_edges(ws):
    """`write_fence`: the fence document, its bytes, an existing fence, and an unavailable directory."""
    control = ws.root / "control"
    control.mkdir()
    out = {"first": ws.n(A.write_fence(control, MID, "rollback-r0")), "entries": entries(ws, control)}
    out["again"] = ws.n(A.write_fence(control, MID, "rollback-r1"))
    out["entries_again"] = entries(ws, control)
    out["absent_directory"] = att(ws, lambda: A.write_fence(ws.root / "absent", MID, "x"))
    return out


def files_current_revision(ws):
    """`current_revision`: absent / foreign / a 40-hex name directly inside the releases directory."""
    out = {}
    hexname = COMMIT
    cases = {
        "absent": lambda rel: None,
        "regular_file": lambda rel: (rel / "current").write_text("x"),
        "directory": lambda rel: (rel / "current").mkdir(),
        "relative_revision": lambda rel: os.symlink(hexname, rel / "current"),
        "dot_relative_revision": lambda rel: os.symlink("./" + hexname, rel / "current"),
        "dangling_revision": lambda rel: os.symlink(LATER, rel / "current"),
        "short_name": lambda rel: os.symlink("abc", rel / "current"),
        "uppercase_name": lambda rel: os.symlink(hexname.upper(), rel / "current"),
        "nested_relative": lambda rel: os.symlink("sub/" + hexname, rel / "current"),
        "parent_relative": lambda rel: os.symlink("../releases/" + hexname, rel / "current"),
        "absolute_inside": lambda rel: os.symlink(str(rel / hexname), rel / "current"),
        "absolute_elsewhere": lambda rel: os.symlink(str(ws.root / "elsewhere" / hexname), rel / "current"),
        "absolute_nested": lambda rel: os.symlink(str(rel / "sub" / hexname), rel / "current"),
    }
    for index, (label, make) in enumerate(cases.items()):
        rel = ws.root / ("rel%02d" % index)
        rel.mkdir()
        make(rel)
        out[label] = att(ws, lambda rel=rel: A.current_revision(rel))
    out["string_path"] = att(ws, lambda: A.current_revision(str(ws.root / "rel03")))
    return out


def files_classify(ws):
    """`classify_activation_files`: the four classes over every (receipt, current) pair, and an unreadable receipt."""
    coordinator, _, intent_id = HM.paused()
    head = coordinator.record_successor(HM.successor(intent_id))["successor_id"]
    plan = current_plan(coordinator, head)
    intent_plan = current_plan(HM.paused()[0])  # a coordinator whose head is still the intent
    out = {"plan": {"effective_revision": plan["effective"]["release_revision"],
                    "predecessor_revision": plan["predecessor"]["release_revision"],
                    "kind": plan["kind"], "intent_plan_kind": intent_plan["kind"],
                    "intent_plan_predecessor": intent_plan["predecessor"]}}
    wanted = A.document_bytes(plan["effective"])
    prior = A.document_bytes(plan["predecessor"])
    receipts = {"effective": wanted, "predecessor": prior, "foreign": b'{"x": 1}\n', "absent": None}
    currents = {"effective": NEXT, "predecessor": COMMIT, "foreign": LATER, "absent": None}
    matrix = {}
    for index, (rlabel, data) in enumerate(receipts.items()):
        for clabel, revision in currents.items():
            control, rel = ws.root / ("c%02d" % len(matrix)), ws.root / ("r%02d" % len(matrix))
            control.mkdir()
            rel.mkdir()
            if data is not None:
                (control / "host-activation.json").write_bytes(data)
            if revision is not None:
                os.symlink(revision, rel / "current")
            matrix[rlabel + "/" + clabel] = ws.n(A.classify_activation_files(control, rel, plan))
    out["matrix"] = matrix
    control, rel = ws.root / "cu", ws.root / "ru"
    (control / "host-activation.json").mkdir(parents=True)
    rel.mkdir()
    os.symlink(COMMIT, rel / "current")
    out["unreadable_receipt"] = ws.n(A.classify_activation_files(control, rel, plan))
    first = {}
    for rlabel in ("effective", "predecessor", "absent"):
        control, rel = ws.root / ("ic-" + rlabel), ws.root / ("ir-" + rlabel)
        control.mkdir()
        rel.mkdir()
        data = {"effective": A.document_bytes(intent_plan["effective"]), "predecessor": prior, "absent": None}[rlabel]
        if data is not None:
            (control / "host-activation.json").write_bytes(data)
        os.symlink(COMMIT, rel / "current")
        first[rlabel] = ws.n(A.classify_activation_files(control, rel, intent_plan))
    out["without_predecessor"] = first
    return out


def files_release_ready(ws):
    """`release_ready`: every named refusal of the release `current` will name."""
    rels = ws.root / "releases"
    out = {}
    serial = [0]

    def fresh(char):
        serial[0] += 1
        return char * 39 + format(serial[0], "x")

    def case(label, prepare, revision=None):
        rev = revision or fresh("1")
        path = release(ws.root, rev) if revision is None else None
        if prepare is not None:
            prepare(rev, path)
        out[label] = att(ws, lambda: A.release_ready(rels, rev))

    def open_up(rev, path):
        release_unseal(path)

    def venv_missing(rev, path):
        release_unseal(path)
        (path / ".venv" / "bin" / "python").unlink()
        release_seal(path)

    def python_not_executable(rev, path):
        (path / ".venv" / "bin" / "python").chmod(0o444)

    def package_missing(rev, path):
        release_unseal(path)
        (path / "src" / "codex_harness" / "__init__.py").unlink()
        release_seal(path)

    def runtime(document):
        def prepare(rev, path):
            release_unseal(path)
            if document is None:
                (path / "runtime.json").unlink()
            else:
                (path / "runtime.json").write_text(document if isinstance(document, str) else json.dumps(document))
            release_seal(path)
        return prepare

    def writable_file(rev, path):
        release_unseal(path)
        os.chmod(path / "runtime.json", 0o644)
        for name in (".", "src", "src/codex_harness"):
            os.chmod(path / name, 0o555)
        os.chmod(path / "src" / "codex_harness" / "__init__.py", 0o444)

    def writable_dir(rev, path):
        release_seal(path)
        os.chmod(path / "src", 0o755)

    def writable_root(rev, path):
        os.chmod(path, 0o755)

    def writable_venv(rev, path):
        os.chmod(path / ".venv" / "bin" / "python", 0o755)
        os.chmod(path / ".venv" / "bin", 0o755)

    def writable_link(rev, path):
        release_unseal(path)
        os.symlink("runtime.json", path / "alias")
        release_seal(path)

    case("ready", None)
    case("writable_file", writable_file)
    case("writable_directory", writable_dir)
    case("writable_release_root", writable_root)
    case("writable_inside_venv_is_allowed", writable_venv)
    case("a_symlink_entry_is_never_writable", writable_link)
    case("venv_python_missing", venv_missing)
    case("venv_python_not_executable", python_not_executable)
    case("package_marker_missing", package_missing)
    case("runtime_json_missing", runtime(None))
    case("runtime_json_not_json", runtime("not json"))
    case("runtime_json_not_an_object", runtime(["x"]))
    case("runtime_json_other_revision", runtime({"revision": LATER}))
    case("runtime_json_without_revision", runtime({"schema": "x"}))
    out["revision_not_hex"] = att(ws, lambda: A.release_ready(rels, "abc"))
    out["revision_uppercase"] = att(ws, lambda: A.release_ready(rels, COMMIT.upper()))
    out["directory_missing"] = att(ws, lambda: A.release_ready(rels, "2" * 40))
    target = release(ws.root, "3" * 40)
    os.symlink(target, rels / ("4" * 40))
    out["release_is_a_symlink"] = att(ws, lambda: A.release_ready(rels, "4" * 40))
    (rels / ("5" * 40)).write_text("x")
    out["release_is_a_file"] = att(ws, lambda: A.release_ready(rels, "5" * 40))
    return out


# ============================== switch ============================================================================

def switch_a1(ws):
    """a1: the receipt, then `current`, both directories fsynced in this order."""
    coordinator, _, intent_id = HM.paused()
    h = host(ws, coordinator)
    head = coordinator.record_successor(HM.successor(intent_id))["successor_id"]
    out = {"check": att(ws, lambda: switch(coordinator, h, check=True))}
    with A.trace() as events:
        out["switch"] = att(ws, lambda: switch(coordinator, h, expected=head))
    out["events"] = list(events)
    out["m7_calls"] = [e for e in events if not e.startswith("os.fsync")]
    written = (h.control / "host-activation.json").read_bytes()
    out["receipt_is_the_document_bytes"] = written == A.document_bytes(coordinator.activation_document(MID))
    out["receipt_supersedes_the_intent"] = json.loads(written)["supersedes"] == intent_id
    out["no_temporary_link"] = own_temp_links(h) == []
    out["view"] = view(ws, h)
    return out


def switch_a2(ws):
    """a2: a crash after the receipt is `receipt_written`, refused by the launcher, and completed once."""
    service = A.launcher
    coordinator, _, intent, intent_id, h = launcher_world(ws)
    head = coordinator.record_successor(HM.successor(intent_id, host_id=intent["host_id"]))["successor_id"]
    out = {}
    with A.os_replace(failing_replace("current")):
        out["crash"] = att(ws, lambda: switch(coordinator, h, expected=head))
    out["own_temporary_removed"] = own_temp_links(h) == []
    out["check"] = att(ws, lambda: switch(coordinator, h, check=True))
    out["launcher_owner_actions"] = launch_outcome(service, h, "owner-actions")
    out["view_after_crash"] = view(ws, h)
    before = os.stat(h.control / "host-activation.json")
    with A.trace() as events:
        out["completion"] = att(ws, lambda: switch(coordinator, h, expected=head))
    out["events"] = list(events)
    out["m7_calls"] = [e for e in events if not e.startswith("os.fsync")]
    out["receipt_inode_unchanged"] = os.stat(h.control / "host-activation.json").st_ino == before.st_ino
    out["launcher_fleet_after"] = launch_outcome(service, h)
    out["view"] = view(ws, h)
    return out


def switch_a3(ws):
    """a3: a rerun when switched is cached and touches nothing."""
    coordinator, _, intent_id = HM.paused()
    h = host(ws, coordinator)
    head = coordinator.record_successor(HM.successor(intent_id))["successor_id"]
    switch(coordinator, h, expected=head)
    receipt_stat, link_stat = os.stat(h.control / "host-activation.json"), os.lstat(h.releases / "current")
    observed = []
    with A.trace() as events:
        result = att(ws, lambda: switch(coordinator, h, expected=head,
                                        preconditions=lambda c, m: observed.append("observed") or []))
    after_receipt, after_link = os.stat(h.control / "host-activation.json"), os.lstat(h.releases / "current")
    return {"result": result, "events": list(events), "preconditions_observed": observed,
            "receipt_untouched": (after_receipt.st_ino, after_receipt.st_mtime_ns) == (receipt_stat.st_ino,
                                                                                      receipt_stat.st_mtime_ns),
            "link_untouched": (after_link.st_ino, after_link.st_mtime_ns) == (link_stat.st_ino, link_stat.st_mtime_ns),
            "view": view(ws, h)}


def switch_a4(damage):
    def case(ws):
        """a4: foreign receipt bytes or a foreign `current` target are inconsistent and nothing is written."""
        coordinator, _, intent_id = HM.paused()
        h = host(ws, coordinator)
        head = coordinator.record_successor(HM.successor(intent_id))["successor_id"]
        link = h.releases / "current"
        if damage == "foreign_receipt":
            (h.control / "host-activation.json").write_text('{"schema": "hand-written"}\n')
        elif damage == "foreign_current":
            link.unlink()
            os.symlink(LATER, link)
        elif damage == "absolute_elsewhere":
            link.unlink()
            os.symlink(str(ws.root / "elsewhere" / NEXT), link)
        elif damage == "missing_current":
            link.unlink()
        else:
            (h.control / "host-activation.json").unlink()
        before = tree(ws, h)
        check = att(ws, lambda: switch(coordinator, h, check=True))
        refused = att(ws, lambda: switch(coordinator, h, expected=head))
        return {"check": check, "refused": refused, "tree_unchanged": tree(ws, h) == before, "view": view(ws, h)}
    return case


def switch_a5(damage):
    def case(ws):
        """a5: a fence or an unready release refuses and writes nothing."""
        coordinator, _, intent_id = HM.paused()
        h = host(ws, coordinator)
        head = coordinator.record_successor(HM.successor(intent_id))["successor_id"]
        target = h.releases / NEXT
        if damage == "fence":
            A.write_fence(h.control, MID, "fixture-fence")
        else:
            release_unseal(target, python=0o644)  # the test's own chmod: every file 0o644
            if damage == "missing":
                shutil.rmtree(target)
            elif damage == "runtime":
                (target / "runtime.json").write_text(json.dumps({"revision": LATER}))
            elif damage == "venv":
                (target / ".venv" / "bin" / "python").unlink()
            elif damage == "package":
                (target / "src" / "codex_harness" / "__init__.py").unlink()
            if damage not in ("missing", "writable"):
                release_seal(target)
        before = tree(ws, h)
        refused = att(ws, lambda: switch(coordinator, h, expected=head))
        return {"refused": refused, "tree_unchanged": tree(ws, h) == before, "view": view(ws, h)}
    return case


def switch_a6(ws):
    """a6: a failed replace removes only its own temporary link."""
    coordinator, _, intent_id = HM.paused()
    h = host(ws, coordinator)
    head = coordinator.record_successor(HM.successor(intent_id))["successor_id"]
    os.symlink("0" * 40, h.releases / ".current.foreignleftover")
    seen = []
    with A.os_replace(failing_replace("current", seen)):
        failed = att(ws, lambda: switch(coordinator, h, expected=head))
    return {"failed": failed,
            "temporary_was_a_link_named_current_dot": [[s["source_is_link"], s["source"].startswith(".current."),
                                                        s["source"] != ".current.foreignleftover"] for s in seen],
            "leftovers": own_temp_links(h), "foreign_leftover_target": os.readlink(h.releases / ".current.foreignleftover"),
            "view": view(ws, h)}


def switch_a7(ws):
    """a7: a stale reader rewriting the intent receipt is refused by the launcher, and the files read inconsistent."""
    service = A.launcher
    coordinator, _, intent, intent_id, h = launcher_world(ws)
    head = coordinator.record_successor(HM.successor(intent_id, host_id=intent["host_id"]))["successor_id"]
    switch(coordinator, h, expected=head)
    row = coordinator.store.data[(A.BUCKET, MID)]
    stale = A.policy.activation_receipt(row["activation_intent"], row["manifest_sha256"], row["state"])
    A.write_activation(h.control, stale)
    return {"launcher": {role: launch_outcome(service, h, role) for role in ("fleet", "owner-actions", "managed-fleet")},
            "check": att(ws, lambda: switch(coordinator, h, check=True)), "view": view(ws, h)}


def switch_ph4_11(ws):
    """PH4-11: recording limited_active writes no `current` and authorizes no new successor."""
    coordinator, manifest_sha, intent_id = HM.paused()
    h = host(ws, coordinator)
    head = coordinator.record_successor(HM.successor(intent_id))["successor_id"]
    switch(coordinator, h, expected=head)
    files = tree(ws, h)
    coordinator.advance(HM.managed_transition(manifest_sha, head, commit=NEXT))
    later = att(ws, lambda: coordinator.record_successor(HM.successor(head, LATER)))
    cached = coordinator.record_successor(HM.successor(intent_id))["cached"]
    return {"new_successor": later, "historic_replay_cached": cached, "files_unchanged": tree(ws, h) == files,
            "current": os.readlink(h.releases / "current"), "view": view(ws, h)}


def switch_non_posix(ws):
    """The counterpart of every posix row: refused before any effect, `check` included, and by the CLI before the store."""
    coordinator, _, intent_id = HM.paused()
    h = SimpleNamespace(control=ws.root / "control", releases=ws.root / "releases", managed=ws.root / "managed",
                        calls=[], root=ws.root)
    for directory in (h.control, h.releases, h.managed):
        directory.mkdir()
    A.write_activation(h.control, coordinator.activation_document(MID))  # the intent's receipt
    release(ws.root, NEXT, seal=False)
    head = coordinator.record_successor(HM.successor(intent_id))["successor_id"]

    def files():
        return sorted((str(p.relative_to(ws.root)), p.read_bytes() if p.is_file() else None)
                      for p in ws.root.rglob("*"))
    before, rows = files(), HM.store_state(coordinator.store)
    out = {"direct": {}}
    observed = []
    with A.patched(_posix=lambda: False), A.trace() as events:
        for label, check, expected in (("effect", False, head), ("check", True, None)):
            out["direct"][label] = att(ws, lambda check=check, expected=expected: switch(
                coordinator, h, expected=expected, check=check, preconditions=lambda c, m: observed.append(1) or []))
        paths = ["--migration-id", MID, "--control-dir", str(h.control), "--releases-dir", str(h.releases),
                 "--managed-state-dir", str(h.managed), "--dsn-env", "ZEUS_AIBOX_MIGRATION_DSN",
                 "--schema", "zeus_aibox_migration"]
        opened = []
        out["cli"] = {}
        with A.patched(_coordinator=lambda args: opened.append(1) or coordinator):
            for label, extra in (("expected_id", ["--expected-id", head]), ("check", ["--check"])):
                out["cli"][label] = cli(ws, ["activation-switch", *extra, *paths])
    out["events"] = list(events)
    out["preconditions_observed"] = observed
    out["coordinator_opened"] = opened
    out["files_unchanged"] = files() == before
    out["rows_unchanged"] = HM.store_state(coordinator.store) == rows
    out["no_temporary_link"] = not [name for name, _ in before if ".current." in name]
    return out


def cli(ws, argv) -> dict:
    """One in-process `main(argv)`: its exit code and the JSON it printed (normalized)."""
    captured = io.StringIO()
    with contextlib.redirect_stdout(captured):
        code = A.main(list(argv))
    text = captured.getvalue()
    try:
        return {"exit": code, "json": ws.n(json.loads(text))}
    except ValueError:
        return {"exit": code, "text": ws.n(text)}


def switch_cli(ws):
    """test_cli_records_a_successor_and_switches_only_with_an_expected_head (in process, labelled doubles)."""
    coordinator, _, intent_id = HM.paused()
    h = host(ws, coordinator)
    document = ws.root / "successor.json"
    document.write_text(json.dumps(HM.successor(intent_id)))
    store = ["--dsn-env", "ZEUS_AIBOX_MIGRATION_DSN", "--schema", "zeus_aibox_migration"]
    out = {}
    with A.patched(_coordinator=lambda args: coordinator, recovery_preconditions=lambda control, managed: []):
        out["record"] = cli(ws, ["activation-successor", "--file", str(document), *store])
        head = out["record"]["json"]["successor_id"]
        out["replay"] = cli(ws, ["activation-successor", "--file", str(document), *store])
        paths = ["--migration-id", MID, "--control-dir", str(h.control), "--releases-dir", str(h.releases),
                 "--managed-state-dir", str(h.managed), *store]
        out["switch_without_expected_id"] = cli(ws, ["activation-switch", *paths])
        out["check"] = cli(ws, ["activation-switch", "--check", *paths])
        out["switch"] = cli(ws, ["activation-switch", "--expected-id", head, *paths])
        (h.control / "host-activation.json").write_text("{}\n")
        out["check_inconsistent"] = cli(ws, ["activation-switch", "--check", *paths])
    out["view"] = view(ws, h)
    return out


def switch_launcher_process(ws):
    """the_launcher_process_refuses_the_mixed_pair_and_launches_the_switched_revision (a real `--dry-run` process)."""
    machine = Path("/etc/machine-id")
    if not machine.is_file():
        return {"unreachable": "the launcher process reads /etc/machine-id, which this host lacks"}
    local = "machine-id-sha256:" + hashlib.sha256(machine.read_text("ascii").strip().encode()).hexdigest()
    coordinator = HM.coordinator()
    manifest_sha = coordinator.plan(HM.manifest())["manifest_sha256"]
    HM.walk(coordinator, manifest_sha, A.policy.RESTORED_PAUSED)
    intent_id = coordinator.intend_activation({**HM.intent_document(), "host_id": local})["intent_id"]
    h = host(ws, coordinator)

    def dry_run(role):
        done = subprocess.run([sys.executable, str(A.launcher_path), "launch", "--role", role, "--dry-run"],
                              env={"ZEUS_AIBOX_ROOT": str(h.root), **ROOT_ENV}, capture_output=True, text=True, timeout=60)
        return {"exit": done.returncode, "event": ws.n(json.loads(done.stderr))}
    out = {"intent_fleet": dry_run("fleet"), "intent_owner_actions": dry_run("owner-actions")}
    head = coordinator.record_successor(HM.successor(intent_id, host_id=local))["successor_id"]
    with A.os_replace(failing_replace("current")):
        out["crash"] = att(ws, lambda: switch(coordinator, h, expected=head))
    out["mixed_pair"] = {role: dry_run(role) for role in ("fleet", "managed-fleet", "owner-actions")}
    switch(coordinator, h, expected=head)
    out["switched_fleet_owner_kept"] = dry_run("fleet")
    os.rename(h.control / "fleet-owner.json", h.control / "fleet-owner.retired-fixture.json")  # S4 shape
    out["switched_fleet_owner_retired"] = dry_run("fleet")
    out["switched_managed_fleet"] = dry_run("managed-fleet")
    return out


# ============================== recovery ==========================================================================

def fake_process(proc: Path, pid: int, argv: list) -> None:
    (proc / str(pid)).mkdir(parents=True)
    (proc / str(pid) / "cmdline").write_bytes(b"\0".join(word.encode() for word in argv) + b"\0")


PRECONDITIONS = [
    ("owner_missing", "owner_marker_missing"),
    ("owner_invalid", "owner_marker_invalid"),
    ("bootstrap_active", "unit_active:zeus-aibox-fleet.service"),
    ("managed_mainpid", "unit_active:zeus-aibox-managed-fleet.service"),
    ("controller_active", "unit_active:zeus-aibox-host-delivery.service"),
    ("controller_unknown", "unit_state_unknown:zeus-aibox-host-delivery.service"),
    ("launch_request", "managed_launch_present:managed-launch.json"),
    ("descriptor", "managed_launch_present:descriptor.json"),
    ("controller_state", "managed_launch_present:controller-state.json"),
    ("runner", "runner_process:4242"),
    ("supervise", "runner_process:4243"),
    ("launch_role", "runner_process:4244"),
]


def recovery_precondition(case_name, violation):
    def case(ws):
        """every recovery precondition is rechecked at the effect boundary (with observers that must NOT count)."""
        coordinator, _, intent_id = HM.paused()
        h = host(ws, coordinator)
        head = coordinator.record_successor(HM.successor(intent_id))["successor_id"]
        h.proc.mkdir()
        states = {}
        if case_name == "owner_missing":
            (h.control / "fleet-owner.json").unlink()
        elif case_name == "owner_invalid":
            (h.control / "fleet-owner.json").write_text("{}")
        elif case_name == "bootstrap_active":
            states["zeus-aibox-fleet.service"] = ("active", "77")
        elif case_name == "managed_mainpid":
            states["zeus-aibox-managed-fleet.service"] = ("inactive", "12")
        elif case_name == "controller_active":
            states["zeus-aibox-host-delivery.service"] = ("activating", "0")
        elif case_name == "controller_unknown":
            states["zeus-aibox-host-delivery.service"] = None
        elif case_name in ("launch_request", "descriptor", "controller_state"):
            name = {"launch_request": "managed-launch.json", "descriptor": "descriptor.json",
                    "controller_state": "controller-state.json"}[case_name]
            (h.managed / name).write_text("{}")
        elif case_name == "runner":
            fake_process(h.proc, 4242, ["/srv/zeus/releases/x/.venv/bin/python", "-m", "zeus", "fleet", "run"])
        elif case_name == "supervise":
            fake_process(h.proc, 4243, ["python", "-m", "codex_harness.adapters.managed_runtime", "supervise"])
        else:
            fake_process(h.proc, 4244, ["/usr/bin/python3", "/srv/zeus/deploy/aibox/zeus_aibox_service.py",
                                        "launch", "--role", "managed-fleet"])
        # Observers that must NOT count: a shell naming the words in one argv word, and a dry run.
        fake_process(h.proc, 5001, ["sh", "-c", "pgrep -f 'zeus fleet run|managed_runtime'"])
        fake_process(h.proc, 5002, ["/usr/bin/python3", "zeus_aibox_service.py", "launch", "--role", "fleet", "--dry-run"])
        before = tree(ws, h)
        checked = att(ws, lambda: switch(coordinator, h, check=True, preconditions=idle(h, systemctl(states))))
        refused = att(ws, lambda: switch(coordinator, h, expected=head, preconditions=idle(h, systemctl(states))))
        return {"expected_violation": violation, "check": checked, "refused": refused,
                "tree_unchanged": tree(ws, h) == before, "systemctl_argv": h.calls}
    return case


def recovery_idle_host(ws):
    """an_idle_host_passes_and_an_unreadable_process_table_is_a_violation."""
    coordinator, _, _ = HM.paused()
    h = host(ws, coordinator)
    h.proc.mkdir()
    seen = []

    def recording(argv, timeout=None):
        seen.append([list(argv), timeout])
        return idle_systemctl(argv, timeout)

    def broken(argv, timeout=None):
        raise OSError("LABELLED systemctl unavailable")
    return {"idle": att(ws, lambda: A.recovery_preconditions(h.control, h.managed, runner=recording, proc=h.proc)),
            "systemctl_argv_and_timeout": seen,
            "switch_units": list(A.SWITCH_UNITS),
            "no_proc_root": att(ws, lambda: A.recovery_preconditions(h.control, h.managed, runner=idle_systemctl,
                                                                     proc=ws.root / "noproc")),
            "systemctl_unavailable": att(ws, lambda: A.recovery_preconditions(h.control, h.managed, runner=broken,
                                                                              proc=h.proc))}


def recovery_unit_states(ws):
    """Direct: each way `systemctl show` can answer, and the order of several violations."""
    coordinator, _, _ = HM.paused()
    h = host(ws, coordinator)
    h.proc.mkdir()
    out = {}

    def one(label, runner):
        out[label] = att(ws, lambda: A.recovery_preconditions(h.control, h.managed, runner=runner, proc=h.proc))

    def answer(stdout, returncode=0):
        return lambda argv, timeout=None: SimpleNamespace(returncode=returncode, stdout=stdout, stderr="")
    one("inactive_pid0", answer("ActiveState=inactive\nMainPID=0\n"))
    one("failed_pid0", answer("ActiveState=failed\nMainPID=0\n"))
    one("failed_pid_nonzero", answer("ActiveState=failed\nMainPID=9\n"))
    one("active_pid0", answer("ActiveState=active\nMainPID=0\n"))
    one("reloading", answer("ActiveState=reloading\nMainPID=0\n"))
    one("pid_00_is_not_0", answer("ActiveState=inactive\nMainPID=00\n"))
    one("returncode_nonzero", answer("ActiveState=inactive\nMainPID=0\n", 3))
    one("no_active_state", answer("MainPID=0\n"))
    one("no_main_pid", answer("ActiveState=inactive\n"))
    one("empty_stdout", answer(""))
    one("none_stdout", answer(None))
    one("unknown_state_word", answer("ActiveState=weird\nMainPID=0\n"))
    (h.control / "fleet-owner.json").unlink()
    shutil.rmtree(h.managed)
    (h.proc).rmdir()
    one("everything_wrong_in_order", answer("ActiveState=active\nMainPID=1\n"))
    return out


def recovery_owner_marker(ws):
    """Direct: the owner marker's accepted and refused shapes."""
    control, managed, proc = ws.root / "control", ws.root / "managed", ws.root / "proc"
    for directory in (control, managed, proc):
        directory.mkdir()
    out = {}
    marker = control / "fleet-owner.json"
    for label, content in (("valid", {"schema": "urn:zeus:aibox-fleet-owner:1", "owner": "managed-fleet"}),
                           ("wrong_schema", {"schema": "x", "owner": "managed-fleet"}),
                           ("wrong_owner", {"schema": "urn:zeus:aibox-fleet-owner:1", "owner": "bootstrap"}),
                           ("list", ["x"]), ("not_json", "{")):
        marker.write_text(content if isinstance(content, str) else json.dumps(content))
        out[label] = att(ws, lambda: A.recovery_preconditions(control, managed, runner=idle_systemctl, proc=proc))
    marker.unlink()
    marker.mkdir()
    out["a_directory"] = att(ws, lambda: A.recovery_preconditions(control, managed, runner=idle_systemctl, proc=proc))
    return out


RUNNER_ARGVS = [
    ("fleet_run_of_zeus", ["python", "-m", "zeus", "fleet", "run"]),
    ("fleet_run_absolute_zeus", ["/srv/x/.venv/bin/zeus", "fleet", "run"]),
    ("fleet_run_of_harness", ["harness", "fleet", "run"]),
    ("fleet_run_absolute_harness", ["/usr/local/bin/harness", "fleet", "run"]),
    ("fleet_run_without_a_program_word_before", ["fleet", "run"]),
    ("fleet_run_of_another_program", ["python", "other", "fleet", "run"]),
    ("fleet_status", ["python", "-m", "zeus", "fleet", "status"]),
    ("shell_naming_the_words_in_one_word", ["sh", "-c", "zeus fleet run"]),
    ("managed_runtime_module", ["python", "-m", "codex_harness.adapters.managed_runtime", "supervise"]),
    ("managed_runtime_without_dash_m", ["python", "codex_harness.adapters.managed_runtime"]),
    ("managed_runtime_dash_m_last", ["python", "-m"]),
    ("service_launch_fleet_role", ["python", "/x/zeus_aibox_service.py", "launch", "--role", "fleet"]),
    ("service_launch_managed_fleet", ["python", "/x/zeus_aibox_service.py", "launch", "--role", "managed-fleet"]),
    ("service_launch_role_equals", ["python", "/x/zeus_aibox_service.py", "launch", "--role=fleet"]),
    ("service_launch_monitor_role", ["python", "/x/zeus_aibox_service.py", "launch", "--role", "monitor-web"]),
    ("service_launch_dry_run", ["python", "/x/zeus_aibox_service.py", "launch", "--role", "fleet", "--dry-run"]),
    ("service_render", ["python", "/x/zeus_aibox_service.py", "render", "--role", "fleet"]),
    ("service_launch_without_role", ["python", "/x/zeus_aibox_service.py", "launch"]),
    ("service_launch_mixed_roles", ["python", "/x/zeus_aibox_service.py", "launch", "--role", "monitor-web",
                                    "--role", "managed-fleet"]),
    ("empty", []),
    ("single_word", ["zeus"]),
]


def recovery_runner_argv(ws):
    """Direct: `_runner_argv` over exact argv words."""
    return {label: A.runner_argv(words) for label, words in RUNNER_ARGVS}


def recovery_runner_processes(ws):
    """Direct: the scan of a LABELLED proc root: digits only, own pid skipped, unreadable entries skipped, string order."""
    proc = ws.root / "proc"
    proc.mkdir()
    fake_process(proc, 9, ["/x/.venv/bin/python", "-m", "zeus", "fleet", "run"])
    fake_process(proc, 100, ["python", "-m", "codex_harness.adapters.managed_runtime", "supervise"])
    fake_process(proc, 4242, ["sh", "-c", "zeus fleet run"])
    fake_process(proc, os.getpid(), ["/x/.venv/bin/python", "-m", "zeus", "fleet", "run"])  # this process: skipped
    (proc / "77").mkdir()  # exited between listing and reading: no cmdline
    (proc / "88").mkdir()
    (proc / "88" / "cmdline").write_bytes(b"")  # an empty argv
    (proc / "self").mkdir()
    (proc / "self" / "cmdline").write_bytes(b"zeus\0fleet\0run\0")  # not a pid
    (proc / "meminfo").write_text("x")
    (proc / "55").mkdir()
    (proc / "55" / "cmdline").write_bytes(b"\xff\xfe\0zeus\0fleet\0run\0")  # undecodable word, then a runner argv
    out = {"found": att(ws, lambda: [pid for pid in A.runner_processes(proc) if pid != os.getpid()]),
           "own_pid_reported": os.getpid() in A.runner_processes(proc)}
    out["absent_root"] = att(ws, lambda: A.runner_processes(ws.root / "noproc"))
    out["root_is_a_file"] = att(ws, lambda: A.runner_processes(ws.root / "proc" / "meminfo"))
    return out


# ============================== interleave ========================================================================

def interleave_switch_switch(ws):
    """switch/switch: the second waits and finds the pair switched."""
    coordinator, _, intent_id = HM.paused()
    h = host(ws, coordinator)
    head = coordinator.record_successor(HM.successor(intent_id))["successor_id"]
    with A.trace() as events:
        first = Paused(A.switch_effect(h.control, h.releases, h.managed, preconditions=idle(h)))
        a, a_box = run_thread(lambda: coordinator.activation_switch(MID, first, expected_id=head))
        entered = first.entered.wait(10)
        b, b_box = run_thread(lambda: switch(coordinator, h, expected=head))
        second_blocked = blocked(b)
        seen_while_blocked = [e for e in events if not e.startswith("os.fsync")]
        first.release.set()
        a.join(10)
        b.join(10)
    calls = [e for e in events if not e.startswith("os.fsync")]
    return {"first_entered": entered, "second_blocked": second_blocked, "events_while_blocked": seen_while_blocked,
            "first": outcome(ws, a_box), "second": outcome(ws, b_box),
            "receipt_writes": calls.count("receipt"), "current_replacements": calls.count("current"),
            "view": view(ws, h)}


def interleave_record_switch(ws):
    """record/switch: a newer successor waits for the switch that selected E1; a stale switch never overwrites it."""
    coordinator, _, intent_id = HM.paused()
    h = host(ws, coordinator)
    first_id = coordinator.record_successor(HM.successor(intent_id))["successor_id"]
    effect = Paused(A.switch_effect(h.control, h.releases, h.managed, preconditions=idle(h)))
    a, a_box = run_thread(lambda: coordinator.activation_switch(MID, effect, expected_id=first_id))
    out = {"switch_entered": effect.entered.wait(10)}
    b, b_box = run_thread(lambda: coordinator.record_successor(HM.successor(first_id, LATER)))
    out["record_blocked"] = blocked(b)
    out["head_revision_while_blocked"] = coordinator.store.data[(A.BUCKET, MID)].get("activation_successors")[-1][
        "release_revision"]
    effect.release.set()
    a.join(10)
    b.join(10)
    out["switch"] = outcome(ws, a_box)
    out["record"] = outcome(ws, b_box)
    newer = b_box["result"]["successor_id"]
    before = tree(ws, h)
    out["stale_switch"] = att(ws, lambda: switch(coordinator, h, expected=first_id))
    out["stale_switch_tree_unchanged"] = tree(ws, h) == before
    out["newer_switch"] = att(ws, lambda: switch(coordinator, h, expected=newer))
    out["stale_switch_after"] = att(ws, lambda: switch(coordinator, h, expected=first_id))
    out["current"] = os.readlink(h.releases / "current")
    out["receipt_intent_is_newer"] = json.loads((h.control / "host-activation.json").read_text())["intent_id"] == newer
    out["view"] = view(ws, h)
    return out


def interleave_record_before_switch(ws):
    """a_successor_recorded_before_the_first_switch_leaves_files_inconsistent_not_overwritten."""
    coordinator, _, intent_id = HM.paused()
    h = host(ws, coordinator)
    first_id = coordinator.record_successor(HM.successor(intent_id))["successor_id"]
    second = coordinator.record_successor(HM.successor(first_id, LATER))["successor_id"]
    before = tree(ws, h)
    return {"first_head": att(ws, lambda: switch(coordinator, h, expected=first_id)),
            "second_head": att(ws, lambda: switch(coordinator, h, expected=second)),
            "tree_unchanged": tree(ws, h) == before, "view": view(ws, h)}


class PortFixture:
    """LABELLED switch port (M7 `PortFixture`): no file, no platform check; records each plan it is given."""

    def __init__(self):
        self.plans = []

    def __call__(self, plan):
        self.plans.append(plan)
        return {"effective_id": plan["effective_id"], "revision": plan["effective"]["release_revision"]}


def interleave_portable(ws):
    """test_portable_a_second_switch_then_a_record_wait_for_the_port_inside_the_transaction."""
    coordinator, _, intent_id = HM.paused()
    head = coordinator.record_successor(HM.successor(intent_id))["successor_id"]
    port = PortFixture()
    held = Paused(port)
    a, a_box = run_thread(lambda: coordinator.activation_switch(MID, held, expected_id=head))
    out = {"first_entered": held.entered.wait(10)}
    b, b_box = run_thread(lambda: coordinator.activation_switch(MID, port, expected_id=head))
    out["second_blocked"] = blocked(b)
    out["plans_while_blocked"] = len(port.plans)
    held.release.set()
    a.join(10)
    b.join(10)
    out["both_returned"] = ["error" not in a_box, "error" not in b_box]
    out["plan_effective_ids_are_head"] = [plan["effective_id"] == head for plan in port.plans]
    held = Paused(port)
    a, a_box = run_thread(lambda: coordinator.activation_switch(MID, held, expected_id=head))
    out["third_entered"] = held.entered.wait(10)
    c, c_box = run_thread(lambda: coordinator.record_successor(HM.successor(head, LATER)))
    out["record_blocked"] = blocked(c)
    out["successors_while_blocked"] = len(coordinator.store.data[(A.BUCKET, MID)]["activation_successors"])
    held.release.set()
    a.join(10)
    c.join(10)
    out["third"] = outcome(ws, a_box)
    out["record"] = {"recorded": c_box["result"]["recorded"]} if "result" in c_box else outcome(ws, c_box)
    out["older_head_again"] = att(ws, lambda: coordinator.activation_switch(MID, port, expected_id=head))
    out["last_plan_is_the_old_head_and_count"] = [port.plans[-1]["effective_id"] == head, len(port.plans)]
    return out


# ============================== systemd ===========================================================================

class Systemctl:
    """LABELLED systemctl double (M7 `Systemctl`): answers `show` from a list of states and records every argv."""

    def __init__(self, states, returncodes=None):
        self.states, self.calls, self.returncodes = list(states), [], dict(returncodes or {})

    def __call__(self, argv, timeout):
        self.calls.append([list(argv), timeout])
        stdout = ""
        if argv[1] == "show":
            state = self.states.pop(0) if self.states else "inactive"
            stdout = f"ActiveState={state}\nMainPID=0\nInvocationID=abc123\n"
        return subprocess.CompletedProcess(argv, self.returncodes.get(argv[1], 0), stdout, "")


def systemd_target(ws, service="zeus-aibox-fleet"):
    return A.validate_targets({"schema": "urn:zeus:host-delivery-targets:1", "targets": [
        {"target_id": "aibox-fleet", "kind": A.KIND_SYSTEMD, "root": "/srv/zeus/releases/current",
         "state_dir": str(ws.root / "state"), "service": service}]})["targets"][0]


def descriptor() -> dict:
    return {"schema": "urn:zeus:host-descriptor:1", "target_id": "aibox-fleet", "root": "/srv/zeus/releases/current",
            "revision": COMMIT, "worker_image": HM.IMAGE, "profile_digest": H, "predecessor": None}


def systemd_controls_only_the_registered_unit(ws):
    """test_systemd_target_controls_only_the_registered_zeus_aibox_unit."""
    control = ws.root / "control"
    control.mkdir()
    runner = Systemctl(["active", "inactive", "inactive"])
    target = A.SystemdHostTarget(runner=runner, control_dir=control)
    registered = systemd_target(ws)
    out = {"running": att(ws, lambda: target.running(registered)),
           "stop": att(ws, lambda: target.stop(registered)),
           "launch_without_receipt": att(ws, lambda: target._launch(registered, descriptor(), None))}
    coordinator = HM.coordinator()
    manifest_sha = coordinator.plan(HM.manifest())["manifest_sha256"]
    HM.walk(coordinator, manifest_sha, A.policy.RESTORED_PAUSED)
    coordinator.intend_activation(HM.intent_document())
    A.write_activation(control, coordinator.activation_document(MID))
    (ws.root / "state").mkdir()
    out["launch"] = att(ws, lambda: target._launch(registered, descriptor(), None))
    out["state_dir"] = entries(ws, ws.root / "state")
    out["systemctl_argv"] = ws.n(runner.calls)
    out["only_show_start_stop"] = all(call[0][1] in ("show", "start", "stop") for call in runner.calls)
    out["another_unit"] = att(ws, lambda: target.running(systemd_target(ws, service="sshd")))
    out["unknown_state"] = att(ws, lambda: A.SystemdHostTarget(runner=Systemctl(["weird"])).running(registered))
    return out


def systemd_unit_allow_list(ws):
    """Direct: which `service` names resolve to a unit."""
    names = ["zeus-aibox-fleet", "zeus-aibox-managed-fleet", "zeus-aibox-host-delivery", "sshd", "zeus-aibox-",
             "zeus-aibox-1x", "zeus-aibox-Fleet", "zeus-aibox-x.service", "zeus-aibox-a", "zeus-aibox-" + "a" * 41,
             "zeus-aibox-" + "a" * 42, "zeus-aibox-a_b", "zeus-aibox-fleet\n", "x zeus-aibox-fleet", ""]
    return {name: att(ws, lambda name=name: A.SystemdHostTarget.unit({"service": name})) for name in names}


def systemd_running_states(ws):
    """Direct: `running` per ActiveState, and an unavailable state."""
    registered = systemd_target(ws)
    out = {}
    for state in ("active", "activating", "deactivating", "reloading", "inactive", "failed", "maintenance", ""):
        runner = Systemctl([state])
        out[state or "<empty>"] = {"result": att(ws, lambda runner=runner: A.SystemdHostTarget(runner=runner).running(registered)),
                                   "argv": ws.n(runner.calls)}
    runner = Systemctl(["active"], {"show": 1})
    out["show_fails"] = att(ws, lambda: A.SystemdHostTarget(runner=runner).running(registered))
    custom = Systemctl(["active"])
    A.SystemdHostTarget(runner=custom, timeout=7).running(registered)
    out["custom_timeout"] = ws.n(custom.calls)
    return out


def systemd_stop(ws):
    """Direct: `stop` records the invocation before stopping, reports the exit code, and never resets a failed unit."""
    registered = systemd_target(ws)
    out = {}
    for label, states, returncodes in (("stopped", ["active", "inactive", "inactive"], {}),
                                       ("failed_unit", ["failed", "failed", "failed"], {}),
                                       ("stop_exit_code", ["active", "inactive", "inactive"], {"stop": 5})):
        runner = Systemctl(states, returncodes)
        out[label] = {"result": att(ws, lambda runner=runner: A.SystemdHostTarget(runner=runner).stop(registered)),
                      "argv": [call[0] for call in runner.calls]}
    return out


def systemd_launch_refusals(ws):
    """Direct: each refusal of the launch before a unit start, and a failing start."""
    registered = systemd_target(ws)
    (ws.root / "state").mkdir()
    p = A.policy
    out = {}

    def launch(label, **kwargs):
        runner = Systemctl(["inactive"], kwargs.pop("returncodes", None))
        target = A.SystemdHostTarget(runner=runner, **kwargs)
        out[label] = {"result": att(ws, lambda: target._launch(registered, descriptor(), None)),
                      "argv": [call[0] for call in runner.calls]}
    launch("unconfigured")
    launch("configured_reason", control={"control_dir": None, "reason_code": "control_dir_invalid"})
    control = ws.root / "control"
    control.mkdir()
    launch("no_receipt", control_dir=control)
    (control / "host-activation.json").write_text("{}")
    launch("invalid_schema", control_dir=control)
    (control / "host-activation.json").write_text(json.dumps({"schema": p.ACTIVATION_SCHEMA}))
    launch("no_intent_id", control_dir=control)
    (control / "host-activation.json").write_text(json.dumps({"schema": p.ACTIVATION_SCHEMA, "intent_id": "i-1"}))
    launch("start_fails", control_dir=control, returncodes={"start": 1})
    out["state_after_failed_start"] = entries(ws, ws.root / "state")
    A.write_fence(control, MID, "fixture")
    launch("fenced", control_dir=control)
    return out


# ============================== layout ============================================================================

def layout_dry_run_and_idempotent(ws):
    """test_prepare_layout_is_dry_run_by_default_and_idempotent."""
    root = ws.root / "srv-zeus"
    dry = A.prepare_layout(root)
    out = {"dry": ws.n(dry), "root_exists_after_dry_run": root.exists(),
           "states": sorted({row["state"] for row in dry["directories"]}),
           "order_is_the_layout": [row["path"] for row in dry["directories"]] == list(A.LAYOUT)}
    applied = A.prepare_layout(root, apply=True)
    out["applied"] = ws.n(applied)
    out["again"] = sorted({row["state"] for row in A.prepare_layout(root, apply=True)["directories"]})
    out["tree"] = sorted(str(p.relative_to(root)) for p in root.rglob("*"))
    return out


def layout_edges(ws):
    """Direct: relative root, partial layout, a conflicting file, a symlink, and a dry run that stays a dry run."""
    out = {"relative_root": att(ws, lambda: A.prepare_layout("srv/zeus")),
           "relative_root_apply": att(ws, lambda: A.prepare_layout(Path("srv/zeus"), apply=True))}
    partial = ws.root / "partial"
    (partial / "repo").mkdir(parents=True)
    (partial / "runtime" / "control").mkdir(parents=True)
    out["partial_dry"] = ws.n(A.prepare_layout(partial))
    out["partial_applied"] = ws.n(A.prepare_layout(partial, apply=True))
    clash = ws.root / "clash"
    clash.mkdir()
    (clash / "repo").mkdir()
    (clash / "worktrees").write_text("file")
    out["conflicting_file"] = att(ws, lambda: A.prepare_layout(clash, apply=True))
    out["nothing_created_before_the_conflict"] = sorted(p.name for p in clash.iterdir())
    out["conflict_in_a_dry_run"] = att(ws, lambda: A.prepare_layout(clash))
    linked = ws.root / "linked"
    (linked / "elsewhere").mkdir(parents=True)
    os.symlink(linked / "elsewhere", linked / "releases")
    out["symlinked_entry"] = att(ws, lambda: A.prepare_layout(linked, apply=True))
    out["created_before_the_symlink"] = sorted(p.name for p in linked.iterdir())
    nested = ws.root / "nested"
    nested.mkdir()
    (nested / "runtime").write_text("file")
    out["parent_is_a_file"] = att(ws, lambda: A.prepare_layout(nested, apply=True))
    out["created_before_the_file_parent"] = sorted(p.name for p in nested.iterdir())
    out["layout"] = list(A.LAYOUT)
    return out


# ============================== canonical =========================================================================

def checkout_path(ws, *, tool: bool = True) -> Path:
    """LABELLED checkout layout: `<root>/checkout/src/codex_harness` and, with `tool`, a COPY of SOURCE scripts/aibox_data."""
    path = ws.root / "checkout"
    (path / "src" / "codex_harness").mkdir(parents=True)
    (path / "src" / "codex_harness" / "__init__.py").write_text("")
    if tool:
        shutil.copytree(Path(A.SOURCE_ROOT) / "scripts" / "aibox_data", path / "scripts" / "aibox_data",
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    return path


@contextlib.contextmanager
def clean_imports():
    """`canonical_module` edits sys.path and imports `aibox_data.*`: both are restored after the case."""
    path, modules = list(sys.path), {name for name in sys.modules if name == "aibox_data" or name.startswith("aibox_data.")}
    try:
        yield
    finally:
        sys.path[:] = path
        for name in [n for n in sys.modules if (n == "aibox_data" or n.startswith("aibox_data.")) and n not in modules]:
            del sys.modules[name]


def canonical_tool_resolution(ws):
    """test_canonical_tool_is_resolved_from_this_checkout: from the package's checkout, never the working directory."""
    path = checkout_path(ws)
    elsewhere = ws.root / "elsewhere"
    elsewhere.mkdir()
    previous = os.getcwd()
    try:
        os.chdir(elsewhere)
        with A.checkout(path):
            tool = A.canonical_tool()
    finally:
        os.chdir(previous)
    return {"tool": ws.n(tool), "is_scripts_aibox_data_of_the_checkout": tool == path / "scripts" / "aibox_data",
            "main_present": (tool / "__main__.py").is_file(), "is_a_path": type(tool).__name__.endswith("Path")}


def canonical_tool_absent(ws):
    """The tool absent beside the package (as in an installed wheel): refused by name."""
    path = checkout_path(ws, tool=False)
    with A.checkout(path):
        first = att(ws, A.canonical_tool)
    (path / "scripts" / "aibox_data").mkdir(parents=True)
    with A.checkout(path):
        no_main = att(ws, A.canonical_tool)
        run = att(ws, lambda: A.run_canonical(["pel-owners"], runner=lambda argv, **kw: pytest_fail()))
    return {"absent": first, "directory_without_main": no_main, "run_canonical_refuses_before_running": run}


def pytest_fail():
    raise AssertionError("the runner must not be reached")


def canonical_module_import(ws):
    """`canonical_module`: the scripts directory is put first on sys.path and `aibox_data.<name>` imported."""
    path = checkout_path(ws)
    scripts = str(path / "scripts")
    with clean_imports(), A.checkout(path):
        before = scripts in sys.path
        module = A.canonical_module("contracts")
        first_entry = sys.path[0] == scripts
        again = A.canonical_module("contracts") is module
        count = sys.path.count(scripts)
        missing = att(ws, lambda: A.canonical_module("no_such_module"))
        return {"on_path_before": before, "module": module.__name__, "scripts_first": first_entry,
                "same_module_twice": again, "path_entries": count, "has_pg_schema": hasattr(module, "PG_SCHEMA"),
                "missing_module": missing["raised"]["type"] if "raised" in missing else missing}


def canonical_argv(ws):
    """test_canonical_tool_runs_under_this_interpreter_with_its_checkout_path."""
    path = checkout_path(ws)
    seen = []

    def runner(argv, **kwargs):
        seen.append({"argv": list(argv), "kwargs": {k: (v if not callable(v) else "<callable>") for k, v in kwargs.items()}})
        return subprocess.CompletedProcess(argv, 0, json.dumps({"valid": True}).encode(), b"")
    os_cwd = os.getcwd()
    try:
        os.chdir(ws.root)
        with A.checkout(path):
            result = A.run_canonical(["pel-owners", "--inventory", "C:\\x\\i.json", "--owners", "o.json"], runner=runner)
    finally:
        os.chdir(os_cwd)
    return {"seen": ws.n(seen), "interpreter_is_this_one": seen[0]["argv"][0] == sys.executable, "result": ws.n(result)}


def canonical_wrapper_exit_rule(ws):
    """test_a_wrapper_never_promotes_exit_zero_beside_a_failing_typed_result, and the rest of the receipt rule."""
    path = checkout_path(ws)
    out = {}
    written = ws.root / "written.json"
    written.write_bytes(b'{"a": 1}\n')

    def runner(code, stdout):
        return lambda argv, **kwargs: subprocess.CompletedProcess(argv, code, stdout, b"")

    def run(label, argv, code, stdout, *, embeds_root=False, **kwargs):
        with A.checkout(path):
            result = A.run_canonical(argv, runner=runner(code, stdout), **kwargs)
        if embeds_root:
            # The digest covers a stdout that names this case's random temporary root: recorded as a comparison only.
            receipt = result["receipt"]
            covers = receipt["result_sha256"] == sha(stdout)
            result = {**result, "receipt": {**receipt, "result_sha256": "<digest of stdout naming the temporary root>"},
                      "digest_is_the_stdout_digest": covers}
        out[label] = {"returned": ws.n(result)}
    typed = lambda **doc: json.dumps(doc).encode()  # noqa: E731
    run("lying_exit_zero_false_typed", ["compare-redis", "--source", "s", "--target", "t"], 0, typed(match=False))
    run("match_true", ["compare-redis"], 0, typed(match=True))
    run("not_json", ["pel-owners"], 0, b"not json")
    run("typed_true_but_exit_one", ["pel-owners"], 1, typed(valid=True))
    run("typed_false_exit_two_keeps_the_code", ["pel-owners"], 2, typed(valid=False))
    run("typed_true_exit_zero", ["pel-owners"], 0, typed(valid=True))
    run("typed_must_be_true_not_truthy", ["pel-owners"], 0, typed(valid=1))
    run("json_list", ["pel-owners"], 0, b"[true]")
    run("empty_stdout", ["pel-owners"], 0, b"")
    run("str_stdout", ["pel-owners"], 0, json.dumps({"valid": True}))
    run("none_stdout", ["pel-owners"], 0, None)
    run("non_utf8", ["pel-owners"], 0, b"\xff\xfe")
    run("stage_complete", ["stage"], 0, typed(status="complete"))
    run("stage_partial", ["stage"], 0, typed(status="partial"))
    run("stage_true_is_not_complete", ["stage"], 0, typed(status=True))
    run("unknown_command", ["nope"], 0, typed(ok=True))
    run("verify_staged", ["verify-staged"], 0, typed(match=True))
    run("gate", ["gate"], 0, typed(eligible=True))
    run("inventory_writes_out", ["inventory"], 0, typed(ok=True, written=str(written)))
    run("written_file_missing", ["inventory"], 0, typed(ok=True, written=str(ws.root / "missing.json")),
        embeds_root=True)
    run("written_is_a_directory", ["inventory"], 0, typed(ok=True, written=str(ws.root)), embeds_root=True)
    run("check_and_subject", ["compare-pg"], 0, typed(match=True), check="verify-staged", subject="root=art")
    run("check_unknown_name", ["compare-pg"], 0, typed(match=True), check="pg-compare")
    run("gate_named_r0", ["gate"], 0, typed(eligible=True), check="gate-r0")
    return out


# ============================== compare ===========================================================================

REGISTRY = {"bucket": "fleet_registry", "id": "fleet", "body": {"repository": "C:\\workspaces\\zeus\\repo"}}
HISTORY = {"bucket": "events", "id": "e1", "body": {"path": "C:\\workspaces\\zeus\\artifacts\\old"}}
LANE = {"bucket": "operations", "id": "o1", "body": {"status": "accepted"}}
MAP = {"public": "zeus_aibox_control", "zeus_fleet_harness": "zeus_aibox_harness"}


def canonical_inventory(ws, role, schemas):
    contracts = A.canonical_module("contracts")
    inventory = {"schema": contracts.PG_SCHEMA, "server_version_num": 171100,
                 "extensions": {"plpgsql": "1.0", "vector": "0.8.6"}, "schemas": {}}
    for name, rows in schemas.items():
        export = ws.root / f"{role}-{name}.jsonl"
        export.write_text("".join(json.dumps(r) + "\n" for r in rows))
        inventory["schemas"][name] = {"tables": ["documents"], "sequences": {},
                                      "buckets": contracts.pg_schema_from_export(export)}
    return inventory


def compare_per_schema(ws):
    """test_per_schema_comparison_with_registry_delta_only_on_public (the real canonical tool, as a subprocess)."""
    path = checkout_path(ws)
    out = {}
    with clean_imports(), A.checkout(path):
        mapping = A.canonical_module("mapping")
        relocated = REGISTRY | {"body": {"repository": "/srv/zeus/repo"}}
        delta = {"changes": [{"bucket": "fleet_registry", "id": "fleet", "before_sha256": mapping.body_sha(REGISTRY["body"]),
                              "after_sha256": mapping.body_sha(relocated["body"])}]}
        source = canonical_inventory(ws, "s", {"public": [REGISTRY, HISTORY], "zeus_fleet_harness": [LANE]})
        target = canonical_inventory(ws, "t", {"zeus_aibox_control": [relocated, HISTORY], "zeus_aibox_harness": [LANE]})
        public = A.pg_compare_schema(source, target, MAP, "public", delta)
        lane = A.pg_compare_schema(source, target, MAP, "zeus_fleet_harness")
        undeclared = A.pg_compare_schema(source, target, MAP, "public")
        out["public"] = ws.n(public)
        out["lane"] = ws.n(lane)
        out["undeclared_delta"] = ws.n(undeclared)
        out["delta_on_a_non_public_schema"] = att(ws, lambda: A.pg_compare_schema(source, target, MAP,
                                                                                 "zeus_fleet_harness", delta))
        history_delta = {"changes": [{**delta["changes"][0], "bucket": "events", "id": "e1"}]}
        out["delta_on_a_history_bucket"] = att(ws, lambda: A.pg_compare_schema(source, target, MAP, "public", history_delta))
        out["schema_missing_in_the_source"] = att(ws, lambda: A.pg_compare_schema(source, target, MAP, "zeus_team_profile_001"))
        out["schema_missing_in_the_source_inventory"] = att(ws, lambda: A.pg_compare_schema(
            {**source, "schemas": {"public": source["schemas"]["public"]}}, target, MAP, "zeus_fleet_harness"))
        out["coverage_complete"] = ws.n(A.pg_coverage_receipt(MAP, [public["receipt"], lane["receipt"]]))
        out["coverage_missing"] = ws.n(A.pg_coverage_receipt(MAP, [public["receipt"]]))
        out["coverage_duplicated"] = ws.n(A.pg_coverage_receipt(MAP, [public["receipt"], public["receipt"], lane["receipt"]]))
        out["coverage_failing"] = ws.n(A.pg_coverage_receipt(MAP, [undeclared["receipt"], lane["receipt"]]))
    return out


def catalog(**schemas):
    body = {"owner": "zeus", "acl": None, "comment": None, "relations": {}, "indexes": [], "constraints": [],
            "sequences": [], "views": [], "functions": [], "triggers": []}
    return {"schema": A.policy.CATALOG_SCHEMA, "database": "zeus", "server_version_num": 171100,
            "extensions": [["vector", "0.8.6", "public"]], "extension_members": ["vector"],
            "schemas": {name: {**body, **extra} for name, extra in schemas.items()}}


def rel() -> dict:
    return {"documents": {"kind": "r", "columns": [["embedding", "public.vector", False, None]], "rows": 2, "rows_sha256": H}}


D1 = {"public": "zeus_aibox_control", "zeus_fleet_harness": "zeus_aibox_harness",
      "zeus_fleet_interface": "zeus_aibox_interface", "zeus_team_profile_001": "zeus_team_profile_001"}


def source_catalog():
    fk = {"constraints": [["knowledge_edges", "fk", "f", "FOREIGN KEY (source) REFERENCES public.knowledge_nodes(id)"]]}
    return catalog(public={"relations": rel(), **fk}, zeus_fleet_harness={"relations": rel()},
                   zeus_fleet_interface={"relations": rel()}, zeus_team_profile_001={"relations": rel()})


def compare_rename_plan(ws):
    """test_rename_plan_is_total_and_allows_public_only_as_the_control_ledger (the plan only; `_rename` needs PostgreSQL)."""
    p = A.policy
    out = {"plan": att(ws, lambda: p.rename_plan(source_catalog(), D1))}
    out["not_total"] = att(ws, lambda: p.rename_plan(source_catalog(), {k: v for k, v in D1.items() if k != "zeus_team_profile_001"}))
    out["public_remapped"] = att(ws, lambda: p.rename_plan(source_catalog(), {**D1, "public": "zeus_other"}))
    out["public_as_a_target"] = att(ws, lambda: p.rename_plan(source_catalog(), {**D1, "zeus_team_profile_001": "public"}))
    out["target_occupied"] = att(ws, lambda: p.rename_plan(source_catalog(), {**D1, "zeus_fleet_harness": "zeus_team_profile_001",
                                                                             "zeus_team_profile_001": "zeus_team_profile_x"}))
    reverse = p.reverse_maps({"schema_map": D1, "path_map": []})["schema_map"]
    out["reverse_map"] = reverse
    target = catalog(public={}, zeus_aibox_control={"relations": rel()}, zeus_aibox_harness={"relations": rel()},
                     zeus_aibox_interface={"relations": rel()}, zeus_team_profile_001={"relations": rel()})
    out["reverse_plan"] = att(ws, lambda: p.rename_plan(target, reverse, reverse=True))
    out["reverse_without_the_flag"] = att(ws, lambda: p.rename_plan(target, reverse))
    return out


def compare_catalog_mapping(ws):
    """test_catalog_comparison_maps_names_but_keeps_extension_references, and `catalog_digest`."""
    import copy

    p = A.policy
    source = source_catalog()
    renamed = copy.deepcopy(source)
    renamed["schemas"] = {D1[k]: v for k, v in renamed["schemas"].items()}
    renamed["schemas"]["zeus_aibox_control"]["constraints"] = [
        ["knowledge_edges", "fk", "f", "FOREIGN KEY (source) REFERENCES zeus_aibox_control.knowledge_nodes(id)"]]
    renamed["schemas"]["public"] = catalog(public={})["schemas"]["public"]  # the bare extension home
    out = {"renamed": att(ws, lambda: p.compare_catalogs(source, renamed, D1))}
    changed = copy.deepcopy(renamed)
    changed["schemas"]["zeus_aibox_harness"]["relations"]["documents"]["rows"] = 1
    out["rows_changed"] = att(ws, lambda: p.compare_catalogs(source, changed, D1))
    typed = copy.deepcopy(renamed)
    typed["schemas"]["zeus_aibox_harness"]["relations"]["documents"]["columns"][0][1] = "zeus_aibox_control.vector"
    out["extension_type_renamed"] = att(ws, lambda: p.compare_catalogs(source, typed, D1))
    missing = copy.deepcopy(renamed)
    del missing["schemas"]["zeus_team_profile_001"]
    out["missing_on_target"] = att(ws, lambda: p.compare_catalogs(source, missing, D1))
    other_ext = copy.deepcopy(renamed)
    other_ext["extensions"] = [["vector", "0.8.5", "public"]]
    out["extension_version"] = att(ws, lambda: p.compare_catalogs(source, other_ext, D1))
    other_db = {**source, "database": "other"}
    out["catalog_digest"] = {"deterministic": A.catalog_digest(source) == A.catalog_digest(copy.deepcopy(source)),
                             "ignores_the_database_name": A.catalog_digest(source) == A.catalog_digest(other_db),
                             "sees_a_row_count": A.catalog_digest(source) != A.catalog_digest(changed),
                             "sha256_hex": bool(re.fullmatch(r"[0-9a-f]{64}", A.catalog_digest(source))),
                             "value": A.catalog_digest(source)}
    return out


# ============================== registry ==========================================================================

GROUPS = {
    "files": [("writer_start_receipt_gap", files_writer_gap),
              ("launcher_accepts_exactly_the_coordinator_receipt", files_launcher_accepts_receipt),
              ("fence_refuses_every_launcher_role", files_fence_refuses_every_role),
              ("t3_successor_receipt", files_t3_successor_receipt), ("document_bytes", files_document_bytes),
              ("atomic_write", files_atomic_write), ("write_activation_edges", files_write_activation_edges),
              ("write_fence_edges", files_write_fence_edges), ("current_revision", files_current_revision),
              ("classify_activation_files", files_classify), ("release_ready", files_release_ready)],
    "switch": [("a1_receipt_then_current_fsynced", switch_a1), ("a2_crash_after_the_receipt", switch_a2),
               ("a3_rerun_when_switched_is_cached", switch_a3),
               *[("a4_inconsistent_" + d, switch_a4(d)) for d in ("foreign_receipt", "foreign_current", "absolute_elsewhere",
                                                                   "missing_current", "missing_receipt")],
               *[("a5_refused_" + d, switch_a5(d)) for d in ("fence", "missing", "writable", "runtime", "venv", "package")],
               ("a6_failed_replace_removes_only_its_own_link", switch_a6), ("a7_stale_reader_refused_by_the_launcher", switch_a7),
               ("ph4_11_limited_active_writes_no_current", switch_ph4_11), ("non_posix_refusal", switch_non_posix),
               ("cli_successor_and_switch", switch_cli), ("launcher_process", switch_launcher_process)],
    "recovery": [*[("precondition_" + name, recovery_precondition(name, violation)) for name, violation in PRECONDITIONS],
                 ("idle_host_and_unreadable_process_table", recovery_idle_host), ("unit_states", recovery_unit_states),
                 ("owner_marker", recovery_owner_marker), ("runner_argv", recovery_runner_argv),
                 ("runner_processes", recovery_runner_processes)],
    "interleave": [("switch_switch", interleave_switch_switch), ("record_switch", interleave_record_switch),
                   ("record_before_the_first_switch", interleave_record_before_switch),
                   ("portable_port_serialization", interleave_portable)],
    "systemd": [("controls_only_the_registered_unit", systemd_controls_only_the_registered_unit),
                ("unit_allow_list", systemd_unit_allow_list), ("running_states", systemd_running_states),
                ("stop", systemd_stop), ("launch_refusals", systemd_launch_refusals)],
    "layout": [("dry_run_and_idempotent", layout_dry_run_and_idempotent), ("edges", layout_edges)],
    "canonical": [("tool_resolution", canonical_tool_resolution), ("tool_absent", canonical_tool_absent),
                  ("module_import", canonical_module_import), ("argv", canonical_argv),
                  ("wrapper_exit_rule", canonical_wrapper_exit_rule)],
    "compare": [("per_schema_comparison", compare_per_schema), ("rename_plan", compare_rename_plan),
                ("catalog_comparison_mapping", compare_catalog_mapping)],
}


def run(api) -> dict:
    global A
    A = api
    HM.A = api
    out = {}
    for group, cases in GROUPS.items():
        out[group] = {}
        for name, fn in cases:
            HM.STORES.clear()
            ws = Ws()
            try:
                try:
                    result = fn(ws)
                except Exception as exc:  # an unexpected failure of the characterized operation is itself compared
                    result = {"case_error": type(exc).__name__, "message": ws.n(str(exc))[:300]}
            finally:
                ws.close()
            out[group][name] = result
    out["carried"] = CARRIED
    return out
