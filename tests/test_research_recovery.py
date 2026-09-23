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
from codex_harness.domain.research_investigations import replacement_dispatch_id
from codex_harness.domain.research_program import ProgramRefused, config_digest, validate_config
from codex_harness.ports import MessageDeliveryError

REPLACEMENT = INVESTIGATION + ".recovery-1"


class Unreachable:
    """LABELLED stand-in for every port the failed council must NEVER reach: any use fails the test."""

    def __getattr__(self, name):
        raise AssertionError("pre-provider failure touched " + name)


class UnreachableBus:
    """LABELLED injected transport fault: the real message contract validates, then the publish
    raises the adapter's delivery error, exactly what a Redis timeout produces."""

    def __init__(self):
        self.attempts = 0

    @staticmethod
    def validate(message):
        return validate_message(message)

    def publish(self, message):
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

    def __init__(self, store):
        self.store, self.bus, self.receipts = store, UnreachableBus(), []

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
    unreachable. Records each inspected (recipient, message id)."""

    def __init__(self, present=False, error=None):
        self.present, self.error, self.calls = present, error, []

    def absent(self, recipient, message_id):
        self.calls.append((recipient, message_id))
        if self.error is not None:
            raise self.error
        return not self.present


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
        def absent(self, recipient, message_id_):
            with env.store.transaction() as tx:   # LABELLED injected race: a delivery record appears
                delivery = tx.get("outbox_delivery", message_id)
                tx.put("outbox_delivery", message_id, {**delivery, "status": "delivered", "delivered_entry_id": "9-0"})
            return True

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
    bus = type("FixtureBus", (), {"namespace": "ns", "stream": staticmethod(lambda agent: "ns:agent:" + agent)})()
    bus.client = FakeRedis(streams, fail)
    return TransportProbe(bus, limit=limit)


def test_the_transport_probe_reads_the_recipient_and_dead_letter_streams_completely_or_refuses():
    body = json.dumps({"message_id": "m-1"})
    assert probe({}).absent("lead:researcher", "m-1") is True
    assert probe({"ns:agent:lead:researcher": [("1-0", {"body": json.dumps({"message_id": "m-2"})})]}).absent(
        "lead:researcher", "m-1") is True
    assert probe({"ns:agent:lead:researcher": [("1-0", {"body": body})]}).absent("lead:researcher", "m-1") is False
    assert probe({"ns:dead-letter": [("1-0", {"body": body, "reason": "x"})]}).absent("lead:researcher", "m-1") is False
    with pytest.raises(ProgramRefused, match="recovery_transport_unbounded"):
        probe({"ns:agent:lead:researcher": [("1-0", {})] * 3}, limit=2).absent("lead:researcher", "m-1")
    with pytest.raises(ConnectionError):
        probe({}, fail=True).absent("lead:researcher", "m-1")


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
