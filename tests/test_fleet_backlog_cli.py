"""`zeus fleet backlog` adapter and CLI glue (INV-FLEET-BACKLOG-001).

Git is real: the plan, the operation manifests and the goal document are committed into a
disposable repository and read at explicit commits. The store is an in-memory Harness and no
provider, bus, budget, observer, Redis or PostgreSQL client exists in this environment, so a
successful command is itself the evidence that none is built. No model runs.
"""
import hashlib
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from codex_harness import cli
from codex_harness.adapters import fleet_cli
from codex_harness.adapters.fleet_backlog import (
    PLAN_SETTING,
    configured_plan,
    load_manifest,
    load_plan,
    register_plan,
    tick_plan,
)
from codex_harness.adapters.operation_cli import GitSource
from codex_harness.adapters.store import MemoryStore
from codex_harness.application.fleet import Fleet
from codex_harness.application.fleet_backlog import BUCKET_INTENTS, FleetBacklog
from codex_harness.domain.fleet import repository_identity
from codex_harness.domain.fleet_backlog import PLAN_SCHEMA, BacklogRefused

CANARY = "CANARY-must-never-be-emitted"
PLAN_PATH = "docs/zeus/backlog.json"
GOAL_PATH = "docs/GOAL.md"
GOAL_TEXT = "# Goal\n\nDeliver the approved backlog item. " + CANARY + "\n"


def git(root, *argv) -> str:
    return subprocess.run(["git", "-C", str(root), *argv], check=True, capture_output=True,
                          text=True).stdout.strip()


def commit(root, message) -> str:
    git(root, "add", "--all")
    git(root, "-c", "user.name=t", "-c", "user.email=t@localhost", "commit", "-q", "-m", message)
    return git(root, "rev-parse", "HEAD")


def write(root, path, document) -> str:
    target = Path(root) / path
    target.parent.mkdir(parents=True, exist_ok=True)
    body = document if isinstance(document, str) else json.dumps(document, indent=2, sort_keys=True)
    target.write_text(body, encoding="utf-8")
    return hashlib.sha256(target.read_bytes()).hexdigest()


def manifest_document(op_id, base_revision, goal_sha256, paths):
    return {"schema": "urn:zeus:operation:1", "id": op_id, "base_revision": base_revision,
            "goal": {"path": GOAL_PATH, "sha256": goal_sha256, "criterion": "crit " + op_id,
                     "rationale": "approved by the owner " + CANARY},
            "plan": {"objective": "implement " + op_id + " " + CANARY,
                     "acceptance_criteria": ["the scoped checks pass"], "allowed_paths": paths},
            "budget": {"per_host": 4, "total": 8},
            "claude": {"model": "claude-fixture-model", "timeout_seconds": 3600, "max_budget_usd": 1.0}}


def plan_document(repository, items, plan_id="plan-1", enabled=True):
    return {"schema": PLAN_SCHEMA, "plan_id": plan_id, "repository": repository,
            "enabled": enabled, "items": items}


def item_document(item_id, path, revision, sha256, **overrides):
    return {"id": item_id, "project_id": "research-improvement", "criterion_id": "verified-loop",
            "lane": "a", "manifest_path": path, "manifest_revision": revision,
            "manifest_sha256": sha256, "priority": 10, "dependencies": [], **overrides}


@pytest.fixture
def repository(tmp_path):
    """A disposable repository holding the goal, two pinned manifests and the approved plan."""
    root = tmp_path / "repo-a"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    goal_sha = write(root, GOAL_PATH, GOAL_TEXT)
    base = commit(root, "goal")
    first = "docs/zeus/manifests/one.json"
    second = "docs/zeus/manifests/two.json"
    write(root, first, manifest_document("op-one", base, goal_sha, ["docs/one.md"]))
    write(root, second, manifest_document("op-two", base, goal_sha, ["docs/two.md"]))
    manifests = commit(root, "manifests")
    digests = {first: hashlib.sha256((root / first).read_bytes()).hexdigest(),
               second: hashlib.sha256((root / second).read_bytes()).hexdigest()}
    identity = repository_identity(str(root))
    items = [item_document("one", first, manifests, digests[first]),
             item_document("two", second, manifests, digests[second], priority=20, dependencies=["one"])]
    plan_sha = write(root, PLAN_PATH, plan_document(identity, items))
    revision = commit(root, "plan")
    return SimpleNamespace(root=root, base=base, goal_sha256=goal_sha, manifests=manifests,
                           digests=digests, identity=identity, items=items, revision=revision,
                           plan_sha256=plan_sha, paths=(first, second))


def config(tmp_path, repository_root, **overrides):
    lanes = [{"id": "a", "team": "alpha", "repository": str(repository_root), "schema": "lane_a",
              "redis_namespace": "fleet-a", "runtime": str(tmp_path / "rt-a")},
             {"id": "b", "team": "beta", "repository": str(tmp_path / "repo-b"), "schema": "lane_b",
              "redis_namespace": "fleet-b", "runtime": str(tmp_path / "rt-b")}]
    return {"schema": "urn:zeus:fleet:1", "id": "fleet-1", "max_parallel": 2,
            "budget": {"per_host": 4, "total": 8}, "lanes": lanes, **overrides}


@pytest.fixture
def service(tmp_path, repository):
    store = MemoryStore()
    Fleet(store).register(config(tmp_path, repository.root))
    return SimpleNamespace(store=store, org=SimpleNamespace(agents={}))


def args(command, **fields):
    return SimpleNamespace(fleet_command="backlog", backlog_command=command, **fields)


def register(service, repository, revision=None, path=PLAN_PATH, lane="a"):
    return fleet_cli.execute(service, args("register", lane=lane,
                                           revision=revision or repository.revision, path=path))


def test_the_plan_and_its_manifests_are_read_at_the_pin_and_never_from_the_working_tree(repository):
    source = GitSource(repository.root)
    loaded = load_plan(source, repository.revision, PLAN_PATH)
    assert loaded["plan"]["plan_id"] == "plan-1" and len(loaded["plan"]["items"]) == 2
    assert loaded["pin"] == {"revision": repository.revision, "path": PLAN_PATH,
                             "sha256": repository.plan_sha256} and loaded["bytes"] > 0
    write(repository.root, PLAN_PATH, plan_document(repository.identity, repository.items, plan_id="edited"))
    assert load_plan(source, repository.revision, PLAN_PATH)["plan"]["plan_id"] == "plan-1", "the pin wins"
    moved = commit(repository.root, "edit")
    assert load_plan(source, moved, PLAN_PATH)["plan"]["plan_id"] == "edited"
    bound = load_manifest(source, repository.items[0])
    assert bound["manifest"]["id"] == "op-one" and bound["manifest"]["base_revision"] == repository.base
    assert bound["goal"] == {"path": GOAL_PATH, "sha256": repository.goal_sha256,
                             "base_revision": repository.base, "criterion": "crit op-one",
                             "bytes": len(GOAL_TEXT.encode("utf-8"))}


def test_register_tick_and_status_admit_one_approved_successor_through_the_existing_fleet(service, repository):
    registered = register(service, repository)
    assert registered["registered"] is True and registered["cached"] is False and registered["exit_code"] == 0
    assert registered["plan_id"] == "plan-1" and registered["pin"]["revision"] == repository.revision
    assert register(service, repository)["cached"] is True

    first = fleet_cli.execute(service, args("tick", plan="plan-1"))
    assert first["outcome"] == "enqueued" and first["item_id"] == "one" and first["job_id"] == "op-one"
    assert first["exit_code"] == 0 and first["cached"] is False
    fleet = Fleet(service.store)
    [job] = fleet.status()["jobs"]
    assert job["id"] == "op-one" and job["status"] == "queued" and job["lane"] == "a"
    assert job["goal"]["criterion"] == "crit op-one"

    waiting = fleet_cli.execute(service, args("tick", plan="plan-1"))
    assert waiting["outcome"] == "blocked" and waiting["blocked"] == {"two": "dependency_waiting"}
    assert waiting["exit_code"] == 0, "a poll with nothing eligible is not a failure"

    claim = fleet.admit_one()["job"]
    fleet.finalize("op-one", claim["owner_token"], {"status": "accepted", "reason_code": "lead_accepted",
                                                    "exit_code": 0, "calls": {"reserved": 2, "settled": 2}})
    second = fleet_cli.execute(service, args("tick", plan="plan-1"))
    assert second["outcome"] == "enqueued" and second["job_id"] == "op-two"
    assert sorted(j["id"] for j in fleet.status()["jobs"]) == ["op-one", "op-two"]

    status = fleet_cli.execute(service, args("status", plan="plan-1"))
    [view] = status["plans"]
    assert status["exit_code"] == 0 and view["outcome"] == "backlog_exhausted"
    assert {i["item_id"]: i["job_status"] for i in view["items"]} == {"one": "accepted", "two": "queued"}
    assert {i["item_id"]: i["next_action"] for i in view["items"]} == {
        "one": "owner_release_decision", "two": "await_fleet"}
    text = json.dumps(status)
    assert CANARY not in text and str(repository.root) not in text and "lane_a" not in text


def test_a_manifest_that_moved_under_an_approved_item_is_refused_with_a_fixed_code(service, repository):
    source = GitSource(repository.root)
    moved = dict(repository.items[0], manifest_sha256="0" * 64)
    with pytest.raises(BacklogRefused, match="manifest_pin_mismatch"):
        load_manifest(source, moved)
    with pytest.raises(BacklogRefused, match="manifest_revision_missing"):
        load_manifest(source, dict(repository.items[0], manifest_revision="0" * 40))
    with pytest.raises(BacklogRefused, match="manifest_missing_at_revision"):
        load_manifest(source, dict(repository.items[0], manifest_path="docs/zeus/absent.json"))
    with pytest.raises(BacklogRefused, match="manifest_not_regular") as info:
        # Path grammar cannot decide a blob's type: a tree, symlink or submodule entry at the
        # pinned path is refused here, where the mode is actually observed.
        load_manifest(source, dict(repository.items[0], manifest_path="docs/zeus/manifests"))
    assert CANARY not in str(info.value)


def test_a_manifest_whose_goal_bytes_do_not_match_its_pin_is_refused(tmp_path, repository):
    root = repository.root
    write(root, "docs/zeus/manifests/bad.json",
          manifest_document("op-bad", repository.base, "b" * 64, ["docs/bad.md"]))
    revision = commit(root, "bad goal")
    sha = hashlib.sha256((root / "docs/zeus/manifests/bad.json").read_bytes()).hexdigest()
    with pytest.raises(BacklogRefused, match="goal_mismatch"):
        load_manifest(GitSource(root), item_document("bad", "docs/zeus/manifests/bad.json", revision, sha))
    write(root, "docs/zeus/manifests/broken.json", "{ not json")
    revision = commit(root, "broken")
    sha = hashlib.sha256((root / "docs/zeus/manifests/broken.json").read_bytes()).hexdigest()
    with pytest.raises(BacklogRefused, match="manifest_not_json"):
        load_manifest(GitSource(root), item_document("broken", "docs/zeus/manifests/broken.json", revision, sha))


def test_a_foreign_repository_an_unknown_lane_and_an_unknown_goal_are_refused(tmp_path, service, repository):
    config_document = Fleet(service.store).registered()["config"]
    foreign = plan_document("7" * 64, repository.items, plan_id="plan-foreign")
    write(repository.root, "docs/zeus/foreign.json", foreign)
    revision = commit(repository.root, "foreign")
    with pytest.raises(BacklogRefused, match="repository_foreign"):
        register_plan(service.store, config_document, "a", revision, "docs/zeus/foreign.json")

    elsewhere = plan_document(repository.identity,
                              [dict(repository.items[0], lane="b")], plan_id="plan-lane")
    write(repository.root, "docs/zeus/lane.json", elsewhere)
    revision = commit(repository.root, "lane")
    with pytest.raises(BacklogRefused, match="repository_foreign"):
        # Lane b exists but belongs to another repository: an approved plan never crosses it.
        register_plan(service.store, config_document, "a", revision, "docs/zeus/lane.json")

    unknown_lane = plan_document(repository.identity,
                                 [dict(repository.items[0], lane="zzz")], plan_id="plan-unknown-lane")
    write(repository.root, "docs/zeus/unknown-lane.json", unknown_lane)
    revision = commit(repository.root, "unknown lane")
    with pytest.raises(BacklogRefused, match="lane_unknown"):
        register_plan(service.store, config_document, "a", revision, "docs/zeus/unknown-lane.json")

    unknown_goal = plan_document(repository.identity,
                                 [dict(repository.items[0], criterion_id="not-a-criterion")],
                                 plan_id="plan-goal")
    write(repository.root, "docs/zeus/goal.json", unknown_goal)
    revision = commit(repository.root, "unknown goal")
    with pytest.raises(BacklogRefused, match="goal_unknown"):
        register_plan(service.store, config_document, "a", revision, "docs/zeus/goal.json")
    assert FleetBacklog(service.store).status()["plans"] == [], "a refused registration stores nothing"


def test_a_missing_plan_revision_or_path_is_a_fixed_code_never_an_empty_success(service, repository):
    config_document = Fleet(service.store).registered()["config"]
    for revision, path, code in (("0" * 40, PLAN_PATH, "plan_revision_missing"),
                                 (repository.revision, "docs/zeus/absent.json", "plan_missing_at_revision"),
                                 (repository.revision, "docs/zeus", "plan_not_regular")):
        with pytest.raises(BacklogRefused, match=code):
            register_plan(service.store, config_document, "a", revision, path)
    assert FleetBacklog(service.store).status()["plans"] == []
    missing = fleet_cli.execute(service, args("tick", plan="plan-1"))
    assert missing["outcome"] == "plan_unregistered" and missing["exit_code"] == 1
    unknown = fleet_cli.execute(service, args("status", plan="plan-1"))
    assert unknown["registered"] is False and unknown["exit_code"] == 1
    # Listing every plan is a successful read even when nothing is registered yet.
    listing = fleet_cli.execute(service, args("status", plan=None))
    assert listing["plans"] == [] and listing["registered"] is False and listing["exit_code"] == 0


def test_a_definition_that_changed_after_registration_refuses_the_item_at_tick(service, repository):
    """The portfolio stays the authority over goals: a criterion that no longer exists refuses the
    item with a reason instead of admitting stale work."""
    config_document = Fleet(service.store).registered()["config"]
    register_plan(service.store, config_document, "a", repository.revision, PLAN_PATH)
    narrowed = {"schema": "urn:zeus:portfolio-definitions:1",
                "projects": [{"id": "research-improvement", "title": "t", "outcome": "o",
                              "source_ref": "docs/x.md", "criteria": [{"id": "other", "text": "t"}]}]}
    result = tick_plan(service.store, config_document, "plan-1", definitions=narrowed)
    assert result["outcome"] == "refused" and result["reason_code"] == "goal_unknown"
    assert Fleet(service.store).status()["jobs"] == []
    assert service.store.data[BUCKET_INTENTS, "plan-1:one"]["attempts"] == 1


def test_the_runner_opt_in_is_absent_by_default(tmp_path):
    assert configured_plan({}) is None and configured_plan({PLAN_SETTING: "   "}) is None
    assert configured_plan({PLAN_SETTING: " plan-1 "}) == "plan-1"
    assert configured_plan(None) is None


def test_the_cli_parser_exposes_backlog_register_tick_and_status():
    parsed = cli.parser().parse_args(["fleet", "backlog", "register", "--lane", "a",
                                      "--revision", "c" * 40, "--path", PLAN_PATH])
    assert parsed.command == "fleet" and parsed.fleet_command == "backlog"
    assert parsed.backlog_command == "register"
    assert parsed.lane == "a" and parsed.revision == "c" * 40 and parsed.path == PLAN_PATH
    tick = cli.parser().parse_args(["fleet", "backlog", "tick", "--plan", "plan-1"])
    assert tick.backlog_command == "tick" and tick.plan == "plan-1"
    assert cli.parser().parse_args(["fleet", "backlog", "status"]).plan is None
    for argv in (["fleet", "backlog"], ["fleet", "backlog", "tick"],
                 ["fleet", "backlog", "register", "--lane", "a"]):
        with pytest.raises(SystemExit):
            cli.parser().parse_args(argv)


def test_a_refusal_prints_a_code_and_a_type_never_the_document_or_a_path(tmp_path):
    refusal = fleet_cli.refusal(BacklogRefused("manifest_pin_mismatch", "items[].manifest_sha256"))
    assert refusal == {"status": "refused", "reason_code": "manifest_pin_mismatch",
                       "error_type": "BacklogRefused", "exit_code": 1}
    assert CANARY not in json.dumps(refusal) and str(tmp_path) not in json.dumps(refusal)
