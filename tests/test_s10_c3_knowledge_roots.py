"""S10 unit C3: the knowledge roots index, query, embed, project-graph, context (DESIGN-s10 §3 C3).

Parity with M7 on a disposable PostgreSQL is the `entry.cli_knowledge.pg` compare family. By owner rule R-c6 that family never
loads the fastembed model, so `query --semantic` and `embed` of a non-empty text are covered here, with a fake embedder and a
fake knowledge store injected through the `composition.cli_knowledge` builders.
"""

import ast
import json
import sys
from pathlib import Path

import pytest

from codex_harness.composition import cli_knowledge
from codex_harness.entry import cli

CLI_DIR = Path(cli.__file__).resolve().parent
ROOTS = ("index", "query", "embed", "project-graph", "context")


class FakeEmbedder:
    model_name = "fake-model"

    def __init__(self):
        self.received = []

    def embed(self, texts):
        self.received.append(list(texts))
        return [[float(len(t))] for t in texts]


class FakeKnowledge:
    def __init__(self):
        self.calls = []

    def hybrid_query(self, text, embedder):
        self.calls.append(("hybrid_query", text))
        return {"vectors": embedder.embed([text]), "model": embedder.model_name}

    def query(self, text):
        self.calls.append(("query", text))
        return [{"id": "n1", "text": text}]

    def embed_missing(self, embedder, limit):
        self.calls.append(("embed_missing", limit))
        rows = ["alpha", "beta"][:limit]
        return {"embedded": len(embedder.embed(rows)), "model": embedder.model_name}

    def index_python(self, root):
        self.calls.append(("index_python", root))
        return {"nodes": 0, "edges": 0, "snapshot": "s"}


@pytest.fixture
def fakes(monkeypatch):
    knowledge, embedder = FakeKnowledge(), FakeEmbedder()
    monkeypatch.setattr(cli_knowledge, "knowledge", lambda: knowledge)
    monkeypatch.setattr(cli_knowledge, "embeddings", lambda: embedder)
    return knowledge, embedder


def run_main(monkeypatch, capsys, *argv):
    monkeypatch.setattr(sys, "argv", ["zeus", *argv])
    cli.main()
    return json.loads(capsys.readouterr().out)


def test_the_five_knowledge_roots_are_in_the_dispatch_table():
    tree = ast.parse((CLI_DIR / "__init__.py").read_text(encoding="utf-8"))
    tables = [n for n in ast.walk(tree) if isinstance(n, ast.Assign)
              and any(isinstance(t, ast.Name) and t.id == "composed" for t in n.targets)]
    assert len(tables) == 1 and isinstance(tables[0].value, ast.Dict)
    assert set(ROOTS) <= {key.value for key in tables[0].value.keys}


def test_query_semantic_hands_the_text_to_the_embedder(fakes, monkeypatch, capsys):
    knowledge, embedder = fakes
    assert run_main(monkeypatch, capsys, "query", "needle", "--semantic") == {"vectors": [[6.0]], "model": "fake-model"}
    assert knowledge.calls == [("hybrid_query", "needle")]
    assert embedder.received == [["needle"]]


def test_query_without_semantic_never_builds_the_embedder(monkeypatch, capsys):
    knowledge = FakeKnowledge()
    monkeypatch.setattr(cli_knowledge, "knowledge", lambda: knowledge)
    monkeypatch.setattr(cli_knowledge, "embeddings", lambda: pytest.fail("embedder built for a lexical query"))
    assert run_main(monkeypatch, capsys, "query", "needle") == [{"id": "n1", "text": "needle"}]
    assert knowledge.calls == [("query", "needle")]


def test_embed_passes_the_limit_and_the_embedder(fakes, monkeypatch, capsys):
    knowledge, embedder = fakes
    assert run_main(monkeypatch, capsys, "embed", "--limit", "2") == {"embedded": 2, "model": "fake-model"}
    assert knowledge.calls == [("embed_missing", 2)]
    assert embedder.received == [["alpha", "beta"]]


def test_embed_defaults_the_limit_to_two_hundred(fakes, monkeypatch, capsys):
    knowledge, _ = fakes
    run_main(monkeypatch, capsys, "embed")
    assert knowledge.calls == [("embed_missing", 200)]


def test_index_emits_the_receipt_of_the_given_root(fakes, monkeypatch, capsys):
    knowledge, _ = fakes
    assert run_main(monkeypatch, capsys, "index", "some/root") == {"nodes": 0, "edges": 0, "snapshot": "s"}
    assert knowledge.calls == [("index_python", "some/root")]


def test_the_builders_are_light_to_import():
    import subprocess
    code = ("import sys, codex_harness.composition.cli_knowledge; "
            "sys.exit(1 if {'psycopg', 'fastembed', 'tree_sitter'} & set(sys.modules) else 0)")
    assert subprocess.run([sys.executable, "-c", code], check=False).returncode == 0


def test_the_embeddings_builder_uses_the_m7_model_cache_path():
    assert cli_knowledge.embeddings().cache_dir == ".runtime/models"
