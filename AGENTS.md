# Codex harness implementation rules

## Local workspace placement

- On this Windows host, put new worktrees under `D:\workspaces\zeus\worktrees`, raw evidence under `D:\workspaces\zeus\artifacts`, and temporary work under `D:\workspaces\zeus\scratch`. WSL accesses these through `/mnt/d/workspaces/zeus`. Do not create review folders directly under the user's home.
- The existing active repository `C:\Users\rudtn\zeus` remains a compatibility exception. Keep small tracked specs, summaries, and manifests in Git. Do not move tracked documents out of a checkout independently of Git.
- Reuse a task's worktree for repeat reviews; preserve dirty and ignored evidence before cleanup. Relocated Python virtual environments may contain old absolute paths: recreate them at the new path before use. Follow `D:\workspaces\README.md` for this host's directory layout.

- This is a new Codex harness. Reference repositories are not implementation roots.
- Domain and application depend only on the standard library and inner contracts.
- Scripts/CLI invoke use cases; do not duplicate domain policy in shell scripts.
- Inter-agent messages use the versioned six-W JSON schema in package resources.
- Git is authoritative for definitions; PostgreSQL is authoritative for runtime records.
- Cite contract IDs in comments where behavior is non-obvious. Contracts live in docs/contracts.md.
- Test recurrence deduplication, stale writes, authorization, context overflow, and promotion failures.
- Never report simulated review/canary as an actual Codex or GitHub production verification.
- Run `uv run ruff check .` and `uv run pytest` after code changes.
- Reference adoption follows `docs/research-standard.md`. README summaries are discovery only.
- Every reference review pins a commit, inventories every tracked path, traces implementations and
  callers against contracts/configuration/tests, and records coverage and unknowns. Inventory is
  not semantic review; an upstream test file is not evidence that the test was executed.
- Never mark a repository fully analyzed while files or subsystems remain unreviewed. Carry forward
  remaining work using immutable evidence references and bounded context, rather than skipping it.

## Two-strike research before another correction

- After two distinct attempts encounter the same or similar failure, including repeated material
  review rejection, stop repeating that approach. A replayed log/event is not a second attempt.
  Similar symptoms open an investigation; they do not establish a shared root cause.
- Reuse the task's existing frame. Search the SSOT, responsible code and source-backed experience;
  consult relevant primary documentation when needed. Record sources/version/date, observations,
  hypotheses and one discriminating check before choosing one coherent correction batch.
- Keep the investigation bounded by the original goal and material acceptance conditions. If it
  needs unavailable evidence or authority, hand that exact gap to the lead. Do not recursively
  spawn investigations or keep retrying until green; minor findings remain follow-up notes.
- Verify the correction against the affected criteria and preserve failed attempts. A hook's
  research-required notice is not proof that research ran or that knowledge was verified.
  Only the existing independent review/promotion path can accept the resulting change.

## Review checkout recording

- An independent review runs in a clean checkout at the candidate commit. Do not create, modify or
  delete any file there, tracked or untracked: no frame files, logs, notes or redirected test output.
  Collect test output from stdout.
- Record one concise review frame and verdict in the response and tool stdout. Zeus preserves the
  response and tool output in its artifact store under `D:\workspaces\zeus\artifacts`, outside the
  checkout; no additional frame file is written anywhere.
- Inspect only the assigned review input. Full re-verification (PostgreSQL/Redis suite, CI) belongs
  to the named owner or CI. The executor's clean-checkout and HEAD checks stay as they are; a dirty
  checkout is refused, never cleaned automatically, and a model run's permission settings are not an
  isolation guarantee.
- Worker answers keep executed commands and result descriptions apart. Legacy (no host project
  evidence profile): `tests` holds only the exact commands that were run, one per string. With a
  host profile (INV-PROJECT-EVIDENCE-001): `tests` holds one `{check_id, status, exit_code}`
  observation per host-declared check, failures and `not_run` included; run the host's delivered
  commands verbatim (version 1 checks are `python -m pytest`/`python -m ruff check` only, under the
  context interpreter, not `python` on PATH). Either way results, skips,
  diagnostic attempts and unrun work go in `summary`.

## Worker profile packaging metadata

- After changing `src/codex_harness/resources/worker-profile-v1.md`, a worker runs exactly
  `python -m codex_harness.adapters.worker_profile_metadata` from the checkout root, with no
  arguments, and copies the reported `document_sha256` into `worker-profile-v1.json` with Edit. The
  JSON observation carries the normalized character count, the 6000 limit, the computed digest,
  `digest_matches` and `within_limit`. Exit 0: the manifest matches. Exit 1: stale digest, overlong
  document or a named input failure (the computed facts are still reported when they exist).
  Exit 2: arguments were passed.
- The command is read-only and fixed to the document, manifest and packaged hook at their three
  cwd-relative paths. It also reports `hook_sha256`, `hook_digest_matches` and `hook_status`;
  an undeclared hook remains explicitly `not_declared`, not a profile-validity verdict. The profile grants this one
  exact command and the evidence policy replays this one exact argv: no arbitrary Python
  (`python -c`, scripts, other modules), no arguments and no other paths. It observes metadata only;
  `worker_profile.load_profile` and the profile tests remain the authority over the final bytes.
- An expected failing run (a stale digest before the repair) is a diagnostic attempt: report it in
  `summary` with its observed exit; legacy `tests` lists the final successful command.
