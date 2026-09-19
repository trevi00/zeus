"""Subscription accounting admission (research program001 batch008). Every ledger here is a real
CallBudget under the test's own root or a LABELLED fake; no provider is ever called. The provider
control tests drive `tests/claude_protocol_child.py`, a labelled protocol fixture recorded with its
launcher: a receipt made this way is never a provider measurement."""
import io
import json
import sys
import threading
from types import SimpleNamespace

import pytest

from codex_harness.adapters import isolated_worker as iw
from codex_harness.adapters import isolated_worker_entry as entry
from codex_harness.adapters.call_budget import CallBudget
from codex_harness.adapters.claude_cli import ClaudeCodeRuntime, claude_settings
from codex_harness.adapters.executor import invocation_options
from codex_harness.adapters.fleet_runtime import LaneLauncher
from codex_harness.adapters.providers import packaged_policy
from codex_harness.adapters.store import MemoryStore
from codex_harness.application.fleet import Fleet
from codex_harness.application.operation import BudgetedExecutor, BudgetRefused
from codex_harness.domain.fleet import FleetRefused, projection, sanitized_config, validate_config
from codex_harness.domain.invocation import parse_request
from codex_harness.domain.model import ContractError
from codex_harness.domain.operation import ManifestError, provider_settings, validate_manifest
from codex_harness.domain.providers import parse_configuration, select_execution
from codex_harness.domain.research_program import ProgramRefused, headroom, select_candidate
from codex_harness.domain.research_program import validate_config as validate_program
from codex_harness.domain.usage_policy import UsagePolicyError, accounting_mode, validate_budget
from tests.test_claude_cli_process import CHILD, SCHEMA, observation
from tests.test_fleet import GOAL, config, manifest
from tests.test_research_program_fixtures import config as program_config

FINITE, SUB = {"per_host": 2, "total": 4}, {"mode": "subscription", "per_host": 2, "total": 4}
BASE = "a" * 40
IMPLEMENT = {"role": "worker:implementation", "action": "implement", "workload": "implementation", "read_only": False}
MODE_SETTING = "ZEUS_CLAUDE_ACCOUNTING_MODE"


def test_policy_keeps_legacy_shape_and_refuses_unknown_modes_or_fields():
    assert validate_budget(FINITE) == FINITE and "mode" not in validate_budget({**FINITE, "mode": "finite"})
    assert validate_budget(SUB) == SUB and accounting_mode(SUB) == "subscription" and accounting_mode(FINITE) == "finite"
    for bad in ({**FINITE, "mode": "unlimited"}, {**FINITE, "mode": 1}, {**SUB, "extra": 1}, {"mode": "subscription"},
                {**SUB, "per_host": 0}, {**SUB, "total": 1}, {**FINITE, "per_host": True}, [], {**FINITE, "mode": None}):
        with pytest.raises(UsagePolicyError):
            validate_budget(bad)
    with pytest.raises(ManifestError):
        validate_manifest({**manifest("op-x", ["docs/x.md"]), "budget": {**FINITE, "mode": "unlimited"}}, packaged_policy())
    with pytest.raises(FleetRefused, match="config_fields"):
        validate_config(config(__import__("pathlib").Path("/tmp"), budget={**SUB, "reset_at": "never"}))


def test_finite_cutoff_unchanged_and_subscription_records_every_call_above_it(tmp_path):
    ledger = CallBudget(root=tmp_path / "ledger")
    for n in range(2):
        ledger.settle(ledger.reserve(per_host=2, total=4, purpose="finite", provider="claude", model="m")["id"], outcome="ok")
    with pytest.raises(ContractError, match="already recorded for this host"):
        ledger.reserve(per_host=2, total=4, purpose="finite", provider="claude", model="m")
    slot = ledger.reserve(per_host=2, total=4, purpose="sub", provider="claude", model="m", mode="subscription")
    assert slot["accounting_mode"] == "subscription" and slot["counts_at_reservation"]["this_host"] == 2
    assert ledger.counts()["this_host"] == 3, "the historical slots are kept and the new one is counted"
    # Slot files are listed by their random id, so the summary order is not reservation order.
    summarized = {row["id"]: row for row in ledger.summary()["slots"]}
    assert summarized[slot["id"]]["accounting_mode"] == "subscription"
    assert sorted(row["accounting_mode"] for row in summarized.values()) == ["finite", "finite", "subscription"]
    with pytest.raises(ContractError, match="Unknown call budget accounting mode"):
        ledger.reserve(per_host=2, total=4, purpose="x", provider="claude", model="m", mode="unlimited")
    assert ledger.counts()["this_host"] == 3, "an unknown mode writes nothing"
    # Injected fault: one damaged slot file. Finite counts it as taken; subscription refuses.
    (ledger.root / "slots" / "damaged.json").write_text("{ not json", encoding="utf-8")
    with pytest.raises(ContractError, match="unreadable"):
        ledger.reserve(per_host=9, total=9, purpose="sub", provider="claude", model="m", mode="subscription")
    assert ledger.reserve(per_host=9, total=9, purpose="finite", provider="claude", model="m")["accounting_mode"] == "finite"


def test_concurrent_subscription_reservations_are_unique_and_all_recorded(tmp_path):
    ledger, taken, errors = CallBudget(root=tmp_path / "ledger"), [], []

    def one():
        try:
            taken.append(ledger.reserve(per_host=1, total=1, purpose="c", provider="claude", model="m", mode="subscription")["id"])
        except Exception as exc:  # pragma: no cover - reported by the assertion
            errors.append(exc)
    threads = [threading.Thread(target=one) for _ in range(6)]
    [t.start() for t in threads], [t.join() for t in threads]
    assert errors == [] and len(set(taken)) == 6 and ledger.counts()["all_hosts"] == 6


class RecordingLedger:
    """LABELLED fake ledger that records the exact reservation call; `readable` False injects a
    ledger read failure as ContractError, the way the real one refuses."""

    def __init__(self, readable=True):
        self.calls, self.readable = [], readable

    def reserve(self, **kwargs):
        self.calls.append(kwargs)
        if not self.readable:
            raise ContractError("ledger unreadable (injected)")
        return {"id": "s" + str(len(self.calls)), "reserved_at": "t"}

    def settle(self, slot_id, *, outcome, detail=None):
        return None


class NoExecutor:
    def execute_one(self, agent, expected=None):
        return {"status": "succeeded"}


def test_budgeted_executor_passes_mode_only_for_subscription_and_refuses_unknown_before_provider():
    finite = RecordingLedger()
    BudgetedExecutor(NoExecutor(), finite, FINITE, "op", "m").execute_one("w")
    assert "mode" not in finite.calls[0] and finite.calls[0]["per_host"] == 2
    sub = RecordingLedger()
    wrapped = BudgetedExecutor(NoExecutor(), sub, SUB, "op", "m")
    wrapped.execute_one("w")
    assert sub.calls[0]["mode"] == "subscription" and wrapped.slots[0]["accounting_mode"] == "subscription"
    with pytest.raises(UsagePolicyError):
        BudgetedExecutor(NoExecutor(), sub, {**SUB, "mode": "unlimited"}, "op", "m")
    with pytest.raises(BudgetRefused, match="budget_exhausted"):
        BudgetedExecutor(NoExecutor(), RecordingLedger(readable=False), SUB, "op", "m").execute_one("w")


def test_fleet_grant_admission_status_and_mismatch(tmp_path):
    f = Fleet(MemoryStore())
    f.register(config(tmp_path, budget=FINITE))
    with pytest.raises(FleetRefused, match="config_invalid"):
        f.authorize_budget(2, 4, 4, mode="unlimited")
    granted = f.authorize_budget(2, 4, 4, mode="subscription")  # unchanged numbers, mode change
    assert granted["budget"] == SUB and granted["prior_mode"] == "finite" and granted["mode"] == "subscription"
    assert f.budget_grants()[0]["mode"] == "subscription" and f.status()["accounting_mode"] == "subscription"
    assert f.registered()["config"]["budget"] == SUB and sanitized_config(f.registered()["config"])["accounting_mode"] == "subscription"
    with pytest.raises(FleetRefused, match="budget_no_increase"):
        f.authorize_budget(2, 4, 4)  # omitted mode keeps subscription: same numbers is no grant
    with pytest.raises(FleetRefused, match="budget_decrease"):
        f.authorize_budget(1, 4, 4, mode="finite")
    with pytest.raises(FleetRefused, match="budget_mismatch"):
        f.enqueue("a", manifest("op-f", ["docs/f.md"], FINITE), GOAL, [])
    f.enqueue("a", manifest("op-s", ["docs/s.md"], SUB), GOAL, [])
    with pytest.raises(FleetRefused, match="fleet_not_idle"):
        f.authorize_budget(2, 4, 4, mode="finite")
    # Launcher admission under subscription: a ledger far above the numbers is not exhausted; an
    # unreadable reading is. The runtime never reserves and no process is spawned here.
    cfg = validate_config(config(tmp_path, budget=SUB))
    above = LaneLauncher(cfg, {}, budget=type("L", (), {"counts": staticmethod(lambda: {"this_host": 50, "all_hosts": 90, "unreadable": 0})})())
    assert above.budget_exhausted(SUB) is False and above.budget_exhausted(FINITE) is True
    damaged = LaneLauncher(cfg, {}, budget=type("L", (), {"counts": staticmethod(lambda: {"this_host": 1, "all_hosts": 1, "unreadable": 1})})())
    assert damaged.budget_exhausted(SUB) is True and damaged.budget_exhausted(FINITE) is False
    assert f.admit_one(budget_exhausted=True)["blocked"] == {"op-s": "budget_exhausted"}
    assert f.admit_one()["job"]["id"] == "op-s" and projection(f.registered(), False, [])["budget"] == SUB
    # A queued finite job under a subscription policy never dispatches (frozen budget stale).
    g = Fleet(MemoryStore())
    g.register(config(tmp_path, budget=FINITE))
    g.enqueue("a", manifest("op-old", ["docs/o.md"], FINITE), GOAL, [])
    with g.store.transaction() as tx:
        tx.put("fleet_control", "admission", {**tx.get("fleet_control", "admission"), "budget": SUB})  # injected race
    assert g.admit_one()["blocked"] == {"op-old": "budget_stale"}


def test_program_headroom_and_template_round_trip_keep_fixed_caps():
    assert headroom(SUB, {"this_host": 500, "all_hosts": 900, "unreadable": 0}) == {"remaining": None, "ok": True, "required": 7}
    assert headroom(SUB, {"this_host": 1, "all_hosts": 1, "unreadable": 2}) == {"remaining": None, "ok": False, "required": 7}
    assert headroom(SUB, {"unreadable": "OSError"}) == {"remaining": None, "ok": False, "required": 7}
    assert headroom(FINITE, {"this_host": 2, "all_hosts": 2, "unreadable": 0}) == {"remaining": 0, "ok": False, "required": 7}
    eligible = [{"id": "c", "source": "github", "topic": "t", "status": "eligible", "url": "https://x"}]
    room = headroom(SUB, {"this_host": 500, "all_hosts": 900, "unreadable": 0})
    assert select_candidate(eligible, 1, 1, room) == {"candidate": None, "reason": "adoption_cap_reached"}, "caps survive"
    head = BASE
    sub_budget = {"mode": "subscription", "per_host": 10, "total": 20}
    document = program_config(head, budget=sub_budget)
    document["template"] = {**document["template"], "budget": sub_budget}
    canonical = validate_program(document, packaged_policy())
    assert canonical["budget"] == sub_budget and canonical["template"]["budget"] == sub_budget
    assert validate_program(canonical, packaged_policy()) == canonical, "canonical form round-trips"
    with pytest.raises(ProgramRefused, match="template_budget_mismatch"):
        validate_program(program_config(head, budget=sub_budget), packaged_policy())
    with pytest.raises(ProgramRefused, match="config_invalid"):
        validate_program(program_config(head, budget={**sub_budget, "mode": "unlimited"}), packaged_policy())


# ---- batch008 provider-control correction: the mode reaches the command and the receipt -----------

def chosen(budget):
    """provider_settings -> policy configuration -> selection, exactly as `zeus operate run` binds it."""
    policy = packaged_policy()
    settings = provider_settings(manifest("op-" + accounting_mode(budget), ["docs/x.md"], budget))
    return select_execution(policy, parse_configuration(policy, settings), **IMPLEMENT)


def fixture_runtime(assignment, **extra):
    """Exactly Executor._open_runtime's host construction, plus the labelled protocol child."""
    return ClaudeCodeRuntime(model="claude-stub-normal", runtime=assignment.runtime, executable=str(CHILD),
                             launcher=[sys.executable], max_budget_usd=assignment.controls.get("max_budget_usd"),
                             settings_document=claude_settings(assignment.runtime), **extra)


def test_provider_settings_bind_the_mode_and_finite_configuration_stays_byte_identical():
    policy = packaged_policy()
    finite_settings = provider_settings(manifest("op-f", ["docs/f.md"], FINITE))
    sub_settings = provider_settings(manifest("op-s", ["docs/s.md"], SUB))
    assert finite_settings[MODE_SETTING] == "finite" and sub_settings[MODE_SETTING] == "subscription"
    legacy = {k: v for k, v in finite_settings.items() if k != MODE_SETTING}
    finite_cfg = parse_configuration(policy, finite_settings)
    assert finite_cfg == parse_configuration(policy, legacy), "explicit finite is the unchanged legacy configuration"
    assert "accounting_mode" not in finite_cfg.enabled["claude"]
    assert finite_cfg.enabled["claude"]["controls"]["max_budget_usd"] == 1.0
    sub_cfg = parse_configuration(policy, sub_settings)
    assert sub_cfg.enabled["claude"]["accounting_mode"] == "subscription"
    assert "max_budget_usd" not in sub_cfg.enabled["claude"]["controls"]
    assert sub_cfg.enabled["claude"]["controls"]["timeout_seconds"] == 120, "other controls are untouched"
    assert sub_cfg.config_digest != finite_cfg.config_digest, "the mode is bound into the configuration digest"
    with pytest.raises(ContractError, match=MODE_SETTING):
        parse_configuration(policy, {**legacy, MODE_SETTING: "unlimited"})
    with pytest.raises((ContractError, ValueError)):
        parse_configuration(policy, {**sub_settings, "ZEUS_CLAUDE_MAX_BUDGET_USD": "500"})  # retained, still validated
    without_cap = {k: v for k, v in sub_settings.items() if k != "ZEUS_CLAUDE_MAX_BUDGET_USD"}
    assert "max_budget_usd" not in parse_configuration(policy, without_cap).enabled["claude"]["controls"]
    with pytest.raises(ContractError, match="ZEUS_CLAUDE_MAX_BUDGET_USD"):
        parse_configuration(policy, {**without_cap, MODE_SETTING: "finite"})  # finite still requires the cap
    assert parse_configuration(policy, {MODE_SETTING: "unlimited"}).enabled == {}, "nothing enabled: nothing read"
    canonical = validate_manifest({**manifest("op-s", ["docs/s.md"], SUB)}, policy)
    assert canonical["budget"] == SUB and canonical["claude"]["max_budget_usd"] == 1.0, "manifest keeps the number"


def test_selection_binds_subscription_into_runtime_receipt_and_invocation_options():
    sub, finite = chosen(SUB), chosen(FINITE)
    packaged = packaged_policy().provider("claude").runtime
    assert sub.provider == "claude" and sub.accounting_mode == "subscription"
    assert sub.runtime["accounting_mode"] == "subscription" and "max_budget_usd" not in sub.controls
    assert {k: v for k, v in sub.runtime.items() if k != "accounting_mode"} == packaged
    assert sub.receipt()["accounting_mode"] == "subscription" and "max_budget_usd" not in sub.receipt()["controls"]
    assert finite.accounting_mode == "finite" and finite.runtime == packaged, "finite runtime is byte-identical"
    assert finite.receipt()["controls"]["max_budget_usd"] == 1.0 and finite.receipt()["accounting_mode"] == "finite"
    policy = packaged_policy()
    codex = select_execution(policy, parse_configuration(policy, {}), role="lead:improvement", action="plan",
                             workload="design", read_only=False)
    assert codex.accounting_mode == "finite" and codex.receipt()["controls"] == {}
    # Executor request options: the dollar cap is present only when the assignment carries it, never null.
    expected = {id(sub): ["permission_mode"], id(finite): ["max_budget_usd", "permission_mode"]}
    for assignment in (sub, finite):
        options = invocation_options(assignment, model="claude-fixture-model", timeout=30, schema=SCHEMA, read_only=False)
        request = parse_request("claude_cli", options)
        assert request["effect_left_to_provider"] == expected[id(assignment)]
        assert ("max_budget_usd" in request["options"]) is (assignment is finite)
    # The shape the previous executor built for a subscription assignment (a null cap) is refused by the
    # matrix before any provider: this is the observed batch008 obstacle's request-side form.
    with pytest.raises(ContractError, match="max_budget_usd"):
        parse_request("claude_cli", {**invocation_options(sub, model="m", timeout=30, schema=SCHEMA, read_only=False),
                                     "max_budget_usd": None})
    assert invocation_options(codex, model="m", timeout=30, schema=SCHEMA, read_only=True) == {
        "model": "m", "timeout": 30, "output_schema": SCHEMA, "read_only": True}


def test_runtime_omits_the_dollar_flag_only_under_explicit_subscription(tmp_path):
    sub = fixture_runtime(chosen(SUB))
    assert "--max-budget-usd" not in sub._planned_flags(), "preflight never requires an option it will not pass"
    with sub as opened:
        argv, shown = opened._command(schema=SCHEMA, session_id="00000000-0000-4000-8000-000000000003")
        assert "--max-budget-usd" not in argv and "--max-budget-usd" not in shown and "--json-schema" in argv
        workspace = tmp_path / "sub"
        workspace.mkdir()
        result = opened.run("fixture prompt", str(workspace), SCHEMA, timeout=60)
    assert result["command"]["max_budget_usd"] is None and result["command"]["accounting_mode"] == "subscription"
    assert "--max-budget-usd" not in result["command"]["argv"] and result["command"]["launcher"] == [sys.executable]
    assert observation(workspace)["max_budget_usd"] is None and "--max-budget-usd" not in observation(workspace)["argv"]
    finite = fixture_runtime(chosen(FINITE))
    assert "--max-budget-usd" in finite._planned_flags()
    with finite as opened:
        workspace = tmp_path / "finite"
        workspace.mkdir()
        result = opened.run("fixture prompt", str(workspace), SCHEMA, timeout=60)
    assert result["command"]["max_budget_usd"] == 1.0 and result["command"]["accounting_mode"] == "finite"
    assert observation(workspace)["max_budget_usd"] == "1.00", "finite forwards the ceiling exactly as before"
    # Refusals at construction: before any probe or process.
    for bad in ("unlimited", None, 1):
        with pytest.raises(ContractError, match="accounting_mode"):
            ClaudeCodeRuntime(model="m", runtime={"accounting_mode": bad}, executable=str(CHILD), launcher=[sys.executable])
    with pytest.raises(ContractError, match="forwards no spend ceiling"):
        ClaudeCodeRuntime(model="m", runtime={"accounting_mode": "subscription"}, max_budget_usd=1.0,
                          executable=str(CHILD), launcher=[sys.executable])
    legacy = ClaudeCodeRuntime(model="m", runtime={}, executable=str(CHILD), launcher=[sys.executable])
    assert legacy.accounting_mode == "finite"
    with pytest.raises(ContractError, match="spend ceiling"):
        legacy._command(schema=SCHEMA, session_id="00000000-0000-4000-8000-000000000004")


def test_executor_opens_the_host_runtime_with_the_selected_mode_and_no_null_cap(tmp_path, monkeypatch):
    from codex_harness.adapters.artifacts import FileArtifacts
    from codex_harness.adapters.executor import Executor
    from codex_harness.application.service import Harness
    from codex_harness.bootstrap import organization

    built = []
    monkeypatch.setattr("codex_harness.adapters.executor.ClaudeCodeRuntime", lambda **kwargs: built.append(kwargs))
    executor = Executor(Harness(MemoryStore(), organization()), SimpleNamespace(_git=lambda *a, **k: "r"),
                        FileArtifacts(str(tmp_path / "a")))
    executor._open_runtime(chosen(SUB), "claude-fixture-model", str(tmp_path), "implement")
    executor._open_runtime(chosen(FINITE), "claude-fixture-model", str(tmp_path), "implement")
    assert built[0]["runtime"]["accounting_mode"] == "subscription" and built[0]["max_budget_usd"] is None
    assert "accounting_mode" not in built[1]["runtime"] and built[1]["max_budget_usd"] == 1.0
    assert set(built[0]) == set(built[1]) == {"model", "runtime", "executable", "max_budget_usd", "settings_document"}


def test_isolated_runtime_dict_and_entry_carry_the_mode_and_omit_the_cap(tmp_path):
    """The isolated request already serializes `runtime` (isolated_worker.py) and the in-image entry hands it
    to ClaudeCodeRuntime unchanged (isolated_worker_entry.py): neither file changes. No container runs here;
    the entry is served in-process with the real runtime over the labelled fixture child."""
    assignment = chosen(SUB)
    config = {"mode": iw.MODE, "image": "sha256:" + "a" * 64}
    isolated = iw.IsolatedWorker(config, tmp_path).runtime(model="claude-stub-normal", runtime=assignment.runtime,
                                                           max_budget_usd=assignment.controls.get("max_budget_usd"),
                                                           settings_document=claude_settings(assignment.runtime))
    assert isolated.runtime["accounting_mode"] == "subscription" and isolated.max_budget_usd is None
    workspace = tmp_path / "ws"
    workspace.mkdir()
    # The request fields are the ones IsolatedClaudeRuntime.run serializes, valued from this runtime object.
    request = {"protocol": iw.PROTOCOL, "prompt": "fixture prompt", "schema": SCHEMA, "timeout": 60,
               "model": isolated.model, "session_id": "00000000-0000-4000-8000-000000000005",
               "runtime": isolated.runtime, "max_budget_usd": isolated.max_budget_usd,
               "settings_document": isolated.settings_document, "cwd": str(workspace), "evidence_root": str(tmp_path / "ev")}

    def factory(**kwargs):
        return ClaudeCodeRuntime(executable=str(CHILD), launcher=[sys.executable], **kwargs)
    output = io.BytesIO()
    assert entry.serve(io.BytesIO(json.dumps(request).encode("utf-8")), output, factory) == 0
    lines = [json.loads(line) for line in output.getvalue().splitlines()]
    assert lines[-1]["kind"] == "result"
    command = lines[-1]["result"]["command"]
    assert command["accounting_mode"] == "subscription" and command["max_budget_usd"] is None
    assert "--max-budget-usd" not in command["argv"] and observation(workspace)["max_budget_usd"] is None
    refused = io.BytesIO()
    bad = {**request, "runtime": {**isolated.runtime, "accounting_mode": "unlimited"}}
    assert entry.serve(io.BytesIO(json.dumps(bad).encode("utf-8")), refused, factory) == 1
    first = json.loads(refused.getvalue().splitlines()[0])
    assert first["kind"] == "refused" and "accounting_mode" in first["message"]
    assert (workspace / "stub-runs.log").read_text("utf-8").count("\n") == 1, "the refused request never spawned"
