"""S10 C5a: `composition.evidence_gate` (M7 `Executor._inspect_evidence` and the inspector selection, OWNER-DECISIONS-S10 #7).

The selection runs over fake artifacts and an isolation object built from `load_host_isolation`; no Docker call is made and
nothing is spawned. `inspect` runs over recording fakes of the evidence ledger, the workflow and the observer: this file
pins the gate's own rules (the error cause, the verdict mapping, the event outcome), while the M7 parity suites run through
the `m7_executor` shim."""
from __future__ import annotations

import ast
import inspect
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from codex_harness.composition import evidence_gate
from codex_harness.composition.evidence_gate import EvidenceGate, evidence_inspector
from codex_harness.evidence.adapters import container_contract as cc
from codex_harness.evidence.adapters import evidence_inspection as ei
from codex_harness.evidence.adapters import isolated_evidence as ie
from codex_harness.evidence.adapters import project_evidence as pe
from codex_harness.evidence.domain import project_evidence as domain
from codex_harness.execution.adapters.containers import evidence_replay as er
from codex_harness.execution.adapters.containers import owned_container as oc
from codex_harness.host_os.adapters.process_tree import ProcessTree
from codex_harness.kernel.errors import ContractError
from codex_harness.observation.domain.observation import inspection_verdict

IMAGE = "sha256:" + "a" * 64
SECRET = "sk-live-0123456789abcdef-never-in-a-record"


def _isolation(tmp_path):
    return SimpleNamespace(config=oc.load_host_isolation({"ZEUS_WORKER_ISOLATION": "docker", "ZEUS_WORKER_IMAGE": IMAGE}),
                           root=tmp_path / "iso", docker="docker-fake")


def _checks():
    return [{"id": "u", "context": "b", "argv": ["python", "-m", "pytest", "-q"], "expected_exit": 0}]


def _host_profile():
    return domain.parse_profile(
        {"schema": domain.SCHEMA, "contexts": {"b": {"cwd": "b", "interpreter": str(Path(inspect.getfile(inspect)).resolve()),
                                                     "source_paths": ["b/src"], "dependency_files": ["b/r.lock"]}},
         "checks": _checks()}, ei.packaged_policy())


def _container_profile():
    return domain.parse_profile(
        {"schema": domain.SCHEMA_V2, "execution": {"kind": "container", "image": IMAGE},
         "contexts": {"b": {"cwd": "b", "interpreter": cc.TRUSTED_PYTHON, "source_paths": ["b/src"],
                            "dependency_files": ["b/r.lock"]}},
         "checks": _checks()}, ei.packaged_policy())


def test_no_isolation_and_no_profile_is_the_legacy_inspector_with_the_process_tree_port():
    inspector = evidence_inspector(None)
    assert type(inspector) is ei.EvidenceInspector and inspector.process_tree is ProcessTree


def test_a_host_profile_without_isolation_is_the_host_project_inspector():
    inspector = evidence_inspector(None, evidence_profile=_host_profile())
    assert type(inspector) is pe.ProjectEvidenceInspector and inspector.process_tree is ProcessTree


def test_isolation_without_a_profile_is_the_docker_inspector_over_the_replays_root(tmp_path):
    isolation = _isolation(tmp_path)
    inspector = evidence_inspector(None, isolation=isolation)
    assert type(inspector) is ie.DockerEvidenceInspector and inspector.process_tree is ProcessTree
    assert inspector.docker == "docker-fake" and inspector.root == tmp_path / "iso" / "replays"
    assert type(inspector.containers) is er.ContainerEvidenceReplay
    assert inspector.containers.root == tmp_path / "iso" / "replays" and inspector.containers.docker == "docker-fake"
    assert inspector.containers.isolation is isolation.config
    assert inspector.containers.runner is evidence_gate.run_process


def test_isolation_with_a_container_profile_is_the_isolated_project_inspector(tmp_path):
    isolation = _isolation(tmp_path)
    inspector = evidence_inspector(None, isolation=isolation, evidence_profile=_container_profile())
    assert type(inspector) is ie.IsolatedProjectEvidenceInspector and inspector.process_tree is ProcessTree
    assert type(inspector.containers) is er.ContainerEvidenceReplay
    assert inspector.containers.root == tmp_path / "iso" / "replays"


def test_isolation_with_a_host_profile_is_refused(tmp_path):
    with pytest.raises(ContractError, match="Isolated worker mode refuses a host project evidence profile"):
        evidence_inspector(None, isolation=_isolation(tmp_path), evidence_profile=_host_profile())


def test_a_container_profile_without_isolation_is_refused():
    with pytest.raises(ContractError, match="A container project evidence profile requires the host isolated worker"):
        evidence_inspector(None, evidence_profile=_container_profile())


class Observer:
    def __init__(self):
        self.events = []

    def for_lease(self, task):
        return {"lease": task["id"]}

    def correlation(self, task):
        return "corr-1"

    def emit(self, event_type, outcome, **fields):
        self.events.append({"event_type": event_type, "outcome": outcome, **fields})


class Workflow:
    def _owned(self, tx, task):
        return task


class Evidence:
    def __init__(self, row=None, error=None):
        self.row, self.error, self.calls = row, error, []

    def inspect(self, task, candidate, claims, cwd, progress=None, guard=None):
        self.calls.append((claims, cwd))
        if self.error:
            raise self.error
        return self.row


TASK = {"id": "task-1", "message": {"correlation_id": "corr-1"}}
RESULT = {"candidate": {"revision": "r"}, "tests": ["claim"], "execution_ref": "sha256:" + "c" * 64}


def test_a_raising_inspector_is_an_inspection_error_that_carries_no_exception_text():
    observer = Observer()
    gate = EvidenceGate(Evidence(error=RuntimeError("boom " + SECRET)), Workflow(), observer)
    verdict = gate.inspect(TASK, RESULT, "/ws")
    assert verdict["verdict"] == "inspection_error" and verdict["claims"] == 1
    assert re.fullmatch(r"RuntimeError: message_sha256=[0-9a-f]{16}", verdict["cause"])
    assert SECRET not in repr(verdict) and SECRET not in repr(observer.events)
    started, finished = observer.events
    assert started["event_type"] == "development.evidence_inspection_started"
    assert finished["event_type"] == "development.evidence_inspection_finished"
    assert (finished["outcome"], finished["reason_code"], finished["severity"]) == (
        inspection_verdict("inspection_error"))
    assert finished["attributes"]["error_type"] == "RuntimeError"
    assert finished["attributes"]["message_sha256"] == verdict["cause"].split("=")[1]


def test_an_all_checked_row_returns_its_identity_verdict_and_denominator():
    observer = Observer()
    denominator = {"claims": 1, "checked": 1}
    gate = EvidenceGate(Evidence(row={"id": "ins-1", "verdict": "all_checked", "denominator": denominator}),
                        Workflow(), observer)
    assert gate.inspect(TASK, RESULT, "/ws") == {"inspection_id": "ins-1", "verdict": "all_checked",
                                                 "denominator": denominator}
    started, finished = observer.events
    assert started["attributes"] == {"claims": 1} and started["evidence_refs"] == [RESULT["execution_ref"]]
    assert (finished["outcome"], finished["reason_code"], finished["severity"]) == inspection_verdict("all_checked")
    assert finished["attributes"]["inspection_id"] == "ins-1" and finished["attributes"]["findings"] == 1
    assert finished["attributes"]["checked"] == 1


def test_an_ownership_refusal_is_re_raised_and_no_verdict_is_returned():
    refusal = ContractError("Stale or expired task execution")

    class Lost(Evidence):
        def inspect(self, task, candidate, claims, cwd, progress=None, guard=None):
            guard(None)

    class Taken(Workflow):
        def _owned(self, tx, task):
            raise refusal

    observer = Observer()
    with pytest.raises(ContractError) as raised:
        EvidenceGate(Lost(), Taken(), observer).inspect(TASK, RESULT, "/ws")
    assert raised.value is refusal and observer.events[-1]["outcome"] == inspection_verdict("inspection_error")[0]


def test_the_gate_stores_its_three_collaborators_publicly():
    evidence, workflow, observer = Evidence(), Workflow(), Observer()
    gate = EvidenceGate(evidence, workflow, observer)
    assert (gate.evidence, gate.workflow, gate.observer) == (evidence, workflow, observer)


def test_the_gate_takes_nothing_from_tests_and_imports_without_docker():
    tree = ast.parse(Path(inspect.getfile(evidence_gate)).read_text(encoding="utf-8"))
    modules = [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    modules += [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names]
    assert not [m for m in modules if m and (m.split(".")[0] in {"tests", "conftest"} or m.startswith("m7_"))]
    assert not [m for m in modules if m and "docker" in m.lower()]
