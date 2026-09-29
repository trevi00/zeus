"""Reference driver: goldens captured statically from the tracked SOURCE bytes (REBUILD-DESIGN-v2 §5.3 S0).

Scenario family `static.source`. Reads the SOURCE archive tree only (no import of the package):
- child argv: `*ARGV*` constants and argv displays in the lane launcher, owner-actions research
  child, continuation guardian and role-container modules, as byte goldens (text + sha256);
- the permanent entry-shim inventory (§3.5) and the pinned-argv scan of tracked files for the 11
  conditional `__main__` modules; reconciliation with persisted argv is pending R2;
- bucket static access candidates (`<tx>.get/put/scan/entries("<literal>"`); candidates only,
  dynamic bucket names can exist;
- schema literal declarations (`zeus.*`, `urn:zeus:*`);
- the atomic-unit catalogue (§2.9 rule 1): every `with <x>.transaction(...) as <tx>:` block with its
  literal bucket writes, `transaction=<tx>` / `<tx>`-argument callees, fence calls and external-effect
  calls inside the block. Static depth 1: callee writes are listed as untraced.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "harness"))

import driver  # noqa: E402

driver.start("reference")

import ast  # noqa: E402
import hashlib  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402

SOURCE = Path(os.environ["ZEUS_REBUILD_SOURCE_ROOT"]).resolve()
PKG = SOURCE / "src" / "codex_harness"
ARGV_MODULES = {
    "lane_launcher_operate_run": "src/codex_harness/adapters/fleet_runtime.py",
    "owner_actions_research_child": "src/codex_harness/adapters/owner_actions.py",
    "continuation_guardian_child": "src/codex_harness/adapters/continuation_process.py",
    "role_container_argv": "src/codex_harness/adapters/role_containers.py",
}
# Pure argv builders captured whole (source text + sha256): the per-profile docker argv.
ARGV_FUNCTIONS = {"role_container_docker_argv": ("src/codex_harness/adapters/isolated_worker.py",
                                                 "container_args")}
ARGV_TOKENS = {"-m", "operate", "run", "--launch", "conduct", "research-program", "--network",
               "--read-only", "--cap-drop", "--user", "--rm", "--init", "--mount", "-v", "--volume"}
SHIMS_UNCONDITIONAL = ["codex_harness.cli", "codex_harness.monitor", "codex_harness.supervisor",
                       "codex_harness.adapters.isolated_worker_entry",
                       "codex_harness.adapters.worker_profile_metadata", "codex_harness.container_main",
                       "codex_harness.resources.worker_profile_hook", "zeus"]
SHIMS_CONDITIONAL = ["artifact_reader", "continuation_process", "managed_runtime", "host_delivery",
                     "host_migration", "migrations", "service_entry", "experience", "observed_assets",
                     "monitor_frontend_checks", "isolated_worker"]
FENCE_NAMES = {"_owned", "require_current_fence", "check_expected", "require_expected",
               "_same_execution", "active", "require_lease", "_require_lease", "fence", "_fenced",
               "validate_decision", "require_owner", "_controller", "_require_controller"}
EFFECT_HINTS = ("subprocess", "Popen", "urlopen", "requests", "push", "merge", "docker", "spawn",
                "runtime.run", "_run", "publish", "systemctl", "os.replace", "shutil.move")
SCHEMA = re.compile(r"^(zeus[.:][A-Za-z0-9_.:/-]+|urn:zeus:[A-Za-z0-9_.:-]+)$")


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def rel(path: Path) -> str:
    return path.relative_to(SOURCE).as_posix()


def module_name(path: Path) -> str:
    parts = list(path.relative_to(SOURCE / "src").with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


class Scope(ast.NodeVisitor):
    """Visit with the enclosing qualname available."""

    def __init__(self):
        self.stack = []

    def qual(self):
        return ".".join(self.stack) or "<module>"

    def _scoped(self, node):
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()

    visit_FunctionDef = visit_AsyncFunctionDef = visit_ClassDef = _scoped


def child_argv() -> dict:
    out = {}
    for label, path in ARGV_MODULES.items():
        text = (SOURCE / path).read_text(encoding="utf-8")
        tree = ast.parse(text)
        rows = []

        class V(Scope):
            def visit_Assign(self, node):
                names = [t.id for t in node.targets if isinstance(t, ast.Name)]
                if any("ARGV" in n.upper() for n in names):
                    seg = ast.get_source_segment(text, node)
                    rows.append({"kind": "constant", "scope": self.qual(), "line": node.lineno,
                                 "text": seg, "sha256": sha(seg)})
                self.generic_visit(node)

            def _display(self, node):
                consts = {e.value for e in node.elts if isinstance(e, ast.Constant)
                          and isinstance(e.value, str)}
                if consts & ARGV_TOKENS and len(node.elts) >= 2:
                    seg = ast.get_source_segment(text, node)
                    rows.append({"kind": "display", "scope": self.qual(), "line": node.lineno,
                                 "text": seg, "sha256": sha(seg)})
                self.generic_visit(node)

            visit_List = visit_Tuple = _display

        V().visit(tree)
        out[label] = {"path": path, "module_sha256": sha(text), "rows": rows}
    for label, (path, name) in ARGV_FUNCTIONS.items():
        text = (SOURCE / path).read_text(encoding="utf-8")
        node = next(n for n in ast.parse(text).body if isinstance(n, ast.FunctionDef) and n.name == name)
        seg = ast.get_source_segment(text, node)
        out[label] = {"path": path, "module_sha256": sha(text), "rows": [
            {"kind": "function", "scope": name, "line": node.lineno, "text": seg, "sha256": sha(seg)}]}
    return out


def tracked_files():
    for root, dirs, files in os.walk(SOURCE):
        dirs[:] = sorted(d for d in dirs if d not in {".git", "node_modules", "__pycache__"})
        for name in sorted(files):
            yield Path(root) / name


def path_class(path: str) -> str:
    top = path.split("/", 1)[0]
    if path.startswith("docs/context/") or path in {"AGENTS.md"}:
        return "contract_docs"
    return {"src": "src", "tests": "tests", "deploy": "deploy", "scripts": "scripts",
            "docs": "docs_history"}.get(top, "other")


def shim_inventory() -> dict:
    patterns = {name: re.compile(r"codex_harness[./]adapters[./]" + name + r"\b")
                for name in SHIMS_CONDITIONAL}
    hits = {name: {} for name in SHIMS_CONDITIONAL}
    for path in tracked_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        r = rel(path)
        own = {f"src/codex_harness/adapters/{name}.py" for name in SHIMS_CONDITIONAL}
        for name, pattern in patterns.items():
            for lineno, line in enumerate(text.splitlines(), 1):
                if r in own and r.endswith("/" + name + ".py"):
                    continue
                if pattern.search(line) and ("-m" in line or '"-m"' in line or "'-m'" in line):
                    hits[name].setdefault(path_class(r), []).append(f"{r}:{lineno}")
    for name in SHIMS_CONDITIONAL:
        # The module's own code (not its docstring) naming itself as a child argv is a pin too.
        path = PKG / "adapters" / (name + ".py")
        tree = ast.parse(path.read_text(encoding="utf-8"))
        doc = ast.get_docstring(tree, clean=False)
        for node in ast.walk(tree):
            if (isinstance(node, ast.Constant) and node.value == "codex_harness.adapters." + name
                    and node.value != doc):
                hits[name].setdefault("self_code", []).append(f"{rel(path)}:{node.lineno}")
    conditional = {}
    for name, found in hits.items():
        pinned = {k: v for k, v in found.items() if k in {"src", "deploy", "scripts", "contract_docs",
                                                            "other", "self_code"}}
        conditional["codex_harness.adapters." + name] = {
            "keep_shim": bool(pinned),
            "references_by_class": {k: len(v) for k, v in sorted(found.items())},
            "pinning_references": sorted(x for v in pinned.values() for x in v)[:20],
        }
    return {"unconditional": SHIMS_UNCONDITIONAL, "conditional": conditional,
            "persisted_argv_reconciliation": "pending R2 (disposable rehearsal)"}


def is_tx(node) -> bool:
    name = node.id if isinstance(node, ast.Name) else node.attr if isinstance(node, ast.Attribute) else ""
    low = name.lower()
    return (low in {"tx", "txn"} or low.endswith("_tx") or low.startswith("tx_")
            or "transaction" in low)


def constants(tree) -> dict:
    out = {}
    for node in tree.body:
        if (isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    out[target.id] = node.value.value
    return out


def literal_arg(node, names: dict):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return names.get(node.id)
    return None


def callee(node) -> str:
    try:
        return ast.unparse(node.func)
    except Exception:  # noqa: BLE001 - unparse of odd nodes
        return "<call>"


def python_modules():
    for path in sorted(PKG.rglob("*.py")):
        yield path


def buckets_schemas_units() -> tuple[dict, dict, list]:
    buckets, schemas, units = {}, {}, []
    for path in python_modules():
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text)
        mod = module_name(path)
        names = constants(tree)
        counters = {}

        class V(Scope):
            def visit_Call(self, node):
                f = node.func
                bucket = literal_arg(node.args[0], names) if node.args else None
                if (isinstance(f, ast.Attribute) and f.attr in {"get", "put", "scan", "entries"}
                        and is_tx(f.value) and bucket is not None):
                    buckets.setdefault(bucket, set()).add((f.attr, mod))
                self.generic_visit(node)

            def visit_Constant(self, node):
                if isinstance(node.value, str) and SCHEMA.match(node.value):
                    schemas.setdefault(node.value, set()).add(rel(path))

            def visit_With(self, node):
                for item in node.items:
                    ctx = item.context_expr
                    if (isinstance(ctx, ast.Call) and isinstance(ctx.func, ast.Attribute)
                            and ctx.func.attr == "transaction" and isinstance(item.optional_vars, ast.Name)):
                        self.unit(node, item.optional_vars.id)
                self.generic_visit(node)

            def unit(self, node, tx):
                q = self.qual()
                counters[q] = counters.get(q, 0) + 1
                writes, passes, fences, effects = set(), set(), set(), set()
                for sub in ast.walk(node):
                    if not isinstance(sub, ast.Call):
                        continue
                    name = callee(sub)
                    f = sub.func
                    if (isinstance(f, ast.Attribute) and f.attr == "put" and isinstance(f.value, ast.Name)
                            and f.value.id == tx and sub.args and literal_arg(sub.args[0], names)):
                        writes.add(literal_arg(sub.args[0], names))
                    elif (isinstance(f, ast.Attribute) and f.attr == "put" and isinstance(f.value, ast.Name)
                            and f.value.id == tx):
                        writes.add("<dynamic>")
                    uses_tx = any(isinstance(a, ast.Name) and a.id == tx for a in sub.args) or any(
                        k.arg in {"transaction", "tx"} and isinstance(k.value, ast.Name) and k.value.id == tx
                        for k in sub.keywords)
                    short = name.rsplit(".", 1)[-1]
                    if short in FENCE_NAMES:
                        fences.add(name)
                    elif uses_tx and not (isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name)
                                          and f.value.id == tx):
                        passes.add(name)
                    if any(h in name for h in EFFECT_HINTS):
                        effects.add(name)
                units.append({"key": f"{mod}:{q}#{counters[q]}", "module": mod, "path": rel(path),
                              "scope": q, "line": node.lineno, "tx": tx,
                              "literal_writes": sorted(writes), "tx_passing_calls": sorted(passes),
                              "fence_calls": sorted(fences), "effect_hint_calls": sorted(effects)})

        V().visit(tree)
    return ({k: sorted(map(list, v)) for k, v in sorted(buckets.items())},
            {k: sorted(v) for k, v in sorted(schemas.items())}, units)


def main() -> None:
    buckets, schemas, units = buckets_schemas_units()
    result = {
        "source_tree_files": sum(1 for _ in tracked_files()),
        "child_argv": child_argv(),
        "shims": shim_inventory(),
        "bucket_candidates": {"count": len(buckets), "names": sorted(buckets),
                              "accesses": buckets,
                              "caveat": "static candidates; dynamic bucket names can exist"},
        "schema_literals": {"count": len(schemas), "values": schemas},
        "transaction_blocks": {"count": len(units), "units": units,
                               "caveat": "static depth 1; callee writes and runtime paths untraced"},
    }
    driver.finish("reference", "static.source", result)


if __name__ == "__main__":
    main()
