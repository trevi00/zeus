"""The `zeus` CLI composition: the ticket and sdd builders (the PREP-S10 composition.cli ticket/sdd builders).

Layer: composition
Owns: tickets, ticket_lifecycle, github_tickets, sdd, read_spec, device_probe, and the file-boundary names the two roots use (load_json, parse_json, write_export, render_review, replay_source, render_ticket_review, runtime_artifacts)
Does not own: any root's argument shape or body (entry.cli.ticket, entry.cli.sdd) and the executor wiring of `ticket dispatch` (S10 unit C5, R-c9)
Entry points: tickets, ticket_lifecycle, github_tickets, sdd, read_spec, device_probe, runtime_artifacts
Contracts: none

Replaces the constructions of M7 `cli.py` `ticket_command` (SOURCE e38aa722:411-446), `adapters/ticket_cli.py:13-19` (`build_lifecycle`) and `adapters/sdd_cli.py:62-69`.
Each builder mirrors the shim that wires the same object for the ported M7 suites: `tickets` is `tests/ported/m7_intake.Tickets` (the outbox port),
`github_tickets` is `m7_intake.GitHubTickets` and `ticket_lifecycle`'s authority is `m7_intake.TicketAuthority` (both with `process_groups.run_process`),
`sdd` is `m7_evidence.SDD` / `m7_review.SDD` (intake's `ticket_binding` and the system clock, R-sdd1/R-sdd2), and `read_spec` / `device_probe` bind
the keyword-only `root` and `run_process` ports of `review.adapters.sdd` (R-sd1, R-sd2) as `m7_review` does, `root` resolved per call as M7 did.
The file-boundary names are the target homes of M7's `adapters.sdd` (`load_json`, `write_export`, `render_review`, `replay_source`),
`adapters.ticket_review`; `artifacts` is `composition.cli.artifacts` (M7 `adapters.artifacts.FileArtifacts`). `ticket_lifecycle` is M7 `build_lifecycle` verbatim with the injected `TicketAuthority`.
"""

from codex_harness.composition.cli import artifacts
from codex_harness.intake.adapters.ticket_review import render_ticket_review as render_ticket_review
from codex_harness.kernel.strict_json import parse_json as parse_json
from codex_harness.review.adapters.sdd import load_json as load_json
from codex_harness.review.adapters.sdd import render_review as render_review
from codex_harness.review.adapters.sdd import replay_source as replay_source
from codex_harness.review.adapters.sdd import write_export as write_export


def tickets(service):
    """The Tickets of `service`, wired as `tests/ported/m7_intake.Tickets` wires it (M7 `Tickets(store, org)`)."""
    from codex_harness.coordination.application.outbox import Outbox
    from codex_harness.intake.application.tickets import Tickets
    return Tickets(service.store, service.org, outbox=Outbox())


def runtime_artifacts():
    """The artifact store of the runtime directory (M7 `FileArtifacts(runtime_dir() / "artifacts")`)."""
    from codex_harness.composition.configuration import runtime_dir
    return artifacts(runtime_dir() / "artifacts")


def ticket_lifecycle(tickets):
    """M7 `ticket_cli.build_lifecycle` verbatim, with the `TicketAuthority` of `tests/ported/m7_intake.TicketAuthority`
    (the keyword-only `run_process` port; no trust commit argument, as M7 passed none)."""
    from codex_harness.composition.configuration import repository_root, runtime_dir
    from codex_harness.host_os.adapters import process_groups
    from codex_harness.host_os.adapters.git_workspace import GitWorkspace
    from codex_harness.intake.adapters.ticket_authority import TicketAuthority
    from codex_harness.intake.application.ticket_lifecycle import TicketLifecycle
    runtime = runtime_dir()
    store = artifacts(runtime / "artifacts")
    git = GitWorkspace(str(repository_root()), str(runtime / "workspaces"))
    return TicketLifecycle(tickets, store, TicketAuthority(git, store, run_process=process_groups.run_process))


def github_tickets(tickets, lifecycle):
    """The GitHubTickets over `lifecycle.artifacts`, wired as `tests/ported/m7_intake.GitHubTickets` wires it (the real `run_process`)."""
    from codex_harness.host_os.adapters import process_groups
    from codex_harness.intake.adapters.github_tickets import GitHubTickets
    return GitHubTickets(tickets, lifecycle.artifacts, lifecycle, run_process=process_groups.run_process)


def sdd(service):
    """The SDD of `service` over the runtime artifact store, wired as `tests/ported/m7_review.SDD` wires it (M7
    `SDD(build().store, FileArtifacts(runtime_dir() / "artifacts"))`)."""
    from codex_harness.intake.application.tickets import ticket_binding
    from codex_harness.kernel.ids import SYSTEM_CLOCK
    from codex_harness.review.application.sdd import SDD
    return SDD(service.store, runtime_artifacts(), ticket_binding=ticket_binding, clock=SYSTEM_CLOCK)


def read_spec(path, revision=None):
    """`review.adapters.sdd.read_spec` with `root` and `run_process` bound (R-sd1); the root is resolved at the call."""
    from codex_harness.composition.configuration import repository_root
    from codex_harness.host_os.adapters import process_groups
    from codex_harness.review.adapters import sdd as adapter
    return adapter.read_spec(path, revision, root=repository_root(), run_process=process_groups.run_process)


def device_probe(run_process=None):
    """`review.adapters.sdd.device_probe` with `run_process` bound (R-sd2); `run_process` is injectable for tests."""
    from codex_harness.host_os.adapters import process_groups
    from codex_harness.review.adapters import sdd as adapter
    return adapter.device_probe(run_process=run_process or process_groups.run_process)
