# Codex implementation review

Recorded before reading Claude implementation findings.

1. GitHub retry: a lost create/edit acknowledgement followed by a local revision change makes a legitimately published old body look like an external edit. Persist the exact pending projection hash before the remote write; permit recovery only against that hash, the last acknowledged hash or the desired hash. Search indexing delays must continue to block duplicate creation.
2. Release orchestration unit tests need an explicit fake disposable-service context. Otherwise mocked test execution starts actual Docker services. Add lifecycle tests including setup/test failure, stale definitions and actual separate-server write/read/cleanup.
3. Windows monitor launcher still casts corrupt PID files and lacks a launch mutex. Match supervisor behavior and test with mocked process/registry operations, without launching production.
4. Ticket provenance must survive planning, lead/conductor rejection and rebase. Test actual Executor/Workflow transitions rather than only a hand-built release binding.
5. Current full local-source adoption is incomplete. Zeus branding and these infrastructure changes cannot certify full semantic absorption or autonomous production readiness.
