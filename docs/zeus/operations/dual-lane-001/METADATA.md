# Worker profile metadata bootstrap — 2026-09-17

Scope: the Bootstrap implementation contract of SPEC.md "Metadata residual resolution" only.
Base revision 2afacfb. The actual canary, its receipt and issue124 closure are not part of this.
The original harness lane stays failed/incomplete; nothing here re-labels it.

## Existing authority and disposition

Searched `src/` and `tests/` for `worker_profile`/`worker-profile`. Authority found:
`adapters/worker_profile.py` (`_normalized`, `_sha256`, `MAX_CHARACTERS`, `PROFILES`, `load_profile`),
`domain/evidence.authorized` with `resources/evidence-policy.json`, and
`adapters/evidence_inspection.replay_argv` (trusted interpreter for `python -m`).
Disposition: reuse. The new module imports the loader's normalization, hash and limit; it reads
bytes and decodes with universal newlines so it sees the text `Path.read_text("utf-8")` gives the
loader. No second hash or limit definition exists. `replay_argv` and project-evidence v1 untouched.

## What changed

- `adapters/worker_profile_metadata.py` (new): no-argument, read-only. Reads only
  `src/codex_harness/resources/worker-profile-v1.json` and `.md` under cwd; the manifest's
  `document` value is compared with the fixed name, never used as a path. Resolved paths outside
  cwd are refused. Reads are bounded (262144 bytes each; 6000 characters need at most 30000).
  Output schema `zeus.worker-profile-metadata/v1`: `characters`, `character_limit`,
  `document_sha256`, `digest_matches`, `within_limit`, `status`.
  Exit 0 match; exit 1 stale digest/overlength (computed facts kept) or a named input failure;
  exit 2 any argument. Error kinds: `invalid_invocation`, `path_unresolvable`, `path_outside_cwd`,
  `missing_file`, `not_a_file`, `unreadable_file`, `input_too_large`, `invalid_utf8`,
  `invalid_json`, `manifest_not_object`, `wrong_id`, `wrong_document`, `wrong_character_limit`,
  `internal_error`. Errors carry a kind and a fixed file name only.
- `worker-profile-v1.json`: one added allow,
  `Bash(python -m codex_harness.adapters.worker_profile_metadata)`. Every other field and the
  profile Markdown are unchanged, so `document_sha256` is unchanged. `manifest_sha256` and
  therefore `profile_digest` change, as for any manifest edit.
- `evidence-policy.json`: the three-token argv added; `policy_hash` changes accordingly.
- `domain/evidence.authorized`: an argv starting with those three tokens is authorized only when
  it equals them, even under a broader prefix; every other command keeps prefix semantics.
- `AGENTS.md`: how workers use the command and what it does not grant.

## Choices the contract left open

- Input failures (missing, invalid, escaped, oversized) exit 1, the same as stale metadata; only
  an argument is exit 2. The JSON `status`/`error.kind` distinguishes them.
- A missing or non-text `document_sha256` is reported as `digest_matches: false` with the computed
  digest (repairable), not as a refusal.
- No test pins the document digest: the canary must be able to change profile md/json only.

## Limits

Metadata observation, not profile certification: hook digest, sources and permission rules are
not checked here; `load_profile` is. Not transactional: the loader rechecks the final bytes.
Permission delivery by the installed Claude CLI is not shown by these tests; the canary decides it.
Rollback: remove the module, the allow rule, the policy entry and the `authorized` guard.
