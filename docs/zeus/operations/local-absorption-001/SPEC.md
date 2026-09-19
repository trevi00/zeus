# Local absorption001: UTF-8 operator documents

## Outcome, authority and completion

User authorized: merge PR153, deploy the validated runtime locally, then one real Claude implementation
and independent Codex review of the live008 BOM recommendation, record results and stop. Claude uses
Opus5 with existing subscription authentication; Codex owns specification and acceptance. No automatic
backlog, provider retry, unrelated cleanup, reboot, credential movement or additional absorption topics.
PR153 merged as a1b40e25a91d530d94a24178c39f37e8266e18e3; its tree matches tested9353fe9.

Complete when pinned runtime is used by local services, one harness-lane job is terminal, code and
evidence are independently reviewed, relevant checks/full suite/CI pass, a concrete candidate PR is
recorded and Fleet is paused/idle. This batch does not authorize merging or deploying its new BOM
candidate automatically. The old uncommitted analysis under C must remain byte-identical.

## Complete path and owners

Hidden scheduled task -> existing launcher -> pinned D runtime -> shared PG Fleet registry/admission ->
harness lane schema/Redis namespace -> exact operation manifest and base -> isolated Claude Opus5 ->
host replay/inspection -> independent Codex -> candidate/evidence -> owner review/CI/PR -> paused.
Keep control repository, authentication and machine usage ledger at existing C home paths. Change only
launcher code roots and worker image to validated153; preserve old launchers for rollback. Fleet idle
is a prerequisite to maintenance. Existing subscription mode must also be applied to the Fleet control
through its public grant API (currently legacy192 ceiling), retaining counts and immutable grant history.
The single explicitly queued job, its900-second task ceiling and two starts bound this batch, not a
per-token bill or a reset machine counter. No second job is admitted. Monitor services remain read-only.

Operator bytes -> adapters/dge_cli.read_document -> duplicate-key-aware JSON -> caller-specific domain
validation -> canonical packet/config digest -> existing registration/execution. Change only the UTF-8
decoder to utf-8-sig and its concise docstring. Keep the256KiB raw byte limit, strict decoding, duplicate
refusal and current error labels. No schema, JSON shape, validation, digest or other reader change.

## Evidence and decisions

Fact: live008 candidate75a5a9d21b6bcbe830d05b8b2ff5e2a91bdb0e4e was independently accepted as a
recommendation, not an implemented change. Local source additional-notes.json sha256
c866959de49c4f36e434b28e7f25549d7fde2f8681337f22669145a6098ac6bc records the Korean/UTF-8 experience.
Current dge_cli.py reads utf-8; JSON refuses a leading BOM. Other adapters already use utf-8-sig.
Primary source: Python3.14.7 documentation, read2026-09-19,
https://docs.python.org/3/library/codecs.html#module-encodings.utf_8_sig : decoding skips an optional
initial UTF-8 BOM. This does not imply accepting UTF-16 or malformed UTF-8.
Inference: accepting this transport prefix improves operator-authored Windows JSON compatibility.
Unknown: no observed production outage was attributed to BOM; do not report this as an incident fix.
Decision: adopt BOM-tolerant UTF-8 at this existing single entry reader, preserving parsed identities.

## Acceptance matrix and one delivery batch

- Actual temp-file tests: BOM present/absent x LF/CRLF x Korean/non-ASCII content. Parsed valid DGE
  packet and research-program config equal their originals; validate through existing validators and
  assert packet/config digests unchanged. Use existing valid fixtures, no model/server mocking.
- Malformed JSON, duplicate key (including BOM-prefixed), malformed UTF-8, UTF-16 and oversized raw
  input still refuse. Missing file remains unavailable. Interior U+FEFF string data is preserved.
- Existing raw byte-size limit counts BOM bytes; no byte-based acceptance expansion beyond the limit.
- Concurrent/restart/network/cancel paths: no new state or external work; not applicable to decoder edit.
  Existing service restart is observed without reboot; no logged-out/reboot recovery claim.
- Windows/Linux covered by current CI; fake success, synthetic provider runs and source reads alone
  cannot establish actual Claude/Codex operation or deployment liveness.
- Worker allowed paths: src/codex_harness/adapters/dge_cli.py and tests/test_dge_cli.py only.
  Run focused tests/test_dge_cli.py,test_research_program.py,test_research_program_cli.py and ruff.
  Owner reviews the complete diff, runs the required full suite and CI once, records real usage,
  models, retries/interventions, service deployment identity, candidate and hashes. End paused/idle.
- Unrelated reader, formatter, model router, observatory design and old reference-analysis findings are
  outside this acceptance. Existing source asset disposition is not a claim of full semantic absorption.
