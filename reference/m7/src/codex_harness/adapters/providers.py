"""Load the packaged execution policy and read the host's provider enablement.

The policy ships in the repository, so a reviewer reads what a provider may run from Git rather
than from a machine. The enablement comes from the host's settings, so the same commit behaves as
Codex-only until an operator turns a pairing on. An unreadable or invalid policy is an error, never
an empty policy that would quietly leave everything to the default.
"""
from __future__ import annotations

import json
from pathlib import Path

from codex_harness.adapters.configuration import settings
from codex_harness.domain.model import ContractError
from codex_harness.domain.providers import (
    ProviderConfiguration,
    ProviderPolicy,
    parse_configuration,
    parse_policy,
    select_execution,
)

POLICY_FILE = Path(__file__).resolve().parents[1] / "resources/providers.json"

__all__ = ["POLICY_FILE", "ExecutionPolicy", "host_policy", "packaged_policy"]


def packaged_policy() -> ProviderPolicy:
    try:
        document = json.loads(POLICY_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ContractError("Provider policy definition unavailable or invalid") from exc
    return parse_policy(document)


class ExecutionPolicy:
    """The packaged policy bound to one host configuration; the executor asks it who runs a task."""

    def __init__(self, policy: ProviderPolicy, configuration: ProviderConfiguration):
        self.policy, self.configuration = policy, configuration

    def select(self, *, role: str, action, workload: str, read_only: bool):
        return select_execution(self.policy, self.configuration, role=role, action=action,
                                workload=workload, read_only=read_only)

    def provider(self, name: str):
        return self.policy.provider(name)

    def summary(self) -> dict:
        """What is enabled on this host, without any configured value beyond the model name."""
        return {"policy_version": self.policy.version, "policy_digest": self.policy.policy_digest,
                "config_digest": self.configuration.config_digest,
                "default_provider": self.policy.default_provider,
                "enabled": {name: {"pairs": [f"{role}/{action}" for role, action in entry["pairs"]],
                                   "model": entry["model"], "controls": sorted(entry["controls"])}
                            for name, entry in sorted(self.configuration.enabled.items())}}


def host_policy(values: dict | None = None) -> ExecutionPolicy:
    policy = packaged_policy()
    return ExecutionPolicy(policy, parse_configuration(policy, values if values is not None else settings()))
