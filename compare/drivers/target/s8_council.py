"""Target driver: `research.council` on the target tree (S8 pilot 78: `coordination.application.council`, V12).

The API mirrors the reference driver's names over the target homes, wired as `s8_autonomous`'s target driver wires the base ports:
M7's `Harness` is the S5 `Service`, M7's `Workflow` its `WorkflowAndMessages`, and the council run (like the plain autonomous run the
scenario also builds) gets its four injected ports (R-c1): research's `DebateSessions` factory, evidence's `EvidenceRecords`,
knowledge's promotion module and the S5 `Operation` composition (as `s5_operation.py` builds it, plus the observer and research's
design gate). `EvidenceUnavailable` and `ReadOnlySnapshot`/`SnapshotUnavailable` are the scenario's LABELLED stand-ins for
`adapters/autonomous_evidence` and `adapters/council_snapshot` (later families): the snapshot stand-in is M7's `ReadOnlySnapshot`
over the same research domain functions, minus the `psycopg` default connect (the scenario always injects its fake `connect`).
The artifact store, executor, evidence source, clock and buses are the scenario's doubles."""

import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

import s5_coordination_composition as composition  # noqa: E402
import s8_council  # noqa: E402
from codex_harness.coordination.application import autonomous as base_run  # noqa: E402
from codex_harness.coordination.application import council as application  # noqa: E402
from codex_harness.coordination.application.operation import Operation  # noqa: E402
from codex_harness.evidence.application.inspections import EvidenceRecords  # noqa: E402
from codex_harness.kernel import ids, message  # noqa: E402
from codex_harness.kernel.errors import ContractError  # noqa: E402
from codex_harness.kernel.ids import canonical, digest, utcnow  # noqa: E402
from codex_harness.kernel.message import envelope  # noqa: E402
from codex_harness.knowledge.application import promotion as knowledge_promotion  # noqa: E402
from codex_harness.research.application import dge  # noqa: E402
from codex_harness.research.domain import autonomous as domain  # noqa: E402
from codex_harness.research.domain.council import (  # noqa: E402
    profile,
    snapshot_envelope,
    snapshot_records,
    validate_council_manifest,
    validate_current_state,
)
from codex_harness.routing.adapters.provider_policy import packaged_policy  # noqa: E402
from codex_harness.storage.adapters.memory_store import MemoryStore  # noqa: E402
from codex_harness.storage.ports import MessageDeliveryError  # noqa: E402

composition.CLOCK.start = composition.CLOCK.current = datetime(2026, 9, 22, tzinfo=timezone.utc)
ids.SYSTEM_CLOCK = composition.PORT
message.SYSTEM_IDS = composition.IDPORT
EVIDENCE_RECORDS = EvidenceRecords()
# The module (and its base class) read `time.monotonic()` for recorded durations: the driver substitutes the base module's `time`
# name with the scripted clock's monotonic reading (the target's standard library is never patched), as `s8_autonomous` does.
base_run.time = SimpleNamespace(monotonic=composition.CLOCK.monotonic)

BEGIN = "BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY"
IDENTITY = "SELECT current_database(), current_schema(), current_setting('server_version')"
SELECT = ("SELECT s.bucket, s.id, d.body FROM unnest(%s::text[], %s::text[]) AS s(bucket, id) "
          "JOIN documents d ON d.bucket = s.bucket AND d.id = s.id")


class EvidenceUnavailable(ContractError):
    """LABELLED stand-in for `adapters.autonomous_evidence.EvidenceUnavailable` (the adapter is a later family)."""

    def __init__(self, reason_code: str):
        super().__init__("execution evidence " + reason_code)
        self.reason_code = reason_code


class SnapshotUnavailable(ContractError):
    """LABELLED stand-in for `adapters.council_snapshot.SnapshotUnavailable` (the adapter is a later family)."""

    def __init__(self, reason_code: str):
        super().__init__("council snapshot " + reason_code)
        self.reason_code = reason_code


class ReadOnlySnapshot:
    """LABELLED stand-in for `adapters.council_snapshot.ReadOnlySnapshot`: M7's statements and error handling over the injected
    `connect` (no `psycopg`; the scenario always injects it)."""

    def __init__(self, dsn: str, *, connect=None, clock=utcnow, connect_timeout: int = 5, statement_timeout_ms: int = 5000):
        if type(connect_timeout) is not int or connect_timeout <= 0 or type(statement_timeout_ms) is not int or statement_timeout_ms <= 0:
            raise ContractError("Snapshot timeouts must be positive integers")
        self.dsn, self.connect, self.clock = dsn, connect, clock
        self.connect_timeout, self.statement_timeout_ms = connect_timeout, statement_timeout_ms

    @contextmanager
    def _session(self):
        try:
            conn = self.connect(self.dsn, connect_timeout=self.connect_timeout, autocommit=True)
        except Exception:
            conn = None
        if conn is None:
            raise SnapshotUnavailable("snapshot_unavailable")
        with conn:
            conn.execute(BEGIN)
            try:
                conn.execute("SET LOCAL statement_timeout = '%dms'" % self.statement_timeout_ms)
                yield conn
            finally:
                conn.execute("ROLLBACK")

    def observe(self, selection: list, *, topic: str, run_id: str, base_revision: str, max_age_seconds: int) -> dict:
        records = validate_current_state({"records": selection, "max_age_seconds": max_age_seconds})["records"]
        failed = False
        try:
            with self._session() as conn:
                identity = conn.execute(IDENTITY).fetchone()
                rows = conn.execute(SELECT, ([r["bucket"] for r in records], [r["id"] for r in records])).fetchall()
                observed_at = self.clock()
        except Exception:
            failed = True
        if failed:
            raise SnapshotUnavailable("snapshot_unavailable")
        if not (isinstance(identity, (tuple, list)) and len(identity) == 3 and all(isinstance(v, str) for v in identity)):
            raise SnapshotUnavailable("snapshot_unavailable")
        bodies = {(bucket, key): body for bucket, key, body in rows}
        endpoint = digest({"database": identity[0], "schema": identity[1], "server_version": identity[2]})
        return snapshot_envelope(topic=topic, run_id=run_id, base_revision=base_revision, selection=records,
                                 records=snapshot_records(records, bodies), database_identity=endpoint,
                                 observed_at=observed_at, max_age_seconds=max_age_seconds)


def _ports(service):
    def operation_factory(executor, bus, workflow, budget, collector, observer=None):
        return Operation(service.store, service.org, flusher=service.flusher, incidents=service.record_incident,
                         executor=executor, bus=bus, workflow=workflow, budget=budget, collector=collector, observer=observer,
                         design_gate=SimpleNamespace(check=dge.design_gate), evidence_records=EVIDENCE_RECORDS,
                         clock=composition.PORT, ids=composition.IDPORT)

    return dict(sessions_factory=dge.DebateSessions, evidence_records=EVIDENCE_RECORDS, promotion=knowledge_promotion,
                operation_factory=operation_factory)


class _AnyRun(type):
    """LABELLED. The scenario asks `isinstance(run, api.AutonomousRun)` of a `CouncilRun`; the port-supplying subclass below is a
    different class from the real `AutonomousRun`, so the check is answered against the module's real class."""

    def __instancecheck__(cls, obj):
        return isinstance(obj, base_run.AutonomousRun)


class AutonomousRun(base_run.AutonomousRun, metaclass=_AnyRun):
    def __init__(self, service, *args, **kwargs):
        super().__init__(service, *args, **_ports(service), **kwargs)


class CouncilRun(application.CouncilRun):
    def __init__(self, service, *args, **kwargs):
        super().__init__(service, *args, **_ports(service), **kwargs)


API = SimpleNamespace(
    MemoryStore=MemoryStore, CouncilRun=CouncilRun, AutonomousRun=AutonomousRun,
    AutonomousRefused=base_run.AutonomousRefused, SNAPSHOT_SOURCE=application.SNAPSHOT_SOURCE,
    SNAPSHOT_REFUSALS=application.SNAPSHOT_REFUSALS, PROPOSAL_SECTION=application.PROPOSAL_SECTION,
    CONSUMER_OVERFLOW=application.CONSUMER_OVERFLOW, CONSUMER_REFUSAL_OUTCOMES=application.CONSUMER_REFUSAL_OUTCOMES,
    ReadOnlySnapshot=ReadOnlySnapshot, SnapshotUnavailable=SnapshotUnavailable,
    Harness=lambda store, org: composition.Service(store), Workflow=lambda store, org: composition.WorkflowAndMessages(store),
    organization=lambda: composition.ORG, packaged_policy=packaged_policy, EvidenceUnavailable=EvidenceUnavailable,
    AutonomousManifestError=domain.AutonomousManifestError, validate_autonomous_manifest=domain.validate_autonomous_manifest,
    validate_council_manifest=validate_council_manifest, profile=profile, ContractError=ContractError, canonical=canonical,
    envelope=envelope, MessageDeliveryError=MessageDeliveryError)

if __name__ == "__main__":
    driver.finish("target", "research.council", s8_council.run(API))
