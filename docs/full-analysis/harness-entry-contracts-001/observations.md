# Original entry and check observations

Pinned harness: `a3f8b3be9a0a389329de6e16a6c7db81782041a3`.
Receipt: `attempts/131e2ab76766453ba8070502577c1a1a/receipt.json`.
Raw stdout SHA-256: `39b2847473923fb13e35c9ed7af1cbc0162f25067ea3eb3cac6acc1a06f0305c`.

The immutable, offline Linux container executed nine direct original `engine.checks.run`
calls, which launched eight real fixture commands, plus three original shell launchers
invoked explicitly with **sh**. These are distinct counts, not twelve upstream test suites.
The discussion prompt calls the launchers Bash; the recorded argv establishes sh instead.
Fixtures are our own local files/processes, with their exact content and hashes in stdout.
They do not simulate a provider, database, device or human acceptance service.

| Observation | Result | Bound |
|---|---|---|
| exit_code, failed process | FAIL, exit 1 | Control rejects process failure |
| metric_threshold, same failed process | PASS, evidence exit 1 and metric 42 | Matching output can outweigh failure |
| trigger_effect, same failed process | PASS | Evidence omits exit and retains unexpanded command token |
| db_query, same failed process | FAIL, exit 1 | Control only; no actual database |
| exit_code, successful process | PASS, exit 0 | Positive local command control |
| Windows set prefix on Linux | PASS; inherited driver-home retained | Does not assign HARNESS_HOME to project cwd |
| repeat 1.9 and true | Each PASS with one command | Integer coercion; not strict repetition schema |
| expect REQUIRED across a.txt and b.txt | PASS with token only in a.txt | Aggregate content check, not every-file invariant |
| dispatch.sh without source runtime pin | Exit 0, explicit fail-open stderr | No guard_boot dispatch executed |
| hud_launcher.sh without pin | Exit 0, newline | No HUD runtime executed |
| rlm_launcher.sh without pin | Exit 1, missing-pin stderr | No MCP server executed |

The inherited HARNESS_HOME intentionally differs from cwd. The test uses the exact
declared Windows assignment prefix with our command; it does not execute the original
pipeline or suite. Correct preexisting environment may avoid this particular mismatch.
Suite discovery-zero rejection cannot detect a nonempty but wrong source tree by itself.

The outer process completed with exit 0, container cleanup returned 0, and all 931 pinned
source files remained unchanged. `process_tree_termination_verified` remains false;
successful named-container cleanup does not prove generic process-tree termination.
No gatewriter, ledger writer, source suite, token mint, arming, provider, real database,
trigger service, human approval, Windows or WSL acceptance was executed. This is not the
historically denied gatewriter probe and does not authorize adoption or deployment.

The freshly read original `tests/unit/test_checks_smoke.py` covers file-content rules,
file metrics, echo trigger/DB output, valid repeats, first-failure stopping, zero repeats
and enum/runner correspondence. It was **not executed**. Its echo-based DB/trigger cases
do not establish real DB/trigger acceptance, and its inspected cases do not test matching
output from failed metric/trigger processes or fractional/boolean repeats.
