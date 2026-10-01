"""Rollback R0/R1 eligibility and Windows retirement gate C (SPEC §10, §1, A8).

Each gate evaluates an evidence document the operator or coordinator assembles from receipts; it
returns every unmet condition rather than the first one and never performs the rollback or the
deletion itself. Missing or non-boolean evidence is unmet: an unknown never becomes a pass.
"""
from __future__ import annotations

import re

HEX_REF = re.compile(r"sha256:[0-9a-f]{64}")
PROTECTED = ("flexday-pg", "/.claude", "/.codex", "\\.claude", "\\.codex", ".gitconfig")


def _true(evidence: dict, key: str, reasons: list[str]) -> None:
    if evidence.get(key) is not True:
        reasons.append(f"{key}_not_confirmed")


def _zero(evidence: dict, key: str, reasons: list[str]) -> None:
    if evidence.get(key) != 0 or type(evidence.get(key)) is not int:
        reasons.append(f"{key}_not_zero")


def rollback_r0(evidence: dict) -> dict:
    """R0: target has made no authoritative write. Restore the untouched source snapshot/runtime."""
    reasons: list[str] = []
    writes = evidence.get("target_authoritative_writes")
    if type(writes) is int and writes > 0:
        return {"gate": "R0", "eligible": False, "reasons": ["target_has_written_use_r1"]}
    _zero(evidence, "target_authoritative_writes", reasons)
    _zero(evidence, "target_external_effects", reasons)
    _true(evidence, "target_fenced", reasons)
    _zero(evidence, "target_writer_count", reasons)
    sealed, current = evidence.get("source_sealed_digest"), evidence.get("source_current_digest")
    if not (isinstance(sealed, str) and HEX_REF.fullmatch(sealed)):
        reasons.append("source_sealed_digest_missing")
    elif sealed != current:
        reasons.append("source_changed_since_seal")
    _true(evidence, "source_runtime_pointer_unchanged", reasons)
    _true(evidence, "source_single_owner_confirmed", reasons)
    return {"gate": "R0", "eligible": not reasons, "reasons": reasons}


def rollback_r1(evidence: dict) -> dict:
    """R1: target has written. Reverse-migrate the target's latest state into a NEW isolated Windows
    restore; booting the old Windows snapshot is refused because it loses writes and can repeat
    external effects."""
    reasons: list[str] = []
    if evidence.get("target_reachable") is not True:
        return {"gate": "R1", "eligible": False,
                "reasons": ["target_unreachable_close_both_admissions_and_report_incident"]}
    for key in ("target_admission_stopped", "target_fenced", "reverse_file_manifest_match",
                "reverse_pg_match", "reverse_redis_match", "reverse_mapping_roundtrip_verified",
                "windows_runtime_binding_receipt", "single_owner_resume_planned"):
        _true(evidence, key, reasons)
    _zero(evidence, "target_writer_count", reasons)
    _zero(evidence, "unknown_external_effects", reasons)
    _zero(evidence, "windows_incompatible_names", reasons)
    _zero(evidence, "case_collisions", reasons)
    restore, original = evidence.get("windows_restore_db_identity"), evidence.get("original_snapshot_identity")
    if not isinstance(restore, str) or not restore:
        reasons.append("windows_restore_db_identity_missing")
    elif restore == original:
        reasons.append("old_windows_snapshot_reuse_refused")
    effects = evidence.get("external_effects")
    if not isinstance(effects, list):
        reasons.append("external_effects_not_listed")
    else:
        for effect in effects:
            if not isinstance(effect, dict) or effect.get("disposition") not in {"reconciled_no_rerun",
                                                                                "not_applicable"}:
                reasons.append(f"external_effect_unreconciled:{(effect or {}).get('id')}")
    return {"gate": "R1", "eligible": not reasons, "reasons": reasons}


def _protected(path: str) -> bool:
    text = path.replace("\\", "/").casefold()
    return any(marker.replace("\\", "/").casefold() in text for marker in PROTECTED)


def retirement_gate_c(evidence: dict) -> dict:
    """Gate C: only after A and B acceptance, Windows-free reference resolution and a verified
    backup restore may Zeus-owned Windows components be disabled/removed, each from an exact
    deletion-manifest item. Shared/other-project and user auth/global configuration are refused."""
    reasons: list[str] = []
    if evidence.get("completion_state") != "autonomous_qualified":
        reasons.append("b_acceptance_missing")
    _true(evidence, "a_accepted", reasons)
    _true(evidence, "b_accepted", reasons)
    _true(evidence, "backup_restore_verified", reasons)
    _true(evidence, "server_references_resolved_without_windows", reasons)
    _true(evidence, "windows_observer_disabled", reasons)
    _zero(evidence, "unresolved_windows_references", reasons)
    items = evidence.get("deletion_manifest")
    blocked_items = []
    if not isinstance(items, list) or not items:
        reasons.append("deletion_manifest_missing")
        items = []
    for item in items:
        problems = []
        if not isinstance(item, dict):
            blocked_items.append({"item": item, "problems": ["not_an_object"]})
            continue
        path = item.get("absolute_path")
        if not isinstance(path, str) or not re.match(r"^([A-Za-z]:[\\/]|/)", path):
            problems.append("absolute_path")
        elif _protected(path) or item.get("kind") == "shared" or item.get("owner") != "zeus":
            problems.append("protected_or_not_zeus_owned")
        if not HEX_REF.fullmatch(str(item.get("prior_sha256", ""))):
            problems.append("prior_hash")
        if item.get("dirty_ignored_checked") is not True:
            problems.append("dirty_ignored_not_checked")
        if item.get("server_copy_verified") is not True:
            problems.append("server_copy_not_verified")
        if item.get("kind") == "claude_harness_original" and item.get("absorption_confirmed") is not True:
            problems.append("original_harness_absorption_unconfirmed")
        if problems:
            blocked_items.append({"path": path, "problems": problems})
    if blocked_items:
        reasons.append("deletion_items_blocked")
    return {"gate": "C", "eligible": not reasons, "reasons": reasons, "blocked_items": blocked_items,
            "action": "none_performed"}
