"""S11 unit AU-b: the structural contract of the atomic units (DESIGN-s11 §5.6 R-AU2, REBUILD-DESIGN-v2 §2.9 rules 2-4).

A JUSTIFIED structural check, not runtime proof (the amendment admits AST checks for an explicit structural contract):
for each atomic-unit row mapped under R-AU1 (`mapping_correction` starts `R-AU1:`), the use-case method named by its
`target_symbol` is parsed from `target/src` and must

1. open at least one `with <store>.transaction() as <tx>` block;
2. pass the bound `tx` to the row's owner operations (`tx_passing_calls`, or the target name they were renamed to,
   cited in `RENAMES`) inside its blocks;
3. call no external-effect port inside any of its blocks (`EXTERNAL_PORTS`, the closed list measured in `target/src`).

Rule 1 is an assertion. Rules 2 and 3 are FINDINGS when they do not hold: the unit's node then ends `xfail` (never a
pass, so rule G1b leaves its `pending:` item) and `FINDINGS` pins the measured finding, so a fix or a new finding both
fail the suite until the pin is edited. The behavioural half of a unit's evidence is `exercise:` (R-AU3).
"""

import ast
import json
import re
from functools import lru_cache
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "target/src"
AU1 = "R-AU1:"
UNIT_PREFIX = "atomic_unit:"
G1B_PENDING = "pending: recorder confirmation in the owning slice"
NODE = "test_unit_is_structurally_atomic"

# Rule 3, the closed list of external-effect ports, by attribute or function name. Each entry cites the definition in
# `target/src` that makes the name a port (checked by `test_every_cited_port_is_defined_in_the_target`).
PROVIDER_RECEIVER = re.compile(r"(?i)(runtime|app_?server|claude|codex)")  # the receiver's last name
PROVIDER_METHODS = {"start", "run"}
SPAWN_METHODS = {"popen"}  # any receiver: the ProcessGroups port method (host_os/ports.py:78, ChokepointProcesses)
SPAWN_ON_MODULE = {"process_groups": {"popen", "run"}, "subprocess": {"run", "Popen", "check_output", "check_call", "call"}}
SPAWN_FUNCTIONS = {"guarded_spawn", "popen"}
GIT_RECEIVER = re.compile(r"(?i)(^|_)git($|_)")  # any method of a git adapter
GIT_METHODS = {"push", "merge"}
DOCKER_RECEIVER = re.compile(r"(?i)^docker$")
DOCKER_FUNCTIONS = {"docker_call", "docker_environment", "docker_state"}
HTTP_FUNCTIONS = {"urlopen", "fetch", "github_detail"}
PORT_CITATIONS = {
    "provider runtimes": [("execution/adapters/providers/claude_cli.py", "ClaudeCodeRuntime.run"),
                          ("execution/adapters/providers/codex_exec.py", "CodexRuntime.run"),
                          ("execution/adapters/providers/codex_app_server.py", "AppServer.run"),
                          ("execution/adapters/containers/launcher.py", "IsolatedClaudeRuntime.run"),
                          ("execution/adapters/containers/launcher.py", "IsolatedCodexRuntime.run")],
    "host_os spawn chokepoint": [("host_os/adapters/process_groups.py", "popen"),
                                 ("host_os/adapters/process_groups.py", "run"),
                                 ("host_os/adapters/process_groups.py", "ChokepointProcesses.popen"),
                                 ("composition/guarded_launch.py", "guarded_spawn")],
    "git push/merge adapters": [("host_os/adapters/git_workspace.py", "GitWorkspace.merge"),
                                ("host_os/adapters/git_workspace.py", "GitWorkspace.is_ancestor"),
                                ("delivery/adapters/host_delivery.py", "GitHubDelivery.merge")],
    "docker": [("execution/adapters/containers/owned_container.py", "docker_call"),
               ("execution/adapters/containers/owned_container.py", "docker_environment"),
               ("coordination/adapters/fleet_recovery.py", "docker_state")],
    "http": [("research/adapters/research.py", "ResearchSources.fetch"),
             ("research/adapters/research.py", "ResearchSources.github_detail")],
}

# Rule 2, renames: the M7 callee (leading underscore dropped) -> the name the target passes `tx` to, with the citation.
RENAMES = {
    "execution_notice": ("record", "research/adapters/audit_execution.py:439,455 `self.notices.record(tx, ...)`; "
                                   "coordination/application/execution_records.py:30 `execution_notices.record(tx, ...)`"),
    "framed": ("policy_frame", "survey 348d4fc2, Continuation.tick/grant_capacity/requalify_delivery: best-matching block "
                               "`passes tx to: ['policy_frame']`"),
    "quarantine_outbox": ("quarantine", "research/application/research_program.py:62 (R-p5) and :907 "
                                        "`self.outbox_quarantine.quarantine(tx, ...)`"),
    "advance_fence": ("advance", "research/application/research_program.py:975 `self.fences.advance(tx, ...)` (R-p5)"),
    "current_fence": ("current", "research/application/research_program.py:972 `self.fences.current(tx, ...)` (R-p5)"),
    "require_adoption": ("adoption", "coordination/application/workflow.py:96-113 `self.adoption(tx, ...)`: the adoption "
                                     "gate is injected"),
    "control": ("observe", "research/application/discovery_pressure.py:84 `self.census.observe(tx, ledger)`; the module "
                           "docstring: Fleet, backlog and continuation reads are the DiscoveryCensus port's"),
    "registry": ("observe", "research/application/discovery_pressure.py:84 (as `control`)"),
    "repository_aliases": ("observe", "research/application/discovery_pressure.py:84 (as `control`)"),
}

# The measured findings (R-AU2 rule 2 or 3) at the time of writing, by unit key without the `atomic_unit:` prefix. They
# are findings for the owner, not passes: the unit's node is `xfail` and rule G1b does not resolve its pending item.
FINDINGS: dict[str, str] = {
    'codex_harness.adapters.deployment:ReleaseRunner.run#1':
        'rule 2: the row records no tx_passing_calls; tx reaches record_superseded',
    'codex_harness.adapters.deployment:ReleaseRunner.abandon#1':
        'rule 2: the row records no tx_passing_calls; tx reaches cancel | rule 3: line 618 git adapter git.is_ancestor()',
    'codex_harness.application.autonomous:AutonomousRun._role#1':
        'rule 2: the row records no tx_passing_calls; tx reaches verify_execution',
    'codex_harness.application.frontdesk:DeskRunner._bound_execution#1':
        'rule 2: the row records no tx_passing_calls; tx reaches nothing',
    'codex_harness.application.scheduling:schedule_research#1':
        'rule 2: the row records no tx_passing_calls; tx reaches append',
    'codex_harness.supervisor:refresh_embeddings#1':
        'rule 2: the row records no tx_passing_calls; tx reaches record',
    'codex_harness.supervisor:maintain_views#1':
        'rule 2: the row records no tx_passing_calls; tx reaches indexed, record',
    'codex_harness.supervisor:tick#3':
        'rule 2: the row records no tx_passing_calls; tx reaches record',
}


# ----------------------------------------------------------------------------------------------------- the analysis

def last_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    return None


def normal(name: str) -> str:
    """A callee name compared without its leading underscores and any receiver (`self.queue.owned` -> `owned`)."""
    return name.split(".")[-1].lstrip("_")


def find_function(tree: ast.Module, qualname: str):
    scope, node = tree.body, None
    for part in qualname.split("."):
        node = next((n for n in scope if isinstance(n, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
                     and n.name == part), None)
        if node is None:
            return None
        scope = node.body
    return node


def transaction_blocks(fn) -> list[tuple[ast.With, str | None]]:
    out = []
    for node in ast.walk(fn):
        if isinstance(node, (ast.With, ast.AsyncWith)):
            for item in node.items:
                call = item.context_expr
                if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) and call.func.attr == "transaction":
                    var = item.optional_vars
                    out.append((node, var.id if isinstance(var, ast.Name) else None))
    return out


def external_effect(call: ast.Call) -> str | None:
    """The closed-list port a call reaches (by attribute or function name), or None."""
    func = call.func
    if isinstance(func, ast.Name):
        if func.id in SPAWN_FUNCTIONS:
            return f"spawn chokepoint {func.id}()"
        if func.id in DOCKER_FUNCTIONS:
            return f"docker {func.id}()"
        if func.id in HTTP_FUNCTIONS:
            return f"http {func.id}()"
        return None
    if not isinstance(func, ast.Attribute):
        return None
    method, receiver = func.attr, last_name(func.value) or ""
    if method in SPAWN_ON_MODULE.get(receiver, ()):
        return f"spawn chokepoint {receiver}.{method}()"
    if method in SPAWN_METHODS:
        return f"spawn chokepoint .{method}()"
    if PROVIDER_RECEIVER.search(receiver) and method in PROVIDER_METHODS:
        return f"provider runtime {receiver}.{method}()"
    if GIT_RECEIVER.search(receiver) or method in GIT_METHODS:
        return f"git adapter {receiver}.{method}()"
    if DOCKER_RECEIVER.search(receiver) or method in DOCKER_FUNCTIONS:
        return f"docker {receiver}.{method}()"
    if method in HTTP_FUNCTIONS:
        return f"http {receiver}.{method}()"
    return None


def analyse(source: str, qualname: str, expected: list[str]) -> dict:
    """{'found': bool, 'blocks': int, 'missing': [...], 'effects': [(line, port)], 'passed_to': [...]}"""
    fn = find_function(ast.parse(source), qualname)
    if fn is None:
        return {"found": False, "blocks": 0, "missing": [], "effects": [], "passed_to": []}
    blocks = transaction_blocks(fn)
    passed, effects = set(), []
    for block, tx in blocks:
        for call in (n for n in ast.walk(block) if isinstance(n, ast.Call)):
            args = [a for a in (*call.args, *(k.value for k in call.keywords))]
            if tx and any(isinstance(a, ast.Name) and a.id == tx for a in args) and last_name(call.func):
                passed.add(normal(last_name(call.func)))
            port = external_effect(call)
            if port:
                effects.append((call.lineno, port))
    wanted = {normal(c) for c in expected}
    missing = sorted(w for w in wanted if RENAMES.get(w, (w,))[0] not in passed and w not in passed)
    return {"found": True, "blocks": len(blocks), "missing": missing, "effects": sorted(set(effects)),
            "passed_to": sorted(passed)}


def verdict(result: dict, expected: list[str]) -> str | None:
    """None when the unit meets rules 2 and 3, else the finding text; rule 1 is the caller's assertion."""
    findings = []
    if not expected:
        findings.append("rule 2: the row records no tx_passing_calls; tx reaches " + ", ".join(result["passed_to"] or ["nothing"]))
    elif result["missing"]:
        findings.append("rule 2: tx is not passed to " + ", ".join(result["missing"]))
    if result["effects"]:
        findings.append("rule 3: " + "; ".join(f"line {line} {port}" for line, port in result["effects"]))
    return " | ".join(findings) or None


def symbol_source(symbol: str) -> tuple[str, str]:
    module, _, qualname = symbol.partition(":")
    return (SRC / (module.replace(".", "/") + ".py")).read_text(encoding="utf-8"), qualname


# --------------------------------------------------------------------------------------------------------- the units

@lru_cache(maxsize=1)
def ledger_rows() -> list[dict]:
    return json.loads((ROOT / "coverage/ledger-coverage.json").read_text(encoding="utf-8"))["rows"]


def mapped_units() -> list[dict]:
    return [r for r in ledger_rows() if r["kind"] == "atomic_unit" and str(r.get("mapping_correction", "")).startswith(AU1)]


def unit_id(row: dict) -> str:
    return row["key"][len(UNIT_PREFIX):]


def measure(row: dict) -> tuple[dict, str | None]:
    source, qualname = symbol_source(row["target_symbol"][0])
    result = analyse(source, qualname, row["tx_passing_calls"])
    return result, verdict(result, row["tx_passing_calls"])


@pytest.mark.parametrize("row", mapped_units(), ids=unit_id)
def test_unit_is_structurally_atomic(row):
    """The structural contract (REBUILD-DESIGN-v2 §2.9 rules 2-4): one transaction block, `tx` to the owner operations, no
    external effect inside. A finding is `xfail` (never a pass); the pinned `FINDINGS` must equal the measurement."""
    result, finding = measure(row)
    assert result["found"], f"the mapped method does not exist: {row['target_symbol'][0]}"
    assert result["blocks"] >= 1, f"rule 1: the method opens no transaction() block: {row['target_symbol'][0]}"
    assert FINDINGS.get(unit_id(row)) == finding, f"measured {finding!r}; pinned {FINDINGS.get(unit_id(row))!r}"
    if finding:
        pytest.xfail("FINDING " + finding)


def test_the_pinned_findings_name_mapped_units_only():
    assert set(FINDINGS) <= {unit_id(r) for r in mapped_units()}


def test_r_au1_mapped_every_prose_unit_with_a_measured_method_and_left_the_ambiguous_ones():
    rows = [r for r in ledger_rows() if r["kind"] == "atomic_unit"]
    ambiguous = [r for r in rows if str(r.get("mapping_correction", "")).startswith("ambiguous (survey):")]
    assert len(mapped_units()) == 144 and len(ambiguous) == 5
    for r in mapped_units():
        assert re.fullmatch(r"codex_harness(\.\w+)+:\w+(\.\w+)*", r["target_symbol"][0]) and len(r["target_symbol"]) == 1
    for r in ambiguous:  # the owner rules on these: the symbol is still the prose rule text
        assert r["target_symbol"][0].startswith("one Store.transaction()"), r["key"]


# ------------------------------------------------------------------------------------------------ negative controls

# Synthetic controls (inline: a support file under target/tests/fixtures would make the evidence bundle stale, R-L13).
CONTROLS = {
    "good_unit.py.txt": (
        '"""Positive control of the R-AU2 structural test: one block, `tx` passed to the owner operation, no external effect."""\n'
        'from codex_harness.host_os.adapters import process_groups\n'
        '\n'
        '\n'
        'class Unit:\n'
        '    def commit(self, task):\n'
        '        with self.store.transaction() as tx:\n'
        '            row = tx.get("tasks", task)\n'
        '            self.ops.record(tx, row)\n'
        '        process_groups.popen(["true"])  # outside the block: an external effect after the commit is allowed\n'
        '        return row\n'
    ),
    "no_transaction.py.txt": (
        '"""Negative control, rule 1: the method opens no `transaction()` block."""\n'
        '\n'
        '\n'
        'class Unit:\n'
        '    def commit(self, task):\n'
        '        row = self.store.get("tasks", task)\n'
        '        self.ops.record(None, row)\n'
        '        return row\n'
    ),
    "renamed_callee.py.txt": (
        '"""The owner operation `record` is passed `tx` under the name `append` (a table-cited rename)."""\n'
        '\n'
        '\n'
        'class Unit:\n'
        '    def commit(self, task):\n'
        '        with self.store.transaction() as tx:\n'
        '            self.ops.append(tx, task)\n'
        '        return task\n'
    ),
    "spawns_inside_block.py.txt": (
        '"""Negative control, rule 3: an external-effect port (the host_os spawn chokepoint) is called inside the block."""\n'
        'from codex_harness.host_os.adapters import process_groups\n'
        '\n'
        '\n'
        'class Unit:\n'
        '    def commit(self, task):\n'
        '        with self.store.transaction() as tx:\n'
        '            self.ops.record(tx, task)\n'
        '            process_groups.popen(["true"])\n'
        '        return task\n'
    ),
    "tx_not_passed.py.txt": (
        '"""Negative control, rule 2: the block calls the owner operation without the bound `tx`."""\n'
        '\n'
        '\n'
        'class Unit:\n'
        '    def commit(self, task):\n'
        '        with self.store.transaction() as tx:\n'
        '            row = tx.get("tasks", task)\n'
        '            self.ops.record(row)\n'
        '        return row\n'
    ),
}


def fixture(name: str) -> str:
    return CONTROLS[name]


def test_the_positive_control_meets_every_rule():
    result = analyse(fixture("good_unit.py.txt"), "Unit.commit", ["self.ops.record"])
    assert result["blocks"] == 1 and verdict(result, ["self.ops.record"]) is None


def test_negative_control_a_method_without_a_transaction_has_no_block():
    result = analyse(fixture("no_transaction.py.txt"), "Unit.commit", ["self.ops.record"])
    assert result["found"] and result["blocks"] == 0


def test_negative_control_a_spawn_inside_a_block_is_a_rule_3_finding():
    result = analyse(fixture("spawns_inside_block.py.txt"), "Unit.commit", ["self.ops.record"])
    assert result["blocks"] == 1 and result["missing"] == []
    assert result["effects"] == [(9, "spawn chokepoint process_groups.popen()")]
    assert verdict(result, ["self.ops.record"]).startswith("rule 3: line 9 spawn chokepoint")


def test_negative_control_a_block_that_does_not_pass_tx_is_a_rule_2_finding():
    result = analyse(fixture("tx_not_passed.py.txt"), "Unit.commit", ["self.ops.record"])
    assert result["blocks"] == 1 and result["missing"] == ["record"] and result["effects"] == []
    assert verdict(result, ["self.ops.record"]) == "rule 2: tx is not passed to record"


def test_a_missing_owner_operation_list_is_a_finding_not_a_pass():
    result = analyse(fixture("good_unit.py.txt"), "Unit.commit", [])
    assert "no tx_passing_calls" in verdict(result, [])


def test_a_renamed_callee_passes_only_through_the_cited_table():
    source = fixture("renamed_callee.py.txt")
    assert analyse(source, "Unit.commit", ["self.ops.record"])["missing"] == ["record"]
    try:
        RENAMES["record"] = ("append", "the renamed_callee control, line 7")
        assert analyse(source, "Unit.commit", ["self.ops.record"])["missing"] == []
    finally:
        del RENAMES["record"]


def test_a_leading_underscore_is_not_a_rename_but_a_different_operation_is():
    source = "class U:\n    def go(self):\n        with self.s.transaction() as tx:\n            self.append(tx)\n"
    assert analyse(source, "U.go", ["self._append"])["missing"] == []
    assert analyse(source, "U.go", ["self._event"])["missing"] == ["event"]


@pytest.mark.parametrize("code, port", [
    ("self.runtime.run(p)", "provider runtime runtime.run()"),
    ("self.app_server.start()", "provider runtime app_server.start()"),
    ("self.claude.run(p)", "provider runtime claude.run()"),
    ("self.groups.popen(argv)", "spawn chokepoint .popen()"),
    ("process_groups.run(argv)", "spawn chokepoint process_groups.run()"),
    ("subprocess.run(argv)", "spawn chokepoint subprocess.run()"),
    ("guarded_spawn()", "spawn chokepoint guarded_spawn()"),
    ("self.git.is_ancestor(a, b)", "git adapter git.is_ancestor()"),
    ("self.repo.push(ref)", "git adapter repo.push()"),
    ("self.host.merge(c)", "git adapter host.merge()"),
    ("docker_call(r, d, a, timeout=1)", "docker docker_call()"),
    ("self.docker.run(a)", "docker docker.run()"),
    ("urlopen(request)", "http urlopen()"),
    ("self.fetcher.fetch(url)", "http fetcher.fetch()"),
])
def test_every_port_family_is_detected_inside_a_block_and_not_outside(code, port):
    inside = f"class U:\n    def go(self):\n        with self.s.transaction() as tx:\n            {code}\n"
    outside = f"class U:\n    def go(self):\n        with self.s.transaction() as tx:\n            self.ops.record(tx)\n        {code}\n"
    assert [p for _, p in analyse(inside, "U.go", ["record"])["effects"]] == [port]
    assert analyse(outside, "U.go", ["record"])["effects"] == []


def test_an_owner_operation_is_not_an_external_port():
    source = ("class U:\n    def go(self):\n        with self.s.transaction() as tx:\n"
              "            self.releases.promote(tx)\n            self.queue.owned(tx)\n            self.census.observe(tx)\n")
    assert analyse(source, "U.go", ["promote"])["effects"] == []


# ----------------------------------------------------------------------------------------------------------- citations

@pytest.mark.parametrize("family, path, qualname", [(f, p, q) for f, cites in PORT_CITATIONS.items() for p, q in cites])
def test_every_cited_port_is_defined_in_the_target(family, path, qualname):
    tree = ast.parse((SRC / "codex_harness" / path).read_text(encoding="utf-8"))
    assert find_function(tree, qualname) is not None, f"{family}: {path}:{qualname}"


def test_every_rename_is_cited_and_is_used_by_a_mapped_unit_whose_block_passes_tx_to_the_new_name():
    for old, (new, citation) in RENAMES.items():
        assert old != new and citation.strip()
    seen = {}
    for row in mapped_units():
        result, _ = measure(row)
        for wanted in (normal(c) for c in row["tx_passing_calls"]):
            if wanted in RENAMES:
                seen.setdefault(wanted, []).append(RENAMES[wanted][0] in result["passed_to"])
    assert set(seen) == set(RENAMES), "a rename that no mapped unit uses"
    assert all(any(v) for v in seen.values()), {k: v for k, v in seen.items() if not any(v)}


# ------------------------------------------------------------------------------------------------------------- G1b

def committed_g1b() -> list[dict]:
    doc = json.loads((ROOT / "coverage/evidence-resolutions.json").read_text(encoding="utf-8"))
    return [e for e in doc["resolutions"] if e["rule"] == "G1b"]


def test_g1b_resolves_exactly_the_mapped_units_that_pass_and_carry_the_recorder_promise():
    entries = {e["key"]: e for e in committed_g1b()}
    resolved = json.loads((ROOT / "coverage/evidence-resolutions.json").read_text(encoding="utf-8"))["resolutions"]
    earlier = {e["key"] for e in resolved if e["rule"] != "G1b" and e["pending"] == G1B_PENDING}  # a recorder family (G1)
    want = {r["key"] for r in mapped_units()
            if G1B_PENDING in r["evidence"] and unit_id(r) not in FINDINGS and r["key"] not in earlier}
    assert set(entries) == want and want
    for row in mapped_units():
        e = entries.get(row["key"])
        if e:
            assert e["pending"] == G1B_PENDING and e["citation"] == "DESIGN-s11 §5.6 R-AU4"
            assert e["replaced_by"] == [f"exercise:{row['target_symbol'][0]}",
                                        f"target:tests/test_s11_atomic_units.py::{NODE}[{unit_id(row)}]"]
