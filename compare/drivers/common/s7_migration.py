"""Shared S7 scenario steps (`delivery.migration`): the lane half of a release migration of M7 `HostDelivery`
(`application/host_delivery.py`), characterized BEFORE the V8 split moves it (DESIGN-s7 §2, TRACE-s7 §5.4):
`stage_migration` (with review's `Releases.request_evaluator_migration` and `request_environment_reverification` behind
it), `register_migration_plan`, `finalize_migration`, `require_controller_code` and the migration projection of `status`.

Groups (each labelled in the result; the M7 tests they mirror are named at each function):

1. **evaluator_lane** (`tests/test_host_delivery_migration.py`, memory `SerialStore` only): the stage/register/finalize flow
   and the hold, the cached replays and conflicts, the source shapes refused, the stale digest / wrong candidate / forged
   identity, the live controller lease and running queue row, the reserved target, the busy target, the crash between the
   steps, every unresolvable or disagreeing evaluator pin, the staged replay without a resolver, another lineage in the
   acknowledgement, and the `status` projection of each phase and hold.
2. **environment_lane** (`tests/test_release_environment_reverification.py`, from
   `test_lane_environment_kind_stages_registers_and_finalizes` to `test_evaluator_kind_request_without_kind_keeps_its_identity`,
   memory store only): the environment kind through the lane, its refusals, the running controller code, the reviewer's zero
   controller approval, the release service's own controller refusals, a moved source and a kind-less request.
3. **controller_code**: `require_controller_code` with the port missing, a matching code and another code.

Each case reports its steps in order (each result, or the named refusal, whether the store was written and the digest of the
whole store after it), named views of the rows the migration writes (the old intent, the migration record, the successor
release, the queue rows), and the digest of every bucket at the end.

Layer: harness (never shipped)

Every double is in `s7_delivery` (LABELLED there) or below; this module never runs GitHub, a host, a process, a verifier or a
git repository, and never imports `codex_harness`. The ONE halted source intent is the LABELLED crafted write M7's own test
makes (the shape `_verify` records for an executed failed check after the source had already merged): the real queue API plus
one intent put. The evaluator-pin resolver (`evaluator_pins`) and the controller-code port (`controller_code`) are LABELLED
doubles returning fixed identities. The M7 private helper `HostDelivery._reservation_in` is not a public surface; the
reservation it reports is observed through `register`'s `target_reserved_by_migration` refusal instead. The PostgreSQL and the
concurrent tests are out of scope (the units family carries PG). Nothing here is an actual Codex, GitHub, host or production
verification.
"""

from __future__ import annotations

from contextlib import contextmanager

import s7_delivery as D
import s7_stages as S

E = "1" * 40                   # the approved evaluator revision (labelled)
OTHER_E = "6" * 40
CONTROLLER = "7" * 40          # the running controller code the labelled port resolves
CHECKS = ("tests", "cli_start", "cli_file_task")   # M7 tests/test_release_reverification.py::CHECKS
ENV_CHECKS = {"tests": {"passed": True, "evidence": "fixture:tests-passed"},
              "cli_start": {"passed": True, "evidence": "fixture:cli-start-passed"},
              "cli_file_task": {"passed": False, "evidence": "fixture:cli-file-task-environment-defect"}}
FAILED_TESTS = {"tests": {"passed": False, "evidence": "fixture-failed-check"}}
SUCCESSOR_PLAN = "delivery-plan-migrated"
INTENT_KEYS = ("stage", "previous_stage", "outcome", "reason_code", "main_effect", "held", "after_verification",
               "merged_revision", "attempts", "migration", "supersession", "verification", "error_type", "head",
               "pr_number", "descriptor_sha256")
UNREACHABLE = {
    "reservation_in": "M7's private `HostDelivery._reservation_in` is not a public surface: the reservation is observed "
                      "through register's target_reserved_by_migration refusal and the migration record's state",
    "concurrent_stage / concurrent_owner_of_target": "PostgreSQL and thread-barrier tests: the units family carries PG",
}


# ---- labelled doubles ---------------------------------------------------------------------------------------
class EvaluatorRepository:
    """LABELLED. M7 `tests/test_host_delivery_migration.py::FixtureEvaluatorRepository`: what `resolve_evaluator_pin` would
    derive for each known E. A dict, or an exception when E is unavailable; every call is recorded."""

    def __init__(self):
        self.commits, self.calls, self.fail = {}, [], None

    def add(self, revision, **overrides):
        self.commits[revision] = {"evaluator_tree": "2" * 40, "paths": ["tests/test_fixture.py"],
                                  "patch_sha256": "3" * 64, **overrides}

    def __call__(self, revision, base):
        self.calls.append((revision, base))
        if self.fail is not None:
            raise self.fail   # labelled injected repository outage
        commit = self.commits[revision]
        return {"evaluator_revision": revision, "parent": commit.get("parent", base), "base": base,
                **{k: v for k, v in commit.items() if k != "parent"}}


@contextmanager
def release_checks(checks):
    """LABELLED. M7 `migrated_rejected_plan` monkeypatches `test_host_delivery.release_policy` to the three checks; the
    shared builder reads the same module-level name, so the same replacement is made and undone here."""
    original = D.release_policy
    D.release_policy = lambda: {"checks": list(checks), "evaluator": "fixture-incumbent-policy"}
    try:
        yield
    finally:
        D.release_policy = original


def tick_view(result):
    return {key: result.get(key) for key in S.TICK_KEYS if key in result}


# ---- one lane ---------------------------------------------------------------------------------------------
class Lane:
    """One wired delivery (`s7_delivery.build`) over the memory `SerialStore` holding the H1-like halted source, and the
    ordered record of every step taken on it."""

    def __init__(self, api, label, *, checks=None, halted=None, **fields):
        self.api, self.label, self.steps, self.extra = api, label, [], {}
        with release_checks(checks or ("tests",)):
            self.system = D.build(api, verified=False)
        self.halted = (self.halt_group1 if halted is None else halted)(**fields)
        self.pins = self.delivery.evaluator_pins = EvaluatorRepository()
        for revision in (E, OTHER_E):
            self.pins.add(revision)

    # ---- views ------------------------------------------------------------------------------------------
    @property
    def delivery(self):
        return self.system["delivery"]

    @property
    def store(self):
        return self.system["store"]

    @property
    def plan(self):
        return self.system["plan"]

    @property
    def release(self):
        return self.system["release"]

    def get(self, bucket, key):
        return S.get(self.store, bucket, key)

    def put(self, bucket, key, body):
        S.put(self.store, bucket, key, body)

    def intent(self, plan_id=None):
        row = self.get(D.BUCKET_INTENTS, plan_id or self.plan["plan_id"])
        return None if row is None else {key: row.get(key) for key in INTENT_KEYS if key in row}

    def queue(self, release_id=None):
        row = self.get("release_queue", release_id or self.release["id"])
        return None if row is None else {"status": row.get("status"), "attempt": row.get("attempt"),
                                         "has_owner": bool(row.get("owner"))}

    def release_view(self, release_id):
        row = self.get("releases", release_id)
        if row is None:
            return None
        return {**{key: row.get(key) for key in ("status", "checks", "reverify_of", "policy_hash", "evaluator_migration",
                                                  "environment_reverification", "policy") if key in row},
                "keys": sorted(row)}

    def buckets(self):
        return D.snapshot(self.store)

    # ---- the crafted halted source ----------------------------------------------------------------------
    def claim_and_reject(self, release, plan, checks):
        """The real queue claim and `Releases.verify` verdict, then the queue finish (no crafted write)."""
        api, queue = self.api, self.api.queue(self.store)
        queue.enqueue(release["id"], "host delivery plan " + plan["plan_id"])
        claim = queue.claim(now=api.now(), eligible=lambda row: row["id"] == release["id"])
        api.releases(self.store).verify(release["id"], release["candidate"]["revision"], release["policy_hash"], checks)
        queue.finish(claim, {"status": "blocked", "reason": "release_rejected"}, api.now())

    def halt_group1(self, **fields):
        """LABELLED crafted write, as M7's `rejected_merged`: a reviewed release REJECTED by an executed failed check
        after its candidate merged (the H1 shape), written through the real queue API plus ONE intent put."""
        api, release, plan = self.api, self.release, self.plan
        self.claim_and_reject(release, plan, FAILED_TESTS)
        now = D.clock(api)()
        validated = api.validate_plan(plan)
        halted = {**api.new_intent(validated, api.plan_digest(validated), now),
                  "stage": api.BLOCKED, "previous_stage": api.VERIFYING, "outcome": "blocked",
                  "reason_code": "release_rejected", "after_verification": api.MERGED, "attempts": 1,
                  "head": release["candidate"]["revision"], "pr_number": 7, "pr_url": "https://example.invalid/pr/7",
                  "merged_revision": release["candidate"]["revision"],
                  "verification": {"attempts": [{"attempt_id": "a" * 32, "cleanup": {"state": "confirmed"}}]},
                  "updated_at": now, **fields}
        self.put(D.BUCKET_INTENTS, plan["plan_id"], halted)
        return halted

    def halt_of(self, release, plan, checks):
        """LABELLED crafted write, as M7's `_halt` of `test_release_environment_reverification.py`: the real queue claim
        and `Releases.verify` verdict, then ONE halted-intent put (over the existing intent when there is one)."""
        api = self.api
        self.claim_and_reject(release, plan, checks)
        now = D.clock(api)()
        validated = api.validate_plan(plan)
        intent = self.get(D.BUCKET_INTENTS, plan["plan_id"]) or api.new_intent(validated, api.plan_digest(validated), now)
        halted = {**intent, "stage": api.BLOCKED, "previous_stage": api.VERIFYING, "outcome": "blocked",
                  "reason_code": "release_rejected", "after_verification": api.MERGED, "attempts": 1, "held": None,
                  "head": release["candidate"]["revision"], "pr_number": 7, "pr_url": "https://example.invalid/pr/7",
                  "merged_revision": release["candidate"]["revision"],
                  "verification": {"attempts": [{"attempt_id": "a" * 32, "cleanup": {"state": "confirmed"}}]},
                  "updated_at": now}
        self.put(D.BUCKET_INTENTS, plan["plan_id"], halted)
        return halted

    # ---- requests, documents, acknowledgements ------------------------------------------------------------
    def request(self, **overrides):
        """M7 `request_for`: the evaluator migration request for the halted source."""
        api, release, plan = self.api, self.release, self.plan
        approval = {"source_release_id": release["id"], "base": release["candidate"]["base"],
                    "evaluator_revision": E, "evaluator_tree": "2" * 40, "patch_sha256": "3" * 64,
                    "paths": ["tests/test_fixture.py"], "evidence": "sha256:" + "4" * 64, "approved_by": "conductor"}
        body = {"old_plan_id": plan["plan_id"], "old_plan_sha256": api.plan_digest(api.validate_plan(plan)),
                "source_release_id": release["id"], "source_policy_hash": release["policy_hash"],
                "candidate_revision": release["candidate"]["revision"], "target_id": plan["target_id"],
                "actor": "conductor", "approval": approval, **overrides}
        return {**body, "migration_id": self.api.migration_request_id(body)}

    def successor_plan(self, staged, plan_id=SUCCESSOR_PLAN, **overrides):
        successor = self.get("releases", staged["successor_release_id"])
        return D.plan_document(self.api, successor, plan_id=plan_id, **overrides)

    def ack(self, request, registered, **overrides):
        """M7 `ack_for`."""
        api = self.api
        lineage = api.migration_lineage_digest(registered["source_release_id"], registered["successor_release_id"],
                                               registered["old_plan_id"], registered["plan_id"],
                                               registered["migration_id"])
        return {"control_action_id": "action-1", "plan_id": registered["plan_id"],
                "plan_sha256": registered["plan_sha256"], "request_sha256": self.api.digest(request),
                "canary_request_id": "not_requested", "lineage_sha256": lineage, **overrides}

    def restarted(self):
        """A restarted controller over the same durable store (no verifier, host or canary port)."""
        return self.api.HostDelivery(self.store, self.system["org"], github=self.system["github"],
                                     clock=D.clock(self.api), enabled=True)

    def competitor(self, revision="8" * 40):
        """M7's second, unreviewed release of another candidate revision, through the real `Releases.propose`."""
        return self.api.releases(self.store).propose({**self.release["candidate"], "revision": revision},
                                                     D.release_policy())

    # ---- steps ------------------------------------------------------------------------------------------
    def do(self, name, fn, *args, **kwargs):
        """One recorded step: its outcome, whether it wrote ANYWHERE, and the digest of the whole store after it."""
        out = D.guarded(self.system, fn, *args, **kwargs)
        self.steps.append({"step": name, **out})
        return out.get("value")

    def tick(self, name, delivery=None):
        result = (delivery or self.delivery).tick()
        self.steps.append({"step": name, "tick": tick_view(result), "store": D.store_digest(self.store)})
        return result

    def report(self, **views):
        return {"label": self.label, "steps": self.steps, **self.extra, **views, "buckets": self.buckets()}


def written(steps):
    """The steps that wrote (a refusal that wrote is a defect the golden records)."""
    return [step["step"] for step in steps if step.get("wrote")]


def changed_keys(before, after, allowed):
    """M7's 'nothing else changed' assertion, as data: the keys outside `allowed` that differ."""
    return sorted(key for key in {*before, *after} if key not in allowed and before.get(key) != after.get(key))


# ---- 1. the evaluator migration lane -----------------------------------------------------------------------------
def lane_flow(api):
    """M7 `test_stage_register_finalize_then_tick_runs_only_after_the_acknowledgement`."""
    run = Lane(api, "lane_flow")
    delivery, plan, request = run.delivery, run.plan, run.request()
    source_before = run.get("releases", run.release["id"])
    old_id = plan["plan_id"]
    staged = run.do("stage", delivery.stage_migration, request)
    successor_id = staged["successor_release_id"]
    old = run.get(D.BUCKET_INTENTS, old_id)
    written_keys = {"stage", "previous_stage", "outcome", "reason_code", "error_type", "stage_deadline", "main_effect",
                    "supersession", "updated_at"}
    run.extra["after_stage"] = {
        "source_release_unchanged": run.get("releases", run.release["id"]) == source_before,
        "old_intent": run.intent(), "old_verification_kept": old["verification"] == run.halted["verification"],
        "only_the_written_keys_changed": changed_keys(run.halted, old, written_keys) == [],
        "original_halt": old["supersession"]["original_halt"] == {k: run.halted.get(k) for k in (
            "stage", "previous_stage", "reason_code", "outcome", "attempts", "error_type", "updated_at")},
        "record": run.get(api.BUCKET_MIGRATIONS, old_id), "record_keys": sorted(run.get(api.BUCKET_MIGRATIONS, old_id)),
        "successor": run.release_view(successor_id), "successor_queue_row": run.queue(successor_id)}
    run.tick("tick_after_stage")
    document = run.successor_plan(staged)
    registered = run.do("register", delivery.register_migration_plan, document, D.pin(), request["migration_id"])
    run.extra["after_register"] = {"held_intent": run.intent(SUCCESSOR_PLAN),
                                   "merged_revision_carried": run.intent(SUCCESSOR_PLAN)["merged_revision"]
                                   == run.halted["merged_revision"]}
    run.tick("tick_held")
    status = delivery.status()
    run.extra["status_plans"] = sorted(view["plan_id"] for view in status["deliveries"])
    run.do("withdraw_the_held_successor", delivery.withdraw, SUCCESSOR_PLAN, registered["plan_sha256"],
           "reviewed_base_moved", "sha256:" + "ab" * 32)
    again = run.restarted()
    run.tick("restarted_tick_holds", again)
    run.extra["queue_after_restart"] = run.queue(successor_id)
    ack = run.ack(request, registered)
    run.do("finalize", delivery.finalize_migration, request["migration_id"], ack)
    run.extra["after_finalize"] = {"held_intent": run.intent(SUCCESSOR_PLAN), "queue_row": run.queue(successor_id)}
    run.tick("restarted_tick_runs_the_successor", again)
    run.extra["steps_that_wrote"] = written(run.steps)
    return run.report(record=run.get(api.BUCKET_MIGRATIONS, old_id))


def replays_and_conflicts(api):
    """M7 `test_every_step_replays_cached_and_refuses_a_conflicting_one`."""
    run = Lane(api, "replays_and_conflicts")
    delivery, request = run.delivery, run.request()
    staged = run.do("stage", delivery.stage_migration, request)
    run.do("stage_replay", delivery.stage_migration, dict(request))
    other = run.request(approval={**request["approval"], "evaluator_revision": OTHER_E})
    run.do("stage_conflict", delivery.stage_migration, other)
    document = run.successor_plan(staged)
    registered = run.do("register", delivery.register_migration_plan, document, D.pin(), request["migration_id"])
    run.do("register_replay", delivery.register_migration_plan, document, D.pin(), request["migration_id"])
    run.do("register_conflict", delivery.register_migration_plan, run.successor_plan(staged, ci_timeout=301), D.pin(),
           request["migration_id"])
    run.do("finalize_ack_mismatch", delivery.finalize_migration, request["migration_id"],
           run.ack(request, registered, plan_sha256="0" * 64))
    ack = run.ack(request, registered)
    run.do("finalize", delivery.finalize_migration, request["migration_id"], ack)
    run.do("finalize_replay", delivery.finalize_migration, request["migration_id"], dict(ack))
    run.do("finalize_conflict", delivery.finalize_migration, request["migration_id"],
           run.ack(request, registered, canary_request_id="sha256:" + "9" * 64))
    run.do("finalize_unknown", delivery.finalize_migration, "f" * 64, ack)
    run.extra["steps_that_wrote"] = written(run.steps)
    return run.report()


SOURCE_SHAPES = (("release_not_verified", {"reason_code": "release_not_verified"}),
                 ("stage_verifying", {"stage": "verifying"}),
                 ("host_touched", {"descriptor_sha256": "d" * 64}),
                 ("merged_revision_missing", {"merged_revision": None}),
                 ("attempt_debt", {"verification": {"attempts": [{"attempt_id": "b" * 32, "cleanup": None}]}}))


def source_shapes(api):
    """M7 `test_a_source_that_is_not_the_exact_rejected_merged_shape_is_refused_without_a_write` (five shapes)."""
    out = {}
    for name, fields in SOURCE_SHAPES:
        run = Lane(api, "source_shape_" + name, **fields)
        run.do("stage", run.delivery.stage_migration, run.request())
        run.extra["steps_that_wrote"] = written(run.steps)
        out[name] = run.report()
    return out


def stale_and_forged(api):
    """M7 `test_a_stale_digest_wrong_candidate_or_forged_identity_is_refused_without_a_write`."""
    run = Lane(api, "stale_and_forged")
    delivery, request = run.delivery, run.request()
    run.do("stale_plan_digest", delivery.stage_migration, run.request(old_plan_sha256="0" * 64))
    run.do("wrong_candidate", delivery.stage_migration, run.request(candidate_revision="7" * 40))
    run.do("forged_migration_id", delivery.stage_migration, {**request, "migration_id": "0" * 64})
    run.do("approved_paths_disagree_with_the_pin", delivery.stage_migration,
           run.request(approval={**request["approval"], "paths": ["src/x.py"]}))
    # A repository that really has that code-touching E: the pin agrees, the release owner refuses.
    run.pins.add("9" * 40, paths=["src/x.py"])
    run.do("code_touching_evaluator", delivery.stage_migration,
           run.request(approval={**request["approval"], "evaluator_revision": "9" * 40, "paths": ["src/x.py"]}))
    run.extra["steps_that_wrote"] = written(run.steps)
    return run.report()


def controller_running(api):
    """M7 `test_a_live_controller_lease_or_running_queue_row_refuses_without_a_write`."""
    run = Lane(api, "controller_running")
    delivery, release_id = run.delivery, run.release["id"]
    queued = run.get("release_queue", release_id)
    run.put("release_queue", release_id, {**queued, "status": "running"})   # labelled: the source row is running
    run.do("running_queue_row", delivery.stage_migration, run.request())
    run.put("release_queue", release_id, queued)
    run.put("deployment_locks", "controller", {"owner": "other", "lease_until": "2999-01-01T00:00:00+00:00"})   # labelled live lease
    run.do("live_controller_lease", delivery.stage_migration, run.request())
    run.extra["steps_that_wrote"] = written(run.steps)
    return run.report()


def reserved_target(api):
    """M7 `test_the_reserved_target_admits_no_other_plan_until_active_and_another_target_is_free`."""
    run = Lane(api, "reserved_target")
    delivery, request = run.delivery, run.request()
    both = D.targets_document(api)
    delivery.register_targets({**both, "targets": [*both["targets"], *D.targets_document(api, target_id="other-service")["targets"]]})
    staged = run.do("stage", delivery.stage_migration, request)
    competitor = run.competitor()
    same = D.plan_document(api, competitor, plan_id="delivery-plan-h2")
    elsewhere = D.plan_document(api, competitor, plan_id="delivery-plan-other", target_id="other-service")
    run.do("register_on_the_reserved_target", delivery.register, same, D.pin())
    run.do("register_on_another_target", delivery.register, elsewhere, D.pin())
    # LABELLED crafted write (M7's own): a plan registered BEFORE the reservation, skipped by selection with the reason.
    validated = api.validate_plan(same)
    run.put(api.BUCKET_PLANS, "delivery-plan-h2", {"id": "delivery-plan-h2", "plan_id": "delivery-plan-h2",
                                                   "plan": validated, "plan_sha256": api.plan_digest(validated),
                                                   "pin": D.pin(), "target_id": "canary-service"})
    blocked = run.tick("tick_selection")["blocked"]
    run.extra["reasons"] = {"h2": blocked.get("delivery-plan-h2"), "other": blocked.get("delivery-plan-other")}
    registered = run.do("register_successor", delivery.register_migration_plan, run.successor_plan(staged), D.pin(),
                        request["migration_id"])
    run.extra["held_reserves"] = run.tick("tick_registered_but_held")["blocked"].get("delivery-plan-h2")
    run.do("finalize", delivery.finalize_migration, request["migration_id"], run.ack(request, registered))
    run.extra["after_active"] = run.tick("tick_after_finalize")["blocked"].get("delivery-plan-h2")
    run.extra["steps_that_wrote"] = written(run.steps)
    return run.report()


def target_busy(api):
    """M7 `test_a_target_with_another_unfinished_plan_is_not_staged`."""
    run = Lane(api, "target_busy")
    competitor = run.competitor()
    run.do("register_the_competitor", run.delivery.register, D.plan_document(api, competitor, plan_id="delivery-plan-h2"),
           D.pin())
    run.do("stage", run.delivery.stage_migration, run.request())
    run.extra["steps_that_wrote"] = written(run.steps)
    return run.report()


def crash_between_steps(api):
    """M7 `test_a_crash_between_steps_leaves_a_named_pending_handoff_never_a_free_target` (the reservation is read through
    the migration record and `register`, not through the private `_reservation_in`)."""
    run = Lane(api, "crash_between_steps")
    delivery, request = run.delivery, run.request()
    staged = run.do("stage", delivery.stage_migration, request)
    again = run.restarted()
    run.extra["record_state_after_stage"] = run.get(api.BUCKET_MIGRATIONS, run.plan["plan_id"])["state"]
    run.extra["tick_after_stage"] = tick_view(again.tick())
    competitor = run.competitor()
    run.do("competitor_sees_the_reservation", again.register, D.plan_document(api, competitor, plan_id="delivery-plan-h2"),
           D.pin())
    run.do("register_another_plan", again.register_migration_plan,
           D.plan_document(api, run.release, plan_id="delivery-plan-x"), D.pin(), request["migration_id"])
    run.do("finalize_before_register", again.finalize_migration, request["migration_id"],
           {"control_action_id": "a", "plan_id": "b", "plan_sha256": "c", "request_sha256": "d",
            "canary_request_id": "not_requested", "lineage_sha256": "f"})
    run.do("register_the_successor", again.register_migration_plan, run.successor_plan(staged), D.pin(),
           request["migration_id"])
    third = run.restarted()
    run.extra["record_state_after_register"] = run.get(api.BUCKET_MIGRATIONS, run.plan["plan_id"])["state"]
    result = run.tick("tick_third_controller", third)
    run.extra["held"] = [result["plan_id"], result["blocked"].get(SUCCESSOR_PLAN)]
    run.extra["successor_queue_row"] = run.queue(staged["successor_release_id"])
    run.extra["steps_that_wrote"] = written(run.steps)
    return run.report()


PIN_CASES = ("tree", "patch", "grandchild", "paths", "unavailable", "unknown", "no_port", "not_a_dict")


def pin_faults(api):
    """M7 `test_an_unresolvable_or_disagreeing_pin_stages_nothing_and_the_right_request_then_succeeds` (eight cases)."""
    out = {}
    for case in PIN_CASES:
        run = Lane(api, "pin_" + case)
        delivery, pins, request = run.delivery, run.pins, run.request()
        if case == "tree":
            pins.add(E, evaluator_tree="0" * 40)
        elif case == "patch":
            pins.add(E, patch_sha256="0" * 64)
        elif case == "grandchild":
            pins.add(E, parent="7" * 40)   # E's parent is not the approved base
        elif case == "paths":
            pins.add(E, paths=["tests/test_fixture.py", "tests/test_other.py"])
        elif case == "unavailable":
            pins.fail = OSError("fixture: repository unreadable")
        elif case == "unknown":
            pins.commits.clear()
        elif case == "no_port":
            delivery.evaluator_pins = None
        elif case == "not_a_dict":
            delivery.evaluator_pins = lambda revision, base: None   # labelled resolver answering nothing
        run.do("stage_refused", delivery.stage_migration, request)
        run.extra["old_intent_unchanged"] = run.get(D.BUCKET_INTENTS, run.plan["plan_id"]) == run.halted
        delivery.evaluator_pins, pins.fail = pins, None
        pins.add(E)
        run.do("stage_with_the_right_pin", delivery.stage_migration, request)
        run.extra["last_pin_call"] = list(pins.calls[-1])
        run.extra["last_pin_call_is_E_and_the_approved_base"] = pins.calls[-1] == (E, run.release["candidate"]["base"])
        run.extra["expected_pin"] = api.expected_evaluator_pin(request["approval"])
        run.extra["steps_that_wrote"] = written(run.steps)
        out[case] = run.report()
    return out


def staged_replay_without_resolver(api):
    """M7 `test_a_staged_replay_needs_no_resolver`."""
    run = Lane(api, "staged_replay_without_resolver")
    request = run.request()
    staged = run.do("stage", run.delivery.stage_migration, request)
    run.delivery.evaluator_pins = None
    replay = run.do("replay_with_no_resolver", run.delivery.stage_migration, request)
    run.extra["replay_is_the_staged_view_cached"] = replay == {**staged, "cached": True}
    run.extra["steps_that_wrote"] = written(run.steps)
    return run.report()


LINEAGE_FIELDS = ("source_release_id", "successor_release_id", "old_plan_id", "plan_id", "migration_id")


def ack_lineage(api):
    """M7 `test_an_ack_with_another_lineage_is_refused_and_the_exact_one_finalizes_once` (five fields)."""
    out = {}
    for field in LINEAGE_FIELDS:
        run = Lane(api, "ack_lineage_" + field)
        delivery, request = run.delivery, run.request()
        staged = run.do("stage", delivery.stage_migration, request)
        registered = run.do("register", delivery.register_migration_plan, run.successor_plan(staged), D.pin(),
                            request["migration_id"])
        identity = {name: registered[name] for name in LINEAGE_FIELDS}
        identity[field] = "x" + str(identity[field])
        run.do("wrong_lineage", delivery.finalize_migration, request["migration_id"],
               run.ack(request, registered, lineage_sha256=api.migration_lineage_digest(**identity)))
        for name, bad in (("canary_request_id_not_a_digest", {"canary_request_id": "canary-1"}),
                          ("canary_request_id_not_hex", {"canary_request_id": "sha256:" + "z" * 64}),
                          ("blank_control_action", {"control_action_id": " "})):
            run.do("invalid_" + name, delivery.finalize_migration, request["migration_id"],
                   run.ack(request, registered, **bad))
        ack = run.ack(request, registered, canary_request_id=api.digest({"fixture": "canary request"}))
        final = run.do("finalize", delivery.finalize_migration, request["migration_id"], ack)
        run.extra["final_state"] = (final or {}).get("state")
        delivery.queue = None   # the replay runs no readiness effect again: the queue is not touched
        run.do("replay_without_a_queue", delivery.finalize_migration, request["migration_id"], dict(ack))
        run.extra["steps_that_wrote"] = written(run.steps)
        out[field] = run.report()
    return out


def status_projection(api):
    """M7 `test_status_projects_each_migration_phase_and_hold`."""
    run = Lane(api, "status_projection")
    delivery, request, old = run.delivery, run.request(), run.plan["plan_id"]
    run.extra["status_before"] = delivery.status()["migrations"]
    staged = run.do("stage", delivery.stage_migration, request)
    run.extra["status_staged"] = delivery.status()["migrations"]
    registered = run.do("register", delivery.register_migration_plan, run.successor_plan(staged), D.pin(),
                        request["migration_id"])
    shown = delivery.status(SUCCESSOR_PLAN)["migrations"]
    run.extra["status_registered_by_successor"] = shown
    run.extra["status_registered_by_old_plan"] = delivery.status(old)["migrations"] == shown
    run.extra["status_unknown_plan"] = delivery.status("delivery-plan-none")["migrations"]
    before = run.buckets()
    run.do("finalize", delivery.finalize_migration, request["migration_id"], run.ack(request, registered))
    run.extra["status_active"] = delivery.status()["migrations"]
    after = run.buckets()
    delivery.status()
    run.extra["status_is_read_only"] = run.buckets() == after != before
    run.extra["status_envelope_keys"] = sorted(delivery.status())
    run.extra["steps_that_wrote"] = written(run.steps)
    return run.report()


def evaluator_lane(api):
    return {"lane_flow": lane_flow(api), "replays_and_conflicts": replays_and_conflicts(api),
            "source_shapes": source_shapes(api), "stale_and_forged": stale_and_forged(api),
            "controller_running": controller_running(api), "reserved_target": reserved_target(api),
            "target_busy": target_busy(api), "crash_between_steps": crash_between_steps(api),
            "pin_faults": pin_faults(api), "staged_replay_without_resolver": staged_replay_without_resolver(api),
            "ack_lineage": ack_lineage(api), "status_projection": status_projection(api)}


# ---- 2. the environment reverification lane -------------------------------------------------------------------------
class EnvLane(Lane):
    """M7 `migrated_rejected_plan`: the real first migration of a rejected merged delivery, then a real rejection verdict on
    the migrated successor (tests passed, cli_start passed, cli_file_task executed and failed). The controller-code port is
    the LABELLED double returning the approved code."""

    def __init__(self, api, label):
        super().__init__(api, label, checks=CHECKS, halted=self.first_halt)
        delivery = self.delivery
        delivery.controller_code = lambda: CONTROLLER   # labelled: the trusted port reports the approved code as running
        request = self.request()
        staged = delivery.stage_migration(request)
        document = self.successor_plan(staged)
        registered = delivery.register_migration_plan(document, D.pin(), request["migration_id"])
        delivery.finalize_migration(request["migration_id"], self.ack(request, registered))
        self.first_request, self.migrated_plan = request, document
        migrated = self.get("releases", staged["successor_release_id"])
        self.migrated_halt = self.halt_of(migrated, document, ENV_CHECKS)
        self.migrated = self.get("releases", migrated["id"])

    def first_halt(self, **fields):
        first = {"tests": FAILED_TESTS["tests"],
                 **{name: {"passed": False, "skipped": True, "evidence": "fixture-not-run"} for name in CHECKS[1:]}}
        return self.halt_of(self.release, self.plan, first)

    def env_request(self, *, approval=None, **overrides):
        """M7 `env_request_for`."""
        api, source, plan = self.api, self.migrated, self.migrated_plan
        sha = api.plan_digest(api.validate_plan(plan))
        approval = approval if approval is not None else self.approval(source, old_plan_id=plan["plan_id"],
                                                                        old_plan_sha256=sha, target_id=plan["target_id"])
        body = {"kind": "environment_reverification", "old_plan_id": plan["plan_id"], "old_plan_sha256": sha,
                "source_release_id": source["id"], "source_policy_hash": source["policy_hash"],
                "candidate_revision": source["candidate"]["revision"], "target_id": plan["target_id"],
                "actor": "conductor", "approval": approval, **overrides}
        return {**body, "migration_id": self.api.migration_request_id(body)}

    @staticmethod
    def approval(source, **overrides):
        """M7 `approval_for`."""
        return {"kind": "environment_reverification", "source_release_id": source["id"],
                "source_policy_hash": source["policy_hash"], "old_plan_id": "delivery-plan-migrated",
                "old_plan_sha256": "c" * 64, "intent_id": "control-intent-1", "policy_id": "control-policy-1",
                "target_id": "canary-service", "lane": "h1-file-canary", "fix_evidence": "sha256:" + "d" * 64,
                "controller_revision": CONTROLLER, "approved_by": "conductor", **overrides}


def environment_kind(api):
    """M7 `test_lane_environment_kind_stages_registers_and_finalizes`."""
    run = EnvLane(api, "environment_kind")
    delivery, source, plan = run.delivery, run.migrated, run.migrated_plan
    request = run.env_request()
    source_before = run.get("releases", source["id"])
    calls_before = len(run.pins.calls)
    staged = run.do("stage", delivery.stage_migration, request)
    successor_id = staged["successor_release_id"]
    successor = run.get("releases", successor_id)
    old = run.get(D.BUCKET_INTENTS, plan["plan_id"])
    run.extra["after_stage"] = {
        "resolver_calls": [list(call) for call in run.pins.calls[calls_before:]],
        "resolver_re_derived_the_sources_own_pin": run.pins.calls[calls_before:] == [
            (source["policy"]["revision"], source["candidate"]["base"])],
        "source_release_unchanged": run.get("releases", source["id"]) == source_before,
        "successor_id_is_the_environment_successor_id": successor["id"] == api.environment_successor_id(source["id"]),
        "successor_keeps_policy_and_evaluator": [successor["policy"] == source["policy"],
                                                 successor["policy_hash"] == source["policy_hash"],
                                                 successor["evaluator_migration"] == source["evaluator_migration"]],
        "successor": run.release_view(successor_id), "controller_revision":
            successor["environment_reverification"]["controller_revision"],
        "old_intent": run.intent(plan["plan_id"]),
        "old_migration_carried": old["migration"] == run.migrated_halt["migration"],
        "record": run.get(api.BUCKET_MIGRATIONS, plan["plan_id"]), "successor_queue_row": run.queue(successor_id)}
    before = run.buckets()
    run.do("stage_replay", delivery.stage_migration, request)
    again = run.restarted()
    run.do("stage_replay_after_restart", again.stage_migration, request)
    run.extra["replays_wrote_nothing"] = run.buckets() == before
    run.do("stage_conflict", delivery.stage_migration,
           run.env_request(approval={**request["approval"], "controller_revision": "8" * 40}))
    document = D.plan_document(api, successor, plan_id="delivery-plan-environment")
    registered = run.do("register", delivery.register_migration_plan, document, D.pin(), request["migration_id"])
    run.extra["held_intent"] = run.intent("delivery-plan-environment")
    run.do("register_replay", delivery.register_migration_plan, document, D.pin(), request["migration_id"])
    shown = {m["migration_id"]: m for m in delivery.status()["migrations"]}
    run.extra["status_kinds"] = {"environment": shown[request["migration_id"]]["kind"],
                                 "first": shown[run.first_request["migration_id"]]["kind"]}
    ack = run.ack(request, registered)
    run.do("finalize_after_restart", again.finalize_migration, request["migration_id"], ack)
    run.extra["queue_after_finalize"] = run.queue(successor_id)
    run.do("finalize_replay", delivery.finalize_migration, request["migration_id"], ack)
    run.extra["steps_that_wrote"] = written(run.steps)
    return run.report()


def environment_refusals(api):
    """M7 `test_lane_environment_refusals_write_nothing`."""
    run = EnvLane(api, "environment_refusals")
    delivery = run.delivery
    good = run.env_request()
    for key, value in (("old_plan_id", "delivery-plan-1"), ("target_id", "other"), ("source_policy_hash", "x"),
                       ("kind", "evaluator_migration")):
        run.do("approval_names_another_" + key, delivery.stage_migration,
               run.env_request(approval={**good["approval"], key: value}))
    unknown = {k: v for k, v in good.items() if k != "migration_id"}
    for kind in ("other", ["environment_reverification"], None):
        unknown["kind"] = kind
        run.do("request_kind_%s" % (kind if not isinstance(kind, list) else "list"), delivery.stage_migration,
               {**unknown, "migration_id": api.migration_request_id(unknown)})
    run.pins.add(E, evaluator_tree="9" * 40)   # the resolver moved: E now resolves to another tree
    run.do("pin_moved", delivery.stage_migration, good)
    run.pins.fail = RuntimeError("fixture: repository unavailable")
    run.do("pin_unavailable", delivery.stage_migration, good)
    run.pins.fail = None
    run.pins.add(E)
    run.do("malformed_controller_revision", delivery.stage_migration,
           run.env_request(approval={**good["approval"], "controller_revision": "x" * 40}))
    run.extra["steps_that_wrote"] = written(run.steps)
    return run.report()


CODE_PORTS = (("missing", None), ("returns_none", lambda: None), ("not_a_revision", lambda: "not-a-revision"),
              ("raises", "raise"), ("other_code", lambda: "0" * 40))


def _unreadable():
    raise OSError("fixture: runtime unreadable")   # labelled injected failure of the trusted port


def controller_code_ports(api):
    """M7 `test_unknown_or_other_running_controller_code_refuses_before_any_stage_effect_...` (five ports)."""
    out = {}
    for name, port in CODE_PORTS:
        run = EnvLane(api, "controller_code_" + name)
        delivery, source = run.delivery, run.migrated
        good = run.env_request()
        delivery.controller_code = _unreadable if port == "raise" else port
        run.do("stage_refused", delivery.stage_migration, good)
        run.extra["successor_unused"] = run.get("releases", api.environment_successor_id(source["id"])) is None
        run.extra["old_intent_not_withdrawn"] = run.get(D.BUCKET_INTENTS, run.migrated_plan["plan_id"])["stage"] != api.WITHDRAWN
        delivery.controller_code = lambda: CONTROLLER
        staged = run.do("stage_with_the_approved_code", delivery.stage_migration, good)
        successor = run.get("releases", staged["successor_release_id"])
        run.extra["controller_resolved"] = successor["environment_reverification"]["controller_resolved"]
        run.extra["steps_that_wrote"] = written(run.steps)
        out[name] = run.report()
    return out


def reviewer_zero_controller(api):
    """M7 `test_the_reviewer_zero_controller_approval_never_consumes_the_successor`."""
    run = EnvLane(api, "reviewer_zero_controller")
    delivery, source = run.delivery, run.migrated
    zero = run.env_request(approval={**run.env_request()["approval"], "controller_revision": "0" * 40})
    run.do("zero_controller_approval", delivery.stage_migration, zero)
    staged = run.do("stage_the_approved", delivery.stage_migration, run.env_request())
    run.extra["successor_is_the_environment_successor"] = (
        staged["successor_release_id"] == api.environment_successor_id(source["id"]))
    run.extra["steps_that_wrote"] = written(run.steps)
    return run.report()


def release_service_controller(api):
    """M7 `test_the_release_service_refuses_an_unresolved_or_other_controller_before_any_write`: `Releases` alone over the
    memory `SerialStore`, a migrated source rejected by an executed environment check (labelled fixture verdicts through the
    real `Releases.verify`)."""
    store = D.SerialStore(api)
    system = {"store": store}
    releases = api.releases(store)
    candidate = {"revision": "candidate", "base": "base", "tree": "tree", "author": "worker:implementation"}
    original = releases.propose(candidate, {"checks": list(CHECKS)})
    for actor in ("lead:improvement", "conductor"):
        releases.review(original["id"], actor, "candidate", True, "fixture:review")
    original = releases.verify(original["id"], "candidate", original["policy_hash"],
                               {"tests": {"passed": False, "evidence": "fixture:tests-failed"},
                                **{name: {"passed": False, "skipped": True, "evidence": "fixture:not-run"}
                                   for name in CHECKS[1:]}})
    approval = {"source_release_id": original["id"], "base": "base", "evaluator_revision": "e" * 40,
                "evaluator_tree": "f" * 40, "patch_sha256": "a" * 64, "paths": ["tests/test_fixture.py"],
                "evidence": "sha256:" + "b" * 64, "approved_by": "conductor"}
    child = releases.request_evaluator_migration(
        original["id"], "conductor", expected_revision="candidate", expected_policy_hash=original["policy_hash"],
        approval=approval, resolved_pin=api.expected_evaluator_pin(approval))
    source = releases.verify(child["id"], "candidate", child["policy_hash"], ENV_CHECKS)

    def reverify(resolved):
        return releases.request_environment_reverification(
            source["id"], "conductor", expected_revision="candidate", expected_policy_hash=source["policy_hash"],
            approval=EnvLane.approval(source), resolved_pin=api.expected_evaluator_pin(source["evaluator_migration"]),
            resolved_controller=resolved)

    steps = [{"step": name, **D.guarded(system, reverify, resolved)}
             for name, resolved in (("controller_unresolved", None), ("controller_other", "0" * 40),
                                    ("controller_uppercase", "F" * 40))]
    done = D.call(reverify, CONTROLLER)
    steps.append({"step": "approved_controller", "refused": done.get("refused"),
                  "controller_resolved": ((done.get("value") or {}).get("environment_reverification") or {})
                  .get("controller_resolved")})
    return {"label": "release_service_controller", "steps": steps, "steps_that_wrote": written(steps),
            "source_status": source["status"], "buckets": D.snapshot(store)}


def source_moved(api):
    """M7 `test_lane_source_moved_is_refused`."""
    run = EnvLane(api, "source_moved")
    good = run.env_request()
    run.put(D.BUCKET_INTENTS, run.migrated_plan["plan_id"], {**run.migrated_halt, "reason_code": "operator_moved"})   # labelled
    run.do("stage_refused", run.delivery.stage_migration, good)
    run.extra["steps_that_wrote"] = written(run.steps)
    return run.report()


def kindless_request(api):
    """M7 `test_evaluator_kind_request_without_kind_keeps_its_identity`."""
    run = Lane(api, "kindless_request")
    request = run.request()
    staged = run.do("stage", run.delivery.stage_migration, request)
    run.extra["request_has_no_kind"] = "kind" not in request
    run.extra["staged_kind"] = staged["kind"]
    run.extra["record_kind"] = run.get(api.BUCKET_MIGRATIONS, run.plan["plan_id"])["kind"]
    return run.report()


def environment_lane(api):
    return {"environment_kind": environment_kind(api), "environment_refusals": environment_refusals(api),
            "controller_code_ports": controller_code_ports(api),
            "reviewer_zero_controller": reviewer_zero_controller(api),
            "release_service_controller": release_service_controller(api), "source_moved": source_moved(api),
            "kindless_request": kindless_request(api)}


# ---- 3. the controller code ---------------------------------------------------------------------------------------
def controller_code(api):
    """`HostDelivery.require_controller_code` itself: the port missing, a matching code and another code (the port also
    unreadable, answering nothing or a malformed revision, as the environment lane reaches them through `stage_migration`)."""
    out = {}
    for name, port in (("port_missing", None), ("matching_code", lambda: CONTROLLER), ("another_code", lambda: "0" * 40),
                       ("returns_none", lambda: None), ("malformed_revision", lambda: "not-a-revision"),
                       ("port_raises", _unreadable)):
        system = D.build(api, verified=False, register_plan=False)
        delivery = system["delivery"]
        delivery.controller_code = port
        out[name] = {**D.guarded(system, delivery.require_controller_code, CONTROLLER), "buckets": D.snapshot(system["store"])}
    return out


def refusals(value, seen):
    """Every named refusal in a result tree (a `D.call` outcome), by code."""
    if isinstance(value, dict):
        if "refused" in value and "reason_code" in value:
            seen[value["reason_code"]] = seen.get(value["reason_code"], 0) + 1
        for child in value.values():
            refusals(child, seen)
    elif isinstance(value, list):
        for child in value:
            refusals(child, seen)


def coverage(groups):
    seen = {}
    refusals(groups, seen)
    return {"refusals_observed": dict(sorted(seen.items())), "unreachable": UNREACHABLE}


def run(api) -> dict:
    groups = {"evaluator_lane": evaluator_lane(api), "environment_lane": environment_lane(api),
              "controller_code": controller_code(api)}
    groups["coverage"] = coverage(groups)
    return groups
