"""CI scope routing (docs/zeus/operations/ci-separation-001/SPEC.md): docs-only changes take the
lightweight route, everything uncertain takes the full matrix, and the gate never passes by default.

Change sets are real commits in disposable repositories, built with Git plumbing so that newline
paths, symlink and executable modes exist in history on every host without touching the disk.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
DOC = "docs/zeus/operations/ci-separation-001/OPERATIONS.md"
SHA_A = "a" * 40


@pytest.fixture(scope="module")
def scope():
    spec = importlib.util.spec_from_file_location("zeus_ci_scope", ROOT / "scripts" / "ci_scope.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses resolve annotations through sys.modules
    spec.loader.exec_module(module)
    return module


def git(repo, *args, data=None):
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True,
                          input=data).stdout.decode("utf-8", "surrogateescape").strip()


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.email", "ci@example.invalid")
    git(tmp_path, "config", "user.name", "ci")
    git(tmp_path, "config", "commit.gpgsign", "false")
    return tmp_path


def commit(repo, parent, files, message="change"):
    """files: {path: (mode, bytes)} or {path: None} for removal; returns the new commit sha."""
    git(repo, "read-tree", parent) if parent else git(repo, "read-tree", "--empty")
    entries = b""
    for path, spec in files.items():
        if spec is None:
            entries += b"0 " + b"0" * 40 + b"\t" + path.encode() + b"\0"
        else:
            blob = git(repo, "hash-object", "-w", "--stdin", data=spec[1])
            entries += f"{spec[0]} {blob}\t{path}\0".encode()
    git(repo, "update-index", "-z", "--index-info", data=entries)
    tree = git(repo, "write-tree")
    args = ["commit-tree", tree, "-m", message] + (["-p", parent] if parent else [])
    return git(repo, *args)


@pytest.fixture
def base(repo):
    return commit(repo, None, {"src/app.py": ("100644", b"x = 1\n"),
                               "docs/zeus/operations/old/NOTE.md": ("100644", b"# old\n"),
                               "docs/contracts.md": ("100644", b"# contracts\n")})


def pr_event(base, head):
    return {"pull_request": {"base": {"sha": base}, "head": {"sha": head}, "title": "$(rm -rf)"}}


def run(scope, monkeypatch, tmp_path, repo, command, event_name, event, capsys):
    """Execute one subcommand under a GitHub-like environment; returns (code, outputs, stdout)."""
    event_path, output, summary = tmp_path / "event.json", tmp_path / "out", tmp_path / "summary"
    event_path.write_text(json.dumps(event), encoding="utf-8")
    for key, value in {"GITHUB_EVENT_NAME": event_name, "GITHUB_EVENT_PATH": str(event_path),
                       "GITHUB_OUTPUT": str(output), "GITHUB_STEP_SUMMARY": str(summary),
                       "GITHUB_WORKSPACE": str(repo)}.items():
        monkeypatch.setenv(key, value)
    code = scope.main([command])
    outputs = dict(line.split("=", 1) for line in output.read_text(encoding="utf-8").splitlines()) \
        if output.exists() else {}
    return code, outputs, capsys.readouterr().out


DOCS_ONLY = {"docs/zeus/operations/x/RUN.md": ("100644", b"# run\n")}
FULL_CASES = {
    "runtime": {"src/app.py": ("100644", b"x = 2\n")},
    "mixed": {"src/app.py": ("100644", b"x = 2\n"), **DOCS_ONLY},
    "rename code into docs": {"src/app.py": None, "docs/zeus/operations/app.md": ("100644", b"x = 1\n")},
    "contracts markdown": {"docs/contracts.md": ("100644", b"# changed\n")},
    "json under operations": {"docs/zeus/operations/x/data.json": ("100644", b"{}")},
    "workflow": {".github/workflows/validation.yml": ("100644", b"on: push\n")},
    "script": {"scripts/ci_scope.py": ("100644", b"")},
    "prefix lookalike": {"docs/zeus/operations-extra/a.md": ("100644", b"#")},
    "symlink markdown": {"docs/zeus/operations/x/link.md": ("120000", b"RUN.md")},
    "executable markdown": {"docs/zeus/operations/x/RUN.md": ("100755", b"# run\n")},
    "mode change only": {"docs/zeus/operations/old/NOTE.md": ("100755", b"# old\n")},
}


def test_docs_only_pull_request_routes_docs(scope, monkeypatch, tmp_path, repo, base, capsys):
    head = commit(repo, base, DOCS_ONLY)
    code, outputs, out = run(scope, monkeypatch, tmp_path, repo, "classify", "pull_request",
                             pr_event(base, head), capsys)
    assert (code, outputs["mode"], outputs["changed"]) == (0, "docs", "1")
    assert "mode=docs" in out and "Markdown" in out
    assert "mode: **docs**" in (tmp_path / "summary").read_text(encoding="utf-8")


def test_docs_only_main_push_routes_docs(scope, monkeypatch, tmp_path, repo, base, capsys):
    head = commit(repo, base, DOCS_ONLY)
    code, outputs, _ = run(scope, monkeypatch, tmp_path, repo, "classify", "push",
                           {"before": base, "after": head}, capsys)
    assert (code, outputs["mode"]) == (0, "docs")


def test_deleted_operations_markdown_routes_docs(scope, monkeypatch, tmp_path, repo, base, capsys):
    head = commit(repo, base, {"docs/zeus/operations/old/NOTE.md": None})
    code, outputs, _ = run(scope, monkeypatch, tmp_path, repo, "classify", "pull_request",
                           pr_event(base, head), capsys)
    assert (code, outputs["mode"]) == (0, "docs")


def test_awkward_path_bytes_stay_single_records(scope, monkeypatch, tmp_path, repo, base, capsys):
    names = ["docs/zeus/operations/ünï cödé/plan one.md"]
    if os.name != "nt":  # Git for Windows refuses control characters in index paths
        names += ["docs/zeus/operations/line\nbreak.md", "docs/zeus/operations/tab\there.md"]
    head = commit(repo, base, {name: ("100644", b"# ok\n") for name in names})
    code, outputs, _ = run(scope, monkeypatch, tmp_path, repo, "classify", "pull_request",
                           pr_event(base, head), capsys)
    assert (code, outputs["mode"], outputs["changed"]) == (0, "docs", str(len(names)))
    assert sorted(c.path for c in scope.decide(repo).changes) == sorted(names)


def test_raw_diff_parser_keeps_newline_paths_in_one_record(scope, monkeypatch):
    """Synthetic `git diff --raw -z` bytes (not a real history) exercise the parser on every host."""
    raw = (b":000000 100644 0000000 8aa429b A\0docs/zeus/operations/line\nbreak.md\0"
           b":100644 000000 8aa429b 0000000 D\0docs/zeus/operations/tab\there.md\0")
    monkeypatch.setattr(scope, "git", lambda args, repo: raw)
    changes = scope.diff_changes(SHA_A, SHA_A, Path("."))
    assert [c.path for c in changes] == ["docs/zeus/operations/line\nbreak.md",
                                         "docs/zeus/operations/tab\there.md"]
    assert scope.classify(changes).mode == "docs"
    for broken in (raw[:-1], raw + b"stray\0", b":100644 100644 a b R100\0old\0new\0"):
        monkeypatch.setattr(scope, "git", lambda args, repo, broken=broken: broken)
        with pytest.raises(scope.ScopeError):
            scope.diff_changes(SHA_A, SHA_A, Path("."))


@pytest.mark.parametrize("name", sorted(FULL_CASES))
def test_non_allowlisted_changes_route_full(scope, monkeypatch, tmp_path, repo, base, capsys, name):
    head = commit(repo, base, FULL_CASES[name])
    code, outputs, out = run(scope, monkeypatch, tmp_path, repo, "classify", "pull_request",
                             pr_event(base, head), capsys)
    assert (code, outputs["mode"]) == (0, "full"), name
    assert "reason=" in out and "\n" not in out.split("reason=", 1)[1].rstrip("\n")


def test_pull_request_range_is_merge_base_not_latest_commit(scope, monkeypatch, tmp_path, repo,
                                                            base, capsys):
    code_commit = commit(repo, base, {"src/app.py": ("100644", b"x = 3\n")})
    head = commit(repo, code_commit, DOCS_ONLY)
    main_moved = commit(repo, base, {"README.md": ("100644", b"# moved on\n")})
    code, outputs, _ = run(scope, monkeypatch, tmp_path, repo, "classify", "pull_request",
                           pr_event(main_moved, head), capsys)
    assert (code, outputs["mode"], outputs["changed"]) == (0, "full", "2")


@pytest.mark.parametrize("event_name, event", [
    ("push", {"before": "0" * 40, "after": SHA_A}),
    ("push", {"before": "HEAD~1", "after": "HEAD"}),
    ("push", {"after": SHA_A}),
    ("pull_request", {"pull_request": {"base": {"sha": SHA_A}, "head": {}}}),
    ("pull_request", {"pull_request": {"base": {"sha": 42}, "head": {"sha": SHA_A}}}),
    ("pull_request", {"pull_request": "docs only, trust me"}),
    ("pull_request", [SHA_A]),
    ("workflow_dispatch", {"inputs": {}}),
    ("", {}),
])
def test_malformed_or_unknown_events_route_full(scope, monkeypatch, tmp_path, repo, base, capsys,
                                                 event_name, event):
    code, outputs, out = run(scope, monkeypatch, tmp_path, repo, "classify", event_name, event,
                             capsys)
    assert (code, outputs["mode"], outputs["changed"]) == (0, "full", "0")
    assert "fallback" in out


def test_missing_objects_and_empty_diffs_route_full(scope, monkeypatch, tmp_path, repo, base,
                                                    capsys):
    for event in ({"before": base, "after": base}, {"before": base, "after": SHA_A},
                  {"before": SHA_A, "after": base}):
        code, outputs, _ = run(scope, monkeypatch, tmp_path, repo, "classify", "push", event, capsys)
        assert (code, outputs["mode"]) == (0, "full"), event


def test_unreadable_event_file_routes_full(scope, monkeypatch, tmp_path, repo, base, capsys):
    head = commit(repo, base, DOCS_ONLY)
    run(scope, monkeypatch, tmp_path, repo, "classify", "pull_request", pr_event(base, head), capsys)
    (tmp_path / "event.json").write_bytes(b"{not json")
    (tmp_path / "out").unlink()
    assert scope.main(["classify"]) == 0
    assert "mode=full" in (tmp_path / "out").read_text(encoding="utf-8")
    monkeypatch.delenv("GITHUB_EVENT_PATH")
    assert "fallback" in scope.decide(repo).reason


def test_classifier_crash_writes_no_mode(scope, monkeypatch, tmp_path, repo, base, capsys):
    """A broken git is not a routing fact: the job fails, so `changes` is not success at the gate."""
    head = commit(repo, base, DOCS_ONLY)

    def broken(args, repo):
        raise RuntimeError("injected fault: git binary unavailable")

    monkeypatch.setattr(scope, "git", broken)
    with pytest.raises(RuntimeError):
        run(scope, monkeypatch, tmp_path, repo, "classify", "pull_request", pr_event(base, head),
            capsys)
    assert not (tmp_path / "out").exists()
    ok, mode, _ = scope.evaluate_gate({"changes": {"result": "failure", "outputs": {}},
                                       "docs": {"result": "skipped"}, "test": {"result": "skipped"},
                                       "integration": {"result": "skipped"}})
    assert (ok, mode) == (False, "unknown")


def test_usage_error_is_nonzero(scope, capsys):
    assert scope.main([]) == 2 and scope.main(["deploy"]) == 2


# --- docs-check -----------------------------------------------------------------------------

def checkout(repo, sha):
    git(repo, "update-ref", "HEAD", sha)
    git(repo, "reset", "-q", "--hard")


def test_docs_check_validates_existing_markdown_and_reports_removed(scope, monkeypatch, tmp_path,
                                                                    repo, base, capsys):
    head = commit(repo, base, {"docs/zeus/operations/x/RUN.md": ("100644", "# ünï\n".encode()),
                               "docs/zeus/operations/old/NOTE.md": None})
    checkout(repo, head)
    code, _, out = run(scope, monkeypatch, tmp_path, repo, "docs-check", "pull_request",
                       pr_event(base, head), capsys)
    assert code == 0
    assert "removed 'docs/zeus/operations/old/NOTE.md'" in out and "checked=2 failures=0" in out


@pytest.mark.parametrize("content, problem", [(b"\xff\xfe# bad\n", "invalid UTF-8"),
                                              (b"# ok\0\n", "contains NUL")])
def test_docs_check_rejects_bad_bytes(scope, monkeypatch, tmp_path, repo, base, capsys, content,
                                      problem):
    head = commit(repo, base, {"docs/zeus/operations/x/RUN.md": ("100644", content)})
    checkout(repo, head)
    code, _, out = run(scope, monkeypatch, tmp_path, repo, "docs-check", "pull_request",
                       pr_event(base, head), capsys)
    assert code == 1 and problem in out


def test_docs_check_rejects_symlink_and_missing_file(scope, tmp_path):
    target = tmp_path / "RUN.md"
    target.write_text("# ok\n", encoding="utf-8")
    assert scope.check_markdown(target) is None
    assert scope.check_markdown(tmp_path / "absent.md") == "not a regular file"
    link = tmp_path / "link.md"
    try:
        os.symlink(target, link)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation not permitted on this host")
    assert scope.check_markdown(link) == "symlink"


def test_docs_check_refuses_full_mode(scope, monkeypatch, tmp_path, repo, base, capsys):
    head = commit(repo, base, FULL_CASES["mixed"])
    checkout(repo, head)
    code, _, out = run(scope, monkeypatch, tmp_path, repo, "docs-check", "pull_request",
                       pr_event(base, head), capsys)
    assert code == 1 and "refused: mode=full" in out
    code, _, out = run(scope, monkeypatch, tmp_path, repo, "docs-check", "workflow_dispatch", {},
                       capsys)
    assert code == 1 and "refused: mode=full" in out


# --- gate -----------------------------------------------------------------------------------

def needs(mode, changes="success", docs="skipped", test="success", integration="success"):
    return {"changes": {"result": changes, "outputs": {"mode": mode}}, "docs": {"result": docs},
            "test": {"result": test}, "integration": {"result": integration}}


def test_gate_passes_only_matching_matrices(scope, monkeypatch, capsys):
    assert scope.evaluate_gate(needs("full"))[:2] == (True, "full")
    assert scope.evaluate_gate(needs("docs", docs="success", test="skipped",
                                     integration="skipped"))[:2] == (True, "docs")
    monkeypatch.setenv("CI_NEEDS", json.dumps(needs("full")))
    assert scope.main(["gate"]) == 0
    out = capsys.readouterr().out
    assert "mode=full verdict=pass" in out and "integration=success" in out


@pytest.mark.parametrize("payload", [
    needs("full", test="failure"),
    needs("full", integration="cancelled"),
    needs("full", test="skipped"),
    needs("full", docs="success"),
    needs("full", changes="failure"),
    needs("full", changes="skipped"),
    needs("docs", docs="success", test="success", integration="skipped"),
    needs("docs", docs="skipped", test="skipped", integration="skipped"),
    needs("docs", docs="failure", test="skipped", integration="skipped"),
    needs("", test="skipped", integration="skipped"),
    needs(None),
    needs(True),
    needs("full", test=["success"]),
    {"changes": {"result": "success"}, "docs": {"result": "skipped"}},
    {"changes": {"result": "success", "outputs": {"mode": "full"}}, "docs": {"result": "skipped"},
     "test": {"result": "success"}},
    {"changes": "success", "docs": "skipped", "test": "success", "integration": "success"},
    [], None, "success",
])
def test_gate_fails_closed(scope, monkeypatch, capsys, payload):
    ok, _, lines = scope.evaluate_gate(payload)
    assert ok is False and lines
    monkeypatch.setenv("CI_NEEDS", json.dumps(payload))
    assert scope.main(["gate"]) == 1
    assert "verdict=FAIL" in capsys.readouterr().out


def test_gate_rejects_unparseable_or_missing_needs(scope, monkeypatch, capsys):
    monkeypatch.setenv("CI_NEEDS", "{success")
    assert scope.main(["gate"]) == 1
    monkeypatch.delenv("CI_NEEDS")
    assert scope.main(["gate"]) == 1


# --- workflow wiring ------------------------------------------------------------------------

@pytest.fixture(scope="module")
def workflow():
    # PyYAML reads YAML 1.1, so the bare `on` key parses as boolean True.
    return yaml.safe_load((ROOT / ".github/workflows/validation.yml").read_text(encoding="utf-8"))


def test_workflow_triggers_and_cancellation(workflow):
    triggers = workflow[True]
    assert set(triggers) == {"pull_request", "push", "workflow_dispatch"}
    assert triggers["push"] == {"branches": ["main"]}
    assert workflow["permissions"] == {"contents": "read"}
    assert "pull_request_target" not in triggers
    concurrency = workflow["concurrency"]
    assert concurrency["cancel-in-progress"] == "${{ github.event_name == 'pull_request' }}"
    assert "github.event.pull_request.number" in concurrency["group"]
    assert "github.run_id" in concurrency["group"]


def test_workflow_routes_jobs_through_changes_and_gate(workflow):
    jobs = workflow["jobs"]
    assert list(jobs) == ["changes", "docs", "test", "integration", "gate"]
    assert jobs["changes"]["outputs"] == {"mode": "${{ steps.scope.outputs.mode }}"}
    assert jobs["changes"]["steps"][0]["with"] == {"fetch-depth": 0}
    assert jobs["changes"]["steps"][-1] == {"id": "scope", "run": "python scripts/ci_scope.py classify"}
    assert jobs["docs"]["needs"] == "changes"
    assert jobs["docs"]["if"] == "needs.changes.outputs.mode == 'docs'"
    assert jobs["docs"]["steps"][-1] == {"run": "python scripts/ci_scope.py docs-check"}
    for job in ("test", "integration"):
        assert jobs[job]["needs"] == "changes"
        assert jobs[job]["if"] == "needs.changes.outputs.mode == 'full'"
    gate = jobs["gate"]
    assert gate["name"] == "CI gate" and gate["if"] == "always()"
    assert gate["needs"] == ["changes", "docs", "test", "integration"]
    assert gate["steps"][-1] == {"run": "python scripts/ci_scope.py gate",
                                 "env": {"CI_NEEDS": "${{ toJSON(needs) }}"}}
    for job in jobs.values():
        assert not any(step.get("continue-on-error") for step in job["steps"])
        assert not job.get("continue-on-error")


def test_workflow_preserves_full_matrix_and_commands(workflow):
    test = workflow["jobs"]["test"]
    assert test["strategy"] == {"fail-fast": False, "matrix": {
        "os": ["ubuntu-latest", "windows-latest"], "python": ["3.12", "3.14"]}}
    assert test["runs-on"] == "${{ matrix.os }}"
    assert test["steps"][0]["with"] == {"fetch-depth": 0}
    assert [step["run"] for step in test["steps"] if "run" in step] == [
        "python -m pip install uv==0.12.2", "uv sync --frozen", "uv run ruff check .",
        "uv run pytest -q", "uv build", "uv run harness-supervisor --help", "uv run zeus --version",
        "uv run python -m zeus ticket --help", "uv run zeus-monitor --help"]
    integration = workflow["jobs"]["integration"]
    assert integration["runs-on"] == "ubuntu-latest"
    assert [step["run"] for step in integration["steps"] if "run" in step] == [
        "python -m pip install uv==0.12.2", "uv sync --frozen", "uv run harness setup",
        "docker compose version", "docker compose -p harness-ci up -d --wait postgres redis",
        "uv run python scripts/check.py --integration",
        "uv run pytest -q tests/test_verification.py tests/test_host_interruption.py",
        "docker compose -p harness-ci down --volumes"]
    assert integration["steps"][-2]["env"] == {"ZEUS_TEST_DOCKER": "1"}
    assert integration["steps"][-1]["if"] == "always()"
