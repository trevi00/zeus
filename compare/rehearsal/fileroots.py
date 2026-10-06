"""The guard-free, metadata-only file-root layer for Phase P (RH-2 P5a): partition, symlinks, secret names, cp, aibox_data.

Standard library plus `.snapshot` and `Refused` only: importing this never loads `copies` or `compare/run.py`, so the
provider guard stays uninstalled (RH-2c). Every check reads names, `lstat` and `readlink` only; no file content under the
source is read and nothing is written under it (the one subprocess is `CP --version`).

The partition is CLOSED: of the four production tops (`FILE_ROOTS`), `CONTAINERS` are listed but never acquired whole,
`STABLE_ROOTS` are acquired whole, the volatile and excluded paths come from `volatile.json` (via `.snapshot`), and the
direct regular files of `STABLE_FILE_DIRS` that are not volatile are stable single files. Anything else is refused.

Refusal reasons (`Refused.code`; `RefusedFacts.facts` carries names only, up to 16 paths, `secrets` components redacted):
    source_root_missing, source_root_symlink, source_root_not_directory   a top, container or stable root is not a real dir
    partition_unclassified    an entry of a container is none of the listed classes
    secret_path_in_root       a secret or credential NAME exists somewhere in the four tops
    external_symlink_unallowed  an absolute or escaping symlink matches no SYMLINK_ALLOWANCE rule
    git_lock_present          a `*.lock` file under a `.git` directory of `repo` or `worktrees`
    cp_identity               `CP` is not the pinned GNU cp
    aibox_data_origin_foreign aibox_data / codex_harness would be imported from outside the tooling checkout

Run: `cd compare && /usr/bin/python3 -B -m rehearsal.fileroots check [--srv PATH] --out FILE` (exit 0 ok, 1 refusal, 2 usage).
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import re
import resource
import stat
import subprocess
import sys
import time
from pathlib import Path

from . import Refused
from .snapshot import EXCLUDED_PATHS, VOLATILE_PATHS, _rel_parts

SRV = "/srv/zeus"
FILE_ROOTS = ("runtime", "managed-fleet", "repo", "worktrees")
CONTAINERS = ("runtime", "runtime/control", "runtime/control/observations", "runtime/managed-fleet")
STABLE_ROOTS = (
    ("runtime-lanes", "runtime/lanes"),
    ("runtime-control-artifacts", "runtime/control/artifacts"),
    ("runtime-control-verification", "runtime/control/verification"),
    ("runtime-control-worker-sessions", "runtime/control/worker-sessions"),
    ("runtime-control-observations-spool", "runtime/control/observations/spool"),
    ("managed-fleet", "managed-fleet"),
    ("repo", "repo"),
    ("worktrees", "worktrees"),
)
STABLE_FILE_DIRS = ("runtime/control", "runtime/managed-fleet")
SYMLINK_ALLOWANCE = (
    {"root": "runtime-lanes",
     "path": r"^harness/workspaces/review-canary-[0-9a-f]{16}/\.venv/bin/python$",
     "target": "/home/trevi/.local/share/uv/python/cpython-3.12-linux-x86_64-gnu/bin/python3.12",
     "reason": "a review-canary workspace venv's interpreter link into the uv-managed CPython the namespace binds read-only"},
)
CP = "/usr/bin/gnucp"
CP_VERSION_PREFIX = "cp (GNU coreutils) "
CP_ENV = {"PATH": "/usr/bin:/bin", "LC_ALL": "C"}

SECRET_COMPONENTS = frozenset({"secrets", ".codex", ".claude"})
SECRET_BASENAMES = frozenset({"auth.json", ".credentials.json", ".netrc", ".git-credentials", ".env"})
SECRET_BASENAME_GLOBS = ("*.env",)
SECRET_BASENAME_PREFIXES = ("id_rsa", "id_ed25519", "id_ecdsa")

AIBOX_FILES = (
    "scripts/aibox_data/__init__.py", "scripts/aibox_data/inventory.py", "scripts/aibox_data/transfer.py",
    "src/codex_harness/__init__.py", "src/codex_harness/kernel/__init__.py", "src/codex_harness/kernel/ids.py",
    "src/codex_harness/kernel/ports.py",
)
AIBOX_MODULES = (("aibox_data", ("aibox_data.inventory", "aibox_data.transfer")),
                 ("codex_harness", ("codex_harness.kernel.ids",)))
SCHEMA = "zeus:aibox-migration-001:rehearsal:fileroots-check:1"
LISTED = 16  # names listed in a refusal or a fact; the count is always exact


class RefusedFacts(Refused):
    """A `Refused` that also carries bounded, name-only facts for the check record."""

    def __init__(self, code: str, detail: str = "", facts: dict | None = None):
        super().__init__(code, detail)
        self.facts = facts or {}


def _redact(rel: str) -> str:
    return "/".join("<redacted>" if p.lower() == "secrets" else p for p in rel.split("/"))


def _named(paths) -> list[str]:
    return [_redact(p) for p in sorted(paths)[:LISTED]]


def _inside(rel: str, root: str) -> bool:
    a, b = tuple(rel.split("/")), tuple(root.split("/"))
    return a[: len(b)] == b


def static_checks(stable_roots=STABLE_ROOTS, containers=CONTAINERS, volatile=VOLATILE_PATHS, excluded=EXCLUDED_PATHS,
                  file_roots=FILE_ROOTS) -> None:
    """The partition's own consistency, re-checkable with other constants (pinned by tests); runs at import."""
    rels = [rel for _id, rel in stable_roots]
    for i, a in enumerate(rels):
        if rels[i].split("/")[0] not in file_roots:
            raise Refused("partition_static", f"stable root outside the tops: {a}")
        for b in rels[i + 1:]:
            if _inside(a, b) or _inside(b, a):
                raise Refused("partition_static", f"stable roots overlap: {a} / {b}")
    for rel in (*volatile, *excluded):
        parts = "/".join(_rel_parts(rel))
        if any(_inside(parts, root) for root in rels):
            raise Refused("partition_static", f"volatile or excluded path inside a stable root: {rel}")
    for container in containers:
        if not any(_inside(other, container) and other != container for other in (*rels, *volatile, *excluded)):
            raise Refused("partition_static", f"container without a stable root or volatile path below it: {container}")


static_checks()


def _lstat_dir(srv: Path, rel: str) -> None:
    try:
        info = os.lstat(srv / rel)
    except FileNotFoundError:
        raise RefusedFacts("source_root_missing", rel, {"path": rel}) from None
    if stat.S_ISLNK(info.st_mode):
        raise RefusedFacts("source_root_symlink", rel, {"path": rel})
    if not stat.S_ISDIR(info.st_mode):
        raise RefusedFacts("source_root_not_directory", rel, {"path": rel})


def classify(srv) -> dict:
    """lstat/scandir only: every top, container and stable root is a real directory; every entry of a container is listed."""
    srv = Path(srv)
    for rel in (*FILE_ROOTS, *CONTAINERS, *(rel for _id, rel in STABLE_ROOTS)):
        _lstat_dir(srv, rel)
    known = set(CONTAINERS) | {rel for _id, rel in STABLE_ROOTS}
    volatile, excluded = {"/".join(_rel_parts(p)) for p in VOLATILE_PATHS}, {"/".join(_rel_parts(p)) for p in EXCLUDED_PATHS}
    stable_files, volatile_present, excluded_present, unclassified = [], [], [], []
    for container in CONTAINERS:
        with os.scandir(srv / container) as entries:
            listing = sorted(entries, key=lambda e: e.name)
        for entry in listing:
            rel = f"{container}/{entry.name}"
            if rel in known:
                continue
            if rel in volatile:
                volatile_present.append(rel)
            elif rel in excluded:
                excluded_present.append(rel)
            elif container in STABLE_FILE_DIRS and stat.S_ISREG(entry.stat(follow_symlinks=False).st_mode):
                stable_files.append(rel)
            else:
                unclassified.append(rel)
    if unclassified:
        raise RefusedFacts("partition_unclassified", f"{len(unclassified)} unclassified entr(ies)",
                           {"count": len(unclassified), "paths": _named(unclassified)})
    return {"containers": list(CONTAINERS), "stable_roots": [rel for _id, rel in STABLE_ROOTS],
            "stable_files": sorted(stable_files), "volatile_present": sorted(volatile_present),
            "excluded": sorted(excluded_present)}


def survey(srv, roots=FILE_ROOTS, excluded=EXCLUDED_PATHS) -> dict:
    """One lstat pass over the tops: `files` (like `snapshot.scan_tree`: every non-directory entry -> (mtime_ns, size)),
    `dirs` (relative names) and `links` (relative path -> readlink text, never resolved). Excluded subtrees are pruned."""
    srv = Path(srv)
    excl = [_rel_parts(e) for e in excluded]
    files, dirs, links = {}, [], {}
    pending = [srv / r for r in roots]
    while pending:
        directory = pending.pop()
        try:
            entries = list(os.scandir(directory))
        except FileNotFoundError:
            continue
        for entry in entries:
            rel = Path(entry.path).relative_to(srv).as_posix()
            if any(tuple(rel.split("/"))[: len(e)] == e for e in excl):
                continue
            info = entry.stat(follow_symlinks=False)
            if stat.S_ISDIR(info.st_mode):
                dirs.append(rel)
                pending.append(Path(entry.path))
            else:
                files[rel] = (info.st_mtime_ns, info.st_size)
                if stat.S_ISLNK(info.st_mode):
                    links[rel] = os.readlink(entry.path)
    return {"files": files, "dirs": sorted(dirs), "links": links}


def _secret_name(rel: str) -> bool:
    parts = [p.lower() for p in rel.split("/")]
    base = parts[-1]
    return (any(p in SECRET_COMPONENTS for p in parts) or base in SECRET_BASENAMES
            or any(fnmatch.fnmatchcase(base, g) for g in SECRET_BASENAME_GLOBS)
            or base.startswith(SECRET_BASENAME_PREFIXES))


def secret_names(scan_paths) -> list:
    """Refuse a secret or credential NAME anywhere in the given relative paths (files and directories); names only."""
    hits = sorted(p for p in scan_paths if _secret_name(p))
    if hits:
        raise RefusedFacts("secret_path_in_root", f"{len(hits)} secret-like name(s)",
                           {"count": len(hits), "paths": _named(hits)})
    return []


def _escapes(link_rel: str, target: str) -> bool:
    """True when the target is absolute or, normalised lexically from the link's directory, leaves the link's top."""
    if target.startswith("/"):
        return True
    joined = os.path.normpath(os.path.join(os.path.dirname(link_rel), target))
    top = link_rel.split("/")[0]
    return not (joined == top or joined.startswith(top + "/"))


def _allowed(link_rel: str, target: str) -> bool:
    roots = dict(STABLE_ROOTS)
    for rule in SYMLINK_ALLOWANCE:
        root = roots[rule["root"]]
        if _inside(link_rel, root) and link_rel != root and target == rule["target"] \
                and re.fullmatch(rule["path"], link_rel[len(root) + 1:]):
            return True
    return False


def symlink_facts(srv, found: dict | None = None) -> dict:
    """Every symlink under the four tops (lstat + readlink, targets never resolved); absolute or escaping ones must match
    a SYMLINK_ALLOWANCE rule (root id, relative-path regex and literal target)."""
    links = (found if found is not None else survey(srv))["links"]
    allowed = sorted(rel for rel, target in links.items() if _escapes(rel, target) and _allowed(rel, target))
    bad = sorted(rel for rel, target in links.items() if _escapes(rel, target) and not _allowed(rel, target))
    if bad:
        raise RefusedFacts("external_symlink_unallowed", f"{len(bad)} unallowed link(s)",
                           {"count": len(bad), "paths": _named(bad)})
    return {"total": len(links), "allowed": len(allowed), "allowed_paths": _named(allowed)}


def git_locks(srv, found: dict | None = None) -> list:
    """`*.lock` entries below a `.git` directory under `repo` or `worktrees` (a `.git` FILE is a pointer, not a lock)."""
    scan = found if found is not None else survey(srv)
    names = [r for r in scan["files"] if r.split("/")[0] in ("repo", "worktrees")
             and ".git" in r.split("/")[1:-1] and r.endswith(".lock")]
    if names:
        raise RefusedFacts("git_lock_present", f"{len(names)} git lock file(s)", {"count": len(names), "paths": _named(names)})
    return []


def cp_identity() -> dict:
    """`CP` is a real (unlinked) executable regular file whose `--version` first line names GNU coreutils cp."""
    if os.path.realpath(CP) != CP:
        raise Refused("cp_identity", "CP is not its own real path")
    info = os.lstat(CP)
    if not stat.S_ISREG(info.st_mode) or not os.access(CP, os.X_OK):
        raise Refused("cp_identity", "CP is not an executable regular file")
    done = subprocess.run([CP, "--version"], capture_output=True, text=True, timeout=10, env=dict(CP_ENV), check=False)
    first = (done.stdout.splitlines() or [""])[0]
    if done.returncode != 0 or not first.startswith(CP_VERSION_PREFIX):
        raise Refused("cp_identity", "CP --version is not GNU coreutils cp")
    with open(CP, "rb") as handle:
        digest = hashlib.sha256(handle.read()).hexdigest()
    return {"path": CP, "sha256": digest, "version": first}


def load_aibox_data(repo) -> dict:
    """Import `aibox_data` and the kernel ids in-process from the tooling checkout `repo` (appended to sys.path, so an
    earlier foreign package wins and is caught by the origin check) and return sha256 per file of the fixed set."""
    repo = Path(repo).resolve()
    for sub in ("scripts", "src"):
        if str(repo / sub) not in sys.path:
            sys.path.append(str(repo / sub))
    import importlib

    for package, modules in AIBOX_MODULES:
        for name in (package, *modules):
            try:
                module = importlib.import_module(name)
            except ImportError as error:
                raise Refused("aibox_data_origin_foreign", f"{name} cannot be imported from the checkout: {error}") from None
            origin = getattr(getattr(module, "__spec__", None), "origin", None)
            if not origin or not Path(os.path.realpath(origin)).is_relative_to(repo):
                raise Refused("aibox_data_origin_foreign", f"{name} does not come from the tooling checkout")
    return {rel: hashlib.sha256((repo / rel).read_bytes()).hexdigest() for rel in AIBOX_FILES}


def _bounded(items: list) -> list:
    return items[:64]


def run_check(srv, repo=None) -> dict:
    """The check's facts, in the contracted order; raises `Refused` (a `RefusedFacts` carries facts) on the first failure."""
    started = time.monotonic()
    repo = Path(repo) if repo is not None else Path(__file__).resolve().parents[2]
    facts: dict = {}
    facts["cp"] = cp_identity()
    partition = classify(srv)
    facts["partition"] = {"containers": len(partition["containers"]), "stable_roots": len(partition["stable_roots"]),
                          "volatile_present": _bounded(partition["volatile_present"]),
                          "excluded": partition["excluded"]}
    found = survey(srv)
    secret_names([*found["files"], *found["dirs"]])
    facts["symlinks"] = symlink_facts(srv, found)
    git_locks(srv, found)
    roots = {}
    for root_id, rel in STABLE_ROOTS:
        mine = [(path, v) for path, v in found["files"].items() if _inside(path, rel)]
        roots[root_id] = {"files": len(mine), "bytes": sum(v[1] for _p, v in mine),
                          "symlinks": sum(1 for path, _v in mine if path in found["links"])}
    facts["stable_roots"] = roots
    facts["stable_files"] = {"count": len(partition["stable_files"]), "paths": _bounded(partition["stable_files"])}
    facts["aibox_data"] = load_aibox_data(repo)
    facts["elapsed_s"] = round(time.monotonic() - started, 3)
    facts["peak_rss_kb"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return facts


def _record(srv: str, refused, facts: dict) -> dict:
    return {"schema": SCHEMA, "srv": str(srv), "ok": refused is None, "refused": refused, "facts": facts}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="rehearsal.fileroots", exit_on_error=False)
    sub = parser.add_subparsers(dest="verb", required=True)
    check = sub.add_parser("check", exit_on_error=False)
    check.add_argument("--srv", default=SRV)
    check.add_argument("--out", required=True)
    try:
        args = parser.parse_args(argv)
    except argparse.ArgumentError:
        return 2
    except SystemExit as stop:  # argparse's own usage exit (2) or --help (0)
        return int(stop.code or 0)
    from .evidence import check_facts

    refused, facts = None, {}
    try:
        facts = run_check(args.srv)
    except Refused as error:
        refused, facts = error.code, {"detail": _redact(error.detail), **getattr(error, "facts", {})}
    record = _record(args.srv, refused, facts)
    check_facts(record["facts"])
    try:
        fd = os.open(args.out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except OSError as error:
        print(f"usage: --out is not creatable: {error.strerror}", file=sys.stderr)
        return 2
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(record, handle, indent=1, sort_keys=True)
        handle.write("\n")
    return 0 if refused is None else 1


if __name__ == "__main__":
    raise SystemExit(main())
