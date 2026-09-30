"""S6 relocations (DESIGN-s6 §1 V1, §13 V2): a name moved to its new home is the same object from both modules.

The moves change the defining module only; every `except ManifestError`, `except ContinuationRefused` and every
validator call reaches the one object it always did. Behaviour is pinned by the S4/S5 suites and goldens, unchanged."""
import importlib

import pytest

V2_NAMES = ("SCHEMA", "SCHEMA_V2", "FIELDS", "FIELDS_V2", "GOAL_FIELDS", "PLAN_FIELDS", "DESIGN_FIELDS", "CLAUDE_FIELDS",
            "WORKER", "ACTION", "TEXT_LIMIT", "ManifestError", "_text", "_integer", "_number", "_fields",
            "validate_plan", "validate_manifest", "provider_settings")


@pytest.mark.parametrize("name", V2_NAMES)
def test_v2_operation_manifest_names_are_one_object(name):
    home = importlib.import_module("codex_harness.intake.domain.operation_manifest")
    old = importlib.import_module("codex_harness.coordination.domain.operation")
    assert getattr(old, name) is getattr(home, name)
