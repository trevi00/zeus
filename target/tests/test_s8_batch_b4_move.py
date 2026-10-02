"""S8 batch B4: M7 `application/decision_feedback.py` moves to `research.application.decision_feedback` (V25: R-df1 the two coordination bucket names as
V9 constants, R-df2 the five own buckets) and M7 `application/sdd.py` moves to `review.application.sdd` (V28: R-sdd1 the injected `ticket_binding`, R-sdd2
the injected `clock`, R-sdd3 the seven own buckets).

M7 is read only as text through `git show e38aa722:...` and compared by AST (never imported: both packages are named `codex_harness`). Behaviour is
compared by the recorded `research.decision_feedback` and `review.sdd` goldens (the wired modules are target-equal to them); the unwired
`ticket_binding` refusal has no M7 counterpart and is pinned here.
"""

from __future__ import annotations

import ast
import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from codex_harness.coordination.application import autonomous as coordination
from codex_harness.intake.application.tickets import ticket_binding
from codex_harness.kernel.errors import ContractError
from codex_harness.kernel.ids import canonical, digest
from codex_harness.research import ports as research_ports
from codex_harness.research.application import decision_feedback as feedback
from codex_harness.review import ports as review_ports
from codex_harness.review.application import sdd as sdd_module
from codex_harness.storage.adapters.memory_store import MemoryStore

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "target" / "src" / "codex_harness"
SOURCE = "e38aa722"
DF_M7 = "src/codex_harness/application/decision_feedback.py"
SDD_M7 = "src/codex_harness/application/sdd.py"
DF_BUCKETS = ("decision_observations", "decision_feedback_groups", "recurring_work_candidates", "decision_feedback_conflicts",
              "decision_feedback_collections")
SDD_BUCKETS = ("sdd_events", "sdd_iterations", "sdd_notifications", "sdd_observations", "sdd_proposals", "sdd_spec_heads", "sdd_transfer_candidates")


def m7_text(path):
    return subprocess.run(["git", "-C", str(REPO), "show", f"{SOURCE}:{path}"], check=True, capture_output=True, text=True).stdout


def text_of(module):
    return Path(module.__file__).read_text()


def statements(src):
    out = {}
    for i, node in enumerate(ast.parse(src).body):
        if isinstance(node, (ast.Import, ast.ImportFrom)) or (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)):
            continue
        name = getattr(node, "name", None) or (node.targets[0].id if isinstance(node, ast.Assign) else i)
        out[name] = node
    return out


def import_modules(src):
    return sorted({n.module for n in ast.walk(ast.parse(src)) if isinstance(n, ast.ImportFrom)})


def put_names(src):
    """The bucket named at each `tx.put(...)`: a string constant or the module constant's name."""
    return sorted({n.args[0].value if isinstance(n.args[0], ast.Constant) else n.args[0].id for n in ast.walk(ast.parse(src))
                   if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "put"
                   and isinstance(n.func.value, ast.Name) and n.func.value.id == "tx" and n.args})


# ----- decision_feedback ---------------------------------------------------------------------------------------------------------------------
def test_r_df1_the_v9_constants_equal_coordinations_bucket_names():
    assert feedback.RUNS == coordination.BUCKET == "autonomous_runs"
    assert feedback.RESERVATIONS == coordination.RESERVATIONS == "invocation_reservations"
    assert feedback.READ_BUCKETS == (feedback.RUNS, feedback.SESSIONS, feedback.EVENTS, feedback.TASKS, feedback.RESERVATIONS)
    text = text_of(feedback)
    assert "coordination" not in import_modules(text) and not [m for m in import_modules(text) if "coordination" in m]


def test_decision_feedback_is_m7s_modulo_the_two_constants():
    ours, theirs = statements(text_of(feedback)), statements(m7_text(DF_M7))
    assert list(ours) == ["RUNS", "RESERVATIONS", *theirs]
    assert ast.unparse(ours["RUNS"]) == "RUNS = 'autonomous_runs'" and ast.unparse(ours["RESERVATIONS"]) == "RESERVATIONS = 'invocation_reservations'"
    for name, node in theirs.items():
        assert ast.dump(ours[name]) == ast.dump(node), name


def test_decision_feedback_import_homes_header_and_buckets():
    text = text_of(feedback)
    assert import_modules(text) == ["__future__", "codex_harness.kernel.errors", "codex_harness.kernel.ids", "codex_harness.research.application.dge",
                                    "codex_harness.research.domain.autonomous", "codex_harness.research.domain.decision_feedback"]
    doc = ast.get_docstring(ast.parse(text))
    assert "Layer: application\nContext: research\n" in doc and "Contracts: INV-DECISION-FEEDBACK-001" in doc and "R-df1" in doc and "R-df2" in doc
    assert (feedback.OBSERVATIONS, feedback.GROUPS, feedback.CANDIDATES, feedback.CONFLICTS, feedback.COLLECTIONS) == DF_BUCKETS
    assert feedback.WRITE_BUCKETS == DF_BUCKETS
    assert put_names(text) == sorted(["OBSERVATIONS", "GROUPS", "CANDIDATES", "CONFLICTS", "COLLECTIONS"])
    for bucket in DF_BUCKETS:
        assert research_ports.OWNED_BUCKETS.count(bucket) == 1, bucket


def test_decision_feedback_constructor_is_unchanged_and_refuses_without_evidence():
    import inspect
    parameters = inspect.signature(feedback.DecisionFeedback.__init__).parameters
    assert [(p.name, p.kind.name) for p in parameters.values()] == [("self", "POSITIONAL_OR_KEYWORD"), ("store", "POSITIONAL_OR_KEYWORD"),
                                                                    ("clock", "POSITIONAL_OR_KEYWORD"), ("evidence", "KEYWORD_ONLY")]
    store = MemoryStore()
    with pytest.raises(feedback.DecisionFeedbackError) as refused:
        feedback.DecisionFeedback(store).collect(registry={}, registry_revision="1" * 40, registry_path="p", registry_sha256="3" * 64, repository="r")
    assert refused.value.reason_code == "evidence_port_unavailable"


def test_only_decision_feedback_writes_its_buckets():
    for path in SRC.rglob("*.py"):
        if path == Path(feedback.__file__):
            continue
        assert not [b for b in DF_BUCKETS if f"put('{b}'" in path.read_text() or f'put("{b}"' in path.read_text()], path


# ----- sdd -----------------------------------------------------------------------------------------------------------------------------------
def rewritten_m7_sdd():
    """M7's `SDD` source with R-sdd1/R-sdd2 applied textually: an independent statement of the rules (the script applies them by rule, this by hand)."""
    t = m7_text(SDD_M7)
    require = 'require(self.ticket_binding is not None, "Ticket binding is not wired")'
    edits = [("def __init__(self, store, artifacts, human_provider=None):\n        self.store, self.artifacts = store, artifacts\n",
              "def __init__(self, store, artifacts, human_provider=None, *, ticket_binding=None, clock=None):\n        self.store, self.artifacts = store, artifacts\n"
              "        self.ticket_binding, self.clock = ticket_binding, clock\n"),
             ("    @staticmethod\n    def _current(tx, row):\n        ticket_binding(tx, row)\n",
              "    def _current(self, tx, row):\n        " + require + "\n        self.ticket_binding(tx, row)\n"),
             ('            ticket_binding(tx, {"zeus_ticket": bound})\n', "            " + require + '\n            self.ticket_binding(tx, {"zeus_ticket": bound})\n'),
             ("    @staticmethod\n    def _append(tx,", "    def _append(self, tx,"), ("    @staticmethod\n    def _notify(tx,", "    def _notify(self, tx,"),
             ("utcnow()", "utcnow(self.clock)"), ("from codex_harness.domain.sdd import HASH", "from codex_harness.review.domain.sdd import HASH")]
    for old, new in edits:
        assert old in t, old
        t = t.replace(old, new)
    return ast.parse(t)


def test_sdd_is_m7s_modulo_r_sdd1_and_r_sdd2():
    ours = statements(text_of(sdd_module))
    theirs = {n.name: n for n in rewritten_m7_sdd().body if isinstance(n, ast.ClassDef)}
    assert list(ours) == ["SDD"] and list(theirs) == ["SDD"]
    assert ast.dump(ours["SDD"]) == ast.dump(theirs["SDD"])
    m7 = m7_text(SDD_M7)
    assert m7.count("utcnow()") == 5 and m7.count("ticket_binding(tx") == 2
    text = text_of(sdd_module)
    calls = [ast.unparse(n) for n in ast.walk(ast.parse(text)) if isinstance(n, ast.Call)]
    assert calls.count("utcnow(self.clock)") == 5 and "utcnow()" not in calls
    assert calls.count("require(self.ticket_binding is not None, 'Ticket binding is not wired')") == 2
    assert len([c for c in calls if c.startswith("self.ticket_binding(tx")]) == 2


def test_sdd_import_homes_header_and_buckets():
    text = text_of(sdd_module)
    assert import_modules(text) == ["codex_harness.evidence.domain.gate_verdicts", "codex_harness.kernel.errors", "codex_harness.kernel.ids",
                                    "codex_harness.review.domain.sdd", "dataclasses"]
    assert "ticket_binding import" not in text and "application.tickets" not in text
    doc = ast.get_docstring(ast.parse(text))
    assert "Layer: application\nContext: review\n" in doc and "Contracts: INV-GATE-001, INV-ORACLE-001" in doc
    assert "R-sdd1" in doc and "R-sdd2" in doc and "R-sdd3" in doc
    assert set(put_names(text)) == set(SDD_BUCKETS)
    for bucket in SDD_BUCKETS:
        assert review_ports.OWNED_BUCKETS.count(bucket) == 1, bucket
    for path in SRC.rglob("*.py"):
        if path != Path(sdd_module.__file__):
            assert not [b for b in SDD_BUCKETS if f"put('{b}'" in path.read_text() or f'put("{b}"' in path.read_text()], path


def test_sdd_positional_shape_is_unchanged_and_the_ports_are_keyword_only():
    import inspect
    parameters = inspect.signature(sdd_module.SDD.__init__).parameters
    assert [(p.name, p.kind.name, p.default) for p in parameters.values()][1:] == [
        ("store", "POSITIONAL_OR_KEYWORD", inspect.Parameter.empty), ("artifacts", "POSITIONAL_OR_KEYWORD", inspect.Parameter.empty),
        ("human_provider", "POSITIONAL_OR_KEYWORD", None), ("ticket_binding", "KEYWORD_ONLY", None), ("clock", "KEYWORD_ONLY", None)]


class Artifacts:
    """A minimal content-addressed double for the unwired tests (the labelled one of the golden is the full double)."""

    def __init__(self):
        self.bodies = {}

    def put(self, body, kind):
        ref = "sha256:" + hashlib.sha256(body.encode()).hexdigest()
        self.bodies[ref] = body
        return {"ref": ref}

    def document(self, ref):
        return json.loads(self.bodies[ref])


class FixedClock:
    def now(self):
        from datetime import datetime, timezone
        return datetime(2026, 9, 22, 12, 0, 0, tzinfo=timezone.utc)


def spec():
    return {"schema": "zeus.sdd.v1", "id": "spec.alpha", "title": "Alpha", "intent": "Review the intent", "personas": ["owner"],
            "requirements": [{"id": "REQ.a", "statement": "s", "risk": "normal", "status": "active"}],
            "scenarios": [{"id": "SCN.a", "title": "t", "status": "active", "requirement_ids": ["REQ.a"], "given": ["g"], "when": ["w"], "then": ["t"],
                           "device_profiles": ["DEV.a"], "bindings": []}],
            "devices": [{"id": "DEV.a", "manufacturer": "samsung", "platform": "android", "form_factor": "phone", "physical_required": True,
                         "conditions": ["c"]}],
            "design": {"components": "c", "icons": "i", "tokens": "t", "required_stories": ["s"]},
            "target": {"kind": "unconfigured", "app_id": None, "build_hash": None, "alpha_url": None}, "reset_contract": "r"}


ENV_FIELDS = ["device_id", "manufacturer", "model", "form_factor", "platform", "os_version", "one_ui_version", "webview_version", "app_build_hash",
              "locale", "timezone", "orientation", "backend_revision", "data_revision", "reset_receipt", "physical_device"]
SOURCE_DRAFT = {"mode": "working_tree_draft", "repository": "contract-test", "revision": None, "path": "spec.json"}


def planted():
    store = MemoryStore()
    content = {"title": "SDD", "ticket": "T-1"}
    with store.transaction() as tx:
        tx.put("tickets", "T-1", {"id": "T-1", "revision": 1, "content_hash": digest(content), "status": "open", "lifecycle_sequence": 0})
        tx.put("ticket_revisions", "T-1:1", {"id": "T-1:1", "content": content})
    return store


def store_digest(store):
    with store.transaction() as tx:
        return digest([[r["bucket"], r["id"], digest(r["body"])] for r in tx.records()])


def test_r_sdd1_an_unwired_ticket_binding_is_refused_before_any_row_is_written():
    store = planted()
    before = store_digest(store)
    unwired = sdd_module.SDD(store, Artifacts())
    with pytest.raises(ContractError, match="Ticket binding is not wired"):
        unwired.register(spec(), "T-1", 1, SOURCE_DRAFT)
    assert store_digest(store) == before, "the one require stands before the first read of the binding"
    wired = sdd_module.SDD(store, Artifacts(), ticket_binding=ticket_binding, clock=FixedClock())
    row = wired.register(spec(), "T-1", 1, SOURCE_DRAFT)
    after = store_digest(store)
    again = sdd_module.SDD(store, wired.artifacts)
    env = dict.fromkeys(ENV_FIELDS, "unverified-contract-input")
    env.update(physical_device=False, form_factor="unknown", orientation="unknown")
    event = {"sequence": 1, "scenario_id": "SCN.a", "kind": "observation", "name": "n", "observed": "o", "source_ref": "r", "timestamp": None,
             "observed_timestamp": "2026-09-09T00:00:00+00:00"}
    with pytest.raises(ContractError, match="Ticket binding is not wired"):
        again.observe(row["id"], env, [event], "source")
    with pytest.raises(ContractError, match="Ticket binding is not wired"):
        again.request_advance(row["id"], 1)
    assert store_digest(store) == after, "an unwired request writes nothing"


def test_r_sdd2_the_injected_clock_stamps_every_row_and_none_uses_the_system_clock():
    store = planted()
    wired = sdd_module.SDD(store, Artifacts(), ticket_binding=ticket_binding, clock=FixedClock())
    row = wired.register(spec(), "T-1", 1, SOURCE_DRAFT)
    assert row["created_at"] == "2026-09-22T12:00:00+00:00"
    with store.transaction() as tx:
        assert [e["at"] for e in tx.scan("sdd_events")] == ["2026-09-22T12:00:00+00:00"]
        assert {n["first_seen"] for n in tx.scan("sdd_notifications")} == {"2026-09-22T12:00:00+00:00"}
        assert {n["last_seen"] for n in tx.scan("sdd_notifications")} == {"2026-09-22T12:00:00+00:00"}
    assert canonical(row)
