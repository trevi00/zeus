# Finalization acceptance evidence

Codex owner review, 2026-09-18. Runtime change at `adb8ce8` was implemented by Claude through Zeus;
Codex authored the specification, counterexamples and the CLI observer-sharing verification update.
The three operation outcomes remain two rejected and one failed (provider budget exhaustion).
The final failed call's exact preserved code was imported only after owner review; it is not an
accepted model execution. Owner code acceptance is separate from those immutable runtime outcomes.

| Check | Actual result |
|---|---|
| Prior owner counterexamples at final code | 4 passed |
| Real local PostgreSQL/Redis finalization matrix | 32 passed; includes six service cases, both claim/submit transaction orderings, rollback and injected ACK gap |
| Final focused regressions including CLI wiring | 152 passed, 23 skipped |
| Final lint | passed |
| Full Windows local suite at 659399c, before final identity guard | 2085 passed, 454 skipped |
| Final-head full/platform CI and rollout | required before closure; linked run and deployment results on issue #142 |

Fault-injected application tests and deliberate message conflicts are synthetic inputs. They do not
establish a real provider outage. PG/Redis services are real and test resources were isolated. Original
failed test outputs and rejected verdicts remain under `D:/workspaces/zeus/artifacts/operation-finalize-001`.

Evidence log SHA256:

- Final PG/Redis: `04837ccde35db58663077d1d11d0d9786434ff6261450b509780254aabaae847`
- Final focused tests: `a009469ab7415e3849dd8514ea3791467c9c3b26396e8d44c51c0c2c014f3319`
- Final counterexamples: `4fcd0796266eb8502f485e7d1eeaa0287f33e9f7d3cae1a66a16193cd9830bb1`
- Full local suite: `1026b31648c82459ef7ce81209b7dd5f1abac3e3bab6178b9e43b0994b1eeeb6`
- Preserved Claude patch: `f8add064165cd0270c4f3710c9bcdbbc0f23c62e44956a87f934349fe8d7c371`

Running or unresolved-effect rows remain operator-owned. Original outcomes remain unchanged.
Finalization events emitted after the operation's synchronous collection are explicitly marked and
collected by the existing external collector. Message draining remains bounded; this delivery does
not claim unlimited unattended operation or automatic merge/reconciliation authority.
