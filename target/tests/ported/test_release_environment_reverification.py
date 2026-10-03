"""INV-RELEASE-ENVIRONMENT-REVERIFY-001: a conductor-approved environment reverification of a migrated source.

Every candidate, review, check, approval, controller revision and repository resolver here is a labelled
fixture; nothing claims an actual Codex, GitHub or production verification. What is real: the `Releases`
owner, the `ReleaseQueue`, the `HostDelivery` owner and their store transactions (the in-memory stores and
an isolated PostgreSQL schema when `HARNESS_INTEGRATION=1`; without it those parameters SKIP and are not
evidence). The one crafted write per delivery is the halted H1-like intent, as in
tests/test_host_delivery_migration.py.

Ported SOURCE M7 suite `tests/test_release_environment_reverification.py` (e38aa722) run against the S8 target (DESIGN-s8 §29).
Every assertion is M7's, unchanged. Adaptations, all import and construction (the `m7_review` shim docstring names them):
`Releases`, `ReleaseQueue`, `HostDelivery`, `MemoryStore`, `organization`, `ContractError` and `digest` come from the shim
(composition wiring and target homes); `BUCKET_INTENTS`/`BUCKET_MIGRATIONS` are
`delivery.application.host_delivery.state`'s; the release names (`ENVIRONMENT_APPROVAL_KEYS`, the refusals, the successor-id
functions, `expected_evaluator_pin`) are `review.domain.releases`; the host-delivery domain names are
`delivery.domain.host_delivery`. The helper modules `test_host_delivery`, `test_host_delivery_migration`,
`test_release_evaluator_migration` and `test_release_reverification` are the ported ones.
"""
import threading

import pytest
import test_host_delivery as delivery_fixtures
from m7_review import (
    ContractError,
    HostDelivery,
    MemoryStore,
    ReleaseQueue,
    Releases,
    digest,
    organization,
)
from test_host_delivery import build, pin
from test_host_delivery_migration import (
    FixtureEvaluatorRepository,
    ack_for,
    refused,
    request_for,
    successor_plan,
)
from test_host_delivery_migration import snapshot as lane_snapshot
from test_release_evaluator_migration import E, migrate
from test_release_reverification import (
    CHECKS,
    backends,
    rejected_release,
    reverify,
    snapshot,
    store_for,
)

from codex_harness.delivery.application.host_delivery.state import BUCKET_INTENTS, BUCKET_MIGRATIONS
from codex_harness.delivery.domain.host_delivery import (
    BLOCKED,
    MERGED,
    VERIFYING,
    WITHDRAWN,
    migration_request_id,
    new_intent,
    plan_digest,
    validate_plan,
)
from codex_harness.review.domain.releases import (
    ENVIRONMENT_APPROVAL_KEYS,
    EnvironmentReverificationRefused,
    UnsupportedEvaluatorReverification,
    environment_successor_id,
    evaluator_successor_id,
    expected_evaluator_pin,
    reverification_successor_id,
)

CONTROLLER = "7" * 40
ENV_CHECKS = {"tests": {"passed": True, "evidence": "fixture:tests-passed"},
              "cli_start": {"passed": True, "evidence": "fixture:cli-start-passed"},
              "cli_file_task": {"passed": False, "evidence": "fixture:cli-file-task-environment-defect"}}


def migrated_rejected(store, checks=None):
    """The H1 shape at the release level: a migrated successor whose tests passed and whose executed
    file canary failed (labelled fixture verdicts through the real `Releases.verify`)."""
    releases, original = rejected_release(store)
    child = migrate(releases, original)
    rejected = releases.verify(child["id"], "candidate", child["policy_hash"], checks or ENV_CHECKS)
    assert rejected["status"] == "rejected"
    return releases, rejected


def approval_for(source, **overrides):
    return {"kind": "environment_reverification", "source_release_id": source["id"],
            "source_policy_hash": source["policy_hash"], "old_plan_id": "delivery-plan-migrated",
            "old_plan_sha256": "c" * 64, "intent_id": "control-intent-1", "policy_id": "control-policy-1",
            "target_id": "canary-service", "lane": "h1-file-canary", "fix_evidence": "sha256:" + "d" * 64,
            "controller_revision": CONTROLLER, "approved_by": "conductor", **overrides}


def env_reverify(releases, source, *, actor="conductor", approval=None, **overrides):
    approval = approval if approval is not None else approval_for(source)
    # Labelled: the trusted resolver's result for the source's own recorded (E, base).
    resolved = overrides.pop("resolved_pin", None) or expected_evaluator_pin(source["evaluator_migration"])
    return releases.request_environment_reverification(
        source["id"], actor, expected_revision=overrides.pop("expected_revision", "candidate"),
        expected_policy_hash=overrides.pop("expected_policy_hash", source["policy_hash"]),
        approval=approval, resolved_pin=resolved,
        # Labelled: the trusted boundary's resolution of the running controller code.
        resolved_controller=overrides.pop("resolved_controller", CONTROLLER), **overrides)


@backends()
def test_environment_successor_keeps_candidate_policy_and_evaluator(backend, request):
    store = store_for(backend, request)
    releases, source = migrated_rejected(store)
    before = snapshot(store)
    child = env_reverify(releases, source)
    after = snapshot(store)
    event_key = ("events", "release.environment_reverification_requested:" + child["id"])
    assert set(after) - set(before) == {("releases", child["id"]), event_key}
    assert {key: after[key] for key in before} == before  # the source bytes are untouched
    assert child["id"] == digest({"environment_reverify_of": source["id"]}) == environment_successor_id(source["id"])
    assert child["status"] == "reviewed" and child["checks"] == {} and "image" not in child
    assert child["candidate"] == source["candidate"] and child["reviews"] == source["reviews"]
    assert child["policy"] == source["policy"] and child["policy"]["revision"] == E
    assert child["policy_hash"] == source["policy_hash"]
    assert child["evaluator_migration"] == source["evaluator_migration"]
    assert child["reverify_of"] == source["id"]
    assert child["inherited_reviews"] == {"release_id": source["id"], "digest": digest(source["reviews"])}
    receipt = child["environment_reverification"]
    assert {k: receipt[k] for k in ENVIRONMENT_APPROVAL_KEYS} == approval_for(source)
    assert receipt["actor"] == "conductor" and receipt["source_policy_hash"] == source["policy_hash"]
    assert receipt["source_checks_digest"] == digest(source["checks"])
    assert receipt["source_digest"] == digest(source) and receipt["at"]
    assert after[event_key]["controller_revision"] == CONTROLLER
    # Every check must be produced afresh for the new id; the successor is not verified by inheritance.
    with pytest.raises(ContractError, match="Missing or extra canary checks"):
        releases.verify(child["id"], "candidate", child["policy_hash"], {})


@backends()
def test_replay_writes_nothing_and_any_difference_conflicts(backend, request):
    store = store_for(backend, request)
    releases, source = migrated_rejected(store)
    child = env_reverify(releases, source)
    before = snapshot(store)
    assert env_reverify(releases, source) == child
    assert snapshot(store) == before
    for changed in ({"controller_revision": "8" * 40}, {"fix_evidence": "sha256:" + "e" * 64},
                    {"lane": "other-lane"}, {"intent_id": "control-intent-2"}):
        # A differing controller approval is resolved as running here, so the recorded one conflicts.
        with pytest.raises(ContractError, match="Conflicting environment reverification"):
            env_reverify(releases, source, approval=approval_for(source, **changed),
                         resolved_controller=changed.get("controller_revision", CONTROLLER))
    # An approval naming another evaluator never replays into the recorded successor.
    with pytest.raises(EnvironmentReverificationRefused, match="environment_reverification_approval_invalid"):
        env_reverify(releases, source, approval=approval_for(source, source_policy_hash="other"))
    assert snapshot(store) == before


def test_environment_successor_blocks_plain_and_evaluator_successors_and_stays_unchanged():
    store = MemoryStore()
    releases, source = migrated_rejected(store)
    child = env_reverify(releases, source)
    before = snapshot(store)
    with pytest.raises(UnsupportedEvaluatorReverification):
        reverify(releases, source)
    with pytest.raises(UnsupportedEvaluatorReverification):
        migrate(releases, source)
    assert snapshot(store) == before and env_reverify(releases, source) == child


@pytest.mark.parametrize("kind", ["plain", "evaluator"])
def test_an_injected_environment_successor_blocks_the_other_kinds_on_any_source(kind):
    """Labelled crafted record: the source-key block holds even where the source shape would allow it."""
    store = MemoryStore()
    releases, source = rejected_release(store)
    with store.transaction() as tx:
        tx.put("releases", environment_successor_id(source["id"]),
               {"id": environment_successor_id(source["id"]), "reverify_of": source["id"], "fixture": True})
    before = snapshot(store)
    with pytest.raises(ContractError, match="already has an environment reverification successor"):
        reverify(releases, source) if kind == "plain" else migrate(releases, source)
    assert snapshot(store) == before


@pytest.mark.parametrize("kind", ["plain", "evaluator"])
def test_an_existing_plain_or_evaluator_successor_blocks_the_environment_kind(kind):
    """Labelled crafted record under the other kind's source key of a migrated source."""
    store = MemoryStore()
    releases, source = migrated_rejected(store)
    key = (reverification_successor_id if kind == "plain" else evaluator_successor_id)(source["id"])
    with store.transaction() as tx:
        tx.put("releases", key, {"id": key, "reverify_of": source["id"], "fixture": True})
    before = snapshot(store)
    message = "already has a reverification successor" if kind == "plain" else "already has an evaluator migration"
    with pytest.raises(ContractError, match=message):
        env_reverify(releases, source)
    assert snapshot(store) == before


def _malformed(source):
    wrong = approval_for(source)
    return [
        ({**wrong, "controller_revision": "7" * 39}, "environment_reverification_approval_invalid"),
        ({**wrong, "controller_revision": "G" * 40}, "environment_reverification_approval_invalid"),
        ({**wrong, "controller_revision": "A" * 40}, "environment_reverification_approval_invalid"),
        ({**wrong, "controller_revision": 7}, "environment_reverification_approval_invalid"),
        ({**wrong, "fix_evidence": "d" * 64}, "environment_reverification_approval_invalid"),
        ({**wrong, "kind": "evaluator_migration"}, "environment_reverification_approval_invalid"),
        ({**wrong, "source_release_id": "other"}, "environment_reverification_approval_invalid"),
        ({**wrong, "extra": "x"}, "environment_reverification_approval_invalid"),
        ({k: v for k, v in wrong.items() if k != "lane"}, "environment_reverification_approval_invalid"),
    ]


def test_malformed_approvals_are_named_refusals_before_any_write():
    store = MemoryStore()
    releases, source = migrated_rejected(store)
    before = snapshot(store)
    for approval, code in _malformed(source):
        with pytest.raises(EnvironmentReverificationRefused) as caught:
            env_reverify(releases, source, approval=approval)
        assert caught.value.reason_code == code
    assert snapshot(store) == before


@pytest.mark.parametrize("field", ["evaluator_revision", "evaluator_tree", "patch_sha256", "paths", "parent"])
def test_a_wrong_evaluator_pin_writes_nothing(field):
    store = MemoryStore()
    releases, source = migrated_rejected(store)
    before = snapshot(store)
    pinned = expected_evaluator_pin(source["evaluator_migration"])
    wrong = {**pinned, field: ["tests/other.py"] if field == "paths" else "0" * len(pinned[field])}
    with pytest.raises(EnvironmentReverificationRefused) as caught:
        env_reverify(releases, source, resolved_pin=wrong)
    assert caught.value.reason_code == "environment_reverification_pin_mismatch"
    assert snapshot(store) == before


def test_source_shape_refusals_are_named_and_write_nothing():
    store = MemoryStore()
    # A non-migrated rejected release is not an environment source.
    releases, plain = rejected_release(store)
    before = snapshot(store)
    with pytest.raises(EnvironmentReverificationRefused) as caught:
        releases.request_environment_reverification(
            plain["id"], "conductor", expected_revision="candidate", expected_policy_hash=plain["policy_hash"],
            approval=approval_for(plain), resolved_pin={}, resolved_controller=CONTROLLER)
    assert caught.value.reason_code == "environment_reverification_requires_migrated_source"
    assert snapshot(store) == before


def test_depth_is_bounded_to_one_environment_successor():
    store = MemoryStore()
    releases, source = migrated_rejected(store)
    child = env_reverify(releases, source)
    again = releases.verify(child["id"], "candidate", child["policy_hash"], ENV_CHECKS)
    assert again["status"] == "rejected"
    before = snapshot(store)
    with pytest.raises(EnvironmentReverificationRefused) as caught:
        env_reverify(releases, again)
    assert caught.value.reason_code == "environment_reverification_depth"
    with pytest.raises(UnsupportedEvaluatorReverification):
        reverify(releases, again)
    assert snapshot(store) == before


@pytest.mark.parametrize("tests_check", [{"passed": False, "evidence": "fixture:tests-failed"},
                                         {"passed": True, "skipped": True, "evidence": "fixture:not-run"}])
def test_tests_must_have_passed(tests_check):
    store = MemoryStore()
    releases, source = migrated_rejected(store, {**ENV_CHECKS, "tests": tests_check})
    before = snapshot(store)
    with pytest.raises(EnvironmentReverificationRefused) as caught:
        env_reverify(releases, source)
    assert caught.value.reason_code == "tests_not_passed"
    assert snapshot(store) == before


def test_a_skipped_only_environment_failure_is_not_an_executed_failed_check():
    store = MemoryStore()
    skipped = {**ENV_CHECKS, "cli_file_task": {"passed": False, "skipped": True, "evidence": "fixture:not-run"}}
    releases, source = migrated_rejected(store, skipped)
    before = snapshot(store)
    with pytest.raises(ContractError, match="No executed failed check"):
        env_reverify(releases, source)
    assert snapshot(store) == before


@pytest.mark.parametrize("case", ["actor", "approver", "policy_hash", "expected_hash", "expected_revision"])
def test_authority_and_staleness_are_refused_before_any_write(case):
    store = MemoryStore()
    releases, source = migrated_rejected(store)
    before = snapshot(store)
    call = {"actor": lambda: env_reverify(releases, source, actor="lead:improvement"),
            "approver": lambda: env_reverify(releases, source,
                                             approval=approval_for(source, approved_by="worker:implementation")),
            "policy_hash": lambda: env_reverify(releases, source,
                                                approval=approval_for(source, source_policy_hash="other")),
            "expected_hash": lambda: env_reverify(releases, source, expected_policy_hash="other"),
            "expected_revision": lambda: env_reverify(releases, source, expected_revision="other")}[case]
    with pytest.raises(ContractError):
        call()
    assert snapshot(store) == before


def test_the_candidate_author_cannot_approve(monkeypatch):
    store = MemoryStore()
    releases, source = migrated_rejected(store)
    author = releases.org.agents["worker:implementation"]
    original = releases.org.actor
    monkeypatch.setattr(releases.org, "actor", lambda actor_id, role=None: author
                        if actor_id == "worker:implementation" and role == "conductor"
                        else original(actor_id, role))
    before = snapshot(store)
    with pytest.raises(ContractError, match="approver is the candidate author"):
        env_reverify(releases, source, approval=approval_for(source, approved_by="worker:implementation"))
    assert snapshot(store) == before


def race(store, source):
    results, gate = {}, threading.Barrier(2)

    def run(name):
        gate.wait()
        try:
            releases = Releases(store, organization())
            revision = CONTROLLER if name == "first" else "8" * 40
            results[name] = env_reverify(releases, source, resolved_controller=revision,
                                         approval=approval_for(source, controller_revision=revision))
        except ContractError as exc:
            results[name] = str(exc)

    threads = [threading.Thread(target=run, args=(name,)) for name in ("first", "second")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    return results


def _one_successor(store, source, results):
    with store.transaction() as tx:
        children = [r for r in tx.scan("releases") if r.get("reverify_of") == source["id"]]
    assert len(children) == 1 and len(results) == 2
    winners = [name for name, value in results.items() if isinstance(value, dict)]
    assert len(winners) == 1 and results[winners[0]] == children[0]
    loser = ({"first", "second"} - set(winners)).pop()
    assert results[loser] == "Conflicting environment reverification"


@pytest.mark.integration
def test_concurrent_conflicting_environment_requests_create_exactly_one_successor(isolated_pgstore):
    _, source = migrated_rejected(isolated_pgstore)
    _one_successor(isolated_pgstore, source, race(isolated_pgstore, source))


def test_memory_conflicting_environment_requests_create_exactly_one_successor():
    store = MemoryStore()
    _, source = migrated_rejected(store)
    _one_successor(store, source, race(store, source))


# ----- the lane kind (INV-HOST-DELIVERY-MIGRATION-001 + INV-RELEASE-ENVIRONMENT-REVERIFY-001) -------

@pytest.fixture(params=["memory", pytest.param("postgres", marks=pytest.mark.integration)])
def store(request):
    if request.param == "memory":
        return delivery_fixtures.SerialStore()
    return request.getfixturevalue("isolated_pgstore")


def _halt(system, store, release, plan, checks):
    """The real queue claim and `Releases.verify` verdict, then ONE labelled halted-intent put."""
    delivery, queue, plan_id = system["delivery"], ReleaseQueue(store), plan["plan_id"]
    if queue.enqueue(release["id"], "host delivery plan " + plan_id).get("status") != "queued":
        raise AssertionError("queue row not queued")
    claim = queue.claim(now=delivery._now(), eligible=lambda row: row["id"] == release["id"])
    verdict = Releases(store, system["org"]).verify(release["id"], release["candidate"]["revision"],
                                                    release["policy_hash"], checks)
    assert verdict["status"] == "rejected"
    queue.finish(claim, {"status": "blocked", "reason": "release_rejected"}, delivery._now())
    now = system["clock"]()
    with store.transaction() as tx:
        intent = tx.get(BUCKET_INTENTS, plan_id) or new_intent(
            validate_plan(plan), plan_digest(validate_plan(plan)), now)
        halted = {**intent, "stage": BLOCKED, "previous_stage": VERIFYING, "outcome": "blocked",
                  "reason_code": "release_rejected", "after_verification": MERGED, "attempts": 1,
                  "held": None, "head": release["candidate"]["revision"], "pr_number": 7,
                  "pr_url": "https://example.invalid/pr/7", "merged_revision": release["candidate"]["revision"],
                  "verification": {"attempts": [{"attempt_id": "a" * 32, "cleanup": {"state": "confirmed"}}]},
                  "updated_at": now}
        tx.put(BUCKET_INTENTS, plan_id, halted)
    return halted


def migrated_rejected_plan(tmp_path, store, monkeypatch):
    """The real first migration of a rejected merged delivery, then a real rejection verdict on the
    migrated successor: tests passed, cli_start passed, cli_file_task executed and failed."""
    monkeypatch.setattr(delivery_fixtures, "release_policy",
                        lambda: {"checks": list(CHECKS), "evaluator": "fixture-incumbent-policy"})
    system = build(tmp_path, store=store, verified=False)
    delivery, plan = system["delivery"], system["plan"]
    first = {"tests": {"passed": False, "evidence": "fixture-failed-check"},
             **{name: {"passed": False, "skipped": True, "evidence": "fixture-not-run"} for name in CHECKS[1:]}}
    _halt(system, store, system["release"], plan, first)
    system["pins"] = delivery.evaluator_pins = FixtureEvaluatorRepository()
    system["pins"].add("1" * 40)
    # Labelled: the trusted port reports the approved controller code as the running code.
    delivery.controller_code = lambda: CONTROLLER
    request = request_for(system)
    staged = delivery.stage_migration(request)
    document = successor_plan(system, staged)
    registered = delivery.register_migration_plan(document, pin(), request["migration_id"])
    delivery.finalize_migration(request["migration_id"], ack_for(request, registered))
    with store.transaction() as tx:
        migrated = tx.get("releases", staged["successor_release_id"])
    system.update(first_request=request, migrated=migrated, migrated_plan=document)
    system["migrated_halt"] = _halt(system, store, migrated, document, ENV_CHECKS)
    with store.transaction() as tx:
        system["migrated"] = tx.get("releases", migrated["id"])
    return system


def env_request_for(system, *, approval=None, **overrides):
    source, plan = system["migrated"], system["migrated_plan"]
    sha = plan_digest(validate_plan(plan))
    approval = approval if approval is not None else {
        **approval_for(source, old_plan_id=plan["plan_id"], old_plan_sha256=sha, target_id=plan["target_id"])}
    body = {"kind": "environment_reverification", "old_plan_id": plan["plan_id"], "old_plan_sha256": sha,
            "source_release_id": source["id"], "source_policy_hash": source["policy_hash"],
            "candidate_revision": source["candidate"]["revision"], "target_id": plan["target_id"],
            "actor": "conductor", "approval": approval, **overrides}
    return {**body, "migration_id": migration_request_id(body)}


def row(store, bucket, key):
    with store.transaction() as tx:
        return tx.get(bucket, key)


def test_lane_environment_kind_stages_registers_and_finalizes(tmp_path, store, monkeypatch):
    system = migrated_rejected_plan(tmp_path, store, monkeypatch)
    delivery, source, plan = system["delivery"], system["migrated"], system["migrated_plan"]
    request = env_request_for(system)
    source_before = row(store, "releases", source["id"])
    calls_before = len(system["pins"].calls)
    staged = delivery.stage_migration(request)
    assert staged["state"] == "staged" and staged["kind"] == "environment_reverification"
    # The resolver re-derived the source's OWN (E, base), outside the staging transaction.
    assert system["pins"].calls[calls_before:] == [(source["policy"]["revision"], source["candidate"]["base"])]
    assert row(store, "releases", source["id"]) == source_before
    successor = row(store, "releases", staged["successor_release_id"])
    assert successor["id"] == environment_successor_id(source["id"])
    assert successor["policy"] == source["policy"] and successor["policy_hash"] == source["policy_hash"]
    assert successor["evaluator_migration"] == source["evaluator_migration"] and successor["checks"] == {}
    assert successor["environment_reverification"]["controller_revision"] == CONTROLLER
    old = row(store, BUCKET_INTENTS, plan["plan_id"])
    assert old["stage"] == WITHDRAWN and old["reason_code"] == "release_rejected_superseded"
    assert old["main_effect"] == "merged" and old["migration"] == system["migrated_halt"]["migration"]
    assert old["supersession"]["original_halt"]["reason_code"] == "release_rejected"
    record = row(store, BUCKET_MIGRATIONS, plan["plan_id"])
    assert record["kind"] == "environment_reverification"
    assert row(store, "release_queue", successor["id"]) is None

    # Lost response: the identical request replays cached, also through a restarted controller.
    before = lane_snapshot(store)
    assert delivery.stage_migration(request)["cached"] is True
    restarted = HostDelivery(store, system["org"], github=system["github"], clock=system["clock"], enabled=True)
    assert restarted.stage_migration(request)["cached"] is True
    assert lane_snapshot(store) == before
    refused("migration_conflict", delivery.stage_migration,
            env_request_for(system, approval={**request["approval"], "controller_revision": "8" * 40}))

    document = delivery_fixtures.plan_document(successor, plan_id="delivery-plan-environment")
    registered = delivery.register_migration_plan(document, pin(), request["migration_id"])
    assert registered["state"] == "registered" and registered["kind"] == "environment_reverification"
    held = row(store, BUCKET_INTENTS, "delivery-plan-environment")
    assert held["held"] == "migration_unacknowledged" and held["stage"] == VERIFYING
    assert held["migration"]["source_release_id"] == source["id"]
    assert delivery.register_migration_plan(document, pin(), request["migration_id"])["cached"] is True
    shown = {m["migration_id"]: m for m in delivery.status()["migrations"]}
    assert shown[request["migration_id"]]["kind"] == "environment_reverification"
    assert shown[system["first_request"]["migration_id"]]["kind"] == "evaluator_migration"

    ack = ack_for(request, registered)
    final = restarted.finalize_migration(request["migration_id"], ack)
    assert final["state"] == "active" and final["acknowledged"] is True
    assert row(store, "release_queue", successor["id"])["status"] == "queued"
    assert delivery.finalize_migration(request["migration_id"], ack)["cached"] is True


def test_lane_environment_refusals_write_nothing(tmp_path, store, monkeypatch):
    system = migrated_rejected_plan(tmp_path, store, monkeypatch)
    delivery = system["delivery"]
    before = lane_snapshot(store)
    good = env_request_for(system)
    # The approval must name exactly the request's own source, plan and target.
    for key, value in (("old_plan_id", "delivery-plan-1"), ("target_id", "other"), ("source_policy_hash", "x"),
                       ("kind", "evaluator_migration")):
        refused("migration_request_invalid", delivery.stage_migration,
                env_request_for(system, approval={**good["approval"], key: value}))
    unknown = {k: v for k, v in good.items() if k != "migration_id"}
    for kind in ("other", ["environment_reverification"], None):
        unknown["kind"] = kind
        refused("migration_request_invalid", delivery.stage_migration,
                {**unknown, "migration_id": migration_request_id(unknown)})
    # The resolver moved: E now resolves to another tree.
    system["pins"].add("1" * 40, evaluator_tree="9" * 40)
    refused("migration_pin_mismatch", delivery.stage_migration, good)
    system["pins"].fail = RuntimeError("fixture: repository unavailable")
    refused("migration_pin_unavailable", delivery.stage_migration, good)
    system["pins"].fail = None
    system["pins"].add("1" * 40)
    # A malformed controller revision is never the running code: refused before the transaction.
    refused("migration_controller_code_mismatch", delivery.stage_migration,
            env_request_for(system, approval={**good["approval"], "controller_revision": "x" * 40}))
    assert lane_snapshot(store) == before


@pytest.mark.parametrize("port, code", [
    (None, "migration_controller_code_unavailable"),
    (lambda: None, "migration_controller_code_unavailable"),
    (lambda: "not-a-revision", "migration_controller_code_unavailable"),
    (lambda: (_ for _ in ()).throw(OSError("fixture: runtime unreadable")), "migration_controller_code_unavailable"),
    (lambda: "0" * 40, "migration_controller_code_mismatch"),
])
def test_unknown_or_other_running_controller_code_refuses_before_any_stage_effect(tmp_path, store, monkeypatch,
                                                                                  port, code):
    """PR214 review B1: the trusted port's resolution of the RUNNING controller code, never the approval's
    own string, gates the stage. Unknown or other code writes nothing: the source, its intent (not
    withdrawn), the one successor identity and the target stay unused - the approved code then stages."""
    system = migrated_rejected_plan(tmp_path, store, monkeypatch)
    delivery, source = system["delivery"], system["migrated"]
    good = env_request_for(system)
    before = lane_snapshot(store)
    delivery.controller_code = port
    refused(code, delivery.stage_migration, good)
    assert lane_snapshot(store) == before
    assert row(store, "releases", environment_successor_id(source["id"])) is None
    assert row(store, BUCKET_INTENTS, system["migrated_plan"]["plan_id"])["stage"] != WITHDRAWN
    delivery.controller_code = lambda: CONTROLLER
    staged = delivery.stage_migration(good)
    assert staged["state"] == "staged"
    successor = row(store, "releases", staged["successor_release_id"])
    assert successor["environment_reverification"]["controller_resolved"] == CONTROLLER


def test_the_reviewer_zero_controller_approval_never_consumes_the_successor(tmp_path, store, monkeypatch):
    """The exact PR214 review reproduction: an approval naming 40 zeros while the approved code runs."""
    system = migrated_rejected_plan(tmp_path, store, monkeypatch)
    delivery, source = system["delivery"], system["migrated"]
    zero = env_request_for(system, approval={**env_request_for(system)["approval"], "controller_revision": "0" * 40})
    before = lane_snapshot(store)
    refused("migration_controller_code_mismatch", delivery.stage_migration, zero)
    assert lane_snapshot(store) == before, "no successor, no withdrawn intent, no reservation"
    staged = delivery.stage_migration(env_request_for(system))
    assert staged["successor_release_id"] == environment_successor_id(source["id"])


def test_the_release_service_refuses_an_unresolved_or_other_controller_before_any_write(store):
    releases, source = migrated_rejected(store)
    before = snapshot(store)
    for resolved, code in ((None, "environment_reverification_controller_unavailable"),
                           ("0" * 40, "environment_reverification_controller_mismatch"),
                           ("F" * 40, "environment_reverification_controller_unavailable")):
        with pytest.raises(EnvironmentReverificationRefused) as caught:
            env_reverify(releases, source, resolved_controller=resolved)
        assert caught.value.reason_code == code
    assert snapshot(store) == before
    assert env_reverify(releases, source)["environment_reverification"]["controller_resolved"] == CONTROLLER


def test_lane_source_moved_is_refused(tmp_path, store, monkeypatch):
    system = migrated_rejected_plan(tmp_path, store, monkeypatch)
    delivery, plan = system["delivery"], system["migrated_plan"]
    good = env_request_for(system)
    with store.transaction() as tx:
        tx.put(BUCKET_INTENTS, plan["plan_id"], {**system["migrated_halt"], "reason_code": "operator_moved"})
    before = lane_snapshot(store)
    refused("migration_not_applicable", delivery.stage_migration, good)
    assert lane_snapshot(store) == before


def test_evaluator_kind_request_without_kind_keeps_its_identity(tmp_path, store):
    """Backward compatibility: a request with no `kind` is the original evaluator migration."""
    from test_host_delivery_migration import rejected_merged
    system = rejected_merged(tmp_path, store)
    request = system["request"]
    assert "kind" not in request
    staged = system["delivery"].stage_migration(request)
    assert staged["kind"] == "evaluator_migration"
    assert row(store, BUCKET_MIGRATIONS, system["plan"]["plan_id"])["kind"] == "evaluator_migration"

