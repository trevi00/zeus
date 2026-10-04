"""S10 unit A5-3 (DESIGN-s10 §15a, §17b): `operations.collector_started`, the spool-drop gauges and the metrics-file split.

Spool directories are tmp paths with real `SpoolDirectory` health files and `.closed` markers; no provider or network.
"""
import json
import re
from types import SimpleNamespace

import pytest
from filelock import FileLock

from codex_harness.composition import monitor as composition_monitor
from codex_harness.composition import observation as builders
from codex_harness.observation.adapters.metrics_exposition import render
from codex_harness.observation.adapters.observation_spool import SpoolDirectory, run_lock_path
from codex_harness.observation.adapters.spool_facts import REASONS, SpoolFacts
from codex_harness.observation.application.catalog_observer import CatalogCheckingObserver
from codex_harness.observation.application.metrics_projector import MetricsProjector
from codex_harness.storage.adapters.memory_store import MemoryStore

NOW = 1_790_000_000
DROPPED = "zeus_observation_spool_dropped_records"
AVAILABLE = "zeus_observation_spool_facts_available"
UNREADABLE = "zeus_observation_spool_unreadable_health_records"
EVENT = "operations.collector_started"


class Recording:
    """The Observer surface `build_collector` uses; wrapped in the real catalog check."""

    def __init__(self, run, component, directory):
        self.process_run_id, self.component, self.directory = run, component, directory
        self.events, self.refused = [], []

    def emit(self, event_type, outcome, **fields):
        self.events.append((event_type, outcome, fields.get("attributes")))
        return {}

    def _refused(self, event_type, exc):
        self.refused.append((event_type, str(exc)))


def observer(directory, run="run-new", component="cli.desk"):
    inner = Recording(run, component, directory)
    return CatalogCheckingObserver(inner), inner


def health(directory, run, component="cli.desk", updated_at="2026-10-04T10:00:00+00:00", **counters):
    directory.write_health(run, {"process_run_id": run, "component": component, "updated_at": updated_at,
                                 "counters": counters})


def close(directory, run):
    marker = directory.root / "spool" / (run + ".closed")
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("{}\n", "utf-8")


@pytest.fixture
def spool(tmp_path):
    root = tmp_path / "observations"
    root.mkdir()
    builders._STARTED.clear()
    yield SpoolDirectory(root)
    builders._STARTED.clear()


def previous(spool, run="run-new", component="cli.desk"):
    return builders._previous_exit(spool, component, run)


def test_no_other_run_is_a_first_start_and_other_components_and_this_run_do_not_count(spool):
    assert previous(spool) == "first_start"
    health(spool, "run-new")
    health(spool, "run-other", component="cli.observe")
    assert previous(spool) == "first_start"


def test_a_closed_run_is_clean(spool):
    health(spool, "run-old")
    close(spool, "run-old")
    assert previous(spool) == "clean"


def test_a_run_whose_writer_is_alive_is_unknown(spool):
    health(spool, "run-old")
    with FileLock(str(run_lock_path(spool.root, "run-old")), is_singleton=False):
        assert previous(spool) == "unknown"


def test_a_run_that_neither_closed_nor_lives_is_crashed(spool):
    health(spool, "run-old")
    assert previous(spool) == "crashed"


def test_the_latest_run_by_updated_at_decides(spool):
    health(spool, "run-a", updated_at="2026-10-04T09:00:00+00:00")
    close(spool, "run-a")
    health(spool, "run-b", updated_at="2026-10-04T11:00:00+00:00")
    assert previous(spool) == "crashed"
    health(spool, "run-c", updated_at="2026-10-04T12:00:00+00:00")
    close(spool, "run-c")
    assert previous(spool) == "clean"


def test_an_unreadable_record_alone_is_unknown_and_a_readable_same_component_record_wins(spool):
    (spool.root / "health").mkdir()
    (spool.root / "health" / "run-bad.json").write_text("{not json", "utf-8")
    assert previous(spool) == "unknown"
    health(spool, "run-old")
    close(spool, "run-old")
    assert previous(spool) == "clean"


def test_the_collector_start_emits_once_per_process_run_and_never_without_an_observer(spool, tmp_path, monkeypatch):
    monkeypatch.setenv("ZEUS_REPOSITORY", str(tmp_path))
    monkeypatch.delenv("HARNESS_RUNTIME_DIR", raising=False)
    health(spool, "run-old")
    wrapped, inner = observer(spool)
    store = MemoryStore()
    builders.build_collector(store, wrapped)
    builders.build_collector(store, wrapped)
    assert inner.events == [(EVENT, "observed", {"collector": "cli.desk", "previous_exit": "crashed"})]
    assert inner.refused == []
    again, second = observer(spool, run="run-second", component="cli.observe")
    builders.build_collector(store, again)
    assert second.events == [(EVENT, "observed", {"collector": "cli.observe", "previous_exit": "first_start"})]
    builders.build_collector(store)
    assert len(inner.events) == len(second.events) == 1


def rows_by_metric(rows):
    return {row["metric"]: row for row in rows}


def test_the_dropped_gauge_sums_each_reason_over_readable_records(spool):
    health(spool, "run-a", dropped_spool_full=3, spool_failures=1, dropped_run_refused=2, refused=5, alerts_pending_dropped=7)
    health(spool, "run-b", dropped_spool_full=4)
    rows = rows_by_metric(SpoolFacts(spool.root).rows())
    assert rows[DROPPED]["type"] == "gauge" and rows[DROPPED]["labels"] == ["reason"]
    assert {tuple(s["labels"]): s["value"] for s in rows[DROPPED]["series"]} == {
        ("spool_full",): 7, ("append_failed",): 1, ("run_refused",): 2, ("refused",): 5, ("alerts_pending_dropped",): 7}
    assert [reason for reason, _ in REASONS] == ["spool_full", "append_failed", "run_refused", "refused", "alerts_pending_dropped"]
    assert [s["value"] for s in rows[AVAILABLE]["series"]] == [1]
    assert [s["value"] for s in rows[UNREADABLE]["series"]] == [0]
    assert "can decrease" in rows[DROPPED]["help"]
    (spool.root / "health" / "run-a.json").unlink()  # pruned: a gauge goes down
    after = rows_by_metric(SpoolFacts(spool.root).rows())
    assert {tuple(s["labels"]): s["value"] for s in after[DROPPED]["series"]}[("spool_full",)] == 4


def test_unreadable_records_are_counted_and_excluded(spool):
    health(spool, "run-a", refused=2)
    (spool.root / "health" / "run-bad.json").write_text("[1, 2", "utf-8")
    rows = rows_by_metric(SpoolFacts(spool.root).rows())
    assert [s["value"] for s in rows[UNREADABLE]["series"]] == [1]
    assert {tuple(s["labels"]): s["value"] for s in rows[DROPPED]["series"]}[("refused",)] == 2


def test_a_missing_directory_or_a_failed_read_is_unavailable_with_no_dropped_series(tmp_path, monkeypatch):
    rows = rows_by_metric(SpoolFacts(tmp_path / "absent").rows())
    assert [s["value"] for s in rows[AVAILABLE]["series"]] == [0]
    assert rows[DROPPED]["series"] == [] and rows[UNREADABLE]["series"] == []
    (tmp_path / "observations").mkdir()

    def boom(self):
        raise OSError("CANARY-secret")

    monkeypatch.setattr(SpoolDirectory, "read_health", boom)
    text = render(SpoolFacts(tmp_path / "observations").rows())
    assert f"{AVAILABLE} 0\n" in text and f"{DROPPED}{{" not in text and "CANARY" not in text


def test_no_identifier_reaches_any_label(spool):
    health(spool, "run-secret-id", component="cli.secret-component", refused=1)
    text = render(SpoolFacts(spool.root).rows())
    assert "run-secret-id" not in text and "secret-component" not in text and str(spool.root) not in text
    for line in text.splitlines():
        if not line.startswith("#") and "{" in line:
            assert re.search(r'reason="(spool_full|append_failed|run_refused|refused|alerts_pending_dropped)"', line), line
    assert f"# TYPE {DROPPED} gauge" in text and "_total" not in text


def seeded():
    store = MemoryStore()
    with store.transaction() as tx:
        MetricsProjector(providers=builders.PROVIDERS).apply(tx, [])
    return SimpleNamespace(store=store, org=None)


class Journal:
    def __init__(self):
        self.lines = []

    def write(self, event, **fields):
        self.lines.append((event, fields))


@pytest.fixture
def runtime(tmp_path):
    path = tmp_path / "runtime"
    (path / "observations").mkdir(parents=True)
    health(SpoolDirectory(path / "observations"), "run-a", refused=3)
    return path


def test_the_main_file_has_no_health_series_and_the_health_file_has_both(runtime):
    composition_monitor.publish_metrics(seeded(), runtime, Journal(), None, clock=lambda: NOW)
    main = (runtime / "zeus-metrics.prom").read_text("utf-8")
    other = (runtime / "zeus-metrics-health.prom").read_text("utf-8")
    assert "zeus_metrics_render" not in main
    assert f'{DROPPED}{{reason="refused"}} 3\n' in main and f"{AVAILABLE} 1\n" in main
    assert "zeus_metrics_render_success 1\n" in other
    assert f"zeus_metrics_render_last_success_timestamp_seconds {NOW}\n" in other


def test_a_render_failure_keeps_the_last_good_main_file_and_writes_health_zero(runtime, monkeypatch):
    journal = Journal()
    last = composition_monitor.publish_metrics(seeded(), runtime, journal, None, clock=lambda: NOW)
    good = (runtime / "zeus-metrics.prom").read_bytes()

    def boom(*args, **kwargs):
        raise RuntimeError("producer failed")

    monkeypatch.setattr(SpoolFacts, "rows", boom)
    assert composition_monitor.publish_metrics(seeded(), runtime, journal, last, clock=lambda: NOW + 60) == NOW
    assert (runtime / "zeus-metrics.prom").read_bytes() == good
    other = (runtime / "zeus-metrics-health.prom").read_text("utf-8")
    assert "zeus_metrics_render_success 0\n" in other and f"timestamp_seconds {NOW}\n" in other
    assert "zeus_metrics_render_success" not in good.decode()
    assert journal.lines == [("metrics_render_failed", {"error": "RuntimeError"})]


def test_collect_once_writes_all_three_files_and_the_main_file_has_the_spool_gauges(runtime, tmp_path, monkeypatch):
    import codex_harness.composition as composition
    from codex_harness.observation.adapters import collectors

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(composition_monitor, "settings", lambda: {})
    monkeypatch.setattr(composition, "build", seeded)
    monkeypatch.setattr(composition, "redis_url", lambda: "redis://127.0.0.1:1/0")
    monkeypatch.setattr(collectors, "collect", lambda *a, **k: {"sources": {"database": {"status": "ok", "error": None}}})
    monkeypatch.setattr(collectors, "lane_resolver", lambda dsn, **kwargs: None)
    monkeypatch.setattr(collectors, "lane_artifact_resolver", lambda: None)
    snapshot = runtime / "monitoring.json"
    try:
        composition_monitor.run_collector(SimpleNamespace(once=True), tmp_path, runtime, snapshot)
    finally:
        for handler in list(composition_monitor.logging.getLogger("zeus.monitor.collector").handlers):
            handler.close()
    for name in ("monitoring.json", "zeus-metrics.prom", "zeus-metrics-health.prom"):
        assert (runtime / name).is_file(), name
    main = (runtime / "zeus-metrics.prom").read_text("utf-8")
    assert f'{DROPPED}{{reason="refused"}} 3\n' in main and "zeus_metrics_render_success" not in main
    assert "zeus_metrics_render_success 1\n" in (runtime / "zeus-metrics-health.prom").read_text("utf-8")
    assert json.loads(snapshot.read_text("utf-8"))["sources"]
