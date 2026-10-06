"""RH-2 P5b-1: the single-descriptor snapshot read and `copy_once` of the guard-free `snapshot` module.

Layer: harness tooling tests. Expected results come from the task spec (rh2-p5b1-acquisition, What 1 and Expected
results): the recorded mtime/mode/size/sha256 describe the one inode and the bytes that were written even when a writer
rename-replaces the path (rename(2)); a vanished path is skipped; a symlink, a FIFO or a socket is refused by name; a copy
is a new 0600 file; `admit` runs before the first read. Inputs are SYNTHETIC trees under tmp_path; one gated audit hook
fails any open/scandir/listdir/subprocess argv naming the real `/srv/zeus` and carries the injection used to model a
rename-replace at the content open. FIFO cases are bounded by `signal.alarm` so a regression fails instead of hanging.
"""

from __future__ import annotations

import contextlib
import errno
import hashlib
import os
import signal
import socket
import stat
import sys

import pytest
from _layout import REPO

sys.path.insert(0, str(REPO / "compare"))
from rehearsal import Refused  # noqa: E402
from rehearsal import snapshot as sn  # noqa: E402

REAL = "/srv/zeus"
_state = {"active": False, "opens": [], "inject": None}


def _hook(event, args):
    if not _state["active"]:
        return
    if event == "subprocess.Popen":
        scanned = [str(a) for a in args[:3]]
    elif event in ("open", "os.scandir", "os.listdir"):
        scanned = [str(args[0])] if args else []
        if event == "open":
            _state["opens"].append(str(args[0]))
            inject = _state["inject"]
            if inject is not None:
                inject(str(args[0]))
    else:
        return
    if any(REAL in text for text in scanned):
        raise AssertionError(f"tripwire: {event} names the real {REAL}: {scanned}")


sys.addaudithook(_hook)


@pytest.fixture(autouse=True)
def tripwire():
    _state.update(active=True, opens=[], inject=None)
    yield _state
    _state["active"] = False


@contextlib.contextmanager
def bounded(seconds=20):
    """Fail (never hang) when the block blocks, e.g. a blocking open of a FIFO."""
    def stop(_signum, _frame):
        raise AssertionError("blocked: the read waited on a FIFO")

    old = signal.signal(signal.SIGALRM, stop)
    signal.alarm(seconds)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old)


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="ascii")


@pytest.fixture
def src(tmp_path):
    root = tmp_path / "src"
    write(root / "runtime/control/monitoring.json", "m0")
    write(root / "runtime/managed-fleet/heartbeat.json", "h0")
    write(root / "runtime/control/observations/health/a.json", "a0")
    write(root / "runtime/control/stable.json", "s0")
    (root / "managed-fleet").mkdir()
    return root


def once_at_open(name, action):
    """Run `action` once, at the first content open of a file called `name`, before that open proceeds."""
    done = []

    def inject(path):
        if os.path.basename(path) == name and not done:
            done.append(path)
            _state["inject"] = None
            action(path)

    _state["inject"] = inject
    return done


def replace_with(path, text, mtime_ns):
    tmp = path + ".new"
    with open(tmp, "w", encoding="ascii") as handle:
        handle.write(text)
    os.utime(tmp, ns=(mtime_ns, mtime_ns))
    os.chmod(tmp, 0o640)
    os.replace(tmp, path)


def test_a_rename_replace_at_the_content_open_is_recorded_as_the_bytes_written(src, tmp_path):
    marker = 1_700_000_000_123_456_789
    done = once_at_open("monitoring.json", lambda path: replace_with(path, "m-replaced-longer", marker))
    manifest = sn.snapshot_volatile(src, tmp_path / "dst", scan_roots=())
    assert done
    entry = next(e for e in manifest["files"] if e["path"] == "runtime/control/monitoring.json")
    written = (tmp_path / "dst/runtime/control/monitoring.json").read_bytes()
    assert written == b"m-replaced-longer"
    assert (entry["size"], entry["sha256"]) == (len(written), hashlib.sha256(written).hexdigest())
    assert entry["mtime_ns"] == marker and entry["mode"] == 0o640  # the replacement inode's, not the replaced one's


def test_a_vanished_declared_path_is_skipped_before_and_at_the_open(src, tmp_path):
    (src / "runtime/managed-fleet/heartbeat.json").unlink()
    done = once_at_open("monitoring.json", lambda path: os.unlink(path))
    manifest = sn.snapshot_volatile(src, tmp_path / "dst", scan_roots=())
    assert done
    paths = [e["path"] for e in manifest["files"]]
    assert "runtime/control/monitoring.json" not in paths and "runtime/managed-fleet/heartbeat.json" not in paths
    assert {"runtime/control/monitoring.json", "runtime/managed-fleet/heartbeat.json"} <= set(manifest["skipped"])
    assert not (tmp_path / "dst/runtime/control/monitoring.json").exists()


def test_a_path_swapped_for_a_symlink_at_the_open_is_refused_as_a_symlink(src, tmp_path):
    def swap(path):
        os.unlink(path)
        os.symlink(str(src / "runtime/control/stable.json"), path)

    once_at_open("monitoring.json", swap)
    with pytest.raises(Refused) as info:
        sn.snapshot_volatile(src, tmp_path / "dst", scan_roots=())
    assert info.value.code == "volatile_symlink" and str(src) not in info.value.detail


def test_copy_once_refuses_a_symlink_a_missing_path_and_a_non_regular_file(tmp_path):
    target = tmp_path / "real"
    write(target, "t")
    link = tmp_path / "link"
    link.symlink_to(target)
    with pytest.raises(Refused) as info:
        sn.copy_once(link, tmp_path / "out1")
    assert info.value.code == "volatile_symlink" and info.value.detail == "link"
    assert sn.copy_once(tmp_path / "absent", tmp_path / "out2") is None
    assert not (tmp_path / "out2").exists()
    with pytest.raises(Refused) as info:
        sn.copy_once(tmp_path, tmp_path / "out3")  # a directory
    assert info.value.code == "volatile_not_regular"


@pytest.mark.parametrize("where", ["declared", "health"])
def test_a_fifo_is_refused_not_regular_and_never_blocks(src, tmp_path, where):
    path = src / ("runtime/control/monitoring.json" if where == "declared" else "runtime/control/observations/health/f.fifo")
    if where == "declared":
        path.unlink()
    os.mkfifo(path)
    with bounded(), pytest.raises(Refused) as info:
        sn.snapshot_volatile(src, tmp_path / "dst", scan_roots=())
    assert info.value.code == "volatile_not_regular"
    with bounded(), pytest.raises(Refused) as info:
        sn.copy_once(path, tmp_path / "direct")
    assert info.value.code == "volatile_not_regular"


def test_a_socket_is_refused_not_regular(src, tmp_path, monkeypatch):
    monkeypatch.chdir(src / "runtime/control/observations/health")  # a short relative name fits sun_path
    listener = socket.socket(socket.AF_UNIX)
    try:
        listener.bind("s.sock")
        monkeypatch.chdir(tmp_path)
        with bounded(), pytest.raises(Refused) as info:
            sn.snapshot_volatile(src, tmp_path / "dst", scan_roots=())
        assert info.value.code == "volatile_not_regular"
    finally:
        listener.close()


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads a mode 000 file")
def test_an_unreadable_file_is_refused_unreadable(src, tmp_path):
    path = src / "runtime/control/monitoring.json"
    path.chmod(0)
    try:
        with pytest.raises(Refused) as info:
            sn.snapshot_volatile(src, tmp_path / "dst", scan_roots=())
        assert info.value.code == "volatile_unreadable" and info.value.detail == "runtime/control/monitoring.json"
    finally:
        path.chmod(0o644)


def test_a_metadata_read_failure_on_the_open_descriptor_is_volatile_unreadable_and_the_descriptor_is_closed(
        tmp_path, monkeypatch):
    """P5b round-1 F1: an fstat OSError after a successful open maps to the named refusal; the fd is not leaked."""
    source = tmp_path / "s.json"
    write(source, "payload")
    opened, real_open = [], os.open

    def recording_open(*args, **kw):
        opened.append(real_open(*args, **kw))
        return opened[-1]

    def failing_fstat(fd):
        raise OSError(errno.EIO, "injected")

    with monkeypatch.context() as patched:
        patched.setattr(os, "open", recording_open)
        patched.setattr(os, "fstat", failing_fstat)
        with pytest.raises(Refused) as info:
            sn.copy_once(source, tmp_path / "out.json", label="s.json")
    assert info.value.code == "volatile_unreadable" and info.value.detail == "s.json"
    assert not (tmp_path / "out.json").exists() and len(opened) == 1
    with pytest.raises(OSError) as closed:
        os.fstat(opened[0])
    assert closed.value.errno == errno.EBADF


def test_a_healthy_single_descriptor_read_still_returns_the_bytes_and_the_inode_facts(tmp_path):
    source = tmp_path / "s.json"
    write(source, "payload")
    data, info = sn._read_once(source, "s.json")
    assert data == b"payload" and info.st_size == 7


def test_copy_once_writes_a_new_0600_file_and_refuses_an_existing_target(tmp_path):
    source = tmp_path / "s.json"
    write(source, "payload")
    source.chmod(0o640)
    old = os.umask(0o022)
    try:
        got = sn.copy_once(source, tmp_path / "deep/er/out.json")
    finally:
        os.umask(old)
    out = tmp_path / "deep/er/out.json"
    assert out.read_text() == "payload" and stat.S_IMODE(out.stat().st_mode) == 0o600
    assert got["mode"] == 0o640 and got["size"] == 7 and set(got) == {"size", "mtime_ns", "mode", "read_at_ns", "sha256"}
    assert got["mtime_ns"] == source.stat().st_mtime_ns and got["sha256"] == hashlib.sha256(b"payload").hexdigest()
    with pytest.raises(Refused) as info:
        sn.copy_once(source, out)
    assert info.value.code == "seal_write_failed"
    assert out.read_text() == "payload"  # an existing target is never overwritten
    (tmp_path / "blocker").write_text("x")
    with pytest.raises(Refused) as info:
        sn.copy_once(source, tmp_path / "blocker/child")  # the parent cannot be created
    assert info.value.code == "seal_write_failed"


def test_every_entry_carries_the_declared_keys_including_mode(src, tmp_path):
    manifest = sn.snapshot_volatile(src, tmp_path / "dst", scan_roots=())
    assert manifest["files"]
    for entry in manifest["files"]:
        assert set(entry) == {"path", "size", "mtime_ns", "mode", "read_at_ns", "sha256"}
        assert entry["mode"] == stat.S_IMODE(os.stat(src / entry["path"]).st_mode)


def test_admit_is_called_once_with_the_sorted_paths_before_the_first_read(src, tmp_path):
    calls = []

    def admit(paths):
        calls.append((list(paths), [o for o in _state["opens"] if o.startswith(str(src))]))

    _state["opens"].clear()  # the fixture's own writes opened these files
    sn.snapshot_volatile(src, tmp_path / "dst", scan_roots=(), admit=admit)
    assert len(calls) == 1
    paths, opens_before = calls[0]
    assert paths == sorted(paths) and "runtime/control/observations/health/a.json" in paths
    assert "runtime/control/stable.json" not in paths  # only the paths about to be read
    assert opens_before == []


def test_an_admit_refusal_stops_before_any_source_read_or_copy(src, tmp_path):
    def admit(_paths):
        raise Refused("secret_path_in_root", "stop")

    _state["opens"].clear()
    with pytest.raises(Refused):
        sn.snapshot_volatile(src, tmp_path / "dst", scan_roots=(), admit=admit)
    assert not [o for o in _state["opens"] if o.startswith(str(src))]
    assert not (tmp_path / "dst").exists()


def test_volatile_undeclared_carries_every_changed_path(src, tmp_path):
    def rewrite():
        for name in ("a", "b", "c", "d", "e", "f", "g"):
            write(src / f"runtime/lanes/{name}.txt", name)

    (src / "runtime/lanes").mkdir()
    with pytest.raises(Refused) as info:
        sn.snapshot_volatile(src, tmp_path / "dst", scan_roots=("runtime",), during=rewrite)
    assert info.value.code == "volatile_undeclared"
    assert info.value.paths == [f"runtime/lanes/{n}.txt" for n in "abcdefg"]
    assert info.value.detail.startswith("7 path(s) changed outside the closed list: ")


def test_a_declared_dir_is_walked_and_a_symlink_inside_it_is_refused_by_name(src, tmp_path):
    (src / "runtime/control/observations/health/l.json").symlink_to(src / "runtime/control/stable.json")
    with pytest.raises(Refused) as info:
        sn.snapshot_volatile(src, tmp_path / "dst", scan_roots=())
    assert info.value.code == "volatile_symlink" and info.value.detail == "l.json"
