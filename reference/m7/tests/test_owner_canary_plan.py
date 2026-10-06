"""INV-OWNER-ACTIONS-001, aibox-migration-001 SPEC s14 G2: the owner's pending-canary authority belongs to
the plan being consumed, never to whichever plan of the same target was registered last.

Real: `HostDelivery` (registry, register, stages, canary gate, rollback) over a real managed target with
two sealed revisions of this checkout's code (`test_managed_runtime`), the incumbent
`owner_qualified_canary`, the `OwnerActions` coordinator's own `_register`/tick producer and the real
`TargetFiles` port over the target state directory. LABELLED fixtures: the continuation policy stand-in,
the Git plan publisher stand-in (it returns the plan and pin the owner recorded; Git publication is
covered by `test_owner_delivery.py`), the GitHub double and the owner canary outcome (built with the real
`canary_receipt` from a labelled outcome instead of a Fleet canary run, which `test_owner_delivery.py`
covers). No model, provider, live service or production store is touched. Nothing here is a production
verification.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from test_continuation import GOAL, manifest
from test_host_delivery import (
    PROFILE,
    pin,
    plan_document,
    reviewed_release,
    runtime_image,
    successor_candidate,
)
from test_managed_runtime import (
    TARGET_ID,
    advance,
    await_work,
    make_source,
    managed_system,
    needs_profile,
    read,
    state,
    teardown,
    trail,
)
from test_owner_delivery import owner_policy

from codex_harness.adapters.host_delivery import (
    DESCRIPTOR_FILE,
    RECEIPT_FILE,
    canary_checks,
    canary_receipt_file,
    canary_request_file,
    owner_qualified_canary,
)
from codex_harness.adapters.owner_actions import TargetFiles
from codex_harness.adapters.store import MemoryStore
from codex_harness.application.host_delivery import BUCKET_INTENTS, HostDelivery
from codex_harness.application.owner_actions import BUCKET_ACTIONS, OwnerActions
from codex_harness.domain import owner_actions as do
from codex_harness.domain.host_delivery import (
    ACTIVE,
    AWAITING_CONSUMPTION,
    CANARY_FLEET,
    REGISTERED,
    ROLLED_BACK,
    descriptor_digest,
    plan_digest,
    validate_plan,
)

# Plan ids sort in registration order, as the actual own-a98e... (H1) and own-fe54... (H2) do.
H1, H2 = "own-h1-canary-plan", "own-h2-canary-plan"
LEGACY_REQUEST_FILE = "owner-canary-request.json"   # the former target-global slot


@pytest.fixture(scope="module")
def source(tmp_path_factory):
    """The labelled disposable source with revisions A and B (`test_managed_runtime.make_source`)."""
    return make_source(tmp_path_factory.mktemp("canary-plan-source") / "source")


class PolicyContinuation:
    """LABELLED continuation stand-in: only the registered continuation policy a tick checks."""

    def policy(self, policy_id):
        return {"id": policy_id, "policy": {"delivery_target": TARGET_ID}}


class RecordedPlans:
    """LABELLED publisher stand-in: `load` returns exactly the plan and pin the owner recorded."""

    def __init__(self):
        self.loaded = {}

    def load(self, revision, path):
        return json.loads(json.dumps(self.loaded[(revision, path)]))


def owner_for(system, control=None, plans=None):
    control = control or MemoryStore()
    plans = plans or RecordedPlans()
    owner = OwnerActions(control, continuation=PolicyContinuation(), deliveries=lambda lane: system["delivery"],
                         publisher=lambda lane: plans, targets=TargetFiles())
    owner.register(owner_policy(canary={"lane": "a", "manifest": manifest("canary-template", "docs/c.md"),
                                        "goal": GOAL}, target_id=TARGET_ID, canary_check_id=CANARY_FLEET,
                                consumption_timeout_seconds=900),
                   {"revision": "e" * 40, "path": "ops/owner-actions.json", "sha256": "d" * 64, "lane": "a"})
    return {"owner": owner, "control": control, "plans": plans}


def owner_plan(system, source, owner, plan_id, *, revision, runtime, expected, when, consumption_timeout=900):
    """One owner plan action at `published`, as `_advance_plan` leaves it before `_register`."""
    release = reviewed_release(system["store"], system["org"],
                               record_candidate={**successor_candidate(system), "revision": revision, "branch": "harness/" + plan_id,
                                                 "task_id": plan_id})
    plan = validate_plan(plan_document(release, plan_id=plan_id, target_id=TARGET_ID, expected=expected,
                                       image=runtime_image(source["root"]), profile=PROFILE, canary=CANARY_FLEET,
                                       descriptor_revision=runtime, consumption_timeout=consumption_timeout))
    pinned = pin(path="docs/zeus/operations/" + plan_id + ".json", revision=revision)
    owner["plans"].loaded[(pinned["revision"], pinned["path"])] = {"plan": plan, "pin": pinned}
    action = {"id": plan_id.replace("-", "0").ljust(64, "0"), "kind": do.DELIVERY_PLAN, "state": do.PUBLISHED,
              "binding": {"plan_id": plan_id}, "binding_sha256": "b" * 64, "policy_id": "owners-1",
              "policy_sha256": "c" * 64, "subject": {"intent_id": plan_id, "lane": "a"}, "plan": plan,
              "plan_id": plan_id, "plan_sha256": plan_digest(plan), "path": pinned["path"],
              "ref": do.plan_ref(plan_id), "commit": pinned["revision"], "bytes_sha256": pinned["sha256"],
              "published_at": when, "created_at": when, "version": 3, "history": [], "reason_code": "plan_published"}
    with owner["control"].transaction() as tx:
        tx.put(BUCKET_ACTIONS, action["id"], action)
    return action


def delivery(system, plan_id):
    with system["store"].transaction() as tx:
        return tx.get(BUCKET_INTENTS, plan_id)


def action_rows(owner):
    with owner["control"].transaction() as tx:
        return {row["id"]: row for row in tx.scan(BUCKET_ACTIONS)}


def owner_receipt(system, action, *, passed=True, consumed=None):
    """The owner receipt exactly as `_advance_canary` writes it, from a LABELLED canary outcome, bound to
    the descriptor of the delivery `consumed` (default: the action's own) and the running instance."""
    startup = read(state(system["target"], RECEIPT_FILE))
    binding = {"plan_id": action["plan_id"], "plan_sha256": action["plan_sha256"], "target_id": TARGET_ID,
               "descriptor_sha256": delivery(system, consumed or action["plan_id"])["descriptor_sha256"],
               "instance_id": startup["instance_id"]}
    outcome = {"state": do.VERDICT_ACCEPTED if passed else do.VERDICT_REJECTED,
               "reason_code": "canary_accepted" if passed else "canary_rejected",
               "evidence": {"labelled": "fixture owner canary outcome"}}
    TargetFiles.write_receipt(system["target"], action["plan_id"],
                              do.canary_receipt({"id": "f" * 64, "binding": binding}, outcome, "2026-09-26T00:00:00Z"))


def active_predecessor(tmp_path, source, **kwargs):
    system = managed_system(tmp_path, source, **kwargs)
    results = advance(system, ACTIVE)
    assert results[-1]["stage"] == ACTIVE, trail(results)
    await_work(system["host"], system["target"], "idle")
    return system, read(state(system["target"], DESCRIPTOR_FILE))


def consume(system, plan_id):
    system["plan"] = {"plan_id": plan_id}
    results = advance(system, AWAITING_CONSUMPTION)
    assert results[-1]["stage"] == AWAITING_CONSUMPTION, trail(results)
    return results


def until_startup_observed(system, plan_id, limit=200):
    """Tick the REAL controller until the candidate's own startup is observed and the canary asked."""
    results = []
    for _ in range(limit):
        results.append(system["delivery"].tick())
        system["clock"].advance(1)
        row = delivery(system, plan_id)
        if row["stage"] != AWAITING_CONSUMPTION or str(row.get("reason_code") or "").startswith("canary_"):
            return results
        time.sleep(0.1)
    return results


# ----- the actual two-plans-on-one-target state (G-H1 review finding) -----------------------------------
@needs_profile
def test_a_later_registered_plan_never_replaces_the_consuming_plans_pending_canary(tmp_path, source):
    system, good = active_predecessor(tmp_path, source)
    owner = owner_for(system)
    try:
        # H1 is published first, H2 later; both bound to the same active predecessor, as on the host.
        h1 = owner_plan(system, source, owner, H1, revision="5" * 40, runtime=source["b"],
                        expected=descriptor_digest(good), when="2026-09-26T01:30:00+00:00")
        h2 = owner_plan(system, source, owner, H2, revision="6" * 40, runtime=source["a"],
                        expected=descriptor_digest(good), when="2026-09-26T01:36:56+00:00")
        owner["owner"].tick("owners-1")           # the REAL producer: request filed, then registration
        assert {row["state"] for row in action_rows(owner).values()} == {do.COMPLETED}
        # Each plan's request is its own; the second registration replaced nothing of the first.
        requests = {plan_id: read(state(system["target"], canary_request_file(plan_id))) for plan_id in (H1, H2)}
        assert requests[H1]["plan_sha256"] == h1["plan_sha256"] and requests[H2]["plan_sha256"] == h2["plan_sha256"]
        assert not state(system["target"], LEGACY_REQUEST_FILE).exists()
        consume(system, H1)
        results = until_startup_observed(system, H1)
        row = delivery(system, H1)
        # Before the fix this tick rolled H1 back with `canary_owner_receipt_missing`: H2's request was
        # the only one on the target. Now H1 waits for ITS canary under its own deadline.
        assert row["stage"] == AWAITING_CONSUMPTION and row["reason_code"] == "canary_owner_receipt_pending", \
            trail(results)
        assert delivery(system, H2) is None or delivery(system, H2)["stage"] == REGISTERED
        # A passed receipt for the OTHER plan (same target, even naming H1's descriptor and instance)
        # cannot pass H1: it is H2's evidence, not H1's.
        owner_receipt(system, h2, consumed=H1)
        for _ in range(3):
            system["delivery"].tick()
            system["clock"].advance(1)
        assert delivery(system, H1)["reason_code"] == "canary_owner_receipt_pending"
        assert delivery(system, H1)["stage"] == AWAITING_CONSUMPTION
        # Restart/replay: a new controller and a new owner over the same stores and files still wait,
        # and the replayed owner tick writes nothing (no action row, request or receipt changes).
        owner["owner"].tick("owners-1")   # the owner's canary is owed to H1, bound to H1's plan and instance
        [canary] = [row for row in action_rows(owner).values() if row["kind"] == do.DELIVERY_CANARY]
        assert (canary["binding"]["plan_id"], canary["binding"]["plan_sha256"]) == (H1, h1["plan_sha256"])
        assert canary["binding"]["instance_id"] == read(state(system["target"], RECEIPT_FILE))["instance_id"]
        before = {name: state(system["target"], name).read_bytes() for name in
                  (canary_request_file(H1), canary_request_file(H2), canary_receipt_file(H2))}
        rows = action_rows(owner)
        replay = owner_for(system, control=owner["control"], plans=owner["plans"])
        replay["owner"].tick("owners-1")
        assert action_rows(owner) == rows
        assert {name: state(system["target"], name).read_bytes() for name in before} == before
        old = system["delivery"]
        system["delivery"] = HostDelivery(system["store"], system["org"], github=old.github, hosts=old.hosts,
                                          canaries=canary_checks(), clock=system["clock"], enabled=True,
                                          resume_seconds=0)
        system["delivery"].tick()
        system["clock"].advance(1)
        assert delivery(system, H1)["reason_code"] == "canary_owner_receipt_pending"
        # H1's OWN passed receipt, bound to its descriptor and candidate instance, activates H1.
        owner_receipt(system, h1)
        system["plan"] = {"plan_id": H1}
        results = advance(system, ACTIVE)
        assert results[-1]["stage"] == ACTIVE, trail(results)
        assert delivery(system, H1)["canary"]["passed"] is True
    finally:
        teardown(system["target"])


@needs_profile
def test_the_pending_wait_stays_bounded_by_the_consuming_plans_own_deadline(tmp_path, source):
    system, good = active_predecessor(tmp_path, source)
    owner = owner_for(system)
    try:
        owner_plan(system, source, owner, H1, revision="5" * 40, runtime=source["b"],
                   expected=descriptor_digest(good), when="2026-09-26T01:30:00+00:00", consumption_timeout=10)
        owner_plan(system, source, owner, H2, revision="6" * 40, runtime=source["a"],
                   expected=descriptor_digest(good), when="2026-09-26T01:36:56+00:00")
        owner["owner"].tick("owners-1")
        consume(system, H1)
        system["plan"] = {"plan_id": H1}
        results = advance(system, ROLLED_BACK)
        assert results[-1]["stage"] == ROLLED_BACK, trail(results)
        assert "canary_owner_receipt_pending" in {r["reason_code"] for r in results}
        assert delivery(system, H1)["rollback"]["reason_code"] == "canary_owner_receipt_pending"
        assert read(state(system["target"], DESCRIPTOR_FILE))["revision"] == source["a"]
    finally:
        teardown(system["target"])


@needs_profile
def test_a_sequential_second_plan_waits_for_its_own_canary_not_the_first_plans_receipt(tmp_path, source):
    system, good = active_predecessor(tmp_path, source)
    owner = owner_for(system)
    try:
        h1 = owner_plan(system, source, owner, H1, revision="5" * 40, runtime=source["b"],
                        expected=descriptor_digest(good), when="2026-09-26T01:30:00+00:00")
        owner["owner"].tick("owners-1")
        consume(system, H1)
        until_startup_observed(system, H1)
        owner_receipt(system, h1)
        system["plan"] = {"plan_id": H1}
        assert advance(system, ACTIVE)[-1]["stage"] == ACTIVE
        await_work(system["host"], system["target"], "idle")
        first = read(state(system["target"], DESCRIPTOR_FILE))
        # H2 afterwards, bound to H1's active descriptor. H1's passed receipt stays on the target.
        h2 = owner_plan(system, source, owner, H2, revision="6" * 40, runtime=source["a"],
                        expected=descriptor_digest(first), when="2026-09-26T02:40:00+00:00")
        owner["owner"].tick("owners-1")
        consume(system, H2)
        results = until_startup_observed(system, H2)
        # Before the fix H1's receipt in the single target file was `canary_owner_receipt_stale` here.
        assert delivery(system, H2)["reason_code"] == "canary_owner_receipt_pending", trail(results)
        owner_receipt(system, h2)
        system["plan"] = {"plan_id": H2}
        results = advance(system, ACTIVE)
        assert results[-1]["stage"] == ACTIVE, trail(results)
        assert read(state(system["target"], DESCRIPTOR_FILE))["predecessor"] == descriptor_digest(first)
    finally:
        teardown(system["target"])


# ----- explicit compatibility: plans registered while the request slot was target global ------------------
@needs_profile
def test_already_registered_plans_get_their_own_request_refiled_from_the_immutable_action_rows(tmp_path, source):
    system, good = active_predecessor(tmp_path, source)
    owner = owner_for(system)
    try:
        h1 = owner_plan(system, source, owner, H1, revision="5" * 40, runtime=source["b"],
                        expected=descriptor_digest(good), when="2026-09-26T01:30:00+00:00")
        h2 = owner_plan(system, source, owner, H2, revision="6" * 40, runtime=source["a"],
                        expected=descriptor_digest(good), when="2026-09-26T01:36:56+00:00")
        # LABELLED former state: both plans completed and registered by the earlier code, whose single
        # target file holds only H2's request; no plan-scoped file exists yet.
        with owner["control"].transaction() as tx:
            for action in (h1, h2):
                completed = do.moved(action, do.COMPLETED, action["published_at"], "plan_registered",
                                     registration={"plan_sha256": action["plan_sha256"], "cached": False})
                tx.put(BUCKET_ACTIONS, action["id"], completed)
                loaded = owner["plans"].loaded[(action["commit"], action["path"])]
                system["delivery"].register(loaded["plan"], loaded["pin"])
        legacy = do.canary_request(h2, h2["plan"], h2["plan_sha256"], h2["published_at"])
        state(system["target"], LEGACY_REQUEST_FILE).write_text(json.dumps(legacy, sort_keys=True), encoding="utf-8")
        legacy_bytes = state(system["target"], LEGACY_REQUEST_FILE).read_bytes()
        rows = action_rows(owner)
        consume(system, H1)
        # The earlier consumer's reading of this state is exactly the finding: no pending authority.
        assert owner_qualified_canary(system["target"], delivery(system, H1)["descriptor"], {},
                                      plan=validate_plan(h1["plan"]))["reason_code"] == "canary_owner_receipt_missing"
        owner["owner"].tick("owners-1")
        # Each still-open plan's request is refiled, byte for byte the one its registration filed.
        for action in (h1, h2):
            filed = read(state(system["target"], canary_request_file(action["plan_id"])))
            assert filed == do.canary_request(action, action["plan"], action["plan_sha256"], action["published_at"])
        # The plan actions are immutable; only an H1 canary action may have been added (owed once H1's
        # startup is observed), never a plan row change.
        assert {k: v for k, v in action_rows(owner).items() if v["kind"] == do.DELIVERY_PLAN} == rows
        assert state(system["target"], LEGACY_REQUEST_FILE).read_bytes() == legacy_bytes, "never rewritten"
        results = until_startup_observed(system, H1)
        assert delivery(system, H1)["reason_code"] == "canary_owner_receipt_pending", trail(results)
        # A terminal delivery gets nothing refiled.
        state(system["target"], canary_request_file(H1)).unlink()
        with system["store"].transaction() as tx:
            row = tx.get(BUCKET_INTENTS, H1)
            snapshot = dict(row)
            tx.put(BUCKET_INTENTS, H1, {**row, "stage": ROLLED_BACK})   # LABELLED terminal delivery
        owner["owner"].tick("owners-1")
        assert not state(system["target"], canary_request_file(H1)).exists()
        with system["store"].transaction() as tx:
            tx.put(BUCKET_INTENTS, H1, snapshot)
    finally:
        teardown(system["target"])


# ----- the check itself: plan-scoped request and receipt, exact receipt binding ---------------------------
def test_the_owner_canary_reads_only_the_consuming_plans_own_request_and_receipt(tmp_path):
    target = {"target_id": TARGET_ID, "state_dir": str(tmp_path / "state")}
    plan = {"plan_id": H1, "target_id": TARGET_ID, "target_descriptor": {"revision": "b" * 40}}
    other = {**plan, "plan_id": H2}
    descriptor = {"target_id": TARGET_ID, "revision": "b" * 40, "predecessor": "p" * 64}
    startup = {"instance_id": "i-1"}

    def request(for_plan, **overrides):
        return {"schema": "urn:zeus:owner-canary-request:1", "action_id": "a" * 64,
                "plan_id": for_plan["plan_id"], "plan_sha256": plan_digest(for_plan), "target_id": TARGET_ID,
                "revision": "b" * 40, "expected_descriptor": "p" * 64, "requested_at": "t", **overrides}

    def check(bound=plan):
        return owner_qualified_canary(target, descriptor, startup, plan=bound)

    assert check()["reason_code"] == "canary_owner_receipt_missing"
    assert check(None)["reason_code"] == "canary_owner_receipt_missing"
    # Another plan's request (even an identical target/revision/predecessor) or the former global slot
    # grants this plan nothing.
    TargetFiles.write_request(target, H2, request(other))
    (Path(target["state_dir"]) / LEGACY_REQUEST_FILE).write_text(json.dumps(request(plan)), encoding="utf-8")
    assert check()["reason_code"] == "canary_owner_receipt_missing" and "pending" not in check()
    # This plan's own file, but naming another plan digest, another revision or another predecessor.
    for wrong in ({"plan_sha256": "0" * 64}, {"plan_id": H2}, {"revision": "c" * 40},
                  {"expected_descriptor": "q" * 64}):
        TargetFiles.write_request(target, H1, request(plan, **wrong))
        assert check()["reason_code"] == "canary_owner_receipt_missing", wrong
    TargetFiles.write_request(target, H1, request(plan))
    assert check()["pending"] is True and check()["reason_code"] == "canary_owner_receipt_pending"
    assert check(other)["reason_code"] == "canary_owner_receipt_pending"   # H2's own request, H2's own wait
    # Another plan's passed receipt, and the former global receipt slot, never pass this plan.
    good = {"schema": "urn:zeus:owner-canary-receipt:1", "descriptor_sha256": descriptor_digest(descriptor),
            "instance_id": "i-1", "passed": True, "evidence": {"plan_id": H2}}
    TargetFiles.write_receipt(target, H2, good)
    (Path(target["state_dir"]) / "owner-canary-receipt.json").write_text(json.dumps(good), encoding="utf-8")
    assert check()["reason_code"] == "canary_owner_receipt_pending"
    # This plan's own receipt must still bind the exact descriptor and instance: stale is refused at once.
    TargetFiles.write_receipt(target, H1, {**good, "descriptor_sha256": "0" * 64})
    assert check()["reason_code"] == "canary_owner_receipt_stale" and "pending" not in check()
    TargetFiles.write_receipt(target, H1, {**good, "instance_id": "i-2"})
    assert check()["reason_code"] == "canary_owner_receipt_stale"
    TargetFiles.write_receipt(target, H1, {**good, "passed": False})
    assert check()["reason_code"] == "canary_owner_receipt_failed"
    TargetFiles.write_receipt(target, H1, good)
    assert check()["passed"] is True


def test_plan_scoped_file_names_accept_only_plan_tokens():
    assert canary_request_file(H1) == "owner-canary-request." + H1 + ".json"
    assert canary_receipt_file(H1) == "owner-canary-receipt." + H1 + ".json"
    for bad in ("../x", "a/b", "", ".hidden", None):
        with pytest.raises(ValueError):
            canary_request_file(bad)
        with pytest.raises(ValueError):
            canary_receipt_file(bad)


def test_the_actual_first_delivery_shape_with_no_predecessor_keeps_each_plans_own_wait(tmp_path):
    """The host's H1 and H2 requests both name `expected_descriptor: null` (no managed descriptor yet)."""
    target = {"target_id": TARGET_ID, "state_dir": str(tmp_path / "state")}
    h1 = {"plan_id": H1, "target_id": TARGET_ID, "target_descriptor": {"revision": "9" * 40}}
    h2 = {"plan_id": H2, "target_id": TARGET_ID, "target_descriptor": {"revision": "8" * 40}}
    for plan in (h1, h2):
        TargetFiles.write_request(target, plan["plan_id"], {
            "schema": "urn:zeus:owner-canary-request:1", "action_id": "a" * 64, "plan_id": plan["plan_id"],
            "plan_sha256": plan_digest(plan), "target_id": TARGET_ID,
            "revision": plan["target_descriptor"]["revision"], "expected_descriptor": None, "requested_at": "t"})
    consumed = {"target_id": TARGET_ID, "revision": "9" * 40, "predecessor": None}
    assert owner_qualified_canary(target, consumed, {}, plan=h1)["reason_code"] == "canary_owner_receipt_pending"
    # H2's request never covers H1's descriptor, and H1's never covers H2's.
    assert owner_qualified_canary(target, consumed, {}, plan=h2)["reason_code"] == "canary_owner_receipt_missing"
    assert owner_qualified_canary(target, {**consumed, "revision": "8" * 40}, {},
                                  plan=h1)["reason_code"] == "canary_owner_receipt_missing"
