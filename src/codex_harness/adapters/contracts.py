import json
from importlib.resources import files

from jsonschema import Draft202012Validator, FormatChecker

from codex_harness.domain.model import ContractError

SCHEMA = json.loads(files("codex_harness.resources").joinpath("message.schema.json").read_text())
VALIDATOR = Draft202012Validator(SCHEMA, format_checker=FormatChecker())
OBSERVATION_SCHEMA = json.loads(files("codex_harness.resources").joinpath("observation.schema.json").read_text())
OBSERVATION_VALIDATOR = Draft202012Validator(OBSERVATION_SCHEMA, format_checker=FormatChecker())


def validate_message(message: dict) -> dict:
    errors = sorted(VALIDATOR.iter_errors(message), key=lambda e: str(e.path))
    if errors:
        raise ContractError("; ".join(f"{list(e.path)}: {e.message}" for e in errors[:5]))
    return message


def validate_observation(event: dict) -> dict:
    """INV-OBSERVATION-001: the versioned observation schema, a different contract from six-W."""
    errors = sorted(OBSERVATION_VALIDATOR.iter_errors(event), key=lambda e: str(e.path))
    if errors:
        raise ContractError("; ".join(f"{list(e.path)}: {e.message}" for e in errors[:5]))
    return event
