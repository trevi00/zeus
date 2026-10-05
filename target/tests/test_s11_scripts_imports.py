"""S11 R-S1/R-S3/R-S4 (DESIGN-s11 §7): every `codex_harness`/`zeus` import in `scripts/` resolves in the target tree.

The ported root scripts name target homes (`# S11 R-S3` comments mark each adapted construction). A script is not run by CI
(most need a provider or a service), so a stale home would stay unseen until an operator ran it. This is the AST check of
`test_s11_a3_static.unresolved_imports` (the AR3 import-existence check, reused, not copied) over the scripts: an import names a
tree module/package, or a name the tree module defines. Scripts are scanned under `scripts/**/*.py`; a file that imports nothing
of ours (`aibox_data/`, check.py, ci_scope.py) contributes no edge. `<root>/scripts` is `target/scripts` now and `scripts/` after
the promotion.
"""
from pathlib import Path

import import_rules
from _layout import TARGET as PROJECT
from test_s11_a3_static import unresolved_imports

PREFIX = "s11_scripts."


class _View:
    """The target tree plus the scripts as pseudo-modules `s11_scripts.<path>`; the helper resolves against all of it."""

    def __init__(self, tree, scripts: Path):
        self.files = dict(tree.files)
        self.packages = set(tree.packages)
        for path in sorted(scripts.rglob("*.py")):
            self.files[PREFIX + ".".join(path.relative_to(scripts).with_suffix("").parts)] = path


def script_import_problems(tree, scripts: Path):
    """(edges checked in the scripts, [(script, unresolved import)])."""
    total, bad = unresolved_imports(_View(tree, scripts))
    in_tree, _ = unresolved_imports(tree)
    return total - in_tree, [(module[len(PREFIX):], target) for module, target in bad if module.startswith(PREFIX)]


def test_every_script_import_resolves_in_the_target_tree():
    tree = import_rules.Tree(PROJECT / "src")
    checked, bad = script_import_problems(tree, PROJECT / "scripts")
    assert bad == [], bad
    assert checked > 0, "the scripts import nothing of ours: the scan is not reaching them"
    print(f"s11 script import edges checked: {checked}, 0 unresolved")


def test_the_ported_scripts_are_present_and_scanned():
    scanned = {p.name for p in (PROJECT / "scripts").glob("*.py")}
    expected = {"request_threshold_review.py", "smoke_bus.py", "verify_failed_canary.py", "verify_rlm.py",
                "verify_runtime.py", "claude_real_call.py", "host_cycle.py"}
    assert expected <= scanned, sorted(expected - scanned)


def test_an_unresolved_script_import_is_found_in_a_synthetic_tree(tmp_path):
    root = tmp_path / "src"
    (root / "codex_harness").mkdir(parents=True)
    (root / "codex_harness" / "__init__.py").write_text("")
    (root / "codex_harness" / "present.py").write_text("real = 1\n")
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "good.py").write_text("from codex_harness.present import real\nimport codex_harness.present\n")
    (scripts / "bad.py").write_text(
        "from codex_harness.absent_module import anything\n"
        "from codex_harness.present import absent_name\n"
        "def main():\n    import codex_harness.also_absent\n")
    checked, bad = script_import_problems(import_rules.Tree(root), scripts)
    assert sorted(bad) == [("bad", "codex_harness.absent_module.anything"),
                           ("bad", "codex_harness.also_absent"),
                           ("bad", "codex_harness.present.absent_name")]
    assert checked == 5
