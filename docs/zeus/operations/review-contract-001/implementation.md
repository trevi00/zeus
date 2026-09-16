# review-contract-001 implementation record

2026-09-16. Claude implementation of SPEC.md under the worker-v1 profile, one bounded batch.
Independent review, the full PostgreSQL/Redis suite, CI, the real canary and PG acceptance are
Codex follow-ups; nothing here is a provider measurement or an acceptance.

## Files

- `src/codex_harness/adapters/evidence_inspection.py`: `trusted_interpreter()` verifies the host
  `sys.executable` (absolute, existing file) before any child; `replay_argv()` rewrites only the
  first token of an already authorized `python -m ...` claim; `replay_environment(cwd=)` binds
  PYTHONPATH to `<cwd>/src` only when it exists; `snapshot(cwd=None)` binds interpreter, normalized
  cwd and the environment digest; `inspect()` / `inspect_command()` take the snapshot's
  `environment` and `interpreter`; findings carry `original_argv`, `replay_argv`,
  `argv_identical`, `argv_transformation`, `interpreter`; the context carries `interpreter` and
  `pythonpath`. `EvidenceInspector(..., interpreter=)` exists for tests and refusal cases.
- `src/codex_harness/application/evidence_inspection.py`: `snapshot(cwd)` per workspace, ledger
  key `evidence-inspection-v4` (v3 rows stay untouched), the replay receives the snapshot's
  interpreter, and the identity check covers environment digest and interpreter.
- `src/codex_harness/adapters/executor.py`: `IMPLEMENTATION` property descriptions (tests =
  executed commands only; summary = results, skips, unrun), the implement objective repeats the
  rule, and `review_context(cwd)` (trusted interpreter, review cwd, `src` when present, stdout
  instruction) is added to `required` for read-only runs only.
- `src/codex_harness/adapters/app_server.py`: `READ_ONLY_INSTRUCTIONS` for thread/start and
  thread/resume: nothing created, modified or deleted in the checkout, tracked or untracked; frame
  and verdict in the response and stdout; assigned scope only.
- `src/codex_harness/resources/worker-profile-v1.md` (Reporting rule) and
  `worker-profile-v1.json` (document digest re-pinned to
  `77a7aed2366a4b1c3c8fb642f9f3abebc6ae273a9b76661602035dcd34ce6632`, 3420 characters).
- `AGENTS.md`: "Review checkout recording" section. `docs/contracts.md`: INV-EVIDENCE-001 gains
  the replay context and review recording paragraphs.
- `tests/test_evidence_inspection.py`, `tests/test_app_server.py`, `tests/test_worker_profile.py`.

## Limits and decisions a reviewer should check

- The claim parser is unchanged: `python -m pytest ... -> 23 passed` still parses the arrow and
  the count as argv tokens. Old claims are not reinterpreted; the generation contract now keeps
  such text out of `tests`.
- `uv run ...` and `ruff check` prefixes are replayed exactly as claimed. A claim naming an
  absolute interpreter is not the policy's `python -m` prefix and stays `not_checked`.
- The reviewer's post-run clean/HEAD checks and the dirty-workspace refusal are untouched.
- `review_context` is added to every read-only `_run` (review, plan, shortlist, diagnose); it is
  host-composed data only and changes no session recovery binding.
- Real-subprocess tests: the trusted-interpreter replay imports a module that exists only under
  the candidate's `src`, with PATH and the parent PYTHONPATH pointed at nonexistent directories
  before the snapshot and changed again after it. The missing-interpreter refusal runs through
  `EvidenceInspections` and the executor. The AppServer tests use the existing request fixture
  (no Codex process). Windows only in this call; Linux is CI's.

## Commands run in this call (focused verification only)

Run from the candidate checkout with the profile's `python` (Windows 11 host, 2026-09-16):

```
python -m pytest tests/test_evidence_inspection.py tests/test_app_server.py tests/test_worker_profile.py -q -rs
54 passed, 1 skipped in 11.79s
SKIPPED tests/test_evidence_inspection.py:261: Integration environment required  (postgres backend variant)

python -m pytest tests/test_workflow.py tests/test_context_recovery.py tests/test_output_validation.py tests/test_model_routing.py tests/test_execution_progress.py tests/test_project_skills.py tests/test_claude_execution.py tests/test_usage_limit.py tests/test_threshold_reviews.py -q -rs
168 passed, 31 skipped in 49.78s
SKIPPED: test_claude_execution.py integration cases (Integration environment required), test_usage_limit.py:194 (Local PostgreSQL required)

python -m ruff check .
All checks passed!
```

Not run in this call: the full pytest suite (PostgreSQL/Redis integration), CI, any real model
call, the real reviewer/canary cycle. Those remain Codex-owned.
