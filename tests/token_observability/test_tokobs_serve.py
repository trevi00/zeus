"""ACCEPTANCE A43 (exporter serves both files), A18 (second serve), A56 (fixture mode) and C-W1-7 (serve)."""

import sqlite3
import time
import urllib.error
import urllib.request

import pytest
from fixtures import (
    SONNET,
    T0,
    Rig,
    claude_init,
    claude_result,
    entry,
    parse_prom,
    start_row,
    terminal_row,
    usage,
)
from tokobs.__main__ import main
from tokobs.ledger import CollectorBusy
from tokobs.serve import FIXTURE_SAMPLE, Service, parse_listen

LISTEN = "127.0.0.1:0"


def get(service, path="/metrics", method="GET"):
    request = urllib.request.Request(f"http://127.0.0.1:{service.port}{path}", method=method)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, response.headers.get("Content-Type"), response.read().decode()
    except urllib.error.HTTPError as error:
        return error.code, error.headers.get("Content-Type"), error.read().decode()


def finished(rig):
    rig.record("serve-task", start_row("serve-task", 1, T0, advisor=None), terminal_row("finished", 1, T0 + 30))
    rig.events("serve-task", 1, claude_init(), claude_result(
        "r1", usage(1, 10, 100, 5), {SONNET: entry(1, 10, 100, 5, 0.25)}))


def service(rig, **kwargs):
    kwargs.setdefault("interval", 3600.0)  # tests drive scans with scan_now()
    kwargs.setdefault("clock", lambda: rig.now)
    return Service(LISTEN, data=rig.data, source_root=rig.root, **kwargs)


@pytest.mark.parametrize("text,expected", [
    ("127.0.0.1:0", ("127.0.0.1", 0)), ("0.0.0.0:9469", ("0.0.0.0", 9469)), ("[::1]:9469", ("::1", 9469))])
def test_listen_accepts_only_an_ip_and_port(text, expected):
    assert parse_listen(text) == expected


@pytest.mark.parametrize("text", ["localhost:9469", "9469", "example.com:80", "127.0.0.1:70000", "127.0.0.1:",
                                  "127.0.0.1:-1", ":9469", "127.0.0.1:9a", "", "::1:9469x"])
def test_listen_refuses_anything_that_is_not_ip_and_port(text):
    with pytest.raises(ValueError):
        parse_listen(text)


def test_cli_serve_refuses_a_hostname_and_missing_inputs_before_binding(tmp_path):
    assert main(["serve", "--listen", "localhost:1", "--data", str(tmp_path / "d"), "--source-root", str(tmp_path)]) == 2
    assert main(["serve", "--listen", "127.0.0.1:0"]) == 2  # neither --fixture nor --data/--source-root
    assert not (tmp_path / "d").exists()


def test_metrics_serves_the_rendered_data_and_health_files(tmp_path):
    rig = Rig(tmp_path)
    finished(rig)
    svc = service(rig)
    svc.start()
    try:
        assert get(svc)[0] == 503  # nothing rendered yet
        rig.now = T0 + 100
        assert svc.scan_now() is True
        status, content_type, body = get(svc)
        assert status == 200 and content_type.startswith("text/plain; version=0.0.4")
        assert body == (rig.data / "data.prom").read_text() + (rig.data / "health.prom").read_text()
        series = parse_prom(body)
        assert series[("zeus_llm_invocations_total", tuple(sorted({
            "model": SONNET, "outcome": "finished", "provider": "anthropic", "role": "implementer",
            "source": "routine"}.items())))] == 1
        assert "zeus_tokobs_render_refused 0" in body
        assert get(svc, "/")[0] == 404 and get(svc, "/metrics.json")[0] == 404
        assert get(svc, method="POST")[0] == 405
        assert get(svc, "/metrics?x=1")[0] == 200
    finally:
        svc.stop()


def test_a43_render_refusal_keeps_the_last_good_data_and_serves_the_refusal(tmp_path):
    rig = Rig(tmp_path)
    finished(rig)
    svc = service(rig)
    svc.start()
    try:
        rig.now = T0 + 100
        assert svc.scan_now() is True
        good = (rig.data / "data.prom").read_text()
        classes = ["unclassified", "unattributed_interval", "identity_unavailable", "coordination", "other",
                   *[f"c{n}" for n in range(11)]]
        rows, n = [], 0
        for provider, source in (("anthropic", "routine"), ("anthropic", "lane"), ("openai", "codex_exec")):
            for model in ("claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-4-5", "gpt-6-astra", "other"):
                for role in ("implementer", "advisor", "advisor_or_nested", "nested_unattributed", "coordinator",
                             "lane_worker", "reviewer"):
                    for tau in ("input", "output", "cache_read", "cache_write"):
                        for task_class in classes:
                            n += 1
                            rows.append((f"synthetic-{n}", "routine:serve-task:1", "main_result", provider, model,
                                         role, source, task_class, tau, 1, T0))
        conn = sqlite3.connect(rig.data / "ledger.sqlite3")
        conn.executemany("INSERT INTO contributions(id,invocation_id,kind,provider,model,role,source,task_class,"
                         "token_type,value,published_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)", rows)
        conn.commit()
        conn.close()
        assert len(rows) > 5000
        rig.now += 60
        assert svc.scan_now() is False
        status, _type, body = get(svc)
        assert status == 200 and body.startswith(good)  # the old data is still served
        assert "zeus_tokobs_render_refused 1" in body  # and the refusal is visible beside it
        assert parse_prom(body)[("zeus_tokobs_series_count", ())] > 5000
        assert (rig.data / "data.prom").read_text() == good
    finally:
        svc.stop()


def test_a18_a_second_serve_on_the_same_data_dir_exits_75_and_leaves_the_ledger_alone(tmp_path):
    rig = Rig(tmp_path)
    finished(rig)
    svc = service(rig)
    svc.start()
    try:
        rig.now = T0 + 100
        svc.scan_now()
        before = (rig.data / "ledger.sqlite3").read_bytes()
        with pytest.raises(CollectorBusy):
            service(rig).start()
        assert main(["serve", "--listen", LISTEN, "--data", str(rig.data), "--source-root", str(rig.root)]) == 75
        assert (rig.data / "ledger.sqlite3").read_bytes() == before
        assert main(["scan", "--data", str(rig.data), "--source-root", str(rig.root)]) == 75  # the flock is held
    finally:
        svc.stop()
    assert main(["scan", "--data", str(rig.data), "--source-root", str(rig.root), "--now", str(T0 + 500)]) == 0


def test_the_scan_loop_runs_periodically_and_stops_cleanly(tmp_path):
    rig = Rig(tmp_path)
    finished(rig)
    rig.now = T0 + 100
    svc = service(rig, interval=0.05)
    svc.start()
    try:
        deadline = time.time() + 10
        while time.time() < deadline and get(svc)[0] != 200:
            time.sleep(0.05)
        assert get(svc)[0] == 200
        first = int(rig.health().sum("zeus_tokobs_last_scan_success_timestamp_seconds"))
        rig.now += 500
        deadline = time.time() + 10
        while time.time() < deadline and int(rig.health().sum("zeus_tokobs_last_scan_success_timestamp_seconds")) == first:
            time.sleep(0.05)
        assert int(rig.health().sum("zeus_tokobs_last_scan_success_timestamp_seconds")) == first + 500
    finally:
        svc.stop()
    assert not any(t.is_alive() for t in svc._threads)
    with pytest.raises(urllib.error.URLError):
        get(svc)


def test_serve_stores_live_since_at_its_first_start_and_never_resets_it(tmp_path):
    rig = Rig(tmp_path)
    finished(rig)  # evidence from T0
    rig.now = T0 + 1000
    first = service(rig)
    first.start()
    try:
        first.scan_now()
    finally:
        first.stop()
    assert rig.sql("SELECT value FROM meta WHERE key='live_since'") == [(str(T0 + 1000),)]
    assert rig.sql("SELECT COUNT(*) FROM contributions WHERE backfill=1")[0][0] > 0  # older than the first start
    rig.now = T0 + 9000
    second = service(rig)
    second.start()
    try:
        second.scan_now()
    finally:
        second.stop()
    assert rig.sql("SELECT value FROM meta WHERE key='live_since'") == [(str(T0 + 1000),)]
    explicit = Rig(tmp_path / "explicit")
    finished(explicit)
    svc = service(explicit, live_since=T0 - 5)
    svc.start()
    try:
        svc.scan_now()
    finally:
        svc.stop()
    assert explicit.sql("SELECT COUNT(*) FROM contributions WHERE backfill=1")[0][0] == 0


def test_fixture_mode_serves_a_static_sample_and_touches_nothing(tmp_path):
    svc = Service(LISTEN, fixture=True)  # no data dir, no source root
    svc.start()
    try:
        status, content_type, body = get(svc)
        assert (status, body) == (200, FIXTURE_SAMPLE) and content_type.startswith("text/plain")
        assert parse_prom(body) == {("zeus_tokobs_fixture_sample", ()): 42.0}
        assert svc.scan_now() is True and svc._threads and len(svc._threads) == 1  # no scan thread
    finally:
        svc.stop()
    assert list(tmp_path.iterdir()) == []
    guarded = tmp_path / "A"
    guarded.mkdir()
    (guarded / "decoy-events.jsonl").write_text("must never be opened\n")
    svc = Service(LISTEN, fixture=True, source_root=guarded)
    svc.start()
    try:
        assert get(svc)[2] == FIXTURE_SAMPLE
    finally:
        svc.stop()
    assert sorted(p.name for p in guarded.iterdir()) == ["decoy-events.jsonl"]


def test_ipv6_loopback_is_accepted_when_the_host_supports_it(tmp_path):
    try:
        svc = Service("[::1]:0", fixture=True)
        svc.start()
    except OSError:
        pytest.skip("no IPv6 loopback")
    try:
        with urllib.request.urlopen(f"http://[::1]:{svc.port}/metrics", timeout=10) as response:
            assert response.read().decode() == FIXTURE_SAMPLE
    finally:
        svc.stop()


def test_python_dash_b_dash_m_tokobs_serve_fixture_runs_as_a_process(tmp_path):
    import socket
    import subprocess
    import sys
    from pathlib import Path

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    tools = Path(__file__).resolve().parents[2] / "tools" / "token_observability"
    proc = subprocess.Popen([sys.executable, "-B", "-m", "tokobs", "serve", "--listen", f"127.0.0.1:{port}",
                             "--fixture"], cwd=tools, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        body = None
        deadline = time.time() + 15
        while time.time() < deadline and body is None:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/metrics", timeout=2) as response:
                    body = response.read().decode()
            except OSError:
                time.sleep(0.1)
        assert body == FIXTURE_SAMPLE
    finally:
        proc.terminate()
        proc.wait(timeout=15)
