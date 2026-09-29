"""Common start/finish for one comparison driver process (REBUILD-DESIGN-v2 §5.2 R-O, R-P).

Layer: harness (never shipped)

`start` refuses to run unless the R-P audit hook is installed (the runner puts `compare/guard` on
PYTHONPATH, whose `sitecustomize` installs it). `finish` asserts module origins for the side and
prints one JSON document: the scenario result plus the origin facts. Payload bytes are never
printed; drivers report digests, sizes, field names and statuses.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

HARNESS = Path(__file__).resolve().parent
COMPARE = HARNESS.parent


def start(side: str) -> None:
    if side not in {"reference", "target"}:
        raise SystemExit(f"unknown side {side!r}")
    sys.path.insert(0, str(COMPARE / "guard"))
    import provider_guard

    if not provider_guard.installed():
        raise SystemExit("R-P: provider guard is not installed in this driver process")


def finish(side: str, scenario: str, result: dict) -> None:
    import origin

    if side == "reference":
        files, facts = origin.record_files()
        seen = origin.assert_record_origins(files)
    else:
        root = Path(os.environ["ZEUS_REBUILD_TARGET_SRC"])
        seen = origin.assert_tree_origins(root)
        facts = {"tree": str(root)}
    report = {
        "scenario": scenario,
        "side": side,
        "origin": {**facts, "modules_checked": len(seen),
                   "python": ".".join(map(str, sys.version_info[:3]))},
        "result": result,
    }
    sys.stdout.write(json.dumps(report, sort_keys=True, ensure_ascii=False) + "\n")
