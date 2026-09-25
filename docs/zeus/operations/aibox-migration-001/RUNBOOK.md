# aibox migration live runbook (INV-HOST-MIGRATION-001)

SSOT: SPEC-retirement-update (aibox-migration-001). The components are:

- the core coordinator (`src/codex_harness/*/host_migration.py`);
- the canonical offline data tooling (`scripts/aibox_data`, see its RUNBOOK);
- the Linux service templates and launcher (`deploy/aibox`, see README and
  INTEGRATION-CONTRACT).

No step here has been run live. Every step that touches the Windows source, `/srv`, systemd,
networking or secrets is an **owner step** at the named gate.

Terms:

- `M` = `python -m codex_harness.adapters.host_migration`, run from the reviewed release venv.
- DSNs are passed only by environment-variable NAME.
- Every check command exits 0 only when its typed receipt is `ok`. A receipt goes into a
  transition's `evidence` unchanged.
- The coordinator records receipts. A state is not itself proof.

## 0. Ownership map

| Concern | Owner | Tool |
|---|---|---|
| State, checkpoints, activation intent, rollback mode | coordinator | `M plan/advance/checkpoint/intend-activation/rollback-plan/status` |
| Artifact inventory, stage, verify | canonical | `M artifact-inventory/-stage/-verify` (delegated) |
| PG export | core (live, read-only) | `M pg-export` |
| PG inventory, compare | canonical | `M pg-inventory`, `M pg-compare-schema` (one schema each), `M pg-coverage` |
| Redis export, copy | core | `M redis-inventory`, `M redis-copy` (verified by canonical `compare-redis`) |
| PEL owners, R0/R1/C gates | canonical | `M pel-owners`, `M gate r0\|r1\|c` |
| Registry host rebinding (D2) | Fleet | `zeus fleet migrate-host` (`Fleet.migrate_host`; same-host `relocate` unchanged) |
| PG whole-DB restore (D3) | core | `M pg-dump-db`, `M pg-catalog`, `M pg-restore-db [--reverse]`, `M pg-compare-catalog` |
| Units, launcher, fence/activation checks, inspection | deploy/aibox | `zeus_aibox_service.py render/verify/launch/inspect/host-id` |
| Launcher files | coordinator-derived | `M activation-write` (from the intent), `M fence-write` |
| Unit control | HostDelivery `systemd_unit` target | `systemctl show/start/stop zeus-aibox-*.service`, restricted rights |

## 1. N and plan (owner)

1. Re-read the address, route and link. Check SSH both ways, outbound HTTPS and NTP. Record the
   result as an `observation` receipt for `network_receipt`.
2. Supply the missing exports in `SOURCE-EXPORT-REQUIREMENTS.json`. Decisions D1–D3 are recorded
   there and implemented (§4).
3. `M validate --file manifest.json`, then `M plan --file manifest.json --dsn-env ZEUS_AIBOX_DSN
   --schema zeus_aibox_migration`. The coordinator schema is created and migrated by the owner.

## 2. staged (owner, root)

1. Create `/srv/zeus` (`M prepare-layout --root /srv/zeus`, then `--apply`).
2. Stand up the dedicated `zeus-aibox` stack: pgvector pg17 and Redis 7.4, both pinned by digest,
   published to loopback or the Docker network only.
3. Build the release at its final path: `/srv/zeus/releases/<40-hex>/.venv` via
   `uv sync --frozen` AT that path. Never copy a venv. `current` points to it.
4. Set `ZEUS_AIBOX_ROOT=/srv/zeus` for the HostDelivery process. `controller()` derives and
   validates `/srv/zeus/runtime/control` from it for the `systemd_unit` target. If it is missing
   or invalid, the target refuses to start the unit.
5. Render and verify the units (`deploy/aibox/zeus_aibox_service.py render` / `verify
   --systemd-analyze`). Install them, and grant a polkit or sudoers rule limited to
   `systemctl start|stop zeus-aibox-*.service` for the service UID. `reset-failed` stays a human
   action.
6. Rehearse the staging restore with a dry-run export (§4). Its `pg-coverage` receipt is
   `staging_restore`.

## 3. draining → source_fenced → snapshot_sealed (owner, Windows)

1. `zeus fleet pause`, then drain HostDelivery and settle unknowns (`fleet reconcile-interrupted`).
   Record this as `admission_pause`.
2. Stop and fence every `stop_and_fence` writer. Record `writer_inventory` (processes, labels,
   leases) and `restart_refusal`.
3. Seal at the barrier:
   - `M pg-export --role source` for every mapped schema (public included), then
     `M pg-inventory --role source` → `pg_inventory`;
   - `M redis-inventory` → `redis_inventory`;
   - `M artifact-inventory` → `artifact_inventory`.

## 4. restore (snapshot_sealed → restored_paused)

Each step first checks `completed_step`, and ends with `M checkpoint` over its input digest.

**PostgreSQL (D1 map, D3 procedure; rehearsed only on disposable servers):**

1. On the source, at the barrier:
   - `M pg-catalog --dsn-env <VAR> --database zeus --out source-catalog.json`;
   - `M pg-dump-db --container <src-pg> --user zeus --database zeus --path /dump/zeus.dump`
     (the whole database; no `-n` filter).
2. Transfer the archive and re-hash it.
3. The target stack must have the role `zeus`, the same image digest
   (`pgvector/pgvector@sha256:cf134a76…8e6f`, PG 17.11, vector 0.8.6), and no database named
   `zeus_aibox`.
4. On the target:

   ```
   M pg-restore-db --container zeus-aibox-postgres --user zeus --dsn-env ZEUS_AIBOX_PG_SERVER \
     --database zeus_aibox --path /dump/zeus.dump --archive-sha256 <sha> \
     --source-catalog source-catalog.json --schema-map d1-schema-map.json --receipt <backups>/pg-restore.json
   ```

   The D1 map renames `public→zeus_aibox_control`, `zeus_fleet_harness→zeus_aibox_harness` and
   `zeus_fleet_interface→zeus_aibox_interface`. Every other schema keeps its name. The map must be
   total.
   - The command refuses an occupied DB.
   - The same receipt replays read-only.
   - Use `--recover` only for this receipt's own empty, marked DB.
   - Never `--clean`, never a shared DB.
5. Verify:
   - `M pg-catalog` on the target, then `M pg-compare-catalog` → `pg_catalog` receipt;
   - `M pg-export` and `M pg-inventory` per schema, then `M pg-compare-schema` with NO delta,
     then `M pg-coverage` → `pg_comparison`.
6. Target DSNs:
   - the control store: `search_path=zeus_aibox_control,public` (so the vector type and operators
     now in `public` resolve);
   - lanes: the lane rule (`search_path=<lane>`), unchanged from the source.

**Registry (D2)**, after the exact comparison:

1. Initialize `/srv/zeus/runtime/lanes/{harness,interface}/isolated-worker/runs`. An uninitialized
   runtime is refused as uncertainty.
2. Have `/srv/zeus/repo` as an independent checkout of the source repository.
3. Run `zeus fleet migrate-host --file host-migration.json --journal
   /srv/zeus/runtime/control/fleet-service-journal.jsonl` with the Fleet paused. The request:
   - binds lanes `harness`/`interface` to `/srv/zeus/repo`, `/srv/zeus/runtime/lanes/<lane>` and
     `zeus_aibox_<lane>`;
   - carries `expected_config_sha256` (the source registry digest) and
     `source_repository_identity` (the root-commit digest of the source checkout).
4. The receipt is `registry_relocation`. Afterwards only `fleet_registry` changes, and one
   `fleet_host_migrations` row is added.

**Redis:**
- `M redis-copy …` → `redis_comparison`. Rehearsed 7.4.11 → 7.4.11 with appendonly yes and the
  source save policy.
- `M pel-owners` → `pel_owners`.

**Artifacts:** `M artifact-stage`, then `M artifact-verify` per root → `artifact_comparison`.

**Admission:** `zeus fleet status` shows the Fleet paused → `admission_paused`.

## 5. Activation (restored_paused → limited_active)

The order below is fixed. After step 1, any interruption or unknown effect is reconciled under R1.

1. `M intend-activation --file intent.json`. The intent carries the host id (`zeus_aibox_service.py
   host-id`), the release revision, image and profile.
2. `M activation-write --control-dir /srv/zeus/runtime/control …` writes `host-activation.json`
   atomically, derived from the intent. It is refused beside `host-fence.json`.
3. Start the monitors, check the read-only monitor, then start `zeus-aibox-fleet.service` through
   the `systemd_unit` target. The launcher re-checks the host id and revision.
4. Transition to `limited_active` with three receipts:
   - `host_activation` with subject = the intent id;
   - `service_consumption`, from the startup receipt, with subject `revision=<rev>`;
   - `canary_admission`, after the owner runs `zeus fleet resume` for the limited canary.

## 6. qualified

`acceptance_a` and `acceptance_b` are independent-review receipts for A1–A8 and B1–B5.
`qualified` is still only a recorded label. Live acceptance is the review itself.

## 7. Rollback

Run `M rollback-plan` first; it shows the mode and the steps.

- **Target fence:** `M fence-write --control-dir …`. The fence refuses every launcher role,
  monitors included. Stop the running units separately.
- **R0**, only while no activation intent exists: `M gate r0 --evidence …` → `rollback_gate`.
  Then resume the retained source.
- **R1**, once an intent exists, even if `limited_active` was never recorded:
  1. Stop and drain the target, and reconcile Docker residue by label (`zeus_aibox_service.py
     inspect`, `fleet reconcile-interrupted`).
  2. Reverse-copy the target's latest state into a NEW isolated Windows restore, using
     `reverse_maps`. For PG: `M pg-dump-db` on the target, then `M pg-restore-db --reverse`
     into a new source-side DB with the inverse map (rehearsed on disposable servers). The
     original names come back, and `public` holds the control ledger and the extension again.
  3. Checkpoint `reverse_pg_restore`, `reverse_redis_restore` and `reverse_artifact_copy`.
  4. `M gate r1` → `rollback_gate`.
  5. Starting the original Windows snapshot is forbidden.

## Not established by this delivery

- Live export, restore, cutover and rollback.
- Installed systemd lifecycle (SIGTERM, restart limit, SSH drop, cold boot), polkit or sudo rights.
- Container authentication, managed runtime consumption and model canaries.
- The D1–D3 procedure on real source data: rehearsed on disposable fixture servers only.
- Redis 7.4 on real data (rehearsed 7.4.11 → 7.4.11 on fixtures only).
- Adversarial concurrent path replacement during staging (see scripts/aibox_data RUNBOOK §3).
