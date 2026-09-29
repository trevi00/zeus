"""M7 `Executor` surface over the S4 composition, for the ported executor-level M7 suites.

Layer: harness (never shipped). A TEST shim: it lets the M7 tests that drive `Executor` run, with their
assertions unchanged, against `RunTask` (execution) and `ReviewDecisions` (review) as composition will
build them (S10). The wiring mirrors `compare/drivers/target/s4_run_task_composition.py` (RunTask) and
`s4_decision_composition.py` (ReviewDecisions); ids and clocks are NOT scripted here: as in M7 the real
clock and uuid4 are used (SYSTEM_IDS / SYSTEM_CLOCK).

Named adaptations (each is a construction/patch-point adaptation, never a behaviour change):
- `Service(store, org)` stands in for M7's `Harness(store, organization())` where a test only used it as the
  carrier of `.store` and `.org` (the target `packaged_organization()` by default).
- `AppServer` and `ClaudeCodeRuntime` are module-level names looked up AT OPEN TIME: a test replaces them with
  `monkeypatch.setattr("m7_executor.AppServer", ...)`, the adapted form of M7's
  `"codex_harness.adapters.executor.AppServer"`. The defaults are the target Claude transport with its host
  facilities injected (the `ClaudeHost` below, with observation's real `redact_text`) and an App Server that
  raises AssertionError (an unstubbed host Codex would be a real provider call).
- `execution_policy` is built on first use from the alias-normalized environment (M7
  `adapters/configuration.settings()` without the repository .env) through the target
  `routing.adapters.provider_policy.host_policy`, so `monkeypatch.setenv` before the first run still routes and
  `executor._execution_policy = None` re-reads the environment.
- `_run` and `_inspect_evidence` are methods of the shim: RunTask's own `_run` and the review invoker call
  through them, so `monkeypatch.setattr(executor, "_run", ...)` works as it did in M7. `_inspect_evidence` raises
  ContractError (S8 evidence inspection is not wired).
- An isolation object without `summary()`/`review_context()` (the M7 tests' stand-ins) is wrapped so the RunTask isolation
  port is met over its `config` (`container_spec.summary`, `owned_container.isolated_review_context`).
- The context composer's threshold source is the packaged definition (`conftest.NATIVE_THRESHOLDS`), as the
  ported S2 suites supply it (research implements that port in S8).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from conftest import NATIVE_THRESHOLDS

from codex_harness.context.adapters import worker_profile
from codex_harness.context.adapters.composition_sources import (
    GitRepository,
    ProjectSkills,
    SkillHistoryRecorder,
)
from codex_harness.context.adapters.review_context import review_context
from codex_harness.context.application.compose import ContextComposer
from codex_harness.coordination.application.breaker import Breaker
from codex_harness.coordination.application.decision_claims import claim_decision
from codex_harness.coordination.application.decision_recovery import release_review_policy
from codex_harness.coordination.application.decisions import DecisionFailures, DecisionOwnership
from codex_harness.coordination.application.events import EventJournal
from codex_harness.coordination.application.execution_records import ExecutionRecords
from codex_harness.coordination.application.execution_recovery import ExecutionRecovery
from codex_harness.coordination.application.invocation_admission import InvocationBreaker
from codex_harness.coordination.application.outbox import Outbox
from codex_harness.coordination.application.sessions import SessionCheckpoints
from codex_harness.coordination.application.task_ownership import TaskOwnership
from codex_harness.coordination.application.workflow import Workflow
from codex_harness.execution.adapters import execution_output, output_schema
from codex_harness.execution.adapters.containers import handoff, owned_container
from codex_harness.execution.adapters.providers import claude_cli
from codex_harness.execution.adapters.providers.claude_cli import claude_settings
from codex_harness.execution.adapters.transports import Transports
from codex_harness.execution.application.invocation_ledger import InvocationLedger
from codex_harness.execution.application.run_task import RunTask
from codex_harness.execution.domain import container_spec
from codex_harness.execution.domain.output_contracts import DIAGNOSIS, VERDICT
from codex_harness.host_os.adapters import process_groups
from codex_harness.host_os.adapters.process_tree import ProcessTree, TreeOwnershipLeak
from codex_harness.intake.application import tickets
from codex_harness.kernel.errors import ContractError
from codex_harness.kernel.ids import SYSTEM_IDS
from codex_harness.observation.adapters.observation_spool import MemorySpool
from codex_harness.observation.application.observations import (
    MemoryDirectory,
    Observer,
    PostExecutionRecordFailure,
    ReconciliationRequired,
)
from codex_harness.observation.domain.observation import redact_text
from codex_harness.research.application.audit_gate import inspect_approval, require_adoption
from codex_harness.research.application.hooks import HookLifecycle
from codex_harness.research.domain.research import require_dispatch
from codex_harness.review.application.decisions import ReviewDecisions
from codex_harness.review.application.releases import Releases
from codex_harness.routing.adapters.organization_source import packaged_organization
from codex_harness.routing.adapters.provider_policy import host_policy

CLAUDE_HOST = claude_cli.ClaudeHost(runner=process_groups.run_process, trees=ProcessTree, tree_leak=TreeOwnershipLeak,
                                    worker_profiles=worker_profile, redact=redact_text)


def AppServer(**kwargs):  # noqa: N802 - the M7 patch-point name
    raise AssertionError("AppServer reached in an M7 executor test without a stub")


def ClaudeCodeRuntime(**kwargs):  # noqa: N802 - the M7 constructor form, adapted: the host is injected
    return claude_cli.ClaudeCodeRuntime(**kwargs, host=CLAUDE_HOST)


def aliases(layer: dict[str, str]) -> dict[str, str]:
    """M7 `adapters/configuration.aliases`, copied: Zeus wins within one layer."""
    result = dict(layer)
    suffixes = {key.split("_", 1)[1] for key in layer if key.startswith(("ZEUS_", "HARNESS_"))}
    for suffix in suffixes:
        value = layer.get("ZEUS_" + suffix, layer.get("HARNESS_" + suffix))
        result["ZEUS_" + suffix] = result["HARNESS_" + suffix] = value
    return result


def no_operations(tx, message):
    """These executions create no operations, so M7 park returns None for every message here (S5 moves park)."""
    return None


class Service:
    """The carrier of `.store` and `.org` (M7 `Harness(store, organization())`)."""

    def __init__(self, store, org=None):
        self.store, self.org = store, org if org is not None else packaged_organization()


class _LazyPolicy:
    """RunTask reads `execution_policy` as an attribute; the shim binds it on first use, as M7 did."""

    def __init__(self, owner):
        self.__dict__["_owner"] = owner

    def __getattr__(self, name):
        return getattr(self._owner.execution_policy, name)


def make_workflow(store, org=None):
    """The coordination Workflow of one composition (submit with the real adoption gate, the park stub)."""
    return Workflow(store, org if org is not None else packaged_organization(),
                    ticket_binding=tickets.ticket_binding, TicketSuperseded=tickets.TicketSuperseded,
                    adoption=require_adoption, park_terminal=no_operations, ids=SYSTEM_IDS)


class _Isolation:
    """RunTask's isolation port over an M7-style isolation object (`config` and its runtimes): at M7 `summary` and
    `review_context` were module functions of the config (`isolated_worker.summary/isolated_review_context`)."""

    def __init__(self, inner):
        self.__dict__["_inner"] = inner

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def summary(self):
        return container_spec.summary(self._inner.config)

    def review_context(self, cwd, profile=None):
        return owned_container.isolated_review_context(cwd, self._inner.config, profile)


class Executor:
    def __init__(self, service, git, artifacts, knowledge=None, research=None, observer=None, execution_policy=None,
                 evidence_profile=None, isolation=None, worker_sessions=None):
        self.service, self.git, self.artifacts = service, git, artifacts
        store, org = service.store, service.org
        self.worker_sessions, self.knowledge, self.research = worker_sessions, knowledge, research
        self._execution_policy = execution_policy
        self.evidence_profile, self.isolation = evidence_profile, isolation
        port = isolation if isolation is None or hasattr(isolation, "summary") else _Isolation(isolation)
        self.observer = observer or Observer(store, MemorySpool(uuid4().hex), component="executor",
                                             directory=MemoryDirectory())
        self.workflow = make_workflow(store, org)
        self.invocations = InvocationLedger(store)
        self.releases = Releases(store, org, ticket_binding=tickets.ticket_binding)
        self.breaker = Breaker(store)
        composer = ContextComposer(artifacts, artifacts.root, GitRepository(git),
                                   ProjectSkills(git, artifacts, NATIVE_THRESHOLDS),
                                   SkillHistoryRecorder(store, artifacts, git), knowledge)
        results = SimpleNamespace(persist=execution_output.persist_result, tool_usage=execution_output.tool_usage,
                                  preflight=output_schema.preflight, handoff_refs=handoff.handoff_refs,
                                  retain_evidence_handoff=handoff.retain_evidence_handoff)
        module = sys.modules[__name__]
        transports = Transports(
            isolation=port, evidence_profile=evidence_profile, claude_settings=claude_settings,
            host_app_server=lambda **kw: module.AppServer(**kw),
            claude_runtime=lambda **kw: module.ClaudeCodeRuntime(**kw), host_hooks=lambda: {})
        interpreter = Path(sys.executable).resolve()
        self.run_task = RunTask(
            store, org, git, artifacts,
            ledger=TaskOwnership(self.workflow, store=store, ids=SYSTEM_IDS),
            admission=InvocationBreaker(self.breaker), invocations=self.invocations,
            sessions=SessionCheckpoints(store, org, workflow=self.workflow, ids=SYSTEM_IDS),
            records=ExecutionRecords(org), observer=self.observer, composer=composer, transports=transports,
            results=results, execution_policy=_LazyPolicy(self),
            review_context=lambda cwd: review_context(cwd, interpreter), host_python=sys.executable,
            ticket_binding=tickets.ticket_binding, inspect_approval=inspect_approval,
            ReconciliationRequired=ReconciliationRequired, PostExecutionRecordFailure=PostExecutionRecordFailure,
            worker_sessions=worker_sessions, isolation=port, evidence_profile=evidence_profile,
            knowledge=knowledge, research=research,
            evidence_gate=SimpleNamespace(inspect=lambda *a, **k: self._inspect_evidence(*a, **k)),
            ids=SYSTEM_IDS)
        # RunTask reaches its own `_run`; route it through the shim so a test's patch of `executor._run` is seen.
        self._run_task_run = self.run_task._run
        self.run_task._run = lambda *a, **k: self._run(*a, **k)
        self.recovery = ExecutionRecovery(store, org, artifacts)
        self.hooks = HookLifecycle(org, outbox=Outbox(), events=EventJournal(), ids=SYSTEM_IDS)
        self.decisions = ReviewDecisions(
            store, org, ownership=DecisionOwnership(self.workflow, self.recovery, org, ids=SYSTEM_IDS),
            failures=DecisionFailures(self.workflow, store), outbox=Outbox(), events=EventJournal(),
            releases=self.releases, hooks=self.hooks, observer=self.observer,
            invoker=SimpleNamespace(invoke=self._invoke), git=git, release_policy=release_review_policy,
            ticket_binding=tickets.ticket_binding, TicketSuperseded=tickets.TicketSuperseded,
            require_dispatch=require_dispatch, ReconciliationRequired=ReconciliationRequired,
            PostExecutionRecordFailure=PostExecutionRecordFailure, worker_sessions=worker_sessions, ids=SYSTEM_IDS)

    @property
    def execution_policy(self):
        """The packaged execution policy bound to this host's configuration (read on first use, as M7)."""
        if self._execution_policy is None:
            self._execution_policy = host_policy({**aliases(dict(os.environ))})
        return self._execution_policy

    def _run(self, *args, **kwargs):
        return self._run_task_run(*args, **kwargs)

    def _invoke(self, agent, task_id, instruction, data, cwd, schema, read_only, **kwargs):
        """The VerdictInvoker port over `_run`: M7 called `_run` with the closed output schema itself."""
        return self._run(agent, task_id, instruction, data, cwd, DIAGNOSIS if schema == "diagnosis" else VERDICT,
                         read_only, **kwargs)

    def _inspect_evidence(self, *args, **kwargs):
        raise ContractError("Evidence inspection is not wired (S8)")

    def execute_one(self, agent, expected=None):
        return self.run_task.execute_one(agent, expected)

    def decide_one(self, agent, expected=None):
        store, org = self.service.store, self.service.org
        owner = str(uuid4())
        decision = claim_decision(store, org, agent, owner, expected, recovery=self.recovery,
                                  ticket_binding=tickets.ticket_binding, TicketSuperseded=tickets.TicketSuperseded)
        if not decision:
            return None
        return self.decisions.decide(agent, decision)
