from types import SimpleNamespace

import pytest

from codex_harness import cli


@pytest.mark.parametrize("empty_queue", [None, "task", "decision"])
def test_continuous_task_backlog_cannot_starve_review_and_diagnosis(monkeypatch, empty_queue):
    # Both queues remain nonempty: finishing tasks must still leave turns for reviews.
    executor = SimpleNamespace(execute_one=lambda agent: None if empty_queue == "task" else {"kind": "task"},
        decide_one=lambda agent: None if empty_queue == "decision" else {"kind": "decision"})
    service = SimpleNamespace(store=None, org=SimpleNamespace(actor=lambda agent: None),
                              flush_outbox=lambda bus: None)
    monkeypatch.setattr(cli, "RedisBus", lambda *args: SimpleNamespace(receive=lambda *a: None))
    monkeypatch.setattr(cli, "build_executor", lambda *args: executor)
    emitted = []

    class StopFixture(Exception):
        pass

    def emit(data):
        if "execution" in data:
            emitted.append(data["execution"]["kind"])
            if len(emitted) == 6:
                raise StopFixture

    monkeypatch.setattr(cli, "emit", emit)
    with pytest.raises(StopFixture):
        cli.serve(service, "lead:improvement", once=False, execute=True)
    if empty_queue:
        assert emitted.count("decision" if empty_queue == "task" else "task") == 6
    else:
        assert emitted.count("task") == emitted.count("decision") == 3
