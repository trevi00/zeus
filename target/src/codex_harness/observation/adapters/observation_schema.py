"""The observation JSON-Schema validation (the packaged `observation.schema.json`).

Layer: adapters
Context: observation
Owns: the jsonschema check of one observation event before it is spooled or collected
Does not own: the observation shape and its builder (`observation.domain.observation`), the six-W message schema (`storage.adapters.message_schema`), the collector that applies the check (`observation.application.observations`, injected as `validate`), its composition (S10)
Entry points: validate_observation
Contracts: INV-OBSERVATION-001

Moved from the observation half of M7 `adapters/contracts.py` (SOURCE e38aa722) through named rules (S9 batch L2-B1, A/evidence/rebuild/s9/l2-b1/transcribe.py): R-sc0 (`OBSERVATION_SCHEMA`, `OBSERVATION_VALIDATOR` and `validate_observation` are M7's, verbatim), R-sc1 (`ContractError` from `kernel.errors`); the error text is M7's: the path and the failed keyword only, never the instance value, which the differential compares exactly.
"""

import json
from importlib.resources import files

from jsonschema import Draft202012Validator, FormatChecker

from codex_harness.kernel.errors import ContractError

OBSERVATION_SCHEMA = json.loads(files("codex_harness.resources").joinpath("observation.schema.json").read_text())
OBSERVATION_VALIDATOR = Draft202012Validator(OBSERVATION_SCHEMA, format_checker=FormatChecker())


def validate_observation(event: dict) -> dict:
    """INV-OBSERVATION-001: the versioned observation schema, a different contract from six-W.

    The error names the path and the failed keyword only. jsonschema's default message repeats
    the offending instance value, which is exactly what a refused record must not carry into
    quarantine rows or health files.
    """
    errors = sorted(OBSERVATION_VALIDATOR.iter_errors(event), key=lambda e: str(e.path))
    if errors:
        raise ContractError("; ".join(f"{list(e.path)}: {e.validator}" for e in errors[:5]))
    return event
