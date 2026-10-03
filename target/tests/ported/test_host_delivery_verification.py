"""Ported SOURCE M7 suite `tests/test_host_delivery_verification.py` (e38aa722) run against the S7 target (DESIGN-s7 §6).

Every assertion is M7's, unchanged. Adaptations, all construction, import and patch-target (the `m7_delivery` shim
docstring names the routing): `HostDelivery`, `Releases`, `ReleaseQueue`, `ProcessHostTarget`, `GitHubDelivery`, the
canary and runtime helpers, `Fleet`, `organization`, `MemoryStore`, `GitWorkspace`, `MergeRefused`, `ContractError`,
`POLICY` and `digest` come from the shim over the S7 split objects and moved adapters; the domain names from
`delivery.domain.host_delivery`, the BUCKET_* names from `delivery.application.host_delivery.state`, the fleet names
from `coordination`, the observation names from `observation`. A name whose owner is in a later slice (the operator
CLI and lane resolution, S10; the Windows scheduled task, W-B) is an `unavailable(slice, name)` placeholder, and only
tests skipped whole and unrewritten (each with its owning slice) name it: of the 13 evaluator tests U2a unskipped,
five name `add_parser`/`run_loop` and stay skipped whole as S10 (the legacy-halt resume through the CLI, the three
SIGTERM/blocked-fence run-loop cases, and the blocked-PostgreSQL-heartbeat stop, an integration case that only the owner's
CI-equivalent `target-integration` run reached); the other eight run.
The release evaluator is the target's (S8): `ReleaseRunner` is the shim's wiring of `delivery.adapters.deployment` with the
real `ReleaseSuite`, `ReleaseVerifier`, `FenceUnobservable` and `bounded_fence` are `composition.release_verifier`'s
(through the shim), and `deployment` is the shim's route to `delivery.adapters.deployment` (its `VerificationServices` is
patched through the runner's injected port). `FixtureServices`, `fake_docker` and `source_repository` are the ported
`verification_fixtures` helper module (M7 `tests/verification_fixtures.py`), imported as M7 imports them.

M7 docstring follows.

The `verifying` stage and `host-delivery resume` over REAL interfaces (INV-HOST-DELIVERY-VERIFY-001).

What is real: the Git repository and review workspaces, the existing `ReleaseRunner.evaluate` and its
`ReleaseSuite` (the candidate's incumbent and candidate suites run as real pytest children), every
child process, the `ReleaseVerifier` port with its attempt records under a temporary root, the
`Releases`/`ReleaseQueue` owners, the store (the in-memory `SerialStore`, and an isolated PostgreSQL
schema when `HARNESS_INTEGRATION=1`; without it that parameter SKIPS and is not evidence), the process
host target of the existing suite, the `zeus host-delivery` argument parser and `execute`, and the
signal delivered to this test process.

What is a labelled SYNTHETIC HOST FIXTURE (tests/verification_fixtures.py): the `docker` and `uv`
executables, the compose-backed verification services, the placeholder auth FILE (created empty and
never opened by anything here), and the GitHub port (`FakeGitHub` of tests/test_host_delivery.py).
The legacy halted H1 shape is crafted through the real queue API plus one labelled intent write.
The unavailable store of the L-3 tests is a labelled fault (`StoreOutage`): one shared event in front
of the in-memory store, or the real controller advisory lock held by a separate PostgreSQL session.
No production service, database, configuration, credential, provider or model is touched, and
nothing here is a rollout or a live verification.
"""
import argparse
import json
import os
import signal
import threading
import time
from types import SimpleNamespace

import pytest
from m7_delivery import (
    POLICY,
    FileArtifacts,
    GitWorkspace,
    HostDelivery,
    ProcessHostTarget,
    ReleaseQueue,
    ReleaseRunner,
    Releases,
    ReleaseVerifier,
    deployment,
    organization,
    owner_qualified_canary,
    startup_identity_canary,
    unavailable,
)
from test_host_delivery import (
    Clock,
    FakeGitHub,
    SerialStore,
    binds_a_runtime,
    pin,
    plan_document,
    stop_target,
    targets_document,
    visited,
)
from verification_fixtures import FixtureServices, fake_docker, source_repository

from codex_harness.delivery.application.host_delivery.state import BUCKET_INTENTS
from codex_harness.delivery.domain.host_delivery import (
    ACTIVE,
    AWAITING_CI,
    AWAITING_CONSUMPTION,
    BLOCKED,
    CANARY_FLEET,
    CANARY_STARTUP,
    DRAIN_INTENDED,
    MERGE_INTENDED,
    MERGED,
    PUBLISHING,
    SWITCHING,
    VERIFYING,
    DeliveryRefused,
    new_intent,
    plan_digest,
    unresolved_attempts,
    validate_plan,
)

host_delivery = unavailable('S10', 'adapters.host_delivery')
add_parser = unavailable('S10', 'adapters.host_delivery.add_parser')
execute = unavailable('S10', 'adapters.host_delivery.execute')
run_loop = unavailable('S10', 'adapters.host_delivery.run_loop')

POLICY_CHECKS = {"checks": ["tests", "cli_start", "cli_file_task"], "evaluator": "fixture-incumbent-policy"}
EVIDENCE = "sha256:" + "ab" * 32


@pytest.fixture(params=["memory", pytest.param("postgres", marks=pytest.mark.integration)])
def store(request):
    if request.param == "memory":
        return SerialStore()
    return request.getfixturevalue("isolated_pgstore")


def build(tmp_path, monkeypatch, store, *, failing=False, fence_seconds=30):
    daemon = fake_docker(tmp_path, monkeypatch)
    FixtureServices.entered = []
    monkeypatch.setattr(deployment, "VerificationServices", FixtureServices)
    repo = source_repository(tmp_path / "source", failing_candidate=failing)
    workspace = GitWorkspace(str(repo["root"]), str(tmp_path / "workspaces"))
    org = organization()
    candidate = {"revision": repo["revision"], "base": repo["base"], "tree": repo["tree"],
                 "author": "worker:implementation", "branch": "harness/delivery-1", "task_id": "delivery-1",
                 "repository": workspace.target_identity()}
    releases = Releases(store, org)
    row = releases.propose(candidate, POLICY_CHECKS)
    releases.review(row["id"], "lead:improvement", candidate["revision"], True, "fixture-lead-review-evidence")
    releases.review(row["id"], "conductor", candidate["revision"], True, "fixture-conductor-review-evidence")
    with store.transaction() as tx:
        release = tx.get("releases", row["id"])
    # SYNTHETIC: a placeholder file only; its presence is checked and it is never opened.
    auth = tmp_path / "fixture-auth-placeholder.json"
    auth.write_text("{}", encoding="utf-8")
    artifacts = FileArtifacts(str(tmp_path / "artifacts"))
    root = tmp_path / "verification"
    owner = SimpleNamespace(store=store, org=org)
    verifier = ReleaseVerifier(
        lambda fence: ReleaseRunner(owner, workspace, artifacts, str(auth), auto_merge=False, fence=fence,
                                    verification_root=root),
        root=root, artifacts=lambda: artifacts, fence_seconds=fence_seconds)
    github = FakeGitHub(merged_tree=repo["tree"], fast_forward=True)
    github.main = repo["base"]
    clock = Clock()
    host = ProcessHostTarget(max_seconds=60)
    delivery = HostDelivery(store, org, github=github, hosts={"process": host},
                            canaries={CANARY_STARTUP: startup_identity_canary, CANARY_FLEET: owner_qualified_canary},
                            clock=clock, enabled=True, resume_seconds=0, verifier=verifier)
    registry = targets_document(tmp_path)
    delivery.register_targets(registry)
    plan = plan_document(release, repository=candidate["repository"])
    delivery.register(plan, pin())
    return {"store": store, "org": org, "clock": clock, "delivery": delivery, "release": release, "plan": plan,
            "host": host, "github": github, "target": registry["targets"][0], "daemon": daemon, "root": root,
            "repo": repo, "workspace": workspace, "artifacts": artifacts, "verifier": verifier}


def drive(system, *, until, limit=60, sleep=0.05):
    """Tick until `until`; every result carries the publish/merge counts and intent AFTER it."""
    results = []
    for _ in range(limit):
        result = system["delivery"].tick()
        system["clock"].advance(1)
        result["publishes"], result["merges"] = system["github"].publishes, system["github"].merges
        result["intent"] = intent_of(system)
        results.append(result)
        if result["stage"] == until or result["outcome"] in {"blocked", "refused", "conflict"}:
            return results
        if result["outcome"] == "pending":
            time.sleep(sleep)
    return results


def intent_of(system):
    with system["store"].transaction() as tx:
        return tx.get(BUCKET_INTENTS, system["plan"]["plan_id"])


def release_of(system):
    with system["store"].transaction() as tx:
        return tx.get("releases", system["release"]["id"]), tx.get("images", system["release"]["id"])


def disk_record(system, attempt_id):
    return json.loads((system["root"] / "attempts" / attempt_id / "run.json").read_text("utf-8"))


def assert_exact_names(system, attempt_id):
    """Every container the attempt created carries its exact name and labels; nothing random."""
    calls = system["daemon"].calls()
    runs = [call for call in calls if call[:1] == ["run"]]
    assert len(runs) == 2
    for call, role in zip(runs, ("release-start", "release-canary")):
        assert call[call.index("--name") + 1] == "zeus-" + role + "-" + attempt_id
        assert "zeus.isolated.run=" + attempt_id in call and "zeus.isolated.role=" + role in call
    assert not any(part.startswith("harness-canary-") for call in calls for part in call)
    assert FixtureServices.entered == [("enter", "zeus-verify-" + attempt_id), ("exit", "zeus-verify-" + attempt_id)]


# ----- N-1: reviewed -> verifying -> verified -> ... -> active ----------------------------------------
@binds_a_runtime
def test_a_reviewed_release_is_verified_by_the_real_evaluator_before_publication(tmp_path, monkeypatch, store):
    system = build(tmp_path, monkeypatch, store)
    try:
        results = drive(system, until=ACTIVE)
        assert visited(results) == [VERIFYING, PUBLISHING, AWAITING_CI, MERGE_INTENDED, MERGED, DRAIN_INTENDED,
                                    SWITCHING, AWAITING_CONSUMPTION, ACTIVE], [r["reason_code"] for r in results]
        # Nothing was published while the delivery was verifying.
        assert all(r["publishes"] == 0 for r in results if r["stage"] == VERIFYING)
        record, image = release_of(system)
        assert record["status"] == "active" and set(record["checks"]) == set(POLICY_CHECKS["checks"])
        assert all(check["passed"] is True and check["evidence"].startswith("sha256:")
                   for check in record["checks"].values())
        assert image["image"].startswith("sha256:") and image["revision"] == system["plan"]["revision"]
        # The attempt was resolved, with its cleanup receipt, in the SAME tick that left `verifying`.
        left = next(r for r in results if r["stage"] == PUBLISHING)
        (attempt,) = left["intent"]["verification"]["attempts"]
        assert attempt["cleanup"]["state"] == "confirmed" and attempt["cleanup"]["receipt"].startswith("sha256:")
        assert attempt["outcome"]["verdict"] == "checked" and attempt["owner"]["pid"] > 0
        assert disk_record(system, attempt["attempt_id"])["state"] == "resolved"
        assert_exact_names(system, attempt["attempt_id"])
        # Every host child the attempt created was recorded, and none of them survives.
        assert disk_record(system, attempt["attempt_id"])["children"]
        assert system["daemon"].state()["containers"] == {}
    finally:
        stop_target(system)


def test_a_check_that_executed_and_failed_rejects_without_publication(tmp_path, monkeypatch, store):
    """F-1 over the real evaluator: the candidate's own suite really fails."""
    system = build(tmp_path, monkeypatch, store, failing=True)
    results = drive(system, until=BLOCKED)
    assert results[-1]["outcome"] == "blocked" and results[-1]["reason_code"] == "release_rejected"
    assert results[-1]["stage"] == BLOCKED and system["github"].publishes == 0
    record, image = release_of(system)
    assert record["status"] == "rejected" and image is None
    assert record["checks"]["tests"]["passed"] is False
    # The checks that never ran are explicitly skipped with evidence, never synthetic passes.
    assert record["checks"]["cli_start"]["skipped"] is True and record["checks"]["cli_start"]["passed"] is False
    (attempt,) = intent_of(system)["verification"]["attempts"]
    assert attempt["cleanup"]["state"] == "confirmed"
    assert results[-1]["next_action"] == "owner_review"


# ----- N-3: the legacy merged/blocked H1 shape, resumed through the real CLI --------------------------
def legacy_halt(system):
    """The 5aa controller's recorded shape (RESEARCH-h1 §1): published, CI passed, merged by the
    lease fast-forward, then halted at `merged` with `release_not_verified`. The GitHub side goes
    through the labelled double, the queue through the REAL `ReleaseQueue`; the intent is the one
    labelled crafted write, with exactly the fields that controller wrote."""
    plan, github, store = system["plan"], system["github"], system["store"]
    candidate = system["release"]["candidate"]
    published = github.publish(candidate)
    github.merge(candidate, published)
    queue = ReleaseQueue(store)
    queue.enqueue(plan["release_id"], "host delivery plan " + plan["plan_id"])
    claim = queue.claim(now=system["delivery"]._now(), eligible=lambda row: row["id"] == plan["release_id"])
    queue.finish(claim, {"status": "blocked", "reason": "release_not_verified"}, system["delivery"]._now())
    now = system["clock"]()
    halted = {**new_intent(validate_plan(plan), plan_digest(validate_plan(plan)), now),
              "stage": BLOCKED, "previous_stage": MERGED, "outcome": "blocked",
              "reason_code": "release_not_verified", "attempts": 1, "head": candidate["revision"],
              "pr_number": published["number"], "pr_url": published["url"],
              "merged_revision": candidate["revision"], "last_check_state": "passed", "updated_at": now}
    with store.transaction() as tx:
        tx.put(BUCKET_INTENTS, plan["plan_id"], halted)
    return halted


def cli(system, monkeypatch, *argv):
    parser = argparse.ArgumentParser(prog="zeus")
    add_parser(parser.add_subparsers(dest="command", required=True))
    args = parser.parse_args(["host-delivery", *argv])
    monkeypatch.setattr(host_delivery, "_git", lambda _service: system["workspace"])
    monkeypatch.setattr(host_delivery, "_observer", lambda _service: None)
    # The real `controller()` would wire the real GitHub CLI; this delivery carries the labelled
    # double instead. Parsing, dispatch and the receipt are the shipped CLI path.
    monkeypatch.setattr(host_delivery, "controller", lambda *_a, **_k: system["delivery"])
    return execute(SimpleNamespace(store=system["store"], org=system["org"]), args)


def snapshot(store):
    with store.transaction() as tx:
        return {bucket: sorted(tx.scan(bucket), key=lambda row: str(row.get("id")))
                for bucket in (BUCKET_INTENTS, "release_queue", "releases", "images", "deployment_locks",
                               "host_delivery_plans")}


@pytest.mark.skip(reason='S10: the operator CLI (adapters.host_delivery.add_parser and execute; no S8 gap)')
@binds_a_runtime
def test_the_merged_unverified_legacy_halt_resumes_once_and_verifies_to_active(tmp_path, monkeypatch, store):
    system = build(tmp_path, monkeypatch, store)
    try:
        halted = legacy_halt(system)
        sha = system["delivery"].plan(system["plan"]["plan_id"])["plan_sha256"]
        argv = ("resume", "--plan", system["plan"]["plan_id"], "--plan-sha256", sha, "--evidence", EVIDENCE)
        receipt = cli(system, monkeypatch, *argv)
        assert receipt["exit_code"] == 0 and receipt["cached"] is False and receipt["stage"] == VERIFYING
        assert receipt["recovery"]["halted_reason_code"] == "release_not_verified"
        assert receipt["queue"] == {"status": "queued", "manual_retries": 1}
        intent = intent_of(system)
        assert intent["after_verification"] == MERGED and intent["previous_stage"] == BLOCKED
        (recovery,) = intent["recoveries"]
        assert recovery["halted"] == {key: halted[key] for key in ("stage", "previous_stage", "reason_code",
                                                                   "outcome", "attempts", "error_type",
                                                                   "updated_at")}
        # A replay is recognized from the record and writes nothing.
        before = snapshot(system["store"])
        again = cli(system, monkeypatch, *argv)
        assert again["cached"] is True and snapshot(system["store"]) == before
        results = drive(system, until=ACTIVE)
        assert visited(results) == [MERGED, DRAIN_INTENDED, SWITCHING, AWAITING_CONSUMPTION, ACTIVE]
        # No second publication or merge ever happened: only the crafted legacy one.
        assert system["github"].publishes == 1 and system["github"].merges == 1
        record, _image = release_of(system)
        assert record["status"] == "active" and all(c["passed"] for c in record["checks"].values())
        (attempt,) = intent_of(system)["verification"]["attempts"]
        assert attempt["cleanup"]["state"] == "confirmed"
        assert_exact_names(system, attempt["attempt_id"])
        with system["store"].transaction() as tx:
            assert len(tx.get("release_queue", system["release"]["id"])["manual_retries"]) == 1
        # The same evidence after the delivery advanced is still that one recovery, not a new one.
        final = cli(system, monkeypatch, *argv)
        assert final["cached"] is True and final["stage"] == ACTIVE
        before = snapshot(system["store"])
        with pytest.raises(DeliveryRefused) as refused:
            cli(system, monkeypatch, "resume", "--plan", system["plan"]["plan_id"], "--plan-sha256", sha,
                "--evidence", "sha256:" + "cd" * 32)
        assert refused.value.reason_code == "resume_conflict" and snapshot(system["store"]) == before
    finally:
        stop_target(system)


# ----- L-1: a real child, a real SIGTERM, the real run loop ---------------------------------------
@pytest.mark.skip(reason='S10: the host-delivery run loop (adapters.host_delivery.run_loop; no S8 gap)')
def test_sigterm_during_an_evaluation_ends_its_own_children_and_containers_once(tmp_path, monkeypatch):
    system = build(tmp_path, monkeypatch, SerialStore())
    daemon = system["daemon"]
    daemon.update(hang=["release-start"])  # labelled: the `docker run` client blocks, its container runs
    first = system["delivery"].tick()
    assert first["stage"] == VERIFYING
    signals = []

    def deliver():
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline and not any(c[:1] == ["run"] for c in daemon.calls()):
            time.sleep(0.05)
        os.kill(os.getpid(), signal.SIGTERM)
        signals.append("first")
        # A second signal while the attempt's own cleanup is stopping its container: flag only.
        while time.monotonic() < deadline and not any(c[:1] == ["kill"] for c in daemon.calls()):
            time.sleep(0.02)
        os.kill(os.getpid(), signal.SIGTERM)
        signals.append("second")

    sender = threading.Thread(target=deliver, daemon=True)
    sender.start()
    summary = run_loop(system["delivery"], interval=1, max_ticks=3, sleep=lambda _s: None)
    sender.join(30)
    assert signals == ["first", "second"] and not sender.is_alive()
    assert summary["stopped"] is True and summary["ticks"] == 1
    assert summary["outcomes"] == {"pending": 1}
    intent = intent_of(system)
    assert intent["stage"] == VERIFYING and intent["reason_code"] == "verification_interrupted"
    (attempt,) = intent["verification"]["attempts"]
    assert attempt["state"] == "interrupted" and attempt["cleanup"]["state"] == "confirmed"
    record = disk_record(system, attempt["attempt_id"])
    assert record["state"] == "resolved"
    # The blocked docker client was a real child; its whole process group is gone.
    for child in record["children"]:
        with pytest.raises(ProcessLookupError):
            os.killpg(child["pgid"], 0)
    # The daemon-owned container of THIS attempt was stopped and removed by exact id.
    assert daemon.state()["containers"] == {}
    start = "zeus-release-start-" + attempt["attempt_id"]
    assert any(c[:1] == ["kill"] for c in daemon.calls())
    assert [c for c in daemon.calls() if c[:1] == ["ps"] and "name=^/" + start + "$" in c]
    # No verdict, no image, and the queue attempt was not spent.
    release, image = release_of(system)
    assert release["status"] == "reviewed" and release["checks"] == {} and image is None
    with system["store"].transaction() as tx:
        row = tx.get("release_queue", system["release"]["id"])
    assert row["status"] == "queued" and row["attempt"] == 0


# ----- L-2 / L-3: a lost lease and an unobservable store between checks -----------------------------
def test_a_lease_lost_between_suite_batches_records_nothing_and_cleans_up(tmp_path, monkeypatch):
    system = build(tmp_path, monkeypatch, SerialStore())
    delivery, store = system["delivery"], system["store"]
    assert delivery.tick()["stage"] == VERIFYING
    real = delivery.queue.heartbeat
    calls = []

    def heartbeat(claim, now=None):
        calls.append(claim["owner"])
        if len(calls) == 3:
            # Another controller took the lease (the real stale shape: a different lock owner).
            with store.transaction() as tx:
                tx.put("deployment_locks", "controller", {"release_id": claim["id"], "owner": "other",
                                                          "lease_until": "2999-01-01T00:00:00+00:00"})
        return real(claim, now=now)

    monkeypatch.setattr(delivery.queue, "heartbeat", heartbeat)
    before = intent_of(system)
    result = delivery.tick()
    assert result["outcome"] == "conflict" and result["reason_code"] == "verification_fence_lost"
    release, image = release_of(system)
    assert release["status"] == "reviewed" and image is None
    after = intent_of(system)
    (attempt,) = after["verification"]["attempts"]
    # Only the attempt written BEFORE the evaluation exists; nothing after the lost fence.
    assert attempt["cleanup"] is None and attempt["state"] == "prepared"
    assert {k: v for k, v in after.items() if k not in {"verification", "updated_at"}} == \
        {k: v for k, v in before.items() if k not in {"verification", "updated_at"}}
    assert disk_record(system, attempt["attempt_id"])["state"] == "resolved"


def queue_row(system):
    with system["store"].transaction() as tx:
        return tx.get("release_queue", system["release"]["id"])


class StoreCallFailed(Exception):
    """LABELLED FAULT: a blocked store call that ends in an error, as `lock_timeout` does on PostgreSQL."""


class StoreOutage:
    """LABELLED FAULT: the store becomes unavailable at the evaluation's first fence observation.

    By default ONE shared event is the store's availability for every caller: once the first queue
    heartbeat arms it, every store transaction - that heartbeat's own, a settlement's
    (`ReleaseQueue.finish`/`defer`), an intent write, anything else - waits on the same event, as a
    call against a blocked store does. `fail` ends that first heartbeat's own wait with
    `StoreCallFailed` once `expired` is set, while the store stays unavailable for everyone else.
    `arm` replaces the event with a real cause (the PostgreSQL controller advisory lock taken
    elsewhere). Settlement entries, the evaluations and how that abandoned heartbeat ended are
    recorded; `ended` is set once its call has returned through the controller's own fence. (That
    helper thread's `is_alive`/`join` cannot say so: once a stop interrupts the evaluator's join,
    CPython 3.12 marks the still-running thread stopped.) The event wait is bounded ONLY so that a
    controller that re-enters the store fails this test instead of hanging it; a real blocked call
    has no such bound.
    """

    def __init__(self, system, monkeypatch, *, arm=None, bound=10, fail=False):
        store, queue, verifier = system["store"], system["delivery"].queue, system["verifier"]
        self.available, self.armed, self.observed = threading.Event(), threading.Event(), threading.Event()
        self.expired, self.ended = threading.Event(), threading.Event()
        self.available.set()
        self.armed_at, self.waiters, self.settled, self.claims, self.late, self.evaluations = \
            None, [], [], [], [], []
        arming = threading.local()
        real_transaction, real_heartbeat = store.transaction, queue.heartbeat
        real_evaluate = verifier.evaluate

        def transaction():
            if not self.available.is_set():
                # Which caller waited on the unavailable store: the controller's own thread or not.
                self.waiters.append(threading.current_thread() is threading.main_thread())
                self.available.wait(bound)
            return real_transaction()

        def heartbeat(claim, now=None):
            if self.armed.is_set():
                return real_heartbeat(claim, now=now)
            self.claims.append(claim)
            arming.call = True
            if arm is None:
                self.available.clear()
            else:
                arm()
            self.armed_at = time.monotonic()
            self.armed.set()
            try:
                if fail:
                    self.waiters.append(threading.current_thread() is threading.main_thread())
                    self.expired.wait(bound)
                    raise StoreCallFailed("labelled fault: the blocked store call failed")
                real_heartbeat(claim, now=now)
                self.late.append("renewed")
            except BaseException as exc:
                self.late.append(type(exc).__name__)
                raise
            finally:
                self.observed.set()

        def settle(name, real):
            def call(*args, **kwargs):
                self.settled.append(name)
                return real(*args, **kwargs)
            return call

        def evaluate(release_id, attempt, *, fence):
            # The intent as stored when an evaluation begins (no transaction is open here).
            self.evaluations.append(intent_of(system))

            def observed(*args, **kwargs):
                try:
                    return fence(*args, **kwargs)
                finally:
                    if getattr(arming, "call", False):
                        self.ended.set()

            return real_evaluate(release_id, attempt, fence=observed)

        if arm is None:
            monkeypatch.setattr(store, "transaction", transaction)
        monkeypatch.setattr(queue, "heartbeat", heartbeat)
        monkeypatch.setattr(queue, "finish", settle("finish", queue.finish))
        monkeypatch.setattr(queue, "defer", settle("defer", queue.defer))
        monkeypatch.setattr(verifier, "evaluate", evaluate)


def test_an_unobservable_store_cancels_without_a_write_and_the_next_tick_attaches_the_receipt(
        tmp_path, monkeypatch):
    system = build(tmp_path, monkeypatch, SerialStore(), fence_seconds=0.5)
    delivery = system["delivery"]
    assert delivery.tick()["stage"] == VERIFYING
    real = delivery.queue.heartbeat
    blocked, observed = threading.Event(), threading.Event()
    claims = []

    def heartbeat(claim, now=None):
        # Labelled: a store call that neither returns nor fails within the fence bound.
        claims.append(claim)
        try:
            blocked.wait(5)
            return real(claim, now=now)
        finally:
            observed.set()

    monkeypatch.setattr(delivery.queue, "heartbeat", heartbeat)
    started = time.monotonic()
    result = delivery.tick()
    blocked.set()
    assert result["outcome"] == "unavailable" and result["reason_code"] == "verification_fence_unobservable"
    assert result["claim"] == "unsettled"  # nothing was settled through the unobserved store either
    assert time.monotonic() - started < 60
    assert observed.wait(10)  # the abandoned observation was never cancelled; it completes later
    (attempt,) = intent_of(system)["verification"]["attempts"]
    assert attempt["cleanup"] is None  # nothing committed after the evaluation
    assert disk_record(system, attempt["attempt_id"])["state"] == "resolved"
    monkeypatch.setattr(delivery.queue, "heartbeat", real)
    # The claim was neither finished nor released: the row stays running until its lease expires.
    row = queue_row(system)
    assert row["status"] == "running" and row["generation"] == claims[0]["generation"]
    system["clock"].advance(POLICY.release_lease_seconds + 60)  # past the (once renewed) lease
    results = drive(system, until=PUBLISHING)
    attempts = intent_of(system)["verification"]["attempts"]
    assert attempts[0]["cleanup"]["state"] == "confirmed"  # attached from the disk record
    assert results[-1]["stage"] == PUBLISHING and len(attempts) == 2


def test_an_unobservable_fence_settles_and_writes_nothing_through_the_same_unavailable_store(
        tmp_path, monkeypatch):
    """R1: ONE unavailable store blocks the heartbeat AND every settlement or write after it; the
    tick returns on its own, the claim stays running for lease expiry, and only the next owner,
    after reconciling the first attempt from its disk record, evaluates again."""
    system = build(tmp_path, monkeypatch, SerialStore(), fence_seconds=0.1)
    delivery = system["delivery"]
    assert delivery.tick()["stage"] == VERIFYING
    system["clock"].advance(1)
    before, queued = intent_of(system), queue_row(system)
    outage = StoreOutage(system, monkeypatch)
    try:
        result = delivery.tick()
        returned = time.monotonic()
        # The store is STILL unavailable here: the tick came back on its own and says so.
        assert outage.armed.is_set() and not outage.available.is_set()
        assert returned - outage.armed_at < 5
        assert result["outcome"] == "unavailable" and result["reason_code"] == "verification_fence_unobservable"
        assert result["claim"] == "unsettled" and result["stage"] == VERIFYING
        # Neither `finish` nor `defer` was entered, and only the abandoned heartbeat waited on the store.
        assert outage.settled == [] and outage.waiters == [False]
        assert not outage.observed.is_set()  # that heartbeat is still in flight: nothing cancelled it
    finally:
        outage.available.set()
    assert outage.observed.wait(10) and outage.late == ["renewed"]  # a late renewal of the same lease
    claim = outage.claims[0]
    row = queue_row(system)
    assert row["status"] == "running" and row["owner"] == claim["owner"]
    assert row["generation"] == claim["generation"] and row["attempt"] == claim["attempt"]
    assert row.get("attempts") == queued.get("attempts")  # no finish/defer entry was ever appended
    after = intent_of(system)
    (attempt,) = after["verification"]["attempts"]
    assert attempt["state"] == "prepared" and attempt["cleanup"] is None and attempt["outcome"] is None
    assert {k: v for k, v in after.items() if k not in {"verification", "updated_at"}} == \
        {k: v for k, v in before.items() if k not in {"verification", "updated_at"}}
    record = disk_record(system, attempt["attempt_id"])
    assert record["state"] == "resolved" and record["cleanup"]["state"] == "confirmed"
    assert [step.get("verdict") for step in record["lifecycle"] if step["state"] == "interrupted"] == \
        ["fence_unobservable"]
    # Before the lease expires nothing else acts: no second evaluation and no second attempt.
    monkeypatch.setattr(system["verifier"], "fence_seconds", 30)  # later observations are unhurried
    busy = delivery.tick()
    assert busy["outcome"] == "controller_busy" and busy["reason_code"] == "controller_lease_held"
    assert len(outage.evaluations) == 1 and len(intent_of(system)["verification"]["attempts"]) == 1
    # Past the lease the next owner reconciles FIRST, and only then evaluates a second attempt.
    system["clock"].advance(POLICY.release_lease_seconds + 60)
    results = drive(system, until=PUBLISHING)
    assert results[-1]["stage"] == PUBLISHING
    attempts = intent_of(system)["verification"]["attempts"]
    assert len(attempts) == 2 and attempts[0]["cleanup"]["state"] == "confirmed"
    assert len(outage.evaluations) == 2
    assert [row["attempt_id"] for row in unresolved_attempts(outage.evaluations[1])] == \
        [attempts[1]["attempt_id"]]
    assert all(len(unresolved_attempts(snapshot)) == 1 for snapshot in outage.evaluations)


@pytest.mark.skip(reason='S10: the host-delivery run loop (adapters.host_delivery.run_loop; no S8 gap)')
def test_a_stop_during_a_blocked_fence_touches_no_store_and_a_repeated_signal_is_only_the_flag(
        tmp_path, monkeypatch):
    """The first SIGTERM lands while the heartbeat is blocked (well inside the default fence bound):
    the attempt is cancelled and cleaned up, and the tick returns without finish, defer or an intent
    write through the store that is still unavailable. A second SIGTERM only sets the flag."""
    system = build(tmp_path, monkeypatch, SerialStore())
    delivery = system["delivery"]
    assert delivery.tick()["stage"] == VERIFYING
    system["clock"].advance(1)
    before = intent_of(system)
    outage = StoreOutage(system, monkeypatch)
    signals = []

    def deliver():
        if outage.armed.wait(120):
            signals.append("first")  # recorded BEFORE the signal, which the main thread handles at once
            os.kill(os.getpid(), signal.SIGTERM)

    real_put = system["artifacts"].put

    def put(*args, **kwargs):
        # The attempt's own receipt after its cancellation, in the main thread: a repeated stop.
        if signals == ["first"]:
            signals.append("second")
            os.kill(os.getpid(), signal.SIGTERM)
        return real_put(*args, **kwargs)

    monkeypatch.setattr(system["artifacts"], "put", put)
    sender = threading.Thread(target=deliver, daemon=True)
    sender.start()
    try:
        summary = run_loop(delivery, interval=1, max_ticks=3, sleep=lambda _s: None)
        returned = time.monotonic()
        sender.join(30)
        assert signals == ["first", "second"] and not sender.is_alive()
        assert summary["stopped"] is True and summary["ticks"] == 1
        assert summary["outcomes"] == {"unavailable": 1}
        assert returned - outage.armed_at < 5  # neither the fence bound nor the store ended it
        assert outage.settled == [] and outage.waiters == [False]
        assert not outage.observed.is_set()
    finally:
        outage.available.set()
    assert outage.observed.wait(10)
    claim = outage.claims[0]
    row = queue_row(system)
    assert row["status"] == "running" and row["owner"] == claim["owner"]
    assert row["generation"] == claim["generation"]
    after = intent_of(system)
    (attempt,) = after["verification"]["attempts"]
    assert attempt["state"] == "prepared" and attempt["cleanup"] is None
    assert after["reason_code"] == before["reason_code"]  # no `verification_interrupted` write either
    record = disk_record(system, attempt["attempt_id"])
    assert record["state"] == "resolved" and record["cleanup"]["state"] == "confirmed"
    assert [step.get("verdict") for step in record["lifecycle"] if step["state"] == "interrupted"] == \
        ["interrupted"]
    release, image = release_of(system)
    assert release["status"] == "reviewed" and image is None


def stop_then_fail_the_heartbeat(system, monkeypatch, outage):
    """Run the loop: the first SIGTERM lands while the heartbeat is blocked, and the cancelled
    attempt's receipt (main thread) goes on only after that heartbeat's call has ENDED in a failure
    and returned through the controller's fence - the cleanup outlasted the store's own bound.
    Returns the loop summary, every tick receipt and when the heartbeat ended and the loop returned."""
    delivery, signals, receipts, failed = system["delivery"], [], [], []
    real_put, real_tick = system["artifacts"].put, delivery.tick

    def deliver():
        if outage.armed.wait(120):
            signals.append("first")  # recorded BEFORE the signal, which the main thread handles at once
            os.kill(os.getpid(), signal.SIGTERM)

    def put(*args, **kwargs):
        if signals == ["first"] and not failed:
            outage.expired.set()
            outage.ended.wait(30)  # asserted below: an error raised here would be the receipt's own
            failed.append(time.monotonic())
        return real_put(*args, **kwargs)

    def tick():
        receipts.append(real_tick())
        return receipts[-1]

    monkeypatch.setattr(system["artifacts"], "put", put)
    monkeypatch.setattr(delivery, "tick", tick)
    sender = threading.Thread(target=deliver, daemon=True)
    sender.start()
    summary = run_loop(delivery, interval=1, max_ticks=3, sleep=lambda _s: None)
    returned = time.monotonic()
    sender.join(30)
    assert signals == ["first"] and not sender.is_alive()
    assert len(failed) == 1 and outage.ended.is_set()
    return {"summary": summary, "receipts": receipts, "failed": failed[0], "returned": returned}


@pytest.mark.skip(reason='S10: the host-delivery run loop (adapters.host_delivery.run_loop; no S8 gap)')
def test_a_stop_during_a_blocked_fence_whose_heartbeat_then_fails_still_settles_nothing(tmp_path, monkeypatch):
    """R1 repair: the heartbeat blocked under a stop FAILS before the evaluation returns, so no
    observation is in flight any more - yet the store never answered it, and the same outage still
    blocks every settlement and intent write. The tick commits, writes and settles nothing."""
    system = build(tmp_path, monkeypatch, SerialStore())
    assert system["delivery"].tick()["stage"] == VERIFYING
    system["clock"].advance(1)
    before = intent_of(system)
    outage = StoreOutage(system, monkeypatch, fail=True)
    try:
        run = stop_then_fail_the_heartbeat(system, monkeypatch, outage)
        assert outage.late == ["StoreCallFailed"] and not outage.available.is_set()
        assert run["summary"]["stopped"] is True and run["summary"]["ticks"] == 1
        (result,) = run["receipts"]
        assert result["outcome"] == "unavailable" and result["reason_code"] == "verification_fence_unobservable"
        assert result["claim"] == "unsettled"
        assert run["returned"] - outage.armed_at < 5
        # Neither `finish` nor `defer` was entered, and the controller's thread never waited on the store.
        assert outage.settled == [] and outage.waiters == [False]
    finally:
        outage.available.set()
    claim = outage.claims[0]
    row = queue_row(system)
    assert row["status"] == "running" and row["owner"] == claim["owner"]
    assert row["generation"] == claim["generation"]
    after = intent_of(system)
    (attempt,) = after["verification"]["attempts"]
    assert attempt["state"] == "prepared" and attempt["cleanup"] is None
    assert after["reason_code"] == before["reason_code"]  # no `verification_interrupted` write either
    record = disk_record(system, attempt["attempt_id"])
    assert record["state"] == "resolved" and record["cleanup"]["state"] == "confirmed"
    assert [step.get("verdict") for step in record["lifecycle"] if step["state"] == "interrupted"] == \
        ["interrupted"]


def test_the_verification_fence_reports_an_observation_in_flight_and_refuses_a_later_one():
    """The fence `_verify` hands the evaluator: `close` says whether an abandoned heartbeat is still
    in flight, and a heartbeat that had not begun by then never reaches the store at all."""
    from codex_harness.delivery.application.host_delivery.stages.verify import _FenceObservations

    answered, calls = threading.Event(), []

    def heartbeat():
        calls.append("heartbeat")
        if len(calls) > 1:
            answered.wait(10)  # labelled: the store stops answering from the second call on

    fence = _FenceObservations(heartbeat)
    fence()
    abandoned = threading.Thread(target=fence, daemon=True)
    abandoned.start()
    deadline = time.monotonic() + 10
    while len(calls) < 2 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert fence.close() is True  # in flight: nothing may be committed or settled
    with pytest.raises(DeliveryRefused):
        fence()  # closed: refused before the store is touched
    assert calls == ["heartbeat", "heartbeat"]
    answered.set()
    abandoned.join(10)
    assert not abandoned.is_alive() and fence.close() is False


def test_the_verification_fence_counts_a_failed_observation_as_unobserved_but_not_a_refused_lease():
    """A heartbeat that ended in a store error was never answered, even after it stopped being in
    flight; a refused lease (`ContractError`) is the store's answer and stays `fence_lost`."""
    from m7_delivery import ContractError

    from codex_harness.delivery.application.host_delivery.stages.verify import _FenceObservations

    def refused():
        raise ContractError("Stale release controller")

    def failed():
        raise StoreCallFailed("labelled fault")

    answered = _FenceObservations(refused)
    with pytest.raises(ContractError):
        answered()
    assert answered.close() is False
    unanswered = _FenceObservations(failed)
    with pytest.raises(StoreCallFailed):
        unanswered()
    assert unanswered.close() is True


@pytest.mark.integration
def test_a_blocked_postgres_heartbeat_is_bounded_by_the_fence_not_by_an_assumed_timeout(isolated_pgstore):
    """The real store: the controller advisory lock is held elsewhere, so the heartbeat blocks."""
    import psycopg
    from m7_delivery import FenceUnobservable, bounded_fence

    store = isolated_pgstore
    org = organization()
    releases = Releases(store, org)
    candidate = {"revision": "a" * 40, "base": "b" * 40, "tree": "c" * 40, "author": "worker:implementation",
                 "branch": "harness/fence", "task_id": "fence"}
    row = releases.propose(candidate, POLICY_CHECKS)
    releases.review(row["id"], "lead:improvement", candidate["revision"], True, "fixture-evidence")
    releases.review(row["id"], "conductor", candidate["revision"], True, "fixture-evidence")
    queue = ReleaseQueue(store)
    queue.enqueue(row["id"], "fence fixture")
    claim = queue.claim()
    fence = bounded_fence(lambda: queue.heartbeat(claim), seconds=1.0)
    fence()  # observable: completes within its bound
    with psycopg.connect(store.dsn) as holder:
        holder.execute("SELECT pg_advisory_lock(734219)")
        started = time.monotonic()
        with pytest.raises(FenceUnobservable):
            fence()
        assert time.monotonic() - started < 5
        holder.execute("SELECT pg_advisory_unlock(734219)")
    fence()  # observable again once the store answers


@pytest.mark.integration
def test_a_blocked_postgres_store_returns_the_whole_tick_unsettled_well_before_lock_timeout(
        tmp_path, monkeypatch, isolated_pgstore):
    """R1 on the real store: from the first heartbeat on the controller advisory lock is held
    elsewhere, so that heartbeat AND any settlement would wait up to `lock_timeout` (10 s) and then
    raise. The whole tick returns well before that, without raising, and leaves the claim running."""
    import psycopg

    system = build(tmp_path, monkeypatch, isolated_pgstore, fence_seconds=0.5)
    delivery = system["delivery"]
    assert delivery.tick()["stage"] == VERIFYING
    system["clock"].advance(1)
    with psycopg.connect(isolated_pgstore.dsn, autocommit=True) as holder:
        outage = StoreOutage(system, monkeypatch,
                             arm=lambda: holder.execute("SELECT pg_advisory_lock(734219)"))
        try:
            result = delivery.tick()
            returned = time.monotonic()
            assert outage.armed.is_set() and returned - outage.armed_at < 5
            assert result["outcome"] == "unavailable"
            assert result["reason_code"] == "verification_fence_unobservable"
            assert result["claim"] == "unsettled" and outage.settled == []
        finally:
            holder.execute("SELECT pg_advisory_unlock(734219)")
    assert outage.observed.wait(15)  # the abandoned heartbeat ends on its own once the store answers
    claim = outage.claims[0]
    row = queue_row(system)
    assert row["status"] == "running" and row["owner"] == claim["owner"]
    assert row["generation"] == claim["generation"]
    (attempt,) = intent_of(system)["verification"]["attempts"]
    assert attempt["state"] == "prepared" and attempt["cleanup"] is None
    assert disk_record(system, attempt["attempt_id"])["state"] == "resolved"


@pytest.mark.skip(reason='S10: the host-delivery run loop (adapters.host_delivery.run_loop; no S8 gap)')
@pytest.mark.integration
def test_a_stop_while_a_blocked_postgres_heartbeat_times_out_settles_nothing(
        tmp_path, monkeypatch, isolated_pgstore):
    """R1 repair on the real store: a stop lands while the heartbeat waits for the controller
    advisory lock held elsewhere; that heartbeat then ends in `LockNotAvailable` (lock_timeout)
    during the cancelled attempt's cleanup, and the lock is still held. The tick returns without
    raising and without waiting on the store again, and leaves the claim running."""
    import psycopg

    system = build(tmp_path, monkeypatch, isolated_pgstore)
    assert system["delivery"].tick()["stage"] == VERIFYING
    system["clock"].advance(1)
    with psycopg.connect(isolated_pgstore.dsn, autocommit=True) as holder:
        outage = StoreOutage(system, monkeypatch,
                             arm=lambda: holder.execute("SELECT pg_advisory_lock(734219)"))
        try:
            run = stop_then_fail_the_heartbeat(system, monkeypatch, outage)
            assert outage.late == ["LockNotAvailable"]
            (result,) = run["receipts"]
            assert result["outcome"] == "unavailable"
            assert result["reason_code"] == "verification_fence_unobservable"
            assert result["claim"] == "unsettled" and outage.settled == []
            assert run["returned"] - run["failed"] < 5  # well under another lock_timeout
        finally:
            holder.execute("SELECT pg_advisory_unlock(734219)")
    claim = outage.claims[0]
    row = queue_row(system)
    assert row["status"] == "running" and row["owner"] == claim["owner"]
    assert row["generation"] == claim["generation"]
    (attempt,) = intent_of(system)["verification"]["attempts"]
    assert attempt["state"] == "prepared" and attempt["cleanup"] is None
    assert disk_record(system, attempt["attempt_id"])["state"] == "resolved"


# ----- L-11: the evaluator split keeps the legacy contract ---------------------------------------
def test_the_evaluator_writes_nothing_to_the_store_and_legacy_names_stay_random(tmp_path, monkeypatch):
    system = build(tmp_path, monkeypatch, SerialStore())
    store = system["store"]
    runner = system["verifier"].runner(lambda: None)
    with store.transaction() as tx:
        before = tx.records()
    owned = runner.evaluate(system["release"]["id"], attempt="7" * 32)
    assert owned["verdict"] == "checked" and owned["passed"] is True
    assert owned["receipt"]["project"] == "zeus-verify-" + "7" * 32
    legacy = runner._evaluate(system["release"], None)  # the legacy recorder's own call
    assert legacy["verdict"] == "checked" and legacy["passed"] is True
    with store.transaction() as tx:
        assert tx.records() == before
    runs = [call for call in system["daemon"].calls() if call[:1] == ["run"]]
    legacy_start, legacy_canary = runs[-2:]
    assert "--name" not in legacy_start and not any("zeus.isolated" in part for part in legacy_start)
    assert legacy_canary[legacy_canary.index("--name") + 1].startswith("harness-canary-")
    assert FixtureServices.entered[-2][1] != "zeus-verify-" + "7" * 32  # a random legacy project
