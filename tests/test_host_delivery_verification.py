"""The `verifying` stage and `host-delivery resume` over REAL interfaces (INV-HOST-DELIVERY-VERIFY-001).

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

from codex_harness.adapters import deployment, host_delivery
from codex_harness.adapters.artifacts import FileArtifacts
from codex_harness.adapters.deployment import ReleaseRunner
from codex_harness.adapters.git import GitWorkspace
from codex_harness.adapters.host_delivery import (
    ProcessHostTarget,
    add_parser,
    execute,
    owner_qualified_canary,
    run_loop,
    startup_identity_canary,
)
from codex_harness.adapters.release_verifier import ReleaseVerifier
from codex_harness.application.host_delivery import BUCKET_INTENTS, HostDelivery
from codex_harness.application.release_queue import ReleaseQueue
from codex_harness.application.releases import Releases
from codex_harness.bootstrap import organization
from codex_harness.domain.host_delivery import (
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
    validate_plan,
)

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


def test_an_unobservable_store_cancels_without_a_write_and_the_next_tick_attaches_the_receipt(
        tmp_path, monkeypatch):
    system = build(tmp_path, monkeypatch, SerialStore(), fence_seconds=0.5)
    delivery = system["delivery"]
    assert delivery.tick()["stage"] == VERIFYING
    real = delivery.queue.heartbeat
    blocked = threading.Event()

    def heartbeat(claim, now=None):
        # Labelled: a store call that neither returns nor fails within the fence bound.
        blocked.wait(5)
        return real(claim, now=now)

    monkeypatch.setattr(delivery.queue, "heartbeat", heartbeat)
    started = time.monotonic()
    result = delivery.tick()
    blocked.set()
    assert result["outcome"] == "unavailable" and result["reason_code"] == "verification_fence_unobservable"
    assert time.monotonic() - started < 60
    (attempt,) = intent_of(system)["verification"]["attempts"]
    assert attempt["cleanup"] is None  # nothing committed after the evaluation
    assert disk_record(system, attempt["attempt_id"])["state"] == "resolved"
    monkeypatch.setattr(delivery.queue, "heartbeat", real)
    with system["store"].transaction() as tx:
        row = tx.get("release_queue", system["release"]["id"])
        tx.put("release_queue", row["id"], {**row, "retry_at": None})  # skip the backoff wait
    results = drive(system, until=PUBLISHING)
    attempts = intent_of(system)["verification"]["attempts"]
    assert attempts[0]["cleanup"]["state"] == "confirmed"  # attached from the disk record
    assert results[-1]["stage"] == PUBLISHING and len(attempts) == 2


@pytest.mark.integration
def test_a_blocked_postgres_heartbeat_is_bounded_by_the_fence_not_by_an_assumed_timeout(isolated_pgstore):
    """The real store: the controller advisory lock is held elsewhere, so the heartbeat blocks."""
    import psycopg

    from codex_harness.adapters.release_verifier import FenceUnobservable, bounded_fence

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
