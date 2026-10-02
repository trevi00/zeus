"""Composition of the Buzz bridge process: one config, the A/B use cases wired, and the single-threaded loop (Buzz DESIGN-D §2).

Layer: composition
Owns: `BridgeConfig` (the one JSON document and its refusals), `BridgeRuntime` (the tick loop, stop, bounded run,
    relay reconnect and store-failure exits) and `build_runtime` (the wiring of the existing use cases)
Does not own: any use case (`InboundPass`, `BuzzProjection`, `BuzzOutbox`, `RemoteControl`, `BridgeLease`), the relay
    protocol, the signer, the Zeus read side (the injected `world`), signal handling (entry)
Entry points: BridgeConfig.parse, BridgeConfig.from_file, BridgeRuntime.run, build_runtime
Contracts: INV-OBSERVATION-001, INV-EXECUTION-IDENTITY-001 (Buzz DESIGN §6.4-§6.5; DESIGN-D §2)

One process, one relay connection, no threads: the relay client is sync and not thread-safe, and every inbound step
is a pass-based reconciliation, not a live subscription. A tick is lease, inbound pass, projection plan, outbox
delivery, housekeeping, then a sliced wait. The stop flag is read between steps and in the wait slices, so the stop
latency is at most `recv_timeout` plus one step. The lease is never released on exit: the next start acquires a new
generation and a stale instance commits nothing (every use-case transaction re-reads the generation). The owner id
is unique per process because `BridgeLease.acquire` advances the generation even for the same owner id.

Exit codes: 0 stop requested or `max_seconds` reached after the current tick; 3 the relay's close code allows no
reconnect; 4 a `restricted:` answer (configuration, final); 5 `store_fail_limit` consecutive failing ticks.

The store DSN is read from a 0600 file and is never logged. A tick log line (JSON on stdout) carries counts only: no
event content, key or DSN, and a failing step is named by its exception class alone.
"""
from __future__ import annotations

import json
import os
import re
import socket
import stat
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from codex_harness.coordination.application.bridge_lease import LOST, BridgeLease
from codex_harness.coordination.application.remote_control import RemoteControl
from codex_harness.coordination.application.remote_inbox import RemoteInbox
from codex_harness.credentials.adapters.role_keys import TestRoleKeys
from codex_harness.kernel.errors import ContractError, require
from codex_harness.observation.adapters.buzz_relay import BuzzRelayClient, reconnect_delay
from codex_harness.observation.adapters.event_signer import NostrEventSigner
from codex_harness.observation.adapters.nostr_verify import verify_event
from codex_harness.observation.application.buzz_inbound import InboundPass
from codex_harness.observation.application.buzz_outbox import BuzzOutbox
from codex_harness.observation.application.buzz_projection import BuzzProjection
from codex_harness.routing.adapters.organization_source import packaged_organization
from codex_harness.routing.domain.organization import Agent, Organization

EXIT_OK, EXIT_NO_RECONNECT, EXIT_RESTRICTED, EXIT_STORE = 0, 3, 4, 5
SLICE_SECONDS = 0.5
COMPACT_EVERY_SECONDS = 3600
SIGNING_ROLE = "conductor"  # the outbox's role, as the B tests wire it
AUTH_ROLE = "bridge"  # the NIP-42 identity, as the A2 tests wire it
_REQUIRED = ("relay_url", "channels", "owners", "custody_dir", "store_dsn_file", "commander_channel", "org_d",
             "team_channels")
_OPTIONAL = {"tick_seconds": 5, "lease_ttl_seconds": 30, "recv_timeout": 10, "max_seconds": 900, "recover_every": 12,
             "store_fail_limit": 12, "max_size": 1 << 20}
_STRINGS = ("relay_url", "custody_dir", "store_dsn_file", "commander_channel", "org_d")
_HEX64 = frozenset("0123456789abcdef")
_CUSTODY_LEGAL = re.compile(r"[a-z0-9_-]+")
CUSTODY_ESCAPE = "x-"
_last_owner_ns = 0


def custody_name(role_id: str) -> str:
    """The key-custody name of an organization role id (injective; `TestRoleKeys` accepts only `[a-z0-9_-]`).

    A legal id is its own name (so `conductor` keeps the bridge's signing key the client pins); any other id (the
    packaged `lead:frontdesk`) becomes `x-` plus the hex of its UTF-8 bytes. A legal id that starts with `x-` is
    refused, so an escaped name can never equal a legal one: the mapping is injective. The D2 runner creates keys
    with the same names."""
    require(isinstance(role_id, str) and bool(role_id), "buzz bridge: a role id is a non-empty string")
    if _CUSTODY_LEGAL.fullmatch(role_id):
        require(not role_id.startswith(CUSTODY_ESCAPE),
                f"buzz bridge: role id {role_id!r} collides with the custody escape prefix {CUSTODY_ESCAPE!r}")
        return role_id
    return CUSTODY_ESCAPE + role_id.encode("utf-8").hex()


def _number(document: dict, key: str, low: float, high: float | None = None) -> float:
    value = document.get(key, _OPTIONAL[key])
    require(isinstance(value, (int, float)) and not isinstance(value, bool) and value >= low
            and (high is None or value <= high), f"buzz bridge config: {key} is out of range")
    return value


def _whole(document: dict, key: str, low: int) -> int:
    value = document.get(key, _OPTIONAL[key])
    require(isinstance(value, int) and not isinstance(value, bool) and value >= low,
            f"buzz bridge config: {key} is an integer of at least {low}")
    return value


@dataclass(frozen=True)
class BridgeConfig:
    relay_url: str
    channels: tuple
    owners: tuple
    custody_dir: str
    store_dsn_file: str
    commander_channel: str
    org_d: str
    team_channels: dict
    organization_file: str | None = None
    tick_seconds: float = 5
    lease_ttl_seconds: float = 30
    recv_timeout: float = 10
    max_seconds: float = 900
    recover_every: int = 12
    store_fail_limit: int = 12
    max_size: int = 1 << 20

    @classmethod
    def parse(cls, document: dict) -> BridgeConfig:
        """The config, or `ContractError`: an unknown or missing key, a bad value, a ttl not above three ticks."""
        require(isinstance(document, dict), "buzz bridge config: a JSON object is required")
        unknown = sorted(set(document) - set(_REQUIRED) - set(_OPTIONAL) - {"organization_file"})
        require(not unknown, f"buzz bridge config: unknown keys {unknown}")
        missing = [key for key in _REQUIRED if key not in document]
        require(not missing, f"buzz bridge config: missing keys {missing}")
        for key in _STRINGS:
            require(isinstance(document[key], str) and document[key], f"buzz bridge config: {key} is a non-empty string")
        teams = document["team_channels"]
        require(isinstance(teams, dict) and teams and all(isinstance(team, str) and team and isinstance(channel, str)
                                                          and channel for team, channel in teams.items()),
                "buzz bridge config: team_channels is a non-empty {team: channel} object of strings")
        organization_file = document.get("organization_file")
        require(organization_file is None or (isinstance(organization_file, str) and organization_file),
                "buzz bridge config: organization_file is a non-empty string")
        for key in ("channels", "owners"):
            require(isinstance(document[key], list) and document[key]
                    and all(isinstance(item, str) and item for item in document[key]),
                    f"buzz bridge config: {key} is a non-empty list of strings")
        for index, owner in enumerate(document["owners"]):
            require(len(owner) == 64 and set(owner) <= _HEX64,
                    f"buzz bridge config: owners[{index}] is not 64 lowercase hex characters (length {len(owner)})")
        unbound = sorted({document["commander_channel"], *teams.values()} - set(document["channels"]))
        require(not unbound, f"buzz bridge config: channels must include the commander and every team channel {unbound}")
        tick = _number(document, "tick_seconds", 1, 60)
        ttl = _number(document, "lease_ttl_seconds", 0)
        require(ttl > 3 * tick, "buzz bridge config: lease_ttl_seconds must exceed three ticks")
        config = cls(document["relay_url"], tuple(document["channels"]), tuple(document["owners"]),
                     document["custody_dir"], document["store_dsn_file"], document["commander_channel"],
                     document["org_d"], dict(teams), organization_file, tick, ttl,
                     _number(document, "recv_timeout", 0.001), _number(document, "max_seconds", 0),
                     _whole(document, "recover_every", 1), _whole(document, "store_fail_limit", 1),
                     _whole(document, "max_size", 1))
        config.load_organization()  # an unreadable or invalid organization file is refused with the config
        return config

    @classmethod
    def from_file(cls, path: str | os.PathLike) -> BridgeConfig:
        try:
            document = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ContractError(f"buzz bridge config: {type(exc).__name__} reading the config file") from None
        return cls.parse(document)

    def load_organization(self) -> Organization:
        """The validated organization: `organization_file` (the packaged document's shape) or the packaged one."""
        if self.organization_file is None:
            return packaged_organization()
        try:
            data = json.loads(Path(self.organization_file).read_text(encoding="utf-8"))
            organization = Organization({a["id"]: Agent(**a) for a in data["agents"]})
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            raise ContractError(f"buzz bridge config: {type(exc).__name__} reading organization_file") from None
        organization.validate()
        return organization

    def read_dsn(self) -> str:
        """The store DSN from its 0600 file (never from argv or the config text)."""
        path = Path(self.store_dsn_file)
        try:
            mode = stat.S_IMODE(path.stat().st_mode)
            text = path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise ContractError(f"buzz bridge config: {type(exc).__name__} reading store_dsn_file") from None
        require(mode & 0o077 == 0, "buzz bridge config: store_dsn_file must not be group or world accessible")
        require(bool(text), "buzz bridge config: store_dsn_file is empty")
        return text


def new_owner_id() -> str:
    """`<hostname>:<pid>:<start epoch ns>`, unique per process and per call."""
    global _last_owner_ns
    _last_owner_ns = max(time.time_ns(), _last_owner_ns + 1)
    return f"{socket.gethostname()}:{os.getpid()}:{_last_owner_ns}"


@dataclass(frozen=True)
class ZeusWorld:
    """The Zeus read side the use cases need from a store (not part of the config).

    `messages` is RemoteControl's message port, `fleet_pause` its pause port, `read_models` the projection's
    `ZeusReadModels`, `channels` the projection's `{"commander", "org_d", "teams"}` map and `roles` the org role ids
    (each needs a key in the custody directory).
    """

    messages: object
    fleet_pause: object
    read_models: object
    channels: dict
    roles: tuple = ()


@dataclass
class _Tick:
    number: int
    generation: object = "passive"
    steps: dict = None
    exit_code: int | None = None

    def line(self, seconds: float) -> str:
        document = {"tick": self.number, "generation": self.generation, "steps": self.steps,
                    "seconds": round(seconds, 3)}
        if self.exit_code is not None:
            document["exit"] = self.exit_code
        return json.dumps(document, sort_keys=True)


class BridgeRuntime:
    def __init__(self, config: BridgeConfig, *, store, relay, inbound, projection, outbox, lease=None,
                 clock: Callable[[], float] = time.time, monotonic: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep, owner_id: str | None = None,
                 out: Callable[[str], object] | None = None):
        self.config, self.store, self.relay = config, store, relay
        self.inbound, self.projection, self.outbox = inbound, projection, outbox
        self.lease = lease or BridgeLease()
        self.clock, self.monotonic, self.sleep = clock, monotonic, sleep
        self.owner_id = owner_id or new_owner_id()
        self._compacted_at: float | None = None
        self.out = out or (lambda text: print(text, file=sys.stdout, flush=True))

    # -- the loop -----------------------------------------------------------------------------------------

    def run(self, stop: Callable[[], bool]) -> int:
        started = self.monotonic()
        generation, number, failures, attempt = None, 0, 0, 0
        try:
            while not stop():
                number += 1
                began = self.monotonic()
                tick, code, lost = _Tick(number, steps={}), None, False
                try:
                    generation, code, lost = self._tick(tick, generation, stop, number)
                    failures = 0
                except ContractError as exc:
                    if str(exc) == LOST:
                        generation, failures = None, 0
                        tick.steps["lease"] = "lost"
                    else:
                        failures, code = self._failed(tick, exc, failures)
                except Exception as exc:  # noqa: BLE001 - a store or relay failure ends the tick, never the process
                    failures, code = self._failed(tick, exc, failures)
                delay = self.config.tick_seconds
                if lost and code is None:
                    delay = reconnect_delay(getattr(self.relay, "last_close_code", None), attempt)
                    attempt += 1
                    if delay is None:
                        code = EXIT_NO_RECONNECT
                elif code is None:
                    attempt = 0
                tick.exit_code = code
                self.out(tick.line(self.monotonic() - began))
                if code is not None:
                    return code
                if stop() or self.monotonic() - started >= self.config.max_seconds:
                    return EXIT_OK
                self._wait(delay, stop)
            return EXIT_OK
        finally:
            self._close_relay()

    def _failed(self, tick: _Tick, exc: Exception, failures: int) -> tuple[int, int | None]:
        failures += 1
        tick.steps["failed"] = type(exc).__name__  # the class only: a message may carry connection details
        return failures, (EXIT_STORE if failures >= self.config.store_fail_limit else None)

    def _tick(self, tick: _Tick, generation, stop, number: int):
        """One tick: `(generation, exit code or None, relay connection lost)`."""
        generation = self._lease(generation)
        if generation is None:
            tick.steps["lease"] = "held_by_other"
            return None, None, False
        tick.generation = generation
        if stop():
            return generation, None, False
        report = self.inbound.run(generation)
        tick.steps["inbound"] = _inbound_counts(report)
        ended = {result["ended"] for result in report.values()}
        if "closed:restricted" in ended:  # DESIGN-D §2: configuration, final, no retry storm
            return generation, EXIT_RESTRICTED, False
        if "connection_closed" in ended:
            return generation, None, True  # the caller paces the reconnect from the relay's close code
        if stop():
            return generation, None, False
        self.projection.use_generation(generation)
        tick.steps["plan"] = self.projection.plan(generation)
        if stop():
            return generation, None, False
        tick.steps["deliver"] = self.outbox.deliver(generation)
        if stop():
            return generation, None, False
        self._housekeeping(tick, generation, number)
        return generation, None, False

    def _lease(self, generation):
        now, ttl = self.clock(), self.config.lease_ttl_seconds
        with self.store.transaction() as tx:
            if generation is None:
                return self.lease.acquire(tx, self.owner_id, now, ttl)
            self.lease.renew(tx, self.owner_id, generation, now, ttl)
            return generation

    def _housekeeping(self, tick: _Tick, generation: int, number: int) -> None:
        if number % self.config.recover_every == 0:
            tick.steps["recover"] = self.outbox.recover_deferred(generation, self.projection.regenerate)
        if self._compacted_at is None or self.monotonic() - self._compacted_at >= COMPACT_EVERY_SECONDS:
            tick.steps["compact"] = self.inbound.compact(generation)  # first active tick, then hourly
            self._compacted_at = self.monotonic()

    def _wait(self, seconds: float, stop: Callable[[], bool]) -> None:
        """Sleep `seconds` in slices of at most 0.5 s, returning as soon as `stop` is set."""
        deadline = self.monotonic() + seconds
        while not stop():
            left = deadline - self.monotonic()
            if left <= 0:
                return
            self.sleep(min(SLICE_SECONDS, left))

    def _close_relay(self) -> None:
        close = getattr(self.relay, "close", None)
        if close is not None:
            try:
                close()
            except Exception:  # noqa: BLE001 - exiting; closing is best effort
                pass


def _inbound_counts(report: dict) -> dict:
    totals = dict.fromkeys(("events", "inserted", "sunk", "sink_failed"), 0)
    for result in report.values():
        for key in totals:
            totals[key] += result.get(key, 0)
    return {"channels": len(report), **totals, "ended": sorted({result["ended"] for result in report.values()})}


def default_relay(config: BridgeConfig, signer) -> BuzzRelayClient:
    class _Verifier:
        def verify(self, event):
            return verify_event(event)

    return BuzzRelayClient(config.relay_url, auth_signer=signer, auth_role=AUTH_ROLE, verifier=_Verifier(),
                           max_size=config.max_size, recv_timeout=config.recv_timeout)


def default_store(dsn: str):
    from codex_harness.storage.adapters.postgres_store import PostgresStore
    return PostgresStore(dsn)


def build_runtime(config: BridgeConfig, *, world_factory: Callable[[object], ZeusWorld],
                  store_factory: Callable[[str], object] = default_store,
                  relay_factory: Callable[[BridgeConfig, object], object] = default_relay,
                  clock: Callable[[], float] = time.time, monotonic: Callable[[], float] = time.monotonic,
                  sleep: Callable[[float], None] = time.sleep, out: Callable[[str], object] | None = None,
                  owner_id: str | None = None) -> BridgeRuntime:
    """Wire the use cases as the B tests do (`test_buzz_b_pg`, `test_buzz_b4_projection`); the Zeus read side comes
    from `world_factory(store)`."""
    store = store_factory(config.read_dsn())
    world = world_factory(store)
    keys = TestRoleKeys(config.custody_dir)
    signer = NostrEventSigner(lambda role: keys.pubkey(custody_name(role)),
                              lambda role, event_id: keys.sign_id(custody_name(role), event_id))
    relay = relay_factory(config, signer)
    lease = BridgeLease()
    projection_box = []
    outbox = BuzzOutbox(store, relay, signer, lease, clock, role=SIGNING_ROLE,
                        replan=lambda subject: projection_box[0].replan(subject))
    pubkeys = {name: keys.pubkey(custody_name(name)) for name in dict.fromkeys((SIGNING_ROLE, *world.roles))}
    projection = BuzzProjection(store, outbox, world.read_models, relay, pubkeys, world.channels, clock)
    projection_box.append(projection)
    remote = RemoteControl(store, world.messages, world.fleet_pause, lease, config.owners, clock)
    inbound = InboundPass(store, relay, RemoteInbox(), lease, lambda row, generation: remote.admit(row, generation)["outcome"],
                          config.owners, config.channels, clock)
    return BridgeRuntime(config, store=store, relay=relay, inbound=inbound, projection=projection, outbox=outbox,
                         lease=lease, clock=clock, monotonic=monotonic, sleep=sleep, owner_id=owner_id, out=out)
