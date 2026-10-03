"""Scenario body `entry.cli_store_b.pg` (REBUILD-DESIGN-v2 §5.2a, §5.3 S10 unit C2b: the hook/incident/recovery store roots incident,
rollback-hook, run-command, demo, seed-research-backlog, execution-recovery).

Layer: harness (never shipped); standard library and psycopg only, and never `codex_harness`.

`api.main` (M7 `codex_harness.cli.main` or the target `codex_harness.entry.cli.main`) runs in-process with `sys.argv`
patched, against a labelled disposable PostgreSQL (`ZEUS_REBUILD_PG_DSN`), as in `entry.cli_store.pg`: one FRESH schema per
case group, `HARNESS_DATABASE_URL` that DSN with `options=-c search_path=<schema>,public`, `ZEUS_REPOSITORY` a fixture
directory (its `.runtime/artifacts` is the artifact store the recovery root uses). Side-specific seams are `api.seed_exhausted`
(a task submitted, claimed with one attempt and failed through the side's own Workflow), `api.put_evidence` (a text put
into the runtime artifact store), `api.put_artifact` (a text put into a given artifact directory), `api.plant_history`
(the historical `reference_audits` rows) and `api.packaged_backlog` (a context manager that replaces the packaged backlog
resource of the research module, as M7's `test_backlog_idempotent_and_preserves_legacy` does).
Cases: `incident_first` / `incident_replay` (the same occurrence twice), `rollback_hook_unknown`, `run_command` (this interpreter
printing ok; the interpreter path normalized to `<PY>`) and `run_command_no_argv`, `demo` (see below), `seed_backlog_packaged_empty`
(the packaged resource over empty artifacts: the refusal) and `seed_backlog_fixture` (five fixture manifests planted: the
emitted list), `recovery_prepare` and `recovery_apply` (an exhausted task prepared, then its packet applied) and
`recovery_prepare_existing_output` (the same `--output` again: "Cannot create new recovery packet file").
`demo` runs the M7 scripted bootstrap lifecycle in-process: its canary probe cannot spawn a Codex executable under the provider
guard (R-P) and is reported unavailable (`cli_start` false), so the hook is rejected, never activated, and the case records the
full M7 result (exit 0), not a refusal.
Each case records argv, the SystemExit code, parsed stdout and parsed stderr, with the fixture directory and the interpreter
path normalized (an exception that `main` does not catch is recorded as its type and message). No mask is declared: every message id is fixed, and the nondeterministic fields (timestamps, uuids) are
reduced to stable values where a case says so (`demo`: the session id and the occurrence ids; `recovery_apply`: the execution's timestamps and receipt digests).
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
TASK_ID = "00000000-0000-4000-8000-0000000000c3"
INCIDENT_ID = "00000000-0000-4000-8000-0000000000c4"

TASK = {
    "schema_version": "1.0", "message_id": TASK_ID, "type": "task.assign",
    "correlation_id": "c-1", "causation_id": None,
    "who": {"sender": "conductor", "recipient": "lead:improvement", "owner": "lead:improvement"},
    "what": {"action": "plan", "details": {"objective": "cli recovery roots"}},
    "why": {"objective": "Improve harness reliability from verified evidence", "evidence_refs": []},
    "when": {"created_at": "2026-01-01T00:00:00+00:00", "deadline": None, "after": []},
    "where": {"repository": "codex-harness", "revision": "bootstrap", "environment": "local", "allowed_paths": []},
    "how": {"constraints": [], "acceptance_criteria": ["Preserve normal behavior"],
            "context_ref": None, "result_schema": "six-w.v1"},
}

INCIDENT = {
    **TASK, "message_id": INCIDENT_ID, "type": "incident.report", "correlation_id": "c-incident",
    "who": {"sender": "worker:implementation", "recipient": "lead:improvement", "owner": "lead:improvement"},
    "what": {"action": "record_incident",
             "details": {"occurrence_id": "occurrence-c2b-1", "root_cause": "powershell-codex-ps1-policy",
                         "scope": "bootstrap/windows/codex", "evidence_refs": ["fixture:windows-codex-ps1-policy"]}},
}


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
    incident_file = fixture / "incident.json"
    incident_file.write_text(json.dumps(INCIDENT), encoding="utf-8")
    replacements = {str(fixture): "<FIXTURE>", sys.executable: "<PY>"}

    snapshot = dict(os.environ)
    for name in list(os.environ):
        if name.startswith(CLEARED) and not name.startswith(KEPT):
            del os.environ[name]
    os.environ["ZEUS_REPOSITORY"] = str(fixture)
    cases: dict = {}
    schemas: list[str] = []

    def fresh(schema: str) -> None:
        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
            conn.execute(f'CREATE SCHEMA "{schema}"')
        schemas.append(schema)
        os.environ["HARNESS_DATABASE_URL"] = make_conninfo(dsn, options=f"-c search_path={schema},public")

    def case(name: str, argv: list[str]) -> dict:
        cases[name] = call(api.main, argv, replacements)
        return cases[name]

    try:
        fresh("s10_cli_store_b_hooks")
        case("init_db", ["init-db"])
        case("incident_first", ["incident", str(incident_file)])
        case("incident_replay", ["incident", str(incident_file)])
        case("rollback_hook_unknown", ["rollback-hook", "no-such-hook", "--reason", "r"])
        case("run_command", ["run-command", "--", sys.executable, "-c", "print('ok')"])
        case("run_command_no_argv", ["run-command"])
        case("seed_backlog_packaged_empty", ["seed-research-backlog", "--artifacts", str(fixture / "empty-artifacts")])

        fresh("s10_cli_store_b_demo")
        case("init_db_demo", ["init-db"])
        demo = case("demo", ["demo"])
        if isinstance(demo["stdout"], dict):  # the uuid4 fields (a session id, the hook's occurrence ids) differ per run: count them
            demo["stdout"]["checkpoint"]["session_id"] = "<uuid>"
            demo["stdout"]["hook"]["occurrences"] = len(demo["stdout"]["hook"]["occurrences"])

        fresh("s10_cli_store_b_backlog")
        case("init_db_backlog", ["init-db"])
        seeds = []
        for i in range(5):
            body = {"repository": f"https://github.com/fixture/repo{i}", "revision": "a" * 40,
                    "files": [{"path": "a"}, {"path": "binary"}]}
            ref = api.put_artifact(fixture / "seed-artifacts", json.dumps(body))
            seeds.append({"repository": body["repository"], "revision": body["revision"], "files": 2, "manifest_ref": ref})
        api.plant_history(seeds)
        with api.packaged_backlog(seeds):
            case("seed_backlog_fixture", ["seed-research-backlog", "--artifacts", str(fixture / "seed-artifacts")])

        fresh("s10_cli_store_b_recovery")
        case("init_db_recovery", ["init-db"])
        task = api.seed_exhausted(TASK)
        cases["seeded"] = {"id": task["id"], "status": task["status"]}
        evidence = api.put_evidence("Operator recovery rationale test fixture")
        packet = fixture / "packet.json"
        prepare = ["execution-recovery", "prepare", TASK_ID, "--operation", "resume", "--max-attempts", "2",
                   "--reason", "Investigated transient failure", "--operator", "test-operator",
                   "--evidence", evidence, "--output", str(packet)]
        case("recovery_prepare", prepare)
        case("recovery_prepare_existing_output", prepare)  # the packet file exists; the task is still unrecovered
        applied = case("recovery_apply", ["execution-recovery", "apply", "--packet", str(packet)])
        if isinstance(applied["stdout"], dict):  # timestamps and the digests that cover them differ per run: keep the stable facts
            out, row = applied["stdout"], applied["stdout"]["execution"]
            applied["stdout"] = {
                "replayed": out["replayed"], "receipt_is_sha256": len(out["receipt_id"]) == 64,
                "receipt_is_bound": row["recovery_receipt"] == out["receipt_id"] == row["retry_budget"]["recovery_ref"],
                "execution": {k: row[k] for k in ("agent", "attempt", "generation", "id", "input_hash", "status", "error",
                                                  "failure", "lease_owner", "lease_until", "execution_deadline", "result",
                                                  "recovery_sequence")},
                "attempt_outcomes": [{k: a[k] for k in ("attempt", "error", "status")} for a in row["attempt_outcomes"]],
                "retry_budget": {k: row["retry_budget"][k] for k in ("max_attempts", "origin", "version")}}
    finally:
        os.environ.clear()
        os.environ.update(snapshot)
        with psycopg.connect(dsn, autocommit=True) as conn:
            for schema in schemas:
                conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
    return {"cases": cases}
