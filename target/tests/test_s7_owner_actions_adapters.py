"""S7 owner-action adapters (pilot 54): `GitPlanPublisher` (coordination) and `TargetFiles` (delivery), moved by
A/evidence/rebuild/s7/owner-actions-adapters/transcribe.py. The M7 owner-action suites are their wider verification."""
import json
import subprocess

import pytest

from codex_harness.composition import owner_action_adapters
from codex_harness.coordination.adapters.owner_actions import GitPlanPublisher
from codex_harness.delivery.adapters import host_delivery
from codex_harness.delivery.adapters.target_files import TargetFiles
from codex_harness.delivery.domain.host_delivery import CANARY_STARTUP, PLAN_SCHEMA

WHEN = "2026-01-01T00:00:00+00:00"
PLAN_PATH = "docs/plan.json"
REF = "refs/zeus/plan/x"
REVISION, TREE, POLICY_HASH = "a" * 40, "c" * 64, "1" * 64


def git(root, *argv) -> str:
    return subprocess.run(["git", "-C", str(root), *argv], check=True, capture_output=True,
                          text=True).stdout.strip()


@pytest.fixture
def repository(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    return root


def plan_document() -> dict:
    return {"schema": PLAN_SCHEMA, "plan_id": "delivery-plan-1", "release_id": "release-1",
            "revision": REVISION, "tree": TREE, "policy_hash": POLICY_HASH,
            "repository": "github:zeus-owner/zeus-harness", "required_checks": ["ci / required"],
            "target_id": "canary-service", "expected_descriptor": None,
            "target_descriptor": {"revision": REVISION, "worker_image": "zeus-worker@sha256:" + "d" * 64,
                                  "profile_digest": "e" * 64},
            "canary_check_id": CANARY_STARTUP, "ci_timeout_seconds": 300,
            "consumption_timeout_seconds": 120}


def test_required_keywords(repository):
    with pytest.raises(TypeError):
        GitPlanPublisher(repository)
    with pytest.raises(TypeError):
        GitPlanPublisher(repository, runner=subprocess.run, load_plan=None)


def test_publish_creates_recognizes_and_conflicts(repository):
    publisher = owner_action_adapters.git_plan_publisher(repository)
    first = publisher.publish(b'{"a":1}', PLAN_PATH, REF, WHEN)
    assert first["conflict"] is False
    assert git(repository, "rev-parse", REF) == first["revision"]
    assert publisher.publish(b'{"a":1}', PLAN_PATH, REF, WHEN) == first  # our own commit

    other = publisher.publish(b'{"a":2}', PLAN_PATH, REF, WHEN)
    assert other["conflict"] is True and other["revision"] != first["revision"]
    assert git(repository, "rev-parse", REF) == first["revision"]  # another commit never moves the ref
    assert git(repository, "for-each-ref", "--format=%(refname)") == REF


def test_load_reads_the_committed_plan(repository):
    publisher = owner_action_adapters.git_plan_publisher(repository)
    data = json.dumps(plan_document()).encode()
    published = publisher.publish(data, PLAN_PATH, REF, WHEN)
    loaded = publisher.load(published["revision"], PLAN_PATH)
    assert loaded["plan"]["plan_id"] == "delivery-plan-1"
    assert loaded["pin"]["revision"] == published["revision"] and loaded["pin"]["path"] == PLAN_PATH
    assert loaded["bytes"] == len(data)


def test_composition_wiring():
    publisher = owner_action_adapters.git_plan_publisher("r", timeout=7)
    assert publisher.timeout == 7 and publisher.repository == "r"
    assert publisher.runner.__module__.endswith("process_groups")
    assert publisher.load_plan.func is host_delivery.load_plan


@pytest.fixture
def target(tmp_path):
    return {"state_dir": str(tmp_path / "state")}


def test_target_files_request_receipt_round_trip(target):
    request, receipt = {"plan": "p1", "n": 1}, {"outcome": "ok"}
    TargetFiles.write_request(target, "p1", request)
    assert TargetFiles.request(target, "p1") == request
    assert TargetFiles.receipt(target, "p1") is None
    TargetFiles.write_receipt(target, "p1", receipt)
    assert TargetFiles.receipt(target, "p1") == receipt
    assert TargetFiles.startup(target) is None


def test_target_files_unreadable_receipt_is_unknown_not_absent(target):
    TargetFiles.write_request(target, "p1", {})
    path = host_delivery.HostTargetBase.path(target, host_delivery.canary_receipt_file("p1"))
    path.write_text("not json", encoding="utf-8")
    assert TargetFiles.receipt(target, "p1") == {"unreadable": True}
    path.write_text("[1]", encoding="utf-8")
    assert TargetFiles.receipt(target, "p1") == {"unreadable": True}
