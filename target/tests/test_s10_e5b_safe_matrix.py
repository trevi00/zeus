"""S10 E5b: the declared differences of `entries.safe_matrix` are reviewable (DESIGN-s10 section 16 (b)).

The row key set of the target driver equals the golden's, and every other byte matches, in
`compare/run.py run --only entries.safe_matrix` (the target result must equal the golden with exactly the
declarations applied). This file proves the declarations themselves are minimal: every mapped row is
declared, an unmapped row differs in no `argv`, and each whole-row value differs from the golden only in the
fields its authority names.
"""

import ast
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COMPARE = ROOT / "compare"
SCENARIO = json.loads((COMPARE / "scenarios/entries.safe_matrix.json").read_text(encoding="utf-8"))
GOLDEN = json.loads((COMPARE / "goldens/reference/entries.safe_matrix.json").read_text(encoding="utf-8"))["rows"]
SOURCE = (COMPARE / "drivers/target/entries.py").read_text(encoding="utf-8")
ARGV_MAP = ast.literal_eval(SOURCE[SOURCE.index("ARGV_MAP = ") + len("ARGV_MAP = "):SOURCE.index("\n}\n") + 2])
DECLARED = {d["key"]: d for d in SCENARIO["intended_differences"]}
STDOUT = {"stdout", "stdout_bytes", "stdout_sha256"}
# Rows whose stdout carries the module dotted path (argparse usage or description text).
PATH_STDOUT = {"module.adapters.experience --help", "module.adapters.host_migration --help",
               "module.adapters.observed_assets --help"}
HELP_ROWS = {"console.zeus --help", "console.harness --help"}
VERSION_ROW = "console.zeus --version"


def differing(key):
    value = DECLARED[key]["value"]
    return {f for f in set(value) | set(GOLDEN[key]) if value.get(f) != GOLDEN[key].get(f)}


def squash(text):
    return re.sub(r"\s+", " ", text)


def test_the_scenario_is_a_target_family_with_whole_row_declarations():
    assert SCENARIO["target_driver"] == "drivers/target/entries.py" and "target_status" not in SCENARIO
    for declaration in SCENARIO["intended_differences"]:
        assert declaration["path"] == "$.rows" and declaration["op"] == "replace"
        assert declaration["key"] in GOLDEN and declaration["authority"].strip()
    assert len(DECLARED) == len(SCENARIO["intended_differences"])


def test_every_mapped_row_is_declared_and_its_argv_is_the_mapped_module():
    assert set(ARGV_MAP) <= set(GOLDEN)
    for key, (m7, target) in ARGV_MAP.items():
        assert key in DECLARED, key
        assert "argv" in differing(key)
        assert DECLARED[key]["value"]["argv"] == [target if a == m7 else a for a in GOLDEN[key]["argv"]]
        assert m7 in GOLDEN[key]["argv"] and target in DECLARED[key]["value"]["argv"]
        assert target in DECLARED[key]["authority"] and m7 in DECLARED[key]["authority"]


def test_no_unmapped_row_has_an_argv_difference():
    for key in DECLARED:
        if key not in ARGV_MAP:
            assert "argv" not in differing(key), key


def test_each_declaration_differs_only_in_the_fields_its_authority_names():
    for key in DECLARED:
        allowed = {"argv"} if key in ARGV_MAP else set()
        if key in PATH_STDOUT or key in HELP_ROWS or key == VERSION_ROW:
            allowed |= STDOUT
        assert differing(key) <= allowed, key
    # the migrations -> migrator row: argparse `prog` is the explicit M7 string on both sides, so argv only
    assert differing("module.adapters.migrations --help") == {"argv"}
    for key in ("artifact_reader --help", "artifact_reader.index_fixture",
                "import_only.codex_harness.adapters.isolated_worker",
                "import_only.codex_harness.adapters.service_entry"):
        assert differing(key) == {"argv"}


def test_dotted_path_stdout_differs_only_by_the_module_path():
    for key in PATH_STDOUT:
        old, new = ARGV_MAP[key]
        golden = GOLDEN[key]["stdout"]
        value = DECLARED[key]["value"]
        assert squash(value["stdout"]) == squash(golden.replace(old, new)), key
        assert value["stdout_bytes"] == len(value["stdout"].encode("utf-8"))


def test_the_top_level_help_gains_exactly_research_package_and_dlq():
    for key in HELP_ROWS:
        old, new = GOLDEN[key]["stdout"].splitlines(), DECLARED[key]["value"]["stdout"].splitlines()
        added = [line for line in new if line not in old]
        removed = [line for line in old if line not in new]
        lists = [line for line in added if "{" in line]
        helps = [line for line in added if "{" not in line]
        assert [line.split()[0] for line in helps] == ["research-package", "dlq"], key
        # the two brace lists (usage and positional) are the only other changed lines
        assert len(removed) == 2 and len(lists) == 2, key
        for before, after in zip(removed, lists):
            assert after.replace(",research-package,dlq", "") == before, key


def test_the_version_row_changes_only_the_version_text():
    value = DECLARED[VERSION_ROW]["value"]
    assert GOLDEN[VERSION_ROW]["stdout"] == "Zeus 0.2.0\n" and value["stdout"] == "Zeus 0.3.0.dev0\n"
    assert value["stdout_bytes"] == len(value["stdout"].encode("utf-8"))
