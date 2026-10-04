"""Scenario body `entry.cli_operation.pg` (REBUILD-DESIGN-v2 §5.2a, §5.3 S10 unit C6a: the operate and autonomous roots).

Layer: harness (never shipped); standard library and psycopg only, and never `codex_harness`.

`api.main` (M7 `codex_harness.cli.main` or the target `codex_harness.entry.cli.main`) runs in-process with `sys.argv` patched,
against a labelled disposable PostgreSQL (`ZEUS_REBUILD_PG_DSN`), as in `entry.cli_research_gov.pg`: one FRESH schema,
`HARNESS_DATABASE_URL` that DSN with `options=-c search_path=<schema>,public`, `ZEUS_REPOSITORY` a fixture directory. The fixture is a
git repository with one commit made under the pinned `GIT_*` identity and dates; its path is fixed by the driver. `api.environment` is
what the side adds to the environment (the target sets `ZEUS_COMPOSITION_PROFILE=development`: declared difference E-c21,
OWNER-DECISIONS-S10 #10; M7 had no profile). No provider, executor, bus or budget is reached: every `run` case refuses first.
The manifests are built from the M7 fixtures of `tests/test_operation.py` (`manifest`: urn:zeus:operation:1, op-001) and
`tests/test_autonomous.py` (`manifest`: urn:zeus:autonomous:1, auto-001), SOURCE e38aa722, with a `base_revision` that is not a commit
of the fixture repository.
Cases (after `init-db`): `operate status` of an unknown id; `operate run` of a file that is not JSON, of a file with a duplicate key
and of a valid manifest whose base revision is absent (`base_revision_missing`); `autonomous status` of an unknown id;
`autonomous run` of an unsupported schema and of a valid v1 manifest whose base revision is absent. Each records argv, the SystemExit
code, parsed stdout and parsed stderr, with the fixture directory normalized to `<FIXTURE>`; no mask is needed.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
from pathlib import Path

CLEARED = ("HARNESS_", "ZEUS_", "COMPOSE_PROJECT_NAME", "CODEX_HOME", "POSTGRES_PASSWORD")
KEPT = ("ZEUS_REBUILD_",)
GIT_FIXED = {"GIT_AUTHOR_NAME": "Fixture", "GIT_AUTHOR_EMAIL": "fixture@localhost",
             "GIT_COMMITTER_NAME": "Fixture", "GIT_COMMITTER_EMAIL": "fixture@localhost",
             "GIT_AUTHOR_DATE": "2026-01-01T00:00:00+00:00", "GIT_COMMITTER_DATE": "2026-01-01T00:00:00+00:00",
             "GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0"}
REDIRECTING = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY", "GIT_COMMON_DIR")
ABSENT = "a" * 40  # not a commit of the fixture repository
GOAL = {"path": "docs/zeus/operations/GOAL.md", "sha256": "b" * 64, "criterion": "one-start entry point",
        "rationale": "the runbook task exercises the entry point"}


def operation_manifest() -> dict:
    """M7 tests/test_operation.py `manifest()` (the default overrides)."""
    return {"schema": "urn:zeus:operation:1", "id": "op-001", "base_revision": ABSENT, "goal": dict(GOAL),
            "plan": {"objective": "Add the RUNBOOK note", "acceptance_criteria": ["focused tests pass"],
                     "allowed_paths": ["docs/zeus/operations/operation-entrypoint-001/RUNBOOK.md"]},
            "budget": {"per_host": 4, "total": 8},
            "claude": {"model": "claude-fixture-model", "timeout_seconds": 300, "max_budget_usd": 2}}


def autonomous_manifest() -> dict:
    """M7 tests/test_autonomous.py `manifest()` (the default overrides)."""
    return {"schema": "urn:zeus:autonomous:1", "id": "auto-001", "base_revision": ABSENT, "goal": dict(GOAL),
            "plan": {"objective": "Add the RUNBOOK note", "acceptance_criteria": ["focused tests pass"],
                     "allowed_paths": ["docs/zeus/operations/autonomous-dge-001/RUNBOOK.md"]},
            "budget": {"per_host": 8, "total": 16},
            "claude": {"model": "claude-fixture-model", "timeout_seconds": 300, "max_budget_usd": 2},
            "deadline": "2030-01-01T00:00:00+00:00",
            "research": {"topic": "runbook note", "questions": ["where is the runbook?"], "search_scope": ["docs"]}}


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


def build_fixture(fixture: Path) -> str:
    """A git repository with one commit holding a pyproject; returns the commit sha."""
    fixture.mkdir(parents=True, exist_ok=True)
    (fixture / "pyproject.toml").write_text('[project]\nname = "zeus-harness"\n', encoding="utf-8")
    empty = fixture.parent / "empty-gitconfig"
    empty.write_text("", encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if k not in REDIRECTING}
    env.update(GIT_FIXED)
    env.update({"GIT_CONFIG_GLOBAL": str(empty), "GIT_CONFIG_SYSTEM": str(empty)})

    def git(*argv):
        done = subprocess.run(["git", "-c", "commit.gpgsign=false", "-C", str(fixture), *argv], env=env,
                              capture_output=True, text=True, timeout=120)
        if done.returncode:
            raise AssertionError("fixture git failed: " + " ".join(argv) + ": " + done.stderr[-300:])
        return done.stdout.strip()

    git("init", "-q")
    git("add", "-A")
    git("commit", "-q", "-m", "fixture")
    return git("rev-parse", "HEAD")


def run_all(api, work: Path, dsn: str) -> dict:
    import psycopg
    from psycopg.conninfo import make_conninfo

    fixture = work / "fixture"
    fixture.mkdir(parents=True)
    base = build_fixture(fixture)
    files = work / "manifests"
    files.mkdir()
    bad_json = files / "invalid.json"
    bad_json.write_text("{not json", encoding="utf-8")
    duplicate = files / "duplicate.json"
    duplicate.write_text('{"id": "a", "id": "b"}', encoding="utf-8")
    operation = files / "operation.json"
    operation.write_text(json.dumps(operation_manifest()), encoding="utf-8")
    unsupported = files / "unsupported.json"
    unsupported.write_text(json.dumps({**autonomous_manifest(), "schema": "urn:zeus:autonomous:9"}), encoding="utf-8")
    autonomous = files / "autonomous.json"
    autonomous.write_text(json.dumps(autonomous_manifest()), encoding="utf-8")
    replacements = {str(files): "<MANIFESTS>", str(fixture): "<FIXTURE>"}

    snapshot = dict(os.environ)
    for name in list(os.environ):
        if name.startswith(CLEARED) and not name.startswith(KEPT):
            del os.environ[name]
    os.environ.update(api.environment)
    os.environ["ZEUS_REPOSITORY"] = str(fixture)
    cases: dict = {"fixture_revision": base}
    schema = "s10_cli_operation"

    def case(name: str, argv: list[str]) -> dict:
        cases[name] = call(api.main, argv, replacements)
        return cases[name]

    try:
        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
            conn.execute(f'CREATE SCHEMA "{schema}"')
        os.environ["HARNESS_DATABASE_URL"] = make_conninfo(dsn, options=f"-c search_path={schema},public")
        case("init_db", ["init-db"])
        case("operate_status_unknown", ["operate", "status", "op-unknown"])
        case("operate_run_invalid_json", ["operate", "run", "--file", str(bad_json)])
        case("operate_run_duplicate_key", ["operate", "run", "--file", str(duplicate)])
        case("operate_run_base_revision_missing", ["operate", "run", "--file", str(operation)])
        case("autonomous_status_unknown", ["autonomous", "status", "auto-unknown"])
        case("autonomous_run_unsupported_schema", ["autonomous", "run", "--file", str(unsupported)])
        case("autonomous_run_base_revision_missing", ["autonomous", "run", "--file", str(autonomous)])
    finally:
        os.environ.clear()
        os.environ.update(snapshot)
        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
    return {"cases": cases}
