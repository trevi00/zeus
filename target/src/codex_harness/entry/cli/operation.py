"""The operation CLI helpers shared by the `zeus` roots (M7 adapters/operation_cli.py).

Layer: entry
Owns: MAX_MANIFEST_BYTES, read_document, read_manifest (the bounded duplicate-key-refusing JSON reader), bind_goal (the goal file bound at the manifest's base revision) and refusal (the code-and-type a CLI prints for a failure)
Does not own: the `zeus operate` and `zeus autonomous` bodies (entry.cli.operate, entry.cli.autonomous), the policy, identity and session owner (composition.cli_operation) and the root parsers (the modules of this package)
Entry points: MAX_MANIFEST_BYTES, read_document, read_manifest, bind_goal, refusal
Contracts: none

Moved from M7 adapters/operation_cli.py:23-46 and :178-183 (SOURCE e38aa722) by named rule R-c11 (S10 unit C7a); the function bodies are M7's verbatim, with the import homes of the target (`kernel.errors`).
`bind_goal` is M7 adapters/operation_cli.py:72-78 by named rule R-c24 (S10 unit C6a), verbatim, with `OperationRefused` (`coordination.application.operation`) and `goal_binding` (`coordination.domain.operation`) at their target homes.
"""

import json
from pathlib import Path

from codex_harness.coordination.application.operation import OperationRefused
from codex_harness.coordination.domain.operation import goal_binding
from codex_harness.kernel.errors import ContractError, require

MAX_MANIFEST_BYTES = 256 * 1024


def read_document(path: Path, label: str) -> dict:
    """Bounded UTF-8 JSON with duplicate keys refused; errors name the file role, not its content.
    utf-8-sig drops one optional leading BOM from operator-authored files: the raw byte budget still
    counts it, interior U+FEFF stays data, and malformed UTF-8 or UTF-16 remains refused."""
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, label + " has a duplicate JSON key")
            result[key] = value
        return result
    try:
        require(path.stat().st_size <= MAX_MANIFEST_BYTES, label + " exceeds budget")
        return json.loads(path.read_text(encoding="utf-8-sig"), object_pairs_hook=unique)
    except OSError as exc:
        raise ContractError(label + " unavailable") from exc
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ContractError(label + " is not valid JSON") from exc


def read_manifest(path: Path) -> dict:
    return read_document(path, "Operation manifest")


def bind_goal(manifest: dict, source) -> dict:
    if not source.commit_exists(manifest["base_revision"]):
        raise OperationRefused("base_revision_missing")
    mode, data = source.blob(manifest["base_revision"], manifest["goal"]["path"])
    if mode is None:
        raise OperationRefused("goal_missing_at_base")
    return goal_binding(manifest, mode, data)


def refusal(exc: Exception) -> dict:
    """What the CLI prints for a failure: a code and a type, never the raw text or a value."""
    code = getattr(exc, "reason_code", None)
    if code is None and isinstance(exc, ContractError):
        code = "contract_refused"
    return {"status": "refused", "reason_code": code or "error", "error_type": type(exc).__name__, "exit_code": 1}
