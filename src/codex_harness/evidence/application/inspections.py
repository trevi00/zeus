"""The read an evidence consumer requires: one inspection row that is all_checked for the named execution.

Layer: application
Context: evidence
Owns: the read of bucket evidence_inspections (no write here)
Does not own: running inspections and writing their rows (M7 `EvidenceInspections.inspect`, S8)
Entry points: EvidenceRecords.require_all_checked
Contracts: INV-EVIDENCE-001

M7 `EvidenceInspections.require_all_checked` (SOURCE e38aa722, `application/evidence_inspection.py`), moved ahead in
S5 verbatim (Option A, DESIGN-s5 §P): coordination's Operation evidence gate consumes it through its `EvidenceRecords`
port; S8 moves the rest of the module and keeps this read.
"""

from __future__ import annotations

from codex_harness.kernel.errors import require

BUCKET = 'evidence_inspections'


class EvidenceRecords:
    """Stateless read over the caller's transaction; its constructor takes nothing."""

    def require_all_checked(self, tx, inspection_id, *, policy_hash=None, binding=None):
        """The consumer names the policy (and optionally the execution) it requires; a row for another is refused."""
        row = tx.get(BUCKET, inspection_id)
        require(row is not None, 'Evidence inspection missing')
        require(policy_hash is None or row['policy_hash'] == policy_hash, 'Evidence inspection was made under another policy')
        require(binding is None or all(row['binding'].get(k) == v for k, v in binding.items()),
                'Evidence inspection is bound to another execution or revision')
        require(row['verdict'] == 'all_checked', 'Evidence inspection is ' + row['verdict'] + ': '
                + ', '.join(f"{state}={count}" for state, count in row['denominator'].items() if count and state != 'claims'))
        return row
