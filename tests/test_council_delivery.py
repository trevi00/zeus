"""Conductor delivery batch (research-program-001 run003): council debate inputs are delivered as REQUIRED
lossless context through the real executor/compiler path; the raw artifact and RFC 6901 pointers stay exact.

Every fixture here is SYNTHETIC and labelled; no model is called (the runtime is a fake that records the
prompt). Fixture sizes are matched to the owner's measured run003 facts (details 32119 bytes, 22000 usable),
not to a live timing claim.
"""
import copy
import inspect
import json
import subprocess

import pytest
from test_autonomous_roles import CRITICAL, MINOR

from codex_harness.adapters.app_server import READ_ONLY_INSTRUCTIONS
from codex_harness.adapters.artifacts import FileArtifacts
from codex_harness.adapters.autonomous_roles import (
    COUNCIL_DEBATE_ROLES,
    OBJECTIVES,
    council_delivery,
    execute_role,
    role_context,
    role_schema,
)
from codex_harness.adapters.executor import (
    ARTIFACT_READER,
    DELIVERY_ARTIFACT_READER,
    VERDICT,
    Executor,
)
from codex_harness.adapters.isolated_worker import isolated_review_context
from codex_harness.adapters.store import MemoryStore
from codex_harness.application.service import Harness
from codex_harness.bootstrap import organization
from codex_harness.domain.council import AGENTS
from codex_harness.domain.dge import DECISIONS, VERDICTS
from codex_harness.domain.model import ContractError, canonical

BASE = "a" * 40
SNAP, REPORT, PACKET_DIGEST = "1" * 64, "2" * 64, "3" * 64
KOREAN = "한글 증거 " * 40  # Unicode body (synthetic)
LARGE_CRITICAL = {**CRITICAL, "id": "f-large", "scenario": "large critical finding " + "x" * 3000,
                  "trigger": KOREAN, "impact": "packet refused after a paid start", "mitigation": "enum from CLAIM_KINDS"}
TRANSITION = {"compatibility": "additive", "rollback": "revert", "retirement": "none"}


def packet(claims: int, text_bytes: int) -> dict:
    return {"objective": "synthetic objective", "claims": [{"id": "c" + str(i), "kind": "fact", "text": "claim " + str(i) + " " + "y" * text_bytes,
                                                             "source_ids": ["s1"]} for i in range(claims)],
            "questions": [{"id": "q1", "question": "which?", "blocking": True, "status": "answered", "claim_ids": ["c0"]}],
            "sources": [{"id": "s1", "path": "docs/contracts.md", "sha256": "b" * 64, "locator": "git", "revision": BASE, "read_scope": "all"}]}


def details_for(role: str, *, claims: int = 4, text_bytes: int = 40, ssot_bytes: int = 200, prior_bytes: int = 200) -> dict:
    """SYNTHETIC council task details shaped like application/council.py builds them."""
    research_proposal = {"summary": "proposal " + KOREAN, "claim_ids": ["c0"], "snapshot_digest": SNAP, "report_digest": REPORT}
    improvement_proposal = {"summary": "alternative", "decision": "migrate", "rationale": "r", "transition": TRANSITION,
                            "claim_ids": ["c0"], "findings": [LARGE_CRITICAL, MINOR], "snapshot_digest": SNAP, "report_digest": REPORT}
    prior = {"research_lead": {"event_id": "e1", "slot": "proposer", "payload": research_proposal, "proposal": research_proposal,
                               "binding": {"task_id": "t-research", "filler": "p" * prior_bytes}}}
    if role == "conductor":
        prior["improvement_lead"] = {"event_id": "e2", "slot": "attacker", "payload": {"findings": improvement_proposal["findings"]},
                                     "proposal": improvement_proposal, "binding": {"task_id": "t-improve", "filler": "p" * prior_bytes}}
    details = {"role": role, "run_id": "run-synthetic", "base_revision": BASE, "packet_digest": PACKET_DIGEST,
               "packet": packet(claims, text_bytes), "ssot": {"searched_paths": ["src"], "evidence": ["z" * ssot_bytes], "decision": "improve"},
               "round": 1, "prior_outputs": prior if role != "research_lead" else {},
               "snapshot_digest": SNAP, "report_digest": REPORT,
               "dba_report": {"snapshot_digest": SNAP, "summary": "records observed " + KOREAN, "claim_ids": ["c0"], "unknowns": ["u1"]},
               "relay": {"dba_task_id": "t-dba", "message_id": "m1", "via": "conductor"},
               "acceptance_criteria": [CRITICAL["criterion"]], "blocker_rule": "critical only: concrete reachable trigger"}
    if role in ("improvement_lead", "conductor"):
        details["research_proposal"] = research_proposal
    if role == "conductor":
        details["improvement_proposal"] = improvement_proposal
    return details


class FakeGit:
    """Synthetic clean checkout at base: rev-parse HEAD == base, status --porcelain empty."""

    def __init__(self, tmp_path):
        self.root = tmp_path / "review"
        self.root.mkdir()

    def review_workspace(self, base, task_id):
        return str(self.root)

    def _git(self, *args, cwd=None, strip=True):
        if args[:2] == ("rev-parse", "HEAD"):
            return BASE
        if args[:2] == ("status", "--porcelain"):
            return ""
        return "revision"  # other read-only git reads, as the sibling fixtures answer them


def harness(tmp_path, monkeypatch, answer=None, entered=None):
    prompts = []

    class Runtime:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def run(self, prompt, cwd, schema, timeout, **kwargs):
            prompts.append(json.loads(prompt))
            assert len(prompt.encode("utf-8")) <= 22000, "the compiler window minus reserve"
            return {"answer": answer, "events": [], "thread_id": "thread", "turn_id": "turn", "usage": None,
                    "rotate": False, "interrupted": False, "requested_model": kwargs.get("model")}

    def forbidden(**kwargs):
        pytest.fail("provider must not be entered")

    monkeypatch.setattr("codex_harness.adapters.executor.AppServer", Runtime if entered is None or entered else forbidden)
    artifacts = FileArtifacts(str(tmp_path / "artifacts"))
    executor = Executor(Harness(MemoryStore(), organization()), FakeGit(tmp_path), artifacts)
    return executor, artifacts, prompts


def deliver(executor, role, details):
    """The exact `_run` call execute_role makes, without a store-owned lease (this unit harness has no claimed
    task row); the lease-bound wiring is exercised by the refusal tests through execute_role itself."""
    return executor._run(AGENTS[role], "task-" + role, OBJECTIVES[role], details, str(executor.git.root),
                         role_schema(role, details), True, None, None, stage="dge:" + role, workload="design",
                         action="dge_role", max_handoffs=1, delivery=council_delivery(role, details))


def task_for(role, details):
    return {"id": "task-" + role, "agent": AGENTS[role], "attempt": 1,
            "message": {"what": {"action": "dge_role", "details": details}, "where": {"revision": BASE}}}


CONDUCTOR_ANSWER = {"verdict": "accept", "rationale": "r", "research_question": None, "snapshot_digest": SNAP, "report_digest": REPORT,
                    "dispositions": [{"finding_id": "f-large", "decision": "resolved", "reason": "enum"},
                                     {"finding_id": "f2", "decision": "deferred", "reason": "backlog"}]}
ANSWERS = {"research_lead": {"summary": "s", "claim_ids": ["c0"], "snapshot_digest": SNAP, "report_digest": REPORT},
           "improvement_lead": {"summary": "s", "decision": "reuse", "rationale": "r", "transition": None, "claim_ids": ["c0"],
                                "findings": [], "snapshot_digest": SNAP, "report_digest": REPORT},
           "conductor": CONDUCTOR_ANSWER}


@pytest.mark.parametrize("role", COUNCIL_DEBATE_ROLES)
def test_debate_roles_receive_the_lossless_projection_inline_and_the_exact_artifact_by_pointer(tmp_path, monkeypatch, role):
    details = details_for(role)
    frozen = copy.deepcopy(details)
    executor, artifacts, prompts = harness(tmp_path, monkeypatch, answer=ANSWERS[role])
    result = deliver(executor, role, details)
    assert result["execution_ref"].startswith("sha256:") and result["basis_revision"] == BASE
    assert details == frozen, "the projection never mutates the task details"
    [prompt] = prompts
    delivery = prompt["required"]["council_delivery"]
    inline = delivery["inline"]
    for key in ("role", "run_id", "base_revision", "round", "packet", "packet_digest", "dba_report", "snapshot_digest",
                "report_digest", "relay", "acceptance_criteria", "blocker_rule"):
        assert inline[key] == details[key], key
    if role != "research_lead":
        assert inline["research_proposal"] == details["research_proposal"]
    if role == "conductor":
        assert inline["improvement_proposal"] == details["improvement_proposal"]
        assert inline["improvement_proposal"]["findings"][0] == LARGE_CRITICAL, "large critical finding delivered whole"
        assert KOREAN in inline["dba_report"]["summary"], "Unicode preserved"
    assert "ssot" not in inline and "prior_outputs" not in inline
    assert set(delivery["not_inline"]) == {"ssot", "prior_outputs"} and delivery["not_inline"]["ssot"]["pointer"] == "/ssot"
    # The raw task is not duplicated as optional evidence and nothing was omitted for budget.
    assert prompt["evidence"] == []
    # Phase-correct context (whole-layout revision: phase, isolation identity and instruction only): no candidate,
    # worker or verifier is asserted; the read-only rule stays.
    context = prompt["required"]["role_context"]
    assert "review_context" not in prompt["required"]
    assert set(context) == {"phase", "isolation", "instruction"} and context["phase"] == "pre_implementation"
    assert "no candidate, worker or verifier has run" in context["instruction"]
    assert "Do not execute code/tests/scripts or change files" in context["instruction"]
    # Whole-layout revision, delivery path only: every contract field is inline so the empty task_contract is
    # omitted, and a prompt without recovery sources carries the bare empty source map.
    assert "task_contract" not in prompt["required"] and prompt["required"]["recovery"] == {"sources": {}}
    # The original artifact is the exact canonical task details, and the pointer read returns the exact ssot.
    external = prompt["required"]["external_context"]
    assert artifacts._body(external["ref"]) == canonical(details)
    # Delivery reader descriptor (SPEC "Final scoped delivery fix"): ref plus exact argv prefix once, no derivable
    # file path; the reader block is the concise argv/quoting/cursor/output contract, the operations live in
    # not_inline only.
    assert set(external) == {"ref", "reader_argv_prefix"} and external["reader_argv_prefix"][-1] == external["ref"]
    reader = prompt["required"]["artifact_reader"]
    assert reader == DELIVERY_ARTIFACT_READER and "operations" not in reader
    for rule in ("reader_argv_prefix", "not_inline", "quote", "argv list", "next_cursor", "--limit"):
        assert rule in reader["instruction"] + reader["output"], rule
    argv = [*external["reader_argv_prefix"], *delivery["not_inline"]["ssot"]["operation"]]
    read = subprocess.run(argv, capture_output=True, check=False, text=True, encoding="utf-8")
    assert read.returncode == 0, read.stderr
    content = json.loads(read.stdout)["content"]
    assert json.loads(content if isinstance(content, str) else json.dumps(content)) == details["ssot"]


def projection_bytes(details: dict) -> int:
    """Canonical size of the task without the pointer fields: the owner's run003 denominator (17819 bytes)."""
    return len(canonical({k: v for k, v in details.items() if k not in ("ssot", "prior_outputs")}).encode("utf-8"))


def test_size_matched_synthetic_conductor_case_keeps_required_fields_inline_within_the_compiler_budget(tmp_path, monkeypatch):
    # SYNTHETIC size match to run003: whole details > 22000 bytes (owner fact: 32119), the inline part below it
    # (owner fact: 17819 without ssot/prior_outputs). This proves delivery under the compiler rule, not live latency.
    details = details_for("conductor", claims=40, text_bytes=100, ssot_bytes=9000, prior_bytes=6000)
    whole = len(canonical(details).encode("utf-8"))
    without = projection_bytes(details)
    assert whole > 22000 > without, (whole, without)
    executor, artifacts, prompts = harness(tmp_path, monkeypatch, answer=CONDUCTOR_ANSWER)
    deliver(executor, "conductor", details)
    [prompt] = prompts
    inline = prompt["required"]["council_delivery"]["inline"]
    assert inline["packet"] == details["packet"] and inline["improvement_proposal"] == details["improvement_proposal"]
    assert prompt["evidence"] == [] and artifacts._body(prompt["required"]["external_context"]["ref"]) == canonical(details)
    # The 9000-byte ssot exceeds one 8000-character page: the delivery pointer stays usable through the exact
    # next_cursor continuation the concise reader contract describes, and the pages rebuild the exact value.
    prefix = prompt["required"]["external_context"]["reader_argv_prefix"]
    operation = list(prompt["required"]["council_delivery"]["not_inline"]["ssot"]["operation"])
    pages, cursor = [], "0"
    while cursor is not None:
        operation[operation.index("--cursor") + 1] = cursor
        read = subprocess.run([*prefix, *operation], capture_output=True, check=False, text=True, encoding="utf-8")
        assert read.returncode == 0 and len(read.stdout) <= 8000, read.stderr
        page = json.loads(read.stdout)
        pages.append(page["content"])
        cursor = None if page["next_cursor"] is None else str(page["next_cursor"])
    assert len(pages) >= 2 and pages[0] != "" and json.loads("".join(pages)) == details["ssot"]


# Owner replay of the retained run003 conductor input (CONDUCTOR-REVIEW-001): projection 17819 bytes, complete
# required context 23377 bytes against the unchanged 22000 budget. The deciding regression measures the COMPLETE
# compiled prompt, not the projected dictionary alone.
OWNER_PROJECTION_BYTES = 17819
BUDGET = 22000


@pytest.fixture
def representative(tmp_path, monkeypatch):
    """SYNTHETIC/INJECTED representative metadata: a host isolation configuration (its summary reaches
    role_context), a deep artifact root in the reader argv prefix and a deep review checkout path."""
    from types import SimpleNamespace

    from codex_harness.adapters.isolated_worker import load_isolation

    prompts = []
    root = tmp_path / "workspaces" / "zeus" / "worktrees" / "research-program-001" / "conductor-delivery"
    root.mkdir(parents=True)
    executor, artifacts, prompts = harness(root, monkeypatch, answer=CONDUCTOR_ANSWER)
    executor.git.root = root / "review" / "run003-conductor-task-9e2f1c7a"
    executor.git.root.mkdir(parents=True)
    config = load_isolation({"ZEUS_WORKER_ISOLATION": "docker", "ZEUS_WORKER_IMAGE": "sha256:" + "c" * 64})
    executor.isolation = SimpleNamespace(config=config)  # INJECTED: only `.config` is read on the dge_role path
    return executor, artifacts, prompts, config


@pytest.mark.parametrize("role", COUNCIL_DEBATE_ROLES)
def test_complete_compiled_prompt_with_representative_metadata_fits_the_budget_for_every_debate_role(representative, role):
    executor, artifacts, prompts, config = representative
    details = details_for(role, claims=56, text_bytes=150, ssot_bytes=9000, prior_bytes=6000)
    if role == "conductor":
        assert projection_bytes(details) >= OWNER_PROJECTION_BYTES, projection_bytes(details)
    frozen = copy.deepcopy(details)
    deliver(executor, role, details)
    [prompt] = prompts
    rendered = canonical(prompt).encode("utf-8")
    sizes = {k: len(canonical(v).encode("utf-8")) for k, v in prompt["required"].items()}
    print("\n", role, "TOTAL", len(rendered), "projection", projection_bytes(details), sizes)
    assert len(rendered) <= BUDGET, (len(rendered), sizes)
    assert details == frozen
    inline = prompt["required"]["council_delivery"]["inline"]
    for key in ("packet", "dba_report", "acceptance_criteria", "blocker_rule", "relay"):
        assert inline[key] == details[key], key
    if role == "conductor":
        assert inline["improvement_proposal"]["findings"] == [LARGE_CRITICAL, MINOR]
    context = prompt["required"]["role_context"]
    assert set(context) == {"phase", "isolation", "instruction"} and context["phase"] == "pre_implementation"
    assert "no candidate, worker or verifier has run" in context["instruction"]
    assert context["isolation"] == {"mode": "docker", "digest": config["digest"]}
    assert "task_contract" not in prompt["required"] and prompt["required"]["recovery"] == {"sources": {}}
    assert artifacts._body(prompt["required"]["external_context"]["ref"]) == canonical(details)


@pytest.mark.parametrize("missing", ["packet", "dba_report", "report_digest", "improvement_proposal", "prior_outputs", "ssot"])
def test_missing_mandatory_council_input_is_refused_before_the_provider(tmp_path, monkeypatch, missing):
    details = {k: v for k, v in details_for("conductor").items() if k != missing}
    executor, _, _ = harness(tmp_path, monkeypatch, entered=False)
    with pytest.raises(ContractError, match="Council delivery input missing: " + missing):
        execute_role(executor, task_for("conductor", details), heartbeat=None)


def test_required_projection_overflow_is_refused_before_the_provider_with_nothing_omitted(tmp_path, monkeypatch):
    # INJECTED oversize: the mandatory inline part alone exceeds the usable window; the existing compiler rule
    # refuses the whole execution instead of silently dropping semantic content.
    details = details_for("conductor", claims=200, text_bytes=120)
    executor, _, _ = harness(tmp_path, monkeypatch, entered=False)
    with pytest.raises(ContractError, match="Required contract exceeds budget"):
        execute_role(executor, task_for("conductor", details), heartbeat=None)


def test_projection_is_a_deep_copy_and_pointers_are_exact_argv_lists():
    details = details_for("conductor")
    delivery = council_delivery("conductor", details)
    delivery["inline"]["packet"]["claims"].clear()
    delivery["inline"]["improvement_proposal"]["findings"][0]["id"] = "renamed"
    assert details["packet"]["claims"] and details["improvement_proposal"]["findings"][0]["id"] == "f-large"
    for name, entry in delivery["not_inline"].items():
        assert entry["operation"] == ["pointer", "--pointer", "/" + name, "--cursor", "0", "--limit", "8000"]
        assert all(isinstance(part, str) for part in entry["operation"]), "argv list, no shell string"
    for word in ("not_inline", "external_context", "reader_argv_prefix", "artifact_reader"):
        assert word in delivery["reading"], word
    with pytest.raises(ContractError, match="debate roles only"):
        council_delivery("dba", {**details, "role": "dba"})
    with pytest.raises(ContractError, match="role mismatch"):
        council_delivery("research_lead", details)
    # The phase rule is stated once, in the delivery guidance; the concise objective only points at it and keeps
    # the materiality rule, the declared enums and the digest echo.
    assert "council_delivery" in OBJECTIVES["conductor"] and "keep unknowns as unknowns" not in OBJECTIVES["conductor"]
    assert "keep unknowns as unknowns" in delivery["guidance"] and "material gap" in delivery["guidance"]
    assert "never defer a critical finding" in OBJECTIVES["conductor"] and "every finding" in OBJECTIVES["conductor"]
    assert all(v in OBJECTIVES["conductor"] for v in VERDICTS | DECISIONS)
    assert "snapshot_digest" in OBJECTIVES["conductor"] and "report_digest" in OBJECTIVES["conductor"]


def test_delivery_with_injected_recovery_sources_regains_the_full_reader_catalogue(tmp_path, monkeypatch):
    # INJECTED: a bound checkpoint and progress row for the same conductor task (a retried attempt). Recovery
    # sources list no operation in the delivery, so the prompt carries the full catalogue again; the delivery
    # descriptor itself is unchanged (no file path, exact pointers).
    details = details_for("conductor")
    executor, artifacts, prompts = harness(tmp_path, monkeypatch, answer=CONDUCTOR_ANSWER)
    binding = {"stage": "dge:conductor", "evidence_ref": artifacts.put(canonical(details), "probe")["ref"], "basis_revision": BASE}
    with executor.service.store.transaction() as tx:
        tx.put("sessions", AGENTS["conductor"], {"generation": 1, "checkpoint": {"task_id": "task-conductor", "research_binding": binding}})
        tx.put("execution_progress", "task-conductor", {"id": "task-conductor", "recent": [], "research_binding": binding})
    deliver(executor, "conductor", details)
    [prompt] = prompts
    sources = prompt["required"]["recovery"]["sources"]
    assert set(sources) == {"checkpoint", "progress"} and all(s["reader_argv_prefix"][-1] == s["ref"] for s in sources.values())
    assert "Before repeating tools" in prompt["required"]["recovery"]["instruction"], "nonempty recovery keeps its instruction"
    assert prompt["required"]["artifact_reader"] == ARTIFACT_READER
    assert set(prompt["required"]["external_context"]) == {"ref", "reader_argv_prefix"}
    assert prompt["required"]["external_context"]["ref"] == binding["evidence_ref"]
    assert prompt["required"]["council_delivery"]["not_inline"]["ssot"]["operation"][:3] == ["pointer", "--pointer", "/ssot"]


def test_real_candidate_review_control_keeps_its_isolation_instructions(tmp_path, monkeypatch):
    # Control: a review-phase read-only run still receives review_context (not role_context); the isolated
    # variant still states that worker and verifier ran, because in that phase they did.
    executor, _, prompts = harness(tmp_path, monkeypatch, answer={"accepted": True, "reason": "fixture", "blocked": False, "risks": [],
                                                                  "sre_assessment": "n/a", "arc42_assessment": "n/a"})
    executor._run("lead:improvement", "review", "Evaluate review_lead", {"candidate": {"revision": "c" * 40}},
                  str(tmp_path), VERDICT, read_only=True)
    [prompt] = prompts
    assert "review_context" in prompt["required"] and "role_context" not in prompt["required"]
    assert "council_delivery" not in prompt["required"] and prompt["evidence"][0]["id"] == prompt["required"]["external_context"]["ref"]
    assert "do not create frame" in prompt["required"]["review_context"]["instruction"]
    # Non-delivery reader contract unchanged: file path handle and the full four-operation catalogue.
    external = prompt["required"]["external_context"]
    assert set(external) == {"ref", "file", "reader_argv_prefix"} and external["file"].endswith(external["ref"][7:] + ".txt")
    assert prompt["required"]["artifact_reader"] == ARTIFACT_READER
    assert set(ARTIFACT_READER["operations"]) == {"index", "pointer", "page", "search"}
    # Generic path unchanged by the delivery-only layout: the (here empty) task_contract key and the recovery
    # instruction on an empty source map are still present.
    assert prompt["required"]["task_contract"] == {"candidate": {"revision": "c" * 40}}
    assert prompt["required"]["recovery"]["sources"] == {} and "Before repeating tools" in prompt["required"]["recovery"]["instruction"]
    # Static control on the unchanged isolated review context (its summary needs a full host config).
    assert "Worker and verifier ran in isolated containers" in inspect.getsource(isolated_review_context)
    assert "candidate" not in READ_ONLY_INSTRUCTIONS.split("whether any")[0].lower().replace("read-only assignment", "")
    assert "whether any candidate, worker or verifier exists" in READ_ONLY_INSTRUCTIONS
    context = role_context()
    assert set(context) == {"phase", "isolation", "instruction"} and context["isolation"] is None
    assert "no candidate, worker or verifier has run" in context["instruction"]
