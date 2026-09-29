"""Contract and runner-failure error types, and the one `require` guard.

Layer: kernel
Context: kernel
Owns: ContractError (a violated declared contract), ExecutionFailure (a runner-observed failure)
Does not own: domain-specific refusal codes (each owner subclasses ContractError)
Entry points: ContractError, ExecutionFailure, require
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
