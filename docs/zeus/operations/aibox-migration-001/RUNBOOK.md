# aibox migration runbook (INV-HOST-MIGRATION-001)

SSOT: `SPEC-d116d26` (Codex, 2026-09-25). This runbook covers the reviewed-ready tools and the
staged order they are used in. It records no cutover. Every step below that touches the Windows
source, `/srv`, shared `~/infra`, networking or secrets is an **owner step**: run it only with the
named gate, and never as part of this first delivery.

`M` = `python -m codex_harness.adapters.host_migration` run from the reviewed checkout's venv.
DSNs are passed by environment-variable NAME only (`--dsn-env`, `--url-env`). Values never go in
argv or output.

## 0. What exists and what is new

| Need (SPEC §) | Reused | Added here |
|---|---|---|
| registry relocation (§6) | `Fleet.relocate` + `collect_relocation_proof` + copy manifest (`urn:zeus:fleet-relocation:1`) | none; the coordinator gates it as the `registry_relocation` step |
| host activation (§9–10) | HostDelivery descriptor/receipt/drain, `ProcessHostTarget` | `SystemdHostTarget` (`kind: systemd_unit`), `render-unit` |
| admission pause (§7) | `Fleet.pause`, HostDelivery `drain` | none |
| state machine + manifest (§6) | none | `HostMigrations` + `urn:zeus:host-migration-manifest:1` |
| PG/Redis/artifact copy + compare (§8) | lane search-path rule, store `records()` | `pg-inventory/-dump/-restore/-compare`, `redis-inventory/-copy`, `artifact-inventory/-copy/-compare` |

## 1. N: network (current LAN)

Re-read `ip -br addr`, `ip route` and `/sys/class/net/enp6s0/speed`. Also check SSH both ways,
outbound HTTPS to the model/GitHub endpoints, and NTP (`timedatectl`). Digest the receipt and
record it as `network_receipt`. The 2026-09-25 observation is in
`artifacts/aibox-migration-001/inventory-aibox.json`: 192.168.0.10/24, a 100 Mbps link, and
docker0 172.17/16 plus infra_default 172.18/16. No overlap with 192.168.0.0/24 was seen.

## 2. Plan

1. Fill the manifest from `SOURCE-EXPORT-REQUIREMENTS.json` (S1–S12) and the target facts.
2. `M validate --file manifest.json` checks the manifest. It refuses secrets, major/extension
   mismatches, namespace rewrites, non-bijective maps and `public`.
3. Create the dedicated migration schema. On the target stack, create `zeus_aibox_migration` and
   run `PostgresStore.migrate()` there. Then run
   `M plan --file manifest.json --dsn-env ZEUS_AIBOX_DSN --schema zeus_aibox_migration`.
4. Each state change is `M advance --file transition.json ...` with the gate digests from
   `GATES`. The identical file replays. A stale `from` refuses.

## 3. staged (target preparation; owner step, needs root)

- Layout: `M prepare-layout --root /srv/zeus` (dry run), then `--apply` under an owner-approved
  `sudo install -d -o trevi -g trevi /srv/zeus`. The dry run was run on 2026-09-25; `/srv/zeus`
  does not exist yet.
- Dedicated stack: compose project `zeus-aibox`, with its own volumes and network. It uses the
  source-matched images pinned by digest: pgvector pg17 (observed
  `pgvector/pgvector@sha256:cf134a76…8e6f`) and the source Redis 7.4 digest. DB/Redis are
  published to loopback or the Docker network only. Do not reuse `infra-postgres-1` or
  `infra-redis-1`.
- Service units: render them with `M render-unit --file unit.json`; see `examples/`. Install
  under `/etc/systemd/system` (owner, root). Register the HostDelivery target with
  `kind: systemd_unit` and `service: zeus-owner`. Starting a system unit as `trevi` needs a
  sudoers/polkit rule for exactly that unit. Otherwise use `user_scope`, which needs
  `loginctl enable-linger trevi`; linger is currently `no`.
- Staging restore rehearsal: run §5 against a staging DB and staging Redis with the dry-run export.
  Record the result as `staging_restore`.

## 4. draining → source_fenced → snapshot_sealed (owner step on Windows)

1. `zeus fleet pause` pauses admission. Drain HostDelivery. Settle unknown jobs with
   `fleet reconcile-interrupted`; unknown is never success. Nothing queued is deleted.
2. Stop and fence every `writers[]` entry with `disposition: stop_and_fence`. Leave
   `leave_untouched_not_zeus` entries alone. Record the observed writer count (processes, Docker
   labels, DB leases) as `writer_inventory`. Record a refused restart attempt under the marker as
   `restart_refusal`.
3. At the quiescent barrier, run `pg-inventory` per schema, `redis-inventory` per namespace and
   `artifact-inventory` per root. These give the `pg_inventory`, `redis_inventory` and
   `artifact_inventory` digests. PG and Redis share no snapshot transaction: quiescence is the
   consistency condition.

## 5. restore (snapshot_sealed → restored_paused)

Each step checks `completed_step` first and ends with `M checkpoint` over its input digest.
A resumed run skips completed steps. A different input refuses.

- PG, one schema at a time:
  1. `M pg-dump --container <src-pg> --database <db> --schema <s> --path /dump/<s>.dump` runs on
     the source.
  2. Transfer the dump and re-hash it.
  3. `M pg-restore --container zeus-aibox-postgres --database zeus_aibox --schema <s>
     --rename-to <mapped> --path /dump/<s>.dump` restores it. The command refuses when either
     schema already exists. After an interrupted run, the owner drops the staging schema, and the
     checkpoint shows which input was used.
  4. Create any extension the dump needs in the target DB first. `vector` lives in `public` and
     is not in a `-n` dump.
- Compare with `M pg-compare --source src.json --target dst.json --schema-map map.json
  [--allow-delta zeus_aibox_control fleet_registry]`. Only buckets changed by a reviewed binding
  (the relocation receipt) may be allowed deltas.
- Redis: `M redis-copy --source-url-env … --target-url-env … --namespace <ns>…` runs
  DUMP/RESTORE ABSTTL, never REPLACE. It re-inventories and compares: groups, last-delivered
  ids, PEL, absolute expiry. `expired_in_downtime` is reported, never revived.
- Artifacts: `M artifact-copy --source <root> --target /srv/zeus/artifacts/<id>
  --expected-tree-sha256 <sealed>` refuses if the source changed after the seal. It never
  overwrites. Then run `M artifact-compare`.
- Registry: run `zeus fleet relocate --file relocation.json --journal …` on the target with the
  runner stopped. Old paths are resolved through the relocation receipt; history is not
  rewritten.

## 6. limited_active → qualified

Start the single owner with admission paused through HostDelivery (`host_activation`). Check the
read-only monitor, then run the limited canary admission (`canary_admission`). A1–A8 become
`acceptance_a`; B1–B5 become `acceptance_b`. Each of those needs Codex's independent review.

## 7. Rollback

Run `M rollback-plan --migration-id aibox-migration-001 …`.

- R0 applies while `limited_active` was never entered. Fence the target, verify zero writers,
  then resume the retained source snapshot and runtime.
- R1 applies after that. The plan lists the exact inverse maps and the `reverse_*` steps.
  `restart_source_from_original_snapshot` is forbidden. The reverse copy uses the same tools with
  source and target swapped, into a NEW isolated Windows restore DB.
- Reverse Redis note: DUMP payloads from a newer Redis cannot be restored into an older one. The
  target therefore stays on the source major (7.4); this is enforced by the manifest.
- External effects (GitHub merges, deploys) are reconciled, never re-run.

## Unsupported / untested in this delivery

- Windows source inventory, real source data, and a real cutover or rollback were not attempted.
- `systemctl` on a real installed unit was not run. The target was exercised with a fake runner
  only. SSH-drop, SIGTERM, restart-limit, cold boot and disk-full behaviour of a real unit are
  untested.
- Docker container residue reconciliation by label for systemd-owned runs is not implemented. The
  existing Fleet `docker_state`/run-label checks remain the tool for it.
- Claude/Codex container authentication (A4) and live model canaries were not run.
- The Redis rehearsal used disposable `redis:8` servers, since no 7.4 image is on aibox. It is
  fixture evidence of the DUMP/RESTORE/PEL/ABSTTL mechanics, not of 7.4 compatibility.
- The coordinator runs on PostgreSQL through the existing advisory-lock store. Concurrent
  coordinators were not load-tested beyond that serialization.
