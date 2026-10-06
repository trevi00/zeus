"""Composition of the launched delivery service: the child process's own wiring (DESIGN-s7 adapters-move §9.2).

Layer: composition
Owns: the wiring only (host settings -> effective worker image, the worker profile adapter -> profile digest, then
    the moved `serve`)
Entry points: serve_service
Contracts: INV-HOST-DELIVERY-001
"""
from __future__ import annotations

from codex_harness.composition.configuration import settings
from codex_harness.context.adapters import worker_profile
from codex_harness.delivery.adapters import host_delivery


def serve_service(state_dir: str, max_seconds: int) -> int:
    try:
        host = settings()
    except Exception:
        # M7 `_host_settings`: a malformed host configuration invents none; the receipt then carries no image.
        host = {}
    return host_delivery.serve(state_dir, max_seconds, image=host_delivery.effective_worker_image(host),
                               profile_digest=host_delivery.effective_profile_digest(worker_profile))
