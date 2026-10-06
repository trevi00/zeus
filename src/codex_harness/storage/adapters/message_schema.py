"""Six-W message JSON-Schema validation (the packaged `message.schema.json`).

Layer: adapters
Context: storage
Owns: the jsonschema check of one message before it is published or after it is decoded
Does not own: the message shape (kernel.message); the observation schema (observation, S9)
Entry points: validate_message
Contracts: INV-MESSAGE-001

Moved out of the kernel (design v2 §1.2 correction) because it needs `jsonschema`; the error text is
the M7 text (path and message of at most five errors) except that a message echoing the offending value is replaced
by the path and the rule keyword (XC-1 A2, an intended difference declared in `kernel.values`).
"""

import json
from importlib.resources import files

from jsonschema import Draft202012Validator, FormatChecker

from codex_harness.kernel.errors import ContractError

SCHEMA = json.loads(files("codex_harness.resources").joinpath("message.schema.json").read_text())
VALIDATOR = Draft202012Validator(SCHEMA, format_checker=FormatChecker())


def _reason(error) -> str:
    # XC-1 A2 (TQ-XCUT-PLAN, OWASP logging): the jsonschema message echoes the offending VALUE, which reaches
    # the dead-letter reason and the `serve` output. The field path and the rule keyword name the failure
    # without it. `required` is schema-derived text (the missing property's name), so it keeps its M7 text.
    if error.validator == "required":
        return f"{list(error.path)}: {error.message}"
    return f"{list(error.path)}: {error.validator} rule violated"


def validate_message(message: dict) -> dict:
    errors = sorted(VALIDATOR.iter_errors(message), key=lambda e: str(e.path))
    if errors:
        raise ContractError("; ".join(_reason(e) for e in errors[:5]))
    return message
