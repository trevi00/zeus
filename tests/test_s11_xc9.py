"""S11 XC-9 (TQ-XCUT-PLAN section 10 G4b; DESIGN-s11 section 10 DUP-1, DOC-1, section 6.2).

Behavioural: the capacity refusal is observed through the composed owner-actions port (DESIGN-s10 section 17 A5-2:
`operations.capacity_refused {fleet_unit, unit_limit}`), and the dge entry reaches the one canonical verifier through composition.
The structural check (named contract: no duplicate of a canonical owner, DESIGN-s11 section 10 R-MC2-9 DUP-1) asserts the entry
no longer defines `_verify_sources`; DOC-1 is a text fact of DESIGN-s11 section 6.2, checked against the module docstring."""
from __future__ import annotations

import pytest

from codex_harness import composition
from codex_harness.composition import cli_research, configuration, owner_actions
from codex_harness.composition.managed_runtime import fixture_config
from codex_harness.coordination.application.fleet.registry import FleetRegistry
from codex_harness.entry.cli import dge as dge_entry
from codex_harness.execution import ports as execution_ports
from codex_harness.research.adapters import dge_sources
from codex_harness.routing.adapters.organization_source import packaged_organization
from codex_harness.storage.adapters.memory_store import MemoryStore

UNIT1, UNIT2 = "1" * 64, "2" * 64


class Recorder:
    def __init__(self):
        self.events = []

    def emit(self, event_type, outcome, **fields):
        self.events.append((event_type, outcome, fields.get("attributes")))


@pytest.fixture
def host(tmp_path, monkeypatch):
    values = {"HARNESS_RUNTIME_DIR": str(tmp_path / "runtime"), "ZEUS_COMPOSITION_PROFILE": "development"}
    monkeypatch.setattr(configuration, "settings", lambda: values)
    monkeypatch.setattr(configuration, "repository_root", lambda: tmp_path)
    (tmp_path / "runtime").mkdir()
    return tmp_path


@pytest.mark.parametrize("site", ["canary", "continuation"])
def test_the_owner_actions_fleet_port_observes_the_capacity_refusal(host, site):
    store = MemoryStore()
    config = fixture_config(host)
    lane = config["lanes"][0]
    config["lanes"] = [lane, {**lane, "id": "spare", "schema": "lane_spare", "redis_namespace": "spare",
                              "runtime": lane["runtime"] + "-spare"}]
    FleetRegistry(store).register({**config, "max_parallel": 1})
    recorder = Recorder()
    service = composition.ServiceHandle(store, packaged_organization())
    owners = owner_actions.coordinator(service, config, {}, lanes=object(), assessments=object(), research=object(),
                                       observer=recorder)
    # the two owner-actions call sites of the continuation fleet port: the canary family's and the continuation port's
    port = owners.canary.fleet if site == "canary" else owners.requalify_family.continuation.tick.fleet
    port.reserve_unit(UNIT1, "conductor", "fixture", "subject")
    assert recorder.events == []
    with pytest.raises(Exception, match="capacity"):
        port.reserve_unit(UNIT2, "conductor", "fixture", "subject")
    assert [(e[0], e[2]["scope"], e[2]["refusal_reason"]) for e in recorder.events] == [
        ("operations.capacity_refused", "fleet_unit", "unit_limit")]


def test_the_dge_entry_verifies_sources_through_the_canonical_owner(monkeypatch):
    # structural contract (DUP-1): the entry holds no second copy; behaviour: the composition pass-through is the canonical one.
    assert not hasattr(dge_entry, "_verify_sources")
    calls = []
    monkeypatch.setattr(dge_sources, "verify_sources", lambda packet, source: calls.append((packet, source)) or ["bound"])
    assert cli_research.verify_sources({"p": 1}, "src") == ["bound"]
    assert calls == [({"p": 1}, "src")]


def test_the_execution_ports_header_states_the_provider_runtime_deviation():
    doc = " ".join(execution_ports.__doc__.split())
    assert "ProviderRuntime Protocol is a declared design deviation" in doc and "DESIGN-s11 section 6.2" in doc
    assert "arrive with RunTask" not in doc
