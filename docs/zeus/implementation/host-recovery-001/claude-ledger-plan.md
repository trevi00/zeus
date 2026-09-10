## Migration review — concrete failure modes

**Plan is sound; the ordering (dump → verify → stop → rename → recreate) is correct.** Gaps below, in priority order.

**Silent-empty-cluster risk (worst case).** If the original sets `PGDATA` to a subdirectory of `/var/lib/postgresql/data` and the new container omits it, the entrypoint sees an empty dir and runs `initdb` — a fresh empty ledger on the same volume, with the real data still present but unreferenced. Copy `Config.Env`, `Mounts`, `Cmd`, `Entrypoint`, `Healthcheck` verbatim from `docker inspect` of the original; don't reconstruct from memory or from compose.yaml.

**Capture inspect JSON before touching anything.** The renamed stopped container is your only rollback artifact, and any `docker system/container prune` deletes it. Persist the full inspect output to `.runtime/host-recovery` so the container is reproducible even if the artifact is lost.

**Dump correctness.** Run `pg_dump` via `docker exec` in the original container, not over the host port — that removes the dependency on the possibly-stale `.env` port and guarantees client/server version match. Custom format is per-database: it excludes roles, passwords and grants. Add `pg_dumpall --globals-only` or a dump-based rollback restores data with unusable auth.

**Quiesce before dump.** The dump is an MVCC snapshot, so it's internally consistent, but if the worker writes after it, your "unchanged digest" comparison is against a moving target. Suspend the worker first (consistent with the Python-side suspension already discussed: no heartbeat side thread once the fresh-connection context returns, `PostgresStore` has no pool, so there is no background writer to miss).

**Digest determinism.** Fix `ORDER BY` on a stable key, pin `TimeZone`/`DateStyle`, and compare **sequence last_values separately** — row digests match while a lost sequence position causes PK collisions later.

**Stop semantics.** Postgres treats SIGTERM as *smart* shutdown and waits for clients; the 10s default then SIGKILLs it, forcing crash recovery. Use an explicit long stop timeout and confirm `State.Running=false` before creating the new container — rename does not stop, and two postmasters on one named volume across containers is the corruption path.

**Durability of the fix.** If the container carries compose labels, a later `docker compose up` recreates it at 55432 and discards the manual container. Updating `compose.yaml` to 63556 is the actual repair; the hand-created container alone reproduces last reboot's drift.

Pause 2/12 keeping the deadline alive is correct IO-stall coverage; deadline crossing stays a separate native case. Port rediscovery remains test-only, not autohealing.