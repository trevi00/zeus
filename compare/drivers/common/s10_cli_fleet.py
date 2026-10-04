"""Scenario body `entry.cli_fleet.pg` (REBUILD-DESIGN-v2 §5.2a, §5.3 S10 unit C8b-2: the fleet root).

Layer: harness (never shipped); standard library and psycopg only, and never `codex_harness`.

`api.main` (M7 `codex_harness.cli.main` or the target `codex_harness.entry.cli.main`) runs in-process with `sys.argv` patched,
against a labelled disposable PostgreSQL (`ZEUS_REBUILD_PG_DSN`), as in `entry.cli_continuation.pg`: one FRESH schema,
`HARNESS_DATABASE_URL` that DSN with `options=-c search_path=<schema>,public`, `ZEUS_REPOSITORY` a fixture directory (a pyproject only)
and `HARNESS_RUNTIME_DIR` a fixture runtime directory. `api.environment` is what the side adds to the environment (the target sets
`ZEUS_COMPOSITION_PROFILE=development`: declared difference E-c21, OWNER-DECISIONS-S10 #10). No provider, process, Docker, journal or
lane store is reached: every case refuses or reads the control store before one.
Cases (after `init-db`): `fleet status` with no fleet; `register` of a file that is not JSON, of a configuration whose repository goes
through a symbolic link (`path_unresolved`) and of a configuration whose repository directory is absent (`repository_missing`);
`enqueue`, `record-delivery`, `authorize-budget`, `pause`, `resume` and `reconcile-interrupted`, `relocate` and `migrate-host` of an
unregistered fleet; `backlog status` (every plan, and an unknown plan: exit 1); then a valid `register` over fixture lane directories
(the work directory is a fixed path on both sides, so the digests are equal), `status`, `enqueue` on an unknown lane and
`authorize-budget` with a stale expected total. The positive `run` and the process cases are the unit tests' (MemoryStore).
Each records argv, the SystemExit code, parsed stdout and parsed stderr, with the fixture directories normalized.
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
FIXED_WORK = "/tmp/zeus-s10-c8b2-fleet"


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


def fleet_config(lanes: Path, repository: str | None = None) -> dict:
    """A valid urn:zeus:fleet:1 document over fixture lane directories (`repository` overrides lane a's repository path)."""
    return {"schema": "urn:zeus:fleet:1", "id": "fleet-c8b2", "max_parallel": 2, "budget": {"per_host": 2, "total": 4},
            "lanes": [{"id": name, "team": "team-" + name, "repository": repository if (repository and name == "a")
                       else str(lanes / name / "repo"), "schema": "lane_" + name, "redis_namespace": "ns-" + name,
                       "runtime": str(lanes / name / "runtime")} for name in ("a", "b")]}


def run_all(api, work: Path, dsn: str) -> dict:
    import psycopg
    from psycopg.conninfo import make_conninfo

    fixture = work / "fixture"
    fixture.mkdir(parents=True)
    build_fixture(fixture)
    runtime = work / "runtime"
    files = work / "documents"
    files.mkdir()
    lanes = work / "lanes"
    for name in ("a", "b"):
        (lanes / name / "repo").mkdir(parents=True)
    (work / "real").mkdir()
    (work / "link").symlink_to(work / "real")
    bad_json = files / "invalid.json"
    bad_json.write_text("{not json", encoding="utf-8")
    empty = files / "empty.json"
    empty.write_text("{}", encoding="utf-8")
    unresolved = files / "unresolved.json"
    unresolved.write_text(json.dumps(fleet_config(lanes, str(work / "link"))), encoding="utf-8")
    missing = files / "missing.json"
    missing.write_text(json.dumps(fleet_config(lanes, str(work / "absent"))), encoding="utf-8")
    valid = files / "valid.json"
    valid.write_text(json.dumps(fleet_config(lanes)), encoding="utf-8")
    journal = work / "journal.log"
    replacements = {str(files): "<DOCUMENTS>", str(lanes): "<LANES>", str(work): "<WORK>"}

    snapshot = dict(os.environ)
    for name in list(os.environ):
        if name.startswith(CLEARED) and not name.startswith(KEPT):
            del os.environ[name]
    os.environ.update(api.environment)
    os.environ["ZEUS_REPOSITORY"] = str(fixture)
    os.environ["HARNESS_RUNTIME_DIR"] = str(runtime)
    cases: dict = {}
    schema = "s10_cli_fleet"

    def case(name: str, argv: list[str]) -> dict:
        cases[name] = call(api.main, argv, replacements)
        return cases[name]

    try:
        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
            conn.execute(f'CREATE SCHEMA "{schema}"')
        os.environ["HARNESS_DATABASE_URL"] = make_conninfo(dsn, options=f"-c search_path={schema},public")
        case("init_db", ["init-db"])
        case("status_no_fleet", ["fleet", "status"])
        case("register_invalid_json", ["fleet", "register", "--file", str(bad_json)])
        case("register_path_unresolved", ["fleet", "register", "--file", str(unresolved)])
        case("register_repository_missing", ["fleet", "register", "--file", str(missing)])
        case("enqueue_no_fleet", ["fleet", "enqueue", "--lane", "x", "--file", str(bad_json)])
        case("pause_no_fleet", ["fleet", "pause"])
        case("resume_no_fleet", ["fleet", "resume"])
        case("record_delivery_unknown_job", ["fleet", "record-delivery", "--job", "nope", "--file", str(empty)])
        case("backlog_status_all", ["fleet", "backlog", "status"])
        case("backlog_status_unknown_plan", ["fleet", "backlog", "status", "--plan", "nope"])
        case("authorize_budget_no_fleet", ["fleet", "authorize-budget", "--per-host", "1", "--total", "1",
                                           "--expected-total", "1"])
        case("reconcile_interrupted_no_fleet", ["fleet", "reconcile-interrupted", "--file", str(bad_json)])
        case("relocate_invalid_json", ["fleet", "relocate", "--file", str(bad_json), "--journal", str(journal)])
        case("migrate_host_invalid_json", ["fleet", "migrate-host", "--file", str(bad_json), "--journal", str(journal)])
        case("register_valid", ["fleet", "register", "--file", str(valid)])
        case("status_registered", ["fleet", "status"])
        case("enqueue_unknown_lane", ["fleet", "enqueue", "--lane", "x", "--file", str(bad_json)])
        case("authorize_budget_expected_mismatch", ["fleet", "authorize-budget", "--per-host", "3", "--total", "5",
                                                    "--expected-total", "1"])
    finally:
        os.environ.clear()
        os.environ.update(snapshot)
        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
    return {"cases": cases}
