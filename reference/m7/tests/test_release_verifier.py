"""The owned-attempt port and the resume transaction over the fixed matrix (INV-HOST-DELIVERY-VERIFY-001).

Real here: `HostDelivery` with its `Releases`/`ReleaseQueue` owners over `SerialStore` (a MemoryStore
that refuses a nested transaction, as the PostgreSQL advisory lock would deadlock on one) or a plain
`MemoryStore` for the thread races, the `ReleaseVerifier` port with its attempt records, `/proc`, real
host child processes and process groups, and `os.killpg`.

Labelled doubles: the EVALUATOR is a scripted stand-in for `ReleaseRunner` (the real evaluator runs in
tests/test_host_delivery_verification.py); `docker` is the synthetic CLI of
tests/verification_fixtures.py; the cgroup v2 tree is a temporary directory; GitHub is `FakeGitHub`.
Every crafted durable record is labelled where it is written. Nothing here touches a production
service, database, credential, provider or model.
"""
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
    BASE,
    MERGED_REVISION,
    TREE,
    Clock,
    FakeGitHub,
    SerialStore,
    candidate,
    pin,
    plan_document,
    reviewed_release,
    targets_document,
)
from verification_fixtures import fake_docker

from codex_harness.adapters.artifacts import FileArtifacts
from codex_harness.adapters.commands import _announce, run_process
from codex_harness.adapters.deployment import (
    RETRY_AUTH,
    RETRY_ISOLATION,
    RETRY_WORKSPACE,
    ReleaseRunner,
    attempt_resources,
)
from codex_harness.adapters.host_delivery import ProcessHostTarget
from codex_harness.adapters.release_verifier import (
    CancellationBoundary,
    EvaluationCancelled,
    HostFacts,
    ReleaseVerifier,
)
from codex_harness.adapters.store import MemoryStore
from codex_harness.application.host_delivery import BUCKET_INTENTS, HostDelivery
from codex_harness.application.release_queue import ReleaseQueue
from codex_harness.application.tickets import TicketSuperseded
from codex_harness.bootstrap import organization
from codex_harness.domain.host_delivery import (
    BLOCKED,
    FAILED,
    MERGED,
    PUBLISHING,
    VERIFYING,
    DeliveryRefused,
    new_intent,
    plan_digest,
    resumable,
    validate_plan,
)
from codex_harness.domain.model import ContractError

EVIDENCE = "sha256:" + "ab" * 32
OTHER_EVIDENCE = "sha256:" + "cd" * 32
IMAGE_ID = "sha256:" + "e" * 64


class ScriptedRunner:
    """LABELLED DOUBLE of `ReleaseRunner.evaluate`: `script(fence, attempt_id)` decides the answer."""

    calls: list = []

    def __init__(self, script, fence):
        self.script, self.fence = script, fence

    def evaluate(self, release_id, *, attempt=None):
        ScriptedRunner.calls.append(attempt)
        return self.script(self.fence, attempt)


def passed(fence, attempt):
    fence()
    run_process(["true"])  # a real owned child, recorded by the attempt
    return {"verdict": "checked", "passed": True, "image": IMAGE_ID, "receipt": {"attempt_id": attempt},
            "checks": {"tests": {"passed": True, "evidence": "sha256:" + "1" * 64}}}


def never(fence, attempt):
    raise AssertionError("the evaluator must not be called")


def build(tmp_path, monkeypatch, *, script=passed, verified=False, store=None, record=None, facts=None):
    daemon = fake_docker(tmp_path, monkeypatch)
    ScriptedRunner.calls = []
    store = store if store is not None else SerialStore()
    org = organization()
    clock = Clock()
    release = reviewed_release(store, org, verified=verified, record_candidate=record)
    cgroups = tmp_path / "cgroup"  # labelled: a fake cgroup v2 root, observable by its cgroup.controllers
    cgroups.mkdir(parents=True, exist_ok=True)
    (cgroups / "cgroup.controllers").write_text("cpu memory pids\n", encoding="ascii")
    facts = facts or HostFacts(cgroup_root=cgroups)
    root = tmp_path / "verification"
    box = {"script": script}
    verifier = ReleaseVerifier(lambda fence: ScriptedRunner(box["script"], fence), root=root,
                               artifacts=lambda: FileArtifacts(str(tmp_path / "artifacts")), facts=facts)
    github = FakeGitHub(fast_forward=True)
    delivery = HostDelivery(store, org, github=github, hosts={"process": ProcessHostTarget(max_seconds=30)},
                            clock=clock, enabled=True, resume_seconds=0, verifier=verifier)
    registry = targets_document(tmp_path)
    delivery.register_targets(registry)
    plan = plan_document(release)
    delivery.register(plan, pin())
    return {"store": store, "org": org, "clock": clock, "delivery": delivery, "release": release, "plan": plan,
            "github": github, "daemon": daemon, "root": root, "facts": facts, "verifier": verifier, "box": box,
            "tmp": tmp_path}


def tick(system):
    result = system["delivery"].tick()
    system["clock"].advance(1)
    return result


def intent_of(system, plan_id=None):
    with system["store"].transaction() as tx:
        return tx.get(BUCKET_INTENTS, plan_id or system["plan"]["plan_id"])


def queue_row(system):
    with system["store"].transaction() as tx:
        return tx.get("release_queue", system["release"]["id"])


def release_status(system):
    with system["store"].transaction() as tx:
        return tx.get("releases", system["release"]["id"])["status"], tx.get("images", system["release"]["id"])


def everything(store):
    with store.transaction() as tx:
        return tx.records()


def to_verifying(system):
    result = tick(system)
    assert result["stage"] == VERIFYING and result["outcome"] == "progressed"
    return result


def dead_owner(system, **overrides):
    """A recorded owner that is provably not running because its identity was REPLACED: this live
    pid under another start time (the pid now names another process)."""
    return {"pid": os.getpid(), "start_ticks": 1, "boot_id": system["facts"].boot_id(),
            "cgroup": "/fixture.slice/dead-owner.scope", **overrides}


def reaped_owner(system):
    """A recorded owner whose pid provably no longer EXISTS: a real child, started, then reaped."""
    child = spawn_group("sleep", "60")
    ticks = system["facts"].start_ticks(child.pid)
    child.kill()
    child.wait()
    assert ticks is not None and not os.path.lexists("/proc/" + str(child.pid))  # its entry is gone
    return {"pid": child.pid, "start_ticks": ticks, "boot_id": system["facts"].boot_id(),
            "cgroup": "/fixture.slice/dead-owner.scope"}


class ProcView:
    """LABELLED FAKE PROC ROOT over the kernel's own facts: `self` and every linked pid are symlinks
    to the real `/proc` entries and the boot id is the real one, so exactly ONE observation (one
    pid's `stat`, or the boot id) can be faulted while every other fact stays what the kernel says."""

    def __init__(self, root: Path):
        self.root = root
        self.boot = root / "sys" / "kernel" / "random" / "boot_id"
        self.boot.parent.mkdir(parents=True)
        self.real_boot = Path("/proc/sys/kernel/random/boot_id").read_text("ascii")
        self.show_boot()
        (root / "self").symlink_to("/proc/self")
        self.link(os.getpid())

    def link(self, pid: int) -> None:
        (self.root / str(pid)).symlink_to("/proc/" + str(pid))

    def fault(self, pid: int, how: str) -> None:
        """Only `<pid>/stat` changes: unreadable (EACCES), garbage, truncated after the name, or
        `replaced` - a whole valid stat of that pid under another start time."""
        entry = self.root / str(pid)
        real = (entry / "stat").read_text("utf-8")
        entry.unlink()
        entry.mkdir()
        head, fields = real[:real.rindex(")") + 1], real[real.rindex(")") + 1:].split()
        fields[19] = str(int(fields[19]) + 1)
        text = {"eacces": real, "garbage": "not a stat line\n", "truncated": real[:real.rindex(")") + 3],
                "replaced": head + " " + " ".join(fields) + "\n"}[how]
        (entry / "stat").write_text(text, encoding="utf-8")
        if how == "eacces":
            (entry / "stat").chmod(0)

    def restore(self, pid: int) -> None:
        entry = self.root / str(pid)
        (entry / "stat").chmod(0o600)
        shutil.rmtree(entry)
        self.link(pid)

    def lose_self(self, how: str) -> None:
        """The root stops showing THIS process as itself: its `self` names another pid (a mount of
        another pid namespace) or is missing. Every other entry stays what it was."""
        (self.root / "self").unlink()
        if how == "other_namespace":
            (self.root / "self").mkdir()
            (self.root / "self" / "stat").write_text(fake_stat(os.getpid() + 1, 5), encoding="utf-8")

    def restore_self(self) -> None:
        entry = self.root / "self"
        if entry.is_symlink():
            entry.unlink()
        elif entry.exists():
            shutil.rmtree(entry)
        entry.symlink_to("/proc/self")

    def hide_boot(self) -> None:
        self.boot.unlink()

    def show_boot(self) -> None:
        self.boot.write_text(self.real_boot, encoding="ascii")


def killpg_spy(monkeypatch) -> list:
    """Every `os.killpg(pgid, signal)` from here on, still delivered; the probe signal 0 included."""
    real, signals = os.killpg, []

    def spy(pgid, sig):
        signals.append((pgid, sig))
        return real(pgid, sig)

    monkeypatch.setattr(os, "killpg", spy)
    return signals


def craft_record(system, attempt_id, owner, *, children=(), state="started", with_intent=True):
    """LABELLED CRAFTED RECORD: what a controller SIGKILLed mid-evaluation leaves behind."""
    path = system["root"] / "attempts" / attempt_id / "run.json"
    path.parent.mkdir(parents=True)
    record = {"attempt_id": attempt_id, "plan_id": system["plan"]["plan_id"], "release_id": system["release"]["id"],
              "generation": 1, "owner": owner, "started_at": "2026-09-22T00:00:00+00:00",
              "resources": attempt_resources(attempt_id), "children": list(children),
              "lifecycle": [{"state": "prepared"}, {"state": state}], "state": state, "cleanup": None,
              "record": str(path)}
    path.write_text(json.dumps(record), encoding="utf-8")
    if with_intent:
        with system["store"].transaction() as tx:
            intent = tx.get(BUCKET_INTENTS, system["plan"]["plan_id"])
            attempts = [*(intent.get("verification") or {}).get("attempts", []),
                        {"attempt_id": attempt_id, "generation": 1, "owner": owner,
                         "started_at": record["started_at"], "state": "prepared", "cleanup": None, "outcome": None}]
            tx.put(BUCKET_INTENTS, intent["id"], {**intent, "verification": {"attempts": attempts}})
    return record


def container_id(seed: str) -> str:
    return (seed * 64)[:64]


def exact_containers(system, attempt_id):
    for role, seed in (("release-start", "a"), ("release-canary", "b")):
        system["daemon"].add_container(container_id(seed + attempt_id[:3]), "zeus-" + role + "-" + attempt_id,
                                       {"zeus.isolated.run": attempt_id, "zeus.isolated.role": role})


def names_touched(system) -> set:
    return {part for call in system["daemon"].calls() for part in call}


def spawn_group(*argv):
    return subprocess.Popen(list(argv), start_new_session=True, stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def gone(pgid):
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return True
    return False


# ----- N-2 / F-2 / F-3 ---------------------------------------------------------------------------------
def test_an_already_verified_release_keeps_todays_path_with_no_attempt(tmp_path, monkeypatch):
    system = build(tmp_path, monkeypatch, script=never, verified=True)
    result = tick(system)
    assert result["stage"] == PUBLISHING and ScriptedRunner.calls == []
    assert "verification" not in intent_of(system)


@pytest.mark.parametrize("code", [RETRY_ISOLATION, RETRY_AUTH, RETRY_WORKSPACE,
                                  "verification_observation_unavailable"])
def test_an_observation_error_is_a_named_retry_that_keeps_the_stage(tmp_path, monkeypatch, code):
    system = build(tmp_path, monkeypatch, script=lambda fence, attempt: {
        "verdict": "retry", "reason_code": code, "evidence": "sha256:" + "2" * 64, "checks": {}})
    to_verifying(system)
    result = tick(system)
    assert result["outcome"] == "unavailable" and result["reason_code"] == code
    assert intent_of(system)["stage"] == VERIFYING
    status, image = release_status(system)
    assert status == "reviewed" and image is None
    (attempt,) = intent_of(system)["verification"]["attempts"]
    assert attempt["cleanup"]["state"] == "confirmed" and attempt["outcome"]["reason_code"] == code
    row = queue_row(system)
    assert row["status"] == "retry" and row["retry_at"]  # the queue's own backoff, unchanged


def test_the_real_evaluator_checks_auth_presence_and_workspaces_before_any_work(tmp_path):
    """F-2 on the REAL `ReleaseRunner.evaluate`: a missing auth file (presence only, never opened)
    and an unavailable review workspace are retries, and the store is never written."""
    store = MemoryStore()
    org = organization()
    release = reviewed_release(store, org, verified=False)

    class Git:  # labelled: the candidate identity matches; the workspace cannot be prepared
        def inspect(self, revision, base):
            return {"tree": TREE, "diff": ""}

        def target_identity(self):
            return release["candidate"]["repository"]

        def review_workspace(self, revision, review_id):
            raise OSError("fixture: workspace unavailable")

    service = type("Service", (), {"store": store, "org": org})()
    artifacts = FileArtifacts(str(tmp_path / "artifacts"))
    before = everything(store)
    missing = ReleaseRunner(service, Git(), artifacts, str(tmp_path / "absent-auth.json"))
    answer = missing.evaluate(release["id"], attempt="f" * 32)
    assert answer["verdict"] == "retry" and answer["reason_code"] == RETRY_AUTH
    auth = tmp_path / "auth-placeholder.json"
    auth.write_text("{}", encoding="utf-8")
    runner = ReleaseRunner(service, Git(), artifacts, str(auth))
    answer = runner.evaluate(release["id"], attempt="f" * 32)
    assert answer["verdict"] == "retry" and answer["reason_code"] == RETRY_WORKSPACE
    with pytest.raises(OSError):  # the legacy runner (no attempt) keeps raising, unchanged
        runner.evaluate(release["id"])
    assert everything(store) == before


def test_identity_divergence_refuses_and_a_superseded_ticket_is_recorded(tmp_path, monkeypatch):
    def diverged(fence, attempt):
        raise ContractError("Candidate tree mismatch")

    system = build(tmp_path, monkeypatch, script=diverged)
    to_verifying(system)
    result = tick(system)
    assert result["outcome"] == "refused" and result["reason_code"] == "verification_refused"
    assert intent_of(system)["stage"] == BLOCKED and release_status(system)[0] == "reviewed"

    def superseded(fence, attempt):
        raise TicketSuperseded("ticket revised")

    other = build(tmp_path / "second", monkeypatch, script=superseded)
    to_verifying(other)
    result = tick(other)
    assert result["reason_code"] == "release_superseded_by_ticket_revision"
    assert release_status(other)[0] == "superseded_by_ticket_revision"
    assert other["github"].publishes == 0


def test_a_hook_candidate_halts_before_any_attempt_exists(tmp_path, monkeypatch):
    system = build(tmp_path, monkeypatch, script=never, record={**candidate(), "hook_id": "hook-1"})
    to_verifying(system)
    result = tick(system)
    assert result["outcome"] == "blocked" and result["reason_code"] == "release_hook_unsupported"
    assert "verification" not in intent_of(system) and not (system["root"] / "attempts").exists()


# ----- L-4 .. L-10: exact reconciliation ---------------------------------------------------------------
@pytest.mark.parametrize("how", ["identity_replaced", "pid_absent", "boot_changed"])
def test_a_dead_owners_exact_resources_are_reclaimed_before_the_next_evaluation(tmp_path, monkeypatch, how):
    """Dead is proof (R2): the recorded pid now names another process (another start time), the pid
    no longer exists at all (a real child, reaped, `/proc/<pid>` gone, same boot), or another boot."""
    system = build(tmp_path, monkeypatch)
    to_verifying(system)
    attempt_id = "1" * 32
    owner = {"identity_replaced": lambda: dead_owner(system), "pid_absent": lambda: reaped_owner(system),
             "boot_changed": lambda: dead_owner(system, start_ticks=None, boot_id="another-boot")}[how]()
    craft_record(system, attempt_id, owner)
    exact_containers(system, attempt_id)
    project = "zeus-verify-" + attempt_id
    system["daemon"].add_container(container_id("c"), "zeus-verify-x-postgres-1",
                                   {"com.docker.compose.project": project})
    (system["root"] / project).mkdir(parents=True)  # labelled: the stack directory it left
    (system["root"] / project / "compose.json").write_text("{}", encoding="utf-8")
    (system["root"] / project / "manifest.json").write_text("{}", encoding="utf-8")
    result = tick(system)
    assert result["stage"] == PUBLISHING, result
    assert system["daemon"].state()["containers"] == {}
    assert len(ScriptedRunner.calls) == 1  # evaluated only AFTER the reconcile
    attempts = intent_of(system)["verification"]["attempts"]
    assert attempts[0]["attempt_id"] == attempt_id and attempts[0]["cleanup"]["state"] == "confirmed"
    record = json.loads((system["root"] / "attempts" / attempt_id / "run.json").read_text("utf-8"))
    assert record["state"] == "resolved"
    calls = system["daemon"].calls()
    compose_down = [c for c in calls if c[:1] == ["compose"]]
    assert compose_down and all(c[c.index("--project-name") + 1] == project for c in compose_down)
    exact = {container_id(seed + attempt_id[:3]) for seed in ("a", "b")}  # found only by exact name + label
    assert {c[-1] for c in calls if c[:1] == ["kill"]} == exact and {c[-1] for c in calls if c[:1] == ["rm"]} == exact
    listed = " ".join(part for c in calls if c[:1] == ["ps"] for part in c)
    assert all("name=^/zeus-" + role + "-" + attempt_id + "$" in listed for role in ("release-start", "release-canary"))


def test_a_live_owner_blocks_replacement_and_the_evaluator_is_not_called(tmp_path, monkeypatch):
    system = build(tmp_path, monkeypatch, script=never)
    to_verifying(system)
    sleeper = spawn_group("sleep", "60")
    try:
        facts = system["facts"]
        owner = {"pid": sleeper.pid, "start_ticks": facts.start_ticks(sleeper.pid), "boot_id": facts.boot_id(),
                 "cgroup": "/fixture.slice/live.scope"}
        craft_record(system, "2" * 32, owner)
        exact_containers(system, "2" * 32)
        before_calls = len(system["daemon"].calls())
        result = tick(system)
        assert result["outcome"] == "pending" and result["reason_code"] == "verification_owner_alive"
        assert ScriptedRunner.calls == [] and len(system["daemon"].calls()) == before_calls
        assert len(system["daemon"].state()["containers"]) == 2  # a live owner's work is never touched
        assert queue_row(system)["attempt"] == 0 and sleeper.poll() is None
    finally:
        sleeper.kill()
        sleeper.wait()


@pytest.mark.parametrize("how", ["eacces", "garbage", "truncated"])
def test_a_live_owner_whose_identity_cannot_be_observed_is_unknown_and_never_reclaimed(tmp_path, monkeypatch, how):
    """R2, the pair of the reaped-pid case above: the owner is a LIVE process keeping its real pid,
    start time and boot, and ONLY its `/proc/<pid>/stat` observation fails. That is unknown, never a
    dead owner: `cleanup_unconfirmed` with no Docker listing/stop/rm, no compose down, no `killpg`,
    no evaluation and an untouched record. Observable again, the same record is the live owner."""
    if how == "eacces" and os.geteuid() == 0:
        pytest.skip("root reads a mode-000 file")
    view = ProcView(tmp_path / "proc")
    system = build(tmp_path, monkeypatch, script=never,
                   facts=HostFacts(proc=view.root, cgroup_root=tmp_path / "cgroup"))
    to_verifying(system)
    owner_process, child = spawn_group("sleep", "60"), spawn_group("sleep", "60")
    try:
        facts, attempt_id = system["facts"], "7" * 32
        for process in (owner_process, child):
            view.link(process.pid)
        owner = {"pid": owner_process.pid, "start_ticks": facts.start_ticks(owner_process.pid),
                 "boot_id": facts.boot_id(), "cgroup": "/fixture.slice/live.scope"}
        assert owner["start_ticks"] is not None and owner["boot_id"]
        craft_record(system, attempt_id, owner,
                     children=[{"pid": child.pid, "pgid": child.pid, "start_ticks": facts.start_ticks(child.pid)}])
        exact_containers(system, attempt_id)
        path = system["root"] / "attempts" / attempt_id / "run.json"
        record_before, calls_before = path.read_text("utf-8"), len(system["daemon"].calls())
        view.fault(owner_process.pid, how)
        signals = killpg_spy(monkeypatch)
        answer = system["verifier"].reconcile(system["delivery"]._open_attempts())
        assert answer == {"state": "cleanup_unconfirmed", "reason_code": "verification_cleanup_unconfirmed",
                          "resolved": {}}
        assert len(system["daemon"].calls()) == calls_before and signals == []  # the port itself did nothing
        result = tick(system)
        assert result["outcome"] == "pending" and result["reason_code"] == "verification_cleanup_unconfirmed"
        assert ScriptedRunner.calls == [] and queue_row(system)["attempt"] == 0
        assert len(system["daemon"].calls()) == calls_before  # no listing, stop, rm or compose down
        assert len(system["daemon"].state()["containers"]) == 2
        assert signals == [] and owner_process.poll() is None and child.poll() is None
        assert path.read_text("utf-8") == record_before
        assert intent_of(system)["verification"]["attempts"][0]["cleanup"] is None
        view.restore(owner_process.pid)
        result = tick(system)
        assert result["reason_code"] == "verification_owner_alive" and ScriptedRunner.calls == []
        assert signals == [] and len(system["daemon"].state()["containers"]) == 2
    finally:
        for process in (owner_process, child):
            process.kill()
            process.wait()


@pytest.mark.parametrize("claim", ["start_time", "boot"])
@pytest.mark.parametrize("root", ["other_namespace", "no_self"])
def test_a_proc_root_that_does_not_show_this_process_proves_no_dead_owner(tmp_path, monkeypatch, root, claim):
    """R2 repair: a proc root whose `self` names another pid (another pid namespace's mount) or is
    missing proves nothing about a pid. A LIVE owner seen there under another start time, or with
    another boot id recorded, is unknown - never a replaced identity or an ended boot: no Docker
    listing/stop/rm, no compose down, no `killpg`, no evaluation, an untouched record. This controller
    has no provable identity there either, so the tick waits before reconciling (`verifier_unavailable`);
    a root lost after that availability check leaves `verification_cleanup_unconfirmed`."""
    view = ProcView(tmp_path / "proc")
    system = build(tmp_path, monkeypatch, script=never,
                   facts=HostFacts(proc=view.root, cgroup_root=tmp_path / "cgroup"))
    to_verifying(system)
    owner_process, child = spawn_group("sleep", "60"), spawn_group("sleep", "60")
    try:
        facts, attempt_id = system["facts"], "8" * 32
        for process in (owner_process, child):
            view.link(process.pid)
        owner = {"pid": owner_process.pid, "start_ticks": facts.start_ticks(owner_process.pid),
                 "boot_id": facts.boot_id() if claim == "start_time" else "another-boot",
                 "cgroup": "/fixture.slice/live.scope"}
        assert owner["start_ticks"] is not None and facts.boot_id()
        craft_record(system, attempt_id, owner,
                     children=[{"pid": child.pid, "pgid": child.pid, "start_ticks": facts.start_ticks(child.pid)}])
        exact_containers(system, attempt_id)
        if claim == "start_time":
            view.fault(owner_process.pid, "replaced")  # that pid, a valid stat, another start time
        path = system["root"] / "attempts" / attempt_id / "run.json"
        record_before, calls_before = path.read_text("utf-8"), len(system["daemon"].calls())
        signals = killpg_spy(monkeypatch)
        view.lose_self(root)
        answer = system["verifier"].reconcile(system["delivery"]._open_attempts())
        assert answer == {"state": "cleanup_unconfirmed", "reason_code": "verification_cleanup_unconfirmed",
                          "resolved": {}}
        assert len(system["daemon"].calls()) == calls_before and signals == []  # the port itself did nothing
        result = tick(system)
        assert result["outcome"] == "unavailable" and result["reason_code"] == "verifier_unavailable"
        assert ScriptedRunner.calls == [] and len(system["daemon"].calls()) == calls_before and signals == []
        view.restore_self()
        with system["store"].transaction() as tx:  # labelled: the wait's backoff elapsed
            row = tx.get("release_queue", system["release"]["id"])
            tx.put("release_queue", row["id"], {**row, "retry_at": None})
        reconcile = system["verifier"].reconcile

        def lost_after_the_check(open_attempts):  # labelled: the root is lost after `available()`
            view.lose_self(root)
            return reconcile(open_attempts)

        monkeypatch.setattr(system["verifier"], "reconcile", lost_after_the_check)
        result = tick(system)
        assert result["outcome"] == "pending" and result["reason_code"] == "verification_cleanup_unconfirmed"
        assert ScriptedRunner.calls == [] and queue_row(system)["attempt"] == 0
        assert len(system["daemon"].calls()) == calls_before  # no listing, stop, rm or compose down
        assert len(system["daemon"].state()["containers"]) == 2
        assert signals == [] and owner_process.poll() is None and child.poll() is None
        assert path.read_text("utf-8") == record_before
        assert intent_of(system)["verification"]["attempts"][0]["cleanup"] is None
    finally:
        for process in (owner_process, child):
            process.kill()
            process.wait()


def test_foreign_resources_are_never_named_by_any_docker_command(tmp_path, monkeypatch):
    system = build(tmp_path, monkeypatch)
    to_verifying(system)
    other = "9" * 32
    system["daemon"].add_container(container_id("d"), "harness-canary-0123456789ab", {})
    system["daemon"].add_container(container_id("e"), "zeus-release-canary-" + other,
                                   {"zeus.isolated.run": other, "zeus.isolated.role": "release-canary"})
    system["daemon"].add_container(container_id("f"), "zeus-verify-other-redis-1",
                                   {"com.docker.compose.project": "zeus-verify-" + other})
    craft_record(system, "3" * 32, dead_owner(system))
    result = tick(system)
    assert result["stage"] == PUBLISHING
    touched = names_touched(system)
    for foreign in (container_id("d"), container_id("e"), container_id("f"), "harness-canary-0123456789ab",
                    "zeus-release-canary-" + other, "zeus-verify-" + other, other):
        assert not any(foreign in part for part in touched), foreign
    assert len(system["daemon"].state()["containers"]) == 3


@pytest.mark.parametrize("failure", ["ps", "ambiguous"])
def test_an_unobservable_or_ambiguous_listing_is_debt_not_absence(tmp_path, monkeypatch, failure):
    system = build(tmp_path, monkeypatch, script=never)
    to_verifying(system)
    attempt_id = "4" * 32
    craft_record(system, attempt_id, dead_owner(system))
    if failure == "ps":
        system["daemon"].update(fail=["ps"])
    else:  # two rows under one exact name+label: never guessed between
        for seed in ("a", "b"):
            system["daemon"].add_container(container_id(seed), "zeus-release-start-" + attempt_id,
                                           {"zeus.isolated.run": attempt_id})
    result = tick(system)
    assert result["outcome"] == "pending" and result["reason_code"] == "verification_cleanup_unconfirmed"
    assert ScriptedRunner.calls == [] and queue_row(system)["attempt"] == 0
    assert intent_of(system)["verification"]["attempts"][0]["cleanup"] is None


def test_host_children_are_reclaimed_only_when_provably_the_attempts_own(tmp_path, monkeypatch):
    system = build(tmp_path, monkeypatch)
    to_verifying(system)
    facts = system["facts"]
    recorded = spawn_group("sleep", "60")                    # a recorded child whose leader is alive
    orphaned = spawn_group("sh", "-c", "sleep 60 & exit 0")  # a recorded group whose leader is gone
    foreign = spawn_group("sleep", "60")                     # never recorded by any attempt
    try:
        orphaned.wait(10)
        time.sleep(0.2)
        children = [{"pid": p.pid, "pgid": p.pid, "start_ticks": facts.start_ticks(p.pid)}
                    for p in (recorded, orphaned)]
        children[1]["start_ticks"] = children[1]["start_ticks"] or 12345
        owner = dead_owner(system, cgroup="/fixture.slice/owner.scope")
        cgroup = tmp_path / "cgroup" / "fixture.slice" / "owner.scope"
        cgroup.mkdir(parents=True)
        (cgroup / "cgroup.procs").write_text(f"{foreign.pid}\n", encoding="ascii")
        craft_record(system, "5" * 32, owner, children=children)
        result = tick(system)
        assert result["reason_code"] == "verification_cleanup_unconfirmed" and ScriptedRunner.calls == []
        recorded.wait(10)
        assert gone(recorded.pid)                       # proven leader: its group was killed
        assert not gone(orphaned.pid)                   # unclassified survivor: retained as debt
        assert foreign.poll() is None                   # foreign cgroup member: untouched
        os.killpg(orphaned.pid, signal.SIGKILL)        # the owner resolves the survivor itself
        (cgroup / "cgroup.procs").write_text("", encoding="ascii")
        time.sleep(0.2)
        result = tick(system)
        assert result["stage"] == PUBLISHING and len(ScriptedRunner.calls) == 1
    finally:
        for process in (recorded, foreign):
            process.kill()
            process.wait()
        if not gone(orphaned.pid):
            os.killpg(orphaned.pid, signal.SIGKILL)


def test_a_store_attempt_without_its_disk_record_is_proven_never_started(tmp_path, monkeypatch):
    system = build(tmp_path, monkeypatch)
    to_verifying(system)
    real = system["verifier"].prepare
    monkeypatch.setattr(system["verifier"], "prepare", lambda attempt: (_ for _ in ()).throw(
        OSError("labelled: the disk record could not be written")))
    result = tick(system)
    assert result["reason_code"] == "verification_record_unavailable" and ScriptedRunner.calls == []
    (attempt,) = intent_of(system)["verification"]["attempts"]
    assert attempt["cleanup"] is None
    monkeypatch.setattr(system["verifier"], "prepare", real)
    with system["store"].transaction() as tx:
        row = tx.get("release_queue", system["release"]["id"])
        tx.put("release_queue", row["id"], {**row, "retry_at": None})
    result = tick(system)
    attempts = intent_of(system)["verification"]["attempts"]
    assert attempts[0]["cleanup"]["state"] == "never_started" and len(attempts) == 2
    assert result["stage"] == PUBLISHING and len(ScriptedRunner.calls) == 1


def test_a_verdict_with_unconfirmed_own_cleanup_never_takes_the_verified_shortcut(tmp_path, monkeypatch):
    def leaves_debt(fence, attempt):
        answer = passed(fence, attempt)
        from verification_fixtures import FakeDaemon
        FakeDaemon(Path(os.environ["DOCKER_CONFIG"])).update(fail=["ps"])  # labelled: daemon lost
        return answer

    system = build(tmp_path, monkeypatch, script=leaves_debt)
    to_verifying(system)
    result = tick(system)
    assert result["outcome"] == "pending" and result["reason_code"] == "verification_cleanup_unconfirmed"
    assert release_status(system)[0] == "verified"  # the executed evidence is recorded
    assert intent_of(system)["stage"] == VERIFYING
    again = tick(system)  # still unobservable: the verified release must NOT be published
    assert again["reason_code"] == "verification_cleanup_unconfirmed" and system["github"].publishes == 0
    system["daemon"].update(fail=[])
    result = tick(system)
    assert result["stage"] == PUBLISHING and len(ScriptedRunner.calls) == 1
    (attempt,) = intent_of(system)["verification"]["attempts"]
    assert attempt["cleanup"]["state"] == "confirmed"


def test_an_unreadable_boot_id_during_the_attempts_own_close_proves_no_process_gone(tmp_path, monkeypatch):
    """R2 direct interaction: an unreadable boot id is not another boot. The attempt's own close
    (`self_owned`) proves nothing about its recorded live child then: nothing is killed, the verdict
    stays recorded and the delivery waits; readable again, that proven child is reclaimed."""
    view = ProcView(tmp_path / "proc")
    box = {}

    def leaves_a_child(fence, attempt):
        answer = passed(fence, attempt)
        box["child"] = child = spawn_group("sleep", "60")
        box["reaper"] = threading.Thread(target=child.wait, daemon=True)  # reaps it once killed
        box["reaper"].start()
        view.link(child.pid)
        _announce(child)  # recorded by the attempt exactly as run_process records its children
        view.hide_boot()  # labelled: the boot id becomes unreadable before the attempt's own close
        return answer

    system = build(tmp_path, monkeypatch, script=leaves_a_child,
                   facts=HostFacts(proc=view.root, cgroup_root=tmp_path / "cgroup"))
    to_verifying(system)
    signals = killpg_spy(monkeypatch)
    try:
        result = tick(system)
        assert result["outcome"] == "pending" and result["reason_code"] == "verification_cleanup_unconfirmed"
        assert release_status(system)[0] == "verified" and intent_of(system)["stage"] == VERIFYING
        child = box["child"]
        assert [sig for pgid, sig in signals if pgid == child.pid] == [] and not gone(child.pid)
        (attempt,) = intent_of(system)["verification"]["attempts"]
        assert attempt["cleanup"]["state"] == "unconfirmed"
        record = json.loads((system["root"] / "attempts" / attempt["attempt_id"] / "run.json").read_text("utf-8"))
        assert record["state"] == "cleanup_unconfirmed"
        view.show_boot()
        result = tick(system)
        assert result["stage"] == PUBLISHING and len(ScriptedRunner.calls) == 1
        box["reaper"].join(10)
        assert (child.pid, signal.SIGKILL) in signals and gone(child.pid)
    finally:
        if "child" in box and not gone(box["child"].pid):
            box["child"].kill()
            box["reaper"].join(10)


def test_the_verdict_is_refused_when_the_lease_was_lost_during_the_evaluation(tmp_path, monkeypatch):
    """C-1: a stalled controller finishes after another took the lease; nothing is recorded."""
    def stolen(fence, attempt):
        answer = passed(lambda: None, attempt)
        with box["store"].transaction() as tx:
            tx.put("deployment_locks", "controller", {"owner": "other", "lease_until": "2999-01-01T00:00:00+00:00"})
        return answer

    box = {}
    system = build(tmp_path, monkeypatch, script=stolen)
    box["store"] = system["store"]
    to_verifying(system)
    before = intent_of(system)
    result = tick(system)
    assert result["outcome"] == "conflict" and result["reason_code"] == "controller_stale_after_effect"
    assert release_status(system) == ("reviewed", None)
    after = intent_of(system)
    assert after["stage"] == VERIFYING and after["verification"]["attempts"][0]["cleanup"] is None
    assert {k: v for k, v in after.items() if k != "verification" and k != "updated_at"} == \
        {k: v for k, v in before.items() if k != "verification" and k != "updated_at"}


def test_withdrawing_a_verifying_delivery_with_attempt_debt_is_refused(tmp_path, monkeypatch):
    system = build(tmp_path, monkeypatch, script=never)
    to_verifying(system)
    craft_record(system, "6" * 32, dead_owner(system))
    system["github"].main = "0" * 40  # the reviewed base really moved
    before = everything(system["store"])
    with pytest.raises(DeliveryRefused) as refused:
        system["delivery"].withdraw(system["plan"]["plan_id"], intent_of(system)["plan_sha256"],
                                    "reviewed_base_moved", EVIDENCE)
    assert refused.value.reason_code == "withdraw_verification_unresolved"
    assert everything(system["store"]) == before


# ----- boundary, fence and availability ------------------------------------------------------------
def test_the_cancellation_boundary_raises_once_and_only_while_active():
    boundary = CancellationBoundary()
    boundary.signal()  # outside an evaluation: flag only
    with pytest.raises(EvaluationCancelled):
        boundary.enter()  # a stop requested before the evaluation began: it does not begin
    boundary.leave()
    fresh = CancellationBoundary()
    fresh.enter()
    with pytest.raises(EvaluationCancelled):
        fresh.signal()
    fresh.signal()  # a second signal during cleanup: never raised again
    fresh.leave()
    fresh.signal()


def test_the_port_refuses_off_the_main_thread(tmp_path, monkeypatch):
    system = build(tmp_path, monkeypatch, script=never)
    to_verifying(system)
    box = {}
    worker = threading.Thread(target=lambda: box.update(result=system["delivery"].tick()))
    worker.start()
    worker.join(30)
    assert box["result"]["reason_code"] == "verifier_unavailable" and ScriptedRunner.calls == []


def test_owner_facts_parse_proc_stat_with_a_hostile_command_name(tmp_path):
    proc = tmp_path / "proc"
    (proc / "77").mkdir(parents=True)
    fields = ["S"] + [str(n) for n in range(4, 22)] + ["987654"] + ["0"] * 30
    (proc / "77" / "stat").write_text("77 (a) b) c (d) " + " ".join(fields), encoding="utf-8")
    (proc / "self").mkdir()  # the root shows this process as itself: its facts are observations
    (proc / "self" / "stat").write_text(fake_stat(os.getpid(), 5), encoding="utf-8")
    (proc / "sys" / "kernel" / "random").mkdir(parents=True)
    (proc / "sys" / "kernel" / "random" / "boot_id").write_text("boot-1\n", encoding="ascii")
    facts = HostFacts(proc=proc, cgroup_root=tmp_path / "cg")
    assert facts.start_ticks(77) == 987654 and facts.start_ticks(78) is None and facts.boot_id() == "boot-1"
    assert facts.members("/../etc") is None and facts.members("/absent.scope") is None  # no cgroup root
    real = HostFacts()
    assert real.start_ticks(os.getpid()) == real.owner()["start_ticks"]


def fake_stat(pid, ticks=987654) -> str:
    fields = ["S"] + [str(n) for n in range(4, 22)] + [str(ticks)] + ["0"] * 30
    return f"{pid} (a) b) c (d) " + " ".join(fields)


def test_host_facts_report_a_process_absent_only_on_proof(tmp_path):
    """R2: `absent` is ENOENT for `/proc/<pid>` under a proc root that shows THIS process as itself;
    EACCES, garbage, a truncated stat, a stat naming another pid, a pid directory without its stat, an
    invalid pid, an unreadable boot id and an unobservable proc root are all `unknown`. Under an
    unobservable root even a readable stat or boot id is unknown: a pid there names nothing recorded."""
    proc = tmp_path / "proc"
    for name, text in {"self": fake_stat(os.getpid(), 5), "77": fake_stat(77), "79": fake_stat(79),
                       "80": "garbage\n", "81": fake_stat(81)[:9], "82": fake_stat(83)}.items():
        (proc / name).mkdir(parents=True)
        (proc / name / "stat").write_text(text, encoding="utf-8")
    (proc / "79" / "stat").chmod(0)
    (proc / "84").mkdir()  # a pid directory whose stat is missing: not proof of anything
    facts = HostFacts(proc=proc, cgroup_root=tmp_path / "cg")
    assert facts.process(77) == ("present", 987654) and facts.start_ticks(77) == 987654
    assert facts.process(78) == ("absent", None) and facts.start_ticks(78) is None
    if os.geteuid() != 0:  # root reads a mode-000 file
        assert facts.process(79) == ("unknown", None) and facts.start_ticks(79) is None
    for pid in (80, 81, 82, 84, "77", True, 0, -1, None):
        assert facts.process(pid) == ("unknown", None), pid
    assert facts.boot_id() is None  # no boot id file: unreadable, never another boot
    (proc / "sys" / "kernel" / "random").mkdir(parents=True)
    (proc / "sys" / "kernel" / "random" / "boot_id").write_text("boot-1\n", encoding="ascii")
    assert facts.boot_id() == "boot-1"
    (proc / "self" / "stat").write_text(fake_stat(os.getpid() + 1, 5), encoding="utf-8")
    # A root of another pid namespace: no absence, no presence, no start time and no boot id.
    for pid in (77, 78, os.getpid()):
        assert facts.process(pid) == ("unknown", None) and facts.start_ticks(pid) is None, pid
    assert facts.boot_id() is None and facts.owner() is None
    shutil.rmtree(proc / "self")
    assert facts.process(78) == ("unknown", None) and facts.process(77) == ("unknown", None)
    assert facts.boot_id() is None and facts.owner() is None
    assert HostFacts(proc=tmp_path / "no-proc").process(78) == ("unknown", None)
    real = HostFacts()
    assert real.process(os.getpid()) == ("present", real.owner()["start_ticks"])
    reaped = subprocess.Popen(["true"])
    reaped.wait()
    assert real.process(reaped.pid) == ("absent", None)


def test_cgroup_members_are_empty_only_under_an_observable_cgroup_root(tmp_path):
    """A removed unit cgroup under an observable v2 root is `[]` (it is removed when empty); a
    missing root, a root that is not a v2 hierarchy (hybrid layout), an unreadable path or a
    directory without its member list is None - and no PermissionError escapes."""
    root = tmp_path / "cgroup"
    facts = HostFacts(cgroup_root=root)
    assert facts.members("/system.slice/unit.scope") is None  # no root at all
    root.mkdir()
    assert facts.members("/system.slice/unit.scope") is None  # a directory, but no cgroup v2 root
    (root / "cgroup.controllers").write_text("cpu memory pids\n", encoding="ascii")
    assert facts.members("/system.slice/unit.scope") == []
    unit = root / "system.slice" / "unit.scope"
    unit.mkdir(parents=True)
    assert facts.members("/system.slice/unit.scope") is None  # present, without a member list
    (unit / "cgroup.procs").write_text("12\n34\n", encoding="ascii")
    assert facts.members("/system.slice/unit.scope") == [12, 34]
    (unit / "cgroup.procs").write_text("12\nx\n", encoding="ascii")
    assert facts.members("/system.slice/unit.scope") is None
    for invalid in ("/../etc", "system.slice", None):
        assert facts.members(invalid) is None
    if os.geteuid() != 0:  # root passes every permission check
        locked = root / "locked.slice"
        locked.mkdir()
        locked.chmod(0)
        try:
            assert facts.members("/locked.slice/unit.scope") is None
        finally:
            locked.chmod(0o700)
        (root / "cgroup.controllers").chmod(0)
        assert facts.members("/system.slice/absent.scope") is None


def test_the_status_projection_shows_the_last_attempt_and_its_cleanup(tmp_path, monkeypatch):
    system = build(tmp_path, monkeypatch)
    to_verifying(system)
    tick(system)
    view = system["delivery"].status(system["plan"]["plan_id"])["deliveries"][0]
    assert view["verification"]["cleanup"] == "confirmed" and view["stage"] == PUBLISHING
    assert view["after_verification"] is None and view["recovery"] is None
    assert set(view["verification"]) == {"attempt_id", "state", "cleanup", "outcome"}


# ----- A2: the one-transaction resume ----------------------------------------------------------------
def legacy(system, *, stage=BLOCKED, queue_status="blocked", **overrides):
    """LABELLED CRAFTED RECORD of the 5aa controller's halt (published, merged, then
    `release_not_verified` at `merged`); the queue row goes through the real `ReleaseQueue`."""
    plan, github = system["plan"], system["github"]
    github.head = None
    published = github.publish(system["release"]["candidate"])
    github.merge(system["release"]["candidate"], published)
    queue = ReleaseQueue(system["store"])
    queue.enqueue(plan["release_id"], "host delivery plan " + plan["plan_id"])
    if queue_status != "queued":
        claim = queue.claim(now=system["delivery"]._now(), eligible=lambda row: row["id"] == plan["release_id"])
        queue.finish(claim, {"status": queue_status, "reason": "release_not_verified"}, system["delivery"]._now())
    canonical_plan = validate_plan(plan)
    halted = {**new_intent(canonical_plan, plan_digest(canonical_plan), system["clock"]()),
              "stage": stage, "previous_stage": MERGED, "outcome": "blocked",
              "reason_code": "release_not_verified", "attempts": 1, "head": plan["revision"],
              "merged_revision": plan["revision"], **overrides}
    with system["store"].transaction() as tx:
        tx.put(BUCKET_INTENTS, plan["plan_id"], halted)
    return halted


def resume(system, evidence=EVIDENCE, sha=None, plan_id=None):
    plan_id = plan_id or system["plan"]["plan_id"]
    sha = sha or system["delivery"].plan(system["plan"]["plan_id"])["plan_sha256"]
    return system["delivery"].resume(plan_id, sha, evidence)


def refused_without_writes(system, code, **kwargs):
    before = everything(system["store"])
    with pytest.raises(DeliveryRefused) as refused:
        resume(system, **kwargs)
    assert refused.value.reason_code == code
    assert everything(system["store"]) == before


def test_resume_moves_exactly_the_legacy_shape_and_keeps_the_original_halt(tmp_path, monkeypatch):
    system = build(tmp_path, monkeypatch)
    halted = legacy(system, stage=FAILED)
    receipt = resume(system)
    assert receipt["stage"] == VERIFYING and receipt["cached"] is False
    intent = intent_of(system)
    assert intent["previous_stage"] == FAILED and intent["after_verification"] == MERGED
    assert intent["recoveries"][0]["halted"]["stage"] == FAILED
    assert intent["merged_revision"] == halted["merged_revision"]
    row = queue_row(system)
    assert row["status"] == "queued" and len(row["manual_retries"]) == 1 and row.get("owner") is None
    assert len(row["attempts"]) == 1  # the queue's own history is never rewritten
    assert system["github"].publishes == 1 and system["github"].merges == 1


@pytest.mark.parametrize("change,code", [
    ({"reason_code": "merged_tree_mismatch"}, "resume_not_applicable"),
    ({"descriptor_sha256": "d" * 64, "descriptor": {"revision": "x"}}, "resume_not_applicable"),
    ({"rollback": {"requested": True}}, "resume_not_applicable"),
    ({"previous_stage": "merge_intended"}, "resume_not_applicable"),
])
def test_resume_refuses_every_other_shape_without_a_write(tmp_path, monkeypatch, change, code):
    system = build(tmp_path, monkeypatch)
    legacy(system, **change)
    refused_without_writes(system, code)


def test_resume_phase_one_refusals_write_nothing(tmp_path, monkeypatch):
    system = build(tmp_path, monkeypatch)
    legacy(system)
    refused_without_writes(system, "resume_evidence_invalid", evidence="sha256:short")
    refused_without_writes(system, "plan_unregistered", plan_id="no-such-plan")
    refused_without_writes(system, "resume_plan_mismatch", sha="0" * 64)
    system["github"].observe_error = RuntimeError("labelled GitHub outage")
    refused_without_writes(system, "resume_unobservable")
    system["github"].observe_error = None
    system["github"].merged_tree = "0" * 64
    refused_without_writes(system, "resume_tree_mismatch")
    system["github"].merged_tree = TREE
    system["github"].mainline = []
    refused_without_writes(system, "resume_merge_mismatch")


def test_resume_refuses_a_release_that_is_not_reviewed_or_verified(tmp_path, monkeypatch):
    system = build(tmp_path, monkeypatch)
    legacy(system)
    with system["store"].transaction() as tx:
        record = tx.get("releases", system["release"]["id"])
        tx.put("releases", record["id"], {**record, "status": "rejected"})
    refused_without_writes(system, "resume_release_rejected")


def during_qualify(system, action):
    """Run `action` between phase 1 and phase 2: inside the merge owner's qualification."""
    real = system["github"].qualify

    def qualify(candidate, revision):
        action()
        return real(candidate, revision)

    system["github"].qualify = qualify


def put(system, bucket, key, change):
    """A write by someone else between the two phases, through its own transaction."""
    with system["store"].transaction() as tx:
        tx.put(bucket, key, change(tx.get(bucket, key)))


def test_resume_phase_two_refusals_roll_back_completely(tmp_path, monkeypatch):
    for index, (action, code) in enumerate([
        (lambda s: put(s, BUCKET_INTENTS, s["plan"]["plan_id"], lambda row: {**row, "updated_at": "changed"}),
         "resume_intent_changed"),
        (lambda s: put(s, "deployment_locks", "controller",
                       lambda row: {"owner": "other", "lease_until": "2999-01-01T00:00:00+00:00"}),
         "resume_controller_running"),
        (lambda s: put(s, "release_queue", s["release"]["id"], lambda row: {**row, "reason": "changed"}),
         "resume_queue_changed"),
        (lambda s: put(s, "host_delivery_plans", s["plan"]["plan_id"], lambda row: {**row, "updated_at": "x"}),
         "resume_intent_changed"),
    ]):
        system = build(tmp_path / str(index), monkeypatch)
        legacy(system)
        during_qualify(system, lambda s=system, a=action: a(s))
        with pytest.raises(DeliveryRefused) as refused:
            resume(system)
        assert refused.value.reason_code == code
        assert intent_of(system)["stage"] == BLOCKED
        assert len(queue_row(system).get("manual_retries") or []) == 0


def test_a_predecessor_that_merged_meanwhile_is_recomputed_inside_the_transaction(tmp_path, monkeypatch):
    system = build(tmp_path, monkeypatch)
    legacy(system)

    def other_merged():
        with system["store"].transaction() as tx:
            tx.put(BUCKET_INTENTS, "other-plan", {"id": "other-plan", "plan_id": "other-plan",
                                                  "target_id": system["plan"]["target_id"], "stage": MERGED})

    during_qualify(system, other_merged)
    with pytest.raises(DeliveryRefused) as refused:
        resume(system)
    assert refused.value.reason_code == "resume_predecessor_in_flight"
    assert intent_of(system)["stage"] == BLOCKED and not queue_row(system).get("manual_retries")


def test_an_error_after_the_in_transaction_retry_rolls_the_retry_back(tmp_path, monkeypatch):
    system = build(tmp_path, monkeypatch)
    legacy(system)
    queue = system["delivery"].queue
    real = queue.retry

    def retry_then_crash(release_id, reason, *, transaction=None):
        real(release_id, reason, transaction=transaction)
        raise RuntimeError("labelled crash after the in-transaction retry")

    monkeypatch.setattr(queue, "retry", retry_then_crash)
    refused_without_writes(system, "resume_unobservable")


def test_a_crash_after_commit_replays_as_cached_and_the_tick_proceeds(tmp_path, monkeypatch):
    system = build(tmp_path, monkeypatch)
    legacy(system)
    real = system["delivery"]._resumed

    def crash(plan, intent, *, cached, evidence_ref=None):
        if not cached:
            raise RuntimeError("labelled crash before the receipt")
        return real(plan, intent, cached=cached, evidence_ref=evidence_ref)

    monkeypatch.setattr(system["delivery"], "_resumed", crash)
    with pytest.raises(RuntimeError):
        resume(system)
    before = everything(system["store"])
    assert resume(system)["cached"] is True and everything(system["store"]) == before
    result = tick(system)
    assert result["stage"] == MERGED and len(ScriptedRunner.calls) == 1


def test_a_queued_row_is_not_retried_again(tmp_path, monkeypatch):
    system = build(tmp_path, monkeypatch)
    legacy(system, queue_status="queued")
    calls = []
    monkeypatch.setattr(system["delivery"].queue, "retry", lambda *a, **k: calls.append(a))
    assert resume(system)["stage"] == VERIFYING and calls == []
    assert not queue_row(system).get("manual_retries")


def test_resume_while_another_controller_holds_the_lease_writes_nothing(tmp_path, monkeypatch):
    system = build(tmp_path, monkeypatch)
    legacy(system)
    with system["store"].transaction() as tx:
        tx.put("deployment_locks", "controller", {"owner": "other", "release_id": "x",
                                                  "lease_until": "2999-01-01T00:00:00+00:00"})
    refused_without_writes(system, "resume_controller_running")


@pytest.mark.parametrize("evidence,expected", [(EVIDENCE, {"cached"}), (OTHER_EVIDENCE, {"resume_conflict"})])
def test_concurrent_resumes_apply_once(tmp_path, monkeypatch, evidence, expected):
    system = build(tmp_path, monkeypatch, store=MemoryStore())
    legacy(system)
    barrier = threading.Barrier(2)
    during_qualify(system, lambda: barrier.wait(10))
    answers = []

    def call(value):
        try:
            answers.append("cached" if resume(system, evidence=value)["cached"] else "applied")
        except DeliveryRefused as exc:
            answers.append(exc.reason_code)

    threads = [threading.Thread(target=call, args=(value,)) for value in (EVIDENCE, evidence)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)
    assert sorted(answers) == sorted(["applied", *expected])
    assert len(queue_row(system)["manual_retries"]) == 1
    assert len(intent_of(system)["recoveries"]) == 1


def test_a_second_recovery_of_the_same_kind_is_exhausted(tmp_path, monkeypatch):
    system = build(tmp_path, monkeypatch)
    legacy(system)
    resume(system)
    with system["store"].transaction() as tx:  # labelled: halted again in the same legacy shape
        intent = tx.get(BUCKET_INTENTS, system["plan"]["plan_id"])
        tx.put(BUCKET_INTENTS, intent["id"], {**intent, "stage": BLOCKED, "previous_stage": MERGED,
                                              "reason_code": "release_not_verified"})
    refused_without_writes(system, "resume_exhausted", evidence=OTHER_EVIDENCE)
    assert resume(system)["cached"] is True


def test_a_resumed_plan_that_is_rejected_stays_merged_and_blocked(tmp_path, monkeypatch):
    """F-4: no revert and no host effect; the owner reviews."""
    system = build(tmp_path, monkeypatch, script=lambda fence, attempt: {
        "verdict": "checked", "passed": False, "image": None, "receipt": {},
        "checks": {"tests": {"passed": False, "evidence": "sha256:" + "3" * 64}}})
    legacy(system)
    resume(system)
    result = tick(system)
    assert result["outcome"] == "blocked" and result["reason_code"] == "release_rejected"
    assert result["next_action"] == "owner_review"
    intent = intent_of(system)
    assert intent["merged_revision"] == system["plan"]["revision"] and intent["descriptor"] is None
    assert system["github"].merges == 1 and system["github"].publishes == 1


def test_a_verifying_resumed_plan_holds_its_target_for_other_plans(tmp_path, monkeypatch):
    """C-2: another plan on the same target sees the merged `verifying` delivery as in flight."""
    system = build(tmp_path, monkeypatch)
    legacy(system)
    resume(system)
    other = {**system["plan"], "plan_id": "other-plan"}
    assert system["delivery"]._predecessor(other) == "in_flight"


def test_resumable_is_pure_and_exact():
    base = {"stage": BLOCKED, "reason_code": "release_not_verified", "previous_stage": MERGED,
            "merged_revision": MERGED_REVISION, "descriptor": None, "descriptor_sha256": None,
            "instance_id": None, "candidate_instance_id": None, "rollback": None}
    assert resumable(base) and resumable({**base, "stage": FAILED})
    assert not resumable({**base, "recoveries": [{"kind": "release_verification_missing"}]})
    assert not resumable({**base, "merged_revision": None}) and not resumable(None)
    assert BASE != MERGED_REVISION


def test_the_attempt_names_are_exactly_the_owned_container_names():
    resources = attempt_resources("a" * 32)
    assert resources["project"] == "zeus-verify-" + "a" * 32
    assert resources["containers"] == {"release-start": "zeus-release-start-" + "a" * 32,
                                       "release-canary": "zeus-release-canary-" + "a" * 32}
    with pytest.raises(ContractError):
        attempt_resources("harness-canary")
    assert sys.platform  # the module imports on every platform; the port itself refuses off POSIX


def test_uv_is_taken_from_path_or_the_service_users_install(tmp_path, monkeypatch):
    """The aibox controller unit's PATH has no uv (observed: only ~/.local/bin/uv exists); the legacy argv is
    unchanged whenever PATH has one, and an absent uv stays `uv` (an observation error, never a pass)."""
    from codex_harness.adapters import deployment

    monkeypatch.setattr(deployment.shutil, "which", lambda name: "/usr/bin/uv")
    assert deployment.uv_command() == "uv"
    monkeypatch.setattr(deployment.shutil, "which", lambda name: None)
    monkeypatch.setattr(deployment.Path, "home", classmethod(lambda cls: tmp_path))
    assert deployment.uv_command() == "uv"
    local = tmp_path / ".local" / "bin" / "uv"
    local.parent.mkdir(parents=True)
    local.write_text("#!/bin/sh\n", encoding="utf-8")
    local.chmod(0o755)
    assert deployment.uv_command() == str(local)
