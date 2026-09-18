import { SOURCE_LABELS, SOURCE_NAMES, STATE_LABELS, formatNumber, formatTime, freshness, type EventRow, type Observations, type Snapshot } from "./snapshot"
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
 *
 * v3: `explanation` is a plain-language Korean reading of the same pinned numbers (summary,
 * conceptual record -> collection -> report flow, operation status distribution, reading guide,
 * caveats, provenance). It is computed here at capture from the fields above only: no timer,
 * fetch, model call or storage is involved, and the view renders it without further derivation.
 */
export type ExplanationFact = { label: string; value: string; known: boolean }
export type ExplanationStep = { key: string; title: string; description: string; facts: ExplanationFact[] }
export type ExplanationBar = { status: string; label: string; count: number; known_status: boolean }

export type Explanation = {
  title: "한눈에 이해하기"
  summary: string[]
  flow: { label: "구조 설명 · 개별 실행을 추적한 증거가 아님"; note: string; steps: ExplanationStep[] }
  operations: {
    label: string
    /** unknown: observations source unusable (counts are null); empty: source ok, zero rows; observed: rows present. */
    state: "unknown" | "empty" | "observed"
    denominator: number | null
    scope: string
    bars: ExplanationBar[]
    note: string
  }
  guide: string[]
  caveats: string[]
  provenance: {
    derived_from: "pinned_report"
    generated_at: string
    collected_at: string | null
    observations_observed_at: string | null
    observations_status: string
    transport_state: Transport["state"]
    computed_by: "frontend buildReport at capture · no model call · no live data"
    reference: { name: string; url: string; commit: string; role: string }
  }
}

export type Report = {
  schema: "zeus-observatory-report.v3"
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
  explanation: Explanation
  next_actions: string[]
  evidence_ids: string[]
  authority: "informational_only"
}

/** Korean labels for the operation statuses written by application/operation.py; anything else stays raw. */
export const OPERATION_STATUS_LABELS: Record<string, string> = {
  accepted: "수락됨", failed: "실패", rejected: "거부됨", exhausted: "예산 소진", running: "실행 중", unknown: "알 수 없음",
}
const OPERATION_STATUS_ORDER = ["accepted", "failed", "rejected", "exhausted", "running", "unknown"]

const ELI5_REFERENCE = {
  name: "DreambigOu/ELI5",
  url: "https://github.com/DreambigOu/ELI5",
  commit: "a766623b062331fdde53467001379b4ddf3acc2f",
  role: "설명 방식 참고(목적 먼저 · 친숙한 말 · 단계별 상세) · 데이터 출처·검증 도구·보증 아님 · 숫자와 불확실성은 그대로 유지",
}

const READING_GUIDE: string[] = [
  "심각도(치명·오류·경고·정보·디버그)와 분류(운영·개발·일반·디버깅)는 서로 다른 축입니다. '디버그'는 심각도이고 '일반·디버깅'은 저장된 분류 라벨입니다.",
  "우선순위는 심각도가 먼저입니다. 개발 분류의 오류 하나가 운영 분류의 정보 이벤트보다 위에 옵니다.",
  "0건은 '샘플 안에서 보이지 않음'이지 '모든 기대 이벤트가 기록됨'이 아닙니다. 빈 큐나 빈 스풀도 수집 완전성을 증명하지 않습니다.",
  "'확인 불가'는 값을 읽지 못한 상태이고, '0' 또는 '비어 있음'은 읽었더니 없었다는 뜻입니다. 이 보고서는 두 상태를 항상 구분해 적습니다.",
  "작업(task)이 끝났다는 것과 운영(operation)이 수락되었다는 것은 다릅니다. 운영 결과는 operations 버킷에 저장된 상태 값 그대로 셉니다.",
  "설명 방식은 DreambigOu/ELI5 저장소의 원칙(목적 먼저, 친숙한 말, 단계별 상세)을 참고했습니다. 그 저장소는 데이터 출처나 검증 도구가 아닙니다.",
]

export function operationBars(operations: Observations["operations"] | null): ExplanationBar[] {
  if (!operations) return []
  const bars: ExplanationBar[] = OPERATION_STATUS_ORDER.map((status) => ({
    status, label: OPERATION_STATUS_LABELS[status], count: operations.by_status[status] ?? 0, known_status: true,
  }))
  const extra = Object.keys(operations.by_status).filter((status) => !Object.hasOwn(OPERATION_STATUS_LABELS, status)).sort()
  for (const status of extra) {
    bars.push({ status, label: `${status} (정의되지 않은 상태)`, count: operations.by_status[status], known_status: false })
  }
  return bars
}

function fact(label: string, value: string | null, known = value != null): ExplanationFact {
  return { label, value: value ?? "확인 불가", known }
}

export function buildExplanation(
  snapshot: Snapshot | null,
  observations: Observations | null,
  sources: Report["sources"],
  transport: Report["transport"],
  generatedAt: string,
): Explanation {
  const collectedAt = snapshot?.collected_at ?? null
  const obsSource = sources.observations
  const obsStateLabel = STATE_LABELS[obsSource.freshness as keyof typeof STATE_LABELS] ?? obsSource.freshness
  const truncatedBuckets = observations
    ? Object.entries(observations.sample.buckets).filter(([, m]) => m.truncated).map(([b]) => b)
    : []

  // 1. Summary: only what the pinned numbers say, in the order an operator needs it.
  const summary: string[] = [
    `이 설명은 ${formatTime(generatedAt)}에 고정한 보고서 하나에서 계산했습니다. 그 뒤에 받은 데이터는 반영되지 않습니다.`,
  ]
  if (transport.state !== "ok") {
    summary.push(`캡처 시점 연결 상태가 '${transport.state}'였습니다. 아래 숫자는 마지막으로 받은 이전 응답이며 지금 상태가 아닙니다.`)
  }
  if (collectedAt == null) {
    summary.push("정상 응답을 받은 적이 없어 설명할 데이터가 없습니다. 모든 건수는 0이 아니라 알 수 없음입니다.")
  } else if (!observations) {
    summary.push(`관측 로그 출처를 읽지 못했습니다(상태 ${obsSource.status}${obsSource.error ? ` · ${obsSource.error}` : ""}). 이벤트·경보·운영 결과 건수는 0이 아니라 알 수 없음입니다.`)
  } else {
    const high = observations.events.high_severity_total
    summary.push(
      high === 0
        ? `저장된 샘플에서 이벤트 ${formatNumber(observations.events.total)}건을 읽었고, 그중 치명·오류는 0건입니다(샘플 안에서 없음 · 기록 완전성과는 별개).`
        : `저장된 샘플에서 이벤트 ${formatNumber(observations.events.total)}건을 읽었고, 그중 치명·오류는 ${formatNumber(high)}건입니다.`,
    )
    const bars = operationBars(observations.operations).filter((bar) => bar.count > 0)
    summary.push(
      observations.operations.total === 0
        ? "샘플 안에 운영(operation) 기록이 없습니다(비어 있음 · 알 수 없음 아님)."
        : `운영 결과 ${formatNumber(observations.operations.total)}건: ${bars.map((bar) => `${bar.label} ${formatNumber(bar.count)}`).join(" · ")}. '수락됨'만 검토가 확인한 운영 결과이며, 작업 완료와는 다른 값입니다.`,
    )
    if (obsSource.freshness !== "fresh") {
      summary.push(`관측 로그 출처는 캡처 시점에 '${obsStateLabel}' 상태였으므로 위 숫자는 그 관측 시각(${formatTime(obsSource.observed_at)}) 기준이며 현재 값이 아닙니다.`)
    }
    if (observations.sample.truncated) summary.push("샘플이 잘려 있어 합계는 저장된 전체가 아닙니다.")
  }
  summary.push("이 요약은 전체 시스템이 정상이라는 뜻이 아니며 원인, 복구 시점, 성공률을 추정하지 않습니다.")

  // 2. Conceptual flow: four boxes with their own units; never a funnel of one population.
  const local = observations?.local ?? null
  const collection = observations?.collection ?? null
  const steps: ExplanationStep[] = [
    {
      key: "record", title: "1. 기록",
      description: "실행 중인 프로세스가 관측 이벤트를 로컬 스풀에 쓰고, 같은 트랜잭션의 감사 기록을 남깁니다.",
      facts: [
        fact("로컬 스풀 세그먼트", !local ? null : local.status === "ok" ? `${formatNumber(local.segments)}개` : `확인 불가 · ${local.reason}`, local?.status === "ok"),
        fact("미확인 바이트", local?.status === "ok" ? `${formatNumber(local.unacknowledged_bytes)} 바이트` : null),
        fact("로컬 대기 경보", local?.status === "ok" ? `${formatNumber(local.pending_alerts)}건` : null),
      ],
    },
    {
      key: "collect", title: "2. 보관·수집",
      description: "수집기가 스풀을 읽어 PostgreSQL에 보관합니다. 수집 시각은 이벤트가 일어난 시각과 다릅니다.",
      facts: [
        fact("마지막 수집", !collection ? null : collection.last_at ? `${formatTime(collection.last_at)} · 지연 ${Math.floor(collection.lag_seconds ?? 0)}초` : "수집 영수증 없음 (알 수 없음)", collection?.last_at != null),
        fact("수집 영수증", collection ? `${formatNumber(collection.receipts)}건 (샘플)` : null),
      ],
    },
    {
      key: "project", title: "3. 읽기 전용 스냅샷",
      description: "모니터가 저장된 행을 버킷당 상한까지만 읽어 스냅샷 하나로 만듭니다. 쓰기·정리·재처리는 하지 않습니다.",
      facts: [
        fact("읽은 이벤트", observations ? `${formatNumber(observations.events.total)}건 (감사+수집 병합)` : null),
        fact("버킷당 상한", observations ? `${formatNumber(observations.sample.limit_per_bucket)}행 · ${observations.sample.truncated ? `잘림(${truncatedBuckets.join(", ")})` : "잘리지 않음"}` : null),
        fact("관측 로그 출처", `${obsStateLabel} · ${formatTime(obsSource.observed_at)}`, obsSource.freshness === "fresh"),
      ],
    },
    {
      key: "report", title: "4. 고정 보고서",
      description: "화면 진입 또는 재생성 시점에 스냅샷 하나를 고정해 화면·인쇄·JSON에 같은 내용을 씁니다.",
      facts: [
        fact("생성 시각", formatTime(generatedAt)),
        fact("수집 시각", collectedAt ? formatTime(collectedAt) : null),
        fact("캡처 시점 연결", `${transport.state}${transport.detail ? ` · ${transport.detail}` : ""}`, transport.state === "ok"),
      ],
    },
  ]

  // 3. Observed operation status distribution with exact counts and its denominator.
  const opBucket = observations?.sample.buckets.operations
  const operations: Explanation["operations"] = {
    label: "관측된 운영 결과 분포",
    state: !observations ? "unknown" : observations.operations.total === 0 ? "empty" : "observed",
    denominator: observations ? observations.operations.total : null,
    scope: !observations
      ? "관측 로그 출처 확인 불가 · 분모 없음"
      : `operations 버킷 읽은 행 ${opBucket ? `${formatNumber(opBucket.scanned)}${opBucket.truncated ? "+ (잘림)" : ""}` : "알 수 없음"} · 저장 전체가 아닌 샘플 기준`,
    bars: operationBars(observations?.operations ?? null),
    note: "상태 값은 저장된 그대로 셉니다. 미확정(pending)은 lead_accepted=false 로부터 추론하지 않으며, 정의되지 않은 상태 값도 그대로 표시합니다.",
  }

  // 4. Caveats: every limitation of this capture, derived from the report fields.
  const caveats: string[] = []
  if (transport.state !== "ok") caveats.push(`캡처 시점 연결 ${transport.state}${transport.detail ? ` · ${transport.detail}` : ""} · 마지막 정상 응답 ${transport.last_ok_at ? formatTime(transport.last_ok_at) : "없음"}`)
  for (const name of SOURCE_NAMES) {
    const source = sources[name]
    if (source.freshness !== "fresh") {
      caveats.push(`${SOURCE_LABELS[name]}: ${STATE_LABELS[source.freshness as keyof typeof STATE_LABELS] ?? source.freshness}${source.error ? ` · ${source.error}` : ""} · 관측 ${formatTime(source.observed_at)}`)
    }
  }
  if (observations) {
    if (observations.sample.truncated) caveats.push(`샘플 잘림: ${truncatedBuckets.join(", ")} · 합계는 저장 전체가 아님`)
    if (observations.events.rows_truncated) caveats.push(`이벤트 행 표시 제한 ${formatNumber(observations.events.rows_limit)} 초과 · 일부만 보고서에 포함`)
    if (observations.operations.rows_truncated) caveats.push("운영 결과 행 표시 제한 초과 · 분포 건수는 샘플 전체, 목록은 일부")
    const unknown = observations.events.unknown
    if (unknown.severity + unknown.category + unknown.observed_at > 0) {
      caveats.push(`해석 불가 값: 심각도 ${unknown.severity} · 분류 ${unknown.category} · 시각 ${unknown.observed_at} (우선순위 맨 뒤로 정렬)`)
    }
    if (observations.local.status !== "ok") caveats.push(`로컬 스풀 확인 불가 · ${observations.local.reason}`)
    if (observations.collection.receipts === 0) caveats.push("수집 영수증 없음 · 마지막 수집 시각과 지연은 알 수 없음")
  }
  if (caveats.length === 0) caveats.push("캡처 시점에 출처·연결·샘플 한계 경고가 없었습니다. 그래도 저장된 샘플 기준이며 완전한 기록의 증거는 아닙니다.")

  return {
    title: "한눈에 이해하기",
    summary,
    flow: {
      label: "구조 설명 · 개별 실행을 추적한 증거가 아님",
      note: "각 상자의 숫자는 단위와 모집단이 서로 다릅니다(바이트·영수증·행·시각). 앞 상자에서 뒤 상자로 줄어드는 깔때기가 아니며, 화살표는 개별 이벤트의 실제 이동을 추적한 것이 아닙니다.",
      steps,
    },
    operations,
    guide: READING_GUIDE,
    caveats,
    provenance: {
      derived_from: "pinned_report",
      generated_at: generatedAt,
      collected_at: collectedAt,
      observations_observed_at: obsSource.observed_at,
      observations_status: obsSource.status,
      transport_state: transport.state,
      computed_by: "frontend buildReport at capture · no model call · no live data",
      reference: ELI5_REFERENCE,
    },
  }
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
  const generatedAt = new Date(now).toISOString()
  const transportRecord: Report["transport"] = { state: transport.state, detail: transport.detail || null, last_ok_at: transport.ok_at }
  return {
    schema: "zeus-observatory-report.v3",
    generated_at: generatedAt,
    scope: snapshot?.scope ?? null,
    collected_at: snapshot?.collected_at ?? null,
    transport: transportRecord,
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
    explanation: buildExplanation(snapshot, observations, sources, transportRecord, generatedAt),
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
