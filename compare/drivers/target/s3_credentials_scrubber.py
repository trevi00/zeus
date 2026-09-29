"""Target driver: `credentials.scrubber` on the target tree (codex_harness.credentials).

The broker and scrubber are the target's credentials adapters over the credentials domain; the same
scenario body as the reference writes dummy credentials into its own temporary directory.
"""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

from types import SimpleNamespace  # noqa: E402

import s3_credentials  # noqa: E402
from codex_harness.credentials.adapters.codex_custody import (  # noqa: E402
    CodexCredentialBroker,
    read_credential_file,
)
from codex_harness.credentials.adapters.scrubber import (  # noqa: E402
    CredentialScrubber,
    OutputUnsanitizable,
)
from codex_harness.credentials.domain import codex_credential as cc  # noqa: E402
from codex_harness.kernel.errors import ContractError, IsolationError  # noqa: E402

API = SimpleNamespace(
    Broker=CodexCredentialBroker, read_credential_file=read_credential_file,
    credential_shape=cc.credential_shape, credential_values=cc.credential_values, Scrubber=CredentialScrubber,
    OutputUnsanitizable=OutputUnsanitizable, REDACTED=cc.REDACTED, REDACTED_JWT=cc.REDACTED_JWT,
    MIN_SECRET_CHARS=cc.MIN_SECRET_CHARS, MAX_AUTH_BYTES=cc.MAX_AUTH_BYTES, IsolationError=IsolationError,
    ContractError=ContractError)

if __name__ == "__main__":
    driver.finish("target", "credentials.scrubber", s3_credentials.run_scrubber(API))
