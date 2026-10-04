"""S10 unit C4: the bus/observer roots flush, send, observe and the online doctor behind `entry.cli.main` (DESIGN-s10 §3 C4).

Parity with M7 is the `entry.cli_bus.pgredis` compare family; these tests cover what it cannot with a MemoryStore and a
fake bus: the Observer `flush` builds (a CatalogCheckingObserver, closed), the ProjectingStore `observe collect` runs
over, and the dispatch table.
"""

import ast
import json
import sys
from pathlib import Path
from types import SimpleNamespace

from codex_harness import composition
from codex_harness.composition import cli_bus
from codex_harness.composition import observation as observation_composition
from codex_harness.entry import cli
from codex_harness.observation.adapters.observation_spool import FileSpool, SpoolDirectory
from codex_harness.observation.application.catalog_observer import CatalogCheckingObserver
from codex_harness.observation.application.metrics_projector import METRICS_BUCKET, MetricsProjector
from codex_harness.observation.application.observations import EVENT_BUCKET, Observer
from codex_harness.observation.domain.observation import new_process_run_id
from codex_harness.routing.adapters.organization_source import packaged_organization
from codex_harness.storage.adapters.memory_store import MemoryStore

ROOTS = {"flush", "send", "observe", "doctor"}


def run_main(monkeypatch, capsys, *argv):
    monkeypatch.setattr(sys, "argv", ["zeus", *argv])
    try:
        cli.main()
        code = 0
    except SystemExit as exc:
        code = exc.code
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def serve_memory_store(monkeypatch, tmp_path):
    store = MemoryStore()
    monkeypatch.setattr(composition, "build", lambda: composition.ServiceHandle(store, packaged_organization()))
    monkeypatch.setattr(observation_composition, "observation_root", lambda: tmp_path / "observations")
    return store


def test_the_dispatch_table_composes_the_bus_roots():
    tree = ast.parse(Path(cli.__file__).read_text(encoding="utf-8"))
    tables = [{k.value for k in node.keys if isinstance(k, ast.Constant)}
              for node in ast.walk(tree) if isinstance(node, ast.Dict)]
    assert any(ROOTS <= table for table in tables)


def test_flush_builds_a_catalog_observer_and_closes_it(monkeypatch, capsys, tmp_path):
    serve_memory_store(monkeypatch, tmp_path)
    built, closed = [], []
    original = observation_composition.build_observer

    def recording(store, component, role=None, root=None):
        observer = original(store, component, role, root)
        built.append((observer, component))
        real_close = observer.close
        observer.close = lambda: (closed.append(observer), real_close())[1]
        return observer

    monkeypatch.setattr(observation_composition, "build_observer", recording)
    monkeypatch.setattr(cli_bus, "bus", lambda: SimpleNamespace())
    code, out, err = run_main(monkeypatch, capsys, "flush")
    assert (code, err) == (0, "")
    assert json.loads(out)["examined"] == 0
    [(observer, component)] = built
    assert isinstance(observer, CatalogCheckingObserver) and component == "cli.flush"
    assert closed == [observer]


def test_observe_collect_runs_over_the_projecting_store(monkeypatch, capsys, tmp_path):
    store = serve_memory_store(monkeypatch, tmp_path)
    root = tmp_path / "observations"
    producer = Observer(store, FileSpool(root, new_process_run_id(), max_bytes=1 << 20, fsync=False),
                        component="unit", directory=SpoolDirectory(root), alert_window_seconds=300)
    assert producer.emit("general.message_quarantined", "observed",
                         attributes={"outbox_id": "m1", "reason": "bad", "quarantine_id": "q1"}) is not None
    code, out, err = run_main(monkeypatch, capsys, "observe", "collect")
    assert (code, err) == (0, "")
    # S10 A5-3: the cli.observe Collector start emits operations.collector_started (DESIGN-s10 §17b)
    assert json.loads(out)["inserted"] == 2
    with store.transaction() as tx:
        assert len(tx.scan(EVENT_BUCKET)) == 2
        assert tx.get(METRICS_BUCKET, "family:zeus_metrics_projected_observations_total") is not None
        rows = MetricsProjector(providers=observation_composition.PROVIDERS).snapshot(tx)
    [projected] = [r for r in rows if r["metric"] == "zeus_metrics_projected_observations_total"]
    assert {tuple(s["labels"]): s["value"] for s in projected["series"]} == {("general",): 1, ("operations",): 1}
