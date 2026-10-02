"""S8 pilot 92 (DESIGN-s8 §13 V18): the first three M7 threshold modules moved to research: `research.adapters.runtime_thresholds`,
`research.application.threshold_replay` and `research.application.threshold_proposals`. Everything but the named rules is M7's
(A/evidence/rebuild/s8/thresholds-a-move/transcribe.py): R-t0 (V9 local constants), R-t1 (`validate_source` injected), R-t2 (`POLICY_FILE` depth),
R-t3 (the import homes).

M7 is read only as text through `git show e38aa722:...` and compared by AST (never imported: both packages are named `codex_harness`). Behaviour is
checked on the TARGET only, against literals; the recorded comparison is the three `research.*` goldens plus `research.threshold_approvals`. The
first-use refusal (the rule is not wired) has no M7 counterpart and is pinned here.
"""
import ast
import importlib
import subprocess
from pathlib import Path

import pytest

from codex_harness.context.domain.skills import history as skill_history
from codex_harness.context.domain.skills import import_ as skill_import
from codex_harness.context.domain.skills import ranking as skill_ranking
from codex_harness.kernel.errors import ContractError
from codex_harness.kernel.ids import digest
from codex_harness.research import ports
from codex_harness.storage.adapters.memory_store import MemoryStore

REPO = Path(__file__).resolve().parents[2]
SOURCE = "e38aa722"
MODULES = {
    "runtime_thresholds": ("adapters", "codex_harness.research.adapters.runtime_thresholds"),
    "threshold_replay": ("application", "codex_harness.research.application.threshold_replay"),
    "threshold_proposals": ("application", "codex_harness.research.application.threshold_proposals"),
}
NAMES = tuple(MODULES)
HOMES = {
    "runtime_thresholds": {"codex_harness.kernel.errors": ["ContractError", "require"], "codex_harness.kernel.ids": ["digest"],
                           "codex_harness.kernel.numbers": ["finite_number"],
                           "codex_harness.research.domain.threshold_proposals": ["REGISTRY", "validate_registry"], "pathlib": ["Path"], "json": ["json"]},
    "threshold_replay": {"codex_harness.kernel.errors": ["require"], "codex_harness.kernel.ids": ["digest"],
                         "codex_harness.research.domain.threshold_replay": ["replay_report"]},
    "threshold_proposals": {"codex_harness.kernel.errors": ["ContractError", "require"], "codex_harness.kernel.ids": ["canonical", "digest", "utcnow"],
                            "codex_harness.research.domain.threshold_proposals": ["propose_threshold_changes"], "json": ["json"]},
}
CONSTANTS = {"runtime_thresholds": ("FULL_BODY_MIN_SCORE", 3, skill_ranking), "threshold_replay": ("MAX_EVENTS", 4000, skill_history),
             "threshold_proposals": ("MAX_EVENTS", 4000, skill_history)}
REWRITTEN = {"runtime_thresholds": ("POLICY_FILE",), "threshold_replay": ("ThresholdReplay",), "threshold_proposals": ("ThresholdProposals",)}
UNWIRED = "validate_source is not wired"
CASES = {"threshold_replay": "ThresholdReplay", "threshold_proposals": "ThresholdProposals"}
REVISION = "a" * 40
NAME = "skill_match.FULL_BODY_MIN_SCORE"


def m7_text(name):
    layer = MODULES[name][0]
    return subprocess.run(["git", "-C", str(REPO), "show", f"{SOURCE}:src/codex_harness/{layer}/{name}.py"], check=True, capture_output=True,
                          text=True).stdout


def module(name):
    return importlib.import_module(MODULES[name][1])


def target_text(name):
    return Path(module(name).__file__).read_text()


def defined(node):
    if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
        return (node.name,)
    if isinstance(node, ast.Assign):
        return tuple(n.id for t in node.targets for n in ast.walk(t) if isinstance(n, ast.Name))
    return ()


def statements(src):
    out = {}
    for i, node in enumerate(ast.parse(src).body):
        if isinstance(node, (ast.Import, ast.ImportFrom)) or (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)):
            continue
        key = defined(node) or ("expr", i)
        assert key not in out
        out[key] = node
    return out


def method(cls, name):
    return next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == name)


def dumped(nodes):
    return [ast.dump(n) for n in nodes]


def imported(name):
    found = {}
    for n in ast.parse(target_text(name)).body:
        if isinstance(n, ast.ImportFrom):
            found[n.module] = [a.name for a in n.names]
        elif isinstance(n, ast.Import):
            found.update({a.name: [a.name] for a in n.names})
    return found


# ---- the transcription: AST against M7 ---------------------------------------------------------------------------------
@pytest.mark.parametrize("name", NAMES)
def test_every_statement_but_the_rewritten_one_and_the_v9_constant_is_m7s_in_order(name):
    ref, ours = statements(m7_text(name)), statements(target_text(name))
    constant = (CONSTANTS[name][0],)
    assert [k for k in ours if k != constant] == list(ref), "the same top-level names in the same order, plus the one constant"
    for key in ref:
        if key != REWRITTEN[name]:
            assert ast.dump(ours[key]) == ast.dump(ref[key]), key
    assert ast.dump(ours[constant]) == ast.dump(ast.parse(f"{constant[0]} = {CONSTANTS[name][1]}").body[0])


def test_r_t2_policy_file_only_climbs_one_directory_more():
    ref = statements(m7_text("runtime_thresholds"))[("POLICY_FILE",)]
    ours = statements(target_text("runtime_thresholds"))[("POLICY_FILE",)]
    assert ast.unparse(ref).count("parents[1]") == 1 and ast.unparse(ours) == ast.unparse(ref).replace("parents[1]", "parents[2]")
    policy = module("runtime_thresholds").POLICY_FILE
    assert policy == REPO / "target/src/codex_harness/resources/threshold-policy.json" and policy.is_file()


@pytest.mark.parametrize("name", CASES)
def test_r_t1_validate_source_is_a_keyword_only_port_required_only_on_the_legacy_path(name):
    cls = CASES[name]
    ref = statements(m7_text(name))[(cls,)]
    ours = statements(target_text(name))[(cls,)]
    init_m, init_t = method(ours, "__init__"), method(ref, "__init__")
    assert [a.arg for a in init_m.args.args] == [a.arg for a in init_t.args.args]
    assert [a.arg for a in init_m.args.kwonlyargs] == ["validate_source"] and [ast.unparse(d) for d in init_m.args.kw_defaults] == ["None"]
    if name == "threshold_proposals":
        assert [a.arg for a in init_m.args.args] == ["self", "store", "artifacts", "policy_provider", "native_replay"]
        assert [ast.unparse(d) for d in init_m.args.defaults] == ["None"], "native_replay keeps its M7 default; the new parameter is appended after it"
    assert dumped(init_m.body[:-1]) == dumped(init_t.body) and ast.unparse(init_m.body[-1]) == "self.validate_source = validate_source"
    entry = "evaluate" if name == "threshold_replay" else "collect"
    a, b = method(ours, entry), method(ref, entry)
    assert ast.dump(a.args) == ast.dump(b.args)
    old = ast.dump(ast.parse("if legacy_source is not None:\n    validate_source(legacy_source)").body[0])
    new = ast.dump(ast.parse(f"if legacy_source is not None:\n    require(self.validate_source is not None, {UNWIRED!r})\n"
                             "    self.validate_source(legacy_source)").body[0])
    hits = [i for i, n in enumerate(b.body) if ast.dump(n) == old]
    assert len(hits) == 1
    assert dumped(a.body) == [new if i == hits[0] else d for i, d in enumerate(dumped(b.body))]
    assert ast.unparse(ours).count("self.validate_source is not None") == 1, "the require is on the legacy_source path only"


STDLIB = {"runtime_thresholds": ("json", "pathlib"), "threshold_replay": (), "threshold_proposals": ("json",)}


@pytest.mark.parametrize("name", NAMES)
def test_imports_are_only_the_v18_homes_and_nothing_reaches_m7_or_context(name):
    found = {k: sorted(v) for k, v in imported(name).items()}
    assert found == {k: sorted(v) for k, v in HOMES[name].items()}
    for module_name in found:
        assert not module_name.startswith(("codex_harness.adapters", "codex_harness.domain", "codex_harness.application", "codex_harness.bootstrap",
                                           "codex_harness.context", "codex_harness.composition", "codex_harness.host_os")), module_name


@pytest.mark.parametrize("name", NAMES)
def test_headers_name_context_layer_the_move_and_the_rules(name):
    header = target_text(name).split('"""')[1]
    for needle in (f"Layer: {MODULES[name][0]}", "Context: research", "Owns:", "Does not own:", "Entry points:", "Contracts: INV-",
                   f"Moved from M7 `{MODULES[name][0]}/{name}.py`", "SOURCE e38aa722", "V18", "A/evidence/rebuild/s8/thresholds-a-move/transcribe.py", "R-t0", "R-t3"):
        assert needle in header, needle
    assert ("R-t1" in header) is (name in CASES) and ("R-t2" in header) is (name == "runtime_thresholds")


# ---- R-t0: the V9 local constants equal their owners ---------------------------------------------------------------------
@pytest.mark.parametrize("name", NAMES)
def test_r_t0_the_local_constant_equals_the_context_owner(name):
    constant, value, owner = CONSTANTS[name]
    assert getattr(module(name), constant) == getattr(owner, constant) == value


def test_the_native_default_and_the_registry_default_agree():
    runtime = module("runtime_thresholds")
    assert runtime.NATIVE_DEFAULTS == {NAME: skill_ranking.FULL_BODY_MIN_SCORE}
    assert runtime.REGISTRY[NAME].default == skill_ranking.FULL_BODY_MIN_SCORE
    assert runtime.effective_policy()["values"] == {NAME: 3}


def test_the_injectable_rule_is_the_same_rule_as_m7s_and_not_a_research_one():
    ref = ast.dump(next(n for n in ast.parse(subprocess.run(["git", "-C", str(REPO), "show", f"{SOURCE}:src/codex_harness/domain/skill_import.py"],
                                                            check=True, capture_output=True, text=True).stdout).body
                        if isinstance(n, ast.FunctionDef) and n.name == "validate_source"))
    assert ast.dump(next(n for n in ast.parse(Path(skill_import.__file__).read_text()).body
                         if isinstance(n, ast.FunctionDef) and n.name == "validate_source")) == ref


# ---- R-t1 behaviour: the first-use refusal --------------------------------------------------------------------------------
OPTIONS = {"old_value": 3, "proposed_value": 4, "holdout_boundary": "2026-01-01T00:00:28Z"}


def seeded(seeds):
    store = MemoryStore()
    with store.transaction() as tx:
        for (bucket, key), state in seeds.items():
            tx.put(bucket, key, state)
    return store


def test_replay_without_validate_source_is_refused_only_on_the_legacy_path():
    replay = module("threshold_replay").ThresholdReplay
    store = MemoryStore()
    with store.transaction() as tx:
        tx.put("skill_history", "p", {"events": []})
    assert replay(store).evaluate("p", **OPTIONS)["events"] == [], "the native path needs no validate_source"
    with pytest.raises(ContractError, match=UNWIRED):
        replay(store).evaluate("p", legacy_source="segment", **OPTIONS)
    with pytest.raises(ContractError, match=UNWIRED):
        replay(store, validate_source=None).evaluate("p", legacy_source="bad id!", **OPTIONS)


def test_replay_calls_the_injected_rule_once_and_its_refusal_propagates():
    replay = module("threshold_replay").ThresholdReplay
    seen = []
    store = MemoryStore()
    assert replay(store, validate_source=seen.append).evaluate("p", legacy_source="segment", **OPTIONS)["legacy_source"] == "segment"
    assert seen == ["segment"]
    with pytest.raises(ContractError, match="Source ID must identify one append-only log segment"):
        replay(store, validate_source=skill_import.validate_source).evaluate("p", legacy_source="bad id!", **OPTIONS)
    with pytest.raises(TypeError):
        replay(store, skill_import.validate_source)


def provider():
    return {"values": {NAME: 3}, "revision": REVISION}


class Artifacts:
    def __init__(self):
        self.puts = []

    def put(self, text, kind):
        self.puts.append(kind)
        return {"ref": "sha256:" + "0" * 64}


def test_proposals_without_validate_source_is_refused_on_the_legacy_path_before_any_policy_or_write():
    proposals = module("threshold_proposals").ThresholdProposals
    calls, artifacts, store = [], Artifacts(), MemoryStore()

    def counted():
        calls.append(1)
        return provider()

    with pytest.raises(ContractError, match=UNWIRED):
        proposals(store, artifacts, counted).collect("p", legacy_source="segment")
    assert calls == [] and artifacts.puts == [] and store.data == {}
    with pytest.raises(ContractError, match="Invalid evaluation round"):
        proposals(store, artifacts, counted).collect("p", legacy_source="segment", evaluation_round=-1)
    run = proposals(store, artifacts, counted).collect("p")
    assert run["proposals"] == [] and run["status"] == "calculated", "the native path needs no validate_source"


def test_proposals_calls_the_injected_rule_and_keeps_native_replay_positional():
    proposals = module("threshold_proposals").ThresholdProposals
    seen = []
    store = seeded({("legacy_skill_imports", digest(["p", "segment"])): {"events": [], "source_ref": "sha256:" + "5" * 64}})

    class Native:
        def evaluate(self, events, values):
            return {"status": "complete"}

    service = proposals(store, Artifacts(), provider, Native(), validate_source=seen.append)
    run = service.collect("p", legacy_source="segment")
    assert seen == ["segment"] and run["status"] == "calculated"
    with pytest.raises(ContractError, match="Source ID must identify one append-only log segment"):
        proposals(store, Artifacts(), provider, validate_source=skill_import.validate_source).collect("p", legacy_source="bad id!")


# ---- the buckets ------------------------------------------------------------------------------------------------------------
BUCKETS = ("threshold_collection_inputs", "threshold_proposal_runs", "threshold_proposals")


def test_research_owns_the_three_proposal_buckets_once_each_and_only_threshold_proposals_writes_them():
    for bucket in BUCKETS:
        assert ports.OWNED_BUCKETS.count(bucket) == 1, bucket
    tree = ast.parse(target_text("threshold_proposals"))
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)]
    assert {ast.unparse(n.args[0]) for n in calls if n.func.attr == "put" and ast.unparse(n.func.value) == "tx"} == {f"'{b}'" for b in BUCKETS}
    # the context-owned corpus is read by literal and never written here
    assert {ast.unparse(n.args[0]) for n in calls if n.func.attr == "get"} >= {"bucket", "'threshold_collection_inputs'", "'threshold_proposal_runs'"}
    assert "'skill_history'" in target_text("threshold_proposals") and "'legacy_skill_imports'" in target_text("threshold_proposals")
    src = REPO / "target" / "src" / "codex_harness"
    writers = [path.relative_to(src).as_posix() for path in sorted(src.rglob("*.py"))
               if any(f"put('{b}'" in path.read_text() or f'put("{b}"' in path.read_text() for b in BUCKETS)]
    assert writers == ["research/application/threshold_proposals.py"], writers
    replay = {ast.unparse(n.func) for n in ast.walk(ast.parse(target_text("threshold_replay"))) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    assert not any(attr.endswith(".put") for attr in replay), "threshold_replay writes nothing"


def test_the_modules_create_no_process_and_open_no_database():
    for name in NAMES:
        code = target_text(name).split('"""', 2)[2]
        for word in ("subprocess", "psycopg", "open(", "os."):
            assert word not in code, (name, word)
