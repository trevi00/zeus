"""S8 pilot 76: the M7 discovery pressure app and adapter moved into research through R-dp0..R-dp2
(A/evidence/rebuild/s8/discovery-pressure-move/transcribe.py; DESIGN-s8 §1 V2e, §10 V15).

M7 is read only as text through `git show e38aa722:...` and compared by AST (never imported: both packages are named
`codex_harness`). Behaviour is checked on the TARGET only, against literals; the recorded comparison is the `research.sources` golden.
"""
import ast
import importlib
import re
import subprocess
import textwrap
from pathlib import Path

from _layout import REPO, TARGET

SRC = TARGET / "src" / "codex_harness"
SOURCE = "e38aa722"
APP, ADAPTER = "codex_harness.research.application.discovery_pressure", "codex_harness.research.adapters.discovery_pressure"
M7_APP, M7_ADAPTER = "src/codex_harness/application/discovery_pressure.py", "src/codex_harness/adapters/discovery_pressure.py"

OLD_BLOCK = (
    "            registry = Fleet._registry(tx)\n"
    "            control = Fleet._control(tx)\n"
    "            config = effective_config(registry[\"config\"], control) if registry is not None else None\n"
    "            jobs = {job[\"id\"]: job for job in tx.scan(BUCKET_JOBS)}\n"
    "            observed = census(config=config, control=control, jobs=jobs, units=tx.scan(BUCKET_UNITS),\n"
    "                              plans=tx.scan(BUCKET_PLANS), intents=tx.scan(BACKLOG_INTENTS),\n"
    "                              continuation_intents=tx.scan(CONTINUATION_INTENTS),\n"
    "                              aliases=Fleet._repository_aliases(tx) if registry is not None else None, ledger=ledger)\n")
NEW_BLOCK = (
    "            require(self.census is not None, \"Discovery pressure needs the census reader (DiscoveryCensus) wired\")\n"
    "            bundle = self.census.observe(tx, ledger)\n"
    "            observed = bundle[\"observed\"]\n")


def m7_text(path):
    return subprocess.run(["git", "-C", str(REPO), "show", f"{SOURCE}:{path}"], check=True, capture_output=True, text=True).stdout


def target_text(module):
    return Path(importlib.import_module(module).__file__).read_text()


def top(src):
    return {n.name if hasattr(n, "name") else ast.unparse(n.targets[0]): n for n in ast.parse(src).body
            if not isinstance(n, (ast.Import, ast.ImportFrom)) and not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant))}


def methods(cls):
    return {n.name: n for n in cls.body if isinstance(n, ast.FunctionDef)}


def imports(src):
    return {(n.module, a.name) for n in ast.walk(ast.parse(src)) if isinstance(n, ast.ImportFrom) for a in n.names}


def test_application_names_and_every_statement_are_m7s_except_the_two_rewritten_methods():
    ref, ours = top(m7_text(M7_APP)), top(target_text(APP))
    assert list(ours) == list(ref) == ["AUTHORITY", "DiscoveryPressure", "view", "status", "__all__"]
    assert [k for k in ref if ast.dump(ref[k]) != ast.dump(ours[k])] == ["DiscoveryPressure"]
    mine, theirs = methods(ours["DiscoveryPressure"]), methods(ref["DiscoveryPressure"])
    assert list(mine) == list(theirs) == ["__init__", "admit", "_evaluate"]
    assert [k for k in theirs if ast.dump(mine[k]) != ast.dump(theirs[k])] == ["__init__", "_evaluate"]


def test_r_dp1_the_two_rewritten_methods_are_m7s_with_exactly_the_rule_applied():
    ref_src = m7_text(M7_APP)
    ref = methods(top(ref_src)["DiscoveryPressure"])
    segment = lambda name: ast.get_source_segment(ref_src, ref[name])  # noqa: E731
    evaluate = segment("_evaluate")
    # `get_source_segment` drops the first line's indent only
    evaluate = "    " + evaluate
    assert evaluate.count(OLD_BLOCK) == 1
    evaluate = evaluate.replace(OLD_BLOCK, NEW_BLOCK)
    digest_old = "digest(registry[\"config\"]) if registry is not None else None"
    assert evaluate.count(digest_old) == 1
    evaluate = evaluate.replace(digest_old, "bundle[\"fleet_config_sha256\"]")
    init = "    " + segment("__init__")
    sig_old = "clock=utcnow, ledger=None):"
    assert init.count(sig_old) == 1
    init = init.replace(sig_old, "clock=utcnow, ledger=None, *, census=None):")
    store_line = "        self.store, self.observer, self.clock, self.ledger = store, observer, clock, ledger\n"
    assert init.count(store_line) == 1
    init = init.replace(store_line, store_line + "        self.census = census\n")
    mine = methods(top(target_text(APP))["DiscoveryPressure"])
    assert ast.dump(ast.parse(textwrap.dedent(evaluate)).body[0]) == ast.dump(mine["_evaluate"])
    assert ast.dump(ast.parse(textwrap.dedent(init)).body[0]) == ast.dump(mine["__init__"])
    kw = mine["__init__"].args
    assert [a.arg for a in kw.kwonlyargs] == ["census"] and [ast.literal_eval(d) for d in kw.kw_defaults] == [None]


def test_r_dp1_order_the_census_is_taken_after_the_ledger_state_and_before_the_prior_read():
    evaluate = methods(top(target_text(APP))["DiscoveryPressure"])["_evaluate"]
    order = [(n.lineno, ast.unparse(n)[:40]) for n in ast.walk(evaluate) if isinstance(n, ast.Assign)]
    line = {text.split(" =")[0]: no for no, text in order}
    assert line["ledger_state"] < line["bundle"] < line["observed"] < line["prior"] < line["outcome"]
    requires = [n.lineno for n in ast.walk(evaluate) if isinstance(n, ast.Expr) and ast.unparse(n).startswith("require(self.census")]
    assert len(requires) == 1 and requires[0] < line["bundle"]


def test_r_dp1_at_run_time_the_reader_runs_before_the_prior_row_is_read_and_the_bundle_digest_reaches_the_basis():
    from codex_harness.storage.adapters.memory_store import MemoryStore
    pressure = importlib.import_module(APP)
    events = []

    class Census:
        def observe(self, tx, ledger):
            events.append("census")
            return {"observed": {"registered": False}, "fleet_config_sha256": "f" * 64}

    class Tx:
        def __init__(self, tx):
            self.tx = tx

        def get(self, bucket, key):
            events.append(("get", bucket, key))
            return self.tx.get(bucket, key)

        def put(self, *args):
            return self.tx.put(*args)

    class Store:
        def __init__(self, store):
            self.store = store

        def transaction(self):
            outer = self.store.transaction()

            class Ctx:
                def __enter__(ctx):
                    return Tx(outer.__enter__())

                def __exit__(ctx, *exc):
                    return outer.__exit__(*exc)

            return Ctx()

    class Observer:
        def audit(self, *args, **kwargs):
            events.append("audit")

    result = pressure.DiscoveryPressure(Store(MemoryStore()), None, Observer(), census=Census()).admit()
    assert result["recorded"] is True and result["basis"]["fleet_config_sha256"] == "f" * 64
    assert events == ["census", ("get", "discovery_pressure", "proactive"), "audit"]


def test_an_unwired_census_is_an_evaluation_failure_hold_that_writes_nothing_as_m7_does_for_any_evaluation_failure():
    from codex_harness.research.domain.discovery_pressure import unrecorded_hold
    from codex_harness.storage.adapters.memory_store import MemoryStore
    store = MemoryStore()
    pressure = importlib.import_module(APP).DiscoveryPressure(store, None, object())
    assert pressure.census is None
    assert pressure.admit() == unrecorded_hold("evaluation_failed")
    assert importlib.import_module(APP).status(store)["evaluated"] is False


def test_the_wired_reader_gives_two_equal_crossings_one_transition_and_one_audit_event():
    from codex_harness.composition import research_program_adapters
    from codex_harness.observation.adapters.observation_spool import MemorySpool
    from codex_harness.observation.application.observations import MemoryDirectory, Observer
    from codex_harness.observation.domain.observation import new_process_run_id
    from codex_harness.storage.adapters.memory_store import MemoryStore
    store = MemoryStore()
    observer = Observer(store, MemorySpool(new_process_run_id()), component="test-pressure", directory=MemoryDirectory())
    evaluator = research_program_adapters.discovery_pressure(store, observer)
    first, second = evaluator.admit(), evaluator.admit()
    assert (first["recorded"], first["version"], first["evaluation_sequence"]) == (True, 1, 1)
    assert (second["version"], second["evaluation_sequence"]) == (1, 2)
    assert first["basis"]["registered"] is False and first["basis"]["fleet_config_sha256"] is None
    with store.transaction() as tx:
        audits = [r for r in tx.scan("observation_audit") if r.get("event_type") == "operations.discovery_pressure_changed"]
    assert len(audits) == 1


def test_r_dp0_the_only_imports_that_moved_are_the_m7_names_and_the_census_block_ones_left():
    ref, ours = imports(m7_text(M7_APP)), imports(target_text(APP))
    domain = ["BUCKET", "EVENT_CHANGED", "KEY", "ROW_SCHEMA", "DiscoveryRefused", "decide", "sample_fresh", "unrecorded_hold", "validate_policy"]
    left = {("codex_harness.application.continuation", "BUCKET_INTENTS"), ("codex_harness.application.fleet", "BUCKET_JOBS"),
            ("codex_harness.application.fleet", "BUCKET_UNITS"), ("codex_harness.application.fleet", "Fleet"),
            ("codex_harness.application.fleet_backlog", "BUCKET_INTENTS"), ("codex_harness.application.fleet_backlog", "BUCKET_PLANS"),
            ("codex_harness.domain.discovery_pressure", "census"), ("codex_harness.domain.fleet", "effective_config"),
            ("codex_harness.domain.model", "digest")}
    renamed = {("codex_harness.domain.discovery_pressure", n) for n in domain} | {
        ("codex_harness.domain.model", "require"), ("codex_harness.domain.model", "utcnow"),
        ("codex_harness.domain.usage_policy", "readable_counts")}
    assert ref - ours == left | renamed
    assert ours - ref == {("codex_harness.research.domain.discovery_pressure", n) for n in domain} | {
        ("codex_harness.kernel.errors", "require"), ("codex_harness.kernel.ids", "utcnow"),
        ("codex_harness.kernel.usage", "readable_counts")}
    mods = {m for m, _ in imports(target_text(APP))}
    assert {m for m in mods if m.startswith("codex_harness.")} == {
        "codex_harness.kernel.errors", "codex_harness.kernel.ids", "codex_harness.kernel.usage",
        "codex_harness.research.domain.discovery_pressure"}


def test_r_dp2_the_adapter_is_m7s_except_pressure_which_passes_ledger_and_census_and_no_longer_imports_call_budget():
    ref, ours = top(m7_text(M7_ADAPTER)), top(target_text(ADAPTER))
    assert list(ours) == list(ref) == ["POLICY_RESOURCE", "packaged_policy", "pressure"]
    assert [k for k in ref if ast.dump(ref[k]) != ast.dump(ours[k])] == ["pressure"]
    args = ours["pressure"].args
    assert [a.arg for a in args.args] == ["store", "observer"] and [a.arg for a in args.kwonlyargs] == ["ledger", "census"]
    assert [ast.literal_eval(d) for d in args.kw_defaults] == [None, None]
    text = target_text(ADAPTER)
    assert "call_budget" not in text and "CallBudget" not in text.split('"""', 2)[2]
    assert imports(text) - imports(m7_text(M7_ADAPTER)) == {("codex_harness.research.application.discovery_pressure", "DiscoveryPressure")}


def test_the_adapter_pressure_wires_the_given_ledger_and_census_and_defaults_to_none():
    adapter = importlib.import_module(ADAPTER)
    census, ledger = object(), (lambda: {})
    evaluator = adapter.pressure(object(), object(), ledger=ledger, census=census)
    assert evaluator.census is census and evaluator.ledger is ledger and evaluator.policy is not None
    bare = adapter.pressure(object(), object())
    assert bare.census is None and bare.ledger is None


def test_v4_discovery_pressure_is_a_research_bucket_and_its_only_writer_is_the_moved_app():
    from codex_harness.coordination import ports as coordination
    from codex_harness.research import ports as research
    assert "discovery_pressure" in research.OWNED_BUCKETS and "discovery_pressure" not in coordination.OWNED_BUCKETS
    writers = set()
    for path in SRC.rglob("*.py"):
        text = path.read_text()
        if re.search(r"\.put\(\s*(BUCKET|\"discovery_pressure\")\s*,\s*(KEY|\"proactive\")", text) and "discovery_pressure" in text:
            writers.add(str(path.relative_to(SRC)))
    assert writers == {"research/application/discovery_pressure.py"}
    for path in SRC.rglob("*.py"):
        if "put(" in path.read_text() and path.name != "discovery_pressure.py":
            assert not re.search(r"\.put\(\s*\"discovery_pressure\"", path.read_text()), path
