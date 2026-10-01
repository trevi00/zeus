"""ACCEPTANCE A56 (W2b, runtime): the isolated connectivity test of DESIGN §7. Owner-run; skipped unless
`TOKOBS_CONNTEST=1`.

Project `zeus-tokobs-conntest`: `compose.yaml` + `compose.conntest.yaml` (Grafana on 127.0.0.1:13300, a fixture
collector that mounts no worker input and no /data), a temporary admin secret under `tmp_path`, and throwaway
containers on the default bridge named `zeus-tokobs-conntest-x<random>-*`. Nothing here touches the production project
`zeus-tokobs`, `/srv`, the artifacts tree or any foreign Docker object: a pre-existing object of the test project makes
the test FAIL before anything is started, and cleanup removes only what this run created.

The admin password lives only in this process: it is never printed, put on a command line or put in a message.
The Grafana container runs as uid 1000 and reads a 0600 secret, so the test must run as uid 1000 (the operator).
"""

import base64
import json
import os
import secrets
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import pytest
import yaml
from tokobs.deploy_lint import lint_compose, lint_inspect

pytestmark = pytest.mark.skipif(os.environ.get("TOKOBS_CONNTEST") != "1",
                                reason="owner-run: needs Docker (DESIGN §7 isolated connectivity test)")

ROOT = Path(__file__).resolve().parents[2]
DEPLOY = ROOT / "deploy" / "observability"
PROJECT = "zeus-tokobs-conntest"
LABEL = f"com.docker.compose.project={PROJECT}"
GRAFANA_PORT, COLLECTOR_PORT, PROMETHEUS_PORT, SINK_PORT = 13300, 9469, 9090, 8000
BASE = f"http://127.0.0.1:{GRAFANA_PORT}"
PROXY = f"{BASE}/api/datasources/proxy/uid/tokobs-prom/api/v1/query"
FORBIDDEN_SOURCES = ("/home/trevi/workspaces/zeus/artifacts", "/srv")
CODE_TARGETS = {"/opt/zeus/tools/token_observability", "/opt/zeus/src"}
WILDCARD_HOSTS = {"0.0.0.0", "[::]", "::", "*"}
# `python -c` probes: exit 0 = connected / resolved, exit 3 = blocked / unresolved; any other exit is a harness fault.
CONNECT_PROBE = ("import socket, sys\n"
                 "try:\n"
                 "    socket.create_connection((sys.argv[1], int(sys.argv[2])), timeout=3).close()\n"
                 "except OSError as exc:\n"
                 "    print('BLOCKED', type(exc).__name__)\n"
                 "    sys.exit(3)\n"
                 "print('CONNECTED')\n")
RESOLVE_PROBE = ("import socket, sys\n"
                 "try:\n"
                 "    socket.getaddrinfo(sys.argv[1], int(sys.argv[2]))\n"
                 "except OSError as exc:\n"
                 "    print('UNRESOLVED', type(exc).__name__)\n"
                 "    sys.exit(3)\n"
                 "print('RESOLVED')\n")


def fail(step: str, detail: str) -> None:
    pytest.fail(f"A56 step {step}: {detail}", pytrace=False)


def run(step, args, *, timeout=60, check=True, env=None):
    """One docker/ss call. Never `shell=True`; a failed check or a timeout fails the named step."""
    try:
        return subprocess.run(args, check=check, timeout=timeout, capture_output=True, text=True, env=env)
    except subprocess.CalledProcessError as exc:
        fail(step, f"{' '.join(args[:4])} exited {exc.returncode}: {(exc.stderr or '').strip()[-400:]}")
    except subprocess.TimeoutExpired:
        fail(step, f"{' '.join(args[:4])} timed out after {timeout}s")


def poll(step, probe, timeout, interval=2.0):
    """Repeat `probe` (returns a truthy value or raises OSError/ValueError/KeyError/IndexError) until `timeout` s."""
    deadline, last = time.monotonic() + timeout, "no attempt"
    while time.monotonic() < deadline:
        try:
            value = probe()
            if value:
                return value
            last = "not yet"
        except (OSError, ValueError, KeyError, IndexError) as exc:
            last = type(exc).__name__
        time.sleep(interval)
    fail(step, f"not ready within {timeout}s (last: {last})")


def listeners(step):
    """`ss -ltnH` as (host, port) pairs of the local address column."""
    pairs = []
    for line in run(step, ["ss", "-ltnH"]).stdout.splitlines():
        columns = line.split()
        if len(columns) >= 4:
            host, _, port = columns[3].rpartition(":")
            if port.isdigit():
                pairs.append((host, int(port)))
    return pairs


def project_objects(step):
    """Containers, networks and volumes carrying the test project's compose label."""
    found = {}
    for kind, args in (("container", ["docker", "ps", "-a", "-q", "--filter", f"label={LABEL}"]),
                       ("network", ["docker", "network", "ls", "-q", "--filter", f"label={LABEL}"]),
                       ("volume", ["docker", "volume", "ls", "-q", "--filter", f"label={LABEL}"])):
        ids = run(step, args).stdout.split()
        if ids:
            found[kind] = ids
    return found


def substitute(expression: str) -> str:
    """Grafana variables to values Prometheus parses (the proxy does not interpolate them)."""
    for old, new in (("$__rate_interval", "5m"), ("$__range", "1h"), ("$__interval", "1m")):
        expression = expression.replace(old, new)
    for name in ("provider", "role", "model", "task_class"):
        expression = expression.replace(f"${name}", ".*")
    return expression


def expressions() -> list[str]:
    found = []
    for group in yaml.safe_load((DEPLOY / "prometheus" / "rules" / "tokobs.yml").read_text())["groups"]:
        found += [rule["expr"] for rule in group["rules"]]
    for path in sorted((DEPLOY / "grafana" / "dashboards").glob("*.json")):
        for panel in json.loads(path.read_text())["panels"]:
            found += [target["expr"] for target in panel.get("targets", [])]
    return [substitute(e) for e in found]


def test_a56_isolated_connectivity(tmp_path):
    # 1. Preconditions: nothing of the test project exists (a foreign object is never cleaned) and the ports are free.
    if project_objects("1 preconditions"):
        fail("1 preconditions", f"objects labelled {LABEL} already exist: {sorted(project_objects('1 preconditions'))}")
    busy = sorted({port for _, port in listeners("1 preconditions")} & {GRAFANA_PORT, COLLECTOR_PORT, PROMETHEUS_PORT})
    if busy:
        fail("1 preconditions", f"host ports already listening: {busy}")
    if os.getuid() != 1000:
        fail("1 preconditions", "must run as uid 1000: the grafana container (uid 1000) reads the 0600 secret")

    # 2. Secret: kept in memory for basic auth only.
    password = secrets.token_urlsafe(24)
    secret_file = tmp_path / "grafana-admin.pass"
    secret_file.write_text(password)
    secret_file.chmod(0o600)
    authorization = "Basic " + base64.b64encode(f"admin:{password}".encode()).decode()

    def http(url):
        request = urllib.request.Request(url, headers={"Authorization": authorization})
        with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310 (fixed loopback http URL)
            return json.loads(response.read())

    def query(expression):
        return http(PROXY + "?" + urllib.parse.urlencode({"query": expression}))

    env = {**os.environ, "TOKOBS_CONNTEST_DIR": str(tmp_path)}
    compose = ["docker", "compose", "-p", PROJECT, "-f", str(DEPLOY / "compose.yaml"),
               "-f", str(DEPLOY / "compose.conntest.yaml")]
    suffix = secrets.token_hex(4)
    created: list[str] = []  # the named containers this run starts outside compose

    def named(role):
        name = f"{PROJECT}-x{suffix}-{role}"
        created.append(name)
        return name

    try:
        # 3. Static config of the resolved override.
        resolved = json.loads(run("3 static config", [*compose, "config", "--format", "json"], env=env).stdout)
        if lint_compose(resolved) != []:
            fail("3 static config", f"lint_compose: {lint_compose(resolved)}")
        collector = resolved["services"]["collector"]
        mounts = collector.get("volumes") or []
        if {m["target"] for m in mounts} != CODE_TARGETS:
            fail("3 static config", f"collector mounts {sorted(m['target'] for m in mounts)}, not only the code")
        for mount in mounts:
            if mount["target"] not in CODE_TARGETS and str(mount["source"]).startswith(FORBIDDEN_SOURCES):
                fail("3 static config", f"collector mounts a worker input {mount['source']}")
        if "--fixture" not in collector["command"]:
            fail("3 static config", "the collector command lacks --fixture")
        image = collector["image"]

        # 4. Up, and Grafana answers.
        run("4 up", [*compose, "up", "-d"], env=env, timeout=900)
        poll("4 grafana health", lambda: urllib.request.urlopen(f"{BASE}/api/health", timeout=5).status == 200, 120)

        # 5. Through Grafana's datasource proxy: the scrape works and the fixture sample is served.
        def up_is_one():
            result = query('up{job="tokobs"}')["data"]["result"]
            return result and result[0]["value"][1] == "1"

        poll("5 proxy up{job=tokobs}", up_is_one, 180, interval=5)

        def sample():
            result = query("zeus_tokobs_fixture_sample")["data"]["result"]
            return result and float(result[0]["value"][1]) == 42

        poll("5 proxy fixture sample", sample, 120, interval=5)

        # 6. Provisioning.
        poll("6 datasource health", lambda: http(f"{BASE}/api/datasources/uid/tokobs-prom/health")["status"] == "OK", 60)

        def dashboards():
            return {d["uid"] for d in http(f"{BASE}/api/search?type=dash-db")} >= {"zeus-llm-usage", "zeus-tokobs-health"}

        poll("6 dashboards provisioned", dashboards, 90, interval=5)

        # 7. Every rule and dashboard expression parses on the pinned Prometheus.
        bad = []
        for expression in expressions():
            if "$" in expression:
                bad.append(f"unsubstituted variable in {expression}")
                continue
            try:
                status = query(expression).get("status")
            except urllib.error.HTTPError as exc:
                status = f"HTTP {exc.code}"
            except (OSError, ValueError) as exc:
                status = type(exc).__name__
            if status != "success":
                bad.append(f"{status}: {expression}")
        if bad:
            fail("7 expressions", f"{len(bad)} did not return success: {bad[:5]}")

        # 8. Listeners: only 127.0.0.1:13300; nothing on 9469 or 9090; no tokobs port on a wildcard address.
        found = listeners("8 listeners")
        if ("127.0.0.1", GRAFANA_PORT) not in found:
            fail("8 listeners", f"no listener on 127.0.0.1:{GRAFANA_PORT}")
        if any(port in (COLLECTOR_PORT, PROMETHEUS_PORT) for _, port in found):
            fail("8 listeners", f"a listener on {COLLECTOR_PORT} or {PROMETHEUS_PORT}")
        wild = [(h, p) for h, p in found if h in WILDCARD_HOSTS and p in (GRAFANA_PORT, COLLECTOR_PORT, PROMETHEUS_PORT)]
        if wild:
            fail("8 listeners", f"a tokobs port is on a wildcard address: {wild}")

        # 9. Isolation (local only): a sink on the default bridge.
        sink = named("sink")
        run("9 sink", ["docker", "run", "-d", "--name", sink, image, "python", "-m", "http.server", str(SINK_PORT)])
        sink_ip = run("9 sink", ["docker", "inspect", "-f", '{{(index .NetworkSettings.Networks "bridge").IPAddress}}',
                                 sink]).stdout.strip()
        if not sink_ip:
            fail("9 sink", "the sink has no default-bridge address")
        control = named("control")

        def control_connects():
            done = run("9 control", ["docker", "run", "--rm", "--name", control, image, "python", "-c", CONNECT_PROBE,
                                     sink_ip, str(SINK_PORT)], check=False, timeout=30)
            return done.returncode == 0 and "CONNECTED" in done.stdout

        poll("9 control: a default-bridge container reaches the sink", control_connects, 30, interval=1)
        egress = run("9 collector egress", [*compose, "exec", "-T", "collector", "python", "-c", CONNECT_PROBE,
                                            sink_ip, str(SINK_PORT)], env=env, check=False, timeout=30)
        if egress.returncode != 3 or not egress.stdout.startswith("BLOCKED"):
            fail("9 collector egress", f"the collector must have no egress; probe exit {egress.returncode}")
        collector_id = run("9 collector ip", [*compose, "ps", "-q", "collector"], env=env).stdout.strip()
        networks = json.loads(run("9 collector ip", ["docker", "inspect", collector_id]).stdout)[0]["NetworkSettings"]["Networks"]
        (collector_ip,) = [n["IPAddress"] for key, n in networks.items() if key.endswith("_private")]
        outsider = named("outsider")
        reach = run("9 outsider reach", ["docker", "run", "--rm", "--name", outsider, image, "python", "-c",
                                         CONNECT_PROBE, collector_ip, str(COLLECTOR_PORT)], check=False, timeout=30)
        if reach.returncode != 3 or not reach.stdout.startswith("BLOCKED"):
            fail("9 outsider reach", f"a default-bridge container must not reach the collector; exit {reach.returncode}")
        resolver = named("resolver")
        resolve = run("9 outsider resolve", ["docker", "run", "--rm", "--name", resolver, image, "python", "-c",
                                             RESOLVE_PROBE, "collector", str(COLLECTOR_PORT)], check=False, timeout=30)
        if resolve.returncode != 3 or not resolve.stdout.startswith("UNRESOLVED"):
            fail("9 outsider resolve", f"a default-bridge container must not resolve `collector`; exit {resolve.returncode}")

        # 10. Hardening of the three project containers.
        ids = run("10 hardening", [*compose, "ps", "-q"], env=env).stdout.split()
        if len(ids) != 3:
            fail("10 hardening", f"expected 3 project containers, found {len(ids)}")
        inspected = json.loads(run("10 hardening", ["docker", "inspect", *ids]).stdout)
        if lint_inspect(inspected) != []:
            fail("10 hardening", f"lint_inspect: {lint_inspect(inspected)}")

        # 11. Import smoke: the collector's code reads the same checkout's policy (C-W1-8); the value is never written here.
        from codex_harness.domain.policy import POLICY

        smoke = run("11 import smoke", [*compose, "run", "--rm", "--no-deps", "collector", "python", "-B", "-c",
                                        "from tokobs import vocab; print(vocab.codex_idle_seconds())"],
                    env=env, timeout=120)
        if smoke.stdout.strip() != str(2 * POLICY.decision_seconds):
            fail("11 import smoke", f"printed {smoke.stdout.strip()!r}, not 2 x policy decision_seconds")
    finally:
        # 12. Cleanup of this run's objects only, then prove nothing of the project remains.
        run("12 cleanup", [*compose, "down", "-v"], env=env, check=False, timeout=300)
        for name in created:
            run("12 cleanup", ["docker", "rm", "-f", name], check=False)
        leftovers = project_objects("12 cleanup")
        leftover_named = [n for n in created if n in run("12 cleanup", ["docker", "ps", "-a", "--format", "{{.Names}}"]).stdout.split()]
        if leftovers or leftover_named:
            fail("12 cleanup", f"left behind: {leftovers} {leftover_named}")
