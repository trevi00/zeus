"""Composition of the three M7 module mains that now run as target process entries (R-e5a, DESIGN-s10 §16 (a)).

Layer: composition
Owns: the adapter-touching calls of `experience`, `isolated_worker` (status|reconcile) and `service_entry`; each delegates to its target home and has no logic of its own
Does not own: the argv shapes and exit codes (entry.processes.*) and the host-migration CLI (a separate S10 carry)
Entry points: experience_store, experience_artifacts, experience_preview, experience_import, isolated_worker_status, isolated_worker_reconcile, service_entry_main
Contracts: INV-EXPERIENCE-001

Target homes: `PostgresStore` storage.adapters.postgres_store, `FileArtifacts` storage.adapters.file_artifacts, `database_url` composition (package),
`preview_lessons`/`import_lessons` knowledge.adapters.experience_import with `load_yaml` from context.adapters.yaml_source (the loader the knowledge adapter
injects), `unresolved_runs`/`reconcile` execution.adapters.containers.cleanup_ledger (`reconcile` takes the Docker runner, built here as in
composition.fleet_recovery: the process_groups chokepoint, M7's default `docker` executable) and `main` host_os.adapters.service_entry.
Imports sit inside the functions, so importing this module stays light.
"""
from __future__ import annotations

import subprocess


def experience_store():
    from codex_harness.composition import database_url
    from codex_harness.storage.adapters.postgres_store import PostgresStore
    return PostgresStore(database_url())


def experience_artifacts(path):
    from codex_harness.storage.adapters.file_artifacts import FileArtifacts
    return FileArtifacts(path)


def experience_preview(paths, source, basis, path_prefix=''):
    from codex_harness.context.adapters.yaml_source import load_yaml
    from codex_harness.knowledge.adapters.experience_import import preview_lessons
    return preview_lessons(paths, source, basis, path_prefix, load_yaml=load_yaml)


def experience_import(paths, source, basis, store, artifacts, path_prefix=''):
    from codex_harness.context.adapters.yaml_source import load_yaml
    from codex_harness.knowledge.adapters.experience_import import import_lessons
    return import_lessons(paths, source, basis, store, artifacts, path_prefix, load_yaml=load_yaml)


def isolated_worker_status(roots):
    from pathlib import Path

    from codex_harness.execution.adapters.containers.cleanup_ledger import unresolved_runs
    return [row for root in roots for row in unresolved_runs(Path(root))]


def _docker(docker, args, *, timeout, env=None):
    from codex_harness.execution.adapters.containers.owned_container import docker_environment
    from codex_harness.host_os.adapters.process_groups import run_process
    try:
        return run_process([docker, *args], timeout=timeout, env=env if env is not None else docker_environment())
    except (OSError, subprocess.TimeoutExpired) as exc:
        return subprocess.CompletedProcess([docker, *args], None, "", type(exc).__name__)


def _reconcile_runner(argv, *, timeout, env=None):
    """`cleanup_ledger.reconcile`'s runner contract is `runner(argv, timeout=, env=)` (`owned_container.docker_call`); `_docker`
    keeps M7's `(docker, args)` shape, so the bare `_docker` raised TypeError on the first docker call (found by S10 F2)."""
    return _docker(argv[0], list(argv[1:]), timeout=timeout, env=env)


def isolated_worker_reconcile(root, observer=None):
    """`isolated_worker_runs reconcile`: the operator step, with its own process observer (S10 F2, FLEET-REBUILD-S10-ACCEPT
    F2 row 3). The observer is spool-only (no store: this step reads and writes run records, not the runtime database), its
    component is `isolated-worker-runs`, and a spool that cannot be built leaves the step uninstrumented, never refused."""
    from codex_harness.execution.adapters.containers.cleanup_ledger import reconcile
    own = observer is None
    if own:
        try:
            from codex_harness.composition.observation import build_observer
            observer = build_observer(None, "isolated-worker-runs")
        except Exception:  # noqa: BLE001 - diagnostics must not refuse the operator's reconcile
            observer = None
    try:
        return reconcile(root, runner=_reconcile_runner, observer=observer)
    finally:
        if own and observer is not None:
            observer.close()


def service_entry_main(argv, *, cli_main):
    from codex_harness.host_os.adapters.service_entry import main
    return main(argv, cli_main=cli_main)


def artifact_reader_main(argv):
    """Owner, int44 (DESIGN-s10 §16b): the kept `adapters.artifact_reader` shim's body."""
    from codex_harness.storage.adapters.artifact_reader import main
    return main(argv)


def migrations_main(argv):
    """Owner, int44 (DESIGN-s10 §16b): the kept `adapters.migrations` shim's body."""
    from codex_harness.storage.adapters.migrator import main
    return main(argv)
