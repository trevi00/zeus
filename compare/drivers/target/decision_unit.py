"""Target driver: the decision/release/outbox atomic unit on the target tree (REBUILD-DESIGN-v2 §2.9, F2).

Derived from `drivers/reference/decision_unit.py` by the substitutions below; the cases, the recorder, the
negative controls and the reported result are the reference's. The target is composed by
`common/s4_target_decisions.Composition` (coordination claim -> review ReviewDecisions, the fixture verdict behind
VerdictInvoker). Ids and clocks are the scripted sources, injected, never patched in. The fence probe wraps the
target Workflow._owned that DecisionOwnership.owned delegates to (the same call sites as M7). The split-commit
control patches the target Releases.propose, as the reference patches M7's.

The reference docstring follows.

Scenario family `effects.decision_unit` (M7 `MemoryStore`) and, when `ZEUS_REBUILD_PG_DSN` names a
labelled disposable PostgreSQL, `effects.decision_unit.pg` (M7 `PostgresStore`, one fresh schema per
case, migrated by M7's own migrator; the actual durable `documents` rows are read back per case).
Runs M7 `Executor.decide_one` -> `_commit_decision` with a fixture `_run` (no provider), a fake clock
and deterministic ids.
Discriminators (a)-(d) and the recorder's negative controls:
  a  failure after release propose/review, before decisions_pending/outbox -> atomic rollback
  b  stale lease -> fence fails, nothing of the unit commits
  c  same-key replay -> no second effect, no new authority write
  d  the provider effect occurs at depth 0
  controls: split commit (propose opens its own transaction), fence ignored, fabricated
  completion, effect inside a unit -> each must be flagged by the recorder.
"""

import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

from types import SimpleNamespace  # noqa: E402

import determinism  # noqa: E402
import masks  # noqa: E402
import recorder as rec  # noqa: E402
from codex_harness.coordination.application import execution_time  # noqa: E402
from codex_harness.kernel.message import envelope  # noqa: E402
from codex_harness.observation.application.observations import ReconciliationRequired  # noqa: E402
from codex_harness.routing.adapters.organization_source import packaged_organization  # noqa: E402
from codex_harness.storage.adapters.memory_store import MemoryStore  # noqa: E402
from codex_harness.storage.adapters.postgres_store import PostgresStore  # noqa: E402
from s1_target import PortClock, PortIds  # noqa: E402
from s4_decision_composition import Composition  # noqa: E402

CLOCK, IDS = determinism.FakeClock(), determinism.FakeIds()
PORT, PIDS = PortClock(CLOCK), PortIds(IDS)
execution_time.DOMAIN = "00000000-0000-4000-8000-00000000d0d0"  # the reference's clock-domain identity
ORG = packaged_organization()
AUTHORITY = {"releases", "release_queue", "hooks", "improvement_loops", "incidents"}
PG_DSN = os.environ.get("ZEUS_REBUILD_PG_DSN")
SCENARIO = "effects.decision_unit.pg" if PG_DSN else "effects.decision_unit"


class Backend:
    """MemoryStore, or a fresh schema on the disposable PostgreSQL with its durable rows readable."""

    def __init__(self, name: str):
        self.schema = None
        if not PG_DSN:
            self.store = MemoryStore()
            return
        import psycopg
        from psycopg.conninfo import make_conninfo

        self.psycopg = psycopg
        self.schema = "s0_" + name
        with psycopg.connect(PG_DSN, autocommit=True) as conn:
            conn.execute(f'DROP SCHEMA IF EXISTS "{self.schema}" CASCADE')
            conn.execute(f'CREATE SCHEMA "{self.schema}"')
        self.dsn = make_conninfo(PG_DSN, options=f"-c search_path={self.schema},public")
        self.store = PostgresStore(self.dsn, clock=PORT)
        self.store.migrate()

    def rows(self) -> list[tuple[str, str, str]]:
        """(bucket, key, status) of every durable document row, read from the database itself."""
        if self.schema is None:
            return sorted((b, k, (v or {}).get("status") or "") for (b, k), v in self.store.data.items())
        with self.psycopg.connect(self.dsn) as conn:
            return sorted((b, k, s or "") for b, k, s in conn.execute(
                "SELECT bucket, id, body->>'status' FROM documents").fetchall())

    def drop(self) -> None:
        if self.schema is not None:
            with self.psycopg.connect(PG_DSN, autocommit=True) as conn:
                conn.execute(f'DROP SCHEMA "{self.schema}" CASCADE')


def completion(e):
    return e["kind"] == "write" and e["bucket"] == "decisions_pending" and e["status"] == "succeeded"


def intent(e):
    return e["kind"] == "write" and e["bucket"] == "decisions_pending" and e["status"] == "running"


class Injected(RuntimeError):
    pass


def case(root: Path, name: str, phase: str, actor: str, *, failure: str = "none",
         control: str = "none", replay: bool = False, outcome: str = "accepted") -> dict:
    CLOCK.reset()
    IDS.reset()
    clock = CLOCK
    tmp = root / name
    tmp.mkdir(parents=True)
    masker = masks.Masker(SCENARIO)
    backend = Backend(name)
    store = rec.RecordingStore(backend.store, rec.Recorder(masker.apply))
    recorder = store.recorder
    git = SimpleNamespace(repository=tmp, inspect=lambda *a: {},
                          review_workspace=lambda *a: str(tmp),
                          _git=lambda *a, **k: "" if a[0] == "status" else "revision")
    executor = Composition(store, ORG, git, clock=PORT, ids=PIDS, monotonic=CLOCK.monotonic)
    # S11 AU-REC-6b: the audit rows of a reconciliation block carry the observer's host and pid
    executor.observer.source.update(host="fixture-host", pid=1)
    candidate = {"revision": "revision", "base": "base", "tree": "tree",
                 "author": "worker:implementation"}
    data = {"candidate": candidate, "source_actor": "worker:implementation",
            "occurrence_id": "occurrence", "source_task_id": "task", "evidence_ref": "fixture:error"}
    if phase == "review_conductor":
        release = executor.releases.propose(candidate, {"checks": ["tests"]})
        executor.releases.review(release["id"], "lead:improvement", "revision", True, "fixture:lead")
        data["release_id"] = release["id"]
    message = envelope("task.assign", "lead:improvement", "worker:implementation", "implement",
                       {}, "correlation", clock=PORT, ids=PIDS)
    with store.transaction() as tx:
        tx.put("decisions_pending", "decision", {"id": "decision", "actor": actor, "phase": phase,
               "input": data, "message": message, "status": "pending", "attempt": 0})
    setup_events = len(recorder.events)
    rows_before = set(backend.rows())
    clock.advance(1)

    def run(*args, **kwargs):
        if control == "effect_in_unit":
            with store.transaction():
                recorder.effect("provider_call")
        elif control != "fabricated_completion":
            recorder.effect("provider_call")
        if failure == "stale_lease":
            with store.transaction() as tx:
                row = tx.get("decisions_pending", "decision")
                row.update(owner="replacement", lease_owner="replacement",
                           generation=row["generation"] + 1)
                tx.put("decisions_pending", "decision", row)
        if outcome == "reconciliation_required":  # S11 AU-REC-6b: a pending termination (INV-OBSERVATION-001)
            raise ReconciliationRequired("decision", [{"record_id": "record"}])
        # S11 AU-REC-4: the run result that reaches Executor.decide_one blocks #2 / #3 (INV-RELEASE-001)
        return {"accepted": outcome == "accepted", "confirmed": True, "root_cause": "cause", "scope": "scope",
                "execution_ref": "fixture:review", "reason": "fixture",
                **({outcome: True} if outcome != "accepted" else {})}

    executor.verdict = run
    owned = executor.workflow._owned

    def fenced(tx, task, *args, **kwargs):
        try:
            current = owned(tx, task, *args, **kwargs)
        except Exception:
            recorder.fence("lease", False)
            if control == "fence_ignored":
                return tx.get(task.get("_bucket", "tasks"), task["id"])
            raise
        recorder.fence("lease", True)
        return current

    executor.workflow._owned = fenced
    if control == "split_commit":
        propose = executor.releases.propose
        executor.releases.propose = lambda c, p, transaction=None: propose(c, p)
    if failure in {"before_decision", "at_outcome"}:
        write = recorder.write
        failing = "succeeded" if failure == "before_decision" else (
            "blocked" if outcome == "reconciliation_required" else outcome)

        def failing_write(bucket, key, body):
            write(bucket, key, body)
            if bucket == "decisions_pending" and isinstance(body, dict) \
                    and body.get("status") == failing:
                raise Injected("fixture failure after release effects, before decision/outbox")

        recorder.write = failing_write
        try:
            executor.decide_one(actor)
        except Injected:  # S11 AU-REC-6b: _block_for_reconciliation catches only ContractError, so the failure escapes
            if outcome != "reconciliation_required":
                raise
        finally:
            del recorder.write
    else:
        executor.decide_one(actor)
    if replay:
        clock.advance(1)
        executor.decide_one(actor)
    events = recorder.events[setup_events:]
    durable = recorder.durable_writes(setup_events)
    with store.transaction() as tx:
        final = tx.get("decisions_pending", "decision")
        outbox_types = sorted(r["message"]["type"] for r in tx.scan("outbox"))
    rows_after = set(backend.rows())
    backend.drop()
    changed = sorted({(b, st) for b, _, st in rows_after - rows_before})
    return {
        "durable_rows_changed": [list(r) for r in changed],
        "durable_authority_rows": sorted({b for b, _ in changed if b in AUTHORITY}),
        "verdict": recorder.classify(AUTHORITY, completion, setup_events),
        "violations": sorted({v["kind"] for v in recorder.violations}),
        "effect_protocol": sorted(set(recorder.effect_protocol(intent, completion, setup_events))),
        "effects": [{"name": e["name"], "depth": e["depth"]} for e in events
                    if e["kind"] == "effect"],
        "fences": [e["ok"] for e in events if e["kind"] == "fence"],
        "durable_authority_writes": sorted({(e["bucket"], e["status"] or "") for e in durable
                                            if e["bucket"] in AUTHORITY}),
        "decision_status": final["status"],
        "outbox_types": outbox_types,
        "trace": [{k: v for k, v in e.items() if k not in {"seq", "digest", "key"}} for e in events],
        "trace_digests": [e.get("digest") for e in events if e["kind"] == "write"],
    }


def main() -> None:
    cases = {
        "success_review_lead": dict(phase="review_lead", actor="lead:improvement"),
        "success_review_conductor": dict(phase="review_conductor", actor="conductor"),
        "a_failure_before_decision_review_lead": dict(phase="review_lead", actor="lead:improvement",
                                                      failure="before_decision"),
        "a_failure_before_decision_review_conductor": dict(phase="review_conductor", actor="conductor",
                                                           failure="before_decision"),
        "b_stale_lease": dict(phase="review_lead", actor="lead:improvement", failure="stale_lease"),
        "c_same_key_replay": dict(phase="review_lead", actor="lead:improvement", replay=True),
        "inspection_blocked_review_lead": dict(phase="review_lead", actor="lead:improvement",
                                               outcome="inspection_blocked"),
        "a_failure_at_outcome_inspection_blocked": dict(phase="review_lead", actor="lead:improvement",
                                                        failure="at_outcome", outcome="inspection_blocked"),
        "b_stale_lease_inspection_blocked": dict(phase="review_lead", actor="lead:improvement",
                                                 failure="stale_lease", outcome="inspection_blocked"),
        "c_same_key_replay_inspection_blocked": dict(phase="review_lead", actor="lead:improvement",
                                                     replay=True, outcome="inspection_blocked"),
        "blocked_review_lead": dict(phase="review_lead", actor="lead:improvement", outcome="blocked"),
        "a_failure_at_outcome_blocked": dict(phase="review_lead", actor="lead:improvement",
                                             failure="at_outcome", outcome="blocked"),
        "b_stale_lease_blocked": dict(phase="review_lead", actor="lead:improvement",
                                      failure="stale_lease", outcome="blocked"),
        "c_same_key_replay_blocked": dict(phase="review_lead", actor="lead:improvement",
                                          replay=True, outcome="blocked"),
        "reconciliation_required_review_lead": dict(phase="review_lead", actor="lead:improvement",
                                                    outcome="reconciliation_required"),
        "a_failure_at_outcome_reconciliation_required": dict(
            phase="review_lead", actor="lead:improvement", failure="at_outcome", outcome="reconciliation_required"),
        "b_stale_lease_reconciliation_required": dict(
            phase="review_lead", actor="lead:improvement", failure="stale_lease", outcome="reconciliation_required"),
        "c_same_key_replay_reconciliation_required": dict(
            phase="review_lead", actor="lead:improvement", replay=True, outcome="reconciliation_required"),
        "control_split_commit": dict(phase="review_lead", actor="lead:improvement",
                                     failure="before_decision", control="split_commit"),
        "control_fence_ignored": dict(phase="review_lead", actor="lead:improvement",
                                      failure="stale_lease", control="fence_ignored"),
        "control_fabricated_completion": dict(phase="review_lead", actor="lead:improvement",
                                              control="fabricated_completion"),
        "control_effect_in_unit": dict(phase="review_lead", actor="lead:improvement",
                                       control="effect_in_unit"),
    }
    with tempfile.TemporaryDirectory(prefix="zeus-s0-decision-") as raw:
        out = {name: case(Path(raw), name, **kw) for name, kw in cases.items()}
    driver.finish("target", SCENARIO, out)


if __name__ == "__main__":
    main()
