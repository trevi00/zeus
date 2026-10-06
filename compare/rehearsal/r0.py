#!/usr/bin/env python3
"""Cutover RH-7 (owner, read-only): the R0 DEPLOYMENT/rollback baseline of every persistent Zeus unit on aibox.

Rehearsal design R0 + plan RH-7 (critique #7: stable vs per-invocation fields). Records, never reads values:
- per unit (persistent zeus-aibox* units whose FragmentPath is under /etc/systemd/system, plus zeus-aibox.target):
  allowlisted `systemctl show` properties; the fragment sha256; each drop-in (name, inode, size, sha256);
  EnvironmentFiles PATHS only (never their content or digest);
- per release dir named by an ExecStart: runtime.json (revision, tree, built_at), pyvenv.cfg sha256, the zeus-harness
  dist-info RECORD sha256 and the interpreter realpath; releases/current;
- managed-fleet state ids (selected id fields only), host-activation.json sha256, the lane names;
- zeus-aibox-postgres/redis allowlisted docker facts and the `docker diff` digest/line count; worker image ids.
No path under /srv/zeus/secrets is opened or hashed; no environment value is read.
usage: r0_record.py OUT.json
"""
import glob
import hashlib
import json
import os
import re
import subprocess
import sys
import datetime

SECRETS = "/srv/zeus/secrets"
STABLE = ("Id", "LoadState", "UnitFileState", "FragmentPath", "DropInPaths", "ExecStart", "EnvironmentFiles", "User",
          "Group", "UMask", "Restart", "KillMode", "Type", "WorkingDirectory", "Triggers", "TriggeredBy", "Wants",
          "Requires", "PartOf")
PER_INVOCATION = ("ActiveState", "SubState", "InvocationID", "MainPID", "ExecMainPID", "NRestarts",
                  "ExecMainStartTimestampMonotonic", "ActiveEnterTimestampMonotonic", "NeedDaemonReload")


def sh(*argv):
    return subprocess.run(argv, capture_output=True, text=True, timeout=60).stdout


def sha(path):
    if os.path.realpath(path).startswith(SECRETS):
        raise SystemExit("refused: a secrets path")
    try:
        with open(path, "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()
    except OSError as exc:
        return f"unreadable:{type(exc).__name__}"


LIST_PROPS = ("DropInPaths", "Triggers", "TriggeredBy", "Wants", "Requires", "PartOf")


def show(unit, props):
    out = sh("systemctl", "show", unit, *[f"-p{p}" for p in props])
    facts = dict(line.split("=", 1) for line in out.splitlines() if "=" in line)
    for key in LIST_PROPS:  # systemd prints these unordered: sort for a deterministic record
        if key in facts:
            facts[key] = " ".join(sorted(facts[key].split()))
    if "ExecStart" in facts:  # keep path and argv only; start_time/stop_time/pid/code/status are per run
        facts["ExecStart"] = re.sub(r" ; (start_time|stop_time|pid|code|status)=[^;}]*", "", facts["ExecStart"])
    return facts


def units():
    names = sorted({line.split()[0] for line in sh("systemctl", "list-unit-files", "--no-legend", "zeus-aibox*").splitlines()
                    if line.strip()})
    keep = []
    for name in names:
        frag = show(name, ("FragmentPath",)).get("FragmentPath", "")
        if frag.startswith("/etc/systemd/system/") or name == "zeus-aibox.target":
            keep.append(name)
    return keep


def env_paths(raw):
    # EnvironmentFiles= prints "<path> (ignore_errors=no)" entries; keep the PATHS only.
    return sorted(set(re.findall(r"(/[^\s;]+)", raw)))


def release_facts(rev_dir):
    facts = {"dir": rev_dir}
    try:
        rt = json.load(open(os.path.join(rev_dir, "runtime.json")))
        facts["runtime"] = {k: rt.get(k) for k in ("revision", "tree", "built_at")}
    except (OSError, ValueError) as exc:
        facts["runtime"] = f"unreadable:{type(exc).__name__}"
    facts["pyvenv_cfg_sha256"] = sha(os.path.join(rev_dir, ".venv", "pyvenv.cfg"))
    records = sorted(glob.glob(os.path.join(rev_dir, ".venv", "lib", "python*", "site-packages", "zeus_harness-*.dist-info", "RECORD")))
    facts["dist_record_sha256"] = [sha(r) for r in records]
    facts["interpreter_realpath"] = os.path.realpath(os.path.join(rev_dir, ".venv", "bin", "python"))
    return facts


def main(out):
    record = {"schema": "zeus:aibox-migration-001:rehearsal:r0:1",
              "at": datetime.datetime.now(datetime.timezone.utc).isoformat(), "stable": {}, "per_invocation": {}}
    releases = set()
    for unit in units():
        st = show(unit, STABLE)
        pi = show(unit, PER_INVOCATION)
        frag = st.get("FragmentPath", "")
        drop = []
        for path in sorted(p for p in st.get("DropInPaths", "").split() if p):
            try:
                s = os.stat(path)
                drop.append({"path": path, "inode": s.st_ino, "size": s.st_size, "sha256": sha(path)})
            except OSError as exc:
                drop.append({"path": path, "error": type(exc).__name__})
        st["FragmentSha256"] = sha(frag) if frag else None
        st["DropIns"] = drop
        st["EnvironmentFiles"] = env_paths(st.get("EnvironmentFiles", ""))
        record["stable"][unit] = st
        record["per_invocation"][unit] = pi
        releases.update(re.findall(r"(/srv/zeus/releases/[0-9a-f]{40})", st.get("ExecStart", "")))
    current = os.path.realpath("/srv/zeus/releases/current")
    releases.add(current)
    record["stable"]["releases"] = {r: release_facts(r) for r in sorted(releases)}
    record["stable"]["releases_current"] = current
    mf = {}
    for name in ("managed-launch.json", "controller-state.json", "startup-receipt.json", "descriptor.json"):
        path = os.path.join("/srv/zeus/runtime/managed-fleet", name)
        try:
            d = json.load(open(path))
            mf[name] = {k: v for k, v in d.items() if isinstance(v, (str, int, bool)) and (
                "instance" in k or "invocation" in k or "revision" in k or k in ("schema", "state", "target_id", "descriptor_sha256"))}
        except (OSError, ValueError) as exc:
            mf[name] = f"unreadable:{type(exc).__name__}"
    record["per_invocation"]["managed_fleet"] = mf
    record["stable"]["host_activation_sha256"] = sha("/srv/zeus/runtime/control/host-activation.json")
    record["stable"]["lanes"] = sorted(os.listdir("/srv/zeus/runtime/lanes"))
    containers = {}
    for name in ("zeus-aibox-postgres", "zeus-aibox-redis"):
        fmt = '{"Id":{{json .Id}},"Image":{{json .Image}},"StartedAt":{{json .State.StartedAt}},"RestartCount":{{json .RestartCount}},"ExecIDs":{{json .ExecIDs}}}'
        raw = sh("docker", "inspect", "--format", fmt, name).strip()
        try:
            facts = json.loads(raw)
            facts["ExecIDs"] = len(facts.get("ExecIDs") or [])
        except ValueError:
            facts = {"error": "inspect_unreadable"}
        diff = sorted(sh("docker", "diff", name).splitlines())  # docker prints the change list unordered
        facts["diff_lines"] = len(diff)
        facts["diff_sha256"] = hashlib.sha256("\n".join(diff).encode()).hexdigest()
        containers[name] = facts
    record["per_invocation"]["containers"] = {k: {x: v[x] for x in ("StartedAt", "RestartCount", "ExecIDs", "diff_lines", "diff_sha256") if x in v} for k, v in containers.items()}
    record["stable"]["containers"] = {k: {x: v[x] for x in ("Id", "Image") if x in v} for k, v in containers.items()}
    record["stable"]["worker_images"] = sorted(line for line in sh("docker", "image", "ls", "--format", "{{.Repository}}:{{.Tag}} {{.ID}}", "zeus-worker").splitlines() if line)
    with open(out, "x") as fh:
        json.dump(record, fh, indent=1, sort_keys=True)
        fh.write("\n")
    print(json.dumps({"out": out, "units": len(record["stable"]) , "releases": sorted(record["stable"]["releases"])}))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: r0_record.py OUT.json")
    main(sys.argv[1])
