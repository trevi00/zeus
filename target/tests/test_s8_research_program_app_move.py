"""S8 pilot 73: the M7 `ResearchProgram` moved into research, VERBATIM through named rules
(A/evidence/rebuild/s8/research-program-app-move/transcribe.py; DESIGN-s8 §1 V3/V4/V9, §6 V11, §8 V13).

M7 is read only as text through `git show e38aa722:...` and compared by AST (never imported: both packages are named
`codex_harness`). Behaviour is checked on the TARGET only, against literals; the recorded comparison is the
`research.program_records` golden.
"""
import ast
import importlib
import inspect
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "target" / "src" / "codex_harness"
SOURCE = "e38aa722"
APP = "codex_harness.research.application.research_program"
M7_PATH = "src/codex_harness/application/research_program.py"
REWRITTEN = ["__init__", "_row", "resume", "_scope_target", "recover_dispatch", "_revoke_dispatch", "_succeed_dispatch",
             "_revocation_held"]
WRITTEN = {"BUCKET_CANDIDATES": "research_program_candidates", "BUCKET_CYCLES": "research_program_cycles",
           "BUCKET_DISPATCHES": "research_investigation_dispatches", "BUCKET_RECOVERIES": "research_dispatch_recoveries",
           "BUCKET_SUCCESSORS": "research_dispatch_successors", "BUCKET_HEADS": "research_dispatch_heads"}


def m7_text(path=M7_PATH):
    return subprocess.run(["git", "-C", str(REPO), "show", f"{SOURCE}:{path}"], check=True, capture_output=True,
                          text=True).stdout


def target_text(module=APP):
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
        out[key] = node
    return out


def methods(src, name="ResearchProgram"):
    klass = next(n for n in ast.parse(src).body if isinstance(n, ast.ClassDef) and n.name == name)
    return {n.name: n for n in klass.body if isinstance(n, ast.FunctionDef)}


def calls(body):
    """[(line, name)] of every call in a function body, by attribute or plain name, in source order."""
    out = []
    for call in ast.walk(body):
        if isinstance(call, ast.Call):
            name = call.func.attr if isinstance(call.func, ast.Attribute) else getattr(call.func, "id", "")
            out.append((call.lineno, name))
    return sorted(out)


def test_application_is_m7_in_m7_order_and_only_the_rewritten_methods_differ():
    ref, ours = statements(m7_text()), statements(target_text())
    keys = list(ref)
    assert ("ResearchProgram",) in keys and len(keys) == 18
    expected = []
    for key in keys:
        key = ("BUCKET_CANDIDATES", "BUCKET_CYCLES") if key == ("BUCKET_PROGRAMS", "BUCKET_CANDIDATES", "BUCKET_CYCLES") else key
        expected.append(key)
        if key == ("BUCKET_OWNER_ACTIONS",):
            expected += [("BUCKET_RUNS", "OPERATIONS", "RESERVATIONS"), ("BUCKET_JOBS",)]
    assert list(ours) == expected
    for key, node in ref.items():
        if key not in (("ResearchProgram",), ("BUCKET_PROGRAMS", "BUCKET_CANDIDATES", "BUCKET_CYCLES")):
            assert ast.dump(ours[key]) == ast.dump(node), key
    theirs, mine = methods(m7_text()), methods(target_text())
    assert list(mine) == list(theirs)
    assert [k for k in theirs if ast.dump(mine[k]) != ast.dump(theirs[k])] == REWRITTEN


def test_r_p0_row_and_resume_delegate_to_s6_whose_bodies_are_m7s():
    s6, m7 = methods(target_text("codex_harness.research.application.program_state"), "ProgramState"), methods(m7_text())
    for name in ("_row", "resume"):
        assert ast.dump(s6[name]) == ast.dump(m7[name]), name
    mine = methods(target_text())
    assert [ast.unparse(s) for s in mine["_row"].body] == ["return self.state._row(tx, program_id)"]
    assert [ast.unparse(s) for s in mine["resume"].body[1:]] == ["return self.state.resume(program_id)"]
    assert "self.state = ProgramState(store, clock)" in target_text()
    module = importlib.import_module(APP)
    from codex_harness.research.application import program_state
    assert module.BUCKET_PROGRAMS is program_state.BUCKET_PROGRAMS == "research_programs"
    assert "BUCKET_PROGRAMS" not in {n for key in statements(target_text()) for n in key}


def test_scope_target_is_an_instance_method_and_m7s_refusal_fields_and_order_are_kept():
    ours, theirs = methods(target_text())["_scope_target"], methods(m7_text())["_scope_target"]
    assert [d.id for d in theirs.decorator_list] == ["staticmethod"] and ours.decorator_list == []
    assert [a.arg for a in ours.args.args] == ["self", "tx", "row", "number", "owner"]

    def fields(fn):
        found = [c for c in ast.walk(fn) if isinstance(c, ast.Call) and getattr(c.func, "id", "") == "unavailable"
                 and c.args and isinstance(c.args[0], ast.Constant)]
        return [c.args[0].value for c in sorted(found, key=lambda c: c.lineno)]
    assert sorted(fields(ours)) == sorted(fields(theirs))
    assert fields(ours) == ["cycle_owner", "owner_action", "binding", "binding.intent_id", "binding.intent_id", "binding.attempts",
                            "binding.attempts"]
    # R-p4 ORDER: the added require, the launches query, the single-launch refusal, then the guard and the authenticity predicate
    order = [name for _, name in calls(ours) if name in ("require", "launches", "unavailable", "authentic", "get", "action_id")]
    assert order[:4] == ["require", "launches", "unavailable", "get"] and "action_id" not in order
    assert order.index("authentic") > order.index("get")
    text = ast.unparse(ours)
    assert "isinstance(binding, dict) and self.launch_facts.authentic(action, owner)" in text
    assert text.count("self.launch_facts.launches(tx, owner)") == 1
    for name in ("RESEARCH_DISPATCH", "LAUNCHING", "RUNNING", "action_id", "research_launch_id"):
        assert name not in target_text()


def test_r_p5_calls_go_through_the_ports_with_one_require_each_at_the_first_use():
    text, m7 = target_text(), m7_text()
    assert m7.count("quarantine_outbox(") == 3 and text.count("self.outbox_quarantine.quarantine(") == 3
    assert m7.count("current_fence(") == 3 and text.count("self.fences.current(") == 3
    assert m7.count("advance_fence(") == 1 and text.count("self.fences.advance(") == 1
    for old in ("quarantine_outbox", "current_fence", "advance_fence"):
        assert old not in text
    for message, port, first_use in (("Outbox quarantine is not wired", "outbox_quarantine", "self.outbox_quarantine.quarantine("),
                                     ("Execution fences are not wired", "fences", "self.fences.current("),
                                     ("Research launch facts are not wired", "launch_facts", "self.launch_facts.launches(")):
        require = f"require(self.{port} is not None, '{message}')"
        assert text.count(require) == 1, port
        assert text.index(require) < text.index(first_use), port
    # `_revocation_held` reads the fence, so it becomes an instance method (it was a staticmethod in M7)
    assert methods(m7)["_revocation_held"].decorator_list and methods(text)["_revocation_held"].decorator_list == []


def test_init_ports_are_keyword_only_after_progress_policy_and_m7_signature_is_unchanged():
    new, old = methods(target_text())["__init__"].args, methods(m7_text())["__init__"].args
    assert [a.arg for a in new.args] == [a.arg for a in old.args] == ["self", "store", "clock", "token", "progress_policy"]
    assert old.kwonlyargs == []
    assert [a.arg for a in new.kwonlyargs] == ["launch_facts", "fences", "outbox_quarantine"]
    assert all(isinstance(d, ast.Constant) and d.value is None for d in new.kw_defaults)


def test_imports_are_only_kernel_intake_knowledge_domains_and_research_homes():
    tree = ast.parse(target_text())
    mods = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module.startswith("codex_harness.")}
    assert mods == {"codex_harness.intake.domain.portfolio", "codex_harness.kernel.errors", "codex_harness.kernel.ids",
                    "codex_harness.knowledge.domain.promotion", "codex_harness.research.application.audit_progress",
                    "codex_harness.research.application.dge", "codex_harness.research.application.program_state",
                    "codex_harness.research.domain.audit_progress", "codex_harness.research.domain.research_attempt_scope",
                    "codex_harness.research.domain.research_hold", "codex_harness.research.domain.research_investigations",
                    "codex_harness.research.domain.research_program"}
    assert not [m for m in mods if m.startswith(("codex_harness.coordination", "codex_harness.domain", "codex_harness.application"))]
    knowledge = {a.name: a.asname for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)
                 and n.module == "codex_harness.knowledge.domain.promotion" for a in n.names}
    assert knowledge == {"BUCKET": "BUCKET_PROMOTIONS"}


def test_v9_local_constants_equal_their_coordination_owners():
    from codex_harness.coordination.application import autonomous
    from codex_harness.coordination.application.fleet import state as fleet
    from codex_harness.coordination.application.owner_actions import state as owner_actions

    module = importlib.import_module(APP)
    assert (module.BUCKET_RUNS, module.OPERATIONS, module.RESERVATIONS) == (autonomous.BUCKET, autonomous.OPERATIONS,
                                                                          autonomous.RESERVATIONS)
    assert (module.BUCKET_RUNS, module.OPERATIONS, module.RESERVATIONS) == ("autonomous_runs", "operations",
                                                                          "invocation_reservations")
    assert module.BUCKET_JOBS == fleet.BUCKET_JOBS == "fleet_jobs"
    assert module.BUCKET_OWNER_ACTIONS == owner_actions.BUCKET_ACTIONS == "owner_actions"


def test_r_p3_promotions_bucket_has_one_owner_in_the_knowledge_domain():
    from codex_harness.knowledge.application import promotion
    from codex_harness.knowledge.domain import promotion as domain

    module = importlib.import_module(APP)
    assert domain.BUCKET == promotion.BUCKET == module.BUCKET_PROMOTIONS == "promotions"
    assert not [n for n in ast.parse(target_text("codex_harness.knowledge.application.promotion")).body
                if isinstance(n, ast.Assign) and defined(n) == ("BUCKET",)]


def _params(fn):
    return [(p.name, p.kind, p.default) for p in inspect.signature(fn).parameters.values() if p.name != "self"]


def _protocol_methods(proto):
    return {n: f for n, f in vars(proto).items() if inspect.isfunction(f) and not n.startswith("_")}


def test_ports_are_structurally_satisfied_by_the_coordination_implementations():
    from codex_harness.coordination.application import execution_fence, outbox_relay
    from codex_harness.coordination.application.research_launch_facts import ResearchLaunchFacts
    from codex_harness.research import ports

    for proto, impl in ((ports.ResearchLaunchFacts, ResearchLaunchFacts), (ports.ExecutionFences, execution_fence),
                        (ports.OutboxQuarantine, outbox_relay)):
        for name, fn in _protocol_methods(proto).items():
            declared = [p for p in _params(fn)]
            actual = _params(getattr(impl, name))
            assert actual[:len(declared)] == declared, (proto.__name__, name)
            assert all(p[1] is inspect.Parameter.KEYWORD_ONLY for p in actual[len(declared):]), (proto.__name__, name)
    assert sorted(_protocol_methods(ports.ResearchLaunchFacts)) == ["authentic", "launches"]
    assert sorted(_protocol_methods(ports.ExecutionFences)) == ["advance", "current"]
    assert sorted(_protocol_methods(ports.OutboxQuarantine)) == ["quarantine"]
    assert outbox_relay.quarantine is outbox_relay._quarantine


def writers(values, names):
    """Relative paths of target modules with a `.put`/`.delete` whose first argument is one of `values` (a literal) or `names`."""
    found = set()
    for path in sorted(SRC.rglob("*.py")):
        for call in ast.walk(ast.parse(path.read_text())):
            if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) and call.func.attr in ("put", "delete") and call.args:
                first = call.args[0]
                if (isinstance(first, ast.Constant) and first.value in values) or (isinstance(first, ast.Name) and first.id in names):
                    found.add(path.relative_to(SRC).as_posix())
    return found


def test_v4_research_owns_the_program_buckets_and_only_this_module_writes_them():
    from codex_harness.research import ports

    module = importlib.import_module(APP)
    for name, value in WRITTEN.items():
        assert getattr(module, name) == value
        assert ports.OWNED_BUCKETS.count(value) == 1, value
    assert ports.OWNED_BUCKETS.count("research_programs") == 1
    # every bucket this module writes, by the first argument of its puts (names resolved through the module's constants)
    written = {getattr(module, c.args[0].id) for c in ast.walk(ast.parse(target_text()))
               if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute) and c.func.attr in ("put", "delete")
               and isinstance(c.args[0], ast.Name)}
    assert written == set(WRITTEN.values()) | {"research_programs"}
    assert not [c for c in ast.walk(ast.parse(target_text())) if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
                and c.func.attr in ("put", "delete") and not isinstance(c.args[0], ast.Name)]
    for context in ("coordination", "evidence", "knowledge", "review", "delivery", "intake", "routing", "storage"):
        other = importlib.import_module(f"codex_harness.{context}.ports") if (SRC / context / "ports.py").exists() else None
        assert other is None or not set(WRITTEN.values()) & set(getattr(other, "OWNED_BUCKETS", ())), context
    assert writers(set(WRITTEN.values()), set(WRITTEN)) == {"research/application/research_program.py"}
    assert writers({"research_programs"}, {"BUCKET_PROGRAMS"}) == {"research/application/research_program.py",
                                                                    "research/application/program_state.py"}


def _program():
    from codex_harness.research.application.research_program import ResearchProgram
    from codex_harness.storage.adapters.memory_store import MemoryStore

    return ResearchProgram, MemoryStore


def test_scope_target_refuses_a_double_launch_with_the_cycle_owner_field_as_in_m7():
    from codex_harness.coordination.application.owner_actions.state import BUCKET_ACTIONS
    from codex_harness.coordination.application.research_launch_facts import ResearchLaunchFacts
    from codex_harness.research.domain.research_program import ProgramRefused

    ResearchProgram, MemoryStore = _program()
    programs = ResearchProgram(MemoryStore(), launch_facts=ResearchLaunchFacts())
    with programs.store.transaction() as tx:
        for key in ("a", "b"):
            tx.put(BUCKET_ACTIONS, key, {"id": key, "kind": "research_dispatch", "launch_id": "owner-1"})
        with pytest.raises(ProgramRefused) as info:
            programs._scope_target(tx, {"id": "rp", "config": {"attempt_scope_source": {}}}, 1, "owner-1")
    assert (info.value.reason_code, info.value.field) == ("attempt_scope_target_unavailable", "cycle_owner")


def test_each_unwired_port_is_refused_by_its_added_require_at_its_first_use():
    from codex_harness.kernel.errors import ContractError

    ResearchProgram, MemoryStore = _program()
    programs = ResearchProgram(MemoryStore())
    assert (programs.launch_facts, programs.fences, programs.outbox_quarantine) == (None, None, None)
    with programs.store.transaction() as tx, pytest.raises(ContractError) as info:
        programs._scope_target(tx, {"id": "rp", "config": {"attempt_scope_source": {}}}, 1, "owner-1")
    assert str(info.value) == "Research launch facts are not wired"
