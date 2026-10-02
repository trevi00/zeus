"""S8 pilot 86: the M7 threshold approvals moved into research, VERBATIM through one named rule
(A/evidence/rebuild/s8/threshold-approvals-move/transcribe.py; DESIGN-s8 §6 V11).

M7 is read only as text through `git show e38aa722:...` and compared by AST (never imported: both packages are named
`codex_harness`). Behaviour is checked on the TARGET only, against literals; the recorded comparison is the
`research.threshold_approvals` golden.
"""
import ast
import importlib
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SOURCE = "e38aa722"
MODULE = "codex_harness.research.application.threshold_approvals"
M7_PATH = "src/codex_harness/application/threshold_approvals.py"
R_C0_IMPORTS = {"codex_harness.kernel.errors": ["ContractError", "require"],
                "codex_harness.kernel.ids": ["digest", "utcnow"],
                "codex_harness.kernel.numbers": ["finite_number"],
                "codex_harness.research.domain.threshold_proposals": ["REGISTRY"]}
M7_IMPORTS = {"codex_harness.domain.model": ["ContractError", "digest", "require", "utcnow"],
              "codex_harness.domain.threshold_proposals": ["REGISTRY"],
              "codex_harness.domain.threshold_replay": ["finite_number"]}
NAMES = [("BUCKET",), ("EVENTS",), ("STATES",), ("ENVIRONMENT",), ("REVISION",), ("MAX_TTL_SECONDS",), ("_time",),
         ("parse_applied_policy",), ("ThresholdApprovals",)]
NAME = "skill_match.FULL_BODY_MIN_SCORE"
T0 = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
REV_A, REV_C = "a" * 40, "c" * 40


def m7_text():
    return subprocess.run(["git", "-C", str(REPO), "show", f"{SOURCE}:{M7_PATH}"], check=True, capture_output=True, text=True).stdout


def target_text():
    return Path(importlib.import_module(MODULE).__file__).read_text()


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


def from_imports(src):
    return {n.module: [a.name for a in n.names] for n in ast.parse(src).body if isinstance(n, ast.ImportFrom)}


def test_every_statement_is_m7_s_by_ast_in_m7_order():
    ref, ours = statements(m7_text()), statements(target_text())
    assert list(ours) == list(ref) == NAMES
    for key in ref:
        assert ast.dump(ours[key]) == ast.dump(ref[key]), key
    klass = ours[("ThresholdApprovals",)]
    assert [n.name for n in klass.body if isinstance(n, ast.FunctionDef)] == ["__init__", "_event", "issue", "_check", "consume", "revoke", "inspect"]


def test_the_only_change_is_the_import_rule_r_c0_and_the_header():
    old, new = from_imports(m7_text()), from_imports(target_text())
    assert {k: v for k, v in old.items() if k.startswith("codex_harness.")} == M7_IMPORTS
    assert {k: v for k, v in new.items() if k.startswith("codex_harness.")} == R_C0_IMPORTS
    assert new["datetime"] == old["datetime"] == ["datetime", "timedelta", "timezone"]
    marker = "\n\nBUCKET = "
    assert m7_text().split(marker, 1)[1] == target_text().split(marker, 1)[1]
    doc = ast.get_docstring(ast.parse(target_text()))
    assert doc.startswith(ast.get_docstring(ast.parse(m7_text())))
    for line in ("Layer: application", "Context: research", "Contracts: INV-THRESHOLD-APPROVAL-001",
                 "Entry points: parse_applied_policy, ThresholdApprovals, BUCKET, EVENTS, STATES, ENVIRONMENT, REVISION, MAX_TTL_SECONDS"):
        assert line in doc.splitlines()


def test_imports_are_only_kernel_and_research_homes():
    tree = ast.parse(target_text())
    mods = sorted({n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module.startswith("codex_harness.")})
    assert mods == sorted(R_C0_IMPORTS)
    assert [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names] == ["re"]
    assert "codex_harness.domain" not in target_text().replace("codex_harness.research.domain", "")


def test_the_module_writes_only_its_two_buckets_and_reads_the_review_rows_by_literal():
    tree = ast.parse(target_text())
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)]
    puts = {ast.unparse(n.args[0]) for n in calls if n.func.attr == "put"}
    assert puts == {"BUCKET", "EVENTS"}
    gets = {ast.unparse(n.args[0]) for n in calls if n.func.attr == "get" and ast.unparse(n.func.value) == "tx"}
    assert gets == {"'threshold_review_requests'", "'threshold_proposals'", "BUCKET"}
    for word in ("subprocess", "psycopg", "open(", "os."):
        assert word not in target_text().split('"""', 2)[2], word


def test_research_owns_the_threshold_approval_buckets():
    from codex_harness.research import ports

    module = importlib.import_module(MODULE)
    assert ports.OWNED_BUCKETS[-2:] == ("threshold_approvals", "threshold_approval_events")
    assert {module.BUCKET, module.EVENTS} == set(ports.OWNED_BUCKETS[-2:])


def test_only_this_module_names_the_threshold_approval_buckets_in_the_target_source():
    src = REPO / "target" / "src" / "codex_harness"
    named = [path.relative_to(src).as_posix() for path in sorted(src.rglob("*.py"))
             if any(f"'{b}'" in path.read_text() or f'"{b}"' in path.read_text() for b in ("threshold_approvals", "threshold_approval_events"))]
    assert named == ["research/application/threshold_approvals.py", "research/ports.py"], named


def test_the_constants_are_m7_s():
    module = importlib.import_module(MODULE)
    assert (module.BUCKET, module.EVENTS, module.MAX_TTL_SECONDS) == ("threshold_approvals", "threshold_approval_events", 2592000)
    assert module.STATES == ("issued", "consumed", "revoked", "expired", "missing", "corrupt", "unreadable")
    assert module.ENVIRONMENT.fullmatch("eu-west.1_a") and not module.ENVIRONMENT.fullmatch("Staging")
    assert module.REVISION.fullmatch(REV_A) and not module.REVISION.fullmatch("A" * 40)


class Artifacts:
    def __init__(self, document):
        self.stored = document

    def document(self, reference):
        return self.stored


def assessed(accepted=True):
    from codex_harness.kernel.ids import digest
    from codex_harness.storage.adapters.memory_store import MemoryStore

    store = MemoryStore()
    proposal = {"name": NAME, "current": 3, "suggested": 4, "reference_accepted": True, "policy_revision": REV_A,
                "corpus_hash": "corpus", "registry_hash": "registry"}
    row = {"id": "row-1", "proposal": proposal, "evidence_ref": "sha256:" + "e" * 64}
    reviews = [{"actor": actor, "decision_id": f"d-{actor}", "generation": 1, "result": {"accepted": accepted}}
               for actor in ("lead:improvement", "conductor")]
    with store.transaction() as tx:
        tx.put("threshold_proposals", "row-1", row)
        tx.put("threshold_review_requests", "req-1", {"id": "req-1", "status": "assessed", "row_id": "row-1", "reviews": reviews,
                                                     "binding": digest(row)})
    return store, Artifacts({"proposals": [proposal]})


def applied(**over):
    return {"previous_revision": REV_A, "previous_values": {NAME: 3}, "revision": REV_C, "values": {NAME: 4}, "environment": "staging", **over}


def approvals(accepted=True):
    from codex_harness.research.application.threshold_approvals import ThresholdApprovals

    store, artifacts = assessed(accepted)
    return store, ThresholdApprovals(store, artifacts)


def rows(store, bucket):
    with store.transaction() as tx:
        return tx.scan(bucket)


def test_an_unaccepted_review_is_refused_and_writes_nothing():
    from codex_harness.kernel.errors import ContractError

    store, service = approvals(accepted=False)
    before = dict(store.data)
    with pytest.raises(ContractError, match="Both independent assessments must have accepted"):
        service.issue("req-1", actor="conductor", environment="staging", ttl_seconds=60, now=T0)
    assert store.data == before


def test_a_repeated_identical_issue_is_the_original_approval():
    store, service = approvals()
    first = service.issue("req-1", actor="conductor", environment="staging", ttl_seconds=3600, now=T0)
    assert first["status"] == "issued" and first["expires_at"] == (T0 + timedelta(hours=1)).isoformat()
    again = service.issue("req-1", actor="conductor", environment="staging", ttl_seconds=60, now=T0 + timedelta(days=1))
    assert again == first
    assert len(rows(store, "threshold_approvals")) == 1 and [e["kind"] for e in rows(store, "threshold_approval_events")] == ["issued"]


def test_a_refused_change_is_a_committed_event_and_the_approval_stays_issued():
    from codex_harness.kernel.errors import ContractError

    store, service = approvals()
    approval = service.issue("req-1", actor="conductor", environment="staging", ttl_seconds=3600, now=T0)
    stored = rows(store, "threshold_approvals")
    with pytest.raises(ContractError, match="applied value differs from the approved proposed value"):
        service.consume(approval["id"], applied(values={NAME: 999}), now=T0 + timedelta(minutes=1))
    assert rows(store, "threshold_approvals") == stored
    kinds = sorted(e["kind"] for e in rows(store, "threshold_approval_events"))
    assert kinds == ["issued", "refused"]
    with pytest.raises(ContractError, match="approval expired"):
        service.consume(approval["id"], applied(), now=T0 + timedelta(hours=1))
    assert service.inspect(approval["id"], now=T0 + timedelta(minutes=1))["state"] == "issued"


def test_one_certification_then_every_later_delivery_is_refused_as_consumed():
    from codex_harness.kernel.errors import ContractError

    store, service = approvals()
    approval = service.issue("req-1", actor="conductor", environment="staging", ttl_seconds=3600, now=T0)
    consumed = service.consume(approval["id"], applied(), now=T0 + timedelta(minutes=2))
    assert consumed["status"] == "consumed" and consumed["application"] == {
        "revision": REV_C, "generation": 1, "environment": "staging", "at": (T0 + timedelta(minutes=2)).isoformat()}
    for index in range(1, 4):
        with pytest.raises(ContractError, match="approval is consumed"):
            service.consume(approval["id"], applied(revision=f"{index:040x}"), now=T0 + timedelta(minutes=3))
    kinds = [e["kind"] for e in sorted(rows(store, "threshold_approval_events"), key=lambda e: e["sequence"])]
    assert kinds == ["issued", "consumed", "refused", "refused", "refused"]
    with pytest.raises(ContractError, match="Only an issued approval can be revoked"):
        service.revoke(approval["id"], actor="conductor", reason="too late")


def test_a_malformed_applied_policy_is_refused_before_any_transaction():
    from codex_harness.kernel.errors import ContractError

    store, service = approvals()
    approval = service.issue("req-1", actor="conductor", environment="staging", ttl_seconds=3600, now=T0)
    before = dict(store.data)
    for bad in (None, {"revision": REV_C}, applied(revision="HEAD"), applied(values={NAME: float("nan")}), applied(values={NAME: True}),
                applied(values={"unknown.NAME": 4}), applied(environment="Staging")):
        with pytest.raises(ContractError):
            service.consume(approval["id"], bad, now=T0)
    assert store.data == before


def test_revocation_is_idempotent_and_states_are_named():
    from codex_harness.kernel.errors import ContractError
    from codex_harness.research.application.threshold_approvals import ThresholdApprovals

    store, service = approvals()
    approval = service.issue("req-1", actor="conductor", environment="staging", ttl_seconds=60, now=T0)
    with pytest.raises(ContractError, match="Only a reviewer revokes an approval"):
        service.revoke(approval["id"], actor="worker:implementation", reason="no")
    revoked = service.revoke(approval["id"], actor="lead:improvement", reason="a later rejection")
    assert revoked["status"] == "revoked" and service.revoke(approval["id"], actor="conductor", reason="again") == revoked
    assert service.inspect(approval["id"])["state"] == "revoked" and service.inspect("nope")["state"] == "missing"
    later = service.issue("req-1", actor="conductor", environment="prod", ttl_seconds=60, now=T0)
    assert service.inspect(later["id"], now=T0 + timedelta(seconds=61))["state"] == "expired"
    with store.transaction() as tx:
        tx.put("threshold_approvals", later["id"], {**tx.get("threshold_approvals", later["id"]), "proposed": float("nan")})
    assert service.inspect(later["id"], now=T0)["state"] == "corrupt"

    class Down:
        def transaction(self):
            raise OSError("closed")

    assert ThresholdApprovals(Down(), Artifacts({})).inspect("any") == {"id": "any", "state": "unreadable", "reason": "OSError"}
