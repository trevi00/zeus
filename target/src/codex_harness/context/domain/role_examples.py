"""Canonical role examples: the closed shape, bounds and selection of the packaged resource.

Layer: domain
Context: context
Owns: validation of the role-examples document (schema, version, role set, 3-5 examples per role, kinds,
field bounds, secret and path shapes) and selection of one role's examples in file order
Does not own: prompt delivery (S10, D10), the packaged file read (context.adapters.role_examples)
Entry points: validate, select
Contracts: INV-CONTEXT-001

REFERENCE-ONLY in S4 (delivery is "reference_only_until_S10"): nothing here reaches a prompt, because
delivery changes bytes that the M7-equal goldens pin.
"""

from __future__ import annotations

import re

from codex_harness.kernel.errors import ContractError, require

SCHEMA = "urn:zeus:role-examples:1"
VERSION = 1
DELIVERY = "reference_only_until_S10"
KINDS = ("normal", "variation")
MIN_EXAMPLES, MAX_EXAMPLES = 3, 5
MAX_FIELD = 300
# Local closed set: context may not import observation's redaction.
FORBIDDEN = re.compile(r"sk-|ghp_|github_pat_|-----BEGIN|/home/|/srv/|C:\\|\w@\w")


def _clean(text, label: str, limit: int | None) -> None:
    require(type(text) is str and bool(text.strip()), label + " must be a non-empty string")
    require(limit is None or len(text) <= limit, label + " is too long")
    require(FORBIDDEN.search(text) is None, label + " carries a secret or path shape")


def validate(document: dict, agents: list[str]) -> dict:
    require(isinstance(document, dict), "Role examples must be an object")
    require(document.get("schema") == SCHEMA, "Wrong role examples schema")
    require(document.get("version") == VERSION, "Wrong role examples version")
    require(document.get("delivery") == DELIVERY, "Role examples delivery must be reference-only")
    roles = document.get("roles")
    require(isinstance(roles, dict), "Role examples need a roles object")
    require(set(roles) == set(agents), "Role examples roles must equal the organization agents")
    for role, entry in roles.items():
        require(isinstance(entry, dict) and set(entry) == {"basis", "examples"},
                role + " entry must carry exactly basis and examples")
        _clean(entry["basis"], role + " basis", None)
        examples = entry["examples"]
        require(isinstance(examples, list) and MIN_EXAMPLES <= len(examples) <= MAX_EXAMPLES,
                role + " needs 3-5 examples")
        for example in examples:
            require(isinstance(example, dict) and set(example) == {"kind", "input", "action", "result"},
                    role + " example must carry exactly kind, input, action, result")
            require(example["kind"] in KINDS, role + " example kind is unknown")
            for field in ("input", "action", "result"):
                _clean(example[field], role + " " + field, MAX_FIELD)
        kinds = [example["kind"] for example in examples]
        require(kinds.count("normal") >= 2 and kinds.count("variation") >= 1,
                role + " needs 2 normal and 1 variation examples")
    return document


def select(document: dict, role: str) -> list[dict]:
    roles = document.get("roles") if isinstance(document, dict) else None
    if not isinstance(roles, dict) or role not in roles:
        raise ContractError("Unknown role for examples")
    return list(roles[role]["examples"])
