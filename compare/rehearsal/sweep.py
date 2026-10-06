"""The rehearsal label sweep (RH-1a rule 5, AMD-1 C.12/C.13): remove ONLY containers carrying BOTH
`zeus.test.fixture=1` and `zeus.rehearsal.run=<run8>`, prove absence, then remove ROOT last and prove it gone.

Removal is by NAME (the guard's fixture-prefix rule), using the names the admitted listing returned; a name
pattern alone never selects anything, and a production name is refused even when it carries the labels.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from . import Refused, check_run8
from .copies import MARKER, PRODUCTION_PREFIX, RUN_LABEL, guarded_docker, provider_guard


class SweepResidue(RuntimeError):
    def __init__(self, ids: list[str]):
        super().__init__(f"labelled containers remain after the sweep: {', '.join(ids)}")
        self.ids = ids


def _list(docker, run8: str, field: str) -> list[str]:
    done = docker("ps", "-a", "--filter", f"label={RUN_LABEL}={run8}", "--filter", f"label={provider_guard.FIXTURE_LABEL}",
                  "--format", field)
    if done.returncode != 0:
        raise RuntimeError("labelled container listing failed: " + done.stderr.strip()[-300:])
    return [line for line in done.stdout.split() if line]


def sweep(run8: str, root: Path | None = None, *, docker=None) -> dict:
    check_run8(run8)
    docker = docker or (lambda *args, timeout=120: guarded_docker(args, timeout=timeout))
    names = _list(docker, run8, "{{.Names}}")
    for name in names:
        if name.startswith(PRODUCTION_PREFIX):
            raise Refused("production_name", name)
    prefix = f"{provider_guard.FIXTURE_NAME_PREFIX}rh-{run8}-"
    removed = 0
    for name in names:
        if not name.startswith(prefix):
            continue  # labelled but outside this run's naming: left in place, reported as residue below
        done = docker("rm", "-f", name)
        if done.returncode != 0 and "no such container" not in done.stderr.lower():
            raise RuntimeError(f"removal of {name} failed: " + done.stderr.strip()[-300:])
        removed += 1
    residue = _list(docker, run8, "{{.ID}}")
    if residue:
        raise SweepResidue(residue)
    root_removed = None
    if root is not None:
        root = Path(root)
        marker = root / MARKER
        if root.exists():
            if root.is_symlink() or not marker.is_file() or marker.read_text(encoding="ascii").strip() != run8:
                raise Refused("root_not_owned", "the directory is not this run's rehearsal root")
            shutil.rmtree(root)
        if root.exists():
            raise RuntimeError("the rehearsal root is still present after removal")
        root_removed = True
    return {"removed": removed, "residue": residue, "root_removed": root_removed}
