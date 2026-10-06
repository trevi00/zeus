"""The `zeus audit-repair` composition: the repair owner over this host's store and artifact root.

Layer: composition
Owns: build_repair
Does not own: the argument shape and the command body (entry.cli.audit_repair) and the replay itself (research.adapters.audit_repair.replay_decode)
Entry points: build_repair
Contracts: INV-AUDIT-REPAIR-001

Moved from M7 `adapters/audit_repair.py:42-49` (`build_repair`, SOURCE e38aa722) by named rule R-c11 (S10 unit C7a). The body is M7's; the object construction is the target's:
`AuditRepair` takes the keyword-only `outbox`, `events` and `notices` ports (coordination's `Outbox`, `EventJournal` and the `execution_notices` module), as
`tests/ported/m7_research.AuditRepair` and `compare/drivers/target/s8_audit_repair.py` wire it, and `replay_decode` is `research.adapters.audit_repair.replay_decode`.
"""


def build_repair(service, artifacts=None, *, replay=None):
    """The repair owner over this host's existing store, organization and artifact root."""
    from codex_harness.composition.configuration import runtime_dir
    from codex_harness.coordination.application import execution_notices
    from codex_harness.coordination.application.events import EventJournal
    from codex_harness.coordination.application.outbox import Outbox
    from codex_harness.research.adapters.audit_repair import replay_decode
    from codex_harness.research.application.audit_repair import AuditRepair
    from codex_harness.storage.adapters.file_artifacts import FileArtifacts

    if artifacts is None:
        artifacts = FileArtifacts(str(runtime_dir() / "artifacts"))
    return AuditRepair(service.store, service.org, artifacts, replay=replay_decode if replay is None else replay,
                       outbox=Outbox(), events=EventJournal(), notices=execution_notices)
