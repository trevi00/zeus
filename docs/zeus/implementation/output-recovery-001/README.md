# Output failure recovery (FA-017 / GitHub #18)

Root and actual read-only Claude CLI review found the same gap: inline JSON/schema
exceptions leave `Executor._run` without a result, bypassing its execution artifact
and structured failure reference. Some completed-item text can survive in progress
artifacts, but it is not linked to the normalized failure. Existing workflow updates
already preserve task identity and counters; this change reuses that path.

The output boundary now distinguishes empty text, invalid text types, strict JSON
failures and schema mismatches. It rejects duplicate properties, non-finite JSON
numbers and unpaired decoded surrogates. Raw text, exact schema, schema hash, and validation paths
are retained with thread/turn identity and observed events in the execution artifact.
Only the runner creates these reason codes; model-authored error words grant no
authority. The existing `ExecutionFailure` path retains the evidence reference in
the attempt history and makes these output failures retryable under the persisted
retry budget. Provider usage-limit failures retain their existing terminal behavior.

Schema-valid empty field values retain their existing meaning. A business-stage
acceptance requirement belongs in its explicit schema or downstream contract; this
change does not infer acceptance or nonempty business content from transport success.
Retries remain new model turns; this is not a claim of resuming the same thread.

The [official App Server documentation](https://learn.chatgpt.com/docs/app-server)
describes `outputSchema` as scoped to a turn. Zeus still validates received output
before treating it as a result. Provider turn completion and human acceptance are
separate facts.

Validation separates transport/Executor unit reconstructions from actual child
processes. The latter read explicit malformed/empty/missing-field input files,
execute the production validator and artifact writer, and call the real workflow
against isolated PostgreSQL schemas. They use real paths with spaces and Korean
characters. No fake Codex executable or model provider is presented as E2E evidence;
thread/turn fields are null and the input origin is labeled explicitly.

For each failure category, two separate failure processes and a new claim process
verify one failure transition, one notice, attempt advancement, and preservation of
task input, project identity, retrospective reference and 3/5 counters. Additional
cases install a PostgreSQL trigger in the isolated schema to reject the failure
record write after the task update. The child exits unsuccessfully with no success
output, the transaction remains unchanged, and replay succeeds after removing only
that test trigger. Artifact writes may precede the failed database transaction;
such an artifact alone is not a committed workflow transition.

This milestone addresses output-failure evidence and process-level retry continuity.
It does not finish the full repository absorption, real model/device acceptance,
cross-host clock matrix, signed human approval, or production deployment.

Claude's implementation review found that preserving raw lone-surrogate text
could make UTF-8 artifact writes fail again. Root fixed both the progress observer
and final result writer. The next review identified encoding-size amplification and
the interrupted-turn handoff path. The final encoder preserves ordinary canonical
UTF-8 bytes and escapes only invalid code units, without lossy replacement. A
40,000-character Korean payload retains its prior content address and fits the
existing 131,072-byte recovery read limit. Successful/interrupted results keep
their historical shape rather than duplicating full answer text. Raw answer text
remains optional for historical consumers and present on the new failure records.

Interrupted handoff artifacts and their context-item hashes now use those same
serialized bytes. A separate Executor unit reconstruction sends a lone surrogate
through the actual progress observer, checkpoints, starts the next iteration, reads
the recovery artifact, and finishes; it is not represented as a real model run.
The output failure also retains an observed context-rotation signal. The exact
review/discussion chain is in `claude-design.md`, `claude-implementation.md`,
`claude-resolution.md` and `claude-final.md`.

Windows validation: Ruff passed; full suite 887 passed / 273 skipped; real
PostgreSQL target 125 passed; isolated Python 3.12 target 81 passed / 9 skipped.
The final target receipt maps eight native evidence files to their byte hashes,
covering 28 child process executions, including four deliberate write rejections.
Earlier target receipts are retained as superseded observations. The source
manifest records local Windows file bytes; checkout line endings may differ on
Linux. Skipped tests are not represented as completed acceptance.
