"""The typed one-use Fleet admission permit `fleet_admission_permits`, kind `delivery_canary` (INV-FLEET-001; FA-SPEC
§6 tests 1-8 and Amendment A6).

Expected results come from FA-SPEC §3 and §6, Amendment A1/A2/A6 and AMD-1 B (never from the code under test). Every test
drives the public boundary: `FleetAdmissionPermits` (grant, admit, close), `AdmissionPermitExecutor` and the owner CLI
leaves, over MemoryStore. Owner action rows, delivery intents and canary jobs are LABELLED fixtures written exactly
as `OwnerActions._advance_canary` and the delivery lane produce them; the launcher is a labelled fixture that never
spawns a process, and both executor transports are stubbed so the unexpected one raises.
"""
import json
import os
import sys
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent / "ported"))

from test_fleet import GOAL, FakeLauncher, config, manifest  # noqa: E402
from test_fleet_maintenance import (  # noqa: E402
    BINDING,
    CANARY_PATHS,
    NOW,
    UNIT,
    Clock,
    put_action,
    put_row,
    refused,
    row_of,
)

from codex_harness.coordination.application.fleet import state  # noqa: E402
from codex_harness.coordination.application.fleet.admission import AdmissionControl  # noqa: E402
from codex_harness.coordination.application.fleet.admission_permit import FleetAdmissionPermits  # noqa: E402
from codex_harness.coordination.application.fleet.maintenance import FleetMaintenance  # noqa: E402
from codex_harness.coordination.application.fleet.pause import FleetPause  # noqa: E402
from codex_harness.coordination.application.fleet.registry import FleetRegistry  # noqa: E402
from codex_harness.coordination.application.fleet.runner import AdmissionPermitExecutor  # noqa: E402
from codex_harness.coordination.domain import fleet_admission_permit as fa  # noqa: E402
from codex_harness.coordination.domain.fleet import FleetRefused  # noqa: E402
from codex_harness.coordination.domain.fleet_maintenance import (  # noqa: E402
    BINDING_FIELDS,
)
from codex_harness.coordination.domain.fleet_maintenance import PERMIT_SCHEMA as PR3_SCHEMA  # noqa: E402
from codex_harness.coordination.domain.owner_actions import canary_receipt  # noqa: E402
from codex_harness.delivery.adapters.host_delivery import (  # noqa: E402
    canary_receipt_file,
    owner_qualified_canary,
)
from codex_harness.delivery.domain.host_delivery import AWAITING_CONSUMPTION, descriptor_digest  # noqa: E402
from codex_harness.kernel.ids import digest  # noqa: E402
from codex_harness.storage.adapters.memory_store import MemoryStore  # noqa: E402

EVIDENCE = "sha256:" + "b" * 64
ACCEPTED = {"status": "accepted", "reason_code": "lead_accepted", "exit_code": 0, "calls": {"reserved": 2, "settled": 2}}
WINDOW = 600
PLAN_ID = BINDING["plan_id"]


@pytest.fixture(autouse=True)
def no_signals(monkeypatch):
    """Nothing in the permit executor may signal a process; a signal fails the test."""
    def forbidden(*args):
        raise AssertionError("a permit-admitted child is never signalled")
    monkeypatch.setattr(os, "kill", forbidden)
    if hasattr(os, "killpg"):
        monkeypatch.setattr(os, "killpg", forbidden)


@pytest.fixture(autouse=True)
def no_executor_transport(monkeypatch):
    """Stub BOTH executor transports so no test here can make a real provider call: reaching either the Codex
    app-server or the Claude runtime raises (the fleet launcher under test is a labelled fixture)."""
    def forbidden(*args, **kwargs):
        raise AssertionError("an executor transport must never be constructed by a fleet admission permit test")
    monkeypatch.setattr("m7_executor.AppServer", forbidden)
    monkeypatch.setattr("m7_executor.ClaudeCodeRuntime", forbidden)


class World:
    """An owner-paused Fleet over one MemoryStore with the OA canary action, its queued job and the delivery intent."""

    def __init__(self, tmp_path, clock=None, binding=None, held_unit=False, **overrides):
        self.clock = clock or Clock()
        self.store = MemoryStore()
        self.registry = FleetRegistry(self.store, clock=self.clock)
        self.pause = FleetPause(self.store, clock=self.clock)
        self.admission = AdmissionControl(self.store, clock=self.clock)
        self.permits = FleetAdmissionPermits(self.store, clock=self.clock)
        self.maintenance = FleetMaintenance(self.store, clock=self.clock)
        self.registry.register(config(tmp_path, **overrides))
        if held_unit:
            # LABELLED: a conductor reserved an execution unit before the owner paused.
            self.admission.reserve_unit(UNIT, "conductor", "b", "intent-held")
        self.pause.pause()
        self.binding = dict(binding or BINDING)
        self.action = None
        self.job = None

    def request_canary(self, lane="a", dependencies=(), intent=True):
        """The OA canary REQUESTED, its fixed-id job queued and (default) the delivery awaiting consumption."""
        self.action = put_action(self.store, self.binding)
        job_id = self.action["job_id"]
        self.job = self.registry.enqueue(lane, manifest(job_id, CANARY_PATHS), GOAL, list(dependencies))["job"]
        if intent:
            self.put_intent()
        return self

    def put_intent(self, window=WINDOW, **overrides):
        put_row(self.store, "host_delivery_intents", self.binding["plan_id"], {
            "stage": AWAITING_CONSUMPTION, "plan_sha256": self.binding["plan_sha256"],
            "target_id": self.binding["target_id"], "descriptor_sha256": self.binding["descriptor_sha256"],
            "stage_deadline": (NOW + timedelta(seconds=window)).isoformat(), **overrides})

    def template(self, **overrides) -> dict:
        return {"schema": fa.TEMPLATE_SCHEMA, "kind": "delivery_canary", "plan_id": self.binding["plan_id"],
                "plan_sha256": self.binding["plan_sha256"], "target_id": self.binding["target_id"], "lane": "a",
                "evidence_ref": EVIDENCE, "issuer": "owner", "approver": "conductor", **overrides}

    def grant(self, **overrides) -> dict:
        template = self.template(**overrides)
        return self.permits.grant_admission_permit(digest(template), template)

    @property
    def permit_id(self) -> str:
        return fa.permit_id_of(self.action["id"])

    def executor(self, launcher):
        return AdmissionPermitExecutor(self.registry, self.permits, self.admission, self.pause, launcher, interval=0)

    def admit(self, **overrides):
        return self.permits.admit_admission_permit(self.permit_id, **{"budget_exhausted": False, **overrides})

    def row(self, bucket, key):
        return row_of(self.store, bucket, key)

    def control_bytes(self) -> str:
        return json.dumps(self.row("fleet_control", "admission"), sort_keys=True)

    def bucket(self, name: str) -> dict:
        return {key: value for (bucket, key), value in self.store.data.items() if bucket == name}

    def snapshot(self) -> dict:
        return deepcopy(self.store.data)


def armed(tmp_path, **kwargs) -> World:
    world = World(tmp_path, **kwargs).request_canary()
    world.grant()
    return world


class CountingLauncher(FakeLauncher):
    """LABELLED fixture launcher that counts launch ATTEMPTS."""

    def __init__(self, outcomes, **kwargs):
        super().__init__(outcomes, **kwargs)
        self.attempts = []

    def launch(self, job):
        self.attempts.append(job["id"])
        return super().launch(job)


# ---- test 1: the exact job only ----------------------------------------------------------------------
def test_a_paused_permit_admits_only_its_exact_job_and_a_concurrent_enqueue_stays_queued(tmp_path):
    w = armed(tmp_path)
    control = w.control_bytes()
    other = w.registry.enqueue("b", manifest("op-concurrent", ["docs/other.md"]), GOAL, [])["job"]
    other_row = w.row("fleet_jobs", other["id"])
    admitted = w.admit()
    assert admitted["admitted"] is True and admitted["job"]["id"] == w.job["id"]
    claimed = w.row("fleet_jobs", w.job["id"])
    assert claimed["status"] == "dispatching" and claimed["owner_token"]
    assert w.row("fleet_jobs", other["id"]) == other_row, "a concurrently enqueued job is neither read-modified nor written"
    assert w.row("fleet_jobs", other["id"])["status"] == "queued"
    assert w.control_bytes() == control, "the Fleet stays owner-paused with its row untouched"
    permit_row = w.row("fleet_admission_permits", w.permit_id)
    assert permit_row["state"] == "admitted" and permit_row["owner_token"] == claimed["owner_token"]
    assert [step["state"] for step in permit_row["history"]] == ["granted", "acknowledged", "admitted"]
    assert "owner_token" not in w.permits.admission_permit(w.permit_id)


# ---- test 2: every other blocker still refuses --------------------------------------------------------
def reserve(world, lane, paths, op_id="op-busy"):
    other = world.registry.enqueue(lane, manifest(op_id, paths), GOAL, [])["job"]
    put_row(world.store, "fleet_jobs", other["id"], {**world.row("fleet_jobs", other["id"]),
                                                      "status": "dispatching", "owner_token": "t"})


@pytest.mark.parametrize("blocker, code, field", [
    ("budget", "permit_refused", "budget_exhausted"),
    ("stale_ceilings", "permit_refused", "budget_stale"),
    ("dependency", "permit_refused", "dependency_failed"),
    ("lane", "permit_debt_unsettled", "fleet"),
    ("path", "permit_debt_unsettled", "fleet"),
    ("debt_unit", "permit_debt_unsettled", "fleet"),
])
def test_every_other_blocker_still_refuses_and_writes_nothing(tmp_path, blocker, code, field):
    w = World(tmp_path, held_unit=blocker == "debt_unit")
    if blocker == "stale_ceilings":
        # LABELLED crafted row: enqueue itself refuses a stale manifest and a grant refuses a non-idle fleet.
        from codex_harness.coordination.domain.fleet import new_job
        from codex_harness.coordination.domain.operation import manifest_digest
        w.action = put_action(w.store, w.binding)
        w.pause.authorize_budget(8, 16, 8)
        old = manifest(w.action["job_id"], CANARY_PATHS)
        put_row(w.store, "fleet_jobs", w.action["job_id"],
                new_job(old, manifest_digest(old), config(tmp_path)["lanes"][0], GOAL, [], NOW.isoformat()))
        w.job = w.row("fleet_jobs", w.action["job_id"])
        w.put_intent()
    elif blocker == "dependency":
        prerequisite = w.registry.enqueue("b", manifest("op-dep", ["docs/dep.md"]), GOAL, [])["job"]
        put_row(w.store, "fleet_jobs", "op-dep", {**w.row("fleet_jobs", "op-dep"), "status": "failed"})
        w.request_canary(dependencies=[prerequisite["id"]])
    else:
        w.request_canary()
    if blocker == "lane":
        reserve(w, "a", ["docs/other.md"])
    if blocker == "path":
        reserve(w, "b", CANARY_PATHS)
    w.grant()
    before = w.snapshot()
    refused(lambda: w.admit(budget_exhausted=blocker == "budget"), code, field)
    assert w.snapshot() == before, "a refusal writes nothing"


def test_the_isolation_blocker_refuses_at_launch_and_the_job_is_never_relaunched(tmp_path):
    w = armed(tmp_path)
    launcher = CountingLauncher({}, refuse={w.job["id"]})
    result = w.executor(launcher).execute(w.permit_id, max_wait_seconds=30)
    assert (result["state"], result["job_status"], result["closed"]) == ("not_launched", "failed", True)
    assert w.row("fleet_jobs", w.job["id"])["reason_code"] == "isolation_required"
    assert launcher.attempts == [w.job["id"]] and launcher.launched == []


@pytest.mark.parametrize("control", [{"paused": False}, {"paused": True, "activation_hold": {"target_id": "managed-fleet"}}])
def test_the_owner_pause_is_required_and_an_activation_hold_is_not_a_pause(tmp_path, control):
    w = armed(tmp_path)
    put_row(w.store, "fleet_control", "admission", {**w.row("fleet_control", "admission"), **control})
    before = w.snapshot()
    refused(w.admit, "permit_pause_required", "fleet")
    assert w.snapshot() == before and w.row("fleet_jobs", w.job["id"])["status"] == "queued"


# ---- test 3: one claim; an unknown dispatch is never relaunched ---------------------------------------
def test_a_double_arm_claims_exactly_once(tmp_path):
    w = armed(tmp_path)
    first = w.admit()["job"]["owner_token"]
    after = w.snapshot()
    refused(w.admit, "permit_already_used", "state")
    assert w.snapshot() == after and w.row("fleet_jobs", w.job["id"])["owner_token"] == first


def test_response_loss_replays_are_refused_and_an_unknown_dispatch_is_held_never_relaunched(tmp_path):
    w = armed(tmp_path)
    launcher = CountingLauncher({}, explode={w.job["id"]})
    result = w.executor(launcher).execute(w.permit_id, max_wait_seconds=30)
    assert (result["state"], result["job_status"], result["closed"]) == ("not_launched", "unknown", False)
    after = w.snapshot()
    refused(lambda: w.executor(launcher).execute(w.permit_id, max_wait_seconds=30), "permit_already_used", "state")
    assert launcher.attempts == [w.job["id"]] and w.snapshot() == after, "the replay launches nothing"
    assert w.row("fleet_jobs", w.job["id"])["status"] == "unknown"
    for reason in (fa.PERMIT_EXPIRED, fa.PERMIT_CANCELLED, fa.PERMIT_SETTLED):
        refused(lambda reason=reason: w.permits.close_admission_permit(w.permit_id, reason),
                "permit_reconciliation_required", "job")
    assert w.snapshot() == after
    # A replay naming a different binding digest is a conflict, not a second claim.
    refused(lambda: w.admit(permit_sha256="0" * 64), "permit_conflict", "permit")


# ---- test 4: expiry ----------------------------------------------------------------------------------
def test_an_expired_unadmitted_permit_fails_the_queued_job_without_a_spawn(tmp_path):
    w = armed(tmp_path)
    launcher = CountingLauncher({})
    w.clock.advance(WINDOW)
    refused(lambda: w.executor(launcher).execute(w.permit_id, max_wait_seconds=30), "permit_expired", "deadline")
    job = w.row("fleet_jobs", w.job["id"])
    assert (job["status"], job["reason_code"]) == ("failed", "permit_expired")
    assert job["admission_permit"] == {"permit_id": w.permit_id, "launched": False, "reason": "permit_expired"}
    assert "maintenance" not in job and launcher.attempts == [] and launcher.launched == []
    row = w.row("fleet_admission_permits", w.permit_id)
    assert (row["state"], row["close_reason"], row["launched"]) == ("closed", "permit_expired", False)
    cached = w.permits.close_admission_permit(w.permit_id, fa.PERMIT_EXPIRED)
    assert cached["cached"] is True and cached["close_reason"] == "permit_expired"


def test_expiry_is_not_a_cancel_before_the_deadline_and_cancel_fails_the_job_without_a_spawn(tmp_path):
    w = armed(tmp_path)
    refused(lambda: w.permits.close_admission_permit(w.permit_id, fa.PERMIT_EXPIRED), "permit_stale", "deadline")
    assert w.row("fleet_jobs", w.job["id"])["status"] == "queued"
    closed = w.permits.close_admission_permit(w.permit_id, fa.PERMIT_CANCELLED)
    assert closed["launched"] is False and w.row("fleet_jobs", w.job["id"])["reason_code"] == "permit_cancelled"


def test_an_admitted_job_stays_owned_until_settlement(tmp_path):
    w = armed(tmp_path)
    w.admit()
    w.clock.advance(WINDOW + 1)
    before = w.snapshot()
    refused(lambda: w.permits.close_admission_permit(w.permit_id, fa.PERMIT_EXPIRED),
            "permit_reconciliation_required", "job")
    refused(lambda: w.permits.close_admission_permit(w.permit_id, fa.PERMIT_SETTLED),
            "permit_reconciliation_required", "job")
    assert w.snapshot() == before and w.row("fleet_jobs", w.job["id"])["status"] == "dispatching"


# ---- test 5: refusals before any claim ----------------------------------------------------------------
@pytest.mark.parametrize("kind", ["maintenance_canary", "forward_candidate", "verification_job", "other", 7, None])
def test_an_unknown_kind_is_refused_before_any_write(tmp_path, kind):
    w = World(tmp_path).request_canary()
    template = w.template(kind=kind)
    before = w.snapshot()
    refused(lambda: w.permits.grant_admission_permit(digest(template), template), "permit_invalid", "kind")
    assert w.snapshot() == before and w.bucket("fleet_admission_permits") == {}


def test_a_stored_permit_of_an_unknown_kind_is_not_admitted(tmp_path):
    w = armed(tmp_path)
    row = w.row("fleet_admission_permits", w.permit_id)
    row["permit"]["kind"] = "maintenance_canary"
    put_row(w.store, "fleet_admission_permits", w.permit_id, row)
    before = w.snapshot()
    refused(w.admit, "permit_invalid", "kind")
    assert w.snapshot() == before and w.row("fleet_jobs", w.job["id"])["status"] == "queued"


@pytest.mark.parametrize("field", ["instance_id", "descriptor_sha256", "plan_sha256"])
def test_a_moved_action_binding_is_refused_before_any_claim(tmp_path, field):
    w = armed(tmp_path)
    action = w.row("owner_actions", w.action["id"])
    action["binding"][field] = ("f" * 32) if field == "instance_id" else "f" * 64
    put_row(w.store, "owner_actions", action["id"], action)
    before = w.snapshot()
    refused(w.admit, "permit_refused", "action")
    assert w.snapshot() == before


@pytest.mark.parametrize("change", [{"manifest_sha256": "e" * 64}, {"lane": "b"}])
def test_a_job_that_differs_from_the_permit_binding_is_refused_before_any_claim(tmp_path, change):
    w = armed(tmp_path)
    put_row(w.store, "fleet_jobs", w.job["id"], {**w.row("fleet_jobs", w.job["id"]), **change})
    before = w.snapshot()
    refused(w.admit, "permit_refused", "job")
    assert w.snapshot() == before


@pytest.mark.parametrize("terminal", ["accepted", "failed", "dispatching"])
def test_only_the_still_queued_job_is_admitted(tmp_path, terminal):
    w = armed(tmp_path)
    put_row(w.store, "fleet_jobs", w.job["id"], {**w.row("fleet_jobs", w.job["id"]), "status": terminal})
    before = w.snapshot()
    refused(w.admit, "permit_refused", "job")
    assert w.snapshot() == before


def test_a_missing_acknowledgement_is_refused_before_any_claim(tmp_path):
    w = armed(tmp_path)
    # LABELLED granted-only fixture row: the grant of this permit always acknowledges in the same transaction.
    put_row(w.store, "fleet_admission_permits", w.permit_id,
            {**w.row("fleet_admission_permits", w.permit_id), "state": "granted", "acknowledged_at": None})
    before = w.snapshot()
    refused(w.admit, "permit_unacknowledged", "state")
    assert w.snapshot() == before and w.row("fleet_jobs", w.job["id"])["status"] == "queued"


def test_an_expired_deadline_is_refused_before_any_claim_and_writes_nothing(tmp_path):
    w = armed(tmp_path)
    w.clock.advance(WINDOW)
    before = w.snapshot()
    refused(w.admit, "permit_expired", "deadline")
    assert w.snapshot() == before, "admit alone only refuses; the executor writes the expiry"


def test_an_unknown_permit_id_and_a_malformed_one_are_refused(tmp_path):
    w = armed(tmp_path)
    for bad in ("fleet_admission:" + "0" * 64, "x", None, 5):
        refused(lambda bad=bad: w.permits.admit_admission_permit(bad, budget_exhausted=False), "permit_refused", "permit")


# ---- the grant (A2, A6) --------------------------------------------------------------------------------
def test_a_template_with_a_different_digest_is_refused_before_any_write(tmp_path):
    w = World(tmp_path).request_canary()
    template = w.template()
    w.permits.consumption = lambda plan_id: pytest.fail("the digest is checked before anything is read")
    before = w.snapshot()
    refused(lambda: w.permits.grant_admission_permit("0" * 64, template), "permit_invalid", "template")
    refused(lambda: w.permits.grant_admission_permit(digest(w.template(evidence_ref="sha256:" + "c" * 64)), template),
            "permit_invalid", "template")
    assert w.snapshot() == before


def test_the_in_window_grant_derives_exactly_the_oa_actions_binding_and_the_consumption_deadline(tmp_path):
    w = World(tmp_path).request_canary()
    result = w.grant()
    assert result["granted"] is True and result["cached"] is False and result["state"] == "acknowledged"
    permit = w.row("fleet_admission_permits", w.permit_id)["permit"]
    assert {key: permit[key] for key in BINDING_FIELDS} == w.action["binding"]
    assert (permit["action_id"], permit["job_id"]) == (w.action["id"], w.action["job_id"])
    assert (permit["lane"], permit["manifest_sha256"]) == (w.job["lane"], w.job["manifest_sha256"])
    assert permit["deadline"] == (NOW + timedelta(seconds=WINDOW)).isoformat(), "the consumption record's deadline"
    assert (permit["issuer"], permit["approver"], permit["kind"]) == ("owner", "conductor", "delivery_canary")
    assert permit["schema"] == "urn:zeus:fleet-admission-permit:1"
    row = w.row("fleet_admission_permits", w.permit_id)
    assert [step["state"] for step in row["history"]] == ["granted", "acknowledged"]
    assert row["ack"]["template_sha256"] == digest(w.template())
    # The same permit replays cached; a conflicting deadline under the same id conflicts.
    assert w.grant()["cached"] is True
    w.put_intent(window=WINDOW - 100)
    refused(w.grant, "permit_conflict", "permit")


@pytest.mark.parametrize("case, code, field", [
    ("approver_equals_issuer", "permit_invalid", "approver"),
    ("lane_mismatch", "permit_refused", "job"),
    ("target_mismatch", "permit_refused", "action"),
    ("plan_digest_mismatch", "permit_refused", "action"),
    ("not_requested", "permit_refused", "action"),
    ("no_consumption", "permit_refused", "consumption"),
    ("descriptor_moved", "permit_refused", "consumption"),
    ("consumption_expired", "permit_expired", "deadline"),
    ("window_too_long", "permit_invalid", "deadline"),
    ("job_not_queued", "permit_refused", "job"),
])
def test_the_grant_refuses_before_any_write(tmp_path, case, code, field):
    w = World(tmp_path).request_canary()
    overrides = {}
    if case == "approver_equals_issuer":
        overrides = {"approver": "owner"}
    elif case == "lane_mismatch":
        overrides = {"lane": "b"}
    elif case == "target_mismatch":
        overrides = {"target_id": "other-target"}
    elif case == "plan_digest_mismatch":
        overrides = {"plan_sha256": "9" * 64}
    elif case == "not_requested":
        put_row(w.store, "owner_actions", w.action["id"], {**w.row("owner_actions", w.action["id"]), "state": "completed"})
    elif case == "no_consumption":
        put_row(w.store, "host_delivery_intents", PLAN_ID, {"stage": "active"})
    elif case == "descriptor_moved":
        w.put_intent(descriptor_sha256="a" * 64)
    elif case == "consumption_expired":
        w.clock.advance(WINDOW)
    elif case == "window_too_long":
        w.put_intent(window=901)
    elif case == "job_not_queued":
        put_row(w.store, "fleet_jobs", w.job["id"], {**w.row("fleet_jobs", w.job["id"]), "status": "dispatching"})
    before = w.snapshot()
    refused(lambda: w.grant(**overrides), code, field)
    assert w.snapshot() == before


def test_the_grant_needs_the_owner_pause_and_exactly_one_requested_action(tmp_path):
    w = World(tmp_path).request_canary()
    put_row(w.store, "fleet_control", "admission", {"paused": False})
    before = w.snapshot()
    refused(w.grant, "permit_pause_required", "fleet")
    assert w.snapshot() == before
    empty = World(tmp_path)
    empty.put_intent()
    refused(empty.grant, "permit_refused", "action")


# ---- test 6: the control row is byte-identical across a full permit cycle; the PR-3 bucket is unchanged -------
def test_a_full_permit_cycle_leaves_the_control_row_and_the_pr3_bucket_byte_identical(tmp_path):
    w = World(tmp_path)
    # A PR-3 permit of ANOTHER generation is open in the PR-3 bucket (the S2R maintenance): an FA cycle never touches it.
    other = {**BINDING, "instance_id": "d" * 32}
    from test_fleet_maintenance import permit_for
    w.maintenance.grant_maintenance_canary(permit_for(other, mid="active_generation_1:" + "c" * 64))
    w.request_canary()
    control = w.control_bytes()
    pr3 = json.dumps(w.bucket("fleet_maintenance_admissions"), sort_keys=True)
    assert pr3 != "{}"
    w.grant()
    launcher = CountingLauncher({w.job["id"]: ACCEPTED})
    result = w.executor(launcher).execute(w.permit_id, max_wait_seconds=30)
    assert result == {"schema": "urn:zeus:fleet-admission-execution:1", "permit_id": w.permit_id,
                      "job_id": w.job["id"], "admitted": True, "state": "finished", "job_status": "accepted",
                      "closed": True}
    assert w.control_bytes() == control, "paused and updated_at are unchanged"
    assert json.dumps(w.bucket("fleet_maintenance_admissions"), sort_keys=True) == pr3
    row = w.row("fleet_admission_permits", w.permit_id)
    assert (row["state"], row["close_reason"], row["launched"], row["job_status"]) == ("closed", "permit_settled", True,
                                                                                          "accepted")
    assert [step["state"] for step in row["history"]] == ["granted", "acknowledged", "admitted", "closed"]
    assert launcher.attempts == [w.job["id"]]
    # A settled row is never rewritten: the replay is cached and the row is byte-identical.
    settled = json.dumps(row, sort_keys=True)
    assert w.permits.close_admission_permit(w.permit_id, fa.PERMIT_SETTLED)["cached"] is True
    assert w.grant()["cached"] is True
    assert json.dumps(w.row("fleet_admission_permits", w.permit_id), sort_keys=True) == settled
    refused(w.admit, "permit_already_used", "state")


# ---- test 7: in-process reader tolerance (the R0-binary half is rehearsal R4/R6) -----------------------------
def test_readers_tolerate_a_store_holding_granted_admitted_and_closed_permit_rows(tmp_path):
    w = World(tmp_path).request_canary()
    w.grant()
    base = w.row("fleet_admission_permits", w.permit_id)
    for key, permit_state in (("fleet_admission:" + "1" * 64, "granted"), ("fleet_admission:" + "2" * 64, "admitted"),
                              ("fleet_admission:" + "3" * 64, "closed"), (w.permit_id, "acknowledged")):
        put_row(w.store, "fleet_admission_permits", key, {**base, "id": key, "state": permit_state})
    status = w.registry.status()
    assert status["registered"] is True and status["paused"] is True
    assert w.registry.reconciliation_required() == []
    readiness = w.pause.maintenance_readiness()
    assert readiness["registered"] is True
    with w.store.transaction() as tx:
        assert state.open_permits(tx) == [] and state.maintenance_debt(tx) is False
        assert [row["id"] for row in tx.scan("fleet_admission_permits")] == sorted(
            ["fleet_admission:" + d * 64 for d in "123"] + [w.permit_id])
    assert w.maintenance.maintenance_permit(w.permit_id) is None
    assert w.permits.admission_permit("fleet_admission:" + "1" * 64)["state"] == "granted"


# ---- test 8: a receipt that does not bind to the new instance fails the canary ------------------------------
def test_a_delivery_canary_receipt_that_does_not_bind_the_new_instance_fails_the_canary(tmp_path):
    descriptor = {"revision": "1" * 40, "image": "fixture"}
    binding = {**BINDING, "descriptor_sha256": descriptor_digest(descriptor)}
    w = World(tmp_path, binding=binding).request_canary()
    w.grant()
    accepted = {"state": "accepted", "reason_code": "canary_accepted", "evidence": {"job_id": w.job["id"]}}
    receipt = canary_receipt(w.action, accepted, NOW.isoformat())
    assert receipt["instance_id"] == binding["instance_id"]
    target = {"state_dir": str(tmp_path)}
    (tmp_path / canary_receipt_file(PLAN_ID)).write_text(json.dumps(receipt))
    plan = {"plan_id": PLAN_ID}
    ok = owner_qualified_canary(target, descriptor, {"instance_id": binding["instance_id"]}, plan=plan)
    assert ok["passed"] is True
    stale = owner_qualified_canary(target, descriptor, {"instance_id": "0" * 32}, plan=plan)
    assert stale["passed"] is False and stale["reason_code"] == "canary_owner_receipt_stale"


# ---- A6: FA never admits a PR-3 job ----------------------------------------------------------------------
def test_fa_never_admits_a_maintenance_canary_or_forward_candidate_job(tmp_path):
    # A PR-3 `maintenance_canary` permit that already names this canary job.
    w = World(tmp_path).request_canary()
    pr3 = {"id": "active_generation_1:" + "a" * 64, "state": "granted",
           "permit": {"schema": PR3_SCHEMA, "action_id": w.action["id"], "job_id": w.job["id"]}}
    put_row(w.store, "fleet_maintenance_admissions", pr3["id"], pr3)
    before = w.snapshot()
    refused(w.grant, "permit_conflict", "maintenance")
    assert w.snapshot() == before
    # A `forward_candidate` permit row that names the job once admitted (LABELLED crafted PR-3 row).
    fwd = World(tmp_path).request_canary()
    fwd.grant()
    forward = {"id": "active_generation_1:" + "b" * 64, "state": "admitted", "job_id": fwd.job["id"],
               "permit": {"schema": PR3_SCHEMA, "kind": "forward_candidate"}}
    put_row(fwd.store, "fleet_maintenance_admissions", forward["id"], forward)
    before = fwd.snapshot()
    refused(fwd.admit, "permit_refused", "maintenance")
    assert fwd.snapshot() == before and fwd.row("fleet_jobs", fwd.job["id"])["status"] == "queued"


def test_only_one_fa_permit_is_unsettled_at_a_time(tmp_path):
    w = armed(tmp_path)
    other = {**BINDING, "plan_id": "plan-two", "instance_id": "d" * 32}
    second = World(tmp_path, binding=other)
    second.store = w.store
    second.permits, second.registry = w.permits, w.registry
    second.request_canary()
    refused(second.grant, "permit_conflict", "permit_id")


def test_a_closed_permit_of_another_action_does_not_block_a_new_grant(tmp_path):
    w = armed(tmp_path)
    w.permits.close_admission_permit(w.permit_id, fa.PERMIT_CANCELLED)
    other = {**BINDING, "plan_id": "plan-two", "instance_id": "d" * 32}
    second = World(tmp_path, binding=other)
    second.store, second.permits, second.registry = w.store, w.permits, w.registry
    second.request_canary()
    assert second.grant()["granted"] is True


# ---- the executor and the CLI leaves ------------------------------------------------------------------
def test_the_executor_settles_nothing_while_the_job_still_runs_and_never_kills(tmp_path):
    w = armed(tmp_path)

    class Hanging(CountingLauncher):
        """LABELLED: a child that never finishes within the bound."""

        def wait(self, handles, seconds):
            return []

        def outcome(self, handle, job):
            raise AssertionError("an unfinished child has no outcome")

    result = w.executor(Hanging({})).execute(w.permit_id, max_wait_seconds=0)
    assert (result["state"], result["job_status"], result["closed"]) == ("running", "dispatching", False)
    assert w.row("fleet_admission_permits", w.permit_id)["state"] == "admitted"


def test_the_executor_refuses_an_unreadable_ledger_with_nothing_launched(tmp_path):
    w = armed(tmp_path)

    class Unreadable(CountingLauncher):
        def budget_exhausted(self, budget):
            raise OSError("ledger unreadable (fixture)")

    launcher = Unreadable({})
    before = w.snapshot()
    refused(lambda: w.executor(launcher).execute(w.permit_id, max_wait_seconds=30), "permit_refused", "budget_unknown")
    assert launcher.attempts == [] and w.snapshot() == before


def test_the_cli_parser_carries_the_two_leaves_and_grant_permit_takes_no_secret_on_argv():
    import argparse

    from codex_harness.entry.cli.fleet import add_parser

    root = argparse.ArgumentParser()
    add_parser(root.add_subparsers(dest="command"))
    grant = root.parse_args(["fleet", "grant-permit", "--template", "a" * 64, "--file", "template.json"])
    admit = root.parse_args(["fleet", "admit-permit", "--permit", "fleet_admission:" + "a" * 64])
    assert (grant.fleet_command, grant.template, str(grant.file)) == ("grant-permit", "a" * 64, "template.json")
    assert (admit.fleet_command, admit.permit, admit.max_wait_seconds) == ("admit-permit", "fleet_admission:" + "a" * 64, 900)
    with pytest.raises(SystemExit):
        root.parse_args(["fleet", "grant-permit", "--file", "template.json"])


def test_the_grant_permit_leaf_grants_through_the_store_and_refuses_with_the_closed_grammar(tmp_path):
    from codex_harness.entry.cli.fleet import _grant_permit

    w = World(tmp_path).request_canary()
    template = w.template()
    # The leaf runs on the real clock: the delivery's deadline is relative to it.
    w.put_intent(stage_deadline=(datetime.now(timezone.utc) + timedelta(seconds=WINDOW)).isoformat())
    path = tmp_path / "template.json"
    path.write_text(json.dumps(template))
    service = SimpleNamespace(store=w.store)
    result = _grant_permit(service, SimpleNamespace(template=digest(template), file=path))
    assert result["granted"] is True and result["exit_code"] == 0 and result["permit_id"] == w.permit_id
    with pytest.raises(FleetRefused) as info:
        _grant_permit(service, SimpleNamespace(template="0" * 64, file=path))
    assert (info.value.reason_code, info.value.field) == ("permit_invalid", "template")
