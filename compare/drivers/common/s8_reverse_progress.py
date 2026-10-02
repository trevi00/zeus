"""Shared S8 scenario steps (`research.reverse_progress`): M7 `application/reverse_progress.py` (`ReverseProgress`: `_source`, `status`,
`record`), characterized BEFORE the module moves (DESIGN-s8 §6 V11; the module has no entry in `branch-table-research.txt`, so every
`require`, `except` and branch of the AST is covered, see `BRANCH_COVERAGE`).

Every case mirrors a test of M7 `tests/test_reverse_progress.py` or of the reverse case of `tests/test_integration.py` (the test name is
the group label), plus LABELLED additions that reach the branches those tests do not:

- **p1_test_four_stages_across_usecase_instances_require_real_artifacts**: the four stages through fresh use-case instances over one
  store, the retained generation and releases, `status` unchanged, the empty complete stage and the missing artifact.
- **p2_test_retry_is_idempotent_but_conflicting_request_rejected**: the idempotent replay, the conflicting request, the one history row,
  the replay after later progress, the sorted-and-deduplicated references, another request on the same stage.
- **p3_test_unknown_dirty_and_moved_sources_do_not_inherit_completion**: `status` over every source observation, `record` over dirty,
  unknown, moved and malformed sources, the rebaseline and its history.
- **p4_test_stage_order_and_completed_stage_immutability**: the order of the stages, the immutable completed stage, partial then complete.
- **p5_predecessor_evidence**: the missing, modified and badly described predecessor artifacts (tests `test_missing_predecessor_evidence_
  blocks_continuation`, `test_modified_predecessor_blocks_continuation`, `test_bad_receipt_metadata_blocks_continuation`,
  `test_artifact_metadata_counts_utf8_bytes`).
- **p6_argument_requires**: every precondition of `record` in its order (project, stage and status, request, generation, rebaseline,
  source, references, retained artifacts).
- **p7_racing_writers_and_integration_replay**: the part the application decides of `test_racing_writers_cannot_lose_a_checkpoint` and of
  `test_postgres_reverse_progress_concurrency_replay_and_history` over MemoryStore (two sequential writers; a second use-case instance
  replays; the later stages, the rebaseline and the history generations). The threads and PostgreSQL are not scenario steps.

The two git cases (`test_tree_is_resolved_from_captured_commit`, `test_git_observation_detects_dirty_and_unknown_sources`) exercise
`adapters.reverse_source.observe_source` (a later layer), not this module; they are recorded in `M7_TESTS`.

Layer: harness (never shipped)

This module never imports `codex_harness`: everything from the product arrives through `api` (`MemoryStore`, `FileArtifacts`,
`ReverseProgress`, `STAGES`, `STATUSES`, `ContractError`, `digest`, `advance`). The artifacts are M7's OWN `FileArtifacts` over a run-scoped
directory (its target counterpart is `storage.adapters.file_artifacts.FileArtifacts`), as the M7 tests build them. For every call the digest of
each owned bucket and of the whole store before and after is recorded; the fake clock ticks once per call."""

from __future__ import annotations

import json
from types import SimpleNamespace

import s8_research_program as R

OWNED = ("reverse_requests", "reverse_progress", "reverse_history")
PROJECT = "p"
UNSET = object()


def sha(value):
    return R.canonical_digest(value)[:16]


# ---- the fixture -----------------------------------------------------------------------------------------------------------
def build(api, ws, name, store=None, artifacts=None):
    """M7 `progress` fixture: a `MemoryStore`, M7's own `FileArtifacts` over a run-scoped directory holding one retained document, and the
    use case over them."""
    store = api.MemoryStore() if store is None else store
    artifacts = api.FileArtifacts(str(ws.case(name) / "artifacts")) if artifacts is None else artifacts
    ref = artifacts.put("verified generated document", "fixture")["ref"]
    return SimpleNamespace(api=api, ws=ws, store=store, artifacts=artifacts, ref=ref, app=api.ReverseProgress(store, artifacts))


def fresh(env):
    """A new use-case instance over the same store and artifacts (M7 `ReverseProgress(app.store, app.artifacts)`)."""
    env.app = env.api.ReverseProgress(env.store, env.artifacts)
    return env.app


def source(commit="a", **over):
    """M7 `source()`: the clean observation of the source project."""
    return {"repository": "source-project", "commit": commit * 40, "tree": "b" * 40, "status": "clean", **over}


def snap(store) -> dict:
    with store.transaction() as tx:
        rows = tx.records()
    out = {}
    for bucket in OWNED:
        mine = sorted([r["id"], R.canonical_digest(r["body"])] for r in rows if r["bucket"] == bucket)
        out[bucket] = "%d:%s" % (len(mine), sha(mine))
    out["all"] = sha(sorted([r["bucket"], r["id"], R.canonical_digest(r["body"])] for r in rows))
    return out


def rows(store, bucket):
    with store.transaction() as tx:
        return tx.scan(bucket)


def get(store, bucket, key):
    with store.transaction() as tx:
        return tx.get(bucket, key)


def view(value):
    """The facts of a returned progress row (the row itself is recorded by digest)."""
    if isinstance(value, dict) and "releases" in value:
        return {"project": value["project"], "generation": value["generation"], "source": value["source"],
                "releases": {k: [v["status"], v["artifact_refs"] == [] and "no-refs" or len(v["artifact_refs"])] for k, v in sorted(value["releases"].items())}}
    return value


def outcome(api, fn, *, plain=False):
    """The characterized outcome of one call: its value (by digest, with a view), or the refusal (type, whether it is the contract error,
    its text and its cause; an OS error is reported by type only, its text names a path)."""
    try:
        value = fn()
    except Exception as exc:  # the refusal is the characterized result
        out = {"refused": type(exc).__name__, "is_contract_error": isinstance(exc, api.ContractError)}
        if not isinstance(exc, OSError):
            out["message"] = str(exc)[:240]
        if exc.__cause__ is not None:
            out["cause"] = type(exc.__cause__).__name__
        return out
    return {"value": R.canonical_digest(value), "view": value if plain else view(value)}


def step(env, fn, plain=False):
    """One call with the owned-bucket digests before and after (a refusal changes none of them) and one tick of the fake clock."""
    before = snap(env.store)
    out = outcome(env.api, fn, plain=plain)
    after = snap(env.store)
    env.api.advance(0.001)
    return {**out, "before": before, "after": after, "changed": [k for k in before if before[k] != after[k]]}


def rec(env, project=PROJECT, stage="1-A", status="complete", src=UNSET, refs=UNSET, gen=0, rid="r", **kw):
    """`record` with the M7 test defaults: one retained document, a clean source."""
    refs = [env.ref] if refs is UNSET else refs
    src = source() if src is UNSET else src
    return step(env, lambda: env.app.record(project, stage, status, src, refs, gen, rid, **kw))


def state(env, src, project=PROJECT):
    return step(env, lambda: env.app.status(project, src), plain=True)


def history(env):
    return sorted(r["generation"] for r in rows(env.store, "reverse_history"))


def metadata_path(env, ref, suffix):
    return env.artifacts.root / (ref[7:] + suffix)


# ---- p1 ----------------------------------------------------------------------------------------------------------------------
def p1_four_stages(api, ws):
    out = {}
    env = build(api, ws, "four")
    for generation, stage in enumerate(("1-A", "1-B", "1-C", "2")):
        fresh(env)
        out["record_" + stage] = rec(env, stage=stage, gen=generation, rid=stage)
    final = get(env.store, "reverse_progress", PROJECT)
    out["final"] = {"generation": final["generation"], "stages": sorted(final["releases"]), "source": final["source"]}
    out["status_unchanged"] = state(env, source())
    out["history_generations"] = history(env)
    out["requests"] = len(rows(env.store, "reverse_requests"))
    out["empty_complete_refused"] = rec(env, project="other", refs=[], rid="empty")
    out["missing_artifact_refused"] = rec(env, project="other", refs=["sha256:" + "f" * 64], rid="missing")
    out["invalid_reference_refused"] = rec(env, project="other", refs=["not-a-reference"], rid="invalid")
    out["status_other_project_unstarted"] = state(env, source(), project="other")
    return out


# ---- p2 ----------------------------------------------------------------------------------------------------------------------
def p2_retry(api, ws):
    out = {}
    env = build(api, ws, "retry")
    original = rec(env, rid="r")
    out["original"] = original
    out["replay_is_the_original"] = rec(env, rid="r")
    out["replay_returns_the_stored_result"] = original["value"] == out["replay_is_the_original"]["value"]
    out["conflict_status"] = rec(env, status="partial", rid="r")
    out["conflict_refs"] = rec(env, refs=[], status="partial", rid="r")
    out["conflict_generation"] = rec(env, gen=3, rid="r")
    out["conflict_stage"] = rec(env, stage="1-B", rid="r")
    out["conflict_source"] = rec(env, src=source("c"), rid="r")
    out["conflict_rebaseline"] = rec(env, rebaseline=True, rid="r")
    out["history_rows"] = history(env)
    # a replay is answered before any generation or order check, even after later progress
    out["next_stage"] = rec(env, stage="1-B", gen=1, rid="next")
    out["replay_after_later_progress"] = rec(env, rid="r")
    out["history_after_later_progress"] = history(env)
    # the references are sorted and de-duplicated before they enter the command: another order is the same request
    env2 = build(api, ws, "retry-order")
    second = env2.artifacts.put("second document", "fixture")["ref"]
    out["refs_unsorted_duplicated"] = rec(env2, stage="1-A", status="partial", refs=[second, env2.ref, second], rid="o")
    out["refs_sorted_is_the_same_request"] = rec(env2, stage="1-A", status="partial", refs=sorted({second, env2.ref}), rid="o")
    out["refs_sorted_stored"] = get(env2.store, "reverse_progress", PROJECT)["releases"]["1-A"]["artifact_refs"] == sorted({second, env2.ref})
    # the request key is the project and the request id: another request id is another command (stale), another project is new
    out["same_rid_other_project"] = rec(env, project="q", rid="r")
    out["other_rid_same_command_is_stale"] = rec(env, rid="other-rid")
    out["request_rows"] = len(rows(env.store, "reverse_requests"))
    return out


# ---- p3 ----------------------------------------------------------------------------------------------------------------------
def p3_sources(api, ws):
    out = {}
    env = build(api, ws, "sources")
    out["status_not_started"] = state(env, source())
    out["status_not_started_dirty"] = state(env, source(status="dirty"))
    out["first"] = rec(env, rid="first")
    for label, observation in (("unknown", {**source(), "status": "unknown"}), ("dirty", {**source(), "status": "dirty"}),
                               ("weird_status", {**source(), "status": "weird"}), ("status_missing", {k: v for k, v in source().items() if k != "status"}),
                               ("status_none", {**source(), "status": None}), ("not_a_dict_none", None), ("not_a_dict_list", [source()]), ("not_a_dict_str", "clean"),
                               ("clean_without_repository", {**source(), "repository": ""}), ("clean_repository_int", {**source(), "repository": 5}),
                               ("clean_commit_short", {**source(), "commit": "a" * 39}),
                               ("clean_commit_upper", {**source(), "commit": "A" * 40}), ("clean_commit_missing", {k: v for k, v in source().items() if k != "commit"}),
                               ("clean_tree_int", {**source(), "tree": 7}), ("clean_tree_trailing_newline", {**source(), "tree": "b" * 40 + "\n"}),
                               ("clean_mixed_hash_formats", {**source(), "commit": "a" * 64}),
                               ("clean_sha256_pair", {**source(), "commit": "a" * 64, "tree": "b" * 64}), ("clean_extra_keys_ignored", {**source(), "extra": 1})):
        out["status_" + label] = state(env, observation)
    out["status_unchanged"] = state(env, source())
    out["status_changed_commit"] = state(env, source("c"))
    out["status_changed_repository"] = state(env, source(repository="elsewhere"))
    out["status_other_project"] = state(env, source(), project="other")
    for label, state_name in (("unknown", "unknown"), ("dirty", "dirty")):
        out["record_" + label] = rec(env, stage="1-B", status="partial", src={**source(), "status": state_name}, refs=[], gen=1, rid=state_name)
    out["moved_without_rebaseline"] = rec(env, stage="1-B", status="partial", src=source("c"), refs=[], gen=1, rid="moved")
    out["moved_rebaseline_not_first_stage"] = rec(env, stage="1-B", status="partial", src=source("c"), refs=[], gen=1, rid="moved-b", rebaseline=True)
    out["rebaseline_without_change"] = rec(env, stage="1-A", status="partial", refs=[], gen=1, rid="same", rebaseline=True)
    out["rebaseline_restart"] = rec(env, stage="1-A", status="partial", src=source("c"), refs=[], gen=1, rid="restart", rebaseline=True)
    out["history_after_rebaseline"] = history(env)
    out["progress_after_rebaseline"] = view(get(env.store, "reverse_progress", PROJECT))
    out["status_after_rebaseline_old_source"] = state(env, source())
    out["status_after_rebaseline_new_source"] = state(env, source("c"))
    out["rebaseline_over_a_complete_first_stage"] = rec(env, stage="1-A", status="partial", src=source("d"), refs=[], gen=2, rid="again", rebaseline=True)
    return out


# ---- p4 ----------------------------------------------------------------------------------------------------------------------
def p4_order_and_immutability(api, ws):
    out = {}
    env = build(api, ws, "order")
    out["skip_ahead"] = rec(env, stage="1-B", gen=0, rid="skip")
    out["skip_to_last"] = rec(env, stage="2", gen=0, rid="skip2")
    out["first"] = rec(env, rid="first")
    out["downgrade_completed"] = rec(env, status="pending", refs=[], gen=1, rid="downgrade")
    out["rewrite_completed"] = rec(env, gen=1, rid="rewrite")
    out["partial_second_stage"] = rec(env, stage="1-B", status="partial", refs=[], gen=1, rid="b1")
    out["third_over_a_partial_predecessor"] = rec(env, stage="1-C", status="partial", refs=[], gen=2, rid="c1")
    out["partial_to_complete"] = rec(env, stage="1-B", status="complete", gen=2, rid="b2")
    out["pending_after_complete"] = rec(env, stage="1-B", status="pending", refs=[], gen=3, rid="b3")
    out["third"] = rec(env, stage="1-C", status="pending", refs=[], gen=3, rid="c2")
    out["third_pending_to_partial"] = rec(env, stage="1-C", status="partial", refs=[], gen=4, rid="c3")
    out["final_stage_over_partial"] = rec(env, stage="2", status="partial", refs=[], gen=5, rid="d1")
    out["progress"] = view(get(env.store, "reverse_progress", PROJECT))
    out["history"] = history(env)
    return out


# ---- p5 ----------------------------------------------------------------------------------------------------------------------
def p5_predecessor_evidence(api, ws):
    out = {}
    env = build(api, ws, "missing")
    rec(env, rid="first")
    metadata_path(env, env.ref, ".txt").unlink()
    out["missing_predecessor"] = rec(env, stage="1-B", status="partial", refs=[], gen=1, rid="lost")
    out["progress_survives"] = state(env, source())["view"]["progress"]["generation"]
    out["missing_first_stage_replay_of_the_same_request"] = rec(env, rid="first")
    env = build(api, ws, "tampered")
    rec(env, rid="first")
    metadata_path(env, env.ref, ".txt").write_text("tampered content")
    out["modified_predecessor"] = rec(env, stage="1-B", status="partial", refs=[], gen=1, rid="tampered")
    out["modified_own_reference"] = rec(env, project="o", stage="1-A", status="partial", gen=0, rid="own")
    for label, metadata in (("absent", None), ("list", []), ("wrong_ref", {"ref": "wrong", "bytes": 27}), ("negative_bytes", {"ref": "original", "bytes": -1}),
                            ("wrong_bytes", {"ref": "original", "bytes": 26}), ("bool_bytes", {"ref": "original", "bytes": True}),
                            ("not_json", "{")):
        env = build(api, ws, "metadata-" + label)
        rec(env, rid="first")
        path = metadata_path(env, env.ref, ".json")
        if metadata is None:
            path.unlink()
        elif metadata == "{":
            path.write_text(metadata)
        else:
            if isinstance(metadata, dict) and metadata["ref"] == "original":
                metadata = {**metadata, "ref": env.ref}
            path.write_text(json.dumps(metadata))
        out["metadata_" + label] = rec(env, stage="1-B", status="partial", refs=[], gen=1, rid="bad-metadata")
    env = build(api, ws, "utf8")
    ref = env.artifacts.put("한글", "fixture")["ref"]
    out["utf8_bytes_are_counted"] = env.artifacts.inspect(ref)["metadata"]["bytes"]
    out["utf8_artifact_is_accepted"] = rec(env, refs=[ref], rid="utf8")
    env = build(api, ws, "own-missing")
    out["own_reference_missing_checked_before_the_transaction"] = rec(env, stage="1-A", status="partial", refs=["sha256:" + "0" * 64], rid="x")
    out["partial_with_a_retained_artifact_is_checked"] = rec(env, stage="1-A", status="partial", refs=[env.ref], rid="y")
    return out


# ---- p6 ----------------------------------------------------------------------------------------------------------------------
def p6_argument_requires(api, ws):
    out = {}
    env = build(api, ws, "args")
    for label, value in (("empty", ""), ("none", None), ("int", 5), ("list", ["p"])):
        out["project_" + label] = rec(env, project=value, rid="a")
    for label, value in (("unknown", "3"), ("lower", "1-a"), ("empty", ""), ("none", None), ("list", ["1-A"])):
        out["stage_" + label] = rec(env, stage=value, rid="a")
    for label, value in (("unknown", "done"), ("upper", "COMPLETE"), ("empty", ""), ("none", None), ("true", True)):
        out["status_" + label] = rec(env, status=value, rid="a")
    for label, value in (("empty", ""), ("none", None), ("int", 5), ("bytes", b"r")):
        out["request_" + label] = rec(env, rid=value)
    for label, value in (("negative", -1), ("true", True), ("float", 0.0), ("str", "0"), ("none", None)):
        out["generation_" + label] = rec(env, gen=value, rid="a")
    for label, value in (("int", 1), ("none", None), ("str", "yes"), ("zero", 0)):
        out["rebaseline_" + label] = rec(env, rebaseline=value, rid="a")
    out["source_only_a_status"] = rec(env, src={"status": "clean"}, rid="a")
    out["source_not_a_dict"] = rec(env, src=[], rid="a")
    out["source_none_value"] = rec(env, src=None, rid="a")
    out["source_dirty"] = rec(env, src=source(status="dirty"), rid="a")
    out["source_unknown"] = rec(env, src=source(status="unknown"), rid="a")
    out["source_repository_empty"] = rec(env, src=source(repository=""), rid="a")
    out["source_repository_int"] = rec(env, src=source(repository=1), rid="a")
    out["source_repository_missing"] = rec(env, src={k: v for k, v in source().items() if k != "repository"}, rid="a")
    for name in ("commit", "tree"):
        for label, value in (("short", "a" * 39), ("long", "a" * 41), ("upper", "A" * 40), ("non_hex", "g" * 40), ("int", 1), ("none", None),
                             ("trailing_newline", "a" * 40 + "\n"), ("sha1_64_mix", "a" * 63)):
            out["source_%s_%s" % (name, label)] = rec(env, src={**source(), name: value}, rid="a")
        out["source_%s_missing" % name] = rec(env, src={k: v for k, v in source().items() if k != name}, rid="a")
    out["source_mixed_formats_commit_sha256"] = rec(env, src=source(commit="a" * 64), rid="a")
    out["source_mixed_formats_tree_sha256"] = rec(env, src=source(tree="b" * 64), rid="a")
    out["source_both_sha256_is_pinned"] = rec(env, project="sha256", src=source(commit="a" * 64, tree="b" * 64), rid="a")
    out["source_extra_keys_are_not_pinned"] = rec(env, project="extra", src={**source(), "extra": "ignored", "dirty_files": 3}, rid="a")
    out["pinned_source_of_the_extra_keys"] = get(env.store, "reverse_progress", "extra")["source"]
    for label, value in (("none", None), ("str", "x"), ("tuple", (env.ref,)), ("dict", {env.ref: 1}), ("int_item", [5]), ("none_item", [None]),
                         ("mixed", [env.ref, 5]), ("bytes_item", [b"x"])):
        out["refs_" + label] = rec(env, refs=value, rid="a")
    out["complete_without_refs"] = rec(env, refs=[], rid="a")
    out["partial_without_refs"] = rec(env, status="partial", refs=[], rid="a2")
    out["pending_without_refs"] = rec(env, project="pend", stage="1-A", status="pending", refs=[], rid="a")
    out["stale_generation_ahead"] = rec(env, project="stale", gen=1, rid="a")
    out["stale_generation_behind"] = rec(env, gen=0, rid="late")
    out["order_project_before_stage"] = rec(env, project="", stage="9", rid="")
    out["order_stage_before_request"] = rec(env, stage="9", rid="")
    out["order_request_before_generation"] = rec(env, rid="", gen=-1)
    out["order_generation_before_rebaseline"] = rec(env, gen=-1, rebaseline=1, rid="a")
    out["order_rebaseline_before_source"] = rec(env, rebaseline=1, src={"status": "dirty"}, rid="a")
    out["order_source_before_references"] = rec(env, src=source(status="dirty"), refs=None, rid="a")
    out["order_references_before_completeness"] = rec(env, refs=[5], rid="a")
    out["order_completeness_before_artifact_inspection"] = rec(env, refs=[], rid="a")
    out["order_inspection_before_the_transaction"] = rec(env, refs=["sha256:" + "9" * 64], gen=7, rid="a")
    out["stale_generation_after_the_conflict_check"] = rec(env, gen=7, rid="a")
    return out


# ---- p7 ----------------------------------------------------------------------------------------------------------------------
def p7_racing_and_integration(api, ws):
    out = {}
    env = build(api, ws, "racing")
    out["writer_a"] = rec(env, stage="1-A", status="partial", refs=[], gen=0, rid="a")
    out["writer_b_stale"] = rec(env, stage="1-A", status="partial", refs=[], gen=0, rid="b")
    out["one_checkpoint"] = state(env, source())["view"]["progress"]["generation"]
    out["one_history_row"] = history(env)
    env = build(api, ws, "integration")
    shared = env.store
    first = rec(env, rid="first")
    second = rec(env, rid="second")
    out["first"], out["second_stale"] = first, second
    reconnected = api.ReverseProgress(shared, env.artifacts)
    env.app = reconnected
    out["reconnected_replay"] = rec(env, rid="first")
    out["reconnected_replay_returns_the_first"] = out["reconnected_replay"]["value"] == first["value"]
    out["next"] = rec(env, stage="1-B", gen=1, rid="next")
    out["rebaseline"] = rec(env, stage="1-A", status="partial", src=source("c"), refs=[], gen=2, rid="rebaseline", rebaseline=True)
    saved = get(env.store, "reverse_progress", PROJECT)
    out["history_generations"] = history(env)
    out["progress_source_commit"] = saved["source"]["commit"]
    generations = {r["generation"]: r for r in rows(env.store, "reverse_history")}
    out["generation_2_release_1B"] = generations[2]["releases"]["1-B"]["status"]
    out["generation_3_releases"] = sorted(generations[3]["releases"])
    out["history_rows_are_the_results"] = [R.canonical_digest(generations[g]) for g in sorted(generations)] == [
        R.canonical_digest(get(env.store, "reverse_history", env.api.digest({"project": PROJECT, "generation": g}))) for g in sorted(generations)]
    out["constants"] = {"STAGES": list(api.STAGES), "STATUSES": list(api.STATUSES)}
    return out


GROUPS = [("p1_test_four_stages_across_usecase_instances_require_real_artifacts", p1_four_stages),
          ("p2_test_retry_is_idempotent_but_conflicting_request_rejected", p2_retry),
          ("p3_test_unknown_dirty_and_moved_sources_do_not_inherit_completion", p3_sources),
          ("p4_test_stage_order_and_completed_stage_immutability", p4_order_and_immutability),
          ("p5_predecessor_evidence", p5_predecessor_evidence),
          ("p6_argument_requires", p6_argument_requires),
          ("p7_racing_writers_and_integration_replay", p7_racing_and_integration)]

M7_TESTS = {
    "test_four_stages_across_usecase_instances_require_real_artifacts": "p1_test_four_stages_across_usecase_instances_require_real_artifacts",
    "test_retry_is_idempotent_but_conflicting_request_rejected": "p2_test_retry_is_idempotent_but_conflicting_request_rejected",
    "test_unknown_dirty_and_moved_sources_do_not_inherit_completion": "p3_test_unknown_dirty_and_moved_sources_do_not_inherit_completion",
    "test_stage_order_and_completed_stage_immutability": "p4_test_stage_order_and_completed_stage_immutability",
    "test_missing_predecessor_evidence_blocks_continuation": "p5_predecessor_evidence",
    "test_modified_predecessor_blocks_continuation": "p5_predecessor_evidence",
    "test_bad_receipt_metadata_blocks_continuation": "p5_predecessor_evidence (absent, list, wrong_ref, negative_bytes)",
    "test_artifact_metadata_counts_utf8_bytes": "p5_predecessor_evidence",
    "test_tree_is_resolved_from_captured_commit": {"unreachable": "exercises adapters.reverse_source.observe_source, not this module"},
    "test_racing_writers_cannot_lose_a_checkpoint": {"p7_racing_writers_and_integration_replay": "the part the application decides, as two sequential writers; threads are not a scenario step"},
    "test_git_observation_detects_dirty_and_unknown_sources": {"unreachable": "exercises adapters.reverse_source.observe_source over a real git repository, not this module"},
    "tests/test_integration.py::test_postgres_reverse_progress_concurrency_replay_and_history": {"p7_racing_writers_and_integration_replay": "the sequential part over MemoryStore; threads and PostgreSQL are not scenario steps"},
}

BRANCH_COVERAGE = {
    "ReverseProgress.__init__": "build",
    "_source require dict": "p3 status_not_a_dict_*; p6 source_not_a_dict, source_none_value",
    "_source require clean": "p3 record_unknown/dirty; p6 source_dirty, source_unknown",
    "_source require repository identity": "p6 source_repository_empty/int/missing",
    "_source require commit and tree format": "p6 source_commit_*, source_tree_*",
    "_source require one hash format": "p6 source_mixed_formats_*; p3 status_clean_mixed_hash_formats; source_both_sha256_is_pinned",
    "_source returns only repository, commit, tree": "p6 source_extra_keys_are_not_pinned, pinned_source_of_the_extra_keys",
    "status not a dict -> unknown": "p3 status_not_a_dict_*",
    "status dirty -> dirty, other not clean -> unknown": "p3 status_not_started_dirty, status_unknown/dirty/weird_status/status_missing/status_none",
    "status clean + ContractError -> unknown": "p3 status_clean_*",
    "status not_started / unchanged / changed": "p3 status_not_started, status_unchanged, status_changed_commit/repository",
    "record require project": "p6 project_*", "record require stage and status": "p6 stage_*, status_*",
    "record require request identity": "p6 request_*", "record require expected generation": "p6 generation_*",
    "record require rebaseline boolean": "p6 rebaseline_*", "record require artifact reference list": "p6 refs_*",
    "record require retained artifacts for complete": "p1 empty_complete_refused; p6 complete_without_refs; partial/pending without refs are allowed",
    "record artifacts.inspect of the references": "p1 missing_artifact_refused, invalid_reference_refused; p5 own_reference_missing_checked_before_the_transaction",
    "record idempotent replay": "p2 replay_is_the_original, replay_after_later_progress, refs_sorted_is_the_same_request",
    "record require conflicting request": "p2 conflict_*",
    "record require generation": "p6 stale_generation_*; p7 writer_b_stale; p2 other_rid_same_command_is_stale",
    "record require rebaseline and first stage on a changed source": "p3 moved_without_rebaseline, moved_rebaseline_not_first_stage, rebaseline_restart",
    "record require no rebaseline without a change": "p3 rebaseline_without_change",
    "record require predecessor complete": "p4 skip_ahead, skip_to_last, third_over_a_partial_predecessor, final_stage_over_partial",
    "record predecessor artifacts.inspect": "p5 missing_predecessor, modified_predecessor, metadata_*",
    "record require stage not complete (immutable)": "p4 downgrade_completed, rewrite_completed, pending_after_complete",
    "record writes progress, history and request": "p1 final, history_generations, requests; p3 history_after_rebaseline; p7 integration",
}


def run(api) -> dict:
    ws = R.Workspace()
    try:
        result, counts = {}, {}
        for name, group in GROUPS:
            result[name] = ws.scrub(group(api, ws))
            counts[name] = len(result[name])
        result["constants"] = {"STAGES": list(api.STAGES), "STATUSES": list(api.STATUSES)}
        result["m7_tests"] = M7_TESTS
        result["branch_coverage"] = BRANCH_COVERAGE
        result["cases_per_group"] = counts
        return result
    finally:
        ws.close()
