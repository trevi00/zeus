"""The one coverage table (REBUILD-DESIGN-v2 §1.5; S0 exit check 2).

Always checked: the pinned ledger identity, the per-kind counts, the key-set digest, the allowed
status/intent values, an owner/symbol/evidence on every mapped row, explicit untraced flags and
bucket candidates, and that only the rows of an implemented slice (S1: kernel, storage, host_os) claim
`implemented`, each with target evidence and a resolvable target module; nothing is `verified` before
Codex accepts the slice. With `ZEUS_REBUILD_LEDGER` naming
the pinned ledger file, the table is regenerated and must be byte-identical (key set included).
"""

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
TABLE = ROOT / "coverage" / "ledger-coverage.json"
PINNED = {"module": 289, "contract": 91, "cli_node": 152, "console_script": 5, "module_entry": 36,
          "http_route": 10, "resource": 33, "capability": 10, "bucket": 169, "flow": 5,
          "public_api": 1769}


@pytest.fixture(scope="module")
def table():
    return json.loads(TABLE.read_text(encoding="utf-8"))


def test_pinned_ledger_and_counts(table):
    assert table["ledger_sha256"] == "38a84d48e4ede80839850fa087e87d526d885fdd32aa452193cb0ad307c048ee"
    assert table["source_commit"] == "e38aa722ff1e91dc01ec650689cfe3eebe1ff699"
    counts = {k: v for k, v in table["counts"].items() if k != "atomic_unit"}
    assert counts == PINNED
    assert table["extra_counts"]["cli_roots"] == 51 and table["extra_counts"]["main_guards"] == 19
    rows = table["rows"]
    assert len({r["key"] for r in rows}) == len(rows)
    keys = sorted(r["key"] for r in rows if r["kind"] != "atomic_unit")
    assert hashlib.sha256("\n".join(keys).encode()).hexdigest() == table["ledger_key_digest"]


def test_row_fields_and_values(table):
    for r in table["rows"]:
        assert r["status"] in table["statuses"]
        assert r["intent"] == "preserve" or r["intent"].startswith(("change:§4 ", "retire:U")), r["key"]
        if r["status"] in {"designed", "implemented"}:
            assert r["target_owner"] and r["target_symbol"] and r["evidence"], r["key"]
        else:
            assert r["status"] == "unmapped" and not r["target_symbol"], r["key"]


IMPLEMENTED_OWNERS = {"kernel", "storage", "host_os"}  # slices implemented so far: S1


def test_only_implemented_slices_claim_implemented_and_nothing_is_verified_early(table):
    assert {r["status"] for r in table["rows"]} <= {"designed", "unmapped", "implemented"}
    assert table["adapters"] == []
    implemented = [r for r in table["rows"] if r["status"] == "implemented"]
    assert implemented and all(r["target_owner"] in IMPLEMENTED_OWNERS for r in implemented)
    for r in implemented:
        assert any(e.startswith(("target:", "compare:", "codex_harness.")) for e in r["evidence"]), r["key"]
        assert not any(e.startswith("pending:") for e in r["evidence"]), r["key"]


def test_implemented_rows_name_modules_that_exist_in_the_target(table):
    src = ROOT / "target" / "src"
    for r in table["rows"]:
        if r["status"] != "implemented" or r["kind"] not in {"module", "public_api"}:
            continue
        for symbol in r["target_symbol"]:
            module = symbol.split(" ")[0].split(":")[0]
            if not module.startswith("codex_harness."):
                continue
            base = src.joinpath(*module.split("."))
            assert base.with_suffix(".py").is_file() or (base / "__init__.py").is_file(), (r["key"], symbol)


def test_s1_module_rows_are_all_accounted_for(table):
    rows = [r for r in table["rows"] if r["kind"] == "module" and r["target_owner"] in IMPLEMENTED_OWNERS]
    assert len(rows) == 27
    partial = {r["key"] for r in rows if r["status"] == "designed"}
    assert partial == {"module:src/codex_harness/domain/model.py", "module:src/codex_harness/adapters/contracts.py",
                       "module:src/codex_harness/adapters/__init__.py",
                       "module:src/codex_harness/application/__init__.py",
                       "module:src/codex_harness/domain/__init__.py"}
    assert all(r.get("slice_progress") for r in rows if r["key"].endswith(("model.py", "contracts.py")))


def test_untraced_rows_stay_explicit(table):
    rows = table["rows"]
    modules = [r for r in rows if r["kind"] == "module"]
    assert sum(r["untraced"] for r in modules) == 289  # 279 listed + 10 hot spots with untraced rest
    assert sum(r["trace"] == "listed, untraced" for r in modules) == 279
    contracts = [r for r in rows if r["kind"] == "contract"]
    assert sum(r["trace"] == "listed, untraced" for r in contracts) == 79
    assert all(r["candidate"] for r in rows if r["kind"] == "bucket")


def test_unmapped_rows_are_named(table):
    unmapped = sorted(r["key"] for r in table["rows"] if r["status"] == "unmapped")
    assert unmapped == sorted("bucket:" + n for n in table["extra_counts"]["static_bucket_scan"]["ledger_only"])


def test_decision_unit_row_is_recorder_confirmed(table):
    row = next(r for r in table["rows"]
               if r["key"] == "atomic_unit:codex_harness.adapters.executor:Executor._commit_decision#1")
    assert row["evidence"] == ["compare:effects.decision_unit", "compare:effects.decision_unit.pg"]
    assert "disposable PostgreSQL" in row["trace"]
    assert {"coordination", "review"} <= set(row["bucket_owners"])


@pytest.mark.skipif(not os.environ.get("ZEUS_REBUILD_LEDGER"),
                    reason="ZEUS_REBUILD_LEDGER not set: the 13 MB pinned ledger lives in the artifact store")
def test_table_regenerates_from_the_pinned_ledger():
    done = subprocess.run([sys.executable, str(ROOT / "coverage" / "generate.py"), "--ledger",
                           os.environ["ZEUS_REBUILD_LEDGER"], "--check"], capture_output=True, text=True)
    assert done.returncode == 0, done.stdout + done.stderr
