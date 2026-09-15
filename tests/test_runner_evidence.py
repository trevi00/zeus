"""PR #73 independent review (docs/zeus/reviews/claude-work-018): the four counterexamples.

Codex drove the real runner - a real isolated PostgreSQL, a real Redis namespace, a real Git
repository and the protocol child - and found four places where "the evidence was preserved" was
decided by something other than the evidence.

Each counterexample appears here demanding the safe result instead:

* a second run with the same label must not write through the first run's evidence,
* an artifact that exists on disk must not be deleted because the bookkeeping never reached it,
* a diff command that failed must not be exported as a verified empty diff,
* and a run whose required evidence is gone must not exit as a success.

Nothing here calls a provider: the runner is driven in `--fixture` mode against the protocol child.
"""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from codex_harness.adapters.scratch import Scratch, file_digest

ROOT = Path(__file__).resolve().parents[1]


def runner():
    """The script, loaded as a module, so the review drives exactly what an operator runs."""
    spec = importlib.util.spec_from_file_location("evidence_runner", ROOT / "scripts/claude_real_call.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fixture_args(database_url: str, redis_url: str | None):
    return SimpleNamespace(label="review", fixture=True, model="claude-stub-normal", budget=1,
                          timeout=60, database_url=database_url, redis_url=redis_url,
                          allow_interop=False, executable=None, compose=False)


@pytest.fixture
def live():
    """A real database and cache, or a skip: these checks drive the runner, not a stand-in for it.

    The runner makes its own isolated schema and Redis namespace inside whatever this points at,
    exactly as it does for an operator, so the same gate the rest of the integration suite uses
    decides whether they run here.
    """
    if os.environ.get("HARNESS_INTEGRATION") != "1":
        pytest.skip("Integration environment required")
    from codex_harness.bootstrap import database_url, redis_url

    return fixture_args(database_url(), redis_url())


def only_receipt(out: Path) -> dict:
    """The receipt this run wrote, found rather than guessed: its name carries the run id."""
    [path] = sorted(out.glob("*-receipt.json"))
    return json.loads(path.read_text(encoding="utf-8"))


def receipts(out: Path) -> list:
    return [json.loads(path.read_text(encoding="utf-8")) for path in sorted(out.glob("*-receipt.json"))]


# ---- R1: a second run writes beside the first, never through it ----------------------------------

def test_r1_a_repeated_label_cannot_touch_the_first_runs_evidence(tmp_path):
    """The first receipt keeps quoting digests, so the bytes behind them have to stay put."""
    module = runner()
    scratch = Scratch.create("zeus-review-073-")
    try:
        first = module.preserve_evidence(
            scratch, {"preservable": {"diff": module.command_record(
                {"argv": ["git", "diff"], "exit_code": 0, "stdout": "first", "stderr": "", "timed_out": False})}},
            tmp_path, "same", "run-one")
        second = module.preserve_evidence(
            scratch, {"preservable": {"diff": module.command_record(
                {"argv": ["git", "diff"], "exit_code": 0, "stdout": "second", "stderr": "", "timed_out": False})}},
            tmp_path, "same", "run-two")

        assert first["complete"] and second["complete"]
        assert first["kept"][0]["path"] != second["kept"][0]["path"], "each run keeps its own copy"
        original = first["kept"][0]
        assert file_digest(Path(original["path"])) == original["sha256"], \
            "the second run wrote through the first run's evidence"
        assert Path(original["path"]).read_text(encoding="utf-8") == "first"
    finally:
        scratch.remove()


def test_r1_evidence_is_never_written_through_even_by_the_same_run(tmp_path):
    """Exclusive creation: a name that already exists is a failure, not a silent replacement."""
    scratch = Scratch.create("zeus-review-073-")
    try:
        entry = {"name": "candidate.diff", "text": "first"}
        kept = scratch.preserve(tmp_path / "evidence", [entry])
        again = scratch.preserve(tmp_path / "evidence", [{"name": "candidate.diff", "text": "second"}])
        assert kept["complete"] is True and again["complete"] is False
        assert again["failures"][0]["error"] == "FileExistsError"
        assert (tmp_path / "evidence" / "candidate.diff").read_text(encoding="utf-8") == "first"
    finally:
        scratch.remove()


def test_r1_the_receipt_and_its_evidence_carry_the_same_run_id(tmp_path, live, monkeypatch):
    """Bound together, so a reader can tell which evidence belongs to which receipt."""
    module = runner()
    module.call(live, tmp_path)
    module.call(live, tmp_path)

    written = receipts(tmp_path)
    assert len(written) == 2, "a repeated label writes a second receipt rather than replacing one"
    identifiers = {receipt["run_id"] for receipt in written}
    assert len(identifiers) == 2
    for receipt in written:
        assert receipt["preserved"]["run_id"] == receipt["run_id"]
        assert receipt["run_id"] in receipt["preserved"]["destination"]
        for entry in receipt["preserved"]["kept"]:
            assert Path(entry["path"]).exists()
            assert file_digest(Path(entry["path"])) == entry["sha256"]


# ---- R2: what is on disk decides, not what the bookkeeping managed to record ---------------------

def test_r2_an_artifact_on_disk_is_never_deleted_because_the_list_was_empty(tmp_path, live, monkeypatch):
    """Codex's counterexample: the execution really happens, then collection throws.

    The run's own list of evidence never gets written, and the artifact the receipt would point at
    is real and on disk. It must survive - either preserved, or by the scratch being kept.
    """
    from codex_harness.adapters.executor import Executor

    module = runner()
    original = Executor.execute_one
    seen = {}

    def fail_after_the_work(self, *args, **kwargs):
        row = original(self, *args, **kwargs)
        assert row["status"] == "succeeded"
        artifact = self.artifacts.root / (row["result"]["execution_ref"][7:] + ".txt")
        assert artifact.is_file(), "the counterexample must reach a real artifact"
        seen["artifact"] = artifact
        raise RuntimeError("review injected post-execution collection failure")

    monkeypatch.setattr(Executor, "execute_one", fail_after_the_work)
    code = module.call(live, tmp_path)
    receipt = only_receipt(tmp_path)

    assert "artifact" in seen
    assert seen["artifact"].exists() or receipt["preserved"]["kept"], \
        "the artifact was deleted while preservation reported nothing to keep"
    assert receipt["preserved"]["kept"], "the sweep finds what the bookkeeping missed"
    assert any(entry["name"].startswith("artifacts/") for entry in receipt["preserved"]["kept"])
    assert receipt["workdir_removed"] is False, "a run that ended unplanned keeps its scratch"
    assert code != 0
    Scratch(Path(receipt["workdir_cleanup"]["root"])).remove()


def test_r2_no_evidence_produced_is_a_different_answer_from_no_list(tmp_path):
    """An empty scratch really is empty, and that determination is allowed to be complete."""
    module = runner()
    scratch = Scratch.create("zeus-review-073-")
    try:
        report = module.preserve_evidence(scratch, {}, tmp_path, "empty", "run-none")
        assert report["complete"] is True and report["kept"] == []
        assert "no execution artifact" in report["note"]
    finally:
        scratch.remove()


def test_r2_an_artifact_in_the_scratch_that_is_not_kept_is_incomplete(tmp_path, monkeypatch):
    """If the sweep sees evidence and none of it survives, the run does not get to say complete."""
    module = runner()
    scratch = Scratch.create("zeus-review-073-")
    try:
        artifact = scratch.root / "artifacts" / "execution.txt"
        artifact.parent.mkdir(parents=True)
        artifact.write_text('{"process": {"exit_code": 0}}', encoding="utf-8")

        def refuse(self, data):
            raise OSError("the destination refused")

        monkeypatch.setattr(Path, "write_bytes", refuse)
        monkeypatch.setattr(os, "open", lambda *a, **kw: (_ for _ in ()).throw(OSError("refused")))
        report = module.preserve_evidence(scratch, {}, tmp_path, "kept-none", "run-x")
        assert report["complete"] is False
        assert report["kept"] == []
    finally:
        monkeypatch.undo()
        scratch.remove()


# ---- R3: a command that failed did not produce evidence ------------------------------------------

def test_r3_a_failed_diff_command_is_not_a_verified_empty_diff(tmp_path, live, monkeypatch):
    module = runner()
    original = module.run
    seen = []

    def fail_diff(argv, **kwargs):
        if argv[:2] == ["git", "diff"] and len(argv) == 4:
            seen.append(argv)
            return {"argv": argv, "exit_code": 128, "stdout": "", "stderr": "review diff failed",
                    "timed_out": False}
        return original(argv, **kwargs)

    monkeypatch.setattr(module, "run", fail_diff)
    code = module.call(live, tmp_path)
    receipt = only_receipt(tmp_path)

    assert seen, "the counterexample must reach the diff command"
    assert receipt["preserved"]["complete"] is False, "a failed diff exported as verified evidence"
    [failure] = receipt["preserved"]["required_failures"]
    assert failure["evidence"] == "candidate.diff" and failure["exit_code"] == 128
    names = {entry["name"] for entry in receipt["preserved"]["kept"]}
    assert "candidate.diff" not in names, "no file stands in for the one that was never produced"
    assert "candidate.diff.failed.json" in names, "and the failure itself is kept"
    assert code != 0
    Scratch(Path(receipt["workdir_cleanup"]["root"])).remove()


def test_r3_a_diff_that_really_is_empty_is_still_complete(tmp_path, live, monkeypatch):
    """The contrast that gives the line above its meaning: exit 0 with no output is evidence."""
    module = runner()
    original = module.run

    def empty_diff(argv, **kwargs):
        if argv[:2] == ["git", "diff"] and len(argv) == 4:
            return {"argv": argv, "exit_code": 0, "stdout": "", "stderr": "", "timed_out": False}
        return original(argv, **kwargs)

    monkeypatch.setattr(module, "run", empty_diff)
    module.call(live, tmp_path)
    receipt = only_receipt(tmp_path)

    assert receipt["preserved"]["required_failures"] == []
    names = {entry["name"] for entry in receipt["preserved"]["kept"]}
    assert "candidate.diff" in names and "candidate.diff.failed.json" not in names
    assert receipt["preserved"]["complete"] is True


def test_r3_a_timed_out_evidence_command_is_not_complete(tmp_path):
    """Timed out is a third answer, and it is not success and not a plain non-zero exit."""
    module = runner()
    scratch = Scratch.create("zeus-review-073-")
    try:
        timed_out = module.command_record({"argv": ["git", "diff"], "exit_code": None, "stdout": "",
                                           "stderr": "", "timed_out": True})
        report = module.preserve_evidence(scratch, {"preservable": {"diff": timed_out}},
                                          tmp_path, "slow", "run-slow")
        assert report["complete"] is False
        assert report["required_failures"][0]["timed_out"] is True
    finally:
        scratch.remove()


# ---- R4: a run that cannot show its evidence is not a run that passed ----------------------------

def test_r4_a_run_that_lost_its_required_evidence_does_not_pass(tmp_path, live, monkeypatch):
    module = runner()
    seen = {}

    def refuse_preservation(self, destination, entries):
        seen["root"] = self.root
        return {"complete": False, "kept": [], "failures": [{"name": "all", "error": "OSError"}],
                "destination": str(destination)}

    monkeypatch.setattr(Scratch, "preserve", refuse_preservation)
    code = module.call(live, tmp_path)
    receipt = only_receipt(tmp_path)

    assert receipt["preserved"]["complete"] is False
    assert receipt["workdir_removed"] is False, "the scratch holds the only copy, so it is kept"
    assert receipt["passed"] is False and code != 0, "an unattended caller must not read this as success"
    assert receipt["recovery"]["scratch"] and receipt["recovery"]["note"]
    assert seen["root"].name.startswith("zeus-claude-call-")
    monkeypatch.undo()
    Scratch(seen["root"]).remove()


def test_r4_the_task_and_the_evidence_are_recorded_as_two_claims(tmp_path, live, monkeypatch):
    """The task may well have succeeded. Saying so is a separate claim from being able to show it."""
    module = runner()
    monkeypatch.setattr(Scratch, "preserve",
                        lambda self, destination, entries: {"complete": False, "kept": [],
                                                            "failures": [{"name": "all", "error": "OSError"}],
                                                            "destination": str(destination)})
    module.call(live, tmp_path)
    receipt = only_receipt(tmp_path)

    assert receipt["task_succeeded"] is True, "the fixture task itself did finish"
    assert receipt["evidence_complete"] is False
    assert receipt["passed"] is False, "and the run as a whole did not pass"
    monkeypatch.undo()
    Scratch(Path(receipt["workdir_cleanup"]["root"])).remove()


def test_r4_a_receipt_that_cannot_be_written_still_reports_and_fails(tmp_path, live, monkeypatch):
    """The output directory refusing must not make the run vanish quietly."""
    module = runner()
    real_write = Path.write_text

    def refuse_receipt(self, *args, **kwargs):
        if self.name.endswith("-receipt.json"):
            raise OSError("the output directory refused")
        return real_write(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", refuse_receipt)
    code = module.call(live, tmp_path)
    monkeypatch.undo()

    assert code == 1, "a run whose receipt could not be written is not a success"
    assert not list(tmp_path.glob("*-receipt.json"))


# ---- second review: an empty selection is not an empty scratch -----------------------------------

@pytest.mark.parametrize("case", ["capped", "missing_reference"])
def test_a_an_empty_selection_is_not_a_determination_that_nothing_was_produced(tmp_path, monkeypatch, case):
    """Both of these select no file, and neither means the scratch had nothing worth keeping.

    A sweep that hit its cap left evidence behind. A receipt naming an artifact that is not there
    has lost the thing it points at. Returning early on "no entries" answered both with complete.
    """
    module = runner()
    scratch = Scratch.create("zeus-claude-call-")
    try:
        receipt = {}
        if case == "capped":
            artifact = scratch.root / "artifacts" / "execution.txt"
            artifact.parent.mkdir()
            artifact.write_bytes(b"ab")
            monkeypatch.setattr(module, "SWEEP_BYTE_CAP", 1)
        else:
            receipt["provider_receipt"] = {"execution_ref": "sha256:" + "a" * 64}

        report = module.preserve_evidence(scratch, receipt, tmp_path, "review", case)

        assert report["complete"] is False
        assert report["kept"] == []
        assert report["failures"], "the reason is named rather than left to be inferred"
    finally:
        scratch.remove()


def test_a_a_scratch_that_really_is_empty_is_still_accepted(tmp_path):
    """The contrast: no cap was hit, nothing was listed, nothing is referenced."""
    module = runner()
    scratch = Scratch.create("zeus-claude-call-")
    try:
        report = module.preserve_evidence(scratch, {}, tmp_path, "review", "run-empty")
        assert report["complete"] is True and report["kept"] == []
        assert report["swept"]["seen"] == 0 and report["swept"]["capped"] is False
    finally:
        scratch.remove()


def test_a_an_evidence_directory_that_cannot_be_listed_is_not_an_empty_one(tmp_path, monkeypatch):
    """Not being able to look is a different answer from there being nothing to see."""
    module = runner()
    scratch = Scratch.create("zeus-claude-call-")
    try:
        (scratch.root / "artifacts").mkdir()

        def refuse(self, pattern):
            raise OSError("the directory refused to be listed")

        monkeypatch.setattr(Path, "rglob", refuse)
        report = module.preserve_evidence(scratch, {}, tmp_path, "review", "run-blind")
        monkeypatch.undo()

        assert report["complete"] is False
        assert report["swept"]["errors"], "the failure to enumerate is recorded"
    finally:
        scratch.remove()


# ---- second review: the destination refusing must not skip the report ----------------------------

def test_b_a_destination_that_cannot_be_created_is_reported_and_the_scratch_is_kept(tmp_path, live):
    """Codex's counterexample: a file occupies the evidence directory's name.

    The failure used to escape past the receipt, so the scratch survived with nothing telling anyone
    where it was.
    """
    module = runner()
    (tmp_path / "review-evidence").write_text("an existing file blocks directory creation",
                                              encoding="utf-8")
    code = module.call(live, tmp_path)
    receipt = only_receipt(tmp_path)

    assert code != 0
    assert receipt["evidence_complete"] is False
    assert receipt["recovery"]["scratch"], "the report says where the only copy is"
    assert receipt["workdir_removed"] is False
    Scratch(Path(receipt["workdir_cleanup"]["root"])).remove()


def test_b_the_call_ledger_is_settled_even_when_preservation_throws(tmp_path, live, monkeypatch):
    """A reserved slot that is never settled keeps counting, whatever else went wrong."""
    module = runner()
    settled = {}

    def refuse(self, destination, entries):
        raise OSError("preservation itself failed")

    monkeypatch.setattr(Scratch, "preserve", refuse)
    monkeypatch.setattr(module.CallBudget, "settle",
                        lambda self, slot_id, **kwargs: settled.setdefault("slot", slot_id))
    code = module.call(live, tmp_path)
    receipt = only_receipt(tmp_path)
    monkeypatch.undo()

    assert receipt["preserved"]["complete"] is False
    assert receipt["preserved"]["failures"][0]["name"] == "preservation"
    assert code != 0 and receipt["recovery"]["scratch"]
    Scratch(Path(receipt["workdir_cleanup"]["root"])).remove()


# ---- second review: an unplanned ending is a failed run ------------------------------------------

def test_c_a_late_collection_error_does_not_exit_as_a_success(tmp_path, live, monkeypatch):
    """The task finished and the copies were kept. The run still ended somewhere it did not plan."""
    module = runner()
    original = module.execute
    seen = {}

    def fail_at_the_boundary(*args, **kwargs):
        seen["root"] = args[2]
        original(*args, **kwargs)
        assert args[1]["execution"]["status"] == "succeeded"
        raise RuntimeError("review late collection boundary failure")

    monkeypatch.setattr(module, "execute", fail_at_the_boundary)
    code = module.call(live, tmp_path)
    receipt = only_receipt(tmp_path)

    assert receipt["error"] and receipt["workdir_removed"] is False
    assert receipt["task_succeeded"] is True, "what the task did is still recorded as it was"
    assert receipt["runner_complete"] is False, "but the run cannot account for itself"
    assert receipt["passed"] is False and code != 0
    assert receipt["recovery"]["error"]["type"] == "RuntimeError"
    Scratch(seen["root"]).remove()


def test_c_a_clean_run_still_passes(tmp_path, live):
    """The contrast that keeps the line above from being a way of never passing."""
    module = runner()
    code = module.call(live, tmp_path)
    receipt = only_receipt(tmp_path)

    assert receipt.get("error") is None
    assert receipt["runner_complete"] is True and receipt["passed"] is True and code == 0
    assert receipt["workdir_removed"] is True
