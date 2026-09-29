"""Reference driver: `context.composition` on SOURCE M7 (REBUILD-DESIGN-v2 §2.7 F4, §5.3 S2, R-C first).

At M7 the composition of delivered context lives inside `adapters.executor.Executor._run`. This driver
calls `_run` directly for each fixed case with:
- a fixture provider transport in place of the in-process `AppServer` name (no provider exists) that
  records the delivered prompt and answers with a schema-valid fixture;
- the scripted fake clock/ids, a fixed disposable project (compare/drivers/common/s2_fixture.py) and a
  fixed placeholder interpreter as `sys.executable` (injection: M7 writes it into the packet);
- the packaged provider policy with an explicit empty host configuration (Codex default);
- for the knowledge cases, a fixture knowledge query: three hits (a runtime hit, a file hit whose
  revision matches the basis blob and one that does not), or one hit naming a path absent at the
  basis revision (M7 lets that Git refusal abort the composition; preserved as characterized).
It records every artifact put, the store rows and the execution record's `context_measurement`.
"""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

import hashlib  # noqa: E402
import json  # noqa: E402

import determinism  # noqa: E402
import s2_composition  # noqa: E402
import s2_fixture  # noqa: E402

from codex_harness.adapters import executor as executor_module  # noqa: E402
from codex_harness.adapters.artifacts import FileArtifacts  # noqa: E402
from codex_harness.adapters.executor import Executor  # noqa: E402
from codex_harness.adapters.git import GitWorkspace  # noqa: E402
from codex_harness.adapters.providers import host_policy  # noqa: E402
from codex_harness.adapters.store import MemoryStore  # noqa: E402
from codex_harness.application import execution_time, workflow  # noqa: E402,F401
from codex_harness.application.service import Harness  # noqa: E402
from codex_harness.bootstrap import organization  # noqa: E402

CLOCK, IDS = determinism.FakeClock(), determinism.FakeIds()
determinism.install(CLOCK, IDS, constants={
    "codex_harness.application.execution_time": {"DOMAIN": "00000000-0000-4000-8000-00000000c0c0"}})


class Sentinel(Exception):
    pass


class RecordingArtifacts(FileArtifacts):
    def __init__(self, root):
        super().__init__(root)
        self.puts, self.bodies = [], {}

    def put(self, body, source, lock_timeout=30):
        ref = super().put(body, source, lock_timeout)
        self.puts.append({"source": source, "ref": ref["ref"]})
        self.bodies[ref["ref"]] = body
        return ref


class FixtureKnowledge:
    def __init__(self, repo: Path, mode: str):
        readme = (repo / "README.md").read_bytes()
        self.hits = [
            {"id": "runtime:note-1", "body": "runtime observation body", "source_ref": "runtime:1", "revision": "r1"},
            {"id": "file:README", "body": "README body", "source_ref": "README.md:1",
             "revision": hashlib.sha256(readme).hexdigest()},
            {"id": "file:stale", "body": "stale body", "source_ref": "README.md:1", "revision": "0" * 64}]
        if mode == "missing_path":
            self.hits = [{"id": "file:missing", "body": "missing body", "source_ref": "nowhere.py:3",
                          "revision": "1" * 64}]
        self.queries = []

    def hybrid_query(self, text, encoder, limit=5):
        self.queries.append({"sha256": hashlib.sha256(text.encode()).hexdigest(), "limit": limit})
        return list(self.hits)


def world_factory():
    world = s2_fixture.build()
    plain = world["root"] / "plain"
    plain.mkdir()
    s2_fixture.git(plain, "init", "-q", "-b", "main")
    (plain / "README.md").write_text("# Fixture project\n", encoding="utf-8")
    (plain / "src").mkdir()
    (plain / "src" / "main.py").write_text("print('fixture')\n", encoding="utf-8")
    s2_fixture.git(plain, "add", ".")
    s2_fixture.git(plain, "commit", "-q", "-m", "plain project")
    world["plain"] = plain
    CLOCK.reset()
    IDS.reset()
    return world


def compose(case: dict, world: dict) -> dict:
    sys.executable = str(world["interpreter"])
    store = MemoryStore()
    for bucket, rows in (case.get("seed") or {}).items():
        with store.transaction() as tx:
            for key, body in rows.items():
                tx.put(bucket, key, body)
    service = Harness(store, organization())
    artifacts = RecordingArtifacts(str(world["artifacts"]))
    repo = world[case["repo"]]
    git = GitWorkspace(str(repo), str(world["workspaces"]))
    knowledge = FixtureKnowledge(repo, case["knowledge"]) if case.get("knowledge") else None
    prompts = []

    class FixtureTransport:
        def __init__(self, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def run(self, prompt, cwd, schema, *args, **kw):
            prompts.append(prompt)
            return {"answer": dict(case["answer"]), "events": [], "thread_id": "fixture",
                    "usage": {"totalTokens": 1}, "rotate": False, "interrupted": False}

    executor_module.AppServer = FixtureTransport
    executor = Executor(service, git, artifacts, knowledge=knowledge, execution_policy=host_policy({}))
    schema = getattr(executor_module, case["schema"])
    status, refusal, measurement = "composed", None, None
    try:
        result = executor._run(case["agent"], case["key"], case["objective"], case["evidence"], str(repo),
                               schema, case["read_only"], None, None, stage=case["stage"],
                               workload=case["workload"], action=case["action"])
        record = json.loads(artifacts.bodies[result["execution_ref"]])
        measurement = record.get("context_measurement")
    except Exception as exc:  # noqa: BLE001 - the refusal type and reason are the result
        status, refusal = "refused", {"error": type(exc).__name__, "message": str(exc)[:400]}
    with store.transaction() as tx:
        rows = [(r["bucket"], r["id"], r["body"]) for r in tx.records()]
    return {"status": status, "refusal": refusal, "prompts": prompts,
            "puts": [p for p in artifacts.puts if not p["source"].startswith(("execution", "runtime-"))],
            "bodies": artifacts.bodies, "rows": rows, "context_measurement": measurement,
            "knowledge_queries": knowledge.queries if knowledge else None}


if __name__ == "__main__":
    try:
        result = s2_composition.run(type("API", (), {"compose": staticmethod(compose)}), world_factory)
    finally:
        s2_fixture.cleanup()
    driver.finish("reference", "context.composition", result)
