"""The incumbent delivery TARGET state files for the owner canary: bounded reads, atomic replacements (INV-OWNER-ACTIONS-001).

Layer: adapters
Context: delivery
Owns: `TargetFiles` (the startup receipt, the plan's canary request and receipt files)
Does not own: the file helpers and target paths (`delivery.adapters.host_delivery`), the owner-actions files port (coordination: `TargetFiles` implements it structurally and imports nothing of coordination)
Entry points: TargetFiles
Contracts: INV-OWNER-ACTIONS-001, INV-HOST-DELIVERY-VERIFY-001

S7 named transcription of M7 `adapters/owner_actions.py` (SOURCE e38aa722, A/evidence/rebuild/s7/owner-actions-adapters/transcribe.py): `TargetFiles` verbatim, placed with the delivery target state files (a coordination adapter may not import delivery adapters); only the import home changes.
"""
from __future__ import annotations

from codex_harness.delivery.adapters.host_delivery import (
    RECEIPT_FILE,
    HostTargetBase,
    _read_json,
    _write_json,
    canary_receipt_file,
    canary_request_file,
)


class TargetFiles:
    """The incumbent target state files; reads are bounded, writes are atomic replacements. The owner
    canary request and receipt are the files of ONE plan (`canary_request_file`/`canary_receipt_file`)."""

    @staticmethod
    def startup(target: dict):
        return _read_json(HostTargetBase.path(target, RECEIPT_FILE))

    @staticmethod
    def request(target: dict, plan_id: str):
        return _read_json(HostTargetBase.path(target, canary_request_file(plan_id)))

    @staticmethod
    def write_request(target: dict, plan_id: str, document: dict) -> None:
        HostTargetBase.state_dir(target).mkdir(parents=True, exist_ok=True)
        _write_json(HostTargetBase.path(target, canary_request_file(plan_id)), document)

    @staticmethod
    def receipt(target: dict, plan_id: str):
        """The plan's owner canary receipt, read only (the canary recovery refuses when one exists). A file
        that exists but cannot be read as a JSON object is an UNKNOWN receipt, never an absent one: it is
        returned as a non-None marker so the recovery refuses rather than ignoring it."""
        path = HostTargetBase.path(target, canary_receipt_file(plan_id))
        if not path.exists():
            return None
        document = _read_json(path)
        return document if isinstance(document, dict) else {"unreadable": True}

    @staticmethod
    def write_receipt(target: dict, plan_id: str, document: dict) -> None:
        _write_json(HostTargetBase.path(target, canary_receipt_file(plan_id)), document)
