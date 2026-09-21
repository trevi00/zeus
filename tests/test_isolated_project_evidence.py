"""INV-PROJECT-EVIDENCE-001 version 2: the host's declared checks delivered to, and replayed in,
the pinned isolation image.

The Docker client and the attached capture are INJECTED fakes (`FakeDocker` plus a local child that
speaks the inner protocol); no container, image, model or live service runs here, so nothing below
is an observation of a real container. What IS exercised for real: the profile parser, the container
resolution against a real candidate tree, the composed docker argv, the request the host writes, the
entry's own parsing, the inherited claim/classification path and the ledger identity.
"""
import json
import os
import sys
from types import SimpleNamespace

import pytest
from test_isolated_worker import IMAGE, TOKEN, FakeDocker, git

from codex_harness.adapters import isolated_evidence as ie
from codex_harness.adapters import isolated_worker as iw
from codex_harness.adapters import isolated_worker_entry as entry
from codex_harness.adapters import project_evidence as pe
from codex_harness.adapters.artifacts import FileArtifacts
from codex_harness.adapters.evidence_inspection import packaged_policy
from codex_harness.adapters.store import MemoryStore
from codex_harness.application.evidence_inspection import EvidenceInspections
from codex_harness.domain.model import ContractError
from codex_harness.domain.project_evidence import SCHEMA, SCHEMA_V2, parse_profile

TASK = {"id": "task-1", "generation": 1, "attempt": 1, "lease_owner": "worker"}
CANDIDATE = {"revision": "a" * 40, "base": "b" * 40, "tree": "c" * 40}
SCHEMA_DOC = {"type": "object", "properties": {"summary": {"type": "string"}}}
UNIT = ["python", "-m", "pytest", "backend/probes", "-q"]
LINT = ["python", "-m", "ruff", "check", "."]
POLICY = packaged_policy()

# An inner entry fixture that preserves the exact request the host wrote, outside the staging tree.
INNER = r'''
import json, os, sys
request = json.loads(sys.stdin.buffer.read().decode("utf-8"))
here = os.path.dirname(os.path.abspath(sys.argv[0]))
with open(os.path.join(here, "request.json"), "w") as handle:
    json.dump(request, handle)
def send(kind, **body):
    sys.stdout.write(json.dumps({"protocol": "zeus-isolated-worker-v1", "kind": kind, **body}) + "\n")
    sys.stdout.flush()
send("entered")
send("result", result={"answer": {"summary": "done", "tests": []}, "command": {"cli_version": "fixture"},
                       "thread_id": request["session_id"]})
'''


def document(schema=SCHEMA_V2, image=IMAGE, interpreter=iw.TRUSTED_PYTHON, checks=None):
    profile = {"schema": schema,
               "contexts": {"backend": {"cwd": "backend", "interpreter": interpreter,
                                        "source_paths": ["backend/src"],
                                        "dependency_files": ["backend/requirements.lock"]}},
               "checks": checks if checks is not None else [
                   {"id": "unit", "context": "backend", "argv": UNIT, "expected_exit": 0},
                   {"id": "lint", "context": "backend", "argv": LINT, "expected_exit": 0}]}
    if schema == SCHEMA_V2:
        profile["execution"] = {"kind": "container", "image": image}
    return profile


def profile(**kwargs):
    return parse_profile(document(**kwargs), POLICY)


def tree(root):
    (root / "backend" / "src").mkdir(parents=True)
    (root / "backend" / "probes").mkdir()
    (root / "backend" / "requirements.lock").write_bytes(b"example==1.0\n")
    (root / "backend" / "src" / "mod.py").write_text("X = 1\n", encoding="utf-8")
    return root


@pytest.fixture
def workspace(tmp_path):
    return tree(tmp_path / "candidate")


@pytest.fixture
def config():
    isolation = iw.load_isolation({"ZEUS_WORKER_ISOLATION": "docker", "ZEUS_WORKER_IMAGE": IMAGE})
    isolation["limits"] = {**isolation["limits"], "inner_grace_seconds": 1, "cleanup_seconds": 2}
    return isolation


@pytest.fixture
def replays(tmp_path, monkeypatch, config):
    """The verifier backend over the injected client: every replay "runs" and exits 0."""
    fake, captured = FakeDocker(tmp_path), []
    monkeypatch.setattr(iw, "_docker", fake)
    monkeypatch.setenv(iw.TOKEN_NAME, TOKEN)

    def capture(argv, cwd, timeout, max_bytes, env, progress=None):
        captured.append({"argv": argv, "env": env, "progress": progress})
        fake.containers[argv[-1]]["status"] = "exited"
        return {"failure": None, "terminated": False, "returncode": 0, "duration_seconds": 0.1,
                "cleanup": {"reason": "exited", "confirmed": True, "injected": True}}
    monkeypatch.setattr(ie, "_capture", capture)
    return fake, captured


def inspector(tmp_path, isolation, parsed=None):
    return ie.IsolatedProjectEvidenceInspector(FileArtifacts(str(tmp_path / "artifacts")), parsed or profile(),
                                               isolation, tmp_path / "replays")


def observed(check_id, code=0, status="executed"):
    return {"check_id": check_id, "status": status, "exit_code": code}


def creates(fake):
    return [call["args"] for call in fake.calls if call["args"][0] == "create"]


# ---- host-authored delivery, stated in container terms ------------------------------------------
def test_container_delivery_is_the_host_checklist_resolved_into_the_image(workspace, config):
    delivery = pe.container_worker_delivery(profile(), str(workspace), config)
    assert delivery["workspace"] == iw.WORKSPACE and delivery["host_workspace"] == str(workspace.resolve())
    assert delivery["execution"] == {"kind": "container", "image": IMAGE, "mode": "docker",
                                     "limits": config["limits"], "isolation_digest": config["digest"]}
    assert [entry_["check_id"] for entry_ in delivery["commands"]] == ["unit", "lint"]
    assert delivery["commands"][0]["command"] == (
        "cd /workspace/backend && PYTHONPATH=/workspace/backend/src PYTHONDONTWRITEBYTECODE=1 "
        "/opt/zeus/bin/python -m pytest backend/probes -q")
    # Exact, wildcard-free rules for the compound command and both of its parts, as version 1 does.
    assert all(rule.startswith("Bash(") and "*" not in rule for rule in delivery["permissions_allow"])
    assert "Bash(cd /workspace/backend)" in delivery["permissions_allow"]
    # What the worker is told holds container values only; the host checkout stays evidence beside it.
    executed = json.dumps([delivery["commands"], delivery["permissions_allow"], delivery["document"]])
    assert str(workspace.resolve()) not in executed and "/tmp" not in executed
    assert "inside this container" in delivery["document"] and "unit" in delivery["document"]


def test_delivery_and_reviewer_context_refuse_a_profile_that_is_not_this_hosts_image(workspace, config):
    other = {**config, "image": "sha256:" + "b" * 64}
    for call in (pe.container_worker_delivery, pe.container_execution_instructions):
        with pytest.raises(ContractError, match="not the host-selected isolation image"):
            call(profile(), str(workspace), other)
        with pytest.raises(ContractError, match="version 1 has no container execution"):
            call(parse_profile(document(schema=SCHEMA, interpreter=sys.executable), POLICY), str(workspace), config)
        with pytest.raises(ContractError, match="requires the host isolation selection"):
            call(profile(), str(workspace), None)


def test_reviewer_receives_the_same_check_ids_bound_to_its_own_checkout_and_told_not_to_run_them_here(
        tmp_path, config):
    implementation, review = tree(tmp_path / "implementation"), tree(tmp_path / "review")
    told = pe.container_execution_instructions(profile(), str(review), config)
    assert told["checks"] == profile()["checks"] and told["schema"] == SCHEMA_V2
    assert told["contexts"]["backend"]["cwd"] == "/workspace/backend"
    assert told["contexts"]["backend"]["interpreter"] == iw.TRUSTED_PYTHON
    assert "must never be run there" in told["instruction"] and told["execution"]["image"] == IMAGE
    assert str(implementation.resolve()) not in json.dumps(told)
    # Bound to ITS OWN checkout: the digest follows the tree it was resolved against.
    assert told["project_digest"] != pe.container_execution_instructions(
        profile(), str(implementation), config)["project_digest"]


def test_a_missing_context_dependency_or_escaping_path_refuses_before_any_container(tmp_path, config):
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(ContractError, match="cwd is not a directory"):
        pe.container_worker_delivery(profile(), str(empty), config)
    partial = tree(tmp_path / "partial")
    (partial / "backend" / "requirements.lock").unlink()
    with pytest.raises(ContractError, match="dependency file is missing"):
        pe.container_worker_delivery(profile(), str(partial), config)
    escaped = tree(tmp_path / "escaped")
    (escaped / "backend" / "src" / "mod.py").unlink()
    (escaped / "backend" / "src").rmdir()
    try:
        (escaped / "backend" / "src").symlink_to(tmp_path, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("this platform does not allow the symlink the escape check needs")
    with pytest.raises(ContractError, match="resolves outside the candidate"):
        pe.container_worker_delivery(profile(), str(escaped), config)


# ---- the request the host writes, and the entry that reads it -----------------------------------
@pytest.fixture
def candidate(tmp_path):
    repo = tree(tmp_path / "repo")
    git(repo, "init", "-q")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "base")
    return repo


def test_the_delivery_travels_into_the_container_under_its_own_protocol(candidate, config, tmp_path, monkeypatch):
    fake = FakeDocker(tmp_path)
    fake.script.write_text(INNER, encoding="utf-8")
    monkeypatch.setattr(iw, "_docker", fake)
    monkeypatch.setattr(iw, "ProcessTree", fake.tree())
    delivery = pe.container_worker_delivery(profile(), str(candidate), config)
    worker = iw.IsolatedWorker(config, tmp_path / "isolated", docker="docker")
    runtime = worker.runtime(model="fable", runtime={}, max_budget_usd=1.0, settings_document=None,
                             project_delivery=delivery)
    runtime.environment_source = {**os.environ, iw.TOKEN_NAME: TOKEN}
    with runtime as opened:
        result = opened.run("do it", str(candidate), SCHEMA_DOC, 20)
    request = json.loads((tmp_path / "request.json").read_text(encoding="utf-8"))
    assert request["protocol"] == iw.DELIVERY_PROTOCOL != iw.PROTOCOL
    assert request["project_delivery"] == delivery and request["cwd"] == iw.WORKSPACE
    receipt = result["isolation"]["project_evidence"]
    assert receipt["checks"] == ["unit", "lint"] and receipt["execution"]["image"] == IMAGE
    assert receipt["profile_digest"] == profile()["profile_digest"] and receipt["protocol"] == iw.DELIVERY_PROTOCOL
    assert TOKEN not in json.dumps(request) and TOKEN not in json.dumps(result)


def test_a_delivery_for_another_image_or_workspace_never_reaches_a_container(config, tmp_path):
    delivery = {"profile_digest": "d", "workspace": iw.WORKSPACE, "document": "x", "permissions_allow": ["Bash(x)"],
                "execution": {"kind": "container", "image": "sha256:" + "b" * 64}}
    for broken in (delivery, {**delivery, "execution": {"kind": "container", "image": IMAGE},
                              "workspace": "D:/host/checkout"}):
        with pytest.raises(ContractError, match="must name this image and the mounted workspace"):
            iw.IsolatedClaudeRuntime(config, tmp_path / "runs", model="fable", project_delivery=broken)


def serve(request, factory):
    import io
    out = io.BytesIO()
    code = entry.serve(io.BytesIO(json.dumps(request).encode("utf-8")), out, runtime_factory=factory)
    return code, [json.loads(line) for line in out.getvalue().splitlines()]


class FakeRuntime:
    """A labelled stand-in for the in-image ClaudeCodeRuntime; no CLI, model or process exists."""

    seen = []

    def __init__(self, **kwargs):
        FakeRuntime.seen.append(kwargs)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def run(self, prompt, cwd, schema, timeout, **kwargs):
        kwargs.get("on_enter", lambda: None)()
        return {"answer": {"summary": "ok"}, "events": []}


def request_document(protocol=iw.DELIVERY_PROTOCOL, delivery=None):
    body = {"protocol": protocol, "prompt": "do it", "schema": SCHEMA_DOC, "timeout": 20, "model": "fable",
            "session_id": "s", "runtime": {}, "max_budget_usd": None, "settings_document": None,
            "cwd": iw.WORKSPACE, "evidence_root": iw.EVIDENCE}
    return body if delivery is None else {**body, "project_delivery": delivery}


def test_the_entry_hands_the_delivery_to_the_runtime_and_refuses_a_disagreeing_request():
    FakeRuntime.seen = []
    delivery = {"profile_digest": "d", "workspace": iw.WORKSPACE, "document": "x", "permissions_allow": ["Bash(x)"]}
    code, lines = serve(request_document(delivery=delivery), FakeRuntime)
    assert code == 0 and [line["kind"] for line in lines] == ["entered", "result"]
    assert FakeRuntime.seen[0]["project_delivery"] == delivery
    # A legacy request is unchanged: no delivery keyword is invented for it.
    FakeRuntime.seen = []
    code, lines = serve(request_document(protocol=iw.PROTOCOL), FakeRuntime)
    assert code == 0 and "project_delivery" not in FakeRuntime.seen[0]
    # Either half alone is a refusal, never a silently dropped checklist.
    for broken in (request_document(), request_document(protocol=iw.PROTOCOL, delivery=delivery)):
        code, lines = serve(broken, FakeRuntime)
        assert code == 1 and lines[-1]["kind"] == "refused" and lines[-1]["error_type"] == "ValueError"


def test_an_entry_that_predates_delivery_refuses_the_request_rather_than_dropping_the_profile(monkeypatch):
    """The old entry compared the protocol for equality with `zeus-isolated-worker-v1`; simulated
    here by restricting the accepted set. It must refuse, not answer as an unprofiled run."""
    monkeypatch.setattr(entry, "PROTOCOLS", (iw.PROTOCOL,))
    FakeRuntime.seen = []
    code, lines = serve(request_document(delivery={"profile_digest": "d"}), FakeRuntime)
    assert code == 1 and lines[-1]["kind"] == "refused" and "is not zeus-isolated-worker-v1" in lines[-1]["message"]
    assert FakeRuntime.seen == [], "no runtime was opened, so no unprofiled answer could be produced"


# ---- isolated replay of the host's declared checks ----------------------------------------------
def inspect(tmp_path, config, workspace, claims, parsed=None, progress=None):
    checker = inspector(tmp_path, config, parsed)
    snapshot = checker.snapshot(workspace)
    report = checker.inspect(claims, str(workspace), {"task_id": "t"}, environment=snapshot["environment"],
                             interpreter=snapshot["identity"]["interpreter"], project=snapshot["project"],
                             progress=progress)
    return checker, report, snapshot


def test_each_declared_check_is_replayed_in_its_own_container_context(tmp_path, config, workspace, replays):
    fake, captured = replays
    checker, report, snapshot = inspect(tmp_path, config, workspace, [observed("unit"), observed("lint")])
    assert [finding["state"] for finding in report["findings"]] == ["checked", "checked"]
    assert [finding["check_id"] for finding in report["findings"]] == ["unit", "lint"]
    assert report["context"]["python"] == "container:" + IMAGE
    assert report["context"]["interpreter"] == iw.TRUSTED_PYTHON
    assert report["context"]["project_digest"] == snapshot["project"]["digest"]
    # Two replays per check, each its own fresh, network-none, credential-free container.
    assert len(creates(fake)) == 4 and len({args[args.index("--name") + 1] for args in creates(fake)}) == 4
    for args in creates(fake):
        assert args[args.index("--network") + 1] == "none" and "--read-only" in args
        assert args[args.index("-w") + 1] == "/workspace/backend", "the host-declared context directory"
        assert args[args.index("--entrypoint") + 1] == iw.TRUSTED_PYTHON
        assert "PYTHONPATH=/workspace/backend/src" in args and iw.TOKEN_NAME not in args
        assert str(workspace.resolve()) not in " ".join(args), "no host path is mounted or passed"
    assert creates(fake)[0][-4:] == ["-m", "pytest", "backend/probes", "-q"]
    assert creates(fake)[-1][-4:] == ["-m", "ruff", "check", "."]
    # The whole container environment is the fixed image set plus this context's PYTHONPATH: no host
    # PATH, interpreter, PYTHONPATH or other inherited value is passed in.
    passed = {args[index + 1].split("=", 1)[0] for args in creates(fake) for index, token in enumerate(args)
              if token == "-e"}
    assert passed == set(ie.CONTAINER_ENVIRONMENT) | {"PYTHONPATH"} and "PATH" not in passed
    assert TOKEN not in json.dumps(fake.calls) + json.dumps(report)
    assert iw.unresolved_runs(checker.root) == [] and not any(checker.root.glob("*/workspace"))


def test_missing_not_run_unknown_duplicate_and_mismatched_exits_cannot_pass(tmp_path, config, workspace, replays):
    fake, _ = replays
    store = MemoryStore()
    ledger = EvidenceInspections(store, inspector(tmp_path, config))
    row = ledger.inspect(TASK, CANDIDATE, [observed("unit", None, "not_run"), observed("invented"),
                                           observed("unit")], str(workspace))
    assert row["verdict"] == "incomplete"
    states = {finding["claim"]["check_id"]: finding["state"] for finding in row["findings"]
              if (finding.get("claim") or {}).get("check_id")}
    assert states == {"unit": "not_checked", "lint": "not_checked"}
    assert [finding["state"] for finding in row["findings"]][2:] == ["error", "error"], "unknown and duplicate"
    assert creates(fake) == [], "a check with no usable observation is never replayed"
    # A reported failure stays a failure even though every replay agreed with the host's expectation.
    mismatch = ledger.inspect(TASK, CANDIDATE, [observed("unit", 1), observed("lint")], str(workspace))
    unit = mismatch["findings"][0]
    assert unit["state"] == "verified_mismatch" and unit["observed_exits"] == [0, 0] and unit["reported_exit"] == 1
    assert mismatch["verdict"] != "all_checked"
    assert ledger.inspect(TASK, CANDIDATE, [], str(workspace))["verdict"] == "incomplete", "no empty denominator"


def test_a_summary_string_or_an_unauthorized_command_never_reaches_a_container(tmp_path, config, workspace, replays):
    fake, captured = replays
    _, report, _ = inspect(tmp_path, config, workspace, ["python -m pytest backend/probes -q", {"summary": "all green"}])
    assert [finding["state"] for finding in report["findings"]] == ["not_checked", "not_checked", "error", "error"]
    assert creates(fake) == [] and captured == [], "diagnostic prose is not an observation and confers nothing"
    # Defense in depth: a profile object that bypassed the parser still cannot spawn another command.
    checker = inspector(tmp_path, config)
    checker.profile = {**checker.profile, "checks": [{**checker.profile["checks"][0], "argv": ["uv", "run", "pytest"]}]}
    snapshot = checker.snapshot(workspace)
    found = checker.inspect([observed("unit")], str(workspace), {}, environment=snapshot["environment"],
                            interpreter=iw.TRUSTED_PYTHON, project=snapshot["project"])
    assert found["findings"][0]["state"] == "not_checked" and creates(fake) == []


def test_the_image_the_profile_and_the_dependency_bytes_are_all_in_the_cached_identity(
        tmp_path, config, workspace, replays):
    store = MemoryStore()
    first = EvidenceInspections(store, inspector(tmp_path, config)).inspect(
        TASK, CANDIDATE, [observed("unit"), observed("lint")], str(workspace))
    assert first["verdict"] == "all_checked" and first["context"]["project_digest"]
    again = EvidenceInspections(store, inspector(tmp_path, config)).inspect(
        TASK, CANDIDATE, [observed("unit"), observed("lint")], str(workspace))
    assert again["id"] == first["id"], "the same image, profile and tree read back the same proof"
    other_image = {**config, "image": "sha256:" + "b" * 64, "digest": "changed"}
    (workspace / "backend" / "requirements.lock").write_bytes(b"example==2.0\n")
    changed_dependency = EvidenceInspections(store, inspector(tmp_path, config)).inspect(
        TASK, CANDIDATE, [observed("unit"), observed("lint")], str(workspace))
    assert changed_dependency["id"] != first["id"]
    with pytest.raises(ContractError, match="not the host-selected isolation image"):
        inspector(tmp_path, other_image)
    fewer = parse_profile(document(checks=[{"id": "unit", "context": "backend", "argv": UNIT, "expected_exit": 0}]),
                          POLICY)
    narrowed = EvidenceInspections(store, inspector(tmp_path, config, fewer)).inspect(
        TASK, CANDIDATE, [observed("unit")], str(workspace))
    assert narrowed["id"] != first["id"] and narrowed["denominator"]["claims"] == 1


def test_a_lost_owner_during_a_replay_stops_that_container_and_starts_no_replacement(
        tmp_path, config, workspace, replays, monkeypatch):
    """INJECTED: the owner's per-call check refuses exactly where the real bounded poll calls back."""
    fake, _ = replays
    seen = []

    def capture(argv, cwd, timeout, max_bytes, env, progress=None):
        fake.containers[argv[-1]]["status"] = "running"
        seen.append(argv[-1])
        try:
            progress("replay_wait")
        except BaseException as exc:
            exc.capture_cleanup = {"reason": type(exc).__name__, "confirmed": True, "injected": True}
            raise
        raise AssertionError("the refusal never reached the capture")
    monkeypatch.setattr(ie, "_capture", capture)

    def lost(stage=None):
        if stage == "replay_wait":
            raise ContractError("Stale or expired task execution")
    with pytest.raises(ContractError, match="Stale or expired task execution"):
        inspect(tmp_path, config, workspace, [observed("unit"), observed("lint")], progress=lost)
    saved = iw.run_records(tmp_path / "replays")
    assert len(saved) == 1 and saved[0]["state"] == "removed" and saved[0]["result"]["interrupted"] == "ContractError"
    assert [c["args"] for c in fake.calls if c["args"][0] == "kill"] == [["kill", seen[0]]]
    assert len(seen) == 1, "no second replay and no second check was started after the refusal"
    assert iw.unresolved_runs(tmp_path / "replays") == [], "truthful, resolved debt"


# ---- selection, pairing and compatibility -------------------------------------------------------
def test_the_container_profile_selects_the_isolated_check_runner_and_refuses_a_host_profile(tmp_path, config):
    worker = iw.IsolatedWorker(config, tmp_path / "isolated")
    artifacts = FileArtifacts(str(tmp_path / "artifacts"))
    assert type(worker.inspector(artifacts)) is ie.DockerEvidenceInspector, "legacy claim replay is unchanged"
    assert type(worker.inspector(artifacts, profile())) is ie.IsolatedProjectEvidenceInspector
    host_profile = parse_profile(document(schema=SCHEMA, interpreter=sys.executable), POLICY)
    with pytest.raises(ContractError, match="version 1 has no container execution"):
        worker.inspector(artifacts, host_profile)


@pytest.mark.parametrize("settings, profile_kwargs, code", [
    ({}, {}, "project_evidence_profile_requires_isolation"),
    ({"ZEUS_WORKER_ISOLATION": "docker", "ZEUS_WORKER_IMAGE": "sha256:" + "b" * 64}, {},
     "project_evidence_image_mismatch")])
def test_bootstrap_refuses_a_container_profile_without_its_exact_image(monkeypatch, settings, profile_kwargs, code):
    from codex_harness import bootstrap

    monkeypatch.setattr(bootstrap, "settings", lambda: settings)
    with pytest.raises(iw.IsolationError) as refused:
        bootstrap.host_isolation(profile(**profile_kwargs))
    assert refused.value.reason_code == code


def test_bootstrap_still_refuses_a_host_profile_beside_isolation_and_keeps_legacy_absence(monkeypatch):
    from codex_harness import bootstrap

    monkeypatch.setattr(bootstrap, "settings", lambda: {"ZEUS_WORKER_ISOLATION": "docker", "ZEUS_WORKER_IMAGE": IMAGE})
    host_profile = parse_profile(document(schema=SCHEMA, interpreter=sys.executable), POLICY)
    with pytest.raises(iw.IsolationError) as refused:
        bootstrap.host_isolation(host_profile)
    assert refused.value.reason_code == "isolation_refuses_project_evidence_profile"
    monkeypatch.setattr(bootstrap, "settings", lambda: {})
    assert bootstrap.host_isolation() is None and bootstrap.host_isolation(host_profile) is None


class FakeIsolation:
    """The executor's isolation port, recording what it is asked for. No container is created."""

    def __init__(self, config, root):
        self.config, self.root, self.opened = config, root, []

    def runtime(self, **kwargs):
        self.opened.append(kwargs)
        return SimpleNamespace(**kwargs)

    def inspector(self, artifacts, evidence_profile=None):
        return iw.IsolatedWorker(self.config, self.root).inspector(artifacts, evidence_profile)


def executor_for(tmp_path, parsed, isolation):
    from codex_harness.adapters.executor import Executor
    from codex_harness.application.service import Harness
    from codex_harness.bootstrap import organization

    return Executor(Harness(MemoryStore(), organization()), SimpleNamespace(_git=lambda *a, **k: "revision"),
                    FileArtifacts(str(tmp_path / "artifacts")), evidence_profile=parsed, isolation=isolation)


def test_the_executor_pairs_only_a_container_profile_with_isolation(tmp_path, config, workspace):
    isolation = FakeIsolation(config, tmp_path / "isolated")
    executor = executor_for(tmp_path, profile(), isolation)
    assert type(executor.evidence.inspector) is ie.IsolatedProjectEvidenceInspector
    assert executor.container_profile is True
    host_profile = parse_profile(document(schema=SCHEMA, interpreter=sys.executable), POLICY)
    with pytest.raises(ContractError, match="refuses a host project evidence profile"):
        executor_for(tmp_path, host_profile, isolation)
    with pytest.raises(ContractError, match="requires the host isolated worker"):
        executor_for(tmp_path, profile(), None)
    # The same fixed ids reach the worker transport and the reviewer, both in container terms.
    assignment = SimpleNamespace(transport="claude_cli", runtime={}, controls={})
    executor._open_runtime(assignment, "fable", str(workspace), action="implement")
    delivered = isolation.opened[0]["project_delivery"]
    assert [entry_["check_id"] for entry_ in delivered["commands"]] == ["unit", "lint"]
    assert delivered["workspace"] == iw.WORKSPACE
    told = executor._project_instructions(str(workspace))
    assert told["execution"]["image"] == IMAGE and told["checks"] == profile()["checks"]
    # A read-only or non-implement opening still carries no delivery.
    executor._open_runtime(assignment, "fable", str(workspace), action="review_lead")
    assert isolation.opened[1]["project_delivery"] is None


def test_an_unprofiled_isolated_run_is_exactly_the_legacy_one(tmp_path, config, workspace):
    isolation = FakeIsolation(config, tmp_path / "isolated")
    executor = executor_for(tmp_path, None, isolation)
    assert executor.container_profile is False and type(executor.evidence.inspector) is ie.DockerEvidenceInspector
    executor._open_runtime(SimpleNamespace(transport="claude_cli", runtime={}, controls={}), "fable",
                           str(workspace), action="implement")
    assert isolation.opened[0]["project_delivery"] is None


def test_the_python_only_check_restriction_still_holds_for_a_container_profile():
    for argv in (["ruff", "check", "."], ["uv", "run", "python", "-m", "pytest"], ["sh", "-c", "python -m pytest"]):
        with pytest.raises(ContractError):
            parse_profile(document(checks=[{"id": "a", "context": "backend", "argv": argv, "expected_exit": 0}]),
                          POLICY)
