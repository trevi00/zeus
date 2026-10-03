"""Shared S8 scenario steps (`review.release_verifier`): M7 `adapters/release_verifier.py` (`ReleaseVerifier`, `CancellationBoundary`, `bounded_fence`, the fence
and cancellation errors), characterized BEFORE the module moves into `composition.release_verifier` (S8 batch B7b, DESIGN-s8 section 32 V34b).

Mirrors the verifier parts of M7 `tests/test_release_verifier.py` and `tests/test_host_interruption.py`: `test_the_cancellation_boundary_raises_once_and_only_
while_active`, `test_the_port_refuses_off_the_main_thread`, `test_owner_facts_parse_proc_stat_with_a_hostile_command_name`, `test_host_facts_report_a_process_
absent_only_on_proof`, `test_cgroup_members_are_empty_only_under_an_observable_cgroup_root`, `test_a_dead_owners_exact_resources_are_reclaimed_before_the_next_
evaluation`, `test_a_live_owner_blocks_replacement_and_the_evaluator_is_not_called`, `test_a_live_owner_whose_identity_cannot_be_observed_is_unknown_and_never_
reclaimed`, `test_a_proc_root_that_does_not_show_this_process_proves_no_dead_owner`, `test_foreign_resources_are_never_named_by_any_docker_command`, `test_an_
unobservable_or_ambiguous_listing_is_debt_not_absence`, `test_host_children_are_reclaimed_only_when_provably_the_attempts_own`, `test_a_store_attempt_without_its_
disk_record_is_proven_never_started`, `test_a_verdict_with_unconfirmed_own_cleanup_never_takes_the_verified_shortcut` (the verifier's part), `test_an_unreadable_boot_
id_during_the_attempts_own_close_proves_no_process_gone`, `test_the_verdict_is_refused_when_the_lease_was_lost_during_the_evaluation` (the fence), `test_identity_
divergence_refuses_and_a_superseded_ticket_is_recorded` (the verifier's classification), `test_an_observation_error_is_a_named_retry_that_keeps_the_stage` (the
verifier's retry outcome), `test_the_attempt_names_are_exactly_the_owned_container_names`, and the interruption cases of `test_host_interruption.py` that reach the
verifier (a stop before the evaluation, a stop during it).
Not mirrored: the `HostDelivery`/`ReleaseQueue`/store/resume tests of `test_release_verifier.py` (the delivery state machine, in `delivery.application`), the
real-child and real-`/proc` variants (`spawn_group`, `ProcView` over the kernel's own pids: replaced here by a scripted facts object and a written proc tree, so no
pid or start time of this host reaches a result), `test_the_real_evaluator_checks_auth_presence_and_workspaces_before_any_work`, `test_uv_is_taken_from_path_or_the_
service_users_install` (`deployment`'s) and `test_the_status_projection_shows_the_last_attempt_and_its_cleanup` (the store projection).

Layer: harness (never shipped)

This module never imports `codex_harness`: everything arrives through `api` (the verifier objects, `HostFacts`, `observe_spawns`, `announce`, `attempt_resources`,
`install_runner`, `module`). The scripted `docker` is ONE function that answers both the owned-container verbs and the compose verbs (`api.install_runner` puts it
where each side resolves its process runner); `os.getpid` is fixed and `os.killpg` is scripted for the whole run, so no host pid, boot id or start time is read.
The wall clock for `utcnow` is the harness's. Temporary paths are replaced by `<ROOT>`; the digest of a record file (it covers its own path) is replaced by `<SHA256>`;
fence waits are real (shortened) time.
"""

from __future__ import annotations

import contextlib
import json
import os
import threading
import uuid
from pathlib import Path
from types import SimpleNamespace

from s1_common import relative


def outcome(action) -> dict:
    """`{"ok": value}` or the refusal; unlike the S1 helper it also records a KeyboardInterrupt (`EvaluationCancelled` is one)."""
    try:
        return {"ok": action()}
    except BaseException as exc:  # noqa: BLE001 - the refusal type and reason are the result
        row = {"error": type(exc).__name__, "message": str(exc)[:400]}
        for attr in ("reason_code", "cause", "code"):
            if hasattr(exc, attr) and isinstance(getattr(exc, attr), (str, int, type(None))):
                row[attr] = getattr(exc, attr)
        return row

PID = 4242
TICKS = 77
BOOT = "boot-A"
CGROUP = "/zeus.slice/owner.scope"
IDS = ["a" * 32, "b" * 32, "c" * 32, "d" * 32, "e" * 32, "f" * 32, "1" * 32, "2" * 32, "3" * 32, "4" * 32, "5" * 32, "6" * 32]
IMAGE = "sha256:" + "e" * 64
PASSED = {"verdict": "checked", "passed": True, "image": IMAGE, "receipt": {"attempt_id": "x"},
          "checks": {"tests": {"passed": True, "evidence": "sha256:" + "1" * 64}, "canary": {"passed": True, "skipped": True}}}


def cid(seed: str) -> str:
    return (seed * 64)[:64]


def exact(attempt_id, role, seed):
    return {"id": cid(seed), "name": "zeus-" + role + "-" + attempt_id, "labels": {"zeus.isolated.run": attempt_id, "zeus.isolated.role": role},
            "status": "running"}


# ---- stand-ins -------------------------------------------------------------------------------------------------------------------------------------
class Artifacts:
    def __init__(self, fail=False):
        self.rows, self.fail = [], fail

    def put(self, body, source, lock_timeout=30):
        if self.fail:
            raise OSError("artifact store down")
        self.rows.append({"source": source, "body": json.loads(body)})
        return {"ref": {"id": len(self.rows)}}


class Facts:
    """Scripted process facts: `procs` maps a pid to `(state, ticks)`; `me` is this process's identity (None = not observable)."""

    def __init__(self, boot=BOOT, procs=None, members=None, me=True):
        self.boot, self.procs, self._members = boot, {7001: ("present", 11), 7002: ("present", 12), **(procs or {})}, dict(members or {})
        self.me = {"pid": PID, "start_ticks": TICKS, "boot_id": boot, "cgroup": CGROUP} if me else None

    def boot_id(self):
        return self.boot

    def process(self, pid):
        if pid == PID:
            return "present", TICKS
        return self.procs.get(pid, ("unknown", None))

    def start_ticks(self, pid):
        return self.process(pid)[1]

    def owner(self):
        return self.me

    def cgroup(self, pid="self"):
        return CGROUP

    def members(self, cgroup):
        return self._members.get(cgroup, [PID])


class Docker:
    """The scripted `docker`: containers by id; `ps` answers by the exact name/label filters; `fail` maps a verb to a return code."""

    def __init__(self, containers=(), fail=None, extra_ids=None, compose_fail=False):
        self.containers = {c["id"]: dict(c) for c in containers}
        self.fail, self.extra_ids, self.compose_fail = fail or {}, extra_ids or {}, compose_fail
        self.calls = []

    def __call__(self, argv, cwd=None, timeout=120, input_text=None, env=None):
        if argv[1] == "compose":
            args = argv[6:]
            self.calls.append({"compose": argv[3], "args": list(args), "cwd": cwd, "timeout": timeout})
            return SimpleNamespace(returncode=1 if self.compose_fail else 0, stdout="", stderr="")
        args = list(argv[1:])
        self.calls.append({"docker": argv[0], "args": args, "timeout": timeout, "env_given": env is not None})
        verb = args[0]
        code = self.fail.get(verb, 0)
        if verb == "ps":
            filters = [a for a in args if a.startswith(("name=", "label="))]
            rows = [c for c in self.containers.values() if all(self._match(c, f) for f in filters)]
            ids = [c["id"] for c in rows] + list(self.extra_ids.get(tuple(filters), []))
            return SimpleNamespace(returncode=code, stdout="".join(i + "\n" for i in ids) if not code else "", stderr="")
        target = self.containers.get(args[-1])
        if verb == "inspect":
            status = target["status"] if target else "unknown"
            return SimpleNamespace(returncode=code or (0 if target else 1), stdout=status + " 137 false\n", stderr="")
        if verb == "kill" and target and not code:
            target["status"] = "exited"
        if verb == "rm" and target and not code:
            del self.containers[args[-1]]
        return SimpleNamespace(returncode=code, stdout="", stderr="")

    @staticmethod
    def _match(container, flt):
        if flt.startswith("name="):
            return "/" + container["name"] == flt[len("name=^"):-1]
        key, _, value = flt[len("label="):].partition("=")
        return container["labels"].get(key) == value

    def view(self):
        """Timings are not facts: a bound is shown as whole seconds (the remainder of the cleanup window shrinks by microseconds)."""
        return [{**c, "timeout": round(c["timeout"])} for c in self.calls]


class Ctx:
    def __init__(self, api, root: Path):
        self.api, self.root = api, root
        self.runner = [None]
        self.killpg = {}
        self.signals = []
        self.group_gone = [True]
        self.counter = iter(range(1_000_000))

    def dir(self, name):
        path = self.root / name
        path.mkdir(parents=True)
        return path

    def fresh_uuid(self):
        return uuid.UUID(int=0x1000 + next(self.counter))

    def scripted_killpg(self, pgid, sig):
        self.signals.append([pgid, sig])
        action = self.killpg.get((pgid, sig), self.killpg.get((pgid, "any")))
        if isinstance(action, BaseException):
            raise action
        if callable(action):
            action()

    def verifier(self, name, script=None, *, docker=None, facts=None, fence_seconds=5.0, artifacts=None, boundary=None, **extra):
        directory = self.dir(name)
        self.art = artifacts or Artifacts()
        self.docker = docker or Docker()
        self.runner[0] = self.docker
        script = script or (lambda fence, attempt, verifier: PASSED)
        box = SimpleNamespace(verifier=None)
        verifier = self.api.ReleaseVerifier(lambda fence: Evaluator(script, fence, box), root=directory / "verification", artifacts=lambda: self.art,
                                            facts=facts or Facts(), fence_seconds=fence_seconds, boundary=boundary, **extra)
        box.verifier = verifier
        return verifier

    def plant(self, verifier, attempt_id, owner, *, children=(), state="started", lifecycle=None):
        path = verifier.root / "attempts" / attempt_id / "run.json"
        path.parent.mkdir(parents=True)
        record = {"attempt_id": attempt_id, "plan_id": "plan-1", "release_id": "release-1", "generation": 1, "owner": owner,
                  "started_at": "2026-09-22T00:00:00+00:00", "resources": self.api.attempt_resources(attempt_id), "children": list(children),
                  "lifecycle": lifecycle or [{"state": "prepared"}, {"state": state}], "state": state, "cleanup": None, "record": str(path)}
        path.write_text(json.dumps(record), encoding="utf-8")
        return record

    def owner(self, **overrides):
        return {"pid": PID, "start_ticks": 1, "boot_id": BOOT, "cgroup": "/zeus.slice/dead-owner.scope", **overrides}

    def show(self, value):
        return mask(relative(value, {"ROOT": str(self.root)}))


class Evaluator:
    """LABELLED DOUBLE of `ReleaseRunner.evaluate`: `script(fence, attempt, verifier)` decides the answer."""

    def __init__(self, script, fence, box):
        self.script, self.fence, self.box = script, fence, box

    def evaluate(self, release_id, *, attempt=None):
        return self.script(self.fence, attempt, self.box.verifier)


def mask(value):
    """The digest of a record file covers its own path, so only its presence is a fact."""
    if isinstance(value, dict):
        return {k: ("<SHA256>" if k == "record_sha256" and isinstance(v, str) else mask(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [mask(v) for v in value]
    return value


def thread_value(action):
    box = {}

    def target():
        box["value"] = outcome(action)

    worker = threading.Thread(target=target)
    worker.start()
    worker.join(10)
    return box.get("value")


def record_of(verifier, attempt_id):
    path = verifier.root / "attempts" / attempt_id / "run.json"
    return json.loads(path.read_text("utf-8")) if path.exists() else None


def digest_free(record):
    return record


# ---- cases -------------------------------------------------------------------------------------------------------------------------------------------
def case_surface(ctx):
    api, mod = ctx.api, ctx.api.module
    art = Artifacts()
    made = []
    verifier = api.ReleaseVerifier(lambda fence: None, root=ctx.root / "surface", artifacts=lambda: made.append(1) or art)
    before = len(made)
    first, second = verifier.artifacts, verifier.artifacts
    return {"constants": {"FENCE_SECONDS": mod.FENCE_SECONDS, "ATTEMPTS_DIR": mod.ATTEMPTS_DIR, "RECORD_FILE": mod.RECORD_FILE, "COMPOSE_LABEL": mod.COMPOSE_LABEL,
                          "states": [mod.PRESENT, mod.ABSENT, mod.UNKNOWN], "RETRY_OBSERVATION": api.RETRY_OBSERVATION,
                          "ATTEMPT_ID": api.ATTEMPT_ID.pattern},
            "all": sorted(mod.__all__),
            "errors": {"EvaluationCancelled": [c.__name__ for c in api.EvaluationCancelled.__mro__],
                       "FenceLost": [c.__name__ for c in api.FenceLost.__mro__], "FenceUnobservable": [c.__name__ for c in api.FenceUnobservable.__mro__]},
            "defaults": {"docker": verifier.docker, "fence_seconds": verifier.fence_seconds, "facts": type(verifier.facts).__name__,
                         "boundary": type(verifier.boundary).__name__, "root": str(verifier.root.relative_to(ctx.root)),
                         "artifact_calls_before": before, "artifact_calls_after_two_reads": len(made), "same_store": first is second is art},
            "signature": str(api.signature(api.ReleaseVerifier.__init__))}


def case_boundary(ctx):
    api = ctx.api
    out = {}
    boundary = api.CancellationBoundary()
    out["initial"] = [boundary.active, boundary.raised, boundary.requested]
    out["signal_inactive"] = outcome(boundary.signal)
    out["after_inactive_signal"] = [boundary.active, boundary.raised, boundary.requested]
    out["enter_after_request"] = outcome(boundary.enter)
    out["after_enter_refusal"] = [boundary.active, boundary.raised, boundary.requested]
    boundary.reset()
    out["reset"] = [boundary.active, boundary.raised, boundary.requested]
    boundary.enter()
    out["entered"] = [boundary.active, boundary.raised, boundary.requested]
    out["signal_active_first"] = outcome(boundary.signal)
    out["signal_active_second"] = outcome(boundary.signal)
    out["flags_after"] = [boundary.active, boundary.raised, boundary.requested]
    boundary.leave()
    out["left"] = [boundary.active, boundary.raised, boundary.requested]
    other = api.CancellationBoundary()
    other.enter()
    out["signal_off_main_thread"] = thread_value(other.signal)
    out["off_main_flags"] = [other.active, other.raised, other.requested]
    other.leave()
    again = api.CancellationBoundary()
    again.enter()
    out["signal_then_leave"] = outcome(again.signal)
    again.leave()
    out["reenter_after_a_request"] = outcome(again.enter)
    out["reenter_clears_raised"] = [again.active, again.raised, again.requested]
    return out


def case_fence(ctx):
    api = ctx.api
    out = {}

    def run(name, heartbeat, seconds=5.0):
        out[name] = outcome(lambda: api.bounded_fence(heartbeat, seconds)())

    run("ok", lambda: None)
    run("contract_error_is_lost", lambda: (_ for _ in ()).throw(api.ContractError("lease gone")))
    run("subclass_of_contract_error_is_lost", lambda: (_ for _ in ()).throw(api.TicketSuperseded("changed")))
    run("runtime_error_is_unobservable", lambda: (_ for _ in ()).throw(RuntimeError("store down")))
    run("keyboard_interrupt_is_unobservable", lambda: (_ for _ in ()).throw(KeyboardInterrupt()))
    run("os_error_is_unobservable", lambda: (_ for _ in ()).throw(OSError("io")))
    release = threading.Event()
    run("hang_is_unobservable_within_bound", lambda: release.wait(30), 0.05)
    release.set()
    done = threading.Event()
    out["late_success_after_bound_is_refused"] = outcome(lambda: api.bounded_fence(lambda: done.wait(30), 0.05)())
    done.set()
    fence = api.bounded_fence(lambda: None, 1.0)
    out["fence_is_reusable"] = [outcome(fence), outcome(fence)]
    out["cause_chain"] = outcome(lambda: _cause(api))
    out["default_seconds"] = api.bounded_fence.__defaults__
    return out


def _cause(api):
    try:
        api.bounded_fence(lambda: (_ for _ in ()).throw(api.ContractError("lease gone")))()
    except api.FenceLost as exc:
        return {"cause": type(exc.__cause__).__name__, "text": str(exc)}


def stat_line(pid, ticks, comm="zeus"):
    fields = ["S"] + ["0"] * 18 + [str(ticks)] + ["0"] * 3
    return f"{pid} ({comm}) " + " ".join(fields) + "\n"


def case_proc_facts(ctx):
    api = ctx.api
    root = ctx.dir("proc_tree")
    proc, cg = root / "proc", root / "cgroup"
    (proc / "sys" / "kernel" / "random").mkdir(parents=True)
    (proc / "sys" / "kernel" / "random" / "boot_id").write_text("boot-A\n", encoding="ascii")

    def entry(name, text):
        (proc / name).mkdir(exist_ok=True)
        (proc / name / "stat").write_text(text, encoding="utf-8")

    entry("self", stat_line(PID, TICKS))
    entry(str(PID), stat_line(PID, TICKS))
    entry("5000", stat_line(5000, 900, comm="a) S 1 (b"))
    entry("5001", "not a stat line\n")
    entry("5002", stat_line(5002, 1)[:stat_line(5002, 1).rindex(")") + 3])
    entry("5003", stat_line(9999, 12))
    entry("5004", stat_line(5004, "x1"))
    (proc / "5005").mkdir()
    (proc / "5006").mkdir()
    (proc / "5006" / "stat").mkdir()
    (proc / "5000" / "cgroup").write_text("12:cpu:/x\n0::/zeus.slice/a.scope\n", encoding="utf-8")
    (proc / "5001" / "cgroup").write_text("0::/a\n0::/b\n", encoding="utf-8")
    (proc / "5002" / "cgroup").write_text("0::relative\n", encoding="utf-8")
    (proc / "5003" / "cgroup").write_text("1:cpu:/x\n", encoding="utf-8")
    facts = api.HostFacts(proc=proc, cgroup_root=cg)
    out = {"boot_id": facts.boot_id(), "observable": facts._observable()}
    out["process"] = {name: facts.process(pid) for name, pid in
                      (("self", PID), ("hostile_name", 5000), ("garbage", 5001), ("truncated", 5002), ("other_pid", 5003), ("bad_ticks", 5004),
                       ("dir_without_stat", 5005), ("stat_is_a_directory", 5006), ("absent", 6000), ("zero", 0), ("negative", -3), ("true", True),
                       ("text", "5000"), ("float", 5000.0))}
    out["start_ticks"] = [facts.start_ticks(PID), facts.start_ticks(5000), facts.start_ticks(6000)]
    out["cgroup"] = {"self_missing": facts.cgroup(), "hostile": facts.cgroup(5000), "two_paths": facts.cgroup(5001), "relative": facts.cgroup(5002),
                     "no_unified": facts.cgroup(5003), "absent": facts.cgroup(6000)}
    out["owner"] = facts.owner()
    out["members_without_controllers"] = facts.members("/zeus.slice/a.scope")
    cg.mkdir()
    (cg / "cgroup.controllers").write_text("cpu memory pids\n", encoding="ascii")
    (cg / "zeus.slice" / "a.scope").mkdir(parents=True)
    (cg / "zeus.slice" / "a.scope" / "cgroup.procs").write_text("11\n12\n", encoding="ascii")
    (cg / "zeus.slice" / "empty.scope").mkdir()
    (cg / "zeus.slice" / "bad.scope").mkdir()
    (cg / "zeus.slice" / "bad.scope" / "cgroup.procs").write_text("x\n", encoding="ascii")
    out["members"] = {"listed": facts.members("/zeus.slice/a.scope"), "gone": facts.members("/zeus.slice/removed.scope"),
                      "no_member_list": facts.members("/zeus.slice/empty.scope"), "unparseable": facts.members("/zeus.slice/bad.scope"),
                      "relative": facts.members("zeus.slice/a.scope"), "dotdot": facts.members("/zeus.slice/../x"), "none": facts.members(None),
                      "number": facts.members(7)}
    (proc / "sys" / "kernel" / "random" / "boot_id").write_text("", encoding="ascii")
    out["empty_boot_id"] = facts.boot_id()
    (proc / "sys" / "kernel" / "random" / "boot_id").write_text("boot-A\n", encoding="ascii")
    (proc / "self" / "stat").unlink()
    entry("self", stat_line(PID + 1, TICKS))
    out["foreign_root"] = {"boot_id": facts.boot_id(), "observable": facts._observable(), "process_present": facts.process(5000),
                           "process_absent": facts.process(6000), "owner": facts.owner()}
    (proc / "self" / "stat").unlink()
    (proc / "self").rmdir()
    out["no_self"] = {"boot_id": facts.boot_id(), "process_present": facts.process(5000), "owner": facts.owner()}
    missing = api.HostFacts(proc=root / "nowhere", cgroup_root=root / "nowhere")
    out["missing_roots"] = {"boot_id": missing.boot_id(), "observable": missing._observable(), "process": missing.process(5000), "cgroup": missing.cgroup(),
                            "members": missing.members("/a"), "owner": missing.owner()}
    out["defaults"] = [str(api.HostFacts().proc), str(api.HostFacts().cgroup_root)]
    return ctx.show(out)


def case_available_and_attempts(ctx):
    ctx.runner[0] = Docker()
    out = {}
    v = ctx.verifier("available")
    out["available"] = v.available()
    out["available_off_main_thread"] = thread_value(v.available)
    out["available_without_owner"] = ctx.verifier("available_no_owner", facts=Facts(me=False)).available()
    attempt = v.new_attempt(plan_id="plan-1", release_id="release-1", generation=3)
    out["new_attempt"] = attempt
    out["new_attempt_no_owner"] = outcome(lambda: ctx.verifier("new_no_owner", facts=Facts(me=False)).new_attempt(plan_id="p", release_id="r", generation=1))
    record = v.prepare(attempt)
    out["prepare"] = record
    out["prepare_twice"] = outcome(lambda: v.prepare(attempt))
    out["load"] = v._load(attempt["attempt_id"]) == record
    out["path"] = str(v._path("x" * 32).relative_to(v.root))
    out["prepare_bad_id"] = outcome(lambda: v.prepare({**attempt, "attempt_id": "../escape"}))
    out["files"] = sorted(str(p.relative_to(v.root)) for p in v.root.rglob("*"))
    return ctx.show(out)


def run_attempt(ctx, name, script, *, heartbeat=lambda: None, docker=None, facts=None, fence_seconds=5.0, artifacts=None, before=None, spawns=True):
    v = ctx.verifier(name, script, docker=docker if isinstance(docker, Docker) else None, facts=facts, fence_seconds=fence_seconds, artifacts=artifacts)
    attempt = v.new_attempt(plan_id="plan-1", release_id="release-1", generation=1)
    if docker is not None and not isinstance(docker, Docker):
        ctx.docker = ctx.runner[0] = docker(attempt["attempt_id"])
    v.prepare(attempt)
    if before:
        before(v)
    result = outcome(lambda: v.evaluate("release-1", attempt, fence=heartbeat))
    record = record_of(v, attempt["attempt_id"])
    return {"result": result, "record": record, "docker": ctx.docker.view(), "artifacts": ctx.art.rows,
            "attempt_dirs": sorted(p.name for p in (v.root / "attempts").iterdir())}


def announce_children(ctx, *pids):
    for pid in pids:
        ctx.api.announce(SimpleNamespace(pid=pid))


def case_evaluate(ctx):
    api = ctx.api
    out = {}

    def passed(fence, attempt, verifier):
        fence()
        announce_children(ctx, 7001, 7002)
        return PASSED

    def stale_child(fence, attempt, verifier):
        announce_children(ctx, 7001)
        return PASSED

    def raising(exc):
        def script(fence, attempt, verifier):
            raise exc
        return script

    def signalled(fence, attempt, verifier):
        verifier.boundary.signal()
        raise AssertionError("unreachable: the signal raises in the main thread")

    def retry_result(code):
        return lambda fence, attempt, verifier: {"verdict": "retry", "reason_code": code, "evidence": "sha256:" + "2" * 64}

    def lost_lease(fence, attempt, verifier):
        fence()
        raise AssertionError("the fence must refuse")

    def refuse(_):
        raise api.ContractError("lease lost")

    def hang_heartbeat(release):
        return lambda: release.wait(30)

    out["passed"] = run_attempt(ctx, "ev_passed", passed)
    out["passed_failing_check"] = run_attempt(ctx, "ev_failed_check", lambda f, a, v: {**PASSED, "passed": False})
    out["retry_with_code"] = run_attempt(ctx, "ev_retry_code", retry_result("custom_retry"))
    out["retry_without_code"] = run_attempt(ctx, "ev_retry_none", retry_result(None))
    out["fence_lost"] = run_attempt(ctx, "ev_lost", lost_lease, heartbeat=lambda: refuse(0))
    out["fence_unobservable_error"] = run_attempt(ctx, "ev_unobservable", lost_lease, heartbeat=lambda: (_ for _ in ()).throw(RuntimeError("down")))
    release = threading.Event()
    out["fence_unobservable_hang"] = run_attempt(ctx, "ev_hang", lost_lease, heartbeat=hang_heartbeat(release), fence_seconds=0.05)
    release.set()
    out["superseded"] = run_attempt(ctx, "ev_superseded", raising(api.TicketSuperseded("the request changed " + "x" * 300)))
    out["refused"] = run_attempt(ctx, "ev_refused", raising(api.ContractError("identity diverged")))
    reason = api.ContractError("identity diverged")
    reason.reason_code = "identity_divergence"
    out["refused_with_reason_code"] = run_attempt(ctx, "ev_refused_code", raising(reason))
    out["unexpected_error"] = run_attempt(ctx, "ev_unexpected", raising(RuntimeError("boom")))
    out["unexpected_os_error"] = run_attempt(ctx, "ev_oserror", raising(OSError("disk")))
    out["cancelled_by_signal"] = run_attempt(ctx, "ev_signalled", signalled)
    out["child_interrupt"] = run_attempt(ctx, "ev_interrupt", raising(KeyboardInterrupt()))
    out["spawned_then_unreclaimed_child"] = run_attempt(ctx, "ev_children", stale_child, facts=Facts(procs={7001: ("present", 5)}))

    def requested(v):
        v.boundary.requested = True

    out["stop_requested_before"] = run_attempt(ctx, "ev_before", lambda f, a, v: (_ for _ in ()).throw(AssertionError("must not run")), before=requested)
    out["docker_listing_error"] = run_attempt(ctx, "ev_docker_error", passed, docker=Docker(fail={"ps": 1}))
    out["own_leftover_container_is_reclaimed"] = run_attempt(
        ctx, "ev_leftover", passed, docker=lambda aid: Docker([exact(aid, "release-start", "a"), exact(aid, "release-canary", "b")]))
    out["own_leftover_that_cannot_be_removed"] = run_attempt(
        ctx, "ev_leftover_rm", passed, docker=lambda aid: Docker([exact(aid, "release-start", "a")], fail={"rm": 1}))
    out["receipts_fail"] = run_attempt(ctx, "ev_receipts", passed, artifacts=Artifacts(fail=True))
    out["boot_unobservable_at_close"] = run_attempt(ctx, "ev_boot", passed, facts=Facts(boot=None))
    out["owner_unobservable_on_new_attempt"] = outcome(lambda: ctx.verifier("ev_noowner", facts=Facts(me=False)).new_attempt(plan_id="p", release_id="r", generation=1))
    return ctx.show(out)


def case_evaluate_record_failure(ctx):
    mod = ctx.api.module
    real = mod._write_record
    calls = []

    def failing(path, record):
        calls.append(record["state"])
        if record["state"] in ("evaluated", "cleanup_confirmed", "cleanup_unconfirmed", "resolved"):
            raise OSError("read-only file system")
        return real(path, record)

    ctx.patched(mod, "_write_record", failing)
    result = run_attempt(ctx, "ev_unwritable", lambda f, a, v: PASSED)
    return ctx.show({**result, "write_states": calls})


def case_reconcile(ctx):
    out = {}

    def one(name, owner, *, children=(), state="started", docker=None, facts=None, wanted=(), planted=True, attempt_id=IDS[0], extra=None):
        v = ctx.verifier(name, docker=docker, facts=facts or Facts(procs={1234: ("present", 5)}))
        if planted:
            ctx.plant(v, attempt_id, owner, children=children, state=state)
        if extra:
            extra(v)
        result = outcome(lambda: v.reconcile(list(wanted)))
        return {"result": result, "record": record_of(v, attempt_id), "docker": ctx.docker.view(), "artifacts": ctx.art.rows}

    other_boot = ctx.owner(boot_id="boot-B")
    absent = ctx.owner(pid=999)
    replaced = ctx.owner(pid=1234, start_ticks=6)
    alive = ctx.owner(pid=1234, start_ticks=5)
    me = ctx.owner(start_ticks=TICKS)
    def store_row(aid, owner):
        return {"attempt_id": aid, "plan_id": "plan-1", "release_id": "release-1", "generation": 1, "owner": owner, "started_at": "2026-09-22T00:00:00+00:00"}

    def facts_gone():
        return Facts(procs={999: ("absent", None), 1234: ("present", 5)})

    out["dead_other_boot"] = one("rc_boot", other_boot)
    out["dead_pid_absent"] = one("rc_absent", absent, facts=facts_gone())
    out["dead_pid_replaced"] = one("rc_replaced", replaced)
    out["dead_replaced_wanted_by_store"] = one("rc_wanted", replaced, wanted=[store_row(IDS[0], replaced)])
    out["alive_owner_blocks"] = one("rc_alive", alive)
    out["alive_owner_touches_nothing"] = one("rc_alive_docker", alive, docker=Docker([exact(IDS[0], "release-start", "a")]))
    out["self_owner"] = one("rc_self", me)
    out["unknown_boot_unobservable"] = one("rc_unknown_boot", replaced, facts=Facts(boot=None))
    out["unknown_incomplete_owner"] = one("rc_incomplete", {"pid": PID})
    out["unknown_owner_not_a_dict"] = one("rc_not_dict", "owner")
    out["unknown_no_start_ticks"] = one("rc_noticks", ctx.owner(start_ticks=None, pid=1234))
    out["unknown_process_unobservable"] = one("rc_unobs", ctx.owner(pid=555), facts=Facts(procs={555: ("unknown", None)}))
    out["dead_cgroup_has_stranger"] = one("rc_cgroup", replaced, facts=Facts(procs={1234: ("present", 5)}, members={"/zeus.slice/dead-owner.scope": [PID, 31]}))
    out["dead_cgroup_unreadable"] = one("rc_cgroup_none", replaced, facts=Facts(procs={1234: ("present", 5)}, members={"/zeus.slice/dead-owner.scope": None}))
    out["resolved_record_is_skipped"] = one("rc_resolved", replaced, state="resolved")
    out["resolved_record_returned_when_wanted"] = one("rc_resolved_wanted", replaced, state="resolved", wanted=[store_row(IDS[0], replaced)])

    def junk(v):
        path = v.root / "attempts" / IDS[1]
        path.mkdir(parents=True)
        (path / "run.json").write_text("{not json", encoding="utf-8")

    def mismatched(v):
        path = v.root / "attempts" / IDS[2]
        path.mkdir(parents=True)
        (path / "run.json").write_text(json.dumps({"attempt_id": IDS[3], "state": "started"}), encoding="utf-8")

    def badname(v):
        path = v.root / "attempts" / "not-an-attempt-id"
        path.mkdir(parents=True)
        (path / "run.json").write_text(json.dumps({"attempt_id": "not-an-attempt-id", "state": "started"}), encoding="utf-8")

    out["unreadable_record_is_unknown"] = one("rc_junk", replaced, extra=junk)
    out["record_with_another_identity_is_unknown"] = one("rc_mismatch", replaced, extra=mismatched)
    out["record_with_a_bad_attempt_id_is_unknown"] = one("rc_badname", replaced, planted=False, extra=badname)
    out["no_attempts_directory"] = one("rc_empty", replaced, planted=False)
    out["store_attempt_without_disk_record"] = one("rc_never", replaced, planted=False, wanted=[store_row(IDS[4], other_boot)])
    out["store_attempt_dead_pid_absent"] = one("rc_never_absent", absent, planted=False, facts=facts_gone(), wanted=[store_row(IDS[4], absent)])
    out["store_attempt_owner_alive"] = one("rc_never_alive", alive, planted=False, wanted=[store_row(IDS[4], alive)])
    out["store_attempt_owner_unknown"] = one("rc_never_unknown", {"pid": 1}, planted=False, wanted=[store_row(IDS[4], {"pid": 1})])
    out["store_attempt_invalid_id"] = one("rc_never_badid", other_boot, planted=False, wanted=[store_row("short", other_boot)])
    out["store_attempt_not_a_string_id"] = one("rc_never_nonstr", other_boot, planted=False, wanted=[{"attempt_id": 7}, {"nope": 1}])
    out["store_attempt_leftover_container_is_debt"] = one("rc_never_left", other_boot, planted=False, wanted=[store_row(IDS[4], other_boot)],
                                                          docker=Docker([exact(IDS[4], "release-start", "9")], fail={"rm": 1}))
    out["store_attempt_docker_error"] = one("rc_never_err", other_boot, planted=False, wanted=[store_row(IDS[4], other_boot)], docker=Docker(fail={"ps": 1}))
    out["two_records_one_alive"] = one("rc_two", replaced, extra=lambda v: ctx.plant(v, IDS[5], alive))
    out["two_records_both_dead"] = one("rc_two_dead", replaced, extra=lambda v: ctx.plant(v, IDS[5], other_boot),
                                       wanted=[store_row(IDS[0], replaced), store_row(IDS[5], other_boot)])
    out["leftover_containers_of_a_dead_owner_are_reclaimed"] = one(
        "rc_leftovers", other_boot, docker=Docker([exact(IDS[0], "release-start", "a"), exact(IDS[0], "release-canary", "b")]))
    out["dead_owner_children_boot_ended"] = one("rc_children_boot", other_boot, children=[{"pid": 1234, "pgid": 1234, "start_ticks": 5}])
    return ctx.show(out)


def case_children(ctx):
    out = {}
    v = ctx.verifier("children")
    PERM = PermissionError(1, "not permitted")

    def reclaim(name, child, facts, killpg):
        ctx.killpg, ctx.signals = killpg, []
        v.facts = facts
        result = outcome(lambda: v._reclaim(child))
        return {"result": result, "signals": ctx.signals}

    present = Facts(procs={1234: ("present", 5), 1300: ("unknown", None), 1400: ("absent", None), 1500: ("present", 9)})
    def child(**kw):
        return {"pid": 1234, "pgid": 1234, "start_ticks": 5, **kw}

    out["group_already_gone"] = reclaim("gone", child(), present, {(1234, 0): ProcessLookupError()})
    out["group_not_ours"] = reclaim("perm", child(), present, {(1234, 0): PERM})
    out["leader_unobservable"] = reclaim("unobs", child(pid=1300), present, {})
    out["no_recorded_start_time_is_never_killed"] = reclaim("noticks", child(start_ticks=None), present, {})
    out["other_start_time_is_never_killed"] = reclaim("other", child(start_ticks=6), present, {})
    out["leader_gone_but_members_remain"] = reclaim("absentleader", child(pid=1400), present, {})
    ctx.group_gone[0] = True
    out["exact_child_is_killed"] = reclaim("kill", child(), present, {})
    out["killed_group_vanishes_first"] = reclaim("vanish", child(), present, {(1234, 9): ProcessLookupError()})
    out["kill_not_permitted"] = reclaim("killperm", child(), present, {(1234, 9): PERM})
    ctx.group_gone[0] = False
    out["killed_group_survives"] = reclaim("survive", child(), present, {})
    out["unrecorded_group"] = reclaim("unrec", {"pid": 1234}, present, {})
    out["pgid_one"] = reclaim("one", child(pgid=1), present, {})
    out["pgid_text"] = reclaim("text", child(pgid="1234"), present, {})
    out["non_dict_child_is_an_error"] = reclaim("nondict", "child", present, {})
    ctx.killpg = {}
    return ctx.show(out)


def case_containers(ctx):
    out = {}
    start, canary = exact(IDS[0], "release-start", "a"), exact(IDS[0], "release-canary", "b")
    foreign = [exact(IDS[1], "release-start", "c"), exact(IDS[1], "release-canary", "d"),
               {"id": cid("e"), "name": "zeus-release-start-" + IDS[0] + "-x", "labels": {"zeus.isolated.run": IDS[0]}, "status": "running"},
               {"id": cid("f"), "name": "zeus-release-start-" + IDS[0], "labels": {"zeus.isolated.run": IDS[1]}, "status": "running"}]

    def exact_filters(role):
        return ["--filter", "name=^/zeus-" + role + "-" + IDS[0] + "$", "--filter", "label=zeus.isolated.run=" + IDS[0]]

    def listing(name, docker, filters):
        v = ctx.verifier(name, docker=docker)
        return {"result": outcome(lambda: v._listing(filters)), "docker": ctx.docker.view()}

    out["listing_absent"] = listing("ls_absent", Docker(), exact_filters("release-start"))
    out["listing_one"] = listing("ls_one", Docker([start]), exact_filters("release-start"))
    out["listing_error"] = listing("ls_error", Docker([start], fail={"ps": 2}), exact_filters("release-start"))
    out["listing_ambiguous"] = listing("ls_amb", Docker(extra_ids={tuple(f for f in exact_filters("release-start") if f.startswith(("name=", "label="))):
                                                                   [cid("9"), cid("8")]}), exact_filters("release-start"))
    out["listing_one_but_not_an_id"] = listing("ls_badid", Docker(extra_ids={tuple(f for f in exact_filters("release-start") if f.startswith(("name=", "label="))):
                                                                              ["short"]}), exact_filters("release-start"))
    out["listing_compose_label"] = listing("ls_compose", Docker([{**start, "labels": {"com.docker.compose.project": "zeus-verify-" + IDS[0]}}]),
                                           ["--filter", "label=com.docker.compose.project=zeus-verify-" + IDS[0]])

    def gone(name, docker, role="release-start"):
        v = ctx.verifier(name, docker=docker)
        return {"result": outcome(lambda: v._container_gone(IDS[0], role)), "docker": ctx.docker.view(), "left": sorted(ctx.docker.containers)}

    out["container_absent"] = gone("cg_absent", Docker())
    out["container_running_is_stopped_and_removed"] = gone("cg_running", Docker([start, *foreign]))
    out["container_already_exited"] = gone("cg_exited", Docker([{**start, "status": "exited"}]))
    out["container_remove_fails"] = gone("cg_rm", Docker([start], fail={"rm": 1}))
    out["container_listing_error"] = gone("cg_err", Docker([start], fail={"ps": 1}))
    out["canary_role"] = gone("cg_canary", Docker([start, canary]), "release-canary")
    out["foreign_containers_are_never_named"] = gone("cg_foreign", Docker(foreign))
    named = set()
    for row in out["container_running_is_stopped_and_removed"]["docker"]:
        named.update(part for part in row["args"])
    out["foreign_ids_named_in_the_removal_case"] = sorted(c for c in named if c in {f["id"] for f in foreign})
    return ctx.show(out)


def case_compose(ctx):
    out = {}
    project = "zeus-verify-" + IDS[0]

    def compose(name, *, directory="valid", docker=None, containers=(), make=None):
        v = ctx.verifier(name, docker=docker or Docker(containers))
        v.root.mkdir(parents=True, exist_ok=True)
        target = v.root / project
        if directory == "valid":
            target.mkdir()
            (target / "compose.json").write_text("{}", encoding="utf-8")
            (target / "manifest.json").write_text("{}", encoding="utf-8")
        elif directory == "symlink":
            (v.root / "elsewhere").mkdir()
            target.symlink_to(v.root / "elsewhere")
        elif directory == "file":
            target.write_text("not a directory", encoding="utf-8")
        elif directory == "no_files":
            target.mkdir()
        if make:
            make(v)
        return {"result": outcome(lambda: v._compose_gone(project)), "docker": ctx.docker.view(), "artifacts": ctx.art.rows,
                "left": sorted(str(p.relative_to(v.root)) for p in v.root.rglob("*"))}

    out["no_directory"] = compose("cp_none", directory="none")
    out["down_succeeds"] = compose("cp_down")
    out["down_fails_and_keeps_the_directory"] = compose("cp_down_fail", docker=Docker(compose_fail=True))
    out["directory_without_its_files"] = compose("cp_nofiles", directory="no_files")
    out["symlinked_directory_is_not_entered"] = compose("cp_symlink", directory="symlink")
    out["file_is_not_a_directory"] = compose("cp_file", directory="file")
    out["compose_label_still_lists_a_container"] = compose(
        "cp_listed", directory="none", containers=[{**exact(IDS[0], "release-start", "a"), "labels": {"com.docker.compose.project": project}}])
    out["compose_listing_error"] = compose("cp_ps_error", directory="none", docker=Docker(fail={"ps": 1}))
    v = ctx.verifier("cp_observe")
    out["observe_all_confirmed"] = {"result": outcome(lambda: v._observe(ctx.plant(v, IDS[0], ctx.owner(boot_id="boot-B")), self_owned=False)),
                                    "docker": ctx.docker.view()}
    return ctx.show(out)


def case_names(ctx):
    api = ctx.api
    v = ctx.verifier("names")
    resources = api.attempt_resources(IDS[0])
    owned = {role: api.new_owned(v.docker, IDS[0], role).name for role in resources["containers"]}
    return {"resources": resources, "owned_names": owned, "equal": resources["containers"] == owned,
            "bad_ids": [outcome(lambda bad=bad: api.attempt_resources(bad)) for bad in ("short", "A" * 32, "../x" + "a" * 29, 5, None)],
            "ticket_superseded_is_a_contract_error": issubclass(api.TicketSuperseded, api.ContractError)}


CASES = [("surface", case_surface), ("boundary", case_boundary), ("fence", case_fence), ("proc_facts", case_proc_facts),
         ("available_and_attempts", case_available_and_attempts), ("evaluate", case_evaluate), ("evaluate_record_failure", case_evaluate_record_failure),
         ("reconcile", case_reconcile), ("children", case_children), ("containers", case_containers), ("compose", case_compose), ("names", case_names)]


def run(api, root: Path) -> dict:
    ctx = Ctx(api, root)
    out = {}
    real_getpid, real_killpg = os.getpid, os.killpg
    os.getpid, os.killpg = (lambda: PID), ctx.scripted_killpg
    api.install_runner(lambda argv, cwd=None, timeout=120, input_text=None, env=None: ctx.runner[0](argv, cwd=cwd, timeout=timeout, input_text=input_text, env=env))
    try:
        for name, case in CASES:
            with contextlib.ExitStack() as stack:
                ctx.patched = lambda target, attr, value, stack=stack: _patch(stack, target, attr, value)
                ctx.patched(api.module, "uuid4", ctx.fresh_uuid)
                ctx.patched(api.module, "_group_gone", lambda pgid, seconds=5.0: ctx.group_gone[0])
                ctx.group_gone[0] = True
                shown = outcome(lambda case=case: case(ctx))
                out[name] = ctx.show(shown)
    finally:
        os.getpid, os.killpg = real_getpid, real_killpg
    return {"case_count": len(out), "cases": out}


def _patch(stack, target, attr, value):
    old = getattr(target, attr)
    setattr(target, attr, value)
    stack.callback(setattr, target, attr, old)
