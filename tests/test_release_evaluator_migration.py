"""INV-RELEASE-EVALUATOR-MIGRATION-001: an owner-approved evaluator successor of a rejected release.

Every candidate, review, check, approval and repository here is a labelled fixture; nothing claims
an actual Codex, GitHub or production verification. PostgreSQL cases run only with
HARNESS_INTEGRATION=1.
"""
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_release_reverification import backends, rejected_release, reverify, snapshot, store_for
from verification_fixtures import git, source_repository

from codex_harness.adapters.artifacts import FileArtifacts
from codex_harness.adapters.deployment import (
    EvaluatorPinMismatch,
    ReleaseRunner,
    evaluator_patch_sha256,
    resolve_evaluator_pin,
)
from codex_harness.adapters.git import GitWorkspace
from codex_harness.adapters.store import MemoryStore
from codex_harness.application.releases import (
    Releases,
    UnsupportedEvaluatorReverification,
    expected_evaluator_pin,
)
from codex_harness.bootstrap import organization
from codex_harness.domain.model import ContractError, digest

E = "e" * 40


def approval_for(release, **overrides):
    return {"source_release_id": release["id"], "base": release["candidate"]["base"],
            "evaluator_revision": E, "evaluator_tree": "f" * 40, "patch_sha256": "a" * 64,
            "paths": ["tests/test_fixture.py"], "evidence": "sha256:" + "b" * 64,
            "approved_by": "conductor", **overrides}


def migrate(releases, release, *, actor="conductor", approval=None, **overrides):
    approval = approval if approval is not None else approval_for(release)
    # Labelled: the trusted resolver's result for a fixture repository that agrees with the approval.
    resolved = overrides.pop("resolved_pin", None) or expected_evaluator_pin(approval)
    return releases.request_evaluator_migration(
        release["id"], actor, expected_revision=overrides.pop("expected_revision", "candidate"),
        expected_policy_hash=overrides.pop("expected_policy_hash", release["policy_hash"]),
        approval=approval, resolved_pin=resolved, **overrides)


@backends()
def test_migration_successor_changes_only_the_evaluator_revision(backend, request):
    store = store_for(backend, request)
    releases, source = rejected_release(store)
    before = snapshot(store)
    child = migrate(releases, source)
    after = snapshot(store)
    event_key = ("events", "release.evaluator_migration_requested:" + child["id"])
    assert set(after) - set(before) == {("releases", child["id"]), event_key}
    assert {key: after[key] for key in before} == before  # the source bytes are untouched
    assert child["id"] == digest({"evaluator_migration_of": source["id"]}) != source["id"]
    assert child["status"] == "reviewed" and child["checks"] == {} and "image" not in child
    assert child["candidate"] == source["candidate"] and child["reviews"] == source["reviews"]
    assert child["policy"] == {**source["policy"], "revision": E}
    assert child["policy"]["checks"] == source["policy"]["checks"]
    assert child["policy_hash"] == digest(child["policy"]) != source["policy_hash"]
    assert child["reverify_of"] == source["id"]
    assert child["inherited_reviews"] == {"release_id": source["id"], "digest": digest(source["reviews"])}
    receipt = child["evaluator_migration"]
    assert {k: receipt[k] for k in approval_for(source)} == approval_for(source)
    assert receipt["actor"] == "conductor" and receipt["source_policy_hash"] == source["policy_hash"]
    assert receipt["source_checks_digest"] == digest(source["checks"])
    assert receipt["source_digest"] == digest(source) and receipt["at"]
    assert not any(bucket in {"release_queue", "images", "promotion_intents", "deployment"}
                   for bucket, _ in set(after) - set(before))
    # The successor still needs every check produced afresh under its own policy hash.
    with pytest.raises(ContractError, match="Stale candidate or evaluator"):
        releases.verify(child["id"], "candidate", source["policy_hash"],
                        {name: {"passed": True, "evidence": "fixture:" + name} for name in source["checks"]})


@backends()
def test_replay_returns_the_successor_and_any_difference_conflicts(backend, request):
    store = store_for(backend, request)
    releases, source = rejected_release(store)
    child = migrate(releases, source)
    before = snapshot(store)
    assert migrate(releases, source) == child
    assert snapshot(store) == before
    for changed in ({"evaluator_revision": "d" * 40}, {"evidence": "sha256:" + "c" * 64},
                    {"patch_sha256": "c" * 64}, {"paths": ["tests/other.py"]}):
        with pytest.raises(ContractError, match="Conflicting evaluator migration"):
            migrate(releases, source, approval=approval_for(source, **changed))
    with pytest.raises(ContractError, match="Conflicting evaluator migration"):
        migrate(releases, source, expected_policy_hash="other")
    assert snapshot(store) == before


def test_conflicting_actor_replay_is_refused(monkeypatch):
    store = MemoryStore()
    releases, source = rejected_release(store)
    migrate(releases, source)
    org = organization()
    second = next(a for a in org.agents.values() if a.role == "conductor")
    monkeypatch.setattr(releases.org, "actor", lambda actor_id, role=None: second)
    with pytest.raises(ContractError, match="Conflicting evaluator migration"):
        migrate(releases, source, actor="conductor-replacement")


def test_plain_reverification_successor_blocks_a_migration_and_stays_unchanged():
    store = MemoryStore()
    releases, source = rejected_release(store)
    plain = reverify(releases, source)
    before = snapshot(store)
    with pytest.raises(ContractError, match="already has a reverification successor"):
        migrate(releases, source)
    assert snapshot(store) == before and reverify(releases, source) == plain


def test_stale_and_non_rejected_sources_are_refused():
    store = MemoryStore()
    releases, source = rejected_release(store)
    with pytest.raises(ContractError, match="Stale candidate or evaluator"):
        migrate(releases, source, expected_revision="other")
    with pytest.raises(ContractError, match="Stale candidate or evaluator"):
        migrate(releases, source, expected_policy_hash="other")
    reviewed = releases.propose({**source["candidate"], "tree": "tree-2"}, source["policy"])
    for actor in ("lead:improvement", "conductor"):
        releases.review(reviewed["id"], actor, "candidate", True, "fixture:review")
    with pytest.raises(ContractError, match="not check-rejected"):
        migrate(releases, reviewed, approval=approval_for(reviewed))
    with store.transaction() as tx:
        tx.put("deployment_locks", "controller",
               {"lease_until": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()})
    with pytest.raises(ContractError, match="controller still running"):
        migrate(releases, source)


@pytest.mark.parametrize("actor, overrides, reason", [
    ("lead:improvement", {}, "lacks required role"),
    ("conductor", {"approved_by": "worker:implementation"}, "lacks required role"),
    ("conductor", {"approved_by": "nobody"}, "Unknown actor"),
    ("conductor", {"source_release_id": "other"}, "names another release"),
    ("conductor", {"base": "other-base"}, "base differs"),
    ("conductor", {"paths": ["src/app.py"]}, "only tests/"),
    ("conductor", {"paths": ["tests/../src/app.py"]}, "only tests/"),
    ("conductor", {"paths": []}, "sorted non-empty"),
    ("conductor", {"paths": ["tests/b.py", "tests/a.py"]}, "sorted non-empty"),
    ("conductor", {"evaluator_revision": "E"}, "pin malformed"),
    ("conductor", {"evidence": "fixture:evidence"}, "pin malformed"),
    ("conductor", {"patch_sha256": 7}, "approval incomplete"),
])
def test_authority_and_approval_shape_are_refused(actor, overrides, reason):
    store = MemoryStore()
    releases, source = rejected_release(store)
    before = snapshot(store)
    with pytest.raises(ContractError, match=reason):
        migrate(releases, source, actor=actor, approval=approval_for(source, **overrides))
    extra = {**approval_for(source), "note": "extra"}
    with pytest.raises(ContractError, match="approval incomplete"):
        migrate(releases, source, approval=extra)
    assert snapshot(store) == before


def test_evaluator_must_differ_from_candidate_and_base_and_author_cannot_approve(monkeypatch):
    store = MemoryStore()
    releases, source = rejected_release(store)
    hexed = {**source["candidate"], "revision": "c" * 40, "base": "d" * 40, "tree": "tree-hex"}
    other = releases.propose(hexed, source["policy"])
    for actor in ("lead:improvement", "conductor"):
        releases.review(other["id"], actor, "c" * 40, True, "fixture:review")
    checks = {"tests": {"passed": False, "evidence": "fixture:failed"},
              **{name: {"passed": False, "skipped": True, "evidence": "fixture:not-run"}
                 for name in source["policy"]["checks"][1:]}}
    other = releases.verify(other["id"], "c" * 40, other["policy_hash"], checks)
    for evaluator in ("c" * 40, "d" * 40):
        with pytest.raises(ContractError, match="must differ from candidate and base"):
            migrate(releases, other, expected_revision="c" * 40,
                    approval=approval_for(other, evaluator_revision=evaluator))
    author = releases.org.agents["worker:implementation"]
    original = releases.org.actor
    monkeypatch.setattr(releases.org, "actor", lambda actor_id, role=None: author
                        if actor_id == "worker:implementation" and role == "conductor"
                        else original(actor_id, role))
    with pytest.raises(ContractError, match="approver is the candidate author"):
        migrate(releases, source, approval=approval_for(source, approved_by="worker:implementation"))


def test_migration_runs_inside_the_callers_transaction():
    store = MemoryStore()
    releases, source = rejected_release(store)
    with store.transaction() as tx:
        child = migrate(releases, source, transaction=tx)
        assert tx.get("releases", child["id"]) == child
    with store.transaction() as tx:
        assert tx.get("releases", child["id"]) == child


# ---- the runner selects and re-derives the evaluator pin ------------------------------------------

def evaluator_commit(repo: dict, *, extra: bool = False, grandchild: bool = False) -> dict:
    """A labelled tests-only evaluator commit E whose direct parent is the candidate base
    (`grandchild`: a consistent tests-only E two commits away, which the parent rule refuses)."""
    root = repo["root"]
    git(root, "checkout", "-q", "--detach", repo["base"])
    if grandchild:
        (root / "tests" / "test_between.py").write_text("def test_between():\n    assert True\n",
                                                          encoding="utf-8")
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", "between")
    (root / "tests" / "test_fixture.py").write_text(
        "def test_incumbent_fixture():\n    assert 'evaluator'\n", encoding="utf-8")
    if extra:
        (root / "feature.txt").write_text("evaluator touched code\n", encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "evaluator")
    revision = git(root, "rev-parse", "HEAD")
    git(root, "checkout", "-q", "--detach", repo["base"])
    inspected = GitWorkspace(str(root), str(root.parent / "probe")).inspect(revision, repo["base"])
    return {"evaluator_revision": revision, "evaluator_tree": inspected["tree"],
            "patch_sha256": evaluator_patch_sha256(inspected["diff"]), "paths": sorted(inspected["files"])}


def runner_for(tmp_path, repo, release, monkeypatch):
    store = MemoryStore()
    with store.transaction() as tx:
        tx.put("releases", release["id"], release)
    service = SimpleNamespace(store=store, org=organization())
    runner = ReleaseRunner(service, GitWorkspace(str(repo["root"]), str(tmp_path / "workspaces")),
                           FileArtifacts(str(tmp_path / "artifacts")), str(tmp_path / "unused-auth"),
                           verification_root=str(tmp_path / "verification"))
    calls = []

    def check(argv, cwd=None, **kwargs):  # labelled: install passes, the incumbent suite "fails"
        calls.append({"argv": [str(a) for a in argv], "cwd": str(cwd)})
        return {"passed": len(calls) == 1, "evidence": "fixture:check-" + str(len(calls))}

    monkeypatch.setattr(runner, "_check", check)
    return runner, calls


def reviewed_record(repo, *, pin=None):
    candidate = {"revision": repo["revision"], "base": repo["base"], "tree": repo["tree"],
                 "author": "worker:implementation"}
    policy = {"checks": ["tests", "cli_start", "cli_file_task"], "revision": repo["base"]}
    record = {"id": "a" * 64, "candidate": candidate, "policy": policy, "status": "reviewed",
              "reviews": [], "checks": {}}
    if pin is not None:
        record["policy"] = {**policy, "revision": pin["evaluator_revision"]}
        record["evaluator_migration"] = {"source_release_id": "b" * 64, "base": repo["base"],
                                         "evidence": "sha256:" + "c" * 64, "approved_by": "conductor",
                                         **pin}
    record["policy_hash"] = digest(record["policy"])
    return record


def test_ordinary_release_still_tests_the_candidate_base(tmp_path, monkeypatch, fake_verification_services):
    repo = source_repository(tmp_path / "repo")
    release = reviewed_record(repo)
    runner, calls = runner_for(tmp_path, repo, release, monkeypatch)
    answer = runner.evaluate(release["id"])
    incumbent = answer["receipt"]["workspaces"]["incumbent"]
    assert incumbent == {"path": incumbent["path"], "revision": repo["base"]}
    assert git(Path(incumbent["path"]), "rev-parse", "HEAD") == repo["base"]
    assert calls[1]["argv"][3] == str(Path(incumbent["path"]) / "tests")
    assert answer["verdict"] == "checked" and answer["passed"] is False


def test_migrated_release_runs_the_pinned_evaluator_tests(tmp_path, monkeypatch, fake_verification_services):
    repo = source_repository(tmp_path / "repo")
    pin = evaluator_commit(repo)
    assert pin["paths"] == ["tests/test_fixture.py"]
    release = reviewed_record(repo, pin=pin)
    runner, calls = runner_for(tmp_path, repo, release, monkeypatch)
    answer = runner.evaluate(release["id"])
    incumbent = answer["receipt"]["workspaces"]["incumbent"]
    assert incumbent["revision"] == pin["evaluator_revision"] and incumbent["base"] == repo["base"]
    assert Path(incumbent["path"]).name == "review-evaluator-" + release["id"][:16]
    assert git(Path(incumbent["path"]), "rev-parse", "HEAD") == pin["evaluator_revision"]
    assert calls[1]["argv"][3] == str(Path(incumbent["path"]) / "tests")
    candidate = answer["receipt"]["workspaces"]["candidate"]
    assert candidate["revision"] == repo["revision"] and calls[1]["cwd"] == candidate["path"]


@pytest.mark.parametrize("tamper", ["tree", "patch", "paths", "revision", "record", "candidate", "code",
                                    "grandchild"])
def test_a_tampered_or_code_touching_pin_is_a_named_refusal(tmp_path, monkeypatch, fake_verification_services,
                                                          tamper):
    repo = source_repository(tmp_path / "repo")
    pin = evaluator_commit(repo, extra=tamper == "code", grandchild=tamper == "grandchild")
    release = reviewed_record(repo, pin=pin)
    migration = release["evaluator_migration"]
    if tamper == "tree":
        migration["evaluator_tree"] = "0" * 40
    elif tamper == "patch":
        migration["patch_sha256"] = "0" * 64
    elif tamper == "paths":
        migration["paths"] = ["tests/other.py"]
    elif tamper == "revision":
        migration["evaluator_revision"] = repo["revision"]
    elif tamper == "record":
        del release["evaluator_migration"]
    elif tamper == "candidate":
        release["policy"]["revision"] = migration["evaluator_revision"] = repo["revision"]
    runner, calls = runner_for(tmp_path, repo, release, monkeypatch)
    with pytest.raises(EvaluatorPinMismatch) as refused:
        runner.evaluate(release["id"])
    assert isinstance(refused.value, ContractError)
    assert refused.value.reason_code == "evaluator_pin_mismatch"
    assert calls == [] and not (tmp_path / "workspaces" / ("review-evaluator-" + release["id"][:16])).exists()


def test_an_approved_migration_is_evaluated_end_to_end_up_to_the_suite(tmp_path, monkeypatch,
                                                                       fake_verification_services):
    """The application record and the runner agree on one pin (labelled fixture repository)."""
    repo = source_repository(tmp_path / "repo")
    pin = evaluator_commit(repo)
    store = MemoryStore()
    releases = Releases(store, organization())
    candidate = {"revision": repo["revision"], "base": repo["base"], "tree": repo["tree"],
                 "author": "worker:implementation"}
    source = releases.propose(candidate, {"checks": ["tests", "cli_start", "cli_file_task"],
                                          "revision": repo["base"]})
    for actor in ("lead:improvement", "conductor"):
        releases.review(source["id"], actor, repo["revision"], True, "fixture:review")
    source = releases.verify(source["id"], repo["revision"], source["policy_hash"], {
        "tests": {"passed": False, "evidence": "fixture:incumbent-assumes-checkout"},
        "cli_start": {"passed": False, "skipped": True, "evidence": "fixture:not-run"},
        "cli_file_task": {"passed": False, "skipped": True, "evidence": "fixture:not-run"}})
    workspace = GitWorkspace(str(repo["root"]), str(tmp_path / "resolver"))
    child = releases.request_evaluator_migration(
        source["id"], "conductor", expected_revision=repo["revision"],
        expected_policy_hash=source["policy_hash"],
        approval={"source_release_id": source["id"], "base": repo["base"],
                  "evidence": "sha256:" + "c" * 64, "approved_by": "conductor", **pin},
        resolved_pin=resolve_evaluator_pin(workspace, pin["evaluator_revision"], repo["base"]))
    runner, calls = runner_for(tmp_path, repo, child, monkeypatch)
    answer = runner.evaluate(child["id"])
    assert answer["receipt"]["workspaces"]["incumbent"]["revision"] == pin["evaluator_revision"]
    assert answer["verdict"] == "checked" and answer["passed"] is False and len(calls) == 2


# ---- one successor policy for a source (F1) and the creation-time pin (F2) ------------------------

def test_a_migration_successor_blocks_plain_reverification_and_stays_unchanged():
    store = MemoryStore()
    releases, source = rejected_release(store)
    child = migrate(releases, source)
    before = snapshot(store)
    with pytest.raises(ContractError, match="Release already has an evaluator migration successor"):
        reverify(releases, source)
    assert snapshot(store) == before and migrate(releases, source) == child


def failed_migrated_successor(store):
    releases, source = rejected_release(store)
    child = migrate(releases, source)
    failed = releases.verify(child["id"], "candidate", child["policy_hash"], {
        "tests": {"passed": False, "evidence": "fixture:evaluator-tests-failed"},
        **{name: {"passed": False, "skipped": True, "evidence": "fixture:not-run"}
           for name in ("cli_start", "cli_file_task")}})
    assert failed["status"] == "rejected"
    return releases, failed


def test_an_honestly_failed_migrated_successor_is_not_reverified_or_migrated_again():
    store = MemoryStore()
    releases, failed = failed_migrated_successor(store)
    before = snapshot(store)
    with pytest.raises(UnsupportedEvaluatorReverification) as refused:
        reverify(releases, failed)
    assert refused.value.reason_code == "unsupported_evaluator_reverification"
    assert "unsupported_evaluator_reverification" in str(refused.value)
    assert isinstance(refused.value, ContractError)
    with pytest.raises(UnsupportedEvaluatorReverification):
        migrate(releases, failed, approval=approval_for(failed, base=failed["candidate"]["base"],
                                                        evaluator_revision="d" * 40))
    assert snapshot(store) == before


def test_a_non_base_policy_without_a_receipt_is_also_refused():
    store = MemoryStore()
    releases, failed = failed_migrated_successor(store)
    with store.transaction() as tx:
        legacy = {**tx.get("releases", failed["id"])}
        del legacy["evaluator_migration"]
        tx.put("releases", failed["id"], legacy)
    before = snapshot(store)
    with pytest.raises(UnsupportedEvaluatorReverification):
        reverify(releases, legacy)
    assert snapshot(store) == before


@pytest.mark.parametrize("field", ["evaluator_revision", "parent", "base", "evaluator_tree", "paths",
                                   "patch_sha256", "missing", "extra"])
def test_a_resolved_pin_that_differs_from_the_approval_writes_nothing(field):
    store = MemoryStore()
    releases, source = rejected_release(store)
    resolved = expected_evaluator_pin(approval_for(source))
    if field == "missing":
        del resolved["patch_sha256"]
    elif field == "extra":
        resolved["files"] = []
    else:
        resolved[field] = ["tests/other.py"] if field == "paths" else "0" * 40
    before = snapshot(store)
    with pytest.raises(ContractError, match="Evaluator pin does not match the repository"):
        migrate(releases, source, resolved_pin=resolved)
    assert snapshot(store) == before
    assert migrate(releases, source)["status"] == "reviewed"


def test_the_resolved_pin_is_required():
    store = MemoryStore()
    releases, source = rejected_release(store)
    before = snapshot(store)
    with pytest.raises(TypeError):
        releases.request_evaluator_migration(source["id"], "conductor", expected_revision="candidate",
                                             expected_policy_hash=source["policy_hash"],
                                             approval=approval_for(source))
    assert snapshot(store) == before


@pytest.mark.parametrize("tamper", ["tree", "patch", "grandchild"])
def test_the_repository_resolver_exposes_a_wrong_or_ancestral_pin(tmp_path, tamper):
    """Labelled fixture repository: the real `resolve_evaluator_pin` over git, compared at creation."""
    repo = source_repository(tmp_path / "repo")
    pin = evaluator_commit(repo, grandchild=tamper == "grandchild")
    resolved = resolve_evaluator_pin(GitWorkspace(str(repo["root"]), str(tmp_path / "probe")),
                                     pin["evaluator_revision"], repo["base"])
    approval = {"source_release_id": "s" * 64, "base": repo["base"], "evidence": "sha256:" + "c" * 64,
                "approved_by": "conductor", **pin}
    if tamper == "tree":
        approval["evaluator_tree"] = "0" * 40
    elif tamper == "patch":
        approval["patch_sha256"] = "0" * 64
    assert resolved != expected_evaluator_pin(approval)
    if tamper == "grandchild":
        assert resolved["parent"] != resolved["base"] == repo["base"]
    approval = {**approval, **pin}
    assert (resolved == expected_evaluator_pin(approval)) is (tamper != "grandchild")


def race(store, source, first):
    results, gate = {}, threading.Barrier(2)

    def run(name):
        gate.wait()
        try:
            releases = Releases(store, organization())
            results[name] = reverify(releases, source) if name == "reverify" else migrate(releases, source)
        except ContractError as exc:
            results[name] = str(exc)

    order = ["reverify", "migrate"] if first == "reverify" else ["migrate", "reverify"]
    threads = [threading.Thread(target=run, args=(name,)) for name in order]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    return results


@pytest.mark.integration
@pytest.mark.parametrize("first", ["reverify", "migrate"])
def test_concurrent_reverification_and_migration_create_exactly_one_successor(isolated_pgstore, first):
    releases, source = rejected_release(isolated_pgstore)
    results = race(isolated_pgstore, source, first)
    with isolated_pgstore.transaction() as tx:
        children = [r for r in tx.scan("releases") if r.get("reverify_of") == source["id"]]
    assert len(children) == 1 and len(results) == 2
    winners = [name for name, value in results.items() if isinstance(value, dict)]
    assert len(winners) == 1 and results[winners[0]] == children[0]
    loser = ({"reverify", "migrate"} - set(winners)).pop()
    assert results[loser] == ("Release already has an evaluator migration successor" if loser == "reverify"
                              else "Release already has a reverification successor")


@pytest.mark.parametrize("first", ["reverify", "migrate"])
def test_memory_reverification_and_migration_in_either_order_create_one_successor(first):
    store = MemoryStore()
    releases, source = rejected_release(store)
    results = race(store, source, first)
    with store.transaction() as tx:
        children = [r for r in tx.scan("releases") if r.get("reverify_of") == source["id"]]
    assert len(children) == 1 and sum(isinstance(v, dict) for v in results.values()) == 1
