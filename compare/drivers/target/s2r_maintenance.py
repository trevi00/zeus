"""Target driver: `delivery.maintenance` / `delivery.maintenance.pg` on the target tree (the ported S2R maintenance, G1-13).

The api is the ported fixtures module `tests/ported/host_delivery_maintenance_fixtures.py` (S2R's fixture bodies; import
lines adapted), imported unchanged from the checkout the run copy was made from. The ported delivery modules bind a
git-attested runtime root that `tests/ported/conftest.py` builds under pytest; here it is built the same way (a COPY of the
target `src/codex_harness`, committed once under the pinned identity and empty git configuration) before the fixtures are
imported. `backend(root)` is the reference driver's: memory, or a fresh schema per store on the disposable PostgreSQL."""

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

CHECKOUT = HERE.parents[1]
sys.path[:0] = [str(CHECKOUT / "tests" / "ported"), str(CHECKOUT / "tests")]

import ported_support  # noqa: E402

_base = Path(tempfile.mkdtemp(prefix="zeus-s2r-attested-"))
_root = _base / "attested-runtime"
shutil.copytree(Path(os.environ["ZEUS_REBUILD_TARGET_SRC"]) / "codex_harness", _root / "src" / "codex_harness",
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
(_base / "empty-gitconfig").write_text("", encoding="utf-8")
_environment = {**os.environ, "GIT_AUTHOR_NAME": "Zeus Fixture", "GIT_AUTHOR_EMAIL": "fixture@zeus.invalid",
                "GIT_AUTHOR_DATE": "2026-09-22T00:00:00+00:00", "GIT_COMMITTER_NAME": "Zeus Fixture",
                "GIT_COMMITTER_EMAIL": "fixture@zeus.invalid", "GIT_COMMITTER_DATE": "2026-09-22T00:00:00+00:00",
                "GIT_CONFIG_GLOBAL": str(_base / "empty-gitconfig"), "GIT_CONFIG_SYSTEM": str(_base / "empty-gitconfig")}
for _args in (("init", "-q", "-b", "main"), ("add", "--all"), ("commit", "-q", "--no-verify", "-m", "attested runtime fixture")):
    _done = subprocess.run(["git", "-c", "commit.gpgsign=false", *_args], cwd=str(_root), env=_environment,
                           capture_output=True, text=True, timeout=120)
    assert _done.returncode == 0, _done.stderr[-500:]
ported_support.ATTESTED["root"] = str(_root)

from types import SimpleNamespace  # noqa: E402

import host_delivery_maintenance_fixtures as F  # noqa: E402
import s2r_maintenance  # noqa: E402
from codex_harness.storage.adapters.postgres_store import PostgresStore  # noqa: E402

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
    driver.finish("target", SCENARIO, s2r_maintenance.run(SimpleNamespace(F=F, backend=backend)))
