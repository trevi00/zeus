"""S8 pilot 63: the M7 portfolio application and adapter moved into intake, VERBATIM through named rules
(A/evidence/rebuild/s8/portfolio-move/transcribe.py; DESIGN-s8 §1 V2c, V4, V9, §6 V11).

M7 is read only as text through `git show e38aa722:...` and compared by AST (never imported: both packages are named
`codex_harness`). Behaviour is checked on the TARGET only, against literals.
"""
import ast
import importlib
import subprocess
from pathlib import Path

from _layout import REPO

SOURCE = "e38aa722"
APP = "codex_harness.intake.application.portfolio"
ADAPTER = "codex_harness.intake.adapters.portfolio"
DOMAIN = "codex_harness.intake.domain.portfolio"
BACKLOG = "codex_harness.intake.domain.backlog"
R_P1 = ("BUCKET_BINDINGS", "BUCKET_INVESTIGATIONS", "FAMILY_MINIMUM", "RESEARCH_REQUIRED")
R_P6 = ("PortfolioRefused", "family_id", "LINEAGE_AUTHORITY", "inherit_binding")
# The M7 statements the application no longer defines (their homes are R-p1 and the S6 move-aheads).
MOVED = {("BUCKET_BINDINGS",), ("BUCKET_INVESTIGATIONS",), ("FAMILY_MINIMUM",),
         ("RESEARCH_REQUIRED", "RESEARCHED", "DEFERRED"), ("PortfolioRefused",), ("family_id",),
         ("LINEAGE_AUTHORITY",), ("inherit_binding",)}


def m7_text(path):
    return subprocess.run(["git", "-C", str(REPO), "show", f"{SOURCE}:{path}"], check=True, capture_output=True,
                          text=True).stdout


def target_text(module):
    return Path(importlib.import_module(module).__file__).read_text()


def defined(node):
    if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
        return (node.name,)
    if isinstance(node, ast.Assign):
        return tuple(n.id for t in node.targets for n in ast.walk(t) if isinstance(n, ast.Name))
    return ()


def statements(src):
    out = {}
    for i, node in enumerate(ast.parse(src).body):
        if isinstance(node, (ast.Import, ast.ImportFrom)) or (
                isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)):
            continue
        key = defined(node) or ("expr", i)
        assert key not in out
        out[key] = ast.dump(node)
    return out


def imported_modules(module):
    return [n.module for n in ast.walk(ast.parse(target_text(module))) if isinstance(n, ast.ImportFrom)]


def test_application_is_m7_minus_the_moved_statements_in_m7_order():
    ref = statements(m7_text("src/codex_harness/application/portfolio.py"))
    ours = statements(target_text(APP))
    assert set(ref) - set(ours) == MOVED
    assert set(ours) - set(ref) == {("RESEARCHED", "DEFERRED")}
    split = ast.dump(ast.parse('RESEARCHED, DEFERRED = "researched", "deferred"').body[0])
    assert ours.pop(("RESEARCHED", "DEFERRED")) == split
    expected = {k: v for k, v in ref.items() if k not in MOVED}
    assert ours == expected and list(ours) == list(expected)
    assert sum(isinstance(n, ast.FunctionDef) for n in ast.parse(target_text(APP)).body) == 14  # M7 has 16: family_id and inherit_binding moved


def test_application_surface_equals_m7_all_and_every_name_resolves():
    app = importlib.import_module(APP)
    m7_all = ast.literal_eval(next(n for n in ast.parse(m7_text("src/codex_harness/application/portfolio.py")).body
                                   if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "__all__").value)
    assert list(app.__all__) == m7_all
    for name in m7_all + ["LINEAGE_AUTHORITY", "FAMILY_MINIMUM", "BUCKET_JOBS", "PROGRESS_KIND", "FAILURE_KIND"]:
        assert hasattr(app, name), name


def test_s6_move_aheads_are_imported_not_redefined():
    from codex_harness.intake.application import portfolio_lineage
    from codex_harness.intake.domain import portfolio as domain

    app = importlib.import_module(APP)
    assert app.PortfolioRefused is domain.PortfolioRefused and app.family_id is domain.family_id
    assert app.inherit_binding is portfolio_lineage.inherit_binding
    assert app.LINEAGE_AUTHORITY is portfolio_lineage.LINEAGE_AUTHORITY
    assert app.BUCKET_JOBS is portfolio_lineage.BUCKET_JOBS and app.BUCKET_JOBS == "fleet_jobs"
    defs = {n.name for n in ast.parse(target_text(APP)).body if isinstance(n, (ast.FunctionDef, ast.ClassDef))}
    assert not defs & {"PortfolioRefused", "family_id", "inherit_binding"}


def test_adapter_is_m7_with_only_the_import_home_changed():
    ref_src = m7_text("src/codex_harness/adapters/portfolio.py")
    assert statements(target_text(ADAPTER)) == statements(ref_src)
    assert list(statements(target_text(ADAPTER))) == list(statements(ref_src))
    assert "from codex_harness.intake.application.portfolio import Portfolio, reconcile" in target_text(ADAPTER)
    assert "from codex_harness.application.portfolio" not in target_text(ADAPTER)
    assert importlib.import_module(ADAPTER).Portfolio is importlib.import_module(APP).Portfolio


def test_application_and_adapter_import_only_kernel_and_intake():
    for module in (APP, ADAPTER):
        mods = [m for m in imported_modules(module) if m.startswith("codex_harness.")]
        assert mods and not [m for m in mods if not m.startswith(("codex_harness.kernel.", "codex_harness.intake."))], mods


def test_r_p1_constants_live_in_intake_domain_and_equal_m7():
    m7 = ast.parse(m7_text("src/codex_harness/application/portfolio.py"))
    values = {}
    for node in m7.body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) and node.targets[0].id in R_P1:
            values[node.targets[0].id] = ast.literal_eval(node.value)
        elif isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Tuple):
            names = [e.id for e in node.targets[0].elts]
            if "RESEARCH_REQUIRED" in names:
                values["RESEARCH_REQUIRED"] = ast.literal_eval(node.value)[names.index("RESEARCH_REQUIRED")]
    assert values == {"BUCKET_BINDINGS": "portfolio_bindings", "BUCKET_INVESTIGATIONS": "portfolio_investigations",
                      "FAMILY_MINIMUM": 2, "RESEARCH_REQUIRED": "research_required"}
    domain, app = importlib.import_module(DOMAIN), importlib.import_module(APP)
    for name, value in values.items():
        assert getattr(domain, name) == value
        assert getattr(app, name) is getattr(domain, name)
    assert not {n for k in statements(target_text(APP)) for n in k} & set(R_P1)


def test_r_p1b_owner_actions_state_imports_the_one_definition():
    from codex_harness.coordination.application.owner_actions import state
    from codex_harness.intake.domain import portfolio as domain

    assert state.BUCKET_INVESTIGATIONS is domain.BUCKET_INVESTIGATIONS == "portfolio_investigations"
    assigned = [t.id for n in ast.parse(target_text(state.__name__)).body if isinstance(n, ast.Assign)
                for t in n.targets if isinstance(t, ast.Name)]
    assert "BUCKET_INVESTIGATIONS" not in assigned


def test_r_p2_research_kinds_equal_the_research_owners():
    from codex_harness.intake.domain import portfolio as domain
    from codex_harness.research.domain import audit_progress, research_investigations

    assert domain.PROGRESS_KIND == audit_progress.KIND == "audit_progress"
    assert domain.FAILURE_KIND == research_investigations.KIND == "failure_family"
    app = importlib.import_module(APP)
    assert app.PROGRESS_KIND is domain.PROGRESS_KIND and app.FAILURE_KIND is domain.FAILURE_KIND


def test_r_p3_read_constants_equal_coordination_fleet():
    from codex_harness.coordination.domain import fleet
    from codex_harness.intake.domain import backlog

    for name, value in (("DISPATCHING", "dispatching"), ("EXHAUSTED", "exhausted"), ("FAILED", "failed"),
                        ("QUEUED", "queued"), ("REJECTED", "rejected")):
        assert getattr(backlog, name) == getattr(fleet, name) == value, name
    app = importlib.import_module(APP)
    assert app.JOB_ACCEPTED == fleet.ACCEPTED == backlog.ACCEPTED


def test_r_p4_safe_code_has_one_owner():
    from codex_harness.coordination.domain import fleet
    from codex_harness.intake.domain import backlog, frontdesk
    from codex_harness.kernel import analysis

    fleet_m7 = ast.parse(m7_text("src/codex_harness/domain/fleet.py"))
    m7_fn = next(n for n in fleet_m7.body if isinstance(n, ast.FunctionDef) and n.name == "safe_code")
    ours = next(n for n in ast.parse(target_text(BACKLOG)).body if isinstance(n, ast.FunctionDef)
                and n.name == "safe_code")
    assert ast.dump(ours) == ast.dump(m7_fn)
    assert fleet.safe_code is backlog.safe_code and fleet.SAFE_CODE is backlog.SAFE_CODE
    assert importlib.import_module(APP).safe_code is backlog.safe_code
    assert backlog.SAFE_CODE.pattern == r"^[A-Za-z0-9_.:-]{1,80}$"
    own = {n.name for n in ast.parse(target_text("codex_harness.coordination.domain.fleet")).body
           if isinstance(n, ast.FunctionDef)}
    assert "safe_code" not in own
    # the kernel and frontdesk functions of the same name are different functions and stay as they are
    assert analysis.safe_code is not backlog.safe_code and frontdesk.safe_code is not backlog.safe_code
    assert backlog.safe_code("exception:ValueError: boom") == "exception:ValueError"
    assert backlog.safe_code("child_refused:detail") == "child_refused"
    assert backlog.safe_code("bad code!") == "unknown" and backlog.safe_code(None) == "unknown"


def test_v4_intake_owns_the_portfolio_buckets():
    from codex_harness.intake import ports

    portfolio = ("portfolio_bindings", "portfolio_acceptances", "portfolio_investigations", "portfolio_followups")
    # S8 pilot 84 (V16) appends the four front-desk buckets after the portfolio ones; pilot 98 (V11) the eight ticket buckets
    tickets = ("tickets", "ticket_dispatches", "ticket_closures", "ticket_closure_sequences", "ticket_reopens", "ticket_github",
               "ticket_lifecycle_events", "ticket_trust_anchors")
    # S8 batch B2 (V30 R-tk3) appends the five buckets of `Tickets` and `GitHubTickets`
    batch_b2 = ("ticket_reviews", "ticket_revisions", "ticket_remote_creations", "ticket_remote_observations", "ticket_syncs")
    assert ports.OWNED_BUCKETS == portfolio + ("desk_sessions", "desk_requests", "desk_events", "desk_receipts") + tickets + batch_b2
    app = importlib.import_module(APP)
    assert {app.BUCKET_BINDINGS, app.BUCKET_ACCEPTANCES, app.BUCKET_INVESTIGATIONS, app.BUCKET_FOLLOWUPS} == set(portfolio)


def test_spot_check_the_moved_portfolio_runs_over_a_memory_store():
    from codex_harness.intake.adapters import portfolio as adapter
    from codex_harness.storage.adapters.memory_store import MemoryStore

    store = MemoryStore()
    summary = adapter.portfolio_reconciler(store)()
    assert summary["reconciled"] is True and summary["scanned"] == 0 and summary["candidates"] == []
    status = adapter.portfolio(store).status()
    assert status["unbound_jobs"] == 0 and status["investigations"] == []
