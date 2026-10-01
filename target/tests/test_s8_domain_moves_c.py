"""S8 step 1c: the discovery census split (V2e) and the intake backlog completion (V2f), moved verbatim by
A/evidence/rebuild/s8/domain-moves-c/transcribe.py (DESIGN-s8 §1 V2e, V2f, V7).

M7 is read only as text through `git show e38aa722:...` and compared by AST (never imported: both packages are named
`codex_harness`). Behaviour is checked on the TARGET only, against literals.
"""
import ast
import importlib
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SOURCE = "e38aa722"
M7 = "src/codex_harness/domain/"
CENSUS = "codex_harness.coordination.domain.discovery_census"
PRESSURE = "codex_harness.research.domain.discovery_pressure"
BACKLOG = "codex_harness.intake.domain.backlog"
CENSUS_NAMES = ["WAITING_ONLY", "CONTINUATION_OPEN", "census"]
R_F1_NAMES = {"ACCEPTED", "DEPENDENCY_BLOCKING"}
# Pilot 63 adds the R-p3 read constants and the R-p4 `safe_code` owner to the same module (test_s8_portfolio_move).
R_P63_NAMES = {"DISPATCHING", "EXHAUSTED", "FAILED", "QUEUED", "REJECTED", "SAFE_CODE", "safe_code"}


def m7_text(path):
    return subprocess.run(["git", "-C", str(REPO), "show", f"{SOURCE}:{path}"], check=True, capture_output=True,
                          text=True).stdout


def target_text(module):
    return Path(importlib.import_module(module).__file__).read_text()


def top_names(src):
    names = []
    for node in ast.parse(src).body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            names.append(node.name)
        elif isinstance(node, ast.Assign):
            names.extend(n.id for t in node.targets for n in ast.walk(t) if isinstance(n, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.append(node.target.id)
    return names


def statements(src):
    out = {}
    for node in ast.parse(src).body:
        if isinstance(node, (ast.Import, ast.ImportFrom)) or (
                isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)):
            continue
        key = tuple(top_names(ast.unparse(node)))
        assert key not in out
        out[key] = ast.dump(node)
    return out


def without_census_in_all(src):
    """Statement dumps with the `census` entry dropped from `__all__` (the one declared edit to that list)."""
    out = {}
    for node in ast.parse(src).body:
        if isinstance(node, (ast.Import, ast.ImportFrom)) or (
                isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)):
            continue
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "__all__" for t in node.targets):
            node.value.elts = [e for e in node.value.elts if e.value != "census"]
        out[tuple(top_names(ast.unparse(node)))] = ast.dump(node)
    return out


def imported_modules(module):
    return [n.module for n in ast.walk(ast.parse(target_text(module))) if isinstance(n, ast.ImportFrom)]


def test_census_module_holds_exactly_the_three_m7_definitions():
    ref = m7_text(M7 + "discovery_pressure.py")
    text = target_text(CENSUS)
    assert top_names(text) == CENSUS_NAMES
    ours, theirs = statements(text), statements(ref)
    assert {k: v for k, v in theirs.items() if k[0] in CENSUS_NAMES} == ours
    assert 'census' in text and "# A queued job counts as waiting work only when" in text
    assert "# Continuation intents that will admit a Fleet operation" in text


def test_research_module_has_every_other_m7_definition_in_m7_order():
    ref = m7_text(M7 + "discovery_pressure.py")
    ours, theirs = without_census_in_all(target_text(PRESSURE)), without_census_in_all(ref)
    expected = {k: v for k, v in theirs.items() if k[0] not in CENSUS_NAMES}
    assert ours == expected and list(ours) == list(expected)
    assert not set(CENSUS_NAMES) & set(top_names(target_text(PRESSURE)))
    assert "census" not in importlib.import_module(PRESSURE).__all__
    assert "# census: coordination.domain.discovery_census (DESIGN-s8 V2e)" in target_text(PRESSURE)
    assert ast.get_docstring(ast.parse(target_text(PRESSURE))).endswith(ast.get_docstring(ast.parse(ref)).strip("\n"))


def test_the_two_halves_are_disjoint_and_cover_m7_discovery_pressure():
    m7 = set(top_names(m7_text(M7 + "discovery_pressure.py")))
    research, census = set(top_names(target_text(PRESSURE))), set(top_names(target_text(CENSUS)))
    assert research | census == m7
    assert not research & census


def test_research_discovery_pressure_imports_nothing_from_coordination_or_intake():
    mods = imported_modules(PRESSURE)
    assert mods and not [m for m in mods if m.startswith(("codex_harness.coordination", "codex_harness.intake"))]
    assert sorted(m for m in mods if m.startswith("codex_harness.")) == [
        "codex_harness.kernel.errors", "codex_harness.kernel.ids"]


def test_census_imports_come_from_the_named_target_homes():
    assert sorted(m for m in imported_modules(CENSUS) if m.startswith("codex_harness.")) == [
        "codex_harness.coordination.domain.continuation", "codex_harness.coordination.domain.fleet",
        "codex_harness.intake.domain.backlog", "codex_harness.kernel.usage"]
    from codex_harness.coordination.domain import continuation
    from codex_harness.intake.domain import backlog
    from codex_harness.kernel import usage

    census = importlib.import_module(CENSUS)
    assert census.CONDUCTOR is continuation.CONDUCTOR and census.select is backlog.select
    assert census.exhausted is usage.exhausted and census.ITEM_OPEN is backlog.ITEM_OPEN


def test_backlog_keeps_the_s5_bytes_and_appends_m7_in_order():
    base = subprocess.run(["git", "-C", str(REPO), "show", "88f8a7516ebed85528e4381720caefceef69dc45:"
                           "target/src/codex_harness/intake/domain/backlog.py"], check=True, capture_output=True,
                          text=True).stdout
    ref = m7_text(M7 + "fleet_backlog.py")
    text = target_text(BACKLOG)
    kept = set(top_names(base))
    ours, theirs = statements(text), statements(ref)
    # every M7 statement is in the output with the same AST; the output adds only the R-f1 pair and `binding`
    assert {k: v for k, v in ours.items() if k[0] not in R_F1_NAMES | R_P63_NAMES | {"binding"}} == theirs
    assert {k[0] for k in ours} - {k[0] for k in theirs} == R_F1_NAMES | R_P63_NAMES | {"binding"}
    assert set(top_names(ref)) <= set(top_names(text))
    appended = [k[0] for k in ours if k[0] not in kept | R_F1_NAMES | R_P63_NAMES | {"binding"}]
    assert appended == [k[0] for k in theirs if k[0] not in kept]
    # the S5 definitions keep their bytes
    for node in ast.parse(base).body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            assert ast.get_source_segment(base, node) in text


def test_binding_is_m7_fleet_binding_with_one_owner():
    from codex_harness.coordination.domain import fleet
    from codex_harness.intake.domain import backlog

    fleet_m7 = ast.parse(m7_text(M7 + "fleet.py"))
    m7_binding = next(n for n in fleet_m7.body if isinstance(n, ast.FunctionDef) and n.name == "binding")
    ours = next(n for n in ast.parse(target_text(BACKLOG)).body if isinstance(n, ast.FunctionDef)
                and n.name == "binding")
    assert ast.dump(ours) == ast.dump(m7_binding)
    assert "binding" not in [n.name for n in ast.parse(target_text("codex_harness.coordination.domain.fleet")).body
                             if isinstance(n, ast.FunctionDef)]
    assert fleet.binding is backlog.binding
    job = {"lane": "l", "manifest_sha256": "m", "repository": "r", "dependencies": [], "goal": {}}
    assert backlog.binding(job) == {"lane": "l", "manifest_sha256": "m", "repository": "r", "dependencies": [],
                                    "goal": {}}


def test_read_constants_equal_coordination_fleet():
    from codex_harness.coordination.domain import fleet
    from codex_harness.intake.domain import backlog

    assert backlog.ACCEPTED == fleet.ACCEPTED == "accepted"
    assert backlog.DEPENDENCY_BLOCKING == fleet.DEPENDENCY_BLOCKING
    assert backlog.DEPENDENCY_BLOCKING == frozenset({"rejected", "failed", "exhausted", "unknown"})


def test_safe_relative_path_is_the_kernel_one():
    from codex_harness.kernel import ids

    assert importlib.import_module(BACKLOG).safe_relative_path is ids.safe_relative_path


def test_backlog_imports_no_coordination():
    assert not [m for m in imported_modules(BACKLOG) if m.startswith("codex_harness.coordination")]


BUDGET = {"per_host": 10, "total": 20}


def census_job(job_id, lane, status, repository):
    return {"id": job_id, "lane": lane, "status": status, "repository": repository, "dependencies": [],
            "manifest": {"budget": BUDGET, "plan": {"allowed_paths": ["src"]}}}


def test_census_spot_check_one_queued_lane_busy_job_is_waiting():
    census = importlib.import_module(CENSUS).census
    jobs = {"a": census_job("a", "lane-1", "dispatching", "repo-a"),
            "b": census_job("b", "lane-1", "queued", "repo-b")}
    row = census(config={"max_parallel": 2, "budget": BUDGET}, control={}, jobs=jobs, units=[], plans=[],
                 intents=[], continuation_intents=[], ledger={"this_host": 0, "all_hosts": 0, "unreadable": 0})
    assert row["registered"] is True and row["paused"] is False
    assert row["capacity"] == 2 and row["waiting"] == 1
    assert row["complete"] is True
    assert row["unknown"] == {"backlog": 0, "continuation": 0, "budget": 0}
    assert row["excluded"] == {}
    assert row["occupancy"] == {"jobs_reserving": 1, "units_held": 0}
    assert census(config=None, control=None, jobs={}, units=[], plans=[], intents=[],
                  continuation_intents=[]) == {"registered": False}
