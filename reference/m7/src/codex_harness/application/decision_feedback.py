"""Bounded read/collect/report over existing decision and outcome records (INV-DECISION-FEEDBACK-001).

`collect` pages the immutable `autonomous_runs` ids in ascending order, joins each run with the
executor-owned debate session, the conductor's decision event, that event's task row and the stored
execution artifact those rows reference, and records one unverified observation per proven run. Exact
contract equality groups runs; a Git-pinned registry turns a group of two distinct run identities into
one advisory candidate that says `needs_analysis`.

The artifact is read through the injected `ExecutionEvidence` port and checked by the existing
`execution_evidence` rule against the authoritative `invocation_reservations` row, so a row whose
`execution_ref` string merely matches earns no evidence credit. Before a recorded terminal outcome is
called a conflict, the run row is re-read inside the write transaction: a page that went stale between
the read and the record is reported as stale, never as a changed source history.

Only four buckets are written — `decision_observations`, `decision_feedback_groups`,
`recurring_work_candidates`, `decision_feedback_conflicts` — plus the collection receipt. No source
row, task, incident, verified graph node, hook or release is read for writing or written at all, no
model or network is used, and nothing here activates, promotes or dispatches anything.
"""
from __future__ import annotations

from codex_harness.application.autonomous import BUCKET as RUNS
from codex_harness.application.autonomous import RESERVATIONS
from codex_harness.application.dge import EVENTS, SESSIONS
from codex_harness.domain.autonomous import evidence_ref_for, execution_evidence
from codex_harness.domain.decision_feedback import (
    ARTIFACT_REASONS,
    CANDIDATE_SCHEMA,
    COLLECTION_AUTHORITY,
    COLLECTION_SCHEMA,
    DECIDING_ROLE,
    DECISION_SLOT,
    DEFAULT_SCAN,
    EVIDENCE_VERIFIED,
    LIMITS,
    MAX_OUTCOME_HISTORY,
    OCCURRENCE_THRESHOLD,
    OUTCOME_STATES,
    REPORT_SCHEMA,
    DecisionFeedbackError,
    add_member,
    candidate_body,
    candidate_id,
    conflict_body,
    match_registry,
    observation_body,
    occurrence_window,
    outcome_facts,
    quality_facts,
    registry_pin,
    scan_limit,
    source_kind_of,
    validate_registry,
    verified_binding,
    work_contract,
)
from codex_harness.domain.model import ContractError, digest, utcnow

TASKS = "tasks"
OBSERVATIONS = "decision_observations"
GROUPS = "decision_feedback_groups"
CANDIDATES = "recurring_work_candidates"
CONFLICTS = "decision_feedback_conflicts"
COLLECTIONS = "decision_feedback_collections"
READ_BUCKETS = (RUNS, SESSIONS, EVENTS, TASKS, RESERVATIONS)
WRITE_BUCKETS = (OBSERVATIONS, GROUPS, CANDIDATES, CONFLICTS, COLLECTIONS)


class DecisionFeedback:
    """`evidence` is the execution-evidence port (`document(ref) -> artifact`) the executor's own
    artifacts are read through; `collect` refuses without it, because no observation can earn evidence
    credit from rows alone. `status` and `report` read this collector's own buckets and need none."""

    def __init__(self, store, clock=utcnow, *, evidence=None):
        self.store, self.clock, self.evidence = store, clock, evidence

    # ----- collect --------------------------------------------------------------------------
    def collect(self, *, registry: dict, registry_revision: str, registry_path: str, registry_sha256: str,
                repository: str, limit: int = DEFAULT_SCAN, after: str = "") -> dict:
        """One explicit bounded collection. A store failure is `source_unavailable`, never an empty
        result; a truncated scan reports its continuation cursor."""
        if self.evidence is None:
            raise DecisionFeedbackError("evidence_port_unavailable")
        registry = validate_registry(registry)
        pin = registry_pin(registry_revision, registry_path, registry_sha256)
        limit = scan_limit(limit)
        if not (isinstance(repository, str) and repository.strip()):
            raise DecisionFeedbackError("repository_unknown")
        if not isinstance(after, str):
            raise DecisionFeedbackError("invalid_cursor")
        page = self._read(after, limit, registry, repository)
        return self._record(page, pin, registry, registry_sha256, repository, self.clock())

    def _read(self, after: str, limit: int, registry: dict, repository: str) -> dict:
        """One read transaction: the bounded page of run ids and every join it needs."""
        try:
            with self.store.transaction() as tx:
                rows = tx.entries(RUNS, after, limit + 1)  # one extra row proves truncation only
                scanned = rows[:limit]
                joined = [self._join(tx, entry.get("body") or {}, registry, repository) for entry in scanned]
        except DecisionFeedbackError:
            raise
        except Exception as exc:  # a store, driver or transport failure is unavailable, not zero samples
            raise DecisionFeedbackError("source_unavailable") from exc
        return {"joined": joined, "truncated": len(rows) > limit,
                "next_cursor": scanned[-1]["id"] if len(rows) > limit and scanned else None,
                "scanned": len(scanned), "after": after, "limit": limit}

    def _join(self, tx, run: dict, registry: dict, repository: str) -> dict:
        """Read-only join of one run. Anything unproven is an explicit reason code and no evidence
        credit; a refusal here writes nothing and never repairs, defaults or infers a field."""
        run_id = run.get("id")
        if not isinstance(run_id, str) or not run_id:
            return {"run_id": None, "reason": "run_identity_unknown", "observation": None, "match": None}
        identity = run.get("identity") if isinstance(run.get("identity"), dict) else {}
        run_repository = identity.get("repository")
        if not (isinstance(run_repository, str) and run_repository):
            return {"run_id": run_id, "reason": "run_identity_unknown", "observation": None, "match": None}
        if run_repository != repository:
            # Another repository's run is never grouped with this one; it is not an unknown sample.
            return {"run_id": run_id, "reason": "foreign_repository", "observation": None, "match": None}
        source_kind = source_kind_of(run)
        if source_kind is None:
            return {"run_id": run_id, "reason": "source_kind_unknown", "observation": None, "match": None}
        session = tx.get(SESSIONS, run.get("session_id")) if isinstance(run.get("session_id"), str) else None
        event = None
        if isinstance(session, dict):
            recorded = [h.get("event_id") for h in (session.get("history") or [])
                        if isinstance(h, dict) and h.get("role") == DECISION_SLOT and h.get("event_id")]
            if recorded:
                event = tx.get(EVENTS, session["id"] + ":" + recorded[-1])
        binding = (run.get("roles") or {}).get(DECIDING_ROLE) if isinstance(run.get("roles"), dict) else None
        task = tx.get(TASKS, (event or {}).get("binding", {}).get("task_id")) \
            if isinstance(event, dict) and isinstance((event.get("binding") or {}).get("task_id"), str) else None
        proven = verified_binding(run, session or {}, event or {}, task or {}, binding, source_kind)
        if proven["reason"] != EVIDENCE_VERIFIED:
            return {"run_id": run_id, "reason": proven["reason"], "observation": None, "match": None}
        artifact = self._artifact_evidence(tx, task, proven["binding"], session)
        if artifact["reason"] != EVIDENCE_VERIFIED:
            return {"run_id": run_id, "reason": artifact["reason"], "observation": None, "match": None}
        try:
            contract = work_contract(run_repository, source_kind, session.get("plan"))
        except DecisionFeedbackError as exc:
            return {"run_id": run_id, "reason": exc.reason_code, "observation": None, "match": None}
        observation = observation_body(run, session, event, proven["binding"], contract, source_kind=source_kind,
                                       artifact=artifact["evidence"])
        return {"run_id": run_id, "reason": EVIDENCE_VERIFIED, "observation": observation,
                "match": match_registry(contract, registry)}

    def _artifact_evidence(self, tx, task: dict, binding: dict, session: dict) -> dict:
        """The stored execution artifact behind this decision's `execution_ref`, read through the
        injected port and checked by the existing `execution_evidence` rule against the authoritative
        reservation row: the artifact must carry this task's own exact answer, that answer must hash to
        the binding's `output_sha256`, and its invocation must be the settled accepted reservation of
        this task, generation, attempt and conductor stage at the session's base revision. Bytes that
        no longer hash to the reference, a missing artifact and another execution's artifact are three
        different fixed codes and none of them is evidence credit."""
        try:
            artifact = self.evidence.document(binding["execution_ref"])
        except ContractError as exc:
            return {"reason": ARTIFACT_REASONS.get(getattr(exc, "reason_code", ""), "decision_artifact_invalid"),
                    "evidence": None}
        except Exception:  # a port without fixed codes: an absent artifact, never a proven one
            return {"reason": "decision_artifact_missing", "evidence": None}
        reservation_id = (artifact.get("invocation") or {}).get("reservation") if isinstance(artifact, dict) else None
        reservation = tx.get(RESERVATIONS, reservation_id) if isinstance(reservation_id, str) else None
        details = ((task.get("message") or {}).get("what") or {}).get("details") if isinstance(task, dict) else None
        try:
            proven = execution_evidence(task, artifact, reservation, bucket=TASKS, stage=binding.get("stage"),
                                        basis_revision=session.get("base_revision"),
                                        evidence_ref=evidence_ref_for(details) if isinstance(details, dict) else None,
                                        exact=True)
        except ContractError:
            return {"reason": "decision_artifact_unproven", "evidence": None}
        if proven["output_sha256"] != binding.get("output_sha256"):
            return {"reason": "decision_artifact_unproven", "evidence": None}
        return {"reason": EVIDENCE_VERIFIED,
                "evidence": {"execution_ref": binding["execution_ref"], "output_sha256": proven["output_sha256"],
                             "reservation_id": proven["reservation_id"], "provider": proven["provider"],
                             "verified": True, "port": "execution_evidence"}}

    def _record(self, page: dict, pin: dict, registry: dict, registry_sha256: str, repository: str, now: str) -> dict:
        """One write transaction: observations, contract groups, candidates and conflicts commit
        together, so concurrent collectors serialize on the store's transaction contract."""
        counts = {"scanned": page["scanned"], "eligible": 0, "unknown": 0, "foreign_repository": 0,
                  "observations_recorded": 0, "observations_updated": 0, "observations_unchanged": 0,
                  "observations_stale": 0, "conflicts": 0, "candidates_created": 0, "candidates_updated": 0}
        reasons, candidates = {}, []
        with self.store.transaction() as tx:
            for joined in page["joined"]:
                if joined["reason"] != EVIDENCE_VERIFIED:
                    counts["foreign_repository" if joined["reason"] == "foreign_repository" else "unknown"] += 1
                    reasons[joined["reason"]] = reasons.get(joined["reason"], 0) + 1
                    continue
                recorded = self._store_observation(tx, joined["observation"], counts, now)
                observation = recorded["observation"]
                if observation is None:
                    if recorded["reason"] == "source_history_conflict":
                        counts["conflicts"] += 1
                    else:
                        counts["unknown"] += 1
                    reasons[recorded["reason"]] = reasons.get(recorded["reason"], 0) + 1
                    continue
                group = self._store_group(tx, observation, now)
                match = joined["match"]
                if not match["matched"]:
                    counts["unknown"] += 1
                    reasons[match["reason"]] = reasons.get(match["reason"], 0) + 1
                    continue
                counts["eligible"] += 1
                reasons["matched"] = reasons.get("matched", 0) + 1
                candidate = self._store_candidate(tx, group, match, pin, registry_sha256, repository, counts, now)
                if candidate is not None and candidate["id"] not in [c["id"] for c in candidates]:
                    candidates.append({"id": candidate["id"], "procedure_id": candidate["procedure_id"],
                                       "status": candidate["status"], "distinct_runs": candidate["distinct_runs"]})
            receipt = {"schema": COLLECTION_SCHEMA,
                       "id": "collection:" + digest({"repository": repository, "registry": {**pin, "sha256": registry_sha256,
                                                                                            "digest": digest(registry)},
                                                     "after": page["after"], "limit": page["limit"],
                                                     "observed": sorted((j["run_id"], j["reason"],
                                                                         (j["observation"] or {}).get("outcome_sha256"))
                                                                        for j in page["joined"] if j["run_id"])}),
                       "repository": repository, "registry": {**pin, "sha256": registry_sha256, "digest": digest(registry),
                                                              "entries": len(registry["entries"])},
                       "counts": counts, "reasons": reasons, "candidates": candidates,
                       "truncated": page["truncated"], "next_cursor": page["next_cursor"],
                       "scan_limit": page["limit"], "after": page["after"], "collected_at": now,
                       "authority": COLLECTION_AUTHORITY, "limits": list(LIMITS)}
            tx.put(COLLECTIONS, receipt["id"], receipt)
        return receipt

    def _store_observation(self, tx, observed: dict, counts: dict, now: str) -> dict:
        """Immutable decision facts. A changed decision, or a changed history after a terminal outcome,
        is recorded as a conflict and the stored observation is left exactly as it was.

        The joined page was read in an earlier transaction, so a differing outcome is first revalidated
        against the authoritative run row inside this one. A page that simply went stale — the run
        reached its terminal state and another collector recorded it first — is reported as stale, not
        as a changed source history, and the stored observation is returned unchanged."""
        stored = tx.get(OBSERVATIONS, observed["id"])
        if stored is None:
            body = {**observed, "first_seen_at": now, "last_seen_at": now, "outcome_history": []}
            tx.put(OBSERVATIONS, body["id"], body)
            counts["observations_recorded"] += 1
            return {"observation": body, "reason": "recorded"}
        if stored.get("decision_sha256") != observed["decision_sha256"]:
            self._store_conflict(tx, stored, observed, "decision_changed", now)
            return {"observation": None, "reason": "source_history_conflict"}
        if stored.get("outcome_sha256") == observed["outcome_sha256"]:
            counts["observations_unchanged"] += 1
            return {"observation": stored, "reason": "unchanged"}
        current = tx.get(RUNS, observed["run_id"])
        if not (isinstance(current, dict) and current.get("id") == observed["run_id"]):
            # The authoritative row cannot be re-read; unknown stays unknown and nothing is written.
            return {"observation": None, "reason": "source_row_unavailable"}
        outcome = outcome_facts(current)
        outcome_sha256 = digest(outcome)
        if outcome_sha256 == stored.get("outcome_sha256"):
            counts["observations_stale"] += 1
            return {"observation": stored, "reason": "source_page_stale"}
        observed = {**observed, "outcome": outcome, "outcome_sha256": outcome_sha256}
        if (stored.get("outcome") or {}).get("terminal"):
            self._store_conflict(tx, stored, observed, "terminal_outcome_changed", now)
            return {"observation": None, "reason": "source_history_conflict"}
        # The delayed outcome of a run that was still in flight when it was first observed; the
        # previous states stay in the bounded history and the source row is not touched.
        history = (stored.get("outcome_history") or []) + [{"at": now, "outcome_sha256": stored["outcome_sha256"],
                                                            "state": (stored.get("outcome") or {}).get("state"),
                                                            "source_status": (stored.get("outcome") or {}).get("source_status")}]
        body = {**stored, "outcome": observed["outcome"], "outcome_sha256": observed["outcome_sha256"],
                "last_seen_at": now, "outcome_history": history[-MAX_OUTCOME_HISTORY:]}
        tx.put(OBSERVATIONS, body["id"], body)
        counts["observations_updated"] += 1
        return {"observation": body, "reason": "updated"}

    @staticmethod
    def _store_conflict(tx, stored: dict, observed: dict, kind: str, now: str) -> None:
        body = conflict_body(stored, observed, kind)
        if tx.get(CONFLICTS, body["id"]) is None:
            tx.put(CONFLICTS, body["id"], {**body, "observed_at": now})

    @staticmethod
    def _store_group(tx, observation: dict, now: str) -> dict:
        """Durable exact membership of distinct run identities per exact contract. Re-collection,
        retries and event replays reach the same run id and add nothing, including past the number of
        occurrence references a candidate reports: the reported window is derived from this membership,
        never accumulated. Past the durable bound the group says `membership_capped` and counts no
        further run, so a repeated collection of an over-sized group still changes nothing."""
        key = observation["group_id"]
        group = tx.get(GROUPS, key) or {"id": key, "contract": observation["contract"],
                                        "source_kind": observation["source_kind"], "run_ids": [],
                                        "membership_capped": False, "first_seen_at": now}
        member = add_member(group["run_ids"], observation["run_id"])
        window = occurrence_window(member["run_ids"])
        group = {**group, "run_ids": member["run_ids"], "distinct_runs": len(member["run_ids"]),
                 "referenced_occurrences": len(window["referenced"]),
                 "unreferenced_occurrences": window["unreferenced"],
                 "membership_capped": bool(group.get("membership_capped")) or member["capped"],
                 "updated_at": now}
        tx.put(GROUPS, key, group)
        return group

    def _store_candidate(self, tx, group: dict, match: dict, pin: dict, registry_sha256: str,
                         repository: str, counts: dict, now: str):
        """Two distinct executed run identities, successes included, make exactly one candidate per
        repository + procedure + registry revision. Further runs append evidence, never a new item;
        past the reported window the distinct-run count stays exact and the remainder is named."""
        if len(group["run_ids"]) < OCCURRENCE_THRESHOLD:
            return None
        key = candidate_id(repository, match["procedure_id"], pin["revision"])
        occurrences, outcomes = [], {state: 0 for state in OUTCOME_STATES}
        for run_id in occurrence_window(group["run_ids"])["referenced"]:
            observation = tx.get(OBSERVATIONS, run_id) or {}
            outcome = observation.get("outcome") or {}
            outcomes[outcome.get("state") if outcome.get("state") in outcomes else "unknown"] += 1
            occurrences.append({"run_id": run_id, "observation_id": observation.get("id"),
                                "session_id": (observation.get("decision") or {}).get("session_id"),
                                "decision_event_id": (observation.get("decision") or {}).get("event_id"),
                                "execution_ref": (observation.get("decision") or {}).get("execution_ref"),
                                "outcome_state": outcome.get("state"), "source_status": outcome.get("source_status"),
                                "observed_at": observation.get("first_seen_at")})
        body = candidate_body(repository=repository, procedure_id=match["procedure_id"], remediation=match["remediation"],
                              registry_revision=pin["revision"], registry_path=pin["path"], registry_sha256=registry_sha256,
                              source_kind=group["source_kind"], occurrences=occurrences, outcomes=outcomes, group=group)
        existing = tx.get(CANDIDATES, key)
        body = {**body, "created_at": (existing or {}).get("created_at", now), "updated_at": now}
        if existing is not None and {k: v for k, v in existing.items() if k != "updated_at"} == \
                {k: v for k, v in body.items() if k != "updated_at"}:
            return existing
        tx.put(CANDIDATES, key, body)
        counts["candidates_updated" if existing is not None else "candidates_created"] += 1
        return body

    # ----- read-only ------------------------------------------------------------------------
    def status(self, *, limit: int = DEFAULT_SCAN) -> dict:
        """Bounded counts per bucket; a page that filled the limit says so instead of implying a total."""
        limit = scan_limit(limit)
        pages = {}
        try:
            with self.store.transaction() as tx:
                for bucket in (OBSERVATIONS, GROUPS, CANDIDATES, CONFLICTS):
                    rows = tx.entries(bucket, "", limit + 1)
                    pages[bucket] = {"counted": len(rows[:limit]), "truncated": len(rows) > limit,
                                     "next_cursor": rows[limit - 1]["id"] if len(rows) > limit else None,
                                     "rows": [r.get("body") or {} for r in rows[:limit]]}
        except Exception as exc:
            raise DecisionFeedbackError("source_unavailable") from exc
        outcomes = {state: 0 for state in OUTCOME_STATES}
        for row in pages[OBSERVATIONS]["rows"]:
            state = (row.get("outcome") or {}).get("state")
            outcomes[state if state in outcomes else "unknown"] += 1
        return {"schema": REPORT_SCHEMA, "kind": "status", "generated_at": self.clock(), "scan_limit": limit,
                "counts": {bucket: {k: pages[bucket][k] for k in ("counted", "truncated", "next_cursor")}
                           for bucket in pages},
                "observed_outcomes": outcomes, "quality": quality_facts(),
                "candidate_status": {CANDIDATE_SCHEMA: sorted({row.get("status") for row in pages[CANDIDATES]["rows"]})},
                "authority": COLLECTION_AUTHORITY, "limits": list(LIMITS)}

    def report(self, *, limit: int = DEFAULT_SCAN, after: str = "", collection_id: str | None = None) -> dict:
        """Candidates with their own evidence and outcome counts, the open conflicts and, when named,
        one collection receipt. Every page states its own truncation and continuation cursor."""
        limit = scan_limit(limit)
        if not isinstance(after, str):
            raise DecisionFeedbackError("invalid_cursor")
        try:
            with self.store.transaction() as tx:
                rows = tx.entries(CANDIDATES, after, limit + 1)
                conflicts = tx.entries(CONFLICTS, "", limit + 1)
                collection = tx.get(COLLECTIONS, collection_id) if isinstance(collection_id, str) and collection_id else None
        except Exception as exc:
            raise DecisionFeedbackError("source_unavailable") from exc
        page = [r.get("body") or {} for r in rows[:limit]]
        return {"schema": REPORT_SCHEMA, "kind": "report", "generated_at": self.clock(), "scan_limit": limit,
                "candidates": page, "candidates_truncated": len(rows) > limit,
                "next_cursor": page[-1].get("id") if len(rows) > limit and page else None,
                "conflicts": [r.get("body") or {} for r in conflicts[:limit]],
                "conflicts_truncated": len(conflicts) > limit,
                "collection": collection, "collection_found": collection is not None,
                "quality": quality_facts(), "authority": COLLECTION_AUTHORITY, "limits": list(LIMITS)}


__all__ = ["CANDIDATES", "COLLECTIONS", "CONFLICTS", "DecisionFeedback", "DecisionFeedbackError",
           "GROUPS", "OBSERVATIONS", "READ_BUCKETS", "WRITE_BUCKETS"]
