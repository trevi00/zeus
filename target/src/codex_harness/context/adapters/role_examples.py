"""Load the packaged canonical role examples.

Layer: adapters
Context: context
Owns: reading `resources/role-examples-v1.json` and validating it against the organization's agents
Does not own: the shape rules (context.domain.role_examples), prompt delivery (S10, D10)
Entry points: load_role_examples
Contracts: INV-CONTEXT-001
"""

from __future__ import annotations

import json
from importlib.resources import files

from codex_harness.context.domain.role_examples import validate


def load_role_examples(organization_agents: list[str]) -> dict:
    document = json.loads(files("codex_harness.resources").joinpath("role-examples-v1.json").read_text())
    return validate(document, organization_agents)
