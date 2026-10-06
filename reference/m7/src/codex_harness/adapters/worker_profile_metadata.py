"""Read-only packaging metadata for the worker profile (INV-WORKER-PROFILE-001, issue 124).

`python -m codex_harness.adapters.worker_profile_metadata` takes no argument. It reads exactly three
cwd-relative files, the worker-v1 document, its packaged hook and its manifest, and prints one JSON
observation: the normalized character count, the limit, the computed `document_sha256`, the computed
`hook_sha256` and whether the manifest agrees with both. A stale digest or an overlong document
still reports the computed facts (exit 1) so the worker can repair the manifest with Edit. A
manifest that names no hook is reported as `hook_status: not_declared` and decides nothing. It
writes nothing, follows no path named by the manifest and never prints file content or exception
text.

This verifies packaging metadata only. It does not certify the hook, the sources or the rest of the
manifest: `worker_profile.load_profile` remains the final authority over the actual final bytes.
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

from codex_harness.adapters.worker_profile import MAX_CHARACTERS, PROFILES, _normalized, _sha256

SCHEMA = "zeus.worker-profile-metadata/v1"
PROFILE_ID = "worker-v1"
RESOURCE_DIRECTORY = ("src", "codex_harness", "resources")
MANIFEST_NAME = PROFILES[PROFILE_ID]
DOCUMENT_NAME = "worker-profile-v1.md"
HOOK_NAME = "worker_profile_hook.py"
# Finite read bounds. 15000 characters are at most 60000 UTF-8 bytes (75000 with CRLF line ends);
# the document bound leaves room to measure an overlong candidate instead of only refusing it.
MAX_DOCUMENT_BYTES = 262144
MAX_MANIFEST_BYTES = 262144
MAX_HOOK_BYTES = 262144
EXIT_OK, EXIT_FAILED, EXIT_INVOCATION = 0, 1, 2


class _Refusal(Exception):
    """A safe failure: `kind` and `file` are fixed words, never content or exception text."""

    def __init__(self, kind: str, file: str):
        super().__init__(kind)
        self.kind, self.file = kind, file


def _read_text(cwd: Path, name: str, limit: int) -> str:
    """Bounded read of one fixed file under cwd, decoded the way the loader's `read_text` does."""
    try:
        resolved = cwd.joinpath(*RESOURCE_DIRECTORY, name).resolve()
    except (OSError, RuntimeError) as exc:
        raise _Refusal("path_unresolvable", name) from exc
    if not resolved.is_relative_to(cwd):
        raise _Refusal("path_outside_cwd", name)
    if not resolved.exists():
        raise _Refusal("missing_file", name)
    if not resolved.is_file():
        raise _Refusal("not_a_file", name)
    try:
        with open(resolved, "rb") as handle:
            data = handle.read(limit + 1)
    except OSError as exc:
        raise _Refusal("unreadable_file", name) from exc
    if len(data) > limit:
        raise _Refusal("input_too_large", name)
    try:
        # Universal newlines, exactly like Path.read_text("utf-8") in worker_profile.load_profile.
        return io.TextIOWrapper(io.BytesIO(data), encoding="utf-8", errors="strict", newline=None).read()
    except UnicodeDecodeError as exc:
        raise _Refusal("invalid_utf8", name) from exc


def _hook(cwd: Path, manifest: dict) -> dict:
    """The hook facts, reported beside the document ones (two-strike-001).

    The hook digest is computed exactly as `worker_profile.load_profile` computes it, so the worker
    can repair a stale `hook_sha256` with Edit after changing the packaged hook. A manifest that
    declares no hook is an observation about that manifest, not a failure of this command: only a
    declared hook that is missing, unreadable or different decides `mismatch`.
    """
    declared = manifest.get("hook")
    if declared is None:
        return {"hook": None, "hook_sha256": None, "hook_digest_matches": None,
                "hook_status": "not_declared"}
    if declared != HOOK_NAME:
        return {"hook": HOOK_NAME, "hook_sha256": None, "hook_digest_matches": False,
                "hook_status": "wrong_hook"}
    try:
        computed = _sha256(_read_text(cwd, HOOK_NAME, MAX_HOOK_BYTES))
    except _Refusal as refusal:
        return {"hook": HOOK_NAME, "hook_sha256": None, "hook_digest_matches": False,
                "hook_status": refusal.kind}
    matches = manifest.get("hook_sha256") == computed
    return {"hook": HOOK_NAME, "hook_sha256": computed, "hook_digest_matches": matches,
            "hook_status": "verified" if matches else "stale_digest"}


def observe(cwd: Path) -> dict:
    """The metadata observation for the checkout at `cwd`; every defect is a `_Refusal`."""
    cwd = cwd.resolve()
    manifest_text = _read_text(cwd, MANIFEST_NAME, MAX_MANIFEST_BYTES)
    try:
        manifest = json.loads(manifest_text)
    except (ValueError, RecursionError) as exc:
        raise _Refusal("invalid_json", MANIFEST_NAME) from exc
    if not isinstance(manifest, dict):
        raise _Refusal("manifest_not_object", MANIFEST_NAME)
    if manifest.get("id") != PROFILE_ID:
        raise _Refusal("wrong_id", MANIFEST_NAME)
    if manifest.get("document") != DOCUMENT_NAME:
        raise _Refusal("wrong_document", MANIFEST_NAME)
    limit = manifest.get("character_limit")
    if type(limit) is not int or limit != MAX_CHARACTERS:
        raise _Refusal("wrong_character_limit", MANIFEST_NAME)
    document = _normalized(_read_text(cwd, DOCUMENT_NAME, MAX_DOCUMENT_BYTES))
    computed = _sha256(document)
    digest_matches = manifest.get("document_sha256") == computed
    within_limit = len(document) <= MAX_CHARACTERS
    hook = _hook(cwd, manifest)
    agreed = digest_matches and within_limit and hook["hook_digest_matches"] is not False
    return {"schema": SCHEMA, "status": "ok" if agreed else "mismatch",
            "profile": PROFILE_ID, "document": DOCUMENT_NAME, "manifest": MANIFEST_NAME,
            "characters": len(document), "character_limit": MAX_CHARACTERS,
            "document_sha256": computed, "digest_matches": digest_matches,
            "within_limit": within_limit, **hook,
            "authority": "metadata observation only; worker_profile.load_profile decides validity"}


def _emit(body: dict) -> None:
    sys.stdout.write(json.dumps(body, ensure_ascii=True, sort_keys=True) + "\n")


def main(argv=None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments:
        _emit({"schema": SCHEMA, "status": "error", "error": {"kind": "invalid_invocation"},
               "usage": "python -m codex_harness.adapters.worker_profile_metadata (no arguments)"})
        return EXIT_INVOCATION
    try:
        body = observe(Path.cwd())
    except _Refusal as refusal:
        _emit({"schema": SCHEMA, "status": "error",
               "error": {"kind": refusal.kind, "file": refusal.file}})
        return EXIT_FAILED
    except Exception:  # noqa: BLE001 - the kind is reported, the exception text never is
        _emit({"schema": SCHEMA, "status": "error", "error": {"kind": "internal_error"}})
        return EXIT_FAILED
    _emit(body)
    return EXIT_OK if body["status"] == "ok" else EXIT_FAILED


if __name__ == "__main__":
    sys.exit(main())
