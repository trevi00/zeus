"""S10 W1/W2: composition.observation builders (INV-OBSERVATION-001, OWNER-DECISIONS-S10 #18(a))."""
import pytest

from codex_harness.composition import observation as builders
from codex_harness.execution.domain.provider_stream import ClaudeStream, CodexStream
from codex_harness.kernel.policy import POLICY
from codex_harness.observation.application.catalog_observer import CatalogCheckingObserver
from codex_harness.observation.application.metrics_projector import MetricsProjector
from codex_harness.observation.application.observations import Observer
from codex_harness.storage.adapters.memory_store import MemoryStore

LEASE = {"id": "task-1", "generation": 1, "attempt": 1, "agent": "worker:implementation"}
DURATION = "zeus_model_invocation_duration_seconds"


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setenv("ZEUS_REPOSITORY", str(tmp_path))
    monkeypatch.delenv("HARNESS_RUNTIME_DIR", raising=False)
    return tmp_path


def spooled_lines(root):
    return [line for path in sorted((root / "spool").glob("**/*")) if path.is_file()
            for line in path.read_text("utf-8").splitlines()]


def test_observation_root_is_the_runtime_observations_dir(repo):
    assert builders.observation_root() == repo.resolve() / ".runtime" / "observations"


def test_build_observer_wraps_a_spooling_observer(repo):
    store = MemoryStore()
    observer = builders.build_observer(store, "unit", role="r")
    assert isinstance(observer, CatalogCheckingObserver)
    inner = observer._observer
    assert isinstance(inner, Observer)
    assert inner.spool.root == builders.observation_root()
    assert inner.spool.max_bytes == POLICY.observation_spool_bytes
    assert inner.directory.root == builders.observation_root()
    assert inner.role == "r" and inner.store is store
    assert observer.process_run_id == inner.process_run_id  # forwarded attribute
    assert callable(observer.audit_system) and observer.close() is None  # forwarded methods


def test_build_observer_root_override(repo, tmp_path):
    other = tmp_path / "lane" / "observations"
    observer = builders.build_observer(MemoryStore(), "unit", root=other)
    assert observer._observer.spool.root == other


def test_out_of_enum_catalog_attribute_is_refused_without_spooling_it(repo):
    root = builders.observation_root()
    observer = builders.build_observer(MemoryStore(), "unit")
    result = observer.emit("development.role_dispatch_decided", "blocked",
                           attributes={"role": "r", "provider": "p", "decision": "bogus",
                                       "decision_reason": "x", "latency_seconds": 0.0})
    assert result is None
    lines = spooled_lines(root)
    assert not any("development.role_dispatch_decided" in line and "bogus" in line for line in lines)
    assert observer._observer.counters["refused"] == 1
    observer.close()


def test_provider_finished_is_collected_into_the_histogram_once(repo):
    store = MemoryStore()
    observer = builders.build_observer(store, "unit")
    execution = observer.for_lease(LEASE, provider=ClaudeStream.identity)
    assert observer.emit("development.provider_finished", "succeeded", execution=execution,
                         attributes={"invocation_outcome": "accepted", "elapsed_seconds": 5.0}) is not None
    collector = builders.build_collector(store, observer)
    assert collector.collect()["inserted"] >= 1
    collector.collect()
    with store.transaction() as tx:
        rows = MetricsProjector(providers=builders.PROVIDERS).snapshot(tx)
    [row] = [r for r in rows if r["metric"] == DURATION]
    [item] = row["series"]
    assert list(item["labels"]) == [ClaudeStream.identity, "accepted"]
    assert item["value"]["count"] == 1 and item["value"]["sum"] == 5.0


def test_providers_are_the_two_stream_identities():
    assert builders.PROVIDERS == ("claude-code-cli", "codex-app-server")
    assert builders.PROVIDERS == (ClaudeStream.identity, CodexStream.identity)
