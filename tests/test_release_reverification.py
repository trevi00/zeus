"""INV-RELEASE-REVERIFY-001: history-preserving reverification of a check-rejected release.

Every candidate, review, check and receipt here is a labelled fixture; nothing claims an actual
Codex, GitHub or production verification. PostgreSQL cases run only with HARNESS_INTEGRATION=1.
"""
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from codex_harness.adapters.artifacts import FileArtifacts
from codex_harness.adapters.deployment import ReleaseRunner
from codex_harness.adapters.store import MemoryStore
from codex_harness.application.release_queue import ReleaseQueue
from codex_harness.application.releases import Releases
from codex_harness.application.service import Harness
from codex_harness.bootstrap import organization
from codex_harness.domain.model import ContractError, digest

CHECKS = ["tests", "cli_start", "cli_file_task"]
TICKET_CONTENT = {"title": "fixture ticket"}
TICKET = {"id": "ticket-1", "revision": "r1", "content_hash": digest(TICKET_CONTENT)}
REQUEST = {"actor": "conductor", "expected_revision": "candidate", "reason": "fixture: short TEMP diagnosis",
           "evidence": "fixture:diagnosis-receipt"}


def store_for(backend, request):
    return MemoryStore() if backend == "memory" else request.getfixturevalue("isolated_pgstore")


def backends():
    return pytest.mark.parametrize("backend", ["memory", pytest.param("postgres", marks=pytest.mark.integration)])


def snapshot(store):
    with store.transaction() as tx:
        return {(row["bucket"], row["id"]): row["body"] for row in tx.records()}


def rejected_release(store, *, ticket=False):
    releases = Releases(store, organization())
    candidate = {"revision": "candidate", "base": "base", "tree": "tree", "author": "worker:implementation"}
    if ticket:
        with store.transaction() as tx:
            tx.put("tickets", TICKET["id"], {**TICKET, "status": "open"})
            tx.put("ticket_revisions", "ticket-1:r1", {"content": TICKET_CONTENT})
        candidate["zeus_ticket"] = TICKET
    release = releases.propose(candidate, {"checks": CHECKS})
    for actor in ("lead:improvement", "conductor"):
        releases.review(release["id"], actor, "candidate", True, "fixture:review")
    checks = {"tests": {"passed": False, "evidence": "fixture:tests-failed"}, **{name: {"passed": False, "skipped": True, "evidence": "fixture:not-run"}
                                 for name in CHECKS[1:]}}
    release = releases.verify(release["id"], "candidate", release["policy_hash"], checks)
    assert release["status"] == "rejected"
    return releases, release


def reverify(releases, release, **overrides):
    return releases.request_reverification(release["id"], **{
        **REQUEST, "expected_policy_hash": release["policy_hash"], **overrides})


@backends()
def test_check_rejected_release_gets_one_reviewed_successor_and_history_is_unchanged(backend, request):
    store = store_for(backend, request)
    releases, source = rejected_release(store)
    before = snapshot(store)
    child = reverify(releases, source)
    after = snapshot(store)
    event_key = ("events", "release.reverification_requested:" + child["id"])
    assert set(after) - set(before) == {("releases", child["id"]), event_key}
    assert {key: after[key] for key in before} == before  # source, reviews, checks, history untouched
    assert child["id"] != source["id"] and child["reverify_of"] == source["id"]
    assert child["status"] == "reviewed" and child["checks"] == {}
    assert child["candidate"] == source["candidate"] and child["policy"] == source["policy"]
    assert child["policy_hash"] == source["policy_hash"] == digest(child["policy"])
    assert child["reviews"] == source["reviews"]
    assert child["inherited_reviews"] == {"release_id": source["id"], "digest": digest(source["reviews"])}
    receipt = child["reverification"]
    assert {k: receipt[k] for k in ("actor", "reason", "evidence")} == {
        k: REQUEST[k] for k in ("actor", "reason", "evidence")}
    assert receipt["source_checks_digest"] == digest(source["checks"]) and receipt["at"]
    assert after[event_key]["reverify_of"] == source["id"]
    # Creation runs nothing: no queue row, image, promotion intent or deployment for the successor.
    assert not any(bucket in {"release_queue", "images", "promotion_intents", "deployment"}
                   for bucket, _ in set(after) - set(before))
    # The existing propose identity still names the rejected source.
    assert releases.propose(source["candidate"], source["policy"])["id"] == source["id"]


@backends()
def test_successor_still_requires_complete_fresh_checks(backend, request):
    store = store_for(backend, request)
    releases, source = rejected_release(store)
    child = reverify(releases, source)
    with pytest.raises(ContractError, match="Missing or extra"):
        releases.verify(child["id"], "candidate", child["policy_hash"],
                        {"tests": {"passed": True, "evidence": "fixture:tests"}})
    with pytest.raises(ContractError, match="real execution evidence"):
        releases.verify(child["id"], "candidate", child["policy_hash"],
                        {name: {"passed": True} for name in CHECKS})
    with pytest.raises(ContractError, match="Release not verified"):
        releases.promote(child["id"], None)
    fresh = {name: {"passed": True, "evidence": "fixture:fresh-" + name} for name in CHECKS}
    assert releases.verify(child["id"], "candidate", child["policy_hash"], fresh)["status"] == "verified"
    with store.transaction() as tx:
        assert tx.get("releases", source["id"]) == source


def test_normal_queue_and_runner_execute_every_check_for_the_successor(tmp_path, monkeypatch,
                                                                       fake_verification_services):
    service = Harness(MemoryStore(), organization())
    service.store.dsn = "fixture:no-connection"
    git = SimpleNamespace(repository=tmp_path, _git=lambda *args: "base", inspect=lambda *args: {"tree": "tree"},
                          review_workspace=lambda *args: str(tmp_path))
    artifacts = FileArtifacts(tmp_path / "artifacts")
    runner = ReleaseRunner(service, git, artifacts, str(tmp_path / "unused-auth"))
    candidate = {"revision": "candidate", "base": "base", "tree": "tree", "author": "worker:implementation"}
    source = runner.releases.propose(candidate, {"checks": CHECKS})
    for actor in ("lead:improvement", "conductor"):
        runner.releases.review(source["id"], actor, "candidate", True, "fixture:review")
    calls, failing = [], {"tests"}

    def check(argv, *args, **kwargs):
        stage = ("install" if argv[:2] == ["uv", "sync"] else "tests" if "pytest" in argv else
                 "startup" if argv[:2] == ["docker", "run"] else "build")
        calls.append(stage)
        return {"passed": stage not in failing, "evidence": artifacts.put(stage, "fixture")["ref"]}

    monkeypatch.setattr(runner, "_check", check)
    monkeypatch.setattr("codex_harness.adapters.deployment.run_process",
                        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="sha256:image"))
    monkeypatch.setattr(runner, "file_canary", lambda image: calls.append("file_canary") or {
        "passed": True, "evidence": artifacts.put("file", "fixture")["ref"]})
    queue = ReleaseQueue(service.store)
    queue.enqueue(source["id"], "fixture conductor acceptance")
    claim = queue.claim()
    assert runner.run(claim["id"])["status"] == "rejected"
    queue.finish(claim, {"status": "rejected"})
    with service.store.transaction() as tx:
        source = tx.get("releases", claim["id"])
    assert calls == ["install", "tests"]
    with pytest.raises(ContractError, match="not recoverable"):
        queue.retry(source["id"], "Retry still refuses a rejected release")

    child = reverify(runner.releases, source)
    with service.store.transaction() as tx:
        assert tx.get("release_queue", child["id"]) is None  # creation enqueues nothing
    queue.enqueue(child["id"], "fixture: owner reverification")
    calls.clear()
    failing.clear()
    promoted = []
    monkeypatch.setattr(runner, "_promote", lambda release, active, image: promoted.append(release["id"])
                        or {"status": "verified"})
    claim = queue.claim()
    assert claim["id"] == child["id"]
    assert runner.run(claim["id"])["status"] == "verified"
    queue.finish(claim, {"status": "done"})
    assert calls == ["install", "tests", "tests", "build", "startup", "file_canary"]
    assert promoted == [child["id"]]
    with service.store.transaction() as tx:
        verified = tx.get("releases", child["id"])
        assert verified["status"] == "verified" and set(verified["checks"]) == set(CHECKS)
        assert all(c["passed"] and c["evidence"] for c in verified["checks"].values())
        assert tx.get("releases", source["id"]) == source
        assert tx.get("images", child["id"])["image"] == "sha256:image"


@backends()
def test_replay_is_idempotent_and_conflicting_request_refuses(backend, request):
    store = store_for(backend, request)
    releases, source = rejected_release(store)
    child = reverify(releases, source)
    before = snapshot(store)
    replay = Releases(store, organization())  # a restarted process
    assert reverify(replay, source) == child
    assert snapshot(store) == before
    for change in ({"reason": "another reason"}, {"evidence": "fixture:other"}):
        with pytest.raises(ContractError, match="Conflicting reverification request"):
            reverify(replay, source, **change)
    assert snapshot(store) == before


@backends()
def test_concurrent_requests_create_one_child(backend, request):
    store = store_for(backend, request)
    releases, source = rejected_release(store)
    results, errors, start = [], [], threading.Barrier(6)

    def attempt(reason):
        start.wait()
        try:
            results.append(reverify(Releases(store, organization()), source, reason=reason))
        except ContractError as exc:
            errors.append(str(exc))

    threads = [threading.Thread(target=attempt, args=(reason,))
               for reason in ["same"] * 3 + ["other"] * 3]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    with store.transaction() as tx:
        children = [r for r in tx.scan("releases") if r.get("reverify_of") == source["id"]]
        events = [e for e in tx.scan("events") if e.get("type") == "release.reverification_requested"]
    assert len(children) == 1 and len(events) == 1
    assert len(results) == 3 and len(errors) == 3
    assert all(r == children[0] for r in results)
    assert set(errors) == {"Conflicting reverification request"}


def test_actor_must_be_conductor_and_request_must_be_explained():
    store = MemoryStore()
    releases, source = rejected_release(store)
    before = snapshot(store)
    for overrides, match in (({"actor": "lead:improvement"}, "required role"),
                             ({"actor": "worker:implementation"}, "required role"),
                             ({"actor": "nobody"}, "Unknown actor"),
                             ({"reason": " "}, "reason and evidence"),
                             ({"evidence": ""}, "reason and evidence"),
                             ({"evidence": ["fixture:list"]}, "reason and evidence")):
        with pytest.raises(ContractError, match=match):
            reverify(releases, source, **overrides)
    assert snapshot(store) == before


@pytest.mark.parametrize("case", ["stale_revision", "stale_policy", "policy_tampered", "not_rejected",
                                  "review_rejected", "stale_review", "missing_lead", "no_evidence",
                                  "only_skipped", "check_missing_evidence", "unknown_release"])
def test_ineligible_source_refuses_without_writes(case):
    store = MemoryStore()
    releases, source = rejected_release(store)
    overrides = {}
    with store.transaction() as tx:
        record = tx.get("releases", source["id"])
        if case == "stale_revision":
            overrides["expected_revision"] = "other"
        elif case == "stale_policy":
            overrides["expected_policy_hash"] = digest({"checks": ["tests"]})
        elif case == "policy_tampered":
            record["policy"] = {"checks": ["tests"]}
        elif case == "not_rejected":
            record["status"] = "verified"
        elif case == "review_rejected":
            record["reviews"].append({"actor": "lead:research", "revision": "candidate",
                                      "accepted": False, "evidence": "fixture:reject"})
        elif case == "stale_review":
            record["reviews"][0]["revision"] = "older"
        elif case == "missing_lead":
            record["reviews"] = [r for r in record["reviews"] if r["actor"] == "conductor"]
        elif case == "no_evidence":
            record["checks"] = {}
        elif case == "only_skipped":
            record["checks"]["tests"] = {"passed": False, "skipped": True, "evidence": "fixture:not-run"}
        elif case == "check_missing_evidence":
            record["checks"]["tests"] = {"passed": False}
        tx.put("releases", source["id"], record)
    before = snapshot(store)
    target = {**source, "id": "missing"} if case == "unknown_release" else source
    with pytest.raises(ContractError):
        reverify(releases, target, **overrides)
    assert snapshot(store) == before


def test_review_rejected_release_is_not_reverifiable():
    store = MemoryStore()
    releases = Releases(store, organization())
    candidate = {"revision": "candidate", "base": "base", "tree": "tree", "author": "worker:implementation"}
    release = releases.propose(candidate, {"checks": CHECKS})
    releases.review(release["id"], "lead:improvement", "candidate", True, "fixture:review")
    release = releases.review(release["id"], "conductor", "candidate", False, "fixture:reject")
    assert release["status"] == "rejected"
    before = snapshot(store)
    with pytest.raises(ContractError, match="review rejected"):
        reverify(releases, release)
    assert snapshot(store) == before


@pytest.mark.parametrize("change", ["superseded", "closed"])
def test_invalid_ticket_binding_refuses_without_writes(change):
    store = MemoryStore()
    releases, source = rejected_release(store, ticket=True)
    with store.transaction() as tx:
        ticket = tx.get("tickets", TICKET["id"])
        tx.put("tickets", TICKET["id"], {**ticket, "revision": "r2"} if change == "superseded"
               else {**ticket, "status": "closed"})
    before = snapshot(store)
    with pytest.raises(ContractError, match="Ticket"):
        reverify(releases, source)
    assert snapshot(store) == before


@pytest.mark.parametrize("effect", ["controller_lease", "queue_running", "promotion_intent", "active_pointer"])
def test_active_lease_or_promotion_effect_refuses_without_writes(effect):
    store = MemoryStore()
    releases, source = rejected_release(store)
    now = datetime.now(timezone.utc)
    with store.transaction() as tx:
        if effect == "controller_lease":
            tx.put("deployment_locks", "controller", {"release_id": "other", "owner": "o",
                   "lease_until": (now + timedelta(minutes=5)).isoformat()})
        elif effect == "queue_running":
            tx.put("release_queue", source["id"], {"id": source["id"], "status": "running"})
        elif effect == "promotion_intent":
            tx.put("promotion_intents", source["id"], {"id": source["id"], "status": "prepared"})
        else:
            tx.put("deployment", "active", {"release_id": source["id"], "revision": "candidate"})
    before = snapshot(store)
    with pytest.raises(ContractError, match="still running|Promotion effects"):
        reverify(releases, source, now=now)
    assert snapshot(store) == before
    if effect == "controller_lease":  # an expired lease no longer blocks the explicit request
        assert reverify(releases, source, now=now + timedelta(minutes=6))["status"] == "reviewed"


class FaultStore:
    """Labelled injected fault: the event write fails after the successor write in one transaction."""

    def __init__(self, store):
        self.store = store

    @contextmanager
    def transaction(self):
        with self.store.transaction() as tx:
            yield SimpleNamespace(get=tx.get, scan=tx.scan, put=self.put(tx))

    @staticmethod
    def put(tx):
        def put(bucket, key, body):
            if bucket == "events":
                raise RuntimeError("injected fault after successor write")
            tx.put(bucket, key, body)
        return put


@backends()
def test_transaction_fault_leaves_no_partial_successor(backend, request):
    store = store_for(backend, request)
    _, source = rejected_release(store)
    before = snapshot(store)
    with pytest.raises(RuntimeError, match="injected fault"):
        reverify(Releases(FaultStore(store), organization()), source)
    assert snapshot(store) == before
    child = reverify(Releases(store, organization()), source)
    assert child["status"] == "reviewed"
