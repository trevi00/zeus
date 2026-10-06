"""RH-2 P5b-1: `fileroots.acquire` and `fileroots.verify_seal` over SYNTHETIC stand-ins with the real `/usr/bin/gnucp`.

Layer: harness tooling tests. Expected results come from the task spec (rh2-p5b1-acquisition, Examples 1-4, Expected
results 1-6, What 3) and E9 (Partition, Transport, Fidelity, Seal and validity): the copy keeps modes, mtimes, empty
directories, hard-link groups and literal links; every failure is one named, bounded `RefusedFacts` that leaves no
`complete.json` (so `verify_seal` refuses); a secret-like name that appears after the survey STOPs before it is
published. A tripwire audit hook (gated, one per module) fails any open/scandir/listdir/subprocess argv naming the real
`/srv/zeus`. The negatives inject their change through the host's per-cp hooks and a fake monotonic clock whose call
order is fixed by the contract: once at the start, then per root before its re-check ("its turn") and before its cp.
The last test drives a fresh interpreter (behavioural: the guard stays uninstalled, `copies` is never loaded).
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys

import pytest
from _layout import REPO

sys.path.insert(0, str(REPO / "compare"))
from rehearsal import Refused  # noqa: E402
from rehearsal import fileroots as fr  # noqa: E402
from rehearsal import phase_p as pp  # noqa: E402
from rehearsal.evidence import check_facts  # noqa: E402

REAL = "/srv/zeus"
RUN8 = "1a2b3c4d"
CANARY = "runtime/lanes/harness/workspaces/review-canary-0123456789abcdef/.venv/bin/python"
OTHER_CANARY = "runtime/lanes/harness/workspaces/review-canary-fedcba9876543210/.venv/bin/python"
IDS = [i for i, _r in fr.STABLE_ROOTS]
_state = {"active": False, "opens": [], "scandirs": [], "argvs": []}


def _hook(event, args):
    if not _state["active"]:
        return
    if event == "subprocess.Popen":
        _state["argvs"].append([str(a) for a in args[1]])
        scanned = [str(a) for a in args[:3]]
    elif event in ("open", "os.scandir", "os.listdir"):
        scanned = [str(args[0])] if args else []
        _state["opens" if event == "open" else "scandirs"].append(scanned[0] if scanned else "")
    else:
        return
    if any(REAL in text for text in scanned):
        raise AssertionError(f"tripwire: {event} names the real {REAL}: {scanned}")


sys.addaudithook(_hook)


@pytest.fixture(autouse=True)
def tripwire():
    _state.update(active=True, opens=[], scandirs=[], argvs=[])
    yield _state
    _state["active"] = False


def touch(path, text="x", mtime=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    if mtime is not None:
        os.utime(path, ns=(mtime, mtime))


@pytest.fixture
def srv(tmp_path, tripwire):
    root = tmp_path / "srv"
    for d in ("runtime/control/artifacts", "runtime/control/observations/health", "runtime/control/observations/spool",
              "runtime/control/verification", "runtime/control/worker-sessions", "runtime/tokobs",
              "runtime/lanes/harness", "runtime/managed-fleet", "managed-fleet/fleetdir", "repo/.git", "worktrees/w",
              "repo/emptydir"):
        (root / d).mkdir(parents=True)
    t = 1_700_000_000_000_000_000
    for i, f in enumerate((
            "runtime/control/monitoring.json", "runtime/control/monitor-collector.log",
            "runtime/control/observations/health/h.json", "runtime/managed-fleet/heartbeat.json",
            "runtime/control/artifacts/a.bin", "runtime/control/artifacts.lock", "runtime/control/fleet-owner.json",
            "runtime/control/host-activation.json", "runtime/managed-fleet/descriptor.json",
            "runtime/tokobs/ledger", "runtime/lanes/harness/l.txt", "runtime/control/verification/v.json",
            "runtime/control/worker-sessions/s.json", "runtime/control/observations/spool/p.json",
            "managed-fleet/f.json", "repo/a.py", "repo/.git/HEAD", "worktrees/w/a.py")):
        touch(root / f, f"content of {f}", t + i * 1_000_000_007)
    touch(root / "worktrees/w/.git", "gitdir: /x")
    touch(root / "managed-fleet/fleetdir/ro.txt", "read only")
    os.chmod(root / "managed-fleet/fleetdir/ro.txt", 0o444)
    touch(root / "repo/run.sh", "#!/bin/sh\n")
    os.chmod(root / "repo/run.sh", 0o755)
    os.link(root / "worktrees/w/a.py", root / "worktrees/w/h2")
    (root / CANARY).parent.mkdir(parents=True)
    (root / CANARY).symlink_to(fr.SYMLINK_ALLOWANCE[0]["target"])
    for rel in ("secrets/x", "stack/secrets/y", "config/a.env", "backups/b"):
        touch(root / rel, "TOPSECRETCONTENT")
    tripwire.update(opens=[], scandirs=[], argvs=[])
    return root


@pytest.fixture
def root(tmp_path):
    (tmp_path / "root").mkdir()
    return tmp_path / "root"


class RecHost(pp.Host):
    """The real Host with per-cp hooks: `before(n, argv)`, `after(n, argv)`; records argv, timeout and clock calls."""

    def __init__(self, clock=None):
        self.runs, self.before, self.after, self.override, self.clock = [], None, None, None, clock

    def run(self, argv, *, timeout=120, stdout=None):
        n = len(self.runs)
        self.runs.append({"argv": list(argv), "timeout": timeout, "clock_calls": self.clock.n if self.clock else None})
        if self.before:
            self.before(n, argv)
        done = self.override(n, argv) if self.override else None
        if done is None:
            done = super().run(argv, timeout=timeout, stdout=stdout)
        if self.after:
            self.after(n, argv)
        return done


class Clock:
    """Fake monotonic: call k returns k seconds (or a jump); `hooks[k]` runs on call k before it returns."""

    def __init__(self, hooks=None, jump_from=None):
        self.n, self.hooks, self.jump_from = 0, hooks or {}, jump_from

    def __call__(self):
        k = self.n
        self.n += 1
        if k in self.hooks:
            self.hooks[k]()
        return 10_000.0 if self.jump_from is not None and k >= self.jump_from else float(k)


def turn(k):
    return 1 + 2 * k  # clock call index before root k's re-check


def cp_call(k):
    return 2 + 2 * k  # clock call index before root k's cp


def go(srv, root, *, host=None, clock=None):
    clock = clock or Clock()
    host = host or RecHost(clock)
    host.clock = clock
    return fr.acquire(host, srv, root / "seal", RUN8, monotonic=clock, repo=REPO), host, clock


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stopped(srv, root, tmp_path, code, **kw):
    """Run acquire expecting the named refusal; return the error after the D17 and no-seal checks."""
    with pytest.raises(fr.RefusedFacts) as caught:
        go(srv, root, **kw)
    error = caught.value
    assert error.code == code, (error.code, error.detail, error.facts)
    assert len(error.detail) <= 512 and str(tmp_path) not in error.detail + json.dumps(error.facts)
    check_facts({"detail": error.detail, **error.facts})
    assert not (root / "seal/meta/complete.json").exists()
    with pytest.raises(Refused) as bad:
        fr.verify_seal(root / "seal", {}, RUN8)
    assert bad.value.code == "seal_invalid"
    return error


def tree_state(path):
    out = {}
    for dirpath, dirnames, filenames in os.walk(path):
        for name in dirnames + filenames:
            full = os.path.join(dirpath, name)
            info = os.lstat(full)
            out[os.path.relpath(full, path)] = (info.st_mode, info.st_mtime_ns, info.st_size)
    return out


# ---- positive ----

def test_the_full_stand_in_is_acquired_verified_and_sealed(srv, root, tmp_path, tripwire):
    before = tree_state(srv)
    tripwire.update(opens=[], scandirs=[], argvs=[])  # the test's own walk above is not acquire's
    old = os.umask(0o022)
    try:
        facts, host, clock = go(srv, root)
        assert os.umask(0o022) == 0o022  # restored
    finally:
        os.umask(old)
    touched = tripwire["opens"] + tripwire["scandirs"]
    argvs = [list(a) for a in tripwire["argvs"]]
    assert facts["ok"] is True and facts["input_kind"] == "synthetic" and facts["symlinks"]["allowed"] == 1
    assert list(facts["roots"]) == IDS
    for root_id, rec in facts["roots"].items():
        assert rec["ok"] is True and rec["cp_exit"] == 0 and rec["verify"] == {
            "missing": 0, "extra": 0, "mismatched": 0, "unreadable": 0, "mtime_mismatch": 0}, root_id
        assert rec["manifest_digest"].startswith("sha256:") and len(rec["manifest_sha256"]) == 64
    check_facts(facts)
    assert str(tmp_path) not in json.dumps(facts) and facts["stable_files"]["count"] == 4
    assert tree_state(srv) == before  # nothing under the source was written
    seal = root / "seal"
    got = fr.verify_seal(seal, facts, RUN8)
    assert got["files"] == 18 and got["complete_sha256"] == facts["complete_sha256"] == sha(seal / "meta/complete.json")
    complete = json.loads((seal / "meta/complete.json").read_text())
    assert complete["schema"] == fr.COMPLETE_SCHEMA and complete["run8"] == RUN8 and len(complete["files"]) == 18
    # cp argv, timeout and ordering after the clock calls
    assert len(host.runs) == 8
    for k, ((root_id, rel), run) in enumerate(zip(fr.STABLE_ROOTS, host.runs, strict=True)):
        assert run["argv"] == [fr.CP, "-a", "-T", "--", str(srv / rel), str(seal / "tree" / rel)]
        assert run["timeout"] == fr.CP_TIMEOUT_S and run["clock_calls"] == cp_call(k) + 1
    # fidelity: modes, mtimes, empty dirs, hard-link groups, the literal link
    for _id, rel in fr.STABLE_ROOTS:
        for dirpath, dirnames, filenames in os.walk(srv / rel):
            for name in dirnames + filenames:
                s, d = os.path.join(dirpath, name), seal / "tree" / os.path.relpath(os.path.join(dirpath, name), srv)
                si, di = os.lstat(s), os.lstat(d)
                assert stat.S_IMODE(si.st_mode) == stat.S_IMODE(di.st_mode), d
                if not stat.S_ISDIR(si.st_mode):
                    assert si.st_mtime_ns == di.st_mtime_ns, d
    tree = seal / "tree"
    assert (tree / "repo/emptydir").is_dir() and stat.S_IMODE(os.lstat(tree / "managed-fleet/fleetdir/ro.txt").st_mode) == 0o444
    assert stat.S_IMODE(os.lstat(tree / "repo/run.sh").st_mode) == 0o755
    assert os.lstat(tree / "worktrees/w/a.py").st_ino == os.lstat(tree / "worktrees/w/h2").st_ino
    assert os.readlink(tree / CANARY) == fr.SYMLINK_ALLOWANCE[0]["target"]
    # volatile and single copies; the excluded and sibling trees are never read
    assert (tree / "runtime/control/monitoring.json").read_text() == "content of runtime/control/monitoring.json"
    assert (tree / "runtime/control/observations/health/h.json").is_file()
    assert (tree / "runtime/control/fleet-owner.json").is_file() and (tree / "runtime/managed-fleet/descriptor.json").is_file()
    assert not (tree / "runtime/tokobs").exists()
    for rel in ("runtime/tokobs", "secrets", "stack", "config", "backups"):
        assert not any(str(srv / rel) in p for p in touched), rel
    assert not any("secrets" in a for argv in argvs for a in argv)
    # 0700 / 0600 under umask 022 (A-F14)
    mode = lambda p: stat.S_IMODE(os.lstat(p).st_mode)  # noqa: E731
    for d in (seal, seal / "tree", seal / "meta", tree / "runtime", tree / "runtime/control", tree / "runtime/control/observations",
              tree / "runtime/control/observations/health", tree / "runtime/managed-fleet"):
        assert mode(d) == 0o700, d
    for f in (*(seal / "meta").iterdir(), tree / "runtime/control/monitoring.json", tree / "runtime/control/fleet-owner.json",
              tree / "runtime/control/observations/health/h.json"):
        assert mode(f) == 0o600, f
    single = json.loads((seal / "meta/single.json").read_text())
    assert single["schema"] == fr.SINGLE_SCHEMA and {e["path"] for e in single["stable"]} == {
        "runtime/control/artifacts.lock", "runtime/control/fleet-owner.json", "runtime/control/host-activation.json",
        "runtime/managed-fleet/descriptor.json"}
    assert all(set(e) == {"path", "size", "mtime_ns", "mode", "read_at_ns", "sha256"} for e in single["stable"])
    assert single["dirs"]["runtime/control"]["mode"] == mode(srv / "runtime/control")


def test_a_seal_is_reproducible_in_its_manifests_modulo_scan_time(srv, tmp_path):
    (tmp_path / "r1").mkdir()
    (tmp_path / "r2").mkdir()
    go(srv, tmp_path / "r1")
    go(srv, tmp_path / "r2")
    a, b = (json.loads((tmp_path / r / "seal/meta/repo.manifest.json").read_text()) for r in ("r1", "r2"))
    assert a["digest"] == b["digest"]


# ---- negatives: the source changes while staging ----

def test_a_stable_file_rewritten_before_its_cp_stops_as_a_mismatch(srv, root, tmp_path):
    host = RecHost()
    host.before = lambda n, argv: touch(srv / "repo/a.py", "rewritten") if n == 6 else None
    stopped(srv, root, tmp_path, "verify_repo_mismatch", host=host)


def test_a_new_file_in_a_root_before_its_cp_stops_as_a_mismatch(srv, root, tmp_path):
    host = RecHost()
    host.before = lambda n, argv: touch(srv / "runtime/lanes/harness/new.txt") if n == 0 else None
    error = stopped(srv, root, tmp_path, "verify_runtime-lanes_mismatch", host=host)
    assert error.facts["extra"] == 1


def test_a_new_file_in_repo_after_the_first_cp_is_volatile_undeclared(srv, root, tmp_path):
    host = RecHost()
    host.after = lambda n, argv: touch(srv / "repo/late.txt") if n == 0 else None
    error = stopped(srv, root, tmp_path, "volatile_undeclared", host=host)
    assert error.facts["paths"] == ["repo/late.txt"] and error.facts["count"] == 1


def test_a_volatile_file_rewritten_during_staging_does_not_stop_and_the_seal_holds_the_first_read(srv, root):
    host = RecHost()
    host.after = lambda n, argv: touch(srv / "runtime/control/monitoring.json", "second, longer content") if n == 0 else None
    facts, _host, _clock = go(srv, root, host=host)
    assert facts["ok"] is True
    assert (root / "seal/tree/runtime/control/monitoring.json").read_text() == "content of runtime/control/monitoring.json"
    entry = next(e for e in json.loads((root / "seal/meta/single.json").read_text())["volatile"]
                 if e["path"] == "runtime/control/monitoring.json")
    assert entry["sha256"] == hashlib.sha256(b"content of runtime/control/monitoring.json").hexdigest()


def test_a_stable_single_file_resized_during_staging_is_volatile_undeclared(srv, root, tmp_path):
    host = RecHost()
    host.after = lambda n, argv: touch(srv / "runtime/control/fleet-owner.json", "a different size") if n == 0 else None
    stopped(srv, root, tmp_path, "volatile_undeclared", host=host)


def test_a_stable_single_file_rewritten_with_its_size_and_mtime_restored_is_caught_by_the_reread(srv, root, tmp_path):
    path = srv / "runtime/control/fleet-owner.json"
    info = path.stat()

    def rewrite(n, argv):
        if n == 0:
            path.write_text("X" * info.st_size)
            os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns))

    host = RecHost()
    host.after = rewrite
    error = stopped(srv, root, tmp_path, "stable_file_changed", host=host)
    assert error.detail == "runtime/control/fleet-owner.json"


# ---- negatives: links, locks, partition, topology ----

def test_an_unallowed_link_at_the_start_is_refused(srv, root, tmp_path):
    link = srv / OTHER_CANARY  # matches the allowance path regex, but not its literal target
    link.parent.mkdir(parents=True)
    link.symlink_to("/usr/bin/python3")
    stopped(srv, root, tmp_path, "external_symlink_unallowed")


def test_an_unallowed_link_appearing_at_its_roots_turn_is_refused_per_root(srv, root, tmp_path):
    def make():
        (srv / OTHER_CANARY).parent.mkdir(parents=True)
        (srv / OTHER_CANARY).symlink_to("/usr/bin/python3")

    host = RecHost()
    stopped(srv, root, tmp_path, "inventory_runtime-lanes_external_symlink", host=host, clock=Clock({turn(0): make}))
    assert host.runs == []


@pytest.mark.parametrize("rel,kind,code", [
    ("repo", "gone", "source_root_missing"),
    ("repo", "symlink", "source_root_symlink"),
    ("runtime/lanes", "symlink", "source_root_symlink"),
])
def test_a_missing_or_symlinked_root_at_the_start_is_refused(srv, root, tmp_path, rel, kind, code):
    path = srv / rel
    shutil.rmtree(path)
    if kind == "symlink":
        path.symlink_to(srv / "worktrees")
    stopped(srv, root, tmp_path, code)


def test_a_root_swapped_for_a_symlink_at_its_turn_is_refused_before_any_cp_of_it(srv, root, tmp_path):
    def swap():
        os.rename(srv / "repo", srv / "repo-away")
        (srv / "repo").symlink_to(srv / "repo-away")

    host = RecHost()
    stopped(srv, root, tmp_path, "source_root_symlink", host=host, clock=Clock({turn(6): swap}))
    assert len(host.runs) == 6 and not any(r["argv"][-1].endswith("tree/repo") for r in host.runs)


def test_an_unclassified_entry_is_refused(srv, root, tmp_path):
    (srv / "runtime/newdir").mkdir()
    stopped(srv, root, tmp_path, "partition_unclassified")


def test_a_git_lock_is_refused_at_the_start_and_at_repos_turn(srv, root, tmp_path):
    touch(srv / "repo/.git/index.lock")
    stopped(srv, root, tmp_path, "git_lock_present")
    (srv / "repo/.git/index.lock").unlink()
    shutil.rmtree(root)
    root.mkdir()
    host = RecHost()
    stopped(srv, root, tmp_path, "git_lock_present", host=host, clock=Clock({turn(6): lambda: touch(srv / "repo/.git/index.lock")}))
    assert len(host.runs) == 6


# ---- negatives: cp, time ----

def test_a_failing_cp_names_its_root_and_exit(srv, root, tmp_path):
    host = RecHost()
    host.override = lambda n, argv: subprocess.CompletedProcess(argv, 1, "", "cp: boom\ncp: more\n") if n == 0 else None
    error = stopped(srv, root, tmp_path, "cp_runtime-lanes_exit_1", host=host)
    assert error.facts == {"exit": 1, "stderr_lines": 2}


def test_a_cp_timeout_propagates_and_the_umask_is_restored(srv, root):
    def boom(n, argv):
        raise subprocess.TimeoutExpired(argv, fr.CP_TIMEOUT_S)

    host = RecHost()
    host.before = boom
    old = os.umask(0o022)
    try:
        with pytest.raises(subprocess.TimeoutExpired):
            go(srv, root, host=host)
        assert os.umask(0o022) == 0o022
    finally:
        os.umask(old)
    assert host.runs[0]["timeout"] == 1800


def test_a_keyboard_interrupt_in_a_cp_propagates_and_the_umask_is_restored(srv, root):
    def interrupt(n, argv):
        raise KeyboardInterrupt

    host = RecHost()
    host.before = interrupt
    old = os.umask(0o022)
    try:
        with pytest.raises(KeyboardInterrupt):
            go(srv, root, host=host)
        assert os.umask(0o022) == 0o022
    finally:
        os.umask(old)


@pytest.mark.parametrize("jump_from", [1, 2, 7, 12])
def test_a_clock_past_the_deadline_stops_before_the_next_root_or_cp(srv, root, tmp_path, jump_from):
    host = RecHost()
    stopped(srv, root, tmp_path, "deadline_exceeded", host=host, clock=Clock(jump_from=jump_from))
    assert len(host.runs) == (jump_from - 1) // 2  # the cps issued before the failing clock call


def test_the_deadline_boundary_is_past_2700_seconds(srv, root):
    class Edge(Clock):
        def __call__(self):
            self.n += 1
            return 0.0 if self.n == 1 else float(fr.DEADLINE_S)

    facts, _host, _clock = go(srv, root, clock=Edge())
    assert facts["ok"] is True  # exactly DEADLINE_S after the start is not past the deadline


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads a mode 000 file")
def test_an_unreadable_file_in_a_root_is_blocking(srv, root, tmp_path):
    path = srv / "repo/a.py"
    path.chmod(0)
    try:
        stopped(srv, root, tmp_path, "inventory_repo_blocking")
    finally:
        path.chmod(0o644)


# ---- negatives: verification (the staged copy differs) ----

def test_a_staged_mtime_changed_after_the_cp_is_an_mtime_stop(srv, root, tmp_path):
    def retime(n, argv):
        if n == 0:
            os.utime(root / "seal/tree/runtime/lanes/harness/l.txt", ns=(5, 5))

    host = RecHost()
    host.after = retime
    stopped(srv, root, tmp_path, "verify_runtime-lanes_mtime", host=host)


def test_a_staged_mode_changed_after_the_cp_is_a_mode_stop(srv, root, tmp_path):
    host = RecHost()
    host.after = lambda n, argv: os.chmod(root / "seal/tree/managed-fleet/fleetdir/ro.txt", 0o644) if n == 5 else None
    stopped(srv, root, tmp_path, "verify_managed-fleet_mode", host=host)


def test_a_staged_empty_directory_removed_after_the_cp_is_a_dirs_stop(srv, root, tmp_path):
    host = RecHost()
    host.after = lambda n, argv: os.rmdir(root / "seal/tree/repo/emptydir") if n == 6 else None
    stopped(srv, root, tmp_path, "verify_repo_dirs", host=host)


def test_a_staged_hard_link_pair_split_into_identical_copies_is_a_links_stop(srv, root, tmp_path):
    def split(n, argv):
        if n == 7:
            target = root / "seal/tree/worktrees/w/h2"
            copy = target.with_name("h2.copy")
            shutil.copy2(target, copy)
            os.replace(copy, target)

    host = RecHost()
    host.after = split
    stopped(srv, root, tmp_path, "verify_worktrees_links", host=host)


def test_a_staged_content_change_is_a_mismatch(srv, root, tmp_path):
    host = RecHost()
    host.after = lambda n, argv: (root / "seal/tree/managed-fleet/f.json").write_text("tampered") if n == 5 else None
    stopped(srv, root, tmp_path, "verify_managed-fleet_mismatch", host=host)


# ---- negatives: evidence, seal, topology of the call ----

def test_a_fact_equal_to_an_environment_value_is_unbounded_and_the_seal_has_no_ok(srv, root, monkeypatch):
    monkeypatch.setenv("RH_P5_PROBE", fr.cp_identity()["version"])
    with pytest.raises(fr.RefusedFacts) as caught:
        go(srv, root)
    assert caught.value.code == "evidence_unbounded" and caught.value.facts == {"rule": "env_value_fact"}
    complete = root / "seal/meta/complete.json"
    assert complete.is_file()  # step 9 precedes the facts check; verify_seal refuses for the missing ok
    with pytest.raises(Refused) as bad:
        fr.verify_seal(root / "seal", {"complete_sha256": sha(complete)}, RUN8)
    assert (bad.value.code, bad.value.detail) == ("seal_invalid", "p5_not_ok")


def test_an_existing_seal_is_refused(srv, root, tmp_path):
    (root / "seal").mkdir()
    stopped(srv, root, tmp_path, "seal_exists")
    assert list((root / "seal").iterdir()) == []


def test_a_root_under_the_source_is_refused_before_any_listing(srv, tmp_path, tripwire):
    seal_root = srv / "worktrees/r"
    clock = Clock()
    with pytest.raises(fr.RefusedFacts) as caught:
        fr.acquire(RecHost(clock), srv, seal_root / "seal", RUN8, monotonic=clock, repo=REPO)
    assert caught.value.code == "seal_overlaps_source"
    assert not any(p.startswith(str(srv)) for p in tripwire["scandirs"] + tripwire["opens"])
    assert not seal_root.exists()


def test_a_source_inside_the_root_is_refused_too(srv, tmp_path):
    with pytest.raises(fr.RefusedFacts) as caught:
        fr.acquire(RecHost(), srv, tmp_path / "seal", RUN8, repo=REPO)  # ROOT == the directory holding srv's parent
    assert caught.value.code == "seal_overlaps_source"


def test_a_secret_name_after_the_survey_in_the_health_dir_stops_before_it_is_read(srv, root, tmp_path, monkeypatch):
    original = fr.git_locks

    def plant(*args, **kwargs):
        got = original(*args, **kwargs)
        touch(srv / "runtime/control/observations/health/.env", "TOPSECRETCONTENT")
        return got

    monkeypatch.setattr(fr, "git_locks", plant)
    _state["opens"].clear()
    error = stopped(srv, root, tmp_path, "secret_path_in_root")
    assert error.facts["where"] == "volatile"
    assert not (root / "seal/tree/runtime").exists()  # nothing was copied
    assert not [p for p in (root / "seal").rglob("*") if p.name == ".env"]


def test_a_secret_name_at_a_roots_turn_stops_at_the_inventory(srv, root, tmp_path):
    host = RecHost()
    error = stopped(srv, root, tmp_path, "secret_path_in_root", host=host,
                    clock=Clock({turn(6): lambda: touch(srv / "repo/sub/.env", "TOPSECRETCONTENT")}))
    assert error.facts["where"] == "inventory:repo" and len(host.runs) == 6


def test_a_secret_name_created_after_the_walk_and_before_the_cp_stops_on_the_staged_walk(srv, root, tmp_path):
    host = RecHost()
    host.before = lambda n, argv: touch(srv / "runtime/lanes/harness/.env", "TOPSECRETCONTENT") if n == 0 else None
    error = stopped(srv, root, tmp_path, "secret_path_in_root", host=host)
    assert error.facts["where"] == "staged:runtime-lanes"
    assert "TOPSECRETCONTENT" not in json.dumps(error.facts)


def test_a_refusing_aibox_loader_stops_before_any_source_listing(srv, root, tmp_path, tripwire, monkeypatch):
    def refuse(repo):
        raise Refused("aibox_data_origin_foreign", f"aibox_data does not come from {tmp_path}/elsewhere")

    monkeypatch.setattr(fr, "load_aibox_data", refuse)
    error = stopped(srv, root, tmp_path, "aibox_data_origin_foreign")
    assert "<path>" in error.detail
    assert not any(p.startswith(str(srv)) for p in tripwire["scandirs"] + tripwire["opens"])
    assert not (root / "seal").exists()


def test_an_entry_vanishing_between_listing_and_lstat_is_named(srv, root, tmp_path, monkeypatch):
    real = os.scandir
    done = []

    class Listing(list):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def scandir(path="."):
        if str(path) == str(srv / "repo") and not done:
            done.append(1)
            entries = Listing(real(path))
            os.unlink(srv / "repo/a.py")
            return entries
        return real(path)

    monkeypatch.setattr(os, "scandir", scandir)
    stopped(srv, root, tmp_path, "source_entry_vanished")


def test_a_root_removed_between_the_recheck_and_the_inventory_is_vanished(srv, root, tmp_path, monkeypatch):
    fr.load_aibox_data(REPO)
    import aibox_data.inventory as inv

    real = inv.scan_root
    done = []

    def scan(path):
        if not done:
            done.append(1)
            shutil.rmtree(path)
        return real(path)

    monkeypatch.setattr(inv, "scan_root", scan)
    stopped(srv, root, tmp_path, "inventory_runtime-lanes_vanished")


# ---- verify_seal ----

@pytest.fixture
def sealed(srv, root):
    facts, _host, _clock = go(srv, root)
    return root / "seal", facts


def test_verify_seal_passes_and_refuses_each_broken_rule(sealed):
    seal, facts = sealed
    meta = seal / "meta"
    assert fr.verify_seal(seal, facts, RUN8)["files"] == 18

    def refuses(rule, p5=None, run8=RUN8):
        with pytest.raises(Refused) as bad:
            fr.verify_seal(seal, facts if p5 is None else p5, run8)
        assert (bad.value.code, bad.value.detail) == ("seal_invalid", rule)

    refuses("complete_run8", run8="ffffffff")
    refuses("p5_not_ok", {**facts, "ok": False})
    refuses("p5_not_ok", {k: v for k, v in facts.items() if k != "ok"})
    refuses("complete_sha256_mismatch", {**facts, "complete_sha256": "0" * 64})
    (meta / "stray.txt").write_text("x")
    refuses("meta_names")
    (meta / "stray.txt").unlink()
    (meta / "repo.verify.json").write_text("{}")
    refuses("sha256_mismatch")
    complete = (meta / "complete.json").read_bytes()
    (meta / "complete.json").unlink()
    refuses("complete_missing")
    (meta / "complete.json").write_bytes(complete)
    os.rename(meta / "single.json", meta / "single.json.moved")
    (meta / "single.json").symlink_to(meta / "single.json.moved")
    refuses("meta_not_regular")


# ---- fresh interpreter ----

def test_acquire_runs_in_a_fresh_interpreter_without_the_guard_or_copies(srv, root):
    code = (
        "import json, sys\n"
        "from pathlib import Path\n"
        "from rehearsal import fileroots as fr, phase_p\n"
        "facts = fr.acquire(phase_p.Host(), Path(sys.argv[1]), Path(sys.argv[2]) / 'seal', '1a2b3c4d', repo=Path(sys.argv[3]))\n"
        "mods = {n: getattr(m, '__spec__', None) and m.__spec__.origin for n, m in sys.modules.items()\n"
        "        if n.split('.')[0] in ('aibox_data', 'codex_harness')}\n"
        "print(json.dumps({'ok': facts['ok'], 'guard': bool(getattr(sys, '_zeus_rebuild_provider_guard_installed', False)),\n"
        "                  'copies': 'rehearsal.copies' in sys.modules, 'run': 'rehearsal_compare_run' in sys.modules,\n"
        "                  'origins': sorted(mods.values(), key=str)}))\n")
    done = subprocess.run(["/usr/bin/python3", "-B", "-c", code, str(srv), str(root), str(REPO)], cwd=REPO / "compare",
                          capture_output=True, text=True, timeout=300)
    assert done.returncode == 0, done.stderr[-800:]
    seen = json.loads(done.stdout.strip().splitlines()[-1])
    assert (seen["ok"], seen["guard"], seen["copies"], seen["run"]) == (True, False, False, False)
    assert seen["origins"] and all(o and o.startswith(str(REPO)) for o in seen["origins"])
