## Scope reviewed
`docs/tickets/FA-006.json` rev1 (`fe13dce…`, issue 7, `synced_revision: 1`), guardian `review.md` F06/F09/F13 and the notifier row of the 흡수 제안 table (`review.md:102-103`), plus `application/service.py:207-218`, `adapters/bus.py`, `adapters/store.py`, `application/monitoring.py`, `adapters/monitoring.py:25-31`, `supervisor.py:109-128`. No execution, no writes, no issues.

## Root cause: agree, with a wider blast radius
`flush_outbox` wraps every publish in one transaction (`service.py:211`). Any raise inside the loop aborts it, so `sent=True` rows committed nowhere while `xadd` already landed in Redis. `MemoryStore.transaction` (`store.py:35-40`) has the identical all-or-nothing semantics, so a memory-backed test reproduces it without PG.

Malformed rows are not the only trigger: `item["sent"]` and `item["message"]["message_id"]` raise `KeyError`/`TypeError` on any non-conforming row, `validate_message` raises `ContractError` from *inside* `publish` (`bus.py:73-75`), and a Redis timeout (`socket_timeout=10`) raises there too. All three are indistinguishable to the caller today — that is the design defect, not just the shape of one row.

Additional defects I found independently:
- `PostgresStore.transaction` takes advisory lock 734219 for **every** transaction (`store.py:83-84`). The whole-batch flush holds the single control-plane writer lock across N network round-trips. Per-item transactions are a latency win, not just a correctness one.
- `sent: True` is not a receipt. `xadd`'s returned stream ID is discarded, so there is no entry_id, attempt count, or timestamp anywhere.
- `scan("outbox")` is unbounded and never prunes; sent rows are rescanned forever.
- `scan` orders by `id` (uuid) — no FIFO. The fix must not claim ordering.

## On the proposed design
**Agree:** stdlib application use-case; one serialized transaction per item; keep the existing bootstrap lock, no lease system; preserve the malformed source; hash-keyed immutable quarantine copy with receipt/status in a separate record; transport failure → stay pending + attempt receipt + continue; explicit at-least-once (consumer dedup already exists via the `inbox` record, `service.py:93`); corrected content retried under a new hash.

**Disagree / gaps:**
1. `MessageBus` (`ports.py:17-18`) has no `validate`. It must be added to the port and to `RedisBus`, or the classification is impossible. Note `publish` will still re-validate internally, so `ContractError` from `publish` must also be treated as permanent, not retried.
2. "Keyed per-bucket entries" needs a concrete mechanism: `Transaction` exposes only get/put/scan/records. The minimal form is a `outbox_pending` index bucket keyed by message_id; `scan` then returns only pending work with no new SQL.
3. That requires **delete**, which `Transaction` lacks. Without it a quarantined row stays in the pending set and is re-quarantined every tick. Either add `delete` to the protocol and both adapters, or write an explicit tombstone value the scan filters. Pick one; this is the only real protocol change the ticket implies.
4. Classify by exception type, not by position: `ContractError`, authorize failures, and row-shape `KeyError`/`TypeError` → quarantine; `redis.exceptions.RedisError` → pending+attempt. Anything else must propagate **after** the current item's transaction has settled, so earlier commits stand. No `except Exception`.
5. Receipt durability: write the receipt (entry_id, published_at, attempts) in the same transaction that flips state, after publish returns. The crash window between `xadd` and commit is irreducible without consumer dedup — state it, don't engineer around it.
6. Counts: return a dict (`published`/`quarantined`/`retried`/`skipped`), not an int. `cli.py:413` emits `{"published": ...}` and `supervisor.py:128` discards the result; both need updating so retries and quarantines aren't invisible.
7. Monitoring: `adapters/monitoring.py:27` doesn't scan outbox or quarantine at all, so nothing is exposed yet. Add the buckets there and a `notification` block in `Monitoring.snapshot`; degrade on an explicit threshold, and keep it separate from `operating_status`, which is health-age-derived only.
8. Check whether the existing `deliveries` bucket (`cli.py:196`) is the right home for receipts before adding a bucket.

Design is sound and minimal; items 1–3 are prerequisites, not polish. Reproduction and Windows/Linux verification remain root's work — unverified here.