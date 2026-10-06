"""Independent reference/target comparison runner (REBUILD-DESIGN-v2 §5.1, §5.2, §5.3 S0).

Layer: harness (never shipped); standard library only. Usage from the worktree root:

    python compare/run.py check-tree          # S0 check 1: reference bytes, allowed paths, no secrets
    python compare/run.py prepare             # build the reference wheel from `git archive SOURCE`
    python compare/run.py prepare --rebaseline ID   # the approved rebaseline's wheel (SOURCE + delta archive)
    python compare/run.py run                 # run every scenario; compare with committed goldens
    python compare/run.py run --record        # reference-only: (re)write reference goldens
    python compare/run.py run --reference rebaseline:ID [--target-vs-reference]   # G1-13c: S2R rebaseline reference
    python compare/run.py run --pg            # also the scenarios that need a disposable PostgreSQL
    python compare/run.py run --redis         # also the scenarios that need a disposable Redis
    python compare/run.py target-integration  # target suite with its integration tests on fixtures
    python compare/run.py docker-fixture      # S3 labelled, network-less Docker fixture suite (target)

The reference environment is built from the SOURCE archive wheel, never from the working tree;
its package-file digest must equal `compare/baseline.json`. Each driver runs as a separate process
of its own environment with the R-P child environment and, where bwrap is available, without
network and with tmpfs over credential directories. The target side of every scenario stays
`pending` until a target driver exists: nothing is reported green without a target run. A present
target driver runs in the target venv (`target/.venv`, built from `target/uv.lock`) with the same
inputs and the same disposable fixture server, and its result must equal the committed reference
golden exactly (S1 onwards).
Exit: 0 all reference results equal their goldens (and every present target equal too), 1 a
difference or failure, 2 usage.
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

COMPARE = Path(__file__).resolve().parent
ROOT = COMPARE.parent
sys.path.insert(0, str(COMPARE / "guard"))
import provider_guard  # noqa: E402

sys.path.insert(0, str(COMPARE / "harness"))
import block_exercise  # noqa: E402

sys.path.remove(str(COMPARE / "harness"))

# Every docker call of this runner passes the same default-deny guard as the tests (R-P, S0 F1).
provider_guard.install()
# The disposable fixture images are pinned by DIGEST, not by moving tag: the recorded goldens capture the image's
# own facts (delivery.restore.pg pins the pgvector extension version 0.8.6), and on 2026-10-01 the upstream
# `pg17` tag moved to a newer pgvector, which failed exact-head CI on both sides. These are the digests the
# goldens were recorded with (the pg17 index of 2026-08-13; redis 7.4-alpine).
PG_IMAGE = "pgvector/pgvector@sha256:cf134a767f474095eeba57e0117be8e568e011a63f33fbf252f14c9b760f8e6f"
REDIS_IMAGE = "redis@sha256:858f009f9709ce576febc734aa78b8f6d624b82571f9ddb6bda4377c833b3499"
# The one layout constant of this tool: the promotion sets ROOT; DESIGN-s11 §20.5.
TARGET_DIR = ROOT  # promoted (S11 unit P)
TARGET_PREFIX = ""  # the repo-relative git prefix of TARGET_DIR (promoted: the root)
TARGET_PYTHON = TARGET_DIR / ".venv" / "bin" / "python"
TARGET_SRC = TARGET_DIR / "src"
TARGET_VENV_MISSING = "target venv missing: run `uv sync --frozen` at the repository root"

BASELINE = json.loads((COMPARE / "baseline.json").read_text(encoding="utf-8"))
SOURCE_COMMIT = BASELINE["source"]["commit"]
SCRATCH = Path(os.environ.get("ZEUS_REBUILD_SCRATCH")
               or Path(tempfile.gettempdir()) / "zeus-rebuild-001").resolve()
SECRET_SHAPES = [re.compile(p) for p in (
    r"[a-z]+://[^\s/@:\"']+:[^\s/@\"']+@",           # URL with a password in its userinfo
    r"sk-ant-[A-Za-z0-9_-]{8,}", r"sk-[A-Za-z0-9]{32,}", r"gh[pousr]_[A-Za-z0-9]{20,}",
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----")]


def git(*args: str, cwd: Path = ROOT, text: bool = True):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=text).stdout


def check_tree(root: Path | None = None, source_commit: str | None = None, baseline: dict | None = None) -> dict:
    """The layout check, dispatched on `baseline["layout"]["mode"]` (absent = "two-tree"). The arguments default to the
    module globals; tests pass a fixture repository."""
    root = ROOT if root is None else root
    source_commit = SOURCE_COMMIT if source_commit is None else source_commit
    baseline = BASELINE if baseline is None else baseline
    mode = baseline["layout"].get("mode", "two-tree")
    if mode == "promoted":
        return _check_tree_promoted(root, source_commit, baseline)
    if mode != "two-tree":
        raise ValueError(f"unknown layout mode {mode!r}")
    return _check_tree_two_tree(root, source_commit, baseline)


def _check_tree_two_tree(root: Path, source_commit: str, baseline: dict) -> dict:
    """Reference bytes unchanged; only allowed paths changed; no credential-shaped strings added."""
    allowed = baseline["layout"]["allowed_changed_paths"]
    excludes = [f":(exclude){a.rstrip('/')}" for a in allowed]
    unchanged = subprocess.run(["git", "diff", "--quiet", source_commit, "--", ".", *excludes],
                               cwd=root).returncode == 0
    # The docs index and the design SSOT may only gain a link/pointer line (§3.1).
    additions_only = {}
    for path, limit in baseline["layout"]["additions_only"].items():
        numstat = git("diff", "--numstat", source_commit, "--", path, cwd=root).split()
        added, deleted = (int(numstat[0]), int(numstat[1])) if numstat else (0, 0)
        additions_only[path] = {"added": added, "deleted": deleted,
                                "ok": deleted == 0 and added <= limit}
    changed = [p for p in git("diff", "--name-only", source_commit, "--", cwd=root).splitlines() if p]
    changed += [p for p in git("ls-files", "--others", "--exclude-standard", cwd=root).splitlines() if p]
    outside = sorted(p for p in set(changed)
                     if not any(p == a or p.startswith(a.rstrip("/") + "/") for a in allowed))
    shaped = []
    for path in sorted(set(changed)):
        file = root / path
        if not file.is_file():
            continue
        text = file.read_text(encoding="utf-8", errors="replace")
        for pattern in SECRET_SHAPES:
            if pattern.search(text):
                shaped.append({"path": path, "pattern": pattern.pattern})
    head_tree = git("rev-parse", f"{source_commit}^{{tree}}", cwd=root).strip()
    return {"source_commit": source_commit, "source_tree": head_tree,
            "source_tree_matches_baseline": head_tree == baseline["source"]["tree"],
            "reference_paths_unchanged": unchanged, "changed_paths": len(set(changed)),
            "changed_outside_allowed": outside, "credential_shaped_strings": shaped,
            "additions_only": additions_only,
            "ok": unchanged and not outside and not shaped
            and all(v["ok"] for v in additions_only.values())
            and head_tree == baseline["source"]["tree"]}


LIST_BOUND = 50


def _hash_working_files(root: Path, paths: list[str]) -> dict[str, str]:
    """Blob ids of the working-tree files among `paths` (modified and untracked included)."""
    present = [p for p in paths if (root / p).is_file()]
    if not present:
        return {}
    done = subprocess.run(["git", "hash-object", "--stdin-paths"], cwd=root, check=True, capture_output=True,
                          text=True, input="\n".join(present) + "\n")
    return dict(zip(present, done.stdout.split()))


def _rebaseline_blobs(root: Path, entry: dict) -> dict[str, str]:
    """The entry commit's blob id for each of its delta paths (a path the commit does not hold is absent)."""
    listing = git("ls-tree", "-r", "-z", entry["commit"], "--", *entry["delta_paths"], cwd=root)
    blobs = {}
    for row in listing.split("\0"):
        if row:
            meta, path = row.split("\t", 1)
            blobs[path] = meta.split()[2]
    return blobs


def _check_rebaseline_entry(root: Path, entry: dict, blobs: dict[str, str]) -> dict:
    """G1-11: the entry's own identity facts (AMD-1 A): `commit^{tree}` equals `tree` and `delta_paths` equals
    `git diff --name-only parent_source commit`. The archive-file comparison itself is rule (b) above."""
    tree = git("rev-parse", f"{entry['commit']}^{{tree}}", cwd=root).strip()
    diff = sorted(p for p in git("diff", "--name-only", entry["parent_source"], entry["commit"], cwd=root).splitlines() if p)
    return {"id": entry["id"], "tree_matches": tree == entry["tree"],
            "delta_paths_match": diff == sorted(entry["delta_paths"]) == list(entry["delta_paths"]),
            "delta_paths_in_commit": sorted(blobs) == sorted(entry["delta_paths"]),
            "ok": tree == entry["tree"] and diff == sorted(entry["delta_paths"]) == list(entry["delta_paths"])
            and sorted(blobs) == sorted(entry["delta_paths"])}


def _check_tree_promoted(root: Path, source_commit: str, baseline: dict) -> dict:
    """DESIGN-s11 §20.5 archive rule (promoted layout): (a) every SOURCE path has its SOURCE blob at the root path or at
    `reference/m7/<path>` (or is an additions-only path); (b) everything under `reference/` is `reference/README.md` or
    a `reference/m7/<q>` equal to SOURCE's `<q>`; (c) no credential-shaped string in a path changed vs SOURCE; (d) the
    SOURCE tree id equals the baseline's. Dormant until the baseline's layout mode is "promoted"."""
    layout = baseline["layout"]
    archive = "reference/m7/"
    listing = git("ls-tree", "-r", "-z", source_commit, cwd=root)
    source = {}  # path -> blob id (gitlinks are not blobs)
    for entry in listing.split("\0"):
        if not entry:
            continue
        meta, path = entry.split("\t", 1)
        mode, kind, blob = meta.split()
        if kind == "blob":
            source[path] = blob
    additions_only = {}
    for path, limit in layout["additions_only"].items():
        numstat = git("diff", "--numstat", source_commit, "--", path, cwd=root).split()
        added, deleted = (int(numstat[0]), int(numstat[1])) if numstat else (0, 0)
        additions_only[path] = {"added": added, "deleted": deleted, "ok": deleted == 0 and added <= limit}
    tracked_reference = git("ls-files", "-z", "--", "reference", cwd=root).split("\0")
    untracked_reference = git("ls-files", "-z", "--others", "--exclude-standard", "--", "reference", cwd=root).split("\0")
    reference = sorted({p for p in tracked_reference + untracked_reference if p and (root / p).is_file()})
    rebaselines = baseline.get("approved_rebaselines", [])
    rebaseline_blobs = {entry["id"]: _rebaseline_blobs(root, entry) for entry in rebaselines}
    rebaseline_files = {f"{entry['archive_root'].rstrip('/')}/{q}": blob
                        for entry in rebaselines for q, blob in rebaseline_blobs[entry["id"]].items()}
    working = _hash_working_files(root, [*source, *(archive + p for p in source), *reference, *rebaseline_files])
    missing = sorted(p for p, blob in source.items() if p not in layout["additions_only"]
                     and working.get(p) != blob and working.get(archive + p) != blob)
    # G1-11: rule (b) also accepts `reference/<entry.id>/<q>` for a delta path q whose blob equals the entry commit's.
    foreign = [p for p in reference if p != "reference/README.md"
               and not (p.startswith(archive) and source.get(p[len(archive):]) == working.get(p))
               and not (p in rebaseline_files and rebaseline_files[p] == working.get(p))]
    foreign += sorted(p for p in rebaseline_files if p not in set(reference))  # a missing delta file
    foreign = sorted(set(foreign))
    changed = [p for p in git("diff", "--name-only", source_commit, "--", cwd=root).splitlines() if p]
    changed += [p for p in git("ls-files", "--others", "--exclude-standard", cwd=root).splitlines() if p]
    # S11 unit P (owner): an archive file equal to SOURCE's is SOURCE's own bytes (rule (b)), not new content; its
    # fixture DSNs and token-shaped test strings were never a candidate change, so (c) scans only new or changed bytes.
    archived_equal = {p for p in reference if p.startswith(archive) and source.get(p[len(archive):]) == working.get(p)}
    archived_equal |= {p for p in reference if p in rebaseline_files and rebaseline_files[p] == working.get(p)}
    shaped = []
    for path in sorted(set(changed) - archived_equal):
        file = root / path
        if not file.is_file():
            continue
        text = file.read_text(encoding="utf-8", errors="replace")
        for pattern in SECRET_SHAPES:
            if pattern.search(text):
                shaped.append({"path": path, "pattern": pattern.pattern})
    head_tree = git("rev-parse", f"{source_commit}^{{tree}}", cwd=root).strip()
    entries = [_check_rebaseline_entry(root, entry, rebaseline_blobs[entry["id"]]) for entry in rebaselines]
    extra = {"rebaselines": entries} if entries else {}
    return {"mode": "promoted", "source_commit": source_commit, "source_tree": head_tree, **extra,
            "source_tree_matches_baseline": head_tree == baseline["source"]["tree"],
            "missing_source_paths": missing[:LIST_BOUND], "missing_source_paths_count": len(missing),
            "foreign_reference_paths": foreign[:LIST_BOUND], "foreign_reference_paths_count": len(foreign),
            "changed_paths": len(set(changed)), "credential_shaped_strings": shaped,
            "additions_only": additions_only,
            "ok": not missing and not foreign and not shaped
            and all(v["ok"] for v in additions_only.values())
            and all(e["ok"] for e in entries)
            and head_tree == baseline["source"]["tree"]}


def prepare() -> dict:
    """Build the reference wheel from the SOURCE archive and install it into its own venv."""
    source, dist, venv = SCRATCH / "source", SCRATCH / "dist", SCRATCH / "venv-ref"
    for path in (source, dist):
        shutil.rmtree(path, ignore_errors=True)
        path.mkdir(parents=True)
    archive = subprocess.run(["git", "archive", SOURCE_COMMIT], cwd=ROOT, check=True,
                             capture_output=True).stdout
    subprocess.run(["tar", "-x", "-C", str(source)], input=archive, check=True)
    uv = shutil.which("uv") or sys.exit("uv is required to build the reference wheel")
    subprocess.run([uv, "build", "--wheel", "--out-dir", str(dist)], cwd=source, check=True,
                   capture_output=True)
    wheel = next(dist.glob("*.whl"))
    expected = BASELINE["source"]["reference_wheel"]
    facts = {"wheel": wheel.name, "wheel_sha256": hashlib.sha256(wheel.read_bytes()).hexdigest()}
    requirements = SCRATCH / "ref-requirements.txt"
    requirements.write_text(subprocess.run(
        [uv, "export", "--frozen", "--no-dev", "--no-emit-project", "--no-hashes", "--format",
         "requirements.txt", "-q"], cwd=source, check=True, capture_output=True, text=True).stdout)
    python = venv / "bin" / "python"
    if not python.exists():
        subprocess.run([uv, "venv", "-q", "--python", BASELINE["environments"]["python"], str(venv)],
                       check=True)
    subprocess.run([uv, "pip", "install", "-q", "--python", str(python), "-r", str(requirements)],
                   check=True)
    subprocess.run([uv, "pip", "install", "-q", "--python", str(python), "--no-deps", "--reinstall",
                    str(wheel)], check=True)
    with zipfile.ZipFile(wheel) as archive_file:
        record = next(n for n in archive_file.namelist() if n.endswith(".dist-info/RECORD"))
        facts["wheel_record_sha256"] = hashlib.sha256(archive_file.read(record)).hexdigest()
    facts["wheel_sha256_matches_baseline"] = facts["wheel_sha256"] == expected["sha256"]
    facts["wheel_record_matches_baseline"] = (facts["wheel_record_sha256"]
                                              == expected["wheel_record_sha256"])
    return facts


def _blob_ids(base: Path, paths: list[str], filters: bool = False) -> dict[str, str]:
    """Blob ids of the files under `base` (`git hash-object`, no object writes; a symlink hashes its link text).
    `filters=True` hashes through the tree's own `.gitattributes` clean filters."""
    flag = [] if filters else ["--no-filters"]
    files = [p for p in paths if not (base / p).is_symlink()]
    ids = dict(zip(files, subprocess.run(
        ["git", "hash-object", *flag, "--stdin-paths"], cwd=base, check=True, capture_output=True,
        text=True, input="".join(p + "\n" for p in files)).stdout.split())) if files else {}
    for p in paths:
        if (base / p).is_symlink():
            ids[p] = subprocess.run(["git", "hash-object", "--no-filters", "--stdin"], check=True, capture_output=True,
                                    text=True, input=os.readlink(base / p)).stdout.strip()
    return ids


def rebaseline_entry(entry_id: str, baseline: dict | None = None) -> dict:
    entries = (BASELINE if baseline is None else baseline).get("approved_rebaselines", [])
    found = [e for e in entries if e["id"] == entry_id]
    if not found:
        sys.exit(f"unknown rebaseline id {entry_id!r}; approved: {[e['id'] for e in entries]}")
    return found[0]


def prepare_rebaseline(entry_id: str, scratch: Path | None = None, archive_base: Path | None = None) -> dict:
    """G1-11 (AMD-1 A): SCRATCH/rebaseline-<id>/source = the SOURCE archive overlaid with the entry's delta archive,
    proven equal to the pinned commit's tree (path -> blob) BEFORE any build; then the same `uv build --wheel` and
    install as `prepare`, into `venv-rb-<id>`. Plain `prepare` is untouched."""
    entry = rebaseline_entry(entry_id)
    scratch = SCRATCH if scratch is None else scratch
    archive_dir = (ROOT if archive_base is None else archive_base) / entry["archive_root"]
    base = scratch / f"rebaseline-{entry['id']}"
    source, dist, venv = base / "source", base / "dist", scratch / f"venv-rb-{entry['id']}"
    for path in (source, dist):
        shutil.rmtree(path, ignore_errors=True)
        path.mkdir(parents=True)
    subprocess.run(["tar", "-x", "-C", str(source)], check=True,
                   input=subprocess.run(["git", "archive", SOURCE_COMMIT], cwd=ROOT, check=True,
                                        capture_output=True).stdout)
    for rel in entry["delta_paths"]:
        target = source / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.unlink(missing_ok=True)
        if (archive_dir / rel).is_file():  # a missing archive file stays absent: the proof below names it
            shutil.copyfile(archive_dir / rel, target)
    overlay_paths = sorted(str(p.relative_to(source)) for p in source.rglob("*") if p.is_file() or p.is_symlink())
    pinned = {}
    for row in git("ls-tree", "-r", "-z", entry["commit"]).split("\0"):
        if row:
            meta, path = row.split("\t", 1)
            if meta.split()[1] == "blob":
                pinned[path] = meta.split()[2]
    overlay = _blob_ids(source, overlay_paths)
    # `git archive` applies the SOURCE tree's own `.gitattributes` eol rules (`*.ps1` is CRLF in the extraction), so a
    # non-delta path may equal its pinned blob only through the clean filter; a delta path is the commit's bytes
    # copied verbatim and must equal its blob exactly (a CRLF-tampered delta file cannot pass through a filter).
    unmatched = [p for p in overlay_paths if p not in entry["delta_paths"] and overlay[p] != pinned.get(p)]
    overlay.update({p: b for p, b in _blob_ids(source, unmatched, filters=True).items() if b == pinned.get(p)})
    differing = sorted(p for p in overlay.keys() | pinned.keys() if overlay.get(p) != pinned.get(p))
    facts = {"rebaseline": entry["id"], "overlay_paths": len(overlay), "pinned_paths": len(pinned),
             "overlay_matches_tree": not differing, "differing_paths": differing[:LIST_BOUND],
             "differing_paths_count": len(differing)}
    if differing:
        facts["refused"] = f"the overlay does not reproduce tree {entry['tree']}; nothing was built"
        facts["wheel_record_matches_baseline"] = False
        return facts
    uv = shutil.which("uv") or sys.exit("uv is required to build the rebaseline wheel")
    subprocess.run([uv, "build", "--wheel", "--out-dir", str(dist)], cwd=source, check=True, capture_output=True)
    wheel = next(dist.glob("*.whl"))
    expected = entry["rebaseline_wheel"]
    facts.update(wheel=wheel.name, wheel_sha256=hashlib.sha256(wheel.read_bytes()).hexdigest())
    requirements = base / "rb-requirements.txt"
    requirements.write_text(subprocess.run(
        [uv, "export", "--frozen", "--no-dev", "--no-emit-project", "--no-hashes", "--format",
         "requirements.txt", "-q"], cwd=source, check=True, capture_output=True, text=True).stdout)
    python = venv / "bin" / "python"
    if not python.exists():
        subprocess.run([uv, "venv", "-q", "--python", BASELINE["environments"]["python"], str(venv)], check=True)
    subprocess.run([uv, "pip", "install", "-q", "--python", str(python), "-r", str(requirements)], check=True)
    subprocess.run([uv, "pip", "install", "-q", "--python", str(python), "--no-deps", "--reinstall", str(wheel)],
                   check=True)
    with zipfile.ZipFile(wheel) as archive_file:
        record = next(n for n in archive_file.namelist() if n.endswith(".dist-info/RECORD"))
        record_bytes = archive_file.read(record)
        facts["wheel_record_sha256"] = hashlib.sha256(record_bytes).hexdigest()
    # The package-file identity the drivers' origin check enforces (compare/harness/origin.py record_files: sorted
    # '<path>,sha256=<b64>' RECORD rows of codex_harness/ and zeus/), computed here from the built wheel's own RECORD.
    facts.update(package_file_identity(record_bytes))
    facts["wheel_filename_matches_baseline"] = wheel.name == expected["filename"]
    facts["wheel_record_matches_baseline"] = (facts["wheel_record_sha256"] == expected["wheel_record_sha256"]
                                              and facts["package_files"] == expected.get("package_files")
                                              and facts["package_files_digest"] == expected.get("package_files_digest"))
    return facts


def package_file_identity(record_bytes: bytes) -> dict:
    """`package_files` and `package_files_digest` of a wheel RECORD, by the method of `origin.record_files`."""
    rows = []
    for row in csv.reader(io.StringIO(record_bytes.decode("utf-8"))):
        if len(row) >= 2 and row[1] and row[0].split("/", 1)[0] in ("codex_harness", "zeus"):
            rows.append(f"{row[0]},{row[1]}")
    return {"package_files": len(rows), "package_files_digest": hashlib.sha256("\n".join(sorted(rows)).encode()).hexdigest()}


def scenarios() -> list[dict]:
    return [json.loads(p.read_text(encoding="utf-8"))
            for p in sorted((COMPARE / "scenarios").glob("*.json"))]


def run_driver(python: Path, driver: Path, work: Path, extra_env: dict, use_bwrap: bool,
               binds: list[Path] | None = None, pythonpath_append: Path | None = None) -> dict:
    env = provider_guard.child_environment(work / "env", extra=extra_env)
    if pythonpath_append is not None:  # the guard owns PYTHONPATH (its sitecustomize): append, never substitute
        env["PYTHONPATH"] = os.pathsep.join(p for p in (env.get("PYTHONPATH"), str(pythonpath_append)) if p)
    if extra_env.get(PG_PAIR_ENV):
        # The pair families run the M7 `docker exec` tool forms against their two owned fixtures: the fake
        # `docker` gives way to the real client, and the guard admits exactly those forms (DOCKER_PGEXEC_ENV).
        (work / "env" / "fakebin" / "docker").unlink(missing_ok=True)
        env.update({provider_guard.DOCKER_OPT_IN_ENV: "1", provider_guard.DOCKER_PGEXEC_ENV: "1"})
    argv = [str(python), "-B", str(driver)]
    if use_bwrap:
        # The run root stays writable for both sides: the fixture sockets live beside their cwd.
        argv = provider_guard.bwrap_prefix(binds or [work]) + argv
    proc = subprocess.run(argv, cwd=str(work), env=env, capture_output=True, text=True, timeout=900)
    if proc.returncode != 0:
        tail = proc.stderr.strip().splitlines()[-5:]
        return {"error": f"driver exit {proc.returncode}", "stderr_tail": tail}
    return json.loads(proc.stdout.strip().splitlines()[-1])


OWNER_KEY = "zeus.rebuild.owner"
PG_PAIR_ENV = "ZEUS_REBUILD_PG_PAIR"


class FixtureCleanupError(RuntimeError):
    """The disposable PostgreSQL fixture could not be proven removed (S0 SF-1): residue is uncertain."""


class DisposablePostgres:
    """A labelled, network-less PostgreSQL container reachable only through a Unix socket directory
    under this run's scratch root; its data lives on a tmpfs and the container is removed on exit.
    No port is published and no password exists (trust on the private socket only).

    Ownership (S0 SF-1): a per-instance owner label marks the container this object started. One
    bounded cleanup path runs on startup failure (readiness timeout, log-read error, interrupted
    start) and on normal or body-error exit. It removes only a container carrying this owner label,
    never an unrelated container that merely shares the name, verifies absence afterwards, and raises
    FixtureCleanupError when residue cannot be ruled out. A primary error is always preserved; a
    cleanup failure during it is reported as a note, without payloads."""

    user, dump_dir = "postgres", None  # the single S0 fixture; a pair member sets both (see __init__)

    def __init__(self, work: Path, *, role: str = "", user: str = "postgres", dump_dir: Path | None = None):
        """`role`, `user` and `dump_dir` serve the `disposable-postgresql-pair` families (S7 restore design §2):
        a named member of a pair, a superuser other than `postgres`, and a dump directory under this run's
        root bind-mounted at `/dump` in both members. The defaults are the single S0 fixture, unchanged."""
        suffix = f"-{role}" if role else ""
        # A Unix socket path is limited to 107 bytes: a pair member's directory stays as short as the single one.
        self.socket = work / (f"pg-{role}" if role else "pg-socket")
        self.socket.mkdir()
        self.socket.chmod(0o777)
        self.name = f"{provider_guard.FIXTURE_NAME_PREFIX}s0-pg-{os.getpid()}{suffix}"
        self.owner_value = f"{os.getpid()}-{time.monotonic_ns()}"
        self.claimed = False
        self.container_id = ""
        self.user, self.dump_dir = user, dump_dir
        self.env = {**os.environ, provider_guard.DOCKER_OPT_IN_ENV: "1",
                    provider_guard.DOCKER_BIND_ROOT_ENV: str(work)}
        self.dsn = f"host={self.socket} port=5432 dbname=postgres user={user} connect_timeout=5"

    def docker(self, *args, timeout=60) -> subprocess.CompletedProcess:
        return subprocess.run(["docker", *args], env=self.env, capture_output=True, text=True,
                              timeout=timeout)

    def _holder(self) -> str | None:
        """The owner-label value of the container holding self.name, "" if it has none, None if absent.

        Uses only guard-admitted forms: `inspect --format` on the owned fixture name (no `ps`, no ids)."""
        found = self.docker("inspect", "--format", f'{{{{index .Config.Labels "{OWNER_KEY}"}}}}', self.name)
        if found.returncode == 0:
            return found.stdout.strip()
        # Docker 29 spells it "no such object"; older engines "No such object"/"No such container".
        if "no such object" in found.stderr.lower() or "no such container" in found.stderr.lower():
            return None
        raise FixtureCleanupError("disposable PostgreSQL ownership lookup failed")

    def cleanup(self) -> None:
        """Remove exactly the container this instance started and prove absence; raise when that
        cannot be shown. A same-name container with another owner is never removed."""
        holder = self._holder()
        if holder is None:
            return
        if holder != self.owner_value:
            raise FixtureCleanupError("disposable PostgreSQL name is held by a container this instance did not start")
        removed = self.docker("rm", "-f", self.name)
        if removed.returncode != 0 and "no such container" not in removed.stderr.lower():
            raise FixtureCleanupError("disposable PostgreSQL removal failed")
        if self._holder() is not None:
            raise FixtureCleanupError("disposable PostgreSQL still present after removal")

    def _start(self) -> None:
        try:
            taken = self._holder() is not None
        except FixtureCleanupError:
            taken = True
        if taken:
            # Never remove a container we did not start merely because the name collides.
            self.claimed = False
            raise RuntimeError("disposable PostgreSQL name is taken or unverifiable; refusing to start")
        self.claimed = True
        # The server runs as this user, so the socket directory stays removable by the runner.
        uid, gid = os.getuid(), os.getgid()
        started = self.docker(
            "run", "-d", "--rm", "--network", "none", "--label", provider_guard.FIXTURE_LABEL,
            "--label", "zeus.rebuild=s0", "--label", f"{OWNER_KEY}={self.owner_value}", "--name", self.name,
            "--user", f"{uid}:{gid}",
            "--mount", f"type=bind,src={self.socket},dst=/var/run/postgresql",
            *(["--mount", f"type=bind,src={self.dump_dir},dst=/dump"] if self.dump_dir else []),
            "--tmpfs", f"/var/lib/postgresql/data:uid={uid},gid={gid},mode=0700",
            *(["-e", f"POSTGRES_USER={self.user}"] if self.user != "postgres" else []),
            "-e", "POSTGRES_HOST_AUTH_METHOD=trust", PG_IMAGE,
            timeout=300)
        if started.returncode != 0:
            raise RuntimeError("disposable PostgreSQL did not start: " + started.stderr.strip()[-300:])
        self.container_id = started.stdout.strip()
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            logs = self.docker("logs", self.name)
            text = logs.stdout + logs.stderr
            done = text.find("PostgreSQL init process complete")
            if done >= 0 and "ready to accept connections" in text[done:]:
                return
            time.sleep(1)
        raise RuntimeError("disposable PostgreSQL did not become ready")

    def __enter__(self):
        try:
            self._start()
        except BaseException as primary:
            # __exit__ does not run when __enter__ raises: clean up here, preserving the primary error.
            if not self.claimed:
                raise
            try:
                self.cleanup()
            except FixtureCleanupError as uncertain:
                primary.add_note(f"cleanup: {uncertain}")
            raise
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            self.cleanup()
        except FixtureCleanupError as uncertain:
            if exc is None:
                raise
            exc.add_note(f"cleanup: {uncertain}")
        return False


class PostgresPair:
    """The `disposable-postgresql-pair` fixture (S7 restore design §2): a source and a target DisposablePostgres
    with superuser `zeus`, sharing one dump directory under this run's root, mounted at `/dump`. Each member keeps
    the S0 ownership/cleanup rules; the pair removes both, the target first, even when one fails."""

    def __init__(self, work: Path, dump: Path):
        self.dump = dump
        self.source = DisposablePostgres(work, role="source", user="zeus", dump_dir=dump)
        self.target = DisposablePostgres(work, role="target", user="zeus", dump_dir=dump)
        self.stack = contextlib.ExitStack()

    def description(self) -> str:
        return json.dumps({"user": "zeus", "dump": "/dump", "host_dump": str(self.dump),
                           **{role: {"container": m.name, "socket": str(m.socket), "dsn": m.dsn}
                              for role, m in (("source", self.source), ("target", self.target))}},
                          sort_keys=True)

    def __enter__(self):
        with contextlib.ExitStack() as stack:
            stack.enter_context(self.source)
            stack.enter_context(self.target)
            self.stack = stack.pop_all()
        return self

    def __exit__(self, exc_type, exc, tb):
        return self.stack.__exit__(exc_type, exc, tb)


class DisposableRedis(DisposablePostgres):
    """A labelled, network-less Redis reachable only through a Unix socket under this run's scratch
    root, with persistence off, removed on exit; the same owner-label lifecycle as the PostgreSQL
    fixture (S0 SF-1). Each scenario case uses its own key namespace on it."""

    def __init__(self, work: Path):
        self.socket = work / "redis-socket"
        self.socket.mkdir()
        self.socket.chmod(0o777)
        self.name = f"{provider_guard.FIXTURE_NAME_PREFIX}s1-redis-{os.getpid()}"
        self.owner_value = f"{os.getpid()}-{time.monotonic_ns()}"
        self.claimed = False
        self.container_id = ""
        self.env = {**os.environ, provider_guard.DOCKER_OPT_IN_ENV: "1",
                    provider_guard.DOCKER_BIND_ROOT_ENV: str(work)}
        self.url = f"unix://{self.socket}/redis.sock?db=0"

    def _start(self) -> None:
        try:
            taken = self._holder() is not None
        except FixtureCleanupError:
            taken = True
        if taken:
            self.claimed = False
            raise RuntimeError("disposable Redis name is taken or unverifiable; refusing to start")
        self.claimed = True
        uid, gid = os.getuid(), os.getgid()
        started = self.docker(
            "run", "-d", "--rm", "--network", "none", "--label", provider_guard.FIXTURE_LABEL,
            "--label", "zeus.rebuild=s1", "--label", f"{OWNER_KEY}={self.owner_value}", "--name", self.name,
            "--user", f"{uid}:{gid}", "--mount", f"type=bind,src={self.socket},dst=/run/zeus-redis",
            REDIS_IMAGE, "redis-server", "--port", "0", "--unixsocket", "/run/zeus-redis/redis.sock",
            "--unixsocketperm", "777", "--save", "", "--appendonly", "no", timeout=300)
        if started.returncode != 0:
            raise RuntimeError("disposable Redis did not start: " + started.stderr.strip()[-300:])
        self.container_id = started.stdout.strip()
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            logs = self.docker("logs", self.name)
            if "Ready to accept connections" in logs.stdout + logs.stderr:
                return
            time.sleep(0.5)
        raise RuntimeError("disposable Redis did not become ready")


def differing_paths(expected, actual, path="$") -> list[str]:
    """JSON paths where a result differs from its golden (no values: payloads are never printed)."""
    if isinstance(expected, dict) and isinstance(actual, dict):
        out = []
        for key in sorted(set(expected) | set(actual), key=str):
            if key not in expected or key not in actual:
                out.append(f"{path}.{key} (missing on one side)")
            else:
                out += differing_paths(expected[key], actual[key], f"{path}.{key}")
        return out
    if isinstance(expected, list) and isinstance(actual, list) and len(expected) == len(actual):
        return [p for i, (e, a) in enumerate(zip(expected, actual))
                for p in differing_paths(e, a, f"{path}[{i}]")]
    return [] if expected == actual else [path]


INTENDED_OPS = frozenset({"absent", "remove_item", "replace", "add", "append_items"})
# G1-13c: a declaration of layer `rebaseline` is a difference between the M7 golden and the approved rebaseline's own
# result (every entry cites REBASELINE-MAIN-S2R and the S2R hunk); the rest are the target's declared differences.
LAYERS = frozenset({None, "rebaseline"})


def apply_intended_differences(golden, declarations) -> tuple[object, list[str]]:
    """The target's EXPECTED result: the reference golden with each declared, authorized intended difference applied.

    A declaration is `{"path": "$.a.b", "op": "absent" | "remove_item" | "replace" | "add", "item": <remove_item>,
    "value": <replace, add>, "key": <add, optionally replace>, "authority": "<who decided, where recorded>"}`. It is
    an ASSERTION, not a mask:
    - the path must exist in the reference golden (a stale declaration is refused);
    - the target must then differ in exactly that way (the key absent, exactly that one list item removed, the value
      at the path exactly `value`, the member `key` of the object at the path exactly `value`, or the list at the path
      followed by exactly the items of `value` for `append_items`);
    - every other byte must be equal.
    `path` is split on `.`, so a member whose name contains a dot is addressed only as a literal `key` under its
    parent path: `add` names the EXISTING object in `path` and a `key` that must be ABSENT there (an existing one is
    "stale or not an addition"); `replace` with a `key` names the parent in `path` and the member in `key`.

    Used only for explicitly retired or additive behaviour (e.g. the W-B Windows branches the user retired on
    2026-09-28, DESIGN-s7 §0; the S9 event catalog additions, DESIGN-s9-X §1). Returns `(expected, problems)`; any
    problem makes the scenario fail."""
    expected = json.loads(json.dumps(golden))
    problems = []
    for index, declaration in enumerate(declarations or []):
        path, op = declaration.get("path"), declaration.get("op")
        literal = declaration.get("key")
        if (not isinstance(path, str) or not path.startswith("$.") or op not in INTENDED_OPS
                or not str(declaration.get("authority") or "").strip()
                or declaration.get("layer") not in LAYERS
                or (op in ("replace", "add") and "value" not in declaration)
                or (op == "append_items" and not isinstance(declaration.get("value"), list))
                or (op == "add" and not isinstance(literal, str))
                or (op == "replace" and "key" in declaration and not isinstance(literal, str))
                or (op in ("absent", "remove_item", "append_items") and "key" in declaration)):
            problems.append(f"intended_differences[{index}]: invalid declaration")
            continue
        keys = path[2:].split(".")
        node = expected
        if op == "add" or (op == "replace" and "key" in declaration):
            for key in keys:
                node = node.get(key) if isinstance(node, dict) else None
            last = literal
            if op == "replace" and (not isinstance(node, dict) or last not in node):
                problems.append(f"intended_differences[{index}]: {path} has no member {last!r} (stale)")
                continue
            if op == "add":
                if not isinstance(node, dict):
                    problems.append(f"intended_differences[{index}]: {path} is not an object in the reference golden (stale)")
                    continue
                if last in node:
                    problems.append(f"intended_differences[{index}]: {path} already has member {last!r} (stale or not an addition)")
                    continue
            node[last] = declaration["value"]
            continue
        for key in keys[:-1]:
            node = node.get(key) if isinstance(node, dict) else None
        last = keys[-1]
        if not isinstance(node, dict) or last not in node:
            problems.append(f"intended_differences[{index}]: {path} is not in the reference golden (stale)")
            continue
        if op == "absent":
            del node[last]
        elif op == "replace":
            node[last] = declaration["value"]
        elif op == "append_items":
            if not isinstance(node[last], list):
                problems.append(f"intended_differences[{index}]: {path} is not a list in the reference golden (stale)")
                continue
            node[last] = node[last] + declaration["value"]
        else:
            value = node[last]
            if not isinstance(value, list) or value.count(declaration.get("item")) != 1:
                problems.append(f"intended_differences[{index}]: {path} does not hold the item exactly once")
                continue
            value.remove(declaration["item"])
    return expected, problems


def split_layers(declarations) -> tuple[list, list]:
    """-> (the `rebaseline`-layer declarations, the others), each in declared order (G1-13c)."""
    declared = list(declarations or [])
    return ([d for d in declared if d.get("layer") == "rebaseline"],
            [d for d in declared if d.get("layer") != "rebaseline"])


# G1-13c (owner decision G1-13C-COMPARE-DECISION rule 4, R-G1-12b): the approved rebaseline's sealed runtime tree is the
# S2R delta, so the runtime revision (a content hash) and every value derived from it differ from M7's. The closed mask
# `rebaseline_runtime_revision` (compare/masks.json) is applied ONLY in a rebaseline-reference run, ONLY to its listed
# families, and equality-preservingly: it never hides whether two values were equal.
HEX40 = re.compile(r"[0-9a-f]{40}")
# the revision leaves: the runtime revision itself, the git tree of the sealed revision (`tree`), and the two fixture
# source revisions the delivery.managed_systemd family reports as `revisions.a` / `revisions.b`
REVISION_LEAVES = frozenset({"revision", "attested_revision", "runtime_revision", "tree"})
REVISION_PAIR_LEAVES = frozenset({"a", "b"})
REVISION_MASK_ID = "rebaseline_runtime_revision"
MASKS_FILE = COMPARE / "masks.json"


def rebaseline_revision_mask(family: str) -> dict | None:
    document = json.loads(MASKS_FILE.read_text(encoding="utf-8"))
    for mask in document["masks"]:
        if mask["id"] == REVISION_MASK_ID and family in mask["scenarios"]:
            return mask
    return None


def _revision_pairs(expected, actual, path=()):
    """(path, expected revision, actual revision) at every revision leaf the two results share and differ in."""
    if isinstance(expected, dict) and isinstance(actual, dict):
        for key in sorted(set(expected) & set(actual)):
            yield from _revision_pairs(expected[key], actual[key], path + (key,))
    elif isinstance(expected, list) and isinstance(actual, list) and len(expected) == len(actual):
        for index, (e, a) in enumerate(zip(expected, actual)):
            yield from _revision_pairs(e, a, path + (str(index),))
    elif (isinstance(expected, str) and isinstance(actual, str) and path
          and (path[-1] in REVISION_LEAVES or (path[-1] in REVISION_PAIR_LEAVES and path[-2:-1] == ("revisions",)))
          and HEX40.fullmatch(expected) and HEX40.fullmatch(actual) and expected != actual):
        yield path, expected, actual


def _replace_revisions(value, table: dict):
    if isinstance(value, dict):
        return {HEX40.sub(lambda m: table.get(m.group(0), m.group(0)), str(k)): _replace_revisions(v, table)
                for k, v in value.items()}
    if isinstance(value, list):
        return [_replace_revisions(v, table) for v in value]
    if isinstance(value, str):
        return HEX40.sub(lambda m: table.get(m.group(0), m.group(0)), value)
    return value


def _alpha_leaves(value, leaves: frozenset, names: dict):
    if isinstance(value, dict):
        out = {}
        for key in sorted(value, key=str):
            item = value[key]
            if key in leaves and not isinstance(item, (dict, list)):
                table = names.setdefault(key, {})
                out[key] = f"<{key}:{table.setdefault(json.dumps(item), len(table) + 1)}>"
            else:
                out[key] = _alpha_leaves(item, leaves, names)
        return out
    if isinstance(value, list):
        return [_alpha_leaves(v, leaves, names) for v in value]
    return value


def rebaseline_normalise(family: str, expected, actual) -> tuple[object, object, bool]:
    """-> (expected, actual, masked) with the closed mask applied. A runtime revision is masked only where the two
    results hold different revisions at the SAME revision leaf, and only as a bijection (one expected revision for one
    actual revision); it becomes `<REV:n>` in values AND keys. The mask's `leaves` (digests and counts of the sealed
    runtime tree) become `<leaf:n>` by first appearance in sorted key order, so equal values stay equal and unequal
    values stay unequal."""
    mask = rebaseline_revision_mask(family)
    if mask is None:
        return expected, actual, False
    pairs = sorted(_revision_pairs(expected, actual))
    forward: dict[str, str] = {}
    backward: dict[str, str] = {}
    for _, e, a in pairs:
        if forward.setdefault(e, a) != a or backward.setdefault(a, e) != e:
            forward.pop(e, None)  # not a bijection: both stay raw, the difference is reported
            backward.pop(a, None)
    tokens = {}
    for _, e, a in pairs:
        if forward.get(e) == a and e not in tokens:
            tokens[e] = f"<REV:{len(tokens) + 1}>"
    to_expected = tokens
    to_actual = {forward[e]: token for e, token in tokens.items()}
    leaves = frozenset(mask.get("leaves", []))
    return (_alpha_leaves(_replace_revisions(expected, to_expected), leaves, {}),
            _alpha_leaves(_replace_revisions(actual, to_actual), leaves, {}), True)


# S11 unit P (owner; DESIGN-s11 §20.5 follow-up): the target side runs from an exact copy of the target distribution
# OUTSIDE any Git checkout, as the reference side runs from its installed wheel. After the promotion the package's
# grandparent is the repository root, a checkout, so code that reads the runtime revision of the package's own root
# (`delivery.adapters.deployment`: M7's `codex_harness.__file__` parents[2] rule) saw a checkout on the target side
# only (`delivery.host_targets`, 2026-10-06): an environment asymmetry, not a product difference. Before the promotion
# `target/` was no checkout root either, so the copy restores the compared conditions on both layouts.
TARGET_COPY_PATHS = ("src", "deploy", "scripts", "pyproject.toml")


def tree_digest(root: Path) -> str:
    """sha256 over (relative path, bytes) of every file under `root`, bytecode excluded."""
    digest = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file() and "__pycache__" not in p.parts
                       and p.suffix != ".pyc"):
        digest.update(path.relative_to(root).as_posix().encode() + b"\0" + path.read_bytes() + b"\0")
    return digest.hexdigest()


def target_tree_copy(work: Path) -> tuple[Path, str]:
    """-> (<work>/target-tree, the digest of its `src`): the run copy of the target distribution, no bytecode, never
    a checkout. Refuses when the copied `src` is not byte-identical to TARGET_SRC."""
    dest = work / "target-tree"
    dest.mkdir()
    for rel in TARGET_COPY_PATHS:
        source = TARGET_DIR / rel
        if source.is_dir():
            shutil.copytree(source, dest / rel, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        elif source.is_file():
            shutil.copy2(source, dest / rel)
    digest = tree_digest(dest / "src")
    if digest != tree_digest(TARGET_SRC) or (dest / ".git").exists():
        raise RuntimeError("the target run copy differs from TARGET_SRC or is a checkout")
    return dest, digest


def run_target(driver_path: Path, work: Path, extra: dict, use_bwrap: bool) -> dict:
    if not TARGET_PYTHON.exists():
        return {"error": TARGET_VENV_MISSING}
    target_work = work / "target-side"
    target_work.mkdir()
    copy, digest = target_tree_copy(work)
    result = run_driver(TARGET_PYTHON, driver_path, target_work,
                        {**extra, "ZEUS_REBUILD_TARGET_SRC": str(copy / "src")}, use_bwrap, binds=[work],
                        pythonpath_append=copy / "src")
    origin = result.get("origin") if isinstance(result, dict) else None
    if isinstance(origin, dict):
        # R-O: every product module came from the run copy, which is byte-identical to TARGET_SRC (digest above)
        exact = origin.get("tree") == str(copy / "src")
        result["origin"] = {**origin, "tree": str(TARGET_SRC) if exact else origin.get("tree"),
                            "run_copy": str(copy / "src"), "copy_digest": digest}
    return result


GOLDENS_REBASELINE = COMPARE / "goldens" / "rebaseline"


def rebaseline_record_refusal(entry_id: str, only: list[str]) -> str | None:
    """Why `--record` with `--reference rebaseline:<entry_id>` is refused, or None when every selected family is a
    scenario that declares `"reference": "rebaseline:<entry_id>"` and keeps its golden under
    `goldens/rebaseline/<entry_id>/` (G1-13c decision rule 5). A family referenced by M7 is never recordable here."""
    if not only:
        return "it needs --only <family> of scenarios that declare their rebaseline reference"
    by_family = {s["family"]: s for s in scenarios()}
    home = (GOLDENS_REBASELINE / entry_id).resolve()
    for family in only:
        scenario = by_family.get(family)
        if scenario is None:
            return f"unknown family {family!r}"
        if scenario.get("reference") != f"rebaseline:{entry_id}":
            return f"{family} is referenced by M7"
        if home not in (COMPARE / scenario["golden"]).resolve().parents:
            return f"{family} keeps its golden outside goldens/rebaseline/{entry_id}/"
    return None


def resolve_reference(reference: str, record: bool, only: list[str] | None = None) -> tuple[Path, Path, str | None]:
    """-> (reference venv, SOURCE root for the drivers, rebaseline id or None). `m7` (the default) is the SOURCE wheel;
    `rebaseline:<id>` is the approved rebaseline's wheel (G1-11). A rebaseline is recorded only for the scenarios that
    declare it as their reference (`rebaseline_record_refusal`): every M7 golden stays M7's."""
    if reference == "m7":
        return SCRATCH / "venv-ref", SCRATCH / "source", None
    kind, _, entry_id = reference.partition(":")
    if kind != "rebaseline" or not entry_id:
        sys.exit(f"unknown --reference {reference!r}: expected m7 or rebaseline:<id>")
    entry = rebaseline_entry(entry_id)
    if record:
        reason = rebaseline_record_refusal(entry["id"], only or [])
        if reason:
            sys.exit(f"refused: --record with a rebaseline reference; goldens stay M7's ({reason}; "
                     "collect other rebaseline output from stdout)")
    return SCRATCH / f"venv-rb-{entry['id']}", SCRATCH / f"rebaseline-{entry['id']}" / "source", entry["id"]


def run(record: bool, use_bwrap: bool, only: list[str], pg: bool = False,
        redis: bool = False, reference: str = "m7", target_vs_reference: bool = False) -> tuple[dict, bool]:
    if target_vs_reference and (record or not reference.startswith("rebaseline:")):
        sys.exit("refused: --target-vs-reference compares the target with a rebaseline reference result "
                 "(--reference rebaseline:<id>, never with --record)")
    ref_venv, source_root, rebaseline = resolve_reference(reference, record, only)
    python = ref_venv / "bin" / "python"
    if not python.exists():
        sys.exit("reference venv missing: run `python compare/run.py prepare"
                 + (f" --rebaseline {rebaseline}`" if rebaseline else "`") + " first")
    # A rebaseline reference is held to its own pinned package-file identity (G1-11 owner correction): the origin
    # check proves the drivers ran on the rebaseline wheel, exactly as it proves M7 for the default reference.
    expected = rebaseline_entry(rebaseline)["rebaseline_wheel"] if rebaseline else BASELINE["source"]["reference_wheel"]
    report, ok = {"bwrap": use_bwrap, "scenarios": {}}, True
    for scenario in scenarios():
        family = scenario["family"]
        if only and family not in only:
            continue
        if scenario.get("reference") and scenario["reference"] != f"rebaseline:{rebaseline}":
            # G1-13c rule 5: M7 has no such behaviour; the scenario's reference exists only in its rebaseline wheel
            report["scenarios"][family] = {"slice": scenario["slice"],
                                           "reference": f"not requested (its reference is {scenario['reference']}: "
                                                        f"run with --reference {scenario['reference']})"}
            continue
        requires = scenario.get("requires")
        needs_pair = requires == "disposable-postgresql-pair"
        needs_both = requires == "disposable-postgresql+redis"  # R-c7: one PostgreSQL AND one Redis in one run
        needs_pg = requires == "disposable-postgresql" or needs_pair or needs_both
        needs_redis = requires == "disposable-redis" or needs_both
        if (needs_pg and not pg) or (needs_redis and not redis):
            if needs_both:
                flag = "--pg and --redis: a labelled disposable PostgreSQL and a labelled disposable Redis"
            else:
                flag = "--pg: a labelled disposable PostgreSQL" if needs_pg else "--redis: a labelled disposable Redis"
            report["scenarios"][family] = {"slice": scenario["slice"], "reference": f"not requested (needs {flag})"}
            continue
        target = scenario.get("target_driver")
        target_path = COMPARE / target if target else None
        target_result = None
        with tempfile.TemporaryDirectory(prefix="zeus-s0-run-", dir=SCRATCH) as raw:
            work = Path(raw)
            (work / "reference-side").mkdir()
            extra = {"ZEUS_REBUILD_SOURCE_ROOT": str(source_root)}
            blocks_out = work / "reference-side" / "block-exercise.json"
            if needs_pair:
                dump = work / "dump"
                dump.mkdir(mode=0o700)
                fixture = PostgresPair(work, dump)
            elif needs_both:
                fixture = None
            else:
                fixture = DisposablePostgres(work) if needs_pg else DisposableRedis(work) if needs_redis else None
            with contextlib.ExitStack() as stack:
                if needs_both:
                    extra["ZEUS_REBUILD_PG_DSN"] = stack.enter_context(DisposablePostgres(work)).dsn
                    extra["ZEUS_REBUILD_REDIS_URL"] = stack.enter_context(DisposableRedis(work)).url
                elif fixture is not None:
                    stack.enter_context(fixture)
                    if needs_pair:
                        extra[PG_PAIR_ENV] = fixture.description()
                    elif needs_pg:
                        extra["ZEUS_REBUILD_PG_DSN"] = fixture.dsn
                    if needs_redis:
                        extra["ZEUS_REBUILD_REDIS_URL"] = fixture.url
                # S11 R-L3d: only the REFERENCE side of a record run is armed (DESIGN-s11 §17 item 1)
                armed = {block_exercise.ENV: str(blocks_out)} if record else {}
                result = run_driver(python, COMPARE / scenario["reference_driver"], work / "reference-side",
                                    {**extra, **armed}, use_bwrap, binds=[work])
                # read inside the run root: it is removed with the run (a driver without windows writes no file)
                blocks = (json.loads(blocks_out.read_text(encoding="utf-8")) if blocks_out.is_file() else None)
                if target_path is not None and target_path.exists() and not needs_pair:
                    target_result = run_target(target_path, work, extra, use_bwrap)
            if needs_pair and target_path is not None and target_path.exists():
                # A pair family's cases fix their database names "on a fresh pair per run" (S7 restore design §2):
                # the target side gets its own fresh pair, started after the reference side's pair is removed.
                side = work / "t"
                side.mkdir()
                (side / "dump").mkdir(mode=0o700)
                with PostgresPair(side, side / "dump") as pair:
                    target_result = run_target(target_path, work, {**extra, PG_PAIR_ENV: pair.description()},
                                               use_bwrap)
        row = {"slice": scenario["slice"]}
        golden_path = COMPARE / scenario["golden"]
        if "error" in result:
            row.update(reference="error", detail=result)
            ok = False
        else:
            origin = result["origin"]
            origin_ok = (origin.get("package_files_digest") == expected["package_files_digest"]
                         and origin.get("package_files") == expected["package_files"])
            if record:
                golden_path.parent.mkdir(parents=True, exist_ok=True)
                golden_path.write_text(json.dumps(result["result"], sort_keys=True, indent=1,
                                                  ensure_ascii=False) + "\n", encoding="utf-8")
                if blocks is not None:
                    golden_path.with_name(f"{family}.blocks.json").write_text(
                        block_exercise.artifact(family, blocks), encoding="utf-8")
            golden = json.loads(golden_path.read_text(encoding="utf-8")) if golden_path.exists() else None
            ref_expected, ref_actual, ref_masked = golden, result["result"], False
            if rebaseline and golden is not None:
                # G1-13c: the rebaseline's own result is the M7 golden plus its declared, S2R-authorized layer, under
                # the closed revision mask where the family has one (R-G1-12b)
                layer, _ = split_layers(scenario.get("intended_differences"))
                ref_expected, ref_problems = apply_intended_differences(golden, layer)
                if ref_problems:
                    row["rebaseline_difference_problems"] = ref_problems
                    ref_expected = None
                else:
                    ref_expected, ref_actual, ref_masked = rebaseline_normalise(family, ref_expected, ref_actual)
            equal = ref_expected is not None and ref_expected == ref_actual
            if not equal and ref_expected is not None:
                row["differing_paths"] = differing_paths(ref_expected, ref_actual)[:20]
            if ref_masked:
                row["masks"] = [REVISION_MASK_ID]
            row.update(reference="equal" if equal else "DIFFERENT", origin_ok=origin_ok,
                       origin={k: origin.get(k) for k in ("modules_checked", "python", "package_files",
                                                           "package_files_digest")})
            ok = ok and equal and origin_ok
        if target_result is None:
            row["target"] = f"pending: no target implementation before {scenario['slice']}"
        elif "error" in target_result:
            row.update(target="error", target_detail=target_result)
            ok = False
        else:
            # The target is compared with the committed reference golden itself: expectations are
            # never rewritten to match new code (R-C), and nothing but the closed masks applies.
            golden = json.loads(golden_path.read_text(encoding="utf-8")) if golden_path.exists() else None
            t_origin = target_result["origin"]
            t_origin_ok = (t_origin.get("tree") == str(TARGET_SRC) and t_origin.get("modules_checked", 0) > 0
                           and target_result.get("side") == "target")
            declared = scenario.get("intended_differences") or []
            layer, others = split_layers(declared)
            if target_vs_reference:
                # G1-13c rule 3: the target against the reference result of THIS run (no stored golden); only the
                # target's own declared differences (the non-rebaseline layer) and the closed mask apply
                base, applied = result.get("result") if "error" not in result else None, others
            else:
                base, applied = golden, layer + others
            target_expected, problems = apply_intended_differences(base, applied) if base is not None else (None, [])
            target_actual, masked = target_result["result"], False
            if target_vs_reference and target_expected is not None and not problems:
                target_expected, target_actual, masked = rebaseline_normalise(family, target_expected, target_actual)
            equal = base is not None and not problems and target_expected == target_actual
            if declared:
                row["intended_differences"] = len(declared)
            if problems:
                row["intended_difference_problems"] = problems
            if masked:
                row["target_masks"] = [REVISION_MASK_ID]
            if not equal and target_expected is not None:
                row["target_differing_paths"] = differing_paths(target_expected, target_actual)[:20]
            if target_vs_reference:
                row["target_vs_reference"] = True
            row.update(target="equal" if equal else "DIFFERENT", target_origin_ok=t_origin_ok,
                       target_origin={k: t_origin.get(k) for k in ("modules_checked", "python")})
            ok = ok and equal and t_origin_ok
        report["scenarios"][family] = row
    return report, ok


def target_integration() -> dict:
    """The target test suite with its integration tests enabled against a labelled disposable
    PostgreSQL and Redis (§5.1 integration job; R-X: never the host's production ports)."""
    if not TARGET_PYTHON.exists():
        return {"error": TARGET_VENV_MISSING}
    SCRATCH.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="zeus-s1-integration-", dir=SCRATCH) as raw:
        work = Path(raw)
        with DisposablePostgres(work) as database, DisposableRedis(work) as redis_fixture:
            env = provider_guard.child_environment(work / "env", extra={
                "HARNESS_INTEGRATION": "1", "ZEUS_TEST_DSN": database.dsn, "HARNESS_REDIS_URL": redis_fixture.url})
            done = subprocess.run([str(TARGET_PYTHON), "-m", "pytest", "-q", "-p", "no:cacheprovider", "-rfEs",
                                   "--basetemp", str(work / "pytest")], cwd=str(TARGET_DIR), env=env,
                                  capture_output=True, text=True, timeout=1800)
    lines = done.stdout.strip().splitlines()
    tail = lines[-15:]
    # S11 (owner, int57 CI): the 15-line tail is all skip lines, so a failing node was never named in the CI log;
    # every FAILED/ERROR summary line is reported in full (observation only: the exit code is unchanged)
    failures = [line for line in lines if line.startswith(("FAILED ", "ERROR "))]
    return {"exit_code": done.returncode, "summary": tail[-1] if tail else "", "failures": failures, "tail": tail}


def docker_fixture() -> dict:
    """The S3 labelled Docker fixture suite (§5.3 S3 slice exit): the target's composed container controls
    checked in real, network-less, owned-fixture containers of an admitted fixture image. The guard stays
    default-deny except for exactly these forms; the fake `docker` of the child environment is removed so
    the admitted calls reach the real client, while the fake provider CLIs stay first on PATH."""
    if not TARGET_PYTHON.exists():
        return {"error": TARGET_VENV_MISSING}
    SCRATCH.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="zeus-s3-docker-", dir=SCRATCH) as raw:
        work = Path(raw)
        bind = work / "bind"
        bind.mkdir()
        env = provider_guard.child_environment(work / "env", extra={
            "ZEUS_TEST_DOCKER": "1", "ZEUS_TEST_DOCKER_BIND_ROOT": str(bind)})
        (work / "env" / "fakebin" / "docker").unlink()
        done = subprocess.run([str(TARGET_PYTHON), "-m", "pytest", "-q", "-p", "no:cacheprovider", "-rs",
                               "--basetemp", str(work / "pytest"), "tests/test_s3_docker_fixture.py"],
                              cwd=str(TARGET_DIR), env=env, capture_output=True, text=True, timeout=900)
    tail = done.stdout.strip().splitlines()[-15:]
    summary = tail[-1] if tail else ""
    ok = done.returncode == 0 and " passed" in summary and "skipped" not in summary
    return {"exit_code": done.returncode if ok or done.returncode else 1, "summary": summary, "tail": tail}


# SKIPPED-TEST-CLOSURE-20261004 B: the owner-run checks that need a real stack under the guard. Each sets only the opt-in
# forms its tests need; a skip of a named test is a failure of the command, not a pass.
OWNER_DOCKER_SKIP_MARKERS = ("Explicit disposable Docker", "Two disposable PostgreSQL 17 + pgvector")


def _owner_pytest(env: dict, work: Path, files: list[str], timeout: int, junit: str | None = None) -> dict:
    # S11 RH-1: `--junit PATH` keeps a per-node JUnit of the owner run, which `relabel.py bundle --junit` merges (R-L2f)
    junit = str(Path(junit).resolve()) if junit else None  # pytest runs in target/: a relative path would move
    done = subprocess.run([str(TARGET_PYTHON), "-m", "pytest", "-q", "-p", "no:cacheprovider", "-rs",
                           "--basetemp", str(work / "pytest"), *(["--junitxml", junit] if junit else []), *files],
                          cwd=str(TARGET_DIR), env=env, capture_output=True, text=True, timeout=timeout)
    lines = done.stdout.strip().splitlines()
    summary = lines[-1] if lines else ""
    missed = [line for line in lines if line.startswith("SKIPPED") and any(m in line for m in OWNER_DOCKER_SKIP_MARKERS)]
    ok = done.returncode == 0 and " passed" in summary and not missed
    report = {"exit_code": 0 if ok else (done.returncode or 1), "summary": summary,
              "skipped": [line for line in lines if line.startswith("SKIPPED")], "tail": lines[-15:]}
    if junit:
        report["junit"] = junit
    return report


def verify_stack(junit: str | None = None) -> dict:
    """The ported VerificationServices Docker tests on real disposable compose stacks, under the guard with the
    fixture opt-in plus `ZEUS_TEST_DOCKER_VERIFY_STACK` (exactly the stack's admitted forms; provider_guard.py)."""
    if not TARGET_PYTHON.exists():
        return {"error": TARGET_VENV_MISSING}
    SCRATCH.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="zeus-verify-stack-", dir=SCRATCH) as raw:
        work = Path(raw)
        env = provider_guard.child_environment(work / "env", extra={
            provider_guard.DOCKER_OPT_IN_ENV: "1", provider_guard.DOCKER_VERIFY_STACK_ENV: "1"})
        (work / "env" / "fakebin" / "docker").unlink()
        return _owner_pytest(env, work, ["tests/ported/test_verification.py", "tests/ported/test_host_interruption.py"],
                             2400, junit)


def migration_rehearsal(junit: str | None = None) -> dict:
    """The ported PostgreSQL migration rehearsal on the `disposable-postgresql-pair` fixture (PostgresPair), under the
    guard with only its `docker exec` pg tool forms (DOCKER_PGEXEC), as the restore.pg families run."""
    if not TARGET_PYTHON.exists():
        return {"error": TARGET_VENV_MISSING}
    SCRATCH.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="zeus-pg-rehearsal-", dir=SCRATCH) as raw:
        work = Path(raw)
        dump = work / "dump"
        dump.mkdir()
        with PostgresPair(work, dump) as pair:
            env = provider_guard.child_environment(work / "env", extra={
                "ZEUS_MIGRATION_TEST_PG_SOURCE_CONTAINER": pair.source.name,
                "ZEUS_MIGRATION_TEST_PG_SOURCE_SOCKET": str(pair.source.socket),
                "ZEUS_MIGRATION_TEST_PG_TARGET_CONTAINER": pair.target.name,
                "ZEUS_MIGRATION_TEST_PG_TARGET_SOCKET": str(pair.target.socket),
                provider_guard.DOCKER_OPT_IN_ENV: "1", provider_guard.DOCKER_PGEXEC_ENV: "1"})
            (work / "env" / "fakebin" / "docker").unlink(missing_ok=True)
            return _owner_pytest(env, work, ["tests/ported/test_host_migration_pg_rehearsal.py"], 1500, junit)


def wheel_check(wheel: str, ref: str = "HEAD") -> dict:
    """S11 A3 (DESIGN-s11 §1): the wheel's RECORD equals the tree (`git ls-files target/src/codex_harness target/src/zeus`,
    prefix removed), file by file, with the sha256 of the tree bytes (`git show <ref>:target/src/<path>`). Paths only."""
    import base64
    import csv
    import io
    prefix = TARGET_PREFIX + "src/"
    tree = [p for p in git("ls-files", "--", prefix + "codex_harness", prefix + "zeus").splitlines() if p]
    expected = {p[len(prefix):]: p for p in tree}
    with zipfile.ZipFile(wheel) as zf:
        records = [n for n in zf.namelist() if n.endswith(".dist-info/RECORD") and n.count("/") == 1]
        if len(records) != 1:
            return {"ok": False, "error": "expected exactly one *.dist-info/RECORD", "records": records}
        rows = list(csv.reader(io.StringIO(zf.read(records[0]).decode("utf-8"))))
    listed = {}
    for row in rows:
        if row and ".dist-info/" not in row[0]:
            listed[row[0]] = row[1] if len(row) > 1 else ""
    extra = sorted(set(listed) - set(expected))
    missing = sorted(set(expected) - set(listed))
    mismatch = []
    for path in sorted(set(listed) & set(expected)):
        digest = hashlib.sha256(git("show", f"{ref}:{expected[path]}", text=False)).digest()
        want = "sha256=" + base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
        if listed[path] != want:
            mismatch.append(path)
    if extra or missing or mismatch:
        return {"ok": False, "extra": extra, "missing": missing, "hash_mismatch": mismatch}
    return {"ok": True, "files": len(listed)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check-tree")
    sub.add_parser("prepare").add_argument("--rebaseline", metavar="ID",
                                           help="build the approved rebaseline's wheel (G1-11) instead of M7's")
    sub.add_parser("target-integration")
    sub.add_parser("docker-fixture")
    for owner_cmd in ("verify-stack", "migration-rehearsal"):  # S11 RH-1
        sub.add_parser(owner_cmd).add_argument("--junit", help="also write the pytest per-node JUnit to this path")
    wheel_cmd = sub.add_parser("wheel-check")
    wheel_cmd.add_argument("wheel")
    run_cmd = sub.add_parser("run")
    run_cmd.add_argument("--record", action="store_true", help="write reference goldens")
    run_cmd.add_argument("--reference", default="m7", metavar="m7|rebaseline:<id>",
                         help="the reference side: SOURCE M7 (default) or an approved rebaseline (--record only for "
                              "scenarios that declare it as their reference)")
    run_cmd.add_argument("--target-vs-reference", action="store_true",
                         help="compare the target with the rebaseline reference result of the same run (G1-13c)")
    run_cmd.add_argument("--no-bwrap", action="store_true")
    run_cmd.add_argument("--only", action="append", default=[])
    run_cmd.add_argument("--pg", action="store_true",
                         help="start a labelled disposable PostgreSQL for scenarios that need one")
    run_cmd.add_argument("--redis", action="store_true",
                         help="start a labelled disposable Redis for scenarios that need one")
    args = parser.parse_args(argv)
    if args.command == "check-tree":
        report = check_tree()
        ok = report["ok"]
    elif args.command == "docker-fixture":
        report = docker_fixture()
        ok = report.get("exit_code") == 0
    elif args.command == "verify-stack":
        report = verify_stack(args.junit)
        ok = report.get("exit_code") == 0
    elif args.command == "migration-rehearsal":
        report = migration_rehearsal(args.junit)
        ok = report.get("exit_code") == 0
    elif args.command == "wheel-check":
        report = wheel_check(args.wheel)
        ok = report["ok"]
    elif args.command == "target-integration":
        report = target_integration()
        ok = report.get("exit_code") == 0
    elif args.command == "prepare":
        report = prepare_rebaseline(args.rebaseline) if args.rebaseline else prepare()
        # The wheel sha256 depends on the unpinned build backend; the RECORD rows are the identity.
        ok = report["wheel_record_matches_baseline"]
    else:
        use_bwrap = provider_guard.bwrap_available() and not args.no_bwrap
        if args.target_vs_reference and (args.record or not args.reference.startswith("rebaseline:")):
            parser.error("--target-vs-reference needs --reference rebaseline:<id> and never --record")
        resolve_reference(args.reference, args.record, args.only)  # refuse before anything is created
        SCRATCH.mkdir(parents=True, exist_ok=True)
        report, ok = run(args.record, use_bwrap, args.only, args.pg, args.redis, args.reference,
                         args.target_vs_reference)
    print(json.dumps({"command": args.command, "ok": ok, **report}, indent=1, sort_keys=True))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
