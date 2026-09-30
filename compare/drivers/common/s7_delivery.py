"""Shared S7 delivery doubles and builders (DESIGN-s7 §2, "Doubles and inputs"): the LABELLED test doubles of M7
`tests/test_host_delivery.py` and `tests/test_host_delivery_verification.py`, rebuilt without a file, a process, a
repository or the network, for every `delivery.*` family (`delivery.registry`, then `delivery.stages`,
`delivery.owner_commands` and `delivery.migration`).

Layer: harness (never shipped). This module never imports `codex_harness`: everything from the product arrives through
`api`, the object a reference (later a target) driver builds. Nothing here is an actual Codex, GitHub, host or
production verification.

**Doubles** (each class docstring names what it mirrors):

- `SerialStore(api)`: M7 `SerialStore`, a `MemoryStore` that refuses a nested transaction; `BrokenStore(inner)`: the
  injected store outage of M7's unavailable-store test.
- The clock: ONE timeline. `api.now()` returns an aware UTC datetime and `api.advance(seconds)` moves it; the
  controller's clock is `clock(api)` = `lambda: api.now().isoformat()`, so `HostDelivery`'s clock and the
  `datetime.now` that `Releases`/`ReleaseQueue` read are the same time. M7's tests keep two timelines (their `Clock`
  and the wall clock), which is not reproducible; one fake timeline is what makes a stage deadline, a lease and a
  backoff comparable and the golden deterministic.
- `FakeGitHub(api, ...)`: M7 `FakeGitHub` (observe, publish, merge_state, merge, qualify, the fault fields, and
  `fast_forward`).
- `MemoryHost(api, ...)`: an in-memory host target with the methods `HostDelivery` calls (`current`, `switch`,
  `receipt`, `identity`, `drain`, `running`, `start`, `launch_record`, and `stop` for cleanup), with the signatures,
  keyword arguments and return shapes of M7 `adapters/host_delivery.py` `HostTargetBase`/`ProcessHostTarget`. It calls
  `authorize` where `HostTargetBase.guard` does. Faults: `fault` = `old_runtime` | `other_image` | `no_receipt`
  (M7 test names), `miss` (M7 `LateReceiptHost`), `start_error` (raised after the start's effect), `stop_confirms`
  and `hand_edit` (a foreign descriptor on the target).
- `StartupCanary(host)` and `OwnerCanary(host)`: the result shapes of `startup_identity_canary` and
  `owner_qualified_canary`. `Verifier(api)`: the port `HostDelivery` calls on `ReleaseVerifier` (`available`,
  `reconcile`, `new_attempt`, `prepare`, `evaluate`).

**Builders** mirroring M7's: `candidate`, `successor_candidate`, `release_policy`, `reviewed_release` (through
`api.releases(store)`), `targets_document`, `plan_document`, `pin`, `build`, `drive`, plus `snapshot`, `call` and
`guarded`.

`api` supplies: `MemoryStore`, `HostDelivery(store, org, **ports)`, `organization()`, `releases(store)`,
`queue(store)`, `POLICY`, `now()`, `advance(seconds)`, `ContractError`, `MergeRefused`, `DeliveryRefused`,
`LifecycleInterrupted`, `descriptor_digest`, `receipt_identity`, `instance_authority`,
`REPLACEABLE_INSTANCES`, `INSTANCE_INTENDED`, `plan_digest`, `PLAN_SCHEMA`, `REGISTRY_SCHEMA` and the stage constants
(`ACTIVE`, `BLOCKED`, `ROLLED_BACK`, ...).
"""

from __future__ import annotations

import copy
import hashlib
import json
from contextlib import contextmanager

CANARY_TEXT = "CANARY-must-never-be-emitted"
REVISION = "a" * 40
BASE = "b" * 40
TREE = "c" * 64
MERGED_REVISION = "9" * 40
# LABELLED fixture identities: no path or image of this machine.
RUNTIME_ROOT = "/opt/zeus-fixture/runtime"
STATE_ROOT = "/var/lib/zeus-fixture"
IMAGE = "zeus-worker@sha256:" + "d" * 64
PROFILE = "e" * 64
DESCRIPTOR_REVISION = "8" * 40
REPOSITORY = "github:zeus-owner/zeus-harness"
CHECK = "ci / required"
PLAN_PATH = "docs/zeus/operations/delivery.json"
RECEIPT_SCHEMA = "urn:zeus:host-startup-receipt:1"
BUCKETS = ("host_delivery_targets", "host_delivery_plans", "host_delivery_intents", "host_delivery_descriptors",
           "host_delivery_migrations", "releases", "release_queue", "deployment_locks", "deployment", "images", "execution_fences")
BUCKET_PLANS, BUCKET_INTENTS, BUCKET_DESCRIPTORS = BUCKETS[1], BUCKETS[2], BUCKETS[3]


def canonical_digest(value) -> str:
    text = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def call(fn, *args, **kwargs):
    try:
        value = fn(*args, **kwargs)
    except Exception as exc:  # the refusal is the characterized result
        out = {"refused": type(exc).__name__, "message": str(exc)[:200]}
        for name in ("reason_code", "field"):
            if hasattr(exc, name):
                out[name] = getattr(exc, name)
        return out
    return {"value": value}


def snapshot(store, buckets=BUCKETS) -> dict:
    """A canonical digest per bucket (the S6 families' `snapshot`): the rows of each bucket, by body."""
    with store.transaction() as tx:
        return {bucket: canonical_digest(tx.scan(bucket)) for bucket in buckets}


def store_digest(store) -> str:
    """One canonical digest of EVERY row of the store (bucket, id, body)."""
    with store.transaction() as tx:
        return canonical_digest([[r["bucket"], r["id"], canonical_digest(r["body"])] for r in tx.records()])


def guarded(system, fn, *args, **kwargs):
    """A call, its outcome, whether it wrote anything ANYWHERE in the store (a refusal must write nothing), and the
    digest of the whole store after it."""
    before = store_digest(system["store"])
    out = call(fn, *args, **kwargs)
    after = store_digest(system["store"])
    return {**out, "wrote": after != before, "store": after}


# ---- the store and the clock -------------------------------------------------------------------------------
class SerialStore:
    """LABELLED. M7 `tests/test_host_delivery.py::SerialStore`: a `MemoryStore` that REFUSES a transaction opened while
    another one is open (the nested case that deadlocks the PostgreSQL advisory lock)."""

    def __init__(self, api):
        self.inner, self.depth, self.transactions = api.MemoryStore(), 0, 0

    @property
    def data(self):
        return self.inner.data

    @contextmanager
    def transaction(self):
        if self.depth:
            raise AssertionError("a nested store transaction deadlocks the PG advisory lock")
        self.depth, self.transactions = self.depth + 1, self.transactions + 1
        try:
            with self.inner.transaction() as tx:
                yield tx
        finally:
            self.depth -= 1


def clock(api):
    """The controller's clock: the ONE timeline (see the module docstring)."""
    return lambda: api.now().isoformat()


class BrokenStore:
    """LABELLED. M7 `tests/test_host_delivery.py::test_an_unavailable_store_is_reported_as_an_outage...`'s injected
    outage: a store in front of another one whose `transaction` raises `ConnectionError` while `failing`."""

    def __init__(self, inner):
        self.inner, self.failing = inner, False

    @contextmanager
    def transaction(self):
        if self.failing:
            raise ConnectionError("injected: store unavailable")  # labelled injected store outage
        with self.inner.transaction() as tx:
            yield tx


# ---- the GitHub port ---------------------------------------------------------------------------------------
class FakeGitHub:
    """LABELLED in-test double for the GitHub port (M7 `tests/test_host_delivery.py::FakeGitHub`, unchanged in
    behaviour): it records what was asked and can be told to fail AFTER its effect (the lost-response case); it never
    runs `gh`, opens a socket or touches a repository."""

    def __init__(self, api, *, checks=((CHECK, "success"),), head=None, merged_tree=TREE, fast_forward=False):
        self.api = api
        self.rows = [{"name": name, "state": state} for name, state in checks]
        self.head = head  # None: each candidate's own revision, as a real PR head would be
        self.prs = {}
        self.publishes = self.merges = self.observations = 0
        self.publish_error = self.merge_error = self.observe_error = None
        self.merged_tree, self.qualifications = merged_tree, []
        self.main, self.mainline, self.fast_forward = BASE, [], fast_forward
        self.merge_refusal = None

    def merge_state(self, candidate, observed=None):
        if self.observe_error is not None:
            raise self.observe_error  # labelled injected GitHub outage
        if candidate["revision"] in self.mainline:
            return {"state": "merged", "merged_revision": candidate["revision"], "main": self.main}
        if (observed or {}).get("state") == "MERGED" and (observed or {}).get("head") == candidate["revision"] \
                and (observed or {}).get("merged_revision"):
            return {"state": "merged", "merged_revision": observed["merged_revision"], "main": self.main}
        if self.main == candidate["base"]:
            return {"state": "unmerged", "merged_revision": None, "main": self.main}
        return {"state": "base_moved", "merged_revision": None, "main": self.main}

    @property
    def pr(self):
        return next(iter(self.prs.values()), None)

    @pr.setter
    def pr(self, value):
        self.prs[value["branch"]] = value

    def observe(self, candidate):
        self.observations += 1
        if self.observe_error is not None:
            raise self.observe_error  # labelled injected GitHub outage
        row = self.prs.get(candidate["branch"])
        if row is None:
            return None
        return {**row, "checks": list(self.rows)}

    def publish(self, candidate):
        self.publishes += 1
        self.prs[candidate["branch"]] = {
            "number": 181 + len(self.prs), "url": "https://example.invalid/pull/181",
            "head": self.head or candidate["revision"], "state": "OPEN",
            "merged_revision": None, "branch": candidate["branch"]}
        if self.publish_error is not None:
            raise self.publish_error  # labelled injected loss of the publish RESPONSE
        return {**self.prs[candidate["branch"]], "checks": []}

    def merge(self, candidate, observed=None):
        self.merges += 1
        if self.merge_refusal is not None:
            raise self.api.MergeRefused(self.merge_refusal)  # labelled injected definite server refusal
        if self.fast_forward:
            self.main = candidate["revision"]
            self.mainline.append(candidate["revision"])
            if self.merge_error is not None:
                raise self.merge_error  # labelled injected loss of the push RESPONSE
            return {"merged": True, "merged_revision": candidate["revision"]}
        self.prs[candidate["branch"]] = {**self.prs[candidate["branch"]], "state": "MERGED",
                                         "merged_revision": MERGED_REVISION}
        self.main = MERGED_REVISION
        if self.merge_error is not None:
            raise self.merge_error  # labelled injected loss of the merge RESPONSE
        return {"merged": True, "merged_revision": MERGED_REVISION}

    def qualify(self, candidate, merged_revision):
        self.qualifications.append(merged_revision)
        if self.merged_tree != candidate["tree"]:
            raise self.api.ContractError("Merged tree differs from reviewed candidate")
        return {"merged_revision": merged_revision, "tree": self.merged_tree}


# ---- the host target ---------------------------------------------------------------------------------------
class MemoryHost:
    """LABELLED. An in-memory stand-in for M7 `adapters/host_delivery.py` `ProcessHostTarget` (over `HostTargetBase`):
    no file, no process, no clock but `api.now()`. State is kept per `target_id`.

    The methods, keywords and return shapes are the adapter's. `authorize` runs INSIDE `guard` before any mutation
    (`switch`, `drain`, `start`) and again after the stop in `start` (`_still_owned`: a loss there is a
    `LifecycleInterrupted`, the stop having happened). `start` classifies the instance that is there through the M7 domain
    function itself (`api.instance_authority` over `observe`, the adapter's observation shape), so recognition, the
    authorized predecessor, an interrupted instance, absence and every foreign/unknown refusal are M7's; the common module
    only supplies the observation.

    `start` makes a new instance (id and pid derived from a counter, so they are reproducible) and, unless a fault
    says otherwise, the startup receipt `startup_receipt` writes for a runtime that loaded EXACTLY the descriptor.
    Faults (all LABELLED injections): `fault="old_runtime"` (the receipt reports another revision, the alive-but-old
    runtime), `fault="other_image"` (another worker image), `fault="no_receipt"` (the instance never reports);
    `miss=N` (M7 `LateReceiptHost`: the next N `receipt` reads answer None); `start_error` (an exception raised AFTER the
    start's effect: a lost response); `stop_confirms=False` (the bounded stop is not confirmed); `work` (the drain's
    `work.json` report, None for a missing report); `hand_edit(target, descriptor)` (a foreign descriptor written
    behind the delivery's back).
    """

    kind = "process"

    def __init__(self, api, *, fault=None, miss=0, start_error=None, stop_confirms=True):
        self.api = api
        self.fault, self.miss, self.start_error, self.stop_confirms = fault, miss, start_error, stop_confirms
        self.states, self.counter, self.calls = {}, 0, []

    def _st(self, target):
        return self.states.setdefault(target["target_id"], {
            "descriptor": None, "receipt": None, "launch": None, "running": False, "paused": False,
            "work": {"active": 0, "unconfirmed": 0}, "locked": False})

    @contextmanager
    def guard(self, target, authorize=None):
        state = self._st(target)
        if state["locked"]:
            raise self.api.DeliveryRefused("target_lock_held", "target_id")
        state["locked"] = True
        try:
            if authorize is not None:
                authorize()
            yield
        finally:
            state["locked"] = False

    def _still_owned(self, authorize, effect):
        if authorize is None:
            return
        try:
            authorize()
        except Exception as exc:
            raise self.api.LifecycleInterrupted(effect, exc) from exc

    def hand_edit(self, target, descriptor):
        """LABELLED fault: a descriptor written by something other than the delivery."""
        self._st(target)["descriptor"] = copy.deepcopy(descriptor)

    def current(self, target):
        self.calls.append("current")
        descriptor = self._st(target)["descriptor"]
        return copy.deepcopy(descriptor)

    def switch(self, target, descriptor, *, expected, authorize=None):
        self.calls.append("switch")
        with self.guard(target, authorize):
            current = self._st(target)["descriptor"]
            observed = None if current is None else self.api.descriptor_digest(current)
            if observed != expected:
                raise self.api.DeliveryRefused("descriptor_changed", "expected_descriptor")
            self._st(target)["descriptor"] = copy.deepcopy(descriptor)
            return {"written": True, "descriptor_sha256": self.api.descriptor_digest(descriptor)}

    def receipt(self, target):
        self.calls.append("receipt")
        if self.miss > 0:
            self.miss -= 1
            return None
        return copy.deepcopy(self._st(target)["receipt"])

    def launch_record(self, target):
        return copy.deepcopy(self._st(target)["launch"])

    def running(self, target):
        return bool(self._st(target)["running"])

    def _liveness(self, target):
        return bool(self._st(target)["running"])

    def observe(self, target):
        """`HostTargetBase.observe`: everything the target says about its instance; it mutates nothing. The receipt
        read goes through `receipt` (so a `miss` fault applies), and presence is the state, not that read."""
        state = self._st(target)
        return {"receipt": self.receipt(target), "receipt_present": state["receipt"] is not None,
                "launch": self.launch_record(target), "launch_present": state["launch"] is not None,
                "running": self._liveness(target)}

    def identity(self, target):
        self.calls.append("identity")
        observed = self.observe(target)
        named = self.api.receipt_identity(observed["receipt"], present=observed["receipt_present"])
        current = self._st(target)["descriptor"]
        return {"descriptor_sha256": None if current is None else self.api.descriptor_digest(current),
                "instance_id": named["instance_id"], "receipt": named["state"],
                "launch": observed["launch"], "running": observed["running"]}

    def drain(self, target, *, authorize=None):
        self.calls.append("drain")
        with self.guard(target, authorize):
            state = self._st(target)
            state["paused"] = True
            running, work = state["running"], state["work"]
        if not running:
            return {"drained": True, "unconfirmed": 0, "running": False, "active": 0}
        if not isinstance(work, dict):
            return {"drained": False, "unconfirmed": 1, "running": True, "active": None}
        return {"drained": work.get("active") == 0, "unconfirmed": int(work.get("unconfirmed") or 0),
                "running": True, "active": work.get("active")}

    def stop(self, target):
        self.calls.append("stop")
        state = self._st(target)
        pid = (state["launch"] or {}).get("pid")
        was = state["running"]
        if self.stop_confirms:
            state["running"] = False
        return {"stopped": not state["running"], "was_running": was, "pid": pid}

    def start(self, target, descriptor, *, authorize=None, replaces=None):
        self.calls.append("start")
        with self.guard(target, authorize):
            state = self._st(target)
            digest = self.api.descriptor_digest(descriptor)
            current = state["descriptor"]
            if current is None or self.api.descriptor_digest(current) != digest:
                raise self.api.DeliveryRefused("descriptor_foreign", "target_id")
            authority = self.api.instance_authority(descriptor, self.observe(target), replaces)
            if authority["state"] == self.api.INSTANCE_INTENDED:
                return {"started": False, "recovered": True, "instance_id": authority["instance_id"],
                        "launch": self.launch_record(target)}
            if authority["state"] not in self.api.REPLACEABLE_INSTANCES:
                raise self.api.DeliveryRefused(authority["reason_code"], "target_id")
            stopped = self.stop(target)
            if not stopped["stopped"]:
                raise self.api.DeliveryRefused("previous_instance_unconfirmed", "target_id")
            self._still_owned(authorize, "service_stopped")
            state["receipt"] = None   # retire the previous instance's evidence
            state["paused"] = False
            self.counter += 1
            instance = hashlib.sha256(("%s:%d" % (target["target_id"], self.counter)).encode()).hexdigest()[:32]
            pid = 4000 + self.counter
            started = self.api.now().isoformat()
            state["launch"] = {"pid": pid, "started_at": started, "descriptor_sha256": digest}
            state["running"] = True
            if self.fault != "no_receipt":
                state["receipt"] = self.startup_receipt(target, descriptor, instance, pid, started)
            if self.start_error is not None:
                raise self.start_error  # labelled injected loss of the start RESPONSE, after its effect
            return {"started": True, "pid": pid, "launch": copy.deepcopy(state["launch"])}

    def startup_receipt(self, target, descriptor, instance, pid, started):
        """The receipt `adapters/host_delivery.startup_receipt` writes, for a runtime that loaded the descriptor
        (or, under a labelled fault, another revision or image)."""
        return {"schema": RECEIPT_SCHEMA, "target_id": descriptor["target_id"], "instance_id": instance, "pid": pid,
                "started_at": started, "runtime_root": descriptor["root"],
                "module_root": descriptor["root"] + "/src/codex_harness",
                "descriptor_sha256": self.api.descriptor_digest(descriptor),
                "revision": "5" * 40 if self.fault == "old_runtime" else descriptor["revision"],
                "worker_image": ("zeus-worker@sha256:" + "f" * 64 if self.fault == "other_image"
                                 else descriptor["worker_image"]),
                "profile_digest": descriptor["profile_digest"]}


# ---- canaries and the verifier ------------------------------------------------------------------------------
class StartupCanary:
    """LABELLED. The result shapes of `adapters/host_delivery.startup_identity_canary` over a `MemoryHost`."""

    def __init__(self, host):
        self.host = host

    def __call__(self, target, descriptor, startup):
        receipt = self.host._st(target)["receipt"]
        if not isinstance(receipt, dict):
            return {"passed": False, "reason_code": "canary_receipt_missing", "evidence": None}
        if receipt.get("descriptor_sha256") != self.host.api.descriptor_digest(descriptor):
            return {"passed": False, "reason_code": "canary_descriptor_mismatch", "evidence": None}
        if receipt.get("instance_id") != (startup or {}).get("instance_id"):
            return {"passed": False, "reason_code": "canary_instance_changed", "evidence": None}
        if not self.host.running(target):
            return {"passed": False, "reason_code": "canary_process_absent", "evidence": None}
        return {"passed": True, "reason_code": None, "evidence": receipt.get("instance_id")}


class OwnerCanary:
    """LABELLED. The result shapes of `adapters/host_delivery.owner_qualified_canary`: the owner's own receipt for
    exactly this plan and descriptor. `receipts` maps plan id -> the owner's receipt body and `requests` is the set of
    plan ids with a filed request (the pending case); nothing here runs a model, a provider or a worker."""

    def __init__(self, host):
        self.host, self.receipts, self.requests = host, {}, set()

    def owner_receipt(self, plan_id, descriptor, *, passed=True, instance_id=None, evidence="fixture-owner-canary"):
        self.receipts[plan_id] = {"descriptor_sha256": self.host.api.descriptor_digest(descriptor),
                                  "instance_id": instance_id, "passed": passed, "evidence": evidence}

    def __call__(self, target, descriptor, startup, *, plan=None):
        if not isinstance(plan, dict):
            return {"passed": False, "reason_code": "canary_owner_receipt_missing", "evidence": None}
        receipt = self.receipts.get(plan["plan_id"])
        if not isinstance(receipt, dict):
            if plan["plan_id"] in self.requests:
                return {"passed": False, "pending": True, "reason_code": "canary_owner_receipt_pending",
                        "evidence": None}
            return {"passed": False, "reason_code": "canary_owner_receipt_missing", "evidence": None}
        if receipt.get("descriptor_sha256") != self.host.api.descriptor_digest(descriptor):
            return {"passed": False, "reason_code": "canary_owner_receipt_stale", "evidence": None}
        if receipt.get("instance_id") is not None \
                and receipt.get("instance_id") != (startup or {}).get("instance_id"):
            return {"passed": False, "reason_code": "canary_owner_receipt_stale", "evidence": None}
        return {"passed": bool(receipt.get("passed")), "evidence": receipt.get("evidence"),
                "reason_code": None if receipt.get("passed") else "canary_owner_receipt_failed"}


class Verifier:
    """LABELLED. The port `HostDelivery._verify` calls on `adapters/release_verifier.ReleaseVerifier`: `available()`,
    `reconcile(open_attempts)`, `new_attempt(plan_id=, release_id=, generation=)`, `prepare(attempt)` and
    `evaluate(release_id, attempt, fence=)`, answering the shapes of that adapter (`reconcile` -> state/reason_code/
    resolved; `evaluate` -> the `_checked` outcome plus state, evaluation and cleanup). It runs no evaluator, container
    or child; `checks` are the LABELLED check results it reports. Faults: `usable` (available), `reconciled` (the
    reconcile answer), `outcome` (replaces the evaluation outcome), `prepare_error`."""

    def __init__(self, api, *, checks=None, usable=True, reconciled=None, outcome=None, prepare_error=None):
        self.api = api
        self.checks = checks or {"tests": {"passed": True, "evidence": "fixture-incumbent-check-receipt"}}
        self.usable, self.outcome, self.prepare_error = usable, outcome, prepare_error
        self.reconciled = reconciled or {"state": "clear", "reason_code": None, "resolved": {}}
        self.attempts, self.prepared, self.evaluated = [], [], []

    def available(self):
        return self.usable

    def reconcile(self, open_attempts):
        return copy.deepcopy(self.reconciled)

    def new_attempt(self, *, plan_id, release_id, generation):
        self.attempts.append(plan_id)
        return {"attempt_id": hashlib.sha256(("attempt:%d" % len(self.attempts)).encode()).hexdigest()[:32],
                "plan_id": plan_id, "release_id": release_id, "generation": generation,
                "owner": {"pid": 4200, "boot_id": "fixture-boot", "start_ticks": 1},
                "started_at": self.api.now().isoformat()}

    def prepare(self, attempt):
        if self.prepare_error is not None:
            raise self.prepare_error  # labelled injected loss of the disk record
        self.prepared.append(attempt["attempt_id"])
        return {"attempt_id": attempt["attempt_id"], "state": "prepared"}

    def evaluate(self, release_id, attempt, *, fence):
        self.evaluated.append(attempt["attempt_id"])
        if self.outcome is not None:
            return copy.deepcopy(self.outcome)
        fence()   # the evaluator's heartbeat through this claim's fence
        return {"verdict": "checked", "passed": True, "checks": copy.deepcopy(self.checks), "image": None,
                "receipt": None, "state": "evaluated", "evaluation": "fixture-evaluation-receipt",
                "cleanup": {"state": "confirmed"}}


# ---- builders (M7 tests/test_host_delivery.py) ---------------------------------------------------------------
def candidate(revision=REVISION, tree=TREE, repository=REPOSITORY):
    return {"revision": revision, "base": BASE, "tree": tree, "author": "worker:implementation",
            "branch": "harness/delivery-1", "task_id": "delivery-1", "repository": repository,
            "objective": CANARY_TEXT}


def successor_candidate(system, **overrides):
    """A candidate cut from the remote main AS IT IS NOW (a real successor's reviewed base)."""
    return {**candidate(), "base": system["github"].main, **overrides}


def release_policy():
    return {"checks": ["tests"], "evaluator": "fixture-incumbent-policy"}


def reviewed_release(api, store, org, *, verified=True, record_candidate=None, lead=True, conductor=True):
    """A release record built through the EXISTING Releases authority (`api.releases(store)`); no shortcut row."""
    releases = api.releases(store)
    row = releases.propose(record_candidate or candidate(), release_policy())
    if lead:
        releases.review(row["id"], "lead:improvement", row["candidate"]["revision"], True,
                        "fixture-lead-review-evidence")
    if conductor and lead:
        releases.review(row["id"], "conductor", row["candidate"]["revision"], True,
                        "fixture-conductor-review-evidence")
    if verified and lead and conductor:
        releases.verify(row["id"], row["candidate"]["revision"], row["policy_hash"],
                        {"tests": {"passed": True, "evidence": "fixture-incumbent-check-receipt"}})
    with store.transaction() as tx:
        return tx.get("releases", row["id"])


def targets_document(api, target_id="canary-service", kind="process", root=None):
    """The owner's host configuration: a fixed LABELLED root and state directory, not a path of this machine."""
    return {"schema": api.REGISTRY_SCHEMA,
            "targets": [{"target_id": target_id, "kind": kind, "root": root or RUNTIME_ROOT,
                         "state_dir": STATE_ROOT + "/state-" + target_id, "service": "zeus-canary-service"}]}


def plan_document(api, release, *, plan_id="delivery-plan-1", target_id="canary-service", expected=None,
                  checks=(CHECK,), canary=None, image=IMAGE, profile=PROFILE, revision=None, tree=None,
                  policy_hash=None, repository=REPOSITORY, descriptor_revision=None, ci_timeout=300,
                  consumption_timeout=120):
    return {"schema": api.PLAN_SCHEMA, "plan_id": plan_id, "release_id": release["id"],
            "revision": revision or release["candidate"]["revision"],
            "tree": tree or release["candidate"]["tree"],
            "policy_hash": policy_hash or release["policy_hash"], "repository": repository,
            "required_checks": list(checks), "target_id": target_id,
            "expected_descriptor": expected,
            "target_descriptor": {"revision": descriptor_revision or DESCRIPTOR_REVISION,
                                  "worker_image": image, "profile_digest": profile},
            "canary_check_id": canary or api.CANARY_STARTUP, "ci_timeout_seconds": ci_timeout,
            "consumption_timeout_seconds": consumption_timeout}


def pin(path=PLAN_PATH, revision="f" * 40, body=b"fixture-plan-bytes"):
    return {"revision": revision, "path": path, "sha256": hashlib.sha256(body).hexdigest()}


def build(api, *, github=None, canaries=None, enabled=True, store=None, org=None, target_id="canary-service",
          kind="process", verified=True, lead=True, conductor=True, plan_overrides=None, register_plan=True,
          root=None, host=None, verifier=None, resume_seconds=0):
    """One wired controller over a MemoryHost and a labelled GitHub double (M7 `build`)."""
    store = store or SerialStore(api)
    org = org or api.organization()
    release = reviewed_release(api, store, org, verified=verified, lead=lead, conductor=conductor)
    host = host if host is not None else MemoryHost(api)
    owner = OwnerCanary(host)
    if canaries is None:
        canaries = {api.CANARY_STARTUP: StartupCanary(host), api.CANARY_FLEET: owner}
    delivery = api.HostDelivery(store, org, github=github if github is not None else FakeGitHub(api),
                                hosts={kind: host}, canaries=canaries, clock=clock(api), enabled=enabled,
                                resume_seconds=resume_seconds, verifier=verifier)
    registry = targets_document(api, target_id=target_id, kind=kind, root=root)
    delivery.register_targets(registry)
    plan = plan_document(api, release, target_id=target_id, **(plan_overrides or {}))
    if register_plan:
        delivery.register(plan, pin())
    return {"api": api, "store": store, "org": org, "delivery": delivery, "release": release, "plan": plan,
            "host": host, "github": delivery.github, "target": registry["targets"][0], "owner_canary": owner,
            "verifier": verifier}


def drive(system, *, until=None, limit=40):
    """Tick until the delivery reaches a stage; the ONE timeline moves one second per tick (never a sleep), as a real
    bounded loop's would, so a stage deadline is reached by ticking (M7 `drive`, without the real child's wait)."""
    api = system["api"]
    until = until or api.ACTIVE
    results = []
    for _ in range(limit):
        result = system["delivery"].tick()
        api.advance(1)
        results.append(result)
        if result["stage"] == until:
            return results
        if result["outcome"] in {"blocked", "refused"}:
            return results
    return results


def stages(results):
    return [result["stage"] for result in results]


def visited(results):
    """The stages in order with consecutive repeats collapsed."""
    seen = []
    for stage in stages(results):
        if not seen or seen[-1] != stage:
            seen.append(stage)
    return seen


def intent_of(system, plan_id=None):
    with system["store"].transaction() as tx:
        return tx.get(BUCKET_INTENTS, plan_id or system["plan"]["plan_id"])


def descriptor_of(system, target_id="canary-service"):
    with system["store"].transaction() as tx:
        return tx.get(BUCKET_DESCRIPTORS, target_id)


def stop_target(system):
    """Leave nothing running, whatever the case proved."""
    try:
        system["host"].stop(system["target"])
    except Exception:  # cleanup is best effort
        pass
