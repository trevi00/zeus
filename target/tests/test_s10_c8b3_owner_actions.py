"""S10 C8b-3: the `owner-actions` root and `composition.owner_actions` (R-c32, E-c21).

MemoryStore, monkeypatched settings and builders; no provider, process, Docker, GitHub, Git or PostgreSQL is touched. Parity with M7 on a
disposable PostgreSQL is the `entry.cli_owner_actions.pg` compare family (the refusal and status paths; a registered policy needs a Git history
whose pin the family cannot seed without a mask, so the positive register/tick paths are covered here and by the ported suites)."""
from __future__ import annotations

import ast
import json
import signal
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from codex_harness import composition
from codex_harness.composition import configuration
from codex_harness.composition import owner_actions as wiring
from codex_harness.coordination.application.owner_actions.canary import CanaryFamily
from codex_harness.coordination.application.owner_actions.migration import MigrationRequestFamily
from codex_harness.coordination.application.owner_actions.scheduler import OwnerActionScheduler
from codex_harness.coordination.domain.owner_actions import OwnerActionRefused
from codex_harness.delivery.adapters import deployment
from codex_harness.entry import cli as entry
from codex_harness.entry.cli import owner_actions as root
from codex_harness.kernel.errors import ContractError
from codex_harness.kernel.ids import SYSTEM_CLOCK, SYSTEM_IDS, utcnow
from codex_harness.routing.adapters.organization_source import packaged_organization
from codex_harness.storage.adapters.memory_store import MemoryStore

TESTS = Path(__file__).resolve().parent
PORTED = TESTS / "ported"
CONTROL_DSN = "postgresql://fixture@fixture-host/control"  # a label: nothing connects to it
CANDIDATE = "a" * 40


@pytest.fixture
def settings(monkeypatch, tmp_path):
    values = {"HARNESS_RUNTIME_DIR": str(tmp_path / "runtime"), "HARNESS_DATABASE_URL": CONTROL_DSN}
    monkeypatch.setattr(configuration, "settings", lambda: values)
    monkeypatch.setattr(configuration, "repository_root", lambda: tmp_path)
    monkeypatch.setattr(configuration, "runtime_dir", lambda: tmp_path / "runtime")
    return values


@pytest.fixture
def service(settings):
    return composition.ServiceHandle(MemoryStore(), packaged_organization())


@pytest.fixture
def shim(monkeypatch):
    monkeypatch.syspath_prepend(str(PORTED))
    import m7_coordination
    return m7_coordination


def literal(path: Path, name: str):
    """The module-level assignment `name` of `path` as a literal (the shim imports a conftest name, so it is read, not imported)."""
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError(name)


def args(command, **fields):
    return SimpleNamespace(owner_actions_command=command, **fields)


def fleet_config():
    return {"lanes": [{"id": "a", "repository": "labelled-repo", "runtime": "labelled-runtime", "schema": "lane_a"}],
            "budget": {"per_host": 2, "total": 4}}


# ----- owner_action_owners builds the split as the shim does ------------------------------------------------------------------------
def test_the_owners_are_the_split_objects_of_the_shim_in_its_construction_order(shim):
    owners = wiring.owner_action_owners(MemoryStore())
    held = shim.OwnerActions(MemoryStore()).holders
    keys = ("actions", "research_acceptance", "delivery_plan", "canary", "migration", "requalify_family",
            "research_dispatch", "scheduler")
    assert [type(getattr(owners, key)).__name__ for key in keys] == [type(holder).__name__ for holder in held]
    assert isinstance(owners.scheduler, OwnerActionScheduler) and isinstance(owners.canary, CanaryFamily)


def test_the_owners_use_the_system_clock_and_ids_and_share_the_store_and_ports():
    store, ports = MemoryStore(), {"assessments": object(), "targets": object(), "publisher": object(),
                                   "deliveries": lambda lane: None, "lanes": lambda lane: None}
    owners = wiring.owner_action_owners(store, org="org", **ports)
    assert owners.actions.clock is utcnow and owners.scheduler.clock is utcnow and owners.canary.clock is utcnow
    assert owners.research_acceptance.message_clock is SYSTEM_CLOCK and owners.research_acceptance.ids is SYSTEM_IDS
    assert owners.store is store and owners.scheduler.store is store
    assert owners.assessments is owners.research_acceptance.assessments is ports["assessments"]
    assert owners.delivery_plan.publisher is owners.migration.publisher is ports["publisher"]
    assert owners.canary.targets is owners.migration.targets is ports["targets"]
    assert owners.migration.delivery_plan is owners.delivery_plan and owners.canary.actions is owners.actions
    clocked = wiring.owner_action_owners(store, clock=lambda: "fixed")
    assert clocked.scheduler.clock() == "fixed" and clocked.actions.clock() == "fixed"


# ----- the M7 method -> split owner table (docstring) -------------------------------------------------------------------------------
def test_each_tabled_method_is_held_by_the_routed_owner(shim):
    routes = shim.OWNER_ROUTES
    called = {"status": "scheduler", "register": "scheduler", "tick": "scheduler", "request_migration": "migration",
              "recover_canary": "canary"}
    classes = {"scheduler": OwnerActionScheduler, "migration": MigrationRequestFamily, "canary": CanaryFamily}
    owners = wiring.owner_action_owners(MemoryStore())
    for method, owner in called.items():
        assert routes[method] == owner
        assert callable(getattr(classes[owner], method))
        assert isinstance(getattr(owners, owner), classes[owner])
    table = wiring.__doc__
    for text in ("status (entry `status`)", "register (register_policy)", "tick (tick_policy)",
                 "request_migration (entry `migrate`)", "recover_canary (entry `canary-recover`)",
                 "scheduler.OwnerActionScheduler", "migration.MigrationRequestFamily", "canary.CanaryFamily"):
        assert text in table


def test_the_entry_and_the_composition_call_only_tabled_owners():
    allowed = {"scheduler", "migration", "canary", "assessments", "store"}
    for path, name in ((Path(root.__file__), "_execute"), (Path(wiring.__file__), "tick_policy")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        function = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == name)
        used = {node.attr for node in ast.walk(function) if isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name) and node.value.id == "owner"}
        assert used <= allowed


def test_the_delivery_and_continuation_ports_route_the_public_names():
    from codex_harness.delivery.application.host_delivery.migration import DeliveryMigration
    from codex_harness.delivery.application.host_delivery.registry import DeliveryRegistry
    from codex_harness.delivery.application.host_delivery.withdrawal import Withdrawal

    store = MemoryStore()
    delivery = wiring.delivery_port(store, packaged_organization())
    assert delivery.store is store
    assert isinstance(delivery.registry, DeliveryRegistry) and isinstance(delivery.migration, DeliveryMigration)
    assert isinstance(delivery.withdrawal, Withdrawal)
    delivery_routes = literal(PORTED / "m7_delivery.py", "ROUTES")
    for name, owner in (("register", "registry"), ("register_migration_plan", "migration"),
                        ("stage_migration", "migration"), ("finalize_migration", "migration"),
                        ("require_controller_code", "migration"), ("withdraw", "withdrawal")):
        assert getattr(delivery, name) == getattr(getattr(delivery, owner), name)
        if name != "withdraw":
            assert delivery_routes[name] == owner
    assert delivery_routes["withdraw"] == "withdrawal"
    continuation = wiring.continuation_port(store)
    for name, owner in (("policy", "frames"), ("research_facts", "research"), ("accept_research", "research")):
        assert getattr(continuation, name) == getattr(getattr(continuation, owner), name)
        assert literal(PORTED / "m7_coordination.py", "CONTINUATION_ROUTES")[name] == owner


# ----- policy_list, tick_policies, run_loop -----------------------------------------------------------------------------------------
def test_policy_list_parses_as_m7():
    assert wiring.policy_list(("a", "b")) == ["a", "b"] and wiring.policy_list(["only"]) == ["only"]
    for bad in ([], (), None, ["a", "a"]):
        with pytest.raises(OwnerActionRefused) as refused:
            wiring.policy_list(bad)
        assert refused.value.reason_code == "policy_list_invalid"


def test_tick_policies_gives_one_refusal_a_receipt_and_never_stops_the_others(monkeypatch):
    def tick(owner, config, policy_id, source_factory=None):
        if policy_id == "broken":
            raise OSError("store read failed (labelled injected fault)")
        return {"outcome": "progressed" if policy_id == "busy" else "idle", "policy_id": policy_id}
    monkeypatch.setattr(wiring, "tick_policy", tick)
    result = wiring.tick_policies(SimpleNamespace(), {}, ["broken", "busy", "quiet"])
    assert result["outcome"] == "progressed" and result["schema"] == "urn:zeus:owner-actions-ticks:1"
    assert [r["outcome"] for r in result["policies"]] == ["refused", "progressed", "idle"]
    assert result["policies"][0]["error_type"] == "OSError" and result["policies"][0]["reason_code"] == "tick_failed"
    only_idle = wiring.tick_policies(SimpleNamespace(), {}, ["quiet"])
    assert only_idle["outcome"] == "idle"


def test_run_loop_counts_the_outcomes_and_restores_the_signal_handlers():
    before = (signal.getsignal(signal.SIGINT), signal.getsignal(signal.SIGTERM))
    outcomes, sleeps = iter(["idle", "progressed", "idle"]), []
    summary = wiring.run_loop(lambda: {"outcome": next(outcomes)}, interval=0, max_ticks=3, sleep=sleeps.append)
    assert summary == {"schema": "urn:zeus:owner-actions-run:1", "ticks": 3,
                       "outcomes": {"idle": 2, "progressed": 1}, "stopped": False}
    assert sleeps == [1, 1] and (signal.getsignal(signal.SIGINT), signal.getsignal(signal.SIGTERM)) == before


def test_run_loop_stops_on_a_signal_after_the_tick_in_flight_and_restores_the_handlers():
    before = (signal.getsignal(signal.SIGINT), signal.getsignal(signal.SIGTERM))

    def tick():
        signal.raise_signal(signal.SIGTERM)  # the loop's own handler, not the process's
        return {"outcome": "idle"}

    summary = wiring.run_loop(tick, interval=1, max_ticks=5, sleep=lambda _s: None)
    assert summary["stopped"] is True and summary["ticks"] == 1
    assert (signal.getsignal(signal.SIGINT), signal.getsignal(signal.SIGTERM)) == before


# ----- the policy read and registration --------------------------------------------------------------------------------------------
POLICY_BYTES = b'{"not": "a policy"}'


def test_load_policy_reads_the_pinned_blob_and_refuses_as_m7_did(monkeypatch):
    from codex_harness.intake.adapters import backlog_blobs
    from codex_harness.intake.domain.backlog import BacklogRefused

    seen = []
    monkeypatch.setattr(backlog_blobs, "read_blob", lambda source, revision, path, limit, name: seen.append(
        (source, revision, path, limit, name)) or POLICY_BYTES)
    with pytest.raises(ContractError):  # the document is parsed, then validated by the owner's own validator
        wiring.load_policy("source", CANDIDATE, "policy.json")
    assert seen == [("source", CANDIDATE, "policy.json", 64 * 1024, "policy")]

    def missing(*_):
        raise BacklogRefused("policy_revision_missing", "policy")
    monkeypatch.setattr(backlog_blobs, "read_blob", missing)
    with pytest.raises(OwnerActionRefused) as refused:
        wiring.load_policy("source", CANDIDATE, "policy.json")
    assert refused.value.reason_code == "policy_revision_missing"
    monkeypatch.setattr(backlog_blobs, "read_blob", lambda *_: b"{not json")
    with pytest.raises(OwnerActionRefused) as refused:
        wiring.load_policy("source", CANDIDATE, "policy.json")
    assert refused.value.reason_code == "policy_not_json"


def test_register_policy_reads_through_the_lanes_repository_and_registers_on_the_scheduler(monkeypatch):
    sources, registered = [], []
    monkeypatch.setattr(wiring, "load_policy", lambda source, revision, path: {
        "policy": {"id": "p"}, "pin": {"revision": revision, "path": path, "sha256": "s"}})
    monkeypatch.setattr(OwnerActionScheduler, "register", lambda self, policy, pin: registered.append((policy, pin)) or {"ok": 1})
    receipt = wiring.register_policy(MemoryStore(), fleet_config(), "a", CANDIDATE, "policy.json",
                                     source_factory=lambda repository: sources.append(repository) or repository)
    assert receipt == {"ok": 1} and sources == ["labelled-repo"]
    assert registered == [({"id": "p"}, {"revision": CANDIDATE, "path": "policy.json", "sha256": "s", "lane": "a"})]
    with pytest.raises(Exception) as unknown:
        wiring.register_policy(MemoryStore(), fleet_config(), "nope", CANDIDATE, "policy.json")
    assert unknown.value.reason_code == "lane_unknown"


def test_tick_policy_of_an_unregistered_policy_is_one_idle_tick_with_no_git_read(monkeypatch):
    owners = wiring.owner_action_owners(MemoryStore())
    monkeypatch.setattr(wiring, "load_policy", lambda *_: pytest.fail("no Git read for an unregistered policy"))
    receipt = wiring.tick_policy(owners, fleet_config(), "nope")
    assert receipt["outcome"] == "unregistered" and receipt["actions"] == []


def test_tick_policy_of_a_registered_policy_rereads_the_pin_and_refuses_before_any_effect(monkeypatch):
    store = MemoryStore()
    with store.transaction() as tx:
        tx.put("owner_action_policies", "p", {"policy": {"enabled": True},
                                              "pin": {"lane": "a", "revision": CANDIDATE, "path": "policy.json"}})
    owners = wiring.owner_action_owners(store)
    ticks = []
    monkeypatch.setattr(OwnerActionScheduler, "tick", lambda self, policy_id, pin_sha256=None: ticks.append(
        (policy_id, pin_sha256)) or {"outcome": "idle"})
    monkeypatch.setattr(wiring, "load_policy", lambda source, revision, path: {"pin": {"sha256": "sha"}})
    assert wiring.tick_policy(owners, fleet_config(), "p", source_factory=lambda repository: repository) == {"outcome": "idle"}
    assert ticks == [("p", "sha")]

    def unreadable(*_):
        raise OSError("labelled")
    monkeypatch.setattr(wiring, "load_policy", unreadable)
    refused = wiring.tick_policy(owners, fleet_config(), "p")
    assert (refused["outcome"], refused["reason_code"], refused["error_type"]) == ("refused", "policy_unavailable", "OSError")
    assert ticks == [("p", "sha")]


# ----- the independent assessment: ceilings and an absent profile --------------------------------------------------------------------
def test_the_assessment_ceilings_are_the_fleets_effective_budget_or_a_named_refusal(service):
    with pytest.raises(OwnerActionRefused) as unregistered:
        wiring.assessment_ceilings(service.store)
    assert unregistered.value.reason_code == "assessment_budget_unregistered"


def test_an_absent_composition_profile_refuses_in_assess_before_any_reservation(service, monkeypatch):
    monkeypatch.delenv("ZEUS_COMPOSITION_PROFILE", raising=False)
    from codex_harness.composition import observation

    monkeypatch.setattr(observation, "build_observer", lambda store, component: None)
    with pytest.raises(ContractError) as refused:
        wiring.assess(service, "d-x", "c-x", "label", ceilings={"per_host": 1, "total": 1})
    assert str(refused.value) == "composition_profile_unknown"
    assert root._refusal(refused.value) == {"status": "refused", "reason_code": "contract_refused",
                                            "error_type": "ContractError", "exit_code": 1}


# ----- the coordinator wiring ----------------------------------------------------------------------------------------------------------
def test_the_coordinator_wires_the_real_ports_and_the_trusted_controller_port(service, monkeypatch):
    from codex_harness.delivery.adapters import host_delivery
    from codex_harness.delivery.adapters.target_files import TargetFiles

    seen = []
    monkeypatch.setattr(host_delivery, "first_activation_facts",
                        lambda lane, host, revision, **ports: seen.append((lane, host, revision, sorted(ports))) or {"f": 1})
    config, host = fleet_config(), {"labelled": "host"}
    lane = SimpleNamespace(store=MemoryStore())
    owner = wiring.coordinator(service, config, host, lanes=lambda lane_id: lane, assessments=object(),
                               continuation=object())
    assert owner.store is service.store and isinstance(owner.canary.targets, TargetFiles)
    assert owner.delivery_plan.first_activation("a", CANDIDATE) == {"f": 1}
    assert seen == [(config["lanes"][0], host, CANDIDATE, ["profiles", "run", "source"])]
    delivery = owner.canary.deliveries("a")
    assert delivery.store is lane.store and delivery.migration.controller_code is deployment.controller_code_revision
    assert callable(delivery.migration.evaluator_pins)
    withdrawing = owner.requalify_family.withdrawals("a")
    assert withdrawing.store is lane.store and withdrawing.withdraw == withdrawing.withdrawal.withdraw
    assert withdrawing.withdrawal.github is not None
    assert owner.requalify_family.mainline.config is config and callable(owner.requalify_family.requalify)
    assert callable(owner.research_dispatch.ledger)
    assert owner.canary.fleet.enqueue and owner.canary.validate is not None


def test_the_coordinator_builds_the_guarded_launches_with_the_spawn_and_the_provider_probe(service, tmp_path):
    from codex_harness.coordination.adapters.owner_launches import Assessments, ResearchLaunches

    config = fleet_config()
    owner = wiring.coordinator(service, config, {}, lanes=lambda lane_id: None, continuation=object())
    assert isinstance(owner.assessments, Assessments) and owner.assessments.spawn is not None
    assert owner.assessments.root == tmp_path / "runtime" / "owner-actions"
    research = owner.research_dispatch.research
    assert isinstance(research, ResearchLaunches) and research.spawn is owner.assessments.spawn is not None
    assert research.root == tmp_path / "runtime" / "owner-actions" / "research"
    assert research.repository("a") == "labelled-repo" and research.resolve is wiring._resolve_provider
    assert callable(research.run)


def test_resolve_provider_names_codex_and_node(monkeypatch):
    from codex_harness.execution.adapters.providers import codex_app_server

    monkeypatch.setattr(codex_app_server, "resolve_codex", lambda: "codex-path")
    monkeypatch.setattr(wiring.shutil, "which", lambda name: "node-path" if name == "node" else None)
    assert wiring._resolve_provider() == {"codex": "codex-path", "node": "node-path"}


# ----- the entry bodies ------------------------------------------------------------------------------------------------------------------
def test_status_reads_the_projection_with_nothing_registered(service):
    receipt = root._execute(service, args("status", policy=None))
    assert receipt["exit_code"] == 0 and receipt["actions"] == []
    assert root._execute(service, args("status", policy="nope"))["exit_code"] == 0


def test_assess_of_a_row_that_is_no_owner_assessment_is_refused(service):
    with pytest.raises(OwnerActionRefused) as foreign:
        root._execute(service, args("assess", decision="d-x", correlation="c-x"))
    assert foreign.value.reason_code == "assessment_row_foreign"
    assert root._refusal(foreign.value) == {"status": "refused", "reason_code": "assessment_row_foreign",
                                            "error_type": "OwnerActionRefused", "exit_code": 1}


def test_every_command_after_status_and_assess_needs_the_registered_fleet(service):
    for command, fields in (("register", {"lane": "a", "revision": CANDIDATE, "path": "p.json"}),
                            ("tick", {"policy": "p"}), ("run", {"policy": ["p"], "interval": 1, "max_ticks": 1}),
                            ("migrate", {"document": "d.json"}), ("canary-recover", {"document": "d", "evidence": "e"})):
        with pytest.raises(Exception) as refused:
            root._execute(service, args(command, **fields))
        assert refused.value.reason_code == "unregistered"


def test_migrate_and_canary_recover_read_their_document_and_call_the_routed_owner(service, monkeypatch, tmp_path):
    owner = SimpleNamespace(
        migration=SimpleNamespace(request_migration=lambda document: {"migration": document}),
        canary=SimpleNamespace(recover_canary=lambda document, evidence: {"recovered": document, "evidence": evidence}),
        assessments=SimpleNamespace(join=lambda: None))
    monkeypatch.setattr(wiring, "coordinator", lambda service, config, host: owner)
    from codex_harness.coordination.application.fleet.registry import FleetRegistry

    monkeypatch.setattr(FleetRegistry, "registered", lambda self: {"config": fleet_config()})
    good, bad = tmp_path / "good.json", tmp_path / "bad.json"
    good.write_text('{"k": 1}', encoding="utf-8")
    bad.write_text("{", encoding="utf-8")
    assert root._execute(service, args("migrate", document=str(good))) == {"migration": {"k": 1}, "exit_code": 0}
    assert root._execute(service, args("canary-recover", document=str(good), evidence="sha256:x")) == {
        "recovered": {"k": 1}, "evidence": "sha256:x", "exit_code": 0}
    for command, code, extra in (("migrate", "migration_document_unreadable", {}),
                                 ("canary-recover", "canary_recovery_document_unreadable", {"evidence": "e"})):
        for path in (bad, tmp_path / "absent.json"):
            with pytest.raises(OwnerActionRefused) as refused:
                root._execute(service, args(command, document=str(path), **extra))
            assert refused.value.reason_code == code


def test_tick_joins_the_assessments_and_exits_one_on_a_refusal(service, monkeypatch):
    joined = []
    owner = SimpleNamespace(assessments=SimpleNamespace(join=lambda: joined.append(1)))
    monkeypatch.setattr(wiring, "coordinator", lambda service, config, host, observer=None: owner)  # S10 F2
    monkeypatch.setattr(wiring, "process_observer", lambda store: None)  # S10 F2
    from codex_harness.coordination.application.fleet.registry import FleetRegistry

    monkeypatch.setattr(FleetRegistry, "registered", lambda self: {"config": fleet_config()})
    outcomes = iter(["idle", "refused"])
    monkeypatch.setattr(wiring, "tick_policy", lambda owner, config, policy_id: {"outcome": next(outcomes)})
    assert root._execute(service, args("tick", policy="p")) == {"outcome": "idle", "exit_code": 0}
    assert root._execute(service, args("tick", policy="p")) == {"outcome": "refused", "exit_code": 1}
    assert joined == [1, 1]


def test_run_ticks_every_named_policy_through_the_loop(service, monkeypatch):
    owner = SimpleNamespace()
    monkeypatch.setattr(wiring, "coordinator", lambda service, config, host, observer=None: owner)  # S10 F2
    monkeypatch.setattr(wiring, "process_observer", lambda store: None)  # S10 F2
    from codex_harness.coordination.application.fleet.registry import FleetRegistry

    monkeypatch.setattr(FleetRegistry, "registered", lambda self: {"config": fleet_config()})
    monkeypatch.setattr(wiring, "tick_policies", lambda owner, config, policies: {"outcome": "idle", "policies": policies})
    summary = root._execute(service, args("run", policy=["p", "q"], interval=3, max_ticks=2))
    assert summary["ticks"] == 2 and summary["outcomes"] == {"idle": 2} and summary["policies"] == ["p", "q"]
    assert summary["schema"] == "urn:zeus:owner-actions-run:1" and summary["exit_code"] == 0
    with pytest.raises(OwnerActionRefused) as repeated:
        root._execute(service, args("run", policy=["p", "p"], interval=3, max_ticks=2))
    assert repeated.value.reason_code == "policy_list_invalid"


def test_run_prints_the_refusal_and_exits_one(service, monkeypatch, capsys):
    monkeypatch.setattr(composition, "build", lambda: service)
    with pytest.raises(SystemExit) as stopped:
        root.run(args("assess", decision="d-x", correlation="c-x"))
    assert stopped.value.code == 1
    assert json.loads(capsys.readouterr().out)["reason_code"] == "assessment_row_foreign"
    root.run(args("status", policy=None))
    assert json.loads(capsys.readouterr().out)["exit_code"] == 0


# ----- dispatch ---------------------------------------------------------------------------------------------------------------------------
def test_the_dispatch_table_composes_the_owner_actions_root(monkeypatch):
    tree = ast.parse(Path(entry.__file__).resolve().read_text(encoding="utf-8"))
    tables = [node for node in ast.walk(tree) if isinstance(node, ast.Assign)
              and any(isinstance(t, ast.Name) and t.id == "composed" for t in node.targets)]
    assert "owner-actions" in [key.value for key in tables[0].value.keys]
    called = []
    monkeypatch.setattr(root, "run", lambda parsed: called.append((parsed.command, parsed.owner_actions_command)))
    monkeypatch.setattr(sys, "argv", ["zeus", "owner-actions", "status"])
    entry.main()
    assert called == [("owner-actions", "status")]
