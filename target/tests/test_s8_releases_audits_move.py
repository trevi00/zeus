"""S8 pilot 106 (DESIGN-s8 §19.1 R-ra1..R-ra4): M7 `Releases.reconcile_audits` and `Releases.request_reverification` move into review's
`Releases`, inserted verbatim at M7's relative positions with the clock and the event journal on the S7 seams.

M7 is read only as text through `git show e38aa722:...` and compared by AST (never imported: both packages are named `codex_harness`). Behaviour is
compared by the recorded `review.releases_audits` golden (the moved methods are target-equal to it); the seams the golden cannot reach (an unwired
event journal, a non-UTC injected clock, the recorded event call) are pinned here.
"""

from __future__ import annotations

import ast
import copy
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from codex_harness.intake.application import tickets
from codex_harness.kernel.errors import ContractError
from codex_harness.kernel.ids import digest
from codex_harness.research import ports as research_ports
from codex_harness.review import ports as review_ports
from codex_harness.review.application import releases as module
from codex_harness.review.application.releases import Releases
from codex_harness.review.domain.releases import reverification_successor_id
from codex_harness.routing.adapters.organization_source import packaged_organization
from codex_harness.storage.adapters.memory_store import MemoryStore

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "target" / "src" / "codex_harness"
SOURCE = "e38aa722"
M7_PATH = "src/codex_harness/application/releases.py"
NEW = ["reconcile_audits", "request_reverification"]
CHECKS = ["tests", "cli_start", "cli_file_task"]


def m7_text():
    return subprocess.run(["git", "-C", str(REPO), "show", f"{SOURCE}:{M7_PATH}"], check=True, capture_output=True, text=True).stdout


def target_text():
    return Path(module.__file__).read_text()


def releases_class(src):
    return next(n for n in ast.parse(src).body if isinstance(n, ast.ClassDef) and n.name == "Releases")


def methods(src):
    return {n.name: n for n in releases_class(src).body if isinstance(n, ast.FunctionDef)}


def is_event_put(node):
    return (isinstance(node, ast.Expr) and isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Attribute)
            and node.value.func.attr == "put" and isinstance(node.value.func.value, ast.Name) and node.value.func.value.id == "tx"
            and bool(node.value.args) and isinstance(node.value.args[0], ast.Constant) and node.value.args[0].value == "events")


class Rules(ast.NodeTransformer):
    """R-ra2 and R-ra3 applied to M7's AST: what the moved method must equal."""

    def __init__(self):
        self.now = self.event = 0

    def visit_Assign(self, node):
        if ast.unparse(node) == "now = now or datetime.now(timezone.utc)":
            self.now += 1
            return ast.parse("now = now or _now(self.clock)").body[0]
        return node

    def visit_Expr(self, node):
        if is_event_put(node):
            self.event += 1
            return ast.Expr(value=ast.Call(func=ast.parse("self._event").body[0].value, args=[ast.Name(id="tx", ctx=ast.Load()),
                                                                                           *node.value.args[1:]], keywords=[]))
        return node


# ---- R-ra1: verbatim, at M7's relative positions -------------------------------------------------------------------------------------------
def test_r_ra1_the_two_methods_sit_right_after_the_same_predecessors_as_in_m7():
    mine, theirs = list(methods(target_text())), list(methods(m7_text()))
    assert theirs[theirs.index("reconcile_audits") - 1] == "__init__" == mine[mine.index("reconcile_audits") - 1]
    assert (theirs[theirs.index("request_reverification") - 1] == "_check_rejected_source"
            == mine[mine.index("request_reverification") - 1])
    # M7 order is kept among the methods both classes have
    assert [n for n in mine if n in theirs] == [n for n in theirs if n in mine]


@pytest.mark.parametrize("name", NEW)
def test_r_ra1_each_method_equals_m7_by_ast_modulo_r_ra2_and_r_ra3(name):
    rules = Rules()
    expected = rules.visit(copy.deepcopy(methods(m7_text())[name]))
    ast.fix_missing_locations(expected)
    assert ast.dump(methods(target_text())[name]) == ast.dump(expected)
    assert (rules.now, rules.event) == ((0, 0) if name == "reconcile_audits" else (1, 1))


def test_r_ra1_every_other_target_method_is_unchanged_from_the_pilots_base():
    base = subprocess.run(["git", "-C", str(REPO), "show", "b8b582d985b44474463143cb28761555d9bd8cc4:target/src/codex_harness/review/application/releases.py"],
                          check=True, capture_output=True, text=True).stdout
    mine, before = methods(target_text()), methods(base)
    assert set(mine) == set(before) | set(NEW)
    assert all(ast.dump(mine[name]) == ast.dump(before[name]) for name in before)
    assert [ast.dump(n) for n in ast.parse(target_text()).body[1:] if not isinstance(n, ast.ClassDef)] == [
        ast.dump(n) for n in ast.parse(base).body[1:] if not isinstance(n, ast.ClassDef)]


def test_the_m7_text_of_the_two_methods_is_byte_for_byte_in_the_target_except_the_two_rules():
    lines = {name: ast.get_source_segment(m7_text(), node) for name, node in methods(m7_text()).items()}
    mine = {name: ast.get_source_segment(target_text(), node) for name, node in methods(target_text()).items()}
    assert mine["reconcile_audits"] == lines["reconcile_audits"]
    expected = (lines["request_reverification"].replace("datetime.now(timezone.utc)", "_now(self.clock)")
                .replace('tx.put("events", "release.reverification_requested:" + successor_id,\n                   {',
                         'self._event(tx, "release.reverification_requested:" + successor_id,\n                        {'))
    assert [line.strip() for line in mine["request_reverification"].splitlines()] == [line.strip() for line in expected.splitlines()]


# ---- R-ra2 / R-ra3: no datetime.now and no tx.put("events" left in the class -------------------------------------------------------------------
def test_no_datetime_now_and_no_event_put_is_left_in_the_class():
    tree = releases_class(target_text())
    now_calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "now"]
    assert now_calls == []
    assert [n for n in ast.walk(tree) if is_event_put(n)] == []


# ---- behaviour the golden cannot reach ----------------------------------------------------------------------------------------------------------
class Clock:
    def __init__(self, value):
        self.value = value

    def now(self):
        return self.value


class Journal:
    def __init__(self):
        self.calls = []

    def append(self, tx, identity, body):
        self.calls.append((identity, body))
        tx.put("events", identity, body)


def rejected(store, release_id="release-0001"):
    policy = {"checks": CHECKS}
    reviews = [{"actor": a, "accepted": True, "revision": "candidate", "evidence": "fixture:review"} for a in ("lead:improvement", "conductor")]
    checks = {"tests": {"passed": False, "evidence": "fixture:failed"}, **{k: {"passed": False, "skipped": True, "evidence": "fixture:skip"} for k in CHECKS[1:]}}
    with store.transaction() as tx:
        tx.put("releases", release_id, {"id": release_id, "candidate": {"revision": "candidate", "base": "base", "tree": "tree",
                                                                        "author": "worker:implementation"},
                                         "policy": policy, "policy_hash": digest(policy), "status": "rejected", "reviews": reviews,
                                         "checks": checks, "created_at": "2026-09-22T00:00:00+00:00"})
    return digest(policy)


def build(clock=None, events=None):
    store = MemoryStore()
    return store, Releases(store, packaged_organization(), ticket_binding=tickets.ticket_binding, clock=clock, events=events), rejected(store)


def snapshot(store):
    with store.transaction() as tx:
        return [(r["bucket"], r["id"], digest(r["body"])) for r in tx.records()]


def request(releases, policy_hash, **kwargs):
    return releases.request_reverification("release-0001", "conductor", "candidate", policy_hash, "fixture: short TEMP diagnosis",
                                           "fixture:diagnosis-receipt", **kwargs)


def test_r_ra2_the_default_receipt_time_is_the_injected_clock_in_utc():
    korea = timezone(timedelta(hours=9))
    store, releases, policy_hash = build(clock=Clock(datetime(2026, 9, 22, 21, 0, 0, tzinfo=korea)), events=Journal())
    record = request(releases, policy_hash)
    assert record["created_at"] == "2026-09-22T12:00:00+00:00" == record["reverification"]["at"]


def test_r_ra2_an_explicit_now_wins_over_the_clock():
    now = datetime(2030, 1, 1, tzinfo=timezone.utc)
    store, releases, policy_hash = build(clock=Clock(datetime(2026, 9, 22, tzinfo=timezone.utc)), events=Journal())
    assert request(releases, policy_hash, now=now)["created_at"] == now.isoformat()


def test_r_ra3_the_event_goes_through_the_injected_journal_once_with_the_m7_key_and_body():
    journal = Journal()
    store, releases, policy_hash = build(clock=Clock(datetime(2026, 9, 22, tzinfo=timezone.utc)), events=journal)
    record = request(releases, policy_hash)
    successor = reverification_successor_id("release-0001")
    assert journal.calls == [("release.reverification_requested:" + successor,
                              {"type": "release.reverification_requested", "at": record["created_at"], "release_id": successor,
                               "reverify_of": "release-0001", "actor": "conductor"})]
    # a replay returns the successor without a second journal call
    assert request(releases, policy_hash) == record
    assert len(journal.calls) == 1


def test_r_ra3_an_unwired_journal_refuses_and_the_unit_leaves_the_store_as_it_was():
    store, releases, policy_hash = build(clock=Clock(datetime(2026, 9, 22, tzinfo=timezone.utc)), events=None)
    before = snapshot(store)
    with pytest.raises(ContractError, match="Event journal is not wired"):
        request(releases, policy_hash)
    assert snapshot(store) == before


def test_reconcile_audits_needs_no_injected_port_and_writes_nothing_without_an_active_release():
    store = MemoryStore()
    releases = Releases(store, packaged_organization(), ticket_binding=tickets.ticket_binding)
    assert releases.reconcile_audits() is None
    assert snapshot(store) == []


# ---- R-ra4 and the bucket owners ----------------------------------------------------------------------------------------------------------------
def test_r_ra4_the_header_owns_the_two_methods_and_no_longer_disclaims_them():
    header = ast.get_docstring(ast.parse(target_text()))
    owns, rest = header.split("Does not own:", 1)
    assert "request_reverification" in owns and "reconcile_audits" in owns
    assert "reconcile_audits" not in rest.split("Entry points:", 1)[0]
    assert "request_reverification" not in rest.split("Entry points:", 1)[0]
    assert "(S8)" not in header.split("Entry points:", 1)[0]


def writers(values, root=SRC):
    found = set()
    for path in sorted(root.rglob("*.py")):
        for call in ast.walk(ast.parse(path.read_text())):
            if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) and call.func.attr in ("put", "delete") and call.args:
                if isinstance(call.args[0], ast.Constant) and call.args[0].value in values:
                    found.add(path.relative_to(SRC).as_posix())
    return found


def test_there_is_no_owned_buckets_change_and_review_is_the_single_writer_of_its_buckets():
    for bucket in ("releases", "deployment", "research_control"):
        assert review_ports.OWNED_BUCKETS.count(bucket) == 1, bucket
        assert bucket not in research_ports.OWNED_BUCKETS, bucket
    assert writers({"releases"}) == {"review/application/releases.py"}
    assert writers({"research_control"}) == {"review/application/releases.py"}
    # `events` stays coordination's: the review class never writes it directly
    assert "review/application/releases.py" not in writers({"events"})
