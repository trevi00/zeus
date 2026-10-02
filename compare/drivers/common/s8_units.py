"""Shared S8 scenario steps (`effects.s8_units`): the §2.9 transaction units of research, intake and the release evaluator,
observed through the S0 recorder (DESIGN-s8 §1 V8 and §2 row `effects.s8_units`; REBUILD-DESIGN-v2 §2.9), over the
MemoryStore only. The S7 form (`s7_units`, `s6_units`) applied to S8.

Units (M7 names; the target's V8 homes keep each one whole):
- `record_collection` (U-1): `ResearchProgram.record_collection` (`application/research_program.py:410`): the ownership
  read, the dedup and relevance, the candidate rows, the claim and the adoption reservation (`row["adoptions"] += 1`), the
  cycle row and the program row in ONE transaction; the program row is its last write;
- `fail_cycle` (U-2): `ResearchProgram.fail_cycle` (`:1448`) with its `recovery`: the cycle's failure record, a failed
  dispatch row (an investigation program), `_close`'s cycle row and the program row (the last write) in ONE transaction;
- `submit` (U-3): `FrontDesk.submit` (`application/frontdesk.py:100`): the request row, the session row, the outbox row and
  the `intake` event in ONE transaction; the event is the last write;
- `evaluator_completion` (U-4): `ReleaseRunner.run`'s completion unit (`adapters/deployment.py:591-595`):
  `releases.promote(release_id, expected_active, transaction=tx)`, the hook activation and the `promotion_intents` row set
  to `completed` in ONE transaction; its external effect is the merge (`git.merge`), recorded at depth 0.

Discriminators:
- **(a)** a failure injected at the unit's LAST write (`s6_units.FaultStore`) leaves nothing of the unit;
- **(b)** a stale writer commits nothing: the cycle's owner token, status or the program's active cycle moved (U-1, U-2),
  a rival turn opened in the session between the assignment and the unit (U-3), the active pointer, the release or the
  intent moved after the merge (U-4);
- **(c)** a same-key replay adds no authority write (a replay after success; a replay after a failed unit finds nothing of
  the unit and runs it once);
- **(d)** the external effect is entered at transaction depth 0 (the `effects` list of every result). U-1, U-2 and U-3
  have none: `{"not_applicable": ...}` names the M7 lines.

Layer: harness (never shipped)

This module never imports `codex_harness`: everything arrives through `api`: `api.program`, `api.desk` and `api.runner`, the
APIs of the reused worlds (`s8_program_records`/`s8_research_program` for U-1 and U-2, `s8_frontdesk` for U-3,
`s7_release_runner` for U-4) over ONE scripted clock and id source, plus `backend(name)` (`.store`, `.rows()`, `.drop()`),
`reset()` and `recording(store)` (the S0 RecordingStore). The store of every
world is the recorded, fault-injectable `s6_units.FaultStore`; a second controller (the mover of a stale case) acts on the
backend's own store, outside the recorder. The compared results are the unit outcomes, the durable writes (bucket and
status), the recorder violations, the effect depths, the digests of the durable rows that changed and the rows themselves,
read back from the backend.

LABELLED doubles added here: the hook activation of U-4 (`service.activate`, a `hooks` row written in the caller's
transaction: the reused `Harness` has no hook registry), and the fixture Git's merge moving `main` to the candidate (so a
replay after a failed completion recovers the merge as M7's `current_main == expected_head` branch does).
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from types import SimpleNamespace

import s6_units as U
import s7_release_runner as RR
import s7_units as S7
import s8_frontdesk as FD
import s8_program_records as PR
import s8_research_program as R

NOT_APPLICABLE = {
    "record_collection": {"not_applicable": "M7 application/research_program.py:410-475 reads and writes the store only: no "
                                            "process, network, provider or Git call (the collection items arrive as arguments)"},
    "fail_cycle": {"not_applicable": "M7 application/research_program.py:1448-1470 reads and writes the store only: the "
                                     "failed dispatch is a row, nothing is released, retried or called"},
    "submit": {"not_applicable": "M7 application/frontdesk.py:100-130 only writes the outbox row inside the unit; the "
                                 "publication is DeskRunner's flush, a separate unit"}}


class Case(S7.Case):
    """One fresh recorded, fault-injectable store (`s7_units.Case`), the shim that hands it to a world that builds its own
    `MemoryStore` (once), and the changed rows' digests."""

    def __init__(self, api, world):
        super().__init__(api)
        self.shim = SimpleNamespace(**vars(world))
        stores = iter([self.store])
        self.shim.MemoryStore = lambda: next(stores)

    def result(self, outcome, **extra):
        changed = {(b, k): d for b, k, _, d in self.backend.rows() if self.before.get((b, k)) != d}
        return super().result(outcome, changed_digests=sorted([b, k, d] for (b, k), d in changed.items()), **extra)

    def arm_open(self, bucket):
        """LABELLED. One failure at the next put into `bucket` of the transaction ALREADY OPEN: `FaultStore.arm` replaces the
        plan, which an open `FaultTransaction` no longer sees, so the plan is updated in place (this case arms no other way)."""
        return lambda: self.store.plan.update(bucket=bucket, state=None, armed=True)

    def rival(self, fn):
        """A second controller acts on the backend's own store (outside the recorder); the call that follows shows it."""
        def move():
            fn(self.backend.store)
        return self.mover(move)


def edit(store, bucket, key, **fields):
    """LABELLED. Another writer's row edit, on the backend's own store."""
    with store.transaction() as tx:
        tx.put(bucket, key, {**tx.get(bucket, key), **fields})


def attempt(fn, *args, **kwargs):
    out = U.attempt(fn, *args, **kwargs)
    value = out.pop("value", None)
    if isinstance(value, dict):
        out["cached"] = value.get("cached")
    return out


# ---- unit 1: ResearchProgram.record_collection ---------------------------------------------------------------------------
def program(case, ws, **overrides):
    """A registered, resumed program over the case's recorded store; its cycle 1 reserved and collecting."""
    s = PR.system(case.shim, ws, store=case.store)
    PR.register(s, max_cycles=4, max_adoptions=2, **overrides)
    return s, PR.reserve(s)


def observe(s, cycle_id):
    return {"row": PR.counters(s), "candidates": PR.cands(s),
            "cycle": PR.brief(PR.get(s.store, s.api.BUCKET_CYCLES, cycle_id))}


def collection(api, ws, variant):
    case = Case(api, api.program)
    s, cycle = program(case, ws)
    case.since()
    items = (PR.PGTOOL, PR.UNRELATED)
    if variant in ("a_failure_at_program_row", "c_replay_after_failure"):
        case.hooks["collect"] = case.arm(s.api.BUCKET_PROGRAMS)
    elif variant == "a_failure_at_cycle_row":
        case.hooks["collect"] = case.arm(s.api.BUCKET_CYCLES)
    elif variant == "a_failure_at_candidate_row":
        case.hooks["collect"] = case.arm(s.api.BUCKET_CANDIDATES)
    elif variant == "b_owner_moved":
        case.hooks["collect"] = case.rival(lambda store: edit(store, s.api.BUCKET_CYCLES, cycle["id"], owner="another-owner"))
    elif variant == "b_cycle_state_moved":
        case.hooks["collect"] = case.rival(lambda store: edit(store, s.api.BUCKET_CYCLES, cycle["id"], status="failed"))
    elif variant == "b_active_cycle_moved":
        case.hooks["collect"] = case.rival(lambda store: edit(store, s.api.BUCKET_PROGRAMS, R.PROGRAM, active_cycle="rp-001:099"))
    out = collect_once(case, s, cycle, items)
    if variant == "c_replay_after_failure":
        # the unit failed at its last write and left nothing: the same key collects once, the adoption counted once
        case.since()
        return case.result(collect_once(case, s, cycle, items), first=out, **observe(s, cycle["id"]))
    if variant == "c_replay_after_success":
        case.since()
        return case.result(collect_once(case, s, cycle, items), first=out, **observe(s, cycle["id"]))
    return case.result(out, **NOT_APPLICABLE["record_collection"], **observe(s, cycle["id"]))


def collect_once(case, s, cycle, items):
    """One `record_collection`; the moved/armed hook fires just before the call (after the caller's reads)."""
    hook = case.hooks.pop("collect", None)
    if hook is not None:
        hook()
    out = attempt(PR.collect, s, cycle, items)
    return out


# ---- unit 2: ResearchProgram.fail_cycle ------------------------------------------------------------------------------------
RECOVERY = {"capture": {"ref": R.CAPTURE_REF, "path": R.CAPTURE_PATH}, "note": "fixture-recovery"}


def failing_program(case, ws, investigation):
    """A selected cycle: the local candidate, or (an investigation program, LABELLED rows of `s8_research_program`) a claimed
    investigation family, whose failure also writes the dispatch row."""
    if not investigation:
        s, cycle = program(case, ws)
        PR.collect(s, cycle, (PR.LOCAL,))
        return s, cycle
    R.portfolio(case.shim, case.store)
    s = PR.system(case.shim, ws, store=case.store)
    PR.register(s, max_cycles=3, max_adoptions=2, investigation_source=dict(R.SOURCE))
    cycle = PR.reserve(s)
    PR.collect(s, cycle, (PR.PGTOOL,))
    return s, cycle


def dispatches(s):
    return sorted([row["id"], row["state"], row["result"]] for row in PR.scan(s.store, s.api.BUCKET_DISPATCHES))


def failure(api, ws, variant, *, investigation=False):
    case = Case(api, api.program)
    s, cycle = failing_program(case, ws, investigation)
    case.since()
    owner, bucket = cycle["owner"], s.api.BUCKET_PROGRAMS
    if variant in ("a_failure_at_program_row", "c_replay_after_failure"):
        case.hooks["fail"] = case.arm(bucket)
    elif variant == "a_failure_at_cycle_row":
        case.hooks["fail"] = case.arm(s.api.BUCKET_CYCLES)
    elif variant == "a_failure_at_dispatch_row":
        case.hooks["fail"] = case.arm(s.api.BUCKET_DISPATCHES)
    elif variant == "b_owner_moved":
        case.hooks["fail"] = case.rival(lambda store: edit(store, s.api.BUCKET_CYCLES, cycle["id"], owner="another-owner"))
    elif variant == "b_cycle_state_moved":
        case.hooks["fail"] = case.rival(lambda store: edit(store, s.api.BUCKET_CYCLES, cycle["id"], status="done"))
    elif variant == "b_active_cycle_moved":
        case.hooks["fail"] = case.rival(lambda store: edit(store, bucket, R.PROGRAM, active_cycle="rp-001:099"))

    def fail_once():
        hook = case.hooks.pop("fail", None)
        if hook is not None:
            hook()
        return attempt(s.programs.fail_cycle, cycle["id"], owner, "capture", "capture_refused", dict(RECOVERY))

    out = fail_once()
    extra = {**NOT_APPLICABLE["fail_cycle"], **observe(s, cycle["id"])}
    if investigation:
        extra["dispatches"] = dispatches(s)
    if variant in ("c_replay_after_failure", "c_replay_after_success"):
        case.since()
        again = fail_once()
        extra = {**NOT_APPLICABLE["fail_cycle"], **observe(s, cycle["id"])}
        if investigation:
            extra["dispatches"] = dispatches(s)
        return case.result(again, first=out, **extra)
    return case.result(out, **extra)


# ---- unit 3: FrontDesk.submit ----------------------------------------------------------------------------------------------
def submit(api, variant):
    desk_api = api.desk
    case = Case(api, desk_api)
    w = FD.World(desk_api)
    svc = desk_api.Harness(case.store, desk_api.organization())
    svc, desk, session_id = w.opened(svc)
    request, rival_request = FD.IDS.uuid(), FD.IDS.uuid()
    document = {"session_id": session_id, "request_id": request, "intent": "consult", "text": "지금 상태가 어때?"}
    case.since()
    if variant in ("a_failure_at_event", "c_replay_after_failure"):
        case.hooks["submit"] = case.arm("desk_events")
    elif variant == "a_failure_at_outbox":
        case.hooks["submit"] = case.arm("outbox")
    elif variant == "b_rival_turn_opened":
        # another desk opens a turn in the session between the assignment and the unit
        assignment = desk._assignment

        def assigned(submitted):
            message = assignment(submitted)
            hook = case.hooks.pop("assigned", None)
            if hook is not None:
                hook()
            return message
        desk._assignment = assigned

        def rival(store):
            other = desk_api.FrontDesk(desk_api.Harness(store, desk_api.organization()), FD.REVISION)
            other.submit({**document, "request_id": rival_request, "text": "rival"})
        case.hooks["assigned"] = case.rival(rival)
    elif variant == "b_request_content_moved":
        # the same request id already holds other content (another writer's turn): refused, nothing written
        other = desk_api.FrontDesk(desk_api.Harness(case.backend.store, desk_api.organization()), FD.REVISION)
        other.submit({**document, "text": "something else"})
        case.since()

    def submit_once():
        hook = case.hooks.pop("submit", None)
        if hook is not None:
            hook()
        return attempt(desk.submit, dict(document))

    out = submit_once()
    if variant in ("c_replay_after_failure", "c_replay_after_success"):
        case.since()
        return finish_submit(case, svc, request, submit_once(), first=out)
    return finish_submit(case, svc, request, out)


def finish_submit(case, svc, request, out, **extra):
    store = case.backend.store
    with store.transaction() as tx:
        rows = {"requests": sorted([r["id"], r["status"]] for r in tx.scan("desk_requests")),
                "outbox": sorted([r["message"]["message_id"], r["sent"]] for r in tx.scan("outbox")),
                "events": sorted(r["id"] for r in tx.scan("desk_events")),
                "session": [[r["id"], r["request_count"]] for r in tx.scan("desk_sessions")]}
    return case.result(out, **NOT_APPLICABLE["submit"], **rows, **extra)


# ---- unit 4: the release evaluator's completion unit ------------------------------------------------------------------------
def completion(api, base, variant):
    case = Case(api, api.runner)
    fx = RR.Fx(case.shim, base)
    world = fx.world("s8-" + variant)
    world.git = RR.FixtureGit(fx, world.dir, merge_error=None)
    world.runner.git = world.git
    record = RR.reviewed(world, verified=True, hook_id="hook-1")
    release_id = record["id"]
    runner, merge = world.runner, world.git.merge

    def merged(candidate):
        case.recorder.effect("git.merge")
        out = merge(candidate)
        world.git.main = candidate["revision"]   # LABELLED: the fixture's main moves to the merged candidate
        hook = case.hooks.pop("git.merge", None)
        if hook is not None:
            hook()
        return out
    world.git.merge = merged
    promote = runner.releases.promote

    def promoted(*args, **kwargs):
        hook = case.hooks.pop("promote", None)
        if hook is not None:
            hook()   # inside the completion unit: the failure is armed on the open transaction
        return promote(*args, **kwargs)
    runner.releases.promote = promoted

    def activate(hook_id, *, transaction):
        """LABELLED: the hook activation, a `hooks` row written in the caller's transaction."""
        transaction.put("hooks", hook_id, {"id": hook_id, "status": "active"})
        return {"id": hook_id, "status": "active"}
    world.service.activate = activate
    case.since()
    store = case.backend.store
    if variant in ("a_failure_at_intent_row", "c_replay_after_failure"):
        case.hooks["promote"] = case.arm_open("promotion_intents")   # the unit's last write
    elif variant == "a_failure_at_hook_row":
        case.hooks["promote"] = case.arm_open("hooks")
    elif variant == "a_failure_at_promotion_last_write":
        case.hooks["promote"] = case.arm_open("events")   # `releases.promote`'s last put
    elif variant == "b_active_moved":
        case.hooks["git.merge"] = case.rival(lambda s: pointer_moved(s))
    elif variant == "b_release_moved":
        case.hooks["git.merge"] = case.rival(lambda s: edit(s, "releases", release_id, status="cancelled"))

    def run_once():
        with world.active():
            return world.attempt(lambda: runner.run(release_id))

    out = run_once()
    if variant in ("c_replay_after_failure", "c_replay_after_success"):
        case.since()
        again = run_once()
        return case.result(world.n(again), first=world.n(out), **view(world, store, release_id))
    return case.result(world.n(out), **view(world, store, release_id))


def view(world, store, release_id):
    """What the backend holds after the case (read outside the recorder), and the Git calls that were made."""
    with store.transaction() as tx:
        rows = {"intent": tx.get("promotion_intents", release_id), "release": tx.get("releases", release_id),
                "pointer": tx.get("deployment", "active"), "hook": tx.get("hooks", "hook-1")}
    return {"git_calls": [call[0] for call in world.git.calls if call[0] in ("merge", "publish")],
            "intent": (rows["intent"] or {}).get("status"), "release": (rows["release"] or {}).get("status"),
            "pointer": world.n((rows["pointer"] or {}).get("release_id")), "hook": (rows["hook"] or {}).get("status")}


def pointer_moved(store):
    with store.transaction() as tx:
        tx.put("deployment", "active", {"release_id": "release-other", "revision": "2" * 40, "previous": None, "at": "t"})


# ---- the run ------------------------------------------------------------------------------------------------------------------
def run(api) -> dict:
    ws = R.Workspace()
    try:
        with tempfile.TemporaryDirectory(prefix="s8-units-") as raw:
            base = Path(raw).resolve()
            collections = ("success", "a_failure_at_program_row", "a_failure_at_cycle_row", "a_failure_at_candidate_row",
                           "b_owner_moved", "b_cycle_state_moved", "b_active_cycle_moved", "c_replay_after_success",
                           "c_replay_after_failure")
            failures = ("success", "a_failure_at_program_row", "a_failure_at_cycle_row", "b_owner_moved",
                        "b_cycle_state_moved", "b_active_cycle_moved", "c_replay_after_success", "c_replay_after_failure")
            return {
                "record_collection": {v: collection(api, ws, v) for v in collections},
                "fail_cycle": {v: failure(api, ws, v) for v in failures},
                "fail_cycle_dispatch": {v: failure(api, ws, v, investigation=True) for v in (
                    "success", "a_failure_at_dispatch_row", "a_failure_at_program_row", "c_replay_after_failure")},
                "submit": {v: submit(api, v) for v in (
                    "success", "a_failure_at_event", "a_failure_at_outbox", "b_rival_turn_opened",
                    "b_request_content_moved", "c_replay_after_success", "c_replay_after_failure")},
                "evaluator_completion": {v: completion(api, base, v) for v in (
                    "success", "a_failure_at_intent_row", "a_failure_at_hook_row", "a_failure_at_promotion_last_write",
                    "b_active_moved", "b_release_moved", "c_replay_after_success",
                    "c_replay_after_failure")},
                "evaluator_completion_unreachable": {"b_intent_moved": {"unreachable": (
                    "M7 adapters/deployment.py:591-595 completes from the `intent` held in memory (written at :541-546 and "
                    ":578-580) and never re-reads promotion_intents inside the unit: another writer's edit of the row is "
                    "overwritten by the completed row, not refused")}}}
    finally:
        ws.close()
