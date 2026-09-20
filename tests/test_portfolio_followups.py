"""Owner-linked follow-ups and per-project activity (operating-portfolio-001 STATUS 2026-09-20).

The question this batch answers on screen is "what is running now, what still needs attention, and
which old failure already has an accepted successor" - so these tests pin exactly the boundary
between the three. A link is the owner's immutable record that an ACCEPTED successor job was
recorded for one preserved failure; it is never "the incident is fixed", never criterion
acceptance, and never inferred from a name, a lane or a timestamp. A successor that is queued,
dispatching, `unknown`, gone or bound elsewhere leaves the history unresolved.

Fleet rows come from the real `Fleet` API through the `test_portfolio` fixtures (no process, no
provider). Where a case cannot be produced through the owner API at all - a binding that changed
after the link was written - the rows are clearly labelled synthetic fixture input to the real
projection, and they are never presented as observed store state.
"""
import json
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from types import SimpleNamespace

import pytest
from test_portfolio import CANARY, CRITERION, PROJECT, REFS, clock, config, enqueue, finish, fleet

from codex_harness.adapters import monitoring
from codex_harness.adapters.portfolio import packaged_definitions, portfolio
from codex_harness.adapters.store import MemoryStore
from codex_harness.application.fleet import BUCKET_JOBS, Fleet
from codex_harness.application.portfolio import (
    BUCKET_FOLLOWUPS,
    Portfolio,
    PortfolioRefused,
    status_projection,
)

OTHER_CRITERION = "coverage"            # same project, a different criterion
OTHER_PROJECT = ("research-improvement", "recurrence")
LINKED_AT = "2026-09-20T05:00:00+00:00"
EMPTY = {"mode": "not_started", "running": 0, "queued": 0, "unknown": 0, "accepted": 0,
         "unresolved_failed": 0, "historical_failed": 0}


def owner(store, marks=None):
    """A Portfolio whose clock is fixed, so a recorded time is asserted rather than guessed."""
    return Portfolio(store, packaged_definitions(), clock=clock(list(marks or [LINKED_AT])))


def definitions():
    return Portfolio(MemoryStore(), packaged_definitions()).definitions


def project_view(view, project_id: str = PROJECT) -> dict:
    return next(p for p in view["projects"] if p["id"] == project_id)


def entries(view, project_id: str = PROJECT) -> dict:
    return {job["id"]: job for job in project_view(view, project_id)["jobs"]}


# ----- synthetic fixture rows: real projection input, never observed store state ---------------
def row(job_id: str, status: str, updated: str = "2026-09-20T00:00:00+00:00", reason=None) -> dict:
    return {"id": job_id, "status": status, "lane": "a", "reason_code": reason, "updated_at": updated}


def bound(job_id: str, project_id: str = PROJECT, criterion_id: str = CRITERION) -> dict:
    return {"id": job_id, "job_id": job_id, "project_id": project_id, "criterion_id": criterion_id}


def link(failed_id: str, successor_id: str, refs=REFS) -> dict:
    return {"id": failed_id, "failed_job_id": failed_id, "successor_job_id": successor_id,
            "evidence_refs": list(refs), "created_at": LINKED_AT}


def test_owner_link_joins_one_failure_to_its_accepted_successor_and_preserves_the_failure(tmp_path):
    f = fleet(tmp_path)
    book = portfolio(f.store, packaged_definitions())
    failed = finish(f, "op-fail", "failed", "child_refused")
    successor = finish(f, "op-next", "accepted", "lead_accepted")
    book.bind(failed, PROJECT, CRITERION)
    book.bind(successor, PROJECT, CRITERION)
    before = deepcopy(f.store.data[BUCKET_JOBS, failed])

    recorded = owner(f.store).follow_up(failed, successor, REFS)
    assert recorded["cached"] is False
    assert recorded["follow_up"] == {
        "id": failed, "failed_job_id": failed, "successor_job_id": successor,
        "project_id": PROJECT, "criterion_id": CRITERION, "evidence_refs": REFS,
        "authority": "owner_linked", "recorded_by": "owner", "created_at": LINKED_AT}
    # The failure receipt itself is untouched: history is linked, never rewritten or deleted.
    assert f.store.data[BUCKET_JOBS, failed] == before
    assert [key[1] for key in f.store.data if key[0] == BUCKET_FOLLOWUPS] == [failed]

    view = book.status()
    shown = entries(view)
    assert shown[failed]["status"] == "failed" and shown[failed]["reason_code"] == "child_refused"
    assert shown[failed]["follow_up"] == {
        "successor_job_id": successor, "successor_status": "accepted", "state": "linked",
        "reason": None, "evidence_refs": REFS, "recorded_at": LINKED_AT}
    assert "follow_up" not in shown[successor]      # the successor is work, not a link of its own
    assert project_view(view)["activity"] == {
        "mode": "idle", "running": 0, "queued": 0, "unknown": 0, "accepted": 1,
        "unresolved_failed": 0, "historical_failed": 1}
    # A linked follow-up is not criterion acceptance and not the owner's completion decision.
    assert {c["status"] for c in project_view(view)["criteria"]} == {"pending"}
    assert project_view(view)["counts"]["criteria_accepted"] == 0
    assert project_view(view, OTHER_PROJECT[0])["activity"] == EMPTY      # zero-job project
    # The returned record is a copy: mutating it never reaches the store or the next projection.
    recorded["follow_up"]["evidence_refs"].append(CANARY)
    assert CANARY not in json.dumps(book.status())


def test_link_is_refused_unless_both_jobs_are_bound_accepted_and_on_the_same_criterion(tmp_path):
    f = fleet(tmp_path)
    book = portfolio(f.store, packaged_definitions())
    failed = finish(f, "op-fail", "failed", "child_refused")
    exhausted = finish(f, "op-spent", "exhausted", "budget_exhausted")
    orphan = finish(f, "op-orphan", "failed", "child_refused")          # deliberately unbound
    elsewhere = finish(f, "op-elsewhere", "accepted", "lead_accepted")
    unbound = finish(f, "op-unbound", "accepted", "lead_accepted")      # deliberately unbound
    successor = finish(f, "op-next", "accepted", "lead_accepted")
    repair = finish(f, "op-repair", "accepted", "lead_accepted")
    queued = enqueue(f, "op-queued")                                     # created last: stays queued
    for job_id in (failed, exhausted, repair, queued):
        book.bind(job_id, PROJECT, CRITERION)
    book.bind(elsewhere, *OTHER_PROJECT)
    book.bind(successor, PROJECT, OTHER_CRITERION)

    refusals = [
        (("op-absent", successor, REFS), "job_unknown"),
        ((failed, "op-absent", REFS), "job_unknown"),
        ((failed, failed, REFS), "followup_invalid"),
        (("", successor, REFS), "followup_invalid"),
        ((failed, 3, REFS), "followup_invalid"),
        ((successor, failed, REFS), "followup_origin_invalid"),   # an accepted job is not history
        ((queued, successor, REFS), "followup_origin_invalid"),
        ((failed, queued, REFS), "successor_not_accepted"),       # queued work resolves nothing
        ((orphan, unbound, REFS), "binding_missing"),
        ((failed, unbound, REFS), "binding_missing"),
        ((failed, elsewhere, REFS), "followup_target_mismatch"),  # other project
        ((failed, successor, REFS), "followup_target_mismatch"),  # other criterion
        ((failed, successor, []), "evidence_invalid"),
        ((failed, successor, [CANARY * 40]), "evidence_invalid"),
    ]
    for arguments, reason_code in refusals:
        with pytest.raises(PortfolioRefused) as info:
            book.follow_up(*arguments)
        assert info.value.reason_code == reason_code, arguments
        assert CANARY not in str(info.value)           # refusals name a field, never a value
    assert [key for key in f.store.data if key[0] == BUCKET_FOLLOWUPS] == []

    # `exhausted` is history the owner may link; the successor must share project AND criterion.
    assert book.follow_up(exhausted, repair, REFS)["cached"] is False
    assert entries(book.status())[exhausted]["follow_up"]["state"] == "linked"
    activity = project_view(book.status())["activity"]
    assert (activity["historical_failed"], activity["unresolved_failed"]) == (1, 1)
    assert activity["mode"] == "queued" and activity["queued"] == 1


def test_link_is_immutable_replayed_exactly_and_refuses_a_conflicting_rewrite(tmp_path):
    f = fleet(tmp_path)
    book = portfolio(f.store, packaged_definitions())
    failed = finish(f, "op-fail", "failed", "child_refused")
    first = finish(f, "op-next", "accepted", "lead_accepted")
    second = finish(f, "op-other", "accepted", "lead_accepted")
    for job_id in (failed, first, second):
        book.bind(job_id, PROJECT, CRITERION)
    assert owner(f.store).follow_up(failed, first, REFS)["cached"] is False
    stored = deepcopy(f.store.data[BUCKET_FOLLOWUPS, failed])

    replay = owner(f.store, ["2026-09-21T09:00:00+00:00"]).follow_up(failed, first, list(REFS))
    assert replay == {"linked": True, "cached": True, "follow_up": stored}
    for arguments in ((failed, second, REFS), (failed, first, [REFS[0]]), (failed, first, REFS[::-1])):
        with pytest.raises(PortfolioRefused) as info:
            book.follow_up(*arguments)
        assert info.value.reason_code == "followup_conflict"
    assert f.store.data[BUCKET_FOLLOWUPS, failed] == stored
    assert [key[1] for key in f.store.data if key[0] == BUCKET_FOLLOWUPS] == [failed]


def test_two_concurrent_links_for_one_failure_leave_exactly_one_row(tmp_path):
    """The existing serialized store decides; no new locking, no partial row, no silent overwrite."""
    f = fleet(tmp_path)
    book = portfolio(f.store, packaged_definitions())
    failed = finish(f, "op-fail", "failed", "child_refused")
    first = finish(f, "op-next", "accepted", "lead_accepted")
    second = finish(f, "op-other", "accepted", "lead_accepted")
    for job_id in (failed, first, second):
        book.bind(job_id, PROJECT, CRITERION)

    def attempt(successor):
        try:
            return book.follow_up(failed, successor, REFS)["follow_up"]["successor_job_id"]
        except PortfolioRefused as refusal:
            return refusal.reason_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = set(pool.map(attempt, (first, second)))
    rows = [value for key, value in f.store.data.items() if key[0] == BUCKET_FOLLOWUPS]
    assert len(rows) == 1 and rows[0]["failed_job_id"] == failed
    assert rows[0]["successor_job_id"] in {first, second}
    # One writer recorded the link, the other was refused: never two rows and never an overwrite.
    assert results == {"followup_conflict", rows[0]["successor_job_id"]}


def test_a_link_the_current_rows_no_longer_support_reads_as_unknown_never_resolved():
    """Synthetic fixture rows (not observed): every way a recorded link can stop being supported."""
    jobs = [row("op-a", "failed", reason="child_refused"), row("op-b", "rejected", reason="lead_rejected"),
            row("op-c", "failed", reason="child_refused"), row("op-d", "exhausted", reason="budget_exhausted"),
            row("op-running", "dispatching"), row("op-free", "accepted"),
            row("op-elsewhere", "accepted")]
    bindings = [bound(job["id"]) for job in jobs if job["id"] not in {"op-free", "op-elsewhere"}]
    bindings.append(bound("op-elsewhere", PROJECT, OTHER_CRITERION))
    links = [link("op-a", "op-gone"), link("op-b", "op-running"),
             link("op-c", "op-free"), link("op-d", "op-elsewhere")]
    view = status_projection(definitions(), jobs, bindings, [], [], links)
    shown = entries(view)
    assert [(shown[job]["follow_up"]["state"], shown[job]["follow_up"]["reason"],
             shown[job]["follow_up"]["successor_status"])
            for job in ("op-a", "op-b", "op-c", "op-d")] == [
        ("unknown", "successor_missing", None),
        ("unknown", "successor_not_accepted", "dispatching"),
        ("unknown", "binding_missing", "accepted"),
        ("unknown", "target_mismatch", "accepted")]
    # The evidence the owner recorded stays visible on an unknown link; only the reading changed.
    assert shown["op-a"]["follow_up"]["evidence_refs"] == REFS
    assert project_view(view)["activity"] == {
        "mode": "running", "running": 1, "queued": 0, "unknown": 0, "accepted": 1,
        "unresolved_failed": 4, "historical_failed": 0}
    # A running project still reports its old unresolved failures: both counts, never one.
    assert project_view(view)["counts"]["jobs_total"] == 6      # `op-free` is unbound


def test_activity_counts_the_full_population_and_the_mode_never_hides_uncertainty():
    jobs = [row("op-%03d" % n, "accepted", updated="2026-09-20T00:%02d:00+00:00" % n) for n in range(51)]
    jobs += [row("op-fail", "failed", "2026-09-20T02:00:00+00:00", "child_refused"),
             row("op-old", "failed", "2026-09-20T02:01:00+00:00", "child_refused"),
             row("op-run", "dispatching", "2026-09-20T02:02:00+00:00"),
             row("op-wait", "queued", "2026-09-20T02:03:00+00:00"),
             row("op-huh", "receipt_pending", "2026-09-20T02:04:00+00:00")]
    bindings = [bound(job["id"]) for job in jobs]
    links = [link("op-old", "op-000")]
    full = status_projection(definitions(), jobs, bindings, [], [], links)
    project = project_view(full)
    assert project["counts"]["jobs_total"] == 56 and project["jobs_truncated"] is True
    assert len(project["jobs"]) == 50            # the sample is bounded, the counts are not
    activity = project["activity"]
    assert activity == {"mode": "unknown", "running": 1, "queued": 1, "unknown": 1, "accepted": 51,
                        "unresolved_failed": 1, "historical_failed": 1}
    # Every bound job lands in exactly one bucket, so the counts add up to the full population.
    assert sum(value for key, value in activity.items() if key != "mode") == 56
    # `receipt_pending` is not a status this projection knows: uncertain, never idle or resolved.
    lone = status_projection(definitions(), [row("op-huh", "receipt_pending")], [bound("op-huh")], [], [])
    assert project_view(lone)["activity"] == {
        "mode": "unknown", "running": 0, "queued": 0, "unknown": 1, "accepted": 0,
        "unresolved_failed": 0, "historical_failed": 0}

    def mode(statuses, links=()):
        rows = [row("op-%d" % n, status) for n, status in enumerate(statuses)]
        view = status_projection(definitions(), rows, [bound(r["id"]) for r in rows], [], [], links)
        return project_view(view)["activity"]["mode"]
    assert mode([]) == "not_started"
    assert mode(["dispatching", "failed"]) == "running"
    assert mode(["queued", "rejected"]) == "queued"
    assert mode(["exhausted", "accepted"]) == "needs_attention"
    assert mode(["accepted"]) == "idle"
    assert mode(["failed", "accepted"], [link("op-0", "op-1")]) == "idle"
    assert mode(["unknown", "accepted"]) == "unknown"


def test_a_collector_without_follow_up_rows_keeps_the_previous_shape(tmp_path):
    """The optional argument is additive: an older caller gets exactly what it got before, plus an
    activity summary in which no failure is claimed to be resolved."""
    jobs = [row("op-fail", "failed", reason="child_refused"), row("op-next", "accepted")]
    bindings = [bound(job["id"]) for job in jobs]
    legacy = status_projection(definitions(), jobs, bindings, [], [])
    assert all("follow_up" not in job for job in project_view(legacy)["jobs"])
    assert project_view(legacy)["activity"] == {
        "mode": "needs_attention", "running": 0, "queued": 0, "unknown": 0, "accepted": 1,
        "unresolved_failed": 1, "historical_failed": 0}
    with_links = status_projection(definitions(), jobs, bindings, [], [], [link("op-fail", "op-next")])
    assert project_view(with_links)["activity"]["historical_failed"] == 1
    stripped = {key: value for key, value in project_view(with_links).items() if key != "activity"}
    stripped["jobs"] = [{k: v for k, v in job.items() if k != "follow_up"} for job in stripped["jobs"]]
    assert stripped == {key: value for key, value in project_view(legacy).items() if key != "activity"}


def test_monitor_envelope_carries_the_additive_fields_without_touching_the_store(tmp_path, monkeypatch):
    monkeypatch.setattr(monitoring, "docker_facts", lambda repository, containers=None: [])
    monkeypatch.setattr(monitoring, "redis_facts", lambda url, agents: [])
    f = fleet(tmp_path)
    book = portfolio(f.store, packaged_definitions())
    failed = finish(f, "op-fail", "failed", "child_refused")
    successor = finish(f, "op-next", "accepted", "lead_accepted")
    book.bind(failed, PROJECT, CRITERION)
    book.bind(successor, PROJECT, CRITERION)
    owner(f.store).follow_up(failed, successor, REFS)
    service, _ = monitoring.read_only(SimpleNamespace(store=f.store, org=SimpleNamespace(agents={})), None)
    before = deepcopy(f.store.data)
    envelope = monitoring.collect(service, None, str(tmp_path), "redis://127.0.0.1/0")["sources"]["portfolio"]
    assert envelope["status"] == "ok"
    project = project_view(envelope["data"])
    assert project["activity"]["historical_failed"] == 1 and project["activity"]["mode"] == "idle"
    assert entries(envelope["data"])[failed]["follow_up"]["state"] == "linked"
    text = json.dumps(envelope)
    assert CANARY not in text and str(tmp_path) not in text
    assert f.store.data == before          # the collector still only reads


def test_link_over_postgres_is_one_atomic_row(isolated_pgstore, tmp_path):
    """Integration (HARNESS_INTEGRATION=1): the same behaviour on the real transactional store."""
    f = Fleet(isolated_pgstore)
    f.register(config(tmp_path))
    book = portfolio(isolated_pgstore, packaged_definitions())
    failed = finish(f, "op-fail", "failed", "child_refused")
    successor = finish(f, "op-next", "accepted", "lead_accepted")
    other = finish(f, "op-other", "accepted", "lead_accepted")
    for job_id in (failed, successor, other):
        book.bind(job_id, PROJECT, CRITERION)
    assert book.follow_up(failed, successor, REFS)["cached"] is False
    assert book.follow_up(failed, successor, REFS)["cached"] is True
    with pytest.raises(PortfolioRefused) as info:
        book.follow_up(failed, other, REFS)
    assert info.value.reason_code == "followup_conflict"
    with isolated_pgstore.transaction() as tx:
        rows = tx.scan(BUCKET_FOLLOWUPS)
        assert tx.get(BUCKET_JOBS, failed)["status"] == "failed"
    assert [(r["failed_job_id"], r["successor_job_id"]) for r in rows] == [(failed, successor)]
    assert entries(book.status())[failed]["follow_up"]["state"] == "linked"
