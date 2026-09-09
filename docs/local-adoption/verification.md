# Local verification — 2026-09-09 KST

Candidate: uncommitted working tree on `fix/portable-runtime-and-local-adoption`, based on
`0548efa`. `candidate-manifest.json` records SHA-256 for the 169 implementation, script,
test and deployment-definition files present during verification. No remote publication,
release promotion or production supervisor startup was performed.

| Check | Observed result |
|---|---|
| Windows native, Python 3.14.7, `uv run python scripts/check.py --integration` | Ruff passed; **584 passed, 7 skipped**, 177.11 s |
| Linux container, Python 3.13, full pytest with actual PostgreSQL/Redis | **591 passed**, 57.45 s |
| `git diff --check` | Passed |
| `uv build` | Source distribution and wheel built |
| Wheel contents | Supervisor, configuration, SQL resource and console entry point present |
| CLI from outside checkout using `uv run --project … harness --repository … doctor --offline` | All installation checks passed; this command does not test DB connectivity |
| Docker Compose configuration | Parsed successfully |
| Final Docker image | Built: `sha256:ce7dc98a9a14fd29032a67ebf6e664800e67905fa84a0a4b457945bfaedf0db4` |
| Windows actual Codex CLI 0.153.4 read/write canary | Passed; 7 runtime events |
| Final Docker image actual Codex read/write canary | Passed; receipt `sha256:8ae842eb1ef726e2bf6deb41c903b65b88c82ad4b7f0ff52392463507fb775cd` |

Linux pytest loaded the candidate source and tests through a read-only `/workspace` mount,
using the image's installed dependencies. The final image was rebuilt after the last code
change, and its file canary executed installed image code. This distinguishes source testing
from the packaged image smoke check. Neither canary is a simulated model response.

PostgreSQL and Redis ran in the dedicated `codex-harness-validation` Compose project.
Tests used isolated schemas/namespaces. The skill-history integration test originally
assumed an already-created global `documents` table; it now uses a freshly migrated private
schema and cleans it up. The validation project is separate from the production Compose name.

Local detailed receipts (gitignored):

- `.runtime/validation-windows.txt`
- `.runtime/validation-linux.txt`
- `.runtime/canary-windows.txt`
- `.runtime/canary-linux.json`
- `.runtime/portability-canary/8ae842eb1ef726e2bf6deb41c903b65b88c82ad4b7f0ff52392463507fb775cd.txt`

Remaining validation: upstream semantic review and execution; independent candidate review;
the newly defined remote CI matrix; Linux host startup/service registration; Windows/WSL
long-running restart and update scenarios; actual release promotion and rollback under load.
The test counts above do not establish these outcomes or completion of the full migration.
