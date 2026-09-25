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
| Registry relocation | Fleet | `zeus fleet relocate` (reuses INV-FLEET-001) |
| Units, launcher, fence/activation checks, inspection | deploy/aibox | `zeus_aibox_service.py render/verify/launch/inspect/host-id` |
| Launcher files | coordinator-derived | `M activation-write` (from the intent), `M fence-write` |
| Unit control | HostDelivery `systemd_unit` target | `systemctl show/start/stop zeus-aibox-*.service`, restricted rights |

## 1. N and plan (owner)

1. Re-read the address, route and link. Check SSH both ways, outbound HTTPS and NTP. Record the
   result as an `observation` receipt for `network_receipt`.
2. Supply the missing exports and decisions in `SOURCE-EXPORT-REQUIREMENTS.json`. D1 is the
   schema classification and map, D2 the mapping allowlist, D3 the public restore procedure.
3. `M validate --file manifest.json`, then `M plan --file manifest.json --dsn-env ZEUS_AIBOX_DSN
   --schema zeus_aibox_migration`. The coordinator schema is created and migrated by the owner.

## 2. staged (owner, root)

1. Create `/srv/zeus` (`M prepare-layout --root /srv/zeus`, then `--apply`).
2. Stand up the dedicated `zeus-aibox` stack: pgvector pg17 and Redis 7.4, both pinned by digest,
   published to loopback or the Docker network only.
3. Build the release at its final path: `/srv/zeus/releases/<40-hex>/.venv` via
   `uv sync --frozen` AT that path. Never copy a venv. `current` points to it.
4. Render and verify the units (`deploy/aibox/zeus_aibox_service.py render` / `verify
   --systemd-analyze`). Install them, and grant a polkit or sudoers rule limited to
   `systemctl start|stop zeus-aibox-*.service` for the service UID. `reset-failed` stays a human
   action.
5. Rehearse the staging restore with a dry-run export (§5). Its `pg-coverage` receipt is
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

- **PG restore:**
  - Run `M pg-dump` and `M pg-restore` per non-public schema.
  - For `public`, follow D3's reviewed procedure; it is refused until one exists.
  - The restored registry must still be paused.
- **PG comparison:**
  1. Run `M pg-export --role target` and `M pg-inventory --role target`.
  2. Run `M pg-compare-schema --source-schema <s>` once per source schema.
  3. For `public` only, run `--delta registry-delta.json`. The delta comes from
     `scripts/aibox_data plan-bindings` over the `fleet_registry` rows. `zeus fleet relocate`
     applies the change on the paused target.
  4. `M pg-coverage --schema-map map.json --receipt …` gives `pg_comparison`.
- **Redis:**
  1. `M redis-copy …` gives `redis_comparison`.
  2. `M pel-owners` gives `pel_owners`.
- **Artifacts:** `M artifact-stage`, then `M artifact-verify` per root → `artifact_comparison`.
- **Relocation:** the `zeus fleet relocate` receipt → `registry_relocation`.
- **Admission:** `zeus fleet status` shows the Fleet paused → `admission_paused`.

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
     `reverse_maps`.
  3. Checkpoint `reverse_pg_restore`, `reverse_redis_restore` and `reverse_artifact_copy`.
  4. `M gate r1` → `rollback_gate`.
  5. Starting the original Windows snapshot is forbidden.

## Not established by this delivery

- Live export, restore, cutover and rollback.
- Installed systemd lifecycle (SIGTERM, restart limit, SSH drop, cold boot), polkit or sudo rights.
- Container authentication, managed runtime consumption and model canaries.
- The public restore procedure (D3), schema classification (D1) and mapping allowlist (D2).
- The Redis 7.4 compatibility of DUMP payloads (rehearsed on redis:8 only).
- Adversarial concurrent path replacement during staging (see scripts/aibox_data RUNBOOK §3).
