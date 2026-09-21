"""Wire the EXISTING pure content decoder and the existing artifact store into the bounded repair
owner (INV-AUDIT-REPAIR-001).

There is no second decoder, schema, validator or diagnosis engine here. `replay_decode` runs
`AuditExecution.proposed_checkpoint`, the same pure half of the rejection boundary that refused the
draft in the first place, against the trusted stored partition and the retained answer: it touches
no store, lease, runner, artifact, transport or provider, it repairs, decodes, normalizes and
deduplicates nothing, and it returns only the refusal's TYPE and the digest of its message. The
message itself never leaves this function, so a diagnosis is bound to a validator's identity rather
than to a substring an operator could read in a log.
"""
from __future__ import annotations

from codex_harness.application.audit_repair import AuditRepair
from codex_harness.domain.model import ContractError, digest
from codex_harness.domain.research import PartitionCheckpoint

__all__ = ["build_repair", "replay_decode"]


def replay_decode(partition: dict, answer: dict) -> dict:
    """Replay the pure content decode of ONE retained draft against its trusted assigned scope.

    A refusal returns its type and the digest of its message; a draft that now decodes cleanly
    returns `refused` false, which makes the diagnosis a mismatch rather than an eligibility. Only
    the pure decoder's own refusal can ever be reproduced here: `AuditDraftRejected` from
    `ResearchAudits.checkpoint` is raised inside that method's transaction against trusted records
    and is deliberately not replayable, so its family is never admitted by this owner.
    """
    from codex_harness.adapters.audit_execution import AuditExecution

    trusted = PartitionCheckpoint(**partition)
    trusted.validate()
    try:
        AuditExecution.proposed_checkpoint(trusted, answer)
    except ContractError as rejection:
        return {"refused": True, "error_type": type(rejection).__name__,
                "error_digest": digest(str(rejection))}
    return {"refused": False, "error_type": None, "error_digest": None}


def build_repair(service, artifacts=None, *, replay=replay_decode) -> AuditRepair:
    """The repair owner over this host's existing store, organization and artifact root."""
    if artifacts is None:
        from codex_harness.adapters.artifacts import FileArtifacts
        from codex_harness.adapters.configuration import runtime_dir

        artifacts = FileArtifacts(str(runtime_dir() / "artifacts"))
    return AuditRepair(service.store, service.org, artifacts, replay=replay)
