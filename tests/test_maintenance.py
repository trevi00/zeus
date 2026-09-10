import os
import time

from codex_harness.adapters.artifacts import FileArtifacts
from codex_harness.adapters.maintenance import ArtifactMaintenance
from codex_harness.adapters.store import MemoryStore
from codex_harness.application.scheduling import schedule_research
from codex_harness.application.service import Harness
from codex_harness.bootstrap import organization


def test_old_orphans_are_collected_but_transitive_evidence_and_recent_files_survive(tmp_path):
    artifacts = FileArtifacts(str(tmp_path / "artifacts"))
    store = MemoryStore()
    child = artifacts.put("evidence", "fixture")["ref"]
    parent = artifacts.put(child, "fixture")["ref"]
    orphan = artifacts.put("orphan", "fixture")["ref"]
    for path in artifacts.root.glob("*.txt"):
        old = time.time() - 14 * 86400
        os.utime(path, (old, old))
    recent = artifacts.put("recent", "fixture")["ref"]
    with store.transaction() as tx:
        tx.put("arbitrary-new-bucket", "root", {"reference": parent})
    maintenance = ArtifactMaintenance(store, artifacts)
    assert maintenance.collect()["files"] == 1
    assert artifacts.read(orphan) == "orphan"
    assert maintenance.collect(apply=True)["files"] == 1
    assert not (artifacts.root / (orphan[7:] + ".txt")).exists()
    assert all((artifacts.root / (ref[7:] + ".txt")).exists() for ref in (child, parent, recent))


def test_missing_referenced_evidence_is_reported_not_folded_into_a_healthy_result(tmp_path):
    # FA-007: unknown integrity never collapses into "healthy"; a lost reference stays visible.
    artifacts = FileArtifacts(str(tmp_path / "artifacts"))
    store = MemoryStore()
    lost = artifacts.put("lost evidence", "fixture")["ref"]
    kept = artifacts.put("kept evidence", "fixture")["ref"]
    orphan = artifacts.put("orphan", "fixture")["ref"]
    for path in artifacts.root.glob("*.txt"):
        old = time.time() - 14 * 86400
        os.utime(path, (old, old))
    with store.transaction() as tx:
        tx.put("approvals", "root", {"evidence_refs": [lost, kept]})
    (artifacts.root / (lost[7:] + ".txt")).unlink()
    maintenance = ArtifactMaintenance(store, artifacts)
    preview = maintenance.collect()
    assert preview["integrity"] == "missing_references" and preview["missing_references"] == 1
    assert preview["missing_reference_sample"] == [lost] and preview["files"] == 1
    with store.transaction() as tx:
        assert tx.scan("events") == [] and tx.get("maintenance", "latest") is None
    applied = maintenance.collect(apply=True)
    assert applied["integrity"] == "missing_references" and applied["files"] == 1
    assert not (artifacts.root / (orphan[7:] + ".txt")).exists()
    assert (artifacts.root / (kept[7:] + ".txt")).exists()
    with store.transaction() as tx:
        events = tx.scan("events")
        assert [e["reference"] for e in events] == [lost]
        assert tx.get("maintenance", "latest")["missing_references"] == 1
    maintenance.collect(apply=True)
    with store.transaction() as tx:
        assert len(tx.scan("events")) == 1, "one durable event per lost reference"
    healthy = ArtifactMaintenance(MemoryStore(), artifacts).collect()
    assert healthy["integrity"] == "complete" and healthy["missing_references"] == 0


def test_corrupted_referenced_evidence_aborts_collection_before_any_deletion(tmp_path):
    import pytest

    from codex_harness.domain.model import ContractError
    artifacts = FileArtifacts(str(tmp_path / "artifacts"))
    store = MemoryStore()
    referenced = artifacts.put("evidence", "fixture")["ref"]
    orphan = artifacts.put("orphan", "fixture")["ref"]
    for path in artifacts.root.glob("*.txt"):
        old = time.time() - 14 * 86400
        os.utime(path, (old, old))
    with store.transaction() as tx:
        tx.put("approvals", "root", {"evidence_refs": [referenced]})
    (artifacts.root / (referenced[7:] + ".txt")).write_text("tampered", encoding="utf-8")
    with pytest.raises(ContractError, match="corrupted"):
        ArtifactMaintenance(store, artifacts).collect(apply=True)
    assert (artifacts.root / (orphan[7:] + ".txt")).exists()
    with store.transaction() as tx:
        assert tx.get("maintenance", "latest") is None


def test_research_schedule_deduplicates_each_interval():
    service = Harness(MemoryStore(), organization())
    assert schedule_research(service, now=0) == 2
    assert schedule_research(service, now=1) == 0
    assert schedule_research(service, now=6 * 3600) == 2
