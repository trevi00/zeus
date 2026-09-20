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
  // `portfolio` is additive in the same way (operating-portfolio-001 SPEC, wire contract
  // `sources.portfolio`): independent of the legacy four sources and of `fleet`, read only by the
  // 프로젝트 view. Its absence is an older collector, never an empty portfolio.
  sources: Partial<Record<SourceName, Envelope>> & { fleet?: Envelope; portfolio?: Envelope }
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
  /** Owner-recorded delivery: the record, `null` for no record (unknown), `false` for off-contract. */
  delivery: FleetDelivery | null | false
}
/**
 * Optional owner-recorded delivery of one fleet job (`urn:zeus:owner-delivery:1`, SPEC "Owner
 * delivery records"). This is what the OWNER stated after checking a preserved receipt; it is not
 * an independent GitHub or network verification, and it grants no authority of its own.
 * `merge_revision` and `deployed_revision` stay separate: a null deployed revision means the owner
 * recorded a merge and said nothing about a deployment. A job with no record at all is unknown,
 * never "not delivered", and delivery is never inferred from `accepted` or from another job.
 */
export const DELIVERY_SCHEMA = "urn:zeus:owner-delivery:1"
export type FleetDelivery = {
  authority: "owner_recorded"
  candidate_revision: string
  merge_revision: string
  deployed_revision: string | null
  recorded_at: string
  evidence_refs: string[]
  report_url: string | null
}

/**
 * Narrow the optional `delivery` object of one job view. Shared by the live 팀 작업 decoder and the
 * report capture so both say the same thing. Absent stays absent (`null` = unknown, not "none"),
 * and an off-contract record is `false`: it is reported as unreadable rather than shown as facts.
 */
export function readDelivery(value: unknown): FleetDelivery | null | false {
  if (value === undefined || value === null) return null
  if (typeof value !== "object") return false
  const record = value as Record<string, unknown>
  if (record.schema !== DELIVERY_SCHEMA || record.authority !== "owner_recorded") return false
  const revision = (field: unknown) => typeof field === "string" && /^[0-9a-f]{40}$/.test(field)
  if (!revision(record.candidate_revision) || !revision(record.merge_revision)) return false
  if (!(record.deployed_revision === null || revision(record.deployed_revision))) return false
  if (typeof record.recorded_at !== "string" || !record.recorded_at) return false
  if (!Array.isArray(record.evidence_refs) || !record.evidence_refs.every((ref) => typeof ref === "string")) return false
  if (!(record.report_url === null || typeof record.report_url === "string")) return false
  return {
    authority: "owner_recorded",
    candidate_revision: record.candidate_revision as string,
    merge_revision: record.merge_revision as string,
    deployed_revision: (record.deployed_revision as string | null) ?? null,
    recorded_at: record.recorded_at,
    evidence_refs: [...(record.evidence_refs as string[])],
    report_url: (record.report_url as string | null) ?? null,
  }
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

/**
 * Wire shape of `sources.portfolio.data` (operating-portfolio-001 SPEC, "Wire contract"). Bounded
 * read-only projection of owner-written goal definitions, owner-recorded criterion acceptances,
 * the fleet jobs explicitly bound to a criterion, and the durable repeated-failure investigation
 * candidates. What it is NOT, and what the view must never imply:
 * - a criterion `status` comes only from an explicit owner acceptance record; it is never derived
 *   from job status, and `accepted` is not "the whole source was absorbed";
 * - `counts` are computed over ALL rows while `jobs` (per project) and `investigations` are the
 *   latest 50 only, so the rendered rows are a labelled sample, never the denominator;
 * - an investigation row groups jobs by (status, reason_code) as a coarse triage family. It is a
 *   research candidate, not a confirmed root cause, incident or executed fix;
 * - `investigations[].job_ids` is itself capped at 50 while `count` covers all job IDs of the
 *   family, so the ID list must not be read as exhaustive;
 * - unknown or unreadable values stay unknown: they never become 0, empty or success.
 */
export const PORTFOLIO_SCHEMA = "urn:zeus:portfolio-status:1"
export type PortfolioCriterion = {
  id: string
  text: string
  /**
   * `pending` | `accepted` on the wire, kept as a raw string so a value this screen does not know
   * can be shown as unknown (lib/portfolio.ts `criterionInfo`) instead of silently counting as
   * either side. Only `accepted` means the owner recorded an acceptance.
   */
  status: string
  /** Opaque owner evidence references of the acceptance record; empty for a pending criterion. */
  evidence_refs: string[]
}
/**
 * The owner's immutable link from one preserved terminal failure to the job they recorded as its
 * successor, re-read against the rows that exist now (STATUS 2026-09-20). `state` is `linked` only
 * while that successor is still present, still `accepted` and still bound to the same criterion;
 * every other case is `unknown` with a `reason` and must never be drawn as resolved. Even `linked`
 * says exactly one thing: the owner linked an accepted follow-up with evidence. It is not "the
 * incident is fixed", not criterion acceptance, not a merge and not a deployment.
 */
export type PortfolioFollowUp = {
  successor_job_id: string
  /** Current fleet status of the successor, or `null` when the store no longer has that job. */
  successor_status: string | null
  /** `linked` | `unknown` on the wire, kept raw so an unfamiliar value stays unknown. */
  state: string
  /** `successor_missing` | `successor_not_accepted` | `binding_missing` | `target_mismatch`. */
  reason: string | null
  evidence_refs: string[]
  recorded_at: string | null
}
export type PortfolioJob = {
  id: string
  /** Criterion this job was explicitly bound to. `null` only if the collector omitted it (unknown). */
  criterion_id: string | null
  lane: string
  status: string
  reason_code: string | null
  updated_at: string
  /** `null` where the owner recorded no link for this job — absence of a link, not unknown. */
  follow_up: PortfolioFollowUp | null
}
/**
 * What one project's bound work is doing, counted over ALL rows before the latest-50 sample. The
 * six counts are disjoint and add up to `counts.jobs_total`; `mode` is the headline of the same
 * numbers and is an ACTIVITY label only — `idle` means no active job, never "criterion accepted".
 * A running project can still carry old unresolved failures, so both counts are always present.
 */
export type PortfolioActivity = {
  /** `not_started` | `unknown` | `running` | `queued` | `needs_attention` | `idle`, kept raw. */
  mode: string
  running: number
  queued: number
  /** Fleet `unknown` jobs and any status this contract does not define: uncertain, never idle. */
  unknown: number
  accepted: number
  /** Failed/rejected/exhausted with no link that currently reads `linked`. */
  unresolved_failed: number
  /** Failed/rejected/exhausted whose owner link currently reads `linked`. */
  historical_failed: number
}
export type PortfolioProject = {
  id: string
  title: string
  outcome: string
  source_ref: string
  criteria: PortfolioCriterion[]
  /** Latest 50 bound jobs, deterministic order from the collector. `counts.jobs_total` is all rows. */
  jobs: PortfolioJob[]
  counts: { criteria_total: number; criteria_accepted: number; jobs_total: number }
  /** `null` from a collector older than the activity contract: summary unavailable, never zeros. */
  activity: PortfolioActivity | null
  jobs_truncated: boolean
}
export type PortfolioInvestigation = {
  id: string
  /** Terminal job status of the family (`failed` / `rejected`), as recorded. */
  family_status: string
  reason_code: string
  /**
   * `research_required` | `researched` | `deferred` on the wire, kept raw for the same reason as a
   * criterion status: an unknown value is shown as unknown and never read as resolved.
   */
  state: string
  /** Distinct job IDs in the family over ALL rows; `job_ids` below is capped at 50. */
  count: number
  job_ids: string[]
  evidence_refs: string[]
  updated_at: string
}
export type PortfolioData = {
  schema: string
  /** Canonical digest of the owner's definition document. Not a completion assertion. */
  definition_sha256: string
  projects: PortfolioProject[]
  investigations: PortfolioInvestigation[]
  investigations_truncated: boolean
  /** Fleet jobs bound to no criterion, over ALL rows — not over the samples above. */
  unbound_jobs: number
  /** Terminal failures left out of triage for lack of a reason code, over ALL rows. */
  unclassified_failures: number
}

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

/** Same accepted freshness rules applied to the optional `sources.portfolio` envelope. */
export function portfolioFreshness(snapshot: Snapshot | null, now: number): Freshness {
  if (!snapshot) return { state: "unavailable", observed_at: null, age: null, reason: "응답 없음" }
  return envelopeFreshness(snapshot.sources?.portfolio, now)
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
