"""Shared S4 scenario steps (`execution.output_contracts`): the role output schemas and request contracts.

Layer: harness (never shipped)

`api` exposes the side's OUTPUT_SEVERITY, object_schema, VERDICT, PLAN, IMPLEMENTATION, RESEARCH,
SHORTLIST, GITHUB_RESEARCH, DIAGNOSIS, implementation_instruction, ARTIFACT_READER,
DELIVERY_ARTIFACT_READER, invocation_options, activity_basis, sync_activity and the three cadence
constants. Schemas and reader contracts are compared by canonical JSON digest and key set;
instruction texts by sha256 and length (product text, never a payload).
"""

from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace


def canonical_digest(value) -> str:
    text = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def text_facts(text: str) -> dict:
    return {"sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(), "chars": len(text)}


def run(api) -> dict:
    schemas = {name: getattr(api, name) for name in ("VERDICT", "PLAN", "IMPLEMENTATION", "RESEARCH", "SHORTLIST",
                                                     "GITHUB_RESEARCH", "DIAGNOSIS")}
    out = {"schemas": {name: {"digest": canonical_digest(s), "required": s["required"],
                              "additionalProperties": s["additionalProperties"]} for name, s in schemas.items()},
           "object_schema": api.object_schema({"a": {"type": "string"}, "b": {"type": "boolean"}}),
           "severity": dict(sorted(api.OUTPUT_SEVERITY.items())),
           "instruction": {"profiled": text_facts(api.implementation_instruction(True)),
                           "plain": text_facts(api.implementation_instruction(False))},
           "reader": {"generic": canonical_digest(api.ARTIFACT_READER),
                      "generic_operations": sorted(api.ARTIFACT_READER["operations"]),
                      "delivery": canonical_digest(api.DELIVERY_ARTIFACT_READER)},
           "cadence": [api.ACTIVITY_LOCK_SECONDS, api.LEASE_CHECK_SECONDS, api.LEASE_RENEW_SECONDS]}
    options = []
    for transport, controls, runtime in (("app_server", {}, {}),
                                         ("claude_cli", {"max_budget_usd": 1.5}, {"permission_mode": "acceptEdits"}),
                                         ("claude_cli", {}, {})):
        assignment = SimpleNamespace(transport=transport, controls=controls, runtime=runtime)
        options.append(api.invocation_options(assignment, model="m", timeout=30, schema={"type": "object"},
                                              read_only=transport == "app_server"))
    out["invocation_options"] = options
    out["activity_basis"] = [api.activity_basis(row) for row in (
        {}, {"activity_sequence": 2, "sequence": 5}, {"activity_sequence": -1}, {"sequence": "5"})]
    syncs = []
    for row, old, linked, failed, gap in (
            ({"sequence": 3}, None, None, False, False),
            ({"sequence": 3, "activity_recent": ["r1"], "activity_progress_sequence": 2}, 2, "r2", False, False),
            ({"sequence": 3, "activity_recent": ["r1"], "activity_progress_sequence": 1}, 2, "r2", False, False),
            ({"sequence": 3, "activity_recent": ["r1"] * 6, "activity_progress_sequence": 2,
              "activity_sequence": 6}, 2, "r7", True, False),
            ({"sequence": 3, "activity_recent": ["r1"], "activity_progress_sequence": 2}, 2, None, False, True)):
        body = dict(row)
        api.sync_activity(body, old, linked, failed, gap)
        syncs.append(body)
    out["sync_activity"] = syncs
    return out
