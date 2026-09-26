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
import signal
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
    RUNTIME_FILE,
    GitHubDelivery,
    ProcessHostTarget,
    checkout_revision,
    configured_enabled,
    effective_worker_image,
    execute,
    load_plan,
    loaded_runtime,
    normalize_checks,
    refusal,
    run_loop,
    runtime_revision,
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


# Explicit short ids: pytest otherwise embeds each whole body in the node id and in
# PYTEST_CURRENT_TEST, and the oversized case alone exceeds the Windows 32767-byte environment
# limit before the refusal contract is ever exercised. The payloads themselves stay full size.
@pytest.mark.parametrize("body,reason", [
    (b"{not json", "plan_not_json"),
    (json.dumps({"schema": PLAN_SCHEMA}).encode(), "plan_fields"),
    (json.dumps(plan_document(canary_check_id="curl evil")).encode(), "plan_invalid"),
    (b"x" * (MAX_PLAN_BYTES + 1), "plan_too_large")],
    ids=["not-json", "missing-fields", "invalid-canary", "oversized"])
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

    def __init__(self, remote="zeus-owner/zeus-harness", merged_tree=TREE):
        self.remote, self.published, self.merged = remote, [], []
        self.merged_tree, self.qualified = merged_tree, []

    def publish(self, candidate, title, body):
        self.published.append({"candidate": candidate, "title": title, "body": body})
        return {"url": "https://example.invalid/pull/7", "headRefOid": candidate["revision"],
                "number": 7}

    def merge(self, candidate):
        self.merged.append(candidate)
        return {"merged": True, "revision": candidate["revision"], "merged_revision": "9" * 40}

    def qualify_merged(self, candidate, merged_revision, *, fetch=True):
        """The merge owner's own merged-tree check, recorded rather than executed."""
        self.qualified.append((candidate["revision"], merged_revision))
        if self.merged_tree != candidate["tree"]:
            raise ContractError("Merged tree differs from reviewed candidate")
        return {"merged_revision": merged_revision, "tree": self.merged_tree}


def candidate():
    return {"revision": REVISION, "tree": TREE, "branch": "harness/delivery-1",
            "objective": CANARY_TEXT}


def test_the_port_qualifies_a_merged_revision_through_the_existing_workspace_contract():
    """One qualification for both paths; the port never re-implements the merged-tree check."""
    workspace = FakeWorkspace()
    port = GitHubDelivery(workspace, runner=lambda argv, timeout=None: completed("[]"))
    assert port.qualify(candidate(), "9" * 40) == {"merged_revision": "9" * 40, "tree": TREE}
    assert workspace.qualified == [(REVISION, "9" * 40)]
    # A merged revision whose tree is not the reviewed one is refused, merged or not.
    other = GitHubDelivery(FakeWorkspace(merged_tree="d" * 64),
                           runner=lambda argv, timeout=None: completed("[]"))
    with pytest.raises(ContractError):
        other.qualify(candidate(), "9" * 40)


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
                # Delivered in process to the handler run_loop installed. `os.kill` on Windows is
                # TerminateProcess for SIGINT and would end the test runner instead.
                signal.raise_signal(signal.SIGINT)
            observed.append(self.calls)
            return {"outcome": "progressed", "stage": "publishing"}

    summary = run_loop(Stub(), interval=1, max_ticks=10, sleep=lambda _seconds: None)
    assert summary["stopped"] is True and observed == [1, 2]
    assert summary["outcomes"] == {"progressed": 2}


# ----- what a runtime root actually is -------------------------------------------------------------
def test_a_runtime_root_attests_its_own_revision_from_its_own_refs(tmp_path):
    """Plain reads of the checkout's own refs: no `git` process, no network and no descriptor."""
    root = tmp_path / "repo"
    init_repository(root)
    assert checkout_revision(root) is None  # a branch with no commit yet attests nothing
    write_bytes(root, "README.md", b"fixture\n")
    revision = commit(root)
    assert checkout_revision(root) == revision and runtime_revision(root) == revision
    # A packed ref, as a freshly cloned or garbage collected repository has.
    loose = root / ".git" / "refs" / "heads" / "main"
    (root / ".git" / "packed-refs").write_text("# pack-refs with: peeled\n" + revision + " refs/heads/main\n",
                                               encoding="utf-8")
    loose.unlink()
    assert checkout_revision(root) == revision
    # A detached HEAD names the commit directly.
    (root / ".git" / "HEAD").write_text(revision + "\n", encoding="utf-8")
    assert checkout_revision(root) == revision


def test_a_root_that_is_no_checkout_uses_the_owners_attestation_and_nothing_else(tmp_path):
    root = tmp_path / "prepared"
    root.mkdir()
    assert checkout_revision(root) is None and runtime_revision(root) is None
    (root / RUNTIME_FILE).write_text(json.dumps({"revision": "not a revision"}), encoding="utf-8")
    assert runtime_revision(root) is None  # a malformed attestation is unknown, never a guess
    (root / RUNTIME_FILE).write_text(json.dumps({"revision": REVISION}), encoding="utf-8")
    assert runtime_revision(root) == REVISION


def test_a_worktree_pointer_resolves_to_the_git_directory_it_names(tmp_path):
    root = tmp_path / "repo"
    init_repository(root)
    write_bytes(root, "README.md", b"fixture\n")
    revision = commit(root)
    linked = tmp_path / "linked"
    linked.mkdir()
    (linked / ".git").write_text("gitdir: " + str(root / ".git") + "\n", encoding="utf-8")
    assert checkout_revision(linked) == revision


def test_the_effective_worker_image_is_configuration_and_never_a_claim(monkeypatch):
    assert effective_worker_image({}) == "none"  # no isolation image configured, said explicitly
    assert effective_worker_image({"HARNESS_WORKER_IMAGE": IMAGE}) == IMAGE
    assert effective_worker_image({"ZEUS_WORKER_IMAGE": IMAGE}) == IMAGE
    monkeypatch.setenv("ZEUS_WORKER_IMAGE", IMAGE)
    assert effective_worker_image() == IMAGE


def test_a_runtime_root_without_an_importable_harness_is_refused_before_a_process_exists(tmp_path):
    """Binding the launch to the registered root is a precondition, not a best effort."""
    empty = tmp_path / "empty-root"
    empty.mkdir()
    with pytest.raises(DeliveryRefused) as refused:
        ProcessHostTarget.runtime_environment(empty)
    assert refused.value.reason_code == "runtime_root_unavailable"
    real = Path(loaded_runtime()["runtime_root"])
    environment = ProcessHostTarget.runtime_environment(real)
    assert environment["PYTHONPATH"].split(os.pathsep)[0] == str(real / "src")
    assert environment["ZEUS_REPOSITORY"] == str(real)


# ----- the launched service, as an actual child process -----------------------------------------------
def test_the_service_entry_runs_as_a_real_child_process_and_reports_its_identity(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    descriptor = {"schema": "urn:zeus:host-descriptor:1", "target_id": "canary-service",
                  "root": str(tmp_path / "root"), "revision": REVISION, "worker_image": IMAGE,
                  "profile_digest": PROFILE, "predecessor": None}
    (state / DESCRIPTOR_FILE).write_text(json.dumps(descriptor), encoding="utf-8")
    # The interpreter itself, not a Windows venv redirector whose PID is a launcher distinct from the
    # Python process that writes the receipt. The venv is replaced by this process's own import
    # paths, in order, so the child still loads the candidate source and its dependencies.
    interpreter = getattr(sys, "_base_executable", None) or sys.executable
    assert Path(interpreter).is_file(), "no base interpreter to launch directly"
    environment = dict(os.environ)
    environment["PYTHONPATH"] = os.pathsep.join(entry for entry in sys.path if entry)
    child = subprocess.Popen([interpreter, "-m", "codex_harness.adapters.host_delivery",
                              "service", "--state-dir", str(state), "--max-seconds", "30"],
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.PIPE, env=environment)
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
        # The runtime identity is what the child observed, not what the descriptor asked for.
        assert receipt["runtime_root"] == loaded_runtime()["runtime_root"]
        assert Path(receipt["module_root"]).is_relative_to(Path(receipt["runtime_root"]))
        assert receipt["revision"] == (runtime_revision(receipt["runtime_root"]) or "")
        assert receipt["profile_digest"] != PROFILE  # the profile this code packages, not a claim
        (state / "stop.json").write_text(json.dumps({"stop": True}), encoding="utf-8")
        assert child.wait(timeout=30) == 0
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=10)


# ----- the owner's withdrawal command (INV-HOST-DELIVERY-001, aibox SPEC s15 D3) -------------------------
def test_the_withdraw_command_parses_the_exact_owner_arguments():
    argv = ["host-delivery", "withdraw", "--lane", "harness", "--plan", "own-a98e38119629936ab85d1032",
            "--plan-sha256", "c" * 64, "--reason", "reviewed_base_moved", "--evidence", "sha256:" + "e" * 64]
    parsed = cli.parser().parse_args(argv)
    assert (parsed.delivery_command, parsed.lane, parsed.plan, parsed.plan_sha256, parsed.reason, parsed.evidence) == (
        "withdraw", "harness", "own-a98e38119629936ab85d1032", "c" * 64, "reviewed_base_moved", "sha256:" + "e" * 64)
    for missing in ("--plan", "--plan-sha256", "--reason", "--evidence"):
        index = argv.index(missing)
        with pytest.raises(SystemExit):
            cli.parser().parse_args(argv[:index] + argv[index + 2:])
    with pytest.raises(SystemExit):
        cli.parser().parse_args(argv[:-3] + ["because", "--evidence", "sha256:" + "e" * 64])


def test_the_withdraw_command_routes_to_the_lane_controller_without_the_opt_in(tmp_path, monkeypatch):
    """Withdrawal publishes, merges and switches nothing, so a held (disabled) controller can retire work."""
    service, lane_store, calls = service_for(), MemoryStore(), []
    route = {"lane": {"id": "harness", "repository": str(tmp_path), "runtime": str(tmp_path / "rt")},
             "store": lane_store}

    class Controller:
        def withdraw(self, plan_id, plan_sha256, reason, evidence):
            calls.append((plan_id, plan_sha256, reason, evidence))
            return {"withdrawn": True, "cached": False, "plan_id": plan_id}
    monkeypatch.setattr(host_delivery, "resolve_lane", lambda _service, lane_id: route)
    monkeypatch.setattr(host_delivery, "lane_git", lambda lane, host: SimpleNamespace(remote="zeus-owner/zeus-harness"))
    monkeypatch.setattr(host_delivery, "_lane_observer", lambda _route: None)
    monkeypatch.setattr(host_delivery, "_settings", lambda: {})
    monkeypatch.setattr(host_delivery, "controller",
                        lambda _service, **kwargs: calls.append(kwargs["store"]) or Controller())
    monkeypatch.delenv(ENABLED_SETTING, raising=False)
    result = execute(service, args("withdraw", lane="harness", plan="own-plan", plan_sha256="c" * 64,
                                   reason="reviewed_base_moved", evidence="sha256:" + "e" * 64))
    assert result == {"withdrawn": True, "cached": False, "plan_id": "own-plan", "lane": "harness", "exit_code": 0}
    assert calls == [lane_store, ("own-plan", "c" * 64, "reviewed_base_moved", "sha256:" + "e" * 64)]
