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
               "research.adoption_gate", "coordination.workflow_submit", "coordination.session_checkpoints",
               "execution.progress_activity"}
S4_IMPLEMENTED = {"execution.ledger", "execution.units", "execution.output_contracts",
                  "execution.lease_progress", "guards.unpatched_transport",
                  "coordination.execution_owners", "review.releases_units", "coordination.execution_time",
                  "coordination.workflow_lease", "hooks.candidate_canary", "coordination.decision_guards",
                  "coordination.decision_claims", "observation.termination_markers",
                  "observation.reconciliation_guard", "observation.event_write_side", "research.hook_effects", "review.decisions", "effects.decision_unit", "effects.decision_unit.pg",
                  "coordination.breaker", "research.adoption_gate",
                  "coordination.workflow_submit", "coordination.session_checkpoints",
                  "execution.progress_activity", "execution.run_task", "effects.context_packet"}  # the S0 R-P control, both transports  # S4 in progress: RunTask/ReviewDecisions pending
# S5 characterization first (RESEARCH-S5, TRACE-coordination §4.1): reference goldens, targets pending.
S5_FAMILIES = {"coordination.workflow_handle", "coordination.outbox_relay", "coordination.local_cycle",
               "coordination.operation", "coordination.fleet", "coordination.fleet_recovery",
               "coordination.fleet_runner", "coordination.execution_recovery", "coordination.fleet_relocation",
               "effects.admission_unit", "effects.admission_unit.pg"}
S5_IMPLEMENTED = {"coordination.fleet", "coordination.fleet_recovery", "coordination.fleet_runner",
                  "coordination.fleet_relocation", "coordination.workflow_handle",
                  "coordination.outbox_relay", "coordination.local_cycle",
                  "coordination.operation",
                  "effects.admission_unit", "effects.admission_unit.pg",
                  "coordination.execution_recovery"}
S6_FAMILIES = {"coordination.continuation_tick", "coordination.continuation_routes",
               "coordination.continuation_owner_paths", "coordination.continuation_research",
               "coordination.owner_actions_research", "coordination.guarded_launch",
               "effects.continuation_units", "effects.continuation_units.pg"}
S6_IMPLEMENTED = {"coordination.guarded_launch", "coordination.continuation_tick",
                  "coordination.continuation_routes", "coordination.continuation_owner_paths",
                  "coordination.continuation_research", "coordination.owner_actions_research",
                  "effects.continuation_units", "effects.continuation_units.pg"}
S7_FAMILIES = {"review.releases_queue", "delivery.registry", "delivery.stages", "delivery.owner_commands",
               "delivery.migration", "delivery.host_migrations", "coordination.owner_actions_delivery",
               "coordination.owner_actions_canary", "coordination.owner_actions_migration",
               "effects.delivery_units", "effects.delivery_units.pg", "delivery.host_targets",
               "delivery.managed_runtime", "delivery.managed_systemd", "delivery.release_runner",
               "delivery.canaries", "delivery.migration_evidence", "delivery.host_migration_transfer",
               "delivery.host_migration_cli", "delivery.migration_evidence_cli",
               "delivery.fleet_recovery_collectors", "delivery.restore.pg", "delivery.tooling"}
S8_FAMILIES = {"research.program_tick", "research.capture", "research.program_records", "research.dispatch_recovery", "research.sources",
               "intake.portfolio", "research.dge", "evidence.inspections", "research.autonomous", "research.audit_core", "research.audit_progress"}
S7_IMPLEMENTED = {"delivery.tooling", "delivery.restore.pg", "delivery.fleet_recovery_collectors", "delivery.release_runner", "delivery.canaries", "delivery.migration_evidence", "delivery.host_migration_transfer", "delivery.host_targets", "delivery.managed_runtime", "delivery.managed_systemd",
                  "review.releases_queue", "delivery.registry", "delivery.stages",
                  "delivery.owner_commands", "delivery.migration", "delivery.host_migrations",
                  "coordination.owner_actions_delivery", "coordination.owner_actions_canary",
                  "coordination.owner_actions_migration", "effects.delivery_units", "effects.delivery_units.pg"}
S8_IMPLEMENTED = {"intake.portfolio", "research.dge", "evidence.inspections", "research.autonomous", "research.audit_core",
                  "research.audit_progress",
                  "research.program_records", "research.capture", "research.program_tick", "research.sources"}
IMPLEMENTED = {**{f: "S1" for f in S1_FAMILIES}, **{f: "S2" for f in S2_FAMILIES},
               **{f: "S3" for f in S3_IMPLEMENTED}, **{f: "S4" for f in S4_IMPLEMENTED},
               **{f: "S5" for f in S5_IMPLEMENTED}, **{f: "S6" for f in S6_IMPLEMENTED},
               **{f: "S7" for f in S7_IMPLEMENTED}, **{f: "S8" for f in S8_IMPLEMENTED}}


def test_every_scenario_has_a_reference_golden_and_only_implemented_slices_have_a_target():
    scenarios = [load(p) for p in sorted((COMPARE / "scenarios").glob("*.json"))]
    assert {s["family"] for s in scenarios} == (S0_FAMILIES | S1_FAMILIES | S2_FAMILIES | S3_FAMILIES
                                                | S4_FAMILIES | S5_FAMILIES | S6_FAMILIES
                                                | S7_FAMILIES | S8_FAMILIES)
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


# ---- declared intended differences (owner, 2026-10-01): asserted, never masks ----
def _run_module():
    import importlib.util
    spec = importlib.util.spec_from_file_location("compare_run_for_intended", COMPARE / "run.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_an_intended_difference_is_asserted_exactly_and_nothing_else_is_masked():
    run = _run_module()
    golden = {"ports": {"default": {"kinds": ["process", "w_b"], "ports": {"process": 1, "w_b": 2}}, "other": 3}}
    declared = [{"path": "$.ports.default.ports.w_b", "op": "absent", "authority": "user 2026-09-28"},
                {"path": "$.ports.default.kinds", "op": "remove_item", "item": "w_b", "authority": "user 2026-09-28"}]
    expected, problems = run.apply_intended_differences(golden, declared)
    assert problems == [] and expected == {"ports": {"default": {"kinds": ["process"], "ports": {"process": 1}},
                                                     "other": 3}}
    assert golden["ports"]["default"]["ports"]["w_b"] == 2  # the reference golden itself is never rewritten
    # a target that still HAS the retired key is not equal to the expectation (the difference is asserted)
    assert expected != golden


def test_stale_or_invalid_declarations_are_problems():
    run = _run_module()
    golden = {"a": {"b": [1]}}
    for bad in ({"path": "$.a.c", "op": "absent", "authority": "x"},            # not in the golden: stale
                {"path": "$.a.b", "op": "remove_item", "item": 2, "authority": "x"},  # item not present once
                {"path": "$.a.b", "op": "replace", "authority": "x"},           # unknown op
                {"path": "$.a.b", "op": "absent", "authority": ""}):            # no authority
        _, problems = run.apply_intended_differences(golden, [bad])
        assert problems, bad


def test_a_pair_family_target_side_gets_its_own_fresh_pair(tmp_path, monkeypatch):
    """The pair families fix their database names "on a fresh pair per run" (S7 restore design §2): the target side
    runs on a NEW pair, started after the reference side's pair is removed, never on the pair the reference seeded."""
    run = _run_module()
    events = []

    class Pair:
        made = 0

        def __init__(self, work, dump):
            Pair.made += 1
            self.n = Pair.made

        def description(self):
            return f"pair-{self.n}"

        def __enter__(self):
            events.append(("enter", self.n))
            return self

        def __exit__(self, *exc):
            events.append(("exit", self.n))
            return False

    target, golden = tmp_path / "target_driver.py", tmp_path / "golden.json"
    target.write_text("", encoding="utf-8")
    golden.write_text("{}", encoding="utf-8")
    (tmp_path / "venv-ref" / "bin").mkdir(parents=True)
    (tmp_path / "venv-ref" / "bin" / "python").write_text("", encoding="utf-8")
    scenario = {"family": "x.pair", "slice": "S7", "requires": "disposable-postgresql-pair",
                "reference_driver": "unused.py", "target_driver": str(target), "golden": str(golden)}
    monkeypatch.setattr(run, "scenarios", lambda: [scenario])
    monkeypatch.setattr(run, "SCRATCH", tmp_path)
    monkeypatch.setattr(run, "PostgresPair", Pair)
    monkeypatch.setattr(run, "run_driver", lambda python, driver, work, extra, use_bwrap, binds=None: (
        events.append(("reference", extra[run.PG_PAIR_ENV])) or {"origin": {}, "result": {}}))
    monkeypatch.setattr(run, "run_target", lambda path, work, extra, use_bwrap: (
        events.append(("target", extra[run.PG_PAIR_ENV])) or {"origin": {}, "result": {}, "side": "target"}))
    run.run(False, False, [], pg=True)
    assert events == [("enter", 1), ("reference", "pair-1"), ("exit", 1),
                      ("enter", 2), ("target", "pair-2"), ("exit", 2)]
