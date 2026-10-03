"""Scenario body `entry.cli_knowledge.pg` (REBUILD-DESIGN-v2 §5.2a, §5.3 S10 unit C3: the knowledge roots index, query, embed, project-graph, context).

Layer: harness (never shipped); standard library and psycopg only, and never `codex_harness`.

`api.main` (M7 `codex_harness.cli.main` or the target `codex_harness.entry.cli.main`) runs in-process with `sys.argv`
patched, against a labelled disposable PostgreSQL (`ZEUS_REBUILD_PG_DSN`): `HARNESS_DATABASE_URL` is that DSN with
`options=-c search_path=<schema>,public`, one FRESH schema per case group (dropped at the end), `init-db` first.
Cases: `index_fixture`, `index_again` (unchanged tree), `query_hit`, `query_miss`, `context_hit`, `context_miss`,
`project_graph`, `embed_limit_zero` (M7 refuses limit 0: "Invalid embedding batch size") and `index_missing_root`. Each records argv, the SystemExit code, parsed stdout and
parsed stderr, the fixture directory path normalized to `<FIXTURE>`. No mask is declared.
Owner rule R-c6: `query --semantic` and `embed` of a non-empty text load the fastembed model (network and a model cache
the harness does not have), so they are not cases here; a unit test covers them with a fake embedder.
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
FIXED_WORK = "/tmp/zeus-s10-c3-knowledge"   # M7 hashes the resolved root path into every node id

ALPHA = '''"""Alpha module."""
import os


class AlphaIndexer:
    """Walks a tree."""

    def walk(self, root):
        return sorted(os.listdir(root))


def build_alpha_index(root):
    return AlphaIndexer().walk(root)
'''
BETA = '''"""Beta module."""
from alpha import build_alpha_index


def summarize_beta(root):
    return len(build_alpha_index(root))
'''


def parsed(text: str):
    try:
        return json.loads(text)
    except ValueError:
        return text


def call(main, argv: list[str], prefix: str) -> dict:
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
    return {"argv": [a.replace(prefix, "<FIXTURE>") for a in argv], "exit": code,
            "stdout": parsed(out.getvalue().replace(prefix, "<FIXTURE>")),
            "stderr": parsed(err.getvalue().replace(prefix, "<FIXTURE>"))}


def run_all(api, work: Path, dsn: str) -> dict:
    import psycopg
    from psycopg.conninfo import make_conninfo

    fixture = work / "fixture"
    tree = fixture / "tree"
    tree.mkdir(parents=True)
    (fixture / "pyproject.toml").write_text('[project]\nname = "zeus-harness"\n', encoding="utf-8")
    (tree / "alpha.py").write_text(ALPHA, encoding="utf-8")
    (tree / "beta.py").write_text(BETA, encoding="utf-8")

    snapshot = dict(os.environ)
    for name in list(os.environ):
        if name.startswith(CLEARED) and not name.startswith(KEPT):
            del os.environ[name]
    os.environ["ZEUS_REPOSITORY"] = str(fixture)
    cases: dict = {}
    schema = "s10_cli_knowledge"

    def case(name: str, argv: list[str]) -> dict:
        cases[name] = call(api.main, argv, str(fixture))
        return cases[name]

    try:
        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
            conn.execute(f'CREATE SCHEMA "{schema}"')
        os.environ["HARNESS_DATABASE_URL"] = make_conninfo(dsn, options=f"-c search_path={schema},public")
        case("init_db", ["init-db"])
        case("index_fixture", ["index", str(tree)])
        case("index_again", ["index", str(tree)])
        case("query_hit", ["query", "build_alpha_index"])
        case("query_miss", ["query", "zzqxnosuchsymbolzz"])
        case("context_hit", ["context", "build_alpha_index", "--agent", "worker:implementation", "--budget", "6000"])
        case("context_miss", ["context", "zzqxnosuchsymbolzz", "--agent", "worker:implementation", "--budget", "6000"])
        case("project_graph", ["project-graph"])
        case("embed_limit_zero", ["embed", "--limit", "0"])
        case("index_missing_root", ["index", str(fixture / "no-such-root")])
    finally:
        os.environ.clear()
        os.environ.update(snapshot)
        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
    return {"cases": cases}
