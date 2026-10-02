"""Shared S8 scenario steps (`review.sdd`): M7 `application/sdd.py` (`SDD`: `register`, `status`, `observe`, `propose`, `request_advance`,
`record_gate_verdict`, `record_transfer`), characterized BEFORE the module moves into REVIEW (S8 batch B4, DESIGN-s8 §23 V28: R-sdd1 the injected
`ticket_binding`, R-sdd2 the injected `clock`, R-sdd3 the seven own buckets). The golden is placement-neutral: it observes SOURCE behaviour only.

M7's `tests/test_sdd.py` has 20 tests and NONE of them drives `SDD` outside PostgreSQL: 13 test the domain and adapter functions (spec/observation
validation, the review export, the CLI) and 7 are `real_postgres` integration tests of `SDD` itself. So the cases here mirror the SEVEN integration
flows over a `MemoryStore` instead (idempotent register/observe/propose and the notifications; the transition CAS reduced to its sequential half; the
superseded spec; identical observations per iteration; the stale ticket and the corrupt artifact; journal tampering and the appended sidecar event;
transfer evidence), plus every other refusal and branch of the module. Reported in `m7_tests`:
- the 13 non-PostgreSQL tests: `domain.sdd` (already moved), `adapters.sdd` and `zeus sdd` (S10): not this family;
- the 7 `real_postgres` tests: carried to the units/.pg step (the thread race of the transition CAS needs the real store's serialization).

Layer: harness (never shipped)

This module never imports `codex_harness`: everything arrives through `api`. LABELLED doubles (nothing here is an actual device run, human
acceptance or provider verification):
- the store is a `MemoryStore`; the `tickets` and `ticket_revisions` rows are PLANTED in the shape `Tickets` leaves (id, revision, content_hash, status, lifecycle_sequence; the
  revision's content, whose digest is the content_hash);
  the ticket binding rule is the real intake function on both sides (M7's imported by the module, the target's injected);
- `FakeArtifacts`: `put(body, kind) -> {"ref"}`, `document(ref)`, `inspect(ref)` and `text(ref, max_bytes)` over a dict, content-addressed, with
  scripted corruption and removal;
- `Provider`: the human decision provider; `verify(claim)` answers a scripted decision and records every claim;
- the clock is the harness's, advanced one millisecond after every call (the reference's `utcnow` reads it through the harness's datetime patch,
  the target receives the same clock through R-sdd2).
The whole-store digest (16 hex) and the artifact count are recorded before and after every call, with a `wrote` flag.
"""

from __future__ import annotations

import hashlib
import inspect
import json

HASH = "a" * 64
SOURCE = {"mode": "working_tree_draft", "repository": "contract-test", "revision": None, "path": "spec.json"}
GIT_SOURCE = {"mode": "git", "repository": "contract-test", "revision": "b" * 40, "path": "spec.json"}
ENV_FIELDS = ["device_id", "manufacturer", "model", "form_factor", "platform", "os_version", "one_ui_version", "webview_version", "app_build_hash",
              "locale", "timezone", "orientation", "backend_revision", "data_revision", "reset_receipt", "physical_device"]

M7_TESTS = {
    "mirrored_over_a_memory_store": [
        "test_real_postgres_idempotency_gaps_notifications_and_restart (register/observe/propose replays, the three notifications, a restarted SDD)",
        "test_real_postgres_transition_cas_and_superseded_spec (the sequential half: one blocked, the stale one refused; the superseded spec)",
        "test_real_postgres_identical_observations_stay_bound_to_each_iteration",
        "test_real_postgres_stale_ticket_and_corrupt_artifact_rejected (a planted lifecycle change; a corrupted artifact)",
        "test_real_postgres_journal_tampering_is_detected",
        "test_appended_sidecar_event_never_softens_a_journal_break",
        "test_real_postgres_transfer_evidence_cannot_change_model_authority (record_transfer; the model_routing half is another family)"],
    "left_out": {
        "the seven real_postgres tests as such": "integration: a disposable PostgreSQL; carried to the units/.pg step (the transition CAS race is a thread race)",
        "test_missing_spec_empty_coverage_and_unknown_authority_fields_rejected, test_retired_ids_cannot_be_deleted_or_resurrected, "
        "test_requirement_meaning_and_retirement_preserve_history, test_adb_diagnostics_are_not_transport_rows, "
        "test_observations_never_create_oracles_and_environment_changes_identity, test_claims_cannot_unlock_eight_stage_report, "
        "test_bounded_json_duplicate_keys_and_export_integrity, test_review_embedded_content_cannot_escape_json_script, "
        "test_replay_export_refuses_unknown_target_financial_flows_and_missing_bindings, "
        "test_replay_attributes_every_assertion_to_its_oracle_and_requirements_at_runtime, test_gwt_must_be_lists_never_one_line_strings, "
        "test_replay_export_is_idempotent_and_never_overwrites_a_different_draft": "domain.sdd (moved in step 1) and adapters.sdd (S10); not SDD",
        "test_offline_cli_review_runs_without_database_access": "the `zeus sdd` CLI (S10 entry)"}}


def sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=repr).encode()).hexdigest()[:16]


def store_digest(store):
    with store.transaction() as tx:
        return sha([[r["bucket"], r["id"], sha(r["body"])] for r in tx.records()])


def put(store, bucket, key, body):
    with store.transaction() as tx:
        tx.put(bucket, key, body)


def get(store, bucket, key):
    with store.transaction() as tx:
        return tx.get(bucket, key)


def scan(store, bucket):
    with store.transaction() as tx:
        return tx.scan(bucket)


def spec(**over):
    document = {"schema": "zeus.sdd.v1", "id": "spec.alpha", "title": "Alpha", "intent": "Review the scenario intent", "personas": ["owner"],
                "requirements": [{"id": "REQ.a", "statement": "The owner reviews the intent", "risk": "normal", "status": "active"}],
                "scenarios": [{"id": "SCN.intent-review", "title": "Intent review", "status": "active", "requirement_ids": ["REQ.a"],
                               "given": ["a draft"], "when": ["the owner reads it"], "then": ["the intent is shown"], "device_profiles": ["DEV.a"],
                               "bindings": []}],
                "devices": [{"id": "DEV.a", "manufacturer": "samsung", "platform": "android", "form_factor": "phone", "physical_required": True,
                             "conditions": ["portrait"]}],
                "design": {"components": "components", "icons": "icons", "tokens": "tokens", "required_stories": ["story"]},
                "target": {"kind": "unconfigured", "app_id": None, "build_hash": None, "alpha_url": None}, "reset_contract": "reset between runs"}
    document.update(over)
    return document


def observation_data():
    """M7 `observation_data`: explicitly unverified input data, not a device run."""
    env = dict.fromkeys(ENV_FIELDS, "unverified-contract-input")
    env.update(physical_device=False, form_factor="unknown", orientation="unknown")
    event = {"sequence": 1, "scenario_id": "SCN.intent-review", "kind": "observation", "name": "contract input",
             "observed": "Observed behavior is not an oracle", "source_ref": "unverified-contract-input", "timestamp": None,
             "observed_timestamp": "2026-09-09T00:00:00+00:00"}
    return env, [event]


class FakeArtifacts:
    """LABELLED content-addressed store; `corrupt(ref)` and `remove(ref)` script the faults."""

    def __init__(self, api):
        self.api, self.bodies, self.broken, self.calls = api, {}, set(), []

    def put(self, body, kind):
        ref = "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()
        self.bodies[ref] = body
        self.calls.append(["put", kind])
        return {"ref": ref, "kind": kind}

    def _read(self, ref):
        self.api.require(ref in self.bodies, "Artifact missing")
        self.api.require(ref not in self.broken, "Artifact modified")
        return self.bodies[ref]

    def document(self, ref):
        return json.loads(self._read(ref))

    def inspect(self, ref):
        self._read(ref)
        return {"ref": ref}

    def text(self, ref, max_bytes):
        body = self._read(ref)
        self.api.require(len(body.encode("utf-8")) <= max_bytes, "Artifact exceeds text budget")
        return body

    def corrupt(self, ref):
        self.broken.add(ref)

    def remove(self, ref):
        self.bodies.pop(ref, None)


class Provider:
    """LABELLED human decision provider: `mode` scripts what `verify` answers; every claim is recorded."""

    def __init__(self, mode="authenticated"):
        self.mode, self.claims = mode, []

    def verify(self, claim):
        self.claims.append(dict(claim))
        if self.mode == "not_a_dict":
            return "yes"
        decision = {**claim, "authenticated": self.mode != "unauthenticated"}
        if self.mode == "unbound":
            decision["actor"] = "someone-else"
        if self.mode == "authenticated_not_bool":
            decision["authenticated"] = 1
        return decision


class NoVerify:
    """LABELLED provider without a `verify` method."""


class World:
    def __init__(self, api, provider=None):
        self.api = api
        self.store = api.MemoryStore()
        self.artifacts = FakeArtifacts(api)
        self.provider = provider
        self.sdd = api.make(self.store, self.artifacts, provider)

    def ticket(self, ticket_id="T-1", revision=1, status="open", lifecycle_sequence=0):
        content = {"title": "SDD contract validation " + str(revision), "ticket": ticket_id}
        row = {"id": ticket_id, "revision": revision, "content_hash": self.api.digest(content), "status": status, "lifecycle_sequence": lifecycle_sequence}
        put(self.store, "tickets", ticket_id, row)
        put(self.store, "ticket_revisions", "%s:%s" % (ticket_id, revision), {"id": "%s:%s" % (ticket_id, revision), "content": content})
        return row

    def edit_ticket(self, ticket_id="T-1", **fields):
        put(self.store, "tickets", ticket_id, {**get(self.store, "tickets", ticket_id), **fields})

    def register(self, document=None, ticket_id="T-1", revision=1, source=None):
        return self.sdd.register(document if document is not None else spec(), ticket_id, revision, source or SOURCE)

    def row(self, iteration_id):
        return get(self.store, "sdd_iterations", iteration_id)

    def call(self, fn, *args, **kwargs):
        """One call with the whole-store digest and the artifact count before and after, then one tick of the clock."""
        before, arts = store_digest(self.store), len(self.artifacts.bodies)
        try:
            out = {"outcome": "returned", "value": fn(*args, **kwargs)}
        except BaseException as exc:  # noqa: BLE001 - what propagates is the observation
            out = {"outcome": "raised", "type": type(exc).__name__, "message": str(exc), "is_contract_error": isinstance(exc, self.api.ContractError),
                   "cause_type": None if exc.__cause__ is None else type(exc.__cause__).__name__}
        after = store_digest(self.store)
        self.api.advance(0.001)
        return {**out, "store_before": before, "store_after": after, "wrote": before != after,
                "artifacts_added": len(self.artifacts.bodies) - arts}

    def registered(self, **options):
        self.ticket()
        return self.register(**options)

    def runner_document(self, row, statement="spec_integrity", stage="spec_discussion", exit_status=0, verdict="PASS", receipt_over=None, ref=None):
        defs = self.api.SDD.statement_definitions(row, stage)
        receipt = {"run_id": row["id"], "cycle": row["revision"], "statement_id": statement, "definition_hash": defs[statement], "artifact_hash": None,
                   "environment_hash": None, "exit_status": exit_status}
        receipt.update(receipt_over or {})
        reference = ref or self.artifacts.put(self.api.canonical(receipt), "gate-receipt")["ref"]
        return {"statement_id": statement, "stage": stage, "artifact_hash": None, "environment_hash": None, "verdict": verdict,
                "origin": "runner_receipt", "receipt_ref": reference, "exit_status": exit_status, "actor": None, "authority": None}

    @staticmethod
    def reviewer_document(statement="human_scope", stage="spec_discussion", verdict="PASS", authority="authenticated_provider", **over):
        return {"statement_id": statement, "stage": stage, "verdict": verdict, "origin": "reviewer_decision", "actor": "alice", "authority": authority,
                "receipt_ref": None, "exit_status": None, **over}


def world(api, provider=None):
    return World(api, provider)


# ----- steps -------------------------------------------------------------------------------------------------------------------------------
def a_surface(api):
    params = list(inspect.signature(api.SDD.__init__).parameters.values())
    w = world(api, Provider())
    static = {n: isinstance(inspect.getattr_static(api.SDD, n), staticmethod) for n in ("statement_definitions", "_gate_verdicts")}
    return {"surface": {
        "constructor_positional": [p.name for p in params if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)],
        "constructor_human_provider_default": params[3].default,
        "methods": {n: str(inspect.signature(getattr(api.SDD, n))) for n in ("register", "status", "observe", "propose", "request_advance",
                                                                           "record_gate_verdict", "record_transfer", "statement_definitions")},
        "static_methods": static, "stages": [[k, s, o, list(c)] for k, s, o, c in api.STAGES],
        "attributes": {"store": w.sdd.store is w.store, "artifacts": w.sdd.artifacts is w.artifacts, "human_provider": w.sdd.human_provider is w.provider},
        "default_has_no_provider": api.make(w.store, w.artifacts, None).human_provider}}


def b_register(api):
    cases = {}
    w = world(api)
    w.ticket()
    first = w.call(w.register)
    cases["first_register"] = {"m7_test": "test_real_postgres_idempotency_gaps_notifications_and_restart", **first,
                               "events": scan(w.store, "sdd_events"), "heads": scan(w.store, "sdd_spec_heads"),
                               "notifications": scan(w.store, "sdd_notifications")}
    cases["replay_returns_the_old_row"] = {"m7_test": "test_real_postgres_idempotency_gaps_notifications_and_restart", **w.call(w.register),
                                           "same_row": first["value"] == w.row(first["value"]["id"]), "events": len(scan(w.store, "sdd_events"))}
    cases["git_source"] = {"m7_test": "none", **w.call(w.register, source=GIT_SOURCE)}
    document = spec()
    document["intent"] += " Revision two."
    changed = w.call(w.register, document=document)
    cases["revision_two_supersedes"] = {"m7_test": "test_real_postgres_transition_cas_and_superseded_spec", **changed,
                                        "heads": scan(w.store, "sdd_spec_heads")}
    cases["first_is_superseded"] = {"m7_test": "test_real_postgres_transition_cas_and_superseded_spec",
                                    **w.call(w.sdd.status, first["value"]["id"])}
    meaning = spec(requirements=[{"id": "REQ.a", "statement": "A different meaning", "risk": "normal", "status": "active"}])
    cases["changed_requirement_meaning"] = {"m7_test": "none", **w.call(w.register, document=meaning)}
    cases["deleted_requirement"] = {"m7_test": "none", **w.call(w.register, document=spec(
        requirements=[{"id": "REQ.b", "statement": "other", "risk": "normal", "status": "active"}],
        scenarios=[{**spec()["scenarios"][0], "requirement_ids": ["REQ.b"]}]))}
    cases["other_spec_id_is_a_new_head"] = {"m7_test": "none", **w.call(w.register, document=spec(id="spec.beta"))}
    for name, edit in (("spec_not_a_dict", lambda: []), ("spec_schema", lambda: spec(schema="zeus.sdd.v2")), ("spec_no_scenarios", lambda: spec(scenarios=[])),
                       ("spec_unknown_field", lambda: {**spec(), "extra": 1})):
        w2 = world(api)
        w2.ticket()
        cases[name] = {"m7_test": "none", **w2.call(w2.register, document=edit())}
    for name, source in (("source_not_a_dict", "x"), ("source_extra_key", {**SOURCE, "extra": 1}), ("source_missing_key", {"mode": "git"}),
                         ("source_mode", {**SOURCE, "mode": "svn"}), ("source_repository_blank", {**SOURCE, "repository": " "}),
                         ("source_path_not_text", {**SOURCE, "path": 5}), ("draft_with_revision", {**SOURCE, "revision": "b" * 40}),
                         ("git_without_revision", {**GIT_SOURCE, "revision": None}), ("git_short_revision", {**GIT_SOURCE, "revision": "abc"}),
                         ("git_uppercase_revision", {**GIT_SOURCE, "revision": "B" * 40}), ("git_revision_64_hex", {**GIT_SOURCE, "revision": "c" * 64})):
        w2 = world(api)
        w2.ticket()
        cases[name] = {"m7_test": "none", **w2.call(w2.register, source=source)}
    w2 = world(api)
    cases["ticket_missing"] = {"m7_test": "none", **w2.call(w2.register)}
    w2.ticket()
    cases["ticket_stale_revision"] = {"m7_test": "none", **w2.call(w2.register, revision=2)}
    w2.edit_ticket(status="closed")
    cases["ticket_closed"] = {"m7_test": "none", **w2.call(w2.register)}
    w2.edit_ticket(status="open", lifecycle_sequence=1)
    cases["ticket_lifecycle_changed"] = {"m7_test": "none", **w2.call(w2.register)}
    return {"register": cases}


def c_observe_propose(api):
    cases = {}
    w = world(api)
    row = w.registered()
    rid = row["id"]
    env, events = observation_data()
    m7 = "test_real_postgres_idempotency_gaps_notifications_and_restart"
    events[0]["sequence"] = 2
    observed = w.call(w.sdd.observe, rid, env, events, "contract-test-input")
    cases["observe_with_a_gap"] = {"m7_test": m7, **observed, "notifications": scan(w.store, "sdd_notifications"),
                                   "observations": scan(w.store, "sdd_observations"), "events": len(scan(w.store, "sdd_events"))}
    cases["observe_replay"] = {"m7_test": m7, **w.call(w.sdd.observe, rid, env, events, "contract-test-input"),
                               "same_receipt": True, "events": len(scan(w.store, "sdd_events"))}
    observation = observed["value"]
    proposed = w.call(w.sdd.propose, rid, observation["id"])
    cases["propose"] = {"m7_test": m7, **proposed, "artifact": w.artifacts.document(proposed["value"]["artifact_ref"]),
                        "events": len(scan(w.store, "sdd_events"))}
    cases["propose_replay"] = {"m7_test": m7, **w.call(w.sdd.propose, rid, observation["id"])}
    cases["restarted_status"] = {"m7_test": m7, **w.call(api.make(w.store, w.artifacts, None).status, rid)}

    w = world(api)
    row = w.registered()
    rid = row["id"]
    cases["observe_complete"] = {"m7_test": "none", **w.call(w.sdd.observe, rid, *observation_data(), "contract-test-input"),
                                 "notifications": scan(w.store, "sdd_notifications")}
    cases["observe_unknown_iteration"] = {"m7_test": "none", **w.call(w.sdd.observe, "missing", *observation_data(), "contract-test-input")}
    env, events = observation_data()
    for name, args in (("environment_incomplete", ({**env, "extra": 1}, events, "s")), ("environment_form_factor", ({**env, "form_factor": "watch"}, events, "s")),
                       ("environment_physical_not_bool", ({**env, "physical_device": 1}, events, "s")), ("events_empty", (env, [], "s")),
                       ("events_unordered", (env, [{**events[0], "sequence": 2}, events[0]], "s")), ("event_kind", (env, [{**events[0], "kind": "x"}], "s")),
                       ("event_timestamp_naive", (env, [{**events[0], "observed_timestamp": "2026-09-09T00:00:00"}], "s")),
                       ("source_name_blank", (env, events, "")), ("source_name_too_long", (env, events, "x" * 201)), ("source_name_not_text", (env, events, 5))):
        cases["observe_" + name] = {"m7_test": "none", **w.call(w.sdd.observe, rid, *args)}
    # a second iteration with the identical observation stays bound to each iteration
    first = w.call(w.sdd.observe, rid, *observation_data(), "contract-test-input")["value"]
    first_proposal = w.sdd.propose(rid, first["id"])
    w.ticket(revision=2)
    newer = w.register(revision=2)
    second = w.call(w.sdd.observe, newer["id"], *observation_data(), "contract-test-input")
    second_proposal = w.call(w.sdd.propose, newer["id"], second["value"]["id"])
    cases["identical_observation_other_iteration"] = {
        "m7_test": "test_real_postgres_identical_observations_stay_bound_to_each_iteration", "second_observation": second, "second_proposal": second_proposal,
        "same_artifact_ref": first["artifact_ref"] == second["value"]["artifact_ref"],
        "different_proposal_ref": first_proposal["artifact_ref"] != second_proposal["value"]["artifact_ref"],
        "bound": second_proposal["value"]["iteration_id"] == newer["id"], "first_status": w.call(w.sdd.status, rid)}
    cases["observe_superseded_iteration"] = {"m7_test": "test_real_postgres_transition_cas_and_superseded_spec", **w.call(w.sdd.observe, rid, *observation_data(), "x")}
    # propose refusals
    w = world(api)
    row = w.registered()
    rid = row["id"]
    receipt = w.sdd.observe(rid, *observation_data(), "contract-test-input")
    cases["propose_unknown_iteration"] = {"m7_test": "none", **w.call(w.sdd.propose, "missing", receipt["id"])}
    cases["propose_unknown_observation"] = {"m7_test": "none", **w.call(w.sdd.propose, rid, "missing")}
    other = w.register(document=spec(id="spec.beta"))
    cases["propose_observation_of_another_iteration"] = {"m7_test": "none", **w.call(w.sdd.propose, other["id"], receipt["id"])}
    put(w.store, "sdd_observations", receipt["id"], {**receipt, "environment_hash": "0" * 64})
    cases["propose_environment_identity_changed"] = {"m7_test": "none", **w.call(w.sdd.propose, rid, receipt["id"])}
    put(w.store, "sdd_observations", receipt["id"], receipt)
    w.artifacts.remove(receipt["artifact_ref"])
    cases["propose_observation_artifact_missing"] = {"m7_test": "none", **w.call(w.sdd.propose, rid, receipt["id"])}
    return {"observe_propose": cases}


def d_status(api):
    cases = {}
    m7 = "test_real_postgres_journal_tampering_is_detected"
    w = world(api)
    row = w.registered()
    rid = row["id"]
    cases["fresh"] = {"m7_test": "none", **w.call(w.sdd.status, rid)}
    cases["unknown"] = {"m7_test": "none", **w.call(w.sdd.status, "missing")}
    w.sdd.observe(rid, *observation_data(), "contract-test-input")
    cases["after_observe"] = {"m7_test": "none", **w.call(w.sdd.status, rid)}
    w.edit_ticket(revision=2)
    cases["superseded_ticket_by_revision"] = {"m7_test": "test_real_postgres_stale_ticket_and_corrupt_artifact_rejected", **w.call(w.sdd.status, rid)}
    cases["observe_after_ticket_revision_change"] = {"m7_test": "test_real_postgres_stale_ticket_and_corrupt_artifact_rejected",
                                                     **w.call(w.sdd.observe, rid, *observation_data(), "x")}
    w.edit_ticket(revision=1, lifecycle_sequence=1)
    cases["observe_after_lifecycle_change"] = {"m7_test": "test_real_postgres_stale_ticket_and_corrupt_artifact_rejected",
                                               **w.call(w.sdd.observe, rid, *observation_data(), "x")}
    w.edit_ticket(lifecycle_sequence=0, status="closed")
    cases["observe_on_a_closed_ticket"] = {"m7_test": "none", **w.call(w.sdd.observe, rid, *observation_data(), "x")}
    cases["ticket_removed_is_superseded"] = {"m7_test": "none", **(lambda: (put(w.store, "tickets", "T-1", None), w.call(w.sdd.status, rid))[1])()}

    # the corrupt spec artifact
    w = world(api)
    row = w.registered()
    w.artifacts.corrupt(row["spec_ref"])
    cases["corrupt_spec_artifact"] = {"m7_test": "test_real_postgres_stale_ticket_and_corrupt_artifact_rejected", **w.call(w.sdd.status, row["id"])}
    w = world(api)
    row = w.registered()
    put(w.store, "sdd_iterations", row["id"], {**row, "spec_hash": "0" * 64})
    cases["spec_snapshot_changed"] = {"m7_test": "none", **w.call(w.sdd.status, row["id"])}

    # the journal
    w = world(api)
    row = w.registered()
    rid = row["id"]
    event = scan(w.store, "sdd_events")[0]
    put(w.store, "sdd_events", rid + ":00000001", {**event, "kind": "unauthorized_edit"})
    cases["journal_tampered"] = {"m7_test": m7, **w.call(w.sdd.status, rid)}
    put(w.store, "sdd_events", rid + ":00000001", event)
    cases["journal_restored"] = {"m7_test": "none", **w.call(w.sdd.status, rid)}
    current = w.row(rid)
    put(w.store, "sdd_events", rid + ":00000001", {**event, "kind": "unauthorized_edit"})
    sidecar = {"iteration_id": rid, "sequence": current["sequence"] + 1, "previous_hash": current["event_hash"], "at": "2026-09-22T00:00:01+00:00",
               "kind": "compaction_marker", "refs": [], "note": "claims to summarize earlier events"}
    sidecar["hash"] = api.digest(sidecar)
    put(w.store, "sdd_events", rid + ":%08d" % sidecar["sequence"], sidecar)
    put(w.store, "sdd_iterations", rid, {**current, "sequence": sidecar["sequence"], "event_hash": sidecar["hash"]})
    cases["appended_sidecar_does_not_soften_the_break"] = {"m7_test": "test_appended_sidecar_event_never_softens_a_journal_break", **w.call(w.sdd.status, rid),
                                                           "events_retained": len(scan(w.store, "sdd_events"))}
    w = world(api)
    row = w.registered()
    rid = row["id"]
    put(w.store, "sdd_iterations", rid, {**row, "sequence": 2})
    cases["journal_head_changed_count"] = {"m7_test": "none", **w.call(w.sdd.status, rid)}
    put(w.store, "sdd_iterations", rid, {**row, "event_hash": "0" * 64})
    cases["journal_head_changed_hash"] = {"m7_test": "none", **w.call(w.sdd.status, rid)}
    event = scan(w.store, "sdd_events")[0]
    put(w.store, "sdd_events", rid + ":00000001", {**event, "sequence": 3})
    put(w.store, "sdd_iterations", rid, row)
    cases["journal_sequence_gap"] = {"m7_test": "none", **w.call(w.sdd.status, rid)}
    return {"status": cases}


def e_gate(api):
    cases = {}
    m7 = "none"
    w = world(api)
    row = w.registered()
    rid = row["id"]
    cases["statement_definitions"] = {"m7_test": m7, "spec_discussion": api.SDD.statement_definitions(row, "spec_discussion"),
                                      "qa_evidence": api.SDD.statement_definitions(row, "qa_evidence")}
    cases["not_a_dict"] = {"m7_test": m7, **w.call(w.sdd.record_gate_verdict, rid, [])}
    cases["authenticated_without_provider"] = {"m7_test": m7, **w.call(w.sdd.record_gate_verdict, rid, w.reviewer_document())}
    cases["unknown_iteration"] = {"m7_test": m7, **w.call(w.sdd.record_gate_verdict, "missing", w.runner_document(row))}
    cases["unknown_stage"] = {"m7_test": m7, **w.call(w.sdd.record_gate_verdict, rid, {**w.runner_document(row), "stage": "nowhere"})}
    cases["statement_not_in_stage"] = {"m7_test": m7, **w.call(w.sdd.record_gate_verdict, rid, {**w.runner_document(row), "statement_id": "monitoring"})}
    cases["unknown_fields"] = {"m7_test": m7, **w.call(w.sdd.record_gate_verdict, rid, {**w.runner_document(row), "extra": 1})}
    cases["runner_pass"] = {"m7_test": m7, **w.call(w.sdd.record_gate_verdict, rid, w.runner_document(row)),
                            "events": len(scan(w.store, "sdd_events")), "last_event": scan(w.store, "sdd_events")[-1]}
    cases["status_after_runner_pass"] = {"m7_test": m7, **w.call(w.sdd.status, rid)}
    cases["runner_receipt_not_bound"] = {"m7_test": m7, **w.call(w.sdd.record_gate_verdict, rid, w.runner_document(
        w.row(rid), receipt_over={"statement_id": "human_scope"}))}
    cases["runner_receipt_exit_differs"] = {"m7_test": m7, **w.call(w.sdd.record_gate_verdict, rid, w.runner_document(
        w.row(rid), verdict="FAIL", exit_status=1, receipt_over={"exit_status": 0}))}
    cases["runner_receipt_artifact_missing"] = {"m7_test": m7, **w.call(w.sdd.record_gate_verdict, rid, w.runner_document(
        w.row(rid), ref="sha256:" + "9" * 64))}
    cases["runner_receipt_corrupt"] = {"m7_test": m7, **(lambda doc: (w.artifacts.corrupt(doc["receipt_ref"]), w.call(
        w.sdd.record_gate_verdict, rid, doc))[1])(w.runner_document(w.row(rid), receipt_over={"run_id": "other"}))}
    cases["runner_fail"] = {"m7_test": m7, **w.call(w.sdd.record_gate_verdict, rid, w.runner_document(w.row(rid), verdict="FAIL", exit_status=1,
                                                                                                         receipt_over={"exit_status": 1}))}
    cases["runner_pass_with_nonzero_exit"] = {"m7_test": m7, **w.call(w.sdd.record_gate_verdict, rid, w.runner_document(
        w.row(rid), exit_status=2, receipt_over={"exit_status": 2}))}
    cases["runner_on_a_human_statement"] = {"m7_test": m7, **w.call(w.sdd.record_gate_verdict, rid, w.runner_document(w.row(rid), statement="human_scope"))}
    cases["unauthenticated_reviewer_claim"] = {"m7_test": m7, **w.call(w.sdd.record_gate_verdict, rid, w.reviewer_document(authority="unauthenticated_claim"))}
    cases["reviewer_without_actor"] = {"m7_test": m7, **w.call(w.sdd.record_gate_verdict, rid, w.reviewer_document(actor=""))}
    cases["status_after_claims"] = {"m7_test": m7, **w.call(w.sdd.status, rid)}

    # a provider
    for name, mode, document in (("authenticated", "authenticated", None), ("unauthenticated_result", "unauthenticated", None),
                                 ("result_not_bound", "unbound", None), ("result_not_a_dict", "not_a_dict", None),
                                 ("authenticated_not_a_bool", "authenticated_not_bool", None)):
        w2 = world(api, Provider(mode))
        row2 = w2.registered()
        out = w2.call(w2.sdd.record_gate_verdict, row2["id"], w2.reviewer_document())
        cases["provider_" + name] = {"m7_test": m7, **out, "claims": w2.provider.claims, "last_event": scan(w2.store, "sdd_events")[-1],
                                     "gate": w2.call(w2.sdd.status, row2["id"])["value"]["gates"]["spec_discussion"]}
    w2 = world(api, NoVerify())
    row2 = w2.registered()
    cases["provider_without_verify"] = {"m7_test": m7, **w2.call(w2.sdd.record_gate_verdict, row2["id"], w2.reviewer_document())}

    # retractions
    w2 = world(api, Provider("authenticated"))
    row2 = w2.registered()
    rid2 = row2["id"]
    w2.sdd.record_gate_verdict(rid2, w2.reviewer_document())
    retract = {"statement_id": "human_scope", "stage": "spec_discussion", "verdict": "RETRACT", "origin": "reviewer_decision", "actor": "alice",
               "authority": "authenticated_provider", "retracts": 2, "receipt_ref": None, "exit_status": None}
    cases["retraction_wrong_target"] = {"m7_test": m7, **w2.call(w2.sdd.record_gate_verdict, rid2, {**retract, "retracts": 1})}
    cases["retraction_other_actor"] = {"m7_test": m7, **w2.call(w2.sdd.record_gate_verdict, rid2, {**retract, "actor": "mallory"})}
    cases["retraction"] = {"m7_test": m7, **w2.call(w2.sdd.record_gate_verdict, rid2, retract),
                           "gate": w2.call(w2.sdd.status, rid2)["value"]["gates"]["spec_discussion"]}
    cases["retraction_unauthenticated_kept_as_claim"] = {"m7_test": m7, **w2.call(w2.sdd.record_gate_verdict, rid2, {**retract, "retracts": 2,
                                                                                                                    "authority": "unauthenticated_claim"})}
    return {"gate": cases}


def f_advance(api):
    cases = {}
    w = world(api)
    row = w.registered()
    rid = row["id"]
    m7 = "test_real_postgres_transition_cas_and_superseded_spec"
    first = w.call(w.sdd.request_advance, rid, 1)
    cases["blocked"] = {"m7_test": m7, **first, "notifications": scan(w.store, "sdd_notifications"), "last_event": scan(w.store, "sdd_events")[-1]}
    cases["stale_sequence"] = {"m7_test": m7, **w.call(w.sdd.request_advance, rid, 1)}
    cases["unknown_iteration"] = {"m7_test": "none", **w.call(w.sdd.request_advance, "missing", 1)}
    cases["notification_count_after_a_second_block"] = {"m7_test": "none", **w.call(w.sdd.request_advance, rid, 2),
                                                        "notifications": scan(w.store, "sdd_notifications")}
    w.sdd.record_gate_verdict(rid, w.runner_document(w.row(rid)))
    cases["blocked_with_one_statement_passed"] = {"m7_test": "none", **w.call(w.sdd.request_advance, rid, w.row(rid)["sequence"])}
    w.edit_ticket(status="closed")
    cases["advance_on_a_closed_ticket"] = {"m7_test": "none", **w.call(w.sdd.request_advance, rid, w.row(rid)["sequence"])}
    w.edit_ticket(status="open")
    w.register(document=spec(intent="Revision two."))
    cases["advance_on_a_superseded_spec"] = {"m7_test": m7, **w.call(w.sdd.request_advance, rid, w.row(rid)["sequence"])}
    return {"advance": cases}


def g_transfer(api):
    cases = {}
    m7 = "test_real_postgres_transfer_evidence_cannot_change_model_authority"
    w = world(api)
    row = w.registered()
    rid = row["id"]
    record = {"task_family": "frontend.selector-export", "contract_hash": "a" * 64, "guardrail_hash": "b" * 64, "toolchain_hash": "c" * 64,
              "source_model": "gpt-6-astra", "target_model": "gpt-5.6-sol", "evidence_refs": [row["spec_ref"]]}
    cases["record"] = {"m7_test": m7, **w.call(w.sdd.record_transfer, rid, record), "candidates": scan(w.store, "sdd_transfer_candidates"),
                       "last_event": scan(w.store, "sdd_events")[-1]}
    cases["replay"] = {"m7_test": m7, **w.call(w.sdd.record_transfer, rid, record)}
    cases["sol_to_terra"] = {"m7_test": "none", **w.call(w.sdd.record_transfer, rid, {**record, "source_model": "gpt-5.6-sol", "target_model": "gpt-5.6-terra"})}
    for name, change in (("wildcard_family", {"task_family": "*"}), ("family_blank", {"task_family": ""}), ("family_too_long", {"task_family": "x" * 101}),
                         ("wrong_order", {"target_model": "gpt-5.6-terra"}), ("unknown_source", {"source_model": "other"}),
                         ("contract_hash_short", {"contract_hash": "abc"}), ("guardrail_hash_not_text", {"guardrail_hash": 5}),
                         ("evidence_empty", {"evidence_refs": []}), ("evidence_51", {"evidence_refs": [row["spec_ref"]] * 51}),
                         ("evidence_not_text", {"evidence_refs": [5]}), ("evidence_missing", {"evidence_refs": ["sha256:" + "9" * 64]}),
                         ("extra_key", {"extra": 1})):
        cases[name] = {"m7_test": m7 if name == "wildcard_family" else "none", **w.call(w.sdd.record_transfer, rid, {**record, **change})}
    cases["record_not_a_dict"] = {"m7_test": "none", **w.call(w.sdd.record_transfer, rid, [])}
    cases["missing_key"] = {"m7_test": "none", **w.call(w.sdd.record_transfer, rid, {k: v for k, v in record.items() if k != "evidence_refs"})}
    cases["unknown_iteration"] = {"m7_test": "none", **w.call(w.sdd.record_transfer, "missing", record)}
    w.edit_ticket(status="closed")
    cases["closed_ticket"] = {"m7_test": "none", **w.call(w.sdd.record_transfer, rid, {**record, "task_family": "frontend.other"})}
    return {"transfer": cases}


def run(api) -> dict:
    groups = {}
    for step in (a_surface, b_register, c_observe_propose, d_status, e_gate, f_advance, g_transfer):
        groups.update(step(api))
    return {**groups, "m7_tests": M7_TESTS, "cases_per_group": {k: len(v) for k, v in groups.items()}}
