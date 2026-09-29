"""Target driver: `context.composition` on the target tree (context.application.compose.ContextComposer).

Inputs owned by other contexts are supplied as values, the way their owners will supply them:
- the snapshot and the checkpoint/progress records are read from the target MemoryStore with the M7
  rule (`digest({"tasks": scan, "sessions": scan})`, `sessions[agent]`, `execution_progress[key]`);
  coordination provides them through its ports in S5 (FixtureSnapshot stands in, like S1's fixture journal);
- the native threshold definition comes from a fixture source reading the packaged
  `threshold-policy.json` (research implements context.ports.ThresholdPolicySource in S8);
- the reader interpreter and the review interpreter are the fixed placeholder file (injection);
- the provider is the packaged default (the host configuration is empty), as on the reference side.
The clock is injected through the kernel port; nothing is patched.
"""

import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

import determinism  # noqa: E402
import s2_composition  # noqa: E402
import s2_fixture  # noqa: E402
from codex_harness.context.adapters.composition_sources import (  # noqa: E402
    GitRepository,
    ProjectSkills,
    SkillHistoryRecorder,
)
from codex_harness.context.adapters.review_context import review_context  # noqa: E402
from codex_harness.context.application.compose import (  # noqa: E402
    CompositionRequest,
    ContextComposer,
)
from codex_harness.host_os.adapters.git_workspace import GitWorkspace  # noqa: E402
from codex_harness.kernel.ids import digest  # noqa: E402
from codex_harness.kernel.policy import POLICY  # noqa: E402
from codex_harness.knowledge.adapters.context_hits import KnowledgeHits  # noqa: E402
from codex_harness.routing.adapters.provider_policy import host_policy  # noqa: E402
from codex_harness.storage.adapters.file_artifacts import FileArtifacts  # noqa: E402
from codex_harness.storage.adapters.memory_store import MemoryStore  # noqa: E402
from s1_target import PortClock  # noqa: E402

CLOCK, IDS = determinism.FakeClock(), determinism.FakeIds()
CLOCK_PORT = PortClock(CLOCK)
RESOURCES = Path(__import__("codex_harness").__file__).resolve().parent / "resources"


class FixtureThresholds:
    """Stands in for research's native threshold resolution (S8) over the packaged definition."""

    def effective_policy(self):
        text = (RESOURCES / "threshold-policy.json").read_text(encoding="utf-8")
        policy = json.loads(text)
        values = {"skill_match.FULL_BODY_MIN_SCORE": 3, **policy["overrides"]}
        return {"values": values, "definition_hash": digest(text), "definition": policy}


class RecordingArtifacts(FileArtifacts):
    def __init__(self, root):
        super().__init__(root, clock=CLOCK_PORT)
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

    def hybrid_query(self, text, encoder, limit=5):
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
    store = MemoryStore()
    for bucket, rows in (case.get("seed") or {}).items():
        with store.transaction() as tx:
            for key, body in rows.items():
                tx.put(bucket, key, body)
    artifacts = RecordingArtifacts(str(world["artifacts"]))
    repo = world[case["repo"]]
    git = GitWorkspace(str(repo), str(world["workspaces"]))
    knowledge = (KnowledgeHits(FixtureKnowledge(repo, case["knowledge"]), str(artifacts.root.parent / "models"))
                 if case.get("knowledge") else None)
    composer = ContextComposer(artifacts, artifacts.root, GitRepository(git),
                               ProjectSkills(git, artifacts, FixtureThresholds()),
                               SkillHistoryRecorder(store, artifacts, git, CLOCK_PORT), knowledge)
    policy = host_policy({})
    assignment = policy.select(role=case["agent"], action=case["action"], workload=case["workload"],
                               read_only=case["read_only"])
    with store.transaction() as tx:
        snapshot = digest({"tasks": tx.scan("tasks"), "sessions": tx.scan("sessions")})
        deployed = tx.get("deployment", "active")
        checkpoint = tx.get("sessions", case["agent"])
        progress = tx.get("execution_progress", case["key"])
    interpreter = str(world["interpreter"])
    request = CompositionRequest(
        agent=case["agent"], key=case["key"], objective=case["objective"], evidence=case["evidence"],
        cwd=str(repo), snapshot=snapshot, runtime_policy_digest=digest(POLICY.snapshot()),
        reader_python=interpreter, provider=assignment.provider, default_provider=policy.policy.default_provider,
        read_only=case["read_only"], action=case["action"], stage=case["stage"],
        deployed_revision=(deployed or {}).get("revision"), checkpoint=checkpoint, progress=progress,
        review_context=review_context(str(repo), Path(interpreter).resolve()) if case["read_only"] else None)
    status, refusal, measurement, prompts = "composed", None, None, []
    try:
        composed = composer.compose(request)
        composer.retain(composed, case["key"])
        prompts.append(composed.rendered)
        measurement = composed.measurement
    except Exception as exc:  # noqa: BLE001 - the refusal type and reason are the result
        status, refusal = "refused", {"error": type(exc).__name__, "message": str(exc)[:400]}
    with store.transaction() as tx:
        rows = [(r["bucket"], r["id"], r["body"]) for r in tx.records()]
    return {"status": status, "refusal": refusal, "prompts": prompts, "puts": artifacts.puts,
            "bodies": artifacts.bodies, "rows": rows, "context_measurement": measurement}


if __name__ == "__main__":
    try:
        result = s2_composition.run(type("API", (), {"compose": staticmethod(compose)}), world_factory)
    finally:
        s2_fixture.cleanup()
    driver.finish("target", "context.composition", result)
