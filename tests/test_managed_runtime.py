"""The opt-in managed Fleet host target: sealed immutable runtimes, a real Fleet entry, truthful
pause/drain/heartbeat and rollback to the exact predecessor code (HOST-RUNTIME.md).

Every fixture here is labelled. The SOURCE is a disposable Git repository built in `tmp_path` from
this checkout's real `src/codex_harness`, with two real commits: revision A, and revision B, which
adds one labelled comment line to `adapters/managed_runtime.py` so the two runtimes carry different
code. The lockfile is a labelled fixture byte string whose digest is the "qualified environment".
The GitHub port is `test_host_delivery.FakeGitHub` (no `gh`, no network). The Fleet WORKLOAD is the
labelled controlled `fixture` workload: the real `FleetRunner` with the real managed control hooks
over an in-memory Fleet, whose jobs are real child processes waiting for a release marker. No model,
provider, scheduled task, live service, package download or production state is touched.

The HOST side is real: an actual managed root, actual sealed directories, an actual trusted
launcher process running this controller's code, and an actual child process importing ONLY the
sealed runtime and reporting what it loaded. Those tests run on POSIX here; the Windows job-object
and hidden-window paths are the incumbent `background_service`/`no_console_kwargs` ones and are not
exercised on this host.
"""
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
from test_host_delivery import (
    PROFILE,
    RUNTIME_ROOT,
    Clock,
    FakeGitHub,
    SerialStore,
    await_receipt,
    candidate,
    fixture_git,
    observer_for,
    pin,
    plan_document,
    reviewed_release,
    runtime_image,
)

from codex_harness.adapters.host_delivery import (
    DESCRIPTOR_FILE,
    RECEIPT_FILE,
    STATE_FILE,
    _alive,
    checkout_revision,
    host_ports,
    owner_qualified_canary,
    runtime_revision,
    startup_identity_canary,
)
from codex_harness.adapters.managed_runtime import (
    FIXTURE_JOBS_FILE,
    TARGET_FILE,
    ManagedFleetTarget,
    Materializer,
    scan,
)
from codex_harness.application.host_delivery import BUCKET_INTENTS, HostDelivery
from codex_harness.bootstrap import organization
from codex_harness.domain.host_delivery import (
    ACTIVE,
    CANARY_FLEET,
    CANARY_STARTUP,
    DESCRIPTOR_SCHEMA,
    DRAIN_INTENDED,
    KIND_MANAGED,
    MERGED,
    RECEIPT_SCHEMA,
    REGISTRY_SCHEMA,
    ROLLED_BACK,
    DeliveryRefused,
    consumption_verdict,
    descriptor_digest,
    managed_runtime_root,
    resolve_descriptor,
    same_path,
    validate_plan,
    validate_targets,
    within_path,
)
from codex_harness.domain.managed_runtime import (
    HEARTBEAT_SCHEMA,
    LISTING_FILE,
    MANIFEST_FILE,
    STAGE_PREFIX,
    EnvironmentUnqualified,
    check_runtime_path,
    validate_manifest,
    work_verdict,
)

# The labelled fixture lockfile and the "qualified environment" digest registered for it.
LOCK = b"# labelled fixture lockfile: the qualified environment of these tests\n"
LOCK_SHA = hashlib.sha256(LOCK).hexdigest()
MARKER = "# labelled fixture revision B: the candidate's code differs from its predecessor\n"
MODULE_PATH = "src/codex_harness/adapters/managed_runtime.py"
TARGET_ID = "managed-fleet"

needs_profile = pytest.mark.skipif(PROFILE is None, reason="this checkout packages no worker profile")
posix_only = pytest.mark.skipif(os.name == "nt", reason="POSIX process ownership is asserted here; "
                                "the Windows job-object path is not exercised on this host")


# ----- fixtures ---------------------------------------------------------------------------------
def make_source(root: Path) -> dict:
    """A labelled disposable source repository with revisions A and B of this checkout's code."""
    shutil.copytree(Path(RUNTIME_ROOT) / "src" / "codex_harness", root / "src" / "codex_harness",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    (root / "uv.lock").write_bytes(LOCK)
    (root / "README.md").write_text("labelled fixture: not part of any runtime\n", encoding="utf-8")
    fixture_git(root, "init", "-q")
    fixture_git(root, "add", "--all")
    fixture_git(root, "commit", "-q", "--no-verify", "-m", "labelled fixture revision A")
    first = fixture_git(root, "rev-parse", "HEAD")
    module = root / MODULE_PATH
    module.write_bytes(module.read_bytes() + MARKER.encode("utf-8"))
    fixture_git(root, "add", "--all")
    fixture_git(root, "commit", "-q", "--no-verify", "-m", "labelled fixture revision B")
    second = fixture_git(root, "rev-parse", "HEAD")
    return {"root": root, "a": first, "b": second}


@pytest.fixture(scope="module")
def source(tmp_path_factory):
    """One shared read-only source: only Git reads ever reach it (asserted below)."""
    return make_source(tmp_path_factory.mktemp("managed-source") / "source")


def registry(tmp_path, source_root, *, lock=LOCK_SHA, target_id=TARGET_ID, **overrides):
    entry = {"target_id": target_id, "kind": KIND_MANAGED, "root": str(tmp_path / "managed"),
             "state_dir": str(tmp_path / ("state-" + target_id)), "service": "zeus-fleet",
             "source": str(source_root), "python": sys.executable, "environment_lock": lock,
             **overrides}
    return {"schema": REGISTRY_SCHEMA, "targets": [entry]}


def target_for(tmp_path, source_root, **overrides):
    return validate_targets(registry(tmp_path, source_root, **overrides))["targets"][0]


def descriptor(target, source_root, revision, **overrides):
    return {"schema": DESCRIPTOR_SCHEMA, "target_id": target["target_id"],
            "root": managed_runtime_root(target, revision), "revision": revision,
            "worker_image": runtime_image(source_root), "profile_digest": PROFILE or "e" * 64,
            "predecessor": None, **overrides}


def state(target, name):
    return Path(target["state_dir"]) / name


def read(path):
    return json.loads(Path(path).read_text("utf-8"))


def git_state(root):
    return (fixture_git(root, "rev-parse", "HEAD"), fixture_git(root, "status", "--porcelain"))


def await_work(host, target, expected, *, require_paused=False, timeout=30.0):
    """The instance's OWN heartbeat verdict, waited for within a bound."""
    deadline = time.monotonic() + timeout
    verdict = None
    while time.monotonic() < deadline:
        verdict = host.work(target, require_paused=require_paused)
        if verdict["state"] == expected:
            return verdict
        time.sleep(0.1)
    raise AssertionError("heartbeat never reached " + expected + ": " + repr(verdict))


def start_live(host, target, desc, *, jobs=None, expected=None):
    """Seal, switch and start one real managed instance; returns its own startup receipt."""
    host.materialize(target, desc)
    if jobs is not None:
        state(target, FIXTURE_JOBS_FILE).parent.mkdir(parents=True, exist_ok=True)
        state(target, FIXTURE_JOBS_FILE).write_text(json.dumps(jobs), encoding="utf-8")
    host.switch(target, desc, expected=expected)
    host.start(target, desc)
    return await_receipt(target, descriptor_digest(desc), timeout=30.0)


def release_jobs(target):
    jobs = state(target, FIXTURE_JOBS_FILE)
    for job in (read(jobs) if jobs.exists() else []):
        (state(target, "fixture") / ("release-" + job)).touch()


def teardown(target):
    """Test cleanup only: release every fixture job, then end the owned launcher tree.

    SIGTERM reaches the incumbent `run_owned` owner, which reclaims its whole tree; this is the
    cleanup of a test, never the managed target's own stop path, which sends no signal at all.
    """
    release_jobs(target)
    record = read(state(target, STATE_FILE)) if state(target, STATE_FILE).exists() else {}
    receipt = read(state(target, RECEIPT_FILE)) if state(target, RECEIPT_FILE).exists() else {}
    pid = record.get("pid")
    if _alive(pid):
        os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + 20
    while (_alive(pid) or _alive(receipt.get("pid"))) and time.monotonic() < deadline:
        time.sleep(0.05)
    # No launcher and no sealed child outlives a test.
    assert not _alive(pid) and not _alive(receipt.get("pid"))


# ----- the extended target contract ---------------------------------------------------------------
def test_only_the_managed_kind_carries_owner_runtime_fields_and_a_plan_carries_none(tmp_path, source):
    checked = target_for(tmp_path, source["root"])
    assert checked["kind"] == KIND_MANAGED and checked["environment_lock"] == LOCK_SHA
    legacy = {"target_id": "legacy", "kind": "process", "root": str(tmp_path / "legacy"),
              "state_dir": str(tmp_path / "legacy-state"), "service": "svc"}
    assert validate_targets({"schema": REGISTRY_SCHEMA, "targets": [legacy]})["targets"][0] == legacy
    with pytest.raises(DeliveryRefused) as extra:
        validate_targets({"schema": REGISTRY_SCHEMA,
                          "targets": [{**legacy, "source": str(source["root"])}]})
    assert extra.value.reason_code == "plan_fields"
    refusals = [({"environment_lock": "not-a-digest"}, "target_invalid"),
                ({"python": "python3"}, "target_invalid"),
                ({"root": str(source["root"] / "managed")}, "target_overlap"),
                ({"state_dir": str(tmp_path / "managed" / "state")}, "target_overlap"),
                ({"source": str(tmp_path / ("state-" + TARGET_ID))}, "target_overlap")]
    for overrides, code in refusals:
        with pytest.raises(DeliveryRefused) as refused:
            target_for(tmp_path, source["root"], **overrides)
        assert refused.value.reason_code == code, overrides
        assert str(tmp_path) not in str(refused.value)
    # A plan names a target id and a revision; it can never carry a root, a source or a command.
    release = {"id": "release-1", "candidate": candidate(), "policy_hash": "c" * 64}
    plan = plan_document(release, target_id=TARGET_ID, image="none", profile="e" * 64)
    for key, value in (("root", "/elsewhere"), ("source", "/elsewhere"), ("argv", ["sh"])):
        with pytest.raises(DeliveryRefused) as unknown:
            validate_plan({**plan, key: value})
        assert unknown.value.reason_code == "plan_fields"
    # The descriptor root is derived from the registry and the reviewed revision alone.
    resolved = resolve_descriptor(checked, validate_plan(plan), None)
    assert same_path(resolved["root"], tmp_path / "managed" / "runtimes" / plan["target_descriptor"]["revision"])
    assert resolve_descriptor({**legacy, "target_id": TARGET_ID}, validate_plan(plan), None)["root"] == legacy["root"]
    assert KIND_MANAGED in host_ports() and isinstance(host_ports()[KIND_MANAGED], ManagedFleetTarget)


def test_a_descriptor_may_name_only_the_sealed_directory_of_its_own_revision(tmp_path, source):
    target = target_for(tmp_path, source["root"])
    good = descriptor(target, source["root"], source["a"])
    assert same_path(check_runtime_path(target, good), good["root"])
    foreign = [str(source["root"]), managed_runtime_root(target, source["b"]),
               str(Path(target["root"]) / "runtimes" / (STAGE_PREFIX + source["a"] + "-x")),
               str(tmp_path / "elsewhere" / "runtimes" / source["a"]), target["root"]]
    for root in foreign:
        with pytest.raises(DeliveryRefused) as refused:
            check_runtime_path(target, {**good, "root": root})
        assert refused.value.reason_code == "runtime_path_foreign"
    with pytest.raises(DeliveryRefused) as other:
        check_runtime_path(target, {**good, "target_id": "another-target"})
    assert other.value.reason_code == "runtime_target_mismatch"


# ----- the heartbeat verdict -------------------------------------------------------------------------
def fixture_receipt(**overrides):
    """A labelled well formed receipt, as a running instance would write about itself."""
    return {"schema": RECEIPT_SCHEMA, "target_id": TARGET_ID, "instance_id": "1" * 32, "pid": 4242,
            "started_at": "2026-09-23T00:00:00+00:00", "runtime_root": "/managed/runtimes/x",
            "module_root": "/managed/runtimes/x/src/codex_harness", "descriptor_sha256": "d" * 64,
            "revision": "a" * 40, "worker_image": "none", "profile_digest": "e" * 64, **overrides}


def test_an_absent_stale_or_foreign_heartbeat_is_unknown_and_never_idle():
    from datetime import datetime, timedelta, timezone

    now = datetime(2026, 9, 23, tzinfo=timezone.utc)
    receipt = fixture_receipt()
    beat = {"schema": HEARTBEAT_SCHEMA, "instance_id": "1" * 32, "descriptor_sha256": "d" * 64,
            "pid": 4242, "at": now.isoformat(), "admission": "paused", "active": 0, "unresolved": 0}
    cases = [(None, receipt, "heartbeat_missing"), ("unreadable", receipt, "heartbeat_unreadable"),
             ({**beat, "extra": 1}, receipt, "heartbeat_unreadable"),
             ({**beat, "active": -1}, receipt, "heartbeat_unreadable"),
             ({**beat, "instance_id": "2" * 32}, receipt, "heartbeat_mismatched"),
             ({**beat, "descriptor_sha256": "f" * 64}, receipt, "heartbeat_mismatched"),
             ({**beat, "pid": 1}, receipt, "heartbeat_mismatched"),
             ({**beat, "at": (now - timedelta(seconds=31)).isoformat()}, receipt, "heartbeat_stale"),
             ({**beat, "at": (now + timedelta(seconds=60)).isoformat()}, receipt, "heartbeat_future"),
             ({**beat, "at": "yesterday"}, receipt, "heartbeat_unreadable"),
             (beat, None, "heartbeat_receipt_absent"),
             (beat, {**receipt, "pid": "x"}, "heartbeat_receipt_unreadable")]
    for heartbeat, owner, code in cases:
        verdict = work_verdict(heartbeat, owner, now=now, require_paused=True)
        assert verdict == {"state": "unknown", "reason_code": code, "active": None,
                           "unresolved": None, "paused": None}, code
    busy = work_verdict({**beat, "active": 2}, receipt, now=now)
    assert (busy["state"], busy["reason_code"], busy["active"]) == ("busy", "work_active", 2)
    unresolved = work_verdict({**beat, "unresolved": 1}, receipt, now=now)
    assert (unresolved["state"], unresolved["reason_code"]) == ("busy", "work_unresolved")
    open_ = work_verdict({**beat, "admission": "open"}, receipt, now=now, require_paused=True)
    assert (open_["state"], open_["reason_code"]) == ("busy", "pause_unacknowledged")
    assert work_verdict({**beat, "admission": "open"}, receipt, now=now)["state"] == "idle"
    assert work_verdict(beat, receipt, now=now, require_paused=True)["state"] == "idle"


# ----- the materializer --------------------------------------------------------------------------------
def test_the_exact_revision_is_sealed_once_and_a_lost_response_revalidates_it(tmp_path, source):
    target = target_for(tmp_path, source["root"])
    before = git_state(source["root"])
    first = descriptor(target, source["root"], source["a"])
    sealed = Materializer(target).materialize(first)
    assert sealed["sealed"] is True and sealed["recovered"] is False
    root = Path(first["root"])
    manifest = validate_manifest(read(root / MANIFEST_FILE))
    assert manifest["revision"] == source["a"] and manifest["environment_lock"] == LOCK_SHA
    assert manifest["tree"] == fixture_git(source["root"], "rev-parse", source["a"] + "^{tree}")
    listed = [path for path, _ in read(root / LISTING_FILE)]
    assert "uv.lock" in listed and "README.md" not in listed
    assert all(path == "uv.lock" or path.startswith("src/") for path in listed)
    # The incumbent attestation reader sees the sealed revision; the sealed files are read-only.
    assert runtime_revision(root) == source["a"]
    assert not os.access(root / MODULE_PATH, os.W_OK) or os.geteuid() == 0
    # A lost response is answered by revalidating the SAME immutable result, never by resealing.
    mtime = (root / MANIFEST_FILE).stat().st_mtime_ns
    again = Materializer(target).materialize(first)
    assert again["recovered"] is True and again["manifest_sha256"] == sealed["manifest_sha256"]
    assert (root / MANIFEST_FILE).stat().st_mtime_ns == mtime
    # A second revision is a second directory; the first stays sealed and verifiable.
    second = descriptor(target, source["root"], source["b"])
    other = Materializer(target).materialize(second)
    assert other["manifest_sha256"] != sealed["manifest_sha256"]
    assert MARKER in (Path(second["root"]) / MODULE_PATH).read_text("utf-8")
    assert MARKER not in (root / MODULE_PATH).read_text("utf-8")
    assert Materializer(target).verify(first)["revision"] == source["a"]
    # Only Git reads reached the owner's source: HEAD and the working tree are unchanged.
    assert git_state(source["root"]) == before


def test_an_interrupted_seal_leaves_named_evidence_and_the_retry_seals_once(tmp_path, source, monkeypatch):
    target = target_for(tmp_path, source["root"])
    desc = descriptor(target, source["root"], source["a"])

    def interrupted(src, dst):
        raise OSError("labelled injected interruption between stage and seal")

    monkeypatch.setattr(os, "rename", interrupted)
    with pytest.raises(OSError):
        Materializer(target).materialize(desc)
    monkeypatch.undo()
    runtimes = Path(target["root"]) / "runtimes"
    stages = [p.name for p in runtimes.iterdir() if p.name.startswith(STAGE_PREFIX + source["a"])]
    assert len(stages) == 1 and not Path(desc["root"]).exists()
    with pytest.raises(DeliveryRefused) as unsealed:
        Materializer(target).verify(desc)
    assert unsealed.value.reason_code == "runtime_unsealed"
    assert Materializer(target).materialize(desc)["recovered"] is False
    # The partial stage is still there, under its own name, as recovery evidence.
    assert stages[0] in {p.name for p in runtimes.iterdir()}
    assert Materializer(target).verify(desc)["revision"] == source["a"]


def test_a_changed_or_foreign_directory_is_refused_and_never_overwritten(tmp_path, source):
    target = target_for(tmp_path, source["root"])
    desc = descriptor(target, source["root"], source["a"])
    Materializer(target).materialize(desc)
    module = Path(desc["root"]) / MODULE_PATH
    module.chmod(0o644)
    module.write_bytes(module.read_bytes() + b"# labelled injected tampering\n")
    for attempt in (Materializer(target).verify, Materializer(target).materialize):
        with pytest.raises(DeliveryRefused) as changed:
            attempt(desc)
        assert changed.value.reason_code == "runtime_content_mismatch"
    assert module.read_bytes().endswith(b"# labelled injected tampering\n")  # nothing overwritten
    foreign = Path(managed_runtime_root(target, source["b"]))
    foreign.mkdir(parents=True)
    (foreign / "owner-file.txt").write_text("labelled unowned evidence", encoding="utf-8")
    with pytest.raises(DeliveryRefused) as unowned:
        Materializer(target).materialize(descriptor(target, source["root"], source["b"]))
    assert unowned.value.reason_code == "manifest_schema"
    assert [p.name for p in foreign.iterdir()] == ["owner-file.txt"]


def test_an_unresolved_revision_or_unqualified_environment_writes_nothing(tmp_path, source):
    target = target_for(tmp_path, source["root"])
    with pytest.raises(DeliveryRefused) as missing:
        Materializer(target).materialize(descriptor(target, source["root"], "0" * 40))
    assert missing.value.reason_code == "runtime_revision_unresolved"
    requalified = target_for(tmp_path, source["root"], lock="9" * 64)
    with pytest.raises(EnvironmentUnqualified) as unqualified:
        Materializer(requalified).materialize(descriptor(requalified, source["root"], source["a"]))
    assert unqualified.value.reason_code == "environment_unqualified"
    runtimes = Path(target["root"]) / "runtimes"
    assert not runtimes.exists() or list(runtimes.iterdir()) == []


def test_a_linked_worktree_resolves_through_git_and_its_checkout_revision_through_commondir(tmp_path):
    repository = make_source(tmp_path / "linked-source")
    worktree = tmp_path / "linked-worktree"
    fixture_git(repository["root"], "worktree", "add", "-q", "-b", "fixture-linked", str(worktree),
                repository["a"])
    # The incumbent receipt reader now follows `commondir`; before, a linked worktree read as None.
    assert checkout_revision(worktree) == repository["a"]
    assert checkout_revision(repository["root"]) == repository["b"]
    target = target_for(tmp_path, worktree)
    sealed = Materializer(target).materialize(descriptor(target, worktree, repository["b"]))
    assert sealed["revision"] == repository["b"]


# ----- the actual child -------------------------------------------------------------------------
@needs_profile
@posix_only
def test_a_bad_runtime_is_refused_before_the_running_instance_is_touched(tmp_path, source):
    target = target_for(tmp_path, source["root"])
    host = ManagedFleetTarget(workload="fixture")
    good = descriptor(target, source["root"], source["a"])
    try:
        receipt = start_live(host, target, good)
        launch = read(state(target, STATE_FILE))
        Materializer(target).materialize(descriptor(target, source["root"], source["b"]))
        tampered = Path(target["root"]) / "runtimes" / source["b"] / "src" / "codex_harness" / "extra.py"
        cases = [(descriptor(target, source["root"], source["a"], root=str(source["root"])),
                  "runtime_path_foreign"),
                 (descriptor(target, source["root"], "0" * 40), "runtime_unsealed"),
                 (descriptor(target, source["root"], source["a"], worker_image="another-image"),
                  "runtime_image_mismatch"),
                 (descriptor(target, source["root"], source["b"]), "runtime_content_mismatch")]
        tampered.write_text("# labelled injected foreign file\n", encoding="utf-8")
        current = good
        for bad, code in cases:
            host.switch(target, bad, expected=descriptor_digest(current))
            current = bad
            with pytest.raises(DeliveryRefused) as refused:
                host.start(target, bad, authorize=lambda: None,
                           replaces={"descriptor_sha256": descriptor_digest(good),
                                     "instance_id": receipt["instance_id"], "launch": launch})
            assert refused.value.reason_code == code
            # Refused BEFORE any effect: same process, same receipt, no stop request, no new launch.
            assert host.running(target) and read(state(target, STATE_FILE)) == launch
            assert read(state(target, RECEIPT_FILE)) == receipt
            assert not state(target, "stop.json").exists()
    finally:
        teardown(target)


@needs_profile
@posix_only
def test_a_clean_start_a_restart_and_a_repeated_start_launch_exactly_once(tmp_path, source):
    target = target_for(tmp_path, source["root"])
    host = ManagedFleetTarget(workload="fixture")
    desc = descriptor(target, source["root"], source["a"])
    try:
        receipt = start_live(host, target, desc)
        verdict = consumption_verdict(desc, receipt)
        assert verdict["consumed"], verdict["reason_code"]
        # The child imported ONLY the sealed runtime, and says which revision that is.
        assert same_path(receipt["runtime_root"], desc["root"])
        assert within_path(receipt["module_root"], desc["root"]) and receipt["revision"] == source["a"]
        assert read(state(target, TARGET_FILE))["source"] == str(source["root"])
        await_work(host, target, "idle")
        first = read(state(target, STATE_FILE))
        # A repeated start (a lost start response, a second controller) recognizes the instance.
        again = ManagedFleetTarget(workload="fixture").start(target, desc)
        assert again["started"] is False and again["recovered"] is True
        assert read(state(target, STATE_FILE)) == first
        # A clean stop is a pause, an idle heartbeat and the graceful stop file; nothing is signalled.
        stopped = host.stop(target)
        assert stopped["stopped"] is True and not _alive(first["pid"])
        journal = [json.loads(line) for line in
                   state(target, "launcher-journal.jsonl").read_text("utf-8").splitlines()]
        assert journal[-1]["event"] == "shutdown" and journal[-1]["final_exit_code"] == 0
        # The restart of the same descriptor is a new instance of the same sealed runtime.
        restarted = host.start(target, desc)
        assert restarted["started"] is True and restarted["pid"] != first["pid"]
        fresh = await_receipt(target, descriptor_digest(desc), timeout=30.0)
        while fresh["instance_id"] == receipt["instance_id"]:
            time.sleep(0.05)
            fresh = read(state(target, RECEIPT_FILE))
        assert consumption_verdict(desc, fresh)["consumed"] and fresh["revision"] == source["a"]
    finally:
        teardown(target)


@needs_profile
@posix_only
def test_a_child_that_outlives_its_killed_launcher_is_still_running_and_stops_gracefully(tmp_path,
                                                                                        source):
    """The documented POSIX limit of the incumbent owner: SIGKILL of the launcher leaves its child.
    That child is still a Fleet runner on this target, never an absence to start over on."""
    target = target_for(tmp_path, source["root"])
    host = ManagedFleetTarget(workload="fixture")
    desc = descriptor(target, source["root"], source["a"])
    try:
        receipt = start_live(host, target, desc)
        await_work(host, target, "idle")
        launcher = read(state(target, STATE_FILE))["pid"]
        os.kill(launcher, signal.SIGKILL)  # labelled injected outright kill of the owner
        deadline = time.monotonic() + 10
        while _alive(launcher) and time.monotonic() < deadline:
            time.sleep(0.05)
        assert not _alive(launcher) and _alive(receipt["pid"])
        assert host.running(target) is True
        # The orphan still honours the pause and reports its own paused, idle heartbeat.
        assert host.drain(target)["running"] is True
        await_work(host, target, "idle", require_paused=True)
        assert host.drain(target)["drained"] is True
        stopped = host.stop(target)
        assert stopped["stopped"] is True and not _alive(receipt["pid"])
    finally:
        teardown(target)


@needs_profile
@posix_only
def test_two_owners_starting_at_once_launch_a_single_runtime(tmp_path, source):
    target = target_for(tmp_path, source["root"])
    desc = descriptor(target, source["root"], source["a"])
    owners = [ManagedFleetTarget(workload="fixture"), ManagedFleetTarget(workload="fixture")]
    owners[0].materialize(target, desc)
    owners[0].switch(target, desc, expected=None)
    barrier, results = threading.Barrier(2), []

    def start(owner):
        barrier.wait()
        try:
            results.append(owner.start(target, desc))
        except DeliveryRefused as exc:
            results.append({"started": False, "refused": exc.reason_code})

    threads = [threading.Thread(target=start, args=(owner,)) for owner in owners]
    try:
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(60)
        assert sorted(bool(r.get("started")) for r in results) == [False, True], results
        loser = next(r for r in results if not r.get("started"))
        assert loser.get("recovered") or loser.get("refused") in {"instance_unidentified",
                                                                   "target_lock_held"}
        winner = next(r for r in results if r.get("started"))
        assert read(state(target, STATE_FILE))["pid"] == winner["pid"]
        assert consumption_verdict(desc, await_receipt(target, descriptor_digest(desc),
                                                      timeout=30.0))["consumed"]
    finally:
        teardown(target)


@needs_profile
@posix_only
def test_active_owned_work_prevents_the_drain_and_the_stop_until_it_finishes(tmp_path, source):
    target = target_for(tmp_path, source["root"])
    host = ManagedFleetTarget(workload="fixture", stop_timeout=1.0)
    good = descriptor(target, source["root"], source["a"])
    try:
        receipt = start_live(host, target, good, jobs=["job-1"])
        busy = await_work(host, target, "busy")
        assert (busy["reason_code"], busy["active"]) == ("work_active", 1)
        drained = host.drain(target)
        assert drained["drained"] is False and drained["unconfirmed"] == 0
        assert drained["work"]["state"] == "busy"
        stopped = host.stop(target)
        assert stopped["stopped"] is False and stopped["reason_code"] == "instance_work_busy"
        assert host.running(target) and not state(target, "stop.json").exists()
        # The same refusal reaches a start that would have to replace this instance.
        successor = descriptor(target, source["root"], source["b"],
                               predecessor=descriptor_digest(good))
        host.materialize(target, successor)
        host.switch(target, successor, expected=descriptor_digest(good))
        with pytest.raises(DeliveryRefused) as refused:
            host.start(target, successor, authorize=lambda: None,
                       replaces={"descriptor_sha256": descriptor_digest(good),
                                 "instance_id": receipt["instance_id"],
                                 "launch": read(state(target, STATE_FILE))})
        assert refused.value.reason_code == "instance_work_busy"
        assert read(state(target, RECEIPT_FILE)) == receipt and host.running(target)
        # The owned child finishes; admission stayed closed, so the instance is now idle and paused.
        release_jobs(target)
        idle = await_work(host, target, "idle", require_paused=True)
        assert idle["paused"] is True and idle["active"] == 0
        assert host.drain(target)["drained"] is True
        assert host.stop(target)["stopped"] is True
    finally:
        teardown(target)


@needs_profile
@posix_only
def test_an_unavailable_heartbeat_prevents_idle_and_the_stop(tmp_path, source):
    target = target_for(tmp_path, source["root"])
    host = ManagedFleetTarget(workload="fixture")
    desc = descriptor(target, source["root"], source["a"])
    try:
        receipt = start_live(host, target, desc)
        await_work(host, target, "idle")
        # The discriminating control: the same live instance read with a zero freshness bound.
        strict = ManagedFleetTarget(workload="fixture", heartbeat_max_age=0.0, stop_timeout=0.5)
        time.sleep(0.05)
        drained = strict.drain(target)
        assert drained["drained"] is False and drained["unconfirmed"] == 1
        assert drained["work"]["reason_code"] in {"heartbeat_stale", "heartbeat_future"}
        refused = strict.stop(target)
        assert refused["stopped"] is False and refused["reason_code"] == "instance_work_unknown"
        # A heartbeat that cannot be bound to a startup receipt identifies no one's work.
        state(target, RECEIPT_FILE).unlink()  # labelled injected loss of the receipt
        assert host.work(target, require_paused=True)["reason_code"] == "heartbeat_receipt_absent"
        assert host.drain(target)["unconfirmed"] == 1 and host.running(target)
        state(target, RECEIPT_FILE).write_text(json.dumps(receipt), encoding="utf-8")
        assert host.drain(target)["drained"] is True
    finally:
        teardown(target)


# ----- through the coordinator ------------------------------------------------------------------------
def managed_system(tmp_path, source, *, canaries=None, lock=LOCK_SHA, host=None):
    """One wired controller over a real managed target and the labelled GitHub double."""
    store, org, clock = SerialStore(), organization(), Clock()
    release = reviewed_release(store, org)
    host = host or ManagedFleetTarget(workload="fixture")
    delivery = HostDelivery(store, org, github=FakeGitHub(), hosts={KIND_MANAGED: host},
                            canaries=canaries or {CANARY_STARTUP: startup_identity_canary,
                                                  CANARY_FLEET: owner_qualified_canary},
                            clock=clock, observer=observer_for(store), enabled=True,
                            resume_seconds=0)
    document = registry(tmp_path, source["root"], lock=lock)
    delivery.register_targets(document)
    plan = plan_document(release, target_id=TARGET_ID, image=runtime_image(source["root"]),
                         profile=PROFILE, descriptor_revision=source["a"], consumption_timeout=900)
    delivery.register(plan, pin())
    return {"store": store, "org": org, "clock": clock, "delivery": delivery, "host": host,
            "plan": plan, "target": validate_targets(document)["targets"][0]}


def successor(system, source, *, expected, canary=CANARY_STARTUP):
    release = reviewed_release(system["store"], system["org"],
                               record_candidate={**candidate(), "revision": "5" * 40,
                                                 "branch": "harness/two", "task_id": "two"})
    plan = plan_document(release, plan_id="managed-plan-2", target_id=TARGET_ID, expected=expected,
                         image=runtime_image(source["root"]), profile=PROFILE, canary=canary,
                         descriptor_revision=source["b"], consumption_timeout=900)
    system["delivery"].register(plan, pin(path="docs/zeus/operations/delivery-2.json"))
    system["plan"] = plan
    return plan


def advance(system, until, *, limit=200, pause=0.1):
    """Tick until a stage, giving the REAL launcher and child time to report between waits."""
    results = []
    for _ in range(limit):
        result = system["delivery"].tick()
        system["clock"].advance(1)
        results.append(result)
        if result["stage"] == until or result["outcome"] in {"blocked", "refused"}:
            return results
        if result["outcome"] in {"pending", "unavailable", "controller_busy"}:
            time.sleep(pause)
    return results


def trail(results):
    return "\n".join(str((r["stage"], r["outcome"], r["reason_code"], r["error_type"])) for r in results)


def intent(system):
    with system["store"].transaction() as tx:
        return tx.get(BUCKET_INTENTS, system["plan"]["plan_id"])


def test_an_unqualified_environment_is_a_named_unavailable_gate_before_any_host_change(tmp_path, source):
    system = managed_system(tmp_path, source, lock="9" * 64)
    results = advance(system, DRAIN_INTENDED, limit=12)
    stuck = [r for r in results if r["reason_code"] == "environment_unqualified"]
    assert stuck and stuck[0]["outcome"] == "unavailable", trail(results)
    assert stuck[0]["error_type"] == "EnvironmentUnqualified" and stuck[0]["stage"] == MERGED
    assert intent(system)["stage"] == MERGED
    assert not (Path(system["target"]["root"]) / "runtimes").exists()
    assert not Path(system["target"]["state_dir"]).exists()


class LostMaterializeResponse(ManagedFleetTarget):
    """Labelled injection: the first seal HAPPENS, and then its response is lost."""

    lost = 1

    def materialize(self, target, descriptor, *, authorize=None):
        sealed = super().materialize(target, descriptor, authorize=authorize)
        if self.lost:
            self.lost -= 1
            raise RuntimeError("labelled injected lost materialize response")
        return sealed


def test_a_lost_materialize_response_is_revalidated_and_projected_without_paths(tmp_path, source):
    system = managed_system(tmp_path, source, host=LostMaterializeResponse(workload="fixture"))
    results = advance(system, DRAIN_INTENDED, limit=60)
    assert results[-1]["stage"] == DRAIN_INTENDED, trail(results)
    assert any(r["outcome"] == "unavailable" and r["stage"] == MERGED for r in results)
    runtime = intent(system)["runtime"]
    assert runtime["recovered"] is True and runtime["revision"] == source["a"]
    runtimes = Path(system["target"]["root"]) / "runtimes"
    assert sorted(p.name for p in runtimes.iterdir()) == [source["a"]]  # sealed exactly once
    status = system["delivery"].status()
    view = status["deliveries"][0]
    assert view["runtime"]["manifest_sha256"] == runtime["manifest_sha256"]
    assert str(tmp_path) not in json.dumps(status)


@needs_profile
@posix_only
def test_forward_activation_consumes_two_sealed_revisions_and_retains_the_predecessor(tmp_path, source):
    system = managed_system(tmp_path, source)
    target, host = system["target"], system["host"]
    try:
        results = advance(system, ACTIVE)
        assert results[-1]["stage"] == ACTIVE, trail(results)
        first = read(state(target, RECEIPT_FILE))
        root_a = managed_runtime_root(target, source["a"])
        assert same_path(first["runtime_root"], root_a) and first["revision"] == source["a"]
        await_work(host, target, "idle")
        good = read(state(target, DESCRIPTOR_FILE))
        successor(system, source, expected=descriptor_digest(good))
        results = advance(system, ACTIVE)
        assert results[-1]["stage"] == ACTIVE, trail(results)
        second = read(state(target, RECEIPT_FILE))
        root_b = managed_runtime_root(target, source["b"])
        assert same_path(second["runtime_root"], root_b) and within_path(second["module_root"], root_b)
        assert second["revision"] == source["b"] and second["instance_id"] != first["instance_id"]
        assert MARKER in (Path(second["module_root"]) / "adapters" / "managed_runtime.py").read_text("utf-8")
        assert not _alive(first["pid"])
        # The drain was the instance's own idle, paused report, recorded with the stage.
        assert intent(system)["work"]["state"] == "idle" and intent(system)["work"]["paused"] is True
        # The predecessor's sealed runtime is retained, byte for byte, for a rollback.
        assert Materializer(target).verify(good)["revision"] == source["a"]
        assert read(state(target, DESCRIPTOR_FILE))["predecessor"] == descriptor_digest(good)
    finally:
        teardown(target)


@needs_profile
@posix_only
def test_a_failed_candidate_restores_the_predecessor_which_runs_its_old_code(tmp_path, source):
    system = managed_system(tmp_path, source)
    target, host = system["target"], system["host"]
    try:
        assert advance(system, ACTIVE)[-1]["stage"] == ACTIVE
        good = read(state(target, DESCRIPTOR_FILE))
        await_work(host, target, "idle")
        # The owner's qualified-work canary has no receipt for the candidate: an honest failure.
        successor(system, source, expected=descriptor_digest(good), canary=CANARY_FLEET)
        results = advance(system, ROLLED_BACK)
        assert results[-1]["stage"] == ROLLED_BACK, trail(results)
        assert "canary_owner_receipt_missing" in {r["reason_code"] for r in results}
        restored = read(state(target, RECEIPT_FILE))
        root_a = managed_runtime_root(target, source["a"])
        # The running instance is a NEW instance of the predecessor, importing its OLD code.
        assert same_path(restored["runtime_root"], root_a) and restored["revision"] == source["a"]
        code = (Path(restored["module_root"]) / "adapters" / "managed_runtime.py").read_text("utf-8")
        assert MARKER not in code
        assert consumption_verdict(good, restored)["consumed"] and host.running(target)
        assert read(state(target, DESCRIPTOR_FILE)) == good
        # The candidate's sealed runtime is retained as evidence, never deleted.
        assert Materializer(target).verify(
            descriptor(target, source["root"], source["b"], predecessor=descriptor_digest(good)))
    finally:
        teardown(target)


def test_the_scan_refuses_a_symlink_inside_a_runtime(tmp_path):
    root = tmp_path / "runtime"
    (root / "src").mkdir(parents=True)
    (root / "src" / "a.py").write_text("x = 1\n", encoding="utf-8")
    assert scan(root) == [["src/a.py", subprocess.run(
        ["git", "hash-object", str(root / "src" / "a.py")], capture_output=True, text=True,
        check=True).stdout.strip()]]
    (root / "src" / "link.py").symlink_to(root / "src" / "a.py")
    assert scan(root) is None
