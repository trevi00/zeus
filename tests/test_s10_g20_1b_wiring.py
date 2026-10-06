"""GAP #20 (G20-1b): the `research-package` CLI root, the operator-recorded exemption and the RF-RT wiring (DESIGN-s10 §14
G20-D4 revision, D6, D7).

A declared target addition (RF-RT has no M7 counterpart). MemoryStore, no provider: the root conftest's provider guard stays
on, and the composed RunTask's provider seam (`_run`) is replaced by a recorder, so "zero provider calls" is observed."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from codex_harness import composition
from codex_harness.composition import cli_research_package, configuration, operation
from codex_harness.coordination.application.research_admission import PersistedResearchAdmission
from codex_harness.entry import cli
from codex_harness.entry.cli import research_package
from codex_harness.kernel.message import envelope
from codex_harness.research.adapters.research_pins import UvLockPins
from codex_harness.research.application.research_package_policy import ResearchPackagePolicy
from codex_harness.research.application.research_packages import ResearchPackages
from codex_harness.routing.adapters.organization_source import packaged_organization
from codex_harness.storage.adapters.file_artifacts import FileArtifacts
from codex_harness.storage.adapters.memory_store import MemoryStore

DECISION = "sha256:" + "a" * 64
CLAIM = "sha256:" + "c" * 64
NOW = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc).isoformat()


def source(n):
    return {"ref": f"https://example.test/{n}", "title": f"source {n}", "retrieved_at": NOW, "kind": "primary",
            "applicable_version": None, "pin_ref": None, "claim_digest": CLAIM, "opened": True, "available": True}


def document(key):
    return {"key": key, "supersedes": None, "question": "Is the change safe?", "sources": [source(n) for n in range(3)],
            "source_gap": None, "contradictions": [], "recorded_by": "lead:research"}


def lease(ticket="t-1", **details):
    binding = {"id": ticket, "revision": 1, "content_hash": "h"}
    return {"id": "task-" + ticket,
            "message": {"correlation_id": f"ticket:{ticket}:1", "what": {"details": {"zeus_ticket": binding, **details}}}}


@pytest.fixture
def service(monkeypatch):
    handle = composition.ServiceHandle(MemoryStore(), packaged_organization())
    monkeypatch.setattr(composition, "build", lambda: handle)
    return handle


@pytest.fixture
def cmd(service, capsys):
    """Run one `zeus research-package ...` through the real parser and `run`; returns (exit code, printed JSON)."""
    def invoke(*argv):
        args = cli.parser().parse_args(["research-package", *map(str, argv)])
        code = 0
        try:
            research_package.run(args)
        except SystemExit as exit_info:
            code = exit_info.code
        return code, json.loads(capsys.readouterr().out)
    return invoke


def policy(service):
    return ResearchPackagePolicy(ResearchPackages(), UvLockPins("/nonexistent"), clock=composition_clock())


def composition_clock():
    from codex_harness.kernel.ids import SYSTEM_CLOCK
    return SYSTEM_CLOCK


def admit(service, task, action="plan"):
    with service.store.transaction() as tx:
        return policy(service).admit(tx, task, action)


def write(tmp_path, body, name="package.json"):
    path = tmp_path / name
    path.write_text(json.dumps(body), encoding="utf-8")
    return path


# ---- the declared exemption (G20-D4 revision) --------------------------------------------------------------------

def test_exempt_admits_the_ticket_plan_lease_and_unexempt_runs_the_package_rules(service, cmd):
    assert admit(service, lease()) == {"disposition": "research", "reason": "package_missing"}
    code, out = cmd("exempt", "ticket:t-1", "--class", "docs-only", "--reason", "README typo")
    assert (code, out["class"], out["active"]) == (0, "docs-only", True)
    assert admit(service, lease()) == {"disposition": "exempt", "reason": "exempt:docs-only"}
    code, shown = cmd("status", "ticket:t-1")
    assert code == 0 and shown["exemption"]["class"] == "docs-only" and shown["exemption"]["recorded_by"] == "operator"
    code, out = cmd("unexempt", "ticket:t-1", "--reason", "scope grew")
    assert (code, out["active"]) == (0, False)
    assert admit(service, lease()) == {"disposition": "research", "reason": "package_missing"}
    # append-only: both rows are kept
    with service.store.transaction() as tx:
        assert [row["active"] for row in sorted(tx.scan("research_exemptions"), key=lambda r: r["seq"])] == [True, False]


def test_a_store_exemption_that_conflicts_with_a_derived_hook_class_blocks(service, cmd):
    hook = {"objective": "fix", "hook": {"id": "h-1"}}
    cmd("exempt", "ticket:t-1", "--class", "docs-only", "--reason", "README typo")
    assert admit(service, lease(**hook)) == {"disposition": "blocked", "reason": "exemption_conflict"}
    cmd("unexempt", "ticket:t-1", "--reason", "x")
    cmd("exempt", "ticket:t-1", "--class", "bugfix-with-failing-test", "--reason", "the hook is the failing check")
    assert admit(service, lease(**hook)) == {"disposition": "exempt", "reason": "exempt:bugfix-with-failing-test"}


def test_an_unknown_class_and_a_missing_exemption_are_refused_with_nothing_written(service, cmd):
    code, out = cmd("exempt", "ticket:t-1", "--class", "because-i-said-so", "--reason", "r")
    assert code == 1 and out["status"] == "refused" and out["reason_code"] == "contract_refused"
    code, out = cmd("unexempt", "ticket:t-1", "--reason", "r")
    assert code == 1 and out["reason_code"] == "exemption_missing"
    with service.store.transaction() as tx:
        assert tx.scan("research_exemptions") == []


# ---- record / status / accept / withdraw ---------------------------------------------------------------------------

def test_record_status_accept_and_withdraw(service, cmd, tmp_path):
    code, out = cmd("record", "--file", write(tmp_path, document("ticket:t-1")))
    assert (code, out["version"], out["status"]) == (0, 1, "draft")
    code, shown = cmd("status", "ticket:t-1")
    assert shown["current"] == {"version": 1, "status": "draft"} and shown["exemption"] is None
    code, out = cmd("accept", "ticket:t-1", 1, "--decision-ref", DECISION)
    assert (code, out["status"], out["decision_ref"], out["resolved"]) == (0, "accepted", DECISION, [])
    assert admit(service, lease()) == {"disposition": "admit", "reason": "admitted"}
    code, out = cmd("withdraw", "ticket:t-1", 1, "--reason", "superseded by a design change")
    assert (code, out["status"]) == (0, "withdrawn")
    assert admit(service, lease()) == {"disposition": "research", "reason": "package_not_accepted"}


def test_refusals_print_a_code_and_a_type_and_exit_one(service, cmd, tmp_path):
    code, out = cmd("accept", "ticket:t-1", 1, "--decision-ref", DECISION)
    assert (code, out["reason_code"], out["error_type"]) == (1, "package_missing", "PackageRefused")
    cmd("record", "--file", write(tmp_path, document("ticket:t-1")))
    code, out = cmd("accept", "ticket:t-1", 1, "--decision-ref", "not-a-digest")
    assert (code, out["reason_code"]) == (1, "contract_refused")
    code, out = cmd("record", "--file", write(tmp_path, {"key": "ticket:t-1"}, "bad.json"))
    assert (code, out["reason_code"]) == (1, "contract_refused")
    code, out = cmd("record", "--file", tmp_path / "missing.json")
    assert (code, out["reason_code"]) == (1, "contract_refused")
    code, out = cmd("withdraw", "ticket:t-1", 9, "--reason", "r")
    assert (code, out["reason_code"]) == (1, "package_missing")


def test_accept_resolves_exactly_the_matching_holding_admissions(service, cmd, tmp_path):
    admission = PersistedResearchAdmission(policy(service))
    with service.store.transaction() as tx:
        for ticket in ("t-1", "t-2"):
            task = lease(ticket)
            tx.put("tasks", task["id"], task)
            assert admission.admit(tx, task, "plan")["disposition"] == "research"
        implement = {**lease("t-1"), "id": "task-t-1-impl"}
        tx.put("tasks", implement["id"], implement)
        assert admission.admit(tx, implement, "implement")["disposition"] == "research"
    cmd("record", "--file", write(tmp_path, document("ticket:t-1")))
    code, out = cmd("accept", "ticket:t-1", 1, "--decision-ref", DECISION)
    assert code == 0
    assert sorted(out["resolved"], key=lambda r: r["task_id"]) == [{"task_id": "task-t-1", "action": "plan"},
                                                                    {"task_id": "task-t-1-impl", "action": "implement"}]
    with service.store.transaction() as tx:
        states = {(r["task_id"], r["action"]): (r["state"], (r["resolution"] or {}).get("ref")) for r in tx.scan("research_admissions")}
    assert states == {("task-t-1", "plan"): ("resolved", DECISION), ("task-t-1-impl", "implement"): ("resolved", DECISION),
                      ("task-t-2", "plan"): ("holding", None)}


def test_accept_and_resolve_is_one_transaction(service, tmp_path):
    with service.store.transaction() as tx:
        ResearchPackages().record(tx, document("ticket:t-1"))
        task = lease("t-1")
        tx.put("tasks", task["id"], task)
        PersistedResearchAdmission(policy(service)).admit(tx, task, "plan")

    class Failing(PersistedResearchAdmission):
        def resolve(self, *a, **k):
            raise RuntimeError("boom")
    import codex_harness.coordination.application.research_admission as module
    original = module.PersistedResearchAdmission
    module.PersistedResearchAdmission = Failing
    try:
        with pytest.raises(RuntimeError):
            cli_research_package.accept_and_resolve(service, "ticket:t-1", 1, DECISION)
    finally:
        module.PersistedResearchAdmission = original
    with service.store.transaction() as tx:
        assert ResearchPackages().get(tx, "ticket:t-1", 1)["status"] == "draft"


# ---- the pins adapter ---------------------------------------------------------------------------------------------

def test_uv_lock_pins(tmp_path):
    (tmp_path / "uv.lock").write_text('version = 1\n[[package]]\nname = "Some_Pkg"\nversion = "1.2.3"\n'
                                      '[[package]]\nname = "other"\nversion = "4"\n', encoding="utf-8")
    pins = UvLockPins(tmp_path)
    assert pins.current("uv.lock:some-pkg") == "1.2.3" and pins.current("uv.lock:other") == "4"
    assert pins.current("uv.lock:absent") is None
    assert pins.current("git:abc") is None and pins.current("uv.lock:") is None
    (tmp_path / "uv.lock").write_text("not toml [", encoding="utf-8")
    assert pins.current("uv.lock:other") is None
    assert UvLockPins(tmp_path / "nowhere").current("uv.lock:other") is None


# ---- the wiring (G20-D7) ----------------------------------------------------------------------------------------

@pytest.fixture
def settings(monkeypatch, tmp_path):
    values = {"HARNESS_RUNTIME_DIR": str(tmp_path / "runtime"), "ZEUS_COMPOSITION_PROFILE": "development"}
    monkeypatch.setattr(configuration, "settings", lambda: values)
    return values


@pytest.mark.parametrize("profile", ["development", "production"])
def test_build_executor_wires_the_package_policy_in_both_profiles(profile, service, settings, tmp_path):
    stand_in = SimpleNamespace(root=tmp_path / "isolation", config={"image": "sha256:" + "a" * 64}, docker="docker")
    kwargs = {"isolation": stand_in} if profile == "production" else {}
    executor = operation.build_executor(knowledge=False, evidence_profile=None, profile=profile, **kwargs)
    admission = executor.run_task.research_admission
    assert isinstance(admission, PersistedResearchAdmission)
    assert isinstance(admission.policy, ResearchPackagePolicy) and isinstance(admission.policy.packages, ResearchPackages)
    assert isinstance(admission.policy.pins, UvLockPins)


# ---- end to end -------------------------------------------------------------------------------------------------

def test_a_plan_task_holds_without_a_package_and_is_admitted_after_record_and_accept(service, settings, cmd, tmp_path,
                                                                                    monkeypatch):
    executor = operation.Executor(service, SimpleNamespace(_git=lambda *a, **k: "revision", repository=tmp_path),
                                  FileArtifacts(str(tmp_path / "artifacts")), knowledge=None)
    provider_calls = []

    def run(*a, **k):
        provider_calls.append(a)
        raise RuntimeError("provider seam reached")
    monkeypatch.setattr(executor.run_task, "_run", run)
    message = envelope("task.assign", "conductor", "lead:improvement", "plan",
                       {"objective": "o", "acceptance_criteria": ["c"]}, "corr-e2e")
    message["how"]["acceptance_criteria"] = ["c"]
    executor.workflow.submit(message)
    first = executor.execute_one("lead:improvement")
    assert "package_missing" in str(first.get("error")) and provider_calls == []
    with service.store.transaction() as tx:
        held = [r for r in tx.scan("research_admissions") if r["state"] == "holding"]
    assert [(r["disposition"], r["reason"]) for r in held] == [("research", "package_missing")]
    cmd("record", "--file", write(tmp_path, document("correlation:corr-e2e")))
    code, out = cmd("accept", "correlation:corr-e2e", 1, "--decision-ref", DECISION)
    assert code == 0 and len(out["resolved"]) == 1
    # The hold is released: the next consult asks the policy again and admits, so the provider seam is reached.
    for _ in range(3):
        executor.execute_one("lead:improvement")
        if provider_calls:
            break
    assert len(provider_calls) >= 1
