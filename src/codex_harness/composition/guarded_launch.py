"""Composition of the guarded child launch: the spawn chokepoint and the process tree bound to the coordination
adapters (DESIGN-s6 §6).

Layer: composition
Owns: the wiring only
Entry points: guarded_spawn, guardian_command, guard_function
Contracts: INV-CONTINUATION-001
"""
from __future__ import annotations

from functools import partial

from codex_harness.coordination.adapters import guarded_launch
from codex_harness.host_os.adapters.process_groups import ChokepointProcesses
from codex_harness.host_os.adapters.process_tree import ProcessTree, TreeOwnershipError, TreeOwnershipLeak


def guarded_spawn() -> guarded_launch.GuardedChildLauncher:
    """The one guarded child spawn every launcher uses."""
    return guarded_launch.GuardedChildLauncher(ChokepointProcesses())


def guard_function():
    """`guard` with the owned process tree seams bound (the guardian side)."""
    return partial(guarded_launch.guard, spawn=ProcessTree.spawn, leak=TreeOwnershipLeak,
                   ownership=TreeOwnershipError)


def guardian_command():
    """The guardian process's `main` with the owned process tree seams bound."""
    return partial(guarded_launch.main, spawn=ProcessTree.spawn, leak=TreeOwnershipLeak,
                   ownership=TreeOwnershipError)
