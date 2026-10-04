"""Scenario body `entry.cli_research_gov.pg` (REBUILD-DESIGN-v2 §5.2a, §5.3 S10 unit C7b: the dge and decision-feedback roots).

Layer: harness (never shipped); standard library and psycopg only, and never `codex_harness`.

`api.main` (M7 `codex_harness.cli.main` or the target `codex_harness.entry.cli.main`) runs in-process with `sys.argv` patched,
against a labelled disposable PostgreSQL (`ZEUS_REBUILD_PG_DSN`), as in `entry.cli_governance.pg`: one FRESH schema,
`HARNESS_DATABASE_URL` that DSN with `options=-c search_path=<schema>,public`, `ZEUS_REPOSITORY` a fixture directory. The fixture is
a git repository with one commit made under the pinned `GIT_*` identity and dates (so its sha is the same every run); its path is
fixed by the driver, because the dge session records a digest of the resolved repository path. `api.scripted` is the symmetric seam
for the clock the two use cases default to (`utcnow`), a ticking fake clock.
Cases (after `init-db`): dge `register` of a valid packet (a source that is a regular blob at base), the same register again
(`cached`), `status`; `register` of a packet whose source digest does not match (refusal), `submit` of an invalid event (refusal);
decision-feedback `status`, `report` on an empty store, `collect` against the fixture registry at the pinned revision, `report`
after it, and `collect` of a registry path that is not in the commit (refusal). Each case records argv, the SystemExit code, parsed
stdout and parsed stderr, with the fixture directory normalized to `<FIXTURE>`; no mask is needed.
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
SOURCE_PATH = "docs/contracts.md"
SOURCE_TEXT = b"INV-OPERATION-001: operations are bound to a pinned revision.\n"
REGISTRY_PATH = "docs/zeus/procedures.json"
REGISTRY = {"schema": "urn:zeus:procedure-registry:1", "version": 1,
            "entries": [{"id": "runbook-note", "source_kind": "council", "repository": "repo-identity",
                         "allowed_paths": ["docs/a.md", "docs/b.md"], "acceptance_criteria_sha256": "c" * 64,
                         "remediation": "existing_owner_review"}]}


def packet(base: str, sha256: str) -> dict:
    return {"schema": "urn:zeus:research-packet:1", "id": "sess-c7b", "base_revision": base,
            "topic": "research-bound gate", "objective": "decide the gate design", "exclusions": ["no merge"],
            "plan": {"objective": "Implement the gate", "acceptance_criteria": ["focused tests pass", "ruff passes"],
                     "allowed_paths": ["src/codex_harness/domain/dge.py"]},
            "questions": [{"id": "q1", "question": "Is PG authoritative?", "blocking": True, "status": "answered",
                           "claim_ids": ["c1"]}],
            "sources": [{"id": "s1", "path": SOURCE_PATH, "sha256": sha256, "locator": "git:" + SOURCE_PATH,
                         "revision": base, "read_scope": "INV-OPERATION-001 section"}],
            "claims": [{"id": "c1", "kind": "fact", "text": "PG is authoritative for runtime records", "source_ids": ["s1"]},
                       {"id": "c2", "kind": "unknown", "text": "contention under load is unmeasured", "source_ids": []}],
            "limits": {"max_rounds": 2, "deadline": "2030-01-01T09:00:00+09:00"},
            "supersedes": None, "research_reason": None}


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
    """A git repository with one commit holding the dge source, the registry and a pyproject; returns the commit sha."""
    (fixture / "docs" / "zeus").mkdir(parents=True)
    (fixture / "pyproject.toml").write_text('[project]\nname = "zeus-harness"\n', encoding="utf-8")
    (fixture / SOURCE_PATH).write_bytes(SOURCE_TEXT)
    (fixture / REGISTRY_PATH).write_bytes(json.dumps(REGISTRY, indent=2).encode("utf-8"))
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
    packets = fixture / ".packets"
    packets.mkdir()
    good = packets / "good.json"
    good.write_text(json.dumps(packet(base, hashlib.sha256(SOURCE_TEXT).hexdigest())), encoding="utf-8")
    bad = packets / "mismatch.json"
    bad.write_text(json.dumps(packet(base, "b" * 64)), encoding="utf-8")
    event = packets / "event.json"
    event.write_text(json.dumps({"schema": "urn:zeus:debate-event:1"}), encoding="utf-8")
    replacements = {str(fixture): "<FIXTURE>"}

    snapshot = dict(os.environ)
    for name in list(os.environ):
        if name.startswith(CLEARED) and not name.startswith(KEPT):
            del os.environ[name]
    os.environ["ZEUS_REPOSITORY"] = str(fixture)
    cases: dict = {"base_revision": base}
    schema = "s10_cli_research_gov"

    def case(name: str, argv: list[str]) -> dict:
        cases[name] = call(api.main, argv, replacements)
        return cases[name]

    try:
        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
            conn.execute(f'CREATE SCHEMA "{schema}"')
        os.environ["HARNESS_DATABASE_URL"] = make_conninfo(dsn, options=f"-c search_path={schema},public")
        with api.scripted():
            case("init_db", ["init-db"])
            case("dge_register", ["dge", "register", "--file", str(good)])
            case("dge_register_cached", ["dge", "register", "--file", str(good)])
            case("dge_status", ["dge", "status", "sess-c7b"])
            case("dge_register_mismatch", ["dge", "register", "--file", str(bad)])
            case("dge_submit_invalid", ["dge", "submit", "sess-c7b", "--file", str(event)])
            case("feedback_status", ["decision-feedback", "status"])
            case("feedback_report_empty", ["decision-feedback", "report"])
            case("feedback_collect", ["decision-feedback", "collect", "--registry", REGISTRY_PATH, "--revision", base])
            case("feedback_report", ["decision-feedback", "report"])
            case("feedback_collect_missing", ["decision-feedback", "collect", "--registry", "docs/zeus/none.json", "--revision", base])
    finally:
        os.environ.clear()
        os.environ.update(snapshot)
        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
    return {"cases": cases}
