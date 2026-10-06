"""S8 pilot 82: the rest of the M7 `Harness` hook lifecycle moved into research `HookLifecycle` through named rules
(A/evidence/rebuild/s8/hook-lifecycle-move/transcribe.py; R-h0 transaction required, R-h1 unit, R-h2 events, R-h3, R-h4 imports).

M7 is read only as text through `git show e38aa722:...` and compared by AST (never imported: both packages are named
`codex_harness`). Behaviour is checked on the TARGET only, against literals; the recorded comparison is the
`research.hook_lifecycle` golden.
"""
import ast
import copy
import inspect
import subprocess
from pathlib import Path

import pytest
from _layout import REPO

from codex_harness.coordination.application.events import EventJournal
from codex_harness.coordination.application.outbox import Outbox
from codex_harness.kernel.errors import ContractError
from codex_harness.research.application import hooks as hooks_module
from codex_harness.research.application.hooks import HookLifecycle
from codex_harness.routing.adapters.organization_source import packaged_organization
from codex_harness.storage.adapters.memory_store import MemoryStore

SOURCE = "e38aa722"
M7_PATH = "src/codex_harness/application/service.py"
MOVED = ["get_hook", "propose", "record_canary", "activate", "rollback", "prepare_command", "active_hooks"]
S4 = ["__init__", "record_incident", "review"]
ALIAS = {"kind": "executable_alias", "match": "python", "replacement": "py", "platform": "windows"}
CHECKS = {"reproduction": True, "normal_case": True, "cli_start": True}


def m7_methods():
    text = subprocess.run(["git", "-C", str(REPO), "show", f"{SOURCE}:{M7_PATH}"], check=True, capture_output=True, text=True).stdout
    cls = next(n for n in ast.parse(text).body if isinstance(n, ast.ClassDef) and n.name == "Harness")
    return {n.name: n for n in cls.body if isinstance(n, ast.FunctionDef)}


def target_tree():
    return ast.parse(Path(hooks_module.__file__).read_text())


def target_methods():
    cls = next(n for n in target_tree().body if isinstance(n, ast.ClassDef) and n.name == "HookLifecycle")
    return {n.name: n for n in cls.body if isinstance(n, ast.FunctionDef)}


def name(id_):
    return ast.Name(id=id_, ctx=ast.Load())


class Rules(ast.NodeTransformer):
    """R-h0..R-h3 as an AST statement, applied to M7's method tree (independent of the text rules)."""

    def visit_FunctionDef(self, node):
        self.generic_visit(node)
        node.args.kwonlyargs = [a for a in node.args.kwonlyargs if a.arg != "transaction"] + [ast.arg(arg="transaction")]
        node.args.kw_defaults = [None] * len(node.args.kwonlyargs)
        return node

    def visit_With(self, node):
        self.generic_visit(node)
        return [ast.Assign(targets=[ast.Name(id="tx", ctx=ast.Store())], value=name("transaction"))] + node.body

    def visit_Call(self, node):
        self.generic_visit(node)
        f = node.func
        if isinstance(f, ast.Name) and f.id == "utcnow" and not node.args:
            node.args = [ast.Attribute(value=name("self"), attr="clock", ctx=ast.Load())]
        if isinstance(f, ast.Attribute) and f.attr == "put" and node.args and isinstance(node.args[0], ast.Constant) \
                and node.args[0].value == "events":
            ids = ast.BoolOp(op=ast.Or(), values=[ast.Attribute(value=name("self"), attr="ids", ctx=ast.Load()), name("SYSTEM_IDS")])
            uuid = ast.Call(func=ast.Attribute(value=ids, attr="uuid4", ctx=ast.Load()), args=[], keywords=[])
            node.func = ast.Attribute(value=ast.Attribute(value=name("self"), attr="events", ctx=ast.Load()), attr="append", ctx=ast.Load())
            node.args = [name("tx"), ast.Call(func=name("str"), args=[uuid], keywords=[]), node.args[2]]
        if isinstance(f, ast.Attribute) and f.attr == "active_hooks" and isinstance(f.value, ast.Name) and f.value.id == "self":
            node.keywords = [ast.keyword(arg="transaction", value=name("transaction"))]
        return node


def test_each_moved_method_is_m7_s_by_ast_under_the_named_rules():
    ref, ours = m7_methods(), target_methods()
    for method in MOVED:
        want = Rules().visit(copy.deepcopy(ref[method]))
        ast.fix_missing_locations(want)
        assert ast.dump(ours[method]) == ast.dump(want), method
    assert list(ours) == S4 + MOVED


def test_the_s4_methods_are_unchanged_and_the_rule_counts_hold_in_m7():
    ref = m7_methods()
    withs = [n for m in MOVED for n in ast.walk(ref[m]) if isinstance(n, ast.With)]
    assert len(withs) == 6
    events = [n for m in MOVED for n in ast.walk(ref[m]) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
              and n.func.attr == "put" and n.args and isinstance(n.args[0], ast.Constant) and n.args[0].value == "events"]
    assert len(events) == 3
    clocks = [n for m in MOVED for n in ast.walk(ref[m]) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "utcnow"]
    assert len(clocks) == 3
    assert {a.arg for m in MOVED for a in ref[m].args.kwonlyargs} == {"transaction"}  # only `activate` had one, with a default
    assert ref["activate"].args.kw_defaults[0].value is None


def test_no_moved_method_opens_its_own_unit_and_every_one_requires_the_transaction():
    ours = target_methods()
    text = Path(hooks_module.__file__).read_text()
    for word in ("nullcontext", "self.store", "from uuid import", "(uuid4()"):
        assert word not in text, word
    assert text.count("(self.ids or SYSTEM_IDS).uuid4()") == 4  # record_incident (S4) and the three moved events
    for method in MOVED:
        args = ours[method].args
        assert [a.arg for a in args.kwonlyargs][-1] == "transaction", method
        assert args.kw_defaults[-1] is None, method  # required: no default
        param = inspect.signature(getattr(HookLifecycle, method)).parameters["transaction"]
        assert param.kind is inspect.Parameter.KEYWORD_ONLY and param.default is inspect.Parameter.empty, method


def test_the_import_rule_and_the_header():
    imports = {n.module: [a.name for a in n.names] for n in target_tree().body if isinstance(n, ast.ImportFrom)}
    assert imports["codex_harness.research.domain.recurrence"] == ["Incident", "hook_apply"]
    assert imports["codex_harness.kernel.ids"] == ["SYSTEM_IDS", "digest", "utcnow"]
    assert imports["codex_harness.kernel.errors"] == ["require"]
    doc = ast.get_docstring(target_tree())
    assert "get_hook/propose/record_canary/activate/rollback/prepare_command/active_hooks" in doc
    assert "propose, canary, activation: S8" not in doc
    assert "the S10 composition facade" in doc


@pytest.mark.parametrize("method,args", [("get_hook", ("h",)), ("propose", ("h", "worker:implementation", ALIAS, "r")),
                                         ("record_canary", ("h", "r", "x", CHECKS)), ("activate", ("h",)),
                                         ("rollback", ("h", "why")), ("prepare_command", (["a"], "windows")), ("active_hooks", ())])
def test_a_missing_transaction_is_a_type_error(method, args):
    lifecycle = HookLifecycle(packaged_organization(), outbox=Outbox(), events=EventJournal())
    with pytest.raises(TypeError, match="transaction"):
        getattr(lifecycle, method)(*args)


def lifecycle_and_store():
    store = MemoryStore()
    with store.transaction() as tx:
        tx.put("hooks", "hook-a", {"id": "hook-a", "status": "required", "revision": None, "spec": None, "author": None,
                                   "reviews": [], "version": 1, "canary": None})
    return HookLifecycle(packaged_organization(), outbox=Outbox(), events=EventJournal()), store


def test_the_chain_runs_in_the_callers_transaction_and_events_go_through_the_journal():
    from codex_harness.kernel.ids import digest

    lifecycle, store = lifecycle_and_store()
    sha = digest(ALIAS)
    with store.transaction() as tx:
        assert lifecycle.propose("hook-a", "worker:implementation", ALIAS, "rev-1", transaction=tx)["status"] == "candidate"
        lifecycle.review("hook-a", "lead:improvement", "rev-1", sha, True, "ev-1", transaction=tx)
        lifecycle.review("hook-a", "conductor", "rev-1", sha, True, "ev-2", transaction=tx)
        assert lifecycle.record_canary("hook-a", "rev-1", sha, CHECKS, transaction=tx)["status"] == "verified"
        assert lifecycle.activate("hook-a", transaction=tx)["status"] == "active"
        assert lifecycle.prepare_command(["python", "-V"], "windows", transaction=tx) == ["py", "-V"]
        assert [h["id"] for h in lifecycle.active_hooks(transaction=tx)] == ["hook-a"]
        lifecycle.rollback("hook-a", "regression", transaction=tx)
        assert lifecycle.get_hook("hook-a", transaction=tx)["status"] == "rolled_back"
        events = sorted(r["body"]["type"] for r in tx.records() if r["bucket"] == "events")
    assert events == ["hook.activated", "hook.proposed", "hook.rolled_back"]


def test_refusals_leave_the_unit_to_the_caller_and_name_the_contract():
    lifecycle, store = lifecycle_and_store()
    with store.transaction() as tx:
        with pytest.raises(ContractError, match="Actor lacks required role"):
            lifecycle.propose("hook-a", "lead:improvement", ALIAS, "rev-1", transaction=tx)
        with pytest.raises(ContractError, match="Hook not found"):
            lifecycle.get_hook("hook-none", transaction=tx)
        with pytest.raises(ContractError, match="Candidate not verified"):
            lifecycle.activate("hook-a", transaction=tx)
        with pytest.raises(ContractError, match="Rollback requires reason"):
            lifecycle.rollback("hook-a", "", transaction=tx)
        with pytest.raises(ContractError, match="Canary needs reproduction"):
            lifecycle.record_canary("hook-a", "rev-1", "x", {"reproduction": True}, transaction=tx)
