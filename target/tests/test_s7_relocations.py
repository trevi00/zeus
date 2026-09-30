"""S7 relocations (DESIGN-s7 §5 V9): the owner-action row values the delivery evidence reader holds locally are the
values of `coordination.domain.owner_actions`, so the vocabulary cannot drift and delivery imports no coordination."""
import importlib

import pytest

V9_NAMES = ("DELIVERY_CANARY", "COMPLETED", "VERDICT_ACCEPTED")


@pytest.mark.parametrize("name", V9_NAMES)
def test_v9_local_read_constants_equal_the_owner_action_values(name):
    reader = importlib.import_module("codex_harness.delivery.domain.host_migration_evidence")
    owner = importlib.import_module("codex_harness.coordination.domain.owner_actions")
    assert getattr(reader, name) == getattr(owner, name)
