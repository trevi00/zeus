"""Scenario body `entry.cli_store.pg` (REBUILD-DESIGN-v2 §5.2a, §5.3 S10 unit C2a: the store roots init-db, status, inspect, cancel, release-retry, goal).

Layer: harness (never shipped); standard library and psycopg only, and never `codex_harness`.

`api.main` (M7 `codex_harness.cli.main` or the target `codex_harness.entry.cli.main`) runs in-process with `sys.argv`
patched, against a labelled disposable PostgreSQL (`ZEUS_REBUILD_PG_DSN`): `HARNESS_DATABASE_URL` is that DSN with
`options=-c search_path=<schema>,public`, one FRESH schema per case group (dropped at the end). `api.seed(message)` submits
a task through the side's own Workflow on the database named by `HARNESS_DATABASE_URL`.
Cases: `init_db_first` / `init_db_second` (applied, then already_applied); `status`, `inspect_tasks`, `cancel_unknown`,
`release_retry_unknown`, `goal_report` on the migrated empty schema; `goal_compare` of two reports (store-free: no database
variable set); `cancel_seeded` then `inspect_tasks_after` (id and status of the seeded task); `status_no_database_url`.
Each case records argv, the SystemExit code, parsed stdout and parsed stderr, the fixture directory path normalized to `<FIXTURE>` (as in
`entry.cli_storefree`). No mask is declared: every message id is fixed,
and the one nondeterministic field (a task's `created_at`) is not read.
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
TASK_ID = "00000000-0000-4000-8000-0000000000c2"

MESSAGE = {
    "schema_version": "1.0", "message_id": TASK_ID, "type": "task.assign",
    "correlation_id": "c-1", "causation_id": None,
    "who": {"sender": "conductor", "recipient": "lead:improvement", "owner": "lead:improvement"},
    "what": {"action": "plan", "details": {"objective": "cli store roots"}},
    "why": {"objective": "Improve harness reliability from verified evidence", "evidence_refs": []},
    "when": {"created_at": "2026-01-01T00:00:00+00:00", "deadline": None, "after": []},
    "where": {"repository": "codex-harness", "revision": "bootstrap", "environment": "local", "allowed_paths": []},
    "how": {"constraints": [], "acceptance_criteria": ["Preserve normal behavior"],
            "context_ref": None, "result_schema": "six-w.v1"},
}

MANIFEST = {
    "version": 1, "id": "goal-c2a", "objective": "Observe one criterion", "non_goals": [],
    "criteria": [{"id": "c1", "acceptance": "ticket closes", "ticket_id": "T-C2A", "revision": 1,
                  "content_hash": "0" * 64}],
}


def parsed(text: str):
    try:
        return json.loads(text)
    except ValueError:
        return text


def call(main, argv: list[str], prefix: str) -> dict:
    out, err, code = io.StringIO(), io.StringIO(), 0
    saved = sys.argv
    sys.argv = ["zeus", *argv]
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                main()
            except SystemExit as exc:
                code = exc.code
    finally:
        sys.argv = saved
    return {"argv": [a.replace(prefix, "<FIXTURE>") for a in argv], "exit": code,
            "stdout": parsed(out.getvalue().replace(prefix, "<FIXTURE>")),
            "stderr": parsed(err.getvalue().replace(prefix, "<FIXTURE>"))}


def run_all(api, work: Path, dsn: str) -> dict:
    import psycopg
    from psycopg.conninfo import make_conninfo

    fixture = work / "fixture"
    fixture.mkdir(parents=True)
    (fixture / "pyproject.toml").write_text('[project]\nname = "zeus-harness"\n', encoding="utf-8")
    manifest = fixture / "manifest.json"
    manifest.write_text(json.dumps(MANIFEST), encoding="utf-8")

    snapshot = dict(os.environ)
    for name in list(os.environ):
        if name.startswith(CLEARED) and not name.startswith(KEPT):
            del os.environ[name]
    os.environ["ZEUS_REPOSITORY"] = str(fixture)
    cases: dict = {}
    schemas: list[str] = []

    def fresh(schema: str) -> None:
        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
            conn.execute(f'CREATE SCHEMA "{schema}"')
        schemas.append(schema)
        os.environ["HARNESS_DATABASE_URL"] = make_conninfo(dsn, options=f"-c search_path={schema},public")

    def case(name: str, argv: list[str]) -> dict:
        cases[name] = call(api.main, argv, str(fixture))
        return cases[name]

    try:
        fresh("s10_cli_store_init")
        case("init_db_first", ["init-db"])
        case("init_db_second", ["init-db"])

        fresh("s10_cli_store_empty")
        case("init_db_empty_schema", ["init-db"])
        case("status", ["status"])
        case("inspect_tasks", ["inspect", "tasks"])
        case("cancel_unknown", ["cancel", "no-such-task", "--reason", "r"])
        case("release_retry_unknown", ["release-retry", "no-such-release", "--reason", "r"])
        report = case("goal_report", ["goal", "report", str(manifest)])
        before = fixture / "before.json"
        before.write_text(json.dumps(report["stdout"]), encoding="utf-8")
        del os.environ["HARNESS_DATABASE_URL"]
        case("goal_compare", ["goal", "compare", str(before), str(before)])
        case("status_no_database_url", ["status"])

        fresh("s10_cli_store_seeded")
        case("init_db_seeded", ["init-db"])
        task = api.seed(MESSAGE)
        cases["seeded"] = {"id": task["id"], "status": task["status"]}
        case("cancel_seeded", ["cancel", TASK_ID, "--reason", "r"])
        inspected = case("inspect_tasks_after", ["inspect", "tasks"])
        inspected["stdout"] = [{"id": t["id"], "status": t["status"]} for t in inspected["stdout"]]
    finally:
        os.environ.clear()
        os.environ.update(snapshot)
        with psycopg.connect(dsn, autocommit=True) as conn:
            for schema in schemas:
                conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
    return {"cases": cases}
