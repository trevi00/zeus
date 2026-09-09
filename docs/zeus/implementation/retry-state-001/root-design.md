# FA-017 retry-state implementation: root adjudication

Existing ticket ZEUS-3875a025c20d / GitHub #18 revision 1 is the scope reference.
The prior Stop implementation lost fields through reconstruction. Both reviewers
confirmed Zeus already updates the stored row and preserves context; copying a new
state constructor would not fix the actual Zeus defects.

The baseline ran four distinct processes against a real isolated PostgreSQL schema.
A committed failure replay returned stale; a new process could increase the limit
from one to two and claim attempt two. These observations are in baseline.json.

Implemented a persisted retry budget for both tasks and decision work. Implicit
claims reuse it; explicit conflicting parameters cannot change it. Root accepted
Claude's warning about queue starvation: a conflict records a deduplicated event
and skips that task, allowing other tasks to be selected. Bounds are positive
integers, excluding booleans, fractions and non-finite values. Lease overflow and
naive caller times fail as contract errors before mutations. New task deadlines
must be timezone-aware ISO timestamps.

Legacy attempted rows lack evidence of their original configured limit. They are
blocked with UnverifiedLegacyRetryBudget and an event rather than adopting a caller's
new limit. An explicit recorded recovery/migration procedure remains necessary before
pilot adoption; that procedure is not implemented by this kernel. Terminal rows are
not automatically reopened. Queued tasks bind only after dependencies are satisfied.
Malformed stored deadlines/budgets are blocked per task instead of stopping the queue.

Failure receipts and transitions share the same PostgreSQL transaction, including
the caller-supplied transaction used by Executor._fail_task. The row stores the
receipt reference. Identical requests can replay without writes only while that
exact failure generation, attempt, status, error and evidence remain current.
Later claim/cancel/expiry cannot be disguised by replaying an old receipt. The
original owner remains in the receipt request after the active lease is cleared.
The executor checks for its existing diagnosis row before writing the diagnosis
artifact, so a committed failure replay does not rewrite that artifact either.

Current structured failure evidence is cleared when a new attempt has none; prior
attempt evidence remains in attempt_outcomes. This prevents the latest failure from
being attributed to a previous attempt's evidence while retaining retrospective data.

This is a coherent retry-state kernel, not completion of FA-017 or the full goal.
Clock-discontinuity disposition, authorized exhausted/deadline recovery, terminal
notification reconciliation, complete malformed-output matrix and the complete
Windows/Linux/WSL process/PG acceptance matrix remain required. Tests of a parser
child process are not actual model execution or human scenario acceptance.
