import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_inner_layers_do_not_import_adapters_or_sdk():
    banned = {"psycopg", "redis", "tree_sitter", "tree_sitter_python", "subprocess", "jsonschema"}
    for folder in ("domain", "application"):
        for source in (ROOT / "src/codex_harness" / folder).rglob("*.py"):
            tree = ast.parse(source.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                imports = ([node.module or ""] if isinstance(node, ast.ImportFrom)
                           else [a.name for a in node.names] if isinstance(node, ast.Import) else [])
                for module in imports:
                    assert module.split(".")[0] not in banned, (source, module)
                    assert not module.startswith("codex_harness.adapters"), (source, module)
                    assert not module.startswith("codex_harness.bootstrap"), (source, module)


SOURCE_TEXT_READERS = re.compile(r"\b(read_text|read_bytes|getsource|ast\.parse|ast\.walk|ast\.dump)\s*\(")
PRODUCTION_LOCATIONS = re.compile(r"(src/|scripts/|harness_hooks/|codex_harness[./])")
# Structural policy tests inspect source deliberately; behavior tests may not.
WIRING_ALLOWLIST = {"test_architecture.py"}


def wiring_assertions(source: str):
    """FA-009: assertions that only check production source text, not executed behavior.

    A `<literal> in <production file text>` or an AST-shape assertion proves that a string was
    typed, never that the wiring runs. Reading fixtures or generated runtime files is fine.
    """
    findings = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Assert):
            continue
        text = ast.unparse(node.test)
        if SOURCE_TEXT_READERS.search(text) and PRODUCTION_LOCATIONS.search(text):
            findings.append((node.lineno, text[:120]))
    return findings


def test_tests_assert_behavior_not_source_text():
    offenders = []
    for test in sorted((ROOT / "tests").glob("test_*.py")):
        if test.name in WIRING_ALLOWLIST:
            continue
        offenders += [(test.name, line, text) for line, text in
                      wiring_assertions(test.read_text(encoding="utf-8-sig"))]
    assert offenders == [], offenders


def test_wiring_detector_has_positive_and_negative_controls():
    positive = (
        "from pathlib import Path\n"
        "def test_x():\n"
        "    assert 'record_incident' in (ROOT / 'src/codex_harness/cli.py').read_text()\n"
        "    assert 'fence' in Path('scripts/check.py').read_bytes().decode()\n"
        "    tree = ast.parse((ROOT / 'src/codex_harness/x.py').read_text())\n"
        "    assert any(isinstance(n, ast.Call) for n in ast.walk(ast.parse(source_of('codex_harness.x'))))\n")
    assert [line for line, _ in wiring_assertions(positive)] == [3, 4, 6]
    negative = (
        "def test_y(tmp_path):\n"
        "    assert (tmp_path / 'lease.json').read_text() == '{}'\n"  # generated runtime file
        "    assert service.record_incident(message)['occurrences'] == 1\n"  # executed behavior
        "    assert 'FASTAPI_ELIGIBLE' in prompts[0]['body']\n"  # observed output of a run
        "    body = (ROOT / 'src/codex_harness/cli.py').read_text()\n"  # read outside an assert
        "    assert parse(body)['version'] == 1\n")
    assert wiring_assertions(negative) == []


def test_invariant_comments_resolve_to_contract_registry():
    contracts = (ROOT / "docs/contracts.md").read_text(encoding="utf-8")
    for source in (ROOT / "src").rglob("*.py"):
        for identifier in re.findall(r"@invariant\s+(INV-[A-Z0-9-]+)", source.read_text(encoding="utf-8")):
            assert identifier in contracts, (source, identifier)
