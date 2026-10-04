"""Scenario body `entry.cli_continuation.pg` (REBUILD-DESIGN-v2 §5.2a, §5.3 S10 unit C8b-1: the continuation root).

Layer: harness (never shipped); standard library and psycopg only, and never `codex_harness`.

`api.main` (M7 `codex_harness.cli.main` or the target `codex_harness.entry.cli.main`) runs in-process with `sys.argv` patched,
against a labelled disposable PostgreSQL (`ZEUS_REBUILD_PG_DSN`), as in `entry.cli_desk_program.pg`: one FRESH schema,
`HARNESS_DATABASE_URL` that DSN with `options=-c search_path=<schema>,public`, `ZEUS_REPOSITORY` a fixture directory (a pyproject only)
and `HARNESS_RUNTIME_DIR` a fixture runtime directory. `api.environment` is what the side adds to the environment (the target sets
`ZEUS_COMPOSITION_PROFILE=development`: declared difference E-c21, OWNER-DECISIONS-S10 #10). No provider, process, lane store or Git
read is reached: every case refuses or reads the control store before one.
Cases (after `init-db`): `status` of an unknown policy and of none (the empty projection), `identity` and `register` and `tick` with
no registered fleet, `research-accept`, `research-supplement`, `capacity-grant` and `delivery-requalify` of a file that is not JSON
(M7 reads the Fleet config first, so the refusal is the unregistered fleet's, not the receipt's), and `ownership-reconcile` of an unknown intent.
No positive case beyond the two reads: registering a fleet is the `fleet` root (S10 unit C8b-2), and the unit tests cover the receipt
refusals over a MemoryStore.
Each records argv, the SystemExit code, parsed stdout and parsed stderr, with the fixture and runtime directories normalized.
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
FIXED_WORK = "/tmp/zeus-s10-c8b1-continuation"


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


def build_fixture(fixture: Path) -> None:
    (fixture / "pyproject.toml").write_text('[project]\nname = "zeus-harness"\n', encoding="utf-8")


def run_all(api, work: Path, dsn: str) -> dict:
    import psycopg
    from psycopg.conninfo import make_conninfo

    fixture = work / "fixture"
    fixture.mkdir(parents=True)
    build_fixture(fixture)
    runtime = work / "runtime"
    files = work / "documents"
    files.mkdir()
    bad_json = files / "invalid.json"
    bad_json.write_text("{not json", encoding="utf-8")
    replacements = {str(files): "<DOCUMENTS>", str(fixture): "<FIXTURE>", str(runtime): "<RUNTIME>"}

    snapshot = dict(os.environ)
    for name in list(os.environ):
        if name.startswith(CLEARED) and not name.startswith(KEPT):
            del os.environ[name]
    os.environ.update(api.environment)
    os.environ["ZEUS_REPOSITORY"] = str(fixture)
    os.environ["HARNESS_RUNTIME_DIR"] = str(runtime)
    cases: dict = {}
    schema = "s10_cli_continuation"

    def case(name: str, argv: list[str]) -> dict:
        cases[name] = call(api.main, argv, replacements)
        return cases[name]

    try:
        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
            conn.execute(f'CREATE SCHEMA "{schema}"')
        os.environ["HARNESS_DATABASE_URL"] = make_conninfo(dsn, options=f"-c search_path={schema},public")
        case("init_db", ["init-db"])
        case("status_unknown_policy", ["continuation", "status", "--policy", "nope"])
        case("status_all", ["continuation", "status"])
        case("identity_no_fleet", ["continuation", "identity", "--lane", "x"])
        case("register_no_fleet", ["continuation", "register", "--lane", "x", "--revision", "0" * 40, "--path", "p"])
        case("research_accept_invalid_json", ["continuation", "research-accept", "--file", str(bad_json)])
        case("research_supplement_invalid_json", ["continuation", "research-supplement", "--file", str(bad_json)])
        case("capacity_grant_invalid_json", ["continuation", "capacity-grant", "--file", str(bad_json)])
        case("delivery_requalify_invalid_json", ["continuation", "delivery-requalify", "--file", str(bad_json)])
        case("tick_no_fleet", ["continuation", "tick", "--policy", "nope"])
        case("ownership_reconcile_unknown_intent", ["continuation", "ownership-reconcile", "--intent", "nope"])
    finally:
        os.environ.clear()
        os.environ.update(snapshot)
        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
    return {"cases": cases}
