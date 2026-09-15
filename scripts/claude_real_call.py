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
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from codex_harness.adapters.call_budget import CallBudget  # noqa: E402
from codex_harness.adapters.scratch import Scratch  # noqa: E402
from codex_harness.domain.model import ContractError  # noqa: E402

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


def call_budget_policy() -> dict:
    """The ceilings, from the packaged execution policy. This runner defines none of its own."""
    from codex_harness.adapters.providers import packaged_policy

    budget = packaged_policy().provider("claude").runtime.get("experiment_call_budget") or {}
    return {"per_host": int(budget.get("per_host", 0)), "total": int(budget.get("total", 0)),
            "note": budget.get("note")}


def receipts_here(out: Path, label: str | None = None) -> int:
    """Receipts in this directory. A count for the reader; never the thing that limits a call."""
    count = 0
    for path in sorted(out.glob("*-receipt.json")):
        try:
            body = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if body.get("mode") == "real" and body.get("executed") and (label is None or body.get("label") == label):
            count += 1
    return count


def command_record(result: dict) -> dict:
    """A command's output together with how it ended. One without the other is not evidence."""
    return {"argv": result["argv"], "exit_code": result["exit_code"], "timed_out": result["timed_out"],
            "stdout": result.get("stdout") or "", "stderr": result.get("stderr") or "",
            "succeeded": result["exit_code"] == 0 and not result["timed_out"]}


def execute(args, receipt: dict, workdir: Path, ready: dict) -> dict:
    # Evidence bookkeeping exists before the first thing that can fail, so a failure partway through
    # is a run with partial evidence rather than a run with no list of it.
    receipt.setdefault("preservable", {})

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
                              # Which option effects this harness checked, and which it passed to
                              # the provider: a spend ceiling in the request is not a spend result.
                              "effect_verified_here": r["request"].get("effect_verified_here"),
                              "effect_left_to_provider": r["request"].get("effect_left_to_provider"),
                              "unconfirmed_options": r["request"].get("unconfirmed"),
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
        # The whole diff and the whole log, not their tails: the scratch that holds them is about to
        # go, and a summary cannot be re-read by somebody checking this later. Each command's exit
        # status travels with its output, because an empty diff and a diff command that failed look
        # identical once only the stdout is kept.
        patch = run(["git", "diff", repository["head"], "HEAD"], cwd=str(workspace), timeout=120)
        receipt["preservable"].update({
            "candidate_revision": candidate.get("revision"),
            "base_revision": repository["head"],
            "diff": command_record(patch), "tests_after": command_record(after),
        })
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



SWEPT_DIRECTORIES = ("artifacts", "observations")
SWEEP_BYTE_CAP = 64 * 1024 * 1024


def swept_evidence(scratch) -> dict:
    """Every file the run actually wrote into the scratch's evidence directories.

    The list a run builds as it goes is bookkeeping, and bookkeeping stops when the run throws. The
    filesystem does not: an execution artifact on disk is the same artifact whether or not anything
    got round to recording its path. So what is on disk decides, and the bookkeeping only adds what
    disk cannot show (a revision id, a command's exit status).
    """
    entries, total, capped, errors, seen = [], 0, False, [], 0
    for name in SWEPT_DIRECTORIES:
        directory = scratch.root / name
        if not directory.is_dir():
            continue
        try:
            found_here = sorted(p for p in directory.rglob("*") if p.is_file())
        except OSError as exc:
            # Not being able to look is not the same as there being nothing to see.
            errors.append({"directory": name, "error": type(exc).__name__, "message": str(exc)[:200]})
            continue
        for found in found_here:
            seen += 1
            try:
                size = found.stat().st_size
            except OSError:
                size = 0
            if total + size > SWEEP_BYTE_CAP:
                capped = True
                continue
            total += size
            entries.append({"name": (name + "/" + str(found.relative_to(directory))).replace("\\", "/"),
                            "source": found})
    return {"entries": entries, "bytes": total, "capped": capped, "errors": errors, "seen": seen}


def preserve_evidence(scratch, receipt: dict, out: Path, label: str, run_id: str) -> dict:
    """Move the evidence out of the scratch and prove it arrived, before the scratch is removed.

    `execution_ref` points into the scratch. A receipt that keeps the reference and drops the bytes
    cannot be re-read by anyone, so everything the run wrote under `artifacts/` and `observations/`
    is copied out and the receipt is told where the copies are. The diff, the candidate revision and
    this runner's own test log go with them: those are the measurements the acceptance rests on.

    The destination is this run's own directory. A second run with the same label writes beside this
    one and never through it, so an earlier receipt's digests keep answering.
    """
    source = receipt.pop("preservable", None) or {}
    destination = Path(out) / f"{label}-evidence" / run_id
    entries, required_failures = [], []

    diff = source.get("diff")
    if diff is not None:
        if diff["succeeded"]:
            entries.append({"name": "candidate.diff", "text": diff["stdout"]})
        else:
            # A failed diff is not an empty diff. The failure is kept as its own record and the run
            # is not called complete on the strength of a file that was never produced.
            required_failures.append({"evidence": "candidate.diff", "argv": diff["argv"],
                                      "exit_code": diff["exit_code"], "timed_out": diff["timed_out"]})
            entries.append({"name": "candidate.diff.failed.json",
                            "text": json.dumps(diff, ensure_ascii=False, indent=2)})
    tests = source.get("tests_after")
    if tests is not None:
        entries.append({"name": "runner-tests-after.log",
                        "text": tests["stdout"] + ("\n--- stderr ---\n" + tests["stderr"]
                                                  if tests["stderr"] else "")})
        entries.append({"name": "runner-tests-after.command.json",
                        "text": json.dumps({k: v for k, v in tests.items()
                                            if k not in ("stdout", "stderr")}, ensure_ascii=False, indent=2)})
        if tests["timed_out"]:
            required_failures.append({"evidence": "runner-tests-after.log", "argv": tests["argv"],
                                      "exit_code": tests["exit_code"], "timed_out": True})

    sweep = swept_evidence(scratch)
    entries.extend(sweep["entries"])

    # An empty selection is not the same as an empty scratch. A sweep that hit its cap, a directory
    # that could not be listed, and a receipt naming an artifact that is not there all produce no
    # entries, and each of them is a reason to be incomplete rather than a reason to say there was
    # nothing to keep. So the copying is conditional and the judging is not.
    if entries:
        report = scratch.preserve(destination, entries)
    else:
        report = {"complete": True, "kept": [], "failures": [], "destination": str(destination),
                  "note": "no file was selected to keep"}
    report["run_id"] = run_id
    report["revisions"] = {"base": source.get("base_revision"),
                           "candidate": source.get("candidate_revision")}
    report["swept"] = {"files": len(sweep["entries"]), "seen": sweep["seen"], "bytes": sweep["bytes"],
                       "capped": sweep["capped"], "errors": sweep["errors"]}
    report["required_failures"] = required_failures
    if required_failures:
        report["complete"] = False
    if sweep["capped"]:
        report["complete"] = False
        report.setdefault("failures", []).append(
            {"name": "swept evidence", "error": "SweepCapped",
             "message": f"the scratch held more evidence than the {SWEEP_BYTE_CAP} byte sweep cap"})
    if sweep["errors"]:
        report["complete"] = False
        report.setdefault("failures", []).append(
            {"name": "swept evidence", "error": "NotEnumerated",
             "message": "an evidence directory in the scratch could not be listed"})
    kept_names = {entry["name"] for entry in report["kept"]}
    swept_prefixes = tuple(name + "/" for name in SWEPT_DIRECTORIES)
    if sweep["seen"] and not any(name.startswith(swept_prefixes) for name in kept_names):
        report["complete"] = False
        report.setdefault("failures", []).append(
            {"name": "swept evidence", "error": "NotPreserved",
             "message": "the scratch held artifacts or observations and none of them were kept"})
    reference = (receipt.get("provider_receipt") or {}).get("execution_ref")
    if reference:
        wanted = "artifacts/" + str(reference)[7:] + ".txt"
        match = next((entry for entry in report["kept"] if entry["name"] == wanted), None)
        if match is not None:
            receipt.setdefault("provider_receipt", {})["preserved_copy"] = {
                "path": match["path"], "sha256": match["sha256"],
                "note": "execution_ref pointed inside the scratch; this copy outlives it"}
        else:
            report["complete"] = False
            report.setdefault("failures", []).append(
                {"name": wanted, "error": "NotPreserved",
                 "message": "the receipt names an execution artifact that was not kept"})
    if report["complete"] and not report["kept"]:
        report["note"] = "the scratch held no execution artifact or observation to keep"
    return report


def call(args, out, stack=None):
    ceilings = call_budget_policy()
    slot = None
    # Made before anything else and never derived from what is already on disk: two runs started at
    # the same moment with the same label still get different identities, and a count of existing
    # files could not promise that.
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]

    receipt = {"label": args.label, "mode": "fixture" if args.fixture else "real",
               "run_id": run_id, "started_at": now(), "executed": False,
               "host": {"platform": sys.platform, "python": sys.version.split()[0],
                        "git": run(["git", "--version"], timeout=60)["stdout"].strip()},
               "limits": {**ceilings, "timeout_seconds": args.timeout,
                          "max_budget_usd": args.budget,
                          "ceiling_source": "the packaged execution policy, counted in a per-machine ledger"},
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
    else:
        if ready["mode"] == "real":
            # The slot is taken before anything can start a process, in a ledger that lives outside
            # every checkout and identifies this machine from its own facts. Renaming the run or
            # writing elsewhere changes nothing here.
            budget = CallBudget()
            try:
                slot = budget.reserve(purpose="u002-c10-acceptance", provider="claude",
                                      model=args.model, per_host=ceilings["per_host"],
                                      total=ceilings["total"])
            except ContractError as refusal:
                receipt["not_executed_reason"] = str(refusal)
                receipt["call_budget"] = {**budget.counts(), "ceilings": ceilings}
            else:
                receipt["call_budget"] = {"slot": slot["id"], "ceilings": ceilings,
                                          "ledger": str(budget.root),
                                          "counts_at_reservation": slot["counts_at_reservation"],
                                          "host": slot["host"]}
    if receipt.get("not_executed_reason") is None and ready["ready"] and args.model:
        os.environ["ZEUS_CLAUDE_ASSIGNMENTS"] = "worker:implementation/implement"
        os.environ["ZEUS_CLAUDE_MODEL"] = args.model
        os.environ["ZEUS_CLAUDE_MAX_BUDGET_USD"] = str(args.budget)
        os.environ["ZEUS_CLAUDE_TIMEOUT_SECONDS"] = str(args.timeout)
        receipt["configuration"] = {"assignments": os.environ["ZEUS_CLAUDE_ASSIGNMENTS"],
                                    "model": args.model, "max_budget_usd": str(args.budget),
                                    "timeout_seconds": str(args.timeout)}
        # The throwaway repository, worktree and spool live outside the evidence directory. What
        # is kept is the receipt and the evidence it points at - and those leave the scratch, and
        # are verified on disk, before any of it is removed.
        scratch = Scratch.create(prefix="zeus-claude-call-")
        workdir = scratch.root
        try:
            execute(args, receipt, workdir, ready)
        except Exception as exc:
            receipt["error"] = {"type": type(exc).__name__, "message": str(exc)[:2000]}
        finally:
            destination = out / f"{args.label}-evidence" / run_id
            try:
                receipt["preserved"] = preserve_evidence(scratch, receipt, out, args.label, run_id)
            except Exception as exc:
                # Preservation failing is exactly when the report matters most: the scratch is the
                # only copy left, and somebody has to be told where it is.
                receipt["preserved"] = {
                    "complete": False, "kept": [], "run_id": run_id, "destination": str(destination),
                    "failures": [{"name": "preservation", "error": type(exc).__name__,
                                  "message": str(exc)[:400]}],
                    "required_failures": [],
                    "note": "preservation itself failed; the scratch is kept and reported"}
            # Two reasons to keep the scratch, and both are about not being able to say what is in
            # it: evidence that could not be preserved, and a run that ended in a way this script
            # did not plan for, where what was produced is not fully known.
            uncertain = bool(receipt.get("error"))
            if receipt["preserved"]["complete"] and not uncertain:
                removal = scratch.remove()
            else:
                removal = {"root": str(scratch.root), "removed": False, "refusals": [],
                           "recleanable": True,
                           "skipped_because": ("the run ended in an unplanned way, so what it produced "
                                               "is not fully known" if uncertain else
                                               "the evidence could not be preserved, so the scratch is kept")}
            receipt["workdir_cleanup"] = removal
            receipt["workdir_removed"] = removal["removed"]
            if slot is not None:
                # Settled whatever happened above: a reserved slot that is never settled keeps
                # counting, and that must not depend on whether the evidence could be copied.
                try:
                    CallBudget().settle(slot["id"],
                                        outcome=str(receipt.get("execution", {}).get("status")),
                                        detail={"label": args.label,
                                                "executed": bool(receipt.get("executed"))})
                    receipt["call_budget_settled"] = True
                except Exception as exc:
                    receipt["call_budget_settled"] = False
                    receipt["call_budget_settle_error"] = type(exc).__name__ + ": " + str(exc)[:200]

    receipt["finished_at"] = now()
    measured = receipt.get("runner_measured", {}).get("tests_after", {})
    receipt["task_verified"] = measured.get("exit_code") == 0
    accepted = bool(receipt.get("executed")) and receipt.get("execution", {}).get("status") == "succeeded"
    # Three different claims, recorded separately because they fail separately. Whether the task was
    # done is about the task. Whether this runner still holds the evidence for saying so is about
    # this runner, and a run that cannot show its evidence is not a run anybody should build on.
    receipt["task_succeeded"] = accepted and (receipt["mode"] == "fixture" or receipt["task_verified"])
    receipt["evidence_complete"] = bool(receipt.get("preserved", {"complete": True})["complete"])
    receipt["accepted_by_harness"] = accepted
    # A third claim, and the one an unattended caller should read. The task may have finished and
    # every copy may have been kept, and this run can still have ended somewhere it did not plan to
    # be - which means something between those two facts went unobserved.
    receipt["runner_complete"] = receipt["evidence_complete"] and not receipt.get("error")
    receipt["passed"] = receipt["task_succeeded"] and receipt["runner_complete"]
    if not receipt["runner_complete"]:
        receipt["recovery"] = {
            "error": receipt.get("error"),
            "scratch": receipt.get("workdir_cleanup", {}).get("root"),
            "destination": receipt.get("preserved", {}).get("destination"),
            "failures": receipt.get("preserved", {}).get("failures"),
            "required_failures": receipt.get("preserved", {}).get("required_failures"),
            "note": "the scratch was kept; it holds the only copy of what could not be preserved"}
    if receipt["mode"] == "fixture":
        suffix = "fixture"
    elif receipt.get("executed"):
        suffix = f"call{receipts_here(out, args.label) + 1}"
    else:
        suffix = "not-executed"  # a refusal is a record of its own, never an unnumbered call
    # The run id is in the name as well as in the body, so a repeated label writes a new receipt
    # instead of writing through one whose digests are still being quoted.
    path = out / f"{args.label}-{suffix}-{run_id}-receipt.json"
    summary = {k: receipt.get(k) for k in ("label", "run_id", "mode", "executed", "accepted_by_harness",
                                           "task_verified", "task_succeeded", "evidence_complete",
                                           "runner_complete", "passed", "not_executed_reason")}
    try:
        out.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        summary["receipt"] = str(path)
    except OSError as exc:
        # The ledger was already settled in the block above. What is left is to make sure the run
        # does not disappear quietly because its output directory refused.
        summary["receipt_write_error"] = type(exc).__name__ + ": " + str(exc)[:200]
        summary["recovery"] = receipt.get("recovery") or {
            "scratch": receipt.get("workdir_cleanup", {}).get("root")}
        print(json.dumps(summary, ensure_ascii=False))
        return 1
    print(json.dumps(summary, ensure_ascii=False))
    if not receipt["runner_complete"]:
        # The task may well have succeeded. This run cannot account for itself, which is a failure
        # of the run, and an unattended caller has to see that in the exit code.
        return 1
    return 0 if (receipt["passed"] or receipt.get("not_executed_reason")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
