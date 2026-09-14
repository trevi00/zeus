"""PR #72 first independent review (docs/zeus/reviews/claude-work-015): the four counterexamples.

Codex drove real temporary processes at this transport and found four places where a receipt said
more than it knew: a surviving grandchild read as a terminated tree, a non-zero exit read as a
finished task, another session's result read as this attempt's answer, and a per-host call ceiling
that a different `--label` reset to zero.

Each counterexample appears here demanding the safe result instead. The children are fault
injectors; nothing in this file is evidence about a model.
"""
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest
from test_claude_cli_process import CHILD, RUNTIME, SCHEMA, execute, observation, transport

from codex_harness.adapters.call_budget import CallBudget, host_identity
from codex_harness.adapters.claude_cli import ClaudeCodeRuntime, _model_agreement, _session_binding
from codex_harness.adapters.process_tree import ProcessTree
from codex_harness.domain.invocation import classify_result
from codex_harness.domain.model import ContractError


def still_ticking(marker: Path, seconds: float = 1.5) -> bool:
    """Whether something is still writing to the file, judged by watching it rather than asking."""
    if not marker.exists():
        return False
    before = marker.read_bytes()
    time.sleep(seconds)
    return marker.read_bytes() != before


# ---- R1: a parent that exited proves nothing about what it left behind ---------------------------

def test_r1_a_grandchild_that_outlives_its_parent_is_killed_and_not_called_confirmed(tmp_path):
    """Codex's counterexample: the child reports success, exits 0, and leaves a detached grandchild.

    The parent's exit used to be the whole proof, so the tree read as terminated while the
    grandchild ran on. The boundary now owns the tree from spawn, so the grandchild goes with it.
    """
    result, _, _, runtime = execute("orphan", tmp_path, timeout=30)
    marker = Path(observation(tmp_path)["orphan_marker"])
    assert result["process"]["parent"]["confirmed"] and result["process"]["parent"]["exit_code"] == 0
    assert result["process"]["tree"]["confirmed"] is True
    if os.name == "nt":
        assert result["process"]["tree"]["active_processes"] == 0
        assert result["process"]["boundary"]["kind"] == "job_object"
        assert result["process"]["boundary"]["created_suspended"] is True
    else:
        assert result["process"]["tree"]["group_empty"] is True
    assert result["process"]["confirmed"] is True
    assert not still_ticking(marker), "the grandchild stopped when the tree it belonged to ended"


def test_r1_the_parent_receipt_and_the_tree_receipt_are_separate(tmp_path):
    """Acceptance needs both, so they are recorded as two facts rather than one verdict."""
    result, _, _, _ = execute("normal", tmp_path)
    process = result["process"]
    assert set(process["parent"]) >= {"confirmed", "exit_code", "pid"}
    assert set(process["tree"]) >= {"confirmed", "method", "evidence"}
    assert process["confirmed"] == (process["parent"]["confirmed"] and process["tree"]["confirmed"])
    assert "a terminated parent is not a terminated tree" in process["note"]


def test_r1_an_unproven_tree_is_unknown_even_when_the_parent_exited_cleanly(tmp_path, monkeypatch):
    """The boundary, not the parent, decides: a tree that cannot be proven empty blocks."""
    runtime = transport("normal")
    with runtime as opened:
        real = ProcessTree.terminate

        def unprovable_tree(self, reason, **kwargs):
            record = real(self, reason, **kwargs)
            record["tree"] = {**record["tree"], "confirmed": False}
            record["confirmed"] = False
            return record

        monkeypatch.setattr(ProcessTree, "terminate", unprovable_tree)
        with pytest.raises(ContractError, match="termination could not be confirmed"):
            opened.run("prompt", str(tmp_path), SCHEMA, timeout=30)


def test_r1_a_tree_that_cannot_be_owned_never_starts(tmp_path, monkeypatch):
    """If the boundary cannot be established the process is not left running outside one."""
    from codex_harness.adapters import process_tree

    monkeypatch.setattr(process_tree.ProcessTree, "spawn",
                        classmethod(lambda cls, *a, **kw: (_ for _ in ()).throw(
                            process_tree.TreeOwnershipError("fixture: no boundary"))))
    runtime = transport("normal")
    with runtime as opened:
        with pytest.raises(ContractError, match="could not be started"):
            opened.run("prompt", str(tmp_path), SCHEMA, timeout=10)
    assert runtime.process is None


# ---- R2: how the process ended is a fact the terminal message does not settle ---------------------

def test_r2_a_success_message_followed_by_a_non_zero_exit_is_not_a_finished_run(tmp_path):
    result, _, _, _ = execute("nonzero", tmp_path, timeout=30)
    assert result["terminal"]["subtype"] == "success" and result["terminal"]["is_error"] is False
    assert result["process"]["exit_code"] == 7
    assert classify_result(result) == "provider_failure"
    assert result["failure"]["cause"] == "claude-provider-exit-conflict"
    assert "exited with code 7" in result["failure"]["detail"]
    assert result["answer"] is None, "no answer is read out of a run that ended badly"


def test_r2_a_run_this_runner_had_to_stop_is_not_clean_even_with_a_result(tmp_path):
    """A result that arrived before the deadline does not turn a forced stop into a clean run."""
    runtime = transport("tree")  # emits a startup report, then never ends by itself
    with runtime as opened:
        result = opened.run("prompt", str(tmp_path), SCHEMA, timeout=4)
    assert result["process"]["stop_reason"] == "deadline"
    assert classify_result(result) == "provider_failure"
    assert result["process"]["confirmed"] is True, "it was stopped, and that was proven"


def test_r2_a_clean_ending_is_still_accepted(tmp_path):
    result, _, _, _ = execute("normal", tmp_path)
    assert result["process"]["parent"]["ended_on_its_own"] is True
    assert result["process"]["exit_code"] == 0 and classify_result(result) == "accepted"


# ---- R3: an answer belongs to the session that was opened, or to no attempt here ------------------

@pytest.mark.parametrize("scenario,cause", [
    # The startup report names this attempt's session and the result names another one, so what
    # was seen is a disagreement inside the run, not simply the wrong id.
    ("wrong_session", "claude-provider-session-conflicting"),
    ("nosession", "claude-provider-session-unreported"),
])
def test_r3_a_result_from_another_session_is_not_this_attempts_answer(tmp_path, scenario, cause):
    result, _, _, _ = execute(scenario, tmp_path, timeout=30)
    assert result["session"]["match"] is False
    assert classify_result(result) == "provider_failure"
    assert result["failure"]["cause"] == cause
    assert result["answer"] is None


def test_r3_an_unobserved_identifier_is_never_read_as_a_match():
    requested = "11111111-1111-4111-8111-111111111111"
    assert _session_binding(requested, requested, requested)["state"] == "match"
    assert _session_binding(requested, None, requested)["state"] == "match"
    assert _session_binding(requested, None, None)["state"] == "unreported"
    assert _session_binding(requested, None, None)["match"] is False
    assert _session_binding(requested, requested, "other")["state"] == "conflicting"
    assert _session_binding(requested, "other", "other")["state"] == "mismatch"


def test_r3_a_reported_model_that_differs_from_an_exact_request_is_refused(tmp_path):
    result, _, _, _ = execute("wrong_model", tmp_path, timeout=30)
    assert result["model_agreement"]["state"] == "mismatch"
    assert classify_result(result) == "provider_failure"
    assert result["failure"]["cause"] == "claude-provider-model-mismatch"
    assert result["answer"] is None


def test_r3_an_alias_request_is_recorded_as_undecidable_rather_than_agreed():
    """An alias names a family. A concrete answer has not disagreed, and this harness says so."""
    assert _model_agreement("claude-fable-5-1", "claude-fable-5-1")["state"] == "match"
    assert _model_agreement("claude-fable-5-1", "claude-opus-5")["state"] == "mismatch"
    alias = _model_agreement("sonnet", "claude-sonnet-5")
    assert alias["state"] == "alias_not_decidable" and alias["decided_here"] is False
    assert _model_agreement("claude-fable-5-1", None)["state"] == "unreported"


def test_r3_an_alias_run_still_completes(tmp_path):
    """The refusal is about disagreement, not about aliases; an alias run is not blocked."""
    runtime = ClaudeCodeRuntime(model="sonnet", runtime=RUNTIME, executable=str(CHILD),
                                launcher=[sys.executable], max_budget_usd=1.0)
    with runtime as opened:
        result = opened.run("prompt", str(tmp_path), SCHEMA, timeout=30)
    assert classify_result(result) == "accepted"
    assert result["model_agreement"]["requested"] == "sonnet"


# ---- R4: the ceiling counts calls, not the names a caller chose for them --------------------------

def budget(tmp_path) -> CallBudget:
    return CallBudget(root=tmp_path / "ledger")


def test_r4_renaming_the_run_does_not_return_the_budget(tmp_path):
    """Codex's counterexample: two calls made, `--label` changed, the count read as zero."""
    ledger = budget(tmp_path)
    for label in ("windows-11", "windows-11"):
        ledger.settle(ledger.reserve(per_host=2, total=4, purpose=label, provider="claude",
                                     model="m")["id"], outcome="succeeded")
    # A different label, a different output directory, a different purpose string: same machine.
    with pytest.raises(ContractError, match="already recorded for this host"):
        ledger.reserve(per_host=2, total=4, purpose="windows-renamed", provider="claude", model="m")
    assert ledger.counts()["this_host"] == 2


def test_r4_a_slot_is_taken_before_anything_starts_and_an_interrupted_one_stays_taken(tmp_path):
    ledger = budget(tmp_path)
    taken = ledger.reserve(per_host=2, total=4, purpose="interrupted", provider="claude", model="m")
    assert taken["status"] == "reserved" and taken["counts_at_reservation"]["this_host"] == 0
    # Nothing settles it: the run was interrupted, and the budget reads that as spent.
    assert ledger.counts()["this_host"] == 1
    ledger.reserve(per_host=2, total=4, purpose="second", provider="claude", model="m")
    with pytest.raises(ContractError):
        ledger.reserve(per_host=2, total=4, purpose="third", provider="claude", model="m")


def test_r4_two_runners_cannot_both_take_the_last_slot(tmp_path):
    """The ledger is on disk and locked, so a second process sees the first one's slot."""
    ledger = budget(tmp_path)
    ledger.reserve(per_host=2, total=4, purpose="first", provider="claude", model="m")
    program = ("import sys, json\n"
               "sys.path.insert(0, sys.argv[1])\n"
               "from codex_harness.adapters.call_budget import CallBudget\n"
               "from codex_harness.domain.model import ContractError\n"
               "budget = CallBudget(root=sys.argv[2])\n"
               "try:\n"
               "    budget.reserve(per_host=2, total=4, purpose='other-process',"
               " provider='claude', model='m')\n"
               "    print(json.dumps({'taken': True}))\n"
               "except ContractError as exc:\n"
               "    print(json.dumps({'taken': False, 'why': str(exc)[:60]}))\n")
    source = str(Path(__file__).resolve().parents[1] / "src")
    done = subprocess.run([sys.executable, "-c", program, source, str(ledger.root)],
                          capture_output=True, text=True, timeout=120)
    assert json.loads(done.stdout.strip())["taken"] is True, "the second slot was free"
    assert ledger.counts()["this_host"] == 2
    done = subprocess.run([sys.executable, "-c", program, source, str(ledger.root)],
                          capture_output=True, text=True, timeout=120)
    assert json.loads(done.stdout.strip())["taken"] is False, "a third process is refused too"


def test_r4_an_unreadable_slot_is_a_taken_slot(tmp_path):
    ledger = budget(tmp_path)
    ledger.reserve(per_host=2, total=4, purpose="first", provider="claude", model="m")
    (ledger.root / "slots" / "damaged.json").write_text("{ not json", encoding="utf-8")
    counts = ledger.counts()
    assert counts["this_host"] == 2 and counts["unreadable"] == 1
    with pytest.raises(ContractError):
        ledger.reserve(per_host=2, total=4, purpose="third", provider="claude", model="m")


def test_r4_the_host_is_identified_by_the_machine_not_by_an_argument():
    identity = host_identity()
    assert identity["id"] and identity["system"] and identity["machine"]
    assert host_identity()["id"] == identity["id"], "the same machine answers the same way"
    assert "node" not in identity, "the machine's name is carried as a digest, not as text"


def test_r4_the_ceilings_come_from_the_packaged_policy(tmp_path):
    from codex_harness.adapters.providers import packaged_policy

    ceiling = packaged_policy().provider("claude").runtime["experiment_call_budget"]
    assert ceiling["per_host"] == 2 and ceiling["total"] == 4 and ceiling["note"]
    with tempfile.TemporaryDirectory() as name:
        ledger = CallBudget(root=Path(name))
        assert ledger.summary()["ledger"] == name and ledger.counts()["all_hosts"] == 0
