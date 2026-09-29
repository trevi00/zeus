"""Scenario body `containers.staging` (REBUILD-DESIGN-v2 §5.3 S3: staging and the immutable evidence hand-off;
I1 (f)3 hand-off, (f)5 partial output never promoted; RESEARCH-S3 D5/D6).

Layer: harness (never shipped); standard library only. A fixture Git repository is built here with host
git (never a provider); the implementation reads it with its own git calls. Results carry names, modes,
digests, counts and refusal codes; host paths are symbolic.

`api` provides: `check_relative_path(name)`, `check_bounds(entries)`, `list_revision(repo, rev)`,
`stage_source(repo, rev, destination, on_progress)`, `init_standalone_git(staging)`, `scan_tree(root,
skip_top_git)`, `plan_import(manifest, staging)`, `apply_import(plan, staging, candidate)`,
`retain_evidence_handoff(artifacts, evidence_dir, run_id)`, `handoff_refs(root, texts)`,
`materialize_handoff(handoff, destination)`, `Artifacts(root)` (a file artifact store with `put(text,
source) -> {"ref"}`), `MAX_FILES`, `MAX_FILE_BYTES`, `IsolationError`, `ContractError`.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path

from s1_common import outcome, relative

ENV = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "GIT_CONFIG_NOSYSTEM": "1",
       "GIT_AUTHOR_DATE": "2026-01-01T00:00:00Z", "GIT_COMMITTER_DATE": "2026-01-01T00:00:00Z"}


class LeaseEnded(Exception):
    """The caller's own heartbeat refusal (an ended, superseded or cancelled execution)."""


def _git(repo: Path, *args) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True,
                          env={**ENV, "HOME": str(repo)}).stdout.strip()


def _repo(root: Path, name: str, files: dict, extra=None) -> tuple:
    repo = root / name
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "fixture@example.invalid")
    _git(repo, "config", "user.name", "fixture")
    for path, data in files.items():
        target = repo.joinpath(*path.split("/"))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        if path.endswith(".sh"):
            target.chmod(0o755)
    if extra is not None:
        extra(repo)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "fixture")
    return repo, _git(repo, "rev-parse", "HEAD")


def _files(root: Path) -> dict:
    out = {}
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        if rel == ".git" or rel.startswith(".git/"):
            continue
        if path.is_file():
            out[rel] = {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "mode": oct(path.stat().st_mode & 0o777)}
    return out


def run(api) -> dict:
    base = Path(tempfile.mkdtemp(prefix="zeus-s3-staging-")).resolve()
    roots = {"BASE": str(base)}
    out: dict = {}
    names = ["a.py", "pkg/b.py", "", "/abs", "a\\b", "a/../b", "./a", "a//b", "a/.git/x", ".GIT", "con.txt",
             "LPT1", "aux.tar.gz", "nul", "a:b", "trailing.", "trailing ", "tab\tname", "ok.name.txt", "COM10",
             "é/ü.py", "a\x00b", 7]
    out["check_relative_path"] = {repr(name): outcome(lambda name=name: list(api.check_relative_path(name)))
                                  for name in names}
    bounds = {
        "ok": [("a.py", 1), ("pkg/b.py", 2)],
        "case_collision": [("A.py", 1), ("a.py", 1)],
        "file_vs_dir": [("pkg", 1), ("pkg/b.py", 1)],
        "dir_spelling": [("Pkg/a.py", 1), ("pkg/b.py", 1)],
        "file_too_large": [("big.bin", api.MAX_FILE_BYTES + 1)],
        "too_many": [(f"f{i}.txt", 0) for i in range(api.MAX_FILES + 1)],
        "unsafe": [("../x", 1)],
    }
    out["check_bounds"] = {name: outcome(lambda entries=entries: api.check_bounds(entries))
                           for name, entries in bounds.items()}
    files = {"README.md": b"fixture\n", "pkg/module.py": b"VALUE = 1\n", "bin/run.sh": b"#!/bin/sh\necho hi\n",
             "data/blob.bin": bytes(range(256)), "deep/a/b/c.txt": b"c\n", "empty.txt": b""}
    repo, revision = _repo(base, "repo", files)
    out["list_revision"] = outcome(lambda: sorted([mode, size, name] for mode, _, size, name in
                                                  api.list_revision(repo, revision)))
    out["list_revision_unknown"] = outcome(lambda: api.list_revision(repo, "0" * 40))
    ticks = []
    staged = base / "staged"
    result = outcome(lambda: api.stage_source(repo, revision, staged, on_progress=lambda: ticks.append(1)))
    if "ok" in result:
        result["ok"] = {**{k: v for k, v in result["ok"].items() if k != "revision"},
                        "revision_matches": result["ok"]["revision"] == revision}
    out["stage_source"] = result
    out["stage_ticks_at_least_two"] = len(ticks) >= 2
    out["staged_files"] = _files(staged)
    out["stage_existing_destination"] = outcome(lambda: api.stage_source(repo, revision, staged))

    def cancelled():
        raise LeaseEnded("lease ended")

    cancel_dest = base / "cancelled"
    out["stage_cancelled_before_files"] = outcome(lambda: api.stage_source(repo, revision, cancel_dest,
                                                                           on_progress=cancelled))
    out["stage_cancelled_left_destination"] = cancel_dest.exists()
    link_repo, link_rev = _repo(base, "linkrepo", {"a.txt": b"a"}, lambda r: os.symlink("a.txt", r / "link"))
    out["stage_symlink_refused"] = outcome(lambda: api.stage_source(link_repo, link_rev, base / "link-staged"))
    out["stage_symlink_left_destination"] = (base / "link-staged").exists()
    case_repo, case_rev = _repo(base, "caserepo", {"A.txt": b"1", "sub/x.txt": b"2", "Sub/y.txt": b"3"})
    out["stage_case_collision"] = outcome(lambda: api.stage_source(case_repo, case_rev, base / "case-staged"))
    git_report = outcome(lambda: api.init_standalone_git(staged))
    out["init_standalone_git"] = git_report
    out["staged_git"] = {"remotes": _git(staged, "remote"), "log": _git(staged, "log", "--format=%s"),
                         "hooks_path": subprocess.run(["git", "-C", str(staged), "config", "--get", "core.hooksPath"],
                                                      capture_output=True, text=True, env={**ENV, "HOME": str(base)}).stdout}
    manifest = out["stage_source"]["ok"]["manifest"] if "ok" in out["stage_source"] else {}
    # -- the worker's output: validation before import, then import ---------------------------------
    (staged / "pkg" / "module.py").write_bytes(b"VALUE = 2\n")
    (staged / "new.txt").write_bytes(b"new\n")
    (staged / "empty.txt").unlink()
    (staged / "__pycache__").mkdir()
    (staged / "__pycache__" / "x.pyc").write_bytes(b"x")
    (staged / "pkg" / "c.pyc").write_bytes(b"x")
    out["scan_tree"] = outcome(lambda: api.scan_tree(staged))
    plan = outcome(lambda: api.plan_import(manifest, staged))
    out["plan_import"] = plan
    candidate = base / "candidate"
    candidate.mkdir()
    for name, data in files.items():
        target = candidate.joinpath(*name.split("/"))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    if "ok" in plan:
        out["apply_import"] = outcome(lambda: api.apply_import(plan["ok"], staged, candidate))
        out["candidate_after"] = _files(candidate)
        (staged / "new.txt").write_bytes(b"changed after validation\n")
        out["apply_changed_after_validation"] = outcome(lambda: api.apply_import(plan["ok"], staged, candidate))
    refusals = {}
    for name, build in {
        "symlink": lambda d: os.symlink("README.md", d / "l"),
        "nested_git_file": lambda d: (d / "sub").mkdir() or (d / "sub" / ".git").write_bytes(b"gitdir: x"),
        "hardlink": lambda d: os.link(d / "README.md", d / "twin.md"),
        "fifo": lambda d: os.mkfifo(d / "pipe"),
        "unsafe_name": lambda d: (d / "con.txt").write_bytes(b"x"),
        "case_collision": lambda d: (d / "readme.MD").write_bytes(b"x"),
    }.items():
        tree = base / ("scan-" + name)
        tree.mkdir()
        (tree / "README.md").write_bytes(b"r")
        build(tree)
        refusals[name] = outcome(lambda tree=tree: api.scan_tree(tree))
    out["scan_refusals"] = refusals
    # -- the evidence hand-off (D4) ------------------------------------------------------------------
    store = base / "artifacts"
    store.mkdir()
    artifacts = api.Artifacts(store)
    evidence = base / "run" / "evidence"
    (evidence / "logs").mkdir(parents=True)
    (evidence / "receipt.json").write_text(json.dumps({"ok": True}), encoding="utf-8")
    (evidence / "logs" / "bin.dat").write_bytes(b"\xff\x00\xfe")
    (base / "run" / "inner_result.json").write_text('{"inner": 1}', encoding="utf-8")
    retained = api.retain_evidence_handoff(artifacts, evidence, "r" * 32)
    out["retain"] = relative(retained, roots)
    manifest_ref = retained.get("manifest")
    link_ev = base / "run2" / "evidence"
    link_ev.mkdir(parents=True)
    os.symlink("/etc/hostname", link_ev / "escape")
    out["retain_link_refused"] = api.retain_evidence_handoff(artifacts, link_ev, "s" * 32)
    receipt = artifacts.put(json.dumps({"isolation": {"evidence_handoff": {"manifest": manifest_ref}}}), "receipt")
    other = artifacts.put("unrelated", "other")
    texts = [f"see {receipt['ref']} and {store}/{other['ref'][7:]}.txt and sha256:{'9' * 64}"]
    refs = api.handoff_refs(store, texts)
    out["handoff_refs"] = refs
    materialized = outcome(lambda: api.materialize_handoff({"root": str(store), "refs": refs}, base / "m1"))
    out["materialize"] = relative(materialized, roots)
    out["materialized_modes"] = sorted({oct(p.stat().st_mode & 0o777) for p in (base / "m1").iterdir()}) \
        if (base / "m1").is_dir() else None
    out["materialize_none"] = [api.materialize_handoff(None, base / "m0"), api.materialize_handoff({"refs": []}, base / "m0")]
    bad = store / (hashlib.sha256(b"x").hexdigest() + ".txt")
    bad.write_bytes(b"not x")
    out["materialize_integrity"] = outcome(lambda: api.materialize_handoff(
        {"root": str(store), "refs": ["sha256:" + hashlib.sha256(b"x").hexdigest()]}, base / "m2"))
    out["materialize_bad_ref"] = outcome(lambda: api.materialize_handoff({"root": str(store), "refs": ["x"]}, base / "m3"))
    out["materialize_relative_root"] = outcome(lambda: api.materialize_handoff({"root": "rel", "refs": [refs[0]]},
                                                                               base / "m4"))
    out["materialize_too_many"] = outcome(lambda: api.materialize_handoff(
        {"root": str(store), "refs": [refs[0]] * 513}, base / "m5"))
    for path in (base / "m1", base / "m2"):
        if path.is_dir():
            path.chmod(0o755)
    return out
