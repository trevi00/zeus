"""Scenario body `entry.cli_desk_program.pg` (REBUILD-DESIGN-v2 §5.2a, §5.3 S10 unit C6c: the desk and research-program roots).

Layer: harness (never shipped); standard library and psycopg only, and never `codex_harness`.

`api.main` (M7 `codex_harness.cli.main` or the target `codex_harness.entry.cli.main`) runs in-process with `sys.argv` patched,
against a labelled disposable PostgreSQL (`ZEUS_REBUILD_PG_DSN`), as in `entry.cli_operation.pg`: one FRESH schema,
`HARNESS_DATABASE_URL` that DSN with `options=-c search_path=<schema>,public`, `ZEUS_REPOSITORY` a fixture directory and
`HARNESS_RUNTIME_DIR` a fixture runtime directory. The fixture is a git repository with one commit made under the pinned `GIT_*`
identity and dates (a goal file, one local research note and a pyproject). `api.environment` is what the side adds to the
environment (the target sets `ZEUS_COMPOSITION_PROFILE=development`: declared difference E-c21, OWNER-DECISIONS-S10 #10).
No provider, executor, bus or feed is reached: no case runs a tick that collects (the seeded program is paused).
The program config is M7 `tests/test_research_program_fixtures.py` `config(head)` (SOURCE e38aa722) at the fixture commit.
Cases (after `init-db`): `desk status` of a valid revision and of an invalid one; `research-program status|pause|resume` of an unknown
id; `register` of a file that is not JSON; `run` with `--ticks 0` and with a malformed `--cycle-owner`; `recover` of a request with an
unknown schema; then the positive path the store seeds deterministically: `register` of the valid config (twice: created, cached),
`resume`, `pause`, and `run` of the paused program (proactive and user_request: reserved false, no feed collected).
The work directory is FIXED (`FIXED_WORK`): the registered program binds the digest of the resolved repository path,
so a random temporary directory would make the golden nondeterministic. `status` of the registered program is not a case: it carries
`registered_at` and `updated_at` (wall clock) and would need a new mask; the unit tests cover it.
Each records argv, the SystemExit code, parsed stdout and parsed stderr, with the fixture, manifest and runtime directories
normalized.
"""

from __future__ import annotations

import contextlib
import hashlib
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
FIXED_WORK = "/tmp/zeus-s10-c6c-desk-program"   # the program row binds the digest of the resolved repository path
CANARY = "CANARY-must-never-be-emitted"
NOTE = b"# local residual\nPG store serializes writers with one advisory lock.\n"
GOAL = b"# goal\n"


def program_config(head: str) -> dict:
    """M7 tests/test_research_program_fixtures.py `config(head)` and `template(head)`."""
    template = {"schema": "urn:zeus:autonomous:2", "id": "council-template", "base_revision": head,
                "goal": {"path": "docs/GOAL.md", "sha256": hashlib.sha256(GOAL).hexdigest(), "criterion": "c", "rationale": "r"},
                "plan": {"objective": "improve the research report " + CANARY, "acceptance_criteria": ["focused tests pass"],
                         "allowed_paths": ["docs/RUNBOOK.md"]},
                "budget": {"per_host": 10, "total": 20},
                "claude": {"model": "claude-fixture-model", "timeout_seconds": 120, "max_budget_usd": 1},
                "deadline": "2030-01-01T00:00:00+00:00",
                "research": {"topic": "research report", "questions": ["What is the SSOT?"], "search_scope": ["docs"]},
                "current_state": {"records": [{"bucket": "tasks", "id": "t-1"}], "max_age_seconds": 600}}
    return {"schema": "urn:zeus:research-program:1", "id": "rp-001", "base_revision": head,
            "deadline": "2029-06-01T00:00:00+00:00", "interval_seconds": 3600, "max_cycles": 2, "max_adoptions": 1,
            "budget": {"per_host": 10, "total": 20},
            "topics": [{"id": "storage", "keywords": ["advisory lock", "postgres"]}],
            "local_candidates": [{"id": "local-note", "topic": "storage", "path": "docs/research/note.md",
                                  "sha256": hashlib.sha256(NOTE).hexdigest(), "rationale": "sterk residual " + CANARY}],
            "template": template}


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
    """A git repository with one commit holding a pyproject, the goal file and one local note; returns the commit sha."""
    (fixture / "docs" / "research").mkdir(parents=True, exist_ok=True)
    (fixture / "docs" / "GOAL.md").write_bytes(GOAL)
    (fixture / "docs" / "research" / "note.md").write_bytes(NOTE)
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
    runtime = work / "runtime"
    files = work / "documents"
    files.mkdir()
    bad_json = files / "invalid.json"
    bad_json.write_text("{not json", encoding="utf-8")
    unknown_schema = files / "recovery-unknown.json"
    unknown_schema.write_text(json.dumps({"schema": "urn:zeus:research-dispatch-recovery:9"}), encoding="utf-8")
    config = files / "program.json"
    config.write_text(json.dumps(program_config(base)), encoding="utf-8")
    replacements = {str(files): "<DOCUMENTS>", str(fixture): "<FIXTURE>", str(runtime): "<RUNTIME>"}

    snapshot = dict(os.environ)
    for name in list(os.environ):
        if name.startswith(CLEARED) and not name.startswith(KEPT):
            del os.environ[name]
    os.environ.update(api.environment)
    os.environ["ZEUS_REPOSITORY"] = str(fixture)
    os.environ["HARNESS_RUNTIME_DIR"] = str(runtime)
    cases: dict = {"fixture_revision": base}
    schema = "s10_cli_desk_program"

    def case(name: str, argv: list[str]) -> dict:
        cases[name] = call(api.main, argv, replacements)
        return cases[name]

    try:
        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
            conn.execute(f'CREATE SCHEMA "{schema}"')
        os.environ["HARNESS_DATABASE_URL"] = make_conninfo(dsn, options=f"-c search_path={schema},public")
        case("init_db", ["init-db"])
        case("desk_status", ["desk", "status", "--revision", base])
        case("desk_status_revision_invalid", ["desk", "status", "--revision", "abc"])
        case("program_status_unknown", ["research-program", "status", "rp-unknown"])
        case("program_pause_unknown", ["research-program", "pause", "rp-unknown"])
        case("program_resume_unknown", ["research-program", "resume", "rp-unknown"])
        case("program_register_invalid_json", ["research-program", "register", "--file", str(bad_json)])
        case("program_run_ticks_zero", ["research-program", "run", "rp-001", "--ticks", "0", "--intent", "user_request"])
        case("program_run_cycle_owner_invalid", ["research-program", "run", "rp-001", "--ticks", "2", "--intent",
                                                 "user_request", "--cycle-owner", "nope"])
        case("program_recover_unknown_schema", ["research-program", "recover", "--file", str(unknown_schema)])
        case("program_register", ["research-program", "register", "--file", str(config)])
        case("program_register_cached", ["research-program", "register", "--file", str(config)])
        case("program_run_paused_user_request", ["research-program", "run", "rp-001", "--ticks", "1", "--intent", "user_request"])
        case("program_run_paused_proactive", ["research-program", "run", "rp-001", "--ticks", "1", "--intent", "proactive"])
        case("program_resume", ["research-program", "resume", "rp-001"])
        case("program_pause", ["research-program", "pause", "rp-001"])
    finally:
        os.environ.clear()
        os.environ.update(snapshot)
        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
    return {"cases": cases}
