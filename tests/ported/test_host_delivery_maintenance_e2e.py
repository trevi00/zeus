"""Ported PR-3 (`feat/host-delivery-maintain-pr3` 09e596ce) suite `tests/test_host_delivery_maintenance_e2e.py` run against the target (G1-14b).

Every assertion is PR-3's, unchanged. Adaptations are import lines and construction only: the helpers are the ported
`test_host_delivery` / `test_managed_runtime` / `test_managed_systemd`; `HostDelivery`, `MemoryStore`, `organization`, `fixture_config`,
`owner_qualified_canary` and the wired `SystemdManagedFleetTarget` come from the `m7_delivery` shim, `Fleet` and `MaintenanceCanaryExecutor(fleet, launcher, interval=)` from the `m7_coordination`
facade (the executor over the Fleet objects of its routes), `FakeLauncher` from the ported `test_fleet`; the target adapters are `delivery.adapters.*` (`TargetFiles` is `delivery.adapters.target_files`), `HostFacts` is
`host_os.adapters.host_facts`; `LazyArtifacts(root)` is `LazyArtifacts(root, FileArtifacts)` (the store constructor is injected); and the
systemd target and the `CredentialObserver` are given the `process_reader` composition injects (`delivery_hosts.process_reader()`: the real `/proc` reader; PR-3's observer built `HostReader()` itself).

PR-3 docstring follows.

INV-HOST-DELIVERY-MAINTENANCE-001 end to end (integration of the host, Fleet and adapter slices).

One ACTIVE, consumed `managed_fleet_systemd` delivery is maintained through its three owner phases:

1. The delivery is driven to ACTIVE by real ticks with the owner's `fleet_worker_operation` canary: a
   LABELLED owner request, then a LABELLED owner receipt and COMPLETED owner action for the incumbent.
2. `restart` replaces exactly the recorded incumbent through the real guarded graceful lifecycle: one more
   `systemctl start` of the simulated unit, no signal, a new invocation and startup receipt, and the
   owner target snapshot untouched. PR-2's consumption predicate refuses the unbound new generation.
3. `arm` verifies PRIMARY through the real `CredentialObserver` running a LABELLED helper script against
   the real `/proc` identities, grants the one-job permit and arms the generation; a LABELLED owner step
   then writes the REQUESTED canary action and enqueues its job through the real `Fleet.enqueue`, and a
   replayed `arm` admits and runs exactly that job through the real `MaintenanceCanaryExecutor` and
   `run_preclaimed` with the labelled `test_fleet.FakeLauncher` (no process, model or provider).
4. A LABELLED owner step completes the action and writes the instance-bound receipt from its outcome.
5. `bind` consumes the new instance; PR-2's consumption and canary predicates accept, the permit is
   closed, and the release, pointer and queue are unchanged.

The host side is real (`test_managed_systemd`): sealed runtimes of a labelled source repository, the real
`supervise`/`launch`/`entry` fixture workload, real processes. systemd itself is the LABELLED
`SimulatedSystemd`, extended to report the properties the maintenance observation reads. The Fleet and the
owner-action rows live in a separate in-memory control store; nothing touches a real unit, database,
provider or model.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest
from m7_coordination import Fleet, MaintenanceCanaryExecutor
from m7_delivery import (
    HostDelivery,
    MemoryStore,
    SystemdManagedFleetTarget,
    fixture_config,
    organization,
    owner_qualified_canary,
)
from test_fleet import FakeLauncher
from test_host_delivery import (
    PROFILE,
    Clock,
    FakeGitHub,
    SerialStore,
    observer_for,
    pin,
    plan_document,
    reviewed_release,
    runtime_image,
)
from test_managed_runtime import fixture_manifest, make_source, read, state
from test_managed_systemd import SimulatedSystemd, finish, systemd_target

from codex_harness.composition import delivery_hosts
from codex_harness.coordination.application.owner_actions.state import BUCKET_ACTIONS
from codex_harness.coordination.domain import owner_actions as do
from codex_harness.delivery.adapters.host_delivery import (
    DESCRIPTOR_FILE,
    RECEIPT_FILE,
    STATE_FILE,
    canary_receipt_file,
)
from codex_harness.delivery.adapters.maintenance_evidence import (
    CredentialObserver,
    LazyArtifacts,
    control_action_reader,
    trusted_authority_reader,
)
from codex_harness.delivery.adapters.managed_runtime import TARGET_FILE
from codex_harness.delivery.adapters.target_files import TargetFiles
from codex_harness.delivery.application.host_delivery.state import (
    BUCKET_DESCRIPTORS,
    BUCKET_INTENTS,
    BUCKET_PLANS,
    BUCKET_TARGETS,
)
from codex_harness.delivery.domain import host_migration_evidence as hme
from codex_harness.delivery.domain.host_delivery import (
    ACTIVE,
    AWAITING_CONSUMPTION,
    CANARY_FLEET,
    CANARY_REQUEST_SCHEMA,
    MANAGED_TARGET_FIELDS,
    DeliveryRefused,
    plan_digest,
    validate_plan,
)
from codex_harness.delivery.domain.host_migration import MigrationRefused
from codex_harness.host_os.adapters.host_facts import HostFacts
from codex_harness.kernel.ids import digest
from codex_harness.storage.adapters.file_artifacts import FileArtifacts

posix_only = pytest.mark.skipif(os.name == "nt", reason="the systemd binding is Linux-only (aibox)")
needs_profile = pytest.mark.skipif(PROFILE is None, reason="this checkout packages no worker profile")
TARGET_ID = "managed-fleet"
DIRECTIVE = b"LABELLED recorded user directive: same-descriptor PRIMARY maintenance of managed-fleet\n"
ENVIRONMENT_FILES = "/labelled/config/zeus-aibox.env (ignore_errors=no)"
HELPER = ("# LABELLED test helper: fixed PRIMARY booleans; reads no secret and no process environment\n"
          "import json, sys\n"
          "print(json.dumps({'pid': int(sys.argv[2]), 'has_token': True, 'is_primary': True,"
          " 'is_secondary': False}))\n")


class MaintainedSystemd(SimulatedSystemd):
    """LABELLED `SimulatedSystemd` that also reports what the maintenance observation reads: the main
    process as `ExecMainPID`, no pending daemon reload, the unit process's own control group, one
    environment file and no drop-in."""

    def __call__(self, argv, timeout=None, **kwargs):
        result = super().__call__(argv, timeout=timeout, **kwargs)
        if argv[1] != "show":
            return result
        pid = self.process.pid if self.active() else 0
        group = (HostFacts().cgroup(pid) or "") if pid else ""
        extra = (f"ExecMainPID={pid}\nNeedDaemonReload=no\nControlGroup={group}\n"
                 f"EnvironmentFiles={ENVIRONMENT_FILES}\nDropInPaths=\n")
        return subprocess.CompletedProcess(argv, 0, result.stdout + extra, "")


@pytest.fixture(scope="module")
def source(tmp_path_factory):
    return make_source(tmp_path_factory.mktemp("maintenance-source") / "source")


def rows(system) -> dict:
    plan_id = system["plan"]["plan_id"]
    with system["store"].transaction() as tx:
        intent = tx.get(BUCKET_INTENTS, plan_id)
        return {"intent": intent, "plan_row": tx.get(BUCKET_PLANS, plan_id),
                "descriptor_row": tx.get(BUCKET_DESCRIPTORS, TARGET_ID),
                "target_row": tx.get(BUCKET_TARGETS, TARGET_ID), "intents": tx.scan(BUCKET_INTENTS),
                "release": tx.get("releases", system["plan"]["release_id"]),
                "pointer": tx.get("deployment", "active"),
                "queue": tx.get("release_queue", system["plan"]["release_id"])}


def tick_until(system, done, *, limit=200):
    results = []
    for _ in range(limit):
        result = system["delivery"].tick()
        system["clock"].advance(1)
        results.append(result)
        if done(result):
            return results
        assert result["outcome"] not in {"blocked", "refused"}, results[-5:]
        time.sleep(0.1)
    raise AssertionError([(r["stage"], r["outcome"], r["reason_code"]) for r in results[-5:]])


def system_for(tmp_path, source):
    document, target = systemd_target(tmp_path, source["root"])
    unit = MaintainedSystemd(Path(target["state_dir"]))
    clock = Clock()
    control = MemoryStore()
    fleet = Fleet(control, clock=clock)
    fleet.register(fixture_config(Path(Path.cwd().anchor) / "labelled-fixture"))
    host = SystemdManagedFleetTarget(workload="fixture", fleet=fleet, runner=unit,
                                     process_reader=delivery_hosts.process_reader())
    store, org = SerialStore(), organization()
    release = reviewed_release(store, org)
    authorities = tmp_path / "control-runtime" / "artifacts"
    authorities.mkdir(parents=True)
    (authorities / (hashlib.sha256(DIRECTIVE).hexdigest() + ".txt")).write_bytes(DIRECTIVE)
    helper = tmp_path / "owner" / "credential_bool_fixture.py"
    helper.parent.mkdir()
    helper.write_text(HELPER, encoding="utf-8")
    launcher = FakeLauncher({})
    delivery = HostDelivery(
        store, org, github=FakeGitHub(), hosts={"managed_fleet_systemd": host},
        canaries={CANARY_FLEET: owner_qualified_canary}, clock=clock, observer=observer_for(store), enabled=True,
        resume_seconds=0, authorities=trusted_authority_reader(authorities), artifacts=LazyArtifacts(authorities, FileArtifacts),
        canary_records=control_action_reader(control),
        credentials=CredentialObserver(str(helper), hashlib.sha256(HELPER.encode()).hexdigest(),
                                      process_reader=delivery_hosts.process_reader()),
        maintenance_fleet=fleet, canary_executor=MaintenanceCanaryExecutor(fleet, launcher, interval=0.05))
    delivery.register_targets(document)
    plan = plan_document(release, plan_id="managed-plan-1", target_id=TARGET_ID, image=runtime_image(source["root"]),
                         profile=PROFILE, descriptor_revision=source["a"], consumption_timeout=900, canary=CANARY_FLEET)
    delivery.register(plan, pin())
    return {"store": store, "control": control, "fleet": fleet, "clock": clock, "delivery": delivery, "host": host,
            "unit": unit, "plan": plan, "target": target, "launcher": launcher, "release": release}


def owner_request(system) -> None:
    """LABELLED: the owner asks for its actual canary of exactly this plan (the initial activation)."""
    plan = validate_plan(system["plan"])
    TargetFiles.write_request(system["target"], plan["plan_id"], {
        "schema": CANARY_REQUEST_SCHEMA, "action_id": "a" * 64, "plan_id": plan["plan_id"],
        "plan_sha256": plan_digest(plan), "target_id": TARGET_ID, "revision": plan["target_descriptor"]["revision"],
        "expected_descriptor": plan["expected_descriptor"], "requested_at": "2026-09-22T00:00:00+00:00"})


def owner_canary(system, instance_id: str, *, state=do.REQUESTED) -> dict:
    """LABELLED owner step: the owner canary action of this instance, as `OwnerActions._advance_canary`
    writes it (REQUESTED with its deterministic job id), in the CONTROL store."""
    current = rows(system)
    binding = do.canary_binding(current["plan_row"], current["intent"], instance_id)
    row = do.new_action(do.DELIVERY_CANARY, binding, {"id": "owners-1", "policy_sha256": "r" * 64},
                        {"lane": "fixture"}, system["clock"]())
    row = do.moved(row, do.REQUESTED, system["clock"](), job_id=do.canary_job_id(row["id"]))
    with system["control"].transaction() as tx:
        tx.put(BUCKET_ACTIONS, row["id"], row)
    return row


def owner_completes(system, row: dict, job_id: str) -> dict:
    """LABELLED owner step: the action completes from its accepted outcome and the instance-bound receipt
    is written from exactly that outcome (`domain.owner_actions.canary_receipt`)."""
    outcome = {"state": do.VERDICT_ACCEPTED, "reason_code": "canary_accepted",
               "evidence": {"job_id": job_id, "operation_id": job_id, "decision_id": "decision-" + job_id,
                            "execution_ref": "sha256:" + "7" * 64}}
    completed = do.moved(row, do.COMPLETED, system["clock"](), reason_code="canary_accepted", outcome=outcome)
    with system["control"].transaction() as tx:
        tx.put(BUCKET_ACTIONS, completed["id"], completed)
    receipt = do.canary_receipt(completed, outcome, datetime.now(timezone.utc).isoformat())
    TargetFiles.write_receipt(system["target"], system["plan"]["plan_id"], receipt)
    return completed


def activate(system) -> dict:
    """Real ticks to ACTIVE under the owner's canary of the incumbent instance."""
    owner_request(system)
    receipt_path = Path(system["target"]["state_dir"]) / RECEIPT_FILE
    tick_until(system, lambda r: r["stage"] == AWAITING_CONSUMPTION and receipt_path.exists()
               and r["reason_code"] == "canary_owner_receipt_pending")
    startup = read(receipt_path)
    row = owner_canary(system, startup["instance_id"])
    owner_completes(system, row, row["job_id"])
    assert tick_until(system, lambda r: r["stage"] == ACTIVE)[-1]["stage"] == ACTIVE
    return startup


def maintenance_document(system, startup) -> tuple[dict, str]:
    current = rows(system)
    intent, plan_row = current["intent"], current["plan_row"]
    launch = read(state(system["target"], STATE_FILE))
    document = {"schema": "urn:zeus:host-delivery-active-generation:1", "kind": "active_generation_restart",
                "plan_id": plan_row["plan_id"], "plan_sha256": plan_row["plan_sha256"],
                "pin_sha256": plan_row["pin"]["sha256"], "target_id": TARGET_ID,
                "release_id": system["plan"]["release_id"], "descriptor_sha256": intent["descriptor_sha256"],
                "from": {"stage": ACTIVE, "updated_at": intent["updated_at"]},
                "retiring": {"instance_id": startup["instance_id"], "invocation_id": launch["invocation_id"],
                             "launch_sha256": digest(launch)},
                "reason": "unit_environment_changed", "canary_window_seconds": 3600,
                "authority": "sha256:" + hashlib.sha256(DIRECTIVE).hexdigest(), "approved_by": "conductor"}
    return document, "sha256:" + digest(document)


def pr2_consumption(system):
    """PR-2's unchanged observer predicates over the current rows and host files (read only)."""
    current = rows(system)
    target = system["target"]
    view = hme.delivery_view(current["target_row"], current["plan_row"], current["intent"], current["descriptor_row"],
                             current["intents"], target_id=TARGET_ID, plan_id=system["plan"]["plan_id"])
    descriptor = read(state(target, DESCRIPTOR_FILE))
    startup = read(state(target, RECEIPT_FILE))
    consumed = hme.require_consumption(view, descriptor, startup,
                                       {"image": descriptor["worker_image"], "profile_sha256": descriptor["profile_digest"]},
                                       target_id=TARGET_ID, plan_id=system["plan"]["plan_id"],
                                       state_dir=target["state_dir"])
    return consumed, startup, current


@pytest.fixture(autouse=True)
def no_executor_transports(monkeypatch):
    """No executor may be built here: BOTH transports raise if anything reaches them."""
    import m7_executor as executor

    def never(*_args, **_kwargs):
        raise AssertionError("an executor transport was reached")
    monkeypatch.setattr(executor, "AppServer", never)
    monkeypatch.setattr(executor, "ClaudeCodeRuntime", never)


class SignalLedger:
    """Records every signal this process sends; a probe (`kill(pid, 0)`) is liveness, not a signal."""

    def __init__(self, monkeypatch):
        self.sent = []
        kill, killpg = os.kill, os.killpg

        def recording_kill(pid, sig):
            if sig != 0:
                self.sent.append(("kill", pid, sig))
            return kill(pid, sig)

        def recording_killpg(pid, sig):
            self.sent.append(("killpg", pid, sig))
            return killpg(pid, sig)
        monkeypatch.setattr(os, "kill", recording_kill)
        monkeypatch.setattr(os, "killpg", recording_killpg)


@posix_only
@needs_profile
def test_one_active_generation_is_restarted_armed_and_bound_end_to_end(tmp_path, source, monkeypatch):
    system = system_for(tmp_path, source)
    target, unit, fleet, delivery = system["target"], system["unit"], system["fleet"], system["delivery"]
    try:
        old = activate(system)
        before = rows(system)
        with system["control"].transaction() as tx:
            old_actions = {row["id"]: row for row in tx.scan(BUCKET_ACTIONS)}
        assert pr2_consumption(system)[0]["instance_id"] == old["instance_id"]
        # The owner pauses the Fleet (which also ends the runtime's activation hold) before any maintenance.
        fleet.pause()
        await_idle(system)
        document, evidence = maintenance_document(system, old)
        target_file = state(target, TARGET_FILE)
        provenance = (target_file.stat().st_ino, target_file.stat().st_mtime_ns, target_file.read_bytes())
        old_invocation, starts = unit.invocation, unit.starts
        # --check first: applicable, and nothing at all is written, started or put.
        checked = delivery.maintain(document, evidence, "restart", check=True)
        assert checked["applicable"] is True and checked["check"] is True and unit.starts == starts
        assert rows(system) == before and not (tmp_path / "control-runtime" / "artifacts.lock").exists()

        # ----- restart: exactly one graceful replacement of the recorded incumbent --------------------------
        signals = SignalLedger(monkeypatch)
        restarted = delivery.maintain(document, evidence, "restart", startup_seconds=60, poll_seconds=0.2)
        assert restarted["state"] == "started" and restarted["cached"] is False and restarted["pending"] is False
        assert unit.starts == starts + 1 and unit.invocation != old_invocation and signals.sent == []
        assert {argv[1] for argv in unit.calls} <= {"show", "start"}
        new = read(state(target, RECEIPT_FILE))
        assert new["instance_id"] != old["instance_id"] and new["pid"] != old["pid"]
        assert (target_file.stat().st_ino, target_file.stat().st_mtime_ns, target_file.read_bytes()) == provenance
        after_restart = rows(system)
        intent = after_restart["intent"]
        assert intent["stage"] == ACTIVE and intent["instance_id"] == old["instance_id"]
        assert [g["state"] for g in intent["generations"]] == ["started"]
        for name in ("release", "pointer", "queue"):
            assert after_restart[name] == before[name], name
        with pytest.raises(MigrationRefused) as unbound:
            pr2_consumption(system)          # the new generation is not a consumption claim yet
        assert unbound.value.field == "instance_binding"
        # A replay of the same document is cached and starts nothing.
        assert delivery.maintain(document, evidence, "restart")["cached"] is True and unit.starts == starts + 1

        # ----- arm: PRIMARY evidence, the one-job permit, the armed generation ------------------------------
        armed = delivery.maintain(document, evidence, "arm", canary_wait_seconds=10)
        assert armed["state"] == "armed" and armed["pending"] is True
        assert armed["reason_code"] == "maintenance_canary_pending"
        deadline = armed["deadline"]
        intent = rows(system)["intent"]
        assert intent["stage"] == AWAITING_CONSUMPTION and intent["candidate_instance_id"] == new["instance_id"]
        with pytest.raises(MigrationRefused) as awaiting:
            pr2_consumption(system)
        assert awaiting.value.field == "delivery_not_active"
        # LABELLED owner step: the unchanged owner-actions would now owe exactly this new-instance canary.
        action = owner_canary(system, new["instance_id"])
        job_id = action["job_id"]
        assert job_id == do.canary_job_id(action["id"]) and action["binding"]["instance_id"] == new["instance_id"]
        other = fixture_manifest("op-unrelated")
        fleet.enqueue("fixture", other, {"path": "docs/GOAL.md", "sha256": "b" * 64, "criterion": "fixture",
                                         "base_revision": "a" * 40, "bytes": 7}, [])
        fleet.enqueue("fixture", fixture_manifest(job_id), {"path": "docs/GOAL.md", "sha256": "b" * 64,
                                                            "criterion": "fixture", "base_revision": "a" * 40,
                                                            "bytes": 7}, [])
        system["launcher"].outcomes[job_id] = {"status": "accepted", "reason_code": "lead_accepted", "exit_code": 0,
                                               "calls": {"reserved": 1, "settled": 1}}
        dispatched = delivery.maintain(document, evidence, "arm", canary_wait_seconds=10)
        assert dispatched["state"] == "armed" and dispatched["pending"] is False and dispatched["deadline"] == deadline
        assert system["launcher"].launched == [job_id], "exactly the owner canary job ran"
        assert fleet.job(job_id)["status"] == "accepted" and fleet.job("op-unrelated")["status"] == "queued"
        assert fleet.maintenance_readiness()["owner_paused"] is True
        # A replayed arm never launches again.
        with pytest.raises(DeliveryRefused) as replayed:
            delivery.maintain(document, evidence, "arm", canary_wait_seconds=10)
        assert replayed.value.reason_code == "maintenance_already_used"
        assert system["launcher"].launched == [job_id]

        # ----- the owner completes its canary; bind consumes the new instance ---------------------------------
        owner_completes(system, action, job_id)
        bound = delivery.maintain(document, evidence, "bind")
        assert bound["state"] == "bound" and bound["pending"] is False
        consumed, startup, current = pr2_consumption(system)
        assert consumed["instance_id"] == new["instance_id"] == startup["instance_id"]
        intent = current["intent"]
        assert intent["stage"] == ACTIVE and intent["instance_id"] == new["instance_id"]
        assert current["descriptor_row"]["consumed"] is True
        assert current["descriptor_row"]["history"][-1]["instance_id"] == old["instance_id"]
        with system["control"].transaction() as tx:
            record = tx.get(BUCKET_ACTIONS, action["id"])
            for identity, row in old_actions.items():
                assert tx.get(BUCKET_ACTIONS, identity) == row, "the old owner canary action is unchanged"
        receipt = read(state(target, canary_receipt_file(system["plan"]["plan_id"])))
        request = TargetFiles.request(target, system["plan"]["plan_id"])
        incumbent = owner_qualified_canary(target, consumed["descriptor"], {"instance_id": new["instance_id"]},
                                           plan=system["plan"])
        hme.require_canary(consumed, incumbent, receipt, request, record, intent=intent,
                           started_at=startup["started_at"])
        for name in ("release", "pointer", "queue"):
            assert current[name] == before[name], name
        permit = fleet.maintenance_permit(intent["generations"][0]["id"])
        assert permit["state"] == "closed" and permit["close_reason"] == "maintenance_settled"
        assert delivery.maintain(document, evidence, "bind")["cached"] is True
        assert unit.starts == starts + 1 and signals.sent == []
        assert {key: current["target_row"][key] for key in MANAGED_TARGET_FIELDS} == {
            key: target[key] for key in MANAGED_TARGET_FIELDS}
    finally:
        finish(system)


def await_idle(system, timeout=30.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if system["host"].work(system["target"], require_paused=False)["state"] == "idle":
            return
        time.sleep(0.1)
    raise AssertionError("the incumbent never reported idle work")
