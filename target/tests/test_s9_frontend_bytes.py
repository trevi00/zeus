"""S9 unit U10: the monitor frontend bytes and the packaged observatory assets are unchanged (design §3.1: "unchanged bytes; built assets packaged as target
resources").

`compare/goldens/reference/observation.frontend_bytes.json` is the sha256/size manifest recorded from SOURCE e38aa722 (never edited by hand). Every ledger row
for `frontend/monitor/*` and the five `resources/` rows is covered by it, and the head's bytes equal it exactly (the compare family does the same through its
target driver; this test states it without the harness). Nothing is built or executed.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
FRONTEND = REPO / "frontend" / "monitor"
RESOURCES = REPO / "target" / "src" / "codex_harness" / "resources"
SOURCE = "e38aa722"
MANIFEST = json.loads((REPO / "compare" / "goldens" / "reference" / "observation.frontend_bytes.json").read_text(encoding="utf-8"))
LEDGER = json.loads((REPO / "coverage" / "ledger-coverage.json").read_text(encoding="utf-8"))["rows"]
FRONTEND_ROWS = sorted(r["key"].removeprefix("module:frontend/monitor/") for r in LEDGER if r["key"].startswith("module:frontend/monitor/"))
RESOURCE_PREFIX = "resource:src/codex_harness/resources/"
RESOURCE_ROWS = sorted(r["key"].removeprefix(RESOURCE_PREFIX) for r in LEDGER
                       if r["key"] == RESOURCE_PREFIX + "monitor.html" or r["key"].startswith(RESOURCE_PREFIX + "observatory/"))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_the_manifest_counts_and_shape():
    assert MANIFEST["counts"] == {"frontend_monitor": 52, "packaged_resources": 5}
    assert len(MANIFEST["frontend_monitor"]) == 52 and len(MANIFEST["packaged_resources"]) == 5
    for entry in [*MANIFEST["frontend_monitor"].values(), *MANIFEST["packaged_resources"].values()]:
        assert sorted(entry) == ["sha256", "size"] and len(entry["sha256"]) == 64


def test_every_ledger_frontend_row_and_resource_row_is_covered_by_the_manifest():
    assert len(FRONTEND_ROWS) == 38 and len(RESOURCE_ROWS) == 5
    assert not [row for row in FRONTEND_ROWS if row not in MANIFEST["frontend_monitor"]]
    assert RESOURCE_ROWS == sorted(MANIFEST["packaged_resources"])
    # the manifest also covers the 14 files the ledger does not list one by one (dotfiles, lock file, public/, README, configs)
    assert len(set(MANIFEST["frontend_monitor"]) - set(FRONTEND_ROWS)) == 14


def test_the_heads_frontend_and_packaged_bytes_equal_the_manifest_with_no_extra_file():
    head = {p.relative_to(FRONTEND).as_posix(): p for p in FRONTEND.rglob("*") if p.is_file()}
    assert sorted(head) == sorted(MANIFEST["frontend_monitor"])
    for name, entry in MANIFEST["frontend_monitor"].items():
        assert (head[name].stat().st_size, sha(head[name])) == (entry["size"], entry["sha256"]), name
    packaged = {"monitor.html": RESOURCES / "monitor.html", **{p.relative_to(RESOURCES).as_posix(): p for p in (RESOURCES / "observatory").rglob("*") if p.is_file()}}
    assert sorted(packaged) == sorted(MANIFEST["packaged_resources"])
    for name, entry in MANIFEST["packaged_resources"].items():
        assert (packaged[name].stat().st_size, sha(packaged[name])) == (entry["size"], entry["sha256"]), name


def test_the_manifest_is_the_source_blobs():
    """The golden is a recording of SOURCE: each entry equals the sha256 of the pinned commit's blob."""
    for name, entry in MANIFEST["frontend_monitor"].items():
        blob = subprocess.run(["git", "-C", str(REPO), "show", f"{SOURCE}:frontend/monitor/{name}"], check=True, capture_output=True).stdout
        assert (len(blob), hashlib.sha256(blob).hexdigest()) == (entry["size"], entry["sha256"]), name
    for name, entry in MANIFEST["packaged_resources"].items():
        blob = subprocess.run(["git", "-C", str(REPO), "show", f"{SOURCE}:src/codex_harness/resources/{name}"], check=True, capture_output=True).stdout
        assert (len(blob), hashlib.sha256(blob).hexdigest()) == (entry["size"], entry["sha256"]), name
