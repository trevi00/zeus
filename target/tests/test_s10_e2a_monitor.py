"""S10 unit E2a: the `zeus-monitor` process (collect | web | desk), `entry.http.desk` and the production `CollectorPorts` (rule R-e2).

No network, no docker, no Redis, no real listener: `collect`, `build` and `serve` are replaced where a process would start one. The ported suites
that exercise the same code (test_frontdesk_http.py, the monitor skips of test_role_containers.py and test_monitoring.py) run beside this file.
"""
import ast
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from filelock import FileLock

from codex_harness.composition import monitor as composition_monitor
from codex_harness.coordination.domain.fleet import FleetRefused
from codex_harness.entry.http import desk as desk_module
from codex_harness.entry.processes import monitor as entry_monitor
from codex_harness.observation import ports
from codex_harness.observation.adapters import collectors, viewer_http
from codex_harness.storage.adapters.memory_store import MemoryStore

REVISION = "a" * 40
SRC = Path(__file__).resolve().parents[1] / "src" / "codex_harness"


# ----- listener_refusal (INV-MONITOR-VIEWER-001) ---------------------------------------------------------------------------------------
def test_web_with_a_desk_revision_refuses():
    assert composition_monitor.listener_refusal("web", None, REVISION, viewer=8787).startswith("monitor web refuses")
    assert composition_monitor.listener_refusal("web", None, None, viewer=8787) is None


def test_desk_without_a_revision_refuses():
    assert composition_monitor.listener_refusal("desk", 8788, "", viewer=8787) == "monitor desk needs ZEUS_DESK_REVISION"
    assert composition_monitor.listener_refusal("desk", 8788, None, viewer=8787) == "monitor desk needs ZEUS_DESK_REVISION"


@pytest.mark.parametrize("port, viewer", [(None, 8787), (8787, 8787), (8790, 8790), (8787, 8790)])
def test_desk_on_the_viewer_port_or_without_a_port_refuses(port, viewer):
    message = composition_monitor.listener_refusal("desk", port, REVISION, viewer=viewer)
    assert "own --port" in message and message.endswith(str(viewer))


def test_a_desk_on_its_own_port_passes_and_the_viewer_port_follows_the_environment():
    assert composition_monitor.listener_refusal("desk", 8788, REVISION, viewer=8787) is None
    assert composition_monitor.viewer_port({"ZEUS_AIBOX_WEB_PORT": "8790"}) == 8790
    assert composition_monitor.viewer_port({"ZEUS_AIBOX_WEB_PORT": "x"}) == viewer_http.VIEWER_PORT
    assert composition_monitor.listener_refusal("collect", None, REVISION) is None


# ----- collector_ports: every field wired to its tabled owner --------------------------------------------------------------------------
def test_collector_ports_has_all_eleven_fields_wired_to_the_tabled_owners():
    from codex_harness.host_os.adapters import process_groups
    from codex_harness.research.application import discovery_pressure

    built = composition_monitor.collector_ports()
    assert isinstance(built, ports.CollectorPorts) and len(ports.CollectorPorts.__dataclass_fields__) == 11
    assert built.run_process is process_groups.run_process
    assert built.discovery_pressure is discovery_pressure.status
    store = MemoryStore()
    schemas = {"fleet": "urn:zeus:fleet-status:1", "research_program": "urn:zeus:research-program-monitor:1",
               "portfolio": "urn:zeus:portfolio-status:1", "fleet_backlog": "urn:zeus:fleet-backlog-status:1",
               "host_delivery": "urn:zeus:host-delivery-status:1", "worker_session": "zeus.worker-session.v1",
               "continuation": "urn:zeus:continuation-status:1", "discovery_pressure": "urn:zeus:discovery-pressure:1"}
    for field, schema in schemas.items():
        assert getattr(built, field)(store)["schema"] == schema, field
    assert built.discovery_pressure(store) == {"schema": schemas["discovery_pressure"], "evaluated": False, "row": None}
    assert built.fleet(store)["registered"] is False
    with pytest.raises(FleetRefused, match="unregistered"):
        built.registered(store)


def test_the_bus_factory_builds_the_redis_bus_with_the_configured_namespace(monkeypatch):
    from codex_harness.storage.adapters import redis_bus

    seen = []
    monkeypatch.setattr(redis_bus, "RedisBus", lambda url, namespace: seen.append((url, namespace)) or "bus")
    monkeypatch.setattr(composition_monitor, "settings", lambda: {"HARNESS_REDIS_NAMESPACE": "ns"})
    assert composition_monitor.collector_ports().bus_factory("redis://x/0") == "bus"
    monkeypatch.setattr(composition_monitor, "settings", lambda: {})
    composition_monitor.collector_ports().bus_factory("redis://y/0")
    assert seen == [("redis://x/0", "ns"), ("redis://y/0", "codex-harness")]


# ----- run_collector --------------------------------------------------------------------------------------------------------------------
@pytest.fixture
def collector(monkeypatch, tmp_path):
    import codex_harness.composition as composition
    from codex_harness.composition import (
        build as _build,  # noqa: F401 - the module attribute the collector imports
    )

    runtime = tmp_path / "runtime"
    runtime.mkdir()
    calls = []

    def fake_collect(service, artifacts, repository, redis_url, containers=None, scope=None, runtime=None, lanes=None,
                     lane_artifacts=None, *, ports):
        calls.append({"ports": ports, "repository": repository, "scope": scope})
        return {"sources": {"database": {"status": "ok", "error": None}}}

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(composition_monitor, "settings", lambda: {"ZEUS_MONITOR_SCOPE": "scope"})
    monkeypatch.setattr(composition, "build", lambda: SimpleNamespace(store=MemoryStore(), org=None))
    monkeypatch.setattr(composition, "redis_url", lambda: "redis://127.0.0.1:1/0")
    monkeypatch.setattr(collectors, "collect", fake_collect)
    monkeypatch.setattr(collectors, "lane_resolver", lambda dsn, **kwargs: None)
    monkeypatch.setattr(collectors, "lane_artifact_resolver", lambda: None)
    yield SimpleNamespace(runtime=runtime, snapshot=runtime / "monitoring.json", root=tmp_path, calls=calls)
    for handler in list(composition_monitor.logging.getLogger("zeus.monitor.collector").handlers):
        handler.close()


def events(runtime):
    return [json.loads(line) for line in (runtime / "monitor-collector.log").read_text("utf-8").splitlines()]


def test_collect_once_writes_the_snapshot_atomically_and_journals_startup_and_shutdown(collector):
    composition_monitor.run_collector(SimpleNamespace(once=True), collector.root, collector.runtime, collector.snapshot)
    assert json.loads(collector.snapshot.read_text("utf-8")) == {"sources": {"database": {"status": "ok", "error": None}}}
    assert not collector.snapshot.with_suffix(".tmp").exists()
    assert [(line["event"], line.get("reason") or line.get("source")) for line in events(collector.runtime)] == [
        ("startup", None), ("source_state", "database"), ("shutdown", "once")]
    (call,) = collector.calls
    assert isinstance(call["ports"], ports.CollectorPorts) and call["scope"] == "scope"


def test_a_held_collector_lock_journals_collector_lock_busy_and_collects_nothing(collector):
    with FileLock(str(collector.runtime / "monitor-collector.lock")):
        composition_monitor.run_collector(SimpleNamespace(once=True), collector.root, collector.runtime, collector.snapshot)
    assert [(line["event"], line.get("reason")) for line in events(collector.runtime)] == [
        ("startup_refused", "collector_lock_busy")]
    assert collector.calls == [] and not collector.snapshot.exists()


# ----- serve_web / serve_desk -----------------------------------------------------------------------------------------------------------
def test_serve_desk_passes_the_entry_http_desk_module_and_serve_web_passes_none(monkeypatch, tmp_path):
    served = []
    monkeypatch.setattr(viewer_http, "serve", lambda *args, **kwargs: served.append((args, kwargs)))
    monkeypatch.setattr(composition_monitor, "desk_service", lambda: "the-desk")
    monkeypatch.setattr(composition_monitor, "viewer_port", lambda environ=None: 8787)
    # S11 XC-2b B2: composition also injects the refusal observer (built per process; a sentinel here, no spool is opened).
    monkeypatch.setattr(composition_monitor, "refusal_observer", lambda component: "observer:" + component)
    snapshot = tmp_path / "monitoring.json"
    composition_monitor.serve_web(snapshot, None)
    composition_monitor.serve_web(snapshot, 9000)
    composition_monitor.serve_desk(snapshot, 8790, desk_http=desk_module)
    assert served == [((snapshot, 8787), {"observer": "observer:monitor.web"}),
                      ((snapshot, 9000), {"observer": "observer:monitor.web"}),
                      ((snapshot, 8790), {"desk": "the-desk", "viewer_port": 8787, "desk_http": desk_module,
                                          "observer": "observer:monitor.desk"})]


def test_the_entry_main_dispatches_each_mode_and_refuses_before_any_listener(monkeypatch, tmp_path):
    called = []
    monkeypatch.setattr(entry_monitor, "settings", lambda: {"ZEUS_DESK_REVISION": REVISION})
    monkeypatch.setattr(entry_monitor, "runtime_dir", lambda: tmp_path / "rt")
    monkeypatch.setattr(entry_monitor, "repository_root", lambda: tmp_path)
    monkeypatch.setattr(entry_monitor, "serve_web", lambda *a, **k: called.append(("web", a, k)))
    monkeypatch.setattr(entry_monitor, "serve_desk", lambda *a, **k: called.append(("desk", a, k)))
    monkeypatch.setattr(entry_monitor, "run_collector", lambda *a, **k: called.append(("collect", a, k)))
    monkeypatch.setattr(sys, "argv", ["zeus-monitor", "web"])
    with pytest.raises(SystemExit, match="refuses to start"):
        entry_monitor.main()
    assert called == []
    monkeypatch.setattr(sys, "argv", ["zeus-monitor", "desk", "--port", "8790"])
    entry_monitor.main()
    assert called == [("desk", (tmp_path / "rt" / "monitoring.json", 8790), {"desk_http": desk_module})]
    called.clear()
    monkeypatch.setattr(entry_monitor, "settings", lambda: {})
    monkeypatch.setattr(sys, "argv", ["zeus-monitor", "web"])
    entry_monitor.main()
    monkeypatch.setattr(sys, "argv", ["zeus-monitor", "collect", "--once"])
    entry_monitor.main()
    assert [name for name, *_ in called] == ["web", "collect"] and called[0][1] == (tmp_path / "rt" / "monitoring.json", None)
    assert called[1][1][0].once is True


def test_entry_http_desk_satisfies_the_desk_http_port():
    for name in ("JSON", "READ_TIMEOUT_SECONDS", "ROUTES_POST", "handle_get", "check_intent", "read_body", "handle_post", "error"):
        assert hasattr(desk_module, name), name
        assert name in ports.DeskHttp.__dict__ or name in ports.DeskHttp.__annotations__, name


# ----- the shim -------------------------------------------------------------------------------------------------------------------------
def test_the_shim_imports_only_entry():
    tree = ast.parse((SRC / "monitor.py").read_text("utf-8"))
    imported = [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    imported += [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names]
    assert imported == ["codex_harness.entry.processes.monitor"]


def test_the_module_entry_prints_help_and_exits_zero():
    done = subprocess.run([sys.executable, "-m", "codex_harness.monitor", "--help"], capture_output=True, text=True, timeout=120)
    assert done.returncode == 0 and "{collect,web,desk}" in done.stdout
