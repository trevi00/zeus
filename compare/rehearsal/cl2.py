"""Cutover RH-2b (owner): CL2 production post-checks (design "10. CL2"; AC11), as one pure function over injected readers.

After the window the following must all hold, and each is a named check in the receipt (facts only, never row text):
- `nonce_rows`: the nonce `rh-<run8>` occurs in no table row text of the restored d_post copy (count 0);
- `redis_manifest_equal_p0`: the Redis volume manifest equals the one P0's Phase P recorded;
- `containers_unchanged`: each container's Id/StartedAt/RestartCount and docker-diff digest equal P0's;
- `fleet_paused`: the Fleet is still paused;
- `no_residue`: the run label sweep leaves zero residue;
- `no_rehearsal_units`: `systemctl list-units 'zeus-rehearsal-*' --all` lists 0 units, through the injected runner.

Every reader is injected, so the caller decides which resources are read (production defaults in the window; labelled
stand-ins in the owner-run controls) and the logic is tested without docker.
"""

from __future__ import annotations

from . import check_run8

CONTAINER_KEYS = ("Id", "StartedAt", "RestartCount", "diff_sha256")
UNITS_ARGV = ["systemctl", "list-units", "zeus-rehearsal-*", "--all", "--no-legend", "--plain"]


def nonce(run8: str) -> str:
    return f"rh-{check_run8(run8)}"


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def count_nonce(conn, run8: str) -> int:
    """Rows, across every table outside pg_catalog/information_schema, whose whole-row text contains `rh-<run8>`."""
    tables = conn.execute("SELECT schemaname, tablename FROM pg_tables "
                          "WHERE schemaname NOT IN ('pg_catalog', 'information_schema') ORDER BY 1, 2").fetchall()
    total = 0
    for schema, table in tables:
        row = conn.execute(f"SELECT count(*) FROM {_quote(schema)}.{_quote(table)} AS t WHERE position(%s in t::text) > 0",
                           (nonce(run8),)).fetchone()
        total += int(row[0])
    return total


def post(run8: str, *, p0: dict, p0_redis: dict, gate_now, redis_now, nonce_count, sweep_now, runner) -> dict:
    """`p0` is P0's gate dict; `p0_redis` its Redis manifest; the others are zero-argument readers (`runner(argv)` runs
    the systemctl listing). Returns {"ok", "failed", "checks"}; every check runs even after a failure."""
    check_run8(run8)
    checks = {}
    count = nonce_count()
    checks["nonce_rows"] = {"count": count, "ok": count == 0}
    checks["redis_manifest_equal_p0"] = {"ok": redis_now() == p0_redis}
    now = gate_now()
    unchanged = set(now["containers"]) == set(p0["containers"]) and all(
        p0["containers"][name][key] == now["containers"][name][key] for name in p0["containers"] for key in CONTAINER_KEYS)
    checks["containers_unchanged"] = {"ok": unchanged}
    checks["fleet_paused"] = {"ok": now["paused"] is True}
    swept = sweep_now()
    checks["no_residue"] = {"removed": swept["removed"], "residue": len(swept["residue"]), "ok": swept["residue"] == []}
    listed = runner(UNITS_ARGV)
    units = len([line for line in (listed.stdout or "").splitlines() if line.strip()])
    checks["no_rehearsal_units"] = {"exit": listed.returncode, "units": units, "ok": listed.returncode == 0 and units == 0}
    failed = [name for name, fact in checks.items() if not fact["ok"]]
    return {"ok": not failed, "failed": failed, "checks": checks}
