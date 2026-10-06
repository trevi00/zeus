"""The `zeus worker-session` composition: the archive root, the evidence store and the owners over them.

Layer: composition
Owns: archive_root, evidence_store, session_archives, worker_sessions
Does not own: the argument shape and the command body (entry.cli.worker_session) and the session rows (execution.application.worker_sessions)
Entry points: archive_root, evidence_store, session_archives, worker_sessions
Contracts: INV-WORKER-SESSION-001

Moved from M7 `adapters/worker_sessions.py` (SOURCE e38aa722) by named rule R-c11 (S10 unit C7a): `archive_root` (:267-269) and `evidence_store` (:282-285) are M7's bodies with the
target homes of `runtime_dir` and `FileArtifacts`. `session_archives` is M7 `SessionArchives(archive_root())` (the target `SessionArchives` takes the store, which composition builds: a
`FileArtifacts` over the root), and `worker_sessions` is M7 `WorkerSessions(service.store, archives, evidence=...)` with the opened evidence store the `close` command passes.
"""


def archive_root():
    from codex_harness.composition.configuration import runtime_dir
    return runtime_dir() / "worker-sessions"


def evidence_store():
    """The verified general artifact store the executor writes execution receipts into."""
    from codex_harness.composition.configuration import runtime_dir
    from codex_harness.storage.adapters.file_artifacts import FileArtifacts
    return FileArtifacts(str(runtime_dir() / "artifacts"))


def session_archives():
    """M7 `SessionArchives(archive_root())`: the restricted archive store over the worker-sessions root."""
    from codex_harness.execution.adapters.worker_sessions import SessionArchives
    from codex_harness.storage.adapters.file_artifacts import FileArtifacts
    return SessionArchives(FileArtifacts(str(archive_root())))


def worker_sessions(service, archives, evidence=None):
    """M7 `WorkerSessions(service.store, archives, evidence=...)`; `evidence` is the opened store (`close` only)."""
    from codex_harness.execution.application.worker_sessions import WorkerSessions
    return WorkerSessions(service.store, archives, evidence=evidence)
