"""S11 unit AU-b: the structural contract of the atomic units (DESIGN-s11 §5.6 R-AU2, REBUILD-DESIGN-v2 §2.9 rules 2-4).

A JUSTIFIED structural check, not runtime proof (the amendment admits AST checks for an explicit structural contract):
for each atomic-unit row mapped under R-AU1 (`mapping_correction` starts `R-AU1:`), the use-case method named by its
`target_symbol` is parsed from `target/src` and must

1. open at least one `with <store>.transaction() as <tx>` block;
2. pass the bound `tx` to the row's owner operations (`tx_passing_calls`, or the target name they were renamed to,
   cited in `RENAMES`) inside its blocks;
3. call no external-effect port inside any of its blocks (`EXTERNAL_PORTS`, the closed list measured in `target/src`).

Rule 1 is an assertion. Rules 2 and 3 are FINDINGS when they do not hold. `R_AU2_FINDINGS` is the exact pinned set
{row key: reason}; `test_the_computed_findings_equal_the_pinned_set` fails on a new finding and on a fixed one that is
still pinned (no xfail/skip: SKIPPED-TEST-CLOSURE). Rule G1b is withheld for a pinned row.

Owner rulings (resume 1, 2026-10-05):
- R-AU2-a: rule 3 lists EFFECTS only (REBUILD-DESIGN-v2 §2.9 rule 4: provider calls, process/container spawns, Git
  push/merge, Docker, HTTP). A read-only local Git query (`is_ancestor`, `rev-parse`, `show`) is not an external effect.
- R-AU2-b: when the row records no `tx_passing_calls`, rule 2 requires that a block uses its own bound `tx` for store
  operations (at least one `<tx>.<op>(` call) and opens no nested `transaction()`. Refined at int51 (owner): passing the
  bound `tx` to a call (`transaction=tx`, §2.9 rule 2's own pattern) also satisfies it. The behavioural half of a unit's evidence is `exercise:` (R-AU3).
"""

import ast
import json
import re
from functools import lru_cache

import pytest
from _layout import REPO as ROOT
from _layout import TARGET

SRC = TARGET / "src"
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
GIT_METHODS = {"push", "merge"}  # §2.9 rule 4 effects; read-only queries (is_ancestor) are not ports (R-AU2-a)
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

# The measured findings (R-AU2 rule 2 or 3), by unit key without the `atomic_unit:` prefix: exact, see the docstring.
# Empty at int51: the 3 earlier rule-2 findings (ReleaseRunner.run#1, supervisor refresh_embeddings#1/maintain_views#1)
# pass their bound tx to owner operations (record_superseded, record, indexed), which R-AU2-b as refined at int51 accepts
# (DESIGN-s11 §5.6). A new finding still fails the exact-set test below.
R_AU2_FINDINGS: dict[str, str] = {}


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
    if method in GIT_METHODS:
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
        return {"found": False, "blocks": 0, "missing": [], "effects": [], "passed_to": [], "own_ops": 0, "nested": 0}
    blocks = transaction_blocks(fn)
    passed, effects, own_ops, nested = set(), [], 0, 0
    for block, tx in blocks:
        nested += sum(1 for other, _ in blocks if other is not block and any(n is other for n in ast.walk(block)))
        for call in (n for n in ast.walk(block) if isinstance(n, ast.Call)):
            args = [a for a in (*call.args, *(k.value for k in call.keywords))]
            if tx and any(isinstance(a, ast.Name) and a.id == tx for a in args) and last_name(call.func):
                passed.add(normal(last_name(call.func)))
            if tx and isinstance(call.func, ast.Attribute) and isinstance(call.func.value, ast.Name) \
                    and call.func.value.id == tx:
                own_ops += 1
            port = external_effect(call)
            if port:
                effects.append((call.lineno, port))
    wanted = {normal(c) for c in expected}
    missing = sorted(w for w in wanted if RENAMES.get(w, (w,))[0] not in passed and w not in passed)
    return {"found": True, "blocks": len(blocks), "missing": missing, "effects": sorted(set(effects)),
            "passed_to": sorted(passed),
            "own_ops": own_ops, "nested": nested}


def verdict(result: dict, expected: list[str]) -> str | None:
    """None when the unit meets rules 2 and 3, else the finding text; rule 1 is the caller's assertion."""
    findings = []
    if not expected:  # R-AU2-b
        if not result["own_ops"] and not result["passed_to"]:  # R-AU2-b as refined at int51 (DESIGN-s11 §5.6)
            findings.append("rule 2: the row records no tx_passing_calls and the block neither makes a <tx>.<op>() call"
                            " nor passes tx to a call")
        if result["nested"]:
            findings.append("rule 2: a nested transaction() block")
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


OWNER_RULED = "S11 owner ruling (DESIGN-s11 §5.6)"  # the 5 survey-ambiguous units the owner ruled on at int51


def mapped_units() -> list[dict]:
    return [r for r in ledger_rows() if r["kind"] == "atomic_unit"
            and str(r.get("mapping_correction", "")).startswith((AU1, OWNER_RULED))]


def unit_id(row: dict) -> str:
    return row["key"][len(UNIT_PREFIX):]


def measure(row: dict) -> tuple[dict, str | None]:
    """Every target symbol of the row is measured (an owner-ruled split unit names two owners with the same body);
    the row is found and has blocks only if each symbol does, and the first finding of any symbol is the row's."""
    results, findings = [], []
    for symbol in row["target_symbol"]:
        source, qualname = symbol_source(symbol)
        result = analyse(source, qualname, row["tx_passing_calls"])
        results.append(result)
        findings.append(verdict(result, row["tx_passing_calls"]))
    merged = {**results[0], "found": all(r["found"] for r in results), "blocks": min(r["blocks"] for r in results)}
    return merged, next((f for f in findings if f), None)


@pytest.mark.parametrize("row", mapped_units(), ids=unit_id)
def test_unit_is_structurally_atomic(row):
    """The structural contract (REBUILD-DESIGN-v2 §2.9 rules 2-4): one transaction block, `tx` to the owner operations, no
    external effect inside. The node passes when rule 1 holds; findings are compared as a set by the next test."""
    result, finding = measure(row)
    assert result["found"], f"the mapped method does not exist: {row['target_symbol'][0]}"
    assert result["blocks"] >= 1, f"rule 1: the method opens no transaction() block: {row['target_symbol'][0]}"


def test_the_computed_findings_equal_the_pinned_set():
    computed = {unit_id(r): f for r in mapped_units() for f in [measure(r)[1]] if f}
    assert computed == R_AU2_FINDINGS


def test_the_pinned_findings_name_mapped_units_only():
    assert set(R_AU2_FINDINGS) <= {unit_id(r) for r in mapped_units()}


def test_r_au1_mapped_every_prose_unit_with_a_measured_method_and_left_the_ambiguous_ones():
    rows = [r for r in ledger_rows() if r["kind"] == "atomic_unit"]
    ambiguous = [r for r in rows if str(r.get("mapping_correction", "")).startswith("ambiguous (survey):")]
    # S11 int51: the owner ruled on the 5 survey-ambiguous units (DESIGN-s11 §5.6): 144 + 5 mapped, 0 ambiguous.
    assert len(mapped_units()) == 149 and len(ambiguous) == 0
    for r in mapped_units():
        assert all(re.fullmatch(r"codex_harness(\.\w+)+:\w+(\.\w+)*", s) for s in r["target_symbol"])
        split = str(r.get("mapping_correction", "")).startswith(OWNER_RULED) and "split into two owners" in r["mapping_correction"]
        assert len(r["target_symbol"]) == (2 if split else 1), r["key"]


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


def test_a_missing_owner_operation_list_needs_the_blocks_own_tx_operations_else_a_finding():
    assert verdict(analyse(fixture("good_unit.py.txt"), "Unit.commit", []), []) is None  # `tx.get` (R-AU2-b)
    source = "class U:\n    def go(self):\n        with self.s.transaction() as tx:\n            self.ops.f(1)\n"
    assert "no tx_passing_calls" in verdict(analyse(source, "U.go", []), [])


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


def test_a_read_only_git_query_is_not_an_external_effect():
    source = "class U:\n    def go(self):\n        with self.s.transaction() as tx:\n            self.git.is_ancestor(a, b)\n"
    assert analyse(source, "U.go", [])["effects"] == []


def test_without_tx_passing_calls_the_block_must_use_its_own_tx_and_not_nest():
    own = "class U:\n    def go(self):\n        with self.s.transaction() as tx:\n            tx.put('b', 1)\n"
    assert verdict(analyse(own, "U.go", []), []) is None
    none = "class U:\n    def go(self):\n        with self.s.transaction() as tx:\n            self.ops.f(1)\n"
    assert "neither makes a <tx>.<op>() call" in verdict(analyse(none, "U.go", []), [])
    nest = ("class U:\n    def go(self):\n        with self.s.transaction() as tx:\n            tx.put('b', 1)\n"
            "            with self.s.transaction() as t2:\n                t2.put('c', 1)\n")
    assert "nested" in verdict(analyse(nest, "U.go", []), [])


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
            if G1B_PENDING in r["evidence"] and unit_id(r) not in R_AU2_FINDINGS and r["key"] not in earlier}
    assert set(entries) == want and want
    for row in mapped_units():
        e = entries.get(row["key"])
        if e:
            assert e["pending"] == G1B_PENDING and e["citation"] == "DESIGN-s11 §5.6 R-AU4"
            assert e["replaced_by"] == [*(f"exercise:{symbol}" for symbol in row["target_symbol"]),
                                        f"target:tests/test_s11_atomic_units.py::{NODE}[{unit_id(row)}]"]
