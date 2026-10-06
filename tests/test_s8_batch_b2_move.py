"""S8 batch B2 (intake, DESIGN-s8 §25 V30): the rest of M7 `application/tickets.py` is MERGED into `intake.application.tickets` (R-tk1 verbatim, R-tk2 the
injected `outbox` and `clock`), and M7 `adapters/github_tickets.py` moves to `intake.adapters.github_tickets` (R-gh1 the injected `run_process`, the spawn
chokepoint, and `clock`); R-tk3 declares the five buckets, R-tk4 pins their SOURCE writers (test_s8_ticket_lifecycle_move.py).

M7 is read only as text through `git show e38aa722:...` and compared by AST (never imported: both packages are named `codex_harness`); the S4 move-ahead
names are also compared against the batch's base commit. Behaviour is compared by the recorded `intake.tickets` and `intake.github_tickets` goldens (the
wired modules are target-equal to them); the unwired `outbox` and `run_process` refusals have no M7 counterpart and are pinned here, each with the whole
store unchanged.
"""

from __future__ import annotations

import ast
import importlib
import inspect
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from _layout import REPO, TARGET

# git_workspace binds `process_groups.run_process` by name at its first import, so it must load before any patch of
# `process_groups.run_process`; first imported under a patch it keeps the fake for the rest of the session.
import codex_harness.host_os.adapters.git_workspace  # noqa: F401
from codex_harness.intake import ports
from codex_harness.intake.adapters import github_tickets as github
from codex_harness.intake.application import tickets
from codex_harness.kernel.errors import ContractError
from codex_harness.kernel.ids import digest
from codex_harness.routing.adapters.organization_source import packaged_organization
from codex_harness.storage.adapters.memory_store import MemoryStore

SRC = TARGET / "src" / "codex_harness"
SOURCE = "e38aa722"
BASE = "0831cc33"   # the batch's base head: the S4 move-ahead names are compared against the file as it stood there
TK_M7 = "src/codex_harness/application/tickets.py"
TK_TARGET = "target/src/codex_harness/intake/application/tickets.py"
GH_M7 = "src/codex_harness/adapters/github_tickets.py"
S4_NAMES = ("TicketSuperseded", "TicketClosed", "ticket_binding")
TICKET_BUCKETS = ("ticket_reviews", "ticket_revisions")
GITHUB_BUCKETS = ("ticket_remote_creations", "ticket_remote_observations", "ticket_syncs")
FORBIDDEN = ("codex_harness.adapters", "codex_harness.domain", "codex_harness.application", "codex_harness.review", "codex_harness.coordination",
             "codex_harness.host_os")


def git_show(rev, path):
    return subprocess.run(["git", "-C", str(REPO), "show", f"{rev}:{path}"], check=True, capture_output=True, text=True).stdout


def text_of(module):
    return Path(module.__file__).read_text()


def statements(src):
    """Every top-level statement but the imports and the docstring, keyed by name (or position)."""
    out = {}
    for i, node in enumerate(ast.parse(src).body):
        if isinstance(node, (ast.Import, ast.ImportFrom)) or (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)):
            continue
        name = getattr(node, "name", None) or (node.targets[0].id if isinstance(node, ast.Assign) else i)
        out[name] = node
    return out


def top_imports(src):
    found = {}
    for node in ast.parse(src).body:
        if isinstance(node, ast.ImportFrom):
            found[node.module] = sorted(a.name for a in node.names)
    return found


def all_import_modules(src):
    return sorted({n.module for n in ast.walk(ast.parse(src)) if isinstance(n, ast.ImportFrom)})


def calls(src, attr):
    return [n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == attr]


def header(module):
    return ast.get_docstring(ast.parse(text_of(module)))


def tx_writes(src):
    return sorted({n.args[0].value for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                   and isinstance(n.func.value, ast.Name) and n.func.value.id == "tx" and n.func.attr in {"put", "delete"} and n.args
                   and isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str)})


def writers(bucket):
    """Relative paths of target modules with a `.put`/`.delete` whose first argument is the literal `bucket`."""
    found = set()
    for path in sorted(SRC.rglob("*.py")):
        for call in ast.walk(ast.parse(path.read_text())):
            if (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) and call.func.attr in ("put", "delete") and call.args
                    and isinstance(call.args[0], ast.Constant) and call.args[0].value == bucket):
                found.add(path.relative_to(SRC).as_posix())
    return found


def apply(text, rules):
    for old, new, count in rules:
        assert text.count(old) == count, old
        text = text.replace(old, new)
    return text


def m7_tickets_with_rules():
    """M7's text with R-tk2 applied as text: the independent expectation of the class (the imports are compared separately)."""
    return apply(git_show(SOURCE, TK_M7), (
        ("    def __init__(self, store, organization):\n        self.store, self.org = store, organization\n",
         "    def __init__(self, store, organization, *, outbox=None, clock=None):\n        self.store, self.org = store, organization\n"
         "        self.outbox, self.clock = outbox, clock\n", 1),
        ('            tx.put("outbox", message["message_id"], {"message": message, "sent": False})\n',
         '            require(self.outbox is not None, "Outbox is not wired")\n            self.outbox.append(tx, message)\n', 1),
        ("utcnow()", "utcnow(self.clock)", 3)))


def m7_github_with_rules():
    return apply(git_show(SOURCE, GH_M7), (
        ("    def __init__(self, tickets, artifacts, lifecycle=None):\n", "    def __init__(self, tickets, artifacts, lifecycle=None, *, run_process=None, clock=None):\n", 1),
        ("        self.lifecycle = lifecycle\n", "        self.lifecycle = lifecycle\n        self.run_process, self.clock = run_process, clock\n", 1),
        ('        result = run_process(["gh", *args], timeout=60)\n',
         '        require(self.run_process is not None, "Process runner is not wired")\n        result = self.run_process(["gh", *args], timeout=60)\n', 1),
        ("utcnow()", "utcnow(self.clock)", 3),
        ("from codex_harness.application.ticket_lifecycle import event_document, verify_chain",
         "from codex_harness.intake.application.ticket_lifecycle import event_document, verify_chain", 1)))


# ---- tickets: R-tk1 (the merge) ---------------------------------------------------------------------------------------------------
def test_r_tk1_the_statements_are_m7s_in_m7_order_and_only_tickets_is_rewritten():
    ours, m7 = statements(text_of(tickets)), statements(git_show(SOURCE, TK_M7))
    assert list(m7) == ["TEXT_FIELDS", "LIST_FIELDS", "TicketSuperseded", "TicketClosed", "validate_content", "ticket_binding", "Tickets", "render_ticket"]
    assert list(ours) == list(m7)
    for name, node in m7.items():
        if name != "Tickets":
            assert ast.dump(ours[name]) == ast.dump(node), name
    assert ast.dump(ours["Tickets"]) == ast.dump(statements(m7_tickets_with_rules())["Tickets"])


def test_r_tk1_the_s4_move_ahead_names_are_unchanged_against_the_base_and_m7():
    ours, base, m7 = statements(text_of(tickets)), statements(git_show(BASE, TK_TARGET)), statements(git_show(SOURCE, TK_M7))
    assert [n for n in base if n in S4_NAMES] == list(S4_NAMES) and sorted(base) == sorted(S4_NAMES)
    for name in S4_NAMES:
        assert ast.dump(ours[name]) == ast.dump(base[name]) == ast.dump(m7[name]), name
    # byte-identical source segments too (the docstrings and the comments inside are part of the text)
    for name in S4_NAMES:
        assert ast.get_source_segment(text_of(tickets), ours[name]) == ast.get_source_segment(git_show(BASE, TK_TARGET), base[name]), name
    assert tickets.TicketClosed.__mro__[:3] == (tickets.TicketClosed, tickets.TicketSuperseded, ContractError)


def test_r_tk0_the_import_homes_are_exactly_the_v30_homes():
    src = text_of(tickets)
    assert top_imports(src) == {"copy": ["deepcopy"], "uuid": ["uuid4"], "codex_harness.intake.application.goal_progress": ["admit_dispatch", "validate_manifest"],
                                "codex_harness.kernel.errors": ["ContractError", "require"], "codex_harness.kernel.ids": ["digest", "utcnow"],
                                "codex_harness.kernel.message": ["envelope"]}
    assert all_import_modules(src) == sorted(top_imports(src))
    for module in all_import_modules(src):
        assert not any(module == f or module.startswith(f + ".") for f in FORBIDDEN), module
    m7 = top_imports(git_show(SOURCE, TK_M7))
    assert m7["codex_harness.application.goal_progress"] == ["admit_dispatch", "validate_manifest"]
    assert sorted(m7["codex_harness.domain.model"]) == ["ContractError", "digest", "envelope", "require", "utcnow"]
    for module, names in top_imports(src).items():
        if module.startswith("codex_harness."):
            home = importlib.import_module(module)
            assert all(hasattr(home, n) for n in names), module


def test_the_tickets_header_names_the_layer_owner_contracts_and_rules():
    doc = header(tickets)
    assert doc.startswith(ast.get_docstring(ast.parse(git_show(SOURCE, TK_M7))))
    for line in ("Layer: application", "Context: intake", "Owns:", "TicketSuperseded, TicketClosed, ticket_binding", "validate_content, Tickets", "render_ticket",
                 "Does not own:", "Contracts: INV-TICKET-001", "SOURCE " + SOURCE, "R-tk0", "R-tk1", "R-tk2", "V30"):
        assert line in doc, line


# ---- tickets: R-tk2 (the ports) ---------------------------------------------------------------------------------------------------
def content(title="Isolated environment"):
    return {"title": title, "problem": "Production and tests share endpoints", "impact": "Potential contention", "rollback": "Restore verified image",
            "evidence_refs": ["fixture:source-inspection"], "scope": ["deployment"], "acceptance_criteria": ["Independent services"],
            "verification": ["Run an isolated test"]}


class Appends:
    """A recording `intake.ports.OutboxAppend`: coordination's `Outbox.append(tx, message)` joins the caller's unit."""

    def __init__(self):
        self.messages = []

    def append(self, tx, message):
        self.messages.append(message)
        tx.put("outbox", message["message_id"], {"message": message, "sent": False})


def records(store):
    with store.transaction() as tx:
        return digest(tx.records())


def test_r_tk2_the_positional_shape_is_unchanged_and_the_ports_are_keyword_only():
    params = list(inspect.signature(tickets.Tickets.__init__).parameters.values())
    assert [p.name for p in params if p.kind is p.POSITIONAL_OR_KEYWORD] == ["self", "store", "organization"]
    assert [(p.name, p.default) for p in params if p.kind is p.KEYWORD_ONLY] == [("outbox", None), ("clock", None)]
    assert [(n, str(inspect.signature(getattr(tickets.Tickets, n)))) for n in ("create", "update", "get", "list", "review", "dispatch")] == [
        ("create", "(self, content, author='operator')"), ("update", "(self, ticket_id, expected_revision, content, reason, author='operator')"),
        ("get", "(self, ticket_id, revision=None)"), ("list", "(self)"),
        ("review", "(self, ticket_id, revision, reviewer, claimed_provider, verdict, summary, evidence_refs)"),
        ("dispatch", "(self, ticket_id, expected_revision, repository_revision, goal_manifest=None, criterion_id=None)")]
    store, org = MemoryStore(), packaged_organization()
    bare = tickets.Tickets(store, org)
    assert bare.store is store and bare.org is org and bare.outbox is None and bare.clock is None


def test_r_tk2_without_an_outbox_the_dispatch_is_refused_and_the_whole_store_is_unchanged():
    store = MemoryStore()
    desk = tickets.Tickets(store, packaged_organization())
    row = desk.create(content())
    before = records(store)
    with pytest.raises(ContractError, match="Outbox is not wired"):
        desk.dispatch(row["id"], 1, "base")
    assert records(store) == before
    with store.transaction() as tx:
        assert tx.scan("outbox") == [] and tx.scan("ticket_dispatches") == [] and tx.get("tickets", row["id"])["status"] == "open"


def test_r_tk2_the_dispatch_appends_through_the_injected_port_inside_its_own_unit():
    store, port = MemoryStore(), Appends()
    desk = tickets.Tickets(store, packaged_organization(), outbox=port)
    row = desk.create(content())
    result = desk.dispatch(row["id"], 1, "repository-commit")
    assert len(port.messages) == 1 and port.messages[0]["message_id"] == result["message_id"]
    assert port.messages[0]["where"]["revision"] == "repository-commit" and port.messages[0]["what"]["details"]["zeus_ticket"]["id"] == row["id"]
    with store.transaction() as tx:
        assert [r["message"]["message_id"] for r in tx.scan("outbox")] == [result["message_id"]]
        assert tx.get("tickets", row["id"])["status"] == "dispatched"
    # the replay returns the stored result and appends nothing
    assert desk.dispatch(row["id"], 1, "other") == result and len(port.messages) == 1


def test_r_tk2_a_refused_assignment_leaves_the_store_unchanged_and_the_port_unused():
    store, port = MemoryStore(), Appends()
    org = packaged_organization()
    desk = tickets.Tickets(store, org, outbox=port)
    row = desk.create(content())
    org.agents.pop("lead:improvement")
    before = records(store)
    with pytest.raises(ContractError, match="Unknown actor"):
        desk.dispatch(row["id"], 1, "base")
    assert records(store) == before and port.messages == []


def test_r_tk2_the_injected_clock_stamps_every_row_the_module_writes():
    store, port = MemoryStore(), Appends()
    moment = datetime(2026, 9, 22, 1, 2, 3, tzinfo=timezone.utc)
    clock = SimpleNamespace(now=lambda: moment)
    desk = tickets.Tickets(store, packaged_organization(), outbox=port, clock=clock)
    row = desk.create(content())
    assert row["created_at"] == "2026-09-22T01:02:03+00:00"
    moment = datetime(2026, 9, 22, 1, 2, 4, tzinfo=timezone.utc)
    assert desk.update(row["id"], 1, content("Next"), "Revise")["updated_at"] == "2026-09-22T01:02:04+00:00"
    moment = datetime(2026, 9, 22, 1, 2, 5, tzinfo=timezone.utc)
    assert desk.review(row["id"], 2, "Claude", "claude", "support", "Fine", ["fixture:review"])["at"] == "2026-09-22T01:02:05+00:00"
    assert "utcnow()" not in text_of(tickets).replace(header(tickets), "")


def test_r_tk2_the_module_writes_four_buckets_and_the_outbox_only_through_the_port():
    src = text_of(tickets)
    assert tx_writes(src) == ["ticket_dispatches", "ticket_reviews", "ticket_revisions", "tickets"]
    assert [ast.unparse(n.args[0]) for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "require"
            and n.args and ast.unparse(n.args[0]).startswith("self.outbox")] == ["self.outbox is not None"]
    assert [ast.unparse(n) for n in calls(src, "append") if "outbox" in ast.unparse(n)] == ["self.outbox.append(tx, message)"]


# ---- R-tk3 / R-tk4: the buckets ---------------------------------------------------------------------------------------------------
def test_r_tk3_intake_owns_the_five_buckets_once_and_no_other_context_declares_them():
    five = TICKET_BUCKETS + GITHUB_BUCKETS
    for bucket in five:
        assert ports.OWNED_BUCKETS.count(bucket) == 1, bucket
    assert ports.OWNED_BUCKETS[-5:] == ("ticket_reviews", "ticket_revisions", "ticket_remote_creations", "ticket_remote_observations", "ticket_syncs")
    for path in sorted(SRC.glob("*/ports.py")):
        if path.parent.name != "intake":
            owned = getattr(importlib.import_module(f"codex_harness.{path.parent.name}.ports"), "OWNED_BUCKETS", ())
            assert not set(five) & set(owned), path


def test_r_tk3_each_bucket_has_exactly_one_writer_module():
    for bucket in TICKET_BUCKETS:
        assert writers(bucket) == {"intake/application/tickets.py"}, bucket
    for bucket in GITHUB_BUCKETS:
        assert writers(bucket) == {"intake/adapters/github_tickets.py"}, bucket
    assert tx_writes(text_of(github)) == ["ticket_github", "ticket_remote_creations", "ticket_remote_observations", "ticket_syncs"]
    # R-tk4: the second writer of `ticket_github`, and of `tickets`/`ticket_dispatches`, is the lifecycle (pilot 98); none of the five is written elsewhere
    assert writers("ticket_github") == {"intake/application/ticket_lifecycle.py", "intake/adapters/github_tickets.py"}
    assert writers("tickets") == writers("ticket_dispatches") == {"intake/application/ticket_lifecycle.py", "intake/application/tickets.py"}
    assert writers("outbox").isdisjoint({"intake/application/tickets.py", "intake/adapters/github_tickets.py"})


# ---- github_tickets: R-gh0, R-gh1 -------------------------------------------------------------------------------------------------
def test_r_gh1_github_tickets_is_m7s_modulo_the_ports_and_the_import_homes():
    ours, expected, m7 = statements(text_of(github)), statements(m7_github_with_rules()), statements(git_show(SOURCE, GH_M7))
    assert list(ours) == list(m7) == ["GitHubTickets"]
    assert ast.dump(ours["GitHubTickets"]) == ast.dump(expected["GitHubTickets"])


def test_r_gh0_the_import_homes_are_exactly_the_v30_homes_and_nothing_reaches_the_host_or_the_process():
    src = text_of(github)
    assert top_imports(src) == {"datetime": ["datetime", "timedelta", "timezone"], "pathlib": ["Path"], "uuid": ["uuid4"],
                                "codex_harness.intake.application.tickets": ["render_ticket"], "codex_harness.kernel.errors": ["require"],
                                "codex_harness.kernel.ids": ["canonical", "digest", "utcnow"]}
    assert all_import_modules(src) == sorted(set(top_imports(src)) | {"codex_harness.intake.application.ticket_lifecycle"})
    for module in all_import_modules(src):
        assert not any(module == f or module.startswith(f + ".") for f in FORBIDDEN), module
    m7 = top_imports(git_show(SOURCE, GH_M7))
    assert m7["codex_harness.adapters.commands"] == ["run_process"] and m7["codex_harness.application.tickets"] == ["render_ticket"]
    lazy = importlib.import_module("codex_harness.intake.application.ticket_lifecycle")
    assert hasattr(lazy, "event_document") and hasattr(lazy, "verify_chain")


def test_the_github_tickets_header_names_the_layer_owner_contract_and_rules():
    doc = header(github)
    assert doc.startswith(ast.get_docstring(ast.parse(git_show(SOURCE, GH_M7))))
    for line in ("Layer: adapters", "Context: intake", "Owns:", "GitHubTickets", "ticket_remote_creations, ticket_remote_observations and ticket_syncs",
                 "Does not own:", "Entry points: GitHubTickets", "Contracts: INV-TICKET-001", "SOURCE " + SOURCE, "R-gh0", "R-gh1", "V30"):
        assert line in doc, line


# ---- the spawn chokepoint ---------------------------------------------------------------------------------------------------------
def test_r_gh1_with_every_spawn_path_patched_to_raise_the_module_still_never_spawns(monkeypatch):
    """Behaviour: the host_os chokepoint, `subprocess` and `os.system` raise on use; the unwired module refuses (never
    falling back to a spawn) and the injected runner receives the one `gh` call, so nothing else could have spawned."""
    import os

    from codex_harness.host_os.adapters import process_groups

    def spawned(*args, **kwargs):
        raise AssertionError("the module spawned a process")

    monkeypatch.setattr(process_groups, "run_process", spawned)
    monkeypatch.setattr(subprocess, "Popen", spawned)
    monkeypatch.setattr(subprocess, "run", spawned)
    monkeypatch.setattr(os, "system", spawned)
    store, desk, hub = world()
    row = desk.create(content())
    before = records(store)
    with pytest.raises(ContractError, match="Process runner is not wired"):
        hub._call(["issue", "view", "7"])
    assert records(store) == before
    for operation in (lambda: hub.sync(row["id"], "fixture/zeus"), lambda: hub.pull(row["id"], "fixture/zeus")):
        with pytest.raises(ContractError):  # sync claims before its first call (M7), so only the refusal is pinned here
            operation()
    seen = []
    _, _, wired = world(run_process=lambda argv, **kwargs: seen.append(list(argv)) or SimpleNamespace(
        returncode=0, stdout="ok\n", stderr=""))
    assert wired._call(["issue", "view", "7"]) == "ok" and seen == [["gh", "issue", "view", "7"]]


def test_r_gh1_the_module_never_spawns_and_the_one_call_goes_through_the_injected_port():
    """Structural: no spawn name in the moved source and the one `run_process` call site is the injected port's (the
    S8 move rule R-gh1); behaviour is covered by
    test_r_gh1_with_every_spawn_path_patched_to_raise_the_module_still_never_spawns."""
    src = text_of(github)
    body = src.replace(header(github), "")
    for banned in ("subprocess", "Popen", "os.system", "adapters.commands", "host_os", "import run_process"):
        assert banned not in body, banned
    assert [ast.unparse(n) for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Call) and "run_process" in ast.unparse(n.func)] == ["self.run_process(['gh', *args], timeout=60)"]
    params = list(inspect.signature(github.GitHubTickets.__init__).parameters.values())
    assert [p.name for p in params if p.kind is p.POSITIONAL_OR_KEYWORD] == ["self", "tickets", "artifacts", "lifecycle"]
    assert [(p.name, p.default) for p in params if p.kind is p.KEYWORD_ONLY] == [("run_process", None), ("clock", None)]


class Artifacts:
    def put(self, body, source):
        return {"ref": "sha256:" + digest(body), "source": source}


def world(**ports_):
    store = MemoryStore()
    desk = tickets.Tickets(store, packaged_organization())
    return store, desk, github.GitHubTickets(desk, Artifacts(), **ports_)


def test_r_gh1_without_a_runner_the_call_is_refused_before_anything_is_spawned_and_the_store_is_unchanged():
    store, desk, hub = world()
    desk.create(content())
    before = records(store)
    assert hub.run_process is None and hub.clock is None
    with pytest.raises(ContractError, match="Process runner is not wired"):
        hub._call(["issue", "view", "7", "--repo", "fixture/zeus"])
    assert records(store) == before


def test_r_gh1_the_injected_runner_gets_the_gh_argv_and_the_60_second_timeout_and_its_failure_is_the_m7_refusal():
    seen = []

    def runner(argv, **kwargs):
        seen.append((list(argv), kwargs))
        return SimpleNamespace(returncode=1 if argv[2] == "close" else 0, stdout="  https://github.com/fixture/zeus/issues/7\n  ", stderr="secret detail")

    store, _, hub = world(run_process=runner)
    before = records(store)
    assert hub._call(["issue", "view", "7"]) == "https://github.com/fixture/zeus/issues/7"
    with pytest.raises(RuntimeError, match="GitHub issue operation failed; local ticket retained") as raised:
        hub._call(["issue", "close", "7"])
    assert "secret detail" not in str(raised.value)
    assert seen == [(["gh", "issue", "view", "7"], {"timeout": 60}), (["gh", "issue", "close", "7"], {"timeout": 60})]
    assert records(store) == before


def test_r_gh1_the_injected_clock_stamps_the_observation_and_a_refused_repository_never_calls_the_runner():
    runs = []
    moment = datetime(2026, 9, 22, 4, 5, 6, tzinfo=timezone.utc)
    store, desk, hub = world(run_process=lambda *a, **k: runs.append(a), clock=SimpleNamespace(now=lambda: moment))
    row = desk.create(content())
    remote = {"number": 7, "url": "https://github.com/fixture/zeus/issues/7", "title": "t", "body": "b", "state": "OPEN"}
    observation = hub._observe(row["id"], "fixture/zeus", remote, "pull")
    assert observation["at"] == observation["first_seen"] == "2026-09-22T04:05:06+00:00" and observation["sequence"] == 1
    before = records(store)
    for bad in ("nope", "a/b/c", "", None):
        with pytest.raises(ContractError, match="GitHub repository must be owner/name"):
            hub.sync(row["id"], bad)
        with pytest.raises(ContractError, match="GitHub repository must be owner/name"):
            hub.pull(row["id"], bad)
    assert runs == [] and records(store) == before
    with pytest.raises(ContractError, match="Ticket has no GitHub link"):
        hub.pull(row["id"], "fixture/zeus")
    assert records(store) == before


def test_r_gh1_no_bare_utcnow_remains():
    body = text_of(github).replace(header(github), "")
    assert "utcnow()" not in body and body.count("utcnow(self.clock)") == 3
