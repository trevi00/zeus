# Two-strike research-first adoption

Owner: Codex. Implementer: Zeus Claude worker. Date: 2026-09-20.

## Outcome and boundary
The user requests Baldrix's rule: after two same/similar failures, stop repeating the approach,
search/investigate, then fix and independently verify. This delivery adds the rule and an actual
per-session tool-failure detector to the EXISTING worker-v1 hook/profile. It does not confer
network permissions, launch recursive researchers, auto-merge, or promote unverified knowledge.
Similarity is a research candidate, NOT a confirmed root cause. Existing PG incident recurrence
(INV-RECURRENCE-001, independent confirmed cause/scope threshold 2) remains authoritative and unchanged.

The broader authorized portfolio remains: local asset absorption, Sterk migration, research
improvement, Projects visibility and cross-job reject/error learning. This particular source
adoption is not full absorption or completion of that portfolio. Cross-job PG aggregation and
automatic research dispatch are not claimed by this session hook. They must consume preserved
evidence through the existing orchestration, not treat a local hook as a new authority.

## Sources / decisions
Local Baldrix commit 7f2d97dab465aa1670267137354d0d44c51fb688, inspected source (upstream tests NOT run):
- scripts/lib/repeat_error_tracker.py blob bb4c86a0db994cefd978c61efac9017f037dac98:
  threshold 2, path/number-normalized symptom fingerprint; its shared temp JSON lacks process
  concurrency protection. Adopt policy, not that storage or its root-cause wording.
- scripts/lib/strike_dispatcher.py blob 90185248b5d150745654cb695b72894552516b1b:
  shared threshold, bounded research dispatch. Do not copy independent check/write quota race.
- scripts/cli/strike_research_consume.py blob a9870918406c9b79e371c9ea29976b107d3860ec:
  research artifact precedes staged skill change; escalation is not application/approval.
- https://code.claude.com/docs/en/hooks (opened 2026-09-20), PostToolUseFailure input/decision
  control: error, tool_use_id, is_interrupt; additionalContext provides next-turn guidance.
  This event does not observe pre-execution validation rejection. Document this coverage limit.
The current Zeus hook records metadata only (SessionStart, PostToolUse Bash); profile is pinned
by document+hook hashes and shipped into isolated workers. Hook receipt != model adherence.

## Complete path / implementation batch
1. Extend the existing standalone stdlib hook, not a second installed global hook. Register
   PostToolUseFailure for supported tools (Bash, Read, Edit, Write, Glob, Grep); retain existing
   SessionStart/PostToolUse receipt behavior. Explicit unsuccessful Bash response with a real
   nonzero exit_code may count too, but success text mentioning 'failed' must not count.
2. On a supported explicit failure, derive a bounded normalized symptom fingerprint in memory:
   tool + error family/text with paths and changing numeric IDs normalized. Never persist
   raw commands, tool inputs, outputs, error samples, or arbitrary messages. Store hashes,
   counters, status only. Missing tool_use_id/session/error, oversized/malformed input or
   interruption means unknown/not counted, not invented evidence.
3. Use stdlib sqlite3 in the already-owned per-session hook evidence directory for atomic
   counting and deduplication. Scope by full session hash + profile digest. Dedup key is
   tool_use_id hash (one failed tool invocation counts once across duplicate event delivery).
   BEGIN IMMEDIATE and bounded busy timeout; failed/corrupt/busy state reports unavailable and
   never resets counts. Distinct tool invocations count even if command is unchanged. This is
   deliberately different from confirmed cross-task incident independence.
4. At count >= 2, emit one research-required context per fingerprint per session using
   hookSpecificOutput with the actual event name. Persist the emitted marker atomically with
   count. Replays do not emit another research request. A crash after marker commit can lose
   context delivery: receipts/status disclose required research; do not promise exactly-once
   model delivery. No reentrant model call or unlimited warning/research loop.
5. Guidance: stop blind retry; inspect existing SSOT, responsible producer/consumer and failure
   evidence; search local references and primary documentation where authorized; record source
   revision/date + supported claim, separate observations/hypotheses; one discriminating check;
   fix within scope, test affected criteria, preserve failure evidence. If search/authority is
   unavailable, report research_required with evidence and specific lead handoff, not success.
   No unrelated exploration. One bounded investigation then coherent correction; unresolved
   material failure goes to lead instead of recursively launching another investigation.
6. Profile text applies this same rule also to repeated reviewer rejection the model can read;
   hooks do NOT mechanically observe those rejections. Never claim otherwise. Fit 6000 chars by
   concise rewriting without dropping existing authority, verification and reporting contracts.
7. Extend existing hook_receipts projection additively with two_strike facts: observation,
   distinct failures, research_required fingerprints/count, unavailable state; no raw data.
   Retain existing keys and truthful no-authority language. Do not mutate from this reader.
   Update settings/receipt event list, packaged manifest hashes and source provenance.
8. Add focused regression tests invoking the real standalone hook subprocess; protocol child
   is synthetic delivery evidence only. Record exact commands and concise WORKER.md evidence.

## Acceptance matrix
| Path | Deciding check |
|---|---|
| first / second / third failure | 1 no research context; 2 one required context; 3 retains required, no new dispatch |
| similar / different | varying path/line maps same symptom; materially different message/tool separate |
| success / interruption / missing fields | no false strike; unknown disclosed |
| duplicate / restart | same tool ID never double counts; new hook process uses existing state |
| concurrent failures | two actual processes commit exactly two distinct failures, one trigger |
| unavailable/corrupt/busy | finite return, no silent reset or success claim |
| privacy | canary credential-bearing input absent from stdout, receipts and SQLite bytes |
| integration | profile hashes verify, added hook shipped by existing settings; existing tests pass |
| Windows/POSIX | portable sqlite and Python subprocess, no platform shell state commands |
| cleanup | only owned session evidence directory, no global state or user tree deletion |
| external research/model adherence | not established by fixtures; manual/actual execution evidence separate |

Owner checks focused worker/profile/isolation tests, root ruff, CI full suite; no need to rerun
unrelated Docker readiness research. Root independently reviews candidate and preserves evidence.
Completion is tested/pinned implementation and truthful delivery report; operational runtime switch
must identify its pin separately. Source inventory counts are not changed to imply full absorption.

## Owner continuation after the first actual execution
The first Claude execution stopped at its 900-second deadline without a terminal answer.
Its seven changed files were preserved at 35de992; no acceptance or automatic retry was inferred.
The assumption that implementation plus reporting would fit that call was false. Owner inspection
found a complete testable draft: 60 focused tests passed, 1 platform skip, root ruff passed.
Continue by verifying this preserved draft, not restarting implementation or expanding scope.
The owner supplies source provenance and packaging documentation; no second implementation call
is necessary unless the remaining checks reveal a material failure.

Projection terminology: `counted_failures` currently means counted receipt observations (replays
can produce another receipt), not unique invocations. Individual `distinct_failures` counters and
research triggers are deduplicated in SQLite. Do not use the receipt-observation count as a
cross-job recurrence metric. A future Projects aggregation must retain this distinction.
