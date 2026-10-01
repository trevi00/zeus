"""S8 pilot 65: the M7 debate-session application moved into research, VERBATIM through named rules
(A/evidence/rebuild/s8/dge-move/transcribe.py; DESIGN-s8 §1 V4, §6 V11).

M7 is read only as text through `git show e38aa722:...` and compared by AST (never imported: both packages are named
`codex_harness`). Behaviour is checked on the TARGET only, against literals.
"""
import ast
import importlib
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SOURCE = "e38aa722"
APP = "codex_harness.research.application.dge"
DOMAIN = "codex_harness.research.domain.dge"
M7_PATH = "src/codex_harness/application/dge.py"
MOVED = {("DgeRefused",)}  # R-d2: moved ahead in S5, imported here


def m7_text(path=M7_PATH):
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


def test_application_is_m7_minus_the_moved_ahead_refusal_in_m7_order():
    ref = statements(m7_text())
    ours = statements(target_text(APP))
    assert set(ref) - set(ours) == MOVED and set(ours) <= set(ref)
    expected = {k: v for k, v in ref.items() if k not in MOVED}
    assert ours == expected and list(ours) == list(expected)
    body = ast.parse(target_text(APP)).body
    assert sum(isinstance(n, ast.FunctionDef) for n in body) == 2  # design_gate, _by_status
    assert [n.name for n in body if isinstance(n, ast.ClassDef)] == ["DebateSessions"]  # M7 also has DgeRefused
    assert len(ref) == 7 and len(ours) == 6


def test_dge_refused_is_the_s5_class_imported_not_redefined():
    app, domain = importlib.import_module(APP), importlib.import_module(DOMAIN)
    assert app.DgeRefused is domain.DgeRefused
    refused = next(n for n in ast.parse(m7_text()).body if isinstance(n, ast.ClassDef) and n.name == "DgeRefused")
    theirs = next(n for n in ast.parse(target_text(DOMAIN)).body if isinstance(n, ast.ClassDef) and n.name == "DgeRefused")
    assert ast.dump(refused) == ast.dump(theirs)
    defs = {n.name for n in ast.parse(target_text(APP)).body if isinstance(n, ast.ClassDef)}
    assert "DgeRefused" not in defs
    try:
        raise app.DgeRefused("expired")
    except domain.DgeRefused as exc:  # what Operation catches
        assert exc.reason_code == "expired" and str(exc) == "dge refused: expired"


def test_imports_are_only_kernel_and_research_homes():
    mods = [n.module for n in ast.walk(ast.parse(target_text(APP))) if isinstance(n, ast.ImportFrom)
            and n.module.startswith("codex_harness.")]
    assert sorted(set(mods)) == ["codex_harness.kernel.errors", "codex_harness.kernel.ids",
                                 "codex_harness.research.domain.dge"]
    assert "codex_harness.domain" not in target_text(APP).replace("codex_harness.research.domain", "")


def test_bucket_and_schema_literals_equal_m7():
    app = importlib.import_module(APP)
    assert (app.SESSIONS, app.EVENTS, app.STATUS_SCHEMA) == ("dge_sessions", "dge_events", "urn:zeus:debate-status:1")


def test_v4_research_owns_the_dge_buckets():
    from codex_harness.research import ports

    # the first six are the S6/pilot 65 names; later V4 moves (pilot 70: the research_* audit buckets) append to the tuple
    assert ports.OWNED_BUCKETS[:6] == ("inbox", "incidents", "hooks", "research_programs", "dge_sessions", "dge_events")
    app = importlib.import_module(APP)
    assert {app.SESSIONS, app.EVENTS} <= set(ports.OWNED_BUCKETS)


def test_only_the_dge_application_writes_the_dge_buckets():
    # M7 and the target alike: the bucket names occur as store keys only in this module; the other readers import the
    # constants (autonomous, decision_feedback, research_program read `SESSIONS`/`EVENTS`).
    src = REPO / "target" / "src" / "codex_harness"
    # V9 (S8 pilot 68, R-a2): a reader that defines its own local constant for the published-language name may contain the
    # literal; it must never write it.
    v9_readers = {"coordination/application/autonomous.py"}
    writers = []
    for path in sorted(src.rglob("*.py")):
        text = path.read_text()
        if ('"dge_sessions"' in text or '"dge_events"' in text) and path.relative_to(src).as_posix() not in (
                {"research/application/dge.py", "research/ports.py"} | v9_readers):
            writers.append(path.relative_to(src).as_posix())
    assert writers == []
    for reader in v9_readers:
        for call in ast.walk(ast.parse((src / reader).read_text())):
            if (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) and call.func.attr in ("put", "delete")
                    and call.args):
                first = call.args[0]
                assert not (isinstance(first, ast.Constant) and first.value in ("dge_sessions", "dge_events")), reader
                assert not (isinstance(first, ast.Name) and first.id in ("SESSIONS", "EVENTS")), reader
    # a module that imports SESSIONS/EVENTS from the dge application must not put them (other modules' EVENTS differ)
    importers = [path for path in sorted(src.rglob("*.py")) if path.relative_to(src).as_posix() != "research/application/dge.py"
                 and "research.application.dge import" in path.read_text()]
    assert not [p for p in importers if "put(SESSIONS" in p.read_text() or "put(EVENTS" in p.read_text()]


def test_spot_check_the_moved_sessions_run_over_a_memory_store():
    from codex_harness.research.application.dge import DebateSessions
    from codex_harness.storage.adapters.memory_store import MemoryStore

    sessions = DebateSessions(MemoryStore())
    try:
        sessions.status("missing")
    except importlib.import_module(APP).DgeRefused as exc:
        assert exc.reason_code
    else:
        raise AssertionError("an unknown session must be refused")
