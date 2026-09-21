"""Owner relocation of lane repository and runtime paths (storage-recovery-001, INV-FLEET-001).

The filesystem side is real: actual temporary Git checkouts, actual copied files and an actual
service lifecycle journal, so the target identity, the pinned queued bases, the goal bytes and the
copy manifest are read from things that exist. Docker is UNAVAILABLE here, so retained isolation
runs are answered by labelled fault injection (`running`, `unavailable`), never by a daemon. No
provider, no PostgreSQL and no model is reached by anything in this file, and no file is moved or
deleted by the code under test.

Platform note: the symlink escape case needs a symlink the OS will create. Windows grants that only
to a privileged or developer-mode session (and expresses the same escape as a junction), so that
one case skips with its reason instead of pretending to have run.
"""
import hashlib
import json
import os
from copy import deepcopy

import pytest

from codex_harness.adapters.commands import run_process
from codex_harness.adapters.fleet_recovery import collect_relocation_proof, run_root, runner_state
from codex_harness.adapters.providers import packaged_policy
from codex_harness.adapters.store import MemoryStore
from codex_harness.application.fleet import (
    BUCKET_JOBS,
    BUCKET_REGISTRY,
    BUCKET_RELOCATION,
    Fleet,
)
from codex_harness.domain.fleet import FleetRefused, repository_identity, resolve_repository
from codex_harness.domain.fleet_recovery import (
    COPY_MANIFEST_SCHEMA,
    REQUEST_SCHEMA,
    relocated_config,
    validate_relocation_request,
)
from codex_harness.domain.operation import validate_manifest

CANARY = "CANARY-must-never-be-emitted"
NOW = "2026-09-22T00:30:00+09:00"
GOAL_BYTES = b"# Goal\nrecover the storage\n"


def git(root, *args):
    result = run_process(["git", *args], cwd=str(root))
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def repository(path, *, goal: bytes = GOAL_BYTES) -> str:
    path.mkdir(parents=True)
    git(path, "init", "-b", "main")
    git(path, "config", "user.name", "Fixture")
    git(path, "config", "user.email", "fixture@localhost")
    (path / "docs").mkdir()
    (path / "docs" / "GOAL.md").write_bytes(goal)
    git(path, "add", ".")
    git(path, "commit", "-m", "Initial fixture")
    return git(path, "rev-parse", "HEAD")


def clone(tmp_path, source, target, *shared):
    git(tmp_path, "clone", "--quiet", *shared, str(source), str(target))
    return target


def manifest(op_id, paths, base):
    return validate_manifest({
        "schema": "urn:zeus:operation:1", "id": op_id, "base_revision": base,
        "goal": {"path": "docs/GOAL.md", "sha256": hashlib.sha256(GOAL_BYTES).hexdigest(),
                 "criterion": "crit " + op_id, "rationale": CANARY},
        "plan": {"objective": CANARY, "acceptance_criteria": ["ok"], "allowed_paths": paths},
        "budget": {"per_host": 4, "total": 8},
        "claude": {"model": "claude-fixture-model", "timeout_seconds": 120, "max_budget_usd": 1.0}},
        packaged_policy())


def goal_of(base):
    return {"path": "docs/GOAL.md", "sha256": hashlib.sha256(GOAL_BYTES).hexdigest(),
            "criterion": "c", "base_revision": base, "bytes": len(GOAL_BYTES)}


def journal(tmp_path, *, finished: bool = True, name="fleet-journal.log", raw: bytes | None = None):
    path = tmp_path / name
    if raw is not None:
        path.write_bytes(raw)
        return path
    lines = [{"event": "start", "run_id": "0" * 32, "timestamp": NOW},
             {"event": "exit", "run_id": "0" * 32, "final_exit_code": 0, "timestamp": NOW},
             {"event": "start", "run_id": "1" * 32, "timestamp": NOW}]
    if finished:
        lines.append({"event": "finish", "run_id": "1" * 32, "reason": "ok", "timestamp": NOW})
        lines.append({"event": "exit", "run_id": "1" * 32, "final_exit_code": 0, "timestamp": NOW})
    path.write_text("\n".join(json.dumps(line, sort_keys=True) for line in lines) + "\n", encoding="utf-8")
    return path


def copy_manifest(tmp_path, destinations, *, corrupt=False):
    entries = []
    for index, destination in enumerate(destinations):
        destination.parent.mkdir(parents=True, exist_ok=True)
        data = ("copied evidence %d\n" % index).encode("utf-8")
        destination.write_bytes(data)
        recorded = hashlib.sha256(data).hexdigest()
        if corrupt and index == 0:
            destination.write_bytes(data + b"tampered")  # the copy no longer is what was verified
        entries.append({"source": str(tmp_path / ("original-%d.txt" % index)),
                        "destination": str(destination), "sha256": recorded, "bytes": len(data)})
    document = {"schema": COPY_MANIFEST_SCHEMA, "entries": entries}
    path = tmp_path / "copy-manifest.json"
    path.write_text(json.dumps(document, sort_keys=True), encoding="utf-8")
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "entries": len(entries)}


def stopped(_container_id):
    return {"status": "exited", "exit_code": 255}


def running(_container_id):
    return {"status": "running", "exit_code": None}


def unavailable(_container_id):
    """Injected fault: Docker could not answer about this retained run."""
    return None


def write_run_record(runtime, **overrides):
    record = {"run_id": "ab" * 16, "role": "worker", "workspace": str(runtime),
              "container": "c" * 64, "container_name": "zeus-worker-" + "ab" * 16,
              "state": "stop_unconfirmed", "lifecycle": [], **overrides}
    directory = run_root(str(runtime)) / record["run_id"]
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "run.json").write_text(json.dumps(record, sort_keys=True), encoding="utf-8")
    return directory / "run.json"


def setup(tmp_path, *, shared_repository=False, queued=("op-1",)):
    """One registered, paused fleet with real source checkouts and prepared copies."""
    source = tmp_path / "old" / "repo-a"
    base = repository(source)
    other = tmp_path / "old" / "repo-b"
    repository(other) if not shared_repository else None
    lane_b_repository = str(source if shared_repository else other)
    lanes = [{"id": "a", "team": "alpha", "repository": str(source), "schema": "lane_a",
              "redis_namespace": "fleet-a", "runtime": str(tmp_path / "old" / "rt-a")},
             {"id": "b", "team": "beta", "repository": lane_b_repository, "schema": "lane_b",
              "redis_namespace": "fleet-b", "runtime": str(tmp_path / "old" / "rt-b")}]
    document = {"schema": "urn:zeus:fleet:1", "id": "fleet-1", "max_parallel": 2,
                "budget": {"per_host": 4, "total": 8}, "lanes": lanes}
    for lane in lanes:
        (tmp_path / lane["runtime"]).mkdir(parents=True, exist_ok=True)
    store = MemoryStore()
    fleet = Fleet(store)
    registry = fleet.register(deepcopy(document))
    for index, op_id in enumerate(queued):
        fleet.enqueue("a", manifest(op_id, ["docs/x%d.md" % index], base), goal_of(base), [])
    fleet.pause()
    target = clone(tmp_path, source, tmp_path / "new" / "repo-a")
    target_runtime = tmp_path / "new" / "rt-a"
    target_runtime.mkdir(parents=True)
    copy = copy_manifest(tmp_path, [target_runtime / "artifacts" / "evidence.json"])
    return {"store": store, "fleet": fleet, "config": document, "config_sha256": registry["config_sha256"],
            "base": base, "source": source, "target": target, "target_runtime": target_runtime,
            "runtime": tmp_path / "old" / "rt-a", "copy": copy, "journal": journal(tmp_path)}


def request_for(state, **overrides):
    moves = overrides.pop("moves", None) or [
        {"lane": "a", "repository": {"from": str(state["source"]), "to": str(state["target"])},
         "runtime": {"from": str(state["runtime"]), "to": str(state["target_runtime"])}}]
    document = {"schema": REQUEST_SCHEMA, "fleet": "fleet-1", "operator": "owner",
                "expected_config_sha256": state["config_sha256"], "moves": moves,
                "copy_manifest": dict(state["copy"]), "recorded_at": NOW}
    document.update(overrides)
    return validate_relocation_request(document)


def proof_for(state, request=None, *, docker=stopped, book=None):
    with state["store"].transaction() as tx:
        jobs = tx.scan(BUCKET_JOBS)
    return collect_relocation_proof(request or request_for(state), state["config"], jobs,
                                    journal=book if book is not None else state["journal"],
                                    state=docker, clock=lambda: NOW)


# ----- the request document ------------------------------------------------------------------
def test_request_document_is_strict_and_never_echoes_values(tmp_path):
    state = setup(tmp_path)
    good = request_for(state)
    assert validate_relocation_request(good) == good
    move = good["moves"][0]
    bad = [
        {"schema": "urn:zeus:fleet-relocation:2"}, {"fleet": "bad id"}, {"operator": ""},
        {"expected_config_sha256": "x" * 64}, {"moves": []}, {"moves": [move] * 5},
        {"moves": [move, move]},
        {"moves": [{**move, "lane": "bad lane"}]},
        {"moves": [{"lane": "a", "repository": None, "runtime": None}]},
        {"moves": [{**move, "repository": {"from": "relative/path", "to": str(state["target"])}}]},
        {"moves": [{**move, "repository": {"from": str(state["source"]), "to": str(state["source"])}}]},
        {"moves": [{**move, "repository": {"from": str(state["source"]),
                                           "to": str(state["source"] / "inner")}}]},
        {"moves": [{**move, "runtime": {"from": str(state["runtime"])}}]},
        {"copy_manifest": {**state["copy"], "sha256": "z" * 64}},
        {"copy_manifest": {**state["copy"], "entries": 0}},
        {"copy_manifest": {**state["copy"], "entries": True}},
        {"copy_manifest": {**state["copy"], "path": "relative.json"}},
        {"recorded_at": "2026-09-22T00:30:00"},
    ]
    for override in bad:
        with pytest.raises(FleetRefused) as info:
            validate_relocation_request({**good, **override})
        assert CANARY not in str(info.value) and str(tmp_path) not in str(info.value)
    with pytest.raises(FleetRefused, match="relocation_invalid_fields"):
        validate_relocation_request({**good, "extra": 1})


def test_only_the_named_paths_change_and_everything_else_must_match(tmp_path):
    state = setup(tmp_path)
    new = relocated_config(state["config"], request_for(state))
    assert new["lanes"][0]["repository"] == str(state["target"])
    assert new["lanes"][0]["runtime"] == str(state["target_runtime"])
    for key in ("id", "team", "schema", "redis_namespace"):
        assert new["lanes"][0][key] == state["config"]["lanes"][0][key]
    assert new["lanes"][1] == state["config"]["lanes"][1]
    assert new["budget"] == state["config"]["budget"] and new["max_parallel"] == 2
    unknown = [{"lane": "z", "repository": {"from": str(state["source"]), "to": str(state["target"])},
                "runtime": None}]
    with pytest.raises(FleetRefused, match="lane_unknown"):
        relocated_config(state["config"], request_for(state, moves=unknown))
    stale = [{"lane": "a", "repository": {"from": str(tmp_path / "old" / "elsewhere"),
                                          "to": str(state["target"])}, "runtime": None}]
    with pytest.raises(FleetRefused, match="source_path_mismatch"):
        relocated_config(state["config"], request_for(state, moves=stale))
    occupied = [{"lane": "a", "repository": {"from": str(state["source"]),
                                             "to": state["config"]["lanes"][1]["repository"]},
                 "runtime": None}]
    with pytest.raises(FleetRefused, match="target_path_in_use"):
        relocated_config(state["config"], request_for(state, moves=occupied))
    own = [{"lane": "a", "repository": None,
            "runtime": {"from": str(state["runtime"]), "to": str(state["source"] / "rt")}}]
    with pytest.raises(FleetRefused, match="target_path_in_use"):
        relocated_config(state["config"], request_for(state, moves=own))
    # The existing configuration grammar still decides the new pair: a runtime inside the new
    # repository is refused by `validate_config`, not by anything invented here.
    inside = [{"lane": "a", "repository": {"from": str(state["source"]), "to": str(state["target"])},
               "runtime": {"from": str(state["runtime"]), "to": str(state["target"] / "rt")}}]
    with pytest.raises(FleetRefused, match="config_runtime_in_repository"):
        relocated_config(state["config"], request_for(state, moves=inside))


# ----- the host observation --------------------------------------------------------------------
def test_the_runner_must_be_proven_stopped_by_its_own_journal(tmp_path):
    state = setup(tmp_path)
    assert runner_state(state["journal"])["state"] == "stopped"
    assert runner_state(journal(tmp_path, finished=False, name="open.log"))["state"] == "running"
    assert runner_state(tmp_path / "absent.log") == {"state": "unknown", "run_id": None,
                                                     "journal_sha256": None, "reason": "journal_missing"}
    assert runner_state(journal(tmp_path, name="empty.log", raw=b""))["reason"] == "no_recorded_run"
    assert runner_state(journal(tmp_path, name="binary.log", raw=b"\xff\xfe\x00"))["state"] == "unknown"
    assert runner_state(None)["state"] == "unknown"
    with pytest.raises(FleetRefused, match="runner_not_stopped"):
        proof_for(state, book=journal(tmp_path, finished=False, name="open2.log"))
    with pytest.raises(FleetRefused, match="runner_state_unknown") as info:
        proof_for(state, book=tmp_path / "missing.log")
    assert str(tmp_path) not in str(info.value)


def test_a_retained_lane_run_refuses_unless_docker_proves_it_is_not_running(tmp_path):
    state = setup(tmp_path)
    record = write_run_record(state["runtime"])
    assert proof_for(state, docker=stopped)["lanes"][0]["active_runs"] == 0
    with pytest.raises(FleetRefused, match="lane_run_active"):
        proof_for(state, docker=running)
    with pytest.raises(FleetRefused, match="lane_run_unknown"):
        proof_for(state, docker=unavailable)
    record.write_text("{ not json", encoding="utf-8")
    with pytest.raises(FleetRefused, match="lane_run_unknown") as info:
        proof_for(state, docker=stopped)
    assert str(tmp_path) not in str(info.value)


def relocate(state, request, *, docker=stopped):
    return state["fleet"].relocate(request, proof_for(state, request, docker=docker))


def repository_move(state, target):
    return request_for(state, moves=[{"lane": "a", "runtime": None,
                                      "repository": {"from": str(state["source"]), "to": str(target)}}])


def test_the_target_must_be_an_independent_checkout_of_the_same_repository(tmp_path):
    state = setup(tmp_path)
    proof = proof_for(state)
    observed = proof["lanes"][0]["repository"]
    assert observed["source_identity"] == observed["target_identity"] and observed["independent"] is True
    assert proof["lanes"][0]["runtime"]["writable"] is True
    stranger = tmp_path / "new" / "stranger"
    repository(stranger, goal=b"another history\n")  # a real checkout, another repository
    with pytest.raises(FleetRefused, match="repository_identity_mismatch"):
        relocate(state, repository_move(state, stranger))
    borrowed = clone(tmp_path, state["source"], tmp_path / "new" / "borrowed", "--shared")
    with pytest.raises(FleetRefused, match="target_not_independent"):
        relocate(state, repository_move(state, borrowed))
    with pytest.raises(FleetRefused, match="path_unresolved"):
        proof_for(state, repository_move(state, tmp_path / "new" / "absent"))


def test_a_symlinked_target_is_refused_rather_than_followed(tmp_path):
    state = setup(tmp_path)
    link = tmp_path / "new" / "linked-repo"
    try:
        os.symlink(str(state["target"]), str(link), target_is_directory=True)
    except (OSError, NotImplementedError, AttributeError) as exc:  # pragma: no cover - platform dependent
        pytest.skip("this platform refuses to create a symlink here (%s); Windows expresses the same "
                    "escape as a junction and needs the same refusal" % type(exc).__name__)
    escaping = request_for(state, moves=[{"lane": "a", "repository": {"from": str(state["source"]),
                                                                      "to": str(link)}, "runtime": None}])
    with pytest.raises(FleetRefused, match="path_unresolved"):
        proof_for(state, escaping)


def test_queued_bases_and_goal_blobs_must_exist_in_the_target(tmp_path):
    state = setup(tmp_path, queued=("op-1", "op-2"))
    proof = proof_for(state)
    bindings = proof["lanes"][0]["queued_bindings"]
    assert [row["job_id"] for row in bindings] == ["op-1", "op-2"]
    assert all(row["base_present"] and row["goal_matches"] for row in bindings)
    # A target cloned before the pinned base exists cannot carry that queued job.
    git(state["source"], "checkout", "--quiet", "-b", "later")
    (state["source"] / "docs" / "GOAL.md").write_bytes(b"changed goal\n")
    git(state["source"], "add", ".")
    git(state["source"], "commit", "-m", "Later base")
    later = git(state["source"], "rev-parse", "HEAD")
    state["fleet"].resume()
    state["fleet"].enqueue("a", manifest("op-3", ["docs/z.md"], later),
                           {**goal_of(later), "sha256": hashlib.sha256(b"changed goal\n").hexdigest()}, [])
    state["fleet"].pause()
    with pytest.raises(FleetRefused, match="queued_base_missing"):
        relocate(state, request_for(state))


def test_the_copy_manifest_must_hash_to_what_was_actually_copied(tmp_path):
    state = setup(tmp_path)
    assert proof_for(state)["copy_manifest"] == {"sha256": state["copy"]["sha256"], "entries": 1, "verified": 1}
    corrupt = copy_manifest(tmp_path, [state["target_runtime"] / "artifacts" / "broken.json"], corrupt=True)
    with pytest.raises(FleetRefused, match="copy_corrupt"):
        proof_for(state, request_for(state, copy_manifest=corrupt))
    (tmp_path / "copy-manifest.json").write_text("{}", encoding="utf-8")
    with pytest.raises(FleetRefused, match="copy_manifest_mismatch"):
        proof_for(state, request_for(state))
    os.unlink(tmp_path / "copy-manifest.json")
    with pytest.raises(FleetRefused, match="copy_manifest_unreadable") as info:
        proof_for(state, request_for(state))
    assert str(tmp_path) not in str(info.value)


# ----- the committing transaction -----------------------------------------------------------
def test_relocation_rewrites_only_the_registry_paths_and_keeps_the_history(tmp_path):
    state = setup(tmp_path)
    fleet, request = state["fleet"], request_for(state)
    with state["store"].transaction() as tx:
        before = tx.get(BUCKET_JOBS, "op-1")
    answer = relocate(state, request)
    assert answer["cached"] is False and answer["config_sha256"] != state["config_sha256"]
    assert str(tmp_path) not in json.dumps(answer) and "lane_a" not in json.dumps(answer)
    with state["store"].transaction() as tx:
        registry = tx.get(BUCKET_REGISTRY, "fleet-1")
        receipt = tx.get(BUCKET_RELOCATION, answer["receipt"]["id"])
        after = tx.get(BUCKET_JOBS, "op-1")
    assert registry["config"]["lanes"][0]["repository"] == str(state["target"])
    assert registry["config"]["lanes"][0]["schema"] == "lane_a"
    assert registry["config_sha256"] == answer["config_sha256"]
    assert receipt["prior_config"]["lanes"][0]["repository"] == str(state["source"])
    assert receipt["prior_config_sha256"] == state["config_sha256"]
    assert after == before, "a queued job's manifest, goal and repository identity are never rewritten"
    assert state["source"].is_dir() and (state["source"] / "docs" / "GOAL.md").read_bytes() == GOAL_BYTES
    # The registration of the OLD configuration is no longer the registered one.
    with pytest.raises(FleetRefused, match="registration_conflict"):
        fleet.register(deepcopy(state["config"]))
    assert fleet.register(registry["config"])["cached"] is True
    assert fleet.relocations()[0]["config_sha256"] == answer["config_sha256"]


def test_identical_relocation_replays_and_a_conflicting_one_refuses(tmp_path):
    state = setup(tmp_path)
    request = request_for(state)
    proof = proof_for(state, request)
    first = state["fleet"].relocate(request, proof)
    replay = state["fleet"].relocate(request, proof)
    assert replay["cached"] is True and replay["receipt"] == first["receipt"]
    with state["store"].transaction() as tx:
        assert len(tx.scan(BUCKET_RELOCATION)) == 1
    other = request_for(state, operator="someone-else")
    with pytest.raises(FleetRefused, match="relocation_conflict"):
        state["fleet"].relocate(other, proof)
    with state["store"].transaction() as tx:
        assert len(tx.scan(BUCKET_RELOCATION)) == 1


@pytest.mark.parametrize("case,reason", [
    ("resumed", "fleet_not_paused"),
    ("dispatching", "fleet_not_idle"),
    ("stale_expectation", "config_expected_mismatch"),
    ("other_fleet", "fleet_mismatch"),
])
def test_a_fleet_that_is_not_paused_and_idle_refuses_the_cutover(tmp_path, case, reason):
    state = setup(tmp_path)
    request = request_for(state)
    proof = proof_for(state, request)
    if case == "resumed":
        state["fleet"].resume()
    elif case == "dispatching":
        state["fleet"].resume()
        state["fleet"].admit_one()
        state["fleet"].pause()
    elif case == "stale_expectation":
        request = request_for(state, expected_config_sha256="0" * 64)
    elif case == "other_fleet":
        request = request_for(state, fleet="fleet-2")
    with pytest.raises(FleetRefused, match=reason) as info:
        state["fleet"].relocate(request, proof)
    assert CANARY not in str(info.value) and str(tmp_path) not in str(info.value)
    with state["store"].transaction() as tx:
        assert tx.scan(BUCKET_RELOCATION) == []
        assert tx.get(BUCKET_REGISTRY, "fleet-1")["config_sha256"] == state["config_sha256"]


def test_a_proof_that_does_not_cover_this_request_refuses(tmp_path):
    state = setup(tmp_path)
    request = request_for(state)
    proof = proof_for(state, request)
    broken = [({**proof, "schema": "urn:zeus:other:1"}, "proof_schema"),
              ({**proof, "runner": {**proof["runner"], "state": "running"}}, "runner_not_stopped"),
              ({**proof, "lanes": []}, "proof_mismatch"),
              ({**proof, "lanes": [{**proof["lanes"][0], "active_runs": 1}]}, "lane_run_active"),
              ({**proof, "copy_manifest": {**proof["copy_manifest"], "verified": 0}}, "copy_unverified"),
              ({**proof, "lanes": [{**proof["lanes"][0], "queued_bindings": []}]}, "queued_binding_incomplete")]
    for document, reason in broken:
        with pytest.raises(FleetRefused, match=reason):
            state["fleet"].relocate(request, document)
    # Only the observation's identities bind; its clock does not.
    moved = {**proof, "observed_at": "2026-09-22T01:00:00+09:00"}
    assert state["fleet"].relocate(request, proof, reread=lambda: moved)["relocated"] is True
    with pytest.raises(FleetRefused, match="relocation_conflict"):
        state["fleet"].relocate(request_for(state, operator="second"), proof)


def test_a_proof_that_changed_between_the_reads_refuses_before_commit(tmp_path):
    state = setup(tmp_path)
    request = request_for(state)
    proof = proof_for(state, request)
    changed = {**proof, "runner": {**proof["runner"], "run_id": "2" * 32}}
    with pytest.raises(FleetRefused, match="proof_changed"):
        state["fleet"].relocate(request, proof, reread=lambda: changed)
    with state["store"].transaction() as tx:
        assert tx.scan(BUCKET_RELOCATION) == []


def test_the_owner_command_exists_on_the_cli_and_requires_the_runner_journal(tmp_path):
    from codex_harness.cli import parser

    args = parser().parse_args(["fleet", "relocate", "--file", str(tmp_path / "request.json"),
                                "--journal", str(tmp_path / "fleet-journal.log")])
    assert args.fleet_command == "relocate" and args.docker == "docker"
    with pytest.raises(SystemExit):  # the runner's own journal is not optional
        parser().parse_args(["fleet", "relocate", "--file", str(tmp_path / "request.json")])


def test_admission_after_a_move_still_excludes_conflicting_paths(tmp_path):
    """A job frozen before the move keeps its old repository identity; the immutable receipt is how
    admission still sees one repository, so the path exclusion is not lost by relocating."""
    state = setup(tmp_path, shared_repository=True, queued=("op-1",))
    fleet = state["fleet"]
    target = state["target"]
    moves = [{"lane": lane, "repository": {"from": str(state["source"]), "to": str(target)}, "runtime": None}
             for lane in ("a", "b")]
    request = request_for(state, moves=moves)
    relocate(state, request)
    fleet.resume()
    with state["store"].transaction() as tx:
        aliases = Fleet._repository_aliases(tx)
    assert resolve_repository(repository_identity(str(state["source"])), aliases) == \
        repository_identity(str(target))
    fleet.enqueue("b", manifest("op-9", ["docs/x0.md"], state["base"]), goal_of(state["base"]), [])
    with state["store"].transaction() as tx:
        assert tx.get(BUCKET_JOBS, "op-1")["repository"] == repository_identity(str(state["source"]))
        assert tx.get(BUCKET_JOBS, "op-9")["repository"] == repository_identity(str(target))
    assert fleet.admit_one()["job"]["id"] == "op-1"
    decision = fleet.admit_one()
    assert decision["job"] is None and decision["blocked"] == {"op-9": "path_conflict"}
