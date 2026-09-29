"""Reference driver: `routing.matrix` on SOURCE M7 (REBUILD-DESIGN-v2 §5.3 S2, R-C first).

M7 `domain.model.Organization/Agent/conductor_self_arbitration` loaded through `bootstrap.organization`,
`domain.providers`, `adapters.providers` (the host settings mapping is always passed explicitly, so
no host configuration is read), `adapters.role_containers.select_profile` and
`domain.model_routing.select_model`. Nothing here needs the clock or ids.
"""

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

from types import SimpleNamespace  # noqa: E402

import s2_routing  # noqa: E402

from codex_harness import bootstrap  # noqa: E402
from codex_harness.adapters import providers as provider_adapter  # noqa: E402
from codex_harness.adapters.role_containers import select_profile  # noqa: E402
from codex_harness.domain import model, providers  # noqa: E402
from codex_harness.domain.model_routing import select_model  # noqa: E402

API = SimpleNamespace(
    organization=bootstrap.organization, Organization=model.Organization, Agent=model.Agent,
    conductor_self_arbitration=model.conductor_self_arbitration, providers=providers,
    packaged_policy=provider_adapter.packaged_policy, ExecutionPolicy=provider_adapter.ExecutionPolicy,
    host_policy=provider_adapter.host_policy, select_profile=select_profile, select_model=select_model,
    ContractError=model.ContractError,
    policy_document=lambda: json.loads(provider_adapter.POLICY_FILE.read_text(encoding="utf-8")))

if __name__ == "__main__":
    driver.finish("reference", "routing.matrix", s2_routing.run(API))
