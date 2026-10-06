"""RunTask's transport choice: the one place a routing result becomes an opened provider transport.

Layer: adapters
Context: execution
Owns: `Transports` (M7 `Executor._role_profile` + `Executor._open_runtime`, moved), including the S4 wiring
    of the accepted S3 container boundary and the active native-hook set into the Codex role container
Does not own: the profile mapping (routing.domain.profiles.select_profile), the containers, credentials
    and hook materialization (S3: execution.adapters.containers, credentials, providers.native_hooks),
    the host hook configuration (M7 `adapters/hooks.NativeHooks`, injected as `host_hooks`), the host
    Claude transport (M7 `adapters/claude_cli`, injected as `claude_runtime` until it moves), composition
Entry points: Transports, Transports.profile, Transports.open
Contracts: INV-ROLE-CONTAINER-001, INV-CODEX-CREDENTIAL-001, INV-RECURRENCE-001, INV-INVOCATION-001

The declared design v2 §5.4 change (S3b), made here and only here: at M7 an isolated `app_server`
assignment with any active native hook refused `codex_container_native_hooks_unsupported`
(executor.py:442-444, characterized by the `hooks.native_container` golden). With isolation selected the
Codex App Server now runs in its role container WITH the active hooks, bound to their Git-verified
digests (`container_hooks`: read-only digest-addressed scripts, container interpreter, trust verified
after binding or the run refuses). There is still no host fallback: with isolation selected neither a
host App Server nor a host Claude runtime is ever constructed, and an unmapped routing shape or a
disabled Codex store refuses before anything starts (CE-9: never a silent fallback). Without isolation
the host paths are M7's exactly: the host App Server receives the host hook configuration.
"""

from __future__ import annotations

from codex_harness.execution.adapters.providers.native_hooks import container_hooks
from codex_harness.execution.domain.container_spec import CLAUDE_IMPL_RW
from codex_harness.kernel.errors import require
from codex_harness.routing.domain.profiles import select_profile


class Transports:
    """Open the transport an assignment names. Nothing here falls back to another provider or the host.

    `isolation` is the S3 `IsolatedWorker` (or None: exact host behaviour). `hooks` supplies
    `active_hooks()` and `read_script(revision, path)` (the hook lifecycle owner and Git; S8/S1).
    `host_app_server(hooks=...)`, `host_hooks()` and `claude_runtime(**kwargs)` build the host transports
    and are never called while isolation is selected. `claude_settings(runtime)` renders the Claude
    settings document (M7 `claude_cli.claude_settings`, moving with the Claude transport)."""

    def __init__(self, *, isolation=None, hooks=None, host_app_server=None, host_hooks=None, claude_runtime=None,
                 claude_settings=None, worker_delivery=None, container_worker_delivery=None,
                 evidence_profile=None):
        self.isolation, self.hooks = isolation, hooks
        self.host_app_server, self.host_hooks = host_app_server, host_hooks
        self.claude_runtime, self.claude_settings = claude_runtime, claude_settings
        self.worker_delivery, self.container_worker_delivery = worker_delivery, container_worker_delivery
        self.evidence_profile = evidence_profile

    def profile(self, assignment, action, read_only) -> str | None:
        """INV-ROLE-CONTAINER-001: the fixed container profile of this routing result, or None without
        isolation (exact host behaviour). Checked before any context work, reservation or provider; an
        unmapped shape or a disabled profile refuses, never falling back to the host. (M7 refused here
        when native hooks were active; S3b runs them in the container instead, see `open`.)"""
        if self.isolation is None:
            return None
        return select_profile(assignment.provider, assignment.transport, action, read_only,
                              codex_enabled=(self.isolation.config or {}).get("codex") is not None)

    def _container_hooks(self):
        """The per-run hook-set builder handed to the Codex role container, or None when no hook source
        is wired. The set is built inside the run directory by the container runtime itself."""
        if self.hooks is None:
            return None
        hooks = self.hooks
        return lambda destination: container_hooks(hooks.active_hooks(), hooks.read_script, destination)

    def open(self, assignment, model: str, cwd=None, action: str | None = None, read_only: bool = False,
             handoff: dict | None = None):
        """The opened transport for this assignment (context manager with `run`)."""
        profile = self.profile(assignment, action, read_only)
        if profile is not None and assignment.transport == "app_server":
            # Selected isolation is the only Codex path: the App Server runs inside the profile's container
            # over stdio, never on this host (D2), with the active native hooks bound in the container.
            return self.isolation.codex_runtime(profile=profile, handoff=handoff,
                                                native_hooks=self._container_hooks())
        if assignment.transport == "app_server":
            return self.host_app_server(hooks=self.host_hooks())
        require(assignment.transport == "claude_cli", "Unsupported provider transport: " + assignment.transport)
        # INV-PROJECT-EVIDENCE-001 (R3): the host profile resolved for THIS implementation checkout reaches
        # the transport itself; without a profile the construction is exactly the legacy one.
        profiled = self.evidence_profile is not None and action == "implement" and cwd is not None
        if profile is not None and profile != CLAUDE_IMPL_RW:
            # claude-role-ro: the review checkout read-only, its own result directory, the hand-off copy.
            return self.isolation.runtime(model=model, runtime=assignment.runtime,
                                          max_budget_usd=assignment.controls.get("max_budget_usd"),
                                          settings_document=self.claude_settings(assignment.runtime),
                                          project_delivery=None, profile=profile, handoff=handoff)
        if self.isolation is not None:
            # Selected isolation is the only Claude path: there is no branch back to the host runtime.
            return self.isolation.runtime(model=model, runtime=assignment.runtime,
                                          max_budget_usd=assignment.controls.get("max_budget_usd"),
                                          settings_document=self.claude_settings(assignment.runtime),
                                          project_delivery=self.container_worker_delivery(
                                              self.evidence_profile, cwd, self.isolation.config) if profiled else None)
        project = ({"project_delivery": self.worker_delivery(self.evidence_profile, cwd)} if profiled else {})
        return self.claude_runtime(model=model, runtime=assignment.runtime,
                                   executable=assignment.controls.get("executable"),
                                   max_budget_usd=assignment.controls.get("max_budget_usd"),
                                   settings_document=self.claude_settings(assignment.runtime), **project)
