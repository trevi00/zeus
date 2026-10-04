"""Ported SOURCE M7 suite `tests/test_host_delivery_first_activation.py` (e38aa722) run against the S7 target (DESIGN-s7 §6).

Every assertion is M7's, unchanged. Adaptations, all construction, import and patch-target (the `m7_delivery` shim
docstring names the routing): `HostDelivery`, `Releases`, `ReleaseQueue`, `ProcessHostTarget`, `GitHubDelivery`, the
canary and runtime helpers, `Fleet`, `organization`, `MemoryStore`, `GitWorkspace`, `MergeRefused`, `ContractError`,
`POLICY` and `digest` come from the shim over the S7 split objects and moved adapters; the domain names from
`delivery.domain.host_delivery`, the BUCKET_* names from `delivery.application.host_delivery.state`, the fleet names
from `coordination`, the observation names from `observation`. A name whose owner is in a later slice (the operator
CLI and lane resolution, S10; the release evaluator and `verification_fixtures`, S8; the Windows scheduled task,
W-B) is an `unavailable(slice, name)` placeholder, and only tests skipped whole and unrewritten (each with its owning
slice) name it.
Root path adaptation: `test_the_committed_profile_digest_equals_the_incumbent_packaged_digest` takes the target tree
(`Path(__file__).resolve().parents[2]`) as the checkout root, where M7 took `parent.parent` of `tests/`.

S10 unit C8b-4 (R-c31) un-skipped the cases that name only the host-delivery CLI and composition functions (import lines, call names and patch targets only): `cli_host_delivery` is `composition.cli_host_delivery`, `execute` is `entry.cli.host_delivery._execute` and `add_parser` is `entry.cli.host_delivery.add_parser`; the production coordinator is the S7 split owners, so a patched `controller` returns them (`SimpleNamespace(recovery=..., resumption=...)`) and `controller(...)` reading M7's one object is the shim `HostDelivery` over `controller_ports`. 

M7 docstring follows.

The first-activation binding of a managed delivery (INV-HOST-DELIVERY-FIRST-ACTIVATION-001).

What is real: the `HostDelivery` lane code, the `Releases`/`ReleaseQueue` owners, the store (the
in-memory store, and an isolated PostgreSQL schema when `HARNESS_INTEGRATION=1`; without it that
parameter SKIPS and is not evidence), the organization and the process host target's identity read.

What is a LABELLED FIXTURE: the GitHub port (`FakeGitHub`), the first-activation port
(`FixedFacts`: fixed image id, profile digest and image source revision, never Docker or Git), the
counting verifier double and the historical null+`unchanged` plan row written as `register` used to
write it. Nothing here touches a production host, Docker daemon, credential or model.
"""
import threading

import pytest
from m7_delivery import HostDelivery, MemoryStore, digest
from test_host_delivery import (
    PROFILE,
    START,
    SerialStore,
    binds_a_runtime,
    build,
    drive,
    intent_of,
    pin,
    register_historical,
    stop_target,
    visited,
)

from codex_harness.delivery.application.host_delivery.state import (
    BUCKET_DESCRIPTORS,
    BUCKET_INTENTS,
    BUCKET_PLANS,
)
from codex_harness.delivery.domain.host_delivery import (
    ACTIVE,
    BLOCKED,
    DRAIN_INTENDED,
    FIRST_ACTIVATION_SCHEMA,
    MERGED,
    RECOVERY_FIRST_ACTIVATION,
    UNCHANGED,
    DeliveryRefused,
    descriptor_digest,
    first_activation_resumable,
    first_activation_unbound,
    resolve_descriptor,
    validate_first_activation,
)

IMAGE_ID = "sha256:" + "d" * 64
PROFILE_HEX = "e" * 64
SOURCE_REVISION = "1" * 40
QUALIFICATION = "sha256:" + "5" * 64


class FixedFacts:
    """LABELLED FAKE of the trusted port: fixed facts, every call counted, optional barrier."""

    def __init__(self, image=IMAGE_ID, profile=PROFILE_HEX, source=SOURCE_REVISION, barrier=None):
        self.facts = {"worker_image": image, "profile_digest": profile, "image_source_revision": source}
        self.calls, self.barrier = [], barrier

    def __call__(self, revision):
        self.calls.append(revision)
        if self.barrier is not None:
            self.barrier.wait(timeout=10)
        return dict(self.facts)


class CountingVerifier:
    """LABELLED DOUBLE: any use of the verifier port is recorded; a first activation needs none."""

    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        def record(*args, **kwargs):
            self.calls.append(name)
            raise AssertionError("the verifier must not be called")
        return record


class ConductorFor:
    """LABELLED ORG DOUBLE: grants the conductor role to one extra actor; everything else delegates."""

    def __init__(self, org, actor_id):
        self.org, self.actor_id = org, actor_id

    def actor(self, actor_id, role=None):
        if actor_id == self.actor_id and role == "conductor":
            return self.org.actor(actor_id)
        return self.org.actor(actor_id, role)


def halted(tmp_path, store=None):
    """A historical null+`unchanged` plan driven to the real `unchanged_without_predecessor` halt."""
    system = build(tmp_path, plan_overrides={"image": UNCHANGED, "profile": UNCHANGED}, register_plan=False,
                   store=store)
    register_historical(system)
    drive(system, until=MERGED, limit=8)
    refused = system["delivery"].tick()
    assert refused["reason_code"] == "unchanged_without_predecessor"
    intent = intent_of(system)
    assert first_activation_resumable(intent), intent
    system["port"] = FixedFacts()
    system["delivery"].first_activation = system["port"]
    system["verifier"] = CountingVerifier()
    system["delivery"].verifier = system["verifier"]
    return system


def document(system, **overrides):
    with system["store"].transaction() as tx:
        row = tx.get(BUCKET_PLANS, system["plan"]["plan_id"])
    intent = intent_of(system)
    body = {"schema": FIRST_ACTIVATION_SCHEMA, "kind": RECOVERY_FIRST_ACTIVATION,
            "plan_id": row["plan_id"], "plan_sha256": row["plan_sha256"], "pin_sha256": row["pin"]["sha256"],
            "target_id": row["target_id"], "release_id": system["release"]["id"],
            "candidate_revision": system["release"]["candidate"]["revision"],
            "candidate_tree": system["release"]["candidate"]["tree"],
            "halt": {key: intent[key] for key in ("stage", "previous_stage", "reason_code", "updated_at")},
            "expected_descriptor": None, "predecessor": None, "worker_image": IMAGE_ID,
            "profile_digest": PROFILE_HEX,
            "qualification": {"image_source_revision": SOURCE_REVISION, "evidence": QUALIFICATION},
            "approved_by": "conductor"}
    body.update(overrides)
    return body, "sha256:" + digest(body)


def resume(system, body=None, evidence=None, delivery=None, plan_sha256=None):
    if body is None:
        body, evidence = document(system)
    with system["store"].transaction() as tx:
        sha = plan_sha256 or tx.get(BUCKET_PLANS, system["plan"]["plan_id"])["plan_sha256"]
    return (delivery or system["delivery"]).resume_first_activation(system["plan"]["plan_id"], sha, body,
                                                                    evidence or "sha256:" + digest(body))


def snapshot(system):
    with system["store"].transaction() as tx:
        return {"intent": tx.get(BUCKET_INTENTS, system["plan"]["plan_id"]),
                "plan": tx.get(BUCKET_PLANS, system["plan"]["plan_id"]),
                "queue": tx.get("release_queue", system["release"]["id"]),
                "release": tx.get("releases", system["release"]["id"]),
                "descriptors": tx.scan(BUCKET_DESCRIPTORS)}


def refused(system, code, **kwargs):
    before = snapshot(system)
    with pytest.raises(DeliveryRefused) as caught:
        resume(system, **kwargs)
    assert caught.value.reason_code == code
    assert snapshot(system) == before, "a refusal writes nothing"


# ----- domain ---------------------------------------------------------------------------------
def test_the_binding_is_used_only_for_a_first_activation_and_an_upgrade_is_unchanged(tmp_path):
    target = {"target_id": "t", "kind": "process", "root": str(tmp_path)}
    plan = {"expected_descriptor": None,
            "target_descriptor": {"revision": "a" * 40, "worker_image": UNCHANGED, "profile_digest": UNCHANGED}}
    binding = {"worker_image": IMAGE_ID, "profile_digest": PROFILE_HEX}
    with pytest.raises(DeliveryRefused, match="unchanged_without_predecessor"):
        resolve_descriptor(target, plan, None)
    first = resolve_descriptor(target, plan, None, binding)
    assert (first["worker_image"], first["profile_digest"], first["predecessor"]) == (IMAGE_ID, PROFILE_HEX, None)
    current = {**first, "worker_image": "sha256:" + "7" * 64, "profile_digest": "8" * 64}
    upgrade = {**plan, "expected_descriptor": descriptor_digest(current)}
    assert resolve_descriptor(target, upgrade, current, binding) == resolve_descriptor(target, upgrade, current)
    assert resolve_descriptor(target, upgrade, current, binding)["worker_image"] == current["worker_image"]
    with pytest.raises(DeliveryRefused, match="unchanged_without_predecessor"):
        resolve_descriptor(target, upgrade, None, binding)
    assert first_activation_unbound(plan) and not first_activation_unbound(upgrade)


@pytest.mark.parametrize("field,value", [
    ("predecessor", "sha256:" + "0" * 64), ("expected_descriptor", "f" * 64), ("worker_image", "zeus:latest"),
    ("profile_digest", "none"), ("kind", "release_verification_missing"),
    ("qualification", {"image_source_revision": "x", "evidence": QUALIFICATION})])
def test_the_document_grammar_refuses_every_field_it_does_not_bind_exactly(tmp_path, field, value):
    system = halted(tmp_path)
    body, _ = document(system, **{field: value})
    with pytest.raises(DeliveryRefused) as caught:
        validate_first_activation(body)
    assert caught.value.reason_code == "first_activation_invalid"
    refused(system, "first_activation_invalid", body=body)
    assert system["port"].calls == []


# ----- the lane recovery ----------------------------------------------------------------------
def test_a_first_boot_binds_the_re_derived_tuple_and_prepare_switch_resolves_it(tmp_path):
    system = halted(tmp_path)
    before = snapshot(system)
    receipt = resume(system)
    assert receipt["cached"] is False and receipt["stage"] == MERGED
    assert receipt["recovery"]["kind"] == RECOVERY_FIRST_ACTIVATION
    assert receipt["recovery"]["binding"]["worker_image"] == IMAGE_ID
    assert receipt["queue"]["manual_retries"] == 1
    intent = intent_of(system)
    assert (intent["stage"], intent["previous_stage"], intent["reason_code"], intent["attempts"]) == (
        MERGED, BLOCKED, None, 0)
    recovery = intent["recoveries"][-1]
    assert recovery["binding"] == {"worker_image": IMAGE_ID, "profile_digest": PROFILE_HEX,
                                   "image_source_revision": SOURCE_REVISION,
                                   "qualification_evidence": QUALIFICATION}
    assert recovery["halted"]["reason_code"] == "unchanged_without_predecessor"
    assert recovery["observed"] == FixedFacts().facts
    assert system["port"].calls == [system["plan"]["revision"]]
    status = system["delivery"].status()["deliveries"][0]
    assert status["recoveries"][-1]["kind"] == RECOVERY_FIRST_ACTIVATION
    assert status["recoveries"][-1]["binding"]["profile_digest"] == PROFILE_HEX
    # The next ordinary tick binds the descriptor; nothing else about the release moved.
    result = system["delivery"].tick()
    assert result["stage"] == DRAIN_INTENDED, result
    intent = intent_of(system)
    descriptor = intent["descriptor"]
    assert (descriptor["worker_image"], descriptor["profile_digest"], descriptor["predecessor"]) == (
        IMAGE_ID, PROFILE_HEX, None)
    assert intent["descriptor_sha256"] == descriptor_digest(descriptor)
    assert snapshot(system)["release"] == before["release"]
    assert system["verifier"].calls == []


def test_a_replay_is_cached_at_any_stage_and_another_document_conflicts(tmp_path):
    system = halted(tmp_path)
    body, evidence = document(system)
    first = resume(system, body, evidence)
    again = resume(system, body, evidence)
    assert again["cached"] is True and again["recovery"] == first["recovery"]
    system["delivery"].tick()
    assert intent_of(system)["stage"] == DRAIN_INTENDED
    # A restarted controller (lost response) over the same store answers from the durable record.
    restarted = HostDelivery(system["store"], system["org"])
    before = snapshot(system)
    assert resume(system, body, evidence, delivery=restarted)["cached"] is True
    assert snapshot(system) == before
    other, other_evidence = document(system, halt=body["halt"],
                                     qualification={"image_source_revision": SOURCE_REVISION,
                                                    "evidence": "sha256:" + "6" * 64})
    refused(system, "resume_conflict", body=other, evidence=other_evidence)
    assert len(intent_of(system)["recoveries"]) == 1


@pytest.mark.parametrize("facts,code", [
    ({"image": "sha256:" + "9" * 64}, "first_activation_image_mismatch"),
    ({"profile": "9" * 64}, "first_activation_profile_mismatch"),
    ({"source": "2" * 40}, "first_activation_qualification_mismatch")])
def test_facts_that_differ_from_the_document_refuse_with_no_write(tmp_path, facts, code):
    system = halted(tmp_path)
    system["delivery"].first_activation = FixedFacts(**facts)
    refused(system, code)


def test_a_missing_or_refusing_port_is_unavailable_with_no_write(tmp_path):
    system = halted(tmp_path)
    system["delivery"].first_activation = None
    refused(system, "first_activation_unavailable")

    def unconfigured(_revision):
        raise DeliveryRefused("first_activation_image_unconfigured", "worker_image")

    system["delivery"].first_activation = unconfigured
    refused(system, "first_activation_image_unconfigured")


@pytest.mark.parametrize("field,value,code", [
    ("candidate_tree", "0" * 64, "first_activation_candidate_tree_mismatch"),
    ("candidate_revision", "0" * 40, "first_activation_candidate_revision_mismatch"),
    ("pin_sha256", "0" * 64, "first_activation_pin_mismatch"),
    ("approved_by", "lead:improvement", "first_activation_approver_invalid")])
def test_identity_drift_or_the_wrong_authority_refuses_with_no_write(tmp_path, field, value, code):
    system = halted(tmp_path)
    body, evidence = document(system, **{field: value})
    refused(system, code, body=body, evidence=evidence)


def test_the_candidate_author_cannot_approve_even_as_a_conductor(tmp_path):
    system = halted(tmp_path)
    author = system["release"]["candidate"]["author"]
    system["delivery"].org = ConductorFor(system["org"], author)
    body, evidence = document(system, approved_by=author)
    refused(system, "first_activation_approver_author", body=body, evidence=evidence)


def test_a_wrong_plan_digest_or_evidence_refuses(tmp_path):
    system = halted(tmp_path)
    refused(system, "resume_plan_mismatch", plan_sha256="0" * 64)
    body, _ = document(system)
    refused(system, "first_activation_evidence_mismatch", body=body, evidence="sha256:" + "0" * 64)


def test_a_predecessor_descriptor_unexpectedly_present_refuses_with_no_write(tmp_path):
    system = halted(tmp_path)
    with system["store"].transaction() as tx:
        tx.put(BUCKET_DESCRIPTORS, system["plan"]["target_id"],
               {"id": system["plan"]["target_id"], "target_id": system["plan"]["target_id"],
                "descriptor": {"revision": "a" * 40}})
    refused(system, "first_activation_predecessor_present")


def test_a_live_controller_lease_refuses_with_no_write(tmp_path):
    system = halted(tmp_path)
    with system["store"].transaction() as tx:
        tx.put("deployment_locks", "controller", {"id": "controller", "lease_until": "2999-01-01T00:00:00+00:00"})
    refused(system, "resume_controller_running")


def test_a_delivery_not_in_the_first_activation_shape_is_not_applicable(tmp_path):
    system = build(tmp_path)
    drive(system, until=MERGED, limit=8)
    body, evidence = document(system)
    system["delivery"].first_activation = FixedFacts()
    before = snapshot(system)
    with pytest.raises(DeliveryRefused):
        resume(system, body, evidence)
    assert snapshot(system) == before


@pytest.fixture(params=["memory", pytest.param("postgres", marks=pytest.mark.integration)])
def concurrent_store(request):
    if request.param == "memory":
        return MemoryStore()
    return request.getfixturevalue("isolated_pgstore")


def test_two_concurrent_resumes_retry_the_queue_exactly_once(tmp_path, concurrent_store):
    system = halted(tmp_path, store=concurrent_store)
    body, evidence = document(system)
    barrier = threading.Barrier(2)
    system["delivery"].first_activation = FixedFacts(barrier=barrier)
    results, errors = [], []

    def run():
        try:
            results.append(resume(system, body, evidence))
        except Exception as exc:  # recorded for the assertion below
            errors.append(exc)

    threads = [threading.Thread(target=run) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert errors == [] and sorted(result["cached"] for result in results) == [False, True]
    assert len(snapshot(system)["queue"]["manual_retries"]) == 1
    assert len(intent_of(system)["recoveries"]) == 1


# ----- registration ---------------------------------------------------------------------------
def test_a_new_unbound_plan_is_refused_and_an_old_one_stays_readable_and_cached(tmp_path):
    system = build(tmp_path, plan_overrides={"profile": UNCHANGED}, register_plan=False, store=SerialStore())
    with pytest.raises(DeliveryRefused) as caught:
        system["delivery"].register(system["plan"], pin())
    assert (caught.value.reason_code, caught.value.field) == ("first_activation_unbound", "target_descriptor")
    assert system["delivery"].plan(system["plan"]["plan_id"]) is None
    register_historical(system)
    assert system["delivery"].register(system["plan"], pin())["cached"] is True
    view = system["delivery"].status()["deliveries"][0]
    assert view["plan_id"] == system["plan"]["plan_id"] and view["recoveries"] == []
    assert system["delivery"].plan(system["plan"]["plan_id"])["registered_at"] == START


@binds_a_runtime
def test_a_bound_first_activation_drains_switches_starts_and_is_consumed(tmp_path, monkeypatch):
    """The real process target end to end: the launched runtime reports the bound image (the host
    settings SSOT, set here for this test process and its child) and its packaged profile digest."""
    monkeypatch.setenv("ZEUS_WORKER_IMAGE", IMAGE_ID)
    system = halted(tmp_path)
    try:
        system["delivery"].first_activation = FixedFacts(profile=PROFILE)
        body, evidence = document(system, profile_digest=PROFILE)
        resume(system, body, evidence)
        results = drive(system, until=ACTIVE, limit=40)
        assert visited(results)[-1] == ACTIVE, visited(results)
        intent = intent_of(system)
        assert intent["descriptor"]["worker_image"] == IMAGE_ID and intent["descriptor"]["predecessor"] is None
        assert system["verifier"].calls == []
    finally:
        stop_target(system)


# ----- the trusted adapter port -----------------------------------------------------------------
class Completed:
    def __init__(self, returncode, stdout):
        self.returncode, self.stdout = returncode, stdout


class Blobs:
    """LABELLED FAKE GitSource: committed bytes by path, or missing."""

    def __init__(self, files):
        self.files = files

    def blob(self, revision, path):
        data = self.files.get(path)
        return (None, b"") if data is None else ("100644", data)


def test_the_committed_profile_digest_equals_the_incumbent_packaged_digest():
    import subprocess
    from pathlib import Path

    from m7_delivery import GitSource, committed_profile_digest, effective_profile_digest

    root = Path(__file__).resolve().parents[2]  # adaptation: the target tree
    head = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True)
    dirty = subprocess.run(["git", "-C", str(root), "status", "--porcelain", "--", "src/codex_harness/resources"],
                           capture_output=True, text=True)
    if head.returncode or dirty.stdout.strip():
        pytest.skip("no clean committed resources in this checkout")
    assert committed_profile_digest(GitSource(root), head.stdout.strip()) == effective_profile_digest()
    with pytest.raises(DeliveryRefused) as caught:
        committed_profile_digest(Blobs({}), "a" * 40)
    assert caught.value.reason_code == "first_activation_profile_unresolved"


def test_the_port_re_derives_the_image_from_settings_and_the_local_image():
    from m7_delivery import first_activation_facts

    lane = {"repository": "/nonexistent"}
    with pytest.raises(DeliveryRefused) as caught:
        first_activation_facts(lane, {}, "a" * 40, run=lambda *a, **k: Completed(0, ""))
    assert caught.value.reason_code == "first_activation_image_unconfigured"
    host = {"ZEUS_WORKER_IMAGE": IMAGE_ID}
    seen = []

    def inspect(argv, timeout=None):
        seen.append(argv)
        return Completed(0, IMAGE_ID + " " + SOURCE_REVISION + "\n")

    def other(argv, timeout=None):
        return Completed(0, "sha256:" + "9" * 64 + " " + SOURCE_REVISION)

    for run in (other, lambda argv, timeout=None: Completed(1, ""), lambda argv, timeout=None: Completed(0, IMAGE_ID)):
        with pytest.raises(DeliveryRefused) as caught:
            first_activation_facts(lane, host, "a" * 40, run=run, source=Blobs({}))
        assert caught.value.reason_code == "first_activation_image_unavailable"
    with pytest.raises(DeliveryRefused) as caught:
        first_activation_facts(lane, host, "a" * 40, run=inspect, source=Blobs({}))
    assert caught.value.reason_code == "first_activation_profile_unresolved"
    assert seen[0][:4] == ["docker", "image", "inspect", IMAGE_ID]


def test_the_resume_command_routes_a_document_to_the_first_activation_binding(tmp_path, monkeypatch):
    """`host-delivery resume --document FILE` calls `resume_first_activation`; without it, `resume`."""
    import json
    from types import SimpleNamespace

    from m7_delivery import organization

    from codex_harness.composition import cli_host_delivery as host_delivery
    from codex_harness.entry import cli
    from codex_harness.entry.cli.host_delivery import _execute as execute

    body = {"kind": RECOVERY_FIRST_ACTIVATION}
    path = tmp_path / "binding.json"
    path.write_text(json.dumps(body), encoding="utf-8")
    argv = ["host-delivery", "resume", "--lane", "harness", "--plan", "own-plan", "--plan-sha256", "c" * 64,
            "--evidence", "sha256:" + "e" * 64]
    assert cli.parser().parse_args(argv).document is None
    parsed = cli.parser().parse_args(argv + ["--document", str(path)])
    calls = []

    class Controller:
        def resume(self, *arguments):
            calls.append(("resume", arguments))
            return {"resumed": True}

        def resume_first_activation(self, *arguments):
            calls.append(("first_activation", arguments))
            return {"resumed": True}

    route = {"lane": {"id": "harness", "repository": str(tmp_path), "runtime": str(tmp_path / "rt")},
             "store": MemoryStore()}
    monkeypatch.setattr(host_delivery, "resolve_lane", lambda _service, lane_id: route)
    monkeypatch.setattr(host_delivery, "lane_git", lambda lane, host: SimpleNamespace(remote="zeus-owner/zeus-harness"))
    monkeypatch.setattr(host_delivery, "_lane_observer", lambda _route: None)
    monkeypatch.setattr(host_delivery, "_settings", lambda: {})
    monkeypatch.setattr(host_delivery, "controller", lambda _service, **kwargs: SimpleNamespace(recovery=Controller(), resumption=Controller()))
    service = SimpleNamespace(store=MemoryStore(), org=organization())
    assert execute(service, parsed)["exit_code"] == 0
    assert calls == [("first_activation", ("own-plan", "c" * 64, body, "sha256:" + "e" * 64))]
    calls.clear()
    execute(service, cli.parser().parse_args(argv))
    assert calls == [("resume", ("own-plan", "c" * 64, "sha256:" + "e" * 64))]
