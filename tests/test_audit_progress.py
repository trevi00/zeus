"""Audit goal-progress observation and its research routing (INV-AUDIT-PROGRESS-001).

The store, the artifact store, the policy resource, the portfolio rows, the research-program state
machine and its claim/capture/council path are REAL. The audit inventory, its partitions, its
settled `tasks` rows, its coverage rows and its source-read receipts are LABELLED synthetic records
written in the exact shape the existing owners write - except where a test says otherwise, where
the real Git audit fixture and the real inert source reader produce them. The council is the
existing labelled stand-in: none of these results is evidence that a model, Redis, PostgreSQL or a
host service ran, and a recorded candidate is an unverified symptom, never a cause.
"""
import json
from dataclasses import asdict
from types import SimpleNamespace

import pytest
from test_audit_service import connected, spool_observer  # noqa: F401  `connected` is a fixture
from test_research_audits import audit  # noqa: F401  imported fixture: registers `audit`
from test_research_program import POLICY as COUNCIL_POLICY
from test_research_program import build, registered
from test_research_program_fixtures import CANARY, FakeCouncil

from codex_harness.adapters.artifacts import FileArtifacts
from codex_harness.adapters.store import MemoryStore
from codex_harness.application.audit_progress import (
    BUCKET_STATE,
    BUCKET_WINDOWS,
    AuditProgress,
    packaged_policy,
    status_view,
)
from codex_harness.application.portfolio import (
    BUCKET_INVESTIGATIONS,
    RESEARCH_REQUIRED,
    Portfolio,
)
from codex_harness.application.research_program import BUCKET_DISPATCHES
from codex_harness.domain.audit_progress import (
    ADEQUATE,
    AUDIT_COMPLETE,
    KIND,
    LOW_YIELD,
    NO_EVIDENCE,
    NOT_COMPARABLE,
    UNKNOWN_EVIDENCE,
    ProgressRefused,
    candidate_identity,
    policy_digest,
    range_identity,
    validate_policy,
)
from codex_harness.domain.audit_progress import (
    validate_source as validate_progress_source,
)
from codex_harness.domain.model import canonical, digest
from codex_harness.domain.research import (
    ExecutionReceipt,
    PartitionCheckpoint,
    PathDisposition,
    SourceIdentity,
    SubsystemAnalysis,
)
from codex_harness.domain.research_investigations import KIND as FAILURE_KIND
from codex_harness.domain.research_investigations import eligible_investigations
from codex_harness.domain.research_program import ProgramRefused, validate_config

AUDIT = "audit-fixture-001"
PATHS = ["cGF0aC0w", "cGF0aC0x", "cGF0aC0y", "cGF0aC0z"]   # base64 inventory paths, as Git audits store them
SUBSYSTEMS = ["core"]
CLOCK_START = 1800000000


class Clock:
    """LABELLED fake clock: every call advances one minute, so elapsed seconds are observed."""

    def __init__(self, step=60):
        self.seconds, self.step = CLOCK_START, step

    def __call__(self):
        from datetime import datetime, timezone
        value = datetime.fromtimestamp(self.seconds, timezone.utc).isoformat()
        self.seconds += self.step
        return value


class World:
    """One labelled audit in a real store with a real artifact store."""

    def __init__(self, tmp_path, store=None, audit_id=AUDIT):
        self.store = store or MemoryStore()
        self.artifacts = FileArtifacts(str(tmp_path / "artifacts"))
        self.audit_id, self.executions, self.reads = audit_id, 0, 0
        source = SourceIdentity("https://github.com/fixture/repo", "a" * 40, "b" * 40, "sha256:" + "0" * 64)
        with self.store.transaction() as tx:
            tx.put("research_audits", audit_id, {
                "id": audit_id, "version": 1, "source": asdict(source),
                "inventory": [{"path": p, "mode": "100644", "object_id": "%040d" % n,
                               "size": 10, "artifact_ref": "sha256:" + "%064d" % n}
                              for n, p in enumerate(PATHS)],
                "subsystems": list(SUBSYSTEMS), "status": "source_verified_not_reviewed"})
        self.partition("p-1", PATHS[:2])
        self.partition("p-2", PATHS[2:])

    def partition(self, partition_id, paths, remaining=None):
        checkpoint = PartitionCheckpoint(self.audit_id, partition_id, 0, list(paths), [], [],
                                         list(paths if remaining is None else remaining), [], [], "pending")
        checkpoint.validate()
        with self.store.transaction() as tx:
            tx.put("research_partitions", partition_id, asdict(checkpoint))

    def settle(self, count=1, status="succeeded"):
        """LABELLED terminal `tasks` rows in the shape `Workflow` writes; no execution ran."""
        with self.store.transaction() as tx:
            for _ in range(count):
                self.executions += 1
                key = "task-%03d" % self.executions
                tx.put("tasks", key, {
                    "id": key, "status": status, "generation": 1, "attempt": 1,
                    "completed_at": "2028-01-01T00:%02d:00+00:00" % (self.executions % 60),
                    "message": {"what": {"action": "audit_partition",
                                         "details": {"audit_id": self.audit_id, "partition_id": "p-1"}}}})
        return self.executions

    def live(self, count=1):
        """A running task: live work, never settled and never treated as stalled or cancelled."""
        with self.store.transaction() as tx:
            for index in range(count):
                key = "live-%03d" % index
                tx.put("tasks", key, {"id": key, "status": "running", "generation": 1, "attempt": 1,
                                      "message": {"what": {"details": {"audit_id": self.audit_id}}}})

    def cover(self, path, disposition="semantic"):
        """A coverage row in the exact shape `ResearchAudits.checkpoint` writes, with the REAL
        `PathDisposition` record; no checkpoint transaction ran. `generated`, `duplicate` and
        `binary` carry the evidence, link and receipt the real record demands of them, so they are
        valid COMPLETION here exactly as the existing audit contract treats them."""
        reviewed = disposition not in ("unreviewed", "unavailable")
        record = PathDisposition(path, disposition, ["sha256:" + "1" * 64] if reviewed else [],
                                 [], "fixture justification" if reviewed else "",
                                 [p for p in PATHS if p != path][:1] if disposition in ("generated", "duplicate") else [],
                                 "read", ["receipt-1"] if disposition == "binary" else [])
        record.validate()
        with self.store.transaction() as tx:
            tx.put("research_paths", digest({"audit": self.audit_id, "item": path}),
                   {"audit_id": self.audit_id, "record": asdict(record), "task_id": "task-001", "generation": 1})
        self._remaining()

    def cover_subsystem(self, name):
        """A subsystem row in the shape `ResearchAudits.checkpoint` writes, with the REAL
        `SubsystemAnalysis` record: no contradiction, no unresolved dependency, no unrun test."""
        record = SubsystemAnalysis(name, list(PATHS), ["contract"], ["entry"], ["impl"], ["caller"],
                                   ["config"], ["store"], ["failure"], ['["pytest"]'], ["receipt-1"],
                                   ["sha256:" + "1" * 64], [], [], [])
        record.validate()
        with self.store.transaction() as tx:
            tx.put("research_subsystems", digest({"audit": self.audit_id, "item": name}),
                   {"audit_id": self.audit_id, "record": asdict(record), "task_id": "task-001",
                    "generation": 1})

    def uncover(self, path):
        """A regressed semantic set: the row disappears (a rebuild, a purge or a rollback)."""
        with self.store.transaction() as tx:
            tx.data.pop(("research_paths", digest({"audit": self.audit_id, "item": path})), None)
        self._remaining()

    def _remaining(self):
        with self.store.transaction() as tx:
            covered = {PathDisposition(**row["record"]).path for row in tx.scan("research_paths")
                       if row["audit_id"] == self.audit_id
                       and row["record"]["disposition"] not in ("unreviewed", "unavailable")}
            for row in tx.scan("research_partitions"):
                if row["audit_id"] != self.audit_id:
                    continue
                tx.put("research_partitions", row["partition_id"],
                       {**row, "remaining_paths": [p for p in row["paths"] if p not in covered]})

    def read(self, path=None, start=0):
        """A source-read receipt with the inert reader's REAL output document in the real artifact
        store; the reader itself is exercised separately against the real Git audit fixture."""
        self.reads += 1
        path = path or PATHS[0]
        body = {"path": path, "lines": ["fixture line"], "start_line": start, "start_char": 0,
                "next_line": start + 1, "next_char": 0, "total_lines": 9, "partial_last_line": False,
                "eof": False, "object_id": "object-" + path, "bytes_sha256": "c" * 64}
        ref = self.artifacts.put(canonical(body), "inert-source-inspection")["ref"]
        receipt = ExecutionReceipt(SourceIdentity("https://github.com/fixture/repo", "a" * 40, "b" * 40,
                                                  "sha256:" + "0" * 64),
                                   "env", ["source-read", path, str(start)],
                                   "inert-objects-no-code-execution", 0, ref, "harness:fixture",
                                   False, passed=True, outcome="read")
        receipt.validate()
        with self.store.transaction() as tx:
            tx.put("research_receipts", "receipt-%03d" % self.reads,
                   {"audit_id": self.audit_id, "task_id": "task-001", "generation": 1,
                    "receipt": asdict(receipt)})
        return ref

    def observer(self, policy=None, clock=None, artifacts=None):
        return AuditProgress(self.store, artifacts or self.artifacts, policy=policy, clock=clock or Clock())

    def rows(self, bucket):
        with self.store.transaction() as tx:
            return tx.scan(bucket)


def small(**overrides) -> dict:
    """The packaged policy with a smaller window, so a test closes windows without 20 fixtures."""
    return {**packaged_policy(), "window_executions": 2, **overrides}


def close(world, observer, *, executions=2, evidence=True):
    """Settle a window's worth of executions (optionally with new read evidence) and observe."""
    if evidence:
        world.read(start=world.reads)
    world.settle(executions)
    return observer.observe(world.audit_id, release_id="release-1", revision="r" * 40)


# ----- the policy and the opt-in configuration ---------------------------------------------------
def test_the_packaged_policy_is_validated_and_a_broken_one_is_refused_not_defaulted():
    policy = validate_policy(packaged_policy())
    assert policy["window_executions"] == 10 and policy["minimum_semantic_paths"] == 1
    assert policy["low_yield_windows"] == 2 and "never model input" in policy["authority"]
    assert policy_digest(policy) == policy_digest(validate_policy(packaged_policy()))
    for override, code in (({"window_executions": 0}, "policy_invalid"), ({"low_yield_windows": 1}, "policy_invalid"),
                           ({"minimum_semantic_paths": True}, "policy_invalid"), ({"version": 2}, "policy_invalid"),
                           ({"extra": 1}, "policy_fields"), ({"schema": "urn:other:1"}, "policy_schema")):
        with pytest.raises(ProgressRefused) as refused:
            validate_policy({**packaged_policy(), **override})
        assert refused.value.reason_code == code, override


def test_the_audit_progress_source_is_opt_in_bounded_and_keeps_the_legacy_config_identical():
    head = "a" * 40
    from test_research_program_fixtures import config as program_config

    legacy = validate_config(program_config(head), COUNCIL_POLICY)
    assert "audit_progress_source" not in legacy
    opted = validate_config(program_config(head, audit_progress_source={"topic": "storage", "audit_ids": [AUDIT]}),
                            COUNCIL_POLICY)
    assert opted["audit_progress_source"] == {"topic": "storage", "audit_ids": [AUDIT]}
    assert {k: v for k, v in opted.items() if k != "audit_progress_source"} == legacy
    for source, code in (({"topic": "missing", "audit_ids": [AUDIT]}, "config_invalid"),
                         ({"topic": "storage", "audit_ids": []}, "config_invalid"),
                         ({"topic": "storage", "audit_ids": ["*"]}, "config_invalid"),
                         ({"topic": "storage", "audit_ids": [AUDIT, AUDIT]}, "config_duplicate"),
                         ({"topic": "storage", "audit_ids": [AUDIT], "extra": 1}, "config_fields")):
        with pytest.raises(ProgramRefused) as refused:
            validate_config(program_config(head, audit_progress_source=source), COUNCIL_POLICY)
        assert refused.value.reason_code == code, source
    with pytest.raises(ProgressRefused, match="config_invalid"):
        validate_progress_source(None, {"storage"})


# ----- baseline, windows and the verdicts --------------------------------------------------------
def test_the_baseline_excludes_history_and_exactly_one_window_closes_per_reading(tmp_path):
    world = World(tmp_path)
    world.settle(5)                       # historical executions, before any observation
    observer = world.observer(policy=small())
    baseline = observer.observe(AUDIT, release_id="release-1", revision="r" * 40)
    assert baseline["status"] == "baseline" and baseline["window"] is None
    assert baseline["metrics"]["executions"] == 5 and baseline["streak"] == 0
    assert status_view(observer.state(AUDIT))["baseline_executions"] == 5
    world.settle(1)
    assert observer.observe(AUDIT, release_id="release-1", revision="r" * 40)["status"] == "observed"
    assert observer.windows(AUDIT) == [], "a window needs exactly its own executions"
    closed = close(world, observer, executions=1)
    assert closed["status"] == "window_closed" and closed["window"]["executions"] == 2
    assert [w["index"] for w in observer.windows(AUDIT)] == [1]
    assert observer.windows(AUDIT)[0]["members"] == ["task-006:1:1:succeeded", "task-007:1:1:succeeded"]
    assert closed["metrics"]["executions"] == 7, "history is counted as scope, never as window credit"


def test_new_evidence_without_semantic_gain_is_low_yield_and_real_progress_clears_the_streak(tmp_path):
    world = World(tmp_path)
    observer = world.observer(policy=small())
    observer.observe(AUDIT, release_id="release-1", revision="r" * 40)
    low = close(world, observer)
    assert low["verdict"] == LOW_YIELD and low["window"]["delta"]["distinct_ranges"] == 1
    assert low["streak"] == 1 and low["candidate"] is None
    world.cover(PATHS[0])
    good = close(world, observer)
    assert good["verdict"] == ADEQUATE and good["window"]["delta"]["semantic_total"] == 1
    assert good["streak"] == 0 and good["candidate"] is None
    assert observer.candidates(AUDIT) == []
    # A disposition-only change is not semantic gain: the window is low yield with no new evidence.
    world.cover(PATHS[1], disposition="unreviewed")
    silent = close(world, observer, evidence=False)
    assert silent["verdict"] == NO_EVIDENCE and silent["window"]["delta"]["semantic_total"] == 0
    assert silent["metrics"]["non_semantic"] == {"unreviewed": 1} and silent["streak"] == 1


def test_generated_duplicate_and_binary_completions_are_valid_but_never_semantic_gain(tmp_path):
    """The completion denominator is not the semantic denominator: `ResearchAudits._coverage`
    counts these dispositions as covered, and this observer counts none of them as semantic yield."""
    world = World(tmp_path)
    observer = world.observer(policy=small())
    observer.observe(AUDIT, release_id="release-1", revision="r" * 40)
    world.cover(PATHS[0], disposition="generated")
    world.cover(PATHS[1], disposition="duplicate")
    first = close(world, observer)
    assert first["metrics"]["semantic_paths"] == 0 and first["window"]["delta"]["semantic_paths"] == 0
    assert first["metrics"]["non_semantic"] == {"duplicate": 1, "generated": 1}
    assert first["verdict"] == LOW_YIELD and first["streak"] == 1
    assert first["metrics"]["remaining_paths"] == 2, "they remain valid completion of those paths"
    world.cover(PATHS[2], disposition="binary")
    second = close(world, observer, evidence=False)
    assert second["metrics"]["non_semantic"]["binary"] == 1 and second["metrics"]["remaining_paths"] == 1
    assert second["window"]["delta"]["semantic_total"] == 0 and second["verdict"] == NO_EVIDENCE
    assert second["streak"] == 2 and second["candidate_created"] is True


def test_one_semantic_path_clears_the_streak_and_a_subsystem_only_gain_does_not(tmp_path):
    world = World(tmp_path)
    observer = world.observer(policy=small())
    observer.observe(AUDIT, release_id="release-1", revision="r" * 40)
    world.cover(PATHS[0])
    good = close(world, observer)
    assert good["verdict"] == ADEQUATE and good["window"]["delta"]["semantic_paths"] == 1
    assert good["streak"] == 0 and good["metrics"]["semantic_paths"] == 1
    # `minimum_semantic_paths` is a PATH threshold: subsystem progress is reported beside it.
    world.cover_subsystem("core")
    subsystem = close(world, observer)
    assert subsystem["window"]["delta"]["semantic_subsystems"] == 1
    assert subsystem["window"]["delta"]["semantic_total"] == 1
    assert subsystem["window"]["delta"]["semantic_paths"] == 0
    assert subsystem["verdict"] == LOW_YIELD and subsystem["streak"] == 1
    assert subsystem["metrics"]["semantic_subsystems"] == 1


def test_a_semantic_path_rewritten_as_a_valid_completion_is_a_visible_regression(tmp_path):
    world = World(tmp_path)
    world.cover(PATHS[0])
    world.cover(PATHS[1])
    observer = world.observer(policy=small())
    observer.observe(AUDIT, release_id="release-1", revision="r" * 40)
    world.cover(PATHS[1], disposition="duplicate")
    world.cover_subsystem("core")          # a subsystem gain never hides the path regression
    regressed = close(world, observer)
    assert regressed["metrics"]["semantic_paths"] == 1
    assert regressed["metrics"]["non_semantic"] == {"duplicate": 1}
    assert regressed["window"]["delta"]["semantic_paths"] == -1
    assert regressed["window"]["delta"]["semantic_subsystems"] == 1
    assert regressed["window"]["delta"]["semantic_total"] == 0
    assert regressed["window"]["delta"]["regressed"] is True
    assert regressed["verdict"] == LOW_YIELD and regressed["streak"] == 1
    assert regressed["metrics"]["remaining_paths"] == 2, "the completion contract did not regress"


def test_a_regressed_semantic_set_is_visible_and_never_positive_only(tmp_path):
    world = World(tmp_path)
    world.cover(PATHS[0])
    world.cover(PATHS[1])
    observer = world.observer(policy=small())
    observer.observe(AUDIT, release_id="release-1", revision="r" * 40)
    world.uncover(PATHS[1])
    regressed = close(world, observer)
    assert regressed["window"]["delta"]["semantic_total"] == -1
    assert regressed["window"]["delta"]["regressed"] is True and regressed["verdict"] == LOW_YIELD
    assert regressed["metrics"]["semantic_paths"] == 1


def test_a_completed_audit_is_never_a_low_yield_strike(tmp_path):
    world = World(tmp_path)
    observer = world.observer(policy=small())
    observer.observe(AUDIT, release_id="release-1", revision="r" * 40)
    for path in PATHS:
        world.cover(path)
    world.cover_subsystem("core")
    complete = close(world, observer)
    assert complete["verdict"] == AUDIT_COMPLETE and complete["streak"] == 0
    assert complete["metrics"]["complete"] is True and complete["candidate"] is None
    assert complete["metrics"]["remaining_paths"] == 0 and complete["metrics"]["open_questions"] == 0


def test_unreadable_evidence_is_unknown_never_zero_and_breaks_comparability(tmp_path):
    world = World(tmp_path)
    observer = world.observer(policy=small())
    observer.observe(AUDIT, release_id="release-1", revision="r" * 40)
    first = close(world, observer)
    assert first["streak"] == 1

    class Broken:
        """Injected fault: the evidence body cannot be read."""

        @staticmethod
        def document(ref):
            raise OSError("fixture: artifact unavailable " + CANARY)

    blind = world.observer(policy=small(), artifacts=Broken())
    unknown = close(world, blind)
    assert unknown["verdict"] == UNKNOWN_EVIDENCE and unknown["unknown"] == "unreadable_evidence"
    assert unknown["metrics"]["distinct_ranges"] == 0 and unknown["window"]["comparable"] is False
    assert unknown["streak"] == 0, "unknown evidence breaks comparability; it is not a second strike"
    assert observer.candidates(AUDIT) == []
    assert CANARY not in json.dumps(unknown)


def test_a_nondivisible_overflow_cohort_is_consumed_once_and_leaves_nothing_behind(tmp_path):
    world = World(tmp_path)
    observer = world.observer(policy=small())
    observer.observe(AUDIT, release_id="release-1", revision="r" * 40)
    world.settle(5)      # a restart or a backlog: more settled work than one window
    overflowed = observer.observe(AUDIT, release_id="release-1", revision="r" * 40)
    assert overflowed["window"]["verdict"] == NOT_COMPARABLE
    assert overflowed["window"]["verdict_reason"] == "window_overflow" and overflowed["streak"] == 0
    # ONE receipt over the WHOLE unseen cohort, with its real size reported, not a size-2 slice.
    assert overflowed["new_executions"] == 5 and overflowed["window"]["executions"] == 5
    assert len(observer.windows(AUDIT)[0]["members"]) == 5
    # Nothing is left over to be given a new opening measurement, so a duplicate reading and a
    # restart close no window at all and no strike is invented from that old work.
    repeat = observer.observe(AUDIT, release_id="release-1", revision="r" * 40)
    assert repeat["status"] == "observed" and repeat["window"] is None and repeat["streak"] == 0
    assert world.observer(policy=small()).observe(AUDIT, release_id="release-1",
                                                  revision="r" * 40)["window"] is None
    assert len(observer.windows(AUDIT)) == 1
    # Two WHOLLY NEW low windows, anchored at the overflow reading, still trigger normally.
    first = close(world, observer)
    assert first["window"]["comparable"] is True and first["streak"] == 1 and first["candidate"] is None
    second = close(world, observer)
    assert second["streak"] == 2 and second["candidate_created"] is True
    assert [w["executions"] for w in observer.windows(AUDIT)] == [5, 2, 2]


def test_gains_before_a_divisible_overflow_anchor_the_next_window_and_invent_no_strike(tmp_path):
    """The owner counterexample: baseline -> four settled executions carrying two semantic gains ->
    observe -> an identical observe -> two genuinely new zero-gain executions -> observe. The old
    leftovers must never be measured against the reading that already contains their own gains."""
    world = World(tmp_path)
    observer = world.observer(policy=small())
    observer.observe(AUDIT, release_id="release-1", revision="r" * 40)
    world.settle(4)                       # exactly two windows' worth: divisible, still ONE cohort
    world.cover(PATHS[0])
    world.cover(PATHS[1])
    overflowed = observer.observe(AUDIT, release_id="release-1", revision="r" * 40)
    assert overflowed["window"]["verdict"] == NOT_COMPARABLE and overflowed["window"]["executions"] == 4
    assert overflowed["window"]["delta"]["semantic_paths"] == 2, "the observed gains are not lost"
    assert overflowed["streak"] == 0 and len(observer.windows(AUDIT)) == 1
    identical = observer.observe(AUDIT, release_id="release-1", revision="r" * 40)
    assert identical["status"] == "observed" and identical["streak"] == 0
    restarted = world.observer(policy=small())
    world.settle(2)
    low = restarted.observe(AUDIT, release_id="release-1", revision="r" * 40)
    assert low["window"]["comparable"] is True and low["window"]["executions"] == 2
    assert low["verdict"] == NO_EVIDENCE and low["streak"] == 1, "one new window, one strike"
    assert low["candidate"] is None and restarted.candidates(AUDIT) == []
    assert len(restarted.windows(AUDIT)) == 2


# ----- exactly two low windows, one candidate ----------------------------------------------------
def test_two_low_windows_create_one_research_required_candidate_with_no_job_membership(tmp_path):
    world = World(tmp_path)
    observer = world.observer(policy=small())
    observer.observe(AUDIT, release_id="release-1", revision="r" * 40)
    first = close(world, observer)
    assert first["candidate"] is None and first["streak"] == 1
    second = close(world, observer)
    assert second["streak"] == 2 and second["candidate_created"] is True
    rows = observer.candidates(AUDIT)
    assert len(rows) == 1
    row = rows[0]
    assert row["kind"] == KIND and row["state"] == RESEARCH_REQUIRED and row["reason_code"] == LOW_YIELD
    assert row["windows"] == [w["id"] for w in observer.windows(AUDIT)] and row["count"] == 2
    assert "job_ids" not in row and "family_status" not in row, "an empty job family is never invented"
    assert row["epoch"] == second["epoch"] and row["policy_sha256"] == policy_digest(validate_policy(small()))
    assert row["id"] == candidate_identity(second["epoch"])
    # A third low window deduplicates onto the same row and only records a later observation.
    third = close(world, observer)
    assert third["candidate"] == row["id"] and third["candidate_created"] is False
    again = observer.candidates(AUDIT)[0]
    assert len(observer.candidates(AUDIT)) == 1 and again["windows"] == row["windows"]
    assert [o["window"] for o in again["observations"]] == [third["window"]["id"]]
    assert again["created_at"] == row["created_at"] and again["state"] == RESEARCH_REQUIRED


def test_an_owner_disposition_survives_later_observations(tmp_path):
    world = World(tmp_path)
    observer = world.observer(policy=small())
    observer.observe(AUDIT, release_id="release-1", revision="r" * 40)
    close(world, observer)
    candidate = close(world, observer)["candidate"]
    owner = Portfolio(world.store, _definitions(), clock=lambda: "2028-02-01T00:00:00+00:00")
    decided = owner.disposition(candidate, "deferred", ["docs/zeus/evidence.md"])["candidate"]
    assert decided["state"] == "deferred" and decided["kind"] == KIND
    close(world, observer)
    kept = observer.candidates(AUDIT)[0]
    assert kept["state"] == "deferred" and kept["evidence_refs"] == ["docs/zeus/evidence.md"]
    assert kept["decided_at"] == "2028-02-01T00:00:00+00:00"


# ----- repetition, restart, live work and epochs -------------------------------------------------
def test_duplicate_ticks_live_work_and_a_restart_do_not_create_extra_windows_or_strikes(tmp_path):
    world = World(tmp_path)
    observer = world.observer(policy=small())
    observer.observe(AUDIT, release_id="release-1", revision="r" * 40)
    world.live(3)
    closed = close(world, observer)
    for _ in range(3):      # duplicate ticks with no new settlement
        repeat = observer.observe(AUDIT, release_id="release-1", revision="r" * 40)
        assert repeat["status"] == "observed" and repeat["window"] is None
    assert len(observer.windows(AUDIT)) == 1 and closed["streak"] == 1
    assert observer.state(AUDIT)["streak"] == 1
    # A restart: a NEW observer object over the same durable state resumes the same epoch.
    restarted = world.observer(policy=small())
    resumed = close(world, restarted)
    assert resumed["epoch"] == closed["epoch"] and resumed["streak"] == 2
    assert len(restarted.windows(AUDIT)) == 2
    with world.store.transaction() as tx:      # the live rows were never touched
        assert [row["status"] for row in tx.scan("tasks") if row["id"].startswith("live-")] == ["running"] * 3


def test_a_changed_scope_policy_or_release_starts_a_new_epoch_without_comparing_history(tmp_path):
    world = World(tmp_path)
    observer = world.observer(policy=small())
    observer.observe(AUDIT, release_id="release-1", revision="r" * 40)
    first = close(world, observer)
    assert first["streak"] == 1
    world.partition("p-3", [PATHS[0]])       # the measuring scope changed
    rescoped = close(world, observer)
    assert rescoped["status"] == "baseline" and rescoped["epoch"] != first["epoch"]
    assert rescoped["streak"] == 0 and observer.state(AUDIT)["epochs"] == 2
    assert [w["epoch"] for w in observer.windows(AUDIT)] == [first["epoch"]], "history is retained, not rewritten"
    # A different release identity and a different policy are likewise new epochs.
    other = close(world, observer)
    moved = observer.observe(AUDIT, release_id="release-2", revision="r" * 40)
    assert moved["status"] == "baseline" and moved["epoch"] not in {first["epoch"], other["epoch"]}
    strict = world.observer(policy=small(minimum_semantic_paths=2))
    assert strict.observe(AUDIT, release_id="release-2", revision="r" * 40)["epoch"] != moved["epoch"]


def test_state_that_changes_during_evidence_verification_writes_nothing(tmp_path):
    world = World(tmp_path)
    observer = world.observer(policy=small())
    observer.observe(AUDIT, release_id="release-1", revision="r" * 40)
    world.read()
    world.settle(2)
    real = world.artifacts

    class Racing:
        """Injected race: another execution settles while the evidence is being verified."""

        def __init__(self):
            self.calls = 0

        def document(self, ref):
            self.calls += 1
            world.settle(1)
            return real.document(ref)

    racing = world.observer(policy=small(), artifacts=Racing())
    degraded = racing.observe(AUDIT, release_id="release-1", revision="r" * 40)
    assert degraded["status"] == "degraded" and degraded["reason_code"] == "state_changed"
    assert observer.windows(AUDIT) == [] and observer.candidates(AUDIT) == []
    assert observer.state(AUDIT)["windows_completed"] == 0
    # The next clean reading closes its window from the same authoritative records.
    assert observer.observe(AUDIT, release_id="release-1", revision="r" * 40)["status"] == "window_closed"


def test_an_unknown_or_unpartitioned_audit_is_degraded_and_never_a_known_zero(tmp_path):
    world = World(tmp_path)
    observer = world.observer(policy=small())
    missing = observer.observe("no-such-audit", release_id="release-1", revision="r" * 40)
    assert missing["status"] == "degraded" and missing["reason_code"] == "unknown_audit"
    assert world.rows(BUCKET_STATE) == [] and world.rows(BUCKET_WINDOWS) == []
    with world.store.transaction() as tx:
        for row in tx.scan("research_partitions"):
            tx.data.pop(("research_partitions", row["partition_id"]), None)
    bare = observer.observe(AUDIT, release_id="release-1", revision="r" * 40)
    assert bare["status"] == "degraded" and bare["reason_code"] == "audit_not_partitioned"


# ----- real reader evidence ----------------------------------------------------------------------
def test_distinct_ranges_come_from_the_real_inert_reader_output_and_repeats_add_nothing(audit, tmp_path):  # noqa: F811
    """The REAL audit fixture, the REAL inert source reader and the REAL artifact store."""
    import base64

    from codex_harness.adapters.audit_runner import AuditRunner
    service, record, source, entries, _ = audit
    service.partition(record["id"], 1)
    runner = AuditRunner(tmp_path / "reader", service.artifacts)
    path = next(e.path for e in entries if base64.b64decode(e.path) == b"normal")
    receipts = [runner.execute(source, ["source-read", path, "0"]),
                runner.execute(source, ["source-read", path, "0"])]      # the same range twice
    with service.store.transaction() as tx:
        for index, receipt in enumerate(receipts):
            tx.put("research_receipts", "r-%d" % index, {"audit_id": record["id"], "task_id": "t",
                                                         "generation": 1, "receipt": asdict(receipt)})
    body = service.artifacts.document(receipts[0].output_ref)
    assert range_identity(body) == (body["object_id"], 0, 0, body["next_line"], body["next_char"])
    observer = AuditProgress(service.store, service.artifacts, policy=small(), clock=Clock())
    observed = observer.observe(record["id"], release_id="release-1", revision="r" * 40)
    assert observed["evidence"]["read_receipts"] == 2, "two receipts naming one immutable body"
    assert observed["evidence"]["verified_bodies"] == 1 and observed["metrics"]["distinct_ranges"] == 1
    assert observed["evidence"]["unreadable"] == 0 and observed["unknown"] is None
    # A different range of the same object is new evidence; the repeat above was not.
    second = runner.execute(source, ["source-read", path, "0", "1"])
    with service.store.transaction() as tx:
        tx.put("research_receipts", "r-2", {"audit_id": record["id"], "task_id": "t", "generation": 1,
                                            "receipt": asdict(second)})
    again = observer.observe(record["id"], release_id="release-1", revision="r" * 40)
    assert again["metrics"]["distinct_ranges"] == 2


# ----- the portfolio boundary --------------------------------------------------------------------
def _definitions() -> dict:
    return {"schema": "urn:zeus:portfolio-definitions:1", "projects": [
        {"id": "ops", "title": "Operations", "outcome": "bound work completes",
         "source_ref": "docs/GOAL.md", "criteria": [{"id": "c1", "text": "jobs reach acceptance"}]}]}


def test_a_progress_candidate_is_never_a_failed_job_family_anywhere(tmp_path):
    world = World(tmp_path)
    observer = world.observer(policy=small())
    observer.observe(AUDIT, release_id="release-1", revision="r" * 40)
    close(world, observer)
    close(world, observer)
    rows = world.rows(BUCKET_INVESTIGATIONS)
    assert len(rows) == 1 and rows[0]["kind"] == KIND
    # The failure-family rule never scans it, counts it or dispatches it.
    found = eligible_investigations(investigations=rows, jobs=[], bindings=[],
                                    source={"topic": "storage", "project_ids": ["ops"],
                                            "reason_codes": [LOW_YIELD, "store_timeout"]},
                                    claimed=set(), required_state=RESEARCH_REQUIRED, minimum=2)
    assert found["candidates"] == []
    assert found["counts"] == {"scanned": 0, "eligible": 0, "malformed": 0, "state": 0,
                               "reason_code": 0, "insufficient_jobs": 0, "claimed": 0}
    # The portfolio projection keeps the failure queue exactly as it was and reports the kind apart.
    status = Portfolio(world.store, _definitions()).status()
    assert status["investigations"] == [] and status["investigations_truncated"] is False
    assert [row["id"] for row in status["progress_investigations"]] == [rows[0]["id"]]
    assert status["progress_investigations"][0]["kind"] == KIND
    assert status["progress_investigations"][0]["audit_id"] == AUDIT
    assert "job_ids" not in status["progress_investigations"][0]
    assert FAILURE_KIND != KIND


# ----- routing into the existing research program ------------------------------------------------
def program(tmp_path, world, **overrides):
    env = build(tmp_path / "program", store=world.store, council=FakeCouncil(world.store, status="accepted"))
    registered(env, audit_progress_source={"topic": "storage", "audit_ids": [world.audit_id]}, **overrides)
    return env


def two_low_windows(world):
    """Two low-yield windows under the PACKAGED thresholds, so the routing below runs against the
    exact policy digest the research program has in force."""
    observer = world.observer()
    observer.observe(world.audit_id, release_id="release-1", revision="r" * 40)
    size = packaged_policy()["window_executions"]
    close(world, observer, executions=size)
    return close(world, observer, executions=size), observer


def test_two_low_windows_route_through_the_existing_claim_capture_and_council(tmp_path):
    world = World(tmp_path)
    closed, observer = two_low_windows(world)
    env = program(tmp_path, world)
    receipt = env.runner.tick("rp-001")
    assert receipt["investigation"] == closed["candidate"] and receipt["result"] == "accepted"
    assert receipt["selected"] == "ap-" + closed["candidate"][:24]
    view = env.programs.status("rp-001")
    cycle = view["cycle_receipts"][0]
    assert cycle["audit_progress"]["counts"]["eligible"] == 1 and cycle["audit_progress"]["new"] == 1
    assert cycle["audit_progress"]["claimed"] == closed["candidate"]
    assert cycle["audit_progress"]["result"] == "accepted"
    assert cycle["investigations"] is None, "the failure-family bridge stays disabled here"
    assert view["audit_progress"]["accepted"] == 1 and view["investigations"]["total"] == 0
    # The claim is the existing cross-program dispatch row, keyed by the candidate id.
    with world.store.transaction() as tx:
        dispatch = tx.get(BUCKET_DISPATCHES, closed["candidate"])
    assert dispatch["kind"] == KIND and dispatch["job_ids"] is None and dispatch["job_ids_total"] is None
    assert dispatch["family_status"] is None and dispatch["reason_code"] == LOW_YIELD
    assert dispatch["scope"] == {"audit_id": AUDIT, "epoch": closed["epoch"],
                                 "policy_sha256": policy_digest(validate_policy(packaged_policy()))}
    assert dispatch["state"] == "resolved" and dispatch["result"] == "accepted"
    # The council received the immutable snapshot with both window receipts at the capture commit.
    from test_research_program_fixtures import git
    captured = json.loads(git(env.root, "show", cycle["capture"]["revision"] + ":" + cycle["capture"]["path"]).stdout)
    snapshot = captured["audit_progress"]
    assert "investigation" not in captured and snapshot["kind"] == KIND
    assert [w["id"] for w in snapshot["windows"]] == [w["id"] for w in observer.windows(AUDIT)]
    assert snapshot["windows"][0]["members_sha256"] == observer.windows(AUDIT)[0]["members_sha256"]
    assert snapshot["audit_id"] == AUDIT and "unverified" in snapshot["trust"]
    # The owner's candidate row is untouched: no state, disposition or window changed.
    assert observer.candidates(AUDIT)[0]["state"] == RESEARCH_REQUIRED
    assert observer.candidates(AUDIT)[0]["decided_at"] is None
    report = (env.runtime / "research-program" / "rp-001" / "report.md").read_text(encoding="utf-8")
    assert "Audit progress dispatches" in report and "audit progress scanned 1" in report
    events = [json.loads(line) for line in
              (env.runtime / "research-program" / "rp-001" / "events.jsonl").read_text("utf-8").splitlines()]
    claimed = [e for e in events if e["event"] == "audit_progress_claimed"]
    assert claimed and claimed[0]["attributes"]["investigation"] == closed["candidate"]
    assert [e for e in events if e["event"] == "audit_progress_result"][0]["attributes"]["result"] == "accepted"
    assert CANARY not in json.dumps(events) + report


def test_a_disallowed_audit_a_decided_owner_and_a_changed_epoch_are_all_ineligible(tmp_path):
    world = World(tmp_path)
    closed, observer = two_low_windows(world)
    env = build(tmp_path / "program", store=world.store, council=FakeCouncil(world.store, status="accepted"))
    registered(env, audit_progress_source={"topic": "storage", "audit_ids": ["another-audit"]})
    receipt = env.runner.tick("rp-001")
    assert receipt["selected"] == "local-note", "an unauthorized audit is never claimed"
    cycle = env.programs.status("rp-001")["cycle_receipts"][0]
    assert cycle["audit_progress"]["counts"] == {"scanned": 1, "eligible": 0, "malformed": 0, "state": 0,
                                                 "scope": 1, "epoch": 0, "window": 0, "policy": 0, "claimed": 0}
    with world.store.transaction() as tx:       # an owner decision ends eligibility
        row = tx.get(BUCKET_INVESTIGATIONS, closed["candidate"])
        tx.put(BUCKET_INVESTIGATIONS, closed["candidate"], {**row, "state": "researched"})
    counts = _scan_counts(tmp_path / "decided", world, [AUDIT])
    assert counts["state"] == 1 and counts["eligible"] == 0
    with world.store.transaction() as tx:       # a changed epoch is never re-dispatched
        tx.put(BUCKET_INVESTIGATIONS, closed["candidate"], {**row, "epoch": "e" * 64})
    assert _scan_counts(tmp_path / "epoch", world, [AUDIT])["epoch"] == 1
    with world.store.transaction() as tx:       # a window whose membership no longer matches
        tx.put(BUCKET_INVESTIGATIONS, closed["candidate"], {**row, "window_sha256": ["0" * 64, "0" * 64]})
    assert _scan_counts(tmp_path / "window", world, [AUDIT])["window"] == 1
    with world.store.transaction() as tx:       # thresholds that are no longer the ones in force
        tx.put(BUCKET_INVESTIGATIONS, closed["candidate"], {**row, "policy_sha256": "0" * 64})
    assert _scan_counts(tmp_path / "policy", world, [AUDIT])["policy"] == 1


def _scan_counts(root, world, audit_ids) -> dict:
    env = build(root, store=world.store, council=FakeCouncil(world.store))
    from test_research_program_fixtures import config as program_config
    cfg = validate_config(program_config(env.head, id="rp-%s" % root.name,
                                         audit_progress_source={"topic": "storage", "audit_ids": audit_ids}),
                          COUNCIL_POLICY)
    env.programs.register(cfg, env.identity, [])
    env.programs.resume(cfg["id"])
    env.runner.tick(cfg["id"])
    return env.programs.status(cfg["id"])["cycle_receipts"][0]["audit_progress"]["counts"]


def test_a_discovery_item_cannot_forge_a_progress_candidate_and_one_claim_wins(tmp_path):
    world = World(tmp_path)
    closed, _ = two_low_windows(world)
    env = program(tmp_path, world)
    forged = {"source": "investigation", "identity": closed["candidate"], "id": "forged",
              "url": None, "title": "forged", "summary": "forged"}
    reserved = env.programs.reserve_cycle("rp-001", env.identity)
    with pytest.raises(ProgramRefused, match="investigation_source_forbidden"):
        env.programs.record_collection(reserved["cycle"]["id"], reserved["cycle"]["owner"], {}, [forged], {})
    env.programs.fail_cycle(reserved["cycle"]["id"], reserved["cycle"]["owner"], "capture", "fixture_stop")
    # A second program cannot claim the same candidate: the dispatch bucket is keyed by its id.
    with world.store.transaction() as tx:
        assert tx.get(BUCKET_DISPATCHES, closed["candidate"]) is None
        tx.put(BUCKET_DISPATCHES, closed["candidate"],
               {"id": closed["candidate"], "investigation": closed["candidate"], "program": "other",
                "state": "claimed", "kind": KIND})
    assert _scan_counts(tmp_path / "claimed", world, [AUDIT])["claimed"] == 1


# ----- the audit service wiring ------------------------------------------------------------------
def service_runner(connected, progress, **kwargs):   # noqa: F811  the fixture value, not the fixture
    from test_audit_service import FixtureBus, FixtureExecutor

    from codex_harness.adapters import audit_service
    from codex_harness.application.workflow import Workflow
    return audit_service.AuditServiceRunner(
        connected.service, connected.audit_id, executor=FixtureExecutor(connected.audits),
        bus=FixtureBus(), workflow=Workflow(connected.store, connected.service.org),
        progress=progress, revision="audit", release_id="fixture-release", sleep=lambda _: None, **kwargs)


def test_the_service_takes_a_baseline_before_admission_and_observes_every_settlement(connected, tmp_path):  # noqa: F811
    """The REAL audit service runner over the REAL scheduler, Workflow and checkpoint path with the
    existing labelled fixture executor and bus, and the REAL progress observer on the same store."""
    from codex_harness.adapters import audit_service

    progress = AuditProgress(connected.store, FileArtifacts(str(tmp_path / "artifacts")),
                             policy=small(), clock=Clock())
    runner = service_runner(connected, progress, max_tasks=2)
    summary = runner.run(once=True)
    assert summary["completed_tasks"] == 2 and summary["stop_reason"] == "max_tasks_reached"
    statuses = [step["progress"]["status"] for step in summary["steps"] if step["action"] == "task"]
    assert statuses == ["observed", "window_closed"], "the baseline was taken before the first task"
    assert summary["progress"]["status"] == "window_closed" and summary["progress"]["window_executions"] == 2
    state = progress.state(connected.audit_id)
    assert state["baseline"]["executions"] == 0 and state["windows_completed"] == 1
    # The executions this run settled are the window's members, read from the durable task rows.
    assert progress.windows(connected.audit_id)[0]["executions"] == 2
    args = SimpleNamespace(audit_service_command="status", audit_id=connected.audit_id)
    view = audit_service.execute(connected.service, args)
    assert view["progress"]["observed"] is True and view["progress"]["windows_completed"] == 1
    assert view["progress"]["last_observation"]["status"] == "window_closed"
    assert view["progress"]["last_delta"]["semantic_total"] == 0
    assert view["progress"]["last_delta"]["distinct_ranges"] == 0 and view["progress"]["streak"] == 1
    assert view["progress"]["candidate"] is None and view["progress"]["last_verdict"] == NO_EVIDENCE
    assert view["last_progress"]["status"] == "window_closed" and view["completed_tasks"] == 2
    assert view["progress"]["metrics"]["semantic_paths"] == 0, "running produced no semantic credit"
    assert CANARY not in json.dumps(view)


def test_an_observation_failure_is_degraded_beside_an_unchanged_execution_result(connected, tmp_path):  # noqa: F811
    class Broken:
        """Injected fault: the observer itself fails."""

        def __init__(self):
            self.calls = 0

        def observe(self, audit_id, *, release_id, revision):
            self.calls += 1
            raise RuntimeError("fixture observer failure " + CANARY)

    observer = spool_observer(connected)
    broken = Broken()
    runner = service_runner(connected, broken, max_tasks=1, observer=observer)
    summary = runner.run(once=True)
    assert broken.calls == 2, "one baseline and one settlement observation"
    assert summary["completed_tasks"] == 1 and summary["stop_reason"] == "max_tasks_reached"
    assert summary["progress"]["status"] == "degraded" and summary["progress"]["error_type"] == "RuntimeError"
    assert summary["progress"]["unknown"] == "observer_failed"
    task = [step for step in summary["steps"] if step["action"] == "task"][-1]
    assert task["status"] == "succeeded" and task["progress"]["status"] == "degraded"
    with connected.store.transaction() as tx:
        assert [row for row in tx.scan(BUCKET_STATE)] == [] and [row for row in tx.scan(BUCKET_WINDOWS)] == []
        assert [row for row in tx.scan(BUCKET_INVESTIGATIONS)] == []
    events = [event for event in observer.spool.records()
              if event["event_type"] == "operations.audit_progress_observed"]
    assert len(events) == 2 and {e["outcome"] for e in events} == {"blocked"}
    assert events[0]["reason_code"] == "observer_failed" and events[0]["severity"] == "warning"
    assert CANARY not in json.dumps(events)


def test_the_production_wiring_gives_the_runner_a_real_observer_on_the_same_store(connected, tmp_path, monkeypatch):  # noqa: F811
    """`build_runner` is the production wiring; only the transport, executor and collector it builds
    are replaced here, because those need Redis, PostgreSQL and a host runtime."""
    from codex_harness import bootstrap
    from codex_harness.adapters import audit_service, bus, configuration

    monkeypatch.setattr(bootstrap, "build_executor", lambda service, observer=None: "executor-stand-in")
    monkeypatch.setattr(bootstrap, "build_collector", lambda store, observer=None: "collector-stand-in")
    monkeypatch.setattr(bootstrap, "redis_url", lambda: "redis://fixture/0")
    monkeypatch.setattr(bus, "RedisBus", lambda url: "bus-stand-in")
    monkeypatch.setattr(configuration, "runtime_dir", lambda: tmp_path)
    args = SimpleNamespace(audit_id=connected.audit_id, max_tasks=None, once=True)
    gate = {"revision": "audit", "release_id": "fixture-release", "partitions": 4}
    runner = audit_service.build_runner(connected.service, args, None, gate)
    assert isinstance(runner.progress, AuditProgress) and runner.progress.store is connected.store
    assert runner.progress.policy == validate_policy(packaged_policy())
    # It reads THIS audit through that wiring: a real baseline observation, no provider involved.
    observed = runner.progress.observe(connected.audit_id, release_id=gate["release_id"],
                                       revision=gate["revision"])
    assert observed["status"] == "baseline" and observed["audit_id"] == connected.audit_id


def test_the_progress_observations_are_declared_events_with_identifiers_and_codes(connected, tmp_path):  # noqa: F811
    from codex_harness.adapters.contracts import validate_observation
    from codex_harness.domain.observation import REGISTRY

    progress = AuditProgress(connected.store, FileArtifacts(str(tmp_path / "artifacts")),
                             policy=small(), clock=Clock())
    observer = spool_observer(connected)
    runner = service_runner(connected, progress, max_tasks=2, observer=observer)
    runner.run(once=True)
    events = [event for event in observer.spool.records()
              if event["event_type"] == "operations.audit_progress_observed"]
    assert len(events) == 3 and [e["outcome"] for e in events] == ["observed"] * 3
    for event in events:
        validate_observation(event)
        assert set(event["attributes"]) <= set(REGISTRY["operations.audit_progress_observed"])
    closed = events[-1]["attributes"]
    assert closed["status"] == "window_closed" and closed["verdict"] in {NO_EVIDENCE, LOW_YIELD}
    assert closed["window_executions"] == 2 and closed["semantic_delta"] == 0
    assert closed["candidate"] is None and closed["streak"] == 1
    assert observer.counters["refused"] == 0


def test_the_progress_facts_are_allow_listed_and_a_foreign_observation_is_never_a_zeus_code():
    from codex_harness.adapters import audit_service
    from codex_harness.domain.observation import REGISTRY, check_attributes

    facts = audit_service.progress_facts({
        "audit_id": AUDIT, "status": "window_closed", "epoch": "e" * 64, "verdict": LOW_YIELD,
        "window_index": 3, "new_executions": 2, "streak": 2, "candidate": "c" * 64,
        "candidate_created": True, "unknown": None,
        "window": {"executions": 2, "delta": {"semantic_total": 0, "distinct_ranges": 4}}})
    assert set(facts) == set(audit_service.PROGRESS_ATTRIBUTES)
    assert facts["semantic_delta"] == 0 and facts["ranges_delta"] == 4 and facts["streak"] == 2
    check_attributes("operations.audit_progress_observed", facts)
    assert set(facts) <= set(REGISTRY["operations.audit_progress_observed"])
    foreign = audit_service.progress_facts({"audit_id": AUDIT, "status": "totally_new",
                                            "verdict": "great", "epoch": "not an id " + CANARY,
                                            "streak": "many", "candidate": {"nested": 1},
                                            "unknown": "invented_reason", "window": "not a window"})
    assert foreign["status"] == "degraded" and foreign["verdict"] == "unknown"
    assert foreign["epoch"] is None and foreign["candidate"] is None and foreign["streak"] is None
    assert foreign["unknown"] == "unknown" and CANARY not in json.dumps(foreign)
    assert audit_service.progress_facts(None)["status"] == "degraded"
