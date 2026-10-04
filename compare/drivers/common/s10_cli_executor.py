"""Scenario body `entry.cli_executor.pgredis` (REBUILD-DESIGN-v2 §5.2a, §5.3 S10 unit C5d: the seven executor roots).

Layer: harness (never shipped); standard library and psycopg only, and never `codex_harness`.

`api.main` (M7 `codex_harness.cli.main` or the target `codex_harness.entry.cli.main`) runs in-process with `sys.argv`
patched, against a labelled disposable PostgreSQL (`ZEUS_REBUILD_PG_DSN`) AND a labelled disposable Redis
(`ZEUS_REBUILD_REDIS_URL`, rule R-c7), as in `entry.cli_bus.pgredis`: `HARNESS_DATABASE_URL` is that DSN with
`options=-c search_path=<schema>,public` on one FRESH schema (dropped at the end), `HARNESS_REDIS_URL` is the Redis URL and
`HARNESS_REDIS_NAMESPACE` is unique per run. `ZEUS_REPOSITORY` is a fixture git repository with one commit whose author,
committer and dates are pinned (`GIT_*`), so `rev-parse HEAD` is the same on both sides.
`api.environment` is what the side adds to the environment (the target sets `ZEUS_COMPOSITION_PROFILE=development`: declared
difference E-c21, OWNER-DECISIONS-S10 #10; M7 had no profile) and `api.scripted()` a context manager the side supplies: the
`uuid4` draws and the `utcnow` of the published message are replaced by a counter and a ticking clock (one shared stream per
side, drawn in the same order), so every id and timestamp is fixed and no mask is needed.
Cases, after `init-db`: `execute_one_idle` (an empty queue: M7's idle status), `artifact_unknown` and `release_abandon_unknown`
and `rebase_unknown` (M7's refusals), `cleanup_dry` (an empty store, no `--apply`; under `scripted()`: the result's wall-clock `at`), `research` and `improve` (the published
message; the stream id, chosen by the Redis server, is normalized in-driver to `<STREAM_ID>`). Each records argv, the
SystemExit code, parsed stdout and parsed stderr, the fixture directory path normalized to `<FIXTURE>`. No mask is declared.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import re
import subprocess
import sys
import uuid
from pathlib import Path

CLEARED = ("HARNESS_", "ZEUS_", "COMPOSE_PROJECT_NAME", "CODEX_HOME", "POSTGRES_PASSWORD", "GIT_")
KEPT = ("ZEUS_REBUILD_",)
STREAM_ID = re.compile(r"^\d+-\d+$")
GIT = {"GIT_AUTHOR_NAME": "zeus", "GIT_AUTHOR_EMAIL": "zeus@example.invalid", "GIT_AUTHOR_DATE": "2026-01-01T00:00:00+00:00",
       "GIT_COMMITTER_NAME": "zeus", "GIT_COMMITTER_EMAIL": "zeus@example.invalid",
       "GIT_COMMITTER_DATE": "2026-01-01T00:00:00+00:00", "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1"}

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

    snapshot = dict(os.environ)
    for name in list(os.environ):
        if name.startswith(CLEARED) and not name.startswith(KEPT):
            del os.environ[name]
    os.environ.update(GIT)
    os.environ["ZEUS_REPOSITORY"] = str(fixture)
    os.environ["HARNESS_REDIS_URL"] = redis_url
    os.environ["HARNESS_REDIS_NAMESPACE"] = "s10c5d-" + uuid.uuid4().hex[:12]
    os.environ["HARNESS_RUNTIME_DIR"] = str(fixture / "rt")
    os.environ.update(getattr(api, "environment", {}))
    for argv in (["init"], ["add", "."], ["commit", "-m", "fixture"]):
        subprocess.run(["git", *argv], cwd=fixture, check=True, capture_output=True)
    cases: dict = {}
    schema = "s10_cli_executor"

    def case(name: str, argv: list[str]) -> dict:
        cases[name] = call(api.main, argv, str(fixture))
        return cases[name]

    def published(entry: dict) -> None:
        if isinstance(entry["stdout"], dict) and STREAM_ID.match(str(entry["stdout"].get("stream_id"))):
            entry["stdout"]["stream_id"] = "<STREAM_ID>"

    try:
        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
            conn.execute(f'CREATE SCHEMA "{schema}"')
        os.environ["HARNESS_DATABASE_URL"] = make_conninfo(dsn, options=f"-c search_path={schema},public")
        case("init_db", ["init-db"])
        case("execute_one_idle", ["execute-one", "--agent", "worker:implementation"])
        case("artifact_unknown", ["artifact", "no-such-artifact"])
        case("release_abandon_unknown", ["release-abandon", "no-such-release", "--reason", "r"])
        case("rebase_unknown", ["rebase", "no-such-task", "--onto", "HEAD"])
        with api.scripted():
            case("cleanup_dry", ["cleanup"])
            published(case("research", ["research", "github", "--intent", "proactive"]))
            published(case("improve", ["improve", "objective", "--acceptance", "accepted"]))
    finally:
        os.environ.clear()
        os.environ.update(snapshot)
        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
    return {"cases": cases}
