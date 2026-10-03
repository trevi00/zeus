"""Reference driver: `review.sdd_adapter` (M7 `adapters/sdd.py`).

The API holds the plain M7 module. M7 resolves `repository_root()` from the working directory (the fixture repository's `pyproject.toml` names
`zeus-harness`) and calls the module-level `run_process` (the real `adapters.commands` one); `shutil.which`, `ANDROID_HOME`, `ANDROID_SDK_ROOT` and
`Path.home()` read the scenario's scripted environment. No device, network or provider is used."""

import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

import s8_sdd_adapter  # noqa: E402

from codex_harness.adapters import sdd as module  # noqa: E402
from codex_harness.domain.model import ContractError  # noqa: E402

API = SimpleNamespace(
    load_json=module.load_json, parse_json=module.parse_json, read_spec=module.read_spec, write_export=module.write_export,
    render_review=module.render_review, device_probe=module.device_probe, adb_inventory=module.adb_inventory,
    replay_source=module.replay_source, ContractError=ContractError)

if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="zeus-s8-sdd-adapter-") as raw:
        result = s8_sdd_adapter.run(API, Path(raw).resolve())
    driver.finish("reference", "review.sdd_adapter", result)
