"""INV-HOST-DELIVERY-MAINTENANCE-001, CLI glue: `zeus host-delivery maintain`.

The use case is a LABELLED fake (`maintenance_controller` monkeypatched) except where the real port wiring is
the subject; lane routing is a labelled `resolve_lane`. The observer, Git workspace, ordinary controller and
BOTH executor transports (AppServer and ClaudeCodeRuntime) are stubbed to raise, so a test that reached one of
them fails instead of calling anything real. The store is an in-memory Harness; no unit, provider, model,
database or network is touched.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from codex_harness import cli
from codex_harness.adapters import host_delivery
from codex_harness.adapters.host_delivery import MAINTENANCE_RESULT_KEYS, execute, refusal
from codex_harness.adapters.maintenance_evidence import (
    LazyArtifacts,
)
from codex_harness.adapters.managed_runtime import SystemdManagedFleetTarget
from codex_harness.adapters.store import MemoryStore
from codex_harness.application.fleet import Fleet
from codex_harness.application.owner_actions import BUCKET_ACTIONS
from codex_harness.bootstrap import organization
from codex_harness.domain.host_delivery import (
    KIND_MANAGED_SYSTEMD,
    DeliveryRefused,
    validate_first_activation,
)
from codex_harness.domain.model import ContractError, canonical, digest

EVIDENCE = "sha256:" + "e" * 64
SENTINEL = "SENTINEL-must-never-be-printed"


def maintenance_document(**overrides) -> dict:
    return {"schema": "urn:zeus:host-delivery-active-generation:1", "kind": "active_generation_restart",
            "plan_id": "managed-plan-1", "plan_sha256": "1" * 64, "pin_sha256": "2" * 64,
            "target_id": "managed-fleet", "release_id": "release-1", "descriptor_sha256": "3" * 64,
            "from": {"stage": "active", "updated_at": "2026-09-28T00:00:00+00:00"},
            "retiring": {"instance_id": "a1" * 16, "invocation_id": "c3" * 16, "launch_sha256": "4" * 64},
            "reason": "unit_environment_changed", "canary_window_seconds": 1800,
            "authority": "sha256:" + "5" * 64, "approved_by": "conductor-1", **overrides}


def service_for():
    return SimpleNamespace(store=MemoryStore(), org=organization())


def args(**fields):
    base = {"delivery_command": "maintain", "lane": None, "phase": "restart", "document": None,
            "evidence": EVIDENCE, "check": False}
    return SimpleNamespace(**{**base, **fields})


def write_document(tmp_path, document) -> Path:
    path = tmp_path / "maintenance.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


@pytest.fixture
def forbidden(monkeypatch):
    """Everything `maintain` must never build: the tick observer, Git, the ordinary controller, the
    executor transports and the artifact store."""
    reached = []

    def never(name):
        def refuse(*_args, **_kwargs):
            reached.append(name)
            raise AssertionError(name + " was reached by the maintenance CLI")
        return refuse
    import codex_harness.adapters.artifacts as artifacts
    import codex_harness.adapters.executor as executor
    import codex_harness.bootstrap as bootstrap
    for name in ("_observer", "_lane_observer", "_git", "lane_git", "controller", "release_verifier"):
        monkeypatch.setattr(host_delivery, name, never(name))
    monkeypatch.setattr(executor, "AppServer", never("AppServer"))
    monkeypatch.setattr(executor, "ClaudeCodeRuntime", never("ClaudeCodeRuntime"))
    monkeypatch.setattr(bootstrap, "build_executor", never("build_executor"))
    monkeypatch.setattr(artifacts, "FileArtifacts", never("FileArtifacts"))
    return reached


class FakeMaintenance:
    """LABELLED use case: records each call and answers the queued result (or raises it)."""

    def __init__(self, *results):
        self.results, self.calls = list(results), []

    def maintain(self, document, evidence_ref, phase, *, check=False):
        self.calls.append((document["kind"], evidence_ref, phase, check))
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def result(**overrides) -> dict:
    return {"schema": "urn:zeus:host-delivery-maintenance:1", "maintenance_id": "active_generation_1:" + "9" * 64,
            "phase": "restart", "check": False, "applicable": True, "state": "started", "cached": False,
            "pending": False, "reason_code": None, "field": None,
            "identities": dict.fromkeys(("plan_id", "release_id", "target_id", "descriptor_sha256",
                                         "retiring_instance_id", "retiring_invocation_id", "new_instance_id",
                                         "new_invocation_id", "action_id", "job_id")),
            "deadline": None, "evidence": {"document": EVIDENCE, "authority": None, "prior": None},
            "authority": "INV-HOST-DELIVERY-MAINTENANCE-001", **overrides}


def maintain_parser() -> argparse.ArgumentParser:
    def child(parser, name):
        for action in parser._actions:
            if isinstance(action, argparse._SubParsersAction) and name in action.choices:
                return action.choices[name]
        raise AssertionError(name)
    return child(child(cli.parser(), "host-delivery"), "maintain")


# ----- S2M-2: the exact command shape, no token argument ------------------------------------------------------
def test_parser_exposes_maintain_with_exact_options_and_no_token_argument():
    argv = ["host-delivery", "maintain", "--lane", "harness", "--phase", "restart", "--document", "doc.json",
            "--evidence", EVIDENCE, "--check"]
    parsed = cli.parser().parse_args(argv)
    assert (parsed.command, parsed.delivery_command, parsed.lane, parsed.phase, parsed.document, parsed.evidence,
            parsed.check) == ("host-delivery", "maintain", "harness", "restart", "doc.json", EVIDENCE, True)
    assert cli.parser().parse_args(argv[:5] + ["restart"] + argv[6:-1]).phase == "restart"
    # This release carries the restart phase only (ALL-PRIMARY-20260930): arm and bind are not accepted.
    for phase in ("arm", "bind"):
        with pytest.raises(SystemExit):
            cli.parser().parse_args(argv[:5] + [phase] + argv[6:-1])
    assert cli.parser().parse_args(argv[:-1]).check is False
    options = {option for action in maintain_parser()._actions for option in action.option_strings}
    assert options == {"-h", "--help", "--lane", "--phase", "--document", "--evidence", "--check"}
    for bad in (argv[:5] + ["rollback"] + argv[6:], argv + ["--token", "x"], argv + ["--credential", "x"],
                argv + ["--env", "A=B"], argv + ["--supersedes", "x"]):
        with pytest.raises(SystemExit):
            cli.parser().parse_args(bad)
    for required in ("--phase", "--document", "--evidence"):
        index = argv.index(required)
        with pytest.raises(SystemExit):
            cli.parser().parse_args(argv[:index] + argv[index + 2:])


# ----- S2M-17: routing, the check flag and the exit code ---------------------------------------------------------
def test_execute_routes_phase_check_and_exit_codes(tmp_path, monkeypatch, forbidden):
    service, lane_store = service_for(), MemoryStore()
    route = {"lane": {"id": "harness", "repository": str(tmp_path), "runtime": str(tmp_path / "rt")},
             "store": lane_store}
    monkeypatch.setattr(host_delivery, "resolve_lane", lambda _service, lane_id: route)
    fake = FakeMaintenance(result(), result(check=True, applicable=False, state="started",
                                            reason_code="maintenance_already_used", field="document"),
                           {**result(state="started"), "raw_document": SENTINEL})
    built = []
    monkeypatch.setattr(host_delivery, "maintenance_controller",
                        lambda _service, *, store, check: built.append((store, check)) or fake)
    path = write_document(tmp_path, maintenance_document())
    started = execute(service, args(lane="harness", document=str(path)))
    assert started == {**result(), "lane": "harness", "exit_code": 0}
    checked = execute(service, args(document=str(path), check=True))
    assert checked["exit_code"] == 1 and checked["applicable"] is False and "lane" not in checked
    # Only the typed result keys are printed, whatever else a result carried.
    replayed = execute(service, args(document=str(path)))
    assert replayed["exit_code"] == 0 and SENTINEL not in json.dumps(replayed)
    assert set(replayed) <= set(MAINTENANCE_RESULT_KEYS) | {"lane", "exit_code"}
    assert fake.calls == [("active_generation_restart", EVIDENCE, "restart", False),
                          ("active_generation_restart", EVIDENCE, "restart", True),
                          ("active_generation_restart", EVIDENCE, "restart", False)]
    # The lane store holds the delivery records; `--check` reaches the controller builder and the use case.
    assert built == [(lane_store, False), (service.store, True), (service.store, False)]
    assert forbidden == []


# ----- S2M-2: the document is one bounded regular JSON object ----------------------------------------------------
def test_unreadable_or_oversized_document_is_maintenance_invalid(tmp_path, monkeypatch, forbidden):
    monkeypatch.setattr(host_delivery, "maintenance_controller",
                        lambda *_a, **_k: pytest.fail("the use case was built for an unreadable document"))
    service = service_for()
    cases = {"missing": tmp_path / "absent.json", "directory": tmp_path}
    for name, body in (("malformed", b"{not json"), ("list", b"[1, 2]"), ("string", b"\"" + SENTINEL.encode() + b"\""),
                       ("oversized", b"{\"a\": \"" + b"x" * (70 * 1024) + b"\"}"), ("not_utf8", b"\xff\xfe{}")):
        cases[name] = tmp_path / (name + ".json")
        cases[name].write_bytes(body)
    if hasattr(os, "mkfifo"):
        cases["fifo"] = tmp_path / "fifo.json"
        os.mkfifo(cases["fifo"])  # a FIFO is refused without blocking on a writer
    for name, path in cases.items():
        with pytest.raises(DeliveryRefused) as refused:
            execute(service, args(document=str(path)))
        assert (refused.value.reason_code, refused.value.field) == ("maintenance_invalid", "document"), name
        assert SENTINEL not in json.dumps(refusal(refused.value))
    assert forbidden == []


# ----- S2M-17: `--check` builds nothing that could write, launch or observe ------------------------------------------
def test_check_builds_no_observer_git_executor_or_artifact_store(tmp_path, monkeypatch, forbidden):
    runtime = tmp_path / "runtime"
    monkeypatch.setattr(host_delivery, "_settings", lambda: {})
    import codex_harness.adapters.configuration as configuration
    monkeypatch.setattr(configuration, "runtime_dir", lambda: runtime)
    built = []

    class RecordingDelivery:
        def __init__(self, store, org, **kwargs):
            built.append(kwargs)

        def maintain(self, document, evidence_ref, phase, *, check=False):
            return result(phase=phase, check=check, applicable=True, state=None)
    monkeypatch.setattr(host_delivery, "HostDelivery", RecordingDelivery)
    service = service_for()
    path = write_document(tmp_path, maintenance_document())
    printed = execute(service, args(phase="restart", document=str(path), check=True))
    assert printed["exit_code"] == 0 and printed["check"] is True
    for kwargs in built:
        assert kwargs["artifacts"] is None and kwargs["observer"] is None
        assert "github" not in kwargs and "verifier" not in kwargs and "first_activation" not in kwargs
        assert not {"credentials", "canary_executor", "qualification_deadline"} & set(kwargs)
    assert len(built) == 1 and forbidden == [] and not runtime.exists()
    with service.store.transaction() as tx:
        assert tx.scan(BUCKET_ACTIONS) == []


# ----- S2M-17: a refusal prints a fixed code and at most an allowlisted field ---------------------------------------
def test_refusal_prints_only_allowlisted_fields(tmp_path, monkeypatch, capsys, forbidden):
    assert refusal(DeliveryRefused("maintenance_stale", "target_file")) == {
        "status": "refused", "reason_code": "maintenance_stale", "error_type": "DeliveryRefused", "exit_code": 1,
        "field": "target_file"}
    for exc in (DeliveryRefused("maintenance_stale", "/srv/" + SENTINEL), DeliveryRefused("maintenance_invalid",
                                                                                        "Document"),
                DeliveryRefused("maintenance_invalid", "x" * 80), DeliveryRefused("maintenance_invalid"),
                DeliveryRefused("maintenance_invalid", SENTINEL + " value")):
        printed = refusal(exc)
        assert "field" not in printed and SENTINEL not in json.dumps(printed)
    # Every other refusal prints exactly as before: no field.
    assert refusal(DeliveryRefused("descriptor_predecessor_mismatch", "expected_descriptor")) == {
        "status": "refused", "reason_code": "descriptor_predecessor_mismatch", "error_type": "DeliveryRefused",
        "exit_code": 1}
    assert refusal(ContractError("Stale maintenance controller"))["reason_code"] == "contract_refused"
    assert refusal(OSError("/srv/" + SENTINEL)) == {"status": "refused", "reason_code": "error",
                                                    "error_type": "OSError", "exit_code": 1}
    # Through the real CLI command: a maintenance refusal is printed with its field and exits 1.
    fake = FakeMaintenance(DeliveryRefused("maintenance_reload_pending", "unit"),
                           DeliveryRefused("maintenance_stale", SENTINEL))
    monkeypatch.setattr(host_delivery, "maintenance_controller", lambda _service, *, store, check: fake)
    path = write_document(tmp_path, maintenance_document())
    for expected in ({"reason_code": "maintenance_reload_pending", "field": "unit"},
                     {"reason_code": "maintenance_stale"}):
        with pytest.raises(SystemExit) as exited:
            cli.host_delivery_command(service_for(), args(document=str(path)))
        assert exited.value.code == 1
        printed = json.loads(capsys.readouterr().out)
        assert printed == {"status": "refused", "error_type": "DeliveryRefused", "exit_code": 1, **expected}
        assert SENTINEL not in json.dumps(printed)


# ----- S2M-1: `resume --document` never reaches maintenance ----------------------------------------------------------
def test_resume_document_never_routes_to_maintenance(tmp_path, monkeypatch, forbidden):
    calls = []

    class Controller:
        def resume_first_activation(self, plan_id, plan_sha256, document, evidence):
            calls.append(("first_activation", document["kind"]))
            return validate_first_activation(document)

        def __getattr__(self, name):
            raise AssertionError("resume routed to " + name)
    monkeypatch.setattr(host_delivery, "_observer", lambda _service: None)
    monkeypatch.setattr(host_delivery, "_git", lambda _service: SimpleNamespace(repository=tmp_path))
    monkeypatch.setattr(host_delivery, "controller", lambda _service, **_kwargs: Controller())
    monkeypatch.setattr(host_delivery, "maintenance_controller",
                        lambda *_a, **_k: pytest.fail("resume reached the maintenance controller"))
    path = write_document(tmp_path, maintenance_document())
    resume = SimpleNamespace(delivery_command="resume", lane=None, plan="managed-plan-1", plan_sha256="1" * 64,
                             evidence="sha256:" + digest(maintenance_document()), document=str(path))
    with pytest.raises(DeliveryRefused) as refused:
        execute(service_for(), resume)
    # The unchanged router hands an unknown kind to the first-activation validator, which refuses it.
    assert calls == [("first_activation", "active_generation_restart")]
    assert not refused.value.reason_code.startswith("maintenance_")
    assert canonical(maintenance_document()) not in str(refused.value)
    assert forbidden == []


# ----- integration: the real port wiring of `maintenance_controller` ---------------------------------------------------
def test_maintenance_controller_wires_every_port(tmp_path, monkeypatch, forbidden):
    runtime = tmp_path / "runtime"
    host = {}
    monkeypatch.setattr(host_delivery, "_settings", lambda: host)
    import codex_harness.adapters.configuration as configuration
    monkeypatch.setattr(configuration, "runtime_dir", lambda: runtime)
    service, lane_store = service_for(), MemoryStore()
    with service.store.transaction() as tx:
        tx.put(BUCKET_ACTIONS, "b" * 64, {"id": "b" * 64, "state": "requested"})
    delivery = host_delivery.maintenance_controller(service, store=lane_store, check=False)
    assert delivery.store is lane_store and delivery.observer is None and delivery.github is None
    assert isinstance(delivery.artifacts, LazyArtifacts)
    assert isinstance(delivery.maintenance_fleet, Fleet) and delivery.maintenance_fleet.store is service.store
    assert delivery.canary_records("b" * 64) == {"id": "b" * 64, "state": "requested"}
    # The restart phase's ports only (ALL-PRIMARY-20260930): no credential helper, executor or deadline port.
    assert not any(hasattr(delivery, name) for name in ("credentials", "canary_executor", "qualification_deadline"))
    managed = delivery.hosts[KIND_MANAGED_SYSTEMD]
    assert isinstance(managed, SystemdManagedFleetTarget) and managed.fleet is delivery.maintenance_fleet
    with pytest.raises(DeliveryRefused) as unverified:
        delivery.authorities("sha256:" + "0" * 64)
    assert unverified.value.reason_code == "maintenance_authority_unverified"
    checked = host_delivery.maintenance_controller(service, store=lane_store, check=True)
    assert checked.artifacts is None
    assert callable(checked.authorities) and callable(checked.canary_records)
    # Building either controller created nothing: no runtime, artifact store or lock.
    assert not runtime.exists() and forbidden == []
