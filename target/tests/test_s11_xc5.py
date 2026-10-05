"""S11 XC-5 (TQ-XCUT-PLAN section 8 A5): the COMPOSED desk turn (`composition.operation._Roles`) supplies the monitoring
evidence, so a desk conversation is answered instead of refused (M7 `adapters/frontdesk.py:280`, the default capture).

Behavioural: a real FrontDesk over a memory store and a recording executor, driven through `_Roles.execute_frontdesk`;
the runtime directory is the composition's `configuration.runtime_dir`, controlled through its settings seam."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from codex_harness.composition import configuration, operation
from codex_harness.intake.adapters.frontdesk import execute_frontdesk
from codex_harness.kernel.errors import ContractError
from test_s8_frontdesk_adapter_move import REVISION, SUPPLIED, FakeGit, document, executor, turn


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    values = {"HARNESS_RUNTIME_DIR": str(tmp_path / "runtime")}
    monkeypatch.setattr(configuration, "settings", lambda: values)
    monkeypatch.setattr(configuration, "repository_root", lambda: tmp_path)
    (tmp_path / "runtime").mkdir()
    return tmp_path / "runtime"


def composed_turn():
    service, request_id, task = turn()
    calls, git = [], FakeGit()
    result = operation._Roles(executor(service, calls, git)).execute_frontdesk(task, "beat")
    return result, calls, git, request_id


def test_a_composed_desk_turn_without_a_capture_runs_with_explicit_unknown_monitoring_evidence(runtime):
    assert not (runtime / "monitoring.json").exists()
    result, calls, git, request_id = composed_turn()
    assert len(calls) == 1 and git.workspaces == [(REVISION, "desk-" + request_id)]
    assert calls[0]["read_only"] is True and calls[0]["action"] == "frontdesk"
    facts = calls[0]["evidence"]["fleet_snapshot"]
    # M7 monitoring_evidence(missing file): explicit unknown, never current, healthy or a failure
    assert facts["availability"] == "unknown" and facts["reason_code"] == "snapshot_missing"
    assert facts["freshness"] == "unknown" and facts["fleet"] is None and facts["collected_at"] is None
    assert result["frontdesk"]["request_id"] == request_id


def test_a_composed_desk_turn_with_a_fresh_capture_carries_its_facts(runtime):
    collected = datetime.now(timezone.utc) - timedelta(seconds=5)
    (runtime / "monitoring.json").write_text(json.dumps(document(collected)), "utf-8")
    _result, calls, _git, _request_id = composed_turn()
    assert len(calls) == 1
    facts = calls[0]["evidence"]["fleet_snapshot"]
    assert facts["availability"] == "observed" and facts["freshness"] == "current" and facts["basis"] == "current_capture"
    assert facts["collected_at"] == collected.isoformat() and 0 <= facts["age_seconds"] < 20
    assert set(facts["sources"]) >= {"database", "docker", "redis"}


def test_the_adapter_still_refuses_a_direct_call_without_a_snapshot(runtime):
    service, _request_id, task = turn()
    calls = []
    with pytest.raises(ContractError, match=SUPPLIED):
        execute_frontdesk(executor(service, calls), task, None)
    assert calls == []
