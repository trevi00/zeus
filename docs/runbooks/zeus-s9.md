# Zeus S9 alert runbook

One section per alert in `target/deploy/observability/prometheus/rules/zeus-s9.yml`; each `runbook` annotation points at its heading.
Every check is a read-only look at a series or a configuration. No Alertmanager and no notification routing exist yet (DESIGN-s9-X §4),
so these alerts are visible only in Prometheus. Every threshold is provisional (no production baseline, S9 fixtures).

## ZeusObservationRecordsRejected

**What fired:** Spool records were refused, found corrupt or found in conflict by a collection run within the last 15 minutes.

**First three read-only checks:**

1. `zeus_observation_records_total{result=~"refused|corrupt|conflict"}` and its `increase` over 15 minutes, to see which result moved.
2. `zeus:observation_records_problem_ratio:rate15m` against the `inserted` and `duplicate` results, to see the share of problem records.
3. `zeus_metrics_projected_observations_total` by category, to confirm the collector is still projecting.

**Do not conclude:** A rejection is not silent data loss: each refused, corrupt or conflicting record is counted and recorded in `observation_quarantine` with its reason, and it is not stored as an observation. A flat counter is not proof of a healthy collector, only that none was rejected.

**Owner:** observation

## ZeusMetricsLabelRejections

**What fired:** The metrics projection refused samples because a label value or attribute was outside its contract within the last hour.

**First three read-only checks:**

1. `zeus_metrics_label_rejections_total` by `metric`, to see which family refused samples.
2. `increase(zeus_metrics_label_rejections_total[1h])` against `zeus_metrics_projected_observations_total`, to size the refusal.
3. The observation rows of the named family (the stored events behind it), read-only, in the observation context.

**Do not conclude:** A refusal is not a lost observation: the stored row is intact and only its metric sample is withheld. It is not an attack signal by itself; a producer with a new enum value looks the same.

**Owner:** observation

## ZeusModelInvocationFailureRatioHigh

**What fired:** More than half of a provider's model invocations over the last hour did not end `accepted`, with at least four invocations in that hour.

**First three read-only checks:**

1. `zeus:model_invocation_failure_ratio:rate1h` by `provider`, and the `outcome` split of `zeus_model_invocation_duration_seconds_count`.
2. `zeus_model_invocation_exceptions_total` by `provider` and `provider_entered`, to separate failures before and after the provider was entered.
3. `zeus_model_invocation_duration_seconds_bucket`, to see whether the failures are fast or timeouts.

**Do not conclude:** A high ratio is not a provider outage by itself: `empty_answer`, `invalid_output`, `tool_only` and `interrupted` all count as not accepted. Fewer than four invocations never fire it, and no data is not a ratio of zero.

**Owner:** execution

## ZeusCgroupOOMKill

**What fired:** The kernel OOM-killed at least one process in a unit cgroup within the last 10 minutes.

**First three read-only checks:**

1. `zeus_cgroup_memory_events_total{event="oom_kill"}` by `unit`, with the `oom` and `max` events beside it.
2. `zeus:cgroup_memory_usage_ratio` for the unit, and `zeus_cgroup_memory_limited`, to see whether a limit exists.
3. `zeus_pressure_stall_ratio{resource="memory"}` for the unit scope, to see the stall before the kill.

**Do not conclude:** An unlimited unit (`zeus_cgroup_memory_limited` 0) has no usage ratio, and a missing ratio is not zero usage. The kill count is the cgroup's, which may include a process outside the Zeus workload.

**Owner:** host_os

## ZeusMemoryPressureHigh

**What fired:** Tasks stalled on memory for more than 20% of the last 60 seconds, sustained for 10 minutes.

**First three read-only checks:**

1. `zeus_pressure_stall_ratio{resource="memory",kind="some"}` by `scope` and `window`, to see whether the host or one unit stalls.
2. `zeus_pressure_waiting_seconds_total{resource="memory"}`, to see the cumulative stall.
3. `zeus_cgroup_memory_current_bytes` and `zeus_cgroup_memory_events_total` for the units in the same scope.

**Do not conclude:** A `some` stall is not an outage: tasks waited, they did not necessarily fail. Absent pressure series (see `zeus_resource_fact_available`) are not zero pressure.

**Owner:** host_os

## ZeusCPUThrottlingHigh

**What fired:** A unit cgroup was CPU-throttled for more than 25% of the time over 5 minutes, sustained for 15 minutes.

**First three read-only checks:**

1. `zeus:cgroup_cpu_throttled_ratio:rate5m` by `unit`.
2. `zeus_cgroup_cpu_throttled_periods_total` against `zeus_cgroup_cpu_usage_seconds_total` for the unit.
3. `zeus_pressure_stall_ratio{resource="cpu"}` for the unit scope.

**Do not conclude:** Throttling is not saturation of the host: the unit hit its own quota while the host may be idle. The ratio is throttled seconds per second, not a share of CPU capacity.

**Owner:** host_os

## ZeusFilesystemSpaceLow

**What fired:** A configured filesystem has had less than 10% of its bytes available to unprivileged users for 15 minutes.

**First three read-only checks:**

1. `zeus:filesystem_available_ratio` by `mount`.
2. `zeus_filesystem_available_bytes` and `zeus_filesystem_size_bytes` for the mount, to see the absolute size.
3. `zeus_filesystem_files_available` against `zeus_filesystem_files`, to rule inodes in or out.

**Do not conclude:** Low bytes available is not low inodes, and the reverse. A mount whose `statvfs` failed has no ratio at all (`zeus_resource_fact_available` is 0), which is not the same as a full or an empty disk.

**Owner:** host_os

## ZeusPidsLimitHit

**What fired:** A unit cgroup reached its process limit within the last 10 minutes.

**First three read-only checks:**

1. `zeus_cgroup_pids_limit_hits_total` by `unit`.
2. `zeus_cgroup_pids_current` against `zeus_cgroup_pids_max` for the unit.
3. `zeus_cgroup_cpu_throttled_periods_total` and the memory events of the same unit, to look for a runaway workload.

**Do not conclude:** A limit hit means a fork was refused, not that a process died. A unit without `zeus_cgroup_pids_max` is unlimited, and an absent series is not zero.

**Owner:** host_os

## ZeusResourceFactUnavailable

**What fired:** A resource fact has been unreadable for 30 minutes: its source file was missing, disabled or malformed, so its value series is absent.

**First three read-only checks:**

1. `zeus_resource_fact_available == 0` by `scope` and `fact`, to see which fact.
2. The value series of that fact (for example `zeus_pressure_stall_ratio` for `pressure_*`), which must be absent.
3. The collector's cgroup, `/proc` and mount configuration for the named scope, read-only, in the observation context.

**Do not conclude:** An unavailable fact is not zero: PSI switched off or a disabled controller reads as unavailable, not as no pressure. It says nothing about the workload, only about what could be observed.

**Owner:** observation
