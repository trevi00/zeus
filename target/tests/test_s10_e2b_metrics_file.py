"""S10 unit E2b (rule R-e2b, DESIGN-s10 §15 (c)): the monitor collector's `zeus-metrics.prom` and `zeus-metrics-health.prom`.

Projected rows are seeded through the real `MetricsProjector`; the clock is fixed; the runtime directory is a tmp path.
"""
import json
import os
import re
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from codex_harness.composition import monitor as composition_monitor
from codex_harness.composition.observation import PROVIDERS
from codex_harness.observation.adapters.metrics_exposition import render
from codex_harness.observation.adapters.queue_facts import QueueFacts
from codex_harness.observation.application.metrics_projector import MetricsProjector
from codex_harness.observation.domain.feature_registry import FEATURES, instrumented_rows
from codex_harness.observation.domain.metric_families import FAMILIES
from codex_harness.storage.adapters.memory_store import MemoryStore

NOW = 1_790_000_000
FEATURE_USES = "zeus_feature_uses_total"
MAPPED = {"category": "development", "event_type": "development.provider_finished",
          "attributes": {"invocation_outcome": "accepted", "elapsed_seconds": 1.0},
          "execution": {"provider": "codex-app-server"}}


def seeded():
    store = MemoryStore()
    with store.transaction() as tx:
        MetricsProjector(providers=PROVIDERS).apply(tx, [MAPPED, MAPPED])
    return SimpleNamespace(store=store, org=None)


def producer_rows(service, now=NOW):
    with service.store.transaction() as tx:
        rows = MetricsProjector(providers=PROVIDERS).snapshot(tx)
    rows += instrumented_rows()
    rows += QueueFacts(service.store, now=lambda: datetime.fromtimestamp(now, timezone.utc)).rows()
    return rows


def health(success, last):
    return composition_monitor._health_rows(success, last)


def test_the_file_is_the_producers_renders_only_and_is_deterministic():
    # S10 A5-3: DESIGN-s10 §15a
    service = seeded()
    text = composition_monitor.render_metrics(service, clock=lambda: NOW)
    assert text == render(producer_rows(service))
    assert text == composition_monitor.render_metrics(service, clock=lambda: NOW)
    assert f'{FEATURE_USES}{{feature="model_invocation"}} 2\n' in text
    assert text.count("zeus_feature_instrumented{") == len(FEATURES)
    assert "# TYPE zeus_queue_depth gauge" in text
    assert "zeus_metrics_render_success" not in text and "zeus_metrics_render_last_success" not in text
    assert " " + str(NOW * 1000) not in text


def test_an_empty_store_renders():
    text = composition_monitor.render_metrics(SimpleNamespace(store=MemoryStore(), org=None), clock=lambda: NOW)
    assert "zeus_metrics_render_success" not in text and FEATURE_USES not in text  # S10 A5-3: DESIGN-s10 §15a


def test_no_series_or_label_outside_the_catalog():
    text = composition_monitor.render_metrics(seeded(), clock=lambda: NOW)
    queue = {row["metric"]: row["labels"] for row in QueueFacts(MemoryStore(), now=lambda: datetime.fromtimestamp(NOW, timezone.utc)).rows()}
    known = {name: list(family.labels) for name, family in FAMILIES.items()}
    known.update(queue)
    known["zeus_feature_instrumented"] = ["feature"]
    samples = [line for line in text.splitlines() if line and not line.startswith("#")]
    assert samples
    for line in samples:
        match = re.fullmatch(r'([a-z_]+?)(?:_bucket|_sum|_count)?(?:\{(.*)\})? \S+', line)
        assert match, line
        [base] = [n for n in known if re.match(re.escape(n) + r"(_bucket|_sum|_count)?[{ ]", line)]
        names = re.findall(r'(\w+)="', match.group(2) or "")
        assert [n for n in names if n != "le"] == known[base], line
        if base in (FEATURE_USES, "zeus_feature_instrumented"):
            assert re.search(r'feature="(\w+)"', line).group(1) in FEATURES


@pytest.fixture
def runtime(tmp_path):
    path = tmp_path / "runtime"
    path.mkdir()
    return path


class Journal:
    def __init__(self):
        self.lines = []

    def write(self, event, **fields):
        self.lines.append((event, fields))


def test_publish_writes_the_metrics_and_health_files_after_a_success(runtime):
    journal = Journal()
    last = composition_monitor.publish_metrics(seeded(), runtime, journal, None, clock=lambda: NOW)
    assert last == NOW and journal.lines == []
    assert (runtime / "zeus-metrics.prom").read_text("utf-8") == composition_monitor.render_metrics(seeded(), clock=lambda: NOW)
    assert (runtime / "zeus-metrics-health.prom").read_text("utf-8") == render(health(True, NOW))
    assert sorted(p.name for p in runtime.iterdir()) == ["zeus-metrics-health.prom", "zeus-metrics.prom"]


def boom(*args, **kwargs):
    raise RuntimeError("producer failed CANARY-secret")


def test_a_producer_failure_keeps_the_last_good_file_and_writes_health_zero(runtime, monkeypatch):
    journal = Journal()
    last = composition_monitor.publish_metrics(seeded(), runtime, journal, None, clock=lambda: NOW)
    good = (runtime / "zeus-metrics.prom").read_bytes()
    monkeypatch.setattr(MetricsProjector, "snapshot", boom)
    later = composition_monitor.publish_metrics(seeded(), runtime, journal, last, clock=lambda: NOW + 60)
    assert later == NOW
    assert (runtime / "zeus-metrics.prom").read_bytes() == good
    assert (runtime / "zeus-metrics-health.prom").read_text("utf-8") == render(health(False, NOW))
    assert journal.lines == [("metrics_render_failed", {"error": "RuntimeError"})]
    assert not list(runtime.glob("*.tmp"))


def test_a_failure_before_any_success_writes_health_without_a_timestamp(runtime, monkeypatch):
    monkeypatch.setattr(MetricsProjector, "snapshot", boom)
    assert composition_monitor.publish_metrics(seeded(), runtime, Journal(), None, clock=lambda: NOW) is None
    assert not (runtime / "zeus-metrics.prom").exists()
    health_text = (runtime / "zeus-metrics-health.prom").read_text("utf-8")
    assert "zeus_metrics_render_success 0\n" in health_text and "last_success_timestamp" not in health_text


def test_a_crash_between_write_and_replace_leaves_the_old_file_intact(runtime, monkeypatch):
    composition_monitor.write_metrics(runtime, "old\n")

    def crash(source, target):
        raise OSError("crash before replace")

    monkeypatch.setattr(os, "replace", crash)
    with pytest.raises(OSError):
        composition_monitor.write_metrics(runtime, "new\n")
    assert (runtime / "zeus-metrics.prom").read_text("utf-8") == "old\n"
    monkeypatch.undo()
    composition_monitor.write_metrics(runtime, "new\n")
    assert (runtime / "zeus-metrics.prom").read_text("utf-8") == "new\n"
    assert not list(runtime.glob("*.tmp"))


@pytest.fixture
def collector(monkeypatch, tmp_path):
    import codex_harness.composition as composition
    from codex_harness.observation.adapters import collectors

    runtime = tmp_path / "runtime"
    runtime.mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(composition_monitor, "settings", lambda: {})
    monkeypatch.setattr(composition, "build", seeded)
    monkeypatch.setattr(composition, "redis_url", lambda: "redis://127.0.0.1:1/0")
    monkeypatch.setattr(collectors, "collect", lambda *a, **k: {"sources": {"database": {"status": "ok", "error": None}}})
    monkeypatch.setattr(collectors, "lane_resolver", lambda dsn, **kwargs: None)
    monkeypatch.setattr(collectors, "lane_artifact_resolver", lambda: None)
    yield SimpleNamespace(runtime=runtime, snapshot=runtime / "monitoring.json", root=tmp_path)
    for handler in list(composition_monitor.logging.getLogger("zeus.monitor.collector").handlers):
        handler.close()


def events(runtime):
    return [json.loads(line) for line in (runtime / "monitor-collector.log").read_text("utf-8").splitlines()]


def test_collect_once_writes_all_three_files(collector):
    composition_monitor.run_collector(SimpleNamespace(once=True), collector.root, collector.runtime, collector.snapshot)
    for name in ("monitoring.json", "zeus-metrics.prom", "zeus-metrics-health.prom"):
        assert (collector.runtime / name).is_file(), name
    assert not list(collector.runtime.glob("*.tmp"))
    assert "zeus_metrics_render_success" not in (collector.runtime / "zeus-metrics.prom").read_text("utf-8")  # S10 A5-3: DESIGN-s10 §15a
    assert "zeus_metrics_render_success 1\n" in (collector.runtime / "zeus-metrics-health.prom").read_text("utf-8")
    assert [e["event"] for e in events(collector.runtime)] == ["startup", "source_state", "shutdown"]


def test_a_metrics_failure_never_stops_the_collector_or_changes_monitoring_json(collector, monkeypatch):
    monkeypatch.setattr(MetricsProjector, "snapshot", boom)
    composition_monitor.run_collector(SimpleNamespace(once=True), collector.root, collector.runtime, collector.snapshot)
    assert json.loads(collector.snapshot.read_text("utf-8")) == {"sources": {"database": {"status": "ok", "error": None}}}
    assert not (collector.runtime / "zeus-metrics.prom").exists()
    assert "zeus_metrics_render_success 0\n" in (collector.runtime / "zeus-metrics-health.prom").read_text("utf-8")
    log = events(collector.runtime)
    assert ("metrics_render_failed", "RuntimeError") in [(e["event"], e.get("error")) for e in log]
    assert log[-1]["event"] == "shutdown" and log[-1]["reason"] == "once"
