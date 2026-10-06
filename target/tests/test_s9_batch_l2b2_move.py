"""S9 batch L2-B2: the measurements (U4) and the pure monitoring projection (U5a) move out of M7 `domain/measurements.py`,
`application/measurements.py` and `application/monitoring.py`.

Each module is M7's whole, in M7's order, with only its import block (R-m0, R-a0, R-g0) and header changed. M7 is read only as text through
`git show e38aa722:...` and compared by AST (never imported: both packages are named `codex_harness`). Behaviour is compared by the recorded
`observation.measurements` and `observation.monitoring_projection` goldens (the moved modules are target-equal to them); this file pins the structure and the
contract facts a golden does not state as a rule: the import homes, the layer rules, the positional call shapes and the single writer of `metric_observations`.

M7 tests these units do NOT port yet (the S9 ported suite is a later step): `test_measurements.py` (10 test functions, of which
`test_attempt_failures_survive_retry_and_are_not_duplicated`, `test_workflow_retry_history_is_fenced_and_cancellation_authorized` and
`test_monitor_reads_persisted_measurements_without_evaluating_or_writing` exercise Workflow or the monitoring adapter, U6/U7), and from
`test_monitoring.py` the Monitoring/initiatives tests `test_completed_implementation_does_not_hide_blocked_review`,
`test_failed_canary_and_expired_lease_are_attention_states` and `test_expired_execution_and_stale_health_are_not_live`; the PostgreSQL-needing
`test_integration.py:290` is also not ported.
"""

from __future__ import annotations

import ast
import inspect
import subprocess
from pathlib import Path

from _layout import REPO, TARGET

from codex_harness.kernel.policy import POLICY
from codex_harness.observation.application import measurements as app_module
from codex_harness.observation.application import monitoring as monitoring_module
from codex_harness.observation.domain import measurements as domain_module

SRC = TARGET / "src" / "codex_harness"
SOURCE = "e38aa722"
DOMAIN_M7 = "src/codex_harness/domain/measurements.py"
APP_M7 = "src/codex_harness/application/measurements.py"
MONITORING_M7 = "src/codex_harness/application/monitoring.py"
FORBIDDEN_HOMES = ("codex_harness.adapters", "codex_harness.domain", "codex_harness.application", "codex_harness.ports")
UNITS = [(domain_module, DOMAIN_M7), (app_module, APP_M7), (monitoring_module, MONITORING_M7)]

def show(rev, path):
    return subprocess.run(["git", "-C", str(REPO), "show", f"{rev}:{path}"], check=True, capture_output=True, text=True).stdout


def text_of(module):
    return Path(module.__file__).read_text()


def statements(src):
    out = {}
    for i, node in enumerate(ast.parse(src).body):
        if isinstance(node, (ast.Import, ast.ImportFrom)) or (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)):
            continue
        name = getattr(node, "name", None) or (node.targets[0].id if isinstance(node, ast.Assign) else i)
        out[name] = node
    return out


def import_modules(src):
    return sorted({n.module for n in ast.walk(ast.parse(src)) if isinstance(n, ast.ImportFrom)})


def plain_imports(src):
    return sorted(a.name for n in ast.parse(src).body if isinstance(n, ast.Import) for a in n.names)


def header(module):
    return ast.get_docstring(ast.parse(text_of(module)))


def test_each_module_is_m7s_in_m7s_order_modulo_imports_and_header():
    for module, m7 in UNITS:
        ours, theirs = statements(text_of(module)), statements(show(SOURCE, m7))
        assert list(ours) == list(theirs), m7
        for name, node in theirs.items():
            assert ast.dump(ours[name]) == ast.dump(node), (m7, name)
    assert list(statements(text_of(domain_module))) == ["Definition", "DEFINITIONS", "TERMINAL", "Evaluation", "timestamp", "evaluate", "definition_documents"]
    assert list(statements(text_of(app_module))) == ["Measurements"]
    assert list(statements(text_of(monitoring_module))) == ["MonitoringFacts", "age_seconds", "Monitoring", "initiatives"]


def test_the_first_header_line_is_m7s_module_docstring():
    for module, m7 in UNITS:
        assert header(module).split("\n")[0] == ast.get_docstring(ast.parse(show(SOURCE, m7))), m7


def test_import_homes_and_no_m7_home_remains():
    assert import_modules(text_of(domain_module)) == ["codex_harness.kernel.policy", "dataclasses", "datetime", "typing"]
    assert import_modules(text_of(app_module)) == ["codex_harness.kernel.errors", "codex_harness.kernel.ids", "codex_harness.observation.domain.measurements",
                                                   "codex_harness.storage.ports", "dataclasses", "datetime"]
    assert import_modules(text_of(monitoring_module)) == ["codex_harness.kernel.policy", "collections", "datetime", "typing"]
    for module, _ in UNITS:
        text = text_of(module)
        assert plain_imports(text) == []
        assert not [m for m in import_modules(text) if m.startswith(FORBIDDEN_HOMES)]
        assert "subprocess" not in text and "multiprocessing" not in text and "Popen" not in text
    assert domain_module.POLICY is POLICY and monitoring_module.POLICY is POLICY
    assert app_module.DEFINITIONS is domain_module.DEFINITIONS and app_module.evaluate is domain_module.evaluate
    assert app_module.definition_documents is domain_module.definition_documents


def test_layer_rules_domain_imports_only_the_kernel_and_application_its_own_domain_and_storage_ports():
    for module in (domain_module, monitoring_module, app_module):
        first_party = [m for m in import_modules(text_of(module)) if m.startswith("codex_harness.")]
        if module is domain_module or module is monitoring_module:
            assert all(m.startswith("codex_harness.kernel.") for m in first_party), module.__name__
        else:
            assert all(m.startswith(("codex_harness.kernel.", "codex_harness.observation.domain.", "codex_harness.storage.ports")) for m in first_party)
    doc = header(domain_module)
    assert doc.split("\n\n")[1].startswith("Layer: domain\nContext: observation\n")
    for module in (app_module, monitoring_module):
        assert header(module).split("\n\n")[1].startswith("Layer: application\nContext: observation\n")


def test_the_headers_carry_the_section_3_2_fields():
    for module, _ in UNITS:
        doc = header(module)
        for field in ("Layer:", "Context: observation", "Owns:", "Does not own:", "Entry points:", "Contracts:", "Moved from M7", SOURCE, "named rules"):
            assert field in doc, (module.__name__, field)
    assert "INV-METRIC-001" in header(domain_module) and "INV-METRIC-001" in header(app_module)
    assert "INV-OBSERVATION-001" in header(monitoring_module)
    for name in ("Measurements", "Measurements.collect"):
        assert name in header(app_module).split("Entry points:")[1].split("\n")[0]
    for name in ("Monitoring", "MonitoringFacts", "initiatives", "age_seconds"):
        assert name in header(monitoring_module).split("Entry points:")[1].split("\n")[0]


def positional_names(function):
    return [p.name for p in inspect.signature(function).parameters.values()]


def test_call_signatures_are_m7s_and_nothing_is_injected():
    m7 = statements(show(SOURCE, APP_M7))["Measurements"]
    init = [n for n in m7.body if isinstance(n, ast.FunctionDef) and n.name == "__init__"][0]
    collect = [n for n in m7.body if isinstance(n, ast.FunctionDef) and n.name == "collect"][0]
    assert positional_names(app_module.Measurements.__init__) == [a.arg for a in init.args.args] == ["self", "store", "artifacts"]
    assert positional_names(app_module.Measurements.collect) == [a.arg for a in collect.args.args] == ["self", "repository_revision", "now"]
    assert inspect.signature(app_module.Measurements.collect).parameters["now"].default is None
    monitoring = statements(show(SOURCE, MONITORING_M7))
    assert positional_names(monitoring_module.Monitoring.__init__) == ["self", "facts"]
    assert positional_names(monitoring_module.Monitoring.snapshot) == ["self", "now"]
    assert inspect.signature(monitoring_module.Monitoring.snapshot).parameters["now"].default is None
    assert positional_names(monitoring_module.initiatives) == ["facts", "now"] == [a.arg for a in monitoring["initiatives"].args.args]
    assert positional_names(monitoring_module.age_seconds) == ["timestamp", "now"]
    assert positional_names(domain_module.evaluate) == ["definition", "evidence", "now"]


def test_the_monitoring_class_name_and_the_protocol_are_m7s():
    """Owner decision D5 as amended: the class stays `Monitoring`; `MonitoringFacts` stays the Protocol it is in M7."""
    assert monitoring_module.Monitoring.__name__ == "Monitoring" and not hasattr(monitoring_module, "SnapshotProjection")
    assert getattr(monitoring_module.MonitoringFacts, "_is_protocol", False)
    assert [n.name for n in ast.parse(text_of(monitoring_module)).body if isinstance(n, ast.FunctionDef | ast.ClassDef)] == [
        "MonitoringFacts", "age_seconds", "Monitoring", "initiatives"]


def test_the_stage_one_definitions_are_the_three_documented_metrics():
    assert [d.metric_id for d in domain_module.DEFINITIONS] == ["task_first_attempt_success", "terminal_logical_task_success", "active_execution_capacity"]
    assert domain_module.DEFINITIONS[2].target == POLICY.max_active_executions
    assert [d["metric_id"] for d in domain_module.definition_documents()] == [d.metric_id for d in domain_module.DEFINITIONS]


def writes_of(path: Path, bucket: str):
    sites = []
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in {"put", "delete", "insert", "upsert", "write", "append"}:
            if any(isinstance(a, ast.Constant) and a.value == bucket for a in node.args[:1]):
                sites.append((node.func.attr, node.lineno))
    return sites


def test_metric_observations_is_written_only_by_the_measurements_use_case():
    writers = {p.relative_to(SRC).as_posix(): writes_of(p, "metric_observations") for p in sorted(SRC.rglob("*.py"))}
    writers = {k: v for k, v in writers.items() if v}
    assert list(writers) == ["observation/application/measurements.py"]
    assert [kind for kind, _ in writers["observation/application/measurements.py"]] == ["put"]
