"""CI wiring discriminator (Codex S0 F2; REBUILD-DESIGN-v2 §5.1, S0 exit checks 6 and 8).

The candidate workflow must keep every M7 command of the `test` and `integration` jobs in order,
run the unchanged reference tests (the test-job suite and the integration job's `check.py
--integration`, which includes it) in the immutable SOURCE tree, whose own workflow fixture stays
M7 so `tests/test_ci_scope.py` keeps its original assertions, and gate the target checks,
source-tree preservation and the reference comparison inside the jobs the CI gate requires.
Removing any of them fails here.
"""

import copy
import json
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "validation.yml"
SOURCE = json.loads((ROOT / "compare" / "baseline.json").read_text(encoding="utf-8"))["source"]["commit"]
SOURCE_DIR = "${{ runner.temp }}/zeus-source"

M7_TEST = ["python -m pip install uv==0.12.2", "uv sync --frozen", "uv run ruff check .",
           "uv run pytest -q", "uv build", "uv run harness-supervisor --help", "uv run zeus --version",
           "uv run python -m zeus ticket --help", "uv run zeus-monitor --help"]
M7_INTEGRATION = ["python -m pip install uv==0.12.2", "uv sync --frozen", "uv run harness setup",
                  "docker compose version", "docker compose -p harness-ci up -d --wait postgres redis",
                  "uv run python scripts/check.py --integration",
                  "uv run pytest -q tests/test_verification.py tests/test_host_interruption.py",
                  "docker compose -p harness-ci down --volumes"]
SOURCE_STEPS = [(f'git worktree add --detach "$RUNNER_TEMP/zeus-source" {SOURCE}', None),
                ("uv sync --frozen", SOURCE_DIR), ("uv run pytest -q", SOURCE_DIR)]
REBUILD_TEST_STEPS = [("python compare/run.py check-tree", None),
                      ("uv sync --frozen --project target", None),
                      ("uv run --project target ruff check target", None),
                      ("uv run pytest -q", "target"),
                      ("uv build --project target", None),
                      ("python compare/run.py prepare", None),
                      ("python compare/run.py run", None)]
REBUILD_INTEGRATION_STEPS = [("uv sync --frozen --project target", None),  # before the decision unit (S4 target)
                             ("python compare/run.py prepare", None),
                             ("python compare/run.py run --only effects.decision_unit.pg --pg", None),
                             ("python compare/run.py run --only effects.admission_unit.pg --pg", None),
                             ("python compare/run.py run --only effects.continuation_units.pg --pg", None),
                             ("python compare/run.py run --only storage.pg --only storage.redis --pg --redis", None),
                             ("python compare/run.py target-integration", None),
                             ("python compare/run.py docker-fixture", None)]


def load():
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def steps(job):
    return [(s["run"], s.get("working-directory")) for s in job["steps"] if "run" in s]


def subsequence(needle, hay) -> bool:
    it = iter(hay)
    return all(any(item == h for h in it) for item in needle)


def wiring_problems(workflow) -> list[str]:
    problems = []
    jobs = workflow["jobs"]
    if list(jobs) != ["changes", "docs", "test", "integration", "gate"]:
        problems.append("job list changed: the CI gate requires changes/docs/test/integration")
    if jobs["gate"]["needs"] != ["changes", "docs", "test", "integration"]:
        problems.append("gate needs changed")
    if "main" not in workflow[True]["push"]["branches"]:
        problems.append("main push trigger lost")
    if not any(b.startswith("rebuild/") for b in workflow[True]["push"]["branches"]):
        problems.append("rebuild branch pushes do not run the gate")
    test = steps(jobs["test"])
    root = [(cmd, None) for cmd in M7_TEST if cmd != "uv run pytest -q"]
    if not subsequence(root, test):
        problems.append("an M7 test-job command is missing or reordered in the candidate root")
    if not subsequence(SOURCE_STEPS, test):
        problems.append("the reference tests do not run in the immutable SOURCE tree")
    if ("uv run pytest -q", None) in test:
        problems.append("the reference suite runs in the candidate tree instead of SOURCE")
    if not subsequence(REBUILD_TEST_STEPS, test):
        problems.append("a rebuild gate (check-tree, target, comparison) is missing from the test job")
    integration = steps(jobs["integration"])
    if not subsequence([M7_INTEGRATION[0], SOURCE_STEPS[0][0]], [cmd for cmd, _ in integration]):
        problems.append("the integration job does not create the SOURCE tree")
    if not subsequence([(cmd, SOURCE_DIR) for cmd in M7_INTEGRATION[1:]], integration):
        problems.append("an M7 integration command is missing, reordered or not run in the SOURCE tree")
    if any(cmd in M7_INTEGRATION[1:] and directory != SOURCE_DIR for cmd, directory in integration):
        problems.append("an M7 integration command runs in the candidate tree instead of SOURCE")
    if not subsequence(REBUILD_INTEGRATION_STEPS, integration):
        problems.append("the PostgreSQL decision-unit discriminators are not in the integration job")
    if jobs["integration"]["steps"][-1].get("if") != "always()":
        problems.append("compose teardown is no longer the final always() step")
    for name, job in jobs.items():
        if job.get("continue-on-error") or any(s.get("continue-on-error") for s in job["steps"]):
            problems.append(f"{name}: continue-on-error would hide a failure")
    return problems


def test_candidate_workflow_is_wired():
    assert wiring_problems(load()) == []


def _drop(workflow, job, command, directory=None):
    changed = copy.deepcopy(workflow)
    changed["jobs"][job]["steps"] = [s for s in changed["jobs"][job]["steps"]
                                     if not (s.get("run") == command
                                             and s.get("working-directory") == directory)]
    assert changed != workflow, (job, command)
    return changed


@pytest.mark.parametrize("command,directory", REBUILD_TEST_STEPS + SOURCE_STEPS)
def test_omitting_a_test_job_gate_fails(command, directory):
    assert wiring_problems(_drop(load(), "test", command, directory))


@pytest.mark.parametrize("command,directory", REBUILD_INTEGRATION_STEPS
                         + [(cmd, SOURCE_DIR) for cmd in M7_INTEGRATION[1:]])
def test_omitting_an_integration_step_fails(command, directory):
    assert wiring_problems(_drop(load(), "integration", command, directory))


def test_running_the_integration_suite_in_the_candidate_tree_fails():
    workflow = load()
    for step in workflow["jobs"]["integration"]["steps"]:
        if step.get("run") == "uv run python scripts/check.py --integration":
            del step["working-directory"]
    assert wiring_problems(workflow)


def test_running_the_reference_suite_in_the_candidate_tree_fails():
    workflow = load()
    for step in workflow["jobs"]["test"]["steps"]:
        if step.get("run") == "uv run pytest -q" and step.get("working-directory") == SOURCE_DIR:
            del step["working-directory"]
    assert "the reference suite runs in the candidate tree instead of SOURCE" in wiring_problems(workflow)


def test_a_moved_source_commit_fails():
    workflow = load()
    for step in workflow["jobs"]["test"]["steps"]:
        if step.get("run", "").startswith("git worktree add"):
            step["run"] = step["run"].replace(SOURCE, "HEAD")
    assert wiring_problems(workflow)


def test_dropping_an_m7_command_or_adding_continue_on_error_fails():
    assert wiring_problems(_drop(load(), "test", "uv run zeus --version"))
    workflow = load()
    workflow["jobs"]["test"]["steps"][-1]["continue-on-error"] = True
    assert wiring_problems(workflow)


def test_the_source_tree_workflow_fixture_is_still_m7():
    """The reference assertion reads SOURCE's own workflow, whose test-job commands are exactly M7."""
    import subprocess

    text = subprocess.run(["git", "show", f"{SOURCE}:.github/workflows/validation.yml"], cwd=ROOT,
                          capture_output=True, text=True, check=True).stdout
    source = yaml.safe_load(text)
    assert [s["run"] for s in source["jobs"]["test"]["steps"] if "run" in s] == M7_TEST
    assert [s["run"] for s in source["jobs"]["integration"]["steps"] if "run" in s] == M7_INTEGRATION
