"""Guard-free constants and the ROOT creator shared by `copies` and the owner-run Phase P path (RH-2c, D-RH2-RUNNER-GUARD).

`copies` loads `compare/run.py`, whose import-time `provider_guard.install()` puts the test audit hook in the process.
The production Phase P script and its owner-run control runner must never reach that, so everything they need from
`copies` lives here instead: this module only *imports* `provider_guard` (names and pure policy); nothing here installs it.
Standard library only, plus `Refused`-free helpers.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

COMPARE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(COMPARE / "guard"))
import provider_guard  # noqa: E402,F401  (imported, never installed)

PRODUCTION_PREFIX = "zeus-aibox-"
RUN_LABEL = "zeus.rehearsal.run"
MARKER = ".rehearsal-root"
# Mirrors compare/run.py PG_IMAGE/REDIS_IMAGE (not importable here: run.py installs the guard); tests pin the equality.
PG_IMAGE = "pgvector/pgvector@sha256:cf134a767f474095eeba57e0117be8e568e011a63f33fbf252f14c9b760f8e6f"
REDIS_IMAGE = "redis@sha256:858f009f9709ce576febc734aa78b8f6d624b82571f9ddb6bda4377c833b3499"


def create_root(root: Path, run8: str) -> None:
    """Create ROOT itself, exclusively and umask-proof 0700, with the run marker (RH-8 F4); its parent may be created."""
    root = Path(root)
    root.parent.mkdir(parents=True, exist_ok=True)
    os.mkdir(root, 0o700)  # exclusive: FileExistsError if anything (even a symlink) is already there
    os.chmod(root, 0o700)  # the umask may have cleared bits mkdir would otherwise keep
    marker = os.open(root / MARKER, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(marker, "w", encoding="ascii") as handle:
        handle.write(run8 + "\n")
