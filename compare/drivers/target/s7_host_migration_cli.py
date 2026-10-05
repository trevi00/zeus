"""Target driver: `delivery.host_migration_cli` on the target tree (S11 unit AR4-T; the S10 operator CLI).

The API is the target `delivery.host_migration_transfer` driver's (loaded from its file under a private module name, so its
V6 injections, clock seam and hooks are the ones that family already proves equal) plus the S10 CLI the reference family
reaches through M7 `adapters.host_migration`:
- `main` is `entry.processes.host_migration.main` (the S10 process root; the M7 module path is a kept shim over it);
- `patched(**attrs)` routes each patched name to the module that now holds it: `_coordinator` to
  `composition.host_migration_cli` (where `execute` reads it), `_posix` and `recovery_preconditions` to the delivery adapter
  (where `switch_effect` reads them), as M7's one module held all three. A patched two-argument `recovery_preconditions`
  accepts and ignores the `runner`/`proc` keywords the moved `switch_effect` passes (the transfer driver's rule).

The clock seam is the transfer driver's `fake_utcnow` (the fence document's `at`)."""

import contextlib
import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

import s7_host_migration_cli  # noqa: E402
from codex_harness.composition import host_migration_cli as composition  # noqa: E402
from codex_harness.delivery.adapters import host_migration as adapter  # noqa: E402
from codex_harness.entry.processes import host_migration as entry  # noqa: E402

_path = Path(__file__).resolve().with_name("s7_host_migration_transfer.py")
_spec = importlib.util.spec_from_file_location("target_s7_host_migration_transfer", _path)
transfer = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(transfer)

_HOMES = {"_coordinator": composition}  # every other patched name lives in the delivery adapter


@contextlib.contextmanager
def patched(**attributes):
    saved = [(_HOMES.get(name, adapter), name, getattr(_HOMES.get(name, adapter), name)) for name in attributes]
    for name, value in attributes.items():
        if name == "recovery_preconditions":
            value = transfer._accepting_runner(value)
        setattr(_HOMES.get(name, adapter), name, value)
    try:
        yield
    finally:
        for module, name, value in saved:
            setattr(module, name, value)


API = transfer.SimpleNamespace(**{**vars(transfer.API), "main": entry.main, "patched": patched})

if __name__ == "__main__":
    with transfer.fake_utcnow():
        result = s7_host_migration_cli.run(API)
    driver.finish("target", "delivery.host_migration_cli", result)
