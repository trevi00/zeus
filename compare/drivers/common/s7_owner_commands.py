"""Shared S7 scenario steps (`delivery.owner_commands`): the owner commands of M7 `HostDelivery`
(`application/host_delivery.py`), characterized BEFORE the V8 split moves them (DESIGN-s7 §2, TRACE-s7 §5.4).

Groups (each labelled in the result; the M7 tests they mirror are named at each function):

1. **withdraw** (`tests/test_host_delivery_requalification.py`, D3): the refusal ladder with nothing written, the fence a tick
   takes, the retirement of both stale plans with every record kept, cached replay and conflict, the crash between the
   withdrawal and the queue finish, the recorded tree mismatch, the stale predecessor binding, a touched host, the held
   migration successor and the verification debt (`tests/test_host_delivery_migration.py`, `tests/test_release_verifier.py`).
2. **resume** (`tests/test_host_delivery_verification.py::test_the_merged_unverified_legacy_halt_resumes_once_...`, with
   the memory store; the phase-two rollbacks of `tests/test_release_verifier.py`): the evidence and plan mismatches, the
   applicability by stage, `resume_unobservable`, the release gate, the cached replay and one successful resume driven to
   `active`. (M7's `test_a_known_dead_instance_of_this_delivery_is_resumed_...` is a HOST-adapter test of
   `ProcessHostTarget.start`, not of `HostDelivery.resume`; it belongs to `delivery.host_targets`.)
3. **first_activation** (`tests/test_host_delivery_first_activation.py`): the binding grammar, every refusal, the trusted
   port, the cached replay, two "concurrent" resumes run sequentially on the memory store, and a bound first activation
   drained, switched, started and consumed.
4. **consumption_retry** (`tests/test_host_delivery_consumption_retry.py`): the exact document grammar, the live host, every
   stale claim, the one retry consuming the same instance, exhaustion and the anchored window.
5. **consumption_rearm** (`tests/test_host_delivery_consumption_rearm.py`): the same on the exhausted retry, the explicit
   window, the final expiry.
6. **generation_restart** (`tests/test_host_delivery_generation_restart.py`): the positively stopped generation, one start
   under the fence, a lost start response recognized, a held fence keeping the recorded request, one restart per delivery.

Each case reports the owner commands in order (each result, or the named refusal, whether the store was written and the
digest of the whole store after it, and the queue row and the intent view after it), the ticks that followed, the doubles'
recorded calls (GitHub publishes/merges/observations, host calls) and the digest of every bucket at the end.

Layer: harness (never shipped)

Every double is in `s7_delivery` and LABELLED; this module never runs GitHub, a host, a process or a verifier. Faults are
injected only through the doubles' public attributes and the ports a controller exposes (`github.qualify`, `host.identity`,
`host.receipt`, `host.start_error`, `delivery.first_activation`, `delivery.queue.claim/finish/retry`), each labelled where it
is injected. The rows this module writes itself are LABELLED fixtures of M7's shapes, each named where it is written: the
legacy `release_not_verified` halt (M7's own test writes it), a bound descriptor on a stopped delivery (M7's own test), a
held migration successor and a moved release/queue/lock row (M7's phase-two tests). A case reached only through a path
the doubles cannot take is recorded as `{"unreachable": ...}`. Nothing here is an actual Codex, GitHub, host or production
verification.
"""

from __future__ import annotations

import copy
from contextlib import contextmanager

import s7_delivery as D
import s7_stages as S

MOVED = "7" * 40            # another writer's commit on main (labelled)
EVIDENCE = "sha256:" + "e" * 64
OTHER_EVIDENCE = "sha256:" + "f" * 64
IMAGE_ID = "sha256:" + "d" * 64
PROFILE_HEX = "e" * 64
SOURCE_REVISION = "1" * 40
QUALIFICATION = "sha256:" + "5" * 64
AUTHORITY = "sha256:" + "a" * 64
OTHER_INSTANCE = "0" * 32
FAR = "2999-01-01T00:00:00+00:00"
PAST_LEASE = S.PAST
PENDING = "canary_owner_receipt_pending"
STARTUP_SECONDS = 0.0   # never a real wait: an unconfirmed receipt is read once


def rows(store, bucket):
    return S.rows(store, bucket)


def get(store, bucket, key):
    return S.get(store, bucket, key)


def put(store, bucket, key, body):
    S.put(store, bucket, key, body)


# ---- labelled doubles of the M7 tests ---------------------------------------------------------------------------
class FixedFacts:
    """LABELLED. M7 `tests/test_host_delivery_first_activation.py::FixedFacts`: the trusted `first_activation` port, fixed
    facts, every call counted. `during`, when set, runs once inside the first call (a sequential stand-in for a second
    caller: the M7 tests use a two-thread barrier there, which is not reproducible)."""

    def __init__(self, image=IMAGE_ID, profile=PROFILE_HEX, source=SOURCE_REVISION):
        self.facts = {"worker_image": image, "profile_digest": profile, "image_source_revision": source}
        self.calls, self.during = [], None

    def __call__(self, revision):
        self.calls.append(revision)
        action, self.during = self.during, None
        if action is not None:
            action()
        return dict(self.facts)


class CountingVerifier:
    """LABELLED. M7 `CountingVerifier`: any use of the verifier port is recorded and refused."""

    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        def record(*args, **kwargs):
            self.calls.append(name)
            raise AssertionError("the verifier must not be called")
        return record


class SwitchCanary:
    """LABELLED. M7 `tests/test_host_delivery_consumption_retry.py::OwnerCanary`: the owner fleet canary, pending until
    switched; every call recorded by the instance it was asked about. It is never an actual fleet canary."""

    def __init__(self):
        self.answer = {"passed": False, "pending": True, "reason_code": PENDING, "evidence": None}
        self.calls = []

    def __call__(self, target, descriptor, startup, **kwargs):
        self.calls.append((startup or {}).get("instance_id"))
        return dict(self.answer)

    def passes(self, evidence="sha256:" + "4" * 64):
        self.answer = {"passed": True, "reason_code": None, "evidence": evidence}


class ConductorFor:
    """LABELLED. M7 `ConductorFor`: grants the conductor role to one extra actor; everything else delegates."""

    def __init__(self, org, actor_id):
        self.org, self.actor_id = org, actor_id

    def actor(self, actor_id, role=None):
        if actor_id == self.actor_id and role == "conductor":
            return self.org.actor(actor_id)
        return self.org.actor(actor_id, role)


# ---- one case ---------------------------------------------------------------------------------------------------
class Case(S.Run):
    """A wired delivery (`S.Run`) whose owner commands are recorded with what they wrote and what followed."""

    def __init__(self, api, label, **kwargs):
        super().__init__(api, label, **kwargs)
        self.commands, self.canary, self.facts, self.counting = [], None, None, None

    # ---- views ----------------------------------------------------------------------------------------------
    def owner_view(self, plan_id=None):
        row = self.intent(plan_id)
        if row is None:
            return None
        out = {key: row.get(key) for key in ("stage", "previous_stage", "outcome", "reason_code", "attempts",
                                              "stage_entered_at", "stage_deadline", "updated_at", "merged_revision",
                                              "after_verification", "candidate_instance_id") if key in row}
        out["recoveries"] = [{"kind": rec.get("kind"), "evidence_ref": rec.get("evidence_ref"), "state": rec.get("state"),
                              "halted_reason_code": (rec.get("halted") or {}).get("reason_code"),
                              "interval": rec.get("interval")} for rec in row.get("recoveries") or []]
        if row.get("withdrawal") is not None:
            out["withdrawal"] = row["withdrawal"]
        out["sha"] = D.canonical_digest(row)
        return out

    def owner_queue(self, release_id=None):
        row = get(self.store, "release_queue", release_id or self.release_id())
        if row is None:
            return None
        return {key: row.get(key) for key in S.QUEUE_KEYS if key in row} | {
            "has_owner": bool(row.get("owner")), "manual_retries": len(row.get("manual_retries") or [])}

    def plan_sha(self, plan_id=None):
        return get(self.store, self.api.BUCKET_PLANS, plan_id or self.system["plan"]["plan_id"])["plan_sha256"]

    # ---- the commands ---------------------------------------------------------------------------------------
    def command(self, method, *args, note=None, plan_id=None, expect=None, via=None, injected=None, **kwargs):
        """One owner command through `D.guarded`: its result or its named refusal, whether it wrote ANYTHING to the
        store, and the digest of the whole store after it. `via` is another controller over the same store (a
        restart); `injected`, a dict a fault seam fills with the store digest right after ITS OWN write, so that a
        phase-two refusal is judged against what the injected fact left, not against the store before it."""
        out = D.guarded(self.system, getattr(via or self.delivery, method), *args, **kwargs)
        entry = {"n": len(self.commands), "call": method, "outcome": out,
                 "queue": self.owner_queue(), "intent": self.owner_view(plan_id)}
        if note:
            entry["note"] = note
        if expect is not None:
            entry["expect"] = expect
            unchanged = out["store"] == injected["store"] if injected is not None else out["wrote"] is False
            entry["as_expected"] = out.get("reason_code") == expect and unchanged
        self.commands.append(entry)
        return out

    def rung(self, expect, method, *args, note=None, plan_id=None, **kwargs):
        """One refusal of a ladder: the named code and NOTHING written."""
        return self.command(method, *args, note=note, plan_id=plan_id, expect=expect, **kwargs)

    def ladder_ok(self):
        return all(entry.get("as_expected") for entry in self.commands if "expect" in entry)

    def report(self, **extra):
        return super().report(commands=self.commands, ladder_ok=self.ladder_ok(),
                              verifier_calls=None if self.counting is None else list(self.counting.calls),
                              facts_calls=None if self.facts is None else list(self.facts.calls),
                              canary_calls=None if self.canary is None else list(self.canary.calls),
                              recoveries=[rec.get("kind") for rec in (self.intent() or {}).get("recoveries") or []],
                              **extra)


def ff_case(api, label, **github):
    """The `fast_forward` merger (M7 tests/test_host_delivery_requalification.py `ff_build`)."""
    return Case(api, label, github=D.FakeGitHub(api, fast_forward=True, **github))


def ticket_bound(record):
    """LABELLED: the release record's candidate carries a Zeus ticket binding to a ticket that does not exist
    (`ticket_binding`: "Ticket missing"); the gate compares only revision, tree, policy and repository."""
    return {**record, "candidate": {**record["candidate"], "zeus_ticket": {"id": "ticket-1", "revision": 1,
                                                                            "content_hash": "0" * 64}}}


def restore(run, bucket, key, body):
    """Put a row back exactly as it was (a labelled injected fact, reverted)."""
    put(run.store, bucket, key, body)


# ---- 1. withdraw ------------------------------------------------------------------------------------------------
def stale_pair(api, label):
    """M7 `stale_pair`: H1 at `awaiting_ci` with an OPEN PR and H2 registered without an intent, both on the old base,
    then main moves (another writer merged something else). The plan's filed canary request of M7 is a FILE, kept out."""
    run = Case(api, label, github=D.FakeGitHub(api, fast_forward=True, checks=((D.CHECK, "pending"),)))
    run.until(api.AWAITING_CI, limit=3)
    run.second = S.successor(run, base=D.BASE)
    run.github.main = MOVED   # labelled provider fact
    return run


def plan_digests(run, plan_ids):
    return {plan_id: D.canonical_digest(get(run.store, run.api.BUCKET_PLANS, plan_id)) for plan_id in plan_ids}


def withdraw(api):
    out = {}
    # ---- D3: the ladder, then both stale plans retired -----------------------------------------------------------
    run = stale_pair(api, "stale_pair")
    api_ = run.api
    p1, p2 = "delivery-plan-1", run.second["plan"]["plan_id"]
    sha1, sha2 = run.plan_sha(p1), run.plan_sha(p2)
    reason = "reviewed_base_moved"
    run.rung("plan_unregistered", "withdraw", "no-such-plan", sha1, reason, EVIDENCE, plan_id=p1)
    run.rung("plan_unregistered", "withdraw", None, sha1, reason, EVIDENCE, note="a plan id that is not a string", plan_id=p1)
    run.rung("withdraw_plan_mismatch", "withdraw", p1, "0" * 64, reason, EVIDENCE, plan_id=p1)
    run.rung("withdraw_reason_unsupported", "withdraw", p1, sha1, "because", EVIDENCE, plan_id=p1)
    run.rung("withdraw_reason_unsupported", "withdraw", p1, sha1, "", EVIDENCE, note="an empty reason", plan_id=p1)
    run.rung("withdraw_evidence_invalid", "withdraw", p1, sha1, reason, "decision.md", plan_id=p1)
    run.rung("withdraw_evidence_invalid", "withdraw", p1, sha1, reason, None, note="evidence that is not a string",
             plan_id=p1)
    run.rung("withdraw_evidence_invalid", "withdraw", p1, sha1, reason, "sha256:" + "E" * 64,
             note="the digest is lowercase hex", plan_id=p1)
    run.github.observe_error = ConnectionError("injected: GitHub unreachable")   # LABELLED
    run.rung("withdraw_unobservable", "withdraw", p1, sha1, reason, EVIDENCE, plan_id=p1)
    run.github.observe_error = None
    real_github, run.delivery.github = run.delivery.github, None   # LABELLED: no GitHub port
    run.rung("withdraw_unobservable", "withdraw", p1, sha1, reason, EVIDENCE, note="no GitHub port", plan_id=p1)
    run.delivery.github = real_github
    run.github.main = D.BASE   # labelled: main is the reviewed base again
    run.rung("withdraw_not_stale", "withdraw", p1, sha1, reason, EVIDENCE, plan_id=p1)
    run.rung("withdraw_not_stale", "withdraw", p1, sha1, "descriptor_predecessor_moved", EVIDENCE, plan_id=p1)
    run.rung("withdraw_not_stale", "withdraw", p1, sha1, "merged_tree_mismatch", EVIDENCE, plan_id=p1)
    run.github.mainline.append(D.REVISION)   # labelled: the candidate is on main after all
    run.github.main = D.REVISION
    run.rung("withdraw_merge_observed", "withdraw", p1, sha1, reason, EVIDENCE, plan_id=p1)
    run.github.mainline.remove(D.REVISION)
    run.github.main = MOVED
    release2 = run.second["plan"]["release_id"]
    record = get(run.store, "releases", release2)
    put(run.store, "releases", release2, {**record, "status": "cancelled"})   # LABELLED: the release is not queueable
    run.rung("withdraw_queue_refused", "withdraw", p2, sha2, reason, EVIDENCE, note="H2's release is not queueable",
             plan_id=p2)
    put(run.store, "releases", release2, record)
    # the fence a tick takes (M7 `test_withdrawal_takes_the_same_fence_a_tick_takes`)
    held = api_.queue(run.store).claim(now=api_.now())   # LABELLED: another controller holds the lease
    out["held_fence_claimed"] = held is not None
    run.rung("controller_lease_held", "withdraw", p1, sha1, reason, EVIDENCE, note="another controller's lease",
             plan_id=p1)
    with run.store.transaction() as tx:   # LABELLED: that controller's lease ends and the row is re-armed
        tx.put("deployment_locks", "controller", {"owner": None, "lease_until": None})
        row = tx.get("release_queue", run.release_id())
        row.update(status="queued", owner=None, lease_until=None, retry_at=None, attempt=0)
        tx.put("release_queue", row["id"], row)
    plans = plan_digests(run, (p1, p2))
    prs = D.canonical_digest(run.github.prs)
    run.command("withdraw", p1, sha1, reason, EVIDENCE, note="H1: an open stage is fenced like a tick", plan_id=p1)
    run.command("withdraw", p2, sha2, reason, EVIDENCE, note="H2: registered, no intent yet", plan_id=p2)
    out["plans_unchanged"] = plan_digests(run, (p1, p2)) == plans
    out["prs_unchanged"] = D.canonical_digest(run.github.prs) == prs
    out["h2_queue"] = run.owner_queue(run.second["plan"]["release_id"])
    run.command("withdraw", p1, sha1, reason, EVIDENCE, note="the identical replay is cached", plan_id=p1)
    run.rung("withdrawal_conflict", "withdraw", p1, sha1, "descriptor_predecessor_moved", EVIDENCE,
             note="another reason for a withdrawn plan", plan_id=p1)
    run.rung("withdrawal_conflict", "withdraw", p1, sha1, reason, OTHER_EVIDENCE,
             note="another evidence for a withdrawn plan", plan_id=p1)
    S.restarted(run)   # a new controller never selects a withdrawn plan and touches nothing external
    run.tick(note="a restarted controller over the withdrawn plans")
    out["status_after_restart"] = D.call(lambda: {
        "counts": run.delivery.status()["counts"],
        "reasons": sorted(view["withdrawal"]["reason_code"] for view in run.delivery.status()["deliveries"])})
    out["stale_pair"] = run.report(prs=run.github.prs)
    S.stop(run)
    # ---- withdrawal refused only at the crash, the fence and the stage shapes -----------------------------------
    run = stale_pair(api, "crash_between_withdrawal_and_queue_finish")
    sha = run.plan_sha(p1)

    def crash(*args, **kwargs):
        raise RuntimeError("injected: controller died after the intent commit")   # LABELLED
    run.delivery.queue.finish = crash
    run.command("withdraw", p1, sha, reason, EVIDENCE, note="the intent commits, the queue finish crashes", plan_id=p1)
    del run.delivery.queue.finish   # the class method again
    run.wait(3600)   # the dead controller's lease has expired
    run.command("withdraw", p1, sha, reason, EVIDENCE, note="the replay finishes the queue row and nothing else",
                plan_id=p1)
    out["crash_between_withdrawal_and_queue_finish"] = run.report()
    S.stop(run)
    # ---- the intent moved between the read-only check and the fenced write ---------------------------------------
    run = stale_pair(api, "intent_changed_under_the_fence")
    sha = run.plan_sha(p1)
    real_observe, seen = run.github.observe, []

    def moving(candidate):
        seen.append(1)
        if len(seen) == 2:   # the SECOND observation is the fenced one: another writer moved the intent (LABELLED)
            row = run.intent(p1)
            put(run.store, api.BUCKET_INTENTS, p1, {**row, "updated_at": "moved-by-another-writer"})
        return real_observe(candidate)
    run.github.observe = moving
    run.command("withdraw", p1, sha, reason, EVIDENCE, note="refused; the lease goes back with no attempt spent",
                plan_id=p1)
    del run.github.observe
    out["intent_changed_queue_after_refusal"] = run.owner_queue()
    run.wait(1)
    run.command("withdraw", p1, sha, reason, EVIDENCE, note="the same evidence then withdraws", plan_id=p1)
    out["intent_changed_under_the_fence"] = run.report()
    S.stop(run)
    # ---- a touched host is never withdrawn ------------------------------------------------------------------------
    run = ff_case(api, "touched_host")
    run.tick()
    intent = run.intent()   # LABELLED: M7 writes this row itself (the delivery already bound a descriptor)
    put(run.store, api.BUCKET_INTENTS, intent["id"], {**intent, "stage": api.BLOCKED, "descriptor": {"schema": "fixture"}})
    run.rung("withdraw_host_touched", "withdraw", p1, run.plan_sha(p1), reason, EVIDENCE, plan_id=p1)
    out["touched_host"] = run.report()
    S.stop(run)
    run = ff_case(api, "active_delivery")
    run.until(api.ACTIVE, limit=40)
    run.rung("withdraw_host_touched", "withdraw", p1, run.plan_sha(p1), reason, EVIDENCE, note="an active delivery",
             plan_id=p1)
    out["active_delivery"] = run.report()
    S.stop(run)
    # ---- the held migration successor and the verification debt -------------------------------------------------
    run = ff_case(api, "migration_held")
    run.tick()
    intent = run.intent()   # LABELLED: a held migration successor (M7 tests/test_host_delivery_migration.py stages one)
    put(run.store, api.BUCKET_INTENTS, intent["id"], {**intent, "held": {"migration_id": "migration-1"}})
    run.rung("withdraw_migration_held", "withdraw", p1, run.plan_sha(p1), reason, EVIDENCE, plan_id=p1)
    out["migration_held"] = run.report()
    S.stop(run)
    run = Case(api, "verification_debt", verified=False,
               verifier=D.Verifier(api, outcome=S.checked(cleanup={"state": "unconfirmed"})))
    run.tick(note="registered enters verifying")
    run.tick(note="the evaluation ends with its cleanup unconfirmed: an unresolved attempt")
    run.github.main = MOVED   # the reviewed base really moved
    run.rung("withdraw_verification_unresolved", "withdraw", p1, run.plan_sha(p1), reason, EVIDENCE, plan_id=p1)
    out["verification_debt"] = run.report(verification=(run.intent() or {}).get("verification"))
    S.stop(run)
    # ---- a recorded tree mismatch is retired only as what it is --------------------------------------------------
    run = Case(api, "recorded_tree_mismatch", github=D.FakeGitHub(api, merged_tree="d" * 64))
    run.until(api.MERGED, limit=6)
    sha = run.plan_sha(p1)
    run.rung("withdraw_merge_observed", "withdraw", p1, sha, reason, EVIDENCE, note="not under a base-moved reason",
             plan_id=p1)
    run.command("withdraw", p1, sha, "merged_tree_mismatch", EVIDENCE, note="retired as what it is", plan_id=p1)
    out["recorded_tree_mismatch"] = run.report(descriptor_row=D.descriptor_of(run.system))
    S.stop(run)
    # ---- a stale predecessor binding is withdrawn under its own reason ----------------------------------------
    run = Case(api, "stale_predecessor_binding", github=D.FakeGitHub(api, fast_forward=True),
               plan_overrides={"expected": "4" * 64})
    run.until(api.MERGED, limit=6)
    sha = run.plan_sha(p1)
    run.rung("withdraw_not_stale", "withdraw", p1, sha, reason, EVIDENCE, note="main IS still the reviewed base",
             plan_id=p1)
    run.command("withdraw", p1, sha, "descriptor_predecessor_moved", EVIDENCE, plan_id=p1)
    out["stale_predecessor_binding"] = run.report()
    S.stop(run)
    return out


# ---- 2. resume (the legacy merged/unverified halt) ---------------------------------------------------------------
@contextmanager
def moved(run, bucket, key, change):
    """A labelled injected fact: the row is changed for the duration of the block and put back exactly as it was."""
    original = get(run.store, bucket, key)
    put(run.store, bucket, key, change(copy.deepcopy(original)))
    try:
        yield original
    finally:
        put(run.store, bucket, key, original)


def legacy_case(api, label, **kwargs):
    """A reviewed, NOT verified release behind the labelled `Verifier` on the `fast_forward` merger (M7
    tests/test_host_delivery_verification.py `build`, without the real evaluator, container or repository)."""
    verifier = D.Verifier(api)
    run = Case(api, label, verified=False, verifier=verifier, github=D.FakeGitHub(api, fast_forward=True), **kwargs)
    run.verifier = verifier
    return run


def legacy_halt(run):
    """M7 `legacy_halt` (LABELLED FIXTURE, the one crafted write of its test): the 5aa controller's recorded shape,
    published, CI passed, merged by the lease fast-forward, then halted at `merged` with `release_not_verified`. The
    GitHub side goes through the labelled double, the queue through the real `ReleaseQueue`; the intent is the one
    crafted write, with exactly the fields that controller wrote."""
    api, plan, github = run.api, run.system["plan"], run.github
    candidate = run.system["release"]["candidate"]
    published = github.publish(candidate)
    github.merge(candidate, published)
    queue = api.queue(run.store)
    queue.enqueue(plan["release_id"], "host delivery plan " + plan["plan_id"])
    claim = queue.claim(now=api.now(), eligible=lambda row: row["id"] == plan["release_id"])
    queue.finish(claim, {"status": "blocked", "reason": "release_not_verified"}, api.now())
    now = D.clock(api)()
    validated = api.validate_plan(plan)
    halted = {**api.new_intent(validated, api.plan_digest(validated), now),
              "stage": api.BLOCKED, "previous_stage": api.MERGED, "outcome": "blocked",
              "reason_code": "release_not_verified", "attempts": 1, "head": candidate["revision"],
              "pr_number": published["number"], "pr_url": published["url"],
              "merged_revision": candidate["revision"], "last_check_state": "passed", "updated_at": now}
    put(run.store, api.BUCKET_INTENTS, plan["plan_id"], halted)
    return halted


def resume_call(run, evidence=EVIDENCE, *, expect=None, note=None, plan_id=None, plan_sha=None, injected=None):
    plan_id = plan_id or run.system["plan"]["plan_id"]
    if plan_sha is None:
        row = get(run.store, run.api.BUCKET_PLANS, plan_id)
        plan_sha = row["plan_sha256"] if row else "0" * 64
    return run.command("resume", plan_id, plan_sha, evidence, expect=expect, note=note, injected=injected)


def during_qualify(run, action, injected):
    """M7 tests/test_release_verifier.py `during_qualify` (LABELLED SEAM): the merge owner's qualification, which runs
    between phase 1 and the one transaction of phase 2, first performs `action`, a write by someone else."""
    real = run.github.qualify

    def qualify(candidate, revision):
        action()
        injected["store"] = D.store_digest(run.store)
        return real(candidate, revision)
    run.github.qualify = qualify


def resume(api):
    out = {}
    # ---- the ladder before the halt exists -----------------------------------------------------------------------
    run = legacy_case(api, "resume_ladder")
    plan_id = run.system["plan"]["plan_id"]
    sha = run.plan_sha()
    run.rung("resume_evidence_invalid", "resume", plan_id, sha, "decision.md")
    run.rung("resume_evidence_invalid", "resume", plan_id, sha, None, note="evidence that is not a string")
    run.rung("plan_unregistered", "resume", "no-such-plan", sha, EVIDENCE)
    run.rung("plan_unregistered", "resume", None, sha, EVIDENCE, note="a plan id that is not a string")
    run.rung("resume_plan_mismatch", "resume", plan_id, "0" * 64, EVIDENCE)
    run.rung("resume_not_applicable", "resume", plan_id, sha, EVIDENCE, note="registered, no intent yet")
    run.tick(note="registered enters verifying")
    run.rung("resume_not_applicable", "resume", plan_id, sha, EVIDENCE, note="verifying is not the resumable shape")
    S.stop(run)
    out["before_the_halt"] = run.report()
    # ---- the observation ladder on the crafted halt ------------------------------------------------------------
    run = legacy_case(api, "resume_observation_ladder")
    plan_id, halted = run.system["plan"]["plan_id"], legacy_halt(run)
    sha = run.plan_sha()
    run.github.observe_error = ConnectionError("injected: GitHub unreachable")   # LABELLED
    resume_call(run, expect="resume_unobservable", note="GitHub unreachable")
    run.github.observe_error = None
    real_github, run.delivery.github = run.delivery.github, None   # LABELLED: no GitHub port
    resume_call(run, expect="resume_unobservable", note="no GitHub port")
    run.delivery.github = real_github
    run.github.mainline.remove(D.REVISION)   # labelled: main no longer carries the recorded revision
    resume_call(run, expect="resume_merge_mismatch", note="GitHub does not show the recorded merge")
    run.github.mainline.append(D.REVISION)
    run.github.merged_tree = "d" * 64   # labelled: the merged tree is not the reviewed one
    resume_call(run, expect="resume_tree_mismatch", note="the merge owner's own qualification fails")
    run.github.merged_tree = D.TREE
    broken = D.BrokenStore(run.store)   # LABELLED: the store is unavailable to the controller
    real_store, run.delivery.store = run.delivery.store, broken
    broken.failing = True
    resume_call(run, expect="resume_unobservable", note="the store is unavailable")
    broken.failing = False
    run.delivery.store = real_store
    record = get(run.store, "releases", run.release_id())
    for change, expect in (({"status": "rejected"}, "resume_release_rejected"),
                           ({"status": "cancelled"}, "resume_release_cancelled"),
                           ({"policy_hash": "0" * 64}, "resume_release_policy_mismatch"),
                           ({"reviews": []}, "resume_release_reviews_incomplete"),
                           ({"status": "proposed"}, "resume_release_not_reviewed")):
        put(run.store, "releases", run.release_id(), {**record, **change})   # LABELLED: the release record moved
        resume_call(run, expect=expect, note="the release gate: " + ",".join(sorted(change)))
    put(run.store, "releases", run.release_id(), record)
    with moved(run, "release_queue", run.release_id(), lambda row: {**row, "status": "withdrawn"}):
        resume_call(run, expect="resume_queue_withdrawn", note="a queue row that is not runnable (LABELLED status)")
    with moved(run, "releases", run.release_id(), ticket_bound):
        resume_call(run, expect="resume_release_ticket_changed", note="the candidate's ticket binding no longer holds")
    out["observation_ladder"] = run.report(halted=halted)
    S.stop(run)
    # ---- phase two: a write by someone else between the read-only checks and the one transaction --------------
    for name, expect, action in (
            ("intent_moved", "resume_intent_changed",
             lambda run: put(run.store, run.api.BUCKET_INTENTS, run.system["plan"]["plan_id"],
                             {**run.intent(), "updated_at": "changed"})),
            ("controller_lease_live", "resume_controller_running",
             lambda run: put(run.store, "deployment_locks", "controller", {"owner": "other", "lease_until": FAR})),
            ("queue_row_moved", "resume_queue_changed",
             lambda run: put(run.store, "release_queue", run.release_id(),
                             {**get(run.store, "release_queue", run.release_id()), "reason": "changed"})),
            ("plan_row_moved", "resume_intent_changed",
             lambda run: put(run.store, run.api.BUCKET_PLANS, run.system["plan"]["plan_id"],
                             {**get(run.store, run.api.BUCKET_PLANS, run.system["plan"]["plan_id"]),
                              "updated_at": "x"})),
            ("predecessor_in_flight", "resume_predecessor_in_flight",
             lambda run: put(run.store, run.api.BUCKET_INTENTS, "other-plan", {
                 "id": "other-plan", "plan_id": "other-plan", "target_id": run.system["plan"]["target_id"],
                 "stage": run.api.MERGED}))):
        run = legacy_case(api, "resume_phase_two_" + name)
        legacy_halt(run)
        injected = {}
        during_qualify(run, lambda run=run, action=action: action(run), injected)
        resume_call(run, expect=expect, note="rolled back as a whole: " + name, injected=injected)
        out["phase_two_" + name] = run.report()
        S.stop(run)
    run = legacy_case(api, "resume_phase_two_retry_then_crash")
    legacy_halt(run)
    real = run.delivery.queue.retry

    def retry_then_crash(release_id, reason, *, transaction=None):
        real(release_id, reason, transaction=transaction)
        raise RuntimeError("labelled crash after the in-transaction retry")   # LABELLED
    run.delivery.queue.retry = retry_then_crash
    resume_call(run, expect="resume_unobservable", note="the in-transaction queue retry is rolled back with it")
    del run.delivery.queue.retry
    out["phase_two_retry_then_crash"] = run.report()
    S.stop(run)
    # ---- the successful resume, driven to active (M7 `test_the_merged_unverified_legacy_halt_resumes_once_...`) -----
    run = legacy_case(api, "resume_legacy_halt")
    plan_id, halted = run.system["plan"]["plan_id"], legacy_halt(run)
    sha = run.plan_sha()
    resume_call(run, note="the legacy halt moves back to verifying")
    resume_call(run, note="the identical replay is recognized from the record and writes nothing")
    intent = run.intent()
    out["recovery_halted_is_the_legacy_halt"] = intent["recoveries"][0]["halted"] == {
        key: halted[key] for key in ("stage", "previous_stage", "reason_code", "outcome", "attempts", "error_type",
                                     "updated_at")}
    results = run.until(api.ACTIVE, limit=40)
    out["visited"] = run.stage_path()
    out["no_second_publication_or_merge"] = [run.github.publishes, run.github.merges]
    out["release_after"] = D.call(lambda: {key: get(run.store, "releases", run.release_id()).get(key)
                                           for key in ("status",)})
    out["verifier_evaluated"] = len(run.verifier.evaluated)
    resume_call(run, note="the same evidence after the delivery advanced is still that one recovery")
    resume_call(run, "sha256:" + "cd" * 32, expect="resume_conflict", note="another evidence conflicts")
    out["resume_legacy_halt"] = run.report(reached_active=results[-1]["stage"] == api.ACTIVE, halted=halted,
                                           status=D.call(lambda: run.delivery.status()["deliveries"][0]["recoveries"]))
    out["exhausted"] = {"unreachable": "resume_exhausted needs a second release_not_verified halt at merged after a "
                                       "recorded recovery; only the crafted legacy write makes that shape, and the "
                                       "characterization never re-crafts an intent"}
    S.stop(run)
    return out


# ---- 3. resume_first_activation ---------------------------------------------------------------------------------
def first_halt(api, label, *, canary=False, **kwargs):
    """M7 `halted` (first activation) and the retry file's `halted`: a HISTORICAL null+`unchanged` plan (the row
    `register` used to write, `S.register_historical`) driven to the real `unchanged_without_predecessor` halt; with
    `canary`, the plan names the owner fleet canary (a switchable pending double) and a 10 s consumption window."""
    overrides = {"image": api.UNCHANGED, "profile": api.UNCHANGED}
    switch = None
    if canary:
        overrides.update(canary=api.CANARY_FLEET, consumption_timeout=10)
        switch = SwitchCanary()
        kwargs["canaries"] = {api.CANARY_FLEET: switch}
    run = Case(api, label, plan_overrides=overrides, register_plan=False, **kwargs)
    S.register_historical(run)
    run.until(api.MERGED, limit=8)
    run.tick(note="the historical unbound plan halts: unchanged_without_predecessor")
    run.facts, run.counting, run.canary = FixedFacts(), CountingVerifier(), switch
    run.delivery.first_activation = run.facts
    run.delivery.verifier = run.counting
    return run


def first_doc(run, **overrides):
    """M7 first-activation `document`: the binding document over the CURRENT plan row and halted intent."""
    api = run.api
    row = get(run.store, api.BUCKET_PLANS, run.system["plan"]["plan_id"])
    intent = run.intent()
    body = {"schema": api.FIRST_ACTIVATION_SCHEMA, "kind": api.RECOVERY_FIRST_ACTIVATION,
            "plan_id": row["plan_id"], "plan_sha256": row["plan_sha256"], "pin_sha256": row["pin"]["sha256"],
            "target_id": row["target_id"], "release_id": run.system["release"]["id"],
            "candidate_revision": run.system["release"]["candidate"]["revision"],
            "candidate_tree": run.system["release"]["candidate"]["tree"],
            "halt": {key: intent[key] for key in ("stage", "previous_stage", "reason_code", "updated_at")},
            "expected_descriptor": None, "predecessor": None, "worker_image": IMAGE_ID,
            "profile_digest": PROFILE_HEX,
            "qualification": {"image_source_revision": SOURCE_REVISION, "evidence": QUALIFICATION},
            "approved_by": "conductor"}
    body.update(overrides)
    return body, "sha256:" + api.digest(body)


def document_command(run, method, doc, body=None, evidence=None, *, expect=None, note=None, plan_sha=None, via=None,
                     plan_id=None, injected=None):
    """One document-bearing owner command over the current plan; `doc` builds the default document."""
    if body is None:
        body, evidence = doc(run)
    plan_id = plan_id or run.system["plan"]["plan_id"]
    return run.command(method, plan_id, plan_sha or run.plan_sha(plan_id), body, evidence or "sha256:" + run.api.digest(body),
                       expect=expect, note=note, via=via, injected=injected)


def first_command(run, body=None, evidence=None, **kwargs):
    return document_command(run, "resume_first_activation", first_doc, body, evidence, **kwargs)


def first_ladder(api):
    """M7 first-activation refusal tests, each writing nothing, over one halted delivery."""
    out = {}
    run = first_halt(api, "first_activation_ladder")
    plan_id = run.system["plan"]["plan_id"]
    sha = run.plan_sha()
    # the document grammar, exactly (`test_the_document_grammar_refuses_every_field_it_does_not_bind_exactly`)
    grammar = {}
    for field, value in (("predecessor", "sha256:" + "0" * 64), ("expected_descriptor", "f" * 64),
                         ("worker_image", "zeus:latest"), ("profile_digest", "none"),
                         ("kind", api.RECOVERY_VERIFICATION_MISSING),
                         ("qualification", {"image_source_revision": "x", "evidence": QUALIFICATION})):
        body, evidence = first_doc(run, **{field: value})
        grammar[field] = D.call(api.validate_first_activation, body)
        first_command(run, body, evidence, expect="first_activation_invalid", note="grammar: " + field)
    out["grammar"] = grammar
    valid, _ = first_doc(run)
    out["grammar"]["extra_field"] = D.call(api.validate_first_activation, {**valid, "extra": 1})
    out["grammar"]["valid_kind"] = api.validate_first_activation(valid)["kind"]
    out["facts_calls_after_grammar"] = list(run.facts.calls)
    # evidence, plan and pin identity
    body, evidence = first_doc(run)
    run.rung("resume_evidence_invalid", "resume_first_activation", plan_id, sha, body, "decision.md")
    run.rung("resume_evidence_invalid", "resume_first_activation", plan_id, sha, body, None,
             note="evidence that is not a string")
    run.rung("first_activation_evidence_mismatch", "resume_first_activation", plan_id, sha, body, "sha256:" + "0" * 64)
    run.rung("plan_unregistered", "resume_first_activation", "no-such-plan", sha, body, evidence)
    run.rung("resume_plan_mismatch", "resume_first_activation", plan_id, "0" * 64, body, evidence,
             note="the call's plan digest")
    other, other_evidence = first_doc(run, plan_sha256="0" * 64)
    run.rung("resume_plan_mismatch", "resume_first_activation", plan_id, sha, other, other_evidence,
             note="the document's plan digest")
    other, other_evidence = first_doc(run, plan_id="another-plan")
    run.rung("first_activation_plan_mismatch", "resume_first_activation", plan_id, sha, other, other_evidence)
    for field, value, code in (("pin_sha256", "0" * 64, "first_activation_pin_mismatch"),
                               ("release_id", "release-other", "first_activation_release_id_mismatch"),
                               ("target_id", "other-service", "first_activation_target_id_mismatch"),
                               ("candidate_revision", "0" * 40, "first_activation_candidate_revision_mismatch"),
                               ("candidate_tree", "0" * 64, "first_activation_candidate_tree_mismatch"),
                               ("approved_by", "lead:improvement", "first_activation_approver_invalid")):
        other, other_evidence = first_doc(run, **{field: value})
        first_command(run, other, other_evidence, expect=code, note="claim: " + field)
    halt = first_doc(run)[0]["halt"]
    other, other_evidence = first_doc(run, halt={**halt, "updated_at": "2999-01-01T00:00:00+00:00"})
    first_command(run, other, other_evidence, expect="first_activation_halt_mismatch", note="the halt is exact")
    # the approver
    author = run.system["release"]["candidate"]["author"]
    real_org = run.delivery.org
    run.delivery.org = ConductorFor(real_org, author)   # LABELLED: the author holds the conductor role
    other, other_evidence = first_doc(run, approved_by=author)
    first_command(run, other, other_evidence, expect="first_activation_approver_author",
                  note="the candidate author cannot approve even as a conductor")
    run.delivery.org = None   # LABELLED: no organization
    first_command(run, expect="first_activation_release_reviews_incomplete",
                  note="no organization: the release gate cannot derive the author's lead, so it refuses before the "
                       "approver check and first_activation_approver_unavailable is shadowed")
    run.delivery.org = real_org
    # the trusted port
    for kwargs, code in (({"image": "sha256:" + "9" * 64}, "first_activation_image_mismatch"),
                         ({"profile": "9" * 64}, "first_activation_profile_mismatch"),
                         ({"source": "2" * 40}, "first_activation_qualification_mismatch")):
        real_port = run.delivery.first_activation
        run.delivery.first_activation = FixedFacts(**kwargs)
        first_command(run, expect=code, note="the port's re-derived facts differ from the document")
        run.delivery.first_activation = real_port
    run.delivery.first_activation = None
    first_command(run, expect="first_activation_unavailable", note="no port")

    def unconfigured(_revision):
        raise api.DeliveryRefused("first_activation_image_unconfigured", "worker_image")   # LABELLED
    run.delivery.first_activation = unconfigured
    first_command(run, expect="first_activation_image_unconfigured", note="the port refuses by its own code")

    def exploding(_revision):
        raise RuntimeError("injected: the port crashed")   # LABELLED
    run.delivery.first_activation = exploding
    first_command(run, expect="first_activation_unavailable", note="the port raises")
    run.delivery.first_activation = lambda _revision: ["not", "facts"]   # LABELLED
    first_command(run, expect="first_activation_unavailable", note="the port answers a non-document")
    run.delivery.first_activation = run.facts
    # the release gate
    record = get(run.store, "releases", run.release_id())
    for change, code in (({"status": "reviewed"}, "first_activation_release_reviewed"),
                         ({"status": "rejected"}, "first_activation_release_rejected"),
                         ({"policy_hash": "0" * 64}, "first_activation_release_policy_mismatch")):
        put(run.store, "releases", run.release_id(), {**record, **change})   # LABELLED: the release record moved
        first_command(run, expect=code, note="the release gate: " + ",".join(sorted(change)))
    put(run.store, "releases", run.release_id(), record)
    with moved(run, "releases", run.release_id(), ticket_bound):
        first_command(run, expect="resume_release_ticket_changed", note="the candidate's ticket binding no longer holds")
    # the controller lease (restored) and an active pointer of this release (restored)
    lock = get(run.store, "deployment_locks", "controller")
    put(run.store, "deployment_locks", "controller", {"id": "controller", "lease_until": FAR})
    first_command(run, expect="resume_controller_running", note="a live controller lease")
    put(run.store, "deployment_locks", "controller", lock)
    put(run.store, "deployment", "active", {"id": "active", "release_id": run.release_id()})   # LABELLED pointer
    first_command(run, expect="first_activation_release_active", note="an active pointer of this release")
    put(run.store, "deployment", "active", {"id": "active"})
    # a store outage, then the predecessor descriptor and another open delivery of the target (never undone)
    broken = D.BrokenStore(run.store)
    real_store, run.delivery.store = run.delivery.store, broken
    broken.failing = True
    first_command(run, expect="resume_unobservable", note="the store is unavailable")
    broken.failing = False
    run.delivery.store = real_store
    put(run.store, "deployment", "active", {"id": "active"})
    put(run.store, api.BUCKET_INTENTS, "other-plan", {"id": "other-plan", "plan_id": "other-plan",
                                                        "target_id": run.system["plan"]["target_id"],
                                                        "stage": api.MERGED})   # LABELLED: another open delivery
    first_command(run, expect="first_activation_target_in_flight", note="another open delivery of the target")
    put(run.store, api.BUCKET_INTENTS, "other-plan", {"id": "other-plan", "plan_id": "other-plan",
                                                        "target_id": run.system["plan"]["target_id"],
                                                        "stage": api.ACTIVE})
    put(run.store, api.BUCKET_DESCRIPTORS, run.system["plan"]["target_id"], {
        "id": run.system["plan"]["target_id"], "target_id": run.system["plan"]["target_id"],
        "descriptor": {"revision": "a" * 40}})   # LABELLED: a predecessor descriptor unexpectedly present
    first_command(run, expect="first_activation_predecessor_present", note="a predecessor descriptor is present")
    out["ladder"] = run.report()
    S.stop(run)
    # not the first-activation shape at all (`test_a_delivery_not_in_the_first_activation_shape_is_not_applicable`)
    run = Case(api, "first_activation_not_applicable")
    run.until(api.MERGED, limit=8)
    run.facts = FixedFacts()
    run.delivery.first_activation = run.facts
    first_command(run, expect="first_activation_invalid",
                  note="an ordinary merged delivery: its halt has no reason code, so the document is invalid "
                       "(M7 asserts only DeliveryRefused)")
    intent = run.intent()
    body, evidence = first_doc(run, halt={"stage": api.BLOCKED, "previous_stage": api.MERGED,
                                          "reason_code": "unchanged_without_predecessor",
                                          "updated_at": intent["updated_at"]})
    first_command(run, body, evidence, expect="resume_not_applicable",
                  note="a well-formed document over a delivery that is not in the first-activation shape")
    out["not_applicable"] = run.report()
    S.stop(run)
    return out


def first_success(api):
    out = {}
    # ---- a first boot binds the re-derived tuple and prepare_switch resolves it -----------------------------------
    run = first_halt(api, "first_activation_bound")
    body, evidence = first_doc(run)
    before = {"release": D.canonical_digest(get(run.store, "releases", run.release_id())),
              "descriptors": D.canonical_digest(rows(run.store, api.BUCKET_DESCRIPTORS))}
    first_command(run, body, evidence, note="the tuple is bound and the delivery is back at merged")
    out["facts_asked"] = list(run.facts.calls)
    out["status_recovery"] = D.call(lambda: run.delivery.status()["deliveries"][0]["recoveries"][-1])
    first_command(run, body, evidence, note="the identical replay is cached")
    run.tick(note="the next ordinary tick binds the descriptor in _prepare_switch")
    descriptor = (run.intent() or {}).get("descriptor") or {}
    out["descriptor_binding"] = {key: descriptor.get(key) for key in ("worker_image", "profile_digest", "predecessor")}
    out["release_unchanged"] = before["release"] == D.canonical_digest(get(run.store, "releases", run.release_id()))
    bare = api.HostDelivery(run.store, run.system["org"])   # a restarted controller over the same store
    first_command(run, body, evidence, via=bare, note="a bare restarted controller answers from the record")
    other, other_evidence = first_doc(run, halt=body["halt"],
                                      qualification={"image_source_revision": SOURCE_REVISION,
                                                     "evidence": "sha256:" + "6" * 64})
    first_command(run, other, other_evidence, expect="resume_conflict", note="another document conflicts")
    out["bound"] = run.report(descriptors_before=before["descriptors"])
    S.stop(run)
    # ---- a bound first activation drains, switches, starts and is consumed ---------------------------------------
    run = first_halt(api, "first_activation_to_active")
    first_command(run, note="the binding")
    results = run.until(api.ACTIVE, limit=40)
    out["to_active"] = run.report(reached_active=results[-1]["stage"] == api.ACTIVE,
                                  visited=run.stage_path(), descriptor_row=D.descriptor_of(run.system),
                                  deployment=get(run.store, "deployment", "active"))
    S.stop(run)
    # ---- two "concurrent" resumes, sequentially on the memory store -----------------------------------------------
    run = first_halt(api, "first_activation_two_resumes")
    body, evidence = first_doc(run)
    run.facts.during = lambda: first_command(run, body, evidence, note="the second caller commits first")
    first_command(run, body, evidence, note="the first caller finds the record when it reaches the transaction")
    out["two_resumes"] = run.report(manual_retries=len(get(run.store, "release_queue", run.release_id())["manual_retries"]),
                                    recoveries_n=len((run.intent() or {}).get("recoveries") or []))
    S.stop(run)
    # ---- phase two: a write by someone else between the port and the one transaction ------------------------------
    for name, expect, action in (
            ("intent_moved", "resume_intent_changed",
             lambda run: put(run.store, run.api.BUCKET_INTENTS, run.system["plan"]["plan_id"],
                             {**run.intent(), "updated_at": "changed"})),
            ("controller_lease_live", "resume_controller_running",
             lambda run: put(run.store, "deployment_locks", "controller", {"id": "controller", "lease_until": FAR})),
            ("queue_row_moved", "resume_queue_changed",
             lambda run: put(run.store, "release_queue", run.release_id(),
                             {**get(run.store, "release_queue", run.release_id()), "reason": "changed"}))):
        run = first_halt(api, "first_activation_phase_two_" + name)
        injected = {}

        def seam(run=run, action=action, injected=injected):
            action(run)
            injected["store"] = D.store_digest(run.store)
        run.facts.during = seam
        first_command(run, expect=expect, note="rolled back as a whole: " + name, injected=injected)
        out["phase_two_" + name] = run.report()
        S.stop(run)
    run = first_halt(api, "first_activation_retry_then_crash")
    real = run.delivery.queue.retry

    def retry_then_crash(release_id, reason, *, transaction=None):
        real(release_id, reason, transaction=transaction)
        raise RuntimeError("labelled crash after the in-transaction retry")   # LABELLED
    run.delivery.queue.retry = retry_then_crash
    first_command(run, expect="resume_unobservable", note="the in-transaction queue retry is rolled back with it")
    del run.delivery.queue.retry
    first_command(run, note="the same evidence then succeeds")
    out["retry_then_crash"] = run.report()
    S.stop(run)
    return out


def first_units(api):
    """M7 `test_the_binding_is_used_only_for_a_first_activation_and_an_upgrade_is_unchanged` and
    `test_a_new_unbound_plan_is_refused_and_an_old_one_stays_readable_and_cached`."""
    out = {}
    target = {"target_id": "t", "kind": "process", "root": D.RUNTIME_ROOT}
    plan = {"expected_descriptor": None,
            "target_descriptor": {"revision": "a" * 40, "worker_image": api.UNCHANGED, "profile_digest": api.UNCHANGED}}
    binding = {"worker_image": IMAGE_ID, "profile_digest": PROFILE_HEX}
    out["without_binding"] = D.call(api.resolve_descriptor, target, plan, None)
    first = api.resolve_descriptor(target, plan, None, binding)
    out["with_binding"] = {key: first.get(key) for key in ("worker_image", "profile_digest", "predecessor")}
    current = {**first, "worker_image": "sha256:" + "7" * 64, "profile_digest": "8" * 64}
    upgrade = {**plan, "expected_descriptor": api.descriptor_digest(current)}
    out["upgrade_is_unchanged"] = (api.resolve_descriptor(target, upgrade, current, binding)
                                   == api.resolve_descriptor(target, upgrade, current))
    out["upgrade_keeps_the_current_image"] = api.resolve_descriptor(target, upgrade, current, binding)[
        "worker_image"] == current["worker_image"]
    out["upgrade_without_predecessor"] = D.call(api.resolve_descriptor, target, upgrade, None, binding)
    out["unbound"] = [api.first_activation_unbound(plan), api.first_activation_unbound(upgrade)]
    # a NEW unbound plan is refused; an old one stays readable and cached
    run = Case(api, "unbound_registration", plan_overrides={"profile": api.UNCHANGED}, register_plan=False)
    refused = D.call(run.delivery.register, run.system["plan"], D.pin())
    out["new_unbound_plan"] = {**refused, "plan_after": run.delivery.plan(run.system["plan"]["plan_id"])}
    S.register_historical(run)
    out["historical_register"] = D.call(run.delivery.register, run.system["plan"], D.pin())
    view = run.delivery.status()["deliveries"][0]
    out["historical_view"] = {"plan_id": view["plan_id"], "recoveries": view["recoveries"]}
    out["historical_registered_at"] = run.delivery.plan(run.system["plan"]["plan_id"])["registered_at"]
    return out


def first_activation(api):
    return {"units": first_units(api), **first_ladder(api), **first_success(api)}


# ---- 4. resume_consumption_retry ---------------------------------------------------------------------------------
def retry_halt(api, label, *, answer=None):
    """M7 retry `halted`: the producer chain up to the halt, through ticks and the binding command: a historical unbound
    first activation, its binding, the start of the bound descriptor and an owner canary still PENDING when the
    consumption deadline expires (`no_known_good_predecessor`, a bound first activation with nothing to roll back to)."""
    run = first_halt(api, label, canary=True)
    if answer is not None:
        run.canary.answer = dict(answer)
    body, evidence = first_doc(run)
    first_command(run, body, evidence, note="the owner binds the first activation")
    run.first_evidence = evidence
    results = run.until(api.ACTIVE, limit=40)
    run.halt = {"stage": results[-1]["stage"], "reason_code": results[-1]["reason_code"]}
    return run


def retry_doc(run, **overrides):
    """M7 retry `document`."""
    api = run.api
    row = get(run.store, api.BUCKET_PLANS, run.system["plan"]["plan_id"])
    intent = run.intent()
    body = {"schema": api.CONSUMPTION_RETRY_SCHEMA, "kind": api.RECOVERY_CONSUMPTION_RETRY,
            "plan_id": row["plan_id"], "plan_sha256": row["plan_sha256"], "pin_sha256": row["pin"]["sha256"],
            "target_id": row["target_id"], "release_id": run.system["release"]["id"],
            "candidate_revision": run.system["release"]["candidate"]["revision"],
            "candidate_tree": run.system["release"]["candidate"]["tree"],
            "halt": {key: intent[key] for key in ("stage", "previous_stage", "reason_code", "updated_at",
                                                   "stage_deadline")},
            "first_activation_evidence": run.first_evidence, "descriptor_sha256": intent["descriptor_sha256"],
            "observed_instance_id": intent["candidate_instance_id"], "approved_by": "conductor"}
    body.update(overrides)
    return body, "sha256:" + api.digest(body)


def retry_command(run, body=None, evidence=None, **kwargs):
    return document_command(run, "resume_consumption_retry", retry_doc, body, evidence, **kwargs)


@contextmanager
def host_fault(run, name, fault):
    """A labelled host read wrapped to report a missing, stopped, foreign or changed instance (M7 `_missing`, `_stopped`,
    `_foreign_descriptor`, `_changed`, `_unobservable`); the instance attribute is removed again."""
    setattr(run.host, name, fault(getattr(run.host, name)))
    try:
        yield
    finally:
        delattr(run.host, name)


def raising(_real):
    def read(target):
        raise RuntimeError("injected: the host read failed")   # LABELLED
    return read


FAULTS = {
    "raises": ("identity", raising),
    "missing": ("receipt", lambda real: (lambda target: None)),
    "stopped": ("identity", lambda real: (lambda target: {**real(target), "running": False})),
    "foreign_descriptor": ("identity", lambda real: (lambda target: {**real(target), "descriptor_sha256": "0" * 64})),
    "changed": ("receipt", lambda real: (lambda target: {**real(target), "instance_id": OTHER_INSTANCE})),
    "unobservable": ("identity", lambda real: (lambda target: {**real(target), "running": None})),
}


def refuse_host(run, fault, command, expect, **kwargs):
    name, make = FAULTS[fault]
    with host_fault(run, name, make):
        return command(run, expect=expect, note="the live host: " + fault, **kwargs)


def seam_on_host(run, action, injected):
    """LABELLED SEAM: the trusted live-host read runs between phase 1 and the one transaction of phase 2; `action` is a
    write by someone else, performed once inside it."""
    real, done = run.host.identity, []

    def identity(target):
        if not done:
            done.append(1)
            action()
            injected["store"] = D.store_digest(run.store)
        return real(target)
    run.host.identity = identity


def retry_units(api):
    body = {"schema": api.CONSUMPTION_RETRY_SCHEMA, "kind": api.RECOVERY_CONSUMPTION_RETRY, "plan_id": "p",
            "plan_sha256": "a" * 64, "pin_sha256": "b" * 64, "target_id": "t", "release_id": "r",
            "candidate_revision": "c" * 40, "candidate_tree": "d" * 40,
            "halt": {"stage": api.BLOCKED, "previous_stage": api.AWAITING_CONSUMPTION,
                     "reason_code": "no_known_good_predecessor", "updated_at": "t", "stage_deadline": "t"},
            "first_activation_evidence": "sha256:" + "e" * 64, "descriptor_sha256": "f" * 64,
            "observed_instance_id": "instance-1", "approved_by": "conductor"}
    out = {"valid_kind": api.validate_consumption_retry(body)["kind"]}
    for field, value in (("kind", api.RECOVERY_FIRST_ACTIVATION), ("schema", "urn:zeus:other:1"),
                         ("observed_instance_id", ""), ("first_activation_evidence", "sha256:xyz"),
                         ("descriptor_sha256", "nope"),
                         ("halt", {"stage": api.BLOCKED, "previous_stage": api.MERGED,
                                   "reason_code": "no_known_good_predecessor", "updated_at": "t",
                                   "stage_deadline": "t"})):
        out["grammar_" + field] = D.call(api.validate_consumption_retry, {**body, field: value})
    out["grammar_extra_field"] = D.call(api.validate_consumption_retry, {**body, "extra": 1})
    # `test_an_actually_failed_canary_never_qualifies`: the halt shape is judged from the record alone
    intent = {"stage": api.BLOCKED, "reason_code": "no_known_good_predecessor",
              "previous_stage": api.AWAITING_CONSUMPTION, "previous_descriptor": None,
              "descriptor": {"revision": "a" * 40}, "descriptor_sha256": "f" * 64,
              "rollback": {"requested": True, "restored": False, "verified": False, "reason_code": PENDING},
              "canary": {"passed": False, "pending": True, "check_id": api.CANARY_FLEET, "evidence": None,
                         "reason_code": PENDING},
              "recoveries": [{"kind": api.RECOVERY_FIRST_ACTIVATION, "evidence_ref": "sha256:" + "1" * 64}]}
    failed = {**intent, "canary": {"passed": False, "check_id": api.CANARY_FLEET, "evidence": None,
                                   "reason_code": "canary_failed"},
              "rollback": {**intent["rollback"], "reason_code": "canary_failed"}}
    out["retryable"] = {
        "pending_canary": api.consumption_retryable(intent), "failed_canary": api.consumption_retryable(failed),
        "no_binding": api.consumption_retryable({**intent, "recoveries": []}),
        "predecessor": api.consumption_retryable({**intent, "previous_descriptor": {"revision": "b" * 40}}),
        "already_retried": api.consumption_retryable({**intent, "recoveries": [
            *intent["recoveries"], {"kind": api.RECOVERY_CONSUMPTION_RETRY}]})}
    return out


class AdvancingClock:
    """LABELLED. M7 `AdvancingClock`: a production-like clock that advances one microsecond on EVERY read (frozen fixture
    clocks hid PR216 review F1)."""

    def __init__(self, start: str):
        from datetime import datetime
        self.at, self.reads = datetime.fromisoformat(start), 0

    def __call__(self) -> str:
        from datetime import timedelta
        self.reads += 1
        self.at += timedelta(microseconds=1)
        return self.at.isoformat()


def retry_ladder(api):
    out = {}
    run = retry_halt(api, "retry_ladder")
    plan_id = run.system["plan"]["plan_id"]
    sha = run.plan_sha()
    out["halt"] = run.halt
    body, evidence = retry_doc(run)
    run.rung("resume_evidence_invalid", "resume_consumption_retry", plan_id, sha, body, "decision.md")
    run.rung("consumption_retry_evidence_mismatch", "resume_consumption_retry", plan_id, sha, body,
             "sha256:" + "0" * 64)
    run.rung("plan_unregistered", "resume_consumption_retry", "no-such-plan", sha, body, evidence)
    run.rung("resume_plan_mismatch", "resume_consumption_retry", plan_id, "0" * 64, body, evidence)
    other, other_evidence = retry_doc(run, plan_id="another-plan")
    run.rung("consumption_retry_plan_mismatch", "resume_consumption_retry", plan_id, sha, other, other_evidence)
    for fault, code in (("missing", "consumption_retry_instance_missing"), ("stopped", "consumption_retry_instance_stopped"),
                        ("foreign_descriptor", "consumption_retry_host_descriptor_changed"),
                        ("changed", "consumption_retry_instance_changed"),
                        ("raises", "consumption_retry_host_unobservable")):
        refuse_host(run, fault, retry_command, code)
    for field, value, code in (
            ("observed_instance_id", OTHER_INSTANCE, "consumption_retry_instance_mismatch"),
            ("descriptor_sha256", "0" * 64, "consumption_retry_descriptor_mismatch"),
            ("first_activation_evidence", "sha256:" + "0" * 64, "consumption_retry_first_activation_mismatch"),
            ("approved_by", "lead:improvement", "consumption_retry_approver_invalid"),
            ("candidate_tree", "0" * 40, "consumption_retry_candidate_tree_mismatch"),
            ("candidate_revision", "0" * 40, "consumption_retry_candidate_revision_mismatch"),
            ("release_id", "release-other", "consumption_retry_release_id_mismatch"),
            ("target_id", "other-service", "consumption_retry_target_id_mismatch"),
            ("pin_sha256", "0" * 64, "consumption_retry_pin_mismatch")):
        other, other_evidence = retry_doc(run, **{field: value})
        retry_command(run, other, other_evidence, expect=code, note="claim: " + field)
    halt = retry_doc(run)[0]["halt"]
    other, other_evidence = retry_doc(run, halt={**halt, "stage_deadline": FAR})
    retry_command(run, other, other_evidence, expect="consumption_retry_halt_mismatch",
                  note="the old deadline cannot be rewritten")
    other, other_evidence = retry_doc(run, **{api.CONSUMPTION_RETRY_RESTART_FIELD: "sha256:" + "1" * 64})
    retry_command(run, other, other_evidence, expect="consumption_retry_restart_link_mismatch",
                  note="a retry naming a restart that was never recorded")
    author = run.system["release"]["candidate"]["author"]
    real_org = run.delivery.org
    run.delivery.org = ConductorFor(real_org, author)   # LABELLED: the author holds the conductor role
    other, other_evidence = retry_doc(run, approved_by=author)
    retry_command(run, other, other_evidence, expect="consumption_retry_approver_author", note="the author cannot approve")
    run.delivery.org = real_org
    target_id = run.system["plan"]["target_id"]
    for change, code in (({"consumed": True}, "consumption_retry_descriptor_state"),
                         ({"startup_observed": False}, "consumption_retry_descriptor_state"),
                         ({"observed_instance_id": OTHER_INSTANCE}, "consumption_retry_instance_mismatch")):
        with moved(run, api.BUCKET_DESCRIPTORS, target_id, lambda row, change=change: {**row, **change}):
            retry_command(run, expect=code, note="the descriptor row: " + ",".join(sorted(change)))
    record = get(run.store, "releases", run.release_id())
    for change, code in (({"status": "reviewed"}, "consumption_retry_release_reviewed"),
                         ({"status": "rejected"}, "consumption_retry_release_rejected"),
                         ({"status": "active"}, "consumption_retry_release_active")):
        put(run.store, "releases", run.release_id(), {**record, **change})   # LABELLED: the release record moved
        retry_command(run, expect=code, note="the release gate: " + change["status"])
    put(run.store, "releases", run.release_id(), record)
    with moved(run, "releases", run.release_id(), ticket_bound):
        retry_command(run, expect="resume_release_ticket_changed", note="the candidate's ticket binding no longer holds")
    lock = get(run.store, "deployment_locks", "controller")
    put(run.store, "deployment_locks", "controller", {"id": "controller", "lease_until": FAR})
    retry_command(run, expect="resume_controller_running", note="a live controller lease")
    put(run.store, "deployment_locks", "controller", lock)
    put(run.store, "deployment_locks", "controller", {"id": "controller", "lease_until": PAST_LEASE})
    put(run.store, "deployment", "active", {"id": "active", "release_id": run.release_id()})   # LABELLED pointer
    retry_command(run, expect="consumption_retry_release_active", note="an active pointer of this release")
    put(run.store, "deployment", "active", {"id": "active"})
    put(run.store, "deployment_locks", "controller", lock)
    put(run.store, api.BUCKET_INTENTS, "other-plan", {"id": "other-plan", "plan_id": "other-plan", "target_id": target_id,
                                                        "stage": api.MERGED})   # LABELLED: another open delivery
    retry_command(run, expect="consumption_retry_target_in_flight", note="another open delivery of the target")
    put(run.store, api.BUCKET_INTENTS, "other-plan", {"id": "other-plan", "plan_id": "other-plan", "target_id": target_id,
                                                        "stage": api.ACTIVE})
    broken = D.BrokenStore(run.store)
    real_store, run.delivery.store = run.delivery.store, broken
    broken.failing = True
    retry_command(run, expect="resume_unobservable", note="the store is unavailable")
    broken.failing = False
    run.delivery.store = real_store
    out["ladder"] = run.report()
    S.stop(run)
    # a failed transaction writes nothing
    run = retry_halt(api, "retry_failed_transaction")
    real = run.delivery.queue.retry
    body, evidence = retry_doc(run)

    def failing(*args, **kwargs):
        real(*args, **kwargs)
        raise RuntimeError("injected inside the transaction")   # LABELLED
    run.delivery.queue.retry = failing
    retry_command(run, body, evidence, expect="resume_unobservable", note="the queue retry is rolled back with it")
    del run.delivery.queue.retry
    retry_command(run, body, evidence, note="then the same evidence retries once more")
    out["failed_transaction"] = run.report()
    S.stop(run)
    # an actually failed canary never qualifies
    run = retry_halt(api, "retry_failed_canary_halt",
                     answer={"passed": False, "reason_code": "canary_owner_rejected", "evidence": None})
    body, evidence = retry_doc(run)
    retry_command(run, body, evidence, expect="resume_not_applicable", note="an actually failed canary is not retryable")
    out["failed_canary_halt"] = run.report(halt=run.halt, rollback=(run.intent() or {}).get("rollback"))
    S.stop(run)
    # phase two: a write by someone else between the live-host read and the one transaction
    for name, expect, action in (
            ("intent_moved", "resume_intent_changed",
             lambda run: put(run.store, run.api.BUCKET_INTENTS, run.system["plan"]["plan_id"],
                             {**run.intent(), "updated_at": "changed"})),
            ("descriptor_row_moved", "consumption_retry_descriptor_changed",
             lambda run: put(run.store, run.api.BUCKET_DESCRIPTORS, run.system["plan"]["target_id"],
                             {**D.descriptor_of(run.system), "noise": 1})),
            ("release_moved", "consumption_retry_release_changed",
             lambda run: put(run.store, "releases", run.release_id(),
                             {**get(run.store, "releases", run.release_id()), "noise": 1})),
            ("queue_row_moved", "resume_queue_changed",
             lambda run: put(run.store, "release_queue", run.release_id(),
                             {**get(run.store, "release_queue", run.release_id()), "reason": "changed"})),
            ("controller_lease_live", "resume_controller_running",
             lambda run: put(run.store, "deployment_locks", "controller", {"id": "controller", "lease_until": FAR}))):
        run = retry_halt(api, "retry_phase_two_" + name)
        injected = {}
        seam_on_host(run, lambda run=run, action=action: action(run), injected)
        retry_command(run, expect=expect, note="rolled back as a whole: " + name, injected=injected)
        out["phase_two_" + name] = run.report()
        S.stop(run)
    return out



def retry_success(api):
    out = {}
    # ---- the retry consumes the same instance and promotes ---------------------------------------------------------
    run = retry_halt(api, "retry_consumes_the_same_instance")
    plan_id = run.system["plan"]["plan_id"]
    halted_intent = run.intent()
    observed = halted_intent["candidate_instance_id"]
    receipt_before = run.host.receipt(run.system["target"])
    before = {"descriptors": D.canonical_digest(rows(run.store, api.BUCKET_DESCRIPTORS)),
              "release": D.canonical_digest(get(run.store, "releases", run.release_id())),
              "plan": D.canonical_digest(get(run.store, api.BUCKET_PLANS, plan_id))}
    facts_before = len(run.facts.calls)
    body, evidence = retry_doc(run)
    retry_command(run, body, evidence, note="the same instance is retried with a fresh interval")
    intent = run.intent()
    out["halted_receipt_names_the_observed_instance"] = receipt_before["instance_id"] == observed
    out["untouched"] = {"descriptors": before["descriptors"] == D.canonical_digest(rows(run.store, api.BUCKET_DESCRIPTORS)),
                        "release": before["release"] == D.canonical_digest(get(run.store, "releases", run.release_id())),
                        "plan": before["plan"] == D.canonical_digest(get(run.store, api.BUCKET_PLANS, plan_id)),
                        "descriptor_in_intent": intent["descriptor"] == halted_intent["descriptor"],
                        "facts_port_not_asked_again": len(run.facts.calls) == facts_before}
    out["after_retry"] = {key: intent.get(key) for key in ("stage", "previous_stage", "outcome", "reason_code", "attempts",
                                                             "rollback", "canary", "stage_deadline")}
    recovery = intent["recoveries"][-1]
    out["recovery_interval"] = recovery["interval"]
    out["old_deadline_kept"] = recovery["halted"]["stage_deadline"] == halted_intent["stage_deadline"]
    out["status_recovery"] = D.call(lambda: run.delivery.status()["deliveries"][0]["recoveries"][-1])
    run.tick(note="pending once more")
    run.canary.passes()
    results = run.until(api.ACTIVE, limit=10)
    out["reached_active"] = results[-1]["stage"] == api.ACTIVE
    out["descriptor_row"] = D.descriptor_of(run.system)
    out["deployment"] = get(run.store, "deployment", "active")
    out["same_process"] = run.host.receipt(run.system["target"]) == receipt_before
    out["old_halt_is_history"] = run.intent()["recoveries"][-1]["halted"] == recovery["halted"]
    # ---- the same evidence is cached at every later stage; another conflicts -----------------------------------------
    retry_command(run, body, evidence, note="cached at active, nothing written")
    other, other_evidence = retry_doc(run, halt=body["halt"], descriptor_sha256=body["descriptor_sha256"],
                                      observed_instance_id=body["observed_instance_id"], approved_by="conductor",
                                      first_activation_evidence="sha256:" + "0" * 64)
    retry_command(run, other, other_evidence, expect="resume_conflict", note="another document conflicts")
    out["consumes_the_same_instance"] = run.report(observed=observed, canary_asked=sorted(set(run.canary.calls)))
    S.stop(run)
    run = retry_halt(api, "retry_cached_between_stages")
    body, evidence = retry_doc(run)
    retry_command(run, body, evidence, note="the retry")
    retry_command(run, body, evidence, note="cached at awaiting_consumption")
    run.canary.passes()
    run.until(api.ACTIVE, limit=10)
    out["cached_between_stages"] = run.report()
    S.stop(run)
    # ---- a second expiry halts again and the retry is exhausted ---------------------------------------------------
    run = retry_halt(api, "retry_second_expiry")
    body, evidence = retry_doc(run)
    retry_command(run, body, evidence, note="the one retry")
    results = run.until(api.ACTIVE, limit=40)
    out["second_expiry_halt"] = {"stage": results[-1]["stage"], "reason_code": results[-1]["reason_code"]}
    retry_command(run, body, evidence, note="the same evidence is still cached")
    second, second_evidence = retry_doc(run)
    retry_command(run, second, second_evidence, expect="resume_exhausted", note="a second retry is exhausted")
    out["second_expiry"] = run.report()
    S.stop(run)
    # ---- a different instance after the retry halts retry_instance_changed --------------------------------------
    run = retry_halt(api, "retry_instance_changed_after")
    retry_command(run, note="the retry")
    with host_fault(run, "receipt", FAULTS["changed"][1]):
        run.tick(note="a foreign instance reports: a retry consumes only the instance it observed")
    row = D.descriptor_of(run.system)
    out["instance_changed_after"] = run.report(descriptor_consumed=row["consumed"], descriptor_instance=row["instance_id"])
    S.stop(run)
    # ---- a promotion refusal after the retry is unchanged --------------------------------------------------------
    run = retry_halt(api, "retry_promotion_refused")
    retry_command(run, note="the retry")
    run.canary.passes()

    def refuse(*args, **kwargs):
        raise api.ContractError("injected promotion refusal")   # LABELLED
    run.delivery.releases.promote = refuse
    results = run.until(api.ACTIVE, limit=10)
    out["promotion_refused"] = run.report(halt={"stage": results[-1]["stage"], "reason_code": results[-1]["reason_code"]},
                                          descriptor_consumed=D.descriptor_of(run.system)["consumed"])
    S.stop(run)
    # ---- an advancing clock still records exactly the plan window from ONE anchor ----------------------------------
    from datetime import datetime, timedelta
    run = retry_halt(api, "retry_advancing_clock")
    halted_intent = run.intent()
    run.delivery.clock = AdvancingClock(D.clock(api)())   # LABELLED
    anchor = run.delivery.clock()
    out["second_read_drifts_past_the_window"] = (datetime.fromisoformat(run.delivery._deadline(10))
                                                 - datetime.fromisoformat(anchor)) > timedelta(seconds=10)
    retry_command(run, note="the interval is one clock read plus the plan's immutable timeout")
    intent = run.intent()
    record = intent["recoveries"][-1]
    started, deadline = (datetime.fromisoformat(record["interval"][key]) for key in ("started_at", "deadline"))
    out["window_seconds"] = (deadline - started).total_seconds()
    out["one_anchor"] = [intent["stage_entered_at"], intent["stage_deadline"]] == [record["interval"]["started_at"],
                                                                                   record["interval"]["deadline"]]
    out["old_deadline_is_history"] = record["halted"]["stage_deadline"] == halted_intent["stage_deadline"]
    view = run.delivery.status()["deliveries"][0]
    out["status_agrees"] = [view["stage_deadline"] == record["interval"]["deadline"],
                            view["recoveries"][-1]["interval"] == record["interval"]]
    out["advancing_clock"] = run.report(reads=run.delivery.clock.reads)
    S.stop(run)
    # ---- two "concurrent" retries, sequentially on the memory store -------------------------------------------------
    run = retry_halt(api, "retry_two_concurrent")
    body, evidence = retry_doc(run)
    injected = {}
    seam_on_host(run, lambda: retry_command(run, body, evidence, note="the second caller commits first"), injected)
    retry_command(run, body, evidence, note="the first caller finds the record when it reaches the transaction")
    out["two_concurrent"] = run.report(manual_retries=len(get(run.store, "release_queue", run.release_id())["manual_retries"]),
                                       retry_recoveries=len([r for r in run.intent()["recoveries"]
                                                             if r["kind"] == api.RECOVERY_CONSUMPTION_RETRY]))
    S.stop(run)
    return out


def consumption_retry(api):
    return {"units": retry_units(api), **retry_ladder(api), **retry_success(api)}


# ---- 5. resume_consumption_rearm --------------------------------------------------------------------------------
def rearm_doc(run, **overrides):
    """M7 `rearm_document`: the retry document over the SPENT retry's observed instance, made a re-arm one."""
    api = run.api
    intent = run.intent()
    spent = [row for row in intent["recoveries"] if row["kind"] == api.RECOVERY_CONSUMPTION_RETRY][0]
    body, _ = retry_doc(run, observed_instance_id=spent["observed"]["observed_instance_id"])
    body.update({"schema": api.CONSUMPTION_REARM_SCHEMA, "kind": api.RECOVERY_CONSUMPTION_REARM,
                 "retry_evidence": spent["evidence_ref"], "window_seconds": 3600, "authority": AUTHORITY})
    body.update(overrides)
    return body, "sha256:" + api.digest(body)


def rearm_command(run, body=None, evidence=None, **kwargs):
    return document_command(run, "resume_consumption_rearm", rearm_doc, body, evidence, **kwargs)


def exhausted(run):
    """M7 `exhausted`: the one retry, then its window expires AGAIN with the canary still pending."""
    body, evidence = retry_doc(run)
    retry_command(run, body, evidence, note="the one retry")
    results = run.until(run.api.ACTIVE, limit=40)
    run.exhausted_halt = {"stage": results[-1]["stage"], "reason_code": results[-1]["reason_code"]}
    return body, evidence


def rearm_units(api):
    body = {"schema": api.CONSUMPTION_REARM_SCHEMA, "kind": api.RECOVERY_CONSUMPTION_REARM, "plan_id": "own-p",
            "plan_sha256": "a" * 64, "pin_sha256": "b" * 64, "target_id": "t", "release_id": "r",
            "candidate_revision": "c" * 40, "candidate_tree": "7" * 40,
            "halt": {"stage": api.BLOCKED, "previous_stage": api.AWAITING_CONSUMPTION,
                     "reason_code": "no_known_good_predecessor", "updated_at": "2026-09-27T12:24:42+00:00",
                     "stage_deadline": "2026-09-27T12:24:37+00:00"},
            "first_activation_evidence": "sha256:" + "e" * 64, "descriptor_sha256": "d" * 64,
            "observed_instance_id": "i" * 32, "approved_by": "conductor", "retry_evidence": "sha256:" + "f" * 64,
            "window_seconds": 3600, "authority": AUTHORITY}
    out = {"valid_window": api.validate_consumption_rearm(body)["window_seconds"],
           "max_seconds": api.CONSUMPTION_REARM_MAX_SECONDS}
    for field, value in (("schema", api.CONSUMPTION_RETRY_SCHEMA), ("kind", api.RECOVERY_CONSUMPTION_RETRY),
                         ("window_seconds", 0), ("window_seconds", api.CONSUMPTION_REARM_MAX_SECONDS + 1),
                         ("window_seconds", True), ("window_seconds", "3600"), ("window_seconds", 3600.0),
                         ("retry_evidence", "sha256:short"), ("authority", ""), ("observed_instance_id", ""),
                         ("approved_by", "x y"), ("halt", {"stage": api.BLOCKED})):
        out["grammar %s=%r" % (field, value)] = D.call(api.validate_consumption_rearm, {**body, field: value})
    out["grammar_extra_field"] = D.call(api.validate_consumption_rearm, {**body, "extra": 1})
    missing = dict(body)
    del missing["authority"]
    out["grammar_missing_authority"] = D.call(api.validate_consumption_rearm, missing)
    return out


def rearm_ladder(api):
    out = {}
    # no re-arm before the retry is spent and exhausted (`test_no_rearm_before_the_retry_is_spent_and_exhausted`)
    run = retry_halt(api, "rearm_before_the_retry")
    out["rearmable_before"] = api.consumption_rearmable(run.intent())
    retry_body, _ = retry_doc(run)
    fake = {**retry_body, "schema": api.CONSUMPTION_REARM_SCHEMA, "kind": api.RECOVERY_CONSUMPTION_REARM,
            "retry_evidence": OTHER_EVIDENCE, "window_seconds": 3600, "authority": AUTHORITY}
    rearm_command(run, fake, "sha256:" + api.digest(fake), expect="resume_not_applicable",
                  note="the one retry was never made")
    retry_command(run, note="the one retry")
    spent = run.intent()["recoveries"][-1]
    live = {**fake, "retry_evidence": spent["evidence_ref"],
            "observed_instance_id": spent["observed"]["observed_instance_id"]}
    rearm_command(run, live, "sha256:" + api.digest(live), expect="resume_not_applicable",
                  note="the retry is spent but its window has not expired again")
    out["before_the_retry"] = run.report()
    S.stop(run)
    # the refusal ladder over one exhausted delivery
    run = retry_halt(api, "rearm_ladder")
    exhausted(run)
    out["exhausted_halt"] = run.exhausted_halt
    plan_id = run.system["plan"]["plan_id"]
    sha = run.plan_sha()
    body, evidence = rearm_doc(run)
    out["rearmable"] = [api.consumption_rearmable(run.intent()), api.consumption_rearm_exhausted(run.intent())]
    run.rung("resume_evidence_invalid", "resume_consumption_rearm", plan_id, sha, body, "decision.md")
    run.rung("consumption_rearm_evidence_mismatch", "resume_consumption_rearm", plan_id, sha, body, "sha256:" + "0" * 64)
    run.rung("plan_unregistered", "resume_consumption_rearm", "no-such-plan", sha, body, evidence)
    run.rung("resume_plan_mismatch", "resume_consumption_rearm", plan_id, "0" * 64, body, evidence)
    other, other_evidence = rearm_doc(run, plan_id="another-plan")
    run.rung("consumption_rearm_plan_mismatch", "resume_consumption_rearm", plan_id, sha, other, other_evidence)
    retry_command(run, *retry_doc(run), expect="resume_exhausted", note="the one retry itself stays exhausted")
    for overrides, code in (
            ({"retry_evidence": "sha256:" + "0" * 64}, "consumption_rearm_retry_mismatch"),
            ({"observed_instance_id": OTHER_INSTANCE}, "consumption_rearm_retry_mismatch"),
            ({"first_activation_evidence": "sha256:" + "0" * 64}, "consumption_rearm_first_activation_mismatch"),
            ({"descriptor_sha256": "0" * 64}, "consumption_rearm_descriptor_mismatch"),
            ({"approved_by": "worker:improvement-1"}, "consumption_rearm_approver_invalid"),
            ({"generation_restart_evidence": "sha256:" + "0" * 64}, "consumption_rearm_restart_link_mismatch"),
            ({"pin_sha256": "0" * 64}, "consumption_rearm_pin_mismatch"),
            ({"release_id": "release-other"}, "consumption_rearm_release_id_mismatch"),
            ({"target_id": "other-service"}, "consumption_rearm_target_id_mismatch"),
            ({"candidate_revision": "0" * 40}, "consumption_rearm_candidate_revision_mismatch"),
            ({"candidate_tree": "0" * 64}, "consumption_rearm_candidate_tree_mismatch")):
        other, other_evidence = rearm_doc(run, **overrides)
        rearm_command(run, other, other_evidence, expect=code, note="claim: " + ",".join(sorted(overrides)))
    halt = rearm_doc(run)[0]["halt"]
    other, other_evidence = rearm_doc(run, halt={**halt, "stage_deadline": "2099-01-01T00:00:00+00:00"})
    rearm_command(run, other, other_evidence, expect="consumption_rearm_halt_mismatch",
                  note="the expired halt cannot be rewritten")
    author = run.system["release"]["candidate"]["author"]
    real_org = run.delivery.org
    run.delivery.org = ConductorFor(real_org, author)   # LABELLED: the author holds the conductor role
    other, other_evidence = rearm_doc(run, approved_by=author)
    rearm_command(run, other, other_evidence, expect="consumption_rearm_approver_author", note="the author cannot approve")
    run.delivery.org = real_org
    target_id = run.system["plan"]["target_id"]
    for change, code in (({"consumed": True}, "consumption_rearm_descriptor_state"),
                         ({"startup_observed": False}, "consumption_rearm_descriptor_state"),
                         ({"observed_instance_id": OTHER_INSTANCE}, "consumption_rearm_instance_mismatch")):
        with moved(run, api.BUCKET_DESCRIPTORS, target_id, lambda row, change=change: {**row, **change}):
            rearm_command(run, expect=code, note="the descriptor row: " + ",".join(sorted(change)))
    for fault, code in (("missing", "consumption_retry_instance_missing"), ("changed", "consumption_retry_instance_changed"),
                        ("foreign_descriptor", "consumption_retry_host_descriptor_changed")):
        refuse_host(run, fault, rearm_command, code)
    S.stop(run)   # LABELLED: the host restarted, nothing runs (last: the host is stopped)
    rearm_command(run, expect="consumption_retry_instance_stopped", note="the live host: stopped")
    out["ladder"] = run.report()
    return out


def rearm_success(api):
    out = {}
    # ---- one re-arm opens the explicit window and consumes the same instance --------------------------------------
    from datetime import datetime
    run = retry_halt(api, "rearm_consumes_the_same_instance")
    retry_body, retry_evidence = exhausted(run)
    halted_intent = run.intent()
    spent = halted_intent["recoveries"][-1]
    instance = spent["observed"]["observed_instance_id"]
    out["shapes_before"] = {"rearmable": api.consumption_rearmable(halted_intent),
                            "rearm_exhausted": api.consumption_rearm_exhausted(halted_intent)}
    retry_command(run, expect="resume_exhausted", note="the one retry stays exhausted")
    before = {"descriptors": D.canonical_digest(rows(run.store, api.BUCKET_DESCRIPTORS)),
              "release": D.canonical_digest(get(run.store, "releases", run.release_id()))}
    body, evidence = rearm_doc(run)
    rearm_command(run, body, evidence, note="the ONE re-arm: the explicit window from one anchor")
    intent = run.intent()
    record = intent["recoveries"][-1]
    start, end = (datetime.fromisoformat(record["interval"][key]) for key in ("started_at", "deadline"))
    out["kinds"] = [row["kind"] for row in intent["recoveries"]]
    out["window_seconds"] = (end - start).total_seconds()
    out["stage_deadline_is_the_window"] = intent["stage_deadline"] == record["interval"]["deadline"]
    out["record"] = {key: record.get(key) for key in ("window_seconds", "authority", "retry_evidence", "approved_by")}
    out["record_instance_is_the_spent_one"] = record["observed"]["observed_instance_id"] == instance
    out["earlier_recoveries_kept"] = intent["recoveries"][:2] == halted_intent["recoveries"]
    out["halted_kept"] = {key: record["halted"][key] == halted_intent[key] for key in (
        "stage", "previous_stage", "reason_code", "updated_at", "stage_deadline", "rollback", "canary")}
    out["untouched"] = {"descriptors": before["descriptors"] == D.canonical_digest(rows(run.store, api.BUCKET_DESCRIPTORS)),
                        "release": before["release"] == D.canonical_digest(get(run.store, "releases", run.release_id()))}
    out["status_recovery"] = D.call(lambda: run.delivery.status()["deliveries"][0]["recoveries"][-1])
    run.wait(1200)   # well inside the window the pending canary only waits
    run.tick(note="inside the explicit window: the plan's 10 s no longer caps it")
    asked = len(run.canary.calls)
    run.canary.passes()
    results = run.until(api.ACTIVE, limit=10)
    out["reached_active"] = results[-1]["stage"] == api.ACTIVE
    row = D.descriptor_of(run.system)
    out["descriptor_consumed"] = [row["consumed"], row["instance_id"] == instance]
    out["canary_asked_after"] = sorted(set(run.canary.calls[asked:])) == [instance]
    rearm_command(run, body, evidence, note="cached at active, nothing written")
    out["consumes_the_same_instance"] = run.report(descriptor_row=row)
    S.stop(run)
    # ---- one re-arm per delivery: another evidence conflicts -------------------------------------------------------
    run = retry_halt(api, "rearm_one_per_delivery")
    exhausted(run)
    body, evidence = rearm_doc(run)
    rearm_command(run, body, evidence, note="the re-arm")
    other = {**body, "authority": "sha256:" + "b" * 64}
    rearm_command(run, other, "sha256:" + api.digest(other), expect="resume_conflict", note="another evidence conflicts")
    out["one_per_delivery"] = run.report()
    S.stop(run)
    # ---- the window expires exactly at its own deadline and is then final ------------------------------------------
    run = retry_halt(api, "rearm_window_expires")
    exhausted(run)
    body, evidence = rearm_doc(run)
    rearm_command(run, body, evidence, note="the re-arm")
    deadline = datetime.fromisoformat(run.intent()["stage_deadline"])
    now = api.now()
    run.wait((deadline - now).total_seconds() - 2)
    result = run.tick(advance=0, note="one second before the deadline: still waiting")
    out["one_second_before"] = [result["stage"], result["outcome"]]
    run.wait(2)
    result = run.tick(advance=0, note="at the deadline: the pending canary is a failure again")
    out["at_the_deadline"] = [result["stage"], result["reason_code"]]
    final = run.intent()
    out["final_shapes"] = {"rearm_exhausted": api.consumption_rearm_exhausted(final),
                           "rearmable": api.consumption_rearmable(final)}
    rearm_command(run, body, evidence, note="the same evidence is still cached")
    other, other_evidence = rearm_doc(run, authority="sha256:" + "b" * 64)
    rearm_command(run, other, other_evidence, expect="resume_exhausted", note="a further re-arm is final")
    retry_command(run, *retry_doc(run), expect="resume_exhausted", note="the retry stays exhausted")
    kinds = [row["kind"] for row in final["recoveries"]]
    out["kind_counts"] = {"rearm": kinds.count(api.RECOVERY_CONSUMPTION_REARM),
                          "retry": kinds.count(api.RECOVERY_CONSUMPTION_RETRY)}
    out["window_expires"] = run.report()
    S.stop(run)
    # ---- a different instance after the re-arm halts retry_instance_changed ----------------------------------------
    run = retry_halt(api, "rearm_instance_changed_after")
    exhausted(run)
    rearm_command(run, note="the re-arm")
    with host_fault(run, "receipt", FAULTS["changed"][1]):
        run.tick(note="a foreign instance reports")
    row = D.descriptor_of(run.system)
    out["instance_changed_after"] = run.report(descriptor_consumed=row["consumed"], descriptor_instance=row["instance_id"])
    S.stop(run)
    return out


def consumption_rearm(api):
    return {"units": rearm_units(api), **rearm_ladder(api), **rearm_success(api)}


# ---- 6. resume_generation_restart -------------------------------------------------------------------------------
def restart_doc(run, **overrides):
    """M7 `restart_document`."""
    api = run.api
    row = get(run.store, api.BUCKET_PLANS, run.system["plan"]["plan_id"])
    intent = run.intent()
    body = {"schema": api.GENERATION_RESTART_SCHEMA, "kind": api.RECOVERY_GENERATION_RESTART,
            "plan_id": row["plan_id"], "plan_sha256": row["plan_sha256"], "pin_sha256": row["pin"]["sha256"],
            "target_id": row["target_id"], "release_id": run.system["release"]["id"],
            "candidate_revision": run.system["release"]["candidate"]["revision"],
            "candidate_tree": run.system["release"]["candidate"]["tree"],
            "halt": {key: intent[key] for key in ("stage", "previous_stage", "reason_code", "updated_at",
                                                   "stage_deadline")},
            "first_activation_evidence": run.first_evidence, "descriptor_sha256": intent["descriptor_sha256"],
            "stopped_instance_id": intent["candidate_instance_id"], "reason": "host_restarted",
            "approved_by": "conductor"}
    body.update(overrides)
    return body, "sha256:" + api.digest(body)


def restart_command(run, body=None, evidence=None, *, expect=None, note=None, plan_sha=None, via=None, injected=None):
    """M7 `restart`: the start is bounded by `startup_seconds` (never a real wait here: 0) and `poll_seconds`."""
    if body is None:
        body, evidence = restart_doc(run)
    plan_id = run.system["plan"]["plan_id"]
    return run.command("resume_generation_restart", plan_id, plan_sha or run.plan_sha(plan_id), body,
                       evidence or "sha256:" + run.api.digest(body), expect=expect, note=note, via=via, injected=injected,
                       startup_seconds=STARTUP_SECONDS, poll_seconds=0.0)


def rebooted(run):
    """M7 `rebooted`: the host restart. The generation's process is gone; its own receipt and launch record remain."""
    before = run.host.receipt(run.system["target"])
    D.stop_target(run.system)
    identity = run.host.identity(run.system["target"])
    run.extra["rebooted"] = {"was_running": identity["running"] is False and identity["instance_id"] == before["instance_id"],
                             "receipt_kept": run.host.receipt(run.system["target"]) == before}
    return before


def restart_units(api):
    body = {"schema": api.GENERATION_RESTART_SCHEMA, "kind": api.RECOVERY_GENERATION_RESTART, "plan_id": "own-p",
            "plan_sha256": "a" * 64, "pin_sha256": "b" * 64, "target_id": "t", "release_id": "r",
            "candidate_revision": "c" * 40, "candidate_tree": "7" * 40,
            "halt": {"stage": api.BLOCKED, "previous_stage": api.AWAITING_CONSUMPTION,
                     "reason_code": "no_known_good_predecessor", "updated_at": "2026-09-22T00:00:00+00:00",
                     "stage_deadline": "2026-09-22T00:00:00+00:00"},
            "first_activation_evidence": "sha256:" + "e" * 64, "descriptor_sha256": "d" * 64,
            "stopped_instance_id": "i" * 32, "reason": "host_restarted", "approved_by": "conductor"}
    out = {"valid_reason": api.validate_generation_restart(body)["reason"],
           "reasons": sorted(api.GENERATION_RESTART_REASONS)}
    for field, value in (("schema", "urn:zeus:host-delivery-generation-restart:2"),
                         ("kind", api.RECOVERY_CONSUMPTION_RETRY), ("reason", "operator_wish"),
                         ("stopped_instance_id", ""), ("approved_by", "x y"),
                         ("first_activation_evidence", "sha256:short"), ("halt", {"stage": api.BLOCKED})):
        out["grammar_" + field] = D.call(api.validate_generation_restart, {**body, field: value})
    out["grammar_extra_field"] = D.call(api.validate_generation_restart, {**body, "extra": 1})
    return out


def restart_ladder(api):
    out = {}
    run = retry_halt(api, "restart_ladder")
    plan_id = run.system["plan"]["plan_id"]
    sha = run.plan_sha()
    body, evidence = restart_doc(run)
    restart_command(run, expect="generation_restart_instance_running", note="a running generation is the retry case")
    rebooted(run)
    out["restartable"] = api.generation_restartable(run.intent())
    retry_command(run, expect="consumption_retry_instance_stopped", note="the old retry has nothing live to consume")
    call = dict(startup_seconds=STARTUP_SECONDS, poll_seconds=0.0)
    run.rung("resume_evidence_invalid", "resume_generation_restart", plan_id, sha, body, "decision.md", **call)
    run.rung("generation_restart_evidence_mismatch", "resume_generation_restart", plan_id, sha, body,
             "sha256:" + "0" * 64, **call)
    run.rung("plan_unregistered", "resume_generation_restart", "no-such-plan", sha, body, evidence, **call)
    run.rung("resume_plan_mismatch", "resume_generation_restart", plan_id, "0" * 64, body, evidence, **call)
    other, other_evidence = restart_doc(run, plan_id="another-plan")
    run.rung("generation_restart_plan_mismatch", "resume_generation_restart", plan_id, sha, other, other_evidence, **call)
    for fault, code in (("foreign_descriptor", "generation_restart_host_descriptor_changed"),
                        ("unobservable", "generation_restart_host_unobservable"),
                        ("raises", "generation_restart_host_unobservable")):
        refuse_host(run, fault, restart_command, code)
    for overrides, code in (
            ({"stopped_instance_id": OTHER_INSTANCE}, "generation_restart_instance_mismatch"),
            ({"approved_by": "worker:implementation"}, "generation_restart_approver_invalid"),
            ({"first_activation_evidence": "sha256:" + "0" * 64}, "generation_restart_first_activation_mismatch"),
            ({"pin_sha256": "0" * 64}, "generation_restart_pin_mismatch"),
            ({"release_id": "release-other"}, "generation_restart_release_id_mismatch"),
            ({"target_id": "other-service"}, "generation_restart_target_id_mismatch"),
            ({"candidate_revision": "0" * 40}, "generation_restart_candidate_revision_mismatch"),
            ({"candidate_tree": "0" * 64}, "generation_restart_candidate_tree_mismatch"),
            ({"descriptor_sha256": "0" * 64}, "generation_restart_descriptor_mismatch")):
        other, other_evidence = restart_doc(run, **overrides)
        restart_command(run, other, other_evidence, expect=code, note="claim: " + ",".join(sorted(overrides)))
    halt = restart_doc(run)[0]["halt"]
    other, other_evidence = restart_doc(run, halt={**halt, "stage_deadline": "2099-01-01T00:00:00+00:00"})
    restart_command(run, other, other_evidence, expect="generation_restart_halt_mismatch",
                    note="the old deadline cannot be rewritten")
    author = run.system["release"]["candidate"]["author"]
    real_org = run.delivery.org
    run.delivery.org = ConductorFor(real_org, author)   # LABELLED: the author holds the conductor role
    other, other_evidence = restart_doc(run, approved_by=author)
    restart_command(run, other, other_evidence, expect="generation_restart_approver_author", note="the author cannot approve")
    run.delivery.org = real_org
    target_id = run.system["plan"]["target_id"]
    for change, code in (({"consumed": True}, "generation_restart_descriptor_state"),
                         ({"startup_observed": False}, "generation_restart_descriptor_state"),
                         ({"observed_instance_id": OTHER_INSTANCE}, "generation_restart_instance_mismatch")):
        with moved(run, api.BUCKET_DESCRIPTORS, target_id, lambda row, change=change: {**row, **change}):
            restart_command(run, expect=code, note="the descriptor row: " + ",".join(sorted(change)))
    lock = get(run.store, "deployment_locks", "controller")
    put(run.store, "deployment_locks", "controller", {"id": "controller", "lease_until": FAR})
    restart_command(run, expect="resume_controller_running", note="a live controller lease")
    put(run.store, "deployment_locks", "controller", lock)
    record = get(run.store, "releases", run.release_id())
    for change, code in (({"status": "reviewed"}, "consumption_retry_release_reviewed"),
                         ({"status": "active"}, "consumption_retry_release_active")):
        put(run.store, "releases", run.release_id(), {**record, **change})   # LABELLED: the release record moved
        restart_command(run, expect=code, note="the release gate: " + change["status"])
    put(run.store, "releases", run.release_id(), record)
    with moved(run, "releases", run.release_id(), ticket_bound):
        restart_command(run, expect="resume_queue_refused",
                        note="the queue re-arm refuses the candidate's ticket binding inside the transaction")
    put(run.store, api.BUCKET_INTENTS, "other-plan", {"id": "other-plan", "plan_id": "other-plan", "target_id": target_id,
                                                        "stage": api.MERGED})   # LABELLED: another open delivery
    restart_command(run, expect="consumption_retry_target_in_flight", note="another open delivery of the target")
    put(run.store, api.BUCKET_INTENTS, "other-plan", {"id": "other-plan", "plan_id": "other-plan", "target_id": target_id,
                                                        "stage": api.ACTIVE})
    broken = D.BrokenStore(run.store)
    real_store, run.delivery.store = run.delivery.store, broken
    broken.failing = True
    restart_command(run, expect="resume_unobservable", note="the store is unavailable")
    broken.failing = False
    run.delivery.store = real_store
    out["ladder"] = run.report()
    S.stop(run)
    # phase two: a write by someone else between the trusted host read and the transaction that records the request
    for name, expect, action in (
            ("intent_moved", "resume_intent_changed",
             lambda run: put(run.store, run.api.BUCKET_INTENTS, run.system["plan"]["plan_id"],
                             {**run.intent(), "updated_at": "changed"})),
            ("descriptor_row_moved", "generation_restart_descriptor_changed",
             lambda run: put(run.store, run.api.BUCKET_DESCRIPTORS, run.system["plan"]["target_id"],
                             {**D.descriptor_of(run.system), "noise": 1})),
            ("release_moved", "generation_restart_release_changed",
             lambda run: put(run.store, "releases", run.release_id(),
                             {**get(run.store, "releases", run.release_id()), "noise": 1})),
            ("queue_row_moved", "resume_queue_changed",
             lambda run: put(run.store, "release_queue", run.release_id(),
                             {**get(run.store, "release_queue", run.release_id()), "reason": "changed"})),
            ("controller_lease_live", "resume_controller_running",
             lambda run: put(run.store, "deployment_locks", "controller", {"id": "controller", "lease_until": FAR}))):
        run = retry_halt(api, "restart_phase_two_" + name)
        rebooted(run)
        injected = {}
        seam_on_host(run, lambda run=run, action=action: action(run), injected)
        restart_command(run, expect=expect, note="rolled back as a whole: " + name, injected=injected)
        out["phase_two_" + name] = run.report()
        S.stop(run)
    # the one retry must name the restart and consume its new instance
    run = retry_halt(api, "restart_link_rules")
    rebooted(run)
    fake_body, fake_evidence = retry_doc(run, **{api.CONSUMPTION_RETRY_RESTART_FIELD: "sha256:" + "1" * 64})
    retry_command(run, fake_body, fake_evidence, expect="consumption_retry_restart_link_mismatch",
                  note="before any restart, a retry naming one is refused")
    body, evidence = restart_doc(run)
    restart_command(run, body, evidence, note="the restart")
    new = run.intent()["recoveries"][-1]["started"]["instance_id"]
    unlinked, unlinked_evidence = retry_doc(run, observed_instance_id=new)
    retry_command(run, unlinked, unlinked_evidence, expect="consumption_retry_restart_link_mismatch",
                  note="the retry does not name the restart")
    wrong, wrong_evidence = retry_doc(run, observed_instance_id=new,
                                      **{api.CONSUMPTION_RETRY_RESTART_FIELD: "sha256:" + "2" * 64})
    retry_command(run, wrong, wrong_evidence, expect="consumption_retry_restart_link_mismatch",
                  note="the retry names another restart")
    stale, stale_evidence = retry_doc(run, **{api.CONSUMPTION_RETRY_RESTART_FIELD: evidence})
    retry_command(run, stale, stale_evidence, expect="consumption_retry_instance_mismatch",
                  note="the retry names the restart but still the stopped instance")
    out["link_rules"] = run.report()
    S.stop(run)
    return out


def restart_success(api):
    out = {}
    # ---- a stopped generation restarts once and the one retry consumes it -------------------------------------------
    run = retry_halt(api, "restart_then_retry")
    plan_id = run.system["plan"]["plan_id"]
    halted_intent = run.intent()
    old = halted_intent["candidate_instance_id"]
    old_receipt = rebooted(run)
    before = {"descriptors": D.canonical_digest(rows(run.store, api.BUCKET_DESCRIPTORS)),
              "plan": D.canonical_digest(get(run.store, api.BUCKET_PLANS, plan_id)),
              "release": D.canonical_digest(get(run.store, "releases", run.release_id()))}
    queue_before = run.owner_queue()["manual_retries"]
    body, evidence = restart_doc(run)
    restart_command(run, body, evidence, note="the ONE start under the release fence")
    intent = run.intent()
    record = intent["recoveries"][-1]
    new = record["started"]["instance_id"]
    out["halt_kept"] = {key: intent[key] == halted_intent[key] for key in (
        "stage", "previous_stage", "reason_code", "outcome", "updated_at", "stage_deadline", "stage_entered_at",
        "rollback", "canary", "candidate_instance_id", "descriptor")}
    out["kinds"] = [row["kind"] for row in intent["recoveries"]]
    out["record"] = {"state": record["state"], "new_is_another_instance": new not in (None, old),
                     "stopped": record["stopped"]["instance_id"] == old,
                     "halted_deadline_kept": record["halted"]["stage_deadline"] == halted_intent["stage_deadline"],
                     "launch_started": record["launch"]["started"],
                     "launch_is_new": record["launch"]["record"] != record["stopped"]["observed_launch"]}
    fresh = run.host.receipt(run.system["target"])
    out["fresh_receipt"] = {"names_the_new_generation": fresh["instance_id"] == new != old_receipt["instance_id"],
                            "same_descriptor": fresh["descriptor_sha256"] == old_receipt["descriptor_sha256"]
                            == intent["descriptor_sha256"]}
    out["untouched"] = {"descriptors": before["descriptors"] == D.canonical_digest(rows(run.store, api.BUCKET_DESCRIPTORS)),
                        "plan": before["plan"] == D.canonical_digest(get(run.store, api.BUCKET_PLANS, plan_id)),
                        "release": before["release"] == D.canonical_digest(get(run.store, "releases", run.release_id()))}
    out["queue_after_restart"] = {"manual_retries_added": run.owner_queue()["manual_retries"] - queue_before,
                                  "status": run.owner_queue()["status"]}
    out["restartable_after"] = api.generation_restartable(intent)
    out["status_recovery"] = D.call(lambda: run.delivery.status()["deliveries"][0]["recoveries"][-1])
    retry_body, retry_evidence = retry_doc(run, observed_instance_id=new,
                                           **{api.CONSUMPTION_RETRY_RESTART_FIELD: evidence})
    retry_command(run, retry_body, retry_evidence, note="the ONE retry, explicitly linked to the restart")
    intent = run.intent()
    out["kinds_after_retry"] = [row["kind"] for row in intent["recoveries"]]
    out["candidate_is_the_new_generation"] = intent["candidate_instance_id"] == new
    out["retry_observed_names_the_restart"] = intent["recoveries"][-1]["observed"][
        api.CONSUMPTION_RETRY_RESTART_FIELD] == evidence
    out["status_retry_recovery"] = D.call(lambda: run.delivery.status()["deliveries"][0]["recoveries"][-1])
    asked_before = len(run.canary.calls)
    run.canary.passes()
    results = run.until(api.ACTIVE, limit=10)
    out["reached_active"] = results[-1]["stage"] == api.ACTIVE
    row = D.descriptor_of(run.system)
    out["descriptor_consumed"] = [row["consumed"], row["instance_id"] == new]
    out["canary_asked_after"] = sorted(set(run.canary.calls[asked_before:])) == [new]
    out["restart_then_retry"] = run.report(descriptor_row=row)
    S.stop(run)
    # ---- the replay is cached and another evidence conflicts ---------------------------------------------------------
    run = retry_halt(api, "restart_cached_and_conflict")
    rebooted(run)
    body, evidence = restart_doc(run)
    restart_command(run, body, evidence, note="the restart")
    launch = run.intent()["recoveries"][-1]["launch"]
    restart_command(run, body, evidence, note="the replay is cached and starts nothing")
    out["no_second_start"] = run.intent()["recoveries"][-1]["launch"] == launch
    other, other_evidence = restart_doc(run, approved_by="conductor", reason="generation_exited")
    restart_command(run, other, other_evidence, expect="resume_conflict", note="another evidence conflicts")
    out["cached_and_conflict"] = run.report()
    S.stop(run)
    # ---- a lost start response is recognized and never started twice -----------------------------------------------
    run = retry_halt(api, "restart_lost_start_response")
    rebooted(run)
    out["starts_before_the_restart"] = run.host.calls.count("start")
    run.host.start_error = RuntimeError("response lost after the start (injected)")   # LABELLED: raised AFTER the effect
    body, evidence = restart_doc(run)
    restart_command(run, body, evidence, note="the start happens, its response is lost")
    out["after_the_lost_response"] = {"state": run.intent()["recoveries"][-1]["state"],
                                      "starts": run.host.calls.count("start")}
    run.host.start_error = None
    restart_command(run, body, evidence, note="the same evidence recognizes the newer launch")
    record = run.intent()["recoveries"][-1]
    out["after_the_replay"] = {"state": record["state"], "starts": run.host.calls.count("start"),
                               "launch_recovered": record["launch"]["recovered"], "launch_started": record["launch"]["started"]}
    out["lost_start_response"] = run.report()
    S.stop(run)
    # ---- an unconfirmed receipt keeps the launch recorded and refuses for the owner -----------------------------------
    run = retry_halt(api, "restart_launch_unconfirmed")
    rebooted(run)
    run.host.fault = "no_receipt"   # LABELLED: the new instance never reports
    body, evidence = restart_doc(run)
    refused = restart_command(run, body, evidence,
                              note="launched, but no fresh receipt within the bound: refused, the launch stays recorded")
    out["unconfirmed"] = {"refused": refused.get("reason_code"), "state": run.intent()["recoveries"][-1]["state"],
                          "starts": run.host.calls.count("start")}
    out["restart_launch_unconfirmed"] = run.report(queue=run.owner_queue())
    S.stop(run)
    # ---- a held fence keeps the recorded request and the same evidence completes it ------------------------------------
    run = retry_halt(api, "restart_held_fence")
    rebooted(run)
    real_claim, held = run.delivery.queue.claim, {"once": True}

    def claim(*args, **kwargs):
        if held["once"]:
            held["once"] = False
            return None   # LABELLED: another controller holds the host lease
        return real_claim(*args, **kwargs)
    run.delivery.queue.claim = claim
    body, evidence = restart_doc(run)
    restart_command(run, body, evidence, expect=None, note="the fence is held: the request stays recorded, nothing starts")
    out["fence_held"] = {"state": run.intent()["recoveries"][-1]["state"],
                         "running": run.host.identity(run.system["target"])["running"], "starts": run.host.calls.count("start")}
    restart_command(run, body, evidence, note="the same evidence completes it under the fence")
    del run.delivery.queue.claim
    out["fence_released"] = {"state": run.intent()["recoveries"][-1]["state"], "starts": run.host.calls.count("start")}
    out["held_fence"] = run.report()
    S.stop(run)
    # ---- one restart per delivery, even after the retry halts again ----------------------------------------------------
    run = retry_halt(api, "restart_one_per_delivery")
    rebooted(run)
    body, evidence = restart_doc(run)
    restart_command(run, body, evidence, note="the restart")
    new = run.intent()["recoveries"][-1]["started"]["instance_id"]
    retry_body, retry_evidence = retry_doc(run, observed_instance_id=new, **{api.CONSUMPTION_RETRY_RESTART_FIELD: evidence})
    retry_command(run, retry_body, retry_evidence, note="the one retry")
    run.wait(20)
    results = run.until(api.ACTIVE, limit=20)
    out["halts_again"] = {"stage": results[-1]["stage"], "reason_code": results[-1]["reason_code"]}
    S.stop(run)
    again, again_evidence = restart_doc(run)
    restart_command(run, again, again_evidence, note="a second restart is refused (any of resume_conflict, "
                    "resume_not_applicable, generation_restart_instance_mismatch)")
    out["one_per_delivery"] = run.report()
    S.stop(run)
    # ---- two "concurrent" restarts, sequentially on the memory store ---------------------------------------------------
    run = retry_halt(api, "restart_two_concurrent")
    rebooted(run)
    body, evidence = restart_doc(run)
    injected = {}
    seam_on_host(run, lambda: restart_command(run, body, evidence, note="the second caller restarts the generation"),
                 injected)
    restart_command(run, body, evidence, note="the first caller then finds the generation running")
    restarts = [row for row in run.intent()["recoveries"] if row["kind"] == api.RECOVERY_GENERATION_RESTART]
    out["two_concurrent"] = run.report(starts=run.host.calls.count("start"), restart_records=len(restarts),
                                       restart_state=restarts[0]["state"])
    S.stop(run)
    return out


def generation_restart(api):
    return {"units": restart_units(api), **restart_ladder(api), **restart_success(api)}


UNREACHABLE = {
    "first_activation_candidate_mismatch": "the release gate and the document's own revision/tree checks refuse first: a "
                                           "gated record's candidate IS the plan's",
    "consumption_retry_candidate_mismatch": "as above, for the consumption retry",
    "consumption_rearm_candidate_mismatch": "as above, for the consumption re-arm",
    "generation_restart_candidate_mismatch": "as above, for the generation restart",
    "github_port_unavailable": "raised inside `_stale_now`'s own try and re-raised as withdraw_unobservable",
    "first_activation_approver_unavailable": "with no organization the release gate cannot derive the author's lead and "
                                             "refuses first (release_reviews_incomplete)",
    "resume_exhausted (resume)": "needs a second release_not_verified halt at merged after a recorded recovery; only the "
                                 "crafted legacy write makes that shape and the characterization never re-crafts an intent",
}


def refusals(value, seen):
    """Every named refusal in a result tree (a `D.call` outcome), by code."""
    if isinstance(value, dict):
        if "refused" in value and "reason_code" in value:
            seen[value["reason_code"]] = seen.get(value["reason_code"], 0) + 1
        for child in value.values():
            refusals(child, seen)
    elif isinstance(value, list):
        for child in value:
            refusals(child, seen)


def coverage(groups):
    seen = {}
    refusals(groups, seen)
    return {"refusals_observed": dict(sorted(seen.items())), "unreachable": UNREACHABLE}


def run(api) -> dict:
    groups = {"withdraw": withdraw(api), "resume": resume(api), "first_activation": first_activation(api),
            "consumption_retry": consumption_retry(api), "consumption_rearm": consumption_rearm(api),
            "generation_restart": generation_restart(api)}
    groups["coverage"] = coverage(groups)
    return groups
