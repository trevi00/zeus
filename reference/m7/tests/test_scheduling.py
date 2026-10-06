"""`schedule_audits` beside an admitted correction (self-improvement-reference-001).

The scheduler is unchanged here: it still creates one durable assignment per partition generation
and still refuses to overlap an unfinished one. These tests pin the INTERACTION the bounded repair
owner relies on (INV-AUDIT-REPAIR-001): a rejected generation is never resubmitted, a queued
correction blocks a second assignment for its partition, and once the correction checkpoints, the
ordinary continuation of the NEW generation proceeds exactly as it always did.

Every model turn is injected; no provider, Redis, PostgreSQL or host service is involved.
"""
from test_audit_repair import (  # noqa: F401  imported fixtures register with pytest
    corrections_of,
    enabled_owner,
    justified_answer,
    rejected_execution,
    repairable,
    settle_successor,
)
from test_research_audits import (  # noqa: F401  `audit` is a pytest fixture: importing registers it
    activate_fixture,
    audit,
)

from codex_harness.application.scheduling import schedule_audits
from codex_harness.domain import audit_repair as domain_repair


def rows_for(ctx, partition_id):
    with ctx.store.transaction() as tx:
        return [row for row in tx.scan("schedule") if row.get("partition_id") == partition_id]


def test_the_rejected_generation_is_never_resubmitted_by_the_scheduler(repairable):  # noqa: F811
    """The existing one-key-per-generation rule already holds the rejected draft's scope."""
    ctx = repairable
    task, _ = rejected_execution(ctx)
    before = rows_for(ctx, ctx.subsystem["partition_id"])
    assert schedule_audits(ctx.service, audit_id=ctx.audit_id) == 0
    assert rows_for(ctx, ctx.subsystem["partition_id"]) == before
    with ctx.store.transaction() as tx:
        assert len([row for row in tx.scan("tasks")
                    if row["message"]["what"]["details"].get("partition_id")
                    == ctx.subsystem["partition_id"]]) == 1
    assert task["status"] == "succeeded"


def test_a_queued_correction_blocks_a_second_assignment_for_its_partition(repairable):  # noqa: F811
    ctx = repairable
    task, _ = rejected_execution(ctx)
    repair = enabled_owner(ctx, task)
    admitted = repair.admit(ctx.audit_id)
    key = domain_repair.schedule_key(admitted["correction_id"])
    # FIXTURE: the ordinary key of the rejected generation is removed from the store, so the ONLY
    # thing that can still prevent an overlapping assignment is the correction's own schedule row.
    for row in rows_for(ctx, ctx.subsystem["partition_id"]):
        if row["id"] != key:
            del ctx.store.data["schedule", row["id"]]

    assert schedule_audits(ctx.service, audit_id=ctx.audit_id) == 0
    rows = rows_for(ctx, ctx.subsystem["partition_id"])
    assert [row["id"] for row in rows] == [key]
    assert len(corrections_of(ctx)) == 1


def test_the_ordinary_continuation_resumes_after_the_correction_checkpoints(repairable):  # noqa: F811
    ctx = repairable
    task, _ = rejected_execution(ctx)
    repair = enabled_owner(ctx, task)
    admitted = repair.admit(ctx.audit_id)
    evidence = ctx.artifacts.put("the corrected draft", "fixture")["ref"]
    successor, settled = settle_successor(ctx, repair, admitted["correction_id"],
                                          justified_answer(ctx, evidence))
    assert settled["changed"][0]["state"] == "repaired"

    created = schedule_audits(ctx.service, audit_id=ctx.audit_id)
    rows = rows_for(ctx, ctx.subsystem["partition_id"])
    with ctx.store.transaction() as tx:
        partition = tx.get("research_partitions", ctx.subsystem["partition_id"])
        queued = [row["message"] for row in tx.scan("outbox")
                  if row["message"]["what"]["details"].get("partition_id")
                  == ctx.subsystem["partition_id"]
                  and row["message"]["what"]["details"].get("generation") == 1]
    # One NEW ordinary assignment for the resumed generation: no repair context, no successor.
    assert created == 1 and len(rows) == 3
    assert partition["generation"] == 1 and len(queued) == 1
    assert "repair" not in queued[0]["what"]["details"]
    assert repair.admit(ctx.audit_id)["admitted"] is False
    assert len(corrections_of(ctx)) == 1
