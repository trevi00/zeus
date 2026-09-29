"""Contract and runner-failure error types, and the one `require` guard.

Layer: kernel
Context: kernel
Owns: ContractError (a violated declared contract), ExecutionFailure (a runner-observed failure),
    IsolationError (the one isolated-path refusal type shared by routing, credentials and execution)
Does not own: domain-specific refusal codes (each owner names its own `reason_code`)
Entry points: ContractError, ExecutionFailure, IsolationError, require
Contracts: INV-ROLE-CONTAINER-001, INV-CODEX-CREDENTIAL-001 (IsolationError)

IsolationError keeps its SOURCE M7 name, message form and `reason_code` (M7 `adapters/isolated_worker`,
re-exported by `adapters/role_containers`). It is defined once here because routing (profile refusal),
credentials (custody/scrubber refusals) and execution (container refusals) must raise and catch the SAME
type, and routing and credentials are DAG roots that may import nothing but the kernel (§2.4).
"""

from __future__ import annotations


class ContractError(ValueError):
    """An input violates a declared contract."""


class ExecutionFailure(RuntimeError):
    """A runner-observed failure, never a model-authored verdict."""

    def __init__(self, cause: str, evidence: dict):
        super().__init__(cause)
        self.cause = cause
        self.evidence = evidence


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise ContractError(reason)


class IsolationError(ContractError):
    """A refusal or failure of the isolated path; the code is printable, the detail never a secret."""

    def __init__(self, reason_code: str, detail: str = ""):
        super().__init__("isolated worker: " + reason_code + (": " + detail if detail else ""))
        self.reason_code = reason_code
