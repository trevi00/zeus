# Ouroboros whole-repository coverage map

Structural inventory, not semantic analysis. Every tracked path belongs to exactly one bucket.
All buckets remain open until contracts, callers, state, tests and Zeus mapping are assessed.

| Source bucket | Paths | Bytes | Status |
|---|---:|---:|---|
| `(root metadata/docs)` | 27 | 980105 | open |
| `.agents` | 1 | 311 | open |
| `.claude` | 1 | 1525 | open |
| `.claude-plugin` | 4 | 6080 | open |
| `.codex` | 2 | 1768 | open |
| `.codex-plugin` | 1 | 1706 | open |
| `.github` | 16 | 51217 | open |
| `.ouroboros` | 3 | 11918 | open |
| `crates` | 14 | 204139 | open |
| `docs` | 158 | 12302447 | open |
| `examples` | 10 | 24245 | open |
| `hooks` | 1 | 2630 | open |
| `integrations` | 3 | 13141 | open |
| `scripts` | 22 | 289101 | open |
| `skills` | 22 | 340197 | open |
| `src/ouroboros (root modules)` | 14 | 131624 | open |
| `src/ouroboros/agents` | 23 | 51349 | open |
| `src/ouroboros/auto` | 49 | 1097420 | open |
| `src/ouroboros/backends` | 4 | 70232 | open |
| `src/ouroboros/bigbang` | 17 | 436052 | open |
| `src/ouroboros/cli` | 54 | 1100753 | open |
| `src/ouroboros/codex` | 6 | 75372 | open |
| `src/ouroboros/config` | 7 | 168240 | open |
| `src/ouroboros/config_tui` | 6 | 69036 | open |
| `src/ouroboros/copilot` | 4 | 21465 | open |
| `src/ouroboros/core` | 38 | 502313 | open |
| `src/ouroboros/dashboard` | 2 | 21441 | open |
| `src/ouroboros/dashboard_web` | 8 | 81576 | open |
| `src/ouroboros/evaluation` | 17 | 261882 | open |
| `src/ouroboros/events` | 13 | 96306 | open |
| `src/ouroboros/evolution` | 23 | 483042 | open |
| `src/ouroboros/execution` | 1 | 381 | open |
| `src/ouroboros/gjc` | 2 | 15818 | open |
| `src/ouroboros/gjc_bridge` | 1 | 2576 | open |
| `src/ouroboros/harness` | 10 | 220374 | open |
| `src/ouroboros/hermes` | 2 | 45158 | open |
| `src/ouroboros/interview_adapters` | 8 | 24532 | open |
| `src/ouroboros/kiro` | 2 | 4750 | open |
| `src/ouroboros/mcp` | 89 | 2019304 | open |
| `src/ouroboros/observability` | 5 | 74805 | open |
| `src/ouroboros/opencode` | 7 | 104963 | open |
| `src/ouroboros/orchestrator` | 135 | 4001801 | open |
| `src/ouroboros/persistence` | 23 | 355246 | open |
| `src/ouroboros/plugin` | 33 | 465092 | open |
| `src/ouroboros/pm` | 3 | 2829 | open |
| `src/ouroboros/profiles` | 7 | 5473 | open |
| `src/ouroboros/providers` | 32 | 575952 | open |
| `src/ouroboros/resilience` | 4 | 55734 | open |
| `src/ouroboros/router` | 5 | 51257 | open |
| `src/ouroboros/runtime` | 4 | 19777 | open |
| `src/ouroboros/skills` | 2 | 2716 | open |
| `src/ouroboros/strategies` | 2 | 7417 | open |
| `src/ouroboros/tui` | 22 | 302652 | open |
| `src/ouroboros/verification` | 4 | 85778 | open |
| `tests/__init__.py` | 1 | 15 | open |
| `tests/_envelope_wiring.py` | 1 | 2104 | open |
| `tests/canonical` | 6 | 97565 | open |
| `tests/canonical/cli-todo` | 3 | 4918 | open |
| `tests/canonical/evidence` | 47 | 844393 | open |
| `tests/conformance` | 1 | 81 | open |
| `tests/conformance/workflow_ir` | 5 | 44786 | open |
| `tests/conftest.py` | 1 | 13257 | open |
| `tests/e2e` | 6 | 81296 | open |
| `tests/fixtures` | 1 | 4081 | open |
| `tests/fixtures/plugin` | 2 | 1040 | open |
| `tests/fixtures/plugins-fixture` | 4 | 3871 | open |
| `tests/fixtures/projection` | 1 | 1709 | open |
| `tests/fixtures/router` | 1 | 506 | open |
| `tests/fixtures/seeds` | 2 | 3658 | open |
| `tests/fixtures/zcode` | 2 | 1346 | open |
| `tests/integration` | 13 | 63823 | open |
| `tests/integration/auto` | 5 | 76790 | open |
| `tests/integration/mcp` | 9 | 157446 | open |
| `tests/integration/orchestrator` | 2 | 28076 | open |
| `tests/integration/plugin` | 5 | 79646 | open |
| `tests/integration/tui` | 2 | 20145 | open |
| `tests/test-execution-plan.md` | 1 | 9563 | open |
| `tests/unit` | 39 | 929890 | open |
| `tests/unit/agents` | 2 | 14349 | open |
| `tests/unit/auto` | 69 | 1578945 | open |
| `tests/unit/backends` | 3 | 36266 | open |
| `tests/unit/bigbang` | 30 | 701700 | open |
| `tests/unit/cli` | 77 | 1856916 | open |
| `tests/unit/codex` | 1 | 10996 | open |
| `tests/unit/config` | 5 | 200648 | open |
| `tests/unit/config_tui` | 5 | 64687 | open |
| `tests/unit/copilot` | 4 | 25126 | open |
| `tests/unit/core` | 35 | 471728 | open |
| `tests/unit/dashboard` | 2 | 15620 | open |
| `tests/unit/dashboard_web` | 8 | 152758 | open |
| `tests/unit/evaluation` | 23 | 329519 | open |
| `tests/unit/events` | 7 | 66421 | open |
| `tests/unit/evolution` | 18 | 449771 | open |
| `tests/unit/gjc` | 1 | 8728 | open |
| `tests/unit/harness` | 10 | 213050 | open |
| `tests/unit/hermes` | 1 | 78640 | open |
| `tests/unit/integrations` | 2 | 5733 | open |
| `tests/unit/interview_adapters` | 4 | 11527 | open |
| `tests/unit/mcp` | 115 | 2367831 | open |
| `tests/unit/observability` | 5 | 102633 | open |
| `tests/unit/opencode` | 1 | 2386 | open |
| `tests/unit/orchestrator` | 137 | 4676947 | open |
| `tests/unit/persistence` | 10 | 320707 | open |
| `tests/unit/plugin` | 24 | 382436 | open |
| `tests/unit/pm` | 2 | 12840 | open |
| `tests/unit/providers` | 31 | 624083 | open |
| `tests/unit/resilience` | 4 | 55250 | open |
| `tests/unit/router` | 14 | 157906 | open |
| `tests/unit/runtime` | 3 | 16346 | open |
| `tests/unit/scripts` | 19 | 355658 | open |
| `tests/unit/skills` | 2 | 58706 | open |
| `tests/unit/tui` | 9 | 148310 | open |
| `tools` | 1 | 7304 | open |

Total: 1,817 paths. Per-path source object IDs and coverage reside in the hashed D-drive manifests referenced by SOURCES.json.
No path is marked fully analyzed or adopted in this initial tranche. Upstream code/tests/installers have not been executed.
