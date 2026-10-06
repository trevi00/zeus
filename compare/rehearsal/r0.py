"""Cutover RH-7/RH-8 (owner, read-only): the R0 DEPLOYMENT/rollback baseline of every persistent Zeus unit on aibox.

Rehearsal design R0 + plan RH-7 (critique #7: stable vs per-invocation fields). Records, never reads values:
- per unit (persistent zeus-aibox* units whose FragmentPath is under /etc/systemd/system, plus zeus-aibox.target):
  allowlisted `systemctl show` properties; the fragment sha256; the EFFECTIVE drop-ins (name, inode, size, sha256);
  and the drop-in DIRECTORY `<FragmentPath>.d/` as a whole (RH-8 F3): every entry, disabled and non-`.conf` ones
  included, with name/type/inode/size and the sha256 of a non-secret regular file; EnvironmentFiles PATHS only
  (never their content or digest); an entry that is a secret/environment file is path-only;
- per release dir named by an ExecStart or WorkingDirectory, releases/current, every `<srv>/releases/<40 hex>` root that
  a unit's cgroup child argv[0] is under (RH-7; an argv[0] under `<srv>/releases/` of another shape is incomplete,
  `children:<unit>:release_shape`) and every directory that carries the MANAGED payload (bound from the descriptor/
  startup receipt revision or a path field, even outside releases/current): runtime.json (revision, tree, built_at) and
  its sha256, pyvenv.cfg sha256, the zeus-harness dist-info RECORD sha256, the interpreter realpath and the interpreter
  sha256; a payload directory without a `.venv` that holds runtime.json, runtime-files.json, uv.lock and src/ is the
  `runtime_dir` shape (nothing in the payload directory is executed): the sha256 of those files and pyproject.toml, and
    - `launcher`: {realpath, sha256, sys_version} of the LAUNCHING unit's ExecStart argv[0] and `script_sha256`, the
      sha256 of the launcher script ExecStart argv[1] names when it is a regular non-secret file (else null);
    - `unit_template_sha256`: the managed unit's FragmentPath sha256;
    - `runtime_executables`: for each live cgroup child of the managed unit {realpath, release (root or null),
      subcommand (supervise|launch|entry|null), interpreter_sha256}, sorted by realpath, pid-free;
    - `payload_executable`: the ONE child that runs the payload {realpath, release, subcommand, interpreter_sha256,
      parent_subcommand, cwd_is_payload_location}: the `entry` child (argv[3] of `-m codex_harness.adapters.
      managed_runtime`, the only argv word read beyond argv[0..2] and only when it is one of the three command words)
      whose parent (`/proc/<pid>/stat` ppid) is the `supervise` child and whose `/proc/<pid>/cwd` target, when
      readable, is the payload location (managed_runtime.py: supervise runs `launch` in-process, which owns one `entry`
      child with cwd=descriptor root). Zero or several such children: `payload_executable` is absent and the record is
      incomplete (`managed_payload:payload_executable:unresolved`); the launcher is never substituted. `environ` is never
      read. A directory of neither shape is incomplete;
- managed-fleet state ids (explicit per-record key allowlists) and the authoritative managed binding `managed.binding`
  (plan_id, descriptor_sha256, instance_id, revision) taken from the injected lane-status JSON row of the managed
  target and cross-checked against the startup receipt, controller state and heartbeat (RH-8 F3 final); the payload
  location binds from the startup receipt's runtime_root/module_root; host-activation.json sha256, the lane names;
- the continuation/research children of each unit, from `<cgroup>/<unit>/cgroup.procs` and `/proc/<pid>/cmdline`
  argv[0..2] only, or the evidenced absence of the cgroup;
- zeus-aibox-postgres/redis allowlisted docker facts and the `docker diff` digest/line count; the worker image ids as
  full immutable `sha256:` ids.
No path under /srv/zeus/secrets is opened or hashed; no environment value is read. A required fact that cannot be read
is never dropped silently: the record is `complete: false` and `incomplete` names the field.
All external interfaces go through `Env` (`run` plus the injectable roots), so tests use synthetic paths.
usage (cwd compare/): python3 -m rehearsal.r0 OUT.json [LANE_STATUS.json]    (exit 0 complete, 1 incomplete)
"""

from __future__ import annotations

import datetime
import glob
import hashlib
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from typing import Callable

STABLE = ("Id", "LoadState", "UnitFileState", "FragmentPath", "DropInPaths", "ExecStart", "EnvironmentFiles", "User",
          "Group", "UMask", "Restart", "KillMode", "Type", "WorkingDirectory", "Triggers", "TriggeredBy", "Wants",
          "Requires", "PartOf")
PER_INVOCATION = ("ActiveState", "SubState", "InvocationID", "MainPID", "ExecMainPID", "NRestarts",
                  "ExecMainStartTimestampMonotonic", "ActiveEnterTimestampMonotonic", "NeedDaemonReload")
LIST_PROPS = ("DropInPaths", "Triggers", "TriggeredBy", "Wants", "Requires", "PartOf")
MANAGED_FILES = ("managed-launch.json", "controller-state.json", "startup-receipt.json", "descriptor.json",
                 "heartbeat.json")
# explicit, non-secret key allowlists of the observed record shapes (no plan id exists in any of them)
MANAGED_STABLE = {
    "descriptor.json": ("predecessor", "profile_digest", "revision", "root", "schema", "target_id", "worker_image"),
    "startup-receipt.json": ("descriptor_sha256", "module_root", "profile_digest", "revision", "runtime_root", "schema",
                             "target_id", "worker_image"),
    "controller-state.json": ("descriptor_sha256", "manifest_sha256", "service"),
    "managed-launch.json": ("descriptor_sha256", "manifest_sha256", "schema", "target_id", "workload"),
    "heartbeat.json": ("descriptor_sha256", "schema")}
MANAGED_INVOCATION = {"startup-receipt.json": ("instance_id",), "controller-state.json": ("invocation_id",),
                      "heartbeat.json": ("instance_id",)}
MANAGED_UNIT = "zeus-aibox-managed-fleet.service"
# `python -m codex_harness.adapters.managed_runtime <sub>`: argv[3] is the only argv word read beyond argv[0..2], and
# only when it is one of these three non-secret command words (managed_runtime.py main(): supervise runs `launch`
# in-process, `launch` owns ONE `entry` child with cwd = the descriptor root; `entry` is the payload)
MANAGED_MODULE = "codex_harness.adapters.managed_runtime"
SUBCOMMANDS = ("supervise", "launch", "entry")
RUNTIME_DIR_FILES = ("runtime.json", "runtime-files.json", "uv.lock")
BINDING_FIELDS = ("plan_id", "descriptor_sha256", "instance_id", "revision")
IMAGE_LINE = re.compile(r"^(\S+) (sha256:[0-9a-f]{64})$")
ENV_NAME = re.compile(r"\.(env|environment)$")
SCHEMA = "zeus:aibox-migration-001:rehearsal:r0:2"


def _run(argv):
    return subprocess.run(list(argv), capture_output=True, text=True, timeout=60)


@dataclass
class Env:
    """The external interfaces: process execution and the (injectable) production roots."""

    run: Callable = _run
    srv: str = "/srv/zeus"
    cgroup: str = "/sys/fs/cgroup/system.slice"
    proc: str = "/proc"
    unit_dir: str = "/etc/systemd/system/"
    lane_status: str = ""  # path of the `host-delivery status --lane harness` JSON the owner supplies (no DB access here)
    now: Callable = lambda: datetime.datetime.now(datetime.timezone.utc).isoformat()  # noqa: E731

    @property
    def secrets(self) -> str:
        return os.path.join(self.srv, "secrets")


class Recorder:
    def __init__(self, env: Env):
        self.env = env
        self.missing: set[str] = set()
        self.live: dict[str, list] = {}  # unit -> live cgroup children (pid, argv0, subcommand, release, ppid, cwd)
        self.fragments: dict[str, str | None] = {}  # unit -> FragmentPath sha256

    def miss(self, name: str) -> None:
        self.missing.add(name)

    def cmd(self, name: str, *argv) -> str:
        """stdout of a required command; a nonzero exit or a failed spawn marks `name` incomplete."""
        try:
            done = self.env.run(argv)
        except (OSError, subprocess.SubprocessError):
            self.miss(name)
            return ""
        if done.returncode != 0:
            self.miss(name)
            return ""
        return done.stdout

    def is_secret(self, path: str) -> bool:
        real = os.path.realpath(path)
        return real == self.env.secrets or real.startswith(self.env.secrets + os.sep) or bool(ENV_NAME.search(path))

    def sha(self, name: str, path: str) -> str:
        """sha256 of a non-secret file; `path_only` for a secret/environment file; unreadable marks `name` incomplete."""
        if self.is_secret(path):
            return "path_only"
        try:
            with open(path, "rb") as fh:
                return hashlib.sha256(fh.read()).hexdigest()
        except OSError as exc:
            self.miss(name)
            return f"unreadable:{type(exc).__name__}"

    def show(self, unit: str, props) -> dict:
        out = self.cmd(f"show:{unit}", "systemctl", "show", unit, *[f"-p{p}" for p in props])
        facts = dict(line.split("=", 1) for line in out.splitlines() if "=" in line)
        for key in LIST_PROPS:  # systemd prints these unordered: sort for a deterministic record
            if key in facts:
                facts[key] = " ".join(sorted(facts[key].split()))
        if "ExecStart" in facts:  # keep path and argv only; start_time/stop_time/pid/code/status are per run
            facts["ExecStart"] = re.sub(r" ; (start_time|stop_time|pid|code|status)=[^;}]*", "", facts["ExecStart"])
        return facts

    def units(self) -> list[str]:
        listing = self.cmd("units", "systemctl", "list-unit-files", "--no-legend", "zeus-aibox*")
        names = sorted({line.split()[0] for line in listing.splitlines() if line.strip()})
        keep = []
        for name in names:
            frag = self.show(name, ("FragmentPath",)).get("FragmentPath", "")
            if frag.startswith(self.env.unit_dir) or name == "zeus-aibox.target":
                keep.append(name)
        return keep

    # -- F3: the drop-in directory --

    def dropin_dir(self, unit: str, frag: str) -> dict:
        """Every entry of `<FragmentPath>.d/` (disabled and non-.conf included): name/type/inode/size and, for a
        non-secret regular file, its sha256. A directory that does not exist is evidenced absence; an unreadable one
        or entry marks the record incomplete."""
        directory = frag + ".d"
        facts = {"path": directory}
        try:
            names = sorted(os.listdir(directory))
        except FileNotFoundError:
            return {**facts, "present": False, "entries": []}
        except OSError as exc:
            self.miss(f"dropin_dir:{unit}")
            return {**facts, "present": None, "error": type(exc).__name__, "entries": []}
        entries = []
        for name in names:
            path = os.path.join(directory, name)
            try:
                info = os.lstat(path)
            except OSError as exc:
                self.miss(f"dropin_entry:{unit}/{name}")
                entries.append({"name": name, "error": type(exc).__name__})
                continue
            if os.path.islink(path):
                entry = {"name": name, "type": "symlink", "inode": info.st_ino, "link_target": os.readlink(path)}
                if os.path.isfile(path) and not self.is_secret(path):
                    entry["sha256"] = self.sha(f"dropin_entry:{unit}/{name}", path)
                elif self.is_secret(path):
                    entry["path_only"] = True
            elif os.path.isfile(path):
                entry = {"name": name, "type": "file", "inode": info.st_ino, "size": info.st_size}
                if self.is_secret(path):
                    entry["path_only"] = True
                else:
                    entry["sha256"] = self.sha(f"dropin_entry:{unit}/{name}", path)
            else:
                entry = {"name": name, "type": "dir" if os.path.isdir(path) else "other", "inode": info.st_ino}
            entries.append(entry)
        return {**facts, "present": True, "entries": entries}

    # -- releases --

    def release_facts(self, rev_dir: str) -> dict:
        facts = {"dir": rev_dir}
        runtime = os.path.join(rev_dir, "runtime.json")
        try:
            with open(runtime) as fh:
                rt = json.load(fh)
            facts["runtime"] = {k: rt.get(k) for k in ("revision", "tree", "built_at")}
        except (OSError, ValueError) as exc:
            self.miss(f"release:{rev_dir}:runtime.json")
            facts["runtime"] = f"unreadable:{type(exc).__name__}"
        facts["runtime_json_sha256"] = self.sha(f"release:{rev_dir}:runtime.json", runtime)
        facts["pyvenv_cfg_sha256"] = self.sha(f"release:{rev_dir}:pyvenv.cfg", os.path.join(rev_dir, ".venv", "pyvenv.cfg"))
        records = sorted(glob.glob(os.path.join(rev_dir, ".venv", "lib", "python*", "site-packages",
                                                "zeus_harness-*.dist-info", "RECORD")))
        if not records:
            self.miss(f"release:{rev_dir}:dist-info RECORD")
        facts["dist_record_sha256"] = [self.sha(f"release:{rev_dir}:dist-info RECORD", r) for r in records]
        interpreter = os.path.realpath(os.path.join(rev_dir, ".venv", "bin", "python"))
        facts["interpreter_realpath"] = interpreter
        facts["interpreter_sha256"] = self.sha(f"release:{rev_dir}:interpreter", interpreter)
        return facts

    # -- the managed payload --

    def payload_facts(self, location: str) -> dict:
        """The release shape (`.venv`) is bound by `release_facts`; the runtime-dir shape (runtime.json +
        runtime-files.json + uv.lock + src/, no `.venv`) by `runtime_dir_facts`; any other shape is incomplete."""
        if os.path.isdir(os.path.join(location, ".venv")):
            return self.release_facts(location)
        if all(os.path.isfile(os.path.join(location, n)) for n in RUNTIME_DIR_FILES) and os.path.isdir(
                os.path.join(location, "src")):
            return self.runtime_dir_facts(location)
        self.miss(f"managed_payload:shape:{location}")
        return {"dir": location, "shape": "unknown"}

    def runtime_dir_facts(self, location: str) -> dict:
        facts = {"dir": location, "shape": "runtime_dir"}
        name = f"payload:{location}"
        try:
            with open(os.path.join(location, "runtime.json")) as fh:
                rt = json.load(fh)
            facts["runtime"] = {k: rt.get(k) for k in ("revision", "tree", "built_at")}
        except (OSError, ValueError, AttributeError) as exc:
            self.miss(f"{name}:runtime.json")
            facts["runtime"] = f"unreadable:{type(exc).__name__}"
        for fname in (*RUNTIME_DIR_FILES, "pyproject.toml"):
            facts[fname.replace(".", "_").replace("-", "_") + "_sha256"] = self.sha(
                f"{name}:{fname}", os.path.join(location, fname))
        # `launcher`: the LAUNCHING unit's ExecStart argv[0] (and the script it names), never anything inside the payload
        # directory; it is NOT the process that runs the payload (that is `payload_executable`, from the cgroup children)
        exec_start = self.show(MANAGED_UNIT, ("ExecStart",)).get("ExecStart", "")
        argv = (re.search(r"argv\[\]=([^;}]*)", exec_start) or re.search(r"path=([^;}]*)", exec_start))
        words = argv.group(1).split() if argv else []
        argv0 = words[0] if words else ""
        real = os.path.realpath(argv0) if argv0.startswith("/") else ""
        location_real = os.path.realpath(location)
        launcher = {"realpath": real or None}
        facts["launcher"] = launcher
        if not real or real == location_real or real.startswith(location_real + os.sep):
            self.miss(f"{name}:launching_executable")
        else:
            launcher["sha256"] = self.sha(f"{name}:interpreter", real)
            launcher["sys_version"] = self.cmd(f"{name}:interpreter_version", real, "-c",
                                               "import sys;print(sys.version)").strip()
            script = words[1] if len(words) > 1 else ""
            launcher["script_sha256"] = (self.sha(f"{name}:launcher_script", script)
                                         if script.startswith("/") and os.path.isfile(script) else None)
        facts["unit_template_sha256"] = self.fragment_sha(MANAGED_UNIT)
        executables, payload = self.runtime_executables(location)
        facts["runtime_executables"] = executables
        if payload is None:
            self.miss("managed_payload:payload_executable:unresolved")
        else:
            facts["payload_executable"] = payload
        return facts

    def fragment_sha(self, unit: str):
        """The unit FragmentPath's sha256 (the same value `collect` records as FragmentSha256)."""
        if unit not in self.fragments:
            frag = self.show(unit, ("FragmentPath",)).get("FragmentPath", "")
            self.fragments[unit] = self.sha(f"fragment:{unit}", frag) if frag else None
            if not frag:
                self.miss(f"fragment:{unit}")
        return self.fragments[unit]

    def runtime_executables(self, location: str):
        """(the executables of every live child of the managed unit sorted by realpath, pid-free; the ONE child that
        runs the payload or None). The payload child is the `entry` child (argv[3]) whose parent is the `supervise`
        child and whose cwd, when readable, is the payload location (managed_runtime.py: `launch` spawns `entry` with
        cwd=descriptor root under the supervising process). Zero or several such children: unresolved, no fallback."""
        if MANAGED_UNIT not in self.live:
            self.children(MANAGED_UNIT)
        kids = self.live.get(MANAGED_UNIT, [])
        executables = []
        for kid in kids:
            real = os.path.realpath(kid["argv0"]) if kid["argv0"].startswith("/") else ""
            if not real:
                self.miss(f"payload:{location}:runtime_executable")
                continue
            executables.append({"realpath": real, "release": kid["release"], "subcommand": kid["sub"],
                                "interpreter_sha256": self.sha(f"payload:{location}:runtime_executable", real)})
        executables.sort(key=lambda e: (e["realpath"], e["subcommand"] or ""))
        supervisors = {k["pid"] for k in kids if k["sub"] == "supervise"}
        locations = {os.path.realpath(location)}
        picked = [k for k in kids if k["sub"] == "entry" and k["ppid"] in supervisors
                  and (k["cwd"] is None or os.path.realpath(k["cwd"]) in locations)]
        if len(picked) != 1 or not picked[0]["argv0"].startswith("/"):
            return executables, None
        kid = picked[0]
        return executables, {
            "realpath": os.path.realpath(kid["argv0"]), "release": kid["release"], "subcommand": "entry",
            "interpreter_sha256": self.sha(f"payload:{location}:runtime_executable", os.path.realpath(kid["argv0"])),
            "parent_subcommand": "supervise", "cwd_is_payload_location": None if kid["cwd"] is None else True}

    def lane_target(self, target_id) -> dict:
        """The AUTHORITATIVE lane-status row of the managed target (the plan id lives only there); {} when the status
        is unreadable, the target is unknown or ambiguous. Never inferred from a revision."""
        path = self.env.lane_status
        if not path:
            self.miss("managed.binding:lane_status")
            return {}
        try:
            with open(path) as fh:
                targets = json.load(fh).get("targets")
        except (OSError, ValueError, AttributeError) as exc:
            self.miss("managed.binding:lane_status")
            return {"error": type(exc).__name__}
        rows = [t for t in targets if isinstance(t, dict) and t.get("target_id") == target_id] if (
            isinstance(targets, list) and isinstance(target_id, str) and target_id) else []
        if len(rows) != 1:
            self.miss("managed.binding:target_row")
            return {}
        return rows[0]

    def payload_location(self, receipt) -> set[str]:
        """The payload directory recorded by the startup receipt (`runtime_root`/`module_root`): the release directory
        `<...>/releases/<40-hex>` that contains it, else the nearest ancestor that holds a runtime.json. An unresolved
        shape is incomplete; no same-revision release is substituted."""
        roots = [receipt.get(k) for k in ("runtime_root", "module_root") if isinstance(receipt.get(k), str)]
        if not roots:
            self.miss("managed_payload:location")
        found = set()
        for root in roots:
            if not root.startswith("/") or self.is_secret(root):
                self.miss(f"managed_payload:location:{root}")
                continue
            hit = re.match(r"(.*/releases/[0-9a-f]{40})(?:/|$)", root)
            location = hit.group(1) if hit else None
            if location is None:
                ancestor = root.rstrip("/")
                while ancestor and ancestor != "/":
                    if os.path.isfile(os.path.join(ancestor, "runtime.json")):
                        location = ancestor
                        break
                    ancestor = os.path.dirname(ancestor)
            if location is None or not os.path.isdir(location):
                self.miss(f"managed_payload:location:{root}")
            else:
                found.add(location)
        return found

    def managed(self) -> tuple[dict, dict, dict, dict]:
        """(per-invocation ids, stable payload binding, payload release facts by dir, authoritative binding)."""
        ids, stable, docs, revisions = {}, {}, {}, set()
        for name in MANAGED_FILES:
            path = os.path.join(self.env.srv, "runtime", "managed-fleet", name)
            try:
                with open(path) as fh:
                    doc = json.load(fh)
                if not isinstance(doc, dict):
                    raise ValueError("not an object")
            except (OSError, ValueError) as exc:
                self.miss(f"managed:{name}")
                ids[name] = f"unreadable:{type(exc).__name__}"
                continue
            docs[name] = doc
            keep = MANAGED_STABLE[name] + MANAGED_INVOCATION.get(name, ())
            ids[name] = {k: doc[k] for k in keep if isinstance(doc.get(k), (str, int, bool))}
            stable[name] = {k: doc[k] for k in MANAGED_STABLE[name] if isinstance(doc.get(k), (str, int, bool))}
        descriptor = docs.get("descriptor.json", {})
        receipt = docs.get("startup-receipt.json", {})
        row = self.lane_target(descriptor.get("target_id"))
        binding = {}
        for field in BINDING_FIELDS:
            value = row.get(field)
            if isinstance(value, str) and value:
                binding[field] = value
            else:
                self.miss(f"managed.binding.{field}")
        # the runtime records must agree with the lane-status binding (a field missing from a readable record is a
        # missing identity, a differing one is inconsistent)
        for name, field, bound in (("startup-receipt.json", "instance_id", "instance_id"),
                                   ("startup-receipt.json", "descriptor_sha256", "descriptor_sha256"),
                                   ("controller-state.json", "descriptor_sha256", "descriptor_sha256"),
                                   ("heartbeat.json", "descriptor_sha256", "descriptor_sha256"),
                                   ("heartbeat.json", "instance_id", "instance_id")):
            if name not in docs:
                continue  # the unreadable record is already named
            value = docs[name].get(field)
            if not isinstance(value, str) or not value:
                self.miss(f"managed.binding.{bound}:{name}:{field}")
            elif bound in binding and value != binding[bound]:
                self.miss(f"managed.binding.{bound}:inconsistent")
        for doc in (row, descriptor, receipt):
            if isinstance(doc.get("revision"), str) and re.fullmatch(r"[0-9a-f]{40}", doc["revision"]):
                revisions.add(doc["revision"])
        if "revision" in binding and receipt.get("revision") not in (None, binding["revision"]):
            self.miss("managed.binding.revision:inconsistent")
        if not revisions:
            self.miss("managed_payload:revision")
        locations = self.payload_location(receipt) if receipt else set()
        payload = {}
        for location in sorted(locations):
            facts = self.payload_facts(location)
            payload[location] = facts
            runtime = facts.get("runtime")
            if isinstance(runtime, dict) and revisions and runtime.get("revision") not in revisions:
                self.miss(f"managed_payload:revision_mismatch:{location}")
        stable["revisions"] = sorted(revisions)
        stable["locations"] = sorted(locations)
        return ids, stable, payload, binding

    # -- children --

    def child_release(self, unit: str, argv0: str):
        """The `<srv>/releases/<40 hex>` root a child's argv[0] is under; None when it is under no release; a path under
        `<srv>/releases/` of any other shape is incomplete."""
        prefix = os.path.join(self.env.srv, "releases") + os.sep
        if not argv0.startswith(prefix):
            return None
        hit = re.match(re.escape(prefix) + r"([0-9a-f]{40})(?:/|$)", argv0)
        if hit is None:
            self.miss(f"children:{unit}:release_shape")
            return None
        return prefix + hit.group(1)

    def child_links(self, pid: int) -> dict:
        """The two non-secret discriminators besides argv: the parent pid (`/proc/<pid>/stat`) and the cwd symlink
        target. Never `environ`. An unreadable one is None (and then does not identify the payload)."""
        ppid = cwd = None
        try:
            with open(os.path.join(self.env.proc, str(pid), "stat")) as fh:
                ppid = int(fh.read().rsplit(")", 1)[1].split()[1])
        except (OSError, ValueError, IndexError):
            pass
        try:
            cwd = os.readlink(os.path.join(self.env.proc, str(pid), "cwd"))
        except OSError:
            pass
        return {"ppid": ppid, "cwd": cwd}

    def children(self, unit: str) -> dict:
        procs = os.path.join(self.env.cgroup, unit, "cgroup.procs")
        try:
            with open(procs) as fh:
                pids = [int(x) for x in fh.read().split()]
        except FileNotFoundError:
            return {"cgroup": "absent", "children": []}  # evidenced absence: the unit has no live cgroup
        except (OSError, ValueError):
            self.miss(f"cgroup:{unit}")
            return {"cgroup": "unreadable", "children": []}
        children, live = [], []
        for pid in sorted(pids):
            try:
                with open(os.path.join(self.env.proc, str(pid), "cmdline"), "rb") as fh:
                    parts = [a.decode("utf-8", "replace") for a in fh.read().split(b"\0") if a][:4]
                argv = parts[:3]  # argv[0..2] ONLY are recorded
                children.append({"pid": pid, "argv": argv})
                sub = parts[3] if len(parts) > 3 and parts[1:3] == ["-m", MANAGED_MODULE] and parts[3] in SUBCOMMANDS else None
                live.append({"pid": pid, "argv0": argv[0] if argv else "", "sub": sub,
                             "release": self.child_release(unit, argv[0]) if argv else None,
                             **(self.child_links(pid) if unit == MANAGED_UNIT else {"ppid": None, "cwd": None})})
            except FileNotFoundError:
                children.append({"pid": pid, "gone": True})  # exited between the two reads
            except OSError:
                self.miss(f"cmdline:{unit}:{pid}")
                children.append({"pid": pid, "unreadable": True})
        self.live[unit] = live
        return {"cgroup": "present", "children": children}

    # -- docker --

    def containers(self) -> dict:
        out = {}
        for name in ("zeus-aibox-postgres", "zeus-aibox-redis"):
            fmt = ('{"Id":{{json .Id}},"Image":{{json .Image}},"StartedAt":{{json .State.StartedAt}},'
                   '"RestartCount":{{json .RestartCount}},"ExecIDs":{{json .ExecIDs}}}')
            raw = self.cmd(f"container:{name}", "docker", "inspect", "--format", fmt, name).strip()
            try:
                facts = json.loads(raw)
                facts["ExecIDs"] = len(facts.get("ExecIDs") or [])
            except ValueError:
                self.miss(f"container:{name}")
                facts = {"error": "inspect_unreadable"}
            diff = sorted(self.cmd(f"diff:{name}", "docker", "diff", name).splitlines())  # docker prints it unordered
            facts["diff_lines"] = len(diff)
            facts["diff_sha256"] = hashlib.sha256("\n".join(diff).encode()).hexdigest()
            out[name] = facts
        return out

    def worker_images(self) -> list:
        listing = self.cmd("worker_images", "docker", "image", "ls", "--no-trunc", "--format",
                           "{{.Repository}}:{{.Tag}} {{.ID}}", "zeus-worker")
        images = []
        for line in sorted(x for x in listing.splitlines() if x):
            match = IMAGE_LINE.match(line)
            if match is None:
                self.miss("worker_images")  # a short or malformed id is not an immutable identity
                continue
            images.append({"ref": match[1], "id": match[2]})
        return images


def collect(env: Env | None = None) -> dict:
    env = env or Env()
    rec = Recorder(env)
    record = {"schema": SCHEMA, "at": env.now(), "stable": {}, "per_invocation": {}}
    releases = set()
    release_re = re.escape(env.srv) + r"/releases/[0-9a-f]{40}"
    names = rec.units()
    for unit in names:
        st = rec.show(unit, STABLE)
        pi = rec.show(unit, PER_INVOCATION)
        frag = st.get("FragmentPath", "")
        drop = []
        for path in sorted(p for p in st.get("DropInPaths", "").split() if p):
            try:
                s = os.stat(path)
                drop.append({"path": path, "inode": s.st_ino, "size": s.st_size, "sha256": rec.sha(f"dropin:{unit}:{path}", path)})
            except OSError as exc:
                rec.miss(f"dropin:{unit}:{path}")
                drop.append({"path": path, "error": type(exc).__name__})
        st["FragmentSha256"] = rec.sha(f"fragment:{unit}", frag) if frag else None
        rec.fragments[unit] = st["FragmentSha256"]
        st["DropIns"] = drop
        st["DropInDir"] = rec.dropin_dir(unit, frag) if frag else None
        st["EnvironmentFiles"] = sorted(set(re.findall(r"(/[^\s;]+)", st.get("EnvironmentFiles", ""))))  # PATHS only
        record["stable"][unit] = st
        record["per_invocation"][unit] = pi
        record["per_invocation"].setdefault("children", {})[unit] = rec.children(unit)
        releases.update(re.findall(f"({release_re})", st.get("ExecStart", "") + " " + st.get("WorkingDirectory", "")))
    current = os.path.realpath(os.path.join(env.srv, "releases", "current"))
    releases.add(current)
    ids, payload_binding, payload_releases, binding = rec.managed()
    for kids in rec.live.values():  # every release a child runs (RH-7), beside the ExecStart/WorkingDirectory ones
        releases.update(kid["release"] for kid in kids if kid["release"])
    record["stable"]["releases"] = {r: rec.release_facts(r) for r in sorted(releases)}
    record["stable"]["releases_current"] = current
    record["stable"]["managed"] = {"binding": binding}
    record["stable"]["managed_payload"] = {"binding": payload_binding, "releases": payload_releases}
    record["per_invocation"]["managed_fleet"] = ids
    record["stable"]["host_activation_sha256"] = rec.sha(
        "host_activation", os.path.join(env.srv, "runtime", "control", "host-activation.json"))
    try:
        record["stable"]["lanes"] = sorted(os.listdir(os.path.join(env.srv, "runtime", "lanes")))
    except OSError:
        rec.miss("lanes")
        record["stable"]["lanes"] = None
    containers = rec.containers()
    record["per_invocation"]["containers"] = {k: {x: v[x] for x in ("StartedAt", "RestartCount", "ExecIDs", "diff_lines", "diff_sha256")
                                                  if x in v} for k, v in containers.items()}
    record["stable"]["containers"] = {k: {x: v[x] for x in ("Id", "Image") if x in v} for k, v in containers.items()}
    record["stable"]["worker_images"] = rec.worker_images()
    record["incomplete"] = sorted(rec.missing)
    record["complete"] = not rec.missing
    return record


def main(out: str, env: Env | None = None) -> int:
    record = collect(env)
    with open(out, "x") as fh:
        json.dump(record, fh, indent=1, sort_keys=True)
        fh.write("\n")
    print(json.dumps({"out": out, "units": len(record["stable"]), "releases": sorted(record["stable"]["releases"]),
                      "complete": record["complete"], "incomplete": record["incomplete"]}))
    return 0 if record["complete"] else 1


if __name__ == "__main__":
    if len(sys.argv) not in (2, 3):
        raise SystemExit("usage: python3 -m rehearsal.r0 OUT.json [LANE_STATUS.json]")
    sys.exit(main(sys.argv[1], Env(lane_status=sys.argv[2] if len(sys.argv) == 3 else "")))
