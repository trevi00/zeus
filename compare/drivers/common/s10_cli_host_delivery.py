"""Scenario body `entry.cli_host_delivery.pg` (REBUILD-DESIGN-v2 §5.2a, §5.3 S10 unit C8b-4: the host-delivery root).

Layer: harness (never shipped); standard library and psycopg only, and never `codex_harness`.

`api.main` (M7 `codex_harness.cli.main` or the target `codex_harness.entry.cli.main`) runs in-process with `sys.argv` patched,
against a labelled disposable PostgreSQL (`ZEUS_REBUILD_PG_DSN`), as in `entry.cli_fleet.pg`: one FRESH schema, `HARNESS_DATABASE_URL`
that DSN with `options=-c search_path=<schema>,public`, `ZEUS_REPOSITORY` a fixture directory (a pyproject only, no Git history) and
`HARNESS_RUNTIME_DIR` a fixture runtime directory. `api.environment` is what the side adds to the environment (the target sets
`ZEUS_COMPOSITION_PROFILE=development`: declared difference E-c21, OWNER-DECISIONS-S10 #10). The delivery opt-in is not set, so no
provider, process, Docker, GitHub, systemd or host target is reached.
Cases (after `init-db`): `host-delivery status` with nothing registered (every plan, and an unknown plan: exit 1); `register-targets` and
`resume --document` with a file that is not JSON; `run --once` (one idle tick), `withdraw`, `resume` (no document) and `register` on an empty store (`tick` alone is a unit test: its receipt carries a clock reading and no mask exists);
`status`, `register-targets` and `tick` on a `--lane` route with no registered fleet; then a valid `fleet register`, the `--lane` routes of
an unknown lane and of a registered lane whose schema is not provisioned, and a valid `register-targets` with its `status` (the one
positive case: a process-kind target of the registry, the fixture paths normalized). Each records argv, the SystemExit code, parsed
stdout and parsed stderr, with the fixture directories normalized.
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
FIXED_WORK = "/tmp/zeus-s10-c8b4-host-delivery"
SHA = "c" * 64
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
    return {"schema": "urn:zeus:fleet:1", "id": "fleet-c8b4", "max_parallel": 2, "budget": {"per_host": 2, "total": 4},
            "lanes": [{"id": name, "team": "team-" + name, "repository": str(lanes / name / "repo"),
                       "schema": "lane_" + name, "redis_namespace": "ns-" + name,
                       "runtime": str(lanes / name / "runtime")} for name in ("a", "b")]}


def targets_document(work: Path) -> dict:
    return {"schema": "urn:zeus:host-delivery-targets:1",
            "targets": [{"target_id": "fixture-process", "kind": "process", "root": str(work / "target-root"),
                         "state_dir": str(work / "target-state"), "service": "zeus-canary"}]}


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
    targets = files / "targets.json"
    targets.write_text(json.dumps(targets_document(work)), encoding="utf-8")
    replacements = {str(files): "<DOCUMENTS>", str(lanes): "<LANES>", str(work): "<WORK>"}

    snapshot = dict(os.environ)
    for name in list(os.environ):
        if name.startswith(CLEARED) and not name.startswith(KEPT):
            del os.environ[name]
    os.environ.update(api.environment)
    os.environ["ZEUS_REPOSITORY"] = str(fixture)
    os.environ["HARNESS_RUNTIME_DIR"] = str(runtime)
    cases: dict = {}
    schema = "s10_cli_host_delivery"
    delivery = ["host-delivery"]
    owner = ["--plan", "plan-x", "--plan-sha256", SHA, "--evidence", EVIDENCE]

    def case(name: str, argv: list[str]) -> dict:
        cases[name] = call(api.main, argv, replacements)
        return cases[name]

    try:
        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
            conn.execute(f'CREATE SCHEMA "{schema}"')
        os.environ["HARNESS_DATABASE_URL"] = make_conninfo(dsn, options=f"-c search_path={schema},public")
        case("init_db", ["init-db"])
        case("status_empty", [*delivery, "status"])
        case("status_unknown_plan", [*delivery, "status", "--plan", "nope"])
        case("register_targets_invalid_json", [*delivery, "register-targets", "--file", str(bad_json)])
        case("resume_document_invalid_json", [*delivery, "resume", *owner, "--document", str(bad_json)])
        case("run_once_empty", [*delivery, "run", "--once"])
        case("withdraw_unknown_plan", [*delivery, "withdraw", *owner, "--reason", "reviewed_base_moved"])
        case("resume_unknown_plan", [*delivery, "resume", *owner])
        case("register_plan_missing", [*delivery, "register", "--revision", "a" * 40, "--path", "plan.json"])
        case("lane_status_no_fleet", [*delivery, "status", "--lane", "a"])
        case("lane_register_targets_no_fleet", [*delivery, "register-targets", "--file", str(targets), "--lane", "a"])
        case("lane_tick_no_fleet", [*delivery, "tick", "--lane", "a"])
        case("fleet_register_valid", ["fleet", "register", "--file", str(fleet)])
        case("lane_status_unknown_lane", [*delivery, "status", "--lane", "nope"])
        case("lane_tick_unprovisioned_schema", [*delivery, "tick", "--lane", "a"])
        case("register_targets_valid", [*delivery, "register-targets", "--file", str(targets)])
        case("status_registered", [*delivery, "status"])
    finally:
        os.environ.clear()
        os.environ.update(snapshot)
        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
    return {"cases": cases}
