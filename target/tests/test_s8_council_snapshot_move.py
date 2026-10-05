"""S8 pilot 79: the M7 council snapshot port moved into research, VERBATIM through one named rule
(A/evidence/rebuild/s8/council-snapshot-move/transcribe.py; DESIGN-s8 §6 V11).

M7 is read only as text through `git show e38aa722:...` and compared by AST (never imported: both packages are named
`codex_harness`). Behaviour is checked on the TARGET only, against literals; the recorded comparison is the
`research.council_snapshot` golden.
"""
import ast
import importlib
import subprocess
from pathlib import Path

import pytest
from _layout import REPO

SOURCE = "e38aa722"
MODULE = "codex_harness.research.adapters.council_snapshot"
M7_PATH = "src/codex_harness/adapters/council_snapshot.py"
R_S0_IMPORTS = {
    "codex_harness.kernel.errors": ["ContractError"],
    "codex_harness.kernel.ids": ["digest", "utcnow"],
    "codex_harness.research.domain.council": ["snapshot_envelope", "snapshot_records", "validate_current_state"],
}
M7_IMPORTS = {"codex_harness.domain.council": ["snapshot_envelope", "snapshot_records", "validate_current_state"],
              "codex_harness.domain.model": ["ContractError", "digest", "utcnow"]}
SELECTION = [{"bucket": "tasks", "id": "task-known"}, {"bucket": "operations", "id": "op-missing"}]
BINDING = dict(topic="t", run_id="council-001", base_revision="a" * 40, max_age_seconds=600)


def m7_text():
    return subprocess.run(["git", "-C", str(REPO), "show", f"{SOURCE}:{M7_PATH}"], check=True, capture_output=True, text=True).stdout


def target_text():
    return Path(importlib.import_module(MODULE).__file__).read_text()


def defined(node):
    if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
        return (node.name,)
    if isinstance(node, ast.Assign):
        return tuple(n.id for t in node.targets for n in ast.walk(t) if isinstance(n, ast.Name))
    return ()


def statements(src):
    out = {}
    for i, node in enumerate(ast.parse(src).body):
        if isinstance(node, (ast.Import, ast.ImportFrom)) or (
                isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)):
            continue
        key = defined(node) or ("expr", i)
        assert key not in out
        out[key] = node
    return out


def from_imports(src):
    return {n.module: [a.name for a in n.names] for n in ast.parse(src).body if isinstance(n, ast.ImportFrom)}


def test_every_statement_is_m7_s_by_ast_in_m7_order():
    ref, ours = statements(m7_text()), statements(target_text())
    assert list(ours) == list(ref) == [("BEGIN",), ("IDENTITY",), ("SELECT",), ("SnapshotUnavailable",), ("ReadOnlySnapshot",), ("__all__",)]
    for key in ref:
        assert ast.dump(ours[key]) == ast.dump(ref[key]), key


def test_the_only_change_is_the_import_block_r_s0_and_the_header():
    old, new = from_imports(m7_text()), from_imports(target_text())
    assert {k: v for k, v in old.items() if k.startswith("codex_harness.")} == M7_IMPORTS
    assert {k: v for k, v in new.items() if k.startswith("codex_harness.")} == R_S0_IMPORTS
    assert new["contextlib"] == old["contextlib"] == ["contextmanager"] and new["__future__"] == old["__future__"]
    plain = lambda src: [n.names[0].name for n in ast.parse(src).body if isinstance(n, ast.Import)]  # noqa: E731
    assert plain(target_text()) == plain(m7_text()) == ["psycopg"]  # the SDK stays (any adapter may import it)
    # the body below the imports is M7's byte for byte
    marker = "\nBEGIN = "
    assert m7_text().split(marker, 1)[1] == target_text().split(marker, 1)[1]
    doc = ast.get_docstring(ast.parse(target_text()))
    assert doc.startswith(ast.get_docstring(ast.parse(m7_text())))
    for line in ("Layer: adapters", "Context: research", "Entry points: SnapshotUnavailable, ReadOnlySnapshot, BEGIN",
                 "Contracts: INV-COUNCIL-001"):
        assert line in doc.splitlines()


def test_imports_are_only_the_sdk_kernel_and_research_homes():
    mods = {n.module for n in ast.walk(ast.parse(target_text())) if isinstance(n, ast.ImportFrom) and n.module.startswith("codex_harness.")}
    assert mods == set(R_S0_IMPORTS)
    assert "codex_harness.domain" not in target_text().replace("codex_harness.research.domain", "")


def test_the_module_never_writes():
    """Structural: no write word and no `.put(`/`transaction(` in the moved source (S8 move rule); the runtime property
    is covered by test_observe_never_issues_a_write_statement_and_runs_in_a_read_only_transaction."""
    module = importlib.import_module(MODULE)
    src = target_text()
    for word in ("INSERT", "UPDATE", "DELETE", "COMMIT", "CREATE", ".put(", "transaction("):
        assert word not in src, word
    assert module.BEGIN == "BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY"
    assert module.__all__ == ["BEGIN", "ReadOnlySnapshot", "SnapshotUnavailable"]


class Cursor:
    def __init__(self, rows):
        self.rows = rows

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return list(self.rows)


class Conn:
    def __init__(self, log, fail=None):
        self.log, self.fail = log, fail

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.log.append("exit")
        return False

    def execute(self, statement, params=None):
        self.log.append(statement)
        if self.fail and self.fail in statement:
            raise OSError("reset SECRET-dsn")
        if statement.startswith("SELECT current_database"):
            return Cursor([("zeus", "public", "18.0")])
        if statement.startswith("SELECT s.bucket"):
            return Cursor([("tasks", "task-known", {"status": "succeeded", "agent": "conductor"})])
        return Cursor([])


def port(log, fail=None, **kwargs):
    module = importlib.import_module(MODULE)
    return module.ReadOnlySnapshot("host=h password=SECRET-dsn dbname=db", connect=lambda dsn, **kw: Conn(log, fail),
                                   clock=lambda: "2029-01-01T00:00:00+00:00", **kwargs)


def test_observe_issues_the_five_statements_in_order_and_reduces_through_the_research_domain():
    log = []
    envelope = port(log, statement_timeout_ms=250).observe(SELECTION, **BINDING)
    assert [s.split(" ")[0] for s in log if s != "exit"] == ["BEGIN", "SET", "SELECT", "SELECT", "ROLLBACK"] and log[-1] == "exit"
    assert "SET LOCAL statement_timeout = '250ms'" in log
    assert [r["state"] for r in envelope["records"]] == ["found", "missing"]
    assert envelope["expires_at"] == "2029-01-01T00:10:00+00:00" and "SECRET" not in repr(envelope)


def test_observe_never_issues_a_write_statement_and_runs_in_a_read_only_transaction():
    """Behaviour: observe over a connection that fails on any write statement completes, and its one transaction is
    declared READ ONLY (the only statements are BEGIN, SET LOCAL, SELECT and ROLLBACK)."""
    writes = ("INSERT", "UPDATE", "DELETE", "COMMIT", "CREATE", "DROP", "ALTER", "TRUNCATE", "GRANT", "COPY", "MERGE")

    class WriteRefusingConn(Conn):
        def execute(self, statement, params=None):
            assert not any(word in statement.upper().split() for word in writes), f"a write statement: {statement}"
            return super().execute(statement, params)

    log = []
    module = importlib.import_module(MODULE)
    envelope = module.ReadOnlySnapshot("dsn", connect=lambda dsn, **kw: WriteRefusingConn(log),
                                       clock=lambda: "2029-01-01T00:00:00+00:00").observe(SELECTION, **BINDING)
    assert [r["state"] for r in envelope["records"]] == ["found", "missing"]
    statements = [s for s in log if s != "exit"]
    assert statements[0] == "BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY" and statements[-1] == "ROLLBACK"
    assert {s.split(" ")[0] for s in statements} == {"BEGIN", "SET", "SELECT", "ROLLBACK"}


@pytest.mark.parametrize("fail", ["BEGIN", "SET LOCAL", "current_database", "unnest"])
def test_a_failing_statement_is_snapshot_unavailable_with_no_chain(fail):
    module = importlib.import_module(MODULE)
    log = []
    with pytest.raises(module.SnapshotUnavailable) as info:
        port(log, fail).observe(SELECTION, **BINDING)
    exc = info.value
    assert exc.reason_code == "snapshot_unavailable" and str(exc) == "council snapshot snapshot_unavailable"
    assert exc.__cause__ is None and exc.__context__ is None
    assert ("ROLLBACK" in log) == (fail != "BEGIN")  # the rollback follows every BEGIN that was followed by a statement


def test_connect_failures_and_a_none_connection_are_unavailable_and_a_bad_timeout_is_a_contract_error():
    from codex_harness.kernel.errors import ContractError

    module = importlib.import_module(MODULE)

    def refuse(dsn, **kw):
        raise OSError("could not connect to " + dsn)

    for connect in (refuse, lambda dsn, **kw: None):
        with pytest.raises(module.SnapshotUnavailable) as info:
            module.ReadOnlySnapshot("dsn", connect=connect).observe(SELECTION, **BINDING)
        assert info.value.__cause__ is None and info.value.__context__ is None and "dsn" not in str(info.value)
    for bad in (0, -1, True, 5.0, "5", None):
        with pytest.raises(ContractError, match="Snapshot timeouts must be positive integers"):
            module.ReadOnlySnapshot("dsn", connect=refuse, connect_timeout=bad)
        with pytest.raises(ContractError, match="Snapshot timeouts must be positive integers"):
            module.ReadOnlySnapshot("dsn", connect=refuse, statement_timeout_ms=bad)
    assert issubclass(module.SnapshotUnavailable, ContractError)


def test_the_selection_is_validated_before_any_connection():
    from codex_harness.research.domain.autonomous import AutonomousManifestError

    def never(dsn, **kw):
        raise AssertionError("connected")

    module = importlib.import_module(MODULE)
    with pytest.raises(AutonomousManifestError):
        module.ReadOnlySnapshot("dsn", connect=never).observe([{"bucket": "tasks", "id": "t%d" % i} for i in range(21)], **BINDING)


def test_the_default_connect_is_psycopg_and_the_council_driver_uses_this_module():
    import psycopg

    module = importlib.import_module(MODULE)
    assert module.ReadOnlySnapshot("dsn").connect is psycopg.connect
    driver = (REPO / "compare" / "drivers" / "target" / "s8_council.py").read_text()
    assert "from codex_harness.research.adapters.council_snapshot import" in driver
    assert "class ReadOnlySnapshot" not in driver and "class SnapshotUnavailable" not in driver
    assert "class EvidenceUnavailable" not in driver  # the stand-in was removed when autonomous_evidence moved (S8 pilot 80)
