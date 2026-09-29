"""Six-W message JSON-Schema validation (the packaged `message.schema.json`).

Layer: adapters
Context: storage
Owns: the jsonschema check of one message before it is published or after it is decoded
Does not own: the message shape (kernel.message); the observation schema (observation, S9)
Entry points: validate_message
Contracts: INV-MESSAGE-001

Moved out of the kernel (design v2 §1.2 correction) because it needs `jsonschema`; the error text is
the M7 text (path and message of at most five errors), which the differential compares exactly.
"""

import json
from importlib.resources import files

from jsonschema import Draft202012Validator, FormatChecker

from codex_harness.kernel.errors import ContractError

SCHEMA = json.loads(files("codex_harness.resources").joinpath("message.schema.json").read_text())
VALIDATOR = Draft202012Validator(SCHEMA, format_checker=FormatChecker())


def validate_message(message: dict) -> dict:
    errors = sorted(VALIDATOR.iter_errors(message), key=lambda e: str(e.path))
    if errors:
        raise ContractError("; ".join(f"{list(e.path)}: {e.message}" for e in errors[:5]))
    return message
