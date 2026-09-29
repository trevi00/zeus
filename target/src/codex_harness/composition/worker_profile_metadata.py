"""Composition of the worker-profile metadata command: the context adapter's `main`, nothing else.

Layer: composition
Owns: the wiring only (the command reads three cwd-relative files and needs no store or setting)
Entry points: metadata_command
Contracts: INV-WORKER-PROFILE-001
"""
from __future__ import annotations

from codex_harness.context.adapters import worker_profile_metadata


def metadata_command():
    return worker_profile_metadata.main
