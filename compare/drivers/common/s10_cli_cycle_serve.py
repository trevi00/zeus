"""Scenario body `entry.cli_cycle_serve.pgredis` (REBUILD-DESIGN-v2 §5.2a, §5.3 S10 unit C5e: the cycle and serve roots).

Layer: harness (never shipped); standard library and psycopg only, and never `codex_harness`.

`api.main` (M7 `codex_harness.cli.main` or the target `codex_harness.entry.cli.main`) runs in-process with `sys.argv`
patched, against a labelled disposable PostgreSQL (`ZEUS_REBUILD_PG_DSN`) AND a labelled disposable Redis
(`ZEUS_REBUILD_REDIS_URL`, rule R-c7), as in `entry.cli_bus.pgredis`: `HARNESS_DATABASE_URL` is that DSN with
`options=-c search_path=<schema>,public` on one FRESH schema (dropped at the end), `HARNESS_REDIS_URL` is the Redis URL and
`HARNESS_REDIS_NAMESPACE` is unique per run. `api.environment` is what the side adds to the environment (the target sets
`ZEUS_COMPOSITION_PROFILE=development`: declared difference E-c21, OWNER-DECISIONS-S10 #10; M7 had no profile) and
`api.scripted()` a context manager the side supplies: the `utcnow` of the local cycle and the process run id of the
observer are replaced by a ticking clock and a counter (drawn in the same order on both sides), so no mask is needed.
Cases, after `init-db`: `cycle_start`, `cycle_status`, `cycle_handoff`, `cycle_step` (an empty queue), `cycle_status_unknown`
(M7's refusal) and `serve_once` (`serve --agent lead:improvement --once` on an empty stream; M7's `--once` breaks after one
receive turn). Each records argv, the SystemExit code, parsed stdout and parsed stderr, the fixture path normalized to
<FIXTURE>. No mask is declared.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import uuid
from pathlib import Path

CLEARED = ("HARNESS_", "ZEUS_", "COMPOSE_PROJECT_NAME", "CODEX_HOME", "POSTGRES_PASSWORD")
KEPT = ("ZEUS_REBUILD_",)


def parsed(text: str):
    try:
        return json.loads(text)
    except ValueError:
        pass
    # `serve` prints several JSON documents (indent=2); a stream of them is kept as a list of documents.
    documents, decoder, position = [], json.JSONDecoder(), 0
    while position < len(text):
        while position < len(text) and text[position].isspace():
            position += 1
        if position >= len(text):
            break
        try:
            document, position = decoder.raw_decode(text, position)
        except ValueError:
            return text
        documents.append(document)
    return documents or text


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
            except Exception as exc:  # an exception main() does not catch escapes as a traceback (recorded, not hidden)
                code = "raised " + type(exc).__name__ + ": " + str(exc).replace(prefix, "<FIXTURE>")
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
    os.environ["ZEUS_REPOSITORY"] = str(fixture)
    os.environ["HARNESS_REDIS_URL"] = redis_url
    os.environ["HARNESS_REDIS_NAMESPACE"] = "s10c5e-" + uuid.uuid4().hex[:12]
    os.environ["HARNESS_RUNTIME_DIR"] = str(fixture / "rt")
    os.environ.update(api.environment)
    cases: dict = {}
    schema = "s10_cli_cycle_serve"

    def case(name: str, argv: list[str]) -> dict:
        cases[name] = call(api.main, argv, str(fixture))
        return cases[name]

    try:
        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
            conn.execute(f'CREATE SCHEMA "{schema}"')
        os.environ["HARNESS_DATABASE_URL"] = make_conninfo(dsn, options=f"-c search_path={schema},public")
        with api.scripted():
            case("init_db", ["init-db"])
            case("cycle_start", ["cycle", "start", "c1", "--correlation", "c", "--max-executions", "2"])
            case("cycle_status", ["cycle", "status", "c1"])
            case("cycle_handoff", ["cycle", "handoff", "c1"])
            case("cycle_step", ["cycle", "step", "c1"])
            case("cycle_status_unknown", ["cycle", "status", "no-such-cycle"])
            case("serve_once", ["serve", "--agent", "lead:improvement", "--once"])
    finally:
        os.environ.clear()
        os.environ.update(snapshot)
        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
    return {"cases": cases}
