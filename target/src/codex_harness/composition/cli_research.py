"""The `zeus dge` and `zeus decision-feedback` composition: the git source, the two use cases and the execution evidence reader.

Layer: composition
Owns: git_source, verify_sources, debate_sessions, decision_feedback, execution_evidence, load_registry
Does not own: the argument shape and the command bodies (entry.cli.dge, entry.cli.decision_feedback), the use cases (research.application) and the registry rules (research.adapters.decision_feedback)
Entry points: git_source, verify_sources, debate_sessions, decision_feedback, execution_evidence, load_registry
Contracts: INV-DGE-001, INV-DECISION-FEEDBACK-001

Built from the construction statements of M7 `adapters/dge_cli.py` (`register`: `GitSource(repository)`, `DebateSessions(service.store)`) and `adapters/decision_feedback_cli.py` (`collect` and the
read commands: `GitSource`, `ExecutionEvidence(FileArtifacts(...))`, `DecisionFeedback(service.store, evidence=...)`, `load_registry`; SOURCE e38aa722) by named rule R-c12 (S10 unit C7b), with the target homes
(`host_os.adapters.git_source`, `storage.adapters.file_artifacts`, `research.adapters`). `load_registry` is bound as `compare/drivers/target/s8_decision_feedback_registry.py` binds it: the source it reads is injected.
"""


def git_source(repository):
    """M7 `GitSource(repository)`: pinned Git bytes through git argv."""
    from codex_harness.host_os.adapters.git_source import GitSource
    return GitSource(repository)


def verify_sources(packet: dict, source) -> list:
    """The canonical dge verifier (`research.adapters.dge_sources.verify_sources`, S8 V14) for the entry, which never imports adapters (S11 XC-9 DUP-1)."""
    from codex_harness.research.adapters import dge_sources
    return dge_sources.verify_sources(packet, source)


def debate_sessions(service):
    """M7 `DebateSessions(service.store)`: the store only, no executor, observer, bus or provider."""
    from codex_harness.research.application.dge import DebateSessions
    return DebateSessions(service.store)


def decision_feedback(service, evidence=None):
    """M7 `DecisionFeedback(service.store[, evidence=...])`; `evidence` is `execution_evidence()` for `collect` only."""
    from codex_harness.research.application.decision_feedback import DecisionFeedback
    if evidence is None:
        return DecisionFeedback(service.store)
    return DecisionFeedback(service.store, evidence=evidence)


def execution_evidence():
    """M7 `ExecutionEvidence(FileArtifacts(runtime_dir() / "artifacts"))`: the executor's own artifact store, read-only."""
    from codex_harness.composition.configuration import runtime_dir
    from codex_harness.research.adapters.autonomous_evidence import ExecutionEvidence
    from codex_harness.storage.adapters.file_artifacts import FileArtifacts
    return ExecutionEvidence(FileArtifacts(str(runtime_dir() / "artifacts")))


def load_registry(source, revision, path):
    """The pinned registry read through the injected git source (the S8 V18 R-df1 adapter)."""
    from codex_harness.research.adapters.decision_feedback import load_registry as load
    return load(source, revision, path)
