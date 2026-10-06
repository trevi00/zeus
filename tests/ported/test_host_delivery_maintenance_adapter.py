"""Ported SOURCE main b9d8f15 (S2R) suite `tests/test_host_delivery_maintenance_adapter.py` run against the target (G1-13 batch b).

Every assertion is S2R's, unchanged. Adaptations: import lines (`delivery.adapters.*`, `delivery.domain.*`; `policy` is
`delivery.domain.maintenance`, where the S2R `domain.host_delivery` maintenance policy lives; `digest` is `kernel.ids`'s);
`ProcessHostTarget`, `ManagedFleetTarget` and `SystemdManagedFleetTarget` are the `m7_delivery` wired subclasses (composition's
injections closed over; `process_reader=` passes through). ONE row is dropped from `test_non_systemd_kinds_refuse_restart_authority`:
`ScheduledTaskHostTarget` is W-B (Windows, classified not moved: it does not exist in the target), as the ported
`test_host_delivery` skips its cases; the other three kinds keep the S2R assertions.

S2R docstring follows.

INV-HOST-DELIVERY-MAINTENANCE-001, host adapter slice: the typed restart authority of
`HostTargetBase.start`, the managed generation observation, the owner target snapshot and the owner canary
reads.

Every host here is a LABELLED fake or a disposable `tmp_path` state directory. The restart-path targets are
`SystemdManagedFleetTarget` subclasses whose `_prepare`, `_reconcile`, `_activation_gate`, `stop`, `_retire`,
`_launch`, `launch_record` and `generation_observation` only record what they were asked; the classification
between them is the REAL pure domain policy (`classify_restart`). The observation tests drive the real
`generation_observation` over a labelled `systemctl show` runner and a labelled `/proc` reader. No unit,
process, signal, store, model or provider is touched: `os.kill`/`os.killpg` raise if anything tries.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from m7_delivery import ManagedFleetTarget, ProcessHostTarget, SystemdManagedFleetTarget

from codex_harness.delivery.adapters.host_delivery import (
    LOCK_DIR,
    RECEIPT_FILE,
    STATE_FILE,
    HostTargetBase,
    canary_receipt_file,
    canary_request_file,
)
from codex_harness.delivery.adapters.host_migration import SystemdHostTarget
from codex_harness.delivery.adapters.managed_runtime import (
    GENERATION_UNIT_PROPERTIES,
    LAUNCH_REQUEST_FILE,
    LAUNCH_REQUEST_SCHEMA,
    TARGET_FILE,
    owner_target,
)
from codex_harness.delivery.domain import maintenance as policy
from codex_harness.delivery.domain.host_delivery import (
    DESCRIPTOR_SCHEMA,
    KIND_MANAGED,
    KIND_MANAGED_SYSTEMD,
    KIND_PROCESS,
    KIND_SYSTEMD,
    MANAGED_SYSTEMD_UNIT,
    RECEIPT_SCHEMA,
    REGISTRY_SCHEMA,
    DeliveryRefused,
    LifecycleInterrupted,
    descriptor_digest,
    managed_runtime_root,
    validate_targets,
)
from codex_harness.delivery.domain.managed_runtime import HEARTBEAT_FILE, HEARTBEAT_SCHEMA
from codex_harness.kernel.ids import digest

UNIT = MANAGED_SYSTEMD_UNIT + ".service"
REVISION = "1" * 40
IMAGE = "zeus-worker@sha256:" + "d" * 64
RETIRING_INSTANCE, NEW_INSTANCE = "a1" * 16, "b2" * 16
RETIRING_INVOCATION, NEW_INVOCATION = "c3" * 16, "d4" * 16
MAINTENANCE_ID = "active_generation_1:" + "9" * 64
REQUESTED_AT = "2026-09-29T00:00:00+00:00"
# Sentinels that must never leave the observation: raw unit paths and environment file names.
SENTINEL_GROUP = "/system.slice/SENTINEL-CGROUP-zeus-aibox-managed-fleet.service"
SENTINEL_ENV_FILES = ["/srv/SENTINEL-CONFIG/zeus-aibox.env (ignore_errors=no)",
                      "/srv/SENTINEL-SECRETS/zeus-aibox-selected.env (ignore_errors=no)"]
SENTINEL_DROP_INS = "/etc/systemd/system/SENTINEL-DROPIN.d/a.conf /etc/systemd/system/SENTINEL-DROPIN.d/b.conf"


@pytest.fixture(autouse=True)
def no_signals(monkeypatch):
    """Nothing in this slice may signal a process; the maintenance restart is a graceful stop only."""
    def refuse(*_args, **_kwargs):
        raise AssertionError("a signal was sent")
    monkeypatch.setattr(os, "kill", refuse)
    monkeypatch.setattr(os, "killpg", refuse, raising=False)


# ----- labelled fixtures --------------------------------------------------------------------------
def managed_target(tmp_path, kind=KIND_MANAGED_SYSTEMD, **overrides) -> dict:
    entry = {"target_id": "managed-fleet", "kind": kind, "root": str(tmp_path / "managed"),
             "state_dir": str(tmp_path / "state"),
             "service": MANAGED_SYSTEMD_UNIT if kind == KIND_MANAGED_SYSTEMD else "zeus-fleet",
             "source": str(tmp_path / "source"), "python": sys.executable, "environment_lock": "a" * 64,
             **overrides}
    return validate_targets({"schema": REGISTRY_SCHEMA, "targets": [entry]})["targets"][0]


def plain_target(tmp_path, kind) -> dict:
    entry = {"target_id": "plain-target", "kind": kind, "root": str(tmp_path / "root"),
             "state_dir": str(tmp_path / "state"),
             "service": "zeus-aibox-collect" if kind == KIND_SYSTEMD else "zeus-plain"}
    return validate_targets({"schema": REGISTRY_SCHEMA, "targets": [entry]})["targets"][0]


def descriptor_for(target) -> dict:
    return {"schema": DESCRIPTOR_SCHEMA, "target_id": target["target_id"],
            "root": managed_runtime_root(target, REVISION) if target["kind"] in (KIND_MANAGED, KIND_MANAGED_SYSTEMD)
            else target["root"], "revision": REVISION, "worker_image": IMAGE, "profile_digest": "e" * 64,
            "predecessor": None}


def receipt_for(desc, instance, *, pid=101, started_at="2026-09-28T00:00:01+00:00") -> dict:
    return {"schema": RECEIPT_SCHEMA, "target_id": desc["target_id"], "instance_id": instance, "pid": pid,
            "started_at": started_at, "runtime_root": desc["root"], "module_root": desc["root"] + "/src/codex_harness",
            "descriptor_sha256": descriptor_digest(desc), "revision": desc["revision"],
            "worker_image": desc["worker_image"], "profile_digest": desc["profile_digest"]}


def retiring_launch(desc) -> dict:
    return {"pid": 100, "service": MANAGED_SYSTEMD_UNIT, "invocation_id": RETIRING_INVOCATION,
            "started_at": "2026-09-28T00:00:00+00:00", "descriptor_sha256": descriptor_digest(desc),
            "manifest_sha256": "f" * 64}


def new_launch(desc, *, started_at="2026-09-29T00:00:05+00:00") -> dict:
    return {**retiring_launch(desc), "pid": 200, "invocation_id": NEW_INVOCATION, "started_at": started_at}


def merged(base: dict, overrides: dict) -> dict:
    result = copy.deepcopy(base)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = {**result[key], **value}
        else:
            result[key] = value
    return result


def observation(desc, **overrides) -> dict:
    """The exact §3.1(a) observation of the running, idle, recorded retiring incumbent."""
    launch = retiring_launch(desc)
    base = {"schema": "urn:zeus:managed-generation-observation:1",
            "observed_at": "2026-09-29T00:00:00.500000+00:00", "running": True,
            "receipt": receipt_for(desc, RETIRING_INSTANCE), "receipt_present": True,
            "launch": launch, "launch_present": True, "launch_sha256": digest(launch),
            "launch_request_sha256": "a" * 64, "launch_request_requested_at": "2026-09-27T23:59:59+00:00",
            "target_file_matches": True, "control_user_matches": True,
            "unit": {"active_state": "active", "invocation_id": RETIRING_INVOCATION, "main_pid": 100,
                     "exec_main_pid": 100, "need_daemon_reload": False, "control_group_sha256": "c" * 64,
                     "environment_files_sha256": "d" * 64, "drop_in_count": 0},
            "supervisor": {"pid": 100, "state": "present", "start_ticks": 5000, "is_main_pid": True},
            "entry": {"pid": 101, "state": "present", "start_ticks": 5001, "parent_is_supervisor": True,
                      "in_unit_cgroup": True, "started_before_receipt": True},
            "work": {"state": "idle", "reason_code": None, "active": 0, "unresolved": 0}}
    result = merged(base, overrides)
    if "launch" in overrides and "launch_sha256" not in overrides:
        result["launch_sha256"] = None if result["launch"] is None else digest(result["launch"])
    return result


def stopped_observation(desc, **overrides) -> dict:
    """The retiring incumbent after its proven graceful stop: nothing runs, controller-state unchanged."""
    return observation(desc, **{"running": False,
                                "unit": {"active_state": "inactive", "invocation_id": None, "main_pid": None,
                                         "exec_main_pid": None, "control_group_sha256": None},
                                "supervisor": {"pid": None, "state": "absent", "start_ticks": None,
                                               "is_main_pid": None},
                                "entry": {"state": "absent", "start_ticks": None, "parent_is_supervisor": None,
                                          "in_unit_cgroup": None, "started_before_receipt": None},
                                "work": {"state": "unknown", "reason_code": "heartbeat_missing", "active": None,
                                         "unresolved": None}, **overrides})


def recognized_observation(desc, **overrides) -> dict:
    """The one launch bound to THIS request already happened: new controller-state, new invocation."""
    launch = new_launch(desc)
    return observation(desc, **{"launch": launch, "launch_request_requested_at": REQUESTED_AT,
                                "receipt": receipt_for(desc, NEW_INSTANCE, pid=201,
                                                       started_at="2026-09-29T00:00:06+00:00"),
                                "unit": {"invocation_id": NEW_INVOCATION, "main_pid": 200, "exec_main_pid": 200},
                                "supervisor": {"pid": 200}, "entry": {"pid": 201}, **overrides})


def restarts_for(desc, **overrides) -> dict:
    return {"maintenance_id": MAINTENANCE_ID, "instance_id": RETIRING_INSTANCE,
            "invocation_id": RETIRING_INVOCATION, "launch_sha256": digest(retiring_launch(desc)),
            "requested_at": REQUESTED_AT, **overrides}


class RecordingTarget(SystemdManagedFleetTarget):
    """LABELLED managed systemd target: every lifecycle step only records itself.

    `observations` is consumed one per `generation_observation` call (the last repeats); after a launch
    the next observation is `after_launch` when given, which is how a replay sees its own earlier start.
    """

    def __init__(self, observations, *, events=None, stop_result=None, stop_error=None, gate_errors=(),
                 target_file=(True,), launch_error=None, after_launch=None, legacy_observation=None):
        super().__init__(fleet=None, runner=self.no_systemctl, lock_timeout=0.3)
        self.events = [] if events is None else events
        self.observations = list(observations)
        self.stop_result = stop_result or {"stopped": True, "was_running": True, "pid": 100}
        self.stop_error, self.gate_errors = stop_error, list(gate_errors)
        self.target_file, self.launch_error = list(target_file), launch_error
        self.after_launch, self.legacy_observation = after_launch, legacy_observation
        self.launches = 0

    @staticmethod
    def no_systemctl(argv, **_):
        raise AssertionError("a fake target ran systemctl: " + repr(argv))

    def _prepare(self, target, descriptor):
        self.events.append("prepare")
        return {"manifest": {"labelled": True}}

    def _reconcile(self, target, descriptor):
        self.events.append("reconcile")

    def generation_observation(self, target):
        self.events.append("observe")
        return copy.deepcopy(self.observations[0] if len(self.observations) == 1 else self.observations.pop(0))

    def observe(self, target):
        self.events.append("legacy_observe")
        return copy.deepcopy(self.legacy_observation)

    def _activation_gate(self, target, descriptor):
        self.events.append("gate")
        error = self.gate_errors.pop(0) if self.gate_errors else None
        if error is not None:
            raise error

    def stop(self, target):
        self.events.append("stop")
        if self.stop_error is not None:
            raise self.stop_error
        return self.stop_result

    def _target_file_matches(self, target):
        self.events.append("target_file")
        return self.target_file.pop(0) if len(self.target_file) > 1 else self.target_file[0]

    def _retire(self, target):
        self.events.append("retire")

    def _launch(self, target, descriptor, context):
        self.events.append("launch")
        self.launches += 1
        if self.launch_error is not None:
            raise self.launch_error
        if self.after_launch is not None:
            self.observations = [self.after_launch]
        return {"started": True, "pid": 200, "launch": new_launch(descriptor)}

    def launch_record(self, target):
        self.events.append("launch_record")
        return new_launch(descriptor_for(target))


def authorizer(events, *, fail_on=None):
    calls = {"count": 0}

    def authorize():
        calls["count"] += 1
        events.append("authorize")
        if fail_on is not None and calls["count"] == fail_on:
            raise RuntimeError("fence lost (labelled)")
    return authorize


def effects(events) -> list:
    return [event for event in events if event in {"gate", "stop", "retire", "launch"}]


def refusal_of(excinfo) -> tuple:
    return excinfo.value.reason_code, excinfo.value.field


# ----- S2M-1: the legacy lifecycle is unchanged without a restart authority --------------------------
@pytest.mark.parametrize("explicit_none", [False, True])
def test_legacy_start_is_byte_for_byte_unchanged_without_restarts(tmp_path, explicit_none):
    target = managed_target(tmp_path)
    desc = descriptor_for(target)
    clean = {"receipt": None, "receipt_present": False, "launch": None, "launch_present": False, "running": False}
    host = RecordingTarget([observation(desc)], legacy_observation=clean)
    extra = {"restarts": None} if explicit_none else {}
    started = host.start(target, desc, authorize=authorizer(host.events), **extra)
    # The exact legacy sequence: guard, prepare, reconcile, classify, gate, stop, recheck, gate, retire, launch.
    assert host.events == ["authorize", "prepare", "reconcile", "legacy_observe", "gate", "stop", "authorize",
                           "gate", "retire", "launch"]
    assert started == {"started": True, "pid": 200, "launch": new_launch(desc)} and "path" not in started
    assert "observe" not in host.events and "target_file" not in host.events
    # A live instance running this descriptor is still RECOGNIZED by the legacy path, never replaced.
    intended = {"receipt": receipt_for(desc, RETIRING_INSTANCE), "receipt_present": True,
                "launch": retiring_launch(desc), "launch_present": True, "running": True}
    host = RecordingTarget([observation(desc)], legacy_observation=intended)
    again = host.start(target, desc, authorize=authorizer(host.events), **extra)
    assert again["started"] is False and again["recovered"] is True
    assert again["instance_id"] == RETIRING_INSTANCE and effects(host.events) == []
    assert "observe" not in host.events and not (Path(target["state_dir"]) / LOCK_DIR).exists()


# ----- S2M-5: only the recorded incumbent is replaced, once, gracefully ---------------------------------
def test_replace_path_only_for_the_matching_intended_incumbent(tmp_path):
    target = managed_target(tmp_path)
    desc = descriptor_for(target)
    host = RecordingTarget([observation(desc)])
    started = host.start(target, desc, authorize=authorizer(host.events), restarts=restarts_for(desc))
    assert host.events == ["authorize", "prepare", "reconcile", "observe", "gate", "stop", "authorize", "gate",
                           "target_file", "retire", "launch"]
    assert started == {"started": True, "pid": 200, "launch": new_launch(desc), "recovered": False,
                       "path": "replace"}
    assert host.events.count("stop") == 1 and host.launches == 1 and host.events.count("authorize") == 2
    assert not (Path(target["state_dir"]) / LOCK_DIR).exists()
    # The same host facts under a restart authority for ANOTHER incumbent replace nothing.
    for other, expected in ((restarts_for(desc, instance_id=NEW_INSTANCE), ("maintenance_invocation_mismatch",
                                                                            "instance_id")),
                            (restarts_for(desc, invocation_id=NEW_INVOCATION), ("maintenance_invocation_mismatch",
                                                                                "invocation_id")),
                            (restarts_for(desc, launch_sha256="0" * 64), ("maintenance_launch_unconfirmed",
                                                                          "launch"))):
        host = RecordingTarget([observation(desc)])
        with pytest.raises(DeliveryRefused) as refused:
            host.start(target, desc, authorize=authorizer(host.events), restarts=other)
        assert refusal_of(refused) == expected and effects(host.events) == [] and host.launches == 0


# ----- S2M-6: after a proved stop launch once; the request's own launch is recognized, never redone ------
def test_launch_after_proved_stop_and_recognized_own_launch_start_at_most_once(tmp_path):
    target = managed_target(tmp_path)
    desc = descriptor_for(target)
    # A replay after the stop's response was lost: the incumbent is proven gone, controller-state unchanged.
    host = RecordingTarget([stopped_observation(desc)], after_launch=recognized_observation(desc))
    first = host.start(target, desc, authorize=authorizer(host.events), restarts=restarts_for(desc))
    assert first["path"] == "launch" and first["started"] is True and first["recovered"] is False
    assert host.events == ["authorize", "prepare", "reconcile", "observe", "gate", "target_file", "retire", "launch"]
    # A replay after the launch's response was lost recognizes the request-bound launch: nothing starts.
    host.events.clear()
    second = host.start(target, desc, authorize=authorizer(host.events), restarts=restarts_for(desc))
    assert second == {"started": False, "recovered": True, "path": "recognized", "launch": new_launch(desc),
                      "pid": None}
    assert effects(host.events) == [] and host.launches == 1
    # An absent receipt beside a stopped unit is the same proven stop.
    host = RecordingTarget([stopped_observation(desc, receipt=None, receipt_present=False)])
    assert host.start(target, desc, restarts=restarts_for(desc))["path"] == "launch" and host.launches == 1
    # The whole replace -> lost response -> replay sequence launches exactly once.
    host = RecordingTarget([observation(desc)], after_launch=recognized_observation(desc))
    host.start(target, desc, restarts=restarts_for(desc))
    for _ in range(3):
        assert host.start(target, desc, restarts=restarts_for(desc))["path"] == "recognized"
    assert host.launches == 1 and host.events.count("stop") == 1


# ----- S2M-4: drift, N1, pid reuse, reload and target changes refuse before ANY effect ---------------------
def _cases(desc):
    changed_launch = new_launch(desc)
    return {
        "n1_new_invocation": (observation(desc, unit={"invocation_id": NEW_INVOCATION}),
                              ("maintenance_invocation_mismatch", "invocation_id")),
        "other_receipt_instance": (observation(desc, receipt=receipt_for(desc, NEW_INSTANCE)),
                                   ("maintenance_invocation_mismatch", "instance_id")),
        "pid_reuse": (observation(desc, entry={"started_before_receipt": False}),
                      ("maintenance_invocation_mismatch", "entry")),
        "wrong_parent": (observation(desc, entry={"parent_is_supervisor": False}),
                         ("maintenance_invocation_mismatch", "entry")),
        "other_cgroup": (observation(desc, entry={"in_unit_cgroup": None}),
                         ("maintenance_invocation_mismatch", "entry")),
        "supervisor_not_main": (observation(desc, supervisor={"is_main_pid": False}),
                                ("maintenance_invocation_mismatch", "supervisor")),
        "reload_pending": (observation(desc, unit={"need_daemon_reload": True}),
                           ("maintenance_reload_pending", "unit")),
        "reload_unknown": (observation(desc, unit={"need_daemon_reload": None}),
                           ("maintenance_reload_pending", "unit")),
        "target_file_drift": (observation(desc, target_file_matches=False), ("maintenance_stale", "target_file")),
        "service_user": (observation(desc, control_user_matches=None), ("maintenance_invalid", "service_user")),
        "liveness_unknown": (observation(desc, running=None), ("maintenance_launch_unconfirmed", "running")),
        "work_busy": (observation(desc, work={"state": "busy", "reason_code": "work_active", "active": 1}),
                      ("maintenance_debt_unsettled", "work")),
        "stopped_but_other_invocation_active": (
            stopped_observation(desc, unit={"active_state": "active", "invocation_id": NEW_INVOCATION}),
            ("maintenance_invocation_mismatch", "instance_id")),
        "changed_launch_before_request": (
            recognized_observation(desc, launch=new_launch(desc, started_at="2026-09-28T23:00:00+00:00")),
            ("maintenance_launch_unconfirmed", "launch")),
        "changed_launch_not_running_it": (
            recognized_observation(desc, unit={"invocation_id": RETIRING_INVOCATION}),
            ("maintenance_launch_unconfirmed", "launch")),
        "changed_launch_request_outside_window": (
            recognized_observation(desc, launch_request_requested_at="2026-09-28T12:00:00+00:00"),
            ("maintenance_launch_unconfirmed", "launch")),
        # S2R F1: a launch request inside the old window but not THIS request's own time is not this attempt.
        "changed_launch_request_not_this_attempt": (
            recognized_observation(desc, launch_request_requested_at="2026-09-29T00:00:03+00:00"),
            ("maintenance_launch_unconfirmed", "launch")),
        "changed_launch_foreign_descriptor": (
            recognized_observation(desc, launch={**changed_launch, "descriptor_sha256": "0" * 64}),
            ("maintenance_launch_unconfirmed", "launch")),
        "extra_observation_key": ({**observation(desc), "environment": {"TOKEN": "x"}},
                                  ("maintenance_invocation_mismatch", "observation")),
    }


@pytest.mark.parametrize("case", sorted(_cases({"schema": DESCRIPTOR_SCHEMA, "target_id": "managed-fleet",
                                                "root": "/labelled", "revision": REVISION, "worker_image": IMAGE,
                                                "profile_digest": "e" * 64, "predecessor": None})))
def test_n1_pid_reuse_reload_and_target_drift_refuse_before_any_effect(tmp_path, case):
    target = managed_target(tmp_path)
    desc = descriptor_for(target)
    observed, expected = _cases(desc)[case]
    host = RecordingTarget([observed])
    with pytest.raises(DeliveryRefused) as refused:
        host.start(target, desc, authorize=authorizer(host.events), restarts=restarts_for(desc))
    assert refusal_of(refused) == expected
    assert effects(host.events) == [] and host.launches == 0
    state = Path(target["state_dir"])
    assert not (state / LOCK_DIR).exists() and list(state.iterdir()) == []


def test_malformed_authority_or_unreadable_observation_refuses_before_any_effect(tmp_path):
    target = managed_target(tmp_path)
    desc = descriptor_for(target)
    for restarts, expected in ((restarts_for(desc, requested_at="yesterday"), ("maintenance_invalid", "restarts")),
                               ({**restarts_for(desc), "token": "x"}, ("maintenance_invalid", "restarts")),
                               (restarts_for(desc, maintenance_id="active_generation_2:" + "9" * 64),
                                ("maintenance_invalid", "restarts"))):
        host = RecordingTarget([observation(desc)])
        with pytest.raises(DeliveryRefused) as refused:
            host.start(target, desc, restarts=restarts)
        assert refusal_of(refused) == expected and effects(host.events) == []

    class Unobservable(RecordingTarget):
        def generation_observation(self, target):
            self.events.append("observe")
            raise RuntimeError("SENTINEL host detail that must not surface")
    host = Unobservable([observation(desc)])
    with pytest.raises(DeliveryRefused) as refused:
        host.start(target, desc, restarts=restarts_for(desc))
    assert refusal_of(refused) == ("maintenance_invocation_mismatch", "observation")
    assert "SENTINEL" not in str(refused.value) and effects(host.events) == []


# ----- S2M-3: only the systemd-supervised managed target accepts a restart authority ---------------------
def test_non_systemd_kinds_refuse_restart_authority(tmp_path):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("a host command ran")
    hosts = [(ProcessHostTarget(), plain_target(tmp_path / "p", KIND_PROCESS)),
             (SystemdHostTarget(runner=forbidden, control_dir=str(tmp_path)),
              plain_target(tmp_path / "d", KIND_SYSTEMD)),
             (ManagedFleetTarget(fleet=None), managed_target(tmp_path / "m", kind=KIND_MANAGED))]
    for host, target in hosts:
        desc = descriptor_for(target)
        with pytest.raises(DeliveryRefused) as refused:
            host.start(target, desc, authorize=forbidden, restarts=restarts_for(desc))
        assert refusal_of(refused) == ("maintenance_not_active", "target_id")
        with pytest.raises(DeliveryRefused) as observed:
            host.generation_observation(target)
        assert refusal_of(observed) == ("maintenance_not_active", "target_id")
        # Refused before the guard: no lock and no state directory was even created.
        assert not Path(target["state_dir"]).exists()
    assert HostTargetBase()._target_file_matches({}) is True


# ----- S2M-6: a loss after the stop is an interrupted lifecycle, never a refusal or a second start ----------
def test_ownership_loss_or_gate_refusal_after_stop_is_an_interrupted_lifecycle(tmp_path):
    target = managed_target(tmp_path)
    desc = descriptor_for(target)

    def run(host, fail_on=None):
        return host.start(target, desc, authorize=authorizer(host.events, fail_on=fail_on),
                          restarts=restarts_for(desc))

    # The fence is lost during the bounded stop: the stop happened, nothing is retired or launched.
    host = RecordingTarget([observation(desc)])
    with pytest.raises(LifecycleInterrupted) as lost:
        run(host, fail_on=2)
    assert lost.value.effect == "service_stopped" and effects(host.events) == ["gate", "stop"]
    # The second gate (debt appeared) or a changed target file after the stop: interrupted, not refused.
    for host, cause in ((RecordingTarget([observation(desc)], gate_errors=[None, DeliveryRefused("fleet_debt_held",
                                                                                                 "fleet")]),
                         ("fleet_debt_held", "fleet")),
                        (RecordingTarget([observation(desc)], target_file=[False]),
                         ("maintenance_stale", "target_file"))):
        with pytest.raises(LifecycleInterrupted) as interrupted:
            run(host)
        assert interrupted.value.effect == "service_stopped"
        assert (interrupted.value.cause.reason_code, interrupted.value.cause.field) == cause
        assert "retire" not in host.events and host.launches == 0 and host.events.count("stop") == 1
    # A stop refused for busy work leaves the incumbent running: a refusal naming why, nothing else.
    host = RecordingTarget([observation(desc)], stop_result={"stopped": False, "was_running": True,
                                                             "reason_code": "instance_work_busy"})
    with pytest.raises(DeliveryRefused) as busy:
        run(host)
    assert refusal_of(busy) == ("instance_work_busy", "target_id") and effects(host.events) == ["gate", "stop"]
    # A stop that raised, or a start whose outcome is unknown, is interrupted and never retried here.
    host = RecordingTarget([observation(desc)], stop_error=RuntimeError("managed unit state unavailable"))
    with pytest.raises(LifecycleInterrupted) as unknown_stop:
        run(host)
    assert unknown_stop.value.effect == "service_stop_unconfirmed" and host.launches == 0
    host = RecordingTarget([observation(desc)], launch_error=RuntimeError("managed unit could not be started"))
    with pytest.raises(LifecycleInterrupted) as unknown_start:
        run(host)
    assert unknown_start.value.effect == "service_stopped" and host.launches == 1
    host = RecordingTarget([stopped_observation(desc)], launch_error=RuntimeError("start timed out"))
    with pytest.raises(LifecycleInterrupted) as unconfirmed:
        run(host)
    assert unconfirmed.value.effect == "service_start_unconfirmed" and host.launches == 1
    # Before any stop the same refusals are plain refusals: nothing was changed yet.
    host = RecordingTarget([observation(desc)], gate_errors=[DeliveryRefused("fleet_pause_unknown", "fleet")])
    with pytest.raises(DeliveryRefused) as first_gate:
        run(host)
    assert refusal_of(first_gate) == ("fleet_pause_unknown", "fleet") and "stop" not in host.events
    host = RecordingTarget([stopped_observation(desc)], target_file=[False])
    with pytest.raises(DeliveryRefused) as drifted:
        run(host)
    assert refusal_of(drifted) == ("maintenance_stale", "target_file") and "retire" not in host.events


# ----- S2M-4 / S2M-17: the managed observation is bounded, safe and read-only -----------------------------------
class UnitShow:
    """LABELLED `systemctl show` of the owner-fixed unit; records every argv and answers `show` only."""

    def __init__(self, **values):
        self.calls, self.returncode, self.error = [], 0, None
        self.values = {"ActiveState": "active", "MainPID": "100", "ExecMainPID": "100",
                       "InvocationID": RETIRING_INVOCATION, "NeedDaemonReload": "no", "ControlGroup": SENTINEL_GROUP,
                       "EnvironmentFiles": list(SENTINEL_ENV_FILES), "DropInPaths": SENTINEL_DROP_INS, **values}

    def __call__(self, argv, timeout=None, **_):
        self.calls.append(list(argv))
        assert argv[:3] == ["systemctl", "show", UNIT], argv
        if self.error is not None:
            raise self.error
        lines = []
        for key, value in self.values.items():
            for item in (value if isinstance(value, list) else [value]):
                if item is not None:
                    lines.append(key + "=" + item)
        return SimpleNamespace(returncode=self.returncode, stdout="\n".join(lines) + "\n", stderr="")


def processes(receipt_started_at: str, overrides=None):
    """LABELLED `/proc` reader: the supervisor 100 and its entry 101 in the unit's control group."""
    now_mono = time.monotonic_ns() // 1000
    started = datetime.fromisoformat(receipt_started_at)
    wall_now = datetime.now(timezone.utc)
    entry_start = now_mono - int((wall_now - started).total_seconds() * 1_000_000) - 500_000
    table = {100: {"pid": 100, "state": "present", "start_ticks": 5000, "start_usec": entry_start - 100,
                   "ppid": 1, "cgroup": SENTINEL_GROUP, "argv_sha256": "1" * 64},
             101: {"pid": 101, "state": "present", "start_ticks": 5001, "start_usec": entry_start,
                   "ppid": 100, "cgroup": SENTINEL_GROUP, "argv_sha256": "2" * 64}}
    for pid, change in (overrides or {}).items():
        # A bare `{pid, state}` replaces the entry (another state); anything else amends its facts.
        table[pid] = change if set(change) <= {"pid", "state"} else {**table[pid], **change}
    reads = []

    def read(pid):
        reads.append(pid)
        answer = table.get(pid)
        if answer is None:
            return {"pid": pid, "state": "absent"}
        if answer.get("state") == "raise":
            raise OSError("unreadable proc (labelled)")
        return dict(answer)
    read.reads = reads
    return read


def live_state(tmp_path, *, heartbeat=True):
    """A disposable state directory as the running incumbent left it (files only; nothing runs)."""
    target = managed_target(tmp_path)
    desc = descriptor_for(target)
    state = Path(target["state_dir"])
    state.mkdir(parents=True)
    started_at = (datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat()
    receipt = receipt_for(desc, RETIRING_INSTANCE, started_at=started_at)
    launch = retiring_launch(desc)
    request = {"schema": LAUNCH_REQUEST_SCHEMA, "target_id": target["target_id"],
               "descriptor_sha256": descriptor_digest(desc), "manifest_sha256": "f" * 64, "workload": "fleet",
               "requested_at": "2026-09-27T23:59:59+00:00"}
    for name, document in ((RECEIPT_FILE, receipt), (STATE_FILE, launch), (LAUNCH_REQUEST_FILE, request)):
        (state / name).write_text(json.dumps(document, sort_keys=True), encoding="utf-8")
    (state / TARGET_FILE).write_bytes(json.dumps(owner_target(target), sort_keys=True).encode("utf-8"))
    if heartbeat:
        (state / HEARTBEAT_FILE).write_text(json.dumps({
            "schema": HEARTBEAT_SCHEMA, "instance_id": RETIRING_INSTANCE, "descriptor_sha256": descriptor_digest(desc),
            "pid": receipt["pid"], "at": datetime.now(timezone.utc).isoformat(), "admission": "open",
            "active": 0, "unresolved": 0}), encoding="utf-8")
    return target, desc, receipt, launch, request


def snapshot(directory: Path) -> dict:
    """Every entry's inode, mtime and (for a regular file) bytes, without following links."""
    return {path.name: (path.lstat().st_ino, path.lstat().st_mtime_ns,
                        path.read_bytes() if path.is_file() and not path.is_symlink() else None)
            for path in sorted(directory.iterdir())}


def test_generation_observation_parses_bounded_safe_facts(tmp_path):
    target, desc, receipt, launch, request = live_state(tmp_path)
    show = UnitShow()
    host = SystemdManagedFleetTarget(fleet=None, runner=show, process_reader=processes(receipt["started_at"]))
    before = snapshot(Path(target["state_dir"]))
    observed = host.generation_observation(target)
    assert snapshot(Path(target["state_dir"])) == before, "the observation wrote, touched or created something"
    assert observed["schema"] == "urn:zeus:managed-generation-observation:1"
    assert observed["running"] is True and observed["receipt"] == receipt and observed["receipt_present"] is True
    assert observed["launch"] == launch and observed["launch_sha256"] == digest(launch)
    assert observed["launch_request_sha256"] == digest(request)
    assert observed["launch_request_requested_at"] == request["requested_at"]
    assert observed["target_file_matches"] is True and observed["control_user_matches"] is True
    assert observed["unit"] == {
        "active_state": "active", "invocation_id": RETIRING_INVOCATION, "main_pid": 100, "exec_main_pid": 100,
        "need_daemon_reload": False, "control_group_sha256": hashlib.sha256(SENTINEL_GROUP.encode()).hexdigest(),
        "environment_files_sha256": hashlib.sha256("\n".join(SENTINEL_ENV_FILES).encode()).hexdigest(),
        "drop_in_count": 2}
    assert observed["supervisor"] == {"pid": 100, "state": "present", "start_ticks": 5000, "is_main_pid": True}
    assert observed["entry"] == {"pid": 101, "state": "present", "start_ticks": 5001, "parent_is_supervisor": True,
                                 "in_unit_cgroup": True, "started_before_receipt": True}
    assert observed["work"] == {"state": "idle", "reason_code": None, "active": 0, "unresolved": 0}
    # The ONE additional read is the fixed property set; every other systemctl argv is the incumbent `show`.
    extended = [argv for argv in show.calls if "NeedDaemonReload" in argv]
    assert extended == [["systemctl", "show", UNIT] + [part for name in GENERATION_UNIT_PROPERTIES
                                                       for part in ("-p", name)]]
    assert all(argv[1] == "show" for argv in show.calls)
    # The domain policy accepts it as data and classifies it as the replaceable incumbent.
    policy.validate_generation_observation(observed)
    decision = policy.classify_restart(desc, observed, {**restarts_for(desc), "launch_sha256": digest(launch)})
    assert decision["path"] == "replace", decision
    # No raw unit path, environment file name or drop-in path leaves the adapter.
    text = json.dumps(observed)
    assert "SENTINEL" not in text and str(tmp_path / "state") not in text


@pytest.mark.parametrize("variant", ["reload_yes", "reload_other", "invocation_empty", "main_pid_zero",
                                     "show_fails", "show_raises", "pid_reuse", "other_parent", "other_cgroup",
                                     "entry_replaced", "proc_unreadable", "no_heartbeat", "dup_drop_ins",
                                     "no_receipt", "one_env_file", "bad_request_time"])
def test_generation_observation_variants_stay_typed_and_never_raise(tmp_path, variant):
    target, desc, receipt, launch, request = live_state(tmp_path, heartbeat=variant != "no_heartbeat")
    show = UnitShow()
    overrides = {}
    if variant == "reload_yes":
        show.values["NeedDaemonReload"] = "yes"
    elif variant == "reload_other":
        show.values["NeedDaemonReload"] = "maybe"
    elif variant == "invocation_empty":
        show.values["InvocationID"] = ""
    elif variant == "main_pid_zero":
        show.values.update(MainPID="0", ExecMainPID="0")
    elif variant == "show_fails":
        show.returncode = 1
    elif variant == "show_raises":
        show.error = RuntimeError("systemctl unavailable (labelled)")
    elif variant == "pid_reuse":
        overrides[101] = {"start_usec": time.monotonic_ns() // 1000}  # started NOW, after the receipt
    elif variant == "other_parent":
        overrides[101] = {"ppid": 4242}
    elif variant == "other_cgroup":
        overrides[101] = {"cgroup": "/user.slice/other.scope"}
    elif variant == "entry_replaced":
        overrides[101] = {"pid": 101, "state": "replaced"}
    elif variant == "proc_unreadable":
        overrides[100] = {"pid": 100, "state": "raise"}
        overrides[101] = {"pid": 101, "state": "raise"}
    elif variant == "dup_drop_ins":
        show.values["DropInPaths"] = ["/a.conf", "/b.conf"]
    elif variant == "no_receipt":
        (Path(target["state_dir"]) / RECEIPT_FILE).unlink()
    elif variant == "one_env_file":
        show.values["EnvironmentFiles"] = SENTINEL_ENV_FILES[:1]
    elif variant == "bad_request_time":
        (Path(target["state_dir"]) / LAUNCH_REQUEST_FILE).write_text(
            json.dumps({**request, "requested_at": "not a time"}), encoding="utf-8")
    host = SystemdManagedFleetTarget(fleet=None, runner=show,
                                     process_reader=processes(receipt["started_at"], overrides))
    observed = host.generation_observation(target)
    unit, supervisor, entry = observed["unit"], observed["supervisor"], observed["entry"]
    expected = {
        "reload_yes": lambda: unit["need_daemon_reload"] is True,
        "reload_other": lambda: unit["need_daemon_reload"] is None,
        "invocation_empty": lambda: unit["invocation_id"] is None,
        "main_pid_zero": lambda: (unit["main_pid"], unit["exec_main_pid"], supervisor["state"],
                                  supervisor["is_main_pid"], entry["parent_is_supervisor"]) == (
                                      None, None, "absent", None, None),
        "show_fails": lambda: all(value is None for value in unit.values()) and supervisor["state"] == "unknown",
        "show_raises": lambda: (all(value is None for value in unit.values()) and supervisor["state"] == "unknown"
                                and observed["running"] is None),
        "pid_reuse": lambda: entry["started_before_receipt"] is False,
        "other_parent": lambda: entry["parent_is_supervisor"] is False,
        "other_cgroup": lambda: entry["in_unit_cgroup"] is False,
        "entry_replaced": lambda: entry["state"] == "replaced" and all(
            entry[flag] is None for flag in ("parent_is_supervisor", "in_unit_cgroup", "started_before_receipt")),
        "proc_unreadable": lambda: supervisor["state"] == entry["state"] == "unknown"
        and supervisor["start_ticks"] is None and entry["started_before_receipt"] is None,
        "no_heartbeat": lambda: observed["work"] == {"state": "unknown", "reason_code": "heartbeat_missing",
                                                     "active": None, "unresolved": None},
        "dup_drop_ins": lambda: unit["drop_in_count"] is None,
        "no_receipt": lambda: (observed["receipt"], observed["receipt_present"], entry["pid"], entry["state"]) == (
            None, False, None, "absent"),
        "one_env_file": lambda: unit["environment_files_sha256"] == hashlib.sha256(
            SENTINEL_ENV_FILES[0].encode()).hexdigest(),
        "bad_request_time": lambda: observed["launch_request_requested_at"] is None
        and observed["launch_request_sha256"] is not None,
    }[variant]
    assert expected(), observed
    policy.validate_generation_observation(observed)
    assert "SENTINEL" not in json.dumps(observed)


# ----- S2M-18: an identical owner target snapshot is never rewritten; a differing one refuses maintenance ---------
def test_identical_target_file_is_never_rewritten_and_a_differing_one_is_refused_under_maintenance(tmp_path):
    target, desc, receipt, launch, _ = live_state(tmp_path)
    path = Path(target["state_dir"]) / TARGET_FILE
    old = time.time_ns() - 3_600_000_000_000
    os.utime(path, ns=(old, old))
    identity = (path.stat().st_ino, path.stat().st_mtime_ns, path.read_bytes())
    host = ManagedFleetTarget(fleet=None)
    assert host._target_file_matches(target) is True
    host._write_owner_target(target)
    assert (path.stat().st_ino, path.stat().st_mtime_ns, path.read_bytes()) == identity
    # The systemd `_launch` itself leaves the identical snapshot alone (and still starts the unit once).
    started = []

    def systemctl(argv, timeout=None, **_):
        started.append(argv[1])
        stdout = "ActiveState=active\nMainPID=300\nInvocationID=" + NEW_INVOCATION + "\n"
        return SimpleNamespace(returncode=0, stdout=stdout, stderr="")
    systemd = SystemdManagedFleetTarget(fleet=None, runner=systemctl)
    systemd._launch(target, desc, {"manifest": {"labelled": "manifest"}})
    assert started == ["start", "show"]
    assert (path.stat().st_ino, path.stat().st_mtime_ns, path.read_bytes()) == identity
    # A differing snapshot refuses the maintenance restart BEFORE any effect, and is not touched.
    path.write_bytes(identity[2] + b" ")
    os.utime(path, ns=(old, old))
    differing = (path.stat().st_ino, path.stat().st_mtime_ns, path.read_bytes())

    class Observed(RecordingTarget):
        def generation_observation(self, target):
            self.events.append("observe")
            return observation(desc, target_file_matches=SystemdManagedFleetTarget._target_file_matches(self, target))

        def _target_file_matches(self, target):
            self.events.append("target_file")
            return SystemdManagedFleetTarget._target_file_matches(self, target)
    maintained = Observed([observation(desc)])
    with pytest.raises(DeliveryRefused) as refused:
        maintained.start(target, desc, restarts=restarts_for(desc))
    assert refusal_of(refused) == ("maintenance_stale", "target_file") and effects(maintained.events) == []
    assert (path.stat().st_ino, path.stat().st_mtime_ns, path.read_bytes()) == differing
    # A link in its place is not the snapshot either, and is never followed.
    link = Path(target["state_dir"]) / "elsewhere.json"
    link.write_bytes(identity[2])
    path.unlink()
    path.symlink_to(link)
    assert host._target_file_matches(target) is False
    # Outside maintenance the legacy launch still replaces a differing or linked snapshot atomically.
    host._write_owner_target(target)
    assert not path.is_symlink() and path.read_bytes() == identity[2]
    path.write_bytes(b"{}")
    host._write_owner_target(target)
    assert path.read_bytes() == identity[2]


# ----- S2M-14: the owner canary files are read bounded and never written ---------------------------------------------
def test_owner_canary_reads_are_bounded_and_read_only(tmp_path):
    target = managed_target(tmp_path)
    host = SystemdManagedFleetTarget(fleet=None, runner=RecordingTarget.no_systemctl)
    state = Path(target["state_dir"])
    # Nothing there: None, and the state directory is not even created.
    assert host.owner_canary(target, "plan-1") is None and host.owner_canary_request(target, "plan-1") is None
    assert not state.exists()
    state.mkdir()
    receipt = {"schema": "urn:zeus:owner-canary-receipt:1", "passed": True}
    (state / canary_receipt_file("plan-1")).write_text(json.dumps(receipt), encoding="utf-8")
    (state / canary_request_file("plan-1")).write_text(json.dumps({"requested": True}), encoding="utf-8")
    assert host.owner_canary(target, "plan-1") == receipt
    assert host.owner_canary_request(target, "plan-1") == {"requested": True}
    # Another plan's files are never read for this plan.
    assert host.owner_canary(target, "plan-2") is None
    for body in (b"[1, 2]", b"{not json", b"\"passed\"", b"{" + b" " * (70 * 1024) + b"}"):
        (state / canary_receipt_file("plan-3")).write_bytes(body)
        assert host.owner_canary(target, "plan-3") == {"unreadable": True}
    (state / canary_receipt_file("plan-4")).symlink_to(state / canary_receipt_file("plan-1"))
    assert host.owner_canary(target, "plan-4") == {"unreadable": True}
    (state / canary_request_file("plan-5")).mkdir()
    assert host.owner_canary_request(target, "plan-5") == {"unreadable": True}
    before = snapshot(state)
    for _ in range(2):
        host.owner_canary(target, "plan-1"), host.owner_canary_request(target, "plan-1")
    assert snapshot(state) == before
    with pytest.raises(DeliveryRefused) as invalid:
        host.owner_canary(target, "../plan")
    assert refusal_of(invalid) == ("maintenance_invalid", "plan_id")


# ----- S2R F1 (Codex round 1): a start whose outcome is unproven is held and never launched a second time -------
class LaunchRunner(UnitShow):
    """LABELLED `systemctl` for the REAL `SystemdManagedFleetTarget._launch` boundary: `start` takes effect (or its
    outcome is unknown: it raises), and the `show` that follows may lose its response. Records every argv."""

    def __init__(self, *, start_error=None, show_error=None, **values):
        super().__init__(**values)
        self.start_error, self.show_error, self.starts = start_error, show_error, 0

    def __call__(self, argv, timeout=None, **_):
        if argv[:2] == ["systemctl", "start"]:
            self.calls.append(list(argv))
            self.starts += 1
            if self.start_error is not None:
                raise self.start_error
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if self.show_error is not None:
            self.calls.append(list(argv))
            raise self.show_error
        return super().__call__(argv, timeout=timeout)


@pytest.mark.parametrize("fault", ["show lost after the start took effect", "start outcome unknown"])
def test_the_real_launch_persists_this_requests_launch_request_before_its_one_start(tmp_path, fault):
    target, desc, receipt, launch, request = live_state(tmp_path)
    state = Path(target["state_dir"])
    (state / RECEIPT_FILE).unlink()                       # `_retire` retired the incumbent's receipt
    lost = TimeoutError("response lost (labelled injected fault)")
    runner = LaunchRunner(start_error=lost if fault == "start outcome unknown" else None,
                          show_error=None if fault == "start outcome unknown" else lost)
    host = SystemdManagedFleetTarget(fleet=None, runner=runner, process_reader=processes(receipt["started_at"]))
    with pytest.raises(Exception):
        host._launch(target, desc, {"manifest": {"id": "labelled-manifest"}, "requested_at": REQUESTED_AT})
    assert runner.starts == 1
    written = json.loads((state / LAUNCH_REQUEST_FILE).read_text(encoding="utf-8"))
    assert written["requested_at"] == REQUESTED_AT and written["requested_at"] != request["requested_at"]
    # The controller-state is still the retiring launch: nothing recorded the unproven start.
    assert json.loads((state / STATE_FILE).read_text(encoding="utf-8")) == launch
    # Without a maintenance request time every other launch is stamped now, exactly as before.
    other = LaunchRunner()
    SystemdManagedFleetTarget(fleet=None, runner=other)._launch(target, desc, {"manifest": {"id": "labelled"}})
    assert json.loads((state / LAUNCH_REQUEST_FILE).read_text(encoding="utf-8"))["requested_at"] > REQUESTED_AT


def unconfirmed_after_lost_start(desc, **overrides) -> dict:
    """What a replay observes after the one start took effect but nothing recorded it and the new generation
    exited before any receipt: the retiring controller-state, no receipt, a stopped unit with no invocation, and
    the launch request of THIS attempt (its time is the request's own)."""
    return stopped_observation(desc, **{"receipt": None, "receipt_present": False,
                                        "launch_request_requested_at": REQUESTED_AT,
                                        "launch_request_sha256": "e" * 64, **overrides})


@pytest.mark.parametrize("request_at", [REQUESTED_AT, "2026-09-29T00:00:05+00:00", None])
def test_a_replay_after_an_unconfirmed_start_is_held_and_launches_nothing(tmp_path, request_at):
    target = managed_target(tmp_path)
    desc = descriptor_for(target)
    overrides = {"launch_request_requested_at": request_at}
    if request_at is None:
        overrides["launch_request_sha256"] = None
    host = RecordingTarget([unconfirmed_after_lost_start(desc, **overrides)])
    with pytest.raises(DeliveryRefused) as held:
        host.start(target, desc, authorize=authorizer(host.events), restarts=restarts_for(desc))
    assert (held.value.reason_code, held.value.field) == ("maintenance_launch_unconfirmed", "launch")
    assert host.launches == 0 and effects(host.events) == []
    # The positive control stays: stopped before the launch (the incumbent's own older request) launches once.
    control = RecordingTarget([unconfirmed_after_lost_start(desc, launch_request_requested_at="2026-09-27T23:59:59+00:00")])
    assert control.start(target, desc, restarts=restarts_for(desc))["path"] == "launch" and control.launches == 1
