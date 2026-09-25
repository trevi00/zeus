"""`zeus fleet backlog` adapter and CLI glue (INV-FLEET-BACKLOG-001).

Git is real: the plan, the operation manifests and the goal document are committed into a
disposable repository and read at explicit commits. The store is an in-memory Harness and no
provider, bus, budget, observer, Redis or PostgreSQL client exists in this environment, so a
successful command is itself the evidence that none is built. No model runs.
"""
import hashlib
import json
import logging
import signal
import subprocess
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from codex_harness import bootstrap, cli
from codex_harness.adapters import fleet_cli, fleet_runtime
from codex_harness.adapters.fleet_backlog import (
    PLAN_SETTING,
    REGULAR_BLOB,
    backlog_ticker,
    configured_plan,
    load_manifest,
    load_plan,
    register_plan,
    tick_plan,
)
from codex_harness.adapters.observation_spool import MemorySpool
from codex_harness.adapters.operation_cli import GitSource
from codex_harness.adapters.providers import packaged_policy
from codex_harness.adapters.store import MemoryStore
from codex_harness.application.fleet import Fleet, FleetRunner
from codex_harness.application.fleet_backlog import BUCKET_INTENTS, FleetBacklog
from codex_harness.application.observations import MemoryDirectory, Observer
from codex_harness.application.portfolio import BUCKET_BINDINGS
from codex_harness.domain.fleet import repository_identity
from codex_harness.domain.fleet_backlog import PLAN_SCHEMA, BacklogRefused
from codex_harness.domain.observation import new_process_run_id
from codex_harness.domain.operation import validate_manifest

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


# Newline normalization is pinned in each disposable repository's OWN config. `git init` otherwise
# inherits the host's `core.autocrlf`, which is `true` by default on Windows and rewrites committed
# blobs, so a digest taken from the working tree names bytes no commit contains. `core.safecrlf` is
# pinned too so an inherited `true` cannot fail `git add` here. Nothing global or system-wide is
# read or written by these tests.
NORMALIZATION = {"core.autocrlf": "false", "core.eol": "lf", "core.safecrlf": "false"}


def init_repository(root, **settings) -> None:
    """An empty disposable repository with its newline normalization declared repo-locally."""
    Path(root).mkdir(parents=True, exist_ok=True)
    git(root, "init", "-q", "-b", "main")
    for key, value in {**NORMALIZATION, **settings}.items():
        git(root, "config", "--local", key, value)


def canonical(document) -> bytes:
    """The exact bytes a fixture commits: the document's own UTF-8, with no platform translation.

    `Path.write_text` translates `\\n` to the host separator, so on Windows the working tree held
    CRLF while the committed blob held LF, and a pin hashed from the file named bytes no commit
    contained. These bytes are built once and are both written and hashed, so the pin IS the
    committed bytes; the fixture documents above are LF, which a regression below asserts.
    """
    body = document if isinstance(document, str) else json.dumps(document, indent=2, sort_keys=True)
    return body.encode("utf-8")


def write(root, path, document) -> str:
    """Write the canonical bytes and return their digest - never a digest of re-read file bytes."""
    target = Path(root) / path
    target.parent.mkdir(parents=True, exist_ok=True)
    data = canonical(document)
    target.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


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
    init_repository(root)
    goal_sha = write(root, GOAL_PATH, GOAL_TEXT)
    base = commit(root, "goal")
    first = "docs/zeus/manifests/one.json"
    second = "docs/zeus/manifests/two.json"
    digests = {first: write(root, first, manifest_document("op-one", base, goal_sha, ["docs/one.md"])),
               second: write(root, second, manifest_document("op-two", base, goal_sha, ["docs/two.md"]))}
    manifests = commit(root, "manifests")
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


def test_the_fixture_pins_the_committed_bytes_under_inherited_git_newline_normalization(
        tmp_path, repository, monkeypatch):
    """Portability of THIS test file, not a runtime change (owner Windows gate, 2026-09-22).

    The owner's Windows run failed six CLI cases: `write_text` emitted CRLF, the inherited
    `core.autocrlf=true` normalized the committed blob back to LF, and the pin hashed from the
    working tree named bytes no commit held. The loader was right to refuse. Here `core.autocrlf`
    is set to `true` REPO-LOCALLY to reproduce that inherited Windows default - the fixture writes
    canonical LF bytes, so working tree, blob and pin agree on every platform - and the exact-byte
    runtime check still refuses a pin taken from CRLF bytes.
    """
    assert b"\r" not in canonical(manifest_document("op-x", "0" * 40, "a" * 64, ["docs/x.md"]))
    assert b"\r" not in canonical(GOAL_TEXT), "fixture documents are written with LF only"
    # The standard fixture declares its normalization in its own config file, never globally.
    local = (Path(repository.root) / ".git" / "config").read_text(encoding="utf-8")
    assert "autocrlf = false" in local and "eol = lf" in local

    root = tmp_path / "repo-crlf"
    init_repository(root, **{"core.autocrlf": "true", "core.eol": "crlf"})
    goal_sha = write(root, GOAL_PATH, GOAL_TEXT)
    base = commit(root, "goal")
    path = "docs/zeus/manifests/one.json"
    manifest_sha = write(root, path, manifest_document("op-one", base, goal_sha, ["docs/one.md"]))
    revision = commit(root, "manifest")

    source = GitSource(root)
    mode, blob = source.blob(revision, path)
    assert mode == REGULAR_BLOB and b"\r\n" not in blob and blob.count(b"\n") > 0
    assert hashlib.sha256(blob).hexdigest() == manifest_sha, "the pin is the committed bytes"
    assert (Path(root) / path).read_bytes() == blob, "working tree and commit hold the same bytes"
    assert hashlib.sha256(source.blob(base, GOAL_PATH)[1]).hexdigest() == goal_sha

    bound = load_manifest(source, item_document("one", path, revision, manifest_sha))
    assert bound["manifest"]["id"] == "op-one" and bound["goal"]["sha256"] == goal_sha

    # The control that makes this regression discriminating: the OLD fixture behaviour in the same
    # repository. LABELLED EMULATION - `newline="\r\n"` stands in for the platform translation
    # `write_text` performs on Windows, so the observed failure is reproduced on any host.
    stale = "docs/zeus/manifests/platform.json"
    body = json.dumps(manifest_document("op-two", base, goal_sha, ["docs/two.md"]),
                      indent=2, sort_keys=True)
    (Path(root) / stale).write_text(body, encoding="utf-8", newline="\r\n")
    working = hashlib.sha256((Path(root) / stale).read_bytes()).hexdigest()
    stale_revision = commit(root, "platform separator")
    committed = source.blob(stale_revision, stale)[1]
    assert (Path(root) / stale).read_bytes().count(b"\r\n") == committed.count(b"\n") > 0
    assert b"\r" not in committed, "core.autocrlf normalized the blob the working tree kept as CRLF"
    with pytest.raises(BacklogRefused, match="manifest_pin_mismatch"):
        # Byte-strictness is unchanged: a working-tree digest still names bytes no commit holds.
        load_manifest(source, item_document("two", stale, stale_revision, working))

    # A revert of `write` back to platform text mode is caught on Linux too: with `write_text`
    # emulating the Windows translation, the canonical writer is unaffected and its pin holds.
    text_mode = Path.write_text
    monkeypatch.setattr(Path, "write_text",
                        lambda self, data, **kw: text_mode(self, data, **{**kw, "newline": "\r\n"}))
    third = "docs/zeus/manifests/three.json"
    third_sha = write(root, third, manifest_document("op-three", base, goal_sha, ["docs/three.md"]))
    third_revision = commit(root, "third")
    assert hashlib.sha256(source.blob(third_revision, third)[1]).hexdigest() == third_sha
    assert load_manifest(source, item_document("three", third, third_revision, third_sha))["bytes"] > 0


def test_a_disposable_repository_overrides_an_inherited_global_autocrlf(tmp_path, monkeypatch):
    """The repository's own settings must beat the value the host would otherwise contribute.

    The inherited Windows default is simulated by pointing Git at a temporary `GIT_CONFIG_GLOBAL`
    file for this test only: the developer's real global configuration is neither read nor written,
    and no `git config --global` is ever executed.
    """
    inherited = tmp_path / "git-global-config"
    inherited.write_bytes(b"[core]\n\tautocrlf = true\n\teol = crlf\n\tsafecrlf = true\n")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(inherited))
    root = tmp_path / "repo-inherited"
    init_repository(root)
    seen = subprocess.run(["git", "-C", str(root), "config", "--global", "core.autocrlf"],
                          capture_output=True, text=True).stdout.strip()
    if seen != "true":
        pytest.skip("this Git ignores GIT_CONFIG_GLOBAL; an inherited value cannot be simulated")
    assert git(root, "config", "core.autocrlf") == "false", "the repository's own setting wins"

    goal_sha = write(root, GOAL_PATH, GOAL_TEXT)
    base = commit(root, "goal")
    path = "docs/zeus/manifests/one.json"
    sha = write(root, path, manifest_document("op-one", base, goal_sha, ["docs/one.md"]))
    revision = commit(root, "manifest")
    source = GitSource(root)
    assert hashlib.sha256(source.blob(revision, path)[1]).hexdigest() == sha
    assert hashlib.sha256(source.blob(base, GOAL_PATH)[1]).hexdigest() == goal_sha
    assert load_manifest(source, item_document("one", path, revision, sha))["manifest"]["id"] == "op-one"


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
    sha = write(root, "docs/zeus/manifests/bad.json",
                manifest_document("op-bad", repository.base, "b" * 64, ["docs/bad.md"]))
    revision = commit(root, "bad goal")
    with pytest.raises(BacklogRefused, match="goal_mismatch"):
        load_manifest(GitSource(root), item_document("bad", "docs/zeus/manifests/bad.json", revision, sha))
    sha = write(root, "docs/zeus/manifests/broken.json", "{ not json")
    revision = commit(root, "broken")
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


class FakeLauncher:
    """Fixture launcher: records what was asked to run, never spawns a process."""

    constructed = []

    def __init__(self, config=None, host=None):
        FakeLauncher.constructed.append(config)
        self.launched = []

    def budget_exhausted(self, budget):
        return False

    def launch(self, job):
        self.launched.append(job["id"])
        FakeLauncher.launched_ids.append(job["id"])
        return {"job_id": job["id"]}

    def wait(self, handles, seconds):
        return list(handles)

    def outcome(self, handle, job):
        return {"status": "accepted", "reason_code": "lead_accepted", "exit_code": 0,
                "calls": {"reserved": 2, "settled": 2}}


FakeLauncher.launched_ids = []


class OutageGit:
    """Labelled fixture: a git source whose reads fail, so the ADAPTER returns `unavailable`
    instead of raising out of the tick."""

    def __init__(self, repository):
        self.repository = repository

    def commit_exists(self, revision):
        raise OSError("injected git outage (fixture)")


def manual_job(service, repository, lane="b"):
    """One job an operator queued by hand, so backlog failures can be shown not to block it."""
    document = manifest_document("op-manual", repository.base, repository.goal_sha256, ["docs/manual.md"])
    goal = {"path": GOAL_PATH, "sha256": repository.goal_sha256, "criterion": "crit op-manual",
            "base_revision": repository.base, "bytes": len(GOAL_TEXT.encode("utf-8"))}
    return Fleet(service.store).enqueue(lane, validate_manifest(document, packaged_policy()), goal, [])


def test_a_tick_records_the_portfolio_binding_of_the_job_it_admitted(service, repository):
    """The existing `Portfolio.bind` owner writes the job-to-criterion binding, in its own
    transaction, for the exact project and criterion the approved item names. No acceptance and no
    criterion verdict is written by a tick."""
    register(service, repository)
    result = fleet_cli.execute(service, args("tick", plan="plan-1"))
    assert result["outcome"] == "enqueued" and result["linked"] is True
    row = service.store.data[BUCKET_BINDINGS, "op-one"]
    assert (row["project_id"], row["criterion_id"]) == ("research-improvement", "verified-loop")
    assert row["recorded_by"] == "owner"
    assert service.store.data[BUCKET_INTENTS, "plan-1:one"]["link_state"] == "linked"
    # A binding is not an acceptance: the portfolio records no criterion completion here.
    assert not [k for k in service.store.data if k[0] == "portfolio_acceptances"]


def test_the_real_ticker_returning_unavailable_is_a_failed_runner_tick_that_blocks_nothing(service, repository, caplog):
    """R4 over the REAL path: `backlog_ticker` -> `tick_plan` -> the adapter's git read. The tick
    RETURNS `unavailable`; the runner must report that as a failure with the reason and exception
    type, keep admitting unrelated work, log one transition and recover."""
    config_document = Fleet(service.store).registered()["config"]
    register(service, repository)
    manual_job(service, repository)
    fleet = Fleet(service.store)
    launcher, seen = FakeLauncher(), []
    outage = backlog_ticker(service.store, config_document, "plan-1", source_factory=OutageGit)

    def ticker():
        seen.append(outage())
        return seen[-1]

    runner = FleetRunner(fleet, launcher, sleep=lambda _: None, interval=0, backlog=ticker)
    with caplog.at_level(logging.INFO, logger="zeus.fleet.runner"):
        first = runner.run(once=True)
        # The adapter RETURNED the failure; unrelated queued work was admitted in the same cycle.
        assert seen[0]["outcome"] == "unavailable" and seen[0]["reason_code"] == "input_unavailable"
        assert seen[0]["error_type"] == "OSError" and seen[0]["job_id"] is None
        assert first["admitted"] == ["op-manual"] and launcher.launched == ["op-manual"]
        assert [j["id"] for j in fleet.status()["jobs"]] == ["op-manual"], "nothing was admitted blindly"
        # The bounded deferral is durable and the item is still recoverable.
        assert service.store.data[BUCKET_INTENTS, "plan-1:one"]["deferrals"] >= 1
        assert service.store.data[BUCKET_INTENTS, "plan-1:one"]["error_type"] == "OSError"
        still_failing = runner.run(once=True)
        assert still_failing["backlog"] == {"state": "unavailable", "outcome": "unavailable",
                                            "reason_code": "input_unavailable", "error_type": "OSError"}
        assert still_failing["admitted"] == []
        runner.backlog = backlog_ticker(service.store, config_document, "plan-1")
        # The bounded wait of the deferred item counts down over the next cycles and then admits
        # it exactly once; no cycle in between retries it and none writes a new log line.
        for _ in range(3):
            recovered = runner.run(once=True)
    assert recovered["backlog"]["state"] == "ok"
    assert sorted(j["id"] for j in fleet.status()["jobs"]) == ["op-manual", "op-one", "op-two"]
    messages = [r.getMessage() for r in caplog.records if r.name == "zeus.fleet.runner"]
    # A deferral tick is a healthy `blocked` answer, so entering and leaving unavailability is
    # logged each time it actually happens - never once per poll, and never with any raw text.
    assert messages == ["approved backlog unavailable; fleet admission continues",
                        "approved backlog recovered",
                        "approved backlog unavailable; fleet admission continues",
                        "approved backlog recovered"]
    assert "injected" not in "\n".join(messages) and "OSError" not in "\n".join(messages)


def test_the_configured_runner_continues_successors_and_emits_the_structured_transitions(
        tmp_path, service, repository, monkeypatch):
    """The shipped `zeus fleet run` entrypoint with the opt-in host setting, not a spy: one runner
    cycle selects, admits, dispatches and finalizes both approved items and then selects the second
    one itself, with no `tick` command in between. Only the launcher and the observer spool are
    fixtures; the observer is the real one the adapter wires."""
    from codex_harness.adapters import configuration

    register(service, repository)
    observer = Observer(service.store, MemorySpool(new_process_run_id()), component="fleet-backlog",
                        directory=MemoryDirectory())
    FakeLauncher.constructed, FakeLauncher.launched_ids = [], []
    monkeypatch.setattr(configuration, "settings", lambda: {PLAN_SETTING: "plan-1"})
    monkeypatch.setattr(fleet_runtime, "LaneLauncher", FakeLauncher)
    monkeypatch.setattr(bootstrap, "build_observer", lambda store, component, role=None: observer)
    before = handlers()
    summary = fleet_cli.execute(service, SimpleNamespace(fleet_command="run", once=True))
    assert handlers() == before, "the run hands the process its previous handlers back"
    assert summary["exit_code"] == 0 and summary["admitted"] == ["op-one", "op-two"]
    assert FakeLauncher.launched_ids == ["op-one", "op-two"]
    assert [entry["status"] for entry in summary["finalized"]] == ["accepted", "accepted"]
    assert summary["backlog"] == {"state": "ok", "outcome": "backlog_exhausted", "reason_code": None,
                                  "error_type": None}
    assert [config["id"] for config in FakeLauncher.constructed] == ["fleet-1"]
    kinds = [record["event_type"] for record in observer.spool.records()]
    assert kinds == ["development.backlog_item_admitted", "development.backlog_item_admitted"]
    attributes = [record["attributes"] for record in observer.spool.records()]
    assert [a["item_id"] for a in attributes] == ["one", "two"]
    assert all(a["linked"] is True and a["plan_id"] == "plan-1" for a in attributes)
    text = json.dumps(observer.spool.records())
    assert CANARY not in text and str(repository.root) not in text and "lane_a" not in text


def test_the_runner_without_the_host_setting_builds_no_backlog_and_no_observer(service, repository, monkeypatch):
    from codex_harness.adapters import configuration

    register(service, repository)
    FakeLauncher.constructed, FakeLauncher.launched_ids = [], []
    monkeypatch.setattr(configuration, "settings", lambda: {})
    monkeypatch.setattr(fleet_runtime, "LaneLauncher", FakeLauncher)
    monkeypatch.setattr(bootstrap, "build_observer",
                        lambda *a, **k: pytest.fail("no observer is built without the opt-in"))
    before = deepcopy(service.store.data)
    installed = handlers()
    summary = fleet_cli.execute(service, SimpleNamespace(fleet_command="run", once=True))
    assert handlers() == installed, "the run hands the process its previous handlers back"
    assert summary["backlog"] == {"state": "disabled", "outcome": None, "reason_code": None,
                                  "error_type": None}
    assert summary["admitted"] == [] and FakeLauncher.launched_ids == []
    assert service.store.data == before, "the default runtime selects nothing and writes nothing"


def owned_signals():
    return [getattr(signal, name) for name in ("SIGINT", "SIGTERM", "SIGBREAK") if hasattr(signal, name)]


def handlers():
    return {number: signal.getsignal(number) for number in owned_signals()}


def plain_run(service, repository, monkeypatch, launcher):
    """`zeus fleet run` without the opt-in settings: the real runner, lane launcher replaced."""
    from codex_harness.adapters import configuration

    register(service, repository)
    monkeypatch.setattr(configuration, "settings", lambda: {})
    monkeypatch.setattr(fleet_runtime, "LaneLauncher", launcher)
    return fleet_cli.execute(service, SimpleNamespace(fleet_command="run", once=False))


def test_an_actual_signal_while_running_stops_gracefully_and_the_handlers_are_restored(
        service, repository, monkeypatch):
    """Release CI cancellation: the run's handlers close over its runner, so a leaked handler
    swallowed a later interrupt in the same process. A real SIGINT delivered while the continuous
    runner scans goes through the installed handler to `stop`; afterwards the previous handlers,
    including a custom Python handler an earlier owner installed, are back."""
    received = []
    incoming = signal.signal(signal.SIGINT, lambda *_: received.append(True))
    try:
        before, during = handlers(), {}

        class SignallingLauncher(FakeLauncher):
            def budget_exhausted(self, budget):
                during.update(handlers())
                signal.raise_signal(signal.SIGINT)
                return False

        summary = plain_run(service, repository, monkeypatch, SignallingLauncher)
        assert all(during[number] is not before[number] for number in before), "installed while running"
        assert summary["exit_code"] == 0 and summary["stopped"] is True and summary["admitted"] == []
        assert handlers() == before and received == []
        signal.raise_signal(signal.SIGINT)
        assert received == [True], "a later interrupt reaches the incoming owner, not the stopped runner"
    finally:
        signal.signal(signal.SIGINT, incoming)  # this test's own custom handler, not the run's


def test_a_runner_exception_restores_the_handlers_and_keeps_the_original_error(
        service, repository, monkeypatch):
    before = handlers()

    class FailingLauncher(FakeLauncher):
        def budget_exhausted(self, budget):
            assert signal.getsignal(signal.SIGINT) is not before[signal.SIGINT]
            raise RuntimeError("runner failed")

    with pytest.raises(RuntimeError, match="runner failed"):
        plain_run(service, repository, monkeypatch, FailingLauncher)
    assert handlers() == before


def test_a_partial_handler_installation_restores_only_what_it_installed(service, repository, monkeypatch):
    """INJECTED FAULT: installing the second owned handler fails after the first was replaced."""
    numbers = owned_signals()
    if len(numbers) < 2:
        pytest.skip("this platform exposes fewer than two owned signals")
    before = handlers()
    real, calls = signal.signal, []

    def failing_install(number, handler):
        calls.append((number, handler))
        if number == numbers[1] and handler is not before[number]:
            raise OSError("injected handler installation failure")
        return real(number, handler)

    monkeypatch.setattr(signal, "signal", failing_install)

    class NeverRuns(FakeLauncher):
        def budget_exhausted(self, budget):
            raise AssertionError("the runner ran after a failed installation")

    with pytest.raises(OSError, match="injected"):
        plain_run(service, repository, monkeypatch, NeverRuns)
    # Installed first, failed second, then only the first is handed back; later signals untouched.
    assert [number for number, _ in calls] == [numbers[0], numbers[1], numbers[0]]
    assert calls[-1][1] is before[numbers[0]]
    assert handlers() == before


def test_a_refusal_prints_a_code_and_a_type_never_the_document_or_a_path(tmp_path):
    refusal = fleet_cli.refusal(BacklogRefused("manifest_pin_mismatch", "items[].manifest_sha256"))
    assert refusal == {"status": "refused", "reason_code": "manifest_pin_mismatch",
                       "error_type": "BacklogRefused", "exit_code": 1}
    assert CANARY not in json.dumps(refusal) and str(tmp_path) not in json.dumps(refusal)
