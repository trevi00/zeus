from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class RuntimePolicy:
    context_checkpoint_fraction: float = 0.70
    idle_seconds: int = 3600
    max_active_executions: int = 2
    max_attempts: int = 3
    max_reworks: int = 2
    task_seconds: int = 900
    decision_seconds: int = 300
    task_lease_seconds: int = 600
    research_interval_hours: int = 6
    recurrence_threshold: int = 2
    artifact_retention_days: int = 7
    stream_retention_entries: int = 1000
    source_execution_seconds: int = 120
    source_request_seconds: int = 300
    source_memory_mb: int = 512
    source_cpus: int = 1
    source_pids: int = 128
    source_scratch_mb: int = 128
    source_output_bytes: int = 65536
    source_read_bytes: int = 24000
    source_read_lines: int = 120
    release_check_seconds: int = 900
    release_retry_seconds: int = 30
    release_max_attempts: int = 3
    release_lease_seconds: int = 1200
    health_failure_threshold: int = 3
    observation_spool_bytes: int = 32 * 1024 * 1024
    observation_segment_bytes: int = 4 * 1024 * 1024
    observation_alert_window_seconds: int = 300
    observation_collect_batch: int = 1000

    def snapshot(self) -> dict:
        return asdict(self)


POLICY = RuntimePolicy()
