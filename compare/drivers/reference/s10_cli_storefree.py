"""Reference driver: `entry.cli_storefree` on SOURCE M7 (REBUILD-DESIGN-v2 §5.2a, §5.3 S10 unit C1).

M7 `codex_harness.cli.main` runs in-process with `sys.argv` patched, in a fresh fixture repository
(see compare/drivers/common/s10_cli_storefree.py).
"""

import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

import s10_cli_storefree  # noqa: E402

from codex_harness.cli import main  # noqa: E402

if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="zeus-s10-c1-") as raw:
        result = s10_cli_storefree.run_all(main, Path(raw).resolve())
    driver.finish("reference", "entry.cli_storefree", result)
