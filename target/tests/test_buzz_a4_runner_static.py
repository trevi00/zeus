"""Buzz A4b: static guards on the owner-run runtime matrix runner and its compose file (no Docker, no network)."""

import ast
import re
from pathlib import Path

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "buzz_conntest"
RUNNER = FIXTURE / "run_matrix.py"
COMPOSE = FIXTURE / "compose.yaml"


def test_runner_parses_and_has_no_provider_guard_import():
    tree = ast.parse(RUNNER.read_text(encoding="utf-8"))  # D-A4-1: the guard is neither imported nor bypassed
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
    assert not {name for name in imported if "provider_guard" in name}
    assert "pytest" not in imported, "the runner is not a pytest module"


def test_compose_has_no_placeholder_and_pins_every_image():
    text = COMPOSE.read_text(encoding="utf-8")
    assert "__DIGEST_TBD__" not in text
    images = re.findall(r"^\s+image:\s*(\S+)\s*$", text, flags=re.MULTILINE)
    assert len(images) == 5
    assert all(re.search(r"@sha256:[0-9a-f]{64}$", image) for image in images), images


def test_compose_publishes_the_relay_on_loopback_only_and_is_unprivileged():
    text = COMPOSE.read_text(encoding="utf-8")
    code = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    assert code.count("published:") == 1 and "host_ip: 127.0.0.1" in code
    assert "0.0.0.0:" not in code.replace("BUZZ_BIND_ADDR: 0.0.0.0:3000", "")
    for forbidden in ("privileged", "network_mode", "cap_add", "docker.sock"):
        assert forbidden not in code, forbidden


def test_b7_send_buffer_is_set_on_the_relay_with_the_test_only_comment():
    text = COMPOSE.read_text(encoding="utf-8")
    assert 'BUZZ_SEND_BUFFER: "8"' in text and "never production" in text
