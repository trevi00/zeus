"""Measure symptom A: the published port that refuses connections from inside WSL only.

Symptom A, from the ledger: inside WSL, `127.0.0.1:<published port>` refuses a connection for the
whole 30s readiness bound while the container is up. Seven occurrences are recorded under
`docs/zeus/evidence/environment-runs-{005,009,010,011}`. It had never been reproduced, so its cause
was undetermined.

Four measurements, each a subcommand. They are separate because they answer different questions and
because the first two are the ones that establish the mechanism:

    reproduce   Hold a port inside the distro, publish that same port, and watch all three vantages.
                Then release the occupant and keep watching. If the port is still refused after the
                collision is gone, the relay never retried - which is symptom A.
    sockets     The same run, but reading the socket tables on both sides instead of the verdict, so
                the claim is "nothing in the distro was listening while Windows was", not "it was
                refused".
    residual    What the fix does not cover: a port in the choice window that a program binds during
                the gap between this process proving it free and the daemon publishing it.
    after-fix   Start real stacks through VerificationServices and record which ports came out.

Run from a zeus checkout. `reproduce`, `sockets` and `residual` only mean anything inside WSL, where
the distro and the Windows host are different places; they will run elsewhere and say so.

Nothing here touches an operational container: every container it starts carries its own name and is
removed on the way out, and the compose stacks come from VerificationServices' own teardown.
"""
from __future__ import annotations

import json
import pathlib
import socket
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from codex_harness.adapters import port_diagnosis, published_ports  # noqa: E402

IMAGE = "redis:7-alpine"
INSIDE = "6379"


def run(argv, timeout=120):
    done = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=timeout)
    return done.returncode, (done.stdout or "").strip(), (done.stderr or "").strip()


def ephemeral_range():
    try:
        with open("/proc/sys/net/ipv4/ip_local_port_range", encoding="utf-8") as stream:
            return [int(value) for value in stream.read().split()[:2]]
    except OSError:
        return None


def a_port_both_sides_draw_from():
    """A port free right now and inside the range the daemon and the distro both take from."""
    for _ in range(300):
        probe = socket.socket()
        probe.bind(("127.0.0.1", 0))
        chosen = probe.getsockname()[1]
        probe.close()
        if 49152 <= chosen <= 60999:
            return chosen
    raise SystemExit("no candidate port in the overlap")


def wait_running(name, seconds=10.0):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        _, state, _ = run(["docker", "inspect", "-f", "{{.State.Running}}", name])
        if state == "true":
            return True
        time.sleep(0.5)
    return False


def look(port, name, note):
    seen = port_diagnosis.observe(port, service="redis", container=name, seconds=10)
    return {"at": note, "verdict": seen["verdict"],
            "reachable": {vantage: observation.get("reachable")
                          for vantage, observation in seen["observations"].items()}}


def reproduce():
    name = "zeus-symptom-a-reproduce"
    run(["docker", "rm", "-f", name])
    port = a_port_both_sides_draw_from()
    steps = []

    occupant = socket.socket()
    occupant.bind(("127.0.0.1", port))     # bound, not listening: what an outbound socket looks like
    steps.append({"at": "occupant holds the port in the distro", "port": port})

    code, _, _ = run(["docker", "run", "-d", "--name", name, "-p", f"127.0.0.1:{port}:{INSIDE}",
                      IMAGE])
    steps.append({"at": "docker publishes that same port", "exit_code": code, "published": code == 0})
    if code != 0:
        occupant.close()
        run(["docker", "rm", "-f", name])
        return {"port": port, "steps": steps, "conclusion": "the daemon refused to publish"}

    wait_running(name)
    steps.append(look(port, name, "while the occupant holds it"))
    occupant.close()
    time.sleep(5.0)
    steps.append(look(port, name, "5s after the occupant let go"))
    time.sleep(25.0)
    steps.append(look(port, name, "30s after the occupant let go"))

    run(["docker", "restart", name])
    wait_running(name)
    time.sleep(3.0)
    steps.append(look(port, name, "after a container restart, port long free"))

    control = "zeus-symptom-a-control"
    run(["docker", "rm", "-f", control])
    free = a_port_both_sides_draw_from()
    code, _, _ = run(["docker", "run", "-d", "--name", control, "-p", f"127.0.0.1:{free}:{INSIDE}",
                      IMAGE])
    if code == 0 and wait_running(control):
        time.sleep(1.0)
        steps.append(look(free, control, "control: a port nobody held"))
    run(["docker", "rm", "-f", control])
    run(["docker", "rm", "-f", name])
    return {"port": port, "control_port": free, "ephemeral_range": ephemeral_range(), "steps": steps}


def sockets():
    name = "zeus-symptom-a-sockets"
    run(["docker", "rm", "-f", name])
    port = a_port_both_sides_draw_from()

    def distro(port):
        _, out, _ = run(["ss", "-tan"])
        rows = [line.split() for line in out.splitlines()[1:]]
        return [{"state": row[0], "local": row[3]} for row in rows
                if len(row) > 3 and row[3].endswith(f":{port}")]

    def windows(port):
        _, out, _ = run(["powershell.exe", "-NoProfile", "-Command",
                         f"(Get-NetTCPConnection -LocalPort {port} -State Listen "
                         f"-ErrorAction SilentlyContinue | Measure-Object).Count"])
        return out.strip()

    def snapshot(note):
        return {"at": note, "distro_sockets": distro(port), "windows_listeners": windows(port),
                "connect_from_distro": port_diagnosis._tcp_here(port, 2.0)["reachable"]}

    occupant = socket.socket()
    occupant.bind(("127.0.0.1", port))
    steps = [snapshot("occupant bound, no container yet")]

    code, _, _ = run(["docker", "run", "-d", "--name", name, "-p", f"127.0.0.1:{port}:{INSIDE}",
                      IMAGE])
    wait_running(name)
    time.sleep(1.0)
    steps.append(snapshot("container up, occupant still holding"))

    occupant.close()
    time.sleep(5.0)
    steps.append(snapshot("5s after the occupant closed"))
    time.sleep(25.0)
    steps.append(snapshot("30s after the occupant closed"))

    run(["docker", "restart", name])
    wait_running(name)
    time.sleep(3.0)
    steps.append(snapshot("after a container restart"))

    run(["docker", "rm", "-f", name])
    return {"port": port, "docker_run_exit": code, "steps": steps}


def residual():
    """The gap the fix leaves: a deliberate bind between proving a port free and publishing it."""
    name = "zeus-residual-probe"
    run(["docker", "rm", "-f", name])
    span = published_ports.window()
    port = published_ports.choose(1)[0]

    occupant = socket.socket()
    occupant.bind(("127.0.0.1", port))          # appears in the gap; no allocator can do this here
    code, _, err = run(["docker", "run", "-d", "--name", name, "-p", f"127.0.0.1:{port}:{INSIDE}",
                        IMAGE])
    record = {"port": port, "choice_window": list(span), "docker_run_exit": code,
              "daemon_refused_to_publish": code != 0}
    if code == 0:
        wait_running(name)
        occupant.close()
        time.sleep(3.0)
        record["after_occupant_released"] = look(port, name, "occupant gone, container up")
    else:
        occupant.close()
        record["daemon_named_the_port"] = ("in use" in err.lower() or "already allocated" in err.lower())
    run(["docker", "rm", "-f", name])
    return record


def after_fix(rounds=3):
    from codex_harness.adapters.artifacts import FileArtifacts
    from codex_harness.adapters.verification import VerificationServices

    span = published_ports.window()
    allocator = ephemeral_range()
    cycles = []
    for index in range(rounds):
        with tempfile.TemporaryDirectory() as room:
            room = pathlib.Path(room)
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
    return {"choice_window": list(span), "ephemeral_range": allocator, "cycles": cycles,
            "note": "ports are read back from `compose port`, never assumed from the choice"}


COMMANDS = {"reproduce": reproduce, "sockets": sockets, "residual": residual}

if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else "reproduce"
    destination = pathlib.Path(sys.argv[2]) if len(sys.argv) > 2 else None
    if what == "after-fix":
        payload = after_fix(int(sys.argv[3]) if len(sys.argv) > 3 else 3)
    else:
        payload = COMMANDS[what]()
    payload["measured_on"] = {"platform": sys.platform, "ephemeral_range": ephemeral_range()}
    text = json.dumps(payload, indent=1, ensure_ascii=False)
    if destination:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(text, encoding="utf-8")
    print(text)
