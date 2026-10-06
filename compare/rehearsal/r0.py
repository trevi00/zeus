"""Cutover RH-7/RH-8 (owner, read-only): the R0 DEPLOYMENT/rollback baseline of every persistent Zeus unit on aibox.

Rehearsal design R0 + plan RH-7 (critique #7: stable vs per-invocation fields). Records, never reads values:
- per unit (persistent zeus-aibox* units whose FragmentPath is under /etc/systemd/system, plus zeus-aibox.target):
  allowlisted `systemctl show` properties; the fragment sha256; the EFFECTIVE drop-ins (name, inode, size, sha256);
  and the drop-in DIRECTORY `<FragmentPath>.d/` as a whole (RH-8 F3): every entry, disabled and non-`.conf` ones
  included, with name/type/inode/size and the sha256 of a non-secret regular file; EnvironmentFiles PATHS only
  (never their content or digest); an entry that is a secret/environment file is path-only;
- per release dir named by an ExecStart or WorkingDirectory, releases/current and every directory that carries the
  MANAGED payload (bound from the descriptor/startup receipt revision or a path field, even outside releases/current):
  runtime.json (revision, tree, built_at) and its sha256, pyvenv.cfg sha256, the zeus-harness dist-info RECORD sha256,
  the interpreter realpath and the interpreter sha256;
- managed-fleet state ids (selected id fields: instance, invocation, revision, plan, descriptor), host-activation.json
  sha256, the lane names;
- the continuation/research children of each unit, from `<cgroup>/<unit>/cgroup.procs` and `/proc/<pid>/cmdline`
  argv[0..2] only, or the evidenced absence of the cgroup;
- zeus-aibox-postgres/redis allowlisted docker facts and the `docker diff` digest/line count; the worker image ids as
  full immutable `sha256:` ids.
No path under /srv/zeus/secrets is opened or hashed; no environment value is read. A required fact that cannot be read
is never dropped silently: the record is `complete: false` and `incomplete` names the field.
All external interfaces go through `Env` (`run` plus the injectable roots), so tests use synthetic paths.
usage (cwd compare/): python3 -m rehearsal.r0 OUT.json    (exit 0 complete, 1 incomplete)
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
MANAGED_FILES = ("managed-launch.json", "controller-state.json", "startup-receipt.json", "descriptor.json")
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
    now: Callable = lambda: datetime.datetime.now(datetime.timezone.utc).isoformat()  # noqa: E731

    @property
    def secrets(self) -> str:
        return os.path.join(self.srv, "secrets")


class Recorder:
    def __init__(self, env: Env):
        self.env = env
        self.missing: set[str] = set()

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

    def managed(self) -> tuple[dict, dict, dict]:
        """(per-invocation ids, stable payload binding, payload release facts by dir)."""
        ids, stable, revisions, paths = {}, {}, set(), set()
        for name in MANAGED_FILES:
            path = os.path.join(self.env.srv, "runtime", "managed-fleet", name)
            try:
                with open(path) as fh:
                    doc = json.load(fh)
            except (OSError, ValueError) as exc:
                self.miss(f"managed:{name}")
                ids[name] = f"unreadable:{type(exc).__name__}"
                continue
            ids[name] = {k: v for k, v in doc.items() if isinstance(v, (str, int, bool)) and (
                "instance" in k or "invocation" in k or "revision" in k or "plan" in k
                or k in ("schema", "state", "target_id", "descriptor_sha256"))}
            if isinstance(doc.get("revision"), str) and re.fullmatch(r"[0-9a-f]{40}", doc["revision"]):
                revisions.add(doc["revision"])
            for key, value in doc.items():
                if isinstance(value, str) and value.startswith("/") and not self.is_secret(value):
                    found = re.match(r"(.*/releases/[0-9a-f]{40})(?:/|$)", value)
                    if found:
                        paths.add(found.group(1))
        if not revisions:
            self.miss("managed_payload:revision")
        locations = set(paths)
        for rev in sorted(revisions):
            candidate = os.path.join(self.env.srv, "releases", rev)
            if os.path.isdir(candidate):
                locations.add(candidate)
            elif not any(p.endswith(rev) for p in paths):
                self.miss(f"managed_payload:location:{rev}")
        if revisions and not locations:
            self.miss("managed_payload:location")
        payload = {}
        for location in sorted(locations):
            facts = self.release_facts(location)
            payload[location] = facts
            runtime = facts.get("runtime")
            if isinstance(runtime, dict) and revisions and runtime.get("revision") not in revisions:
                self.miss(f"managed_payload:revision_mismatch:{location}")
        for name in ("descriptor.json", "startup-receipt.json", "controller-state.json", "managed-launch.json"):
            if isinstance(ids.get(name), dict):
                stable[name] = {k: v for k, v in ids[name].items() if "instance" not in k and "invocation" not in k}
        stable["revisions"] = sorted(revisions)
        stable["locations"] = sorted(locations)
        return ids, stable, payload

    # -- children --

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
        children = []
        for pid in sorted(pids):
            try:
                with open(os.path.join(self.env.proc, str(pid), "cmdline"), "rb") as fh:
                    argv = [a.decode("utf-8", "replace") for a in fh.read().split(b"\0") if a][:3]  # argv[0..2] ONLY
                children.append({"pid": pid, "argv": argv})
            except FileNotFoundError:
                children.append({"pid": pid, "gone": True})  # exited between the two reads
            except OSError:
                self.miss(f"cmdline:{unit}:{pid}")
                children.append({"pid": pid, "unreadable": True})
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
        st["DropIns"] = drop
        st["DropInDir"] = rec.dropin_dir(unit, frag) if frag else None
        st["EnvironmentFiles"] = sorted(set(re.findall(r"(/[^\s;]+)", st.get("EnvironmentFiles", ""))))  # PATHS only
        record["stable"][unit] = st
        record["per_invocation"][unit] = pi
        record["per_invocation"].setdefault("children", {})[unit] = rec.children(unit)
        releases.update(re.findall(f"({release_re})", st.get("ExecStart", "") + " " + st.get("WorkingDirectory", "")))
    current = os.path.realpath(os.path.join(env.srv, "releases", "current"))
    releases.add(current)
    ids, payload_binding, payload_releases = rec.managed()
    record["stable"]["releases"] = {r: rec.release_facts(r) for r in sorted(releases)}
    record["stable"]["releases_current"] = current
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
    if len(sys.argv) != 2:
        raise SystemExit("usage: python3 -m rehearsal.r0 OUT.json")
    sys.exit(main(sys.argv[1]))
