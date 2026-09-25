# aibox data transfer — staged transfer/restore runbook (offline tooling)

SSOT: `artifacts/aibox-migration-001/SPEC-retirement-update.md` §6–§8, §10, §11 (A2, A3, A8), gate C.
This tooling proves identities; it does **not** dump, restore, fence, pause admission, relocate the
registry or delete anything. Those transitions belong to the migration coordinator
(`migration_id` state machine) and the named operator. Invoke as
`uv run python scripts/aibox_data <command> …`; each command prints one JSON document
(exit 0 pass, 1 refused/mismatch/needs decision, 2 usage).

## 1. Source-export requirements (to be produced by Codex/coordinator, read-only)

The tooling consumes these documents. None of them may contain secrets, DSN passwords or tokens.

| # | Export | Exact contract | Tool |
|---|---|---|---|
| E1 | File roots | Every referenced root (union): FileArtifacts roots, raw logs, JUnit, observation spool, uncollected notifications, call ledger, handoff receipts, rollback evidence outside DB, `checklist-verification-artifacts`. One stable `ID=PATH` per root. | `inventory` |
| E2 | PG metadata per database | `{"schema":"zeus.aibox-pg-inventory/1","server_version_num":int,"extensions":{name:version},"schemas":{<schema>:{"tables":[…],"sequences":{name:last_value}}}}` from `SHOW server_version_num`, `pg_extension`, `information_schema.tables`, `pg_sequences` — Zeus control + every lane schema, never `public`. | `pg-inventory --meta` |
| E3 | PG rows per schema | JSONL, one `{"bucket","id","body"}` per row of `<schema>.documents`, `body` as parsed JSON (e.g. `SELECT bucket, id, body FROM <schema>.documents` via a read-only transaction `SET TRANSACTION READ ONLY, ISOLATION LEVEL REPEATABLE READ`). Row identity = sha256 of canonical JSON (sorted keys, `,`/`:` separators, UTF-8), so jsonb text layout never matters. | `pg-inventory --export SCHEMA=FILE` |
| E4 | Redis inventory | `{"schema":"zeus.aibox-redis-inventory/1","captured_at_ms":int (server TIME),"namespace_prefixes":[…],"keys":{key:{"type","expire_at_ms" (PEXPIRETIME, null if persistent),"dump_sha256" (sha256 of DUMP bytes, non-stream keys)}},"streams":{key:{"length","last_generated_id","entries_sha256","groups":{name:{"last_delivered_id","consumers":{name:pending_count},"pending":[{"id","consumer","deliveries"}]}}}}}`. Keys via `SCAN MATCH <prefix>:*` only; streams via `XINFO STREAM/GROUPS/CONSUMERS` and full `XPENDING key group - + <count>`; `entries_sha256` = `contracts.stream_entries_sha256(XRANGE - + result)` with ids/fields/values decoded as UTF-8 strings (field order is not part of identity). | `compare-redis` |
| E5 | PEL owners | `{"<stream>/<group>/<entry-id>": {"bucket","id"}}` mapping each pending entry to the PG record (operation/inbox) that owns its effect. | `pel-owners` |
| E6 | Mapping allowlist | `{"schema":"zeus.aibox-mapping-allowlist/1","fields":[{"bucket","path":[…]}],"immutable_buckets":[…],"prefix_rules":[{"source":"D:/workspaces/zeus/","target":"/srv/zeus/"}]}` — reviewed by Codex; audit/history buckets listed immutable. | `plan-bindings` |
| E7 | Gate evidence | JSON documents whose keys are listed in `gates.py` (R0, R1, C), each value taken from a receipt, not typed by hand. | `gate r0|r1|c` |

Unknowns stay unknown: the actual production PG image/version/extensions, Redis version (PEXPIRETIME
requires Redis ≥ 7.0), the full set of namespaces and roots are **not** established by this tooling.

## 2. Staged procedure

1. **Pre-seal inventory (source running, read-only):** `inventory --migration-id M --root …` to size
   the copy and surface `case_collisions`, `external_symlinks`, `special_files`, `unreadable`,
   `windows_incompatible` (exit 1 while any blocking finding exists). `verify-artifacts ROOT` per
   FileArtifacts root. `scan-paths ROOT` records Windows path references as evidence (no rewrite).
2. **Pre-copy staging (optional, restartable):** `stage` into `/srv/zeus/backups/M/staging/<root>`
   with a journal outside staging. Interruptions leave `<file>.part`; rerunning resumes after
   re-verifying the prefix. Same `migration_id` with another manifest digest is refused.
3. **Seal (after coordinator reports writer 0 / `source_fenced`):** rebuild the manifest; this is the
   sealed digest. Stage again into the same staging root with a **new journal file** (a journal is
   bound to one manifest digest) — already-verified files are skipped, changed files after the pre-seal
   copy are refused as `staged_conflict` and must be decided explicitly (never overwritten).
4. **Verify staged:** `verify-staged` must be `match: true` with no `partials`.
5. **PG/Redis:** coordinator produces E2–E5 for source (sealed) and for the paused target after
   restore; `plan-bindings` gives the delta receipt the coordinator's relocation use case applies;
   `compare-pg --delta RECEIPT` and `compare-redis` must match; `pel-owners` must be valid.
6. **Rollback evidence:** before any target write → `gate r0`; after the first target write →
   `gate r1` (old Windows snapshot reuse is refused). **Retirement:** `gate c` only after A/B.

## 3. What these checks cannot show

- They are offline comparisons of exported documents; a wrong or partial export produces a wrong
  inventory. Export completeness (every schema/namespace/root) is the exporter's responsibility.
- A staged file whose own name ends in `.part` is excluded from `verify-staged` comparison.
- No real PG/Redis, container, service lifecycle, network or cutover behaviour is exercised here.
