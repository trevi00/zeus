import { SOURCE_NAMES, freshness, type EventRow, type Observations, type Snapshot } from "./snapshot"
import type { Transport } from "./use-snapshot"

/**
 * One local report captured from one snapshot at one explicit time: every number comes from the
 * same `/api/status` body the screen rendered, with the sample limits and source times that bound
 * it. The object is pinned by the report view (built at view entry or on explicit regenerate) and
 * shared by the print view and the JSON download. No global health, SLO or acceptance claim is
 * derived here.
 *
 * v2: `observations` describes whether the observation source was usable at capture; when it was
 * not, `critical_events` and `critical_events_total` are `null` (unknown), never an empty list.
 * `transport` records the page-to-server state at capture so a report captured after a request
 * failure keeps that notice.
 */
export type Report = {
  schema: "zeus-observatory-report.v2"
  generated_at: string
  scope: Snapshot["scope"] | null
  collected_at: string | null
  transport: { state: Transport["state"]; detail: string | null; last_ok_at: string | null }
  sources: Record<string, { status: string; observed_at: string | null; freshness: string; error: string | null }>
  observations: { available: boolean; status: string; error: string | null; freshness: string }
  completeness: {
    sample: Observations["sample"] | null
    rows_truncated: boolean | null
    unknown: Observations["events"]["unknown"] | null
    local: Observations["local"] | null
    collection: Observations["collection"] | null
    note: string
  }
  counts: {
    events_total: number | null
    by_category: Record<string, number> | null
    by_severity: Record<string, number> | null
    alerts: Observations["alerts"] | null
    quarantine: Observations["quarantine"] | null
    terminations: Observations["terminations"] | null
  }
  critical_events: EventRow[] | null
  critical_events_total: number | null
  operations: Observations["operations"] | null
  next_actions: string[]
  evidence_ids: string[]
  authority: "informational_only"
}

export function nextActions(observations: Observations | null, unavailable: string[]): string[] {
  const actions: string[] = []
  if (unavailable.length) actions.push(`수집 실패 출처 확인: ${unavailable.join(", ")}`)
  if (!observations) return actions.length ? actions : ["관측 로그 출처가 없어 조치 판단 불가"]
  if (observations.terminations.pending > 0) actions.push(`미확정 종료 기록 ${observations.terminations.pending}건 운영자 조정 필요`)
  if (observations.alerts.recorded > 0) actions.push(`기록된 경보 ${observations.alerts.recorded}건 검토`)
  if (observations.quarantine.total > 0) actions.push(`격리 기록 ${observations.quarantine.total}건 원인 확인`)
  if (observations.local.status === "ok") {
    if (observations.local.pending_alerts > 0) actions.push(`로컬 대기 경보 ${observations.local.pending_alerts}건 · 수집기 재생 확인`)
    if (observations.local.unacknowledged_bytes > 0) actions.push(`스풀 미확인 ${observations.local.unacknowledged_bytes} 바이트 · 수집기 동작 확인`)
  } else {
    actions.push(`로컬 스풀 상태 확인 불가 (${observations.local.reason})`)
  }
  if (observations.sample.truncated) actions.push("샘플이 잘렸으므로 합계는 저장 전체가 아님 · 직접 조회 필요")
  const failed = Object.entries(observations.operations.by_status).filter(([status]) => ["failed", "rejected", "exhausted", "unknown"].includes(status))
  if (failed.length) actions.push(`운영 결과 확인: ${failed.map(([s, n]) => `${s} ${n}`).join(", ")}`)
  return actions.length ? actions : ["샘플 범위 안에서 즉시 조치 항목 없음 · 완전성은 보장되지 않음"]
}

export function buildReport(snapshot: Snapshot | null, transport: Transport, now: number): Report {
  const envelope = snapshot?.sources?.observations
  const observations = envelope && envelope.status === "ok" && envelope.data ? (envelope.data as Observations) : null
  const sources: Report["sources"] = {}
  const unavailable: string[] = []
  for (const name of SOURCE_NAMES) {
    const state = freshness(snapshot, name, now)
    const source = snapshot?.sources?.[name]
    sources[name] = { status: source?.status ?? "missing", observed_at: source?.observed_at ?? null,
      freshness: state.state, error: source?.error ?? null }
    if (state.state !== "fresh") unavailable.push(`${name} (${state.state})`)
  }
  const critical = observations ? observations.events.high_severity : null
  const evidence = new Set<string>()
  for (const row of critical ?? []) for (const ref of row.evidence_refs) evidence.add(ref)
  return {
    schema: "zeus-observatory-report.v2",
    generated_at: new Date(now).toISOString(),
    scope: snapshot?.scope ?? null,
    collected_at: snapshot?.collected_at ?? null,
    transport: { state: transport.state, detail: transport.detail || null, last_ok_at: transport.ok_at },
    sources,
    observations: { available: observations !== null, status: sources.observations.status,
      error: sources.observations.error, freshness: sources.observations.freshness },
    completeness: {
      sample: observations?.sample ?? null,
      rows_truncated: observations?.events.rows_truncated ?? null,
      unknown: observations?.events.unknown ?? null,
      local: observations?.local ?? null,
      collection: observations?.collection ?? null,
      note: "저장된 샘플 기준 · 모든 기대 이벤트가 기록되었다는 증거가 아님 · 전역 상태나 SLO 판정 아님",
    },
    counts: {
      events_total: observations?.events.total ?? null,
      by_category: observations?.events.by_category ?? null,
      by_severity: observations?.events.by_severity ?? null,
      alerts: observations?.alerts ?? null,
      quarantine: observations?.quarantine ?? null,
      terminations: observations?.terminations ?? null,
    },
    critical_events: critical,
    critical_events_total: observations?.events.high_severity_total ?? null,
    operations: observations?.operations ?? null,
    next_actions: nextActions(observations, unavailable),
    evidence_ids: [...evidence].sort(),
    authority: "informational_only",
  }
}

export function downloadJson(report: Report) {
  const blob = new Blob([JSON.stringify(report, null, 2)], { type: "application/json" })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement("a")
  anchor.href = url
  anchor.download = `zeus-observatory-${report.generated_at.replace(/[:.]/g, "-")}.json`
  anchor.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
