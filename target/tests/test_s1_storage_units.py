"""S1 storage target properties that the differential scenarios cannot show by equality: the port
boundaries the target introduced (injected namespace and event journal), the owned buckets, and
resource bytes identical to SOURCE (REBUILD-DESIGN-v2 §2.7, §3.1 resources, §5.3 S1)."""

import hashlib
import os
import time
from pathlib import Path

import pytest

from codex_harness.storage import ports
from codex_harness.storage.adapters import message_schema, redis_bus
from codex_harness.storage.adapters.file_artifacts import FileArtifacts
from codex_harness.storage.adapters.maintenance import ArtifactMaintenance
from codex_harness.storage.adapters.memory_store import MemoryStore

ROOT = Path(__file__).resolve().parents[2]
TARGET_RESOURCES = Path(message_schema.__file__).resolve().parents[2] / "resources"
SOURCE_RESOURCES = ROOT / "src" / "codex_harness" / "resources"


class RecordingJournal:
    def __init__(self):
        self.calls = []

    def append(self, tx, event_id, body):
        self.calls.append((event_id, body["type"], body["reference"]))
        if tx.get("events", event_id) is None:
            tx.put("events", event_id, body)


def test_collection_appends_missing_references_through_the_owner_journal_in_the_same_unit(tmp_path):
    store, journal = MemoryStore(), RecordingJournal()
    arts = FileArtifacts(str(tmp_path / "artifacts"))
    kept = arts.put("kept", "fixture")["ref"]
    missing = "sha256:" + "d" * 64
    with store.transaction() as tx:
        tx.put("evidence", "e", {"a": kept, "b": missing})
    result = ArtifactMaintenance(store, arts, journal).collect(apply=True)
    assert result["integrity"] == "missing_references" and journal.calls == [
        (journal.calls[0][0], "artifact.reference_missing", missing)]
    with store.transaction() as tx:
        assert tx.get("maintenance", "latest")["missing_references"] == 1
        assert len(tx.scan("events")) == 1


def test_a_failing_journal_rolls_the_whole_collection_back(tmp_path):
    class Refusing:
        def append(self, tx, event_id, body):
            raise RuntimeError("journal refused")

    store = MemoryStore()
    arts = FileArtifacts(str(tmp_path / "artifacts"))
    old = arts.put("old unreferenced", "fixture")["ref"]
    stamp = time.time() - 30 * 86400
    os.utime(tmp_path / "artifacts" / (old[7:] + ".txt"), (stamp, stamp))
    with store.transaction() as tx:
        tx.put("evidence", "e", {"b": "sha256:" + "e" * 64})
    with pytest.raises(RuntimeError):
        ArtifactMaintenance(store, arts, Refusing()).collect(apply=True)
    with store.transaction() as tx:
        assert tx.get("maintenance", "latest") is None, "the result write is in the failed unit"


def test_the_bus_namespace_is_a_required_setting():
    with pytest.raises(TypeError):
        redis_bus.RedisBus("redis://localhost:6379")  # the missing namespace argument is the subject
    with pytest.raises(ValueError):
        redis_bus.RedisBus("redis://localhost:6379", "")


def test_storage_declares_its_owned_buckets_and_not_events():
    assert set(ports.OWNED_BUCKETS) == {"maintenance", "migration_runs", "knowledge_nodes", "knowledge_edges"}
    assert "events" not in ports.OWNED_BUCKETS


def test_message_schema_holds_only_the_six_w_half():
    assert not hasattr(message_schema, "validate_observation"), "observation schema belongs to S9"


def test_packaged_resources_are_the_source_bytes():
    def tree(root):
        return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(root.rglob("*")) if p.is_file() and "__pycache__" not in p.parts}

    assert tree(TARGET_RESOURCES) == tree(SOURCE_RESOURCES)
