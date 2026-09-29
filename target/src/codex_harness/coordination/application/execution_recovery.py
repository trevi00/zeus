"""Explicit recovery at the trusted local operator boundary; no human attestation.

Layer: application
Context: coordination
Owns: ExecutionRecovery.validate_decision and _related (M7 `application/execution_recovery.py`, moved ahead in S4
    unchanged: lead decision Option A, the guard ReviewDecisions runs before any provider and before committing)
Does not own: prepare/apply and the other recovery operations (S5), the related-evidence projection (M7
    `_related_checked`: decision_recovery.context and threshold reviews, S5/S8; injected as `related`)
Entry points: ExecutionRecovery, ExecutionRecovery.validate_decision
Contracts: INV-EXECUTION-IDENTITY-001, INV-RESEARCH-004
"""

from __future__ import annotations

from codex_harness.kernel.errors import ContractError, require
from codex_harness.kernel.ids import digest


class ExecutionRecovery:
    def __init__(self, store, organization, artifacts, *, related=None):
        # Target (§2.4): the related-evidence projection is injected; without it a recovered decision refuses.
        self.store, self.org, self.artifacts = store, organization, artifacts
        self._related_checked = related if related is not None else self._related_unavailable

    @staticmethod
    def _related_unavailable(tx, bucket, row):
        raise ContractError("Related recovery evidence projection is not wired")

    def _related(self, tx, bucket, row):
        try:
            return self._related_checked(tx, bucket, row)
        except ContractError:
            raise
        except (OSError, ValueError, KeyError, TypeError, AttributeError, IndexError, RecursionError) as exc:
            raise ContractError('Related recovery evidence unavailable or malformed') from exc

    def validate_decision(self, tx, row):
        """Recheck the recovered dependencies before spending an attempt or committing effects."""
        reference = row.get('recovery_receipt')
        budget = row.get('retry_budget')
        if not reference:
            require(not row.get('recovery_sequence') and not (isinstance(budget, dict) and budget.get('recovery_ref')),
                    'Decision recovery receipt missing')
            return
        require(isinstance(reference, str), 'Invalid decision recovery receipt reference')
        receipt = tx.get('execution_recoveries', reference)
        packet = receipt.get('packet') if isinstance(receipt, dict) else None
        require(isinstance(packet, dict) and packet.get('bucket') == 'decisions_pending'
                and packet.get('task_id') == row['id'] and receipt.get('id') == reference == digest(packet),
                'Decision recovery receipt missing or mismatched')
        previous = receipt.get('previous')
        require(isinstance(previous, dict) and type(previous.get('generation')) is int
                and type(previous.get('recovery_sequence', 0)) is int
                and isinstance(budget, dict) and budget.get('recovery_ref') == reference
                and row.get('recovery_sequence') == previous.get('recovery_sequence', 0) + 1
                and type(row.get('generation')) is int and row['generation'] > previous['generation'],
                'Decision recovery generation changed')
        require(digest(self._related(tx, 'decisions_pending', row)) == receipt.get('result_related_hash'),
                'Recovered decision dependencies changed')
