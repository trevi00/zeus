# Original reference Bash observation

After the static initial/follow-up reports, root executed only the unmodified Bash function
definitions at verification-patterns.md lines 525-552. The complete reference SHA-256 is
5ee34d57a8e60486ec4bdf278ebc2b5eec66cdb7d4aa02b00299310bdd4b4df0 and the excerpt hash is
e3dd73553103f890f862e566f18f3761e0c1987396c3d75595d06c1ed2b91dc6.

Attempt: attempts/4a7d0546b30a453ba35fff813457c888. Seven Bash processes invoked the original
four functions against three explicitly recorded scratch text files and one missing path.
The image was immutable, network disabled, source read-only, unprivileged, and scratch bounded.
All 1,648 pinned source files remained unchanged. Outer process and named container cleanup
returned zero; generic process-tree termination remains unverified.

| Input/check | Observed result | Exit |
|---|---|---:|
| Missing file, check_exists | MISSING | 0 |
| Comment-only endpoint, check_wiring | WIRED | 0 |
| Missing file, check_wiring | NOT_WIRED plus grep missing-file stderr | 0 |
| No stub matches, check_stubs | No stdout; two zero lines cause integer-expression error | 2 |
| Actual TODO token, check_stubs | STUB_PATTERNS: 1 | 0 |
| No expected pattern, check_substantive | THIN, malformed count and integer-expression stderr | 0 |
| Two comment lines with expected token, check_substantive | SUBSTANTIVE | 0 |

The functions emit labels; an exit of zero is not a claimed real PASS. The measured defects
are lost producer status, inconsistent error treatment and token-only labels on comments.
No full verifier, deployment, original suite, model judgment, genuine user data, credentials,
database, HTTP/payment service, Windows/WSL or human acceptance was executed. The endpoint
string is scratch text only, not a service or a mock acceptance result. No frontend behavior
or general false-positive rate was measured. Raw argv/stdout/stderr and fixture hashes remain
in the attempt's stdout; the wrapper and recorder receipts bind the observation program.
