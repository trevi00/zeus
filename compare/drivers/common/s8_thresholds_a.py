"""Shared S8 scenario steps for the first three threshold modules, characterized BEFORE pilot 92 moves them (DESIGN-s8 §13 V18):

- `research.runtime_thresholds`: M7 `adapters/runtime_thresholds.py` (`resolve_policy`, `effective_policy`, `NATIVE_DEFAULTS`, `POLICY_FILE`);
  R-t0: `FULL_BODY_MIN_SCORE` is a V9 local constant (equal to the context ranking's), the registry comes from `research.domain`;
- `research.threshold_replay`: M7 `application/threshold_replay.py` (`ThresholdReplay.evaluate`); R-t0 (`MAX_EVENTS` V9 local) and R-t1
  (`validate_source` is an injected keyword-only constructor parameter, required only on the `legacy_source` path);
- `research.threshold_proposals`: M7 `application/threshold_proposals.py` (`ThresholdProposals.collect`); the same R-t0 and R-t1, plus the three
  owned buckets (`threshold_collection_inputs`, `threshold_proposal_runs`, `threshold_proposals`).

The reference holds the plain M7 modules (M7's own `validate_source`); the target injects context's `validate_source` (the same rule). The
recorded results must be identical.

Cases mirror M7 `tests/test_runtime_thresholds.py` (the invalid-policy refusals, the native default drift; the packaged-override test runs two
real processes and a real git repository: unreachable), `tests/test_threshold_replay.py` (the CLI test is the adapter, not this module),
`tests/test_threshold_collection.py` (the collection tests: once and keeps history, the vacuous acceptance, the legacy provenance, the non-
finite metadata, the reference verdict, the append tail) and `tests/test_threshold_proposals.py` (domain, not this module) plus LABELLED
additions for every `require`, branch and bucket of the three modules. `M7_TESTS` names what is reachable and what needs a real process.

Layer: harness (never shipped)

This module never imports `codex_harness`: everything arrives through `api`. The artifacts store, the policy provider and the native
evaluator are LABELLED fakes (M7's are `FileArtifacts`, `adapters.threshold_policy.current_policy` over a git repository and
`application.native_routing_replay`); the clock for `created_at` is the harness's. For every refusal the digest of the whole store before and
after is recorded."""

from __future__ import annotations

import hashlib
import json
import math
import tempfile
from copy import deepcopy
from pathlib import Path

NAME = "skill_match.FULL_BODY_MIN_SCORE"
REVISION = "a" * 40
OTHER_REVISION = "b" * 40
OWNED = ("threshold_collection_inputs", "threshold_proposal_runs", "threshold_proposals")


def sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=lambda o: type(o).__name__).encode()).hexdigest()[:16]


def plain(value):
    if isinstance(value, dict):
        return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        return {"nonfinite": repr(value)}
    return value


def outcome(fn) -> dict:
    """The returned value, or the refusal's type and message."""
    try:
        return {"returned": plain(fn())}
    except Exception as exc:  # the refusal is the characterized result
        return {"refused": type(exc).__name__, "message": str(exc)[:300], "cause": type(exc.__cause__).__name__ if exc.__cause__ else None}


def snapshot(store):
    return {"keys": sorted([b, k] for b, k in store.data), "digest": sha(sorted([[b, k, v] for (b, k), v in store.data.items()]))}


class Artifacts:
    """LABELLED fake of `FileArtifacts` (`put(text, kind) -> {'ref'}` and `document(ref)`): content-addressed, every call recorded."""

    def __init__(self, on_put=None):
        self.docs, self.puts, self.on_put = {}, [], on_put

    def put(self, text, kind):
        ref = "sha256:" + hashlib.sha256(text.encode()).hexdigest()
        self.puts.append({"kind": kind, "ref": ref, "bytes": len(text.encode())})
        self.docs[ref] = json.loads(text)
        if self.on_put is not None:
            self.on_put(ref)
        return {"ref": ref}

    def document(self, ref):
        return deepcopy(self.docs[ref])


class Native:
    """LABELLED fake native evaluator: `evaluate(events, values)` returns a scripted verdict and records its arguments."""

    def __init__(self, status="complete"):
        self.status, self.calls = status, []

    def evaluate(self, events, values):
        self.calls.append({"events": len(events), "values": list(values)})
        return {"status": self.status, "values": list(values), "events": len(events)}


def events(count=40, empty=False, sized=True, score=3):
    return [{"at": f"2026-01-01T00:{i // 60:02d}:{i % 60:02d}Z",
             "top": [{"score": s, **({"body_chars": 500} if sized else {})} for s in ([score] if empty else [score, score + 2])]}
            for i in range(count)]


def seed(store, bucket, key, state):
    with store.transaction() as tx:
        tx.put(bucket, key, state)


def policy(revision=REVISION, value=3):
    return {"values": {NAME: value}, "revision": revision, "definition_hash": "h" * 64}


# =====================================================================================================================
# research.runtime_thresholds
# =====================================================================================================================

INVALID_POLICIES = [
    ("empty_object", "{}"), ("version_true", '{"version":true,"overrides":{}}'), ("duplicate_key", '{"version":1,"version":1,"overrides":{}}'),
    ("override_bool", '{"version":1,"overrides":{"skill_match.FULL_BODY_MIN_SCORE":true}}'),
    ("override_nan", '{"version":1,"overrides":{"skill_match.FULL_BODY_MIN_SCORE":NaN}}'),
    ("override_infinity", '{"version":1,"overrides":{"skill_match.FULL_BODY_MIN_SCORE":Infinity}}'),
    ("override_other_registry_entry", '{"version":1,"overrides":{"lib.repeat_error_tracker.STRIKE_THRESHOLD":9}}'),
    ("override_ratio", '{"version":1,"overrides":{"ratio_tracker.WARN_THRESHOLD":4}}'),
    ("override_string", '{"version":1,"overrides":{"skill_match.FULL_BODY_MIN_SCORE":"4"}}'),
    ("override_null", '{"version":1,"overrides":{"skill_match.FULL_BODY_MIN_SCORE":null}}'),
    ("override_huge_int", '{"version":1,"overrides":{"skill_match.FULL_BODY_MIN_SCORE":' + "9" * 400 + "}}"),
    ("version_float", '{"version":1.0,"overrides":{}}'), ("version_two", '{"version":2,"overrides":{}}'),
    ("extra_key", '{"version":1,"overrides":{},"extra":1}'), ("overrides_list", '{"version":1,"overrides":[]}'),
    ("not_json", "not json"), ("bytes_not_text", None), ("json_list", "[]"), ("json_null", "null"), ("empty_text", ""),
]


def t1_resolve(api):
    cases = []
    for label, text in INVALID_POLICIES:
        cases.append({"case": label, **outcome(lambda: api.resolve_policy(text))})
    valid = ['{"version":1,"overrides":{}}', '{"version":1,"overrides":{"skill_match.FULL_BODY_MIN_SCORE":4}}',
             '{"version":1,"overrides":{"skill_match.FULL_BODY_MIN_SCORE":3.5}}', '{"version":1,"overrides":{"skill_match.FULL_BODY_MIN_SCORE":-1}}',
             '{"version":1,"overrides":{"skill_match.FULL_BODY_MIN_SCORE":0}}', '{ "version" : 1 , "overrides" : { } }']
    for text in valid:
        cases.append({"case": "valid:" + text, **outcome(lambda: api.resolve_policy(text))})
    return cases


def t2_native_drift(api):
    cases = []
    saved = dict(api.NATIVE_DEFAULTS)
    try:
        api.NATIVE_DEFAULTS[NAME] = 4  # tests: test_native_default_drift_is_detected
        cases.append({"case": "default_drifts_from_registry", **outcome(lambda: api.resolve_policy('{"version":1,"overrides":{}}'))})
        api.NATIVE_DEFAULTS[NAME] = saved[NAME]
        api.NATIVE_DEFAULTS["not.in.registry"] = 1
        cases.append({"case": "default_not_in_registry", **outcome(lambda: api.resolve_policy('{"version":1,"overrides":{}}'))})
        del api.NATIVE_DEFAULTS["not.in.registry"]
        api.NATIVE_DEFAULTS[NAME] = saved[NAME]
        cases.append({"case": "restored", **outcome(lambda: api.resolve_policy('{"version":1,"overrides":{}}'))})
    finally:
        api.NATIVE_DEFAULTS.clear()
        api.NATIVE_DEFAULTS.update(saved)
    return cases


def t3_effective(api):
    cases = [{"case": "packaged", **outcome(api.effective_policy)}]
    root = Path(tempfile.mkdtemp(prefix="thr-"))
    saved = api.get_policy_file()
    try:
        missing = root / "absent.json"
        api.set_policy_file(missing)
        cases.append({"case": "definition_unavailable", **outcome(api.effective_policy)})
        override = root / "override.json"
        override.write_text('{"version":1,"overrides":{"skill_match.FULL_BODY_MIN_SCORE":5}}', encoding="utf-8")
        api.set_policy_file(override)
        cases.append({"case": "override_file", **outcome(api.effective_policy)})
        bad = root / "bad.json"
        bad.write_text('{"version":1,"overrides":{"skill_match.FULL_BODY_MIN_SCORE":NaN}}', encoding="utf-8")
        api.set_policy_file(bad)
        cases.append({"case": "invalid_file", **outcome(api.effective_policy)})
        directory = root / "dir"
        directory.mkdir()
        api.set_policy_file(directory)
        cases.append({"case": "directory_is_oserror", **outcome(api.effective_policy)})
    finally:
        api.set_policy_file(saved)
    cases.append({"case": "restored", **outcome(api.effective_policy)})
    return cases


def runtime_thresholds(api) -> dict:
    groups = {"t1_resolve": t1_resolve(api), "t2_native_drift": t2_native_drift(api), "t3_effective": t3_effective(api)}
    return {**groups, "constants": {"NATIVE_DEFAULTS": dict(api.NATIVE_DEFAULTS), "registry_names": sorted(api.REGISTRY),
                                    "registry_default": api.REGISTRY[NAME].default, "policy_file_name": api.get_policy_file().name,
                                    "policy_parent_name": api.get_policy_file().parent.name},
            "m7_tests": M7_TESTS["runtime_thresholds"], "cases_per_group": {k: len(v) for k, v in groups.items()}}


# =====================================================================================================================
# research.threshold_replay
# =====================================================================================================================

def replay_cases(api):
    cases = []

    def record(label, fn, store):
        before = snapshot(store)
        cases.append({"case": label, **outcome(fn), "store_before": before, "store_after": snapshot(store)})

    def corpus_store():
        store = api.MemoryStore()
        seed(store, "skill_history", "project", {"events": events()})
        return store

    options = {"old_value": 3, "proposed_value": 4, "holdout_boundary": "2026-01-01T00:00:28Z"}
    store = corpus_store()
    record("native_history", lambda: api.replay(store).evaluate("project", **options), store)
    record("native_history_no_options", lambda: api.replay(store).evaluate("project"), store)
    record("missing_project_is_empty", lambda: api.replay(store).evaluate("other", **options), store)
    store = corpus_store()
    record("invalid_option_value", lambda: api.replay(store).evaluate("project", old_value=3, proposed_value=4, holdout_boundary="unknown"), store)
    record("unexpected_option", lambda: api.replay(store).evaluate("project", bogus=1), store)
    # a legacy segment (tests: test_import_to_replay_and_proposal_preserves_legacy_provenance)
    legacy = api.MemoryStore()
    seed(legacy, "legacy_skill_imports", api.digest(["project", "segment"]), {"events": events(), "source_ref": "sha256:" + "5" * 64})
    record("legacy_source", lambda: api.replay(legacy).evaluate("project", legacy_source="segment", **options), legacy)
    record("legacy_source_absent_segment", lambda: api.replay(legacy).evaluate("project", legacy_source="absent", **options), legacy)
    record("legacy_source_does_not_read_native", lambda: api.replay(store).evaluate("project", legacy_source="segment", **options), store)
    for label, bad in [("bad_id_punctuation", "bad id!"), ("empty", ""), ("leading_dot", ".x"), ("too_long", "a" * 129), ("integer", 7), ("slash", "a/b"),
                       ("bytes", b"segment"), ("unicode", "séance"), ("trailing_newline", "segment\n")]:
        record("invalid_source:" + label, lambda: api.replay(legacy).evaluate("project", legacy_source=bad, **options), legacy)
    record("longest_valid_source", lambda: api.replay(legacy).evaluate("project", legacy_source="a" * 128, **options), legacy)
    record("valid_source_charset", lambda: api.replay(legacy).evaluate("project", legacy_source="A0_.-z", **options), legacy)
    # the corpus is the last MAX_EVENTS events
    tall = api.MemoryStore()
    many = [{"id": str(i), "at": "2026-01-01T00:00:00Z", "top": [{"score": 3, "body_chars": 10}]} for i in range(api.MAX_EVENTS + 5)]
    seed(tall, "skill_history", "project", {"events": many})
    out = outcome(lambda: api.replay(tall).evaluate("project", **options))
    returned = out.get("returned", {})
    cases.append({"case": "corpus_is_the_last_max_events", "max_events": api.MAX_EVENTS, "events": len(returned.get("events", [])),
                  "first_id": returned.get("events", [{}])[0].get("id"), "last_id": returned.get("events", [{}])[-1].get("id"),
                  "corpus_hash": returned.get("corpus_hash"), "report_digest": sha(returned.get("report"))})
    exact = api.MemoryStore()
    seed(exact, "skill_history", "project", {"events": many[:api.MAX_EVENTS]})
    out = outcome(lambda: api.replay(exact).evaluate("project", **options))
    cases.append({"case": "exactly_max_events_kept_whole", "events": len(out["returned"]["events"]), "corpus_hash": out["returned"]["corpus_hash"]})
    # the call does not write
    cases.append({"case": "no_write", "store": snapshot(store)})
    return cases


def threshold_replay(api) -> dict:
    cases = replay_cases(api)
    return {"r1_replay": cases, "m7_tests": M7_TESTS["threshold_replay"], "cases_per_group": {"r1_replay": len(cases)}}


# =====================================================================================================================
# research.threshold_proposals
# =====================================================================================================================

def collect_cases(api):
    cases = []

    def fresh(**kw):
        store, artifacts = api.MemoryStore(), Artifacts(kw.pop("on_put", None))
        return store, artifacts

    def service(store, artifacts, provider=None, native=None, calls=None):
        def prov():
            if calls is not None:
                calls.append(1)
            return (provider or policy)()
        return api.proposals(store, artifacts, prov, native)

    def record(label, fn, store, artifacts=None, extra=None):
        before = snapshot(store)
        result = outcome(fn)
        cases.append({"case": label, **result, "store_before": before, "store_after": snapshot(store),
                      "artifact_puts": [p["kind"] for p in artifacts.puts] if artifacts else None, **(extra or {})})
        return result

    # tests: test_collection_records_exact_evidence_once_and_keeps_history
    store, artifacts = fresh()
    seed(store, "skill_history", "project", {"events": events()})
    original = deepcopy(store.data["skill_history", "project"])
    svc = service(store, artifacts)
    results = [record(f"collect_{i}", lambda: svc.collect("project"), store, artifacts) for i in range(3)]
    cases.append({"case": "collect_is_idempotent", "equal": all(r == results[0] for r in results), "puts": len(artifacts.puts),
                  "history_unchanged": store.data["skill_history", "project"] == original,
                  "threshold_proposals_rows": sum(b == "threshold_proposals" for b, _ in store.data),
                  "no_deployment": not any(b in {"deployment", "decisions_pending"} for b, _ in store.data)})
    run = results[0]["returned"]
    document = artifacts.document(run["evidence_ref"])
    cases.append({"case": "evidence_document", "keys": sorted(document), "events": len(document["events"]), "policy": document["policy"],
                  "alternatives": [len(p["alternatives"]) for p in document["proposals"]], "native_routing": document["native_routing"],
                  "digest": sha(document)})
    record("other_project_other_run", lambda: svc.collect("other"), store, artifacts)
    record("collect_other_project_with_history", lambda: (seed(store, "skill_history", "third", {"events": events(score=4)}) or svc.collect("third")), store, artifacts)

    # every require / option
    for label, rnd in [("negative", -1), ("bool", True), ("float", 1.0), ("string", "1"), ("none", None)]:
        s, a = fresh()
        calls = []
        record("evaluation_round_" + label, lambda: service(s, a, calls=calls).collect("project", evaluation_round=rnd), s, a, {"provider_calls": len(calls)})
    s, a = fresh()
    seed(s, "skill_history", "project", {"events": events()})
    r0 = record("evaluation_round_zero", lambda: service(s, a).collect("project", evaluation_round=0), s, a)
    r1 = record("evaluation_round_one_is_another_run", lambda: service(s, a).collect("project", evaluation_round=1), s, a)
    cases.append({"case": "rounds_differ", "different": r0["returned"]["id"] != r1["returned"]["id"], "rounds": [r0["returned"]["evaluation_round"], r1["returned"]["evaluation_round"]]})
    for label, bad in [("punctuation", "bad id!"), ("empty", ""), ("integer", 5), ("too_long", "a" * 129), ("slash", "a/b")]:
        s, a = fresh()
        calls = []
        record("invalid_source:" + label, lambda: service(s, a, calls=calls).collect("project", legacy_source=bad), s, a, {"provider_calls": len(calls)})
    s, a = fresh()
    calls = []
    record("round_refusal_precedes_source_refusal", lambda: service(s, a, calls=calls).collect("project", legacy_source="bad id!", evaluation_round=-1), s, a,
           {"provider_calls": len(calls)})

    # the policy provider
    def failing():
        raise RuntimeError("provider down")
    s, a = fresh()
    record("policy_provider_error_propagates", lambda: service(s, a, provider=failing).collect("project"), s, a)
    s, a = fresh()
    seed(s, "skill_history", "project", {"events": events()})
    record("policy_revision_binds_the_run", lambda: service(s, a, provider=lambda: policy(OTHER_REVISION)).collect("project"), s, a)
    record("policy_value_changes_current", lambda: service(s, a, provider=lambda: policy(value=4)).collect("project"), s, a)
    record("policy_without_revision", lambda: service(s, a, provider=lambda: {"values": {NAME: 3}}).collect("project"), s, a)
    record("policy_unbound_revision", lambda: service(s, a, provider=lambda: policy("unbound")).collect("project"), s, a)
    record("policy_without_values", lambda: service(s, a, provider=lambda: {"revision": REVISION}).collect("project"), s, a)
    record("policy_value_not_finite", lambda: service(s, a, provider=lambda: policy(value=float("nan"))).collect("project"), s, a)

    # corpus shapes
    for label, ev in [("empty_corpus_no_proposals", []), ("too_few_events", events(5)), ("empty_admission_events", events(empty=True)),
                      ("unsized_events_reference_rejected", events(sized=False)), ("shifted_scores", events(score=4))]:
        s, a = fresh()
        seed(s, "skill_history", "project", {"events": ev})
        res = record(label, lambda: service(s, a).collect("project"), s, a)
        if "returned" in res:
            cases.append({"case": label + ":rows", "blockers": [r["activation_blockers"] for r in res["returned"]["proposals"]],
                          "suggested": [r["proposal"]["suggested"] for r in res["returned"]["proposals"]]})
    s, a = fresh()
    record("missing_history_record", lambda: service(s, a).collect("project"), s, a)
    for sample in (0, -1, True, 10.0, 41, 1):
        s, a = fresh()
        seed(s, "skill_history", "project", {"events": events()})
        record(f"min_sample:{sample!r}", lambda: service(s, a).collect("project", min_sample=sample), s, a)

    # native evaluator
    for status in ("complete", "partial", "failed"):
        s, a = fresh()
        seed(s, "skill_history", "project", {"events": events()})
        native = Native(status)
        res = record("native_" + status, lambda: service(s, a, native=native).collect("project"), s, a, {"native_calls": native.calls})
        document = a.document(res["returned"]["evidence_ref"])
        cases.append({"case": "native_" + status + ":evidence", "native_routing": document["native_routing"],
                      "blockers": [r["activation_blockers"] for r in res["returned"]["proposals"]]})
    s, a = fresh()
    seed(s, "skill_history", "project", {"events": events()})
    plain_run = service(s, a).collect("project")
    s2, a2 = fresh()
    seed(s2, "skill_history", "project", {"events": events()})
    native_run = service(s2, a2, native=Native()).collect("project")
    cases.append({"case": "native_evaluator_is_part_of_the_basis", "different_runs": plain_run["id"] != native_run["id"],
                  "inputs": sorted(k for b, k in s.data if b == "threshold_collection_inputs") != sorted(k for b, k in s2.data if b == "threshold_collection_inputs")})

    # legacy provenance
    s, a = fresh()
    seed(s, "legacy_skill_imports", api.digest(["project", "segment"]), {"events": events(), "source_ref": "sha256:" + "5" * 64})
    res = record("legacy_source", lambda: service(s, a).collect("project", legacy_source="segment"), s, a)
    document = a.document(res["returned"]["evidence_ref"])
    cases.append({"case": "legacy_source:evidence", "source_ref": document["source_ref"], "legacy_source": document["legacy_source"],
                  "blockers": [r["activation_blockers"] for r in res["returned"]["proposals"]]})
    record("legacy_source_absent_segment", lambda: service(s, a).collect("project", legacy_source="absent"), s, a)
    record("legacy_source_is_not_native_history", lambda: service(s, a).collect("project"), s, a)

    # non-finite evidence (tests: test_nonfinite_source_metadata_cannot_enter_evidence)
    for label, extra in [("nan", float("nan")), ("infinity", float("inf")), ("unserializable", object())]:
        s, a = fresh()
        corpus = events()
        corpus[0]["extra"] = extra
        seed(s, "skill_history", "project", {"events": corpus})
        record("nonfinite_metadata:" + label, lambda: service(s, a).collect("project"), s, a, {"threshold_buckets": sorted(b for b, _ in s.data if b.startswith("threshold_"))})
    for label, mutate in [("nonfinite_score", lambda e: e[0]["top"][0].__setitem__("score", float("nan"))), ("string_score", lambda e: e[0]["top"][0].__setitem__("score", "3")),
                          ("bool_score", lambda e: e[0]["top"][0].__setitem__("score", True)), ("top_not_list", lambda e: e[0].__setitem__("top", "x")),
                          ("event_not_dict", lambda e: e.__setitem__(0, 7))]:
        s, a = fresh()
        corpus = events()
        mutate(corpus)
        seed(s, "skill_history", "project", {"events": corpus})
        record("malformed_event:" + label, lambda: service(s, a).collect("project"), s, a)

    # the corpus is the last MAX_EVENTS events
    s, a = fresh()
    many = [{"id": str(i), "at": f"2026-01-01T00:00:{i % 60:02d}Z", "top": [{"score": 3 + (i % 3), "body_chars": 500}]} for i in range(api.MAX_EVENTS + 3)]
    seed(s, "skill_history", "project", {"events": many})
    res = record("corpus_is_the_last_max_events", lambda: service(s, a).collect("project"), s, a)
    if "returned" in res:
        document = a.document(res["returned"]["evidence_ref"])
        cases.append({"case": "corpus_is_the_last_max_events:evidence", "max_events": api.MAX_EVENTS, "events": len(document["events"]),
                      "first_id": document["events"][0]["id"], "last_id": document["events"][-1]["id"]})

    # the first committed evaluation wins (INV-NATIVE-REPLAY-001): a concurrent writer commits between the artifact and the final unit
    s, a = fresh()
    seed(s, "skill_history", "project", {"events": events()})
    won = {}

    def writer(winning_run):
        def hook(ref):
            probe_s, probe_a = fresh()
            seed(probe_s, "skill_history", "project", {"events": events()})
            # compute the basis the collector computes: find it from a dry run on a scratch store
            dry = service(probe_s, probe_a).collect("project")
            basis = next(k for b, k in probe_s.data if b == "threshold_collection_inputs")
            with s.transaction() as tx:
                tx.put("threshold_proposal_runs", winning_run, {"id": winning_run, "winner": True})
                tx.put("threshold_collection_inputs", basis, {"run_id": winning_run})
                won["dry"] = dry["id"]
        return hook
    a.on_put = writer("winner-run")
    record("concurrent_input_won_returns_winner", lambda: service(s, a).collect("project"), s, a)
    # a concurrent writer committed the same run id but no input row
    s, a = fresh()
    seed(s, "skill_history", "project", {"events": events()})

    def same_run(ref):
        run_id = api.digest(["project", ref])
        with s.transaction() as tx:
            tx.put("threshold_proposal_runs", run_id, {"id": run_id, "same_run": True})
    a.on_put = same_run
    record("concurrent_same_run_returns_existing", lambda: service(s, a).collect("project"), s, a)
    return cases


def threshold_proposals(api) -> dict:
    cases = collect_cases(api)
    return {"c1_collect": cases, "owned_buckets": list(OWNED), "m7_tests": M7_TESTS["threshold_proposals"], "cases_per_group": {"c1_collect": len(cases)}}


M7_TESTS = {
    "runtime_thresholds": {
        "test_invalid_or_unwired_policy_cannot_be_loaded": "t1_resolve (the eight listed texts plus labelled additions)",
        "test_native_default_drift_is_detected": "t2_native_drift",
        "test_packaged_override_changes_actual_router_and_git_proposer_together": "unreachable here: a real git repository and two real child processes"},
    "threshold_replay": {
        "test_import_to_replay_and_proposal_preserves_legacy_provenance": "r1_replay legacy_source (the import is another module)",
        "test_cli_preserves_corpus_and_never_writes_policy": "the CLI adapter (threshold_replay.main) is out of scope; r1_replay no_write for the use case"},
    "threshold_proposals": {
        "test_collection_records_exact_evidence_once_and_keeps_history": "c1_collect collect_idempotent and evidence_document (sequential, not threads)",
        "test_vacuous_reference_acceptance_is_explicitly_blocked": "c1_collect empty_admission_events",
        "test_import_to_replay_and_proposal_preserves_legacy_provenance": "c1_collect legacy_source",
        "test_nonfinite_source_metadata_cannot_enter_evidence": "c1_collect nonfinite_metadata",
        "test_reference_verdict_never_removes_required_release_blocker": "c1_collect unsized_events_reference_rejected and shifted_scores",
        "test_import_append_tail_and_separate_segment_keep_replayable_lineage": "c1_collect corpus_is_the_last_max_events (the import is another module)",
        "test_current_policy_*, test_real_git_cli_*, test_literal_crlf_*": "the policy adapter and the CLI: out of scope (a real git repository)"},
}
