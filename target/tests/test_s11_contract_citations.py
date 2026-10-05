"""S11 unit CT: behavioural tests for contracts that no passing target test cited (DESIGN-s11 §5 R-L9, §5.4 G2).

Each test names its contract ID in its own docstring (the R-L9 citation), drives the owner through its public API and
takes its expected results from the contract text in docs/contracts.md, not from the implementation. Contracts that an
existing target test already covers behaviourally are not duplicated here; they are listed in the S11 CT report.
"""

import json
from copy import deepcopy
from pathlib import Path

import pytest

from codex_harness.coordination.application.outbox import Outbox
from codex_harness.intake.application import tickets as ticket_module
from codex_harness.kernel.errors import ContractError
from codex_harness.kernel.ids import SYSTEM_CLOCK
from codex_harness.research.adapters import runtime_thresholds
from codex_harness.research.application.research_program import ResearchProgram
from codex_harness.research.domain.research_program import ProgramRefused
from codex_harness.review.adapters.sdd import load_json
from codex_harness.review.application.sdd import SDD
from codex_harness.review.domain.sdd import ENVIRONMENT_FIELDS
from codex_harness.routing.adapters.organization_source import packaged_organization
from codex_harness.storage.adapters.file_artifacts import FileArtifacts
from codex_harness.storage.adapters.memory_store import MemoryStore

ROOT = Path(__file__).resolve().parents[2]
BASE = "a" * 40


def program_config(program_id="rp-ct", **overrides):
    # `register` stores the config unvalidated; strict validation is `validate_config`'s, not `config`'s.
    document = {"schema": "urn:zeus:research-program:1", "id": program_id, "base_revision": BASE,
                "deadline": "2029-06-01T00:00:00+00:00", "interval_seconds": 3600, "max_cycles": 2,
                "max_adoptions": 1, "topics": [{"id": "storage", "keywords": ["postgres"]}]}
    document.update(overrides)
    return document


def test_s11_contract_research_program_config_returns_the_registered_config_only():
    """INV-RESEARCH-PROGRAM-001: a program's config is immutable once registered; `ResearchProgram.config` reads it back.

    It returns the config registered under that id (not another program's), a later conflicting registration under the
    same id is refused without replacing it, pausing/resuming leaves it unchanged, and an unregistered id is the
    fixed refusal `unknown_program`."""
    programs = ResearchProgram(MemoryStore())
    first, other = program_config("rp-ct-one"), program_config("rp-ct-two", max_cycles=7)
    programs.register(first, "repo-identity", [])
    programs.register(other, "repo-identity", [])
    assert programs.config("rp-ct-one") == first
    assert programs.config("rp-ct-two") == other
    with pytest.raises(ProgramRefused) as conflict:
        programs.register(program_config("rp-ct-one", max_cycles=99), "repo-identity", [])
    assert "registration_conflict" in str(conflict.value)
    programs.resume("rp-ct-one")
    programs.pause("rp-ct-one")
    assert programs.config("rp-ct-one") == first
    with pytest.raises(ProgramRefused) as unknown:
        programs.config("rp-ct-absent")
    assert "unknown_program" in str(unknown.value)


def test_s11_contract_threshold_policy_override_reaches_resolved_values_and_unwired_ones_are_refused():
    """INV-THRESHOLD-POLICY-001: only implemented, unlocked registry consumers accept finite numeric overrides, and the
    resolved values and the definition identity are reported together.

    A finite override of the one wired consumer changes its resolved value and the definition hash (the identity that
    accompanies routing evidence) and leaves the packaged default definition's value untouched; a non-finite value, an
    unknown consumer and a consumer that is not wired are refused explicitly."""
    name = "skill_match.FULL_BODY_MIN_SCORE"
    default = runtime_thresholds.resolve_policy('{"version":1,"overrides":{}}')
    assert default["values"][name] == runtime_thresholds.NATIVE_DEFAULTS[name]
    text = json.dumps({"version": 1, "overrides": {name: 3.5}})
    overridden = runtime_thresholds.resolve_policy(text)
    assert overridden["values"][name] == 3.5
    assert overridden["definition_hash"] != default["definition_hash"]
    assert overridden["definition"] == {"version": 1, "overrides": {name: 3.5}}
    assert runtime_thresholds.resolve_policy('{"version":1,"overrides":{}}')["values"][name] != 3.5
    for refused in ('{"version":1,"overrides":{"%s":NaN}}' % name, '{"version":1,"overrides":{"%s":true}}' % name,
                    '{"version":1,"overrides":{"ratio_tracker.WARN_THRESHOLD":4}}',
                    '{"version":1,"overrides":{"no.such_consumer":1}}'):
        with pytest.raises(ContractError):
            runtime_thresholds.resolve_policy(refused)


@pytest.fixture
def sdd(tmp_path):
    store = MemoryStore()
    tickets = ticket_module.Tickets(store, packaged_organization(), outbox=Outbox())
    ticket = tickets.create({"title": "SDD journal contract", "problem": "Duplicate import", "impact": "Replayed evidence",
                             "rollback": "Keep prior snapshot", "evidence_refs": ["contract-test-input"],
                             "scope": ["sdd"], "acceptance_criteria": ["Idempotent import"],
                             "verification": ["Memory store"]})
    service = SDD(store, FileArtifacts(tmp_path / "artifacts"), None, ticket_binding=ticket_module.ticket_binding,
                  clock=SYSTEM_CLOCK)
    return service, ticket


def test_s11_contract_sdd_journal_is_idempotent_compare_and_swap_and_hash_linked(sdd):
    """INV-SDD-002: SDD journals retain ordered, hash-linked events; duplicate imports/proposals are idempotent and
    transitions use compare-and-swap.

    Re-registering, re-importing the same observation and re-proposing return the recorded rows and add no journal
    event; an advance with a stale expected sequence is refused (`Stale SDD transition`) and a current one is recorded
    in order; an edited journal event is refused as a break instead of being read."""
    service, ticket = sdd
    spec = load_json(ROOT / "docs/sdd/zeus-sdd.spec.json")
    source = {"mode": "working_tree_draft", "repository": "contract-test", "revision": None, "path": "spec.json"}
    row = service.register(deepcopy(spec), ticket["id"], 1, source)
    assert service.register(deepcopy(spec), ticket["id"], 1, source) == row
    environment = dict.fromkeys(ENVIRONMENT_FIELDS, "unverified-contract-input")
    environment.update(physical_device=False, form_factor="unknown", orientation="unknown")
    events = [{"sequence": 2, "scenario_id": "SCN.intent-review", "kind": "observation", "name": "contract input",
               "observed": "Observed behavior is not an oracle", "source_ref": "unverified-contract-input",
               "timestamp": None, "observed_timestamp": "2026-09-09T00:00:00+00:00"}]
    observation = service.observe(row["id"], environment, events, "contract-test-input")
    after_observe = len(service.status(row["id"])["events"])
    assert service.observe(row["id"], environment, events, "contract-test-input") == observation
    proposal = service.propose(row["id"], observation["id"])
    after_propose = len(service.status(row["id"])["events"])
    assert service.propose(row["id"], observation["id"]) == proposal
    status = service.status(row["id"])
    assert len(status["observations"]) == 1 and len(status["events"]) == after_propose == after_observe + 1
    sequence = status["sequence"]
    with pytest.raises(ContractError, match="Stale SDD transition"):
        service.request_advance(row["id"], sequence - 1)
    assert len(service.status(row["id"])["events"]) == after_propose
    blocked = service.request_advance(row["id"], sequence)
    assert blocked["status"] == "blocked" and blocked["release_authorized"] is False
    events_now = service.status(row["id"])["events"]
    assert [e["sequence"] for e in events_now] == list(range(1, len(events_now) + 1))
    assert all(a["hash"] == b["previous_hash"] for a, b in zip(events_now, events_now[1:], strict=False))
    with service.store.transaction() as tx:
        key = row["id"] + ":00000002"  # the journal's own key form: iteration id, zero-padded sequence
        victim = tx.get("sdd_events", key)
        victim["kind"] = "edited_after_the_fact"
        tx.put("sdd_events", key, victim)
    with pytest.raises(ContractError, match="journal gap or corruption"):
        service.status(row["id"])
