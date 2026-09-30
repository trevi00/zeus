"""Shared S7 scenario steps (`delivery.host_targets`): the M7 process host target, the service child it launches
and `GitHubDelivery` (DESIGN-s7 §2 row `delivery.host_targets`; TRACE-s7 §5.6), recorded BEFORE the move.

Eight case groups, each case labelled in the result:
- `switch`: the immutable descriptor replacement under the target guard.
- `guard`: the per-target lifecycle lock (serialization, the bounded refusal, another target, an unavailable fence).
- `start`: the one protected start (reconcile, classify, stop, retire, launch).
- `stop_reaping`: `stop` with the stop file, SIGTERM and pid reaping, and the `_reaped`/`_alive` primitives.
- `drain`: pause, running and work reports.
- `observe_identity`: the `observe` and `identity` projections.
- `service_child`: `serve`, `main` and `startup_receipt` in this process and as a child process.
- `github`: `GitHubDelivery` over a recording runner and workspace double.

**Fixtures (all LABELLED).**
- The runtime root is `<root>/runtime`, with `src/codex_harness` a symlink to the side's package directory, so
  a launched child runs the side's OWN `service`. The root has no `.git`. M7's `loaded_runtime` resolves the
  symlink, so the child's receipt names the resolved package and its parent, and its revision is empty: a valid
  receipt needs 40 hex. Every real child therefore reports a receipt that M7 itself reads as unreadable
  (`receipt_invalid`). This is recorded, and the cases that need a RECOGNIZABLE live instance (recognition,
  replacement, a fence lost during the stop, resumption) use a LABELLED sleeper process (`sys.executable -c`) and
  a hand-written valid receipt and launch record, exactly as a runtime would have written them.
- Real children are started by `ProcessHostTarget` itself (`python=sys.executable`, small `max_seconds`). Every
  case that starts a process stops it before it ends, and a sweep after each case fails the run on any live
  child (`live_children: 0` is recorded).
- `worker_image` of a real child's receipt is what its `settings()` reads (the inherited environment and the host
  `.env`), so it is recorded `<absent>` (`none`) or `<present>`. `profile_digest` comes from the packaged worker
  profile, which reads no environment, and is recorded literally.
- The GitHub runner and workspace are recording doubles: no `gh`, no git, no network.

`api` supplies `ProcessHostTarget`, `HostTargetBase`, `GitHubDelivery`, `serve`, `main`, `startup_receipt`, `reaped`,
`alive`, the file names `DESCRIPTOR_FILE`, `RECEIPT_FILE`, `STATE_FILE`, `WORK_FILE`, `STOP_FILE`, `PAUSE_FILE`,
`LOCK_DIR`, `validate_descriptor`, `descriptor_digest`, `consumption_verdict`, `DeliveryRefused`,
`LifecycleInterrupted`, `DESCRIPTOR_SCHEMA`, `RECEIPT_SCHEMA`, `ContractError`, `MergeRefused`, `PACKAGE_DIR` and
`advance(seconds)` (the fake clock, which only the bounded waits of the in-process cases need).

**Normalization is explicit, done here and identical on both sides:**
- `sys.executable` → `<python>`;
- this run's temporary root → `<root>`;
- the side's package directory, and anything that resolves through the symlink → `<package>`;
- the root `loaded_runtime` derives from that package (the package's parent, or its grandparent under a `src`
  directory), which a receipt reports as `runtime_root` → `<package-root>`;
- pids (the `pid` key) → `<pid>`, `instance_id` → `<instance>`, ISO times → `<time>`;
- a 64-hex descriptor digest the FIXTURE built → `<digest:NAME>`. A descriptor's digest covers its `root` path,
  which embeds the run's random temporary directory, so the value differs between runs while the identity does not.
  The NAME is the fixture's own label of the descriptor, never derived from the observed value.
Replacements run longest-first. Durations and waits are never recorded, and nothing else is masked.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace

PY = sys.executable
ISO = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?(\+00:00|Z)?$")
IMAGE = "zeus-worker@sha256:" + "d" * 64
PROFILE = "e" * 64
INSTANCE_A, INSTANCE_B = "a1" * 16, "b2" * 16
STAMP = "2026-01-01T00:00:00+00:00"
REVISIONS = {"one": "1" * 40, "two": "2" * 40, "three": "3" * 40}
PLAIN_SLEEPER = "import time; time.sleep(60)"
# A LABELLED sleeper that records the SIGTERM it receives and whether the stop file already existed then.
WATCHING_SLEEPER = (
    "import json, os, signal, sys, time\n"
    "marker, stop = sys.argv[1], sys.argv[2]\n"
    "def term(*_):\n"
    "    with open(marker, 'w') as f:\n"
    "        json.dump({'signal': 'TERM', 'stop_file_present': os.path.exists(stop)}, f)\n"
    "    os._exit(0)\n"
    "signal.signal(signal.SIGTERM, term)\n"
    "open(marker + '.ready', 'w').close()\n"
    "time.sleep(60)\n")
SMALL = 20  # max_seconds of every real child: a driver crash orphans it for at most this long


def proc_state(pid):
    try:
        return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
    except (OSError, IndexError):
        return None


def proc_alive(pid) -> bool:
    return proc_state(pid) not in (None, "Z", "X")


def child_facts(fx, pid) -> dict:
    """What the launched child really is, read from /proc: argv, cwd, stdio, session and the bound environment."""
    proc = Path(f"/proc/{pid}")
    environment = dict(item.split("=", 1) for item in
                       (proc / "environ").read_bytes().decode().split("\0") if "=" in item)
    first = environment.get("PYTHONPATH", "").split(os.pathsep)[0]
    return fx.n({
        "argv": (proc / "cmdline").read_bytes().decode().rstrip("\0").split("\0"),
        "cwd": os.readlink(proc / "cwd"),
        "stdio": [os.readlink(proc / "fd" / str(n)) for n in (0, 1, 2)],
        "own_session": os.getsid(pid) == pid,
        "pythonpath_first": first, "pythonpath_has_inherited_entries": len(environment["PYTHONPATH"].split(
            os.pathsep)) > 1,
        "zeus_repository": environment.get("ZEUS_REPOSITORY"),
        "harness_repository": environment.get("HARNESS_REPOSITORY")})


def until(predicate, seconds=30.0) -> bool:
    deadline = time.perf_counter() + seconds
    while time.perf_counter() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


class Fixture:
    """One run: the temporary root, the labelled runtime root, the digest labels and every pid started."""

    def __init__(self, api, base: Path):
        self.api, self.base = api, base
        self.runtime = base / "runtime"
        (self.runtime / "src").mkdir(parents=True)
        (self.runtime / "src" / "codex_harness").symlink_to(api.PACKAGE_DIR)
        self.bare = base / "bare-root"
        self.bare.mkdir()
        self.children, self.sleepers, self.popens, self.digests, self.serial = set(), set(), [], {}, 0
        loaded = Path(api.PACKAGE_DIR).resolve()
        loaded_root = loaded.parent.parent if loaded.parent.name == "src" else loaded.parent
        pairs = [(str(loaded), "<package>"), (str(api.PACKAGE_DIR), "<package>"), (PY, "<python>"),
                 (str(loaded_root), "<package-root>"), (str(base), "<root>")]
        self.substitutions = sorted(pairs, key=lambda pair: -len(pair[0]))

    # --- normalization -----------------------------------------------------------------------------
    def n(self, value):
        if isinstance(value, dict):
            out = {}
            for key, item in value.items():
                if key == "pid" and type(item) is int:
                    out[key] = "<pid>"
                elif key == "instance_id" and isinstance(item, str):
                    out[key] = "<instance>"
                elif key == "worker_image" and isinstance(item, str) and item != IMAGE:
                    out[key] = "<absent>" if item == "none" else "<present>"
                else:
                    out[self.n(key)] = self.n(item)
            return out
        if isinstance(value, (list, tuple)):
            return [self.n(item) for item in value]
        if isinstance(value, Path):
            return self.n(str(value))
        if isinstance(value, str):
            if ISO.match(value):
                return "<time>"
            if value in self.digests:
                return "<digest:" + self.digests[value] + ">"
            for old, new in self.substitutions:
                value = value.replace(old, new)
            return value
        return value

    def attempt(self, call):
        """The outcome of one call: what it returned, or the exception type and its reason fields."""
        try:
            return {"returned": self.n(call())}
        except SystemExit as exc:
            return {"exit": exc.code}
        except Exception as exc:  # the refusal is the characterized result
            view = {"type": type(exc).__name__, "message": self.n(str(exc))}
            for name in ("reason_code", "field", "effect"):
                if getattr(exc, name, None) is not None:
                    view[name] = getattr(exc, name)
            if getattr(exc, "cause", None) is not None:
                view["cause"] = type(exc.cause).__name__
            return {"raised": view}

    # --- targets, descriptors, receipts ------------------------------------------------------------
    def host(self, **kwargs):
        return self.api.ProcessHostTarget(python=PY, max_seconds=SMALL, **kwargs)

    def target(self, name: str, root=None) -> dict:
        self.serial += 1
        state = self.base / "states" / f"{self.serial:03d}-{name}"
        return {"target_id": name, "state_dir": str(state), "root": str(root or self.runtime)}

    def descriptor(self, target, label, revision, *, predecessor=None, root=None) -> dict:
        document = {"schema": self.api.DESCRIPTOR_SCHEMA, "target_id": target["target_id"],
                    "root": str(root or target["root"]), "revision": REVISIONS[revision], "worker_image": IMAGE,
                    "profile_digest": PROFILE, "predecessor": predecessor}
        self.digests[self.api.descriptor_digest(document)] = label
        return document

    def digest(self, descriptor) -> str:
        return self.api.descriptor_digest(descriptor)

    def receipt_for(self, descriptor, pid, instance=INSTANCE_A) -> dict:
        return {"schema": self.api.RECEIPT_SCHEMA, "target_id": descriptor["target_id"],
                "instance_id": instance, "pid": pid, "started_at": STAMP, "runtime_root": descriptor["root"],
                "module_root": descriptor["root"] + "/src/codex_harness",
                "descriptor_sha256": self.digest(descriptor), "revision": descriptor["revision"],
                "worker_image": descriptor["worker_image"], "profile_digest": descriptor["profile_digest"]}

    def state(self, target, name) -> Path:
        return Path(target["state_dir"]) / name

    def write(self, target, name, document) -> None:
        path = self.state(target, name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(document if isinstance(document, str) else json.dumps(document, sort_keys=True),
                        encoding="utf-8")

    def read(self, target, name):
        try:
            return json.loads(self.state(target, name).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def listing(self, target) -> dict:
        out = {}
        directory = Path(target["state_dir"])
        for path in sorted(directory.iterdir()) if directory.is_dir() else []:
            if path.is_dir():
                out[path.name] = "<dir>"
                continue
            text = path.read_text(encoding="utf-8")
            try:
                out[path.name] = self.n(json.loads(text))
            except ValueError:
                out[path.name] = {"text": self.n(text)}
        return out

    # --- processes -----------------------------------------------------------------------------------
    def launched(self, target):
        """Track, as a child the TARGET started, the pid of the launch record and of the receipt."""
        for name in ("controller-state.json", "startup-receipt.json"):
            document = self.read(target, name)
            if isinstance(document, dict) and type(document.get("pid")) is int:
                self.children.add(document["pid"])

    def sleeper(self, *args, code=PLAIN_SLEEPER) -> int:
        process = subprocess.Popen([PY, "-c", code, *args], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL, start_new_session=True)
        self.popens.append(process)
        self.sleepers.add(process.pid)
        return process.pid

    def dead_pid(self) -> int:
        process = subprocess.Popen([PY, "-c", "pass"])
        process.wait(timeout=60)
        return process.pid

    def plant(self, target, descriptor, *, live=True, receipt=True, launch=True, instance=INSTANCE_A,
              descriptor_file=True) -> dict:
        """LABELLED: the files a runtime and a prior launch would have left, with a sleeper as the instance."""
        pid = self.sleeper() if live else self.dead_pid()
        launched = {"pid": pid, "started_at": STAMP, "descriptor_sha256": self.digest(descriptor)}
        if descriptor_file:
            self.write(target, self.api.DESCRIPTOR_FILE, descriptor)
        written = self.receipt_for(descriptor, pid, instance)
        if receipt:
            self.write(target, self.api.RECEIPT_FILE, written)
        if launch:
            self.write(target, self.api.STATE_FILE, launched)
        return {"pid": pid, "receipt": written, "launch": launched}

    def authority(self, descriptor, planted, *, instance=INSTANCE_A) -> dict:
        return {"descriptor_sha256": self.digest(descriptor), "instance_id": instance,
                "launch": planted["launch"]}

    def await_receipt(self, target):
        def appeared():
            document = self.read(target, self.api.RECEIPT_FILE)
            return isinstance(document, dict) and "pid" in document

        assert until(appeared, 60), "the launched child wrote no startup receipt"
        self.launched(target)
        return self.read(target, self.api.RECEIPT_FILE)

    def real_start(self, name, host=None):
        """A clean start of a REAL child by the target itself, and its own receipt."""
        host = host or self.host()
        target = self.target(name)
        first = self.descriptor(target, name + "-1", "one")
        host.switch(target, first, expected=None)
        started = host.start(target, first, authorize=lambda: None)
        self.launched(target)
        return host, target, first, started, self.await_receipt(target)

    def sweep(self, case) -> int:
        """End the labelled sleepers, and fail the run if a child the TARGET started is still alive."""
        leaked = [pid for pid in sorted(self.children) if proc_alive(pid)]
        for pid in sorted(self.children | self.sleepers):
            if proc_alive(pid):
                with contextlib.suppress(OSError):
                    os.kill(pid, signal.SIGKILL)
        for process in self.popens:
            with contextlib.suppress(Exception):
                process.wait(timeout=30)
        for pid in sorted(self.children | self.sleepers):
            assert until(lambda: not proc_alive(pid), 30)
            self.api.alive(pid)
        self.children.clear()
        self.sleepers.clear()
        self.popens.clear()
        assert not leaked, f"case {case} left live children"
        return len(leaked)


@contextlib.contextmanager
def ticking(api):
    """`determinism.install` freezes `time.monotonic`: advance the fake clock while a bounded wait runs."""
    stop = threading.Event()

    def run():
        while not stop.is_set():
            api.advance(0.1)
            time.sleep(0.05)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join(10)


def stale_fence(after=0):
    """A LABELLED injected fence: it authorizes `after` calls, then reports the lease it lost."""
    def authorize():
        authorize.calls += 1
        if authorize.calls > after:
            raise ContractErrorHolder.error("injected: stale release controller")

    authorize.calls = 0
    return authorize


class ContractErrorHolder:
    error = RuntimeError  # replaced by `run` with the side's ContractError


# ======================================================================================================
# 1. switch
# ======================================================================================================
def group_switch(fx):
    api, out = fx.api, {}
    host = fx.host()

    target = fx.target("switch-first")
    d1 = fx.descriptor(target, "first", "one", root="/fixture/root")
    d2 = fx.descriptor(target, "second", "two", predecessor=fx.digest(d1), root="/fixture/root")
    out["first_over_no_predecessor"] = {
        "switch": fx.attempt(lambda: host.switch(target, d1, expected=None)),
        "files": fx.listing(target), "current_is_first": host.current(target) == d1}
    out["exact_predecessor_written"] = {
        "switch": fx.attempt(lambda: host.switch(target, d2, expected=fx.digest(d1))),
        "files": fx.listing(target), "current_is_second": host.current(target) == d2}
    before = fx.state(target, api.DESCRIPTOR_FILE).read_bytes()
    out["wrong_predecessor"] = {
        "switch": fx.attempt(lambda: host.switch(target, d1, expected=fx.digest(d1))),
        "unchanged": fx.state(target, api.DESCRIPTOR_FILE).read_bytes() == before,
        "lock_released": not fx.state(target, api.LOCK_DIR).exists(), "files": fx.listing(target)}
    out["none_expected_over_existing"] = {
        "switch": fx.attempt(lambda: host.switch(target, d1, expected=None)),
        "unchanged": fx.state(target, api.DESCRIPTOR_FILE).read_bytes() == before}

    fence = stale_fence()
    over_none = fx.target("switch-fence-none")
    out["refusing_fence_over_no_predecessor"] = {
        "switch": fx.attempt(lambda: host.switch(over_none, fx.descriptor(over_none, "fenced", "one"),
                                                 expected=None, authorize=fence)),
        "fence_calls": fence.calls, "files": fx.listing(over_none),
        "lock_released": not fx.state(over_none, api.LOCK_DIR).exists()}
    fence = stale_fence()
    out["refusing_fence_over_existing"] = {
        "switch": fx.attempt(lambda: host.switch(target, d1, expected=fx.digest(d2), authorize=fence)),
        "fence_calls": fence.calls, "unchanged_second": host.current(target) == d2,
        "lock_released": not fx.state(target, api.LOCK_DIR).exists()}
    fence = stale_fence(after=1)
    out["fence_asked_before_the_comparison"] = {
        "switch": fx.attempt(lambda: host.switch(target, d1, expected=fx.digest(d1), authorize=fence)),
        "fence_calls": fence.calls}

    malformed = fx.target("switch-malformed")
    fx.write(malformed, api.DESCRIPTOR_FILE, "not json")
    wrong = dict(fx.descriptor(malformed, "malformed", "one"), revision="nothex")
    fx.write(malformed, "other.json", {})
    out["unreadable_current_is_none"] = {
        "current_malformed": host.current(malformed),
        "switch_expected_none": fx.attempt(lambda: host.switch(malformed, d1, expected=None)),
        "files": fx.listing(malformed)}
    fx.write(malformed, api.DESCRIPTOR_FILE, wrong)
    out["invalid_current_is_none"] = {"current": host.current(malformed)}
    return out


# ======================================================================================================
# 2. guard
# ======================================================================================================
def group_guard(fx):
    api, out = fx.api, {}

    # Two operations on one target serialize: the second enters only after the first has left.
    host, other = fx.host(), fx.host()
    target = fx.target("guard-serial", root="/fixture/root")
    descriptor = fx.descriptor(target, "serial-first", "one", root="/fixture/root")
    second = fx.descriptor(target, "serial-second", "two", predecessor=fx.digest(descriptor), root="/fixture/root")
    events, inside, release = [], threading.Event(), threading.Event()

    def hold():
        events.append("holder:enter")
        inside.set()
        release.wait(60)
        events.append("holder:exit")

    def follow():
        events.append("follower:enter")

    results = {}
    holder = threading.Thread(target=lambda: results.update(holder=fx.attempt(
        lambda: host.switch(target, descriptor, expected=None, authorize=hold))))
    follower = threading.Thread(target=lambda: results.update(follower=fx.attempt(
        lambda: other.switch(target, second, expected=fx.digest(descriptor), authorize=follow))))
    holder.start()
    assert inside.wait(60)
    follower.start()
    time.sleep(0.4)
    events.append("lock_present_while_held:" + str(fx.state(target, api.LOCK_DIR).is_dir()))
    release.set()
    holder.join(60)
    follower.join(60)
    out["two_operations_serialize"] = {
        "events": events, "results": results, "files": fx.listing(target),
        "current_is_second": host.current(target) == second}

    # A contender with a short bounded wait is refused while the holder is inside; another target is free.
    first = fx.target("guard-held", root="/fixture/root")
    elsewhere = fx.target("guard-other", root="/fixture/root")
    held = fx.descriptor(first, "held", "one", root="/fixture/root")
    free = fx.descriptor(elsewhere, "elsewhere", "one", root="/fixture/root")
    inside, release, results = threading.Event(), threading.Event(), {}

    def barrier():
        inside.set()
        release.wait(60)

    holder = threading.Thread(target=lambda: results.update(holder=fx.attempt(
        lambda: fx.host().switch(first, held, expected=None, authorize=barrier))))
    holder.start()
    assert inside.wait(60)
    contender = fx.host(lock_timeout=0.3)
    with ticking(api):
        refused = fx.attempt(lambda: contender.start(first, held, authorize=lambda: None))
    free_result = fx.attempt(lambda: fx.host().switch(elsewhere, free, expected=None))
    during = {"files_held_target": fx.listing(first), "files_other_target": fx.listing(elsewhere)}
    release.set()
    holder.join(60)
    out["contender_refused_and_another_target_free"] = {
        "contender": refused, "another_target": free_result, "during_hold": during,
        "holder": results["holder"], "after_release": fx.listing(first)}

    # An unavailable authority stops the lifecycle before any effect; the real child stays as it was.
    host, target, first_descriptor, _, receipt = fx.real_start("guard-unavailable")
    pid = fx.read(target, api.STATE_FILE)["pid"]
    successor = fx.descriptor(target, "unavailable-2", "two", predecessor=fx.digest(first_descriptor))

    def unavailable():
        raise ConnectionError("injected: the fence cannot be read")

    files = fx.listing(target)
    out["unavailable_authority_before_any_effect"] = {
        "switch": fx.attempt(lambda: host.switch(target, successor, expected=fx.digest(first_descriptor),
                                                 authorize=unavailable)),
        "start": fx.attempt(lambda: host.start(target, first_descriptor, authorize=unavailable)),
        "drain": fx.attempt(lambda: host.drain(target, authorize=unavailable)),
        "descriptor_unchanged": host.current(target) == first_descriptor,
        "child_alive": proc_alive(pid), "files_unchanged": fx.listing(target) == files,
        "no_stop_no_pause_no_lock": not any(fx.state(target, name).exists() for name in
                                            ("stop.json", "pause.json", api.LOCK_DIR)),
        "receipt_instance_unchanged": fx.read(target, api.RECEIPT_FILE)["instance_id"] == receipt["instance_id"]}
    host.stop(target)
    return out


# ======================================================================================================
# 3. start / recognize / replace
# ======================================================================================================
def group_start(fx):
    api, out = fx.api, {}

    # A clean start of a real child, and what its own receipt says (LABELLED: the runtime root is the link).
    host = fx.host()
    target = fx.target("start-clean")
    d1 = fx.descriptor(target, "clean-1", "one")
    host.switch(target, d1, expected=None)
    before = fx.listing(target)
    started = fx.attempt(lambda: host.start(target, d1, authorize=lambda: None))
    fx.launched(target)
    receipt = fx.await_receipt(target)
    pid = receipt["pid"]
    facts = child_facts(fx, pid)
    out["clean_start_real_child"] = {
        "listing_before": before, "start": started,
        "launch_pid_is_child": fx.read(target, api.STATE_FILE)["pid"] == pid,
        "launch_record": fx.n(fx.read(target, api.STATE_FILE)),
        "child": facts,
        "receipt": fx.n(receipt),
        "receipt_is_this_sides_package": receipt["module_root"] == str(Path(api.PACKAGE_DIR).resolve()),
        "consumption_verdict": api.consumption_verdict(d1, receipt),
        "observe": fx.n(host.observe(target)), "child_alive": proc_alive(pid),
        "listing_after": fx.listing(target)}
    stopped = fx.attempt(lambda: host.stop(target))
    out["clean_start_real_child"].update(
        stop=stopped, child_alive_after_stop=proc_alive(pid), listing_after_stop=fx.listing(target))
    host.stop(target)

    # A restart over the real live child: M7 reads its receipt as unreadable (revision empty) and refuses.
    host, target, d1, _, receipt = fx.real_start("start-restart")
    pid = receipt["pid"]
    launch = fx.read(target, api.STATE_FILE)
    files = fx.listing(target)
    successor = fx.descriptor(target, "restart-2", "two", predecessor=fx.digest(d1))
    restart = fx.attempt(lambda: host.start(target, d1, authorize=lambda: None))
    host.switch(target, successor, expected=fx.digest(d1))
    replace = fx.attempt(lambda: host.start(target, successor, authorize=lambda: None, replaces={
        "descriptor_sha256": fx.digest(d1), "instance_id": receipt["instance_id"], "launch": launch}))
    out["restart_over_real_child_is_unreadable"] = {
        "restart_same": restart, "replace_with_authority": replace, "child_alive": proc_alive(pid),
        "receipt_instance_unchanged": fx.read(target, api.RECEIPT_FILE)["instance_id"] == receipt["instance_id"],
        "launch_unchanged": fx.read(target, api.STATE_FILE) == launch, "no_stop_file": not fx.state(
            target, "stop.json").exists(), "files_before_switch": files,
        "lock_released": not fx.state(target, api.LOCK_DIR).exists()}
    out["real_child_recognition"] = {
        "unreachable": "a real child's receipt names the resolved package and an empty revision (the root has no "
                       ".git), which M7 reads as receipt_invalid; recognition and replacement are recorded over "
                       "a LABELLED sleeper and a hand-written receipt below",
        "consumption_reason": api.consumption_verdict(d1, receipt)["reason_code"],
        "receipt_revision": receipt["revision"]}
    host.stop(target)

    # A runtime root without an importable harness is refused before any process exists.
    host, bare = fx.host(), fx.target("start-bare", root=fx.bare)
    bare_descriptor = fx.descriptor(bare, "bare", "one", root=fx.bare)
    host.switch(bare, bare_descriptor, expected=None)
    out["runtime_root_unavailable"] = {
        "start": fx.attempt(lambda: host.start(bare, bare_descriptor, authorize=lambda: None)),
        "files": fx.listing(bare)}

    # A foreign descriptor (or none) on the target refuses before anything.
    foreign = fx.target("start-foreign")
    mine = fx.descriptor(foreign, "foreign-mine", "one")
    theirs = fx.descriptor(foreign, "foreign-theirs", "two")
    out["descriptor_foreign"] = {
        "no_descriptor": fx.attempt(lambda: host.start(foreign, mine)),
        "after_theirs": None}
    host.switch(foreign, theirs, expected=None)
    planted = fx.plant(foreign, theirs)
    out["descriptor_foreign"]["after_theirs"] = fx.attempt(lambda: host.start(foreign, mine))
    out["descriptor_foreign"].update(child_alive=proc_alive(planted["pid"]),
                                     no_stop_file=not fx.state(foreign, "stop.json").exists(),
                                     files=fx.listing(foreign))

    # A stale controller (its fence lost) stops nothing and unlinks nothing; the real child survives.
    host, target, d1, _, receipt = fx.real_start("start-stale")
    pid = receipt["pid"]
    successor = fx.descriptor(target, "stale-2", "two", predecessor=fx.digest(d1))
    host.switch(target, successor, expected=fx.digest(d1))
    fence = stale_fence()
    files = fx.listing(target)
    out["stale_controller_real_child"] = {
        "start": fx.attempt(lambda: host.start(target, successor, authorize=fence)),
        "fence_calls": fence.calls, "child_alive": proc_alive(pid), "files_unchanged": fx.listing(target) == files,
        "no_stop_file": not fx.state(target, "stop.json").exists(),
        "lock_released": not fx.state(target, api.LOCK_DIR).exists()}
    host.stop(target)

    # RECOGNIZE: the live matching instance is kept (LABELLED sleeper with a hand-written valid receipt).
    target = fx.target("start-recognize", root=fx.runtime)
    d1 = fx.descriptor(target, "recognize-1", "one")
    planted = fx.plant(target, d1)
    files = fx.listing(target)
    out["recognizes_the_live_matching_instance"] = {
        "consumption_reason": api.consumption_verdict(d1, planted["receipt"])["reason_code"],
        "start": fx.attempt(lambda: host.start(target, d1, authorize=lambda: None)),
        "again": fx.attempt(lambda: host.start(target, d1, authorize=lambda: None)),
        "launch_is_the_planted_record": None,
        "child_alive": proc_alive(planted["pid"]), "no_stop_file": not fx.state(target, "stop.json").exists(),
        "files_unchanged": fx.listing(target) == files}
    recognized = host.start(target, d1)
    out["recognizes_the_live_matching_instance"]["launch_is_the_planted_record"] = (
        recognized["launch"] == planted["launch"] and recognized["recovered"] is True
        and recognized["started"] is False)

    # A foreign or unauthorized live instance is refused BEFORE any stop.
    target = fx.target("start-unauthorized", root=fx.runtime)
    d1 = fx.descriptor(target, "unauth-1", "one")
    d2 = fx.descriptor(target, "unauth-2", "two", predecessor=fx.digest(d1))
    other = fx.descriptor(target, "unauth-other", "three")
    planted = fx.plant(target, d1)
    host.switch(target, d2, expected=fx.digest(d1))
    files = fx.listing(target)
    out["live_instance_not_authorized_refused_before_stop"] = {
        "no_authority": fx.attempt(lambda: host.start(target, d2, authorize=lambda: None)),
        "another_descriptors_authority": fx.attempt(lambda: host.start(target, d2, replaces={
            "descriptor_sha256": fx.digest(other), "instance_id": INSTANCE_A, "launch": None})),
        "another_instance_authority": fx.attempt(lambda: host.start(target, d2, replaces={
            "descriptor_sha256": fx.digest(d1), "instance_id": INSTANCE_B, "launch": None})),
        "malformed_authority": fx.attempt(lambda: host.start(target, d2, replaces={
            "descriptor_sha256": "nothex", "instance_id": None, "launch": None})),
        "child_alive": proc_alive(planted["pid"]), "no_stop_file": not fx.state(target, "stop.json").exists(),
        "files_unchanged": fx.listing(target) == files}

    # An unidentified live instance (launch record, no receipt) and unknown absence are refused.
    target = fx.target("start-unidentified", root=fx.runtime)
    d1 = fx.descriptor(target, "unident-1", "one")
    planted = fx.plant(target, d1, receipt=False)
    out["unidentified_live_instance_refused"] = {
        "start": fx.attempt(lambda: host.start(target, d1, authorize=lambda: None)),
        "child_alive": proc_alive(planted["pid"]), "no_stop_file": not fx.state(target, "stop.json").exists()}
    target = fx.target("start-absence-unknown", root=fx.runtime)
    d1 = fx.descriptor(target, "absence-1", "one")
    foreign_launch = {"pid": fx.dead_pid(), "started_at": STAMP, "descriptor_sha256": "f" * 64}
    fx.write(target, api.DESCRIPTOR_FILE, d1)
    fx.write(target, api.STATE_FILE, foreign_launch)
    out["dead_foreign_launch_absence_unknown"] = {
        "start": fx.attempt(lambda: host.start(target, d1, authorize=lambda: None)),
        "no_stop_file": not fx.state(target, "stop.json").exists()}

    # REPLACE the authorized predecessor: stop (SIGTERM), retire, launch a real child.
    target = fx.target("start-replace", root=fx.runtime)
    d1 = fx.descriptor(target, "replace-1", "one")
    d2 = fx.descriptor(target, "replace-2", "two", predecessor=fx.digest(d1))
    planted = fx.plant(target, d1)
    host.switch(target, d2, expected=fx.digest(d1))
    authority = fx.authority(d1, planted)
    replaced = fx.attempt(lambda: host.start(target, d2, authorize=lambda: None, replaces=authority))
    fx.launched(target)
    new_receipt = fx.await_receipt(target)
    out["replaces_the_authorized_predecessor"] = {
        "start": replaced, "previous_alive": proc_alive(planted["pid"]),
        "new_child_alive": proc_alive(new_receipt["pid"]),
        "new_instance_differs": new_receipt["instance_id"] != INSTANCE_A,
        "new_receipt_describes_d2": new_receipt["descriptor_sha256"] == fx.digest(d2),
        "launch_record": fx.n(fx.read(target, api.STATE_FILE)),
        "listing": fx.listing(target)}
    host.stop(target)

    # The fence lost during the bounded stop: the effect is preserved, nothing is started; a successor resumes.
    target = fx.target("start-fence-lost", root=fx.runtime)
    d1 = fx.descriptor(target, "lost-1", "one")
    d2 = fx.descriptor(target, "lost-2", "two", predecessor=fx.digest(d1))
    planted = fx.plant(target, d1)
    host.switch(target, d2, expected=fx.digest(d1))
    authority = fx.authority(d1, planted)
    recorded = fx.read(target, api.STATE_FILE)
    fence = stale_fence(after=1)
    interrupted = fx.attempt(lambda: host.start(target, d2, authorize=fence, replaces=authority))
    kept = {"previous_alive": proc_alive(planted["pid"]),
            "receipt_kept": fx.read(target, api.RECEIPT_FILE) == planted["receipt"],
            "launch_kept": fx.read(target, api.STATE_FILE) == recorded,
            "stop_file": fx.n(fx.read(target, "stop.json")),
            "no_new_launch": fx.read(target, api.STATE_FILE)["pid"] == planted["pid"],
            "lock_released": not fx.state(target, api.LOCK_DIR).exists(), "fence_calls": fence.calls}
    resumed = fx.attempt(lambda: fx.host().start(target, d2, authorize=lambda: None, replaces=authority))
    fx.launched(target)
    new_receipt = fx.await_receipt(target)
    out["fence_lost_during_the_bounded_stop"] = {
        "start": interrupted, "kept": kept, "successor_resumes": resumed,
        "new_receipt_describes_d2": new_receipt["descriptor_sha256"] == fx.digest(d2),
        "listing": fx.listing(target)}
    host.stop(target)

    # A known dead instance of this delivery (valid receipt, dead pid) is resumed; nothing is recognized.
    target = fx.target("start-resume-dead", root=fx.runtime)
    d1 = fx.descriptor(target, "resume-1", "one")
    planted = fx.plant(target, d1, live=False)
    resumed = fx.attempt(lambda: host.start(target, d1, authorize=lambda: None))
    fx.launched(target)
    new_receipt = fx.await_receipt(target)
    out["resumes_a_known_dead_instance"] = {
        "start": resumed, "new_instance_differs": new_receipt["instance_id"] != INSTANCE_A,
        "listing": fx.listing(target)}
    host.stop(target)
    return out


# ======================================================================================================
# 4. stop and reaping
# ======================================================================================================
def group_stop_reaping(fx):
    api, out = fx.api, {}
    host = fx.host()

    # stop of a running child: the stop file first, then SIGTERM, then the child is reaped.
    target = fx.target("stop-running")
    marker = fx.base / "stop-running.term"
    pid = fx.sleeper(str(marker), fx.state(target, "stop.json").as_posix(), code=WATCHING_SLEEPER)
    assert until(lambda: Path(str(marker) + ".ready").exists(), 60)
    fx.write(target, api.STATE_FILE, {"pid": pid, "started_at": STAMP, "descriptor_sha256": "0" * 64})
    stopped = fx.attempt(lambda: host.stop(target))
    out["stop_running_sleeper"] = {
        "stop": stopped, "stop_file": fx.n(fx.read(target, "stop.json")),
        "term_seen": json.loads(marker.read_text()) if marker.exists() else None,
        "gone": not proc_alive(pid), "not_a_zombie": proc_state(pid) is None,
        "running_after": host.running(target)}

    host, target, d1, _, receipt = fx.real_start("stop-real")
    pid = receipt["pid"]
    stopped = host.stop(target)
    out["stop_real_child"] = {
        "stopped": stopped["stopped"], "pid_is_the_launched_child": stopped["pid"] == pid,
        "stop_file": fx.n(fx.read(target, "stop.json")), "gone": not proc_alive(pid),
        "not_a_zombie": proc_state(pid) is None, "receipt_kept": fx.read(target, api.RECEIPT_FILE) == receipt}

    host = fx.host()
    target = fx.target("stop-no-pid")
    out["stop_with_no_recorded_pid"] = {"stop": fx.attempt(lambda: host.stop(target)), "files": fx.listing(target)}
    target = fx.target("stop-dead-pid")
    fx.write(target, api.STATE_FILE, {"pid": fx.dead_pid(), "started_at": STAMP, "descriptor_sha256": "0" * 64})
    out["stop_with_a_dead_recorded_pid"] = {"stop": fx.attempt(lambda: host.stop(target)),
                                            "files": fx.listing(target)}
    target = fx.target("stop-bad-pid")
    fx.write(target, api.STATE_FILE, {"pid": "12", "started_at": STAMP, "descriptor_sha256": "0" * 64})
    out["stop_with_a_non_integer_recorded_pid"] = {"stop": fx.attempt(lambda: host.stop(target))}

    # `_reaped` / `_alive` over this process's own children (never call poll/wait: both would reap).
    def exited_child():
        process = subprocess.Popen([PY, "-c", "pass"])
        fx.popens.append(process)
        assert until(lambda: proc_state(process.pid) == "Z", 60)
        return process.pid

    pid = exited_child()
    zombie = proc_state(pid)
    out["alive_reaps_an_exited_child"] = {
        "state_before": zombie, "alive": api.alive(pid), "gone_after": proc_state(pid) is None,
        "reaped_again": api.reaped(pid), "alive_again": api.alive(pid)}
    pid = exited_child()
    out["reaped_collects_an_exited_child"] = {
        "state_before": proc_state(pid), "reaped": api.reaped(pid), "gone_after": proc_state(pid) is None,
        "reaped_again": api.reaped(pid), "alive_after": api.alive(pid)}
    pid = fx.sleeper()
    out["a_running_child_is_alive_and_not_reaped"] = {
        "reaped": api.reaped(pid), "alive": api.alive(pid), "still_running": proc_alive(pid)}
    parent = os.getppid()
    out["a_pid_that_is_not_a_child"] = {"reaped": api.reaped(parent), "alive": api.alive(parent),
                                        "reaped_self": api.reaped(os.getpid()), "alive_self": api.alive(os.getpid())}
    out["alive_of_values_that_are_not_pids"] = {
        repr(value): api.alive(value) for value in (None, 0, -5, "7", True, 3.0)}
    out["alive_of_a_collected_pid"] = {"alive": api.alive(fx.dead_pid())}
    return out


# ======================================================================================================
# 5. drain
# ======================================================================================================
def group_drain(fx):
    api, out = fx.api, {}
    host = fx.host()

    def with_running(name, work=None, *, raw=None):
        target = fx.target(name)
        pid = fx.sleeper()
        fx.write(target, api.STATE_FILE, {"pid": pid, "started_at": STAMP, "descriptor_sha256": "0" * 64})
        if raw is not None:
            fx.write(target, api.WORK_FILE, raw)
        elif work is not None:
            fx.write(target, api.WORK_FILE, work)
        return target

    target = fx.target("drain-none")
    out["no_running_service_is_drained"] = {"drain": fx.attempt(lambda: host.drain(target)),
                                            "files": fx.listing(target)}
    target = fx.target("drain-none-stale-work")
    fx.write(target, api.WORK_FILE, {"active": 5, "unconfirmed": 2})
    out["no_running_service_ignores_its_work_report"] = {"drain": fx.attempt(lambda: host.drain(target))}
    target = with_running("drain-idle", {"active": 0, "unconfirmed": 0, "at": STAMP})
    out["running_with_active_zero"] = {"drain": fx.attempt(lambda: host.drain(target)), "files": fx.listing(target)}
    target = with_running("drain-no-work")
    out["running_without_a_work_report"] = {"drain": fx.attempt(lambda: host.drain(target)),
                                            "files": fx.listing(target)}
    target = with_running("drain-malformed", raw="not json")
    out["running_with_a_malformed_work_report"] = {"drain": fx.attempt(lambda: host.drain(target))}
    target = with_running("drain-active", {"active": 2, "unconfirmed": 1})
    out["running_with_active_work"] = {"drain": fx.attempt(lambda: host.drain(target))}
    target = with_running("drain-unconfirmed", {"active": 0, "unconfirmed": 3})
    out["running_idle_with_unconfirmed_work"] = {"drain": fx.attempt(lambda: host.drain(target))}
    target = with_running("drain-missing-keys", {})
    out["running_with_an_empty_work_report"] = {"drain": fx.attempt(lambda: host.drain(target))}

    target = with_running("drain-stale", {"active": 0, "unconfirmed": 0})
    fence = stale_fence()
    out["a_stale_authorize_pauses_nothing"] = {
        "drain": fx.attempt(lambda: host.drain(target, authorize=fence)), "fence_calls": fence.calls,
        "no_pause_file": not fx.state(target, "pause.json").exists(),
        "lock_released": not fx.state(target, api.LOCK_DIR).exists()}

    host, target, d1, _, receipt = fx.real_start("drain-real")
    assert until(lambda: isinstance(fx.read(target, api.WORK_FILE), dict), 60)
    out["real_child_reports_no_active_work"] = {
        "work_file": fx.n(fx.read(target, api.WORK_FILE)), "drain": fx.attempt(lambda: host.drain(target)),
        "pause_file": fx.n(fx.read(target, "pause.json"))}
    host.stop(target)
    return out


# ======================================================================================================
# 6. observe / identity
# ======================================================================================================
def group_observe_identity(fx):
    api, out = fx.api, {}
    host = fx.host()

    target = fx.target("observe-empty")
    out["nothing_on_the_target"] = {"observe": fx.attempt(lambda: host.observe(target)),
                                    "identity": fx.attempt(lambda: host.identity(target)),
                                    "receipt": host.receipt(target), "launch_record": host.launch_record(target)}
    target = fx.target("observe-unreadable")
    fx.write(target, api.RECEIPT_FILE, "{not json")
    out["receipt_present_but_unreadable_is_unknown_not_absent"] = {
        "observe": fx.attempt(lambda: host.observe(target)), "identity": fx.attempt(lambda: host.identity(target))}
    fx.write(target, api.RECEIPT_FILE, [1, 2])
    out["receipt_of_the_wrong_shape_is_unreadable"] = {"identity": fx.attempt(lambda: host.identity(target))}
    fx.write(target, api.RECEIPT_FILE, {"schema": api.RECEIPT_SCHEMA})
    out["receipt_missing_its_fields_is_unreadable"] = {"identity": fx.attempt(lambda: host.identity(target))}
    target = fx.target("observe-oversized")
    fx.write(target, api.RECEIPT_FILE, json.dumps({"pad": "x" * (64 * 1024)}))
    out["an_oversized_receipt_is_unreadable"] = {"observe": fx.attempt(lambda: host.observe(target))}

    target = fx.target("observe-launch")
    pid = fx.sleeper()
    fx.write(target, api.STATE_FILE, {"pid": pid, "started_at": STAMP, "descriptor_sha256": "0" * 64})
    out["launch_present_and_running"] = {"observe": fx.attempt(lambda: host.observe(target)),
                                         "launch_record": fx.attempt(lambda: host.launch_record(target))}
    target = fx.target("observe-launch-garbage")
    fx.write(target, api.STATE_FILE, "garbage")
    out["launch_present_but_unreadable"] = {"observe": fx.attempt(lambda: host.observe(target))}
    target = fx.target("observe-launch-dead")
    fx.write(target, api.STATE_FILE, {"pid": fx.dead_pid(), "started_at": STAMP, "descriptor_sha256": "0" * 64})
    out["launch_present_but_not_running"] = {"observe": fx.attempt(lambda: host.observe(target))}

    class Unobservable(api.ProcessHostTarget):
        """LABELLED injected liveness failure."""

        def running(self, target):
            raise OSError("injected: liveness cannot be read")

    target = fx.target("observe-liveness")
    out["liveness_that_cannot_be_read_is_none"] = {
        "observe": fx.attempt(lambda: Unobservable(python=PY).observe(target))}

    class BaseProbe(api.HostTargetBase):
        """LABELLED: the shared base with a liveness that cannot be read, and with none implemented."""

        def running(self, target):
            raise OSError("injected: liveness cannot be read")

    target = fx.target("observe-base")
    out["the_shared_base_reads_an_unreadable_liveness_as_none"] = {
        "observe": fx.attempt(lambda: BaseProbe().observe(target))}
    out["the_shared_base_without_a_liveness_reads_none"] = {
        "observe": fx.attempt(lambda: api.HostTargetBase().observe(target)),
        "stop": fx.attempt(lambda: api.HostTargetBase().stop(target)),
        "start": fx.attempt(lambda: api.HostTargetBase().start(target, {})),
        "state_dir": fx.attempt(lambda: api.HostTargetBase.state_dir(target)),
        "path": fx.attempt(lambda: api.HostTargetBase.path(target, "x.json"))}

    target = fx.target("identity-live", root=fx.runtime)
    d1 = fx.descriptor(target, "identity-1", "one")
    planted = fx.plant(target, d1)
    out["identity_before_a_replacement"] = {
        "identity": fx.attempt(lambda: host.identity(target)),
        "observe_receipt_equals_planted": host.observe(target)["receipt"] == planted["receipt"]}
    target = fx.target("identity-no-descriptor", root=fx.runtime)
    d1 = fx.descriptor(target, "identity-2", "one")
    fx.plant(target, d1, descriptor_file=False)
    out["identity_with_a_receipt_and_no_descriptor"] = {"identity": fx.attempt(lambda: host.identity(target))}
    target = fx.target("identity-dead", root=fx.runtime)
    d1 = fx.descriptor(target, "identity-3", "one")
    fx.plant(target, d1, live=False)
    out["identity_of_a_dead_instance"] = {"identity": fx.attempt(lambda: host.identity(target))}
    return out


# ======================================================================================================
# 7. the service child
# ======================================================================================================
def child_environment(fx) -> dict:
    environment = dict(os.environ)
    inherited = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = str(fx.runtime / "src") + (os.pathsep + inherited if inherited else "")
    return environment


def run_service(fx, *args):
    done = subprocess.run([PY, "-m", "codex_harness.adapters.host_delivery", *args], cwd=str(fx.runtime),
                          env=child_environment(fx), stdin=subprocess.DEVNULL, capture_output=True, timeout=120)
    return done.returncode


def group_service_child(fx):
    api, out = fx.api, {}

    def state(name, descriptor=None, *, raw=None):
        target = fx.target(name)
        if raw is not None:
            fx.write(target, api.DESCRIPTOR_FILE, raw)
        elif descriptor is not None:
            fx.write(target, api.DESCRIPTOR_FILE, descriptor)
        return target

    # serve in this process over a missing or malformed descriptor: exit 2 and no receipt.
    target = state("serve-missing")
    out["serve_missing_descriptor"] = {"exit": api.serve(target["state_dir"], 1), "files": fx.listing(target)}
    target = state("serve-garbage", raw="not json")
    out["serve_malformed_descriptor"] = {"exit": api.serve(target["state_dir"], 1), "files": fx.listing(target)}
    target = state("serve-schema", raw=json.dumps({"schema": "urn:other:1"}))
    out["serve_wrong_schema"] = {"exit": api.serve(target["state_dir"], 1), "files": fx.listing(target)}
    template = fx.target("serve-template")
    good = fx.descriptor(template, "serve-good", "one")
    target = state("serve-invalid-field", dict(good, revision="nothex"))
    out["serve_invalid_field"] = {"exit": api.serve(target["state_dir"], 1), "files": fx.listing(target)}

    # a valid descriptor: work.json, the receipt, then exit 0 on the stop file.
    target = state("serve-valid", good)
    fx.write(target, "stop.json", {"stop": True})
    code = api.serve(target["state_dir"], 30)
    receipt = fx.read(target, api.RECEIPT_FILE)
    out["serve_valid_descriptor_exits_on_the_stop_file"] = {
        "exit": code, "work_file": fx.n(fx.read(target, api.WORK_FILE)), "receipt": fx.n(receipt),
        "receipt_pid_is_this_process": receipt["pid"] == os.getpid(),
        "receipt_describes_the_descriptor": receipt["descriptor_sha256"] == fx.digest(good),
        "consumption_verdict": api.consumption_verdict(good, receipt), "files": fx.listing(target)}
    direct = api.startup_receipt(good)
    out["startup_receipt"] = {
        "keys": sorted(direct), "receipt": fx.n(direct), "pid_is_this_process": direct["pid"] == os.getpid(),
        "instance_is_32_hex": bool(re.fullmatch(r"[0-9a-f]{32}", direct["instance_id"]))}

    # main: the bounded idle (max-seconds 1), argument errors.
    target = state("main-idle", good)
    with ticking(api):
        code = api.main(["service", "--state-dir", target["state_dir"], "--max-seconds", "1"])
    out["main_service_max_seconds_one"] = {
        "exit": code, "files": fx.listing(target), "no_stop_file": not fx.state(target, "stop.json").exists()}
    with contextlib.redirect_stderr(io.StringIO()):
        out["main_without_a_state_dir"] = fx.attempt(lambda: api.main(["service"]))
        out["main_with_an_unknown_command"] = fx.attempt(lambda: api.main(["bogus"]))
        out["main_without_a_command"] = fx.attempt(lambda: api.main([]))
        out["main_with_a_non_integer_seconds"] = fx.attempt(lambda: api.main(
            ["service", "--state-dir", target["state_dir"], "--max-seconds", "x"]))
    target = state("main-missing")
    out["main_service_over_a_missing_descriptor"] = {"exit": api.main(["service", "--state-dir", target["state_dir"]]),
                                                     "files": fx.listing(target)}

    # the same service as a CHILD process started the way the target starts it (this side's own package).
    target = state("child-missing")
    out["child_missing_descriptor"] = {
        "exit": run_service(fx, "service", "--state-dir", target["state_dir"], "--max-seconds", "1"),
        "files": fx.listing(target)}
    target = state("child-malformed", raw="not json")
    out["child_malformed_descriptor"] = {
        "exit": run_service(fx, "service", "--state-dir", target["state_dir"]), "files": fx.listing(target)}
    target = state("child-valid-stop", good)
    fx.write(target, "stop.json", {"stop": True})
    code = run_service(fx, "service", "--state-dir", target["state_dir"], "--max-seconds", "30")
    receipt = fx.read(target, api.RECEIPT_FILE)
    out["child_valid_descriptor_exits_on_the_stop_file"] = {
        "exit": code, "work_file": fx.n(fx.read(target, api.WORK_FILE)), "receipt": fx.n(receipt),
        "receipt_is_this_sides_package": receipt["module_root"] == str(Path(api.PACKAGE_DIR).resolve()),
        "receipt_pid_is_not_this_process": receipt["pid"] != os.getpid(),
        "consumption_verdict": api.consumption_verdict(good, receipt), "files": fx.listing(target)}
    target = state("child-idle", good)
    code = run_service(fx, "service", "--state-dir", target["state_dir"], "--max-seconds", "1")
    out["child_bounded_idle_exits_zero"] = {"exit": code, "files": fx.listing(target)}
    out["child_without_arguments"] = {"exit": run_service(fx)}
    return out


# ======================================================================================================
# 8. GitHubDelivery
# ======================================================================================================
REPOSITORY = "github:zeus-owner/zeus-harness"


class Runner:
    """LABELLED recording `gh` runner: it answers the scripted outcomes in order and never runs anything."""

    def __init__(self, *outcomes):
        self.calls, self.outcomes = [], list(outcomes)

    def __call__(self, argv, timeout=None):
        self.calls.append({"argv": list(argv), "timeout": timeout})
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        code, stdout = outcome
        return SimpleNamespace(returncode=code, stdout=stdout, stderr="")


class Workspace:
    """LABELLED recording workspace double (the `GitWorkspace` calls `GitHubDelivery` makes)."""

    def __init__(self, remote=REPOSITORY, **scripted):
        self.remote, self.scripted, self.calls = remote, scripted, []

    def _answer(self, name, *args, **kwargs):
        self.calls.append({"call": name, "args": list(args), "kwargs": sorted(kwargs)})
        outcome = self.scripted.get(name, {})
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def publish(self, candidate, title, body):
        return self._answer("publish", candidate["revision"], title, body)

    def merge_state(self, candidate, observed=None):
        return self._answer("merge_state", candidate["revision"], observed)

    def merge(self, candidate, **kwargs):
        return self._answer("merge", candidate["revision"], **kwargs)

    def qualify_merged(self, candidate, merged_revision):
        return self._answer("qualify_merged", candidate["revision"], merged_revision)


def candidate():
    return {"revision": "a" * 40, "base": "b" * 40, "tree": "c" * 64, "author": "worker:implementation",
            "branch": "harness/delivery-1", "task_id": "delivery-1", "repository": REPOSITORY,
            "objective": "LABELLED fixture candidate"}


def row(**fields):
    base = {"number": 181, "url": "https://example.invalid/pull/181", "headRefOid": "a" * 40, "state": "OPEN",
            "mergeCommit": None, "statusCheckRollup": []}
    base.update(fields)
    return base


def group_github(fx):
    api, out = fx.api, {}

    def observing(name, outcome, *, workspace=None, **options):
        runner = Runner(outcome)
        delivery = api.GitHubDelivery(workspace or Workspace(), runner=runner, **options)
        out["observe_" + name] = {"result": fx.attempt(lambda: delivery.observe(candidate())),
                                  "runner_calls": runner.calls}

    def listing(*rows):
        return (0, json.dumps(list(rows)))

    observing("no_pull_request", listing())
    observing("empty_output", (0, ""))
    observing("none_output", (0, None))
    observing("open_with_its_checks", listing(row(statusCheckRollup=[
        {"name": "ci / success", "status": "COMPLETED", "conclusion": "SUCCESS"},
        {"name": "ci / running", "status": "IN_PROGRESS", "conclusion": ""},
        {"name": "ci / queued", "status": "QUEUED"},
        {"name": "ci / failed", "status": "COMPLETED", "conclusion": "FAILURE"},
        {"name": "ci / skipped", "status": "COMPLETED", "conclusion": "SKIPPED"},
        {"name": "ci / cancelled", "status": "COMPLETED", "conclusion": "CANCELLED"},
        {"context": "legacy / ok", "state": "SUCCESS"}, {"context": "legacy / pending", "state": "PENDING"},
        {"context": "legacy / expected", "state": "EXPECTED"}, {"context": "legacy / error", "state": "ERROR"},
        {"name": "", "status": "COMPLETED", "conclusion": "SUCCESS"}, {"state": "SUCCESS"}, "not a row", None])))
    observing("merged_with_its_merge_commit", listing(row(state="MERGED", mergeCommit={"oid": "9" * 40})))
    observing("merge_commit_that_is_not_an_object", listing(row(state="MERGED", mergeCommit="9" * 40)))
    observing("closed_rows_are_ignored", listing(row(state="CLOSED"), row(state="other")))
    observing("the_row_of_the_exact_head_wins", listing(row(number=1, headRefOid="d" * 40),
                                                        row(number=2, headRefOid="a" * 40)))
    observing("the_first_row_when_no_head_matches", listing(row(number=1, headRefOid="d" * 40),
                                                            row(number=2, headRefOid="e" * 40)))
    observing("a_listing_that_is_an_object", (0, "{}"))
    observing("a_nonzero_exit", (1, "boom"))
    observing("a_malformed_answer", (0, "not json"))
    observing("a_runner_error", OSError("injected: gh is unavailable"))
    observing("a_custom_timeout", listing(), timeout=7)
    observing("no_repository_configured", listing(), workspace=Workspace(remote=""))

    def workspace_case(name, method, scripted, *args, **options):
        workspace = Workspace(**scripted)
        delivery = api.GitHubDelivery(workspace, runner=Runner())
        out[name] = {"result": fx.attempt(lambda: getattr(delivery, method)(candidate(), *args, **options)),
                     "workspace_calls": workspace.calls}

    published = {"number": 181, "url": "https://example.invalid/pull/181", "headRefOid": "f" * 40}
    workspace_case("publish_through_the_workspace", "publish", {"publish": published})
    workspace_case("publish_without_a_head", "publish", {"publish": {"number": 7, "url": "u"}})
    workspace_case("publish_with_an_empty_answer", "publish", {"publish": {}})
    workspace_case("publish_refused_by_the_workspace", "publish", {"publish": api.ContractError("injected: target")})
    workspace_case("publish_transport_error", "publish", {"publish": OSError("injected: lost response")})
    state = {"state": "unmerged", "merged_revision": None, "main": "b" * 40}
    workspace_case("merge_state_without_an_observation", "merge_state", {"merge_state": state})
    workspace_case("merge_state_with_an_observation", "merge_state", {"merge_state": state},
                   {"state": "MERGED", "head": "a" * 40})
    workspace_case("merge_state_error", "merge_state", {"merge_state": OSError("injected")})
    workspace_case("merge_without_an_observation", "merge",
                   {"merge": {"merged": True, "merged_revision": "a" * 40}})
    workspace_case("merge_with_an_observation", "merge", {"merge": {"merged": True, "revision": "a" * 40}},
                   {"state": "OPEN"})
    workspace_case("merge_not_merged", "merge", {"merge": {"merged": 0}})
    workspace_case("merge_with_an_empty_answer", "merge", {"merge": {}})
    workspace_case("merge_definitely_refused", "merge", {"merge": api.MergeRefused("main_moved")})
    workspace_case("merge_unknown_outcome", "merge", {"merge": OSError("injected: lost push response")})
    workspace_case("qualify_through_the_workspace", "qualify",
                   {"qualify_merged": {"merged_revision": "9" * 40, "tree": "c" * 64}}, "9" * 40)
    workspace_case("qualify_tree_differs", "qualify",
                   {"qualify_merged": api.ContractError("Merged tree differs from reviewed candidate")}, "9" * 40)
    out["constructor_defaults"] = {"timeout": api.GitHubDelivery(Workspace()).timeout,
                                   "explicit_timeout": api.GitHubDelivery(Workspace(), timeout=5).timeout}
    return out


GROUPS = (("switch", group_switch), ("guard", group_guard), ("start", group_start),
          ("stop_reaping", group_stop_reaping), ("drain", group_drain),
          ("observe_identity", group_observe_identity), ("service_child", group_service_child),
          ("github", group_github))


def run(api) -> dict:
    ContractErrorHolder.error = api.ContractError
    result, counts, live = {}, {}, 0
    with tempfile.TemporaryDirectory(prefix="s7-host-targets-") as raw:
        fx = Fixture(api, Path(raw).resolve())
        for name, group in GROUPS:
            result[name] = group(fx)
            live += fx.sweep(name)
            counts[name] = len(result[name])
        result["live_children"] = live
        result["cases_per_group"] = counts
    return result
