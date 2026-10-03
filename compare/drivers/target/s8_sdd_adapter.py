"""Target driver: `review.sdd_adapter` on the target tree (S8 batch B8: `review.adapters.sdd`).

The API mirrors the reference driver's names over the target home. Composition (S10) is played by the two injections: `read_spec` receives
`composition.configuration.repository_root()` (resolved from the working directory per call, as M7 did) and the host_os `run_process` (R-sd1), and
`device_probe` receives the same `run_process` (R-sd2). The target's standard library and module attributes are never patched."""

import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

import s8_sdd_adapter  # noqa: E402
from codex_harness.composition.configuration import repository_root  # noqa: E402
from codex_harness.host_os.adapters.process_groups import run_process  # noqa: E402
from codex_harness.kernel.errors import ContractError  # noqa: E402
from codex_harness.review.adapters import sdd as module  # noqa: E402

API = SimpleNamespace(
    load_json=module.load_json, parse_json=module.parse_json,
    read_spec=lambda path, revision=None: module.read_spec(path, revision, root=repository_root(), run_process=run_process),
    write_export=module.write_export, render_review=module.render_review,
    device_probe=lambda: module.device_probe(run_process=run_process), adb_inventory=module.adb_inventory,
    replay_source=module.replay_source, ContractError=ContractError)

if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="zeus-s8-sdd-adapter-") as raw:
        result = s8_sdd_adapter.run(API, Path(raw).resolve())
    driver.finish("target", "review.sdd_adapter", result)
