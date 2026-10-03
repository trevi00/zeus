"""Scenario body `entry.cli_storefree` (REBUILD-DESIGN-v2 §5.2a, §5.3 S10 unit C1: the store-free `zeus` roots).

Layer: harness (never shipped); standard library only.

`main` (M7 `codex_harness.cli.main` or the target `codex_harness.entry.cli.main`) runs in-process with
`sys.argv` patched, in a fresh fixture repository: a `pyproject.toml` whose `[project] name` is
`zeus-harness`, with `ZEUS_REPOSITORY` pointing at it. Each case records the parsed stdout JSON, the
stderr (parsed JSON, else the text) and the SystemExit code. Cases: `paths`; `--repository <second>
paths`; `organization` (agent count and the sha256 of stdout); `validate` with a valid and an invalid
message; `doctor --offline`; `setup` twice (`env_created` true, then false; the `.env` mode 0600 is
asserted here and its content is never read). `canary` is not a case: it spawns `codex`.
The one declared normalization: the fixture directory path becomes `<FIXTURE>` (in stdout, stderr and argv).
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import stat
import sys
from pathlib import Path

CLEARED = ("HARNESS_", "ZEUS_", "COMPOSE_PROJECT_NAME", "CODEX_HOME", "POSTGRES_PASSWORD")
KEPT = ("ZEUS_REBUILD_",)

MESSAGE = {
    "schema_version": "1.0", "message_id": "00000000-0000-4000-8000-000000000001", "type": "task.assign",
    "correlation_id": "c-1", "causation_id": None,
    "who": {"sender": "conductor", "recipient": "lead:improvement", "owner": "lead:improvement"},
    "what": {"action": "plan", "details": {"objective": "storefree validate"}},
    "why": {"objective": "Improve harness reliability from verified evidence", "evidence_refs": []},
    "when": {"created_at": "2026-01-01T00:00:00+00:00", "deadline": None, "after": []},
    "where": {"repository": "codex-harness", "revision": "bootstrap", "environment": "local", "allowed_paths": []},
    "how": {"constraints": [], "acceptance_criteria": ["Preserve normal behavior"],
            "context_ref": None, "result_schema": "six-w.v1"},
}


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def parsed(text: str):
    try:
        return json.loads(text)
    except ValueError:
        return text


def make_fixture(path: Path) -> None:
    path.mkdir(parents=True)
    (path / "pyproject.toml").write_text('[project]\nname = "zeus-harness"\n', encoding="utf-8")


def call(main, fixture: Path, argv: list[str], normalize) -> dict:
    os.environ["ZEUS_REPOSITORY"] = str(fixture)
    os.environ.pop("HARNESS_REPOSITORY", None)
    out, err, code = io.StringIO(), io.StringIO(), 0
    saved = sys.argv
    sys.argv = ["zeus", *argv]
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                main()
            except SystemExit as exc:
                code = exc.code
    finally:
        sys.argv = saved
    stdout, stderr = normalize(out.getvalue()), normalize(err.getvalue())
    return {"argv": [normalize(a) for a in argv], "exit": code,
            "stdout": parsed(stdout), "stderr": parsed(stderr), "_stdout_text": stdout}


def run_all(main, work: Path) -> dict:
    fixture, second = work / "fixture", work / "fixture" / "second"
    make_fixture(fixture)
    second.mkdir()
    prefix = str(fixture)

    def normalize(text: str) -> str:
        return text.replace(prefix, "<FIXTURE>")

    good, bad = fixture / "good.json", fixture / "bad.json"
    good.write_text(json.dumps(MESSAGE), encoding="utf-8")
    broken = {k: v for k, v in MESSAGE.items() if k != "who"}
    bad.write_text(json.dumps(broken), encoding="utf-8")

    snapshot = dict(os.environ)
    for name in list(os.environ):
        if name.startswith(CLEARED) and not name.startswith(KEPT):
            del os.environ[name]
    cases = {}
    try:
        def case(name: str, argv: list[str]) -> dict:
            row = call(main, fixture, argv, normalize)
            cases[name] = {k: v for k, v in row.items() if k != "_stdout_text"}
            return row

        case("paths", ["paths"])
        case("repository_option_paths", ["--repository", str(second), "paths"])
        organization = case("organization", ["organization"])
        cases["organization"]["stdout"] = {"agent_count": len(organization["stdout"]["agents"])}
        cases["organization"]["stdout_sha256"] = sha(organization["_stdout_text"])
        case("validate_valid", ["validate", str(good)])
        case("validate_invalid", ["validate", str(bad)])
        case("doctor_offline", ["doctor", "--offline"])
        case("setup_first", ["setup"])
        env_file = fixture / ".env"
        assert stat.S_IMODE(env_file.stat().st_mode) == 0o600, "the .env must be mode 0600"
        case("setup_second", ["setup"])
        assert stat.S_IMODE(env_file.stat().st_mode) == 0o600
        cases["setup_files"] = {"env_mode": "0600", "runtime_dir": (fixture / ".runtime").is_dir()}
    finally:
        os.environ.clear()
        os.environ.update(snapshot)
    return {"cases": cases}
