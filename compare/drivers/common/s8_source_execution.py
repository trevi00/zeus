"""Shared S8 scenario steps (`research.source_execution`): M7 `application/source_execution.py` (`SourceExecutions`: `_validate`, `request`,
`claim`, `result`, `complete`), characterized BEFORE the module moves (DESIGN-s8 §6 V11; the module has no entry in `branch-table-research.txt`,
so every `require`, `except` and branch of the AST is covered, see `BRANCH_COVERAGE`).

Every case mirrors a `SourceExecutions` test of M7 `tests/test_research_audits.py` (the test name is the group label), plus LABELLED additions
that reach the branches those tests do not:

- **e1_test_host_request_deduplicates_and_rejects_cross_source**: `request` (the queued row, the idempotent replay, the other command, the cross
  source, the malformed sources and commands, every authority that `_validate` checks: the audit, its source, the activation, the task's
  lease, generation and identity), then the first `claim`.
- **e2_test_host_queue_pause_cancels_pending_without_execution**: `claim` (nothing pending, the running row, the statuses it skips, the expiry
  boundary of a running row, the reclaim by a second runner as in `test_host_restart_reclaims_expired_runner_and_fences_late_result`, the
  pending rows an invalid authority cancels with its reason, every refusal of the verified execution image).
- **e3_test_completed_host_receipt_rechecks_deployment_on_consumption**: `result` (the owner, the validation, the succeeded row and the
  deployment pointer it is consumed under).
- **e4_test_host_result_preserves_evidence_but_cannot_cross_invalidated_authority**: `complete` (the succeeded row, the three invalidations
  of M7's parametrization, the receipt's own validation and binding, the fenced late result of the restart test, the missing row, the repeat).

`test_docker_source_runner_uses_only_inert_source_and_immutable_image` and `test_inventory_receipt_cannot_clear_claimed_test_coverage`
exercise `adapters.source_execution` and `application.research`, not this module; they are recorded in `M7_TESTS`.

Layer: harness (never shipped)

This module never imports `codex_harness`: everything from the product arrives through `api` (`MemoryStore`, `Workflow`, `organization`,
`SourceExecutions`, `SourceIdentity`, `ExecutionReceipt`, `ContractError`, `envelope`, `POLICY`, `now`, `advance`). M7's tests build the audit
and the release through `ResearchAudits.import_audit` and `Releases.promote`; the scenario writes the rows those leave (`research_audits`,
`research_control`, `releases`, `deployment`, `images`) directly, with the fields the module reads (LABELLED), and claims the task through the
real `Workflow` over the packaged organization. The receipts are M7 `FixtureRunner`'s: injected, never an isolated execution. For every call the
digest of each owned bucket and of the whole store before and after is recorded; the fake clock ticks once per call."""

from __future__ import annotations

from dataclasses import asdict, replace
from datetime import timedelta, timezone
from types import SimpleNamespace

import s8_research_program as R

REPO = "https://github.com/fixture/repo"
OTHER_REPO = "https://github.com/other/repo"
COMMIT = "1" * 40
TREE = "2" * 40
MANIFEST = "sha256:" + "0" * 64
OUTPUT = "sha256:" + "e" * 64
IMAGE = "sha256:" + "a" * 64
OWNED = ("source_execution_requests", "source_execution_history")
COMMAND = ["python", "--version"]
UNSET = object()


def sha(value):
    return R.canonical_digest(value)[:16]


# ---- the fixture -----------------------------------------------------------------------------------------------------------
def put(store, bucket, key, body):
    with store.transaction() as tx:
        tx.put(bucket, key, body)


def get(store, bucket, key):
    with store.transaction() as tx:
        return tx.get(bucket, key)


def scan(store, bucket):
    with store.transaction() as tx:
        return tx.scan(bucket)


def claim_task(env, audit="audit-1", owner="fixture-host", plant=True, agent="worker:github"):
    """M7 `queued_source_fixture`: one `audit_partition` task for `worker:github` (a second one for `worker:geeknews`: one active execution per agent), submitted and claimed through the real `Workflow`."""
    source = env.source
    if plant:
        put(env.store, "research_audits", audit, {"id": audit, "source": asdict(source)})
    message = env.api.envelope("task.assign", "lead:research", agent, "audit_partition", {"audit_id": audit}, "host-runner-fixture")
    env.workflow.submit(message)
    return env.workflow.claim(agent, owner)


def build(api, tag, audit=True, active=True, deployed=True, image=True, task=True):
    """M7 `queued_source_fixture`: a `MemoryStore`, the real `Workflow` over the packaged organization, the audited source, an active release with
    its verified image (planted, LABELLED) and one claimed task."""
    store = api.MemoryStore()
    workflow = api.Workflow(store, api.organization())
    env = SimpleNamespace(api=api, tag=tag, store=store, workflow=workflow, queue=api.SourceExecutions(workflow),
                          source=api.SourceIdentity(REPO, COMMIT, TREE, MANIFEST), task=None)
    if active:
        put(store, "research_control", "activation", {"status": "active", "release_id": "rel-1", "revision": "audit"})
    if deployed:
        put(store, "releases", "rel-1", {"id": "rel-1", "status": "active", "policy_hash": "policy-hash-1",
                                          "candidate": {"revision": "audit", "audit_lifecycle_version": 1}})
        put(store, "deployment", "active", {"release_id": "rel-1", "revision": "audit", "previous": None})
    if image:
        put(store, "images", "rel-1", {"id": "rel-1", "revision": "audit", "image": IMAGE})
    if task:
        env.task = claim_task(env, plant=audit)
    return env


def receipt(env, source=None, command=None, **over):
    """M7 `FixtureRunner.execute`: an injected receipt over `source` and `command` (the output document is a fixed reference)."""
    values = {"source": env.source if source is None else source, "environment_revision": "fixture-env", "command": list(COMMAND if command is None else command),
              "isolation": "fixture-isolation", "exit_status": 0, "output_ref": OUTPUT, "runner_id": "fixture-runner", "inspection_blocked": False,
              "passed": True, "outcome": "executed"}
    values.update(over)
    return env.api.ExecutionReceipt(**values)


# ---- observations ----------------------------------------------------------------------------------------------------------
def snap(store) -> dict:
    with store.transaction() as tx:
        rows = tx.records()
    out = {}
    for bucket in OWNED:
        mine = sorted([r["id"], R.canonical_digest(r["body"])] for r in rows if r["bucket"] == bucket)
        out[bucket] = "%d:%s" % (len(mine), sha(mine))
    out["all"] = sha(sorted([r["bucket"], r["id"], R.canonical_digest(r["body"])] for r in rows))
    return out


def view(value):
    """The facts of a returned request row (the row itself is recorded by digest)."""
    if isinstance(value, dict) and "task" in value and "status" in value:
        keys = ("status", "owner", "started_at", "completed_at", "at", "image", "release_id", "reason", "command", "id")
        out = {k: value[k] for k in keys if k in value}
        out["task"] = [value["task"]["id"], value["task"]["generation"]]
        out["source"] = value["source"]
        if "receipt" in value:
            out["receipt"] = {k: value["receipt"][k] for k in ("output_ref", "exit_status", "passed", "outcome", "runner_id")}
        return out
    return value


def outcome(api, fn):
    """The characterized outcome of one call: its value (by digest, with a view), or the refusal (type, whether it is the contract error, its
    text and its cause)."""
    try:
        value = fn()
    except Exception as exc:  # the refusal is the characterized result
        out = {"refused": type(exc).__name__, "is_contract_error": isinstance(exc, api.ContractError), "message": str(exc)[:240]}
        if exc.__cause__ is not None:
            out["cause"] = type(exc.__cause__).__name__
        return out
    return {"value": R.canonical_digest(value), "view": view(value)}


def step(env, fn):
    """One call with the owned-bucket digests before and after (a refusal changes none of them) and one tick of the fake clock."""
    before = snap(env.store)
    out = outcome(env.api, fn)
    after = snap(env.store)
    env.api.advance(0.001)
    return {**out, "before": before, "after": after, "changed": [k for k in before if before[k] != after[k]]}


def request(env, command=UNSET, source=None, task=None):
    command = list(COMMAND) if command is UNSET else command
    return step(env, lambda: env.queue.request(env.task if task is None else task, env.source if source is None else source, command))


def claim(env):
    return step(env, env.queue.claim)


def row_of(env, request_id):
    return get(env.store, "source_execution_requests", request_id)


def stored(env):
    return [view(r) for r in scan(env.store, "source_execution_requests")]


def queued(env, command=UNSET):
    """`request` and its id (M7: `queue.request(task, source, command)`)."""
    row = env.queue.request(env.task, env.source, list(COMMAND) if command is UNSET else command)
    env.api.advance(0.001)
    return row


def running(env, command=UNSET):
    """A claimed (running) request and its row, as M7's host tests build it."""
    queued(env, command)
    return env.queue.claim()


def backdate(env, request_id, seconds, extra_microseconds=0):
    """M7 `test_host_restart...`: `started_at` is `seconds` before the (scripted) clock."""
    row = row_of(env, request_id)
    row["started_at"] = (env.api.now() - timedelta(seconds=seconds, microseconds=extra_microseconds)).astimezone(timezone.utc).isoformat()
    put(env.store, "source_execution_requests", request_id, row)


def spoil_first(env, second_audit):
    """The audit of the request that sorts FIRST in the scan (the order of `claim`) gets another source, so `claim` meets the invalid row first."""
    first = sorted(scan(env.store, "source_execution_requests"), key=lambda r: r["id"])[0]
    audit = "audit-1" if first["task"]["id"] == env.task["id"] else second_audit
    put(env.store, "research_audits", audit, {"id": audit, "source": {**asdict(env.source), "commit": "6" * 40}})
    return first["task"]["id"] == env.task["id"]


def set_control(env, body):
    put(env.store, "research_control", "activation", body)


# ---- e1: request ----------------------------------------------------------------------------------------------------------
def e1_request(api):
    out = {}
    env = build(api, "request")
    first = request(env)
    out["request"] = first
    out["stored_rows"] = stored(env)
    again = request(env)
    out["replay"] = again
    out["replay_returns_the_stored_row"] = first["value"] == again["value"]
    other = request(env, ["true"])
    out["other_command_is_another_request"] = other
    out["other_command_other_id"] = other["view"]["id"] != first["view"]["id"]
    out["rows_after_three_calls"] = len(scan(env.store, "source_execution_requests"))
    out["cross_source_mismatch"] = request(env, ["true"], source=replace(env.source, repository=OTHER_REPO))
    out["other_commit_mismatch"] = request(env, ["true"], source=replace(env.source, commit="3" * 40))
    out["other_tree_mismatch"] = request(env, ["true"], source=replace(env.source, tree="4" * 40))
    out["other_manifest_mismatch"] = request(env, ["true"], source=replace(env.source, manifest_ref="sha256:" + "5" * 64))
    for label, source in (("version", replace(env.source, version=2)), ("repository", replace(env.source, repository="https://example.com/x/y")),
                          ("repository_git_suffix", replace(env.source, repository=REPO + ".git")), ("commit_short", replace(env.source, commit="1" * 39)),
                          ("tree_upper", replace(env.source, tree="A" * 40)), ("manifest_ref", replace(env.source, manifest_ref="manifest"))):
        out["invalid_source_" + label] = request(env, ["true"], source=source)
    for label, command in (("empty", []), ("none", None), ("empty_arg", [""]), ("int_arg", [1]), ("second_empty", ["a", ""]), ("none_arg", ["a", None]),
                           ("empty_string", ""), ("bytes_arg", [b"a"]), ("string_is_iterated", "ls"), ("tuple_is_accepted", ("true", "-v")),
                           ("dict_is_iterated", {"a": 1})):
        out["command_" + label] = request(env, command)
    out["order_source_before_command"] = request(env, [], source=replace(env.source, version=2))
    out["order_command_before_authority"] = request(env, [], source=replace(env.source, repository=OTHER_REPO))
    # `_validate` runs before the replay lookup: every invalid authority refuses even a request that is already queued
    set_control(env, {"status": "paused"})
    out["paused_refuses_a_queued_replay"] = request(env)
    out["paused_refuses_a_new_request"] = request(env, ["new"])
    set_control(env, {"status": "active"})
    out["active_again_replays"] = request(env)
    control = build(api, "control-absent", active=False)
    out["activation_absent"] = request(control)
    for label, body in (("status_missing", {}), ("status_none", {"status": None}), ("status_upper", {"status": "Active"}), ("draining", {"status": "draining"})):
        control = build(api, "control-" + label)
        set_control(control, body)
        out["activation_" + label] = request(control)
    env = build(api, "no-audit", audit=False)
    out["audit_missing"] = request(env)
    env = build(api, "audit-other-source")
    put(env.store, "research_audits", "audit-1", {"id": "audit-1", "source": {**asdict(env.source), "commit": "9" * 40}})
    out["audit_has_another_source"] = request(env)
    env = build(api, "audit-without-source", audit=False)
    put(env.store, "research_audits", "audit-1", {"id": "audit-1"})
    out["audit_without_source_field"] = step(env, lambda: env.queue.request(env.task, env.source, COMMAND))
    env = build(api, "input-without-audit-id")
    row = get(env.store, "tasks", env.task["id"])
    put(env.store, "tasks", env.task["id"], {**row, "input": {"other": 1}})
    out["task_input_without_an_audit_id_looks_up_the_empty_id"] = request(env)
    env = build(api, "input-overrides")
    put(env.store, "research_audits", "audit-2", {"id": "audit-2", "source": {**asdict(env.source), "commit": "8" * 40}})
    row = get(env.store, "tasks", env.task["id"])
    put(env.store, "tasks", env.task["id"], {**row, "input": {"audit_id": "audit-2"}})
    out["task_input_is_read_before_the_message_details"] = request(env)
    put(env.store, "tasks", env.task["id"], {**row, "input": {}})
    out["empty_task_input_falls_back_to_the_message_details"] = request(env)
    # the task's own authority (`Workflow._owned`)
    env = build(api, "task-identity")
    out["unknown_task"] = request(env, task={**env.task, "id": "no-such-task"})
    out["stale_generation"] = request(env, task={**env.task, "generation": env.task["generation"] + 1})
    out["other_owner"] = request(env, task={**env.task, "lease_owner": "someone-else"})
    env = build(api, "task-bumped")
    row = get(env.store, "tasks", env.task["id"])
    put(env.store, "tasks", env.task["id"], {**row, "generation": row["generation"] + 1})
    out["lease_generation_changed_in_the_store"] = request(env)
    env = build(api, "task-completed")
    row = get(env.store, "tasks", env.task["id"])
    put(env.store, "tasks", env.task["id"], {**row, "status": "completed"})
    out["task_no_longer_running"] = request(env)
    env = build(api, "lease-expired")
    api.advance(api.POLICY.task_lease_seconds + 5)
    out["lease_expired"] = request(env)
    return out


# ---- e2: claim -------------------------------------------------------------------------------------------------------------
def e2_claim(api):
    out = {}
    env = build(api, "empty", task=False)
    out["nothing_pending"] = claim(env)
    env = build(api, "claim")
    out["no_request_yet"] = claim(env)
    queued(env)
    out["claim"] = claim(env)
    out["claim_row_after"] = stored(env)
    out["second_claim_is_empty"] = claim(env)
    out["running_not_reclaimed"] = stored(env)
    # M7 test_host_request_deduplicates_and_rejects_cross_source: the claimed row carries the image and the release
    seconds = api.POLICY.source_execution_seconds
    out["constants"] = {"source_execution_seconds": seconds}
    # the statuses a claim skips
    env = build(api, "statuses")
    row = queued(env)
    for status in ("succeeded", "cancelled", "failed", "weird", "queued_"):
        put(env.store, "source_execution_requests", "x-" + status, {**row, "id": "x-" + status, "status": status})
    put(env.store, "source_execution_requests", row["id"], {**row, "status": "succeeded"})
    out["skipped_statuses"] = claim(env)
    # the expiry boundary of a running row: reclaimed only after `source_execution_seconds + 40`
    env = build(api, "boundary")
    first = running(env)
    backdate(env, first["id"], seconds + 40)
    out["running_exactly_at_the_limit_is_kept"] = claim(env)
    backdate(env, first["id"], seconds + 40, extra_microseconds=1)
    out["running_one_microsecond_past_the_limit_is_reclaimed"] = claim(env)
    out["reclaimed_owner_differs"] = row_of(env, first["id"])["owner"] != first["owner"]
    env = build(api, "inside")
    first = running(env)
    backdate(env, first["id"], seconds + 39)
    out["running_inside_the_limit_is_kept"] = claim(env)
    # M7 test_host_restart_reclaims_expired_runner_and_fences_late_result (the reclaim; the late result is e4)
    env = build(api, "restart")
    first = running(env)
    backdate(env, first["id"], 200)
    second = claim(env)
    out["restart_reclaims"] = second
    out["restart_owners_differ"] = row_of(env, first["id"])["owner"] != first["owner"]
    out["restart_image_and_release_kept"] = [row_of(env, first["id"])[k] for k in ("image", "release_id", "status")]
    # a running row whose started_at is missing or not text is not skipped by the expiry test (it raises, the transaction rolls back)
    env = build(api, "running-without-started-at")
    first = running(env)
    row = row_of(env, first["id"])
    row.pop("started_at")
    put(env.store, "source_execution_requests", first["id"], row)
    out["running_without_started_at"] = claim(env)
    env = build(api, "running-bad-started-at")
    first = running(env)
    row = row_of(env, first["id"])
    row["started_at"] = "yesterday"
    put(env.store, "source_execution_requests", first["id"], row)
    out["running_with_an_unparsable_started_at"] = claim(env)
    # M7 test_host_queue_pause_cancels_pending_without_execution
    env = build(api, "pause")
    queued(env)
    set_control(env, {"status": "paused"})
    out["paused_cancels_pending"] = claim(env)
    out["paused_row"] = stored(env)
    out["claim_again_after_cancel"] = claim(env)
    env = build(api, "pause-running")
    first = running(env)
    backdate(env, first["id"], seconds + 100)
    set_control(env, {"status": "paused"})
    out["paused_cancels_an_expired_running_row"] = claim(env)
    out["paused_running_row"] = stored(env)
    for label, change in (("lease_generation", "lease"), ("audit_source", "audit"), ("audit_missing", "noaudit")):
        env = build(api, "invalid-" + label)
        queued(env)
        if change == "lease":
            row = get(env.store, "tasks", env.task["id"])
            put(env.store, "tasks", env.task["id"], {**row, "generation": row["generation"] + 1})
        elif change == "audit":
            put(env.store, "research_audits", "audit-1", {"id": "audit-1", "source": {**asdict(env.source), "tree": "7" * 40}})
        else:
            put(env.store, "research_audits", "audit-1", None)
        out["cancelled_" + label] = claim(env)
        out["cancelled_" + label + "_rows"] = stored(env)
    # an invalid row is cancelled and the scan goes on to the next valid one
    env = build(api, "two-requests")
    queued(env)
    second_task = claim_task(env, audit="audit-2", owner="fixture-host-2", agent="worker:geeknews")
    second = env.queue.request(second_task, env.source, ["other"])
    out["the_first_row_is_the_task_of_audit_1"] = spoil_first(env, "audit-2")
    out["one_invalid_one_valid"] = claim(env)
    out["one_invalid_one_valid_rows"] = sorted((v["id"] == second["id"], v["status"], v.get("reason", "")) for v in stored(env))
    out["the_valid_one_is_next"] = claim(env)
    # the verified execution image (`require` of `claim`)
    cases = [("no_deployment_row", dict(deployed=False)), ("no_image_row", dict(image=False))]
    for label, kwargs in cases:
        env = build(api, "image-" + label, **kwargs)
        queued(env)
        out["image_" + label] = claim(env)
    mutations = {
        "release_missing": ("releases", "rel-1", None),
        "release_superseded": ("releases", "rel-1", {"id": "rel-1", "status": "superseded"}),
        "release_status_missing": ("releases", "rel-1", {"id": "rel-1"}),
        "image_revision_differs": ("images", "rel-1", {"id": "rel-1", "revision": "other", "image": IMAGE}),
        "image_not_a_digest": ("images", "rel-1", {"id": "rel-1", "revision": "audit", "image": "latest"}),
        "image_empty": ("images", "rel-1", {"id": "rel-1", "revision": "audit", "image": ""}),
        "image_row_empty": ("images", "rel-1", {}),
        "image_not_text": ("images", "rel-1", {"id": "rel-1", "revision": "audit", "image": 5}),
        "deployment_release_other": ("deployment", "active", {"release_id": "rel-2", "revision": "audit"}),
        "deployment_without_release": ("deployment", "active", {"revision": "audit"}),
        "deployment_revision_differs": ("deployment", "active", {"release_id": "rel-1", "revision": "other"}),
        "deployment_revision_missing": ("deployment", "active", {"release_id": "rel-1"}),
        "deployment_empty": ("deployment", "active", {}),
    }
    for label, (bucket, key, body) in mutations.items():
        env = build(api, "image-" + label)
        queued(env)
        put(env.store, bucket, key, body)
        out["image_" + label] = claim(env)
    # an invalid row cancelled in the same transaction is rolled back with the refusal
    env = build(api, "cancel-then-refuse", image=False)
    queued(env)
    second_task = claim_task(env, audit="audit-3", owner="fixture-host-3", agent="worker:geeknews")
    env.queue.request(second_task, env.source, ["third"])
    out["cancel_then_refuse_first_is_audit_1"] = spoil_first(env, "audit-3")
    out["cancel_then_refuse_rolls_back"] = claim(env)
    out["cancel_then_refuse_rows"] = sorted(v["status"] for v in stored(env))
    # the image is the one of the ACTIVE deployment at the claim
    env = build(api, "image-follows-deployment")
    queued(env)
    put(env.store, "releases", "rel-2", {"id": "rel-2", "status": "active"})
    put(env.store, "images", "rel-2", {"id": "rel-2", "revision": "audit2", "image": "sha256:" + "b" * 64})
    put(env.store, "deployment", "active", {"release_id": "rel-2", "revision": "audit2", "previous": "rel-1"})
    out["claim_uses_the_active_deployment"] = claim(env)
    return out


# ---- e3: result -------------------------------------------------------------------------------------------------------------
def e3_result(api):
    out = {}
    env = build(api, "result")
    made = queued(env)
    out["queued_result"] = step(env, lambda: env.queue.result(env.task, made["id"]))
    claimed = env.queue.claim()
    out["running_result"] = step(env, lambda: env.queue.result(env.task, made["id"]))
    env.queue.complete(claimed, receipt(env))
    out["succeeded_result"] = step(env, lambda: env.queue.result(env.task, made["id"]))
    put(env.store, "deployment", "active", {"release_id": "changed-after-completion", "revision": "audit"})
    out["superseded_before_consumption"] = step(env, lambda: env.queue.result(env.task, made["id"]))
    put(env.store, "deployment", "active", {})
    out["superseded_by_an_empty_deployment"] = step(env, lambda: env.queue.result(env.task, made["id"]))
    with env.store.transaction() as tx:
        tx.put("deployment", "active", None)
    out["superseded_by_no_deployment"] = step(env, lambda: env.queue.result(env.task, made["id"]))
    env = build(api, "result-owner")
    made = queued(env)
    out["unknown_request"] = step(env, lambda: env.queue.result(env.task, "no-such-request"))
    out["empty_request_id"] = step(env, lambda: env.queue.result(env.task, ""))
    out["other_task"] = step(env, lambda: env.queue.result({**env.task, "id": "another-task"}, made["id"]))
    out["other_generation"] = step(env, lambda: env.queue.result({**env.task, "generation": env.task["generation"] + 1}, made["id"]))
    out["owner_checked_before_authority"] = step(env, lambda: env.queue.result({**env.task, "id": "another-task"}, "no-such-request"))
    for label, change in (("paused", "pause"), ("audit_changed", "audit"), ("lease_changed", "lease")):
        env = build(api, "result-" + label)
        made = queued(env)
        if change == "pause":
            set_control(env, {"status": "paused"})
        elif change == "audit":
            put(env.store, "research_audits", "audit-1", {"id": "audit-1", "source": {**asdict(env.source), "commit": "9" * 40}})
        else:
            row = get(env.store, "tasks", env.task["id"])
            put(env.store, "tasks", env.task["id"], {**row, "generation": row["generation"] + 1})
        out["result_when_" + label] = step(env, lambda: env.queue.result(env.task, made["id"]))
    env = build(api, "result-cancelled")
    made = queued(env)
    env.queue.claim()
    put(env.store, "source_execution_requests", made["id"], {**row_of(env, made["id"]), "status": "cancelled", "reason": "planted"})
    out["cancelled_row_is_returned_without_a_deployment_check"] = step(env, lambda: env.queue.result(env.task, made["id"]))
    return out


# ---- e4: complete -----------------------------------------------------------------------------------------------------------
def history_of(env):
    return [{"request_matches": r["request_id"], "receipt_output": r["receipt"]["output_ref"], "at": r["at"]} for r in scan(env.store, "source_execution_history")]


def e4_complete(api):
    out = {}
    env = build(api, "complete")
    claimed = running(env)
    done = step(env, lambda: env.queue.complete(claimed, receipt(env)))
    out["complete"] = done
    out["completed_row"] = stored(env)
    out["history"] = history_of(env)
    out["history_key_is_the_request_and_the_owner"] = get(env.store, "source_execution_history", api.digest({"request": claimed["id"], "owner": claimed["owner"]})) is not None
    out["repeat_complete_keeps_the_succeeded_row"] = step(env, lambda: env.queue.complete(claimed, receipt(env, runner_id="second-runner")))
    out["repeat_rows"] = stored(env)
    out["repeat_history"] = history_of(env)
    # M7 test_host_result_preserves_evidence_but_cannot_cross_invalidated_authority
    for invalidate in ("pause", "lease", "deployment"):
        env = build(api, "invalidate-" + invalidate)
        claimed = running(env, ["true"])
        evidence = receipt(env, command=["true"])
        if invalidate == "pause":
            set_control(env, {"status": "paused"})
        elif invalidate == "lease":
            current = get(env.store, "tasks", env.task["id"])
            put(env.store, "tasks", env.task["id"], {**current, "generation": current["generation"] + 1})
        else:
            put(env.store, "deployment", "active", {"release_id": "changed"})
        out["invalidated_by_" + invalidate] = step(env, lambda: env.queue.complete(claimed, evidence))
        saved = row_of(env, claimed["id"])
        out["invalidated_by_%s_row" % invalidate] = [saved["status"], saved["receipt"]["output_ref"] == evidence.output_ref, "completed_at" in saved]
        out["invalidated_by_%s_history" % invalidate] = history_of(env)
    for label, body in (("audit_source", {"id": "audit-1", "source": {"repository": OTHER_REPO}}), ("audit_missing", None)):
        env = build(api, "invalidate-" + label)
        claimed = running(env)
        put(env.store, "research_audits", "audit-1", body)
        out["invalidated_by_" + label] = step(env, lambda: env.queue.complete(claimed, receipt(env)))
        out["invalidated_by_%s_row" % label] = stored(env)
    env = build(api, "deployment-gone")
    claimed = running(env)
    with env.store.transaction() as tx:
        tx.put("deployment", "active", None)
    out["deployment_gone_cancels"] = step(env, lambda: env.queue.complete(claimed, receipt(env)))
    out["deployment_gone_row"] = stored(env)
    # the receipt's own validation and its binding to the request (before any transaction)
    env = build(api, "receipt")
    claimed = running(env)
    for label, over in (("environment_empty", {"environment_revision": ""}), ("command_empty", {"command": []}), ("isolation_empty", {"isolation": ""}),
                        ("runner_empty", {"runner_id": ""}), ("passed_not_bool", {"passed": 1}), ("outcome_empty", {"outcome": ""}),
                        ("outcome_not_text", {"outcome": 5}), ("passed_with_exit_status", {"exit_status": 1}),
                        ("passed_while_blocked", {"inspection_blocked": True}), ("exit_status_text", {"exit_status": "0", "passed": False}),
                        ("output_ref_invalid", {"output_ref": "out"}), ("output_ref_none", {"output_ref": None}),
                        ("source_repository_invalid", {"source": replace(env.source, repository="https://example.com/x/y")}),
                        ("source_version", {"source": replace(env.source, version=2)}),
                        ("failed_but_valid", {"exit_status": 1, "passed": False, "outcome": "failed"}),
                        ("blocked_but_valid", {"inspection_blocked": True, "passed": False, "outcome": "isolation_unavailable"})):
        evidence = receipt(env, **over)
        out["receipt_" + label] = step(env, lambda e=evidence: env.queue.complete(claimed, e))
        if label in ("failed_but_valid", "blocked_but_valid"):
            put(env.store, "source_execution_requests", claimed["id"], {**row_of(env, claimed["id"]), "status": "running"})
    out["binding_other_repository"] = step(env, lambda: env.queue.complete(claimed, receipt(env, source=replace(env.source, repository=OTHER_REPO))))
    out["binding_other_commit"] = step(env, lambda: env.queue.complete(claimed, receipt(env, source=replace(env.source, commit="3" * 40))))
    out["binding_other_command"] = step(env, lambda: env.queue.complete(claimed, receipt(env, command=["python", "-V"])))
    out["binding_command_extended"] = step(env, lambda: env.queue.complete(claimed, receipt(env, command=COMMAND + ["x"])))
    # M7 test_host_restart_reclaims_expired_runner_and_fences_late_result
    env = build(api, "fenced")
    first = running(env, ["true"])
    backdate(env, first["id"], 200)
    second = env.queue.claim()
    out["late_result_of_the_replaced_runner"] = step(env, lambda: env.queue.complete(first, receipt(env, command=["true"])))
    saved = row_of(env, first["id"])
    out["late_result_row"] = [saved["owner"] == second["owner"], saved["owner"] != first["owner"], saved["status"], "receipt" in saved]
    out["late_result_history"] = len(scan(env.store, "source_execution_history"))
    out["the_new_runner_completes"] = step(env, lambda: env.queue.complete(second, receipt(env, command=["true"], runner_id="second-runner")))
    out["history_keeps_both_receipts"] = [history_of(env), len(scan(env.store, "source_execution_history"))]
    out["completed_by_the_second_owner"] = stored(env)
    # a result for a row the store no longer has, a row that is not running, a row without an owner
    env = build(api, "ghost")
    claimed = running(env)
    ghost = {**claimed, "id": "ghost-request"}
    out["row_missing_keeps_the_evidence"] = step(env, lambda: env.queue.complete(ghost, receipt(env)))
    out["row_missing_history"] = len(scan(env.store, "source_execution_history"))
    out["row_missing_other_owner_is_fenced"] = step(env, lambda: env.queue.complete({**claimed, "owner": "someone-else"}, receipt(env)))
    out["row_missing_other_owner_history_rows"] = len(scan(env.store, "source_execution_history"))
    env = build(api, "queued-row")
    made = queued(env)
    out["queued_row_without_an_owner_raises"] = step(env, lambda: env.queue.complete(made, receipt(env)))
    env = build(api, "cancelled-row")
    claimed = running(env)
    put(env.store, "source_execution_requests", claimed["id"], {**row_of(env, claimed["id"]), "status": "cancelled", "reason": "planted"})
    out["not_running_keeps_the_evidence_only"] = step(env, lambda: env.queue.complete(claimed, receipt(env)))
    out["not_running_rows"] = stored(env)
    return out


GROUPS = [("e1_test_host_request_deduplicates_and_rejects_cross_source", e1_request),
          ("e2_test_host_queue_pause_cancels_pending_without_execution", e2_claim),
          ("e3_test_completed_host_receipt_rechecks_deployment_on_consumption", e3_result),
          ("e4_test_host_result_preserves_evidence_but_cannot_cross_invalidated_authority", e4_complete)]

M7_TESTS = {
    "test_host_request_deduplicates_and_rejects_cross_source": "e1_test_host_request_deduplicates_and_rejects_cross_source (request, replay, cross source; the claim: e2 claim)",
    "test_host_result_preserves_evidence_but_cannot_cross_invalidated_authority": "e4_test_host_result_preserves_evidence_but_cannot_cross_invalidated_authority (pause, lease, deployment)",
    "test_host_queue_pause_cancels_pending_without_execution": "e2_test_host_queue_pause_cancels_pending_without_execution (paused_cancels_pending)",
    "test_completed_host_receipt_rechecks_deployment_on_consumption": "e3_test_completed_host_receipt_rechecks_deployment_on_consumption",
    "test_host_restart_reclaims_expired_runner_and_fences_late_result": "e2 restart_reclaims; e4 late_result_of_the_replaced_runner",
    "test_docker_source_runner_uses_only_inert_source_and_immutable_image": {"unreachable": "exercises adapters.source_execution (the Docker runner, a later layer), not this module"},
    "test_inventory_receipt_cannot_clear_claimed_test_coverage": {"unreachable": "exercises application.research and adapters.audit_runner, not this module"},
}

BRANCH_COVERAGE = {
    "SourceExecutions.__init__": "build",
    "_validate Workflow._owned": "e1 unknown_task, stale_generation, other_owner, lease_generation_changed_in_the_store, task_no_longer_running, lease_expired",
    "_validate require audit exists and has the request's source": "e1 cross_source_mismatch, other_*_mismatch, audit_missing, audit_has_another_source, audit_without_source_field, task_input_without_an_audit_id_looks_up_the_empty_id",
    "_validate task input before the message details": "e1 task_input_is_read_before_the_message_details, empty_task_input_falls_back_to_the_message_details",
    "_validate require activation active": "e1 paused_*, activation_*; e2 paused_cancels_pending; e3 result_when_paused",
    "request source.validate": "e1 invalid_source_*",
    "request require command": "e1 command_*, order_source_before_command, order_command_before_authority",
    "request idempotent replay": "e1 replay, replay_returns_the_stored_row, active_again_replays",
    "request put queued row": "e1 request, stored_rows",
    "claim skips other statuses": "e2 skipped_statuses",
    "claim skips a running row inside its limit": "e2 running_exactly_at_the_limit_is_kept, running_inside_the_limit_is_kept, running_not_reclaimed",
    "claim reclaims an expired running row": "e2 running_one_microsecond_past_the_limit_is_reclaimed, restart_reclaims",
    "claim except ContractError -> cancelled with the reason": "e2 paused_cancels_pending, cancelled_*, one_invalid_one_valid, paused_cancels_an_expired_running_row",
    "claim require the verified execution image": "e2 image_*, cancel_then_refuse_rolls_back",
    "claim running row + owner + image + release": "e2 claim, claim_row_after, claim_uses_the_active_deployment",
    "claim returns None": "e2 nothing_pending, no_request_yet, second_claim_is_empty, claim_again_after_cancel",
    "result require the owner": "e3 unknown_request, empty_request_id, other_task, other_generation, owner_checked_before_authority",
    "result _validate": "e3 result_when_*",
    "result succeeded requires the deployed release": "e3 superseded_before_consumption, superseded_by_an_empty_deployment, superseded_by_no_deployment",
    "result returns the row": "e3 queued_result, running_result, succeeded_result, cancelled_row_is_returned_without_a_deployment_check",
    "complete receipt.validate": "e4 receipt_*",
    "complete require the binding": "e4 binding_*",
    "complete history row always": "e4 history, late_result_of_the_replaced_runner, row_missing_keeps_the_evidence, not_running_keeps_the_evidence_only",
    "complete fenced late result returns": "e4 late_result_*, row_missing_*, not_running_*, queued_row_without_an_owner_raises",
    "complete except ContractError -> cancelled": "e4 invalidated_by_*, deployment_gone_cancels",
    "complete succeeded": "e4 complete, completed_row, the_new_runner_completes",
}


def run(api) -> dict:
    result, counts = {}, {}
    for name, group in GROUPS:
        result[name] = group(api)
        counts[name] = len(result[name])
    result["constants"] = {"source_execution_seconds": api.POLICY.source_execution_seconds, "task_lease_seconds": api.POLICY.task_lease_seconds}
    result["m7_tests"] = M7_TESTS
    result["branch_coverage"] = BRANCH_COVERAGE
    result["cases_per_group"] = counts
    return result
