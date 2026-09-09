# Codex independent evidence observer review

Root read both primary bodies (7,819 bytes) at Baldrix
`cbb5c3e6c9c4af6f86626474f4d7d62fd8e8a6d2`, scope
`3febc60e9994a8aef5daa7e32cf300bcc257c9379549268479d2fd254794ccd1`, before reading
Claude's response. Fresh support: replay/constants.py full, test_evidence_fab.py full,
agent_outcome_audit.py lines 219–328. Other search hits are discovery only. Source execution
is zero at this initial checkpoint. No source or live harness changes were made.

## Deterministic observations versus proof of fabrication

Explicit enum precedence and separation from semantic LLM grading are useful. The detector
does inspect files and real subprocess exit codes. Those are observations at replay time,
not proof a prior claimed result was fabricated. A removed artifact, different cwd/environment,
missing executable, timeout or changed source can invalidate replay without proving the prior
claim false. Both failed attempts are collapsed into FABRICATION_CONFIRMED; their return codes,
stdout/stderr, exception cause and environment identity are not retained in the verdict.
First success skips the second attempt. Two attempts neither prove stability nor establish
a statistical flake rate, and stateful replay can itself create the fail-then-pass pattern.

File existence does not establish content, source revision, line validity or type: directories
and unrelated existing files can satisfy stat. Relative file_path resolves against the detector's
process cwd, independently of entry.cwd used by replay. FileNotFoundError alone is fabrication;
other OSError is silently non-missing, and some malformed paths can raise outside that catch.
No immutable original receipt or execution-to-evidence binding is checked. Lossy static evidence
cannot be promoted to actual semantic truth or authenticated accusation of fabrication.

## Unknowns and execution authority

Malformed/empty envelopes, wrong evidence types, skipped entries, missing replay commands and
test_result values other than exact 'passed' all become CLEAN. This is intentionally delegated
to structural validation, but CLEAN itself does not say which checks ran. An outer invalid or
empty evidence value prevents fallback to a valid nested envelope unless it is None. An
existing artifact plus no replay also becomes CLEAN without validating any claimed test.

The stated no-writes/no-network boundary is not enforced by shell=False. Replay accepts
envelope-selected argv (coercing arbitrary elements to strings), cwd and timeout; a subprocess
can write, invoke another shell/interpreter, use inherited credentials or network. There is no
allowlist, source/attempt capability, environment pin, filesystem/network isolation or global
budget in this module. Actual live exploitability depends on the upstream envelope trust and
host controls, which are not closed by this read. Only isolated controlled executions are
appropriate for later observations.

Timeout coercion has no positive/finite/upper bound and accepts bool. Default timeout is 30s
per call, plus imported 5s backoff; total envelope cost grows with unbounded entry count and
output capture is unbounded. _replay_once maps timeout to124 and OS failures to127, then loses
their distinction in the enum. Text decoding can raise UnicodeDecodeError outside its catch.
Timeout of a direct child is not proven cleanup of an entire spawned process tree. Local
exceptions and budget exhaustion need explicit unknown/error receipts, not fabricated/clean.

## Caller and original test contract

The sampled hook invokes structural validation and then detect through _safe_call without
an early return on structural failure in the read range. Thus a bad schema is not shown to
prevent replay execution. _safe_call's definition is still unread in this checkpoint, so its
exact logging/error fallback is pending. _resolve_failure_mode returns None on import failure
and gives D2 TOOL_MISUSE precedence over D1 FABRICATION, despite a docstring ordering the latter
first. FLAKE and CLEAN both reach no D1 failure. Later outcome persistence and all callers remain
outside this exact fresh range; previously read hooks are not new primary coverage here.

The original test module lists11 cases. It calls actual SUT functions and real temporary files/
Python subprocesses, including controlled writes and timeout. These are synthetic replay claims,
not an actual historical user test receipt. Assertions test the declared classifications, not
whether missing files or two timeouts logically prove fabrication. Warmup child writes are
already contrary to the module's transitive no-writes claim. Environment variables are popped
rather than restored to their previous values. The test sets RC.REPLAY_BACKOFF_SEC=0 after
importing detect, but the detector imported the float by value, so that mutation does not change
its local backoff binding. No test has been executed in this initial checkpoint.

## Zeus adaptation

Retain typed findings and deterministic checks but separate missing/unknown/replay-failed/
flake-pattern/verified mismatch from semantic fabrication. Bind original and replay receipts to
exact source, environment, argv, attempt and policy; preserve raw outputs and checked denominators.
Run replay only with explicit capabilities in isolated bounded workers, and require actual
results before approval/model qualification. Human SDD acceptance cannot follow from CLEAN or
an enum named CONFIRMED. Full caller/config/test closure, actual OS/process/human/model evidence,
license and independent discussion remain open; no adoption or pilot readiness is claimed.
