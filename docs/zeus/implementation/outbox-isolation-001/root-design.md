# FA-006 revision 1: root / Claude resolution

The exact existing ticket is ZEUS-fb340b746179, revision 1, content hash
fe13dceb48b66cab295ef14143d4dcb51309927689de35a29cedea26e4f27a0b, GitHub #7.
No new issue or upstream analysis advisory was created. The guardian source finding is prior evidence;
`baseline.json` independently reproduces the corresponding Zeus failure with actual
isolated PostgreSQL and Redis against the recorded baseline commit.

Both reviewers identified the batch-wide transaction failure. Root's reproduction
observed the first valid message twice in Redis, neither send flag committed, and
the later valid message absent. Claude additionally identified discarded stream IDs,
unbounded scans and the shared database lock held across the whole batch.

Accepted: schema validation on the MessageBus port; separate malformed input and
transport failure handling; per-item transactions; durable attempt and delivery
receipts; explicit counters; persistent operator attention. RedisError is translated
at the adapter boundary to MessageDeliveryError. Unexpected errors are recorded and
then re-raised, never treated as successful delivery. Database failures propagate.

Root chose paginated keyed `entries(bucket, after, limit)` and a persisted cursor
instead of introducing a second pending index and delete API. This preserves every
existing producer and original malformed record, bounds PostgreSQL rows fetched per
flush, and eventually revisits corrected or earlier-ID records after wraparound.
It is not FIFO, and old sent/quarantined rows still consume page capacity. Content
hashes prevent repeated quarantine copies/events for an unchanged bad record.

An additional pre-publish transaction durably stores the attempt intent and message
hash before any Redis call. This matters when the first successful publish is followed
by a failed database commit: subsequent attempts cannot reuse the ID for different
content. The publish transaction rechecks the intent owner and exact source hash.
Concurrent superseded intents are retained. No lease system or exactly-once claim is
introduced. Redis success followed by lost ACK/commit can still produce duplicates;
consumers must deduplicate immutable message IDs. A producer must use a new ID for a
changed message once any intent was committed.

Post-publish ContractError is an unexpected error, not automatic quarantine: a custom
transport may have delivered before raising. Pre-publish schema and authorization
ContractError are permanent input faults and are quarantined. This deliberately
narrows Claude's proposal to classify every ContractError as permanent.

The unused `deliveries` CLI choice has no current producer. New `outbox_delivery`,
`outbox_attempts`, and `outbox_quarantine` buckets explicitly identify their purpose.
Legacy `sent: true` without new receipts remains a historical claim, not certified
delivery. Redis stream IDs prove enqueue acknowledgement, not consumption, E2E
completion or human acceptance. Monitor counters expose unresolved records without
publishing raw messages or arbitrary exception text.

The first live probe found the default Redis port unavailable before it could
exercise the defect. A dedicated Redis container with a random localhost port was
created, preserving the already-created isolated PostgreSQL schema; the source
reproduction then completed. Existing deployment containers/data were not modified.
