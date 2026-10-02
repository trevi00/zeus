"""Shared S8 scenario steps (`intake.ticket_lifecycle`): M7 `application/ticket_lifecycle.py` (`TicketLifecycle`: prepare, review, close, reopen,
verify_closed; the helpers `require_no_promotion`, `event_document`, `verify_chain`, `transition`), characterized BEFORE pilot 98 moves it into
INTAKE (DESIGN-s8 §6 V11), in the sequences of the M7 `tests/test_ticket_lifecycle.py` (22 tests; each case is labelled with its test).

- **a_surface**: the module's own names and signatures, the constructor's attributes.
- **b_helpers**: `require_no_promotion`, `event_document`, `verify_chain` and `transition` called on a transaction (every refusal, the rows written).
- **c_prepare**: `prepare` (the packet, its refusals, every `_evidence` rule: kind, binding, age, order, budgets, canonical bytes, criterion identity).
- **d_review**: `review` (time_status, the unmerged commit, a ticket changed during export, the pinned anchor).
- **e_close**: `test_signed_close_reopen_and_new_cycle_invalidate_old_work`, `test_closure_rejects_missing_failed_stale_or_unsigned_evidence`,
  `test_signature_authority_is_not_an_actor_string`, `test_state_ack_loss_recovers_without_duplicate_decision` (the one decision),
  `test_repo_commit_cannot_replace_anchored_signers`, `test_concurrent_same_packet_commits_one_decision` (the same overlap, sequentially),
  `test_two_valid_packets_cannot_consume_same_sequence`, `test_closure_database_failure_rolls_back_*`, `test_ticket_edit_during_signature_verification_*`,
  `test_invalid_or_untrusted_policy_cannot_authorize_close`, `test_new_deployment_anchor_cannot_bypass_existing_pg_pin`,
  `test_crlf_signature_armor_and_explicit_required_signers_receipt`, `test_old_environment_observation_rejected_even_in_same_revision`,
  `test_corrupted_old_event_blocks_new_closure`, and the refusals the tests do not reach (promotion, signer expiry, consumed slot, tampered revision).
- **f_reopen**: `test_explicit_open_reassertion_intentionally_invalidates_old_execution`, `test_reopen_projection_checks_the_whole_history`, the
  argument refusals, the replay and the stale retry, `test_consumed_reopen_does_not_override_later_manual_close` (the reopen side).
- **g_verify_closed**: `verify_closed` (the chain, the decision, the revision, the packet and proof, the heartbeat, the anchor).

Layer: harness (never shipped)

This module never imports `codex_harness`: everything arrives through `api`. The store is a MemoryStore (a raised exception discards the draft, as the
PostgreSQL transaction rolls back). The `Tickets` the lifecycle receives is M7's (reference) or the labelled stand-in transcribed from M7 (target; `Tickets`
is layer 2). LABELLED fakes: the authority (`FakeAuthority`: the policy document, `require_merged`, `verify` with the verifier's accept/reject rule for
signatures; the cryptography of `adapters/ticket_authority.py` is not this module's) and the artifact store (`FakeArtifacts`: `put`, `text`, `document`
with the real bounds). The ticket rows are written the way `Tickets.create`/`update`/`dispatch` and the GitHub link leave them. Scripted clock.

Unreachable here, reported in `m7_tests`: the real `ssh-keygen` signatures and git trust repository, the GitHub sync (`test_github_tickets` fixtures:
`github.sync`, the remote state, the lease), the ticket CLI, the thread overlap, the PostgreSQL boundary. For every refusal the digest of the whole store
before and after is recorded."""

from __future__ import annotations

import hashlib
import inspect
import json
from copy import deepcopy
from datetime import timedelta, timezone

TICKET = "ZEUS-000000000001"
OTHER = "ZEUS-000000000002"
COMMIT = "a" * 40
POLICY_COMMIT = "b" * 40
PRINCIPAL = "test-only-not-a-human@zeus.invalid"
NAMESPACE = "zeus-ticket-close-v1"
BUCKETS = ("tickets", "ticket_dispatches", "ticket_closures", "ticket_closure_sequences", "ticket_reopens", "ticket_github",
           "ticket_lifecycle_events", "ticket_trust_anchors")
CONTENT = {"title": "Independent services", "problem": "Services share one failure domain.", "impact": "One outage stops every review.",
           "rollback": "Revert the merge commit.", "evidence_refs": ["docs/evidence.md"], "scope": ["split the queue", "split the store"],
           "acceptance_criteria": ["queue runs alone", "store runs alone"], "verification": ["run both"]}
DAY = 86400

M7_TESTS = {
    "covered": ["test_signed_close_reopen_and_new_cycle_invalidate_old_work (the lifecycle part; GitHub sync and Tickets.update/dispatch unreachable)",
                "test_closure_rejects_missing_failed_stale_or_unsigned_evidence",
                "test_signature_authority_is_not_an_actor_string (propagation of the labelled authority's refusal)",
                "test_state_ack_loss_recovers_without_duplicate_decision (the one decision; the GitHub half unreachable)",
                "test_repo_commit_cannot_replace_anchored_signers (the pinned anchor; the git policy unreachable)",
                "test_concurrent_same_packet_commits_one_decision (the same overlap run sequentially through a hook)",
                "test_two_valid_packets_cannot_consume_same_sequence",
                "test_closure_database_failure_rolls_back_ticket_event_anchor_and_pending_links",
                "test_ticket_edit_during_signature_verification_prevents_closure",
                "test_invalid_or_untrusted_policy_cannot_authorize_close (a refused policy through the labelled authority)",
                "test_new_deployment_anchor_cannot_bypass_existing_pg_pin",
                "test_missing_authority_invalidates_previous_synced_link (the authority refusal; the GitHub half unreachable)",
                "test_crlf_signature_armor_and_explicit_required_signers_receipt (the receipt fields)",
                "test_old_environment_observation_rejected_even_in_same_revision",
                "test_corrupted_old_event_blocks_new_closure",
                "test_explicit_open_reassertion_intentionally_invalidates_old_execution (the lifecycle part)",
                "test_reopen_projection_checks_the_whole_history (the chain part)",
                "test_consumed_reopen_does_not_override_later_manual_close (the reopen side)"],
    "unreachable": {"test_late_remote_close_cannot_complete_newer_local_cycle[reopen]": "GitHub sync and the remote state",
                    "test_late_remote_close_cannot_complete_newer_local_cycle[expired-lease]": "GitHub sync and the lease",
                    "test_consumed_close_does_not_override_external_reopen": "GitHub sync and the remote state",
                    "test_cli_close_and_reopen_use_same_verified_application": "the ticket CLI (S10)",
                    "test_slow_verification_renews_owned_lease_between_bounded_operations": "GitHub sync lease renewal"}}


def sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=repr).encode()).hexdigest()[:16]


def shape(value):
    if isinstance(value, dict):
        return {str(k): shape(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [shape(v) for v in value]
    return value


class FakeArtifacts:
    """LABELLED double of `FileArtifacts`: `put(body, source)` answers the content address, `text(ref, max_bytes)` and `document(ref)` read it back
    with the real bounds (an absent reference is a `FileNotFoundError`; a scripted fault is raised)."""

    def __init__(self, api, clock):
        self.api, self.clock, self.bodies, self.faults, self.calls = api, clock, {}, {}, []

    def put(self, body, source):
        data = body.encode("utf-8")
        ref = "sha256:" + hashlib.sha256(data).hexdigest()
        self.bodies[ref] = body
        self.calls.append(["put", source])
        return {"ref": ref, "source": source, "bytes": len(data)}

    def text(self, ref, max_bytes):
        self.calls.append(["text", ref, max_bytes])
        if ref in self.faults:
            raise self.faults[ref]
        if ref not in self.bodies:
            raise FileNotFoundError(ref)
        data = self.bodies[ref].encode("utf-8")
        self.api.require(len(data) <= max_bytes, "Artifact exceeds text budget")
        return self.bodies[ref]

    def document(self, ref):
        self.calls.append(["document", ref])
        if ref not in self.bodies:
            raise FileNotFoundError(ref)
        value = json.loads(self.bodies[ref])
        self.api.require(isinstance(value, dict), "Evidence document must be an object")
        return value


class FakeAuthority:
    """LABELLED double of `TicketAuthority`: `policy(heartbeat)` answers the scripted policy document or raises the scripted fault; `require_merged`
    refuses a commit in `unmerged`; `verify` applies the verifier's rule (every required principal signs once, the signature text is the one signed
    over that packet in that namespace) and answers the proof. `hooks` run once at the named call (a ticket edited during verification, an overlapping
    close)."""

    def __init__(self, api, artifacts):
        self.api, self.artifacts, self.calls, self.hooks, self.unmerged, self.policy_fault, self.verify_fault = api, artifacts, [], {}, set(), None, None
        self.document = {"policy_commit": POLICY_COMMIT, "policy_hash": "policy-hash-1", "scope": "test-only-ticket-authority",
                         "definition": {"version": 1, "scope": "test-only-ticket-authority", "required_signers": [PRINCIPAL],
                                        "required_human_signers": [], "max_evidence_age_seconds": DAY},
                         "enrolled": {PRINCIPAL: {"role": "automation", "valid_before": "2099-01-01T00:00:00+00:00"}}}

    def _hook(self, name):
        hook = self.hooks.pop(name, None)
        if hook is not None:
            hook()

    def policy(self, heartbeat=None):
        self.calls.append(["policy", heartbeat])
        if self.policy_fault is not None:
            raise self.policy_fault
        return deepcopy(self.document)

    def require_merged(self, commit):
        self.calls.append(["require_merged", commit])
        self._hook("require_merged")
        self.api.require(commit not in self.unmerged, "Solution commit is not merged")

    def verify(self, packet_ref, packet, signatures, heartbeat=None):
        self.calls.append(["verify", packet_ref, [s["principal"] for s in signatures], heartbeat])
        self._hook("verify")
        if self.verify_fault is not None:
            raise self.verify_fault
        required = self.document["definition"]["required_signers"]
        principals = [s["principal"] for s in signatures]
        self.api.require(bool(principals), "Required signature missing")
        self.api.require(len(set(principals)) == len(principals), "Duplicate signer")
        self.api.require(set(principals) == set(required), "Signer is not an enrolled required signer")
        for signature in signatures:
            body = self.artifacts.text(signature["signature_ref"], 16384).replace("\r\n", "\n")
            self.api.require(body == "SIGNED:" + NAMESPACE + ":" + packet_ref + ":" + signature["principal"] + "\nEND", "Signature verification failed")
        return {"packet_ref": packet_ref, "attestation_scope": "configured_key_authority_only", "physical_human_presence_verified": False,
                "required_signers": list(required), "required_human_signers": list(self.document["definition"]["required_human_signers"]),
                "signatures": [{"principal": s["principal"], "signature_ref": s["signature_ref"]} for s in signatures]}


class World:
    """One ticket in a MemoryStore as `Tickets.create` leaves it (plus a dispatch and a GitHub link, and the same rows of another ticket), the lifecycle
    over the labelled authority and artifact store, and the scripted clock at its start."""

    def __init__(self, api, *, links=True, content=None):
        api.clock.reset()
        self.api, self.clock = api, api.clock
        self.store, self.artifacts = api.MemoryStore(), FakeArtifacts(api, api.clock)
        self.authority = FakeAuthority(api, self.artifacts)
        self.tickets = api.Tickets(self.store, "org")
        self.life = api.TicketLifecycle(self.tickets, self.artifacts, self.authority)
        self.content = deepcopy(CONTENT if content is None else content)
        for ticket_id in (TICKET, OTHER):
            row = {"id": ticket_id, "revision": 1, "content_hash": api.digest(self.content), "status": "open", "created_at": self.now()}
            self.put("tickets", ticket_id, row)
            self.put("ticket_revisions", ticket_id + ":1", {**row, "content": self.content, "claimed_author": "operator", "reason": "created"})
        if links:
            for ticket_id, tag in ((TICKET, "1"), (OTHER, "2")):
                self.put("ticket_dispatches", "dispatch-" + tag, {"id": "dispatch-" + tag, "ticket_id": ticket_id, "status": "dispatched"})
                self.put("ticket_github", "github-" + tag, {"id": "github-" + tag, "ticket_id": ticket_id, "status": "synced", "desired_state": "OPEN"})
            self.put("ticket_dispatches", "dispatch-old", {"id": "dispatch-old", "ticket_id": TICKET, "status": "superseded"})

    # clock
    def now(self, seconds=0):
        value = self.clock.now(timezone.utc)
        return (value + timedelta(seconds=seconds)).isoformat()

    def tick(self, seconds=1):
        self.clock.advance(seconds)

    # rows
    def put(self, bucket, key, row):
        with self.store.transaction() as tx:
            tx.put(bucket, key, row)

    def get(self, bucket, key):
        with self.store.transaction() as tx:
            return tx.get(bucket, key)

    def scan(self, bucket):
        with self.store.transaction() as tx:
            return tx.scan(bucket)

    def revise(self, content=None):
        """`Tickets.update`'s effect on the rows: a new revision, the content hash, `open`, `updated_at`, the dispatches superseded."""
        content = deepcopy(content or {**self.content, "title": "Revised criteria"})
        with self.store.transaction() as tx:
            row = tx.get("tickets", TICKET)
            row.update(revision=row["revision"] + 1, content_hash=self.api.digest(content), status="open", updated_at=self.now())
            tx.put("tickets", TICKET, row)
            tx.put("ticket_revisions", TICKET + ":" + str(row["revision"]), {**row, "content": content, "claimed_author": "operator", "reason": "Revise"})
            for dispatch in tx.scan("ticket_dispatches"):
                if dispatch["ticket_id"] == TICKET and dispatch["status"] != "superseded":
                    tx.put("ticket_dispatches", dispatch["id"], {**dispatch, "status": "superseded", "superseded_by_revision": row["revision"]})

    # evidence
    def base(self, **over):
        current = self.get("tickets", TICKET)
        return {"revision": current["revision"], "content_hash": current["content_hash"], "ticket_id": TICKET, "solution_commit": COMMIT,
                "observed_at": self.now(), "details": {"test_only": True, "human_acceptance": False}, **over}

    def doc(self, body):
        return self.artifacts.put(self.api.canonical(body), "test-evidence")["ref"]

    def environment(self, **over):
        return self.doc({**self.base(), "kind": "ticket-environment-v1", **over})

    def criterion(self, index, **over):
        return self.doc({**self.base(), "kind": "ticket-criterion-evidence-v1", "criterion_index": index, "outcome": "passed", **over})

    def evidence(self, *, environment=None, refs=None, **over):
        contents = self.get("ticket_revisions", TICKET + ":" + str(self.get("tickets", TICKET)["revision"]))["content"]["acceptance_criteria"]
        refs = refs if refs is not None else [[self.criterion(i)] for i in range(len(contents))]
        return {"solution_commit": COMMIT, "environment_ref": environment or self.environment(), "reason": "Test-only acceptance",
                "criteria": [{"index": i, "criterion_hash": self.api.digest(text), "outcome": "passed", "evidence_refs": refs[i]}
                             for i, text in enumerate(contents)], **over}

    def prepare(self, **over):
        self.tick()
        return self.life.prepare(TICKET, self.evidence(**over))

    def sign(self, packet_ref, principal=PRINCIPAL, namespace=NAMESPACE, tail=""):
        body = "SIGNED:" + namespace + ":" + packet_ref + ":" + principal + tail + "\nEND"
        return [{"principal": principal, "signature_ref": self.artifacts.put(body, "test-only-signature")["ref"]}]

    def ready(self, **over):
        prepared = self.prepare(**over)
        return prepared, self.sign(prepared["packet_ref"])

    def store_packet(self, packet):
        return self.artifacts.put(self.api.canonical(packet), "test-modified-packet")["ref"]

    # observation
    def snap(self):
        with self.store.transaction() as tx:
            records = tx.records()
        return {"store": sha(records), "artifacts": len(self.artifacts.bodies), "counts": {b: sum(r["bucket"] == b for r in records) for b in BUCKETS}}

    def observe(self, call):
        before = self.snap()
        try:
            out = {"outcome": "returned", "value": shape(call())}
        except BaseException as exc:  # noqa: BLE001 - what propagates is part of the observation
            out = {"outcome": "raised", "type": type(exc).__name__, "message": str(exc), "is_contract_error": isinstance(exc, self.api.ContractError),
                   "cause_type": None if exc.__cause__ is None else type(exc.__cause__).__name__}
        after = self.snap()
        out.update(store_before=before["store"], store_after=after["store"], store_unchanged=before["store"] == after["store"],
                   artifacts_added=after["artifacts"] - before["artifacts"], counts_after=after["counts"])
        return out

    def in_tx(self, call):
        def run():
            with self.store.transaction() as tx:
                return call(tx)
        return run

    def state(self):
        row = self.get("tickets", TICKET)
        return {"ticket": row, "events": [[e["sequence"], e["kind"], e["previous_status"]] for e in sorted(self.scan("ticket_lifecycle_events"),
                key=lambda e: e["sequence"])], "counts": self.snap()["counts"]}


def a_surface(api):
    names = ("require_no_promotion", "event_document", "verify_chain", "transition")
    cases = {"functions": {n: str(inspect.signature(getattr(api, n))) for n in names}}
    methods = {n: str(inspect.signature(getattr(api.TicketLifecycle, n))) for n in
               ("__init__", "prepare", "_evidence", "review", "_anchor", "close", "reopen", "verify_closed")}
    cases["TicketLifecycle_methods"] = methods
    cases["anchor_is_static"] = isinstance(inspect.getattr_static(api.TicketLifecycle, "_anchor"), staticmethod)
    w = World(api)
    cases["constructor"] = {"tickets": w.life.tickets is w.tickets, "store_is_tickets_store": w.life.store is w.tickets.store,
                            "artifacts": w.life.artifacts is w.artifacts, "authority": w.life.authority is w.authority}
    cases["tickets_get"] = shape(w.tickets.get(TICKET))
    return {"surface": cases}


def b_helpers(api):
    cases = {}
    w = World(api)
    # require_no_promotion
    intents = {"completed": ("completed", TICKET), "abandoned": ("abandoned", TICKET), "pending": ("pending", TICKET),
               "running": ("running", TICKET), "other_ticket_pending": ("pending", OTHER)}
    for name, (status, ticket_id) in intents.items():
        w.put("promotion_intents", "intent-" + name, {"status": status, "candidate": {"zeus_ticket": {"id": ticket_id}}})
    w.put("promotion_intents", "intent-nocandidate", {"status": "pending"})
    w.put("promotion_intents", "intent-nobinding", {"status": "pending", "candidate": {}})
    cases["promotion_mixed_refused_by_pending_and_running"] = w.observe(w.in_tx(lambda tx: api.require_no_promotion(tx, TICKET)))
    cases["promotion_other_ticket_only_pending_refused"] = w.observe(w.in_tx(lambda tx: api.require_no_promotion(tx, OTHER)))
    cases["promotion_unknown_ticket_passes"] = w.observe(w.in_tx(lambda tx: api.require_no_promotion(tx, "ZEUS-unknown")))
    clean = World(api)
    for name in ("completed", "abandoned"):
        clean.put("promotion_intents", "intent-" + name, {"status": name, "candidate": {"zeus_ticket": {"id": TICKET}}})
    clean.put("promotion_intents", "intent-nocandidate", {"status": "pending"})
    clean.put("promotion_intents", "intent-nobinding", {"status": "pending", "candidate": {}})
    cases["promotion_resolved_and_unbound_intents_pass"] = clean.observe(clean.in_tx(lambda tx: api.require_no_promotion(tx, TICKET)))
    clean.put("promotion_intents", "intent-null-candidate", {"status": "pending", "candidate": None})
    cases["promotion_null_candidate_is_not_guarded"] = clean.observe(clean.in_tx(lambda tx: api.require_no_promotion(tx, TICKET)))

    # transition: the rows it writes, the chain it extends
    w = World(api)
    ticket = w.get("tickets", TICKET)
    w.tick(5)
    cases["transition_closed"] = w.observe(w.in_tx(lambda tx: api.transition(tx, ticket, "closed", "Accepted", packet_ref="sha256:" + "1" * 64,
                                                                             proof_ref="sha256:" + "2" * 64)))
    cases["transition_closed_state"] = {"ticket": w.get("tickets", TICKET), "dispatches": w.scan("ticket_dispatches"), "github": w.scan("ticket_github")}
    ticket = w.get("tickets", TICKET)
    w.tick(5)
    cases["transition_reopened"] = w.observe(w.in_tx(lambda tx: api.transition(tx, ticket, "reopened", "Recurrence", request_id="request-1")))
    cases["transition_reopened_state"] = {"ticket": w.get("tickets", TICKET), "dispatches": w.scan("ticket_dispatches"), "github": w.scan("ticket_github")}
    ticket = w.get("tickets", TICKET)
    w.tick(5)
    cases["transition_third"] = w.observe(w.in_tx(lambda tx: api.transition(tx, ticket, "closed", "Accepted again")))
    events = sorted(w.scan("ticket_lifecycle_events"), key=lambda e: e["sequence"])
    cases["event_ids_are_the_digest_of_the_event"] = [e["id"] == api.digest({k: v for k, v in e.items() if k != "id"}) for e in events]
    cases["chain_links"] = [[e["sequence"], e["from_sequence"], e["previous_event"] == (events[i - 1]["id"] if i else None)] for i, e in enumerate(events)]
    current = w.get("tickets", TICKET)
    cases["verify_chain_whole"] = w.observe(w.in_tx(lambda tx: api.verify_chain(tx, current)))

    # transition refused: a stale chain, an unresolved promotion
    w2 = World(api)
    w2.put("promotion_intents", "intent-1", {"status": "pending", "candidate": {"zeus_ticket": {"id": TICKET}}})
    ticket = w2.get("tickets", TICKET)
    cases["transition_refused_by_promotion"] = w2.observe(w2.in_tx(lambda tx: api.transition(tx, ticket, "closed", "Accepted")))
    w2.put("promotion_intents", "intent-1", {"status": "completed", "candidate": {"zeus_ticket": {"id": TICKET}}})
    cases["transition_after_promotion_completed"] = w2.observe(w2.in_tx(lambda tx: api.transition(tx, ticket, "closed", "Accepted")))

    # verify_chain: sequences and the chain
    w3 = World(api)
    base = w3.get("tickets", TICKET)
    for name, ticket in (("zero_without_event", {**base}), ("zero_with_event", {**base, "lifecycle_event": "x"}),
                         ("negative", {**base, "lifecycle_sequence": -1}), ("string", {**base, "lifecycle_sequence": "1"}),
                         ("bool", {**base, "lifecycle_sequence": True}), ("float", {**base, "lifecycle_sequence": 1.0}),
                         ("one_without_event", {**base, "lifecycle_sequence": 1, "lifecycle_event": "missing"})):
        cases["verify_chain_" + name] = w3.observe(w3.in_tx(lambda tx, t=ticket: api.verify_chain(tx, t)))

    def chained():
        world = World(api)
        for kind in ("closed", "reopened", "closed"):
            world.tick()
            with world.store.transaction() as tx:
                api.transition(tx, tx.get("tickets", TICKET), kind, "r-" + kind)
        return world

    for name, edit in (("another_ticket", lambda e: {**e, "ticket_id": OTHER}), ("sequence", lambda e: {**e, "sequence": e["sequence"] + 5}),
                       ("from_sequence", lambda e: {**e, "from_sequence": 9}), ("content", lambda e: {**e, "reason": "Tampered"}),
                       ("id_removed", lambda e: {k: v for k, v in e.items() if k != "id"})):
        world = chained()
        current = world.get("tickets", TICKET)
        head = world.get("ticket_lifecycle_events", current["lifecycle_event"])
        world.put("ticket_lifecycle_events", head["id"], edit(head))
        cases["verify_chain_head_" + name] = world.observe(world.in_tx(lambda tx, c=current: api.verify_chain(tx, c)))
    world = chained()
    first = sorted(world.scan("ticket_lifecycle_events"), key=lambda e: e["sequence"])[0]
    world.put("ticket_lifecycle_events", first["id"], {**first, "reason": "Tampered older event"})
    current = world.get("tickets", TICKET)
    cases["verify_chain_first_event_tampered"] = world.observe(world.in_tx(lambda tx: api.verify_chain(tx, current)))
    cases["transition_refused_by_tampered_history"] = world.observe(world.in_tx(lambda tx: api.transition(tx, current, "reopened", "More")))
    cases["event_document_missing"] = world.observe(world.in_tx(lambda tx: api.event_document(tx, "nope")))
    cases["event_document_none"] = world.observe(world.in_tx(lambda tx: api.event_document(tx, None)))
    cases["event_document_tampered"] = world.observe(world.in_tx(lambda tx: api.event_document(tx, first["id"])))
    world.put("ticket_lifecycle_events", "no-id", {"ticket_id": TICKET})
    cases["event_document_without_id_key"] = world.observe(world.in_tx(lambda tx: api.event_document(tx, "no-id")))
    ok = sorted((e for e in world.scan("ticket_lifecycle_events") if "sequence" in e), key=lambda e: e["sequence"])[-1]
    cases["event_document_valid"] = world.observe(world.in_tx(lambda tx: api.event_document(tx, ok["id"])))
    return {"helpers": cases}


def c_prepare(api):
    cases = {}
    w = World(api)
    w.tick()
    evidence = w.evidence()
    prepared = w.observe(lambda: w.life.prepare(TICKET, evidence))
    cases["prepare_ok"] = prepared
    result = prepared["value"]
    packet = result["packet"]
    cases["prepare_packet_facts"] = {"keys": sorted(packet), "payload_is_canonical_packet": result["signing_payload"] == api.canonical(packet),
                                    "artifact_is_payload": w.artifacts.bodies[result["packet_ref"]] == result["signing_payload"],
                                    "expires_after_issue_seconds": 3600, "namespace": result["signing_namespace"], "status": result["status"],
                                    "policy_fields": [packet["policy_commit"], packet["policy_hash"], packet["scope"]], "issued": packet["issued_at"],
                                    "expires": packet["expires_at"], "expected_status": packet["expected_status"], "sequence": packet["sequence"],
                                    "criteria_hash": packet["criteria_hash"] == api.digest(CONTENT["acceptance_criteria"])}
    cases["prepare_repeated_is_the_same_packet_ref"] = w.life.prepare(TICKET, evidence)["packet_ref"] == result["packet_ref"]
    cases["prepare_unknown_ticket"] = w.observe(lambda: w.life.prepare("ZEUS-unknown", evidence))
    cases["prepare_evidence_not_a_dict"] = w.observe(lambda: w.life.prepare(TICKET, [evidence]))
    cases["prepare_evidence_missing_key"] = w.observe(lambda: w.life.prepare(TICKET, {k: v for k, v in evidence.items() if k != "reason"}))
    cases["prepare_evidence_extra_key"] = w.observe(lambda: w.life.prepare(TICKET, {**evidence, "extra": 1}))
    w.authority.policy_fault = api.ContractError("Out-of-band trust anchor configuration required")
    cases["prepare_policy_refused_by_the_authority"] = w.observe(lambda: w.life.prepare(TICKET, evidence))
    w.authority.policy_fault = None

    # `_evidence` / validate_packet / validate_evidence rules, each through prepare with one defect
    def refused(name, **over):
        world = World(api)
        world.tick()
        built = over.pop("build")(world) if "build" in over else world.evidence(**over)
        cases["prepare_" + name] = world.observe(lambda: world.life.prepare(TICKET, built))

    refused("criteria_missing", criteria=[])
    refused("criterion_not_passed", build=lambda x: _criteria(x, outcome="failed"))
    refused("criterion_index_wrong", build=lambda x: _criteria(x, index=1))
    refused("criterion_hash_wrong", build=lambda x: _criteria(x, criterion_hash="0" * 64))
    refused("criterion_extra_key", build=lambda x: _criteria(x, extra=1))
    refused("criterion_no_evidence", build=lambda x: _criteria(x, evidence_refs=[]))
    refused("criterion_bad_reference", build=lambda x: _criteria(x, evidence_refs=["sha256:xyz"]))
    refused("criterion_21_references", build=lambda x: _criteria(x, evidence_refs=["sha256:" + "%064x" % i for i in range(21)]))
    refused("environment_reference_bad", environment="sha256:short")
    refused("solution_commit_short", solution_commit="abc123")
    refused("solution_commit_not_a_string", solution_commit=None)
    refused("reason_empty", reason="   ")
    refused("reason_too_long", reason="x" * 4001)
    refused("reason_exactly_4000_still_needs_the_rest", reason="x" * 4000)

    def other(name, setup, **over):
        world = World(api)
        setup(world)
        world.tick()
        cases["prepare_" + name] = world.observe(lambda: world.life.prepare(TICKET, world.evidence(**over)))

    other("ticket_already_closed", lambda x: x.put("tickets", TICKET, {**x.get("tickets", TICKET), "status": "closed"}))
    other("ticket_dispatched_is_allowed", lambda x: x.put("tickets", TICKET, {**x.get("tickets", TICKET), "status": "dispatched"}))
    other("ticket_status_unknown", lambda x: x.put("tickets", TICKET, {**x.get("tickets", TICKET), "status": "weird"}))

    # evidence documents
    def evidence_case(name, mutate, kind="criterion", tick=1):
        world = World(api)
        if tick:
            world.tick(tick)
        if kind == "environment":
            built = world.evidence(environment=world.environment(**mutate(world)))
        else:
            built = world.evidence(refs=[[world.criterion(0, **mutate(world))], [world.criterion(1)]])
        world.tick()
        cases["evidence_" + name] = world.observe(lambda: world.life.prepare(TICKET, built))

    evidence_case("criterion_revision_stale", lambda x: {"revision": 0})
    evidence_case("criterion_revision_not_int", lambda x: {"revision": "1"})
    evidence_case("criterion_revision_bool", lambda x: {"revision": True})
    evidence_case("criterion_content_hash", lambda x: {"content_hash": "0" * 64})
    evidence_case("criterion_other_ticket", lambda x: {"ticket_id": OTHER})
    evidence_case("criterion_other_commit", lambda x: {"solution_commit": "c" * 40})
    evidence_case("criterion_kind_environment", lambda x: {"kind": "ticket-environment-v1"})
    evidence_case("criterion_outcome_failed", lambda x: {"outcome": "failed"})
    evidence_case("criterion_outcome_skipped", lambda x: {"outcome": "skipped"})
    evidence_case("criterion_outcome_unknown", lambda x: {"outcome": "unknown"})
    evidence_case("criterion_index_not_int", lambda x: {"criterion_index": "0"})
    evidence_case("criterion_index_other_criterion", lambda x: {"criterion_index": 1})
    evidence_case("criterion_details_empty", lambda x: {"details": {}})
    evidence_case("criterion_details_not_dict", lambda x: {"details": [1]})
    evidence_case("criterion_observed_not_a_string", lambda x: {"observed_at": 5})
    evidence_case("criterion_observed_no_timezone", lambda x: {"observed_at": "2026-09-22T00:00:00"})
    evidence_case("criterion_observed_unparsable", lambda x: {"observed_at": "yesterday"})
    evidence_case("criterion_observed_after_issue", lambda x: {"observed_at": x.now(500)})
    evidence_case("criterion_observed_before_ticket_revision", lambda x: {"observed_at": x.now(-1)}, tick=0)
    evidence_case("environment_kind_wrong", lambda x: {"kind": "ticket-criterion-evidence-v1"}, kind="environment")
    evidence_case("environment_stale_revision", lambda x: {"revision": 0}, kind="environment")
    evidence_case("environment_observed_after_issue", lambda x: {"observed_at": x.now(500)}, kind="environment")

    # age: the exact boundary and one second over (max_evidence_age_seconds = 86400)
    for name, age in (("at_the_age_limit", DAY), ("one_second_too_old", DAY + 1)):
        world = World(api)
        built = world.evidence()
        world.tick(age)
        cases["evidence_age_" + name] = world.observe(lambda: world.life.prepare(TICKET, built))
    world = World(api)
    built = world.evidence()
    world.tick(3 * DAY)
    cases["test_old_environment_observation_rejected_even_in_same_revision"] = world.observe(lambda: world.life.prepare(TICKET, built))

    # bodies: not JSON, not canonical, not an object, absent, over the 1 MiB read budget, over the 8 MiB total
    def body_case(name, body=None, absent=False, arrange=None):
        world = World(api)
        world.tick()
        ref = ("sha256:" + "f" * 64) if absent else world.artifacts.put(body, "test-evidence")["ref"]
        built = world.evidence(refs=[[ref], [world.criterion(1)]])
        cases["evidence_body_" + name] = world.observe(lambda: world.life.prepare(TICKET, built))

    body_case("absent", absent=True)
    body_case("not_json", body="not json")
    body_case("a_list", body="[1]")
    body_case("not_canonical_pretty", body=json.dumps({"kind": "ticket-criterion-evidence-v1"}, indent=1))
    world = World(api)
    world.tick()
    document = {**world.base(), "kind": "ticket-criterion-evidence-v1", "criterion_index": 0, "outcome": "passed"}
    pretty = json.dumps(document, indent=1)
    built = world.evidence(refs=[[world.artifacts.put(pretty, "test-evidence")["ref"]], [world.criterion(1)]])
    cases["evidence_body_valid_but_not_canonical"] = world.observe(lambda: world.life.prepare(TICKET, built))
    big = {**world.base(), "kind": "ticket-criterion-evidence-v1", "criterion_index": 0, "outcome": "passed"}
    big["details"] = {"pad": "x" * (1024 * 1024)}
    built = world.evidence(refs=[[world.doc(big)], [world.criterion(1)]])
    cases["evidence_body_over_one_mebibyte"] = world.observe(lambda: world.life.prepare(TICKET, built))
    world = World(api)
    world.tick()
    docs = []
    for i in range(9):
        body = {**world.base(), "kind": "ticket-criterion-evidence-v1", "criterion_index": 0 if i < 5 else 1, "outcome": "passed",
                "details": {"pad": chr(97 + i) * 1_000_000}}
        docs.append(world.doc(body))
    built = world.evidence(refs=[docs[:5], docs[5:]])
    cases["evidence_total_over_eight_mebibytes"] = world.observe(lambda: world.life.prepare(TICKET, built))
    built = world.evidence(refs=[docs[:4], docs[5:8]])
    cases["evidence_total_just_under_the_budget"] = world.observe(lambda: world.life.prepare(TICKET, built))
    return {"prepare": cases}


def _criteria(world, **over):
    built = world.evidence()
    built["criteria"][0] = {**built["criteria"][0], **over}
    return built


def d_review(api):
    cases = {}
    w = World(api)
    prepared = w.prepare()
    packet = prepared["packet"]
    cases["review_ok"] = w.observe(lambda: w.life.review(deepcopy(packet)))
    cases["review_calls"] = w.authority.calls
    cases["review_snapshot_ref_is_the_digest_of_the_packet"] = cases["review_ok"]["value"]["packet_ref"] == "sha256:" + api.digest(packet)
    cases["review_records_no_authority"] = {"counts": w.snap()["counts"], "approval_granted": cases["review_ok"]["value"]["approval_granted"]}
    cases["review_packet_not_a_dict"] = w.observe(lambda: w.life.review(["x"]))
    cases["review_ticket_id_missing"] = w.observe(lambda: w.life.review({}))
    cases["review_ticket_id_not_a_string"] = w.observe(lambda: w.life.review({"ticket_id": 5}))
    cases["review_unknown_ticket"] = w.observe(lambda: w.life.review({**packet, "ticket_id": "ZEUS-unknown"}))
    cases["review_issued_at_missing"] = w.observe(lambda: w.life.review({k: v for k, v in packet.items() if k != "issued_at"}))
    for name, seconds in (("expired_grant", 7200), ("exactly_expired", 3600), ("future", -1)):
        world = World(api)
        pre = world.prepare()
        world.tick(seconds if name != "future" else 0)
        review_packet = deepcopy(pre["packet"])
        if name == "future":
            review_packet["issued_at"] = world.now(10)
            review_packet["expires_at"] = world.now(3610)
        cases["review_time_status_" + name] = world.observe(lambda: world.life.review(review_packet))
    world = World(api)
    pre = world.prepare()
    world.tick(10)
    cases["review_time_status_recheck_at_close_later"] = world.observe(lambda: world.life.review(deepcopy(pre["packet"])))
    world.authority.unmerged.add(COMMIT)
    cases["test_review_cli_unmerged_commit_is_refused"] = world.observe(lambda: world.life.review(deepcopy(pre["packet"])))
    world.authority.unmerged.clear()
    world.authority.hooks["require_merged"] = world.revise
    cases["review_ticket_changed_during_export"] = world.observe(lambda: world.life.review(deepcopy(pre["packet"])))
    world = World(api)
    pre = world.prepare()
    world.put("ticket_trust_anchors", "deployment", {"policy_commit": "c" * 40, "policy_hash": "policy-hash-1", "scope": "test-only-ticket-authority"})
    cases["review_policy_differs_from_the_pinned_anchor"] = world.observe(lambda: world.life.review(deepcopy(pre["packet"])))
    world.put("ticket_trust_anchors", "deployment", {"policy_commit": POLICY_COMMIT, "policy_hash": "policy-hash-1", "scope": "test-only-ticket-authority"})
    cases["review_policy_equals_the_pinned_anchor"] = world.observe(lambda: world.life.review(deepcopy(pre["packet"])))
    world = World(api)
    pre = world.prepare()
    world.put("tickets", TICKET, {**world.get("tickets", TICKET), "lifecycle_sequence": 1, "lifecycle_event": "missing"})
    cases["review_stale_sequence_is_refused_by_the_packet"] = world.observe(lambda: world.life.review(deepcopy(pre["packet"])))
    world.authority.policy_fault = api.ContractError("Out-of-band trust anchor configuration required")
    cases["review_policy_refused_by_the_authority"] = world.observe(lambda: world.life.review(deepcopy(pre["packet"])))
    return {"review": cases}


def e_close(api):
    cases = {}

    # test_signed_close_reopen_and_new_cycle_invalidate_old_work
    w = World(api)
    before_bound = {"id": TICKET, "revision": 1, "content_hash": w.get("tickets", TICKET)["content_hash"]}
    prepared, signatures = w.ready()
    closed = w.observe(lambda: w.life.close(prepared["packet_ref"], signatures))
    cases["lifecycle_close"] = closed
    cases["lifecycle_after_close"] = w.state()
    cases["lifecycle_close_rows"] = {"dispatches": w.scan("ticket_dispatches"), "github": w.scan("ticket_github"), "closures": w.scan("ticket_closures"),
                                     "sequences": w.scan("ticket_closure_sequences"), "anchor": w.get("ticket_trust_anchors", "deployment"),
                                     "proof": json.loads(w.artifacts.bodies[closed["value"]["decision"]["proof_ref"]])}
    calls_before = len(w.authority.calls)
    cases["lifecycle_replay"] = w.observe(lambda: w.life.close(prepared["packet_ref"], []))
    cases["lifecycle_replay_touches_no_authority"] = len(w.authority.calls) == calls_before
    cases["lifecycle_replay_equals_decision"] = [cases["lifecycle_replay"]["value"]["decision"] == closed["value"]["decision"],
                                                 cases["lifecycle_replay"]["value"]["replayed"], closed["value"]["replayed"]]
    cases["lifecycle_tickets_get_closed"] = shape(w.tickets.get(TICKET))
    cases["lifecycle_binding_after_close"] = [w.observe(w.in_tx(lambda tx: api.ticket_binding(tx, {"zeus_ticket": before_bound}))),
                                               w.observe(w.in_tx(lambda tx: api.ticket_binding(tx, {"zeus_ticket": {**before_bound, "lifecycle_sequence": 1}})))]
    w.tick()
    reopened = w.observe(lambda: w.life.reopen(TICKET, 1, 1, "Recurrence"))
    cases["lifecycle_reopen"] = reopened
    cases["lifecycle_reopen_replay"] = w.observe(lambda: w.life.reopen(TICKET, 1, 1, "Recurrence"))
    cases["lifecycle_stale_close_retry_after_reopen"] = w.observe(lambda: w.life.close(prepared["packet_ref"], []))
    cases["lifecycle_binding_after_reopen"] = w.observe(w.in_tx(lambda tx: api.ticket_binding(tx, {"zeus_ticket": before_bound})))
    cases["lifecycle_after_reopen_rows"] = {"dispatches": w.scan("ticket_dispatches"), "github": w.scan("ticket_github"), "state": w.state()}
    fresh, fresh_signatures = w.ready()
    cases["lifecycle_second_close"] = w.observe(lambda: w.life.close(fresh["packet_ref"], fresh_signatures))
    cases["lifecycle_stale_reopen_retry"] = w.observe(lambda: w.life.reopen(TICKET, 1, 1, "Recurrence"))
    history = w.tickets.get(TICKET)["lifecycle_history"]
    cases["lifecycle_history"] = {"kinds": [r["kind"] for r in history], "sequences": [r["sequence"] for r in history],
                                  "attestation_scope": json.loads(w.artifacts.bodies[history[0]["proof_ref"]])["attestation_scope"],
                                  "physical_human_presence_verified": json.loads(w.artifacts.bodies[history[0]["proof_ref"]])["physical_human_presence_verified"]}
    cases["lifecycle_ticket_binding_classes"] = [api.TicketClosed.__name__, issubclass(api.TicketClosed, api.TicketSuperseded),
                                                 issubclass(api.TicketSuperseded, api.ContractError)]

    # test_closure_rejects_missing_failed_stale_or_unsigned_evidence (and the packet defects the tests do not reach)
    def corrupt(name, edit):
        world = World(api)
        prepared, signatures = world.ready()
        packet = deepcopy(prepared["packet"])
        edit(world, packet)
        ref = world.store_packet(packet)
        cases["corruption_" + name] = world.observe(lambda: world.life.close(ref, signatures))
        cases["corruption_" + name + "_rows"] = {"status": world.get("tickets", TICKET)["status"], "events": len(world.scan("ticket_lifecycle_events")),
                                                 "anchors": len(world.scan("ticket_trust_anchors"))}

    corrupt("missing", lambda w, p: p.update(criteria=[]))
    for outcome in ("failed", "skipped", "unknown"):
        corrupt(outcome, lambda w, p, o=outcome: p["criteria"][0].update(outcome=o))
    corrupt("wrong_index", lambda w, p: p["criteria"][0].update(index=1))
    corrupt("expired", lambda w, p: p.update(expires_at=w.now(-1)))
    corrupt("future", lambda w, p: p.update(issued_at=w.now(60), expires_at=w.now(3660)))
    corrupt("grant_too_long", lambda w, p: p.update(expires_at=w.now(25 * 3600)))
    corrupt("old_evidence", lambda w, p: p["criteria"][0].update(evidence_refs=[w.criterion(0, revision=0)]))
    corrupt("modified_after_signing", lambda w, p: p.update(reason="Changed after signing"))
    corrupt("policy_hash_changed", lambda w, p: p.update(policy_hash="policy-hash-2"))
    corrupt("version_two", lambda w, p: p.update(version=2))
    corrupt("extra_key", lambda w, p: p.update(extra=1))
    corrupt("ticket_id_other", lambda w, p: p.update(ticket_id=OTHER))
    corrupt("revision_stale", lambda w, p: p.update(revision=2))
    corrupt("sequence_stale", lambda w, p: p.update(sequence=1))
    corrupt("expected_status_wrong", lambda w, p: p.update(expected_status="closed"))
    corrupt("commit_changed", lambda w, p: p.update(solution_commit="c" * 40))
    corrupt("issued_long_ago", lambda w, p: p.update(issued_at=w.now(-100000)))

    # test_signature_authority_is_not_an_actor_string
    def signed(name, make):
        world = World(api)
        prepared = world.prepare()
        signatures = make(world, prepared["packet_ref"])
        cases["signature_" + name] = world.observe(lambda: world.life.close(prepared["packet_ref"], signatures))
        cases["signature_" + name + "_rows"] = {"status": world.get("tickets", TICKET)["status"], "events": len(world.scan("ticket_lifecycle_events")),
                                                "anchors": len(world.scan("ticket_trust_anchors"))}

    signed("missing", lambda w, ref: [])
    signed("wrong_principal", lambda w, ref: [{**w.sign(ref)[0], "principal": "human"}])
    signed("duplicate", lambda w, ref: w.sign(ref) * 2)
    signed("wrong_namespace", lambda w, ref: w.sign(ref, namespace="zeus-ticket-reopen-v1"))
    signed("untrusted_key", lambda w, ref: w.sign(ref, tail="-untrusted"))
    signed("absent_signature_artifact", lambda w, ref: [{"principal": PRINCIPAL, "signature_ref": "sha256:" + "e" * 64}])
    signed("crlf_armor_is_accepted", lambda w, ref: [{"principal": PRINCIPAL, "signature_ref": w.artifacts.put(
        w.artifacts.bodies[w.sign(ref)[0]["signature_ref"]].replace("\n", "\r\n"), "test-CRLF-signature")["ref"]}])
    w = World(api)
    prepared, signatures = w.ready()
    w.authority.verify_fault = api.ContractError("Signing identity revoked")
    cases["signature_verifier_refusal_leaves_no_proof_artifact"] = [w.observe(lambda: w.life.close(prepared["packet_ref"], signatures)),
                                                                    [c[1] for c in w.artifacts.calls if c[0] == "put"].count("ticket-closure-signature-verification")]

    # test_crlf_signature_armor_and_explicit_required_signers_receipt
    w = World(api)
    prepared = w.prepare()
    sig = w.sign(prepared["packet_ref"])
    body = w.artifacts.bodies[sig[0]["signature_ref"]]
    crlf = [{"principal": PRINCIPAL, "signature_ref": w.artifacts.put(body.replace("\n", "\r\n"), "test-CRLF-signature")["ref"]}]
    result = w.life.close(prepared["packet_ref"], crlf)
    proof = json.loads(w.artifacts.bodies[result["decision"]["proof_ref"]])
    cases["receipt_after_crlf_close"] = {"required_signers": proof["required_signers"], "required_human_signers": proof["required_human_signers"],
                                         "physical_human_presence_verified": proof["physical_human_presence_verified"],
                                         "proof_ref_is_the_digest": result["decision"]["proof_ref"] == "sha256:" + hashlib.sha256(api.canonical(proof).encode()).hexdigest()}

    # test_state_ack_loss_recovers_without_duplicate_decision: one decision however often the close is repeated
    w = World(api)
    prepared, signatures = w.ready()
    first = w.life.close(prepared["packet_ref"], signatures)
    again = [w.life.close(prepared["packet_ref"], signatures) for _ in range(3)]
    cases["one_decision_for_repeated_closes"] = {"events": len(w.scan("ticket_lifecycle_events")), "replayed": [r["replayed"] for r in again],
                                                 "same": all(r["decision"] == first["decision"] for r in again), "verify_calls": sum(c[0] == "verify" for c in w.authority.calls)}

    # test_repo_commit_cannot_replace_anchored_signers / test_missing_authority_invalidates_previous_synced_link
    w = World(api)
    prepared, signatures = w.ready()
    w.life.close(prepared["packet_ref"], signatures)
    w.authority.policy_fault = api.ContractError("Out-of-band trust anchor configuration required")
    cases["authority_gone_replay_still_answers"] = w.observe(lambda: w.life.close(prepared["packet_ref"], []))
    w.tick()
    cases["authority_gone_reopen_does_not_need_it"] = w.observe(lambda: w.life.reopen(TICKET, 1, 1, "Next cycle"))
    cases["authority_gone_prepare_refused"] = w.observe(lambda: w.life.prepare(TICKET, w.evidence()))
    w.authority.policy_fault = None
    w2 = World(api)
    prepared, signatures = w2.ready()
    w2.authority.policy_fault = api.ContractError("Out-of-band trust anchor configuration required")
    cases["authority_gone_close_refused"] = w2.observe(lambda: w2.life.close(prepared["packet_ref"], signatures))

    # test_concurrent_same_packet_commits_one_decision, run as the overlap it models: a second closer commits while the first verifies
    w = World(api)
    prepared, signatures = w.ready()
    other = api.TicketLifecycle(w.tickets, w.artifacts, w.authority)
    inner = {}

    def overlapping_close():
        inner["result"] = other.close(prepared["packet_ref"], signatures)

    w.authority.hooks["verify"] = overlapping_close
    outer = w.observe(lambda: w.life.close(prepared["packet_ref"], signatures))
    cases["overlap_outer_replays_the_decision"] = outer
    cases["overlap_one_decision"] = {"inner_replayed": inner["result"]["replayed"], "same_decision": inner["result"]["decision"] == outer["value"]["decision"],
                                     "events": len(w.scan("ticket_lifecycle_events")), "sequences": len(w.scan("ticket_closure_sequences")),
                                     "verify_calls": sum(c[0] == "verify" for c in w.authority.calls)}

    # test_two_valid_packets_cannot_consume_same_sequence
    w = World(api)
    first, first_signatures = w.ready()
    second, second_signatures = w.ready()
    cases["two_packets_first"] = w.observe(lambda: w.life.close(first["packet_ref"], first_signatures))
    cases["two_packets_second_refused"] = w.observe(lambda: w.life.close(second["packet_ref"], second_signatures))
    cases["two_packets_one_event"] = len(w.scan("ticket_lifecycle_events"))

    # test_closure_database_failure_rolls_back_ticket_event_anchor_and_pending_links
    w = World(api)
    prepared, signatures = w.ready()
    transaction = w.store.transaction
    seen = []

    class Failing:
        def __init__(self, tx):
            self.tx = tx
            self.get, self.scan, self.records = tx.get, tx.scan, tx.records

        def put(self, bucket, key, row):
            if bucket == "ticket_closures":
                seen.append(bucket)
                raise RuntimeError("Injected PG boundary failure before commit")
            return self.tx.put(bucket, key, row)

    def failing_transaction():
        import contextlib

        @contextlib.contextmanager
        def manager():
            with transaction() as tx:
                yield Failing(tx)
        return manager()

    w.store.transaction = failing_transaction
    cases["rollback_failure"] = w.observe(lambda: w.life.close(prepared["packet_ref"], signatures))
    w.store.transaction = transaction
    cases["rollback_rows"] = {"state": w.state(), "github": w.scan("ticket_github"), "dispatches": w.scan("ticket_dispatches"), "anchor": w.get("ticket_trust_anchors", "deployment"),
                              "put_attempts": seen}
    cases["rollback_then_close_succeeds"] = w.observe(lambda: w.life.close(prepared["packet_ref"], signatures))

    # test_ticket_edit_during_signature_verification_prevents_closure
    w = World(api)
    prepared, signatures = w.ready()
    w.authority.hooks["verify"] = w.revise
    cases["edit_during_verification"] = w.observe(lambda: w.life.close(prepared["packet_ref"], signatures))
    cases["edit_during_verification_rows"] = {"revision": w.get("tickets", TICKET)["revision"], "events": len(w.scan("ticket_lifecycle_events")),
                                              "anchors": len(w.scan("ticket_trust_anchors"))}

    # test_invalid_or_untrusted_policy_cannot_authorize_close: a refusing authority at each entry
    w = World(api)
    prepared, signatures = w.ready()
    for entry, call in (("close", lambda: w.life.close(prepared["packet_ref"], signatures)), ("prepare", lambda: w.life.prepare(TICKET, w.evidence())),
                        ("review", lambda: w.life.review(deepcopy(prepared["packet"])))):
        w.authority.policy_fault = api.ContractError("Trust policy invalid or untrusted")
        cases["policy_refused_" + entry] = w.observe(call)
    w.authority.policy_fault = None
    cases["policy_refused_then_trusted_close"] = w.observe(lambda: w.life.close(prepared["packet_ref"], signatures))

    # test_new_deployment_anchor_cannot_bypass_existing_pg_pin
    w = World(api)
    first, first_signatures = w.ready()
    w.life.close(first["packet_ref"], first_signatures)
    w.tick()
    w.life.reopen(TICKET, 1, 1, "Next cycle")
    w.authority.document["policy_commit"] = "c" * 40
    second, second_signatures = w.ready()
    cases["anchor_pinned_commit_changed"] = w.observe(lambda: w.life.close(second["packet_ref"], second_signatures))
    cases["anchor_pinned_state"] = {"anchor": w.get("ticket_trust_anchors", "deployment"), "status": w.get("tickets", TICKET)["status"]}
    w.authority.document["policy_commit"] = POLICY_COMMIT
    w.authority.document["scope"] = "other-scope"
    third, third_signatures = w.ready()
    cases["anchor_pinned_scope_changed"] = w.observe(lambda: w.life.close(third["packet_ref"], third_signatures))
    w.authority.document["scope"] = "test-only-ticket-authority"
    fourth, fourth_signatures = w.ready()
    cases["anchor_unchanged_policy_closes_again"] = w.observe(lambda: w.life.close(fourth["packet_ref"], fourth_signatures))

    # more refusals: signer expiry, the consumed slot, tampered or missing revision, a corrupted old event, an unresolved promotion
    w = World(api)
    prepared, signatures = w.ready()
    w.authority.document["enrolled"][PRINCIPAL]["valid_before"] = w.now(-1)
    cases["signer_expired_before_closure_commit"] = w.observe(lambda: w.life.close(prepared["packet_ref"], signatures))
    w.authority.document["enrolled"][PRINCIPAL]["valid_before"] = w.now(1)
    cases["signer_valid_until_after_now"] = w.observe(lambda: w.life.close(prepared["packet_ref"], signatures))
    w = World(api)
    prepared, signatures = w.ready()
    w.put("ticket_closure_sequences", TICKET + ":0", {"packet_ref": "other", "event_id": "other"})
    cases["closure_sequence_already_consumed"] = w.observe(lambda: w.life.close(prepared["packet_ref"], signatures))
    w = World(api)
    prepared, signatures = w.ready()
    revision = w.get("ticket_revisions", TICKET + ":1")
    w.put("ticket_revisions", TICKET + ":1", {**revision, "content": {**revision["content"], "title": "Tampered"}})
    cases["revision_content_tampered_is_refused_by_tickets_get"] = w.observe(lambda: w.life.close(prepared["packet_ref"], signatures))
    w = World(api)
    prepared, signatures = w.ready()
    w.put("ticket_revisions", TICKET + ":1", {**w.get("ticket_revisions", TICKET + ":1"), "content_hash": "0" * 64})
    cases["revision_row_hash_mismatch"] = w.observe(lambda: w.life.close(prepared["packet_ref"], signatures))
    w = World(api)
    prepared, signatures = w.ready()
    w.authority.hooks["verify"] = lambda: w.put("ticket_revisions", TICKET + ":1", {**w.get("ticket_revisions", TICKET + ":1"), "content": {**w.content, "title": "Swapped"}})
    cases["revision_content_swapped_during_verification"] = w.observe(lambda: w.life.close(prepared["packet_ref"], signatures))
    w = World(api)
    prepared, signatures = w.ready()
    w.authority.hooks["verify"] = lambda: _drop(w, "ticket_revisions", TICKET + ":1")
    cases["revision_row_removed_during_verification"] = w.observe(lambda: w.life.close(prepared["packet_ref"], signatures))
    w = World(api)
    prepared, signatures = w.ready()
    w.put("promotion_intents", "intent-1", {"status": "pending", "candidate": {"zeus_ticket": {"id": TICKET}}})
    cases["promotion_unresolved_blocks_closure"] = w.observe(lambda: w.life.close(prepared["packet_ref"], signatures))
    cases["promotion_unresolved_rolls_back_the_anchor"] = len(w.scan("ticket_trust_anchors"))
    w = World(api)
    first, first_signatures = w.ready()
    closed = w.life.close(first["packet_ref"], first_signatures)["decision"]
    w.tick()
    w.life.reopen(TICKET, 1, 1, "Second cycle")
    second, second_signatures = w.ready()
    w.put("ticket_lifecycle_events", closed["id"], {**closed, "reason": "Tampered history"})
    cases["test_corrupted_old_event_blocks_new_closure"] = w.observe(lambda: w.life.close(second["packet_ref"], second_signatures))
    return {"close": cases}


def _drop(world, bucket, key):
    with world.store.transaction() as tx:
        del tx.data[bucket, key]


def f_reopen(api):
    cases = {}
    w = World(api)
    for name, args in (("revision_not_int", ("1", 0, "r")), ("revision_bool", (True, 0, "r")), ("sequence_not_int", (1, "0", "r")),
                       ("sequence_none", (1, None, "r")), ("reason_not_a_string", (1, 0, 5)), ("reason_empty", (1, 0, "")),
                       ("reason_blank", (1, 0, "   ")), ("reason_too_long", (1, 0, "x" * 4001))):
        cases["refused_" + name] = w.observe(lambda a=args: w.life.reopen(TICKET, *a))
    cases["refused_status_closing"] = w.observe(lambda: w.life.reopen(TICKET, 1, 0, "r", expected_status="reopened"))
    cases["refused_status_none"] = w.observe(lambda: w.life.reopen(TICKET, 1, 0, "r", expected_status=None))
    cases["refused_unknown_ticket"] = w.observe(lambda: w.life.reopen("ZEUS-unknown", 1, 0, "r"))
    cases["refused_stale_revision"] = w.observe(lambda: w.life.reopen(TICKET, 2, 0, "r", expected_status="open"))
    cases["refused_stale_sequence"] = w.observe(lambda: w.life.reopen(TICKET, 1, 3, "r", expected_status="open"))
    cases["refused_status_differs_open_ticket_expected_closed"] = w.observe(lambda: w.life.reopen(TICKET, 1, 0, "r"))
    cases["reason_boundary_4000_accepted_and_trimmed_for_length_only"] = w.observe(lambda: w.life.reopen(TICKET, 1, 0, "  " + "x" * 3996 + "  ", expected_status="open"))

    # test_explicit_open_reassertion_intentionally_invalidates_old_execution
    w = World(api)
    w.put("tickets", TICKET, {**w.get("tickets", TICKET), "status": "dispatched"})
    before_bound = {"id": TICKET, "revision": 1, "content_hash": w.get("tickets", TICKET)["content_hash"]}
    w.tick()
    cases["reassertion"] = w.observe(lambda: w.life.reopen(TICKET, 1, 0, "Reconcile divergence and reassess work", expected_status="dispatched"))
    cases["reassertion_rows"] = {"dispatches": w.scan("ticket_dispatches"), "github": w.scan("ticket_github"), "state": w.state()}
    cases["reassertion_binding"] = w.observe(w.in_tx(lambda tx: api.ticket_binding(tx, {"zeus_ticket": before_bound})))
    cases["reassertion_replay"] = w.observe(lambda: w.life.reopen(TICKET, 1, 0, "Reconcile divergence and reassess work", expected_status="dispatched"))
    prepared, signatures = w.ready()
    w.life.close(prepared["packet_ref"], signatures)
    cases["reassertion_stale_retry_after_close"] = w.observe(lambda: w.life.reopen(TICKET, 1, 0, "Reconcile divergence and reassess work", expected_status="dispatched"))

    # test_consumed_reopen_does_not_override_later_manual_close (the reopen side): a reopen of an open ticket, with its explicit expected state
    w = World(api)
    prepared, signatures = w.ready()
    w.life.close(prepared["packet_ref"], signatures)
    w.tick()
    w.observe(lambda: w.life.reopen(TICKET, 1, 1, "First recurrence"))
    cases["reopen_open_ticket_explicitly"] = w.observe(lambda: w.life.reopen(TICKET, 1, 2, "Explicitly reconcile the new remote close", expected_status="open"))
    cases["reopen_open_ticket_default_state_refused"] = w.observe(lambda: w.life.reopen(TICKET, 1, 3, "again"))
    cases["reopen_history"] = [[e[0], e[1], e[2]] for e in w.state()["events"]]
    request_ids = sorted(r for r in (e["request_id"] for e in w.scan("ticket_lifecycle_events")) if r)
    cases["reopen_request_ids_are_the_digest_of_the_request"] = [
        api.digest({"ticket_id": TICKET, "revision": 1, "from_sequence": 1, "expected_status": "closed", "reason": "First recurrence"}) in request_ids,
        len(w.scan("ticket_reopens")), sorted(r["event_id"] == e["id"] for r in w.scan("ticket_reopens") for e in w.scan("ticket_lifecycle_events")
                                              if r["event_id"] == e["id"])]

    # test_reopen_projection_checks_the_whole_history
    w = World(api)
    prepared, signatures = w.ready()
    first = w.life.close(prepared["packet_ref"], signatures)["decision"]
    w.tick()
    w.life.reopen(TICKET, 1, 1, "Recurrence")
    w.put("ticket_lifecycle_events", first["id"], {**first, "reason": "Tampered older event"})
    cases["history_tampered_blocks_tickets_get_projection"] = w.observe(lambda: w.life.reopen(TICKET, 1, 2, "Again", expected_status="open"))
    cases["history_tampered_blocks_verify_closed"] = w.observe(lambda: w.life.verify_closed(w.tickets.get(TICKET)))

    # promotion unresolved
    w = World(api)
    prepared, signatures = w.ready()
    w.life.close(prepared["packet_ref"], signatures)
    w.put("promotion_intents", "intent-1", {"status": "pending", "candidate": {"zeus_ticket": {"id": TICKET}}})
    cases["promotion_unresolved_blocks_reopen"] = w.observe(lambda: w.life.reopen(TICKET, 1, 1, "Recurrence"))
    w.put("promotion_intents", "intent-1", {"status": "abandoned", "candidate": {"zeus_ticket": {"id": TICKET}}})
    cases["promotion_abandoned_allows_reopen"] = w.observe(lambda: w.life.reopen(TICKET, 1, 1, "Recurrence"))
    return {"reopen": cases}


def g_verify_closed(api):
    cases = {}
    w = World(api)
    prepared, signatures = w.ready()
    closed = w.life.close(prepared["packet_ref"], signatures)["decision"]
    ticket = w.tickets.get(TICKET)
    w.tick(30)
    cases["verify_closed_ok"] = w.observe(lambda: w.life.verify_closed(ticket))
    cases["verify_closed_calls"] = w.authority.calls[-3:]
    cases["verify_closed_equals_the_decision"] = w.life.verify_closed(ticket) == closed
    cases["verify_closed_heartbeat_reaches_policy_and_verify"] = [w.observe(lambda: w.life.verify_closed(ticket, heartbeat="beat-1")),
                                                                  w.authority.calls[-3:]]
    with w.store.transaction() as tx:
        del tx.data["ticket_trust_anchors", "deployment"]
    cases["verify_closed_pins_the_anchor_if_absent"] = [w.observe(lambda: w.life.verify_closed(ticket)), w.get("ticket_trust_anchors", "deployment")]
    w.authority.document["policy_commit"] = "c" * 40
    cases["verify_closed_anchor_differs"] = w.observe(lambda: w.life.verify_closed(ticket))
    w.authority.document["policy_commit"] = POLICY_COMMIT
    w.authority.policy_fault = api.ContractError("Out-of-band trust anchor configuration required")
    cases["verify_closed_policy_refused"] = w.observe(lambda: w.life.verify_closed(ticket))
    w.authority.policy_fault = None
    w.authority.verify_fault = api.ContractError("Signing identity revoked")
    cases["verify_closed_signature_refused"] = w.observe(lambda: w.life.verify_closed(ticket))
    w.authority.verify_fault = None

    # the ticket row against the event
    open_ticket = World(api)
    cases["verify_closed_ticket_never_closed"] = open_ticket.observe(lambda: open_ticket.life.verify_closed(open_ticket.tickets.get(TICKET)))
    cases["verify_closed_other_sequence"] = w.observe(lambda: w.life.verify_closed({**ticket, "lifecycle_sequence": 2}))
    cases["verify_closed_other_revision"] = w.observe(lambda: w.life.verify_closed({**ticket, "revision": 2}))
    cases["verify_closed_other_content_hash"] = w.observe(lambda: w.life.verify_closed({**ticket, "content_hash": "0" * 64}))
    w.tick()
    w.life.reopen(TICKET, 1, 1, "Recurrence")
    cases["verify_closed_after_reopen_is_not_a_closure"] = w.observe(lambda: w.life.verify_closed(w.tickets.get(TICKET)))

    # stored documents
    w = World(api)
    prepared, signatures = w.ready()
    closed = w.life.close(prepared["packet_ref"], signatures)["decision"]
    ticket = w.tickets.get(TICKET)
    revision = w.get("ticket_revisions", TICKET + ":1")
    w.put("ticket_revisions", TICKET + ":1", {**revision, "content_hash": "0" * 64})
    cases["verify_closed_revision_hash_mismatch"] = w.observe(lambda: w.life.verify_closed(ticket))
    with w.store.transaction() as tx:
        del tx.data["ticket_revisions", TICKET + ":1"]
    cases["verify_closed_revision_missing"] = w.observe(lambda: w.life.verify_closed(ticket))
    w.put("ticket_revisions", TICKET + ":1", revision)
    del w.artifacts.bodies[closed["packet_ref"]]
    cases["verify_closed_packet_artifact_missing"] = w.observe(lambda: w.life.verify_closed(ticket))
    w.artifacts.bodies[closed["packet_ref"]] = prepared["signing_payload"]
    del w.artifacts.bodies[closed["proof_ref"]]
    cases["verify_closed_proof_artifact_missing"] = w.observe(lambda: w.life.verify_closed(ticket))

    # evidence checked at the time of the decision: aged evidence is still fine after the decision (`now` is the event's `at`)
    w = World(api)
    prepared, signatures = w.ready()
    w.life.close(prepared["packet_ref"], signatures)
    ticket = w.tickets.get(TICKET)
    w.tick(10 * DAY)
    cases["verify_closed_ten_days_later_uses_the_event_time"] = w.observe(lambda: w.life.verify_closed(ticket))
    w.artifacts.bodies[prepared["packet"]["criteria"][0]["evidence_refs"][0]] = "{}"
    cases["verify_closed_evidence_replaced"] = w.observe(lambda: w.life.verify_closed(ticket))
    return {"verify_closed": cases}


def run(api) -> dict:
    groups = {}
    for step in (a_surface, b_helpers, c_prepare, d_review, e_close, f_reopen, g_verify_closed):
        groups.update(step(api))
    return {**groups, "m7_tests": M7_TESTS, "cases_per_group": {k: len(v) for k, v in groups.items()}}
