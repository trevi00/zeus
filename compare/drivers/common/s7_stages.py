"""Shared S7 scenario steps (`delivery.stages`): every stage handler of one M7 `HostDelivery.tick`
(`application/host_delivery.py`), characterized BEFORE the V8 split moves them (DESIGN-s7 §2, TRACE-s7 §5.1-§5.3).

Groups (each labelled in the result; the M7 tests they mirror are named at each function):

1. **normal_path**: one delivery from `registered` to `active`, the stage sequence and each tick's settle on the queue row.
2. **verify**: `_verify` over the labelled `Verifier` (the port missing or unavailable, a reconcile that is not clear,
   cleanup unconfirmed, every evaluation verdict, `release_<status>`, `release_verdict_refused`, a hook candidate).
3. **publish_ci_merge**: `_publish`, `_observe_ci` and `_merge` (every enter/pending/halt of TRACE §5.1, the lost publish
   and merge responses, qualification, the `fast_forward` merger, the predecessor binding, a definite `MergeRefused`).
4. **prepare_drain_switch**: `_prepare_switch`, `_drain` and `_switch`.
5. **consume_rollback**: `_consume`, `_begin_rollback` and `_rollback`.
6. **fence_and_ambiguity**: the four `AmbiguousEffect` raise sites (`_record`, `_lifecycle`, `_commit_verification`,
   `_promote`), each reached with the fence moved between the effect and its record, and the `_settle` mapping.
7. **coverage**: every TRACE §5.1 reason and stage the cases reached, `{"unreachable": ...}` for the rest.

Each case reports its ticks in order (the whole tick receipt: `stage`, `outcome`, `reason_code`, `controller`,
`ambiguous_effect`, `blocked`, ...), the queue row and the intent stage after each tick, the double's recorded calls
(GitHub publishes/merges/observations/qualifications, host calls) and the digests of every bucket at the end.

Layer: harness (never shipped)

Every double is in `s7_delivery` and LABELLED; this module never runs GitHub, a host, a process or a verifier. The rows it
writes itself are LABELLED fixtures of M7's shapes, each named where it is written. Nothing here is an actual Codex,
GitHub, host or production verification.
"""

from __future__ import annotations

import s7_delivery as D

PAST = "2000-01-01T00:00:00+00:00"
MOVED = "7" * 40            # another writer's commit on main (labelled)
SUCCESSOR_REVISION = "5" * 40
TICK_KEYS = ("stage", "outcome", "reason_code", "error_type", "controller", "ambiguous_effect", "claim", "attempts",
             "head", "pr_number", "merged_revision", "descriptor_sha256", "previous_descriptor_sha256", "instance_id",
             "canary", "rollback", "active", "blocked", "next_action", "at", "plan_id", "release_id", "target_id")
QUEUE_KEYS = ("status", "attempt", "retry_at", "lease_until", "generation", "reason", "last")


def rows(store, bucket):
    with store.transaction() as tx:
        return tx.scan(bucket)


def get(store, bucket, key):
    with store.transaction() as tx:
        return tx.get(bucket, key)


def put(store, bucket, key, body):
    with store.transaction() as tx:
        tx.put(bucket, key, body)


class Run:
    """One wired delivery (`s7_delivery.build`) whose every tick is recorded with the queue row it settled to."""

    def __init__(self, api, label, **kwargs):
        self.api, self.label, self.ticks = api, label, []
        self.system = D.build(api, **kwargs)
        self.extra = {}

    # ---- views ----------------------------------------------------------------------------------------------
    @property
    def delivery(self):
        return self.system["delivery"]

    @property
    def github(self):
        return self.system["github"]

    @property
    def host(self):
        return self.system["host"]

    @property
    def store(self):
        return self.system["store"]

    def release_id(self, system=None):
        return (system or self.system)["release"]["id"]

    def queue_row(self, release_id=None):
        row = get(self.store, "release_queue", release_id or self.release_id())
        if row is None:
            return None
        return {key: row.get(key) for key in QUEUE_KEYS if key in row} | {"has_owner": bool(row.get("owner"))}

    def intent(self, plan_id=None):
        return D.intent_of(self.system, plan_id)

    def intent_view(self, plan_id=None):
        row = self.intent(plan_id)
        if row is None:
            return None
        return {key: row.get(key) for key in ("stage", "previous_stage", "outcome", "reason_code", "attempts",
                                               "stage_deadline", "merged_revision", "head", "switch",
                                               "candidate_instance_id", "rollback") if key in row}

    # ---- ticks ----------------------------------------------------------------------------------------------
    def tick(self, plan_id=None, *, advance=1, note=None):
        result = self.delivery.tick(plan_id) if plan_id else self.delivery.tick()
        self.api.advance(advance)
        entry = {"n": len(self.ticks), "result": {key: result.get(key) for key in TICK_KEYS if key in result},
                 "queue": self.queue_row(result.get("release_id") or None) if result.get("release_id") else None,
                 "intent": self.intent_view(result.get("plan_id")) if result.get("plan_id") else None}
        if note:
            entry["note"] = note
        self.ticks.append(entry)
        return result

    def wait(self, seconds):
        """The ONE timeline moves (never a sleep): a backoff, a stage deadline or a lease is reached by it."""
        self.api.advance(seconds)

    def until(self, stage, limit=40, plan_id=None):
        """Tick until the tick that ENTERED `stage` (or a stop); never a sleep, one fake second per tick."""
        out = []
        for _ in range(limit):
            result = self.tick(plan_id)
            out.append(result)
            if result["stage"] == stage or result["outcome"] in {"blocked", "refused", "conflict"}:
                break
        return out

    def stage_path(self):
        seen = []
        for entry in self.ticks:
            stage = entry["result"]["stage"]
            if not seen or seen[-1] != stage:
                seen.append(stage)
        return seen

    def report(self, **extra):
        github, host = self.github, self.host
        return {
            "label": self.label, "stage_path": self.stage_path(), "ticks": self.ticks,
            "github": {"publishes": github.publishes, "merges": github.merges, "observations": github.observations,
                       "qualifications": github.qualifications, "main": github.main, "mainline": github.mainline,
                       "prs": sorted(github.prs)},
            "host": {"calls": host.calls, "descriptor": D.canonical_digest(host._st(self.system["target"])["descriptor"]),
                     "running": host.running(self.system["target"])},
            "intent": self.intent_view(), "queue": self.queue_row(),
            "buckets": D.snapshot(self.store), **self.extra, **extra}


def stop(run):
    D.stop_target(run.system)
    return run


def supersede(run):
    """M7 `supersede`: a LABELLED injected supersession. This controller's lease expires and a successor claims."""
    with run.store.transaction() as tx:
        row = tx.get("release_queue", run.release_id())
        row["lease_until"] = PAST
        tx.put("release_queue", row["id"], row)
        lock = tx.get("deployment_locks", "controller") or {}
        tx.put("deployment_locks", "controller", {**lock, "lease_until": PAST})
    claimed = run.api.queue(run.store).claim()
    return {"claimed": claimed is not None and claimed["id"] == run.release_id()}


def free_queue(run):
    """M7's reconciliation step after a supersession: the successor's lease is released and the row re-armed
    (LABELLED fixture: what `ReleaseQueue` would show once the successor finished)."""
    with run.store.transaction() as tx:
        tx.put("deployment_locks", "controller", {"owner": None, "lease_until": None})
        row = tx.get("release_queue", run.release_id())
        row.update(status="queued", owner=None, lease_until=None, retry_at=None, attempt=0)
        tx.put("release_queue", row["id"], row)


def canary_passing(verdicts):
    """M7's injected canary: `verdicts["passed"]` decides, with a fixed failing reason."""
    def canary(target, descriptor, startup):
        return {"passed": verdicts["passed"], "reason_code": None if verdicts["passed"] else "canary_fixture_failed"}
    return canary


def successor(run, *, plan_id="delivery-plan-2", revision=SUCCESSOR_REVISION, expected=None, base=None, **overrides):
    """M7 `second_plan`/the rollback tests' successor: a reviewed release cut on the CURRENT main, and its plan."""
    api = run.api
    record = D.successor_candidate(run.system, revision=revision, branch="harness/" + plan_id, task_id=plan_id)
    if base is not None:
        record["base"] = base
    release = D.reviewed_release(api, run.store, run.system["org"], record_candidate=record)
    plan = D.plan_document(api, release, plan_id=plan_id, expected=expected, **overrides)
    run.delivery.register(plan, D.pin(path="docs/zeus/operations/%s.json" % plan_id))
    return {"release": release, "plan": plan}


# ---- 1. the normal path ----------------------------------------------------------------------------------------
def normal_path(api):
    """M7 `test_normal_path_publishes_observes_ci_merges_switches_and_proves_consumption`, with each settle."""
    run = Run(api, "normal_path")
    results = run.until(api.ACTIVE)
    idle = run.tick()
    report = run.report(reached_active=results[-1]["stage"] == api.ACTIVE,
                        descriptor_row=get(run.store, api.BUCKET_DESCRIPTORS, "canary-service"),
                        deployment=get(run.store, "deployment", "active"),
                        release=get(run.store, "releases", run.release_id()),
                        idle_after_active=D.canonical_digest(idle["outcome"]))
    stop(run)
    return report


# ---- 2. verify -------------------------------------------------------------------------------------------------
UNCONFIRMED = {"verdict": "checked", "passed": True, "image": None, "receipt": None, "state": "evaluated",
               "evaluation": "fixture-evaluation-receipt", "cleanup": {"state": "unconfirmed"},
               "checks": {"tests": {"passed": True, "evidence": "fixture-incumbent-check-receipt"}}}


def checked(**fields):
    """A LABELLED `Verifier.evaluate` outcome of the `checked` shape, with fields replaced."""
    return {**UNCONFIRMED, "cleanup": {"state": "confirmed"}, **fields}


def verifying(api, label, **verifier_kwargs):
    """A reviewed, unverified release behind the labelled `Verifier` port (M7 tests/test_host_delivery_verification.py,
    without the real evaluator); the first tick enters `verifying`."""
    verifier = D.Verifier(api, **verifier_kwargs)
    run = Run(api, label, verified=False, verifier=verifier)
    run.verifier = verifier
    run.tick(note="registered enters verifying")
    return run


def set_release(run, **fields):
    """LABELLED injected fact: the release record (owned by `Releases`) changed under the delivery."""
    record = get(run.store, "releases", run.release_id())
    put(run.store, "releases", run.release_id(), {**record, **fields})


def verify(api):
    out = {}
    # No port at all, then a port that cannot be used: the wait is `verifier_unavailable` (unavailable, queue retry).
    run = Run(api, "verifier_missing", verified=False)
    run.tick(note="registered enters verifying")
    run.tick(note="no verifier port: unavailable")
    run.tick(note="the retry is not due")
    run.wait(120)
    run.tick(note="due again, still unavailable")
    out["verifier_missing"] = run.report()
    run = verifying(api, "verifier_unusable", usable=False)
    run.tick(note="port present but not usable")
    out["verifier_unusable"] = run.report()
    # A reconcile that is not clear is a named wait: no attempt, no transition.
    run = verifying(api, "reconcile_not_clear", reconciled={"state": "owner_alive", "reason_code":
                                                            "verification_owner_alive", "resolved": {}})
    run.tick(note="reconcile answers not clear: pending")
    run.tick(note="again: the attempt debt is unchanged")
    out["reconcile_not_clear"] = run.report(attempts=run.verifier.attempts)
    # A passing evaluation whose cleanup is unconfirmed: the verdict stays, the stage waits for the cleanup.
    run = verifying(api, "cleanup_unconfirmed", outcome=UNCONFIRMED)
    run.tick(note="evaluated: verdict recorded, cleanup unconfirmed: pending")
    run.tick(note="the attempt is still unresolved: pending")
    attempt = run.intent()["verification"]["attempts"][0]["attempt_id"]
    run.verifier.reconciled = {"state": "clear", "reason_code": None, "resolved": {
        attempt: {"state": "confirmed", "receipt": "fixture-cleanup-receipt"}}}
    run.tick(note="reconcile proved the cleanup: the verified release enters publishing")
    out["cleanup_unconfirmed"] = run.report(release_status=get(run.store, "releases", run.release_id())["status"])
    # Every evaluation verdict.
    verdicts = {
        "interrupted": {"verdict": "interrupted", "state": "interrupted", "cleanup": {"state": "confirmed"}},
        "retry": {"verdict": "retry", "reason_code": "verification_observation_unavailable",
                  "error_type": "TimeoutError", "state": "evaluated", "cleanup": {"state": "confirmed"}},
        "refused": {"verdict": "refused", "error_type": "ContractError", "state": "evaluated",
                    "cleanup": {"state": "confirmed"}},
        "unknown_verdict": {"verdict": "surprise", "state": "evaluated", "cleanup": {"state": "confirmed"}},
        "fence_lost": {"verdict": "fence_lost", "state": "evaluated", "cleanup": {"state": "confirmed"}},
        "fence_unobservable": {"verdict": "fence_unobservable", "state": "evaluated",
                               "cleanup": {"state": "confirmed"}},
        "rejected": checked(passed=False, checks={"tests": {"passed": False, "evidence": "fixture-failed-check"}}),
        "superseded": checked(verdict="superseded", reason="fixture ticket revision"),
        "verdict_refused": checked(checks={"unknown-check": {"passed": True, "evidence": "fixture-extra-check"}}),
    }
    for name, outcome in verdicts.items():
        run = verifying(api, "verdict_" + name, outcome=outcome)
        run.tick(note="evaluation returns the " + name + " verdict")
        run.tick(note="the next tick")
        if name == "fence_unobservable":
            run.wait(7200)
            run.tick(note="after the lease: the next owner reconciles first")
        out["verdict_" + name] = run.report(release_status=get(run.store, "releases", run.release_id())["status"],
                                            attempts=run.verifier.attempts)
    # The verified release enters publishing (the default labelled Verifier: the incumbent checks pass).
    run = verifying(api, "verified_enters_publishing")
    run.tick(note="the evaluation verifies the release: publishing")
    out["verified_enters_publishing"] = run.report(release_status=get(run.store, "releases", run.release_id())["status"],
                                                   attempts=run.verifier.attempts, prepared=run.verifier.prepared,
                                                   evaluated=run.verifier.evaluated)
    run = verifying(api, "prepare_error", prepare_error=OSError("injected: the disk record is lost"))
    run.tick(note="the attempt is durable, its disk record is not: unavailable")
    out["prepare_error"] = run.report(attempts=run.verifier.attempts)
    run = verifying(api, "evaluate_error", evaluate_error=RuntimeError("injected: the evaluator crashed"))
    run.tick(note="the evaluator raises with no observation in flight: unavailable")
    out["evaluate_error"] = run.report(attempts=run.verifier.attempts)
    # A hook candidate never reaches an attempt.
    run = verifying(api, "hook_candidate")
    record = get(run.store, "releases", run.release_id())
    put(run.store, "releases", run.release_id(), {**record, "candidate": {**record["candidate"], "hook_id": "fixture-hook"}})
    run.tick(note="a hook candidate halts before any attempt exists")
    out["hook_candidate"] = run.report(attempts=run.verifier.attempts)
    # The release record refused by its gate: inside `verifying` (after the reconcile) and outside it (at once).
    run = verifying(api, "gate_refused_in_verifying")
    set_release(run, status="rejected")
    run.tick(note="the gate refuses inside _verify")
    out["gate_refused_in_verifying"] = run.report(attempts=run.verifier.attempts)
    run = Run(api, "gate_refused_outside_verifying")
    run.tick(note="registered enters publishing")
    set_release(run, status="cancelled")
    run.tick(note="the gate refuses before the stage runs")
    out["gate_refused_outside_verifying"] = run.report()
    return out


# ---- 3. publish, ci, merge -------------------------------------------------------------------------------------
def restarted(run):
    """M7 `test_a_lost_push_response...`: a SECOND controller over the SAME durable state, as a restart would be."""
    old = run.delivery
    run.system["delivery"] = run.api.HostDelivery(
        run.store, run.system["org"], github=old.github, hosts=old.hosts, canaries=old.canaries,
        clock=D.clock(run.api), enabled=True, resume_seconds=0)


def merged_ff(api, label, **github):
    """The `fast_forward` merger (M7 tests/test_host_delivery_requalification.py `ff_build`)."""
    return Run(api, label, github=D.FakeGitHub(api, fast_forward=True, **github))


def external_merge(run, revision=D.MERGED_REVISION):
    """LABELLED provider fact (M7 `test_an_external_merge_...`): the PR was merged in the UI."""
    run.github.pr = {**run.github.pr, "state": "MERGED", "merged_revision": revision}
    run.github.main = revision


def publish(api):
    out = {}
    run = Run(api, "lost_publish_response")
    run.github.publish_error = TimeoutError("injected: publish response lost")
    run.tick(note="registered enters publishing")
    run.tick(note="the PR was created, its response was lost: unavailable")
    run.github.publish_error = None
    run.wait(120)
    run.tick(note="the existing PR is adopted, never published twice")
    out["lost_publish_response"] = run.report()
    run = Run(api, "publish_head_mismatch", github=D.FakeGitHub(api, head="9" * 40))
    run.tick()
    run.tick(note="the PR head is not the reviewed revision")
    out["publish_head_mismatch"] = run.report()
    run = Run(api, "reviewed_base_moved_before_publish")
    run.github.main = MOVED
    run.tick()
    run.tick(note="main moved after the review: no PR, no CI")
    out["reviewed_base_moved_before_publish"] = run.report()
    run = merged_ff(api, "reviewed_base_moved_before_publish_ff")
    run.github.main = MOVED
    run.until(api.AWAITING_CI, limit=4)
    out["reviewed_base_moved_before_publish_ff"] = run.report()
    run = Run(api, "github_port_unavailable")
    run.tick()
    run.delivery.github = None
    run.tick(note="no GitHub port: refused")
    out["github_port_unavailable"] = run.report()
    run = Run(api, "github_outage")
    run.github.observe_error = ConnectionError("injected: GitHub unreachable")
    run.tick()
    run.tick(note="GitHub unreachable: stage_unavailable")
    run.github.observe_error = None
    run.wait(120)
    run.tick(note="GitHub is back")
    out["github_outage"] = run.report()
    return out


def ci(api):
    out = {}
    run = Run(api, "ci_pending_then_timeout", github=D.FakeGitHub(api, checks=((D.CHECK, "pending"),)))
    run.until(api.AWAITING_CI, limit=3)
    run.tick(note="the check is pending: the lease goes back, the deadline does not move")
    run.tick(note="still pending, bounded")
    run.wait(600)
    run.tick(note="past ci_timeout_seconds")
    out["ci_pending_then_timeout"] = run.report()
    for name, github in (("ci_check_missing", {"checks": ()}),
                         ("ci_other_check_only", {"checks": (("other", "success"),)}),
                         ("ci_check_failed", {"checks": ((D.CHECK, "failure"),)})):
        run = Run(api, name, github=D.FakeGitHub(api, **github))
        run.until(api.AWAITING_CI, limit=3)
        run.tick(note="the required check is " + name)
        out[name] = run.report()
    run = Run(api, "ci_head_changed")
    run.until(api.AWAITING_CI, limit=3)
    run.github.head = "7" * 40
    run.github.pr = {**run.github.pr, "head": "7" * 40}
    run.tick(note="the PR head moved: requalification, never a silent rebase")
    out["ci_head_changed"] = run.report()
    run = Run(api, "ci_publication_missing")
    run.until(api.AWAITING_CI, limit=3)
    run.github.prs.clear()
    run.tick(note="the recorded publication is gone: a definite refusal, no second publish")
    out["ci_publication_missing"] = run.report()
    run = Run(api, "ci_passes")
    run.until(api.MERGE_INTENDED, limit=4)
    out["ci_passes"] = run.report()
    run = Run(api, "already_on_main_does_not_skip_checks",
              github=D.FakeGitHub(api, fast_forward=True, checks=((D.CHECK, "pending"),)))
    run.until(api.AWAITING_CI, limit=3)
    run.github.mainline.append(D.REVISION)
    run.github.main = D.REVISION
    run.tick(note="a candidate already on main is recovery, never CI approval")
    out["already_on_main_does_not_skip_checks"] = run.report()
    return out


def merge(api):
    out = {}
    run = Run(api, "lost_merge_response")
    run.until(api.MERGE_INTENDED, limit=4)
    run.github.merge_error = TimeoutError("injected: merge response lost")
    run.tick(note="the merge happened, its response was lost: unavailable")
    run.github.merge_error = None
    run.wait(120)
    run.tick(note="the merge is recognized and qualified, never merged again")
    out["lost_merge_response"] = run.report()
    run = Run(api, "recovered_merge_tree_mismatch")
    run.until(api.MERGE_INTENDED, limit=4)
    run.github.merge_error = TimeoutError("injected: merge response lost")
    run.tick()
    run.github.merge_error = None
    run.github.merged_tree = "d" * 64
    run.wait(120)
    run.tick(note="the recovered merge does not carry the reviewed tree")
    run.wait(600)
    run.tick(note="a blocked delivery is not re-observed into qualification")
    out["recovered_merge_tree_mismatch"] = run.report()
    run = Run(api, "performed_merge_tree_mismatch", github=D.FakeGitHub(api, merged_tree="d" * 64))
    run.until(api.MERGED, limit=6)
    out["performed_merge_tree_mismatch"] = run.report()
    run = Run(api, "merge_unqualified")
    run.until(api.MERGE_INTENDED, limit=4)
    run.github.qualify = None    # LABELLED: a merger port without the qualification method
    run.tick(note="no qualify: merge_unqualified")
    out["merge_unqualified"] = run.report()
    run = Run(api, "merge_publication_missing")
    run.until(api.MERGE_INTENDED, limit=4)
    run.github.prs.clear()
    run.tick(note="publication_missing at the merge")
    out["merge_publication_missing"] = run.report()
    run = Run(api, "merge_head_changed")
    run.until(api.MERGE_INTENDED, limit=4)
    run.github.pr = {**run.github.pr, "head": "6" * 40}
    run.tick(note="ci_head_changed at the merge")
    out["merge_head_changed"] = run.report()
    run = Run(api, "merge_publication_not_open")
    run.until(api.MERGE_INTENDED, limit=4)
    run.github.pr = {**run.github.pr, "state": "CLOSED"}
    run.tick(note="publication_not_open at the merge")
    out["merge_publication_not_open"] = run.report()
    run = Run(api, "merge_check_regressed")
    run.until(api.MERGE_INTENDED, limit=4)
    run.github.rows = [{"name": D.CHECK, "state": "failure"}]
    run.tick(note="a re-run failed: the merge is never attempted")
    out["merge_check_regressed"] = run.report()
    run = Run(api, "merge_base_moved")
    run.until(api.MERGE_INTENDED, limit=4)
    run.github.main = MOVED
    run.tick(note="main moved after CI passed: reviewed_base_moved")
    out["merge_base_moved"] = run.report()
    run = Run(api, "merge_outage")
    run.until(api.MERGE_INTENDED, limit=4)
    run.github.observe_error = ConnectionError("injected: GitHub unreachable")
    run.tick(note="GitHub unreachable at the merge")
    out["merge_outage"] = run.report()
    run = Run(api, "descriptor_predecessor_moved", plan_overrides={"expected": "4" * 64})
    run.until(api.MERGED, limit=6)
    out["descriptor_predecessor_moved"] = run.report()
    for code in ("reviewed_base_moved", "merge_push_refused", "candidate_not_fast_forward"):
        run = merged_ff(api, "merge_refused_" + code)
        run.until(api.MERGE_INTENDED, limit=4)
        run.github.merge_refusal = code    # LABELLED: the server's (or the ancestry check's) definite refusal
        run.tick(note="MergeRefused " + code)
        out["merge_refused_" + code] = run.report()
    run = merged_ff(api, "fast_forward_once")
    run.until(api.MERGED, limit=6)
    out["fast_forward_once"] = run.report()
    run = merged_ff(api, "ff_main_drift_before_merge")
    run.until(api.MERGE_INTENDED, limit=4)
    run.github.main = MOVED
    run.tick(note="main moved: left to its writer")
    out["ff_main_drift_before_merge"] = run.report()
    run = merged_ff(api, "ff_lost_push_response")
    run.until(api.MERGE_INTENDED, limit=4)
    run.github.merge_error = TimeoutError("injected: push outcome unknown after the update")
    run.tick(note="the push happened, its response was lost")
    run.github.merge_error = None
    run.wait(120)
    restarted(run)
    run.tick(note="a restarted controller recognizes main and never pushes again")
    out["ff_lost_push_response"] = run.report()
    run = merged_ff(api, "ff_unknown_push_remote_untouched")
    run.until(api.MERGE_INTENDED, limit=4)
    original = run.github.merge

    def unknown(candidate, observed=None):
        run.github.merges += 1
        raise TimeoutError("injected: push outcome unknown, remote untouched")   # LABELLED transport death
    run.github.merge = unknown
    run.tick(note="the transport died before any update: unavailable, main at the base")
    run.github.merge = original
    run.tick(note="the retry waits for the queue's own bounded backoff")
    run.wait(120)
    run.tick(note="the retry goes through the fence and merges once")
    out["ff_unknown_push_remote_untouched"] = run.report()
    run = merged_ff(api, "ff_external_merge_same_tree")
    run.until(api.MERGE_INTENDED, limit=4)
    external_merge(run)
    run.tick(note="an external merge of the same tree is recognized and qualified without a push")
    out["ff_external_merge_same_tree"] = run.report()
    run = Run(api, "ff_external_merge_other_tree", github=D.FakeGitHub(api, fast_forward=True, merged_tree="d" * 64))
    run.until(api.MERGE_INTENDED, limit=4)
    external_merge(run)
    run.tick(note="an external merge of another tree stays blocked")
    out["ff_external_merge_other_tree"] = run.report()
    run = merged_ff(api, "ff_moved_or_closed_publication")
    run.until(api.MERGE_INTENDED, limit=4)
    run.github.pr = {**run.github.pr, "state": "MERGED", "merged_revision": None}
    run.tick(note="a closed publication is refused before any push")
    out["ff_moved_or_closed_publication"] = run.report()
    return out


def predecessor(api):
    out = {}
    run = merged_ff(api, "second_plan_waits_then_is_refused")
    run.until(api.MERGED, limit=6)
    plan2 = successor(run, plan_id="delivery-plan-2")["plan"]
    for _ in range(4):
        run.tick(plan2["plan_id"], note="plan 2 while plan 1 is merged and not settled")
    run.until(api.ACTIVE, limit=30)
    run.tick(plan2["plan_id"], note="plan 1 is active: plan 2's expected predecessor moved")
    out["second_plan_waits_then_is_refused"] = run.report(plan2=run.intent_view(plan2["plan_id"]))
    stop(run)
    run = merged_ff(api, "old_second_plan_on_stale_base")
    run.until(api.MERGED, limit=6)
    plan2 = successor(run, plan_id="delivery-plan-2", base=D.BASE)["plan"]
    run.tick(plan2["plan_id"])
    run.tick(plan2["plan_id"], note="registered on the first candidate's base after the first merged")
    out["old_second_plan_on_stale_base"] = run.report(plan2=run.intent_view(plan2["plan_id"]))
    run = merged_ff(api, "failed_predecessor_unverified_descriptor")
    run.tick(note="plan 1 has an intent")
    row = run.intent()
    put(run.store, api.BUCKET_INTENTS, row["id"], {**row, "stage": api.FAILED, "descriptor": {"schema": "fixture"},
                                                    "rollback": {"requested": True, "verified": False}})   # LABELLED
    plan2 = successor(run, plan_id="delivery-plan-2")["plan"]
    for _ in range(4):
        run.tick(plan2["plan_id"], note="a failed predecessor with an unverified descriptor stops a new merge")
    row = run.intent()
    put(run.store, api.BUCKET_INTENTS, row["id"], {**row, "rollback": {"requested": True, "verified": True}})   # LABELLED
    run.tick(plan2["plan_id"], note="its rollback was proven: the merge proceeds")
    out["failed_predecessor_unverified_descriptor"] = run.report(plan2=run.intent_view(plan2["plan_id"]))
    return out


# ---- 4. prepare, drain, switch ---------------------------------------------------------------------------------
def register_historical(run):
    """M7 `register_historical` (LABELLED FIXTURE): a plan stored BEFORE registration refused `first_activation_unbound`,
    written as the row `register` used to write."""
    api = run.api
    plan = api.validate_plan(run.system["plan"])
    put(run.store, api.BUCKET_PLANS, plan["plan_id"], {
        "id": plan["plan_id"], "plan_id": plan["plan_id"], "plan": plan, "plan_sha256": api.plan_digest(plan),
        "pin": D.pin(), "target_id": plan["target_id"], "registered_at": D.clock(api)(), "updated_at": D.clock(api)()})


def first_active(api, label, **kwargs):
    """A delivery driven to `active` with a passing canary the caller can flip (M7's rollback tests)."""
    verdicts = {"passed": True}
    run = Run(api, label, canaries={api.CANARY_STARTUP: canary_passing(verdicts)}, **kwargs)
    run.verdicts = verdicts
    run.until(api.ACTIVE, limit=40)
    run.good = get(run.store, api.BUCKET_DESCRIPTORS, "canary-service")
    return run


def second_delivery(run, **overrides):
    """A second plan on the target, expected predecessor = the first delivery's active descriptor; the run's default
    plan and release now name it (so `report`, `supersede` and `free_queue` act on it)."""
    made = successor(run, expected=run.good["descriptor_sha256"], **overrides)
    run.system["plan"], run.system["release"] = made["plan"], made["release"]
    return made


def switch_foreign_receipt(run):
    """LABELLED injected foreign instance: an otherwise perfect receipt for another instance (M7)."""
    state = run.host._st(run.system["target"])
    state["receipt"] = {**state["receipt"], "instance_id": "c" * 32}


def prepare_switch(api):
    out = {}
    run = Run(api, "release_not_verified", verified=False)
    run.tick(note="registered enters verifying")
    run.tick(note="no verifier: verifier_unavailable")
    intent = run.intent()
    put(run.store, api.BUCKET_INTENTS, intent["id"], {**intent, "stage": api.MERGED, "merged_revision": D.MERGED_REVISION})
    row = get(run.store, "release_queue", run.release_id())
    put(run.store, "release_queue", run.release_id(), {**row, "status": "queued", "attempt": 0, "retry_at": None})
    run.tick(note="LABELLED legacy shape: merged with an unverified release halts before the host")
    out["release_not_verified"] = run.report(descriptor_row=get(run.store, api.BUCKET_DESCRIPTORS, "canary-service"))
    run = Run(api, "target_unregistered")
    run.until(api.MERGED, limit=6)
    put(run.store, api.BUCKET_TARGETS, "canary-service", None)   # LABELLED: the target row is gone
    run.tick(note="the registered target is gone: refused")
    out["target_unregistered"] = run.report()
    run = Run(api, "descriptor_hand_edited_after_merge")
    run.until(api.MERGED, limit=6)
    put(run.store, api.BUCKET_DESCRIPTORS, "canary-service", {"id": "canary-service", "target_id": "canary-service",
                                                              "descriptor": {"schema": "fixture", "revision": "4" * 40}})
    run.tick(note="LABELLED hand edit between the merge and the switch: descriptor_predecessor_mismatch")
    out["descriptor_hand_edited_after_merge"] = run.report(descriptor_row=get(run.store, api.BUCKET_DESCRIPTORS, "canary-service"))
    run = Run(api, "unchanged_without_predecessor", plan_overrides={"image": "unchanged"}, register_plan=False)
    refusal = D.call(run.delivery.register, run.system["plan"], D.pin())
    register_historical(run)
    run.until(api.MERGED, limit=6)
    run.tick(note="an unchanged binding without a predecessor refuses instead of guessing")
    out["unchanged_without_predecessor"] = run.report(registration=refusal)
    run = first_active(api, "target_instance_mismatch")
    second_delivery(run)
    switch_foreign_receipt(run)
    run.until(api.SWITCHING, limit=20)
    out["target_instance_mismatch"] = run.report(good_descriptor_sha256=run.good["descriptor_sha256"])
    stop(run)
    run = first_active(api, "instance_not_authorized")
    second_delivery(run)
    run.until(api.SWITCHING, limit=20)
    switch_foreign_receipt(run)
    run.tick(note="a foreign instance appeared after the authority was captured: the start refuses")
    out["instance_not_authorized"] = run.report(descriptor_row=get(run.store, api.BUCKET_DESCRIPTORS, "canary-service"))
    stop(run)
    run = first_active(api, "second_delivery_replaces_predecessor")
    second_delivery(run)
    run.verdicts["passed"] = True
    run.until(api.ACTIVE, limit=30)
    out["second_delivery_replaces_predecessor"] = run.report(good_descriptor_sha256=run.good["descriptor_sha256"],
                                                            active=get(run.store, "deployment", "active"))
    stop(run)
    return out


def unsettled_work(run, *, active, unconfirmed, report=True):
    """LABELLED injected host state (M7): the service is running and reports this work (None: no report)."""
    state = run.host._st(run.system["target"])
    state["running"] = True
    state["work"] = {"active": active, "unconfirmed": unconfirmed} if report else None


def drain(api):
    out = {}
    for name, work in (("drain_pending_then_timeout", {"active": 1, "unconfirmed": 0}),
                       ("drain_unconfirmed_pending_then_blocked", {"active": 1, "unconfirmed": 1}),
                       ("drain_missing_report", {"active": 0, "unconfirmed": 0, "report": False})):
        run = Run(api, name)
        run.until(api.DRAIN_INTENDED, limit=8)
        unsettled_work(run, **{"active": work["active"], "unconfirmed": work["unconfirmed"],
                               "report": work.get("report", True)})
        run.tick(note="the target is not drained: a bounded wait")
        run.tick(note="still bounded")
        run.wait(600)
        run.tick(note="past the stage deadline")
        out[name] = report_with_state(run)
    run = Run(api, "drain_missing_host_port", canaries={})
    run.delivery.hosts = {}
    run.until(api.DRAIN_INTENDED, limit=8)
    run.tick(note="no host port for the target's kind: refused, nothing touched")
    out["drain_missing_host_port"] = run.report(descriptor_row=get(run.store, api.BUCKET_DESCRIPTORS, "canary-service"))
    run = Run(api, "environment_unqualified")
    run.until(api.DRAIN_INTENDED, limit=8)

    def unqualified(target, *, authorize=None):
        raise api.EnvironmentUnqualified("injected: the runtime environment is not qualified")   # LABELLED outage
    run.host.drain = unqualified
    run.tick(note="a named unavailable gate, not a refusal")
    run.wait(120)
    run.tick(note="after the retry backoff")
    out["environment_unqualified"] = run.report()
    return out


def report_with_state(run):
    return run.report(work=run.host._st(run.system["target"])["work"])


def switch(api):
    out = {}
    run = Run(api, "descriptor_foreign")
    run.until(api.SWITCHING, limit=8)
    foreign = {**run.intent()["descriptor"], "revision": "7" * 40}
    run.host.switch(run.system["target"], foreign, expected=None)   # LABELLED: something else owns the target now
    run.tick(note="a foreign descriptor blocks the switch instead of being overwritten")
    out["descriptor_foreign"] = run.report(host_descriptor_is_foreign=run.host.current(run.system["target"]) == foreign,
                                           descriptor_row=get(run.store, api.BUCKET_DESCRIPTORS, "canary-service"))
    run = Run(api, "lost_switch_response")
    run.until(api.SWITCHING, limit=8)
    descriptor = run.intent()["descriptor"]
    run.host.switch(run.system["target"], descriptor, expected=None)   # LABELLED: switched AND started, then lost
    run.host.start(run.system["target"], descriptor)
    started = run.host._st(run.system["target"])["launch"]
    run.tick(note="the descriptor and the process are recognized, neither written nor started again")
    run.until(api.ACTIVE, limit=20)
    out["lost_switch_response"] = run.report(launch_kept=run.host._st(run.system["target"])["launch"] == started,
                                             instance=get(run.store, api.BUCKET_DESCRIPTORS, "canary-service")["instance_id"])
    stop(run)
    run = Run(api, "lost_start_response", host=D.MemoryHost(api, start_error=TimeoutError("injected: start response lost")))
    run.until(api.SWITCHING, limit=8)
    run.tick(note="the process started, its response was lost: unavailable")
    run.host.start_error = None
    run.wait(120)
    run.tick(note="the running instance is recognized, never started twice")
    run.until(api.ACTIVE, limit=20)
    out["lost_start_response"] = run.report()
    stop(run)
    run = first_active(api, "start_previous_instance_unconfirmed")
    second_delivery(run)
    run.until(api.SWITCHING, limit=20)
    run.host.stop_confirms = False   # LABELLED fault: the bounded stop is not confirmed
    run.tick(note="the predecessor's stop is not confirmed: refused")
    out["start_previous_instance_unconfirmed"] = run.report(descriptor_row=get(run.store, api.BUCKET_DESCRIPTORS, "canary-service"))
    stop(run)
    return out


# ---- 5. consume and rollback -----------------------------------------------------------------------------------
def consume(api):
    out = {}
    run = Run(api, "late_receipt", host=D.MemoryHost(api, miss=4))
    run.until(api.ACTIVE, limit=30)
    out["late_receipt"] = run.report()
    stop(run)
    run = Run(api, "no_receipt_until_deadline", host=D.MemoryHost(api, fault="no_receipt"),
              plan_overrides={"consumption_timeout": 10})
    run.until(api.ACTIVE, limit=30)
    out["no_receipt_until_deadline"] = run.report(descriptor_row=get(run.store, api.BUCKET_DESCRIPTORS, "canary-service"))
    stop(run)
    for fault in ("old_runtime", "other_image"):
        run = Run(api, "receipt_" + fault, host=D.MemoryHost(api, fault=fault), plan_overrides={"consumption_timeout": 10})
        run.until(api.ACTIVE, limit=30)
        out["receipt_" + fault] = run.report(descriptor_row=get(run.store, api.BUCKET_DESCRIPTORS, "canary-service"),
                                             deployment=get(run.store, "deployment", "active"))
        stop(run)
    # The owner's canary needs the owner's own receipt (M7 `test_an_owner_qualified_canary_needs_the_owners_own_receipt`).
    for name in ("pending_then_passes", "pending_expires", "missing", "stale", "failed"):
        run = Run(api, "owner_canary_" + name, plan_overrides={"canary": api.CANARY_FLEET})
        plan_id = run.system["plan"]["plan_id"]
        if name.startswith("pending"):
            run.system["owner_canary"].requests.add(plan_id)
        run.until(api.AWAITING_CONSUMPTION, limit=8)
        descriptor = run.intent()["descriptor"]
        if name == "stale":
            run.system["owner_canary"].owner_receipt(plan_id, {**descriptor, "revision": "3" * 40})
        if name == "failed":
            run.system["owner_canary"].owner_receipt(plan_id, descriptor, passed=False)
        run.tick(note="the owner's canary answers: " + name)
        if name == "pending_then_passes":
            run.tick(note="still pending")
            run.system["owner_canary"].owner_receipt(plan_id, descriptor)
            run.tick(note="the owner's receipt arrived")
        if name == "pending_expires":
            run.wait(600)
            run.tick(note="past the stage deadline: the pending canary is a failure")
        out["owner_canary_" + name] = run.report(descriptor_row=get(run.store, api.BUCKET_DESCRIPTORS, "canary-service"))
        stop(run)
    run = Run(api, "canary_unavailable", canaries={})
    run.until(api.ACTIVE, limit=12)
    out["canary_unavailable"] = run.report()
    stop(run)

    def exploding(target, descriptor, startup):
        raise RuntimeError("injected: the canary crashed")   # LABELLED
    run = Run(api, "canary_error", canaries={api.CANARY_STARTUP: exploding})
    run.until(api.ACTIVE, limit=12)
    out["canary_error"] = run.report()
    stop(run)
    run = Run(api, "retry_instance_changed")
    run.until(api.AWAITING_CONSUMPTION, limit=8)
    intent = run.intent()
    put(run.store, api.BUCKET_INTENTS, intent["id"], {**intent, "recoveries": [{
        "kind": api.RECOVERY_CONSUMPTION_RETRY, "observed": {"observed_instance_id": "e" * 32}}]})   # LABELLED
    run.tick(note="a retry consumes ONLY the instance it observed")
    out["retry_instance_changed"] = run.report()
    stop(run)
    run = Run(api, "release_promotion_refused")
    run.until(api.AWAITING_CONSUMPTION, limit=8)
    put(run.store, "deployment", "active", {"release_id": "release-other", "revision": "2" * 40})   # LABELLED pointer move
    run.tick(note="the host is consumed, the pointer is not this release's: blocked, never an activation")
    out["release_promotion_refused"] = run.report(descriptor_row=get(run.store, api.BUCKET_DESCRIPTORS, "canary-service"),
                                                  deployment=get(run.store, "deployment", "active"))
    stop(run)
    return out


def failing_successor(api, label, **kwargs):
    """M7's rollback shape: a first delivery active, then a successor whose canary fails; ticks to ROLLING_BACK."""
    run = first_active(api, label, **kwargs)
    run.verdicts["passed"] = False
    second_delivery(run, consumption_timeout=10)
    run.until(api.ROLLING_BACK, limit=30)
    return run


def rollback(api):
    out = {}
    run = failing_successor(api, "rollback_restores_the_predecessor")
    run.until(api.ROLLED_BACK, limit=40)
    out["rollback_restores_the_predecessor"] = run.report(
        descriptor_row=get(run.store, api.BUCKET_DESCRIPTORS, "canary-service"), good_descriptor_sha256=run.good["descriptor_sha256"],
        deployment=get(run.store, "deployment", "active"))
    stop(run)
    run = failing_successor(api, "rollback_interrupted_acknowledgement")
    intent = run.intent()
    run.host.switch(run.system["target"], intent["previous_descriptor"], expected=intent["descriptor_sha256"])   # LABELLED
    run.until(api.ROLLED_BACK, limit=40)
    out["rollback_interrupted_acknowledgement"] = run.report(descriptor_row=get(run.store, api.BUCKET_DESCRIPTORS, "canary-service"))
    stop(run)
    run = failing_successor(api, "rollback_foreign_descriptor")
    intent = run.intent()
    foreign = {**intent["descriptor"], "revision": "7" * 40}
    run.host.switch(run.system["target"], foreign, expected=intent["descriptor_sha256"])   # LABELLED
    run.tick(note="a rollback onto a foreign descriptor blocks rather than overwriting it")
    out["rollback_foreign_descriptor"] = run.report(host_descriptor_is_foreign=run.host.current(run.system["target"]) == foreign,
                                                    descriptor_row=get(run.store, api.BUCKET_DESCRIPTORS, "canary-service"))
    stop(run)

    def never_reports(host):
        """LABELLED fault (M7 `BrokenHost`): the restored descriptor's service is stopped and never reports."""
        def start(target, descriptor, *, authorize=None, replaces=None):
            host.calls.append("start")
            host.stop(target)
            return {"started": True, "pid": None}
        return start
    run = failing_successor(api, "rollback_unverified")
    run.host.start = never_reports(run.host)
    run.until(api.ROLLED_BACK, limit=30)
    out["rollback_unverified"] = run.report(descriptor_row=get(run.store, api.BUCKET_DESCRIPTORS, "canary-service"))
    stop(run)
    run = failing_successor(api, "rollback_failed_restoring_switch")
    run.host.switch = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("injected: the restoring switch failed"))
    run.tick(note="the restoring switch failed")
    out["rollback_failed_restoring_switch"] = run.report()
    stop(run)
    run = failing_successor(api, "rollback_failed_start")
    intent = run.intent()
    run.tick(note="restores the predecessor descriptor")

    def start_fails(target, descriptor, *, authorize=None, replaces=None):
        raise api.DeliveryRefused("previous_instance_unconfirmed", "target_id")   # LABELLED: not an activation gate
    run.host.start = start_fails
    run.tick(note="the predecessor cannot be started")
    out["rollback_failed_start"] = run.report()
    stop(run)
    run = failing_successor(api, "rollback_start_crashes")
    run.tick(note="restores the predecessor descriptor")
    run.host.start = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("injected: the start crashed"))
    run.tick(note="the start raises: rollback_failed")
    out["rollback_start_crashes"] = run.report()
    stop(run)
    run = failing_successor(api, "rollback_gate_pending_then_blocked")
    run.tick(note="restores the predecessor descriptor")

    def gate_held(target, descriptor, *, authorize=None, replaces=None):
        raise api.DeliveryRefused("fleet_debt_held", "target_id")   # LABELLED: the target's Fleet debt is held
    run.host.start = gate_held
    run.tick(note="the activation gate holds: pending, nothing started")
    run.tick(note="still held")
    run.wait(600)
    run.tick(note="expired: blocked for its recovery owner under the same code")
    out["rollback_gate_pending_then_blocked"] = run.report(gate_codes=sorted(api.ACTIVATION_GATE_CODES))
    stop(run)
    run = first_active(api, "stale_instance_receipt_then_rollback")
    second_delivery(run)
    run.until(api.AWAITING_CONSUMPTION, limit=20)
    state = run.host._st(run.system["target"])
    state["receipt"] = {**state["receipt"], "instance_id": run.good["instance_id"]}
    run.tick(note="LABELLED: the predecessor's own instance still answers: a bounded wait")
    run.wait(600)
    run.tick(note="expired: not an unknown that can be waited out, the exact predecessor is restored")
    out["stale_instance_receipt_then_rollback"] = run.report(good_descriptor_sha256=run.good["descriptor_sha256"])
    stop(run)
    run = Run(api, "no_known_good_predecessor", canaries={api.CANARY_STARTUP: canary_passing({"passed": False})})
    run.until(api.ACTIVE, limit=12)
    out["no_known_good_predecessor"] = run.report(descriptor_row=get(run.store, api.BUCKET_DESCRIPTORS, "canary-service"),
                                                  deployment=get(run.store, "deployment", "active"))
    stop(run)
    return out


# ---- 6. the fence and the ambiguous effects -----------------------------------------------------------------------
def reconcile(run, until, *, limit=30, note="the next owner reconciles"):
    """After a supersession: the successor's lease is gone, the row is re-armed and the ONE timeline moves past the
    queue backoff (M7); the next ticks reconcile from the durable intent and finish."""
    free_queue(run)
    run.wait(120)
    return run.until(until, limit=limit)


def fence(api):
    out = {}
    run = Run(api, "superseded_before_the_effect")
    run.tick(note="registered enters publishing")
    original = run.github.observe

    def stolen(candidate):
        result = original(candidate)
        supersede(run)   # LABELLED injected supersession, BEFORE the effect
        return result
    run.github.observe = stolen
    before = run.intent()
    run.tick(note="loss BEFORE the effect: the fence is checked at the mutation boundary")
    out["superseded_before_the_effect"] = run.report(intent_unchanged=run.intent() == before, publishes=run.github.publishes)
    run = Run(api, "ambiguous_published")
    run.tick(note="registered enters publishing")
    publish = run.github.publish

    def stolen_publish(candidate):
        row = publish(candidate)
        supersede(run)   # LABELLED: the response came back, the fence is gone before it can be recorded
        return row
    run.github.publish = stolen_publish
    run.tick(note="_record: published, then the fence was lost")
    run.github.publish = publish
    stage_after = run.intent()["stage"]
    reconcile(run, api.AWAITING_CI, limit=3)
    out["ambiguous_published"] = run.report(intent_stage_after_effect=stage_after)
    run = Run(api, "ambiguous_merged", github=D.FakeGitHub(api, fast_forward=True))
    run.until(api.MERGE_INTENDED, limit=4)
    qualify = run.github.qualify

    def stolen_qualify(candidate, revision):
        result = qualify(candidate, revision)
        supersede(run)   # LABELLED: the merge and its qualification happened, the fence is gone
        return result
    run.github.qualify = stolen_qualify
    run.tick(note="_record: merged, then the fence was lost")
    run.github.qualify = qualify
    reconcile(run, api.MERGED, limit=3)
    out["ambiguous_merged"] = run.report()
    run = Run(api, "ambiguous_service_stopped")
    run.until(api.SWITCHING, limit=8)
    stop_original = run.host.stop

    def stolen_stop(target):
        observed = stop_original(target)
        supersede(run)   # LABELLED: the fence is lost exactly inside the lifecycle's own bounded stop
        return observed
    run.host.stop = stolen_stop
    run.tick(note="_lifecycle: LifecycleInterrupted becomes the ambiguity it is")
    run.host.stop = stop_original
    after_effect = {"descriptor_row": get(run.store, api.BUCKET_DESCRIPTORS, "canary-service"),
                    "receipt_written": run.host._st(run.system["target"])["receipt"] is not None,
                    "running": run.host.running(run.system["target"])}
    reconcile(run, api.ACTIVE, limit=20)
    out["ambiguous_service_stopped"] = run.report(
        after_effect=after_effect, instance=(get(run.store, api.BUCKET_DESCRIPTORS, "canary-service") or {}).get("instance_id"))
    stop(run)
    run = Run(api, "ambiguous_descriptor_switched")
    run.until(api.SWITCHING, limit=8)
    start = run.host.start

    def stolen_start(target, descriptor, **kwargs):
        result = start(target, descriptor, **kwargs)
        supersede(run)   # LABELLED: the switch and the start happened, the fence is gone before they are recorded
        return result
    run.host.start = stolen_start
    run.tick(note="_record: descriptor_switched, then the fence was lost")
    run.host.start = start
    reconcile(run, api.ACTIVE, limit=20)
    out["ambiguous_descriptor_switched"] = run.report(instance=(get(run.store, api.BUCKET_DESCRIPTORS, "canary-service") or {}).get("instance_id"))
    stop(run)
    # `_commit_verification`: after an evaluation (the verifier's own heartbeat still succeeded).
    verifier = D.Verifier(api)
    run = Run(api, "ambiguous_verification", verified=False, verifier=verifier)
    run.tick(note="registered enters verifying")
    evaluate = verifier.evaluate

    def stolen_evaluate(release_id, attempt, *, fence):
        outcome = evaluate(release_id, attempt, fence=fence)
        supersede(run)   # LABELLED: evaluated, then the fence is lost before the verdict can be recorded
        return outcome
    verifier.evaluate = stolen_evaluate
    run.tick(note="_commit_verification: verification, then the fence was lost")
    verifier.evaluate = evaluate
    release_status = get(run.store, "releases", run.release_id())["status"]
    free_queue(run)
    run.wait(120)
    run.tick(note="the next owner: the evaluation's attempt is unresolved, so it waits for its cleanup")
    attempt = run.intent()["verification"]["attempts"][0]["attempt_id"]
    verifier.reconciled = {"state": "clear", "reason_code": None, "resolved": {
        attempt: {"state": "confirmed", "receipt": "fixture-cleanup-receipt"}}}
    run.tick(note="reconcile proved the cleanup: a new evaluation verifies the release")
    out["ambiguous_verification"] = run.report(release_status_after_effect=release_status,
                                               attempts=verifier.attempts, evaluated=verifier.evaluated)
    # `_promote`: the promotion shares its transaction with the fence check.
    run = Run(api, "ambiguous_release_promotion")
    delivery = run.delivery
    emit, stolen = delivery._emit, {"done": False}

    def racing(event_type, outcome, plan, **fields):
        emit(event_type, outcome, plan, **fields)
        if event_type == api.EVENT_SWITCHED and outcome == "succeeded" and not stolen["done"]:
            stolen["done"] = True
            supersede(run)   # LABELLED: between the recorded consumption and the promotion
    delivery._emit = racing
    run.until(api.ACTIVE, limit=30)
    pointer_after_effect = get(run.store, "deployment", "active")
    status_after_effect = get(run.store, "releases", run.release_id())["status"]
    consumed = get(run.store, api.BUCKET_DESCRIPTORS, "canary-service")
    stage_after_effect = run.intent()["stage"]
    delivery._emit = emit
    reconcile(run, api.ACTIVE, limit=20)
    out["ambiguous_release_promotion"] = run.report(
        pointer_after_effect=pointer_after_effect, release_status_after_effect=status_after_effect,
        consumed_after_effect=consumed, intent_stage_after_effect=stage_after_effect,
        deployment=get(run.store, "deployment", "active"),
        same_instance=(get(run.store, api.BUCKET_DESCRIPTORS, "canary-service") or {}).get("instance_id") == consumed["instance_id"])
    stop(run)
    return out


def queue_faults(api):
    out = {}
    run = Run(api, "queue_refused")
    run.delivery.queue.enqueue = lambda *a, **k: (_ for _ in ()).throw(api.ContractError("injected: release is not queueable"))
    run.tick(note="the queue refuses the enqueue: a definite verdict")
    out["queue_refused"] = run.report()
    run = Run(api, "queue_unavailable")
    run.delivery.queue.claim = lambda *a, **k: (_ for _ in ()).throw(ConnectionError("injected: queue store unreachable"))
    run.tick(note="the store cannot be reached for the claim: an outage, nothing committed")
    out["queue_unavailable"] = run.report()
    return out


def settle(groups):
    """The `_settle` mapping observed across every case: outcome -> the queue status each tick's settle left."""
    table = {}
    for _, cases in groups.items():
        for case in cases.values():
            if not isinstance(case, dict):
                continue
            for entry in case.get("ticks", []):
                outcome = entry["result"]["outcome"]
                queue = entry["queue"] or {}
                key = "%s -> %s%s" % (outcome, queue.get("status"),
                                       " (stale)" if entry["result"].get("controller") == "stale" else "")
                table[key] = table.get(key, 0) + 1
    return dict(sorted(table.items()))


# ---- 7. coverage -----------------------------------------------------------------------------------------------
# TRACE-s7 §5.1: every handler and the reasons/stages it can end in. A reason is REACHED when some case's tick receipt
# carries it; the rest say why they are not.
EXPECTED = {
    "_verify": ["verifier_unavailable", "verification_owner_alive", "verification_cleanup_unconfirmed",
                "verification_interrupted", "verification_refused", "verification_outcome_unknown",
                "verification_record_unavailable", "verification_unavailable", "verification_fence_lost",
                "verification_fence_unobservable", "verification_observation_unavailable", "release_hook_unsupported",
                "release_rejected", "release_superseded_by_ticket_revision", "release_verdict_refused",
                "release_cancelled"],
    "_publish": ["reviewed_base_moved", "publish_head_mismatch", "github_port_unavailable", "stage_unavailable"],
    "_observe_ci": ["ci_check_pending", "ci_check_missing", "ci_check_failed", "ci_head_changed", "ci_timeout",
                    "publication_missing"],
    "_merge": ["predecessor_in_flight", "descriptor_predecessor_moved", "publication_not_open", "merged_tree_mismatch",
               "merge_unqualified", "merge_push_refused", "candidate_not_fast_forward"],
    "_prepare_switch": ["release_not_verified", "target_unregistered", "descriptor_predecessor_mismatch",
                        "target_instance_mismatch", "unchanged_without_predecessor"],
    "_drain": ["drain_pending", "drain_unconfirmed_effects", "drain_timeout", "host_port_unavailable",
               "environment_unqualified"],
    "_switch": ["descriptor_foreign", "instance_not_authorized", "previous_instance_unconfirmed"],
    "_consume": ["receipt_missing", "receipt_stale_instance", "receipt_revision_mismatch",
                 "receipt_worker_image_mismatch", "canary_owner_receipt_pending", "retry_instance_changed",
                 "release_promotion_refused", "no_known_good_predecessor"],
    "_rollback": ["rollback_awaiting_consumption", "rollback_foreign_descriptor", "rollback_unverified",
                  "rollback_failed", "fleet_debt_held", "canary_fixture_failed"],
    "_act": ["controller_stale", "controller_stale_after_effect", "verification_fence_lost", "queue_refused",
             "queue_unavailable", "controller_lease_held", "release_retry_not_due"],
}
UNREACHABLE = {}
STAGES = ["verifying", "publishing", "awaiting_ci", "merge_intended", "merged", "drain_intended", "switching",
          "awaiting_consumption", "active", "blocked", "rolling_back", "rolled_back", "failed"]
STAGE_UNREACHABLE = {
    "failed": "a delivery reaches `failed` only when a BLOCKED halt repeats (MAX_STAGE_ATTEMPTS) on an intent an owner "
              "command has re-armed; every owner command is a later family (delivery.owner_commands)",
}


def coverage(groups):
    reasons, stages_seen, causes = {}, {}, {}
    for group, cases in groups.items():
        for name, case in cases.items():
            if not isinstance(case, dict):
                continue
            for entry in case.get("ticks", []):
                result = entry["result"]
                where = group + "." + name
                if result.get("reason_code"):
                    reasons.setdefault(result["reason_code"], set()).add(where)
                if result.get("stage"):
                    stages_seen.setdefault(result["stage"], set()).add(where)
                cause = (result.get("rollback") or {}).get("reason_code")
                if cause:
                    causes.setdefault(cause, set()).add(where)
    table = {}
    for handler, wanted in EXPECTED.items():
        for reason in wanted:
            if reason in reasons or reason in causes:
                hit = sorted(reasons.get(reason, set()) | causes.get(reason, set()))
                table[handler + ":" + reason] = {"reached": len(hit), "first": hit[0]}
            else:
                table[handler + ":" + reason] = {"unreachable": UNREACHABLE.get(reason, "not reached by a case")}
    stage_table = {}
    for stage in STAGES:
        if stage in stages_seen:
            stage_table[stage] = {"reached": len(stages_seen[stage]), "first": sorted(stages_seen[stage])[0]}
        else:
            stage_table[stage] = {"unreachable": STAGE_UNREACHABLE.get(stage, "not reached by a case")}
    return {"reasons": table, "stages": stage_table, "all_reasons_observed": sorted(reasons),
            "rollback_causes_observed": sorted(causes)}


def run(api) -> dict:
    groups = {"normal_path": {"normal_path": normal_path(api)}, "verify": verify(api),
              "publish_ci_merge": {**publish(api), **ci(api), **merge(api), **predecessor(api)},
              "prepare_drain_switch": {**prepare_switch(api), **drain(api), **switch(api)},
              "consume_rollback": {**consume(api), **rollback(api)},
              "fence_and_ambiguity": {**fence(api), **queue_faults(api)}}
    groups["settle_mapping"] = {"outcome_to_queue_status": settle(groups)}
    groups["coverage"] = {"coverage": coverage(groups)}
    return groups
