"""Shared S8 research-program doubles and builders (DESIGN-s8 §1 V5, the research program bullet; TRACE-s8 §2): the
LABELLED test doubles of M7 `tests/test_research_program.py`, `tests/test_research_program_fixtures.py` and
`tests/test_research_investigations.py`, for the `research.program_tick` and `research.capture` families (the other
research-program families come in the next pilots).

Layer: harness (never shipped). This module never imports `codex_harness`: everything from the product arrives through
`api`, the object a reference (later a target) driver builds. Nothing here is an actual Codex, GitHub or production
verification, and nothing here touches a network or a provider (RESEARCH-S8 R2): the feeds return RECORDED bodies.

**Doubles** (each class docstring names the M7 double it mirrors; every injected fault is labelled where it is made):

- `Workspace`: M7's `tmp_path`, one fresh directory per case under one temporary root, a private `tempfile.tempdir`
  (so the capture's owned temporary directory can be counted), and `scrub`, which turns that root into `<root>` in
  every reported value (a projection, not a mask: the golden never holds a machine path).
- `Clock`: M7 `Clock` (a settable ISO string); `step` is the labelled extension that advances the time by that many
  seconds after every read, so `run` can complete several ticks without a scenario step between them.
- `Sources`: M7 `FakeSources`: the recorded feeds, `outages`, `paused` (the pressure evaluator's hold) and
  `github_detail`.
- `Budget`: M7 `FakeBudget`; `fail` is the labelled raise of an unreadable machine ledger.
- `Council`: M7 `FakeCouncil` (validates the persisted manifest with the real validator and writes the scripted
  `autonomous_runs` row; `status` None writes no row and raises before any claim; `raise_after_row` raises after the
  row), plus M7 `MismatchedCouncil` (`sha`) and the labelled `silent` (no row, no raise).
- `FlakyStore`: M7 `FlakyStore` (the store becomes unavailable on demand). `ShiftingSource`: a labelled wrapper whose
  `blob` answers differently after the first read of a path (the time-of-check/time-of-use gap in `_capture`).
- the repository: a REAL temporary Git repository built under the pinned `GIT_*` identity, dates and empty
  configuration files (`repository`), with M7's dirty untracked file and edited goal.

**Builders**: `config`/`template` (M7), `build`/`registered` (M7), `portfolio` (M7 investigations), plus the
observation helpers `call`, `guarded`, `snapshot`, `git_snapshot`, `checkout`, `events` and `files`.

`api` supplies: `MemoryStore`, `ResearchProgram`, `ProgramRunner`, `GitCapture`, `GitSource`, `CaptureError`,
`FileArtifacts`, `ContractError`, `ProgramRefused`, `DiscoveryPaused`, `POLICY`, `validate_config`,
`validate_any_manifest`, `manifest_digest`, the bucket names (`BUCKET_PROGRAMS`, `BUCKET_CANDIDATES`, `BUCKET_CYCLES`, `BUCKET_DISPATCHES`, `RUNS`,
`BUCKET_INVESTIGATIONS`, `BUCKET_JOBS`), `Portfolio`, `family_id`, and `patch(name, value)` (a context manager that
replaces one name of the research-program adapter module: the labelled fault seam).
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

CANARY = "CANARY-must-never-be-emitted"
NOTE = b"# local residual\nPG store serializes writers with one advisory lock.\n"
GOAL = b"# goal\n"
BASE_CLOCK = "2028-01-01T00:00:00+00:00"
PROGRAM = "rp-001"
INTENT = "proactive"
CAPTURE_PATH = "docs/zeus/research-captures/rp-001/001.json"
CAPTURE_REF = "refs/zeus/research/rp-001/001"
# LABELLED fixture identities of a repository root. M7's tests use `repository_identity(root)`, a digest of the resolved
# path; that path is a per-run temporary directory, so the golden uses a digest of a fixed label instead (the mismatch
# between two identities is what the cases observe, not the digest of a path).
IDENTITY = hashlib.sha256(b"s8-fixture-repository-identity").hexdigest()
OTHER_IDENTITY = hashlib.sha256(b"s8-fixture-other-repository-identity").hexdigest()
GIT_FIXED = {"GIT_AUTHOR_NAME": "Fixture", "GIT_AUTHOR_EMAIL": "fixture@localhost",
             "GIT_COMMITTER_NAME": "Fixture", "GIT_COMMITTER_EMAIL": "fixture@localhost",
             "GIT_AUTHOR_DATE": "2026-01-01T00:00:00+00:00", "GIT_COMMITTER_DATE": "2026-01-01T00:00:00+00:00",
             "GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0"}
REDIRECTING = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY", "GIT_COMMON_DIR")
BUCKET_LIST = ("research_programs", "research_program_candidates", "research_program_cycles",
               "research_investigation_dispatches", "autonomous_runs", "portfolio_investigations", "fleet_jobs")


def canonical_digest(value) -> str:
    text = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ---- the pinned git environment and the workspace ------------------------------------------------------------------
def pin_git(base: Path) -> None:
    """Pin the driver process's own environment (the capture's child inherits it): the `GIT_FIXED` identity and dates,
    empty git configuration files in place of the host's, and no redirecting variable (the T-ENV-1 case plants one
    itself and restores it)."""
    empty = base / "empty-gitconfig"
    empty.write_text("", encoding="utf-8")
    os.chmod(empty, 0o644)
    os.environ.update(GIT_FIXED)
    os.environ.update({"GIT_CONFIG_GLOBAL": str(empty), "GIT_CONFIG_SYSTEM": str(empty)})
    for name in REDIRECTING:
        os.environ.pop(name, None)


def git_env() -> dict:
    """The environment of THIS module's own git calls: the process environment without a redirecting variable, so a
    planted `GIT_DIR` never redirects the observation of what the product did."""
    return {k: v for k, v in os.environ.items() if k not in REDIRECTING}


def git(root, *argv, check=True, text=True, input_text=None):
    done = subprocess.run(["git", "-c", "commit.gpgsign=false", "-C", str(root), *argv], env=git_env(),
                          capture_output=True, text=text, input=input_text, timeout=120)
    if check and done.returncode:
        raise AssertionError("fixture git failed: " + " ".join(argv) + ": " + str(done.stderr)[-300:])
    return done


def out(root, *argv) -> str:
    return git(root, *argv).stdout.strip()


class Workspace:
    """LABELLED. M7's `tmp_path`: one temporary root, a fresh directory per case, a private `tempfile.tempdir`."""

    def __init__(self):
        self.root = Path(tempfile.mkdtemp(prefix="s8rp-")).resolve()
        self.count = 0
        self.tmp = self.root / "tmp"
        self.tmp.mkdir()
        self.saved_tempdir = tempfile.tempdir
        tempfile.tempdir = str(self.tmp)
        pin_git(self.root)

    def case(self, name: str) -> Path:
        self.count += 1
        path = self.root / ("c%03d-%s" % (self.count, name))
        path.mkdir()
        return path

    def leftovers(self) -> list:
        """The owned temporary directories of the capture that still exist (`zeus-capture-*` under the private tmp)."""
        return sorted(p.name[:len("zeus-capture-")] for p in self.tmp.glob("zeus-capture-*"))

    def scrub(self, value):
        text = str(self.root)
        if isinstance(value, str):
            return value.replace(text, "<root>")
        if isinstance(value, dict):
            return {self.scrub(k) if isinstance(k, str) else k: self.scrub(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [self.scrub(v) for v in value]
        return value

    def close(self) -> None:
        tempfile.tempdir = self.saved_tempdir
        shutil.rmtree(self.root, ignore_errors=True)


def call(ws, fn, *args, **kwargs):
    """The characterized outcome of one call: its value, or the refusal (type, reason code and, for a product refusal,
    its text; an OS error is reported by type only, its text names a path)."""
    try:
        value = fn(*args, **kwargs)
    except Exception as exc:  # the refusal is the characterized result
        result = {"raised": type(exc).__name__}
        for name in ("reason_code", "field"):
            if hasattr(exc, name):
                result[name] = getattr(exc, name)
        if not isinstance(exc, OSError):
            result["message"] = ws.scrub(str(exc))[:200]
        return result
    return {"value": value}


def snapshot(store, buckets=BUCKET_LIST) -> dict:
    """A canonical digest per bucket: the rows of each bucket, by body (the S6/S7 families' `snapshot`)."""
    with store.transaction() as tx:
        return {bucket: canonical_digest(tx.scan(bucket)) for bucket in buckets}


def store_digest(store) -> str:
    with store.transaction() as tx:
        return canonical_digest([[r["bucket"], r["id"], canonical_digest(r["body"])] for r in tx.records()])


def guarded(ws, system, fn, *args, **kwargs):
    """A call, whether it wrote anything ANYWHERE in the store (a refusal before any effect writes nothing) and the
    digest of the whole store after it."""
    before = store_digest(system.store)
    result = call(ws, fn, *args, **kwargs)
    after = store_digest(system.store)
    return {**result, "wrote": after != before, "store": after}


# ---- the git observations -----------------------------------------------------------------------------------------------
def checkout(root) -> dict:
    """What 'the checkout is never moved' is observed through: HEAD, the branch, the staged content (`ls-files -s`),
    `status --porcelain`, and the raw index file (compared, never reported: it holds per-run stat data)."""
    status = out(root, "status", "--porcelain")
    return {"head": out(root, "rev-parse", "HEAD"), "branch": git(root, "symbolic-ref", "-q", "HEAD", check=False).stdout.strip() or None,
            "index": sha256(git(root, "ls-files", "-s").stdout.encode()), "status": status.splitlines(),
            "raw": sha256((Path(root) / ".git" / "index").read_bytes())}


def unchanged(before: dict, after: dict) -> dict:
    return {key: before[key] == after[key] for key in ("head", "branch", "index", "status", "raw")}


def public(observed: dict) -> dict:
    return {key: value for key, value in observed.items() if key != "raw"}


def git_snapshot(root, prefix="refs/zeus/") -> dict:
    """The refs under `refs/zeus/`, for each capture commit its tree, its files (`ls-tree -r`), its parents, its
    author and committer identity and its subject, and the number of loose objects (a refusal after the objects were
    written leaves them; the count shows it)."""
    refs = {}
    for line in out(root, "for-each-ref", "--format=%(refname) %(objectname)", prefix).splitlines():
        name, commit = line.split(" ")
        refs[name] = {"commit": commit, "type": out(root, "cat-file", "-t", commit)}
        if refs[name]["type"] == "commit":
            refs[name].update(
                tree=out(root, "rev-parse", commit + "^{tree}"),
                files=out(root, "ls-tree", "-r", commit).splitlines(),
                parents=out(root, "log", "-1", "--format=%P", commit).split(),
                identity=out(root, "log", "-1", "--format=%an <%ae> | %cn <%ce> | %aI | %cI", commit),
                subject=out(root, "log", "-1", "--format=%s", commit))
    counts = dict(line.split(": ") for line in out(root, "count-objects", "-v").splitlines())
    return {"refs": refs, "loose_objects": int(counts["count"])}


# ---- the repository and the configuration (M7 `repository`, `template`, `config`) ----------------------------------
def repository(base: Path, note=NOTE, message="base", name="repo"):
    """M7 `repository`: a real temporary Git repository with the goal, one local note and a dirty untracked file, under
    the pinned identity and dates, with explicit file modes."""
    root = base / name
    (root / "docs" / "research").mkdir(parents=True)
    for path, data in (((root / "docs" / "research" / "note.md"), note), ((root / "docs" / "GOAL.md"), GOAL)):
        path.write_bytes(data)
        os.chmod(path, 0o644)
    git(root, "init", "-q", "-b", "main")
    git(root, "add", "--all")
    git(root, "commit", "-q", "-m", message)
    head = out(root, "rev-parse", "HEAD")
    (root / "dirty.txt").write_text("uncommitted work stays untouched\n", encoding="utf-8")
    (root / "docs" / "GOAL.md").write_bytes(GOAL + b"working tree edit\n")
    return root, head


def clone(base: Path, root, name="clone"):
    """M7 `clone`: a REAL second clone of the temporary repository (same objects, another root)."""
    other = base / name
    git(root, "clone", "-q", str(root), str(other))
    return other


def template(head, deadline="2030-01-01T00:00:00+00:00"):
    return {"schema": "urn:zeus:autonomous:2", "id": "council-template", "base_revision": head,
            "goal": {"path": "docs/GOAL.md", "sha256": sha256(GOAL), "criterion": "c", "rationale": "r"},
            "plan": {"objective": "improve the research report " + CANARY, "acceptance_criteria": ["focused tests pass"],
                     "allowed_paths": ["docs/RUNBOOK.md"]},
            "budget": {"per_host": 10, "total": 20},
            "claude": {"model": "claude-fixture-model", "timeout_seconds": 120, "max_budget_usd": 1},
            "deadline": deadline,
            "research": {"topic": "research report", "questions": ["What is the SSOT?"], "search_scope": ["docs"]},
            "current_state": {"records": [{"bucket": "tasks", "id": "t-1"}], "max_age_seconds": 600}}


def config(head, **overrides):
    document = {"schema": "urn:zeus:research-program:1", "id": PROGRAM, "base_revision": head,
                "deadline": "2029-06-01T00:00:00+00:00", "interval_seconds": 3600, "max_cycles": 2, "max_adoptions": 1,
                "budget": {"per_host": 10, "total": 20},
                "topics": [{"id": "storage", "keywords": ["advisory lock", "postgres"]}],
                "local_candidates": [{"id": "local-note", "topic": "storage", "path": "docs/research/note.md",
                                      "sha256": sha256(NOTE), "rationale": "sterk residual " + CANARY}],
                "template": template(head)}
    document.update(overrides)
    return document


# ---- the doubles ---------------------------------------------------------------------------------------------------------
class Clock:
    """LABELLED. M7 `tests/test_research_program.py::Clock`: a settable ISO string. `step` (the labelled extension)
    advances the time by that many seconds after every read."""

    def __init__(self, value=BASE_CLOCK, step=0):
        self.value, self.step = value, step

    def __call__(self):
        value = self.value
        if self.step:
            self.advance(self.step)
        return value

    def advance(self, seconds):
        self.value = (datetime.fromisoformat(self.value) + timedelta(seconds=seconds)).isoformat()


class Sources:
    """LABELLED. M7 `FakeSources`: synthetic feeds from RECORDED bodies, no network. `outages` names sources that raise
    on collect; `paused` the sources the pressure evaluator holds (INV-DISCOVERY-PRESSURE-001); `detail` is what
    `github_detail` does: None raises (M7), a dict is returned."""

    def __init__(self, api, artifacts, outages=(), items=None, detail=None):
        self.api, self.artifacts, self.outages, self.calls = api, artifacts, set(outages), []
        self.paused, self.detail = set(), detail
        self.items = items if items is not None else {
            "github": [{"url": "https://github.com/acme/pgtool#readme", "title": "acme/pgtool", "summary": "Postgres tooling"},
                       {"url": "https://github.com/acme/unrelated", "title": "acme/unrelated", "summary": "a game engine"}],
            "geeknews": [{"url": "https://news.hada.io/topic?id=1", "title": "Advisory lock patterns", "summary": "<p>x</p>"}]}

    def collect(self, source, *, intent):
        self.calls.append(source)
        if source in self.paused:
            raise self.api.DiscoveryPaused({"decision": "hold", "reason_code": "pressure_high"})
        if source in self.outages:
            raise OSError("fixture outage " + CANARY)
        receipt = self.artifacts.put("<html>fixture body " + source + "</html>", "fixture:" + source)
        return {"source": source, "fetched_at": BASE_CLOCK, "artifact": receipt["ref"], "items": list(self.items[source])}

    def github_detail(self, url):
        if self.detail is None:
            raise RuntimeError("fixture: no GitHub API " + CANARY)
        return dict(self.detail)


class Budget:
    """LABELLED. M7 `FakeBudget`: a synthetic machine-ledger reading; the real CallBudget is never touched. `fail` is
    the labelled raise of an unreadable ledger."""

    def __init__(self, this_host=0, all_hosts=0, fail=None):
        self.this_host, self.all_hosts, self.fail = this_host, all_hosts, fail

    def counts(self):
        if self.fail is not None:
            raise self.fail
        return {"host": "fixture", "this_host": self.this_host, "all_hosts": self.all_hosts, "unreadable": 0}


class Council:
    """LABELLED council STAND-IN. M7 `FakeCouncil` and `MismatchedCouncil`: validates the persisted manifest with the
    real validator and writes the `autonomous_runs` row the runner must read; no provider is called. `status` None
    writes no row and raises `error` (a refusal before any claim); `raise_after_row` raises after writing the row;
    `sha` replaces the row's manifest digest (M7 `MismatchedCouncil`); `silent` returns without a row or a raise."""

    def __init__(self, api, store, status="rejected", raise_after_row=False, error=RuntimeError, sha=None, silent=False):
        self.api, self.store, self.status, self.raise_after_row = api, store, status, raise_after_row
        self.error, self.sha, self.silent, self.manifests = error, sha, silent, []

    def __call__(self, service, args):
        manifest = self.api.validate_any_manifest(json.loads(Path(args.file).read_text(encoding="utf-8")), self.api.POLICY)
        self.manifests.append(manifest)
        if self.silent:
            return {"status": "silent", "exit_code": 0}
        if self.status is None:
            raise self.error("fixture refusal before claim " + CANARY)  # LABELLED fault: raise before any row
        with self.store.transaction() as tx:
            tx.put(self.api.RUNS, manifest["id"], {
                "id": manifest["id"], "status": self.status, "stage": "promotion",
                "manifest_sha256": self.sha or self.api.manifest_digest(manifest), "reason_code": "fixture_" + self.status})
        if self.raise_after_row:
            raise self.error("fixture crash after the row " + CANARY)  # LABELLED fault: raise after the row
        return {"status": self.status, "exit_code": 0}


class FlakyStore:
    """LABELLED. M7 `FlakyStore`: a store in front of another one whose `transaction` raises `OSError` while `fail`."""

    def __init__(self, store):
        self.inner, self.fail = store, False

    def transaction(self):
        if self.fail:
            raise OSError("fixture: store unavailable " + CANARY)  # LABELLED fault: the store outage
        return self.inner.transaction()


class ShiftingSource:
    """LABELLED fault: a `GitSource` whose `blob` answers as the real one for the first `after` reads of a path and
    then as `mode`/`data` says (None keeps the real value): the base content changing between the discovery check and
    the capture's own check."""

    def __init__(self, inner, after=1, mode=None, data=None):
        self.inner, self.after, self.mode, self.data, self.reads = inner, after, mode, data, {}

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def blob(self, revision, path):
        mode, data = self.inner.blob(revision, path)
        self.reads[path] = self.reads.get(path, 0) + 1
        if self.reads[path] > self.after:
            return (self.mode or mode), (self.data if self.data is not None else data)
        return mode, data


# ---- the environment builders (M7 `build`, `registered`) ----------------------------------------------------------------
def build(api, ws, name, store=None, clock=None, council=None, outages=(), budget=None, root=None, head=None,
          identity=IDENTITY, detail=None, items=None, github_detail=True, status="rejected", **council_options):
    """M7 `build`: a fresh repository (or `root`/`head`), a store, the program state machine, the feeds, the artifacts
    in a temporary root, a runtime directory and the runner. `identity` is the LABELLED repository identity."""
    base = ws.case(name)
    if root is None:
        root, head = repository(base)
    store = store or api.MemoryStore()
    clock = clock or Clock()
    service = SimpleNamespace(store=store, org=None)
    runtime = base / "runtime"
    artifacts = api.FileArtifacts(str(runtime / "artifacts"))
    programs = api.ResearchProgram(store, clock=clock)
    sources = Sources(api, artifacts, outages, items=items, detail=detail)
    if council is None:
        council = Council(api, store, status=status, **council_options)
    runner = api.ProgramRunner(service, programs, sources, api.GitSource(root), api.GitCapture(root), budget or Budget(),
                               artifacts, runtime, council=council,
                               github_detail=sources.github_detail if github_detail else None, clock=clock,
                               repository=identity)
    return SimpleNamespace(api=api, ws=ws, base=base, root=root, head=head, store=store, clock=clock, programs=programs,
                           sources=sources, council=council, runner=runner, runtime=runtime, artifacts=artifacts,
                           identity=identity, service=service)


def registered(env, resume=True, **overrides):
    """M7 `registered`: validate, register with the labelled identity, resume."""
    cfg = env.api.validate_config(config(env.head, **overrides), env.api.POLICY)
    env.programs.register(cfg, env.identity, [])
    if resume:
        env.programs.resume(cfg["id"])
    return cfg


def tick(env, program=PROGRAM, intent=INTENT):
    return env.runner.tick(program, intent=intent)


# ---- the observations of a program ---------------------------------------------------------------------------------------
def events(env, program=PROGRAM) -> list:
    path = env.runtime / "research-program" / program / "events.jsonl"
    if not path.is_file():  # absent, or replaced by a directory by a labelled fault
        return []
    return [json.loads(line) for line in path.read_text("utf-8").splitlines()]


def event_names(env, program=PROGRAM) -> list:
    return [e["category"] + "/" + e["event"] for e in events(env, program)]


def files(env) -> dict:
    """Every file the runner wrote under `<runtime>/research-program`: its size and digest (`events.jsonl` carries the
    frozen fake clock, so it is deterministic)."""
    base = env.runtime / "research-program"
    found = {}
    if base.exists():
        for path in sorted(p for p in base.rglob("*") if p.is_file()):
            data = path.read_bytes()
            found[str(path.relative_to(base))] = {"bytes": len(data), "sha256": sha256(data)}
    return found


def candidates(env, program=PROGRAM) -> list:
    keys = ("id", "source", "status", "reason", "result", "seen", "claimed_cycle", "first_cycle", "last_cycle")
    return [{k: row.get(k) for k in keys} for row in env.programs.candidates(program)]


def runs(env) -> list:
    with env.store.transaction() as tx:
        return tx.scan(env.api.RUNS)


def view(env, program=PROGRAM):
    try:
        return env.programs.status(program)
    except Exception as exc:
        return {"raised": type(exc).__name__, "reason_code": getattr(exc, "reason_code", None)}


def observe(env, *, program=PROGRAM, git_state=True, full=True) -> dict:
    """The standard observation after a call: the program view, the candidates, the run rows, the digests of the store,
    the event names and attributes, the files written, the feeds and council calls, and the git state of the root."""
    observed = {"program": view(env, program), "store": snapshot(env.store),
                "source_calls": list(env.sources.calls), "council_calls": len(getattr(env.council, "manifests", []))}
    if full:
        observed.update(candidates=candidates(env, program) if observed["program"].get("id") else [],
                        runs=runs(env), events=[[e["category"], e["event"], e["cycle"], e["attributes"]]
                                               for e in events(env, program)], files=files(env))
    if git_state:
        observed["git"] = git_snapshot(env.root)
    return env.ws.scrub(observed)


@contextlib.contextmanager
def replaced(obj, name, value):
    """LABELLED fault seam: replace one attribute of an object for the duration of a case."""
    had = name in vars(obj)
    saved = vars(obj).get(name)
    setattr(obj, name, value)
    try:
        yield
    finally:
        if had:
            setattr(obj, name, saved)
        else:
            delattr(obj, name)


# ---- the investigation candidate (M7 `tests/test_research_investigations.py`) ---------------------------------------------
POLICY_TOPICS = {"storage"}
SOURCE = {"topic": "storage", "project_ids": ["ops"], "reason_codes": ["store_timeout"]}
FAMILY = ("failed", "store_timeout")
DEFINITIONS = {"schema": "urn:zeus:portfolio-definitions:1", "projects": [
    {"id": "ops", "title": "Operations", "outcome": "bound fleet work completes", "source_ref": "docs/GOAL.md",
     "criteria": [{"id": "c1", "text": "jobs reach a terminal accepted state"}]},
    {"id": "other", "title": "Other", "outcome": "unrelated work", "source_ref": "docs/GOAL.md",
     "criteria": [{"id": "c1", "text": "unrelated criterion"}]}]}
# (job id, status, reason code, bound project): two distinct qualifying jobs and one same-family job bound to a project
# the program is NOT authorized for.
JOBS = (("j-1", "failed", "store_timeout", "ops"), ("j-2", "failed", "store_timeout", "ops"),
        ("j-3", "failed", "store_timeout", "other"), ("j-4", "rejected", "review_rejected", "ops"))


def portfolio(api, store, jobs=JOBS):
    """M7 `portfolio`: LABELLED synthetic Fleet rows (only the fields the reconciler reads) under the REAL portfolio
    reconciler, owner bindings and owner dispositions."""
    owner = api.Portfolio(store, DEFINITIONS, clock=lambda: BASE_CLOCK)
    with store.transaction() as tx:
        for job_id, status, reason, _ in jobs:
            tx.put(api.BUCKET_JOBS, job_id, {"id": job_id, "lane": "lane-1", "status": status, "reason_code": reason,
                                             "error_type": None, "updated_at": BASE_CLOCK})
    for job_id, _, _, project in jobs:
        owner.bind(job_id, project, "c1")
    owner.reconcile()
    return owner


def dispatch_rows(env) -> list:
    with env.store.transaction() as tx:
        return tx.scan(env.api.BUCKET_DISPATCHES)
