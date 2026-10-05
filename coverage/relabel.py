"""Relabel `coverage/ledger-coverage.json` from its evidence (DESIGN-s11 §5, R-L1..R-L16).

Layer: harness (never shipped); standard library only; no product import.

    python coverage/relabel.py bundle --junit <xml> --compare <json>... --owner-run <path>... --head <sha>
    python coverage/relabel.py apply            # rewrite statuses + `verification` from rows + tree + bundle
    python coverage/relabel.py --check          # byte equality with the committed ledger (the CI guard)
    python coverage/relabel.py --check-fresh    # --check, and the evidence inputs are unchanged since the bundle head

The relabel never reads `A/` (the artifact store) and never runs tests. `bundle` is the one command that reads owner
artifacts: it maps the TI JUnit XML (xunit2) onto the collected node list at the evidence head (L3: classname = dotted
path without `.py` plus class parts, name = function plus `[params]`) and refuses on any mismatch. No status is
hand-edited (R-L12): a row's status is exactly what `relabel()` computes.
"""

from __future__ import annotations

import argparse
import ast
import collections
import copy
import hashlib
import json
import re
import subprocess
import sys
import tomllib
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import generate  # noqa: E402  (stdlib harness module: the one table serialisation)

LEDGER = HERE / "ledger-coverage.json"
BUNDLE = HERE / "run-evidence.json"
BUNDLE_SCHEMA = "zeus:s11-run-evidence:1"

# R-L14: the record that accepted each slice (named, never read). S10: S10-CLOSURE.md (ACCEPTED at 8f7fed5f).
ACCEPTED = {f"S{n}": f"FLEET-REBUILD-S{n}-ACCEPT.md" for n in range(1, 10)}
ACCEPTED["S10"] = "evidence/rebuild/s10/S10-CLOSURE.md (S10 ACCEPTED at 8f7fed5f1dc8847839121d1cd80ddf2bf1a8a84d)"

# R-L16: the owning-slice derivation of prep-e0dc49c4/gen_s11.py (PREP-S11 §2.2): DESIGN §5.3 owner -> slice.
OWNER_SLICE = {"kernel": "S1", "storage": "S1", "host_os": "S1", "routing": "S2", "context": "S2", "knowledge": "S2",
               "execution": "S3/S4", "credentials": "S3/S4", "coordination": "S5/S6", "delivery": "S7",
               "review": "S8", "research": "S8", "intake": "S8", "evidence": "S8", "observation": "S9",
               "composition": "S10", "entry": "S10"}

# R-L7: the node that enforces the single-writer rule: `import_rules.check` includes `single_writer_violations`
# (a literal `tx.put("<bucket>"` occurs only in the context whose ports declare OWNED_BUCKETS) and the test asserts
# the empty result for the whole target tree.
SINGLE_WRITER_NODE = "tests/test_architecture.py::test_target_tree_has_no_violation_and_no_exception"
CAPABILITY_DOC = "docs/context/ARCHITECTURE.md"
HOST_MIGRATION = "codex_harness.delivery.adapters.host_migration"
HOST_MIGRATION_TEST = "target:tests/ported/test_host_migration_successor.py"
# R-L7 / S10-PACKET §4b (OWNER-DECISIONS-S11 #9): the four `unmapped` ledger buckets. Maintained fields only; applied
# idempotently by `relabel()`. discovery_pressure is a real bucket (it follows the bucket rule); the three others are
# constants of host_migration.py, verified through the symbol that defines them and its passing ported test.
UNMAPPED_BUCKETS = {
    "bucket:discovery_pressure": {
        "target_owner": "research", "target_symbol": ["codex_harness.research.ports.OWNED_BUCKETS"],
        "mapping_correction": "a real bucket (S10-PACKET §4b): the write goes through the BUCKET constant the "
                              "generator's literal-only scan misses"},
    "bucket:fleet-owner.json": {
        "target_owner": "delivery", "target_symbol": [HOST_MIGRATION + ":FLEET_OWNER_FILE"],
        "mapping_correction": "not a bucket (S10-PACKET §4b): FLEET_OWNER_FILE constant (a file name)",
        "add_evidence": [HOST_MIGRATION_TEST]},
    "bucket:urn:zeus:aibox-fleet-owner:1": {
        "target_owner": "delivery", "target_symbol": [HOST_MIGRATION + ":FLEET_OWNER_SCHEMA"],
        "mapping_correction": "not a bucket (S10-PACKET §4b): FLEET_OWNER_SCHEMA constant (a schema URN)",
        "add_evidence": [HOST_MIGRATION_TEST]},
    "bucket:zeus-aibox-fleet.service": {
        "target_owner": "delivery", "target_symbol": [HOST_MIGRATION + ":SWITCH_UNITS"],
        "mapping_correction": "not a bucket (S10-PACKET §4b): SWITCH_UNITS constant (systemd unit names)",
        "add_evidence": [HOST_MIGRATION_TEST]},
}

EXEC = "exec"  # an executable item: it can pass or fail
CONTEXT = "context"  # a declaration or a SOURCE fact: never passing evidence
PENDING = "pending"  # an owed promise


class Refused(Exception):
    """A refusal with a named cause (exit 1)."""


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git(root: Path, *args: str, check: bool = True) -> str:
    done = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
    if check and done.returncode:
        raise Refused(f"git {' '.join(args)} failed: {done.stderr.strip()[:200]}")
    return done.stdout


# ---------------------------------------------------------------------------------------------------- the bundle (R-L1)

def mangle(node: str) -> tuple[str, str]:
    """pytest's junitxml mangling (L3): (classname, name) of a collected node ID."""
    path, bracket, params = node.partition("[")
    names = path.split("::")
    names[0] = re.sub(r"\.py$", "", names[0].replace("/", "."))
    names[-1] += bracket + params
    return ".".join(names[:-1]), names[-1]


def read_junit(path: Path) -> dict[tuple[str, str], str]:
    """(classname, name) -> 'passed' or the worst child ('error', 'failure', 'skipped', 'xfail')."""
    out: dict[tuple[str, str], str] = {}
    for case in ET.parse(path).getroot().iter("testcase"):
        key = (case.get("classname", ""), case.get("name", ""))
        outcome = "passed"
        for child in case:
            if child.tag in ("error", "failure"):
                outcome = child.tag
                break
            if child.tag == "skipped":
                outcome = "xfail" if child.get("type") == "pytest.xfail" else "skipped"
        if key in out:  # a second testcase of one node: a teardown error after a pass, or the reverse
            if out[key] == "passed" and outcome == "passed":
                raise Refused(f"duplicate testcase for node {key[0]}::{key[1]}")
            rank = ("passed", "xfail", "skipped", "failure", "error")
            outcome = max(out[key], outcome, key=rank.index)
        out[key] = outcome
    return out


def collect_nodes(root: Path) -> list[str]:
    """The node list of `cd target && uv run --frozen pytest --collect-only -q -p no:cacheprovider`."""
    done = subprocess.run(["uv", "run", "--frozen", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider"],
                          cwd=root / "target", capture_output=True, text=True)
    if done.returncode:
        raise Refused(f"collect-only exited {done.returncode}: {done.stdout[-300:]}{done.stderr[-300:]}")
    return parse_collected(done.stdout)


def parse_collected(text: str) -> list[str]:
    nodes = [ln for ln in text.splitlines() if "::" in ln and not ln.startswith((" ", "=", "E ", "ERROR", "FAILED"))]
    summary = re.search(r"^(\d+) tests? collected", text, re.M)
    if not summary or int(summary.group(1)) != len(nodes):
        raise Refused(f"collection summary does not match the {len(nodes)} listed nodes")
    return nodes


def is_test_module(path: str) -> bool:
    return path.startswith("target/tests/") and path.endswith(".py") and Path(path).name.startswith("test_")


def head_files(root: Path, rev: str) -> dict[str, str]:
    """`git ls-tree -r <rev> target/tests` -> path -> blob id."""
    out = {}
    for line in git(root, "ls-tree", "-r", rev, "--", "target/tests").splitlines():
        meta, path = line.split("\t", 1)
        out[path] = meta.split()[2]
    return out


def bound_ids(root: Path, rev: str) -> dict[str, str]:
    return {p: git(root, "rev-parse", f"{rev}:{p}").strip()
            for p in ("target/src", "compare", "target/pyproject.toml", "target/uv.lock")}


def artifact_path(path: str) -> str:
    """`A/…`-relative form of an artifact-store path (the store is `.../artifacts/aibox-migration-001`)."""
    if path.startswith("A/"):
        return path
    parts = Path(path).resolve().parts
    for i in range(len(parts) - 1):
        if parts[i] == "artifacts" and parts[i + 1] == "aibox-migration-001":
            return "A/" + "/".join(parts[i + 2:])
    raise Refused(f"not an artifact-store path: {path}")


def repo_or_artifact_path(path: str, root: Path) -> str:
    p = Path(path)
    if p.is_absolute():
        try:
            return str(p.resolve().relative_to(root.resolve()))
        except ValueError:
            return artifact_path(path)
    return path


def read_compare(path: Path) -> dict[str, dict]:
    report = json.loads(Path(path).read_text(encoding="utf-8"))
    if report.get("ok") is not True:
        raise Refused(f"compare report {path.name}: ok is not true")
    out = {}
    for fam, entry in (report.get("scenarios") or {}).items():
        if entry.get("target") is None and str(entry.get("reference", "")).startswith("not requested"):
            continue  # a .pg/.pgredis family this run did not execute (the owner ran those in their own report)
        out[fam] = {k: entry.get(k) for k in ("target", "reference", "origin_ok", "target_origin_ok")}
    return out


def build_bundle(root: Path, junit: Path, compares: list[Path], owner_runs: list[Path], head: str,
                 collected: list[str] | None = None, artifact_names: dict[Path, str] | None = None) -> dict:
    head = git(root, "rev-parse", "--verify", head + "^{commit}").strip()
    files = head_files(root, head)
    modules = {p: b for p, b in files.items() if is_test_module(p)}
    support = {p: b for p, b in files.items() if not is_test_module(p)}
    stale = working_tree_drift(root, head)
    if stale:
        raise Refused("the working tree differs from the evidence head in a bound input: " + "; ".join(stale[:5]))
    listed = collect_nodes(root) if collected is None else collected
    if len(set(listed)) != len(listed):
        dup = [n for n, c in collections.Counter(listed).items() if c > 1]
        raise Refused(f"duplicate collected node: {dup[0]}")
    # a test module added after the evidence head has no testcase in the run: it is not part of this evidence
    nodes = sorted(n for n in listed if "target/" + n.split("::")[0] in files)
    mangled: dict[tuple[str, str], str] = {}
    for node in nodes:
        key = mangle(node)
        if key in mangled:
            raise Refused(f"duplicate node after mangling: {node} and {mangled[key]}")
        mangled[key] = node
    outcomes = read_junit(junit)
    for key in sorted(outcomes):
        if key not in mangled:
            raise Refused(f"testcase matches no collected node: {key[0]}::{key[1]}")
    for key, node in sorted(mangled.items()):
        if key not in outcomes:
            raise Refused(f"collected node with no testcase: {node}")
    not_passed = {mangled[k]: o for k, o in sorted(outcomes.items()) if o != "passed"}
    compare: dict[str, dict] = {}
    for path in compares:
        for fam, entry in read_compare(path).items():
            if fam in compare and compare[fam] != entry:
                raise Refused(f"compare family {fam} reported differently by two reports")
            compare[fam] = entry
    names = artifact_names or {}
    owner: dict[str, str] = {}
    for path in owner_runs:
        try:
            owner[names.get(path) or repo_or_artifact_path(str(path), root)] = sha256_file(path)
        except OSError as exc:
            raise Refused(f"owner-run artifact {path}: sha256 cannot be computed ({exc.strerror})") from exc
    inputs = {names.get(p) or repo_or_artifact_path(str(p), root): sha256_file(p) for p in [junit, *compares]}
    return {"schema": BUNDLE_SCHEMA, "head": head, "ids": bound_ids(root, head), "support": support,
            "test_modules": modules, "nodes": nodes, "not_passed": not_passed, "compare": dict(sorted(compare.items())),
            "owner_run": dict(sorted(owner.items())), "inputs": dict(sorted(inputs.items()))}


def working_tree_drift(root: Path, head: str) -> list[str]:
    """Bound inputs whose working tree differs from `head` (R-L13 set). A test module is not checked here: a changed
    collection fails the JUnit mapping, and a changed evidence module is `freshness`'s finding."""
    diff = git(root, "diff", "--name-status", "--no-renames", head, "--", "target/src", "compare",
               "target/pyproject.toml", "target/uv.lock", "target/tests")
    out = []
    for line in diff.splitlines():
        status, path = line.split("\t", 1)
        if not is_test_module(path):
            out.append(f"{status} {path}")
    return out


def dump_json(document: dict) -> str:
    return json.dumps(document, indent=1, sort_keys=True, ensure_ascii=False) + "\n"


# ----------------------------------------------------------------------------------------------------- the tree (static)

class Tree:
    """Static facts of the checkout: file reads and AST only, never an import of a product module."""

    def __init__(self, root: Path):
        self.root = root
        self._ast: dict[str, ast.Module | None] = {}

    def exists(self, rel: str) -> bool:
        return (self.root / rel).is_file()

    def read(self, rel: str) -> str:
        return (self.root / rel).read_text(encoding="utf-8")

    def module_file(self, dotted: str, bases=("target/src", "target")) -> str | None:
        for base in bases:
            stem = f"{base}/" + dotted.replace(".", "/")
            for cand in (stem + ".py", stem + "/__init__.py"):
                if self.exists(cand):
                    return cand
        return None

    def tree_of(self, rel: str):
        if rel not in self._ast:
            try:
                self._ast[rel] = ast.parse(self.read(rel))
            except (SyntaxError, OSError):
                self._ast[rel] = None
        return self._ast[rel]

    @staticmethod
    def _bound(body) -> dict[str, list]:
        """Top-level names (also under `if`/`try`): defs/classes keep their body, assignments and imports are leaves."""
        names: dict[str, list] = {}
        for node in body:
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                names[node.name] = node.body
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for t in targets:
                    if isinstance(t, ast.Name):
                        names.setdefault(t.id, [])
            elif isinstance(node, (ast.Import, ast.ImportFrom)):  # a re-export (the permanent entry shims)
                for alias in node.names:
                    names.setdefault((alias.asname or alias.name).split(".")[0], [])
            elif isinstance(node, (ast.If, ast.Try)):
                for sub in (node.body, getattr(node, "orelse", [])):
                    for k, v in Tree._bound(sub).items():
                        names.setdefault(k, v)
        return names

    def resolve(self, symbol: str, bases=("target/src", "target")) -> bool:
        """`module`, `module:Qual.name` or `module.Name` exists in the tree (gen_s11 `Tree.resolve`, R-L16)."""
        mod, _, qual = symbol.partition(":")
        file = self.module_file(mod, bases)
        if file is None and not qual and "." in mod:
            mod, _, qual = mod.rpartition(".")
            file = self.module_file(mod, bases)
        if file is None:
            return False
        if not qual:
            return True
        tree = self.tree_of(file)
        if tree is None:
            return False
        scope = tree.body
        for i, part in enumerate(qual.split(".")):
            bound = self._bound(scope)
            if part not in bound:
                return False
            scope = bound[part]
        return True

    def owned_buckets(self) -> dict[str, list[str]]:
        """bucket -> contexts whose `<ctx>/ports.py` declares it in OWNED_BUCKETS (AST; names resolved in the file)."""
        out: dict[str, list[str]] = collections.defaultdict(list)
        for ports in sorted((self.root / "target/src/codex_harness").glob("*/ports.py")):
            rel = str(ports.relative_to(self.root))
            tree = self.tree_of(rel)
            if tree is None:
                continue
            consts = {t.id: n.value for n in tree.body if isinstance(n, ast.Assign) for t in n.targets
                      if isinstance(t, ast.Name) and isinstance(n.value, ast.Constant)}
            for node in tree.body:
                targets = (node.targets if isinstance(node, ast.Assign) else
                           [node.target] if isinstance(node, ast.AnnAssign) else [])
                if node and any(isinstance(t, ast.Name) and t.id == "OWNED_BUCKETS" for t in targets) \
                        and getattr(node, "value", None) is not None:
                    found = set()
                    for sub in ast.walk(node.value):
                        if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                            found.add(sub.value)
                        elif isinstance(sub, ast.Name) and isinstance(consts.get(sub.id), str):
                            found.add(consts[sub.id])
                    for bucket in sorted(found):
                        out[bucket].append(ports.parent.name)
        return dict(out)

    def contract_ids(self) -> set[str]:
        return set(re.findall(r"INV-[A-Z0-9-]+-\d{3}", self.read("docs/contracts.md")))

    def scripts(self) -> dict[str, str]:
        return tomllib.loads(self.read("target/pyproject.toml")).get("project", {}).get("scripts", {})

    def capabilities(self) -> dict[str, dict]:
        """ARCHITECTURE.md `## Capabilities`: TARGET symbols and tests, and the PROPOSED rows that still say pending."""
        text = re.split(r"^## ", re.split(r"^## Capabilities$", self.read(CAPABILITY_DOC), maxsplit=1, flags=re.M)[1],
                        maxsplit=1, flags=re.M)[0]
        out: dict[str, dict] = collections.defaultdict(lambda: {"symbols": [], "tests": [], "pending": []})
        for line in text.splitlines():
            if not line.startswith("|"):
                continue
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) != 7 or cells[1] not in ("TARGET", "PROPOSED"):
                continue
            entry = out[cells[0]]
            if cells[1] == "TARGET":
                for cell in cells[2:5]:
                    entry["symbols"] += [s for s in re.findall(r"`([^`]+)`", cell) if s.startswith("codex_harness.")]
                entry["tests"] += re.findall(r"`([^`]+)`", cells[6])
            elif cells[6].startswith("pending"):
                entry["pending"].append(cells[6])
        return dict(out)

    def cites(self) -> dict[str, list[tuple[str, tuple[str, ...]]]]:
        """contract ID -> [(test path relative to target, scope)] for every `target/tests/**/test_*.py` citation.

        scope is () for a module-level citation, ('f',) a function, ('C', 'm') a method, ('C',) a class body."""
        out: dict[str, list] = collections.defaultdict(list)
        for path in sorted((self.root / "target/tests").rglob("test_*.py")):
            rel = str(path.relative_to(self.root))
            text = self.read(rel)
            if "INV-" not in text:
                continue
            tree = self.tree_of(rel)
            spans = []  # (start, end, scope) of top-level functions, classes' methods and class bodies
            for node in (tree.body if tree else []):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    spans.append((min([node.lineno] + [d.lineno for d in node.decorator_list]), node.end_lineno,
                                  (node.name,)))
                elif isinstance(node, ast.ClassDef):
                    spans.append((min([node.lineno] + [d.lineno for d in node.decorator_list]), node.end_lineno,
                                  (node.name,)))
                    for sub in node.body:
                        if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            spans.append((min([sub.lineno] + [d.lineno for d in sub.decorator_list]), sub.end_lineno,
                                          (node.name, sub.name)))
            for lineno, line in enumerate(text.splitlines(), 1):
                for cid in set(re.findall(r"INV-[A-Z0-9-]+-\d{3}", line)):
                    inner = [s for s in spans if s[0] <= lineno <= s[1]]
                    scope = max(inner, key=lambda s: len(s[2]))[2] if inner else ()
                    entry = (rel[len("target/"):], scope)
                    if entry not in out[cid]:
                        out[cid].append(entry)
        return dict(out)


# ---------------------------------------------------------------------------------------------------- the relabel

PATH_ITEM = re.compile(r"A/[^\s)]+")


class Relabel:
    def __init__(self, root: Path, bundle: dict):
        self.root, self.bundle, self.tree = root, bundle, Tree(root)
        self.collected = bundle["nodes"]
        self.by_path: dict[str, list[str]] = collections.defaultdict(list)
        for node in self.collected:
            self.by_path[node.split("::")[0]].append(node)
        self.not_passed = bundle["not_passed"]
        self.verified_modules: set[str] = set()
        self.supplying: set[str] = set()
        self._buckets = self._cites = self._caps = self._ids = None

    # -- evidence items (R-L2) -------------------------------------------------------------------------------------
    def node_state(self, nodes: list[str], what: str, whole_file: bool, cat: str = "target test"):
        """(state, reason) for a set of collected nodes. A named node: all of its nodes passed. A file: >=1 passed
        and none failed or errored (a skipped node is not a pass but not a failure either)."""
        if not nodes:
            return "missing", f"{cat} has no collected node: {what}"
        bad = {n: self.not_passed[n] for n in nodes if n in self.not_passed}
        if whole_file:
            hard = [n for n, o in bad.items() if o in ("failure", "error")]
            if hard:
                return "fail", f"{cat} not passing: {what} ({bad[hard[0]]} in {hard[0].split('::', 1)[-1]})"
            if len(bad) == len(nodes):
                return "fail", f"{cat} not passing: {what} (no passing node, {collections.Counter(bad.values()).most_common(1)[0][0]})"
        elif bad:
            n = sorted(bad)[0]
            return "fail", f"{cat} not passing: {what} ({bad[n]} in {n.split('::', 1)[-1]})"
        self.supplying.update(n.split("::")[0] for n in nodes)
        return "pass", ""

    def item(self, e: str):
        """-> (class, state, reason) of one evidence string; an unrecognised form is refused."""
        if e.startswith("target:"):
            path, _, node = e[len("target:"):].partition("::")
            if not (path.startswith("tests/") and path.endswith(".py")):
                raise Refused(f"unrecognised target item: {e}")
            if not self.tree.exists("target/" + path):
                return EXEC, "missing", f"target file absent: {e}"
            if not node:
                return (EXEC, *self.node_state(self.by_path.get(path, []), e, True))
            exact = [n for n in self.by_path.get(path, []) if n == f"{path}::{node}" or n.startswith(f"{path}::{node}[")]
            if not exact:
                return EXEC, "missing", f"target node not collected: {e}"
            return (EXEC, *self.node_state(exact, e, False))
        if e.startswith("compare:"):
            return (EXEC, *self.family(re.split(r"[ #]", e[len("compare:"):], maxsplit=1)[0], e))
        if e.startswith("reference:+"):
            return EXEC, "missing", f"unnamed reference test files (AR4 map owed): {e}"
        if e.startswith("reference:tests/"):
            name = e[len("reference:tests/"):]
            if not name.endswith(".py"):
                raise Refused(f"unrecognised reference item: {e}")
            ported = "tests/ported/" + name
            nodes = self.by_path.get(ported, [])
            if not nodes:
                return EXEC, "missing", f"reference has no same-name ported file (AR4 map owed): {e}"
            return (EXEC, *self.node_state(nodes, e, False, "reference test"))
        if e.startswith("module:"):
            if e in self.module_rows:
                return (EXEC, "pass", "") if e in self.verified_modules else (EXEC, "fail", f"module row not verified: {e}")
            return EXEC, "missing", f"module row absent: {e}"
        if e.startswith("owner-run:"):
            found = PATH_ITEM.search(e)
            if found and found.group(0) in self.bundle["owner_run"]:
                return EXEC, "pass", ""
            return EXEC, "missing", f"owner-run artifact not in the bundle: {e}"
        if e.startswith(("static:", "ledger only", "codex_harness.", CAPABILITY_DOC)):
            return CONTEXT, "context", ""
        if e.startswith("pending:"):
            return PENDING, "pending", ""
        raise Refused(f"unrecognised evidence form: {e}")

    def family(self, fam: str, label: str):
        scenario = self.root / "compare/scenarios" / f"{fam}.json"
        if not scenario.is_file():
            return "missing", f"compare scenario absent: {label}"
        if not json.loads(scenario.read_text(encoding="utf-8")).get("target_driver"):
            return "missing", f"compare family has no target driver: {label}"
        report = self.bundle["compare"].get(fam)
        if report is None:
            return "missing", f"compare report absent for the family: {label}"
        if (report["target"], report["reference"], report["origin_ok"], report["target_origin_ok"]) \
                != ("equal", "equal", True, True):
            return "fail", f"compare not equal: {label} (target {report['target']}, reference {report['reference']})"
        return "pass", ""

    # -- the owning slice (R-L14, R-L16) ---------------------------------------------------------------------------
    def derived_slice(self, row: dict):
        if row.get("slice"):
            return row["slice"]
        if row["kind"] == "public_api":
            m = self.module_row_by_path.get(row["key"][len("api:"):].split("::")[0])
            if m and m.get("slice"):
                return m["slice"]
        if row["kind"] in ("cli_node", "console_script", "module_entry"):
            return "S10"
        if re.match(r"codex_harness\.(entry|composition)\b", (row.get("target_symbol") or [""])[0]):
            return "S10"
        return OWNER_SLICE.get(row.get("target_owner"))

    # -- the target symbol (R-L3, R-L9, R-L11) ---------------------------------------------------------------------
    def symbol(self, row: dict):
        """-> (resolves, reason): every target symbol of the row resolves (R-L3), the first failure is the reason."""
        syms = row.get("target_symbol") or []
        if not syms:
            return False, "no target symbol"
        for sym in syms:
            ok, why = self.one_symbol(row, sym)
            if not ok:
                return False, why
        return True, ""

    def one_symbol(self, row: dict, sym: str):
        kind, syms = row["kind"], [sym]
        s0 = sym.split(" (")[0].strip()
        t = self.tree
        if kind == "contract":
            cid = row["key"][len("contract:"):]
            return (cid in self.ids, f"contract not in docs/contracts.md: {cid}")
        if kind == "console_script":
            name = row["key"][len("script:"):]
            declared = t.scripts().get(name)
            if declared != s0:
                return False, f"[project.scripts] {name} is {declared!r}, the row says {s0!r}"
            return t.resolve(s0), f"target symbol does not resolve: {s0}"
        if kind == "capability":
            return True, ""
        if kind == "cli_node":  # `module:sub-command`: the sub-command label is not a Python name
            return t.resolve(s0.split(":")[0]), f"target module does not resolve: {s0}"
        if kind == "public_api" and s0.startswith("target/"):
            m = re.match(r"^(target/\S+\.py) \(.*\):(.+)$", syms[0])
            if not m or not t.exists(m.group(1)):
                return False, f"target file does not exist: {syms[0].split(' (')[0]}"
            tree = t.tree_of(m.group(1))
            return (tree is not None and m.group(2) in Tree._bound(tree.body)), f"target symbol does not resolve: {syms[0]}"
        if s0.startswith("target/") or s0.startswith("frontend/"):
            ok = (t.exists(s0) or (t.root / s0).is_dir() or (s0.startswith("frontend/") and t.exists("target/" + s0)))
            return ok, f"target path does not exist: {s0}"
        if s0.startswith("codex_harness") and "." in s0 or kind == "module_entry" and "." in s0 and " " not in s0:
            if kind in ("module", "public_api") and ":" not in s0:
                mf = t.module_file(s0.split(":")[0])
                if mf is not None and mf.endswith("/__init__.py"):  # gen_s11: a bare package marker is not the module
                    return False, f"target symbol is a package marker: {s0}"
            return t.resolve(s0), f"target symbol does not resolve: {s0}"
        return False, f"target symbol is not a code symbol: {s0[:60]}"

    @property
    def ids(self):
        if self._ids is None:
            self._ids = self.tree.contract_ids()
        return self._ids

    def node_set(self, path: str, scope: tuple[str, ...]) -> list[str]:
        nodes = self.by_path.get(path, [])
        if not scope:
            return nodes
        prefix = path + "::" + "::".join(scope)
        return [n for n in nodes if n == prefix or n.startswith(prefix + "[") or n.startswith(prefix + "::")]

    def any_passed(self, scopes) -> bool:
        """>=1 node of the given (path, scope) set passed."""
        for path, scope in scopes:
            ok = [n for n in self.node_set(path, scope) if n not in self.not_passed]
            if ok:
                self.supplying.add(path)
                return True
        return False

    # -- one row -----------------------------------------------------------------------------------------------
    def evaluate(self, row: dict):
        """-> (status, verification body: {'unmet': [...]} or {'passed': [...]})."""
        kind = row["kind"]
        unmet, passed, exec_exist = [], [], False
        slice_ = self.derived_slice(row)
        parts = (slice_ or "").split("/")
        if not slice_:
            slice_unmet = "owning slice not derivable"
        elif not all(p in ACCEPTED for p in parts):
            slice_unmet = f"owning slice not accepted: {slice_}"
        else:
            slice_unmet = None
        non_bucket = kind != "bucket" or row.get("mapping_correction", "").startswith("not a bucket")
        resolves, why = (True, "")
        if non_bucket:
            resolves, why = self.symbol(row)
        else:
            owners = self.buckets.get(row["key"][len("bucket:"):], [])
            resolves = len(owners) == 1
            why = f"bucket declared in {len(owners)} OWNED_BUCKETS (need exactly 1): {','.join(owners)}"
        blocking = False
        for e in row["evidence"]:
            cls, state, reason = self.item(e) if non_bucket or e.startswith("pending:") else (CONTEXT, "context", "")
            if cls == PENDING:
                unmet.append(e)
            elif cls == EXEC:
                exec_exist = True
                if state == "pass":
                    passed.append(e)
                else:
                    unmet.append(reason)
                    blocking = True
        # the implicit items of the kinds whose own rule names the evidence (R-L7, R-L8, R-L9)
        if kind == "bucket" and not non_bucket:
            exec_exist = True
            if SINGLE_WRITER_NODE in self.collected and SINGLE_WRITER_NODE not in self.not_passed:
                passed.append("node:" + SINGLE_WRITER_NODE)
                self.supplying.add(SINGLE_WRITER_NODE.split("::")[0])
            else:
                unmet.append(f"single-writer node did not pass: {SINGLE_WRITER_NODE}")
                blocking = True
        elif kind == "contract":
            cid = row["key"][len("contract:"):]
            scopes = self.cites.get(cid, [])
            exec_exist = exec_exist or bool(scopes)
            if self.any_passed(scopes):
                passed.append(f"cites:{cid}")
            else:
                unmet.append(f"no passing target test cites the contract: {cid}")
                blocking = True
        elif kind == "capability":
            cap = self.caps.get(row["key"][len("capability:"):])
            if cap is None:
                unmet.append("capability has no ARCHITECTURE.md TARGET row")
                blocking = True
            else:
                bad = [s for s in cap["symbols"] if not self.tree.resolve(s)]
                if not cap["symbols"] or bad:
                    resolves, why = False, f"ARCHITECTURE.md TARGET symbols do not resolve: {bad[:2] or 'none named'}"
                good = False
                for tok in cap["tests"]:
                    exec_exist = True
                    m = re.fullmatch(r"compare/(?:goldens/reference|scenarios)/([^/]+)\.json", tok)
                    if m:
                        if self.family(m.group(1), tok)[0] == "pass":
                            good, passed = True, passed + [f"compare:{m.group(1)}"]
                    elif tok.startswith("target/tests/"):
                        st = self.item("target:" + tok[len("target/"):])
                        if st[1] == "pass":
                            good, passed = True, passed + ["target:" + tok[len("target/"):]]
                if not good:
                    unmet.append("no named TARGET-row test passed (ARCHITECTURE.md)")
                    blocking = True
                for text in cap["pending"]:
                    unmet.append("pending: ARCHITECTURE.md PROPOSED row: " + text)
        if row["intent"].startswith("retire:"):
            unmet.append(f"intent is {row['intent'].split(' ')[0]}")
        if slice_unmet:
            unmet.append(slice_unmet)
        if not resolves:
            unmet.append(why)
        if not passed:
            unmet.append("no passing executable item")
        verified = (not unmet) and not blocking
        if verified:
            return "verified", {"passed": sorted(set(passed))}
        if not (row.get("target_symbol") or []):
            return "unmapped", {"unmet": sorted(set(unmet))}
        status = "implemented" if resolves and exec_exist else "designed"
        return status, {"unmet": sorted(set(unmet))}

    @property
    def buckets(self):
        if self._buckets is None:
            self._buckets = self.tree.owned_buckets()
        return self._buckets

    @property
    def cites(self):
        if self._cites is None:
            self._cites = self.tree.cites()
        return self._cites

    @property
    def caps(self):
        if self._caps is None:
            self._caps = self.tree.capabilities()
        return self._caps

    def run(self, ledger: dict) -> dict:
        out = copy.deepcopy(ledger)
        rows = out["rows"]
        for row in rows:  # R-L7: the four unmapped buckets (maintained fields; idempotent)
            fix = UNMAPPED_BUCKETS.get(row["key"])
            if fix:
                row["target_owner"], row["target_symbol"] = fix["target_owner"], list(fix["target_symbol"])
                row["mapping_correction"] = fix["mapping_correction"]
                row["evidence"] += [e for e in fix.get("add_evidence", []) if e not in row["evidence"]]
        self.module_rows = {r["key"]: r for r in rows if r["kind"] == "module"}
        self.module_row_by_path = {k[len("module:"):]: r for k, r in self.module_rows.items()}
        # R-L4: module rows first, then the rows that inherit through `module:`
        for phase in ("module", None):
            for row in rows:
                if (row["kind"] == "module") != (phase == "module") or row["status"] == "retired-with-authority":
                    continue
                status, body = self.evaluate(row)
                row["status"] = status
                row["verification"] = {"head": self.bundle["head"], **body}
                if phase == "module" and status == "verified":
                    self.verified_modules.add(row["key"])
        return out


def relabel(ledger: dict, bundle: dict, root: Path = ROOT):
    engine = Relabel(root, bundle)
    return engine.run(ledger), engine


# --------------------------------------------------------------------------------------------------- freshness (R-L13)

def freshness(root: Path, bundle: dict, supplying: set[str]) -> list[str]:
    """Evidence inputs that changed since the bundle head (committed HEAD vs the recorded ids)."""
    problems = []
    now = bound_ids(root, "HEAD")
    for path, ident in bundle["ids"].items():
        if now[path] != ident:
            problems.append(f"{path} changed ({ident[:8]} -> {now[path][:8]})")
    files = head_files(root, "HEAD")
    current = {p: b for p, b in files.items() if not is_test_module(p)}
    for path in sorted(set(current) | set(bundle["support"])):
        if current.get(path) != bundle["support"].get(path):
            problems.append(f"{path} {'added' if path not in bundle['support'] else 'removed' if path not in current else 'changed'}")
    for path in sorted(supplying):
        if files.get("target/" + path) != bundle["test_modules"].get("target/" + path):
            problems.append(f"target/{path} (evidence test module) changed")
    return problems


# ------------------------------------------------------------------------------------------------------------- report

def summary(before: dict, after: dict) -> dict:
    def table(doc):
        t = collections.Counter((r["kind"], r["status"]) for r in doc["rows"])
        return {f"{k}|{s}": n for (k, s), n in sorted(t.items())}
    hist = collections.Counter()
    pending = collections.Counter()
    for r in after["rows"]:
        for u in r["verification"].get("unmet", []):
            hist[u.split(":")[0] if not u.startswith("pending:") else "pending"] += 1
            if u.startswith("pending:"):
                pending[u] += 1
    return {"before": table(before), "after": table(after), "unmet_histogram": dict(hist.most_common()),
            "pending_groups": dict(pending.most_common())}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--check-fresh", action="store_true")
    parser.add_argument("--root", type=Path, default=ROOT, help=argparse.SUPPRESS)
    sub = parser.add_subparsers(dest="cmd")
    b = sub.add_parser("bundle")
    b.add_argument("--junit", required=True, type=Path)
    b.add_argument("--compare", required=True, nargs="+", type=Path)
    b.add_argument("--owner-run", nargs="*", default=[], type=Path)
    b.add_argument("--head", required=True)
    b.add_argument("--collected", type=Path, help="a saved `--collect-only -q` output instead of collecting")
    sub.add_parser("apply")
    args = parser.parse_args(argv)
    root = args.root
    ledger_path, bundle_path = root / "coverage/ledger-coverage.json", root / "coverage/run-evidence.json"
    try:
        if args.cmd == "bundle":
            collected = parse_collected(args.collected.read_text()) if args.collected else None
            names = {p: repo_or_artifact_path(str(p), root) for p in [args.junit, *args.compare, *args.owner_run]}
            doc = build_bundle(root, args.junit, args.compare, args.owner_run, args.head, collected, names)
            bundle_path.write_text(dump_json(doc), encoding="utf-8")
            print(json.dumps({"written": "coverage/run-evidence.json", "head": doc["head"], "nodes": len(doc["nodes"]),
                              "not_passed": len(doc["not_passed"]), "compare_families": len(doc["compare"]),
                              "owner_run": len(doc["owner_run"])}))
            return 0
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
        bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
        new, engine = relabel(ledger, bundle, root)
        text = generate.dump(new)
        if args.cmd == "apply":
            ledger_path.write_text(text, encoding="utf-8")
            print(json.dumps(summary(ledger, new), indent=1))
            return 0
        if args.check or args.check_fresh:
            same = ledger_path.read_text(encoding="utf-8") == text
            result = {"ledger_matches_relabel": same}
            problems = []
            if args.check_fresh:
                problems = freshness(root, bundle, engine.supplying)
                result["fresh"] = not problems
                result["stale"] = problems[:10]
            print(json.dumps(result))
            return 0 if same and not problems else 1
        parser.print_usage(sys.stderr)
        return 2
    except Refused as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
