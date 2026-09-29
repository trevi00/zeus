"""Reference driver: `credentials.custody` on SOURCE M7 (REBUILD-DESIGN-v2 §5.3 S3, R-C first).

M7 `adapters.role_containers`: the Codex credential broker (store, lock, ledger, quarantine, validated
write-back) and the output-boundary scrubber, over dummy credentials the scenario writes into its own
temporary directory. No real store, home, provider or container is touched.
"""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

from types import SimpleNamespace  # noqa: E402

import s3_credentials  # noqa: E402

from codex_harness.adapters import role_containers as rc  # noqa: E402
from codex_harness.domain.model import ContractError  # noqa: E402

API = SimpleNamespace(
    Broker=rc.CodexCredentialBroker, read_credential_file=rc.read_credential_file,
    credential_shape=rc.credential_shape, credential_values=rc.credential_values, Scrubber=rc.CredentialScrubber,
    OutputUnsanitizable=rc.OutputUnsanitizable, REDACTED=rc.REDACTED, REDACTED_JWT=rc.REDACTED_JWT,
    MIN_SECRET_CHARS=rc.MIN_SECRET_CHARS, MAX_AUTH_BYTES=rc.MAX_AUTH_BYTES, IsolationError=rc.IsolationError,
    ContractError=ContractError)

if __name__ == "__main__":
    driver.finish("reference", "credentials.custody", s3_credentials.run_custody(API))
