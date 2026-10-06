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
    partition_static          the partition constants are inconsistent (raised at import by `static_checks`)
    secret_path_in_root       a secret or credential NAME exists somewhere in the four tops
    external_symlink_unallowed  an absolute or escaping symlink matches no SYMLINK_ALLOWANCE rule
    git_lock_present          a `*.lock` file under a `.git` directory of `repo` or `worktrees`
    cp_identity               `CP` is not the pinned GNU cp
    aibox_data_origin_foreign aibox_data / codex_harness would be imported from outside the tooling checkout

Run: `cd compare && /usr/bin/python3 -B -m rehearsal.fileroots check [--srv PATH] --out FILE` (exit 0 ok, 1 refusal, 2 usage).

ACQUISITION (RH-2 P5b-1, E9 Phase P step P5): `acquire(host, srv, seal, run8)` copies the four file roots into `seal` and
`verify_seal(seal, p5, run8)` re-proves a finished seal. Both are guard-free library functions (no Phase P edit here).

Seal layout (`seal` = ROOT/seal, every directory 0700, every meta file and volatile/single copy 0600):
    seal/tree/{runtime,managed-fleet,repo,worktrees}   minus runtime/tokobs; the stable roots are `gnucp -a -T` copies
    seal/meta/<id>.manifest.json x8, <id>.verify.json x8, single.json, scan-after.tsv, complete.json (written LAST)
Validity rule: a ROOT without a passing `verify_seal` and Phase P verdict `ok` is INVALID and is kept for diagnosis (the
owner deletes it per the rehearsal disposal rule; it stays 0700). Accepted residual (D14): a secret-named file created in
a stable root after its lstat walk and manifest but before its cp is content-copied by cp, then STOPs (the staged lstat
walk re-applies the secret-name check, so the reason is `secret_path_in_root`).

Time (D11): `DEADLINE_S` from the start of `acquire`, checked before each root's re-check and before each cp; one cp has
`CP_TIMEOUT_S`. The verify after the last admitted cp is outside the deadline; the phase's RuntimeMaxSec is the backstop.

Every refusal leaving `acquire` is a `RefusedFacts` (D17: detail <= 512 chars with no absolute path, facts pass
`check_facts`) with one of these codes (`<id>` is a STABLE_ROOTS id):
    bad_run8, seal_overlaps_source, aibox_data_origin_foreign, cp_identity (see above), source_root_missing,
    source_root_symlink, source_root_not_directory, partition_unclassified, secret_path_in_root, external_symlink_unallowed,
    git_lock_present, seal_exists, seal_write_failed, source_entry_vanished, source_access_denied, stable_file_changed,
    deadline_exceeded, scan_after_inconsistent, evidence_unbounded,
    inventory_<id>_vanished, inventory_<id>_blocking, inventory_<id>_external_symlink,
    cp_<id>_exit_<n>, cp_<id>_spawn_failed,
    verify_<id>_mismatch, verify_<id>_mtime, verify_<id>_dirs, verify_<id>_mode, verify_<id>_links,
    and the snapshot codes passed through (re-rendered): volatile_undeclared (facts: count, paths), volatile_symlink,
    volatile_not_regular, volatile_unreadable, volatile_excluded, volatile_path_bad.
`subprocess.TimeoutExpired` (a cp over CP_TIMEOUT_S) and `KeyboardInterrupt` propagate; the umask is always restored.
Any other OSError reading the source maps to `source_access_denied`; writing under the seal to `seal_write_failed`.
"""

from __future__ import annotations

import argparse
import contextlib
import fnmatch
import hashlib
import importlib
import json
import os
import re
import resource
import stat
import subprocess
import sys
import time
from pathlib import Path

from . import Refused, check_run8, snapshot
from .evidence import check_facts
from .snapshot import (
    EXCLUDED_PATHS,
    VOLATILE_PATHS,
    _covered,
    _read_once,
    _rel_parts,
    copy_once,
    scan_tree,
    stable_sha256,
)

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
SINGLE_SCHEMA = "zeus:aibox-migration-001:rehearsal:p5-single:1"
COMPLETE_SCHEMA = "zeus:aibox-migration-001:rehearsal:p5-complete:1"
DEADLINE_S = 2700  # D11: from the start of `acquire`
CP_TIMEOUT_S = 1800  # D11: one cp
DETAIL_LIMIT = 512
LISTED_PATHS = 64  # redacted paths per category in a verify record
PATH_LIMIT = 160  # characters of one rendered path fact
LISTED = 16  # names listed in a refusal or a fact; the count is always exact


class RefusedFacts(Refused):
    """A `Refused` that also carries bounded, name-only facts for the check record."""

    def __init__(self, code: str, detail: str = "", facts: dict | None = None):
        super().__init__(code, detail)
        self.facts = facts or {}


def _redact(rel: str) -> str:
    """A path as a bounded fact: every component the secret-name policy recognizes becomes `<redacted>`, and the rendered
    string is cut at PATH_LIMIT with a `…` marker (cut after redaction, so it discloses no hidden component)."""
    text = "/".join("<redacted>" if p.lower() in SECRET_COMPONENTS or _secret_basename(p) else p
                    for p in rel.split("/"))
    return text if len(text) <= PATH_LIMIT else text[: PATH_LIMIT - 1] + "…"


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
        raise RefusedFacts("source_root_missing", _redact(rel), {"path": _redact(rel)}) from None
    if stat.S_ISLNK(info.st_mode):
        raise RefusedFacts("source_root_symlink", _redact(rel), {"path": _redact(rel)})
    if not stat.S_ISDIR(info.st_mode):
        raise RefusedFacts("source_root_not_directory", _redact(rel), {"path": _redact(rel)})


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
    return any(p in SECRET_COMPONENTS for p in parts) or _secret_basename(parts[-1])


def _secret_basename(base: str) -> bool:
    base = base.lower()
    return (base in SECRET_BASENAMES or any(fnmatch.fnmatchcase(base, g) for g in SECRET_BASENAME_GLOBS)
            or base.startswith(SECRET_BASENAME_PREFIXES))


def secret_names(scan_paths, where: str | None = None) -> list:
    """Refuse a secret or credential NAME anywhere in the given relative paths (files and directories); names only.
    `where` (optional) names the acquisition step that applied the check."""
    hits = sorted(p for p in scan_paths if _secret_name(p))
    if hits:
        raise RefusedFacts("secret_path_in_root", f"{len(hits)} secret-like name(s)",
                           {"count": len(hits), "paths": _named(hits), **({"where": where} if where else {})})
    return []


def _escapes(link_rel: str, target: str) -> bool:
    """True when the target is absolute or, normalised lexically from the link's directory, leaves the STABLE ROOT that
    contains the link (D8; as `aibox_data.inventory` judges it: relative to the scanned root). A link inside no stable
    root escapes, so the second `check` predicts P5's per-root refusal."""
    if target.startswith("/"):
        return True
    top = next((rel for _id, rel in STABLE_ROOTS if _inside(link_rel, rel) and link_rel != rel), None)
    if top is None:
        return True
    joined = os.path.normpath(os.path.join(os.path.dirname(link_rel), target))
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


def _git_lock_name(rel: str) -> bool:
    return rel.split("/")[0] in ("repo", "worktrees") and ".git" in rel.split("/")[1:-1] and rel.endswith(".lock")


def git_locks(srv, found: dict | None = None) -> list:
    """`*.lock` entries below a `.git` directory under `repo` or `worktrees` (a `.git` FILE is a pointer, not a lock)."""
    scan = found if found is not None else survey(srv)
    names = [r for r in scan["files"] if _git_lock_name(r)]
    if names:
        raise RefusedFacts("git_lock_present", f"{len(names)} git lock file(s)", {"count": len(names), "paths": _named(names)})
    return []


def cp_identity() -> dict:
    """`CP` is a real (unlinked) executable regular file whose `--version` first line names GNU coreutils cp. Every
    expected probe failure (missing, spawn error, timeout, undecodable output) is one sanitized `Refused("cp_identity")`."""
    try:
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
    except (OSError, subprocess.SubprocessError, UnicodeError, ValueError):
        raise Refused("cp_identity", "the CP probe failed") from None
    return {"path": CP, "sha256": digest, "version": _redact(first)}


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


def run_check(srv, repo=None) -> dict:
    """The check's facts, in the contracted order; raises `Refused` (a `RefusedFacts` carries facts) on the first failure."""
    started = time.monotonic()
    repo = Path(repo) if repo is not None else Path(__file__).resolve().parents[2]
    facts: dict = {}
    facts["cp"] = cp_identity()
    partition = classify(srv)
    facts["partition"] = {"containers": len(partition["containers"]), "stable_roots": len(partition["stable_roots"]),
                          "volatile_present": _named(partition["volatile_present"]),
                          "excluded": _named(partition["excluded"])}
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
    facts["stable_files"] = {"count": len(partition["stable_files"]), "paths": _named(partition["stable_files"])}
    facts["aibox_data"] = load_aibox_data(repo)
    facts["elapsed_s"] = round(time.monotonic() - started, 3)
    facts["peak_rss_kb"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return facts


# ---- acquisition (P5b-1) ----

_ABSOLUTE = re.compile(r"(?<![\w.<>\-])/[^\s'\"]*")


def _scrub(text: str) -> str:
    """A refusal detail as a bounded fact (D17): secret components redacted, any absolute path replaced."""
    return _redact(_ABSOLUTE.sub("<path>", str(text)))[:DETAIL_LIMIT]


def _rerender(error: Refused) -> RefusedFacts:
    facts = dict(getattr(error, "facts", None) or {})
    detail, paths = error.detail, getattr(error, "paths", None)
    if error.code == "volatile_undeclared" and paths is not None:
        detail = f"{len(paths)} path(s) changed outside the closed list"
        facts.update(count=len(paths), paths=_named(paths))
    return RefusedFacts(error.code, _scrub(detail), facts)


@contextlib.contextmanager
def _source(vanished: str = "source_entry_vanished"):
    """OSError while reading the source -> a named refusal (a file or directory that disappears is `vanished`)."""
    try:
        yield
    except FileNotFoundError:
        raise RefusedFacts(vanished) from None
    except OSError:
        raise RefusedFacts("source_access_denied") from None


@contextlib.contextmanager
def _seal_writes():
    try:
        yield
    except FileExistsError:
        raise RefusedFacts("seal_exists") from None
    except OSError:
        raise RefusedFacts("seal_write_failed") from None


def _lstat_walk(base: Path) -> dict:
    """lstat only, no content (D3): every entry name, the directory modes (the root is `""`, empty directories
    included), the regular-file modes and the hard-link groups (2+ non-directory paths sharing `(st_dev, st_ino)`)."""
    dirs = {"": stat.S_IMODE(os.lstat(base).st_mode)}
    files, names, inodes = {}, [], {}
    pending = [(base, "")]
    while pending:
        directory, prefix = pending.pop()
        with os.scandir(directory) as scanned:
            entries = list(scanned)
        for entry in entries:
            rel = prefix + entry.name
            info = entry.stat(follow_symlinks=False)
            names.append(rel)
            if stat.S_ISDIR(info.st_mode):
                dirs[rel] = stat.S_IMODE(info.st_mode)
                pending.append((Path(entry.path), rel + "/"))
                continue
            if stat.S_ISREG(info.st_mode):
                files[rel] = stat.S_IMODE(info.st_mode)
            inodes.setdefault((info.st_dev, info.st_ino), []).append(rel)
    return {"names": names, "dirs": dirs, "files": files,
            "groups": frozenset(frozenset(group) for group in inodes.values() if len(group) > 1)}


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _ancestors(rels) -> list[str]:
    found = set()
    for rel in rels:
        parts = rel.split("/")
        found.update("/".join(parts[:i]) for i in range(1, len(parts)))
    return sorted(found)


class _Acquisition:
    def __init__(self, host, srv: Path, seal: Path, run8: str, monotonic, repo: Path):
        self.host, self.srv, self.seal, self.run8, self.monotonic, self.repo = host, srv, seal, run8, monotonic, repo
        self.tree, self.meta = seal / "tree", seal / "meta"
        self.t0 = 0.0
        self.old_umask: int | None = None
        self.roots: dict = {}
        self.singles: list = []
        self.created_for: list = []

    # -- helpers
    def put(self, name: str, text: str) -> None:
        with _seal_writes():
            with self.host.open(self.meta / name, "x") as handle:
                handle.write(text)

    def put_json(self, name: str, document) -> None:
        self.put(name, json.dumps(document, sort_keys=True) + "\n")

    def disk_sha256(self, name: str) -> str:
        with _seal_writes(), self.host.open(self.meta / name, "rb") as handle:
            return _sha256_bytes(handle.read())

    def deadline(self) -> None:
        if self.monotonic() - self.t0 > DEADLINE_S:
            raise RefusedFacts("deadline_exceeded", f"more than {DEADLINE_S} s since the start")

    # -- the steps
    def run(self) -> dict:
        srv, seal = self.srv, self.seal
        self.t0 = self.monotonic()
        real_seal, real_srv = Path(os.path.realpath(seal.parent)), Path(os.path.realpath(srv))
        if real_seal == real_srv or real_seal.is_relative_to(real_srv) or real_srv.is_relative_to(real_seal):
            raise RefusedFacts("seal_overlaps_source", "the seal's parent and the source contain one another")
        tools = {"aibox_data": load_aibox_data(self.repo), "cp": cp_identity(),
                 "python_version": ".".join(str(n) for n in sys.version_info[:3])}
        try:
            self.inventory = importlib.import_module("aibox_data.inventory")
        except ImportError:
            raise RefusedFacts("aibox_data_origin_foreign", "aibox_data.inventory cannot be imported") from None
        self.old_umask = os.umask(0o077)
        with _source():
            partition = classify(srv)
            found = survey(srv)
        secret_names([*found["files"], *found["dirs"]], where="survey")
        symlinks = symlink_facts(srv, found)
        git_locks(srv, found)
        for path in (seal, self.tree, self.meta):
            with _seal_writes():
                os.mkdir(path, 0o700)
                os.chmod(path, 0o700)
        with _source():
            manifest = snapshot.snapshot_volatile(
                srv, self.tree, scan_roots=FILE_ROOTS, during=lambda: self.stage(partition),
                admit=lambda paths: secret_names(paths, where="volatile"))
        return self.finish(manifest, partition, symlinks, tools)

    def stage(self, partition: dict) -> None:
        srv = self.srv
        for rel in partition["stable_files"]:
            try:
                done = copy_once(srv / rel, self.tree / rel, label=rel)
            except Refused as error:
                if error.code == "volatile_unreadable":
                    raise RefusedFacts("source_access_denied", rel) from None
                if error.code.startswith("volatile_"):
                    raise RefusedFacts("stable_file_changed", rel) from None
                raise
            if done is None:
                raise RefusedFacts("stable_file_changed", rel)
            self.singles.append({"path": rel, **done})
        for root_id, rel in STABLE_ROOTS:
            self.stage_root(root_id, rel)

    def stage_root(self, root_id: str, rel: str) -> None:
        srv, inv = self.srv, self.inventory
        vanished = f"inventory_{root_id}_vanished"
        self.deadline()
        _lstat_dir(srv, rel)
        with _source(vanished):
            source_walk = _lstat_walk(srv / rel)
        secret_names([f"{rel}/{n}" for n in source_walk["names"]], where=f"inventory:{root_id}")
        try:
            manifest = inv.build_manifest("rh-" + self.run8, {root_id: str(srv / rel)}, "rehearsal")
        except (ValueError, FileNotFoundError):
            raise RefusedFacts(vanished) from None
        except OSError:
            raise RefusedFacts(f"inventory_{root_id}_blocking") from None
        root = manifest["roots"][root_id]
        entries = root["entries"]
        secret_names([f"{rel}/{e['path']}" for e in entries] + [f"{rel}/{u['path']}" for u in root["unreadable"]],
                     where=f"inventory:{root_id}")
        self.put_json(f"{root_id}.manifest.json", manifest)
        blocking = inv.blocking_findings(root)
        if blocking["source_unreadable"] or blocking["special_files"]:
            raise RefusedFacts(f"inventory_{root_id}_blocking", "",
                               {"unreadable": len(blocking["source_unreadable"]),
                                "special": len(blocking["special_files"])})
        allowed = sorted(e["path"] for e in entries if e.get("escapes_root"))
        for entry in entries:
            if entry.get("escapes_root") and not _allowed(f"{rel}/{entry['path']}", entry["link_target"]):
                raise RefusedFacts(f"inventory_{root_id}_external_symlink", "",
                                   {"count": len(allowed), "paths": _named([entry["path"]])})
        locks = [e["path"] for e in entries if _git_lock_name(f"{rel}/{e['path']}")]
        if locks:
            raise RefusedFacts("git_lock_present", "", {"count": len(locks), "paths": _named(locks)})
        dst = self.tree / rel
        if os.path.lexists(dst):
            raise RefusedFacts("seal_exists", "a staged root already exists")
        with _seal_writes():
            os.makedirs(dst.parent, 0o700, exist_ok=True)
        self.deadline()
        try:
            done = self.host.run([CP, "-a", "-T", "--", str(srv / rel), str(dst)], timeout=CP_TIMEOUT_S)
        except OSError:
            raise RefusedFacts(f"cp_{root_id}_spawn_failed") from None
        if done.returncode != 0:
            raise RefusedFacts(f"cp_{root_id}_exit_{done.returncode}", "",
                               {"exit": done.returncode, "stderr_lines": len((done.stderr or "").splitlines())})
        try:
            if not stat.S_ISDIR(os.lstat(dst).st_mode):
                raise RefusedFacts(f"verify_{root_id}_dirs", "the staged root is not a real directory")
        except FileNotFoundError:
            raise RefusedFacts(f"verify_{root_id}_dirs", "the staged root is missing") from None
        except OSError:
            raise RefusedFacts(f"verify_{root_id}_mismatch") from None
        if not inv.verify_manifest_digest(manifest):
            raise RefusedFacts(f"verify_{root_id}_mismatch", "the manifest digest does not verify")
        try:
            staged = inv.scan_root(dst)
            staged_walk = _lstat_walk(dst)
        except (OSError, ValueError):
            raise RefusedFacts(f"verify_{root_id}_mismatch", "the staged tree cannot be read") from None
        secret_names([f"{rel}/{n}" for n in staged_walk["names"]], where=f"staged:{root_id}")
        compared = inv.compare_roots(root, staged)
        want = {e["path"]: e["mtime_ns"] for e in entries if e["kind"] == "file"}
        have = {e["path"]: e["mtime_ns"] for e in staged["entries"] if e["kind"] == "file"}
        mtime_bad = sorted(p for p in want.keys() & have.keys() if want[p] != have[p])
        counts = {"missing": len(compared["missing"]), "extra": len(compared["extra"]),
                  "mismatched": len(compared["mismatched"]), "unreadable": len(compared["unreadable"]),
                  "mtime_mismatch": len(mtime_bad)}
        listed = {"missing": compared["missing"], "extra": compared["extra"], "mismatched": compared["mismatched"],
                  "unreadable": compared["unreadable"], "mtime_mismatch": mtime_bad}
        self.put_json(f"{root_id}.verify.json", {
            "root": root_id, "counts": counts,
            "paths": {k: [_redact(p) for p in sorted(v)[:LISTED_PATHS]] for k, v in listed.items()}})
        if (compared["missing"] or compared["extra"] or compared["mismatched"] or compared["unreadable"]
                or sorted(compared["external_symlinks"]) != allowed):
            raise RefusedFacts(f"verify_{root_id}_mismatch", "", counts)
        if mtime_bad:
            raise RefusedFacts(f"verify_{root_id}_mtime", "", counts)
        if source_walk["dirs"].keys() != staged_walk["dirs"].keys():
            raise RefusedFacts(f"verify_{root_id}_dirs", "", counts)
        if source_walk["dirs"] != staged_walk["dirs"] or source_walk["files"] != staged_walk["files"]:
            raise RefusedFacts(f"verify_{root_id}_mode", "", counts)
        if source_walk["groups"] != staged_walk["groups"]:
            raise RefusedFacts(f"verify_{root_id}_links", "", counts)
        files = [e for e in entries if e["kind"] == "file"]
        self.roots[root_id] = {
            "files": len(files), "bytes": sum(e["bytes"] for e in files), "entries": len(entries),
            "symlinks": sum(1 for e in entries if e["kind"] == "symlink"), "external_allowed": len(allowed),
            "manifest_digest": manifest["digest"], "cp_exit": done.returncode, "dirs": len(source_walk["dirs"]),
            "modes_compared": len(source_walk["dirs"]) + len(source_walk["files"]),
            "link_groups": len(source_walk["groups"]), "verify": counts, "ok": True}

    def finish(self, manifest: dict, partition: dict, symlinks: dict, tools: dict) -> dict:
        srv = self.srv
        for entry in self.singles:
            try:
                got = _read_once(srv / entry["path"], entry["path"])
            except Refused as error:
                raise RefusedFacts("source_access_denied" if error.code == "volatile_unreadable"
                                   else "stable_file_changed", entry["path"]) from None
            if got is None or _sha256_bytes(got[0]) != entry["sha256"]:
                raise RefusedFacts("stable_file_changed", entry["path"])
        with _source():
            after = scan_tree(srv, FILE_ROOTS)
        secret_names(list(after), where="scan_after")
        self.put("scan-after.tsv", "".join(f"{json.dumps(rel)}\t{m}\t{n}\n" for rel, (m, n) in sorted(after.items())))
        stable = manifest["stable"]
        single_paths = {e["path"] for e in self.singles}
        stable_tops = [rel for _id, rel in STABLE_ROOTS]
        if stable_sha256(after) != stable["sha256_after"] or not all(
                any(_inside(rel, top) for top in stable_tops) or _covered(rel, VOLATILE_PATHS)
                or _covered(rel, EXCLUDED_PATHS) or rel in single_paths for rel in after):
            raise RefusedFacts("scan_after_inconsistent")
        copied = [e["path"] for e in manifest["files"]] + sorted(single_paths) + stable_tops
        dirs = {}
        with _source():
            for rel in _ancestors(copied):
                info = os.lstat(srv / rel)
                dirs[rel] = {"mode": stat.S_IMODE(info.st_mode), "mtime_ns": info.st_mtime_ns}
        self.put_json("single.json", {"schema": SINGLE_SCHEMA, "volatile": manifest["files"], "stable": self.singles,
                                      "skipped": manifest["skipped"], "skew_ns": manifest["skew_ns"], "dirs": dirs})
        names = sorted([f"{i}.manifest.json" for i, _r in STABLE_ROOTS] + [f"{i}.verify.json" for i, _r in STABLE_ROOTS]
                       + ["single.json", "scan-after.tsv"])
        files = {name: self.disk_sha256(name) for name in names}
        self.put_json("complete.json", {"schema": COMPLETE_SCHEMA, "run8": self.run8, "files": files})
        complete_sha = self.disk_sha256("complete.json")
        for root_id, _rel in STABLE_ROOTS:
            self.roots[root_id]["manifest_sha256"] = files[f"{root_id}.manifest.json"]
            self.roots[root_id]["verify_sha256"] = files[f"{root_id}.verify.json"]
        facts = {
            "input_kind": "observed" if str(srv) == SRV else "synthetic",
            "partition": {"containers": len(partition["containers"]), "stable_roots": len(partition["stable_roots"]),
                          "volatile_present": _named(partition["volatile_present"]),
                          "excluded": _named(partition["excluded"])},
            "stable_files": {"count": len(partition["stable_files"]), "paths": _named(partition["stable_files"])},
            "symlinks": symlinks, "roots": self.roots,
            "single": {"volatile": len(manifest["files"]), "stable": len(self.singles),
                       "skipped": len(manifest["skipped"]), "dirs": len(dirs)},
            "stable": stable, "scan_after_sha256": files["scan-after.tsv"], "complete_sha256": complete_sha,
            "volatile_read_span_ns": manifest["skew_ns"], "tool": tools,
            "elapsed_s": round(self.monotonic() - self.t0, 3),
            "peak_rss_kb": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}
        try:
            check_facts(facts)
        except Refused as error:
            raise RefusedFacts("evidence_unbounded", error.code, {"rule": error.code}) from None
        facts["ok"] = True
        return facts


def acquire(host, srv, seal, run8, *, monotonic=time.monotonic, repo=None) -> dict:
    """Copy the four file roots from `srv` into `seal` (ROOT/seal), verified and sealed last by `meta/complete.json`
    (E9 Phase P step P5; see the module docstring for the layout, the closed reason list and the bounds).

    `host` offers `run(argv, *, timeout)` and `open(path, mode)` (phase_p.Host's interface). Raises only `RefusedFacts`,
    plus `subprocess.TimeoutExpired` and `KeyboardInterrupt`; the umask is always restored. Returns the bounded facts
    with `ok: True` set only after they pass `check_facts`."""
    repo = Path(repo) if repo is not None else Path(__file__).resolve().parents[2]
    run = _Acquisition(host, Path(srv), Path(seal), run8, monotonic, repo)
    try:
        check_run8(run8)
        return run.run()
    except Refused as error:
        raise _rerender(error) from None
    finally:
        if run.old_umask is not None:
            os.umask(run.old_umask)


def verify_seal(seal, p5: dict, run8: str) -> dict:
    """Re-prove a finished seal from `seal/meta` alone: `complete.json` is a regular file with this schema and run8, its
    names equal the other regular files of `meta` (and `meta` holds nothing else), every sha256 matches, and the Phase P
    facts `p5` carry that complete.json's digest and `ok: True`. Refuses `Refused("seal_invalid", <rule>)`."""
    meta = Path(seal) / "meta"

    def bad(rule: str):
        return Refused("seal_invalid", rule)

    def read(path: Path) -> bytes:
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        except OSError:
            raise bad("meta_unreadable") from None
        with os.fdopen(fd, "rb") as handle:
            return handle.read()

    try:
        if any(not stat.S_ISDIR(os.lstat(p).st_mode) for p in (Path(seal), meta)):
            raise bad("meta_missing")
        listing = {entry.name: entry.stat(follow_symlinks=False) for entry in os.scandir(meta)}
    except OSError:
        raise bad("meta_missing") from None
    info = listing.get("complete.json")
    if info is None or not stat.S_ISREG(info.st_mode):
        raise bad("complete_missing")
    body = read(meta / "complete.json")
    try:
        document = json.loads(body)
    except ValueError:
        raise bad("complete_not_json") from None
    if not isinstance(document, dict) or document.get("schema") != COMPLETE_SCHEMA:
        raise bad("complete_schema")
    if document.get("run8") != run8:
        raise bad("complete_run8")
    files = document.get("files")
    if not isinstance(files, dict) or not all(isinstance(v, str) for v in files.values()):
        raise bad("complete_files")
    if any(not stat.S_ISREG(i.st_mode) for i in listing.values()):
        raise bad("meta_not_regular")
    if set(files) != set(listing) - {"complete.json"}:
        raise bad("meta_names")
    for name in sorted(files):
        if _sha256_bytes(read(meta / name)) != files[name]:
            raise bad("sha256_mismatch")
    if not isinstance(p5, dict) or p5.get("complete_sha256") != _sha256_bytes(body):
        raise bad("complete_sha256_mismatch")
    if p5.get("ok") is not True:
        raise bad("p5_not_ok")
    return {"files": len(files), "complete_sha256": _sha256_bytes(body)}


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

    out = Path(args.out)
    out_dir, srv_real = Path(os.path.realpath(out.parent)), Path(os.path.realpath(args.srv))
    if out_dir == srv_real or out_dir.is_relative_to(srv_real):
        print("usage: --out lies within --srv; the check never writes into its source", file=sys.stderr)
        return 2
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
