"""Reference driver: `delivery.maintenance` / `delivery.maintenance.pg` on the approved rebaseline wheel (main-s2r-b9d8f15;
M7 has no maintenance, G1-13C-COMPARE-DECISION rule 5). The api is the rebaseline's own LABELLED fixtures module,
`tests/host_delivery_maintenance_fixtures.py` of the SOURCE overlay (`ZEUS_REBUILD_SOURCE_ROOT`), imported unchanged.

The reference venv has no pytest: the fixtures' test modules import it only for decorators at import time, so a
LABELLED stand-in module (decorators return the function, `mark.*` and `fixture` are no-ops) is registered first.
`backend(root)` selects the stores: memory (the fixtures' own), or with `ZEUS_REBUILD_PG_DSN` a fresh schema per store on
the labelled disposable PostgreSQL, migrated by this side's PostgresStore."""

import os
import sys
import types
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

SOURCE_ROOT = Path(os.environ["ZEUS_REBUILD_SOURCE_ROOT"]).resolve()


class _Mark:
    def __getattr__(self, name):
        def decorate(*args, **kwargs):
            return args[0] if len(args) == 1 and callable(args[0]) and not kwargs else (lambda function: function)
        return decorate


_pytest = types.ModuleType("pytest")
_pytest.mark = _Mark()
_pytest.fixture = lambda *a, **k: a[0] if a and callable(a[0]) else (lambda function: function)
sys.modules["pytest"] = _pytest
sys.path.insert(0, str(SOURCE_ROOT / "tests"))

import determinism  # noqa: E402
import host_delivery_maintenance_fixtures as F  # noqa: E402
import s2r_maintenance  # noqa: E402
from types import SimpleNamespace  # noqa: E402

from codex_harness.adapters.store import PostgresStore  # noqa: E402

# The modules' own `utcnow()`/`uuid4()` (release `created_at`, the active pointer and queue `at`) follow one fake timeline
# at the fixtures' START (2026-09-22), as the s7 delivery drivers do; the fixtures' injected Clock is unchanged.
determinism.install(determinism.FakeClock(F.Clock().at), determinism.FakeIds())

PG_DSN = os.environ.get("ZEUS_REBUILD_PG_DSN")
SCENARIO = "delivery.maintenance.pg" if PG_DSN else "delivery.maintenance"
_counter = [0]


def _pg_store():
    import psycopg
    from psycopg.conninfo import make_conninfo

    _counter[0] += 1
    schema = f"s2r_maint_{_counter[0]}"
    with psycopg.connect(PG_DSN, autocommit=True) as conn:
        conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        conn.execute(f'CREATE SCHEMA "{schema}"')
    store = PostgresStore(make_conninfo(PG_DSN, options=f"-c search_path={schema},public"))
    store.migrate()
    return store


def backend(root):
    if PG_DSN and not getattr(F.LinkedStore, "_pg", False):
        original = F.LinkedStore.__init__

        def init(self, group, name):
            original(self, group, name)
            self.inner = _pg_store()
        F.LinkedStore.__init__, F.LinkedStore._pg = init, True


if __name__ == "__main__":
    driver.finish("reference", SCENARIO, s2r_maintenance.run(SimpleNamespace(F=F, backend=backend)))
