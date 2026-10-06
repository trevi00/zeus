from __future__ import annotations

import hashlib
import math
import os
import re
from pathlib import Path

import psycopg
import tree_sitter_python
from psycopg.types.json import Jsonb
from tree_sitter import Language, Parser

from codex_harness.domain.model import ContractError, canonical, digest, require

SKIP = {".git", ".venv", "node_modules", "__pycache__", ".runtime", ".pytest_cache", ".ruff_cache"}


def extract_python(root: str) -> dict:
    base = Path(root).resolve()
    require(base.is_dir(), "Repository not found")
    parser = Parser(Language(tree_sitter_python.language()))
    nodes, edges = [], []
    fingerprints = []
    repository_id = digest(str(base))[:16]
    imports, calls, modules, symbols, symbol_counts = [], [], {}, {}, {}
    for directory, children, names in os.walk(base):
        children[:] = sorted(n for n in children if n not in SKIP and not Path(directory, n).is_symlink())
        for name in sorted(names):
            path = Path(directory, name)
            if path.suffix != ".py" or path.is_symlink():
                continue
            raw = path.read_bytes()
            tree = parser.parse(raw)
            if tree.root_node.has_error:
                raise ContractError(f"Parse failed: {path.relative_to(base)}")
            relative = path.relative_to(base).as_posix()
            revision = hashlib.sha256(raw).hexdigest()
            fingerprints.append((relative, revision))
            file_id = f"file:{repository_id}:{relative}"
            module = relative.removesuffix(".py").replace("/", ".").removeprefix("src.")
            module = module.removesuffix(".__init__")
            modules[module] = file_id
            nodes.append({"id": file_id, "repository": str(base), "kind": "file",
                          "body": relative, "source_ref": relative, "revision": revision,
                          "properties": {"language": "python"}})

            def visit(node, parent_id, qualified):
                current_parent, current_qualified = parent_id, qualified
                if node.type in {"function_definition", "class_definition"}:
                    symbol = node.child_by_field_name("name").text.decode()
                    current_qualified = qualified + [symbol]
                    node_id = f"symbol:{repository_id}:{relative}:{'.'.join(current_qualified)}"
                    symbol_counts[node_id] = symbol_counts.get(node_id, 0) + 1
                    if symbol_counts[node_id] > 1:
                        node_id += ":variant:" + str(symbol_counts[node_id])
                    nodes.append({"id": node_id, "repository": str(base), "kind": node.type,
                                  "body": node.text.decode()[:6000],
                                  "source_ref": f"{relative}:{node.start_point.row + 1}",
                                  "revision": revision, "properties": {"name": symbol}})
                    symbols[(relative, ".".join(current_qualified))] = node_id
                    edges.append((parent_id, node_id, "contains"))
                    current_parent = node_id
                elif node.type == "comment":
                    for rule_id in re.findall(rb"@invariant\s+([A-Z0-9-]+)", node.text):
                        rule = rule_id.decode()
                        rule_node = f"rule:{repository_id}:{rule}"
                        if not any(n["id"] == rule_node for n in nodes):
                            nodes.append({"id": rule_node, "repository": str(base), "kind": "rule_reference",
                                          "body": rule, "source_ref": f"{relative}:{node.start_point.row + 1}",
                                          "revision": revision, "properties": {"trust": "declared"}})
                        edges.append((parent_id, rule_node, "references"))
                elif node.type in {"import_statement", "import_from_statement"}:
                    imported = node.child_by_field_name("module_name")
                    names = ([imported.text.decode()] if imported else
                             [(child.child_by_field_name("name") or child).text.decode()
                              for child in node.named_children])
                    for name in names:
                        if name.startswith("."):
                            levels = len(name) - len(name.lstrip("."))
                            package = module.split(".") if relative.endswith("__init__.py") else module.split(".")[:-1]
                            name = ".".join(package[:len(package) - levels + 1] + [name.lstrip(".")]).rstrip(".")
                        imports.append((parent_id, name, f"{relative}:{node.start_point.row + 1}", revision))
                elif node.type == "call":
                    function = node.child_by_field_name("function")
                    if function:
                        expression = function.text.decode()
                        target = (".".join(qualified[:-1] + [expression[5:]])
                                  if expression.startswith("self.") else expression)
                        calls.append((parent_id, relative, target))
                for child in node.named_children:
                    visit(child, current_parent, current_qualified)

            visit(tree.root_node, file_id, [])
    external = set()
    for source, module, source_ref, revision in imports:
        target = modules.get(module)
        if target is None:
            target = f"module:{repository_id}:{module}"
            if target not in external:
                external.add(target)
                nodes.append({"id": target, "repository": str(base), "kind": "external_module",
                              "body": module, "source_ref": source_ref, "revision": revision,
                              "properties": {"evidence": "Tree-sitter import syntax"}})
        edges.append((source, target, "imports"))
    for source, relative, name in calls:
        target = symbols.get((relative, name))
        if target and target != source:
            edges.append((source, target, "may_call"))
    snapshot = hashlib.sha256(repr(fingerprints).encode()).hexdigest()
    return {"repository": str(base), "snapshot": snapshot, "nodes": nodes, "edges": edges}


class PostgresKnowledge:
    def __init__(self, dsn: str):
        self.dsn = dsn

    def index_python(self, root: str) -> dict:
        graph = extract_python(root)
        with psycopg.connect(self.dsn) as conn:
            conn.execute("SELECT pg_advisory_xact_lock(734220)")
            # Preserve vectors when content is unchanged; remove deleted nodes transactionally.
            ids = [n["id"] for n in graph["nodes"]]
            conn.execute("DELETE FROM knowledge_nodes WHERE repository=%s AND NOT (id=ANY(%s))",
                         (graph["repository"], ids))
            conn.execute("DELETE FROM knowledge_edges WHERE source IN (SELECT id FROM knowledge_nodes WHERE repository=%s)",
                         (graph["repository"],))
            for n in graph["nodes"]:
                conn.execute("""INSERT INTO knowledge_nodes
                    (id,repository,kind,body,source_ref,revision,properties)
                    VALUES (%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT(id) DO UPDATE SET body=excluded.body,source_ref=excluded.source_ref,
                    revision=excluded.revision,properties=excluded.properties ||
                    CASE WHEN knowledge_nodes.body=excluded.body THEN
                    jsonb_strip_nulls(jsonb_build_object('embedding_model',knowledge_nodes.properties->'embedding_model'))
                    ELSE '{}'::jsonb END,
                    embedding=CASE WHEN knowledge_nodes.body=excluded.body THEN knowledge_nodes.embedding ELSE NULL END""",
                             (n["id"], n["repository"], n["kind"], n["body"], n["source_ref"],
                              n["revision"], Jsonb({**n["properties"], "snapshot": graph["snapshot"]})))
            for source, target, kind in graph["edges"]:
                conn.execute("INSERT INTO knowledge_edges VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
                             (source, target, kind))
        return {"snapshot": graph["snapshot"], "nodes": len(graph["nodes"]), "edges": len(graph["edges"])}

    def project_runtime(self, store, organization) -> dict:
        with store.transaction() as tx:
            records = {bucket: tx.scan(bucket) for bucket in
                       ("tasks", "hooks", "sessions", "releases", "decisions_pending")}
        nodes, edges = [], []
        snapshot = digest(records)
        for agent in organization.agents.values():
            nodes.append(("runtime:agent:" + agent.id, "agent", canonical({"id": agent.id, "role": agent.role,
                          "team": agent.team}), "organization.json", "definition", {"authority": "Git"}))
            if agent.parent:
                edges.append(("runtime:agent:" + agent.parent, "runtime:agent:" + agent.id, "supervises"))
        for bucket, rows in records.items():
            for row in rows:
                key = row.get("id") or row.get("agent_id")
                node_id = f"runtime:{bucket}:{key}"
                nodes.append((node_id, bucket, canonical(row), f"postgres:{bucket}/{key}", digest(row),
                              {"authority": "PostgreSQL", "snapshot": snapshot}))
                agent = row.get("agent") or row.get("agent_id") or row.get("author") or row.get("actor")
                if agent:
                    edges.append(("runtime:agent:" + agent, node_id, "owns"))
                if bucket == "tasks":
                    for dependency in row["message"]["when"]["after"]:
                        edges.append((f"runtime:tasks:{dependency}", node_id, "precedes"))
        with psycopg.connect(self.dsn) as conn:
            conn.execute("SELECT pg_advisory_xact_lock(734220)")
            conn.execute("DELETE FROM knowledge_nodes WHERE repository='runtime:ssot' AND NOT (id=ANY(%s))",
                         ([node[0] for node in nodes],))
            conn.execute("DELETE FROM knowledge_edges WHERE source IN (SELECT id FROM knowledge_nodes WHERE repository='runtime:ssot')")
            for node_id, kind, body, source, revision, properties in nodes:
                conn.execute("INSERT INTO knowledge_nodes (id,repository,kind,body,source_ref,revision,properties) "
                             "VALUES (%s,'runtime:ssot',%s,%s,%s,%s,%s) ON CONFLICT(id) DO UPDATE SET "
                             "body=excluded.body,revision=excluded.revision,source_ref=excluded.source_ref,"
                             "properties=excluded.properties || CASE WHEN knowledge_nodes.body=excluded.body THEN "
                             "jsonb_strip_nulls(jsonb_build_object('embedding_model',knowledge_nodes.properties->'embedding_model')) "
                             "ELSE '{}'::jsonb END,embedding=CASE WHEN knowledge_nodes.body=excluded.body "
                             "THEN knowledge_nodes.embedding ELSE NULL END",
                             (node_id, kind, body, source, revision, Jsonb({"snapshot": snapshot, **properties})))
            ids = {n[0] for n in nodes}
            for source, target, kind in edges:
                if source in ids and target in ids:
                    conn.execute("INSERT INTO knowledge_edges VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
                                 (source, target, kind))
        return {"snapshot": snapshot, "nodes": len(nodes), "edges": len(edges)}

    def embed_missing(self, embedder, limit: int = 200) -> dict:
        require(0 < limit <= 1000, "Invalid embedding batch size")
        with psycopg.connect(self.dsn) as conn:
            rows = conn.execute("SELECT id,body,revision FROM knowledge_nodes WHERE embedding IS NULL "
                                "OR properties->>'embedding_model' IS DISTINCT FROM %s ORDER BY id LIMIT %s",
                                (embedder.model_name, limit)).fetchall()
        vectors = embedder.embed([row[1] for row in rows]) if rows else []
        require(len(vectors) == len(rows), "Embedding provider response count mismatch")
        updated = 0
        with psycopg.connect(self.dsn) as conn:
            for (node_id, _, revision), vector in zip(rows, vectors):
                cursor = conn.execute("UPDATE knowledge_nodes SET embedding=%s::vector,properties=properties || %s "
                                      "WHERE id=%s AND revision=%s",
                                      (self.vector(vector), Jsonb({"embedding_model": embedder.model_name}), node_id, revision))
                updated += cursor.rowcount
        return {"embedded": updated, "model": embedder.model_name}

    def hybrid_query(self, text: str, embedder, depth: int = 1, limit: int = 12) -> list[dict]:
        require(0 <= depth <= 3 and 1 <= limit <= 100, "Invalid hybrid query budget")
        semantic = self.vector_query(embedder.embed([text])[0], embedder.model_name, limit)
        lexical = self.query(text, depth=0, limit=limit)
        scores = {}
        for result in (semantic, lexical):
            for rank, row in enumerate(result, 1):
                scores[row["id"]] = scores.get(row["id"], 0) + 1 / (60 + rank)
        seeds = sorted(scores, key=lambda key: (-scores[key], key))[:limit]
        found = set(seeds)
        with psycopg.connect(self.dsn) as conn:
            for _ in range(depth):
                rows = conn.execute("SELECT source,target FROM knowledge_edges WHERE source=ANY(%s) OR target=ANY(%s) "
                                    "ORDER BY source,target LIMIT 500", (sorted(found), sorted(found))).fetchall()
                found.update(value for row in rows for value in row)
            rows = conn.execute("SELECT id,kind,body,source_ref,revision,properties FROM knowledge_nodes WHERE id=ANY(%s)",
                                (sorted(found),)).fetchall()
        hits = [dict(zip(("id", "kind", "body", "source_ref", "revision", "properties"), row)) for row in rows]
        return sorted(hits, key=lambda row: (-scores.get(row["id"], 0), row["id"]))[:limit]

    def query(self, text: str, depth: int = 1, limit: int = 12) -> list[dict]:
        require(bool(text.strip()) and 0 <= depth <= 3 and 1 <= limit <= 100, "Invalid graph query")
        with psycopg.connect(self.dsn) as conn:
            seeds = [r[0] for r in conn.execute("""SELECT id FROM knowledge_nodes
                WHERE body ILIKE %s ORDER BY id LIMIT %s""", (f"%{text}%", limit))]
            found = set(seeds)
            for _ in range(depth):
                rows = conn.execute("""SELECT source,target FROM knowledge_edges
                    WHERE source=ANY(%s) OR target=ANY(%s) ORDER BY source,target LIMIT 500""",
                                    (sorted(found), sorted(found))).fetchall()
                found.update(value for row in rows for value in row)
            rows = conn.execute("""SELECT id,kind,body,source_ref,revision,properties
                FROM knowledge_nodes WHERE id=ANY(%s)
                ORDER BY CASE WHEN id=ANY(%s) THEN 0 ELSE 1 END,id LIMIT %s""",
                                (sorted(found), seeds, limit)).fetchall()
        return [dict(zip(("id", "kind", "body", "source_ref", "revision", "properties"), r)) for r in rows]

    @staticmethod
    def vector(values: list[float]) -> str:
        require(bool(values) and all(math.isfinite(v) for v in values), "Invalid embedding")
        return "[" + ",".join(str(float(v)) for v in values) + "]"

    def set_embedding(self, node_id: str, values: list[float], model: str) -> None:
        require(bool(model), "Embedding model ID required")
        with psycopg.connect(self.dsn) as conn:
            result = conn.execute("""UPDATE knowledge_nodes SET embedding=%s::vector,
                properties=properties || %s WHERE id=%s""",
                                  (self.vector(values), Jsonb({"embedding_model": model}), node_id))
            require(result.rowcount == 1, "Knowledge node not found")

    def vector_query(self, values: list[float], model: str, limit: int = 12) -> list[dict]:
        require(1 <= limit <= 100, "Invalid limit")
        with psycopg.connect(self.dsn) as conn:
            rows = conn.execute("""SELECT id,source_ref,revision,embedding <=> %s::vector AS distance
                FROM knowledge_nodes WHERE embedding IS NOT NULL
                AND vector_dims(embedding)=%s AND properties->>'embedding_model'=%s
                ORDER BY distance,id LIMIT %s""", (self.vector(values), len(values), model, limit))
            return [dict(zip(("id", "source_ref", "revision", "distance"), r)) for r in rows]
