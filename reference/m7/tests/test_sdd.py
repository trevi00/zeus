"""Real contract/file/CLI checks; integration cases use PostgreSQL, never device doubles."""
import ast
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path

import pytest

from codex_harness.adapters.artifacts import FileArtifacts
from codex_harness.adapters.sdd import (
    adb_inventory,
    load_json,
    render_review,
    replay_source,
    write_export,
)
from codex_harness.application.sdd import SDD
from codex_harness.application.tickets import Tickets
from codex_harness.bootstrap import organization
from codex_harness.domain.model import ContractError, digest
from codex_harness.domain.model_routing import select_model
from codex_harness.domain.sdd import (
    ENVIRONMENT_FIELDS,
    gate_report,
    propose_scenarios,
    validate_spec,
)

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "docs/sdd/zeus-sdd.spec.json"
SOURCE = {"mode": "working_tree_draft", "repository": "contract-test", "revision": None, "path": "spec.json"}


def spec_data():
    return load_json(SPEC)


def observation_data():
    # Explicitly unverified input data for parser/proposal tests, not a device run.
    env = dict.fromkeys(ENVIRONMENT_FIELDS, "unverified-contract-input")
    env.update(physical_device=False, form_factor="unknown", orientation="unknown")
    event = {"sequence": 1, "scenario_id": "SCN.intent-review", "kind": "observation",
             "name": "contract input", "observed": "Observed behavior is not an oracle",
             "source_ref": "unverified-contract-input", "timestamp": None,
             "observed_timestamp": "2026-09-09T00:00:00+00:00"}
    return env, [event]


def test_missing_spec_empty_coverage_and_unknown_authority_fields_rejected():
    with pytest.raises(ContractError):
        validate_spec({})
    for key, value in (("scenarios", []), ("requirements", []), ("human_approved", True)):
        data = spec_data()
        data[key] = value
        with pytest.raises(ContractError):
            validate_spec(data)
    data = spec_data()
    data["scenarios"].pop()
    with pytest.raises(ContractError, match="without an active scenario"):
        validate_spec(data)


def test_retired_ids_cannot_be_deleted_or_resurrected():
    previous = spec_data()
    retired = deepcopy(previous["scenarios"][0])
    retired.update(id="SCN.retired", status="retired")
    previous["scenarios"].append(retired)
    validate_spec(previous)
    with pytest.raises(ContractError, match="Retire scenario IDs"):
        validate_spec(spec_data(), previous)
    changed = deepcopy(previous)
    changed["scenarios"][-1]["status"] = "active"
    with pytest.raises(ContractError, match="cannot be reused"):
        validate_spec(changed, previous)


def test_requirement_meaning_and_retirement_preserve_history():
    previous = spec_data()
    changed = deepcopy(previous)
    changed["requirements"][0]["statement"] = "A different purpose"
    with pytest.raises(ContractError, match="new ID"):
        validate_spec(changed, previous)
    retired = deepcopy(previous["requirements"][0])
    retired.update(id="REQ.retired", status="retired")
    previous["requirements"].append(retired)
    validate_spec(previous)
    with pytest.raises(ContractError, match="Retire requirement IDs"):
        validate_spec(spec_data(), previous)
    changed = deepcopy(previous)
    changed["requirements"][-1]["status"] = "active"
    changed["scenarios"][0]["requirement_ids"].append("REQ.retired")
    with pytest.raises(ContractError, match="Retired requirement ID"):
        validate_spec(changed, previous)


def test_adb_diagnostics_are_not_transport_rows():
    output = "* daemon not running; starting now at tcp:5037\n* daemon started successfully\nList of devices attached\n"
    assert adb_inventory(output) == []
    assert adb_inventory(output + "emulator-5554 device product:sdk\nserial unauthorized\n") == [
        ("emulator-5554", "device"), ("serial", "unauthorized")]


def test_observations_never_create_oracles_and_environment_changes_identity():
    spec, (env, events) = spec_data(), observation_data()
    first = propose_scenarios(spec, env, events)
    second = propose_scenarios(spec, {**env, "locale": "ko-KR"}, events)
    assert first["environment_hash"] != second["environment_hash"]
    assert first["sequence_complete"] and not first["acceptance_passed"]
    assert "expected" not in first and "then" not in first
    assert len(first["coverage"]["missing"]) == 4
    assert first["observations"][events[0]["scenario_id"]][0]["observed"] == events[0]["observed"]
    events[0].update(sequence=2, scenario_id="SCN.orphan")
    gapped = propose_scenarios(spec, env, events)
    assert not gapped["sequence_complete"] and gapped["coverage"]["orphan"] == ["SCN.orphan"]
    events[0]["observed_timestamp"] = "2026-09-09T00:00:00"
    with pytest.raises(ContractError):
        propose_scenarios(spec, env, events)


def test_claims_cannot_unlock_eight_stage_report():
    report = gate_report(spec_data(), [{"physical_device": True, "human_approved": True, "passed": True}])
    assert len(report["stages"]) == 8
    assert all(s["status"] == "blocked" for s in report["stages"])
    assert not report["acceptance_passed"] and not report["release_authorized"]


def test_bounded_json_duplicate_keys_and_export_integrity(tmp_path):
    path = tmp_path / "input.json"
    path.write_text('{"id":1,"id":2}', "utf-8")
    with pytest.raises(ContractError, match="Duplicate JSON"):
        load_json(path)
    path.write_bytes(b" " * (1024 * 1024 + 1))
    with pytest.raises(ContractError, match="budget"):
        load_json(path)
    target = tmp_path / "review.html"
    first = write_export(target, "검토")
    assert write_export(target, "검토") == first
    with pytest.raises(ContractError, match="different content"):
        write_export(target, "변경")
    assert target.read_text("utf-8") == "검토"
    for kind in ("review", "replay"):
        with pytest.raises(ContractError, match="automatic test collection"):
            write_export(tmp_path / "test_generated.py", "content", kind)
    assert not (tmp_path / "test_generated.py").exists()


def test_review_embedded_content_cannot_escape_json_script():
    spec = spec_data()
    spec["title"] = '</script><script>alert("injected")</script>'
    page = render_review(spec)
    assert spec["title"] not in page
    body = page.split('<script id="sdd-data" type="application/json">')[1].split('</script>')[0]
    assert json.loads(body)["spec"]["title"] == spec["title"]


def test_replay_export_refuses_unknown_target_financial_flows_and_missing_bindings():
    spec = spec_data()
    with pytest.raises(ContractError, match="Concrete Android"):
        replay_source(spec)
    spec["target"].update(kind="android", app_id="contract.test", build_hash="a" * 64)
    with pytest.raises(ContractError, match="Financial replay"):
        replay_source(spec)
    for req in spec["requirements"]:
        req["risk"] = "normal"
    with pytest.raises(ContractError, match="per-scenario reset"):
        replay_source(spec)
    spec["scenarios"] = spec["scenarios"][:1]
    spec["requirements"] = spec["requirements"][:1]
    with pytest.raises(ContractError, match="no observed selector"):
        replay_source(spec)
    for scenario in spec["scenarios"]:
        scenario["bindings"] = [{"operation": "assert_text", "selector": {"strategy": "id", "value": "contract:id/label"},
                                 "value": text, "oracle_index": i, "source_ref": "unverified-contract-input"}
                                for i, text in enumerate(scenario["then"])]
    source = replay_source(spec)
    # Syntax validation only: no Appium import, no fake server and no device acceptance claim.
    ast.parse(source)
    spec["scenarios"][0]["bindings"].pop()
    with pytest.raises(ContractError, match="Every oracle"):
        replay_source(spec)


def replay_ready_spec(then_texts=None, value_texts=None):
    spec = spec_data()
    spec["target"].update(kind="android", app_id="contract.test", build_hash="a" * 64)
    for req in spec["requirements"]:
        req["risk"] = "normal"
    spec["scenarios"] = spec["scenarios"][:1]
    spec["requirements"] = spec["requirements"][:1]
    scenario = spec["scenarios"][0]
    scenario["requirement_ids"] = [spec["requirements"][0]["id"]]
    if then_texts is not None:
        scenario["then"] = then_texts
    values = value_texts or scenario["then"]
    scenario["bindings"] = [{"operation": "assert_text", "selector": {"strategy": "id", "value": "contract:id/label"},
                             "value": values[i], "oracle_index": i, "source_ref": "unverified-contract-input"}
                            for i in range(len(scenario["then"]))]
    scenario["bindings"].insert(0, {"operation": "tap", "selector": {"strategy": "accessibility id", "value": "go"},
                                    "value": None, "oracle_index": None, "source_ref": "unverified-contract-input"})
    return spec


def test_replay_attributes_every_assertion_to_its_oracle_and_requirements_at_runtime():
    # FA-014: no xfail/skeleton, no truncation, and hostile text survives as Python literals.
    hostile = ['첫 번째 기대 """docstring""" \\ backslash', "second 'quote' \"double\" line\nbreak\ttab",
               "x" * 400 + " end"]
    spec = replay_ready_spec(then_texts=hostile, value_texts=["a\"b", "c'd\n", "e\\f"])
    source = replay_source(spec)
    tree = ast.parse(source)
    assert not any(token in source for token in ("xfail", "skip(", "NotImplementedError", "pass  #"))
    constants = {node.targets[0].id: ast.literal_eval(node.value) for node in tree.body
                 if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)}
    scenario = spec["scenarios"][0]
    assert constants["SPEC_HASH"] == digest(validate_spec(spec))
    assert constants["ORACLES"] == {scenario["id"]: {"requirement_ids": scenario["requirement_ids"], "oracles": hostile}}
    attributions, expected_values = [], []
    for node in ast.walk(tree):
        if isinstance(node, ast.With):
            call = node.items[0].context_expr
            assert isinstance(call, ast.Call) and call.func.attr == "subTest"
            attributions.append(ast.literal_eval(call.keywords[0].value))
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "exact_text":
            expected_values.append(ast.literal_eval(node.args[1]))
    assert attributions == [{"scenario": scenario["id"], "oracle": i, "requirement_ids": scenario["requirement_ids"],
                             "expected": text} for i, text in enumerate(hostile)]
    assert expected_values == ["a\"b", "c'd\n", "e\\f"]
    assert len(attributions[2]["expected"]) == 404, "acceptance text is never truncated"
    tap_line = next(line for line in source.splitlines() if "element.click()" in line)
    assert not tap_line.startswith("            "), "actions carry no oracle attribution"


def test_gwt_must_be_lists_never_one_line_strings():
    spec = spec_data()
    spec["scenarios"][0]["then"] = "Given x When y Then z"
    with pytest.raises(ContractError, match="Missing or excessive then"):
        validate_spec(spec)
    spec = spec_data()
    spec["scenarios"][0]["given"] = ["", "ok"]
    with pytest.raises(ContractError, match="Invalid given"):
        validate_spec(spec)


def test_replay_export_is_idempotent_and_never_overwrites_a_different_draft(tmp_path):
    source = replay_source(replay_ready_spec())
    target = tmp_path / "draft.py.review"
    first = write_export(target, source, kind="replay")
    assert write_export(target, source, kind="replay") == first
    with pytest.raises(ContractError, match="different content"):
        write_export(target, source + "\n# edited", kind="replay")
    assert target.read_text("utf-8") == source
    with pytest.raises(ContractError, match="py.review"):
        write_export(tmp_path / "test_draft.py", source, kind="replay")


def test_offline_cli_review_runs_without_database_access(tmp_path):
    result = subprocess.run([sys.executable, "-m", "zeus", "sdd", "view", str(SPEC),
                             "--output", str(tmp_path / "review.html")], cwd=ROOT,
                            capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["status"] == "review_only"
    replay = subprocess.run([sys.executable, "-m", "zeus", "sdd", "export-replay", str(SPEC),
                             "--output", str(tmp_path / "test_replay.py")], cwd=ROOT,
                            capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert replay.returncode != 0 and not (tmp_path / "test_replay.py").exists()


@pytest.fixture
def sdd(isolated_pgstore, tmp_path):
    tickets = Tickets(isolated_pgstore, organization())
    ticket = tickets.create({"title": "SDD contract validation", "problem": "Missing version binding",
        "impact": "Stale evidence", "rollback": "Keep prior snapshot", "evidence_refs": ["contract-test-input"],
        "scope": ["sdd"], "acceptance_criteria": ["Reject stale evidence"], "verification": ["Real PostgreSQL integration"]})
    service = SDD(isolated_pgstore, FileArtifacts(tmp_path / "artifacts"))
    row = service.register(spec_data(), ticket["id"], 1, SOURCE)
    return service, tickets, ticket, row


@pytest.mark.integration
def test_real_postgres_idempotency_gaps_notifications_and_restart(sdd):
    service, _, ticket, row = sdd
    assert row == service.register(spec_data(), ticket["id"], 1, SOURCE)
    env, events = observation_data()
    events[0]["sequence"] = 2
    observation = service.observe(row["id"], env, events, "contract-test-input")
    assert observation == service.observe(row["id"], env, events, "contract-test-input")
    proposal = service.propose(row["id"], observation["id"])
    assert proposal == service.propose(row["id"], observation["id"])
    restarted = SDD(service.store, service.artifacts)
    status = restarted.status(row["id"])
    assert len(status["observations"]) == 1 and status["sequence"] == 3
    assert {n["code"] for n in status["notifications"]} == {"human_authority_missing", "observation_gap", "unverified_observation"}
    assert all(n["count"] == 1 and n["delivery"] == "local_only" for n in status["notifications"])
    assert not status["report"]["acceptance_passed"]
    assert "expected" not in service.artifacts.document(proposal["artifact_ref"])


@pytest.mark.integration
def test_real_postgres_transition_cas_and_superseded_spec(sdd):
    service, _, ticket, row = sdd
    def advance():
        try:
            return service.request_advance(row["id"], 1)["status"]
        except ContractError:
            return "stale"
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _: advance(), range(2))) == ["blocked", "stale"]
    changed = spec_data()
    changed["intent"] += " Revision two."
    latest = service.register(changed, ticket["id"], 1, SOURCE)
    assert service.status(row["id"])["status"] == "superseded_spec"
    with pytest.raises(ContractError, match="Superseded SDD"):
        service.observe(row["id"], *observation_data(), "contract-test-input")
    assert latest["revision"] == 2


@pytest.mark.integration
def test_real_postgres_identical_observations_stay_bound_to_each_iteration(sdd):
    service, tickets, ticket, row = sdd
    first_observation = service.observe(row["id"], *observation_data(), "contract-test-input")
    first = service.propose(row["id"], first_observation["id"])
    content = deepcopy(tickets.get(ticket["id"])["content"])
    content["title"] += " revised"
    tickets.update(ticket["id"], 1, content, "New review topic revision")
    newer = service.register(spec_data(), ticket["id"], 2, SOURCE)
    second_observation = service.observe(newer["id"], *observation_data(), "contract-test-input")
    second = service.propose(newer["id"], second_observation["id"])
    assert first_observation["artifact_ref"] == second_observation["artifact_ref"]
    assert first["artifact_ref"] != second["artifact_ref"] and second["iteration_id"] == newer["id"]


@pytest.mark.integration
def test_real_postgres_stale_ticket_and_corrupt_artifact_rejected(sdd):
    service, tickets, ticket, row = sdd
    content = deepcopy(tickets.get(ticket["id"])["content"])
    content["title"] += " revised"
    tickets.update(ticket["id"], 1, content, "Updated acceptance")
    assert service.status(row["id"])["status"] == "superseded_ticket"
    with pytest.raises(ContractError, match="Ticket changed"):
        service.observe(row["id"], *observation_data(), "contract-test-input")
    artifact = service.artifacts.root / (row["spec_ref"][7:] + ".txt")
    artifact.write_text("corrupt", "utf-8")
    with pytest.raises(ContractError, match="Artifact modified"):
        service.status(row["id"])


@pytest.mark.integration
def test_real_postgres_journal_tampering_is_detected(sdd):
    service, _, _, row = sdd
    with service.store.transaction() as tx:
        event = tx.scan("sdd_events")[0]
        event["kind"] = "unauthorized_edit"
        tx.put("sdd_events", row["id"] + ":00000001", event)
    with pytest.raises(ContractError, match="journal gap or corruption"):
        service.status(row["id"])


@pytest.mark.integration
def test_appended_sidecar_event_never_softens_a_journal_break(sdd):
    # FA-007: a new, well-formed continuation record does not downgrade a broken chain.
    from codex_harness.domain.model import digest, utcnow
    service, _, _, row = sdd
    with service.store.transaction() as tx:
        first = tx.scan("sdd_events")[0]
        first["kind"] = "unauthorized_edit"
        tx.put("sdd_events", row["id"] + ":00000001", first)
        current = tx.get("sdd_iterations", row["id"])
        sidecar = {"iteration_id": row["id"], "sequence": current["sequence"] + 1,
                   "previous_hash": current["event_hash"], "at": utcnow(), "kind": "compaction_marker",
                   "refs": [], "note": "claims to summarize earlier events"}
        sidecar["hash"] = digest(sidecar)
        tx.put("sdd_events", row["id"] + ":%08d" % sidecar["sequence"], sidecar)
        current.update(sequence=sidecar["sequence"], event_hash=sidecar["hash"])
        tx.put("sdd_iterations", row["id"], current)
    with pytest.raises(ContractError, match="journal gap or corruption"):
        service.status(row["id"])
    with service.store.transaction() as tx:
        assert len(tx.scan("sdd_events")) == 2, "evidence of both records is retained"


@pytest.mark.integration
def test_real_postgres_transfer_evidence_cannot_change_model_authority(sdd):
    service, _, _, row = sdd
    record = {"task_family": "frontend.selector-export", "contract_hash": "a" * 64,
              "guardrail_hash": "b" * 64, "toolchain_hash": "c" * 64,
              "source_model": "gpt-6-astra", "target_model": "gpt-5.6-sol", "evidence_refs": [row["spec_ref"]]}
    result = service.record_transfer(row["id"], record)
    assert result == service.record_transfer(row["id"], record)
    assert not result["routing_authority"] and result["status"] == "recorded_unqualified"
    assert select_model("implementation", "simple").requested_model == "gpt-6-astra"
    with pytest.raises(ContractError, match="Concrete task family"):
        service.record_transfer(row["id"], {**record, "task_family": "*"})
