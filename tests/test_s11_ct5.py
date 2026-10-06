"""S11 unit CT-5: behavioural tests of the release-check, file-canary and gate-verdict contracts (DESIGN-s11 §5 G2).

Each test names its contract ID in its own docstring and quotes the rule from docs/contracts.md. Expected results come
from that contract text, not from the implementation: the tests drive the public `ReleaseRunner._check` /
`ReleaseRunner.file_canary` (delivery) and `SDD.record_gate_verdict` (review) with fixtures that are labelled as such
(no provider, container, network or database; the pytest children of the CHECK tests are real local processes).
"""

import hashlib
import json
import os
import sys
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest
from _layout import REPO as ROOT

from codex_harness.coordination.application.outbox import Outbox
from codex_harness.delivery.adapters.deployment import ReleaseRunner
from codex_harness.host_os.adapters import process_groups
from codex_harness.intake.application import tickets as ticket_module
from codex_harness.kernel.errors import ContractError
from codex_harness.kernel.ids import SYSTEM_CLOCK
from codex_harness.observation.domain.observation import redact_text, redact_value
from codex_harness.review.adapters.release_suite import REPORT_ENV, SELECT_ENV, ReleaseSuite
from codex_harness.review.adapters.sdd import load_json
from codex_harness.review.application.sdd import SDD
from codex_harness.routing.adapters.organization_source import packaged_organization
from codex_harness.storage.adapters.file_artifacts import FileArtifacts
from codex_harness.storage.adapters.memory_store import MemoryStore

PY = sys.executable
CANDIDATE = "c" * 40


def suite_factory(artifacts, fence):
    """`ReleaseSuite` with the production injections closed over, as composition passes them."""
    return ReleaseSuite(artifacts, fence, run_logged_process=process_groups.run_logged_process, redact=redact_text,
                        redact_value=redact_value)


class FixtureGit:
    """A labelled stand-in for the Git adapter: reports a fixed HEAD and porcelain status, or fails."""

    def __init__(self, head=CANDIDATE, porcelain="", fail=None):
        self.head, self.porcelain, self.fail = head, porcelain, fail

    def _git(self, *args, cwd=None):
        if self.fail:
            raise self.fail
        return self.head if args[:2] == ("rev-parse", "HEAD") else self.porcelain


class Recorder:
    """The injected process port: records every command it is asked to run."""

    def __init__(self, returncode=0, stdout="", stderr=""):
        self.calls, self.result = [], SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)

    def __call__(self, argv, **kwargs):
        self.calls.append(list(argv))
        return self.result


def make_runner(tmp_path, *, git=None, runner=None):
    tmp_path.mkdir(parents=True, exist_ok=True)
    auth = tmp_path / "fixture-auth.json"
    auth.write_text("{}", "utf-8")  # a labelled placeholder, not a credential
    artifacts = FileArtifacts(str(tmp_path / "artifacts"))
    none = None
    return ReleaseRunner(
        SimpleNamespace(store=MemoryStore()), git, artifacts, str(auth), releases=none, ticket_binding=none,
        ticket_superseded=none, runner=runner, release_suite=suite_factory, verification_services=none,
        verification_environment=none, hooks=none, request_rebase=none, compose_environment=none, naming=none,
        release_queue=none), artifacts


def test_s11_contract_check_001_a_check_runs_only_in_the_candidate_tree(tmp_path):
    """INV-CHECK-001 (docs/contracts.md:361-364): "A check whose workspace HEAD is not the candidate or whose tree is
    dirty is `revision_mismatch` and does not run; a workspace whose revision cannot be observed is
    `observation_error`, never a verdict."

    The receipt binds the workspace, expected revision, observed HEAD and cleanliness; a mismatching, dirty or
    unobservable tree never reaches the process port."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    argv = [PY, "-c", "raise SystemExit(0)"]

    runner, artifacts = make_runner(tmp_path / "ok", git=FixtureGit(), runner=Recorder())
    ok = runner._check(argv, str(workspace), expected_revision=CANDIDATE)
    assert ok["passed"] is True and ok["outcome"] == "executed" and runner.runner.calls == [argv]
    receipt = artifacts.document(ok["evidence"])
    assert receipt["binding"]["cwd"] == str(workspace.resolve())
    assert receipt["binding"]["expected_revision"] == CANDIDATE and receipt["binding"]["observed_head"] == CANDIDATE
    assert receipt["binding"]["dirty"] is False and receipt["argv"] == argv

    cases = [
        (FixtureGit(head="d" * 40), "revision_mismatch"),
        (FixtureGit(porcelain="?? scratch.txt"), "revision_mismatch"),
        (FixtureGit(fail=RuntimeError("not a git worktree")), "observation_error"),
    ]
    for index, (git, outcome) in enumerate(cases):
        runner, artifacts = make_runner(tmp_path / f"case{index}", git=git, runner=Recorder())
        refused = runner._check(argv, str(workspace), expected_revision=CANDIDATE)
        assert refused["passed"] is False and refused["outcome"] == outcome, refused
        assert runner.runner.calls == [], "the check must not run against a tree that is not the candidate"
        assert artifacts.document(refused["evidence"])["executed"] is False


def test_s11_contract_check_001_a_test_run_passes_only_by_its_denominator(tmp_path):
    """INV-CHECK-001 (docs/contracts.md:366-368): "A test run passes only by its parsed denominator — executed tests
    greater than zero and no failures or errors — so an exit status of zero with everything skipped, deselected or no
    tests collected is `empty_check`" and "a summary that reports failures outranks a zero exit".

    Real local pytest children in a throwaway tree: all-skipped exits 0 yet is `empty_check`; one passing test passes;
    a failing test is an executed failure."""
    def run(name, body):
        tree = tmp_path / name
        (tree / "tests").mkdir(parents=True)
        (tree / "tests" / "test_x.py").write_text(body, encoding="utf-8")
        runner, artifacts = make_runner(tmp_path / (name + "-runner"), git=FixtureGit(), runner=Recorder())
        argv = [PY, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests"]
        return runner._check(argv, str(tree), expected_revision=CANDIDATE), artifacts

    skipped, artifacts = run("skipped", "import pytest\n\n@pytest.mark.skip(reason='fixture')\ndef test_a():\n    pass\n")
    assert skipped["passed"] is False and skipped["outcome"] == "empty_check"
    passing, _ = run("passing", "def test_b():\n    assert 1 + 1 == 2\n")
    assert passing["passed"] is True and passing["outcome"] == "executed"
    failing, _ = run("failing", "def test_c():\n    assert False\n")
    assert failing["passed"] is False and failing["outcome"] == "executed"


def test_s11_contract_check_002_a_suite_owns_its_accounting_variables(tmp_path):
    """INV-CHECK-002 (docs/contracts.md:379-384): "an inherited `RELEASE_ACCOUNTING_REPORT` or
    `RELEASE_ACCOUNTING_SELECT` ... is removed from the child environment before collection and named in the report's
    `accounting.inherited_removed`; ... The caller's dict and `os.environ` are never mutated."

    A pytest release check called with stale accounting variables is not filtered by the stale selection, does not
    write into the stale report, names both variables as removed, and leaves the caller's environment untouched."""
    tree = tmp_path / "suite"
    (tree / "tests").mkdir(parents=True)
    (tree / "tests" / "test_x.py").write_text("def test_one():\n    assert True\n\ndef test_two():\n    assert True\n",
                                              encoding="utf-8")
    stale_select, stale_report = tmp_path / "stale.select.json", tmp_path / "stale.jsonl"
    stale_select.write_text(json.dumps(["tests/elsewhere.py::test_gone"]), encoding="utf-8")
    env = {**os.environ, SELECT_ENV: str(stale_select), REPORT_ENV: str(stale_report)}
    snapshot, process_env = dict(env), dict(os.environ)
    runner, artifacts = make_runner(tmp_path / "runner", git=FixtureGit(), runner=Recorder())
    argv = [PY, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests"]
    result = runner._check(argv, str(tree), env=env, expected_revision=CANDIDATE)
    assert result["passed"] is True and result["denominator"]["collected"] == 2, result
    assert not stale_report.exists()
    assert env == snapshot and dict(os.environ) == process_env
    assert artifacts.document(result["evidence"])["accounting"]["inherited_removed"] == [REPORT_ENV, SELECT_ENV]


def test_s11_contract_check_002_an_empty_collection_is_never_a_passing_suite(tmp_path):
    """INV-CHECK-002 (docs/contracts.md:384-386): "A collection that fails, times out, reports nothing or has duplicate
    IDs is not an empty passing suite: `executed` failure, `observation_error`, `coverage_mismatch`; no tests is
    `empty_check`."

    A pytest release check over a tree that collects no tests is not a pass and is `empty_check`; one whose test
    module cannot be imported is not a pass either."""
    runner, _ = make_runner(tmp_path / "runner", git=FixtureGit(), runner=Recorder())
    argv = [PY, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests"]
    empty = tmp_path / "empty"
    (empty / "tests").mkdir(parents=True)
    result = runner._check(argv, str(empty), expected_revision=CANDIDATE)
    assert result["passed"] is False and result["outcome"] == "empty_check", result
    broken = tmp_path / "broken"
    (broken / "tests").mkdir(parents=True)
    (broken / "tests" / "test_x.py").write_text("raise RuntimeError('collection fails')\n", encoding="utf-8")
    result = runner._check(argv, str(broken), expected_revision=CANDIDATE)
    assert result["passed"] is False and result["outcome"] in {"executed", "observation_error", "coverage_mismatch"}, result


# --- INV-RELEASE-FILE-CANARY-001 -------------------------------------------------------------------------------------

def canary_root(argv) -> Path:
    mount = next(a for a in argv if str(a).startswith("type=bind,source=") and str(a).endswith(",target=/canary"))
    return Path(mount[len("type=bind,source="):-len(",target=/canary")])


def canary_runner(tmp_path, monkeypatch, container, *, returncode=0):
    """A `ReleaseRunner` whose `_check` is a labelled fixture writing what the container would leave behind."""
    process = Recorder()
    runner, artifacts = make_runner(tmp_path, runner=process)
    seen = {"argv": None, "root": None, "token": None}

    def check(argv, cwd=None, **kwargs):
        seen["argv"], seen["root"] = [str(a) for a in argv], canary_root(argv)
        seen["token"] = (seen["root"] / "input.txt").read_text("utf-8")
        container(seen["root"], seen["token"])
        receipt = artifacts.put(json.dumps({"fixture": "command", "exit_code": returncode,
                                           "stdout": seen["token"]}), "canary")  # stdout always carries the token
        return {"passed": returncode == 0, "evidence": receipt["ref"], "outcome": "executed", "binding": {}}

    monkeypatch.setattr(runner, "_check", check)
    return runner, artifacts, seen, process


def honest(root, token):
    (root / "output.txt").write_bytes(token.encode())
    (root / "result.json").write_text(json.dumps({"value": token}), "utf-8")


def test_s11_contract_file_canary_the_same_container_runs_codex_then_hands_over_exactly_two_files(tmp_path, monkeypatch):
    """INV-RELEASE-FILE-CANARY-001 (docs/contracts.md:4001-4005): "The SAME owned container runs the UNCHANGED codex
    argv, with the same name, labels, auth mount, prompt, schema and output paths. Only its entrypoint is a fixed
    `/bin/sh` wrapper, which runs codex with the argv as positional arguments, keeps codex's exit status, and then
    hands ownership of exactly `/canary/result.json` and `/canary/output.txt` to the controller's numeric uid:gid with
    `chown -h`."

    The docker argv keeps the owned name and labels, mounts the auth file, overrides only the entrypoint with `/bin/sh
    -c <wrapper>`, passes the codex arguments positionally, and the wrapper chowns exactly the two files with `-h`."""
    runner, _, seen, process = canary_runner(tmp_path, monkeypatch, honest)
    answer = runner.file_canary("sha256:" + "d" * 64, name="owned-canary", labels=("zeus.a=1", "zeus.b=2"))
    argv = seen["argv"]
    assert argv[:5] == ["docker", "run", "--rm", "--name", "owned-canary"]
    assert argv[5:9] == ["--label", "zeus.a=1", "--label", "zeus.b=2"]
    assert f"type=bind,source={runner.auth},target=/root/.codex/auth.json,readonly" in argv
    image = argv.index("sha256:" + "d" * 64)
    assert argv[image - 2:image] == ["--entrypoint", "/bin/sh"]
    assert argv[image + 1] == "-c" and argv[image + 3] == "sh"
    script = argv[image + 2]
    assert script.startswith('codex "$@"') and script.endswith("exit $rc") and "rc=$?" in script
    assert f"chown -h {os.getuid()}:{os.getgid()} /canary/result.json /canary/output.txt" in script
    assert "chmod" not in script and "umask" not in script and "chown -R" not in script
    codex = argv[image + 4:]
    assert codex[:2] == ["exec", "--ephemeral"] and "--output-last-message" in codex
    assert codex[codex.index("--output-last-message") + 1] == "/canary/result.json"
    assert codex[codex.index("--output-schema") + 1] == "/canary/schema.json"
    assert answer["passed"] is True and answer["postcondition_reason"] == "ok"
    assert process.calls == [["docker", "rm", "-f", "owned-canary"]]


def write(name, data):
    def container(root, token):
        honest(root, token)
        target = root / name
        target.unlink()
        if data is not None:
            target.write_bytes(data(token) if callable(data) else data)
    return container


def replace_with_symlink(name):
    def container(root, token):
        honest(root, token)
        outside = root.parent / (root.name + "-outside")
        outside.write_text(token, "utf-8")
        (root / name).unlink()
        (root / name).symlink_to(outside)
    return container


@pytest.mark.parametrize("container,reason,file", [
    (write("result.json", None), "missing", "result.json"),
    (write("output.txt", None), "missing", "output.txt"),
    (replace_with_symlink("output.txt"), "not_regular", "output.txt"),
    (write("result.json", b"{not json"), "not_json", "result.json"),
    (write("result.json", b'["x"]'), "not_object", "result.json"),
    (write("result.json", b'{"other": 1}'), "no_value", "result.json"),
    (write("result.json", b'{"value": "wrong"}'), "value_mismatch", "result.json"),
    (write("output.txt", lambda t: (t + "\n").encode()), "bytes_mismatch", "output.txt"),
])
def test_s11_contract_file_canary_each_postcondition_failure_is_named_and_stdout_is_never_accepted(
        tmp_path, monkeypatch, container, reason, file):
    """INV-RELEASE-FILE-CANARY-001 (docs/contracts.md:4006-4012): "The host postcondition is exact, and stdout is never
    accepted in its place: both paths must be regular files (a symlink or directory is refused); `output.txt` bytes
    must equal the token; `result.json` must be a JSON object whose `value` equals the token. ... The check passes
    only when the command passed and the reason is `ok`."

    The command passes and its stdout carries the token, yet a missing, symlinked, unparseable, non-object, value-less,
    mismatching or byte-different file is a named failure and never a pass."""
    runner, artifacts, seen, _ = canary_runner(tmp_path, monkeypatch, container)
    answer = runner.file_canary("img")
    assert answer["passed"] is False
    assert answer["postcondition_reason"] == reason
    record = json.loads(artifacts.read(answer["postcondition"], 0, 32000))
    assert record["reason"] == reason and record["reason_file"] == file and record["files"][file]["outcome"] == reason


def test_s11_contract_file_canary_the_receipt_is_sanitized_and_an_unwritable_one_is_never_a_pass(tmp_path, monkeypatch):
    """INV-RELEASE-FILE-CANARY-001 (docs/contracts.md:4013-4018): "a sanitized postcondition artifact is stored and
    referenced by the check. ... for each file its existence, type, mode, uid/gid, size, sha256 and its read, parse and
    compare outcomes, plus the named reason and the token's sha256. It never holds raw file content or the token. An
    artifact that cannot be written fails the check as the named observation error
    `postcondition_artifact_unavailable:<ErrorType>`, which is a retry and never a pass."

    The stored receipt names both files' metadata and the token digest but not the token; when the store refuses the
    receipt the check is a failed `observation_error` with the named reason."""
    runner, artifacts, seen, _ = canary_runner(tmp_path / "ok", monkeypatch, honest)
    answer = runner.file_canary("img")
    text = artifacts.read(answer["postcondition"], 0, 32000)
    record = json.loads(text)
    assert answer["passed"] is True and seen["token"] not in text
    assert record["token_sha256"] == hashlib.sha256(seen["token"].encode()).hexdigest()
    for name in ("result.json", "output.txt"):
        entry = record["files"][name]
        assert entry["exists"] is True and entry["type"] == "file" and entry["size"] > 0
        assert {"mode", "uid", "gid", "sha256", "read", "compare"} <= set(entry)

    runner, artifacts, _, _ = canary_runner(tmp_path / "unwritable", monkeypatch, honest)
    original = artifacts.put

    def put(content, kind):
        if kind == "canary-postcondition":
            raise OSError("fixture: store unavailable")
        return original(content, kind)

    monkeypatch.setattr(artifacts, "put", put)
    failed = runner.file_canary("img")
    assert failed["passed"] is False and failed["outcome"] == "observation_error"
    assert failed["postcondition_reason"] == "postcondition_artifact_unavailable:OSError"


def test_s11_contract_file_canary_a_cleanup_failure_is_recorded_and_never_turns_a_failure_into_a_pass(
        tmp_path, monkeypatch):
    """INV-RELEASE-FILE-CANARY-001 (docs/contracts.md:4019-4020): "Removal of the temporary directory is recorded
    truthfully. A cleanup failure is kept as recorded debt and never turns a failure into a pass".

    When the temporary directory cannot be removed the answer records `removed: False` with the error type and keeps
    the verdict it already had (a failing postcondition stays failed; a passing one is not changed to failed)."""
    from codex_harness.delivery.adapters import deployment

    def refuse(path, *args, **kwargs):
        raise PermissionError("fixture: cleanup refused")

    for container, passed in ((write("result.json", None), False), (honest, True)):
        runner, _, seen, _ = canary_runner(tmp_path / str(passed), monkeypatch, container)
        with monkeypatch.context() as scope:
            scope.setattr(deployment.shutil, "rmtree", refuse)
            answer = runner.file_canary("img")
        assert answer["passed"] is passed
        assert answer["cleanup"] == {"removed": False, "error_type": "PermissionError"}
        assert seen["root"].exists()
        for child in seen["root"].iterdir():
            child.unlink()
        seen["root"].rmdir()


# --- INV-GATE-001 -----------------------------------------------------------------------------------------------------

@pytest.fixture
def gated(tmp_path):
    store = MemoryStore()
    tickets = ticket_module.Tickets(store, packaged_organization(), outbox=Outbox())
    ticket = tickets.create({"title": "Gate contract", "problem": "Verdict settlement", "impact": "Gates",
                             "rollback": "Keep prior snapshot", "evidence_refs": ["contract-test-input"],
                             "scope": ["sdd"], "acceptance_criteria": ["Verdicts are bound"],
                             "verification": ["Memory store"]})
    service = SDD(store, FileArtifacts(tmp_path / "artifacts"), None, ticket_binding=ticket_module.ticket_binding,
                  clock=SYSTEM_CLOCK)
    source = {"mode": "working_tree_draft", "repository": "contract-test", "revision": None, "path": "spec.json"}
    row = service.register(deepcopy(load_json(ROOT / "docs/sdd/zeus-sdd.spec.json")), ticket["id"], 1, source)
    return service, row


def test_s11_contract_gate_001_a_non_zero_exit_is_never_pass_and_a_claim_never_settles(gated):
    """INV-GATE-001 (docs/contracts.md:1505): "a non-zero exit is never PASS and an unauthenticated reviewer claim
    never settles a statement"; "the planned statements are the denominator (`not_run` is a state, never an omission)".

    A runner PASS carrying exit status 1 is refused and journals nothing; every planned statement starts `not_run`; an
    unauthenticated reviewer PASS is recorded but leaves its statement `pending`, so the gate is not complete; a claim
    of provider authority without a configured provider is refused."""
    service, row = gated
    stage = row["stage"]
    statements = service.statement_definitions(row, stage)
    statement = "spec_integrity"
    before = service.status(row["id"])
    assert set(before["gates"][stage]["statements"]) == set(statements)
    assert {s["state"] for s in before["gates"][stage]["statements"].values()} == {"not_run"}

    runner_pass = {"statement_id": statement, "stage": stage, "artifact_hash": None, "environment_hash": None,
                   "verdict": "PASS", "origin": "runner_receipt", "receipt_ref": "sha256:" + "f" * 64,
                   "exit_status": 1, "actor": None, "authority": None}
    with pytest.raises(ContractError, match="non-zero exit"):
        service.record_gate_verdict(row["id"], runner_pass)
    assert len(service.status(row["id"])["events"]) == len(before["events"])

    claim = {**runner_pass, "origin": "reviewer_decision", "receipt_ref": None, "exit_status": None,
             "actor": "someone", "authority": "unauthenticated_claim"}
    recorded = service.record_gate_verdict(row["id"], claim)
    assert recorded["gate"]["statements"][statement]["state"] == "pending"
    assert recorded["gate"]["complete"] is False and recorded["release_authorized"] is False
    with pytest.raises(ContractError, match="configured decision provider"):
        service.record_gate_verdict(row["id"], {**claim, "authority": "authenticated_provider"})
