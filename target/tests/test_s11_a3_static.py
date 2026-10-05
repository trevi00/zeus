"""S11 unit A3 (DESIGN-s11 §1; the AR3 static checks as repository checks), each with a negative control.

1. wheel RECORD = the tree: `compare/run.py wheel-check` (never against a fresh build inside pytest: a synthetic wheel
   zip, built here from the HEAD tree bytes, plus an extra file, a missing file and a wrong hash).
2. import existence: every `codex_harness`/`zeus` import in `target/src` (absolute and relative, resolved like
   `import_rules.edges`) names a tree module/package or a name the tree module defines.
3. the shim shape (OWNER-DECISIONS-S11 #6): every tree module whose dotted path also exists in SOURCE is in
   `import_rules.SHIMS`, a package `__init__` importing nothing, `zeus.*`, or the one declared non-shim
   `codex_harness.resources.worker_profile_hook` (a packaged hook, 195 lines by the rule: DELTA §5.3); each SHIM has at
   most 10 AST lines (non-blank, non-comment, non-docstring), exactly one import from `codex_harness.entry.*`, and the
   `if __name__ == "__main__":` guard.
4. pinned argv: every literal `-m <module>` in `git ls-files target/deploy target/Dockerfile.worker` names a SHIMS
   module or a tree module (a package needs its `__main__`); a stdlib module (`python -m venv`) is not ours. In `.py`
   files an argv is only an adjacent `"-m"`, `"<module>"` pair in a list/tuple literal (so the multi-line form is seen);
   text files use a regex. Excluded BY PARSING (not an argv): docstring and help-text mentions, i.e.
   `host_os/adapters/service_entry.py` (docstring, `USAGE`) and `knowledge/adapters/experience_import.py` (docstring)
   (DELTA §5.4), and `install -m 0644` in the aibox README.
"""
import ast
import base64
import csv
import hashlib
import importlib.util
import io
import re
import subprocess
import sys
import tokenize
import zipfile
from pathlib import Path

import import_rules
import pytest

TARGET = Path(__file__).resolve().parents[1]
ROOT = TARGET.parent
SRC = TARGET / "src"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "s11_a3"
SOURCE_COMMIT = "e38aa722"
HOOK = "codex_harness.resources.worker_profile_hook"
SHIM_LIMIT = 10


def _git(*args, text=True):
    return subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True, text=text).stdout


def _fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


def _run_module():
    spec = importlib.util.spec_from_file_location("compare_run_for_s11_a3", ROOT / "compare" / "run.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---- 1. wheel RECORD = the tree -------------------------------------------------------------------------------------
def _digest(data: bytes) -> str:
    return "sha256=" + base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode("ascii")


def _tree_files():
    prefix = "target/src/"
    names = _git("ls-files", "--", prefix + "codex_harness", prefix + "zeus").split()
    return {n[len(prefix):]: _git("show", f"HEAD:{n}", text=False) for n in names}


def _wheel(path: Path, files: dict, record_hashes: dict | None = None, drop=()):
    rows = []
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in files.items():
            if name in drop:
                continue
            zf.writestr(name, data)
        for name, data in files.items():
            if name in drop and not (record_hashes or {}).get(name):
                continue
            rows.append([name, (record_hashes or {}).get(name) or _digest(data), str(len(data))])
        rows += [["zeus_harness-0.0.dist-info/METADATA", "sha256=x", "1"],
                 ["zeus_harness-0.0.dist-info/RECORD", "", ""]]
        buf = io.StringIO()
        csv.writer(buf, lineterminator="\n").writerows(rows)
        zf.writestr("zeus_harness-0.0.dist-info/METADATA", "Name: zeus-harness\n")
        zf.writestr("zeus_harness-0.0.dist-info/RECORD", buf.getvalue())
    return str(path)


@pytest.fixture(scope="module")
def tree_files():
    return _tree_files()


def test_the_wheel_record_equal_to_the_tree_passes(tmp_path, tree_files):
    report = _run_module().wheel_check(_wheel(tmp_path / "ok.whl", tree_files))
    assert report == {"ok": True, "files": len(tree_files)}
    assert len(tree_files) > 500  # 595 at the S10 head: the tree, not a stub


def test_a_wheel_with_an_extra_file_fails_naming_the_path(tmp_path, tree_files):
    report = _run_module().wheel_check(_wheel(tmp_path / "x.whl", {**tree_files, "codex_harness/rogue.py": b"x = 1\n"}))
    assert report == {"ok": False, "extra": ["codex_harness/rogue.py"], "missing": [], "hash_mismatch": []}


def test_a_wheel_missing_a_tree_file_fails_naming_the_path(tmp_path, tree_files):
    report = _run_module().wheel_check(_wheel(tmp_path / "m.whl", tree_files, drop=("zeus/__main__.py",)))
    assert report == {"ok": False, "extra": [], "missing": ["zeus/__main__.py"], "hash_mismatch": []}


def test_a_wheel_with_a_wrong_hash_fails_naming_the_path_never_the_content(tmp_path, tree_files):
    changed = {**tree_files, "zeus/__main__.py": b"SECRET-CONTENT = 1\n"}
    report = _run_module().wheel_check(_wheel(tmp_path / "h.whl", changed))
    assert report == {"ok": False, "extra": [], "missing": [], "hash_mismatch": ["zeus/__main__.py"]}
    assert "SECRET-CONTENT" not in str(report)


def test_the_cli_exit_codes(tmp_path, tree_files):
    def run(wheel):
        return subprocess.run([sys.executable, str(ROOT / "compare" / "run.py"), "wheel-check", wheel],
                              cwd=ROOT, capture_output=True, text=True, timeout=120)
    good = run(_wheel(tmp_path / "ok.whl", tree_files))
    assert good.returncode == 0 and '"files": %d' % len(tree_files) in good.stdout, good.stderr[-400:]
    bad = run(_wheel(tmp_path / "bad.whl", {**tree_files, "codex_harness/rogue.py": b"\n"}))
    assert bad.returncode == 1 and "codex_harness/rogue.py" in bad.stdout


# ---- 2. import existence --------------------------------------------------------------------------------------------
def _defined_names(path: Path) -> set:
    names = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            names.add(node.id)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            names |= {(a.asname or a.name).split(".")[0] for a in node.names}
    return names


def unresolved_imports(tree) -> tuple[int, list]:
    """(edges checked, [(module, target)] unresolved): an internal import must name a tree module/package, or a name
    the (tree) module it is imported from defines."""
    edges_checked, bad = 0, []
    defined = {}
    for module, path in sorted(tree.files.items()):
        package = module if module in tree.packages else module.rpartition(".")[0]
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            targets = []  # (module that must exist, optional name it must define)
            if isinstance(node, ast.Import):
                targets = [(a.name, None) for a in node.names if a.name.split(".")[0] in {"codex_harness", "zeus"}]
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    parts = package.split(".")
                    base = ".".join(parts[: len(parts) - node.level + 1] + ([node.module] if node.module else []))
                else:
                    base = node.module or ""
                if base.split(".")[0] in {"codex_harness", "zeus"}:
                    targets = [(base, a.name) for a in node.names]
            elif (isinstance(node, ast.Call) and getattr(node.func, "attr", getattr(node.func, "id", "")) == "import_module"
                  and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)
                  and node.args[0].value.split(".")[0] in {"codex_harness", "zeus"}):
                targets = [(node.args[0].value, None)]
            for base, name in targets:
                edges_checked += 1
                if name is None or name == "*":
                    ok = base in tree.files
                elif f"{base}.{name}" in tree.files:
                    ok = True
                elif base in tree.files:
                    defined.setdefault(base, _defined_names(tree.files[base]))
                    ok = name in defined[base]
                else:
                    ok = False
                if not ok:
                    bad.append((module, f"{base}.{name}" if name else base))
    return edges_checked, bad


def test_every_internal_import_resolves_in_the_target_tree():
    tree = import_rules.Tree(SRC)
    checked, bad = unresolved_imports(tree)
    assert bad == [], bad[:10]
    # the same edge count as import_rules (one internal edge per imported name or dotted target)
    rules_edges = sum(1 for m in tree.files for t, kind in import_rules.edges(tree, m)[0] if kind == "internal")
    assert checked == rules_edges and checked > 4000, (checked, rules_edges)
    print(f"s11-a3 import edges checked: {checked} in {len(tree.files)} modules, 0 unresolved")


def test_an_unresolved_import_is_found_in_a_synthetic_tree(tmp_path):
    root = tmp_path / "src"
    (root / "codex_harness").mkdir(parents=True)
    (root / "codex_harness" / "__init__.py").write_text("")
    (root / "codex_harness" / "present.py").write_text("real = 1\n")
    (root / "codex_harness" / "bad.py").write_text(_fixture("unresolved_import.py.txt"))
    (root / "codex_harness" / "good.py").write_text(
        "from codex_harness.present import real\nfrom . import present\nimport codex_harness.present\n")
    checked, bad = unresolved_imports(import_rules.Tree(root))
    assert sorted(bad) == [("codex_harness.bad", "codex_harness.absent_module"),
                           ("codex_harness.bad", "codex_harness.present.absent_name")]
    assert checked == 5


# ---- 3. the shim shape ----------------------------------------------------------------------------------------------
def ast_lines(source: str) -> int:
    """Non-blank, non-comment, non-docstring lines (OWNER-DECISIONS-S11 #6)."""
    module = ast.parse(source)
    skip = set()
    first = module.body[0] if module.body else None
    if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
        skip = set(range(first.lineno, first.end_lineno + 1))
    skipped = {tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT, tokenize.ENDMARKER}
    lines = {tok.start[0] for tok in tokenize.generate_tokens(io.StringIO(source).readline) if tok.type not in skipped}
    return len(lines - skip)


def shim_problems(source: str) -> list:
    out = []
    module = ast.parse(source)
    if ast_lines(source) > SHIM_LIMIT:
        out.append(f"{ast_lines(source)} lines")
    imports = [n for n in ast.walk(module) if isinstance(n, (ast.Import, ast.ImportFrom))]
    entry = [n for n in imports if isinstance(n, ast.ImportFrom) and not n.level
             and (n.module or "").startswith("codex_harness.entry.")]
    if len(imports) != 1 or len(entry) != 1:
        out.append(f"{len(imports)} imports, {len(entry)} from codex_harness.entry")
    guard = [n for n in module.body if isinstance(n, ast.If) and isinstance(n.test, ast.Compare)
             and isinstance(n.test.left, ast.Name) and n.test.left.id == "__name__"
             and [getattr(c, "value", None) for c in n.test.comparators] == ["__main__"]]
    if len(guard) != 1:
        out.append("no __main__ guard")
    return out


def _source_modules():
    try:
        names = _git("ls-tree", "-r", "--name-only", SOURCE_COMMIT, "src/").split()
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        pytest.skip(f"SOURCE {SOURCE_COMMIT} is not available in this repository ({type(exc).__name__})")
    modules = set()
    for name in names:
        if name.endswith(".py"):
            parts = name[len("src/"):-3].split("/")
            modules.add(".".join(parts[:-1] if parts[-1] == "__init__" else parts))
    return modules


def test_every_m7_dotted_path_in_the_tree_is_a_shim_under_the_ast_rule():
    tree = import_rules.Tree(SRC)
    shared = sorted(set(tree.files) & _source_modules())
    assert shared, "no module shared with SOURCE: the path mapping is wrong"
    assert HOOK in shared and HOOK not in import_rules.SHIMS  # the one declared non-shim (DELTA §5.3)
    assert import_rules.SHIMS <= set(tree.files)
    problems, shims = [], 0
    for module in shared:
        source = tree.files[module].read_text(encoding="utf-8")
        if module.split(".")[0] == "zeus" or module == HOOK:
            continue
        if module in import_rules.SHIMS:
            shims += 1
            problems += [(module, p) for p in shim_problems(source)]
        elif module in tree.packages:
            if any(isinstance(n, (ast.Import, ast.ImportFrom)) for n in ast.walk(ast.parse(source))):
                problems.append((module, "package __init__ imports"))
        else:
            problems.append((module, "an M7 dotted path that is neither a shim nor an empty package init"))
    assert problems == [], problems
    assert shims == len(import_rules.SHIMS)
    print(f"s11-a3 shared with SOURCE: {len(shared)} modules, {shims} shims checked")


def test_a_conforming_shim_passes_and_each_defect_fails():
    assert shim_problems(_fixture("shim_ok.py.txt")) == []
    assert shim_problems(_fixture("shim_two_imports.py.txt")) == ["2 imports, 1 from codex_harness.entry"]
    assert shim_problems(_fixture("shim_no_guard.py.txt")) == ["no __main__ guard"]
    assert shim_problems(_fixture("shim_not_entry.py.txt")) == ["1 imports, 0 from codex_harness.entry"]
    long_shim = _fixture("shim_ok.py.txt") + "".join(f"x{i} = {i}\n" for i in range(10))
    assert shim_problems(long_shim) == ["13 lines"]


def test_the_ast_line_rule_ignores_blank_comment_and_docstring_lines():
    source = '"""doc\nmore"""\n\n# comment\nfrom a import b\n\nif x:\n    b()  # tail\n'
    assert ast_lines(source) == 3


# ---- 4. the pinned argv of deploy / image files ---------------------------------------------------------------------
MODULE = r"[A-Za-z_][\w.]*"
TEXT_ARGV = [re.compile(rf"(?<![\w-])-m[ \t]+({MODULE})"), re.compile(rf"\"-m\",\s*\"({MODULE})\"")]


def argv_modules(name: str, text: str) -> list:
    if name.endswith(".py"):
        out = []
        for node in ast.walk(ast.parse(text)):
            if isinstance(node, (ast.List, ast.Tuple)):
                for a, b in zip(node.elts, node.elts[1:]):
                    if (isinstance(a, ast.Constant) and a.value == "-m" and isinstance(b, ast.Constant)
                            and isinstance(b.value, str) and re.fullmatch(MODULE, b.value)):
                        out.append(b.value)
        return out
    return sorted({m for rx in TEXT_ARGV for m in rx.findall(text)})


def unresolved_argv(modules, tree) -> list:
    bad = []
    for module in sorted(set(modules)):
        if module in import_rules.SHIMS:
            continue
        if module.split(".")[0] not in {"codex_harness", "zeus"}:
            if module.split(".")[0] not in sys.stdlib_module_names:
                bad.append(module)
            continue
        if module not in tree.files or (module in tree.packages and f"{module}.__main__" not in tree.files):
            bad.append(module)
    return bad


def _argv_inputs():
    return _git("ls-files", "--", "target/deploy", "target/Dockerfile.worker").split()


def test_every_pinned_argv_names_a_shim_or_a_tree_module():
    tree = import_rules.Tree(SRC)
    inputs, pinned = _argv_inputs(), {}
    assert "target/Dockerfile.worker" in inputs and "target/deploy/aibox/zeus_aibox_service.py" in inputs
    for name in inputs:
        for module in argv_modules(name, (ROOT / name).read_text(encoding="utf-8", errors="replace")):
            pinned.setdefault(module, []).append(name)
    assert unresolved_argv(pinned, tree) == [], pinned
    assert {"zeus", "codex_harness.monitor", "codex_harness.adapters.managed_runtime",
            "codex_harness.adapters.isolated_worker_entry"} <= set(pinned), pinned
    print(f"s11-a3 argv inputs: {len(inputs)} files; pinned modules: {sorted(pinned)}")


def test_help_text_and_docstring_mentions_are_not_an_argv():
    tree = import_rules.Tree(SRC)
    for rel in ("codex_harness/host_os/adapters/service_entry.py", "codex_harness/knowledge/adapters/experience_import.py"):
        text = (SRC / rel).read_text(encoding="utf-8")
        assert "-m codex_harness.adapters." in text  # the mention exists...
        assert argv_modules(rel, text) == []  # ...and parsing excludes it
        flagged = unresolved_argv([m for rx in TEXT_ARGV for m in rx.findall(text)], tree)
        if rel.startswith("codex_harness/host_os/"):
            # S11 SH-1 (DESIGN-s11 §8 SH-a): the kept shim exists, so the mention now resolves.
            assert flagged == []
        else:
            assert flagged  # a regex scan would flag it


def test_a_deploy_text_naming_an_absent_module_fails():
    tree = import_rules.Tree(SRC)
    text = _fixture("absent_module.service.in.txt")
    assert argv_modules("x.service.in", text) == ["codex_harness.adapters.no_such_module"]
    assert unresolved_argv(argv_modules("x.service.in", text), tree) == ["codex_harness.adapters.no_such_module"]
    multi = _fixture("absent_module_argv.py.txt")  # the multi-line `"-m",` + `"<module>"` form
    assert unresolved_argv(argv_modules("x.py", multi), tree) == ["codex_harness.adapters.no_such_module"]
    assert unresolved_argv(['codex_harness.cli', 'zeus', 'venv'], tree) == []
    assert unresolved_argv(["pytest_not_stdlib"], tree) == ["pytest_not_stdlib"]
