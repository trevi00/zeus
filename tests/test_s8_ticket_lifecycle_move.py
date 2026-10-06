"""S8 pilot 98 (DESIGN-s8 §6 V11): M7 `application/ticket_lifecycle.py` moves to `intake.application.ticket_lifecycle` VERBATIM through one named rule
(R-tl0 import homes; A/evidence/rebuild/s8/ticket-lifecycle-move/transcribe.py).

M7 is read only as text through `git show e38aa722:...` and compared by AST (never imported: both packages are named `codex_harness`). Behaviour is
checked on the TARGET only, against literals; the recorded comparison is the `intake.ticket_lifecycle` golden."""

from __future__ import annotations

import ast
import importlib
import inspect
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from _layout import REPO, TARGET

SRC = TARGET / "src" / "codex_harness"
SOURCE = "e38aa722"
APP = "codex_harness.intake.application.ticket_lifecycle"
M7_PATH = "src/codex_harness/application/ticket_lifecycle.py"
BUCKETS = ("tickets", "ticket_dispatches", "ticket_closures", "ticket_closure_sequences", "ticket_reopens", "ticket_github",
           "ticket_lifecycle_events", "ticket_trust_anchors")
HOMES = {"datetime": ["datetime", "timedelta", "timezone"], "json": [],
         "codex_harness.intake.domain.ticket_lifecycle": ["timestamp", "validate_evidence", "validate_packet"],
         "codex_harness.kernel.errors": ["require"], "codex_harness.kernel.ids": ["canonical", "digest", "utcnow"]}


def m7_text(path=M7_PATH):
    return subprocess.run(["git", "-C", str(REPO), "show", f"{SOURCE}:{path}"], check=True, capture_output=True, text=True).stdout


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
        if isinstance(node, (ast.Import, ast.ImportFrom)) or (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)):
            continue
        key = defined(node) or ("expr", i)
        assert key not in out
        out[key] = node
    return out


def imports(src):
    found = {}
    for node in ast.parse(src).body:
        if isinstance(node, ast.ImportFrom):
            found.setdefault(node.module, []).extend(a.name for a in node.names)
        elif isinstance(node, ast.Import):
            for a in node.names:
                found.setdefault(a.name, [])
    return found


def put_literals(src):
    return {c.args[0].value for c in ast.walk(ast.parse(src)) if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
            and c.func.attr == "put" and c.args and isinstance(c.args[0], ast.Constant)}


def writers(values):
    """Relative paths of target modules with a `.put`/`.delete` whose first argument is one of `values` (a literal)."""
    found = set()
    for path in sorted(SRC.rglob("*.py")):
        for call in ast.walk(ast.parse(path.read_text())):
            if (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) and call.func.attr in ("put", "delete") and call.args
                    and isinstance(call.args[0], ast.Constant) and call.args[0].value in values):
                found.add(path.relative_to(SRC).as_posix())
    return found


# ---- the transcription: AST against M7 ---------------------------------------------------------------------------------
def test_every_statement_is_m7s_in_m7_order_without_any_rewrite():
    ref, ours = statements(m7_text()), statements(target_text())
    assert list(ref) == [("require_no_promotion",), ("event_document",), ("verify_chain",), ("transition",), ("TicketLifecycle",)]
    assert list(ours) == list(ref)
    for key in ours:
        assert ast.dump(ours[key]) == ast.dump(ref[key]), key


def test_r_tl0_the_import_homes_are_exactly_the_v11_homes():
    ref, ours = imports(m7_text()), imports(target_text())
    assert {k: sorted(v) for k, v in ours.items()} == {k: sorted(v) for k, v in HOMES.items()}
    assert sorted(ref["codex_harness.domain.model"]) == ["canonical", "digest", "require", "utcnow"]
    assert ref["codex_harness.domain.ticket_lifecycle"] == ours["codex_harness.intake.domain.ticket_lifecycle"]
    for module, wanted in HOMES.items():
        if module.startswith("codex_harness."):
            home = importlib.import_module(module)
            assert all(hasattr(home, name) for name in wanted), module


def test_the_module_spawns_nothing_and_imports_no_adapter_domain_or_application_of_m7():
    tree = ast.parse(target_text())
    assert not [n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom)) and "subprocess" in ast.unparse(n)]
    for module in imports(target_text()):
        assert not module.startswith(("codex_harness.adapters", "codex_harness.domain", "codex_harness.application")), module


def test_header_names_context_layer_the_move_and_the_rule():
    header = target_text().split('"""')[1]
    for needle in ("Layer: application", "Context: intake", "Owns:", "Does not own:", "Entry points:", "Contracts: INV-TICKET-001",
                   "SOURCE e38aa722", "DESIGN-s8 §6 V11", "R-tl0", "ticket-lifecycle-move/transcribe.py"):
        assert needle in header, needle
    assert header.startswith("Durable acceptance decisions; remote issue projection is a separate operation.")


def test_the_collaborators_are_injected_not_imported_the_call_signature_audit():
    ours = statements(target_text())[("TicketLifecycle",)]
    init = next(n for n in ours.body if isinstance(n, ast.FunctionDef) and n.name == "__init__")
    assert [a.arg for a in init.args.args] == ["self", "tickets", "artifacts", "authority"]
    used = {}
    for node in ast.walk(ours):
        if (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Attribute) and isinstance(node.value.value, ast.Name)
                and node.value.value.id == "self" and node.value.attr in ("tickets", "artifacts", "authority")):
            used.setdefault(node.value.attr, set()).add(node.attr)
    assert used == {"tickets": {"get"}, "artifacts": {"document", "put", "text"}, "authority": {"policy", "require_merged", "verify"}}


# ---- the buckets: one declaration, one writer --------------------------------------------------------------------------
def test_v11_intake_owns_the_eight_ticket_buckets_and_the_source_writers_write_them():
    from codex_harness.intake import ports

    for bucket in BUCKETS:
        assert ports.OWNED_BUCKETS.count(bucket) == 1, bucket
    assert ports.OWNED_BUCKETS[:8] == ("portfolio_bindings", "portfolio_acceptances", "portfolio_investigations", "portfolio_followups",
                                       "desk_sessions", "desk_requests", "desk_events", "desk_receipts")
    # S8 batch B2 (V30 R-tk3) appends the five buckets `Tickets` and `GitHubTickets` write after these eight
    assert ports.OWNED_BUCKETS[8:16] == BUCKETS
    for path in sorted(SRC.glob("*/ports.py")):
        if path.parent.name != "intake":
            owned = getattr(importlib.import_module(f"codex_harness.{path.parent.name}.ports"), "OWNED_BUCKETS", ())
            assert not set(BUCKETS) & set(owned), path
    assert put_literals(target_text()) == set(BUCKETS)
    assert put_literals(m7_text()) == set(BUCKETS)
    # V30 R-tk4: the SOURCE writer set per bucket. The lifecycle is the only writer of the six decision, closure, reopen, event and pin buckets;
    # in SOURCE `Tickets` (application/tickets.py) also writes `tickets` and `ticket_dispatches`, and `GitHubTickets` (adapters/github_tickets.py)
    # `ticket_github` (the b8b582d9 lesson: a single-writer pin names every writer SOURCE has).
    lifecycle = "intake/application/ticket_lifecycle.py"
    tickets_module = "intake/application/tickets.py"
    expected = {bucket: {lifecycle} for bucket in BUCKETS}
    expected["tickets"] = expected["ticket_dispatches"] = {lifecycle, tickets_module}
    expected["ticket_github"] = {lifecycle, "intake/adapters/github_tickets.py"}
    assert {bucket: writers((bucket,)) for bucket in BUCKETS} == expected


# ---- the target behaviour, against literals ----------------------------------------------------------------------------
def world():
    from codex_harness.storage.adapters.memory_store import MemoryStore

    store = MemoryStore()
    row = {"id": "ZEUS-1", "revision": 1, "content_hash": "h" * 64, "status": "open", "created_at": "2026-09-22T00:00:00+00:00"}
    with store.transaction() as tx:
        tx.put("tickets", "ZEUS-1", row)
        tx.put("ticket_dispatches", "d-1", {"id": "d-1", "ticket_id": "ZEUS-1", "status": "dispatched"})
        tx.put("ticket_github", "g-1", {"id": "g-1", "ticket_id": "ZEUS-1", "status": "synced", "desired_state": "OPEN"})
    return store


def test_the_constructor_takes_the_stores_of_the_injected_tickets_positionally():
    from codex_harness.intake.application.ticket_lifecycle import TicketLifecycle

    assert list(inspect.signature(TicketLifecycle.__init__).parameters) == ["self", "tickets", "artifacts", "authority"]
    store, artifacts, authority = world(), object(), object()
    tickets = SimpleNamespace(store=store)
    life = TicketLifecycle(tickets, artifacts, authority)
    assert life.tickets is tickets and life.store is store and life.artifacts is artifacts and life.authority is authority


def test_reopen_of_an_open_ticket_writes_the_event_the_request_the_ticket_the_dispatches_and_the_links_and_replays():
    from codex_harness.intake.application.ticket_lifecycle import TicketLifecycle
    from codex_harness.kernel.ids import digest

    store = world()
    life = TicketLifecycle(SimpleNamespace(store=store), object(), object())
    first = life.reopen("ZEUS-1", 1, 0, "Recurrence", expected_status="open")
    event = first["decision"]
    assert first["replayed"] is False and first["verification"] == "not_required_authority_removed"
    request = digest({"ticket_id": "ZEUS-1", "revision": 1, "from_sequence": 0, "expected_status": "open", "reason": "Recurrence"})
    assert (event["kind"], event["sequence"], event["from_sequence"], event["previous_event"], event["previous_status"], event["request_id"]) == (
        "reopened", 1, 0, None, "open", request)
    assert event["id"] == digest({k: v for k, v in event.items() if k != "id"})
    with store.transaction() as tx:
        assert tx.get("ticket_reopens", request) == {"event_id": event["id"]}
        ticket = tx.get("tickets", "ZEUS-1")
        assert (ticket["status"], ticket["lifecycle_sequence"], ticket["lifecycle_event"]) == ("open", 1, event["id"])
        assert tx.get("ticket_dispatches", "d-1")["status"] == "superseded"
        assert tx.get("ticket_dispatches", "d-1")["lifecycle_event"] == event["id"]
        assert tx.get("ticket_github", "g-1")["status"] == "pending" and tx.get("ticket_github", "g-1")["desired_state"] == "OPEN"
    again = life.reopen("ZEUS-1", 1, 0, "Recurrence", expected_status="open")
    assert again == {"decision": event, "replayed": True, "verification": "not_required_authority_removed"}


@pytest.mark.parametrize("arguments, message", [
    (("ZEUS-1", "1", 0, "r"), "Exact reopen revision and sequence required"),
    (("ZEUS-1", 1, 0, "  "), "Reopen reason required"),
    (("ZEUS-9", 1, 0, "r"), "Ticket not found"),
    (("ZEUS-1", 1, 0, "r"), "Stale reopen revision, sequence or state"),
])
def test_reopen_refusals_are_contract_errors_and_write_nothing(arguments, message):
    from codex_harness.intake.application.ticket_lifecycle import TicketLifecycle
    from codex_harness.kernel.errors import ContractError

    store = world()
    with store.transaction() as tx:
        before = tx.records()
    with pytest.raises(ContractError, match=message):
        TicketLifecycle(SimpleNamespace(store=store), object(), object()).reopen(*arguments)
    with store.transaction() as tx:
        assert tx.records() == before


def test_an_unresolved_promotion_blocks_the_transition_and_writes_nothing():
    from codex_harness.intake.application.ticket_lifecycle import TicketLifecycle
    from codex_harness.kernel.errors import ContractError

    store = world()
    with store.transaction() as tx:
        tx.put("promotion_intents", "p-1", {"status": "pending", "candidate": {"zeus_ticket": {"id": "ZEUS-1"}}})
        before = tx.records()
    with pytest.raises(ContractError, match="Ticket promotion unresolved"):
        TicketLifecycle(SimpleNamespace(store=store), object(), object()).reopen("ZEUS-1", 1, 0, "r", expected_status="open")
    with store.transaction() as tx:
        assert tx.records() == before
