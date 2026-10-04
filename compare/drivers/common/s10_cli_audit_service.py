"""Scenario body `entry.cli_audit_service.pg` (REBUILD-DESIGN-v2 §5.2a, §5.3 S10 unit C6b: the audit-service root).

Layer: harness (never shipped); standard library and psycopg only, and never `codex_harness`.

`api.main` (M7 `codex_harness.cli.main` or the target `codex_harness.entry.cli.main`) runs in-process with `sys.argv` patched, against a
labelled disposable PostgreSQL (`ZEUS_REBUILD_PG_DSN`): one FRESH schema, `HARNESS_DATABASE_URL` that DSN with `options=-c search_path=<schema>,public`,
`ZEUS_REPOSITORY` a fixture git repository with ONE pinned commit (fixed `GIT_*` environment), so the run gate's `git rev-parse HEAD` succeeds;
the runtime directory is the fixture's default `.runtime`. `api.environment` is what the side adds to the environment (the target sets
`ZEUS_COMPOSITION_PROFILE=development`: declared difference E-c21, M7 had no profile).
Cases (after `init-db`): `status` of an unknown audit (`known_audit: false`); `run --once` of an unknown audit and `run --max-tasks 0 --once`
(both refused by the activation gate, before any observer, executor or transport; the runtime directory listing after them shows only the lock file and the empty workspaces root git creates, no spool);
`status` of a SEEDED audit (one `research_audits` row, two `research_partitions` rows, one `schedule` row whose task is not submitted, and an
active `research_control` activation row, written through the store's own transaction api, which both sides share).
Every id and timestamp is fixed, so no mask is needed. Each case records argv, the SystemExit code, parsed stdout and parsed stderr, with the
fixture directory normalized to `<FIXTURE>`.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
from pathlib import Path

CLEARED = ("HARNESS_", "ZEUS_", "COMPOSE_PROJECT_NAME", "CODEX_HOME", "POSTGRES_PASSWORD", "GIT_")
KEPT = ("ZEUS_REBUILD_",)
GIT_ENV = {"GIT_AUTHOR_NAME": "Fixture", "GIT_AUTHOR_EMAIL": "fixture@localhost", "GIT_COMMITTER_NAME": "Fixture",
           "GIT_COMMITTER_EMAIL": "fixture@localhost", "GIT_AUTHOR_DATE": "2026-01-01T00:00:00+00:00",
           "GIT_COMMITTER_DATE": "2026-01-01T00:00:00+00:00", "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull}
UNKNOWN = "audit-unknown"
SEEDED = "audit-seeded"

PARTITIONS = (
    {"id": "p1", "partition_id": "p1", "audit_id": SEEDED, "generation": 2, "remaining_paths": ["a.py", "b.py"],
     "remaining_subsystems": ["core"], "open_questions": []},
    {"id": "p2", "partition_id": "p2", "audit_id": SEEDED, "generation": 1, "remaining_paths": [],
     "remaining_subsystems": [], "open_questions": ["why?"]},
)


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


def make_fixture(fixture: Path) -> str:
    fixture.mkdir(parents=True)
    (fixture / "pyproject.toml").write_text('[project]\nname = "zeus-harness"\n', encoding="utf-8")
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), **GIT_ENV}
    for argv in (["init", "-q", "-b", "main"], ["add", "pyproject.toml"], ["commit", "-q", "-m", "fixture"]):
        subprocess.run(["git", *argv], cwd=fixture, env=env, check=True, capture_output=True)
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=fixture, env=env, check=True, capture_output=True,
                          text=True).stdout.strip()


def listing(root: Path) -> list[str]:
    return sorted(str(p.relative_to(root)) for p in root.rglob("*")) if root.exists() else []


def run_all(api, work: Path, dsn: str) -> dict:
    import psycopg
    from psycopg.conninfo import make_conninfo

    fixture = work / "fixture"
    commit = make_fixture(fixture)
    replacements = {str(fixture): "<FIXTURE>"}

    snapshot = dict(os.environ)
    for name in list(os.environ):
        if name.startswith(CLEARED) and not name.startswith(KEPT):
            del os.environ[name]
    os.environ["ZEUS_REPOSITORY"] = str(fixture)
    os.environ.update(GIT_ENV)
    os.environ.update(api.environment)
    cases: dict = {"fixture_commit_length": len(commit)}
    schema = "s10_cli_audit_service"

    def case(name: str, argv: list[str]) -> dict:
        cases[name] = call(api.main, argv, replacements)
        return cases[name]

    try:
        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
            conn.execute(f'CREATE SCHEMA "{schema}"')
        os.environ["HARNESS_DATABASE_URL"] = make_conninfo(dsn, options=f"-c search_path={schema},public")
        case("init_db", ["init-db"])
        case("status_unknown", ["audit-service", "status", "--audit-id", UNKNOWN])
        case("run_unknown", ["audit-service", "run", "--audit-id", UNKNOWN, "--once"])
        case("run_max_tasks_zero", ["audit-service", "run", "--audit-id", "a", "--max-tasks", "0", "--once"])
        cases["runtime_listing"] = listing(fixture / ".runtime")
        service = api.build()
        with service.store.transaction() as tx:
            tx.put("research_audits", SEEDED, {"id": SEEDED, "audit_id": SEEDED})
            for row in PARTITIONS:
                tx.put("research_partitions", row["id"], dict(row))
            tx.put("schedule", "s1", {"id": "s1", "partition_id": "p1", "task_id": "task-not-submitted", "at": "2026-01-01T00:00:00+00:00"})
            tx.put("research_control", "activation", {"id": "activation", "status": "active", "release_id": "rel-1", "revision": commit})
        case("status_seeded", ["audit-service", "status", "--audit-id", SEEDED])
    finally:
        os.environ.clear()
        os.environ.update(snapshot)
        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
    return {"cases": cases}
