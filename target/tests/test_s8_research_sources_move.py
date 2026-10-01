"""S8 pilot 75: the M7 `adapters/research.py` (`ResearchSources`) moved into research, VERBATIM through R-s0
(A/evidence/rebuild/s8/research-sources-move/transcribe.py; DESIGN-s8 §6 V11).

M7 is read only as text through `git show e38aa722:...` and compared by AST (never imported: both packages are named
`codex_harness`). Behaviour is checked on the TARGET only, against literals; the recorded comparison is the
`research.program_tick` golden.
"""
import ast
import importlib
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SOURCE = "e38aa722"
MOD = "codex_harness.research.adapters.research"
M7_PATH = "src/codex_harness/adapters/research.py"


def m7_text():
    return subprocess.run(["git", "-C", str(REPO), "show", f"{SOURCE}:{M7_PATH}"], check=True, capture_output=True,
                          text=True).stdout


def target_text():
    return Path(importlib.import_module(MOD).__file__).read_text()


def classes(src):
    return {n.name: n for n in ast.parse(src).body if isinstance(n, ast.ClassDef)}


def test_names_and_every_statement_are_m7s_and_only_the_imports_and_header_differ():
    ref, ours = ast.parse(m7_text()), ast.parse(target_text())
    body = [n for n in ours.body if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant))]
    rest = lambda tree: [ast.dump(n) for n in tree if not isinstance(n, (ast.Import, ast.ImportFrom))]  # noqa: E731
    assert rest(body) == rest(ref.body) and len(rest(ref.body)) == 1  # the one class, byte-for-AST identical
    (name, klass), = classes(target_text()).items()
    assert name == "ResearchSources"
    methods = [n.name for n in klass.body if isinstance(n, ast.FunctionDef)]
    assert methods == ["__init__", "fetch", "collect", "parse_github", "parse_feed", "github_detail"]
    assert ast.get_docstring(ast.parse(m7_text())) is None and ast.get_docstring(ours).startswith("Research feed sources")


def test_r_s0_the_only_imports_that_moved_are_the_discovery_pressure_and_kernel_names():
    def imports(src):
        return {(n.module, a.name) for n in ast.walk(ast.parse(src)) if isinstance(n, ast.ImportFrom) for a in n.names}

    ref, ours = imports(m7_text()), imports(target_text())
    moved = {("codex_harness.domain.discovery_pressure", name) for name in
             ("ALLOW", "HOLD", "PROACTIVE", "DiscoveryPaused", "unrecorded_hold", "validate_intent")}
    moved |= {("codex_harness.domain.model", "require"), ("codex_harness.domain.model", "utcnow")}
    assert ref - ours == moved
    assert ours - ref == {("codex_harness.kernel.errors", "require"), ("codex_harness.kernel.ids", "utcnow"),
                          *{("codex_harness.research.domain.discovery_pressure", n[1]) for n in moved if "discovery" in n[0]}}
    tree = ast.parse(target_text())
    mods = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert not [m for m in mods if m.startswith(("codex_harness.domain", "codex_harness.application", "codex_harness.adapters",
                                                 "codex_harness.host_os"))]
    assert {m for m in mods if m.startswith("codex_harness.")} == {
        "codex_harness.kernel.errors", "codex_harness.kernel.ids", "codex_harness.research.domain.discovery_pressure"}


def test_the_class_is_the_m7_feed_and_only_urllib_does_io():
    module = importlib.import_module(MOD)
    assert module.ResearchSources.URLS == {"github": "https://github.com/trending", "geeknews": "https://news.hada.io/rss/news"}
    assert "urllib.request" in target_text() and "requests" not in target_text() and "subprocess" not in target_text()


def test_collect_refuses_a_missing_intent_and_holds_a_proactive_fetch_without_an_evaluator_before_any_io():
    from codex_harness.kernel.errors import ContractError
    from codex_harness.research.domain.discovery_pressure import PROACTIVE, DiscoveryPaused

    class Sink:
        def put(self, *args):
            raise AssertionError("no artifact before the gate")

    sources = importlib.import_module(MOD).ResearchSources(Sink())
    sources.fetch = lambda url: pytest.fail("no fetch before the gate")
    with pytest.raises(ContractError):
        sources.collect("github", intent="")
    with pytest.raises(DiscoveryPaused):
        sources.collect("github", intent=PROACTIVE)


def test_parsers_are_the_m7_ones_on_a_small_feed():
    sources = importlib.import_module(MOD).ResearchSources
    rss = ("<rss><channel><item><link>https://e.example/1</link><title>t</title><description>&lt;b&gt;x&lt;/b&gt;</description></item>"
           "<item><link>http://insecure.example/2</link><title>u</title></item></channel></rss>")
    assert sources.parse_feed(rss) == [{"url": "https://e.example/1", "title": "t", "summary": "x"}]
    page = '<article><h2><a href="/o/r">o / r</a></h2><p>A &amp; B</p></article>'
    assert sources.parse_github(page) == [{"url": "https://github.com/o/r", "title": "o/r", "summary": "A & B"}]
