"""S9 batch L2-B1: the observation schema (U1) and the file spool (U2) move out of M7 `adapters/contracts.py` and `adapters/observation_spool.py`.

U1 is the observation half of `contracts.py` verbatim (R-sc0, ContractError from `kernel.errors` R-sc1); U2 is `observation_spool.py` whole, in M7's order, with only
its import block (R-sp0) and header changed, the S4 part (`RECORD_KINDS`, `encode_record`, `MemorySpool`) still equal to the base head's. M7 is read only as
text through `git show e38aa722:...` and compared by AST (never imported: both packages are named `codex_harness`). Behaviour over real files, real child
processes and real barrier threads is compared by the recorded `observation.schema` and `observation.file_spool` goldens (the moved modules are target-equal to
them); this file pins the structure and the contract facts a golden does not state as a rule.

M7 tests this unit does NOT port yet (the S9 ported suite is a later step): `test_observation_contract.py` (11), `test_observation_spool.py` (4), and the spool
parts of `test_observation_review.py`, `review2`, `review3`, `review4`, `review5` (see the report).
"""

from __future__ import annotations

import ast
import inspect
import subprocess
from pathlib import Path

import pytest
from test_spawn_chokepoint import spawn_sites

from codex_harness.kernel.errors import ContractError
from codex_harness.observation import ports as observation_ports
from codex_harness.observation.adapters import observation_schema as schema_module
from codex_harness.observation.adapters import observation_spool as spool_module

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "target" / "src" / "codex_harness"
SOURCE = "e38aa722"
BASE = "06c3aa79"
CONTRACTS_M7 = "src/codex_harness/adapters/contracts.py"
SPOOL_M7 = "src/codex_harness/adapters/observation_spool.py"
SPOOL_REL = "target/src/codex_harness/observation/adapters/observation_spool.py"
CANARY = "CANARY-9f3b1c7e2a5d4f6b8e0c1d2a3b4c5d6e"
FORBIDDEN_HOMES = ("codex_harness.adapters", "codex_harness.domain", "codex_harness.application", "codex_harness.ports")


def show(rev, path):
    return subprocess.run(["git", "-C", str(REPO), "show", f"{rev}:{path}"], check=True, capture_output=True, text=True).stdout


def text_of(module):
    return Path(module.__file__).read_text()


def statements(src):
    out = {}
    for i, node in enumerate(ast.parse(src).body):
        if isinstance(node, (ast.Import, ast.ImportFrom)) or (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)):
            continue
        name = getattr(node, "name", None) or (node.targets[0].id if isinstance(node, ast.Assign) else i)
        out[name] = node
    return out


def import_modules(src):
    return sorted({n.module for n in ast.walk(ast.parse(src)) if isinstance(n, ast.ImportFrom)})


def plain_imports(src):
    return sorted(a.name for n in ast.parse(src).body if isinstance(n, ast.Import) for a in n.names)


def header(module):
    return ast.get_docstring(ast.parse(text_of(module)))


# ----- U1 schema -----------------------------------------------------------------------------------------------------------------------------
def test_the_schema_module_is_the_observation_half_of_contracts_verbatim():
    ours, theirs = statements(text_of(schema_module)), statements(show(SOURCE, CONTRACTS_M7))
    assert list(ours) == ["OBSERVATION_SCHEMA", "OBSERVATION_VALIDATOR", "validate_observation"]
    for name in ours:
        assert ast.dump(ours[name]) == ast.dump(theirs[name]), name
    # the six-W half stays out: S1 owns it as storage.adapters.message_schema
    assert not hasattr(schema_module, "validate_message") and not hasattr(schema_module, "VALIDATOR")
    assert {"SCHEMA", "VALIDATOR", "validate_message"} <= set(theirs)


def test_the_schema_import_home_and_header():
    text = text_of(schema_module)
    assert import_modules(text) == ["codex_harness.kernel.errors", "importlib.resources", "jsonschema"]
    assert plain_imports(text) == ["json"]
    doc = header(schema_module)
    assert "Layer: adapters\nContext: observation\n" in doc and "Entry points: validate_observation" in doc and "Contracts: INV-OBSERVATION-001" in doc
    assert "Owns:" in doc and "Does not own:" in doc and "R-sc0" in doc
    assert schema_module.ContractError is ContractError


def good_event():
    from codex_harness.observation.domain.observation import build_event, execution_identity
    run = "0" * 31 + "1"
    return build_event(event_type="general.process_started", outcome="started", execution=execution_identity("system", process_run_id=run),
                       sequence={"process_run_id": run, "number": 1, "basis": "spool_append"}, observed_at="2026-01-01T00:00:00+00:00",
                       source={"component": "unit", "host": "h", "pid": 1}, attributes={})


def test_a_valid_event_is_returned_as_the_same_object():
    event = good_event()
    assert schema_module.validate_observation(event) is event


@pytest.mark.parametrize("path,value", [(["event_id"], CANARY), (["severity"], CANARY), (["observed_at"], CANARY), (["summary"], CANARY),
                                        (["source", "component"], {"v": CANARY}), (["execution", "task_id"], CANARY),
                                        (["evidence_refs"], [CANARY, ""]), (["sequence", "number"], CANARY), (["correlation_id"], CANARY * 30)])
def test_validate_observation_names_path_and_keyword_and_never_echoes_an_instance_value(path, value):
    event = good_event()
    node = event
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value
    with pytest.raises(ContractError) as refused:
        schema_module.validate_observation(event)
    message = str(refused.value)
    assert CANARY not in message
    assert all(piece.startswith("[") and "]: " in piece for piece in message.split("; "))


def test_the_error_is_capped_at_five_entries_in_sorted_path_order():
    event = good_event()
    event.update({"event_id": CANARY, "severity": CANARY, "outcome": CANARY, "category": CANARY, "event_type": CANARY, "reason_code": CANARY,
                  "observed_at": CANARY, "summary": CANARY})
    event["execution"]["process_run_id"] = CANARY
    with pytest.raises(ContractError) as refused:
        schema_module.validate_observation(event)
    pieces = str(refused.value).split("; ")
    assert len(pieces) == 5 and CANARY not in str(refused.value)
    assert [p.split("]: ")[0] for p in pieces] == sorted(p.split("]: ")[0] for p in pieces)


# ----- U2 spool ------------------------------------------------------------------------------------------------------------------------------
def test_the_spool_module_is_m7s_in_m7s_order_modulo_imports_and_header():
    ours, theirs = statements(text_of(spool_module)), statements(show(SOURCE, SPOOL_M7))
    assert list(ours) == list(theirs)
    for name, node in theirs.items():
        assert ast.dump(ours[name]) == ast.dump(node), name
    assert list(ours) == ["run_lock_path", "LIFECYCLE_TIMEOUT", "lifecycle_lock", "writer_alive", "RECORD_KINDS", "LINE", "RECORD_ID", "IDENTIFIER_NAME",
                          "SEGMENT", "atomic_write", "encode_record", "read_records", "segment_path", "segment_identity", "read_acknowledged", "FileSpool",
                          "MemorySpool", "SpoolDirectory"]


def test_the_s4_part_is_unchanged_against_the_base_head():
    ours, base = statements(text_of(spool_module)), statements(show(BASE, SPOOL_REL))
    assert sorted(base) == ["MemorySpool", "RECORD_KINDS", "encode_record"]
    for name, node in base.items():
        assert ast.dump(ours[name]) == ast.dump(node), name


def test_the_spool_import_homes_and_header():
    text = text_of(spool_module)
    assert import_modules(text) == ["__future__", "codex_harness.kernel.errors", "codex_harness.kernel.ids", "codex_harness.kernel.policy",
                                    "codex_harness.observation.ports", "filelock", "pathlib"]
    assert plain_imports(text) == ["hashlib", "json", "os", "re", "tempfile", "time"]
    assert not [m for m in import_modules(text) if m.startswith(FORBIDDEN_HOMES)]
    doc = header(spool_module)
    assert "Layer: adapters\nContext: observation\n" in doc and "Contracts: INV-OBSERVATION-001" in doc
    assert "Owns:" in doc and "Does not own:" in doc and "Entry points:" in doc and "R-sp0" in doc
    for name in ("FileSpool", "SpoolDirectory", "MemorySpool", "encode_record", "writer_alive", "lifecycle_lock", "atomic_write", "read_records"):
        assert name in doc.split("Entry points:")[1].split("\n")[0], name
    assert spool_module.SpoolFull is observation_ports.SpoolFull


def test_call_signatures_are_m7s_and_nothing_is_injected():
    m7 = statements(show(SOURCE, SPOOL_M7))
    for name in ("FileSpool", "SpoolDirectory"):
        theirs = [n for n in m7[name].body if isinstance(n, ast.FunctionDef) and n.name == "__init__"][0]
        parameters = inspect.signature(getattr(spool_module, name).__init__).parameters
        assert [p for p in parameters if p != "self"] == [a.arg for a in theirs.args.args[1:] + theirs.args.kwonlyargs], name
    parameters = inspect.signature(spool_module.FileSpool.__init__).parameters
    assert [(p.name, p.kind.name) for p in parameters.values()][:4] == [("self", "POSITIONAL_OR_KEYWORD"), ("root", "POSITIONAL_OR_KEYWORD"),
                                                                       ("process_run_id", "POSITIONAL_OR_KEYWORD"), ("max_bytes", "KEYWORD_ONLY")]
    assert [p for p in inspect.signature(spool_module.SpoolDirectory.__init__).parameters] == ["self", "root"]


def test_the_module_level_names_m7s_lifecycle_tests_patch_are_kept():
    """`tests/test_observation_review5.py` monkeypatches `LIFECYCLE_TIMEOUT` on the module and reads `run_lock_path`, `lifecycle_lock`, `writer_alive`."""
    assert spool_module.LIFECYCLE_TIMEOUT == 10.0
    for name in ("run_lock_path", "lifecycle_lock", "writer_alive", "SEGMENT", "LINE", "RECORD_ID", "IDENTIFIER_NAME", "atomic_write", "read_records",
                 "segment_path", "segment_identity", "read_acknowledged"):
        assert hasattr(spool_module, name), name


def test_a_spool_smaller_than_two_records_refuses_the_second_and_keeps_exactly_the_first(tmp_path):
    line = len(spool_module.encode_record("event", {"a": 1}))
    spool = spool_module.FileSpool(tmp_path, "0" * 31 + "1", max_bytes=line + 10, fsync=False)
    try:
        assert spool.append("event", {"a": 1}) == line
        with pytest.raises(observation_ports.SpoolFull):
            spool.append("event", {"a": 2})
        rows = list(spool_module.read_records(tmp_path / "spool" / ("0" * 31 + "1.0000.jsonl")))
        assert [(r[2], r[4]) for r in rows] == [("complete", {"a": 1})]
    finally:
        spool.close()


# ----- no new spawn site, no M7 home ---------------------------------------------------------------------------------------------------------
def test_neither_module_spawns_a_process_or_imports_an_m7_home():
    for module in (schema_module, spool_module):
        path = Path(module.__file__)
        assert spawn_sites(path) == [], path
        text = path.read_text()
        assert "subprocess" not in text and "multiprocessing" not in text and "Popen" not in text, path
        assert not [m for m in import_modules(text) if m.startswith(FORBIDDEN_HOMES)], path
