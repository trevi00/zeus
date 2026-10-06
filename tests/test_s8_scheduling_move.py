"""S8 pilot 102 (DESIGN-s8 §19 V23 R-sc1..R-sc3): M7 `application/scheduling.py` moves to `research.application.scheduling` with the outbox and the
release reconciliation injected.

M7 is read only as text through `git show e38aa722:...` and compared by AST (never imported: both packages are named `codex_harness`). Behaviour is
compared by the recorded `research.scheduling` golden (the wired module is target-equal to it); the unwired-port refusals have no M7 counterpart and
are pinned here, each with the store left exactly as it was.
"""

from __future__ import annotations

import ast
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from _layout import REPO, TARGET

from codex_harness.coordination.application.outbox import Outbox
from codex_harness.kernel.errors import ContractError
from codex_harness.kernel.ids import digest
from codex_harness.research import ports
from codex_harness.research.application import scheduling as module
from codex_harness.research.application.scheduling import schedule_audits, schedule_research
from codex_harness.routing.adapters.organization_source import packaged_organization
from codex_harness.storage.adapters.memory_store import MemoryStore

SRC = TARGET / "src" / "codex_harness"
SOURCE = "e38aa722"
M7_PATH = "src/codex_harness/application/scheduling.py"
NOW = 1_800_000_000.0
RECONCILE_MESSAGE = "Release reconciliation is not wired"
OUTBOX_MESSAGE = "Outbox is not wired"


def m7_text():
    return subprocess.run(["git", "-C", str(REPO), "show", f"{SOURCE}:{M7_PATH}"], check=True, capture_output=True, text=True).stdout


def target_text():
    return Path(module.__file__).read_text()


def functions(src):
    return {n.name: n for n in ast.parse(src).body if isinstance(n, ast.FunctionDef)}


def m7_with_rules():
    """M7's text with the named rules applied as text (R-sc0 homes, R-sc1, R-sc2, R-sc3): the independent expectation of the output's functions."""
    text = m7_text()
    for old, new in (
        ("    from codex_harness.domain.model import digest\n", "    from codex_harness.kernel.ids import digest\n"),
        ("        from codex_harness.application.audit_gate import require_adoption\n        from codex_harness.domain.model import ContractError\n",
         "        from codex_harness.kernel.errors import ContractError\n        from codex_harness.research.application.audit_gate import require_adoption\n"),
        ("    from codex_harness.application.releases import Releases\n", ""),
        ("    Releases(service.store, service.org).reconcile_audits()\n",
         "    require(reconcile_audits is not None, 'Release reconciliation is not wired')\n    reconcile_audits()\n"),
        ("def schedule_research(service, now: float | None = None) -> int:", "def schedule_research(service, now: float | None = None, *, outbox=None, reconcile_audits=None) -> int:"),
        ("created + schedule_audits(service)", "created + schedule_audits(service, outbox=outbox, reconcile_audits=reconcile_audits)"),
        ("def schedule_audits(service, audit_id: str | None = None) -> int:",
         "def schedule_audits(service, audit_id: str | None = None, *, outbox=None, reconcile_audits=None) -> int:"),
        ('tx.put("outbox", message["message_id"], {"message": message, "sent": False})', "_append(outbox, tx, message)"),
        ("tx.put('outbox', message['message_id'], {'message': message, 'sent': False})", "_append(outbox, tx, message)"),
    ):
        assert old in text
        text = text.replace(old, new)
    return text


# ---- the rules ---------------------------------------------------------------------------------------------------------------
def test_the_two_functions_are_m7s_modulo_r_sc1_to_r_sc3():
    ours, expected = functions(target_text()), functions(m7_with_rules())
    for name in ("schedule_research", "schedule_audits"):
        assert ast.dump(ours[name]) == ast.dump(expected[name])
    assert list(ours) == ["_append", "schedule_research", "schedule_audits"]


def test_r_sc1_the_ports_are_keyword_only_and_default_none():
    for fn, positional in ((schedule_research, ["service", "now"]), (schedule_audits, ["service", "audit_id"])):
        args = functions(target_text())[fn.__name__].args
        assert [a.arg for a in args.args] == positional
        assert [a.arg for a in args.kwonlyargs] == ["outbox", "reconcile_audits"]
        assert [ast.unparse(d) for d in args.kw_defaults] == ["None", "None"]


def test_r_sc3_no_direct_outbox_put_and_six_appends_in_place():
    tree = ast.parse(target_text())
    puts = [n.args[0].value for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "put"
            and n.args and isinstance(n.args[0], ast.Constant)]
    assert "outbox" not in puts and puts == ["schedule"] * 6
    appends = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "_append"]
    assert len(appends) == 6
    requires = sorted(ast.unparse(n.args[0]) for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "require")
    assert requires == ["outbox is not None", "reconcile_audits is not None"]


def test_import_homes_and_header():
    text = target_text()
    tree = ast.parse(text)
    modules = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert modules == {"__future__", "codex_harness.kernel.errors", "codex_harness.kernel.ids", "codex_harness.kernel.message",
                       "codex_harness.kernel.policy", "codex_harness.research.application.audit_gate"}
    doc = ast.get_docstring(tree)
    for line in ("Layer: application", "Context: research", "Owns:", "Does not own:", "Entry points: schedule_research, schedule_audits", "Contracts:",
                 "SOURCE " + SOURCE, "DESIGN-s8 §19 V23"):
        assert line in doc


def test_the_outbox_port_shape_is_coordinations_append_and_declared_by_research():
    assert hasattr(ports, "OutboxAppend") and hasattr(Outbox, "append")
    assert "schedule" in ports.OWNED_BUCKETS


def test_the_outbox_bucket_has_no_research_writer_beyond_the_port():
    for path in sorted((SRC / "research").rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "put" and node.args \
                    and isinstance(node.args[0], ast.Constant):
                assert node.args[0].value != "outbox", path


# ---- behaviour: the wiring and the refusals -----------------------------------------------------------------------------------
def digest_of(store):
    with store.transaction() as tx:
        return digest([[r["bucket"], r["id"], digest(r["body"])] for r in tx.records()])


def world(*, control="active", discovery=False):
    store = MemoryStore()
    service = SimpleNamespace(store=store, org=packaged_organization())
    with store.transaction() as tx:
        if control:
            tx.put("research_control", "activation", {"status": control, "release_id": "r", "revision": "v"})
        if discovery:
            tx.put("research_discoveries", "d1", {"id": "d1"})
    return service


def count(store, bucket):
    with store.transaction() as tx:
        return len(tx.scan(bucket))


def test_schedule_research_passes_both_ports_to_schedule_audits():
    service, calls = world(discovery=True), []
    outbox = Outbox()
    created = schedule_research(service, NOW, outbox=outbox, reconcile_audits=lambda: calls.append("reconcile"))
    assert created == 3 and calls == ["reconcile"]  # two sources plus the discovery: the audits pass saw the outbox
    assert count(service.store, "outbox") == 3 and count(service.store, "schedule") == 3


def test_the_wired_pass_writes_coordinations_outbox_row():
    service = world(discovery=True)
    schedule_audits(service, outbox=Outbox(), reconcile_audits=lambda: None)
    with service.store.transaction() as tx:
        rows = tx.scan("outbox")
    assert len(rows) == 1 and rows[0]["sent"] is False and rows[0]["message"]["what"]["action"] == "audit_discovery"


def test_schedule_research_without_reconcile_audits_keeps_only_its_own_slot():
    """`schedule_research` commits its research slot before `schedule_audits` runs (M7 order); the audits pass is refused before its transaction."""
    service = world(discovery=True)
    with pytest.raises(ContractError, match=RECONCILE_MESSAGE):
        schedule_research(service, NOW, outbox=Outbox())
    assert count(service.store, "schedule") == 2 and count(service.store, "outbox") == 2


def test_schedule_audits_without_reconcile_leaves_the_store_unchanged():
    service = world(discovery=True)
    before = digest_of(service.store)
    with pytest.raises(ContractError, match=RECONCILE_MESSAGE):
        schedule_audits(service, outbox=Outbox())
    assert digest_of(service.store) == before


def test_no_outbox_is_refused_at_the_first_append_and_rolled_back():
    service = world(discovery=True)
    before = digest_of(service.store)
    with pytest.raises(ContractError, match=OUTBOX_MESSAGE):
        schedule_audits(service, reconcile_audits=lambda: None)
    assert digest_of(service.store) == before and count(service.store, "schedule") == 0


def test_no_outbox_in_schedule_research_rolls_its_slot_back():
    service = world()
    before = digest_of(service.store)
    with pytest.raises(ContractError, match=OUTBOX_MESSAGE):
        schedule_research(service, NOW, reconcile_audits=lambda: None)
    assert digest_of(service.store) == before


def test_a_pass_that_schedules_nothing_succeeds_without_an_outbox():
    for service in (world(control="paused", discovery=True), world(control=None), world()):
        before = digest_of(service.store)
        assert schedule_audits(service, reconcile_audits=lambda: None) == 0
        assert digest_of(service.store) == before


def test_the_reconcile_port_runs_before_the_control_is_read():
    service = world(control=None, discovery=True)

    def activate():
        with service.store.transaction() as tx:
            tx.put("research_control", "activation", {"status": "active"})

    assert schedule_audits(service, outbox=Outbox(), reconcile_audits=activate) == 1
