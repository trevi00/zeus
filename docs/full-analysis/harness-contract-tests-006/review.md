# Harness contract tests 006: static review

All three primary bodies (27,681 bytes) were read from pinned revision a3f8b3be9a0a389329de6e16a6c7db81782041a3. Ten supporting paths were read only in the recorded ranges. Source execution, import, probes, network and installation: zero. Historical incidents and test expectations are not current execution evidence. Primary status remains body_reviewed_call_test_trace_pending. No prior semantic report was reused.

Correction: the first unpublished review suffered question-mark substitution while passing Korean literals through PowerShell stdin. This English rewrite restores the semantic findings from the original body review. UTF-8 decoding alone did not detect that content loss; validation now checks for substitution and visibly samples the report. Source bodies and their hashes were unaffected.

## f01

tests/contract/test_verdict_reprobe_contract.py, lines 1-161. The test specifies a seven-day retry for blocked results and permanent retention of reachable=True. Synthetic cases cover old/new False, old None, missing/malformed timestamps, both sides of a boundary, and True with old or absent timestamps. Census replaces the youtube probe with a callback and uses a temporary three-item cache: only the stale failure should be probed, then no item on the next census. This does not call a real provider. Real time, rather than an injected clock, determines these fixtures. Restoration of the original probe is conditional on its truthiness. Source-text assertions about retry wording and the invented TTL document provenance, not empirical tuning.

s01 is_stale exempts exact True forever, whereas is_distillable can reject a reachable item with no caption or positive chapter count. Such reachable-but-not-distillable entries can be held by s02 without becoming eligible for this retry policy. This is a static condition mismatch, not a reproduced incident. Cache identity is id alone, independent of source. Future timestamps can defer retries. Limits, malformed top-level JSON, probe exceptions and concurrent cache updates need further closure.

For Zeus, distinguish discoverability, evidence freshness and queue eligibility. Bind source, revision, parser and attempt identity to PG receipts. A cached discovery is input to research in the user-defined eight-stage SDD, not human acceptance or a permanent fact. The seven-day value remains an unvalidated policy choice.

## f02

tests/contract/test_youtube_note_contract.py, lines 1-170. The test builds the actual YAML via the loader, but was not executed here. It checks note/uptake order, NOTE_OUT input, machine gate modes, nonempty expect strings, output paths, artifact enums, canary requirements and a contrasting role pipeline. _expects extracts configured text: agreement between a declaration and its loaded representation is not evidence of output quality. Source attribution, linkage verdict, legitimate no-link output and non-copying instructions are asserted as wording, not observed compliance.

s03 defines two stages, not the user's eight SDD stages. Its iteration and wall-clock limits are declarations. Fixed output paths need separate request attribution and overwrite tests. s08 validates supported configuration; s09 concatenates file content and searches literal or regex expectations. This configuration does not bind a video ID to the request, prove source reading, qualify an independent reviewer, or authenticate human approval. s10 is a configuration contrast, not a completed role run. Completion-line and archiving closure remain pending.

For Zeus, preserve the research-note-to-uptake proposal, but bind artifact digests and request IDs to separate stage receipts and actual human review. String presence is not approval or adoption.

## f03

tests/contract/test_youtube_queue_contract.py, lines 1-230. A synthetic three-video feed checks kind/video_id, separation from research requests, omission of a malicious title, repeat suppression, additions, missing IDs, missing feeds and unreadable queues. Mapping/path checks, payload parser cases and pipeline construction do not exercise actual arm or host dispatch. Source-string inspection of ledger names does not prove delivery. The isolation guard permits arbitrary state when the research path is absent and is not a general contamination proof.

s02 filters against a snapshot of already queued IDs; duplicates within one feed and concurrent read-append races remain uncovered. Absent or unreadable reachability caches can permit queueing. Malformed top-level JSON differs from JSON syntax failure and can reach unchecked .get calls. s04 queue append and watermark persistence are not established as one transaction. Omitting titles usefully minimizes input, but does not establish trust in all IDs or payloads.

s05 can record consumed requests as outcome=spawned. s07 lines 953-976 consumes a blocked request and returns zero without spawning; gate exceptions are fail-open. Queue consumption, process start, task completion and human acceptance therefore require distinct receipts. This connection was read statically; no gate or historically denied probe was executed. Role/path restrictions and separate tagged ledgers are defenses worth preserving. Concurrent host behavior, delivery retries, leases and Windows/Linux/WSL execution remain unverified.

For Zeus, use PG uniqueness over source/id/generation and explicit held, consumed, rejected, started, completed and accepted states, tied to Git-defined pipeline versions. Learning proposals require the user's SDD and human acceptance contract; current Zeus equivalence and adoption are not established.

## supporting

supporting.json records exact ranges, SHA256, raw Git blob and bytes for s01-s10. Only s03 was read in full; the other nine are partial. They add no primary coverage. Loader, queue, supervisor and driver transition closure, provider behavior, archive and completion-line contracts, concurrency and database implementation remain pending. Supporting ranges were read freshly; no prior semantic report was substituted for source reading.

## limits

No test collection or execution occurred. Test output strings are not current results; the runner's collected/skip/pass denominator was not validated in this partition. Actual Claude joint review, license/dependency closure, model qualification, Windows/Linux/WSL, real human experience acceptance, complete transition closure and adoption remain pending. validation.json concerns only this report's metadata integrity.
