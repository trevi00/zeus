"""Buzz A4: the owner-run runtime matrix on the disposable relay stack (compose project `zeus-buzz-conntest`).

SKIPPED unless BUZZ_CONNTEST=1 ("owner-run: needs Docker (Buzz Batch A4)"): workers have no Docker. The test starts
`tests/fixtures/buzz_conntest/compose.yaml` (relay pinned by digest, postgres, redis, minio; the relay published only
on 127.0.0.1:<ephemeral port>), drives it with the A1-A3 modules (`BuzzRelayClient`, `NostrEventSigner`,
`verify_event`, `TestRoleKeys`, `InboundPass`, `BuzzOutbox`) and writes a JSON report (path printed at the end).

Owner prerequisites (each is checked by step 1, which fails with a message naming the gap):
- the `__DIGEST_TBD__` placeholders for postgres and redis in the compose file are pinned;
- the R-P guard (`compare/guard/provider_guard.py`, installed by conftest in every pytest process) is default-deny for
  docker and admits no `compose`/`pause`/`ps`/`volume`/`network` form and no `inspect` of a non-fixture name: the test
  declares the exact argv forms it needs (`docker_forms`) and dry-checks each through `provider_guard.docker_policy`.
  The owner must admit them (or run where the guard is not installed). The test never bypasses the guard.

Run: `BUZZ_CONNTEST=1 ZEUS_TEST_DOCKER=1 uv run pytest -s tests/test_buzz_a4_conntest.py` (`-s` shows the report path).

Steps (A = asserted, R = recorded verbatim in the report; a failing step is named and the matrix goes on):
 1 preconditions  A: digests pinned, docker forms admitted, no resource of this project exists (a foreign one is
                     never cleaned), a free loopback port.
 2 keys           A: owner, conductor, stranger and relay keys exist (0600, TestRoleKeys); the env file is 0600.
                     No key or password is printed or put in a message.
 3 up + health    A: relay healthy within 180 s.
 4 bootstrap      A: owner AUTH + kind 9030 (conductor), kind 9007 (private channel), kind 9000 (conductor joins).
                     R: each relay answer.
 5 negative       A: stranger publish -> `restricted:`, not stored. R: wire frames, number of EVENT sends.
 6 B1             A: same kind-9 event twice -> accepted, then `duplicate:`.
 7 B2             A: reconnect + `since` returns the event once. R: raw frame count.
 8 B3             A: graceful restart; a live subscribe ends with close code 1012; reconnect + `since` finds the event
                     published after the restart by a second client; no duplicate effect.
 9 B4             A: 45010 create / update(prev=head) accepted, stale prev refused, resubmitted create succeeds, the
                     `#d` query returns the head only (NIP-AR). R: every relay answer.
10 B7             A: reconnect + query_all recovers every accepted event. R: what a non-reading subscriber saw
                     (closed / frames dropped / all delivered) under the relay's default buffer.
11 drift          A: created_at = now - 1000 is refused with a timestamp message the outbox recognises; the A3b outbox
                     leaves the op `unknown` and reconciles by `ids` (nothing found). R: the message verbatim.
12 EOSE-partial   A: the InboundPass interval is `gap_unknown`. R: whether EOSE arrived under a paused postgres.
13 lease          A: two InboundPass on one MemoryStore: only the holder commits; the stale one commits nothing.
14 hardening      A: every container: not privileged, not host network, no docker socket mount, no cap_add, ports
                     only on 127.0.0.1 (inspect with --format on those fields only: never the env).
15 cleanup        A: `down -v` for this project, then no container, network or volume carries its label.

The Buzz source this relies on (d7a35afa, read only): 9007 (ingest.rs:2970-3062 pre-creates the channel from the h tag,
a repeat answers `duplicate: channel already exists`; side_effects.rs:458, :1912-1936 tags name/visibility/
channel_type/about), 9000 (side_effects.rs:485, :1435 h + p tags), 9030 (relay_admin.rs:1-13, p tag), the timestamp
refusal (ingest.rs:2376), the send buffer and its grace limit (config.rs:714-728), NIP-AR (docs/nips/NIP-AR.md).
"""

import json
import os
import secrets
import shutil
import socket
import subprocess
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

import pytest
from websockets.exceptions import ConnectionClosed
from websockets.sync.client import connect as ws_connect

from codex_harness.coordination.application.bridge_lease import BridgeLease
from codex_harness.coordination.application.remote_inbox import RemoteInbox
from codex_harness.credentials.adapters.role_keys import TestRoleKeys
from codex_harness.kernel.errors import ContractError
from codex_harness.kernel.ids import canonical
from codex_harness.observation.adapters.buzz_relay import BuzzRelayClient, reconnect_delay
from codex_harness.observation.adapters.event_signer import NostrEventSigner
from codex_harness.observation.adapters.nostr_verify import verify_event
from codex_harness.observation.application.buzz_inbound import InboundPass
from codex_harness.observation.application.buzz_outbox import TIMESTAMP_MARKS, BuzzOutbox
from codex_harness.observation.domain import nostr_event as ne
from codex_harness.storage.adapters.memory_store import MemoryStore

pytestmark = pytest.mark.skipif(os.environ.get("BUZZ_CONNTEST") != "1",
                                reason="owner-run: needs Docker (Buzz Batch A4)")

PROJECT = "zeus-buzz-conntest"
LABEL = f"label=com.docker.compose.project={PROJECT}"
COMPOSE = Path(__file__).resolve().parent / "fixtures" / "buzz_conntest" / "compose.yaml"
ROLES = ("owner", "conductor", "stranger", "relay")
MAX_SIZE = 4 * 1024 * 1024
HEALTH_SECONDS = 180
PACE_SECONDS = 1.2  # <= 50 persistent publishes per minute per key: under the relay's 60/min human limit
B7_EVENTS = 40
STOP_TIMEOUT = 45  # the relay drains for up to 35 s after SIGTERM (A4-PREP fact 4)
CHANNEL_NAME = "zeus-conntest"
SOURCE_REFS = [
    "ingest.rs:2970-3062 (9007 name/visibility/channel_type, h-tag pre-creation, duplicate: channel already exists)",
    "side_effects.rs:458,1912-1936 (9007 handler); side_effects.rs:485,1435 (9000 h + p tags)",
    "relay_admin.rs:1-13 (9030 admin/owner adds the first p tag; processed directly, not stored)",
    "ingest.rs:2376 (invalid: event timestamp too far from server time)",
    "config.rs:714-728 (BUZZ_SEND_BUFFER default 1000, BUZZ_SLOW_CLIENT_GRACE_LIMIT default 15)",
    "docs/nips/NIP-AR.md (45010 create/update/prev, resubmission, current-state queries)",
]
OWNER_DECISIONS = [
    "pin the postgres:17-alpine and redis:7-alpine digests (compose placeholders)",
    "admit the compose/pause/ps/network/volume/inspect docker forms to the R-P guard (see step 1)",
    "B7 under the default BUZZ_SEND_BUFFER=1000 / grace 15 cannot be provoked within 60 messages/min per key: "
    "decide whether to tune BUZZ_SEND_BUFFER and BUZZ_SLOW_CLIENT_GRACE_LIMIT for a drop/close measurement",
]


# -- the one docker chokepoint ------------------------------------------------------------------------------------

def compose_tail(env_file, *tail):
    return ["compose", "-p", PROJECT, "-f", str(COMPOSE), "--env-file", str(env_file), *tail]


def docker_forms(env_file):
    """Every docker argv shape the test uses (without the `docker` word); step 1 dry-checks each one."""
    inspect_format = "{{.State.Status}}"
    return [
        compose_tail(env_file, "up", "-d"),
        compose_tail(env_file, "ps", "-q", "relay"),
        compose_tail(env_file, "ps", "-a", "-q"),
        compose_tail(env_file, "restart", "-t", str(STOP_TIMEOUT), "relay"),
        compose_tail(env_file, "pause", "postgres"),
        compose_tail(env_file, "unpause", "postgres"),
        compose_tail(env_file, "logs", "--no-color", "--tail", "200", "relay"),
        compose_tail(env_file, "down", "-v", "--remove-orphans"),
        ["ps", "-a", "-q", "--filter", LABEL],
        ["network", "ls", "-q", "--filter", LABEL],
        ["volume", "ls", "-q", "--filter", LABEL],
        ["inspect", "--format", inspect_format, f"{PROJECT}-relay-1"],
    ]


class Ctx:
    """The run's state: paths, keys, the secrets to scrub, the shared pacer and the report."""

    def __init__(self, tmp: Path):
        self.tmp = tmp
        self.env_file = tmp / "conntest.env"
        self.keys = TestRoleKeys(tmp / "keys")
        self.signer = NostrEventSigner(self.keys.pubkey, self.keys.sign_id)
        self.secrets: set[str] = set()
        self.port = 0
        self.url = ""
        self.owned = False  # preconditions passed: nothing foreign exists under the project label
        self.started = False  # `up` was issued: this run created resources that `down -v` must remove
        self.chan = ""
        self.events: dict[str, str] = {}  # label -> event id, for the report
        self.last_sent: dict[str, float] = {}
        self.t0 = int(time.time())

    # -- docker -------------------------------------------------------------------------------------------------

    def scrub(self, text: str) -> str:
        for value in self.secrets:
            text = text.replace(value, "***")
        return text

    def docker(self, args, timeout, ok=(0,)):
        try:
            done = subprocess.run(["docker", *args], capture_output=True, text=True, timeout=timeout,
                                  stdin=subprocess.DEVNULL, check=False)
        except subprocess.TimeoutExpired:
            raise AssertionError(f"docker {self.verb(args)} timed out after {timeout}s") from None
        except OSError as exc:
            raise AssertionError(f"docker {self.verb(args)} could not start: {type(exc).__name__}") from None
        if done.returncode not in ok:
            raise AssertionError(f"docker {self.verb(args)} exited {done.returncode}: "
                                 f"{self.scrub(done.stderr or '')[-300:].strip()}")
        return done

    @staticmethod
    def verb(args):
        return " ".join(args[7:9] if args[:1] == ["compose"] else args[:2])

    def compose(self, *tail, timeout=120, ok=(0,)):
        return self.docker(compose_tail(self.env_file, *tail), timeout, ok)

    def relay_container(self) -> str:
        cid = self.compose("ps", "-q", "relay", timeout=60).stdout.strip()
        assert cid, "the relay container does not exist"
        return cid

    def relay_state(self) -> str:
        fmt = "{{.State.Status}}/{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}"
        return self.docker(["inspect", "--format", fmt, self.relay_container()], 30).stdout.strip()

    def wait_healthy(self, seconds=HEALTH_SECONDS) -> float:
        started, state = time.monotonic(), "unknown"
        while time.monotonic() - started < seconds:
            try:
                state = self.relay_state()
            except AssertionError as exc:
                state = f"inspect failed ({str(exc)[:80]})"
            if state == "running/healthy":
                return round(time.monotonic() - started, 1)
            if state.startswith(("exited", "dead")):
                break
            time.sleep(3)
        self.save_relay_tail()
        raise AssertionError(f"the relay is not healthy after {seconds}s (last state {state}); "
                             f"scrubbed log tail: {self.tmp / 'relay-tail.log'}")

    def save_relay_tail(self):
        try:
            logs = self.compose("logs", "--no-color", "--tail", "200", "relay", timeout=60).stdout
        except AssertionError:
            return
        (self.tmp / "relay-tail.log").write_text(self.scrub(logs), encoding="utf-8")

    # -- relay clients -----------------------------------------------------------------------------------------

    def client(self, role, *, recv_timeout=30, wire=None):
        connect = None
        if wire is not None:
            def connect(url, **options):
                return _Wire(ws_connect(url, **options), wire)
        return BuzzRelayClient(self.url, auth_signer=self.signer, auth_role=role, verifier=_Verifier(),
                               connect=connect, max_size=MAX_SIZE, recv_timeout=recv_timeout)

    def pace(self, role):
        wait = self.last_sent.get(role, -1e9) + PACE_SECONDS - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self.last_sent[role] = time.monotonic()

    def sign(self, role, kind, tags, content="", created_at=None):
        return self.signer.sign(role, {"kind": kind, "created_at": int(time.time()) if created_at is None
                                       else created_at, "tags": tags, "content": content})

    def send(self, client, role, kind, tags, content="", created_at=None):
        """Sign, pace (the relay's per-key message limit) and publish; `(event, relay answer)`."""
        event = self.sign(role, kind, tags, content, created_at)
        self.pace(role)
        return event, client.publish(event)

    def message(self, client, role, content, label=None):
        event, answer = self.send(client, role, 9, [["h", self.chan]], content)
        if label:
            self.events[label] = event["id"]
        return event, answer


class _Verifier:
    def verify(self, event):
        return verify_event(event)


class _Wire:
    """A websocket proxy that logs frame types (and the text of OK/CLOSED/NOTICE) for the report."""

    def __init__(self, ws, log):
        self._ws, self._log = ws, log

    def send(self, text):
        self._log.append(["send", _frame_note(text)])
        return self._ws.send(text)

    def recv(self, *args, **kwargs):
        text = self._ws.recv(*args, **kwargs)
        self._log.append(["recv", _frame_note(text)])
        return text

    def __getattr__(self, name):
        return getattr(self._ws, name)


def _frame_note(text):
    try:
        items = json.loads(text)
        head = items[0]
    except (TypeError, ValueError, IndexError):
        return "unparsed"
    if head == "OK":
        return [head, *items[2:]]
    return [head, *items[1:]] if head in ("CLOSED", "NOTICE") else head


@contextmanager
def connected(ctx, role, **options):
    client = ctx.client(role, **options)
    try:
        yield client
    finally:
        client.close()


# -- the report ------------------------------------------------------------------------------------------------

class Matrix:
    def __init__(self, ctx, path):
        self.ctx, self.path, self.steps, self.failed, self.aborted = ctx, path, [], [], False
        self.save()

    def save(self):
        body = {"project": PROJECT, "relay_url": self.ctx.url, "buzz_source": SOURCE_REFS,
                "owner_decisions": OWNER_DECISIONS, "steps": self.steps}
        self.path.write_text(json.dumps(body, indent=2, default=str), encoding="utf-8")

    def step(self, name, asserts, fn, *, needs=True, fatal=False):
        record = {"step": name, "asserts": asserts, "records": {}}
        self.steps.append(record)
        if self.aborted or not needs:
            record["status"] = "skipped"
            record["why"] = "an earlier fatal step failed" if self.aborted else "a prerequisite step failed"
            self.save()
            return False
        started = time.monotonic()
        try:
            fn(record["records"])
            record["status"] = "pass"
        except Exception as exc:  # noqa: BLE001 - the matrix names the step and goes on
            record["status"] = "FAIL"
            record["error"] = self.ctx.scrub(f"{type(exc).__name__}: {exc}")[:800]
            self.failed.append(name)
            self.aborted = self.aborted or fatal
        record["seconds"] = round(time.monotonic() - started, 1)
        self.save()
        return record["status"] == "pass"


def summarize(result):
    return {key: (len(value) if key == "events" else value) for key, value in result.items()}


def free_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


# -- steps -----------------------------------------------------------------------------------------------------

def step_preconditions(ctx, rec):
    assert shutil.which("docker"), "docker is not on PATH"
    text = COMPOSE.read_text(encoding="utf-8")
    assert "__DIGEST_TBD__" not in text, "owner must pin the postgres/redis digests in the compose file"
    import provider_guard  # compare/guard, put on sys.path by conftest

    refused = []
    for form in docker_forms(ctx.env_file):
        try:
            provider_guard.docker_policy(["docker", *form], os.environ)
        except provider_guard.DockerRefused as exc:
            refused.append(f"docker {ctx.verb(form)} ... ({exc})")
    rec["guard_forms_checked"] = len(docker_forms(ctx.env_file))
    assert not refused, ("R-P guard refuses docker forms this test needs; owner admission needed: "
                         + "; ".join(sorted(set(refused))))
    residue = {
        "containers": ctx.docker(["ps", "-a", "-q", "--filter", LABEL], 60).stdout.split(),
        "networks": ctx.docker(["network", "ls", "-q", "--filter", LABEL], 60).stdout.split(),
        "volumes": ctx.docker(["volume", "ls", "-q", "--filter", LABEL], 60).stdout.split(),
    }
    rec["residue_before"] = {key: len(value) for key, value in residue.items()}
    assert not any(residue.values()), ("a resource of project zeus-buzz-conntest already exists; it is foreign "
                                       "to this run and is never cleaned")
    ctx.port = free_port()
    ctx.url = f"ws://127.0.0.1:{ctx.port}"
    rec["port"] = ctx.port
    ctx.owned = True


def step_keys(ctx, rec):
    for role in ROLES:
        ctx.keys.create(role)
    pubkeys = {role: ctx.keys.pubkey(role) for role in ROLES}
    assert len(set(pubkeys.values())) == len(ROLES), "the role keys are not distinct"
    relay_secret = (ctx.tmp / "keys" / "relay.key").read_bytes().hex()  # the file is the test's own throwaway
    values = {
        "RELAY_OWNER_PUBKEY": pubkeys["owner"],
        "BUZZ_RELAY_PRIVATE_KEY": relay_secret,
        "BUZZ_GIT_HOOK_HMAC_SECRET": secrets.token_hex(32),
        "POSTGRES_PASSWORD": secrets.token_hex(16),
        "REDIS_PASSWORD": secrets.token_hex(16),
        "BUZZ_S3_ACCESS_KEY": "k" + secrets.token_hex(8),
        "BUZZ_S3_SECRET_KEY": secrets.token_hex(16),
        "BUZZ_CONNTEST_PORT": str(ctx.port),
        "BUZZ_CONNTEST_ENV_FILE": str(ctx.env_file),
    }
    public = ("BUZZ_CONNTEST_PORT", "BUZZ_CONNTEST_ENV_FILE", "RELAY_OWNER_PUBKEY")
    ctx.secrets.update(value for key, value in values.items() if key not in public)
    fd = os.open(ctx.env_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        for key, value in values.items():
            handle.write(f"{key}={value}\n")
    assert ctx.env_file.stat().st_mode & 0o777 == 0o600, "the env file is not mode 0600"
    rec["pubkeys"] = pubkeys
    rec["env_file_mode"] = "0600"


def step_up(ctx, rec):
    ctx.started = True
    ctx.compose("up", "-d", timeout=900)
    rec["healthy_after_seconds"] = ctx.wait_healthy()


def step_bootstrap(ctx, rec):
    conductor = ctx.keys.pubkey("conductor")
    with connected(ctx, "owner") as owner:
        _, rec["9030_add_conductor"] = ctx.send(owner, "owner", 9030, [["p", conductor]])
        assert rec["9030_add_conductor"]["accepted"] is True, "kind 9030 (add conductor) was not accepted"
        chan = str(uuid.uuid4())
        tags = [["h", chan], ["name", CHANNEL_NAME], ["visibility", "private"], ["channel_type", "stream"]]
        _, rec["9007_create_channel"] = ctx.send(owner, "owner", 9007, tags)
        assert rec["9007_create_channel"]["accepted"] is True, "kind 9007 (create private channel) was not accepted"
        _, rec["9000_put_conductor"] = ctx.send(owner, "owner", 9000, [["h", chan], ["p", conductor]])
        assert rec["9000_put_conductor"]["accepted"] is True, "kind 9000 (add conductor to the channel) refused"
        ctx.chan = chan
    rec["channel"] = chan


def step_negative(ctx, rec):
    wire = []
    with connected(ctx, "stranger", wire=wire) as stranger:
        event, answer = ctx.send(stranger, "stranger", 9, [["h", ctx.chan]], "stranger must not publish")
    rec["answer"] = answer
    rec["wire"] = wire
    rec["event_sends"] = sum(1 for item in wire if item == ["send", "EVENT"])
    assert answer["accepted"] is False and answer["prefix"] == "restricted", \
        f"the stranger was not answered `restricted:`: {answer}"
    assert rec["event_sends"] <= 2, "a restricted answer must be final (at most one auth-required retry)"
    with connected(ctx, "owner") as owner:
        rec["stored_copies"] = len(owner.query([{"ids": [event["id"]]}])["events"])
    assert rec["stored_copies"] == 0, "the stranger's event was stored"


def step_b1(ctx, rec):
    with connected(ctx, "conductor") as conductor:
        event, first = ctx.message(conductor, f"b1-{uuid.uuid4()}", "b1")
        second = conductor.publish(event)
    rec["first"], rec["second"] = first, second
    assert first["accepted"] is True and first["prefix"] != "duplicate", f"first publish: {first}"
    assert second["accepted"] is True and second["prefix"] == "duplicate", f"second publish: {second}"


def step_b2(ctx, rec):
    published = ctx.events["b1"]
    since = ctx.t0
    with connected(ctx, "conductor") as client:  # a fresh connection: the reconnect
        result = client.query([{"kinds": [9], "#h": [ctx.chan], "since": since}])
    ids = [event["id"] for event in result["events"]]
    rec["result"] = summarize(result)
    assert result["ended"] == "eose", f"history ended {result['ended']}"
    assert ids.count(published) == 1, "the B1 event is not returned exactly once"
    assert len(ids) == len(set(ids)), "the result carries a duplicate id"


def step_b3(ctx, rec):
    live = {"events": [], "reason": None, "close_code": None, "error": None}
    started = int(time.time())
    subscriber = ctx.client("conductor")

    def listen():
        generator = subscriber.subscribe("zeus-b3", [{"kinds": [9], "#h": [ctx.chan], "since": started - 2}])
        try:
            while True:
                live["events"].append(next(generator)["id"])
        except StopIteration as stop:
            live["reason"] = stop.value
        except Exception as exc:  # noqa: BLE001 - reported, not swallowed
            live["error"] = f"{type(exc).__name__}"
        live["close_code"] = subscriber.last_close_code

    thread = threading.Thread(target=listen, daemon=True)
    thread.start()
    try:
        with connected(ctx, "owner") as owner:
            sentinel, answer = ctx.message(owner, f"b3-sentinel-{uuid.uuid4()}", "b3_sentinel")
        assert answer["accepted"] is True, f"sentinel publish: {answer}"
        deadline = time.monotonic() + 30
        while sentinel["id"] not in live["events"] and time.monotonic() < deadline:
            time.sleep(0.2)
        assert sentinel["id"] in live["events"], "the live subscription never received the sentinel"
        restart_started = int(time.time())
        ctx.compose("restart", "-t", str(STOP_TIMEOUT), "relay", timeout=STOP_TIMEOUT + 90)
        thread.join(timeout=30)
        assert not thread.is_alive(), "the live subscribe did not end after the relay restarted"
        rec["live"] = {"reason": live["reason"], "close_code": live["close_code"], "error": live["error"],
                       "events_before_restart": len(live["events"])}
        rec["reconnect_delay_for_1012"] = reconnect_delay(live["close_code"], 0)
        assert live["close_code"] == 1012, f"the live subscribe closed with {live['close_code']}, not 1012"
        assert rec["reconnect_delay_for_1012"] is not None, "the client policy does not reconnect after 1012"
        rec["healthy_after_restart_seconds"] = ctx.wait_healthy()
        with connected(ctx, "owner") as second:  # a second client, after the restart
            gap, answer = ctx.message(second, f"b3-gap-{uuid.uuid4()}", "b3_gap")
            rec["gap_publish"] = answer
            assert answer["accepted"] is True, f"gap publish: {answer}"
            replay = second.publish(gap)
        rec["gap_replay"] = replay
        assert replay["accepted"] is True and replay["prefix"] == "duplicate", f"replay: {replay}"
        found = {}
        for attempt in range(1, 11):  # the reconnect: the subscriber's own client, with `since`
            found = subscriber.query([{"kinds": [9], "#h": [ctx.chan], "since": restart_started - 600}])
            if found["ended"] == "eose":
                break
            time.sleep(3)
        ids = [event["id"] for event in found["events"]]
        rec["reconcile"] = {**summarize(found), "attempts": attempt}
        assert gap["id"] in ids and sentinel["id"] in ids, "reconciliation lost an event"
        assert len(ids) == len(set(ids)), "reconciliation returned a duplicate id"
    finally:
        if not thread.is_alive():  # the client is not thread-safe: never close it under the listener
            subscriber.close()


def step_b4(ctx, rec):
    artifact = str(uuid.uuid4())

    def head(op, title, content, prev=None):
        tags = [["ar", "1"], ["d", artifact], ["h", ctx.chan], ["type", "zeus.conntest"], ["title", title],
                ["op", op]]
        if prev:
            tags.append(["prev", prev])
        return tags, content

    with connected(ctx, "conductor") as client:
        tags, content = head("create", "v1", '{"version":1}')
        create, created = ctx.send(client, "conductor", 45010, tags, content)
        rec["create"] = created
        assert created["accepted"] is True, f"create: {created}"
        tags, content = head("update", "v2", '{"version":2}', prev=create["id"])
        update, updated = ctx.send(client, "conductor", 45010, tags, content)
        rec["update_with_current_prev"] = updated
        assert updated["accepted"] is True, f"update: {updated}"
        tags, content = head("update", "v2-stale", '{"version":"stale"}', prev=create["id"])
        _, stale = ctx.send(client, "conductor", 45010, tags, content)
        rec["update_with_stale_prev"] = stale
        assert stale["accepted"] is False, f"a stale prev was not refused: {stale}"
        resubmitted = client.publish(create)
        rec["resubmit_accepted_create"] = resubmitted
        assert resubmitted["accepted"] is True, f"resubmitting the accepted create failed: {resubmitted}"
        current = client.query([{"kinds": [45010], "#d": [artifact]}])
        rec["query_by_d"] = {**summarize(current), "ids": [event["id"] for event in current["events"]],
                             "head": update["id"], "create": create["id"]}
        assert current["ended"] == "eose", f"query ended {current['ended']}"
        assert [event["id"] for event in current["events"]] == [update["id"]], \
            "the #d query did not return the current head alone"


def _slow_subscriber(ctx, rec, publish_all):
    """A subscriber that stops reading while `publish_all` runs, then drains what is left."""
    since = int(time.time()) - 1
    with ws_connect(ctx.url, proxy=None, compression=None, max_size=MAX_SIZE, open_timeout=10) as ws:
        challenge = None
        for _ in range(5):
            frame = json.loads(ws.recv(timeout=10))
            if frame[0] == "AUTH":
                challenge = frame[1]
                break
        assert challenge, "the relay sent no AUTH challenge"
        signed = ctx.signer.sign("conductor", ne.auth_event_template(ctx.url, challenge, int(time.time())))
        ws.send(ne.auth_frame(signed))
        while True:
            frame = json.loads(ws.recv(timeout=10))
            if frame[0] == "OK" and frame[1] == signed["id"]:
                rec["slow_auth"] = frame[2:]
                break
        assert rec["slow_auth"][0] is True, "the slow subscriber could not authenticate"
        ws.send(ne.req("zeus-b7", {"kinds": [9], "#h": [ctx.chan], "since": since}))
        while json.loads(ws.recv(timeout=10))[0] != "EOSE":
            pass
        accepted = publish_all()  # the subscriber reads nothing meanwhile
        time.sleep(3)
        seen, closed = set(), None
        try:
            while True:
                frame = json.loads(ws.recv(timeout=5))
                if frame[0] == "EVENT" and frame[2]["id"] in accepted:
                    seen.add(frame[2]["id"])
        except TimeoutError:
            pass
        except ConnectionClosed as exc:
            closed = exc.rcvd.code if exc.rcvd else "no close frame"
    rec["slow_subscriber"] = {"published_accepted": len(accepted), "received_after_stall": len(seen),
                              "closed_by_relay": closed}
    rec["slow_subscriber"]["observed"] = ("closed" if closed is not None else "all_delivered"
                                          if len(seen) == len(accepted) else "frames_dropped")


def step_b7(ctx, rec):
    accepted, refused = {}, []
    size = 40000

    def publish_all():
        nonlocal size
        with connected(ctx, "owner") as owner:
            for index in range(B7_EVENTS):
                body = f"b7-{uuid.uuid4()}-{index}-".ljust(size, "x")
                event, answer = ctx.send(owner, "owner", 9, [["h", ctx.chan]], body)
                if answer["accepted"] is True:
                    accepted[event["id"]] = index
                    continue
                refused.append(answer)
                if index == 0 and size > 1000:  # an over-size refusal: retry smaller (recorded)
                    size //= 4
        return accepted

    started = int(time.time()) - 1
    _slow_subscriber(ctx, rec, publish_all)
    rec["content_bytes"] = size
    rec["refused_publishes"] = refused[:5]
    assert accepted, "no B7 event was accepted"
    with connected(ctx, "conductor") as client:
        recovered = client.query_all({"kinds": [9], "#h": [ctx.chan], "since": started})
    ids = {event["id"] for event in recovered["events"]}
    rec["recover"] = {key: (len(value) if key == "events" else value) for key, value in recovered.items()}
    assert recovered["ended"] == "eose", f"query_all ended {recovered['ended']}"
    assert set(accepted) <= ids, f"{len(set(accepted) - ids)} accepted events were not recovered"


def step_drift(ctx, rec):
    created_at = int(time.time()) - 1000
    with connected(ctx, "owner") as owner:
        event, answer = ctx.send(owner, "owner", 9, [["h", ctx.chan]], "drift-old", created_at)
        rec["publish_old_event"] = answer
        assert answer["accepted"] is False, f"an event 1000 s old was accepted: {answer}"
        assert any(mark in answer["message"].lower() for mark in TIMESTAMP_MARKS), \
            "the outbox does not recognise this timestamp refusal (A3b TIMESTAMP_MARKS)"
        store, lease = MemoryStore(), BridgeLease()
        with store.transaction() as tx:
            generation = lease.acquire(tx, "conntest-outbox", time.time(), 600)
        clock = {"now": created_at + 100}  # the outbox believes the event is still inside its drift window
        outbox = BuzzOutbox(store, owner, ctx.signer, lease, lambda: clock["now"], role="owner",
                            replan=lambda subject: None)
        unsigned = {"kind": 9, "created_at": created_at, "tags": [["h", ctx.chan]], "content": "drift-outbox"}
        with store.transaction() as tx:
            enqueued = outbox.enqueue(tx, generation, "conntest/drift", 1, unsigned, "state")
        ctx.pace("owner")
        first = outbox.deliver(generation)
        clock["now"] = int(time.time())  # now the window has passed
        second = outbox.deliver(generation)
        with store.transaction() as tx:
            [row] = tx.scan("buzz_outbox")
        rec["outbox"] = {"enqueue": enqueued, "deliver_in_window": first, "deliver_after_window": second,
                         "status": row["status"], "reconcile": row["reconcile"],
                         "relay_message": row["relay_message"]}
        assert first["sent"] == 1 and row["reconcile"] is True, f"the timestamp refusal was not seen: {first}"
        assert second["unknown"] == 1 and row["status"] == "unknown", f"the op did not stay unknown: {second}"
        absent = owner.query([{"ids": [row["event_id"]]}])
        rec["query_by_ids"] = summarize(absent)
        assert absent["ended"] == "eose" and not absent["events"], "the refused event exists on the relay"


def step_eose_partial(ctx, rec):
    paused = False
    client = ctx.client("conductor", recv_timeout=10)
    try:
        warm = client.query([{"kinds": [9], "#h": [ctx.chan], "limit": 1}])
        rec["before_pause"] = summarize(warm)
        assert warm["ended"] == "eose" and warm["events"], "the warm-up history query did not work"
        ctx.compose("pause", "postgres", timeout=60)
        paused = True
        rec["history_under_pause"] = summarize(client.query([{"kinds": [9], "#h": [ctx.chan], "limit": 5}]))
        store, lease, inbox = MemoryStore(), BridgeLease(), RemoteInbox()
        with store.transaction() as tx:
            generation = lease.acquire(tx, "conntest-eose", time.time(), 600)
        inbound = InboundPass(store, client, inbox, lease, lambda event: "stub_recorded",
                              [ctx.keys.pubkey("conductor")], [ctx.chan], time.time)
        rec["inbound_pass"] = inbound.run(generation)[ctx.chan]
        with store.transaction() as tx:
            [record] = tx.scan("buzz_passes")
        rec["pass_record"] = {key: record[key] for key in ("state", "coverage", "ended")}
        assert (record["state"], record["coverage"]) == ("gap_unknown", "gap_unknown"), \
            f"the interval is not gap_unknown: {rec['pass_record']}"
        assert record["retired_at"] is None, "an unproven interval was retired"
    finally:
        client.close()
        if paused:
            ctx.compose("unpause", "postgres", timeout=60)
            rec["healthy_after_unpause_seconds"] = ctx.wait_healthy(120)
    with connected(ctx, "conductor") as after:
        rec["after_unpause"] = summarize(after.query([{"kinds": [9], "#h": [ctx.chan], "limit": 1}]))
    assert rec["after_unpause"]["ended"] == "eose", "the relay did not recover after unpause"


def step_lease(ctx, rec):
    conductor = ctx.keys.pubkey("conductor")
    store, lease, inbox, seen = MemoryStore(), BridgeLease(), RemoteInbox(), []

    def sink(event):
        seen.append(event["id"])
        return "stub_recorded"

    def rows():
        with store.transaction() as tx:
            return tx.scan("remote_inbox")

    with connected(ctx, "conductor") as conductor_client, connected(ctx, "owner") as owner_client:
        ctx.message(conductor_client, f"lease-{uuid.uuid4()}", "lease_probe")  # a fresh event inside the lookback
        holder = InboundPass(store, conductor_client, inbox, lease, sink, [conductor], [ctx.chan], time.time)
        other = InboundPass(store, owner_client, inbox, lease, sink, [conductor], [ctx.chan], time.time)
        now = time.time()
        with store.transaction() as tx:
            generation = lease.acquire(tx, "bridge-A", now, 60)
            denied = lease.acquire(tx, "bridge-B", now, 60)
        rec["acquire"] = {"bridge-A": generation, "bridge-B_while_A_holds": denied}
        assert generation is not None and denied is None, "the second bridge acquired a live lease"
        first = holder.run(generation)[ctx.chan]
        committed = canonical(sorted(store.data.items(), key=str))
        rec["holder_pass"] = {key: first[key] for key in ("ended", "events", "inserted", "sunk")}
        assert first["inserted"] >= 1 and rows(), "the lease holder committed nothing"
        try:
            other.run(generation + 1)  # the generation B would hold had it acquired the lease
        except ContractError as exc:
            rec["second_pass_without_lease"] = str(exc)
        else:
            raise AssertionError("the second instance ran under a lease it does not hold")
        assert canonical(sorted(store.data.items(), key=str)) == committed, "the second instance changed the store"
        with store.transaction() as tx:  # expiry hands the lease over; the old generation is fenced out
            takeover = lease.acquire(tx, "bridge-B", now + 120, 60)
        assert takeover == generation + 1, f"takeover generation {takeover}"
        try:
            holder.run(generation)
        except ContractError as exc:
            rec["old_holder_after_takeover"] = str(exc)
        else:
            raise AssertionError("the old holder committed after the takeover")
        assert canonical(sorted(store.data.items(), key=str)) == committed, "the old holder changed the store"
        before = len(rows())
        second = other.run(takeover)[ctx.chan]
        rec["new_holder_pass"] = {key: second[key] for key in ("ended", "events", "inserted", "sunk")}
        assert len(rows()) == before and second["inserted"] == 0, "the dedup of the inbox did not hold"


def step_hardening(ctx, rec):
    fmt = ("{{.Name}}|{{.HostConfig.Privileged}}|{{.HostConfig.NetworkMode}}|{{json .HostConfig.PortBindings}}"
           "|{{json .HostConfig.CapAdd}}|{{json .Mounts}}")
    containers = ctx.compose("ps", "-a", "-q", timeout=60).stdout.split()
    assert len(containers) >= 4, f"only {len(containers)} containers of the stack"
    published = {}
    for cid in containers:
        name, privileged, mode, ports, cap_add, mounts = ctx.docker(["inspect", "--format", fmt, cid],
                                                                     30).stdout.strip().split("|", 5)
        bindings = json.loads(ports) or {}
        host_ips = sorted({b["HostIp"] for binds in bindings.values() for b in binds or []})
        published[name.lstrip("/")] = {"privileged": privileged, "network_mode": mode, "host_ips": host_ips,
                                       "cap_add": json.loads(cap_add), "binding_count": len(bindings)}
        assert privileged == "false", f"{name} runs privileged"
        assert mode != "host", f"{name} uses the host network"
        assert not json.loads(cap_add), f"{name} adds capabilities"
        assert "docker.sock" not in mounts, f"{name} mounts the docker socket"
        assert set(host_ips) <= {"127.0.0.1"}, f"{name} publishes on {host_ips}"
    rec["containers"] = published
    relay = next(value for key, value in published.items() if "relay" in key)
    assert relay["host_ips"] == ["127.0.0.1"], "the relay publishes no loopback port"


def step_cleanup(ctx, rec):
    try:
        ctx.compose("unpause", "postgres", timeout=60, ok=(0, 1))  # best effort: a paused container blocks rm
    except AssertionError:
        pass
    ctx.compose("down", "-v", "--remove-orphans", timeout=300)
    residue = {
        "containers": ctx.docker(["ps", "-a", "-q", "--filter", LABEL], 60).stdout.split(),
        "networks": ctx.docker(["network", "ls", "-q", "--filter", LABEL], 60).stdout.split(),
        "volumes": ctx.docker(["volume", "ls", "-q", "--filter", LABEL], 60).stdout.split(),
    }
    rec["residue_after"] = {key: len(value) for key, value in residue.items()}
    assert not any(residue.values()), f"resources remain after down -v: {rec['residue_after']}"


# -- the matrix ------------------------------------------------------------------------------------------------

def test_buzz_a4_runtime_matrix(tmp_path):
    ctx = Ctx(tmp_path)
    matrix = Matrix(ctx, tmp_path / "buzz_a4_report.json")
    try:
        matrix.step("1 preconditions", "digests pinned; docker forms admitted; no residue; free loopback port",
                    lambda rec: step_preconditions(ctx, rec), fatal=True)
        matrix.step("2 keys", "role keys and the 0600 env file; nothing printed",
                    lambda rec: step_keys(ctx, rec), fatal=True)
        matrix.step("3 up + health", "relay healthy within 180 s", lambda rec: step_up(ctx, rec), fatal=True)
        matrix.step("4 bootstrap", "owner AUTH; 9030 add conductor; 9007 private channel; 9000 add conductor",
                    lambda rec: step_bootstrap(ctx, rec), fatal=True)
        matrix.step("5 negative", "stranger -> restricted, final, not stored", lambda rec: step_negative(ctx, rec))
        b1 = matrix.step("6 B1", "same event twice -> accepted then duplicate", lambda rec: step_b1(ctx, rec))
        matrix.step("7 B2", "reconnect + since returns the event once", lambda rec: step_b2(ctx, rec), needs=b1)
        matrix.step("8 B3", "graceful restart: close 1012; reconnect + since finds the restart-window event",
                    lambda rec: step_b3(ctx, rec))
        matrix.step("9 B4", "45010 create/update/stale/resubmit; #d query returns the head",
                    lambda rec: step_b4(ctx, rec))
        matrix.step("10 B7", "slow receiver recorded; reconnect + query_all recovers every event",
                    lambda rec: step_b7(ctx, rec))
        matrix.step("11 drift window", "created_at now-1000 refused (timestamp); outbox unknown -> ids, absent",
                    lambda rec: step_drift(ctx, rec))
        matrix.step("12 EOSE-partial", "paused postgres: the InboundPass interval is gap_unknown",
                    lambda rec: step_eose_partial(ctx, rec))
        matrix.step("13 lease", "two InboundPass on one store: only the lease holder commits",
                    lambda rec: step_lease(ctx, rec))
        matrix.step("14 hardening", "no privileged, no host network, no socket, no cap_add, loopback ports only",
                    lambda rec: step_hardening(ctx, rec))
    finally:
        if ctx.owned and ctx.started:
            matrix.aborted = False
            matrix.step("15 cleanup", "down -v for this project; zero labelled containers, networks, volumes",
                        lambda rec: step_cleanup(ctx, rec))
        print(f"BUZZ_A4_REPORT={matrix.path}", flush=True)
    assert not matrix.failed, f"failed steps: {matrix.failed} (report: {matrix.path})"
