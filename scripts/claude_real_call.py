"""C10: run one assigned implementation task through the real Claude Code CLI and bind the evidence.

One run = one host, one task, one provider call. The task is a small change in a throwaway Git
repository: a `slugify` helper whose tests already exist and currently fail. Everything the harness
normally does stays in place - the reservation, the mandatory audit, the unconfirmed marker, the
worktree, the independent evidence replay, the six-W result through the outbox - and this script
only supplies the repository, an isolated database schema and an isolated Redis namespace, then
writes down what actually happened.

What the receipt separates, deliberately:

* what the model said it did (its structured answer), and
* what this runner measured (the worktree diff, a pytest run it executed itself, the provider's
  own process exit, the rows the harness committed).

Spend and time are bounded by configuration, not by hope: the model is explicit, the CLI's own
`--max-budget-usd` ceiling is passed, the execution has a finite deadline, and the script refuses
to start more than `--max-calls` real calls per output directory. `--fixture` runs the identical
path against `tests/claude_protocol_child.py`, which costs nothing and proves the plumbing; a
fixture receipt is labelled as one and is never evidence about a model.

usage: uv run python scripts/claude_real_call.py --label windows-11 --out docs/zeus/evidence/claude-real-call-001
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

MODULE = '''"""A tiny helper the assigned task has to finish."""


def slugify(text):
    raise NotImplementedError
'''
TESTS = '''from slug import slugify


def test_lowercases_and_joins_words():
    assert slugify("Hello World") == "hello-world"


def test_collapses_separators_and_trims():
    assert slugify("  Zeus   Harness--Release  ") == "zeus-harness-release"


def test_drops_characters_that_are_not_words():
    assert slugify("Release 2.0 (final)!") == "release-2-0-final"
'''
OBJECTIVE = ("Implement slugify in slug.py so that every test in test_slug.py passes. "
             "Use only the Python standard library. Do not change test_slug.py. "
             "Run the tests with `python -m pytest -q` and report the exact commands you ran "
             "in the `tests` field of your answer.")


def now():
    return datetime.now(timezone.utc).isoformat()


def run(argv, cwd=None, timeout=300, env=None):
    try:
        done = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=timeout,
                              env=env if env is not None else {**os.environ, "PYTHONIOENCODING": "utf-8"})
        return {"argv": argv, "exit_code": done.returncode, "stdout": done.stdout, "stderr": done.stderr,
                "timed_out": False}
    except subprocess.TimeoutExpired:
        return {"argv": argv, "exit_code": None, "stdout": "", "stderr": "", "timed_out": True}
    except OSError as exc:
        return {"argv": argv, "exit_code": None, "stdout": "", "stderr": type(exc).__name__, "timed_out": False}


def build_repository(root: Path) -> dict:
    """A throwaway Git repository holding the task: failing tests and an unimplemented helper."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "slug.py").write_text(MODULE, encoding="utf-8", newline="\n")
    (root / "test_slug.py").write_text(TESTS, encoding="utf-8", newline="\n")
    for argv in (["git", "init", "-b", "main"], ["git", "add", "--all"],
                 ["git", "-c", "user.name=Zeus Evidence", "-c", "user.email=evidence@localhost",
                  "commit", "-m", "Task fixture: slugify is not implemented yet"]):
        result = run(argv, cwd=str(root), timeout=120)
        if result["exit_code"] != 0:
            raise RuntimeError("repository setup failed: " + json.dumps(result))
    head = run(["git", "rev-parse", "HEAD"], cwd=str(root))["stdout"].strip()
    before = run([sys.executable, "-m", "pytest", "-q", "test_slug.py"], cwd=str(root), timeout=300)
    return {"path": str(root), "head": head, "tests_before": summarize(before)}


def summarize(result: dict) -> dict:
    lines = [line for line in (result.get("stdout") or "").splitlines() if line.strip()]
    return {"argv": result["argv"], "exit_code": result["exit_code"], "timed_out": result["timed_out"],
            "summary": lines[-1] if lines else "", "stdout_tail": lines[-8:],
            "stderr_tail": [line for line in (result.get("stderr") or "").splitlines() if line.strip()][-4:]}


def isolated_store(dsn: str):
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import make_conninfo

    from codex_harness.adapters.store import PostgresStore

    schema = "claude_call_" + uuid4().hex[:12]
    with psycopg.connect(dsn) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))

    def drop():
        with psycopg.connect(dsn) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))

    store = PostgresStore(make_conninfo(dsn, options=f"-c search_path={schema},public"))
    store.migrate()
    return store, schema, drop


def preflight(args) -> dict:
    """Everything that must be true before a real call is worth starting."""
    from codex_harness.adapters.claude_cli import resolve_claude
    from codex_harness.adapters.commands import run_process

    if args.fixture:
        return {"ready": True, "mode": "fixture", "executable": str(ROOT / "tests/claude_protocol_child.py"),
                "launcher": [sys.executable], "version": "fixture", "flags": [],
                "note": "the protocol child; this receipt is not evidence about a model"}
    executable = resolve_claude(args.executable)
    if not executable:
        return {"ready": False, "mode": "real", "reason": "Claude Code CLI is not installed on this host"}
    # On Linux, PATH can reach a Windows executable through interop. Running it measures a Windows
    # process from a Linux shell, which is not evidence about Linux process handling, so it is
    # refused unless a caller says outright that is what they want.
    interop = os.name != "nt" and (executable.lower().endswith(".exe") or executable.startswith("/mnt/"))
    kind = "windows_binary_via_interop" if interop else ("host_native" if os.name == "nt" else "posix_native")
    if interop and not args.allow_interop:
        return {"ready": False, "mode": "real", "executable": executable, "executable_kind": kind,
                "reason": ("the only Claude Code reachable here is a Windows executable through interop; "
                           "running it would measure a Windows process, not this host")}
    version = run_process([executable, "--version"], timeout=60)
    if version.returncode != 0:
        return {"ready": False, "mode": "real", "executable": executable,
                "reason": "the CLI did not report a version"}
    help_text = run_process([executable, "--help"], timeout=60)
    if help_text.returncode != 0:
        return {"ready": False, "mode": "real", "executable": executable,
                "reason": "the CLI did not report its options"}
    required = ["--print", "--output-format", "--model", "--max-budget-usd", "--json-schema",
                "--session-id", "--permission-mode"]
    missing = [flag for flag in required if flag not in help_text.stdout]
    if missing:
        return {"ready": False, "mode": "real", "executable": executable,
                "reason": "the installed CLI lacks required controls: " + ", ".join(missing)}
    return {"ready": True, "mode": "real", "executable": executable, "launcher": [],
            "executable_kind": kind, "version": version.stdout.strip(),
            "flags": sorted({flag for flag in required if flag in help_text.stdout})}


def already_made(out: Path, label: str | None = None) -> int:
    """Real calls already recorded here: all of them, or only this host's.

    Every call keeps its own receipt, so a later run can neither hide nor overwrite an earlier one,
    and the ceiling is counted from what is on disk rather than from anyone's memory.
    """
    count = 0
    for path in sorted(out.glob("*-receipt.json")):
        try:
            body = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if body.get("mode") == "real" and body.get("executed") and (label is None or body.get("label") == label):
            count += 1
    return count


def execute(args, receipt: dict, workdir: Path, ready: dict) -> dict:

    from codex_harness.adapters.artifacts import FileArtifacts
    from codex_harness.adapters.bus import RedisBus
    from codex_harness.adapters.claude_cli import ClaudeCodeRuntime
    from codex_harness.adapters.contracts import validate_observation
    from codex_harness.adapters.executor import Executor
    from codex_harness.adapters.git import GitWorkspace
    from codex_harness.adapters.observation_spool import FileSpool, SpoolDirectory
    from codex_harness.application.observations import Collector, Observer
    from codex_harness.application.service import Harness
    from codex_harness.bootstrap import organization
    from codex_harness.domain.model import envelope
    from codex_harness.domain.observation import new_process_run_id
    from codex_harness.domain.policy import POLICY

    repository = build_repository(workdir / "repository")
    receipt["task_repository"] = repository

    store, schema, drop = isolated_store(args.database_url)
    receipt["database"] = {"schema": schema, "isolated": True}
    observation_root = workdir / "observations"
    spool = FileSpool(observation_root, new_process_run_id(), max_bytes=POLICY.observation_spool_bytes)
    observer = Observer(store, spool, component="claude-real-call", directory=SpoolDirectory(observation_root))
    try:
        artifacts = FileArtifacts(str(workdir / "artifacts"))
        git = GitWorkspace(repository["path"], str(workdir / "workspaces"))
        service = Harness(store, organization())
        executor = Executor(service, git, artifacts, observer=observer)

        if ready["mode"] == "fixture":
            def factory(**kwargs):
                kwargs.pop("executable", None)
                return ClaudeCodeRuntime(executable=ready["executable"], launcher=ready["launcher"], **kwargs)
            import codex_harness.adapters.executor as executor_module
            executor_module.ClaudeCodeRuntime = factory

        message = envelope("task.assign", "lead:improvement", "worker:implementation", "implement",
                           {"plan": {"objective": OBJECTIVE,
                                     "acceptance_criteria": ["every test in test_slug.py passes",
                                                             "only the standard library is used"],
                                     "allowed_paths": ["slug.py"]}},
                           "claude-real-call-" + uuid4().hex[:8])
        task = executor.workflow.submit(message)
        receipt["assignment"] = {"task_id": task["id"], "agent": task["agent"],
                                 "correlation_id": message["correlation_id"],
                                 "action": message["what"]["action"]}
        started = time.monotonic()
        row = executor.execute_one("worker:implementation")
        receipt["execution"] = {"seconds": round(time.monotonic() - started, 1),
                                "status": (row or {}).get("status"), "error": (row or {}).get("error")}
        receipt["executed"] = True
        if not row:
            receipt["execution"]["note"] = "the task was not claimable"
            return receipt

        # ---- what the harness committed, read back from the database it committed to
        with store.transaction() as tx:
            stored = tx.get("tasks", task["id"])
            reservations = tx.scan("invocation_reservations")
            outbox = [entry["message"] for entry in tx.scan("outbox")]
            terminations = tx.scan("observation_terminations")
            audit = tx.scan("observation_audit")
            session = tx.get("sessions", "worker:implementation")
        result = (stored or {}).get("result") or {}
        receipt["postgres"] = {
            "task": {"id": stored["id"], "status": stored["status"], "attempt": stored["attempt"],
                     "generation": stored["generation"], "agent": stored["agent"]},
            "reservations": [{"id": r["id"], "status": r["status"], "outcome": r["outcome"],
                              "usage": r["usage"], "transport": r["request"]["transport"],
                              "assignment": r["request"].get("assignment"),
                              "within_budget": r.get("within_budget")} for r in reservations],
            "terminations": [{"record_id": r.get("record_id"), "status": r.get("status")} for r in terminations],
            "audit_events": sorted({a["event_type"] for a in audit}),
            "session": {k: session["checkpoint"].get(k) for k in
                        ("provider", "provider_identity", "provider_session_id", "transport",
                         "workspace_identity", "policy_digest", "config_digest", "session_resume",
                         "generation", "attempt")} if session else None,
        }
        receipt["six_w_result"] = [{"type": m["type"], "sender": m["who"]["sender"],
                                    "recipient": m["who"]["recipient"], "action": m["what"]["action"],
                                    "correlation_id": m["correlation_id"],
                                    "task_id": m["what"]["details"].get("task_id")} for m in outbox]

        # ---- what the model said
        receipt["model_self_report"] = {"summary": result.get("summary"),
                                        "tests_claimed": result.get("tests"),
                                        "note": "the model's own words; nothing here is a measurement"}

        # ---- what this runner measured
        candidate = result.get("candidate") or {}
        workspace = git.workspaces / task["id"]
        diff = run(["git", "diff", "--stat", repository["head"], "HEAD"], cwd=str(workspace), timeout=120)
        names = run(["git", "diff", "--name-only", repository["head"], "HEAD"], cwd=str(workspace), timeout=120)
        after = run([sys.executable, "-m", "pytest", "-q", "test_slug.py"], cwd=str(workspace), timeout=600)
        unchanged = run(["git", "diff", "--exit-code", repository["head"], "HEAD", "--", "test_slug.py"],
                        cwd=str(workspace), timeout=120)
        receipt["runner_measured"] = {
            "worktree": str(workspace), "candidate_revision": candidate.get("revision"),
            "diff_stat": [line for line in diff["stdout"].splitlines() if line.strip()],
            "changed_files": [line for line in names["stdout"].splitlines() if line.strip()],
            "tests_after": summarize(after),
            "test_file_unchanged": unchanged["exit_code"] == 0,
            "evidence_inspection": result.get("evidence_inspection"),
            "note": "this runner ran the tests itself in the worktree the execution produced",
        }

        # ---- what the provider's own process did
        reference = result.get("execution_ref")
        provider = {}
        if reference:
            body = json.loads((artifacts.root / (reference[7:] + ".txt")).read_text(encoding="utf-8"))
            provider = {"execution_ref": reference,
                        "command": {k: v for k, v in body.get("command", {}).items()
                                    if k not in {"argv"}},
                        "argv_manifest": body.get("command", {}).get("argv"),
                        "process": body.get("process"), "terminal": body.get("terminal"),
                        "stream": {k: v for k, v in (body.get("stream") or {}).items()
                                   if k not in {"stderr_tail"}},
                        "invocation": body.get("invocation"), "session": body.get("session"),
                        "effective_configuration": body.get("effective_configuration"),
                        "cost": body.get("cost"), "answer_source": body.get("answer_source"),
                        "execution_assignment": body.get("execution_assignment"),
                        "model_selection": body.get("model_selection"),
                        "tool_usage": body.get("tool_usage")}
        receipt["provider_receipt"] = provider

        # ---- the observation log, collected the way the harness collects it
        collector = Collector(store, observer.directory, validate=validate_observation, observer=observer)
        receipt["observations"] = {k: v for k, v in collector.collect(prune=False).items() if k != "per_file"}

        # ---- the six-W result over a real Redis namespace, when one is reachable
        if args.redis_url:
            namespace = "zeus-claude-real-call-" + uuid4().hex[:8]
            bus = RedisBus(args.redis_url, namespace=namespace)
            try:
                receipt["redis"] = {"namespace": namespace,
                                    **service.flush_outbox(bus, audit=observer.audit_system)}
                entry = receipt["redis"].get("entries", [])
                receipt["redis"]["stream_entries_present"] = bool(
                    bus.client.xrange(bus.stream("lead:improvement"))) if not entry else True
            except Exception as exc:  # a missing cache is recorded, never hidden
                receipt["redis"] = {"namespace": namespace, "error": type(exc).__name__}
            finally:
                try:
                    bus.client.delete(bus.stream("lead:improvement"))
                except Exception:
                    pass
        return receipt
    finally:
        observer.close()
        drop()


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Run one assigned implementation task through the configured provider "
                    "and write a receipt that separates the model's report from what was measured.")
    parser.add_argument("--label", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--model", default=os.environ.get("ZEUS_CLAUDE_MODEL"))
    parser.add_argument("--budget", default=os.environ.get("ZEUS_CLAUDE_MAX_BUDGET_USD", "1"))
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--max-calls", type=int, default=2, help="real calls allowed for this host")
    parser.add_argument("--max-total-calls", type=int, default=4,
                        help="real calls allowed across every host in this output directory")
    parser.add_argument("--allow-interop", action="store_true",
                        help="permit a Windows executable reached from Linux; it measures Windows, not this host")
    parser.add_argument("--executable", default=None)
    parser.add_argument("--database-url", default=None)
    parser.add_argument("--redis-url", default=None)
    parser.add_argument("--fixture", action="store_true",
                        help="drive the protocol child instead of the real CLI; costs nothing")
    parser.add_argument("--compose", action="store_true",
                        help="create an isolated PostgreSQL/Redis stack for this run and remove it after")
    args = parser.parse_args(argv)
    out = ROOT / args.out
    out.mkdir(parents=True, exist_ok=True)
    if args.fixture:
        args.model = "claude-stub-normal"
    if args.compose:
        return with_isolated_stack(args, out)
    from codex_harness.bootstrap import database_url, redis_url
    args.database_url = args.database_url or database_url()
    args.redis_url = args.redis_url or redis_url()
    return call(args, out)


def with_isolated_stack(args, out):
    """Borrow the host evidence runner's stack lifecycle: a fresh compose project this run owns,
    ephemeral loopback ports, and a teardown that removes only what it created."""
    sys.path.insert(0, str(ROOT / "scripts"))
    from environment_evidence import EvidenceRun

    stack = EvidenceRun(args.label + "-claude-call", args.out)
    if not stack.preflight() or not stack.claim_project():
        print(json.dumps({"label": args.label, "executed": False,
                          "not_executed_reason": "the isolated stack could not be claimed"}))
        return 1
    try:
        if not stack.stack_up():
            print(json.dumps({"label": args.label, "executed": False,
                              "not_executed_reason": "the isolated stack did not start"}))
            return 1
        args.database_url = (f"postgresql://harness:{stack.password}@127.0.0.1:"
                             f"{stack.services['postgres']['host_port']}/harness")
        args.redis_url = f"redis://127.0.0.1:{stack.services['redis']['host_port']}/0"
        return call(args, out, stack={"compose_project": stack.project,
                                      "services": stack.services, "isolated": True})
    finally:
        stack.teardown()
        for leftover in (stack.override_path, out / f"{stack.label}-receipt.json"):
            leftover.unlink(missing_ok=True)


def call(args, out, stack=None):

    receipt = {"label": args.label, "mode": "fixture" if args.fixture else "real",
               "started_at": now(), "executed": False,
               "host": {"platform": sys.platform, "python": sys.version.split()[0],
                        "git": run(["git", "--version"], timeout=60)["stdout"].strip()},
               "limits": {"max_calls_per_host": args.max_calls, "max_calls_total": args.max_total_calls,
                          "timeout_seconds": args.timeout, "max_budget_usd": args.budget},
               "authority": ("one assigned task executed on this host through the configured provider; "
                             "not a qualification, not a billed amount, not an operational change")}
    if stack is not None:
        receipt["stack"] = stack
    ready = preflight(args)
    receipt["preflight"] = ready
    if not ready["ready"]:
        receipt["not_executed_reason"] = ready["reason"]
    elif not args.model:
        receipt["not_executed_reason"] = "no explicit model was configured; a model is never derived"
    elif ready["mode"] == "real" and already_made(out, args.label) >= args.max_calls:
        receipt["not_executed_reason"] = (f"{args.max_calls} real calls are already recorded for "
                                          f"{args.label}; the per-host ceiling is deliberate")
    elif ready["mode"] == "real" and already_made(out) >= args.max_total_calls:
        receipt["not_executed_reason"] = (f"{args.max_total_calls} real calls are already recorded in "
                                          f"{args.out}; the overall ceiling is deliberate")
    else:
        os.environ["ZEUS_CLAUDE_ASSIGNMENTS"] = "worker:implementation/implement"
        os.environ["ZEUS_CLAUDE_MODEL"] = args.model
        os.environ["ZEUS_CLAUDE_MAX_BUDGET_USD"] = str(args.budget)
        os.environ["ZEUS_CLAUDE_TIMEOUT_SECONDS"] = str(args.timeout)
        receipt["configuration"] = {"assignments": os.environ["ZEUS_CLAUDE_ASSIGNMENTS"],
                                    "model": args.model, "max_budget_usd": str(args.budget),
                                    "timeout_seconds": str(args.timeout)}
        # The throwaway repository, worktree and spool live outside the evidence directory: what
        # is kept is the receipt, not the scratch space the run needed to produce it.
        workdir = Path(tempfile.mkdtemp(prefix="zeus-claude-call-"))
        try:
            execute(args, receipt, workdir, ready)
        except Exception as exc:
            receipt["error"] = {"type": type(exc).__name__, "message": str(exc)[:2000]}
        finally:
            for _ in range(5):  # Windows releases a just-closed pack file a moment late
                shutil.rmtree(workdir, ignore_errors=True)
                if not workdir.exists():
                    break
                time.sleep(1)
            receipt["workdir_removed"] = not workdir.exists()

    receipt["finished_at"] = now()
    measured = receipt.get("runner_measured", {}).get("tests_after", {})
    receipt["task_verified"] = measured.get("exit_code") == 0
    accepted = bool(receipt.get("executed")) and receipt.get("execution", {}).get("status") == "succeeded"
    # A completed execution is not a finished task: for a real call the runner's own test run
    # decides, and a fixture run only claims that the path worked.
    receipt["passed"] = accepted and (receipt["mode"] == "fixture" or receipt["task_verified"])
    receipt["accepted_by_harness"] = accepted
    passed = receipt["passed"]
    if receipt["mode"] == "fixture":
        suffix = "fixture"
    elif receipt.get("executed"):
        suffix = f"call{already_made(out, args.label) + 1}"
    else:
        suffix = "not-executed"  # a refusal is a record of its own, never an unnumbered call
    path = out / f"{args.label}-{suffix}-receipt.json"
    path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: receipt.get(k) for k in ("label", "mode", "executed", "accepted_by_harness",
                                                  "task_verified", "passed", "not_executed_reason")},
                     ensure_ascii=False))
    return 0 if (passed or receipt.get("not_executed_reason")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
