"""Shared S8 scenario steps (`research.scheduling`): M7 `application/scheduling.py` (`schedule_research`, `schedule_audits`), characterized
BEFORE the module moves (DESIGN-s8 §19 V23: R-sc1..R-sc3). The golden is placement-neutral: it observes SOURCE behaviour only; the move is a
later commit of the same pilot.

Each case is labelled with the M7 test it mirrors (`m7_test`), or `none` (a branch of the module no M7 test names, labelled where it is made).
M7's `tests/test_scheduling.py` (3 tests) drives `schedule_audits` over the whole audit-repair and research-audit fixtures (a service, an
executor, a correction); the golden is APPLICATION-level instead: the partition, task and `schedule` rows those tests obtain are PLANTED, and
their three interactions are cases (`m7_*` below). No M7 test is left out; the repair fixtures themselves belong to other families.

Layer: harness (never shipped)

This module never imports `codex_harness`: everything from the product arrives through `api`, the object a reference (later a target) driver
builds. LABELLED doubles and plantings (nothing here is an actual Codex, Git, Docker, model or production verification):
- the store is a `MemoryStore`; the `research_control`, `research_discoveries`, `research_backlog`, `research_partitions`, `research_audits`,
  `research_approvals` (with their `research_reviews` and `research_receipts`), `tasks`, `schedule`, `deployment` and `releases` rows are
  PLANTED in the shape their owners write; an approval's `binding` is computed by the gate's own `binding` over the planted store;
- `service` is a `SimpleNamespace(store=..., org=...)`: the two attributes M7 reads; the organization is the packaged one;
- `api.ports(store, org)` are the keywords the side's call takes beyond M7's (none in the reference; the target's `outbox` and
  `reconcile_audits`); the reference reaches the `reconcile_audits` of M7's `Releases` through the module itself;
- the clock and the ids are the harness's, advanced one millisecond after every step; `now` is passed (the module's `time.time()` default is
  not exercised: it is the real clock).
The whole-store digest (16 hex) is recorded before and after every call with a `wrote` flag, and the `schedule` keys the call added.
"""

from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

REV = "rev-0001"
RELEASE = "release-0001"
SOURCE_URL = "https://example.invalid/source"
COMMIT = "c" * 40
NOW = 1_800_000_000.0  # slot = int(NOW // (research_interval_hours * 3600)): the harness fixes it, the module's own time.time() is unused
SLOT_SECONDS = 6 * 3600


def canonical_digest(value) -> str:
    text = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def store_digest(store) -> str:
    with store.transaction() as tx:
        return canonical_digest([[r["bucket"], r["id"], canonical_digest(r["body"])] for r in tx.records()])[:16]


def get(store, bucket, key):
    with store.transaction() as tx:
        return tx.get(bucket, key)


def scan(store, bucket):
    with store.transaction() as tx:
        return tx.scan(bucket)


def put(store, bucket, key, body):
    with store.transaction() as tx:
        tx.put(bucket, key, body)


def outcome(fn, *args, **kwargs):
    try:
        value = fn(*args, **kwargs)
    except Exception as exc:  # the refusal is the characterized result
        return {"refused": type(exc).__name__, "message": str(exc)[:200]}
    return {"value": value}


def schedule_keys(store) -> set:
    return {row["id"] for row in scan(store, "schedule")}


class World:
    """A MemoryStore with the packaged organization and an ACTIVE audit control of the active release `release-0001`."""

    def __init__(self, api, *, control="active", release=True):
        self.api = api
        self.store, self.org = api.MemoryStore(), api.organization()
        self.service = SimpleNamespace(store=self.store, org=self.org)
        if release:
            plant_release(self)
        if control == "active":
            put(self.store, "research_control", "activation", {"status": "active", "release_id": RELEASE, "revision": REV})
        elif control:
            put(self.store, "research_control", "activation", {"status": control, "release_id": RELEASE, "revision": REV})

    # -- planted rows ---------------------------------------------------------------------------------------------------------
    def discovery(self, key):
        put(self.store, "research_discoveries", key, {"id": key})

    def backlog(self, key, priority, **extra):
        put(self.store, "research_backlog", key, {"id": key, "priority": priority, "repository": SOURCE_URL + "/" + key,
                                                  "revision": COMMIT, **extra})

    def audit(self, key):
        put(self.store, "research_audits", key, {"id": key, "repository": SOURCE_URL, "commit": COMMIT})

    def partition(self, key, audit_id, *, generation=0, paths=(), subsystems=(), questions=()):
        put(self.store, "research_partitions", key, {"partition_id": key, "audit_id": audit_id, "generation": generation,
                                                     "remaining_paths": list(paths), "remaining_subsystems": list(subsystems),
                                                     "open_questions": list(questions)})

    def task(self, key, status):
        put(self.store, "tasks", key, {"id": key, "status": status})

    def schedule_row(self, key, **body):
        put(self.store, "schedule", key, {"id": key, **body})

    def approval(self, audit_id, name, variant="good"):
        """An approval of `audit_id` the way the audit lifecycle leaves it, bound by the gate's own `binding` over the store as it is now."""
        proposal = {"name": name, "source": {"repository": SOURCE_URL, "commit": COMMIT}}
        with self.store.transaction() as tx:
            binding = self.api.binding(tx, audit_id, proposal)
        keys = []
        actors = ("lead:research", "conductor") if variant != "one_actor" else ("lead:research",)
        for actor in () if variant == "no_reviews" else actors:
            receipt = {"receipt": {"exit_status": 0, "inspection_blocked": variant == "blocked_inspection"}, "who": actor, "binding": binding}
            receipt_id = self.api.digest(receipt)
            put(self.store, "research_receipts", receipt_id, receipt)
            review = {"binding": binding, "accepted": True, "actor": actor, "execution_id": receipt_id}
            key = self.api.digest(review)
            if variant == "changed_review" and actor == "conductor":
                key = "not-the-review-digest"
            put(self.store, "research_reviews", key, {"review": review, "sequence": 1, "at": "t1"})
            keys.append(key)
            if variant == "rejected_later" and actor == "lead:research":
                later = {**review, "accepted": False}
                put(self.store, "research_reviews", self.api.digest(later), {"review": later, "sequence": 2, "at": "t2"})
        body = {"id": binding, "audit_id": audit_id, "proposal": proposal, "binding": binding, "reviews": keys,
                **({"status": "revoked"} if variant == "revoked" else {})}
        put(self.store, "research_approvals", binding, body)
        return binding

    # -- calls ----------------------------------------------------------------------------------------------------------------
    def call(self, fn, *args, **kwargs):
        """One call with the whole-store digest before and after, the `schedule` keys it added, then one tick of the fake clock."""
        before, keys = store_digest(self.store), schedule_keys(self.store)
        out = outcome(fn, self.service, *args, **kwargs, **self.api.ports(self.store, self.org))
        after = store_digest(self.store)
        self.api.advance(0.001)
        return {**out, "store_before": before, "store_after": after, "wrote": before != after,
                "added": sorted(schedule_keys(self.store) - keys)}

    def research(self, now=NOW):
        return self.call(self.api.schedule_research, now)

    def audits(self, audit_id=None):
        return self.call(self.api.schedule_audits, audit_id) if audit_id is not None else self.call(self.api.schedule_audits)

    def view(self):
        """The `schedule` rows and the `outbox` messages (the whole `who`/`what` of each) in key order."""
        return {"schedule": sorted(scan(self.store, "schedule"), key=lambda r: r["id"]),
                "outbox": [{"message_id": r["message_id"] if "message_id" in r else r["message"]["message_id"], "sent": r["sent"],
                            "message": r["message"]} for r in sorted(scan(self.store, "outbox"), key=lambda r: r["message"]["message_id"])]}


def plant_release(w, *, lifecycle=1, policy_hash=None, reviews="complete", checks="complete"):
    """The ACTIVE release `release-0001` as M7's `Releases.promote` leaves it (LABELLED: planted, not driven through propose/review/verify)."""
    policy = {"checks": ["tests", "cli_start", "cli_file_task"]}
    candidate = {"revision": REV, "tree": "fixture-tree", "base": "fixture-base", "author": "worker:implementation"}
    if lifecycle is not None:
        candidate["audit_lifecycle_version"] = lifecycle
    accepted = [{"actor": "lead:improvement", "accepted": True, "revision": REV, "evidence": "fixture-review"},
                {"actor": "conductor", "accepted": True, "revision": REV, "evidence": "fixture-review"}]
    if reviews == "missing_conductor":
        accepted = accepted[:1]
    results = {k: {"passed": True, "evidence": "fixture-canary-not-production"} for k in policy["checks"]}
    if checks == "failed":
        results["tests"] = {"passed": False, "evidence": "fixture"}
    put(w.store, "releases", RELEASE, {"id": RELEASE, "status": "active", "candidate": candidate, "policy": policy,
                                       "policy_hash": policy_hash or w.api.digest(policy), "reviews": accepted, "checks": results})
    put(w.store, "deployment", "active", {"release_id": RELEASE, "revision": REV})


def after(w, **extra):
    return {**extra, "view": w.view()}


# ---- cases ---------------------------------------------------------------------------------------------------------------------
def case_research_slot(api):
    """`none`: the research slot per source (`research:<source>:<slot>`), its idempotence, the next slot, and a closed control."""
    out = {"m7_test": "none"}
    w = World(api)
    out["first"] = w.research()
    out["repeat_same_slot"] = w.research()
    out["later_in_slot"] = w.research(NOW + 3600)
    out["next_slot"] = w.research(NOW + SLOT_SECONDS)
    out["view"] = w.view()
    # the slot rows are written BEFORE `schedule_audits` runs: a closed control schedules the sources and still returns their count
    closed = World(api, control="paused")
    out["paused_control"] = closed.research()
    out["paused_view"] = closed.view()
    nothing = World(api, control=None, release=False)
    out["no_control"] = nothing.research()
    # `schedule_research` returns what the slot scheduled plus what `schedule_audits` added
    both = World(api)
    both.discovery("d1")
    out["with_discovery"] = both.research()
    out["with_discovery_repeat"] = both.research()
    out["with_discovery_view"] = both.view()
    return out


def case_control(api):
    """`none`: control not active -> 0 and nothing written, with rows that would otherwise be scheduled."""
    out = {"m7_test": "none"}
    for name, control in (("absent", None), ("paused", "paused"), ("inactive", "inactive"), ("rolled_back", "rolled_back")):
        w = World(api, control=control, release=False)
        w.discovery("d1")
        w.backlog("b1", 1)
        w.audit("a1")
        w.partition("p1", "a1", paths=["x"])
        out[name] = w.audits()
    w = World(api, control=None, release=False)
    put(w.store, "research_control", "activation", {})
    w.discovery("d1")
    out["empty_control_row"] = w.audits()
    return out


def case_discovery(api):
    """`none`: one `map:<id>` assignment (`audit_discovery`) per discovery, once."""
    out = {"m7_test": "none"}
    w = World(api)
    for key in ("d-b", "d-a"):
        w.discovery(key)
    out["first"] = w.audits()
    out["repeat"] = w.audits()
    w.discovery("d-c")
    out["added_discovery"] = w.audits()
    out["view"] = w.view()
    return out


def case_acquire(api):
    """`none`: one `acquire:<id>` assignment (`audit_acquire`) per backlog row in priority order; a row with an `audit_id` is not acquired."""
    out = {"m7_test": "none"}
    w = World(api)
    w.backlog("b-two", 2)
    w.backlog("b-one", 1)
    w.backlog("b-done", 0, audit_id="a-done")
    w.backlog("b-three", 3)
    out["first"] = w.audits()
    out["repeat"] = w.audits()
    out["view"] = w.view()
    return out


def case_partition(api):
    """`none` (the overlap guard is the premise of the three `m7_*` cases): a partition is assigned once per generation, only while it has
    remaining paths, subsystems or questions, and only when no earlier assignment of that partition is queued, running or retrying."""
    out = {"m7_test": "none"}
    w = World(api)
    w.audit("a1")
    w.partition("p-queued", "a1", paths=["x"])        # predecessor: its task row is absent -> reads as `queued`
    w.partition("p-running", "a1", paths=["x"])
    w.partition("p-retry", "a1", subsystems=["s"])
    w.partition("p-done", "a1", questions=["q"])      # predecessor succeeded -> assigned
    w.partition("p-free", "a1", subsystems=["s"])     # no predecessor -> assigned
    w.partition("p-questions", "a1", questions=["q"])
    w.partition("p-complete", "a1")                   # nothing remaining -> never assigned
    for key, status in (("t-running", "running"), ("t-retry", "retry"), ("t-done", "succeeded")):
        w.task(key, status)
    w.schedule_row("prior-queued", partition_id="p-queued", task_id="t-absent")
    w.schedule_row("prior-running", partition_id="p-running", task_id="t-running")
    w.schedule_row("prior-retry", partition_id="p-retry", task_id="t-retry")
    w.schedule_row("prior-done", partition_id="p-done", task_id="t-done")
    out["first"] = w.audits()
    out["repeat"] = w.audits()
    w.task("t-running", "succeeded")
    out["after_running_succeeds"] = w.audits()
    out["after_running_repeat"] = w.audits()
    # a new generation is a new key; the NEW assignment's own task is absent (`queued`), so it blocks a further generation until it finishes
    w.partition("p-running", "a1", generation=1, paths=["x"])
    out["generation_bump_blocked_by_new_assignment"] = w.audits()
    new_task = next(r["task_id"] for r in scan(w.store, "schedule") if r.get("partition_id") == "p-running" and r["id"].startswith("audit:")
                    and r["task_id"] != "t-running")
    w.task(new_task, "succeeded")
    out["generation_bump_after_succeeded"] = w.audits()
    out["view"] = w.view()
    return out


def case_propose(api):
    """`none`: one `propose:<digest of the audit's partitions>` assignment (`audit_propose`) per audit whose partitions are ALL complete;
    changing a partition changes the key."""
    out = {"m7_test": "none"}
    w = World(api)
    for key in ("a-ready", "a-open", "a-empty"):
        w.audit(key)
    w.partition("p-ready-1", "a-ready")
    w.partition("p-ready-2", "a-ready", generation=3)
    w.partition("p-open-1", "a-open")
    w.partition("p-open-2", "a-open", questions=["q"])
    out["first"] = w.audits()
    out["repeat"] = w.audits()
    w.partition("p-ready-2", "a-ready", generation=4)
    out["changed_partition"] = w.audits()
    out["view"] = w.view()
    return out


APPROVAL_VARIANTS = ("good", "no_reviews", "one_actor", "revoked", "rejected_later", "blocked_inspection", "changed_review")


def case_adopt(api):
    """`none`: one `adopt:<binding>` assignment (a `plan` from the conductor to lead:improvement) per approval the gate admits;
    `require_adoption` refusing an approval is a skip, never an error; the gate's reasons are one world per variant."""
    out = {"m7_test": "none"}
    for variant in APPROVAL_VARIANTS:
        w = World(api)
        w.audit("a1")
        w.partition("p1", "a1")
        binding = w.approval("a1", "proposal-" + variant, variant)
        result = w.audits()
        out[variant] = {"binding": binding, "pass": result, "repeat": w.audits()}
    w = World(api)
    w.audit("a1")
    w.partition("p1", "a1")
    w.approval("a1", "proposal-stale")
    w.partition("p1", "a1", generation=9)  # the evidence the approval was bound to changed
    out["stale_binding"] = w.audits()
    other = World(api)
    other.audit("a1")
    other.partition("p1", "a1")
    other.approval("a1", "proposal-other-release")
    put(other.store, "research_control", "activation", {"status": "active", "release_id": "release-0002", "revision": REV})
    out["control_of_another_release"] = other.audits()
    w = World(api)
    w.audit("a1")
    w.partition("p1", "a1")
    w.approval("a1", "proposal-one")
    w.approval("a1", "proposal-two")
    out["two_approvals"] = {"first": w.audits(), "repeat": w.audits(), "view": w.view()}
    return out


def case_audit_narrowed(api):
    """`none` (M7's `tests/test_scheduling.py` passes `audit_id`): a pass narrowed to one audit schedules only that audit's partitions,
    proposal and adoption; discovery and acquisition are left to the global pass; an unknown audit schedules nothing."""
    out = {"m7_test": "none"}
    w = World(api)
    w.discovery("d1")
    w.backlog("b1", 1)
    for key in ("a1", "a2"):
        w.audit(key)
    w.partition("p-a1-open", "a1", paths=["x"])
    w.partition("p-a1-done", "a1")
    w.partition("p-a2-done", "a2")
    w.approval("a1", "proposal-a1")
    w.approval("a2", "proposal-a2")
    out["a1"] = w.audits("a1")
    out["a1_repeat"] = w.audits("a1")
    out["unknown"] = w.audits("no-such-audit")
    out["a2"] = w.audits("a2")
    out["global"] = w.audits()
    out["global_repeat"] = w.audits()
    out["view"] = w.view()
    return out


def case_m7_correction_interactions(api):
    """The three tests of M7 `tests/test_scheduling.py`, over PLANTED rows instead of the audit-repair fixtures (the planted shape is what the
    fixtures leave: the rejected generation's ordinary key, a correction's own `schedule` row carrying the `partition_id`, a settled task)."""
    out = {}
    ordinary = lambda w, partition: "audit:" + w.api.digest({"partition": partition, "generation": 0})  # noqa: E731
    w = World(api)
    w.audit("a1")
    w.partition("p1", "a1", paths=["x"])
    w.task("t-rejected", "succeeded")
    w.schedule_row(ordinary(w, "p1"), task_id="t-rejected", partition_id="p1")
    out["test_the_rejected_generation_is_never_resubmitted_by_the_scheduler"] = {
        "m7_test": "test_the_rejected_generation_is_never_resubmitted_by_the_scheduler", "pass": w.audits("a1"), "view": w.view()["schedule"]}
    w = World(api)
    w.audit("a1")
    w.partition("p1", "a1", paths=["x"])
    w.task("t-correction", "queued")
    w.schedule_row("correction:c1", task_id="t-correction", partition_id="p1")
    out["test_a_queued_correction_blocks_a_second_assignment_for_its_partition"] = {
        "m7_test": "test_a_queued_correction_blocks_a_second_assignment_for_its_partition", "pass": w.audits("a1"),
        "view": w.view()["schedule"]}
    w = World(api)
    w.audit("a1")
    w.partition("p1", "a1", generation=1, paths=["x"])
    w.task("t-rejected", "succeeded")
    w.task("t-correction", "succeeded")
    w.schedule_row(ordinary(w, "p1"), task_id="t-rejected", partition_id="p1")
    w.schedule_row("correction:c1", task_id="t-correction", partition_id="p1")
    out["test_the_ordinary_continuation_resumes_after_the_correction_checkpoints"] = {
        "m7_test": "test_the_ordinary_continuation_resumes_after_the_correction_checkpoints", "pass": w.audits("a1"), "view": w.view()}
    return out


def case_reconcile(api):
    """`none` (M7 `tests/test_research_audits.py::activate_fixture` runs the same `Releases` at the head of `schedule_audits`): the head
    `reconcile_audits` runs BEFORE the transaction, so an ACTIVE audit release with no control activates it and the same pass schedules;
    a pause or a rollback of that release survives; an invalid record is refused with nothing written (the research slot stays committed)."""
    out = {"m7_test": "none"}

    def world(**release):
        w = World(api, control=None, release=False)
        plant_release(w, **release)
        w.discovery("d1")
        return w

    w = world()
    out["activates"] = {"pass": w.audits(), "control": get(w.store, "research_control", "activation"),
                        "graph": get(w.store, "research_control", "graph"), "repeat": w.audits(), "view": w.view()}
    w = world()
    out["activates_from_schedule_research"] = {"pass": w.research(), "control": get(w.store, "research_control", "activation"), "view": w.view()}
    w = world(lifecycle=None)
    out["no_audit_lifecycle_version"] = {"pass": w.audits(), "control": get(w.store, "research_control", "activation")}
    w = world(lifecycle=2)
    out["other_lifecycle_version"] = {"pass": w.audits(), "control": get(w.store, "research_control", "activation")}
    for name, control in (("paused", {"status": "paused", "release_id": "release-other", "revision": REV}),
                          ("same_release", {"status": "inactive", "release_id": RELEASE, "revision": REV}),
                          ("rolled_back_release", {"status": "inactive", "rolled_back_release": RELEASE})):
        w = world()
        put(w.store, "research_control", "activation", control)
        out[name] = {"pass": w.audits(), "control": get(w.store, "research_control", "activation"),
                     "graph": get(w.store, "research_control", "graph")}
    w = World(api, control=None, release=False)
    out["no_deployment"] = {"pass": w.audits(), "control": get(w.store, "research_control", "activation")}
    w = world()
    put(w.store, "releases", RELEASE, {**get(w.store, "releases", RELEASE), "status": "rolled_back"})
    out["release_not_active"] = {"pass": w.audits(), "control": get(w.store, "research_control", "activation")}
    for name, options in (("policy_hash_changed", {"policy_hash": "0" * 64}), ("reviews_incomplete", {"reviews": "missing_conductor"}),
                          ("checks_incomplete", {"checks": "failed"})):
        w = world(**options)
        out[name] = {"pass": w.audits(), "control": get(w.store, "research_control", "activation"), "view": w.view()["schedule"]}
    w = world(policy_hash="0" * 64)
    out["invalid_release_after_research_slot"] = {"pass": w.research(), "view": w.view()}
    w = world()
    put(w.store, "deployment", "active", {"release_id": RELEASE, "revision": "rev-other"})
    out["revision_differs_from_the_deployment"] = {"pass": w.audits(), "control": get(w.store, "research_control", "activation")}
    return out


def case_idempotence(api):
    """`none`: every key kind (`research:`, `map:`, `acquire:`, `audit:`, `propose:`, `adopt:`) is created once; repeated calls change nothing."""
    out = {"m7_test": "none"}
    w = World(api)
    w.discovery("d1")
    w.backlog("b1", 1)
    for key in ("a1", "a2"):
        w.audit(key)
    w.partition("p-a1", "a1", paths=["x"])
    w.partition("p-a2", "a2")
    w.approval("a2", "proposal-a2")
    out["research"] = w.research()
    digests = []
    for n in range(3):
        out["audits_%d" % n] = w.audits()
        digests.append(out["audits_%d" % n]["store_after"])
    out["research_again"] = w.research()
    out["stable"] = len(set(digests)) == 1
    keys = sorted(schedule_keys(w.store))
    out["keys_by_kind"] = {kind: sum(1 for k in keys if k.startswith(kind + ":")) for kind in ("research", "map", "acquire", "audit", "propose", "adopt")}
    out["view"] = w.view()
    return out


CASES = (case_research_slot, case_control, case_discovery, case_acquire, case_partition, case_propose, case_adopt, case_audit_narrowed,
         case_m7_correction_interactions, case_reconcile, case_idempotence)


def run(api) -> dict:
    return {fn.__name__[len("case_"):]: fn(api) for fn in CASES}
