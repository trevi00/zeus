"""M7 research-subject names over the S8 target, for the ported M7 research suites (DESIGN-s8 §29).

Layer: harness (never shipped). A TEST shim: it lets M7 `tests/test_research_*.py` run, with their assertions unchanged,
against the S8 research target. Ids and clocks are NOT scripted here: as in M7 the real clock and uuid4 are used.

Named adaptations (each is a construction/import adaptation, never a behaviour change):
- `packaged_policy` is `routing.adapters.provider_policy.packaged_policy` (M7 `adapters.providers.packaged_policy`).
- `OwnerActions(store, **ports)` is `m7_coordination.OwnerActions` (the facade over the split objects of
  `coordination.application.owner_actions`, built as the S6 composition builds it, with the SYSTEM clock and ids) with
  four more routes, for the private methods of M7's one class that the scoped-research suite calls, to the split
  homes: `_research_decide`, `_observe_dispatch` and `_discover_research` (the target's `discover`) to the
  scheduler's `research_dispatch` family, `_research_binding` (the target's `research_binding`) to its
  `research_acceptance` family. An unrouted name still raises AttributeError (never a fallback).
- `unavailable(slice_, name)` is `m7_coordination`'s.
- The research domain modules (`research_attempt_scope`, `research_program`, `research_investigations`,
  `audit_progress`, `autonomous`, `council`, `discovery_pressure`) are imported by the ported suites from
  `codex_harness.research.domain`; `continuation` and `owner_actions` from `codex_harness.coordination.domain`;
  `family_id` and the portfolio bucket names from `intake.domain.portfolio`; the owner-action, continuation and research
  bucket names from the `state` modules of their application packages; `digest`/`canonical` from `kernel.ids`;
  `MemoryStore` from `storage.adapters.memory_store`. No M7 name of this batch is without an S8-or-earlier home.

Batch P2 (research program) adds, each a construction/import adaptation:
- `ResearchProgram(store, **kwargs)` is the target class with its three composition ports wired (coordination's
  `ResearchLaunchFacts`, the `execution_fence` module, the `outbox_relay` module), as `compare/drivers/target/
  s8_program_tick.py` builds it, with the SYSTEM clock and uuid4 (the application's own default).
- `GitCapture(repository, ...)` is the target class with host_os's `process_groups.run_process` and `GitSource` wired
  (`composition.research_program_adapters.git_capture`); `ProgramRunner(...)` the target runner with the dge
  `verify_sources` wired (`composition.program_runner`); `GitSource` is `host_os.adapters.git_source.GitSource`.
- `research_program` is a namespace holding the one attribute M7's `adapters.research_program` module global
  `run_process` (host_os's runner); the shim's `GitCapture` reads it at call time, so a test's
  `monkeypatch.setattr(research_program, "run_process", ...)` reaches it as it reached the M7 global.
- `monitoring.research_program_facts(store)` is exactly `ResearchProgram(store).monitor()` (the driver's binding of the
  ledger target `observation.adapters.collectors:research_program_facts`, whose projection is wired by composition).
- `repository_identity(path)` is M7 `adapters.dge_cli.repository_identity` BODY, verbatim (`digest(str(Path(path).resolve()))`),
  a labelled copy: its ledger home `entry.cli.dge` is the S10 CLI module, absent from the target (the precedent is
  `m7_coordination.ResearchEvidence`). It is NOT `coordination.domain.fleet.repository_identity`, whose body differs.
- `SOURCE`, `FAMILY`, `INVESTIGATION`, `DEFINITIONS`, `JOBS` and `portfolio(store, jobs=JOBS)` are M7
  `tests/test_research_investigations.py`'s helper definitions, verbatim, labelled copies: that suite belongs to batch P5
  (not yet ported) and the chain and recovery suites cannot be collected without them (`Portfolio` and `BUCKET_JOBS`
  are the target homes). Batch P5 owns the ported module.
- `organization`, `Harness`, `Workflow`, `relay` are `m7_coordination`'s (M7 `bootstrap.organization`,
  `application.service.Harness`, `application.workflow.Workflow`, `application.outbox.relay`).
- `CouncilRun(service, executor=None, bus=None, workflow=None, budget=None, collector=None, verify_sources=None,
  repository=None, observer=None, clock=utcnow, evidence=None, snapshot=None, artifacts=None)` is the target class with its
  four composition ports (research's `DebateSessions`, evidence's `EvidenceRecords`, knowledge's `promotion`, the S5
  `Operation` over the service as `s8_council.py` builds it), M7's positional arguments unchanged.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from m7_coordination import Harness, Workflow, organization, packaged_policy, relay, unavailable
from m7_coordination import OwnerActions as _OwnerActions

from codex_harness.coordination.application import council as _council
from codex_harness.coordination.application import execution_fence, outbox_relay
from codex_harness.coordination.application.fleet.state import BUCKET_JOBS
from codex_harness.coordination.application.operation import Operation
from codex_harness.coordination.application.research_launch_facts import ResearchLaunchFacts
from codex_harness.evidence.application.inspections import EvidenceRecords
from codex_harness.host_os.adapters import git_source, process_groups
from codex_harness.intake.application.portfolio import Portfolio, family_id
from codex_harness.kernel.ids import SYSTEM_CLOCK, SYSTEM_IDS, digest
from codex_harness.knowledge.application import promotion as knowledge_promotion
from codex_harness.research.adapters import dge_sources
from codex_harness.research.adapters import research_program as _adapter
from codex_harness.research.application import dge
from codex_harness.research.application import research_program as _application

__all__ = ["CouncilRun", "DEFINITIONS", "FAMILY", "GitCapture", "GitSource", "Harness", "INVESTIGATION", "JOBS",
           "OwnerActions", "ProgramRunner", "ResearchProgram", "SOURCE", "Workflow", "monitoring", "organization",
           "packaged_policy", "portfolio", "relay", "repository_identity", "research_program", "unavailable"]

GitSource = git_source.GitSource
research_program = SimpleNamespace(run_process=process_groups.run_process)


class ResearchProgram(_application.ResearchProgram):
    def __init__(self, store, **kwargs):
        super().__init__(store, launch_facts=ResearchLaunchFacts(), fences=execution_fence, outbox_quarantine=outbox_relay,
                         **kwargs)


class GitCapture(_adapter.GitCapture):
    def __init__(self, repository, *args, **kwargs):
        def run_process(*a, **k):  # read at call time, as M7 read its module global
            return research_program.run_process(*a, **k)
        super().__init__(repository, *args, run_process=run_process, git_source=git_source.GitSource, **kwargs)


class ProgramRunner(_adapter.ProgramRunner):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, verify_sources=dge_sources.verify_sources, **kwargs)


monitoring = SimpleNamespace(research_program_facts=lambda store: ResearchProgram(store).monitor())


def repository_identity(repository) -> str:
    """The same resolved-repository digest `operate` records in its identity, so the claim-time
    gate compares like with like; the path itself is never stored."""
    return digest(str(Path(repository).resolve()))


class CouncilRun(_council.CouncilRun):
    def __init__(self, service, *args, **kwargs):
        def operation_factory(executor, bus, workflow, budget, collector, observer=None):
            return Operation(service.store, service.org, flusher=service.flusher, incidents=service.record_incident,
                             executor=executor, bus=bus, workflow=workflow, budget=budget, collector=collector,
                             observer=observer, design_gate=SimpleNamespace(check=dge.design_gate),
                             evidence_records=EvidenceRecords(), clock=SYSTEM_CLOCK, ids=SYSTEM_IDS)
        super().__init__(service, *args, sessions_factory=dge.DebateSessions, evidence_records=EvidenceRecords(),
                         promotion=knowledge_promotion, operation_factory=operation_factory, **kwargs)


# M7 `tests/test_research_investigations.py` helpers, verbatim (labelled copies; see the docstring).
SOURCE = {"topic": "storage", "project_ids": ["ops"], "reason_codes": ["store_timeout"]}
FAMILY = ("failed", "store_timeout")
INVESTIGATION = family_id(*FAMILY)
DEFINITIONS = {"schema": "urn:zeus:portfolio-definitions:1", "projects": [
    {"id": "ops", "title": "Operations", "outcome": "bound fleet work completes", "source_ref": "docs/GOAL.md",
     "criteria": [{"id": "c1", "text": "jobs reach a terminal accepted state"}]},
    {"id": "other", "title": "Other", "outcome": "unrelated work", "source_ref": "docs/GOAL.md",
     "criteria": [{"id": "c1", "text": "unrelated criterion"}]}]}
# (job id, status, reason code, bound project): two distinct qualifying jobs and one same-family job
# bound to a project this program is NOT authorized for.
JOBS = (("j-1", "failed", "store_timeout", "ops"), ("j-2", "failed", "store_timeout", "ops"),
        ("j-3", "failed", "store_timeout", "other"), ("j-4", "rejected", "review_rejected", "ops"))


def portfolio(store, jobs=JOBS) -> Portfolio:
    """LABELLED synthetic Fleet rows (only the fields the reconciler reads) under the REAL portfolio
    reconciler, owner bindings and owner dispositions."""
    from test_research_program_fixtures import BASE_CLOCK
    owner = Portfolio(store, DEFINITIONS, clock=lambda: BASE_CLOCK)
    with store.transaction() as tx:
        for job_id, status, reason, _ in jobs:
            tx.put(BUCKET_JOBS, job_id, {"id": job_id, "lane": "lane-1", "status": status, "reason_code": reason,
                                         "error_type": None, "updated_at": BASE_CLOCK})
    for job_id, _, _, project in jobs:
        owner.bind(job_id, project, "c1")
    owner.reconcile()
    return owner

RESEARCH_PRIVATE = {"_research_decide": ("research_dispatch", "_research_decide"),
                    "_observe_dispatch": ("research_dispatch", "_observe_dispatch"),
                    "_discover_research": ("research_dispatch", "discover"),
                    "_research_binding": ("research_acceptance", "research_binding")}


class OwnerActions(_OwnerActions):
    def __getattr__(self, name):
        route = RESEARCH_PRIVATE.get(name)
        if route is None:
            return super().__getattr__(name)
        return getattr(getattr(self.objects["scheduler"], route[0]), route[1])
