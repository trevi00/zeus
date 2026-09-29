"""Fixture project for the S2 context scenarios (REBUILD-DESIGN-v2 §5.2 R-D, §5.3 S2).

Layer: harness (never shipped); standard library only.

A labelled, disposable Git repository at a FIXED absolute path, so paths embedded in delivered
context and in retained packet artifacts are equal on both sides by injection, not by a mask
(each side runs in its own process; under bwrap /tmp is private to it). Author/committer identity
and dates are fixed, so the commit ids are equal. The repository holds a project profile with a
Git-owned UUID, matcher-bearing and legacy project skills, a packaged-skill directory and source
files that the skill matcher can cite. A fixed placeholder interpreter file is created and never run.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path("/tmp/zeus-rebuild-s2-context")
MARKER = ".zeus-rebuild-s2-disposable"
FIXED = {"GIT_AUTHOR_NAME": "Fixture", "GIT_AUTHOR_EMAIL": "fixture@localhost",
         "GIT_COMMITTER_NAME": "Fixture", "GIT_COMMITTER_EMAIL": "fixture@localhost",
         "GIT_AUTHOR_DATE": "2026-01-01T00:00:00+00:00", "GIT_COMMITTER_DATE": "2026-01-01T00:00:00+00:00",
         "GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0"}
PROJECT_ID = "3f1c2b7a-8d4e-4c1b-9a2f-6e5d4c3b2a19"

FILES = {
    ".harness/tech-stack.yaml": (
        "schema_version: '1'\n"
        f"project_id: {PROJECT_ID}\n"
        "stacks:\n"
        "  - language: python\n"
        "    framework: pytest\n"
        "    version: '3.12'\n"
        "extensions:\n"
        "  - shared\n"),
    ".harness/skills/_common/review-checklist.md": (
        "# Review checklist\n\nRead the diff first. Name every unverified claim.\n"),
    ".harness/skills/_common/testing/SKILL.md": (
        "---\n"
        "name: testing\n"
        "description: Write focused pytest tests   # inline comment is dropped\n"
        "keywords: [pytest, tests]\n"
        "intent: [test]\n"
        "requires: [retry-patterns, missing-skill]\n"
        "---\n"
        "# Testing\n\nWrite one failing test first, then the smallest change.\n"),
    ".harness/skills/python/retry-patterns.md": (
        "---\n"
        "description: Bounded retry with backoff\n"
        "keywords: [retry, backoff]\n"
        "paths: [src/app]\n"
        "patterns: [def retry]\n"
        "---\n"
        "# Retry patterns\n\nRetry only idempotent operations; cap attempts; add jitter.\n"),
    ".harness/skills/python/logging.md": (
        "---\n"
        "description: Structured logging\n"
        "keywords: [logging]\n"
        "min_score: 2\n"
        "---\n"
        "# Logging\n\nLog events, not prose.\n"),
    ".harness/skills/python/huge-retry.md": (
        "---\n"
        "description: Exhaustive retry catalogue\n"
        "keywords: [retry]\n"
        "---\n"
        "# Exhaustive retry catalogue\n\n" + ("Retry note line with guidance. " * 180) + "\n"),
    ".harness/skills/python/pytest/fixtures.md": (
        "---\n"
        "description: Pytest fixtures\n"
        "keywords: [fixtures]\n"
        "---\n"
        "# Fixtures\n\nPrefer tmp_path.\n"),
    ".harness/skills/shared/_private/hidden/SKILL.md": "# hidden\n",
    ".harness/skills/shared/tools/SKILL.md": (
        "---\n"
        "description: Shared tool guidance\n"
        "keywords: [tools]\n"
        "---\n"
        "# Tools\n\nUse the project tools.\n"),
    "src/app/__init__.py": "",
    "src/app/retry.py": "def retry(operation, attempts=3):\n    return operation()\n",
    "README.md": "# Fixture project\n",
}


def git(cwd: Path, *args: str) -> str:
    done = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, check=True)
    return done.stdout.strip()


def fresh_root() -> Path:
    if ROOT.exists():
        if not (ROOT / MARKER).exists():
            raise SystemExit(f"{ROOT} exists and is not a labelled disposable S2 root")
        shutil.rmtree(ROOT)
    ROOT.mkdir(parents=True)
    (ROOT / MARKER).write_text("disposable S2 context workspace\n", encoding="utf-8")
    return ROOT


def build() -> dict:
    """Create the fixture world; returns its fixed paths."""
    os.environ.update(FIXED)
    root = fresh_root()
    repo = root / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    for relative, body in FILES.items():
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "fixture project")
    interpreter = root / "bin" / "python"
    interpreter.parent.mkdir()
    interpreter.write_text("#!/bin/sh\nexit 97\n", encoding="utf-8")
    interpreter.chmod(0o755)
    return {"root": root, "repo": repo, "artifacts": root / "runtime" / "artifacts",
            "workspaces": root / "workspaces", "interpreter": interpreter,
            "revision": git(repo, "rev-parse", "HEAD")}


def cleanup() -> None:
    if ROOT.exists() and (ROOT / MARKER).exists():
        shutil.rmtree(ROOT)
