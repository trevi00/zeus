"""Shared S7 scenario steps (`delivery.registry`): the registry and selection surface of M7 `HostDelivery`
(`application/host_delivery.py`), characterized BEFORE the V8 split moves it (DESIGN-s7 §2).

- **targets** (`register_targets`; M7 tests/test_host_delivery.py
  `test_registry_is_host_configuration_and_a_plan_can_only_name_a_registered_target`): a valid registry, the identical
  document again (`registered_at` kept, `updated_at` moved), a changed entry, a two-kind registry with a managed target,
  and every `validate_targets` refusal that reaches the application, each with the store digests unchanged.
- **plans** (`register`, and the gate a tick applies): the plan grammar, the pin grammar, the cached replay, the
  in-flight refusal, every `_register_in` refusal branch (unregistered target, first activation unbound, reserved by a
  migration, in flight) and its precedence, a conflicting plan under one id, registration before review, a plan that
  names another candidate or evaluator, and the conductor review of the author's own lead.
- **projections** (`approval`, `plan`, `status`): approved / awaiting-review / refused plans; one plan, every plan, an
  unregistered id, a store holding a labelled migration row, and the active projection carrying no bodies.
- **selection** (`tick` before any stage acts): disabled, idle, unregistered, the missing ports, the store outage,
  claiming only a registered plan's rows, target serialization, the unreviewed and the backed-off plan not starving
  another, every `_unclaimed` reason, and the `blocked` map of the plans passed over (including `scan_bounded`).

Layer: harness (never shipped)

Every double is in `s7_delivery` and LABELLED; this module never runs GitHub, a host, a process or a verifier. The rows
it writes itself are LABELLED fixtures of M7's shapes: a migration record (the `host_delivery_migrations` body
`register_migration_plan`/`stage_migration` write, only the fields `_reservation_in`, `_select` and `status` read), an
intent with a chosen stage (`new_intent` with `stage`/`held` set), a release-queue row of `ReleaseQueue.enqueue`/`finish`'s
shape, and stored plan rows of `register`'s shape. A case reached only through a path the doubles cannot take is recorded
as `{"unreachable": ...}`.
"""

from __future__ import annotations

import json
from datetime import timedelta

import s7_delivery as D

MIGRATION = {"id": "delivery-plan-old", "migration_id": "migration-1", "kind": "evaluator_migration",
             "state": "staged", "successor_release_id": "release-successor", "plan_id": None,
             "target_id": "canary-service", "at": "2026-09-22T00:00:00+00:00"}
MANAGED = {"target_id": "managed-host", "kind": "managed_fleet", "root": "/opt/zeus-fixture/managed",
           "state_dir": "/var/lib/zeus-fixture/managed-state", "service": "zeus-canary-service",
           "source": "/opt/zeus-fixture/source", "python": "/opt/zeus-fixture/python/bin/python",
           "environment_lock": "1" * 64}


def brief(result):
    return {key: result.get(key) for key in ("plan_id", "stage", "outcome", "reason_code")}


def rows(store, bucket):
    with store.transaction() as tx:
        return tx.scan(bucket)


def put(store, bucket, key, body):
    with store.transaction() as tx:
        tx.put(bucket, key, body)


def get(store, bucket, key):
    with store.transaction() as tx:
        return tx.get(bucket, key)


def data_of(store):
    """The raw store data as M7's idle-poll test compares it (`repr` of the sorted items)."""
    return repr(sorted((str(key), repr(value)) for key, value in store.data.items()))


def state(system):
    return D.snapshot(system["store"])


def register_other(api, system, plan_id, *, target_id=None, revision="5" * 40, path=None, **overrides):
    """A second reviewed release (through Releases) and its plan, registered; optionally on another target."""
    target_id = target_id or "canary-service"
    if target_id not in {row["target_id"] for row in rows(system["store"], api.BUCKET_TARGETS)}:
        system["delivery"].register_targets(D.targets_document(api, target_id=target_id))
    release = D.reviewed_release(api, system["store"], system["org"], record_candidate={
        **D.candidate(), "revision": revision, "branch": "harness/" + plan_id, "task_id": plan_id})
    plan = D.plan_document(api, release, plan_id=plan_id, target_id=target_id, **overrides)
    system["delivery"].register(plan, D.pin(path=path or "docs/zeus/operations/%s.json" % plan_id))
    return release, plan


def labelled_intent(plan_id, target_id, stage, **fields):
    """LABELLED: an intent row of `new_intent`'s identity fields with a chosen stage (what `_select` reads)."""
    return {"id": plan_id, "plan_id": plan_id, "target_id": target_id, "stage": stage, **fields}


# ---- 1. targets ------------------------------------------------------------------------------------------------
def targets(api):
    store = D.SerialStore(api)
    delivery = api.HostDelivery(store, api.organization(), clock=D.clock(api))
    system = {"store": store}
    document = D.targets_document(api)
    out = {}
    out["valid"] = D.guarded(system, delivery.register_targets, document)
    out["valid"]["rows"] = rows(store, api.BUCKET_TARGETS)
    api.advance(10)
    out["identical_again"] = D.guarded(system, delivery.register_targets, document)
    out["identical_again"]["rows"] = rows(store, api.BUCKET_TARGETS)
    api.advance(10)
    changed = {**document, "targets": [{**document["targets"][0], "service": "zeus-canary-service-2"}]}
    out["changed_entry"] = D.guarded(system, delivery.register_targets, changed)
    out["changed_entry"]["rows"] = rows(store, api.BUCKET_TARGETS)
    api.advance(10)
    two_kinds = {**document, "targets": [document["targets"][0], MANAGED]}
    out["process_and_managed"] = D.guarded(system, delivery.register_targets, two_kinds)
    out["process_and_managed"]["rows"] = [row["target_id"] + ":" + row["kind"]
                                          for row in rows(store, api.BUCKET_TARGETS)]
    entry = document["targets"][0]
    refusals = {
        "schema": {**document, "schema": "urn:zeus:other:1"}, "not_a_document": [],
        "extra_root_field": {**document, "extra": 1}, "missing_targets": {"schema": api.REGISTRY_SCHEMA},
        "no_targets": {**document, "targets": []},
        "too_many_targets": {**document, "targets": [{**entry, "target_id": "svc-%02d" % i} for i in range(17)]},
        "duplicate_ids": {**document, "targets": [entry, entry]},
        "kind_docker": {**document, "targets": [{**entry, "kind": "docker"}]},
        "bad_target_id": {**document, "targets": [{**entry, "target_id": "../other"}]},
        "blank_root": {**document, "targets": [{**entry, "root": "  "}]},
        "long_state_dir": {**document, "targets": [{**entry, "state_dir": "s" * 401}]},
        "bad_service": {**document, "targets": [{**entry, "service": "rm -rf /"}]},
        "extra_target_field": {**document, "targets": [{**entry, "extra": "x"}]},
        "missing_target_field": {**document, "targets": [{k: v for k, v in entry.items() if k != "service"}]},
        "target_not_a_mapping": {**document, "targets": ["canary-service"]},
        "managed_relative_root": {**document, "targets": [{**MANAGED, "root": "relative/managed"}]},
        "managed_overlap": {**document, "targets": [{**MANAGED, "state_dir": MANAGED["root"] + "/state"}]},
        "managed_missing_lock": {**document, "targets": [{k: v for k, v in MANAGED.items()
                                                          if k != "environment_lock"}]},
        "managed_bad_lock": {**document, "targets": [{**MANAGED, "environment_lock": "1" * 40}]},
        "managed_systemd_foreign_unit": {**document, "targets": [{**MANAGED, "kind": "managed_fleet_systemd",
                                                                  "service": "some-other-unit"}]},
    }
    out["refusals"] = {name: D.guarded(system, delivery.register_targets, doc) for name, doc in refusals.items()}
    # A plan can only name a registered target (M7: a delivery with no ports, a fresh store).
    fresh = {"store": D.SerialStore(api), "org": api.organization()}
    release = D.reviewed_release(api, fresh["store"], fresh["org"])
    fresh["delivery"] = api.HostDelivery(fresh["store"], fresh["org"])
    out["plan_names_unregistered_target"] = D.guarded(
        fresh, fresh["delivery"].register, D.plan_document(api, release, target_id="unregistered-target"), D.pin())
    out["plan_names_unregistered_target"]["plans"] = rows(fresh["store"], api.BUCKET_PLANS)
    return out


# ---- 2. plans --------------------------------------------------------------------------------------------------
def plan_grammar(api):
    system = D.build(api, register_plan=False)
    delivery, good = system["delivery"], system["plan"]
    out = {"canonical": api.validate_plan(good)}
    mutations = [("plan_id", "not a token"), ("release_id", "not a token"), ("target_id", "../other"),
                 ("revision", "z" * 40), ("tree", "c" * 63), ("tree", "c" * 39), ("tree", "c" * 41),
                 ("tree", "c" * 65), ("tree", "C" * 40), ("tree", "g" * 40), ("tree", " " + "c" * 40),
                 ("tree", 40), ("policy_hash", "1" * 40), ("policy_hash", 1), ("expected_descriptor", "e" * 40),
                 ("expected_descriptor", "short"), ("repository", "https://github.com/o/r"),
                 ("required_checks", []), ("required_checks", [D.CHECK, D.CHECK]),
                 ("required_checks", ["x" * 121]), ("canary_check_id", "rm -rf /"),
                 ("ci_timeout_seconds", 1), ("ci_timeout_seconds", True), ("consumption_timeout_seconds", 10 ** 9),
                 ("schema", "urn:zeus:other:1")]
    cases = []
    for field, value in mutations:
        refused = D.guarded(system, delivery.register, {**good, field: value}, D.pin())
        message = refused.get("message", "")
        cases.append({"field": field, "value": repr(value)[:60], **refused,
                      "leaks_value": str(value) in message, "leaks_canary_text": D.CANARY_TEXT in message})
    out["mutations"] = cases
    descriptor = good["target_descriptor"]
    out["descriptor_shapes"] = {name: D.guarded(system, delivery.register, {**good, "target_descriptor": value}, D.pin())
                                for name, value in {
        "missing_profile_digest": {"revision": descriptor["revision"], "worker_image": descriptor["worker_image"]},
        "bad_profile_digest": {**descriptor, "profile_digest": "e" * 40},
        "bad_image": {**descriptor, "worker_image": "not an image!"},
        "bad_revision": {**descriptor, "revision": "z" * 40},
        "not_a_mapping": "unchanged"}.items()}
    out["extra_field"] = D.guarded(system, delivery.register, {**good, "extra": 1}, D.pin())
    out["not_a_document"] = D.guarded(system, delivery.register, [], D.pin())
    pins = {"bad_revision": {**D.pin(), "revision": "z" * 40}, "traversal": D.pin(path="../escape.json"),
            "absolute": D.pin(path="/etc/plan.json"), "bad_sha": {**D.pin(), "sha256": "1" * 40},
            "extra_field": {**D.pin(), "extra": 1}, "missing_field": {"revision": "f" * 40, "path": D.PLAN_PATH},
            "not_a_mapping": "pin"}
    out["pins"] = {name: D.guarded(system, delivery.register, good, value) for name, value in pins.items()}
    out["tree_sha1_accepted"] = D.guarded(system, delivery.register, {**good, "plan_id": "plan-sha1", "tree": "c" * 40},
                                          D.pin())
    out["plans_after"] = [row["plan_id"] for row in rows(system["store"], api.BUCKET_PLANS)]
    return out


def plan_registration(api):
    out = {}
    # idempotent, and an in-flight delivery is never edited (M7 test_registration_is_idempotent_...)
    system = D.build(api, register_plan=False)
    delivery, plan = system["delivery"], system["plan"]
    first = delivery.register(plan, D.pin())
    plans_first = rows(system["store"], api.BUCKET_PLANS)
    api.advance(30)
    again = delivery.register(plan, D.pin())
    out["cached_replay"] = {"first": first, "again": again, "plans_kept": rows(system["store"], api.BUCKET_PLANS) == plans_first}
    ticked = delivery.tick()
    out["ticked_into_flight"] = brief(ticked)
    moved = {**plan, "target_descriptor": {**plan["target_descriptor"], "profile_digest": "0" * 64}}
    out["edit_in_flight"] = D.guarded(system, delivery.register, moved, D.pin())
    out["edit_in_flight"]["plan_row_unchanged"] = get(system["store"], api.BUCKET_PLANS, plan["plan_id"])["plan"] == plan
    out["identical_other_pin_in_flight"] = D.guarded(system, delivery.register, plan, D.pin(revision="1" * 40))
    unbound = {**plan, "expected_descriptor": None, "target_descriptor": {**plan["target_descriptor"], "worker_image": "unchanged"}}
    out["precedence_in_flight_before_unbound"] = D.guarded(system, delivery.register, unbound, D.pin())
    # the intent goes back to `registered` (a LABELLED row edit): the plan may be edited again
    intent = get(system["store"], api.BUCKET_INTENTS, plan["plan_id"])
    put(system["store"], api.BUCKET_INTENTS, plan["plan_id"], {**intent, "stage": api.REGISTERED})
    out["edit_while_registered"] = D.guarded(system, delivery.register, moved, D.pin())
    out["edit_while_registered"]["registered_at_kept"] = (
        get(system["store"], api.BUCKET_PLANS, plan["plan_id"])["registered_at"] == first_registered(plans_first))
    out["edit_while_registered"]["plan_row"] = get(system["store"], api.BUCKET_PLANS, plan["plan_id"])
    # a conflicting plan under one id with no intent yet replaces the stored plan; a different pin does too
    other = D.build(api, register_plan=False)
    other["delivery"].register(other["plan"], D.pin())
    api.advance(5)
    conflicting = {**other["plan"], "ci_timeout_seconds": 600}
    out["conflicting_plan_no_intent"] = D.guarded(other, other["delivery"].register, conflicting, D.pin())
    out["conflicting_plan_no_intent"]["plan_row"] = get(other["store"], api.BUCKET_PLANS, other["plan"]["plan_id"])
    out["other_pin_no_intent"] = D.guarded(other, other["delivery"].register, conflicting, D.pin(revision="2" * 40))
    out["other_pin_no_intent"]["pin"] = get(other["store"], api.BUCKET_PLANS, other["plan"]["plan_id"])["pin"]
    # an in-flight delivery held at awaiting_review is in flight too (the intent left `registered`)
    review = D.build(api, lead=False, conductor=False)
    out["awaiting_review_tick"] = brief(review["delivery"].tick())
    out["edit_at_awaiting_review"] = D.guarded(review, review["delivery"].register,
                                               {**review["plan"], "ci_timeout_seconds": 600}, D.pin())
    return out


def first_registered(plans):
    return plans[0]["registered_at"]


def register_refusal_branches(api):
    out = {}
    system = D.build(api, register_plan=False)
    delivery, plan = system["delivery"], system["plan"]
    unbound = {**plan, "expected_descriptor": None, "target_descriptor": {**plan["target_descriptor"], "worker_image": "unchanged"}}
    unbound_profile = {**plan, "target_descriptor": {**plan["target_descriptor"], "profile_digest": "unchanged"}}
    out["unregistered_target"] = D.guarded(system, delivery.register, {**plan, "target_id": "nowhere"}, D.pin())
    out["unregistered_target_before_unbound"] = D.guarded(system, delivery.register, {**unbound, "target_id": "nowhere"}, D.pin())
    out["first_activation_unbound_image"] = D.guarded(system, delivery.register, unbound, D.pin())
    out["first_activation_unbound_profile"] = D.guarded(system, delivery.register, unbound_profile, D.pin())
    out["unchanged_with_expected_predecessor"] = D.guarded(
        system, delivery.register, {**unbound, "plan_id": "plan-upgrade", "expected_descriptor": "1" * 64}, D.pin())
    # an already stored unbound plan stays readable history: the identical one replays as cached
    stored = api.validate_plan({**unbound, "plan_id": "plan-history"})
    put(system["store"], api.BUCKET_PLANS, "plan-history", {
        "id": "plan-history", "plan_id": "plan-history", "plan": stored, "plan_sha256": api.plan_digest(stored),
        "pin": D.pin(), "target_id": stored["target_id"], "registered_at": "2026-09-22T00:00:00+00:00",
        "updated_at": "2026-09-22T00:00:00+00:00"})
    out["unbound_history_replays_cached"] = D.guarded(system, delivery.register, {**unbound, "plan_id": "plan-history"}, D.pin())
    out["unbound_history_other_pin"] = D.guarded(system, delivery.register, {**unbound, "plan_id": "plan-history"},
                                                 D.pin(revision="3" * 40))
    # a target reserved by an unfinished migration admits no NEW plan through `register`
    put(system["store"], api.BUCKET_MIGRATIONS, MIGRATION["id"], dict(MIGRATION))
    out["reserved_staged"] = D.guarded(system, delivery.register, plan, D.pin())
    out["reserved_before_unbound"] = D.guarded(system, delivery.register, unbound, D.pin())
    put(system["store"], api.BUCKET_MIGRATIONS, MIGRATION["id"], {**MIGRATION, "state": "registered", "plan_id": plan["plan_id"]})
    out["reserved_registered_own_plan_via_register"] = D.guarded(system, delivery.register, plan, D.pin())
    put(system["store"], api.BUCKET_MIGRATIONS, MIGRATION["id"], {**MIGRATION, "state": "active"})
    out["migration_active_reserves_nothing"] = D.guarded(system, delivery.register, plan, D.pin())
    put(system["store"], api.BUCKET_MIGRATIONS, "delivery-plan-elsewhere",
        {**MIGRATION, "id": "delivery-plan-elsewhere", "target_id": "another-target"})
    out["reservation_on_another_target"] = D.guarded(system, delivery.register, {**plan, "plan_id": "plan-two"}, D.pin())
    put(system["store"], api.BUCKET_MIGRATIONS, MIGRATION["id"], dict(MIGRATION))
    out["identical_stored_plan_replays_though_reserved"] = D.guarded(system, delivery.register, plan, D.pin())
    out["in_flight_refusal_before_reservation"] = None
    ticked = D.build(api)
    ticked["delivery"].tick()
    put(ticked["store"], api.BUCKET_MIGRATIONS, MIGRATION["id"], dict(MIGRATION))
    out["in_flight_refusal_before_reservation"] = D.guarded(
        ticked, ticked["delivery"].register, {**ticked["plan"], "ci_timeout_seconds": 600}, D.pin())
    return out


def plan_review_gate(api):
    out = {}
    # registration before review projects awaiting_review and touches nothing (M7)
    system = D.build(api, lead=False, conductor=False)
    result = system["delivery"].tick()
    out["registration_before_review"] = {
        "tick": result, "publishes": system["github"].publishes, "merges": system["github"].merges,
        "queue_rows": rows(system["store"], "release_queue"),
        "controller_lock": get(system["store"], "deployment_locks", "controller"),
        "status_stage": system["delivery"].status()["deliveries"][0]["stage"], "host_calls": system["host"].calls}
    # a plan that names another candidate or evaluator is refused without side effects (M7 parametrization)
    mismatch = {}
    for field, value in (("revision", "1" * 40), ("tree", "2" * 64), ("policy_hash", "3" * 64),
                         ("repository", "github:other-owner/other-repo")):
        one = D.build(api, plan_overrides={field: value})
        result = one["delivery"].tick()
        mismatch[field] = {"tick": result, "publishes": one["github"].publishes,
                           "observations": one["github"].observations,
                           "intent_stage": D.intent_of(one)["stage"], "queue_rows": rows(one["store"], "release_queue")}
    out["another_candidate_or_evaluator"] = mismatch
    # only the conductor review of the author's own lead opens the delivery (M7)
    one = D.build(api, conductor=False)
    first = one["delivery"].tick()
    releases = api.releases(one["store"])
    releases.review(one["release"]["id"], "conductor", D.REVISION, True, "fixture-conductor-review-evidence")
    releases.verify(one["release"]["id"], D.REVISION, one["release"]["policy_hash"],
                    {"tests": {"passed": True, "evidence": "fixture-incumbent-check-receipt"}})
    out["conductor_review_opens"] = {"before": brief(first), "after": brief(one["delivery"].tick())}
    no_lead = D.build(api, lead=False)
    out["conductor_without_lead"] = brief(no_lead["delivery"].tick())
    # reviewed but not yet verified: the verifier is a port; without one the release waits in `verifying`
    unverified = D.build(api, verified=False)
    out["reviewed_unverified_without_verifier"] = [brief(unverified["delivery"].tick()) for _ in range(2)]
    out["reviewed_unverified_without_verifier"].append(D.intent_of(unverified)["reason_code"])
    # both reviews exist but the release record is not (or no longer) `reviewed`: LABELLED status edit, still a wait
    unreviewed = D.build(api, verified=False)
    row = get(unreviewed["store"], "releases", unreviewed["release"]["id"])
    put(unreviewed["store"], "releases", row["id"], {**row, "status": "candidate"})
    out["reviews_with_a_candidate_status"] = {"approval": unreviewed["delivery"].approval(unreviewed["plan"]),
                                              "tick": brief(unreviewed["delivery"].tick())}
    # a rejected review refuses the plan (the release record itself says so)
    rejected = D.build(api, lead=False, conductor=False)
    releases = api.releases(rejected["store"])
    out["rejected_lead_review"] = call_review(releases, rejected, "lead:improvement", False)
    out["rejected_lead_review"]["tick"] = brief(rejected["delivery"].tick())
    return out


def call_review(releases, system, actor, accepted):
    out = D.call(releases.review, system["release"]["id"], actor, D.REVISION, accepted, "fixture-review-evidence")
    if "value" in out:
        out = {"status": out["value"].get("status")}
    return out


def plans(api):
    return {"grammar": plan_grammar(api), "registration": plan_registration(api),
            "refusal_branches": register_refusal_branches(api), "review_gate": plan_review_gate(api)}


# ---- 3. projections --------------------------------------------------------------------------------------------
def projections(api):
    out = {}
    approved = D.build(api, register_plan=False)
    delivery = approved["delivery"]
    before = state(approved)
    out["approval"] = {
        "approved_verified": delivery.approval(approved["plan"]),
        "written_nothing": state(approved) == before}
    reviewed = D.build(api, verified=False, register_plan=False)
    out["approval"]["approved_reviewed_only"] = reviewed["delivery"].approval(reviewed["plan"])
    awaiting = D.build(api, lead=False, conductor=False, register_plan=False)
    out["approval"]["awaiting_review"] = awaiting["delivery"].approval(awaiting["plan"])
    conductor_only = D.build(api, lead=False, register_plan=False)
    out["approval"]["awaiting_review_no_lead"] = conductor_only["delivery"].approval(conductor_only["plan"])
    out["approval"]["refused_revision"] = delivery.approval({**approved["plan"], "revision": "1" * 40})
    out["approval"]["refused_tree"] = delivery.approval({**approved["plan"], "tree": "2" * 64})
    out["approval"]["refused_policy"] = delivery.approval({**approved["plan"], "policy_hash": "3" * 64})
    out["approval"]["refused_repository"] = delivery.approval({**approved["plan"], "repository": "github:other-owner/other-repo"})
    out["approval"]["refused_release_missing"] = delivery.approval({**approved["plan"], "release_id": "no-such-release"})
    out["approval"]["invalid_document"] = D.call(delivery.approval, {**approved["plan"], "extra": 1})
    # status for one plan, every plan, an unregistered id, an empty store (M7 status projection)
    system = D.build(api)
    out["plan_row"] = {"registered": system["delivery"].plan(system["plan"]["plan_id"]),
                       "unregistered": system["delivery"].plan("nope")}
    out["status_registered_untouched"] = system["delivery"].status(system["plan"]["plan_id"])
    register_other(api, system, "delivery-plan-2", target_id="second-service")
    out["status_every_plan"] = system["delivery"].status()
    out["status_unregistered_id"] = system["delivery"].status("nope")
    empty = api.HostDelivery(D.SerialStore(api), api.organization(), clock=D.clock(api))
    out["status_empty_store"] = {"all": empty.status(), "one": empty.status("nope")}
    # a store holding a labelled migration row
    put(system["store"], api.BUCKET_MIGRATIONS, "delivery-plan-old", {**MIGRATION, "plan_id": "delivery-plan-2"})
    put(system["store"], api.BUCKET_INTENTS, "delivery-plan-2",
        {**(D.intent_of(system, "delivery-plan-2") or labelled_intent("delivery-plan-2", "second-service", api.REGISTERED)),
         "held": "migration_unacknowledged"})
    out["status_with_migration_all"] = system["delivery"].status()
    out["status_with_migration_matching_plan"] = system["delivery"].status("delivery-plan-2")
    out["status_with_migration_other_plan"] = system["delivery"].status(system["plan"]["plan_id"])
    out["status_with_migration_old_id"] = system["delivery"].status("delivery-plan-old")
    only = api.HostDelivery(D.SerialStore(api), api.organization(), clock=D.clock(api))
    put(only.store, api.BUCKET_MIGRATIONS, "delivery-plan-old", dict(MIGRATION))
    out["status_migration_only_all"] = only.status()
    out["status_migration_only_unregistered"] = only.status("nope")
    # an active delivery: identities and digests, but no bodies (M7 test_the_status_projection_carries_...)
    active = D.build(api)
    drive = D.drive(active)
    projection = active["delivery"].status()
    text = json.dumps(projection)
    view = projection["deliveries"][0]
    out["active_projection"] = {
        "reached": drive[-1]["stage"], "projection": projection,
        "no_canary_text": D.CANARY_TEXT not in text, "no_runtime_root": D.RUNTIME_ROOT not in text,
        "no_state_root": D.STATE_ROOT not in text, "no_service_name": "zeus-canary-service" not in text,
        "consumed": view["consumed"], "descriptor_matches_intent": (
            view["active_descriptor_sha256"] == D.intent_of(active)["descriptor_sha256"]),
        "missing": active["delivery"].status("no-such-plan")}
    D.stop_target(active)
    return out


# ---- 4. selection ----------------------------------------------------------------------------------------------
def disabled_idle_unregistered(api):
    out = {}
    system = D.build(api, enabled=False)
    result = system["delivery"].tick()
    out["disabled"] = {"tick": result, "intent": D.intent_of(system), "observations": system["github"].observations,
                       "queue_rows": rows(system["store"], "release_queue"), "state": state(system)}
    out["disabled_again_writes_nothing"] = D.guarded(system, system["delivery"].tick)
    out["disabled_named_plan"] = D.guarded(system, system["delivery"].tick, system["plan"]["plan_id"])
    out["disabled_unregistered_plan"] = D.guarded(system, system["delivery"].tick, "nope")
    # while disabled, a plan awaiting review is still projected read-only (no intent is created)
    review = D.build(api, enabled=False, lead=False, conductor=False)
    out["disabled_awaiting_review"] = D.guarded(review, review["delivery"].tick)
    out["disabled_awaiting_review"]["intent"] = D.intent_of(review)
    enabled = D.build(api, register_plan=False)
    out["enabled_no_plans"] = D.guarded(enabled, enabled["delivery"].tick)
    out["enabled_unregistered_plan"] = D.guarded(enabled, enabled["delivery"].tick, "nope")
    return out


def missing_ports(api):
    out = {}
    system = D.build(api, canaries={})
    system["delivery"].hosts = {}
    results = D.drive(system, until=api.DRAIN_INTENDED, limit=8)
    blocked = system["delivery"].tick()
    out["host_and_canary_missing"] = {"visited": D.visited(results), "last": brief(results[-1]),
                                      "blocked": blocked, "descriptor": D.descriptor_of(system)}
    no_github = D.build(api)
    no_github["delivery"].github = None
    out["github_missing"] = {"tick": [brief(no_github["delivery"].tick()) for _ in range(2)],
                             "intent": D.intent_of(no_github)}
    other_kind = D.build(api, kind="process")
    other_kind["delivery"].hosts = {"systemd_unit": D.MemoryHost(api)}
    results = D.drive(other_kind, until=api.DRAIN_INTENDED, limit=8)
    out["host_port_for_another_kind"] = {"last": brief(results[-1]), "blocked": brief(other_kind["delivery"].tick())}
    return out


def store_outage(api):
    system = D.build(api)
    system["delivery"].tick()
    broken = D.BrokenStore(system["store"])
    outage = api.HostDelivery(broken, system["org"], github=system["github"], hosts={"process": system["host"]},
                              clock=D.clock(api), enabled=True, queue=api.queue(broken))
    broken.failing = True
    result = outage.tick()
    named = outage.tick(system["plan"]["plan_id"])
    broken.failing = False
    return {"outage": result, "outage_named_plan": brief(named), "status_after": outage.status()["deliveries"][0]["stage"],
            "state_after_outage_unchanged_stage": D.intent_of(system)["stage"]}


def idle_and_nested(api):
    system = D.build(api)
    results = D.drive(system)
    active = system["delivery"].status()["deliveries"][0]["stage"]
    before = D.snapshot(system["store"], D.BUCKETS)
    data_before = data_of(system["store"])
    idle = system["delivery"].tick()
    out = {"visited": D.visited(results), "ticks": [brief(r) for r in results], "final": results[-1],
           "status_stage": active, "idle": idle, "idle_wrote_nothing": (
               D.snapshot(system["store"], D.BUCKETS) == before
               and data_of(system["store"]) == data_before),
           "github": {"publishes": system["github"].publishes, "merges": system["github"].merges,
                      "qualifications": len(system["github"].qualifications)},
           "descriptor": D.descriptor_of(system), "active_pointer": get(system["store"], "deployment", "active"),
           "host_calls": sorted(set(system["host"].calls)), "host_instance_running": system["host"].running(system["target"]),
           "release_status": get(system["store"], "releases", system["release"]["id"])["status"]}
    D.stop_target(system)
    return out


def claims_and_serialization(api):
    out = {}
    system = D.build(api)
    other = D.reviewed_release(api, system["store"], system["org"], record_candidate={
        **D.candidate(), "revision": "5" * 40, "branch": "harness/other", "task_id": "other"})
    api.queue(system["store"]).enqueue(other["id"], "another controller's work")
    result = system["delivery"].tick()
    foreign = get(system["store"], "release_queue", other["id"])
    out["claims_only_registered_rows"] = {"tick": brief(result), "release_is_plans": result["release_id"] == system["release"]["id"],
                                          "foreign_row": {k: foreign.get(k) for k in ("status", "attempt")}}
    # two plans on one target serialize; the newcomer is recorded as waiting, not failed
    system = D.build(api, host=D.MemoryHost(api, fault="no_receipt"))   # labelled: the instance never reports
    D.drive(system, until=api.AWAITING_CONSUMPTION, limit=8)
    register_other(api, system, "delivery-plan-2")
    result = system["delivery"].tick()
    out["two_plans_one_target"] = {"tick": brief(result), "blocked": result["blocked"],
                                   "second_stage": system["delivery"].status()["deliveries"][1]["stage"]}
    named = system["delivery"].tick("delivery-plan-2")
    out["named_plan_on_a_busy_target"] = {"tick": brief(named), "blocked": named["blocked"]}
    D.stop_target(system)
    # an unrelated plan is not starved by the busy target
    system = D.build(api, host=D.MemoryHost(api, fault="no_receipt"))   # labelled: the instance never reports
    D.drive(system, until=api.AWAITING_CONSUMPTION, limit=8)
    register_other(api, system, "delivery-plan-3", target_id="third-service")
    result = system["delivery"].tick()
    out["busy_target_does_not_starve_another_target"] = {"tick": brief(result), "blocked": result["blocked"]}
    second = system["delivery"].tick()
    out["busy_target_does_not_starve_another_target"]["next"] = brief(second)
    D.stop_target(system)
    # two actionable plans: one advances, the other waits as `controller_serialized`
    system = D.build(api)
    register_other(api, system, "delivery-plan-2", target_id="second-service")
    result = system["delivery"].tick()
    out["two_actionable_plans"] = {"tick": brief(result), "blocked": result["blocked"]}
    named = system["delivery"].tick("delivery-plan-2")
    out["two_actionable_plans"]["named"] = {"tick": brief(named), "blocked": named["blocked"]}
    return out


def review_and_backoff(api):
    out = {}
    system = D.build(api, lead=False, conductor=False)   # plan 1: no reviews at all
    delivery = system["delivery"]
    register_other(api, system, "delivery-plan-2", target_id="second-service")
    result = delivery.tick()
    out["awaiting_review_does_not_starve"] = {"tick": brief(result), "blocked": result["blocked"]}
    published = delivery.tick()
    out["awaiting_review_does_not_starve"]["next"] = brief(published)
    out["awaiting_review_does_not_starve"]["publishes"] = system["github"].publishes
    out["awaiting_review_does_not_starve"]["plan1_stage"] = delivery.status("delivery-plan-1")["deliveries"][0]["stage"]
    out["awaiting_review_does_not_starve"]["plan1_queue_row"] = get(system["store"], "release_queue", system["release"]["id"])
    # a queue row in backoff or exhausted does not starve another target (M7)
    system = D.build(api)
    delivery = system["delivery"]
    register_other(api, system, "delivery-plan-2", target_id="second-service")
    queue = api.queue(system["store"])
    queue.enqueue(system["release"]["id"], "fixture")
    claim = queue.claim()
    queue.finish(claim, {"status": "retry", "reason": "fixture injected retry"})   # labelled: plan 1's row in backoff
    result = delivery.tick()
    out["backoff"] = {"tick": brief(result), "blocked": result["blocked"]}
    row = get(system["store"], "release_queue", system["release"]["id"])
    put(system["store"], "release_queue", system["release"]["id"], {**row, "status": "blocked", "reason": "fixture owner stop"})
    later = delivery.tick()
    out["owner_stop"] = {"tick": brief(later), "blocked": later["blocked"]}
    row = get(system["store"], "release_queue", system["release"]["id"])
    put(system["store"], "release_queue", system["release"]["id"],
        {**row, "status": "queued", "attempt": api.POLICY.release_max_attempts, "retry_at": None})
    exhausted = delivery.tick()
    out["exhausted"] = {"tick": brief(exhausted), "blocked": exhausted["blocked"]}
    return out


def unclaimed_reasons(api):
    """Each reason `_unclaimed` names, reached with the only plan of a store so it is selected as the waiting plan."""
    out = {}
    def rid(system):
        return system["release"]["id"]

    def row_case(name, row_of):
        system = D.build(api)
        put(system["store"], "release_queue", rid(system), row_of(system))
        before = D.snapshot(system["store"], D.BUCKETS)
        result = system["delivery"].tick()
        out[name] = {"tick": result, "github_calls": [system["github"].publishes, system["github"].observations],
                     "row": get(system["store"], "release_queue", rid(system)),
                     "wrote_queue_or_lock": D.snapshot(system["store"], ("release_queue", "deployment_locks"))
                     != {b: v for b, v in before.items() if b in ("release_queue", "deployment_locks")}}

    for status in ("blocked", "failed", "cancelled", "done", "active", "rolled_back"):
        row_case("release_queue_" + status, lambda s, st=status: {"id": rid(s), "status": st, "attempt": 1, "at": "2026-09-22T00:00:00+00:00", "reason": "fixture"})
    row_case("release_attempts_exhausted_alone", lambda s: {
        "id": rid(s), "status": "queued", "attempt": api.POLICY.release_max_attempts, "at": "2026-09-22T00:00:00+00:00",
        "reason": "fixture"})   # `claim` itself marks the exhausted row failed, so the tick reports the queue status
    row_case("release_retry_not_due", lambda s: {
        "id": rid(s), "status": "retry", "attempt": 1, "at": "2026-09-22T00:00:00+00:00",
        "retry_at": (api.now() + timedelta(seconds=3600)).isoformat(), "reason": "fixture"})
    row_case("retry_due_is_claimable", lambda s: {"id": rid(s), "status": "retry", "attempt": 1, "at": "2026-09-22T00:00:00+00:00",
                                                   "retry_at": "2026-09-21T00:00:00+00:00", "reason": "fixture"})
    # the release's own row running under a live lease: the waiting reason and the unclaimed reason agree
    def leased(s):
        put(s["store"], "deployment_locks", "controller", {"release_id": rid(s), "owner": "fixture-other-controller",
                                                            "lease_until": (api.now() + timedelta(seconds=3600)).isoformat()})
        return {"id": rid(s), "status": "running", "attempt": 1, "owner": "fixture-other-controller", "generation": 1,
                "at": "2026-09-22T00:00:00+00:00", "lease_until": (api.now() + timedelta(seconds=3600)).isoformat(),
                "reason": "fixture"}

    row_case("own_row_lease_held", leased)
    row_case("own_row_running_without_the_lock_is_claimed", lambda s: {
        "id": rid(s), "status": "running", "attempt": 1, "owner": "fixture-other-controller", "generation": 1,
        "at": "2026-09-22T00:00:00+00:00", "lease_until": (api.now() + timedelta(seconds=3600)).isoformat(),
        "reason": "fixture"})
    row_case("own_row_lease_expired_is_claimed", lambda s: {"id": rid(s), "status": "running", "attempt": 1, "owner": "fixture-old-controller",
                                                             "generation": 1, "at": "2026-09-22T00:00:00+00:00",
                                                             "lease_until": "2026-09-21T00:00:00+00:00", "reason": "fixture"})
    # another controller holds the single host lease over ANOTHER release
    system = D.build(api)
    other = D.reviewed_release(api, system["store"], system["org"], record_candidate={
        **D.candidate(), "revision": "5" * 40, "branch": "harness/other", "task_id": "other"})
    queue = api.queue(system["store"])
    queue.enqueue(other["id"], "another controller's work")
    held = queue.claim()
    result = system["delivery"].tick()
    out["controller_lease_held_by_another_release"] = {
        "tick": result, "lock": get(system["store"], "deployment_locks", "controller"),
        "own_row": get(system["store"], "release_queue", rid(system)), "other_generation": held["generation"],
        "github_calls": [system["github"].publishes, system["github"].observations]}
    exhausted_row = get(system["store"], "release_queue", rid(system))
    out["controller_lease_held_by_another_release"]["queued_row_after_tick"] = exhausted_row
    exhausted = D.build(api)
    other = D.reviewed_release(api, exhausted["store"], exhausted["org"], record_candidate={
        **D.candidate(), "revision": "5" * 40, "branch": "harness/other", "task_id": "other"})
    api.queue(exhausted["store"]).enqueue(other["id"], "another controller's work")
    api.queue(exhausted["store"]).claim()
    put(exhausted["store"], "release_queue", rid(exhausted), {
        "id": rid(exhausted), "status": "queued", "attempt": api.POLICY.release_max_attempts,
        "at": "2026-09-22T00:00:00+00:00", "reason": "fixture"})
    result = exhausted["delivery"].tick()
    out["release_attempts_exhausted"] = {"tick": result, "row": get(exhausted["store"], "release_queue", rid(exhausted))}
    api.advance(200)   # past the lease: the delivery may now claim its own row
    later = system["delivery"].tick()
    out["controller_lease_held_by_another_release"]["after_lease_expiry"] = brief(later)
    # a claim refused by the fence itself is a queue refusal, not a wait
    fenced = D.build(api)
    put(fenced["store"], "release_queue", rid(fenced), {"id": rid(fenced), "status": "queued", "attempt": 0, "generation": 5,
                                                         "at": "2026-09-22T00:00:00+00:00", "reason": "fixture"})
    put(fenced["store"], "execution_fences", "release_queue:" + rid(fenced), {"generation": 9, "owner": "fixture-newer"})
    out["fence_ahead_of_the_row"] = {"tick": fenced["delivery"].tick(), "row": get(fenced["store"], "release_queue", rid(fenced))}
    return out


def blocked_map(api):
    out = {}
    # stages that are terminal or stopped, a held migration successor, a reserved target, a busy target
    system = D.build(api)
    ids = {}
    for name, stage in (("a-active", api.ACTIVE), ("b-blocked", api.BLOCKED), ("c-rolled", api.ROLLED_BACK),
                        ("d-failed", "failed"), ("e-withdrawn", "withdrawn")):
        release, other = register_other(api, system, "plan-" + name, target_id="target-" + name, revision=str(len(ids) + 1) * 40)
        put(system["store"], api.BUCKET_INTENTS, other["plan_id"], labelled_intent(other["plan_id"], other["target_id"], stage))
        ids[name] = other["plan_id"]
    _, held = register_other(api, system, "plan-f-held", target_id="target-f-held", revision="6" * 40)
    put(system["store"], api.BUCKET_INTENTS, held["plan_id"], labelled_intent(held["plan_id"], held["target_id"], api.REGISTERED,
                                                                            held="migration_unacknowledged"))
    _, reserved = register_other(api, system, "plan-g-reserved", target_id="target-g-reserved", revision="7" * 40)
    put(system["store"], api.BUCKET_MIGRATIONS, "plan-old", {**MIGRATION, "id": "plan-old", "target_id": "target-g-reserved",
                                                            "plan_id": "plan-elsewhere"})
    _, busy_holder = register_other(api, system, "plan-h-inflight", target_id="target-h-busy", revision="8" * 40)
    put(system["store"], api.BUCKET_INTENTS, busy_holder["plan_id"], labelled_intent(
        busy_holder["plan_id"], busy_holder["target_id"], api.SWITCHING))
    _, waiting = register_other(api, system, "plan-i-waiting", target_id="target-h-busy", revision="0" * 40)
    result = system["delivery"].tick()
    out["passed_over"] = {"tick": result, "blocked": result["blocked"]}
    # the same store, only the migration-reserved and busy plans left: nothing to act on -> idle with the map
    idle = D.build(api, register_plan=False)
    _, reserved_own = register_other(api, idle, "plan-own", target_id="target-own")
    put(idle["store"], api.BUCKET_MIGRATIONS, "plan-old", {**MIGRATION, "id": "plan-old", "target_id": "target-own", "plan_id": "plan-own"})
    result = idle["delivery"].tick()
    out["reserved_for_this_plans_own_migration"] = {"tick": brief(result), "blocked": result["blocked"]}
    stopped = D.build(api, register_plan=False)
    _, one = register_other(api, stopped, "plan-one", target_id="target-one")
    put(stopped["store"], api.BUCKET_INTENTS, "plan-one", labelled_intent("plan-one", "target-one", api.BLOCKED))
    result = stopped["delivery"].tick()
    out["nothing_actionable_is_idle"] = {"tick": result}
    result = stopped["delivery"].tick("plan-one")
    out["named_stopped_plan_is_idle"] = {"tick": result}
    # the scan bound: MAX_SCAN plans are read, the rest are recorded as scan_bounded
    bounded = D.build(api, register_plan=False)
    base = bounded["release"]
    template = api.validate_plan(D.plan_document(api, base, plan_id="zz-real"))
    bounded["delivery"].register(template, D.pin())
    for index in range(64):
        plan_id = "p-%03d" % index
        stored = {**template, "plan_id": plan_id}
        put(bounded["store"], api.BUCKET_PLANS, plan_id, {
            "id": plan_id, "plan_id": plan_id, "plan": stored, "plan_sha256": api.plan_digest(stored), "pin": D.pin(),
            "target_id": stored["target_id"], "registered_at": "2026-09-22T00:00:00+00:00",
            "updated_at": "2026-09-22T00:00:00+00:00"})
        put(bounded["store"], api.BUCKET_INTENTS, plan_id, labelled_intent(plan_id, stored["target_id"], api.ACTIVE))
    result = bounded["delivery"].tick()
    reasons = {}
    for reason in result["blocked"].values():
        reasons[reason] = reasons.get(reason, 0) + 1
    out["scan_bounded"] = {"tick": brief(result), "blocked_by_reason": reasons, "last": result["blocked"]["zz-real"],
                           "first": result["blocked"]["p-000"]}
    # a delivery already ROLLING BACK is owed work: selected even though its queue row is blocked
    rolling = D.build(api)
    put(rolling["store"], api.BUCKET_INTENTS, rolling["plan"]["plan_id"], labelled_intent(
        rolling["plan"]["plan_id"], rolling["plan"]["target_id"], api.ROLLING_BACK))
    put(rolling["store"], "release_queue", rolling["release"]["id"], {"id": rolling["release"]["id"], "status": "blocked", "attempt": 1,
                                                                    "at": "2026-09-22T00:00:00+00:00", "reason": "fixture"})
    out["rolling_back_is_never_a_wait"] = brief(rolling["delivery"].tick())
    # a refused release is owed work (halting it), not a wait
    refused = D.build(api, plan_overrides={"revision": "1" * 40})
    put(refused["store"], "release_queue", refused["release"]["id"], {"id": refused["release"]["id"], "status": "blocked", "attempt": 1,
                                                                    "at": "2026-09-22T00:00:00+00:00", "reason": "fixture"})
    out["refused_release_is_not_a_wait"] = brief(refused["delivery"].tick())
    out["held_intent_in_act"] = {"unreachable": "_select never chooses a held intent, so the defensive held branch of "
                                                "_act cannot be reached through tick"}
    return out


def selection(api):
    return {"disabled_idle": disabled_idle_unregistered(api), "missing_ports": missing_ports(api),
            "store_outage": store_outage(api), "drive_to_active": idle_and_nested(api),
            "claims_and_serialization": claims_and_serialization(api),
            "review_and_backoff": review_and_backoff(api), "unclaimed": unclaimed_reasons(api),
            "blocked_map": blocked_map(api)}


def run(api) -> dict:
    return {"targets": targets(api), "plans": plans(api), "projections": projections(api), "selection": selection(api)}
