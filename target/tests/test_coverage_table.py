"""The one coverage table (REBUILD-DESIGN-v2 §1.5; S0 exit check 2).

Always checked: the pinned ledger identity, the per-kind counts, the key-set digest, the allowed
status/intent values, an owner/symbol/evidence on every mapped row, explicit untraced flags and
bucket candidates, and that only the rows of an implemented slice (S1: kernel, storage, host_os) claim
`implemented`, each with target evidence and a resolvable target module; nothing is `verified` before
Codex accepts the slice (S11 L: `coverage/relabel.py` now computes every status from the evidence; the checks below
that pinned the pre-relabel statuses carry `# S11 L`). With `ZEUS_REBUILD_LEDGER` naming
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
          "public_api": 1769,
          "addition": 25}  # S9 D4 additive rows, no SOURCE counterpart: X1a 12 (DESIGN-s9-X §1); X1b-1 catalog_observer,
#                            X2a bucket + 3 modules (§2.2), X3a resource_facts (§3), X4a rules + runbook (§4),
#                            X2c queue_facts (§2.4), X5a feature_registry (§5.1), G3 redis_stream_facts, X4b rules + runbook


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
        assert r["intent"] == "preserve" or r["intent"].startswith(("change:§4 ", "retire:U", "addition:")), r["key"]
        if r["intent"].startswith("addition:"):  # an addition has an authority, a target and its own tests (D4)
            assert r["kind"] == "addition" and len(r["intent"]) > len("addition:") and r["target_symbol"], r["key"]
        if r["status"] in {"designed", "implemented", "verified"}:  # S11 L: `verified` rows are mapped rows too
            assert r["target_owner"] and r["target_symbol"] and r["evidence"], r["key"]
        else:
            assert r["status"] == "unmapped" and not r["target_symbol"], r["key"]


S1_OWNERS = {"kernel", "storage", "host_os"}
S2_OWNERS = {"routing", "context", "knowledge"}
S3_OWNERS = {"execution", "credentials"}  # S3: the container/credential rows only (execution is shared with S4)
S4_EARLY_OWNERS = {"coordination", "intake", "research"}  # S4 Option A: moved-ahead owner operations only
S6_EARLY_OWNERS = {"delivery"}  # S6: the delivery domain moved ahead (DESIGN-s6 §2; S7 owns the rest)
S7_EARLY_OWNERS = {"review"}  # S7: ReleaseQueue/Releases moved ahead for delivery (DESIGN-s7 V3; S8 owns the rest)
IMPLEMENTED_OWNERS = S1_OWNERS | S2_OWNERS | S3_OWNERS | S4_EARLY_OWNERS | S6_EARLY_OWNERS | S7_EARLY_OWNERS


def test_only_implemented_slices_claim_implemented_and_nothing_is_verified_early(table):
    # S11 L: every slice is accepted, so rows are verified by `coverage/relabel.py` (R-L3), never by hand: a verified
    # row names no pending item, its verification record lists the passing items, and no row is retired or unmapped.
    assert {r["status"] for r in table["rows"]} <= {"designed", "implemented", "verified"}
    assert table["adapters"] == []
    implemented = [r for r in table["rows"] if r["status"] == "implemented"]
    assert implemented
    for r in implemented:
        assert r["target_owner"] and r["target_symbol"] and r["evidence"], r["key"]
        assert r["verification"]["unmet"], r["key"]  # implemented = resolves and has executable evidence, not verified
    # S11 L2: the rows stay frozen, so a resolved `pending:` item is still in `evidence`; it must be named by a cited
    # entry of `coverage/evidence-resolutions.json` (R-L6), and no other pending item may remain on a verified row.
    resolved = {(e["key"], e["pending"]) for e in json.loads(
        (ROOT / "coverage" / "evidence-resolutions.json").read_text(encoding="utf-8"))["resolutions"]}
    for r in table["rows"]:
        if r["status"] == "verified":
            assert r["verification"]["passed"] and all(
                (r["key"], e) in resolved for e in r["evidence"] if e.startswith("pending:")), r["key"]


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
            if ":" not in symbol.split(" ")[0] and not (base.with_suffix(".py").is_file() or (base / "__init__.py").is_file()):
                base = base.parent  # S11 L: `module.Name` (the relabel resolves the last component as the symbol)
            assert base.with_suffix(".py").is_file() or (base / "__init__.py").is_file(), (r["key"], symbol)


def test_s1_module_rows_are_all_accounted_for(table):
    rows = [r for r in table["rows"] if r["kind"] == "module" and r["target_owner"] in S1_OWNERS]
    assert len(rows) == 27
    # S11 L: the relabel measured the S1 rows: five layer-marker / package-root rows have no resolving code symbol
    # (designed); model, contracts and commands resolve but name unmet evidence (implemented); the rest are verified.
    # S11 MC2 (R-MC2-3/-5): the package root now resolves as `codex_harness`; four layer markers stay designed.
    partial = {r["key"] for r in rows if r["status"] == "designed"}
    assert partial == {"module:src/codex_harness/resources/__init__.py",
                       "module:src/codex_harness/adapters/__init__.py",
                       "module:src/codex_harness/application/__init__.py",
                       "module:src/codex_harness/domain/__init__.py"}
    assert {r["key"] for r in rows if r["status"] == "implemented"} == {"module:src/codex_harness/adapters/commands.py"}
    assert sum(r["status"] == "verified" for r in rows) == 21
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
    # S11 L (R-L7, S10-PACKET §4b): the four formerly unmapped buckets are traced; none stays unmapped. One is a real
    # bucket, three are constants of host_migration.py (mapping_correction), each verified by the relabel.
    rows = {r["key"]: r for r in table["rows"]}
    assert not [r for r in rows.values() if r["status"] == "unmapped"]
    ledger_only = sorted("bucket:" + n for n in table["extra_counts"]["static_bucket_scan"]["ledger_only"])
    assert ledger_only == ["bucket:discovery_pressure", "bucket:fleet-owner.json", "bucket:urn:zeus:aibox-fleet-owner:1",
                           "bucket:zeus-aibox-fleet.service"]
    for key in ledger_only:
        assert rows[key]["status"] == "verified" and rows[key]["mapping_correction"], key
    assert [k for k in ledger_only if rows[k]["mapping_correction"].startswith("not a bucket (S10-PACKET §4b)")] == \
        ledger_only[1:]


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


def test_s2_module_rows_are_all_accounted_for(table):
    rows = [r for r in table["rows"] if r["kind"] == "module" and r["target_owner"] in S2_OWNERS]
    assert len(rows) == 41
    # S11 L: S10 moved the three entry mains; every S2 module row is now verified by the relabel
    partial = {"module:src/codex_harness/adapters/skill_import.py", "module:src/codex_harness/adapters/skill_audit.py",
               "module:src/codex_harness/adapters/experience.py"}
    assert {r["status"] for r in rows} == {"verified"}
    assert all("S10" in r["slice_progress"] for r in rows if r["key"] in partial)
    replay = next(r for r in rows if r["key"].endswith("native_routing_replay.py"))
    assert replay["target_owner"] == "context" and replay["mapping_correction"]
    for key in ("module:src/codex_harness/adapters/executor.py", "module:src/codex_harness/domain/model.py"):
        row = next(r for r in table["rows"] if r["key"] == key)
        assert "S2 implemented" in row["slice_progress"] and row["status"] == "verified"  # S11 L: was designed
    s2_contracts = [r for r in table["rows"] if r["kind"] == "contract" and r["target_owner"] in S2_OWNERS]
    assert len(s2_contracts) == 16 and all(r["status"] in {"implemented", "verified"} for r in s2_contracts)  # S11 L


S3_MODULES = {"isolated_worker.py", "role_containers.py", "app_server.py", "output_schema.py", "execution_output.py",
              "codex.py", "hooks.py"}


def test_s3_rows_are_accounted_for(table):
    rows = {r["key"]: r for r in table["rows"]}
    # S11 L: measured by the relabel. Every S3 module row resolves and all its items pass (R-L2b: app_server and hooks name
    # `compare:hooks.native_container`, a reference-only family, which is context): all verified.
    statuses = {name: rows["module:src/codex_harness/adapters/" + name]["status"] for name in S3_MODULES}
    assert statuses == {"isolated_worker.py": "verified", "role_containers.py": "verified", "output_schema.py": "verified",
                        "execution_output.py": "verified", "codex.py": "verified", "app_server.py": "verified",
                        "hooks.py": "verified"}
    for name in S3_MODULES:
        assert "S3" in rows["module:src/codex_harness/adapters/" + name]["slice_progress"], name
    apis = [r for r in table["rows"] if r["kind"] == "public_api"
            and r["key"].split("::")[0].rsplit("/", 1)[-1] in {"isolated_worker.py", "role_containers.py", "app_server.py"}]
    assert apis and all(r["status"] in {"implemented", "verified"} for r in apis)
    for key in ("contract:INV-ROLE-CONTAINER-001", "contract:INV-CODEX-CREDENTIAL-001"):
        # S11 L2: both contracts are cited by a feature-map-named target test (G2), so the relabel verifies them
        assert rows[key]["status"] == "verified" and "S4" in rows[key]["slice_progress"]


S4_IMPLEMENTED = {"application/invocation_ledger.py", "domain/invocation.py", "adapters/call_budget.py",
                  "domain/provider_stream.py", "domain/worker_sessions.py", "application/worker_sessions.py",
                  "adapters/codex.py", "adapters/claude_cli.py", "adapters/hooks.py"}
S4_REMAINING = {"adapters/executor.py", "adapters/worker_sessions.py"}


def test_s4_rows_moved_so_far_are_implemented_and_the_rest_stay_designed(table):
    """S4 (in progress): only the modules with a target move and compare/target evidence are implemented."""
    rows = {r["key"]: r for r in table["rows"]}
    # S11 L: the relabel verified the rows whose items all pass (R-L2b: a target-driverless family is context)
    for name in S4_IMPLEMENTED:
        row = rows["module:src/codex_harness/" + name]
        assert row["status"] == "verified", name
        assert "S4 implemented" in row["slice_progress"], name
        assert any(e.startswith(("compare:", "target:tests/")) for e in row["evidence"]), name
    assert {name: rows["module:src/codex_harness/" + name]["status"] for name in S4_REMAINING} == {
        "adapters/executor.py": "verified", "adapters/worker_sessions.py": "verified"}


def _generator():
    sys.path.insert(0, str(ROOT / "coverage"))
    try:
        import generate
    finally:
        sys.path.remove(str(ROOT / "coverage"))
    return generate


def test_the_regeneration_check_compares_the_generated_skeleton_and_still_sees_skeleton_drift(table):
    """SKIPPED-TEST-CLOSURE-20261004 B: the generator owns the skeleton; the integrations own MAINTAINED_FIELDS and the
    addition rows (since S3, 0a8737cc). A drift in any generator-owned field must still fail the check."""
    import copy

    generate = _generator()
    base = generate.skeleton(table)
    maintained = copy.deepcopy(table)
    row = next(r for r in maintained["rows"] if r["kind"] == "module")
    for field in generate.MAINTAINED_FIELDS:
        row[field] = "edited by an integration"
    maintained["rows"].append({**row, "key": "addition:fixture/extra", "kind": generate.ADDITION})
    maintained["counts"][generate.ADDITION] = maintained["counts"].get(generate.ADDITION, 0) + 1
    assert generate.skeleton(maintained) == base
    for field, value in (("trace", "changed"), ("kind", "contract"), ("layer", "changed"), ("untraced", None)):
        drifted = copy.deepcopy(table)
        next(r for r in drifted["rows"] if r["kind"] == "module")[field] = value
        assert generate.skeleton(drifted) != base, field
    removed = copy.deepcopy(table)
    removed["rows"] = [r for r in removed["rows"] if r["kind"] == generate.ADDITION or r is not removed["rows"][0]]
    assert generate.skeleton(removed) != base
    assert not generate.MAINTAINED_FIELDS & {"key", "kind", "layer", "trace", "untraced", "intent", "candidate"}
