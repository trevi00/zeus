# Original GSD execution observations

Root observations precede the actual Claude follow-up. Source is unchanged
Baldrix `cbb5c3e6c9c4af6f86626474f4d7d62fd8e8a6d2`; all 1,648 pinned files
have identical before/after fingerprints in each attempt. This adds zero primary
semantic coverage. Original implementations were independently reviewed in
`../baldrix-gsd-bin-002/`; this report upgrades only the explicitly executed scope.

## Runtime and failed attempts

`attempts/environment-6cc818bf75894a37ad7390742dc164f1` qualified Linux x64,
Node v24.20.0 and Git 2.54.0 as UID 65534. Immutable image is
`sha256:12ba66164e4c3074725e4e6972ca436f946dac480cd2e426530f3c1b8343ef6c`.
The Dockerfile pins its base; `apk add git` is not a reproducible package lock.
The image identity and actual package inventory bind this execution, not future builds.
The apk inventory contains cache-index warnings; its exit status is zero.

`attempts/original-tests-0f264366c5b44076b3e045457bafceae` was interrupted
at the in-container 60-second deadline: one cancelled file wrapper, zero passed,
not 13 failed or passed. Its outer 80-second recorder did not time out, hence
`status:completed`, `returncode:1`, `timed_out:false` are consistent.

`attempts/diagnostic-f25b1def7b59447d9f50d119c318add1` reran the unchanged
test with TAP reporting and process observation, then terminated its own child
at 16 seconds. At each observation (5/10/15/16 seconds), 43 processes contained
38 zombie Git processes adopted by PID 1; summed Threads was exactly 64,
matching the PID limit. The CLI child had five threads and waited in futex.
This supports PID exhaustion from unreaped descendants, rather than slow source
bind reads or a universal CLI hang. No inference from a lock/mtime was used.

`run_observations_with_init.py` differs from the initial wrapper only by adding
Docker `--init`. No source, test, image, resource limit, deadline, environment or
mount permission changed. Its attempt
`original-tests-b017f7cfa7f947a09c5b3f940c449391` passed all 13 original tests,
zero failed/cancelled/skipped, duration 4799.426315 ms. This controlled change
supports the process-reaping diagnosis; the original failed receipts remain.
The 13 definitions cover 12 nonempty worktree scenarios and one no-worktree no-op.
The source execution adapter currently lacks `--init` (source_execution.py);
carry this environment requirement into the post-analysis implementation backlog.

## Additional real counterexamples

`attempts/components-367f9cbb19a94b90ae20392ca0ceb5c3` ran six separate
observations using the original CLI, real Git repositories/commits/worktrees,
and real filesystem writes in disposable container scratch. All six commands
returned zero and valid JSON. That denotes successful observation, not acceptance.

| Case | Actual observation | Meaning |
|---|---|---|
| merge-control | Normal worktree merged and removed | Positive fixture control |
| merge-invalid-base | `not-a-real-commit` accepted; merged true, worktree removed | `expectedBase` is not enforced |
| merge-foreign-branch | `unrelated-owner` branch merged, worktree removed, branch deleted | Caller ownership is not established by branch selection |
| phase-renumber | Removing 5 changes both headings 6 and 7 to 5, while directories become 05-six and 06-seven | Descending textual substitutions cascade; document and directory identities diverge |
| profile-evidence | Inert password-pattern sentinel redacted; count 1 | Positive sanitizer control |
| profile-evidence_quotes | Same inert sentinel rendered verbatim; count 0 | Preferred alternate field bypasses sanitization |

The sentinel is explicitly synthetic, not a credential or user session. LOW
confidence was reported for both profile inputs. These are actual source executions
with controlled input, not mocked services or product E2E/human acceptance.
The merge command's returned commit hash identifies a code commit; a later cleanup
commit can change HEAD, so that difference alone is not a new defect claim.

## Scope and adaptation

The successful original suite does not test invalid expected-base rejection,
task ownership of all selected worktrees, phase text renumbering, or the alternate
profile evidence field. Passing it cannot override the counterexamples. Conversely,
the first timeout is not evidence that the merge implementation failed its assertions.

Zeus needs process reaping under existing isolation limits, task-owned merge
selection and ancestry/current-revision fencing, stable phase identities separate
from display order, and one canonical sanitizer across accepted input fields.
An exact `expectedBase == current HEAD` requirement would reject deliberate
non-fast-forward/conflict cases in original tests 2 and 7; do not adopt it blindly.
These remain adaptation requirements, not implemented fixes or ticket closure.

All attempts recorded zero-exit cleanup for their exact named disposable container.
The generic recorder retains `process_tree_termination_verified:false`; do not
rewrite that as a verified host process-tree kill. No operating Docker deployment,
local Claude harness, credential store, or runtime ticket state was mounted.
Windows, WSL, real devices, production deployment, human acceptance, model routing
qualification and whole-repository analysis remain unproved by this Linux evidence.
