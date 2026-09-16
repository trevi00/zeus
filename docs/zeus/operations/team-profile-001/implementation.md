# worker-v1 profile implementation record

2026-09-16. Claude implementation of SPEC.md, first call. Independent review and the real canary
are Codex follow-ups; nothing here is a provider measurement.

## Files

- `src/codex_harness/adapters/worker_profile.py`: profile loading and verification, hook command
  quoting, settings merge, profile environment, per-session evidence directory, receipt reading.
- `src/codex_harness/resources/worker-profile-v1.md`: the document (3052 characters, limit 6000),
  newly written from the adapted principles; no upstream text copied. The verification section
  makes the full suite the default and allows a task to narrow verification explicitly when the
  lead owns the final verification; a narrowed run must report the full suite as not run, never
  as passed.
- `src/codex_harness/resources/worker-profile-v1.json`: manifest with id, version, document and
  hook sha256 (LF-normalized), Bash allow rules, and the four pinned sources from sources.json
  with their disposition.
- `src/codex_harness/resources/worker_profile_hook.py`: standalone stdlib hook.
- `src/codex_harness/adapters/claude_cli.py`: opt-in wiring; unconfigured behaviour unchanged.
- `tests/test_worker_profile.py`, `tests/claude_protocol_child.py` (`profile` scenario and
  `--append-system-prompt` in the fixture's option list).
- `docs/contracts.md`: INV-WORKER-PROFILE-001.

## Decisions that a reviewer should check

- Selection: `runtime.worker_profile == "worker-v1"` only. `None` and absence are unconfigured.
  Refusals happen in the constructor, before probe, so the executor's pre-entry path applies.
- Bash allowance: the manifest adds `Bash(python -m pytest:*)`, `Bash(python -m pytest)`,
  `Bash(python -m ruff:*)`, `Bash(python -m compileall:*)` and read-only git rules to the run's
  existing allow list. Deny rules and the permission mode are untouched. Whether the installed
  CLI treats `:*` as the prefix form is for the canary to confirm; the existing ` *` rules from
  the packaged policy remain in the list.
- Hook command quoting: double quotes, forward slashes, refusal of `" $ \` \ % ! ^ & | < > ;` and
  line breaks. Tested by running the command through `shell=True` on this host (cmd.exe) and by
  `shlex` parsing for POSIX. Not tested on Linux in this call.
- Evidence root: `runtime.profile_evidence_root` when set, else `<runtime_dir>/worker-profile`.
  One directory per session id; receipts are created with O_EXCL.
- Interpreter: `sys.executable` of the harness process unless `runtime.profile_interpreter` names
  another file; it must exist.

## Out of scope, left for Codex

- Host wiring of `worker_profile` / `profile_evidence_root` into the packaged provider policy or a
  host setting: `providers.py` is outside this task's allowed paths and `providers.json` was left
  unchanged to preserve unconfigured behaviour.
- The real Claude canary (SessionStart/PostToolUse receipts, actual test output, candidate diff).
- Independent PostgreSQL/Redis verification: the integration-marked tests skipped here because
  `HARNESS_INTEGRATION` was not set.

## Call history and test results

### First call (draft, not accepted)

The first Claude implementation call wrote the code, tests and documents listed above and then
timed out at the 900 second limit. Its working tree was preserved at base 34cd979 and was never
accepted. Whatever that call ran before the deadline is not recorded here; in particular no claim
is made that a full pytest run completed in it.

### Second call (2026-09-16, this record)

Scope assigned by the task: focused verification only. The full PostgreSQL/Redis suite is run
independently by Codex and was deliberately not run in this call.

Commands, run from the candidate checkout with the host venv interpreter:

```
PYTHONPATH=src python -m pytest tests/test_worker_profile.py -q
19 passed in 12.86s        (base 34cd979, before the document change)
19 passed in 4.40s         (after the document change and manifest re-pin)

python -m ruff check .
All checks passed!
```

Change made in this call: the profile document's verification section now states the
full-suite default and the explicit lead-owned narrowing rule, and the manifest's
`document_sha256` was re-pinned to the new LF-normalized digest. No adapter, hook or test code
was changed. Full pytest: not run by this call.
