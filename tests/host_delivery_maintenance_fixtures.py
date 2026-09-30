"""LABELLED fixtures for INV-HOST-DELIVERY-MAINTENANCE-001 (helper module; not collected).

Real: `HostDelivery` (registry, register, the ordinary ticks to ACTIVE, the maintenance phases), `Releases`,
`ReleaseQueue` (including its maintenance hold), the owner canary check `owner_qualified_canary`, the owner
canary receipt/request files and the startup receipt as real JSON files in a temporary state directory.
LABELLED fakes: the GitHub port (`test_host_delivery.FakeGitHub`), the managed systemd host
(`FakeManagedHost`: no process, no unit, no signal; it simulates one unit, its supervisor and entry), the
trusted authority store and the artifact store. The Fleet is the REAL one, registered and owner-paused over the
SAME control store owner-actions uses; the restart phase reads only its `maintenance_readiness`
(ALL-PRIMARY-20260930: arm and bind are PR-3's remainder).
No model, provider, network, live service, real systemd unit, secret or production store is touched.

`LinkedStores` models the one PostgreSQL advisory lock every store takes: opening ANY transaction while
another one (on either store) is open in the same thread raises, so a cross-store nesting deadlock is an
immediate failure here instead of a `lock_timeout` in production.
"""
from __future__ import annotations

import copy
import hashlib
import json
import threading
from contextlib import contextmanager
from pathlib import Path

from test_fleet import config as fleet_config
from test_host_delivery import (
    FIXTURE_IMAGE,
    FIXTURE_PROFILE,
    Clock,
    FakeGitHub,
    pin,
    plan_document,
    reviewed_release,
)

from codex_harness.adapters.host_delivery import (
    DESCRIPTOR_FILE,
    RECEIPT_FILE,
    STATE_FILE,
    canary_receipt_file,
    canary_request_file,
    owner_qualified_canary,
    startup_identity_canary,
)
from codex_harness.adapters.store import MemoryStore
from codex_harness.application.fleet import (
    ACTIVATION_HOLD,
    BUCKET_CONTROL,
    BUCKET_UNITS,
    CONTROL_KEY,
    Fleet,
)
from codex_harness.application.host_delivery import (
    BUCKET_DESCRIPTORS,
    BUCKET_INTENTS,
    BUCKET_PLANS,
    HostDelivery,
)
from codex_harness.bootstrap import organization
from codex_harness.domain import owner_actions as do
from codex_harness.domain.host_delivery import (
    ACTIVE,
    AWAITING_CONSUMPTION,
    CANARY_FLEET,
    CANARY_REQUEST_SCHEMA,
    CANARY_STARTUP,
    GENERATION_OBSERVATION_SCHEMA,
    KIND_MANAGED_SYSTEMD,
    MAINTENANCE_KIND,
    MAINTENANCE_REASON,
    MAINTENANCE_SCHEMA,
    MANAGED_SYSTEMD_UNIT,
    OWNER_CANARY_RECEIPT_SCHEMA,
    RECEIPT_SCHEMA,
    REGISTRY_SCHEMA,
    RESTART_RECOGNIZED,
    DeliveryRefused,
    LifecycleInterrupted,
    classify_restart,
    consumption_verdict,
    descriptor_digest,
    plan_digest,
    validate_descriptor,
    validate_plan,
)
from codex_harness.domain.model import ContractError, digest

TARGET = "fleet-host"
PLAN_ID = "maintained-plan"
DESCRIPTOR_REVISION = "2" * 40
AUTHORITY_BYTES = b"LABELLED fixture: the recorded user directive for the S2 same-descriptor maintenance\n"
AUTHORITY_REF = "sha256:" + hashlib.sha256(AUTHORITY_BYTES).hexdigest()
SENTINEL = "SENTINEL-must-never-leak"
BUCKET_ACTIONS = "owner_actions"
BUCKET_JOBS = "fleet_jobs"


class Crash(BaseException):
    """LABELLED injected process death: it bypasses every `except Exception` like a killed controller."""


# ----- the stores ------------------------------------------------------------------------------------------
class LinkedStore:
    """One MemoryStore whose transactions share the ONE (per-thread) depth of its `LinkedStores` group."""

    def __init__(self, group, name: str):
        self.inner, self.group, self.name, self.transactions = MemoryStore(), group, name, 0

    @property
    def data(self):
        return self.inner.data

    @contextmanager
    def transaction(self, **_kwargs):
        local = self.group.local
        if getattr(local, "depth", 0):
            raise AssertionError("nested store transaction")
        local.depth = 1
        self.transactions += 1
        try:
            with self.inner.transaction() as tx:
                yield tx
        finally:
            local.depth = 0


class LinkedStores:
    def __init__(self):
        self.local = threading.local()
        self.lane, self.control = LinkedStore(self, "lane"), LinkedStore(self, "control")


def snapshot(*stores) -> list:
    return [copy.deepcopy(store.data) for store in stores]


def read(store, bucket, key):
    with store.transaction() as tx:
        return copy.deepcopy(tx.get(bucket, key))


def put(store, bucket, key, value):
    with store.transaction() as tx:
        tx.put(bucket, key, value)


def _write(path: Path, document) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, sort_keys=True), encoding="utf-8")


def _read(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


# ----- the managed systemd host ------------------------------------------------------------------------------
class FakeManagedHost:
    """LABELLED fake `managed_fleet_systemd` host port: one simulated unit, its supervisor and its entry.

    Descriptor, startup receipt, controller-state, launch request and owner canary files are REAL files in
    the target's temporary state directory, so `owner_qualified_canary`, `TargetFiles` and owner-actions
    read them unchanged. `start(restarts=)` calls `authorize()`, then the REAL domain `classify_restart`,
    and simulates exactly the path it selects. `calls` records ("gate",), ("stop",), ("retire",) and
    ("launch", invocation); it never records or sends a signal."""

    kind = KIND_MANAGED_SYSTEMD

    def __init__(self, clock):
        self.clock, self.calls, self.counter = clock, [], 0
        self.alive, self.active_state, self.invocation = False, "inactive", None
        self.supervisor = self.entry = None           # {"pid", "start_ticks"} of the simulated processes
        self.need_reload, self.target_file, self.control_user = False, True, True
        self.supervisor_main = True
        self.entry_flags = {"parent_is_supervisor": True, "in_unit_cgroup": True, "started_before_receipt": True}
        self.work = {"state": "idle", "reason_code": None, "active": 0, "unresolved": 0}
        self.environment_sha256, self.drop_ins = "e" * 64, 1
        self.running_unknown = False
        self.receipt_delay, self.pending_receipt = 0, None
        # LABELLED fault knobs
        self.crash_after_stop = False
        self.raise_after_launch = 0
        self.after_stop = None        # a hook run right after the graceful stop (e.g. steal the lease)
        self.on_start = None          # a hook run at the very start of `start(restarts=)`
        self.observe_error = None

    # --- files ---
    @staticmethod
    def path(target, name) -> Path:
        return Path(target["state_dir"]) / name

    def current(self, target):
        document = _read(self.path(target, DESCRIPTOR_FILE))
        try:
            return validate_descriptor(document) if document is not None else None
        except DeliveryRefused:
            return None

    def receipt(self, target):
        return _read(self.path(target, RECEIPT_FILE))

    def launch_record(self, target):
        return _read(self.path(target, STATE_FILE))

    def launch_request(self, target):
        return _read(self.path(target, "managed-launch.json"))

    def running(self, target):
        return self.alive

    def identity(self, target):
        receipt = self.receipt(target)
        current = self.current(target)
        return {"descriptor_sha256": None if current is None else descriptor_digest(current),
                "instance_id": (receipt or {}).get("instance_id"), "receipt": "valid" if receipt else "absent",
                "launch": self.launch_record(target), "running": self.alive}

    def owner_canary(self, target, plan_id):
        return self._owner_file(target, canary_receipt_file(plan_id))

    def owner_canary_request(self, target, plan_id):
        return self._owner_file(target, canary_request_file(plan_id))

    def _owner_file(self, target, name):
        path = self.path(target, name)
        if not path.exists():
            return None
        document = _read(path)
        return document if isinstance(document, dict) else {"unreadable": True}

    # --- the ordinary delivery lifecycle ---
    def drain(self, target, *, authorize=None):
        if authorize is not None:
            authorize()
        return {"drained": True, "unconfirmed": 0, "running": self.alive, "active": 0}

    def switch(self, target, descriptor, *, expected, authorize=None):
        if authorize is not None:
            authorize()
        current = self.current(target)
        if (None if current is None else descriptor_digest(current)) != expected:
            raise DeliveryRefused("descriptor_changed", "expected_descriptor")
        _write(self.path(target, DESCRIPTOR_FILE), descriptor)
        return {"written": True, "descriptor_sha256": descriptor_digest(descriptor)}

    def stop(self, target):
        self.calls.append(("stop",))
        if self.work["state"] != "idle":
            return {"stopped": False, "reason_code": "managed_work_active"}
        self.alive, self.active_state = False, "inactive"
        return {"stopped": True}

    def start(self, target, descriptor, *, authorize=None, replaces=None, restarts=None):
        if restarts is None:
            if authorize is not None:
                authorize()
            if self.alive and consumption_verdict(descriptor, self.receipt(target))["consumed"]:
                return {"started": False, "recovered": True, "instance_id": self.receipt(target)["instance_id"],
                        "launch": self.launch_record(target)}
            record = self._launch(target, descriptor)
            return {"started": True, "pid": record["pid"], "launch": record}
        if self.on_start is not None:
            self.on_start()
        if authorize is not None:
            authorize()                                         # the guard's entry
        decision = classify_restart(descriptor, self.generation_observation(target), restarts)
        if decision["path"] is None:
            raise DeliveryRefused(decision["reason_code"], decision["field"])
        if decision["path"] == RESTART_RECOGNIZED:
            return {"started": False, "recovered": True, "path": RESTART_RECOGNIZED,
                    "launch": self.launch_record(target), "pid": None}
        stopped_here = False
        if decision["path"] == "replace":
            self.calls.append(("gate",))
            stopped = self.stop(target)
            if not stopped["stopped"]:
                raise DeliveryRefused(stopped["reason_code"], "target_id")
            stopped_here = True
            if self.after_stop is not None:
                self.after_stop()
            if self.crash_after_stop:
                self.crash_after_stop = False
                raise Crash("controller died after the graceful stop (labelled injected fault)")
            if authorize is not None:
                try:
                    authorize()
                except Exception as exc:
                    raise LifecycleInterrupted("service_stopped", exc) from exc
        self.calls.append(("gate",))
        if not self.target_file:
            refusal = DeliveryRefused("maintenance_stale", "target_file")
            if stopped_here:
                raise LifecycleInterrupted("service_stopped", refusal)
            raise refusal
        self.calls.append(("retire",))
        self.path(target, RECEIPT_FILE).unlink(missing_ok=True)
        record = self._launch(target, descriptor)
        if self.raise_after_launch:
            self.raise_after_launch -= 1
            raise TimeoutError("launch response lost after the unit started (labelled injected fault)")
        return {"started": True, "recovered": False, "path": decision["path"], "launch": record,
                "pid": record["pid"]}

    def _launch(self, target, descriptor) -> dict:
        self.counter += 1
        n = self.counter
        invocation = "%032x" % (0xABC000 + n)
        now = self.clock()
        _write(self.path(target, "managed-launch.json"), {
            "schema": "urn:zeus:managed-launch-request:1", "target_id": target["target_id"],
            "descriptor_sha256": descriptor_digest(descriptor), "manifest_sha256": "5" * 64, "workload": "fleet",
            "requested_at": now})
        self.alive, self.active_state, self.invocation = True, "active", invocation
        self.supervisor = {"pid": 1000 + n, "start_ticks": 50_000 + n}
        self.entry = {"pid": 2000 + n, "start_ticks": 60_000 + n}
        record = {"pid": self.supervisor["pid"], "service": MANAGED_SYSTEMD_UNIT, "invocation_id": invocation,
                  "started_at": now, "descriptor_sha256": descriptor_digest(descriptor), "manifest_sha256": "5" * 64}
        _write(self.path(target, STATE_FILE), record)
        receipt = self.startup(descriptor, "%032x" % (0xF00D000 + n), now)
        if self.receipt_delay:
            self.pending_receipt = (target, receipt)
        else:
            _write(self.path(target, RECEIPT_FILE), receipt)
        self.calls.append(("launch", invocation))
        return record

    def startup(self, descriptor, instance_id, now) -> dict:
        return {"schema": RECEIPT_SCHEMA, "target_id": descriptor["target_id"], "instance_id": instance_id,
                "pid": self.entry["pid"], "started_at": now, "runtime_root": descriptor["root"],
                "module_root": descriptor["root"] + "/src/codex_harness",
                "descriptor_sha256": descriptor_digest(descriptor), "revision": descriptor["revision"],
                "worker_image": descriptor["worker_image"], "profile_digest": descriptor["profile_digest"]}

    @property
    def launches(self) -> int:
        return sum(1 for call in self.calls if call[0] == "launch")

    # --- LABELLED injected host facts ---
    def n1(self, target):
        """An unrecorded replacement generation: systemd restarted the unit itself; the controller-state is
        unchanged, the unit runs a new invocation and the new entry wrote its own receipt."""
        self.counter += 1
        n = self.counter
        self.invocation = "%032x" % (0xDEAD000 + n)
        self.supervisor = {"pid": 3000 + n, "start_ticks": 70_000 + n}
        self.entry = {"pid": 4000 + n, "start_ticks": 80_000 + n}
        self.alive, self.active_state = True, "active"
        _write(self.path(target, RECEIPT_FILE), self.startup(self.current(target), "%032x" % (0xBAD000 + n),
                                                             self.clock()))

    def pid_reuse(self):
        self.entry_flags = {**self.entry_flags, "started_before_receipt": False}

    def reload_pending(self, value=True):
        self.need_reload = value

    def target_file_changed(self):
        self.target_file = False

    def work_busy(self):
        self.work = {"state": "busy", "reason_code": "managed_work_active", "active": 1, "unresolved": 0}

    def generation_observation(self, target) -> dict:
        if self.observe_error is not None:
            raise self.observe_error
        if self.pending_receipt is not None:
            if self.receipt_delay <= 0:
                where, receipt = self.pending_receipt
                _write(self.path(where, RECEIPT_FILE), receipt)
                self.pending_receipt = None
            else:
                self.receipt_delay -= 1
        receipt_path = self.path(target, RECEIPT_FILE)
        launch, request = self.launch_record(target), self.launch_request(target)
        alive, supervisor, entry = self.alive, self.supervisor, self.entry
        return {"schema": GENERATION_OBSERVATION_SCHEMA, "observed_at": self.clock(),
                "running": None if self.running_unknown else alive,
                "receipt": _read(receipt_path), "receipt_present": receipt_path.exists(),
                "launch": launch, "launch_present": launch is not None,
                "launch_sha256": None if launch is None else digest(launch),
                "launch_request_sha256": None if request is None else digest(request),
                "launch_request_requested_at": None if request is None else request["requested_at"],
                "target_file_matches": self.target_file, "control_user_matches": self.control_user,
                "unit": {"active_state": self.active_state, "invocation_id": self.invocation,
                         "main_pid": (supervisor or {}).get("pid") if alive else None,
                         "exec_main_pid": (supervisor or {}).get("pid") if alive else 0,
                         "need_daemon_reload": self.need_reload, "control_group_sha256": "c" * 64,
                         "environment_files_sha256": self.environment_sha256, "drop_in_count": self.drop_ins},
                "supervisor": {"pid": (supervisor or {}).get("pid") if alive else None,
                               "state": "present" if alive else "absent",
                               "start_ticks": (supervisor or {}).get("start_ticks") if alive else None,
                               "is_main_pid": self.supervisor_main if alive else None},
                "entry": {"pid": (entry or {}).get("pid") if alive else None, "state": "present" if alive else "absent",
                          "start_ticks": (entry or {}).get("start_ticks") if alive else None,
                          **{flag: (value if alive else None) for flag, value in self.entry_flags.items()}},
                "work": dict(self.work)}


# ----- the control-store ports -------------------------------------------------------------------------------
def registered_fleet(control, clock, tmp_path) -> Fleet:
    """The REAL Fleet registered with the two fixture lanes of `test_fleet.config` and OWNER-paused, over the SAME
    control store the owner action rows live in; the restart phase reads only its `maintenance_readiness`."""
    fleet = Fleet(control, clock=clock)
    fleet.register(fleet_config(tmp_path / "fleet"))
    fleet.pause()
    return fleet


def hold_activation(system) -> None:
    """LABELLED injected fact: a managed runtime's activation hold on the (paused) Fleet control row."""
    with system["control"].transaction() as tx:
        control = tx.get(BUCKET_CONTROL, CONTROL_KEY) or {}
        tx.put(BUCKET_CONTROL, CONTROL_KEY, {**control, "paused": True,
                                            ACTIVATION_HOLD: {"descriptor_sha256": "0" * 64,
                                                              "at": system["clock"]()}})


def hold_unit(system, unit_id="conductor-held") -> None:
    """LABELLED injected fact: an execution unit that still holds Fleet capacity (not released)."""
    put(system["control"], BUCKET_UNITS, unit_id, {"id": unit_id, "state": "reserved", "kind": "conductor"})


class FakeArtifacts:
    """LABELLED content-addressed artifact store; counts puts and keeps the bodies in memory only."""

    def __init__(self):
        self.puts, self.bodies = 0, {}

    def put(self, body, source):
        self.puts += 1
        ref = "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()
        self.bodies[ref] = (body, source)
        return {"ref": ref, "source": source, "bytes": len(body)}


def authority_store(entries=None):
    """LABELLED trusted authority store: ref -> recorded directive bytes, read only."""
    entries = {AUTHORITY_REF: AUTHORITY_BYTES} if entries is None else entries
    calls = []

    def reader(ref):
        calls.append(ref)
        return entries[ref]

    reader.calls = calls
    return reader


def action_reader(control):
    def reader(identity):
        with control.transaction() as tx:
            return copy.deepcopy(tx.get(BUCKET_ACTIONS, identity))
    return reader


class CountingQueue:
    """Wraps the REAL ReleaseQueue and counts maintenance holds (a check must take none)."""

    def __init__(self, queue):
        self.queue, self.holds = queue, 0

    def __getattr__(self, name):
        return getattr(self.queue, name)

    def hold_maintenance(self, *args, **kwargs):
        self.holds += 1
        return self.queue.hold_maintenance(*args, **kwargs)


# ----- the ACTIVE managed delivery ------------------------------------------------------------------------------
def managed_targets(tmp_path) -> dict:
    return {"schema": REGISTRY_SCHEMA, "targets": [{
        "target_id": TARGET, "kind": KIND_MANAGED_SYSTEMD, "root": str(tmp_path / "managed-root"),
        "state_dir": str(tmp_path / "managed-state"), "service": MANAGED_SYSTEMD_UNIT,
        "source": str(tmp_path / "managed-source"), "python": str(tmp_path / "interpreter" / "bin" / "python3"),
        "environment_lock": "1" * 64}]}


def old_canary(system) -> dict:
    """The retiring instance's COMPLETED owner canary action and its receipt (LABELLED realistic evidence)."""
    intent = read(system["store"], BUCKET_INTENTS, system["plan_id"])
    receipt = system["host"].receipt(system["target"])
    binding = {"plan_id": system["plan_id"], "plan_sha256": system["plan_sha256"], "target_id": TARGET,
               "descriptor_sha256": intent["descriptor_sha256"], "instance_id": receipt["instance_id"]}
    identity = do.action_id(do.DELIVERY_CANARY, binding)
    outcome = {"state": do.VERDICT_ACCEPTED, "reason_code": "canary_accepted",
               "evidence": {"job_id": do.canary_job_id(identity), "operation_id": do.canary_job_id(identity),
                            "decision_id": "lead-old", "execution_ref": "sha256:" + "7" * 64}}
    row = {"id": identity, "kind": do.DELIVERY_CANARY, "state": do.COMPLETED, "binding": binding,
           "binding_sha256": digest(binding), "policy_id": "owners-1", "policy_sha256": "8" * 64,
           "subject": {"intent_id": "s" * 64, "lane": "a"}, "reason_code": "canary_accepted",
           "job_id": do.canary_job_id(identity), "outcome": outcome, "created_at": "2026-09-22T00:00:00+00:00",
           "updated_at": "2026-09-22T00:00:00+00:00", "version": 3, "history": []}
    return row, do.canary_receipt(row, outcome, system["clock"]())


def active_system(tmp_path, *, control=None, observer=None):
    """A REAL HostDelivery driven to ACTIVE on a managed_fleet_systemd target whose canary is the owner's
    `fleet_worker_operation` (`owner_qualified_canary` over a real receipt file and a COMPLETED action)."""
    stores = LinkedStores()
    lane = stores.lane
    control = control if control is not None else stores.control
    clock, org = Clock(), organization()
    release = reviewed_release(lane, org)
    host = FakeManagedHost(clock)
    fleet = registered_fleet(control, clock, tmp_path)
    artifacts, authorities = FakeArtifacts(), authority_store()
    delivery = HostDelivery(lane, org, github=FakeGitHub(), hosts={KIND_MANAGED_SYSTEMD: host},
                            canaries={CANARY_STARTUP: startup_identity_canary, CANARY_FLEET: owner_qualified_canary},
                            clock=clock, observer=observer, enabled=True, resume_seconds=0,
                            authorities=authorities, artifacts=artifacts, canary_records=action_reader(control),
                            maintenance_fleet=fleet)
    registry = managed_targets(tmp_path)
    delivery.register_targets(registry)
    plan = plan_document(release, plan_id=PLAN_ID, target_id=TARGET, canary=CANARY_FLEET, image=FIXTURE_IMAGE,
                         profile=FIXTURE_PROFILE, descriptor_revision=DESCRIPTOR_REVISION)
    delivery.register(plan, pin())
    system = {"stores": stores, "store": lane, "control": control, "clock": clock, "org": org, "release": release,
              "host": host, "fleet": fleet, "artifacts": artifacts, "authorities": authorities,
              "delivery": delivery, "plan": plan,
              "plan_id": PLAN_ID, "plan_sha256": plan_digest(validate_plan(plan)),
              "target": registry["targets"][0]}
    for _ in range(40):
        result = delivery.tick()
        clock.advance(1)
        if result["stage"] == AWAITING_CONSUMPTION:
            break
    else:
        raise AssertionError("the fixture delivery never reached awaiting_consumption")
    row, receipt = old_canary(system)
    put(control, BUCKET_ACTIONS, row["id"], row)
    _write(host.path(system["target"], canary_receipt_file(PLAN_ID)), receipt)
    for _ in range(10):
        result = delivery.tick()
        clock.advance(1)
        if result["stage"] == ACTIVE:
            break
    else:
        raise AssertionError("the fixture delivery never became active")
    system.update(old_action=row, old_receipt=receipt)
    return system


def intent_of(system) -> dict:
    return read(system["store"], BUCKET_INTENTS, system["plan_id"])


def row_of(system) -> dict:
    return read(system["store"], BUCKET_DESCRIPTORS, TARGET)


def plan_row_of(system) -> dict:
    return read(system["store"], BUCKET_PLANS, system["plan_id"])


def generation_of(system):
    generations = (intent_of(system) or {}).get("generations") or []
    return generations[-1] if generations else None


def document_for(system, **overrides) -> tuple:
    """The owner's maintenance document for the CURRENT active binding and its canonical evidence."""
    intent, row = intent_of(system), plan_row_of(system)
    host, target = system["host"], system["target"]
    document = {"schema": MAINTENANCE_SCHEMA, "kind": MAINTENANCE_KIND, "plan_id": system["plan_id"],
                "plan_sha256": row["plan_sha256"], "pin_sha256": row["pin"]["sha256"], "target_id": TARGET,
                "release_id": system["release"]["id"], "descriptor_sha256": intent["descriptor_sha256"],
                "from": {"stage": "active", "updated_at": intent["updated_at"]},
                "retiring": {"instance_id": intent["instance_id"], "invocation_id": host.invocation,
                             "launch_sha256": digest(host.launch_record(target))},
                "reason": MAINTENANCE_REASON, "canary_window_seconds": 600, "authority": AUTHORITY_REF,
                "approved_by": "conductor"}
    for key, value in overrides.items():
        document[key] = value
    return document, "sha256:" + digest(document)


def restarted(system, **kwargs) -> tuple:
    """Run the restart phase to `started` and return (document, evidence, result)."""
    document, evidence = document_for(system)
    result = system["delivery"].maintain(document, evidence, "restart", startup_seconds=0, poll_seconds=0, **kwargs)
    assert result["state"] == "started", result
    return document, evidence, result


def write_request(system, **overrides) -> dict:
    plan = validate_plan(system["plan"])
    document = {"schema": CANARY_REQUEST_SCHEMA, "action_id": "a" * 64, "plan_id": plan["plan_id"],
                "plan_sha256": plan_digest(plan), "target_id": TARGET, "revision": plan["target_descriptor"]["revision"],
                "expected_descriptor": plan["expected_descriptor"], "requested_at": system["clock"](), **overrides}
    _write(system["host"].path(system["target"], canary_request_file(system["plan_id"])), document)
    return document


def write_owner_file(system, name, text: str) -> None:
    path = system["host"].path(system["target"], name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def steal_lease(system, owner="labelled-successor-controller") -> None:
    """LABELLED injected successor: another controller now holds the single controller lease."""
    until = system["clock"].at.replace(year=2099).isoformat()
    put(system["store"], "deployment_locks", "controller", {"owner": owner, "lease_until": until})


__all__ = ["AUTHORITY_BYTES", "AUTHORITY_REF", "BUCKET_ACTIONS", "BUCKET_JOBS", "Crash", "CountingQueue",
           "DESCRIPTOR_REVISION", "FakeArtifacts", "FakeManagedHost", "LinkedStores", "PLAN_ID", "SENTINEL", "TARGET",
           "ContractError", "OWNER_CANARY_RECEIPT_SCHEMA", "action_reader", "active_system", "authority_store",
           "document_for", "generation_of", "hold_activation", "hold_unit", "intent_of", "managed_targets",
           "old_canary", "plan_row_of", "put", "read", "registered_fleet", "restarted", "row_of", "snapshot",
           "steal_lease", "write_owner_file", "write_request"]
