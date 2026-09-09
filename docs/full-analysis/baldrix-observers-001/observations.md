# Original evidence observer observations

After the independent root review, one original unit wrapper and one controlled component
program completed in the recorded immutable Docker image with return code zero. Source/root
mounts were read-only, network disabled, uid 65534 and resource limits recorded. All 1,648
pinned source files remained unchanged. No host harness or policy was edited.

The original wrapper passed11 tests using real temporary files and actual controlled Python
children with synthetic claims. Its mutation of RC.REPLAY_BACKOFF_SEC does not change the
float already imported by evidence_fab. The separate program observed imported backoff 5.0.
It did not patch methods, clocks, subprocesses or providers.

The component stdout records:

- Empty evidence, a directory path, passed without a replay, permission-denied stat, and
  outer-empty evidence masking nested missing evidence all returned CLEAN.
- An existing file relative to entry.cwd was called FABRICATION_CONFIRMED because file stat
  used the detector cwd. A nonexistent executable also yielded FABRICATION_CONFIRMED.
- A controlled replay created a file under isolated scratch and returned CLEAN. This proves
  this invocation's write effect; it is not a host-write or network test.
- Invalid UTF-8 child stdout raised UnicodeDecodeError; a NUL file path raised ValueError.

Root subsequently read agent_outcome_audit.py 40–136 in addition to 219–328: _safe_call
attempts telemetry then returns None on exception, and malformed/free-text responses or
unavailable/non-machine-readable specs can produce empty/synthetic envelopes or omitted
schema validation. Those are bounded caller findings; the whole structural validator and
all producer/consumer paths are not closed by this read.

These observations concern deterministic replay/classification contracts. Synthetic original
claims do not establish that any historical user claim was fabricated. No actual model/human
acceptance, process-tree cleanup, native Windows/WSL verification or adoption is claimed.
Actual Claude comparison and remaining caller/config/test/license closure are pending.
