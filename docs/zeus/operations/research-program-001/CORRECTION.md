# research-program-001 — correction for consolidated review001 (R1/R2/R3)

Worker correction on the task branch; the feature stays WIP and unaccepted until the owner's
independent review, the native Windows + PostgreSQL rerun, CI and the live canary pass. No SPEC
edit, no provider call, no git command against the user's checkout, no deploy, no scope change.

## Findings, fixes and actual checks (Linux, worker)

| Finding | Fix | Regression test (labelled fixtures noted) |
|---|---|---|
| R1 repository authority: a run from another clone of the same store/base reached the council and created a capture ref there | `ResearchProgram.reserve_cycle(program_id, repository)` now requires the CURRENT repository identity (`dge_cli.repository_identity` of the current root) and raises `repository_mismatch` inside the reservation transaction, before the busy/pause/deadline checks, before any log write, fetch, capture or model effect. `ProgramRunner` carries the identity; `research_program_cli.run` passes `repository_identity(repository_root())`. Register is unchanged. | `test_r1_wrong_repository_refuses_before_any_effect_and_the_registered_root_continues` (real `git clone` B of real temp repo A, same MemoryStore: 0 cycle rows, `next_cycle` 1, 0 feed calls, 0 council calls, 0 `refs/zeus/*` in A and B, no runtime directory; A then ticks normally). CLI path: `test_run_in_another_real_clone_is_refused_before_any_effect` (`ZEUS_REPOSITORY` switched to the clone; refusal `repository_mismatch`, exit 1, then the registered root runs). Unit tests now register with the real identity of the temp repository instead of a placeholder string. |
| R2 pre-dispatch ownership: an artifact/manifest write failure after capture escaped, leaving `captured` + indefinite busy with no reason | The post-capture, pre-provider phase is stage-tracked: `capture_record`, `manifest_derive`, `manifest_artifact`, `manifest_file`, `council_start`. Any failure calls `fail_cycle(stage, type-or-code, recovery={capture})`: cycle `failed`, counted, program `blocked` with `<stage>:<code>`, claim kept, capture reference kept on the cycle and copied into `failure.capture`; zero council calls. If `fail_cycle` itself raises (store unavailable), the receipt says `recorded: False` with `record_code`, state `unknown`, the cycle stays owned (`busy`) and nothing is cleared or retried. Post-provider handling is untouched. | `test_r2_actual_manifest_file_write_failure_...`: a REAL on-disk failure (a regular file occupies the manifests directory path → `FileExistsError` from `mkdir`), receipt/state/store/ref/event log asserted. `test_r2_injected_artifact_failure_and_unavailable_store_keep_ownership_honest`: LABELLED injected `PermissionError` from the manifest artifact `put` (the owner's case) → blocked `manifest_artifact:PermissionError`; LABELLED control with a store that fails from that moment → `recorded: False`, cycle still `captured`/owned, `busy` afterwards. |
| R3 exact bytes: Windows text-mode stdin turned 18 LF bytes into 19 CRLF bytes; the receipt SHA named the original | `GitCapture` writes the exact UTF-8 bytes to an owned binary temp file inside the owned temp directory and runs `git hash-object -w --no-filters -- <file>`; the returned blob id must equal the content-addressed SHA-1 of the bytes (`capture_blob_mismatch` otherwise) and, after `commit-tree` but BEFORE `update-ref`, `GitSource.blob(commit, path)` must return mode 100644 and the identical bytes (`capture_readback_mismatch`). `commands.run_process` is unchanged. | `test_r3_capture_stores_exact_utf8_bytes_and_verifies_them_before_the_ref`: real temp repo with `core.autocrlf=true`, body with LF and Korean text, LABELLED monkeypatch of the module's `run_process` that rewrites `input_text` LF→CRLF (simulating the Windows pipe; the new path never sends the body through `input_text`), raw `git cat-file blob` bytes and `GitSource.blob` bytes equal the UTF-8 bytes, blob id equals the computed SHA-1; LABELLED injected wrong blob id → refused before any ref. Existing HEAD/dirty checkout/temp cleanup assertions kept. |

Commands run by the worker (Linux, repository revision 29f5bc6a base):

```
python -m pytest tests/test_research_program.py tests/test_research_program_cli.py -q -p no:cacheprovider
python -m ruff check .
```

Observed: 21 passed, 1 skipped (`test_postgres_reservation_claims_exactly_one_cycle`, needs
`HARNESS_INTEGRATION=1`); ruff: all checks passed. Baseline before the change: 16 passed, 1 skipped.

## Honest gaps / not run here

- The Windows text-mode defect itself cannot reproduce on Linux; the LF→CRLF simulation is a
  labelled monkeypatch of the adapter module's `run_process` reference, not the real pipe. The
  owner must repeat the R3 check natively on Windows (18-byte body → 18-byte blob, `git cat-file`).
- No PostgreSQL run: the R1/R2 receipts were observed on `MemoryStore`; the PG integration test
  remains skipped here. The `FlakyStore` control is a synthetic wrapper, not a real PG outage.
- No live feeds, no real council, no real CallBudget ledger; `FakeSources`/`FakeBudget`/`FakeCouncil`
  are labelled stand-ins. Live owner canary and CI (Linux/Windows) are separate unexecuted steps.
- The full test suite was not run by the worker (SPEC narrows worker verification to the two
  modules plus lint); owner/CI own the full/platform checks.
- `reserve_cycle` gained a required parameter; the only callers are the runner and the two test
  modules (searched `src/` and `tests/`). Any out-of-tree caller must pass the current identity.
