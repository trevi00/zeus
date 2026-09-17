"""Operation path grammar (INV-OPERATION-001): ordinary dot-prefixed project paths are accepted by the
one shared helper and every caller; Git metadata aliases, traversal, roots, ADS and wrong types stay
refused. The temporary Git repositories here are fixtures under tmp_path, never the real checkout;
no executor, provider or model is started."""
import shutil
import subprocess

import pytest
from test_autonomous import manifest as autonomous_manifest
from test_dge import packet
from test_operation import manifest as operation_manifest

from codex_harness.adapters import isolated_worker as iw
from codex_harness.adapters.providers import packaged_policy
from codex_harness.domain.autonomous import AutonomousManifestError, validate_autonomous_manifest
from codex_harness.domain.dge import PacketError, validate_packet
from codex_harness.domain.operation import (
    ManifestError,
    safe_relative_path,
    validate_manifest,
    validate_plan,
)

CANARY = "CANARY-must-never-be-emitted"
NORMAL_HIDDEN = [".github/workflows/ci.yml", ".gitignore", ".config/settings.json", "docs/.github/GOAL.md",
                 ".gitattributes", ".gitmodules", ".git-blame-ignore-revs", "a/.b/c/.d.e", ".x", "src/.hidden_dir/mod.py"]
ORDINARY_PRIOR = ["docs/GOAL.md", "src/codex_harness/domain/operation.py", "a", "a/b/c", "x.y-z_1", "trailing.",
                  "a..b", "1/2/3", "README", "docs/zeus/operations/operation-entrypoint-001/RUNBOOK.md"]
METADATA_ALIASES = [".git", ".GIT", ".Git", ".gIt", ".git/config", "a/.git/b", "docs/.GIT/x.md", ".git.", ".GIT..",
                    ".git./config", "a/.Git./b", ".github.", ".x."]
TRAVERSAL_AND_ROOTS = ["..", ".", "../x", "a/../b", "a/./b", "..x", "...x", "a/..x", "/abs", "/", "C:/x", "C:\\x",
                       "\\\\server\\share", "a\\b", "//host/x"]
UNSAFE_CHARACTERS = ["a b", " a", "a ", "a:b", "file.txt:stream", "a\x00b", "a\nb", "a\tb", "a/b\x1f", "é", "a*b",
                     "a?b", "a<b", "a|b", "a\"b"]
STRUCTURE = ["", "a/", "a//b", "/a", "a/.", "a/..", "-a", "_a", "a/-b", ".-a", "._a"]
WRONG_TYPES = [None, 1, 1.0, True, b".github", [".github"], {"path": ".github"}, (".github",)]


# ----- direct helper -------------------------------------------------------------------------
@pytest.mark.parametrize("path", NORMAL_HIDDEN)
def test_ordinary_and_nested_dot_paths_are_accepted(path):
    assert safe_relative_path(path) is True


@pytest.mark.parametrize("path", ORDINARY_PRIOR)
def test_previously_accepted_ordinary_grammar_is_unchanged(path):
    assert safe_relative_path(path) is True


@pytest.mark.parametrize("path", METADATA_ALIASES)
def test_git_metadata_and_its_aliases_are_refused_at_any_depth(path):
    assert safe_relative_path(path) is False


@pytest.mark.parametrize("path", TRAVERSAL_AND_ROOTS + UNSAFE_CHARACTERS + STRUCTURE)
def test_traversal_roots_drives_unc_ads_whitespace_and_control_characters_are_refused(path):
    assert safe_relative_path(path) is False


@pytest.mark.parametrize("value", WRONG_TYPES)
def test_non_string_values_are_refused(value):
    assert safe_relative_path(value) is False


def test_segment_budget_is_255_including_the_optional_dot():
    assert safe_relative_path("a" * 255) and not safe_relative_path("a" * 256)
    assert safe_relative_path("." + "a" * 254) and not safe_relative_path("." + "a" * 255)
    assert safe_relative_path("docs/" + "." + "a" * 254 + "/x") and not safe_relative_path("docs/" + "." + "a" * 255 + "/x")


def test_whole_path_cap_is_1024_unchanged_for_hidden_and_plain_segments():
    plain = "/".join(["a" * 255, "b" * 255, "c" * 255, "d" * 254, "e"])  # 3*255 + 254 + 1 + 4 slashes = 1024
    assert len(plain) == 1024 and safe_relative_path(plain) and not safe_relative_path(plain + "e")
    hidden = ".github/" + "/".join(["a" * 200] * 5) + "/" + "c" * 11
    assert len(hidden) == 1024 and safe_relative_path(hidden) and not safe_relative_path(hidden + "c")


# ----- validate_manifest goal and allowed_paths -----------------------------------------------
def test_manifest_accepts_hidden_goal_and_allowed_paths_and_keeps_them_verbatim():
    document = operation_manifest(**{"goal.path": "docs/.github/GOAL.md",
                                     "plan.allowed_paths": [".github/workflows/ci.yml", ".gitignore", ".config/settings.json"]})
    canonical = validate_manifest(document, packaged_policy())
    assert canonical["goal"]["path"] == "docs/.github/GOAL.md"
    assert canonical["plan"]["allowed_paths"] == [".github/workflows/ci.yml", ".gitignore", ".config/settings.json"]
    assert canonical == validate_manifest(document, packaged_policy())  # deterministic, no alias normalization


@pytest.mark.parametrize("field, value", [
    ("goal.path", ".git/GOAL.md"), ("goal.path", ".GIT/GOAL.md"), ("goal.path", "docs/.Git/GOAL.md"),
    ("goal.path", ".git./GOAL.md"), ("goal.path", "..hidden/GOAL.md"), ("goal.path", "/.github/GOAL.md"),
    ("goal.path", ".github/GOAL.md:stream.md"), ("goal.path", ".github\\GOAL.md"), ("goal.path", ".github/../GOAL.md"),
    ("plan.allowed_paths", [".git"]), ("plan.allowed_paths", [".GIT..", "docs/x.md"]), ("plan.allowed_paths", ["a/.git/b"]),
    ("plan.allowed_paths", [".github/workflows/ci.yml", ".github/workflows/ci.yml"]),
    ("plan.allowed_paths", [".github/workflows/ci.yml", 1]), ("plan.allowed_paths", ["..github"]),
    ("plan.allowed_paths", ["C:\\.github"]), ("plan.allowed_paths", [".git hooks"])])
def test_manifest_refuses_metadata_aliases_traversal_roots_ads_and_wrong_types(field, value):
    with pytest.raises(ManifestError) as info:
        validate_manifest(operation_manifest(**{field: value}), packaged_policy())
    assert CANARY not in str(info.value) and ".git" not in str(info.value)


def test_manifest_goal_path_still_requires_markdown_after_a_hidden_directory():
    with pytest.raises(ManifestError, match="Markdown"):
        validate_manifest(operation_manifest(**{"goal.path": ".github/GOAL.yml"}), packaged_policy())


# ----- validate_plan: the shared contract ------------------------------------------------------
def test_validate_plan_accepts_hidden_allowed_paths_and_refuses_metadata_with_the_callers_error():
    plan = {"objective": "o", "acceptance_criteria": ["a"], "allowed_paths": [".github/workflows/ci.yml", ".gitignore"]}
    assert validate_plan(plan)["allowed_paths"] == [".github/workflows/ci.yml", ".gitignore"]
    with pytest.raises(PacketError, match="allowed_paths"):
        validate_plan({**plan, "allowed_paths": [".gitignore", ".GIT/config"]}, PacketError)
    with pytest.raises(ManifestError, match="allowed_paths"):
        validate_plan({**plan, "allowed_paths": [".git."]})


# ----- DGE and autonomous consumer seams ------------------------------------------------------
def test_research_packet_sources_and_plan_share_the_grammar():
    source = {"id": "s1", "path": ".github/workflows/ci.yml", "sha256": "b" * 64, "locator": "l", "revision": "r", "read_scope": "s"}
    accepted = validate_packet(packet(sources=[source], **{"plan.allowed_paths": [".gitignore", "docs/.github/GOAL.md"]}))
    assert accepted["sources"][0]["path"] == ".github/workflows/ci.yml"
    assert accepted["plan"]["allowed_paths"] == [".gitignore", "docs/.github/GOAL.md"]
    for bad in (".GIT/config", ".git.", "../.github", ".github:ads", "..github"):
        with pytest.raises(PacketError, match="source paths"):
            validate_packet(packet(sources=[{**source, "path": bad}]))
        with pytest.raises(PacketError, match="allowed_paths"):
            validate_packet(packet(**{"plan.allowed_paths": [bad]}))


def test_autonomous_manifest_scope_and_plan_share_the_grammar():
    research = {"topic": "hidden files", "questions": ["which workflow?"], "search_scope": [".github", "docs/.github"]}
    plan = {"objective": "o", "acceptance_criteria": ["a"], "allowed_paths": [".github/workflows/ci.yml", ".gitignore"]}
    accepted = validate_autonomous_manifest(autonomous_manifest(research=research, plan=plan), packaged_policy())
    assert accepted["research"]["search_scope"] == [".github", "docs/.github"]
    assert accepted["plan"]["allowed_paths"] == [".github/workflows/ci.yml", ".gitignore"]
    for bad in (".GIT", ".git.", "a/.git", "/.github", ".github\\x"):
        with pytest.raises(AutonomousManifestError, match="search_scope"):
            validate_autonomous_manifest(autonomous_manifest(research={**research, "search_scope": [bad]}), packaged_policy())
        with pytest.raises(AutonomousManifestError, match="allowed_paths"):
            validate_autonomous_manifest(autonomous_manifest(plan={**plan, "allowed_paths": [bad]}), packaged_policy())


# ----- the isolated staging seam: real temporary Git, no model, no real .git --------------------
def git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), "-c", "user.name=t", "-c", "user.email=t@localhost", *args],
                          capture_output=True, text=True, check=True).stdout.strip()


HIDDEN_FILES = {".github/workflows/ci.yml": b"on: push\n", ".gitignore": b"*.pyc\n", "docs/.github/GOAL.md": b"# goal\n",
                "kept.txt": b"original\n"}


def test_hidden_files_pass_the_manifest_grammar_and_the_isolated_staging_import_unchanged(tmp_path):
    if shutil.which("git") is None:
        pytest.skip("git is not on PATH for the temporary fixture repository")
    candidate = tmp_path / "candidate"  # fixture repository under tmp_path, never the real checkout
    candidate.mkdir()
    git(candidate, "init", "-q")
    for name, body in HIDDEN_FILES.items():
        (candidate / name).parent.mkdir(parents=True, exist_ok=True)
        (candidate / name).write_bytes(body)
    git(candidate, "add", "-A")
    git(candidate, "commit", "-q", "-m", "base")
    stage = tmp_path / "stage"
    source = iw.stage_source(candidate, git(candidate, "rev-parse", "HEAD"), stage)
    assert set(source["manifest"]) == set(HIDDEN_FILES) and source["files"] == 4
    # Both grammars agree on every staged name: the manifest helper and the adapter's own check.
    assert all(safe_relative_path(name) for name in source["manifest"])
    assert all(iw.check_relative_path(name) == tuple(name.split("/")) for name in source["manifest"])
    for alias in (".git", "a/.GIT/b", ".git."):
        assert not safe_relative_path(alias)
        with pytest.raises(iw.IsolationError):
            iw.check_relative_path(alias)
    # Observed, not changed here: the adapter accepts a repeated leading dot (`..x`) that the manifest
    # grammar refuses; the manifest refusal comes first, so the stricter rule is the operative one.
    assert not safe_relative_path("..x") and iw.check_relative_path("..x") == ("..x",)
    iw.init_standalone_git(stage)
    (stage / ".github" / "workflows" / "ci.yml").write_bytes(b"on: [push, pull_request]\n")  # a benign worker edit
    (stage / ".gitignore").write_bytes(b"*.pyc\n*.log\n")
    plan = iw.plan_import(source["manifest"], stage)
    assert plan["added"] == [] and plan["modified"] == [".github/workflows/ci.yml", ".gitignore"] and plan["deleted"] == []
    imported = iw.apply_import(plan, stage, candidate)
    assert imported["modified"] == [".github/workflows/ci.yml", ".gitignore"]
    assert (candidate / ".github" / "workflows" / "ci.yml").read_bytes() == b"on: [push, pull_request]\n"
    assert (candidate / ".gitignore").read_bytes() == b"*.pyc\n*.log\n"
    assert (candidate / "docs" / ".github" / "GOAL.md").read_bytes() == b"# goal\n"
    # `git` strips the whole output, so the first line loses its leading status space: compare stripped lines.
    status = sorted(line.strip() for line in git(candidate, "status", "--porcelain").splitlines())
    assert status == ["M .github/workflows/ci.yml", "M .gitignore"]  # worktree-modified only, nothing staged or untracked
