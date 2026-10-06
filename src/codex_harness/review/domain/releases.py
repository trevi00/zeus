"""Release successor and approval vocabulary (pure; M7 `application/releases.py` module level, moved in S7).

Layer: domain
Context: review
Owns: the successor identities of a check-rejected release, the evaluator-migration and
    environment-reverification approval shapes and pins, and their named refusals
Does not own: the release records (review.application.releases)
Entry points: expected_evaluator_pin, require_controller_code, EnvironmentReverificationRefused,
    UnsupportedEvaluatorReverification, evaluator_successor_id, reverification_successor_id,
    environment_successor_id
Contracts: INV-RELEASE-001, INV-RELEASE-EVALUATOR-MIGRATION-001, INV-RELEASE-ENVIRONMENT-REVERIFY-001

S7 named transcription (DESIGN-s7 V3): verbatim; delivery imports it as a domain (delivery → review).
"""
from __future__ import annotations

import re

from codex_harness.kernel.errors import ContractError, require
from codex_harness.kernel.ids import digest


class UnsupportedEvaluatorReverification(ContractError):
    """INV-RELEASE-EVALUATOR-MIGRATION-001: an evaluator-migrated release gets no further successor.

    An ordinary reverification would drop the evaluator receipt the runner requires for a non-base
    test source, and a second migration would chain evaluator authority; both refuse before any write.
    """

    reason_code = "unsupported_evaluator_reverification"

    def __init__(self):
        super().__init__("unsupported_evaluator_reverification: "
                         "release is an evaluator-migrated successor")


def _evaluator_migrated(release: dict) -> bool:
    """True for a release whose incumbent tests are not candidate.base (INV-RELEASE-EVALUATOR-MIGRATION-001)."""
    policy = release.get("policy") or {}
    candidate = release.get("candidate") or {}
    return ("evaluator_migration" in release
            or policy.get("revision", candidate.get("base")) != candidate.get("base"))


def evaluator_successor_id(release_id: str) -> str:
    return digest({"evaluator_migration_of": release_id})


def reverification_successor_id(release_id: str) -> str:
    return digest({"reverify_of": release_id})


def environment_successor_id(release_id: str) -> str:
    return digest({"environment_reverify_of": release_id})


class EnvironmentReverificationRefused(ContractError):
    """INV-RELEASE-ENVIRONMENT-REVERIFY-001: a named refusal raised before any write."""

    def __init__(self, reason_code: str, message: str):
        self.reason_code = reason_code
        super().__init__(reason_code + ": " + message)


def expected_evaluator_pin(approval: dict) -> dict:
    """The resolver result an approval requires: E itself, a DIRECT child of the approved base."""
    return {"evaluator_revision": approval["evaluator_revision"], "parent": approval["base"],
            "base": approval["base"], "evaluator_tree": approval["evaluator_tree"],
            "paths": approval["paths"], "patch_sha256": approval["patch_sha256"]}


EVALUATOR_APPROVAL_KEYS = ("source_release_id", "base", "evaluator_revision", "evaluator_tree",
                           "patch_sha256", "paths", "evidence", "approved_by")


_HEX40, _HEX64 = re.compile(r"[0-9a-f]{40}"), re.compile(r"[0-9a-f]{64}")


def _require_evaluator_approval(approval, release_id: str) -> None:
    """The exact owner-authored approval shape of INV-RELEASE-EVALUATOR-MIGRATION-001."""
    require(isinstance(approval, dict) and set(approval) == set(EVALUATOR_APPROVAL_KEYS)
            and all(type(approval[k]) is str for k in EVALUATOR_APPROVAL_KEYS if k != "paths"),
            "Evaluator migration approval incomplete")
    require(bool(_HEX40.fullmatch(approval["evaluator_revision"]))
            and bool(_HEX40.fullmatch(approval["evaluator_tree"]))
            and bool(_HEX64.fullmatch(approval["patch_sha256"]))
            and approval["evidence"].startswith("sha256:")
            and bool(_HEX64.fullmatch(approval["evidence"][7:])), "Evaluator migration pin malformed")
    paths = approval["paths"]
    require(type(paths) is list and bool(paths) and all(type(p) is str for p in paths)
            and paths == sorted(set(paths)), "Evaluator paths must be a sorted non-empty list")
    require(all(p.startswith("tests/") and ".." not in p.split("/") for p in paths),
            "Evaluator migration may change only tests/")
    require(approval["source_release_id"] == release_id, "Evaluator approval names another release")
    require(bool(approval["base"]) and bool(approval["approved_by"]), "Evaluator migration approval incomplete")


ENVIRONMENT_APPROVAL_KEYS = ("kind", "source_release_id", "source_policy_hash", "old_plan_id",
                             "old_plan_sha256", "intent_id", "policy_id", "target_id", "lane",
                             "fix_evidence", "controller_revision", "approved_by")


def require_controller_code(resolved, expected: str) -> str:
    """INV-RELEASE-ENVIRONMENT-REVERIFY-001 creation preflight: the controller code the integration
    boundary RESOLVED (the runtime_revision SSOT of the running harness code, never a requester's
    string) must be a known revision equal to the approved one. Unknown code is
    `environment_reverification_controller_unavailable`, other code `..._controller_mismatch`; both
    are raised before any write, so the source, its intent and the one successor identity stay unused."""
    if type(resolved) is not str or not _HEX40.fullmatch(resolved):
        raise EnvironmentReverificationRefused("environment_reverification_controller_unavailable",
                                               "the running controller code is unknown")
    if resolved != expected:
        raise EnvironmentReverificationRefused("environment_reverification_controller_mismatch",
                                               "the running controller code is not the approved revision")
    return resolved


def _require_environment_approval(approval, release_id: str) -> None:
    """The exact conductor-authored approval shape of INV-RELEASE-ENVIRONMENT-REVERIFY-001."""
    if not (isinstance(approval, dict) and set(approval) == set(ENVIRONMENT_APPROVAL_KEYS)
            and all(type(approval[k]) is str and approval[k] for k in ENVIRONMENT_APPROVAL_KEYS)
            and approval["kind"] == "environment_reverification"):
        raise EnvironmentReverificationRefused("environment_reverification_approval_invalid",
                                               "environment reverification approval incomplete")
    if not (_HEX40.fullmatch(approval["controller_revision"])
            and _HEX64.fullmatch(approval["old_plan_sha256"])
            and approval["fix_evidence"].startswith("sha256:")
            and _HEX64.fullmatch(approval["fix_evidence"][7:])):
        raise EnvironmentReverificationRefused("environment_reverification_approval_invalid",
                                               "environment reverification approval malformed")
    if approval["source_release_id"] != release_id:
        raise EnvironmentReverificationRefused("environment_reverification_approval_invalid",
                                               "environment approval names another release")
