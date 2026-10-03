"""Target driver: `context.composition_council` on the target tree, composed as S10 will compose it (DESIGN-s8 §30).

RunTask gets `council=research.adapters.autonomous_roles`, `feedback=research.adapters.correction_feedback` and
`composition_admission=CouncilCompositionAdmission()`; `RunTask._run` is called with `delivery=` /
`correction_feedback=` like the reference's M7 `Executor._run`, with the same fixture provider transport.
The rest follows the S2 target driver:

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
from types import SimpleNamespace

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

import determinism  # noqa: E402
import s2_fixture  # noqa: E402
import s8_council_composition  # noqa: E402
from codex_harness.context.adapters.composition_sources import (  # noqa: E402
    GitRepository,
    ProjectSkills,
    SkillHistoryRecorder,
)
from codex_harness.context.adapters.review_context import review_context  # noqa: E402
from codex_harness.context.application.compose import ContextComposer  # noqa: E402
from codex_harness.coordination.application.breaker import Breaker  # noqa: E402
from codex_harness.coordination.application.execution_records import ExecutionRecords  # noqa: E402
from codex_harness.coordination.application.invocation_admission import (  # noqa: E402
    InvocationBreaker,
)
from codex_harness.coordination.application.sessions import SessionCheckpoints  # noqa: E402
from codex_harness.coordination.application.task_ownership import TaskOwnership  # noqa: E402
from codex_harness.coordination.application.workflow import Workflow  # noqa: E402
from codex_harness.execution.adapters import execution_output, output_schema  # noqa: E402
from codex_harness.execution.adapters.containers import handoff  # noqa: E402
from codex_harness.execution.adapters.transports import Transports  # noqa: E402
from codex_harness.execution.application.invocation_ledger import InvocationLedger  # noqa: E402
from codex_harness.execution.application.run_task import RunTask  # noqa: E402
from codex_harness.execution.domain import output_contracts  # noqa: E402
from codex_harness.host_os.adapters.git_workspace import GitWorkspace  # noqa: E402
from codex_harness.intake.application import tickets  # noqa: E402
from codex_harness.kernel.ids import digest, utcnow  # noqa: E402
from codex_harness.knowledge.adapters.context_hits import KnowledgeHits  # noqa: E402
from codex_harness.observation.adapters.observation_spool import MemorySpool  # noqa: E402
from codex_harness.observation.application.observations import (  # noqa: E402
    MemoryDirectory,
    Observer,
    PostExecutionRecordFailure,
    ReconciliationRequired,
)
from codex_harness.research.adapters import autonomous_roles, correction_feedback  # noqa: E402
from codex_harness.research.adapters.council_composition import (  # noqa: E402
    CouncilCompositionAdmission,
)
from codex_harness.research.application.audit_gate import (  # noqa: E402
    inspect_approval,
    require_adoption,
)
from codex_harness.routing.adapters.organization_source import packaged_organization  # noqa: E402
from codex_harness.routing.adapters.provider_policy import host_policy  # noqa: E402
from codex_harness.storage.adapters.file_artifacts import FileArtifacts  # noqa: E402
from codex_harness.storage.adapters.memory_store import MemoryStore  # noqa: E402
from s1_target import PortClock, PortIds  # noqa: E402

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


class ClaudeRefused:
    """The unexpected transport: constructing it is a driver failure, never a provider call."""

    def __init__(self, *args, **kwargs):
        raise AssertionError("ClaudeCodeRuntime reached in a council-composition fixture")


def no_operations(tx, message):
    return None


def compose(case: dict, world: dict) -> dict:
    case = dict(case)
    delivery = None
    if case.get("role"):
        role, details = case["role"], case["details"]
        case["agent"], case["evidence"] = autonomous_roles.AGENTS[role], details
        case["objective"] = autonomous_roles.role_objective(role, details) + "x" * case.get("objective_pad", 0)
        delivery = autonomous_roles.council_delivery(role, {**details, "run_id": "other"} if case.get("foreign")
                                                     else details)
        if case.get("recovery"):
            case["seed"] = s8_council_composition.recovery_rows(case["agent"], case, world[case["repo"]])
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

    org, ids = packaged_organization(), PortIds(IDS)
    interpreter = Path(world["interpreter"])
    observer = Observer(store, MemorySpool(ids.uuid4().hex), component="executor", directory=MemoryDirectory(),
                        clock=lambda: utcnow(CLOCK_PORT), monotonic=CLOCK.monotonic)
    workflow = Workflow(store, org, ticket_binding=tickets.ticket_binding, TicketSuperseded=tickets.TicketSuperseded,
                        adoption=require_adoption, park_terminal=no_operations, clock=CLOCK_PORT, ids=ids,
                        monotonic=CLOCK.monotonic)
    composer = ContextComposer(artifacts, artifacts.root, GitRepository(git),
                               ProjectSkills(git, artifacts, FixtureThresholds()),
                               SkillHistoryRecorder(store, artifacts, git, CLOCK_PORT), knowledge)
    results = SimpleNamespace(persist=execution_output.persist_result, tool_usage=execution_output.tool_usage,
                              preflight=output_schema.preflight, handoff_refs=handoff.handoff_refs,
                              retain_evidence_handoff=handoff.retain_evidence_handoff)
    run_task = RunTask(
        store, org, git, artifacts,
        ledger=TaskOwnership(workflow, store=store, clock=CLOCK_PORT, ids=ids, monotonic=CLOCK.monotonic),
        admission=InvocationBreaker(Breaker(store, clock=CLOCK_PORT)),
        invocations=InvocationLedger(store, clock=CLOCK_PORT),
        sessions=SessionCheckpoints(store, org, workflow=workflow, ids=ids), records=ExecutionRecords(org),
        observer=observer, composer=composer,
        transports=Transports(host_app_server=FixtureTransport, host_hooks=lambda: {}, claude_runtime=ClaudeRefused),
        results=results, execution_policy=host_policy({}),
        review_context=lambda cwd: review_context(cwd, interpreter.resolve()), host_python=str(interpreter),
        ticket_binding=tickets.ticket_binding, inspect_approval=inspect_approval,
        ReconciliationRequired=ReconciliationRequired, PostExecutionRecordFailure=PostExecutionRecordFailure,
        knowledge=knowledge, council=autonomous_roles, feedback=correction_feedback,
        composition_admission=CouncilCompositionAdmission(), clock=CLOCK_PORT, ids=ids,
        monotonic=CLOCK.monotonic)
    schema = (autonomous_roles.role_schema(case["role"], case["details"]) if case["schema"] == "ROLE"
              else getattr(output_contracts, case["schema"]))
    status, refusal, measurement = "composed", None, None
    try:
        result = run_task._run(case["agent"], case["key"], case["objective"], case["evidence"], str(repo), schema,
                               case["read_only"], None, None, stage=case["stage"], workload=case["workload"],
                               action=case["action"], max_handoffs=1, delivery=delivery,
                               correction_feedback=case.get("feedback"))
        record = json.loads(artifacts.bodies[result["execution_ref"]])
        measurement = record.get("context_measurement")
    except Exception as exc:  # noqa: BLE001 - the refusal type and reason are the result
        status, refusal = "refused", {"error": type(exc).__name__, "message": str(exc)[:400]}
    with store.transaction() as tx:
        rows = [(r["bucket"], r["id"], r["body"]) for r in tx.records()]
    return {"status": status, "refusal": refusal, "prompts": prompts,
            "puts": [p for p in artifacts.puts if not p["source"].startswith(("execution", "runtime-"))],
            "bodies": artifacts.bodies, "rows": rows, "context_measurement": measurement}


if __name__ == "__main__":
    try:
        result = s8_council_composition.run(type("API", (), {"compose": staticmethod(compose)}), world_factory)
    finally:
        s2_fixture.cleanup()
    driver.finish("target", "context.composition_council", result)
