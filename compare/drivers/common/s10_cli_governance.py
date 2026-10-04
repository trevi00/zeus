"""Scenario body `entry.cli_governance.pg` (REBUILD-DESIGN-v2 §5.2a, §5.3 S10 unit C7a: the audit-repair and worker-session roots).

Layer: harness (never shipped); standard library and psycopg only, and never `codex_harness`.

`api.main` (M7 `codex_harness.cli.main` or the target `codex_harness.entry.cli.main`) runs in-process with `sys.argv` patched,
against a labelled disposable PostgreSQL (`ZEUS_REBUILD_PG_DSN`), as in `entry.cli_store_b.pg`: one FRESH schema,
`HARNESS_DATABASE_URL` that DSN with `options=-c search_path=<schema>,public`, `ZEUS_REPOSITORY` a fixture directory.
Cases (after `init-db`): `audit-repair status`, `inspect` (with and without a task id), `enable` and `disable` on an unknown
audit (M7's refusal shapes: a code and a type, exit 1), `worker-session status` of an unknown task, of a seeded task that has no
session row and with no task id (the positive read: a bounded status, exit 0), and `worker-session close` of an unknown
and of a seeded task (M7's refusal). The seeded task is submitted through the side's own `Workflow` (`api.seed_task`) from a fixed six-W message,
so its id and timestamps come from the message. Every id and timestamp is fixed, so no mask is needed.
Each case records argv, the SystemExit code, parsed stdout and parsed stderr, with the fixture directory normalized to `<FIXTURE>`.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import sys
from pathlib import Path

CLEARED = ("HARNESS_", "ZEUS_", "COMPOSE_PROJECT_NAME", "CODEX_HOME", "POSTGRES_PASSWORD")
KEPT = ("ZEUS_REBUILD_",)
TASK_ID = "00000000-0000-4000-8000-0000000000c7"
AUDIT_ID = "audit-unknown"

TASK = {
    "schema_version": "1.0", "message_id": TASK_ID, "type": "task.assign",
    "correlation_id": "c-1", "causation_id": None,
    "who": {"sender": "conductor", "recipient": "lead:improvement", "owner": "lead:improvement"},
    "what": {"action": "plan", "details": {"objective": "cli governance roots"}},
    "why": {"objective": "Improve harness reliability from verified evidence", "evidence_refs": []},
    "when": {"created_at": "2026-01-01T00:00:00+00:00", "deadline": None, "after": []},
    "where": {"repository": "codex-harness", "revision": "bootstrap", "environment": "local", "allowed_paths": []},
    "how": {"constraints": [], "acceptance_criteria": ["Preserve normal behavior"],
            "context_ref": None, "result_schema": "six-w.v1"},
}


def parsed(text: str):
    try:
        return json.loads(text)
    except ValueError:
        return text


def call(main, argv: list[str], replacements: dict) -> dict:
    out, err, code = io.StringIO(), io.StringIO(), 0
    saved = sys.argv
    sys.argv = ["zeus", *argv]

    def clean(text: str) -> str:
        for old, new in replacements.items():
            text = text.replace(old, new)
        return text

    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                main()
            except SystemExit as exc:
                code = exc.code
            except Exception as exc:  # an exception main() does not catch escapes as a traceback (recorded, not hidden)
                code = "raised " + type(exc).__name__ + ": " + clean(str(exc))
    finally:
        sys.argv = saved
    return {"argv": [clean(a) for a in argv], "exit": code,
            "stdout": parsed(clean(out.getvalue())), "stderr": parsed(clean(err.getvalue()))}


def run_all(api, work: Path, dsn: str) -> dict:
    import psycopg
    from psycopg.conninfo import make_conninfo

    fixture = work / "fixture"
    fixture.mkdir(parents=True)
    (fixture / "pyproject.toml").write_text('[project]\nname = "zeus-harness"\n', encoding="utf-8")
    replacements = {str(fixture): "<FIXTURE>"}

    snapshot = dict(os.environ)
    for name in list(os.environ):
        if name.startswith(CLEARED) and not name.startswith(KEPT):
            del os.environ[name]
    os.environ["ZEUS_REPOSITORY"] = str(fixture)
    cases: dict = {}
    schema = "s10_cli_governance"

    def case(name: str, argv: list[str]) -> dict:
        cases[name] = call(api.main, argv, replacements)
        return cases[name]

    try:
        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
            conn.execute(f'CREATE SCHEMA "{schema}"')
        os.environ["HARNESS_DATABASE_URL"] = make_conninfo(dsn, options=f"-c search_path={schema},public")
        case("init_db", ["init-db"])
        case("repair_status_unknown", ["audit-repair", "status", "--audit-id", AUDIT_ID])
        case("repair_inspect_unknown", ["audit-repair", "inspect", "--audit-id", AUDIT_ID, "--task-id", TASK_ID])
        case("repair_inspect_no_task", ["audit-repair", "inspect", "--audit-id", AUDIT_ID])
        case("repair_enable_unknown", ["audit-repair", "enable", "--audit-id", AUDIT_ID, "--task-id", TASK_ID, "--operator", "op"])
        case("repair_disable_unknown", ["audit-repair", "disable", "--audit-id", AUDIT_ID, "--operator", "op"])
        case("session_status_unknown", ["worker-session", "status", "--task-id", TASK_ID])
        case("session_close_unknown", ["worker-session", "close", "--task-id", TASK_ID])
        task = api.seed_task(TASK)
        cases["seeded"] = {"id": task["id"], "status": task["status"]}
        case("session_status_seeded", ["worker-session", "status", "--task-id", TASK_ID])
        case("session_close_seeded", ["worker-session", "close", "--task-id", TASK_ID])
        case("session_status_all", ["worker-session", "status"])
        case("repair_enable_seeded", ["audit-repair", "enable", "--audit-id", AUDIT_ID, "--task-id", TASK_ID, "--operator", "op"])
    finally:
        os.environ.clear()
        os.environ.update(snapshot)
        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
    return {"cases": cases}
