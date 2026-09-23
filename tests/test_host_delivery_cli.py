"""`zeus host-delivery` adapter and CLI glue (INV-HOST-DELIVERY-001).

Git is real: the owner-approved plan is committed into a disposable repository and read at an
explicit commit. The GitHub client is a labelled in-test runner - no `gh` binary, no network, no
pull request and no merge exists here - and the scheduled-task client is never invoked at all. The
service entry is exercised as an actual disposable child process of this test. The store is an
in-memory Harness and no provider, bus, budget, Redis or PostgreSQL client is built, so a
successful command is itself the evidence that none was needed. No model runs.
"""
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from codex_harness import cli
from codex_harness.adapters import host_delivery
from codex_harness.adapters.host_delivery import (
    DESCRIPTOR_FILE,
    ENABLED_SETTING,
    MAX_PLAN_BYTES,
    RECEIPT_FILE,
    GitHubDelivery,
    configured_enabled,
    execute,
    load_plan,
    normalize_checks,
    refusal,
    run_loop,
)
from codex_harness.adapters.operation_cli import GitSource
from codex_harness.adapters.store import MemoryStore
from codex_harness.application.host_delivery import BUCKET_PLANS, BUCKET_TARGETS
from codex_harness.bootstrap import organization
from codex_harness.domain.host_delivery import (
    CANARY_STARTUP,
    PLAN_SCHEMA,
    REGISTRY_SCHEMA,
    DeliveryRefused,
    descriptor_digest,
)
from codex_harness.domain.model import ContractError

CANARY_TEXT = "CANARY-must-never-be-emitted"
REVISION = "a" * 40
TREE = "c" * 64
POLICY_HASH = "1" * 64
IMAGE = "zeus-worker@sha256:" + "d" * 64
PROFILE = "e" * 64
CHECK = "ci / required"
PLAN_PATH = "docs/zeus/operations/delivery.json"

# Newline normalization is pinned in each disposable repository's OWN config: `git init` otherwise
# inherits the host's `core.autocrlf`, which rewrites committed blobs, so a digest taken from the
# working tree would name bytes no commit contains. Nothing global is read or written here.
NORMALIZATION = {"core.autocrlf": "false", "core.eol": "lf", "core.safecrlf": "false"}


def git(root, *argv) -> str:
    return subprocess.run(["git", "-C", str(root), *argv], check=True, capture_output=True,
                          text=True).stdout.strip()


def init_repository(root) -> None:
    Path(root).mkdir(parents=True, exist_ok=True)
    git(root, "init", "-q", "-b", "main")
    for key, value in NORMALIZATION.items():
        git(root, "config", "--local", key, value)


def commit(root, message="fixture") -> str:
    git(root, "add", "--all")
    git(root, "-c", "user.name=t", "-c", "user.email=t@localhost", "commit", "-q", "-m", message)
    return git(root, "rev-parse", "HEAD")


def write_bytes(root, path, data: bytes) -> None:
    target = Path(root) / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)


def plan_document(**overrides) -> dict:
    return {"schema": PLAN_SCHEMA, "plan_id": "delivery-plan-1", "release_id": "release-1",
            "revision": REVISION, "tree": TREE, "policy_hash": POLICY_HASH,
            "repository": "github:zeus-owner/zeus-harness", "required_checks": [CHECK],
            "target_id": "canary-service", "expected_descriptor": None,
            "target_descriptor": {"revision": REVISION, "worker_image": IMAGE,
                                  "profile_digest": PROFILE},
            "canary_check_id": CANARY_STARTUP, "ci_timeout_seconds": 300,
            "consumption_timeout_seconds": 120, **overrides}


def targets_document(tmp_path) -> dict:
    return {"schema": REGISTRY_SCHEMA,
            "targets": [{"target_id": "canary-service", "kind": "process",
                         "root": str(tmp_path / "root"), "state_dir": str(tmp_path / "state"),
                         "service": "zeus-canary-service"}]}


def service_for():
    return SimpleNamespace(store=MemoryStore(), org=organization())


def args(command, **fields):
    return SimpleNamespace(delivery_command=command, **fields)


def completed(stdout="", returncode=0, stderr=""):
    return subprocess.CompletedProcess(["gh"], returncode, stdout, stderr)


# ----- the plan is read from a commit --------------------------------------------------------
def test_the_plan_is_read_from_the_commit_and_pinned_to_its_exact_bytes(tmp_path):
    root = tmp_path / "repo"
    init_repository(root)
    body = json.dumps(plan_document(), sort_keys=True).encode("utf-8")
    write_bytes(root, PLAN_PATH, body)
    revision = commit(root)
    loaded = load_plan(GitSource(str(root)), revision, PLAN_PATH)
    assert loaded["pin"] == {"revision": revision, "path": PLAN_PATH,
                             "sha256": hashlib.sha256(body).hexdigest()}
    assert loaded["plan"]["plan_id"] == "delivery-plan-1" and loaded["bytes"] == len(body)
    # An edited working tree changes nothing: only a commit named in the pin can change a plan.
    write_bytes(root, PLAN_PATH, json.dumps(plan_document(plan_id="edited")).encode("utf-8"))
    assert load_plan(GitSource(str(root)), revision, PLAN_PATH)["plan"]["plan_id"] == "delivery-plan-1"


@pytest.mark.parametrize("body,reason", [
    (b"{not json", "plan_not_json"),
    (json.dumps({"schema": PLAN_SCHEMA}).encode(), "plan_fields"),
    (json.dumps(plan_document(canary_check_id="curl evil")).encode(), "plan_invalid"),
    (b"x" * (MAX_PLAN_BYTES + 1), "plan_too_large")])
def test_a_malformed_or_oversized_plan_is_refused_by_code_without_its_bytes(tmp_path, body, reason):
    root = tmp_path / "repo"
    init_repository(root)
    write_bytes(root, PLAN_PATH, body)
    revision = commit(root)
    with pytest.raises(DeliveryRefused) as refused:
        load_plan(GitSource(str(root)), revision, PLAN_PATH)
    assert refused.value.reason_code == reason
    assert CANARY_TEXT not in str(refused.value) and "curl" not in str(refused.value)


def test_a_missing_path_or_revision_is_a_code_not_a_traceback(tmp_path):
    root = tmp_path / "repo"
    init_repository(root)
    write_bytes(root, "README.md", b"fixture\n")
    revision = commit(root)
    with pytest.raises(DeliveryRefused) as missing:
        load_plan(GitSource(str(root)), revision, PLAN_PATH)
    assert missing.value.reason_code == "plan_missing_at_revision"
    with pytest.raises(DeliveryRefused) as unknown:
        load_plan(GitSource(str(root)), "b" * 40, PLAN_PATH)
    assert unknown.value.reason_code == "plan_revision_missing"


# ----- the parser ------------------------------------------------------------------------------
def test_the_parser_exposes_the_owner_commands_and_nothing_executable(tmp_path):
    parsed = cli.parser().parse_args(["host-delivery", "register", "--revision", "a" * 40,
                                      "--path", PLAN_PATH])
    assert parsed.command == "host-delivery" and parsed.delivery_command == "register"
    assert parsed.revision == "a" * 40 and parsed.path == PLAN_PATH
    assert cli.parser().parse_args(["host-delivery", "status"]).plan is None
    assert cli.parser().parse_args(["host-delivery", "tick"]).plan is None
    run = cli.parser().parse_args(["host-delivery", "run", "--once"])
    assert run.once is True and run.interval == 15 and run.max_ticks == 0
    for argv in (["host-delivery"], ["host-delivery", "register"],
                 ["host-delivery", "register-targets"], ["host-delivery", "exec", "--argv", "sh"]):
        with pytest.raises(SystemExit):
            cli.parser().parse_args(argv)


# ----- the owner commands ------------------------------------------------------------------------
def test_register_targets_then_register_a_plan_and_read_the_projection(tmp_path, monkeypatch):
    service = service_for()
    registry = tmp_path / "targets.json"
    registry.write_text(json.dumps(targets_document(tmp_path)), encoding="utf-8")
    receipt = execute(service, args("register-targets", file=registry))
    assert receipt["exit_code"] == 0 and receipt["targets"] == ["canary-service"]
    with service.store.transaction() as tx:
        assert tx.get(BUCKET_TARGETS, "canary-service")["kind"] == "process"
    root = tmp_path / "repo"
    init_repository(root)
    write_bytes(root, PLAN_PATH, json.dumps(plan_document()).encode("utf-8"))
    revision = commit(root)
    monkeypatch.setattr(host_delivery, "_git", lambda _service: SimpleNamespace(repository=root))
    registered = execute(service, args("register", revision=revision, path=PLAN_PATH))
    assert registered["exit_code"] == 0 and registered["cached"] is False
    with service.store.transaction() as tx:
        assert tx.get(BUCKET_PLANS, "delivery-plan-1")["pin"]["revision"] == revision
    monkeypatch.setenv(ENABLED_SETTING, "0")
    projection = execute(service, args("status", plan="delivery-plan-1"))
    assert projection["exit_code"] == 0 and projection["enabled"] is False
    assert projection["deliveries"][0]["stage"] == "registered"
    missing = execute(service, args("status", plan="no-such-plan"))
    assert missing["exit_code"] == 1 and missing["registered"] is False


def test_a_plan_naming_an_unregistered_target_is_refused_before_anything_is_stored(tmp_path, monkeypatch):
    service = service_for()
    root = tmp_path / "repo"
    init_repository(root)
    write_bytes(root, PLAN_PATH, json.dumps(plan_document(target_id="other")).encode("utf-8"))
    revision = commit(root)
    monkeypatch.setattr(host_delivery, "_git", lambda _service: SimpleNamespace(repository=root))
    with pytest.raises(DeliveryRefused) as refused:
        execute(service, args("register", revision=revision, path=PLAN_PATH))
    assert refused.value.reason_code == "target_unregistered"
    with service.store.transaction() as tx:
        assert tx.scan(BUCKET_PLANS) == []


def test_the_tick_command_exit_code_follows_the_outcome(tmp_path, monkeypatch):
    service = service_for()
    monkeypatch.setattr(host_delivery, "_git", lambda _service: SimpleNamespace(repository=tmp_path))
    monkeypatch.setattr(host_delivery, "_observer", lambda _service: None)
    monkeypatch.delenv(ENABLED_SETTING, raising=False)
    idle = execute(service, args("tick", plan=None))
    # Nothing is registered and delivery is off: an honest idle read, not a failure and not work.
    assert idle["exit_code"] == 0 and idle["outcome"] == "idle"
    refused = execute(service, args("tick", plan="no-such-plan"))
    assert refused["exit_code"] == 1 and refused["outcome"] == "plan_unregistered"


def test_refusals_print_a_code_and_a_type_and_never_a_value():
    printed = refusal(DeliveryRefused("descriptor_predecessor_mismatch", "expected_descriptor"))
    assert printed == {"status": "refused", "reason_code": "descriptor_predecessor_mismatch",
                       "error_type": "DeliveryRefused", "exit_code": 1}
    assert refusal(ContractError("Stale release controller"))["reason_code"] == "contract_refused"
    assert refusal(OSError("/opt/zeus/secret"))["reason_code"] == "error"
    assert "/opt/zeus" not in json.dumps(refusal(OSError("/opt/zeus/secret")))


def test_delivery_is_opt_in_through_one_explicit_host_setting():
    assert configured_enabled({}) is False and configured_enabled(None) is False
    assert configured_enabled({ENABLED_SETTING: "0"}) is False
    assert configured_enabled({ENABLED_SETTING: "maybe"}) is False
    assert configured_enabled({ENABLED_SETTING: " TRUE "}) is True
    assert configured_enabled({ENABLED_SETTING: "1"}) is True


# ----- the GitHub port ---------------------------------------------------------------------------
class FakeWorkspace:
    """The existing GitWorkspace contract, recorded rather than executed: no push, no gh, no merge."""

    def __init__(self, remote="zeus-owner/zeus-harness"):
        self.remote, self.published, self.merged = remote, [], []

    def publish(self, candidate, title, body):
        self.published.append({"candidate": candidate, "title": title, "body": body})
        return {"url": "https://example.invalid/pull/7", "headRefOid": candidate["revision"],
                "number": 7}

    def merge(self, candidate):
        self.merged.append(candidate)
        return {"merged": True, "revision": candidate["revision"], "merged_revision": "9" * 40}


def candidate():
    return {"revision": REVISION, "tree": TREE, "branch": "harness/delivery-1",
            "objective": CANARY_TEXT}


def test_the_github_port_reads_the_exact_head_and_its_own_rollup(tmp_path):
    rows = [{"number": 7, "url": "u", "headRefOid": REVISION, "state": "OPEN",
             "mergeCommit": None,
             "statusCheckRollup": [{"name": CHECK, "status": "COMPLETED", "conclusion": "SUCCESS"},
                                   {"context": "legacy", "state": "PENDING"}]}]
    calls = []

    def runner(argv, timeout=None):
        calls.append(argv)
        return completed(json.dumps(rows))

    port = GitHubDelivery(FakeWorkspace(), runner=runner)
    observed = port.observe(candidate())
    assert observed["head"] == REVISION and observed["number"] == 7
    assert observed["checks"] == [{"name": CHECK, "state": "success"},
                                  {"name": "legacy", "state": "pending"}]
    assert calls[0][:4] == ["gh", "pr", "list", "--repo"]
    assert "--state" in calls[0] and calls[0][calls[0].index("--head") + 1] == "harness/delivery-1"


def test_an_unreadable_or_failed_listing_raises_instead_of_reporting_no_pull_request():
    for result in (completed("", returncode=1, stderr="gh: not authenticated"),
                   completed("<html>")):
        port = GitHubDelivery(FakeWorkspace(), runner=lambda argv, timeout=None: result)
        with pytest.raises(RuntimeError) as failed:
            port.observe(candidate())
        assert "not authenticated" not in str(failed.value)  # never the client's raw text


def test_no_pull_request_at_all_is_a_definite_none_not_an_invented_one():
    port = GitHubDelivery(FakeWorkspace(), runner=lambda argv, timeout=None: completed("[]"))
    assert port.observe(candidate()) is None
    closed = json.dumps([{"number": 7, "url": "u", "headRefOid": REVISION, "state": "CLOSED",
                          "mergeCommit": None, "statusCheckRollup": []}])
    port = GitHubDelivery(FakeWorkspace(), runner=lambda argv, timeout=None: completed(closed))
    assert port.observe(candidate()) is None


def test_publish_and_merge_go_through_the_existing_workspace_contract():
    workspace = FakeWorkspace()
    port = GitHubDelivery(workspace, runner=lambda argv, timeout=None: completed("[]"))
    published = port.publish(candidate())
    assert published["head"] == REVISION and published["state"] == "OPEN"
    assert workspace.published[0]["candidate"]["revision"] == REVISION
    # The body carries identities only; no objective, plan text or check output reaches GitHub.
    assert CANARY_TEXT not in workspace.published[0]["body"]
    assert REVISION in workspace.published[0]["body"]
    merged = port.merge(candidate())
    assert merged == {"merged": True, "merged_revision": "9" * 40}
    assert workspace.merged == [candidate()]


def test_a_missing_remote_refuses_rather_than_publishing_somewhere_else():
    port = GitHubDelivery(FakeWorkspace(remote=None), runner=lambda argv, timeout=None: completed("[]"))
    with pytest.raises(ContractError):
        port.observe(candidate())


def test_check_rollup_states_are_normalized_without_inventing_a_pass():
    assert normalize_checks(None) == [] and normalize_checks([{"no": "name"}]) == []
    assert normalize_checks([{"name": CHECK, "status": "QUEUED", "conclusion": None}]) == [
        {"name": CHECK, "state": "pending"}]
    assert normalize_checks([{"name": CHECK, "status": "COMPLETED", "conclusion": "SKIPPED"}]) == [
        {"name": CHECK, "state": "failure"}]
    assert normalize_checks([{"context": CHECK, "state": "ERROR"}]) == [
        {"name": CHECK, "state": "failure"}]


# ----- the bounded run loop ------------------------------------------------------------------------
def test_the_run_loop_is_bounded_and_an_empty_queue_idles_without_provider_calls():
    ticks = {"count": 0}

    class Stub:
        def tick(self, plan_id=None):
            ticks["count"] += 1
            return {"outcome": "idle", "stage": None}

    slept = []
    once = run_loop(Stub(), once=True, sleep=slept.append)
    assert once == {"schema": "urn:zeus:host-delivery-run:1", "ticks": 1,
                    "outcomes": {"idle": 1}, "stopped": False}
    assert slept == []  # a single tick never sleeps
    ticks["count"] = 0
    bounded = run_loop(Stub(), max_ticks=3, interval=2, sleep=slept.append)
    assert bounded["ticks"] == 3 and bounded["outcomes"] == {"idle": 3} and slept == [2, 2]


def test_the_run_loop_stops_gracefully_and_finishes_the_tick_in_flight():
    observed = []

    class Stub:
        def __init__(self):
            self.calls = 0

        def tick(self, plan_id=None):
            self.calls += 1
            if self.calls == 2:
                os.kill(os.getpid(), __import__("signal").SIGINT)
            observed.append(self.calls)
            return {"outcome": "progressed", "stage": "publishing"}

    summary = run_loop(Stub(), interval=1, max_ticks=10, sleep=lambda _seconds: None)
    assert summary["stopped"] is True and observed == [1, 2]
    assert summary["outcomes"] == {"progressed": 2}


# ----- the launched service, as an actual child process -----------------------------------------------
def test_the_service_entry_runs_as_a_real_child_process_and_reports_its_identity(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    descriptor = {"schema": "urn:zeus:host-descriptor:1", "target_id": "canary-service",
                  "root": str(tmp_path / "root"), "revision": REVISION, "worker_image": IMAGE,
                  "profile_digest": PROFILE, "predecessor": None}
    (state / DESCRIPTOR_FILE).write_text(json.dumps(descriptor), encoding="utf-8")
    child = subprocess.Popen([sys.executable, "-m", "codex_harness.adapters.host_delivery",
                              "service", "--state-dir", str(state), "--max-seconds", "30"],
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.PIPE)
    try:
        receipt = None
        for _ in range(100):
            if (state / RECEIPT_FILE).exists():
                receipt = json.loads((state / RECEIPT_FILE).read_text("utf-8"))
                break
            time.sleep(0.1)
        assert receipt is not None, "the launched service wrote no startup receipt"
        assert receipt["pid"] == child.pid and receipt["target_id"] == "canary-service"
        assert receipt["descriptor_sha256"] == descriptor_digest(descriptor)
        assert Path(receipt["module_root"]).is_dir()
        (state / "stop.json").write_text(json.dumps({"stop": True}), encoding="utf-8")
        assert child.wait(timeout=30) == 0
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=10)
