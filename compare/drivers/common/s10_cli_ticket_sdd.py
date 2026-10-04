"""Scenario body `entry.cli_ticket_sdd.pg` (REBUILD-DESIGN-v2 §5.2a, §5.3 S10 unit C2c: the ticket and sdd roots).

Layer: harness (never shipped); standard library and psycopg only, and never `codex_harness`.

`api.main` (M7 `codex_harness.cli.main` or the target `codex_harness.entry.cli.main`) runs in-process with `sys.argv`
patched, against a labelled disposable PostgreSQL (`ZEUS_REBUILD_PG_DSN`), as in `entry.cli_store_b.pg`: one FRESH schema,
`HARNESS_DATABASE_URL` that DSN with `options=-c search_path=<schema>,public`, `ZEUS_REPOSITORY` a fixture directory at a path both sides share (the SDD iteration id digests the spec's origin, so the path is part of the recorded result).
`api.scripted()` is a context manager the side supplies: the ticket-id `uuid4` and the `utcnow` of the ticket, lifecycle,
SDD and artifact modules are replaced by a counter and a ticking clock (the S8 scripted-clock idiom), so every id and
timestamp is fixed and no mask is needed.
Cases (after `init-db`): ticket `create`, `list`, `show`, `update` (a second revision), `review`, `export`, `sync --preview`,
`evidence` (a document for the current revision), `prepare-close` (the fixture repository has no trust anchor: M7's refusal),
`reopen` (an open ticket: M7's refusal) and `show` of an unknown id; sdd `inspect` and `view` of a working-tree fixture
spec, `register` of it against the ticket, `status` of the iteration and `inspect` of an invalid spec.
Excluded (never composed into the family): `ticket sync` without `--preview`, `ticket pull` (GitHub) and `sdd device-check`
(adb), by owner rule R-c10; `ticket dispatch` (R-c9, C5).
Each case records argv, the SystemExit code, parsed stdout and parsed stderr, with the fixture directory normalized to `<FIXTURE>`.
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


def content(title, **over):
    return {"title": title, "problem": "Production and tests share endpoints", "impact": "Potential contention",
            "rollback": "Restore verified image", "evidence_refs": ["fixture:source-inspection"], "scope": ["deployment"],
            "acceptance_criteria": ["Independent services"], "verification": ["Run isolated service integration test"], **over}


def spec(**over):
    document = {"schema": "zeus.sdd.v1", "id": "spec.alpha", "title": "Alpha", "intent": "Review the scenario intent",
                "personas": ["owner"],
                "requirements": [{"id": "REQ.a", "statement": "The owner reviews the intent", "risk": "normal", "status": "active"}],
                "scenarios": [{"id": "SCN.intent-review", "title": "Intent review", "status": "active", "requirement_ids": ["REQ.a"],
                               "given": ["a draft"], "when": ["the owner reads it"], "then": ["the intent is shown"],
                               "device_profiles": ["DEV.a"], "bindings": []}],
                "devices": [{"id": "DEV.a", "manufacturer": "samsung", "platform": "android", "form_factor": "phone",
                             "physical_required": True, "conditions": ["portrait"]}],
                "design": {"components": "components", "icons": "icons", "tokens": "tokens", "required_stories": ["story"]},
                "target": {"kind": "unconfigured", "app_id": None, "build_hash": None, "alpha_url": None},
                "reset_contract": "reset between runs"}
    document.update(over)
    return document


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


def run_all(api, work: Path, dsn: str) -> dict:
    import psycopg
    from psycopg.conninfo import make_conninfo

    fixture = work / "fixture"
    fixture.mkdir(parents=True)
    (fixture / "pyproject.toml").write_text('[project]\nname = "zeus-harness"\n', encoding="utf-8")
    replacements = {str(fixture): "<FIXTURE>"}

    def write(name: str, document) -> str:
        path = fixture / name
        path.write_text(json.dumps(document), encoding="utf-8")
        return str(path)

    snapshot = dict(os.environ)
    for name in list(os.environ):
        if name.startswith(CLEARED) and not name.startswith(KEPT):
            del os.environ[name]
    os.environ["ZEUS_REPOSITORY"] = str(fixture)
    cases: dict = {}
    schema = "s10_cli_ticket_sdd"

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
            created = case("ticket_create", ["ticket", "create", "--file", write("ticket.json", content("Isolated verification"))])
            ticket_id = created["stdout"]["id"] if isinstance(created["stdout"], dict) else "ZEUS-missing"
            case("ticket_list", ["ticket", "list"])
            case("ticket_show", ["ticket", "show", ticket_id])
            case("ticket_update", ["ticket", "update", ticket_id, "--revision", "1", "--reason", "Tighten the scope",
                                   "--file", write("ticket2.json", content("Isolated verification", scope=["deployment", "tests"]))])
            shown = case("ticket_show_current", ["ticket", "show", ticket_id])
            case("ticket_review", ["ticket", "review", ticket_id, "--revision", "2", "--reviewer", "reviewer-a", "--provider",
                                   "independent", "--verdict", "support", "--summary", "The scope is bounded",
                                   "--evidence", "fixture:review-evidence"])
            case("ticket_export", ["ticket", "export", ticket_id])
            case("ticket_sync_preview", ["ticket", "sync", ticket_id, "--repo", "fixture/repo", "--preview"])
            row = shown["stdout"] if isinstance(shown["stdout"], dict) else {}
            case("ticket_evidence", ["ticket", "evidence", ticket_id, "--file",
                                     write("evidence.json", {"ticket_id": ticket_id, "revision": row.get("revision"),
                                                             "content_hash": row.get("content_hash")})])
            case("ticket_prepare_close", ["ticket", "prepare-close", ticket_id, "--file",
                                          write("closure.json", {"solution_commit": "a" * 40, "criteria": [],
                                                                 "environment_ref": "sha256:" + "b" * 64, "reason": "Fixture closure"}),
                                          "--output", str(fixture / "signing" / "packet.json")])
            case("ticket_reopen", ["ticket", "reopen", ticket_id, "--revision", "2", "--sequence", "1", "--reason", "Reopen"])
            case("ticket_show_unknown", ["ticket", "show", "ZEUS-unknown000000"])

            spec_file = write("spec.json", spec())
            case("sdd_inspect", ["sdd", "inspect", spec_file])
            case("sdd_view", ["sdd", "view", spec_file, "--output", str(fixture / "exports" / "review.html")])
            registered = case("sdd_register", ["sdd", "register", spec_file, "--ticket", ticket_id, "--ticket-revision", "2"])
            iteration = registered["stdout"].get("id") if isinstance(registered["stdout"], dict) else None
            case("sdd_status", ["sdd", "status", str(iteration)])
            case("sdd_inspect_invalid", ["sdd", "inspect", write("bad-spec.json", spec(schema="zeus.sdd.v0"))])
    finally:
        os.environ.clear()
        os.environ.update(snapshot)
        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
    return {"cases": cases}
