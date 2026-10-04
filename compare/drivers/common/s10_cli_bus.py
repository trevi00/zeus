"""Scenario body `entry.cli_bus.pgredis` (REBUILD-DESIGN-v2 §5.2a, §5.3 S10 unit C4: the bus/observer roots flush, send, observe, doctor online).

Layer: harness (never shipped); standard library and psycopg only, and never `codex_harness`.

`api.main` (M7 `codex_harness.cli.main` or the target `codex_harness.entry.cli.main`) runs in-process with `sys.argv`
patched, against a labelled disposable PostgreSQL (`ZEUS_REBUILD_PG_DSN`) AND a labelled disposable Redis
(`ZEUS_REBUILD_REDIS_URL`, rule R-c7): `HARNESS_DATABASE_URL` is that DSN with `options=-c search_path=<schema>,public` on
one FRESH schema (dropped at the end), `HARNESS_REDIS_URL` is the Redis URL and `HARNESS_REDIS_NAMESPACE` is unique per run.
Cases, after `init-db`: `doctor` (online), `flush_empty`, `send` (the stream id, chosen by the Redis server, is normalized
in-driver to `<STREAM_ID>`), `observe_status` and `observe_collect` on an empty spool, and `observe_reconcile_unknown`
(M7's refusal). Each records argv, the SystemExit code, parsed stdout and parsed stderr, the fixture directory path
normalized to `<FIXTURE>`. No mask is declared.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import re
import sys
import uuid
from pathlib import Path

CLEARED = ("HARNESS_", "ZEUS_", "COMPOSE_PROJECT_NAME", "CODEX_HOME", "POSTGRES_PASSWORD")
KEPT = ("ZEUS_REBUILD_",)
TASK_ID = "00000000-0000-4000-8000-0000000000c4"
STREAM_ID = re.compile(r"^\d+-\d+$")

MESSAGE = {
    "schema_version": "1.0", "message_id": TASK_ID, "type": "task.assign",
    "correlation_id": "c-1", "causation_id": None,
    "who": {"sender": "conductor", "recipient": "lead:improvement", "owner": "lead:improvement"},
    "what": {"action": "plan", "details": {"objective": "cli bus roots"}},
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


def run_all(api, work: Path, dsn: str, redis_url: str) -> dict:
    import psycopg
    from psycopg.conninfo import make_conninfo

    fixture = work / "fixture"
    fixture.mkdir(parents=True)
    (fixture / "pyproject.toml").write_text('[project]\nname = "zeus-harness"\n', encoding="utf-8")
    message = fixture / "message.json"
    message.write_text(json.dumps(MESSAGE), encoding="utf-8")

    snapshot = dict(os.environ)
    for name in list(os.environ):
        if name.startswith(CLEARED) and not name.startswith(KEPT):
            del os.environ[name]
    os.environ["ZEUS_REPOSITORY"] = str(fixture)
    os.environ["HARNESS_REDIS_URL"] = redis_url
    os.environ["HARNESS_REDIS_NAMESPACE"] = "s10c4-" + uuid.uuid4().hex[:12]
    cases: dict = {}
    schema = "s10_cli_bus"

    def case(name: str, argv: list[str]) -> dict:
        cases[name] = call(api.main, argv, str(fixture))
        return cases[name]

    try:
        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
            conn.execute(f'CREATE SCHEMA "{schema}"')
        os.environ["HARNESS_DATABASE_URL"] = make_conninfo(dsn, options=f"-c search_path={schema},public")
        case("init_db", ["init-db"])
        case("doctor", ["doctor"])
        case("flush_empty", ["flush"])
        sent = case("send", ["send", str(message)])
        if isinstance(sent["stdout"], dict) and STREAM_ID.match(str(sent["stdout"].get("stream_id"))):
            sent["stdout"]["stream_id"] = "<STREAM_ID>"
        case("observe_status", ["observe", "status"])
        case("observe_collect", ["observe", "collect"])
        case("observe_reconcile_unknown", ["observe", "reconcile", "no-such-record", "--resolution", "discard",
                                            "--operator", "op", "--reason", "r"])
    finally:
        os.environ.clear()
        os.environ.update(snapshot)
        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
    return {"cases": cases}
