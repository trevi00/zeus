## Design review — FA-017/GH18 remaining acceptance

### What the code actually does today

`AppServer.run` (`src/codex_harness/adapters/app_server.py:246-248`) does `json.loads(answer_text)` then `validate(...)` inline on the `turn/completed` branch. Both raise out of `run`. In `Executor._run` (`src/codex_harness/adapters/executor.py:271-273`) `result` is still `None`, so the `except Exception` re-raises. Consequence: no `execution:{key}` artifact (line 286), no `ExecutionFailure`, no `evidence_ref`, no checkpoint. `Workflow.fail_execution` (`application/workflow.py:282-289`) then records `failure=None` with a stringified `JSONDecodeError`/`ValidationError`. Your root suspicion is confirmed, including the partial-text nuance: `observe()` (lines 238-259) has already persisted `runtime-event:` artifacts and `last_completed` into `execution_progress`, so *some* text survives but is never linked to a normalized failure. Retry identity itself is fine — `retryable` stays `True` since only `codex-provider-usage-limit-exceeded` is `confirmed`, and generation/attempt fencing in `fail` is untouched.

Empty output collapses into the same path: `json.loads("")` raises, so "empty" is currently indistinguishable from "malformed".

### Concrete gaps your proposal doesn't yet cover

1. **`model_answer_text` is only on `blocked_result`** (line 187). The success/interrupted return (251) and the usage-limit return (239) omit it; the latter also omits `rotate`/`requested_model` shape parity. If the validator emits a failure dict, it must carry `turn_id` — line 291 reads `result["turn_id"]`, which `blocked_result` does *not* provide. Any new dict reusing that path must include it or `_run` raises `KeyError` while handling a failure.
2. **Two failure shapes already coexist** (`failure` vs `inspection_blocked`) and lines 283-293 branch on both. Adding a third variant is where the bug will be; prefer emitting the existing `failure` shape verbatim so `ExecutionFailure(cause, evidence)` and `evidence_ref` reuse is literal, not near-identical.
3. **`fail_execution` cause taxonomy is implicit.** `confirmed` is a hardcoded single-cause check. Adding `malformed_json`/`schema_mismatch`/`empty_output` silently makes them retryable — correct, but assert it in a test, since a future non-retryable cause will otherwise be misclassified by omission.
4. **Thread continuity is recorded but never reused.** `thread_id` appears only at lines 291/301; `_run` never passes it back into `run`. Don't claim retries "resume the thread" — they don't.

### Empty typed payloads

Yes, separate. JSON Schema cannot express "the stage produced a decision." A schema with no `required`, or `{}`, validates and line 314 spreads it, so missing `accepted`/`scope` surfaces as a `KeyError` far downstream (e.g. lines 579, 634). Minimal form: a per-stage required-key check at the `_run` return boundary emitting cause `empty_result`, not a second schema layer.

### Test shape

Agreed on native child processes. The cheapest honest harness: a stub codex binary launched via `resolve_codex` speaking real JSON-RPC on stdio with scripted `agentMessage` text (`""`, `"{"`, valid-but-wrong), real PG store and real artifact root — asserting `execution:{key}` exists, contains raw text plus events, and that `status == "retry"` with `failure.execution_ref` set. That exercises the actual process boundary without fabricating a model run.