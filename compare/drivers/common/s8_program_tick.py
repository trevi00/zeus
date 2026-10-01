"""Shared S8 scenario steps (`research.program_tick`): `ProgramRunner.run`/`tick` of M7 `adapters/research_program.py`
and the `ResearchProgram` calls they make (`application/research_program.py`), characterized BEFORE step 3 moves them
(DESIGN-s8 §1 V5, §2; TRACE-s8 §2, rows T1-T13).

- **t01_repository_mismatch** (T1): a runner naming another root's identity refuses `repository_mismatch` before any
  effect (M7 `test_r1_wrong_repository_...`), for `tick` and `run`; the registered root continues; an empty identity.
- **t02_not_reserved** (T2): paused, busy (no fetch), not due, completed, blocked, past its deadline, an unknown
  program, an invalid intent: the `tick_skipped` receipts and the store untouched.
- **t13_run** (T13): `ticks` 0, -1, True, "1", 1.0, None and an invalid intent refuse before any reservation; a valid
  `run` stops at the first not-reserved, failed or unknown result and continues past a rejected one.
- **t03_collection** (T3/T4): a degraded feed, both feeds down, a policy-paused feed (not degraded), the real
  `ResearchSources` whose evaluator cannot complete, local verification failures, normalized and bounded feed items, an
  unreadable or tight budget.
- **t05_no_candidate** (T5): `complete_cycle`; the adoption is never consumed by a cycle that selects nothing.
- **t06_capture_failure** (T6/T7): every capture refusal and unexpected exception: `fail_cycle(stage="capture")`, the
  recorded snapshot of a github candidate with each `github_detail` outcome.
- **t08_pre_council** (T8/T8b): a failure at EACH of `capture_record`, `manifest_derive`, `manifest_artifact`,
  `manifest_file`, `council_start` (labelled faults; `manifest_file` is a real OS failure), once more with `fail_cycle`
  itself failing (`recorded: False`, `state: unknown`) and with the log failing too.
- **t09_council** (T9/T10): the council raises before writing a row, raises after writing it (the row is
  authoritative), returns rejected, accepted, unknown, exhausted, running, with a mismatched or no row.
- **t11_investigation** (T11): an investigation candidate's dispatch outcome (accepted, rejected, unknown, capture
  failure, mismatched row, the opt-out program, the replay, no headroom, the dispatch row missing).
- **t12_report** (T12): a report write failure leaves `report: None`.
- **m7_mirror**: the M7 tests that drive a tick and are not covered above (two ticks, the monitor projection).

Layer: harness (never shipped)

Every double is in `s8_research_program` and LABELLED; this module never runs a provider, a network call or a host
tool except the real `git` of the fixture repository. The council is a STAND-IN (it writes the scripted RUNS row);
every injected fault is labelled at its injection point. A case unreachable with the doubles is `{"unreachable": ...}`.
"""

from __future__ import annotations

import contextlib
import json
from types import SimpleNamespace

import s8_research_program as R

PATH, REF = R.CAPTURE_PATH, R.CAPTURE_REF


def tick_case(env, **kw):
    """One tick: its receipt (or refusal) and the standard observation."""
    result = R.call(env.ws, R.tick, env)
    return {"result": result, **R.observe(env, **kw)}


def snapshot_of(env, revision, path=PATH):
    """The capture document the commit holds at `path` (parsed), or None."""
    shown = R.git(env.root, "show", revision + ":" + path, check=False)
    return json.loads(shown.stdout) if shown.returncode == 0 else None


def captured(env):
    """The snapshot document of cycle 1's recorded capture, if any."""
    receipts = R.view(env).get("cycle_receipts") or []
    capture = receipts[0].get("capture") if receipts else None
    return None if not capture else snapshot_of(env, capture["revision"], capture["path"])


def with_capture_file(env_base, root, head):
    """A real second commit that already holds the capture path (so `capture_path_exists` is reached)."""
    path = root / PATH
    path.parent.mkdir(parents=True)
    path.write_text("{}\n", encoding="utf-8")
    import os
    os.chmod(path, 0o644)
    R.git(root, "add", PATH)
    R.git(root, "commit", "-q", "-m", "capture path present at base")
    return R.out(root, "rev-parse", "HEAD")


def broken(error):
    """LABELLED fault: a callable that raises `error` (an instance)."""
    def raiser(*args, **kwargs):
        raise error
    return raiser


# ---- T1 ------------------------------------------------------------------------------------------------------------------
def t01_repository_mismatch(api, ws):
    results = {}
    env = R.build(api, ws, "t01")
    R.registered(env)
    other = R.clone(env.base, env.root)
    wrong = R.build(api, ws, "t01w", store=env.store, clock=env.clock, root=other, head=env.head,
                    identity=R.OTHER_IDENTITY)
    before = R.snapshot(env.store)
    tick, run = (R.guarded(ws, env, wrong.runner.tick, R.PROGRAM, intent=R.INTENT),
                 R.guarded(ws, env, wrong.runner.run, R.PROGRAM, 2, intent=R.INTENT))
    results["wrong_root"] = {
        "tick": tick, "run": run, "store_unchanged": R.snapshot(env.store) == before,
        "feeds_fetched": wrong.sources.calls, "council_calls": len(wrong.council.manifests),
        "refs_registered_root": sorted(R.git_snapshot(env.root)["refs"]),
        "refs_other_root": sorted(R.git_snapshot(other)["refs"]),
        "log_or_files_written": (wrong.runtime / "research-program").exists(), "program": R.view(env)}
    results["registered_root_continues"] = tick_case(env)
    # An empty identity (the runner's default `repository=""`) is another identity.
    empty = R.build(api, ws, "t01e", identity="")
    R.registered(empty)
    results["empty_identity"] = {**tick_case(empty)}
    return results


# ---- T2 and T13 ----------------------------------------------------------------------------------------------------------
def t02_not_reserved(api, ws):
    results = {}
    env = R.build(api, ws, "t02p")
    R.registered(env, resume=False)
    results["paused"] = tick_case(env)
    env = R.build(api, ws, "t02b")
    R.registered(env)
    env.programs.reserve_cycle(R.PROGRAM, R.IDENTITY)  # a crashed owner: reserved, never finished
    results["busy"] = tick_case(env)
    env = R.build(api, ws, "t02n")
    R.registered(env, max_cycles=5, max_adoptions=0)
    first = tick_case(env)
    results["not_due"] = {"first": first, "second": tick_case(env)}
    env = R.build(api, ws, "t02c")
    R.registered(env, max_cycles=1, max_adoptions=0)
    done = tick_case(env)
    results["program_completed"] = {"first": done, "second": tick_case(env)}
    env = R.build(api, ws, "t02k", status="unknown")
    R.registered(env)
    blocked = tick_case(env)
    results["program_blocked"] = {"first": blocked, "second": tick_case(env)}
    env = R.build(api, ws, "t02d", clock=R.Clock("2031-01-01T00:00:00+00:00"))
    R.registered(env)
    results["deadline_expired"] = tick_case(env)
    env = R.build(api, ws, "t02u")
    results["unknown_program"] = {"result": R.guarded(ws, env, env.runner.tick, "nope", intent=R.INTENT),
                                  "source_calls": env.sources.calls}
    env = R.build(api, ws, "t02i")
    R.registered(env)
    results["invalid_intent"] = {
        label: {**R.guarded(ws, env, env.runner.tick, R.PROGRAM, intent=intent), "source_calls": list(env.sources.calls)}
        for label, intent in (("empty", ""), ("none", None), ("unknown", "bogus"))}
    return results


def t13_run(api, ws):
    results = {}
    env = R.build(api, ws, "t13i")
    R.registered(env)
    results["ticks_invalid"] = {
        label: R.guarded(ws, env, env.runner.run, R.PROGRAM, ticks, intent=R.INTENT)
        for label, ticks in (("zero", 0), ("negative", -1), ("true", True), ("false", False), ("string", "1"),
                             ("float", 1.0), ("none", None))}
    results["intent_invalid"] = {
        label: R.guarded(ws, env, env.runner.run, R.PROGRAM, 1, intent=intent)
        for label, intent in (("empty", ""), ("none", None), ("unknown", "bogus"))}
    results["ticks_checked_before_intent"] = R.guarded(ws, env, env.runner.run, R.PROGRAM, 0, intent="bogus")
    results["after_refusals"] = {"store": R.snapshot(env.store), "feeds_fetched": env.sources.calls,
                                 "program": R.view(env)}
    env = R.build(api, ws, "t13c")
    R.registered(env, max_cycles=5, max_adoptions=0)
    two = R.call(ws, env.runner.run, R.PROGRAM, 2, intent=R.INTENT)
    results["stops_at_not_reserved"] = {"result": two, **R.observe(env)}
    env.clock.advance(7200)
    env.programs.reserve_cycle(R.PROGRAM, R.IDENTITY)  # a crashed owner: reserved, never finished
    env.sources.calls.clear()
    results["stops_at_busy"] = {"result": R.call(ws, env.runner.run, R.PROGRAM, 3, intent=R.INTENT),
                                "source_calls": env.sources.calls}
    # LABELLED: `step` advances the fake time after every read so successive ticks are due.
    env = R.build(api, ws, "t13s", clock=R.Clock(step=7200))
    R.registered(env, max_cycles=3, max_adoptions=0)
    results["completes_every_tick_then_stops"] = {
        "result": R.call(ws, env.runner.run, R.PROGRAM, 5, intent=R.INTENT), **R.observe(env)}
    env = R.build(api, ws, "t13r", clock=R.Clock(step=7200))
    R.registered(env, max_cycles=3, max_adoptions=3)
    results["continues_past_rejected"] = {
        "result": R.call(ws, env.runner.run, R.PROGRAM, 3, intent=R.INTENT), **R.observe(env)}
    env = R.build(api, ws, "t13f", clock=R.Clock(step=7200))
    R.registered(env, max_cycles=3, max_adoptions=3)
    R.git(env.root, "update-ref", REF, env.head)  # LABELLED: a stale ref from an earlier attempt (capture refusal)
    results["stops_at_failure"] = {"result": R.call(ws, env.runner.run, R.PROGRAM, 3, intent=R.INTENT), **R.observe(env)}
    env = R.build(api, ws, "t13u", clock=R.Clock(step=7200), status="unknown")
    R.registered(env, max_cycles=3, max_adoptions=3)
    results["stops_at_unknown"] = {"result": R.call(ws, env.runner.run, R.PROGRAM, 3, intent=R.INTENT), **R.observe(env)}
    env = R.build(api, ws, "t13x", clock=R.Clock(step=7200), status="exhausted")
    R.registered(env, max_cycles=3, max_adoptions=3)
    results["stops_at_failed_council"] = {"result": R.call(ws, env.runner.run, R.PROGRAM, 3, intent=R.INTENT),
                                          **R.observe(env)}
    return results


# ---- T3 and T4 -----------------------------------------------------------------------------------------------------------
def t03_collection(api, ws):
    results = {}
    for label, outages in (("github_down", ("github",)), ("geeknews_down", ("geeknews",)),
                           ("both_down", ("github", "geeknews"))):
        env = R.build(api, ws, "t03-" + label, outages=outages)
        R.registered(env)
        results[label] = tick_case(env)
    for label, paused, outages in (("both_paused", {"github", "geeknews"}, ()), ("github_paused", {"github"}, ()),
                                   ("paused_and_down", {"github"}, ("geeknews",))):
        env = R.build(api, ws, "t03-" + label, outages=outages)
        R.registered(env)
        env.sources.paused = set(paused)  # LABELLED: the pressure evaluator holds these feeds
        results[label] = tick_case(env)
    # M7 `test_an_evaluator_that_cannot_complete_...`: the REAL ResearchSources whose pressure evaluation raises.
    env = R.build(api, ws, "t03-evaluator")
    R.registered(env)

    class NoFetch(api.ResearchSources):
        def fetch(self, url):  # LABELLED: any fetch is a failure of the case, never a network call
            raise AssertionError("fetched " + url)

    def unreadable():
        raise OSError("store unreadable")  # LABELLED fault: the evaluator cannot read its store
    env.runner.sources = NoFetch(api.FileArtifacts(str(env.base / "runtime" / "artifacts")),
                                 pressure=SimpleNamespace(admit=unreadable))
    results["real_sources_evaluator_cannot_complete"] = tick_case(env)
    # Local verification.
    bad = dict(R.config("0" * 40)["local_candidates"][0])
    for label, change in (("digest_mismatch", {"sha256": "0" * 64}), ("missing_at_base", {"path": "docs/research/none.md"}),
                          ("not_a_regular_blob", {"path": "docs"})):
        env = R.build(api, ws, "t03-local-" + label)
        R.registered(env, local_candidates=[{**bad, **change}])
        results["local_" + label] = tick_case(env)
    env = R.build(api, ws, "t03-local-empty")
    R.registered(env, local_candidates=[])
    results["local_none_configured"] = tick_case(env)
    env = R.build(api, ws, "t03-live-direct")
    status, items = api_collect_live(api, env)
    results["collect_live_both_down"] = {"status": status, "items": items}
    # Feed items: unsupported scheme, no url, a fragment and trailing slash (the same normalized url), long text.
    long_items = {"github": [{"url": "http://github.com/acme/insecure", "title": "postgres", "summary": "x"},
                             {"url": None, "title": "postgres", "summary": "no url"},
                             {"url": "https://GitHub.com/acme/pgtool/#readme", "title": "T" * 500,
                              "summary": "postgres " * 400},
                             {"url": "https://github.com/acme/pgtool", "title": "dup", "summary": "postgres"}],
                  "geeknews": []}
    env = R.build(api, ws, "t03-items", items=long_items)
    R.registered(env, local_candidates=[])
    results["feed_items_normalized_and_bounded"] = {**tick_case(env), "snapshot": captured(env)}
    # The machine ledger.
    for label, budget in (("budget_unreadable", R.Budget(fail=OSError("fixture: ledger unreadable"))),
                          ("budget_unreadable_value", R.Budget(fail=ValueError("fixture"))),
                          ("budget_tight", R.Budget(this_host=4, all_hosts=4)),
                          ("budget_exact", R.Budget(this_host=3, all_hosts=3))):
        env = R.build(api, ws, "t03-" + label, budget=budget)
        R.registered(env)
        results[label] = tick_case(env)
    return results


def api_collect_live(api, env):
    """M7 `test_local_verification_failure_...`'s direct `collect_live` over both feeds down."""
    sources = R.Sources(api, env.artifacts, outages=("github", "geeknews"))
    return api.collect_live(sources, intent=R.INTENT)


# ---- T5 ------------------------------------------------------------------------------------------------------------------
def t05_no_candidate(api, ws):
    results = {}
    irrelevant = {"github": [{"url": "https://github.com/acme/unrelated", "title": "x", "summary": "a game engine"}],
                  "geeknews": []}
    env = R.build(api, ws, "t05n", items=irrelevant)
    R.registered(env, local_candidates=[])
    results["no_eligible_candidate"] = tick_case(env)
    env = R.build(api, ws, "t05c")
    R.registered(env, max_cycles=3, max_adoptions=0)
    results["adoption_cap_reached"] = tick_case(env)
    env = R.build(api, ws, "t05a", items=irrelevant)
    R.registered(env, local_candidates=[], max_cycles=1, max_adoptions=1)
    nothing = tick_case(env)
    results["cycle_selecting_nothing_keeps_its_adoption"] = {"tick": nothing, "adoptions": R.view(env)["adoptions"]}
    env = R.build(api, ws, "t05f")
    R.registered(env, max_adoptions=0)
    with R.replaced(env.programs, "complete_cycle", broken(OSError("fixture: store unavailable"))):  # LABELLED fault
        results["complete_cycle_fails_propagates"] = tick_case(env)
    return results


# ---- T6 and T7 -----------------------------------------------------------------------------------------------------------
class RaisingCapture:
    """LABELLED fault: a capture whose `capture` raises `error` (an unexpected exception in the capture step)."""

    def __init__(self, error):
        self.error = error

    def capture(self, *args):
        raise self.error


def t06_capture_failure(api, ws):
    results = {}
    env = R.build(api, ws, "t06ref")
    R.registered(env)
    R.git(env.root, "update-ref", REF, env.head)  # LABELLED: a stale ref from an earlier attempt
    results["ref_exists"] = tick_case(env)
    base = ws.case("t06path")
    root, head = R.repository(base)
    head = with_capture_file(base, root, head)
    env = R.build(api, ws, "t06path-run", root=root, head=head)
    R.registered(env)
    results["path_exists_at_base"] = tick_case(env)
    env = R.build(api, ws, "t06base")
    env.head = "0" * 40  # LABELLED: a registered base that is not a commit of the repository
    R.registered(env)
    results["base_revision_missing"] = tick_case(env)
    for label, shift in (("local_source_not_regular", {"mode": "100755"}),
                         ("local_source_digest_mismatch", {"data": b"changed after discovery\n"})):
        env = R.build(api, ws, "t06-" + label)
        R.registered(env)
        # LABELLED fault: the base content seems to change between the discovery check and the capture's own check.
        env.runner.git_source = R.ShiftingSource(env.runner.git_source, after=1, **shift)
        results[label] = tick_case(env)
    for label, error in (("unexpected_runtime_error", RuntimeError("fixture: unexpected capture failure " + R.CANARY)),
                         ("unexpected_os_error", OSError("fixture: disk")),
                         ("contract_error_without_reason_code", api.ContractError("fixture contract refusal")),
                         ("capture_error_with_code", api.CaptureError("fixture_code"))):
        env = R.build(api, ws, "t06-" + label)
        R.registered(env)
        env.runner.capture = RaisingCapture(error)  # LABELLED fault: the injected capture exception
        results[label] = tick_case(env)
    env = R.build(api, ws, "t06art")
    R.registered(env)
    real_put = env.artifacts.put

    def failing_put(body, source):
        if source.startswith("research-capture:"):
            raise PermissionError("fixture: capture artifact denied " + R.CANARY)  # LABELLED fault
        return real_put(body, source)
    with R.replaced(env.artifacts, "put", failing_put):
        results["capture_artifact_put_fails"] = tick_case(env)
    env = R.build(api, ws, "t06fc")
    R.registered(env)
    R.git(env.root, "update-ref", REF, env.head)
    with R.replaced(env.programs, "fail_cycle", broken(OSError("fixture: store unavailable"))):  # LABELLED fault
        results["capture_refusal_with_fail_cycle_failing_propagates"] = tick_case(env)
    # github candidates and the detail the snapshot records.
    for label, kwargs in (("detail_raises", {}), ("detail_ok", {"detail": {"revision": "r" * 40, "readme_ref": "README.md",
                                                                          "license": "MIT", "archived": False,
                                                                          "pushed_at": R.BASE_CLOCK,
                                                                          "default_branch": "main", "fetched_at": R.BASE_CLOCK,
                                                                          "extra": "dropped"}}),
                          ("detail_not_requested", {"github_detail": False})):
        env = R.build(api, ws, "t06-github-" + label, **kwargs)
        R.registered(env, local_candidates=[])
        results["github_" + label] = {**tick_case(env), "snapshot": captured(env)}
    env = R.build(api, ws, "t06ok")
    R.registered(env)
    results["local_success_snapshot"] = {**tick_case(env), "snapshot": captured(env)}
    return results


# ---- T8 and T8b ------------------------------------------------------------------------------------------------------------
STAGES = ("capture_record", "manifest_derive", "manifest_artifact", "manifest_file", "council_start")


def inject(env, stack, stage, error):
    """The labelled fault at one pre-council stage (`manifest_file` is a REAL OS failure: a regular file where the
    manifest directory must be created)."""
    if stage == "capture_record":
        stack.enter_context(R.replaced(env.programs, "record_capture", broken(error)))
    elif stage == "manifest_derive":
        stack.enter_context(env.api.patch("derive_manifest", broken(error)))
    elif stage == "manifest_artifact":
        real_put = env.artifacts.put

        def failing_put(body, source):
            if source.startswith("research-program:"):
                raise error
            return real_put(body, source)
        stack.enter_context(R.replaced(env.artifacts, "put", failing_put))
    elif stage == "manifest_file":
        manifests = env.runtime / "research-program" / R.PROGRAM / "manifests"
        manifests.parent.mkdir(parents=True)
        manifests.write_text("a regular file where the manifest directory must be created\n", encoding="utf-8")
    else:
        stack.enter_context(R.replaced(env.programs, "record_council_start", broken(error)))


def t08_pre_council(api, ws):
    results = {}
    for stage in STAGES:
        for label, recording in (("recorded", False), ("fail_cycle_fails", True)):
            env = R.build(api, ws, "t08-%s-%s" % (stage, label))
            R.registered(env)
            with contextlib.ExitStack() as stack:
                inject(env, stack, stage, RuntimeError("fixture: " + stage + " " + R.CANARY))  # LABELLED fault
                if recording:
                    # LABELLED fault: `fail_cycle` itself fails (the store becomes unavailable at the same moment).
                    stack.enter_context(R.replaced(env.programs, "fail_cycle", broken(OSError("fixture: store unavailable"))))
                results[stage + "." + label] = tick_case(env)
            results[stage + "." + label]["reserve_again"] = R.call(ws, env.programs.reserve_cycle, R.PROGRAM, R.IDENTITY)
    # A product reason code on the exception is the recorded code (not the type name).
    for stage in ("capture_record", "council_start"):
        env = R.build(api, ws, "t08-code-" + stage)
        R.registered(env)
        with contextlib.ExitStack() as stack:
            inject(env, stack, stage, api.ProgramRefused("fixture_code"))  # LABELLED fault
            results[stage + ".reason_code"] = tick_case(env)
    # M7 FlakyStore: the store is cut at the moment the manifest artifact fails.
    store = R.FlakyStore(api.MemoryStore())
    env = R.build(api, ws, "t08-flaky", store=store)
    R.registered(env)
    real_put = env.artifacts.put

    def cut_then_fail(body, source):
        if source.startswith("research-program:"):
            store.fail = True  # LABELLED fault: the store outage
            raise PermissionError("fixture " + R.CANARY)
        return real_put(body, source)
    with R.replaced(env.artifacts, "put", cut_then_fail):
        receipt = R.call(ws, R.tick, env)
    store.fail = False
    results["flaky_store"] = {"result": receipt, **R.observe(env),
                              "reserve_again": R.call(ws, env.programs.reserve_cycle, R.PROGRAM, R.IDENTITY)}
    # The log failing too (an OSError while recording the unrecorded failure is swallowed).
    env = R.build(api, ws, "t08-logfail")
    R.registered(env)
    events_file = env.runtime / "research-program" / R.PROGRAM / "events.jsonl"

    def fail_cycle_and_log(*args, **kwargs):
        events_file.unlink()
        events_file.mkdir()  # LABELLED fault: the event log can no longer be appended to
        raise OSError("fixture: store unavailable")
    with contextlib.ExitStack() as stack:
        inject(env, stack, "manifest_artifact", PermissionError("fixture " + R.CANARY))
        stack.enter_context(R.replaced(env.programs, "fail_cycle", fail_cycle_and_log))
        results["log_failure_swallowed"] = tick_case(env)
    return results


# ---- T9 and T10 ------------------------------------------------------------------------------------------------------------
def t09_council(api, ws):
    results = {}
    for status in ("rejected", "accepted", "unknown", "exhausted", "running", "failed"):
        env = R.build(api, ws, "t09-" + status, status=status)
        R.registered(env)
        results["row_" + status] = {**tick_case(env), "manifest": manifest_brief(env)}
    for label, error in (("runtime_error", RuntimeError), ("key_error", KeyError), ("os_error", OSError)):
        env = R.build(api, ws, "t09-before-" + label, status=None, error=error)
        R.registered(env)
        results["raises_before_row." + label] = tick_case(env)
    for status in ("accepted", "rejected", "unknown"):
        env = R.build(api, ws, "t09-after-" + status, status=status, raise_after_row=True)
        R.registered(env)
        results["raises_after_row." + status] = tick_case(env)
    env = R.build(api, ws, "t09-mismatch", sha="0" * 64)
    R.registered(env)
    results["row_for_another_manifest"] = tick_case(env)
    env = R.build(api, ws, "t09-silent", silent=True)
    R.registered(env)
    results["no_row_no_raise"] = tick_case(env)
    env = R.build(api, ws, "t09-raise-no-row-then-row-appears", status=None)
    R.registered(env)
    results["raises_before_row_then_blocked_replay"] = {"first": tick_case(env),
                                                        "second": tick_case(env)}
    # record_council_result failing after the council ran propagates (the cycle stays owned).
    env = R.build(api, ws, "t09-record-fails")
    R.registered(env)
    with R.replaced(env.programs, "record_council_result", broken(OSError("fixture: store unavailable"))):  # LABELLED
        results["record_council_result_fails_propagates"] = tick_case(env)
    return results


def manifest_brief(env):
    """What the council received: the manifest's id, base, deadline, scope and question count."""
    if not env.council.manifests:
        return None
    manifest = env.council.manifests[0]
    return {"id": manifest["id"], "base_revision": manifest["base_revision"], "deadline": manifest["deadline"],
            "search_scope": manifest["research"]["search_scope"], "questions": len(manifest["research"]["questions"]),
            "goal_equals_template": manifest["goal"] == R.template(env.head)["goal"],
            "plan_equals_template": manifest["plan"] == R.template(env.head)["plan"]}


# ---- T11 -------------------------------------------------------------------------------------------------------------------
def investigation_env(api, ws, name, **kwargs):
    store = api.MemoryStore()
    env = R.build(api, ws, name, store=store, **kwargs)
    R.portfolio(api, store)
    return env


def investigation_rows(env):
    with env.store.transaction() as tx:
        return {"investigations": tx.scan(env.api.BUCKET_INVESTIGATIONS), "dispatches": tx.scan(env.api.BUCKET_DISPATCHES)}


def t11_investigation(api, ws):
    results = {}
    for status in ("accepted", "rejected", "unknown"):
        env = investigation_env(api, ws, "t11-" + status, status=status)
        R.registered(env, investigation_source=dict(R.SOURCE))
        results[status] = {**tick_case(env), **investigation_rows(env), "snapshot": captured(env),
                           "dispatches_view": env.programs.dispatches(R.PROGRAM)}
    env = investigation_env(api, ws, "t11-capture")
    R.registered(env, investigation_source=dict(R.SOURCE))
    R.git(env.root, "update-ref", REF, env.head)  # LABELLED: a stale ref from an earlier attempt
    results["capture_failure"] = {**tick_case(env), **investigation_rows(env)}
    env = investigation_env(api, ws, "t11-mismatch", sha="0" * 64, status="accepted")
    R.registered(env, investigation_source=dict(R.SOURCE))
    results["mismatched_run_row"] = {**tick_case(env), **investigation_rows(env)}
    env = investigation_env(api, ws, "t11-before-row", status=None)
    R.registered(env, investigation_source=dict(R.SOURCE))
    results["council_raises_before_row"] = {**tick_case(env), **investigation_rows(env)}
    env = investigation_env(api, ws, "t11-nodispatch", status="accepted")
    R.registered(env, investigation_source=dict(R.SOURCE))
    with R.replaced(env.programs, "dispatches", lambda program_id=None: []):  # LABELLED fault: no dispatch row is read back
        results["dispatch_row_not_read_back"] = {**tick_case(env), **investigation_rows(env)}
    env = investigation_env(api, ws, "t11-other-claim", status="accepted")
    R.registered(env, investigation_source=dict(R.SOURCE))
    with R.replaced(env.programs, "dispatches",  # LABELLED fault: only another investigation's row is read back
                    lambda program_id=None: [{"investigation": "other", "kind": "x", "state": "y", "result": "z",
                                              "result_reason": None, "reported_result": None, "row_status": None}]):
        results["dispatch_row_of_another_investigation"] = {**tick_case(env), **investigation_rows(env)}
    env = investigation_env(api, ws, "t11-optout", status="accepted")
    R.registered(env)  # no investigation_source: the opt-out program
    results["opt_out_program"] = {**tick_case(env), **investigation_rows(env)}
    env = investigation_env(api, ws, "t11-replay", status="accepted")
    R.registered(env, investigation_source=dict(R.SOURCE), max_cycles=3, max_adoptions=3)
    first = tick_case(env)
    env.clock.value = "2028-01-01T02:00:00+00:00"
    results["replay_keeps_the_claim"] = {"first": first, "second": tick_case(env), **investigation_rows(env)}
    env = investigation_env(api, ws, "t11-headroom", budget=R.Budget(this_host=4, all_hosts=4))
    R.registered(env, investigation_source=dict(R.SOURCE), max_cycles=3, max_adoptions=2)
    results["no_headroom_keeps_the_candidate_unclaimed"] = {**tick_case(env), **investigation_rows(env),
                                                            "candidates": R.candidates(env)}
    results["audit_progress_and_attempt_scope_results"] = {
        "unreachable": "the audit_progress and attempt_scope candidates need audit windows and a research_dispatch owner "
                       "launch row; they are the research.program_records family's states (next pilot)"}
    return results


# ---- T12 -------------------------------------------------------------------------------------------------------------------
def t12_report(api, ws):
    results = {}
    env = R.build(api, ws, "t12-done")
    R.registered(env)
    report = env.runtime / "research-program" / R.PROGRAM / "report.md"
    report.parent.mkdir(parents=True)
    report.mkdir()  # a real OS failure: a directory where the report file must be written
    results["report_unwritable_after_council"] = tick_case(env)
    env = R.build(api, ws, "t12-nothing")
    R.registered(env, max_adoptions=0)
    report = env.runtime / "research-program" / R.PROGRAM / "report.md"
    report.parent.mkdir(parents=True)
    report.mkdir()
    results["report_unwritable_no_candidate"] = tick_case(env)
    env = R.build(api, ws, "t12-failed")
    R.registered(env)
    report = env.runtime / "research-program" / R.PROGRAM / "report.md"
    report.parent.mkdir(parents=True)
    report.mkdir()
    R.git(env.root, "update-ref", REF, env.head)
    results["report_unwritable_after_capture_failure"] = tick_case(env)
    env = R.build(api, ws, "t12-predispatch")
    R.registered(env)
    manifests = env.runtime / "research-program" / R.PROGRAM / "manifests"
    manifests.parent.mkdir(parents=True)
    manifests.write_text("a regular file where the manifest directory must be created\n", encoding="utf-8")
    (env.runtime / "research-program" / R.PROGRAM / "report.md").mkdir()
    results["report_unwritable_after_pre_council_failure"] = tick_case(env)
    return results


# ---- the M7 tests that drive a tick, not covered above ----------------------------------------------------------------
def m7_mirror(api, ws):
    results = {}
    env = R.build(api, ws, "m7-two", outages=("geeknews",))
    cfg = R.registered(env)
    first = tick_case(env)
    snapshot = captured(env)
    candidates = {c["id"]: c for c in env.programs.candidates(R.PROGRAM)}
    second_not_due = R.call(ws, R.tick, env)
    env.clock.value = "2028-01-01T02:00:00+00:00"
    env.sources.outages.clear()
    second = tick_case(env)
    third = R.call(ws, R.tick, env)
    results["two_ticks"] = {
        "first": first, "snapshot": snapshot, "candidates_after_first": candidates, "second_not_due": second_not_due,
        "second": second, "after_completion": third, "candidate_seen": env.programs.candidate(R.PROGRAM, "local-note")["seen"],
        "manifest_equals_template": [env.council.manifests[0]["goal"] == cfg["template"]["goal"],
                                     env.council.manifests[0]["plan"] == cfg["template"]["plan"]],
        "report": (env.runtime / "research-program" / R.PROGRAM / "report.md").read_text(encoding="utf-8"),
        "checkout_untouched": (env.root / "dirty.txt").exists()}
    env = R.build(api, ws, "m7-monitor")
    R.registered(env)
    tick_case(env)
    facts = api.research_program_facts(env.store)
    empty = api.research_program_facts(api.MemoryStore())
    for i in range(21):
        env.programs.register(api.validate_config(R.config(env.head, id="rp-%03d" % (i + 10)), api.POLICY), env.identity, [])
    many = api.research_program_facts(env.store)
    results["monitor_projection"] = {"facts": facts, "empty": empty, "truncated": many["truncated"],
                                     "listed": len(many["programs"])}
    return results


GROUPS = (("t01_repository_mismatch", t01_repository_mismatch), ("t02_not_reserved", t02_not_reserved),
          ("t13_run", t13_run), ("t03_collection", t03_collection), ("t05_no_candidate", t05_no_candidate),
          ("t06_capture_failure", t06_capture_failure), ("t08_pre_council", t08_pre_council),
          ("t09_council", t09_council), ("t11_investigation", t11_investigation), ("t12_report", t12_report),
          ("m7_mirror", m7_mirror))


def run(api) -> dict:
    ws = R.Workspace()
    try:
        result, counts = {}, {}
        for name, group in GROUPS:
            result[name] = ws.scrub(group(api, ws))
            counts[name] = len(result[name])
        result["cases_per_group"] = counts
        result["leftover_capture_directories"] = ws.leftovers()
        return result
    finally:
        ws.close()
