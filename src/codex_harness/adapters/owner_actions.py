"""Production wiring of the server-owned pending-action coordinator (INV-OWNER-ACTIONS-001).

Opt-in only: nothing runs unless the owner registered a Git-pinned `urn:zeus:owner-actions-policy:1` or
`:2` (`zeus owner-actions register`) and a tick or the bounded `run` loop names it; `run` takes `--policy`
once per registered policy and ticks them in turn in ONE process, so their delivery plans are bound
serially against one lane store. Every port here does its
I/O OUTSIDE a store transaction; the application calls them between its own short transactions.

* `load_policy`/`register_policy` - the owner policy read through the existing `GitSource` at an
  explicit commit (never the working tree) and re-read, digest compared, on every tick.
* `GitPlanPublisher` - the exact plan bytes as one deterministic commit (fixed identity and the action's
  own recorded time, so a restart derives the SAME commit) on `refs/zeus/owner-plans/<plan id>`, created
  only when absent; an existing ref with other content is a named conflict, never overwritten. Reading
  back uses the incumbent `host_delivery.load_plan` so registration sees exactly what Git holds.
* `TargetFiles` - the incumbent target state files: the candidate's own startup receipt (read), the
  owner canary request and the owner canary receipt (atomic writes).
* `Assessments` - the independent assessor: the bounded bound report text from the trusted artifact
  store, the assessment document stored content addressed, and one DB-free guardian per launch id (the
  incumbent `continuation_process` guardian) running `zeus owner-actions assess`, i.e. the existing
  guarded `decide_one` of the assessor under `BudgetedExecutor` and the machine call ledger.
* `ResearchLaunches` - the policy v2 research tick: a provider probe on this process's own PATH (the
  unit's explicit provider PATH), then one DB-free guardian per launch id running the existing
  `zeus research-program run <program> --ticks 1 --cycle-owner <launch id>` in the lane repository. The
  owner tick only polls it: a council never runs in this process or blocks another policy's tick.
* policy v2 requalification: `HostDelivery.withdraw` through the lane's GitHub workspace (`lane_git`, as
  `host-delivery withdraw --lane` builds it) and `adapters.continuation.requalify_delivery` (the pin, lane
  runtime and remote main re-verified by that owner).
* `run_loop` - a gated wakeup loop: an idle tick calls no model, writes nothing and starts nothing.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

from codex_harness.adapters.continuation_process import (
    CONDUCT_MARGIN_SECONDS,
    ENTRY_ARGV,
    GUARDIAN_SCHEMA,
    _exclusive,
    _write_atomic,
    launch_directory,
    observe,
    spawn_guardian,
)
from codex_harness.adapters.fleet_backlog import _parse, read_blob
from codex_harness.adapters.host_delivery import (
    RECEIPT_FILE,
    GitHubDelivery,
    HostTargetBase,
    _read_json,
    _write_json,
    canary_receipt_file,
    canary_request_file,
    lane_git,
    load_plan,
)
from codex_harness.adapters.operation_cli import GitSource
from codex_harness.application.owner_actions import OwnerActions
from codex_harness.domain.fleet import lane_of
from codex_harness.domain.fleet_backlog import BacklogRefused
from codex_harness.domain.model import ContractError, canonical
from codex_harness.domain.owner_actions import (
    ASSESSOR,
    EVIDENCE_REF,
    MAX_REPORT_CHARS,
    TICK_SCHEMA,
    OwnerActionRefused,
    validate_policy,
)
from codex_harness.domain.policy import POLICY

MAX_POLICY_BYTES = 64 * 1024
GIT_TIMEOUT = 60
PLAN_AUTHOR = ("Zeus owner actions", "owner-actions@zeus.invalid")
DEFAULT_ARGV = (sys.executable, "-m", "codex_harness.cli")


# ----- the owner's policy ----------------------------------------------------------------------------
def load_policy(source, revision: str, path: str) -> dict:
    try:
        data = read_blob(source, revision, path, MAX_POLICY_BYTES, "policy")
        document = _parse(data, "policy_not_json")
    except BacklogRefused as exc:
        raise OwnerActionRefused(exc.reason_code, "policy") from exc
    return {"policy": validate_policy(document),
            "pin": {"revision": revision, "path": path, "sha256": hashlib.sha256(data).hexdigest()}}


def register_policy(store, config: dict, lane_id: str, revision: str, path: str, source_factory=GitSource) -> dict:
    lane = lane_of(config, lane_id)
    loaded = load_policy(source_factory(lane["repository"]), revision, path)
    return OwnerActions(store).register(loaded["policy"], {**loaded["pin"], "lane": lane_id})


# ----- Git plan publication ------------------------------------------------------------------------------
class GitPlanPublisher:
    """One repository; argv-only Git with a fixed author, never a shell and never the working tree."""

    def __init__(self, repository, *, timeout: int = GIT_TIMEOUT):
        self.repository, self.timeout = str(repository), timeout

    def _git(self, *args, stdin: bytes | None = None, env=None) -> subprocess.CompletedProcess:
        environment = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull, **(env or {})}
        try:
            return subprocess.run(["git", "-C", self.repository, *args], input=stdin, capture_output=True,
                                  timeout=self.timeout, env=environment)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError("git unavailable") from exc

    def _out(self, *args, stdin: bytes | None = None, env=None) -> str:
        done = self._git(*args, stdin=stdin, env=env)
        if done.returncode:
            raise RuntimeError("git refused")
        return done.stdout.decode("ascii", "replace").strip()

    def commit_for(self, data: bytes, path: str, when: str) -> str:
        """The deterministic commit carrying exactly `data` at `path` (content addressed objects only)."""
        blob = self._out("hash-object", "-w", "--stdin", stdin=data)
        parts = path.split("/")
        entry = "100644 blob " + blob + "\t" + parts[-1] + "\n"
        tree = self._out("mktree", stdin=entry.encode("utf-8"))
        for name in reversed(parts[:-1]):
            tree = self._out("mktree", stdin=("040000 tree " + tree + "\t" + name + "\n").encode("utf-8"))
        identity = {"GIT_AUTHOR_NAME": PLAN_AUTHOR[0], "GIT_AUTHOR_EMAIL": PLAN_AUTHOR[1],
                    "GIT_COMMITTER_NAME": PLAN_AUTHOR[0], "GIT_COMMITTER_EMAIL": PLAN_AUTHOR[1],
                    "GIT_AUTHOR_DATE": when, "GIT_COMMITTER_DATE": when}
        return self._out("commit-tree", tree, "-m", "owner delivery plan " + parts[-1], env=identity)

    def current(self, ref: str) -> str | None:
        done = self._git("rev-parse", "--verify", "--quiet", ref + "^{commit}")
        return done.stdout.decode("ascii", "replace").strip() if done.returncode == 0 else None

    def publish(self, data: bytes, path: str, ref: str, when: str) -> dict:
        """Create `ref` at the deterministic commit only when absent; recognize our own; never move another."""
        commit = self.commit_for(data, path, when)
        existing = self.current(ref)
        if existing is None:
            done = self._git("update-ref", ref, commit, "")  # "" = must not exist yet
            existing = self.current(ref)
            if done.returncode and existing is None:
                raise RuntimeError("git refused")
        return {"revision": commit, "conflict": existing != commit}

    def load(self, revision: str, path: str) -> dict:
        return load_plan(GitSource(self.repository), revision, path)


# ----- target files ----------------------------------------------------------------------------------------
class TargetFiles:
    """The incumbent target state files; reads are bounded, writes are atomic replacements. The owner
    canary request and receipt are the files of ONE plan (`canary_request_file`/`canary_receipt_file`)."""

    @staticmethod
    def startup(target: dict):
        return _read_json(HostTargetBase.path(target, RECEIPT_FILE))

    @staticmethod
    def request(target: dict, plan_id: str):
        return _read_json(HostTargetBase.path(target, canary_request_file(plan_id)))

    @staticmethod
    def write_request(target: dict, plan_id: str, document: dict) -> None:
        HostTargetBase.state_dir(target).mkdir(parents=True, exist_ok=True)
        _write_json(HostTargetBase.path(target, canary_request_file(plan_id)), document)

    @staticmethod
    def write_receipt(target: dict, plan_id: str, document: dict) -> None:
        _write_json(HostTargetBase.path(target, canary_receipt_file(plan_id)), document)


# ----- the independent assessor ------------------------------------------------------------------------
class Assessments:
    """Context from the trusted artifact store, the assessment document, and one guardian per launch.

    `root` is the launch directory root (`<runtime>/owner-actions`); `command(decision_id, correlation)`
    overrides the assessor argv (tests use a labelled child); `spawn` overrides the guardian spawn."""

    def __init__(self, artifacts, root, *, argv=DEFAULT_ARGV, entry=ENTRY_ARGV, command=None, spawn=spawn_guardian,
                 seconds: float | None = None, environment=None):
        self.artifacts, self.root, self.argv, self.entry = artifacts, Path(root), tuple(argv), tuple(entry)
        self.command, self.spawn, self.environment = command, spawn, environment
        self.seconds = POLICY.decision_seconds + CONDUCT_MARGIN_SECONDS if seconds is None else seconds
        self.children: dict = {}

    def context(self, binding: dict, found: dict) -> dict:
        """The bound report the assessor must read: the accepted council's frozen report execution
        receipt (its answer), bounded. Unreadable evidence is no context, never an empty report."""
        run = ((found.get("facts") or {}).get("acceptance") or {}).get("run") or {}
        report = run.get("report") if isinstance(run.get("report"), dict) else {}
        ref = report.get("execution_ref")
        if not (type(ref) is str and EVIDENCE_REF.fullmatch(ref)):
            return {"report": None}
        try:
            document = self.artifacts.document(ref)
        except (OSError, ValueError, ContractError):
            return {"report": None}
        answer = document.get("answer")
        return {"report": canonical(answer)[:MAX_REPORT_CHARS] if answer is not None else None,
                "report_digest": report.get("sha256"), "evidence_refs": [ref], "members": found.get("members") or []}

    def document(self, document: dict) -> str:
        return self.artifacts.put(canonical(document), "owner-assessment")["ref"]

    def start(self, launch: str, decision_id: str, correlation_id: str) -> dict:
        command = (list(self.command(decision_id, correlation_id)) if self.command is not None else
                   [*self.argv, "owner-actions", "assess", "--decision", decision_id, "--correlation", correlation_id])
        env = self.environment() if self.environment is not None else None
        return _start_guardian(self, launch, decision_id, command, env=env)

    def poll(self, launch: str) -> dict:
        return _poll_guardian(self, launch)

    def join(self, poll_seconds: float = 0.2) -> None:
        while any(child.poll() is None for child in self.children.values()):
            time.sleep(poll_seconds)


def _start_guardian(port, launch: str, token: str, command: list, *, env=None, cwd=None) -> dict:
    """ONE spawn per launch identity: the exclusive `spawn` marker is created before the guardian exists,
    so a lost response, a restart or a second coordinator gets `cached`, never a second child."""
    directory = launch_directory(port.root, launch)
    if launch in port.children:
        return {"cached": True}
    directory.mkdir(parents=True, exist_ok=True)
    if not _exclusive(directory / "spawn", "owner-actions"):
        return {"cached": True}  # one-shot: this identity was spawned before (a lost response, a restart)
    _write_atomic(directory / "launch.json", {"schema": GUARDIAN_SCHEMA, "launch": launch, "token": token,
                                              "seconds": port.seconds})
    argv = [*port.entry, "--launch", str(directory), "--seconds", repr(float(port.seconds)), "--", *command]
    guardian = port.spawn(argv, env=env) if cwd is None else port.spawn(argv, env=env, cwd=cwd)
    port.children[launch] = guardian
    return {"cached": False, "pid": guardian.pid}


def _poll_guardian(port, launch: str) -> dict:
    child = port.children.get(launch)
    if child is not None and child.poll() is None:
        return {"state": "running", "owned": True}
    port.children.pop(launch, None)
    return observe(launch_directory(port.root, launch))


# ----- the guarded research tick (policy v2 `research`) -----------------------------------------------------
class ResearchLaunches:
    """`probe()` before any effect, `start(launch, program, lane)` once per launch id and `poll(launch)`.

    `repository(lane_id)` is the lane's registered repository path: the child runs there with
    `ZEUS_REPOSITORY`/`HARNESS_REPOSITORY` naming it, so the program's own `repository_mismatch` check sees
    the identity it was registered with. The guardian bound is the implementation allowance plus the
    conductor margin (`domain.policy`), never restated here. `command` (tests: a LABELLED child),
    `spawn`, `resolve` and `run` are the test seams."""

    def __init__(self, root, repository, *, argv=DEFAULT_ARGV, entry=ENTRY_ARGV, command=None, spawn=spawn_guardian,
                 seconds: float | None = None, resolve=None, run=subprocess.run):
        self.root, self.repository, self.argv, self.entry = Path(root), repository, tuple(argv), tuple(entry)
        self.command, self.spawn, self.run = command, spawn, run
        self.resolve = resolve or _resolve_provider
        self.seconds = POLICY.task_seconds + CONDUCT_MARGIN_SECONDS if seconds is None else seconds
        self.children: dict = {}

    def probe(self) -> dict:
        """The provider executables the child would resolve on this PATH, each answering `--version`. No
        model call and no store; anything unresolved or failing is `ok: false` with a fixed code."""
        found = self.resolve()
        record = {"ok": False, "codex": found.get("codex"), "node": found.get("node"), "reason_code": None}
        for name in ("codex", "node"):
            if not found.get(name):
                return {**record, "reason_code": name + "_unresolved"}
            try:
                done = self.run([found[name], "--version"], capture_output=True, timeout=60, stdin=subprocess.DEVNULL,
                                check=False)
            except (OSError, subprocess.TimeoutExpired) as exc:
                return {**record, "reason_code": name + "_unavailable", "error_type": type(exc).__name__}
            if done.returncode != 0:
                return {**record, "reason_code": name + "_version_failed"}
        return {**record, "ok": True}

    def start(self, launch: str, program_id: str, lane: str) -> dict:
        repository = str(self.repository(lane))
        command = (list(self.command(program_id, launch)) if self.command is not None else
                   [*self.argv, "research-program", "run", program_id, "--ticks", "1", "--cycle-owner", launch])
        env = {**os.environ, "ZEUS_REPOSITORY": repository, "HARNESS_REPOSITORY": repository}
        return _start_guardian(self, launch, launch, command, env=env, cwd=repository)

    def poll(self, launch: str) -> dict:
        return _poll_guardian(self, launch)


def _resolve_provider() -> dict:
    from codex_harness.adapters.codex import resolve_codex

    return {"codex": resolve_codex(), "node": shutil.which("node")}


def assess(service, decision_id: str, correlation_id: str, model_label: str, *, executor=None, budget=None) -> dict:
    """The guardian's child: the existing guarded `decide_one` of the independent assessor for EXACTLY
    this pending owner-assessment row, under the machine call ledger. A second dispatcher claims nothing."""
    from codex_harness.application.operation import BudgetedExecutor

    if executor is None:
        from codex_harness.adapters.call_budget import CallBudget
        from codex_harness.bootstrap import build_executor, build_observer

        executor = build_executor(service, observer=build_observer(service.store, "cli.owner-actions"),
                                  knowledge=False)
        budget = CallBudget()
    expected = {"id": decision_id, "correlation_id": correlation_id, "statuses": {"pending", "retry"}}
    wrapped = BudgetedExecutor(executor, budget, {"per_host": 1, "total": 1}, "owner-assessment:" + decision_id,
                               model_label)
    result = wrapped.decide_one(ASSESSOR, expected=expected)
    with service.store.transaction() as tx:
        decision = tx.get("decisions_pending", decision_id) or {}
    accepted = (decision.get("result") or {}).get("accepted")
    calls = {"reserved": len(wrapped.slots), "settled": sum(s["settled"] for s in wrapped.slots)}
    # The exit code is the launch's bound execution outcome the coordinator promotes on (R1): THIS
    # launch owned the claim, the decision succeeded and every call reservation it took is settled.
    resolved = result is not None and decision.get("status") == "succeeded" and calls["reserved"] == calls["settled"]
    return {"decision_id": decision_id, "claimed": result is not None, "status": decision.get("status"),
            "accepted": accepted if isinstance(accepted, bool) else None, "calls": calls,
            "exit_code": 0 if resolved else 1}


# ----- the coordinator with its real ports -------------------------------------------------------------
def coordinator(service, config: dict, host: dict, *, lanes=None, assessments=None, publisher_factory=None,
                continuation=None, research=None):
    from codex_harness.adapters.artifacts import FileArtifacts
    from codex_harness.adapters.call_budget import CallBudget
    from codex_harness.adapters.configuration import runtime_dir
    from codex_harness.adapters.continuation import (
        LaneMainline,
        lane_stores,
        requalify_delivery,
        research_evidence,
        validator,
    )
    from codex_harness.application.continuation import Continuation
    from codex_harness.application.fleet import Fleet
    from codex_harness.application.host_delivery import HostDelivery

    lanes = lanes or lane_stores(config, host)
    store = service.store
    continuation = continuation or Continuation(store, Fleet(store), lanes, None, validate=validator(),
                                                evidence=research_evidence())
    root = runtime_dir()
    artifacts = FileArtifacts(str(root / "artifacts"))
    assessments = assessments or Assessments(artifacts, root / "owner-actions")
    research = research or ResearchLaunches(root / "owner-actions" / "research",
                                            lambda lane_id: lane_of(config, lane_id)["repository"])
    publisher_factory = publisher_factory or GitPlanPublisher

    def withdrawals(lane_id):
        # The same lane store and GitHub workspace `host-delivery withdraw --lane` uses: one authority.
        return HostDelivery(lanes(lane_id).store, service.org,
                            github=GitHubDelivery(lane_git(lane_of(config, lane_id), host)))

    return OwnerActions(store, continuation=continuation, org=service.org, lanes=lanes,
                        deliveries=lambda lane_id: HostDelivery(lanes(lane_id).store, service.org),
                        publisher=lambda lane_id: publisher_factory(lane_of(config, lane_id)["repository"]),
                        assessments=assessments, targets=TargetFiles(), fleet=Fleet(store), validate=validator(),
                        withdrawals=withdrawals, mainline=LaneMainline(config, host),
                        requalify=lambda document: requalify_delivery(store, config, host, document, lanes=lanes),
                        artifacts=artifacts, research=research, ledger=lambda: CallBudget().counts())


def tick_policy(owner: OwnerActions, config: dict, policy_id: str, *, source_factory=GitSource) -> dict:
    """One bounded tick; the registered pin is re-read so a changed policy refuses before any effect."""
    with owner.store.transaction() as tx:
        row = tx.get("owner_action_policies", policy_id)
    if row is None or not row["policy"]["enabled"]:
        return owner.tick(policy_id)
    pin = row["pin"]
    try:
        sha = load_policy(source_factory(lane_of(config, pin["lane"])["repository"]), pin["revision"],
                          pin["path"])["pin"]["sha256"]
    except Exception as exc:
        return {"schema": "urn:zeus:owner-actions-tick:1", "policy_id": policy_id, "outcome": "refused",
                "reason_code": "policy_unavailable", "error_type": type(exc).__name__, "actions": []}
    return owner.tick(policy_id, pin_sha256=sha)


def tick_policies(owner: OwnerActions, config: dict, policy_ids, *, source_factory=GitSource) -> dict:
    """One bounded tick of each named policy in turn, in this one process. A refused read of one policy is
    that policy's named receipt and never stops the others; a research child is only polled, never waited."""
    results = []
    for policy_id in policy_ids:
        try:
            results.append(tick_policy(owner, config, policy_id, source_factory=source_factory))
        except (ContractError, OSError, RuntimeError, ValueError) as exc:
            results.append({"schema": TICK_SCHEMA, "policy_id": policy_id, "outcome": "refused",
                            "reason_code": getattr(exc, "reason_code", None) or "tick_failed",
                            "error_type": type(exc).__name__, "actions": []})
    outcomes = {result["outcome"] for result in results}
    outcome = "progressed" if "progressed" in outcomes else ("refused" if "refused" in outcomes else "idle")
    return {"schema": "urn:zeus:owner-actions-ticks:1", "outcome": outcome, "policies": results}


def policy_list(values) -> list:
    """The `--policy` values of one `run`: at least one, each once."""
    values = list(values or [])
    if not values or len(set(values)) != len(values):
        raise OwnerActionRefused("policy_list_invalid", "policy")
    return values


def run_loop(tick, *, interval: int = 15, max_ticks: int = 0, sleep=time.sleep) -> dict:
    """Gated wakeups: each tick does nothing while idle; a stop finishes the tick in flight."""
    stopping = {"stop": False}

    def stop(*_):
        stopping["stop"] = True

    installed = []
    for name in ("SIGINT", "SIGTERM"):
        handler = getattr(signal, name, None)
        try:
            installed.append((handler, signal.signal(handler, stop)))
        except (ValueError, OSError, TypeError):
            pass
    counts: dict = {}
    ticks = 0
    try:
        while not stopping["stop"]:
            result = tick()
            ticks += 1
            counts[result["outcome"]] = counts.get(result["outcome"], 0) + 1
            if max_ticks and ticks >= max_ticks:
                break
            sleep(max(1, int(interval)))
    finally:
        for handler, previous in installed:
            try:
                signal.signal(handler, previous)
            except (ValueError, OSError, TypeError):
                pass
    return {"schema": "urn:zeus:owner-actions-run:1", "ticks": ticks, "outcomes": counts, "stopped": stopping["stop"]}


# ----- CLI -------------------------------------------------------------------------------------------------
def add_parser(commands) -> None:
    root = commands.add_parser("owner-actions", help="Server-owned research acceptance, delivery-plan and canary "
                                                     "handoffs (opt-in; approves nothing itself)")
    sub = root.add_subparsers(dest="owner_actions_command", required=True)
    register = sub.add_parser("register", help="Register the owner policy read at a commit "
                                               "(urn:zeus:owner-actions-policy:1 or :2)")
    register.add_argument("--lane", required=True)
    register.add_argument("--revision", required=True)
    register.add_argument("--path", required=True)
    tick = sub.add_parser("tick", help="One bounded pass; no model call and no write when idle")
    tick.add_argument("--policy", required=True)
    run = sub.add_parser("run", help="Gated wakeup loop over `tick` of every named policy in turn")
    run.add_argument("--policy", required=True, action="append",
                     help="A registered owner policy id; repeat it to tick several in this one process")
    run.add_argument("--interval", type=int, default=15)
    run.add_argument("--max-ticks", type=int, default=0, dest="max_ticks")
    status = sub.add_parser("status", help="Read the owner-action projection; store read only")
    status.add_argument("--policy", default=None)
    assess_parser = sub.add_parser("assess", help="Guardian child: the guarded independent assessment of one row")
    assess_parser.add_argument("--decision", required=True)
    assess_parser.add_argument("--correlation", required=True)


def execute(service, args) -> dict:
    from codex_harness.adapters.configuration import settings
    from codex_harness.application.fleet import Fleet

    command = args.owner_actions_command
    if command == "status":
        return {**OwnerActions(service.store).status(args.policy), "exit_code": 0}
    if command == "assess":
        with service.store.transaction() as tx:
            decision = tx.get("decisions_pending", args.decision) or {}
            policies = tx.scan("owner_action_policies")
        label = next((row["policy"]["assessment"]["model_label"] for row in policies), "owner-assessment")
        if decision.get("phase") != "owner_assessment":
            raise OwnerActionRefused("assessment_row_foreign", "decision")
        return assess(service, args.decision, args.correlation, label)
    config = Fleet(service.store).registered()["config"]
    if command == "register":
        return {**register_policy(service.store, config, args.lane, args.revision, args.path), "exit_code": 0}
    owner = coordinator(service, config, settings())
    if command == "tick":
        result = tick_policy(owner, config, args.policy)
        owner.assessments.join()
        return {**result, "exit_code": 1 if result["outcome"] == "refused" else 0}
    policies = policy_list(args.policy)
    return {**run_loop(lambda: tick_policies(owner, config, policies), interval=args.interval,
                       max_ticks=args.max_ticks), "policies": policies, "exit_code": 0}


def refusal(exc: Exception) -> dict:
    return {"status": "refused", "reason_code": getattr(exc, "reason_code", None)
            or ("contract_refused" if isinstance(exc, ContractError) else "error"),
            "error_type": type(exc).__name__, "exit_code": 1}


__all__ = ["Assessments", "GitPlanPublisher", "ResearchLaunches", "TargetFiles", "add_parser", "assess", "coordinator",
           "execute", "load_policy", "policy_list", "refusal", "register_policy", "run_loop", "tick_policies",
           "tick_policy"]
