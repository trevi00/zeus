"""RF-RT, S5 part (addendum A1 v2): the persisted research-admission disposition (a declared addition; no golden).

Representative paths:
- normal (admit, recorded and re-evaluated);
- missing evidence (research, holding) preserved across a restart without asking the policy again;
- an unresolved material contradiction (blocked) keeps ZERO dispatch through RunTask after a restart;
- a recorded resolution releases the hold, and the ordinary check runs again;
- an absent policy and an unknown disposition refuse and write nothing.
"""

from __future__ import annotations

import pytest
from test_s4_run_task import build, submit

from codex_harness.coordination.application.research_admission import (
    BUCKET,
    PersistedResearchAdmission,
    admission_key,
)
from codex_harness.kernel.errors import ContractError
from codex_harness.storage.adapters.memory_store import MemoryStore

LEASE = {"id": "task-1"}
EVIDENCE = "sha256:" + "d" * 64


class Policy:
    def __init__(self, *answers):
        self.answers, self.calls = list(answers), []

    def admit(self, tx, lease, action):
        self.calls.append((lease["id"], action))
        return self.answers.pop(0)


def rows(store):
    with store.transaction() as tx:
        return tx.scan(BUCKET)


def consult(store, admission, action="plan"):
    with store.transaction() as tx:
        return admission.admit(tx, LEASE, action)


def test_an_admitting_disposition_is_recorded_and_re_evaluated_every_time():
    store, policy = MemoryStore(), Policy({"disposition": "admit", "reason": "package fresh"},
                                          {"disposition": "exempt", "reason": "routine unchanged procedure"})
    admission = PersistedResearchAdmission(policy)
    assert consult(store, admission) == {"disposition": "admit", "reason": "package fresh", "persisted": False}
    assert consult(store, admission)["disposition"] == "exempt" and len(policy.calls) == 2
    [row] = rows(store)
    assert row["state"] == "admitted" and [h["disposition"] for h in row["history"]] == ["admit", "exempt"]


@pytest.mark.parametrize("disposition", ["research", "blocked"])
def test_a_holding_disposition_survives_restart_without_asking_the_policy_again(disposition):
    store = MemoryStore()
    first = Policy({"disposition": disposition, "reason": "material contradiction unresolved"})
    assert consult(store, PersistedResearchAdmission(first))["persisted"] is False
    restarted = Policy({"disposition": "admit", "reason": "must not be asked"})
    out = consult(store, PersistedResearchAdmission(restarted))  # a new process over the same durable store
    assert out == {"disposition": disposition, "reason": "material contradiction unresolved", "persisted": True}
    assert restarted.calls == []


def test_a_blocked_disposition_keeps_zero_dispatch_through_run_task_after_restart(tmp_path):
    first = Policy({"disposition": "blocked", "reason": "material contradiction unresolved"})
    run_task, workflow, store, _, calls = build(tmp_path, research_admission=PersistedResearchAdmission(first))
    submit(workflow)
    out = run_task.execute_one("lead:improvement")
    assert calls == [] and "Research-first admission: blocked" in out["error"]
    restarted = Policy({"disposition": "admit", "reason": "must not be asked"})
    run_task.research_admission = PersistedResearchAdmission(restarted)  # the restarted process's admission
    task = next(r for r in rows(store))
    assert task["state"] == "holding" and restarted.calls == []
    with store.transaction() as tx:
        again = run_task.research_admission.admit(tx, {"id": task["task_id"]}, "plan")
    assert again["disposition"] == "blocked" and again["persisted"] is True and calls == []


def test_a_recorded_resolution_releases_the_hold_and_the_ordinary_check_runs_again():
    store = MemoryStore()
    policy = Policy({"disposition": "research", "reason": "evidence missing"},
                    {"disposition": "admit", "reason": "applicability established"})
    admission = PersistedResearchAdmission(policy)
    consult(store, admission)
    with store.transaction() as tx:
        with pytest.raises(ContractError, match="evidence reference"):
            admission.resolve(tx, "task-1", "plan", resolution_ref="not-a-ref", actor="lead:research")
    with store.transaction() as tx:
        resolved = admission.resolve(tx, "task-1", "plan", resolution_ref=EVIDENCE, actor="lead:research")
    assert resolved["state"] == "resolved" and resolved["resolution"]["released"]["disposition"] == "research"
    assert consult(store, admission) == {"disposition": "admit", "reason": "applicability established",
                                         "persisted": False}
    with store.transaction() as tx:
        with pytest.raises(ContractError, match="No holding research admission"):
            admission.resolve(tx, "task-1", "plan", resolution_ref=EVIDENCE, actor="lead:research")


def test_an_absent_policy_or_an_unknown_disposition_refuses_and_writes_nothing():
    store = MemoryStore()
    with pytest.raises(ContractError, match="Research admission policy is not wired"):
        consult(store, PersistedResearchAdmission())
    with pytest.raises(ContractError, match="Unknown research admission disposition"):
        consult(store, PersistedResearchAdmission(Policy({"disposition": "maybe", "reason": "x"})))
    assert rows(store) == [] and admission_key("task-1", "plan") not in {r["id"] for r in rows(store)}
