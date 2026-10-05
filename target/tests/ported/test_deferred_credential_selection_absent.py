# Ported from SOURCE M7 tests/test_deferred_credential_selection_absent.py (REBUILD-DESIGN-v2 §3.1 target tests): only the import paths
# are rewritten to the target tree; assertions are unchanged unless a comment below names the adaptation.
"""The automatic worker-credential selection is DEFERRED (root §10k): it is absent from the candidate, so no
configured service, CLI command or Fleet dispatch can reach it. The H1 launch uses an explicitly MANUAL credential
through the managed unit's environment; a provider refusal of that credential is contained (tests/test_usage_limit.py),
never answered by switching to another credential."""
import importlib
from pathlib import Path

import pytest

from codex_harness import cli

SRC = Path(__file__).resolve().parents[2] / "src" / "codex_harness"  # S11 M B3: target/tests/ported -> target/src


@pytest.mark.parametrize("module", ["codex_harness.domain.worker_credentials",
                                    "codex_harness.application.worker_credentials",
                                    "codex_harness.adapters.worker_credentials",
                                    "codex_harness.adapters.worker_credentials_cli"])
def test_the_deferred_selector_modules_do_not_exist(module):
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module(module)


def test_no_cli_command_and_no_setting_reaches_a_credential_selector():
    with pytest.raises(SystemExit):
        cli.parser().parse_args(["worker-credentials", "status"])
    sources = [p.read_text("utf-8") for p in SRC.rglob("*.py")]
    assert not any("ZEUS_WORKER_CREDENTIALS" in text or "worker_credentials" in text for text in sources)
