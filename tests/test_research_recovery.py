"""Research dispatch transport recovery (research-dispatch-recovery-001, SPEC "Research dispatch
transport recovery").

A council that failed with `publication_incomplete` before its first role execution strands its
investigation: the dispatch claim is keyed by investigation id and kept. The owner may authorize ONE
replacement through a NEW registered program; the failed run, dispatch, cycle and outbox record stay
history, the unsent assignment is fenced through the existing outbox quarantine, and the scoped
receipt can only name the replacement.

REAL: MemoryStore transactions, the Portfolio reconciler, `ResearchProgram`, `ProgramRunner` over a
real temporary Git repository, and - for the failed council - the real `CouncilRun` with the real
organization, workflow, message contract and outbox relay. LABELLED stand-ins: the transport fault
(every publish raises `MessageDeliveryError`), the transport proof (`FakeTransport`), the accepted
replacement council (`FakeCouncil` writes its run row) and the clock. Nothing here is a Redis, model,
provider or production-store observation; PostgreSQL coverage runs only with HARNESS_INTEGRATION=1.
"""
from __future__ import annotations

import json
import threading
from copy import deepcopy
from pathlib import Path

import pytest
from test_research_investigations import INVESTIGATION, SOURCE, portfolio
from test_research_program import POLICY, build
from test_research_program_fixtures import CANARY, FakeCouncil, config

from codex_harness.adapters.contracts import validate_message
from codex_harness.adapters.providers import packaged_policy
from codex_harness.adapters.research_program import TransportProbe
from codex_harness.adapters.research_program_cli import recover as recover_cli
from codex_harness.adapters.store import MemoryStore
from codex_harness.application.council import CouncilRun
from codex_harness.application.outbox import relay
from codex_harness.application.portfolio import Portfolio
from codex_harness.application.research_program import (
    BUCKET_CANDIDATES,
    BUCKET_CYCLES,
    BUCKET_DISPATCHES,
    BUCKET_PROGRAMS,
    BUCKET_RECOVERIES,
    ResearchProgram,
)
from codex_harness.application.service import Harness
from codex_harness.application.workflow import Workflow
from codex_harness.bootstrap import organization
from codex_harness.domain.council import validate_any_manifest
from codex_harness.domain.model import ContractError, digest
from codex_harness.domain.research_investigations import replacement_dispatch_id
from codex_harness.domain.research_program import ProgramRefused, config_digest, validate_config
from codex_harness.ports import MessageDeliveryError

REPLACEMENT = INVESTIGATION + ".recovery-1"


class Unreachable:
    """LABELLED stand-in for every port the failed council must NEVER reach: any use fails the test."""

    def __getattr__(self, name):
        raise AssertionError("pre-provider failure touched " + name)


IDENTITY = {"schema": "urn:test:transport:1", "storage": "token-a"}   # LABELLED fixture transport identity


class UnreachableBus:
    """LABELLED injected transport fault: the real message contract validates, the attempt binds the
    fixture identity, then the publish raises the adapter's delivery error, exactly what a Redis
    timeout produces. `bound=False` is the legacy bus that has no identity at all."""

    def __init__(self, bound=True):
        self.attempts, self.bound = 0, bound

    def __getattr__(self, name):
        if name == "transport" and self.bound:
            return lambda: dict(IDENTITY)
        raise AttributeError(name)

    @staticmethod
    def validate(message):
        return validate_message(message)

    def publish(self, message, transport=None):
        self.attempts += 1
        raise MessageDeliveryError("TimeoutError")


class RecordingBus:
    """LABELLED healthy transport for the global relay replay: records what it would publish."""

    def __init__(self):
        self.published = []

    @staticmethod
    def validate(message):
        return validate_message(message)

    def publish(self, message):
        self.published.append(message)
        return str(len(self.published)) + "-0"


class PublicationFailingCouncil:
    """The REAL CouncilRun on the shared store with an unreachable transport: it claims the run row,
    writes the researcher assignment to the outbox, fails the correlation-scoped publication and ends
    `failed:publication_incomplete` before any reservation, task or provider start."""

    def __init__(self, store, bus=None):
        self.store, self.bus, self.receipts = store, bus or UnreachableBus(), []

    def __call__(self, service, args):
        manifest = validate_any_manifest(json.loads(Path(args.file).read_text(encoding="utf-8")), packaged_policy())
        harness = Harness(self.store, organization())
        never = Unreachable()
        run = CouncilRun(harness, executor=never, bus=self.bus, workflow=Workflow(self.store, harness.org),
                         budget=never, evidence=never, snapshot=never, artifacts=never)
        receipt = run.run(manifest, {"repository": "fixture"}, {"path": "docs/GOAL.md", "sha256": "0" * 64})
        self.receipts.append(receipt)
        return receipt


class FakeTransport:
    """LABELLED transport proof: `present` says the message is in the stream, `error` that the bus is
    unreachable, `identity`/`after` the bus identity read before/after the stream read. Records each
    inspected (recipient, message id)."""

    def __init__(self, present=False, error=None, identity=IDENTITY, after=None):
        self.present, self.error, self.calls = present, error, []
        self.identity, self.after = identity, identity if after is None else after

    def inspect(self, recipient, message_id):
        self.calls.append((recipient, message_id))
        if self.error is not None:
            raise self.error
        return {"before": self.identity, "absent": not self.present, "after": self.after}


def failed_world(tmp_path, council=PublicationFailingCouncil, store=None):
    """rp-001 claims the investigation and its council (by default the REAL one, failing before
    provider entry) records its outcome. `council(store)` builds the council on the shared store."""
    store = store or MemoryStore()
    portfolio(store)
    env = build(tmp_path, store=store)
    env.runner.council = council(store)
    cfg = validate_config(config(env.head, investigation_source=dict(SOURCE)), POLICY)
    env.programs.register(cfg, env.identity, [])
    env.programs.resume("rp-001")
    tick = env.runner.tick("rp-001")
    assert tick["investigation"] == INVESTIGATION
    return env, tick


def replacement(env, program_id="rp-002", **overrides):
    """A NEW owner-authorized program with the same authority; registered paused, never ticked."""
    cfg = validate_config(config(env.head, id=program_id, investigation_source=dict(SOURCE), **overrides), POLICY)
    env.programs.register(cfg, env.identity, [])
    return cfg, config_digest(cfg, env.identity)


def request(env, config_sha256, program_id="rp-002", **failed):
    with env.store.transaction() as tx:
        dispatch = tx.get(BUCKET_DISPATCHES, INVESTIGATION)
    pinned = {k: dispatch[k] for k in ("program", "cycle", "run_id", "manifest_sha256", "snapshot_sha256")}
    return {"schema": "urn:zeus:research-dispatch-recovery:1", "investigation": INVESTIGATION,
            "failed": {**pinned, **failed}, "replacement": {"program": program_id, "config_sha256": config_sha256}}


def history(store) -> dict:
    """Every record of the failed attempt that must stay exactly as it was."""
    with store.transaction() as tx:
        run = tx.get("autonomous_runs", "rp-001.c001")
        outbox = [o for o in tx.scan("outbox") if o["message"]["correlation_id"] == "autonomous:rp-001.c001"]
        return deepcopy({"dispatch": tx.get(BUCKET_DISPATCHES, INVESTIGATION), "run": run,
                         "cycle": tx.get(BUCKET_CYCLES, "rp-001:001"), "outbox": outbox,
                         "attempts": sorted(tx.scan("outbox_attempts"), key=lambda a: a["id"]),
                         "program": tx.get(BUCKET_PROGRAMS, "rp-001"),
                         "candidates": [c for c in tx.scan(BUCKET_CANDIDATES) if c["program"] == "rp-001"]})


def replacement_runner(env, status="accepted"):
    """The existing runner for the replacement program on the SAME store and repository."""
    runner = build(env.root.parent, store=env.store, root=env.root, head=env.head).runner
    runner.council = FakeCouncil(env.store, status=status)
    return runner


def refused(call, *args) -> str:
    with pytest.raises(ProgramRefused) as info:
        call(*args)
    assert CANARY not in str(info.value)
    return info.value.reason_code


# ----- the real pre-provider failure --------------------------------------------------------------------
def test_the_fixture_is_a_real_pre_provider_publication_failure(tmp_path):
    env, tick = failed_world(tmp_path)
    assert tick["result"] == "failed" and tick["reason_code"] == "publication_incomplete"
    assert env.runner.council.bus.attempts == 1
    with env.store.transaction() as tx:
        run = tx.get("autonomous_runs", "rp-001.c001")
        [outbox] = tx.scan("outbox")
        assert run["status"] == "failed" and run["stage"] == "research" and run["reason_code"] == "publication_incomplete"
        assert run["starts"] == {"reserved": 0, "settled": 0, "slots": []} and run["roles"] == {}
        assert outbox["sent"] is False and tx.scan("tasks") == [] and tx.scan("invocation_reservations") == []
        assert [a["status"] for a in tx.scan("outbox_attempts")] == ["retry"]
        dispatch = tx.get(BUCKET_DISPATCHES, INVESTIGATION)
        assert dispatch["result"] == "failed" and dispatch["result_reason"] == "publication_incomplete"
        assert tx.get(BUCKET_PROGRAMS, "rp-001")["state"] == "blocked"
    assert refused(env.programs.resume, "rp-001") == "program_blocked", "the only resume stays refused"


# ----- the complete path -------------------------------------------------------------------------------
def test_one_owner_request_fences_the_old_assignment_and_one_replacement_is_claimed_and_accepted(tmp_path):
    env, _ = failed_world(tmp_path)
    before = history(env.store)
    _, sha = replacement(env)
    transport = FakeTransport()
    result = env.programs.recover_dispatch(request(env, sha), transport)
    assert result["recovered"] is True and result["cached"] is False and result["state"] == "authorized"
    message_id = before["outbox"][0]["message"]["message_id"]
    assert transport.calls == [("lead:researcher", message_id)]
    assert result["replacement"] == {"program": "rp-002", "config_sha256": sha, "dispatch": REPLACEMENT, "cycle": None}
    with env.store.transaction() as tx:
        fence = tx.get("outbox_delivery", message_id)
        assert fence["status"] == "quarantined" and fence["attempts"] == 1
        [kept] = tx.scan("outbox_quarantine")
        assert kept["reason"] == "ResearchDispatchSuperseded" and kept["source"] == before["outbox"][0]
    assert history(env.store) == before, "run, dispatch, cycle, outbox item and attempts are untouched"

    # The global relay after the owner fixed the transport: the fenced assignment is never published.
    bus = RecordingBus()
    counted = relay(env.store, organization(), bus)
    assert bus.published == [] and counted["quarantined_existing"] == 1 and counted["published"] == 0

    # Read-only status names the failed original and the pending replacement; it schedules nothing.
    views = {d["id"]: d for d in env.programs.dispatches()}
    assert set(views) == {INVESTIGATION} and views[INVESTIGATION]["current"] is False
    assert env.programs.status("rp-001")["recoveries"][0]["state"] == "authorized"
    assert env.programs.status("rp-002")["state"] == "paused" and history(env.store) == before

    env.programs.resume("rp-002")
    runner = replacement_runner(env)
    tick = runner.tick("rp-002")
    assert tick["investigation"] == INVESTIGATION and tick["result"] == "accepted" and tick["run_id"] == "rp-002.c001"
    views = {d["id"]: d for d in env.programs.dispatches()}
    assert set(views) == {INVESTIGATION, REPLACEMENT}
    old, new = views[INVESTIGATION], views[REPLACEMENT]
    assert old["current"] is False and old["result"] == "failed" and old["program"] == "rp-001"
    assert new["current"] is True and new["result"] == "accepted" and new["program"] == "rp-002"
    assert new["run_id"] == "rp-002.c001" and new["recovery"] == INVESTIGATION
    assert new["supersedes"] == {"dispatch": INVESTIGATION, **{k: before["dispatch"][k] for k in
                                                               ("program", "cycle", "run_id", "manifest_sha256",
                                                                "snapshot_sha256")}}
    with env.store.transaction() as tx:
        lineage = tx.get(BUCKET_RECOVERIES, INVESTIGATION)
    assert lineage["state"] == "claimed" and lineage["replacement"]["cycle"] == "rp-002:001"
    assert history(env.store) == before, "the replacement never rewrote the failed history"
    status = env.programs.status("rp-002")
    assert status["investigations"]["accepted"] == 1 and status["adoptions"]["dispatched"] == 1
    assert env.programs.status("rp-001")["investigations"]["failed"] == 1

    # Replays: the identical request is cached; no second replacement, no second council.
    again = env.programs.recover_dispatch(request(env, sha), FakeTransport(error=AssertionError("not read")))
    assert again["cached"] is True and again["state"] == "claimed"
    assert len(env.programs.dispatches()) == 2 and len(runner.council.manifests) == 1


# ----- refusals over the real records ------------------------------------------------------------------------
@pytest.mark.parametrize("status, reason", [("accepted", "recovery_dispatch_not_failed"),
                                            ("rejected", "recovery_dispatch_not_failed"),
                                            ("failed", "recovery_not_pre_provider")])
def test_accepted_rejected_or_other_failed_councils_are_never_recoverable(tmp_path, status, reason):
    env, _ = failed_world(tmp_path, council=lambda store: FakeCouncil(store, status=status))
    _, sha = replacement(env)
    assert refused(env.programs.recover_dispatch, request(env, sha), FakeTransport()) == reason
    assert _untouched(env)


def _untouched(env) -> bool:
    """A refused request writes nothing: no lineage row, no fence."""
    with env.store.transaction() as tx:
        return tx.scan(BUCKET_RECOVERIES) == [] and tx.scan("outbox_quarantine") == []


def _put(bucket, key, body):
    def change(env, message_id):
        with env.store.transaction() as tx:
            tx.put(bucket, key.replace("{id}", message_id), {**body, "task_id": message_id} if "task_id" in body else body)
    return change


def _later_publication(env, message_id):
    relay(env.store, organization(), RecordingBus())   # the global relay delivered it after the failure


def _in_flight(env, message_id):
    with env.store.transaction() as tx:   # LABELLED injected fault: a publisher crashed mid-publish
        tx.put("outbox_attempts", "attempt-crashed", {"id": "attempt-crashed", "outbox_id": message_id,
                                                      "status": "started", "number": 2})


def _provider_slot(env, message_id):
    with env.store.transaction() as tx:   # LABELLED injected fault: the run row reports a reserved start
        run = tx.get("autonomous_runs", "rp-001.c001")
        run["starts"] = {"reserved": 1, "settled": 0, "slots": [{"id": "res-x", "settled": False}]}
        tx.put("autonomous_runs", run["id"], run)


def _disposition(env, message_id):
    from test_research_investigations import DEFINITIONS
    Portfolio(env.store, DEFINITIONS).disposition(INVESTIGATION, "researched", ["sha256:" + "1" * 64])


@pytest.mark.parametrize("change, reason", [
    (_put("tasks", "{id}", {"id": "task", "status": "queued"}), "recovery_task_exists"),
    (_put("invocation_reservations", "res-1", {"id": "res-1", "task_id": None}), "recovery_invocation_exists"),
    (_put("dge_sessions", "rp-001.c001.design", {"id": "rp-001.c001.design"}), "recovery_residue"),
    (_later_publication, "recovery_message_delivered"),
    (_in_flight, "recovery_effect_unknown"),
    (_provider_slot, "recovery_provider_entered"),
    (_disposition, "recovery_investigation_changed")])
def test_active_unknown_or_possibly_delivered_effects_refuse_and_write_nothing(tmp_path, change, reason):
    env, _ = failed_world(tmp_path)
    _, sha = replacement(env)
    message_id = history(env.store)["outbox"][0]["message"]["message_id"]
    change(env, message_id)
    transport = FakeTransport()
    assert refused(env.programs.recover_dispatch, request(env, sha), transport) == reason
    assert transport.calls == [] and _untouched(env)


@pytest.mark.parametrize("pin, reason", [({"run_id": "rp-001.c002"}, "recovery_dispatch_mismatch"),
                                         ({"manifest_sha256": "f" * 64}, "recovery_dispatch_mismatch"),
                                         ({"cycle": "rp-001:002"}, "recovery_dispatch_mismatch"),
                                         ({"snapshot_sha256": "e" * 64}, "recovery_dispatch_mismatch")])
def test_a_stale_owner_request_naming_another_attempt_refuses(tmp_path, pin, reason):
    env, _ = failed_world(tmp_path)
    _, sha = replacement(env)
    assert refused(env.programs.recover_dispatch, request(env, sha, **pin), FakeTransport()) == reason
    assert _untouched(env)


def test_a_changed_scope_foreign_digest_or_ticked_replacement_refuses(tmp_path):
    env, _ = failed_world(tmp_path)
    widened, wide_sha = replacement(env, "rp-wide", max_adoptions=2)
    assert refused(env.programs.recover_dispatch, request(env, wide_sha, "rp-wide"), FakeTransport()) == "recovery_scope_changed"
    other = {**SOURCE, "reason_codes": ["store_timeout", "other_code"]}
    cfg = validate_config(config(env.head, id="rp-other", investigation_source=other), POLICY)
    env.programs.register(cfg, env.identity, [])
    other_sha = config_digest(cfg, env.identity)
    assert refused(env.programs.recover_dispatch, request(env, other_sha, "rp-other"), FakeTransport()) == "recovery_scope_changed"
    _, sha = replacement(env)
    assert refused(env.programs.recover_dispatch, request(env, "d" * 64), FakeTransport()) == "recovery_replacement_mismatch"
    env.programs.resume("rp-002")
    assert refused(env.programs.recover_dispatch, request(env, sha), FakeTransport()) == "recovery_replacement_not_fresh"
    assert refused(env.programs.recover_dispatch, request(env, sha, "rp-001"), FakeTransport()) == "recovery_request_invalid"
    assert _untouched(env) and widened["max_adoptions"] == 2


# ----- the transport proof --------------------------------------------------------------------------------------
def test_an_unavailable_transport_refuses_keeps_the_fence_and_a_later_proof_authorizes_once(tmp_path):
    env, _ = failed_world(tmp_path)
    before = history(env.store)
    _, sha = replacement(env)
    code = refused(env.programs.recover_dispatch, request(env, sha), FakeTransport(error=TimeoutError(CANARY)))
    assert code == "recovery_transport_unavailable"
    with env.store.transaction() as tx:
        assert tx.get(BUCKET_RECOVERIES, INVESTIGATION)["state"] == "fenced"
    views = {d["id"]: d for d in env.programs.dispatches()}
    assert views[INVESTIGATION]["current"] is True, "a fenced request authorizes nothing"
    env.programs.resume("rp-002")
    assert replacement_runner(env).tick("rp-002")["selected"] != "inv-" + INVESTIGATION[:24]
    with env.store.transaction() as tx:
        assert tx.get(BUCKET_DISPATCHES, REPLACEMENT) is None
    assert history(env.store) == before


def test_a_message_present_on_the_transport_is_a_durable_refusal(tmp_path):
    env, _ = failed_world(tmp_path)
    _, sha = replacement(env)
    assert refused(env.programs.recover_dispatch, request(env, sha), FakeTransport(present=True)) == "recovery_message_delivered"
    transport = FakeTransport()
    assert refused(env.programs.recover_dispatch, request(env, sha), transport) == "recovery_message_delivered"
    assert transport.calls == [], "a recorded refusal is not re-probed until it happens to pass"
    with env.store.transaction() as tx:
        row = tx.get(BUCKET_RECOVERIES, INVESTIGATION)
        assert row["state"] == "refused" and tx.get("outbox_delivery", row["fence"]["outbox"])["status"] == "quarantined"


def test_a_publication_change_after_the_fence_refuses_the_authorization(tmp_path):
    env, _ = failed_world(tmp_path)
    _, sha = replacement(env)
    message_id = history(env.store)["outbox"][0]["message"]["message_id"]

    class Racing(FakeTransport):
        def inspect(self, recipient, message_id_):
            with env.store.transaction() as tx:   # LABELLED injected race: a delivery record appears
                delivery = tx.get("outbox_delivery", message_id)
                tx.put("outbox_delivery", message_id, {**delivery, "status": "delivered", "delivered_entry_id": "9-0"})
            return super().inspect(recipient, message_id_)

    assert refused(env.programs.recover_dispatch, request(env, sha), Racing()) == "recovery_message_delivered"
    with env.store.transaction() as tx:
        assert tx.get(BUCKET_RECOVERIES, INVESTIGATION)["state"] == "fenced"


# ----- repeat, restart and concurrency --------------------------------------------------------------------------
def test_concurrent_and_restarted_requests_and_ticks_create_one_replacement(tmp_path):
    env, _ = failed_world(tmp_path)
    _, sha = replacement(env)
    document, results, errors = request(env, sha), [], []

    def owner():
        try:
            results.append(ResearchProgram(env.store, clock=env.clock).recover_dispatch(document, FakeTransport()))
        except Exception as exc:   # pragma: no cover - reported below
            errors.append(exc)
    threads = [threading.Thread(target=owner) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == [] and len(results) == 4 and all(r["recovered"] for r in results)
    assert sum(not r["cached"] for r in results) >= 1
    with env.store.transaction() as tx:
        assert len(tx.scan(BUCKET_RECOVERIES)) == 1 and len(tx.scan("outbox_quarantine")) == 1
    restarted = ResearchProgram(env.store, clock=env.clock)
    assert restarted.recover_dispatch(document, FakeTransport())["cached"] is True
    other = {**document, "replacement": {"program": "rp-003", "config_sha256": sha}}
    assert refused(restarted.recover_dispatch, other, FakeTransport()) == "recovery_conflict"

    # A third program with the same authority never takes the authorized replacement over.
    cfg = validate_config(config(env.head, id="rp-003", investigation_source=dict(SOURCE)), POLICY)
    env.programs.register(cfg, env.identity, [])
    env.programs.resume("rp-003")
    assert replacement_runner(env).tick("rp-003").get("investigation") is None
    env.programs.resume("rp-002")
    ticks = []
    runners = [replacement_runner(env) for _ in range(2)]
    workers = [threading.Thread(target=lambda r=r: ticks.append(r.tick("rp-002"))) for r in runners]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()
    claimed = [t for t in ticks if t.get("investigation") == INVESTIGATION]
    assert len(claimed) == 1 and sum(len(r.council.manifests) for r in runners) == 1
    with env.store.transaction() as tx:
        rows = tx.scan(BUCKET_DISPATCHES)
    assert sorted(r["id"] for r in rows) == [INVESTIGATION, REPLACEMENT]


def test_a_failed_replacement_is_held_and_never_opens_a_second_recovery(tmp_path):
    env, _ = failed_world(tmp_path)
    _, sha = replacement(env)
    document = request(env, sha)
    env.programs.recover_dispatch(document, FakeTransport())
    env.programs.resume("rp-002")
    tick = replacement_runner(env, status="failed").tick("rp-002")
    assert tick["result"] == "failed" and env.programs.status("rp-002")["state"] == "blocked"
    views = {d["id"]: d for d in env.programs.dispatches()}
    assert views[REPLACEMENT]["current"] is True and views[REPLACEMENT]["result"] == "failed"
    _, next_sha = replacement(env, "rp-004")
    second = {**document, "replacement": {"program": "rp-004", "config_sha256": next_sha}}
    assert refused(env.programs.recover_dispatch, second, FakeTransport()) == "recovery_conflict"
    assert env.programs.recover_dispatch(document, FakeTransport())["state"] == "claimed"


def test_postgres_concurrent_requests_record_one_lineage_and_one_replacement(tmp_path, isolated_pgstore):
    """Real isolated PostgreSQL (HARNESS_INTEGRATION=1): the advisory-locked transactions serialize
    concurrent owner requests and the replacement claim exactly as the memory store does."""
    env, _ = failed_world(tmp_path, store=isolated_pgstore)
    before = history(env.store)
    _, sha = replacement(env)
    document, results = request(env, sha), []
    start = threading.Barrier(3)

    def owner():
        start.wait()
        results.append(ResearchProgram(env.store, clock=env.clock).recover_dispatch(document, FakeTransport()))
    threads = [threading.Thread(target=owner) for _ in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(results) == 3 and all(r["recovered"] for r in results)
    env.programs.resume("rp-002")
    assert replacement_runner(env).tick("rp-002")["result"] == "accepted"
    with env.store.transaction() as tx:
        assert len(tx.scan(BUCKET_RECOVERIES)) == 1 and len(tx.scan("outbox_quarantine")) == 1
        assert sorted(r["id"] for r in tx.scan(BUCKET_DISPATCHES)) == [INVESTIGATION, REPLACEMENT]
    assert history(env.store) == before


# ----- adapter entry and transport probe --------------------------------------------------------------------------
class FakeRedis:
    """LABELLED in-memory stand-in for the two Redis read calls the probe uses; no writes exist."""

    def __init__(self, streams, fail=False):
        self.streams, self.fail = streams, fail

    def xlen(self, stream):
        if self.fail:
            raise ConnectionError("fixture: unreachable " + CANARY)
        return len(self.streams.get(stream, []))

    def xrange(self, stream, count):
        return list(self.streams.get(stream, []))[:count]


def probe(streams, fail=False, limit=10000):
    bus = type("FixtureBus", (), {"namespace": "ns", "stream": staticmethod(lambda agent: "ns:agent:" + agent),
                                  "transport": lambda self, create=True: dict(IDENTITY)})()
    bus.client = FakeRedis(streams, fail)
    return TransportProbe(bus, limit=limit)


def test_the_transport_probe_reads_the_recipient_and_dead_letter_streams_completely_or_refuses():
    body = json.dumps({"message_id": "m-1"})

    def absent(p):
        observed = p.inspect("lead:researcher", "m-1")
        assert observed["before"] == observed["after"] == IDENTITY
        return observed["absent"]
    assert absent(probe({})) is True
    assert absent(probe({"ns:agent:lead:researcher": [("1-0", {"body": json.dumps({"message_id": "m-2"})})]})) is True
    assert absent(probe({"ns:agent:lead:researcher": [("1-0", {"body": body})]})) is False
    assert absent(probe({"ns:dead-letter": [("1-0", {"body": body, "reason": "x"})]})) is False
    with pytest.raises(ProgramRefused, match="recovery_transport_unbounded"):
        probe({"ns:agent:lead:researcher": [("1-0", {})] * 3}, limit=2).inspect("lead:researcher", "m-1")
    with pytest.raises(ConnectionError):
        probe({}, fail=True).inspect("lead:researcher", "m-1")


def test_the_probe_reads_the_run_scoped_bus_only_when_that_run_owns_a_storage_token():
    body = json.dumps({"message_id": "m-1"})
    configured = probe({})
    scoped = type("ScopedBus", (), {"namespace": "ns:run:x", "stream": staticmethod(lambda agent: "ns:run:x:agent:" + agent),
                                    "transport": lambda self, create=True: {**IDENTITY, "namespace": "ns:run:x"}})()
    scoped.client = FakeRedis({"ns:run:x:agent:lead:researcher": [("1-0", {"body": body})]})
    observed = TransportProbe(configured.bus, scoped=scoped).inspect("lead:researcher", "m-1")
    assert observed["absent"] is False and observed["before"]["namespace"] == "ns:run:x"
    tokenless = type("Tokenless", (), {"transport": lambda self, create=True: {**IDENTITY, "storage": None}})()
    observed = TransportProbe(configured.bus, scoped=tokenless).inspect("lead:researcher", "m-1")
    assert observed["absent"] is True and observed["before"] == IDENTITY, "a pre-scoping run reads the configured bus"


def test_the_cli_entry_reads_the_owner_file_and_refuses_an_unreachable_bus(tmp_path):
    env, _ = failed_world(tmp_path)
    _, sha = replacement(env)
    path = tmp_path / "recovery.json"
    path.write_text(json.dumps(request(env, sha)), encoding="utf-8")
    service = type("Service", (), {"store": env.store})()
    args = type("Args", (), {"file": path})()
    with pytest.raises(ProgramRefused, match="recovery_transport_unavailable"):
        recover_cli(service, args, transport=probe({}, fail=True))
    result = recover_cli(service, args, transport=probe({}))
    assert result["exit_code"] == 0 and result["state"] == "authorized" and result["investigation"] == INVESTIGATION
    assert replacement_dispatch_id(INVESTIGATION) == REPLACEMENT


# ----- original transport ownership (SPEC "Research recovery resubmission: original transport ownership") -----
class SecondBus(UnreachableBus):
    """LABELLED: the same injected delivery fault on a DIFFERENT fixture transport."""

    def __getattr__(self, name):
        if name == "transport":
            return lambda: {**IDENTITY, "storage": "token-b"}
        raise AttributeError(name)


class UnidentifiedBus(UnreachableBus):
    """LABELLED: a binding-capable bus whose identity read times out, so nothing is published."""

    def __getattr__(self, name):
        if name == "transport":
            def unreadable():
                raise MessageDeliveryError("TimeoutError")
            return unreadable
        raise AttributeError(name)


def test_the_failed_attempt_committed_its_transport_and_the_fence_pins_it(tmp_path):
    env, _ = failed_world(tmp_path)
    [attempt] = history(env.store)["attempts"]
    assert attempt["status"] == "retry" and attempt["transport"] == IDENTITY
    _, sha = replacement(env)
    result = env.programs.recover_dispatch(request(env, sha), FakeTransport())
    assert result["fence"]["transport"] == IDENTITY and result["proof"] == "absent_on_bound_transport"


def test_a_legacy_attempt_without_a_binding_refuses_as_unknown_and_writes_nothing(tmp_path):
    """Our historical failed run's attempt predates bindings: its destination is unknown and is never
    backfilled from today's configuration or an owner assertion."""
    env, _ = failed_world(tmp_path, council=lambda store: PublicationFailingCouncil(store, UnreachableBus(bound=False)))
    assert "transport" not in history(env.store)["attempts"][0]
    _, sha = replacement(env)
    transport = FakeTransport()
    assert refused(env.programs.recover_dispatch, request(env, sha), transport) == "recovery_transport_unbound"
    assert transport.calls == [] and _untouched(env)


@pytest.mark.parametrize("probe_view", [
    {"identity": {**IDENTITY, "storage": "token-b"}},              # another server behind the configuration
    {"identity": {**IDENTITY, "storage": None}},                   # a server that never held the token
    {"after": {**IDENTITY, "storage": "token-b"}},                 # the identity changed during the read
    {"identity": {**IDENTITY, "namespace": "other"}}])             # another namespace
def test_absence_on_any_other_transport_refuses_keeps_the_fence_and_the_bound_one_authorizes_once(tmp_path, probe_view):
    env, _ = failed_world(tmp_path)
    before = history(env.store)
    _, sha = replacement(env)
    assert refused(env.programs.recover_dispatch, request(env, sha), FakeTransport(**probe_view)) == \
        "recovery_transport_changed"
    with env.store.transaction() as tx:
        assert tx.get(BUCKET_RECOVERIES, INVESTIGATION)["state"] == "fenced"
        assert tx.get(BUCKET_DISPATCHES, REPLACEMENT) is None
    assert {d["id"]: d for d in env.programs.dispatches()}[INVESTIGATION]["current"] is True
    unreadable = FakeTransport()
    unreadable.identity = None
    assert refused(env.programs.recover_dispatch, request(env, sha), unreadable) == "recovery_transport_unavailable"
    assert env.programs.recover_dispatch(request(env, sha), FakeTransport())["state"] == "authorized"
    assert history(env.store) == before


def test_attempts_on_two_different_transports_refuse_before_any_fence(tmp_path):
    env, _ = failed_world(tmp_path)
    message_id = history(env.store)["outbox"][0]["message"]["message_id"]
    relay(env.store, organization(), SecondBus(), correlation_id="autonomous:rp-001.c001")   # a later attempt elsewhere
    with env.store.transaction() as tx:
        attempts = [a for a in tx.scan("outbox_attempts") if a["outbox_id"] == message_id]
        assert sorted(a["transport"]["storage"] for a in attempts) == ["token-a", "token-b"]
        assert tx.get("outbox_delivery", message_id)["transport"] == IDENTITY, "the first binding is kept"
    _, sha = replacement(env)
    transport = FakeTransport()
    assert refused(env.programs.recover_dispatch, request(env, sha), transport) == "recovery_transport_changed"
    assert transport.calls == [] and _untouched(env)


def test_no_publish_call_needs_no_probe(tmp_path):
    """The bus identity was unreadable, so the outbox committed `transport_unavailable` and never
    called publish: no transport can hold the assignment."""
    env, _ = failed_world(tmp_path, council=lambda store: PublicationFailingCouncil(store, UnidentifiedBus()))
    assert [a["status"] for a in history(env.store)["attempts"]] == ["transport_unavailable"]
    assert env.runner.council.bus.attempts == 0
    _, sha = replacement(env)
    transport = FakeTransport(error=AssertionError("not read"))
    result = env.programs.recover_dispatch(request(env, sha), transport)
    assert result["state"] == "authorized" and result["proof"] == "no_publish_call" and transport.calls == []


# ----- actual production adapters: RedisBus publisher, TransportProbe and the CLI wiring -------------------------
def _redis_world(tmp_path, monkeypatch, lose_reply):
    """The REAL CouncilRun publishes through the REAL RedisBus to LABELLED fixture server A; the
    injected fault is a lost reply AFTER the XADD landed, or a timeout of the publish script before
    its write. The owner recovery then runs the REAL CLI wiring (`RedisBus(redis_url())` and
    `TransportProbe`) against whatever HARNESS_REDIS_URL/NAMESPACE now name."""
    from test_bus import SECRET, FakeRedisFactory, FakeRedisServer

    from codex_harness.adapters.bus import RedisBus
    servers = {("a.example", 6379): FakeRedisServer("run-a"), ("b.example", 6379): FakeRedisServer("run-b")}
    monkeypatch.setattr("codex_harness.adapters.bus.Redis", FakeRedisFactory(servers))
    url_a = "redis://owner:" + SECRET + "@a.example:6379/0"
    a = servers[("a.example", 6379)]
    a.lose_reply, a.fail_write = lose_reply, not lose_reply
    env, tick = failed_world(tmp_path, council=lambda store: PublicationFailingCouncil(store, RedisBus(url_a, namespace="ns")))
    a.lose_reply = a.fail_write = False
    assert tick["reason_code"] == "publication_incomplete"
    _, sha = replacement(env)
    path = tmp_path / "recovery.json"
    path.write_text(json.dumps(request(env, sha)), encoding="utf-8")
    service, args = type("Service", (), {"store": env.store})(), type("Args", (), {"file": path})()

    def recover(url, namespace="ns"):
        monkeypatch.setenv("HARNESS_REDIS_URL", url)
        monkeypatch.setenv("HARNESS_REDIS_NAMESPACE", namespace)
        return recover_cli(service, args)
    return env, servers, url_a, recover


def _no_secret(env, *values):
    from test_bus import SECRET
    with env.store.transaction() as tx:
        text = json.dumps(tx.records(), default=str)
    assert SECRET not in text and "a.example" not in text
    assert all(SECRET not in json.dumps(value, default=str) for value in values)


def test_production_wiring_lost_reply_on_a_then_empty_b_refuses_before_any_replacement(tmp_path, monkeypatch):
    env, servers, url_a, recover = _redis_world(tmp_path, monkeypatch, lose_reply=True)
    assert len(servers[("a.example", 6379)].database(0)["streams"]["ns:agent:lead:researcher"]) == 1, \
        "the fixture's lost reply really wrote on A"
    [attempt] = history(env.store)["attempts"]
    assert attempt["status"] == "retry" and attempt["transport"]["server"] == "run-a"
    with pytest.raises(ProgramRefused, match="recovery_transport_changed"):
        recover("redis://b.example:6379/0")                     # configuration now names empty B
    assert servers[("b.example", 6379)].database(0) == {"strings": {}, "streams": {}}, "the probe wrote nothing"
    with env.store.transaction() as tx:
        assert tx.get(BUCKET_RECOVERIES, INVESTIGATION)["state"] == "fenced"
        assert tx.get(BUCKET_DISPATCHES, REPLACEMENT) is None
    with pytest.raises(ProgramRefused, match="recovery_message_delivered"):
        recover(url_a)                                           # the bound transport holds the assignment
    with env.store.transaction() as tx:
        assert tx.get(BUCKET_RECOVERIES, INVESTIGATION)["state"] == "refused"
        assert tx.get(BUCKET_DISPATCHES, REPLACEMENT) is None
    _no_secret(env)


def test_production_wiring_changed_database_namespace_server_or_storage_refuse_and_a_authorizes(tmp_path, monkeypatch):
    env, servers, url_a, recover = _redis_world(tmp_path, monkeypatch, lose_reply=False)
    a = servers[("a.example", 6379)]
    assert a.database(0)["streams"] == {}, "the injected timeout came before the write"
    [attempt] = history(env.store)["attempts"]
    assert attempt["status"] == "retry" and attempt["transport"]["database"] == 0
    for url, namespace in ((url_a.replace("/0", "/1"), "ns"), (url_a, "other")):
        with pytest.raises(ProgramRefused, match="recovery_transport_changed"):
            recover(url, namespace)
    a.restart("run-a2")
    with pytest.raises(ProgramRefused, match="recovery_transport_changed"):
        recover(url_a)
    a.restart("run-a")
    token = a.database(0)["strings"].pop("ns:transport-incarnation")
    with pytest.raises(ProgramRefused, match="recovery_transport_changed"):
        recover(url_a)                                           # storage reset: the probe never recreates it
    assert "ns:transport-incarnation" not in a.database(0)["strings"]
    a.database(0)["strings"]["ns:transport-incarnation"] = token
    a.fail_before = True
    with pytest.raises(ProgramRefused, match="recovery_transport_unavailable"):
        recover(url_a)
    a.fail_before = False
    result = recover(url_a)
    assert result["state"] == "authorized" and result["proof"] == "absent_on_bound_transport"
    assert recover("redis://b.example:6379/0")["cached"] is True, "an authorized row is never re-probed"
    _no_secret(env, result)


def test_domain_transport_rules_are_pure_and_fail_closed():
    from codex_harness.domain.research_investigations import (
        InvestigationRefused,
        attempted_transport,
        check_transport_proof,
    )
    b = {**IDENTITY, "storage": "token-b"}
    assert attempted_transport([]) is None
    assert attempted_transport([{"status": "superseded_before_publish"}, {"status": "transport_unavailable"}]) is None
    assert attempted_transport([{"status": "retry", "transport": IDENTITY}] * 2) == IDENTITY
    for attempts, code in (([{"status": "retry"}], "recovery_transport_unbound"),
                           ([{"status": "retry", "transport": {**IDENTITY, "storage": None}}], "recovery_transport_unbound"),
                           ([{"status": "retry", "transport": IDENTITY}, {"status": "retry", "transport": b}],
                            "recovery_transport_changed")):
        with pytest.raises(InvestigationRefused) as info:
            attempted_transport(attempts)
        assert info.value.reason_code == code
    assert check_transport_proof(IDENTITY, {"before": IDENTITY, "absent": True, "after": IDENTITY}) is True
    assert check_transport_proof(IDENTITY, {"before": IDENTITY, "absent": False, "after": IDENTITY}) is False
    for observation, code in ((None, "recovery_transport_unavailable"),
                              ({"before": IDENTITY, "absent": "yes", "after": IDENTITY}, "recovery_transport_unavailable"),
                              ({"before": b, "absent": True, "after": b}, "recovery_transport_changed")):
        with pytest.raises(InvestigationRefused) as info:
            check_transport_proof(IDENTITY, observation)
        assert info.value.reason_code == code


# ----- explicit execution revocation (SPEC "Actual legacy research recovery: execution revocation") -----------
# The actual-shaped fixture: the REAL council fails before provider entry on a LABELLED legacy bus that
# has no transport identity, so its one `retry` attempt carries NO binding, zero tasks and reservations.
# Revocation never claims the assignment was not delivered: the explicit owner request advances the
# existing task identity fence of that assignment's id, so the REAL `Workflow.submit` refuses a late
# delivery before any task, reservation or provider start in this store.
REVOCATION = "urn:zeus:research-dispatch-recovery:2"


def legacy_world(tmp_path, store=None):
    return failed_world(tmp_path, council=lambda s: PublicationFailingCouncil(s, UnreachableBus(bound=False)),
                        store=store)


def assignment(env) -> dict:
    [item] = history(env.store)["outbox"]
    return item


def revocation(env, config_sha256, program_id="rp-002", **revoke):
    item = assignment(env)
    pinned = {"message_id": item["message"]["message_id"], "source_sha256": digest(item)}
    return {**request(env, config_sha256, program_id), "schema": REVOCATION, "mode": "execution_revocation",
            "revoke": {**pinned, **revoke}}


def late_delivery(env):
    """The ORIGINAL assignment reaching the real workflow admission after the fact (a delayed
    consumer of an old stream entry). Returns the refusal, or the task if it was admitted."""
    try:
        return Workflow(env.store, organization()).submit(deepcopy(assignment(env)["message"]))
    except ContractError as exc:
        return exc


def no_execution(env) -> bool:
    with env.store.transaction() as tx:
        return (tx.scan("tasks") == [] and tx.scan("invocation_reservations") == []
                and tx.get("autonomous_runs", "rp-001.c001")["starts"] == {"reserved": 0, "settled": 0, "slots": []})


def fence_of(env):
    with env.store.transaction() as tx:
        return tx.get("execution_fences", "tasks:" + assignment(env)["message"]["message_id"])


def test_explicit_revocation_blocks_the_late_original_and_authorizes_exactly_one_replacement(tmp_path):
    env, _ = legacy_world(tmp_path)
    before = history(env.store)
    assert "transport" not in before["attempts"][0] and before["attempts"][0]["status"] == "retry"
    _, sha = replacement(env)
    # The existing strict transport-proof mode still refuses this row and writes nothing.
    assert refused(env.programs.recover_dispatch, request(env, sha), FakeTransport()) == "recovery_transport_unbound"
    assert _untouched(env) and fence_of(env) is None

    transport = FakeTransport(error=AssertionError("revocation never reads a transport"))
    result = env.programs.recover_dispatch(revocation(env, sha), transport)
    message_id = assignment(env)["message"]["message_id"]
    assert transport.calls == [] and result["recovered"] is True and result["cached"] is False
    assert result["state"] == "authorized" and result["mode"] == "execution_revocation"
    assert result["proof"] == "execution_revoked" and result["fence"]["transport"] is None
    fence = fence_of(env)
    assert fence["generation"] == 1 and fence["owner"] == "research-dispatch-recovery:" + result["request_sha256"]
    assert result["revocation"]["delivery"] == "unknown", "revocation is never reported as non-delivery"
    assert result["revocation"]["fenced_at"] == fence["at"] and result["revocation"]["row_id"] == message_id
    assert "not delivered" in result["revocation"]["authority"] and "unknown" in result["revocation"]["authority"]

    # The delayed original delivery cannot create a task, reserve or start a provider.
    refusal = late_delivery(env)
    assert isinstance(refusal, ContractError) and "used before" in str(refusal)
    assert no_execution(env)
    bus = RecordingBus()
    assert relay(env.store, organization(), bus)["published"] == 0 and bus.published == []
    assert history(env.store) == before, "run, retry attempt and unsent outbox history are preserved"

    # No downgrade and no second recovery: the old-mode request is a conflict now.
    assert refused(env.programs.recover_dispatch, request(env, sha), FakeTransport()) == "recovery_conflict"

    env.programs.resume("rp-002")
    runner = replacement_runner(env)
    tick = runner.tick("rp-002")
    assert tick["investigation"] == INVESTIGATION and tick["result"] == "accepted"
    with env.store.transaction() as tx:
        assert tx.get(BUCKET_RECOVERIES, INVESTIGATION)["state"] == "claimed"
    assert refused(env.programs.recover_dispatch, revocation(env, sha, "rp-003"), FakeTransport()) == "recovery_conflict"
    again = ResearchProgram(env.store, clock=env.clock).recover_dispatch(revocation(env, sha), None)
    assert again["cached"] is True and again["state"] == "claimed" and fence_of(env) == fence
    assert isinstance(late_delivery(env), ContractError) and no_execution(env)
    assert len(runner.council.manifests) == 1 and history(env.store) == before


def test_admission_first_refuses_the_revocation_and_authorizes_nothing(tmp_path):
    env, _ = legacy_world(tmp_path)
    _, sha = replacement(env)
    task = late_delivery(env)   # the original reached admission first: a real queued task
    assert task["status"] == "queued"
    assert refused(env.programs.recover_dispatch, revocation(env, sha), None) == "recovery_task_exists"
    assert _untouched(env) and fence_of(env) is None, "this delivery is never a cancellation of a task"


@pytest.mark.parametrize("first", ["admission", "revocation"])
def test_forced_interleavings_leave_exactly_one_winner(tmp_path, first):
    """Both orders forced through the one writer transaction: the first writer is paused INSIDE its
    transaction while the other is started; the loser refuses and leaves no partial state."""
    from contextlib import contextmanager
    env, _ = legacy_world(tmp_path)
    _, sha = replacement(env)
    entered, release, outcome = threading.Event(), threading.Event(), {}
    workflow = Workflow(env.store, organization())
    original = env.store.transaction
    # Both inputs are read before the pause is installed: each call then opens exactly ONE writer
    # transaction (submit's, or the revocation's), so the pause holds the first writer itself.
    document, message = revocation(env, sha), deepcopy(assignment(env)["message"])

    @contextmanager
    def holding():   # LABELLED injected pause inside the first writer's transaction
        with original() as tx:
            entered.set()
            release.wait(5)
            yield tx

    def admit():
        try:
            outcome["admission"] = workflow.submit(deepcopy(message))
        except ContractError as exc:
            outcome["admission"] = exc

    def revoke():
        try:
            outcome["revocation"] = ResearchProgram(env.store, clock=env.clock).recover_dispatch(document, None)
        except ProgramRefused as exc:
            outcome["revocation"] = exc
    runs = {"admission": admit, "revocation": revoke}
    env.store.transaction = holding
    winner = threading.Thread(target=runs[first])
    winner.start()
    assert entered.wait(5)
    env.store.transaction = original
    loser = threading.Thread(target=runs["revocation" if first == "admission" else "admission"])
    loser.start()
    release.set()
    winner.join(10)
    loser.join(10)
    with env.store.transaction() as tx:
        tasks, recoveries = tx.scan("tasks"), tx.scan(BUCKET_RECOVERIES)
    if first == "admission":
        assert outcome["admission"]["status"] == "queued" and len(tasks) == 1
        assert outcome["revocation"].reason_code == "recovery_task_exists" and recoveries == [] and fence_of(env) is None
    else:
        assert outcome["revocation"]["state"] == "authorized" and len(recoveries) == 1
        assert isinstance(outcome["admission"], ContractError) and tasks == [] and no_execution(env)


def test_a_concurrent_race_between_admission_and_revocation_never_yields_both(tmp_path):
    env, _ = legacy_world(tmp_path)
    _, sha = replacement(env)
    document, start, outcome = revocation(env, sha), threading.Barrier(2), {}

    def admit():
        start.wait()
        outcome["admission"] = late_delivery(env)

    def revoke():
        start.wait()
        try:
            outcome["revocation"] = env.programs.recover_dispatch(document, None)
        except ProgramRefused as exc:
            outcome["revocation"] = exc
    threads = [threading.Thread(target=admit), threading.Thread(target=revoke)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    admitted = isinstance(outcome["admission"], dict)
    authorized = isinstance(outcome["revocation"], dict)
    assert admitted != authorized, "exactly one of admission and revocation wins"


def test_an_existing_foreign_fence_is_not_this_revocation(tmp_path):
    from codex_harness.application.execution_fence import advance
    env, _ = legacy_world(tmp_path)
    _, sha = replacement(env)
    message_id = assignment(env)["message"]["message_id"]
    with env.store.transaction() as tx:   # LABELLED injected fault: an arbitrary fence for the identity
        advance(tx, "tasks", message_id, 1, "someone-else")
    assert refused(env.programs.recover_dispatch, revocation(env, sha), None) == "recovery_fence_exists"
    assert _untouched(env)


@pytest.mark.parametrize("revoke", [{"source_sha256": "f" * 64}, {"message_id": "0f0f0f0f-other-message"}])
def test_a_changed_message_refuses_before_any_fence(tmp_path, revoke):
    env, _ = legacy_world(tmp_path)
    _, sha = replacement(env)
    assert refused(env.programs.recover_dispatch, revocation(env, sha, **revoke), None) == "recovery_message_changed"
    assert _untouched(env) and fence_of(env) is None


@pytest.mark.parametrize("change, reason", [
    (_put("tasks", "{id}", {"id": "task", "status": "queued"}), "recovery_task_exists"),
    (_put("invocation_reservations", "res-1", {"id": "res-1", "task_id": None}), "recovery_invocation_exists"),
    (_put("dge_sessions", "rp-001.c001.design", {"id": "rp-001.c001.design"}), "recovery_residue"),
    (_in_flight, "recovery_effect_unknown"),
    (_provider_slot, "recovery_provider_entered"),
    (_disposition, "recovery_investigation_changed")])
def test_revocation_keeps_every_other_precondition(tmp_path, change, reason):
    env, _ = legacy_world(tmp_path)
    _, sha = replacement(env)
    document = revocation(env, sha)
    change(env, assignment(env)["message"]["message_id"])
    assert refused(env.programs.recover_dispatch, document, None) == reason
    assert _untouched(env) and fence_of(env) is None


def test_an_accepted_original_or_a_changed_scope_refuses_revocation(tmp_path):
    (tmp_path / "accepted").mkdir()
    env, _ = failed_world(tmp_path / "accepted", council=lambda store: FakeCouncil(store, status="accepted"))
    _, sha = replacement(env)
    document = {**request(env, sha), "schema": REVOCATION, "mode": "execution_revocation",
                "revoke": {"message_id": "m-1", "source_sha256": "a" * 64}}
    assert refused(env.programs.recover_dispatch, document, None) == "recovery_dispatch_not_failed"
    (tmp_path / "scope").mkdir()
    env, _ = legacy_world(tmp_path / "scope")
    _, wide = replacement(env, "rp-wide", max_adoptions=2)
    assert refused(env.programs.recover_dispatch, revocation(env, wide, "rp-wide"), None) == "recovery_scope_changed"
    assert _untouched(env) and fence_of(env) is None


@pytest.mark.parametrize("document", [
    lambda d: {**d, "mode": "transport_proof"},
    lambda d: {k: v for k, v in d.items() if k != "revoke"},
    lambda d: {**d, "revoke": {"message_id": d["revoke"]["message_id"]}},
    lambda d: {**d, "schema": "urn:zeus:research-dispatch-recovery:1"}])
def test_the_revocation_request_is_strict(tmp_path, document):
    env, _ = legacy_world(tmp_path)
    _, sha = replacement(env)
    assert refused(env.programs.recover_dispatch, document(revocation(env, sha)), None) == "recovery_request_invalid"


def _drop_fence(env):
    key = "tasks:" + assignment(env)["message"]["message_id"]
    with env.store.lock:   # LABELLED injected fault: the fence row was lost (partial restore)
        env.store.data.pop(("execution_fences", key))


def _rewrite(**changes):
    def fault(env):
        with env.store.transaction() as tx:   # LABELLED injected fault: the fence row was rewritten
            key = "tasks:" + assignment(env)["message"]["message_id"]
            tx.put("execution_fences", key, {**tx.get("execution_fences", key), **changes})
    return fault


def _corrupt_row(env):
    with env.store.transaction() as tx:   # LABELLED injected fault: the lineage evidence was edited
        row = tx.get(BUCKET_RECOVERIES, INVESTIGATION)
        row["revocation"]["owner"] = "someone-else"
        tx.put(BUCKET_RECOVERIES, INVESTIGATION, row)


def _task_appeared(env):
    message_id = assignment(env)["message"]["message_id"]
    with env.store.transaction() as tx:   # LABELLED injected fault: a task row appeared anyway
        tx.put("tasks", message_id, {"id": message_id, "status": "queued"})


def _moved_quarantine(env):
    message_id = assignment(env)["message"]["message_id"]
    with env.store.transaction() as tx:   # LABELLED injected fault: the outbox fence was released
        tx.put("outbox_delivery", message_id, {**tx.get("outbox_delivery", message_id), "status": "retry"})


@pytest.mark.parametrize("fault, reason", [
    (_drop_fence, "recovery_revocation_fence_missing"),
    (_rewrite(owner="someone-else"), "recovery_revocation_fence_changed"),
    (_rewrite(generation=2), "recovery_revocation_fence_changed"),
    (_rewrite(at="2000-01-01T00:00:00+00:00"), "recovery_revocation_fence_changed"),
    (_corrupt_row, "recovery_revocation_corrupt"),
    (_task_appeared, "recovery_revocation_breached"),
    (_moved_quarantine, "recovery_publication_changed")])
def test_a_missing_changed_or_corrupt_retained_fence_holds_replay_and_the_replacement_claim(tmp_path, fault, reason):
    env, _ = legacy_world(tmp_path)
    _, sha = replacement(env)
    document = revocation(env, sha)
    env.programs.recover_dispatch(document, None)
    fault(env)
    restarted = ResearchProgram(env.store, clock=env.clock)
    assert refused(restarted.recover_dispatch, document, None) == reason
    env.programs.resume("rp-002")
    tick = replacement_runner(env).tick("rp-002")
    assert tick.get("investigation") is None and tick["selected"] != "inv-" + INVESTIGATION[:24], \
        "no replacement claim on a held revocation (an ordinary local candidate may still run)"
    with env.store.transaction() as tx:
        assert tx.get(BUCKET_DISPATCHES, REPLACEMENT) is None
        assert tx.get(BUCKET_RECOVERIES, INVESTIGATION)["state"] == "authorized"


def test_concurrent_and_restarted_revocations_record_one_lineage_one_fence_one_quarantine(tmp_path):
    env, _ = legacy_world(tmp_path)
    _, sha = replacement(env)
    document, results, errors = revocation(env, sha), [], []

    def owner():
        try:
            results.append(ResearchProgram(env.store, clock=env.clock).recover_dispatch(document, None))
        except Exception as exc:   # pragma: no cover - reported below
            errors.append(exc)
    threads = [threading.Thread(target=owner) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == [] and len(results) == 4 and sum(not r["cached"] for r in results) == 1
    with env.store.transaction() as tx:
        assert len(tx.scan(BUCKET_RECOVERIES)) == 1 and len(tx.scan("outbox_quarantine")) == 1
        assert len(tx.scan("execution_fences")) == 1
    assert ResearchProgram(env.store, clock=env.clock).recover_dispatch(document, None)["cached"] is True


def test_a_failed_replacement_after_revocation_is_held(tmp_path):
    env, _ = legacy_world(tmp_path)
    _, sha = replacement(env)
    env.programs.recover_dispatch(revocation(env, sha), None)
    env.programs.resume("rp-002")
    assert replacement_runner(env, status="failed").tick("rp-002")["result"] == "failed"
    _, next_sha = replacement(env, "rp-004")
    assert refused(env.programs.recover_dispatch, revocation(env, next_sha, "rp-004"), None) == "recovery_conflict"
    assert isinstance(late_delivery(env), ContractError) and no_execution(env)


def test_the_cli_revocation_builds_no_bus(tmp_path, monkeypatch):
    env, _ = legacy_world(tmp_path)
    _, sha = replacement(env)
    path = tmp_path / "revocation.json"
    path.write_text(json.dumps(revocation(env, sha)), encoding="utf-8")

    def forbidden(*args, **kwargs):
        raise AssertionError("revocation must not build a bus")
    monkeypatch.setattr("codex_harness.adapters.bus.RedisBus", forbidden)
    service, args = type("Service", (), {"store": env.store})(), type("Args", (), {"file": path})()
    result = recover_cli(service, args)
    assert result["exit_code"] == 0 and result["proof"] == "execution_revoked" and result["mode"] == "execution_revocation"


# ----- settled read-only successor (SPEC "Real council progress: ... settled-read-only successor") -------------
# The actual-shaped fixture of replacement002: rp-001 failed before provider entry and was revoked; the
# replacement rp-002 claimed `.recovery-1` and its REAL CouncilRun really completed the researcher AND the
# DBA role (two succeeded tasks, two settled accepted reservations, two execution artifacts), then stopped
# `foreign_message` on the conductor relay. LABELLED stand-ins: the role executor, the call budget, the
# in-memory bus holding the foreign-run report, the snapshot port, the artifact store and the clock.
SUCCESSOR_SCHEMA = "urn:zeus:research-dispatch-recovery:3"
SECOND = INVESTIGATION + ".recovery-2"


class ReadOnlyCouncilExecutor:
    """LABELLED fixture executor: settles ONLY researcher and DBA `dge_role` tasks the way the real
    executor records them (settled accepted reservation, content-addressed execution artifact bound to
    the stage, the task's own base and its exact input evidence) and files each role's `task.result`
    through the outbox, as `Workflow.complete` does. Any other role reaching it fails the test."""

    def __init__(self, svc, artifacts):
        self.svc, self.artifacts, self.calls = svc, artifacts, []

    def execute_one(self, agent, expected=None):
        from test_autonomous import RESEARCH, evidence_ref_of
        from test_council import DBA_REPORT

        from codex_harness.domain.model import canonical, envelope
        self.calls.append(agent)
        with self.svc.store.transaction() as tx:
            task = tx.get("tasks", expected["id"])
            message = task["message"]
            details, base = message["what"]["details"], message["where"]["revision"]
            role = details["role"]
            assert role in {"researcher", "dba"}, "only the read-only roles may execute in this fixture"
            answer = ({**RESEARCH, "sources": [{**RESEARCH["sources"][0], "revision": base}]} if role == "researcher"
                      else {"snapshot_digest": details["snapshot_digest"], **DBA_REPORT})
            reservation = {"id": "res-" + task["id"], "bucket": "tasks", "task_id": task["id"], "generation": 1,
                           "attempt": 1, "invocation": 1, "stage": "dge:" + role, "status": "settled",
                           "outcome": "accepted", "usage": {"source": "provider", "total_tokens": 1}}
            tx.put("invocation_reservations", reservation["id"], reservation)
            ref = self.artifacts.put(canonical({
                "answer": answer, "thread_id": "thread-" + task["id"], "execution_assignment": {"provider": "codex"},
                "invocation": {"reservation": reservation["id"], "outcome": "accepted"},
                "research_binding": {"stage": "dge:" + role, "evidence_ref": evidence_ref_of(details), "basis_revision": base}}))
            task.update(attempt=1, generation=1, lease_owner="fixture", status="succeeded",
                        result={**answer, "execution_ref": ref, "basis_revision": base})
            tx.put("tasks", task["id"], task)
            report = envelope("task.result", task["agent"], message["who"]["sender"], "dge_role",
                              {"task_id": task["id"], "result": task["result"]}, message["correlation_id"], task["id"])
            tx.put("outbox", report["message_id"], {"message": report, "sent": False})
        return task


class ForeignMessageCouncil:
    """The REAL CouncilRun (v2) on the shared store: researcher and DBA execute through the LABELLED
    fixture executor, then a LABELLED report of another run already pending on the conductor stream
    stops the relay with `foreign_message`. `artifacts` is the execution evidence it wrote."""

    def __init__(self, store):
        from test_autonomous import Artifacts
        self.store, self.artifacts, self.receipts, self.executor = store, Artifacts(), [], None

    def __call__(self, service, args):
        from test_council import FakeSnapshotPort, SnapshotArtifacts
        from test_operation import Bus, Collector, FakeBudget

        from codex_harness.domain.model import envelope, utcnow
        manifest = validate_any_manifest(json.loads(Path(args.file).read_text(encoding="utf-8")), packaged_policy())
        harness = Harness(self.store, organization())
        bus = Bus()
        bus.publish(envelope("task.result", "lead:dba", "conductor", "dge_role", {"task_id": "x", "result": {}},
                             "autonomous:other-run"))
        self.executor = ReadOnlyCouncilExecutor(harness, self.artifacts)
        run = CouncilRun(harness, self.executor, bus, Workflow(self.store, harness.org), FakeBudget(), Collector(),
                         verify_sources=lambda packet: [{**s, "bytes": 1} for s in packet["sources"]], repository="r",
                         evidence=self.artifacts, snapshot=FakeSnapshotPort(utcnow), artifacts=SnapshotArtifacts(self.artifacts))
        receipt = run.run(manifest, {"repository": "fixture"}, {"path": "docs/GOAL.md", "sha256": "0" * 64})
        self.receipts.append(receipt)
        return receipt


def read_only_world(tmp_path, store=None):
    """rp-001 revoked -> rp-002 claims `.recovery-1` -> the real council settles researcher + DBA and
    fails `foreign_message`. Returns the env, the council (its artifact store is the evidence port) and
    the runner reused for later programs."""
    env, _ = legacy_world(tmp_path, store=store)
    _, sha = replacement(env)
    env.programs.recover_dispatch(revocation(env, sha), None)
    env.programs.resume("rp-002")
    runner = build(env.root.parent, store=env.store, root=env.root, head=env.head).runner
    council = ForeignMessageCouncil(env.store)
    runner.council = council
    tick = runner.tick("rp-002")
    assert tick["investigation"] == INVESTIGATION and tick["result"] == "failed", tick
    assert council.receipts[0]["reason_code"] == "foreign_message"
    return env, council, runner


def successor_request(env, replacement_sha256, program_id="rp-003", **pinned):
    with env.store.transaction() as tx:
        dispatch, lineage = tx.get(BUCKET_DISPATCHES, REPLACEMENT), tx.get(BUCKET_RECOVERIES, INVESTIGATION)
        program = tx.get(BUCKET_PROGRAMS, "rp-002")
    old = {"dispatch": REPLACEMENT, "lineage_version": 1, "lineage_request_sha256": lineage["request_sha256"],
           "program": "rp-002", "config_sha256": program["config_sha256"],
           **{k: dispatch[k] for k in ("cycle", "run_id", "manifest_sha256", "snapshot_sha256")}}
    return {"schema": SUCCESSOR_SCHEMA, "mode": "settled_read_only_successor", "investigation": INVESTIGATION,
            "predecessor": {**old, **pinned}, "replacement": {"program": program_id, "config_sha256": replacement_sha256}}


def predecessor_history(env) -> dict:
    """Every record of the failed read-only predecessor and of the original recovery that must stay."""
    correlation = "autonomous:rp-002.c001"
    with env.store.transaction() as tx:
        tasks = sorted([t for t in tx.scan("tasks") if t["message"]["correlation_id"] == correlation], key=lambda t: t["id"])
        ids = {t["id"] for t in tasks}
        return deepcopy({"run": tx.get("autonomous_runs", "rp-002.c001"), "tasks": tasks,
                         "reservations": sorted([r for r in tx.scan("invocation_reservations") if r["task_id"] in ids],
                                                key=lambda r: r["id"]),
                         "dispatch": tx.get(BUCKET_DISPATCHES, REPLACEMENT), "cycle": tx.get(BUCKET_CYCLES, "rp-002:001"),
                         "program": tx.get(BUCKET_PROGRAMS, "rp-002"), "recovery": tx.get(BUCKET_RECOVERIES, INVESTIGATION),
                         "fences": tx.scan("execution_fences"), "original": tx.get(BUCKET_DISPATCHES, INVESTIGATION),
                         "outbox": sorted([o for o in tx.scan("outbox") if o["message"]["correlation_id"] == correlation],
                                          key=lambda o: o["message"]["message_id"])})


def no_successor(env) -> bool:
    with env.store.transaction() as tx:
        return (tx.scan("research_dispatch_successors") == [] and tx.scan("research_dispatch_heads") == []
                and len(tx.scan("outbox_quarantine")) == 1 and tx.get(BUCKET_DISPATCHES, SECOND) is None)


def test_the_fixture_is_the_real_shaped_settled_read_only_foreign_message_failure(tmp_path):
    env, council, _ = read_only_world(tmp_path)
    facts = predecessor_history(env)
    assert council.executor.calls == ["lead:researcher", "lead:dba"]
    run = facts["run"]
    assert run["status"] == "failed" and run["reason_code"] == "foreign_message" and run["stage"] == "dba"
    assert run["starts"]["reserved"] == run["starts"]["settled"] == 2 and set(run["roles"]) == {"researcher", "dba"}
    assert [t["status"] for t in facts["tasks"]] == ["succeeded", "succeeded"]
    assert [r["status"] for r in facts["reservations"]] == ["settled", "settled"]
    assert facts["dispatch"]["result"] == "failed" and facts["dispatch"]["result_reason"] == "foreign_message"
    assert facts["recovery"]["state"] == "claimed" and facts["program"]["state"] == "blocked"
    assert refused(env.programs.resume, "rp-002") == "program_blocked", "no automatic retry"
    # Neither existing mode applies: the original recovery is used up and its request conflicts.
    _, sha = replacement(env, "rp-003")
    assert refused(env.programs.recover_dispatch, revocation(env, sha, "rp-003"), None) == "recovery_conflict"


def test_one_explicit_successor_of_the_exact_failed_head_is_claimed_once_and_history_is_kept(tmp_path):
    env, council, runner = read_only_world(tmp_path)
    before = predecessor_history(env)
    _, sha = replacement(env, "rp-003")
    document = successor_request(env, sha)
    result = env.programs.recover_dispatch(document, FakeTransport(error=AssertionError("never read")), council.artifacts)
    assert result["recovered"] is True and result["cached"] is False and result["state"] == "authorized"
    assert result["mode"] == "settled_read_only_successor" and result["proof"] == "settled_read_only"
    assert result["version"] == 2 and result["replacement"] == {"program": "rp-003", "config_sha256": sha,
                                                                "dispatch": SECOND, "cycle": None}
    calls = result["evidence"]["calls"]
    assert calls == {"reserved": 2, "settled": 2, "reservations": 2}, "the two settled calls stay counted as two"
    assert sorted(e["role"] for e in result["evidence"]["executions"]) == ["dba", "researcher"]
    assert predecessor_history(env) == before, "predecessor, original recovery and its fence are untouched"

    views = {d["id"]: d for d in env.programs.dispatches()}
    assert views[REPLACEMENT]["current"] is False and views[INVESTIGATION]["current"] is False
    status = env.programs.status("rp-003")
    assert status["current"] == [{"investigation": INVESTIGATION, "version": 2, "successor": INVESTIGATION + ":2",
                                   "dispatch": SECOND, "request_sha256": result["request_sha256"],
                                   "previous": {"version": 1, "dispatch": REPLACEMENT,
                                                "request_sha256": before["recovery"]["request_sha256"]},
                                   "updated_at": result["authorized_at"]}]
    assert [s["id"] for s in status["successors"]] == [INVESTIGATION + ":2"]
    assert env.programs.status("rp-002")["recoveries"][0]["state"] == "claimed", "the original row is not rewritten"

    env.programs.resume("rp-003")
    runner.council = FakeCouncil(env.store, status="accepted")
    tick = runner.tick("rp-003")
    assert tick["investigation"] == INVESTIGATION and tick["result"] == "accepted" and tick["run_id"] == "rp-003.c001"
    views = {d["id"]: d for d in env.programs.dispatches()}
    assert set(views) == {INVESTIGATION, REPLACEMENT, SECOND} and views[SECOND]["current"] is True
    assert views[SECOND]["recovery"] == INVESTIGATION + ":2"
    assert views[SECOND]["supersedes"] == {"dispatch": REPLACEMENT, **{k: before["dispatch"][k] for k in
                                           ("program", "cycle", "run_id", "manifest_sha256", "snapshot_sha256")}}
    assert predecessor_history(env) == before
    with env.store.transaction() as tx:
        assert tx.get("research_dispatch_successors", INVESTIGATION + ":2")["state"] == "claimed"

    # Replays: the identical request is cached (no evidence read); another for the same head conflicts.
    again = ResearchProgram(env.store, clock=env.clock).recover_dispatch(document, None, None)
    assert again["cached"] is True and again["state"] == "claimed"
    _, other = replacement(env, "rp-004")
    assert refused(env.programs.recover_dispatch, successor_request(env, other, "rp-004"), None,
                   council.artifacts) == "recovery_conflict"
    # The successor was accepted: another successor of it is never available (not a failed head).
    with env.store.transaction() as tx:
        head = tx.get("research_dispatch_heads", INVESTIGATION)
        accepted = tx.get(BUCKET_DISPATCHES, SECOND)
        program = tx.get(BUCKET_PROGRAMS, "rp-003")
    next_request = {**successor_request(env, other, "rp-004"), "predecessor": {
        "dispatch": SECOND, "lineage_version": 2, "lineage_request_sha256": head["request_sha256"], "program": "rp-003",
        "config_sha256": program["config_sha256"],
        **{k: accepted[k] for k in ("cycle", "run_id", "manifest_sha256", "snapshot_sha256")}}}
    assert refused(env.programs.recover_dispatch, next_request, None, council.artifacts) == "recovery_dispatch_not_failed"
    assert len(runner.council.manifests) == 1


def _task_status(status):
    def fault(env, council):
        with env.store.transaction() as tx:   # LABELLED injected fault on the predecessor's DBA task
            [task] = [t for t in tx.scan("tasks") if t["agent"] == "lead:dba"]
            tx.put("tasks", task["id"], {**task, "status": status})
    return fault


def _reservation_unknown(env, council):
    with env.store.transaction() as tx:   # LABELLED injected fault: a reservation never settled
        row = tx.scan("invocation_reservations")[0]
        tx.put("invocation_reservations", row["id"], {**row, "status": "unsettled_unknown"})


def _implementation_started(env, council):
    with env.store.transaction() as tx:   # LABELLED injected fault: an operation residue exists
        tx.put("operations", "rp-002.c001.impl", {"id": "rp-002.c001.impl", "status": "running"})


def _other_role(env, council):
    from codex_harness.domain.model import envelope
    with env.store.transaction() as tx:   # LABELLED injected fault: a non-read-only role task of the run
        message = envelope("task.assign", "conductor", "lead:research", "dge_role", {"role": "research_lead"},
                           "autonomous:rp-002.c001")
        tx.put("tasks", message["message_id"], {"id": message["message_id"], "agent": "lead:research",
                                                "status": "succeeded", "message": message, "result": {}})


def _terminated(env, council):
    with env.store.transaction() as tx:   # LABELLED injected fault: an unresolved termination record
        task = next(t for t in tx.scan("tasks") if t["agent"] == "lead:researcher")
        tx.put("observation_terminations", "term-1", {"id": "term-1", "task_id": task["id"]})


def _answer_changed(env, council):
    with env.store.transaction() as tx:   # LABELLED injected fault: the stored answer is not the artifact's
        task = next(t for t in tx.scan("tasks") if t["agent"] == "lead:dba")
        tx.put("tasks", task["id"], {**task, "result": {**task["result"], "summary": "rewritten"}})


def _corrupt_artifact(env, council):
    with env.store.transaction() as tx:
        task = next(t for t in tx.scan("tasks") if t["agent"] == "lead:dba")
    council.artifacts.corrupt(task["result"]["execution_ref"])   # LABELLED injected fault


def _unsent_foreign_role(env, council):
    from codex_harness.domain.model import envelope
    with env.store.transaction() as tx:   # LABELLED injected fault: an unsent assignment to a non-read-only lead
        message = envelope("task.assign", "conductor", "lead:research", "dge_role", {"role": "research_lead"},
                           "autonomous:rp-002.c001")
        tx.put("outbox", message["message_id"], {"message": message, "sent": False})


@pytest.mark.parametrize("fault, reason", [
    (_task_status("running"), "recovery_predecessor_active"),
    (_task_status("failed"), "recovery_effect_unknown"),
    (_reservation_unknown, "recovery_invocation_unsettled"),
    (_implementation_started, "recovery_effect_outside_read_only"),
    (_other_role, "recovery_effect_outside_read_only"),
    (_unsent_foreign_role, "recovery_effect_outside_read_only"),
    (_terminated, "recovery_effect_unknown"),
    (_answer_changed, "recovery_evidence_mismatch"),
    (_corrupt_artifact, "recovery_evidence_corrupt"),
    (_drop_fence, "recovery_revocation_fence_missing")])
def test_unsettled_unknown_effectful_or_unproven_predecessors_refuse_and_write_nothing(tmp_path, fault, reason):
    env, council, _ = read_only_world(tmp_path)
    _, sha = replacement(env, "rp-003")
    document = successor_request(env, sha)
    if fault is _drop_fence:
        fault(env)
    else:
        fault(env, council)
    assert refused(env.programs.recover_dispatch, document, None, council.artifacts) == reason
    assert no_successor(env)


def test_unavailable_evidence_stale_pins_and_widened_scope_refuse_and_write_nothing(tmp_path):
    from test_autonomous import Artifacts

    from codex_harness.adapters.autonomous_evidence import ExecutionEvidence
    env, council, _ = read_only_world(tmp_path)
    _, sha = replacement(env, "rp-003")
    assert refused(env.programs.recover_dispatch, successor_request(env, sha), None, None) == "recovery_evidence_unavailable"
    empty = ExecutionEvidence(Artifacts())   # the REAL port over an empty LABELLED store: no such artifact
    assert refused(env.programs.recover_dispatch, successor_request(env, sha), None, empty) == "recovery_evidence_missing"
    for pin, code in (({"lineage_request_sha256": "f" * 64}, "recovery_successor_stale"),
                      ({"manifest_sha256": "f" * 64}, "recovery_dispatch_mismatch"),
                      ({"config_sha256": "f" * 64}, "recovery_dispatch_mismatch"),
                      ({"cycle": "rp-002:002"}, "recovery_dispatch_mismatch")):
        assert refused(env.programs.recover_dispatch, successor_request(env, sha, **pin), None, council.artifacts) == code
    for pin in ({"lineage_version": 2}, {"dispatch": INVESTIGATION}):   # a pin that is not a head at all
        assert refused(env.programs.recover_dispatch, successor_request(env, sha, **pin), None,
                       council.artifacts) == "recovery_request_invalid"
    _, wide = replacement(env, "rp-wide", max_adoptions=2)
    assert refused(env.programs.recover_dispatch, successor_request(env, wide, "rp-wide"), None,
                   council.artifacts) == "recovery_scope_changed"
    assert no_successor(env)


@pytest.mark.parametrize("status, reason", [("accepted", "recovery_dispatch_not_failed"),
                                            ("rejected", "recovery_dispatch_not_failed"),
                                            ("failed", "recovery_not_settled_read_only")])
def test_accepted_rejected_or_other_failed_predecessors_are_never_succeeded(tmp_path, status, reason):
    env, _ = legacy_world(tmp_path)
    _, sha = replacement(env)
    env.programs.recover_dispatch(revocation(env, sha), None)
    env.programs.resume("rp-002")
    assert replacement_runner(env, status=status).tick("rp-002")["investigation"] == INVESTIGATION
    _, sha3 = replacement(env, "rp-003")
    assert refused(env.programs.recover_dispatch, successor_request(env, sha3), None, ForeignMessageCouncil(env.store).artifacts) \
        == reason
    assert no_successor(env)


def _unsent_report(env):
    """LABELLED: one more DBA report of the predecessor run committed to the outbox and never attempted
    (no delivery row, no attempt), the shape a relay stopped before publishing leaves behind."""
    from codex_harness.domain.model import envelope
    with env.store.transaction() as tx:
        task = next(t for t in tx.scan("tasks") if t["agent"] == "lead:dba")
        report = envelope("task.result", "lead:dba", "conductor", "dge_role", {"task_id": task["id"], "result": {}},
                          "autonomous:rp-002.c001")
        tx.put("outbox", report["message_id"], {"message": report, "sent": False})
    return report["message_id"]


def _move_quarantine(env, message_id):
    with env.store.transaction() as tx:   # LABELLED injected fault: the successor's outbox fence was released
        tx.put("outbox_delivery", message_id, {**tx.get("outbox_delivery", message_id), "status": "retry"})


def _change_task(env, message_id):
    with env.store.transaction() as tx:   # LABELLED injected fault: a bound predecessor execution changed
        task = next(t for t in tx.scan("tasks") if t["agent"] == "lead:researcher")
        tx.put("tasks", task["id"], {**task, "status": "retry"})


def _corrupt_successor(env, message_id):
    with env.store.transaction() as tx:   # LABELLED injected fault: the authorization row was edited
        row = tx.get("research_dispatch_successors", INVESTIGATION + ":2")
        tx.put("research_dispatch_successors", row["id"], {**row, "predecessor": {**row["predecessor"],
                                                                                  "lineage_version": 7}})


def _drop_head(env, message_id):
    with env.store.lock:   # LABELLED injected fault: the versioned head was lost (partial restore)
        env.store.data.pop(("research_dispatch_heads", INVESTIGATION))


def _drop_original_fence(env, message_id):
    _drop_fence(env)


@pytest.mark.parametrize("fault, reason", [
    (_move_quarantine, "recovery_publication_changed"),
    (_change_task, "recovery_successor_history_changed"),
    (_corrupt_successor, "recovery_successor_corrupt"),
    (_drop_head, "recovery_successor_corrupt"),
    (_drop_original_fence, "recovery_revocation_fence_missing")])
def test_a_broken_retained_chain_holds_replay_and_the_successor_claim(tmp_path, fault, reason):
    env, council, runner = read_only_world(tmp_path)
    message_id = _unsent_report(env)
    _, sha = replacement(env, "rp-003")
    document = successor_request(env, sha)
    result = env.programs.recover_dispatch(document, None, council.artifacts)
    assert result["fence"] == [{"outbox": message_id, "source_hash": result["fence"][0]["source_hash"], "attempts": 0}]
    bus = RecordingBus()
    assert relay(env.store, organization(), bus)["published"] == 0 and bus.published == [], "the unsent report is fenced"
    fault(env, message_id)
    assert refused(ResearchProgram(env.store, clock=env.clock).recover_dispatch, document, None, None) == reason
    env.programs.resume("rp-003")
    runner.council = FakeCouncil(env.store, status="accepted")
    tick = runner.tick("rp-003")
    assert tick.get("investigation") is None, "a held chain never releases the successor claim"
    with env.store.transaction() as tx:
        assert tx.get(BUCKET_DISPATCHES, SECOND) is None
        assert tx.get("research_dispatch_successors", INVESTIGATION + ":2")["state"] == "authorized"


def test_concurrent_and_restarted_successor_requests_record_one_row_one_head(tmp_path):
    env, council, _ = read_only_world(tmp_path)
    _unsent_report(env)
    _, sha = replacement(env, "rp-003")
    document, results, errors = successor_request(env, sha), [], []

    def owner():
        try:
            results.append(ResearchProgram(env.store, clock=env.clock).recover_dispatch(document, None, council.artifacts))
        except Exception as exc:   # pragma: no cover - reported below
            errors.append(exc)
    threads = [threading.Thread(target=owner) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == [] and len(results) == 4 and sum(not r["cached"] for r in results) == 1
    with env.store.transaction() as tx:
        assert len(tx.scan("research_dispatch_successors")) == 1 and len(tx.scan("research_dispatch_heads")) == 1
        assert len(tx.scan("outbox_quarantine")) == 2, "the original fence plus the one successor fence"
    assert ResearchProgram(env.store, clock=env.clock).recover_dispatch(document, None, None)["cached"] is True


def test_the_cli_successor_reads_the_executor_artifact_store_and_builds_no_bus(tmp_path, monkeypatch):
    env, council, _ = read_only_world(tmp_path)
    _, sha = replacement(env, "rp-003")
    path = tmp_path / "successor.json"
    path.write_text(json.dumps(successor_request(env, sha)), encoding="utf-8")

    def forbidden(*args, **kwargs):
        raise AssertionError("the successor must not build a bus")
    monkeypatch.setattr("codex_harness.adapters.bus.RedisBus", forbidden)
    service, args = type("Service", (), {"store": env.store})(), type("Args", (), {"file": path})()
    result = recover_cli(service, args, evidence=council.artifacts)
    assert result["exit_code"] == 0 and result["proof"] == "settled_read_only" and result["state"] == "authorized"


def test_postgres_successor_requests_serialize_to_one_authorization(tmp_path, isolated_pgstore):
    """Real isolated PostgreSQL (HARNESS_INTEGRATION=1): concurrent owner requests over the writer-locked
    transaction record one successor row and one head; the claim follows once."""
    env, council, runner = read_only_world(tmp_path, store=isolated_pgstore)
    before = predecessor_history(env)
    _, sha = replacement(env, "rp-003")
    document, results = successor_request(env, sha), []
    start = threading.Barrier(3)

    def owner():
        start.wait()
        results.append(ResearchProgram(env.store, clock=env.clock).recover_dispatch(document, None, council.artifacts))
    threads = [threading.Thread(target=owner) for _ in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(results) == 3 and sum(not r["cached"] for r in results) == 1
    env.programs.resume("rp-003")
    runner.council = FakeCouncil(env.store, status="accepted")
    assert runner.tick("rp-003")["result"] == "accepted"
    with env.store.transaction() as tx:
        assert len(tx.scan("research_dispatch_successors")) == 1 and len(tx.scan("research_dispatch_heads")) == 1
        assert tx.get(BUCKET_DISPATCHES, SECOND)["run_id"] == "rp-003.c001"
    assert predecessor_history(env) == before


def test_postgres_revocation_and_admission_serialize_to_one_winner(tmp_path, isolated_pgstore):
    """Real isolated PostgreSQL (HARNESS_INTEGRATION=1): the writer-locked transactions serialize a
    concurrent late admission against repeated owner revocation requests."""
    env, _ = legacy_world(tmp_path, store=isolated_pgstore)
    before = history(env.store)
    _, sha = replacement(env)
    document, outcome, results = revocation(env, sha), {}, []
    start = threading.Barrier(3)

    def admit():
        start.wait()
        outcome["admission"] = late_delivery(env)

    def revoke():
        start.wait()
        try:
            results.append(ResearchProgram(env.store, clock=env.clock).recover_dispatch(document, None))
        except ProgramRefused as exc:
            results.append(exc)
    threads = [threading.Thread(target=admit)] + [threading.Thread(target=revoke) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    authorized = [r for r in results if isinstance(r, dict)]
    with env.store.transaction() as tx:
        tasks, recoveries = tx.scan("tasks"), tx.scan(BUCKET_RECOVERIES)
    if isinstance(outcome["admission"], dict):
        assert authorized == [] and len(tasks) == 1 and recoveries == []
        assert all(r.reason_code == "recovery_task_exists" for r in results)
        return
    assert len(authorized) == 2 and sum(not r["cached"] for r in authorized) == 1 and tasks == []
    assert isinstance(late_delivery(env), ContractError) and no_execution(env)
    env.programs.resume("rp-002")
    assert replacement_runner(env).tick("rp-002")["result"] == "accepted"
    with env.store.transaction() as tx:
        assert len(tx.scan(BUCKET_RECOVERIES)) == 1 and len(tx.scan("outbox_quarantine")) == 1
        assert sorted(r["id"] for r in tx.scan(BUCKET_DISPATCHES)) == [INVESTIGATION, REPLACEMENT]
    assert history(env.store) == before
