"""S10 C8b-1: the `continuation` root, `composition.continuation`, `composition.cli_continuation` and `coordination.adapters.continuation` (R-c27, E-c21).

MemoryStore, monkeypatched settings and builders, a tmp `FileArtifacts`; no provider, process, Git or PostgreSQL is touched. Parity with M7 on a
disposable PostgreSQL is the `entry.cli_continuation.pg` compare family; the receipt, grant and requalification paths are the ported suites'."""
from __future__ import annotations

import ast
import hashlib
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from codex_harness import composition
from codex_harness.composition import (
    cli_continuation,
    cli_operation,
    configuration,
    observation,
)
from codex_harness.composition import continuation as wiring
from codex_harness.composition import fleet as composition_fleet
from codex_harness.coordination.adapters.continuation import MAX_RESEARCH_EVIDENCE_BYTES, ResearchEvidence
from codex_harness.coordination.adapters.guarded_launch import GuardedChildLauncher
from codex_harness.coordination.application.fleet.admission import AdmissionControl
from codex_harness.coordination.application.fleet.registry import FleetRegistry
from codex_harness.coordination.domain.continuation import RESEARCH, ROUTE_OWNERS, ContinuationRefused
from codex_harness.entry import cli as entry
from codex_harness.entry.cli import continuation as root
from codex_harness.kernel.errors import ContractError
from codex_harness.routing.adapters.organization_source import packaged_organization
from codex_harness.storage.adapters.file_artifacts import FileArtifacts
from codex_harness.storage.adapters.memory_store import MemoryStore

SHIM = Path(__file__).resolve().parent / "ported" / "m7_coordination.py"


@pytest.fixture
def settings(monkeypatch, tmp_path):
    values = {"HARNESS_RUNTIME_DIR": str(tmp_path / "runtime")}
    monkeypatch.setattr(configuration, "settings", lambda: values)
    monkeypatch.setattr(configuration, "repository_root", lambda: tmp_path)
    monkeypatch.setattr(configuration, "runtime_dir", lambda: tmp_path / "runtime")
    return values


@pytest.fixture
def service(settings):
    return composition.ServiceHandle(MemoryStore(), packaged_organization())


def shim():
    spec = importlib.util.spec_from_file_location("m7_coordination_c8b1_probe", SHIM)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ----- continuation_owners: the split objects of the shim, and the owner of each M7 method ----------------------------
def test_owners_are_the_split_objects_the_shim_builds():
    probe = shim()
    owners = wiring.continuation_owners(MemoryStore())
    built = probe.Continuation(MemoryStore()).objects
    assert set(vars(owners)) == set(built)
    assert {name: type(getattr(owners, name)) for name in built} == {name: type(obj) for name, obj in built.items()}


def test_each_public_m7_method_is_held_by_the_tabled_owner():
    probe = shim()
    owners = wiring.continuation_owners(MemoryStore())
    built = probe.Continuation(MemoryStore()).objects
    for method, owner in probe.CONTINUATION_ROUTES.items():
        assert callable(getattr(getattr(owners, owner), method))
        assert type(getattr(owners, owner)) is type(built[owner])
    # the table in the module docstring names exactly these owners for the methods the adapters call
    table = {"register": "frames", "policy": "frames", "status": "frames", "unresolved": "frames",
             "accept_research": "research", "supplement_research_scope": "research", "grant_capacity": "grants",
             "requalify_delivery": "requalification", "reconcile_ownership": "ownership", "tick": "tick",
             "drain": "settlement"}
    assert all(probe.CONTINUATION_ROUTES[method] == owner for method, owner in table.items())
    for method, owner in table.items():
        assert f"{method} " in wiring.__doc__ and owner in wiring.__doc__


def test_the_ports_reach_the_objects_that_use_them():
    store, fleet, lanes, conductor, evidence = MemoryStore(), object(), object(), object(), object()
    owners = wiring.continuation_owners(store, fleet, lanes, conductor, lambda manifest: manifest, evidence=evidence)
    assert owners.tick.fleet is fleet and owners.settlement.fleet is fleet
    assert owners.tick.conductor is conductor and owners.settlement.conductor is conductor
    assert owners.research.evidence is evidence and owners.research.lanes is lanes and owners.grants.lanes is lanes
    assert owners.frames.grants is owners.grants and owners.frames.requalification is owners.requalification
    assert owners.tick.settlement is owners.settlement and owners.tick.frames is owners.frames
    assert owners.ownership.successors is owners.successors and owners.grants.research is owners.research


def test_fleet_port_routes_each_method_to_its_s5_owner():
    port = wiring.fleet_port(MemoryStore())
    assert isinstance(port.enqueue.__self__, FleetRegistry)
    assert isinstance(port.reserve_unit.__self__, AdmissionControl) and isinstance(port.settle_unit.__self__, AdmissionControl)


def test_conductor_processes_default_to_the_guarded_spawn_and_the_lane_environment():
    processes = wiring.conductor_processes({"lanes": []}, {})
    assert isinstance(processes.spawn, GuardedChildLauncher) and processes.environment is composition_fleet.lane_environment
    marked = wiring.conductor_processes({"lanes": []}, {}, spawn="spawn", environment="environment")
    assert (marked.spawn, marked.environment) == ("spawn", "environment")


# ----- ResearchEvidence ------------------------------------------------------------------------------------------------
def test_the_store_factory_is_a_required_keyword(tmp_path):
    with pytest.raises(TypeError):
        ResearchEvidence(tmp_path)
    with pytest.raises(TypeError):
        ResearchEvidence(tmp_path, 10, FileArtifacts)


def refusal_of(evidence, reference) -> ContinuationRefused:
    with pytest.raises(ContinuationRefused) as info:
        evidence.verify(reference)
    return info.value


def test_evidence_refuses_a_missing_root_and_a_missing_ref_and_creates_nothing(tmp_path):
    absent = tmp_path / "absent"
    refused = refusal_of(ResearchEvidence(absent, store_factory=FileArtifacts), "sha256:" + "0" * 64)
    assert (refused.reason_code, refused.owner) == ("research_evidence_missing", ROUTE_OWNERS[RESEARCH]) and not absent.exists()
    root_dir = tmp_path / "artifacts"
    root_dir.mkdir()
    refused = refusal_of(ResearchEvidence(root_dir, store_factory=FileArtifacts), "sha256:" + hashlib.sha256(b"none").hexdigest())
    assert refused.reason_code == "research_evidence_missing" and str(tmp_path) not in str(refused)


def test_evidence_accepts_the_stored_bytes_and_refuses_oversized_corrupt_and_non_text(tmp_path):
    artifacts = FileArtifacts(str(tmp_path))
    evidence = ResearchEvidence(tmp_path, store_factory=FileArtifacts)
    stored = artifacts.put("report\n", "research-council")["ref"]
    assert evidence.verify(stored) is None
    path = tmp_path / (stored.partition(":")[2] + ".txt")
    path.write_text("report\nedited after storage\n", encoding="utf-8")
    assert refusal_of(ResearchEvidence(tmp_path, store_factory=FileArtifacts), stored).reason_code == "research_evidence_corrupt"
    big = FileArtifacts(str(tmp_path)).put("x" * (MAX_RESEARCH_EVIDENCE_BYTES + 1), "research-council")["ref"]
    assert refusal_of(ResearchEvidence(tmp_path, store_factory=FileArtifacts), big).reason_code == "research_evidence_oversized"
    assert refusal_of(ResearchEvidence(tmp_path, 3, store_factory=FileArtifacts), artifacts.put("abcdef", "r")["ref"]).reason_code \
        == "research_evidence_oversized"
    data = b"\xff\xfe\x00 binary"
    binary = "sha256:" + hashlib.sha256(data).hexdigest()
    (tmp_path / (binary.partition(":")[2] + ".txt")).write_bytes(data)
    assert refusal_of(ResearchEvidence(tmp_path, store_factory=FileArtifacts), binary).reason_code == "research_evidence_invalid"
    unreadable = artifacts.put("held", "r")["ref"]
    held = tmp_path / (unreadable.partition(":")[2] + ".txt")
    held.unlink()
    held.mkdir()
    refused = refusal_of(ResearchEvidence(tmp_path, store_factory=FileArtifacts), unreadable)
    assert refused.reason_code == "research_evidence_unreadable" and str(tmp_path) not in str(refused)


def test_the_store_is_built_once_by_the_injected_factory(tmp_path):
    built = []

    def factory(root_path):
        built.append(root_path)
        return FileArtifacts(root_path)

    evidence = ResearchEvidence(tmp_path, store_factory=factory)
    ref = FileArtifacts(str(tmp_path)).put("once", "r")["ref"]
    evidence.verify(ref)
    evidence.verify(ref)
    assert built == [str(tmp_path)]


def test_the_configured_evidence_owner_is_the_runtime_artifact_store(monkeypatch, settings, tmp_path):
    monkeypatch.setattr(wiring, "runtime_dir", lambda: tmp_path / "runtime")
    evidence = wiring.research_evidence()
    assert isinstance(evidence, ResearchEvidence) and evidence.root == tmp_path / "runtime" / "artifacts"
    assert evidence.store_factory is FileArtifacts and evidence.max_bytes == MAX_RESEARCH_EVIDENCE_BYTES


# ----- configured_policies -----------------------------------------------------------------------------------------------
@pytest.mark.parametrize("value, expected", [
    (None, None), ("", None), ("   ", None), (" policy-1 ", ["policy-1"]), ("a, b ,c", ["a", "b", "c"])])
def test_configured_policies_parses_the_host_setting_as_m7_does(value, expected):
    settings = {} if value is None else {wiring.POLICY_SETTING: value}
    assert wiring.configured_policies(settings) == expected
    assert wiring.configured_policies(None) is None
    assert wiring.configured_policy(settings) == (None if expected is None else value.strip())


@pytest.mark.parametrize("value, code", [
    ("a,,b", "continuation_policy_list_invalid"), ("a,-b", "continuation_policy_list_invalid"),
    ("a,b,", "continuation_policy_list_invalid"), ("a,b,a", "continuation_policy_list_duplicate")])
def test_a_malformed_policy_list_refuses_before_any_pass(value, code):
    with pytest.raises(ContinuationRefused) as info:
        wiring.configured_policies({wiring.POLICY_SETTING: value})
    assert (info.value.reason_code, info.value.owner) == (code, "operator")


def test_the_ticker_is_one_pass_for_one_policy_and_a_shared_pass_for_several(monkeypatch):
    class Processes:
        pass

    monkeypatch.setattr(wiring, "conductor_processes", lambda config, host: Processes())
    monkeypatch.setattr(wiring, "lane_stores", lambda config, host: (lambda lane: None))
    monkeypatch.setattr(wiring, "research_evidence", lambda: "evidence")
    one = wiring.continuation_ticker(MemoryStore(), {}, {}, "a")
    many = wiring.continuation_ticker(MemoryStore(), {}, {}, ["a", "b"])
    assert type(one) is wiring.ContinuationPass and type(many) is wiring.ContinuationPasses
    assert many.passes[0].processes is many.passes[1].processes is many.processes
    assert wiring.continuation_ticker(MemoryStore(), {}, {}, ["a"]).policy_id == "a"


# ----- the adapters over a MemoryStore -------------------------------------------------------------------------------------------
def test_ownership_reconcile_of_an_unknown_intent_is_refused_by_the_ownership_owner():
    with pytest.raises(ContinuationRefused) as info:
        wiring.reconcile_ownership(MemoryStore(), "nope")
    assert (info.value.reason_code, info.value.owner) == ("ownership_intent_invalid", "operator")


def test_receipt_grant_and_requalification_files_are_bounded_and_named(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    big = tmp_path / "big.json"
    big.write_bytes(b" " * (wiring.MAX_POLICY_BYTES + 1))
    for read, prefix in ((wiring.read_receipt, "research_receipt"), (wiring.read_grant, "capacity_grant"),
                         (wiring.read_requalification, "requalification")):
        for path, suffix in ((bad, "invalid"), (big, "invalid"), (tmp_path / "absent.json", "unreadable")):
            with pytest.raises(ContinuationRefused) as info:
                read(path)
            assert (info.value.reason_code, info.value.owner) == (f"{prefix}_{suffix}", "operator")
    good = tmp_path / "good.json"
    good.write_text('{"a": 1}', encoding="utf-8")
    assert wiring.read_receipt(good) == {"a": 1}


def test_a_policy_document_with_a_duplicate_key_or_bad_utf8_is_refused_by_role(monkeypatch):
    class Source:
        def commit_exists(self, revision):
            return True

        def blob(self, revision, path):
            return "100644", Source.data

    for data in (b'{"a": 1, "a": 2}', b"\xff\xfe"):
        Source.data = data
        with pytest.raises(ContinuationRefused) as info:
            wiring.load_policy(Source(), "a" * 40, "p.json")
        assert (info.value.reason_code, info.value.owner) == ("policy_not_json", "operator")
    Source.data = b"{}"
    monkeypatch.setattr(Source, "commit_exists", lambda self, revision: False)
    with pytest.raises(ContinuationRefused) as info:
        wiring.load_policy(Source(), "a" * 40, "p.json")
    assert info.value.reason_code == "policy_revision_missing"


def test_the_archive_identity_is_the_digest_of_the_resolved_archive_root(tmp_path):
    expected = hashlib.sha256((tmp_path.resolve() / "worker-sessions").as_posix().encode("utf-8")).hexdigest()
    assert wiring.archive_identity(tmp_path) == expected


# ----- the entry bodies ---------------------------------------------------------------------------------------------------------------
def args(**kwargs):
    return SimpleNamespace(**kwargs)


def test_status_reads_the_frames_owner_and_exits_zero(service):
    result = root._execute(service, args(continuation_command="status", policy="nope"))
    assert result["exit_code"] == 0 and result["intents"] == []
    assert root._execute(service, args(continuation_command="status", policy=None))["exit_code"] == 0


def test_a_command_that_needs_the_fleet_refuses_when_none_is_registered(service, tmp_path):
    for command, extra in (("identity", {"lane": "x"}), ("tick", {"policy": "nope"}),
                           ("register", {"lane": "x", "revision": "0" * 40, "path": "p"}),
                           ("research-accept", {"file": tmp_path / "x.json"})):
        with pytest.raises(Exception) as info:
            root._execute(service, args(continuation_command=command, **extra))
        assert getattr(info.value, "reason_code", None) == "unregistered"


def test_a_registered_fleet_config_is_read_before_the_receipt_file(monkeypatch, service, tmp_path):
    monkeypatch.setattr(FleetRegistry, "registered", lambda self: {"config": {"lanes": []}})
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    for command, code in (("research-accept", "research_receipt_invalid"), ("research-supplement", "research_receipt_invalid"),
                          ("capacity-grant", "capacity_grant_invalid"), ("delivery-requalify", "requalification_invalid")):
        with pytest.raises(ContinuationRefused) as info:
            root._execute(service, args(continuation_command=command, file=bad))
        assert (info.value.reason_code, info.value.owner) == (code, "operator")


def test_refusal_prints_a_code_an_owner_and_a_type_only():
    refused = root._refusal(ContinuationRefused("research_receipt_invalid", "operator", "file"))
    assert refused == {"status": "refused", "reason_code": "research_receipt_invalid", "next_owner": "operator",
                       "error_type": "ContinuationRefused", "exit_code": 1}
    assert root._refusal(ContractError("secret text"))["reason_code"] == "contract_refused"
    assert root._refusal(ValueError("secret text")) == {"status": "refused", "reason_code": "error", "next_owner": None,
                                                         "error_type": "ValueError", "exit_code": 1}


def test_conduct_reads_the_manifest_through_the_entry_helper(service, tmp_path):
    bad = tmp_path / "manifest.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(ContractError, match="Operation manifest is not valid JSON"):
        root._conduct(service, args(file=bad))


def pass_double(monkeypatch, outcome, owned):
    events = []

    class Processes:
        def join(self):
            events.append("join")

    class Pass:
        def __init__(self, store, config, host, policy_id, *, observer):
            self.processes = Processes()
            events.append(("pass", policy_id, observer))

        def __call__(self):
            return {"outcome": outcome, "actions": ["a"], "skipped": []}

        def owned(self):
            return owned

        def drain(self):
            events.append("drain")
            return {"actions": ["d"], "skipped": ["s"]}

    observer = SimpleNamespace(close=lambda: events.append("close"))
    monkeypatch.setattr(wiring, "ContinuationPass", Pass)
    monkeypatch.setattr(observation, "build_observer", lambda store, name: observer)
    return events, observer


def test_tick_runs_one_owned_pass_and_always_closes_the_observer(monkeypatch, service, tmp_path):
    monkeypatch.setattr(FleetRegistry, "registered", lambda self: {"config": {}})
    events, observer = pass_double(monkeypatch, "refused", ["launch"])
    result = root._execute(service, args(continuation_command="tick", policy="p"))
    assert events == [("pass", "p", observer), "join", "drain", "close"]
    assert result == {"outcome": "refused", "actions": ["a", "d"], "skipped": ["s"], "exit_code": 1}
    events, observer = pass_double(monkeypatch, "idle", [])
    result = root._execute(service, args(continuation_command="tick", policy="p"))
    assert events == [("pass", "p", observer), "close"] and result["exit_code"] == 0 and result["actions"] == ["a"]


# ----- composition.cli_continuation -------------------------------------------------------------------------------------------------
def test_an_absent_composition_profile_refuses_the_conduct_executor(monkeypatch, service):
    closed = []
    monkeypatch.setattr(observation, "build_observer", lambda *a, **k: SimpleNamespace(close=lambda: closed.append(1)))
    monkeypatch.setattr(cli_operation, "execution_policy", lambda manifest, host: "policy")
    with pytest.raises(ContractError, match="composition_profile_unknown"):
        cli_continuation.lane_executor(service, {"id": "op-1"}, None)


def test_the_lane_executor_is_built_without_knowledge_and_returns_its_budget_and_sessions(monkeypatch, service):
    built = {}
    observer = SimpleNamespace(close=lambda: None)
    monkeypatch.setattr(observation, "build_observer", lambda store, name: (built.update(observer=(store, name)), observer)[1])
    monkeypatch.setattr(cli_operation, "execution_policy", lambda manifest, host: ("policy", manifest["id"]))
    monkeypatch.setattr(cli_operation, "session_owner", lambda svc, op, seen: {"worker_sessions": "sessions"})
    monkeypatch.setattr(cli_operation, "call_budget", lambda: "budget")
    from codex_harness.composition import operation
    monkeypatch.setattr(operation, "host_evidence_profile", lambda: None)
    monkeypatch.setattr(operation, "host_isolation", lambda profile: None)
    monkeypatch.setattr(operation, "build_executor", lambda *a, **k: (built.update(executor=(a, k)), "executor")[1])
    assert cli_continuation.lane_executor(service, {"id": "op-1"}, None) == ("executor", "budget", "sessions")
    assert built["observer"] == (service.store, "cli.continuation")
    (positional, keywords) = built["executor"]
    assert positional == (service,) and keywords == {"observer": observer, "execution_policy": ("policy", "op-1"),
                                                     "knowledge": False, "evidence_profile": None,
                                                     "worker_sessions": "sessions"}
    monkeypatch.setattr(operation, "host_isolation", lambda profile: "isolation")
    cli_continuation.lane_executor(service, {"id": "op-1"}, None)
    assert built["executor"][1]["isolation"] == "isolation"


# ----- dispatch ---------------------------------------------------------------------------------------------------------------------------
def test_the_dispatch_table_composes_the_continuation_root(monkeypatch):
    tree = ast.parse(Path(entry.__file__).resolve().read_text(encoding="utf-8"))
    tables = [node for node in ast.walk(tree) if isinstance(node, ast.Assign)
              and any(isinstance(t, ast.Name) and t.id == "composed" for t in node.targets)]
    assert "continuation" in [key.value for key in tables[0].value.keys]
    called = []
    monkeypatch.setattr(root, "run", lambda parsed: called.append((parsed.command, parsed.continuation_command)))
    monkeypatch.setattr(sys, "argv", ["zeus", "continuation", "status"])
    entry.main()
    assert called == [("continuation", "status")]
