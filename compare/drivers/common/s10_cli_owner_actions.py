"""Scenario body `entry.cli_owner_actions.pg` (REBUILD-DESIGN-v2 §5.2a, §5.3 S10 unit C8b-3: the owner-actions root).

Layer: harness (never shipped); standard library and psycopg only, and never `codex_harness`.

`api.main` (M7 `codex_harness.cli.main` or the target `codex_harness.entry.cli.main`) runs in-process with `sys.argv` patched,
against a labelled disposable PostgreSQL (`ZEUS_REBUILD_PG_DSN`), as in `entry.cli_host_delivery.pg`: one FRESH schema,
`HARNESS_DATABASE_URL` that DSN with `options=-c search_path=<schema>,public`, `ZEUS_REPOSITORY` a fixture directory (a pyproject
only, no Git history) and `HARNESS_RUNTIME_DIR` a fixture runtime directory. `api.environment` is what the side adds to the
environment (the target sets `ZEUS_COMPOSITION_PROFILE=development`: declared difference E-c21, OWNER-DECISIONS-S10 #10). No
provider, process, Docker, GitHub or host target is reached.
Cases (after `init-db`): `status` with nothing registered (every policy and an unknown policy); `assess` of a decision that is no
owner-assessment row; `register`, `tick`, `run`, `migrate` and `canary-recover` with no registered fleet; then a valid `fleet
register` and `migrate` and `canary-recover` with a file that is not JSON, `register` of an unknown lane and of a registered lane
whose repository has no Git history, `run` with a repeated `--policy`, and the positive cases `tick` and `run --max-ticks 1` of a
policy nothing registered (an idle receipt) and `status` after the fleet is registered. Each records argv, the SystemExit code,
parsed stdout and parsed stderr, with the fixture directories normalized.
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
FIXED_WORK = "/tmp/zeus-s10-c8b3-owner-actions"
EVIDENCE = "sha256:" + "e" * 64


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


def fleet_config(lanes: Path) -> dict:
    """A valid urn:zeus:fleet:1 document over fixture lane directories."""
    return {"schema": "urn:zeus:fleet:1", "id": "fleet-c8b3", "max_parallel": 2, "budget": {"per_host": 2, "total": 4},
            "lanes": [{"id": name, "team": "team-" + name, "repository": str(lanes / name / "repo"),
                       "schema": "lane_" + name, "redis_namespace": "ns-" + name,
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
    bad_json = files / "invalid.json"
    bad_json.write_text("{not json", encoding="utf-8")
    fleet = files / "fleet.json"
    fleet.write_text(json.dumps(fleet_config(lanes)), encoding="utf-8")
    replacements = {str(files): "<DOCUMENTS>", str(lanes): "<LANES>", str(work): "<WORK>"}

    snapshot = dict(os.environ)
    for name in list(os.environ):
        if name.startswith(CLEARED) and not name.startswith(KEPT):
            del os.environ[name]
    os.environ.update(api.environment)
    os.environ["ZEUS_REPOSITORY"] = str(fixture)
    os.environ["HARNESS_RUNTIME_DIR"] = str(runtime)
    cases: dict = {}
    schema = "s10_cli_owner_actions"
    owner = ["owner-actions"]

    def case(name: str, argv: list[str]) -> dict:
        cases[name] = call(api.main, argv, replacements)
        return cases[name]

    try:
        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
            conn.execute(f'CREATE SCHEMA "{schema}"')
        os.environ["HARNESS_DATABASE_URL"] = make_conninfo(dsn, options=f"-c search_path={schema},public")
        case("init_db", ["init-db"])
        case("status_empty", [*owner, "status"])
        case("status_unknown_policy", [*owner, "status", "--policy", "nope"])
        case("assess_foreign_row", [*owner, "assess", "--decision", "d-x", "--correlation", "c-x"])
        case("register_no_fleet", [*owner, "register", "--lane", "a", "--revision", "a" * 40, "--path", "policy.json"])
        case("tick_no_fleet", [*owner, "tick", "--policy", "p"])
        case("run_no_fleet", [*owner, "run", "--policy", "p", "--max-ticks", "1"])
        case("migrate_no_fleet", [*owner, "migrate", "--document", str(bad_json)])
        case("canary_recover_no_fleet", [*owner, "canary-recover", "--document", str(bad_json), "--evidence", EVIDENCE])
        case("fleet_register_valid", ["fleet", "register", "--file", str(fleet)])
        case("migrate_invalid_json", [*owner, "migrate", "--document", str(bad_json)])
        case("migrate_missing_file", [*owner, "migrate", "--document", str(files / "absent.json")])
        case("canary_recover_invalid_json", [*owner, "canary-recover", "--document", str(bad_json), "--evidence", EVIDENCE])
        case("register_unknown_lane", [*owner, "register", "--lane", "nope", "--revision", "a" * 40, "--path", "policy.json"])
        case("register_lane_no_git", [*owner, "register", "--lane", "a", "--revision", "a" * 40, "--path", "policy.json"])
        case("run_repeated_policy", [*owner, "run", "--policy", "p", "--policy", "p", "--max-ticks", "1"])
        case("tick_unregistered_policy", [*owner, "tick", "--policy", "p"])
        case("run_once_unregistered_policy", [*owner, "run", "--policy", "p", "--max-ticks", "1"])
        case("status_after_fleet", [*owner, "status"])
    finally:
        os.environ.clear()
        os.environ.update(snapshot)
        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
    return {"cases": cases}
