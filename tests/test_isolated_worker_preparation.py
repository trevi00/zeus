"""Source preparation reaches the existing lease heartbeat before the provider is entered
(INV-ISOLATED-WORKER-001, self-improvement-reference-001 delivery obstacle).

The repository, the files, the export and the staged bytes are REAL; the Docker client and the
inner process are the existing injected fakes from `test_isolated_worker`, and the lease is a
LABELLED stand-in for the `Workflow` API the REAL `LeaseProgress` calls. No model, provider,
container or host service runs here, and nothing here observes a real preparation delay: these
tests bound the behaviour of the fix, not the cause of the delay that motivated it.
"""
import json
import threading

import pytest
from test_isolated_worker import (  # noqa: F401  `candidate` and `config` are imported fixtures
    SCHEMA,
    FakeDocker,
    candidate,
    config,
    git,
    record,
    runtime,
)

from codex_harness.adapters import isolated_worker as iw
from codex_harness.adapters.executor import LeaseProgress
from codex_harness.domain.model import ContractError

FILES = 12


class FakeMonotonic:
    """LABELLED fake clock: every read advances `step` seconds. No test here sleeps."""

    def __init__(self, step=4.0):
        self.value, self.step = 0.0, step

    def __call__(self):
        self.value += self.step
        return self.value


class OwnedLease:
    """LABELLED stand-in for the two `Workflow` calls the REAL `LeaseProgress` makes.

    `remaining_seconds` refuses exactly as the real one does once the lease is gone; `heartbeat`
    renews for the SAME duration and never extends a deadline. Nothing here is a real task row.
    """

    def __init__(self, clock, deadline=10_000.0):
        self.clock, self.deadline = clock, deadline
        self.checks = self.beats = 0
        self.threads, self.docker_calls = set(), []

    def remaining_seconds(self, task, limit):
        self.checks += 1
        self.threads.add(threading.current_thread().name)
        if self.clock.value >= self.deadline:
            raise ContractError("Execution lease expired or was superseded")
        return min(limit, self.deadline - self.clock.value)

    def heartbeat(self, task):
        self.beats += 1


def big_candidate(repo):
    """The real fixture repository with more real files to export."""
    for index in range(FILES):
        (repo / ("module_%02d.py" % index)).write_text("VALUE = %d\n" % index, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "more files")
    return git(repo, "rev-parse", "HEAD")


def lease(clock, deadline=10_000.0):
    progress = LeaseProgress(OwnedLease(clock, deadline), {"id": "task-1", "generation": 1},
                             clock=clock)
    return progress, progress.workflow


# ----- the export itself --------------------------------------------------------------------------
def test_the_export_beats_the_existing_heartbeat_as_it_makes_progress(candidate, tmp_path, monkeypatch):  # noqa: F811
    head = big_candidate(candidate)
    monkeypatch.setattr(iw, "PREPARATION_TICK_SECONDS", 0)
    clock = FakeMonotonic()
    progress, owner = lease(clock)
    source = iw.stage_source(candidate, head, tmp_path / "stage", on_progress=progress)
    assert source["files"] == FILES + 3 and source["revision"] == head
    # One heartbeat owner, on the working thread: no renewal thread and no second watchdog.
    assert owner.checks >= source["files"] and owner.beats >= 2
    assert owner.threads == {threading.current_thread().name}
    assert progress.refusal is None


def test_preparation_without_a_callback_is_byte_identical(candidate, tmp_path, monkeypatch):  # noqa: F811
    head = big_candidate(candidate)
    monkeypatch.setattr(iw, "PREPARATION_TICK_SECONDS", 0)
    plain = iw.stage_source(candidate, head, tmp_path / "plain")
    ticks = []
    beaten = iw.stage_source(candidate, head, tmp_path / "beaten", on_progress=lambda: ticks.append(1))
    assert plain == beaten and len(ticks) >= FILES
    for name in plain["manifest"]:
        left = (tmp_path / "plain").joinpath(*name.split("/"))
        right = (tmp_path / "beaten").joinpath(*name.split("/"))
        assert left.read_bytes() == right.read_bytes()
        assert (left.stat().st_mode & 0o777) == (right.stat().st_mode & 0o777)
    assert plain["manifest_sha256"] == beaten["manifest_sha256"]


def test_a_refusing_heartbeat_stops_the_export_before_the_next_file(candidate, tmp_path, monkeypatch):  # noqa: F811
    """The caller's own refusal travels unchanged and the export stops where it was."""
    head = big_candidate(candidate)
    monkeypatch.setattr(iw, "PREPARATION_TICK_SECONDS", 0)
    calls = []

    def cancel():
        calls.append(1)
        if len(calls) > 3:
            raise ContractError("Execution lease expired or was superseded")

    with pytest.raises(ContractError, match="lease expired"):
        iw.stage_source(candidate, head, tmp_path / "stage", on_progress=cancel)
    staged = [path for path in (tmp_path / "stage").rglob("*") if path.is_file()]
    assert len(calls) == 4 and 0 < len(staged) < FILES + 3, "it stopped mid export, not at the end"


# ----- the run: before the container exists ---------------------------------------------------------
def test_a_lease_that_ends_while_preparing_starts_no_container_and_retains_the_record(
        config, candidate, tmp_path, monkeypatch):  # noqa: F811
    head = big_candidate(candidate)
    monkeypatch.setattr(iw, "PREPARATION_TICK_SECONDS", 0)
    fake = FakeDocker(tmp_path)
    clock = FakeMonotonic()
    # The lease ends part way through the export: 4 fake seconds per beat, gone after 24.
    progress, owner = lease(clock, deadline=24.0)
    with runtime(config, tmp_path, monkeypatch, fake) as opened, pytest.raises(ContractError) as refused:
        opened.run("do it", str(candidate), SCHEMA, 20, on_tick=progress)
    assert "lease expired" in str(refused.value), "the caller's own refusal, not a new isolation code"
    assert progress.refusal is refused.value and owner.beats >= 1
    # Nothing was created and nothing was started: this is a refusal that never ran.
    assert [call["args"][0] for call in fake.calls if call["args"][0] in ("create", "start")] == []
    assert list(fake.containers) == ["f" * 64]     # only the untouched sibling fixture
    saved = record(tmp_path)
    assert saved["state"] == "refused" and saved["container"] is None
    assert [step["state"] for step in saved["lifecycle"]] == ["refused"]
    assert saved["lifecycle"][0]["reason"] == "preparation_cancelled"
    assert saved["workspace"] == str(candidate.resolve()) and saved["record"].endswith("run.json")
    # The refusal is resolved: it never created a container, so it blocks no later run.
    assert iw.unresolved_runs(tmp_path / "runs") == []
    assert (candidate / "kept.txt").read_text() == "original\n", "the candidate is untouched"
    # The retained record names the run and its workspace; it carries no source bytes and no file.
    assert head not in json.dumps(saved) and "VALUE = 0" not in json.dumps(saved)


def test_a_live_lease_is_renewed_during_preparation_and_the_run_still_completes(
        config, candidate, tmp_path, monkeypatch):  # noqa: F811
    big_candidate(candidate)
    monkeypatch.setattr(iw, "PREPARATION_TICK_SECONDS", 0)
    fake = FakeDocker(tmp_path)
    clock = FakeMonotonic()
    owner = OwnedLease(clock)
    seen = []

    class Watched(LeaseProgress):
        """The REAL cadence, with the docker argv observed at every beat."""

        def __call__(self, stage=None):
            seen.append([call["args"][0] for call in fake.calls])
            return super().__call__(stage)

    watched = Watched(owner, {"id": "task-1", "generation": 1}, clock=clock)
    with runtime(config, tmp_path, monkeypatch, fake) as opened:
        result = opened.run("do it", str(candidate), SCHEMA, 20, on_tick=watched)
    assert result["answer"] == {"summary": "done"}
    prepared = [call for call in seen if "create" not in call]
    assert len(prepared) >= FILES, "the heartbeat ran while preparing, before any container existed"
    assert any("create" in call for call in seen), "and it kept running once the container existed"
    assert owner.beats >= 2 and owner.threads == {threading.current_thread().name}
    saved = record(tmp_path)
    assert [step["state"] for step in saved["lifecycle"]][:2] == ["prepared", "created"]
    assert saved["state"] == "removed" and watched.refusal is None
