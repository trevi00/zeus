"""S8 V32 (DESIGN-s8 §30, §30.1): the council-delivery and correction-feedback composition, rules R-cd1..R-cd5.

The base text is read through `git show` at the base head of the change (never imported). Behaviour is checked on
the TARGET against literals; the recorded comparison is the `context.composition_council` golden, and the S2
`context.composition` family pins the legacy branch's bytes.
"""
import ast
import dataclasses
import inspect
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from codex_harness.context import ports
from codex_harness.context.application.compose import ContextComposer
from codex_harness.context.domain.composition import CompositionRequest
from codex_harness.kernel.errors import ContractError
from codex_harness.research.adapters import correction_feedback
from codex_harness.research.adapters.council_composition import CouncilCompositionAdmission
from codex_harness.research.domain import council_input

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "target" / "src" / "codex_harness"
BASE = "c943966d2604f0d0dced782d3a37416cf09ee3da"
COMPOSE = "target/src/codex_harness/context/application/compose.py"
REQUEST = "target/src/codex_harness/context/domain/composition.py"
RUN_TASK = "target/src/codex_harness/execution/application/run_task.py"
ADMISSION_METHODS = {"admit_delivery", "council_budget", "admit_council", "admit_feedback"}
NEW_FIELDS = ("delivery", "correction_feedback", "delivery_reader")


def base_text(path):
    return subprocess.run(["git", "-C", str(REPO), "show", f"{BASE}:{path}"], check=True, capture_output=True,
                          text=True).stdout


def now_text(path):
    return (REPO / path).read_text()


def method(src, klass, name):
    node = next(n for n in ast.parse(src).body if isinstance(n, ast.ClassDef) and n.name == klass)
    return next(n for n in node.body if isinstance(n, ast.FunctionDef) and n.name == name)


def imports(path):
    out = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.ImportFrom) and node.module:
            out.add(node.module)
        elif isinstance(node, ast.Import):
            out.update(a.name for a in node.names)
    return out


# ---- R-cd1: the context port ---------------------------------------------------------------------------------
def test_r_cd1_the_port_has_four_methods_and_the_policy_name():
    names = {n for n, v in vars(ports.CompositionAdmission).items() if inspect.isfunction(v) and n != "__init__"}
    assert names == ADMISSION_METHODS
    assert ports.CompositionAdmission.__annotations__ == {"council_policy": "str"}


# ---- R-cd2: the composer -------------------------------------------------------------------------------------
def test_r_cd2_the_refusal_is_the_first_statement_and_admission_is_keyword_only():
    compose = method(now_text(COMPOSE), "ContextComposer", "compose")
    assert [a.arg for a in compose.args.kwonlyargs] == ["admission"] and compose.args.kw_defaults[0].value is None
    body = compose.body[1:] if isinstance(compose.body[0], ast.Expr) else compose.body  # the docstring
    first = body[0]
    assert isinstance(first, ast.Expr) and ast.unparse(first.value.func) == "require"
    text = ast.unparse(first)
    assert "admission is not None" in text and "request.delivery is None" in text
    assert "request.correction_feedback is None" in text and "Composition admission is not wired" in text


def test_r_cd2_a_delivery_or_feedback_without_admission_refuses_before_any_effect():
    def boom(*args, **kwargs):
        raise AssertionError("an effect happened before the refusal")

    composer = ContextComposer(SimpleNamespace(put=boom), "root", SimpleNamespace(revision=boom), None)
    base = dict(agent="a", key="k", objective="o", evidence={}, cwd="c", snapshot="s", runtime_policy_digest="d",
                reader_python="p", provider="codex", default_provider="codex")
    for extra in ({"delivery": {"inline": {}}}, {"correction_feedback": {"findings": {}}}):
        with pytest.raises(ContractError, match="Composition admission is not wired"):
            composer.compose(CompositionRequest(**base, **extra))


def test_r_cd2_the_legacy_branch_is_unchanged_but_for_the_five_delivery_statements():
    before = method(base_text(COMPOSE), "ContextComposer", "compose").body
    after = {ast.dump(n) for n in method(now_text(COMPOSE), "ContextComposer", "compose").body}
    changed = [ast.unparse(n).split("=")[0].strip() for n in before if ast.dump(n) not in after]
    assert changed == ["window, reserved", "items", "required", "contract", "measurement"]
    for name in ("retain", "__init__"):
        assert (ast.dump(method(base_text(COMPOSE), "ContextComposer", name))
                == ast.dump(method(now_text(COMPOSE), "ContextComposer", name)))
    source = now_text(COMPOSE)
    # M7's delivery order: the admission right after the raw put, the preflights before compile_context.
    for earlier, later in (("self.artifacts.put(canonical(r.evidence)", "admission.admit_delivery("),
                           ("admission.admit_delivery(", "admission.council_budget()"),
                           ("admission.admit_council(len(", "compile_context(r.agent"),
                           ("admission.admit_feedback(", "compile_context(r.agent")):
        assert source.index(earlier) < source.index(later), (earlier, later)


# ---- R-cd3: the request --------------------------------------------------------------------------------------
def test_r_cd3_the_request_gains_only_additive_defaults():
    fields = {f.name: f for f in dataclasses.fields(CompositionRequest)}
    for name in NEW_FIELDS:
        assert fields[name].default is None
    base_names = [n.target.id for c in ast.parse(base_text(REQUEST)).body
                  if isinstance(c, ast.ClassDef) and c.name == "CompositionRequest"
                  for n in c.body if isinstance(n, ast.AnnAssign)]
    assert [f.name for f in dataclasses.fields(CompositionRequest)] == base_names + list(NEW_FIELDS)
    assert "council" not in fields


# ---- R-cd4: RunTask ------------------------------------------------------------------------------------------
def test_r_cd4_one_early_refusal_before_any_reservation_or_provider_and_no_old_refusal():
    source = now_text(RUN_TASK)
    assert "composition is not wired" not in source
    run = method(source, "RunTask", "_run")
    guard = next(n for n in run.body if isinstance(n, ast.If) and "correction_feedback is not None" in ast.unparse(n.test))
    assert ast.unparse(guard.test) == "delivery is not None or correction_feedback is not None"
    assert "self.composition_admission is not None" in ast.unparse(guard.body[0])
    assert "Composition admission is not wired" in ast.unparse(guard.body[0])
    text = ast.unparse(run)
    for later in ("self.store.transaction()", "self.invocations.", "self.composer.compose(", ".reserve("):
        assert text.index("Composition admission is not wired") < text.index(later), later
    # The values and the port reach the composer; the council role context keeps its own port.
    assert "delivery=delivery" in text and "correction_feedback=correction_feedback" in text
    assert "delivery_reader=DELIVERY_ARTIFACT_READER if delivery is not None else None" in text
    assert "admission=self.composition_admission" in text and "self.council.admitted_delivery" not in text
    init = method(source, "RunTask", "__init__")
    assert "composition_admission" in [a.arg for a in init.args.kwonlyargs] and "admission" in [a.arg for a in init.args.kwonlyargs]
    assert "self.composition_admission = composition_admission" in ast.unparse(init)


# ---- R-cd5: the research adapter -----------------------------------------------------------------------------
def test_r_cd5_pure_delegation_and_the_policy_name():
    assert CouncilCompositionAdmission.council_policy == council_input.SCHEMA == "urn:zeus:council-input:2"
    assert {n for n, v in vars(CouncilCompositionAdmission).items() if inspect.isfunction(v)} == ADMISSION_METHODS | {"__init__"}
    klass = next(n for n in ast.parse((SRC / "research/adapters/council_composition.py").read_text()).body
                 if isinstance(n, ast.ClassDef))
    for fn in (n for n in klass.body if isinstance(n, ast.FunctionDef) and n.name != "__init__"):
        [statement] = fn.body
        assert isinstance(statement, ast.Return) and isinstance(statement.value, ast.Call), fn.name
    admission = CouncilCompositionAdmission()
    assert admission.feedback_require is correction_feedback.require_context
    assert admission.council_budget() == council_input.council_budget()
    assert admission.admit_council(5000, 1000) == council_input.admit_required(5000, 1000)
    with pytest.raises(council_input.CouncilInputOverflow):
        admission.admit_council(10 ** 6, 1000)
    seen = []
    CouncilCompositionAdmission(lambda rendered, usable: seen.append((rendered, usable))).admit_feedback(7, 9)
    assert seen == [(7, 9)]
    with pytest.raises(correction_feedback.CorrectionFeedbackRefused, match="feedback_context_insufficient"):
        admission.admit_feedback(10, 9)
    with pytest.raises(ContractError, match="requires a read-only dge_role"):
        admission.admit_delivery("a", "plan", True, None, {}, {"inline": {}})


# ---- the import homes and the DAG ----------------------------------------------------------------------------
def test_import_homes_and_the_dag():
    for path in (SRC / "context").rglob("*.py"):
        found = imports(path)
        assert not {m for m in found if m.startswith(("codex_harness.research", "codex_harness.execution"))}, path
    assert {m for m in imports(SRC / "research/adapters/council_composition.py") if m.startswith("codex_harness")} == {
        "codex_harness.research.adapters", "codex_harness.research.domain"}
    assert not {m for m in imports(SRC / "execution/application/run_task.py") if m.startswith("codex_harness.research")}
