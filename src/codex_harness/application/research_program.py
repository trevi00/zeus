"""Research program state machine over the existing store (INV-RESEARCH-PROGRAM-001).

Four buckets: `research_programs` (immutable config, digest, durable counters and state),
`research_program_candidates` (dedup identity across cycles, relevance reason, claim and result),
`research_program_cycles` (one receipt per reserved cycle) and `research_investigation_dispatches`
(one claim per portfolio investigation, keyed SOLELY by investigation id, across every program).
Every state change is one store transaction that re-reads the row it expects; no transaction stays
open across network, Git or provider work: the adapter reserves, then fetches, then records. A
reserved cycle stays owned until its owner records a terminal fact; a crash leaves it owned and the
program busy, never assumed empty. Counters never reset: the adoption cap counts every dispatched
council, accepted or not.

The investigation bridge (research-dispatch-001) is opt-in per program. Candidates are synthesized
from the authoritative `portfolio_investigations`, `portfolio_bindings` and `fleet_jobs` reads INSIDE
the selection transaction - an adapter may never supply one as a discovery item - and the claim, the
cycle reservation bookkeeping and the candidate selection commit together. `portfolio_investigations`
is read only: no owner disposition, Fleet job or investigation state is ever written here, a dispatch
result is never an incident resolution, and an unknown outcome keeps its claim instead of releasing it.

The audit-progress bridge (self-improvement-reference-001) is the SAME path for a second explicit
candidate kind: an opt-in `audit_progress_source` synthesizes candidates from the authoritative
`portfolio_investigations` rows of that kind together with their epoch state and their completed
windows, revalidates all of it inside the selection transaction, and claims through the same
cross-program dispatch bucket. Failure-family eligibility, its counts and its snapshot are
untouched, the two kinds are counted and reported apart, and no audit, partition, task or window row
is ever written here: a claim is a research dispatch, never an audit decision or a promotion.

Dispatch transport recovery (research-dispatch-recovery-001) is the one owner-authorized exception to
"a failed dispatch keeps its claim": a proven pre-provider failure may be replaced ONCE by a new
registered program with the same authority, through `research_dispatch_recoveries`. The failed rows
stay history; the lineage names the replacement key that is the investigation's current dispatch.
"""
from __future__ import annotations

from uuid import uuid4

from codex_harness.application.audit_progress import (
    BUCKET_STATE as BUCKET_PROGRESS_STATE,
)
from codex_harness.application.audit_progress import (
    BUCKET_WINDOWS as BUCKET_PROGRESS_WINDOWS,
)
from codex_harness.application.audit_progress import (
    packaged_policy,
)
from codex_harness.application.autonomous import BUCKET as BUCKET_RUNS
from codex_harness.application.autonomous import OPERATIONS, RESERVATIONS
from codex_harness.application.dge import SESSIONS
from codex_harness.application.fleet import BUCKET_JOBS
from codex_harness.application.outbox import _quarantine as quarantine_outbox
from codex_harness.application.portfolio import (
    BUCKET_BINDINGS,
    BUCKET_INVESTIGATIONS,
    FAMILY_MINIMUM,
    RESEARCH_REQUIRED,
)
from codex_harness.domain.audit_progress import KIND as AUDIT_PROGRESS
from codex_harness.domain.audit_progress import (
    candidate_label as progress_label,
)
from codex_harness.domain.audit_progress import (
    eligible_candidates,
    policy_digest,
    validate_policy,
)
from codex_harness.domain.audit_progress import (
    snapshot as progress_snapshot,
)
from codex_harness.domain.model import digest, require, utcnow
from codex_harness.domain.research_investigations import (
    AUTHORIZED,
    DISPATCHED,
    FENCE_REASON,
    FENCED,
    RECOVERED,
    REFUSED,
    RESOLVED,
    InvestigationRefused,
    candidate_identity,
    check_recovery,
    current_dispatch_id,
    dispatch_row,
    dispatch_view,
    eligible_investigations,
    recovery_view,
    replacement_dispatch_id,
    snapshot,
    validate_recovery_request,
)
from codex_harness.domain.research_investigations import (
    SOURCE as INVESTIGATION,
)
from codex_harness.domain.research_program import (
    ACTIVE,
    BLOCKED,
    CAPTURED,
    CLAIMED,
    COLLECTING,
    COMPLETED,
    COUNCIL,
    CYCLE_DONE,
    CYCLE_FAILED,
    ELIGIBLE,
    IGNORED,
    NO_SELECTION,
    PAUSED,
    RESULTS,
    SELECTED,
    ProgramRefused,
    candidate_id,
    candidate_key,
    config_digest,
    council_result,
    cycle_id,
    due,
    expired,
    headroom,
    match_topics,
    monitor_projection,
    program_view,
    safe_code,
    same_authority,
    select_candidate,
)

BUCKET_PROGRAMS, BUCKET_CANDIDATES, BUCKET_CYCLES = ("research_programs", "research_program_candidates",
                                                     "research_program_cycles")
BUCKET_DISPATCHES = "research_investigation_dispatches"
BUCKET_RECOVERIES = "research_dispatch_recoveries"
ELIGIBLE_REASON, INELIGIBLE_REASON = "portfolio_investigation_eligible", "investigation_ineligible"
PROGRESS_ELIGIBLE_REASON, PROGRESS_INELIGIBLE_REASON = "audit_progress_eligible", "audit_progress_ineligible"


class ResearchProgram:
    def __init__(self, store, clock=utcnow, token=lambda: uuid4().hex, progress_policy=None):
        self.store, self.clock, self.token = store, clock, token
        # The audit-progress thresholds in force, as versioned data only: this state machine never
        # measures an audit, never observes one and never edits a threshold. It reads the digest so
        # a candidate recorded under other thresholds can never be dispatched as if it were current.
        self.progress_policy = validate_policy(packaged_policy() if progress_policy is None else progress_policy)
        self.progress_policy_sha256 = policy_digest(self.progress_policy)

    # ----- registration -----------------------------------------------------------------------
    def register(self, config: dict, repository: str, verified_local: list) -> dict:
        """Idempotent for the identical config in the identical repository; anything else under the
        same id is `registration_conflict`. Initially paused; no model, network or Git access here."""
        sha = config_digest(config, repository)
        with self.store.transaction() as tx:
            old = tx.get(BUCKET_PROGRAMS, config["id"])
            if old is not None:
                if old["config_sha256"] != sha:
                    raise ProgramRefused("registration_conflict")
                return {"registered": True, "cached": True, "id": old["id"], "config_sha256": sha, "state": old["state"]}
            now = self.clock()
            row = {"id": config["id"], "schema": config["schema"], "config": config, "config_sha256": sha,
                   "repository": repository, "state": PAUSED, "cycles": 0, "adoptions": 0, "next_cycle": 1,
                   "active_cycle": None, "last_tick_at": None, "stop_reason": None, "blocked_reason": None,
                   "verified_local": [{"id": v["id"], "path": v["path"], "sha256": v["sha256"]} for v in verified_local],
                   "registered_at": now, "updated_at": now}
            tx.put(BUCKET_PROGRAMS, row["id"], row)
        return {"registered": True, "cached": False, "id": row["id"], "config_sha256": sha, "state": PAUSED}

    def _row(self, tx, program_id: str) -> dict:
        row = tx.get(BUCKET_PROGRAMS, program_id)
        if row is None:
            raise ProgramRefused("unknown_program")
        return row

    def config(self, program_id: str) -> dict:
        with self.store.transaction() as tx:
            return self._row(tx, program_id)["config"]

    # ----- pause / resume ---------------------------------------------------------------------
    def pause(self, program_id: str) -> dict:
        """Blocks NEW ticks durably; an owned active cycle finishes under its owner."""
        with self.store.transaction() as tx:
            row = self._row(tx, program_id)
            if row["state"] == ACTIVE:
                row.update(state=PAUSED, updated_at=self.clock())
                tx.put(BUCKET_PROGRAMS, program_id, row)
            return {"id": program_id, "state": row["state"], "active_cycle": row["active_cycle"]}

    def resume(self, program_id: str) -> dict:
        """Paused -> active only. Completed stays completed; blocked needs a new authorized program
        (no blind repair); the counters are untouched either way."""
        with self.store.transaction() as tx:
            row = self._row(tx, program_id)
            if row["state"] in {COMPLETED, BLOCKED}:
                raise ProgramRefused("program_" + row["state"])
            if row["state"] == PAUSED:
                row.update(state=ACTIVE, updated_at=self.clock())
                tx.put(BUCKET_PROGRAMS, program_id, row)
            return {"id": program_id, "state": row["state"], "active_cycle": row["active_cycle"]}

    # ----- reservation ------------------------------------------------------------------------
    def reserve_cycle(self, program_id: str, repository: str) -> dict:
        """One transaction before any fetch: the current repository identity must equal the
        registered one (review001 R1: `repository_mismatch` is raised before any reservation, log,
        fetch, capture or model effect), then pause, deadline, cap, interval and busy checks, then
        the next cycle number with a fresh owner token. `reserved` False carries the fixed reason."""
        with self.store.transaction() as tx:
            row = self._row(tx, program_id)
            if not repository or row.get("repository") != repository:
                raise ProgramRefused("repository_mismatch")
            now = self.clock()
            config = row["config"]
            if row["active_cycle"] is not None:
                return {"reserved": False, "reason": "busy", "state": row["state"], "active_cycle": row["active_cycle"]}
            if row["state"] in {COMPLETED, BLOCKED}:
                return {"reserved": False, "reason": "program_" + row["state"], "state": row["state"]}
            if row["state"] == PAUSED:
                return {"reserved": False, "reason": "paused", "state": PAUSED}
            if expired(config["deadline"], now):
                row.update(state=COMPLETED, stop_reason="deadline_expired", updated_at=now)
                tx.put(BUCKET_PROGRAMS, program_id, row)
                return {"reserved": False, "reason": "deadline_expired", "state": COMPLETED}
            if row["cycles"] >= config["max_cycles"]:
                row.update(state=COMPLETED, stop_reason="max_cycles_reached", updated_at=now)
                tx.put(BUCKET_PROGRAMS, program_id, row)
                return {"reserved": False, "reason": "max_cycles_reached", "state": COMPLETED}
            if not due(row["last_tick_at"], config["interval_seconds"], now):
                return {"reserved": False, "reason": "not_due", "state": ACTIVE, "last_tick_at": row["last_tick_at"]}
            number = row["next_cycle"]
            cycle = {"id": cycle_id(program_id, number), "program": program_id, "number": number, "owner": self.token(),
                     "status": COLLECTING, "counts": None, "sources": None, "selection": None, "budget": None,
                     "capture": None, "council": None, "result": None, "failure": None, "stop_reason": None,
                     "remaining": {"cycles": config["max_cycles"] - row["cycles"] - 1,
                                   "adoptions": config["max_adoptions"] - row["adoptions"]},
                     "started_at": now, "updated_at": now, "finished_at": None}
            require(tx.get(BUCKET_CYCLES, cycle["id"]) is None, "Research program cycle row already exists")
            tx.put(BUCKET_CYCLES, cycle["id"], cycle)
            row.update(active_cycle=cycle["id"], next_cycle=number + 1, updated_at=now)
            tx.put(BUCKET_PROGRAMS, program_id, row)
        return {"reserved": True, "reason": None, "state": ACTIVE, "cycle": cycle, "config": config}

    def _owned(self, tx, cycle_ref: str, owner: str, statuses) -> tuple[dict, dict]:
        cycle = tx.get(BUCKET_CYCLES, cycle_ref)
        if cycle is None:
            raise ProgramRefused("unknown_cycle")
        if not owner or cycle.get("owner") != owner:
            raise ProgramRefused("owner_mismatch")
        if cycle["status"] not in statuses:
            raise ProgramRefused("cycle_state_changed")
        row = self._row(tx, cycle["program"])
        if row["active_cycle"] != cycle["id"]:
            raise ProgramRefused("cycle_not_active")
        return cycle, row

    # ----- collection -------------------------------------------------------------------------
    def record_collection(self, cycle_ref: str, owner: str, sources: dict, items: list, counts: dict) -> dict:
        """Dedup, relevance, claim and the adoption reservation in ONE transaction. `sources` is the
        per-source status map (type/code only), `items` the discovered entries (source, identity, url,
        path, sha256, title, summary), `counts` the machine ledger reading. Returns the cycle.

        An investigation candidate is NEVER an ordinary discovery item: the source is refused at this
        boundary and synthesized from the authoritative transaction reads instead."""
        for item in items:
            if item.get("source") == INVESTIGATION:
                raise ProgramRefused("investigation_source_forbidden", "items[].source")
        with self.store.transaction() as tx:
            cycle, row = self._owned(tx, cycle_ref, owner, {COLLECTING})
            config, now = row["config"], self.clock()
            tally = {"discovered": len(items), "new": 0, "duplicate": 0, "ignored": 0, "eligible": 0, "selected": 0}
            program_candidates = [c for c in tx.scan(BUCKET_CANDIDATES) if c["program"] == row["id"]]
            known = {c["key"]: c for c in program_candidates}
            for item in items:
                key = candidate_key(item["source"], item["identity"])
                existing = known.get(key)
                if existing is not None:
                    tally["duplicate"] += 1
                    existing.update(last_cycle=cycle["number"], seen=existing["seen"] + 1, updated_at=now)
                    tx.put(BUCKET_CANDIDATES, existing["_key"], existing)
                    continue
                if item["source"] == "local":
                    relevance = {"topic": item["topic"], "eligible": True, "reason": "owner_authorized_local_candidate"}
                else:
                    relevance = match_topics(config["topics"], item.get("title"), item.get("summary"))
                candidate = {"id": item["id"] if item["source"] == "local" else candidate_id(key), "program": row["id"], "key": key,
                             "source": item["source"], "url": item.get("url"), "path": item.get("path"), "sha256": item.get("sha256"),
                             "title": item.get("title"), "summary": item.get("summary"), "content_sha256": item.get("content_sha256"),
                             "topic": relevance["topic"], "reason": relevance["reason"],
                             "status": ELIGIBLE if relevance["eligible"] else IGNORED, "first_cycle": cycle["number"],
                             "last_cycle": cycle["number"], "seen": 1, "claimed_cycle": None, "result": None,
                             "created_at": now, "updated_at": now}
                candidate["_key"] = row["id"] + ":" + candidate["id"]
                tally["new"] += 1
                tally["ignored" if candidate["status"] == IGNORED else "eligible"] += 1
                known[key] = candidate
                tx.put(BUCKET_CANDIDATES, candidate["_key"], candidate)
            bridge = self._investigations(tx, row, cycle, known, now)
            progress = self._audit_progress(tx, row, cycle, known, now)
            room = headroom(config["budget"], counts)
            selection = select_candidate(list(known.values()), row["adoptions"], config["max_adoptions"], room)
            chosen = selection["candidate"]
            budget = {**{k: counts.get(k) for k in ("this_host", "all_hosts", "unreadable")}, **config["budget"], "headroom": room}
            if chosen is not None:
                chosen.update(status=CLAIMED, claimed_cycle=cycle["number"], updated_at=now)
                tx.put(BUCKET_CANDIDATES, chosen["_key"], chosen)
                row["adoptions"] += 1   # every dispatched attempt counts, from the claim on
                tally["selected"] = 1
                if chosen["source"] == INVESTIGATION:
                    # The cross-program claim commits with this selection and this cycle
                    # bookkeeping. One bucket, one claim per candidate id, whatever the kind.
                    claimed = self._claim_investigation(tx, chosen, cycle, now)["investigation"]
                    receipt = progress if chosen.get("kind") == AUDIT_PROGRESS else bridge
                    receipt["claimed"] = claimed
            cycle.update(status=SELECTED if chosen else NO_SELECTION, counts=tally, sources=sources, budget=budget,
                         investigations=bridge, audit_progress=progress,
                         selection={"candidate": None if chosen is None else chosen["id"], "reason": selection["reason"],
                                    "source": None if chosen is None else chosen["source"]},
                         remaining={"cycles": cycle["remaining"]["cycles"], "adoptions": config["max_adoptions"] - row["adoptions"]},
                         updated_at=now)
            tx.put(BUCKET_CYCLES, cycle["id"], cycle)
            row.update(updated_at=now)
            tx.put(BUCKET_PROGRAMS, row["id"], row)
            return {"cycle": cycle, "candidate": None if chosen is None else {k: v for k, v in chosen.items() if k != "_key"}}

    def candidate(self, program_id: str, candidate_ref: str) -> dict | None:
        with self.store.transaction() as tx:
            row = tx.get(BUCKET_CANDIDATES, program_id + ":" + candidate_ref)
        return None if row is None else {k: v for k, v in row.items() if k != "_key"}

    # ----- investigation bridge (research-dispatch-001) ----------------------------------------
    def _investigations(self, tx, row: dict, cycle: dict, known: dict, now: str) -> dict | None:
        """Synthesize and REVALIDATE the program's investigation candidates from the authoritative
        rows in this transaction, immediately before selection. `None` when the program did not opt
        in: no portfolio bucket is read and the legacy behaviour is byte-identical. A candidate whose
        state, scope or claim changed since an earlier tick is ignored here, so an old cached entry
        can never run later; nothing in the portfolio is written."""
        source = row["config"].get("investigation_source")
        if source is None:
            return None
        claimed = {d["investigation"] for d in tx.scan(BUCKET_DISPATCHES) if type(d.get("investigation")) is str}
        # research-dispatch-recovery-001: an authorized, not yet claimed replacement is unclaimed for
        # ITS named program only; every other program still sees the failed claim.
        claimed -= {r["investigation"] for r in tx.scan(BUCKET_RECOVERIES)
                    if r.get("state") == AUTHORIZED and (r.get("replacement") or {}).get("program") == row["id"]}
        found = eligible_investigations(investigations=tx.scan(BUCKET_INVESTIGATIONS), jobs=tx.scan(BUCKET_JOBS),
                                        bindings=tx.scan(BUCKET_BINDINGS), source=source, claimed=claimed,
                                        required_state=RESEARCH_REQUIRED, minimum=FAMILY_MINIMUM)
        current, new, ineligible = {}, 0, 0
        for entry in found["candidates"]:
            key = candidate_key(INVESTIGATION, entry["investigation"])
            current[entry["investigation"]] = key
            document = snapshot(candidate=entry, program_id=row["id"], cycle_number=cycle["number"],
                                topic=source["topic"], observed_at=now)
            existing = known.get(key)
            if existing is None:
                identity = candidate_identity(entry["investigation"])
                existing = {"id": identity, "program": row["id"], "key": key, "source": INVESTIGATION, "url": None,
                            "path": None, "sha256": None, "title": None, "summary": None,
                            "content_sha256": document["job_ids_sha256"], "topic": source["topic"],
                            "reason": ELIGIBLE_REASON, "status": ELIGIBLE, "investigation": entry["investigation"],
                            "snapshot": document, "first_cycle": cycle["number"], "last_cycle": cycle["number"],
                            "seen": 1, "claimed_cycle": None, "result": None, "created_at": now, "updated_at": now,
                            "_key": row["id"] + ":" + identity}
                new += 1
                known[key] = existing
            elif existing["status"] == CLAIMED:
                continue    # its dispatch owns the investigation; a claim is never recomputed
            else:
                existing.update(status=ELIGIBLE, reason=ELIGIBLE_REASON, snapshot=document,
                                content_sha256=document["job_ids_sha256"], last_cycle=cycle["number"],
                                seen=existing["seen"] + 1, updated_at=now)
            tx.put(BUCKET_CANDIDATES, existing["_key"], existing)
        for entry in known.values():
            if (entry["source"] != INVESTIGATION or entry.get("kind") == AUDIT_PROGRESS
                    or entry["status"] != ELIGIBLE or entry.get("investigation") in current):
                continue    # another kind's candidates are owned by their own rule, never by this one
            # State, scope or a competing claim changed: drop the cached snapshot with the eligibility.
            entry.update(status=IGNORED, reason=INELIGIBLE_REASON, snapshot=None, updated_at=now)
            tx.put(BUCKET_CANDIDATES, entry["_key"], entry)
            ineligible += 1
        return {"counts": found["counts"], "new": new, "ineligible": ineligible, "claimed": None,
                "result": None, "reported_result": None}

    def _audit_progress(self, tx, row: dict, cycle: dict, known: dict, now: str) -> dict | None:
        """Synthesize and REVALIDATE this program's audit-progress candidates from the authoritative
        rows in this transaction, immediately before selection. `None` when the program did not opt
        in: no progress bucket is read and the legacy behaviour is byte-identical.

        The candidate row, its epoch and BOTH completed windows are re-read here, so a candidate
        whose owner disposition, epoch, policy digest, window membership or authorized audit changed
        since an earlier tick simply stops being eligible and its cached snapshot is dropped. A
        discovery item can never forge one: nothing outside these reads reaches this rule, and
        nothing in the portfolio, the audit or its windows is written.
        """
        source = row["config"].get("audit_progress_source")
        if source is None:
            return None
        claimed = {d["investigation"] for d in tx.scan(BUCKET_DISPATCHES) if type(d.get("investigation")) is str}
        found = eligible_candidates(candidates=tx.scan(BUCKET_INVESTIGATIONS),
                                    windows=tx.scan(BUCKET_PROGRESS_WINDOWS),
                                    states=tx.scan(BUCKET_PROGRESS_STATE), source=source, claimed=claimed,
                                    required_state=RESEARCH_REQUIRED,
                                    policy_sha256=self.progress_policy_sha256)
        current, new, ineligible = {}, 0, 0
        for entry in found["candidates"]:
            candidate, identifier = entry["candidate"], entry["candidate"]["id"]
            key = candidate_key(INVESTIGATION, identifier)
            current[identifier] = key
            document = progress_snapshot(candidate=candidate, windows=entry["windows"], program_id=row["id"],
                                         cycle_number=cycle["number"], topic=source["topic"], observed_at=now)
            existing = known.get(key)
            if existing is None:
                short = progress_label(identifier)
                existing = {"id": short, "program": row["id"], "key": key, "source": INVESTIGATION,
                            "kind": AUDIT_PROGRESS, "url": None, "path": None, "sha256": None, "title": None,
                            "summary": None, "content_sha256": document["windows"][-1]["members_sha256"],
                            "topic": source["topic"], "reason": PROGRESS_ELIGIBLE_REASON, "status": ELIGIBLE,
                            "investigation": identifier, "audit_id": candidate["audit_id"],
                            "epoch": candidate["epoch"], "snapshot": document, "first_cycle": cycle["number"],
                            "last_cycle": cycle["number"], "seen": 1, "claimed_cycle": None, "result": None,
                            "created_at": now, "updated_at": now, "_key": row["id"] + ":" + short}
                new += 1
                known[key] = existing
            elif existing["status"] == CLAIMED:
                continue    # its dispatch owns the candidate; a claim is never recomputed
            else:
                existing.update(status=ELIGIBLE, reason=PROGRESS_ELIGIBLE_REASON, snapshot=document,
                                content_sha256=document["windows"][-1]["members_sha256"],
                                last_cycle=cycle["number"], seen=existing["seen"] + 1, updated_at=now)
            tx.put(BUCKET_CANDIDATES, existing["_key"], existing)
        for entry in known.values():
            if (entry.get("kind") != AUDIT_PROGRESS or entry["status"] != ELIGIBLE
                    or entry.get("investigation") in current):
                continue
            entry.update(status=IGNORED, reason=PROGRESS_INELIGIBLE_REASON, snapshot=None, updated_at=now)
            tx.put(BUCKET_CANDIDATES, entry["_key"], entry)
            ineligible += 1
        return {"counts": found["counts"], "new": new, "ineligible": ineligible, "claimed": None,
                "result": None, "reported_result": None, "policy_sha256": self.progress_policy_sha256}

    def _claim_investigation(self, tx, chosen: dict, cycle: dict, now: str) -> dict:
        """The durable cross-program claim, keyed solely by investigation id. A row that appeared in
        the meantime refuses the whole transaction: two programs and two workers cannot both claim."""
        document = chosen.get("snapshot")
        require(isinstance(document, dict) and document.get("investigation") == chosen["investigation"],
                "Research investigation candidate must carry its snapshot")
        dispatch = dispatch_row(document=document, candidate_id=chosen["id"], cycle_ref=cycle["id"], now=now)
        recovery = tx.get(BUCKET_RECOVERIES, chosen["investigation"])
        if (isinstance(recovery, dict) and recovery.get("state") == AUTHORIZED
                and recovery["replacement"]["program"] == cycle["program"]):
            # The ONE replacement: its own key, bound to the lineage and the failed identity it
            # supersedes; the failed row is never rewritten. The lineage records the claim here, in
            # the same transaction, so a repeat, a restart or a concurrent tick cannot claim twice.
            dispatch.update(id=recovery["replacement"]["dispatch"], recovery=recovery["id"],
                            supersedes={"dispatch": chosen["investigation"], **recovery["failed"]})
            recovery.update(state=RECOVERED, claimed_at=now, updated_at=now,
                            replacement={**recovery["replacement"], "cycle": cycle["id"]})
            tx.put(BUCKET_RECOVERIES, recovery["id"], recovery)
        if tx.get(BUCKET_DISPATCHES, dispatch["id"]) is not None:
            raise ProgramRefused("investigation_already_claimed")
        tx.put(BUCKET_DISPATCHES, dispatch["id"], dispatch)
        return dispatch

    def _dispatch(self, tx, row: dict, cycle: dict) -> dict | None:
        """This cycle's dispatch row, or None when the cycle did not claim an investigation."""
        selected = (cycle.get("selection") or {}).get("candidate")
        if selected is None:
            return None
        candidate = tx.get(BUCKET_CANDIDATES, row["id"] + ":" + selected)
        if candidate is None or candidate.get("source") != INVESTIGATION:
            return None
        investigation = candidate["investigation"]
        dispatch = tx.get(BUCKET_DISPATCHES, current_dispatch_id(investigation, tx.get(BUCKET_RECOVERIES, investigation)))
        if dispatch is None or dispatch.get("cycle") != cycle["id"] or dispatch.get("program") != row["id"]:
            return None   # another program's claim is never rewritten from this cycle
        return dispatch

    def dispatches(self, program_id: str | None = None) -> list:
        """Bounded read-only projection of the claims; no config, prompt, output or error text.
        `current` marks the one row that answers for its investigation now: a failed original that
        was replaced stays listed as history with `current` False."""
        with self.store.transaction() as tx:
            rows = tx.scan(BUCKET_DISPATCHES)
            recoveries = {r["investigation"]: r for r in tx.scan(BUCKET_RECOVERIES)}
        return [{**dispatch_view(r),
                 "current": r.get("id", r["investigation"]) == current_dispatch_id(r["investigation"],
                                                                                   recoveries.get(r["investigation"]))}
                for r in sorted(rows, key=lambda r: (r["investigation"], r.get("id", r["investigation"])))
                if program_id is None or r.get("program") == program_id]

    # ----- failed-dispatch recovery (research-dispatch-recovery-001) -----------------------------
    def recover_dispatch(self, document, transport) -> dict:
        """Authorize ONE replacement of a proven pre-provider failed investigation dispatch for a NEW
        registered program. Three steps, no transaction across the transport read:

        1. one transaction re-reads every authoritative record (`check_recovery`) and, on the first
           request, fences the failed run's unsent assignment through the existing outbox quarantine
           (source copy retained, `sent` untouched, never claimed as sent) and records the lineage
           row `fenced`, so no relay can publish it after this point;
        2. `transport.absent(recipient, message_id)` inspects the configured transport for that
           exact message; a delivery error before the fence may still have delivered it, so a
           timeout alone is never proof. Unavailable proof refuses and the row stays `fenced`;
        3. one transaction re-reads every record again and moves `fenced` -> `authorized`, or
           records the durable refusal when the message is present.

        The identical request replays (`cached`); any other for the same investigation is
        `recovery_conflict`: one recovery per investigation, ever, and a failed replacement is held.
        Nothing is deleted, no failed row becomes accepted and no model or council runs here."""
        try:
            request = validate_recovery_request(document)
        except InvestigationRefused as exc:
            raise ProgramRefused(exc.reason_code, exc.field) from exc
        request_sha = digest(request)
        investigation = request["investigation"]
        with self.store.transaction() as tx:
            row = self._recovery_row(tx, investigation, request_sha)
            if row is not None and row["state"] != FENCED:
                return self._recovery_result(row, cached=True)
            proof = self._recovery_check(tx, request, None if row is None else row["fence"])
            if row is None:
                now = self.clock()
                item = tx.get("outbox", proof["message_id"])
                quarantine_outbox(tx, proof["message_id"], item, proof["source_hash"], FENCE_REASON,
                                  tx.get("outbox_delivery", proof["message_id"]) or {})
                row = {"id": investigation, "investigation": investigation, "state": FENCED, "reason_code": None,
                       "request": request, "request_sha256": request_sha, "failed": dict(request["failed"]),
                       "replacement": {**request["replacement"], "dispatch": replacement_dispatch_id(investigation),
                                       "cycle": None},
                       "fence": {"outbox": proof["message_id"], "source_hash": proof["source_hash"],
                                 "attempts": proof["attempts"], "reason": FENCE_REASON},
                       "requested_at": now, "authorized_at": None, "claimed_at": None, "updated_at": now}
                tx.put(BUCKET_RECOVERIES, investigation, row)
        try:
            absent = transport.absent(proof["recipient"], proof["message_id"])
        except Exception as exc:
            raise ProgramRefused("recovery_transport_unavailable") from exc
        refused = None
        with self.store.transaction() as tx:
            row = self._recovery_row(tx, investigation, request_sha)
            if row["state"] != FENCED:
                return self._recovery_result(row, cached=True)   # a concurrent request finished first
            self._recovery_check(tx, request, row["fence"])
            now = self.clock()
            if absent is not True:
                refused = "recovery_message_delivered"
                row.update(state=REFUSED, reason_code=refused, updated_at=now)
            else:
                row.update(state=AUTHORIZED, authorized_at=now, updated_at=now)
            tx.put(BUCKET_RECOVERIES, investigation, row)
        if refused is not None:
            raise ProgramRefused(refused)
        return self._recovery_result(row, cached=False)

    @staticmethod
    def _recovery_row(tx, investigation: str, request_sha: str) -> dict | None:
        row = tx.get(BUCKET_RECOVERIES, investigation)
        if row is None:
            return None
        if row.get("request_sha256") != request_sha:
            raise ProgramRefused("recovery_conflict")
        if row["state"] == REFUSED:
            raise ProgramRefused(row["reason_code"])
        return row

    def _recovery_check(self, tx, request: dict, fence) -> dict:
        """The authoritative reads of one recovery, checked by the pure domain rule."""
        failed, investigation = request["failed"], request["investigation"]
        program = tx.get(BUCKET_PROGRAMS, failed["program"])
        replacement = tx.get(BUCKET_PROGRAMS, request["replacement"]["program"])
        dispatch, run = tx.get(BUCKET_DISPATCHES, investigation), tx.get(BUCKET_RUNS, failed["run_id"])
        correlation = "autonomous:" + failed["run_id"]
        outbox = [item for item in tx.scan("outbox")
                  if isinstance(item, dict) and (item.get("message") or {}).get("correlation_id") == correlation]
        ids = {(item.get("message") or {}).get("message_id") for item in outbox}
        ids.discard(None)
        message_id = next(iter(ids)) if len(ids) == 1 else None
        try:
            return check_recovery(
                request, investigation=tx.get(BUCKET_INVESTIGATIONS, investigation), required_state=RESEARCH_REQUIRED,
                dispatch=dispatch, program=program, cycle=tx.get(BUCKET_CYCLES, failed["cycle"]),
                run_result=council_result(failed["run_id"], failed["manifest_sha256"], run), run=run, outbox=outbox,
                tasks=[i for i in ids if tx.get("tasks", i) is not None],
                reservations=[r for r in tx.scan(RESERVATIONS) if r.get("task_id") in ids],
                residue=[k for b, k in ((SESSIONS, failed["run_id"] + ".design"), (OPERATIONS, failed["run_id"] + ".impl"))
                         if tx.get(b, k) is not None],
                delivery=tx.get("outbox_delivery", message_id) if message_id else None,
                attempts=[a for a in tx.scan("outbox_attempts") if message_id and a.get("outbox_id") == message_id],
                replacement=replacement,
                same_authority=isinstance(program, dict) and isinstance(replacement, dict)
                and same_authority(program["config"], replacement["config"]),
                fence=fence)
        except InvestigationRefused as exc:
            raise ProgramRefused(exc.reason_code, exc.field) from exc

    @staticmethod
    def _recovery_result(row: dict, cached: bool) -> dict:
        return {"recovered": row["state"] in {AUTHORIZED, RECOVERED}, "cached": cached, **recovery_view(row)}

    # ----- capture and council ----------------------------------------------------------------
    def record_capture(self, cycle_ref: str, owner: str, capture: dict) -> dict:
        with self.store.transaction() as tx:
            cycle, row = self._owned(tx, cycle_ref, owner, {SELECTED})
            cycle.update(status=CAPTURED, capture=capture, updated_at=self.clock())
            tx.put(BUCKET_CYCLES, cycle["id"], cycle)
            return cycle

    def record_council_start(self, cycle_ref: str, owner: str, run_id: str, manifest_sha256: str, manifest_ref: str) -> dict:
        """Persisted BEFORE the council starts: the run id, manifest digest and its stored reference.
        An investigation dispatch is bound to that EXACT run and manifest digest here, so its result
        can only ever be read back from the run row it actually started."""
        with self.store.transaction() as tx:
            cycle, row = self._owned(tx, cycle_ref, owner, {CAPTURED})
            now = self.clock()
            cycle.update(status=COUNCIL, updated_at=now,
                         council={"run_id": run_id, "manifest_sha256": manifest_sha256, "manifest_ref": manifest_ref,
                                  "status": "started", "reason_code": None, "row_status": None, "started_at": now})
            dispatch = self._dispatch(tx, row, cycle)
            if dispatch is not None:
                dispatch.update(state=DISPATCHED, run_id=run_id, manifest_sha256=manifest_sha256,
                                manifest_ref=manifest_ref, started_at=now, updated_at=now)
                tx.put(BUCKET_DISPATCHES, dispatch["id"], dispatch)
            tx.put(BUCKET_CYCLES, cycle["id"], cycle)
            return cycle

    def record_council_result(self, cycle_ref: str, owner: str, verdict: dict) -> dict:
        """`verdict` comes from `council_result` over the authoritative run row. accepted/rejected
        complete the cycle; failed/unknown complete it AND block the program. The claimed candidate
        keeps its claim and records the result either way."""
        result = verdict["result"]
        require(result in RESULTS, "Research program council result must be accepted, rejected, failed or unknown")
        with self.store.transaction() as tx:
            cycle, row = self._owned(tx, cycle_ref, owner, {COUNCIL})
            now = self.clock()
            cycle["council"].update(status=result, reason_code=verdict.get("reason_code"), row_status=verdict.get("row_status"),
                                    finished_at=now)
            candidate = tx.get(BUCKET_CANDIDATES, row["id"] + ":" + cycle["selection"]["candidate"])
            if candidate is not None:
                candidate.update(result=result, updated_at=now)
                tx.put(BUCKET_CANDIDATES, candidate["_key"], candidate)
            self._record_dispatch_result(tx, row, cycle, verdict, now)
            blocked = result in {"failed", "unknown"}
            self._close(tx, cycle, row, now, result=result, stop_reason="council_" + result if blocked else None,
                        blocked_reason="council_" + result + ":" + safe_code(verdict.get("reason_code")) if blocked else None)
            return cycle

    def _record_dispatch_result(self, tx, row: dict, cycle: dict, verdict: dict, now: str) -> dict | None:
        """The dispatch outcome comes from the authoritative `autonomous_runs` row read INSIDE this
        transaction and validated by the existing `council_result` helper against the bound run id and
        manifest digest. The caller's verdict is kept only as `reported_result`, an unverified claim:
        a missing, mismatched or still running row stays `unknown`, never accepted. The claim is never
        released and this is a dispatch outcome only - not an owner disposition, not a resolved
        incident and not a promotion."""
        dispatch = self._dispatch(tx, row, cycle)
        if dispatch is None:
            return None
        run = tx.get(BUCKET_RUNS, dispatch["run_id"]) if dispatch.get("run_id") else None
        authoritative = (council_result(dispatch["run_id"], dispatch["manifest_sha256"], run) if dispatch.get("run_id")
                         else {"result": "unknown", "reason_code": "dispatch_not_started", "row_status": None})
        dispatch.update(state=RESOLVED, result=authoritative["result"], result_reason=authoritative["reason_code"],
                        row_status=authoritative["row_status"], reported_result=safe_code(verdict.get("result")),
                        finished_at=now, updated_at=now)
        tx.put(BUCKET_DISPATCHES, dispatch["id"], dispatch)
        self._project_dispatch(cycle, dispatch)
        return dispatch

    @staticmethod
    def _project_dispatch(cycle: dict, dispatch: dict) -> None:
        """The cycle receipt carries the dispatch outcome beside the council outcome, so a status or
        report reader sees a dispatch that is NOT an acceptance without reading another bucket. The
        outcome lands on the receipt of the kind that was actually claimed."""
        name = "audit_progress" if dispatch.get("kind") == AUDIT_PROGRESS else "investigations"
        if isinstance(cycle.get(name), dict):
            cycle[name].update(result=dispatch["result"], reported_result=dispatch.get("reported_result"))

    def complete_cycle(self, cycle_ref: str, owner: str) -> dict:
        """A collection-only tick (nothing selected) ends here: counted, never a dispatch."""
        with self.store.transaction() as tx:
            cycle, row = self._owned(tx, cycle_ref, owner, {NO_SELECTION})
            self._close(tx, cycle, row, self.clock(), result=None)
            return cycle

    def fail_cycle(self, cycle_ref: str, owner: str, stage: str, code: str, recovery: dict | None = None) -> dict:
        """Evidence, Git, capture, manifest or council-start failure: persisted with stage and fixed
        code, the cycle counted, the program blocked; the claimed candidate stays claimed and any
        recorded capture reference stays on the cycle AND in `failure.recovery` (review001 R2).
        A store failure here propagates: the caller must then keep ownership and report inability."""
        with self.store.transaction() as tx:
            cycle, row = self._owned(tx, cycle_ref, owner, {COLLECTING, SELECTED, CAPTURED, COUNCIL})
            capture = cycle.get("capture") or {}
            retained = {k: capture.get(k) for k in ("revision", "ref", "path", "blob", "sha256")} if capture else None
            cycle["failure"] = {"stage": stage, "code": safe_code(code), "recovery": recovery, "capture": retained}
            now = self.clock()
            dispatch = self._dispatch(tx, row, cycle)
            if dispatch is not None:
                # A failed dispatch KEEPS its claim: nothing is released, retried or cleaned up here.
                dispatch.update(state=RESOLVED, result="failed", result_reason=safe_code(code),
                                failure={"stage": stage, "code": safe_code(code)}, finished_at=now, updated_at=now)
                tx.put(BUCKET_DISPATCHES, dispatch["id"], dispatch)
                self._project_dispatch(cycle, dispatch)
            self._close(tx, cycle, row, now, result="failed" if cycle["status"] == COUNCIL else None,
                        status=CYCLE_FAILED, stop_reason="failed:" + stage, blocked_reason=stage + ":" + safe_code(code))
            return cycle

    def _close(self, tx, cycle, row, now, *, result, status=CYCLE_DONE, stop_reason=None, blocked_reason=None):
        config = row["config"]
        row["cycles"] += 1
        row.update(active_cycle=None, last_tick_at=now, updated_at=now)
        if blocked_reason is not None:
            row.update(state=BLOCKED, blocked_reason=blocked_reason, stop_reason=stop_reason)
        elif row["cycles"] >= config["max_cycles"]:
            row.update(state=COMPLETED, stop_reason="max_cycles_reached")
            stop_reason = "max_cycles_reached"
        cycle.update(status=status, result=result, stop_reason=stop_reason, updated_at=now, finished_at=now,
                     remaining={"cycles": config["max_cycles"] - row["cycles"], "adoptions": config["max_adoptions"] - row["adoptions"]})
        tx.put(BUCKET_CYCLES, cycle["id"], cycle)
        tx.put(BUCKET_PROGRAMS, row["id"], row)

    # ----- read-only ----------------------------------------------------------------------------
    def status(self, program_id: str) -> dict:
        with self.store.transaction() as tx:
            row = self._row(tx, program_id)
            cycles = [c for c in tx.scan(BUCKET_CYCLES) if c["program"] == program_id]
            candidates = [c for c in tx.scan(BUCKET_CANDIDATES) if c["program"] == program_id]
            dispatches = [d for d in tx.scan(BUCKET_DISPATCHES) if d.get("program") == program_id]
            recoveries = [r for r in tx.scan(BUCKET_RECOVERIES)
                          if program_id in {r["failed"]["program"], r["replacement"]["program"]}]
        return program_view(row, cycles, candidates, dispatches, recoveries)

    def candidates(self, program_id: str) -> list:
        with self.store.transaction() as tx:
            rows = [c for c in tx.scan(BUCKET_CANDIDATES) if c["program"] == program_id]
        return [{k: v for k, v in c.items() if k != "_key"} for c in rows]

    def monitor(self) -> dict:
        with self.store.transaction() as tx:
            programs, cycles = tx.scan(BUCKET_PROGRAMS), tx.scan(BUCKET_CYCLES)
        return monitor_projection(programs, cycles)


__all__ = ["BUCKET_CANDIDATES", "BUCKET_CYCLES", "BUCKET_DISPATCHES", "BUCKET_PROGRAMS", "BUCKET_RECOVERIES",
           "ResearchProgram"]
