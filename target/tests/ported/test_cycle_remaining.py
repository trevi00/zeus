"""Ported SOURCE M7 suite `tests/test_cycle_remaining.py` (e38aa722) run against the S5 target.

Every assertion is M7's, unchanged. Adaptations, all construction/import: `Harness`, `LocalCycle` and `organization`
come from the `m7_coordination` shim; `MemoryStore` from `storage.adapters`. Every test drives M7's `codex_harness.cli`; they run the S10
target (K1): `cli.parser()` is `entry.cli.parser()`, `cli.emit` is `entry.cli.output.emit` (patched there), and
`cli.cycle_command(svc, args)` is `entry.cli.cycle.run(args)` over the service `composition.build` returns (patched to `svc`).

M7 module docstring follows.

`zeus cycle status` reports remaining_executions as CLI presentation; the stored row is untouched.
"""
from m7_coordination import Harness, LocalCycle, organization

from codex_harness import composition
from codex_harness.entry import cli
from codex_harness.entry.cli import cycle as cycle_root
from codex_harness.entry.cli import output
from codex_harness.storage.adapters.memory_store import MemoryStore

CORR = "improvement:cycle-remaining-test"


def service():
    return Harness(MemoryStore(), organization())


def status_output(svc, monkeypatch, cycle_id="c1"):
    outputs = []
    monkeypatch.setattr(output, "emit", outputs.append)
    monkeypatch.setattr(composition, "build", lambda: svc)
    cycle_root.run(cli.parser().parse_args(["cycle", "status", cycle_id]))
    assert len(outputs) == 1
    return outputs[0]


def set_executions(svc, cycle_id, executions):
    with svc.store.transaction() as tx:
        row = tx.get("local_cycles", cycle_id)
        row["executions"] = executions
        tx.put("local_cycles", cycle_id, row)


def stored_row(svc, cycle_id="c1"):
    with svc.store.transaction() as tx:
        return tx.get("local_cycles", cycle_id)


def test_status_reports_nonzero_remaining_executions(monkeypatch):
    svc = service()
    LocalCycle(svc).start("c1", CORR, 3)
    assert status_output(svc, monkeypatch)["remaining_executions"] == 3
    set_executions(svc, "c1", 1)
    output = status_output(svc, monkeypatch)
    assert output["remaining_executions"] == 2
    assert output["executions"] == 1 and output["max_executions"] == 3


def test_status_reports_zero_remaining_and_never_negative(monkeypatch):
    svc = service()
    LocalCycle(svc).start("c1", CORR, 2)
    set_executions(svc, "c1", 2)
    assert status_output(svc, monkeypatch)["remaining_executions"] == 0
    set_executions(svc, "c1", 5)  # over-budget residue must clamp, not go negative
    assert status_output(svc, monkeypatch)["remaining_executions"] == 0


def test_status_does_not_store_remaining_executions(monkeypatch):
    svc = service()
    LocalCycle(svc).start("c1", CORR, 2)
    before = dict(stored_row(svc))
    output = status_output(svc, monkeypatch)
    assert output["remaining_executions"] == 2
    after = stored_row(svc)
    assert "remaining_executions" not in after
    assert after == before
    assert "remaining_executions" not in LocalCycle(svc).status("c1")


def test_start_and_step_outputs_are_unchanged(monkeypatch):
    svc = service()
    outputs = []
    monkeypatch.setattr(output, "emit", outputs.append)
    monkeypatch.setattr(composition, "build", lambda: svc)
    args = cli.parser().parse_args(["cycle", "start", "c1", "--correlation", CORR, "--max-executions", "2"])
    cycle_root.run(args)
    assert "remaining_executions" not in outputs[0]
    assert "remaining_executions" not in stored_row(svc)
