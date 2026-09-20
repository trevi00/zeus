# Skill source discovery: bounded adaptation decision

2026-09-20. Same SPEC.md frame and fixed SOURCES.json pins. Analysis only.

## Decision

**Reuse Zeus's Git-revision-bound project skill selection; do not port Ouroboros's ancestor-directory
discovery into worker execution.** Shared package discovery is useful for an installer but serves a
different authority contract. It does not establish the exact skill bytes used by a reviewed job.
This closes the design choice for source discovery at the inspected boundary, not the entire
skills/installers/router subsystem or whole-source semantic coverage.

## Source evidence

- Ouroboros `skills/artifacts.py` (all 86 lines) and `skills/__init__.py` (1 line): explicit directory
  override, importlib package resources, then ancestor `skills` fallback; child bundles are sorted
  and recognized by SKILL.md existence. Explicit override is yielded without bundle validation here.
- `codex/artifacts.py` 127–211: the Codex wrapper uses the shared resolver and a separate collector
  refuses an empty bundle. Thus the resolver's empty-directory behavior must not be generalized to
  every consumer as a proved failure.
- `hermes/artifacts.py` 1037–1063: Hermes tries its repository-root helper before shared package
  discovery. Consumer order differs; one universal installed/editable priority would be inaccurate.
- `router/registry.py` 60–136: registry builds targets from discovered bundles and exposes normalized
  identifiers. Full target parsing, installer mutations and routing execution remain open.
- `tests/unit/skills/test_skill_artifacts.py` 1168–1193: a temporary directory and patched package
  discovery test the editable fallback. Read only; upstream tests were not run.
- Zeus `adapters/project_skills.py` 95–160: reads the requested Git revision, requires regular Git
  file modes, bounds skill bytes, stores content references and a selection manifest. Context
  recommendations explicitly do not claim verified stage completion.

## Review matrix

| Boundary | Decision and evidence limit |
|---|---|
| Normal installed/editable lookup | Resolver and three direct consumers inspected; retain distinction from execution authority |
| Empty/missing source | Empty resolver result and consumer rejection are distinct; no invented global guarantee |
| Unknown source version | Zeus revision/content references retained; local ancestor discovery cannot replace them |
| Concurrency/restart | No source-discovery mutation or restart contract added; installer ownership remains open |
| Platform/cleanup | No installation or global-skill mutation executed; archive resource lifecycle not qualified here |
| Acceptance | Existing Zeus project skill contract tests run separately; no upstream runtime claim |

This substep is Codex source analysis and self-crosscheck, not a separate independent review session.
Raw source ranges reside in the D-drive read ledger. No upstream code copied; no new licensing
decision for code transfer is implied. No new project skill, provider call, deployment or team created.

## Executed checks

See `D:/workspaces/zeus/artifacts/self-improvement-reference-001/packaging-001.json` and its log/JUnit.
The runner uses `pytest tests/test_project_skills.py -q -p no:cacheprovider`, removes ZEUS_/HARNESS_
environment variables and writes evidence outside the checkout. **29 passed, zero skipped**, exit 0,
pytest 12.60 seconds. This checks existing local contracts, not live worker operation.
Log SHA-256: `07182edd45c69d17a486baee8d20d0ecf159ef6288e5bb1988fa4882f2ed457a`.
