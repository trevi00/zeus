"""S9 batch L2-B4: the collector (U3) and the projection's local facts (U5b) move out of M7 into the observation context.

`observation.application.observations` gains M7's `Collector`, `orphan_report` and `status_report` VERBATIM after the S4 part (its import block and its
§3.2 header are the only changes); `observation.adapters.monitoring_observations` is M7's `adapters/monitoring_observations.py` with its import block,
the lazy `SpoolDirectory` import and its header changed. M7 is read only as text through `git show e38aa722:...` (the S4 part through `git show` of the
base commit) and compared by AST, never imported: both packages are named `codex_harness`. Behaviour is compared by the recorded `observation.collector` and
`observation.local_facts` goldens (both families are target-equal); this file pins what a golden cannot: the AST against M7 and against the base, the
import homes (no `research.domain.dge`, no M7 path), the single writer of the six observation buckets, the layer rules, the call shapes, the order of
acknowledgement after commit with recording fakes, and the read-only projection.

M7 tests this batch does NOT port yet (the S9 ported suite is a later step): from `test_observations.py`
`test_collector_deduplicates_redelivery_and_isolates_conflicting_redelivery`, `test_sink_outage_is_observed_locally_and_alerts_replay_after_recovery`,
`test_stale_observation_after_lease_expiry_is_kept_but_changes_no_task_state`, `test_orphan_report_distinguishes_live_heartbeat_from_missing_end`,
`test_restart_uses_a_new_namespace_and_status_report_is_informational`, `test_canary_secret_never_reaches_spool_sink_health_or_status`; from
`test_observation_review.py` `test_continuous_production_and_collection_never_saturates`,
`test_sink_outage_bounds_the_spool_and_recovery_resumes_without_loss_or_duplicates`,
`test_reconcile_decision_correlation_and_schema_errors_never_carry_the_canary`; from `test_observation_review2.py`
`test_live_origin_new_alert_survives_a_stale_inheritor`, `test_segment_10000_is_collected_in_order`,
`test_finished_run_leftovers_are_pruned_and_a_final_truncated_tail_is_quarantined`, `test_dead_run_without_marker_is_finalized_after_retention`,
`test_known_token_shape_is_refused_as_identifier`; from `test_observation_review3.py` `test_pending_alerts_without_spool_records_replay_after_recovery`,
`test_pending_only_replay_survives_a_failed_commit_and_a_concurrent_inheritor`, `test_second_writer_for_the_same_run_is_refused`; from
`test_observation_review4.py` `test_owner_record_after_a_refused_writers_close_is_collected`,
`test_dead_run_with_an_unacknowledged_record_is_collected_then_pruned`; from `test_observation_review5.py`
`test_gc_waits_for_a_registering_writer_and_keeps_its_active_segment`, `test_gc_that_runs_before_registration_leaves_the_writer_a_valid_path`; from
`test_observation_boundaries.py` `test_structured_output_retry_exhaustion_is_named_apart_and_bound_to_its_artifact`,
`test_a_failed_inspection_is_unknown_and_its_exception_text_reaches_no_surface`,
`test_the_boundary_events_reach_the_monitoring_projection_and_replay_adds_no_second_count`; from `test_observation_wiring.py`
`test_l04_settlement_write_failure_keeps_termination_evidence_and_refuses_blind_rerun`; from `test_monitoring_observations.py`
`test_priority_order_dedup_and_unknown_rows`, `test_bounded_sample_reports_truncation_and_row_cap`,
`test_script_like_labels_and_credentials_are_redacted_and_bounded`, `test_collection_alerts_quarantine_terminations_and_operations_are_separate`,
`test_local_spool_health_is_read_only_and_unavailable_when_missing`, `test_projection_never_writes_through_the_read_only_store` and (U7, the monitoring
collector) `test_collect_adds_observations_only_with_runtime_and_keeps_other_sources`.
"""

from __future__ import annotations

import ast
import contextlib
import copy
import inspect
import re
import subprocess
from pathlib import Path

import import_rules
import pytest
from _layout import REPO, TARGET

from codex_harness.kernel.ids import utcnow
from codex_harness.kernel.policy import POLICY
from codex_harness.observation import ports
from codex_harness.observation.adapters import monitoring_observations as mon
from codex_harness.observation.adapters import observation_spool
from codex_harness.observation.application import observations as obs
from codex_harness.observation.domain import observation as domain

SRC = TARGET / "src" / "codex_harness"
SOURCE = "e38aa722"
BASE = "0aa71de3948485547a5191943c2fe39d9de353a0"
M7_OBS = "src/codex_harness/application/observations.py"
M7_MON = "src/codex_harness/adapters/monitoring_observations.py"
OUT_OBS = "target/src/codex_harness/observation/application/observations.py"
OBS_TEXT = Path(obs.__file__).read_text(encoding="utf-8")
MON_TEXT = Path(mon.__file__).read_text(encoding="utf-8")
BUCKET_NAMES = ("AUDIT_BUCKET", "EVENT_BUCKET", "QUARANTINE_BUCKET", "ALERT_BUCKET", "COLLECTION_BUCKET", "TERMINATION_BUCKET")
BUCKETS = {getattr(obs, name) for name in BUCKET_NAMES}
FORBIDDEN_HOMES = ("codex_harness.adapters", "codex_harness.domain", "codex_harness.application", "codex_harness.ports", "codex_harness.entry",
                   "codex_harness.intake", "codex_harness.research", "codex_harness.evidence", "codex_harness.execution")


def show(rev, path):
    return subprocess.run(["git", "-C", str(REPO), "show", f"{rev}:{path}"], check=True, capture_output=True, text=True).stdout


def statements(src):
    out = {}
    for i, node in enumerate(ast.parse(src).body):
        if isinstance(node, (ast.Import, ast.ImportFrom)) or (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)):
            continue
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            name = node.name
        elif isinstance(node, ast.Assign):
            name = node.targets[0].id
        else:
            name = i
        out[name] = node
    return out


def from_imports(tree):
    return {n.module: sorted(a.name for a in n.names) for n in tree.body if isinstance(n, ast.ImportFrom)}


class InverseOfLazyImport(ast.NodeTransformer):
    """The inverse of R-m1 on the target AST: the lazy import inside `local_facts` back to M7's module path."""

    def visit_ImportFrom(self, node):
        if node.module == "codex_harness.observation.adapters.observation_spool":
            node.module = "codex_harness.adapters.observation_spool"
        return node


# ---- U3: the collector half of observations.py -------------------------------------------------

def test_every_statement_is_m7s_in_m7s_order_and_the_s4_part_is_the_bases():
    ours, theirs, base = statements(OBS_TEXT), statements(show(SOURCE, M7_OBS)), statements(show(BASE, OUT_OBS))
    assert list(ours) == list(theirs)
    assert list(ours)[-3:] == ["Collector", "orphan_report", "status_report"]
    for name, node in theirs.items():
        assert ast.dump(ours[name]) == ast.dump(node), name
    assert list(ours)[:len(base)] == list(base) and len(base) == len(ours) - 3
    for name, node in base.items():
        assert ast.dump(ours[name]) == ast.dump(node), name


def test_the_s4_part_text_is_the_bases_byte_for_byte_after_the_import_block():
    base = show(BASE, OUT_OBS)
    start = "AUDIT_BUCKET = "
    assert OBS_TEXT[OBS_TEXT.index(start):].startswith(base[base.index(start):].rstrip("\n"))
    assert OBS_TEXT.endswith(show(SOURCE, M7_OBS)[show(SOURCE, M7_OBS).index("class Collector:"):])


def test_the_header_keeps_m7s_docstring_and_names_the_collector_half():
    doc = ast.get_docstring(ast.parse(OBS_TEXT))
    assert ast.get_docstring(ast.parse(show(SOURCE, M7_OBS))) in doc
    for field in ("Layer: application", "Context: observation", "Owns:", "Does not own:", "Entry points:", "Contracts: INV-OBSERVATION-001"):
        assert field in doc, field
    entry_points = doc.split("Entry points:")[1].split("Contracts:")[0]
    for name in ("Observer", "Collector", "Collector.collect", "Collector.replay_pending_alerts", "orphan_report", "status_report", "BUCKETS"):
        assert name in entry_points, name
    assert "Does not own: Collector" not in doc
    assert all(hasattr(obs, name) for name in ("Collector", "orphan_report", "status_report"))


def test_observations_import_homes_resolve_in_the_target_alone():
    tree = ast.parse(OBS_TEXT)
    assert from_imports(tree) == {
        "__future__": ["annotations"], "collections": ["Counter"], "datetime": ["datetime"], "codex_harness.kernel.errors": ["ContractError", "require"],
        "codex_harness.kernel.ids": ["digest", "utcnow"], "codex_harness.kernel.policy": ["POLICY"],
        "codex_harness.observation.domain.observation": ["REFERENCE", "build_event", "content_hash", "execution_identity", "is_business_message",
                                                         "lease_identity", "opaque_identifier", "redact_text"],
        "codex_harness.observation.ports": ["SpoolFull"]}
    assert sorted(a.name for n in tree.body if isinstance(n, ast.Import) for a in n.names) == ["os", "platform", "sys", "threading", "time"]
    modules = [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
    assert not [m for m in modules if m.startswith(FORBIDDEN_HOMES)]
    assert obs.is_business_message is domain.is_business_message and obs.REFERENCE is domain.REFERENCE and obs.content_hash is domain.content_hash
    assert obs.POLICY is POLICY and obs.datetime.__module__ == "datetime"
    for banned in ("subprocess", "multiprocessing", "Popen"):
        assert banned not in OBS_TEXT


def test_collector_and_report_call_shapes_are_m7s_and_the_directory_stays_untyped():
    init = inspect.signature(obs.Collector.__init__)
    assert list(init.parameters) == ["self", "store", "directory", "validate", "observer", "batch", "clock"]
    assert [n for n, p in init.parameters.items() if p.kind is p.KEYWORD_ONLY] == ["validate", "observer", "batch", "clock"]
    assert init.parameters["batch"].default == POLICY.observation_collect_batch and init.parameters["clock"].default is utcnow
    assert init.parameters["observer"].default is None and init.parameters["directory"].annotation is inspect.Parameter.empty
    assert list(inspect.signature(obs.status_report).parameters) == ["store", "directory", "observer"]
    assert inspect.signature(obs.status_report).parameters["directory"].annotation is inspect.Parameter.empty
    assert list(inspect.signature(obs.orphan_report).parameters) == ["tx", "now"]
    assert list(inspect.signature(obs.Collector.collect).parameters) == ["self", "prune"]
    assert list(inspect.signature(obs.Collector.replay_pending_alerts).parameters) == ["self"]
    assert list(inspect.signature(mon.observation_facts).parameters) == ["store", "runtime", "now"]
    assert list(inspect.signature(mon.local_facts).parameters) == ["runtime"]


# ---- the acknowledgement follows the commit, shown with recording fakes --------------------------

class Log(list):
    pass


class Tx:
    def __init__(self, log):
        self.log = log

    def get(self, bucket, key):
        return None

    def put(self, bucket, key, body):
        self.log.append(("put", bucket))

    def scan(self, bucket):
        return []


class Store:
    def __init__(self, log, fail_commit=False):
        self.log, self.fail_commit = log, fail_commit

    @contextlib.contextmanager
    def transaction(self):
        yield Tx(self.log)
        if self.fail_commit:
            raise OSError("commit failed")
        self.log.append(("commit",))


class Directory:
    def __init__(self, log, records):
        self.log, self.records, self.offset = log, records, 0

    def spool_files(self):
        return [Path("r.0000.jsonl")]

    def acknowledged(self, path):
        return self.offset

    def read(self, path, offset):
        end = offset
        for event in self.records:
            yield end, end + 10, "ok", "event", event, None
            end += 10

    def acknowledge(self, path, offset, consumed):
        self.log.append(("acknowledge", offset, consumed))

    def run_finished(self, run):
        return False

    def reclaim(self, path):
        self.log.append(("reclaim",))
        return False

    def prune(self):
        self.log.append(("prune",))
        return {}


def event(identity):
    return {"event_id": identity, "event_type": "general.process_started", "outcome": "observed"}


def test_the_offset_is_acknowledged_only_after_the_sink_commit():
    log = Log()
    collector = obs.Collector(Store(log), Directory(log, [event("e1"), event("e2")]), validate=lambda e: e, clock=lambda: "2026-01-01T00:00:00+00:00")
    receipt = collector.collect(prune=False)
    assert receipt["inserted"] == 2 and receipt["records"] == 2
    assert [step[0] for step in log] == ["put", "put", "put", "commit", "acknowledge", "reclaim"]
    assert log[0][1] == obs.EVENT_BUCKET and log[2][1] == obs.COLLECTION_BUCKET and log[4] == ("acknowledge", 20, 2)


def test_a_failed_commit_acknowledges_nothing_and_is_counted_not_raised():
    log = Log()
    collector = obs.Collector(Store(log, fail_commit=True), Directory(log, [event("e1")]), validate=lambda e: e, clock=lambda: "2026-01-01T00:00:00+00:00")
    receipt = collector.collect(prune=False)
    assert receipt["sink_failures"] == 1 and receipt["inserted"] == 0 and receipt["per_file"] == []
    assert not [step for step in log if step[0] in ("acknowledge", "reclaim", "commit")]


def test_prune_runs_after_the_files_and_its_failure_is_reported_not_raised():
    log = Log()
    collector = obs.Collector(Store(log), Directory(log, []), validate=lambda e: e, clock=lambda: "2026-01-01T00:00:00+00:00")
    assert collector.collect()["pruned_runs"] == 0 and ("prune",) in log

    class Failing(Directory):
        def prune(self):
            raise OSError("boom")
    assert obs.Collector(Store(Log()), Failing(Log(), []), validate=lambda e: e).collect()["pruned_files"] == 0


# ---- the single writer of the six observation buckets and the layer rules -----------------------

def put_sites(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    sites = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "put" and node.args:
            first = node.args[0]
            if (isinstance(first, ast.Name) and first.id in BUCKET_NAMES) or (isinstance(first, ast.Constant) and first.value in BUCKETS):
                sites.append(node.lineno)
    return sites


def test_the_six_buckets_are_declared_and_written_only_by_the_observation_application():
    assert BUCKETS <= set(ports.OWNED_BUCKETS) and len(BUCKETS) == 6
    writers = {p.relative_to(SRC).as_posix() for p in SRC.rglob("*.py") if put_sites(p)}
    assert writers == {"observation/application/observations.py"}
    assert import_rules.single_writer_violations(import_rules.Tree(TARGET / "src")) == []
    # the literal form of the same rule: no other module spells a bucket name in a `tx.put(...)`
    for path in SRC.rglob("*.py"):
        if path.name != "observations.py":
            assert not re.search(r"""\.put\(\s*["']observation_(?:audit|quarantine|alerts|collections|terminations)["']""", path.read_text(encoding="utf-8")), path


def test_no_layer_or_cycle_violation_touches_either_module():
    violations = import_rules.check(TARGET / "src")
    assert [v for v in violations if "observation.application.observations" in v.module or "monitoring_observations" in v.module] == []
    assert violations == []


# ---- U5b: the projection's local facts ----------------------------------------------------------

def test_the_projection_is_m7s_modulo_its_import_homes_and_the_lazy_import():
    ours, theirs = statements(MON_TEXT), statements(show(SOURCE, M7_MON))
    assert list(ours) == list(theirs)
    changed = []
    for name, node in theirs.items():
        if ast.dump(ours[name]) == ast.dump(node):
            continue
        changed.append(name)
        assert ast.dump(InverseOfLazyImport().visit(copy.deepcopy(ours[name]))) == ast.dump(node), name
    assert changed == ["local_facts"]
    assert list(ours) == ["SCHEMA", "BUCKET_LIMIT", "PAGE", "ROW_LIMIT", "HIGH_LIMIT", "OPERATION_LIMIT", "TEXT_LIMIT", "REFS_LIMIT", "SEVERITY_RANK", "CATEGORY_RANK",
                          "CATEGORY_LABELS", "PENDING_TERMINATION", "OPERATION_BUCKET", "text", "parse_time", "scan_bounded", "project_event", "sort_key",
                          "merge_events", "collection_facts", "project_operation", "local_facts", "observation_facts"]


def test_the_projection_header_keeps_m7s_docstring_first():
    doc = ast.get_docstring(ast.parse(MON_TEXT))
    assert doc.startswith(ast.get_docstring(ast.parse(show(SOURCE, M7_MON))) + "\n\nLayer: adapters\nContext: observation\n")
    for field in ("Owns:", "Does not own:", "Entry points:", "Contracts: INV-OBSERVATION-001", "Moved from M7", SOURCE, "R-m0", "R-m1", "R-mh"):
        assert field in doc, field
    entry_points = doc.split("Entry points:")[1].split("\n")[0]
    for name in ("observation_facts", "local_facts", "scan_bounded", "project_event", "merge_events"):
        assert name in entry_points


def test_the_projection_import_homes_are_the_target_homes_and_never_research_dge():
    tree = ast.parse(MON_TEXT)
    assert from_imports(tree) == {
        "collections": ["Counter"], "datetime": ["datetime", "timezone"], "pathlib": ["Path"],
        "codex_harness.observation.application.observations": ["ALERT_BUCKET", "AUDIT_BUCKET", "COLLECTION_BUCKET", "EVENT_BUCKET", "QUARANTINE_BUCKET",
                                                               "TERMINATION_BUCKET"],
        "codex_harness.observation.domain.observation": ["CATEGORIES", "REFERENCE", "SEVERITIES", "redact_text"]}
    modules = [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
    assert not [m for m in modules if m.startswith(FORBIDDEN_HOMES)]
    assert "research.domain.dge" not in MON_TEXT and "research" not in MON_TEXT and "frontdesk" not in MON_TEXT
    assert mon.SEVERITIES is domain.SEVERITIES and mon.CATEGORIES is domain.CATEGORIES and mon.REFERENCE is domain.REFERENCE
    assert mon.redact_text is domain.redact_text
    for name in BUCKET_NAMES:
        assert getattr(mon, name) is getattr(obs, name)
    assert mon.SEVERITY_RANK == {"debug": 0, "info": 1, "warning": 2, "error": 3, "critical": 4}


def test_the_only_lazy_import_is_the_target_spool_directory():
    lazy = [n for n in ast.walk(ast.parse(MON_TEXT)) if isinstance(n, ast.ImportFrom) and n.col_offset > 0]
    assert [(n.module, [a.name for a in n.names]) for n in lazy] == [("codex_harness.observation.adapters.observation_spool", ["SpoolDirectory"])]


def test_local_facts_builds_the_target_spool_directory_for_the_runtime_observations_directory(tmp_path, monkeypatch):
    seen = []

    class Recording(observation_spool.SpoolDirectory):
        def __init__(self, root):
            seen.append(Path(root))
            super().__init__(root)
    monkeypatch.setattr(observation_spool, "SpoolDirectory", Recording)
    (tmp_path / "observations").mkdir()
    assert mon.local_facts(tmp_path)["status"] == "ok"
    assert seen == [tmp_path / "observations"]
    assert mon.local_facts(None) == {"status": "unavailable", "reason": "runtime_not_configured"}
    assert mon.local_facts(tmp_path / "missing") == {"status": "unavailable", "reason": "directory_missing"}
    assert seen == [tmp_path / "observations"]


READ_ONLY_VERBS = {"put", "put_node", "put_edge", "acknowledge", "prune", "reclaim", "write_health", "write_pending_alerts", "record_termination",
                   "resolve_termination", "atomic_write", "acquire", "unlink", "write_text", "write_bytes", "mkdir", "emit", "alert", "audit", "collect"}


def test_the_projection_calls_no_mutating_method_and_reads_only_through_the_read_methods():
    called = {n.func.attr for n in ast.walk(ast.parse(MON_TEXT)) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    assert called.isdisjoint(READ_ONLY_VERBS), called & READ_ONLY_VERBS
    assert {"spool_files", "read_health", "pending_terminations", "read_pending_alerts", "unacknowledged_bytes", "entries", "transaction"} <= called


def test_observation_facts_reads_through_one_transaction_and_writes_nothing():
    class Store:
        def __init__(self):
            self.opened, self.puts = 0, 0

        @contextlib.contextmanager
        def transaction(self):
            self.opened += 1
            outer = self

            class Reader:
                def entries(self, bucket, after, limit):
                    return []

                def put(self, *args):
                    outer.puts += 1
            yield Reader()
    store = Store()
    facts = mon.observation_facts(store, None, mon.datetime(2026, 9, 18, 12, tzinfo=mon.timezone.utc))
    assert store.opened == 1 and store.puts == 0
    assert facts["schema"] == "harness-monitor-observations.v1" and facts["authority"] == "informational_only"
    assert sorted(facts["sample"]["buckets"]) == sorted([obs.AUDIT_BUCKET, obs.EVENT_BUCKET, obs.ALERT_BUCKET, obs.QUARANTINE_BUCKET,
                                                         obs.COLLECTION_BUCKET, obs.TERMINATION_BUCKET, "operations"])
    with pytest.raises(OSError):
        class Broken:
            def transaction(self):
                raise OSError("down")
        mon.observation_facts(Broken(), None, None)
