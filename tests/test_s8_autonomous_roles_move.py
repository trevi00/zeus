"""S8 pilot 81: the M7 `dge_role` executor action moved into research, VERBATIM through named rules
(A/evidence/rebuild/s8/autonomous-roles-move/transcribe.py; DESIGN-s8 §6 V11).

M7 is read only as text through `git show e38aa722:...` and compared by AST (never imported: both packages are named
`codex_harness`). Behaviour is checked on the TARGET only, against literals; the recorded comparison is the
`research.autonomous_roles` golden.
"""
import ast
import importlib
import subprocess
from pathlib import Path

import pytest
from _layout import REPO

SOURCE = "e38aa722"
MODULE = "codex_harness.research.adapters.autonomous_roles"
M7_PATH = "src/codex_harness/adapters/autonomous_roles.py"
R_S0_IMPORTS = {
    "codex_harness.kernel.errors": ["require"],
    "codex_harness.research.domain.autonomous": ["DEBATE_ROLES", "MAX_ROLE_ENTRIES", "RESEARCHER", "SSOT_DECISIONS"],
    "codex_harness.research.domain.council": ["AGENTS", "CONDUCTOR_ROLE", "DBA", "FIELD_LIMITS", "IMPROVEMENT_LEAD", "RESEARCH_LEAD"],
    "codex_harness.research.domain.dge": ["CLAIM_KINDS", "DECISIONS", "QUESTION_STATUSES", "SEVERITIES", "VERDICTS"],
}
COUNCIL_INPUT = ["DBA_REPORT", "IMPROVEMENT_PROPOSAL", "PACKET", "RESEARCH_PROPOSAL", "admit_delivery", "output_limit", "preceding", "SCHEMA"]
FUNCTIONS = ["_object", "_enum", "_limited", "_limits", "_claim", "_question", "_listed", "role_objective", "council_delivery",
             "admitted_delivery", "isolation_reference", "role_context", "role_schema", "execute_role"]
BASE = "a1" * 20


def m7_text():
    return subprocess.run(["git", "-C", str(REPO), "show", f"{SOURCE}:{M7_PATH}"], check=True, capture_output=True, text=True).stdout


def target_text():
    return Path(importlib.import_module(MODULE).__file__).read_text()


def defined(node):
    if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
        return (node.name,)
    if isinstance(node, ast.Assign):
        return tuple(n.id for t in node.targets for n in ast.walk(t) if isinstance(n, ast.Name))
    raise AssertionError(ast.dump(node)[:80])


def statements(src):
    out = {}
    for node in ast.parse(src).body:
        if isinstance(node, (ast.Import, ast.ImportFrom)) or (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)):
            continue
        out[defined(node)] = node
    return out


def from_imports(src):
    out = {}
    for n in ast.parse(src).body:
        if isinstance(n, ast.ImportFrom):
            out.setdefault(n.module, []).extend(a.name + (" as " + a.asname if a.asname else "") for a in n.names)
    return out


def test_every_statement_is_m7_s_by_ast_in_m7_order():
    ref, ours = statements(m7_text()), statements(target_text())
    assert list(ours) == list(ref)
    assert [k[0] for k in ref if k[0] in FUNCTIONS] == FUNCTIONS
    assert len(ref) == 51
    for key in ref:
        assert ast.dump(ours[key]) == ast.dump(ref[key]), key


def test_the_only_change_is_the_import_rule_r_s0_and_the_header():
    old, new = from_imports(m7_text()), from_imports(target_text())
    domain = {k.replace("codex_harness.domain.", "codex_harness.research.domain."): v for k, v in old.items() if k.startswith("codex_harness.domain.")
              and k != "codex_harness.domain.model"}
    assert {k: v for k, v in new.items() if k.startswith("codex_harness.research.")} == domain
    assert new["codex_harness.kernel.errors"] == old["codex_harness.domain.model"] == ["require"]
    assert sorted(new["codex_harness.research.domain.council_input"]) == sorted(COUNCIL_INPUT[:-1] + ["SCHEMA as INPUT_POLICY"])
    assert {k: v for k, v in new.items() if k not in R_S0_IMPORTS and not k.startswith("codex_harness.research.domain.council_input")} == {
        "__future__": ["annotations"]}
    marker = "\n\nTEXT = "
    assert m7_text().split(marker, 1)[1] == target_text().split(marker, 1)[1]
    doc = ast.get_docstring(ast.parse(target_text()))
    assert doc.startswith(ast.get_docstring(ast.parse(m7_text())))
    for line in ("Layer: adapters", "Context: research"):
        assert line in doc.splitlines()
    entry = [line for line in doc.splitlines() if line.startswith("Entry points:")]
    assert entry == ["Entry points: role_objective, council_delivery, admitted_delivery, isolation_reference, role_context, role_schema, execute_role"]


def test_imports_are_only_inner_homes_and_the_module_never_writes():
    tree = ast.parse(target_text())
    mods = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module.startswith("codex_harness.")}
    assert mods == set(R_S0_IMPORTS) | {"codex_harness.research.domain.council_input"}
    assert [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names] == ["copy"]
    body = target_text().split('"""', 2)[2]
    for word in (".put(", "open(", "write", "subprocess", "psycopg", "codex_harness.domain", "codex_harness.adapters"):
        assert word not in body, word


def test_the_module_has_no_raise_and_no_except_every_refusal_is_a_require():
    """Structural: the moved source carries no `Raise`/`ExceptHandler` node (the S8 move rule); behaviour is covered by
    test_every_refusal_path_raises_a_contract_error_with_its_message."""
    tree = ast.parse(target_text())
    assert not [n for n in ast.walk(tree) if isinstance(n, (ast.Raise, ast.ExceptHandler))]


def roles():
    return importlib.import_module(MODULE)


def _refuse_role_objective():
    roles().role_objective("research_lead", "not an object")


REFUSALS = [
    (_refuse_role_objective, "Role details must be an object"),
    (lambda: roles().council_delivery("attacker", details("attacker")), "Council delivery is defined for the debate roles only"),
    (lambda: roles().council_delivery("conductor", details("research_lead")), "Council delivery role mismatch"),
    (lambda: roles().council_delivery("conductor", {k: v for k, v in details("conductor").items() if k != "ssot"}),
     "Council delivery input missing: ssot"),
    (lambda: roles().council_delivery("conductor", details("conductor", packet=[])),
     "Council delivery packet and dba_report must be objects"),
    (lambda: roles().admitted_delivery("conductor", "task", True, "dge:conductor", details("conductor"), {}),
     "Council delivery requires a read-only dge_role execution"),
    (lambda: roles().admitted_delivery("conductor", "dge_role", True, "dge:conductor", details("conductor"), {}),
     "Council delivery names no debate role"),
    (lambda: roles().admitted_delivery("conductor", "dge_role", True, "dge:attacker", details("conductor"),
                                       roles().council_delivery("conductor", details("conductor"))),
     "Council delivery role, stage and agent must agree"),
    (lambda: roles().admitted_delivery("conductor", "dge_role", True, "dge:conductor", details("conductor", round=2),
                                       roles().council_delivery("conductor", details("conductor"))),
     "Council delivery is not the projection of this task"),
    (lambda: roles().isolation_reference({"mode": "m"}), "Isolation configuration carries no digest"),
    (lambda: roles().isolation_reference({"mode": "m", "digest": ""}), "Isolation configuration carries no digest"),
    (lambda: roles().role_schema("attacker", {}), "Role details must carry the pinned plan acceptance_criteria"),
    (lambda: roles().role_schema("attacker", {"acceptance_criteria": ["a", "a"]}),
     "Role details must carry the pinned plan acceptance_criteria"),
]


@pytest.mark.parametrize("refuse,message", REFUSALS, ids=[m + f" #{i}" for i, (_, m) in enumerate(REFUSALS)])
def test_every_refusal_path_raises_a_contract_error_with_its_message(refuse, message):
    """Behaviour: each pure refusal path of the module, driven through the public functions, raises `ContractError`
    carrying that path's declared message (the `execute_role` refusals need an executor and are driven in
    ported/test_autonomous_roles.py)."""
    from codex_harness.kernel.errors import ContractError

    with pytest.raises(ContractError) as info:
        refuse()
    assert str(info.value) == message


def details(role, **overrides):
    out = {"role": role, "run_id": "r", "base_revision": BASE, "round": 1, "packet": {"claims": []}, "packet_digest": "sha256:p", "dba_report": {"unknowns": []},
           "snapshot_digest": "sha256:s", "report_digest": "sha256:d", "relay": {}, "acceptance_criteria": ["c1"], "blocker_rule": "rule",
           "research_proposal": {"summary": "s"}, "improvement_proposal": {"summary": "i"}, "ssot": {}, "prior_outputs": []}
    out.update(overrides)
    return out


def test_the_delivery_is_the_deep_copied_projection_and_admitted_exactly_for_its_own_task():
    from codex_harness.kernel.errors import ContractError

    module = roles()
    d = details("conductor")
    delivery = module.council_delivery("conductor", d)
    assert delivery["schema"] == "urn:zeus:council-delivery:1" and delivery["input_policy"] == "urn:zeus:council-input:2"
    assert list(delivery["inline"]) == list(module.INLINE_DELIVERY + ("research_proposal", "improvement_proposal"))
    assert delivery["inline"]["packet"] == d["packet"] and delivery["inline"]["packet"] is not d["packet"]
    assert delivery["not_inline"]["ssot"]["operation"] == ["pointer", "--pointer", "/ssot", "--cursor", "0", "--limit", "8000"]
    assert module.admitted_delivery("conductor", "dge_role", True, "dge:conductor", d, delivery)["role"] == "conductor"
    with pytest.raises(ContractError, match="requires a read-only dge_role execution"):
        module.admitted_delivery("conductor", "dge_role", False, "dge:conductor", d, delivery)
    with pytest.raises(ContractError, match="role, stage and agent must agree"):
        module.admitted_delivery("lead:research", "dge_role", True, "dge:conductor", d, delivery)
    with pytest.raises(ContractError, match="not the projection of this task"):
        module.admitted_delivery("conductor", "dge_role", True, "dge:conductor", details("conductor", round=2), delivery)
    with pytest.raises(ContractError, match="input missing: ssot"):
        module.council_delivery("conductor", {k: v for k, v in d.items() if k != "ssot"})


def test_the_module_object_satisfies_the_council_delivery_port_signatures():
    import inspect

    module = roles()
    assert list(inspect.signature(module.role_context).parameters) == ["isolation"]
    assert list(inspect.signature(module.admitted_delivery).parameters) == ["agent", "action", "read_only", "stage", "details", "delivery"]
    assert module.role_context()["phase"] == "pre_implementation" and module.role_context()["isolation"] is None
    assert module.role_context({"mode": "m", "digest": "d", "x": 1})["isolation"] == {"mode": "m", "digest": "d"}


def test_the_criterion_roles_pin_the_plan_criteria_and_the_static_schema_stays_unmodified():
    from codex_harness.kernel.errors import ContractError

    module = roles()
    schema = module.role_schema("attacker", {"acceptance_criteria": ["z", "a"]})
    assert schema["properties"]["findings"]["items"]["properties"]["criterion"] == {"type": "string", "enum": ["z", "a"]}
    assert module.SCHEMAS["attacker"]["properties"]["findings"]["items"]["properties"]["criterion"] == {"type": "string"}
    for bad in ([], ["a", "a"], ["a", 3], ["a", ""], "a", None):
        with pytest.raises(ContractError, match="pinned plan acceptance_criteria"):
            module.role_schema("improvement_lead", {"acceptance_criteria": bad})


class Git:
    def __init__(self, heads=(BASE, BASE), status=""):
        self.heads, self.status, self.calls = list(heads), status, []

    def review_workspace(self, base, task_id):
        self.calls.append(("review_workspace", base, task_id))
        return "/ws/" + task_id

    def _git(self, *args, cwd=None):
        self.calls.append((args, cwd))
        return self.heads.pop(0) if args == ("rev-parse", "HEAD") else self.status


class Executor:
    def __init__(self, git=None):
        self.git, self.runs = git or Git(), []

    def _run(self, *args, **kwargs):
        self.runs.append((args, kwargs))
        return {"output": {}}


def task(role, agent, base=BASE):
    d = details(role)
    return {"id": "t-" + role, "agent": agent, "message": {"what": {"details": d}, "where": {"revision": base}}}


def test_a_debate_role_runs_once_with_its_delivery_and_the_read_only_block():
    module = roles()
    executor, hb = Executor(), object()
    t = task("research_lead", "lead:research")
    result = module.execute_role(executor, t, hb)
    (args, kwargs), = executor.runs
    assert args[:2] == ("lead:research", "t-research_lead") and args[4:] == ("/ws/t-research_lead", module.role_schema("research_lead", t["message"]["what"]["details"]), True, hb, t)
    assert kwargs["stage"] == "dge:research_lead" and kwargs["action"] == "dge_role" and kwargs["max_handoffs"] == 1 and kwargs["workload"] == "design"
    assert kwargs["delivery"] == module.council_delivery("research_lead", t["message"]["what"]["details"])
    assert result["role_execution"] == {"role": "research_lead", "stage": "dge:research_lead", "read_only": True, "provider_entries_cap": 1,
                                        "input_policy": "urn:zeus:council-input:2"}
    plain = module.execute_role(Executor(), task("proposer", "lead:proposer"), hb)
    assert plain["role_execution"]["input_policy"] is None


@pytest.mark.parametrize("make, message, provider", [
    (lambda: (Executor(), task("nobody", "x")), "Unknown autonomous role", False),
    (lambda: (Executor(), task("proposer", "lead:other")), "wrong agent", False),
    (lambda: (Executor(), task("proposer", "lead:proposer", base="b2" * 20)), "base revision mismatch", False),
    (lambda: (Executor(Git(heads=("b2" * 20, BASE))), task("proposer", "lead:proposer")), "not at base", False),
    (lambda: (Executor(Git(status=" M f")), task("proposer", "lead:proposer")), "modified its checkout", True),
    (lambda: (Executor(Git(heads=(BASE, "b2" * 20))), task("proposer", "lead:proposer")), "changed its commit", True),
])
def test_each_role_execution_refusal_is_a_contract_error(make, message, provider):
    from codex_harness.kernel.errors import ContractError

    module = roles()
    executor, t = make()
    with pytest.raises(ContractError, match=message):
        module.execute_role(executor, t, object())
    assert bool(executor.runs) is provider


def test_a_fault_outside_the_requirements_propagates_unchanged():
    module = roles()
    with pytest.raises(KeyError):
        module.execute_role(Executor(), {"id": "t", "agent": "x"}, object())


def test_the_drivers_use_this_module():
    driver = (REPO / "compare" / "drivers" / "target" / "s8_autonomous_roles.py").read_text()
    assert "from codex_harness.research.adapters import autonomous_roles as module" in driver
