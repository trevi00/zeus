"""Measure symptom A: the published port that refuses connections from inside WSL only.

Symptom A, from the ledger: inside WSL, `127.0.0.1:<published port>` refuses a connection for the
whole 30s readiness bound while the container is up. Seven occurrences are recorded under
`docs/zeus/evidence/environment-runs-{005,009,010,011}`. It had never been reproduced, so its cause
was undetermined. This reproduces the same symptom deliberately and reads the mechanism off the
socket tables; what it does **not** do is establish what held the port in those seven runs, because
nobody collected that at the time.

Five measurements, each a subcommand:

    reproduce     Hold a port inside the distro, publish that same port, watch all three vantages.
                  Then let go and keep watching: still refused means the occupant is not the refuser.
    sockets       The same run read as socket tables on both sides, so the claim is "nothing in the
                  distro was listening while Windows was" rather than "it was refused".
    directions    Which side's occupant the daemon notices: Windows-side held, versus distro-side
                  held. These are not symmetric and the difference decides what a check must cover.
    residual      What the mitigation does not cover: a port in the choice window bound on purpose in
                  the gap between proving it free and publishing it.
    after-fix     Start real stacks through VerificationServices and record what they published.

`reproduce`, `sockets`, `directions` and `residual` only mean anything inside WSL, where the distro
and the Windows host are different places.

**Ownership.** Every container is created with a name nobody else can be using - a fresh uuid - and a
`zeus.probe` label, and only the id that `docker run` handed back is ever removed. Nothing is deleted
by name beforehand, so two of these running at once cannot take each other's containers, and an
operational container is never a candidate. Creation, observation and removal sit in one `finally`,
and what the removal did - including failing - is part of the record.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import random
import socket
import subprocess
import sys
import tempfile
import time
import uuid

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from codex_harness.adapters import port_diagnosis, published_ports  # noqa: E402

IMAGE = "redis:7-alpine"
INSIDE = "6379"
RUN_ID = uuid.uuid4().hex[:12]


def run(argv, timeout=120):
    done = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=timeout)
    return done.returncode, (done.stdout or "").strip(), (done.stderr or "").strip()


class Container:
    """One container this run owns: created here, removed here, and reported either way.

    It is addressed by the id `docker run` returned, never by the name. A name can belong to somebody
    else's container; an id from this creation cannot.
    """

    def __init__(self, port):
        self.name = f"zeus-probe-{RUN_ID}-{uuid.uuid4().hex[:8]}"
        self.port = port
        self.id = None
        self.start_exit = None
        self.start_refused_port = False
        self.cleanup = {"attempted": False, "removed": None, "error": None}

    def __enter__(self):
        code, out, err = run(["docker", "run", "-d", "--name", self.name,
                              "--label", f"zeus.probe={RUN_ID}",
                              "-p", f"127.0.0.1:{self.port}:{INSIDE}", IMAGE])
        self.start_exit = code
        if code == 0:
            self.id = out.splitlines()[-1].strip() if out else None
        else:
            lowered = err.lower()
            self.start_refused_port = ("already allocated" in lowered or "in use" in lowered
                                       or "bind" in lowered)
        return self

    def __exit__(self, *_):
        if self.id is None:
            # Nothing was created, so there is nothing of ours to remove. A failed start does not
            # license deleting whatever happens to carry the name.
            self.cleanup = {"attempted": False, "removed": None, "error": "nothing_was_created"}
            return False
        self.cleanup["attempted"] = True
        try:
            code, _, err = run(["docker", "rm", "-f", self.id])
            self.cleanup["removed"] = code == 0
            self.cleanup["error"] = None if code == 0 else "remove_failed"
        except (OSError, subprocess.SubprocessError) as exc:
            self.cleanup["removed"] = False
            self.cleanup["error"] = type(exc).__name__
        return False

    def running(self, seconds=10.0):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            _, state, _ = run(["docker", "inspect", "-f", "{{.State.Running}}", self.id])
            if state == "true":
                return True
            time.sleep(0.5)
        return False

    def report(self):
        return {"name": self.name, "started": self.id is not None, "start_exit": self.start_exit,
                "cleanup": self.cleanup}


class Occupant:
    """A port held inside this distro the way an outbound socket holds one: bound, not listening."""

    def __init__(self, port):
        self.port = port
        self.socket = socket.socket()

    def __enter__(self):
        self.socket.bind(("127.0.0.1", self.port))
        return self

    def release(self):
        try:
            self.socket.close()
        except OSError:
            pass

    def __exit__(self, *_):
        self.release()
        return False


def ephemeral_range():
    try:
        with open("/proc/sys/net/ipv4/ip_local_port_range", encoding="utf-8") as stream:
            return [int(value) for value in stream.read().split()[:2]]
    except OSError:
        return None


OVERLAP = (49152, 60999)


def a_port_both_sides_draw_from():
    """A port free right now, inside the range the daemon and the distro both draw from.

    Asking the OS for port 0 and hoping it lands in the overlap is not a search: Windows hands out
    ephemeral ports in sequence and can sit above the overlap for a whole session, which is exactly
    where 300 of those hopes failed. This binds candidates in the band instead.
    """
    picker = random.Random()
    for _ in range(400):
        candidate = picker.randint(*OVERLAP)
        probe = socket.socket()
        try:
            probe.bind(("127.0.0.1", candidate))
        except OSError:
            continue
        finally:
            probe.close()
        return candidate
    raise SystemExit(f"no free port found in {OVERLAP[0]}-{OVERLAP[1]}")


def look(port, container, note):
    seen = port_diagnosis.observe(port, service="redis", container=container, seconds=10)
    return {"at": note, "verdict": seen["verdict"],
            "reachable": {vantage: observation.get("reachable")
                          for vantage, observation in seen["observations"].items()}}


def reproduce():
    port = a_port_both_sides_draw_from()
    steps, control_report, free = [], None, None
    with Occupant(port) as occupant, Container(port) as box:
        steps.append({"at": "occupant holds the port in the distro", "port": port})
        steps.append({"at": "docker publishes that same port", "exit_code": box.start_exit,
                      "published": box.id is not None})
        if box.id is not None:
            box.running()
            steps.append(look(port, box.id, "while the occupant holds it"))
            occupant.release()
            time.sleep(5.0)
            steps.append(look(port, box.id, "5s after the occupant let go"))
            time.sleep(25.0)
            steps.append(look(port, box.id, "30s after the occupant let go"))
            run(["docker", "restart", box.id])
            box.running()
            time.sleep(3.0)
            steps.append(look(port, box.id, "after a container restart, port long free"))
        boxes = [box]
    # Reports are taken after the block: `cleanup` only says anything once __exit__ has run.
    held = boxes[0].report()

    free = a_port_both_sides_draw_from()
    with Container(free) as control:
        if control.id is not None and control.running():
            time.sleep(1.0)
            steps.append(look(free, control.id, "control: a port nobody held"))
    control_report = control.report()

    return {"port": port, "control_port": free, "ephemeral_range": ephemeral_range(),
            "steps": steps, "containers": [held, control_report]}


def sockets():
    port = a_port_both_sides_draw_from()

    def distro():
        _, out, _ = run(["ss", "-tan"])
        rows = [line.split() for line in out.splitlines()[1:]]
        return [{"state": row[0], "local": row[3]} for row in rows
                if len(row) > 3 and row[3].endswith(f":{port}")]

    def windows():
        _, out, _ = run(["powershell.exe", "-NoProfile", "-Command",
                         f"(Get-NetTCPConnection -LocalPort {port} -State Listen "
                         f"-ErrorAction SilentlyContinue | Measure-Object).Count"])
        return out.strip()

    def snapshot(note):
        return {"at": note, "distro_sockets": distro(), "windows_listeners": windows(),
                "connect_from_distro": port_diagnosis._tcp_here(port, 2.0)["reachable"]}

    steps = []
    with Occupant(port) as occupant, Container(port) as box:
        steps.append(snapshot("occupant bound, no container yet"))
        if box.id is not None:
            box.running()
            time.sleep(1.0)
            steps.append(snapshot("container up, occupant still holding"))
            occupant.release()
            time.sleep(5.0)
            steps.append(snapshot("5s after the occupant closed"))
            time.sleep(25.0)
            steps.append(snapshot("30s after the occupant closed"))
            run(["docker", "restart", box.id])
            box.running()
            time.sleep(3.0)
            steps.append(snapshot("after a container restart"))
    return {"port": port, "docker_run_exit": box.start_exit, "steps": steps,
            "containers": [box.report()]}


def directions():
    """Does the daemon notice an occupant on **this** side? Run on both sides to get both answers.

    `socket.bind` here holds a port on whichever side this process is on - the distro when run inside
    WSL, Windows when run there. So this measures one leg, names which leg it was, and the pair of
    runs gives the comparison. Holding the far side over interop would be a third process whose
    timing this could not vouch for, and the answer does not need one.
    """
    side = published_ports.here()
    port = a_port_both_sides_draw_from()
    with Occupant(port) as occupant, Container(port) as box:
        record = {"held_on": side, "port": port,
                  "daemon_refused_to_publish": box.id is None,
                  "daemon_named_the_port": box.start_refused_port,
                  "docker_run_exit": box.start_exit}
        if box.id is not None:
            box.running()
            record["while_held"] = look(port, box.id, "occupant still holding")
            occupant.release()
            time.sleep(3.0)
            record["after_release"] = look(port, box.id, "occupant gone, container up")
        record["means"] = ("the daemon refused, so this side needs no prediction"
                           if box.id is None else
                           "the daemon published anyway, so an occupant on this side fails silently")
    record["containers"] = [box.report()]
    return record


def residual():
    """The gap the mitigation leaves: a deliberate bind between proving a port free and publishing."""
    span = published_ports.window()
    chosen = published_ports.choose(1)
    if chosen["ports"] is None:
        return {"skipped": "no port was offered", "fallback": chosen["fallback"]}
    port = chosen["ports"][0]

    with Occupant(port) as occupant, Container(port) as box:
        record = {"port": port, "choice_window": list(span[:2]),
                  "choice": {key: value for key, value in chosen.items() if key != "ports"},
                  "docker_run_exit": box.start_exit,
                  "daemon_refused_to_publish": box.id is None}
        if box.id is not None:
            box.running()
            occupant.release()
            time.sleep(3.0)
            record["after_occupant_released"] = look(port, box.id, "occupant gone, container up")
    record["containers"] = [box.report()]
    return record


def after_fix(rounds=3):
    from codex_harness.adapters.artifacts import FileArtifacts
    from codex_harness.adapters.verification import VerificationServices

    span = published_ports.window()
    allocator = ephemeral_range()
    cycles = []
    for index in range(rounds):
        with tempfile.TemporaryDirectory(prefix="zeus-afterfix-") as scratch:
            room = pathlib.Path(scratch)
            services = VerificationServices(room / "verification", FileArtifacts(room / "artifacts"))
            with services as endpoints:
                postgres = int(endpoints["database_url"].rsplit(":", 1)[1].split("/")[0])
                redis = int(endpoints["redis_url"].rsplit(":", 1)[1].split("/")[0])
                container = services._command("ps", "-q", "postgres", timeout=20).strip()
                seen = port_diagnosis.observe(postgres, service="postgres", container=container,
                                              seconds=10)
                cycles.append({
                    "cycle": index, "postgres_port": postgres, "redis_port": redis,
                    "inside_choice_window": [bool(span[0] <= p <= span[1])
                                             for p in (postgres, redis)],
                    "inside_ephemeral_range": ([bool(allocator[0] <= p <= allocator[1])
                                                for p in (postgres, redis)] if allocator else None),
                    "verdict": seen["verdict"],
                    "reachable": {v: o.get("reachable") for v, o in seen["observations"].items()}})
    return {"choice_window": list(span[:2]), "window_source": span[2],
            "ephemeral_range": allocator, "cycles": cycles,
            "note": "ports are read back from `compose port`, never assumed from the choice"}


COMMANDS = {"reproduce": reproduce, "sockets": sockets, "directions": directions,
            "residual": residual}

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("what", nargs="?", default="reproduce",
                        choices=[*COMMANDS, "after-fix"])
    parser.add_argument("out", nargs="?")
    parser.add_argument("rounds", nargs="?", type=int, default=3)
    args = parser.parse_args()

    payload = after_fix(args.rounds) if args.what == "after-fix" else COMMANDS[args.what]()
    payload["run_id"] = RUN_ID
    payload["measured_on"] = {"platform": sys.platform, "side": published_ports.here(),
                              "ephemeral_range": ephemeral_range()}
    text = json.dumps(payload, indent=1, ensure_ascii=False)
    if args.out:
        destination = pathlib.Path(args.out)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(text, encoding="utf-8")
    print(text)
