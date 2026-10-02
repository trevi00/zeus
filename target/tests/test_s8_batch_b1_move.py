"""S8 batch B1 (intake): M7 `application/goal_progress.py` moves to `intake.application.goal_progress` with no rule beyond the import homes and the
header, and M7 `adapters/ticket_authority.py` moves to `intake.adapters.ticket_authority` with R-ta1 (the injected `run_process`, the spawn
chokepoint) and R-ta2 (the injected `clock`).

M7 is read only as text through `git show e38aa722:...` and compared by AST (never imported: both packages are named `codex_harness`). Behaviour is
compared by the recorded `intake.goal_progress` and `intake.ticket_authority` goldens (the wired modules are target-equal to them); the unwired
`run_process` refusal has no M7 counterpart and is pinned here.
"""

from __future__ import annotations

import ast
import base64
import inspect
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from codex_harness.intake.adapters import ticket_authority as authority
from codex_harness.intake.application import goal_progress as goal
from codex_harness.kernel.errors import ContractError
from codex_harness.kernel.ids import SYSTEM_CLOCK, canonical
from codex_harness.review.application import releases

REPO = Path(__file__).resolve().parents[2]
SOURCE = "e38aa722"
GOAL_M7 = "src/codex_harness/application/goal_progress.py"
AUTH_M7 = "src/codex_harness/adapters/ticket_authority.py"
BUCKET_WRITES = {"put", "delete"}


def m7_text(path):
    return subprocess.run(["git", "-C", str(REPO), "show", f"{SOURCE}:{path}"], check=True, capture_output=True, text=True).stdout


def text_of(module):
    return Path(module.__file__).read_text()


def statements(src):
    """Every top-level statement but the imports and the docstring, keyed by name (or position)."""
    out = {}
    for i, node in enumerate(ast.parse(src).body):
        if isinstance(node, (ast.Import, ast.ImportFrom)) or (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)):
            continue
        name = getattr(node, "name", None) or (node.targets[0].id if isinstance(node, ast.Assign) else i)
        out[name] = node
    return out


def import_modules(src):
    return sorted({n.module for n in ast.parse(src).body if isinstance(n, ast.ImportFrom)})


def calls(src, attr):
    return [n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == attr]


def header_lines(module):
    return ast.get_docstring(ast.parse(text_of(module)))


# ---- goal_progress: no rule -------------------------------------------------------------------------------------------------
def test_goal_progress_every_statement_is_m7s():
    ours, theirs = statements(text_of(goal)), statements(m7_text(GOAL_M7))
    assert list(ours) == list(theirs) and len(theirs) == 18
    for name, node in theirs.items():
        assert ast.dump(ours[name]) == ast.dump(node), name


def test_goal_progress_import_homes_and_header():
    assert import_modules(text_of(goal)) == ["codex_harness.intake.application.ticket_lifecycle", "codex_harness.kernel.errors", "codex_harness.kernel.ids", "copy"]
    doc = header_lines(goal)
    assert doc.startswith(ast.get_docstring(ast.parse(m7_text(GOAL_M7))).split("\n\n")[0])
    for line in ("Layer: application", "Context: intake", "Owns:", "Does not own:", "Contracts: INV-GOAL-PROGRESS-001", "SOURCE " + SOURCE, "R-gp0"):
        assert line in doc


def test_goal_progress_writes_no_bucket_and_reads_only_the_ticket_buckets():
    tree = ast.parse(text_of(goal))
    assert not [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in BUCKET_WRITES]
    reads = sorted({n.args[0].value for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in {"get", "scan"}
                    and isinstance(n.func.value, ast.Name) and n.func.value.id == "tx" and n.args and isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str)})
    assert reads == ["ticket_closures", "ticket_revisions", "tickets"]


# ---- ticket_authority: R-ta0..R-ta2 --------------------------------------------------------------------------------------------------
def m7_authority_with_rules():
    """M7's text with R-ta1/R-ta2 applied as text: the independent expectation of the class."""
    text = m7_text(AUTH_M7)
    for old, new in (
        ("    def __init__(self, git, artifacts, trust_commit=None):\n        self.git, self.artifacts = git, artifacts\n",
         "    def __init__(self, git, artifacts, trust_commit=None, *, run_process=None, clock=None):\n        self.git, self.artifacts = git, artifacts\n"
         "        self.run_process, self.clock = run_process, clock\n"),
        ("                    result = run_process([", "                    require(self.run_process is not None, \"Process runner is not wired\")\n"
                                                      "                    result = self.run_process(["),
        ("        at = at or datetime.now(timezone.utc)\n", "        at = at or _now(self.clock)\n"),
        ("        finished = datetime.now(timezone.utc)\n", "        finished = _now(self.clock)\n"),
    ):
        assert text.count(old) == 1
        text = text.replace(old, new)
    return text


def test_ticket_authority_is_m7s_modulo_r_ta1_and_r_ta2():
    ours, expected, m7 = statements(text_of(authority)), statements(m7_authority_with_rules()), statements(m7_text(AUTH_M7))
    assert list(ours) == ["POLICY_PATH", "PRINCIPAL", "_now", "TicketAuthority"] and list(m7) == ["POLICY_PATH", "PRINCIPAL", "TicketAuthority"]
    for name in ("POLICY_PATH", "PRINCIPAL"):
        assert ast.dump(ours[name]) == ast.dump(m7[name])
    assert ast.dump(ours["TicketAuthority"]) == ast.dump(expected["TicketAuthority"])


def test_ticket_authority_import_homes_and_header():
    src = text_of(authority)
    assert import_modules(src) == ["codex_harness.intake.domain.ticket_lifecycle", "codex_harness.kernel.errors", "codex_harness.kernel.ids",
                                   "codex_harness.kernel.strict_json", "datetime", "pathlib"]
    doc = header_lines(authority)
    assert doc.startswith(ast.get_docstring(ast.parse(m7_text(AUTH_M7))))
    for line in ("Layer: adapters", "Context: intake", "Owns:", "Does not own:", "Entry points: TicketAuthority", "Contracts: INV-TICKET-001", "SOURCE " + SOURCE,
                 "R-ta1", "R-ta2"):
        assert line in doc


def test_ticket_authority_writes_no_bucket_and_spawns_nothing():
    src = text_of(authority)
    assert not [n for n in calls(src, "put") + calls(src, "delete")]
    for banned in ("subprocess", "Popen", "adapters.commands", "host_os"):
        assert banned not in src.replace(header_lines(authority), "")
    # the one environment read is the adapter's own configuration, as in M7
    assert [ast.unparse(n) for n in calls(src, "get") if ast.unparse(n).startswith("os.environ")] == ["os.environ.get('ZEUS_TICKET_TRUST_COMMIT')"]


def test_r_ta1_r_ta2_the_positional_shape_is_unchanged_and_the_ports_are_keyword_only():
    params = list(inspect.signature(authority.TicketAuthority.__init__).parameters.values())
    assert [p.name for p in params if p.kind is p.POSITIONAL_OR_KEYWORD] == ["self", "git", "artifacts", "trust_commit"]
    keyword = [p for p in params if p.kind is p.KEYWORD_ONLY]
    assert [(p.name, p.default) for p in keyword] == [("run_process", None), ("clock", None)]


def test_r_ta2_now_equals_the_review_seam_by_ast():
    ours = [n for n in ast.parse(text_of(authority)).body if isinstance(n, ast.FunctionDef) and n.name == "_now"]
    theirs = [n for n in ast.parse(text_of(releases)).body if isinstance(n, ast.FunctionDef) and n.name == "_now"]
    assert len(ours) == len(theirs) == 1 and ast.dump(ours[0]) == ast.dump(theirs[0])


def test_r_ta2_now_reads_the_injected_clock_and_defaults_to_the_system_clock():
    fixed = datetime(2026, 9, 22, 1, tzinfo=timezone(timedelta(hours=9)))
    assert authority._now(SimpleNamespace(now=lambda: fixed)) == fixed and authority._now(SimpleNamespace(now=lambda: fixed)).utcoffset() == timedelta(0)
    before = datetime.now(timezone.utc)
    assert before <= authority._now(None) <= before + timedelta(minutes=1) and authority._now(None).tzinfo is not None
    assert SYSTEM_CLOCK is authority.SYSTEM_CLOCK


# ---- R-ta1's refusal: no runner, refused at first use -----------------------------------------------------------------------------------
COMMIT = "a" * 40
PRINCIPAL = "test-only@zeus.invalid"


class ScriptedGit:
    def __init__(self, document):
        self.document, self.calls = document, []

    def _git(self, *args, cwd=None, strip=True):
        self.calls.append(args[0])
        return {"rev-parse": COMMIT, "ls-tree": "100644 blob " + "d" * 40 + "\t.zeus/ticket-trust.json", "show": canonical(self.document),
                "merge-base": "b" * 40}[args[0]]


class Artifacts:
    def __init__(self):
        self.bodies = {}

    def text(self, ref, max_bytes):
        return self.bodies[ref]


def setup(**ports):
    document = {"version": 1, "scope": "test-only", "signers": [{"principal": PRINCIPAL, "role": "automation",
                "public_key": "ssh-ed25519 " + base64.b64encode(b"\x01" * 32).decode(), "valid_after": "2020-01-01T00:00:00+00:00",
                "valid_before": "2099-01-01T00:00:00+00:00"}], "required_signers": [PRINCIPAL], "required_human_signers": [], "revoked": [],
                "max_evidence_age_seconds": 86400}
    git, artifacts = ScriptedGit(document), Artifacts()
    auth = authority.TicketAuthority(git, artifacts, COMMIT, **ports)
    policy = auth.policy()
    packet = {"policy_commit": COMMIT, "policy_hash": policy["policy_hash"], "scope": "test-only", "issued_at": "2026-09-22T00:00:00+00:00",
              "solution_commit": "b" * 40}
    artifacts.bodies["sha256:" + "1" * 64] = canonical(packet)
    artifacts.bodies["sha256:" + "2" * 64] = "SIGNATURE\n"
    return auth, git, packet, [{"principal": PRINCIPAL, "signature_ref": "sha256:" + "2" * 64}]


def test_r_ta1_without_a_runner_verify_is_refused_at_the_one_call_and_nothing_spawned():
    auth, git, packet, signatures = setup()
    assert auth.run_process is None
    with pytest.raises(ContractError, match="Process runner is not wired"):
        auth.verify("sha256:" + "1" * 64, packet, signatures, at=datetime(2026, 9, 22, tzinfo=timezone.utc))
    assert "merge-base" not in git.calls   # refused before the merged-commit check, i.e. at the first use of the port


def test_r_ta1_r_ta2_the_wired_ports_are_the_only_runner_and_clock():
    seen = []

    def runner(argv, **kwargs):
        seen.append((argv[:3], sorted(kwargs)))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    moment = datetime(2026, 9, 22, 12, tzinfo=timezone.utc)
    auth, _, packet, signatures = setup(run_process=runner, clock=SimpleNamespace(now=lambda: moment))
    record = auth.verify("sha256:" + "1" * 64, packet, signatures)
    assert seen == [(["ssh-keygen", "-Y", "verify"], ["env", "input_text", "timeout"])]
    assert record["verified_at"] == moment.isoformat() and [s["principal"] for s in record["signatures"]] == [PRINCIPAL]
