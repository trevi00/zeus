"""S8 pilot 97 (DESIGN-s8 §16 V21): M7 `application/fleet_backlog.py` moves to `coordination.application.fleet_backlog` VERBATIM through named rules
(R-fb0 import homes, R-fb1 `Fleet` is `FleetRegistry`; A/evidence/rebuild/s8/fleet-backlog-move/transcribe.py).

M7 is read only as text through `git show e38aa722:...` and compared by AST (never imported: both packages are named `codex_harness`). Behaviour is
checked on the TARGET only, against literals; the recorded comparison is the `coordination.fleet_backlog` golden."""

from __future__ import annotations

import ast
import importlib
import inspect
import subprocess
from pathlib import Path

from _layout import REPO, TARGET

SRC = TARGET / "src" / "codex_harness"
SOURCE = "e38aa722"
APP = "codex_harness.coordination.application.fleet_backlog"
M7_PATH = "src/codex_harness/application/fleet_backlog.py"
M7_FLEET = "src/codex_harness/application/fleet.py"
BUCKETS = ("fleet_backlog_plans", "fleet_backlog_intents")
BACKLOG_HOME = "codex_harness.intake.domain.backlog"
HOMES = {"__future__": ["annotations"], "logging": [],
         "codex_harness.coordination.application.fleet.registry": ["FleetRegistry"],
         "codex_harness.coordination.application.fleet.state": ["BUCKET_CONTROL", "BUCKET_JOBS", "CONTROL_KEY"],
         "codex_harness.coordination.domain.fleet": ["FleetRefused"],
         "codex_harness.coordination.domain.operation": ["manifest_digest"],
         "codex_harness.intake.domain.portfolio": ["PortfolioRefused"], "codex_harness.kernel.ids": ["utcnow"]}


def m7_text(path=M7_PATH):
    return subprocess.run(["git", "-C", str(REPO), "show", f"{SOURCE}:{path}"], check=True, capture_output=True, text=True).stdout


def target_text(module=APP):
    return Path(importlib.import_module(module).__file__).read_text()


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


def imports(src):
    found = {}
    for node in ast.parse(src).body:
        if isinstance(node, ast.ImportFrom):
            found.setdefault(node.module, []).extend(a.name for a in node.names)
        elif isinstance(node, ast.Import):
            for a in node.names:
                found.setdefault(a.name, [])
    return found


class Registry(ast.NodeTransformer):
    """R-fb1 on M7's AST: `Fleet` -> `FleetRegistry`."""

    def visit_Name(self, node):
        return ast.copy_location(ast.Name(id="FleetRegistry", ctx=node.ctx), node) if node.id == "Fleet" else node


def signature(src, klass, name):
    node = next(n for n in statements(src)[(klass,)].body if isinstance(n, ast.FunctionDef) and n.name == name)
    args = node.args
    return ([a.arg for a in args.posonlyargs + args.args], [a.arg for a in args.kwonlyargs], [ast.unparse(d) for d in args.defaults],
            args.vararg and args.vararg.arg, args.kwarg and args.kwarg.arg)


def writers(values, names):
    """Relative paths of target modules with a `.put`/`.delete` whose first argument is one of `values` (a literal) or one of `names` that the module
    imports from the backlog home or this module (a same-named constant of another bucket, e.g. the continuation's, is not these buckets)."""
    found = set()
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text())
        bound = {a.asname or a.name for n in tree.body if isinstance(n, ast.ImportFrom) and n.module in (BACKLOG_HOME, APP) for a in n.names}
        for call in ast.walk(tree):
            if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) and call.func.attr in ("put", "delete") and call.args:
                first = call.args[0]
                if (isinstance(first, ast.Constant) and first.value in values) or (isinstance(first, ast.Name) and first.id in names and first.id in bound):
                    found.add(path.relative_to(SRC).as_posix())
    return found


# ---- the transcription: AST against M7 ---------------------------------------------------------------------------------
def test_every_statement_is_m7s_in_m7_order_modulo_r_fb1_and_the_one_removed_assignment():
    ref, ours = statements(m7_text()), statements(target_text())
    removed = ("BUCKET_PLANS", "BUCKET_INTENTS")
    assert list(ref) == [removed, ("LOGGER",), ("OBSERVED_OUTCOMES",), ("FleetBacklog",), ("__all__",)]
    assert list(ours) == [k for k in ref if k != removed]
    for key in ours:
        assert ast.dump(ours[key]) == ast.dump(Registry().visit(ast.Module(body=[ref[key]], type_ignores=[])).body[0]), key


def test_r_fb1_only_the_import_the_annotation_and_the_default_construction_name_the_fleet():
    ref, ours = m7_text(), target_text()
    init = next(n for n in statements(ours)[("FleetBacklog",)].body if isinstance(n, ast.FunctionDef) and n.name == "__init__")
    assert ast.unparse(init.args) == "self, store, fleet: FleetRegistry | None=None, clock=utcnow, portfolio=None, observer=None"
    assert "self.fleet = FleetRegistry(store) if fleet is None else fleet" in ast.unparse(init)
    assert not [n for n in ast.walk(ast.parse(ours)) if isinstance(n, ast.Name) and n.id == "Fleet"]
    assert [n.id for n in ast.walk(ast.parse(ref)) if isinstance(n, ast.Name) and n.id == "Fleet"] == ["Fleet", "Fleet"]


def test_r_fb0_the_import_homes_are_exactly_the_v21_homes_and_the_buckets_come_from_intake():
    ref, ours = imports(m7_text()), imports(target_text())
    names = ours.pop(BACKLOG_HOME)
    assert {k: sorted(v) for k, v in ours.items()} == {k: sorted(v) for k, v in HOMES.items()}
    assert sorted(names) == sorted([n for n in ref["codex_harness.domain.fleet_backlog"]] + list(BUCKETS_NAMES()))
    for module in ours:
        assert not module.startswith(("codex_harness.adapters", "codex_harness.domain", "codex_harness.application")), module
    for module, wanted in {**HOMES, BACKLOG_HOME: names}.items():
        if module.startswith("codex_harness."):
            home = importlib.import_module(module)
            assert all(hasattr(home, name) for name in wanted), module


def BUCKETS_NAMES():
    return ("BUCKET_PLANS", "BUCKET_INTENTS")


def test_the_module_spawns_nothing_and_imports_no_adapter():
    tree = ast.parse(target_text())
    assert not [n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom)) and "subprocess" in ast.unparse(n)]
    assert "adapters" not in " ".join(imports(target_text()))


def test_header_names_context_layer_the_move_and_the_rules():
    header = target_text().split('"""')[1]
    for needle in ("Layer: application", "Context: coordination", "Owns:", "Does not own:", "Entry points:", "Contracts: INV-FLEET-BACKLOG-001",
                   "SOURCE e38aa722", "DESIGN-s8 §16 V21", "R-fb0", "R-fb1", "fleet-backlog-move/transcribe.py"):
        assert needle in header, needle
    assert header.startswith("Approved backlog admission into the existing Fleet (INV-FLEET-BACKLOG-001).")


# ---- the FleetRegistry member audit ------------------------------------------------------------------------------------
def test_the_only_fleet_member_the_module_uses_is_enqueue_and_fleet_registry_has_it_with_the_m7_signature():
    members = sorted({n.attr for n in ast.walk(ast.parse(target_text())) if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Attribute)
                      and n.value.attr == "fleet" and isinstance(n.value.value, ast.Name) and n.value.value.id == "self"})
    assert members == ["enqueue"]
    registry = target_text("codex_harness.coordination.application.fleet.registry")
    for member in members:
        assert signature(registry, "FleetRegistry", member) == signature(m7_text(M7_FLEET), "Fleet", member)
    assert signature(registry, "FleetRegistry", "enqueue")[0] == ["self", "lane_id", "manifest", "goal", "dependencies"]


# ---- the buckets: one declaration, one writer --------------------------------------------------------------------------
def test_v21_coordination_owns_the_two_buckets_and_only_this_module_writes_them():
    from codex_harness.coordination import ports

    module = importlib.import_module(APP)
    assert (module.BUCKET_PLANS, module.BUCKET_INTENTS) == BUCKETS
    for bucket in BUCKETS:
        assert ports.OWNED_BUCKETS.count(bucket) == 1, bucket
    for context in ("intake", "research", "evidence", "knowledge", "review", "delivery", "routing", "storage", "execution", "context"):
        other = importlib.import_module(f"codex_harness.{context}.ports") if (SRC / context / "ports.py").exists() else None
        assert other is None or not set(BUCKETS) & set(getattr(other, "OWNED_BUCKETS", ())), context
    assert writers(BUCKETS, ("BUCKET_PLANS", "BUCKET_INTENTS")) == {"coordination/application/fleet_backlog.py"}


def test_the_bucket_names_are_the_intake_domain_constants_and_exported():
    backlog = importlib.import_module(BACKLOG_HOME)
    module = importlib.import_module(APP)
    assert (backlog.BUCKET_PLANS, backlog.BUCKET_INTENTS) == BUCKETS
    assert module.BUCKET_PLANS is backlog.BUCKET_PLANS and module.BUCKET_INTENTS is backlog.BUCKET_INTENTS
    assert module.__all__ == ["BUCKET_INTENTS", "BUCKET_PLANS", "OBSERVED_OUTCOMES", "FleetBacklog", "LOGGER"]
    assert module.LOGGER.name == "zeus.fleet.backlog"
    assert sorted(module.OBSERVED_OUTCOMES) == ["conflict", "enqueued", "refused", "unavailable"]


# ---- the M7 caller shapes ----------------------------------------------------------------------------------------------
def test_the_m7_positional_shapes_and_the_default_fleet_are_kept():
    from codex_harness.coordination.application.fleet.registry import FleetRegistry
    from codex_harness.coordination.application.fleet_backlog import FleetBacklog
    from codex_harness.storage.adapters.memory_store import MemoryStore

    parameters = list(inspect.signature(FleetBacklog.__init__).parameters)
    assert parameters == ["self", "store", "fleet", "clock", "portfolio", "observer"]
    store = MemoryStore()
    default = FleetBacklog(store)
    assert isinstance(default.fleet, FleetRegistry) and default.fleet.store is store
    assert default.portfolio is None and default.observer is None
    given = FleetRegistry(store)
    marker, watcher = object(), object()
    explicit = FleetBacklog(store, given, portfolio=marker, observer=watcher)
    assert explicit.fleet is given and explicit.portfolio is marker and explicit.observer is watcher
    projection = FleetBacklog(store).status()
    assert projection == {"schema": "urn:zeus:fleet-backlog-status:1", "registered": False, "fleet_paused": False, "plans": [],
                          "authority": projection["authority"]}
    assert FleetBacklog(store).status("plan-1")["outcome"] == "plan_unregistered"
