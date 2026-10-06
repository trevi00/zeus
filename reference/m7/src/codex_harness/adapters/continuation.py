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
* `evidence` - `ResearchEvidence` over the control host's configured artifact store
  (`<HARNESS_RUNTIME_DIR>/artifacts`): the actual bounded bytes and digest of every research receipt
  evidence ref, at `research-accept` AND on each tick before a receipt releases a hold.
* `ConductorProcesses` (adapters/continuation_process.py) - the guarded conductor dispatch: one
  hidden, DB-free per-launch guardian that owns the existing `zeus continuation conduct` as its
  tree, spawned once under the launch identity and unit token the Fleet reserved and committed
  first, polled on later ticks and never waited on inside one. Only its confirmed parent-and-tree
  cleanup receipt (or the never-entered fence) settles the Fleet unit; unknown cleanup stays held
  debt for ExecutionRecovery, never a relaunch.
* `ContinuationPass` - what `FleetRunner(continuation=...)` holds for its lifetime: the tick, the
  admission-closed `drain`, the DB-free `request_stop` a graceful stop forwards to its guardians,
  and the owned/unresolved conductor launches its heartbeat and drain account for. Capacity is the Fleet's shared unit reservation, not a count here.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from codex_harness.adapters.artifacts import FileArtifacts
from codex_harness.adapters.continuation_process import ConductorProcesses
from codex_harness.adapters.fleet_backlog import _parse, read_blob
from codex_harness.adapters.operation_cli import GitSource
from codex_harness.adapters.providers import packaged_policy
from codex_harness.application.continuation import Continuation, LaneEvidence
from codex_harness.application.fleet import Fleet
from codex_harness.domain.continuation import (
    RESEARCH,
    ROUTE_OWNERS,
    ContinuationRefused,
    validate_policy,
)
from codex_harness.domain.fleet import lane_of, repository_identity
from codex_harness.domain.fleet_backlog import BacklogRefused
from codex_harness.domain.model import ContractError
from codex_harness.domain.operation import WORKER_PROFILE, validate_manifest

POLICY_SETTING = "ZEUS_CONTINUATION_POLICY"
MAX_POLICY_BYTES = 64 * 1024
MAX_RESEARCH_EVIDENCE_BYTES = 1024 * 1024  # the FileArtifacts.text ceiling


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


def read_receipt(path) -> dict:
    """The owner's research receipt file: bounded, JSON, validated by the domain afterwards."""
    try:
        data = Path(path).read_bytes()
    except OSError as exc:
        raise ContinuationRefused("research_receipt_unreadable", "operator", "file") from exc
    if len(data) > MAX_POLICY_BYTES:
        raise ContinuationRefused("research_receipt_invalid", "operator", "file")
    try:
        return json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ContinuationRefused("research_receipt_invalid", "operator", "file") from exc


class ResearchEvidence:
    """The research evidence port over ONE trusted content-addressed store (`FileArtifacts`): `verify`
    reads at most `max_bytes` of the reference's actual bytes and checks their SHA-256. Refusals are
    fixed codes (`research_evidence_missing|unreadable|oversized|corrupt|invalid`); no path, raw error
    or content leaves. The root is fixed by configuration; it is never created, searched or
    supplied by a caller, and nothing is fetched. Integrity holds at the observed read only."""

    def __init__(self, root, max_bytes: int = MAX_RESEARCH_EVIDENCE_BYTES):
        self.root, self.max_bytes, self.store = Path(root), max_bytes, None

    def verify(self, reference) -> None:
        code = None
        try:
            if self.store is None:
                if not self.root.is_dir():
                    raise FileNotFoundError
                self.store = FileArtifacts(str(self.root))
            self.store.text(reference, self.max_bytes)
        except FileNotFoundError:
            code = "research_evidence_missing"
        except UnicodeDecodeError:
            code = "research_evidence_invalid"  # digest matched, but not the text the store writes
        except OSError:
            code = "research_evidence_unreadable"
        except ContractError as exc:
            code = {"Artifact exceeds text budget": "research_evidence_oversized",
                    "Artifact modified": "research_evidence_corrupt"}.get(str(exc), "research_evidence_invalid")
        if code is not None:
            raise ContinuationRefused(code, ROUTE_OWNERS[RESEARCH], "evidence_refs")


def research_evidence() -> ResearchEvidence:
    """The configured owner of research receipt evidence: the control host's general artifact store
    (`<HARNESS_RUNTIME_DIR>/artifacts`), where the research council and the executor write."""
    from codex_harness.adapters.configuration import runtime_dir
    return ResearchEvidence(runtime_dir() / "artifacts")


def accept_research(store, config: dict, host: dict, document, *, lanes=None, evidence=None) -> dict:
    """The owner's explicit scoped research receipt, verified against the Fleet control store, each
    attempt's own lane store and the actual evidence bytes, then stored once
    (`Continuation.accept_research`)."""
    return Continuation(store, lanes=lanes or lane_stores(config, host),
                        evidence=evidence or research_evidence()).accept_research(document)


def supplement_research(store, config: dict, host: dict, document, *, lanes=None, evidence=None) -> dict:
    """The owner's typed research scope supplement, verified against the same control-store rows,
    lane stores and trusted evidence bytes as a receipt, then stored once
    (`Continuation.supplement_research_scope`). It releases nothing by itself."""
    return Continuation(store, lanes=lanes or lane_stores(config, host),
                        evidence=evidence or research_evidence()).supplement_research_scope(document)


def read_grant(path) -> dict:
    """The owner's capacity grant file, read under the same bounds as a receipt file."""
    try:
        return read_receipt(path)
    except ContinuationRefused as exc:
        raise ContinuationRefused(exc.reason_code.replace("research_receipt", "capacity_grant", 1), "operator",
                                  "file") from None


def grant_capacity(store, config: dict, host: dict, document, *, lanes=None, evidence=None, runtime=None,
                   source_factory=GitSource) -> dict:
    """The owner's one-use evidence-repair capacity grant (`Continuation.grant_capacity`), verified
    against the registered pin re-read through Git now, the lanes' actual runtime identity, the lane
    stores and the trusted evidence bytes. It starts nothing: the next tick admits the successor."""
    owner = Continuation(store, lanes=lanes or lane_stores(config, host), validate=validator(),
                         evidence=evidence or research_evidence())
    row = owner.policy(document.get("policy_id")) if isinstance(document, dict) and type(
        document.get("policy_id")) is str else None
    sha = None
    if row is not None:
        pin = row["pin"]
        try:
            sha = load_policy(source_factory(lane_of(config, pin["lane"])["repository"]), pin["revision"],
                              pin["path"])["pin"]["sha256"]
        except Exception as exc:
            raise ContinuationRefused("policy_unavailable", "operator", "pin") from exc
    return owner.grant_capacity(document, pin_sha256=sha, runtime=runtime or lane_runtime(config, host))


def read_requalification(path) -> dict:
    """The owner's delivery requalification file, read under the same bounds as a receipt file."""
    try:
        return read_receipt(path)
    except ContinuationRefused as exc:
        raise ContinuationRefused(exc.reason_code.replace("research_receipt", "requalification", 1), "operator",
                                  "file") from None


class LaneMainline:
    """`lane_id -> port` over the lane's OWN registered repository and the host's GitHub setting (the
    same pair `host-delivery --lane` merges with): `remote_main()` is an `ls-remote` read of the remote
    main, `commit_exists` and `goal(revision, path)` (mode, SHA-256 and size of the blob) read the lane
    repository at an explicit commit. Read only: no fetch, no ref move; an owner who names a main the
    lane repository lacks fetches it first."""

    def __init__(self, config: dict, host: dict, source_factory=GitSource):
        self.config, self.host, self.source_factory = config, host, source_factory

    def __call__(self, lane_id: str):
        from types import SimpleNamespace

        from codex_harness.adapters.git import GitWorkspace

        lane = lane_of(self.config, lane_id)
        workspace = GitWorkspace(lane["repository"], str(Path(lane["runtime"]) / "workspaces"),
                                 self.host.get("HARNESS_GITHUB_REPO"))
        source = self.source_factory(lane["repository"])
        def goal(revision: str, path: str) -> dict | None:
            mode, data = source.blob(revision, path)
            return None if mode is None else {"mode": mode, "sha256": hashlib.sha256(data).hexdigest(),
                                              "bytes": len(data)}
        return SimpleNamespace(remote_main=workspace.remote_main, commit_exists=source.commit_exists, goal=goal)


def requalify_delivery(store, config: dict, host: dict, document, *, lanes=None, evidence=None, runtime=None,
                       mainline=None, source_factory=GitSource) -> dict:
    """The owner's delivery requalification (`Continuation.requalify_delivery`), verified against the
    registered pin re-read through Git now, the lanes' actual runtime identity, the lane stores (the
    withdrawn HostDelivery plan and the release record), the remote main and the lane repository, and
    the trusted rationale bytes. It starts nothing: the next tick binds and admits the successor."""
    owner = Continuation(store, lanes=lanes or lane_stores(config, host), validate=validator(),
                         evidence=evidence or research_evidence())
    row = owner.policy(document.get("policy_id")) if isinstance(document, dict) and type(
        document.get("policy_id")) is str else None
    sha = None
    if row is not None:
        pin = row["pin"]
        try:
            sha = load_policy(source_factory(lane_of(config, pin["lane"])["repository"]), pin["revision"],
                              pin["path"])["pin"]["sha256"]
        except Exception as exc:
            raise ContinuationRefused("policy_unavailable", "operator", "pin") from exc
    return owner.requalify_delivery(document, pin_sha256=sha, runtime=runtime or lane_runtime(config, host),
                                    mainline=mainline or LaneMainline(config, host, source_factory))


def reconcile_ownership(store, intent_id: str) -> dict:
    """The owner's explicit present-ownership reconciliation of one admitted continuation successor
    (`Continuation.reconcile_ownership`): control-store rows only, no lane, Git or process."""
    return Continuation(store).reconcile_ownership(intent_id)


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


def coordinator(store, config: dict, host: dict, *, lanes=None, conductor=None, observer=None,
                evidence=None) -> Continuation:
    return Continuation(store, Fleet(store), lanes or lane_stores(config, host),
                        conductor if conductor is not None else ConductorProcesses(config, host),
                        validate=validator(), observer=observer, evidence=evidence or research_evidence())


def tick_policy(store, config: dict, host: dict, policy_id: str, *, source_factory=GitSource, lanes=None,
                conductor=None, runtime=None, observer=None, evidence=None) -> dict:
    """One bounded tick. An unregistered or disabled policy returns before any Git read, lane
    connection or process; the registered pin is re-read so a changed policy refuses. A pin that
    cannot be re-read refuses every NEW effect, while launches already started are still drained."""
    owner = coordinator(store, config, host, lanes=lanes, conductor=conductor, observer=observer, evidence=evidence)
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
                 lanes=None, runtime=None, source_factory=GitSource, evidence=None):
        self.store, self.config, self.host, self.policy_id = store, config, host, policy_id
        self.observer, self.runtime, self.source_factory = observer, runtime, source_factory
        self.processes = processes if processes is not None else ConductorProcesses(config, host)
        self.lanes = lanes or lane_stores(config, host)
        self.evidence = evidence or research_evidence()

    def __call__(self) -> dict:
        return tick_policy(self.store, self.config, self.host, self.policy_id, source_factory=self.source_factory,
                           lanes=self.lanes, conductor=self.processes, runtime=self.runtime, observer=self.observer,
                           evidence=self.evidence)

    def _owner(self) -> Continuation:
        return coordinator(self.store, self.config, self.host, lanes=self.lanes, conductor=self.processes,
                           observer=self.observer, evidence=self.evidence)

    def drain(self) -> dict:
        return self._owner().drain(self.policy_id)

    def request_stop(self) -> dict:
        """The runner's stop, forwarded to the guardians this pass spawned: local stop files only,
        no store, lane or Git access, so it reaches them while the store is blocked or down. It
        proves no cleanup; `drain()` settles each unit later from the guardian's own proof."""
        return self.processes.request_stop()

    def owned(self) -> list:
        return self.processes.active()

    def unresolved(self) -> list:
        return self._owner().unresolved(self.policy_id, self.processes.active())


class ContinuationPasses:
    """Several registered policies ticked in turn by the ONE Fleet runner (aibox whole-goal adjudication C2:
    disjoint families, e.g. `aibox-qualification-001` and `aibox-qualification-i1`, on one harness lane).

    One `ContinuationPass` per policy, all sharing ONE `ConductorProcesses` (so the runner's owned,
    stop and drain accounting sees every launch once; capacity stays the Fleet's shared unit reservation)
    and one lane-store cache. A policy whose tick raises is that policy's `unavailable` row and never
    stops the others; the combined outcome is `refused`/`disabled` only when EVERY policy says so, and
    the pass raises (the runner's own `unavailable`) only when every policy raised."""

    def __init__(self, store, config: dict, host: dict, policy_ids, *, observer=None, processes=None, lanes=None,
                 runtime=None, source_factory=GitSource, evidence=None):
        self.policy_ids = list(policy_ids)
        self.processes = processes if processes is not None else ConductorProcesses(config, host)
        lanes = lanes or lane_stores(config, host)
        evidence = evidence or research_evidence()
        self.passes = [ContinuationPass(store, config, host, policy_id, observer=observer, processes=self.processes,
                                        lanes=lanes, runtime=runtime, source_factory=source_factory,
                                        evidence=evidence) for policy_id in self.policy_ids]

    def _each(self, call) -> dict:
        rows, errors = [], []
        for policy_id, one in zip(self.policy_ids, self.passes):
            try:
                row = call(one)
            except Exception as exc:
                errors.append(exc)
                row = {"policy_id": policy_id, "outcome": "unavailable", "error_type": type(exc).__name__}
            rows.append(row if isinstance(row, dict) else {"policy_id": policy_id})
        if errors and len(errors) == len(rows):
            raise errors[0]
        outcomes = {row.get("outcome") for row in rows}
        if outcomes <= {"refused"} or outcomes <= {"disabled"}:
            outcome = rows[0].get("outcome")
            reason = next((row.get("reason_code") for row in rows if row.get("reason_code")), None)
        else:
            outcome = next(row.get("outcome") for row in rows if row.get("outcome") not in {"refused", "disabled",
                                                                                             "unavailable"}) \
                if outcomes - {"refused", "disabled", "unavailable"} else "partial"
            reason = None
        return {"schema": "urn:zeus:continuation-ticks:1", "outcome": outcome, "reason_code": reason,
                "actions": [action for row in rows for action in row.get("actions") or []], "policies": rows}

    def __call__(self) -> dict:
        return self._each(lambda one: one())

    def drain(self) -> dict:
        return self._each(lambda one: one.drain())

    def request_stop(self) -> dict:
        return self.processes.request_stop()

    def owned(self) -> list:
        return self.processes.active()

    def unresolved(self) -> list:
        found = []
        for one in self.passes:
            found += [launch for launch in one.unresolved() if launch not in found]
        return found


def continuation_ticker(store, config: dict, host: dict, policy_id, observer=None):
    """The optional `FleetRunner(..., continuation=...)` pass; disabled by default. One policy id (or a
    one-element list) is exactly the single `ContinuationPass` it always was; several share one pass."""
    ids = [policy_id] if isinstance(policy_id, str) else list(policy_id)
    if len(ids) == 1:
        return ContinuationPass(store, config, host, ids[0], observer=observer)
    return ContinuationPasses(store, config, host, ids, observer=observer)


POLICY_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def configured_policy(settings: dict) -> str | None:
    value = (settings or {}).get(POLICY_SETTING)
    return value.strip() if type(value) is str and value.strip() else None


def configured_policies(settings: dict) -> list | None:
    """The host setting as the policy list the ONE Fleet runner continues: absent or blank is None (no
    continuation, exactly as before); a single value is `[that value]` unchanged; a comma-separated list
    must name each registered-policy token once, and anything else refuses before any pass is built."""
    value = configured_policy(settings)
    if value is None:
        return None
    if "," not in value:
        return [value]
    ids = [part.strip() for part in value.split(",")]
    if not all(POLICY_ID.fullmatch(part) for part in ids):
        raise ContinuationRefused("continuation_policy_list_invalid", "operator", POLICY_SETTING)
    if len(set(ids)) != len(ids):
        raise ContinuationRefused("continuation_policy_list_duplicate", "operator", POLICY_SETTING)
    return ids


__all__ = ["ConductorProcesses", "ContinuationPass", "ContinuationPasses", "POLICY_SETTING", "configured_policies", "ResearchEvidence", "accept_research",
           "archive_identity", "configured_policy", "continuation_ticker", "coordinator", "grant_capacity",
           "lane_runtime", "lane_stores", "load_policy", "read_grant", "read_receipt","reconcile_ownership", "register_policy", "research_evidence",
           "supplement_research", "tick_policy"]
