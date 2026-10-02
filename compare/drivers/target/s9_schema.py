"""Target driver: `observation.schema` on the target tree (`observation.adapters.observation_schema.validate_observation`)."""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

from types import SimpleNamespace  # noqa: E402

import s9_schema  # noqa: E402
from codex_harness.observation.adapters.observation_schema import validate_observation  # noqa: E402
from codex_harness.observation.domain.observation import (  # noqa: E402
    REGISTRY,
    build_event,
    execution_identity,
)

API = SimpleNamespace(validate=validate_observation, REGISTRY=REGISTRY, build_event=build_event, execution_identity=execution_identity)

if __name__ == "__main__":
    driver.finish("target", "observation.schema", s9_schema.run(API))
