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
* `LaneConductor` - the guarded conductor dispatch: the existing `zeus continuation conduct` in the
  lane environment as a child process, exactly as the Fleet launches `zeus operate run`. Its
  timeout or a lost child is an UNKNOWN effect for ExecutionRecovery, never a relaunch.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

from codex_harness.adapters.commands import no_console_kwargs
from codex_harness.adapters.fleet_backlog import _parse, read_blob
from codex_harness.adapters.operation_cli import GitSource
from codex_harness.adapters.providers import packaged_policy
from codex_harness.application.continuation import Continuation, LaneEvidence
from codex_harness.application.fleet import Fleet
from codex_harness.domain.continuation import ContinuationRefused, validate_policy
from codex_harness.domain.fleet import lane_of, repository_identity
from codex_harness.domain.fleet_backlog import BacklogRefused
from codex_harness.domain.operation import WORKER_PROFILE, validate_manifest
from codex_harness.domain.policy import POLICY

POLICY_SETTING = "ZEUS_CONTINUATION_POLICY"
MAX_POLICY_BYTES = 64 * 1024
DEFAULT_ARGV = (sys.executable, "-m", "codex_harness.cli")
# The conductor child is one Codex decision; its wall-clock bound is the decision allowance plus a
# fixed margin for process start and store I/O, never an extension of the decision itself.
CONDUCT_MARGIN_SECONDS = 120


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


class LaneConductor:
    """`(lane_id, job) -> outcome`: the guarded conductor decision in the lane environment."""

    def __init__(self, config: dict, host: dict, *, argv=DEFAULT_ARGV, run=subprocess.run):
        self.config, self.host, self.argv, self.run = config, host, tuple(argv), run

    def __call__(self, lane_id: str, job: dict) -> dict:
        from codex_harness.adapters.fleet_runtime import lane_environment

        lane = lane_of(self.config, lane_id)
        env = lane_environment(lane, self.host)
        directory = Path(lane["runtime"]) / "continuation"
        directory.mkdir(parents=True, exist_ok=True)
        manifest = directory / (job["id"] + ".manifest.json")
        body = json.dumps(job["manifest"], sort_keys=True)
        if not manifest.exists() or manifest.read_text(encoding="utf-8") != body:
            manifest.write_text(body, encoding="utf-8")
        argv = [*self.argv, "--repository", lane["repository"], "continuation", "conduct", "--file", str(manifest)]
        with (directory / (job["id"] + ".conduct.log")).open("ab") as log:
            # A timeout raises: the controller records an unknown effect and never relaunches it.
            completed = self.run(argv, env=env, stdout=log, stderr=subprocess.STDOUT,
                                 timeout=POLICY.decision_seconds + CONDUCT_MARGIN_SECONDS, **no_console_kwargs())
        return {"exit_code": completed.returncode}


def validator():
    policy = packaged_policy()
    return lambda manifest: validate_manifest(manifest, policy)


def coordinator(store, config: dict, host: dict, *, lanes=None, conductor=None, observer=None) -> Continuation:
    return Continuation(store, Fleet(store), lanes or lane_stores(config, host),
                        conductor if conductor is not None else LaneConductor(config, host),
                        validate=validator(), observer=observer)


def tick_policy(store, config: dict, host: dict, policy_id: str, *, source_factory=GitSource, lanes=None,
                conductor=None, runtime=None, observer=None) -> dict:
    """One bounded tick. An unregistered or disabled policy returns before any Git read, lane
    connection or process; the registered pin is re-read so a changed policy refuses."""
    owner = coordinator(store, config, host, lanes=lanes, conductor=conductor, observer=observer)
    row = owner.policy(policy_id)
    if row is None or not row["policy"]["enabled"]:
        return owner.tick(policy_id)
    pin = row["pin"]
    try:
        loaded = load_policy(source_factory(lane_of(config, pin["lane"])["repository"]), pin["revision"], pin["path"])
        sha = loaded["pin"]["sha256"]
    except Exception as exc:
        return {"schema": "urn:zeus:continuation-tick:1", "policy_id": policy_id, "outcome": "refused",
                "reason_code": "policy_unavailable", "error_type": type(exc).__name__, "actions": [],
                "skipped": [], "next_owner": "operator"}
    return owner.tick(policy_id, pin_sha256=sha, runtime=runtime or lane_runtime(config, host))


def continuation_ticker(store, config: dict, host: dict, policy_id: str, observer=None):
    """The optional per-pass callable for `FleetRunner(..., continuation=...)`; disabled by default."""
    return lambda: tick_policy(store, config, host, policy_id, observer=observer)


def configured_policy(settings: dict) -> str | None:
    value = (settings or {}).get(POLICY_SETTING)
    return value.strip() if type(value) is str and value.strip() else None


__all__ = ["LaneConductor", "POLICY_SETTING", "archive_identity", "configured_policy", "continuation_ticker",
           "coordinator", "lane_runtime", "lane_stores", "load_policy", "register_policy", "tick_policy"]
