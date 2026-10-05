"""S10 owner correction int44 (DESIGN-s10 §16b, disclosure 29): the §3.5 shim set follows the CORRECTED S0 pinned-argv
scan (`compare/goldens/reference/static.source.json` `shims.conditional`, OWNER-DECISIONS-S11 #11). Every conditional
module with `keep_shim: true` is a shim in `import_rules.SHIMS` and every `false` one is not; the restored shims
(`artifact_reader`, `host_migration`, `migrations`; `service_entry` since S11 SH-1) only delegate to `entry` and answer `--help` through M7's argv."""
import ast
import json
import subprocess
import sys

import import_rules
import pytest
from _layout import REPO, TARGET

GOLDEN = json.loads((REPO / "compare/goldens/reference/static.source.json").read_text(encoding="utf-8"))
CONDITIONAL = GOLDEN["shims"]["conditional"]
RESTORED = ("codex_harness.adapters.artifact_reader", "codex_harness.adapters.host_migration",
            "codex_harness.adapters.migrations", "codex_harness.adapters.service_entry")


def test_the_conditional_shims_are_exactly_the_scan_keep_set():
    kept = {name for name, row in CONDITIONAL.items() if row["keep_shim"]}
    dropped = set(CONDITIONAL) - kept
    assert kept <= import_rules.SHIMS
    assert not dropped & import_rules.SHIMS
    assert set(RESTORED) <= kept


@pytest.mark.parametrize("module", RESTORED)
def test_each_restored_shim_only_delegates_to_entry(module):
    path = TARGET / "src" / (module.replace(".", "/") + ".py")
    tree = ast.parse(path.read_text(encoding="utf-8"))
    body = [n for n in tree.body if not (isinstance(n, ast.Expr) and isinstance(getattr(n, "value", None), ast.Constant))]
    imports = [n for n in body if isinstance(n, ast.ImportFrom)]
    assert len(imports) == 1 and imports[0].module.startswith("codex_harness.entry.processes.")
    assert import_rules.classify(imports[0].module)[0] == "ENTRY"
    assert len(body) == 2 and isinstance(body[1], ast.If)  # the import and the __main__ guard, nothing else


@pytest.mark.parametrize("module, usage", [
    ("codex_harness.adapters.artifact_reader", "usage: "),
    ("codex_harness.adapters.host_migration", "usage: python -m codex_harness.adapters.host_migration"),
    ("codex_harness.adapters.migrations", "usage: codex_harness.adapters.migrations"),
])
def test_help_answers_through_the_m7_argv(module, usage):
    done = subprocess.run([sys.executable, "-m", module, "--help"], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    assert done.stdout.startswith(usage), done.stdout[:200]


def test_service_entry_without_arguments_prints_the_m7_usage_and_exits_with_m7_code():
    """Expected result from SOURCE `adapters/service_entry.py` USAGE and its diagnostics exit code (125)."""
    done = subprocess.run([sys.executable, "-m", "codex_harness.adapters.service_entry"],
                          capture_output=True, text=True, timeout=60)
    assert done.returncode == 125, done.stderr
    assert done.stderr.strip() == "usage: python -m codex_harness.adapters.service_entry --journal PATH -- CLI_ARGS"
