"""S8 pilot 85: the M7 completion authority moved into evidence, VERBATIM through one named rule
(A/evidence/rebuild/s8/completion-move/transcribe.py; DESIGN-s8 §6 V11).

M7 is read only as text through `git show e38aa722:...` and compared by AST (never imported: both packages are named
`codex_harness`). Behaviour is checked on the TARGET only, against literals; the recorded comparison is the
`evidence.completion` golden.
"""
import ast
import importlib
import subprocess
from pathlib import Path

import pytest
from _layout import REPO, TARGET

SOURCE = "e38aa722"
MODULE = "codex_harness.evidence.application.completion"
M7_PATH = "src/codex_harness/application/completion.py"
R_C0_IMPORTS = {"codex_harness.evidence.domain.completion": ["KEYS", "latest", "parse_verdict"],
                "codex_harness.kernel.errors": ["ContractError", "require"],
                "codex_harness.kernel.ids": ["digest", "utcnow"]}
M7_IMPORTS = {"codex_harness.domain.completion": ["KEYS", "latest", "parse_verdict"],
              "codex_harness.domain.model": ["ContractError", "digest", "require", "utcnow"]}
NAMES = [("BUCKET",), ("REJECTIONS",), ("RECORD_ONLY",), ("STATES",), ("EVALUATION_KIND",), ("_excerpt",), ("_task_of",),
         ("CompletionAuthority",)]
SPEC = "a" * 40
EVALUATION = "sha256:" + "b" * 64
EXECUTION = "sha256:" + "c" * 64


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
    klass = ours[("CompletionAuthority",)]
    assert [n.name for n in klass.body if isinstance(n, ast.FunctionDef)] == ["__init__", "record", "inspect", "_provenance", "require_authority"]


def test_the_only_change_is_the_import_rule_r_c0_and_the_header():
    old, new = from_imports(m7_text()), from_imports(target_text())
    assert {k: v for k, v in old.items() if k.startswith("codex_harness.")} == M7_IMPORTS
    assert {k: v for k, v in new.items() if k.startswith("codex_harness.")} == R_C0_IMPORTS
    assert new["datetime"] == old["datetime"] == ["datetime", "timezone"]
    marker = "\n\nBUCKET = "
    assert m7_text().split(marker, 1)[1] == target_text().split(marker, 1)[1]
    doc = ast.get_docstring(ast.parse(target_text()))
    assert doc.startswith(ast.get_docstring(ast.parse(m7_text())))
    for line in ("Layer: application", "Context: evidence", "Contracts: INV-COMPLETION-001",
                 "Entry points: CompletionAuthority, BUCKET, REJECTIONS, RECORD_ONLY, STATES, EVALUATION_KIND"):
        assert line in doc.splitlines()


def test_imports_are_only_kernel_and_evidence_homes():
    tree = ast.parse(target_text())
    mods = sorted({n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module.startswith("codex_harness.")})
    assert mods == sorted(R_C0_IMPORTS)
    assert [n for n in ast.walk(tree) if isinstance(n, ast.Import)] == []
    assert "codex_harness.domain" not in target_text().replace("codex_harness.evidence.domain", "")


def test_the_module_writes_only_its_two_buckets_and_reads_tasks_by_literal():
    tree = ast.parse(target_text())
    puts = [ast.unparse(n.args[0]) for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr == "put"]
    assert sorted(puts) == ["BUCKET", "REJECTIONS"]
    gets = sorted(ast.unparse(n.args[0]) for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                  and n.func.attr == "get" and ast.unparse(n.func.value) == "tx")
    assert gets == ["'tasks'", "'tasks'", "'tasks'", "BUCKET", "REJECTIONS"]
    for word in ("subprocess", "psycopg", "open(", "os."):
        assert word not in target_text().split('"""', 2)[2], word


def test_evidence_owns_the_completion_buckets():
    from codex_harness.evidence import ports

    module = importlib.import_module(MODULE)
    assert ports.OWNED_BUCKETS[-2:] == ("completion_verdicts", "completion_rejections")
    assert {module.BUCKET, module.REJECTIONS} == set(ports.OWNED_BUCKETS[-2:])


def test_only_this_module_names_the_completion_buckets_in_the_target_source():
    src = TARGET / "src" / "codex_harness"
    named = [path.relative_to(src).as_posix() for path in sorted(src.rglob("*.py"))
             if any(f"'{b}'" in path.read_text() or f'"{b}"' in path.read_text() for b in ("completion_verdicts", "completion_rejections"))]
    assert named == ["evidence/application/completion.py", "evidence/ports.py"], named


def test_the_constants_are_m7_s():
    module = importlib.import_module(MODULE)
    assert (module.BUCKET, module.REJECTIONS, module.RECORD_ONLY, module.EVALUATION_KIND) == (
        "completion_verdicts", "completion_rejections", ("sequence", "recorded_at"), "completion-evaluation")
    assert module.STATES == ("unreadable", "no_ledger", "corrupt", "partially_corrupt", "rejected_only", "not_evaluated", "stale",
                             "not_approved", "incomplete", "not_succeeded", "receipt_unbound", "artifact_missing", "artifact_unbound",
                             "reviewer_unbound", "scenario_mismatch", "verdict_mismatch", "authoritative")


def authority(artifacts=None, org=None):
    from codex_harness.evidence.application.completion import CompletionAuthority
    from codex_harness.storage.adapters.memory_store import MemoryStore

    store = MemoryStore()
    return store, CompletionAuthority(store, artifacts=artifacts, org=org)


def verdict(**over):
    target = {"task_id": "task-1", "generation": 1, "attempt": 1}
    base = {"schema_version": 1, "event": "completion.verdict", "verdict": "approved", "target": target, "spec_revision": SPEC,
            "evaluation_artifact": EVALUATION, "runner_receipt": {"id": EXECUTION, "digest": EXECUTION[7:], **target},
            "reviewer": {"actor": "lead:research", "kind": "model"},
            "scenarios": {"expected": ["login"], "passed": ["login"], "excluded": []}, "observed_at": "2026-09-10T00:00:00+00:00"}
    return {**base, **over}


def rows(store, bucket):
    with store.transaction() as tx:
        return tx.scan(bucket)


def put_task(store, **fields):
    with store.transaction() as tx:
        tx.put("tasks", "task-1", {"id": "task-1", "generation": 1, "attempt": 1, "status": "running", **fields})


def test_a_verdict_for_an_unknown_task_is_refused_and_writes_nothing():
    from codex_harness.kernel.errors import ContractError

    store, completion = authority()
    with pytest.raises(ContractError, match="Completion verdict for an unknown task"):
        completion.record(verdict())
    assert store.data == {}


def test_a_verdict_bound_to_another_execution_is_refused_and_writes_nothing():
    from codex_harness.kernel.errors import ContractError

    store, completion = authority()
    put_task(store, generation=2)
    before = dict(store.data)
    with pytest.raises(ContractError, match="different execution than the current one"):
        completion.record(verdict())
    assert store.data == before


def test_a_repeated_identical_verdict_is_the_original_row_and_a_changed_one_is_refused():
    from codex_harness.kernel.errors import ContractError

    store, completion = authority()
    put_task(store)
    first = completion.record(verdict())
    assert first["changed"] is True and first["sequence"] == 1
    again = completion.record(verdict(observed_at="2026-09-10T00:00:30+00:00"))
    assert again == {"id": first["id"], "changed": False, "sequence": 1}
    assert len(rows(store, "completion_verdicts")) == 1
    with store.transaction() as tx:
        row = tx.get("completion_verdicts", first["id"])
        tx.put("completion_verdicts", first["id"], {**row, "verdict": "iterate"})
    with pytest.raises(ContractError, match="identity reused with different content"):
        completion.record(verdict())


def test_a_malformed_record_is_kept_as_one_notice_however_often_it_is_replayed():
    from codex_harness.kernel.errors import ContractError

    store, completion = authority()
    bad = verdict(schema_version=2)
    for _ in range(3):
        with pytest.raises(ContractError, match="Completion verdict rejected: schema_version must be 1"):
            completion.record(bad)
    notices = rows(store, "completion_rejections")
    assert len(notices) == 1 and notices[0]["task_id"] == "task-1" and notices[0]["reason"].startswith("Completion verdict rejected")
    assert rows(store, "completion_verdicts") == []
    with pytest.raises(ContractError):
        completion.record(None)
    assert sorted(str(n["task_id"]) for n in rows(store, "completion_rejections")) == ["None", "task-1"]


def test_the_excerpt_of_a_notice_is_bounded():
    from codex_harness.kernel.errors import ContractError

    store, completion = authority()
    with pytest.raises(ContractError):
        completion.record(verdict(extra="x" * 3000))
    (notice,) = rows(store, "completion_rejections")
    assert len(notice["excerpt"]) == 2001 and notice["excerpt"].endswith("…")


def test_a_worker_success_alone_is_not_authority_and_require_authority_names_the_state():
    from codex_harness.kernel.errors import ContractError

    store, completion = authority()
    put_task(store, status="succeeded")
    report = completion.inspect("task-1", spec_revision=SPEC, evaluation_artifact=EVALUATION)
    assert (report["state"], report["authority"], report["verdicts"]) == ("not_evaluated", False, 0)
    with pytest.raises(ContractError, match="No completion authority: not_evaluated"):
        completion.require_authority("task-1", spec_revision=SPEC, evaluation_artifact=EVALUATION)
    assert completion.inspect("nobody", spec_revision=SPEC, evaluation_artifact=EVALUATION)["state"] == "no_ledger"
    with pytest.raises(ContractError, match="Task identity required"):
        completion.inspect("", spec_revision=SPEC, evaluation_artifact=EVALUATION)


def test_an_approved_verdict_without_an_artifact_store_is_artifact_missing_after_the_receipt_check():
    store, completion = authority()
    put_task(store, status="succeeded", result={"execution_ref": EXECUTION})
    completion.record(verdict())
    report = completion.inspect("task-1", spec_revision=SPEC, evaluation_artifact=EVALUATION)
    assert (report["state"], report["authority"], report["latest"]["sequence"]) == ("artifact_missing", False, 1)
    assert completion.inspect("task-1", spec_revision=OTHER_SPEC, evaluation_artifact=EVALUATION)["state"] == "stale"
    put_task(store, status="succeeded", result={"execution_ref": "sha256:" + "9" * 64})
    assert completion.inspect("task-1", spec_revision=SPEC, evaluation_artifact=EVALUATION)["state"] == "receipt_unbound"


OTHER_SPEC = "d" * 40


def test_a_store_that_fails_is_unreadable_never_no_evaluation():
    from codex_harness.evidence.application.completion import CompletionAuthority

    class Down:
        def transaction(self):
            raise OSError("z" * 500)

    report = CompletionAuthority(Down()).inspect("task-1", spec_revision=SPEC, evaluation_artifact=EVALUATION)
    assert (report["state"], report["authority"]) == ("unreadable", False)
    assert report["reason"] == "OSError: " + "z" * 200


def test_a_stored_row_that_fails_the_closed_schema_is_corrupt():
    store, completion = authority()
    put_task(store)
    row_id = completion.record(verdict())["id"]
    with store.transaction() as tx:
        tx.put("completion_verdicts", row_id, {**tx.get("completion_verdicts", row_id), "verdict": "false"})
    report = completion.inspect("task-1", spec_revision=SPEC, evaluation_artifact=EVALUATION)
    assert (report["state"], report["authority"], report["corrupt"]) == ("corrupt", False, 1)
