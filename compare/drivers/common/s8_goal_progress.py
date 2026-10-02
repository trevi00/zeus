"""Shared S8 scenario steps (`intake.goal_progress`): M7 `application/goal_progress.py` (`validate_manifest`, `definition_hash`, `evaluate_criterion`,
`admit_dispatch`, `GoalProgress.report`, `compare_reports`), characterized BEFORE the module moves into INTAKE (S8 batch B1). The golden is
placement-neutral: it observes SOURCE behaviour only.

Each case is labelled with the M7 test it mirrors (`m7_test`), or `none`. M7's `tests/test_goal_progress.py` (9 tests) drives the module through
the GitHub/ssh-keygen lifecycle fixture, `Tickets.dispatch` and the CLI; the golden is MODULE-level instead: the ticket, revision, closure and
lifecycle-event rows are PLANTED the way `Tickets.create`/`update` and `application.ticket_lifecycle.transition` leave them (`transition` itself is
called, so the events are real chains). Left out, by name, in `m7_tests`: `test_row2_remote_close_review_vote_and_task_success_do_not_count` (GitHub
sync, review and Workflow), `test_row4_goal_bound_dispatch_*` and `test_row4_resolved_and_unverified_criteria_refuse_dispatch_*` (`Tickets.dispatch`,
which owns `application/tickets.py`), `test_row6_cli_*` (the CLI, S10); their module-level halves (`admit_dispatch`, the unverified statuses) are cases.

Layer: harness (never shipped)

This module never imports `codex_harness`: everything arrives through `api`. The store is a MemoryStore. The whole-store digest (16 hex) is recorded
before and after every call with an `unchanged` flag (the module writes nothing). The clock is the harness's.
"""

from __future__ import annotations

import hashlib
import inspect
import json
from copy import deepcopy

M7_TESTS = {
    "covered": ["test_row1_pending_then_local_close_resolves_exact_denominator (a planted close)",
                "test_row2_remote_close_review_vote_and_task_success_do_not_count (the missing, closure-receipt, tampered-chain and fabricated-closure halves)",
                "test_row2_stale_revision_and_corrupted_revision_content_are_not_resolved",
                "test_row3_reopen_regresses_and_changed_definition_is_not_comparable",
                "test_row4_* (the module half: admit_dispatch for pending, reopened, resolved, unverified, a binding mismatch, an unknown criterion)",
                "test_row5_invalid_duplicate_or_empty_manifests_are_rejected",
                "test_row5_unknown_compare_shapes_and_store_failures"],
    "unreachable": {"test_row2_remote_close_review_vote_and_task_success_do_not_count (the GitHub sync, review vote and task halves)": "GitHub fixture, Workflow",
                    "test_row4_goal_bound_dispatch_is_atomic_idempotent_and_distinct": "Tickets.dispatch (application/tickets.py)",
                    "test_row4_resolved_and_unverified_criteria_refuse_dispatch_before_writes (the dispatch half)": "Tickets.dispatch",
                    "test_row6_cli_report_compare_and_dispatch_options": "the CLI (S10)"}}

TICKET = "ZEUS-000000000001"
OTHER = "ZEUS-000000000002"
CONTENT = {"title": "Independent services", "problem": "Services share one failure domain.", "acceptance_criteria": ["queue runs alone"]}
PACKET = "sha256:" + "1" * 64
PROOF = "sha256:" + "2" * 64


def sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=repr).encode()).hexdigest()[:16]


class World:
    def __init__(self, api):
        api.clock.reset()
        self.api, self.store = api, api.MemoryStore()

    def put(self, bucket, key, row):
        with self.store.transaction() as tx:
            tx.put(bucket, key, row)

    def get(self, bucket, key):
        with self.store.transaction() as tx:
            return tx.get(bucket, key)

    def ticket(self, ticket_id=TICKET, content=None):
        content = deepcopy(content or CONTENT)
        row = {"id": ticket_id, "revision": 1, "content_hash": self.api.digest(content), "status": "open", "created_at": "2026-09-22T00:00:00+00:00"}
        self.put("tickets", ticket_id, row)
        self.put("ticket_revisions", ticket_id + ":1", {**row, "content": content, "claimed_author": "operator", "reason": "created"})
        return row

    def revise(self, ticket_id=TICKET, title="Revised"):
        content = {**CONTENT, "title": title}
        row = self.get("tickets", ticket_id)
        row = {**row, "revision": row["revision"] + 1, "content_hash": self.api.digest(content), "status": "open"}
        self.put("tickets", ticket_id, row)
        self.put("ticket_revisions", ticket_id + ":" + str(row["revision"]), {**row, "content": content, "claimed_author": "operator", "reason": "Revise"})
        return row

    def event(self, kind, ticket_id=TICKET, closure=True):
        self.api.clock.advance(1)
        with self.store.transaction() as tx:
            ticket = tx.get("tickets", ticket_id)
            args = {"packet_ref": PACKET, "proof_ref": PROOF} if kind == "closed" else {}
            event = self.api.transition(tx, ticket, kind, "r-" + kind, **args)
            if kind == "closed" and closure:
                tx.put("ticket_closures", PACKET, {"packet_ref": PACKET, "event_id": event["id"]})
        return event

    def snap(self):
        with self.store.transaction() as tx:
            return sha(tx.records())

    def observe(self, call):
        before = self.snap()
        try:
            out = {"outcome": "returned", "value": call()}
        except BaseException as exc:  # noqa: BLE001 - what propagates is part of the observation
            out = {"outcome": "raised", "type": type(exc).__name__, "message": str(exc), "is_contract_error": isinstance(exc, self.api.ContractError)}
        after = self.snap()
        out.update(store_before=before, store_after=after, store_unchanged=before == after)
        return out


def criterion(row, cid="c1", **over):
    return {"id": cid, "acceptance": "Ticket closed with local evidence", "ticket_id": row["id"], "revision": row["revision"],
            "content_hash": row["content_hash"], **over}


def manifest(row, goal="goal-1", cid="c1", **over):
    return {"version": 1, "id": goal, "objective": "Resolve the fixture residual", "non_goals": ["Deploy"], "criteria": [criterion(row, cid, **over)]}


def a_surface(api):
    cases = {"constants": {"SCHEMA": api.SCHEMA, "MANIFEST_FIELDS": sorted(api.MANIFEST_FIELDS), "CRITERION_FIELDS": sorted(api.CRITERION_FIELDS),
                           "REPORT_FIELDS": sorted(api.REPORT_FIELDS), "STATUSES": sorted(api.STATUSES), "COUNTED": list(api.COUNTED)}}
    cases["signatures"] = {n: str(inspect.signature(getattr(api, n))) for n in
                           ("validate_manifest", "definition_hash", "evaluate_criterion", "admit_dispatch", "compare_reports")}
    cases["GoalProgress"] = {"__init__": str(inspect.signature(api.GoalProgress.__init__)), "report": str(inspect.signature(api.GoalProgress.report))}
    store = api.MemoryStore()
    cases["constructor_keeps_the_store"] = api.GoalProgress(store).store is store
    return {"surface": cases}


def b_manifest(api):
    cases, w = {}, World(api)
    row = w.ticket()
    good = manifest(row)
    cases["valid"] = w.observe(lambda: api.validate_manifest(good))
    copy = api.validate_manifest(good)
    cases["valid_is_a_deep_copy"] = [copy == good, copy is not good, copy["criteria"][0] is not good["criteria"][0]]
    cases["definition_hash"] = w.observe(lambda: api.definition_hash(good))
    cases["definition_hash_of_a_changed_denominator_differs"] = api.definition_hash(good) != api.definition_hash(manifest(row, revision=2))
    cases["definition_hash_of_invalid"] = w.observe(lambda: api.definition_hash({}))
    mutations = {
        "not_a_dict": lambda m: [m], "missing_non_goals": lambda m: {k: v for k, v in m.items() if k != "non_goals"},
        "extra_field": lambda m: {**m, "extra": 1}, "version_string": lambda m: {**m, "version": "1"}, "version_bool": lambda m: {**m, "version": True},
        "version_2": lambda m: {**m, "version": 2}, "id_blank": lambda m: {**m, "id": " "}, "id_long": lambda m: {**m, "id": "g" * 201},
        "objective_empty": lambda m: {**m, "objective": ""}, "objective_not_text": lambda m: {**m, "objective": 1},
        "non_goals_string": lambda m: {**m, "non_goals": "none"}, "non_goals_number": lambda m: {**m, "non_goals": [1]},
        "non_goals_long": lambda m: {**m, "non_goals": ["n" * 4001]}, "non_goals_empty_ok": lambda m: {**m, "non_goals": []},
        "criteria_empty": lambda m: {**m, "criteria": []}, "criteria_string": lambda m: {**m, "criteria": "c1"},
        "criteria_51": lambda m: {**m, "criteria": [{**m["criteria"][0], "id": "c" + str(i), "ticket_id": "T" + str(i)} for i in range(51)]},
        "criteria_50_ok": lambda m: {**m, "criteria": [{**m["criteria"][0], "id": "c" + str(i), "ticket_id": "T" + str(i)} for i in range(50)]},
        "criterion_not_a_dict": lambda m: {**m, "criteria": ["c1"]},
        "criterion_missing_acceptance": lambda m: {**m, "criteria": [{k: v for k, v in m["criteria"][0].items() if k != "acceptance"}]},
        "criterion_extra": lambda m: {**m, "criteria": [{**m["criteria"][0], "note": "x"}]},
        "criterion_acceptance_blank": lambda m: {**m, "criteria": [{**m["criteria"][0], "acceptance": " "}]},
        "criterion_ticket_blank": lambda m: {**m, "criteria": [{**m["criteria"][0], "ticket_id": ""}]},
        "criterion_revision_0": lambda m: {**m, "criteria": [{**m["criteria"][0], "revision": 0}]},
        "criterion_revision_bool": lambda m: {**m, "criteria": [{**m["criteria"][0], "revision": True}]},
        "criterion_revision_string": lambda m: {**m, "criteria": [{**m["criteria"][0], "revision": "1"}]},
        "criterion_hash_upper": lambda m: {**m, "criteria": [{**m["criteria"][0], "content_hash": "A" * 64}]},
        "criterion_hash_short": lambda m: {**m, "criteria": [{**m["criteria"][0], "content_hash": "0" * 63}]},
        "criterion_hash_not_text": lambda m: {**m, "criteria": [{**m["criteria"][0], "content_hash": 1}]},
        "duplicate_ticket": lambda m: {**m, "criteria": [m["criteria"][0], {**m["criteria"][0], "id": "c2"}]},
        "duplicate_id": lambda m: {**m, "criteria": [m["criteria"][0], {**m["criteria"][0], "ticket_id": OTHER}]},
        "two_distinct_ok": lambda m: {**m, "criteria": [m["criteria"][0], {**m["criteria"][0], "id": "c2", "ticket_id": OTHER}]},
    }
    for name, mutate in mutations.items():
        cases["validate_" + name] = w.observe(lambda f=mutate: api.validate_manifest(f(deepcopy(good))))
    cases["report_refuses_an_invalid_manifest_before_the_store"] = w.observe(lambda: api.GoalProgress(w.store).report({"version": 1}))
    return {"manifest": cases}


def c_evaluate(api):
    cases = {}

    def evaluate(w, crit):
        return w.observe(lambda: w.api.GoalProgress(w.store).report({"version": 1, "id": "g", "objective": "o", "non_goals": [], "criteria": [crit]})
                         ["criteria"][0])

    def direct(w, crit):
        def run():
            with w.store.transaction() as tx:
                return api.evaluate_criterion(tx, crit)
        return w.observe(run)

    w = World(api)
    row = w.ticket()
    cases["open_pending"] = direct(w, criterion(row))
    cases["absent_ticket_missing"] = direct(w, criterion({**row, "id": "ZEUS-absent00000"}))
    cases["absent_revision_missing"] = direct(w, criterion({**row, "revision": 2}))
    cases["wrong_hash_stale"] = direct(w, criterion({**row, "content_hash": "f" * 64}))
    # M7 test_row1: close resolves (planted closure receipt), repeated observation unchanged
    event = w.event("closed")
    cases["closed_resolved_with_closure"] = direct(w, criterion(row))
    cases["closed_resolved_repeated"] = direct(w, criterion(row))
    cases["closed_resolved_through_report"] = evaluate(w, criterion(row))
    # M7 test_row3: a reopen regresses
    w.event("reopened")
    cases["reopened"] = direct(w, criterion(row))
    w.event("closed")
    cases["closed_again_resolved"] = direct(w, criterion(row))
    cases["event_chain_length"] = len(iter_events(w))

    # M7 test_row2: injected faults on a closed ticket
    w = World(api)
    row = w.ticket()
    event = w.event("closed")
    current = w.get("tickets", TICKET)
    w.put("ticket_closures", PACKET, {"packet_ref": PACKET, "event_id": "0" * 64})
    cases["closure_names_another_event_unverified"] = direct(w, criterion(row))
    w.put("ticket_closures", PACKET, {"packet_ref": PACKET})
    cases["closure_without_event_id_unverified"] = direct(w, criterion(row))
    w.put("ticket_closures", PACKET, {"packet_ref": PACKET, "event_id": event["id"]})
    cases["restored_closure_resolved"] = direct(w, criterion(row))
    w.put("ticket_lifecycle_events", event["id"], {**event, "reason": "Tampered"})
    cases["tampered_event_unverified"] = direct(w, criterion(row))
    w.put("ticket_lifecycle_events", event["id"], event)
    w.put("tickets", TICKET, {**current, "lifecycle_sequence": 0, "lifecycle_event": None})
    cases["closed_status_without_decision_unverified"] = direct(w, criterion(row))
    w.put("tickets", TICKET, {**current, "lifecycle_sequence": 5})
    cases["closed_sequence_mismatch_unverified"] = direct(w, criterion(row))
    w.put("tickets", TICKET, {**current, "lifecycle_event": "f" * 64})
    cases["closed_fabricated_event_reference_unverified"] = direct(w, criterion(row))
    w.put("tickets", TICKET, current)
    cases["restored_resolved"] = direct(w, criterion(row))
    for name, edit in (("not_closed_kind", {"kind": "reopened"}), ("other_revision", {"revision": 9}), ("other_hash", {"content_hash": "e" * 64}),
                       ("packet_ref_not_sha", {"packet_ref": "x"}), ("proof_ref_missing", {"proof_ref": None}), ("proof_ref_bad_hex", {"proof_ref": "sha256:" + "G" * 64})):
        v = World(api)
        v.ticket()
        ev = v.event("closed")
        forged = {k: val for k, val in {**ev, **edit}.items() if k != "id"}
        forged["id"] = api.digest(forged)
        v.put("ticket_lifecycle_events", forged["id"], forged)
        # the chain is rebuilt from the forged head: previous_event/sequence kept, so only the closure rule can refuse it
        v.put("tickets", TICKET, {**v.get("tickets", TICKET), "lifecycle_event": forged["id"]})
        v.put("ticket_closures", forged.get("packet_ref") if isinstance(forged.get("packet_ref"), str) else PACKET,
              {"packet_ref": PACKET, "event_id": forged["id"]})
        cases["forged_closed_event_" + name] = direct(v, criterion(row))

    # M7 test_row2 (stale/corrupt): a revised ticket, a corrupted revision, a fabricated closed status
    w = World(api)
    row = w.ticket()
    new = w.revise()
    cases["revised_old_binding_stale"] = direct(w, criterion(row))
    cases["revised_new_binding_pending"] = direct(w, criterion(new))
    saved = w.get("ticket_revisions", TICKET + ":2")
    w.put("ticket_revisions", TICKET + ":2", {**saved, "content": {**saved["content"], "title": "x"}})
    cases["corrupted_revision_content_unverified"] = direct(w, criterion(new))
    w.put("ticket_revisions", TICKET + ":2", {**saved, "content_hash": "d" * 64})
    cases["revision_hash_differs_unverified"] = direct(w, criterion(new))
    w.put("ticket_revisions", TICKET + ":2", saved)
    w.put("tickets", TICKET, {**w.get("tickets", TICKET), "status": "closed", "lifecycle_sequence": 1, "lifecycle_event": "f" * 64})
    cases["fabricated_closed_unverified"] = direct(w, criterion(new))
    w.put("tickets", TICKET, {**new, "status": "dispatched"})
    cases["dispatched_pending"] = direct(w, criterion(new))
    w.put("tickets", TICKET, {**new, "status": "superseded"})
    cases["unknown_status_unverified"] = direct(w, criterion(new))
    w.put("tickets", TICKET, {**new, "status": "dispatched", "lifecycle_sequence": 3})
    cases["broken_chain_unverified"] = direct(w, criterion(new))
    return {"evaluate": cases}


def iter_events(w):
    with w.store.transaction() as tx:
        return list(tx.scan("ticket_lifecycle_events"))


def d_admit(api):
    cases = {}
    w = World(api)
    row = w.ticket()
    other = w.ticket(OTHER, {**CONTENT, "title": "Other"})
    m = manifest(row)
    m["criteria"].append(criterion(other, "c2"))
    bound = {"id": TICKET, "revision": 1, "content_hash": row["content_hash"]}

    def admit(manifest_, cid, bound_):
        def run():
            with w.store.transaction() as tx:
                return api.admit_dispatch(tx, manifest_, cid, bound_)
        return w.observe(run)

    cases["pending_admitted"] = admit(m, "c1", bound)
    cases["unknown_criterion"] = admit(m, "c9", bound)
    cases["blank_criterion_id"] = admit(m, " ", bound)
    cases["criterion_id_not_text"] = admit(m, 1, bound)
    cases["other_ticket_binding"] = admit(m, "c1", {**bound, "id": OTHER})
    cases["other_revision_binding"] = admit(m, "c1", {**bound, "revision": 2})
    cases["other_hash_binding"] = admit(m, "c1", {**bound, "content_hash": "a" * 64})
    cases["binding_without_id"] = admit(m, "c1", {"revision": 1, "content_hash": row["content_hash"]})
    cases["second_criterion_admitted"] = admit(m, "c2", {"id": OTHER, "revision": 1, "content_hash": other["content_hash"]})
    w.event("closed")
    cases["resolved_refused"] = admit(m, "c1", bound)
    w.event("reopened")
    cases["reopened_admitted"] = admit(m, "c1", bound)
    w.put("ticket_lifecycle_events", w.get("tickets", TICKET)["lifecycle_event"], {"id": "x"})
    cases["unverified_refused"] = admit(m, "c1", bound)
    stale = manifest({**row, "content_hash": "b" * 64})
    cases["stale_refused"] = admit(stale, "c1", {**bound, "content_hash": "b" * 64})
    cases["missing_refused"] = admit(manifest({**row, "id": "ZEUS-absent00000"}), "c1", {**bound, "id": "ZEUS-absent00000"})
    return {"admit": cases}


def e_report(api):
    cases = {}
    w = World(api)
    row = w.ticket()
    other = w.ticket(OTHER, {**CONTENT, "title": "Other"})
    m = manifest(row)
    report = lambda manifest_: w.observe(lambda: api.GoalProgress(w.store).report(manifest_))  # noqa: E731
    cases["pending"] = report(m)
    cases["repeat_equal"] = report(m)["value"] == cases["pending"]["value"]
    cases["pending_hash_is_the_definition_hash"] = cases["pending"]["value"]["definition_hash"] == api.definition_hash(m)
    cases["manifest_not_mutated"] = m == manifest(row)
    w.event("closed")
    cases["resolved"] = report(m)
    mixed = {**m, "criteria": [m["criteria"][0], criterion(other, "c2"), criterion({**row, "id": "ZEUS-absent00000"}, "c3"),
                               criterion({**other, "id": "ZEUS-absent00001"}, "c4")]}
    mixed["criteria"][3] = {**mixed["criteria"][3], "revision": 1}
    cases["mixed_counts"] = report(mixed)
    cases["report_total_one_ratio"] = cases["resolved"]["value"]["metrics"]
    w.event("reopened")
    cases["reopened"] = report(m)
    cases["broken_store"] = None

    class Broken:
        def transaction(self):
            raise RuntimeError("store unavailable")
    try:
        api.GoalProgress(Broken()).report(m)
        cases["broken_store"] = {"outcome": "returned"}
    except BaseException as exc:  # noqa: BLE001
        cases["broken_store"] = {"outcome": "raised", "type": type(exc).__name__, "message": str(exc)}
    return {"report": cases}


def f_compare(api):
    cases = {}
    w = World(api)
    row = w.ticket()
    m = manifest(row)
    rep = lambda: api.GoalProgress(w.store).report(m)  # noqa: E731
    pending = rep()
    w.event("closed")
    resolved = rep()
    w.event("reopened")
    reopened = rep()

    def compare(a, b):
        return w.observe(lambda: api.compare_reports(a, b))

    cases["resolved_to_reopened"] = compare(resolved, reopened)
    cases["reopened_to_resolved"] = compare(reopened, resolved)
    cases["pending_to_resolved"] = compare(pending, resolved)
    cases["same_report"] = compare(resolved, resolved)
    cases["definition_changed"] = compare(resolved, {**reopened, "definition_hash": api.definition_hash(manifest(row, revision=2))})
    cases["goal_changed"] = compare(resolved, {**reopened, "goal_id": "goal-2"})
    cases["bindings_differ"] = compare(resolved, {**reopened, "criteria": [{**reopened["criteria"][0], "revision": 2}]})
    cases["metrics_are_ignored"] = compare(resolved, {**reopened, "metrics": {**reopened["metrics"], "resolved": 1}})
    two = {**resolved, "criteria": [resolved["criteria"][0], {**resolved["criteria"][0], "id": "c2", "status": "pending"}]}
    cases["identities_differ_by_a_criterion"] = compare(resolved, two)
    shapes = {"none": None, "empty": {}, "list": [], "schema": {**resolved, "schema": "urn:zeus:cycle-handoff:1"}, "authority": {**resolved, "authority": "approved"},
              "extra_field": {**resolved, "extra": 1}, "criteria_empty": {**resolved, "criteria": []}, "criteria_51": {**resolved, "criteria": resolved["criteria"] * 51},
              "status_unknown": {**resolved, "criteria": [{**resolved["criteria"][0], "status": "done"}]},
              "duplicate_id": {**resolved, "criteria": resolved["criteria"] * 2}, "raw_field": {**resolved, "criteria": [{**resolved["criteria"][0], "raw": {}}]},
              "missing_field": {**resolved, "criteria": [{k: v for k, v in resolved["criteria"][0].items() if k != "acceptance"}]},
              "criterion_not_dict": {**resolved, "criteria": ["c1"]}, "hash_not_hex": {**resolved, "definition_hash": "x"},
              "goal_blank": {**resolved, "goal_id": " "}, "criteria_not_list": {**resolved, "criteria": "c1"}}
    for name, shape in shapes.items():
        cases["bad_after_" + name] = compare(resolved, shape)
        cases["bad_before_" + name] = compare(shape, resolved)
    return {"compare": cases}


def run(api) -> dict:
    groups = {}
    for step in (a_surface, b_manifest, c_evaluate, d_admit, e_report, f_compare):
        groups.update(step(api))
    return {**groups, "m7_tests": M7_TESTS, "cases_per_group": {k: len(v) for k, v in groups.items()}}
