"""Reference driver: `observation.schema` (M7 `adapters/contracts.py::validate_observation`)."""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

from types import SimpleNamespace  # noqa: E402

import s9_schema  # noqa: E402

from codex_harness.adapters.contracts import validate_observation  # noqa: E402
from codex_harness.domain.observation import REGISTRY, build_event, execution_identity  # noqa: E402

API = SimpleNamespace(validate=validate_observation, REGISTRY=REGISTRY, build_event=build_event, execution_identity=execution_identity)

if __name__ == "__main__":
    driver.finish("reference", "observation.schema", s9_schema.run(API))
