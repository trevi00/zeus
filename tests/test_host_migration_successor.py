"""Successor activation (INV-HOST-MIGRATION-001): T and A rows of the bootstrap-recovery matrix.

Everything runs on the memory store and temporary directories; no live host, store, unit, `current`
or receipt is read or written. The launcher checks import the unchanged deploy/aibox tool. Files
named `releases/<rev>` here are LABELLED fixtures (a stub interpreter, a package marker and
`runtime.json`), not built releases. `systemctl` answers and `/proc` are fixture stubs unless a
test says otherwise. The PostgreSQL rows run only with `HARNESS_INTEGRATION=1` against a disposable
server (`isolated_pgstore`); skipped, they prove nothing.

Platform split (INV-HOST-MIGRATION-001): recording, the coordinator's serialization of the switch
port and its refusals run on every platform. Only the real Linux adapter rows (`posix_only`: the
actual symlink rename, file classification and launcher) are skipped elsewhere, with a reason that
names their non-POSIX counterpart, `test_switch_refuses_on_non_posix`.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_continuation import LaneLauncher, accepted_item, only
from test_continuation_requalification import document as requalification_document
from test_continuation_requalification import requalify, withdrawn_world
from test_fleet import GOAL, FakeLauncher, RecordingControl, fleet
from test_fleet import manifest as operation
from test_host_migration import (
    COMMIT,
    HOST_ID,
    IMAGE,
    INTENT,
    H,
    gate_evidence,
    launcher,
    manifest,
    needs_symlink,
    receipt,
    transition,
    walk,
)

from codex_harness.adapters import host_migration as adapter
from codex_harness.adapters.store import MemoryStore, PostgresStore
from codex_harness.application.fleet import BUCKET_UNITS, FleetRunner
from codex_harness.application.host_migration import BUCKET, BUCKET_TRANSITIONS, HostMigrations
from codex_harness.domain import continuation as dc
from codex_harness.domain import host_migration as policy
from codex_harness.domain.host_migration import MigrationRefused

MID = "aibox-migration-001"
NEXT = "e" * 40  # the successor's revision (5aa220f in the live recovery)
LATER = "7" * 40
LOCK = "f" * 64
posix_only = pytest.mark.skipif(os.name != "posix", reason=(
    "INV-HOST-MIGRATION-001 Linux adapter contract: atomic rename(2) of a directory symlink; non-POSIX "
    "refusal is tested by test_switch_refuses_on_non_posix"))


def successor(predecessor_id: str, revision: str = NEXT, **overrides) -> dict:
    document = {"schema": policy.SUCCESSOR_SCHEMA, "migration_id": MID, "host_id": HOST_ID,
                "predecessor_id": predecessor_id, "release_revision": revision, "image": IMAGE,
                "profile_sha256": H, "environment_lock": LOCK, "reason_code": "bootstrap-recovery",
                "evidence": {"release_identity": receipt(policy.OBSERVATION, "revision=" + revision),
                             "worker_compatibility": receipt(policy.OBSERVATION, "image=" + IMAGE),
                             "admission_drained": receipt(policy.OBSERVATION, "fleet=paused-settled")},
                "actor": "owner", "at": "2026-09-26T09:00:00Z"}
    document.update(overrides)
    return document


def paused(store=None) -> tuple[HostMigrations, str, str]:
    """A coordinator in restored_paused with the recorded intent; returns it, the manifest digest
    and the intent id."""
    coordinator = HostMigrations(store or MemoryStore())
    sha = coordinator.plan(manifest())["manifest_sha256"]
    walk(coordinator, sha, policy.RESTORED_PAUSED)
    return coordinator, sha, coordinator.intend_activation(INTENT)["intent_id"]


def snapshot(store: MemoryStore) -> dict:
    return copy.deepcopy(store.data)


# ----- T1-T2: the record and the unchanged derivation ------------------------------------------------
def test_t1_successor_is_recorded_beside_an_unchanged_intent_and_is_the_effective_head():
    coordinator, sha, intent_id = paused()
    before = coordinator.store.data[(BUCKET, MID)]
    transitions = {k: v for k, v in coordinator.store.data.items() if k[0] == BUCKET_TRANSITIONS}
    recorded = coordinator.record_successor(successor(intent_id))
    assert recorded["recorded"] is True and recorded["cached"] is False
    after = coordinator.store.data[(BUCKET, MID)]
    for field in ("activation_intent", "state", "manifest", "manifest_sha256", "checkpoints"):
        assert after[field] == before[field]
    assert after["history"][:-1] == before["history"]
    assert after["history"][-1] == {"event": "activation_successor", "successor_id": recorded["successor_id"],
                                    "predecessor_id": intent_id, "release_revision": NEXT,
                                    "at": "2026-09-26T09:00:00Z", "actor": "owner"}
    assert {k: v for k, v in coordinator.store.data.items() if k[0] == BUCKET_TRANSITIONS} == transitions
    view = coordinator.status(MID)
    assert view["activation_intent"] == intent_id and view["activation_current"] == recorded["successor_id"]
    assert view["activation_chain"] == [
        {"id": intent_id, "release_revision": COMMIT, "kind": "intent", "predecessor_id": None},
        {"id": recorded["successor_id"], "release_revision": NEXT, "kind": "successor", "predecessor_id": intent_id}]
    assert view["state"] == policy.RESTORED_PAUSED and view["rollback_mode"] == policy.ROLLBACK_R1
    document = coordinator.activation_document(MID)
    assert document["intent_id"] == recorded["successor_id"] and document["release_revision"] == NEXT


# The recorded live intent and its installed receipt (evidence/paused-activation/activate/intent.json
# and host-activation.json; digests and ids only, no secret). The manifest digest is the live one.
LIVE_INTENT = {"actor": "claude-paused-activation", "at": "2026-09-25T14:50:51.353103Z",
               "host_id": "machine-id-sha256:d8d97db19abbc67e202823e2fcc0af3ee6f6fad6ddfdaf00c5cdc061d4fd35ef",
               "image": "sha256:9fb57f15a238d5e7789db44bd3036d393dc7acd6ff7d790b3f3ab48497509fce",
               "migration_id": MID,
               "profile_sha256": "cc7150678052ad3d4636a930a7fef34f5a991cfe85b633ada5dc49b830b93bda",
               "release_revision": "ced20281ba10fa3b16280cb73a20279b7e94052a",
               "schema": policy.INTENT_SCHEMA}
LIVE_MANIFEST = "69ec63f9422d49e575f09ea0a5015ed6e214098c76515bd84f2c9e0c37a841c1"
LIVE_INTENT_ID = "69221c1083fdd5ec81c7216e88a342ee11a00ffb36b4560922e91ca058b9230e"
LIVE_RECEIPT_SHA = "f0e5e9ec934be1b001c04be1c61518040fccf20346bb2b45961ee0c625d2cbe9"


def live_row() -> dict:
    return {"migration_id": MID, "manifest": {}, "manifest_sha256": LIVE_MANIFEST, "state": policy.RESTORED_PAUSED,
            "history": [{"event": "activation_intent", "intent_id": LIVE_INTENT_ID}], "checkpoints": {},
            "activation_intent": policy.validate_intent(LIVE_INTENT)}


def test_t2_without_a_successor_the_receipt_bytes_are_the_installed_live_bytes():
    store = MemoryStore()
    with store.transaction() as tx:  # LABELLED: the live row's activation fields, not the live store
        tx.put(BUCKET, MID, live_row())
    coordinator = HostMigrations(store)
    document = coordinator.activation_document(MID)
    assert document["intent_id"] == LIVE_INTENT_ID
    data = adapter._document_bytes(document)
    assert hashlib.sha256(data).hexdigest() == LIVE_RECEIPT_SHA
    assert "supersedes" not in document and "activation_kind" not in document
    assert coordinator.status(MID)["activation_chain"] == [
        {"id": LIVE_INTENT_ID, "release_revision": LIVE_INTENT["release_revision"], "kind": "intent",
         "predecessor_id": None}]


# ----- T3: the unchanged launcher accepts the successor receipt ---------------------------------------
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
        for directory, names, files in os.walk(path, topdown=False):
            for name in files:
                Path(directory, name).chmod(0o555 if name == "python" else 0o444)
            Path(directory).chmod(0o555)
    return path


def host(tmp_path: Path, coordinator: HostMigrations, *, owner: bool = True) -> SimpleNamespace:
    """The fixture host after the paused activation: receipt of the intent, current -> COMMIT, the
    managed owner record present, the managed state dir holding only a canary request."""
    control = tmp_path / "runtime" / "control"
    control.mkdir(parents=True)
    managed = tmp_path / "runtime" / "managed-fleet"
    managed.mkdir(parents=True)
    (managed / "owner-canary-request.json").write_text("{}")
    for revision in (COMMIT, NEXT, LATER):
        release(tmp_path, revision)
    os.symlink(COMMIT, tmp_path / "releases" / "current")
    adapter.write_activation(control, coordinator.activation_document(MID))
    if owner:
        (control / "fleet-owner.json").write_text(json.dumps({"schema": "urn:zeus:aibox-fleet-owner:1",
                                                              "owner": "managed-fleet",
                                                              "unit": "zeus-aibox-managed-fleet.service"}))
    (tmp_path / "machine-id").write_text("fixture-machine\n")
    return SimpleNamespace(root=tmp_path, control=control, releases=tmp_path / "releases", managed=managed,
                           proc=tmp_path / "proc")


def idle_systemctl(argv, timeout=None):
    """Fixture `systemctl show`: every unit inactive with MainPID 0."""
    return SimpleNamespace(returncode=0, stdout="ActiveState=inactive\nMainPID=0\n", stderr="")


def idle(h: SimpleNamespace, runner=idle_systemctl):
    h.proc.mkdir(exist_ok=True)
    return lambda control, managed: adapter.recovery_preconditions(control, managed, runner=runner, proc=h.proc)


def switch(coordinator, h, *, expected=None, check=False, preconditions=None):
    effect = adapter.switch_effect(h.control, h.releases, h.managed, check=check,
                                   preconditions=preconditions or idle(h))
    return coordinator.activation_switch(MID, effect, expected_id=expected)


def launch(service, h, role="fleet"):
    return service.launch_plan(role, {"ZEUS_AIBOX_ROOT": str(h.root), "PATH": "/usr/bin:/bin"},
                               machine_id_path=h.root / "machine-id")


def fixture_intent(h) -> dict:
    """The intent bound to the fixture machine id (the launcher compares the host id digest)."""
    raw = (h.root / "machine-id").read_text().strip()
    return {**INTENT, "host_id": "machine-id-sha256:" + hashlib.sha256(raw.encode()).hexdigest()}


@posix_only
def test_t3_successor_receipt_adds_two_fields_and_the_unchanged_launcher_accepts_it(tmp_path):
    service = launcher()
    coordinator = HostMigrations(MemoryStore())
    sha = coordinator.plan(manifest())["manifest_sha256"]
    walk(coordinator, sha, policy.RESTORED_PAUSED)
    (tmp_path / "machine-id").parent.mkdir(exist_ok=True)
    (tmp_path / "machine-id").write_text("fixture-machine\n")
    intent = fixture_intent(SimpleNamespace(root=tmp_path))
    intent_id = coordinator.intend_activation(intent)["intent_id"]
    original = coordinator.activation_document(MID)
    (tmp_path / "machine-id").unlink()
    h = host(tmp_path, coordinator, owner=False)
    assert launch(service, h)["revision"] == COMMIT
    recorded = coordinator.record_successor(successor(intent_id, host_id=intent["host_id"]))
    document = coordinator.activation_document(MID)
    assert set(document) == set(original) | {"supersedes", "activation_kind"}
    assert {k: document[k] for k in original if k not in ("intent_id", "release_revision")} == \
        {k: original[k] for k in original if k not in ("intent_id", "release_revision")}
    assert document["supersedes"] == intent_id and document["activation_kind"] == "successor"
    assert switch(coordinator, h, expected=recorded["successor_id"], preconditions=lambda c, m: [])["revision"] == NEXT
    plan = launch(service, h)
    assert plan["revision"] == NEXT and plan["argv"][1:] == ["-m", "zeus", "fleet", "run"]
    assert plan["migration_id"] == MID


# ----- T4-T8: refusals, replay and CAS -------------------------------------------------------------
def test_t4_state_intent_and_migration_refusals_write_nothing():
    store = MemoryStore()
    coordinator = HostMigrations(store)
    with pytest.raises(MigrationRefused, match="migration_unknown"):
        coordinator.record_successor(successor(H))
    sha = coordinator.plan(manifest())["manifest_sha256"]
    walk(coordinator, sha, policy.RESTORED_PAUSED)
    before = snapshot(store)
    with pytest.raises(MigrationRefused, match="activation_intent_missing"):
        coordinator.record_successor(successor(H))
    assert store.data == before
    intent_id = coordinator.intend_activation(INTENT)["intent_id"]
    coordinator.advance(transition(sha, policy.RESTORED_PAUSED, policy.LIMITED_ACTIVE, evidence=gate_evidence(
        policy.LIMITED_ACTIVE, host_activation=receipt("host-activation", intent_id),
        service_consumption=receipt("service-startup", "revision=" + COMMIT))))
    before = snapshot(store)
    with pytest.raises(MigrationRefused, match="activation_state"):
        coordinator.record_successor(successor(intent_id))
    assert store.data == before


@pytest.mark.parametrize("change, reason", [
    ({"release_revision": COMMIT}, "successor_same_revision"),
    ({"image": "sha256:" + "9" * 64}, "successor_image_changed"),
    ({"profile_sha256": "9" * 64}, "successor_profile_changed"),
    ({"host_id": "machine-id-sha256:" + "9" * 64}, "successor_other_host"),
])
def test_t5_same_revision_image_profile_and_host_refusals_write_nothing(change, reason):
    coordinator, _, intent_id = paused()
    document = successor(intent_id, change.get("release_revision", NEXT))
    document.update(change)
    if change.get("image"):
        document["evidence"]["worker_compatibility"] = receipt(policy.OBSERVATION, "image=" + change["image"])
    before = snapshot(coordinator.store)
    with pytest.raises(MigrationRefused, match=reason):
        coordinator.record_successor(document)
    assert coordinator.store.data == before


def test_t5_a_secret_named_field_or_credential_value_is_refused_by_name():
    coordinator, _, intent_id = paused()
    before = snapshot(coordinator.store)
    with pytest.raises(MigrationRefused, match="secret_field") as refused:
        coordinator.record_successor({**successor(intent_id), "api_token": "hunter2"})
    assert "hunter2" not in str(refused.value)
    with pytest.raises(MigrationRefused, match="secret_value") as refused:
        coordinator.record_successor(successor(intent_id, actor="postgres://u:hunter2@h/db"))
    assert "hunter2" not in str(refused.value)
    assert coordinator.store.data == before


@pytest.mark.parametrize("gate, value, reason", [
    ("admission_drained", None, "successor_evidence_fields"),
    ("admission_drained", receipt(policy.OBSERVATION, "fleet=paused-settled", ok=False), "successor_evidence_failed"),
    ("admission_drained", receipt(policy.OBSERVATION, "fleet=paused-settled", ok=True, exit_code=3),
     "evidence_inconsistent"),
    ("release_identity", receipt("host-activation", "revision=" + NEXT), "successor_evidence_kind"),
    ("release_identity", receipt(policy.OBSERVATION, "revision=" + COMMIT), "successor_evidence_subject"),
    ("worker_compatibility", receipt(policy.OBSERVATION, "image=sha256:" + "0" * 64), "successor_evidence_subject"),
    ("admission_drained", [], "successor_evidence_missing"),
])
def test_t6_missing_failing_wrong_kind_or_wrong_subject_evidence_is_refused(gate, value, reason):
    coordinator, _, intent_id = paused()
    document = successor(intent_id)
    if value is None:
        del document["evidence"][gate]
    else:
        document["evidence"][gate] = value
    with pytest.raises(MigrationRefused, match=reason):
        coordinator.record_successor(document)
    assert coordinator.status(MID)["activation_current"] == intent_id


def test_t7_identical_replay_is_cached_with_exactly_one_event():
    coordinator, _, intent_id = paused()
    first = coordinator.record_successor(successor(intent_id))
    again = coordinator.record_successor(successor(intent_id))
    assert again == {**first, "recorded": False, "cached": True}
    events = [e for e in coordinator.status(MID)["history"] if e.get("event") == "activation_successor"]
    assert len(events) == 1


def test_t8_a_second_successor_of_the_same_head_conflicts_and_a_superseded_head_is_stale():
    coordinator, _, intent_id = paused()
    first = coordinator.record_successor(successor(intent_id))
    before = snapshot(coordinator.store)
    with pytest.raises(MigrationRefused, match="activation_successor_conflict"):
        coordinator.record_successor(successor(intent_id, LATER))
    with pytest.raises(MigrationRefused, match="activation_predecessor_stale"):
        coordinator.record_successor(successor("0" * 64, LATER))
    assert coordinator.store.data == before
    second = coordinator.record_successor(successor(first["successor_id"], LATER))
    assert coordinator.status(MID)["activation_current"] == second["successor_id"]
    with pytest.raises(MigrationRefused, match="activation_successor_conflict"):
        coordinator.record_successor(successor(first["successor_id"], "8" * 40))


# ----- T9-T10: limited_active binding and the rollback successor --------------------------------------
def test_t9_limited_active_binds_the_effective_activation_only():
    coordinator, sha, intent_id = paused()
    head = coordinator.record_successor(successor(intent_id))["successor_id"]
    identity = {"config_sha256": H, "commit": NEXT, "image": IMAGE, "profile_sha256": H}

    def limited(activation_id, revision, identity=identity):
        return transition(sha, policy.RESTORED_PAUSED, policy.LIMITED_ACTIVE, identity=identity,
                          evidence=gate_evidence(policy.LIMITED_ACTIVE,
                                                 host_activation=receipt("host-activation", activation_id),
                                                 service_consumption=receipt("service-startup",
                                                                             "revision=" + revision)))
    with pytest.raises(MigrationRefused, match="activation_receipt_unbound"):
        coordinator.advance(limited(intent_id, NEXT))
    with pytest.raises(MigrationRefused, match="service_consumption_unbound"):
        coordinator.advance(limited(head, COMMIT))
    with pytest.raises(MigrationRefused, match="activation_identity_mismatch"):
        coordinator.advance(limited(head, NEXT, {**identity, "commit": COMMIT}))
    assert coordinator.advance(limited(head, NEXT))["state"] == policy.LIMITED_ACTIVE
    assert coordinator.activation_document(MID)["state"] == policy.LIMITED_ACTIVE


def test_t10_a_rollback_successor_is_cas_on_the_first_and_leaves_intent_and_r1_unchanged():
    coordinator, _, intent_id = paused()
    plan_before = coordinator.rollback_plan(MID)
    first = coordinator.record_successor(successor(intent_id))["successor_id"]
    back = coordinator.record_successor(successor(first, COMMIT, reason_code="successor_rollback"))
    view = coordinator.status(MID)
    assert view["activation_intent"] == intent_id and view["activation_current"] == back["successor_id"]
    assert [row["release_revision"] for row in view["activation_chain"]] == [COMMIT, NEXT, COMMIT]
    assert coordinator.rollback_plan(MID) == plan_before and plan_before["mode"] == policy.ROLLBACK_R1
    document = coordinator.activation_document(MID)
    assert document["release_revision"] == COMMIT and document["supersedes"] == first
    assert document["intent_id"] != intent_id  # the rollback is a new head, never the old receipt
    assert coordinator.store.data[(BUCKET, MID)]["activation_intent"] == policy.validate_intent(INTENT)


# ----- A1-A7: the file switch ----------------------------------------------------------------------------
def spied(monkeypatch):
    calls = []
    real_write, real_replace, real_fsync = adapter.write_activation, adapter._replace_current, adapter._fsync_directory
    monkeypatch.setattr(adapter, "write_activation", lambda *a, **k: calls.append("receipt") or real_write(*a, **k))
    monkeypatch.setattr(adapter, "_replace_current",
                        lambda *a, **k: calls.append("current") or real_replace(*a, **k))
    monkeypatch.setattr(adapter, "_fsync_directory",
                        lambda path: calls.append("fsync:" + Path(path).name) or real_fsync(path))
    return calls


@posix_only
def test_a1_switch_writes_the_receipt_then_current_and_fsyncs_both_directories(tmp_path, monkeypatch):
    coordinator, _, intent_id = paused()
    h = host(tmp_path, coordinator)
    head = coordinator.record_successor(successor(intent_id))["successor_id"]
    assert switch(coordinator, h, check=True)["classification"] == adapter.RECORDED_NOT_SWITCHED
    calls = spied(monkeypatch)
    result = switch(coordinator, h, expected=head)
    assert calls == ["receipt", "fsync:control", "current", "fsync:releases"]
    assert result["classification_before"] == adapter.RECORDED_NOT_SWITCHED
    assert result["classification"] == adapter.SWITCHED and result["receipt_written"] is True
    assert os.readlink(h.releases / "current") == NEXT
    written = (h.control / "host-activation.json").read_bytes()
    assert written == adapter._document_bytes(coordinator.activation_document(MID))
    assert result["receipt_sha256"] == hashlib.sha256(written).hexdigest()
    assert json.loads(written)["supersedes"] == intent_id
    assert not [p for p in h.releases.iterdir() if p.name.startswith(".current.")]


@posix_only
def test_a2_crash_after_the_receipt_is_receipt_written_refused_by_the_launcher_and_completed_once(
        tmp_path, monkeypatch):
    service = launcher()
    coordinator = HostMigrations(MemoryStore())
    sha = coordinator.plan(manifest())["manifest_sha256"]
    walk(coordinator, sha, policy.RESTORED_PAUSED)
    (tmp_path / "machine-id").write_text("fixture-machine\n")
    intent = fixture_intent(SimpleNamespace(root=tmp_path))
    intent_id = coordinator.intend_activation(intent)["intent_id"]
    (tmp_path / "machine-id").unlink()
    h = host(tmp_path, coordinator)
    head = coordinator.record_successor(successor(intent_id, host_id=intent["host_id"]))["successor_id"]
    real_replace = os.replace

    def crash(source, destination):
        if Path(destination).name == "current":
            raise OSError("LABELLED injected crash between the receipt and the symlink rename")
        return real_replace(source, destination)
    monkeypatch.setattr(adapter.os, "replace", crash)
    with pytest.raises(OSError, match="injected crash"):
        switch(coordinator, h, expected=head)
    monkeypatch.setattr(adapter.os, "replace", real_replace)
    assert not [p for p in h.releases.iterdir() if p.name.startswith(".current.")]  # own temp removed
    assert switch(coordinator, h, check=True)["classification"] == adapter.RECEIPT_WRITTEN
    with pytest.raises(service.Refused) as refused:
        launch(service, h, "owner-actions")  # any activation role: the mixed pair is refused
    assert refused.value.reason == "activation_receipt_revision_mismatch"
    receipt_stat = os.stat(h.control / "host-activation.json")
    calls = spied(monkeypatch)
    result = switch(coordinator, h, expected=head)
    assert calls == ["current", "fsync:releases"]  # completion only; no second receipt write
    assert result["classification_before"] == adapter.RECEIPT_WRITTEN and result["receipt_written"] is False
    assert os.stat(h.control / "host-activation.json").st_ino == receipt_stat.st_ino
    with pytest.raises(service.Refused, match="fleet_owner_managed"):
        launch(service, h)  # the owner marker still blocks the bootstrap role until S4


@posix_only
def test_a3_a_rerun_when_switched_is_cached_and_touches_nothing(tmp_path, monkeypatch):
    coordinator, _, intent_id = paused()
    h = host(tmp_path, coordinator)
    head = coordinator.record_successor(successor(intent_id))["successor_id"]
    switch(coordinator, h, expected=head)
    receipt_stat, link_stat = os.stat(h.control / "host-activation.json"), os.lstat(h.releases / "current")
    calls = spied(monkeypatch)
    result = switch(coordinator, h, expected=head,
                    preconditions=lambda c, m: pytest.fail("a cached switch observes no precondition"))
    assert result["cached"] is True and result["classification"] == adapter.SWITCHED and calls == []
    after_receipt, after_link = os.stat(h.control / "host-activation.json"), os.lstat(h.releases / "current")
    assert (after_receipt.st_ino, after_receipt.st_mtime_ns) == (receipt_stat.st_ino, receipt_stat.st_mtime_ns)
    assert (after_link.st_ino, after_link.st_mtime_ns) == (link_stat.st_ino, link_stat.st_mtime_ns)


def tree(h) -> dict:
    """Every name, link target and file digest under the control and releases directories."""
    state = {}
    for base in (h.control, h.releases):
        for path in sorted(base.iterdir()):
            if path.is_symlink():
                state[str(path)] = "->" + os.readlink(path)
            elif path.is_file():
                state[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
            else:
                state[str(path)] = "dir"
    return state


@posix_only
@pytest.mark.parametrize("damage", ["foreign_receipt", "foreign_current", "absolute_elsewhere", "missing_current",
                                    "missing_receipt"])
def test_a4_foreign_receipt_bytes_or_current_target_are_inconsistent_and_nothing_is_written(tmp_path, damage):
    coordinator, _, intent_id = paused()
    h = host(tmp_path, coordinator)
    head = coordinator.record_successor(successor(intent_id))["successor_id"]
    link = h.releases / "current"
    if damage == "foreign_receipt":
        (h.control / "host-activation.json").write_text('{"schema": "hand-written"}\n')
    elif damage == "foreign_current":
        link.unlink()
        os.symlink(LATER, link)
    elif damage == "absolute_elsewhere":
        link.unlink()
        os.symlink(str(tmp_path / "elsewhere" / NEXT), link)
    elif damage == "missing_current":
        link.unlink()
    else:
        (h.control / "host-activation.json").unlink()
    before = tree(h)
    assert switch(coordinator, h, check=True)["classification"] == adapter.INCONSISTENT
    with pytest.raises(MigrationRefused, match="activation_files_inconsistent"):
        switch(coordinator, h, expected=head)
    assert tree(h) == before


@posix_only
@pytest.mark.parametrize("damage, reason", [
    ("fence", "host_fenced"),
    ("missing", "release_not_ready"),
    ("writable", "release_not_ready"),
    ("runtime", "release_not_ready"),
    ("venv", "release_not_ready"),
    ("package", "release_not_ready"),
])
def test_a5_a_fence_or_an_unready_release_refuses_and_writes_nothing(tmp_path, damage, reason):
    coordinator, _, intent_id = paused()
    h = host(tmp_path, coordinator)
    head = coordinator.record_successor(successor(intent_id))["successor_id"]
    target = h.releases / NEXT
    if damage == "fence":
        adapter.write_fence(h.control, MID, "fixture-fence")
    else:
        for directory, names, files in os.walk(target):
            os.chmod(directory, 0o755)
            for name in files:
                os.chmod(os.path.join(directory, name), 0o644)
        if damage == "missing":
            import shutil
            shutil.rmtree(target)
        elif damage == "runtime":
            (target / "runtime.json").write_text(json.dumps({"revision": LATER}))
        elif damage == "venv":
            (target / ".venv" / "bin" / "python").unlink()
        elif damage == "package":
            (target / "src" / "codex_harness" / "__init__.py").unlink()
        if damage != "missing" and damage != "writable":
            release_seal(target)
    before = tree(h)
    with pytest.raises(MigrationRefused, match=reason):
        switch(coordinator, h, expected=head)
    assert tree(h) == before
    if damage == "fence":
        assert (h.control / "host-fence.json").exists()  # a source fence is never cleared


def release_seal(path: Path) -> None:
    for directory, names, files in os.walk(path, topdown=False):
        for name in files:
            Path(directory, name).chmod(0o555 if name == "python" else 0o444)
        Path(directory).chmod(0o555)


@posix_only
def test_a6_a_failed_replace_removes_only_its_own_temporary_link(tmp_path, monkeypatch):
    coordinator, _, intent_id = paused()
    h = host(tmp_path, coordinator)
    head = coordinator.record_successor(successor(intent_id))["successor_id"]
    os.symlink("0" * 40, h.releases / ".current.foreignleftover")
    real_replace = os.replace
    seen = []

    def fail(source, destination):
        if Path(destination).name == "current":
            seen.append(Path(source).name)
            assert os.path.islink(source)  # the temporary link existed when the rename failed
            raise OSError("LABELLED injected rename failure")
        return real_replace(source, destination)
    monkeypatch.setattr(adapter.os, "replace", fail)
    with pytest.raises(OSError, match="injected rename failure"):
        switch(coordinator, h, expected=head)
    assert seen and seen[0].startswith(".current.") and seen[0] != ".current.foreignleftover"
    leftovers = sorted(p.name for p in h.releases.iterdir() if p.name.startswith(".current."))
    assert leftovers == [".current.foreignleftover"]
    assert os.readlink(h.releases / ".current.foreignleftover") == "0" * 40


@posix_only
def test_a7_a_stale_reader_rewriting_the_intent_receipt_is_refused_by_the_launcher(tmp_path):
    service = launcher()
    coordinator = HostMigrations(MemoryStore())
    sha = coordinator.plan(manifest())["manifest_sha256"]
    walk(coordinator, sha, policy.RESTORED_PAUSED)
    (tmp_path / "machine-id").write_text("fixture-machine\n")
    intent = fixture_intent(SimpleNamespace(root=tmp_path))
    intent_id = coordinator.intend_activation(intent)["intent_id"]
    (tmp_path / "machine-id").unlink()
    h = host(tmp_path, coordinator)
    head = coordinator.record_successor(successor(intent_id, host_id=intent["host_id"]))["successor_id"]
    switch(coordinator, h, expected=head)
    # Pre-successor coordinator code knows only the intent: its `activation-write` derives this.
    row = coordinator.store.data[(BUCKET, MID)]
    stale = policy.activation_receipt(row["activation_intent"], row["manifest_sha256"], row["state"])
    adapter.write_activation(h.control, stale)
    for role in ("fleet", "owner-actions", "managed-fleet"):
        with pytest.raises(service.Refused) as refused:
            launch(service, h, role)
        assert refused.value.reason == "activation_receipt_revision_mismatch"
    assert switch(coordinator, h, check=True)["classification"] == adapter.INCONSISTENT


# ----- effect-boundary preconditions of the supported initial recovery --------------------------------
def systemctl(states: dict):
    def run(argv, timeout=None):
        answer = states.get(argv[2], ("inactive", "0"))
        if answer is None:
            return SimpleNamespace(returncode=1, stdout="", stderr="")
        return SimpleNamespace(returncode=0, stdout="ActiveState=%s\nMainPID=%s\n" % answer, stderr="")
    return run


def fake_process(proc: Path, pid: int, argv: list) -> None:
    (proc / str(pid)).mkdir(parents=True)
    (proc / str(pid) / "cmdline").write_bytes(b"\0".join(word.encode() for word in argv) + b"\0")


@posix_only
@pytest.mark.parametrize("case, violation", [
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
])
def test_every_recovery_precondition_is_rechecked_at_the_effect_boundary(tmp_path, case, violation):
    coordinator, _, intent_id = paused()
    h = host(tmp_path, coordinator)
    head = coordinator.record_successor(successor(intent_id))["successor_id"]
    h.proc.mkdir()
    states = {}
    if case == "owner_missing":
        (h.control / "fleet-owner.json").unlink()
    elif case == "owner_invalid":
        (h.control / "fleet-owner.json").write_text("{}")
    elif case == "bootstrap_active":
        states["zeus-aibox-fleet.service"] = ("active", "77")
    elif case == "managed_mainpid":
        states["zeus-aibox-managed-fleet.service"] = ("inactive", "12")
    elif case == "controller_active":
        states["zeus-aibox-host-delivery.service"] = ("activating", "0")
    elif case == "controller_unknown":
        states["zeus-aibox-host-delivery.service"] = None
    elif case in ("launch_request", "descriptor", "controller_state"):
        name = {"launch_request": "managed-launch.json", "descriptor": "descriptor.json",
                "controller_state": "controller-state.json"}[case]
        (h.managed / name).write_text("{}")
    elif case == "runner":
        fake_process(h.proc, 4242, ["/srv/zeus/releases/x/.venv/bin/python", "-m", "zeus", "fleet", "run"])
    elif case == "supervise":
        fake_process(h.proc, 4243, ["python", "-m", "codex_harness.adapters.managed_runtime", "supervise"])
    else:
        fake_process(h.proc, 4244, ["/usr/bin/python3", "/srv/zeus/deploy/aibox/zeus_aibox_service.py",
                                    "launch", "--role", "managed-fleet"])
    # Observers that must NOT count: a shell naming the words in one argv word, and a dry run.
    fake_process(h.proc, 5001, ["sh", "-c", "pgrep -f 'zeus fleet run|managed_runtime'"])
    fake_process(h.proc, 5002, ["/usr/bin/python3", "zeus_aibox_service.py", "launch", "--role", "fleet",
                                "--dry-run"])
    before = tree(h)
    checked = switch(coordinator, h, check=True, preconditions=idle(h, systemctl(states)))
    assert checked["classification"] == adapter.RECORDED_NOT_SWITCHED and violation in checked["preconditions"]
    with pytest.raises(MigrationRefused) as refused:
        switch(coordinator, h, expected=head, preconditions=idle(h, systemctl(states)))
    assert refused.value.reason_code == "recovery_precondition" and refused.value.field == violation
    assert tree(h) == before


@needs_symlink
def test_an_idle_host_passes_and_an_unreadable_process_table_is_a_violation(tmp_path):
    coordinator, _, _ = paused()
    h = host(tmp_path, coordinator)
    h.proc.mkdir()
    assert adapter.recovery_preconditions(h.control, h.managed, runner=idle_systemctl, proc=h.proc) == []
    missing = adapter.recovery_preconditions(h.control, h.managed, runner=idle_systemctl, proc=tmp_path / "noproc")
    assert missing == ["process_table_unreadable"]

    def broken(argv, timeout=None):
        raise OSError("LABELLED systemctl unavailable")
    unknown = adapter.recovery_preconditions(h.control, h.managed, runner=broken, proc=h.proc)
    assert unknown == ["unit_state_unknown:" + unit for unit in adapter.SWITCH_UNITS]


# ----- serialization: the coordinator transaction is the shared fence -----------------------------------
class Paused:
    """Wrap a switch effect so it stops inside the coordinator transaction, after the head selection
    and before the wrapped effect classifies or writes, until the test releases it (deterministic
    interleaving)."""

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


@posix_only
def test_switch_switch_interleaving_the_second_waits_and_finds_the_pair_switched(tmp_path, monkeypatch):
    coordinator, _, intent_id = paused()
    h = host(tmp_path, coordinator)
    head = coordinator.record_successor(successor(intent_id))["successor_id"]
    calls = spied(monkeypatch)
    first = Paused(adapter.switch_effect(h.control, h.releases, h.managed, preconditions=idle(h)))
    a, a_box = run_thread(lambda: coordinator.activation_switch(MID, first, expected_id=head))
    assert first.entered.wait(10)
    b, b_box = run_thread(lambda: switch(coordinator, h, expected=head))
    b.join(0.3)
    assert b.is_alive() and calls == []  # the second switch cannot even classify yet
    first.release.set()
    a.join(10)
    b.join(10)
    assert a_box["result"]["classification_before"] == adapter.RECORDED_NOT_SWITCHED
    assert b_box["result"]["cached"] is True
    assert calls.count("receipt") == 1 and calls.count("current") == 1


@posix_only
def test_record_switch_interleaving_a_successor_waits_and_a_stale_switch_never_overwrites_it(
        tmp_path, monkeypatch):
    coordinator, _, intent_id = paused()
    h = host(tmp_path, coordinator)
    first_id = coordinator.record_successor(successor(intent_id))["successor_id"]
    effect = Paused(adapter.switch_effect(h.control, h.releases, h.managed, preconditions=idle(h)))
    a, a_box = run_thread(lambda: coordinator.activation_switch(MID, effect, expected_id=first_id))
    assert effect.entered.wait(10)
    b, b_box = run_thread(lambda: coordinator.record_successor(successor(first_id, LATER)))
    b.join(0.3)
    assert b.is_alive()  # the newer head waits for the switch that already selected E1
    assert coordinator.store.data[(BUCKET, MID)].get("activation_successors")[-1]["release_revision"] == NEXT
    effect.release.set()
    a.join(10)
    b.join(10)
    assert a_box["result"]["revision"] == NEXT and b_box["result"]["recorded"] is True
    newer = b_box["result"]["successor_id"]
    # A process still holding the older expectation is refused before any classification or write.
    before = tree(h)
    with pytest.raises(MigrationRefused, match="activation_head_moved"):
        switch(coordinator, h, expected=first_id)
    assert tree(h) == before
    done = switch(coordinator, h, expected=newer)
    assert done["classification_before"] == adapter.RECORDED_NOT_SWITCHED and done["revision"] == LATER
    with pytest.raises(MigrationRefused, match="activation_head_moved"):
        switch(coordinator, h, expected=first_id)  # the stale head can never be written back
    assert os.readlink(h.releases / "current") == LATER
    assert json.loads((h.control / "host-activation.json").read_text())["intent_id"] == newer


@posix_only
def test_a_successor_recorded_before_the_first_switch_leaves_files_inconsistent_not_overwritten(tmp_path):
    coordinator, _, intent_id = paused()
    h = host(tmp_path, coordinator)
    first_id = coordinator.record_successor(successor(intent_id))["successor_id"]
    second = coordinator.record_successor(successor(first_id, LATER))["successor_id"]
    before = tree(h)
    with pytest.raises(MigrationRefused, match="activation_head_moved"):
        switch(coordinator, h, expected=first_id)
    with pytest.raises(MigrationRefused, match="activation_files_inconsistent"):
        switch(coordinator, h, expected=second)  # intent files vs a two-step head: stop for root
    assert tree(h) == before


# ----- portable: the coordinator side of the switch port, on every platform ---------------------------
class PortFixture:
    """LABELLED switch port: no file, no platform check; records each plan it is given."""

    def __init__(self):
        self.plans = []

    def __call__(self, plan):
        self.plans.append(plan)
        return {"effective_id": plan["effective_id"], "revision": plan["effective"]["release_revision"]}


def test_portable_the_port_gets_the_effective_and_predecessor_receipts_and_a_stale_head_never_reaches_it():
    port = PortFixture()
    with pytest.raises(MigrationRefused, match="migration_unknown"):
        HostMigrations(MemoryStore()).activation_switch(MID, port)
    coordinator, _, intent_id = paused()
    assert coordinator.activation_switch(MID, port)["effective_id"] == intent_id  # the intent is the head
    assert port.plans[0]["kind"] == "intent" and port.plans[0]["predecessor"] is None
    head = coordinator.record_successor(successor(intent_id))["successor_id"]
    before = snapshot(coordinator.store)
    assert coordinator.activation_switch(MID, port, expected_id=head)["revision"] == NEXT
    plan = port.plans[-1]
    assert plan["kind"] == "successor" and plan["effective"] == coordinator.activation_document(MID)
    assert (plan["predecessor"]["intent_id"], plan["predecessor"]["release_revision"]) == (intent_id, COMMIT)
    with pytest.raises(MigrationRefused, match="activation_head_moved"):
        coordinator.activation_switch(MID, port, expected_id=intent_id)
    assert len(port.plans) == 2

    def refusing(plan):
        raise MigrationRefused("recovery_precondition", "unit_active:zeus-aibox-fleet.service")
    with pytest.raises(MigrationRefused, match="recovery_precondition"):
        coordinator.activation_switch(MID, refusing, expected_id=head)
    assert coordinator.store.data == before  # the coordinator writes no row for a switch


def test_portable_a_second_switch_then_a_record_wait_for_the_port_inside_the_transaction():
    coordinator, _, intent_id = paused()
    head = coordinator.record_successor(successor(intent_id))["successor_id"]
    port = PortFixture()
    held = Paused(port)
    a, a_box = run_thread(lambda: coordinator.activation_switch(MID, held, expected_id=head))
    assert held.entered.wait(10)
    b, b_box = run_thread(lambda: coordinator.activation_switch(MID, port, expected_id=head))
    b.join(0.3)
    assert b.is_alive() and port.plans == []  # the second switch cannot even select a head yet
    held.release.set()
    a.join(10)
    b.join(10)
    assert "error" not in a_box and "error" not in b_box, (a_box, b_box)
    assert [plan["effective_id"] for plan in port.plans] == [head, head]
    held = Paused(port)
    a, a_box = run_thread(lambda: coordinator.activation_switch(MID, held, expected_id=head))
    assert held.entered.wait(10)
    c, c_box = run_thread(lambda: coordinator.record_successor(successor(head, LATER)))
    c.join(0.3)
    assert c.is_alive()  # the record waits for the held switch (its row is read unlocked below)
    assert len(coordinator.store.data[(BUCKET, MID)]["activation_successors"]) == 1
    held.release.set()
    a.join(10)
    c.join(10)
    assert a_box["result"]["revision"] == NEXT and c_box["result"]["recorded"] is True
    with pytest.raises(MigrationRefused, match="activation_head_moved"):
        coordinator.activation_switch(MID, port, expected_id=head)  # the older head is never switched again
    assert port.plans[-1]["effective_id"] == head and len(port.plans) == 3


def test_switch_refuses_on_non_posix(tmp_path, monkeypatch, capsys):
    """The counterpart of every `posix_only` row: on a non-POSIX host as it is; on POSIX through the
    adapter's own platform seam (never the process-wide `os.name`). Nothing is written: no receipt,
    no temporary link, no store row, and the CLI never opens the coordinator store."""
    if os.name == "posix":
        monkeypatch.setattr(adapter, "_posix", lambda: False)
    coordinator, _, intent_id = paused()
    h = SimpleNamespace(control=tmp_path / "control", releases=tmp_path / "releases", managed=tmp_path / "managed")
    for directory in (h.control, h.releases, h.managed):
        directory.mkdir()
    adapter.write_activation(h.control, coordinator.activation_document(MID))  # the intent's receipt
    release(tmp_path, NEXT, seal=False)
    head = coordinator.record_successor(successor(intent_id))["successor_id"]

    def files():
        return sorted((str(p.relative_to(tmp_path)), p.read_bytes() if p.is_file() else None)
                      for p in tmp_path.rglob("*"))
    before, rows = files(), snapshot(coordinator.store)
    calls = spied(monkeypatch)
    for check, expected in ((False, head), (True, None)):
        with pytest.raises(MigrationRefused) as refused:
            switch(coordinator, h, expected=expected, check=check,
                   preconditions=lambda c, m: pytest.fail("no precondition is observed"))
        assert (refused.value.reason_code, refused.value.field) == (adapter.POSIX_ONLY, "platform")
    monkeypatch.setattr(adapter, "_coordinator", lambda args: pytest.fail("the coordinator store is never opened"))
    paths = ["--migration-id", MID, "--control-dir", str(h.control), "--releases-dir", str(h.releases),
             "--managed-state-dir", str(h.managed), "--dsn-env", "ZEUS_AIBOX_MIGRATION_DSN",
             "--schema", "zeus_aibox_migration"]
    for extra in (["--expected-id", head], ["--check"]):
        assert adapter.main(["activation-switch", *extra, *paths]) == 1
        assert json.loads(capsys.readouterr().out) == {"refused": adapter.POSIX_ONLY, "field": "platform"}
    assert calls == [] and files() == before and coordinator.store.data == rows
    assert not [name for name, _ in before if ".current." in name]


# ----- CLI --------------------------------------------------------------------------------------------
@posix_only
def test_cli_records_a_successor_and_switches_only_with_an_expected_head(tmp_path, monkeypatch, capsys):
    coordinator, _, intent_id = paused()
    h = host(tmp_path, coordinator)
    monkeypatch.setattr(adapter, "_coordinator", lambda args: coordinator)
    monkeypatch.setattr(adapter, "recovery_preconditions", lambda control, managed: [])  # fixture: idle host
    document = tmp_path / "successor.json"
    document.write_text(json.dumps(successor(intent_id)))
    store = ["--dsn-env", "ZEUS_AIBOX_MIGRATION_DSN", "--schema", "zeus_aibox_migration"]
    assert adapter.main(["activation-successor", "--file", str(document), *store]) == 0
    head = json.loads(capsys.readouterr().out)["successor_id"]
    assert adapter.main(["activation-successor", "--file", str(document), *store]) == 0
    assert json.loads(capsys.readouterr().out)["cached"] is True
    paths = ["--migration-id", MID, "--control-dir", str(h.control), "--releases-dir", str(h.releases),
             "--managed-state-dir", str(h.managed), *store]
    assert adapter.main(["activation-switch", *paths]) == 1
    assert json.loads(capsys.readouterr().out) == {"refused": "expected_id_required", "field": "expected_id"}
    assert adapter.main(["activation-switch", "--check", *paths]) == 0
    assert json.loads(capsys.readouterr().out)["classification"] == adapter.RECORDED_NOT_SWITCHED
    assert adapter.main(["activation-switch", "--expected-id", head, *paths]) == 0
    assert json.loads(capsys.readouterr().out)["revision"] == NEXT
    (h.control / "host-activation.json").write_text("{}\n")
    assert adapter.main(["activation-switch", "--check", *paths]) == 1  # inconsistent is not a pass


# ----- S6 ordering on the actual FleetRunner ------------------------------------------------------------
# Two different pauses. A CLOSED runtime control (the managed runner's pause file, RecordingControl
# here) makes the runner drain only. The S5/S6 bootstrap `zeus fleet run` has NO runtime control: only
# the Fleet DB pause holds it, which lets continuation state and the queue progress but refuses every
# conductor unit and worker admission (F-208-1; the second test below).
class RequalificationContinuation:
    """LABELLED continuation fixture with the runner's port (`__call__`, `drain`, `owned`). Its
    ordinary pass is what admits the intended requalification: it enqueues the job the way the
    first effect would; `drain` only settles and never enqueues."""

    def __init__(self, fleet_):
        self.fleet, self.calls, self.intent = fleet_, [], "intended"

    def __call__(self):
        self.calls.append("pass")
        if self.intent == "intended":
            self.fleet.enqueue("a", operation("h1-requal", ["docs/x.md"]), GOAL, [])
            self.intent = "admitted"
            return {"outcome": "ok", "actions": [{"effect": "admitted"}]}
        return {"outcome": "ok", "actions": []}

    def drain(self):
        self.calls.append("drain")
        return {"outcome": "idle"}

    def owned(self):
        return []


def test_a_closed_runtime_control_only_drains_and_its_reopening_admits_the_requalification(tmp_path):
    f = fleet(tmp_path)
    control = RecordingControl()
    control.paused = True
    continuation = RequalificationContinuation(f)
    accepted = {"status": "accepted", "reason_code": "lead_accepted", "exit_code": 0}
    launcher_ = FakeLauncher({"h1-requal": accepted})
    runner = FleetRunner(f, launcher_, interval=0, control=control, continuation=continuation)
    passes = []

    def sleep(seconds):
        passes.append(seconds)
        if len(passes) == 3:
            control.stopping = True
    runner.sleep = sleep
    summary = runner.run(once=False)
    # Closed control (the managed path, not the S5/S6 bootstrap): the continuation is only drained.
    assert continuation.calls and set(continuation.calls) == {"drain"} and continuation.intent == "intended"
    assert summary["admitted"] == [] and f.status()["jobs"] == [] and launcher_.launched == []
    assert {"admission": "paused", "active": 0, "unresolved": 0} in control.beats
    # The control reopens; the ordinary pass admits and the job runs.
    control.paused = control.stopping = False
    resumed = FleetRunner(f, launcher_, interval=0, control=control, continuation=continuation).run(once=True)
    first_pass = continuation.calls.index("pass")
    assert first_pass > 0 and set(continuation.calls[:first_pass]) == {"drain"}
    assert continuation.intent == "admitted" and resumed["admitted"] == ["h1-requal"]
    assert launcher_.launched == ["h1-requal"]
    assert resumed["finalized"] == [{"id": "h1-requal", "status": "accepted", "reason_code": "lead_accepted"}]


def test_s6_the_control_less_bootstrap_on_a_db_paused_fleet_moves_state_but_starts_nothing(tmp_path):
    """F-208-1, the S5/S6 shape: the REAL FleetRunner with control=None (`zeus fleet run`), the REAL
    Continuation and Fleet of test_continuation's world (LABELLED fixture worker, lead and conductor
    port). An accepted job awaits its conductor and an owner requalification is intended (H1'
    shape) when the owner pauses the Fleet in its store."""
    world, origin, delivery, rationale = withdrawn_world(tmp_path)
    awaiting = accepted_item(world, "op-2", "docs/b.md")
    requalify(world, requalification_document(delivery, rationale))
    requalification = dc.requalification_id(delivery["id"])
    assert world.intents()[requalification]["state"] == dc.INTENDED
    world.fleet.pause()

    def units():
        with world.control.transaction() as tx:
            return list(tx.scan(BUCKET_UNITS))
    conducted, held = list(world.conductor.calls), units()
    assert conducted == [origin]  # the first item's conductor ran (and was settled) before the pause
    launcher_ = LaneLauncher(world, [True])
    ticks = []
    runner = FleetRunner(world.fleet, launcher_, sleep=lambda _: None,
                         continuation=lambda: ticks.append(world.tick()) or ticks[-1])
    assert runner.control is None
    summary = runner.run(once=True)
    intents = world.intents()
    successor_job = intents[requalification]["successor_job"]
    # Allowed while DB-paused: continuation state and the queue progress (not drain-only).
    assert summary["continuation"]["state"] == "ok" and ticks
    assert intents[requalification]["state"] == dc.ADMITTED and world.jobs()[successor_job]["status"] == "queued"
    assert only(intents, route=dc.CONDUCTOR, origin_job=awaiting)["state"] == dc.INTENDED
    assert {skip["reason_code"] for tick in ticks for skip in tick["skipped"]} == {"conductor_paused"}
    # Refused while DB-paused: no conductor start, no new execution unit, no worker admission or launch.
    assert world.conductor.calls == conducted and units() == held and summary["units_held"] == []
    assert summary["admitted"] == [] and summary["blocked"] == {successor_job: "paused"}
    assert launcher_.launched == []
    # P6a: the owner's resume. The awaiting conductor starts once and the requalification is admitted once.
    world.fleet.resume()
    resumed = runner.run(once=True)
    assert resumed["admitted"] == [successor_job] and launcher_.launched == [successor_job]
    assert world.conductor.calls[:2] == [origin, awaiting] and world.conductor.calls.count(awaiting) == 1


# ----- PostgreSQL: the same fence across two connections -----------------------------------------------
@pytest.mark.integration
@posix_only
def test_postgres_record_waits_for_a_switch_holding_the_coordinator_lock(tmp_path, isolated_pgstore):
    coordinator, _, intent_id = paused(isolated_pgstore)
    h = host(tmp_path, coordinator)
    first_id = coordinator.record_successor(successor(intent_id))["successor_id"]
    other = HostMigrations(PostgresStore(isolated_pgstore.dsn))  # its own connection per transaction
    effect = Paused(adapter.switch_effect(h.control, h.releases, h.managed, preconditions=idle(h)))
    a, a_box = run_thread(lambda: coordinator.activation_switch(MID, effect, expected_id=first_id))
    assert effect.entered.wait(10)
    b, b_box = run_thread(lambda: other.record_successor(successor(first_id, LATER)))
    b.join(1.0)
    assert b.is_alive()  # blocked on advisory lock 734219 held by the switch transaction
    effect.release.set()
    a.join(15)
    b.join(15)
    assert "error" not in a_box and "error" not in b_box, (a_box, b_box)
    assert a_box["result"]["revision"] == NEXT and b_box["result"]["recorded"] is True
    with pytest.raises(MigrationRefused, match="activation_head_moved"):
        other.activation_switch(MID, adapter.switch_effect(h.control, h.releases, h.managed,
                                                           preconditions=idle(h)), expected_id=first_id)
    assert switch(other, h, expected=b_box["result"]["successor_id"])["revision"] == LATER


@pytest.mark.integration
def test_postgres_a_waiter_past_the_10s_lock_timeout_is_refused_and_writes_nothing(isolated_pgstore):
    """F-208-3: the wait on the coordinator lock is bounded by PostgresStore's `lock_timeout = '10s'`;
    the held effect itself is not. Portable: the switch port is a fixture, not the Linux adapter."""
    import time

    import psycopg

    coordinator, _, intent_id = paused(isolated_pgstore)
    head = coordinator.record_successor(successor(intent_id))["successor_id"]
    held = Paused(PortFixture(), timeout=60)
    a, a_box = run_thread(lambda: coordinator.activation_switch(MID, held, expected_id=head))
    assert held.entered.wait(10)
    started = time.monotonic()
    try:
        with pytest.raises(psycopg.errors.LockNotAvailable):
            HostMigrations(PostgresStore(isolated_pgstore.dsn)).record_successor(successor(head, LATER))
        waited = time.monotonic() - started
    finally:
        held.release.set()
        a.join(15)
    assert 9.5 <= waited < 20, waited
    assert "error" not in a_box and a_box["result"]["revision"] == NEXT  # the holder was never broken
    view = coordinator.status(MID)
    assert view["activation_current"] == head and len(view["activation_chain"]) == 2  # the waiter wrote nothing


@pytest.mark.integration
def test_postgres_two_successors_of_one_head_race_to_exactly_one_record(isolated_pgstore):
    coordinator, _, intent_id = paused(isolated_pgstore)
    barrier = threading.Barrier(2)

    def record(revision):
        barrier.wait(10)
        return HostMigrations(PostgresStore(isolated_pgstore.dsn)).record_successor(successor(intent_id, revision))
    threads = [run_thread(lambda r=r: record(r)) for r in (NEXT, LATER)]
    for thread, _ in threads:
        thread.join(20)
    outcomes = sorted("recorded" if "result" in box else box["error"].reason_code for _, box in threads)
    assert outcomes == ["activation_successor_conflict", "recorded"]
    assert len(coordinator.status(MID)["activation_chain"]) == 2


# ----- the unchanged launcher as a real process under a temporary root ----------------------------------
LAUNCHER = Path(__file__).resolve().parents[1] / "deploy" / "aibox" / "zeus_aibox_service.py"


def dry_run(h, role: str) -> tuple[int, dict]:
    import subprocess
    import sys

    completed = subprocess.run([sys.executable, str(LAUNCHER), "launch", "--role", role, "--dry-run"],
                               env={"ZEUS_AIBOX_ROOT": str(h.root), "PATH": "/usr/bin:/bin"},
                               capture_output=True, text=True, timeout=60)
    return completed.returncode, json.loads(completed.stderr)


@posix_only
@pytest.mark.skipif(not Path("/etc/machine-id").is_file(), reason="the launcher process reads /etc/machine-id")
def test_the_launcher_process_refuses_the_mixed_pair_and_launches_the_switched_revision(tmp_path, monkeypatch):
    """The receipts name THIS machine's id digest (read-only), because the launcher process reads
    /etc/machine-id itself; everything else lives in the temporary root."""
    raw = Path("/etc/machine-id").read_text("ascii").strip()
    local = "machine-id-sha256:" + hashlib.sha256(raw.encode()).hexdigest()
    coordinator = HostMigrations(MemoryStore())
    sha = coordinator.plan(manifest())["manifest_sha256"]
    walk(coordinator, sha, policy.RESTORED_PAUSED)
    intent_id = coordinator.intend_activation({**INTENT, "host_id": local})["intent_id"]
    h = host(tmp_path, coordinator)
    assert dry_run(h, "fleet") == (78, {"event": "launch_refused", "role": "fleet", "reason": "fleet_owner_managed"})
    code, event = dry_run(h, "owner-actions")
    assert code == 78 and event["reason"] == "owner_actions_policy_unset"  # past the activation check
    head = coordinator.record_successor(successor(intent_id, host_id=local))["successor_id"]
    real_replace = os.replace

    def crash(source, destination):
        if Path(destination).name == "current":
            raise OSError("LABELLED injected crash")
        return real_replace(source, destination)
    monkeypatch.setattr(adapter.os, "replace", crash)
    with pytest.raises(OSError, match="LABELLED injected crash"):
        switch(coordinator, h, expected=head)
    monkeypatch.setattr(adapter.os, "replace", real_replace)
    for role in ("fleet", "managed-fleet", "owner-actions"):
        code, event = dry_run(h, role)
        assert (code, event["reason"]) == (78, "activation_receipt_revision_mismatch")
    switch(coordinator, h, expected=head)
    assert dry_run(h, "fleet")[1]["reason"] == "fleet_owner_managed"  # owner marker kept until S4
    os.rename(h.control / "fleet-owner.json", h.control / "fleet-owner.retired-fixture.json")  # S4 shape
    assert dry_run(h, "fleet") == (0, {"event": "launch", "role": "fleet", "revision": NEXT, "migration_id": MID})
    code, event = dry_run(h, "managed-fleet")
    assert (code, event["reason"]) == (78, "fleet_owner_not_managed")
