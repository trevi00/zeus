"""Shared S8 scenario steps (`intake.tickets`): the rest of M7 `application/tickets.py` (`validate_content`, `Tickets.create/update/get/list/review/dispatch`,
`render_ticket`, with `ticket_binding`, `TicketClosed` and `TicketSuperseded` through the closed and stale dispatches), characterized BEFORE the module's
remaining names move into INTAKE (S8 batch B2, DESIGN-s8 §25 V30). The golden is placement-neutral: it observes SOURCE behaviour only.

Each case is labelled with the M7 test it mirrors, or `none`. M7's `tests/test_tickets.py` (4 tests; each parametrized memory/postgres) and the `Tickets`
cases of `tests/test_goal_progress.py` and `tests/test_ticket_execution.py` drive `Tickets` through `Workflow`, `Releases`, the GitHub fixture, the Harness
service and PostgreSQL; the golden is MODULE-level, over a MemoryStore, with the real organization graph. Left out, by name, in `m7_tests`: the
Workflow/Releases halves, PostgreSQL, the GitHub fixture and the CLI.

Layer: harness (never shipped)

This module never imports `codex_harness`: everything arrives through `api`. The whole-store digest (16 hex) is recorded before and after every call with an
`unchanged` flag, so every refusal is shown to leave the store as it was. The clock and the id source are the harness's: ids are `ZEUS-` + 12 hex of the
scripted uuid and the message id of the one envelope a dispatch draws. A raised exception discards the draft, as the PostgreSQL transaction rolls back.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import uuid
from copy import deepcopy

M7_TESTS = {
    "covered": ["test_ticket_revisions_are_immutable_and_reviews_bound_to_current_content (create, review replay, update, stale review/update, get by revision)",
                "test_dispatch_is_durable_idempotent_and_stale_ticket_blocks_old_task (the dispatch, its replay, the outbox row, the stale dispatch)",
                "test_nested_binding_and_export_do_not_change_authority (render_ticket; ticket_binding through the dispatch)",
                "test_goal_progress.py row4 (the Tickets.dispatch half: goal-bound dispatch, its refusals before any write)"],
    "unreachable": {"test_ticket_revisions_are_immutable_and_reviews_bound_to_current_content[postgres]": "PostgreSQL",
                    "test_dispatch_is_durable_idempotent_and_stale_ticket_blocks_old_task (the Workflow.submit/claim half)": "Workflow (S5)",
                    "test_topic_change_during_execution_cannot_complete_or_promote": "Workflow and Releases",
                    "test_ticket_execution.py": "the Harness service, Workflow, canary and promotion",
                    "test_dispatch_and_outbox_roll_back_together": "the PostgreSQL store (the rollback of a raised dispatch is shown on the MemoryStore by the unchanged store digest)",
                    "test_github_tickets.py (the Tickets half)": "the GitHub fixture; batch B2's intake.github_tickets family covers GitHubTickets"}}

TICKET_FIELDS = ("title", "problem", "impact", "rollback", "evidence_refs", "scope", "acceptance_criteria", "verification")


class SpreadIds:
    """The scripted id source: the counter sits in the high bits, so `uuid4().hex[:12]` (a ticket id's suffix) differs from draw to draw (the harness's
    `FakeIds` counts in the low bits, which M7's twelve-character suffix never reaches). The same on both sides."""

    def __init__(self, start=1):
        self.start = self.counter = start

    def reset(self):
        self.counter = self.start

    def uuid4(self):
        value = uuid.UUID(int=(0x5EED << 112) | (self.counter << 80), version=4)
        self.counter += 1
        return value


def content(title="검증 환경 격리", **over):
    return {"title": title, "problem": "Production and tests share endpoints", "impact": "Potential contention", "rollback": "Restore verified image",
            "evidence_refs": ["fixture:source-inspection"], "scope": ["deployment"], "acceptance_criteria": ["Independent services"],
            "verification": ["Run isolated service integration test"], **over}


def sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=repr).encode()).hexdigest()[:16]


def shape(value):
    if isinstance(value, dict):
        return {str(k): shape(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [shape(v) for v in value]
    return value


class World:
    def __init__(self, api, *, org=None):
        api.reset()
        self.api, self.store = api, api.MemoryStore()
        self.org = org if org is not None else api.organization()
        self.tickets = api.new_tickets(self.store, self.org)

    def put(self, bucket, key, row):
        with self.store.transaction() as tx:
            tx.put(bucket, key, row)

    def get(self, bucket, key):
        with self.store.transaction() as tx:
            return tx.get(bucket, key)

    def scan(self, bucket):
        with self.store.transaction() as tx:
            return tx.scan(bucket)

    def snap(self):
        with self.store.transaction() as tx:
            return sha(tx.records())

    def counts(self):
        with self.store.transaction() as tx:
            records = tx.records()
        return {b: sum(r["bucket"] == b for r in records) for b in sorted({r["bucket"] for r in records})}

    def observe(self, call):
        before = self.snap()
        try:
            out = {"outcome": "returned", "value": shape(call())}
        except BaseException as exc:  # noqa: BLE001 - what propagates is part of the observation
            out = {"outcome": "raised", "type": type(exc).__name__, "message": str(exc), "is_contract_error": isinstance(exc, self.api.ContractError)}
        after = self.snap()
        out.update(store_before=before, store_after=after, store_unchanged=before == after)
        return out

    def create(self, title="검증 환경 격리"):
        self.api.clock.advance(1)
        return self.tickets.create(content(title))

    def goal(self, row, goal="goal-1", cid="c1", **over):
        criterion = {"id": cid, "acceptance": "Ticket closed with local evidence", "ticket_id": row["id"], "revision": row["revision"],
                     "content_hash": row["content_hash"], **over}
        return {"version": 1, "id": goal, "objective": "Resolve the fixture residual", "non_goals": ["Deploy"], "criteria": [criterion]}


def binding(w, value):
    with w.store.transaction() as tx:
        return w.api.ticket_binding(tx, value)


def a_surface(api):
    positional = lambda fn: [n for n, p in inspect.signature(fn).parameters.items() if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)]  # noqa: E731
    cases = {"constants": {"TEXT_FIELDS": list(api.TEXT_FIELDS), "LIST_FIELDS": list(api.LIST_FIELDS)},
             "signatures": {n: str(inspect.signature(getattr(api, n))) for n in ("validate_content", "render_ticket", "ticket_binding")},
             "Tickets_positional": {n: positional(getattr(api.Tickets, n)) for n in ("__init__", "create", "update", "get", "list", "review", "dispatch")},
             "Tickets_defaults": {n: {k: repr(p.default) for k, p in inspect.signature(getattr(api.Tickets, n)).parameters.items() if p.default is not p.empty}
                                  for n in ("create", "update", "get", "review", "dispatch")}}
    w = World(api)
    cases["constructor"] = {"store_is_kept": w.tickets.store is w.store, "organization_is_kept": w.tickets.org is w.org}
    cases["error_classes"] = {"TicketSuperseded_is_ContractError": issubclass(api.TicketSuperseded, api.ContractError),
                              "TicketClosed_is_TicketSuperseded": issubclass(api.TicketClosed, api.TicketSuperseded)}
    return {"surface": cases}


def b_validate_content(api):
    cases, w = {}, World(api)
    good = content()
    cases["valid"] = w.observe(lambda: api.validate_content(good))
    copy = api.validate_content(good)
    cases["valid_is_a_deep_copy"] = [copy == good, copy is not good, copy["scope"] is not good["scope"]]
    cases["unicode_title_kept"] = copy["title"] == "검증 환경 격리"
    drop = lambda name: {k: v for k, v in good.items() if k != name}  # noqa: E731
    mutations = {"not_a_dict": [good], "none": None, "empty": {}, "extra_field": {**good, "extra": "x"}}
    mutations.update({"missing_" + name: drop(name) for name in TICKET_FIELDS})
    for name in api.TEXT_FIELDS:
        mutations.update({name + "_blank": {**good, name: "  "}, name + "_not_text": {**good, name: 1}, name + "_12000": {**good, name: "x" * 12000},
                          name + "_12001": {**good, name: "x" * 12001}})
    for name in api.LIST_FIELDS:
        mutations.update({name + "_empty": {**good, name: []}, name + "_string": {**good, name: "one"}, name + "_item_number": {**good, name: [1]},
                          name + "_item_blank": {**good, name: [" "]}, name + "_item_4000": {**good, name: ["x" * 4000]},
                          name + "_item_4001": {**good, name: ["x" * 4001]}, name + "_50": {**good, name: ["x"] * 50},
                          name + "_51": {**good, name: ["x"] * 51}, name + "_tuple": {**good, name: ("x",)}})
    for name, value in mutations.items():
        cases["mutation_" + name] = w.observe(lambda value=value: api.validate_content(value))
    return {"validate_content": cases}


def c_create(api):
    cases, w = {}, World(api)
    first = w.observe(lambda: w.create())
    cases["create"] = first
    cases["create_rows"] = {"tickets": w.scan("tickets"), "ticket_revisions": w.scan("ticket_revisions"), "counts": w.counts()}
    row = first["value"]
    cases["create_row_keys"] = sorted(row)
    cases["create_hash_is_the_content_digest"] = row["content_hash"] == api.digest(content())
    cases["create_with_author"] = w.observe(lambda: w.tickets.create(content("Second"), "reviewer-1"))
    cases["create_second_id_differs"] = cases["create_with_author"]["value"]["id"] != row["id"]
    cases["create_author_recorded"] = w.get("ticket_revisions", cases["create_with_author"]["value"]["id"] + ":1")["claimed_author"]
    for name, author in {"blank": " ", "empty": "", "none": None, "number": 1}.items():
        cases["author_" + name] = w.observe(lambda author=author: w.tickets.create(content("Third"), author))
    cases["invalid_content"] = w.observe(lambda: w.tickets.create({"title": "only"}))
    cases["invalid_content_before_author"] = w.observe(lambda: w.tickets.create({"title": "only"}, " "))
    cases["identical_content_is_a_second_ticket"] = w.observe(lambda: w.tickets.create(content()))
    cases["rows_after"] = w.counts()
    return {"create": cases}


def d_update(api):
    cases, w = {}, World(api)
    row = w.create()
    other = w.create("Another topic")
    w.tickets.dispatch(row["id"], 1, "base")
    w.tickets.review(row["id"], 1, "Claude", "claude", "question", "How is rollback tested?", ["fixture:review"])
    cases["unchanged_content"] = w.observe(lambda: w.tickets.update(row["id"], 1, content(), "Same"))
    cases["stale_revision"] = w.observe(lambda: w.tickets.update(row["id"], 2, content("Other"), "Stale"))
    cases["unknown_ticket"] = w.observe(lambda: w.tickets.update("ZEUS-unknown", 1, content("Other"), "None"))
    for name, reason in {"blank": " ", "empty": "", "none": None, "number": 1}.items():
        cases["reason_" + name] = w.observe(lambda reason=reason: w.tickets.update(row["id"], 1, content("Other"), reason))
    for name, author in {"blank": " ", "none": None}.items():
        cases["author_" + name] = w.observe(lambda author=author: w.tickets.update(row["id"], 1, content("Other"), "Edit", author))
    cases["invalid_content"] = w.observe(lambda: w.tickets.update(row["id"], 1, {"title": "x"}, "Edit"))
    cases["dispatches_before"] = w.scan("ticket_dispatches")
    w.api.clock.advance(5)
    cases["update"] = w.observe(lambda: w.tickets.update(row["id"], 1, content("Updated scope"), "Clarify acceptance", "editor"))
    cases["update_rows"] = {"tickets": w.scan("tickets"), "ticket_revisions": w.scan("ticket_revisions"), "dispatches_after": w.scan("ticket_dispatches")}
    cases["old_revision_kept"] = w.get("ticket_revisions", row["id"] + ":1")["content"] == content()
    cases["second_update"] = w.observe(lambda: w.tickets.update(row["id"], 2, content("Third scope"), "Again"))
    cases["other_ticket_dispatch_untouched"] = [w.get("tickets", other["id"])["status"]]
    # a closed ticket must be reopened before an edit
    w.put("tickets", other["id"], {**w.get("tickets", other["id"]), "status": "closed"})
    cases["closed_ticket"] = w.observe(lambda: w.tickets.update(other["id"], 1, content("Reopen first"), "Edit"))
    # an unresolved promotion of this ticket blocks the edit; resolved ones and other tickets' do not
    third = w.create("Promoted topic")
    for name, status, ticket_id in (("completed", "completed", third["id"]), ("abandoned", "abandoned", third["id"]), ("other", "pending", other["id"])):
        w.put("promotion_intents", "intent-" + name, {"status": status, "candidate": {"zeus_ticket": {"id": ticket_id}}})
    w.put("promotion_intents", "intent-nocandidate", {"status": "pending"})
    w.put("promotion_intents", "intent-nobinding", {"status": "pending", "candidate": {}})
    cases["promotion_resolved_and_foreign_pass"] = w.observe(lambda: w.tickets.update(third["id"], 1, content("Promoted 2"), "Edit"))
    for status in ("pending", "running", "failed"):
        w.put("promotion_intents", "intent-block", {"status": status, "candidate": {"zeus_ticket": {"id": third["id"]}}})
        cases["promotion_" + status] = w.observe(lambda: w.tickets.update(third["id"], 2, content("Promoted " + status), "Edit"))
    return {"update": cases}


def e_get_list(api):
    cases, w = {}, World(api)
    first = w.create("First")
    w.api.clock.advance(5)
    second = w.create("Second")
    cases["get_missing"] = w.observe(lambda: w.tickets.get("ZEUS-unknown"))
    cases["get_current"] = w.observe(lambda: w.tickets.get(first["id"]))
    cases["get_unknown_revision"] = w.observe(lambda: w.tickets.get(first["id"], 7))
    review = w.tickets.review(first["id"], 1, "Claude", "claude", "support", "Looks fine", ["fixture:a"])
    w.api.clock.advance(1)
    w.tickets.review(first["id"], 1, "Codex", "codex", "question", "Why?", ["fixture:b"])
    w.put("ticket_github", "link-1", {"id": "link-1", "ticket_id": first["id"], "number": 3, "status": "synced"})
    w.put("ticket_github", "link-0", {"id": "link-0", "ticket_id": first["id"], "number": 2, "status": "synced"})
    w.put("ticket_github", "link-x", {"id": "link-x", "ticket_id": second["id"], "number": 9, "status": "synced"})
    for sequence, at in ((2, "2026-09-22T00:00:09+00:00"), (1, "2026-09-22T00:00:09+00:00"), (0, "2026-09-22T00:00:01+00:00")):
        w.put("ticket_remote_observations", "obs-%d" % sequence, {"id": "obs-%d" % sequence, "ticket_id": first["id"], "sequence": sequence, "at": at})
    w.put("ticket_remote_observations", "obs-nosequence", {"id": "obs-nosequence", "ticket_id": first["id"], "at": "2026-09-22T00:00:00+00:00"})
    w.put("ticket_lifecycle_events", "event-2", {"id": "event-2", "ticket_id": first["id"], "sequence": 2})
    w.put("ticket_lifecycle_events", "event-1", {"id": "event-1", "ticket_id": first["id"], "sequence": 1})
    cases["get_with_reviews_links_observations_events"] = w.observe(lambda: w.tickets.get(first["id"]))
    cases["review_row_replayed_equal"] = review == w.tickets.review(first["id"], 1, "Claude", "claude", "support", "Looks fine", ["fixture:a"])
    w.api.clock.advance(1)
    w.tickets.update(first["id"], 1, content("First, revised"), "Revise")
    cases["get_revision_one_after_update"] = w.observe(lambda: w.tickets.get(first["id"], 1))
    cases["get_current_after_update_has_no_reviews"] = w.observe(lambda: w.tickets.get(first["id"]))
    cases["revision_zero_is_the_current_one"] = w.observe(lambda: w.tickets.get(first["id"], 0))
    cases["list"] = w.observe(lambda: w.tickets.list())
    cases["list_order_by_created_at"] = [t["id"] for t in w.tickets.list()] == [first["id"], second["id"]]
    # a corrupted revision is refused
    w.put("ticket_revisions", second["id"] + ":1", {**w.get("ticket_revisions", second["id"] + ":1"), "content_hash": "0" * 64})
    cases["get_corrupted_revision"] = w.observe(lambda: w.tickets.get(second["id"]))
    cases["list_with_a_corrupted_revision"] = w.observe(lambda: w.tickets.list())
    w2 = World(api)
    cases["list_empty"] = w2.observe(lambda: w2.tickets.list())
    w2.put("tickets", "ZEUS-norev", {"id": "ZEUS-norev", "revision": 1, "content_hash": "x", "status": "open", "created_at": "2026-09-22T00:00:00+00:00"})
    cases["get_without_a_revision_row"] = w2.observe(lambda: w2.tickets.get("ZEUS-norev"))
    return {"get_list": cases}


def f_review(api):
    cases, w = {}, World(api)
    row = w.create()
    args = (row["id"], 1, "Claude", "claude", "question", "How is rollback tested?", ["fixture:review"])
    cases["review"] = w.observe(lambda: w.tickets.review(*args))
    cases["review_row_is_advisory"] = w.scan("ticket_reviews")
    cases["review_replay_returns_the_existing_row"] = w.observe(lambda: w.tickets.review(*args))
    cases["review_replay_added_no_row"] = len(w.scan("ticket_reviews"))
    cases["same_reviewer_other_verdict"] = w.observe(lambda: w.tickets.review(row["id"], 1, "Claude", "claude", "support", "Fine", ["fixture:review"]))
    for verdict in ("support", "changes_requested", "question", "approve", "", None):
        cases["verdict_" + str(verdict)] = w.observe(lambda verdict=verdict: w.tickets.review(row["id"], 1, "R-" + str(verdict), "p", verdict, "s", ["e"]))
    for name, bad in {"reviewer_blank": ("", "claude", "s"), "provider_blank": ("R", " ", "s"), "summary_blank": ("R", "claude", " "),
                      "reviewer_not_text": (1, "claude", "s"), "summary_12001": ("R", "claude", "x" * 12001), "reviewer_12001": ("x" * 12001, "claude", "s")}.items():
        cases[name] = w.observe(lambda bad=bad: w.tickets.review(row["id"], 1, bad[0], bad[1], "support", bad[2], ["e"]))
    for name, refs in {"empty": [], "string": "e", "none": None, "blank_item": [" "], "number_item": [1]}.items():
        cases["evidence_" + name] = w.observe(lambda refs=refs: w.tickets.review(row["id"], 1, "E-" + name, "claude", "support", "s", refs))
    cases["stale_revision"] = w.observe(lambda: w.tickets.review(row["id"], 2, "Claude", "claude", "support", "s", ["e"]))
    cases["unknown_ticket"] = w.observe(lambda: w.tickets.review("ZEUS-unknown", 1, "Claude", "claude", "support", "s", ["e"]))
    before = len(w.scan("ticket_reviews"))
    for index in range(40):
        try:
            w.tickets.review(row["id"], 1, "Budget-%d" % index, "claude", "support", "s", ["e"])
        except Exception:  # noqa: BLE001
            break
    cases["budget"] = {"rows_before": before, "rows_after": len(w.scan("ticket_reviews")), "reviews_for_revision": sum(r["revision"] == 1 for r in w.scan("ticket_reviews"))}
    cases["budget_exhausted"] = w.observe(lambda: w.tickets.review(row["id"], 1, "One-more", "claude", "support", "s", ["e"]))
    cases["budget_replay_still_returns"] = w.observe(lambda: w.tickets.review(*args))
    w.api.clock.advance(3)
    w.tickets.update(row["id"], 1, content("Next"), "Next")
    cases["new_revision_has_its_own_budget"] = w.observe(lambda: w.tickets.review(row["id"], 2, "Claude", "claude", "support", "s", ["e"]))
    return {"review": cases}


def g_dispatch(api):
    cases, w = {}, World(api)
    row = w.create()
    w.tickets.review(row["id"], 1, "Codex", "codex", "support", "Advisory only", ["fixture:review"])
    manifest = w.goal(row)
    for name, revision in {"blank": "", "none": None}.items():
        cases["repository_" + name] = w.observe(lambda revision=revision: w.tickets.dispatch(row["id"], 1, revision))
    cases["manifest_without_criterion"] = w.observe(lambda: w.tickets.dispatch(row["id"], 1, "base", goal_manifest=manifest))
    cases["criterion_without_manifest"] = w.observe(lambda: w.tickets.dispatch(row["id"], 1, "base", criterion_id="c1"))
    cases["invalid_manifest"] = w.observe(lambda: w.tickets.dispatch(row["id"], 1, "base", goal_manifest={"id": "x"}, criterion_id="c1"))
    cases["stale_revision"] = w.observe(lambda: w.tickets.dispatch(row["id"], 2, "base"))
    cases["unknown_ticket"] = w.observe(lambda: w.tickets.dispatch("ZEUS-unknown", 1, "base"))
    cases["unknown_criterion"] = w.observe(lambda: w.tickets.dispatch(row["id"], 1, "base", goal_manifest=manifest, criterion_id="c2"))
    cases["blank_criterion"] = w.observe(lambda: w.tickets.dispatch(row["id"], 1, "base", goal_manifest=manifest, criterion_id=" "))
    cases["criterion_bound_to_another_revision"] = w.observe(
        lambda: w.tickets.dispatch(row["id"], 1, "base", goal_manifest=w.goal(row, revision=2), criterion_id="c1"))
    cases["criterion_bound_to_another_ticket"] = w.observe(
        lambda: w.tickets.dispatch(row["id"], 1, "base", goal_manifest=w.goal(row, ticket_id="ZEUS-other"), criterion_id="c1"))
    cases["criterion_bound_to_another_hash"] = w.observe(
        lambda: w.tickets.dispatch(row["id"], 1, "base", goal_manifest=w.goal(row, content_hash="0" * 64), criterion_id="c1"))
    cases["rows_before_the_first_dispatch"] = w.counts()
    whole = api.organization()
    org_bad = World(api, org=type(whole)({k: v for k, v in whole.agents.items() if k != "lead:improvement"}))
    bad = org_bad.create()
    cases["organization_refuses_the_assignment"] = org_bad.observe(lambda: org_bad.tickets.dispatch(bad["id"], 1, "base"))
    w.api.clock.advance(2)
    first = w.observe(lambda: w.tickets.dispatch(row["id"], 1, "repository-commit"))
    cases["dispatch"] = first
    cases["dispatch_rows"] = {"outbox": w.scan("outbox"), "ticket_dispatches": w.scan("ticket_dispatches"), "tickets": w.scan("tickets"), "counts": w.counts()}
    cases["dispatch_key_is_the_binding_digest"] = first["value"]["id"] == api.digest({k: row[k] for k in ("id", "revision", "content_hash")})
    w.api.clock.advance(2)
    cases["dispatch_replay_returns_the_stored_result"] = w.observe(lambda: w.tickets.dispatch(row["id"], 1, "other-commit"))
    cases["replay_added_no_outbox_row"] = len(w.scan("outbox"))
    cases["stale_after_dispatch"] = w.observe(lambda: w.tickets.dispatch(row["id"], 2, "repository-commit"))
    # the dispatched ticket's status is `dispatched`; an update supersedes the dispatch and the new revision dispatches again
    w.api.clock.advance(2)
    w.tickets.update(row["id"], 1, content("Changed topic"), "Needs new review")
    cases["dispatch_after_update"] = w.observe(lambda: w.tickets.dispatch(row["id"], 2, "repository-commit"))
    cases["dispatches_after_update"] = w.scan("ticket_dispatches")
    # goal-bound dispatch
    g = World(api)
    ticket = g.create()
    goal = g.goal(ticket)
    cases["goal_dispatch"] = g.observe(lambda: g.tickets.dispatch(ticket["id"], 1, "base", goal_manifest=goal, criterion_id="c1"))
    cases["goal_dispatch_rows"] = {"outbox": g.scan("outbox"), "ticket_dispatches": g.scan("ticket_dispatches")}
    cases["goal_dispatch_replay"] = g.observe(lambda: g.tickets.dispatch(ticket["id"], 1, "other", goal_manifest=goal, criterion_id="c1"))
    cases["goal_dispatch_key_includes_the_goal"] = cases["goal_dispatch"]["value"]["id"] != api.digest({k: ticket[k] for k in ("id", "revision", "content_hash")})
    cases["goal_and_plain_dispatch_are_distinct"] = g.observe(lambda: g.tickets.dispatch(ticket["id"], 1, "base"))
    cases["dispatch_rows_after_both"] = g.counts()
    # observations: only the last ten ride in the message, with the totals
    o = World(api)
    obs = o.create()
    for sequence in range(13):
        o.put("ticket_remote_observations", "obs-%02d" % sequence, {"id": "obs-%02d" % sequence, "ticket_id": obs["id"], "sequence": sequence,
                                                                    "at": "2026-09-22T00:%02d:00+00:00" % sequence})
    o.put("ticket_remote_observations", "obs-other", {"id": "obs-other", "ticket_id": "ZEUS-other", "sequence": 0, "at": "2026-09-22T00:30:00+00:00"})
    result = o.observe(lambda: o.tickets.dispatch(obs["id"], 1, "base"))
    details = o.scan("outbox")[0]["message"]["what"]["details"]
    cases["observations_dispatch"] = result
    cases["observations_bounded"] = {"kept": [r["id"] for r in details["external_ticket_observations"]], "total": details["external_ticket_observations_total"],
                                     "omitted": details["external_ticket_observations_omitted"]}
    # a lifecycle sequence is part of the binding; a closed ticket and a changed lifecycle refuse
    s = World(api)
    seq = s.create()
    s.put("tickets", seq["id"], {**s.get("tickets", seq["id"]), "lifecycle_sequence": 2})
    cases["lifecycle_sequence_dispatch"] = s.observe(lambda: s.tickets.dispatch(seq["id"], 1, "base"))
    cases["lifecycle_sequence_in_the_message"] = s.scan("outbox")[0]["message"]["what"]["details"]["zeus_ticket"]
    c = World(api)
    closed = c.create()
    c.put("tickets", closed["id"], {**c.get("tickets", closed["id"]), "status": "closed"})
    cases["closed_ticket_dispatch"] = c.observe(lambda: c.tickets.dispatch(closed["id"], 1, "base"))
    cases["closed_ticket_error_classes"] = [issubclass(api.TicketClosed, api.TicketSuperseded)]
    t = World(api)
    torn = t.create()
    t.put("ticket_revisions", torn["id"] + ":1", {**t.get("ticket_revisions", torn["id"] + ":1"), "content": content("Tampered")})
    cases["tampered_revision_dispatch"] = t.observe(lambda: t.tickets.dispatch(torn["id"], 1, "base"))
    return {"dispatch": cases}


def h_binding(api):
    """`ticket_binding`, `TicketClosed` and `TicketSuperseded` (the S4 names, moved ahead unchanged) through a ticket `Tickets` created."""
    cases, w = {}, World(api)
    row = w.create()
    bound = {k: row[k] for k in ("id", "revision", "content_hash")}
    call = lambda value: w.observe(lambda: binding(w, value))  # noqa: E731
    cases["no_binding"] = call({"plan": {}})
    cases["bound"] = call({"zeus_ticket": bound})
    cases["nested_and_repeated"] = call({"origin": {"zeus_ticket": bound}, "items": [{"zeus_ticket": bound}]})
    cases["conflicting"] = call({"zeus_ticket": bound, "other": {"zeus_ticket": {**bound, "revision": 2}}})
    cases["invalid_shape"] = call({"zeus_ticket": {"id": row["id"]}})
    cases["not_a_dict_binding"] = call({"zeus_ticket": "x"})
    cases["missing_ticket"] = call({"zeus_ticket": {**bound, "id": "ZEUS-unknown"}})
    cases["lifecycle_sequence_bool"] = call({"zeus_ticket": {**bound, "lifecycle_sequence": True}})
    cases["lifecycle_sequence_mismatch"] = call({"zeus_ticket": {**bound, "lifecycle_sequence": 1}})
    cases["revision_mismatch"] = call({"zeus_ticket": {**bound, "revision": 2}})
    cases["hash_mismatch"] = call({"zeus_ticket": {**bound, "content_hash": "0" * 64}})
    w.api.clock.advance(1)
    w.tickets.update(row["id"], 1, content("Revised"), "Revise")
    cases["superseded_after_update"] = call({"zeus_ticket": bound})
    cases["superseded_error_type"] = [cases["superseded_after_update"]["type"], issubclass(api.TicketSuperseded, api.ContractError)]
    w.put("tickets", row["id"], {**w.get("tickets", row["id"]), "status": "closed"})
    cases["closed"] = call({"zeus_ticket": bound})
    return {"binding": cases}


def i_render(api):
    cases, w = {}, World(api)
    row = w.create()
    plain = w.tickets.get(row["id"])
    cases["no_reviews"] = api.render_ticket(plain)
    cases["no_review_marker"] = "No review recorded for this revision." in cases["no_reviews"]
    w.api.clock.advance(1)
    w.tickets.review(row["id"], 1, "Claude", "claude", "question", "How is rollback tested?", ["fixture:review", "fixture:two"])
    w.api.clock.advance(1)
    w.tickets.review(row["id"], 1, "Codex", "codex", "support", "Advisory only", ["fixture:three"])
    reviewed = w.tickets.get(row["id"])
    cases["reviewed"] = api.render_ticket(reviewed)
    cases["pure"] = [api.render_ticket(reviewed) == api.render_ticket(deepcopy(reviewed)), w.tickets.get(row["id"]) == reviewed]
    cases["first_line_is_the_marker"] = cases["reviewed"].splitlines()[0] == "<!-- zeus-ticket:" + row["id"] + " -->"
    cases["ends_with_one_newline"] = cases["reviewed"].endswith("\n") and not cases["reviewed"].endswith("\n\n")
    cases["bytes"] = len(cases["reviewed"].encode("utf-8"))
    cases["digest"] = api.digest(cases["reviewed"])
    cases["lists_render_as_bullets"] = "## Scope\n\n- deployment" in cases["reviewed"]
    cases["missing_content_key"] = None
    try:
        api.render_ticket({k: v for k, v in reviewed.items() if k != "content"})
    except BaseException as exc:  # noqa: BLE001
        cases["missing_content_key"] = {"type": type(exc).__name__}
    return {"render": cases}


def run(api) -> dict:
    groups = {}
    for step in (a_surface, b_validate_content, c_create, d_update, e_get_list, f_review, g_dispatch, h_binding, i_render):
        groups.update(step(api))
    return {**groups, "m7_tests": M7_TESTS, "cases_per_group": {k: len(v) for k, v in groups.items()}}
