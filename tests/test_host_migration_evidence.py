"""Read-only managed `limited_active` receipt producer (INV-HOST-MIGRATION-001): PH4-6, 7, 8, 9 and 12.

Everything runs on fixture data: memory stores behind a read-only wrapper, a temporary `ZEUS_AIBOX_ROOT`
with labelled release and sealed-runtime fixtures, a fixture `/proc` read through the accepted
`HostFacts`, and a fake `systemctl show` / `journalctl` runner. No live host, store, unit, journal,
provider or model is touched. The fixture reproduces the live topology the spec describes. The
effective successor's revision (5aa analogue) owns launch and `current`. The consumed managed
descriptor has another payload revision (ec8 analogue). The entry runs the registered interpreter of a
third release. The journal lines are produced by the unchanged deploy/aibox launcher's own `emit`.
"""
from __future__ import annotations

import builtins
import copy
import fcntl
import hashlib
import importlib.util
import io
import json
import os
import shutil
import socket
import subprocess
import tempfile
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from test_host_migration import manifest

from codex_harness.adapters import host_migration as adapter
from codex_harness.adapters import host_migration_evidence as producer
from codex_harness.adapters.release_verifier import HostFacts
from codex_harness.adapters.store import MemoryStore
from codex_harness.application.host_delivery import (
    BUCKET_DESCRIPTORS,
    BUCKET_INTENTS,
    BUCKET_PLANS,
    BUCKET_TARGETS,
)
from codex_harness.application.host_migration import BUCKET, HostMigrations
from codex_harness.domain import host_migration as migration
from codex_harness.domain import host_migration_evidence as policy
from codex_harness.domain.host_delivery import (
    ACTIVE,
    DESCRIPTOR_SCHEMA,
    PLAN_SCHEMA,
    RECEIPT_SCHEMA,
    descriptor_digest,
    new_intent,
    plan_digest,
    validate_plan,
    validate_targets,
)
from codex_harness.domain.managed_runtime import blob_id, new_manifest
from codex_harness.domain.model import digest
from codex_harness.domain.owner_actions import (
    DELIVERY_CANARY,
    action_id,
    canary_receipt,
    canary_request,
)

pytestmark = pytest.mark.skipif(os.name != "posix", reason=(
    "INV-HOST-MIGRATION-001 Linux producer: systemd unit, journald launch lines, /proc identities and the "
    "deploy/aibox launcher are POSIX-only; there is no non-POSIX managed limited_active observation"))

ROOT = Path(__file__).resolve().parents[1]
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


def launcher():
    """deploy/aibox's launcher module, unchanged: its `emit` writes the lines journald stores."""
    spec = importlib.util.spec_from_file_location("zeus_aibox_service_evidence",
                                                  ROOT / "deploy" / "aibox" / "zeus_aibox_service.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


LAUNCHER = launcher()


def receipt(check: str, subject: str) -> dict:
    return {"schema": migration.EVIDENCE_SCHEMA, "check": check, "subject": subject, "exit_code": 0, "ok": True,
            "result_sha256": "a" * 64}


def journal(event: dict, *, pid=SUP_PID, invocation=INVOCATION, boot=BOOT_HEX, mono=LAUNCH_MONO,
            real=LAUNCH_REAL, stream="aab17a6192c242018273c435b78ae485", start=144755) -> list:
    """One launcher document exactly as journald stores it: one entry per emitted line."""
    out = io.StringIO()
    LAUNCHER.emit(event, out)
    return [{"MESSAGE": line, "_PID": str(pid), "_STREAM_ID": stream, "_BOOT_ID": boot,
             "_SYSTEMD_INVOCATION_ID": invocation, "_SYSTEMD_UNIT": UNIT, "_TRANSPORT": "stdout",
             "__CURSOR": "s=088ada45;i=" + format(start + index, "x") + ";b=" + boot,
             "__MONOTONIC_TIMESTAMP": str(mono), "__REALTIME_TIMESTAMP": str(real), "__SEQNUM": str(start + index)}
            for index, line in enumerate(out.getvalue().splitlines())]


def launch_event(**overrides) -> dict:
    return {"event": "launch", "role": "managed-fleet", "revision": ACT_REV, "migration_id": MID, **overrides}


class ReadOnly:
    """A store view whose transactions can read and never write; it counts what it was asked."""

    def __init__(self, store):
        self.store, self.transactions, self.fail, self.puts = store, 0, None, []

    @contextmanager
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
    """`systemctl show` and `journalctl` answers; anything else is an unexpected command."""

    def __init__(self, world):
        self.world, self.calls, self.shows, self.on_recheck = world, [], 0, None

    def __call__(self, argv, timeout=None, **kwargs):
        self.calls.append(list(argv))
        if argv[:2] == ["systemctl", "show"]:
            self.shows += 1
            if self.shows == 2 and self.on_recheck is not None:
                self.on_recheck()
            text = "".join(key + "=" + value + "\n" for key, value in self.world.unit.items())
            return subprocess.CompletedProcess(argv, self.world.show_rc, text, "")
        if argv[:1] == ["journalctl"]:
            text = "".join(json.dumps(entry) + "\n" for entry in self.world.journal)
            return subprocess.CompletedProcess(argv, self.world.journal_rc, text, "")
        raise AssertionError("unexpected command")


class Clock:
    def __init__(self):
        self.ticks = 0

    def __call__(self) -> str:
        self.ticks += 1
        return (datetime(2026, 9, 28, 11, 30, tzinfo=timezone.utc) + timedelta(milliseconds=self.ticks)).isoformat()


def stat_line(pid: int, ppid: int, ticks: int, name: str = "python") -> str:
    fields = ["S", str(ppid), str(pid), str(pid), "0", "-1", "4194560"] + ["0"] * 12 + [str(ticks), "92794880", "11498"]
    return str(pid) + " (" + name + ") " + " ".join(fields) + "\n"


class World:
    """One consistent host: coordinator in restored_paused with a successor, the launcher files, the
    managed state directory, the delivery lane, the owner-action record, `/proc` and the unit."""

    def __init__(self, tmp: Path):
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
        self.target = validate_targets({"schema": "urn:zeus:host-delivery-targets:1", "targets": [{
            "target_id": TARGET, "kind": "managed_fleet_systemd", "root": str(self.managed),
            "state_dir": str(self.state), "service": "zeus-aibox-managed-fleet", "source": str(self.root / "repo"),
            "python": str(self.releases / INTENT_REV / ".venv" / "bin" / "python"),
            "environment_lock": hashlib.sha256(LOCK).hexdigest()}]})["targets"][0]
        self.descriptor = {"schema": DESCRIPTOR_SCHEMA, "target_id": TARGET,
                           "root": str(self.managed / "runtimes" / PAYLOAD), "revision": PAYLOAD,
                           "worker_image": IMAGE, "profile_digest": PROFILE, "predecessor": PREDECESSOR}
        self.descriptor_sha256 = descriptor_digest(self.descriptor)
        self._coordinator()
        self._delivery()
        self._host()

    # --- builders -------------------------------------------------------------------------------
    def _seal(self):
        final = self.managed / "runtimes" / PAYLOAD
        files = {"pyproject.toml": b"[project]\nname = 'fixture'\n",
                 "src/codex_harness/__init__.py": b"# labelled sealed runtime fixture\n", "uv.lock": LOCK}
        for relative, data in files.items():
            (final / relative).parent.mkdir(parents=True, exist_ok=True)
            (final / relative).write_bytes(data)
        sealed, listing = new_manifest(PAYLOAD, "b" * 40, [(path, blob_id(data)) for path, data in files.items()],
                                       hashlib.sha256(LOCK).hexdigest())
        (final / "runtime-files.json").write_text(json.dumps(listing))
        (final / "runtime.json").write_text(json.dumps(sealed))

    def _coordinator(self):
        self.coordinator = MemoryStore()
        coordinator = HostMigrations(self.coordinator)
        self.manifest_sha256 = coordinator.plan(manifest())["manifest_sha256"]
        with self.coordinator.transaction() as tx:
            row = tx.get(BUCKET, MID)
            row["state"] = migration.RESTORED_PAUSED
            tx.put(BUCKET, MID, row)
        intent_id = coordinator.intend_activation({
            "schema": migration.INTENT_SCHEMA, "migration_id": MID, "host_id": HOST_ID,
            "release_revision": INTENT_REV, "image": IMAGE, "profile_sha256": PROFILE, "actor": "owner",
            "at": "2026-09-25T06:00:00Z"})["intent_id"]
        self.effective_id = coordinator.record_successor({
            "schema": migration.SUCCESSOR_SCHEMA, "migration_id": MID, "host_id": HOST_ID,
            "predecessor_id": intent_id, "release_revision": ACT_REV, "image": IMAGE, "profile_sha256": PROFILE,
            "environment_lock": "f" * 64, "reason_code": "bootstrap-recovery",
            "evidence": {"release_identity": receipt(migration.OBSERVATION, "revision=" + ACT_REV),
                         "worker_compatibility": receipt(migration.OBSERVATION, "image=" + IMAGE),
                         "admission_drained": receipt(migration.OBSERVATION, "fleet=paused-settled")},
            "actor": "owner", "at": "2026-09-26T14:09:55Z"})["successor_id"]
        self.activation_document = coordinator.activation_document(MID)
        (self.control / "host-activation.json").write_bytes(adapter._document_bytes(self.activation_document))

    def _delivery(self):
        plan = validate_plan({
            "schema": PLAN_SCHEMA, "plan_id": PLAN, "release_id": "7" * 64, "revision": PAYLOAD, "tree": "f" * 40,
            "policy_hash": "a" * 64, "repository": "github:trevi00/zeus", "required_checks": ["test"],
            "target_id": TARGET, "expected_descriptor": PREDECESSOR,
            "target_descriptor": {"revision": PAYLOAD, "worker_image": "unchanged", "profile_digest": "unchanged"},
            "canary_check_id": "fleet_worker_operation", "ci_timeout_seconds": 3600,
            "consumption_timeout_seconds": 900})
        self.plan, self.plan_sha256 = plan, plan_digest(plan)
        binding = {"plan_id": PLAN, "plan_sha256": self.plan_sha256, "target_id": TARGET,
                   "descriptor_sha256": self.descriptor_sha256, "instance_id": INSTANCE}
        self.action_id = action_id(DELIVERY_CANARY, binding)
        outcome = {"state": "accepted", "reason_code": "canary_accepted",
                   "evidence": {"job_id": "canary-" + self.action_id[:24], "operation_id": "canary-" + self.action_id[:24],
                                "decision_id": "9ba9669e-59f6-4e8a-a2e0-a1deded4d5fd",
                                "execution_ref": "sha256:" + "cb" * 32}}
        self.record = {"id": self.action_id, "kind": DELIVERY_CANARY, "state": "completed", "binding": binding,
                       "binding_sha256": digest(binding), "policy_id": "aibox-owner", "policy_sha256": "ab" * 32,
                       "subject": {"intent_id": "intent"}, "reason_code": "canary_accepted",
                       "job_id": "canary-" + self.action_id[:24], "outcome": outcome, "version": 3,
                       "created_at": "2026-09-27T20:35:08+00:00", "updated_at": RECORDED_AT, "history": []}
        self.control_store = MemoryStore()
        with self.control_store.transaction() as tx:
            tx.put("owner_actions", self.action_id, self.record)
        canary = canary_receipt(self.record, outcome, RECORDED_AT)
        intent = new_intent(plan, self.plan_sha256, "2026-09-27T20:30:00+00:00")
        intent.update(stage=ACTIVE, previous_stage="awaiting_consumption", descriptor=self.descriptor,
                      descriptor_sha256=self.descriptor_sha256, previous_descriptor_sha256=PREDECESSOR,
                      previous_instance_id=PREVIOUS, candidate_instance_id=INSTANCE, instance_id=INSTANCE,
                      canary={"passed": True, "evidence": canary["evidence"], "reason_code": None,
                              "check_id": "fleet_worker_operation"})
        self.delivery = MemoryStore()
        with self.delivery.transaction() as tx:
            tx.put(BUCKET_TARGETS, TARGET, {"id": TARGET, **self.target, "registered_at": "2026-09-26T10:00:00+00:00",
                                            "updated_at": "2026-09-26T10:00:00+00:00"})
            tx.put(BUCKET_PLANS, PLAN, {"id": PLAN, "plan_id": PLAN, "plan": plan, "plan_sha256": self.plan_sha256,
                                        "pin": {"revision": "1" * 40, "path": "deploy/aibox/owner-plans/p.json",
                                                "sha256": "2" * 64}, "target_id": TARGET})
            tx.put(BUCKET_INTENTS, PLAN, intent)
            tx.put(BUCKET_INTENTS, OTHER_PLAN, {"id": OTHER_PLAN, "plan_id": OTHER_PLAN, "target_id": TARGET,
                                                "stage": ACTIVE})
            tx.put(BUCKET_DESCRIPTORS, TARGET, {
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
            "schema": RECEIPT_SCHEMA, "target_id": TARGET, "instance_id": INSTANCE, "pid": ENTRY_PID,
            "started_at": STARTED_AT, "runtime_root": self.descriptor["root"],
            "module_root": self.descriptor["root"] + "/src/codex_harness", "descriptor_sha256": self.descriptor_sha256,
            "revision": PAYLOAD, "worker_image": IMAGE, "profile_digest": PROFILE})
        self.write(self.state / ("owner-canary-receipt." + PLAN + ".json"), canary)
        self.write(self.state / ("owner-canary-request." + PLAN + ".json"),
                   canary_request({"id": "0" * 64}, plan, self.plan_sha256, "2026-09-27T20:35:08+00:00"))

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
        # The launcher's own lines, and a Fleet runner document from the child that must be ignored.
        self.journal = journal(launch_event()) + [{
            "MESSAGE": json.dumps({"event": "launch", "job": "fleet-job"}), "_PID": str(ENTRY_PID),
            "_STREAM_ID": "c" * 32, "_BOOT_ID": BOOT_HEX, "_SYSTEMD_INVOCATION_ID": INVOCATION,
            "_SYSTEMD_UNIT": UNIT, "_TRANSPORT": "stdout", "__CURSOR": "s=1;i=2",
            "__MONOTONIC_TIMESTAMP": str(LAUNCH_MONO + 900_000), "__REALTIME_TIMESTAMP": str(LAUNCH_REAL + 900_000)}]
        self.show_rc = self.journal_rc = 0
        self.runner = Runner(self)

    def supervisor_argv(self) -> list:
        return [str((self.releases / ACT_REV).resolve() / ".venv" / "bin" / "python"), "-m", MODULE, "supervise",
                "--state-dir", str(self.state)]

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

    # --- the producer ----------------------------------------------------------------------------
    def request(self, **overrides) -> dict:
        return {"migration_id": MID, "expected_id": self.effective_id, "target_id": TARGET, "plan_id": PLAN,
                "actor": "claude-ph4", "root": str(self.root), "config_file": None, **overrides}

    def ports(self) -> producer.Ports:
        self.stores = {"coordinator": ReadOnly(self.coordinator), "control": ReadOnly(self.control_store),
                       "delivery": ReadOnly(self.delivery)}
        return producer.Ports(coordinator=self.stores["coordinator"], control=self.stores["control"],
                              delivery=lambda control: self.stores["delivery"],
                              host=producer.HostReader(runner=self.runner, facts=HostFacts(
                                  proc=self.proc, cgroup_root=self.proc / "no-cgroup"), clk_tck=100),
                              clock=Clock())

    def observe(self, **overrides) -> dict:
        return producer.observe(self.request(**overrides), self.ports())


@pytest.fixture
def world(tmp_path):
    return World(tmp_path)


def refused(result: dict, code: str, detail: str | None = None) -> dict:
    """A recorded failure: fixed code, failed receipts only, no draft, a valid observation."""
    observation = result["observation"]
    assert observation["ok"] is False and observation["reason_code"] == code
    assert result["diagnostic"]["reason_code"] == code
    if detail is not None:
        assert result["diagnostic"]["detail"] == detail
    assert result["transition_draft"] is None
    assert all(r["exit_code"] == 1 and r["ok"] is False and r["result_sha256"] == result["result_sha256"]
               for r in result["evidence"].values())
    assert policy.validate_observation(observation) == observation
    assert policy.observation_digest(observation) == result["result_sha256"]
    return observation


# ----- success: host launch authority apart from the consumed managed payload (PH4-2 shape) ------------
def test_genuine_launch_and_managed_consumption_produce_three_bound_receipts_and_draft(world):
    result = world.observe()
    observation = result["observation"]
    assert observation["ok"] is True and observation["reason_code"] is None and result["diagnostic"] is None
    assert all(observation["checks"].values()) and set(observation["checks"]) == set(policy.CHECKS)
    assert list(observation) == list(policy.OBSERVATION_FIELDS)
    assert observation["activation"] == {"id": world.effective_id, "release_revision": ACT_REV, "image": IMAGE,
                                         "profile_sha256": PROFILE,
                                         "document_sha256": digest(world.activation_document)}
    lineage = observation["lineage"]
    assert lineage == {"owner": "managed", "descriptor": world.descriptor, "instance_id": INSTANCE, "plan_id": PLAN}
    assert lineage["descriptor"]["revision"] == PAYLOAD != ACT_REV  # the payload is never relabelled 5aa
    evidence = result["evidence"]
    assert (evidence["host_activation"]["check"], evidence["host_activation"]["subject"]) == (
        "host-activation", world.effective_id)
    assert (evidence["service_consumption"]["check"], evidence["service_consumption"]["subject"]) == (
        "service-startup", "descriptor=" + world.descriptor_sha256)
    assert (evidence["canary_admission"]["check"], evidence["canary_admission"]["subject"]) == (
        "observation", "canary=" + PLAN + ":instance=" + INSTANCE)
    assert all(r["exit_code"] == 0 and r["ok"] is True and r["result_sha256"] == result["result_sha256"]
               for r in evidence.values())
    draft = result["transition_draft"]
    assert migration.validate_transition(draft) == draft
    assert (draft["from"], draft["to"], draft["host"], draft["actor"], draft["at"]) == (
        migration.RESTORED_PAUSED, migration.LIMITED_ACTIVE, "aibox", "claude-ph4", observation["observed_to"])
    assert draft["identity"] == {"config_sha256": hashlib.sha256(world.config.read_bytes()).hexdigest(),
                                 "commit": ACT_REV, "image": IMAGE, "profile_sha256": PROFILE}
    assert draft["lineage"] == lineage and draft["manifest_sha256"] == world.manifest_sha256
    assert draft["evidence"] == {gate: [receipt] for gate, receipt in evidence.items()}
    assert migration.managed_consumption_subject(lineage) == evidence["service_consumption"]["subject"]
    assert migration.managed_canary_subject(lineage) == evidence["canary_admission"]["subject"]
    # Only the two read commands ran: one capture, then the recheck (which reads the unit, not the journal).
    assert [call[:2] for call in world.runner.calls] == [["systemctl", "show"], ["journalctl", "--no-pager"],
                                                         ["systemctl", "show"]]


def test_consumption_uses_the_previous_instance_and_binds_the_current_one_separately(world):
    """`expected_instance` is the delivery's PREVIOUS instance (INV-HOST-DELIVERY-001): the current
    instance passes, and every current binding (intent, descriptor row, live entry) is compared apart."""
    assert world.observe()["observation"]["ok"] is True
    world.row(world.delivery, BUCKET_INTENTS, PLAN, previous_instance_id=INSTANCE)
    refused(world.observe(), policy.CONSUMPTION, "receipt_stale_instance")


# ----- PH4-6: the owner canary ------------------------------------------------------------------------
RECEIPT_NAME = "owner-canary-receipt." + PLAN + ".json"
REQUEST_NAME = "owner-canary-request." + PLAN + ".json"


def _move_receipt_to_other_plan(world):
    path = world.state / RECEIPT_NAME
    path.rename(world.state / ("owner-canary-receipt." + OTHER_PLAN + ".json"))
    (world.state / REQUEST_NAME).unlink()


def _evidence(world, **changes):
    document = world.read(world.state / RECEIPT_NAME)
    world.edit(RECEIPT_NAME, evidence={**document["evidence"], **changes})


CANARY_CASES = {
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
    "delivery_consumed_other_evidence": (lambda w: w.row(w.delivery, BUCKET_INTENTS, PLAN, canary={
        "passed": True, "evidence": {"action_id": "1" * 64}, "reason_code": None,
        "check_id": "fleet_worker_operation"}), "delivery_canary"),
    "receipt_before_startup": (lambda w: w.edit(RECEIPT_NAME, recorded_at="2026-09-27T21:00:00+00:00"),
                               "canary_before_startup"),
    "request_other_plan_digest": (lambda w: w.edit(REQUEST_NAME, plan_sha256="0" * 64), "canary_request"),
    "receipt_extra_key": (lambda w: w.edit(RECEIPT_NAME, note="x"), "canary_receipt_shape"),
}


@pytest.mark.parametrize("case", sorted(CANARY_CASES))
def test_canary_other_plan_target_instance_descriptor_null_false_pending_or_missing_refuses(world, case):
    mutate, detail = CANARY_CASES[case]
    mutate(world)
    observation = refused(world.observe(), policy.CANARY, detail)
    checks = observation["checks"]
    assert checks["consumption"] and checks["process_bound"] and not checks["canary_bound"]
    # The consumption held, so the lineage is known and the failed receipts still name their subjects.
    assert observation["lineage"]["instance_id"] == INSTANCE


def test_incumbent_owner_canary_is_weaker_and_unchanged(world):
    """`owner_qualified_canary` still passes a null instance and a string `passed`. The producer adds the
    stricter rule; the incumbent check itself is not changed."""
    from codex_harness.adapters.host_delivery import owner_qualified_canary

    world.edit(RECEIPT_NAME, instance_id=None, passed="yes")
    weak = owner_qualified_canary(world.target, world.descriptor, {"instance_id": INSTANCE}, plan=world.plan)
    assert weak["passed"] is True
    refused(world.observe(), policy.CANARY, "canary_not_passed")


# ----- PH4-7: the existing consumption controls --------------------------------------------------------
def _seal_tampered(world):
    path = world.managed / "runtimes" / PAYLOAD / "src" / "codex_harness" / "__init__.py"
    path.chmod(0o644)
    path.write_bytes(b"# edited after sealing\n")


def _descriptor_drift(world):
    world.edit("descriptor.json", worker_image="sha256:" + "8" * 64)


CONSUMPTION_CASES = {
    "stale_prior_instance": (lambda w: w.edit("startup-receipt.json", instance_id=PREVIOUS), "receipt_stale_instance"),
    "foreign_runtime_root": (lambda w: w.edit("startup-receipt.json", runtime_root=str(w.releases / ACT_REV),
                                              module_root=str(w.releases / ACT_REV / "src" / "codex_harness")),
                             "receipt_runtime_root_mismatch"),
    "foreign_module_root": (lambda w: w.edit("startup-receipt.json", module_root=str(w.root / "repo" / "src")),
                            "receipt_module_root_foreign"),
    "revision_mismatch": (lambda w: w.edit("startup-receipt.json", revision=ACT_REV), "receipt_revision_mismatch"),
    "image_mismatch": (lambda w: w.edit("startup-receipt.json", worker_image="sha256:" + "8" * 64),
                       "receipt_worker_image_mismatch"),
    "profile_mismatch": (lambda w: w.edit("startup-receipt.json", profile_digest="0" * 64),
                         "receipt_profile_digest_mismatch"),
    "digest_mismatch": (lambda w: w.edit("startup-receipt.json", descriptor_sha256="0" * 64),
                        "receipt_descriptor_sha256_mismatch"),
    "descriptor_identity_drift": (_descriptor_drift, "descriptor_identity"),
    "descriptor_relabelled_to_launcher_revision": (lambda w: w.edit("descriptor.json", revision=ACT_REV),
                                                   "runtime_path_foreign"),
    "sealed_runtime_tampered": (_seal_tampered, "runtime_content_mismatch"),
    "environment_unqualified": (lambda w: w.row(w.delivery, BUCKET_TARGETS, TARGET, environment_lock="0" * 64),
                                "environment_unqualified"),
    "delivery_not_active": (lambda w: w.row(w.delivery, BUCKET_INTENTS, PLAN, stage="awaiting_consumption"),
                            "delivery_not_active"),
    "delivery_bound_other_instance": (lambda w: w.row(w.delivery, BUCKET_DESCRIPTORS, TARGET, instance_id=PREVIOUS),
                                      "instance_binding"),
    "delivery_rolled_back": (lambda w: w.row(w.delivery, BUCKET_DESCRIPTORS, TARGET, rolled_back=True),
                             "instance_binding"),
    "delivery_in_flight": (lambda w: w.row(w.delivery, BUCKET_INTENTS, OTHER_PLAN, stage="switching"),
                           "delivery_in_flight"),
    "plan_digest_mismatch": (lambda w: w.row(w.delivery, BUCKET_PLANS, PLAN, plan_sha256="0" * 64), "plan_binding"),
    "target_not_the_managed_unit": (lambda w: w.row(w.delivery, BUCKET_TARGETS, TARGET, kind="managed_fleet"),
                                    "target_binding"),
}


@pytest.mark.parametrize("case", sorted(CONSUMPTION_CASES))
def test_consumption_stale_foreign_revision_image_profile_digest_mismatch_refuses(world, case):
    mutate, detail = CONSUMPTION_CASES[case]
    mutate(world)
    observation = refused(world.observe(), policy.CONSUMPTION, detail)
    assert observation["checks"]["launch_bound"] and not observation["checks"]["consumption"]
    assert observation["lineage"] is None
    assert result_subjects_unknown(observation)


def result_subjects_unknown(observation) -> bool:
    receipts = policy.observation_receipts(observation, "0" * 64, "e" * 64)
    return receipts["service_consumption"]["subject"] is None and receipts["canary_admission"]["subject"] is None


# ----- PH4-8: launch provenance and the live process chain ---------------------------------------------
def _bootstrap_receipt(world):
    """The retired bootstrap Fleet's receipt: the release checkout, `revision=5aa`, its own pid."""
    world.edit("startup-receipt.json", runtime_root=str(world.releases / ACT_REV),
               module_root=str(world.releases / ACT_REV / "src" / "codex_harness"), revision=ACT_REV,
               instance_id="d89f34e0" + "0" * 24, pid=4242)


def _entry_stopped(world):
    shutil.rmtree(world.proc / str(ENTRY_PID))


def _entry_pid_reused(world):
    # Same pid, same argv and parent, but started long after the receipt it would claim.
    world.process(ENTRY_PID, SUP_PID, ENTRY_TICKS + 100_000, world.read_cmdline(ENTRY_PID))


def _dry_run_only(world):
    # The only launch event of the invocation came from another process (a dry run), not the main pid.
    world.journal = journal(launch_event(), pid=9999)


def _not_execd(world):
    # The main process is still the launcher: the event exists, but nothing was exec'd.
    world.process(SUP_PID, 1, SUP_TICKS, ["/usr/bin/python3", str(ROOT / "deploy" / "aibox" / "zeus_aibox_service.py"),
                                          "launch", "--role", "managed-fleet"])


def _two_launches(world):
    world.journal = journal(launch_event()) + journal(launch_event(), start=144800)


PROCESS_CASES = {
    "retired_bootstrap_receipt": (_bootstrap_receipt, policy.CONSUMPTION, "receipt_runtime_root_mismatch"),
    "stopped_entry_pid": (_entry_stopped, policy.PROCESS, "entry_absent"),
    "reused_entry_pid": (_entry_pid_reused, policy.PROCESS, "entry_after_startup"),
    "entry_not_supervisor_child": (lambda w: w.process(ENTRY_PID, 1, ENTRY_TICKS, w.read_cmdline(ENTRY_PID)),
                                   policy.PROCESS, "entry_parent"),
    "entry_other_cgroup": (lambda w: w.process(ENTRY_PID, SUP_PID, ENTRY_TICKS, w.read_cmdline(ENTRY_PID),
                                               "/user.slice/session.scope"), policy.PROCESS, "entry_cgroup"),
    "entry_other_workload": (lambda w: w.process(ENTRY_PID, SUP_PID, ENTRY_TICKS,
                                                 w.read_cmdline(ENTRY_PID)[:-1] + ["fixture"]),
                             policy.PROCESS, "entry_argv"),
    "supervisor_gone": (lambda w: shutil.rmtree(w.proc / str(SUP_PID)), policy.PROCESS, "supervisor_absent"),
    "supervisor_pid_reused": (lambda w: w.process(SUP_PID, 1, SUP_TICKS + 1_000, w.supervisor_argv()),
                              policy.PROCESS, "supervisor_start"),
    "supervisor_other_cgroup": (lambda w: w.process(SUP_PID, 1, SUP_TICKS, w.supervisor_argv(), "/other.scope"),
                                policy.PROCESS, "supervisor_cgroup"),
    "supervisor_other_release": (lambda w: w.process(SUP_PID, 1, SUP_TICKS, [
        str(w.releases / INTENT_REV / ".venv" / "bin" / "python"), *w.supervisor_argv()[1:]]),
        policy.PROCESS, "supervisor_argv"),
    "launcher_not_execd": (_not_execd, policy.PROCESS, "supervisor_argv"),
    "unit_not_running": (lambda w: w.unit.update(SubState="stop-sigterm"), policy.PROCESS, "unit_not_running"),
    "supervisor_never_launched_this_invocation": (lambda w: w.supervisor_journal([]), policy.PROCESS,
                                                  "supervisor_launch_missing"),
    "supervisor_launched_other_descriptor": (lambda w: w.supervisor_journal([{
        "event": "launch", "descriptor_sha256": PREDECESSOR, "workload": "fleet", "invocation_id": INVOCATION}]),
        policy.PROCESS, "supervisor_descriptor"),
    "supervisor_refused_this_invocation": (lambda w: w.supervisor_journal([
        {"event": "refused", "reason_code": "descriptor_changed", "invocation_id": INVOCATION},
        {"event": "launch", "descriptor_sha256": w.descriptor_sha256, "workload": "fleet",
         "invocation_id": INVOCATION}]), policy.PROCESS, "supervisor_refused"),
    "wrong_boot": (lambda w: setattr(w, "journal", journal(launch_event(), boot="0" * 32)),
                   policy.LAUNCH, "launch_boot"),
    "wrong_invocation": (lambda w: setattr(w, "journal", journal(launch_event(), invocation=OLD_INVOCATION)),
                         policy.LAUNCH, "launch_invocation"),
    "no_launch_in_invocation": (lambda w: setattr(w, "journal", []), policy.LAUNCH, "launch_missing"),
    "dry_run_launch_only": (_dry_run_only, policy.LAUNCH, "launch_missing"),
    "wrong_launch_revision": (lambda w: setattr(w, "journal", journal(launch_event(revision=INTENT_REV))),
                              policy.LAUNCH, "launch_revision"),
    "wrong_launch_migration": (lambda w: setattr(w, "journal", journal(launch_event(migration_id="other"))),
                               policy.LAUNCH, "launch_migration"),
    "wrong_launch_role": (lambda w: setattr(w, "journal", journal(launch_event(role="fleet"))),
                          policy.LAUNCH, "launch_role"),
    "launch_refused": (lambda w: setattr(w, "journal", journal({"event": "launch_refused", "role": "managed-fleet",
                                                                "reason": "host_fenced"})),
                       policy.LAUNCH, "launch_refused"),
    "two_launches": (_two_launches, policy.LAUNCH, "launch_ambiguous"),
    "launch_before_invocation": (lambda w: setattr(w, "journal", journal(launch_event(), mono=EXEC_MAIN - 1)),
                                 policy.LAUNCH, "launch_before_invocation"),
}


@pytest.mark.parametrize("case", sorted(PROCESS_CASES))
def test_retired_receipt_stopped_or_reused_pid_wrong_boot_invocation_dry_run_or_revision_refuses(world, case):
    mutate, code, detail = PROCESS_CASES[case]
    mutate(world)
    observation = refused(world.observe(), code, detail)
    assert not observation["checks"]["process_bound"]


# ----- PH4-9: the activation document, current, fence, unreadable sources and changes ------------------
def _activation(world, **changes):
    world.write(world.control / "host-activation.json", {**world.activation_document, **changes})


def _current(world, revision):
    (world.releases / "current").unlink()
    os.symlink(revision, world.releases / "current")


DOCUMENT_CASES = {
    "state_limited_active": (lambda w: _activation(w, state="limited_active"), "activation_file"),
    "superseded_intent": (lambda w: _activation(w, intent_id="0" * 64), "activation_file"),
    "extra_key": (lambda w: _activation(w, note="relabelled"), "activation_file"),
    "revision_only_equal": (lambda w: w.write(w.control / "host-activation.json", {
        "schema": migration.ACTIVATION_SCHEMA, "release_revision": ACT_REV, "state": "restored_paused"}),
        "activation_file"),
    "current_other_revision": (lambda w: _current(w, INTENT_REV), "current"),
    "current_missing": (lambda w: (w.releases / "current").unlink(), "current"),
    "host_fenced": (lambda w: w.write(w.control / "host-fence.json", {"migration_id": MID}), "host_fenced"),
    "coordinator_not_restored_paused": (lambda w: w.row(w.coordinator, BUCKET, MID, state="limited_active"),
                                        "migration_state"),
}


@pytest.mark.parametrize("case", sorted(DOCUMENT_CASES))
def test_activation_file_must_equal_the_derived_receipt_and_current_and_no_fence(world, case):
    mutate, detail = DOCUMENT_CASES[case]
    mutate(world)
    refused(world.observe(), policy.DOCUMENT, detail)
    assert world.runner.calls == []  # refused before the unit or journal was read


def test_activation_file_equality_is_as_an_object_not_as_bytes(world):
    (world.control / "host-activation.json").write_text(json.dumps(world.activation_document, separators=(",", ":")))
    assert world.observe()["observation"]["ok"] is True


def test_expected_id_must_be_the_effective_head(world):
    refused(world.observe(expected_id="0" * 64), policy.DOCUMENT, "activation_head_moved")


UNREADABLE_CASES = {
    "activation_file_missing": (lambda w: (w.control / "host-activation.json").unlink(), "activation_file"),
    "activation_file_not_json": (lambda w: (w.control / "host-activation.json").write_text("{"), "activation_file"),
    "config_missing": (lambda w: w.config.unlink(), "config"),
    "unit_unreadable": (lambda w: setattr(w, "show_rc", 1), "unit"),
    "journal_unreadable": (lambda w: setattr(w, "journal_rc", 1), "journal"),
    "boot_unreadable": (lambda w: (w.proc / "sys" / "kernel" / "random" / "boot_id").unlink(), "boot"),
    "supervisor_stat_garbage": (lambda w: (w.proc / str(SUP_PID) / "stat").write_text("garbage"), "supervisor"),
    "supervisor_journal_missing": (lambda w: (w.state / "supervisor-journal.jsonl").unlink(), "supervisor_journal"),
    "descriptor_missing": (lambda w: (w.state / "descriptor.json").unlink(), "descriptor"),
    "startup_not_json": (lambda w: (w.state / "startup-receipt.json").write_text("{"), "startup"),
    "delivery_row_missing": (lambda w: w.delivery.data.pop((BUCKET_DESCRIPTORS, TARGET)), "delivery_descriptor"),
}


@pytest.mark.parametrize("case", sorted(UNREADABLE_CASES))
def test_unreadable_source_refuses_as_unavailable(world, case):
    mutate, detail = UNREADABLE_CASES[case]
    mutate(world)
    refused(world.observe(), policy.UNAVAILABLE, detail)


@pytest.mark.parametrize("store,detail", [("coordinator", "migration"), ("delivery", "delivery"),
                                          ("control", "canary_record")])
def test_unavailable_store_refuses_without_error_text(world, store, detail):
    ports = world.ports()
    world.stores[store].fail = RuntimeError("connection to postgresql://zeus:hunter2@db/zeus failed")
    result = producer.observe(world.request(), ports)
    refused(result, policy.UNAVAILABLE, detail)
    assert "hunter2" not in json.dumps(result)


def _successor_recorded(world):
    with world.coordinator.transaction() as tx:
        row = tx.get(BUCKET, MID)
        row["history"].append({"event": "activation_successor", "successor_id": "0" * 64})
        tx.put(BUCKET, MID, row)


def _restarted_entry(world):
    world.process(ENTRY_PID, SUP_PID, ENTRY_TICKS + 5, world.read_cmdline(ENTRY_PID))


CHANGE_CASES = {
    "unit_restarted": (lambda w: w.unit.update(InvocationID="f" * 32), "unit"),
    "startup_rewritten": (lambda w: w.edit("startup-receipt.json", instance_id="f" * 32), "startup"),
    "descriptor_switched": (lambda w: w.edit("descriptor.json", predecessor="0" * 64), "descriptor"),
    "coordinator_moved": (_successor_recorded, "migration"),
    "activation_file_rewritten": (lambda w: _activation(w, state="limited_active"), "activation_file"),
    "current_switched": (lambda w: _current(w, INTENT_REV), "activation_file"),
    "entry_restarted": (_restarted_entry, "entry"),
    "delivery_row_updated": (lambda w: w.row(w.delivery, BUCKET_DESCRIPTORS, TARGET, updated_at="later"), "delivery"),
    "canary_record_updated": (lambda w: w.row(w.control_store, "owner_actions", w.action_id, version=4),
                              "canary_record"),
    "canary_receipt_rewritten": (lambda w: w.edit(RECEIPT_NAME, recorded_at=RECORDED_AT.replace("43.4", "44.4")),
                                 "canary_receipt"),
    "config_changed": (lambda w: w.config.write_text("ZEUS_AIBOX_ROOT=elsewhere\n"), "config"),
    "supervisor_relaunched": (lambda w: w.supervisor_journal([{
        "event": "launch", "descriptor_sha256": w.descriptor_sha256, "workload": "fleet", "invocation_id": INVOCATION},
        {"event": "launch", "descriptor_sha256": w.descriptor_sha256, "workload": "fleet",
         "invocation_id": INVOCATION}]), "supervisor_journal"),
}


@pytest.mark.parametrize("case", sorted(CHANGE_CASES))
def test_any_identity_change_during_capture_refuses_changed(world, case):
    mutate, detail = CHANGE_CASES[case]
    world.runner.on_recheck = lambda: mutate(world)
    observation = refused(world.observe(), policy.CHANGED, detail)
    assert [name for name, value in observation["checks"].items() if not value] == ["stable_capture"]
    assert all(entry is not None for entry in observation["sources"].values())


# ----- PH4-12: read-only instrumentation, digests and no leakage ---------------------------------------
@contextmanager
def no_effects(monkeypatch, attempts: list):
    """Every write, lock, process, signal and network primitive records the attempt and raises."""
    real_open, real_os_open = builtins.open, os.open
    write_flags = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND

    def forbid(name):
        def refused_effect(*args, **kwargs):
            attempts.append(name)
            raise AssertionError("side effect: " + name)
        return refused_effect

    def guarded_open(file, mode="r", *args, **kwargs):
        if any(flag in mode for flag in "wax+"):
            return forbid("open:" + mode)()
        return real_open(file, mode, *args, **kwargs)

    def guarded_os_open(path, flags, *args, **kwargs):
        if flags & write_flags:
            return forbid("os.open")()
        return real_os_open(path, flags, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(builtins, "open", guarded_open)
        patch.setattr(io, "open", guarded_open)
        patch.setattr(os, "open", guarded_os_open)
        for name in ("replace", "rename", "remove", "unlink", "rmdir", "mkdir", "makedirs", "symlink", "link",
                     "chmod", "chown", "truncate", "kill", "killpg", "execv", "execve", "system"):
            patch.setattr(os, name, forbid("os." + name))
        for module, names in ((shutil, ("rmtree", "move", "copy", "copy2", "copyfile", "copytree")),
                              (tempfile, ("mkstemp", "mkdtemp", "NamedTemporaryFile", "TemporaryDirectory")),
                              (subprocess, ("Popen", "run", "call", "check_call", "check_output")),
                              (socket, ("socket", "create_connection")), (fcntl, ("flock", "lockf"))):
            for name in names:
                patch.setattr(module, name, forbid(module.__name__ + "." + name))
        yield


def tree(*roots) -> dict:
    snapshot = {}
    for root in roots:
        for path in sorted(Path(root).rglob("*")):
            snapshot[str(path)] = (os.readlink(path) if path.is_symlink() else
                                   path.read_bytes() if path.is_file() else "dir", path.lstat().st_mode)
    return snapshot


def recompute(result: dict) -> None:
    observation = result["observation"]
    assert policy.observation_digest(observation) == digest(observation) == result["result_sha256"]
    for name in policy.SOURCES:
        entry, projection = observation["sources"][name], result["projections"][name]
        if entry is None:
            assert projection is None
        else:
            assert entry["sha256"] == digest(projection)


@pytest.mark.parametrize("case", ["success", "canary_missing", "consumption_stale", "launch_dry_run",
                                  "document_fence", "journal_unreadable"])
def test_producer_is_read_only_on_success_and_failure(world, monkeypatch, case):
    mutations = {"canary_missing": CANARY_CASES["missing_receipt"][0],
                 "consumption_stale": CONSUMPTION_CASES["stale_prior_instance"][0],
                 "launch_dry_run": _dry_run_only, "document_fence": DOCUMENT_CASES["host_fenced"][0],
                 "journal_unreadable": UNREADABLE_CASES["journal_unreadable"][0]}
    if case in mutations:
        mutations[case](world)
    ports = world.ports()
    before = (tree(world.root, world.proc), copy.deepcopy(world.coordinator.data),
              copy.deepcopy(world.control_store.data), copy.deepcopy(world.delivery.data))
    attempts: list = []
    with no_effects(monkeypatch, attempts):
        result = producer.observe(world.request(), ports)
    assert attempts == [] and all(store.puts == [] for store in world.stores.values())
    assert (tree(world.root, world.proc), world.coordinator.data, world.control_store.data,
            world.delivery.data) == before
    assert all(call[:2] == ["systemctl", "show"] or call[:1] == ["journalctl"] for call in world.runner.calls)
    assert result["observation"]["ok"] is (case == "success")
    recompute(result)


def test_every_source_hash_and_the_common_digest_recompute_from_the_archive(world):
    result = world.observe()
    recompute(result)
    # The archived output round-trips through JSON unchanged; the receipts do not hash the wrapper.
    archived = json.loads(json.dumps(result, sort_keys=True))
    assert archived == result
    recompute(archived)
    assert result["projections"]["launch"]["event"] == launch_event()
    assert result["projections"]["launch"]["cursor"].startswith("s=")
    supervisor, entry = result["projections"]["supervisor"], result["projections"]["entry"]
    assert (supervisor["role"], supervisor["pid"], supervisor["start_ticks"], supervisor["invocation_id"]) == (
        "supervisor", SUP_PID, SUP_TICKS, INVOCATION)
    assert (entry["role"], entry["pid"], entry["start_ticks"], entry["boot_id"]) == ("entry", ENTRY_PID, ENTRY_TICKS,
                                                                                     BOOT_HEX)
    # The entry runs the registered interpreter of a THIRD release; its provenance is the sealed runtime.
    assert entry["argv"][0].split("/releases/")[1].startswith(INTENT_REV)
    assert result["projections"]["descriptor"]["runtime"]["revision"] == PAYLOAD


def _cli(world, *extra) -> list:
    return ["observe-limited-active", "--migration-id", MID, "--expected-id", world.effective_id,
            "--target-id", TARGET, "--plan-id", PLAN, "--actor", "claude-ph4", "--root", str(world.root),
            "--schema", "zeus_aibox_migration", "--control-schema", "zeus_aibox_control", *extra]


def test_cli_prints_observation_evidence_and_draft_and_exits_by_ok(world, monkeypatch, capsys):
    ports = world.ports()
    monkeypatch.setattr(producer, "cli_ports", lambda args: ports)
    assert adapter.main(_cli(world)) == 0
    printed = json.loads(capsys.readouterr().out)
    assert {"observation", "evidence", "transition_draft"} <= set(printed)
    assert printed["observation"]["ok"] is True
    world.edit(RECEIPT_NAME, instance_id=None)
    ports = world.ports()
    assert adapter.main(_cli(world)) == 1
    assert json.loads(capsys.readouterr().out)["observation"]["reason_code"] == policy.CANARY


def test_cli_store_failure_leaks_no_credential_and_reads_no_host(world, monkeypatch, capsys):
    import psycopg

    secret = "hunter2-credential"
    monkeypatch.setenv("ZEUS_TEST_MIGRATION_DSN", "postgresql://zeus:" + secret + "@127.0.0.1:1/zeus")
    monkeypatch.setenv("ZEUS_TEST_CONTROL_DSN", "postgresql://zeus:" + secret + "@127.0.0.1:1/zeus")

    def connect(dsn, **kwargs):
        raise psycopg.OperationalError("connection to " + dsn + " failed: password " + secret)

    def host_command(*args, **kwargs):
        raise AssertionError("host command")

    monkeypatch.setattr(psycopg, "connect", connect)
    monkeypatch.setattr(producer, "run_process", host_command)
    code = adapter.main(_cli(world, "--dsn-env", "ZEUS_TEST_MIGRATION_DSN", "--control-dsn-env",
                               "ZEUS_TEST_CONTROL_DSN", "--lane", "harness"))
    captured = capsys.readouterr()
    assert code == 1 and secret not in captured.out + captured.err
    printed = json.loads(captured.out)
    assert printed["diagnostic"] == {"reason_code": policy.UNAVAILABLE, "detail": "migration"}
    assert printed["transition_draft"] is None


def test_cli_ports_are_read_only_snapshots_and_connect_nothing(monkeypatch):
    import psycopg

    from codex_harness.adapters import store as stores
    from codex_harness.adapters.monitoring import LaneSnapshotStore

    monkeypatch.setenv("ZEUS_TEST_DSN", "postgresql://zeus@127.0.0.1:1/zeus")
    monkeypatch.setattr(psycopg, "connect", lambda *a, **k: (_ for _ in ()).throw(AssertionError("connected")))
    monkeypatch.setattr(stores.PostgresStore, "__init__", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("writer store constructed")))
    args = adapter.parser().parse_args(["observe-limited-active", "--migration-id", MID, "--expected-id", "a" * 64,
                                        "--target-id", TARGET, "--plan-id", PLAN, "--actor", "a", "--root", "/r",
                                        "--dsn-env", "ZEUS_TEST_DSN", "--schema", "zeus_aibox_migration",
                                        "--control-dsn-env", "ZEUS_TEST_DSN", "--control-schema",
                                        "zeus_aibox_control"])
    ports = producer.cli_ports(args)
    assert isinstance(ports.coordinator, LaneSnapshotStore) and isinstance(ports.control, LaneSnapshotStore)
    assert (ports.coordinator.schema, ports.control.schema) == ("zeus_aibox_migration", "zeus_aibox_control")
    assert ports.delivery(ports.control) is ports.control
    args.schema = "public"
    with pytest.raises(migration.MigrationRefused, match="schema_invalid"):
        producer.cli_ports(args)


@pytest.mark.parametrize("argv", [["--consumed", "true"], ["--passed", "true"], ["--receipt", "r.json"],
                                  ["--apply"]])
def test_cli_accepts_no_claim_substitute_receipt_or_apply_argument(world, argv, capsys):
    with pytest.raises(SystemExit):
        adapter.parser().parse_args(_cli(world, *argv))


@pytest.mark.parametrize("option", ["--dsn", "--dsn-env", "--control-dsn-env"])
def test_a_credential_given_as_an_env_name_is_refused_and_never_echoed(world, monkeypatch, capsys, option):
    """argparse accepts `--dsn` as `--dsn-env`: whatever is typed there is a NAME, validated as one, and
    the refusal names the argument only. Nothing is read."""
    secret = "postgresql://zeus:hunter2@127.0.0.1/zeus"
    monkeypatch.setenv("HARNESS_DATABASE_URL", "postgresql://zeus@127.0.0.1:1/zeus")
    monkeypatch.setattr(producer, "HostReader", lambda **kwargs: pytest.fail("host reader built"))
    assert adapter.main(_cli(world, option, secret)) == 1
    captured = capsys.readouterr()
    assert "hunter2" not in captured.out + captured.err
    assert json.loads(captured.out)["refused"] == "environment_name_invalid"


@pytest.mark.parametrize("field,value", [("migration_id", "Bad Id"), ("expected_id", "x"), ("plan_id", "../p"),
                                         ("target_id", ""), ("actor", "Actor!"), ("root", "relative/root"),
                                         ("config_file", "relative.env")])
def test_invalid_request_refuses_before_any_read(world, field, value):
    ports = world.ports()
    with pytest.raises(migration.MigrationRefused, match="request_invalid"):
        producer.observe(world.request(**{field: value}), ports)
    assert world.runner.calls == [] and all(store.transactions == 0 for store in world.stores.values())


# ----- the observation document itself -----------------------------------------------------------------
def test_observation_validation_is_strict_and_ok_means_everything_held(world):
    good = world.observe()["observation"]
    assert policy.validate_observation(good) == good
    for broken in ({**good, "extra": 1},
                   {**good, "checks": {**good["checks"], "canary_bound": False}},
                   {**good, "sources": {**good["sources"], "canary_record": None}},
                   {**good, "reason_code": policy.CANARY},
                   {**good, "ok": False, "reason_code": "made_up"},
                   {**good, "lineage": {**good["lineage"], "owner": "bootstrap"}},
                   {**good, "lineage": {**good["lineage"], "descriptor": {**good["lineage"]["descriptor"],
                                                                          "worker_image": "sha256:" + "8" * 64}}},
                   {**good, "observed_to": "2026-09-28T11:29:00+00:00"},
                   {**good, "sources": {**good["sources"], "launch": {"sha256": "X" * 64,
                                                                       "observed_at": good["observed_to"]}}}):
        with pytest.raises(migration.MigrationRefused, match="observation_invalid"):
            policy.validate_observation(broken)
    with pytest.raises(migration.MigrationRefused, match="observation_invalid"):
        policy.transition_draft({**good, "ok": False}, {}, host="aibox", actor="a", config_sha256="0" * 64)
