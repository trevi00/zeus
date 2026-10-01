"""Shared S8 scenario steps (`intake.portfolio`): M7 `application/portfolio.py` (`Portfolio` and its module functions) and
`adapters/portfolio.py`, characterized BEFORE pilot 63 moves them (DESIGN-s8 §2 row `intake.portfolio` and §6 V11; the
branch table `branch-table-intake.txt` section `application/portfolio.py`: 25 functions, 36 refusals).

- **g1_definitions**: `validate_definitions` (every refusal, the accepted boundaries, the cached and identical forms),
  `validate_evidence`, the packaged definitions, and the M7 `test_definitions_are_validated_and_every_goal_is_visible_...`.
- **g2_bindings_investigations**: `Portfolio.bind` and every refusal reachable with labelled rows, `inherit_binding`
  (`LINEAGE_AUTHORITY`), the investigation kinds the projection reads (`failure_family`, `audit_progress`), `family_id`,
  `classified_failure`, `failure_families`, `FAMILY_MINIMUM`, `RESEARCH_REQUIRED` and `Portfolio.disposition`; the M7
  `test_binding_is_exact_immutable_...`, `test_two_terminal_failures_make_one_durable_candidate_...`,
  `test_classifier_separates_...` and `test_new_failures_extend_a_candidate_...`.
- **g3_acceptances_followups**: `Portfolio.accept` and `Portfolio.follow_up` with every refusal; the M7
  `test_criterion_acceptance_comes_only_from_the_owner_record` and ALL NINE `tests/test_portfolio_followups.py` tests.
- **g4_status_activity**: `status_projection`, `job_entry`, `follow_up_view`, `project_activity`, `activity_mode`, the
  vocabulary (`STATUS_SCHEMA`, `ACTIVITY_COUNTS`, `UNCLASSIFIED`, the Fleet statuses it reads), sampling and counting.
- **g5_reconcile_adapter**: the module `reconcile` and `Portfolio.reconcile`, `adapters.portfolio` (`packaged_definitions`,
  `portfolio`, `portfolio_reconciler`), the module surface; the portfolio side of the M7 runner/monitor/CLI tests.

Layer: harness (never shipped)

This module never imports `codex_harness`: everything from the product arrives through `api`, the object a reference
(later a target) driver builds. Every double is LABELLED where it is made: Fleet job rows are LABELLED synthetic rows
(`put_job`: only the fields the portfolio reads, as the M7 `row()` helper of `test_portfolio_followups`), written straight
into the `fleet_jobs` bucket of a `MemoryStore`; a binding or an investigation row that no honest call path writes is
LABELLED where it is written. The M7 tests that build jobs through the real `Fleet` API, `FleetRunner`, `fleet_cli` and
`monitoring.collect` belong to other families: their portfolio side is characterized here over synthetic rows, and the rest
is reported `{"unreachable": ...}`. No repository, provider, network, process or PostgreSQL is touched. For every refusal the
digest of the whole store before and after is recorded (nothing written)."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from types import SimpleNamespace

import s8_research_program as R

CANARY = "CANARY-must-never-be-emitted"
T0 = "2026-09-20T00:00:00+00:00"
LINKED_AT = "2026-09-20T05:00:00+00:00"
PROJECT, CRITERION, OTHER_CRITERION = "sterk-migration", "projects", "coverage"
OTHER_PROJECT = ("research-improvement", "recurrence")
REFS = ["sha256:" + "d" * 64, "docs/zeus/operations/operating-portfolio-001/SPEC.md"]


# ---- builders ---------------------------------------------------------------------------------------------------------
def system(api, ws, definitions=None, value=T0, step=0, store=None):
    """A `Portfolio` over a `MemoryStore` with the labelled settable clock (`R.Clock`) and the packaged definitions."""
    store = store or api.MemoryStore()
    clock = R.Clock(value, step)
    book = api.Portfolio(store, api.packaged_definitions() if definitions is None else definitions, clock=clock)
    return SimpleNamespace(api=api, ws=ws, store=store, clock=clock, book=book)


def put(store, bucket, key, body):
    with store.transaction() as tx:
        tx.put(bucket, key, body)


def get(store, bucket, key):
    with store.transaction() as tx:
        return tx.get(bucket, key)


def scan(store, bucket):
    with store.transaction() as tx:
        return tx.scan(bucket)


def put_job(s, job_id, status, reason=None, lane="a", updated=T0):
    """LABELLED synthetic Fleet job row: only the fields the portfolio reads (`id`, `lane`, `status`, `reason_code`,
    `updated_at`)."""
    put(s.store, s.api.BUCKET_JOBS, job_id, {"id": job_id, "lane": lane, "status": status, "reason_code": reason,
                                             "updated_at": updated})


def put_binding(s, job_id, project=PROJECT, criterion=CRITERION):
    """LABELLED synthetic binding row, written directly (a target no honest `bind` accepts is reachable this way)."""
    put(s.store, s.api.BUCKET_BINDINGS, job_id, {"id": job_id, "job_id": job_id, "project_id": project,
                                                 "criterion_id": criterion, "recorded_by": "owner", "created_at": T0})


def bound_job(s, job_id, status, reason=None, project=PROJECT, criterion=CRITERION, lane="a", updated=T0):
    """A job row and its REAL owner binding (`Portfolio.bind`)."""
    put_job(s, job_id, status, reason, lane, updated)
    return s.book.bind(job_id, project, criterion)


def job_rows(store, api):
    return {r["id"]: r for r in scan(store, api.BUCKET_JOBS)}


def obs(s, fn, *args, **kwargs):
    """One call: its value or refusal, and the digest of the whole store before and after (nothing written)."""
    before = R.store_digest(s.store)
    result = R.call(s.ws, fn, *args, **kwargs)
    after = R.store_digest(s.store)
    return {**result, "store_before": before, "store_after": after, "nothing_written": before == after}


def leak(result):
    """Whether a refusal message holds a value (a refusal names a field, never a value)."""
    return CANARY in str(result.get("message", ""))


def view_project(view, project_id=PROJECT):
    return next(p for p in view["projects"] if p["id"] == project_id)


def entries(view, project_id=PROJECT):
    return {job["id"]: job for job in view_project(view, project_id)["jobs"]}


def row_job(job_id, status, updated=T0, reason=None):
    return {"id": job_id, "status": status, "lane": "a", "reason_code": reason, "updated_at": updated}


def row_binding(job_id, project=PROJECT, criterion=CRITERION):
    return {"id": job_id, "job_id": job_id, "project_id": project, "criterion_id": criterion}


def row_link(failed_id, successor_id, refs=REFS):
    return {"id": failed_id, "failed_job_id": failed_id, "successor_job_id": successor_id, "evidence_refs": list(refs),
            "created_at": LINKED_AT}


def definitions(api):
    return api.Portfolio(api.MemoryStore(), api.packaged_definitions()).definitions


def verdict(ws, fn, *args):
    """The validators are pure: accepted (digest of the normalized value) or the refusal with its leak flag."""
    result = R.call(ws, fn, *args)
    if "value" in result:
        return {"accepted": True, "sha256": R.canonical_digest(result["value"])}
    return {**result, "leaks_value": leak(result)}


# ---- G1 --------------------------------------------------------------------------------------------------------------------
def broken_definitions(api):
    """LABELLED synthetic documents: one per refusal branch of `validate_definitions` (and `_fields`)."""
    d = api.packaged_definitions()
    p = deepcopy(d["projects"][0])

    def proj(**kw):
        return {**d, "projects": [{**p, **kw}]}

    def crit(criteria):
        return proj(criteria=criteria)

    def many(n):
        return {**d, "projects": [{**p, "id": "p%02d" % i} for i in range(n)]}
    missing = {k: v for k, v in p.items() if k != "outcome"}
    return {
        "top_not_a_dict": [], "top_extra_key": {**d, "extra": 1}, "top_missing_projects": {"schema": d["schema"]},
        "top_missing_schema": {"projects": d["projects"]},
        "schema_other_version": {**d, "schema": "urn:zeus:portfolio-definitions:2"}, "schema_not_a_string": {**d, "schema": 1},
        "projects_not_a_list": {**d, "projects": {}}, "projects_empty": {**d, "projects": []}, "projects_17": many(17),
        "project_not_a_dict": {**d, "projects": ["x"]}, "project_extra_key": proj(extra=1),
        "project_missing_key": {**d, "projects": [missing]},
        "id_with_space_and_canary": proj(id="bad id " + CANARY), "id_empty": proj(id=""), "id_65_chars": proj(id="x" * 65),
        "id_starts_with_underscore": proj(id="_a"), "id_starts_with_dot": proj(id=".a"), "id_not_a_string": proj(id=3),
        "id_bool": proj(id=True), "title_empty": proj(title=""), "title_blank": proj(title="   "),
        "title_121_chars": proj(title="t" * 121), "title_canary_times_40": proj(title=CANARY * 40),
        "title_control_char": proj(title="a\tb"), "title_not_a_string": proj(title=None),
        "outcome_601_chars": proj(outcome="o" * 601), "outcome_empty": proj(outcome=""),
        "source_ref_absolute": proj(source_ref="/tmp/x.md"), "source_ref_parent": proj(source_ref="../secrets.md"),
        "source_ref_not_a_string": proj(source_ref=3), "source_ref_empty": proj(source_ref=""),
        "criteria_not_a_list": crit({}), "criteria_empty": crit([]), "criteria_17": crit(
            [{"id": "c%02d" % i, "text": "t"} for i in range(17)]),
        "criterion_not_a_dict": crit(["x"]), "criterion_extra_key": crit([{"id": "x", "text": "t", "done": True}]),
        "criterion_missing_key": crit([{"id": "x"}]), "criterion_id_bad": crit([{"id": "x y", "text": "t"}]),
        "criterion_text_empty": crit([{"id": "x", "text": ""}]), "criterion_text_601": crit([{"id": "x", "text": "t" * 601}]),
        "criteria_duplicate_ids": proj(criteria=p["criteria"] + [p["criteria"][0]]),
        "projects_duplicate_ids": {**d, "projects": [p, p]},
        "projects_duplicate_ids_with_other_valid": {**d, "projects": [p, d["projects"][1], p]},
    }


def accepted_definitions(api):
    """LABELLED boundary documents the validator accepts (the limits are inclusive)."""
    d = api.packaged_definitions()
    p = deepcopy(d["projects"][0])

    def proj(**kw):
        return {**d, "projects": [{**p, **kw}]}
    return {
        "id_64_chars": proj(id="x" * 64), "id_unicode_alphanumeric": proj(id="üï.-_a"), "id_with_dot_dash_underscore": proj(id="a.b-c_d"),
        "title_120_chars": proj(title="t" * 120), "title_padded_keeps_whitespace": proj(title="  t  "),
        "outcome_600_chars": proj(outcome="o" * 600), "outcome_newline_allowed": proj(outcome="a\nb"),
        "criteria_16": proj(criteria=[{"id": "c%02d" % i, "text": "t"} for i in range(16)]),
        "projects_16": {**d, "projects": [{**p, "id": "p%02d" % i} for i in range(16)]},
        "source_ref_nested": proj(source_ref="docs/a/b.md"),
    }


def g1_definitions(api, ws):
    results = {}
    packaged = api.packaged_definitions()
    book = api.Portfolio(api.MemoryStore(), packaged)
    results["packaged_definitions"] = {
        "schema": packaged["schema"], "projects": [[p["id"], [c["id"] for c in p["criteria"]]] for p in packaged["projects"]],
        "sha256": R.canonical_digest(packaged), "name": api.DEFINITIONS,
        "constants": {"DEFINITIONS_SCHEMA": api.DEFINITIONS_SCHEMA, "STATUS_SCHEMA": api.STATUS_SCHEMA,
                      "limits": {"MAX_PROJECTS": api.MAX_PROJECTS, "MAX_CRITERIA": api.MAX_CRITERIA, "MAX_ID": api.MAX_ID,
                                 "MAX_TITLE": api.MAX_TITLE, "MAX_TEXT": api.MAX_TEXT, "MAX_REF": api.MAX_REF,
                                 "MAX_REFS": api.MAX_REFS}}}
    first, second = api.validate_definitions(packaged), api.validate_definitions(packaged)
    results["validate_identical_form"] = {
        "equal_to_input": first == packaged, "equal_again": first == second, "same_object_as_input": first is packaged,
        "same_object_twice": first is second, "projects_are_copies": first["projects"][0] is not packaged["projects"][0],
        "portfolio_definitions_equal_validated": book.definitions == first,
        "definition_sha256_is_digest_of_definitions": book.definition_sha256 == api.digest(book.definitions),
        "sha256": book.definition_sha256}
    results["validate_never_mutates_the_input"] = {"unchanged": deepcopy(packaged) == packaged and first == packaged}
    results["portfolio_cached_form_two_instances_agree"] = {
        "equal_sha": api.Portfolio(api.MemoryStore(), packaged).definition_sha256 == book.definition_sha256}
    for name, document in accepted_definitions(api).items():
        results["accepted_" + name] = verdict(ws, api.validate_definitions, document)
    for name, document in broken_definitions(api).items():
        results["refused_" + name] = verdict(ws, api.validate_definitions, document)
    # M7 test_definitions_are_validated...: the Portfolio constructor refuses what the validator refuses, naming a field.
    project = deepcopy(packaged["projects"][0])
    m7 = [{"schema": "urn:zeus:portfolio-definitions:2"}, {"projects": []}, {"projects": {}},
          {"projects": [{**project, "id": "bad id " + CANARY}]}, {"projects": [{**project, "title": CANARY * 40}]},
          {"projects": [{**project, "source_ref": "/tmp/x.md"}]}, {"projects": [{**project, "source_ref": "../secrets.md"}]},
          {"projects": [{**project, "criteria": []}]}, {"projects": [{**project, "criteria": [{"id": "x", "text": ""}]}]},
          {"projects": [{**project, "criteria": [{"id": "x", "text": "t", "done": True}]}]},
          {"projects": [{**project, "criteria": project["criteria"] + [project["criteria"][0]]}]},
          {"projects": [project, project]}, {"extra": 1}]
    constructor = []
    for override in m7:
        store = api.MemoryStore()
        result = R.call(ws, api.Portfolio, store, {**packaged, **override})
        constructor.append({"raised": result.get("raised"), "reason_code": result.get("reason_code"),
                            "field": result.get("field"), "leaks_value": leak(result),
                            "starts_with_definitions": str(result.get("reason_code")).startswith("definitions_"),
                            "agrees_with_validate": verdict(ws, api.validate_definitions, {**packaged, **override}).get(
                                "reason_code") == result.get("reason_code")})
    results["m7_constructor_refusals_name_a_field_never_a_value"] = constructor
    s = system(api, ws, store=api.MemoryStore())
    view = s.book.status()
    results["m7_every_goal_is_visible_before_any_binding"] = {
        "schema": view["schema"], "definition_sha256_matches": view["definition_sha256"] == api.digest(s.book.definitions),
        "project_ids_in_order": [p["id"] for p in view["projects"]] == [p["id"] for p in packaged["projects"]],
        "projects": [{"id": p["id"], "jobs": p["jobs"], "jobs_truncated": p["jobs_truncated"],
                      "criteria_statuses": sorted({c["status"] for c in p["criteria"]}),
                      "criteria_refs_empty": all(c["evidence_refs"] == [] for c in p["criteria"]), "counts": p["counts"],
                      "activity": p["activity"]} for p in view["projects"]],
        "investigations": view["investigations"], "investigations_truncated": view["investigations_truncated"],
        "unbound_jobs": view["unbound_jobs"], "unclassified_failures": view["unclassified_failures"],
        "progress": [view["progress_investigations"], view["progress_investigations_truncated"]],
        "store_after": R.store_digest(s.store)}
    results["adapter_portfolio_default_definitions_status_equal"] = {
        "equal": api.portfolio(api.MemoryStore()).status() == view}
    # validate_evidence: every branch.
    ev = {}
    for name, refs in {
            "ok_two": REFS, "ok_one": ["x"], "ok_ten": ["r%d" % i for i in range(10)], "ok_200_chars": ["x" * 200],
            "ok_padded_kept": ["  x  "], "not_a_list_tuple": tuple(REFS), "not_a_list_string": "sha256:x", "none": None,
            "empty": [], "eleven": ["r%d" % i for i in range(11)], "non_string_item": [REFS[0], 3], "empty_string_item": [""],
            "blank_item": ["   "], "item_201_chars": ["x" * 201], "item_with_newline": ["a\nb"],
            "item_with_control_char": ["a\tb"], "item_canary_times_40": [CANARY * 40], "duplicates": [REFS[0]] * 2,
            "duplicate_after_distinct": ["a", "b", "a"], "bytes_item": [b"x"]}.items():
        ev[name] = verdict(ws, api.validate_evidence, refs)
    given = list(REFS)
    out = api.validate_evidence(given)
    ev["returns_a_copy"] = {"equal": out == given, "same_object": out is given}
    results["validate_evidence"] = ev
    return results


# ---- G2 --------------------------------------------------------------------------------------------------------------------
def g2_bindings_investigations(api, ws):
    results = {}
    # -- bind (M7 test_binding_is_exact_immutable_and_leaves_fleet_rows_untouched) --
    s = system(api, ws)
    put_job(s, "op-1", "queued")
    jobs_before = R.canonical_digest(scan(s.store, api.BUCKET_JOBS))
    results["bind_job_unknown"] = obs(s, s.book.bind, "op-absent", PROJECT, CRITERION)
    results["bind_project_unknown"] = obs(s, s.book.bind, "op-1", "no-such-project", CRITERION)
    results["bind_criterion_unknown"] = obs(s, s.book.bind, "op-1", PROJECT, "no-such-criterion")
    results["bind_criterion_of_another_project_is_unknown"] = obs(s, s.book.bind, "op-1", PROJECT, "recurrence")
    results["bind_target_is_checked_before_the_job_id"] = obs(s, s.book.bind, None, "no-such-project", CRITERION)
    for name, job_id in (("none", None), ("empty", ""), ("int", 3), ("bytes", b"op-1")):
        results["bind_invalid_job_id_" + name] = obs(s, s.book.bind, job_id, PROJECT, CRITERION)
    results["bind_first"] = obs(s, s.book.bind, "op-1", PROJECT, CRITERION)
    results["bind_row_in_the_store"] = get(s.store, api.BUCKET_BINDINGS, "op-1")
    results["bind_identical_replay_is_cached"] = obs(s, s.book.bind, "op-1", PROJECT, CRITERION)
    results["bind_other_target_conflicts"] = obs(s, s.book.bind, "op-1", "research-improvement", "recurrence")
    results["bind_other_criterion_conflicts"] = obs(s, s.book.bind, "op-1", PROJECT, OTHER_CRITERION)
    results["bind_leaves_the_job_rows_untouched"] = {
        "jobs_unchanged": R.canonical_digest(scan(s.store, api.BUCKET_JOBS)) == jobs_before,
        "buckets": sorted({r["bucket"] for r in _records(s.store)})}
    shown = view_project(s.book.status())
    results["bind_projection"] = {"jobs": shown["jobs"], "counts": shown["counts"],
                                  "unbound_jobs": s.book.status()["unbound_jobs"]}
    returned = s.book.bind("op-1", PROJECT, CRITERION)
    returned["binding"]["project_id"] = "mutated"
    results["bind_returned_record_is_a_copy"] = {"stored_project": get(s.store, api.BUCKET_BINDINGS, "op-1")["project_id"]}
    # -- binding to a job through the clock: the recorded time is the clock's read --
    t = system(api, ws, value=LINKED_AT, step=0)
    put_job(t, "op-t", "accepted")
    results["bind_records_the_clock_read"] = {"created_at": t.book.bind("op-t", PROJECT, CRITERION)["binding"]["created_at"]}
    # -- inherit_binding (LINEAGE_AUTHORITY) --
    results["lineage_authority"] = api.LINEAGE_AUTHORITY
    lineage = {"intent": "i-1", "program": "rp-001"}

    def inherit(store, job, origin, lin, now=LINKED_AT):
        with store.transaction() as tx:
            return api.inherit_binding(tx, job, origin, lin, now)
    i = system(api, ws)
    put_job(i, "origin", "accepted")
    put_job(i, "child", "queued")
    put_job(i, "orphan-origin", "accepted")
    results["inherit_unbound_origin_returns_none"] = obs(i, inherit, i.store, "child", "orphan-origin", lineage)
    results["inherit_origin_absent_returns_none"] = obs(i, inherit, i.store, "child", "no-origin", lineage)
    i.book.bind("origin", PROJECT, OTHER_CRITERION)
    results["inherit_unknown_job"] = obs(i, inherit, i.store, "ghost", "origin", lineage)
    results["inherit_first"] = obs(i, inherit, i.store, "child", "origin", lineage)
    results["inherit_row_in_the_store"] = get(i.store, api.BUCKET_BINDINGS, "child")
    results["inherit_replay_is_cached"] = obs(i, inherit, i.store, "child", "origin", {"other": "lineage ignored on replay"})
    results["inherit_projection_places_the_job_under_the_origin_target"] = {
        "jobs": [j["id"] for j in view_project(i.book.status())["jobs"]],
        "criterion": [j["criterion_id"] for j in view_project(i.book.status())["jobs"]]}
    put_job(i, "owner-bound", "queued")
    i.book.bind("owner-bound", PROJECT, CRITERION)
    results["inherit_existing_other_target_conflicts"] = obs(i, inherit, i.store, "owner-bound", "origin", lineage)
    put_job(i, "owner-same", "queued")
    i.book.bind("owner-same", PROJECT, OTHER_CRITERION)
    results["inherit_existing_owner_binding_of_the_same_target_replays"] = obs(i, inherit, i.store, "owner-same", "origin",
                                                                              lineage)
    put_job(i, "own", "queued")
    results["inherit_lineage_may_override_origin_job"] = {
        "binding": inherit(i.store, "own", "origin", {"origin_job": "claimed-elsewhere", "x": 1})["binding"]["lineage"]}
    results["inherit_refusal_is_not_a_nested_transaction"] = {
        "refused_inside_an_open_transaction": _inherit_inside_open_tx(api, i, "ghost2", "origin", lineage)}
    # -- the investigation kinds, family_id, the classifier (M7 test_classifier_separates_...) --
    results["vocabulary"] = {
        "FAILURE_KIND": api.FAILURE_KIND, "PROGRESS_KIND": api.PROGRESS_KIND, "FAMILY_MINIMUM": api.FAMILY_MINIMUM,
        "RESEARCH_REQUIRED": api.RESEARCH_REQUIRED, "RESEARCHED": api.RESEARCHED, "DEFERRED": api.DEFERRED,
        "DISPOSITIONS": sorted(api.DISPOSITIONS), "FAILURE_STATUSES": sorted(api.FAILURE_STATUSES),
        "UNCLASSIFIED": api.UNCLASSIFIED, "SAMPLE": api.SAMPLE,
        "buckets": [api.BUCKET_BINDINGS, api.BUCKET_ACCEPTANCES, api.BUCKET_INVESTIGATIONS, api.BUCKET_FOLLOWUPS]}
    fid = api.family_id("failed", "child_refused")
    results["family_id"] = {
        "value": fid, "equals_digest_of_the_pair": fid == api.digest({"family_status": "failed", "reason_code": "child_refused"}),
        "stable": fid == api.family_id("failed", "child_refused"), "differs_by_status": fid != api.family_id("rejected", "child_refused"),
        "differs_by_reason": fid != api.family_id("failed", "other"), "length": len(fid)}
    classified = {}
    for name, job in {
            "failed_safe": {"id": "j", "status": "failed", "reason_code": "child_refused"},
            "rejected_safe": {"id": "j", "status": "rejected", "reason_code": "lead_rejected"},
            "failed_unknown_code": {"status": "failed", "reason_code": "unknown"},
            "failed_none_reason": {"status": "failed", "reason_code": None},
            "failed_missing_reason": {"status": "failed"}, "failed_empty_reason": {"status": "failed", "reason_code": ""},
            "failed_unsafe_reason": {"status": "failed", "reason_code": "raw: " + CANARY},
            "failed_non_string_reason": {"status": "failed", "reason_code": 3},
            "unknown_status": {"status": "unknown", "reason_code": "receipt_missing"},
            "accepted": {"status": "accepted", "reason_code": "lead_accepted"},
            "exhausted": {"status": "exhausted", "reason_code": "budget_exhausted"},
            "dispatching": {"status": "dispatching", "reason_code": None},
            "queued": {"status": "queued", "reason_code": "capacity"}, "no_status": {}}.items():
        classified[name] = api.classified_failure({"id": "j", **job})
    results["classified_failure"] = classified
    families, unclassified = api.failure_families([
        {"id": "j-1", "status": "failed", "reason_code": "unknown"}, {"id": "j-2", "status": "failed", "reason_code": "unknown"},
        {"id": "j-3", "status": "failed", "reason_code": "child_refused"},
        {"id": "j-3", "status": "failed", "reason_code": "child_refused"},    # replay of one job
        {"id": "j-4", "status": "unknown", "reason_code": "receipt_missing"},
        {"id": "j-5", "status": "rejected", "reason_code": "lead_rejected"}, {"id": "j-6", "status": "rejected", "reason_code": "lead_rejected"},
        {"status": "failed", "reason_code": "child_refused"}, {"id": "", "status": "failed", "reason_code": "child_refused"},
        {"id": 7, "status": "failed", "reason_code": "child_refused"}, {"id": None, "status": "failed", "reason_code": None}])
    results["failure_families"] = {"families": [[list(k), sorted(v)] for k, v in sorted(families.items())],
                                   "unclassified": unclassified}
    results["failure_families_empty"] = list(map(lambda x: x if not isinstance(x, dict) else dict(x), api.failure_families([])))
    # -- M7 test_two_terminal_failures_make_one_durable_candidate_and_replay_adds_nothing --
    c = system(api, ws)
    for job_id, status, reason, lane in (
            ("op-1", "failed", "child_refused", "a"), ("op-2", "failed", "child_refused", "b"),
            ("op-3", "rejected", "lead_rejected", "a"), ("op-4", "failed", "exception:OSError: /home/owner/secret " + CANARY, "a"),
            ("op-5", "failed", None, "a"), ("op-6", "unknown", "receipt_missing", "b"), ("op-7", "queued", None, "a")):
        put_job(c, job_id, status, reason, lane)
    marks = iter(["2026-09-20T01:00:00+00:00", "2026-09-20T02:00:00+00:00"])
    summary = api.reconcile(c.store, lambda: next(marks))
    view = c.book.status()
    results["m7_two_failures_make_one_candidate"] = {
        "summary": summary, "candidates": view["investigations"], "truncated": view["investigations_truncated"],
        "unclassified_failures": view["unclassified_failures"], "unbound_jobs": view["unbound_jobs"],
        "leaks_canary_or_path": CANARY in json.dumps(view) or "/home/owner" in json.dumps(view),
        "row": get(c.store, api.BUCKET_INVESTIGATIONS, fid)}
    before = R.store_digest(c.store)
    replay = api.reconcile(c.store, lambda: next(marks))
    results["m7_replay_over_an_unchanged_fleet_writes_nothing"] = {"summary": replay, "nothing_written": before == R.store_digest(c.store)}
    results["m7_uncertain_and_active_work_keep_their_fleet_meaning"] = {
        "unknown_job_status": job_rows(c.store, api)["op-6"]["status"], "queued": job_rows(c.store, api)["op-7"]["status"],
        "families_over_the_fleet": [[list(k), sorted(v)] for k, v in sorted(api.failure_families(
            scan(c.store, api.BUCKET_JOBS))[0].items())]}
    # reconcile over rows that are all unclassified writes no candidate
    u = system(api, ws)
    put_job(u, "j-1", "failed", "unknown")
    put_job(u, "j-2", "failed", "unknown")
    results["m7_classifier_unknown_rows_make_no_candidate"] = {
        "summary": api.reconcile(u.store, u.clock), "investigation_rows": len(scan(u.store, api.BUCKET_INVESTIGATIONS))}
    # -- disposition (M7 test_new_failures_extend_a_candidate_without_touching_the_owner_disposition) --
    d = system(api, ws, value="2026-09-20T03:00:00+00:00")
    put_job(d, "op-1", "failed", "child_refused")
    put_job(d, "op-2", "failed", "child_refused", "b")
    api.reconcile(d.store, lambda: "2026-09-20T01:00:00+00:00")
    candidate = d.book.status()["investigations"][0]["id"]
    for name, args in (("state_confirmed", ("confirmed", REFS)), ("state_none", (None, REFS)),
                       ("state_research_required", (api.RESEARCH_REQUIRED, REFS)), ("evidence_empty", ("researched", [])),
                       ("evidence_canary", ("researched", [CANARY * 40])), ("evidence_duplicates", ("deferred", [REFS[0]] * 2)),
                       ("evidence_not_a_list", ("deferred", REFS[0]))):
        results["disposition_refused_" + name] = {**obs(d, d.book.disposition, candidate, *args)}
        results["disposition_refused_" + name]["leaks_value"] = leak(results["disposition_refused_" + name])
    results["disposition_state_is_checked_before_the_candidate"] = obs(d, d.book.disposition, "0" * 64, "confirmed", REFS)
    results["disposition_evidence_is_checked_before_the_candidate"] = obs(d, d.book.disposition, "0" * 64, "deferred", [])
    results["disposition_candidate_unknown"] = obs(d, d.book.disposition, "0" * 64, "deferred", REFS)
    results["disposition_first"] = obs(d, d.book.disposition, candidate, "deferred", REFS)
    results["disposition_identical_replay_is_cached"] = obs(d, d.book.disposition, candidate, "deferred", list(REFS))
    results["disposition_other_state_conflicts"] = obs(d, d.book.disposition, candidate, "researched", REFS)
    results["disposition_other_evidence_conflicts"] = obs(d, d.book.disposition, candidate, "deferred", [REFS[0]])
    results["disposition_reordered_evidence_conflicts"] = obs(d, d.book.disposition, candidate, "deferred", REFS[::-1])
    put_job(d, "op-3", "failed", "child_refused")
    d.clock.value = "2026-09-20T04:00:00+00:00"
    extended = api.reconcile(d.store, lambda: "2026-09-20T04:00:00+00:00")
    row = get(d.store, api.BUCKET_INVESTIGATIONS, candidate)
    results["m7_third_failure_extends_the_decided_candidate"] = {
        "summary": extended, "candidate": d.book.status()["investigations"][0], "decided_at": row["decided_at"]}
    # a disposition of the other kind is the same explicit record (this module decides nothing more about it)
    k = system(api, ws, value=LINKED_AT)
    put(k.store, api.BUCKET_INVESTIGATIONS, "p-1", {"id": "p-1", "kind": api.PROGRESS_KIND, "state": api.RESEARCH_REQUIRED,
                                                    "evidence_refs": [], "decided_at": None, "updated_at": T0})
    results["disposition_applies_to_a_progress_kind_row_the_same_way"] = obs(k, k.book.disposition, "p-1", "researched", REFS)
    put(k.store, api.BUCKET_INVESTIGATIONS, "legacy", {"id": "legacy", "state": api.RESEARCH_REQUIRED, "evidence_refs": [],
                                                        "decided_at": None, "updated_at": T0})
    results["disposition_applies_to_a_legacy_row_without_a_kind"] = obs(k, k.book.disposition, "legacy", "deferred", REFS)
    put(k.store, api.BUCKET_INVESTIGATIONS, "stateless", {"id": "stateless", "evidence_refs": []})
    results["disposition_on_a_row_without_a_state_raises_keyerror"] = obs(k, k.book.disposition, "stateless", "deferred", REFS)
    return results


def _records(store):
    with store.transaction() as tx:
        return tx.records()


def _inherit_inside_open_tx(api, s, job, origin, lineage):
    """LABELLED: a refusal raised inside the caller's open transaction propagates out of that transaction."""
    try:
        with s.store.transaction() as tx:
            api.inherit_binding(tx, job, origin, lineage, LINKED_AT)
    except api.PortfolioRefused as refusal:
        return [refusal.reason_code, refusal.field]
    return None


# ---- G3 --------------------------------------------------------------------------------------------------------------------
def g3_acceptances_followups(api, ws):
    results = {}
    # -- accept (M7 test_criterion_acceptance_comes_only_from_the_owner_record) --
    s = system(api, ws, value=LINKED_AT)
    bound_job(s, "op-1", "accepted", "lead_accepted")

    def criterion(book=s.book):
        project = view_project(book.status())
        return next(c for c in project["criteria"] if c["id"] == CRITERION)
    results["m7_an_accepted_job_is_work_not_the_owner_decision"] = {"criterion": criterion()}
    for name, refs in (("empty", []), ("string", "sha256:x"), ("empty_item", [""]), ("duplicate", [REFS[0]] * 2),
                       ("item_201_chars", ["x" * 201]), ("non_string_item", [REFS[0], 3]), ("none", None),
                       ("eleven", ["r%d" % n for n in range(11)])):
        results["accept_refused_evidence_" + name] = obs(s, s.book.accept, PROJECT, CRITERION, refs)
    results["accept_project_unknown"] = obs(s, s.book.accept, "no-such-project", CRITERION, REFS)
    results["accept_criterion_unknown"] = obs(s, s.book.accept, PROJECT, "no-such-criterion", REFS)
    results["accept_target_is_checked_before_the_evidence"] = obs(s, s.book.accept, "no-such-project", CRITERION, [])
    results["accept_first"] = obs(s, s.book.accept, PROJECT, CRITERION, REFS)
    results["accept_row_in_the_store"] = get(s.store, api.BUCKET_ACCEPTANCES, PROJECT + ":" + CRITERION)
    results["accept_identical_replay_is_cached"] = obs(s, s.book.accept, PROJECT, CRITERION, list(REFS))
    results["accept_other_evidence_conflicts"] = obs(s, s.book.accept, PROJECT, CRITERION, [REFS[0]])
    results["accept_reordered_evidence_conflicts"] = obs(s, s.book.accept, PROJECT, CRITERION, REFS[::-1])
    results["m7_the_criterion_reads_accepted_with_its_refs"] = {
        "criterion": criterion(), "counts": view_project(s.book.status())["counts"]}
    view_criterion = criterion()
    view_criterion["evidence_refs"].append(CANARY)
    results["m7_the_projection_is_a_copy"] = {"refs_after": criterion()["evidence_refs"]}
    returned = s.book.accept(PROJECT, CRITERION, REFS)
    returned["acceptance"]["evidence_refs"].append(CANARY)
    results["accept_returned_record_is_a_copy"] = {"stored": get(s.store, api.BUCKET_ACCEPTANCES, PROJECT + ":" + CRITERION)["evidence_refs"]}
    results["accept_another_criterion_of_the_same_project_is_a_second_row"] = obs(s, s.book.accept, PROJECT, OTHER_CRITERION, ["x"])
    results["accept_is_independent_of_the_job_statuses"] = {
        "statuses": sorted({j["status"] for j in scan(s.store, api.BUCKET_JOBS)}),
        "accepted_criteria": view_project(s.book.status())["counts"]["criteria_accepted"]}
    # -- follow_up: M7 test_owner_link_joins_one_failure_to_its_accepted_successor_and_preserves_the_failure --
    f = system(api, ws, value=LINKED_AT)
    bound_job(f, "op-fail", "failed", "child_refused")
    bound_job(f, "op-next", "accepted", "lead_accepted")
    job_before = deepcopy(get(f.store, api.BUCKET_JOBS, "op-fail"))
    recorded = f.book.follow_up("op-fail", "op-next", REFS)
    results["m7_link_joins_one_failure_to_its_successor"] = {
        "recorded": recorded, "failure_row_untouched": get(f.store, api.BUCKET_JOBS, "op-fail") == job_before,
        "followup_keys": [r["id"] for r in scan(f.store, api.BUCKET_FOLLOWUPS)]}
    view = f.book.status()
    shown = entries(view)
    results["m7_link_projection"] = {
        "failed": shown["op-fail"], "successor_has_no_link_key": "follow_up" not in shown["op-next"],
        "activity": view_project(view)["activity"],
        "criteria_statuses": sorted({c["status"] for c in view_project(view)["criteria"]}),
        "criteria_accepted": view_project(view)["counts"]["criteria_accepted"],
        "other_project_activity": view_project(view, OTHER_PROJECT[0])["activity"]}
    recorded["follow_up"]["evidence_refs"].append(CANARY)
    results["m7_link_returned_record_is_a_copy"] = {"canary_reaches_the_projection": CANARY in json.dumps(f.book.status())}
    # -- M7 test_link_is_refused_unless_both_jobs_are_bound_accepted_and_on_the_same_criterion --
    r = system(api, ws, value=LINKED_AT)
    bound_job(r, "op-fail", "failed", "child_refused")
    bound_job(r, "op-spent", "exhausted", "budget_exhausted")
    put_job(r, "op-orphan", "failed", "child_refused")                    # deliberately unbound
    bound_job(r, "op-elsewhere", "accepted", "lead_accepted", *OTHER_PROJECT)
    put_job(r, "op-unbound", "accepted", "lead_accepted")                 # deliberately unbound
    bound_job(r, "op-next", "accepted", "lead_accepted", criterion=OTHER_CRITERION)
    bound_job(r, "op-repair", "accepted", "lead_accepted")
    bound_job(r, "op-queued", "queued")
    bound_job(r, "op-running", "dispatching")
    bound_job(r, "op-unknown", "unknown", "receipt_missing")
    bound_job(r, "op-rejected", "rejected", "lead_rejected")
    refusals = [
        ("origin_job_absent", ("op-absent", "op-next", REFS)), ("successor_job_absent", ("op-fail", "op-absent", REFS)),
        ("same_job", ("op-fail", "op-fail", REFS)), ("failed_id_empty", ("", "op-next", REFS)),
        ("successor_id_not_a_string", ("op-fail", 3, REFS)), ("failed_id_none", (None, "op-next", REFS)),
        ("successor_id_empty", ("op-fail", "", REFS)),
        ("origin_is_accepted_not_history", ("op-next", "op-fail", REFS)), ("origin_is_queued", ("op-queued", "op-next", REFS)),
        ("origin_is_dispatching", ("op-running", "op-repair", REFS)), ("origin_is_unknown", ("op-unknown", "op-repair", REFS)),
        ("successor_is_queued", ("op-fail", "op-queued", REFS)), ("successor_is_dispatching", ("op-fail", "op-running", REFS)),
        ("successor_is_unknown", ("op-fail", "op-unknown", REFS)), ("successor_is_failed", ("op-fail", "op-rejected", REFS)),
        ("origin_unbound", ("op-orphan", "op-unbound", REFS)), ("successor_unbound", ("op-fail", "op-unbound", REFS)),
        ("other_project", ("op-fail", "op-elsewhere", REFS)), ("other_criterion", ("op-fail", "op-next", REFS)),
        ("evidence_empty", ("op-fail", "op-repair", [])), ("evidence_canary", ("op-fail", "op-repair", [CANARY * 40])),
        ("evidence_duplicates", ("op-fail", "op-repair", [REFS[0]] * 2)),
        ("ids_are_checked_before_the_evidence", ("", "op-repair", [])),
        ("evidence_is_checked_before_the_jobs", ("op-absent", "op-repair", [])),
        ("jobs_are_checked_before_the_statuses", ("op-absent", "op-queued", REFS))]
    for name, arguments in refusals:
        result = obs(r, r.book.follow_up, *arguments)
        results["m7_link_refused_" + name] = {**result, "leaks_value": leak(result)}
    results["m7_link_no_follow_up_row_after_the_refusals"] = {"rows": len(scan(r.store, api.BUCKET_FOLLOWUPS))}
    results["m7_exhausted_is_history_the_owner_may_link"] = obs(r, r.book.follow_up, "op-spent", "op-repair", REFS)
    results["rejected_is_history_the_owner_may_link"] = obs(r, r.book.follow_up, "op-rejected", "op-repair", REFS)
    after = r.book.status()
    results["m7_exhausted_link_projection"] = {
        "state": entries(after)["op-spent"]["follow_up"]["state"], "activity": view_project(after)["activity"]}
    # a binding whose project the definitions no longer define: the last `_target` check of follow_up
    put_job(r, "op-old-fail", "failed", "child_refused")
    put_job(r, "op-old-next", "accepted", "lead_accepted")
    put_binding(r, "op-old-fail", "retired-project", "c")
    put_binding(r, "op-old-next", "retired-project", "c")
    results["link_refused_project_no_longer_defined"] = obs(r, r.book.follow_up, "op-old-fail", "op-old-next", REFS)
    put_job(r, "op-old2-fail", "failed", "child_refused")
    put_job(r, "op-old2-next", "accepted", "lead_accepted")
    put_binding(r, "op-old2-fail", PROJECT, "retired-criterion")
    put_binding(r, "op-old2-next", PROJECT, "retired-criterion")
    results["link_refused_criterion_no_longer_defined"] = obs(r, r.book.follow_up, "op-old2-fail", "op-old2-next", REFS)
    # -- M7 test_link_is_immutable_replayed_exactly_and_refuses_a_conflicting_rewrite --
    i = system(api, ws, value=LINKED_AT)
    bound_job(i, "op-fail", "failed", "child_refused")
    bound_job(i, "op-next", "accepted", "lead_accepted")
    bound_job(i, "op-other", "accepted", "lead_accepted")
    first = obs(i, i.book.follow_up, "op-fail", "op-next", REFS)
    stored = deepcopy(get(i.store, api.BUCKET_FOLLOWUPS, "op-fail"))
    i.clock.value = "2026-09-21T09:00:00+00:00"
    replay = obs(i, i.book.follow_up, "op-fail", "op-next", list(REFS))
    results["m7_link_first"] = first
    results["m7_link_exact_replay"] = {**replay, "equals_the_stored_row": replay.get("value", {}).get("follow_up") == stored}
    for name, arguments in (("other_successor", ("op-fail", "op-other", REFS)), ("other_evidence", ("op-fail", "op-next", [REFS[0]])),
                            ("reordered_evidence", ("op-fail", "op-next", REFS[::-1]))):
        results["m7_link_conflict_" + name] = obs(i, i.book.follow_up, *arguments)
    results["m7_link_conflict_leaves_one_row"] = {
        "row_unchanged": get(i.store, api.BUCKET_FOLLOWUPS, "op-fail") == stored,
        "keys": [x["id"] for x in scan(i.store, api.BUCKET_FOLLOWUPS)]}
    # the replay is answered before the jobs are even read: a cached link survives a vanished successor row
    del i.store.data[(api.BUCKET_JOBS, "op-next")]    # LABELLED: the in-memory store has no delete; a vanished row
    results["link_replay_survives_a_vanished_successor_row"] = obs(i, i.book.follow_up, "op-fail", "op-next", REFS)
    results["link_replay_with_a_vanished_successor_and_other_evidence_conflicts"] = obs(
        i, i.book.follow_up, "op-fail", "op-next", ["x"])
    # -- M7 test_two_concurrent_links_for_one_failure_leave_exactly_one_row (the in-memory store; PG is out of scope) --
    t = system(api, ws, value=LINKED_AT)
    bound_job(t, "op-fail", "failed", "child_refused")
    bound_job(t, "op-next", "accepted", "lead_accepted")
    bound_job(t, "op-other", "accepted", "lead_accepted")

    def attempt(successor):
        try:
            return t.book.follow_up("op-fail", successor, REFS)["follow_up"]["successor_job_id"]
        except api.PortfolioRefused as refusal:
            return refusal.reason_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = set(pool.map(attempt, ("op-next", "op-other")))
    rows = scan(t.store, api.BUCKET_FOLLOWUPS)
    results["m7_two_concurrent_links_leave_exactly_one_row"] = {
        "rows": len(rows), "failed": rows[0]["failed_job_id"], "winner_is_one_of_the_two": rows[0]["successor_job_id"] in {"op-next", "op-other"},
        "outcomes_are_the_winner_and_followup_conflict": outcomes == {"followup_conflict", rows[0]["successor_job_id"]}}
    # -- the projection tests of test_portfolio_followups (their projection side is g4's `status_projection` cases too) --
    results["m7_a_link_the_current_rows_no_longer_support_reads_as_unknown"] = _unsupported_links(api)
    results["m7_activity_counts_the_full_population_and_the_mode_never_hides_uncertainty"] = _full_population(api)
    results["m7_a_collector_without_follow_up_rows_keeps_the_previous_shape"] = _previous_shape(api)
    results["m7_monitor_envelope_carries_the_additive_fields"] = {
        "unreachable": "monitoring.collect and monitoring.read_only belong to the monitoring adapter (another family, with docker and "
                       "redis facts); the portfolio side is the read-only status(), asserted here to write nothing",
        "status_writes_nothing": _status_writes_nothing(api, ws)}
    results["m7_link_over_postgres_is_one_atomic_row"] = {
        "unreachable": "needs the real PostgreSQL store (out of scope, DESIGN-s8 §6: PG cases are integration); the memory-store "
                       "form is m7_link_first, m7_link_exact_replay, m7_link_conflict_* and the concurrent case"}
    return results


def _status_writes_nothing(api, ws):
    s = system(api, ws, value=LINKED_AT)
    bound_job(s, "op-fail", "failed", "child_refused")
    bound_job(s, "op-next", "accepted", "lead_accepted")
    s.book.follow_up("op-fail", "op-next", REFS)
    before = R.store_digest(s.store)
    status = s.book.status()
    return {"nothing_written": before == R.store_digest(s.store), "link_state": entries(status)["op-fail"]["follow_up"]["state"],
            "activity": view_project(status)["activity"], "canary_free": CANARY not in json.dumps(status)}


def _unsupported_links(api):
    """M7 `test_a_link_the_current_rows_no_longer_support_reads_as_unknown_never_resolved` (synthetic rows, verbatim)."""
    jobs = [row_job("op-a", "failed", reason="child_refused"), row_job("op-b", "rejected", reason="lead_rejected"),
            row_job("op-c", "failed", reason="child_refused"), row_job("op-d", "exhausted", reason="budget_exhausted"),
            row_job("op-running", "dispatching"), row_job("op-free", "accepted"), row_job("op-elsewhere", "accepted")]
    bindings = [row_binding(job["id"]) for job in jobs if job["id"] not in {"op-free", "op-elsewhere"}]
    bindings.append(row_binding("op-elsewhere", PROJECT, OTHER_CRITERION))
    links = [row_link("op-a", "op-gone"), row_link("op-b", "op-running"), row_link("op-c", "op-free"),
             row_link("op-d", "op-elsewhere")]
    view = api.status_projection(definitions(api), jobs, bindings, [], [], links)
    shown = entries(view)
    return {"links": {job: shown[job]["follow_up"] for job in ("op-a", "op-b", "op-c", "op-d")},
            "activity": view_project(view)["activity"], "jobs_total": view_project(view)["counts"]["jobs_total"],
            "unbound_jobs": view["unbound_jobs"]}


def _full_population(api):
    jobs = [row_job("op-%03d" % n, "accepted", "2026-09-20T00:%02d:00+00:00" % n) for n in range(51)]
    jobs += [row_job("op-fail", "failed", "2026-09-20T02:00:00+00:00", "child_refused"),
             row_job("op-old", "failed", "2026-09-20T02:01:00+00:00", "child_refused"),
             row_job("op-run", "dispatching", "2026-09-20T02:02:00+00:00"), row_job("op-wait", "queued", "2026-09-20T02:03:00+00:00"),
             row_job("op-huh", "receipt_pending", "2026-09-20T02:04:00+00:00")]
    bindings = [row_binding(job["id"]) for job in jobs]
    full = api.status_projection(definitions(api), jobs, bindings, [], [], [row_link("op-old", "op-000")])
    project = view_project(full)
    lone = api.status_projection(definitions(api), [row_job("op-huh", "receipt_pending")], [row_binding("op-huh")], [], [])

    def mode(statuses, links=()):
        rows = [row_job("op-%d" % n, status) for n, status in enumerate(statuses)]
        view = api.status_projection(definitions(api), rows, [row_binding(r["id"]) for r in rows], [], [], links)
        return view_project(view)["activity"]["mode"]
    return {"jobs_total": project["counts"]["jobs_total"], "truncated": project["jobs_truncated"], "sample": len(project["jobs"]),
            "activity": project["activity"],
            "activity_sums_to_the_population": sum(v for k, v in project["activity"].items() if k != "mode"),
            "unknown_status_alone": view_project(lone)["activity"],
            "modes": {"empty": mode([]), "running_and_failed": mode(["dispatching", "failed"]),
                      "queued_and_rejected": mode(["queued", "rejected"]), "exhausted_and_accepted": mode(["exhausted", "accepted"]),
                      "accepted": mode(["accepted"]),
                      "linked_failure_and_accepted": mode(["failed", "accepted"], [row_link("op-0", "op-1")]),
                      "unknown_and_accepted": mode(["unknown", "accepted"])}}


def _previous_shape(api):
    jobs = [row_job("op-fail", "failed", reason="child_refused"), row_job("op-next", "accepted")]
    bindings = [row_binding(job["id"]) for job in jobs]
    legacy = api.status_projection(definitions(api), jobs, bindings, [], [])
    with_links = api.status_projection(definitions(api), jobs, bindings, [], [], [row_link("op-fail", "op-next")])
    stripped = {k: v for k, v in view_project(with_links).items() if k != "activity"}
    stripped["jobs"] = [{k: v for k, v in job.items() if k != "follow_up"} for job in stripped["jobs"]]
    return {"legacy_jobs_have_no_follow_up_key": all("follow_up" not in j for j in view_project(legacy)["jobs"]),
            "legacy_activity": view_project(legacy)["activity"], "with_links_historical": view_project(with_links)["activity"]["historical_failed"],
            "stripped_equals_legacy": stripped == {k: v for k, v in view_project(legacy).items() if k != "activity"}}


# ---- G4 --------------------------------------------------------------------------------------------------------------------
def g4_status_activity(api, ws):
    results = {}
    results["vocabulary"] = {
        "STATUS_SCHEMA": api.STATUS_SCHEMA, "ACTIVITY_COUNTS": list(api.ACTIVITY_COUNTS), "ACTIVITY_MODES": sorted(api.ACTIVITY_MODES),
        "UNCLASSIFIED": api.UNCLASSIFIED, "SAMPLE": api.SAMPLE, "FOLLOWUP_FAILURES": sorted(api.FOLLOWUP_FAILURES),
        "FAILURE_STATUSES": sorted(api.FAILURE_STATUSES),
        "fleet_statuses_read": {k: getattr(api.JOB_STATUS, k) for k in ("ACCEPTED", "DISPATCHING", "EXHAUSTED", "FAILED", "QUEUED",
                                                                       "REJECTED")},
        "follow_up": [api.FOLLOWUP_LINKED, api.FOLLOWUP_UNKNOWN]}
    # -- activity_mode / project_activity / job_entry / follow_up_view, direct --
    zero = dict.fromkeys(api.ACTIVITY_COUNTS, 0)
    results["activity_mode_table"] = {
        "zero_total": api.activity_mode(0, zero), "zero_total_beats_counts": api.activity_mode(0, {**zero, "unknown": 5}),
        "idle": api.activity_mode(3, {**zero, "accepted": 3}), "idle_with_only_historical": api.activity_mode(2, {**zero, "historical_failed": 2}),
        "unknown_beats_running": api.activity_mode(3, {**zero, "unknown": 1, "running": 1, "queued": 1, "unresolved_failed": 1}),
        "running_beats_queued": api.activity_mode(2, {**zero, "running": 1, "queued": 1, "unresolved_failed": 1}),
        "queued_beats_attention": api.activity_mode(2, {**zero, "queued": 1, "unresolved_failed": 1}),
        "needs_attention": api.activity_mode(1, {**zero, "unresolved_failed": 1}),
        "missing_keys_raise": R.call(ws, api.activity_mode, 1, {})}
    activity = {}
    for name, statuses in {
            "empty": [], "dispatching": ["dispatching"], "queued": ["queued"], "accepted": ["accepted"], "failed": ["failed"],
            "rejected": ["rejected"], "exhausted": ["exhausted"], "unknown": ["unknown"], "unknown_vocabulary": ["receipt_pending"],
            "missing_status": [None], "all_kinds": ["dispatching", "queued", "accepted", "failed", "rejected", "exhausted", "unknown",
                                                    "weird", None]}.items():
        activity[name] = api.project_activity([{"status": st} for st in statuses])
    link = {"state": api.FOLLOWUP_LINKED}
    activity["failed_with_linked_follow_up"] = api.project_activity([{"status": "failed", "follow_up": link}])
    activity["failed_with_unknown_follow_up"] = api.project_activity([{"status": "failed", "follow_up": {"state": "unknown"}}])
    activity["exhausted_with_linked_follow_up"] = api.project_activity([{"status": "exhausted", "follow_up": link}])
    activity["rejected_with_linked_follow_up"] = api.project_activity([{"status": "rejected", "follow_up": link}])
    activity["accepted_with_a_link_is_still_accepted"] = api.project_activity([{"status": "accepted", "follow_up": link}])
    activity["a_link_without_state_raises"] = R.call(ws, api.project_activity, [{"status": "failed", "follow_up": {}}])
    activity["a_link_none_counts_unresolved"] = api.project_activity([{"status": "failed", "follow_up": None}])
    results["project_activity"] = activity
    entry = {}
    job = {"id": "j", "lane": "a", "status": "failed", "reason_code": "child_refused", "updated_at": T0}
    entry["plain"] = api.job_entry(job, "c1")
    entry["with_follow_up"] = api.job_entry(job, "c1", {"state": "linked"})
    entry["follow_up_empty_dict_is_added"] = api.job_entry(job, "c1", {})
    entry["no_reason"] = api.job_entry({**job, "reason_code": None}, "c1")
    entry["missing_optional_fields"] = api.job_entry({"id": "j"}, "c1")
    entry["unsafe_reason_becomes_a_safe_code"] = api.job_entry({**job, "reason_code": "raw: " + CANARY + " /home/x"}, "c1")
    entry["unsafe_reason_leaks"] = CANARY in json.dumps(entry["unsafe_reason_becomes_a_safe_code"])
    entry["empty_reason"] = api.job_entry({**job, "reason_code": ""}, "c1")
    entry["missing_id_raises"] = R.call(ws, api.job_entry, {"status": "failed"}, "c1")
    entry["extra_fields_are_not_projected"] = api.job_entry({**job, "manifest": {"objective": CANARY}, "error_type": "E"}, "c1")
    results["job_entry"] = entry
    views = {}
    rows = {"ok": row_job("ok", "accepted"), "queued": row_job("queued", "queued"), "failed": row_job("failed", "failed"),
            "other": row_job("other", "accepted")}
    targets = {"failed": (PROJECT, CRITERION), "ok": (PROJECT, CRITERION), "queued": (PROJECT, CRITERION), "other": (PROJECT, OTHER_CRITERION)}
    base = {"failed_job_id": "failed", "successor_job_id": "ok", "evidence_refs": REFS, "created_at": LINKED_AT}
    views["linked"] = api.follow_up_view(base, rows, targets)
    views["successor_missing"] = api.follow_up_view({**base, "successor_job_id": "gone"}, rows, targets)
    views["successor_not_accepted"] = api.follow_up_view({**base, "successor_job_id": "queued"}, rows, targets)
    views["binding_missing_failed"] = api.follow_up_view(base, rows, {k: v for k, v in targets.items() if k != "failed"})
    views["binding_missing_successor"] = api.follow_up_view(base, rows, {k: v for k, v in targets.items() if k != "ok"})
    views["target_mismatch"] = api.follow_up_view({**base, "successor_job_id": "other"}, rows, targets)
    views["successor_status_is_reported_even_when_not_accepted"] = api.follow_up_view({**base, "successor_job_id": "queued"}, rows,
                                                                                    targets)["successor_status"]
    views["missing_evidence_refs_key_reads_empty"] = api.follow_up_view({k: v for k, v in base.items() if k != "evidence_refs"}, rows, targets)
    views["missing_created_at_reads_none"] = api.follow_up_view({k: v for k, v in base.items() if k != "created_at"}, rows, targets)
    views["successor_id_none_is_missing"] = api.follow_up_view({**base, "successor_job_id": None}, rows, targets)
    views["evidence_is_copied"] = {"copied": api.follow_up_view(base, rows, targets)["evidence_refs"] is not base["evidence_refs"]}
    views["successor_without_a_status_is_not_accepted"] = api.follow_up_view(
        {**base, "successor_job_id": "nostatus"}, {**rows, "nostatus": {"id": "nostatus"}}, targets)
    results["follow_up_view"] = views
    # -- status_projection --
    d = definitions(api)
    shape = api.status_projection(d, [], [], [], [])
    results["status_projection_empty_shape"] = {
        "keys": sorted(shape), "schema": shape["schema"], "definition_sha256_is_digest": shape["definition_sha256"] == api.digest(d),
        "project_keys": sorted(shape["projects"][0]), "counts_keys": sorted(shape["projects"][0]["counts"]),
        "activity_keys": sorted(shape["projects"][0]["activity"]),
        "empty_follow_ups_equal_default": api.status_projection(d, [], [], [], [], ()) == shape}
    # M7 test_projection_samples_jobs_and_candidates_while_counting_every_row
    s = system(api, ws, value=T0)
    ids = []
    for n in range(55):
        job_id = "op-%03d" % n
        ids.append(job_id)
        put_job(s, job_id, "queued", updated="2026-09-20T00:%02d:00+00:00" % n if n < 60 else T0)
        s.book.bind(job_id, PROJECT, CRITERION)
    project = view_project(s.book.status())
    rows_by_id = job_rows(s.store, api)
    latest = sorted(ids, key=lambda i: (rows_by_id[i]["updated_at"], i))[-50:]
    results["m7_projection_samples_jobs_while_counting_every_row"] = {
        "jobs_total": project["counts"]["jobs_total"], "truncated": project["jobs_truncated"], "sample": len(project["jobs"]),
        "sample_is_the_latest_fifty": [j["id"] for j in project["jobs"]] == latest, "first": project["jobs"][0]["id"],
        "activity": project["activity"]}
    synthetic = [{"id": "%064d" % n, "family_status": "failed", "reason_code": "code_%d" % n, "state": "research_required", "count": 9,
                  "job_ids": ["j-%d" % i for i in range(60)], "evidence_refs": [], "updated_at": "2026-09-20T00:%02d:00+00:00" % n}
                 for n in range(51)]
    view = api.status_projection(d, [], [], [], synthetic)
    results["m7_projection_samples_candidates_while_counting_every_row"] = {
        "truncated": view["investigations_truncated"], "listed": len(view["investigations"]),
        "last_is_the_newest": view["investigations"][-1]["id"] == synthetic[-1]["id"], "first_is_not_the_oldest": view["investigations"][0]["id"] != synthetic[0]["id"],
        "job_ids_sample": len(view["investigations"][0]["job_ids"]), "count": view["investigations"][0]["count"],
        "job_ids_are_the_last_fifty_sorted": view["investigations"][0]["job_ids"] == sorted(synthetic[0]["job_ids"])[-50:]}
    # kinds: failure_family (explicit and legacy), audit_progress (its own list), any other kind (neither)
    progress = [{"id": "p-%02d" % n, "kind": api.PROGRESS_KIND, "audit_id": "a-1", "epoch": n, "reason_code": "low_yield",
                 "state": "research_required", "windows": ["w1", "w2"], "count": 2, "evidence_refs": ["e"], "observations": [1, 2, 3],
                 "updated_at": "2026-09-20T00:%02d:00+00:00" % n, "job_ids": ["must-not-appear"], "secret": CANARY} for n in range(51)]
    family = {"id": "f-explicit", "kind": api.FAILURE_KIND, "family_status": "failed", "reason_code": "child_refused", "state": "researched",
              "count": 2, "job_ids": ["b", "a"], "evidence_refs": REFS, "updated_at": T0, "extra": CANARY}
    legacy = {"id": "f-legacy", "family_status": "rejected", "reason_code": "lead_rejected", "state": "research_required", "count": 3,
              "job_ids": ["c", "a", "b"], "evidence_refs": [], "updated_at": None}
    other = {"id": "x-other", "kind": "something_else", "family_status": "failed", "reason_code": "x", "state": "research_required",
             "count": 1, "job_ids": [], "evidence_refs": [], "updated_at": T0}
    mixed = api.status_projection(d, [], [], [], progress + [family, legacy, other])
    results["investigation_kinds_are_projected_apart"] = {
        "families": mixed["investigations"], "families_truncated": mixed["investigations_truncated"],
        "progress_listed": len(mixed["progress_investigations"]), "progress_truncated": mixed["progress_investigations_truncated"],
        "progress_first": mixed["progress_investigations"][0], "progress_first_id": mixed["progress_investigations"][0]["id"],
        "progress_last_id": mixed["progress_investigations"][-1]["id"],
        "progress_job_ids_or_secret_leak": "must-not-appear" in json.dumps(mixed) or CANARY in json.dumps(mixed),
        "other_kind_is_in_neither": "x-other" not in json.dumps(mixed)}
    sparse = api.status_projection(d, [], [], [], [{"id": "p-sparse", "kind": api.PROGRESS_KIND}])
    results["progress_row_with_only_its_kind_reads_none_and_empty"] = sparse["progress_investigations"]
    results["family_row_missing_a_field_raises"] = R.call(ws, api.status_projection, d, [], [], [], [{"id": "f", "state": "x"}])
    # bindings and unbound jobs
    jobs = [row_job("j-bound", "accepted"), row_job("j-orphan", "accepted"), row_job("j-undefined-project", "accepted"),
            row_job("j-undefined-criterion", "accepted"), row_job("j-other", "queued", updated="2026-09-20T01:00:00+00:00")]
    bindings = [row_binding("j-bound"), row_binding("j-undefined-project", "retired", "c"), row_binding("j-undefined-criterion", PROJECT, "retired"),
                row_binding("j-gone-job"), row_binding("j-other", *OTHER_PROJECT), {"job_id": None, "project_id": PROJECT, "criterion_id": CRITERION}]
    bound = api.status_projection(d, jobs, bindings, [], [])
    results["bindings_to_a_missing_job_or_an_undefined_goal_stay_unbound"] = {
        "shown": {p["id"]: [j["id"] for j in p["jobs"]] for p in bound["projects"]}, "unbound_jobs": bound["unbound_jobs"],
        "totals": {p["id"]: p["counts"]["jobs_total"] for p in bound["projects"]}}
    odd = [row_job("good", "accepted"), {"status": "accepted"}, {"id": None, "status": "accepted"}, {"id": 5, "status": "accepted"},
           {"id": "", "status": "failed", "reason_code": None}]
    oddview = api.status_projection(d, odd, [row_binding("good")], [], [])
    results["jobs_without_a_string_id_are_never_counted"] = {"unbound_jobs": oddview["unbound_jobs"], "shown": [j["id"] for j in view_project(oddview)["jobs"]],
                                                              "unclassified_failures": oddview["unclassified_failures"]}
    # acceptances
    accepted = [{"project_id": PROJECT, "criterion_id": CRITERION, "evidence_refs": REFS},
                {"project_id": "retired", "criterion_id": "c", "evidence_refs": ["gone"]}]
    withacc = api.status_projection(d, [], [], accepted, [])
    results["acceptances_read_only_defined_goals_and_copy_their_refs"] = {
        "criteria": view_project(withacc)["criteria"], "counts": view_project(withacc)["counts"],
        "copy": view_project(withacc)["criteria"][0]["evidence_refs"] is not accepted[0]["evidence_refs"],
        "retired_leaks": "gone" in json.dumps(withacc)}
    results["an_acceptance_row_without_refs_raises"] = R.call(ws, api.status_projection, d, [], [], [
        {"project_id": PROJECT, "criterion_id": CRITERION}], [])
    # follow_ups argument forms
    f_jobs = [row_job("f", "failed", reason="child_refused"), row_job("s", "accepted")]
    f_bind = [row_binding("f"), row_binding("s")]
    forms = {}
    for name, fups in {"none_default": (), "tuple": (row_link("f", "s"),), "list": [row_link("f", "s")], "non_dict_entries_ignored": [None, 3, "x", row_link("f", "s")],
                       "non_string_failed_id_ignored": [{"failed_job_id": 3, "successor_job_id": "s"}], "missing_failed_id_ignored": [{"successor_job_id": "s"}],
                       "later_link_for_the_same_failure_wins": [row_link("f", "gone"), row_link("f", "s")],
                       "link_for_a_job_that_is_not_bound": [row_link("s", "f")]}.items():
        v = api.status_projection(d, f_jobs, f_bind, [], [], fups)
        forms[name] = {"activity": view_project(v)["activity"], "f_link": entries(v)["f"].get("follow_up")}
    results["follow_ups_argument_forms"] = forms
    # the successor bound AFTER the failure still reads linked (two passes), and the order of the binding list never matters
    swapped = api.status_projection(d, f_jobs, f_bind[::-1], [], [], [row_link("f", "s")])
    results["a_successor_bound_later_still_links"] = {"state": entries(swapped)["f"]["follow_up"]["state"]}
    # an entry sample ordered by (updated_at or "", id) with None updated_at
    nones = [row_job("b", "queued", updated=None), row_job("a", "queued", updated=None), row_job("c", "queued", updated=T0)]
    nv = api.status_projection(d, nones, [row_binding(i["id"]) for i in nones], [], [])
    results["sample_order_treats_a_missing_time_as_oldest"] = [j["id"] for j in view_project(nv)["jobs"]]
    # the projected jobs carry only the wire shape
    wire = api.status_projection(d, [{"id": "w", "status": "failed", "lane": "lane-x", "reason_code": "child_refused", "updated_at": T0,
                                      "manifest": {"objective": CANARY}, "error_type": "E", "path": "/home/owner"}],
                                 [row_binding("w")], [], [])
    results["projected_job_carries_only_the_wire_shape"] = {"jobs": view_project(wire)["jobs"],
                                                             "leak": CANARY in json.dumps(wire) or "/home/owner" in json.dumps(wire)}
    # unclassified failures through the projection
    uncl = api.status_projection(d, [row_job("u1", "failed", reason="unknown"), row_job("u2", "rejected", reason=None),
                                     row_job("u3", "exhausted", reason="unknown"), row_job("u4", "failed", reason="child_refused")], [], [], [])
    results["unclassified_failures_count_failed_and_rejected_only"] = {"unclassified_failures": uncl["unclassified_failures"]}
    # the three statuses of the activity summary through the real owner calls
    s2 = system(api, ws)
    for job_id, status, reason in (("a", "dispatching", None), ("b", "queued", None), ("c", "unknown", "receipt_missing"), ("d", "accepted", "lead_accepted"),
                                   ("e", "failed", "child_refused"), ("f", "rejected", "lead_rejected"), ("g", "exhausted", "budget_exhausted")):
        bound_job(s2, job_id, status, reason)
    results["m7_activity_over_bound_jobs_of_every_status"] = view_project(s2.book.status())["activity"]
    # the rejected job counts toward unresolved_failed, as the M7 status test shows
    s3 = system(api, ws)
    bound_job(s3, "r", "rejected", "lead_rejected")
    results["rejected_counts_toward_unresolved_failed"] = view_project(s3.book.status())["activity"]
    bound_job(s3, "x", "exhausted", "budget_exhausted")
    results["exhausted_counts_toward_unresolved_failed"] = view_project(s3.book.status())["activity"]
    # the status reads each bucket; it never writes
    before = R.store_digest(s3.store)
    s3.book.status()
    results["status_is_read_only"] = {"nothing_written": before == R.store_digest(s3.store)}
    # the status of a store that fails propagates (the collector reports unavailable)

    class Broken:
        def transaction(self):
            raise RuntimeError("injected outage (LABELLED fixture)")
    broken = api.Portfolio(Broken(), api.packaged_definitions())
    results["m7_store_failure_propagates_from_status"] = R.call(ws, broken.status)
    results["m7_monitor_envelope_is_additive_read_only_and_unavailable_on_store_failure"] = {
        "unreachable": "monitoring.collect/read_only (the monitoring adapter, another family) builds the envelope; the portfolio side "
                       "is status_is_read_only and m7_store_failure_propagates_from_status"}
    return results


# ---- G5 --------------------------------------------------------------------------------------------------------------------
def g5_reconcile_adapter(api, ws):
    results = {}
    e = system(api, ws, value=T0)
    results["reconcile_empty_store"] = obs(e, api.reconcile, e.store, e.clock)
    s = system(api, ws, value=T0)
    for job_id, status, reason, lane in (
            ("a1", "failed", "child_refused", "a"), ("a2", "failed", "child_refused", "b"), ("a3", "failed", "child_refused", "a"),
            ("r1", "rejected", "lead_rejected", "a"), ("r2", "rejected", "lead_rejected", "b"), ("solo", "failed", "only_once", "a"),
            ("same-reason-other-status", "rejected", "child_refused", "a"),
            ("u1", "failed", "unknown", "a"), ("u2", "failed", None, "a"), ("u3", "failed", "", "a"), ("u4", "failed", "raw: " + CANARY, "a"),
            ("x1", "exhausted", "budget_exhausted", "a"), ("x2", "exhausted", "budget_exhausted", "a"), ("q", "queued", "child_refused", "a"),
            ("k", "unknown", "receipt_missing", "a"), ("ok", "accepted", "lead_accepted", "a")):
        put_job(s, job_id, status, reason, lane)
    put(s.store, api.BUCKET_JOBS, "no-id-field", {"status": "failed", "reason_code": "child_refused"})   # LABELLED malformed row
    first = obs(s, api.reconcile, s.store, s.clock)
    results["reconcile_first"] = first
    results["reconcile_rows"] = sorted(({k: v for k, v in r.items()} for r in scan(s.store, api.BUCKET_INVESTIGATIONS)), key=lambda r: r["id"])
    results["reconcile_replay_writes_nothing"] = obs(s, api.reconcile, s.store, s.clock)
    results["reconcile_below_the_minimum_is_not_a_candidate"] = {
        "solo_family": api.family_id("failed", "only_once"), "has_row": get(s.store, api.BUCKET_INVESTIGATIONS, api.family_id("failed", "only_once")) is not None,
        "same_reason_other_status_family": get(s.store, api.BUCKET_INVESTIGATIONS, api.family_id("rejected", "child_refused")) is not None,
        "exhausted_family": get(s.store, api.BUCKET_INVESTIGATIONS, api.family_id("exhausted", "budget_exhausted")) is not None}
    put_job(s, "a4", "failed", "child_refused", updated="2026-09-20T09:00:00+00:00")
    put_job(s, "r3", "rejected", "lead_rejected")
    s.clock.value = "2026-09-21T00:00:00+00:00"
    key = api.family_id("failed", "child_refused")
    decided = get(s.store, api.BUCKET_INVESTIGATIONS, key)
    decided.update(state=api.DEFERRED, evidence_refs=REFS, decided_at="2026-09-20T12:00:00+00:00")
    put(s.store, api.BUCKET_INVESTIGATIONS, key, decided)       # LABELLED: the owner's disposition (also reached through disposition())
    results["reconcile_new_members_extend_and_keep_the_disposition"] = {
        "summary": api.reconcile(s.store, s.clock), "decided_row": get(s.store, api.BUCKET_INVESTIGATIONS, key),
        "other_family_row": get(s.store, api.BUCKET_INVESTIGATIONS, api.family_id("rejected", "lead_rejected"))}
    # a stored membership that is a superset keeps its extra ids (a union, never a replacement)
    sup = get(s.store, api.BUCKET_INVESTIGATIONS, key)
    sup.update(job_ids=sup["job_ids"] + ["z-gone"], count=99)
    put(s.store, api.BUCKET_INVESTIGATIONS, key, sup)
    before = R.store_digest(s.store)
    results["reconcile_a_stored_superset_is_never_shrunk"] = {
        "summary": api.reconcile(s.store, s.clock), "nothing_written": before == R.store_digest(s.store),
        "row": get(s.store, api.BUCKET_INVESTIGATIONS, key)}
    # an out-of-order stored membership list is sorted by the merge (a write), an identical sorted one is not
    unsorted = get(s.store, api.BUCKET_INVESTIGATIONS, api.family_id("rejected", "lead_rejected"))
    unsorted.update(job_ids=["r3", "r2", "r1"])
    put(s.store, api.BUCKET_INVESTIGATIONS, api.family_id("rejected", "lead_rejected"), unsorted)
    results["reconcile_an_unsorted_stored_membership_is_rewritten_sorted"] = {
        "summary": api.reconcile(s.store, s.clock), "row_ids": get(s.store, api.BUCKET_INVESTIGATIONS, api.family_id("rejected", "lead_rejected"))["job_ids"]}
    # a legacy stored row without job_ids reads as empty
    lg = system(api, ws, value=T0)
    put_job(lg, "l1", "failed", "child_refused")
    put_job(lg, "l2", "failed", "child_refused")
    put(lg.store, api.BUCKET_INVESTIGATIONS, api.family_id("failed", "child_refused"),
        {"id": api.family_id("failed", "child_refused"), "state": api.RESEARCH_REQUIRED})      # LABELLED legacy row
    results["reconcile_a_stored_row_without_job_ids_reads_empty"] = {
        "summary": api.reconcile(lg.store, lg.clock), "row": get(lg.store, api.BUCKET_INVESTIGATIONS, api.family_id("failed", "child_refused"))}
    # candidates are listed in sorted family order; the default clock is the harness's fake clock
    d = system(api, ws)
    for n in range(2):
        for status, reason in (("failed", "zzz"), ("failed", "aaa"), ("rejected", "mmm")):
            put_job(d, "%s-%s-%d" % (status, reason, n), status, reason)
    summary = api.reconcile(d.store)
    results["reconcile_default_clock_and_candidate_order"] = {
        "summary": summary, "order_is_the_sorted_family_key": summary["candidates"] == [api.family_id(st, rs) for st, rs in sorted(
            [("failed", "zzz"), ("failed", "aaa"), ("rejected", "mmm")])], "created_at_is_the_clock_read": [
                r["created_at"] for r in scan(d.store, api.BUCKET_INVESTIGATIONS)][0] == summary["at"]}
    jobs_digest = R.canonical_digest(scan(d.store, api.BUCKET_JOBS))
    api.reconcile(d.store, d.clock)
    results["reconcile_touches_only_the_investigations_bucket"] = {
        "buckets_after": sorted({r["bucket"] for r in _records(d.store)}),
        "jobs_unchanged": R.canonical_digest(scan(d.store, api.BUCKET_JOBS)) == jobs_digest}
    p = system(api, ws, value=T0)
    for n in range(2):
        put_job(p, "p%d" % n, "failed", "child_refused")
    results["portfolio_reconcile_is_the_module_function"] = {
        "summary": p.book.reconcile(), "needs_no_definitions": api.reconcile(api.MemoryStore())["scanned"]}
    # a store failure inside reconcile propagates (no swallowing; the runner's `reconciliation` state is the fleet family's)

    class Broken:
        def transaction(self):
            raise RuntimeError("injected outage (LABELLED fixture)")
    results["reconcile_store_failure_propagates"] = R.call(ws, api.reconcile, Broken(), lambda: T0)
    # -- adapters/portfolio.py --
    a = {}
    a["DEFINITIONS"] = api.DEFINITIONS
    a["packaged_definitions_default_is_the_resource"] = api.packaged_definitions() == api.packaged_definitions(api.DEFINITIONS)
    a["packaged_definitions_returns_a_fresh_document"] = api.packaged_definitions() is not api.packaged_definitions()
    a["packaged_definitions_unknown_resource"] = R.call(ws, api.packaged_definitions, "no-such-resource.json")
    a["packaged_definitions_is_unvalidated"] = {"keys": sorted(api.packaged_definitions()), "validated_equal": api.validate_definitions(
        api.packaged_definitions()) == api.packaged_definitions()}
    store = api.MemoryStore()
    book = api.portfolio(store)
    a["portfolio_default"] = {"class": type(book).__name__, "sha": book.definition_sha256, "store_is_the_given_store": book.store is store}
    custom = {"schema": api.DEFINITIONS_SCHEMA, "projects": [{"id": "only", "title": "t", "outcome": "o", "source_ref": "docs/x.md",
                                                               "criteria": [{"id": "c", "text": "t"}]}]}
    b = api.portfolio(store, custom)
    a["portfolio_custom_definitions"] = {"projects": [p["id"] for p in b.definitions["projects"]]}
    a["portfolio_empty_definitions_is_not_the_default"] = R.call(ws, api.portfolio, store, {})
    a["portfolio_invalid_definitions_refuse"] = R.call(ws, api.portfolio, store, {"schema": "x", "projects": []})
    results["adapter"] = a
    # portfolio_reconciler: the bounded per-tick callable of FleetRunner(..., reconcile=...)
    r = system(api, ws, value=T0)
    for job_id, status, reason, lane in (("op-1", "failed", "child_refused", "a"), ("op-2", "failed", "child_refused", "b")):
        put_job(r, job_id, status, reason, lane)
    tick = api.portfolio_reconciler(r.store)
    results["reconciler_callable"] = {
        "is_callable_taking_no_arguments": callable(tick), "first": tick(), "second": tick(),
        "candidate": [{"count": c["count"], "job_ids": c["job_ids"], "state": c["state"], "reason_code": c["reason_code"]}
                      for c in api.portfolio(r.store).status()["investigations"]]}
    q = api.MemoryStore()
    results["reconciler_needs_no_definitions_or_resource"] = api.portfolio_reconciler(q)()
    results["m7_runner_reconciles_once_per_tick_and_its_failure_never_blocks_admission"] = {
        "unreachable": "FleetRunner is the fleet family; the portfolio side is reconciler_callable (counted summary, never a cause) and "
                       "reconcile_store_failure_propagates (the runner is what turns it into `unavailable`)"}
    results["m7_actual_fleet_cli_run_reconciles_through_the_real_runner"] = {
        "unreachable": "fleet_cli.execute and the real runner are the fleet family; the portfolio side is reconciler_callable over rows "
                       "of two failures reading one candidate of count 2"}
    results["m7_reconciliation_transitions_are_logged_once"] = {
        "unreachable": "the runner's logger 'zeus.fleet.runner' is the fleet family; reconcile itself logs nothing (a call with a "
                       "raising store propagates, reconcile_store_failure_propagates)"}
    results["module_surface"] = {"__all__": sorted(api.ALL), "adapter_all": sorted(api.ADAPTER_ALL)}
    return results


GROUPS = (("g1_definitions", g1_definitions), ("g2_bindings_investigations", g2_bindings_investigations),
          ("g3_acceptances_followups", g3_acceptances_followups), ("g4_status_activity", g4_status_activity),
          ("g5_reconcile_adapter", g5_reconcile_adapter))


def run(api) -> dict:
    ws = R.Workspace()
    try:
        result, counts = {}, {}
        for name, group in GROUPS:
            result[name] = ws.scrub(group(api, ws))
            counts[name] = len(result[name])
        result["cases_per_group"] = counts
        return result
    finally:
        ws.close()
