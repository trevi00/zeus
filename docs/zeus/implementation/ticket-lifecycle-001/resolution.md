# Root implementation and review decision

Root and actual Claude independently reviewed the ticket adapter before the patch.
The initial three regressions reproduced false success for externally CLOSED issues,
external title edits, and acknowledged edits that did not reach remote state. Root
implemented full readback, conflict observations and recovery; Claude reviewed the
patch, and root corrected the concrete defects found together.

Accepted corrections include bounded dispatch context without deleting stored
observations, deduplicated identical remote observations, revision checks on plain
sync, known legacy title provenance, and independent preservation of late creation
receipts. A late creation receipt is a remote fact, never ownership of a new claim.

Claude's final review identified a reconciliation leak: a failed explicit overwrite
could promote foreign text to the hashes trusted by later plain sync. Root added
body/title regressions; both failed before correction (`fd12e4`). Root then fixed
the leak and found the same trust promotion in CLOSED conflict finalization.
Conflict readback now stores measured hashes separately from trusted projection
hashes. Additional tests cover a CLOSED reconciliation followed by external reopen,
and external text changed between the two conflict reads. These additional tests
were executed after the correction; Claude's blanket statement that all four tests
were run red beforehand overstates the recorded execution and is not adopted.

Claude independently verified these final corrections and approved the incremental
patch (`claude-correction.md`). Root agrees. Two readability nits remain nonblocking:
the link's `title` is measured external text whereas `title_hash` is trusted projection
text; a stored reconciliation reference is historical context, not a reusable grant.
No consumer outside this adapter calculates trust from either field. Unknown initial
projection hashes may be null; only this adapter consumes them and comparisons are safe.

Root rejected trusting arbitrary first-observed legacy titles, assuming undocumented
GitHub text normalization, or treating a local lease as a physical fence on an already
sent GitHub request. Search discovery now reads full issue data; exact text mismatches
stay conflicts. The independent remote receipt permits recovery but cannot provide a
distributed transaction with PostgreSQL.

Validation boundaries: 56 targeted memory/actual-PostgreSQL tests passed; their GitHub
transport is a deterministic unit seam. Actual PostgreSQL plus actual GitHub issue30
readback passed separately under the recorded source hashes, with remote body, title,
state and comments unchanged. No improvement issue was closed for testing. Full-suite
and CI results are recorded separately when completed, not inferred from targeted tests.

FA-029 remains open. Evidence-bound closure, recurrence/reopen, authenticated required
human approval, resumable remote state-changing projection and actual separate-issue
acceptance still require implementation. No new analysis issue or review advisory was
registered for this correction. The user's implementation priority is preserved.
