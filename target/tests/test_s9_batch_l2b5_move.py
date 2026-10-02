"""S9 batch L2-B5: the core collectors (U6) move out of M7 `adapters/monitoring.py` into `observation.adapters.collectors`.

The module is M7's U6 definitions VERBATIM in SOURCE order (the four line groups 32-275, 428-432, 497-925 and 966-970) with only the import block, the §3.2
header and R-c1 changed: in `lane_view` the lazy `application.worker_sessions` bucket import becomes the V9 literal `SESSIONS = 'worker_sessions'` and the lazy
`status_view` import comes from `execution.domain.worker_sessions`. M7 is read only as text through `git show e38aa722:...` and compared by AST, never imported:
both packages are named `codex_harness`. Behaviour is compared by the recorded `observation.collectors_core` golden (target-equal); this file pins what a golden
cannot: the AST against M7, the exact U6 names in SOURCE order, the import homes (none of U7's), R-c1's literal equal to the owner's `BUCKET`, no `put`/`graph`
reachable through the read-only wrappers, no new spawn site and the layer rules.

M7 tests this batch does NOT port yet (the S9 ported suite is a later step): from `test_monitoring_activity.py`
`test_only_fixed_vocabularies_and_builtin_tool_names_survive`, `test_codex_occurrence_is_validated_epoch_millis_and_claude_has_none`,
`test_membership_is_only_the_bound_recent_list`, `test_two_lanes_never_share_an_artifact_root`,
`test_malformed_and_missing_receipts_stay_explicit_beside_a_valid_one`, `test_malformed_only_progress_says_so_and_never_reads_the_malformed_ring`,
`test_a_wrong_typed_consulted_field_is_invalid_shape_never_an_exception`,
`test_wrong_typed_refs_and_a_failing_read_stay_single_entries_beside_readable_ones`, `test_only_the_last_six_refs_are_read_and_the_body_budget_is_exact`,
`test_integrity_encoding_numbers_depth_links_and_fifos_are_refused_without_writes`,
`test_retention_order_is_kept_duplicates_read_once_and_only_last_record_has_sequence`, `test_active_rows_and_recently_completed_rows_only`,
`test_progress_of_another_generation_or_attempt_is_never_shown`; from `test_progress_activity.py`
`test_a_synchronized_compact_ring_is_read_instead_of_the_raw_ring_and_raw_ref_is_never_followed`,
`test_the_compact_ring_is_selected_only_when_it_is_synchronized_with_the_raw_sequence`, `test_the_lane_view_projects_fixed_s1a_labels_and_the_recorded_drop_count`,
`test_a_compact_ring_that_fails_entirely_never_falls_back_to_raw_and_raw_ref_is_never_read`; from `test_monitoring.py`
`test_persisted_measurements_are_latest_per_metric_and_honest_when_empty`, `test_container_scope_rejects_invalid_configuration`,
`test_audit_progress_keeps_missing_checkpoints_unknown_and_pause_visible`, `test_credential_redaction`; and (U7, they call `lane_session_facts`, `collect`,
`docker_facts` or the monitor CLI) `test_one_unreadable_lane_root_leaves_the_other_lane_and_every_session_fact_intact`,
`test_a_bad_ref_and_a_bad_receipt_between_good_ones_keep_the_lane_and_its_session_facts`,
`test_a_row_whose_activity_cannot_be_projected_is_unavailable_and_keeps_its_session_facts`,
`test_read_only_store_and_reader_refuse_writes_while_collection_works`, `test_container_scope_unset_keeps_compose_and_named_mode_is_exact` and
`test_collector_entrypoint_is_read_only_and_needs_no_executor`.
"""

from __future__ import annotations

import ast
import copy
import re
import subprocess
from pathlib import Path

import import_rules
import pytest

from codex_harness.execution.application import worker_sessions as owner
from codex_harness.observation.adapters import collectors
from codex_harness.storage.adapters.memory_store import MemoryStore

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "target" / "src" / "codex_harness"
SOURCE = "e38aa722"
M7_MON = "src/codex_harness/adapters/monitoring.py"
TEXT = Path(collectors.__file__).read_text(encoding="utf-8")
U6_NAMES = ["CONTAINER_NAME", "MAX_CONTAINERS", "safe_text", "ReadOnlyTransaction", "ReadOnlyStore", "ReadOnlyArtifacts", "ReadOnlyService", "read_only",
            "container_scope", "parse_observed", "persisted_measurements", "DatabaseFacts", "audit_progress",
            "LANE_SESSIONS_SCHEMA", "LANE_SESSION_LIMIT", "ACTIVE_EXECUTION", "UNINSTRUMENTED",
            "ACTIVITY_REFS", "ACTIVITY_BODY_BYTES", "RECENT_TERMINAL_SECONDS", "TERMINAL_EXECUTION", "ARTIFACT_REF", "CLAUDE_LABELS", "CODEX_LABELS", "PLAIN_STATUSES",
            "ENVELOPE_KEYS", "_optional_strings", "ArtifactReader", "_strict_json", "_epoch_ms", "project_receipt", "_aware", "execution_activity", "COMPACT_ONLY",
            "_failed_entry", "_compact_selected", "_compact_activity", "lane_artifact_resolver", "_execution_view", "lane_view", "scope_label"]
U7_NAMES = {"docker_stats", "docker_facts", "redis_facts", "fleet_facts", "research_program_facts", "portfolio_facts", "fleet_backlog_facts", "host_delivery_facts",
            "worker_session_facts", "continuation_facts", "LANE_SNAPSHOT_BEGIN", "LaneSnapshotStore", "LaneSnapshotTransaction", "lane_resolver", "lane_session_facts",
            "discovery_pressure_facts", "collect"}
U7_IMPORTED = {"RedisBus", "run_process", "Fleet", "FleetRefused", "Monitoring", "observation_facts", "ThreadPoolExecutor"}
FORBIDDEN_HOMES = ("codex_harness.adapters", "codex_harness.domain", "codex_harness.application", "codex_harness.ports", "codex_harness.entry", "codex_harness.intake",
                   "codex_harness.evidence", "codex_harness.delivery", "codex_harness.coordination")


def show(rev, path):
    return subprocess.run(["git", "-C", str(REPO), "show", f"{rev}:{path}"], check=True, capture_output=True, text=True).stdout


def names_of(node):
    if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
        return (node.name,)
    if isinstance(node, ast.Assign):
        return tuple(n.id for t in node.targets for n in ast.walk(t) if isinstance(n, ast.Name))
    return ()


def statements(src):
    out = {}
    for node in ast.parse(src).body:
        if names_of(node):
            out[names_of(node)[0]] = node
    return out


def from_imports(tree):
    return {n.module: sorted(a.name for a in n.names) for n in tree.body if isinstance(n, ast.ImportFrom)}


class InverseOfR_c1(ast.NodeTransformer):
    """The inverse of R-c1 on the target AST: the literal back to M7's lazy bucket import and the execution-domain home back to M7's."""

    def visit_Assign(self, node):
        if len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) and node.targets[0].id == "SESSIONS":
            return ast.parse("from codex_harness.application.worker_sessions import BUCKET as SESSIONS").body[0]
        return node

    def visit_ImportFrom(self, node):
        if node.module == "codex_harness.execution.domain.worker_sessions":
            node.module = "codex_harness.domain.worker_sessions"
        return node


# ---- the statements ----------------------------------------------------------------------------

def test_exactly_the_u6_names_are_present_in_source_order():
    ours, theirs = statements(TEXT), statements(show(SOURCE, M7_MON))
    assert list(ours) == U6_NAMES
    assert list(ours) == [n for n in theirs if n in U6_NAMES]
    assert not U7_NAMES & set(ours) and not U7_NAMES & set(dir(collectors))
    assert set(theirs) - set(ours) == U7_NAMES
    assert {n for n in dir(collectors) if not n.startswith("__")} >= set(U6_NAMES)


def test_every_u6_statement_is_m7s_modulo_r_c1():
    ours, theirs = statements(TEXT), statements(show(SOURCE, M7_MON))
    changed = []
    for name in U6_NAMES:
        if ast.dump(ours[name]) == ast.dump(theirs[name]):
            continue
        changed.append(name)
        assert ast.dump(InverseOfR_c1().visit(copy.deepcopy(ours[name]))) == ast.dump(theirs[name]), name
    assert changed == ["lane_view"]


def test_the_text_is_m7s_four_line_groups_byte_for_byte_but_r_c1():
    lines = show(SOURCE, M7_MON).split("\n")
    groups = ["\n".join(lines[a - 1:b]) for a, b in ((32, 275), (428, 432), (497, 925), (966, 970))]
    body = TEXT[TEXT.index("CONTAINER_NAME = "):]
    old = ("    from codex_harness.application.worker_sessions import BUCKET as SESSIONS\n"
           "    from codex_harness.domain.worker_sessions import status_view\n")
    assert groups[2].count(old) == 1
    expected = "\n\n\n".join(groups[:2] + [groups[2].replace(old, "@@")] + groups[3:]) + "\n"
    assert body.count("SESSIONS = 'worker_sessions'") == 1
    pieces = expected.split("@@")
    assert len(pieces) == 2 and body.startswith(pieces[0]) and body.endswith(pieces[1])
    middle = body[len(pieces[0]):len(body) - len(pieces[1])]
    assert middle.splitlines()[1] == "    from codex_harness.execution.domain.worker_sessions import status_view"
    assert middle.splitlines()[0].startswith("    SESSIONS = 'worker_sessions'") and len(middle.splitlines()) == 2


def test_the_header_keeps_m7s_docstring_first_and_names_u6_not_u7():
    doc = ast.get_docstring(ast.parse(TEXT))
    assert doc.startswith(ast.get_docstring(ast.parse(show(SOURCE, M7_MON))) + "\n\nLayer: adapters\nContext: observation\n")
    for field in ("Owns:", "Does not own:", "Entry points:", "Contracts: INV-OBSERVATION-001", "Moved from M7", SOURCE, "R-c0", "R-c1", "R-ch"):
        assert field in doc, field
    entry_points = doc.split("Entry points:")[1].split("\n")[0]
    for name in ("ReadOnlyStore", "DatabaseFacts", "ArtifactReader", "project_receipt", "execution_activity", "lane_view", "scope_label"):
        assert name in entry_points
    assert not [name for name in U7_NAMES if name in entry_points]


# ---- the import homes and R-c1 -----------------------------------------------------------------

def test_the_import_homes_resolve_in_the_target_alone_and_none_is_u7s():
    tree = ast.parse(TEXT)
    assert from_imports(tree) == {
        "collections": ["Counter"], "contextlib": ["contextmanager"], "dataclasses": ["asdict"], "datetime": ["datetime", "timezone"], "pathlib": ["Path"],
        "codex_harness.execution.domain.progress_activity": ["BUILTIN_TOOLS", "CODEX_ITEM_TYPES", "fixed_completed_status", "fixed_completed_type", "fixed_last_event",
                                                             "validate_receipt"],
        "codex_harness.kernel.errors": ["ContractError"], "codex_harness.research.domain.council": ["TASK_STATUSES"]}
    assert sorted(a.name for n in tree.body if isinstance(n, ast.Import) for a in n.names) == ["json", "re"]
    modules = [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
    assert not [m for m in modules if m.startswith(FORBIDDEN_HOMES)]
    imported = {a.asname or a.name for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom)) for a in n.names}
    assert not U7_IMPORTED & imported
    lazy = sorted(a.name for n in ast.walk(tree) if isinstance(n, ast.Import) and n not in tree.body for a in n.names)
    assert lazy == ["hashlib", "os", "stat"]
    from codex_harness.execution.domain import progress_activity
    from codex_harness.execution.domain import worker_sessions as domain_sessions
    from codex_harness.kernel import errors
    from codex_harness.research.domain import council
    assert collectors.BUILTIN_TOOLS is progress_activity.BUILTIN_TOOLS and collectors.validate_receipt is progress_activity.validate_receipt
    assert collectors.ContractError is errors.ContractError and collectors.TASK_STATUSES is council.TASK_STATUSES
    assert callable(domain_sessions.status_view)


def test_r_c1_literal_equals_the_owners_bucket_and_status_view_is_the_execution_domains():
    lane_view = next(n for n in ast.parse(TEXT).body if isinstance(n, ast.FunctionDef) and n.name == "lane_view")
    literal = [n for n in lane_view.body if isinstance(n, ast.Assign) and [t.id for t in n.targets if isinstance(t, ast.Name)] == ["SESSIONS"]]
    assert len(literal) == 1 and isinstance(literal[0].value, ast.Constant) and literal[0].value.value == owner.BUCKET == "worker_sessions"
    lazy = [n for n in lane_view.body if isinstance(n, ast.ImportFrom)]
    assert [(n.module, [a.name for a in n.names]) for n in lazy] == [("codex_harness.execution.domain.worker_sessions", ["status_view"])]
    modules = [n.module or "" for n in ast.walk(ast.parse(TEXT)) if isinstance(n, ast.ImportFrom)]
    assert not [m for m in modules if "application" in m.split(".")]


class Recording:
    def __init__(self, inner):
        self.inner, self.scanned = inner, []

    def transaction(self):
        import contextlib
        owner_ = self

        @contextlib.contextmanager
        def cm():
            with owner_.inner.transaction() as tx:
                class Tx:
                    def scan(self, bucket):
                        owner_.scanned.append(bucket)
                        return tx.scan(bucket)
                yield Tx()
        return cm()


def test_lane_view_reads_the_worker_session_rows_through_the_literal_bucket():
    store = MemoryStore()
    with store.transaction() as tx:
        tx.put(owner.BUCKET, "job", {"task_id": "job", "state": "checkpointed"})
        tx.put("operations", "op", {"id": "op", "assignment_message_id": "t", "continuation": {"session": {"task_id": "job"}}})
        tx.put("tasks", "t", {"id": "t", "status": "queued", "created_at": "2026-09-28T00:00:00+00:00"})
    recording = Recording(store)
    view = collectors.lane_view(recording, None, collectors.datetime(2026, 9, 28, 1, tzinfo=collectors.timezone.utc))
    assert recording.scanned == ["operations", "tasks", "decisions_pending", "execution_progress", "invocation_reservations", owner.BUCKET]
    assert view["worker_sessions"] == {"checkpointed": 1}
    assert view["executions"][0]["worker_session"]["state"] == "checkpointed"
    assert set(view["executions"][0]) & {"objective", "prompt", "transcript", "worktree", "context_ref", "error"} == set()


# ---- read-only: no put or graph is reachable ---------------------------------------------------

class Spy:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        def record(*args, **kwargs):
            self.calls.append(name)
        return record


def test_no_put_or_graph_is_reachable_through_the_read_only_wrappers():
    class Inner(Spy):
        def get(self, bucket, key):
            return None

        def scan(self, bucket):
            return []

        def entries(self, bucket, after="", limit=100):
            return []

        def records(self):
            return []

    inner = Inner()

    class Store:
        def transaction(self):
            import contextlib

            @contextlib.contextmanager
            def cm():
                yield inner
            return cm()
    with collectors.ReadOnlyStore(Store()).transaction() as tx:
        with pytest.raises(collectors.ContractError, match="read-only"):
            tx.put("b", "k", {})
        with pytest.raises(collectors.ContractError, match="read-only"):
            tx.graph()
        for name in ("put_node", "put_edge", "delete", "commit"):
            with pytest.raises(AttributeError):
                getattr(tx, name)
    assert inner.calls == []
    artifacts = Spy()
    reader = collectors.ReadOnlyArtifacts(artifacts)
    with pytest.raises(collectors.ContractError, match="read-only"):
        reader.put("body", "monitor")
    assert artifacts.calls == []
    service, wrapped = collectors.read_only(type("S", (), {"store": Store(), "org": "ORG"})(), artifacts)
    assert (service.org, type(service.store), type(wrapped)) == ("ORG", collectors.ReadOnlyStore, collectors.ReadOnlyArtifacts)


def test_the_module_never_calls_a_write_method_and_the_wrappers_define_only_the_two_refusals():
    tree = ast.parse(TEXT)
    writes = {"put", "put_node", "put_edge", "graph", "write_text", "write_bytes", "mkdir", "touch", "unlink", "rename", "replace", "chmod", "write"}
    calls = [n.func.attr for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in writes]
    assert calls == []
    refusals = {c.name: sorted(f.name for f in c.body if isinstance(f, ast.FunctionDef) and f.name in ("put", "graph"))
                for c in tree.body if isinstance(c, ast.ClassDef) and c.name.startswith("ReadOnly")}
    assert refusals == {"ReadOnlyTransaction": ["graph", "put"], "ReadOnlyStore": [], "ReadOnlyArtifacts": ["put"], "ReadOnlyService": []}


# ---- call shapes, no spawn, the uninjected clock stays, the layer rules -------------------------

def test_call_shapes_are_m7s_and_nothing_is_injected_in_this_batch():
    import inspect
    shapes = {name: list(inspect.signature(getattr(collectors, name)).parameters) for name in (
        "safe_text", "read_only", "container_scope", "parse_observed", "persisted_measurements", "audit_progress", "project_receipt", "execution_activity",
        "lane_artifact_resolver", "lane_view", "scope_label")}
    assert shapes == {"safe_text": ["value", "limit"], "read_only": ["service", "artifacts"], "container_scope": ["value"], "parse_observed": ["value"],
                      "persisted_measurements": ["store", "now"], "audit_progress": ["data", "control"], "project_receipt": ["text"],
                      "execution_activity": ["row", "progress", "reader", "now", "recent_terminal_seconds"], "lane_artifact_resolver": [],
                      "lane_view": ["store", "reader", "now", "recent_terminal_seconds"], "scope_label": ["repository", "label"]}
    assert list(inspect.signature(collectors.DatabaseFacts.__init__).parameters) == ["self", "service", "artifacts"]
    assert list(inspect.signature(collectors.ArtifactReader.__init__).parameters) == ["self", "root"]
    assert inspect.signature(collectors.execution_activity).parameters["recent_terminal_seconds"].default == collectors.RECENT_TERMINAL_SECONDS == 600
    assert inspect.signature(collectors.lane_view).parameters["now"].default is None
    assert inspect.signature(collectors.persisted_measurements).parameters["now"].default is None


def test_the_u6_clock_calls_stay_the_two_uninjected_datetime_now_calls_of_m7():
    now_calls = {n.lineno: next(f.name for f in ast.walk(ast.parse(TEXT)) if isinstance(f, ast.FunctionDef) and f.lineno <= n.lineno <= f.end_lineno)
                 for n in ast.walk(ast.parse(TEXT)) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "now"}
    assert sorted(now_calls.values()) == ["lane_view", "persisted_measurements"]
    assert "utcnow" not in TEXT and "Clock" not in TEXT


def test_no_new_spawn_site_and_no_process_or_thread_machinery():
    tree = ast.parse(TEXT)
    imported = {n.module if isinstance(n, ast.ImportFrom) else a.name for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom)) for a in
                (n.names if isinstance(n, ast.Import) else [None])}
    assert not imported & {"subprocess", "multiprocessing", "threading", "concurrent.futures", "socket", "asyncio", "redis", "psycopg"}
    for banned in ("subprocess", "Popen", "multiprocessing", "ThreadPoolExecutor", "os.system", "os.popen", "os.exec", "os.spawn", "os.fork", "run_process"):
        assert banned not in TEXT, banned
    spawn = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and isinstance(n.func.value, ast.Name)
             and n.func.value.id == "os" and re.match(r"(exec|spawn|posix_spawn|system|popen|fork)", n.func.attr)]
    assert spawn == []


def test_no_layer_or_cycle_violation_touches_the_module():
    violations = import_rules.check(REPO / "target" / "src")
    assert [v for v in violations if "observation.adapters.collectors" in v.module] == []
    assert violations == []
    assert not re.search(r"(?m)^(?:from|import) codex_harness\.(?!kernel|execution\.domain|research\.domain)", TEXT)
