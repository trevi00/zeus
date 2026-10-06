"""S8 pilot 72: intake's `ProgressCandidates` reads and writes exactly M7's `portfolio_investigations` row (R-ap1)."""
from codex_harness.intake.application.progress_candidates import ProgressCandidates
from codex_harness.storage.adapters.memory_store import MemoryStore


def test_progress_candidate_reads_and_records_the_row_unchanged():
    store, owner = MemoryStore(), ProgressCandidates()
    row = {"id": "audit-progress-x", "kind": "audit_progress", "windows": [1, 2]}
    with store.transaction() as tx:
        assert owner.progress_candidate(tx, "audit-progress-x") is None
        assert owner.record_progress_candidate(tx, "audit-progress-x", row) is None
    with store.transaction() as tx:
        assert owner.progress_candidate(tx, "audit-progress-x") == row
        assert tx.get("portfolio_investigations", "audit-progress-x") == row
        owner.record_progress_candidate(tx, "audit-progress-x", {**row, "windows": [1, 2, 3]})
    with store.transaction() as tx:
        assert tx.get("portfolio_investigations", "audit-progress-x")["windows"] == [1, 2, 3]
