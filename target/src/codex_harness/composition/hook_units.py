"""The per-call store unit around the hook lifecycle (OWNER-DECISIONS-S10 #5).

Layer: composition
Owns: HookUnits
Does not own: the hook lifecycle (research), the store (storage)
Entry points: HookUnits
Contracts: OWNER-DECISIONS-S10 #5
"""

from __future__ import annotations


class HookUnits:
    """One store unit per call, as M7's Harness did: each method opens `store.transaction()` and passes it to
    the lifecycle method of the same name as `transaction=`. The same shape as the ported fixture
    `m7_intake._hook_unit`. Composition passes this as `HookCandidates.lifecycle`, as `HostHooks.hooks` (with
    `read_script`, C5) and as `Transports.hooks`."""

    def __init__(self, lifecycle, store):
        self.lifecycle, self.store = lifecycle, store

    def review(self, hook_id, actor, revision, spec_hash, passed, evidence_ref, **kwargs):
        with self.store.transaction() as tx:
            return self.lifecycle.review(hook_id, actor, revision, spec_hash, passed, evidence_ref,
                                         transaction=tx, **kwargs)

    def get_hook(self, hook_id, **kwargs):
        with self.store.transaction() as tx:
            return self.lifecycle.get_hook(hook_id, transaction=tx, **kwargs)

    def propose(self, hook_id, actor, spec, revision, **kwargs):
        with self.store.transaction() as tx:
            return self.lifecycle.propose(hook_id, actor, spec, revision, transaction=tx, **kwargs)

    def record_canary(self, hook_id, revision, spec_hash, checks, **kwargs):
        with self.store.transaction() as tx:
            return self.lifecycle.record_canary(hook_id, revision, spec_hash, checks, transaction=tx, **kwargs)

    def activate(self, hook_id, **kwargs):
        with self.store.transaction() as tx:
            return self.lifecycle.activate(hook_id, transaction=tx, **kwargs)

    def rollback(self, hook_id, reason, **kwargs):
        with self.store.transaction() as tx:
            return self.lifecycle.rollback(hook_id, reason, transaction=tx, **kwargs)

    def prepare_command(self, argv, platform, **kwargs):
        with self.store.transaction() as tx:
            return self.lifecycle.prepare_command(argv, platform, transaction=tx, **kwargs)

    def active_hooks(self, **kwargs):
        with self.store.transaction() as tx:
            return self.lifecycle.active_hooks(transaction=tx, **kwargs)
