# Baldrix tests 013 checkpoint

18 primary files (167146 bytes) were freshly read in full. Direct supporting reads cover 25 paths, of which two were read in full. The review remains body_reviewed_call_test_trace_pending; no source test was collected or executed.

Read review.md for per-file oracles, side effects, authority boundaries and pending work. files.json binds primary ranges to the pinned revision, raw SHA-256, Git blob, byte size and exact prior ledger row. supporting.json keeps supporting evidence separate from primary coverage. checkpoint.json and validation.json record only local artifact integrity checks.

Key findings concern writeback token consumption and approval binding, rollback audit failure, alert delivery versus local append, a candidate-builder purity claim contradicted by insight logging, and serial/mocked tests being narrower than lifecycle acceptance. Existing preimage staging and readiness rechecks are preserved as positive defenses. Actual execution, platform qualification, model/human acceptance, license closure, independent Claude review and adoption remain pending.
