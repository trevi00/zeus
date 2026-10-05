"""S11 unit XC-4 (TQ-XCUT-PLAN §1 C follow-ups U11, U12): schema_version compatibility and per-root file-input bounds.

Behavioural tests only (TQ-XCUT-RESEARCH T1). Expected results come from independent sources, never from the target:
U11 from the packaged schemas (`message.schema.json` `schema_version` const "1.0", `observation.schema.json:9`
`{"const": "1.0"}`) and AGENTS.md ("Inter-agent messages use the versioned six-W JSON schema in package resources");
U12 from the M7 SOURCE golden (`codex_harness` 0.x reference package, read only, never imported here): each test asserts
the bound NUMBER cited with its M7 file:line.

U12 coverage is the six `equal` bounds, one per distinct bound owner. The measurement table of every root (target
bound, M7 bound, class) is in the unit's report; roots whose bound is `both unbounded`, `target stricter` or whose
owner is already covered below are deliberately not tested here.
"""

import json
import sys

import pytest
from test_s10_c5e_cycle_serve import MESSAGE
from test_s11_xc1_boundaries import ConsumerBus, serve_once

from codex_harness import composition
from codex_harness.composition import continuation as continuation_adapter
from codex_harness.entry import cli
from codex_harness.kernel.errors import ContractError
from codex_harness.observation.adapters.observation_schema import validate_observation
from codex_harness.observation.domain.observation import build_event, execution_identity
from codex_harness.research.domain.research_hold import ContinuationRefused
from codex_harness.routing.adapters.organization_source import packaged_organization
from codex_harness.storage.adapters.memory_store import MemoryStore

KIB, MIB = 1024, 1024 * 1024


# --- U11: schema_version compatibility --------------------------------------------------------------------------

def test_a_bus_message_with_another_or_no_schema_version_is_dead_lettered_and_the_next_message_is_served(
        monkeypatch, capsys, tmp_path):
    """message.schema.json `schema_version` const "1.0": "1.1" and a missing version are refused at decode and
    dead-lettered once; "1.0" is accepted (the XC-1 A1 path: ContractError, dead letter + ack, loop continues)."""
    missing = {key: value for key, value in MESSAGE.items() if key != "schema_version"}
    bus = ConsumerBus([("1-0", {"body": json.dumps({**MESSAGE, "schema_version": "1.1"})}),
                       ("2-0", {"body": json.dumps(missing)}),
                       ("3-0", {"body": json.dumps({**MESSAGE, "schema_version": "1.0"})})])
    first = serve_once(monkeypatch, capsys, tmp_path, bus)
    assert first[-1]["rejected"] == "1-0"
    second = serve_once(monkeypatch, capsys, tmp_path, bus)
    assert second[-1]["rejected"] == "2-0"
    third = serve_once(monkeypatch, capsys, tmp_path, bus)
    assert third[-1]["message_id"] == MESSAGE["message_id"]
    assert [entry for entry, _ in bus.dead] == ["1-0", "2-0"] and bus.acked == ["1-0", "2-0", "3-0"]
    assert "schema_version" in bus.dead[0][1] and "schema_version" in bus.dead[1][1]


def valid_event():
    run = "0" * 31 + "1"
    return build_event(event_type="general.process_started", outcome="started",
                       execution=execution_identity("system", process_run_id=run),
                       sequence={"process_run_id": run, "number": 1, "basis": "spool_append"},
                       observed_at="2026-01-01T00:00:00+00:00", source={"component": "unit", "host": "h", "pid": 1},
                       attributes={})


@pytest.mark.parametrize("version", ["1.1", "1.0.0", "1", 1.0, None])
def test_an_observation_record_with_another_schema_version_is_refused_naming_the_field(version):
    """observation.schema.json:9 `{"const": "1.0"}`."""
    event = {**valid_event(), "schema_version": version}
    with pytest.raises(ContractError, match=r"schema_version"):
        validate_observation(event)


def test_an_observation_record_without_a_schema_version_is_refused_and_one_with_1_0_is_accepted():
    event = valid_event()
    assert validate_observation(event) is event and event["schema_version"] == "1.0"
    missing = {key: value for key, value in event.items() if key != "schema_version"}
    with pytest.raises(ContractError):  # the observation text names only the path and keyword (`[]: required`)
        validate_observation(missing)


# --- U12: per-root file-input bounds, the `equal` ones (target bound == M7 bound) ----------------------------------

def sized(path, size):
    """A JSON object file of exactly `size` bytes."""
    body = '{"p":"' + "a" * (size - 8) + '"}'
    assert len(body) == size
    path.write_text(body, encoding="utf-8")
    return path


def run_root(monkeypatch, capsys, tmp_path, argv):
    """Run one `zeus` root on a MemoryStore and a per-test runtime directory; return (exit, stdout, stderr, store)."""
    store = MemoryStore()
    monkeypatch.setattr(composition, "build", lambda: composition.ServiceHandle(store, packaged_organization()))
    monkeypatch.setenv("HARNESS_RUNTIME_DIR", str(tmp_path / "runtime"))
    monkeypatch.setattr(sys, "argv", ["zeus", *argv])
    code = 0
    try:
        cli.main()
    except SystemExit as exc:
        code = exc.code
    out, err = capsys.readouterr()
    return code, out, err, store


def outcome(code, out, err):
    """What the root printed for a refusal: the stderr `{"error": text}`, or (dge, which prints a code and a type and
    never raw text, INV-DGE-001) the stdout `reason_code/error_type`."""
    if err.strip():
        return code, json.loads(err.strip().splitlines()[-1])["error"]
    document = json.loads(out)
    return code, document["reason_code"] + "/" + document["error_type"]


def assert_bound(monkeypatch, capsys, tmp_path, argv_for, bound, over_outcome, next_outcome):
    """`bound` bytes get past the size check and reach the root's next validation (`next_outcome`, measured);
    `bound + 1` is refused with `over_outcome` (exit 1), the store holds no row and no file is written under the runtime directory."""
    at = sized(tmp_path / "at.json", bound)
    code, out, err, _ = run_root(monkeypatch, capsys, tmp_path / "at", argv_for(at))
    assert outcome(code, out, err) == (1, next_outcome)
    over = sized(tmp_path / "over.json", bound + 1)
    code, out, err, store = run_root(monkeypatch, capsys, tmp_path / "over", argv_for(over))
    assert outcome(code, out, err) == (1, over_outcome)
    assert store.data == {}
    assert not [p for p in (tmp_path / "over" / "runtime").rglob("*") if p.is_file()]


def test_goal_report_manifest_bound_is_1_mib(monkeypatch, capsys, tmp_path):
    """M7 cli.py:394 `path.stat().st_size <= 1024 * 1024`, "Goal file exceeds budget" (owner: goal `_json_file`,
    shared by `goal report|compare` and `ticket dispatch --goal-manifest`)."""
    assert_bound(monkeypatch, capsys, tmp_path, lambda path: ["goal", "report", str(path)], MIB,
                 "Goal file exceeds budget", "Goal manifest needs version, id, objective, non_goals and criteria")


def test_dge_submit_event_bound_is_256_kib(monkeypatch, capsys, tmp_path):
    """M7 adapters/operation_cli.py:23 `MAX_MANIFEST_BYTES = 256 * 1024`, :37 `st_size <= MAX_MANIFEST_BYTES`
    (owner: `operation.read_document`, shared by operate, fleet, dge, autonomous, research-program and
    research-package roots)."""
    assert_bound(monkeypatch, capsys, tmp_path,
                 lambda path: ["dge", "submit", "session-1", "--file", str(path)], 256 * KIB,
                 "contract_refused/ContractError", "contract_refused/EventError")


def test_sdd_transfer_record_bound_is_1_mib(monkeypatch, capsys, tmp_path):
    """M7 adapters/sdd.py:17 `stream.read(1024 * 1024 + 1)` then the 1 MiB check (owner: `sdd.load_json`, shared by
    `sdd import-log|transfer-record` and `ticket evidence|prepare-close`)."""
    assert_bound(monkeypatch, capsys, tmp_path,
                 lambda path: ["sdd", "transfer-record", "iteration-1", "--file", str(path)], MIB,
                 "SDD input exceeds 1 MiB budget", "Invalid model transfer record")


def test_execution_recovery_apply_packet_bound_is_1_mib(monkeypatch, capsys, tmp_path):
    """M7 cli.py:737 `args.packet.stat().st_size <= 1024 * 1024`, "Recovery packet exceeds budget"."""
    assert_bound(monkeypatch, capsys, tmp_path,
                 lambda path: ["execution-recovery", "apply", "--packet", str(path)], MIB,
                 "Recovery packet exceeds budget", "Invalid recovery packet")


def test_ticket_close_packet_bound_is_1_mib(monkeypatch, capsys, tmp_path):
    """M7 adapters/ticket_cli.py:38 `stream.read(1024 * 1024 + 1)`, :39 "Closure packet exceeds budget"."""
    assert_bound(monkeypatch, capsys, tmp_path,
                 lambda path: ["ticket", "close", "T-1", "--signature", "a=b", "--packet", str(path)], MIB,
                 "Closure packet exceeds budget", "Ticket identity or canonical signing bytes mismatch")


def test_continuation_receipt_file_bound_is_64_kib(tmp_path):
    """M7 adapters/continuation.py:57 `MAX_POLICY_BYTES = 64 * 1024`, :101 `len(data) > MAX_POLICY_BYTES` (owner:
    `continuation.read_receipt`, shared by research-accept|supplement, capacity-grant, delivery-requalify). The file
    is read by a function, not a store-backed root path, so this drives that function."""
    at = sized(tmp_path / "at.json", 64 * KIB)
    assert continuation_adapter.read_receipt(at)["p"] == "a" * (64 * KIB - 8)
    over = sized(tmp_path / "over.json", 64 * KIB + 1)
    with pytest.raises(ContinuationRefused) as refused:
        continuation_adapter.read_receipt(over)
    assert refused.value.reason_code == "research_receipt_invalid"
