"""Composition of the release runner: its verification environment and the wiring of the deployment adapter (DESIGN-s7 adapters-move §13).

Layer: composition
Owns: `ENVIRONMENT_KEYS` and `verification_environment` (M7 `adapters/verification.py`, moved ahead of S8; the rest of verification.py stays S8), `ExecutionContainerNaming` and `release_runner`, the wiring of `delivery.adapters.deployment.ReleaseRunner`
Does not own: VerificationServices, the release suite and the hooks (S8/S10) and the rebase request (S5): `release_runner` takes them as parameters (carries)
Entry points: ENVIRONMENT_KEYS, verification_environment, ExecutionContainerNaming, release_runner
Contracts: INV-RELEASE-001, INV-ENCODING-001, INV-HOST-DELIVERY-VERIFY-001

Moved ahead of its slice from M7 `adapters/verification.py` (SOURCE e38aa722) through named rules (A/evidence/rebuild/s7/deployment-move/move_aheads.py); the only change is the home of `python_channel_environment` (host_os.adapters.process_groups, which only composition may import); the body is otherwise M7's. `release_runner` supplies what M7's `ReleaseRunner` constructed itself (DESIGN-s7 adapters-move §13).
"""
from __future__ import annotations

import os

from codex_harness.composition import configuration
from codex_harness.delivery.adapters.deployment import ReleaseRunner
from codex_harness.execution.domain.container_spec import LABEL, ROLE_LABEL
from codex_harness.host_os.adapters.process_groups import python_channel_environment
from codex_harness.intake.application import tickets
from codex_harness.review.application.releases import Releases

ENVIRONMENT_KEYS = {"PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP", "TMPDIR",
    "HOME", "USERPROFILE", "LOCALAPPDATA", "APPDATA", "LANG", "LC_ALL", "UV_CACHE_DIR",
    "PROGRAMDATA", "PROGRAMFILES", "PROGRAMFILES(X86)", "HOMEDRIVE", "HOMEPATH", "ALLUSERSPROFILE",
    "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE"}


def verification_environment(endpoints, environ=None):
    source = os.environ if environ is None else environ
    env = {key: value for key, value in source.items() if key.upper() in ENVIRONMENT_KEYS}
    # INV-RELEASE-001: old incumbent tests mutate HARNESS_*; remove inherited Zeus aliases.
    env.update(HARNESS_INTEGRATION="1", HARNESS_DATABASE_URL=endpoints["database_url"],
               HARNESS_REDIS_URL=endpoints["redis_url"], HARNESS_REDIS_NAMESPACE="zeus-verification")
    # INV-ENCODING-001: release pytest is a Python child; the allowlist above already dropped
    # any inherited PYTHONIOENCODING/PYTHONUTF8, so the channel is bound here explicitly.
    return python_channel_environment(env)


class ExecutionContainerNaming:
    """`delivery.ports.ContainerNaming` over execution's exact name and label pair (INV-HOST-DELIVERY-VERIFY-001)."""

    def name(self, run_id, role) -> str:
        # The body of execution's `OwnedContainer.name`: creation and reconciliation use one exact name.
        return "zeus-" + role + "-" + run_id

    def labels(self, run_id, role) -> list[str]:
        return [LABEL + "=" + run_id, ROLE_LABEL + "=" + role]


def release_runner(service, git, artifacts, auth, auto_merge=True, fence=None, verification_root=None, *,
                   runner, release_suite, verification_services, hooks, request_rebase, clock=None, events=None, hooks_rollback=None, ids=None):
    """M7's `ReleaseRunner(service, git, artifacts, auth, auto_merge, fence, verification_root)`, wired (V6).

    `runner` (host_os), `release_suite` and `verification_services` (S8), `hooks` (S10) and `request_rebase` (S5)
    are carried: their owners are not in the target yet, so the caller passes them."""
    releases = Releases(service.store, service.org, ticket_binding=tickets.ticket_binding,
                        ticket_superseded=tickets.TicketSuperseded, clock=clock, events=events, hooks=hooks_rollback, ids=ids)
    return ReleaseRunner(
        service, git, artifacts, auth, auto_merge, fence, verification_root or configuration.runtime_dir() / "verification",
        releases=releases, ticket_binding=tickets.ticket_binding, ticket_superseded=tickets.TicketSuperseded,
        runner=runner, release_suite=release_suite, verification_services=verification_services,
        verification_environment=verification_environment, hooks=hooks, request_rebase=request_rebase,
        compose_environment=configuration.compose_environment, naming=ExecutionContainerNaming(), clock=clock)
