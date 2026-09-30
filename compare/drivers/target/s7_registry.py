"""Target driver: `delivery.registry` on the target tree (the HostDelivery split, DESIGN-s7 V8; composed by
s7_delivery_composition)."""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

import s7_delivery_composition  # noqa: E402
import s7_registry  # noqa: E402

if __name__ == "__main__":
    driver.finish("target", "delivery.registry", s7_registry.run(s7_delivery_composition.api()))
