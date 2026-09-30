"""Executable dependency rules: the one precedence-free allowed-edge table (REBUILD-DESIGN-v2 §3.6, F5).

An edge is allowed iff its importer row lists it; nothing overrides anything; unlisted is forbidden.
Edges counted: absolute and relative imports, module-level, function-local and `if TYPE_CHECKING:`
imports, and `importlib.import_module("<literal>")`. `from P import n` resolves to `P.n` when that is
a module in the tree, else to `P`. A non-literal dynamic import is itself a violation. The SCC check
uses the same edge set. `D(X)` is the direct row of X in the §2.4 DAG (not its transitive closure);
D(observation) is every other context's domain. The exception list is empty from the start.
"""

from __future__ import annotations

import ast
import re
import sys
from dataclasses import dataclass
from pathlib import Path

CONTEXTS = ("storage", "host_os", "routing", "context", "knowledge", "intake", "coordination",
            "execution", "credentials", "evidence", "review", "research", "delivery", "observation")
DAG = {
    "routing": (), "knowledge": (), "evidence": (), "credentials": (), "storage": (),
    "intake": ("routing",),
    "host_os": (),
    "context": ("routing", "knowledge"),
    "execution": ("routing", "context", "evidence", "credentials"),
    "review": ("routing", "evidence"),
    "research": ("routing", "evidence", "knowledge", "intake"),
    "delivery": ("review", "evidence"),
    "coordination": ("routing", "intake", "evidence", "execution", "review", "research", "delivery"),
    "observation": tuple(c for c in CONTEXTS if c != "observation"),
}
SHIMS = frozenset({"codex_harness.cli", "codex_harness.monitor", "codex_harness.supervisor",
                   "codex_harness.adapters.isolated_worker_entry", "codex_harness.adapters.continuation_process",
                   "codex_harness.adapters.worker_profile_metadata", "codex_harness.container_main"})
# Package __init__ modules that only hold shims/resources; they must not import anything.
PACKAGE_INITS = frozenset({"codex_harness.adapters", "codex_harness.resources"})
RES = frozenset({"codex_harness.resources.worker_profile_hook"})
SDK = frozenset({"psycopg", "redis", "tree_sitter", "tree_sitter_python", "jsonschema", "yaml",
                 "filelock", "fastembed"})
SUBP = frozenset({"subprocess"})
EXCEPTIONS: tuple = ()  # §3.6: empty from the start; it may only shrink.
MAX_PORT_METHODS = 6
LAYERS = {"domain": "dom", "application": "app", "adapters": "adp"}


@dataclass(frozen=True, order=True)
class Violation:
    module: str
    target: str
    rule: str


def classify(module: str) -> tuple[str, str | None]:
    """(class, context) for a codex_harness/zeus module name, or ("UNCLASSIFIED", None)."""
    if module in SHIMS or module.split(".")[0] == "zeus":
        return "SHIM", None
    if module in RES:
        return "RES", None
    parts = module.split(".")
    if parts[0] != "codex_harness":
        return "UNCLASSIFIED", None
    if len(parts) == 1:
        return "ROOT", None
    head = parts[1]
    if head == "kernel":
        return "K", "kernel"
    if head == "composition":
        return "COMP", None
    if head == "entry":
        return "ENTRY", None
    if module in PACKAGE_INITS:
        return "PKGINIT", None
    if head in CONTEXTS:
        if len(parts) == 2:
            return "CTXPKG", head
        if parts[2] == "ports" and len(parts) == 3:
            return "port", head
        if parts[2] in LAYERS:
            return LAYERS[parts[2]], head
    return "UNCLASSIFIED", None


def _domain_of(ctx: str) -> set[str]:
    return {f"{c}.dom" for c in DAG.get(ctx, ())}


def allowed(importer: str, target: str) -> bool:
    ic, ix = classify(importer)
    tc, tx = classify(target)
    t = f"{tx}.{tc}" if tc in {"dom", "port", "app", "adp"} else tc
    sp = {"storage.port", "host_os.port"}
    if ic == "K":
        return t == "K"
    if ic in {"dom", "port", "app", "adp"}:
        own = {"dom": {f"{ix}.dom"},
               "port": {f"{ix}.port", f"{ix}.dom"},
               "app": {f"{ix}.app", f"{ix}.dom", f"{ix}.port"},
               "adp": {f"{ix}.adp", f"{ix}.app", f"{ix}.dom", f"{ix}.port"}}[ic]
        extra = sp if ic != "dom" else set()
        return t == "K" or t in own or t in _domain_of(ix) or t in extra
    if ic == "COMP":
        return t in {"COMP", "K"} or tc in {"dom", "port", "app", "adp"}
    if ic == "ENTRY":
        return t in {"ENTRY", "COMP", "K"} or tc in {"dom", "app"}
    if ic == "SHIM":
        return t == "ENTRY"
    return False


def external_allowed(importer: str, top: str) -> bool:
    ic, _ = classify(importer)
    stdlib = top in sys.stdlib_module_names
    if ic in {"K", "dom", "port", "app"}:
        return stdlib and top not in SUBP
    if ic == "adp":
        return stdlib or top in SDK
    if ic == "COMP":
        return stdlib or top in SDK
    if ic == "ENTRY":
        return stdlib
    if ic == "RES":
        return stdlib
    return False


class Tree:
    """The modules of one source root (the directory that contains `codex_harness`)."""

    def __init__(self, root: Path):
        self.root = root
        self.files: dict[str, Path] = {}
        for path in sorted(root.rglob("*.py")):
            rel = path.relative_to(root).with_suffix("")
            parts = list(rel.parts)
            if parts[0] not in {"codex_harness", "zeus"}:
                continue
            is_pkg = parts[-1] == "__init__"
            if is_pkg:
                parts.pop()
            self.files[".".join(parts)] = path
        self.packages = {m for m, p in self.files.items() if p.name == "__init__.py"}

    def resolve_from(self, base: str, name: str) -> str:
        candidate = f"{base}.{name}" if base else name
        return candidate if candidate in self.files else base


def edges(tree: Tree, module: str) -> tuple[list[tuple[str, str]], list[Violation]]:
    """([(target, kind)], violations); kind is 'internal' or 'external'."""
    path = tree.files[module]
    source = ast.parse(path.read_text(encoding="utf-8"), str(path))
    package = module if module in tree.packages else module.rpartition(".")[0]
    out, bad = [], []

    def internal(name: str) -> bool:
        return name.split(".")[0] in {"codex_harness", "zeus"}

    for node in ast.walk(source):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if internal(alias.name):
                    out.append((alias.name, "internal"))
                else:
                    out.append((alias.name.split(".")[0], "external"))
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                parts = package.split(".")
                base_parts = parts[: len(parts) - node.level + 1]
                base = ".".join(base_parts + ([node.module] if node.module else []))
            else:
                base = node.module or ""
            if internal(base):
                for alias in node.names:
                    out.append((tree.resolve_from(base, alias.name), "internal"))
            else:
                out.append((base.split(".")[0], "external"))
        elif isinstance(node, ast.Call):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if name in {"import_module", "__import__"}:
                arg = node.args[0] if node.args else None
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    target = arg.value
                    out.append((target, "internal") if internal(target)
                               else (target.split(".")[0], "external"))
                else:
                    bad.append(Violation(module, "<dynamic>", "non-literal dynamic import"))
            elif isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) \
                    and func.value.id == "os" and (func.attr.startswith(("exec", "spawn"))
                                                    or func.attr == "posix_spawn"):
                out.append(("subprocess", "external"))  # os.exec*/os.posix_spawn count as SUBP
    return out, bad


def check_edges(tree: Tree) -> list[Violation]:
    violations = []
    for module in sorted(tree.files):
        cls, _ = classify(module)
        if cls in {"ROOT", "CTXPKG", "PKGINIT"}:
            found, bad = edges(tree, module)
            violations += bad + [Violation(module, t, "package __init__ must not import")
                                 for t, _ in found]
            continue
        if cls == "UNCLASSIFIED":
            violations.append(Violation(module, "", "unclassified module"))
            continue
        found, bad = edges(tree, module)
        violations += bad
        for target, kind in found:
            if kind == "internal":
                tcls, _ = classify(target)
                if target in tree.packages and tcls in {"CTXPKG", "ROOT"}:
                    violations.append(Violation(module, target, "import of a bare package"))
                elif not allowed(module, target):
                    violations.append(Violation(module, target, f"{cls} -> {tcls} not in the table"))
            elif not external_allowed(module, target):
                violations.append(Violation(module, target, f"{cls} -> external {target} not allowed"))
    return violations


def sccs(tree: Tree) -> list[list[str]]:
    graph = {m: sorted({t for t, k in edges(tree, m)[0] if k == "internal" and t in tree.files
                        and t != m}) for m in tree.files}
    index, low, stack, on, out = {}, {}, [], set(), []
    counter = [0]

    def visit(v):
        index[v] = low[v] = counter[0]
        counter[0] += 1
        stack.append(v)
        on.add(v)
        for w in graph[v]:
            if w not in index:
                visit(w)
                low[v] = min(low[v], low[w])
            elif w in on:
                low[v] = min(low[v], index[w])
        if low[v] == index[v]:
            comp = []
            while True:
                w = stack.pop()
                on.discard(w)
                comp.append(w)
                if w == v:
                    break
            if len(comp) > 1:
                out.append(sorted(comp))

    for v in sorted(graph):
        if v not in index:
            visit(v)
    return out


def port_violations(tree: Tree) -> list[Violation]:
    out = []
    for module, path in tree.files.items():
        if classify(module)[0] != "port" and not module.endswith(".kernel.ports"):
            continue
        for node in ast.parse(path.read_text(encoding="utf-8")).body:
            if isinstance(node, ast.ClassDef) and any(
                    getattr(b, "id", getattr(b, "attr", "")) == "Protocol" for b in node.bases):
                methods = [n for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
                if len(methods) > MAX_PORT_METHODS:
                    out.append(Violation(module, node.name, f"Protocol has {len(methods)} methods (> 6)"))
    return out


LABEL = re.compile(r"^(Layer|Context|Contracts):\s*(.+)$", re.MULTILINE)


def label_violations(tree: Tree, contract_ids: set[str]) -> list[Violation]:
    out = []
    for module, path in tree.files.items():
        doc = ast.get_docstring(ast.parse(path.read_text(encoding="utf-8"))) or ""
        cls, ctx = classify(module)
        for field, value in LABEL.findall(doc):
            value = value.strip()
            if field == "Context" and ctx is not None and value != ctx:
                out.append(Violation(module, value, "Context label does not match the path"))
            if field == "Layer":
                expected = {"dom": "domain", "app": "application", "adp": "adapters", "port": "ports",
                            "K": "kernel", "COMP": "composition", "ENTRY": "entry"}.get(cls)
                if expected is not None and value != expected:
                    out.append(Violation(module, value, "Layer label does not match the path"))
            if field == "Contracts":
                for ident in re.findall(r"INV-[A-Z0-9-]+-\d{3}", value):
                    if ident not in contract_ids:
                        out.append(Violation(module, ident, "Contracts label does not resolve"))
    return out


PUT = re.compile(r"""\btx\.put\(\s*["']([A-Za-z0-9_.:-]+)["']""")


def single_writer_violations(tree: Tree) -> list[Violation]:
    """A literal `tx.put("<bucket>"` occurs only in the context whose ports declare OWNED_BUCKETS."""
    owners = {}
    for module, path in tree.files.items():
        cls, ctx = classify(module)
        if cls != "port":
            continue
        for node in ast.parse(path.read_text(encoding="utf-8")).body:
            if (isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "OWNED_BUCKETS"
                                                     for t in node.targets)):
                for bucket in ast.literal_eval(node.value):
                    owners[bucket] = ctx
    out = []
    for module, path in tree.files.items():
        _, ctx = classify(module)
        for bucket in PUT.findall(path.read_text(encoding="utf-8")):
            owner = owners.get(bucket)
            if owner is None:
                out.append(Violation(module, bucket, "bucket has no declared owner"))
            elif owner != ctx:
                out.append(Violation(module, bucket, f"write to {owner}-owned bucket"))
    return out


def check(root: Path, contract_ids: set[str] | None = None) -> list[Violation]:
    tree = Tree(root)
    found = check_edges(tree) + port_violations(tree) + single_writer_violations(tree)
    found += [Violation(",".join(c), "", "import cycle (SCC)") for c in sccs(tree)]
    if contract_ids is not None:
        found += label_violations(tree, contract_ids)
    return sorted(set(v for v in found if (v.module, v.target, v.rule) not in EXCEPTIONS))
