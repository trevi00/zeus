"""S10 unit C2b: the incident, rollback-hook, run-command, demo, seed-research-backlog and execution-recovery roots (DESIGN-s10 §3 C2).

Parity with M7 on a disposable PostgreSQL is the `entry.cli_store_b.pg` compare family; these tests cover what it cannot: the R-c5
mapping of M7's `service.<m>` calls onto the composed objects, the one-unit `incidents(service).record_incident` and the dispatch table.
"""

import ast
from contextlib import contextmanager
from pathlib import Path

from codex_harness import composition
from codex_harness.composition import cli as composition_cli
from codex_harness.entry import cli
from codex_harness.kernel.message import envelope
from codex_harness.routing.adapters.organization_source import packaged_organization
from codex_harness.storage.adapters.memory_store import MemoryStore

CLI_DIR = Path(cli.__file__).resolve().parent
ROOTS = ("paths", "setup", "organization", "validate", "canary", "doctor", "init-db", "status", "inspect", "cancel",
         "release-retry", "goal", "incident", "rollback-hook", "run-command", "demo", "seed-research-backlog",
         "execution-recovery")
# R-c5: M7's `service.<m>(...)` call and the composed object (builder of composition.cli) that owns it now.
MAPPING = {"record_incident": "incidents", "get_hook": "hook_units", "propose": "hook_units", "review": "hook_units",
           "record_canary": "hook_units", "activate": "hook_units", "prepare_command": "hook_units",
           "rollback": "hook_units", "checkpoint": "sessions"}
# the composed root modules and the builders each one calls through `composition.<builder>(`
BUILDERS = {"incident": {"incidents", "validate_message"}, "rollback_hook": {"hook_units"},
            "run_command": {"hook_units", "run_process"}, "seed_research_backlog": {"research_audits", "artifacts"},
            "execution_recovery": {"execution_recovery", "artifacts"},
            "demo": {"hook_units", "incidents", "sessions", "executable_canary", "validate_message"}}


def tree(name: str) -> ast.Module:
    return ast.parse((CLI_DIR / f"{name}.py").read_text(encoding="utf-8"))


def dispatch_keys() -> list[str]:
    tables = [node for node in ast.walk(tree("__init__")) if isinstance(node, ast.Assign)
              and any(isinstance(t, ast.Name) and t.id == "composed" for t in node.targets)]
    assert len(tables) == 1 and isinstance(tables[0].value, ast.Dict)
    return [key.value for key in tables[0].value.keys]


def method_calls(module: ast.Module):
    return [(node.func.attr, node.func.value) for node in ast.walk(module)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)]


def composition_calls(module: ast.Module) -> set[str]:
    return {attr for attr, owner in method_calls(module) if isinstance(owner, ast.Name) and owner.id == "composition"}


def test_the_dispatch_table_holds_the_eighteen_composed_roots():
    assert set(ROOTS) <= set(dispatch_keys())


def test_no_moved_body_calls_a_harness_method_on_the_service():
    for name in BUILDERS:
        for attr, owner in method_calls(tree(name)):
            assert not (attr in MAPPING and isinstance(owner, ast.Name) and owner.id == "service"), (name, attr)


def test_each_m7_service_call_maps_to_its_composed_object():
    # the receiver of each mapped method is a local bound from the owning builder of the same module
    for name in BUILDERS:
        module = tree(name)
        bound = {}
        for node in ast.walk(module):
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Tuple):
                pairs = zip(node.targets[0].elts, node.value.elts, strict=True) if isinstance(node.targets[0], ast.Tuple) else ()
            elif isinstance(node, ast.Assign):
                pairs = [(node.targets[0], node.value)]
            else:
                pairs = ()
            for target, value in pairs:
                if (isinstance(target, ast.Name) and isinstance(value, ast.Call) and isinstance(value.func, ast.Attribute)
                        and isinstance(value.func.value, ast.Name) and value.func.value.id == "composition"):
                    bound[target.id] = value.func.attr
        for attr, owner in method_calls(module):
            if attr not in MAPPING:
                continue
            builder = (bound.get(owner.id) if isinstance(owner, ast.Name) else owner.func.attr
                       if isinstance(owner, ast.Call) and isinstance(owner.func, ast.Attribute) else None)
            assert builder == MAPPING[attr], (name, attr, builder)


def test_each_root_calls_only_its_listed_builders():
    for name, builders in BUILDERS.items():
        used = composition_calls(tree(name))
        assert builders <= used, (name, builders - used)
        for builder in used:
            assert hasattr(composition_cli, builder), (name, builder)


def test_the_composed_builders_exist_with_their_docstrings_naming_a_shim():
    for builder in ("hook_units", "incidents", "sessions", "execution_recovery", "research_audits", "executable_canary"):
        assert "tests/ported" in getattr(composition_cli, builder).__doc__ or "compare/drivers" in getattr(composition_cli, builder).__doc__


def test_incidents_record_incident_opens_exactly_one_unit():
    class Counting(MemoryStore):
        units = 0

        @contextmanager
        def transaction(self):
            type(self).units += 1
            with super().transaction() as tx:
                yield tx

    store = Counting()
    message = envelope("incident.report", "worker:implementation", "lead:improvement", "record_incident",
                       {"occurrence_id": "o-1", "root_cause": "rc", "scope": "s", "evidence_refs": ["e1"]}, "c-1")
    result = composition_cli.incidents(composition.ServiceHandle(store, packaged_organization())).record_incident(message)
    assert Counting.units == 1
    assert result["occurrences"] == 1 and result["hook_created"] is False
