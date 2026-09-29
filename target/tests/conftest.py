"""Target test session guards (REBUILD-DESIGN-v2 §5.2 R-O, R-P, R-X).

- R-P: the provider audit hook is installed before any test runs; children get the fake-provider
  PATH, empty homes and no credential-named variables through `provider_guard.child_environment`.
- R-O: an import audit refuses any `codex_harness`/`zeus` import whose origin is outside the target
  tree, and the session ends by asserting every loaded module's origin. The reference implementation
  is never importable from here: there is no fallback.
- R-X: the session refuses to start when a database/Redis setting points at a production port;
  runtime tests use disposable, labelled resources only. Values are never printed.
"""

import os
import sys
from pathlib import Path

import pytest

TARGET = Path(__file__).resolve().parents[1]
ROOT = TARGET.parent
TARGET_SRC = TARGET / "src"
sys.path.insert(0, str(ROOT / "compare" / "guard"))
sys.path.insert(0, str(ROOT / "compare" / "harness"))

import origin  # noqa: E402
import provider_guard  # noqa: E402

provider_guard.install()
origin.install_import_audit(TARGET_SRC)

PRODUCTION_PORTS = (":55432", ":56379")
ENDPOINT_NAMES = ("ZEUS_DATABASE_URL", "HARNESS_DATABASE_URL", "DATABASE_URL", "ZEUS_REDIS_URL",
                  "HARNESS_REDIS_URL", "REDIS_URL", "ZEUS_TEST_DSN", "ZEUS_TEST_REDIS_URL")


def production_endpoint(value: str | None) -> bool:
    return bool(value) and any(port in value for port in PRODUCTION_PORTS)


def pytest_configure(config):
    named = [name for name in ENDPOINT_NAMES if production_endpoint(os.environ.get(name))]
    if named:
        pytest.exit(f"R-X: refusing to run with production endpoints in {named}", returncode=4)


def pytest_sessionfinish(session, exitstatus):
    origin.assert_tree_origins(TARGET_SRC)


@pytest.fixture
def child_env(tmp_path):
    return provider_guard.child_environment(tmp_path / "child")
