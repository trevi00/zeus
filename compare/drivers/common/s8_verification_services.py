"""Shared S8 scenario steps (`host_os.verification_services`): M7 `adapters/verification.py` (`VerificationServices` and its attempt/resource machinery),
characterized BEFORE the module moves into HOST_OS (S8 batch B7a, DESIGN-s8 section 32 V34a; R-v1 moves `ENVIRONMENT_KEYS` into it).

Mirrors the adapter tests of M7 `tests/test_verification.py`: `test_isolated_services_cleanup_on_every_exit` (4), `test_stale_cleanup_requires_unchanged_definition_
and_leaves_fresh_stack`, `test_docker_command_uses_generated_project_and_filtered_environment`, `test_cleanup_failure_preserves_primary_error_and_is_retryable`,
`test_invalid_manifest_does_not_block_other_stack_cleanup`, the readiness checks (`..._refuses_a_port_that_accepts_and_cannot_answer`, `..._names_the_refusals_it_saw_
without_quoting_them`, `..._still_refuses_a_port_that_never_accepts`, `..._waits_for_the_answer_rather_than_the_socket`, `..._refuses_a_service_that_is_not_this_
projects`, `..._binds_the_receipt_to_what_answered`, `..._refuses_an_answer_that_arrives_after_the_deadline`, `..._refuses_a_success_that_completed_past_the_deadline`,
`..._returns_even_when_the_service_stops_answering`, `..._refuses_when_the_container_identity_cannot_be_read_in_time`, `..._failure_carries_nothing_back_on_the_
exception_chain`, `..._receipt_separates_the_two_deadlines_and_names_what_is_held`), the attempt machinery (`test_a_timed_out_attempt_takes_back_its_thread_and_its_
socket`, `test_an_attempt_that_cannot_be_taken_back_is_counted_and_then_refused`, `test_the_unreclaimed_limit_is_the_processs_and_does_not_reset_with_a_new_object`,
`test_a_close_that_hangs_does_not_hold_the_caller`, `test_a_resource_registered_after_reclamation_began_is_still_closed`, `test_a_running_attempt_occupies_its_slot_
before_its_worker_starts`, `test_starting_reserves_the_slot_so_running_work_counts_against_the_limit`, `test_a_resource_that_will_not_close_is_kept_and_the_attempt_
stays_owed`, `test_a_resource_registered_after_the_reclaim_window_is_still_taken_back`, `test_a_slot_is_released_only_when_everything_it_owns_is_finished`,
`test_starting_one_attempt_does_not_reclaim_another_that_is_still_running`, `test_a_reservation_is_not_mistaken_for_a_finished_attempt`, `test_a_resource_that_cannot_
say_whether_it_is_shut_is_not_called_closed`, `test_a_resource_with_a_readable_state_still_releases_its_slot`) and the capture (`test_the_capture_of_a_failed_
readiness_has_a_bound_of_its_own`, `test_a_capture_that_itself_fails_narrows_nothing_and_still_names_its_bound`).
Not mirrored: `test_verification_environment_cannot_inherit_production_endpoints` (`verification_environment` lives in `composition.release_verification`, moved ahead
in S7) and `test_real_disposable_database_and_redis_are_isolated_and_removed` (real Docker, opt-in). It adds what they leave out: the constructor's project names and
refusals, `_command`'s timeout floor and refusal, the compose/manifest definition and the receipt, every endpoint refusal, every cleanup failure, `collect_stale` over
a matrix of stacks, `_container_identity`, `_answer` over loopback, `_state_of`/`_Held`/`_Attempt` unit transitions and the failed thread start.

Layer: harness (never shipped)

This module never imports `codex_harness`: everything arrives through `api` (`VerificationServices`, `module` (the verification module: `ATTEMPTS`, the constants,
`_state_of`, `_Held`, `_Attempt`, `_RedisHandle`, `run_process`), `port_diagnosis`, `published_ports`, `ContractError`). The scripted `docker` is a function put where
the module looks `run_process` up (`api.module.run_process`); the artifact store is a recording stand-in; readiness uses REAL loopback sockets (and real psycopg/redis
clients refused by them); the wall clock for `utcnow` is the harness's, while waits and reclaim windows are real time (the reclaim window is shortened through the
module attribute, and its default is recorded first). Environment variables are scripted for the whole run. Temporary paths, the generated passwords and the
loopback ports of this run are replaced by symbolic names (a URL's whole userinfo becomes <USERINFO>); where a peer that drops a connection is seen as a reset or as an end of stream depending on a race (redis over loopback), the scenario records M7's own `_refusal_kind` family (a connection drop) instead of the raw OS message, the same method on both sides; timings are reported as facts about order, never as seconds.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import socket
import threading
import time
import traceback
from pathlib import Path
from types import SimpleNamespace

from s1_common import outcome, relative

SCRIPTED_ENV = {
    "PATH": "/scripted/bin", "HOME": "/scripted/home", "LANG": "C.UTF-8", "TEMP": "/scripted/temp", "http_proxy": "http://scripted-proxy:3128",
    "NO_PROXY": "localhost", "SSL_CERT_FILE": "/scripted/ca.pem", "DOCKER_HOST": "unix:///scripted/docker.sock", "DOCKER_CONTEXT": "scripted",
    "DOCKER_CONFIG": "/scripted/docker", "DOCKER_TLS_VERIFY": "1", "ZEUS_DATABASE_URL": "production", "HARNESS_DATABASE_URL": "production",
    "GH_TOKEN": "secret", "PYTHONPATH": "/scripted/py", "ZEUS_VERIFY_PASSWORD": "inherited-password-replaced",
}
PROJECT_A, PROJECT_B, PROJECT_C = ("zeus-verify-" + c * 32 for c in "abc")
HEX = re.compile(r"zeus-verify-[0-9a-f]{32}")


# ---- stand-ins -------------------------------------------------------------------------------------------------------------------------------------
class Artifacts:
    """Records every `put(body, source)` as parsed JSON; returns a counter reference (M7 callers ignore it)."""

    def __init__(self):
        self.rows = []

    def put(self, body, source, lock_timeout=30):
        self.rows.append({"source": source, "body": json.loads(body)})
        return {"id": len(self.rows)}


class Docker:
    """The scripted `docker`: records every call and answers by verb. `fail` maps a verb to a return code, `fail_projects` maps a project to its failing verbs."""

    def __init__(self, ctx, ports=(45678, 45679), fail=None, fail_projects=None, answers=None):
        self.ctx, self.ports, self.fail, self.fail_projects = ctx, dict(zip(("postgres", "redis"), ports)), fail or {}, fail_projects or {}
        self.answers, self.calls, self.snapshots = answers or {}, [], []

    def __call__(self, argv, cwd=None, env=None, timeout=None, **extra):
        project, files, args = argv[3], argv[5], list(argv[6:])
        verb = args[0]
        directory = Path(cwd) if cwd else None
        snapshot = {}
        if directory is not None and directory.is_dir():
            snapshot = {p.name: p.read_text("utf-8") for p in sorted(directory.iterdir()) if p.is_file() and not p.is_symlink()}
        self.calls.append({"prefix": argv[:3] + [project, argv[4], Path(files).name], "args": args, "cwd": cwd, "timeout": timeout, "env": dict(env or {}),
                           "extra": sorted(extra), "files": sorted(snapshot)})
        if verb == "up":
            self.snapshots.append(snapshot)
        code = self.fail.get(verb, 0) or (1 if verb in self.fail_projects.get(project, ()) else 0)
        key = tuple(args[:2]) if tuple(args[:2]) in self.answers else verb
        if key in self.answers:
            answer = self.answers[key]
            out = answer(args) if callable(answer) else answer
        elif verb == "port":
            out = f"127.0.0.1:{self.ports[args[1]]}\n"
        elif verb == "ps":
            out = f"container-{args[-1]}\n"
        elif verb == "exec" and "psql" in args:
            out = "  7001  \n"
        elif verb == "exec":
            out = "# Server\r\nredis_version:7.4\r\nrun_id:runid-redis\r\n"
        else:
            out = "" if verb != "up" else "started\n"
        return SimpleNamespace(returncode=code, stdout=out, stderr="not recorded")

    def verbs(self):
        return [call["args"][0] for call in self.calls]

    def view(self):
        return [{"prefix": c["prefix"], "args": c["args"], "cwd": c["cwd"], "timeout": c["timeout"], "extra": c["extra"], "files": c["files"],
                 "env": dict(sorted(c["env"].items()))} for c in self.calls]


class Recorded:
    """A resource that only records that it was closed."""

    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class Hanging:
    """A resource whose `close` stops until released."""

    def __init__(self, released):
        self.released, self.closed = released, False

    def close(self):
        self.released.wait(30)
        self.closed = True


class Stubborn:
    """A resource whose close always fails."""

    def __init__(self, pair):
        self.pair, self.attempts = pair, 0

    def close(self):
        self.attempts += 1
        raise OSError("this resource refuses to close")


class Unreadable:
    """A resource that refuses both to close and to say whether it is closed."""

    def __init__(self, pair):
        self.pair, self.asked = pair, 0

    def fileno(self):
        self.asked += 1
        raise OSError("this resource will not say")

    def close(self):
        raise OSError("this resource will not close")


USED_PORTS: set = set()


def bound_socket():
    """A loopback socket on a port no earlier step of this run used (a symbolic name must mean one port)."""
    while True:
        server = socket.socket()
        server.bind(("127.0.0.1", 0))
        port = server.getsockname()[1]
        if port not in USED_PORTS:
            USED_PORTS.add(port)
            return server, port
        server.close()


def listener(behaviour="close_immediately"):
    """A real socket that accepts and then closes (or lingers 50 ms and closes): the port accepts and nothing answers."""
    server, port = bound_socket()
    server.listen(8)
    stop = threading.Event()

    def serve():
        server.settimeout(0.2)
        while not stop.is_set():
            try:
                client, _ = server.accept()
            except OSError:
                continue
            if behaviour == "close_immediately":
                client.close()
            else:
                stop.wait(0.05)
                client.close()
        server.close()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    return port, stop, thread


def silent_listener():
    """A real socket that accepts a connection and then never says anything again."""
    server, port = bound_socket()
    server.listen(8)
    accepted, stop = [], threading.Event()

    def serve():
        server.settimeout(0.2)
        while not stop.is_set():
            try:
                client, _ = server.accept()
            except OSError:
                continue
            accepted.append(client)
        for client in accepted:
            with contextlib.suppress(OSError):
                client.close()
        server.close()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    return port, accepted, stop, thread


def free_port():
    probe, port = bound_socket()
    probe.close()
    return port


# ---- the run context -------------------------------------------------------------------------------------------------------------------------------
class Ctx:
    def __init__(self, api, root: Path):
        self.api, self.root, self.module = api, root.resolve(), api.module
        self.cls = api.VerificationServices
        self.secrets, self.ports, self.stack, self.counter = [], [], None, 0

    def dir(self, name):
        path = self.root / name
        path.mkdir(parents=True, exist_ok=True)
        return path

    def service(self, root, artifacts, project=None):
        service = self.cls(root, artifacts, project) if project else self.cls(root, artifacts)
        self.secrets.append(service.password)
        return service

    def port(self, value):
        self.ports.append(value)
        return value

    def patch(self, target, name, value):
        original = getattr(target, name)
        setattr(target, name, value)
        self.stack.callback(setattr, target, name, original)

    def docker(self, **options):
        docker = Docker(self, **options)
        self.patch(self.module, "run_process", docker)
        return docker

    def fresh(self):
        self.module.ATTEMPTS.slots.clear()
        self.module.ATTEMPTS.started = 0

    def drain(self, *events):
        for event in events:
            event.set()
        for attempt in list(self.module.ATTEMPTS.slots.values()):
            attempt.thread.join(5)
            if attempt.reclaimer is not None:
                attempt.reclaimer.join(5)
        self.module.ATTEMPTS.slots.clear()

    def show(self, value):
        """Symbolic form: the run root, every generated password and every loopback port of this run."""
        value = relative(value, {"ROOT": str(self.root)})
        return self._swap(value)

    def _swap(self, value):
        if isinstance(value, dict):
            return {self._swap(k) if isinstance(k, str) else k: self._swap(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [self._swap(v) for v in value]
        if isinstance(value, int) and not isinstance(value, bool) and value in self.ports:
            return f"<PORT-{self.ports.index(value)}>"
        if isinstance(value, str):
            for secret in self.secrets:
                value = value.replace(secret, "<PASSWORD>")
            # `check-tree` refuses a credential-shaped URL userinfo in a committed file: the whole userinfo is masked as <USERINFO> (declared mask)
            value = re.sub(r"://[a-z]+:<PASSWORD>" r"@", r"://<USERINFO>" r"@", value)
            for index, port in enumerate(self.ports):
                value = re.sub(r"(?<![0-9])" + str(port) + r"(?![0-9])", f"<PORT-{index}>", value)
        return value


def shape(message):
    """A refusal message with its counts removed (`{"closed_unexpectedly":3}` -> `{"closed_unexpectedly":N}`)."""
    return re.sub(r'(":)[0-9]+', r"\1N", message)


def refusal(result):
    """An `outcome` error row with the counts of the refusals removed."""
    if "message" in result:
        result = {**result, "message": shape(result["message"])}
    return result


def lifted(artifacts, source=None):
    rows = [row for row in artifacts.rows if source is None or row["source"] == source]
    return sorted(rows, key=lambda row: json.dumps(row, sort_keys=True))


def stub_readiness(ctx):
    """The M7 fixture: faked compose stacks publish ports nobody listens on, so the readiness gate answers at once."""
    ctx.patch(ctx.cls, "_await_service", lambda self, service, port, deadline_seconds=30.0: {
        "tcp_after": 0.0, "ready_after": 0.0, "identity": "fixture", "refusals_during_startup": {}})


def pin_choice(ctx, ports=(31000, 31001)):
    """`published_ports.choose` is host dependent (the ephemeral window, the peer): the scenario scripts its answer."""
    def choose(count, *, rng=None):
        return {"ports": list(ports) if ports else None, "window": [20000, 32767], "window_source": "scripted",
                "sides": {"local": {"kind": "linux", "checked": True, "how": "bind"}, "peer": {"kind": "none", "checked": False}},
                "verified_on": ["local"], "daemon_is_local": True, "guarantee": "scripted", "asked": count}
    ctx.patch(ctx.api.published_ports, "choose", choose)


def scripted_observe(ctx, verdict="service", lookup_seconds=2.0):
    """A stand-in for `port_diagnosis.observe` that also exercises the container lookup the way the real one does."""
    calls = []

    def observe(port, *, service, container=None, container_lookup=None, seconds=None, failed_at=None):
        found = container_lookup(lookup_seconds) if container_lookup is not None else None
        calls.append({"port": port, "service": service, "seconds": seconds, "failed_at": type(failed_at).__name__, "container": container, "lookup": found})
        return {"port": port, "service": service, "verdict": verdict, "means": "scripted: " + verdict}

    ctx.patch(ctx.api.port_diagnosis, "observe", observe)
    return calls


def poll(check, seconds=5.0):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if check():
            return True
        time.sleep(0.05)
    return check()


def view_record(record):
    """An attempt record without its racy field."""
    return {k: v for k, v in record.items() if k not in ("reclaim_thread_finished",)}


# ---- cases ----------------------------------------------------------------------------------------------------------------------------------------
def case_constants(ctx):
    m = ctx.module
    return {"RECLAIM_SECONDS": m.RECLAIM_SECONDS, "UNRECLAIMED_LIMIT": m.UNRECLAIMED_LIMIT, "DIAGNOSIS_SECONDS": m.DIAGNOSIS_SECONDS,
            "states": [m.CLOSED, m.OPEN, m.UNKNOWN, m.RESERVED, m.RUNNING, m.WORKER_FINISHED, m.CANCELLED, m.RELEASED], "reclaimable": list(m.RECLAIMABLE),
            "environment_keys": sorted(m.ENVIRONMENT_KEYS), "registry": type(m.ATTEMPTS).__name__, "registry_empty": m.ATTEMPTS.outstanding() == []}


def case_project_names(ctx):
    artifacts, base = Artifacts(), ctx.dir("names")
    first, second = ctx.service(base, artifacts), ctx.service(base, artifacts)
    explicit = ctx.service(base, artifacts, PROJECT_A)
    link = base / "link"
    link.symlink_to(ctx.dir("names-real"))
    linked = ctx.service(link, artifacts, PROJECT_B)
    refused = {}
    for label, name in (("upper_case", "zeus-verify-" + "A" * 32), ("short", "zeus-verify-" + "a" * 31), ("long", "zeus-verify-" + "a" * 33),
                        ("other_prefix", "other-" + "a" * 32), ("empty", ""), ("traversal", "../zeus-verify-" + "a" * 32), ("newline", "zeus-verify-" + "a" * 32 + "\n"),
                        ("non_hex", "zeus-verify-" + "g" * 32)):
        refused[label] = outcome(lambda n=name: ctx.cls(base, artifacts, n))
    return {"default_shape": bool(HEX.fullmatch(first.project)), "default_directory_under_root": first.directory == first.root / first.project,
            "password_hex_48": bool(re.fullmatch(r"[0-9a-f]{48}", first.password)), "distinct_projects": first.project != second.project,
            "distinct_passwords": first.password != second.password, "explicit": explicit.project, "explicit_directory": str(explicit.directory),
            "explicit_root": str(explicit.root), "linked_root_resolved": str(linked.root), "linked_directory": str(linked.directory),
            "artifacts_kept": linked.artifacts is artifacts, "refused": refused, "nothing_created": sorted(p.name for p in base.iterdir())}


def case_command(ctx):
    docker = ctx.docker()
    service = ctx.service(ctx.dir("command"), Artifacts(), PROJECT_A)
    with_env = {}
    out = {"stdout_stripped": service._command("up", "-d")}
    for label, timeout in (("default", None), ("fraction", 0.2), ("truncated", 2.9), ("negative", -5), ("large", 600)):
        with_env[label] = service._command("ps", "-q", "postgres") if timeout is None else service._command("ps", "-q", "postgres", timeout=timeout)
    ctx.patch(ctx.module, "run_process", Docker(ctx, fail={"up": 1, "port": 3}))
    refused = {verb: outcome(lambda v=verb: service._command(v, "x")) for verb in ("up", "port", "down")}
    return {**out, "answers": with_env, "calls": ctx.show(docker.view()), "refused": refused,
            "password_in_env": all(call["env"].get("ZEUS_VERIFY_PASSWORD") == service.password for call in docker.calls)}


def lifecycle(ctx, label, *, fail=None, tests_fail=False, pin=(31000, 31001), project=PROJECT_A, ports=(45678, 45679), port_answer=None):
    artifacts, base = Artifacts(), ctx.dir("lifecycle-" + label)
    docker = ctx.docker(fail={fail: 1} if fail else {}, ports=ports, answers={"port": port_answer} if port_answer else None)
    pin_choice(ctx, pin)
    stub_readiness(ctx)
    service = ctx.service(base, artifacts, project)
    seen = {}

    def execute():
        with service as endpoints:
            seen["endpoints"] = endpoints
            seen["inside"] = sorted(p.name for p in service.directory.iterdir())
            if tests_fail:
                raise RuntimeError("fixture tests failed")
        return "left"

    result = outcome(execute)
    snapshot = docker.snapshots[0] if docker.snapshots else {}
    spec = json.loads(snapshot["compose.json"]) if "compose.json" in snapshot else None
    manifest = json.loads(snapshot["manifest.json"]) if "manifest.json" in snapshot else None
    return {"result": result, "endpoints": seen.get("endpoints"), "inside": seen.get("inside"), "verbs": docker.verbs(), "last_args": docker.calls[-1]["args"],
            "compose": spec, "manifest": manifest, "password_not_in_compose": service.password not in snapshot.get("compose.json", ""),
            "directory_removed": not service.directory.exists(), "artifacts": lifted(artifacts), "docker_cwd": ctx.show(docker.calls[0]["cwd"]) if docker.calls else None,
            "timeouts": [call["timeout"] for call in docker.calls]}


def case_lifecycle(ctx):
    out = {label: lifecycle(ctx, label, fail=failure, tests_fail=label == "tests") for label, failure in
           (("ok", None), ("up", "up"), ("port", "port"), ("tests", None), ("down", "down"))}
    out["daemon_ports"] = lifecycle(ctx, "daemon", pin=None)
    return out


def case_endpoint_refusals(ctx):
    out = {}
    for label, answer in (("wildcard", "0.0.0.0:45678\n"), ("zero", "127.0.0.1:0\n"), ("too_large", "127.0.0.1:65536\n"), ("empty", ""), ("text", "no port\n"),
                          ("ipv6", "[::1]:45678\n"), ("trailing", "127.0.0.1:45678 extra\n"), ("max", "127.0.0.1:65535\n")):
        out[label] = lifecycle(ctx, "ep-" + label, port_answer=answer)
    return out


def case_directory_exists(ctx):
    artifacts, base = Artifacts(), ctx.dir("exists")
    docker = ctx.docker()
    pin_choice(ctx)
    stub_readiness(ctx)
    service = ctx.service(base, artifacts, PROJECT_A)
    service.directory.mkdir()
    (service.directory / "keep.txt").write_text("kept", encoding="utf-8")
    result = outcome(service.__enter__)
    return {"result": result, "verbs": docker.verbs(), "kept": (service.directory / "keep.txt").read_text("utf-8"), "artifacts": lifted(artifacts)}


def case_cleanup_guards(ctx):
    out = {}
    pin_choice(ctx)
    stub_readiness(ctx)
    for label in ("elsewhere", "symlink", "missing_file", "extra_file", "ok"):
        artifacts, base = Artifacts(), ctx.dir("guard-" + label)
        docker = ctx.docker()
        service = ctx.service(base, artifacts, PROJECT_A)
        service.__enter__()
        real = service.directory
        if label == "elsewhere":
            other = ctx.dir("guard-elsewhere-target") / "x"
            other.mkdir()
            for name in ("compose.json", "manifest.json"):
                (other / name).write_text("{}", encoding="utf-8")
            service.directory = other
        elif label == "symlink":
            target = ctx.dir("guard-symlink-target") / "y"
            target.mkdir()
            for name in ("compose.json", "manifest.json"):
                (target / name).write_text("{}", encoding="utf-8")
            moved = base / "moved"
            real.rename(moved)
            real.symlink_to(target)
        elif label == "missing_file":
            (real / "compose.json").unlink()
        elif label == "extra_file":
            (real / "extra.txt").write_text("x", encoding="utf-8")
        failure = service._cleanup_observed()
        out[label] = {"failure": failure, "verbs": docker.verbs(), "artifacts": lifted(artifacts),
                      "listing": sorted(str(p.relative_to(ctx.root)) for p in ctx.root.glob("guard-" + label + "*/**/*"))}
    return out


def make_stack(ctx, base, artifacts, project, created):
    service = ctx.service(base, artifacts, project)
    service.__enter__()
    manifest = service.directory / "manifest.json"
    data = json.loads(manifest.read_text("utf-8"))
    data["created_at"] = created
    manifest.write_text(json.dumps(data), encoding="utf-8")
    return service


def case_collect_stale(ctx):
    base, artifacts = ctx.dir("stale"), Artifacts()
    stub_readiness(ctx)
    pin_choice(ctx)
    ctx.docker()
    names = {label: "zeus-verify-" + str(i) * 32 for i, label in enumerate(
        ("stale", "fresh", "changed", "mismatch", "symlinked_definition", "down_fails", "naive", "missing_key", "not_hex_name"), start=1)}
    stacks = {}
    for label in ("stale", "fresh", "changed", "mismatch", "symlinked_definition", "down_fails", "naive", "missing_key"):
        created = {"fresh": "2100-01-01T00:00:00+00:00", "naive": "2000-01-01T00:00:00"}.get(label, "2000-01-01T00:00:00+00:00")
        stacks[label] = make_stack(ctx, base, artifacts, names[label], created)
    changed_original = (stacks["changed"].directory / "compose.json").read_text("utf-8")
    (stacks["changed"].directory / "compose.json").write_text("{}", encoding="utf-8")
    data = json.loads((stacks["mismatch"].directory / "manifest.json").read_text("utf-8"))
    data["project"] = "zeus-verify-" + "9" * 32
    (stacks["mismatch"].directory / "manifest.json").write_text(json.dumps(data), encoding="utf-8")
    definition = stacks["symlinked_definition"].directory / "compose.json"
    kept = definition.read_text("utf-8")
    (base / "definition-target.json").write_text(kept, encoding="utf-8")
    definition.unlink()
    definition.symlink_to(base / "definition-target.json")
    data = json.loads((stacks["missing_key"].directory / "manifest.json").read_text("utf-8"))
    del data["created_at"]
    (stacks["missing_key"].directory / "manifest.json").write_text(json.dumps(data), encoding="utf-8")
    invalid = base / ("zeus-verify-" + "0" * 32)
    invalid.mkdir()
    (invalid / "manifest.json").write_text("broken", encoding="utf-8")
    odd = base / "zeus-verify-not-a-hex-name"
    odd.mkdir()
    (odd / "manifest.json").write_text(json.dumps({"project": odd.name, "created_at": "2000-01-01T00:00:00+00:00", "definition_hash": "x"}), encoding="utf-8")
    real_dir = ctx.dir("stale-symlink-target")
    (real_dir / "manifest.json").write_text("{}", encoding="utf-8")
    (base / ("zeus-verify-" + "d" * 32)).symlink_to(real_dir)
    other = base / ("zeus-verify-" + "e" * 32)
    other.mkdir()
    (base / "manifest-target.json").write_text("{}", encoding="utf-8")
    (other / "manifest.json").symlink_to(base / "manifest-target.json")

    docker = ctx.docker(fail_projects={names["down_fails"]: ("down",)})
    artifacts = Artifacts()
    first = ctx.cls.collect_stale(base, artifacts)
    out = {"first": {"removed": sorted(first["removed"]), "failures": sorted(first.get("failures", []), key=lambda f: f["project"]), "keys": sorted(first)},
           "after_first": sorted(p.name for p in base.iterdir() if p.name.startswith("zeus-verify-")),
           "down_projects": sorted(c["prefix"][3] for c in docker.calls if c["args"][0] == "down"),
           "down_args": sorted({tuple(c["args"]) for c in docker.calls if c["args"][0] == "down"}),
           "artifacts": lifted(artifacts)}
    definition.unlink()
    definition.write_text(kept, encoding="utf-8")
    (stacks["changed"].directory / "compose.json").write_text(changed_original, encoding="utf-8")
    second = ctx.cls.collect_stale(base, Artifacts(), max_age=0)
    out["second_max_age_zero"] = {"removed": sorted(second["removed"]), "failures": sorted(second.get("failures", []), key=lambda f: f["project"])}
    out["after_second"] = sorted(p.name for p in base.iterdir() if p.name.startswith("zeus-verify-"))
    out["absent_root"] = ctx.cls.collect_stale(base / "does-not-exist", Artifacts())
    out["empty_root"] = ctx.cls.collect_stale(ctx.dir("stale-empty"), Artifacts())
    return out


def case_stale_cycle(ctx):
    """M7 `test_stale_cleanup_requires_unchanged_definition_and_leaves_fresh_stack` and `test_cleanup_failure_preserves_primary_error_and_is_retryable`."""
    out = {}
    artifacts, base = Artifacts(), ctx.dir("cycle")
    pin_choice(ctx)
    stub_readiness(ctx)
    docker = ctx.docker()
    service = ctx.service(base, artifacts, PROJECT_A)
    service.__enter__()
    manifest = service.directory / "manifest.json"
    original_manifest = json.loads(manifest.read_text("utf-8"))
    out["entered_manifest"] = original_manifest
    # the stack was made at the harness clock; the age rule is about a manifest dated long before or long after now
    data = {**original_manifest, "created_at": "2100-01-01T00:00:00+00:00"}
    manifest.write_text(json.dumps(data), encoding="utf-8")
    out["fresh_left"] = ctx.cls.collect_stale(service.root, artifacts)
    data["created_at"] = "2000-01-01T00:00:00+00:00"
    manifest.write_text(json.dumps(data), encoding="utf-8")
    definition = service.directory / "compose.json"
    original = definition.read_text("utf-8")
    definition.write_text("{}", encoding="utf-8")
    blocked = ctx.cls.collect_stale(service.root, artifacts)
    out["changed_definition"] = {"result": blocked, "directory_kept": service.directory.exists()}
    definition.write_text(original, encoding="utf-8")
    out["restored"] = {"result": ctx.cls.collect_stale(service.root, artifacts), "directory_removed": not service.directory.exists()}
    out["verbs"] = docker.verbs()
    # a startup that fails while its own cleanup also fails keeps the primary error and the manifest for a retry
    failing = ctx.docker(fail={"up": 1, "down": 1})
    retry = ctx.service(base, artifacts, PROJECT_B)
    out["primary"] = outcome(retry.__enter__)
    out["retry_manifest_kept"] = (retry.directory / "manifest.json").exists()
    out["failing_verbs"] = failing.verbs()
    ctx.docker()
    collected = ctx.cls.collect_stale(base, artifacts, max_age=0)
    out["retried"] = {"result": collected, "directory_removed": not retry.directory.exists()}
    out["artifacts"] = lifted(artifacts)
    return out


def case_invalid_manifest(ctx):
    artifacts, base = Artifacts(), ctx.dir("invalid")
    pin_choice(ctx)
    stub_readiness(ctx)
    ctx.docker()
    service = ctx.service(base, artifacts, PROJECT_A)
    service.__enter__()
    invalid = base / ("zeus-verify-" + "0" * 32)
    invalid.mkdir()
    (invalid / "manifest.json").write_text("broken", encoding="utf-8")
    result = ctx.cls.collect_stale(base, artifacts, max_age=0)
    return {"removed": result["removed"], "failures": result["failures"], "invalid_kept": invalid.exists(), "valid_removed": not service.directory.exists(),
            "artifacts": lifted(artifacts)}


# ---- readiness --------------------------------------------------------------------------------------------------------------------------------------
def readiness(ctx, label, service_name, port, *, deadline, patches=(), observe="service"):
    """One `_await_service` call over a real port; the result with its counts removed and what the stand-in observe saw."""
    artifacts = Artifacts()
    service = ctx.service(ctx.dir("ready-" + label), artifacts, PROJECT_A)
    calls = scripted_observe(ctx, observe)
    for name, value in patches:
        ctx.patch(ctx.cls, name, value)
    started = time.monotonic()
    result = refusal(outcome(lambda: service._await_service(service_name, port, deadline_seconds=deadline)))
    return service, artifacts, calls, result, time.monotonic() - started


def case_readiness_cannot_answer(ctx):
    """The CI symptom: the socket opens and the service never serves (real `_answer` over loopback: psycopg, then redis)."""
    out = {}
    for service_name in ("postgres", "redis"):
        port, stop, thread = listener()
        ctx.port(port)
        try:
            service, artifacts, calls, result, elapsed = readiness(ctx, "cannot-" + service_name, service_name, port, deadline=1.5)
        finally:
            stop.set()
            thread.join(3)
        row = {"result": result, "diagnosis_calls": calls, "artifacts": lifted(artifacts), "password_in_message": service.password in json.dumps(result),
               "bounded": elapsed < 10}
        if service_name == "redis":
            # redis reports the same dropped connection as a reset or as an end of stream, depending on the race: only the family of kinds is a fact
            found = re.search(r"refusals: (\{[^}]*\})", result.get("message", ""))
            kinds = sorted(json.loads(found.group(1))) if found else []
            row["result"] = {**result, "message": re.sub(r"refusals: \{[^}]*\}", "refusals: {kinds}", result.get("message", ""))}
            row["kinds_are_connection_drops"] = bool(kinds) and set(kinds) <= {"closed_unexpectedly", "other"}
        out[service_name] = row
    return out


def case_refusal_kinds(ctx):
    service = ctx.service(ctx.dir("kinds"), Artifacts(), PROJECT_A)
    kinds = {text: service._refusal_kind(error) for text, error in (
        ("starting_up", Exception("FATAL: the database system is starting up")), ("closed", Exception("server closed the connection unexpectedly")),
        ("reset", Exception("Connection reset by peer")), ("refused", ConnectionRefusedError("Connection refused")), ("timeout", TimeoutError("timed out")),
        ("timeout_word", Exception("socket timeout")), ("other", Exception("something else")), ("empty", Exception("")),
        ("order_starting_first", Exception("starting up: connection refused")), ("order_closed_before_refused", Exception("closed the connection, refused")),
        ("upper", Exception("CONNECTION REFUSED")))}
    return {"kinds": kinds, "static": ctx.cls._refusal_kind(Exception("refused"))}


def case_readiness_never_accepts(ctx):
    out = {}
    docker = ctx.docker(answers={"ps": lambda args: "container-" + args[-1] + "\n"})
    for service_name in ("redis", "postgres"):
        port = ctx.port(free_port())
        service, artifacts, calls, result, elapsed = readiness(ctx, "never-" + service_name, service_name, port, deadline=0.5, observe="publication")
        out[service_name] = {"result": result, "diagnosis_calls": calls, "artifacts": lifted(artifacts), "bounded": elapsed < 10}
    out["lookup_calls"] = [c["args"] + [c["timeout"]] for c in docker.calls]
    return out


def case_readiness_diagnosis_lookup(ctx):
    """`_diagnose`: the container lookup runs through `_command ps -q`, inside the capture's own bound, and every failure of it is a missing container."""
    out = {}
    for label, options in (("found", {}), ("empty_answer", {"answers": {"ps": "\n"}}), ("docker_fails", {"fail": {"ps": 1}})):
        docker = ctx.docker(**options)
        service = ctx.service(ctx.dir("diag-" + label), Artifacts(), PROJECT_A)
        calls = scripted_observe(ctx, "service")
        record = service._diagnose("postgres", ctx.port(54321), failed_at=12.5)
        out[label] = {"record": ctx.show(record), "calls": ctx.show(calls), "docker": ctx.show(docker.view())}
    zero = scripted_observe(ctx, "service", lookup_seconds=0)
    service = ctx.service(ctx.dir("diag-zero"), Artifacts(), PROJECT_A)
    out["zero_seconds"] = {"record": service._diagnose("redis", 1, failed_at=None), "calls": zero}
    return out


def case_readiness_waits_for_answer(ctx):
    port, stop, thread = listener()
    answers_at = time.monotonic() + 0.5

    def answer(self, service, port_, seconds=30, register=None):
        if time.monotonic() < answers_at:
            raise RuntimeError("FATAL: the database system is starting up")
        return "our-service"

    try:
        service, artifacts, calls, result, elapsed = readiness(
            ctx, "waits", "postgres", port, deadline=10, patches=(("_answer", answer), ("_container_identity", lambda self, service, seconds=30: "our-service")))
    finally:
        stop.set()
        thread.join(3)
    report = result.get("ok", {})
    return {"keys": sorted(report), "identity": report.get("identity"), "waited_for_the_answer": report.get("ready_after", 0) >= 0.4,
            "socket_first": report.get("tcp_after", 1) < report.get("ready_after", 0), "starting_up_seen": bool(report.get("refusals_during_startup", {}).get("starting_up")),
            "refusal_kinds": sorted(report.get("refusals_during_startup", {})), "unreclaimed": report.get("unreclaimed_attempts"), "result_kind": sorted(result)[:1],
            "diagnosis_calls": calls, "artifacts": lifted(artifacts)}


def case_readiness_not_this_project(ctx):
    port, stop, thread = listener()
    ctx.port(port)
    try:
        service, artifacts, calls, result, elapsed = readiness(
            ctx, "other", "postgres", port, deadline=5,
            patches=(("_answer", lambda self, service, port_, seconds=30, register=None: "somebody-elses"), ("_container_identity", lambda self, service, seconds=30: "ours")))
        empty = readiness(ctx, "empty-identity", "redis", port, deadline=5, patches=(
            ("_answer", lambda self, service, port_, seconds=30, register=None: ""), ("_container_identity", lambda self, service, seconds=30: "")))[3]
    finally:
        stop.set()
        thread.join(3)
    return {"mismatch": result, "empty_identity": empty, "diagnosis_calls": calls, "artifacts": lifted(artifacts)}


def case_readiness_receipt(ctx):
    port, stop, thread = listener()
    try:
        service, artifacts, calls, result, elapsed = readiness(
            ctx, "receipt", "redis", port, deadline=5, patches=(
                ("_answer", lambda self, service, port_, seconds=30, register=None: "identity-" + service),
                ("_container_identity", lambda self, service, seconds=30: "identity-" + service)))
    finally:
        stop.set()
        thread.join(3)
    report = result.get("ok", {})
    return {"keys": sorted(report), "identity": report.get("identity"), "readiness_deadline_seconds": report.get("readiness_deadline_seconds"),
            "reclaim_deadline_seconds": report.get("reclaim_deadline_seconds"), "unreclaimed_attempts": report.get("unreclaimed_attempts"), "note": report.get("note"),
            "refusals": report.get("refusals_during_startup"), "numbers": [isinstance(report.get(k), float) for k in ("tcp_after", "ready_after")],
            "result_kind": sorted(result)[:1]}


def case_readiness_late_answer(ctx):
    """An answer that arrives after the deadline is a failure: abandoned at its bound, and returned unbounded."""
    out = {}
    for label, bound in (("abandoned", None), ("unbounded", lambda self, work, seconds: work(lambda resource: None))):
        port, stop, thread = listener()
        ctx.port(port)

        def slow(self, service, port_, seconds=30, register=None):
            time.sleep(0.4)
            return "our-service"

        patches = [("_answer", slow), ("_container_identity", lambda self, service, seconds=30: "our-service")]
        if bound is not None:
            patches.append(("_bounded", bound))
        try:
            service, artifacts, calls, result, elapsed = readiness(ctx, "late-" + label, "postgres", port, deadline=0.1, patches=patches)
        finally:
            stop.set()
            thread.join(3)
        ctx.drain()
        out[label] = {"result": result, "diagnosis_calls": calls, "artifacts": [r["source"] + ":" + str(r["body"].get("status")) for r in lifted(artifacts)]}
    return out


def case_readiness_silent_service(ctx):
    port, stop, thread = listener()
    ctx.port(port)
    released = threading.Event()

    def never_answers(self, service, port_, seconds=30, register=None):
        released.wait(30)
        return "our-service"

    try:
        service, artifacts, calls, result, elapsed = readiness(ctx, "silent", "postgres", port, deadline=0.5, patches=(("_answer", never_answers),))
        owed = [view_record(r) for r in ctx.module.ATTEMPTS.outstanding()]
    finally:
        ctx.drain(released)
        stop.set()
        thread.join(3)
    return {"result": result, "bounded": elapsed < 10, "diagnosis_calls": calls, "owed_while_blocked": len(owed), "owed_states": sorted({r["state"] for r in owed}),
            "unreclaimed": [{k: v for k, v in r["body"].items() if k in ("status", "project", "state", "worker_finished", "resources_still_held", "reclaimed")}
                            for r in lifted(artifacts, "verification-unreclaimed")]}


def case_readiness_identity_unreadable(ctx):
    port, stop, thread = listener()
    ctx.port(port)
    released = threading.Event()

    def slow_lookup(self, service, seconds=30):
        released.wait(1.5)
        return "our-service"

    try:
        service, artifacts, calls, result, elapsed = readiness(ctx, "identity", "postgres", port, deadline=1.0, patches=(
            ("_answer", lambda self, service, port_, seconds=30, register=None: "our-service"), ("_container_identity", slow_lookup)))
    finally:
        ctx.drain(released)
        stop.set()
        thread.join(3)
    return {"result": result, "within_both_bounds": elapsed < 1.0 + ctx.module.RECLAIM_SECONDS + 2, "diagnosis_calls": calls}


def case_readiness_exception_chain(ctx):
    port, stop, thread = listener()
    ctx.port(port)
    sentinel = "SENTINEL-ORIGINAL-ERROR-TEXT-b4f1"

    def refuse(self, service, port_, seconds=30, register=None):
        raise RuntimeError("connection failed: " + sentinel)

    services = ctx.service(ctx.dir("chain"), Artifacts(), PROJECT_A)
    scripted_observe(ctx, "service")
    ctx.patch(ctx.cls, "_answer", refuse)
    try:
        with contextlib_raises() as raised:
            services._await_service("postgres", port, deadline_seconds=0.3)
    finally:
        stop.set()
        thread.join(3)
    error = raised[0]
    rendered = "".join(traceback.format_exception(type(error), error, error.__traceback__))
    return {"type": type(error).__name__, "sentinel_in_traceback": sentinel in rendered, "password_in_traceback": services.password in rendered,
            "refusals_named": "refusals" in str(error), "cause": repr(error.__cause__), "suppressed_context": error.__suppress_context__, "message": shape(ctx.show(str(error)))}


@contextlib.contextmanager
def contextlib_raises():
    box = []
    try:
        yield box
    except BaseException as exc:  # noqa: BLE001
        box.append(exc)
    else:
        raise AssertionError("did not raise")


def case_container_identity(ctx):
    docker = ctx.docker()
    service = ctx.service(ctx.dir("identity-lookup"), Artifacts(), PROJECT_A)
    out = {"postgres": service._container_identity("postgres", 7), "redis": service._container_identity("redis", 7.9)}
    ctx.patch(ctx.module, "run_process", Docker(ctx, answers={("exec", "-T"): "# Server\nredis_version:7\n"}))
    out["redis_without_run_id"] = service._container_identity("redis", 3)
    ctx.patch(ctx.module, "run_process", Docker(ctx, answers={("exec", "-T"): "run_id:  spaced  \nrun_id:second\n"}))
    out["redis_first_run_id"] = service._container_identity("redis", 3)
    ctx.patch(ctx.module, "run_process", Docker(ctx, fail={"exec": 1}))
    out["docker_fails"] = outcome(lambda: service._container_identity("postgres", 3))
    out["calls"] = ctx.show(docker.view())
    return out


def case_answer_over_loopback(ctx):
    """`_answer` against real loopback ports: nothing there (refused), a socket that closes at once, and the resources it registers."""
    out = {}
    service = ctx.service(ctx.dir("answer"), Artifacts(), PROJECT_A)
    for label in ("closed_port", "accepts_and_closes"):
        for name in ("postgres", "redis"):
            if label == "closed_port":
                port, stop, thread = ctx.port(free_port()), None, None
            else:
                port, stop, thread = listener()
                ctx.port(port)
            registered = []
            result = outcome(lambda n=name, p=port: service._answer(n, p, 1.0, registered.append))
            kind = service._refusal_kind(Exception(result.get("message", "")))
            out[f"{label}_{name}"] = {"error": result.get("error"), "registered": [type(r).__name__ for r in registered],
                                      "closed_after": [getattr(r, "closed", None) for r in registered],
                                      # a peer that drops the connection is a reset or an end of stream depending on the race: only the family is a fact
                                      **({"kind": kind} if label == "closed_port" else {"kind_is_a_connection_drop": kind in ("closed_unexpectedly", "other")})}
            if stop is not None:
                stop.set()
                thread.join(3)
    out["default_register"] = {n: outcome(lambda n=n: service._answer(n, free_port(), 0.2)).get("error") for n in ("postgres", "redis")}
    return out


# ---- the attempt machinery --------------------------------------------------------------------------------------------------------------------------
def case_timed_out_attempt(ctx):
    ctx.fresh()
    service = ctx.service(ctx.dir("timeout"), Artifacts(), PROJECT_A)
    port, accepted, stop, thread = silent_listener()
    sockets, before = [], threading.active_count()
    results = []
    try:
        def blocking_work(register):
            client = socket.create_connection(("127.0.0.1", port), timeout=5)
            sockets.append(client)
            register(client)
            client.recv(1)
            return "unreachable"

        for _ in range(3):
            results.append(outcome(lambda: service._bounded(blocking_work, 0.1)))
        drained = poll(lambda: ctx.module.ATTEMPTS.outstanding() == [])
        gone = poll(lambda: threading.active_count() <= before)
        return {"results": results, "sockets": len(sockets), "all_closed": all(c.fileno() == -1 for c in sockets), "taken_back": drained, "no_leftover_threads": gone,
                "slots_after": sorted(ctx.module.ATTEMPTS.slots), "started": ctx.module.ATTEMPTS.started}
    finally:
        stop.set()
        thread.join(3)


def case_unreclaimed_limit(ctx):
    ctx.fresh()
    released = threading.Event()
    limit = ctx.module.UNRECLAIMED_LIMIT
    artifacts = Artifacts()

    def unreclaimable(register):
        released.wait(30)
        return "late"

    out = {"timeouts": [], "owed": []}
    try:
        for index in range(limit):
            service = ctx.service(ctx.dir(f"limit-{index}"), artifacts, "zeus-verify-" + str(index) * 32)
            out["timeouts"].append(outcome(lambda: service._bounded(unreclaimable, 0.05)))
            out["owed"].append(len(ctx.module.ATTEMPTS.outstanding()))
        records = [view_record(r) for r in ctx.module.ATTEMPTS.outstanding()]
        out["records"] = records
        out["recovery_text"] = records[0]["recovery"]
        fresh = ctx.service(ctx.dir("limit-next"), artifacts, PROJECT_C)
        out["refused"] = outcome(lambda: fresh._bounded(unreclaimable, 0.05))
        out["owed_after_refusal"] = len(ctx.module.ATTEMPTS.outstanding())
        out["started_after"] = ctx.module.ATTEMPTS.started
        out["direct_refusal"] = outcome(lambda: ctx.module.ATTEMPTS.start(unreclaimable, "direct"))
        out["unreclaimed_artifacts"] = [{k: v for k, v in r["body"].items() if k in ("status", "project", "attempt", "state", "worker_finished", "resources_still_held", "reclaimed",
                                                                                      "owed_in_process", "thread", "reclaim_thread")} for r in lifted(artifacts, "verification-unreclaimed")]
    finally:
        ctx.drain(released)
    return out


def case_close_that_hangs(ctx):
    ctx.fresh()
    service = ctx.service(ctx.dir("hang"), Artifacts(), PROJECT_A)
    released, done = threading.Event(), threading.Event()
    hanging = Hanging(released)

    def work(register):
        register(hanging)
        done.wait(30)
        return "late"

    started = time.monotonic()
    try:
        raised = outcome(lambda: service._bounded(work, 0.02))
        elapsed = time.monotonic() - started
        held = ctx.module.ATTEMPTS.outstanding()
        return {"raised": raised, "caller_came_back": elapsed < ctx.module.RECLAIM_SECONDS + 3, "close_really_stuck": not hanging.closed,
                "owed": len(held), "reclaim_still_running": held[0]["reclaim_thread_finished"] is False, "recovery": bool(held[0]["recovery"]),
                "resources": [{k: v for k, v in r.items()} for r in held[0]["resources"]], "state": held[0]["state"]}
    finally:
        ctx.drain(released, done)


def case_registered_after_reclamation(ctx):
    ctx.fresh()
    service = ctx.service(ctx.dir("late-register"), Artifacts(), PROJECT_A)
    swept, late, first = threading.Event(), Recorded(), Recorded()

    def work(register):
        register(first)
        swept.wait(10)
        register(late)
        return "done"

    original = Recorded.close

    def close_and_release(self):
        original(self)
        if self is first:
            swept.set()

    Recorded.close = close_and_release
    try:
        raised = outcome(lambda: service._bounded(work, 0.05))
    finally:
        Recorded.close = original
        ctx.drain(swept)
    return {"raised": raised, "first_closed": first.closed, "late_closed": late.closed, "owed_after": ctx.module.ATTEMPTS.outstanding()}


def case_slot_limits(ctx):
    ctx.fresh()
    limit = ctx.module.UNRECLAIMED_LIMIT
    released = threading.Event()

    def never_ends(register):
        released.wait(30)
        return "late"

    started, out = [], {}
    try:
        for _ in range(limit):
            started.append(ctx.module.ATTEMPTS.start(never_ends, "reserve"))
        out["all_running"] = all(a.thread.is_alive() for a in started)
        out["states"] = sorted({a.state for a in started})
        out["refused"] = outcome(lambda: ctx.module.ATTEMPTS.start(never_ends, "reserve"))
        out["slots"] = sorted(ctx.module.ATTEMPTS.slots)
        out["started_counter"] = ctx.module.ATTEMPTS.started
    finally:
        ctx.drain(released)
        for attempt in started:
            attempt.thread.join(5)
    return out


def case_stubborn_resource(ctx):
    ctx.fresh()
    service = ctx.service(ctx.dir("stubborn"), Artifacts(), PROJECT_A)
    left, right = socket.socketpair()
    stubborn, hold = Stubborn(left), threading.Event()

    def work(register):
        register(stubborn)
        hold.wait(30)
        return "done"

    try:
        raised = outcome(lambda: service._bounded(work, 0.05))
        hold.set()
        poll(lambda: stubborn.attempts > 0)
        held = ctx.module.ATTEMPTS.outstanding()
        record = held[0] if held else {}
        return {"raised": raised, "owed": len(held), "reclaimed": record.get("reclaimed"), "resources_still_held": record.get("resources_still_held"),
                "resource": [{k: v for k, v in r.items() if k != "close_attempts"} for r in record.get("resources", [])],
                "close_tried": [r["close_attempts"] >= 1 for r in record.get("resources", [])], "socket_open": left.fileno() != -1}
    finally:
        hold.set()
        ctx.drain(hold)
        left.close()
        right.close()


def case_registered_after_window(ctx):
    ctx.fresh()
    service = ctx.service(ctx.dir("after-window"), Artifacts(), PROJECT_A)
    window_over, keep_running, late = threading.Event(), threading.Event(), Recorded()

    def work(register):
        window_over.wait(30)
        register(late)
        keep_running.wait(30)
        return "late"

    try:
        raised = outcome(lambda: service._bounded(work, 0.05))
        owned = len(ctx.module.ATTEMPTS.outstanding())
        window_over.set()
        closed = poll(lambda: (ctx.module.ATTEMPTS.sweep(), late.closed)[1], 10)
        return {"raised": raised, "owned_after_window": owned, "late_closed": closed}
    finally:
        ctx.drain(window_over, keep_running)


def case_slot_released(ctx):
    ctx.fresh()
    service = ctx.service(ctx.dir("released"), Artifacts(), PROJECT_A)
    out = {}
    for label, action in (("closed_by_worker", lambda left: left.close()), ("left_open", lambda left: None)):
        left, right = socket.socketpair()

        def work(register, left=left, action=action):
            register(left)
            action(left)
            return "answered"

        result = outcome(lambda: service._bounded(work, 5))
        # a worker that left its socket open is taken back by a reclaimer: wait for the debt to clear instead of reading it mid-flight
        out[label] = {"result": result, "debt_cleared": poll(lambda: ctx.module.ATTEMPTS.outstanding() == []), "socket_closed": left.fileno() == -1}
        ctx.module.ATTEMPTS.slots.clear()
        left.close()
        right.close()
    out["worker_error"] = outcome(lambda: service._bounded(lambda register: (_ for _ in ()).throw(ValueError("worker failed")), 5))
    out["after_error"] = ctx.module.ATTEMPTS.outstanding()
    out["slots_after"] = sorted(ctx.module.ATTEMPTS.slots)
    return out


def case_other_attempt_untouched(ctx):
    ctx.fresh()
    service = ctx.service(ctx.dir("untouched"), Artifacts(), PROJECT_A)
    holding, finish, started = Recorded(), threading.Event(), []

    def slow(register):
        register(holding)
        finish.wait(30)
        return "done"

    try:
        started.append(ctx.module.ATTEMPTS.start(slow, "A"))
        poll(lambda: bool(started[0].held))
        second = outcome(lambda: service._bounded(lambda register: "done", 5))
        return {"second": second, "a_resource_closed": holding.closed, "a_state": started[0].state, "slots": sorted(ctx.module.ATTEMPTS.slots)}
    finally:
        finish.set()
        started[0].thread.join(5)
        ctx.module.ATTEMPTS.sweep()
        ctx.drain()


def case_reservation(ctx):
    ctx.fresh()
    service = ctx.service(ctx.dir("reservation"), Artifacts(), PROJECT_A)
    reserved = ctx.module._Attempt("a-test", "reserve", lambda register: "done")
    try:
        out = {"state": reserved.state, "settled": reserved.settled(), "reclaimable": reserved.reclaimable()}
        ctx.module.ATTEMPTS.slots[reserved.id] = reserved
        ctx.module.ATTEMPTS.sweep()
        out["kept_by_sweep"] = reserved.id in ctx.module.ATTEMPTS.slots
        out["beside"] = outcome(lambda: service._bounded(lambda register: "beside", 5))
        out["still_there"] = reserved.id in ctx.module.ATTEMPTS.slots
        out["outstanding"] = [view_record(r) for r in ctx.module.ATTEMPTS.outstanding()]
        return out
    finally:
        ctx.module.ATTEMPTS.slots.pop(reserved.id, None)


def case_unreadable_resource(ctx):
    ctx.fresh()
    service = ctx.service(ctx.dir("unreadable"), Artifacts(), PROJECT_A)
    left, right = socket.socketpair()
    unreadable, hold = Unreadable(left), threading.Event()

    def work(register):
        register(unreadable)
        hold.wait(30)
        return "done"

    try:
        raised = outcome(lambda: service._bounded(work, 0.05))
        hold.set()
        poll(lambda: unreadable.asked > 0)
        held = ctx.module.ATTEMPTS.outstanding()
        record = held[0] if held else {}
        return {"raised": raised, "owed": len(held), "state": [r["state"] for r in record.get("resources", [])], "reclaimed": record.get("reclaimed"),
                "socket_open": left.fileno() != -1}
    finally:
        ctx.drain(hold)
        left.close()
        right.close()


def case_state_of(ctx):
    m = ctx.module
    left, right = socket.socketpair()
    out = {"open_socket": m._state_of(left)}
    left.close()
    out["closed_socket"] = m._state_of(left)
    right.close()

    class Broken(socket.socket):
        def fileno(self):
            raise OSError("no answer")

    broken = Broken()
    out["fileno_fails"] = m._state_of(broken)
    socket.socket.close(broken)
    for label, value in (("bool_true", True), ("bool_false", False), ("int_one", 1), ("int_zero", 0), ("none", None), ("string", "yes"), ("float", 1.0)):
        out[label] = m._state_of(SimpleNamespace(closed=value))
    out["no_attribute"] = m._state_of(object())
    return out


class Scripted:
    """A resource with only the named actions; records the order they are called in."""

    def __init__(self, actions, fail=(), closes_on=None, flag=False):
        self.calls, self.closed, self._fail, self._closes_on = [], flag, set(fail), closes_on
        for name in actions:
            setattr(self, name, lambda name=name: self._act(name))

    def _act(self, name):
        self.calls.append(name)
        if name in self._fail:
            raise RuntimeError(name + " failed")
        if name == self._closes_on:
            self.closed = True


def case_held(ctx):
    m = ctx.module
    out = {}
    for label, resource in (
            ("cancel_then_close", Scripted(("cancel", "close"), closes_on="close")), ("cancel_fails", Scripted(("cancel", "close"), fail=("cancel",), closes_on="close")),
            ("terminate_only", Scripted(("terminate",), closes_on="terminate")), ("kill_only", Scripted(("kill",), closes_on="kill")),
            ("cancel_only", Scripted(("cancel",), closes_on="cancel")), ("close_fails", Scripted(("close", "terminate", "kill"), fail=("close",), closes_on="kill")),
            ("close_without_flag", Scripted(("close",))), ("nothing", Scripted(())), ("already_closed", Scripted(("close",), flag=True)),
            ("all_fail", Scripted(("cancel", "close", "terminate", "kill"), fail=("cancel", "close", "terminate", "kill")))):
        held = m._Held(resource)
        initial = held.state
        first = held.shut()
        second = held.shut()
        out[label] = {"initial": initial, "first": first, "second": second, "calls": resource.calls, "report": held.report(), "closed": held.closed}
    flipping = Recorded()
    held = m._Held(flipping)
    before = held.confirm()
    flipping.closed = True
    out["confirm"] = {"before": before, "after": held.confirm(), "state": held.state}
    redis = SimpleNamespace(calls=0)
    redis.close = lambda: setattr(redis, "calls", redis.calls + 1)
    handle = m._RedisHandle(redis)
    out["redis_handle"] = {"state_before": m._state_of(handle), "closed_before": handle.closed}
    handle.close()
    out["redis_handle"].update(state_after=m._state_of(handle), closed_after=handle.closed, client_closes=redis.calls)
    return out


def case_attempt_units(ctx):
    m = ctx.module
    ctx.fresh()
    out = {}
    done = m._Attempt("a-u1", "unit", lambda register: "value")
    out["new"] = {"state": done.state, "thread_name": done.thread.name, "daemon": done.thread.daemon, "reclaimable": done.reclaimable(), "settled": done.settled()}
    done.running()
    out["running"] = done.state
    done.thread.start()
    out["waited"] = done.wait(5)
    out["finished"] = {"state": done.state, "result": done.result(), "settled": done.settled(), "record": view_record(done.record())}
    bad = m._Attempt("a-u2", "unit", lambda register: (_ for _ in ()).throw(ValueError("unit failure")))
    bad.thread.start()
    bad.wait(5)
    out["worker_error"] = {"state": bad.state, "result": outcome(bad.result), "settled": bad.settled()}
    early = m._Attempt("a-u3", "unit", lambda register: "early")
    early.thread.start()
    early.wait(5)
    out["done_while_reserved"] = {"before": early.state, "worker_done": early.worker_done}
    early.running()
    out["done_while_reserved"]["after"] = early.state
    cancelled = m._Attempt("a-u4", "unit", lambda register: "x")
    cancelled.cancel()
    late = Recorded()
    cancelled.register(late)
    out["register_after_cancel"] = {"state": cancelled.state, "closed": late.closed, "report": cancelled.held[0].report(), "settled": cancelled.settled()}
    release = threading.Event()
    blocked = m._Attempt("a-u5", "unit", lambda register: (register(Recorded()), release.wait(30), "late")[-1])
    blocked.thread.start()
    poll(lambda: bool(blocked.held))
    blocked.running()
    deadline_hit = time.monotonic() + 0.2
    blocked.take_back(deadline_hit)
    out["take_back_deadline"] = {"state": blocked.state, "resource_closed": blocked.held[0].resource.closed, "worker_alive": blocked.thread.is_alive(),
                                 "worker_finished": blocked.worker_done, "reclaimable": blocked.reclaimable(), "settled": blocked.settled()}
    release.set()
    blocked.thread.join(5)
    blocked.take_back(time.monotonic() + 5)
    out["take_back_after_worker"] = {"worker_finished": blocked.worker_done, "settled": blocked.settled()}
    reclaim = m._Attempt("a-u6", "unit", lambda register: "x")
    reclaim.thread.start()
    reclaim.wait(5)
    ATTEMPTS = m.ATTEMPTS
    ATTEMPTS.slots[reclaim.id] = reclaim
    report = ATTEMPTS.reclaim(reclaim, 1.0)
    out["reclaim"] = {"report": view_record(report), "slots_after": sorted(ATTEMPTS.slots)}
    ATTEMPTS.slots.clear()
    out["fresh_registry"] = {"outstanding": m._Attempts().outstanding(), "started": m._Attempts().started}
    return out


def case_start_failure(ctx):
    m = ctx.module
    ctx.fresh()
    original = m._Attempt

    class Failing(original):
        def __init__(self, *args):
            super().__init__(*args)
            self.thread = SimpleNamespace(start=lambda: (_ for _ in ()).throw(RuntimeError("cannot start a thread")), name="failing")

    ctx.patch(m, "_Attempt", Failing)
    raised = outcome(lambda: m.ATTEMPTS.start(lambda register: "x", "failing"))
    return {"raised": raised, "slots": sorted(m.ATTEMPTS.slots), "started": m.ATTEMPTS.started}


def case_finish_and_sweep(ctx):
    m = ctx.module
    ctx.fresh()
    service = ctx.service(ctx.dir("finish"), Artifacts(), PROJECT_A)
    attempt = m.ATTEMPTS.start(lambda register: "ok", "finish")
    attempt.wait(5)
    before = sorted(m.ATTEMPTS.slots)
    m.ATTEMPTS.finish(attempt)
    return {"slot_before": before, "slots_after_finish": sorted(m.ATTEMPTS.slots), "outstanding": m.ATTEMPTS.outstanding(), "result": attempt.result(),
            "second_wait": outcome(lambda: service._bounded(lambda register: 3, 5))}


# ---- the capture (`_diagnose` over the real observation) --------------------------------------------------------------------------------------------
def case_capture_bound(ctx):
    pd = ctx.api.port_diagnosis
    ctx.patch(ctx.module, "DIAGNOSIS_SECONDS", 0.5)
    for name in ("_tcp_in_container", "_tcp_from_windows", "_tcp_from_wsl"):
        ctx.patch(pd, name, lambda *args, **kwargs: {"reachable": True, "observed": True, "how": "stub"})
    ctx.patch(pd, "_run", lambda argv, seconds: {"ran": False, "why": "command_failed"})
    asked = []

    def slow_docker(argv, cwd=None, env=None, timeout=None, **extra):
        asked.append(timeout)
        time.sleep(min(timeout if timeout else 10.0, 10.0) if timeout and timeout > 1 else 1.0)
        return SimpleNamespace(returncode=0, stdout="abc123\n")

    ctx.patch(ctx.module, "run_process", slow_docker)
    service = ctx.service(ctx.dir("capture"), Artifacts(), PROJECT_A)
    started = time.monotonic()
    record = service._diagnose("postgres", ctx.port(55432))
    spent = time.monotonic() - started
    ctx.patch(ctx.module, "DIAGNOSIS_SECONDS", 3.0)
    ctx.docker()
    fast = service._diagnose("redis", ctx.port(55433), failed_at=0.0)
    return {"fast": {"verdict": fast["verdict"], "means": fast["means"], "deadline_seconds": fast["deadline_seconds"], "lookup_found": fast["container_lookup"]["found"],
                     "observations": {k: {"how": v.get("how"), "reachable": v.get("reachable"), "observed": v.get("observed")} for k, v in sorted(fast["observations"].items())},
                     "context_keys": sorted(fast["context"]), "still_running": fast["still_running"], "delay_is_number": isinstance(fast["delay_from_failure_seconds"], float)},
            "lookup_bound": asked, "spent_within_bound": spent <= 3.0, "deadline_seconds": record["deadline_seconds"], "verdict": record["verdict"], "means": record["means"],
            "lookup": {"found": record["container_lookup"]["found"], "positive": record["container_lookup"]["seconds"] > 0}, "keys": sorted(record),
            "observations": {k: {"how": v.get("how"), "reachable": v.get("reachable")} for k, v in sorted(record["observations"].items())}}


def case_capture_fails(ctx):
    pd = ctx.api.port_diagnosis

    def explode(port, **kwargs):
        raise RuntimeError("the capture could not start")

    ctx.patch(pd, "observe", explode)
    service = ctx.service(ctx.dir("capture-fails"), Artifacts(), PROJECT_A)
    record = service._diagnose("redis", 56379)
    return {"record": record, "uses_module_bound": record["deadline_seconds"] == ctx.module.DIAGNOSIS_SECONDS,
            "failed_at_forwarded": service._diagnose("redis", 1, failed_at=3.0)["verdict"]}


CASES = [
    ("constants", case_constants), ("project_names", case_project_names), ("command", case_command), ("lifecycle", case_lifecycle),
    ("endpoint_refusals", case_endpoint_refusals), ("directory_exists", case_directory_exists), ("cleanup_guards", case_cleanup_guards),
    ("stale_cycle", case_stale_cycle), ("invalid_manifest", case_invalid_manifest), ("collect_stale", case_collect_stale),
    ("refusal_kinds", case_refusal_kinds), ("readiness_cannot_answer", case_readiness_cannot_answer), ("readiness_never_accepts", case_readiness_never_accepts),
    ("readiness_diagnosis_lookup", case_readiness_diagnosis_lookup), ("readiness_waits_for_answer", case_readiness_waits_for_answer),
    ("readiness_not_this_project", case_readiness_not_this_project), ("readiness_receipt", case_readiness_receipt), ("readiness_late_answer", case_readiness_late_answer),
    ("readiness_silent_service", case_readiness_silent_service), ("readiness_identity_unreadable", case_readiness_identity_unreadable),
    ("readiness_exception_chain", case_readiness_exception_chain), ("container_identity", case_container_identity), ("answer_over_loopback", case_answer_over_loopback),
    ("timed_out_attempt", case_timed_out_attempt), ("unreclaimed_limit", case_unreclaimed_limit), ("close_that_hangs", case_close_that_hangs),
    ("registered_after_reclamation", case_registered_after_reclamation), ("slot_limits", case_slot_limits), ("stubborn_resource", case_stubborn_resource),
    ("registered_after_window", case_registered_after_window), ("slot_released", case_slot_released), ("other_attempt_untouched", case_other_attempt_untouched),
    ("reservation", case_reservation), ("unreadable_resource", case_unreadable_resource), ("state_of", case_state_of), ("held", case_held),
    ("attempt_units", case_attempt_units), ("start_failure", case_start_failure), ("finish_and_sweep", case_finish_and_sweep),
    ("capture_bound", case_capture_bound), ("capture_fails", case_capture_fails),
]
SHORT_RECLAIM = 0.5


def run(api, root: Path) -> dict:
    ctx = Ctx(api, root)
    saved = dict(os.environ)
    os.environ.clear()
    os.environ.update(SCRIPTED_ENV)
    out = {}
    USED_PORTS.clear()
    try:
        for name, case in CASES:
            with contextlib.ExitStack() as stack:
                ctx.stack, ctx.ports = stack, []
                if name != "constants":
                    ctx.patch(ctx.module, "RECLAIM_SECONDS", SHORT_RECLAIM)
                ctx.fresh()
                try:
                    out[name] = ctx.show(outcome(lambda case=case: case(ctx)))
                finally:
                    ctx.drain()
    finally:
        os.environ.clear()
        os.environ.update(saved)
    return {"case_count": len(out), "cases": out}
