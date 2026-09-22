"""Owner relocation of lane repository and runtime paths (storage-recovery-001, INV-FLEET-001).

The filesystem side is real: actual temporary Git checkouts, actual copied files and an actual
service lifecycle journal, so the target identity, the pinned queued bases, the goal bytes and the
copy manifest are read from things that exist. Docker is UNAVAILABLE here, so retained isolation
runs are answered by labelled fault injection (`running`, `unavailable`), never by a daemon. No
provider, no PostgreSQL and no model is reached by anything in this file, and no file is moved or
deleted by the code under test.

Platform note: the symlink escape case needs a symlink the OS will create. Windows grants that only
to a privileged or developer-mode session (and expresses the same escape as a junction), so that
one case skips with its reason instead of pretending to have run. The case-distinct sibling cases
need a case-sensitive filesystem to hold `rt` and `RT` as two directories at all; where the
filesystem folds them into one, that escape does not exist and the case skips with that reason.
"""
import hashlib
import json
import os
import shutil
from copy import deepcopy
from pathlib import Path

import pytest

from codex_harness.adapters.commands import run_process
from codex_harness.adapters.fleet_recovery import (
    _hash_bounded,
    _hash_file,
    _relative,
    collect_relocation_proof,
    run_root,
    runner_state,
    verify_copy_manifest,
)
from codex_harness.adapters.isolated_worker import run_records
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
    COPY_OWNERSHIP,
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


def copy_manifest(tmp_path, pairs, *, corrupt=False, write=True, name="copy-manifest.json", entries=None):
    """The owner's record of files copied from a stated source root to a stated target root.

    `pairs` is `(source_root, target_root, relative)`: the same relative path below both roots, as
    a real copy has. BOTH ends are written for real - a manifest row describes a file that was
    copied from somewhere that exists - unless `write` is false (a target that must stay absent for
    the test that needs it absent). `entries` replaces the generated rows, so a test can state a
    malformed, unbound or duplicated entry on purpose.
    """
    rows = []
    for index, (source_root, target_root, relative) in enumerate(pairs):
        source = Path(source_root).joinpath(*relative.split("/"))
        destination = Path(target_root).joinpath(*relative.split("/"))
        data = ("copied evidence %d\n" % index).encode("utf-8")
        recorded = hashlib.sha256(data).hexdigest()
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(data)
        if write:
            destination.parent.mkdir(parents=True, exist_ok=True)
            # The copy no longer is what was verified.
            destination.write_bytes(data + b"tampered" if corrupt and index == 0 else data)
        rows.append({"source": str(source), "destination": str(destination),
                     "sha256": recorded, "bytes": len(data)})
    document = {"schema": COPY_MANIFEST_SCHEMA, "entries": rows if entries is None else entries}
    path = tmp_path / name
    path.write_text(json.dumps(document, sort_keys=True), encoding="utf-8")
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "entries": len(document["entries"])}


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
        # An initialized lane runtime: `bootstrap.isolated_worker` owns this root, and a lane that
        # has hosted isolated runs has it whether or not any run is retained in it.
        run_root(lane["runtime"]).mkdir(parents=True, exist_ok=True)
    store = MemoryStore()
    fleet = Fleet(store)
    registry = fleet.register(deepcopy(document))
    for index, op_id in enumerate(queued):
        fleet.enqueue("a", manifest(op_id, ["docs/x%d.md" % index], base), goal_of(base), [])
    fleet.pause()
    target = clone(tmp_path, source, tmp_path / "new" / "repo-a")
    target_runtime = tmp_path / "new" / "rt-a"
    target_runtime.mkdir(parents=True)
    copy = copy_manifest(tmp_path, [(tmp_path / "old" / "rt-a", target_runtime, "artifacts/evidence.json")])
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


def test_runs_that_cannot_be_enumerated_are_a_refusal_not_an_empty_lane(tmp_path):
    """`run_records` answers the same empty list for a root that is missing, that is not a
    directory and that could not be read. Only a root that was actually enumerated may be counted
    as zero, and the missing one is never created to make the check pass."""
    state = setup(tmp_path)
    runs = run_root(str(state["runtime"]))
    assert runs.is_dir() and not any(runs.iterdir())
    assert proof_for(state)["lanes"][0]["active_runs"] == 0  # initialized, accessible, genuinely empty
    shutil.rmtree(runs)
    # Control for the behaviour this corrects: the record reader answers the same empty list for a
    # root that is not there, and a count over it reads as "this lane has no active run".
    assert run_records(runs) == [] and not runs.exists()
    with pytest.raises(FleetRefused, match="lane_runs_unavailable") as info:
        proof_for(state)
    assert str(tmp_path) not in str(info.value)
    assert not runs.exists()
    (runs / ("ab" * 16)).mkdir(parents=True)  # a retained run whose record is not there at all
    with pytest.raises(FleetRefused, match="lane_runs_unreadable"):
        proof_for(state)
    shutil.rmtree(state["runtime"])
    with pytest.raises(FleetRefused, match="lane_runtime_unavailable"):
        proof_for(state)
    assert not state["runtime"].exists()


def relocate(state, request, *, docker=stopped):
    return state["fleet"].relocate(request, proof_for(state, request, docker=docker))


def repository_move(state, tmp_path, target, *, write=True, lanes=("a",)):
    """A repository-only move, with a copy manifest bound to exactly that move."""
    copy = copy_manifest(tmp_path, [(state["source"], target, "copied/evidence.json")], write=write,
                         name="copy-" + Path(target).name + ".json")
    return request_for(state, copy_manifest=copy,
                       moves=[{"lane": lane, "runtime": None,
                               "repository": {"from": str(state["source"]), "to": str(target)}}
                              for lane in lanes])


def test_the_target_must_be_an_independent_checkout_of_the_same_repository(tmp_path):
    state = setup(tmp_path)
    proof = proof_for(state)
    observed = proof["lanes"][0]["repository"]
    assert observed["source_identity"] == observed["target_identity"] and observed["independent"] is True
    assert proof["lanes"][0]["runtime"]["writable"] is True
    stranger = tmp_path / "new" / "stranger"
    repository(stranger, goal=b"another history\n")  # a real checkout, another repository
    with pytest.raises(FleetRefused, match="repository_identity_mismatch"):
        relocate(state, repository_move(state, tmp_path, stranger))
    borrowed = clone(tmp_path, state["source"], tmp_path / "new" / "borrowed", "--shared")
    with pytest.raises(FleetRefused, match="target_not_independent"):
        relocate(state, repository_move(state, tmp_path, borrowed))
    absent = tmp_path / "new" / "absent"
    with pytest.raises(FleetRefused, match="path_unresolved"):
        proof_for(state, repository_move(state, tmp_path, absent, write=False))
    assert not absent.exists(), "an absent target is never created to make the check pass"


def test_a_symlinked_target_is_refused_rather_than_followed(tmp_path):
    state = setup(tmp_path)
    link = tmp_path / "new" / "linked-repo"
    try:
        os.symlink(str(state["target"]), str(link), target_is_directory=True)
    except (OSError, NotImplementedError, AttributeError) as exc:  # pragma: no cover - platform dependent
        pytest.skip("this platform refuses to create a symlink here (%s); Windows expresses the same "
                    "escape as a junction and needs the same refusal" % type(exc).__name__)
    with pytest.raises(FleetRefused, match="path_unresolved"):
        proof_for(state, repository_move(state, tmp_path, link, write=False))


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
    assert proof_for(state)["copy_manifest"] == {"sha256": state["copy"]["sha256"], "entries": 1,
                                                 "verified": 1, "bound": True,
                                                 "ownership": COPY_OWNERSHIP, "covered": ["a.runtime"]}
    corrupt = copy_manifest(tmp_path, [(state["runtime"], state["target_runtime"], "artifacts/broken.json")],
                            corrupt=True, name="corrupt.json")
    with pytest.raises(FleetRefused, match="copy_corrupt"):
        proof_for(state, request_for(state, copy_manifest=corrupt))
    (tmp_path / "copy-manifest.json").write_text("{}", encoding="utf-8")
    with pytest.raises(FleetRefused, match="copy_manifest_mismatch"):
        proof_for(state, request_for(state))
    os.unlink(tmp_path / "copy-manifest.json")
    with pytest.raises(FleetRefused, match="copy_manifest_unreadable") as info:
        proof_for(state, request_for(state))
    assert str(tmp_path) not in str(info.value)


def entry_of(state, relative="artifacts/evidence.json", **overrides):
    source = Path(state["runtime"]).joinpath(*relative.split("/"))
    destination = Path(state["target_runtime"]).joinpath(*relative.split("/"))
    data = b"copied evidence 0\n"
    return {"source": str(source), "destination": str(destination),
            "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data), **overrides}


@pytest.mark.parametrize("case,reason", [
    ("null_digest_missing_file", "copy_manifest_invalid"),
    ("missing_destination", "copy_unreadable"),
    ("short_bytes", "copy_corrupt"),
    ("untyped_bytes", "copy_manifest_invalid"),
    ("relative_path", "copy_manifest_invalid"),
    ("duplicate", "copy_entry_duplicate"),
    ("outside_the_move", "copy_entry_unbound"),
    ("renamed", "copy_entry_unbound"),
    ("runtime_uncovered", "copy_manifest_incomplete"),
])
def test_a_manifest_entry_must_prove_a_file_this_request_actually_moves(tmp_path, case, reason):
    """The old credit of `None == None` - a missing destination beside a null digest - is the first
    case here; the rest are the entries a manifest of unrelated or malformed copies would carry."""
    state = setup(tmp_path)
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    entries = {
        "null_digest_missing_file": [entry_of(state, "artifacts/never-copied.json", sha256=None)],
        "missing_destination": [entry_of(state, "artifacts/never-copied.json")],
        "short_bytes": [entry_of(state, bytes=2)],
        "untyped_bytes": [entry_of(state, bytes="18")],
        "relative_path": [entry_of(state, source="artifacts/evidence.json")],
        "duplicate": [entry_of(state), entry_of(state)],
        "outside_the_move": [entry_of(state), {"source": str(outside / "a.txt"),
                                               "destination": str(outside / "b.txt"),
                                               "sha256": "c" * 64, "bytes": 0}],
        "renamed": [entry_of(state, destination=str(Path(state["target_runtime"]) / "artifacts" / "other.json"))],
        "runtime_uncovered": [entry_of(state, source=str(Path(state["source"]) / "docs" / "GOAL.md"),
                                       destination=str(Path(state["target"]) / "docs" / "GOAL.md"),
                                       sha256=hashlib.sha256(GOAL_BYTES).hexdigest(), bytes=len(GOAL_BYTES))],
    }[case]
    copy = copy_manifest(tmp_path, [(state["runtime"], state["target_runtime"], "artifacts/evidence.json")],
                         name=case + ".json", entries=entries)
    if case == "missing_destination":
        # The source of a copy that was never made still exists; only the destination is absent.
        Path(entries[0]["source"]).write_bytes(b"copied evidence 0\n")
    if case == "null_digest_missing_file":
        # Control for the behaviour this corrects: the destination cannot be read, so the entry was
        # compared as `None == None` and counted as verified.
        assert _hash_file(Path(entries[0]["destination"])) is None and entries[0]["sha256"] is None
    with pytest.raises(FleetRefused, match=reason) as info:
        proof_for(state, request_for(state, copy_manifest=copy))
    assert str(tmp_path) not in str(info.value) and CANARY not in str(info.value)


# ----- physical ownership of the copied files -------------------------------------------------
def symlink_or_skip(source, name, *, directory: bool = True):
    """A real link on this filesystem, or a labelled skip.

    Windows expresses the same redirection as a directory junction and grants a symlink only to a
    privileged or developer-mode session; the owner's retained Windows junction reproducer covers
    that side of the same rule, and it is not executed from here.
    """
    try:
        os.symlink(str(source), str(name), target_is_directory=directory)
    except (OSError, NotImplementedError, AttributeError) as exc:  # pragma: no cover - platform dependent
        pytest.skip("this platform refuses to create a symlink here (%s); a Windows junction expresses the "
                    "same redirection and needs the same refusal" % type(exc).__name__)
    return Path(name)


def entry_for(source_root, target_root, relative: str, data: bytes):
    """One manifest row: what the owner says was copied to `target_root/relative`."""
    return {"source": str(Path(source_root).joinpath(*relative.split("/"))),
            "destination": str(Path(target_root).joinpath(*relative.split("/"))),
            "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}


def runtime_move(state, tmp_path, target_root, entries, *, name, source_root=None):
    """A runtime-only move whose manifest states exactly `entries`."""
    copy = copy_manifest(tmp_path, [], name=name, entries=entries)
    return request_for(state, copy_manifest=copy,
                       moves=[{"lane": "a", "repository": None,
                               "runtime": {"from": str(source_root or state["runtime"]),
                                           "to": str(target_root)}}])


def test_a_child_link_to_the_source_is_refused_even_though_the_bytes_read_back(tmp_path, monkeypatch):
    """The owner's reproducer, in the form this platform can create: the new runtime's `artifacts`
    child is a LINK to the old runtime's `artifacts`, so nothing was copied at all and every name
    below the new root still reads the old runtime's bytes."""
    from codex_harness.adapters import fleet_recovery

    state = setup(tmp_path)
    target = tmp_path / "new" / "rt-junction"
    target.mkdir(parents=True)
    data = b"interrupted evidence\n"
    (Path(state["runtime"]) / "artifacts" / "interrupted.json").write_bytes(data)
    symlink_or_skip(Path(state["runtime"]) / "artifacts", target / "artifacts")
    entry = entry_for(state["runtime"], target, "artifacts/interrupted.json", data)
    # Control for the behaviour this corrects: the destination NAME is below the new runtime root at
    # exactly the relative path its source is below the old one, and it reads back to the declared
    # digest and length - because it IS the source file. Lexical containment credits this as a copy.
    assert _relative(entry["destination"], str(target)) == "artifacts/interrupted.json"
    assert _hash_bounded(Path(entry["destination"]), entry["bytes"]) == {"sha256": entry["sha256"],
                                                                        "bytes": len(data)}
    assert Path(entry["destination"]).resolve() == Path(entry["source"]).resolve()
    request = runtime_move(state, tmp_path, target, [entry], name="junction.json")
    # ... and the same control at the boundary this corrects: with the physical ownership check
    # removed, the remaining rules are the pre-fix ones, and they answer verified=1/bound=True for
    # a destination that IS the source - the result the owner reproduced with a real junction.
    monkeypatch.setattr(fleet_recovery, "_owned_copy", lambda *_, **__: None)
    lexical = verify_copy_manifest(request)
    assert lexical["verified"] == 1 and lexical["bound"] is True
    monkeypatch.undo()
    # The redirection itself is the refusal now: the `artifacts` component is inspected with lstat
    # and rejected as a link, before and independently of where it happens to lead.
    with pytest.raises(FleetRefused, match="copy_entry_link_refused") as info:
        verify_copy_manifest(request)
    assert "destination" in str(info.value)
    assert str(tmp_path) not in str(info.value) and CANARY not in str(info.value)
    # The same refusal at the collection boundary the owner command actually uses, and no receipt.
    with pytest.raises(FleetRefused, match="copy_entry_link_refused"):
        proof_for(state, request)
    with state["store"].transaction() as tx:
        assert tx.scan(BUCKET_RELOCATION) == []
        assert tx.get(BUCKET_REGISTRY, "fleet-1")["config_sha256"] == state["config_sha256"]
    assert (Path(state["runtime"]) / "artifacts" / "interrupted.json").read_bytes() == data


def test_a_destination_that_links_outside_the_target_is_refused(tmp_path, monkeypatch):
    """A copied FILE that is a link to identical bytes elsewhere is not this target's own file."""
    from codex_harness.adapters import fleet_recovery

    state = setup(tmp_path)
    target = tmp_path / "new" / "rt-escape"
    (target / "artifacts").mkdir(parents=True)
    data = b"stored somewhere this request never moves\n"
    outside = tmp_path / "elsewhere" / "evidence.json"
    outside.parent.mkdir(parents=True)
    outside.write_bytes(data)
    (Path(state["runtime"]) / "artifacts" / "escape.json").write_bytes(data)
    symlink_or_skip(outside, target / "artifacts" / "escape.json", directory=False)
    entry = entry_for(state["runtime"], target, "artifacts/escape.json", data)
    assert _hash_bounded(Path(entry["destination"]), entry["bytes"])["sha256"] == entry["sha256"]
    request = runtime_move(state, tmp_path, target, [entry], name="escape.json")
    monkeypatch.setattr(fleet_recovery, "_owned_copy", lambda *_, **__: None)  # pre-fix control
    assert verify_copy_manifest(request)["verified"] == 1
    monkeypatch.undo()
    with pytest.raises(FleetRefused, match="copy_entry_link_refused"):
        verify_copy_manifest(request)
    with pytest.raises(FleetRefused, match="copy_entry_link_refused"):
        proof_for(state, request)


def test_a_source_side_redirection_is_refused_as_well(tmp_path, monkeypatch):
    """A link on the SOURCE side substitutes unrelated storage just as well: the manifest then
    certifies a file that never lived below the path this request moves away from."""
    from codex_harness.adapters import fleet_recovery

    state = setup(tmp_path)
    target = tmp_path / "new" / "rt-source-link"
    (target / "staged").mkdir(parents=True)
    data = b"only ever on the target\n"
    (target / "staged" / "evidence.json").write_bytes(data)
    symlink_or_skip(target / "staged", Path(state["runtime"]) / "staged")
    entry = entry_for(state["runtime"], target, "staged/evidence.json", data)
    request = runtime_move(state, tmp_path, target, [entry], name="source-link.json")
    monkeypatch.setattr(fleet_recovery, "_owned_copy", lambda *_, **__: None)  # pre-fix control
    assert verify_copy_manifest(request)["verified"] == 1
    monkeypatch.undo()
    with pytest.raises(FleetRefused, match="copy_entry_link_refused") as info:
        verify_copy_manifest(request)
    assert "source" in str(info.value) and str(tmp_path) not in str(info.value)
    # A move ROOT that is itself a link lends its whole subtree to storage this request never moves.
    aliased = symlink_or_skip(state["runtime"], tmp_path / "old" / "rt-a-alias")
    entry = entry_for(aliased, target, "staged/evidence.json", data)
    with pytest.raises(FleetRefused, match="copy_entry_link_refused") as info:
        verify_copy_manifest(runtime_move(state, tmp_path, target, [entry], name="alias.json",
                                          source_root=aliased))
    assert "source" in str(info.value)


def case_sensitive_or_skip(parent):
    """This filesystem must distinguish two names that differ only in case, or the case skips.

    Windows and a default macOS volume fold them into one entry, so the escapes below cannot exist
    there at all; the owner's retained junction reproducer covers the Windows side of the same rule.
    """
    probe = parent / "case-probe"
    probe.mkdir(parents=True, exist_ok=True)
    if (parent / "CASE-PROBE").exists():
        pytest.skip("this filesystem folds names that differ only in case into one entry, so a "
                    "case-distinct sibling cannot exist here")
    return parent


def case_distinct_roots(parent, lower="rt", upper="RT"):
    """Two sibling directories that differ only in case, on a filesystem that keeps them apart."""
    case_sensitive_or_skip(parent)
    low, high = parent / lower, parent / upper
    low.mkdir(parents=True)
    high.mkdir(parents=True)
    return low, high


def test_a_case_distinct_sibling_is_not_this_target_even_though_names_casefold_equal(tmp_path, monkeypatch):
    """The owner's POSIX finding, in its plainest form: a manifest row that simply NAMES the
    case-distinct sibling of the move target.

    `normalize_path` casefolds for scheduling identity, so the lexical rules read `new/RT/...` as
    living below `new/rt` and credited the row. The filesystem does not: these are two directories,
    and the copy this request moves is not in the one it states.
    """
    from codex_harness.adapters import fleet_recovery

    state = setup(tmp_path)
    target, sibling = case_distinct_roots(tmp_path / "new" / "case")
    data = b"synthetic equal bytes\n"
    (sibling / "artifacts").mkdir()
    (sibling / "artifacts" / "evidence.json").write_bytes(data)
    entry = entry_for(state["runtime"], sibling, "artifacts/evidence.json", data)
    Path(entry["source"]).parent.mkdir(parents=True, exist_ok=True)
    Path(entry["source"]).write_bytes(data)
    request = runtime_move(state, tmp_path, target, [entry], name="case-sibling.json")
    # Control for the behaviour this corrects: the casefolded comparison form answers the exact
    # relative path the request moves, for a destination that is not below the target at all.
    assert _relative(entry["destination"], str(target)) == "artifacts/evidence.json"
    assert not Path(entry["destination"]).is_relative_to(target)
    monkeypatch.setattr(fleet_recovery, "_owned_copy", lambda *_, **__: None)  # pre-fix control
    assert verify_copy_manifest(request)["verified"] == 1
    monkeypatch.undo()
    with pytest.raises(FleetRefused, match="copy_entry_escaped") as info:
        verify_copy_manifest(request)
    assert "destination" in str(info.value)
    assert str(tmp_path) not in str(info.value) and CANARY not in str(info.value)
    with pytest.raises(FleetRefused, match="copy_entry_escaped"):
        proof_for(state, request)
    with state["store"].transaction() as tx:
        assert tx.scan(BUCKET_RELOCATION) == []


def test_the_owners_case_distinct_symlink_reproduction_refuses(tmp_path, monkeypatch):
    """The reproduction the owner EXECUTED in a disposable Linux container (`case-repro-001`):
    distinct `new/rt` and `new/RT`, `new/rt/artifacts` a symlink to `new/RT/artifacts`, synthetic
    equal bytes. `verify_copy_manifest` answered `bound=true`/`ownership=resolved_paths` although
    `Path.is_relative_to` on the resolved destination proved the escape."""
    from codex_harness.adapters import fleet_recovery

    state = setup(tmp_path)
    target, sibling = case_distinct_roots(tmp_path / "new" / "repro")
    data = b"synthetic equal bytes\n"
    (sibling / "artifacts").mkdir()
    (sibling / "artifacts" / "evidence.json").write_bytes(data)
    symlink_or_skip(sibling / "artifacts", target / "artifacts")
    entry = entry_for(state["runtime"], target, "artifacts/evidence.json", data)
    Path(entry["source"]).parent.mkdir(parents=True, exist_ok=True)
    Path(entry["source"]).write_bytes(data)
    request = runtime_move(state, tmp_path, target, [entry], name="case-repro.json")
    # The owner's recorded result: the name reads as contained and the bytes read back, while the
    # concrete resolution leaves the root.
    assert _relative(entry["destination"], str(target)) == "artifacts/evidence.json"
    assert _hash_bounded(Path(entry["destination"]), entry["bytes"]) == {"sha256": entry["sha256"],
                                                                        "bytes": len(data)}
    assert not Path(entry["destination"]).resolve().is_relative_to(target.resolve())
    monkeypatch.setattr(fleet_recovery, "_owned_copy", lambda *_, **__: None)  # pre-fix control
    lexical = verify_copy_manifest(request)
    assert lexical["verified"] == 1 and lexical["bound"] is True and lexical["ownership"] == COPY_OWNERSHIP
    monkeypatch.undo()
    with pytest.raises(FleetRefused, match="copy_entry_link_refused") as info:
        verify_copy_manifest(request)
    assert "destination" in str(info.value) and str(tmp_path) not in str(info.value)
    with pytest.raises(FleetRefused, match="copy_entry_link_refused"):
        proof_for(state, request)
    with state["store"].transaction() as tx:
        assert tx.scan(BUCKET_RELOCATION) == []
        assert tx.get(BUCKET_REGISTRY, "fleet-1")["config_sha256"] == state["config_sha256"]


@pytest.mark.parametrize("side", ["source", "destination"])
def test_a_child_link_is_refused_even_when_it_leads_to_a_contained_file(tmp_path, side, monkeypatch):
    """No-child-redirection holds INSIDE the root too, on both sides.

    `artifacts/Carried.json` is a link to the root's OWN `artifacts/carried.json`, so it never
    leaves the root - and the casefolded comparison the correction removes read the resolved
    redirection as exactly the relative path the request states, which is the pre-fix credit
    asserted below. The component is a link, and that alone is the refusal: ownership does not
    depend on where a redirection happens to lead.
    """
    from codex_harness.adapters import fleet_recovery

    state = setup(tmp_path)
    case_sensitive_or_skip(tmp_path)
    target = tmp_path / "new" / ("rt-contained-" + side)
    (target / "artifacts").mkdir(parents=True)
    data = b"contained but redirected\n"
    relative = "artifacts/Carried.json"
    root = Path(state["runtime"]) if side == "source" else target
    other = target if side == "source" else Path(state["runtime"])
    (other / "artifacts").mkdir(parents=True, exist_ok=True)
    (other / "artifacts" / "Carried.json").write_bytes(data)
    (root / "artifacts").mkdir(parents=True, exist_ok=True)
    (root / "artifacts" / "carried.json").write_bytes(data)
    # The link is a CHILD of its own move root and resolves to a file of that same root.
    symlink_or_skip(root / "artifacts" / "carried.json", root / "artifacts" / "Carried.json",
                    directory=False)
    entry = entry_for(state["runtime"], target, relative, data)
    resolved = Path(entry[side]).resolve()
    assert resolved.is_relative_to(root.resolve()) and resolved.name == "carried.json"
    # Control for the behaviour this corrects: the casefolded comparison answers the declared
    # relative path for the redirection, so the pre-fix rules counted this row as a verified copy.
    assert _relative(str(resolved), str(root.resolve())) == _relative(entry[side], str(root))
    request = runtime_move(state, tmp_path, target, [entry], name="contained-" + side + ".json")
    monkeypatch.setattr(fleet_recovery, "_owned_copy", lambda *_, **__: None)  # pre-fix control
    assert verify_copy_manifest(request)["verified"] == 1
    monkeypatch.undo()
    with pytest.raises(FleetRefused, match="copy_entry_link_refused") as info:
        verify_copy_manifest(request)
    assert side in str(info.value) and str(tmp_path) not in str(info.value)


def test_mixed_case_nested_copies_pass_without_lowercasing_real_path_names(tmp_path):
    """The valid control for the same family: ordinary directories whose real names carry mixed
    case verify and relocate. The correction replaces the casefolded comparison with the platform's
    own path rule; it does not require lowercase paths, and it lowercases no real name."""
    state = setup(tmp_path)
    target = tmp_path / "new" / "RT-Mixed"
    target.mkdir(parents=True)
    relative = "Artifacts/F2H/Deep/Evidence.JSON"
    copy = copy_manifest(tmp_path, [(state["runtime"], target, relative)], name="mixed.json")
    request = request_for(state, copy_manifest=copy,
                          moves=[{"lane": "a", "repository": None,
                                  "runtime": {"from": str(state["runtime"]), "to": str(target)}}])
    document = json.loads(Path(copy["path"]).read_text(encoding="utf-8"))
    for entry in document["entries"]:
        # The request and the manifest keep the names the owner actually copied.
        assert "Artifacts/F2H/Deep/Evidence.JSON" in entry["destination"].replace(os.sep, "/")
    assert verify_copy_manifest(request) == {"sha256": copy["sha256"], "entries": 1, "verified": 1,
                                             "bound": True, "ownership": COPY_OWNERSHIP,
                                             "covered": ["a.runtime"]}
    answer = state["fleet"].relocate(request, proof_for(state, request))
    assert answer["relocated"] is True and answer["cached"] is False
    with state["store"].transaction() as tx:
        assert tx.get(BUCKET_REGISTRY, "fleet-1")["config"]["lanes"][0]["runtime"] == str(target)


@pytest.mark.parametrize("case,reason,side", [
    ("missing_source", "copy_entry_unresolved", "source"),
    ("missing_destination_directory", "copy_entry_unresolved", "destination"),
    ("looping_destination_chain", "copy_entry_unresolved", "destination"),
])
def test_a_manifest_path_whose_resolution_is_inaccessible_refuses(tmp_path, case, reason, side):
    """Strict resolution: a path that is missing, unreadable or looping is a refusal, never an
    assumption that it lives where it is spelled."""
    state = setup(tmp_path)
    target = tmp_path / "new" / ("rt-" + case)
    (target / "artifacts").mkdir(parents=True)
    data = b"resolution evidence\n"
    entry = entry_for(state["runtime"], target, "artifacts/evidence.json", data)
    if case == "missing_source":
        entry = entry_for(state["runtime"], target, "artifacts/no-such-source.json", data)
        Path(entry["destination"]).write_bytes(data)  # the copy exists; its stated source does not
        assert not Path(entry["source"]).exists()
    elif case == "missing_destination_directory":
        (Path(state["runtime"]) / "artifacts" / "evidence.json").write_bytes(data)
        entry = entry_for(state["runtime"], target, "artifacts/never/evidence.json", data)
        (Path(state["runtime"]) / "artifacts" / "never").mkdir()
        (Path(state["runtime"]) / "artifacts" / "never" / "evidence.json").write_bytes(data)
    else:
        (Path(state["runtime"]) / "artifacts" / "evidence.json").write_bytes(data)
        entry = entry_for(state["runtime"], target, "artifacts/loop/evidence.json", data)
        (Path(state["runtime"]) / "artifacts" / "loop").mkdir()
        (Path(state["runtime"]) / "artifacts" / "loop" / "evidence.json").write_bytes(data)
        symlink_or_skip(target / "artifacts" / "loop-b", target / "artifacts" / "loop")
        symlink_or_skip(target / "artifacts" / "loop", target / "artifacts" / "loop-b")
    request = runtime_move(state, tmp_path, target, [entry], name=case + ".json")
    with pytest.raises(FleetRefused, match=reason) as info:
        verify_copy_manifest(request)
    assert side in str(info.value) and str(tmp_path) not in str(info.value)


def test_a_nested_ordinary_copy_below_the_target_commits(tmp_path):
    """The passing control: ordinary directories and an ordinary file, deep below the target, are
    verified and relocate - the refusals above are about redirection, not about depth."""
    state = setup(tmp_path)
    target = tmp_path / "new" / "rt-nested"
    target.mkdir(parents=True)
    relative = "artifacts/f2h/artifacts/deep/evidence.json"
    copy = copy_manifest(tmp_path, [(state["runtime"], target, relative)], name="nested.json")
    request = request_for(state, copy_manifest=copy,
                          moves=[{"lane": "a", "repository": None,
                                  "runtime": {"from": str(state["runtime"]), "to": str(target)}}])
    assert verify_copy_manifest(request) == {"sha256": copy["sha256"], "entries": 1, "verified": 1,
                                             "bound": True, "ownership": COPY_OWNERSHIP,
                                             "covered": ["a.runtime"]}
    answer = state["fleet"].relocate(request, proof_for(state, request))
    assert answer["relocated"] is True and answer["cached"] is False
    with state["store"].transaction() as tx:
        assert tx.get(BUCKET_REGISTRY, "fleet-1")["config"]["lanes"][0]["runtime"] == str(target)


def test_a_proof_that_only_compared_names_cannot_commit(tmp_path):
    """The commit needs the adapter's own statement that ownership was resolved on the filesystem;
    a `bound` manifest observation without it is the shape a purely lexical check produced."""
    state = setup(tmp_path)
    request = request_for(state)
    proof = proof_for(state, request)
    assert proof["copy_manifest"]["ownership"] == COPY_OWNERSHIP
    for copy in ({key: value for key, value in proof["copy_manifest"].items() if key != "ownership"},
                 {**proof["copy_manifest"], "ownership": "names"}):
        with pytest.raises(FleetRefused, match="copy_unverified"):
            state["fleet"].relocate(request, {**proof, "copy_manifest": copy})
    with state["store"].transaction() as tx:
        assert tx.scan(BUCKET_RELOCATION) == []


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
    relocate(state, repository_move(state, tmp_path, target, lanes=("a", "b")))
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


def move_back(state, tmp_path, source, target, *, lanes=("a", "b"), name="back"):
    """The reverse move, with its own copy manifest bound to it: B -> A is a relocation like any
    other, and after it the registered path is the one the older jobs were frozen at."""
    copy = copy_manifest(tmp_path, [(source, target, name + "/evidence.json")], name="copy-" + name + ".json")
    with state["store"].transaction() as tx:
        expected = tx.get(BUCKET_REGISTRY, "fleet-1")["config_sha256"]
    request = request_for(state, copy_manifest=copy, expected_config_sha256=expected,
                          moves=[{"lane": lane, "runtime": None,
                                  "repository": {"from": str(source), "to": str(target)}} for lane in lanes])
    with state["store"].transaction() as tx:
        config = tx.get(BUCKET_REGISTRY, "fleet-1")["config"]
    return state["fleet"].relocate(request, collect_relocation_proof(
        request, config, jobs_of(state), journal=state["journal"], state=stopped, clock=lambda: NOW))


def jobs_of(state):
    with state["store"].transaction() as tx:
        return tx.scan(BUCKET_JOBS)


def aliases_of(state):
    with state["store"].transaction() as tx:
        return Fleet._repository_aliases(tx)


def test_a_repository_that_moved_and_came_back_is_still_one_repository(tmp_path):
    """A -> B -> A is a CYCLE in the receipts' edges. Walking that chain answers `A` from `A` and
    `B` from `B`, which would split one repository in two and lose the admission path exclusion
    between a job frozen before the move and a job enqueued between the two moves."""
    state = setup(tmp_path, shared_repository=True, queued=("op-1",))
    fleet, source, target = state["fleet"], state["source"], state["target"]
    a, b = repository_identity(str(source)), repository_identity(str(target))
    relocate(state, repository_move(state, tmp_path, target, lanes=("a", "b")))
    fleet.resume()
    # Enqueued while the lanes point at B, so this job is frozen at the intermediate identity.
    fleet.enqueue("b", manifest("op-9", ["docs/x0.md"], state["base"]), goal_of(state["base"]), [])
    fleet.pause()
    move_back(state, tmp_path, target, source)
    with state["store"].transaction() as tx:
        assert tx.get(BUCKET_REGISTRY, "fleet-1")["config"]["lanes"][0]["repository"] == str(source)
        assert tx.get(BUCKET_JOBS, "op-1")["repository"] == a and tx.get(BUCKET_JOBS, "op-9")["repository"] == b
    # Control for the behaviour this corrects: the receipts' raw edges are the cycle A->B->A, and
    # walking them answers a different repository depending on which identity a job carries.
    edges = {}
    with state["store"].transaction() as tx:
        for row in sorted(tx.scan(BUCKET_RELOCATION), key=lambda r: (r["recorded_at"], r["id"])):
            edges.update(row["repository_aliases"])
    assert resolve_repository(a, edges) != resolve_repository(b, edges)
    aliases = aliases_of(state)
    assert resolve_repository(a, aliases) == resolve_repository(b, aliases) == a
    fleet.resume()
    assert fleet.admit_one()["job"]["id"] == "op-1"
    decision = fleet.admit_one()
    assert decision["job"] is None and decision["blocked"] == {"op-9": "path_conflict"}


def test_a_repository_moved_twice_resolves_to_its_current_path_from_either_identity(tmp_path):
    """A -> B -> C: every identity the repository ever had answers the path it is at now, whichever
    one a frozen job happens to carry."""
    state = setup(tmp_path, shared_repository=True, queued=("op-1",))
    fleet, source, target = state["fleet"], state["source"], state["target"]
    third = clone(tmp_path, source, tmp_path / "newer" / "repo-a")
    a, b, c = (repository_identity(str(path)) for path in (source, target, third))
    relocate(state, repository_move(state, tmp_path, target, lanes=("a", "b")))
    fleet.resume()
    fleet.enqueue("b", manifest("op-9", ["docs/x0.md"], state["base"]), goal_of(state["base"]), [])
    fleet.pause()
    move_back(state, tmp_path, target, third, name="onward")
    aliases = aliases_of(state)
    assert resolve_repository(a, aliases) == resolve_repository(b, aliases) == resolve_repository(c, aliases) == c
    with state["store"].transaction() as tx:
        assert tx.get(BUCKET_JOBS, "op-1")["repository"] == a and tx.get(BUCKET_JOBS, "op-9")["repository"] == b
    fleet.resume()
    assert fleet.admit_one()["job"]["id"] == "op-1"
    decision = fleet.admit_one()
    assert decision["job"] is None and decision["blocked"] == {"op-9": "path_conflict"}


def test_the_cli_replays_a_committed_relocation_without_observing_the_old_paths(tmp_path, monkeypatch):
    """The shipped `zeus fleet relocate` entrypoint: once the receipt is committed, the command
    answers from it even though the journal, the old checkout and the copied files it verified are
    gone. Every external reader is replaced by a fault that fails the test if it is reached."""
    from types import SimpleNamespace

    from codex_harness.adapters import fleet_cli, fleet_recovery

    state = setup(tmp_path)
    request = request_for(state)
    first = relocate(state, request)

    def gone(*_, **__):
        """Injected fault: the sources this relocation moved away from no longer answer."""
        raise AssertionError("a committed relocation must not observe any external state")

    monkeypatch.setattr(fleet_recovery, "collect_relocation_proof", gone)
    monkeypatch.setattr(fleet_recovery, "docker_state", gone)
    shutil.rmtree(state["source"])  # the old checkout is gone, as it is after a real cutover
    os.unlink(state["journal"])

    def run(name, body):
        path = tmp_path / name
        path.write_text(json.dumps(body, sort_keys=True), encoding="utf-8")
        return fleet_cli.execute(SimpleNamespace(store=state["store"]),
                                 SimpleNamespace(fleet_command="relocate", file=path,
                                                 journal=state["journal"], docker="docker"))

    answer = run("request.json", request)
    assert answer["exit_code"] == 0 and answer["cached"] is True and answer["receipt"] == first["receipt"]
    with pytest.raises(FleetRefused, match="relocation_conflict"):
        run("other.json", {**request, "operator": "someone-else"})
