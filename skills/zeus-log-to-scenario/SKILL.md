---
name: zeus-log-to-scenario
description: Turn Zeus device or application observation logs into version-bound scenario proposals for human oracle review. Use for log-to-scenario and replay preparation in Zeus SDD workflows.
---

Use the Zeus checkout containing `docs/sdd/README.md`. Inspect `zeus sdd --help` and that document for the installed contract and command syntax.

1. Bind a strict spec snapshot to the current local ticket revision using `zeus sdd register`. Keep the Git definition and runtime snapshot distinct; a working tree draft is not a reviewed candidate commit.
2. Record the actual environment and ordered events. Preserve missing events as sequence gaps or `kind: gap`. Record both event time and observed time; do not invent device versions, timestamps, reset receipts, successful requests or source artifacts. Redact account secrets and personal data before import while preserving stable correlation identifiers.
3. Use `zeus sdd import-log`, then `zeus sdd propose`. Inspect missing and orphan scenario IDs, environment identity and the immutable observation reference.
4. Present the proposal alongside the spec using `view-iteration`. Ask for the intended success condition when it is absent. Observed behavior, including a successful-looking screen, cannot define a human-approved oracle.
5. Export replay code only for a concrete supported target with reviewed assertion bindings and real selector provenance. `export-replay` generates unexecuted code; it neither performs the run nor certifies physical-device execution. Financial flows require an actual reviewed backend reconciliation integration, which this first slice does not implement.

Imported logs, reviewer names and model transfer records grant no QA or deployment authority. Preserve the blocked state when the authenticated human decision provider or actual runner is unavailable. Use the repository's existing release workflow when those integrations are implemented; do not route around it.
