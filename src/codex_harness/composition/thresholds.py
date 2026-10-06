"""The threshold-proposal composition: the builders `entry.cli.threshold_proposals` calls (V27, DESIGN-s8 §26).

Layer: composition
Owns: policy_git, artifacts, proposals, proposal_store, replay, replay_store, replay_artifacts, and the re-exports current_policy and project_identity
Does not own: the argument shape or the exit codes (entry.cli.threshold_proposals and entry.cli.threshold_replay), the Git-bound policy (research.adapters.threshold_policy) and the proposal rules (research.application.threshold_proposals)
Entry points: policy_git, current_policy, artifacts, proposals, proposal_store, replay, replay_store, replay_artifacts, project_identity
Contracts: INV-THRESHOLD-PROPOSAL-001, INV-NATIVE-REPLAY-001

Replaces the adapter constructions of M7 `adapters/threshold_proposals.py:main` (SOURCE e38aa722:34-44): `GitWorkspace(...)`, `FileArtifacts(...)`, `ThresholdProposals(...)` with `NativeRoutingReplay(artifacts)`, and `PostgresStore(database_url())`.
`proposals` also wires context's `validate_source` into `ThresholdProposals` (V18 R-t1: the `legacy_source` path requires it), so `--legacy-source` keeps M7's behaviour.
"""
from codex_harness.context.adapters.skill_history import project_identity
from codex_harness.research.adapters.threshold_policy import current_policy

__all__ = ["artifacts", "current_policy", "policy_git", "project_identity", "proposal_store", "proposals", "replay", "replay_artifacts", "replay_store"]


def policy_git(repository, workspaces):
    from codex_harness.host_os.adapters.git_workspace import GitWorkspace
    return GitWorkspace(repository, workspaces)


def artifacts(path):
    from codex_harness.storage.adapters.file_artifacts import FileArtifacts
    return FileArtifacts(path)


def proposals(store, artifacts, policy):
    from codex_harness.context.adapters.native_routing_replay import NativeRoutingReplay
    from codex_harness.context.domain.skills.import_ import validate_source
    from codex_harness.research.application.threshold_proposals import ThresholdProposals
    return ThresholdProposals(store, artifacts, lambda: policy, NativeRoutingReplay(artifacts),
                              validate_source=validate_source)


def proposal_store():
    from codex_harness.composition import database_url
    from codex_harness.storage.adapters.postgres_store import PostgresStore
    return PostgresStore(database_url())


def replay(store):
    """The ThresholdReplay of `store`, wired with context's `validate_source` (V18 R-t1: the `legacy_source` path requires it)."""
    from codex_harness.context.domain.skills.import_ import validate_source
    from codex_harness.research.application.threshold_replay import ThresholdReplay
    return ThresholdReplay(store, validate_source=validate_source)


def replay_store():
    """M7 `threshold_replay.main`'s `PostgresStore(database_url())` (SOURCE e38aa722:42)."""
    return proposal_store()


def replay_artifacts(path):
    """M7 `threshold_replay.main`'s `FileArtifacts(args.artifacts)` (SOURCE e38aa722:47)."""
    return artifacts(path)
