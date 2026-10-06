"""Composition of the pinned frontend-checks command: the observation capability with the bounded capture bound.

Layer: composition
Owns: the wiring only (D3/D3.1: the capture is `evidence.adapters.evidence_inspection._capture` with the host_os `ProcessTree` class itself, which reproduces the capture
M7's module-level import gave `observe`; the command reads no store and no setting)
Entry points: frontend_checks_command
Contracts: INV-EVIDENCE-001
"""
from __future__ import annotations

import functools

from codex_harness.evidence.adapters.evidence_inspection import _capture
from codex_harness.host_os.adapters.process_tree import ProcessTree
from codex_harness.observation.adapters import monitor_frontend_checks


def frontend_checks_command():
    return functools.partial(monitor_frontend_checks.main, capture=functools.partial(_capture, process_tree=ProcessTree))
