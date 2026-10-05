"""S8 pilot 87: the M7 closure review page moved into intake, VERBATIM through one named rule
(A/evidence/rebuild/s8/ticket-review-move/transcribe.py; DESIGN-s8 §6 V11).

M7 is read only as text through `git show e38aa722:...` and compared by AST (never imported: both packages are named
`codex_harness`). Behaviour is checked on the TARGET only, against literals; the recorded comparison is the
`intake.ticket_review` golden.
"""
import ast
import importlib
import subprocess
from html.parser import HTMLParser
from pathlib import Path

from _layout import REPO

SOURCE = "e38aa722"
MODULE = "codex_harness.intake.adapters.ticket_review"
M7_PATH = "src/codex_harness/adapters/ticket_review.py"
R_S0_IMPORTS = {"codex_harness.kernel.ids": ["canonical"]}
M7_IMPORTS = {"codex_harness.domain.model": ["canonical"]}
ENV = "sha256:" + "e1" * 32
EV = "sha256:" + "c1" * 32


def m7_text():
    return subprocess.run(["git", "-C", str(REPO), "show", f"{SOURCE}:{M7_PATH}"], check=True, capture_output=True, text=True).stdout


def target_text():
    return Path(importlib.import_module(MODULE).__file__).read_text()


def statements(src):
    out = {}
    for node in ast.parse(src).body:
        if isinstance(node, (ast.Import, ast.ImportFrom)) or (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)):
            continue
        assert isinstance(node, ast.FunctionDef)
        out[node.name] = node
    return out


def from_imports(src):
    return {n.module: [a.name for a in n.names] for n in ast.parse(src).body if isinstance(n, ast.ImportFrom)}


def review(**content):
    return {
        "ticket": {"id": "TKT-1", "content": {"title": "T", "problem": "P", "impact": "I", "scope": ["s"], "acceptance_criteria": ["a"],
                                              "rollback": "R", **content}},
        "packet": {"environment_ref": ENV, "criteria": [{"index": 0, "evidence_refs": [EV]}], "reason": "why", "revision": 1, "sequence": 1,
                   "issued_at": "i", "expires_at": "e", "solution_commit": "c" * 40, "policy_commit": "p" * 40, "policy_hash": "h"},
        "policy": {"required_human_signers": [], "required_signers": ["robot"], "signers": [{"principal": "robot", "role": "automation"}]},
        "documents": {ENV: {"observed_at": "o1", "details": {"k": 1}}, EV: {"observed_at": "o2", "details": {"k": 2}}},
        "packet_ref": "sha256:" + "9a" * 32, "time_status": "recheck_at_close"}


def render(**kwargs):
    module = importlib.import_module(MODULE)
    return module.render_ticket_review(review(**kwargs), "packet.json")


def test_every_statement_is_m7_s_by_ast_in_m7_order():
    ref, ours = statements(m7_text()), statements(target_text())
    assert list(ours) == list(ref) == ["render_ticket_review"]
    for key in ref:
        assert ast.dump(ours[key]) == ast.dump(ref[key]), key


def test_the_only_change_is_the_import_rule_r_s0_and_the_header():
    old, new = from_imports(m7_text()), from_imports(target_text())
    assert old == M7_IMPORTS and new == R_S0_IMPORTS
    marker = "\n\ndef render_ticket_review"
    assert m7_text().split(marker, 1)[1] == target_text().split(marker, 1)[1]
    doc = ast.get_docstring(ast.parse(target_text()))
    assert doc.startswith(ast.get_docstring(ast.parse(m7_text())))
    for line in ("Layer: adapters", "Context: intake", "Entry points: render_ticket_review", "Contracts: INV-TICKET-001"):
        assert line in doc.splitlines()


def test_imports_are_only_the_kernel_home_and_the_module_never_reads_or_writes():
    tree = ast.parse(target_text())
    mods = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert mods == set(R_S0_IMPORTS)
    assert sorted(a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names) == ["html", "json"]
    for word in (".put(", "open(", "write", "subprocess", "psycopg", "datetime", "os."):
        assert word not in target_text().split('"""', 2)[2], word


def test_the_page_is_deterministic_inert_and_names_its_inputs():
    page = render()
    assert page == render() and page.startswith('<!doctype html>\n<html lang="ko">')
    assert "script-src 'none'" in page and "default-src 'none'" in page and "form-action 'none'" in page
    assert "<title>Zeus 종료 검토 · T</title>" in page and "sha256:" + "9a" * 32 in page
    assert "사람 승인 요구 없음" in page and "서명 기한" in page and "인수 기준 1" in page


def test_markup_in_every_displayed_text_is_escaped():
    payload = '<script src="x"></script><img src=x onerror="alert(1)">'
    page = render(title=payload, problem=payload, impact=payload, scope=[payload], acceptance_criteria=[payload], rollback=payload)

    class Tags(HTMLParser):
        def __init__(self):
            super().__init__()
            self.tags, self.attributes = set(), []

        def handle_starttag(self, tag, attrs):
            self.tags.add(tag)
            self.attributes.extend(attrs)

    parser = Tags()
    parser.feed(page)
    assert not parser.tags & {"script", "img", "iframe", "form", "a", "object", "base"}
    assert not [n for n, _ in parser.attributes if n.startswith("on")]
    assert "&lt;script" in page and "<script" not in page


def test_a_large_preview_is_bounded_and_says_so():
    module = importlib.import_module(MODULE)
    value = review()
    value["documents"][ENV]["details"] = {"large": "<" * 300000}
    page = module.render_ticket_review(value, "packet.json")
    assert page.count("미리보기 일부만 표시됨") == 1 and len(page.encode("utf-8")) < 400000


def test_the_environment_preview_comes_first_and_the_total_budget_runs_out():
    module = importlib.import_module(MODULE)
    value = review()
    value["documents"][EV]["details"] = {"large": "x" * 100000}
    value["packet"]["criteria"][0]["evidence_refs"] = [EV] * 5
    value["documents"][ENV]["details"] = {"marker": "ENVIRONMENT_STILL_VISIBLE"}
    page = module.render_ticket_review(value, "packet.json")
    assert "ENVIRONMENT_STILL_VISIBLE" in page and "미리보기 일부만 표시됨" in page


def test_each_time_status_has_its_message_and_an_unknown_one_is_a_key_error():
    module = importlib.import_module(MODULE)
    for status, text in (("expired", "서명 기한이 지났습니다"), ("future", "미래입니다"), ("recheck_at_close", "다시 검증합니다")):
        value = review()
        value["time_status"] = status
        assert text in module.render_ticket_review(value, "p")
    value = review()
    value["time_status"] = "closed"
    try:
        module.render_ticket_review(value, "p")
    except KeyError as exc:
        assert exc.args == ("closed",)
    else:
        raise AssertionError("an unknown time_status must raise")


def test_a_signer_without_a_role_is_a_runtime_error_and_the_review_is_not_mutated():
    module = importlib.import_module(MODULE)
    value = review()
    value["policy"]["required_signers"] = ["nobody"]
    before = repr(value)
    try:
        module.render_ticket_review(value, "p")
    except RuntimeError:
        pass
    else:
        raise AssertionError("a StopIteration inside the generator becomes a RuntimeError")
    assert repr(value) == before
