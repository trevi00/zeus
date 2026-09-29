"""Comparison manifest, closed masks, scenarios and origin audit (S0 exit checks 1 and 3)."""

import json
from pathlib import Path

import masks
import origin
import pytest

ROOT = Path(__file__).resolve().parents[2]
COMPARE = ROOT / "compare"


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_baseline_pins_source_and_leaves_deployment_pending():
    base = load(COMPARE / "baseline.json")
    assert base["source"]["commit"] == "e38aa722ff1e91dc01ec650689cfe3eebe1ff699"
    assert base["source"]["tree"] == "5a3622304ab4b20902ad541a363d36526b829ca9"
    assert base["deployment"]["status"] == "pending" and base["deployment"]["collected_at"] is None
    assert base["approved_rebaselines"] == []
    assert base["layout"]["branch"] == "rebuild/zeus-rebuild-001"


def test_mask_list_is_closed_and_refuses_protected_fields():
    document = masks.load()
    assert {m["kind"] for m in document["masks"]} <= masks.KINDS
    for field in ("owner", "generation", "attempt", "lease_until", "status", "context_ref",
                  "manifest_hash", "body_digest"):
        bad = {"version": 1, "closed": True, "masks": [
            {"id": "X", "kind": "nondeterministic_os", "field": field, "scenarios": ["s"], "reason": "r"}]}
        with pytest.raises(ValueError):
            masks.validate(bad)
    with pytest.raises(ValueError):
        masks.validate({"version": 1, "closed": True, "masks": [
            {"id": "X", "kind": "normalize_everything", "field": "a", "scenarios": ["s"], "reason": "r"}]})
    with pytest.raises(ValueError):
        masks.validate({"version": 1, "closed": False, "masks": []})


def test_alpha_renaming_preserves_equality_relations():
    document = {"version": 1, "closed": True, "masks": [
        {"id": "A", "kind": "alpha_rename", "field": "run_id", "scenarios": ["s"], "reason": "r"}]}
    masker = masks.Masker("s", document)
    out = masker.apply([{"run_id": "x"}, {"run_id": "y"}, {"run_id": "x", "status": "ok"}])
    assert out == [{"run_id": "<A:1>"}, {"run_id": "<A:2>"}, {"run_id": "<A:1>", "status": "ok"}]


S0_FAMILIES = {"cli.parser", "entries.safe_matrix", "static.source", "effects.decision_unit",
               "effects.context_packet", "guards.unpatched_transport", "effects.decision_unit.pg"}
S1_FAMILIES = {"kernel.values", "storage.memory", "storage.pg", "storage.redis", "host_os.git", "host_os.process"}
S2_FAMILIES = {"routing.matrix", "context.composition", "context.worker_profile_entry", "knowledge.units"}
S3_FAMILIES = {"containers.profiles", "containers.staging", "credentials.custody", "credentials.scrubber", "hooks.native_container"}
S3_IMPLEMENTED = {"credentials.custody", "credentials.scrubber", "containers.staging", "containers.profiles"}
S4_FAMILIES = {"execution.run_task", "review.decisions", "execution.ledger", "execution.units",
               "execution.output_contracts", "execution.lease_progress", "coordination.execution_owners",
               "review.releases_units", "coordination.execution_time", "coordination.workflow_lease",
               "hooks.candidate_canary", "coordination.decision_guards",
               "coordination.decision_claims", "observation.termination_markers",
               "observation.reconciliation_guard",
               "observation.event_write_side", "research.hook_effects", "coordination.breaker",
               "research.adoption_gate"}
S4_IMPLEMENTED = {"execution.ledger", "execution.units", "execution.output_contracts",
                  "execution.lease_progress", "guards.unpatched_transport",
                  "coordination.execution_owners", "review.releases_units", "coordination.execution_time",
                  "coordination.workflow_lease", "hooks.candidate_canary", "coordination.decision_guards",
                  "coordination.decision_claims", "observation.termination_markers",
                  "observation.reconciliation_guard", "observation.event_write_side", "research.hook_effects", "review.decisions", "effects.decision_unit", "effects.decision_unit.pg",
                  "coordination.breaker"}  # the S0 R-P control, both transports  # S4 in progress: RunTask/ReviewDecisions pending
IMPLEMENTED = {**{f: "S1" for f in S1_FAMILIES}, **{f: "S2" for f in S2_FAMILIES},
               **{f: "S3" for f in S3_IMPLEMENTED}, **{f: "S4" for f in S4_IMPLEMENTED}}


def test_every_scenario_has_a_reference_golden_and_only_implemented_slices_have_a_target():
    scenarios = [load(p) for p in sorted((COMPARE / "scenarios").glob("*.json"))]
    assert {s["family"] for s in scenarios} == (S0_FAMILIES | S1_FAMILIES | S2_FAMILIES | S3_FAMILIES
                                                | S4_FAMILIES)
    for s in scenarios:
        assert (COMPARE / s["reference_driver"]).is_file()
        assert (COMPARE / s["golden"]).is_file()
        if s["family"] in IMPLEMENTED:
            assert s["slice"] == IMPLEMENTED[s["family"]] and (COMPARE / s["target_driver"]).is_file()
            assert "target_status" not in s
            driver = (COMPARE / s["target_driver"]).read_text(encoding="utf-8")
            assert 'driver.start("target")' in driver and "determinism.install" not in driver
        else:
            assert s["target_driver"] is None and s["target_status"].startswith("pending")


def test_s1_scenario_bodies_never_import_the_product():
    for path in (COMPARE / "drivers" / "common").glob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "import codex_harness" not in text and "from codex_harness" not in text, path.name


def test_reference_goldens_hold_the_f3_and_f2_expectations():
    entries = load(COMPARE / "goldens/reference/entries.safe_matrix.json")["rows"]
    assert entries["metadata.no_arguments_from_checkout_root"]["exit"] == 0
    assert entries["metadata.--help"]["exit"] == 2 and entries["metadata.extra_argument"]["exit"] == 2
    assert entries["isolated_worker_entry.empty_stdin"]["json"][0]["kind"] == "refused"
    decision = load(COMPARE / "goldens/reference/effects.decision_unit.json")
    assert decision["a_failure_before_decision_review_lead"]["verdict"] == "atomic_rollback"
    assert decision["b_stale_lease"]["verdict"] == "atomic_rollback"
    assert decision["c_same_key_replay"]["effects"] == [{"depth": 0, "name": "provider_call"}]
    assert decision["control_split_commit"]["verdict"] == "partial_commit"
    assert "write_after_failed_fence" in decision["control_fence_ignored"]["violations"]
    assert decision["control_fabricated_completion"]["effect_protocol"] == ["completion_without_effect"]
    assert decision["control_effect_in_unit"]["violations"] == ["effect_inside_unit"]
    packets = load(COMPARE / "goldens/reference/effects.context_packet.json")["packets"]
    assert packets and all(p["manifest_hash_recomputes"] and p["sha256_matches_ref"] for p in packets)
    assert decision["a_failure_before_decision_review_lead"]["durable_authority_rows"] == []
    transport = load(COMPARE / "goldens/reference/guards.unpatched_transport.json")
    assert transport.pop("markers_written") == []
    assert set(transport.values()) == {"ProviderSpawnRefused"}
    parser = load(COMPARE / "goldens/reference/cli.parser.json")
    assert parser["node_count"] == 152 and parser["root_count"] == 51


def test_import_audit_refuses_a_codex_harness_origin_outside_the_target(tmp_path):
    foreign = tmp_path / "codex_harness"
    foreign.mkdir()
    (foreign / "__init__.py").write_text("")
    finder = origin._AuditFinder((Path(__file__).resolve().parents[1] / "src",))
    with pytest.raises(origin.OriginError):
        finder.find_spec("codex_harness", [str(tmp_path)])


def test_loaded_target_modules_come_from_the_target_tree():
    import codex_harness

    assert Path(codex_harness.__file__).resolve().is_relative_to(Path(__file__).resolve().parents[1] / "src")
    origin.assert_tree_origins(Path(__file__).resolve().parents[1] / "src")


DISCRIMINATOR_FIELDS = ("verdict", "violations", "effect_protocol", "effects", "fences", "decision_status",
                        "outbox_types", "durable_authority_writes", "durable_rows_changed")


def test_postgresql_unit_matches_memory_and_reads_back_durable_rows():
    """Codex S0 F3: the same bounded unit on a labelled disposable PostgreSQL (M7 PostgresStore)."""
    memory = load(COMPARE / "goldens/reference/effects.decision_unit.json")
    pg = load(COMPARE / "goldens/reference/effects.decision_unit.pg.json")
    assert set(pg) == set(memory)
    for case in ("success_review_lead", "success_review_conductor",
                 "a_failure_before_decision_review_lead", "a_failure_before_decision_review_conductor",
                 "b_stale_lease", "c_same_key_replay", "control_fence_ignored",
                 "control_fabricated_completion", "control_effect_in_unit"):
        assert {k: pg[case][k] for k in DISCRIMINATOR_FIELDS} == \
            {k: memory[case][k] for k in DISCRIMINATOR_FIELDS}, case
    assert pg["success_review_lead"]["durable_authority_rows"] == ["releases"]
    assert ["decisions_pending", "succeeded"] in pg["success_review_lead"]["durable_rows_changed"]
    for case in ("a_failure_before_decision_review_lead", "a_failure_before_decision_review_conductor"):
        assert pg[case]["verdict"] == "atomic_rollback" and pg[case]["durable_authority_rows"] == []
        assert ["decisions_pending", "succeeded"] not in pg[case]["durable_rows_changed"]
    assert pg["b_stale_lease"]["fences"] == [False, False]
    assert pg["b_stale_lease"]["durable_authority_rows"] == []
    assert len(pg["c_same_key_replay"]["effects"]) == 1
    # The nested probe waits on the advisory lock its own unit holds; the bounded (fail-fast) lock
    # budget ends it with LockNotAvailable, the recorder flags the nested BEGIN, nothing commits.
    split = pg["control_split_commit"]
    assert split["violations"] == ["nested_begin"] and split["durable_authority_rows"] == []
    assert {e.get("error") for e in split["trace"] if e["kind"] == "ROLLBACK"} == {"LockNotAvailable"}
