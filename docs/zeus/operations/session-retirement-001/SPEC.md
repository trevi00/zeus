# PostgreSQL-first retirement of disposable Codex sessions

## Owner evidence triage — 2026-09-22

Candidate 56520f999dda89647e1c34bccfcb04a8121a7147 stopped at evidence_gate_refused,
inspection 4099e6665a6c1371962e12e74087bcad15946239fc8911b72c74caaada4da60c.
Direct PG inspection shows the specified focused pytest command passed twice (177.364/178.100s),
and the extra same-command -rf variant passed twice (178.265/179.752s). The additional full-suite
claim then timed out after the remaining 167.247s; regression subset and Ruff were not checked
because aggregate replay budget was exhausted. This is evidence-contract scope drift and budget
exhaustion, not proof that the feature is correct or that its implementation caused the full-suite
failure. Skipped PG tests still do not establish actual PostgreSQL behavior. No independent reviewer
call ran and no production deletion occurred. Preserve all original claims and failed output.

Next feature batch after priority recovery: inspect worker report and full-suite output for material
actual failures; preserve already passed focused evidence; supply only the original declared checks
to the bounded evidence path without rewriting the historic receipt or raising global budgets.
Any implementation issue from the fixed matrix belongs in one consolidated correction. Owner real
PG retention/restoration and exact installed-provider canary remain required before activation.

## Outcome and authority (2026-09-22)

The user authorizes permanent destruction of finished one-shot Zeus sessions ONLY after full
preservation in PostgreSQL. Codex owns design, acceptance and activation; Claude implements and
supplies evidence. This is not authority to delete arbitrary Desktop chats, active work, conductor
sessions, user/frontdesk conversations, resumable or unresolved executions. No bulk home-directory
cleanup. Work storage for this recovery remains C:/workspaces/zeus following the explicit D disk
incident decision. Credentials and machine accounting stay at home.

Completion: an owner command can identify eligible sessions from authoritative Zeus records,
preserve the complete supported export and all required referenced evidence BYTES in normal durable
PG storage, reread/verify them after commit, and delete only that exact session through supported
Codex APIs. Reports distinguish preserved, verified, delete_pending, deleted and blocked. Production
activation and a controlled actual canary belong to Codex after independent review. Until then no
existing session is deleted. Automatic periodic operation follows that activation, not worker tests.

## Existing path and evidence

At runtime-176 c4660cf: adapters/app_server.py starts ordinary thread/start sessions and supports
resume; it does not archive/delete them. adapters/codex.py uses exec --ephemeral, a separate transport.
adapters/execution_output.py persist_result writes FileArtifacts. executor.py checkpoints bind
provider_session_id, task, generation, attempt, invocation, evidence_ref and context_ref in PG.
FileArtifacts stores payload bytes on disk; a PG reference does NOT establish PG payload retention.
Reuse these identities, the existing store transaction abstraction and provenance; do not create
another truth source or turn raw archives into accepted knowledge/ontology.

Official source read 2026-09-22: https://learn.chatgpt.com/docs/app-server
thread/read can read persisted turns without resume; thread/archive retains local history;
thread/delete permanently removes a thread AND spawned descendants. A successful parent deletion
therefore is not scoped proof of safe descendant deletion. Current installed CLI capability and
the completeness of exports/attachments need explicit adapter checks; docs are not execution proof.
Recent Desktop entries have not all been matched to Zeus: never infer ownership from cwd/title/age.

## One design and delivery batch

Add a small session-retirement domain/application owner plus Codex adapter/CLI using existing PG
store. Trace store, tasks/decisions, session checkpoints, invocation settlement and app-server request
semantics first. Keep transport API handling separate from eligibility and preservation policy.
Provide a read-only plan and explicit apply mode (default plan) through a dedicated module entrypoint;
no model call, no desktop UI automation, no raw SQLite edits, no shell deletion. CLI accepts bounded
batch size and explicit session IDs or scans only owned records. Redacted JSON report for every case.

State: discovered -> blocked OR export_pending -> persisted -> verified -> delete_pending -> deleted.
PG receipt owns immutable session/provider/task/generation/attempt/invocation binding, export version,
content inventory, byte lengths/hashes, observed usage (unknown stays unknown), terminal state and
required refs. Preserve accessible input/output/tool events, execution/context artifacts, usage and
failure evidence. Recursively resolve declared evidence dependencies using known schemas; never call
a mere ref complete. Store full payloads in bounded chunks in regular logged PG rows plus manifest;
do not truncate to fit model context. Keep secrets out using existing redaction contracts and record
redaction metadata. If a required source is inaccessible, unsupported, incomplete, exceeds supported
limits, has unresolved dependencies, or lacks export completeness proof, keep the session and report
the exact blocked category. Do not claim access to provider-internal hidden data.

Read back committed payloads in a NEW transaction and verify inventory, hash, lengths and bindings
before deletion authorization. Immutable manifest completeness includes attachment payloads, not only
file paths. Existing filesystem artifacts remain untouched in this delivery. PG data is an execution
archive, not semantic acceptance. Rejected/failed terminal work can be archived but unresolved
termination/reconciliation and work still eligible for resume cannot be deleted.

Eligibility is positive: recorded Zeus ownership, explicit one-shot semantics, terminal task/decision,
settled invocation and no active/recovery/resume reference. Missing legacy ownership or semantics
means blocked, not disposable. Derive explicit one-shot designation from authoritative assignment
policy, never broad `read_only`, role-name or cwd heuristics; add narrow recording at the existing
checkpoint boundary if needed. Coordinate retirement with the same ownership boundary used to resume
sessions: no check-then-delete race with a new resume. Do not hold PG transactions across unbounded
provider calls. Durable claims must be recoverable and release only with observed disposition.

Because deletion cascades, initially refuse any thread with descendants or when their absence cannot
be established by the installed provider capability. Do not opportunistically widen deletion to a
tree. No ephemeral switch in this batch: that would remove export before PG confirmation on crashes.
Unsupported delete/read/list capability blocks safely; archive is not counted as permanent deletion.

DB and provider deletion are not atomic. Commit verified delete intent before provider request. On
timeout/response loss retain intent and reconcile exact provider thread existence; unknown is pending,
not deleted. A restart must use the existing verified archive/identity and must not create duplicate
archives or re-export from an absent source. A missing thread is success only with this exact previous
verified delete intent; otherwise it is missing-source and blocked. Per-session concurrency uses the
existing store CAS/transaction contract. Bound RPC, batch and export work; failure diagnostics identify
stage/type/digest without credentials or raw sensitive exception text.

## Fixed acceptance matrix

| Boundary | Required outcome / evidence |
|---|---|
| Finished owned one-shot | complete committed bytes reread, exact delete, durable disposition |
| Active/user/conductor/resumable/foreign/ambiguous | refusal, zero destructive RPCs |
| Required artifact missing/corrupt/attachment unavailable | blocked, no truncation or deletion |
| PG write/commit/reread failure | keep source, failure retained where possible |
| Unknown usage | null/unknown preserved, no fabricated zero |
| Descendant exists or capability cannot prove absence | no cascading deletion |
| Concurrent scan/apply/resume | one owner, resume/retirement cannot overlap destructively |
| Crash before commit / after commit / after remote delete | recoverable ordered state, no data loss |
| Delete timeout or unsupported RPC | pending/blocked, not falsely deleted |
| Same replay / conflicting archive | idempotent replay / explicit conflict |
| Windows and Linux | Python/API path portable; capability differences reported |
| Cleanup | only provider-owned exact disposable session; files/auth/user chats untouched |

Tests use real temporary files and existing MemoryStore plus repository's isolated PG test fixture
where available. Provider fake/fault injections must be labelled as such, including delete timeout;
they do not prove actual installed API or Desktop disappearance. Include byte restoration solely from
DB after original temporary artifact removal, PG rollback and fresh-transaction read verification.
Worker must not use real user thread IDs or production DB writes/deletion. Owner actual controlled
canary is required before scheduling automatic apply; preserve failure attempts.

Allowed scope: new domain/session_retirement.py, application/session_retirement.py,
adapters/session_retirement.py; narrow changes to adapters/app_server.py, adapters/executor.py and
application session resume ownership code if required by the above trace; focused
tests/test_session_retirement.py and tests/test_session_retirement_postgres.py; docs/contracts.md and
this task folder. Do not rework Fleet relocation, staging promotion, ontology or app frontend.
If resume exclusion cannot be safely established in this batch, implement preservation and report
deletion blocked with the precise missing ownership boundary rather than weakening the criterion.

Worker commands: python -m pytest tests/test_session_retirement.py tests/test_session_retirement_postgres.py -q -p no:cacheprovider
and python -m ruff check . --no-cache. Record all skips and failures accurately. Full host acceptance
and activation remain owner work. One consolidated independent review against this matrix; unrelated
minor observations are follow-ups. This document is a design, not an implemented cleanup claim.
