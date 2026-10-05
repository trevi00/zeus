"""S8 batch B3: M7 `adapters/audit_execution.py` moves to `research.adapters.audit_execution` (V24: R-ae1 the injected `audits`, R-ae2 `self.audits.workflow`,
R-ae3 the injected `notices` and `audits.decision_validation`, R-ae4 the injected `decisions`, R-ae5 the `research_proposal_runs` bucket) and M7
`adapters/audit_runner.py` moves to `research.adapters.audit_runner` (V29: R-au0 the import homes, R-au1 the ports `processes`, `run_process` and `classify`,
R-au2 `acquire` through `self.processes`, R-au3 `execute` through `self.run_process`/`self.classify`).

M7 is read only as text through `git show e38aa722:...` and compared by AST (never imported: both packages are named `codex_harness`); the rules are restated
here BY HAND, independently of the transcription script. Behaviour is compared by the recorded `research.audit_execution` and `research.audit_runner` goldens (the
wired modules are target-equal to them); every unwired-port refusal has no M7 counterpart and is pinned here, each with no effect (the store digest unchanged, no
directory, no lock, no staging).
"""

from __future__ import annotations

import ast
import inspect
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from _layout import REPO, TARGET

from codex_harness.execution import ports as execution_ports
from codex_harness.kernel.errors import ContractError
from codex_harness.research import ports as research_ports
from codex_harness.research.adapters import audit_execution as ae
from codex_harness.research.adapters import audit_runner as ar
from codex_harness.storage.adapters.memory_store import MemoryStore

SRC = TARGET / "src" / "codex_harness"
SOURCE = "e38aa722"
AE_M7 = "src/codex_harness/adapters/audit_execution.py"
AR_M7 = "src/codex_harness/adapters/audit_runner.py"
VALIDATION = "Decision validation is not wired"
DECISIONS = "Decision record is not wired"
NOTICES = "Execution notices are not wired"


def m7_text(path):
    return subprocess.run(["git", "-C", str(REPO), "show", f"{SOURCE}:{path}"], check=True, capture_output=True, text=True).stdout


def text_of(module):
    return Path(module.__file__).read_text()


def statements(src):
    out = {}
    for i, node in enumerate(ast.parse(src).body):
        if isinstance(node, (ast.Import, ast.ImportFrom)) or (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)):
            continue
        name = getattr(node, "name", None) or (node.targets[0].id if isinstance(node, ast.Assign) else i)
        out[name] = node
    return out


def import_modules(src):
    return sorted({n.module for n in ast.walk(ast.parse(src)) if isinstance(n, ast.ImportFrom)})


def class_of(src, name):
    return next(n for n in ast.parse(src).body if isinstance(n, ast.ClassDef) and n.name == name)


def method(cls, name):
    return next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == name)


def replaced(text, old, new, count):
    assert text.count(old) == count, (old, text.count(old))
    return text.replace(old, new)


def spawn_calls(src):
    """Every `subprocess.<spawn>(...)` call of the module (the chokepoint's concern)."""
    return [ast.unparse(n.func) for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and isinstance(n.func.value, ast.Name) and n.func.value.id == "subprocess"
            and n.func.attr in ("run", "Popen", "call", "check_call", "check_output")]


def put_buckets(src):
    return sorted(n.args[0].value for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                  and n.func.attr == "put" and n.args and isinstance(n.args[0], ast.Constant))


def digest_of(store):
    with store.transaction() as tx:
        return sorted((r["bucket"], r["id"], repr(sorted(r["body"].items()))) for r in tx.records())


def preceded_by_require(cls, function, call, message):
    """Every statement of `function` that is the call `call(...)` is directly preceded by `require(<port> is not None, message)`; the sites found."""
    found = 0
    for node in ast.walk(method(cls, function)):
        for field in ("body", "orelse", "finalbody"):
            block = getattr(node, field, None)
            if not isinstance(block, list):
                continue
            for index, item in enumerate(block):
                if isinstance(item, ast.Expr) and isinstance(item.value, ast.Call) and ast.unparse(item.value.func) == call:
                    before = block[index - 1]
                    assert isinstance(before, ast.Expr) and ast.unparse(before.value).endswith(f"is not None, {message!r})"), (call, ast.unparse(before))
                    found += 1
    return found


# ----- audit_execution: the rules restated by hand ------------------------------------------------------------------------------------------
def ae_expected_class():
    """M7's `AuditExecution` with R-ae1..R-ae4 applied textually: an independent statement of the rules."""
    t = m7_text(AE_M7)
    t = replaced(t, "    def __init__(self, executor, runner):\n        self.executor, self.runner = executor, runner\n"
                    "        self.audits = ResearchAudits(executor.service.store, None, executor.artifacts,\n                                    executor.workflow, runner)\n",
                 "    def __init__(self, executor, runner, *, audits, notices=None, decisions=None):\n        self.executor, self.runner = executor, runner\n"
                 "        self.audits = audits\n        self.notices, self.decisions = notices, decisions\n", 1)
    t = replaced(t, "self.executor.workflow", "self.audits.workflow", 6)
    t = replaced(t, "        from codex_harness.application.execution_notices import record as execution_notice\n"
                    "        from codex_harness.application.execution_recovery import ExecutionRecovery\n"
                    "        recovery = ExecutionRecovery(self.audits.store, self.audits.workflow.org, self.audits.artifacts)\n", "", 1)
    for indent in ("                    ", "                "):
        t = replaced(t, indent + "recovery.validate_decision(tx, current)\n",
                     indent + f"require(self.audits.decision_validation is not None, {VALIDATION!r})\n"
                     + indent + "self.audits.decision_validation.validate_decision(tx, current)\n", 1)
    t = replaced(t, "                    tx.put('decisions_pending', task['id'], current)\n                    execution_notice(",
                 f"                    require(self.decisions is not None, {DECISIONS!r})\n                    self.decisions.record(tx, current)\n"
                 f"                    require(self.notices is not None, {NOTICES!r})\n                    self.notices.record(", 1)
    t = replaced(t, "            tx.put('decisions_pending', task['id'], current)\n            if blocked:\n                execution_notice(",
                 f"            require(self.decisions is not None, {DECISIONS!r})\n            self.decisions.record(tx, current)\n            if blocked:\n"
                 f"                require(self.notices is not None, {NOTICES!r})\n                self.notices.record(", 1)
    return class_of(t, "AuditExecution")


def test_audit_execution_is_m7s_modulo_the_v24_rules():
    """Structural: move fidelity, `AuditExecution` is M7's class statement for statement modulo the V24 rules (the S8 move
    rule); behaviour is covered by test_the_blocked_review_refuses_each_unwired_port_with_no_effect,
    test_the_wired_blocked_review_validates_records_and_notifies_in_one_transaction and
    test_the_succeeded_review_needs_decisions_but_not_notices_and_does_not_validate."""
    ours, theirs = statements(text_of(ae)), statements(m7_text(AE_M7))
    assert list(ours) == list(theirs)
    for name, node in theirs.items():
        if name != "AuditExecution":
            assert ast.dump(ours[name]) == ast.dump(node), name
    assert ast.dump(ours["AuditExecution"]) == ast.dump(ae_expected_class())


def test_audit_execution_rule_sites_and_removed_names():
    text = text_of(ae)
    cls = class_of(text, "AuditExecution")
    assert not [n for n in ast.walk(cls) if isinstance(n, ast.Attribute) and n.attr == "workflow" and ast.unparse(n.value) == "self.executor"]
    sites = sorted(n.attr for n in ast.walk(cls) if isinstance(n, ast.Attribute) and n.attr in ("_owned", "heartbeat") and ast.unparse(n.value) == "self.audits.workflow")
    assert sites == ["_owned"] * 5 + ["heartbeat"]   # the six places M7 read `executor.workflow`
    code = {n.id for n in ast.walk(ast.parse(text)) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(ast.parse(text)) if isinstance(n, ast.Attribute)}
    assert "service" not in code and "ResearchAudits" not in code
    assert preceded_by_require(cls, "review", "self.audits.decision_validation.validate_decision", VALIDATION) == 2
    assert preceded_by_require(cls, "review", "self.decisions.record", DECISIONS) == 2
    assert preceded_by_require(cls, "review", "self.notices.record", NOTICES) == 2
    assert "decisions_pending" in text and put_buckets(text) == ["research_backlog", "research_backlog", "research_proposal_runs"]
    assert not ({"recovery", "execution_notice", "ExecutionRecovery"} & {n.id for n in ast.walk(ast.parse(text)) if isinstance(n, ast.Name)})
    assert spawn_calls(text) == []


def test_audit_execution_import_homes_and_header():
    text = text_of(ae)
    assert import_modules(text) == ["codex_harness.kernel.analysis", "codex_harness.kernel.errors", "codex_harness.kernel.ids",
                                    "codex_harness.research.application.audit_gate", "codex_harness.research.domain.audit_repair",
                                    "codex_harness.research.domain.research", "dataclasses", "importlib.resources"]
    doc = ast.get_docstring(ast.parse(text))
    assert "Layer: adapters\nContext: research\n" in doc and "Contracts: INV-RESEARCH-002, INV-RESEARCH-003, INV-AUDIT-REPAIR-001" in doc
    assert all(rule in doc for rule in ("R-ae0", "R-ae1", "R-ae2", "R-ae3", "R-ae4", "R-ae5"))


def test_r_ae5_research_proposal_runs_is_a_research_bucket_with_a_single_writer():
    assert research_ports.OWNED_BUCKETS.count("research_proposal_runs") == 1
    for path in SRC.rglob("*.py"):
        if path == Path(ae.__file__):
            continue
        body = path.read_text()
        assert "put('research_proposal_runs'" not in body and 'put("research_proposal_runs"' not in body, path


def test_audit_execution_constructor_shape_and_the_execution_port():
    parameters = inspect.signature(ae.AuditExecution.__init__).parameters
    assert [(p.name, p.kind.name, p.default is inspect.Parameter.empty) for p in parameters.values()] == [
        ("self", "POSITIONAL_OR_KEYWORD", True), ("executor", "POSITIONAL_OR_KEYWORD", True), ("runner", "POSITIONAL_OR_KEYWORD", True),
        ("audits", "KEYWORD_ONLY", True), ("notices", "KEYWORD_ONLY", False), ("decisions", "KEYWORD_ONLY", False)]
    with pytest.raises(TypeError):
        ae.AuditExecution(SimpleNamespace(), None)   # `audits` is required: nothing is ever built in-adapter
    # `execution.ports.AuditExecution` (execute) and the review port (`ReviewDecisions` calls `.review(lease)`)
    assert list(inspect.signature(ae.AuditExecution.execute).parameters) == list(inspect.signature(execution_ports.AuditExecution.execute).parameters)
    assert list(inspect.signature(ae.AuditExecution.review).parameters) == ["self", "task"]
    instance = ae.AuditExecution(SimpleNamespace(), None, audits=SimpleNamespace())
    assert callable(instance.execute) and callable(instance.review) and (instance.notices, instance.decisions) == (None, None)


# ----- audit_execution: behaviour of the injected ports -------------------------------------------------------------------------------------
BLOCKED = {"id": "receipt-1", "receipt": {"inspection_blocked": True, "exit_status": 125, "output_ref": "sha256:" + "a" * 64}}
PASSED = {"id": "receipt-1", "receipt": {"inspection_blocked": False, "exit_status": 0, "output_ref": "sha256:" + "a" * 64}}
ASSESSMENTS = {"license_assessment": "l", "dependency_assessment": "d", "sre_assessment": "s", "architecture_assessment": "a", "graph_assessment": "g"}


class Recorder:
    def __init__(self, name, tx_writes=None):
        self.name, self.calls, self.tx_writes = name, [], tx_writes

    def validate_decision(self, tx, row):
        self.calls.append(("validate", row["id"]))

    def record(self, *args, **kwargs):
        self.calls.append(("record", args[0] is not None))
        if self.tx_writes:   # a write inside the caller's transaction: a later refusal must roll it back
            args[0].put(self.tx_writes, "written", {"id": "written"})


def review_case(receipt, answers=(), validation=True, decisions=True, notices=True):
    """An `AuditExecution` over a stub `audits` (the composed `ResearchAudits` is another family) and a leased decision row."""
    store = MemoryStore()
    lease = {"id": "d1", "status": "running", "actor": "lead:research", "_bucket": "decisions_pending",
             "input": {"audit_id": "audit-1", "binding": "binding-1"}}
    with store.transaction() as tx:
        tx.put("decisions_pending", "d1", dict(lease))
    heartbeats, turns, reviewed = [], list(answers), []
    workflow = SimpleNamespace(org="org-1", heartbeat=lambda task: heartbeats.append(task["id"]),
                               _owned=lambda tx, task: tx.get("decisions_pending", task["id"]))
    validator = Recorder("validation", None)
    audits = SimpleNamespace(store=store, artifacts=None, workflow=workflow, execute=lambda task, audit_id, command: receipt,
                             decision_validation=validator if validation else None, review=lambda task, review: reviewed.append(review))
    # the executor is a RunTask-shaped stub: `_run`, `git.repository`, `research`, and NO `service` and NO `workflow`
    executor = SimpleNamespace(git=SimpleNamespace(repository="/repository"), research=None,
                               _run=lambda *args, **kwargs: (kwargs["heartbeat"](), turns.pop(0))[1])
    record, notice = Recorder("decisions", "decisions_pending"), Recorder("notices", "execution_notices")
    adapter = ae.AuditExecution(executor, None, audits=audits, decisions=record if decisions else None, notices=notice if notices else None)
    return SimpleNamespace(adapter=adapter, store=store, lease=lease, heartbeats=heartbeats, reviewed=reviewed, validator=validator,
                           decisions=record, notices=notice)


@pytest.mark.parametrize("receipt, answers", [(BLOCKED, ()), (PASSED, ({"accepted": False, "inspection_blocked": True},))],
                         ids=["blocked-inspection", "model-reported-block"])
def test_the_blocked_review_refuses_each_unwired_port_with_no_effect(receipt, answers):
    for missing, message in (("validation", VALIDATION), ("decisions", DECISIONS), ("notices", NOTICES)):
        case = review_case(receipt, answers, **{missing: False})
        before = digest_of(case.store)
        with pytest.raises(ContractError, match=message):
            case.adapter.review(case.lease)
        assert digest_of(case.store) == before, missing   # the transaction is rolled back, including the decision row the recorder wrote
        assert case.reviewed == []
    # nothing past the missing port ran: with no validation the decision is not even recorded
    case = review_case(receipt, answers, validation=False)
    with pytest.raises(ContractError):
        case.adapter.review(case.lease)
    assert case.decisions.calls == [] and case.notices.calls == []


@pytest.mark.parametrize("receipt, answers", [(BLOCKED, ()), (PASSED, ({"accepted": False, "inspection_blocked": True},))],
                         ids=["blocked-inspection", "model-reported-block"])
def test_the_wired_blocked_review_validates_records_and_notifies_in_one_transaction(receipt, answers):
    case = review_case(receipt, answers)
    current = case.adapter.review(case.lease)
    assert current["status"] == "inspection_blocked" and case.validator.calls == [("validate", "d1")]
    assert case.decisions.calls == [("record", True)] and case.notices.calls == [("record", True)]


def test_the_succeeded_review_needs_decisions_but_not_notices_and_does_not_validate():
    answers = ({"accepted": True, **ASSESSMENTS},)
    case = review_case(PASSED, answers, notices=False, validation=False)
    current = case.adapter.review(case.lease)
    assert current["status"] == "succeeded" and len(case.reviewed) == 1 and case.reviewed[0].accepted is True
    assert case.decisions.calls == [("record", True)] and case.validator.calls == []
    case = review_case(PASSED, answers, decisions=False)
    before = digest_of(case.store)
    with pytest.raises(ContractError, match=DECISIONS):
        case.adapter.review(case.lease)
    assert digest_of(case.store) == before and len(case.reviewed) == 1   # the review itself ran before the final record


def test_r_ae2_the_workflow_is_the_composed_audits_workflow_and_the_executor_has_none():
    store, heartbeats, owned = MemoryStore(), [], []
    with store.transaction() as tx:
        tx.put("research_discoveries", "disc-1", {"id": "disc-1"})
    workflow = SimpleNamespace(heartbeat=lambda task: heartbeats.append(task["id"]), _owned=lambda tx, task: owned.append(task["id"]))
    audits = SimpleNamespace(store=store, workflow=workflow)
    calls = []

    def run(agent, key, objective, evidence, cwd, schema, read_only, **kwargs):
        calls.append((agent, key, cwd, read_only, sorted(kwargs)))
        kwargs["heartbeat"]()
        return {"repository": "fixture/repo", "reason": "r", "execution_ref": "sha256:" + "b" * 64}
    executor = SimpleNamespace(git=SimpleNamespace(repository="/repository"), _run=run,
                               research=SimpleNamespace(github_detail=lambda repository: {"url": "https://github.com/fixture/repo", "revision": "d" * 40}))
    assert not hasattr(executor, "workflow") and not hasattr(executor, "service")
    task = {"id": "t1", "agent": "worker:github", "message": {"what": {"action": "audit_discovery", "details": {"discovery_id": "disc-1"}}}}
    row = ae.AuditExecution(executor, None, audits=audits).execute(task)
    assert row["status"] == "discovered_not_reviewed" and heartbeats == ["t1"] and owned == ["t1"]
    assert calls == [("worker:github", "t1", "/repository", True, ["heartbeat", "lease", "stage", "workload"])]
    with store.transaction() as tx:
        assert tx.get("research_backlog", row["id"]) == row


# ----- audit_runner: the rules restated by hand ---------------------------------------------------------------------------------------------
def ar_expected_class():
    """M7's `AuditRunner` with R-au1..R-au3 applied textually: an independent statement of the rules."""
    import re
    t = m7_text(AR_M7)
    t = replaced(t, "    def __init__(self, root, artifacts, host_execution=False):\n", "    def __init__(self, root, artifacts, host_execution=False, *, processes=None, run_process=None, classify=None):\n", 1)
    t = replaced(t, "        self.root.mkdir(parents=True, exist_ok=True)\n\n    def execute_assigned",
                 "        self.root.mkdir(parents=True, exist_ok=True)\n        self.processes, self.run_process, self.classify = processes, run_process, classify\n\n    def execute_assigned", 1)
    t = replaced(t, "from codex_harness.adapters.source_execution import SourceExecutionClient", "from codex_harness.research.adapters.source_execution import SourceExecutionClient", 1)
    t = replaced(t, "    def acquire(self, repository, commit):\n", "    def acquire(self, repository, commit):\n        require(self.processes is not None, 'processes is not wired')\n", 1)
    assert len(re.findall(r",\s+\*\*no_console_kwargs\(\)", t)) == 3
    t = re.sub(r",\s+\*\*no_console_kwargs\(\)", "", t)
    t = replaced(t, "subprocess.run(", "self.processes.run(", 3)
    t = replaced(t, "GitSourceVerifier(target, self.artifacts)", "GitSourceVerifier(target, self.artifacts, processes=self.processes)", 1)
    t = replaced(t, "    def execute(self, source, command):\n", "    def execute(self, source, command):\n        require(self.run_process is not None, 'run_process is not wired')\n"
                                                           "        require(self.classify is not None, 'classify is not wired')\n", 1)
    t = replaced(t, "result = run_process(", "result = self.run_process(", 1)
    t = replaced(t, "verdict = classify_isolated_run(", "verdict = self.classify(", 1)
    return class_of(t, "AuditRunner")


def test_audit_runner_is_m7s_modulo_the_v29_rules():
    ours, theirs = statements(text_of(ar)), statements(m7_text(AR_M7))
    assert list(ours) == list(theirs) == ["AuditRunner"]
    assert ast.dump(ours["AuditRunner"]) == ast.dump(ar_expected_class())


def test_audit_runner_spawns_nothing_itself_and_writes_no_bucket():
    text = text_of(ar)
    assert spawn_calls(text) == []
    code = {n.id for n in ast.walk(ast.parse(text)) if isinstance(n, ast.Name)}
    assert not ({"no_console_kwargs", "classify_isolated_run"} & code)
    assert put_buckets(text) == []
    assert "subprocess.TimeoutExpired" in text   # the stdlib type the isolated run's `except` names stays
    names = {n.id for n in ast.walk(class_of(text, "AuditRunner")) if isinstance(n, ast.Name)}
    assert "run_process" not in {n.func.id for n in ast.walk(class_of(text, "AuditRunner")) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "classify" not in {n.func.id for n in ast.walk(class_of(text, "AuditRunner")) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "GitSourceVerifier" in names


def test_audit_runner_import_homes_header_and_ports():
    text = text_of(ar)
    assert import_modules(text) == ["__future__", "codex_harness.kernel.errors", "codex_harness.kernel.ids", "codex_harness.kernel.policy",
                                    "codex_harness.research.adapters.source_execution", "codex_harness.research.adapters.source_verification",
                                    "codex_harness.research.domain.research", "dataclasses", "filelock", "pathlib"]
    doc = ast.get_docstring(ast.parse(text))
    assert "Layer: adapters\nContext: research\n" in doc and "Contracts: INV-RESEARCH-001, INV-RESEARCH-002, INV-RESEARCH-003" in doc
    assert all(rule in doc for rule in ("R-au0", "R-au1", "R-au2", "R-au3"))
    parameters = inspect.signature(ar.AuditRunner.__init__).parameters
    assert [(p.name, p.kind.name, p.default) for p in parameters.values()] == [
        ("self", "POSITIONAL_OR_KEYWORD", inspect.Parameter.empty), ("root", "POSITIONAL_OR_KEYWORD", inspect.Parameter.empty),
        ("artifacts", "POSITIONAL_OR_KEYWORD", inspect.Parameter.empty), ("host_execution", "POSITIONAL_OR_KEYWORD", False),
        ("processes", "KEYWORD_ONLY", None), ("run_process", "KEYWORD_ONLY", None), ("classify", "KEYWORD_ONLY", None)]


def test_the_lazy_host_client_is_the_research_source_execution_client():
    from codex_harness.research.adapters import source_execution
    assert hasattr(source_execution, "SourceExecutionClient")


# ----- audit_runner: behaviour of the injected ports -------------------------------------------------------------------------------------------
class Stop(Exception):
    pass


class Processes:
    """A `processes` port stub: answers the three acquire spawns, then stops the flow at the verifier's first Git call."""

    def __init__(self):
        self.calls = []

    def run(self, argv, **kwargs):
        self.calls.append((list(argv), kwargs))
        if len(self.calls) > 3:
            raise Stop
        return subprocess.CompletedProcess(argv, 0, b"", b"")


REPOSITORY = "https://github.com/fixture/repo"
COMMIT = "1" * 40


def test_acquire_without_processes_is_refused_before_the_directory_the_lock_or_any_spawn(tmp_path):
    root = tmp_path / "runner"
    runner = ar.AuditRunner(root, None)
    assert list(root.iterdir()) == []
    for repository, commit in ((REPOSITORY, COMMIT), ("not a repository", "bad")):   # the port is the FIRST check, even before the identity's
        with pytest.raises(ContractError, match="processes is not wired"):
            runner.acquire(repository, commit)
        assert list(root.iterdir()) == []   # no target directory and no `.lock` file


def test_acquire_with_processes_validates_first_and_spawns_only_through_the_port(tmp_path):
    processes = Processes()
    runner = ar.AuditRunner(tmp_path / "runner", None, processes=processes)
    with pytest.raises(ContractError, match="Noncanonical repository identity"):
        runner.acquire("https://evil.example/o/r", COMMIT)
    assert processes.calls == [] and list((tmp_path / "runner").iterdir()) == []
    with pytest.raises(Stop):
        runner.acquire(REPOSITORY, COMMIT)
    target = str(next(p for p in (tmp_path / "runner").iterdir() if p.is_dir()))
    argvs = [c[0] for c in processes.calls]
    assert argvs[0] == ["git", "init", "--bare", target]
    assert argvs[1] == ["git", "-C", target, "remote", "add", "origin", REPOSITORY]
    assert argvs[2] == ["git", "-C", target, "cat-file", "-e", COMMIT + "^{commit}"]
    # the same keyword arguments as M7 minus the no-console keywords, which the port applies
    assert [c[1] for c in processes.calls[:3]] == [{"check": True, "capture_output": True}, {"check": True, "capture_output": True},
                                                  {"capture_output": True, "timeout": 30}]
    # the verifier is built with the same port: its first Git call is the fourth spawn
    assert argvs[3][:4] == ["git", "--no-replace-objects", "-C", target] and processes.calls[3][1]["timeout"] == 60 and len(argvs) == 4


@pytest.mark.parametrize("ports, message", [({}, "run_process is not wired"), ({"classify": lambda **kwargs: {}}, "run_process is not wired"),
                                            ({"run_process": lambda argv, timeout: None}, "classify is not wired")])
def test_execute_without_run_process_or_classify_is_refused_before_any_staging(tmp_path, ports, message):
    root = tmp_path / "runner"
    runner = ar.AuditRunner(root, None, **ports)   # artifacts None: reaching the manifest read would be an AttributeError
    for command in (["find", "."], ["source-list"], []):   # the head check precedes even the command validation and the inert built-ins
        with pytest.raises(ContractError, match=message):
            runner.execute(SimpleNamespace(manifest_ref="sha256:" + "0" * 64), command)
    assert [p.name for p in root.iterdir()] == []   # no staging directory


def test_execute_with_both_ports_reaches_the_command_validation(tmp_path):
    runner = ar.AuditRunner(tmp_path / "runner", None, run_process=lambda argv, timeout: None, classify=lambda **kwargs: {})
    with pytest.raises(ContractError, match="Invalid inspection command"):
        runner.execute(SimpleNamespace(), [])


# ----- audit_repair: replay_decode alone (DESIGN-s8 §28.1 R-rd1) ----------------------------------------------------------------------------
RD_M7 = "src/codex_harness/adapters/audit_repair.py"


def test_r_rd1_the_module_holds_replay_decode_verbatim_and_nothing_else():
    from codex_harness.research.adapters import audit_repair as rd
    text = text_of(rd)
    ours, theirs = statements(text), statements(m7_text(RD_M7))
    assert list(ours) == ["__all__", "replay_decode"] and list(theirs) == ["__all__", "replay_decode", "build_repair"]
    assert ast.literal_eval(ours["__all__"].value) == ["replay_decode"]
    expected = ast.parse(m7_text(RD_M7).replace("from codex_harness.adapters.audit_execution import AuditExecution",
                                                "from codex_harness.research.adapters.audit_execution import AuditExecution")).body
    function = next(n for n in expected if isinstance(n, ast.FunctionDef) and n.name == "replay_decode")
    assert ast.dump(ours["replay_decode"]) == ast.dump(function)
    code = {n.id for n in ast.walk(ast.parse(text)) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(ast.parse(text)) if isinstance(n, ast.Attribute)}
    assert not ({"build_repair", "AuditRepair", "FileArtifacts", "runtime_dir"} & code)
    assert import_modules(text) == ["__future__", "codex_harness.kernel.errors", "codex_harness.kernel.ids", "codex_harness.research.adapters.audit_execution",
                                    "codex_harness.research.domain.research"]
    doc = ast.get_docstring(ast.parse(text))
    assert "Layer: adapters\nContext: research\n" in doc and "Contracts: INV-AUDIT-REPAIR-001" in doc and "R-rd1" in doc
    assert spawn_calls(text) == [] and put_buckets(text) == []


def test_replay_decode_is_the_moved_pure_decode_and_returns_only_a_type_and_a_digest():
    from codex_harness.kernel.ids import digest
    from codex_harness.research.adapters.audit_repair import replay_decode
    part = {"audit_id": "a", "partition_id": "p", "generation": 0, "paths": ["cGF0aA=="], "subsystems": [], "evidence_refs": [], "remaining_paths": ["cGF0aA=="],
            "remaining_subsystems": [], "open_questions": [], "cursor": "start", "version": 1}
    refused = replay_decode(part, {"paths": {"Zm9yZWlnbg==": None}, "subsystems": {}, "open_questions": [], "cursor": "c"})
    assert refused == {"refused": True, "error_type": "ContractError", "error_digest": digest("Assigned output identities changed")}
    assert replay_decode(part, {"paths": {"cGF0aA==": None}, "subsystems": {}, "open_questions": [], "cursor": "c"}) == {
        "refused": False, "error_type": None, "error_digest": None}
    with pytest.raises(ContractError):   # an invalid trusted partition is raised, not returned as a diagnosis
        replay_decode({**part, "cursor": ""}, {})
