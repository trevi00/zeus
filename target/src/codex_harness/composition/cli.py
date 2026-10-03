"""The `zeus` CLI composition: the adapters the store-free roots use (OWNER-DECISIONS-S10 #1).

Layer: composition
Owns: organization, codex_runtime, and the re-exports validate_message and resolve_codex
Does not own: any root's argument shape or body (entry.cli) and the store-backed wiring (S10 units C2-C8)
Entry points: organization, codex_runtime, validate_message, resolve_codex
Contracts: none

Replaces the M7 `bootstrap.organization`, `adapters.codex.CodexRuntime()` and `adapters.contracts.validate_message`
imports of `cli.py` (SOURCE e38aa722). M7 built `CodexRuntime()` with no runner; the target injects `run_process`.
"""

from codex_harness.execution.adapters.providers.codex_app_server import resolve_codex
from codex_harness.execution.adapters.providers.codex_exec import CodexRuntime
from codex_harness.host_os.adapters.process_groups import run_process
from codex_harness.routing.adapters.organization_source import packaged_organization
from codex_harness.storage.adapters.message_schema import validate_message

__all__ = ["organization", "codex_runtime", "validate_message", "resolve_codex"]


def organization():
    return packaged_organization()


def codex_runtime():
    return CodexRuntime(runner=run_process)
