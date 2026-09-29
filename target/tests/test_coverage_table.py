"""The one coverage table (REBUILD-DESIGN-v2 §1.5; S0 exit check 2).

Always checked: the pinned ledger identity, the per-kind counts, the key-set digest, the allowed
status/intent values, an owner/symbol/evidence on every mapped row, explicit untraced flags and
bucket candidates, and that S0 claims nothing beyond `designed`. With `ZEUS_REBUILD_LEDGER` naming
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
        if r["status"] == "designed":
            assert r["target_owner"] and r["target_symbol"] and r["evidence"], r["key"]
        else:
            assert r["status"] == "unmapped" and not r["target_symbol"], r["key"]


def test_s0_claims_nothing_beyond_designed(table):
    assert {r["status"] for r in table["rows"]} <= {"designed", "unmapped"}
    assert table["adapters"] == []


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
    assert row["evidence"] == ["compare:effects.decision_unit"]
    assert {"coordination", "review"} <= set(row["bucket_owners"])


@pytest.mark.skipif(not os.environ.get("ZEUS_REBUILD_LEDGER"),
                    reason="ZEUS_REBUILD_LEDGER not set: the 13 MB pinned ledger lives in the artifact store")
def test_table_regenerates_from_the_pinned_ledger():
    done = subprocess.run([sys.executable, str(ROOT / "coverage" / "generate.py"), "--ledger",
                           os.environ["ZEUS_REBUILD_LEDGER"], "--check"], capture_output=True, text=True)
    assert done.returncode == 0, done.stdout + done.stderr
