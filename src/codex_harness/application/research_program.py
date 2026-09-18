"""Research program state machine over the existing store (INV-RESEARCH-PROGRAM-001).

Three buckets: `research_programs` (immutable config, digest, durable counters and state),
`research_program_candidates` (dedup identity across cycles, relevance reason, claim and result) and
`research_program_cycles` (one receipt per reserved cycle). Every state change is one store
transaction that re-reads the row it expects; no transaction stays open across network, Git or
provider work: the adapter reserves, then fetches, then records. A reserved cycle stays owned until
its owner records a terminal fact; a crash leaves it owned and the program busy, never assumed empty.
Counters never reset: the adoption cap counts every dispatched council, accepted or not.
"""
from __future__ import annotations

from uuid import uuid4

from codex_harness.domain.model import require, utcnow
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
    cycle_id,
    due,
    expired,
    headroom,
    match_topics,
    monitor_projection,
    program_view,
    safe_code,
    select_candidate,
)

BUCKET_PROGRAMS, BUCKET_CANDIDATES, BUCKET_CYCLES = ("research_programs", "research_program_candidates",
                                                     "research_program_cycles")


class ResearchProgram:
    def __init__(self, store, clock=utcnow, token=lambda: uuid4().hex):
        self.store, self.clock, self.token = store, clock, token

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
        path, sha256, title, summary), `counts` the machine ledger reading. Returns the cycle."""
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
            room = headroom(config["budget"], counts)
            selection = select_candidate(list(known.values()), row["adoptions"], config["max_adoptions"], room)
            chosen = selection["candidate"]
            budget = {**{k: counts.get(k) for k in ("this_host", "all_hosts", "unreadable")}, **config["budget"], "headroom": room}
            if chosen is not None:
                chosen.update(status=CLAIMED, claimed_cycle=cycle["number"], updated_at=now)
                tx.put(BUCKET_CANDIDATES, chosen["_key"], chosen)
                row["adoptions"] += 1   # every dispatched attempt counts, from the claim on
                tally["selected"] = 1
            cycle.update(status=SELECTED if chosen else NO_SELECTION, counts=tally, sources=sources, budget=budget,
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

    # ----- capture and council ----------------------------------------------------------------
    def record_capture(self, cycle_ref: str, owner: str, capture: dict) -> dict:
        with self.store.transaction() as tx:
            cycle, row = self._owned(tx, cycle_ref, owner, {SELECTED})
            cycle.update(status=CAPTURED, capture=capture, updated_at=self.clock())
            tx.put(BUCKET_CYCLES, cycle["id"], cycle)
            return cycle

    def record_council_start(self, cycle_ref: str, owner: str, run_id: str, manifest_sha256: str, manifest_ref: str) -> dict:
        """Persisted BEFORE the council starts: the run id, manifest digest and its stored reference."""
        with self.store.transaction() as tx:
            cycle, row = self._owned(tx, cycle_ref, owner, {CAPTURED})
            cycle.update(status=COUNCIL, updated_at=self.clock(),
                         council={"run_id": run_id, "manifest_sha256": manifest_sha256, "manifest_ref": manifest_ref,
                                  "status": "started", "reason_code": None, "row_status": None, "started_at": self.clock()})
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
            blocked = result in {"failed", "unknown"}
            self._close(tx, cycle, row, now, result=result, stop_reason="council_" + result if blocked else None,
                        blocked_reason="council_" + result + ":" + safe_code(verdict.get("reason_code")) if blocked else None)
            return cycle

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
            self._close(tx, cycle, row, self.clock(), result="failed" if cycle["status"] == COUNCIL else None,
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
        return program_view(row, cycles, candidates)

    def candidates(self, program_id: str) -> list:
        with self.store.transaction() as tx:
            rows = [c for c in tx.scan(BUCKET_CANDIDATES) if c["program"] == program_id]
        return [{k: v for k, v in c.items() if k != "_key"} for c in rows]

    def monitor(self) -> dict:
        with self.store.transaction() as tx:
            programs, cycles = tx.scan(BUCKET_PROGRAMS), tx.scan(BUCKET_CYCLES)
        return monitor_projection(programs, cycles)


__all__ = ["BUCKET_CANDIDATES", "BUCKET_CYCLES", "BUCKET_PROGRAMS", "ResearchProgram"]
