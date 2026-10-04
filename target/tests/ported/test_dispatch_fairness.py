"""Ported SOURCE M7 suite `tests/test_dispatch_fairness.py` (e38aa722) run against the S9 target.

Every assertion is M7's, unchanged. Adaptations (construction, import and patch-target only; the shim is `m7_observation`):
- `MemorySpool`, `MemoryDirectory`, `Observer` and `new_process_run_id` are `m7_observation`'s (their S9 homes);
- `from codex_harness import cli` moves into the test body as the S10 target roots (K1): `serve._serve(service, ...)` is `entry.cli.serve._serve`,
  `cli.emit` is `entry.cli.output.emit`, `cli.RedisBus` is `composition.cli_bus.bus`, `cli.build_executor` is `composition.operation.build_executor`,
  `cli.build_observer` is `composition.observation.build_observer`, and the service's `flush_outbox` is the flusher `composition.cli_bus.flusher(service)` returns.
"""
from types import SimpleNamespace

import pytest
from m7_observation import MemoryDirectory, MemorySpool, Observer, new_process_run_id


@pytest.mark.parametrize("empty_queue", [None, "task", "decision"])
def test_continuous_task_backlog_cannot_starve_review_and_diagnosis(monkeypatch, empty_queue):
    from codex_harness.composition import cli_bus, observation, operation
    from codex_harness.entry.cli import output, serve
    # Both queues remain nonempty: finishing tasks must still leave turns for reviews.
    executor = SimpleNamespace(execute_one=lambda agent: None if empty_queue == "task" else {"kind": "task"},
        decide_one=lambda agent: None if empty_queue == "decision" else {"kind": "decision"},
        observer=Observer(None, MemorySpool(new_process_run_id()), component="unit", directory=MemoryDirectory()))
    service = SimpleNamespace(store=None, org=SimpleNamespace(actor=lambda agent: None))
    monkeypatch.setattr(cli_bus, "flusher", lambda service: SimpleNamespace(flush=lambda bus, **kwargs: None))
    monkeypatch.setattr(cli_bus, "bus", lambda *args: SimpleNamespace(receive=lambda *a: None))
    monkeypatch.setattr(operation, "build_executor", lambda *args, **kwargs: executor)
    monkeypatch.setattr(observation, "build_observer", lambda *args, **kwargs: executor.observer)
    emitted = []

    class StopFixture(Exception):
        pass

    def emit(data):
        if "execution" in data:
            emitted.append(data["execution"]["kind"])
            if len(emitted) == 6:
                raise StopFixture

    monkeypatch.setattr(output, "emit", emit)
    with pytest.raises(StopFixture):
        serve._serve(service, "lead:improvement", once=False, execute=True)
    if empty_queue:
        assert emitted.count("decision" if empty_queue == "task" else "task") == 6
    else:
        assert emitted.count("task") == emitted.count("decision") == 3
