"""The one mapping table of the ported S3 container suites (REBUILD-DESIGN-v2 §5.3 S3).

The SOURCE M7 suites address two modules, `adapters.isolated_worker` (`iw`) and `adapters.role_containers`
(`rc`). Their symbols moved to several target modules; `iw` and `rc` here bind the SAME names to the moved
target symbols so the ported test bodies read as in M7. Two adaptations are named once, here:

- Composition's injection: the target transports receive their host facilities (`ContainerHost`: docker
  runner, git processes, attached-client trees) and the credential boundary (`CredentialBoundary`)
  explicitly; `rc.IsolatedCodexRuntime`, `iw.IsolatedClaudeRuntime` and `iw.OwnedContainer` below supply
  the ones composition supplies (the host_os chokepoint and the credentials adapters).
- The M7 fixtures replaced the module globals `iw._docker` and `iw.ProcessTree`; the ported fixtures call
  `install_fake(monkeypatch, fake)` (or `install_docker` for `_docker` alone), which replaces the target's
  one docker-call function (`owned_container.docker_call`) and the trees the transports are built with.
  The fake itself is the M7 fake, unchanged. Module globals an M7 test patched on `iw` (`MAX_FILES`,
  `MAX_TOTAL_BYTES`, `_write_record`) are patched on the target module that owns them.
"""

from __future__ import annotations

from types import SimpleNamespace

from codex_harness.credentials.adapters import codex_custody, scrubber
from codex_harness.credentials.domain import codex_credential as cc
from codex_harness.execution.adapters.containers import (
    cleanup_ledger,
    handoff,
    launcher,
    owned_container,
    staging,
)
from codex_harness.execution.adapters.providers import codex_app_server
from codex_harness.execution.domain import container_spec as spec
from codex_harness.execution.domain import staging_rules
from codex_harness.host_os.adapters import process_groups
from codex_harness.host_os.adapters.process_tree import ProcessTree
from codex_harness.kernel.errors import ContractError, IsolationError
from codex_harness.routing.domain.profiles import select_profile

TREES = {"current": ProcessTree}
PROCESSES = process_groups.ChokepointProcesses()
CREDENTIALS = launcher.CredentialBoundary(scrubber=scrubber.CredentialScrubber,
                                          OutputUnsanitizable=scrubber.OutputUnsanitizable)


def host(worker_profiles=None) -> launcher.ContainerHost:
    return launcher.ContainerHost(runner=process_groups.run_process, processes=PROCESSES, trees=TREES["current"],
                                  worker_profiles=worker_profiles)


def install_fake(monkeypatch, fake) -> None:
    """Route every docker call to the M7 fake (signature `fake(docker, args, *, timeout, env)`) and build
    attached clients with its tree, as the M7 fixture did by replacing `_docker` and `ProcessTree`."""
    monkeypatch.setattr(owned_container, "docker_call",
                        lambda runner, docker, args, *, timeout, env=None: fake(docker, args, timeout=timeout, env=env))
    monkeypatch.setitem(TREES, "current", fake.tree())


def install_docker(monkeypatch, fake) -> None:
    """Route every docker call to `fake(docker, args, *, timeout, env)` (M7: replacing `iw._docker` alone)."""
    monkeypatch.setattr(owned_container, "docker_call",
                        lambda runner, docker, args, *, timeout, env=None: fake(docker, args, timeout=timeout, env=env))


def _stage_source(repository, revision, destination, *, on_progress=None):
    return staging.stage_source(repository, revision, destination, processes=PROCESSES, on_progress=on_progress)


def _list_revision(repository, revision):
    return staging.list_revision(repository, revision, processes=PROCESSES)


def _init_standalone_git(directory):
    return staging.init_standalone_git(directory, processes=PROCESSES)


class _CodexRuntime(launcher.IsolatedCodexRuntime):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("host", host())
        kwargs.setdefault("credentials", CREDENTIALS)
        super().__init__(*args, **kwargs)


class _ClaudeRuntime(launcher.IsolatedClaudeRuntime):
    def __init__(self, *args, worker_profiles=None, **kwargs):
        kwargs.setdefault("host", host(worker_profiles))
        super().__init__(*args, **kwargs)


class _OwnedContainer(owned_container.OwnedContainer):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("runner", process_groups.run_process)
        super().__init__(*args, **kwargs)


def _isolated_worker(config, root, docker="docker"):
    return launcher.IsolatedWorker(config, root, docker, host=host(), broker_factory=codex_custody.CodexCredentialBroker,
                                   credentials=CREDENTIALS)


def _container_args(config, **fields):
    return spec.container_args(config, user=owned_container.host_user(), **fields)


def _reconcile(run_directory, docker="docker"):
    return cleanup_ledger.reconcile(run_directory, docker, runner=process_groups.run_process)


def _preflight(config, docker="docker", environment=None, *, token=True):
    return owned_container.preflight(config, docker, environment, token=token, runner=process_groups.run_process)


def _forbidden_controls(observed):
    return spec.forbidden_controls(observed, home=owned_container.operator_home())


iw = SimpleNamespace(
    IsolationError=IsolationError, load_isolation=owned_container.load_host_isolation, summary=spec.summary,
    LABEL=spec.LABEL, ROLE_LABEL=spec.ROLE_LABEL, WORKSPACE=spec.WORKSPACE, EVIDENCE=spec.EVIDENCE,
    CONTAINER_HOME=spec.CONTAINER_HOME, LIMITS=spec.LIMITS, INSPECT_FORMAT=spec.INSPECT_FORMAT,
    TOKEN_NAME=spec.TOKEN_NAME, IMAGE=spec.IMAGE, MODE=spec.MODE, TRUSTED_PYTHON=spec.TRUSTED_PYTHON,
    ENTRY_MODULE=spec.ENTRY_MODULE, PROTOCOL=spec.PROTOCOL, PROTOCOLS=spec.PROTOCOLS,
    READ_ONLY_PROTOCOL=spec.READ_ONLY_PROTOCOL, DELIVERY_PROTOCOL=spec.DELIVERY_PROTOCOL,
    SESSION_PROTOCOL=spec.SESSION_PROTOCOL, SESSION_DELIVERY_PROTOCOL=spec.SESSION_DELIVERY_PROTOCOL,
    MAX_FILES=spec.MAX_FILES, MAX_FILE_BYTES=spec.MAX_FILE_BYTES, MAX_TOTAL_BYTES=spec.MAX_TOTAL_BYTES,
    RESOLVED=spec.RESOLVED, request_protocol=spec.request_protocol, worker_environment=spec.worker_environment,
    read_only_mounts=spec.read_only_mounts, container_args=_container_args, forbidden_controls=_forbidden_controls,
    docker_environment=owned_container.docker_environment, preflight=_preflight, OwnedContainer=_OwnedContainer,
    run_records=cleanup_ledger.run_records, unresolved_runs=cleanup_ledger.unresolved_runs,
    new_record=cleanup_ledger.new_record, advance=cleanup_ledger.advance, hold=cleanup_ledger.hold,
    retire=cleanup_ledger.retire, join_cleanup=cleanup_ledger.join_cleanup, cleanup_debt=cleanup_ledger.cleanup_debt,
    reconcile=_reconcile, check_relative_path=staging_rules.check_relative_path,
    check_bounds=staging_rules.check_bounds, scan_tree=staging.scan_tree, plan_import=staging.plan_import,
    apply_import=staging.apply_import, PREPARATION_TICK_SECONDS=staging.PREPARATION_TICK_SECONDS,
    stage_source=_stage_source, list_revision=_list_revision, init_standalone_git=_init_standalone_git,
    parse_line=launcher.parse_line, IsolatedClaudeRuntime=_ClaudeRuntime, ProcessTree=ProcessTree,
    IsolatedWorker=_isolated_worker, _write_record=cleanup_ledger._write_record)

rc = SimpleNamespace(
    select_profile=select_profile, CLAUDE_IMPL_RW=spec.CLAUDE_IMPL_RW, CLAUDE_ROLE_RO=spec.CLAUDE_ROLE_RO,
    CODEX_ROLE_RO=spec.CODEX_ROLE_RO, CODEX_IMPL_RW=spec.CODEX_IMPL_RW, PROFILES=spec.PROFILES, RESULT=spec.RESULT,
    ROLE_PROFILES=spec.ROLE_PROFILES, WRITABLE_PROFILES=spec.WRITABLE_PROFILES,
    CODEX_HOME=cc.CODEX_HOME, CODEX_EXECUTABLE=cc.CODEX_EXECUTABLE, CODEX_CLI_VERSION=cc.CODEX_CLI_VERSION,
    CODEX_CLI_SHA256=cc.CODEX_CLI_SHA256, CODEX_CONFIG=cc.CODEX_CONFIG, CODEX_CONFIG_SHA256=cc.CODEX_CONFIG_SHA256,
    REDACTED=cc.REDACTED, REDACTED_JWT=cc.REDACTED_JWT, codex_environment=spec.codex_environment,
    CodexCredentialBroker=codex_custody.CodexCredentialBroker, CredentialScrubber=scrubber.CredentialScrubber,
    OutputUnsanitizable=scrubber.OutputUnsanitizable, IsolatedCodexRuntime=_CodexRuntime,
    AttachedAppServer=launcher.AttachedAppServer, retain_evidence_handoff=handoff.retain_evidence_handoff,
    handoff_refs=handoff.handoff_refs, materialize_handoff=handoff.materialize_handoff,
    discard_tree=handoff.discard_tree, HANDOFF_KIND=handoff.HANDOFF_KIND)

app_server = codex_app_server

__all__ = ["iw", "rc", "app_server", "ContractError", "install_fake", "install_docker", "host", "TREES", "PROCESSES",
           "CREDENTIALS", "staging", "staging_rules", "cleanup_ledger", "owned_container", "launcher"]
