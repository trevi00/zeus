"""Load the packaged execution policy and bind it to one host configuration.

Layer: adapters
Context: routing
Owns: reading `resources/providers.json`; ExecutionPolicy, the policy bound to one host settings mapping
Does not own: reading host settings (composition passes the mapping; S10), provider transports (execution)
Entry points: packaged_policy, ExecutionPolicy.select, ExecutionPolicy.provider, ExecutionPolicy.summary, host_policy
Contracts: INV-CLAUDE-WORKER-001

Moved from SOURCE M7 `adapters/providers.py`. The policy ships in the repository, so a reviewer reads
what a provider may run from Git; the enablement comes from the host's settings. An unreadable or
invalid policy is an error, never an empty policy. Change (declared, §2.8): `host_policy(values)`
takes the settings mapping explicitly; the M7 fallback to reading the host environment moves to the
composition root, so this adapter never acquires host configuration itself.
"""
from __future__ import annotations

import json
from pathlib import Path

from codex_harness.kernel.errors import ContractError
from codex_harness.routing.domain.providers import (
    ProviderConfiguration,
    ProviderPolicy,
    parse_configuration,
    parse_policy,
    select_execution,
)

POLICY_FILE = Path(__file__).resolve().parents[2] / "resources/providers.json"

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


def host_policy(values) -> ExecutionPolicy:
    """The packaged policy bound to the given host settings mapping (read once by composition)."""
    policy = packaged_policy()
    return ExecutionPolicy(policy, parse_configuration(policy, values))
