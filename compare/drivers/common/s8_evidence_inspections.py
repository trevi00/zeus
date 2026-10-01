"""Shared S8 scenario steps (`evidence.inspections`): M7 `application/evidence_inspection.py` (`EvidenceInspections`:
`binding`, `inspect` with its `fence`, `require_all_checked`; `forwards_progress`), characterized BEFORE the module moves
(DESIGN-s8 §1 V4/V7 and §6 V11; the branch table `branch-table-evidence.txt` section `application/evidence_inspection.py`:
every raise and every `require` of this module is covered).

- **e1_forwards_progress**: which inspector callables take the caller's `progress` (a declared name, `**kwargs`, a keyword-only
  or positional-only name, a bound method, a callable instance) and which are legacy (no name, a callable that cannot be
  described: a `TypeError` and a `ValueError` from `signature`).
- **e2_binding**: the typed-lease and captured-candidate refusals, the bound keys and their defaults, `cwd` as text.
- **e3_inspect_identity**: the snapshot validation (every `require` of the identity), the v4 key and what it is sensitive to
  (policy, environment, interpreter, cwd, platform, claims, the execution), the cache hit, the row shape and the verdicts.
- **e4_inspect_checks**: the order of the report checks (unknown state, policy, project, environment/interpreter), the absent
  workspace that skips them, the project context handed to the adapter exactly as keyed, `progress` called before and after and
  handed only to an adapter that declares it, the concurrent winner, an inspector that raises.
- **e5_fence_recording**: `guard` (the fence): called inside the ledger's own transactions, its refusal raised unchanged with
  no row and no notice, a `BaseException` refusal, the transaction counts with and without a guard; a failed recording is a
  named notice and a `ContractError`, the notice that cannot be written, a store that fails on the cache read.
- **e6_require_all_checked**: every refusal in order, the message of each verdict, the keyword-only arguments, no write.

Layer: harness (never shipped)

This module never imports `codex_harness`: everything from the product arrives through `api`, the object a reference (later a
target) driver builds. The `inspector` is a LABELLED double with the result shapes of M7
`adapters/evidence_inspection.EvidenceInspector` (`snapshot`, `inspect`): the adapter itself is a later family and is never run
here. The lease, the candidate and the claims are LABELLED fixtures with the typed shapes of M7 `tests/test_evidence_inspection.py`
(`Workflow.claim`, a captured candidate, `parse_claim`); a store that fails on a chosen transaction is M7's `RecordingFails`
generalized (labelled where it is made). The M7 tests that need the real adapter (real child processes), the executor, the
Workflow or PostgreSQL belong to the adapter and executor families; the part of them the application decides is characterized here.
For every refusal the digest of each of the two owned buckets and of the whole store before and after is recorded."""

from __future__ import annotations

import json
from copy import deepcopy
from types import SimpleNamespace

import s8_research_program as R

CANARY = "CANARY-must-never-be-emitted"
REV, BASE, TREE = "c" * 40, "b" * 40, "d" * 40
POLICY, ENVDIGEST = "a" * 64, "e" * 64
PY = "/fixture/bin/python"
CWD = "/fixture/ws"
ENVIRONMENT = {"PATH": "/fixture/bin", "PYTHONIOENCODING": "utf-8"}
OWNED = ("evidence_inspections", "evidence_inspection_notices")
CLAIMS = [{"id": "k1", "kind": "command", "argv": ["python", "-m", "pytest", "-q"], "expected_exit": 0, "origin": "free_text"},
          {"id": "k2", "kind": "file", "path": "docs/note.md", "sha256": "f" * 64, "range": None, "origin": "structured"}]
UNSET = object()


class Stop(BaseException):
    """LABELLED. A refusal that is not an `Exception` (a cancellation): the fence records it and re-raises it."""


# ---- builders (M7 tests/test_evidence_inspection.py) --------------------------------------------------------------------
def lease(**overrides):
    """LABELLED. The typed execution lease `Workflow.claim` returns: id, generation, attempt and owner."""
    return {"id": "task-1", "generation": 1, "attempt": 1, "lease_owner": "owner-1", **overrides}


def candidate(**overrides):
    """LABELLED. The captured candidate: revision, base and tree."""
    return {"revision": REV, "base": BASE, "tree": TREE, **overrides}


def identity(**overrides):
    """The identity shape of M7 `EvidenceInspector.snapshot`."""
    return {"policy_hash": POLICY, "environment_names": sorted(ENVIRONMENT), "environment_digest": ENVDIGEST, "interpreter": PY,
            "cwd": CWD, "tool": {"python": "3.fixture", "executable_digest": "x" * 64, "implementation": "CPython"},
            "platform": "fixture-host", **overrides}


class Base:
    """LABELLED. The result shapes of M7 `EvidenceInspector` (`snapshot`, `inspect`), scripted: the default report checks
    every claim and names the identity's own policy, environment and interpreter, so a refusal case changes one thing.
    `snapshot_value` (a dict, or any other value), `report_edit` (a function over the default report), `on_run` (a side
    effect inside `inspect`), `snapshot_error` and `run_error` script the faults."""

    def __init__(self, ident=None, snapshot_value=UNSET, report_edit=None, on_run=None, snapshot_error=None, run_error=None,
                 project=None, states=None):
        self.ident = identity() if ident is None else ident
        self.snapshot_value, self.report_edit, self.on_run = snapshot_value, report_edit, on_run
        self.snapshot_error, self.run_error, self.project, self.states = snapshot_error, run_error, project, states
        self.calls = []

    def snapshot(self, cwd=None):
        self.calls.append(["snapshot", None if cwd is None else str(cwd)])
        if self.snapshot_error is not None:
            raise self.snapshot_error
        if self.snapshot_value is not UNSET:
            return deepcopy(self.snapshot_value)
        value = {"identity": deepcopy(self.ident), "environment": dict(ENVIRONMENT), "interpreter": self.ident["interpreter"]}
        if self.project is not None:
            value["project"] = deepcopy(self.project)
        return value

    def _run(self, claims, cwd, binding, environment, interpreter, extra):
        shown = {k: ("<callable>" if callable(v) else v) for k, v in extra.items()}
        self.calls.append(["inspect", list(claims), str(cwd), binding, environment, interpreter, shown])
        if self.on_run is not None:
            self.on_run()
        if self.run_error is not None:
            raise self.run_error
        states = self.states or ["checked"] * len(claims)
        context = {**binding, "cwd": str(cwd), "environment": sorted(environment), "environment_digest": ENVDIGEST, "python": "3.fixture",
                   "interpreter": interpreter, "pythonpath": None}
        if "project" in extra:
            context["project_digest"] = extra["project"]["digest"]
        report = {"context": context, "policy_hash": POLICY,
                  "findings": [{"claim": c, "state": st, "cause": "fixture " + st} for c, st in zip(claims, states)],
                  "inspection_id": "fixture-inspection"}
        return self.report_edit(report) if self.report_edit is not None else report


class Legacy(Base):
    """M7 `EvidenceInspector.inspect` before `progress`: neither `progress` nor `project` is accepted."""

    def inspect(self, claims, cwd, binding, environment=None, interpreter=None):
        return self._run(claims, cwd, binding, environment, interpreter, {})


class Declaring(Base):
    """M7 `EvidenceInspector.inspect` as shipped: `progress` is a declared parameter."""

    def inspect(self, claims, cwd, binding, environment=None, interpreter=None, progress=None):
        return self._run(claims, cwd, binding, environment, interpreter, {} if progress is None else {"progress": progress})


class Profiled(Base):
    """The profile-aware shape (INV-PROJECT-EVIDENCE-001): `project` and `progress` are both accepted."""

    def inspect(self, claims, cwd, binding, environment=None, interpreter=None, project=None, progress=None):
        extra = {}
        if project is not None:
            extra["project"] = project
        if progress is not None:
            extra["progress"] = progress
        return self._run(claims, cwd, binding, environment, interpreter, extra)


class Keywords(Base):
    """An adapter whose `inspect` takes `**kwargs`: it is handed `progress` and `project` by keyword."""

    def inspect(self, claims, cwd, binding, **kwargs):
        return self._run(claims, cwd, binding, kwargs.pop("environment", None), kwargs.pop("interpreter", None), kwargs)


class Counting:
    """LABELLED. A store wrapper that counts the transactions the ledger opens and, for `fail_on`, raises `error` instead of
    opening the n-th one (M7's `RecordingFails`, generalized: the read succeeds, the write does not)."""

    def __init__(self, inner, fail_on=(), error=None):
        self.inner, self.fail_on, self.error, self.count = inner, set(fail_on), error, 0

    def transaction(self, *args, **kwargs):
        self.count += 1
        if self.count in self.fail_on:
            raise self.error
        return self.inner.transaction(*args, **kwargs)


def system(api, inspector=None, fail_on=(), error=None):
    base = api.MemoryStore()
    store = Counting(base, fail_on, error)
    inspector = Declaring() if inspector is None else inspector
    return SimpleNamespace(api=api, base=base, store=store, inspector=inspector, svc=api.EvidenceInspections(store, inspector))


def go(s, claims=None, task=None, cand=None, cwd=CWD, **kwargs):
    return s.svc.inspect(lease() if task is None else task, candidate() if cand is None else cand,
                         CLAIMS if claims is None else claims, cwd, **kwargs)


def key(s, claims=None, task=None, cand=None, cwd=CWD, ident=None):
    """The v4 key M7 computes (the digest of the version, the binding, the identity and the claims)."""
    bound = s.api.EvidenceInspections.binding(lease() if task is None else task, candidate() if cand is None else cand, cwd)
    return s.api.digest(["evidence-inspection-v4", bound, identity() if ident is None else ident, list(CLAIMS if claims is None else claims)])


# ---- observations -------------------------------------------------------------------------------------------------------
def attempt(fn, *args, **kwargs):
    """The characterized outcome of one call: its value, or the refusal (type, text; a `Stop` is a `BaseException`)."""
    try:
        return {"value": fn(*args, **kwargs)}
    except (Exception, Stop) as exc:
        result = {"raised": type(exc).__name__, "message": str(exc)[:400]}
        for name in ("reason_code", "field"):
            if hasattr(exc, name):
                result[name] = getattr(exc, name)
        return result


def state(s):
    """The digests of the two owned buckets and of the whole store, and the row counts of the two buckets."""
    rows = {bucket: len(scan(s.base, bucket)) for bucket in OWNED}
    return {"buckets": R.snapshot(s.base, OWNED), "store": R.store_digest(s.base), "rows": rows}


def obs(s, fn, *args, **kwargs):
    """One call: its value or refusal, and the owned-bucket and whole-store digests before and after."""
    before = state(s)
    result = attempt(fn, *args, **kwargs)
    after = state(s)
    return {**result, "before": before, "after": after, "nothing_written": before["store"] == after["store"],
            "leaks_canary": CANARY in json.dumps(result, default=str)}


def scan(store, bucket):
    with store.transaction() as tx:
        return tx.scan(bucket)


def get(store, bucket, row_id):
    with store.transaction() as tx:
        return tx.get(bucket, row_id)


def put(store, bucket, row_id, body):
    with store.transaction() as tx:
        tx.put(bucket, row_id, body)


def inspections(s):
    return {"inspector_calls": [c[0] for c in s.inspector.calls], "transactions": s.store.count}


# ---- E1 -----------------------------------------------------------------------------------------------------------------
def e1_forwards_progress(api, ws):
    out = {}

    def legacy(claims, cwd, binding, environment=None, interpreter=None): pass

    def declared(claims, cwd, binding, environment=None, interpreter=None, progress=None): pass

    def keyword_only(claims, *, progress=None): pass

    def positional_only(progress, /, claims): pass

    def var_keyword(claims, **kwargs): pass

    def var_positional(*args): pass

    def other_name(claims, cwd, binding, progression=None): pass

    def uninspectable(claims): pass
    uninspectable.__wrapped__ = uninspectable      # LABELLED: `signature` raises ValueError (a wrapper loop)

    def invalid_signature(claims): pass
    invalid_signature.__signature__ = 5            # LABELLED: `signature` raises TypeError (not a Signature)

    class Instance:
        def __call__(self, claims, progress=None): pass

    class InstanceLegacy:
        def __call__(self, claims): pass

    cases = {"legacy": legacy, "declared": declared, "keyword_only": keyword_only, "positional_only": positional_only,
             "var_keyword": var_keyword, "var_positional_only": var_positional, "other_name": other_name,
             "uninspectable_value_error": uninspectable, "invalid_signature_type_error": invalid_signature,
             "callable_instance_declared": Instance(), "callable_instance_legacy": InstanceLegacy(),
             "bound_method_declared": Declaring().inspect, "bound_method_legacy": Legacy().inspect,
             "bound_method_keywords": Keywords().inspect, "bound_method_profiled": Profiled().inspect,
             "lambda_default": lambda claims, progress=None: None, "none": None, "not_callable": 7}
    for name, call in cases.items():
        result = attempt(api.forwards_progress, call)
        out[name] = {**result, "is_bool": type(result.get("value")) is bool}
    return out


# ---- E2 -----------------------------------------------------------------------------------------------------------------
def e2_binding(api, ws):
    out = {}
    s = system(api)
    binding = api.EvidenceInspections.binding
    out["binding_valid"] = obs(s, binding, lease(), candidate(), CWD)
    out["binding_through_the_instance"] = obs(s, s.svc.binding, lease(), candidate(), CWD)
    out["binding_defaults"] = obs(s, binding, {"id": "t", "generation": 0, "attempt": 0}, {"revision": REV}, "ws")
    out["binding_extra_keys_ignored"] = obs(s, binding, lease(extra=CANARY), candidate(extra=CANARY), CWD)
    import pathlib
    out["binding_cwd_path_object"] = obs(s, binding, lease(), candidate(), pathlib.PurePosixPath("/fixture/p"))
    for name, task in (("not_a_dict", ["task-1", 1, 1]), ("none", None), ("no_id", {"generation": 1, "attempt": 1}),
                       ("id_not_text", lease(id=7)), ("id_none", lease(id=None)), ("no_generation", {"id": "t", "attempt": 1}),
                       ("generation_bool", lease(generation=True)), ("generation_text", lease(generation="1")),
                       ("generation_float", lease(generation=1.0)), ("no_attempt", {"id": "t", "generation": 1}),
                       ("attempt_bool", lease(attempt=True)), ("attempt_text", lease(attempt="1")),
                       ("m7_only_the_id", {"id": "task-1"})):
        out["lease_refused_" + name] = obs(s, binding, task, candidate(), CWD)
    for name, cand in (("not_a_dict", [REV]), ("none", None), ("empty", {}), ("revision_empty", candidate(revision="")),
                       ("revision_not_text", candidate(revision=7)), ("revision_none", candidate(revision=None)),
                       ("revision_bytes", candidate(revision=REV.encode()))):
        out["candidate_refused_" + name] = obs(s, binding, lease(), cand, CWD)
    out["order_lease_before_candidate"] = obs(s, binding, {"id": "t"}, {}, CWD)
    # inspect refuses on the binding before the inspector is asked anything, with no transaction
    for name, args in (("lease", ({"id": "task-1"}, candidate())), ("candidate", (lease(), {}))):
        t = system(api)
        out["inspect_binding_refusal_" + name] = {**obs(t, t.svc.inspect, args[0], args[1], CLAIMS, CWD), **inspections(t)}
    t = system(api)
    out["inspect_binding_refusal_after_progress_start"] = {**obs(t, t.svc.inspect, {"id": "t"}, candidate(), CLAIMS, CWD,
                                                                 progress=lambda point: t.inspector.calls.append(["progress", point])),
                                                           **inspections(t)}
    out["state_on_instance"] = {"store_is_given": s.svc.store is s.store, "inspector_is_given": s.svc.inspector is s.inspector}
    return out


# ---- E3 -----------------------------------------------------------------------------------------------------------------
def snapshot_of(**identity_overrides):
    return {"identity": identity(**identity_overrides), "environment": dict(ENVIRONMENT), "interpreter": PY}


def e3_inspect_identity(api, ws):
    out = {}
    # M7 test_ledger_binds_the_inspection_to_the_execution_and_never_records_a_failure_as_success (the memory backend)
    s = system(api)
    row = go(s)
    out["first_inspection"] = {"row": row, "id_is_the_v4_key": row["id"] == key(s), "calls": s.inspector.calls, "stored_equals_row":
                               get(s.base, api.BUCKET, row["id"]) == row, **inspections(s), "state": state(s)}
    out["row_keys"] = sorted(row)
    out["authority_text_has_no_canary"] = CANARY not in json.dumps(row)
    before = state(s)
    again = go(s)
    out["cache_hit_returns_the_stored_row"] = {"equal": again == row, "inspector_calls": [c[0] for c in s.inspector.calls],
                                               "transactions": s.store.count, "unchanged": state(s) == before}
    out["verdict_incomplete_denominator"] = {k: row[k] for k in ("verdict", "denominator")}
    t = system(api, Declaring(states=["checked", "not_checked"]))
    out["verdict_incomplete_with_unchecked"] = (lambda r: {k: r[k] for k in ("verdict", "denominator")})(go(t))
    t = system(api, Declaring(states=["checked", "checked"]))
    done = go(t)
    out["verdict_all_checked"] = {k: done[k] for k in ("verdict", "denominator")}
    t = system(api)
    empty = go(t, claims=[])
    out["verdict_no_claims"] = {"verdict": empty["verdict"], "denominator": empty["denominator"], "claims": empty["claims"]}
    t = system(api, Declaring(states=["checked", "flake_pattern"]))
    out["verdict_flake_is_incomplete"] = go(t)["verdict"]
    # claims as a tuple, and the stored claims are a copy
    t = system(api)
    tupled = go(t, claims=tuple(CLAIMS))
    out["claims_tuple_stored_as_list"] = {"type": type(tupled["claims"]).__name__, "equal": tupled["claims"] == CLAIMS,
                                          "same_id_as_list": tupled["id"] == key(t, claims=list(CLAIMS)),
                                          "inspector_received": type(t.inspector.calls[1][1]).__name__}
    # the identity of the inspection: what changes the id and what does not
    ids = {"base": row["id"]}
    variants = {
        "other_task": dict(task=lease(id="task-2")), "other_generation": dict(task=lease(generation=2)),
        "other_attempt": dict(task=lease(attempt=2)), "other_owner": dict(task=lease(lease_owner="owner-2")),
        "other_revision": dict(cand=candidate(revision="e" * 40)), "other_base": dict(cand=candidate(base="a" * 40)),
        "other_tree": dict(cand=candidate(tree="a" * 40)), "other_cwd": dict(cwd="/fixture/ws2"),
        "other_claims": dict(claims=CLAIMS[:1]), "reordered_claims": dict(claims=list(reversed(CLAIMS)))}
    for name, kwargs in variants.items():
        t = system(api)
        r = go(t, **kwargs)
        ids[name] = r["id"]
        out["identity_" + name] = {"new_id": r["id"] != row["id"], "is_the_v4_key": r["id"] == key(t, **{k: v for k, v in kwargs.items()})}
    for name, change in (("other_policy", {"policy_hash": "b" * 64}), ("other_environment_digest", {"environment_digest": "f" * 64}),
                         ("other_interpreter", {"interpreter": "/other/python"}), ("other_platform", {"platform": "fixture-other-host"}),
                         ("other_cwd_in_identity", {"cwd": "/elsewhere"}), ("other_tool", {"tool": {"python": "3.other"}}),
                         ("extra_identity_key", {"extra": 1})):
        t = system(api, Declaring(ident=identity(**change), report_edit=(
            (lambda rep, c=change: {**rep, "policy_hash": c["policy_hash"]}) if "policy_hash" in change else
            (lambda rep, c=change: {**rep, "context": {**rep["context"], "environment_digest": c["environment_digest"]}})
            if "environment_digest" in change else
            (lambda rep, c=change: {**rep, "context": {**rep["context"], "interpreter": c["interpreter"]}})
            if "interpreter" in change else None)))
        r = go(t)
        out["identity_" + name] = {"new_id": r["id"] != row["id"], "is_the_v4_key": r["id"] == key(t, ident=identity(**change)),
                                   "inspector_in_row": r["inspector"] == identity(**change)}
    out["ids_distinct"] = len(set(ids.values())) == len(ids)
    # the older row is neither reused nor overwritten by another inspection in the same store
    t = system(api)
    first = go(t)
    other = go(t, cwd="/fixture/ws2")
    out["other_cwd_keeps_the_older_row"] = {"two_rows": len(scan(t.base, api.BUCKET)) == 2, "older_untouched":
                                            get(t.base, api.BUCKET, first["id"]) == first, "ids_differ": first["id"] != other["id"]}
    # the snapshot is asked once, for this workspace; `cwd` reaches it as given
    out["snapshot_asked_once_with_the_cwd"] = {"calls": [c for c in s.inspector.calls if c[0] == "snapshot"]}
    # a snapshot that is not a dict, and every require of the identity
    shapes = {
        "snapshot_none": None, "snapshot_list": [identity()], "snapshot_text": "identity", "snapshot_empty_dict": {},
        "identity_missing": {"environment": dict(ENVIRONMENT)}, "identity_none": {"identity": None, "environment": dict(ENVIRONMENT)},
        "identity_list": {"identity": [], "environment": dict(ENVIRONMENT)},
        "no_environment": {"identity": identity(), "interpreter": PY},
        "environment_list": {"identity": identity(), "environment": ["PATH"], "interpreter": PY},
        "environment_none": {"identity": identity(), "environment": None, "interpreter": PY},
        "policy_hash_missing": {**snapshot_of(), "identity": {k: v for k, v in identity().items() if k != "policy_hash"}},
        "policy_hash_empty": snapshot_of(policy_hash=""), "policy_hash_not_text": snapshot_of(policy_hash=7),
        "policy_hash_none": snapshot_of(policy_hash=None),
        "environment_digest_missing": {**snapshot_of(), "identity": {k: v for k, v in identity().items() if k != "environment_digest"}},
        "environment_digest_not_text": snapshot_of(environment_digest=7),
        "environment_digest_empty_passes_the_identity_check": snapshot_of(environment_digest=""),
        "interpreter_missing": {**snapshot_of(), "identity": {k: v for k, v in identity().items() if k != "interpreter"}},
        "interpreter_empty": snapshot_of(interpreter=""), "interpreter_not_text": snapshot_of(interpreter=7)}
    for name, value in shapes.items():
        t = system(api, Declaring(snapshot_value=value))
        out["snapshot_" + name] = {**obs(t, go, t), **inspections(t)}
    # M7 test_a_missing_trusted_interpreter_is_refused_before_any_child...: the adapter refuses in `snapshot`
    t = system(api, Declaring(snapshot_error=api.ContractError("Trusted replay interpreter is not a file: /fixture/missing")))
    out["snapshot_refusal_propagates_nothing_recorded"] = {**obs(t, go, t), **inspections(t)}
    t = system(api, Declaring(snapshot_error=OSError("snapshot failed")))
    out["snapshot_os_error_propagates"] = {**obs(t, go, t), **inspections(t)}
    # M7 OtherHost: the same execution, claims and policy under another platform is a new inspection
    t = system(api, Declaring(ident=identity(platform="fixture-other-host")))
    other_host = go(t)
    out["other_host_platform_recorded"] = {"platform": other_host["inspector"]["platform"], "new_id": other_host["id"] != row["id"]}
    return out


# ---- E4 -----------------------------------------------------------------------------------------------------------------
def with_report(**changes):
    """A report edit: the default report with the given top-level keys replaced."""
    return lambda report: {**report, **changes}


def with_context(**changes):
    return lambda report: {**report, "context": {**report["context"], **changes}}


def e4_inspect_checks(api, ws):
    out = {}
    # the order of the checks on the report
    def unknown(report):
        return {**report, "findings": [{"claim": CLAIMS[0], "state": "CLEAN", "cause": "x"}]}

    cases = {
        "unknown_state": dict(report_edit=unknown),
        "unknown_state_before_policy": dict(report_edit=lambda r: with_report(policy_hash="z" * 64)(unknown(r))),
        "policy_mismatch": dict(report_edit=with_report(policy_hash="b" * 64)),
        "policy_mismatch_before_environment": dict(report_edit=lambda r: with_context(environment_digest="f" * 64)(with_report(policy_hash="b" * 64)(r))),
        "environment_digest_mismatch": dict(report_edit=with_context(environment_digest="f" * 64)),
        "interpreter_mismatch": dict(report_edit=with_context(interpreter="/other/python")),
        "environment_and_interpreter_both_mismatch": dict(report_edit=with_context(environment_digest="f" * 64, interpreter="/other/python")),
        "environment_digest_absent_from_context": dict(report_edit=lambda r: {**r, "context": {k: v for k, v in r["context"].items() if k != "environment_digest"}}),
        "interpreter_absent_from_context": dict(report_edit=lambda r: {**r, "context": {k: v for k, v in r["context"].items() if k != "interpreter"}}),
        "report_without_findings": dict(report_edit=lambda r: {k: v for k, v in r.items() if k != "findings"}),
        "report_without_policy_hash": dict(report_edit=lambda r: {k: v for k, v in r.items() if k != "policy_hash"}),
        "report_without_context": dict(report_edit=lambda r: {k: v for k, v in r.items() if k != "context"}),
        "report_without_context_but_absent_workspace": dict(report_edit=lambda r: {
            "policy_hash": POLICY, "findings": [{"claim": None, "state": "error", "cause": "workspace directory does not exist"}]})}
    for name, kwargs in cases.items():
        s = system(api, Declaring(**kwargs))
        out["report_" + name] = {**obs(s, go, s), **inspections(s)}
    # the absent workspace: the environment, interpreter and project checks are skipped; the policy and the state are not
    def absent(extra=None, **ctx):
        return lambda r: {**r, "context": {**r["context"], **ctx}, "findings": [
            {"claim": None, "state": "error", "cause": "workspace directory does not exist"}], **(extra or {})}

    s = system(api, Declaring(report_edit=absent(environment_digest="f" * 64, interpreter="/other/python")))
    out["absent_workspace_skips_environment_and_interpreter"] = {**obs(s, go, s), **inspections(s)}
    s = system(api, Declaring(report_edit=absent(extra={"policy_hash": "b" * 64})))
    out["absent_workspace_still_checks_policy"] = {**obs(s, go, s), **inspections(s)}
    s = system(api, Declaring(report_edit=lambda r: {**r, "findings": [{"claim": CLAIMS[0], "state": "error", "cause": "other cause"}],
                                                      "context": {**r["context"], "interpreter": "/other/python"}}))
    out["another_error_cause_is_not_absent"] = {**obs(s, go, s), **inspections(s)}
    s = system(api, Declaring(report_edit=lambda r: {**r, "findings": [{"claim": CLAIMS[0], "state": "checked", "cause": "workspace directory does not exist"},
                                                                        {"claim": CLAIMS[1], "state": "checked"}],
                                                      "context": {**r["context"], "interpreter": "/other/python"}}))
    out["absent_cause_on_a_checked_first_finding_skips_too"] = {**obs(s, go, s), **inspections(s)}
    s = system(api, Declaring(report_edit=lambda r: {**r, "findings": [{"claim": CLAIMS[0], "state": "checked", "cause": "ok"},
                                                                        {"claim": None, "state": "error", "cause": "workspace directory does not exist"}],
                                                      "context": {**r["context"], "interpreter": "/other/python"}}))
    out["absent_cause_only_counts_as_the_first_finding"] = {**obs(s, go, s), **inspections(s)}
    s = system(api, Declaring(report_edit=lambda r: {**r, "findings": []}))
    out["no_findings_with_claims_is_no_claims"] = {**obs(s, go, s), **inspections(s)}
    # the project context (INV-PROJECT-EVIDENCE-001): handed to the adapter exactly as keyed
    project = {"digest": "9" * 64, "contexts": [{"name": "app", "cwd": "src"}]}
    pident = identity(project={"digest": "9" * 64})
    s = system(api, Profiled(ident=pident, project=project))
    row = go(s)
    out["project_forwarded_exactly_as_keyed"] = {"call": s.inspector.calls[1], "context_project_digest": row["context"]["project_digest"],
                                                 "inspector_has_project": row["inspector"]["project"], "id_is_the_v4_key": row["id"] == key(s, ident=pident)}
    s = system(api, Keywords(ident=pident, project=project))
    go(s)
    out["project_forwarded_to_a_keywords_adapter"] = {"call": s.inspector.calls[1]}
    s = system(api, Legacy(ident=pident, project=project))
    out["project_with_an_adapter_that_does_not_take_it_is_a_type_error"] = {**obs(s, go, s), **inspections(s)}
    s = system(api, Profiled())
    go(s)
    out["no_project_no_keyword"] = {"call": s.inspector.calls[1]}
    for name, (ident, proj) in {
            "project_without_identity_project": (identity(), project),
            "identity_project_not_a_dict": (identity(project="9" * 64), project),
            "project_not_a_dict": (pident, ["digest"]),
            "project_digest_not_text": (identity(project={"digest": 9}), {"digest": 9}),
            "project_digest_differs": (identity(project={"digest": "8" * 64}), project),
            "project_without_digest": (identity(project={"digest": "9" * 64}), {"contexts": []}),
            "identity_project_without_digest": (identity(project={}), project),
            "project_empty_dict": (identity(project={}), {})}.items():
        s = system(api, Profiled(ident=ident, project=proj))
        out["project_refused_" + name] = {**obs(s, go, s), **inspections(s)}
    s = system(api, Profiled(ident=pident, project=project, report_edit=with_context(project_digest="8" * 64)))
    out["project_replayed_under_another_context"] = {**obs(s, go, s), **inspections(s)}
    s = system(api, Profiled(ident=pident, project=project, report_edit=lambda r: {**r, "context": {k: v for k, v in r["context"].items() if k != "project_digest"}}))
    out["project_digest_absent_from_the_report_context"] = {**obs(s, go, s), **inspections(s)}
    s = system(api, Profiled(ident=pident, project=project, report_edit=lambda r: {**with_context(project_digest="8" * 64)(r), "findings": [
        {"claim": None, "state": "error", "cause": "workspace directory does not exist"}]}))
    out["project_check_skipped_for_the_absent_workspace"] = {**obs(s, go, s), **inspections(s)}
    s = system(api, Profiled(ident=pident, project=project, report_edit=lambda r: {**r, "policy_hash": "b" * 64, "context": {**r["context"], "project_digest": "8" * 64}}))
    out["policy_before_project"] = {**obs(s, go, s), **inspections(s)}
    s = system(api, Profiled(ident=pident, project=project, report_edit=lambda r: with_context(project_digest="8" * 64, interpreter="/other/python")(r)))
    out["project_before_environment"] = {**obs(s, go, s), **inspections(s)}
    # progress: before anything is read and again before the row; handed only to an adapter that declares it
    for name, inspector in (("declaring", Declaring()), ("legacy", Legacy()), ("keywords", Keywords()), ("profiled", Profiled())):
        s = system(api, inspector)
        marks = []
        row = go(s, progress=lambda point, m=marks, t=s: (m.append([point, t.store.count, len(t.inspector.calls)])))
        out["progress_" + name] = {"marks": marks, "inspector_call": s.inspector.calls[1], "recorded": row["id"] == key(s)}
    s = system(api, Declaring())
    go(s)
    out["progress_none_is_the_previous_behaviour"] = {"inspector_call": s.inspector.calls[1]}
    for name, point in (("start", "inspection_start"), ("end", "inspection_end")):
        s = system(api, Declaring())
        marks = []

        def stop(p, m=marks, at=point, t=s):
            m.append([p, t.store.count, len(t.inspector.calls)])
            if p == at:
                raise api.ContractError("ownership lost at " + p)
        out["progress_refusal_at_" + name] = {**obs(s, go, s, progress=stop), "marks": marks, **inspections(s)}
    s = system(api, Declaring())
    marks = []

    def stop_base(p, m=marks):
        m.append(p)
        raise Stop("cancelled")
    out["progress_base_exception_at_start"] = {**obs(s, go, s, progress=stop_base), "marks": marks, **inspections(s)}
    s2 = system(api, Declaring())
    cache_hit_marks = []
    go(s2)
    go(s2, progress=lambda p: cache_hit_marks.append(p))
    out["progress_on_a_cache_hit_is_start_only"] = {"marks": cache_hit_marks, "inspector_calls": [c[0] for c in s2.inspector.calls]}
    # an inspector that raises
    for name, error in (("contract_error", api.ContractError("replay refused")), ("os_error", OSError("boom")),
                        ("key_error", KeyError("missing"))):
        s = system(api, Declaring(run_error=error))
        out["inspector_raises_" + name] = {**obs(s, go, s), **inspections(s)}
    # the concurrent winner: another writer takes the key between the cache read and the write
    s = system(api, Declaring())
    winner = {"id": key(s), "marker": "winner", "verdict": "all_checked"}
    s.inspector.on_run = lambda: put(s.base, api.BUCKET, key(s), winner)
    result = go(s)
    out["concurrent_winner_is_returned_unchanged"] = {"returned_is_the_winner": result == winner, "stored": get(s.base, api.BUCKET, key(s)),
                                                       "rows": len(scan(s.base, api.BUCKET)), "notices": len(scan(s.base, api.NOTICES))}
    return out


# ---- E5 -----------------------------------------------------------------------------------------------------------------
class Guard:
    """LABELLED. The caller's ownership check taken INSIDE the ledger's own transactions: it receives the open transaction
    (it reads through it, never opening one of its own) and raises `error` on the calls named by `fail_on`."""

    def __init__(self, s, fail_on=(), error=None):
        self.s, self.fail_on, self.error, self.calls = s, set(fail_on), error, []

    def __call__(self, tx):
        n = len(self.calls) + 1
        seen = len(tx.scan(self.s.api.BUCKET))
        self.calls.append({"n": n, "rows_visible": seen, "transactions_opened_so_far": self.s.store.count,
                           "inspector_calls": len(self.s.inspector.calls)})
        if n in self.fail_on:
            raise self.error


def e5_fence_recording(api, ws):
    out = {}
    # no guard keeps the previous contract, including its transaction count
    s = system(api)
    go(s)
    out["no_guard_miss_two_transactions"] = inspections(s)
    go(s)
    out["no_guard_hit_one_more_transaction"] = inspections(s)
    s = system(api)
    guard = Guard(s)
    go(s, guard=guard)
    out["guard_miss_called_before_the_read_and_before_the_write"] = {"guard": guard.calls, **inspections(s)}
    guard2 = Guard(s)
    go(s, guard=guard2)
    out["guard_hit_called_once_before_the_cached_row"] = {"guard": guard2.calls, **inspections(s)}
    # the guard's refusal is the CALLER's failure, raised unchanged: no row, no notice
    for name, fail_on in (("on_the_cache_read", (1,)), ("before_the_write", (2,))):
        s = system(api)
        error = api.ContractError("lease no longer held " + name)
        guard = Guard(s, fail_on, error)
        before = state(s)
        try:
            go(s, guard=guard)
            raised, same = None, None
        except Exception as exc:
            raised, same = type(exc).__name__, exc is error
        out["guard_refusal_" + name] = {"raised": raised, "same_object": same, "guard": guard.calls, "unchanged": state(s) == before,
                                        "rows": state(s)["rows"], **inspections(s)}
    # a cache hit is a publication: the fence refuses it too
    s = system(api)
    go(s)
    error = api.ContractError("lease no longer held on a hit")
    guard = Guard(s, (1,), error)
    before = state(s)
    out["guard_refusal_on_a_cache_hit"] = {**obs(s, go, s, guard=guard), "guard": guard.calls, "unchanged": state(s) == before, **inspections(s)}
    # the owner's guard sees the winner between read and write: the second call refuses, nothing is written
    s = system(api)
    s.inspector.on_run = lambda: put(s.base, api.BUCKET, key(s), {"id": key(s), "marker": "winner", "verdict": "all_checked"})
    error = api.ContractError("lease lost while replaying")
    guard = Guard(s, (2,), error)
    out["guard_refusal_beats_the_concurrent_winner"] = {**obs(s, go, s, guard=guard), "guard": guard.calls,
                                                         "winner_kept": get(s.base, api.BUCKET, key(s))["marker"]}
    # a guard that is a BaseException refusal
    for name, fail_on in (("on_the_cache_read", (1,)), ("before_the_write", (2,))):
        s = system(api)
        error = Stop("cancelled " + name)
        guard = Guard(s, fail_on, error)
        try:
            go(s, guard=guard)
            raised, same = None, None
        except (Exception, Stop) as exc:
            raised, same = type(exc).__name__, exc is error
        out["guard_base_exception_" + name] = {"raised": raised, "same_object": same, "guard": guard.calls, "rows": state(s)["rows"],
                                               **inspections(s)}
    # the guard does not stop a recording failure from being a notice, and a refusal that is not the guard's is a notice
    s = system(api, fail_on=(2,), error=OSError("write failed"))
    guard = Guard(s)
    out["store_failure_with_a_guard_passing_is_a_notice"] = {**obs(s, go, s, guard=guard), "guard": guard.calls}
    # a guard that raised once but whose exception is swallowed by the caller never reaches the ledger as a refusal
    s = system(api)
    refusals = []

    def swallowing(tx):
        refusals.append(len(refusals) + 1)
        try:
            raise api.ContractError("handled inside the guard")
        except api.ContractError:
            return None
    row = go(s, guard=swallowing)
    out["guard_that_swallows_its_own_failure_passes"] = {"calls": refusals, "recorded": row["id"] == key(s)}
    # M7 test_recording_failure_is_a_named_notice_not_a_success
    s = system(api, fail_on=(2,), error=OSError("Explicit ledger write failure fixture"))
    result = obs(s, go, s)
    notices = scan(s.base, api.NOTICES)
    cause = None
    try:
        s2 = system(api, fail_on=(2,), error=OSError("Explicit ledger write failure fixture"))
        go(s2)
    except Exception as exc:
        cause = {"type": type(exc.__cause__).__name__, "context": type(exc.__context__).__name__}
    out["recording_failure_is_a_named_notice"] = {**result, "notices": notices, "chained": cause, "rows": len(scan(s.base, api.BUCKET)),
                                                  "notice_id_is_the_digest": notices[0]["id"] == api.digest([key(s), "recording_failed"]),
                                                  **inspections(s)}
    # the reason is bounded to 300 characters of the message
    s = system(api, fail_on=(2,), error=OSError("x" * 900 + CANARY))
    result = obs(s, go, s)
    out["recording_failure_reason_is_truncated"] = {**result, "reason_length": len(scan(s.base, api.NOTICES)[0]["reason"]),
                                                    "canary_in_notice": CANARY in json.dumps(scan(s.base, api.NOTICES))}
    s = system(api, fail_on=(2,), error=api.ContractError("a ContractError from the store"))
    out["recording_failure_by_a_contract_error_is_a_notice_too"] = {**obs(s, go, s), "notices": scan(s.base, api.NOTICES)}
    s = system(api, fail_on=(2,), error=ValueError(""))
    out["recording_failure_with_an_empty_message"] = {**obs(s, go, s), "notices": scan(s.base, api.NOTICES)}
    # the notice that cannot be written: the ContractError still replaces the secondary failure
    s = system(api, fail_on=(2, 3), error=OSError("ledger is down"))
    out["notice_write_failure_still_raises_the_contract_error"] = {**obs(s, go, s), "notices": len(scan(s.base, api.NOTICES)),
                                                                    "rows": len(scan(s.base, api.BUCKET)), **inspections(s)}
    s = system(api, fail_on=(2, 3), error=OSError("ledger is down"))
    try:
        go(s)
    except Exception as exc:
        out["notice_write_failure_chain"] = {"raised": type(exc).__name__, "cause": type(exc.__cause__).__name__,
                                             "context": type(exc.__context__).__name__}
    # a store that fails on the cache read: nothing is wrapped, no notice
    s = system(api, fail_on=(1,), error=OSError("store unavailable"))
    out["cache_read_failure_is_raw_not_a_notice"] = {**obs(s, go, s), "notices": len(scan(s.base, api.NOTICES)), **inspections(s)}
    # the same inspection after a recording failure is recorded and the notice stays (never cleaned)
    s = system(api, fail_on=(2,), error=OSError("write failed"))
    attempt(go, s)
    row = go(s)
    out["retry_after_a_recording_failure_records_the_row"] = {"row_id_is_the_key": row["id"] == key(s), "rows": len(scan(s.base, api.BUCKET)),
                                                              "notices_kept": len(scan(s.base, api.NOTICES)), **inspections(s)}
    # a second failure of the same inspection overwrites the same notice id
    s = system(api, fail_on=(2,), error=OSError("write failed"))
    attempt(go, s)
    first = scan(s.base, api.NOTICES)
    s.store.count = 0
    s.store.fail_on = {2}
    attempt(go, s)
    out["the_same_failure_twice_is_one_notice"] = {"first": len(first), "after": len(scan(s.base, api.NOTICES))}
    # a recording failure keeps the verdict and the denominator it would have recorded
    s = system(api, Declaring(states=["checked", "not_checked"]), fail_on=(2,), error=OSError("write failed"))
    attempt(go, s)
    notice = scan(s.base, api.NOTICES)[0]
    out["notice_carries_the_verdict_and_denominator"] = {k: notice[k] for k in ("verdict", "denominator", "reason")}
    # the previous behaviour of the transaction on success: one write, the row, no notice
    s = system(api)
    row = go(s)
    out["success_writes_one_row_and_no_notice"] = {"rows": len(scan(s.base, api.BUCKET)), "notices": len(scan(s.base, api.NOTICES))}
    return out


# ---- E6 -----------------------------------------------------------------------------------------------------------------
def e6_require_all_checked(api, ws):
    out = {}
    # M7 test_ledger_binds...: the consumer's reads
    s = system(api, Declaring(states=["checked", "not_checked"]))
    incomplete = go(s)
    good_system = system(api, Declaring(states=["checked", "checked"]))
    checked = go(good_system)

    def req(system_, row_id, *args, **kwargs):
        with system_.base.transaction() as tx:
            try:
                return {"value": system_.svc.require_all_checked(tx, row_id, *args, **kwargs)}
            except (Exception, Stop) as exc:
                result = {"raised": type(exc).__name__, "message": str(exc)[:400]}
                for name in ("reason_code", "field"):
                    if hasattr(exc, name):
                        result[name] = getattr(exc, name)
                return result

    def watch(system_, row_id, *args, **kwargs):
        before = state(system_)
        result = req(system_, row_id, *args, **kwargs)
        after = state(system_)
        return {**result, "nothing_written": before["store"] == after["store"], "before": before, "after": after}

    out["incomplete_is_refused_with_the_counts"] = watch(s, incomplete["id"])
    out["all_checked_returns_the_stored_row"] = {**watch(good_system, checked["id"]), "is_the_row": req(good_system, checked["id"])["value"] == checked}
    out["policy_and_binding_both_match"] = watch(good_system, checked["id"], policy_hash=checked["policy_hash"],
                                                 binding={"task_id": "task-1", "source_revision": REV})
    out["missing_row"] = watch(good_system, "nope")
    out["another_policy"] = watch(good_system, checked["id"], policy_hash="f" * 64)
    out["another_execution_or_revision"] = watch(good_system, checked["id"], binding={"source_revision": "e" * 40})
    out["binding_key_not_in_the_row"] = watch(good_system, checked["id"], binding={"no_such_key": 1})
    out["binding_key_with_a_none_value_matches_an_absent_key"] = watch(good_system, checked["id"], binding={"no_such_key": None})
    out["binding_empty_dict_passes"] = {"is_the_row": req(good_system, checked["id"], binding={})["value"] == checked}
    out["binding_partial_mismatch_among_matches"] = watch(good_system, checked["id"], binding={"task_id": "task-1", "attempt": 2})
    out["binding_owner_none_matches"] = {"is_the_row": req(good_system, checked["id"], binding={"base": BASE, "tree": TREE})["value"] == checked}
    out["policy_none_skips_the_policy_check"] = {"is_the_row": req(good_system, checked["id"], policy_hash=None)["value"] == checked}
    out["order_missing_before_policy"] = watch(good_system, "nope", policy_hash="f" * 64, binding={"source_revision": "e" * 40})
    out["order_policy_before_binding"] = watch(good_system, checked["id"], policy_hash="f" * 64, binding={"source_revision": "e" * 40})
    out["order_binding_before_verdict"] = watch(s, incomplete["id"], binding={"source_revision": "e" * 40})
    out["order_policy_before_verdict"] = watch(s, incomplete["id"], policy_hash="f" * 64)
    out["incomplete_with_matching_policy_and_binding"] = watch(s, incomplete["id"], policy_hash=incomplete["policy_hash"], binding={"task_id": "task-1"})
    # every verdict's refusal text
    texts = {}
    for name, states in (("no_claims", []), ("all_unchecked", ["not_checked", "not_checked"]), ("mixed_states", ["checked", "missing", "unknown",
                         "error", "replay_failed", "flake_pattern", "verified_mismatch", "not_checked"]),
                         ("flake_only", ["flake_pattern"]), ("one_missing", ["missing"])):
        t = system(api, Declaring(states=states))
        row = go(t, claims=[dict(CLAIMS[0], id="c%d" % i) for i in range(len(states))])
        texts[name] = {"verdict": row["verdict"], **watch(t, row["id"])}
    out["verdict_texts"] = texts
    # a hand-written row (LABELLED: a row no honest call path writes) for the shapes the message reads
    manual = system(api)
    put(manual.base, api.BUCKET, "manual", {"id": "manual", "policy_hash": POLICY, "binding": {"task_id": "t"}, "verdict": "incomplete",
                                            "denominator": {"checked": 0, "not_checked": 0, "claims": 0}})
    out["manual_row_with_only_zero_counts"] = watch(manual, "manual")
    put(manual.base, api.BUCKET, "manual2", {"id": "manual2", "policy_hash": POLICY, "binding": {"task_id": "t"}, "verdict": "incomplete",
                                             "denominator": {"claims": 3, "missing": 2, "checked": 1}})
    out["manual_row_counts_in_row_order_and_claims_excluded"] = watch(manual, "manual2")
    put(manual.base, api.BUCKET, "manual3", {"id": "manual3", "policy_hash": POLICY, "binding": {"task_id": "t"}, "verdict": "all_checked", "denominator": {}})
    out["manual_all_checked_ignores_the_denominator"] = {"is_the_row": req(manual, "manual3")["value"]["id"] == "manual3"}
    put(manual.base, api.BUCKET, "manual4", {"id": "manual4", "verdict": "all_checked", "denominator": {}})
    out["manual_row_without_a_policy_hash"] = {"no_check": req(manual, "manual4"), "with_check": req(manual, "manual4", policy_hash=POLICY)}
    put(manual.base, api.BUCKET, "manual5", {"id": "manual5", "policy_hash": POLICY, "verdict": "all_checked", "denominator": {}})
    out["manual_row_without_a_binding_is_a_key_error_only_when_one_is_named"] = {
        "no_binding_named": req(manual, "manual5"), "binding_named": req(manual, "manual5", binding={"task_id": "t"})}
    # the refusal text is built before `require` runs: a row without a denominator is a KeyError even when all_checked
    put(manual.base, api.BUCKET, "manual7", {"id": "manual7", "policy_hash": POLICY, "binding": {}, "verdict": "all_checked"})
    out["manual_all_checked_row_without_a_denominator_is_a_key_error"] = req(manual, "manual7")
    put(manual.base, api.BUCKET, "manual6", {"id": "manual6", "policy_hash": POLICY, "binding": {}, "denominator": {}})
    out["manual_row_without_a_verdict_is_a_key_error"] = req(manual, "manual6")
    # the consumer needs neither the inspector nor the clock; arguments after the id are keyword-only
    bare = SimpleNamespace(base=good_system.base, svc=api.EvidenceInspections(good_system.store, None))
    out["no_inspector_is_needed"] = {"is_the_row": req(bare, checked["id"])["value"] == checked}
    out["policy_hash_is_keyword_only"] = req(good_system, checked["id"], POLICY)
    out["unknown_keyword_is_refused"] = req(good_system, checked["id"], policy=POLICY)
    out["reads_the_owned_bucket_only"] = {"bucket": api.BUCKET, "notices": api.NOTICES}
    # a notice with the inspection id is never a row
    notice_system = system(api, fail_on=(2,), error=OSError("write failed"))
    attempt(go, notice_system)
    notice_id = scan(notice_system.base, api.NOTICES)[0]["id"]
    out["a_notice_is_not_an_inspection_row"] = watch(notice_system, notice_id)
    out["inspection_row_of_another_store_is_missing"] = watch(system(api), checked["id"])
    # M7 test_executor_inspects_implementation_claims... is the executor family
    out["m7_tests"] = {
        "test_policy_and_claims_are_closed_and_typed": {"unreachable": "the domain.evidence validators: S5 domain.evidence moves; the adapter policy is the adapter family"},
        "test_file_claims_are_checked_against_the_workspace_never_the_inspector_cwd": {"unreachable": "EvidenceInspector.inspect_file (real files; the adapter family)"},
        "test_command_claims_replay_only_by_policy_and_keep_raw_bytes": {"unreachable": "EvidenceInspector.inspect_command (real child processes; the adapter family)"},
        "test_python_replays_run_the_trusted_interpreter_against_the_candidate_source": {"unreachable": "real subprocess and the trusted interpreter (the adapter family); the snapshot identity is e3"},
        "test_the_profile_metadata_module_replays_only_as_its_exact_argv": {"unreachable": "authorized() on the packaged policy and a real replay (the adapter family)"},
        "test_a_missing_trusted_interpreter_is_refused_before_any_child_and_never_recorded_as_success": {
            "unreachable": "the real EvidenceInspector and the executor (the adapter and executor families); the application side is e3 snapshot_refusal_propagates_nothing_recorded"},
        "test_deadline_and_budgets_are_enforced_and_termination_is_recorded": {"unreachable": "real child processes and deadlines (the adapter family)"},
        "test_real_capture_*": {"unreachable": "ei._capture and ProcessTree (the adapter family)"},
        "test_ledger_binds_the_inspection_to_the_execution_and_never_records_a_failure_as_success": {
            "unreachable": "its postgres parameter needs PostgreSQL (the disposable fixture) and the memory half drives the real adapter; the ledger half is e2/e3/e6"},
        "test_recording_failure_is_a_named_notice_not_a_success": {"unreachable": "drives the real adapter; the notice is e5 recording_failure_is_a_named_notice"},
        "test_executor_inspects_implementation_claims_in_the_workspace": {"unreachable": "the executor family"},
        "test_read_only_runs_receive_a_host_composed_review_context_and_implementation_runs_do_not": {"unreachable": "the executor family"}}
    return out


GROUPS = (("e1_forwards_progress", e1_forwards_progress), ("e2_binding", e2_binding), ("e3_inspect_identity", e3_inspect_identity),
          ("e4_inspect_checks", e4_inspect_checks), ("e5_fence_recording", e5_fence_recording),
          ("e6_require_all_checked", e6_require_all_checked))


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
