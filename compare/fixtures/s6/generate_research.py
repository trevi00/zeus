"""Generate the S6 recorded research fixtures from SOURCE M7 test flows (LABELLED input, not a golden).

Layer: harness (never shipped)

Why recorded: the research-held continuation state (Portfolio grouping, an opted-in research program, a council
run row and its dispatch) is produced by research and intake application code that moves in S8. Both comparison
drivers load these rows as identical inputs, so the S6 goldens characterize the continuation/owner-action logic
over them without depending on unmoved contexts (DESIGN-s6 §7).

Provenance: SOURCE M7 e38aa722 (`src/` and `tests/` unchanged, checked below); the M7 dev environment (the
repository root `.venv`, which imports `src/`); the harness determinism patches (a 1 ms ticking FakeClock, FakeIds) installed
after every M7 module is imported; pinned Git identity/dates (GIT_ENV); a fixed temporary root that is recreated for every
run. The output is byte-reproducible:
run it twice and compare. Run from the repository root:

    .venv/bin/python compare/fixtures/s6/generate_research.py compare/fixtures/s6/research.json
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(os.environ.get("ZEUS_REBUILD_REPO") or Path(__file__).resolve().parents[3])
SOURCE = "e38aa722"
ROOT = Path("/tmp/zeus-rebuild-s6-fixture")
sys.path[:0] = [str(REPO / "tests"), str(REPO / "compare" / "harness")]
# Deterministic Git objects (RESEARCH-S6 R4, Pro Git "Environment Variables"): the research flow commits into a
# fixture repository, and a commit id covers its author/committer identity and dates. Pin both, and isolate the
# user's and the system's Git configuration.
GIT_ENV = {"GIT_AUTHOR_NAME": "zeus-fixture", "GIT_AUTHOR_EMAIL": "fixture@zeus.invalid",
           "GIT_COMMITTER_NAME": "zeus-fixture", "GIT_COMMITTER_EMAIL": "fixture@zeus.invalid",
           "GIT_AUTHOR_DATE": "2026-09-30T00:00:00+00:00", "GIT_COMMITTER_DATE": "2026-09-30T00:00:00+00:00",
           "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1"}


def unchanged() -> None:
    done = subprocess.run(["git", "-C", str(REPO), "diff", "--quiet", SOURCE, "--", "src", "tests"])
    if done.returncode != 0:
        raise SystemExit("src/ or tests/ differ from SOURCE " + SOURCE + ": refusing to record")


def ticking_clock():
    """A FakeClock that advances 1 ms per read: deterministic, and strictly increasing like real time. The flows
    order rows by (created_at, id), so a frozen clock would change which prior failures count (checked: the M7
    `budget_refused` flow fails under a frozen clock and passes under this one)."""
    import datetime

    import determinism

    class TickingClock(determinism.FakeClock):
        def now(self, tz=None):
            value = super().now(tz)
            self.advance(0.001)
            return value

    return TickingClock(), datetime


def rows(store) -> list:
    with store.transaction() as tx:
        return sorted(({"bucket": r["bucket"], "id": r["id"], "body": r["body"]} for r in tx.records()),
                      key=lambda r: (r["bucket"], r["id"]))


def held_flow(tmp: Path) -> dict:
    import test_continuation_research as tcr

    world = tcr.World(tmp)
    root, successor, research, investigation, dispatch = tcr.held(world, tmp)
    return {"flow": "tests/test_continuation_research.py::held", "world": world,
            "ids": {"root": root, "successor": successor, "research_intent": research["id"],
                    "investigation": investigation}}


def accepted003_flow(tmp: Path) -> dict:
    import test_continuation_research as tcr

    world = tcr.World(tmp)
    root, successor, research, investigation, dispatch, repair = tcr.accepted003(world, tmp)
    return {"flow": "tests/test_continuation_research.py::accepted003", "world": world,
            "ids": {"root": root, "successor": successor, "research_intent": research["id"],
                    "investigation": investigation, "repair_intent": repair["id"]}}


def budget_refused_flow(tmp: Path) -> dict:
    import test_continuation_research as tcr

    world = tcr.World(tmp, max_corrections=2)
    family = tcr.budget_refused(world, tmp)
    return {"flow": "tests/test_continuation_research.py::budget_refused", "world": world,
            "ids": {"child": family["child"], "refused_intent": family["refused"]["id"],
                    "research_intent": family["research"]["id"]}}


FLOWS = {"held": held_flow, "accepted003": accepted003_flow, "budget_refused": budget_refused_flow}


def artifacts(root: Path) -> dict:
    """ref -> text of every artifact the flow stored (the evidence bytes the scenarios verify)."""
    import hashlib

    out = {}
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        data = path.read_bytes()
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            continue
        out["sha256:" + hashlib.sha256(data).hexdigest()] = text
    return out


def main(argv) -> int:
    unchanged()
    os.environ.update(GIT_ENV)
    import determinism
    import test_continuation  # noqa: F401  (every M7 module the flows use is imported before patching)
    import test_continuation_research as tcr

    out = {"schema": "zeus:rebuild-s6-fixture:1", "source_commit": "e38aa722", "generator":
           "compare/fixtures/s6/generate_research.py", "labelled": True, "flows": {},
           "texts": {"report": tcr.REPORT, "attestation": tcr.ATTESTATION, "rationale": tcr.RATIONALE}}
    for name, flow in FLOWS.items():
        determinism.install(ticking_clock()[0], determinism.FakeIds())
        if ROOT.exists():
            shutil.rmtree(ROOT)
        ROOT.mkdir(parents=True)
        made = flow(ROOT)
        world = made["world"]
        out["flows"][name] = {
            "flow": made["flow"], "ids": made["ids"], "evidence": artifacts(ROOT / "runtime" / "artifacts"),
            "policy_document": world.document, "pin": world.pin,
            "runtime": world.runtime("a"), "control": rows(world.control), "lane": rows(world.lane.store)}
    shutil.rmtree(ROOT, ignore_errors=True)
    Path(argv[1]).write_text(json.dumps(out, sort_keys=True, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
