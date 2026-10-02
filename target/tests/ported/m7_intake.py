"""M7 intake surface (tickets, GitHub tickets, ticket lifecycle, front desk) over the S8 target, for the ported M7 suites
`test_tickets`, `test_ticket_execution`, `test_ticket_review`, `test_github_tickets`, `test_ticket_lifecycle` and
`test_frontdesk`.

Layer: harness (never shipped). A TEST shim: it lets those M7 suites run, with their assertions unchanged, against the
moved intake objects as `compare/drivers/target/s8_tickets.py`, `s8_github_tickets.py`, `s8_ticket_lifecycle.py`,
`s8_ticket_authority.py`, `s8_frontdesk.py` and `s8_frontdesk_adapter.py` build them. Ids and clocks are NOT scripted
here: as in M7 the real clock and uuid4 are used (the kernel's SYSTEM_CLOCK / SYSTEM_IDS, the modules' own `uuid4`).

Named adaptations (each is a construction/import/patch-target adaptation, never a behaviour change):
- `Tickets(store, organization)` is the moved class with its one injected port (R-tk2): coordination's `Outbox()`.
- `GitHubTickets(tickets, artifacts, lifecycle=None)` is the moved class with the production `run_process` injected
  (R-gh1: `host_os.adapters.process_groups.run_process`, the shape of M7's `adapters.commands.run_process`); the clock
  is the default (the kernel's system clock). Every case that reaches `gh` replaces `_call`, as in M7.
- `TicketAuthority(git, artifacts, trust_commit=None)` is the moved class with the same `run_process` injected (R-ta1);
  `run_process` stands for M7 `adapters.commands.run_process` (`process_groups.run_process`); `GitWorkspace` is
  `host_os.adapters.git_workspace.GitWorkspace`.
- `github_tickets` stands for the module M7 cases patch (`codex_harness.adapters.github_tickets`): a facade over
  `intake.adapters.github_tickets`. A name reads from the module and an assignment lands on the module, so the module's
  own calls see it (`datetime`, the lease clock). M7's module read the process clock through a zero-argument `utcnow`;
  the moved module calls `utcnow(self.clock)` (R-gh1), so an assignment of `utcnow` installs the zero-argument callable
  behind a wrapper that ignores the clock argument, and reads give the callable back. The patch target is written
  `m7_intake.github_tickets.utcnow`.
- `Executor` is `m7_executor.Executor` with M7's evidence gate wired (`m7_executor` leaves it unwired, S8): M7's
  `Executor.evidence` is `EvidenceInspections(store, EvidenceInspector(artifacts))` (the legacy inspector: no project
  profile, no isolation), the target's `evidence.application.evidence_inspection.EvidenceInspections` over
  `evidence.adapters.evidence_inspection.EvidenceInspector` with `process_tree=ProcessTree` injected (E-4c), and
  `_inspect_evidence` is M7's method over it: the claims, the lease-bound `LeaseProgress` and ownership guard, the same
  `inspection_error` result for a failed inspection and the same `{inspection_id, verdict, denominator}` row. M7's two
  observation events around the inspection are not re-emitted (no ported suite of this batch asserts them). M7's
  `Executor.workflow` held `handle`, `cancel`, `request_rebase` and `context` too: `executor.workflow` is the same
  coordination Workflow with those four names routed to the S5 `MessageHandler` over it (as `m7_coordination.Workflow`).
  `executor.releases` (and the one the decisions use) is `m7_delivery.Releases`: the review `Releases` with intake's
  `ticket_binding`/`TicketSuperseded`, the event journal and the hook rollback injected, as composition wires it
  (`m7_executor` builds it with the binding alone, and `verify`/`promote` need the other ports).
- `Harness(store, org)` is `m7_coordination.Harness` (`.store`, `.org`, and the `.flusher` the moved `DeskRunner`
  flushes through, R-d2); `Workflow(store, org)` is `m7_coordination.Workflow`; `Releases(store, org)` is
  `m7_delivery.Releases`; `Executor`/`ReleaseRunner` are `m7_executor.Executor`/`m7_delivery.ReleaseRunner` (the ported
  suites import them from there); `organization()` is the packaged organization.
- `FrontDesk(service, base_revision, ...)` is the moved class with its outbox port wired (R-f1: coordination's `Outbox()`),
  a subclass as in the golden driver. `DeskRunner`, `LEAD`, `BUCKET_REQUESTS` and `message_id_of` are the moved names, and
  `SUMMARY_TURNS` is the runner's; `desk_domain`, `DeskRefused`, `prior_turns` and `validate_answer` are
  `intake.domain.frontdesk`; `validate_message` is `storage.adapters.message_schema.validate_message`.
- The M7 `adapters.frontdesk` module is split by owner (V17 P-b): `frontdesk_adapter` is a facade over the monitoring side
  (`observation.adapters.desk_monitoring`: `monitoring_facts`, `monitoring_evidence`, `ACCOUNTING_NOTE`,
  `MONITORING_AUTHORITY`, `FRESH_SECONDS`, `MONITORING_MAX_BYTES`, an assignment of a constant lands there) and the execute
  side (`intake.adapters.frontdesk`: `execute_frontdesk`, `DESK_OUTPUT`). The moved `execute_frontdesk` REQUIRES the
  monitoring evidence as `snapshot` (R-f1); M7's read the runtime capture when it was None, so the shim's wrapper supplies
  it exactly as composition passes it: `monitoring_evidence(snapshot_path())`, where `snapshot_path()` is
  `composition.configuration.runtime_dir() / MONITORING_FILE` (M7's body of `snapshot_path`). A case may replace
  `snapshot_path` on the facade, as M7 cases patched it on the module. `readiness` is
  `observation.adapters.monitoring_readiness.readiness`; `completed_output` is `execution.adapters.execution_output`'s.
- The operator CLIs (`cli`, `ticket_cli`, `frontdesk_cli`) and `bootstrap` are NOT here (S10): only tests skipped whole,
  with the owning slice, name them.
"""

from __future__ import annotations

from m7_coordination import Harness, Workflow, organization  # noqa: F401
from m7_delivery import ReleaseRunner, Releases  # noqa: F401
from m7_executor import Executor as _Executor

from codex_harness.composition import configuration
from codex_harness.coordination.application.desk_runner import SUMMARY_TURNS, DeskRunner  # noqa: F401
from codex_harness.coordination.application.messages import MessageHandler
from codex_harness.coordination.application.outbox import Outbox
from codex_harness.coordination.application.workflow import ClaimGuardRefused  # noqa: F401
from codex_harness.evidence.adapters.evidence_inspection import EvidenceInspector
from codex_harness.evidence.application.evidence_inspection import EvidenceInspections
from codex_harness.execution.adapters.execution_output import completed_output  # noqa: F401
from codex_harness.execution.application.lease_progress import LeaseProgress
from codex_harness.host_os.adapters import process_groups
from codex_harness.host_os.adapters.git_workspace import GitWorkspace  # noqa: F401
from codex_harness.host_os.adapters.process_tree import ProcessTree
from codex_harness.intake.adapters import frontdesk as _execute_side
from codex_harness.intake.adapters import github_tickets as _github_module
from codex_harness.intake.adapters import ticket_authority as _authority
from codex_harness.intake.adapters.frontdesk import DESK_OUTPUT  # noqa: F401
from codex_harness.intake.adapters.ticket_review import render_ticket_review  # noqa: F401
from codex_harness.intake.application import frontdesk as _application
from codex_harness.intake.application import ticket_lifecycle as application_ticket_lifecycle  # noqa: F401
from codex_harness.intake.application import tickets as _tickets
from codex_harness.intake.application.frontdesk import BUCKET_REQUESTS, LEAD, message_id_of  # noqa: F401
from codex_harness.intake.application.ticket_lifecycle import TicketLifecycle  # noqa: F401
from codex_harness.intake.application.tickets import (  # noqa: F401
    TicketClosed,
    TicketSuperseded,
    render_ticket,
    ticket_binding,
)
from codex_harness.intake.domain import frontdesk as desk_domain  # noqa: F401
from codex_harness.intake.domain import ticket_lifecycle as domain_ticket_lifecycle  # noqa: F401
from codex_harness.intake.domain.frontdesk import DeskRefused, prior_turns, validate_answer  # noqa: F401
from codex_harness.kernel.errors import ContractError  # noqa: F401
from codex_harness.kernel.ids import canonical, digest, utcnow  # noqa: F401
from codex_harness.observation.adapters import desk_monitoring as _monitoring_side
from codex_harness.observation.adapters.desk_monitoring import (  # noqa: F401
    ACCOUNTING_NOTE,
    monitoring_evidence,
    monitoring_facts,
)
from codex_harness.observation.adapters.monitoring_readiness import readiness  # noqa: F401
from codex_harness.storage.adapters.file_artifacts import FileArtifacts  # noqa: F401
from codex_harness.storage.adapters.memory_store import MemoryStore, MemoryTransaction  # noqa: F401
from codex_harness.storage.adapters.message_schema import validate_message  # noqa: F401


def Tickets(store, org):  # noqa: N802 - the M7 constructor name
    return _tickets.Tickets(store, org, outbox=Outbox())


def GitHubTickets(tickets, artifacts, lifecycle=None):  # noqa: N802 - the M7 constructor name
    return _github_module.GitHubTickets(tickets, artifacts, lifecycle, run_process=process_groups.run_process)


def TicketAuthority(git, artifacts, trust_commit=None):  # noqa: N802 - the M7 constructor name
    return _authority.TicketAuthority(git, artifacts, trust_commit, run_process=process_groups.run_process)


run_process = process_groups.run_process


class _Facade:
    """A module as the M7 suites saw it: names read from the moved module(s), assignments land on the module that owns
    the name (`own`: name -> a replacing holder, for a name the shim rewraps)."""

    def __init__(self, *modules, **own):
        object.__setattr__(self, "_modules", modules)
        object.__setattr__(self, "_own", own)

    def _owner(self, name):
        for module in object.__getattribute__(self, "_modules"):
            if hasattr(module, name):
                return module
        raise AttributeError(name)

    def __getattr__(self, name):
        own = object.__getattribute__(self, "_own")
        if name in own:
            return own[name]
        return getattr(self._owner(name), name)

    def __setattr__(self, name, value):
        own = object.__getattribute__(self, "_own")
        if name in own:
            own[name] = value
        else:
            setattr(self._owner(name), name, value)


_MODULE_UTCNOW = _github_module.utcnow  # the moved module's own function (module-level: a class attribute would bind)


class _GitHubTicketsModule(_Facade):
    """`utcnow` is M7's zero-argument process clock; the moved module calls `utcnow(self.clock)` (R-gh1)."""

    def __getattr__(self, name):
        value = super().__getattr__(name)
        return getattr(value, "__wrapped__", value) if name == "utcnow" else value

    def __setattr__(self, name, value):
        if name == "utcnow" and value is not _MODULE_UTCNOW:
            zero_argument = value

            def wrapper(clock=None):
                return zero_argument()
            wrapper.__wrapped__ = zero_argument
            value = wrapper
        super().__setattr__(name, value)


github_tickets = _GitHubTicketsModule(_github_module)


def snapshot_path():
    """M7 `adapters.frontdesk.snapshot_path`: the owner-runtime capture beside the runtime directory."""
    return configuration.runtime_dir() / _monitoring_side.MONITORING_FILE


def execute_frontdesk(executor, task, heartbeat=None, snapshot=None):
    """The moved helper with the evidence supplied as composition supplies it (V17 R-f1)."""
    if snapshot is None:
        snapshot = _monitoring_side.monitoring_evidence(frontdesk_adapter.snapshot_path())
    return _execute_side.execute_frontdesk(executor, task, heartbeat, snapshot)


frontdesk_adapter = _Facade(_monitoring_side, _execute_side, snapshot_path=snapshot_path,
                            execute_frontdesk=execute_frontdesk)


class FrontDesk(_application.FrontDesk):
    """The moved class with its outbox port wired (a subclass: the cases build it from the service and revision)."""

    def __init__(self, service, base_revision, *args, **kwargs):
        super().__init__(service, base_revision, *args, outbox=Outbox(), **kwargs)


class _Messaging:
    """A coordination Workflow with M7's message names routed to the MessageHandler over it."""

    MESSAGE_METHODS = ("handle", "cancel", "request_rebase", "context")

    def __init__(self, workflow):
        self.workflow, self.messages = workflow, MessageHandler(workflow)

    def __getattr__(self, name):
        return getattr(self.messages if name in self.MESSAGE_METHODS else self.workflow, name)


class Executor(_Executor):
    """`m7_executor.Executor` with the evidence gate wired as M7 built it (legacy inspector)."""

    def __init__(self, service, git, artifacts, *args, **kwargs):
        super().__init__(service, git, artifacts, *args, **kwargs)
        self.evidence = EvidenceInspections(service.store, EvidenceInspector(artifacts, process_tree=ProcessTree))
        self.workflow = _Messaging(self.workflow)
        self.releases = self.decisions.releases = Releases(service.store, service.org)

    def _inspect_evidence(self, task, result, workspace_path, heartbeat=None):
        claims = result.get("tests") if isinstance(result.get("tests"), list) else []
        progress = LeaseProgress(self.workflow, task, heartbeat=heartbeat)
        ownership_refusals = []

        def guard(tx):
            try:
                return self.workflow._owned(tx, task)
            except BaseException as exc:
                ownership_refusals.append(exc)
                raise
        try:
            row = self.evidence.inspect(task, result["candidate"], claims, workspace_path, progress=progress,
                                        guard=guard)
        except Exception as exc:
            error_type, message_sha256 = type(exc).__name__, digest(str(exc))[:16]
            if progress.refusal is exc or any(exc is refusal for refusal in ownership_refusals):
                raise
            return {"verdict": "inspection_error", "cause": error_type + ": message_sha256=" + message_sha256,
                    "claims": len(claims)}
        return {"inspection_id": row["id"], "verdict": row["verdict"], "denominator": row["denominator"]}
