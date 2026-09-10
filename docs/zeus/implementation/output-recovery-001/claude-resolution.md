## Resolution review — output-recovery-001 (read-only; no edits run)

Blockers 1–3 from `claude-implementation.md` are addressed as described. `evidence_json` (`execution_output.py:9`) is lossless, and it is applied to both writers — `executor.py:241` (progress events, which do run before `persist_result`) and `:59`. Native parametrization now transports a real lone surrogate via `json.dumps(..., ensure_ascii=True)` through a UTF-8 file, child processes and PG, including the trigger-rejection/replay case (`test_execution_output.py:91,110,149`). Executor wiring now asserts the same raw text in both the progress artifact and the failure body under `cleanup` on/off (`:79,86`).

### Concrete regressions introduced

1. **Size multiplier against unchanged fixed budgets.** `ensure_ascii=True` doubles non-ASCII bodies (CJK 3→6 bytes) and the success return now stores the full answer twice (`answer` + `model_answer_text`, `app_server.py:255`). `execution_recovery.py:115` caps execution evidence at `artifacts.text(ref, 131072)` and catches only `OSError/UnicodeError`, so a body that previously fit can now raise "Artifact exceeds text budget" and block operator recovery. Same multiplier hits every per-event `runtime-event:` artifact.
2. **Bodies written before/after this change no longer content-address identically** (`artifacts._put:26`), so dedupe and any cross-commit body comparison break for non-ASCII payloads. Stored refs still resolve; low severity, worth noting.
3. **The crash is relocated, not closed, for interrupted turns.** Interrupted status never calls `completed_output`, so raw `events` carry the surrogate into `canonical(value)`/`digest(value)` at `executor.py:198–201` on the next iteration; `digest` encodes (`model.py:31`) → `UnicodeEncodeError` outside any handler, now *after* `checkpoint` (`:297`) bumped the generation. No test drives a surrogate through the interrupted path.

### Boundary scope

Correct: `artifact_query._json` already re-escapes surrogates (`:27`), and PG only ever receives ref/`failure` fields, not raw text. Declining a semantic verdict for `{"summary":""}` remains right, and the permissive-schema `required` gap stays open — unchanged, not closed.