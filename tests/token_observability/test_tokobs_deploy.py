"""ACCEPTANCE A55 (compose/Prometheus/Grafana static structure), A57 (denied configurations, read allowlist) and the
rule-file part of A27/A28 (W2a). `promtool` and `docker compose config` are owner-run and NOT run here."""

import copy
import fnmatch
import io
import json
import os
import re
import sys
from pathlib import Path

import pytest
import yaml
from fixtures import (
    SONNET,
    T0,
    Rig,
    claude_init,
    claude_result,
    codex_thread_started,
    codex_turn_completed,
    codex_usage,
    entry,
    start_row,
    terminal_row,
    usage,
)
from tokobs.__main__ import main
from tokobs.deploy_lint import (
    COLLECTOR_READ_ALLOWLIST,
    S9_READ_ALLOWLIST,
    allowed_input,
    lint_compose,
    lint_inspect,
)
from tokobs.serve import Service

DEPLOY = Path(__file__).resolve().parents[2] / "deploy" / "observability"
ARTIFACTS = "/home/trevi/workspaces/zeus/artifacts/aibox-migration-001"
SECRET = "/srv/zeus/secrets/grafana-admin.pass"
CODE_MOUNTS = [("../../tools/token_observability", "/opt/zeus/tools/token_observability", True),
               ("../../src", "/opt/zeus/src", True)]


class _Loader(yaml.SafeLoader):
    """SafeLoader for compose.conntest.yaml: `!override` / `!reset` yield the plain node value."""


def _plain(loader, tag_suffix, node):
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node, deep=True)
    if isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node, deep=True)
    return loader.construct_scalar(node)


_Loader.add_multi_constructor("!override", _plain)
_Loader.add_multi_constructor("!reset", _plain)
_Loader.add_constructor("!override", lambda loader, node: _plain(loader, "", node))
_Loader.add_constructor("!reset", lambda loader, node: _plain(loader, "", node))


def load(rel: str, loader=yaml.SafeLoader):
    return yaml.load((DEPLOY / rel).read_text(), Loader=loader)


@pytest.fixture(scope="module")
def compose():
    return load("compose.yaml")


@pytest.fixture(scope="module")
def conntest():
    return load("compose.conntest.yaml", _Loader)


def mounts(service):
    return [(v["source"], v["target"], v.get("read_only", False)) for v in service["volumes"]]


# -- A55 ----------------------------------------------------------------------

def test_a55_networks_and_volumes(compose):
    assert compose["name"] == "zeus-tokobs"
    private, edge = compose["networks"]["private"], compose["networks"]["edge"]
    assert private["driver"] == "bridge" and private["internal"] is True and private["enable_ipv6"] is False
    assert private["driver_opts"] == {"com.docker.network.bridge.gateway_mode_ipv4": "isolated"}
    assert edge == {"driver": "bridge"}
    assert set(compose["networks"]) == {"private", "edge"}
    assert compose["volumes"] == {"tokobs-prometheus": {}, "tokobs-grafana": {}}
    assert set(compose["services"]) == {"collector", "prometheus", "grafana"}


def test_a55_every_service_is_hardened_and_limited(compose):
    limits = {"collector": ("128m", 0.1, 16), "prometheus": ("512m", 0.5, 64), "grafana": ("256m", 0.5, 128)}
    for name, service in compose["services"].items():
        assert service["user"] == "1000:1000", name
        assert service["read_only"] is True, name
        assert service["cap_drop"] == ["ALL"], name
        assert service["security_opt"] == ["no-new-privileges:true"], name
        assert service["restart"] == "unless-stopped", name
        assert (service["mem_limit"], service["cpus"], service["pids_limit"]) == limits[name], name
        assert "@sha256:" in service["image"], name
        for forbidden in ("privileged", "network_mode", "pid", "ipc", "cap_add"):
            assert forbidden not in service, (name, forbidden)
        for volume in service["volumes"]:
            assert isinstance(volume, dict), (name, volume)  # long syntax only
            assert not volume["source"].endswith("docker.sock")
            if volume["type"] == "bind":
                assert volume["bind"] == {"create_host_path": False}, (name, volume)
                assert "read_only" in volume, (name, volume)


def test_a55_networks_and_ports_per_service(compose):
    svc = compose["services"]
    assert svc["collector"]["networks"] == ["private"] and "ports" not in svc["collector"]
    assert svc["prometheus"]["networks"] == ["private"] and "ports" not in svc["prometheus"]
    assert svc["grafana"]["networks"] == {"private": {}, "edge": {"gw_priority": 1}}
    assert svc["grafana"]["ports"] == [{"target": 3000, "published": "3300", "host_ip": "127.0.0.1",
                                        "protocol": "tcp"}]


def test_a55_collector_mounts_are_exactly_the_five_inputs(compose):
    collector = compose["services"]["collector"]
    assert mounts(collector) == CODE_MOUNTS + [
        (ARTIFACTS, "/input/artifacts", True), ("/srv/zeus/runtime/control", "/input/s9", True),
        ("/srv/zeus/runtime/tokobs", "/data", False)]
    assert collector["tmpfs"] == ["/tmp:size=16m"]
    assert collector["environment"] == {"PYTHONPATH": "/opt/zeus/tools/token_observability:/opt/zeus/src",
                                        "PYTHONDONTWRITEBYTECODE": "1"}
    assert collector["command"] == ["python", "-B", "-m", "tokobs", "serve", "--listen", "0.0.0.0:9469",
                                    "--data", "/data", "--source-root", "/input/artifacts",
                                    "--s9-dir", "/input/s9"]
    assert collector["image"].startswith("python:3.13-slim-bookworm@sha256:")


def test_a55_the_secret_path_appears_only_in_grafana(compose):
    for name, service in compose["services"].items():
        found = SECRET in json.dumps(service)
        assert found == (name == "grafana"), name
    grafana = compose["services"]["grafana"]
    assert (SECRET, "/run/secrets/grafana-admin.pass", True) in mounts(grafana)
    assert not any("/srv/zeus/secrets" in m[0] for m in mounts(compose["services"]["collector"]))


def test_a55_prometheus_service(compose):
    prom = compose["services"]["prometheus"]
    assert prom["group_add"] == ["65534"] and prom["user"] == "1000:1000"
    assert prom["command"] == ["--config.file=/etc/prometheus/prometheus.yml", "--storage.tsdb.path=/prometheus",
                               "--storage.tsdb.retention.time=180d", "--storage.tsdb.retention.size=2GB"]
    assert mounts(prom) == [("tokobs-prometheus", "/prometheus", False),
                            ("./prometheus/prometheus.yml", "/etc/prometheus/prometheus.yml", True),
                            ("./prometheus/rules", "/etc/prometheus/rules", True)]


def test_a55_grafana_service(compose):
    grafana = compose["services"]["grafana"]
    assert grafana["tmpfs"] == ["/tmp:size=64m"]
    env = grafana["environment"]
    assert env["GF_SECURITY_ADMIN_PASSWORD"] == "$$__file{/run/secrets/grafana-admin.pass}"
    for key in ("GF_AUTH_ANONYMOUS_ENABLED", "GF_ANALYTICS_REPORTING_ENABLED", "GF_ANALYTICS_CHECK_FOR_UPDATES",
                "GF_ANALYTICS_CHECK_FOR_PLUGIN_UPDATES", "GF_PLUGINS_PLUGIN_ADMIN_ENABLED"):
        assert env[key] == "false", key
    assert env["GF_LOG_MODE"] == "console"
    assert mounts(grafana) == [("tokobs-grafana", "/var/lib/grafana", False),
                               ("./grafana/provisioning", "/etc/grafana/provisioning", True),
                               ("./grafana/dashboards", "/etc/grafana/dashboards", True),
                               (SECRET, "/run/secrets/grafana-admin.pass", True)]


def test_a55_prometheus_and_grafana_provisioning_are_static_and_consistent(compose):
    prometheus = load("prometheus/prometheus.yml")
    assert prometheus["global"] == {"scrape_interval": "60s", "evaluation_interval": "60s"}
    assert "alerting" not in prometheus
    assert prometheus["scrape_configs"] == [{"job_name": "tokobs", "static_configs": [{"targets": ["collector:9469"]}]}]
    rules_target = next(t for s, t, _ in mounts(compose["services"]["prometheus"]) if s == "./prometheus/rules")
    assert prometheus["rule_files"] == [rules_target + "/tokobs.yml"]
    assert (DEPLOY / "prometheus" / "rules" / "tokobs.yml").is_file()

    datasource = load("grafana/provisioning/datasources/tokobs.yaml")["datasources"]
    assert len(datasource) == 1
    assert datasource[0]["type"] == "prometheus" and datasource[0]["uid"] == "tokobs-prom"
    assert datasource[0]["url"] == "http://prometheus:9090"
    assert datasource[0]["access"] == "proxy" and datasource[0]["isDefault"] is True
    assert datasource[0]["editable"] is False

    providers = load("grafana/provisioning/dashboards/tokobs.yaml")["providers"]
    assert len(providers) == 1 and providers[0]["type"] == "file"
    assert providers[0]["allowUiUpdates"] is False and providers[0]["disableDeletion"] is True
    dashboards_target = next(t for s, t, _ in mounts(compose["services"]["grafana"]) if s == "./grafana/dashboards")
    assert providers[0]["options"]["path"] == dashboards_target
    assert (DEPLOY / "grafana" / "dashboards").is_dir()


def test_a55_every_bind_source_in_the_checkout_exists(compose):
    for name, service in compose["services"].items():
        for volume in service["volumes"]:
            if volume["type"] == "bind" and not volume["source"].startswith("/"):
                assert (DEPLOY / volume["source"]).resolve().exists(), (name, volume["source"])


def test_a55_the_conntest_override_mounts_no_worker_input(conntest):
    collector, grafana = conntest["services"]["collector"], conntest["services"]["grafana"]
    assert collector["command"] == ["python", "-B", "-m", "tokobs", "serve", "--listen", "0.0.0.0:9469", "--fixture"]
    assert [(v["source"], v["target"], v["read_only"]) for v in collector["volumes"]] == CODE_MOUNTS
    assert not any(v["target"] == "/data" for v in collector["volumes"])
    assert grafana["ports"] == [{"target": 3000, "published": "13300", "host_ip": "127.0.0.1", "protocol": "tcp"}]
    sources = [v["source"] for v in grafana["volumes"]]
    assert "${TOKOBS_CONNTEST_DIR:?}/grafana-admin.pass" in sources
    assert SECRET not in sources
    assert set(conntest["services"]) == {"collector", "grafana"}  # prometheus is unchanged
    text = (DEPLOY / "compose.conntest.yaml").read_text()
    assert ARTIFACTS not in text and "/srv/" not in text
    assert "!override" in text


# -- A57: compose ---------------------------------------------------------------

def test_a57_the_production_compose_file_has_no_violations(compose):
    assert lint_compose(compose) == []


def _mutate(compose, service, **changes):
    config = copy.deepcopy(compose)
    for key, value in changes.items():
        if key.endswith("+"):
            config["services"][service].setdefault(key[:-1], []).extend(value)
        elif key == "ports":
            config["services"][service]["ports"] = value
        else:
            config["services"][service][key] = value
    return config


MUTATIONS = [
    ("host network", "collector", {"network_mode": "host"}, ["collector: network_mode host"]),
    ("privileged", "prometheus", {"privileged": True}, ["prometheus: privileged"]),
    ("docker socket", "collector",
     {"volumes+": ["/var/run/docker.sock:/var/run/docker.sock"]},
     ["collector: mounts the Docker socket /var/run/docker.sock"]),
    ("docker socket long", "grafana",
     {"volumes+": [{"type": "bind", "source": "/run/docker.sock", "target": "/x"}]},
     ["grafana: mounts the Docker socket /run/docker.sock"]),
    ("pid host", "grafana", {"pid": "host"}, ["grafana: pid host"]),
    ("ipc host", "grafana", {"ipc": "host"}, ["grafana: ipc host"]),
    ("cap_add", "collector", {"cap_add": ["NET_ADMIN"]}, ["collector: cap_add ['NET_ADMIN']"]),
    ("short no host ip", "grafana", {"ports": ["3300:3000"]}, ["grafana: publish 3300:3000 has no host_ip 127.0.0.1"]),
    ("short all interfaces", "grafana", {"ports": ["0.0.0.0:3300:3000"]},
     ["grafana: publish 0.0.0.0:3300:3000 has no host_ip 127.0.0.1 (host_ip 0.0.0.0)"]),
    ("short ipv6 any", "grafana", {"ports": ["[::]:3300:3000"]},
     ["grafana: publish [::]:3300:3000 has no host_ip 127.0.0.1 (host_ip ::)"]),
    ("collector 9469", "collector", {"ports": ["127.0.0.1:9469:9469"]},
     ["collector: publish 127.0.0.1:9469:9469 exposes denied port 9469"]),
    ("prometheus 9090", "prometheus", {"ports": ["127.0.0.1:9090:9090"]},
     ["prometheus: publish 127.0.0.1:9090:9090 exposes denied port 9090"]),
    ("long no host_ip", "grafana", {"ports": [{"target": 3000, "published": "3300", "protocol": "tcp"}]},
     ["grafana: publish 3300:3000 has no host_ip 127.0.0.1"]),
]


@pytest.mark.parametrize("label,service,changes,expected", MUTATIONS, ids=[m[0] for m in MUTATIONS])
def test_a57_each_denied_compose_configuration_is_rejected_with_exactly_its_violation(
        compose, label, service, changes, expected):
    assert lint_compose(_mutate(compose, service, **changes)) == expected


def test_a57_short_syntax_ports_are_parsed():
    assert lint_compose({"services": {"grafana": {"ports": ["3300:3000"]}}}) == [
        "grafana: publish 3300:3000 has no host_ip 127.0.0.1"]
    assert lint_compose({"services": {"g": {"ports": ["127.0.0.1:3300:3000"]}}}) == []
    assert lint_compose({"services": {"g": {"ports": ["127.0.0.1:3300:3000/tcp"]}}}) == []
    assert lint_compose({"services": {"g": {"ports": [3000]}}}) == ["g: publish 3000 has no host_ip 127.0.0.1"]


NORMALIZED = {  # the shape of `docker compose config --format json`: ports and volumes in long syntax
    "name": "zeus-tokobs",
    "services": {
        "collector": {"user": "1000:1000", "read_only": True, "cap_drop": ["ALL"],
                      "volumes": [{"type": "bind", "source": ARTIFACTS, "target": "/input/artifacts",
                                   "read_only": True, "bind": {"create_host_path": False}}]},
        "grafana": {"user": "1000:1000", "read_only": True, "cap_drop": ["ALL"],
                    "ports": [{"mode": "ingress", "host_ip": "127.0.0.1", "target": 3000, "published": "3300",
                               "protocol": "tcp"}],
                    "volumes": [{"type": "volume", "source": "tokobs-grafana", "target": "/var/lib/grafana",
                                 "volume": {}}]},
        "prometheus": {"user": "1000:1000", "read_only": True, "cap_drop": ["ALL"], "group_add": ["65534"]},
    },
}


def test_a57_the_normalized_long_syntax_form_passes_and_its_mutations_fail():
    assert lint_compose(NORMALIZED) == []
    bad = copy.deepcopy(NORMALIZED)
    bad["services"]["grafana"]["ports"][0].pop("host_ip")
    assert lint_compose(bad) == ["grafana: publish 3300:3000 has no host_ip 127.0.0.1"]
    bad = copy.deepcopy(NORMALIZED)
    bad["services"]["collector"]["ports"] = [{"host_ip": "127.0.0.1", "target": 9469, "published": "9469"}]
    assert lint_compose(bad) == ["collector: publish 9469:9469 exposes denied port 9469"]


# -- A57: docker inspect -----------------------------------------------------------

def hardened(name, bindings=None):
    return {"Name": f"/{name}", "Config": {"User": "1000:1000"},
            "HostConfig": {"NetworkMode": "zeus-tokobs_private", "Privileged": False, "PidMode": "", "IpcMode": "private",
                           "CapAdd": None, "CapDrop": ["ALL"], "ReadonlyRootfs": True,
                           "SecurityOpt": ["no-new-privileges:true"], "PortBindings": bindings or {},
                           "Binds": ["/srv/zeus/runtime/tokobs:/data:rw"]},
            "Mounts": [{"Type": "bind", "Source": "/srv/zeus/runtime/tokobs", "Destination": "/data"}]}


def inspect_fixture():
    return [hardened("zeus-tokobs-collector-1"), hardened("zeus-tokobs-prometheus-1"),
            hardened("zeus-tokobs-grafana-1", {"3000/tcp": [{"HostIp": "127.0.0.1", "HostPort": "3300"}]})]


def test_a57_a_hardened_inspect_list_has_no_violations():
    assert lint_inspect(inspect_fixture()) == []


INSPECT_MUTATIONS = [
    ("host network", lambda c: c["HostConfig"].update(NetworkMode="host"), "x: NetworkMode host"),
    ("privileged", lambda c: c["HostConfig"].update(Privileged=True), "x: Privileged"),
    ("socket mount", lambda c: c["Mounts"].append({"Source": "/var/run/docker.sock"}),
     "x: mounts the Docker socket"),
    ("socket bind", lambda c: c["HostConfig"]["Binds"].append("/var/run/docker.sock:/var/run/docker.sock"),
     "x: mounts the Docker socket"),
    ("pid host", lambda c: c["HostConfig"].update(PidMode="host"), "x: PidMode host"),
    ("ipc host", lambda c: c["HostConfig"].update(IpcMode="host"), "x: IpcMode host"),
    ("cap add", lambda c: c["HostConfig"].update(CapAdd=["SYS_ADMIN"]), "x: CapAdd ['SYS_ADMIN']"),
    ("all interfaces", lambda c: c["HostConfig"].update(
        PortBindings={"3000/tcp": [{"HostIp": "", "HostPort": "3300"}]}),
     "x: PortBindings 3000/tcp HostIp '' is not 127.0.0.1"),
    ("0.0.0.0", lambda c: c["HostConfig"].update(
        PortBindings={"3000/tcp": [{"HostIp": "0.0.0.0", "HostPort": "3300"}]}),
     "x: PortBindings 3000/tcp HostIp '0.0.0.0' is not 127.0.0.1"),
    ("9469", lambda c: c["HostConfig"].update(
        PortBindings={"9469/tcp": [{"HostIp": "127.0.0.1", "HostPort": "9469"}]}),
     "x: PortBindings 9469/tcp publishes denied port 9469"),
    ("9090", lambda c: c["HostConfig"].update(
        PortBindings={"9090/tcp": [{"HostIp": "127.0.0.1", "HostPort": "9090"}]}),
     "x: PortBindings 9090/tcp publishes denied port 9090"),
    ("capdrop none", lambda c: c["HostConfig"].update(CapDrop=None), "x: CapDrop lacks ALL"),
    ("capdrop partial", lambda c: c["HostConfig"].update(CapDrop=["NET_RAW"]), "x: CapDrop lacks ALL"),
    ("writable rootfs", lambda c: c["HostConfig"].update(ReadonlyRootfs=False), "x: ReadonlyRootfs is not true"),
    ("root user", lambda c: c["Config"].update(User=""), "x: Config.User is '', not 1000:1000"),
    ("no-new-privileges", lambda c: c["HostConfig"].update(SecurityOpt=[]),
     "x: SecurityOpt lacks no-new-privileges:true"),
]


@pytest.mark.parametrize("label,mutate,expected", INSPECT_MUTATIONS, ids=[m[0] for m in INSPECT_MUTATIONS])
def test_a57_each_denied_inspect_field_is_rejected_with_exactly_its_violation(label, mutate, expected):
    container = hardened("x")
    mutate(container)
    assert lint_inspect([container]) == [expected]


def write(path, value):
    path.write_text(value if isinstance(value, str) else json.dumps(value))
    return str(path)


def test_a57_cli_exit_codes(tmp_path, capsys):
    clean = write(tmp_path / "clean.json", inspect_fixture())
    assert main(["lint-deploy", "--inspect-json", clean]) == 0
    assert capsys.readouterr().out == ""
    bad = inspect_fixture()
    bad[0]["HostConfig"]["Privileged"] = True
    assert main(["lint-deploy", "--inspect-json", write(tmp_path / "bad.json", bad)]) == 1
    assert capsys.readouterr().out == "zeus-tokobs-collector-1: Privileged\n"
    assert main(["lint-deploy", "--inspect-json", write(tmp_path / "broken.json", "{not json")]) == 2
    assert main(["lint-deploy", "--inspect-json", str(tmp_path / "missing.json")]) == 2
    assert main(["lint-deploy", "--inspect-json", write(tmp_path / "wrongtype.json", {"a": 1})]) == 2
    capsys.readouterr()
    assert main(["lint-deploy", "--compose-json", write(tmp_path / "c.json", NORMALIZED)]) == 0
    mutated = copy.deepcopy(NORMALIZED)
    mutated["services"]["collector"]["privileged"] = True
    assert main(["lint-deploy", "--compose-json", write(tmp_path / "c2.json", mutated)]) == 1
    assert capsys.readouterr().out == "collector: privileged\n"
    assert main(["lint-deploy"]) == 2  # one of the two inputs is required


def test_a57_cli_reads_stdin_for_a_dash(monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(inspect_fixture())))
    assert main(["lint-deploy", "--inspect-json", "-"]) == 0
    assert capsys.readouterr().out == ""
    monkeypatch.setattr(sys, "stdin", io.StringIO("nope"))
    assert main(["lint-deploy", "--inspect-json", "-"]) == 2


# -- A57: the collector read allowlist --------------------------------------------

def test_a57_allowed_input_matches_segment_by_segment():
    yes = ["routine-runs/t1/record.jsonl", "routine-runs/t1/events-2.jsonl", "routine-runs/t1/receipt-1.json",
           "x-events.jsonl", "r1-codex-events.jsonl", "r1-codex-run.sh", "fleet-x-codex-prestart.json",
           "evidence/lane1/events.jsonl", "evidence/lane1/events-2.jsonl", "evidence/lane1/run.json",
           "evidence/lane1/run-2.json", "credential-selection/000.json"]
    no = ["deep/y-events.jsonl", "STATUS.md", "x.env", "routine-runs/t1/notes.md", "routine-runs/t1/spec-1.md",
          "evidence/lane1/other.txt", "credential-selection/sub/x.json", "routine-runs/events-1.jsonl",
          "routine-runs/a/b/record.jsonl", "", "../x-events.jsonl", "/x-events.jsonl", "a//x-events.jsonl"]
    assert [p for p in yes if not allowed_input(p)] == []
    assert [p for p in no if allowed_input(p)] == []
    assert S9_READ_ALLOWLIST == ("monitoring.json",)
    assert "*-codex-prestart.json" in COLLECTOR_READ_ALLOWLIST


_OPENED: list[str] = []
_HOOK = {"on": False, "installed": False}


def _audit(event, args):
    if _HOOK["on"] and event == "open" and isinstance(args[0], (str, bytes, os.PathLike)):
        _OPENED.append(os.path.realpath(os.fsdecode(args[0])))


@pytest.fixture(scope="session")
def audit_hook():
    """One `sys.addaudithook` per session (hooks cannot be removed); the flag turns it off between tests."""
    if not _HOOK["installed"]:
        sys.addaudithook(_audit)
        _HOOK["installed"] = True
    return _HOOK


def build_tree(tmp_path):
    rig = Rig(tmp_path)
    # routine: record + events + receipt
    rig.record("t1", start_row("t1", 1, T0, advisor=None), terminal_row("finished", 1, T0 + 30))
    rig.events("t1", 1, claude_init(), claude_result("r1", usage(1, 10, 100, 5), {SONNET: entry(1, 10, 100, 5, 0.25)}))
    rig.receipt("t1", 1)
    # S2: a coordinator stream, a lane run.json + events, and a credential-selection receipt
    rig.stream("coord-events.jsonl", claude_init(), claude_result("c1", usage(2, 20, 30, 1), {SONNET: entry(2, 20, 30, 1)}))
    rig.lane_meta("lane1", state="finished", finished_at="2026-10-01T05:14:00+00:00")
    rig.stream("evidence/lane1/events.jsonl", claude_init(model="opus"), claude_result("l1", usage(1, 8, 4, 0), None))
    rig.credential_receipt("lane", "evidence/lane1/events.jsonl")
    # S3: a fresh run and a resumed run with a C-W1-4 prestart sidecar
    p0, p1 = codex_usage(1000, 800, 100, 30), codex_usage(1500, 1200, 160, 40)
    rig.codex_script("gold0", resume=False)
    rig.codex_events("gold0", codex_thread_started("th-1"), codex_turn_completed(p0))
    rig.codex_script("gold1", resume=True)
    rig.codex_prestart("gold1", "th-1", p0)
    rig.codex_events("gold1", codex_thread_started("th-1"), codex_turn_completed(p1))
    # decoys under A
    decoys = ["STATUS.md", "x.env", "routine-runs/t1/notes.md", "routine-runs/t1/spec-1.md",
              "evidence/lane1/other.txt", "credential-selection/sub/x.json", "deep/y-events.jsonl"]
    for rel in decoys:
        path = rig.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("SYNTHETIC-DECOY\n")
    s9 = tmp_path / "control"
    s9.mkdir()
    (s9 / "monitoring.json").write_text(json.dumps({"collected_at": "2026-10-01T06:44:28+00:00", "sources": {}}))
    (s9 / "other.json").write_text("{}")
    return rig, s9, decoys


def test_a57_the_collector_opens_only_allowlisted_paths_decoys_never(tmp_path, audit_hook):
    rig, s9, decoys = build_tree(tmp_path)
    service = Service("127.0.0.1:0", data=rig.data, source_root=rig.root, s9_dir=s9, interval=3600.0,
                      clock=lambda: rig.now)
    del _OPENED[:]
    audit_hook["on"] = True
    try:
        service.scan_now()
    finally:
        audit_hook["on"] = False
    root, s9_root = os.path.realpath(rig.root), os.path.realpath(s9)
    source_opened = sorted({os.path.relpath(p, root) for p in _OPENED if p.startswith(root + os.sep)})
    s9_opened = sorted({os.path.relpath(p, s9_root) for p in _OPENED if p.startswith(s9_root + os.sep)})
    assert source_opened, "the scan opened nothing: the test would pass vacuously"
    assert [p for p in source_opened if not allowed_input(p)] == []
    assert [p for p in s9_opened if p not in S9_READ_ALLOWLIST] == []
    assert s9_opened == ["monitoring.json"]
    assert [d for d in decoys if d in source_opened] == []  # decoys opened = 0
    counts = {}
    for pattern in COLLECTOR_READ_ALLOWLIST:
        segs = pattern.split("/")
        counts[pattern] = sum(1 for p in source_opened if len(p.split("/")) == len(segs)
                              and all(fnmatch.fnmatchcase(s, g) for s, g in zip(p.split("/"), segs)))
    assert [k for k, v in counts.items() if v == 0] == [], counts  # every allowlisted kind WAS opened
    assert "gold1-codex-prestart.json" in source_opened  # opened through the C-W1-4 reader path
    assert rig.sql("SELECT COUNT(*) FROM invocations")[0][0] >= 1  # the scan really ingested


# -- A27 / A28: the rule-file part -----------------------------------------------

def rules():
    groups = load("prometheus/rules/tokobs.yml")["groups"]
    return [rule for group in groups for rule in group["rules"]]


TOKEN_METRIC = re.compile(r"zeus_llm_tokens_total|zeus_task_tokens_total|zeus_llm_reasoning_output_tokens_total"
                          r"|zeus:llm_tokens|zeus:task_tokens")


def names_in(rule):
    found = set(re.findall(r"\bzeus[a-z0-9_:]*", rule["expr"]))
    found.add(rule.get("record") or rule["alert"])
    return found


def combines_provider_and_tokens(expr):
    return "zeus_llm_provider_" in expr and bool(TOKEN_METRIC.search(expr))


def test_a27_no_rule_combines_a_provider_window_metric_with_a_token_metric():
    assert [r["expr"] for r in rules() if combines_provider_and_tokens(r["expr"])] == []
    assert combines_provider_and_tokens("zeus_llm_provider_utilization_ratio / zeus:llm_tokens:increase1d")  # lint bites
    assert any("zeus_llm_provider_" in r["expr"] for r in rules())  # TokObsWindowStale is in the file


def test_a28_no_charge_or_bill_metric_and_the_only_cost_metric_is_the_estimate():
    names = set().union(*(names_in(r) for r in rules()))
    assert [n for n in names if "charge" in n or "bill" in n] == []
    assert [n for n in names if "cost" in n and n != "zeus_llm_estimated_cost_usd_total"] == []


def test_the_rule_file_matches_design_5_1():
    by_name = {(r.get("record") or r["alert"]): r for r in rules()}
    assert set(by_name) == {"zeus:llm_tokens:increase1d", "zeus:task_tokens_per_accepted:7d",
                            "zeus:llm_unknown_ratio:1d", "TokObsExporterDown", "TokObsScanStale",
                            "TokObsRenderRefused", "TokObsUnknownHigh", "TokObsS9SnapshotStale", "TokObsWindowStale"}
    assert by_name["zeus:task_tokens_per_accepted:7d"]["expr"] == (
        'sum by (task_class,token_type)(increase(zeus_task_tokens_total{outcome="accepted"}[7d])) / '
        'ignoring(token_type) group_left sum by (task_class)(increase(zeus_task_outcomes_total{outcome="accepted"}[7d]))')
    assert by_name["zeus:llm_unknown_ratio:1d"]["expr"] == (
        "sum(increase(zeus_llm_unknown_invocations_total[1d])) / sum(increase(zeus_llm_invocations_total[1d]))")
    assert by_name["zeus:llm_tokens:increase1d"]["expr"] == (
        "sum by (provider,model,role,token_type)(increase(zeus_llm_tokens_total[1d]))")
    assert by_name["TokObsExporterDown"]["for"] == "5m" and by_name["TokObsWindowStale"]["for"] == "1h"
    assert by_name["TokObsUnknownHigh"]["expr"] == "zeus:llm_unknown_ratio:1d > 0.2"
    assert by_name["TokObsS9SnapshotStale"]["expr"] == (
        "time() - zeus_s9_snapshot_collected_timestamp_seconds > 120")
    for name, rule in by_name.items():
        if "alert" in rule:
            assert rule["labels"]["severity"] == ("info" if name == "TokObsWindowStale" else "warning")
            assert rule["annotations"]["summary"]


def test_the_promtool_test_file_is_present_and_names_the_a25_a26_a29_a43_cases():
    tests = load("prometheus/rules/tokobs.test.yml")
    assert tests["rule_files"] == ["tokobs.yml"] and tests["evaluation_interval"] == "1m"
    assert [t["name"].split()[0] for t in tests["tests"]] == ["A25", "A25", "A26", "A43", "A29"]
