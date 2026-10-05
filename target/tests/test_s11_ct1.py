"""S11 unit CT-1: behavioural contract characterization for the release and oracle contracts (DESIGN-s11 §5.4 G2).

Each test names its contract ID in its own docstring (the R-L9 citation), quotes the contract's first concrete rule from
docs/contracts.md, drives the review context's public use case on MemoryStore (`Releases`, `SDD`), and takes its expected
results from that contract text, never from the implementation. Every candidate, review and check is a labelled fixture;
nothing claims an actual Codex, GitHub or production verification.
"""

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

import pytest

from codex_harness.coordination.application.events import EventJournal
from codex_harness.coordination.application.outbox import Outbox
from codex_harness.intake.application import tickets as ticket_module
from codex_harness.kernel.errors import ContractError
from codex_harness.kernel.ids import SYSTEM_CLOCK, digest
from codex_harness.review.adapters.sdd import load_json
from codex_harness.review.application.releases import Releases, expected_evaluator_pin
from codex_harness.review.application.sdd import SDD
from codex_harness.review.domain.sdd import ENVIRONMENT_FIELDS
from codex_harness.routing.adapters.organization_source import packaged_organization
from codex_harness.storage.adapters.file_artifacts import FileArtifacts
from codex_harness.storage.adapters.memory_store import MemoryStore

ROOT = Path(__file__).resolve().parents[2]
CHECKS = ["tests", "cli_start", "cli_file_task"]
CANDIDATE = {"revision": "candidate", "base": "base", "tree": "tree", "author": "worker:implementation"}
EVALUATOR = "e" * 40
NOW = datetime(2026, 10, 6, tzinfo=timezone.utc)


def releases_on(store):
    return Releases(store, packaged_organization(), ticket_binding=ticket_module.ticket_binding,
                    ticket_superseded=ticket_module.TicketSuperseded, events=EventJournal(), clock=SYSTEM_CLOCK)


def reviewed(releases, revision="candidate"):
    release = releases.propose(dict(CANDIDATE), {"checks": CHECKS})
    for actor in ("lead:improvement", "conductor"):
        release = releases.review(release["id"], actor, revision, True, "fixture:review")
    return release


def rejected(store):
    releases = releases_on(store)
    release = reviewed(releases)
    checks = {"tests": {"passed": False, "evidence": "fixture:tests-failed"},
              **{name: {"passed": False, "skipped": True, "evidence": "fixture:not-run"} for name in CHECKS[1:]}}
    release = releases.verify(release["id"], "candidate", release["policy_hash"], checks)
    assert release["status"] == "rejected"
    return releases, release


def snapshot(store):
    with store.transaction() as tx:
        return {(row["bucket"], row["id"]): deepcopy(row["body"]) for row in tx.records()}


def test_s11_contract_release_failed_checks_cannot_promote_and_changed_commits_need_new_approvals():
    """INV-RELEASE-001: "Failed checks cannot promote. Changed commits require new approvals." (docs/contracts.md:9).

    A review naming a commit other than the candidate's is refused (`Stale release review`) and leaves the record
    unchanged; a release whose actual checks failed becomes `rejected`, `promote` refuses it and writes no deployment;
    a release whose checks all passed is promoted to the active deployment."""
    store = MemoryStore()
    releases = releases_on(store)
    proposed = releases.propose(dict(CANDIDATE), {"checks": CHECKS})
    before = snapshot(store)
    with pytest.raises(ContractError, match="Stale release review"):
        releases.review(proposed["id"], "lead:improvement", "another-commit", True, "fixture:review")
    assert snapshot(store) == before
    ok = {name: {"passed": True, "evidence": "fixture:passed"} for name in CHECKS}
    for actor in ("lead:improvement", "conductor"):
        releases.review(proposed["id"], actor, "candidate", True, "fixture:review")
    failing = dict(ok, tests={"passed": False, "evidence": "fixture:tests-failed"})
    assert releases.verify(proposed["id"], "candidate", proposed["policy_hash"], failing)["status"] == "rejected"
    with store.transaction() as tx:
        assert tx.get("deployment", "active") is None
    before = snapshot(store)
    with pytest.raises(ContractError, match="Release not verified"):
        releases.promote(proposed["id"], None)
    assert snapshot(store) == before
    other = releases.propose({**CANDIDATE, "revision": "candidate-2"}, {"checks": CHECKS})
    for actor in ("lead:improvement", "conductor"):
        releases.review(other["id"], actor, "candidate-2", True, "fixture:review")
    assert releases.verify(other["id"], "candidate-2", other["policy_hash"], ok)["status"] == "verified"
    assert releases.promote(other["id"], None)["release_id"] == other["id"]
    with store.transaction() as tx:
        assert tx.get("deployment", "active")["release_id"] == other["id"]


def test_s11_contract_release_reverification_writes_one_empty_checked_successor_and_keeps_the_source():
    """INV-RELEASE-REVERIFY-001: a check-rejected release "can only get fresh verification through
    `Releases.request_reverification(...)`", which "writes ONE successor, `digest({"reverify_of": source_id})`"
    (docs/contracts.md:3589-3613).

    The conductor's request creates a `reviewed` successor with that id, the exact candidate, policy and policy hash,
    `checks: {}` and the verbatim inherited reviews, and one `release.reverification_requested` event; the source row is
    byte-for-byte unchanged; an identical request returns the same successor with no write; a different reason is
    refused `Conflicting reverification request`; an actor without the conductor role, an empty reason and a source
    that is not check-rejected are refused with no write."""
    store = MemoryStore()
    releases, source = rejected(store)
    request = {"actor": "conductor", "expected_revision": "candidate", "expected_policy_hash": source["policy_hash"],
               "reason": "fixture: short TEMP diagnosis", "evidence": "fixture:diagnosis-receipt"}
    before = snapshot(store)
    with pytest.raises(ContractError):
        releases.request_reverification(source["id"], **{**request, "actor": "lead:improvement"})
    with pytest.raises(ContractError):
        releases.request_reverification(source["id"], **{**request, "reason": " "})
    assert snapshot(store) == before
    live = releases.propose({**CANDIDATE, "revision": "candidate-2"}, {"checks": CHECKS})  # not rejected: no source
    before = snapshot(store)
    with pytest.raises(ContractError, match="Release is not check-rejected"):
        releases.request_reverification(live["id"], **{**request, "expected_revision": "candidate-2"})
    assert snapshot(store) == before
    successor = releases.request_reverification(source["id"], **request, now=NOW)
    assert successor["id"] == digest({"reverify_of": source["id"]})
    assert successor["status"] == "reviewed" and successor["checks"] == {}
    assert successor["candidate"] == source["candidate"] and successor["policy"] == source["policy"]
    assert successor["policy_hash"] == source["policy_hash"] and successor["reverify_of"] == source["id"]
    assert successor["reviews"] == source["reviews"]
    assert successor["inherited_reviews"] == {"release_id": source["id"], "digest": digest(source["reviews"])}
    assert successor["reverification"]["source_checks_digest"] == digest(source["checks"])
    after = snapshot(store)
    assert after[("releases", source["id"])] == before[("releases", source["id"])]
    assert set(after) - set(before) >= {("releases", successor["id"])}
    assert all(after[key] == before[key] for key in before)
    assert releases.request_reverification(source["id"], **request, now=NOW) == successor
    assert snapshot(store) == after
    with pytest.raises(ContractError, match="Conflicting reverification request"):
        releases.request_reverification(source["id"], **{**request, "reason": "fixture: another reason"})
    assert snapshot(store) == after


def approval_for(release):
    return {"source_release_id": release["id"], "base": release["candidate"]["base"], "evaluator_revision": EVALUATOR,
            "evaluator_tree": "f" * 40, "patch_sha256": "a" * 64, "paths": ["tests/test_fixture.py"],
            "evidence": "sha256:" + "b" * 64, "approved_by": "conductor"}


def migrate(releases, release, approval, **overrides):
    # Labelled: the trusted resolver's result for a fixture repository that agrees with the approval.
    return releases.request_evaluator_migration(
        release["id"], "conductor", expected_revision="candidate", expected_policy_hash=release["policy_hash"],
        approval=approval, resolved_pin=overrides.pop("resolved_pin", expected_evaluator_pin(approval)),
        now=NOW, **overrides)


def test_s11_contract_release_evaluator_migration_changes_only_the_policy_revision_and_pins_must_match():
    """INV-RELEASE-EVALUATOR-MIGRATION-001: the successor "policy = {**source.policy, "revision": E} (the check list is
    unchanged) with its own `policy_hash`, `checks: {}`, no image, `reverify_of` and an `evaluator_migration` receipt";
    "a wrong tree, patch or ancestry ... therefore writes nothing"; the source is "never changed"
    (docs/contracts.md:3640-3680).

    The migration of a check-rejected source writes ONE successor keyed by the source alone, with the exact candidate
    and reviews, only `policy.revision` changed (so a new policy hash) and empty checks; the source is unchanged; an
    identical request replays with no write; a resolved pin that differs from the approval writes nothing; a
    migrated successor cannot be reverified or migrated again (`unsupported_evaluator_reverification`)."""
    store = MemoryStore()
    releases, source = rejected(store)
    approval = approval_for(source)
    before = snapshot(store)
    wrong = {**expected_evaluator_pin(approval), "evaluator_tree": "0" * 40}
    with pytest.raises(ContractError, match="Evaluator pin does not match the repository"):
        migrate(releases, source, approval, resolved_pin=wrong)
    assert snapshot(store) == before
    successor = migrate(releases, source, approval)
    assert successor["id"] == digest({"evaluator_migration_of": source["id"]})
    assert successor["policy"] == {**source["policy"], "revision": EVALUATOR}
    assert successor["policy_hash"] == digest(successor["policy"]) != source["policy_hash"]
    assert successor["policy"]["checks"] == source["policy"]["checks"]
    assert successor["candidate"] == source["candidate"] and successor["reviews"] == source["reviews"]
    assert successor["checks"] == {} and successor["status"] == "reviewed" and "image" not in successor
    assert successor["reverify_of"] == source["id"] and successor["evaluator_migration"]["evaluator_revision"] == EVALUATOR
    after = snapshot(store)
    assert all(after[key] == before[key] for key in before)
    assert migrate(releases, source, approval) == successor
    assert snapshot(store) == after
    with pytest.raises(ContractError):
        migrate(releases, source, {**approval, "evidence": "sha256:" + "c" * 64})
    assert snapshot(store) == after
    with pytest.raises(ContractError, match="unsupported_evaluator_reverification"):
        migrate(releases, successor, approval_for(successor))
    assert snapshot(store) == after


@pytest.fixture
def sdd(tmp_path):
    store = MemoryStore()
    tickets = ticket_module.Tickets(store, packaged_organization(), outbox=Outbox())
    ticket = tickets.create({"title": "Oracle contract", "problem": "Imported observation", "impact": "No authority",
                             "rollback": "Keep prior snapshot", "evidence_refs": ["contract-test-input"],
                             "scope": ["sdd"], "acceptance_criteria": ["Proposal only"],
                             "verification": ["Memory store"]})
    return SDD(store, FileArtifacts(tmp_path / "artifacts"), None, ticket_binding=ticket_module.ticket_binding,
               clock=SYSTEM_CLOCK), ticket


def test_s11_contract_oracle_imported_observations_carry_no_expected_outcome_or_authority(sdd):
    """INV-ORACLE-001: "Imported observations and structural coverage cannot populate approved expected outcomes,
    certify real-device execution, authenticate human QA, or authorize a release. Gaps remain visible."
    (docs/contracts.md:1503).

    An imported observation is proposed as observations only: the proposal is `proposal_only`, requires human oracle
    review, is not accepted, carries no expected outcome beyond the spec's own and no gap is hidden; the gate report counts
    it as neither executed by a runner nor human-accepted; a transition request is blocked and authorizes no release; a verdict
    claiming an authenticated human provider is refused when none is configured."""
    service, ticket = sdd
    spec = load_json(ROOT / "docs/sdd/zeus-sdd.spec.json")
    source = {"mode": "working_tree_draft", "repository": "contract-test", "revision": None, "path": "spec.json"}
    row = service.register(deepcopy(spec), ticket["id"], 1, source)
    environment = dict.fromkeys(ENVIRONMENT_FIELDS, "unverified-contract-input")
    environment.update(physical_device=False, form_factor="unknown", orientation="unknown")
    claim = "Observed behavior is not an oracle"
    events = [{"sequence": 2, "scenario_id": "SCN.intent-review", "kind": "observation", "name": "contract input",
               "observed": claim, "source_ref": "unverified-contract-input", "timestamp": None,
               "observed_timestamp": "2026-09-09T00:00:00+00:00"}]
    observation = service.observe(row["id"], environment, events, "contract-test-input")
    proposal = service.propose(row["id"], observation["id"])
    assert proposal["status"] == "requires_human_oracle_review" and proposal["acceptance_passed"] is False
    document = service.artifacts.document(proposal["artifact_ref"])
    assert document["authority"] == "proposal_only" and document["acceptance_passed"] is False
    assert document["status"] == "requires_human_oracle_review"
    assert document["sequence_complete"] is False  # the journal starts at sequence 2: the gap stays visible
    assert document["observations"]["SCN.intent-review"][0]["observed"] == claim
    assert not {"expected", "then", "approved_expected"} & set(document)
    denominators = service.status(row["id"])["report"]["denominators"]
    assert denominators["scenarios_executed_by_runner"] == 0 and denominators["human_accepted"] == 0
    blocked = service.request_advance(row["id"], service.status(row["id"])["sequence"])
    assert blocked["status"] == "blocked" and blocked["release_authorized"] is False
    with pytest.raises(ContractError, match="Authenticated human authority requires a configured decision provider"):
        service.record_gate_verdict(row["id"], {"authority": "authenticated_provider"})
