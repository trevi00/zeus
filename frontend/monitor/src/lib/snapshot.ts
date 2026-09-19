// Snapshot contract of /api/status (harness-monitor.v1 + observatory-001 `observations` envelope).
// Freshness rules are the accepted ones: 20s window, invalid/future(>5s) timestamps never fresh.

import type { Accounting } from "./accounting"

export const FRESH_MS = 20_000
export const FUTURE_TOLERANCE_MS = 5_000
export const REQUEST_TIMEOUT_MS = 5_000
export const POLL_MS = 5_000
export const SOURCE_NAMES = ["database", "observations", "docker", "redis"] as const
export type SourceName = (typeof SOURCE_NAMES)[number]

export type Envelope = {
  status?: string
  observed_at?: string | null
  error?: string | null
  data?: unknown
}

export type Snapshot = {
  schema?: string
  collected_at?: string
  scope?: { label?: string; docker?: string; containers?: string[] | null }
  // `fleet` is additive (INV-FLEET-001, fleet-001 SPEC). It is not in SOURCE_NAMES: older
  // snapshots without it stay valid, the source strip, retained map, header warnings and the pinned
  // report keep their fixed four-source contract, and only the 팀 작업 view reads it.
  sources: Partial<Record<SourceName, Envelope>> & { fleet?: Envelope }
}

// Wire shape of `sources.fleet.data` (fleet-001 SPEC "Monitoring wire contract"). Projection only:
// no manifests, objectives, repository paths, schema names, DSNs or raw errors are expected here.
export const FLEET_SCHEMA = "urn:zeus:fleet-status:1"
export type FleetLane = { id: string; team: string; active_job: string | null }
export type FleetJob = {
  id: string
  lane: string
  team: string
  status: string
  reason_code: string | null
  operation_id: string
  goal: { path: string; criterion: string }
  dependencies: string[]
  calls: { reserved: number | null; settled: number | null }
  created_at: string
  updated_at: string
}
export type FleetUnregistered = { schema: string; registered: false; lanes: []; jobs: [] }
export type FleetRegistered = {
  schema: string
  registered: true
  id: string
  paused: boolean
  max_parallel: number
  /** The two wire numbers only. What they mean in this capture is `accounting`, never assumed here. */
  budget: { per_host: number; total: number }
  /**
   * Shared reading of the wire fields `accounting_mode` and `budget.mode` (lib/accounting.ts).
   * Both decoders (this view lane and the pinned report) fill it from the same function, so the
   * live screen and the captured report never disagree about the mode.
   */
  accounting: Accounting
  lanes: FleetLane[]
  jobs: FleetJob[]
  truncated: boolean
}
export type FleetData = FleetUnregistered | FleetRegistered

export type EventRow = {
  event_id: string | null
  event_type: string | null
  category: string
  severity: string
  outcome: string | null
  reason_code: string | null
  observed_at: string | null
  observed_at_valid: boolean
  occurred_at: string | null
  collected_at: string | null
  record_kind: string
  audit_confirmed: boolean | null
  correlation_id: string | null
  execution: {
    kind: string | null
    role: string | null
    task_id: string | null
    bucket: string | null
    attempt: number | null
    generation: number | null
    process_run_id: string | null
    invocation_id: string | null
  }
  component: string | null
  evidence_refs: string[]
  evidence_refs_total: number
}

export type OperationRow = {
  id: string | null
  status: string | null
  reason_code: string | null
  task_id: string | null
  decision_id: string | null
  lead_accepted: boolean | null
  criterion: string | null
  correlation_id: string | null
}

export type HealthRow = {
  process_run_id: string | null
  component: string | null
  role: string | null
  updated_at: string | null
  sink: string | null
  unreadable: boolean
  dropped: Record<string, number | null | undefined>
  pending_alerts: number
  unacknowledged_bytes: number | null
  limit_bytes: number | null
  last_defect: string | null
}

export type LocalFacts =
  | { status: "unavailable"; reason: string }
  | {
      status: "ok"
      segments: number
      unacknowledged_bytes: number
      health: HealthRow[]
      health_total: number
      pending_alert_files: Record<string, number>
      pending_alerts: number
      pending_terminations: number
      unreadable_terminations: number
    }

export type Observations = {
  schema: string
  observed_at: string
  authority: string
  labels: Record<string, string>
  sample: {
    limit_per_bucket: number
    selection: string
    truncated: boolean
    buckets: Record<string, { scanned: number; limit: number; truncated: boolean }>
    note: string
  }
  events: {
    total: number
    record_kinds: Record<string, number>
    by_category: Record<string, number>
    by_severity: Record<string, number>
    by_outcome: Record<string, number>
    unknown: { severity: number; category: number; observed_at: number }
    rows: EventRow[]
    rows_limit: number
    rows_truncated: boolean
    high_severity: EventRow[]
    high_severity_total: number
  }
  collection: {
    last_at: string | null
    lag_seconds: number | null
    last: Record<string, unknown> | null
    receipts: number
    receipts_with_time: number
  }
  alerts: { recorded: number; by_status: Record<string, number> }
  quarantine: { total: number; by_reason: Record<string, number> }
  terminations: { by_status: Record<string, number>; pending: number }
  operations: { total: number; by_status: Record<string, number>; rows: OperationRow[]; rows_truncated: boolean }
  local: LocalFacts
}

export type DatabaseFacts = {
  operating_status?: string
  task_counts?: Record<string, number>
  agents?: Array<{ id: string; role?: string; execution_state?: string; work?: string[]; queued?: number; expired_leases?: number }>
  tasks?: Array<{ id: string; agent?: string | null; status: string; phase?: string | null; objective?: string; attempt?: number; created_at?: string | null }>
  health?: { status?: string | null; checked_at?: string | null }
  active?: { release_id?: string | null; revision?: string | null; at?: string | null }
  initiatives?: Array<{ id: string; title: string; status: string; focus: string; reason: string; last_activity: string }>
  measurements?: Array<{ metric_id: string; value: unknown; status: string; observed_at: string }>
  policy?: { max_active_executions?: number }
}

export type DockerRow = { service?: string; name?: string; state?: string; image?: string; cpu?: string | null; memory?: string | null }
export type RedisRow = { agent: string; entries?: number; pending?: number; lag?: number | null }

export type FreshState = "fresh" | "stale" | "unavailable" | "invalid"
export type Freshness = { state: FreshState; observed_at: string | null; age: number | null; reason: string }

/** Date.parse of ISO strings with more than three fractional digits is implementation-defined. */
export function parseTime(value: unknown): number {
  if (typeof value !== "string" || !value) return NaN
  return Date.parse(value.replace(/(\.\d{3})\d+/, "$1"))
}

export function freshness(snapshot: Snapshot | null, name: SourceName, now: number): Freshness {
  if (!snapshot) return { state: "unavailable", observed_at: null, age: null, reason: "응답 없음" }
  return envelopeFreshness(snapshot.sources?.[name], now)
}

/** Same accepted freshness rules applied to the optional `sources.fleet` envelope. */
export function fleetFreshness(snapshot: Snapshot | null, now: number): Freshness {
  if (!snapshot) return { state: "unavailable", observed_at: null, age: null, reason: "응답 없음" }
  return envelopeFreshness(snapshot.sources?.fleet, now)
}

function envelopeFreshness(source: Envelope | undefined, now: number): Freshness {
  if (!source || typeof source !== "object") {
    return { state: "unavailable", observed_at: null, age: null, reason: "출처 기록 없음" }
  }
  if (source.status !== "ok") {
    return { state: "unavailable", observed_at: source.observed_at ?? null, age: null,
      reason: source.error ? `수집 실패 · ${source.error}` : "수집 실패" }
  }
  const at = parseTime(source.observed_at)
  if (!Number.isFinite(at)) {
    return { state: "invalid", observed_at: source.observed_at ?? null, age: null, reason: "관측 시각 없음 또는 해석 불가" }
  }
  const age = now - at
  if (age < -FUTURE_TOLERANCE_MS) {
    return { state: "invalid", observed_at: source.observed_at ?? null, age: null, reason: "관측 시각이 미래" }
  }
  const clamped = Math.max(0, age)
  return { state: clamped < FRESH_MS ? "fresh" : "stale", observed_at: source.observed_at ?? null, age: clamped,
    reason: clamped < FRESH_MS ? "" : "정보가 오래됨" }
}

export function formatTime(value: unknown): string {
  const at = parseTime(value)
  if (Number.isFinite(at)) return new Date(at).toLocaleString("ko-KR", { hour12: false })
  return value == null || value === "" ? "관측 없음" : "시각 해석 불가"
}

export function formatSeconds(ms: number | null): string {
  return ms == null ? "알 수 없음" : `${Math.floor(ms / 1000)}초`
}

export function formatNumber(value: unknown): string {
  return typeof value === "number" && Number.isFinite(value) ? value.toLocaleString("ko-KR") : "—"
}

export const SEVERITY_LABELS: Record<string, string> = {
  critical: "치명", error: "오류", warning: "경고", info: "정보", debug: "디버그", unknown: "알 수 없음",
}
export const CATEGORY_LABELS: Record<string, string> = {
  operations: "운영", development: "개발", general: "일반·디버깅", unknown: "알 수 없음",
}
export const SEVERITY_ORDER = ["critical", "error", "warning", "info", "debug", "unknown"]
export const CATEGORY_ORDER = ["operations", "development", "general", "unknown"]
export const STATE_LABELS: Record<FreshState, string> = {
  fresh: "최신", stale: "오래됨", unavailable: "수집 실패", invalid: "시각 무효",
}
export const SOURCE_LABELS: Record<SourceName, string> = {
  database: "운영 기록 (PostgreSQL)", observations: "관측 로그", docker: "컨테이너", redis: "메시지 버스",
}
