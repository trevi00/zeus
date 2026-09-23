"""Production wiring of the conductor continuation (INV-CONTINUATION-001).

Opt-in only. Nothing here runs unless the owner registered a Git-pinned policy (`zeus continuation
register`) AND the host setting `ZEUS_CONTINUATION_POLICY` names it for `zeus fleet run`, or the
owner runs one explicit `zeus continuation tick`. The policy is read through the existing
`GitSource` at an explicit commit, never from the working tree, and re-read (digest-compared) on
every tick. Every I/O here happens OUTSIDE a store transaction; the application calls these ports
between its own short transactions.

The ports it supplies:

* `lanes(lane_id)` - the lane's own store (host DSN with the lane schema as its only search path,
  the same `lane_dsn` the Fleet launcher uses) wrapped as `LaneEvidence`, with that lane's
  `WorkerSessions` owner for `record_review`.
* `runtime(lane_id)` - the identity the lane ACTUALLY runs: the host-selected isolation image, the
  packaged worker profile and the digest of the lane's session archive root. A policy naming
  anything else refuses before any effect.
* `ConductorProcesses` (adapters/continuation_process.py) - the guarded conductor dispatch: one
  hidden, DB-free per-launch guardian that owns the existing `zeus continuation conduct` as its
  tree, spawned once under the launch identity and unit token the Fleet reserved and committed
  first, polled on later ticks and never waited on inside one. Only its confirmed parent-and-tree
  cleanup receipt (or the never-entered fence) settles the Fleet unit; unknown cleanup stays held
  debt for ExecutionRecovery, never a relaunch.
* `ContinuationPass` - what `FleetRunner(continuation=...)` holds for its lifetime: the tick, the
  admission-closed `drain`, and the owned/unresolved conductor launches its heartbeat and drain
  account for. Capacity is the Fleet's shared unit reservation, not a count here.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from codex_harness.adapters.continuation_process import ConductorProcesses
from codex_harness.adapters.fleet_backlog import _parse, read_blob
from codex_harness.adapters.operation_cli import GitSource
from codex_harness.adapters.providers import packaged_policy
from codex_harness.application.continuation import Continuation, LaneEvidence
from codex_harness.application.fleet import Fleet
from codex_harness.domain.continuation import ContinuationRefused, validate_policy
from codex_harness.domain.fleet import lane_of, repository_identity
from codex_harness.domain.fleet_backlog import BacklogRefused
from codex_harness.domain.operation import WORKER_PROFILE, validate_manifest

POLICY_SETTING = "ZEUS_CONTINUATION_POLICY"
MAX_POLICY_BYTES = 64 * 1024


def archive_identity(runtime_root) -> str:
    """The digest of a lane's session archive root (`<runtime>/worker-sessions`) as it resolves."""
    return hashlib.sha256((Path(runtime_root).resolve() / "worker-sessions").as_posix().encode("utf-8")).hexdigest()


def load_policy(source, revision: str, path: str) -> dict:
    """The pinned owner policy and the identity of the exact bytes it was read from."""
    try:
        data = read_blob(source, revision, path, MAX_POLICY_BYTES, "policy")
        document = _parse(data, "policy_not_json")
    except BacklogRefused as exc:
        raise ContinuationRefused(exc.reason_code, "operator") from exc
    return {"policy": validate_policy(document),
            "pin": {"revision": revision, "path": path, "sha256": hashlib.sha256(data).hexdigest()}}


def register_policy(store, config: dict, lane_id: str, revision: str, path: str, source_factory=GitSource) -> dict:
    """Read one policy at its pin from the named lane's repository and register it (idempotent)."""
    lane = lane_of(config, lane_id)
    loaded = load_policy(source_factory(lane["repository"]), revision, path)
    policy = loaded["policy"]
    if policy["repository"] != repository_identity(lane["repository"]):
        raise ContinuationRefused("repository_foreign", "operator", "repository")
    for name in policy["lanes"]:
        try:
            if repository_identity(lane_of(config, name)["repository"]) != policy["repository"]:
                raise ContinuationRefused("repository_foreign", "operator", "lanes")
        except ContinuationRefused:
            raise
        except Exception as exc:
            raise ContinuationRefused("lane_unknown", "operator", "lanes") from exc
    return Continuation(store).register(policy, {**loaded["pin"], "lane": lane_id})


def lane_runtime(config: dict, host: dict):
    """What each lane actually runs, for the policy's qualified identity check."""
    from codex_harness.adapters.isolated_worker import load_isolation

    isolation = load_isolation(host)

    def runtime(lane_id: str) -> dict:
        lane = lane_of(config, lane_id)
        return {"image": (isolation or {}).get("image"), "profile": WORKER_PROFILE,
                "session_archive_sha256": archive_identity(lane["runtime"])}
    return runtime


def lane_stores(config: dict, host: dict, store_factory=None):
    """`lane_id -> LaneEvidence` over the lane's own schema, cached per process."""
    from codex_harness.adapters.fleet_runtime import lane_dsn
    from codex_harness.adapters.worker_sessions import SessionArchives
    from codex_harness.application.worker_sessions import WorkerSessions

    if store_factory is None:
        from codex_harness.adapters.store import PostgresStore
        store_factory = PostgresStore
    cache: dict = {}

    def lanes(lane_id: str) -> LaneEvidence:
        if lane_id not in cache:
            lane = lane_of(config, lane_id)
            store = store_factory(lane_dsn(host.get("HARNESS_DATABASE_URL"), lane["schema"]))
            cache[lane_id] = LaneEvidence(store, WorkerSessions(
                store, SessionArchives(Path(lane["runtime"]) / "worker-sessions")))
        return cache[lane_id]
    return lanes


def validator():
    policy = packaged_policy()
    return lambda manifest: validate_manifest(manifest, policy)


def coordinator(store, config: dict, host: dict, *, lanes=None, conductor=None, observer=None) -> Continuation:
    return Continuation(store, Fleet(store), lanes or lane_stores(config, host),
                        conductor if conductor is not None else ConductorProcesses(config, host),
                        validate=validator(), observer=observer)


def tick_policy(store, config: dict, host: dict, policy_id: str, *, source_factory=GitSource, lanes=None,
                conductor=None, runtime=None, observer=None) -> dict:
    """One bounded tick. An unregistered or disabled policy returns before any Git read, lane
    connection or process; the registered pin is re-read so a changed policy refuses. A pin that
    cannot be re-read refuses every NEW effect, while launches already started are still drained."""
    owner = coordinator(store, config, host, lanes=lanes, conductor=conductor, observer=observer)
    row = owner.policy(policy_id)
    if row is None or not row["policy"]["enabled"]:
        return owner.tick(policy_id)
    pin = row["pin"]
    try:
        loaded = load_policy(source_factory(lane_of(config, pin["lane"])["repository"]), pin["revision"], pin["path"])
        sha = loaded["pin"]["sha256"]
    except Exception as exc:
        drained = owner.drain(policy_id)
        return {"schema": "urn:zeus:continuation-tick:1", "policy_id": policy_id, "outcome": "refused",
                "reason_code": "policy_unavailable", "error_type": type(exc).__name__, "actions": drained["actions"],
                "skipped": drained["skipped"], "next_owner": "operator"}
    return owner.tick(policy_id, pin_sha256=sha, runtime=runtime or lane_runtime(config, host))


class ContinuationPass:
    """The runner-lifetime continuation: one `ConductorProcesses` (so owned child handles survive
    across ticks) and one lane-store cache. Calling it is one tick; `drain()` settles only launches
    already started (admission closed); `owned()` and `unresolved()` are what the Fleet heartbeat,
    drain and concurrency slot count - never reported as idle while a conductor is pending."""

    def __init__(self, store, config: dict, host: dict, policy_id: str, *, observer=None, processes=None,
                 lanes=None, runtime=None, source_factory=GitSource):
        self.store, self.config, self.host, self.policy_id = store, config, host, policy_id
        self.observer, self.runtime, self.source_factory = observer, runtime, source_factory
        self.processes = processes if processes is not None else ConductorProcesses(config, host)
        self.lanes = lanes or lane_stores(config, host)

    def __call__(self) -> dict:
        return tick_policy(self.store, self.config, self.host, self.policy_id, source_factory=self.source_factory,
                           lanes=self.lanes, conductor=self.processes, runtime=self.runtime, observer=self.observer)

    def _owner(self) -> Continuation:
        return coordinator(self.store, self.config, self.host, lanes=self.lanes, conductor=self.processes,
                           observer=self.observer)

    def drain(self) -> dict:
        return self._owner().drain(self.policy_id)

    def owned(self) -> list:
        return self.processes.active()

    def unresolved(self) -> list:
        return self._owner().unresolved(self.policy_id, self.processes.active())


def continuation_ticker(store, config: dict, host: dict, policy_id: str, observer=None) -> ContinuationPass:
    """The optional `FleetRunner(..., continuation=...)` pass; disabled by default."""
    return ContinuationPass(store, config, host, policy_id, observer=observer)


def configured_policy(settings: dict) -> str | None:
    value = (settings or {}).get(POLICY_SETTING)
    return value.strip() if type(value) is str and value.strip() else None


__all__ = ["ConductorProcesses", "ContinuationPass", "POLICY_SETTING", "archive_identity", "configured_policy",
           "continuation_ticker", "coordinator", "lane_runtime", "lane_stores", "load_policy", "register_policy",
           "tick_policy"]
