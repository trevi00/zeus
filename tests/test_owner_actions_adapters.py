"""INV-OWNER-ACTIONS-001 production ports: the Git plan publisher, the assessment guardian port and the CLI.

Real: a temporary Git repository, the incumbent DB-free conductor guardian (`continuation_process`) with a
LABELLED child command (`python -c` exiting 0; no model or provider), a temporary FileArtifacts store and
the MemoryStore. Nothing reaches a live service, a provider or production state.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from types import SimpleNamespace

import pytest
from test_owner_delivery import git_repository

from codex_harness.adapters import owner_actions as adapter
from codex_harness.adapters.artifacts import FileArtifacts
from codex_harness.adapters.store import MemoryStore
from codex_harness.bootstrap import organization
from codex_harness.domain import owner_actions as do
from codex_harness.domain.model import canonical

LAUNCH = "a" * 64
DECISION = "b" * 64


def labelled_child(decision_id, correlation_id):
    """LABELLED stand-in for `zeus owner-actions assess`: exits 0 and touches nothing."""
    return [sys.executable, "-c", "import sys; sys.exit(0)"]


def test_the_assessment_guardian_is_spawned_once_per_launch_identity_and_proves_its_cleanup(tmp_path):
    ports = adapter.Assessments(FileArtifacts(str(tmp_path / "artifacts")), tmp_path / "owner-actions",
                                command=labelled_child, seconds=30)
    first = ports.start(LAUNCH, DECISION, "corr-1")
    assert first["cached"] is False and ports.start(LAUNCH, DECISION, "corr-1")["cached"] is True
    ports.join()
    observed = ports.poll(LAUNCH)
    assert observed["state"] == "exited" and observed["cleanup_confirmed"] is True and observed["exit_code"] == 0
    # A restarted coordinator (new port object) never spawns the same identity again.
    again = adapter.Assessments(FileArtifacts(str(tmp_path / "artifacts")), tmp_path / "owner-actions",
                                command=labelled_child, seconds=30)
    assert again.start(LAUNCH, DECISION, "corr-1")["cached"] is True and again.poll(LAUNCH)["state"] == "exited"
    # A launch identity that was never spawned is fenced as never entered (the one relaunch condition).
    assert again.poll("c" * 64)["state"] == "absent"


def test_the_assessor_context_is_the_bound_report_bytes_or_nothing(tmp_path):
    artifacts = FileArtifacts(str(tmp_path / "artifacts"))
    ports = adapter.Assessments(artifacts, tmp_path / "owner-actions")
    ref = artifacts.put(canonical({"answer": {"findings": ["labelled fixture report"]}}), "research-council")["ref"]
    found = {"facts": {"acceptance": {"run": {"report": {"execution_ref": ref, "sha256": "d" * 64}}}}, "members": []}
    context = ports.context({}, found)
    assert context["report"] == canonical({"findings": ["labelled fixture report"]})
    assert context["evidence_refs"] == [ref] and context["report_digest"] == "d" * 64
    missing = {"facts": {"acceptance": {"run": {"report": {"execution_ref": "sha256:" + "e" * 64}}}}}
    assert ports.context({}, missing)["report"] is None
    assert ports.context({}, {"facts": {}})["report"] is None
    document = {"schema": do.ASSESSMENT_SCHEMA, "owner_action": "x"}
    assert ports.document(document) == ports.document(document) and artifacts.document(ports.document(document)) \
        == document


def test_the_plan_commit_is_deterministic_and_another_owners_ref_is_a_conflict(tmp_path):
    repo = git_repository(tmp_path)
    data, path, ref, when = b'{"labelled":"plan"}\n', "deploy/aibox/owner-plans/own-x.json", \
        "refs/zeus/owner-plans/own-x", "2026-09-25T00:00:00+00:00"
    first = adapter.GitPlanPublisher(repo).publish(data, path, ref, when)
    second = adapter.GitPlanPublisher(repo).publish(data, path, ref, when)   # a restart re-derives it
    assert first == second and first["conflict"] is False
    shown = subprocess.run(["git", "-C", str(repo), "show", first["revision"] + ":" + path], capture_output=True,
                           check=True).stdout
    assert shown == data
    other = adapter.GitPlanPublisher(repo).publish(b'{"other":1}\n', path, ref, when)
    assert other["conflict"] is True
    assert subprocess.run(["git", "-C", str(repo), "rev-parse", ref], capture_output=True, text=True,
                          check=True).stdout.strip() == first["revision"]


def test_the_cli_status_reads_the_store_and_assess_refuses_a_foreign_row():
    store = MemoryStore()
    service = SimpleNamespace(store=store, org=organization())
    status = adapter.execute(service, argparse.Namespace(owner_actions_command="status", policy=None))
    assert status["schema"] == do.STATUS_SCHEMA and status["exit_code"] == 0 and status["actions"] == []
    with store.transaction() as tx:
        tx.put("decisions_pending", DECISION, {"id": DECISION, "phase": "review_lead", "actor": "conductor"})
    with pytest.raises(do.OwnerActionRefused, match="assessment_row_foreign"):
        adapter.execute(service, argparse.Namespace(owner_actions_command="assess", decision=DECISION,
                                                    correlation="c"))
    assert adapter.refusal(do.OwnerActionRefused("x_code"))["reason_code"] == "x_code"


def test_the_cli_parser_names_every_owner_command():
    parser = argparse.ArgumentParser()
    adapter.add_parser(parser.add_subparsers(dest="command"))
    for argv in (["owner-actions", "status"], ["owner-actions", "tick", "--policy", "p"],
                 ["owner-actions", "run", "--policy", "p", "--max-ticks", "1"],
                 ["owner-actions", "register", "--lane", "a", "--revision", "f" * 40, "--path", "x.json"],
                 ["owner-actions", "assess", "--decision", "d", "--correlation", "c"]):
        assert parser.parse_args(argv).owner_actions_command == argv[1]


def test_the_run_loop_only_wakes_and_stops_after_its_bound():
    outcomes = iter(["idle", "idle", "progressed"])
    result = adapter.run_loop(lambda: {"outcome": next(outcomes)}, interval=1, max_ticks=3, sleep=lambda s: None)
    assert result["ticks"] == 3 and result["outcomes"] == {"idle": 2, "progressed": 1}


class LedgerFixture:
    """LABELLED machine call ledger: reserves a slot; `settle` fails when `settle_fails` (an unsettled slot)."""

    def __init__(self, settle_fails=False):
        self.settle_fails, self.settled = settle_fails, []

    def reserve(self, **arguments):
        return {"id": "slot-1", "reserved_at": "2026-09-25T00:00:00+00:00"}

    def settle(self, slot_id, **kwargs):
        if self.settle_fails:
            raise OSError("ledger settlement failed (labelled injected fault)")
        self.settled.append(slot_id)


class DecidingExecutor:
    """LABELLED executor: claims (or not) the row and commits a succeeded decision; no model is called."""

    def __init__(self, store, claims=True):
        self.store, self.claims = store, claims

    def decide_one(self, agent, expected=None):
        with self.store.transaction() as tx:
            tx.put("decisions_pending", DECISION, {"id": DECISION, "phase": do.OWNER_PHASE, "status": "succeeded",
                                                   "result": {"accepted": True}})
        return {"status": "succeeded"} if self.claims else None


@pytest.mark.parametrize("settle_fails, claims, exit_code", [(False, True, 0), (True, True, 1), (False, False, 1)])
def test_the_assess_child_exits_zero_only_when_it_owned_the_claim_and_settled_every_reservation(settle_fails,
                                                                                               claims, exit_code):
    store = MemoryStore()
    service = SimpleNamespace(store=store)
    result = adapter.assess(service, DECISION, "c", "labelled-fixture-assessor",
                            executor=DecidingExecutor(store, claims), budget=LedgerFixture(settle_fails))
    # A succeeded decision alone is not the launch's outcome (R1): ownership and settlement are.
    assert result["status"] == "succeeded" and result["exit_code"] == exit_code
    assert result["calls"]["reserved"] == 1 and result["calls"]["settled"] == (0 if settle_fails else 1)
