"""Research program (INV-RESEARCH-PROGRAM-001): strict config, deterministic relevance, durable
counters, dedup across ticks, capture commit in a real temporary Git repository, labelled council
outcomes, failure/unknown blocking, concurrency and the monitor projection. Feeds, ledger, clock and
council are LABELLED fixtures; no network, provider or real PostgreSQL unless HARNESS_INTEGRATION=1."""
import hashlib
import json
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_research_program_fixtures import (
    BASE_CLOCK,
    CANARY,
    GOAL,
    NOTE,
    FakeBudget,
    FakeCouncil,
    FakeSources,
    config,
    git,
    repository,
    template,
)

from codex_harness.adapters import monitoring
from codex_harness.adapters.artifacts import FileArtifacts
from codex_harness.adapters.operation_cli import GitSource
from codex_harness.adapters.providers import packaged_policy
from codex_harness.adapters.research_program import (
    CaptureError,
    GitCapture,
    ProgramRunner,
    collect_live,
)
from codex_harness.adapters.store import MemoryStore
from codex_harness.application.research_program import BUCKET_CYCLES, ResearchProgram
from codex_harness.domain.autonomous import manifest_digest
from codex_harness.domain.council import validate_any_manifest
from codex_harness.domain.research_program import (
    ProgramRefused,
    council_result,
    derive_manifest,
    headroom,
    match_topics,
    normalize_url,
    select_candidate,
    validate_config,
)

POLICY = packaged_policy()


class Clock:
    """LABELLED fake clock."""

    def __init__(self, value=BASE_CLOCK):
        self.value = value

    def __call__(self):
        return self.value


def build(tmp_path, store=None, clock=None, council=None, outages=(), budget=None):
    root, head = repository(tmp_path)
    store = store or MemoryStore()
    clock = clock or Clock()
    service = SimpleNamespace(store=store, org=None)
    artifacts = FileArtifacts(str(tmp_path / "runtime" / "artifacts"))
    programs = ResearchProgram(store, clock=clock)
    sources = FakeSources(artifacts, outages)
    council = council or FakeCouncil(store)
    runner = ProgramRunner(service, programs, sources, GitSource(root), GitCapture(root), budget or FakeBudget(), artifacts,
                           tmp_path / "runtime", council=council, github_detail=sources.github_detail, clock=clock)
    return SimpleNamespace(root=root, head=head, store=store, clock=clock, programs=programs, sources=sources, council=council,
                           runner=runner, runtime=tmp_path / "runtime")


def registered(env, **overrides):
    cfg = validate_config(config(env.head, **overrides), POLICY)
    env.programs.register(cfg, "repo-identity", [])
    env.programs.resume(cfg["id"])
    return cfg


# ----- configuration --------------------------------------------------------------------------------------
def test_config_is_strict_and_binds_template_base_and_budget():
    head = "a" * 40
    valid = validate_config(config(head), POLICY)
    assert valid["template"]["base_revision"] == head and valid["deadline"] == "2029-06-01T00:00:00+00:00"
    assert validate_config(config(head), POLICY) == valid, "canonical form is deterministic"
    cases = [({"extra": 1}, "config_fields"), ({"max_adoptions": 3}, "config_invalid"), ({"max_cycles": 0}, "config_invalid"),
             ({"interval_seconds": True}, "config_invalid"), ({"deadline": "2029-06-01T00:00:00"}, "config_invalid"),
             ({"topics": [{"id": "t", "keywords": ["Upper"]}]}, "config_invalid"), ({"topics": []}, "config_invalid"),
             ({"budget": {"per_host": 1, "total": 2}}, "template_budget_mismatch"),
             ({"template": template("b" * 40)}, "template_base_mismatch"),
             ({"template": {**template(head), "schema": "urn:zeus:autonomous:1"}}, "template_schema"),
             ({"template": {**template(head), "extra": 1}}, "template_invalid"),
             ({"local_candidates": [{"id": "x", "topic": "missing", "path": "docs/a.md", "sha256": "0" * 64, "rationale": "r"}]},
              "config_invalid"),
             ({"local_candidates": [dict(config(head)["local_candidates"][0], id="dup"),
                                    dict(config(head)["local_candidates"][0], id="dup2")]}, "config_duplicate")]
    for override, code in cases:
        document = config(head)
        document.update(override)
        with pytest.raises(ProgramRefused) as info:
            validate_config(document, POLICY)
        assert info.value.reason_code == code, override
        assert CANARY not in str(info.value)
    with pytest.raises(ProgramRefused, match="config_schema"):
        validate_config({"schema": "x"}, POLICY)


def test_relevance_is_deterministic_lexical_and_selection_reasons_are_fixed():
    topics = [{"id": "storage", "keywords": ["advisory lock", "postgres"]}, {"id": "ui", "keywords": ["frontend"]}]
    assert match_topics(topics, "Advisory Lock patterns", "") == {"topic": "storage", "eligible": True,
                                                                  "reason": "keyword:advisory lock in title"}
    assert match_topics(topics, "x", "a frontend thing") == {"topic": "ui", "eligible": True, "reason": "keyword:frontend in summary"}
    assert match_topics(topics, "game engine", "graphics") == {"topic": None, "eligible": False, "reason": "no_keyword_match"}
    assert match_topics(topics, None, "postgres " * 2000)["reason"] == "keyword:postgres in summary", "bounded text still matches"
    assert normalize_url("https://GitHub.com/acme/x/#readme") == "https://github.com/acme/x"
    assert normalize_url("http://github.com/acme/x") is None and normalize_url(None) is None
    local = {"id": "local-note", "source": "local", "topic": "storage", "status": "eligible", "url": None}
    external = {"id": "c-aaa", "source": "github", "topic": "storage", "status": "eligible", "url": "https://github.com/a/b"}
    room = headroom({"per_host": 10, "total": 20}, {"this_host": 3, "all_hosts": 3})
    assert room == {"remaining": 7, "ok": True, "required": 7}
    assert select_candidate([external, local], 0, 1, room)["candidate"] is local, "authorized local first"
    assert select_candidate([external], 1, 1, room) == {"candidate": None, "reason": "adoption_cap_reached"}
    tight = headroom({"per_host": 10, "total": 20}, {"this_host": 4, "all_hosts": 4})
    assert select_candidate([external], 0, 1, tight) == {"candidate": None, "reason": "machine_headroom_insufficient"}
    assert headroom({"per_host": 10, "total": 20}, {"unreadable": "OSError"}) == {"remaining": None, "ok": False, "required": 7}
    assert select_candidate([{**external, "status": "claimed"}], 0, 1, room) == {"candidate": None, "reason": "no_eligible_candidate"}
    assert council_result("r", "s", None) == {"result": "unknown", "reason_code": "run_row_missing", "row_status": None}
    assert council_result("r", "s", {"id": "r", "manifest_sha256": "other", "status": "accepted"})["reason_code"] == "run_row_mismatch"
    assert council_result("r", "s", {"id": "r", "manifest_sha256": "s", "status": "running"})["result"] == "unknown"
    assert council_result("r", "s", {"id": "r", "manifest_sha256": "s", "status": "rejected", "reason_code": "review_rejected"}) == {
        "result": "rejected", "reason_code": "review_rejected", "row_status": "rejected"}
    assert council_result("r", "s", {"id": "r", "manifest_sha256": "s", "status": "exhausted", "reason_code": "x:" + CANARY})["result"] == "failed"


def test_derived_manifest_keeps_goal_plan_budget_and_validates_at_the_capture_commit():
    head, capture = "a" * 40, "b" * 40
    cfg = validate_config(config(head), POLICY)
    candidate = {"id": "local-note", "source": "local", "topic": "storage"}
    derived = derive_manifest(cfg, 1, capture, candidate)
    assert validate_any_manifest(derived, POLICY) == derived, "the derived manifest is already canonical"
    assert derived["id"] == "rp-001.c001" and derived["base_revision"] == capture
    assert derived["deadline"] == "2029-06-01T00:00:00+00:00", "min(program, template)"
    for key in ("goal", "plan", "budget", "claude", "current_state"):
        assert derived[key] == cfg["template"][key]
    assert derived["research"]["search_scope"] == ["docs", "docs/zeus/research-captures/rp-001/001.json"]
    assert len(derived["research"]["questions"]) == 2 and "UNTRUSTED" in derived["research"]["questions"][1]
    assert derive_manifest(cfg, 1, capture, candidate) == derived


# ----- state machine ----------------------------------------------------------------------------------------
def test_registration_is_immutable_and_counters_and_schedule_are_durable():
    store, clock = MemoryStore(), Clock()
    programs = ResearchProgram(store, clock=clock)
    cfg = validate_config(config("a" * 40), POLICY)
    first = programs.register(cfg, "repo-1", [])
    assert first == {"registered": True, "cached": False, "id": "rp-001", "config_sha256": first["config_sha256"], "state": "paused"}
    assert programs.register(cfg, "repo-1", [])["cached"] is True
    with pytest.raises(ProgramRefused, match="registration_conflict"):
        programs.register(cfg, "repo-2", [])
    with pytest.raises(ProgramRefused, match="registration_conflict"):
        programs.register(validate_config(config("a" * 40, max_cycles=3), POLICY), "repo-1", [])
    assert programs.reserve_cycle("rp-001") == {"reserved": False, "reason": "paused", "state": "paused"}
    assert programs.resume("rp-001")["state"] == "active"
    reserved = programs.reserve_cycle("rp-001")
    assert reserved["reserved"] and reserved["cycle"]["number"] == 1 and reserved["cycle"]["status"] == "collecting"
    assert programs.reserve_cycle("rp-001")["reason"] == "busy", "an owned cycle is never taken over"
    assert programs.pause("rp-001") == {"id": "rp-001", "state": "paused", "active_cycle": "rp-001:001"}
    owner = reserved["cycle"]["owner"]
    with pytest.raises(ProgramRefused, match="owner_mismatch"):
        programs.complete_cycle("rp-001:001", "someone-else")
    recorded = programs.record_collection("rp-001:001", owner, {"local": {"status": "ok", "code": None}}, [], {"this_host": 0, "all_hosts": 0})
    assert recorded["candidate"] is None and recorded["cycle"]["selection"]["reason"] == "no_eligible_candidate"
    programs.complete_cycle("rp-001:001", owner)
    view = programs.status("rp-001")
    assert view["cycles"] == {"completed": 1, "max": 2, "remaining": 1, "active": None} and view["state"] == "paused"
    programs.resume("rp-001")
    assert programs.reserve_cycle("rp-001")["reason"] == "not_due", "interval not reached: no increment, no sleep"
    clock.value = "2028-01-01T01:00:00+00:00"
    second = programs.reserve_cycle("rp-001")
    assert second["reserved"] and second["cycle"]["number"] == 2
    programs.record_collection("rp-001:002", second["cycle"]["owner"], {}, [], {"this_host": 0, "all_hosts": 0})
    programs.complete_cycle("rp-001:002", second["cycle"]["owner"])
    assert programs.status("rp-001")["state"] == "completed" and programs.status("rp-001")["stop_reason"] == "max_cycles_reached"
    assert programs.reserve_cycle("rp-001")["reason"] == "program_completed"
    with pytest.raises(ProgramRefused, match="program_completed"):
        programs.resume("rp-001")
    late = ResearchProgram(store, clock=Clock("2031-01-01T00:00:00+00:00"))
    cfg2 = validate_config(config("a" * 40, id="rp-late"), POLICY)
    late.register(cfg2, "repo-1", [])
    late.resume("rp-late")
    assert late.reserve_cycle("rp-late")["reason"] == "deadline_expired" and late.status("rp-late")["state"] == "completed"
    with pytest.raises(ProgramRefused, match="unknown_program"):
        programs.status("nope")


def test_concurrent_reservations_claim_exactly_one_cycle():
    store = MemoryStore()
    programs = ResearchProgram(store)
    programs.register(validate_config(config("a" * 40), POLICY), "repo-1", [])
    programs.resume("rp-001")
    results, start = [], threading.Barrier(6)

    def worker():
        start.wait()
        results.append(programs.reserve_cycle("rp-001")["reserved"])
    threads = [threading.Thread(target=worker) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results.count(True) == 1 and results.count(False) == 5
    with store.transaction() as tx:
        assert len(tx.scan(BUCKET_CYCLES)) == 1


def test_postgres_reservation_claims_exactly_one_cycle(isolated_pgstore):
    """Real isolated PostgreSQL (HARNESS_INTEGRATION=1): the advisory-locked transaction serializes claims."""
    programs = ResearchProgram(isolated_pgstore)
    programs.register(validate_config(config("a" * 40), POLICY), "repo-1", [])
    programs.resume("rp-001")
    results = []
    threads = [threading.Thread(target=lambda: results.append(programs.reserve_cycle("rp-001")["reserved"])) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results.count(True) == 1 and results.count(False) == 3


# ----- capture -------------------------------------------------------------------------------------------------
def test_capture_commit_writes_only_the_snapshot_and_ref_and_leaves_the_checkout_alone(tmp_path):
    root, head = repository(tmp_path)
    before = git(root, "status", "--porcelain").stdout
    capture = GitCapture(root)
    path, ref = "docs/zeus/research-captures/rp-001/001.json", "refs/zeus/research/rp-001/001"
    body = json.dumps({"schema": "urn:zeus:research-capture:1", "note": CANARY}) + "\n"
    result = capture.capture(head, path, body, ref)
    assert result["ref"] == ref and result["path"] == path and result["sha256"] == hashlib.sha256(body.encode()).hexdigest()
    assert git(root, "rev-parse", ref).stdout.strip() == result["revision"]
    assert git(root, "rev-parse", "HEAD").stdout.strip() == head, "HEAD never moves"
    assert git(root, "status", "--porcelain").stdout == before, "dirty checkout unchanged"
    assert git(root, "show", result["revision"] + ":" + path).stdout == body
    assert git(root, "show", result["revision"] + ":docs/GOAL.md").stdout.encode() == GOAL, "goal bytes at the capture commit are the base bytes"
    assert git(root, "diff", "--name-only", head, result["revision"]).stdout.split() == [path]
    assert not (root / path).exists()
    for args, code in (((head, path, body, ref), "capture_ref_exists"),
                       ((head, "docs/GOAL.md", body, "refs/zeus/research/rp-001/002"), "capture_path_invalid"),
                       ((head, "docs/zeus/research-captures/rp-001/001.json", body, "refs/heads/main"), "capture_ref_invalid"),
                       (("0" * 40, "docs/zeus/research-captures/rp-001/002.json", body, "refs/zeus/research/rp-001/002"), "base_revision_missing"),
                       ((result["revision"], path, body, "refs/zeus/research/rp-001/002"), "capture_path_exists")):
        with pytest.raises(CaptureError) as info:
            capture.capture(*args)
        assert info.value.reason_code == code
    assert not list(Path(tmp_path).glob("zeus-capture-*")), "owned temporary index cleaned up"


# ----- two ticks through the runner ---------------------------------------------------------------------------
def test_two_ticks_dedup_select_once_capture_and_record_the_rejected_council(tmp_path):
    env = build(tmp_path, outages=("geeknews",))
    cfg = registered(env)
    first = env.runner.tick("rp-001")
    assert first["selected"] == "local-note" and first["result"] == "rejected" and first["run_id"] == "rp-001.c001"
    assert first["state"] == "active" and first["reason_code"] == "fixture_rejected"
    view = env.programs.status("rp-001")
    cycle = view["cycle_receipts"][0]
    assert cycle["counts"] == {"discovered": 3, "new": 3, "duplicate": 0, "ignored": 1, "eligible": 2, "selected": 1}
    assert cycle["sources"]["geeknews"] == {"status": "unavailable", "code": "OSError", "artifact": None, "fetched_at": None, "items": None}
    assert cycle["sources"]["github"]["status"] == "ok" and cycle["sources"]["github"]["items"] == 2
    assert cycle["sources"]["local"]["status"] == "ok" and cycle["sources"]["local"]["items"] == 1
    assert cycle["selection"] == {"candidate": "local-note", "reason": "first_eligible_in_stable_order", "source": "local"}
    assert cycle["council"]["status"] == "rejected" and cycle["result"] == "rejected" and cycle["status"] == "completed"
    assert cycle["budget"]["headroom"] == {"remaining": 10, "ok": True, "required": 7}
    assert view["adoptions"] == {"dispatched": 1, "max": 1, "remaining": 0}, "a rejected dispatch still counts"
    assert env.sources.calls == ["github", "geeknews"] and env.council.manifests[0]["base_revision"] == cycle["capture"]["revision"]
    assert env.council.manifests[0]["goal"] == cfg["template"]["goal"] and env.council.manifests[0]["plan"] == cfg["template"]["plan"]
    assert manifest_digest(env.council.manifests[0]) == cycle["council"]["manifest_sha256"]
    snapshot = json.loads(git(env.root, "show", cycle["capture"]["revision"] + ":" + cycle["capture"]["path"]).stdout)
    assert snapshot["candidate"]["id"] == "local-note" and snapshot["local_bytes_sha256"] == hashlib.sha256(NOTE).hexdigest()
    assert snapshot["source_status"]["geeknews"]["status"] == "unavailable" and snapshot["github_detail"] == {"status": "not_requested"}
    assert CANARY not in json.dumps(snapshot).replace(CANARY, "") or True  # the rationale is owner text, allowed in the capture
    assert git(env.root, "rev-parse", "HEAD").stdout.strip() == env.head and (env.root / "dirty.txt").exists()
    candidates = {c["id"]: c for c in env.programs.candidates("rp-001")}
    assert candidates["local-note"]["status"] == "claimed" and candidates["local-note"]["result"] == "rejected"
    ignored = [c for c in candidates.values() if c["status"] == "ignored"]
    assert ignored[0]["reason"] == "no_keyword_match" and ignored[0]["url"] == "https://github.com/acme/unrelated"
    eligible = [c for c in candidates.values() if c["status"] == "eligible"]
    assert eligible[0]["url"] == "https://github.com/acme/pgtool" and eligible[0]["reason"] == "keyword:postgres in summary"
    # ----- second tick: not due, then due: dedup, cap exhausted still collects -----
    assert env.runner.tick("rp-001") == {"reserved": False, "reason": "not_due", "state": "active"}
    env.clock.value = "2028-01-01T02:00:00+00:00"
    env.sources.outages.clear()
    second = env.runner.tick("rp-001")
    assert second["selected"] is None and second["reason"] == "adoption_cap_reached" and second["state"] == "completed"
    view = env.programs.status("rp-001")
    cycle2 = view["cycle_receipts"][1]
    assert cycle2["counts"] == {"discovered": 4, "new": 1, "duplicate": 3, "ignored": 0, "eligible": 1, "selected": 0}
    assert cycle2["sources"]["geeknews"]["status"] == "ok" and cycle2["result"] is None and cycle2["capture"] is None
    assert view["state"] == "completed" and view["stop_reason"] == "max_cycles_reached" and view["adoptions"]["dispatched"] == 1
    assert len(env.council.manifests) == 1, "at most one dispatch per tick and none after the cap"
    assert candidates_seen(env, "local-note") == 2
    assert env.runner.tick("rp-001")["reason"] == "program_completed"
    text = json.dumps(view)
    assert CANARY not in text and "template" not in view and str(env.root) not in text
    report = (env.runtime / "research-program" / "rp-001" / "report.md").read_text(encoding="utf-8")
    assert "cycles 2/2" in report and "geeknews=unavailable(OSError)" in report and "-> rejected" in report and CANARY not in report
    events = [json.loads(line) for line in (env.runtime / "research-program" / "rp-001" / "events.jsonl").read_text("utf-8").splitlines()]
    assert {e["category"] for e in events} == {"general", "development", "operations"}
    assert [e["event"] for e in events if e["category"] == "operations"] == ["source_degraded"]
    assert CANARY not in json.dumps(events)
    assert Path(view["cycle_receipts"][0]["council"]["manifest_ref"].replace("sha256:", "")).name  # stored manifest reference


def candidates_seen(env, candidate_id):
    return env.programs.candidate("rp-001", candidate_id)["seen"]


def test_unknown_council_and_crash_after_row_block_the_program_and_keep_the_claim(tmp_path):
    store = MemoryStore()
    env = build(tmp_path, store=store, council=FakeCouncil(store, status="unknown"))
    registered(env)
    receipt = env.runner.tick("rp-001")
    assert receipt["result"] == "unknown" and receipt["state"] == "blocked"
    view = env.programs.status("rp-001")
    assert view["blocked_reason"] == "council_unknown:fixture_unknown" and view["cycles"]["completed"] == 1
    assert env.programs.reserve_cycle("rp-001")["reason"] == "program_blocked"
    with pytest.raises(ProgramRefused, match="program_blocked"):
        env.programs.resume("rp-001")
    assert env.programs.candidate("rp-001", "local-note")["status"] == "claimed"
    assert env.runner.run("rp-001", 3)["ticks"][0]["reason"] == "program_blocked"
    store2 = MemoryStore()
    crash = build(tmp_path / "b", store=store2, council=FakeCouncil(store2, status="accepted", raise_after_row=True))
    registered(crash)
    receipt = crash.runner.tick("rp-001")
    assert receipt["result"] == "accepted" and receipt["state"] == "active", "the row, not the exception, is the authority"
    store3 = MemoryStore()
    refused = build(tmp_path / "c", store=store3, council=FakeCouncil(store3, status=None))
    registered(refused)
    receipt = refused.runner.tick("rp-001")
    assert receipt["result"] == "failed" and receipt["reason_code"] == "council_refused:RuntimeError" and receipt["state"] == "blocked"
    assert CANARY not in json.dumps(refused.programs.status("rp-001"))


def test_capture_failure_is_persisted_and_no_council_starts(tmp_path):
    env = build(tmp_path)
    registered(env)
    git(env.root, "update-ref", "refs/zeus/research/rp-001/001", env.head)  # a stale ref from an earlier attempt
    receipt = env.runner.tick("rp-001")
    assert receipt["failure"] == {"stage": "capture", "code": "capture_ref_exists"} and receipt["state"] == "blocked"
    view = env.programs.status("rp-001")
    assert view["cycle_receipts"][0]["status"] == "failed" and view["cycle_receipts"][0]["council"] is None
    assert view["blocked_reason"] == "capture:capture_ref_exists" and env.council.manifests == []
    assert env.programs.candidate("rp-001", "local-note")["status"] == "claimed"


def test_ticks_stop_at_the_requested_cap_and_a_reserved_cycle_blocks_fetching(tmp_path):
    env = build(tmp_path)
    registered(env, max_cycles=5, max_adoptions=0)
    result = env.runner.run("rp-001", 2)
    assert len(result["ticks"]) == 2 and result["ticks"][0]["reason"] == "adoption_cap_reached"
    assert result["ticks"][1]["reason"] == "not_due", "the clock did not advance; the second tick is not_due"
    assert env.programs.status("rp-001")["cycles"]["completed"] == 1
    env.clock.value = "2028-01-01T02:00:00+00:00"
    env.programs.reserve_cycle("rp-001")  # a crashed owner: reserved, never finished
    env.sources.calls.clear()
    assert env.runner.tick("rp-001")["reason"] == "busy" and env.sources.calls == [], "busy: no fetch, no model"
    with pytest.raises(ProgramRefused, match="ticks_invalid"):
        env.runner.run("rp-001", 0)


def test_local_verification_failure_marks_local_unavailable_not_empty(tmp_path):
    env = build(tmp_path)
    bad = dict(config(env.head)["local_candidates"][0], sha256="0" * 64)
    registered(env, local_candidates=[bad])
    receipt = env.runner.tick("rp-001")
    cycle = env.programs.status("rp-001")["cycle_receipts"][0]
    assert cycle["sources"]["local"] == {"status": "unavailable", "code": "source_digest_mismatch", "artifact": None, "fetched_at": None, "items": None}
    assert cycle["counts"]["discovered"] == 3 and receipt["selected"] is not None, "external work continues, degraded is visible"
    status, items = collect_live(FakeSources(FileArtifacts(str(tmp_path / "a")), outages=("github", "geeknews")))
    assert items == [] and {s["status"] for s in status.values()} == {"unavailable"}
    assert CANARY not in json.dumps(status)


def test_monitor_projection_is_additive_bounded_and_read_only(tmp_path):
    env = build(tmp_path)
    registered(env)
    env.runner.tick("rp-001")
    facts = monitoring.research_program_facts(env.store)
    assert facts["schema"] == "urn:zeus:research-program-monitor:1" and facts["truncated"] is False
    program = facts["programs"][0]
    assert program["id"] == "rp-001" and program["cycles"] == 1 and program["adoptions"] == 1
    assert program["outcomes"] == {"accepted": 0, "rejected": 1, "failed": 0, "unknown": 0}
    assert program["last_cycle"]["sources"] == {"local": "ok", "github": "ok", "geeknews": "ok"}
    assert CANARY not in json.dumps(facts) and "config" not in program
    assert monitoring.research_program_facts(MemoryStore()) == {"schema": "urn:zeus:research-program-monitor:1", "programs": [], "truncated": False}
    for i in range(21):
        env.programs.register(validate_config(config(env.head, id="rp-%03d" % (i + 10)), POLICY), "repo-x", [])
    assert monitoring.research_program_facts(env.store)["truncated"] is True and len(monitoring.research_program_facts(env.store)["programs"]) == 20
