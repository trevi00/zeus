# Zeus S9 alert runbook, queue, Redis stream and feature-use rules

One section per alert in `target/deploy/observability/prometheus/rules/zeus-s9b.yml`; each `runbook` annotation points at its heading.
Every check is a read-only look at a series or a configuration. No Alertmanager and no notification routing exist yet (DESIGN-s9-X §4),
so these alerts are visible only in Prometheus. Every threshold is provisional (no production baseline, S9 fixtures).
The feature-use recording rules have no alert: `zeus:feature_unused_instrumented_candidate:7d` is a candidate list only, and zero use is never a removal authority.

## ZeusOutboxOldestWaitingHigh

**What fired:** The oldest unsent outbox row has waited more than ten minutes for at least ten minutes.

**First three read-only checks:**

1. `zeus_queue_oldest_age_seconds{queue="outbox"}` and `zeus_queue_depth{queue="outbox"}`, to see whether the wait comes with a growing backlog.
2. `zeus_queue_unparseable_rows{queue="outbox"}` and `zeus_queue_scanned_rows{queue="outbox"}`, to see what the bounded scan excluded.
3. `zeus_queue_facts_available{queue="outbox"}`, which must be 1 for the age to mean anything.

**Do not conclude:** The age is the oldest waiting row with a parseable time, not the average wait, and it is not proof of lost messages: a waiting row is still stored. A relay that is merely slow, or a single stuck row, gives the same signal.

**Owner:** coordination

## ZeusTaskOldestWaitingHigh

**What fired:** The oldest queued or retrying task has waited more than an hour for at least 15 minutes.

**First three read-only checks:**

1. `zeus_queue_oldest_age_seconds{queue="tasks"}` and `zeus_queue_depth{queue="tasks"}` by `state`, to separate waiting from in-progress rows.
2. `zeus_queue_unparseable_rows{queue="tasks"}`, to see rows excluded from the age.
3. `zeus_queue_facts_available{queue="tasks"}`, which must be 1 for the age to mean anything.

**Do not conclude:** A long wait is not a failed task and not a dead worker: a task in `retry` is waiting by design, and the age counts from creation. A running task is not part of the age.

**Owner:** coordination

## ZeusQueueFactsUnavailable

**What fired:** A queue has been read incompletely (a truncated scan or a failed read) for 30 minutes, so its depth and oldest age are absent.

**First three read-only checks:**

1. `zeus_queue_facts_available == 0` by `queue`, to see which queue.
2. `zeus_queue_scanned_rows` of that queue, to see whether the bounded scan was cut off.
3. The state source of that queue (its file or table), read-only, in the observation context.

**Do not conclude:** An unavailable queue is not an empty queue: truncated or unreadable is unavailable, never zero, and the depth and age series are absent rather than 0. It says nothing about the workload.

**Owner:** observation

## ZeusRedisPendingStale

**What fired:** An agent's workers group holds a pending entry that has been idle for more than five minutes since its last delivery, for at least ten minutes.

**First three read-only checks:**

1. `zeus_redis_pending_oldest_idle_seconds` by `agent`, together with `zeus_redis_stream_pending` for the same agent.
2. `zeus_redis_stream_lag` and `zeus_redis_stream_entries` of the agent, to see whether new work is still arriving.
3. `zeus_redis_facts_available{scope="<agent>"}`, which must be 1.

**Do not conclude:** A stale idle is not proof that the consumer is dead: the idle time is since last delivery (the XAUTOCLAIM idle semantics), so a long-running task holds an entry idle without any fault. It is the longest idle over a bounded sample of the first pending entries, not over all of them.

**Owner:** coordination

## ZeusRedisDeadLettersGrowing

**What fired:** The dead-letter stream gained entries over the last hour, and it has done so for at least five minutes.

**First three read-only checks:**

1. `zeus_redis_dead_letter_entries` over the last day, to see the growth and its start.
2. `zeus_redis_stream_pending` and `zeus_redis_pending_oldest_idle_seconds` by `agent`, to see which agent is struggling.
3. The dead-letter entries themselves, read-only (XRANGE), for the reason and the source agent.

**Do not conclude:** Growth is not data loss: a dead-lettered entry is kept in its stream with its reason and can be inspected. A delta is not a rate of loss either, and a stream that shrinks (trim or manual removal) resolves the alert without any entry having been handled.

**Owner:** coordination

## ZeusRedisMemoryHigh

**What fired:** Redis has used more than 80 percent of its configured maxmemory for at least ten minutes.

**First three read-only checks:**

1. `zeus:redis_memory_usage_ratio` with `zeus_redis_memory_used_bytes` and `zeus_redis_memory_max_bytes`.
2. `zeus_redis_stream_entries` by `agent` and `zeus_redis_dead_letter_entries`, to see which stream holds the memory.
3. `zeus_redis_stream_lag` and `zeus_redis_stream_pending` by `agent`, to see whether consumers are falling behind.

**Do not conclude:** High usage is not an eviction or an outage: it is a ratio of used memory to maxmemory. With maxmemory 0 (unlimited) the max series is absent and there is no ratio, which is not 0 percent.

**Owner:** storage

## ZeusRedisFactsUnavailable

**What fired:** The Redis reads of a scope (an agent or the server) failed for 15 minutes, so its stream and memory facts are absent.

**First three read-only checks:**

1. `zeus_redis_facts_available == 0` by `scope`, to see which scope.
2. The value series of that scope (for example `zeus_redis_stream_pending`), which must be absent.
3. The collector's Redis URL and roster configuration, read-only, in the observation context.

**Do not conclude:** An unavailable Redis is not an idle or empty Redis: a failed read emits no values, so absent pending, lag and memory series are not zero. It says only that the facts could not be observed.

**Owner:** observation
