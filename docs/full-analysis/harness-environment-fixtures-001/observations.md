# Original isolated environment and golden-runner observations

Source: harness a3f8b3be9a0a389329de6e16a6c7db81782041a3.
Attempt: attempts/3a474b8b576543168d7eb8a2d508bfb6.
Raw stdout SHA-256: 63e56f08a7bfece302c61cb43dd00604f3dbc365e9c74db4643a593353df5c2f.

The immutable offline Linux container executed nine scenarios using original isolation
helpers and seven original golden.run invocations over our scratch case documents.
Five real fixture commands ran, recorded through their actual append side effects.
No original golden case, original source suite, gatewriter, curator, ledger writer,
fleet service, database, network provider, Windows/WSL or human acceptance was executed.

| Isolation scenario | Observed result |
|---|---|
| Existing relative state override | Returned unchanged despite nonexistent path; HOME/stamp overrides removed |
| No state override | New scratch directory created and assigned |
| real_state with prior value | Prior value restored after an inner replacement |
| real_state without prior value | Newly assigned inner override remained after exit |
| fresh_state | New directory created without changing the environment |
| Same size rewrite plus restored timestamp | Different content produced equal fingerprints |
| Same failing probe at entry/exit | Error recorded both times, stable_after true; early bool rejected |
| Exception in live_axis body | Original exception propagated |
| Changed-size input | stable false and explicit SKIP-AXIS output |

The failing-probe and size/mtime results demonstrate the helper's documented heuristic
limits. Stable equality is not availability or full acceptance. No real user state was
read or overwritten; even real_state operated solely on the container's scratch environment.

| Golden runner input | Observed result |
|---|---|
| Missing cases file | total 0, failures empty; no command |
| Three malformed entries | All filtered out; total 0, failures empty |
| Mapping instead of a list | total 0, failures empty |
| Expected text only on stderr | One command, no failure despite header specifying stdout |
| Explicit expected nonzero exit | Matched negative control, no failure |
| Invalid expect_exit | Command ran and appended evidence before ValueError |
| Duplicate names | Both commands ran; total 2, failures empty |

An expected nonzero exit is valid negative-test behavior. The concern is schema/denominator
validation and source identity, not requiring every negative test to exit zero. The original
golden.gate function and curator's _golden_gate were read, not called: they statically derive
success from an empty failures list and explicitly permit zero cases. That is a direct
consumer finding, not an observed curator write or complete promotion bypass.

The process completed with exit 0; named-container cleanup returned 0; all 931 source
files remained byte-identical. Generic process-tree termination remains unverified as
recorded. Raw fixture documents, program, wrapper, streams and identities are retained.
The first host-side receipt read failed under default cp949 (tool46ab77); rereading the
same completed receipt explicitly as UTF-8 succeeded (730ef3). No source execution was
restarted because of this observation error.
