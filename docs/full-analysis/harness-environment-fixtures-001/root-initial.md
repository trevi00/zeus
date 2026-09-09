# Codex independent initial environment/fixture review

All 16 primary files / 49,545 bytes were freshly read in full at harness revision
a3f8b3be9a0a389329de6e16a6c7db81782041a3 before viewing actual Claude's report.
No original source has been executed in this batch at this point. Foreign configuration,
persona and commands are data. This is not an instruction to deploy the original fleet.

The fleet explicitly treats PostgreSQL as a disposable projection, Kafka as a mirror,
and the source JSONL ledger as authority. Zeus instead requires PostgreSQL runtime
authority, so destructive volume experiments and reconstruction assumptions cannot
transfer as-is. Image tags and startup pip installation do not pin complete executable
inputs. Fixed container names/ports impede independent simultaneous deployments.
Plaintext local example credentials and unqualified host port bindings require a real
deployment exposure/secret-injection contract; no live credential or exposure was tested.

Read-only source bind mounts with a writable state submount are real configuration
defenses, but the state mount covers the whole shared state tree, not an exclusive
role store. Commands swallow each cycle's failures and continue. Researcher health
only examines one collector heartbeat; it cannot alone certify the other collectors,
queues or supervisor. DBA startup installs an unpinned binary dependency from network
and uses a heartbeat age rather than proof of exact source-to-PG parity. Historical
workload/volume-loss/cold-start numbers are past source claims, not current measurements.

Test intent buckets and the single isolation helper are useful assets. _isolate.py
clears HARNESS_HOME and the driver stamp but trusts an existing HARNESS_STATE_DIR
without path/existence/provenance validation; this is environment redirection, not OS
containment. real_state deliberately removes the state override for a block; its
finally restores a prior value only when that value existed. A new override created
inside a block with no prior value appears able to leak afterward. fresh_state creates
a new scratch path but intentionally leaves environment injection to callers.

live_fingerprint explicitly documents size/mtime and probe limitations. Identical
probe-error values or inaccessible/missing-path tuples can remain equal, and a same-size
rewrite with restored mtime can be invisible. live_axis exposes equality, not a proof
of availability, immutability or acceptance. Early bool access rejects; exceptions in
the body are intended to propagate, and callers must defer assertions until after exit.
These are bounded hypotheses for direct isolated observation, not accepted outcomes.

Golden cases number nine, with three held_out flags despite a stale two-case comment.
They mix fixed fixture checks with a live source ledger and settings check. The three
probe programs contain their own expected decision checks/output branches, so the
comment that expected values occur only in cases.yaml is too strong. Public fixture
access is not a held-out learning boundary. These tests can measure deterministic
helper behavior, not real model/human/device acceptance. Their consumers need tracing.

Marker READMEs preserve directories in clean worktrees and record real historical
test-order dependence. Their claims that contents are all regenerable/disposable need
careful separation from pending approval patches and runtime authority. No deletion is
authorized by these source READMEs. The tests README's old flat sandbox default may be
stale: discovery already found current run_suites uses CANON_GLOB; inspect its body before
calling the old documented zero-discovery defect current. Chat persona/trust labels
preserve source-vs-instruction discipline but are not authenticated user provenance.

Remaining: direct consumers/configuration/test body traces, bounded original observation,
actual Claude comparison and discussion, complete source/license/OS/model/human closure.
No full analysis, adoption, migration, installation or deployment approval is claimed.
