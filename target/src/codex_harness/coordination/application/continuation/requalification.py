"""The owner's delivery requalification.

Layer: application
Context: coordination
Owns: bucket continuation_requalifications
Does not own: the intent rows (IntentStore), delivery and review rows (read only)
Entry points: Requalification
Contracts: INV-CONTINUATION-001

Split from M7 `application/continuation.py` (SOURCE e38aa722) by the named S6 split (DESIGN-s6 §3,
A/evidence/rebuild/s6/continuation-split/split_continuation.py); the bodies are M7's.
"""

from __future__ import annotations

from codex_harness.coordination.application.continuation.lanes import LaneRuntime
from codex_harness.coordination.application.continuation.state import (
    BUCKET_INTENTS,
    BUCKET_POLICIES,
    BUCKET_REQUALIFICATIONS,
    FLEET_JOBS,
    WITHDRAWN_STAGE,
    policy_frame,
)
from codex_harness.coordination.domain.continuation import (
    BINDING_SCHEMA,
    DELIVERY,
    DELIVERY_BOUND,
    GOAL_MIGRATION,
    GOAL_MIGRATION_REVIEW,
    INTENDED,
    MAX_HISTORY,
    OPEN_STATES,
    RECOVERY_REQUIRED,
    REQUALIFICATION,
    REQUALIFICATION_AUTHORIZED,
    REQUALIFICATION_REQUALIFIABLE,
    REQUALIFICATION_SCHEMA,
    ROUTE_OWNERS,
    SUPERSEDED,
    ContinuationRefused,
    authorization,
    check_authorization,
    check_scope,
    delivery_tuple,
    refuse,
    requalification_id,
    requalification_manifest,
    requalification_view,
    successor_id,
    validate_requalification,
)
from codex_harness.kernel.errors import ContractError
from codex_harness.kernel.ids import digest, utcnow


class Requalification:
    """The owner's delivery requalification on the current main: verified bindings, one unit
    superseding the intent and creating the requalification intent, and its recheck."""

    def __init__(self, store, *, clock=utcnow, lanes=None, validate=None, intents=None, research=None):
        self.store = store
        self.clock = clock
        self.lanes = lanes
        self.validate = validate
        self.intents = intents
        self.research = research

    def requalify_delivery(self, document, *, pin_sha256: str | None = None, runtime=None, mainline=None) -> dict:
        """Supersede ONE delivery intent whose HostDelivery plan the owner withdrew as stale by ONE fresh
        `requalification` operation on the named current main (SPEC aibox-migration-001 s15, D5).

        Verified first against authoritative reads (`_requalification_bindings`): the registered, enabled
        policy at its re-read pin and the current runtime/frame authorization of the origin job; the
        intent (this policy's `host_delivery` route, `awaiting_owner` or `paused`, same family and
        release); the lane's HostDelivery row of exactly the named plan at stage `withdrawn` for the named
        reason; the release candidate; `main_revision` equal to the remote main NOW, present in the lane
        repository and (for `reviewed_base_moved`) not the withdrawn candidate's base; the goal bytes at
        that main still the goal's pinned digest, or - only with the owner's optional `goal_migration`
        block - the block's exact old digest as the stored origin binding and the real blob at the
        origin's base, and its new digest as the real blob at that main, same path and criterion, with
        the review reference's bytes (owner review R1); no other open requalification in the family; the
        rationale bytes. Then ONE control-store transaction rechecks the family (R2) and stores the
        document, moves the intent to `superseded` (an explicit owner transition, never a TRANSITIONS
        edge; its snapshot and history stay) and creates the `requalification` intent with the origin's
        goal (at the migrated digest when recorded), allowed paths, criteria, budget and controls on
        `main_revision`, a fresh workspace (no session, no continued workspace) and explicit lineage.
        Nothing external happens: the next tick binds and admits it through the existing path. The
        identical document replays (`cached`); any other for the same intent is
        `requalification_conflict`. Owner-triggered only: nothing here ever re-arms itself."""
        requalification = validate_requalification(document)
        key = requalification["intent_id"]
        with self.store.transaction() as tx:
            stored = tx.get(BUCKET_REQUALIFICATIONS, key)
            row = tx.get(BUCKET_POLICIES, requalification["policy_id"])
            intent = tx.get(BUCKET_INTENTS, key)
            jobs = {job["id"]: job for job in tx.scan(FLEET_JOBS)}
            framed = policy_frame(tx, row)
        if stored is not None:
            refuse(stored.get("document") == requalification, "requalification_conflict", "operator", "intent_id")
            return self._requalification_result(stored, cached=True)
        refuse(pin_sha256 is not None and runtime is not None and mainline is not None,
               "requalification_unverified", "operator", "pin")
        refuse(isinstance(row, dict) and row["policy_sha256"] == requalification["policy_sha256"]
               and row["policy"]["enabled"] and row["pin"].get("sha256") == pin_sha256,
               "requalification_policy_foreign", "operator", "policy")
        refuse(isinstance(intent, dict) and intent.get("policy_id") == requalification["policy_id"]
               and intent.get("policy_sha256") == requalification["policy_sha256"],
               "requalification_intent_unknown", "operator", "intent_id")
        refuse(intent.get("route") == DELIVERY and intent.get("state") in REQUALIFICATION_REQUALIFIABLE,
               "requalification_intent_state", "operator", "intent_id")
        refuse(intent.get("family") == requalification["family"]
               and intent.get("release_id") == requalification["release_id"],
               "requalification_intent_mismatch", "operator", "intent_id")
        ctx = {"policy": framed, "sha": row["policy_sha256"], "pin": row["pin"].get("sha256"),
               "runtime": LaneRuntime(runtime), "jobs": jobs}
        job = jobs.get(intent["origin_job"])
        refuse(isinstance(job, dict), "origin_job_missing", "fleet", "origin_job")
        current = ctx["runtime"](job["lane"])
        check_scope(ctx["policy"], job, current)
        check_authorization(intent.get("authorization"), authorization(ctx["sha"], ctx["pin"], job, current))
        goal, compared = self._requalification_bindings(ctx, requalification, intent, job, mainline)
        successor = successor_id(requalification_id(key))
        migration = requalification.get(GOAL_MIGRATION)
        manifest = requalification_manifest(job["manifest"], requalification["main_revision"], successor, {
            "predecessor_job": job["id"], "predecessor_intent": key,
            "candidate_revision": requalification["candidate"]["revision"],
            "candidate_tree": requalification["candidate"]["tree"],
            "candidate_base": requalification["candidate"]["base"], "release_id": requalification["release_id"],
            "plan_id": requalification["plan"]["plan_id"], "withdrawal_reason": requalification["withdrawal_reason"],
            "goal_from_sha256": (migration or {}).get("from_sha256"),
            "goal_to_sha256": (migration or {}).get("to_sha256")}, goal["sha256"] if migration else None)
        if self.validate is not None:
            try:
                manifest = self.validate(manifest)
            except ContractError:
                raise ContinuationRefused("requalification_manifest_refused", "operator", "manifest") from None
        return self._commit_requalification(requalification, row, intent, job, manifest, goal, compared)

    @staticmethod
    def _family_open(rows, requalification: dict) -> bool:
        """Another requalification of this policy's family is still open (one at a time per family)."""
        return any(row.get("route") == REQUALIFICATION and row.get("state") in OPEN_STATES | {RECOVERY_REQUIRED}
                   and row.get("policy_id") == requalification["policy_id"]
                   and row.get("family") == requalification["family"] for row in rows)

    def _requalification_bindings(self, ctx, requalification: dict, intent: dict, job: dict, mainline):
        """What one requalification is bound to, re-read now outside any transaction; returns the goal
        binding at `main_revision` and the stored goal comparison (None without a migration block). The
        first gap refuses by name; an unreadable read refuses too. The family check here only refuses
        early: `_commit_requalification` decides it again inside its transaction."""
        with self.store.transaction() as tx:
            every = tx.scan(BUCKET_INTENTS)
        refuse(not self._family_open(every, requalification), "requalification_family_open", "fleet", "family")
        migration = requalification.get(GOAL_MIGRATION)
        origin_goal = job["goal"]
        if migration is not None:
            # R1: the SAME goal (path and criterion), from exactly the digest the origin was bound and
            # authorized under; never a wider or another goal.
            refuse(migration["path"] == origin_goal["path"] and migration["criterion"] == origin_goal["criterion"],
                   "requalification_goal_migration_scope", "operator", GOAL_MIGRATION)
            refuse(migration["from_sha256"] == origin_goal["sha256"]
                   == ((intent.get("authorization") or {}).get("goal") or {}).get("sha256"),
                   "requalification_goal_migration_origin", "operator", GOAL_MIGRATION)
        lane = self.lanes(intent["lane"])
        evidence = lane.read(job, ctx["policy"]["delivery_target"])
        delivery = evidence.get("delivery") or {}
        plan = requalification["plan"]
        refuse(delivery.get("binding") == DELIVERY_BOUND and delivery_tuple(delivery)
               == delivery_tuple(intent.get("delivery_binding")), "requalification_delivery_unbound", "host_delivery",
               "plan")
        refuse((delivery.get("plan_id"), delivery.get("plan_sha256")) == (plan["plan_id"], plan["plan_sha256"]),
               "requalification_plan_mismatch", "host_delivery", "plan")
        withdrawn = lane.delivery_intent(plan["plan_id"])
        refuse(delivery.get("stage") == WITHDRAWN_STAGE and isinstance(withdrawn, dict)
               and withdrawn.get("stage") == WITHDRAWN_STAGE, "requalification_plan_not_withdrawn", "host_delivery",
               "plan")
        refuse((withdrawn.get("withdrawal") or {}).get("reason_code") == requalification["withdrawal_reason"],
               "requalification_reason_mismatch", "host_delivery", "withdrawal_reason")
        task = evidence.get("task") if isinstance(evidence.get("task"), dict) else {}
        candidate = (task.get("result") or {}).get("candidate") or {}
        release = lane.release(requalification["release_id"])
        recorded = ((release or {}).get("candidate") or {}) if isinstance(release, dict) else {}
        refuse(all({k: source.get(k) for k in ("revision", "tree", "base")} == requalification["candidate"]
                   for source in (recorded, candidate)), "requalification_candidate_mismatch", "operator", "candidate")
        main = requalification["main_revision"]
        try:
            port = mainline(intent["lane"])
            remote = port.remote_main()
            present = port.commit_exists(main)
            observed = port.goal(main, origin_goal["path"]) if present else None
            # The real blob the origin was bound to at its own base (only read for a migration).
            before = port.goal(origin_goal["base_revision"], origin_goal["path"]) if migration is not None \
                and port.commit_exists(origin_goal["base_revision"]) else None
        except ContinuationRefused:
            raise
        except Exception:
            raise ContinuationRefused("requalification_main_unreadable", "operator", "main_revision") from None
        refuse(remote == main, "requalification_main_changed", "operator", "main_revision")
        refuse(present, "requalification_main_missing", "operator", "main_revision")
        if requalification["withdrawal_reason"] == "reviewed_base_moved":
            refuse(main != requalification["candidate"]["base"], "requalification_main_not_moved", "operator",
                   "main_revision")
        regular = isinstance(observed, dict) and observed.get("mode") == "100644"
        compared = None
        if migration is None:
            # The same rule the operation's own goal binding applies at its base (`goal_binding`).
            refuse(regular and observed.get("sha256") == origin_goal["sha256"], "requalification_goal_changed",
                   "operator", "goal")
        else:
            refuse(isinstance(before, dict) and before.get("mode") == "100644"
                   and before.get("sha256") == migration["from_sha256"], "requalification_goal_migration_origin",
                   "operator", GOAL_MIGRATION)
            refuse(regular and observed.get("sha256") == migration["to_sha256"],
                   "requalification_goal_migration_target", "operator", GOAL_MIGRATION)
            self._verify_review(migration["review_ref"])
            # Durable comparison inputs only (hashes, sizes, revisions): no claim the diff was reviewed here.
            compared = {"path": migration["path"], "criterion": migration["criterion"],
                        "from": {"revision": origin_goal["base_revision"], "sha256": migration["from_sha256"],
                                 "bytes": before.get("bytes")},
                        "to": {"revision": main, "sha256": migration["to_sha256"], "bytes": observed.get("bytes")},
                        "review_ref": migration["review_ref"], "review": GOAL_MIGRATION_REVIEW}
        try:
            self.research.verify_evidence([requalification["rationale_ref"]])
        except ContinuationRefused as exc:
            raise ContinuationRefused(exc.reason_code.replace("research_evidence", "requalification_rationale", 1),
                                      "operator", "rationale_ref") from None
        return ({"path": origin_goal["path"], "sha256": observed["sha256"], "criterion": origin_goal["criterion"],
                 "base_revision": main, "bytes": observed.get("bytes")}, compared)

    def _verify_review(self, ref: str) -> None:
        """The owner's goal-diff review reference: its actual bytes through the trusted store, now."""
        try:
            self.research.verify_evidence([ref])
        except ContinuationRefused as exc:
            raise ContinuationRefused(exc.reason_code.replace("research_evidence", "requalification_goal_review", 1),
                                      "operator", GOAL_MIGRATION) from None

    def _commit_requalification(self, requalification: dict, row: dict, intent: dict, job: dict, manifest: dict,
                                goal: dict, compared: dict | None) -> dict:
        """ONE transaction: nothing the verification read moved and no other requalification of the
        family opened meanwhile (owner review R2; `Store.transaction` serializes writers), then the
        document, the superseded intent and the requalification intent together - an interruption
        leaves all three or none, and a refusal writes none."""
        key, now = requalification["intent_id"], self.clock()
        new_id = requalification_id(key)
        successor = manifest["id"]
        document_sha = digest(requalification)
        with self.store.transaction() as tx:
            old = tx.get(BUCKET_REQUALIFICATIONS, key)
            if old is not None:
                refuse(old.get("document") == requalification, "requalification_conflict", "operator", "intent_id")
                return self._requalification_result(old, cached=True)
            refuse(not self._family_open(tx.scan(BUCKET_INTENTS), requalification), "requalification_family_open",
                   "fleet", "family")
            current = tx.get(BUCKET_INTENTS, key)
            refuse(current == intent, "requalification_intent_changed", "operator", "intent_id")
            refuse(tx.get(BUCKET_POLICIES, requalification["policy_id"]) == row, "requalification_policy_foreign",
                   "operator", "policy")
            refuse(tx.get(FLEET_JOBS, job["id"]) == job, "requalification_source_changed", "operator", "origin_job")
            refuse(tx.get(BUCKET_INTENTS, new_id) is None and tx.get(FLEET_JOBS, successor) is None,
                   "requalification_successor_exists", "fleet", "successor_job")
            snapshot = {k: current.get(k) for k in ("state", "reason_code", "next_owner", "version", "updated_at")}
            stored = {"id": key, "schema": REQUALIFICATION_SCHEMA, "document": requalification,
                      "document_sha256": document_sha, "requalification_intent": new_id, "successor_job": successor,
                      GOAL_MIGRATION: compared, "superseded": snapshot, "recorded_at": now, "recorded_by": "owner"}
            # The one explicit owner transition of the delivery intent (never a TRANSITIONS edge).
            current.update(state=SUPERSEDED, reason_code=REQUALIFICATION_AUTHORIZED, next_owner="operator",
                           superseded_by=new_id, requalification=document_sha, version=current["version"] + 1,
                           updated_at=now)
            current["history"] = current["history"][-(MAX_HISTORY - 1):] + [
                {"state": SUPERSEDED, "previous": snapshot["state"], "reason_code": REQUALIFICATION_AUTHORIZED,
                 "error_type": None, "requalification": document_sha, "at": now}]
            binding = {"schema": BINDING_SCHEMA, "operation_id": successor, "policy_sha256": intent["policy_sha256"],
                       "intent_id": new_id, "family": intent["family"], "route": REQUALIFICATION, "session": None,
                       "workspace": None,
                       "predecessor": {"job_id": job["id"], "intent_id": key, "release_id": requalification["release_id"],
                                       "candidate_revision": requalification["candidate"]["revision"],
                                       "plan_id": requalification["plan"]["plan_id"],
                                       "withdrawal_reason": requalification["withdrawal_reason"]}}
            created = {"id": new_id, "policy_id": intent["policy_id"], "policy_sha256": intent["policy_sha256"],
                       "origin_job": intent["origin_job"], "lane": intent["lane"], "family": intent["family"],
                       "predecessor_intent": key, "job_updated_at": intent.get("job_updated_at"),
                       "route": REQUALIFICATION, "state": INTENDED, "reason_code": REQUALIFICATION_AUTHORIZED,
                       "next_owner": ROUTE_OWNERS[REQUALIFICATION], "evidence_sha256": document_sha,
                       "evidence_refs": [requalification["rationale_ref"]], "authorization": intent.get("authorization"),
                       "successor_job": successor, "manifest": manifest, "goal": goal, "binding": binding,
                       "session_mode": "fresh_workspace_requalification", "requalification": document_sha,
                       "generation": intent.get("generation", 0), "attempt": intent.get("attempt", 0),
                       "version": 1, "created_at": now, "updated_at": now,
                       "history": [{"state": INTENDED, "reason_code": REQUALIFICATION_AUTHORIZED, "at": now}]}
            tx.put(BUCKET_REQUALIFICATIONS, key, stored)
            tx.put(BUCKET_INTENTS, key, current)
            tx.put(BUCKET_INTENTS, new_id, created)
        self.intents.emit(snapshot["state"], current)
        self.intents.emit(None, created)
        return self._requalification_result(stored, cached=False)

    @staticmethod
    def _requalification_result(row: dict, cached: bool) -> dict:
        return {"requalified": True, "cached": cached, **requalification_view(row)}

    def check(self, ctx, intent: dict) -> None:
        """Before a requalification intent's NEW effect: its stored owner document, intact and naming
        exactly this intent, successor and policy; the goal the successor is admitted with is exactly
        the recorded one (the origin's digest, or the migration's target with its stored comparison);
        and a migration's review reference bytes, verified again now."""
        with self.store.transaction() as tx:
            row = tx.get(BUCKET_REQUALIFICATIONS, intent.get("predecessor_intent") or "")
        refuse(isinstance(row, dict), "requalification_missing", "operator", "requalification")
        document = row.get("document")
        refuse(isinstance(document, dict) and row.get("document_sha256") == digest(document) == intent["requalification"]
               and row.get("requalification_intent") == intent["id"] == requalification_id(document["intent_id"])
               and row.get("successor_job") == intent.get("successor_job") == successor_id(intent["id"]),
               "requalification_corrupt", "operator", "requalification")
        refuse(document["policy_id"] == ctx["policy"]["id"] and document["policy_sha256"] == ctx["sha"],
               "requalification_policy_foreign", "operator", "policy")
        origin = (ctx["jobs"].get(intent["origin_job"]) or {}).get("goal") or {}
        migration, compared = document.get(GOAL_MIGRATION), row.get(GOAL_MIGRATION)
        goal, manifest_goal = intent.get("goal") or {}, (intent.get("manifest") or {}).get("goal") or {}
        expected = origin.get("sha256") if migration is None else migration["to_sha256"]
        refuse(goal.get("sha256") == manifest_goal.get("sha256") == expected
               and goal.get("path") == manifest_goal.get("path") == origin.get("path")
               and goal.get("criterion") == manifest_goal.get("criterion") == origin.get("criterion")
               and goal.get("base_revision") == document["main_revision"]
               and (compared is None if migration is None else isinstance(compared, dict)
                    and (compared.get("from") or {}).get("sha256") == migration["from_sha256"]
                    and (compared.get("to") or {}).get("sha256") == migration["to_sha256"]
                    and compared.get("review_ref") == migration["review_ref"]),
               "requalification_corrupt", "operator", "requalification")
        if migration is not None:
            self._verify_review(migration["review_ref"])
