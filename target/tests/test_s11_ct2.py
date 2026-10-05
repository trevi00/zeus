"""S11 unit CT-2: behavioural tests for INV-RESEARCH-001, INV-RESEARCH-003, INV-REVERSE-001 and INV-RUNNER-001 (DESIGN-s11 §5 G2).

Each test names its contract ID in its own docstring (the R-L9 citation) and takes its expected results from the contract text
in docs/contracts.md, not from the implementation. Every test drives the public use case or adapter on MemoryStore, FileArtifacts
or an injected fake process port; no provider, network, PostgreSQL or Redis.
"""

import io
import subprocess
from dataclasses import asdict, replace

import pytest

from codex_harness.kernel.errors import ContractError
from codex_harness.kernel.ids import canonical
from codex_harness.research.adapters.source_execution import DockerSourceRunner
from codex_harness.research.application.research import ResearchAudits
from codex_harness.research.application.reverse_progress import ReverseProgress
from codex_harness.research.domain.research import (
    InventoryEntry,
    ObservedAsset,
    PathDisposition,
    SourceIdentity,
    SubsystemAnalysis,
    parse_record,
)
from codex_harness.review.domain.check_results import classify_isolated_run
from codex_harness.storage.adapters.file_artifacts import FileArtifacts
from codex_harness.storage.adapters.memory_store import MemoryStore

IMAGE = "sha256:" + "a" * 64
REPO = "https://github.com/fixture/repo"


class FixtureVerifier:
    """Stands in for the Git-backed source verifier: it accepts the inventory it is given."""

    def verify(self, source, entries):
        return {"entries": [asdict(e) for e in entries]}


def b64(text):
    import base64
    return base64.b64encode(text.encode()).decode()


@pytest.fixture
def audit(tmp_path):
    artifacts = FileArtifacts(str(tmp_path / "artifacts"))
    manifest = artifacts.put(canonical({"version": 1, "entries": []}), "fixture")["ref"]
    source = SourceIdentity(REPO, "1" * 40, "2" * 40, manifest)
    blob = artifacts.put("body", "fixture")["ref"]
    entries = [InventoryEntry(b64("README.md"), "100644", "3" * 40, 4, blob),
               InventoryEntry(b64("src/app.py"), "100644", "4" * 40, 4, blob)]
    service = ResearchAudits(MemoryStore(), FixtureVerifier(), artifacts, None)
    return service, service.import_audit(source, entries, ["core"]), artifacts, entries


def observed(path, state="unreviewed_observed_asset", sha=None, refs=()):
    return ObservedAsset(b64(path), "observed", state, sha, None, list(refs))


def test_s11_contract_research_001_inventory_never_implies_review_and_observed_assets_stay_outside_the_tracked_denominator(audit):
    """INV-RESEARCH-001 (docs/contracts.md:27): "Discovery and historical inventory never imply semantic review."

    Also: assets outside Git "never enter the tracked denominator", whole-analysis completeness needs "every observed asset
    dispositioned", and "a disposition never regresses to pending"."""
    service, record, artifacts, entries = audit
    tracked = sorted(e.path for e in entries)
    assert record["status"] == "source_verified_not_reviewed"
    coverage = service.coverage(record["id"])
    assert coverage["reviewed_paths"] == 0 and coverage["remaining_paths"] == tracked
    assert coverage["whole_analysis_complete"] is False and coverage["adoption_eligible"] is False

    # An asset outside Git has its own ledger: the tracked denominator is unchanged, and a tracked path is refused there.
    result = service.observe_assets(record["id"], [observed("notes/uncommitted.md")])
    assert result["changed"] == 1 and result["total"] == 1 and result["pending"] == 1
    coverage = service.coverage(record["id"])
    assert coverage["remaining_paths"] == tracked and coverage["observed_assets"]["pending"] == 1
    with pytest.raises(ContractError):
        service.observe_assets(record["id"], [replace(observed("README.md"))])
    assert service.coverage(record["id"])["observed_assets"]["total"] == 1

    # A disposition never regresses to pending; the recorded disposition stays.
    evidence = artifacts.put("review of the note", "fixture")["ref"]
    reviewed = observed("notes/uncommitted.md", "semantically_reviewed", "5" * 64, [evidence])
    assert service.observe_assets(record["id"], [reviewed])["pending"] == 0
    with pytest.raises(ContractError):
        service.observe_assets(record["id"], [observed("notes/uncommitted.md")])
    after = service.coverage(record["id"])["observed_assets"]
    assert after["pending"] == 0 and after["states"] == {"semantically_reviewed": 1}
    # Observed assets dispositioned does not turn unreviewed tracked paths into reviewed ones.
    assert service.coverage(record["id"])["whole_analysis_complete"] is False


def test_s11_contract_research_003_unknown_path_dispositions_are_refused_and_unexecuted_work_is_not_completion():
    """INV-RESEARCH-003 (docs/contracts.md:29): "Any other value, including `partial`, is refused by both boundaries and never
    normalized to a reviewed disposition."

    The accepted vocabulary is the six names the contract lists; "Missing execution ... cannot establish completion", so a
    subsystem analysis with neither receipts nor explained tests not run is refused."""
    base = dict(evidence_refs=[], symbols=[], justification="", links=[], method="", receipt_ids=[])
    for name in ("unreviewed", "unavailable"):
        PathDisposition(b64("a.py"), name, **base).validate()
    # An otherwise complete record (evidence and justification present): only the vocabulary can refuse it.
    full = dict(base, evidence_refs=["sha256:" + "6" * 64], justification="read part of the file")
    PathDisposition(b64("a.py"), "semantic", **full).validate()
    for name in ("partial", "reviewed", "semantic ", "UNREVIEWED", ""):
        with pytest.raises(ContractError):
            PathDisposition(b64("a.py"), name, **full).validate()
        with pytest.raises(ContractError):  # the wire boundary refuses it too
            parse_record({"version": 1, "kind": "PathDisposition",
                          "record": {"path": b64("a.py"), "disposition": name, **full}})
    # A reviewed disposition needs evidence and a justification; it is not granted by name alone.
    with pytest.raises(ContractError):
        PathDisposition(b64("a.py"), "semantic", **base).validate()

    trace = ["x"]
    analysis = dict(name="core", paths=trace, contracts=trace, entry_points=trace, implementations=trace, callers=trace,
                    configuration=trace, storage_authority=trace, failure_paths=trace, tests=["t"], receipt_ids=[],
                    evidence_refs=["sha256:" + "6" * 64], contradictions=[], unresolved_dependencies=[], tests_not_run=[])
    with pytest.raises(ContractError):  # no execution receipt and nothing recorded as not run
        SubsystemAnalysis(**analysis).validate()
    with pytest.raises(ContractError):  # a test not run needs its reason and follow-up
        SubsystemAnalysis(**{**analysis, "tests_not_run": [{"test": "t", "reason": "", "follow_up": ""}]}).validate()
    SubsystemAnalysis(**{**analysis, "tests_not_run": [{"test": "t", "reason": "no docker", "follow_up": "rerun on host"}]}).validate()
    SubsystemAnalysis(**{**analysis, "receipt_ids": ["receipt-1"]}).validate()


@pytest.fixture
def progress(tmp_path):
    artifacts = FileArtifacts(str(tmp_path / "artifacts"))
    return ReverseProgress(MemoryStore(), artifacts), artifacts.put("verified generated document", "fixture")["ref"]


def pin(commit="a", status="clean"):
    return {"repository": "source-project", "commit": commit * 40, "tree": "b" * 40, "status": status}


def test_s11_contract_reverse_001_records_bind_a_clean_source_and_are_idempotent_fenced_and_ordered(progress):
    """INV-REVERSE-001 (docs/contracts.md:47): "Unknown or dirty source cannot authorize continuation. Requests are idempotent
    and generation-fenced; complete predecessors are required; explicit rebaseline preserves prior history."

    The record binds "source repository, commit, tree and retained artifacts"."""
    app, ref = progress
    for source in (pin(status="dirty"), pin(status="unknown"), {"repository": "source-project"}, None):
        with pytest.raises(ContractError):
            app.record("p", "1-A", "complete", source, [ref], 0, "dirty")
    assert app.status("p", pin(status="dirty"))["source_state"] == "dirty" and app.status("p", pin())["progress"] is None

    row = app.record("p", "1-A", "complete", pin(), [ref], 0, "r1")
    assert row["source"] == {"repository": "source-project", "commit": "a" * 40, "tree": "b" * 40}
    assert row["releases"]["1-A"]["artifact_refs"] == [ref] and row["generation"] == 1
    with pytest.raises(ContractError):  # a complete stage needs retained artifacts
        app.record("p", "1-B", "complete", pin(), [], 1, "r-empty")

    assert app.record("p", "1-A", "complete", pin(), [ref], 0, "r1") == row  # the replay is the same result, not generation 2
    assert app.status("p", pin())["progress"]["generation"] == 1
    with pytest.raises(ContractError):  # the same request id with another command conflicts
        app.record("p", "1-A", "partial", pin(), [ref], 0, "r1")
    with pytest.raises(ContractError):  # a stale generation is fenced
        app.record("p", "1-B", "complete", pin(), [ref], 0, "r2")
    with pytest.raises(ContractError):  # the predecessor stage must be complete
        app.record("p", "1-C", "complete", pin(), [ref], 1, "r3")
    assert app.status("p", pin())["progress"]["generation"] == 1

    # A changed source needs an explicit rebaseline at the first stage, and the earlier history is preserved.
    with pytest.raises(ContractError):
        app.record("p", "1-A", "partial", pin("c"), [], 1, "r4")
    rebased = app.record("p", "1-A", "partial", pin("c"), [], 1, "r5", rebaseline=True)
    assert rebased["generation"] == 2 and rebased["source"]["commit"] == "c" * 40
    assert rebased["releases"] == {"1-A": {"status": "partial", "artifact_refs": [], "at": rebased["releases"]["1-A"]["at"]}}
    with app.store.transaction() as tx:
        history = sorted(r["generation"] for r in tx.scan("reverse_history"))
    assert history == [1, 2]


class FakeProcess:
    def __init__(self, returncode, out, err, deadline=False):
        self.stdout, self.stderr = io.BytesIO(out.encode()), io.BytesIO(err.encode())
        self.returncode, self.deadline, self.killed = returncode, deadline, False

    def wait(self, timeout=None):
        if self.deadline and not self.killed:
            raise subprocess.TimeoutExpired("docker", timeout)
        return self.returncode

    def kill(self):
        self.killed = True


class FakeProcesses:
    """The injected `ChildProcesses` port: `popen` records the argv and returns the scripted process, or raises."""

    def __init__(self, process=None, error=None):
        self.process, self.error, self.argvs = process, error, []

    def popen(self, argv, **kwargs):
        self.argvs.append(list(argv))
        if self.error:
            raise self.error
        return self.process


@pytest.fixture
def runner_world(tmp_path):
    artifacts = FileArtifacts(str(tmp_path / "artifacts"))
    manifest = {"version": 1, "repository": REPO, "commit": "1" * 40, "tree": "2" * 40, "entries": []}
    source = SourceIdentity(REPO, "1" * 40, "2" * 40, artifacts.put(canonical(manifest), "fixture")["ref"])
    return artifacts, source, manifest, tmp_path


def run_once(world, processes, command=("python", "script.py"), attempt=None, source=None):
    artifacts, default_source, _, tmp_path = world
    removed = []
    runner = DockerSourceRunner(tmp_path / "host", artifacts, processes=processes, classify=classify_isolated_run,
                                run_process=lambda argv, timeout: removed.append(list(argv)) or subprocess.CompletedProcess(argv, 0, "", ""))
    receipt = runner.execute(source or default_source, list(command), IMAGE, attempt=attempt)
    return receipt, artifacts.document(receipt.output_ref), removed


def test_s11_contract_runner_001_an_isolated_run_is_named_by_where_it_ended_and_what_it_produced(runner_world):
    """INV-RUNNER-001 (docs/contracts.md:415-425): "An executed command passes only with exit 0 and observable stdout: exit 0
    with no output, or with diagnostics only on stderr, is not a pass"; "In-container deadline exits (124, 137) are `timeout`;
    the runner's own exits (125-127) are `runner_error`".

    Every receipt carries "the command, the runner mode, output digests, the category and, when dispatched from the queue, the
    request, owner, task and generation it ran for"."""
    attempt = {"request_id": "r1", "owner": "o1", "task_id": "t1", "generation": 1}
    seen = {}
    for name, (status, out, err) in {"ok": (0, "hello", ""), "empty": (0, "", ""), "stderr": (0, "", "FAIL: x"),
                                      "deadline": (137, "", ""), "runner": (125, "", "docker: daemon error"),
                                      "failing": (2, "out", "")}.items():
        seen[name] = run_once(runner_world, FakeProcesses(FakeProcess(status, out, err)), attempt=attempt)
    receipt, doc, _ = seen["ok"]
    assert receipt.passed is True and receipt.outcome == "executed" and not receipt.inspection_blocked
    assert doc["verdict"]["category"] == "executed" and doc["command"] == ["python", "script.py"]
    assert doc["runner_mode"] == "docker-networkless-readonly" and doc["attempt"] == attempt
    assert doc["stdout_sha256"] and doc["stderr_sha256"]
    for name in ("empty", "stderr", "failing"):
        assert seen[name][0].passed is False, name
        assert seen[name][1]["verdict"]["category"] == "executed"
    assert seen["empty"][1]["verdict"]["output_class"] == "empty" and seen["stderr"][1]["verdict"]["output_class"] == "stderr_only"
    assert seen["deadline"][1]["verdict"]["category"] == "timeout" and seen["deadline"][0].passed is False
    assert seen["runner"][1]["verdict"]["category"] == "runner_error" and seen["runner"][0].inspection_blocked
    # A pytest command passes only by its parsed denominator: all-skipped exit 0 is not a pass.
    receipt, doc, _ = run_once(runner_world, FakeProcesses(FakeProcess(0, "3 skipped in 0.1s", "")), command=("python", "-m", "pytest"))
    assert receipt.passed is False and doc["verdict"]["mode"] == "pytest"
    receipt, doc, _ = run_once(runner_world, FakeProcesses(FakeProcess(0, "4 passed in 0.2s", "")), command=("python", "-m", "pytest"))
    assert receipt.passed is True and doc["verdict"]["denominator"]["passed"] == 4


def test_s11_contract_runner_001_isolation_failures_are_unavailable_never_a_host_run_and_a_client_timeout_removes_the_container(runner_world):
    """INV-RUNNER-001 (docs/contracts.md:417-420): "Materialization or runner start failures are `isolation_unavailable` with
    the failing stage and error; they are never substituted by a run in the host environment. A runner client that outlives
    its deadline is `client_timeout` and the uniquely named container is removed regardless."
    """
    artifacts, source, manifest, _ = runner_world
    # Runner start failure: the spawn raises; the only other process call is the removal of the named container.
    processes = FakeProcesses(error=FileNotFoundError("docker"))
    receipt, doc, removed = run_once(runner_world, processes)
    assert doc["verdict"]["category"] == "isolation_unavailable" and doc["verdict"]["stage"] == "spawn"
    assert doc["verdict"]["substitute_execution"] is False and "FileNotFoundError" in doc["verdict"]["reason"]
    assert receipt.inspection_blocked and receipt.passed is False and len(processes.argvs) == 1
    assert [argv[1:3] for argv in removed] == [["rm", "-f"]]

    # Materialization failure: a source entry whose bytes do not match its hash ends the attempt before any runner starts.
    envelope = artifacts.put(canonical({"data": b64("corrupt"), "bytes_sha256": "f" * 64}), "fixture")["ref"]
    entry = {"path": b64("a.py"), "mode": "100644", "artifact_ref": envelope}
    bad_manifest = artifacts.put(canonical({**manifest, "entries": [entry]}), "fixture")["ref"]
    processes = FakeProcesses(FakeProcess(0, "hello", ""))
    receipt, doc, _ = run_once(runner_world, processes, source=replace(source, manifest_ref=bad_manifest))
    assert doc["verdict"]["category"] == "isolation_unavailable" and doc["verdict"]["stage"] == "materialize"
    assert processes.argvs == [] and receipt.passed is False and receipt.inspection_blocked

    # A client that outlives its deadline: client_timeout, and the uniquely named container is removed.
    processes = FakeProcesses(FakeProcess(0, "", "", deadline=True))
    receipt, doc, removed = run_once(runner_world, processes)
    assert doc["verdict"]["category"] == "client_timeout" and receipt.inspection_blocked and receipt.passed is False
    name = processes.argvs[0][processes.argvs[0].index("--name") + 1]
    assert name.startswith("harness-source-") and removed == [["docker", "rm", "-f", name]]
