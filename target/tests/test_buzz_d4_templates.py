"""Buzz D4: the production templates (bridge unit + config, relay compose) and their static lint (no Docker, no systemd).

`run_e2e.py --lint-templates` reads `deploy/buzz-bridge/*` and `deploy/buzz-relay/*`; each rule is proved by planting one
violation in a temp copy of the deploy tree. Nothing is installed or started. Contracts: DESIGN-D section 5, section 6 row 7.
"""

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from codex_harness.composition.buzz_bridge import BridgeConfig

TARGET = Path(__file__).resolve().parents[1]
DEPLOY = TARGET / "deploy"
RUNNER = Path(__file__).resolve().parent / "fixtures" / "buzz_e2e" / "run_e2e.py"
A4_COMPOSE = Path(__file__).resolve().parent / "fixtures" / "buzz_e2e" / "compose.yaml"
UNIT = Path("buzz-bridge/buzz-bridge.service.template")
CONFIG = Path("buzz-bridge/config.template.json")
COMPOSE = Path("buzz-relay/compose.template.yaml")
SCHEME = "postgres" + "://"  # split: the tree check flags credential-shaped literals


def lint(directory):
    done = subprocess.run([sys.executable, "-B", str(RUNNER), "--lint-templates", "--templates-dir", str(directory)],
                          capture_output=True, text=True, timeout=120, check=False)
    return done.returncode, done.stdout


def plant(tmp_path, relative, old, new):
    """A copy of the deploy templates with the first `old` of `relative` replaced; `old` must be present."""
    target = tmp_path / "deploy"
    for name in (UNIT, CONFIG, COMPOSE):
        (target / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(DEPLOY / name, target / name)
    text = (target / relative).read_text(encoding="utf-8")
    assert old in text, f"{old!r} is not in {relative}"
    (target / relative).write_text(text.replace(old, new, 1), encoding="utf-8")
    return target


def expect_violation(tmp_path, relative, old, new, rule, needle=None):
    code, out = lint(plant(tmp_path, relative, old, new))
    lines = [line for line in out.splitlines() if line.startswith("LINT ")]
    assert code == 1, out
    hits = [line for line in lines if f": {rule}: " in line and (needle is None or needle in line)]
    assert hits, out
    assert re.match(rf"LINT \S+:\d+: {rule}: ", hits[0]), hits[0]
    return hits[0]


def line_number(relative, needle):
    for number, line in enumerate((DEPLOY / relative).read_text(encoding="utf-8").splitlines(), 1):
        if needle in line:
            return number
    raise AssertionError(needle)


# -- the templates themselves ------------------------------------------------------------------------------------------

def test_the_lint_passes_on_the_templates():
    code, out = lint(DEPLOY)
    assert (code, out.strip()) == (0, "templates lint-clean"), out


def test_the_unit_carries_the_design_directives_and_no_secret_environment():
    directives = {}
    for line in (DEPLOY / UNIT).read_text(encoding="utf-8").splitlines():
        if line.strip() and line[0] not in "#[":
            key, _, value = line.partition("=")
            directives.setdefault(key, []).append(value)
    expected = {"Type": "simple", "User": "@USER@", "Restart": "always", "RestartSec": "10", "KillMode": "mixed",
                "TimeoutStopSec": "45", "NoNewPrivileges": "yes", "ProtectSystem": "strict", "ProtectHome": "read-only",
                "PrivateTmp": "yes", "ReadWritePaths": "", "MemoryMax": "2G", "MemorySwapMax": "0",
                "OOMPolicy": "continue",
                "ExecStart": "@VENV_PYTHON@ -B -m codex_harness.entry.processes.buzz_bridge --config @CONFIG_PATH@"}
    assert {key: directives.get(key) for key in expected} == {key: [value] for key, value in expected.items()}
    assert "EnvironmentFile" not in directives and directives["Environment"] == ["PYTHONUNBUFFERED=1"]


def test_the_config_lists_every_bridge_config_key_with_the_code_defaults():
    document = json.loads((DEPLOY / CONFIG).read_text(encoding="utf-8"))
    fields = BridgeConfig.__dataclass_fields__
    assert set(document) == set(fields)
    for key, field in fields.items():
        if key in ("organization_file", "tick_seconds", "lease_ttl_seconds", "recv_timeout", "max_seconds",
                   "recover_every", "store_fail_limit", "max_size", "op_deadline_seconds"):
            assert document[key] == field.default, key
    for key in ("relay_url", "custody_dir", "store_dsn_file", "org_d"):
        assert re.fullmatch(r"@[A-Z_]+@", document[key]), key


def test_the_compose_template_is_the_a4_relay_stack_without_s3_secrets_or_a_public_port():
    text = (DEPLOY / COMPOSE).read_text(encoding="utf-8")
    template = yaml.safe_load(text)
    fixture = yaml.safe_load(A4_COMPOSE.read_text(encoding="utf-8"))
    images = {name: service["image"] for name, service in template["services"].items()}
    assert set(images) == {"relay", "postgres", "redis"}
    assert images == {name: fixture["services"][name]["image"] for name in images}, "the A4 digests are kept"
    assert set(template["volumes"]) == {"buzz-postgres-data", "buzz-redis-data", "buzz-git-data"}
    assert template["services"]["relay"]["ports"] == [
        {"target": 3000, "published": "@RELAY_PORT@", "host_ip": "127.0.0.1", "protocol": "tcp"}]
    assert all("ports" not in service for name, service in template["services"].items() if name != "relay")
    assert all(service["env_file"] == ["@ENV_FILE@"] for service in template["services"].values())
    assert "minio" not in yaml.safe_dump(template).lower(), "no S3-compatible service"
    assert "MEDIA IS UNAVAILABLE" in text
    assert not [key for key in template["services"]["relay"]["environment"] if key.startswith("BUZZ_S3")]


# -- one planted violation per rule ------------------------------------------------------------------------------------

def test_a_port_that_is_not_loopback_is_named_by_line(tmp_path):
    hit = expect_violation(tmp_path, COMPOSE, "host_ip: 127.0.0.1", "host_ip: 0.0.0.0", "port")
    assert f"{COMPOSE}:{line_number(COMPOSE, 'target: 3000')}:" in hit


def test_a_short_form_public_port_is_refused(tmp_path):
    expect_violation(tmp_path, COMPOSE, "    ports:\n      - target: 3000\n        published: \"@RELAY_PORT@\"\n"
                     "        host_ip: 127.0.0.1\n        protocol: tcp\n", "    ports:\n      - \"0.0.0.0:3000:3000\"\n",
                     "port", "0.0.0.0:3000:3000")


def test_an_image_that_is_not_by_digest_is_refused(tmp_path):
    expect_violation(tmp_path, COMPOSE, "redis:7-alpine@sha256:", "redis:7-alpine@sha1:", "image", "redis:7-alpine@sha1")
    expect_violation(tmp_path, COMPOSE, "postgres:17-alpine@sha256:b0f9560a2de083e2cc7382e75f808c7381a32852a7ec49117deedb300e552b24",
                     "postgres:17-alpine", "image", "postgres:17-alpine")


@pytest.mark.parametrize("planted", ["    privileged: true\n", "    network_mode: host\n", "    cap_add:\n      - NET_ADMIN\n"])
def test_privileged_host_network_and_cap_add_are_refused(tmp_path, planted):
    expect_violation(tmp_path, COMPOSE, "    restart: unless-stopped\n    networks:\n      - internal\n      - edge\n",
                     "    restart: unless-stopped\n" + planted + "    networks:\n      - internal\n      - edge\n", "forbidden")


def test_the_docker_socket_is_refused(tmp_path):
    expect_violation(tmp_path, COMPOSE, "      - buzz-git-data:/data/git\n",
                     "      - buzz-git-data:/data/git\n      - /var/run/docker.sock:/var/run/docker.sock\n", "forbidden",
                     "docker socket")


def test_a_stop_timeout_below_op_deadline_plus_five_is_refused(tmp_path):
    expect_violation(tmp_path, UNIT, "TimeoutStopSec=45", "TimeoutStopSec=5", "stop-timeout", "TimeoutStopSec=5")
    expect_violation(tmp_path, UNIT, "TimeoutStopSec=45", "TimeoutStopSec=41", "stop-timeout")  # below 20 + 5 + 15 + 2 (D6)
    code, out = lint(plant(tmp_path, UNIT, "TimeoutStopSec=45", "TimeoutStopSec=42s"))
    assert code == 0, out


def test_the_stop_timeout_follows_the_config_templates_op_deadline(tmp_path):
    target = plant(tmp_path, CONFIG, '"op_deadline_seconds": 20', '"op_deadline_seconds": 40')
    code, out = lint(target)
    assert code == 1 and "stop-timeout" in out, out


def test_a_missing_kill_mode_is_refused(tmp_path):
    expect_violation(tmp_path, UNIT, "KillMode=mixed\n", "", "kill-mode")


def test_a_missing_stop_timeout_is_refused(tmp_path):
    expect_violation(tmp_path, UNIT, "TimeoutStopSec=45\n", "", "stop-timeout")


@pytest.mark.parametrize(("relative", "old", "new"), [
    (COMPOSE, '      RUST_LOG: ', '      POSTGRES_PASSWORD: hunter2hunter2\n      RUST_LOG: '),
    (COMPOSE, '      RUST_LOG: ', '      BUZZ_RELAY_PRIVATE_KEY: ' + "ab" * 32 + '\n      RUST_LOG: '),
    (COMPOSE, '      RUST_LOG: ', '      SOME_API_TOKEN: sk-abcdefghijklmnop\n      RUST_LOG: '),
    (COMPOSE, '      RUST_LOG: ', '      DATABASE_URL: ' + SCHEME + 'buzz:hunter2@postgres:5432/buzz\n      RUST_LOG: '),
    (UNIT, "Environment=PYTHONUNBUFFERED=1", "Environment=BUZZ_TOKEN=abc123"),
    (UNIT, "Environment=PYTHONUNBUFFERED=1", "EnvironmentFile=@SECRET_ENV@"),
    (UNIT, "Environment=PYTHONUNBUFFERED=1", "Environment=NOTE=nsec1qqqqqqqqqqqqqqqqqqqqqqqq"),
    (CONFIG, '"custody_dir": "@CUSTODY_DIR@"', '"custody_dir": "@CUSTODY_DIR@", "api_secret": "' + "cd" * 32 + '"'),
])
def test_a_secret_shaped_literal_is_refused(tmp_path, relative, old, new):
    expect_violation(tmp_path, relative, old, new, "secret")


def test_a_boolean_under_a_secret_named_key_is_not_a_secret():
    # BUZZ_REQUIRE_AUTH_TOKEN: "true" is in the template and the lint passes on it (test_the_lint_passes_on_the_templates)
    assert "BUZZ_REQUIRE_AUTH_TOKEN" in (DEPLOY / COMPOSE).read_text(encoding="utf-8")


def test_an_unknown_config_key_is_named_by_line(tmp_path):
    hit = expect_violation(tmp_path, CONFIG, '"tick_seconds": 5', '"tick_secs": 5', "unknown-key", "tick_secs")
    assert f"{CONFIG}:{line_number(CONFIG, 'tick_seconds')}:" in hit
    # the removed key is also reported missing
    code, out = lint(plant(tmp_path, CONFIG, '"tick_seconds": 5', '"tick_secs": 5'))
    assert "missing-key" in out and "tick_seconds" in out


def test_a_config_value_the_bridge_would_refuse_is_refused(tmp_path):
    expect_violation(tmp_path, CONFIG, '"lease_ttl_seconds": 30', '"lease_ttl_seconds": 10', "config", "lease_ttl_seconds")
