import { FLEET_SCHEMA, SOURCE_LABELS, SOURCE_NAMES, STATE_LABELS, fleetFreshness, formatNumber, formatTime, freshness, type EventRow, type FleetData, type FleetJob, type FleetLane, type FleetRegistered, type FreshState, type Observations, type Snapshot } from "./snapshot"
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
 *
 * v4 (report-background-001, Interface lane): `fleet` captures the optional `sources.fleet`
 * envelope of the same snapshot once, as a detached copy validated against the fleet-001 wire
 * contract, and `story` is the goal -> team -> verdict -> remaining reading of that copy. Every
 * v3 field is unchanged. The fleet source is still not in SOURCE_NAMES: `sources`, the caveats
 * and the denominators of the v3 fields never see it. The fleet projection carries goals, lanes,
 * status/reason, call reservations, dependencies and two timestamps; it carries no per-stage
 * timestamps, reviewer findings, patches, merge/deploy facts or a machine call ledger, so none of
 * those are derived here.
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

/**
 * Capture-time state of the optional `sources.fleet` envelope. Each state has one meaning:
 * - `missing`: no snapshot or the snapshot has no `fleet` envelope (older collector) -> 확인 불가;
 * - `unavailable`: the collector reported a failure -> 확인 불가;
 * - `invalid_data`: `status:"ok"` but the body is off the fleet-001 wire contract -> 확인 불가;
 * - `unregistered`: `registered:false` -> 비어 있음, not unknown;
 * - `registered`: `data` holds the detached copy; `freshness` still says whether it is current.
 */
export type FleetCaptureState = "missing" | "unavailable" | "invalid_data" | "unregistered" | "registered"
/** Bound of the collector's job sample (fleet-001 SPEC "Monitoring wire contract": latest 100 jobs). */
export const FLEET_SAMPLE_LIMIT = 100

export type ReportFleet = {
  state: FleetCaptureState
  detail: string
  status: string | null
  error: string | null
  observed_at: string | null
  freshness: FreshState
  freshness_reason: string
  /** Age of the fleet observation at capture (seconds), independent of any job timestamp. */
  age_seconds: number | null
  sample: { limit: number; count: number | null; truncated: boolean | null }
  data: FleetRegistered | null
}

/** Fleet job states of INV-FLEET-001 plus `undefined` for any status string this report does not know. */
export type StoryVerdict = "queued" | "dispatching" | "accepted" | "rejected" | "failed" | "exhausted" | "unknown" | "undefined"
/** Same verdict rule as the 팀 작업 view: only a sampled non-accepted prerequisite confirms unmet; absence is unknown. */
export type StoryDependencyState = "none" | "confirmed_unmet" | "unknown" | "all_accepted"
export type StoryDependency = { id: string; sampled: boolean; status: string | null }
export type StoryJob = {
  id: string
  short_id: string
  team: string | null
  lane: string | null
  operation_id: string | null
  goal: { criterion: string | null; path: string | null }
  status: string
  verdict: StoryVerdict
  verdict_label: string
  verdict_meaning: string
  reason_code: string | null
  calls: { reserved: number | null; settled: number | null }
  dependencies: StoryDependency[]
  dependency_state: StoryDependencyState
  dependency_label: string
  /** 무엇이 남았는가: the recorded facts and who decides next, never a predicted completion. */
  remaining: string
  created_at: string | null
  updated_at: string | null
}
export type StoryLane = { id: string; active_job: string | null; active_in_sample: boolean | null }
export type StoryTeam = { team: string; lanes: StoryLane[]; jobs: StoryJob[] }
export type StoryControl = {
  admission: "open" | "paused"
  max_parallel: number
  lanes_total: number
  active_lanes: number
  active_outside_sample: string[]
  /** Declared call ceilings from the fleet definition: not a remaining balance and not a spend ledger. */
  budget: { per_host: number; total: number }
  /** Sum of the sampled jobs' reservations only; `partial` when any sampled value was null. Not the machine total. */
  sample_calls: { reserved: number | null; settled: number | null; partial: boolean; jobs_unknown: number }
  policy: string[]
}
export type StoryOutcome = { verdict: StoryVerdict; label: string; count: number; remaining: string }
export type Story = {
  title: "무엇을 하려는가 → 어느 팀이 수행했는가 → 어떤 판정인가 → 무엇이 남았는가"
  stage_label: "개념 단계 · 단계별 측정 시각 없음 · 생성·마지막 기록 시각만 실제 값"
  stages: Array<{ key: "goal" | "team" | "verdict" | "remaining"; title: string; note: string }>
  state: FleetCaptureState
  state_note: string
  fleet_id: string | null
  control: StoryControl | null
  teams: StoryTeam[]
  outcomes: StoryOutcome[]
  remaining: string[]
  caveats: string[]
  comparison: { label: string; note: string; before: string[]; after: string[] }
}

export type Report = {
  schema: "zeus-observatory-report.v4"
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
  fleet: ReportFleet
  story: Story
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

/** Labels and meanings of the INV-FLEET-001 job states, as the 팀 작업 view words them; anything else is `undefined`. */
const VERDICTS: Record<StoryVerdict, { label: string; meaning: string }> = {
  queued: { label: "대기", meaning: "admission 전 · 상한·레인·의존성·경로 충돌 검사 대기" },
  dispatching: { label: "배정됨", meaning: "소유 토큰 보유 · 프로세스 생성 전 구간 포함 · 실행 중일 수 있음 · 종료 기록 없음" },
  accepted: { label: "검토 수락", meaning: "독립 검토가 후보를 수락함 · 병합·배포 아님" },
  rejected: { label: "검토 거부", meaning: "독립 검토가 후보를 거부함" },
  failed: { label: "실패", meaning: "정확한 실패 기록 · 자동 재시도 없음" },
  exhausted: { label: "예산 소진", meaning: "호출 예산 상한 도달 · 자동 상향 없음" },
  unknown: { label: "알 수 없음", meaning: "시작·종료·PG 읽기 불확실 · 예약·용량·경로 배제 유지 · 자동 인계 없음" },
  undefined: { label: "정의되지 않은 상태", meaning: "이 보고서가 모르는 상태 값 · 저장된 그대로 표시" },
}
const VERDICT_ORDER: StoryVerdict[] = ["accepted", "dispatching", "queued", "unknown", "rejected", "failed", "exhausted", "undefined"]
/** 무엇이 남았는가 per verdict (SPEC "결과와 잔여"): recorded facts and the next owner decision only. */
const VERDICT_REMAINING: Record<StoryVerdict, string> = {
  accepted: "후보 수락됨 · 병합·배포 여부는 이 출처로 알 수 없음 · 다음은 소유자 통합 결정",
  dispatching: "배정됨 · 종료 기록 없음 · 결과 알 수 없음 · 자동 시간 초과 없음",
  queued: "admission 대기 · 기록된 사유와 의존성 판정 그대로 · 소유자 개입 없이는 배정 순서만 기다림",
  unknown: "소유자 reconciliation 필요 · 소유권·예약 유지 · 성공도 실패도 아님",
  rejected: "검토 거부 사유 기록 · 소유자 다음 결정 필요 · 자동 재시도 없음",
  failed: "실패 사유 기록 · 소유자 다음 결정 필요 · 자동 재시도 없음",
  exhausted: "예산 소진 · 다음 예산은 소유자만 부여 · 자동 상향 없음",
  undefined: "정의되지 않은 상태 · 해석하지 않음 · 소유자 확인 필요",
}
const DEPENDENCY_LABELS: Record<StoryDependencyState, string> = {
  none: "의존성 없음",
  confirmed_unmet: "미충족 확인 · 표본 안 선행 작업이 검토 수락 아님",
  unknown: "표본 밖 선행 작업 · 알 수 없음 · 미충족으로 세지 않음",
  all_accepted: "선행 작업 모두 검토 수락 (표본) · admission 은 별도",
}
const STORY_STAGES: Story["stages"] = [
  { key: "goal", title: "1. 무엇을 하려는가", note: "작업의 goal.criterion 과 경로 · 소유자가 넣은 명시적 작업만" },
  { key: "team", title: "2. 어느 팀이 수행했는가", note: "팀·레인 배정과 생성·마지막 기록 시각 · 단계별 시각은 없음" },
  { key: "verdict", title: "3. 어떤 판정인가", note: "저장된 상태·사유·호출 사실 그대로 · 검토 수락 = 후보 수락" },
  { key: "remaining", title: "4. 무엇이 남았는가", note: "기록된 사실과 다음 결정 주체 · 완료 시점 예측 아님" },
]
/** Before/after of this report screen as a UI design comparison (SPEC): no measured improvement, no code change summary. */
const UI_COMPARISON: Story["comparison"] = {
  label: "UI 설계 비교 · 측정된 운영 개선 아님 · 소스 변경 요약 아님",
  note: "이 보고서 화면의 이전 구성과 현재 구성을 나란히 적은 설명입니다. 성능·정확도·시간 측정값이 아니며 원인 분석도 아닙니다. 요청되거나 제공된 측정은 없습니다.",
  before: [
    "숫자 카드와 분류·심각도·운영 결과 막대가 먼저 보임 (집계만)",
    "출처 → 스냅샷 → 보고서의 개념 경로만 그림으로 표시",
    "쉬운 설명은 접힌 상태 · 팀 작업(fleet)의 목표·판정은 보고서에 없음",
    "무엇을 하려 했고 어느 팀이 어떤 판정을 받았는지 서로 연결되지 않음",
  ],
  after: [
    "목표 → 팀 → 판정 → 잔여 이야기 그림이 집계보다 먼저 · 접히지 않음",
    "작업별 실제 goal.criterion · 짧은 ID · 상태 · 사유 · 호출 예약/정산을 노드에 직접 표기",
    "유한 운영 띠: 호출 상한 · 활성 레인/동시 실행 상한 · 일시 정지 · 표본·잘림 · 관측 시각",
    "이전 집계·차트·상세 섹션은 그대로 아래에 유지 · JSON·인쇄에 같은 이야기 포함",
  ],
}

type ParsedFleet = { ok: true; data: FleetData } | { ok: false; reason: string }

/**
 * Same narrowing rules as `readFleet` in views/fleet.tsx (fleet-001 wire contract): anything off
 * contract is invalid, never empty. Kept here because that function is view-local and unexported;
 * the objects built are new, so the report holds a copy detached from the live snapshot.
 */
function parseFleet(data: unknown): ParsedFleet {
  if (!data || typeof data !== "object") return { ok: false, reason: "data 없음" }
  const record = data as Record<string, unknown>
  if (record.schema !== FLEET_SCHEMA) return { ok: false, reason: `schema ${typeof record.schema === "string" ? record.schema : "없음"} ≠ ${FLEET_SCHEMA}` }
  if (typeof record.registered !== "boolean") return { ok: false, reason: "registered 불리언 아님" }
  if (!Array.isArray(record.lanes) || !Array.isArray(record.jobs)) return { ok: false, reason: "lanes/jobs 배열 아님" }
  if (!record.registered) return { ok: true, data: { schema: FLEET_SCHEMA, registered: false, lanes: [], jobs: [] } }
  const budget = record.budget as Record<string, unknown> | undefined
  if (typeof record.id !== "string" || typeof record.paused !== "boolean" || typeof record.max_parallel !== "number"
    || !budget || typeof budget !== "object" || typeof budget.per_host !== "number" || typeof budget.total !== "number"
    || typeof record.truncated !== "boolean") {
    return { ok: false, reason: "등록 필드(id·paused·max_parallel·budget·truncated) 형식 불일치" }
  }
  const lanes = record.lanes.filter((lane): lane is FleetLane => !!lane && typeof lane === "object" && typeof (lane as FleetLane).id === "string" && typeof (lane as FleetLane).team === "string")
  const jobs = record.jobs.filter((job): job is FleetJob => !!job && typeof job === "object" && typeof (job as FleetJob).id === "string" && typeof (job as FleetJob).status === "string")
  if (lanes.length !== record.lanes.length || jobs.length !== record.jobs.length) return { ok: false, reason: "lanes/jobs 행 형식 불일치" }
  return {
    ok: true,
    data: {
      schema: FLEET_SCHEMA, registered: true, id: record.id, paused: record.paused, max_parallel: record.max_parallel,
      budget: { per_host: budget.per_host, total: budget.total },
      lanes: lanes.map((lane) => ({ id: lane.id, team: lane.team, active_job: typeof lane.active_job === "string" ? lane.active_job : null })),
      jobs: jobs.map((job) => ({
        id: job.id, lane: typeof job.lane === "string" ? job.lane : "", team: typeof job.team === "string" ? job.team : "", status: job.status,
        reason_code: typeof job.reason_code === "string" ? job.reason_code : null,
        operation_id: typeof job.operation_id === "string" ? job.operation_id : "",
        goal: { path: typeof job.goal?.path === "string" ? job.goal.path : "", criterion: typeof job.goal?.criterion === "string" ? job.goal.criterion : "" },
        dependencies: Array.isArray(job.dependencies) ? job.dependencies.filter((d): d is string => typeof d === "string") : [],
        calls: { reserved: typeof job.calls?.reserved === "number" ? job.calls.reserved : null, settled: typeof job.calls?.settled === "number" ? job.calls.settled : null },
        created_at: typeof job.created_at === "string" ? job.created_at : "", updated_at: typeof job.updated_at === "string" ? job.updated_at : "",
      })),
      truncated: record.truncated,
    },
  }
}

/** Capture the optional fleet envelope once, at report time, with the accepted freshness rules. */
export function captureFleet(snapshot: Snapshot | null, now: number): ReportFleet {
  const envelope = snapshot?.sources?.fleet
  const fresh = fleetFreshness(snapshot, now)
  const base = {
    status: envelope?.status ?? null,
    error: envelope?.error ?? null,
    observed_at: fresh.observed_at,
    freshness: fresh.state,
    freshness_reason: fresh.reason,
    age_seconds: fresh.age == null ? null : Math.floor(fresh.age / 1000),
    sample: { limit: FLEET_SAMPLE_LIMIT, count: null, truncated: null },
    data: null,
  }
  if (!snapshot) return { state: "missing", detail: "정상 응답 없음 · 스냅샷 없음 · 팀·작업은 확인 불가", ...base }
  if (!envelope) return { state: "missing", detail: "이 스냅샷에 sources.fleet 출처 없음(이전 계약의 수집기) · 확인 불가 · 비어 있음 아님", ...base }
  if (envelope.status !== "ok") {
    return { state: "unavailable", detail: `fleet 출처 수집 실패 · 상태 ${envelope.status ?? "없음"}${envelope.error ? ` · ${envelope.error}` : ""} · 확인 불가 · 비어 있음 아님`, ...base }
  }
  const parsed = parseFleet(envelope.data)
  if (!parsed.ok) return { state: "invalid_data", detail: `fleet 데이터 해석 불가 · ${parsed.reason} · 계약과 다른 응답은 표시하지 않음 (확인 불가)`, ...base }
  if (!parsed.data.registered) return { state: "unregistered", detail: "등록된 fleet 없음 · 비어 있음 · 확인 불가 아님 · 등록은 소유자의 호스트 명령", ...base }
  return {
    ...base,
    state: "registered",
    detail: fresh.state === "fresh" ? "등록됨 · 관측 최신" : `등록됨 · ${STATE_LABELS[fresh.state]} · ${fresh.reason} · 현재 상태 아님`,
    sample: { limit: FLEET_SAMPLE_LIMIT, count: parsed.data.jobs.length, truncated: parsed.data.truncated },
    data: parsed.data,
  }
}

function verdictOf(status: string): StoryVerdict {
  return Object.hasOwn(VERDICTS, status) && status !== "undefined" ? (status as StoryVerdict) : "undefined"
}

function dependencyStateOf(job: FleetJob, jobsById: Map<string, FleetJob>): StoryDependencyState {
  if (job.dependencies.length === 0) return "none"
  const sampled = job.dependencies.map((dep) => jobsById.get(dep))
  if (sampled.some((prerequisite) => prerequisite && prerequisite.status !== "accepted")) return "confirmed_unmet"
  if (sampled.some((prerequisite) => !prerequisite)) return "unknown"
  return "all_accepted"
}

function shortId(id: string): string {
  return id.length > 20 ? `${id.slice(0, 20)}…` : id
}

function storyJob(job: FleetJob, jobsById: Map<string, FleetJob>): StoryJob {
  const verdict = verdictOf(job.status)
  const dependencyState = dependencyStateOf(job, jobsById)
  const remainingParts = [VERDICT_REMAINING[verdict]]
  if (verdict === "queued" && job.reason_code) remainingParts.unshift(`기록된 사유 ${job.reason_code}`)
  if (verdict === "queued" && dependencyState !== "none") remainingParts.push(DEPENDENCY_LABELS[dependencyState])
  return {
    id: job.id,
    short_id: shortId(job.id),
    team: job.team || null,
    lane: job.lane || null,
    operation_id: job.operation_id || null,
    goal: { criterion: job.goal.criterion || null, path: job.goal.path || null },
    status: job.status,
    verdict,
    verdict_label: verdict === "undefined" ? `${job.status} (${VERDICTS.undefined.label})` : VERDICTS[verdict].label,
    verdict_meaning: VERDICTS[verdict].meaning,
    reason_code: job.reason_code,
    calls: { reserved: job.calls.reserved, settled: job.calls.settled },
    dependencies: job.dependencies.map((dep) => {
      const prerequisite = jobsById.get(dep)
      return { id: dep, sampled: prerequisite != null, status: prerequisite?.status ?? null }
    }),
    dependency_state: dependencyState,
    dependency_label: DEPENDENCY_LABELS[dependencyState],
    remaining: remainingParts.join(" · "),
    created_at: job.created_at || null,
    updated_at: job.updated_at || null,
  }
}

/** The story of one captured fleet copy. Pure function of `fleet`: no live data, clock or request. */
export function buildStory(fleet: ReportFleet): Story {
  const empty: Story = {
    title: "무엇을 하려는가 → 어느 팀이 수행했는가 → 어떤 판정인가 → 무엇이 남았는가",
    stage_label: "개념 단계 · 단계별 측정 시각 없음 · 생성·마지막 기록 시각만 실제 값",
    stages: STORY_STAGES,
    state: fleet.state,
    state_note: fleet.detail,
    fleet_id: null,
    control: null,
    teams: [],
    outcomes: [],
    remaining: [],
    caveats: [],
    comparison: UI_COMPARISON,
  }
  const data = fleet.data
  if (fleet.state !== "registered" || !data) {
    empty.remaining.push(
      fleet.state === "unregistered"
        ? "등록된 fleet 없음 · 소유자가 등록·투입하기 전에는 이야기할 작업이 없음 (비어 있음)"
        : "fleet 출처를 읽지 못해 목표·팀·판정·잔여는 모두 확인 불가 · 0건이 아님 · 출처 복구 후 재생성",
    )
    empty.caveats.push(fleet.detail)
    return empty
  }

  const jobsById = new Map(data.jobs.map((job) => [job.id, job]))
  const jobs = data.jobs.map((job) => storyJob(job, jobsById))
  const teamNames = [...new Set([...data.lanes.map((lane) => lane.team), ...data.jobs.map((job) => job.team || "")])].sort()
  const teams: StoryTeam[] = teamNames.map((team) => ({
    team: team || "팀 없음",
    lanes: data.lanes.filter((lane) => lane.team === team).map((lane) => ({
      id: lane.id, active_job: lane.active_job, active_in_sample: lane.active_job == null ? null : jobsById.has(lane.active_job),
    })),
    jobs: jobs.filter((job) => (job.team ?? "") === team),
  }))

  const activeLanes = data.lanes.filter((lane) => lane.active_job != null)
  const reservedKnown = data.jobs.filter((job) => job.calls.reserved != null)
  const settledKnown = data.jobs.filter((job) => job.calls.settled != null)
  const jobsUnknownCalls = data.jobs.filter((job) => job.calls.reserved == null || job.calls.settled == null).length
  const control: StoryControl = {
    admission: data.paused ? "paused" : "open",
    max_parallel: data.max_parallel,
    lanes_total: data.lanes.length,
    active_lanes: activeLanes.length,
    active_outside_sample: activeLanes.filter((lane) => lane.active_job != null && !jobsById.has(lane.active_job)).map((lane) => `${lane.id} → ${lane.active_job}`),
    budget: { per_host: data.budget.per_host, total: data.budget.total },
    sample_calls: {
      reserved: reservedKnown.length ? reservedKnown.reduce((acc, job) => acc + (job.calls.reserved ?? 0), 0) : null,
      settled: settledKnown.length ? settledKnown.reduce((acc, job) => acc + (job.calls.settled ?? 0), 0) : null,
      partial: jobsUnknownCalls > 0,
      jobs_unknown: jobsUnknownCalls,
    },
    policy: [
      "명시적으로 넣은 작업만 실행 · 생성된 백로그 없음",
      "다음 예산은 소유자만 부여 · 자동 상향·재시도 없음",
      "상한 값은 선언된 호출 수 상한 · 남은 호출·금액·실제 지출 장부 아님",
    ],
  }

  const counts: Partial<Record<StoryVerdict, number>> = {}
  for (const job of jobs) counts[job.verdict] = (counts[job.verdict] ?? 0) + 1
  const outcomes: StoryOutcome[] = VERDICT_ORDER.filter((verdict) => counts[verdict]).map((verdict) => ({
    verdict, label: VERDICTS[verdict].label, count: counts[verdict] ?? 0, remaining: VERDICT_REMAINING[verdict],
  }))

  const remaining: string[] = []
  if (counts.unknown) remaining.push(`알 수 없음 ${formatNumber(counts.unknown)}건 · 소유자 reconciliation 필요 · 자동 해제 없음`)
  const decided = (counts.failed ?? 0) + (counts.rejected ?? 0) + (counts.exhausted ?? 0)
  if (decided) remaining.push(`실패·거부·예산 소진 ${formatNumber(decided)}건 · 사유는 노드에 기록 · 소유자 다음 결정 필요`)
  if (counts.dispatching) remaining.push(`배정됨 ${formatNumber(counts.dispatching)}건 · 종료 기록 없음 · 결과 알 수 없음`)
  if (counts.queued) remaining.push(`대기 ${formatNumber(counts.queued)}건 · admission 과 의존성 판정 대기`)
  if (counts.accepted) remaining.push(`검토 수락 ${formatNumber(counts.accepted)}건 · 후보 수락 · 병합·배포 여부는 이 출처로 알 수 없음 · 소유자 통합 결정`)
  if (counts.undefined) remaining.push(`정의되지 않은 상태 ${formatNumber(counts.undefined)}건 · 해석하지 않음`)
  if (jobs.length === 0) remaining.push("표본 안에 작업 없음 · 등록됨 · 비어 있음 · 확인 불가 아님")

  const caveats: string[] = []
  if (fleet.freshness !== "fresh") caveats.push(`fleet 관측 ${formatTime(fleet.observed_at)} · ${STATE_LABELS[fleet.freshness]}${fleet.freshness_reason ? ` · ${fleet.freshness_reason}` : ""} · 현재 상태 아님`)
  if (data.truncated) caveats.push(`작업 표본 잘림 · 최근 ${formatNumber(FLEET_SAMPLE_LIMIT)}건까지만 · 건수·팀별 분포는 전체가 아님 · 표본 밖 선행 작업 상태는 알 수 없음`)
  if (control.active_outside_sample.length) caveats.push(`표본 밖 활성 작업: ${control.active_outside_sample.join(", ")} (목록에 없음)`)
  if (jobsUnknownCalls) caveats.push(`호출 예약/정산 확인 불가 작업 ${formatNumber(jobsUnknownCalls)}건 · 표본 합계는 부분 합계`)
  if (jobs.some((job) => job.dependency_state === "unknown")) caveats.push("표본 밖 선행 작업은 알 수 없음 · 미충족으로 세지 않음 · 충족도 아님")
  caveats.push("단계별 시각·검토 세부 소견·패치·병합·배포 사실은 fleet 출처에 없음 · 표시하지 않음 · 마지막 기록 시각은 생존 신호 아님")

  return { ...empty, fleet_id: data.id, control, teams, outcomes, remaining, caveats }
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
  const fleet = captureFleet(snapshot, now)
  return {
    schema: "zeus-observatory-report.v4",
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
    fleet,
    story: buildStory(fleet),
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
