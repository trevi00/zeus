#!/usr/bin/env python3
"""Cutover RH-2 (owner): rehearsal Phase P, the ONLY code that names production resources. DRAFT FOR RH-8 REVIEW.

NOT EXECUTED until Codex RH-8 accepts it together with AMD-1 section C (C.1 PG-a stdout dump, C.2 Redis-a volume
copy, C.3 no network, C.5 DB scope, C.6 ordering). Every production touch is a READ:
- P0  pause + quiet gate: monitoring.json sources.fleet.data.paused is true; managed heartbeat active 0 / unresolved 0;
      the pg/redis container facts (allowlisted --format, never Env); the docker diff digest.
- P1  read-only SQL via local trust in the production container: database names; pg_stat_activity counts by
      datname/application_name (no query text).
- P2a per DB in scope (zeus_aibox, zeus_aibox_migration): `pg_dump -Fc` to STDOUT, captured on the host into
      ROOT/p/<db>.d0a.dump (O_EXCL, 0600, 0700 dir). Never `-f` inside the production container.
- P3  the Redis-a helper: a labelled `--network none` container with the redis volume mounted READONLY + volume-nocopy,
      copying appendonlydir + dump.rdb out with before/after stat+sha256 manifests; accepted only if both manifests
      are identical and equal the host sha256 of the copy. Then redis-check-aof (no --fix) on the COPY.
- P2b dump again as d0b (the quiescence bracket around P3).
- P4  repeat P0: container Id/StartedAt/RestartCount equal and docker-diff digest equal.
Never: record_run (it buffers stdout into evidence), a secret read, an environment value, a write to production.
Evidence (names, counts, digests, exit codes; no bodies) goes to the evidence dir; raw copies stay under ROOT.

usage: phase_p.py ROOT EVIDENCE_DIR RUN8          (ROOT and EVIDENCE_DIR must not exist)
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import datetime

PG, REDIS = "zeus-aibox-postgres", "zeus-aibox-redis"
REDIS_VOLUME = "zeus-aibox-redisdata"
REDIS_IMAGE = "redis@sha256:858f009f9709ce576febc734aa78b8f6d624b82571f9ddb6bda4377c833b3499"
DB_SCOPE = ("zeus_aibox", "zeus_aibox_migration")  # AMD-1 C.5; zeus_canary_* inventoried by name only
MONITORING = "/srv/zeus/runtime/control/monitoring.json"
HEARTBEAT = "/srv/zeus/runtime/managed-fleet/heartbeat.json"
INSPECT = ('{"Id":{{json .Id}},"Image":{{json .Image}},"StartedAt":{{json .State.StartedAt}},'
           '"RestartCount":{{json .RestartCount}},"ExecIDs":{{json .ExecIDs}}}')


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def run(argv, **kw):
    return subprocess.run(argv, capture_output=True, text=True, timeout=kw.pop("timeout", 120), **kw)


def gate():
    mon = json.load(open(MONITORING))
    paused = (((mon.get("sources") or {}).get("fleet") or {}).get("data") or {}).get("paused") is True
    hb = json.load(open(HEARTBEAT))
    quiet = hb.get("active") == 0 and hb.get("unresolved") == 0
    facts = {}
    for name in (PG, REDIS):
        raw = json.loads(run(["docker", "inspect", "--format", INSPECT, name]).stdout)
        raw["ExecIDs"] = len(raw.get("ExecIDs") or [])
        diff = sorted(run(["docker", "diff", name]).stdout.splitlines())
        raw["diff_sha256"] = hashlib.sha256("\n".join(diff).encode()).hexdigest()
        facts[name] = raw
    return {"at": now(), "paused": paused, "quiet": quiet, "heartbeat_instance": hb.get("instance_id"),
            "containers": facts}


def psql(sql):
    return run(["docker", "exec", PG, "psql", "-U", "zeus", "-h", "/var/run/postgresql", "-d", "postgres", "-XAtq",
                "-v", "ON_ERROR_STOP=1", "-c", sql])


def dump(db, path):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as out:
        proc = subprocess.run(["docker", "exec", PG, "pg_dump", "-U", "zeus", "-h", "/var/run/postgresql", "-d", db,
                               "-Fc", "--lock-wait-timeout=30000", "--no-password"], stdout=out,
                              stderr=subprocess.PIPE, timeout=3600)
    data = open(path, "rb").read()
    return {"db": db, "exit": proc.returncode, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
            "stderr_lines": len(proc.stderr.splitlines())}


def redis_copy(root, run8):
    out = os.path.join(root, "p", "redis")
    os.makedirs(out, mode=0o700)
    manifest = ("cd /src && find . -type f -print0 | sort -z | xargs -0 sha256sum")
    script = (f"{manifest} > /out/.before && cp -a /src/appendonlydir /src/dump.rdb /out/ 2>/dev/null; "
              f"{manifest} > /out/.after; chown -R {os.getuid()}:{os.getgid()} /out")
    proc = run(["docker", "run", "--rm", "--network", "none", "--label", f"zeus.rehearsal.run={run8}",
                "--name", f"zeus-rh-{run8}-redis-snap", "--memory", "1g",
                "--mount", f"type=volume,src={REDIS_VOLUME},dst=/src,readonly,volume-nocopy",
                "--mount", f"type=bind,src={out},dst=/out", "--entrypoint", "sh", REDIS_IMAGE, "-c", script],
               timeout=900)
    before = open(os.path.join(out, ".before")).read()
    after = open(os.path.join(out, ".after")).read()
    host = run(["sh", "-c", f"cd {out} && find appendonlydir dump.rdb -type f -print0 2>/dev/null | sort -z | "
                            "xargs -0 sha256sum"]).stdout
    norm = lambda text: sorted(re.sub(r"\s+\./", "  ", line) for line in text.splitlines())
    ok = proc.returncode == 0 and before == after and norm(before) == norm(host)
    check = run(["docker", "run", "--rm", "--network", "none", "--label", f"zeus.rehearsal.run={run8}",
                 "--name", f"zeus-rh-{run8}-aof-check", "--memory", "1g",
                 "--mount", f"type=bind,src={out},dst=/c,readonly", "--entrypoint", "sh", REDIS_IMAGE, "-c",
                 "ls /c/appendonlydir/*.manifest >/dev/null 2>&1 && redis-check-aof /c/appendonlydir/*.manifest || true"],
                timeout=900)
    return {"exit": proc.returncode, "manifest_equal": before == after, "copy_equals_manifest": norm(before) == norm(host),
            "files": len(before.splitlines()), "aof_check_exit": check.returncode, "ok": ok}


def main(root, evidence, run8):
    if not re.fullmatch(r"[0-9a-f]{8}", run8):
        raise SystemExit("run8 must be 8 hex")
    if os.path.exists(root) or os.path.exists(evidence):
        raise SystemExit("ROOT and EVIDENCE_DIR must not exist")
    os.makedirs(os.path.join(root, "p"), mode=0o700)
    os.makedirs(evidence, mode=0o700)
    rec = {"schema": "zeus:aibox-migration-001:rehearsal:phase-p:1", "run8": run8, "steps": []}
    p0 = gate()
    rec["steps"].append({"step": "P0", **p0})
    if not (p0["paused"] and p0["quiet"]):
        rec["verdict"] = "refused: Fleet not paused or not quiet"
        return finish(rec, evidence, 1)
    dbs = psql("SELECT datname FROM pg_database ORDER BY 1")
    act = psql("SELECT coalesce(datname,''), coalesce(application_name,''), count(*) FROM pg_stat_activity "
               "GROUP BY 1,2 ORDER BY 1,2")
    rec["steps"].append({"step": "P1", "databases": dbs.stdout.split(), "activity": act.stdout.splitlines(),
                         "exit": [dbs.returncode, act.returncode]})
    rec["steps"].append({"step": "P2a", "dumps": [dump(db, os.path.join(root, "p", f"{db}.d0a.dump")) for db in DB_SCOPE]})
    p3 = redis_copy(root, run8)
    rec["steps"].append({"step": "P3", **p3})
    rec["steps"].append({"step": "P2b", "dumps": [dump(db, os.path.join(root, "p", f"{db}.d0b.dump")) for db in DB_SCOPE]})
    p4 = gate()
    rec["steps"].append({"step": "P4", **p4})
    same = all(p0["containers"][n][k] == p4["containers"][n][k] for n in (PG, REDIS)
               for k in ("Id", "StartedAt", "RestartCount", "diff_sha256"))
    if not p3["ok"]:
        rec["verdict"] = "STOP: the Redis bracket is unequal (the copy is invalid); diagnose before one new attempt"
        return finish(rec, evidence, 1)
    rec["verdict"] = "ok" if same and p4["paused"] and p4["quiet"] else "STOP: production changed during Phase P"
    return finish(rec, evidence, 0 if rec["verdict"] == "ok" else 1)


def finish(rec, evidence, code):
    with open(os.path.join(evidence, "phase-p.json"), "x") as fh:
        json.dump(rec, fh, indent=1, sort_keys=True)
        fh.write("\n")
    print(json.dumps({"verdict": rec["verdict"]}))
    return code


if __name__ == "__main__":
    if len(sys.argv) != 4:
        raise SystemExit("usage: phase_p.py ROOT EVIDENCE_DIR RUN8")
    sys.exit(main(*sys.argv[1:]))
