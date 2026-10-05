"""S11 unit CT-8: behavioural tests for INV-METRIC-001, INV-SDD-001 and INV-VERIFICATION-001 (DESIGN-s11 §5 G2).

Each test names its contract ID in its own docstring (the R-L9 citation), drives the owner through its public API and
takes its expected results from the contract text in docs/contracts.md, not from the implementation.
"""

import json
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from codex_harness.composition.release_verification import verification_environment
from codex_harness.coordination.application.outbox import Outbox
from codex_harness.intake.application import tickets as ticket_module
from codex_harness.kernel.errors import ContractError
from codex_harness.kernel.ids import SYSTEM_CLOCK
from codex_harness.observation.domain.measurements import DEFINITIONS, evaluate
from codex_harness.review.application.sdd import SDD
from codex_harness.review.domain.sdd import ENVIRONMENT_FIELDS
from codex_harness.routing.adapters.organization_source import packaged_organization
from codex_harness.storage.adapters.file_artifacts import FileArtifacts
from codex_harness.storage.adapters.memory_store import MemoryStore

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)
FIRST_ATTEMPT = next(d for d in DEFINITIONS if d.metric_id == "task_first_attempt_success")


def task(key, outcome="succeeded", observed=NOW):
    return {"id": key, "status": outcome, "attempt": 1, "created_at": (observed - timedelta(hours=1)).isoformat(),
            "attempt_outcomes": [{"attempt": 1, "status": outcome, "at": (observed - timedelta(minutes=1)).isoformat()}]}


def evidence(*rows, observed=NOW):
    return {"tasks": list(rows), "decisions": [], "observed_at": observed.isoformat()}


def test_s11_contract_metric_missing_invalid_stale_future_or_insufficient_evidence_is_unknown():
    """INV-METRIC-001 (docs/contracts.md:41): "Missing, invalid, stale, future or insufficient evidence is unknown.
    Undefined targets remain observational."

    Each bad input yields status `unknown` with no ratio value; the same definition with fresh, valid, sufficient
    evidence yields a ratio, still `unknown` against its undefined target and observational (never pass/fail)."""
    # Otherwise valid evidence (its rows are consistent with its own observation time), wrong only in its age.
    old, ahead = NOW - timedelta(seconds=FIRST_ATTEMPT.freshness_seconds + 60), NOW + timedelta(minutes=5)
    stale = evidence(task("a", observed=old), observed=old)
    future = evidence(task("a", observed=ahead), observed=ahead)
    invalid = evidence(task("a"), task("a"))  # a duplicate population id is not a countable population
    bad_status = evidence(dict(task("a"), status="exploded"))
    insufficient = evidence()  # zero population
    for case in (None, stale, future, invalid, bad_status, insufficient, {"observed_at": "not-a-time"}):
        result = evaluate(FIRST_ATTEMPT, case, NOW)
        assert result.status == "unknown" and result.value is None, case
    good = evaluate(FIRST_ATTEMPT, evidence(task("a"), task("b", "failed")), NOW)
    assert good.value == 0.5 and (good.numerator, good.denominator) == (1, 2)
    assert good.status == "unknown" and good.observational is True


def test_s11_contract_metric_retries_retain_failed_attempt_outcomes():
    """INV-METRIC-001 (docs/contracts.md:41): "Retries retain failed attempt outcomes."

    A task whose first attempt failed and whose retry succeeded stays a failure of the first-attempt metric."""
    retried = dict(task("a"), attempt=2, attempt_outcomes=[
        {"attempt": 1, "status": "failed", "at": (NOW - timedelta(minutes=30)).isoformat()},
        {"attempt": 2, "status": "succeeded", "at": (NOW - timedelta(minutes=1)).isoformat()}])
    result = evaluate(FIRST_ATTEMPT, evidence(retried), NOW)
    assert (result.numerator, result.denominator) == (0, 1) and result.value == 0.0


SPEC_PATH = ROOT / "docs/sdd/zeus-sdd.spec.json"
SOURCE = {"mode": "working_tree_draft", "repository": "ct8", "revision": None, "path": "spec.json"}


@pytest.fixture
def sdd(tmp_path):
    store = MemoryStore()
    tickets = ticket_module.Tickets(store, packaged_organization(), outbox=Outbox())
    ticket = tickets.create({"title": "SDD validation contract", "problem": "Invalid specs", "impact": "Unsound scenarios",
                             "rollback": "Keep prior snapshot", "evidence_refs": ["contract-test-input"],
                             "scope": ["sdd"], "acceptance_criteria": ["Fail closed"], "verification": ["Memory store"]})
    service = SDD(store, FileArtifacts(tmp_path / "artifacts"), None, ticket_binding=ticket_module.ticket_binding,
                  clock=SYSTEM_CLOCK)
    return service, ticket, json.loads(SPEC_PATH.read_text(encoding="utf-8"))


def iterations(service):
    with service.store.transaction() as tx:
        return tx.scan("sdd_iterations")


def scenario(spec, scenario_id):
    return next(row for row in spec["scenarios"] if row["id"] == scenario_id)


def test_s11_contract_sdd_missing_unknown_uncovered_and_retired_reused_specs_fail_validation(sdd):
    """INV-SDD-001 (docs/contracts.md:1502): "Missing specs, unknown fields, uncovered requirements and reused retired
    scenario IDs fail validation."

    `SDD.register` refuses each, with the contract's reason, and records no iteration; the unmodified spec registers."""
    service, ticket, spec = sdd
    cases = {}
    cases["unknown field"] = (dict(deepcopy(spec), surprise="x"), "Invalid SDD spec fields")
    absent = deepcopy(spec)
    del absent["scenarios"]
    cases["missing scenarios"] = (absent, "Invalid SDD spec fields")
    empty = deepcopy(spec)
    empty["scenarios"] = []
    cases["no scenarios"] = (empty, "Scenarios missing")
    uncovered = deepcopy(spec)
    uncovered["requirements"].append({"id": "REQ.uncovered", "statement": "Nothing exercises this", "risk": "normal",
                                      "status": "active"})
    cases["uncovered requirement"] = (uncovered, "Requirement without an active scenario")
    for name, (document, reason) in cases.items():
        with pytest.raises(ContractError, match=reason):
            service.register(document, ticket["id"], ticket["revision"], SOURCE)
        assert iterations(service) == [], name
    first = service.register(deepcopy(spec), ticket["id"], ticket["revision"], SOURCE)
    assert first["revision"] == 1
    # A scenario retired in the registered head cannot be activated again under the same ID.
    retired = deepcopy(spec)
    scenario(retired, "SCN.cs-feedback")["status"] = "retired"
    scenario(retired, "SCN.model-transfer")["requirement_ids"].append("REQ.iteration")
    second = service.register(retired, ticket["id"], ticket["revision"], SOURCE)
    assert second["revision"] == 2
    revived = deepcopy(retired)
    scenario(revived, "SCN.cs-feedback")["status"] = "active"
    with pytest.raises(ContractError, match="Retired scenario ID cannot be reused"):
        service.register(revived, ticket["id"], ticket["revision"], SOURCE)
    assert len(iterations(service)) == 2


def test_s11_contract_sdd_superseded_iterations_cannot_append_observations_or_request_transitions(sdd):
    """INV-SDD-001 (docs/contracts.md:1502): "Superseded iterations cannot append observations or request
    transitions."

    After a changed spec is registered the first iteration is refused by `observe` and `request_advance`, and its
    journal does not grow."""
    service, ticket, spec = sdd
    first = service.register(deepcopy(spec), ticket["id"], ticket["revision"], SOURCE)
    newer = deepcopy(spec)
    newer["title"] = "A revised title"
    second = service.register(newer, ticket["id"], ticket["revision"], SOURCE)
    assert second["id"] != first["id"]
    before = service.status(first["id"])
    environment = dict.fromkeys(ENVIRONMENT_FIELDS, "unverified-contract-input")
    environment.update(physical_device=False, form_factor="unknown", orientation="unknown")
    event = {"sequence": 2, "scenario_id": "SCN.intent-review", "kind": "observation", "name": "contract input",
             "observed": "Observed behavior is not an oracle", "source_ref": "unverified-contract-input",
             "timestamp": None, "observed_timestamp": "2026-09-09T00:00:00+00:00"}
    with pytest.raises(ContractError, match="Superseded SDD specification"):
        service.request_advance(first["id"], before["sequence"])
    with pytest.raises(ContractError, match="Superseded SDD specification"):
        service.observe(first["id"], environment, [event], "contract-test-input")
    after = service.status(first["id"])
    assert (after["sequence"], len(after["events"]), after["observations"]) == (
        before["sequence"], len(before["events"]), before["observations"])


def test_s11_contract_verification_release_pytest_receives_only_disposable_endpoints_without_inherited_aliases():
    """INV-VERIFICATION-001 (docs/contracts.md:171): "Release pytest receives only disposable service endpoints, with
    inherited Zeus/Harness aliases removed."

    The environment built for the release pytest carries the disposable PostgreSQL/Redis endpoints and no inherited
    Zeus/Harness value, whatever the operator's environment held."""
    inherited = {"ZEUS_DATABASE_URL": "production-db", "ZEUS_REDIS_URL": "production-redis",
                 "HARNESS_DATABASE_URL": "production-db", "HARNESS_REDIS_URL": "production-redis",
                 "HARNESS_REDIS_NAMESPACE": "production-ns", "HARNESS_RUNTIME_DIR": "production-runtime",
                 "ZEUS_REPOSITORY": "production-path", "PATH": "executables"}
    env = verification_environment({"database_url": "disposable-db", "redis_url": "disposable-redis"}, inherited)
    assert env["HARNESS_DATABASE_URL"] == "disposable-db" and env["HARNESS_REDIS_URL"] == "disposable-redis"
    assert not any(key.startswith("ZEUS_") for key in env)
    assert "HARNESS_RUNTIME_DIR" not in env
    assert not any("production" in value for value in env.values())
