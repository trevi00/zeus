"""Target driver: `research.threshold_reviews` on the target tree (S8 pilot 101: `research.application.threshold_reviews`, V22 R-tr1..R-tr4).

The API mirrors the reference driver's names over the target homes. M7's `Workflow` is the S5 composition's `WorkflowAndMessages`.
`ThresholdReviews` gets its two injected ports: coordination's `ExecutionRecovery` as `decision_validation` (R-tr1; wired with the
research audit binding and `ThresholdReviewRecords`, as the composition will) and coordination's EXISTING `DecisionOwnership` as
`decisions` (R-tr2). The ordinary claim is coordination's `claim_decision` with `ThresholdReviews.exhausted` as its
`threshold_exhausted` hook (R-tr4) and the owner id drawn as the next scripted id where M7's `decide_one` draws it. The scenario reads the
kernel's default clock where M7 read `utcnow`, and the kernel id source where M7's `envelope` drew a uuid; the harness's scripted clock and
ids (the composition's) reach them through `kernel.ids.SYSTEM_CLOCK` and `kernel.message.SYSTEM_IDS`. The import-time execution domain is
pinned as the reference run pinned it."""

import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

import s5_coordination_composition as composition  # noqa: E402
import s8_threshold_reviews  # noqa: E402
from codex_harness.coordination.application import execution_recovery, execution_time  # noqa: E402
from codex_harness.coordination.application.decision_claims import claim_decision  # noqa: E402
from codex_harness.coordination.application.decisions import DecisionOwnership  # noqa: E402
from codex_harness.intake.application import tickets  # noqa: E402
from codex_harness.kernel import ids, message  # noqa: E402
from codex_harness.kernel.ids import digest  # noqa: E402
from codex_harness.kernel.policy import POLICY  # noqa: E402
from codex_harness.research.application import audit_gate  # noqa: E402
from codex_harness.research.application import threshold_reviews as application  # noqa: E402
from codex_harness.storage.adapters.memory_store import MemoryStore  # noqa: E402

composition.CLOCK.start = composition.CLOCK.current = datetime(2026, 9, 22, tzinfo=timezone.utc)
ids.SYSTEM_CLOCK = composition.PORT
message.SYSTEM_IDS = composition.IDPORT
execution_time.DOMAIN = "00000000-0000-4000-8000-00000000a0d2"  # the reference run's pinned clock-domain identity


def recovery(store, org, artifacts):
    return execution_recovery.ExecutionRecovery(
        store, org, artifacts, audit_binding=audit_gate.binding, threshold_reviews=application.ThresholdReviewRecords(artifacts),
        clock=composition.PORT, ids=composition.IDPORT)


def reviews(store, org, artifacts):
    workflow = composition.WorkflowAndMessages(store)
    validation = recovery(store, org, artifacts)
    return application.ThresholdReviews(
        workflow, artifacts, decision_validation=validation,
        decisions=DecisionOwnership(workflow, validation, org, clock=composition.PORT, ids=composition.IDPORT))


def claim(store, org, artifacts, actor):
    owner = str(composition.IDS.uuid4())
    row = claim_decision(store, org, actor, owner, None, recovery=recovery(store, org, artifacts), ticket_binding=tickets.ticket_binding,
                         TicketSuperseded=tickets.TicketSuperseded, threshold_exhausted=application.ThresholdReviews.exhausted,
                         clock=composition.PORT, monotonic=composition.CLOCK.monotonic)
    return None if row is None else {**row, "_bucket": "decisions_pending"}


API = SimpleNamespace(
    MemoryStore=MemoryStore, organization=lambda: composition.ORG, digest=digest, max_attempts=POLICY.max_attempts, claim=claim,
    reviews=reviews, exhausted=application.ThresholdReviews.exhausted,
    records=lambda store, org, artifacts: application.ThresholdReviewRecords(artifacts), advance=composition.CLOCK.advance)

if __name__ == "__main__":
    driver.finish("target", "research.threshold_reviews", s8_threshold_reviews.run(API))
