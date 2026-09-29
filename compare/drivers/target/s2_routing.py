"""Target driver: `routing.matrix` on the target tree (codex_harness.routing).

The host settings mapping is always passed explicitly (the target adapter never reads the host).
"""

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

from types import SimpleNamespace  # noqa: E402

import s2_routing  # noqa: E402
from codex_harness.kernel.errors import ContractError  # noqa: E402
from codex_harness.routing.adapters import provider_policy  # noqa: E402
from codex_harness.routing.adapters.organization_source import packaged_organization  # noqa: E402
from codex_harness.routing.domain import organization, providers  # noqa: E402
from codex_harness.routing.domain.model_selection import select_model  # noqa: E402
from codex_harness.routing.domain.profiles import select_profile  # noqa: E402

API = SimpleNamespace(
    organization=packaged_organization, Organization=organization.Organization, Agent=organization.Agent,
    conductor_self_arbitration=organization.conductor_self_arbitration, providers=providers,
    packaged_policy=provider_policy.packaged_policy, ExecutionPolicy=provider_policy.ExecutionPolicy,
    host_policy=provider_policy.host_policy, select_profile=select_profile, select_model=select_model,
    ContractError=ContractError,
    policy_document=lambda: json.loads(provider_policy.POLICY_FILE.read_text(encoding="utf-8")))

if __name__ == "__main__":
    driver.finish("target", "routing.matrix", s2_routing.run(API))
