import { interpretAccounting, type Accounting } from "./accounting"
import { FLEET_SCHEMA, SOURCE_LABELS, SOURCE_NAMES, STATE_LABELS, fleetFreshness, formatNumber, formatTime, freshness, readDelivery, type EventRow, type FleetData, type FleetDelivery, type FleetJob, type FleetLane, type FleetRegistered, type FreshState, type Observations, type Snapshot } from "./snapshot"
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
 *
 * v5 (local-operations-desk-001, Part A): the captured fleet copy and `story.control` carry the
 * shared usage-accounting reading (`lib/accounting.ts`) instead of dropping the wire mode, so the
 * pinned report never presents a subscription fleet as an active call ceiling and an off-contract
 * or contradictory mode stays unknown. `next_actions` keeps its type but each line now states its own
 * scope: an explicit current state, a stored historical record whose outcome is unresolved or
 * unknown, or a limit/unknown of this capture. No v4 field is removed or renamed, no historical
 * count is dropped, no absent value becomes zero and no incident state is inferred from age.
 * Additively within v5 (local-operations-desk-001, Part C): each captured job keeps the optional
 * owner-recorded `delivery` document of the same wire row, so the pinned report distinguishes
 * merge from deploy exactly as the live view does. Missing stays unknown, an off-contract record
 * is captured as unreadable, and neither is an independent verification of a merge or deployment.
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
  /** Owner-recorded merge/deploy of this job, captured with the rest; absence stays unknown. */
  delivery: StoryDelivery
  /** 무엇이 남았는가: the recorded facts and who decides next, never a predicted completion. */
  remaining: string
  created_at: string | null
  updated_at: string | null
}
/**
 * Captured owner delivery of one job (SPEC "Owner delivery records"):
 * - `unknown`: the job carries no record, so merge and deploy are simply not known here;
 * - `invalid`: a record exists but is off the `urn:zeus:owner-delivery:1` contract -> not shown;
 * - `merged`: the owner recorded a merge revision and nothing about a deployment;
 * - `deployed`: the owner also recorded a deployed revision.
 * Every state is the owner's own report, never this report's verification of GitHub or of a host.
 */
export type StoryDeliveryState = "unknown" | "invalid" | "merged" | "deployed"
export type StoryDelivery = { state: StoryDeliveryState; label: string; note: string; record: FleetDelivery | null }
export type StoryLane = { id: string; active_job: string | null; active_in_sample: boolean | null }
export type StoryTeam = { team: string; lanes: StoryLane[]; jobs: StoryJob[] }
export type StoryControl = {
  admission: "open" | "paused"
  max_parallel: number
  lanes_total: number
  active_lanes: number
  active_outside_sample: string[]
  /** The two wire numbers of the fleet definition; `accounting` says whether they are ceilings at all. */
  budget: { per_host: number; total: number }
  /**
   * Captured usage-accounting reading (lib/accounting.ts), identical to the live 팀 작업 view for
   * the same envelope. In subscription mode the numbers above are retained migration metadata, not
   * an active ceiling; a contradictory or off-contract mode stays unknown.
   */
  accounting: Accounting
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
  schema: "zeus-observatory-report.v5"
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
  "저장된 치명·오류·경보·격리 건수는 '기록 이력'입니다. 지금도 미해결이라는 뜻이 아니고, 해결되었다는 뜻도 아닙니다(결과 미확정 · 알 수 없음). 기록이 오래되었다는 이유로 해결로 바꾸지 않습니다.",
  "'현재 상태'로 적는 것은 미확정 종료 기록처럼 현재 상태가 명시적으로 기록된 항목뿐입니다. 미확정 종료가 막는 범위는 그 작업의 재실행·복구이며 전체 실행 중단이 아닙니다.",
  "'검토 수락'은 후보 수락입니다. 소유자의 병합·배포 기록은 아직 이 보고서에 연결되어 있지 않으므로, 배포 여부는 확인할 수도 부정할 수도 없습니다.",
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
        : `저장된 샘플에서 이벤트 ${formatNumber(observations.events.total)}건을 읽었고, 그중 치명·오류는 ${formatNumber(high)}건입니다. 이는 저장된 과거 기록이며, 지금 미해결이라는 뜻도 해결되었다는 뜻도 아닙니다(결과 미확정·알 수 없음).`,
    )
    summary.push(
      observations.terminations.pending > 0
        ? `현재 상태로 명시된 항목: 미확정 종료 기록 ${formatNumber(observations.terminations.pending)}건. 해당 작업의 재실행·복구만 막히며 전체 실행이 차단된다는 뜻이 아닙니다. 운영자 조정 전까지 그대로 남습니다.`
        : "현재 상태로 명시된 미확정 종료 기록은 0건입니다(저장된 샘플 기준 · 완전성 보장 아님).",
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
        fact("로컬 종료 기록 파일", local?.status === "ok" ? `${formatNumber(local.pending_terminations)}건 · 판독 불가 ${formatNumber(local.unreadable_terminations)}건` : null),
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

/** Scope prefixes of `next_actions`: the line itself says what kind of fact it stands on. */
export const ACTION_CURRENT = "현재 상태"
export const ACTION_HISTORY = "기록 이력"
export const ACTION_UNKNOWN = "확인 불가"

/**
 * Three kinds of line, never mixed (SPEC Part A "Separate historical ... from current known action
 * conditions"):
 * - `현재 상태`: an explicitly recorded current condition (pending terminations, local pending
 *   alerts/unreadable files, unacknowledged spool bytes). Its count is kept exactly as stored.
 * - `기록 이력`: stored records of past events. Their outcome is unresolved or unknown here; they
 *   are neither deleted nor reconciled, and their age proves nothing about the present.
 * - `확인 불가`: a source, freshness or sample limit of this capture.
 */
export function nextActions(observations: Observations | null, unavailable: string[]): string[] {
  const current: string[] = []
  const history: string[] = []
  const unknown: string[] = []
  if (unavailable.length) unknown.push(`${ACTION_UNKNOWN} · 최신이 아니거나 읽지 못한 출처 확인: ${unavailable.join(", ")} · 이 출처의 값은 0이 아니라 알 수 없음`)
  if (!observations) {
    unknown.push(`${ACTION_UNKNOWN} · 관측 로그 출처를 읽지 못해 현재 상태·이력 모두 판단 불가 · 0건 아님`)
    return unknown
  }
  if (observations.terminations.pending > 0) {
    current.push(`${ACTION_CURRENT} · 미확정 종료 기록 ${formatNumber(observations.terminations.pending)}건 (pending_reconciliation·unconfirmed) · 해당 작업의 재실행·복구만 막힘 · 전체 실행 차단 아님 · 운영자 조정 필요`)
  }
  if (observations.local.status === "ok") {
    if (observations.local.pending_alerts > 0) current.push(`${ACTION_CURRENT} · 로컬 대기 경보 ${formatNumber(observations.local.pending_alerts)}건 (로컬 스풀 파일) · 수집기 재생 확인`)
    if (observations.local.unreadable_terminations > 0) current.push(`${ACTION_CURRENT} · 판독 불가 로컬 종료 기록 ${formatNumber(observations.local.unreadable_terminations)}건 · 내용 확인 불가 · 해결 여부 알 수 없음`)
    if (observations.local.pending_terminations > 0) current.push(`${ACTION_CURRENT} · 로컬 종료 기록 파일 ${formatNumber(observations.local.pending_terminations)}건 · 싱크 도달 여부는 이 값으로 알 수 없음`)
    if (observations.local.unacknowledged_bytes > 0) current.push(`${ACTION_CURRENT} · 스풀 미확인 ${formatNumber(observations.local.unacknowledged_bytes)} 바이트 · 수집기 동작 확인`)
  } else {
    unknown.push(`${ACTION_UNKNOWN} · 로컬 스풀 상태 확인 불가 (${observations.local.reason}) · 대기 경보·종료 기록 파일 수는 0이 아니라 알 수 없음`)
  }
  if (observations.events.high_severity_total > 0) {
    history.push(`${ACTION_HISTORY} · 치명·오류 이벤트 ${formatNumber(observations.events.high_severity_total)}건 (표본 기준) · 저장된 과거 기록 · 현재 미해결 증거 아님 · 해결 증거도 아님`)
  }
  if (observations.alerts.recorded > 0) history.push(`${ACTION_HISTORY} · 기록된 경보 ${formatNumber(observations.alerts.recorded)}건 검토 · 상태별 ${Object.entries(observations.alerts.by_status).map(([s, n]) => `${s} ${n}`).join(" · ") || "상태 기록 없음"} · 현재 상태로 해석하지 않음`)
  if (observations.quarantine.total > 0) history.push(`${ACTION_HISTORY} · 격리 기록 ${formatNumber(observations.quarantine.total)}건 원인 확인 · 저장된 과거 기록`)
  const failed = Object.entries(observations.operations.by_status).filter(([status]) => ["failed", "rejected", "exhausted", "unknown"].includes(status))
  if (failed.length) history.push(`${ACTION_HISTORY} · 운영 결과 확인: ${failed.map(([s, n]) => `${s} ${n}`).join(", ")} · 저장된 결과 그대로 · 후속 조치 여부는 이 출처에 없음`)
  if (observations.sample.truncated) unknown.push(`${ACTION_UNKNOWN} · 샘플이 잘렸으므로 합계는 저장 전체가 아님 · 직접 조회 필요`)
  if (observations.events.unknown.severity + observations.events.unknown.category + observations.events.unknown.observed_at > 0) {
    unknown.push(`${ACTION_UNKNOWN} · 해석 불가 값 (심각도 ${observations.events.unknown.severity} · 분류 ${observations.events.unknown.category} · 시각 ${observations.events.unknown.observed_at}) · 정상으로도 이상으로도 세지 않음`)
  }
  if (current.length === 0) {
    current.push(`${ACTION_CURRENT} · 명시적으로 기록된 현재 조치 상태 없음 · 저장된 샘플 기준이며 완전성 보장 아님 · 아래 이력 항목은 그대로 남아 있음`)
  }
  return [...current, ...history, ...unknown]
}

/** Labels and meanings of the INV-FLEET-001 job states, as the 팀 작업 view words them; anything else is `undefined`. */
const VERDICTS: Record<StoryVerdict, { label: string; meaning: string }> = {
  queued: { label: "대기", meaning: "admission 전 · 상한·레인·의존성·경로 충돌 검사 대기" },
  dispatching: { label: "배정됨", meaning: "소유 토큰 보유 · 프로세스 생성 전 구간 포함 · 실행 중일 수 있음 · 종료 기록 없음" },
  accepted: { label: "검토 수락", meaning: "독립 검토가 후보를 수락함 · 병합·배포 아님" },
  rejected: { label: "검토 거부", meaning: "독립 검토가 후보를 거부함" },
  failed: { label: "실패", meaning: "정확한 실패 기록 · 자동 재시도 없음" },
  exhausted: { label: "예산 소진", meaning: "예산 소진으로 기록된 상태 · 기록 당시 기준 · 자동 상향 없음" },
  unknown: { label: "알 수 없음", meaning: "시작·종료·PG 읽기 불확실 · 예약·용량·경로 배제 유지 · 자동 인계 없음" },
  undefined: { label: "정의되지 않은 상태", meaning: "이 보고서가 모르는 상태 값 · 저장된 그대로 표시" },
}
const VERDICT_ORDER: StoryVerdict[] = ["accepted", "dispatching", "queued", "unknown", "rejected", "failed", "exhausted", "undefined"]
/** 무엇이 남았는가 per verdict (SPEC "결과와 잔여"): recorded facts and the next owner decision only. */
const VERDICT_REMAINING: Record<StoryVerdict, string> = {
  accepted: "후보 수락됨 · 병합·배포는 소유자 기록이 있을 때만 알 수 있음 · 다음은 소유자 통합 결정",
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
    "운영 한계 띠: 캡처된 호출 회계 방식(유한 상한 또는 구독 기록 또는 확인 불가) · 활성 레인/동시 실행 상한 · 일시 정지 · 표본·잘림 · 관측 시각",
    "이전 집계·차트·상세 섹션은 그대로 아래에 유지 · JSON·인쇄에 같은 이야기 포함",
  ],
}

type ParsedFleet = { ok: true; data: FleetData } | { ok: false; reason: string }

/**
 * Same narrowing rules as `readFleet` in views/fleet.tsx (fleet-001 wire contract): anything off
 * contract is invalid, never empty. Kept here because that function is view-local and unexported;
 * the objects built are new, so the report holds a copy detached from the live snapshot. The
 * accounting mode is the one place the two decoders do share: both call `interpretAccounting`, so a
 * subscription, finite or contradictory mode reads the same way live and in the pinned report. An
 * off-contract mode makes the reading unknown; it never invalidates the whole envelope.
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
      // Same shared reading as the live 팀 작업 decoder (lib/accounting.ts): the mode is captured
      // once here and the poll never rewrites it, so screen, print and JSON agree.
      accounting: interpretAccounting(record.accounting_mode, budget.mode),
      lanes: lanes.map((lane) => ({ id: lane.id, team: lane.team, active_job: typeof lane.active_job === "string" ? lane.active_job : null })),
      jobs: jobs.map((job) => ({
        id: job.id, lane: typeof job.lane === "string" ? job.lane : "", team: typeof job.team === "string" ? job.team : "", status: job.status,
        reason_code: typeof job.reason_code === "string" ? job.reason_code : null,
        operation_id: typeof job.operation_id === "string" ? job.operation_id : "",
        goal: { path: typeof job.goal?.path === "string" ? job.goal.path : "", criterion: typeof job.goal?.criterion === "string" ? job.goal.criterion : "" },
        dependencies: Array.isArray(job.dependencies) ? job.dependencies.filter((d): d is string => typeof d === "string") : [],
        calls: { reserved: typeof job.calls?.reserved === "number" ? job.calls.reserved : null, settled: typeof job.calls?.settled === "number" ? job.calls.settled : null },
        created_at: typeof job.created_at === "string" ? job.created_at : "", updated_at: typeof job.updated_at === "string" ? job.updated_at : "",
        // Same shared reading as the live decoder: the owner delivery document is captured once,
        // absence stays unknown and an off-contract record is captured as unreadable, not as facts.
        delivery: readDelivery(job.delivery),
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

/** The captured delivery of one job. The owner's document only; absence is never "미배포". */
function storyDelivery(delivery: FleetDelivery | null | false): StoryDelivery {
  if (delivery === false) {
    return { state: "invalid", label: "배송 기록 형식 불일치", record: null,
      note: "계약(urn:zeus:owner-delivery:1)과 다른 기록 · 표시하지 않음 · 확인 불가" }
  }
  if (delivery === null) {
    return { state: "unknown", label: "소유자 기록 없음", record: null,
      note: "병합·배포 여부 확인 불가 · 미배포 증거 아님 · '검토 수락'에서 배포를 추론하지 않음" }
  }
  const deployed = delivery.deployed_revision != null
  return {
    state: deployed ? "deployed" : "merged",
    label: deployed ? "소유자 기록 · 병합 + 배포" : "소유자 기록 · 병합만",
    note: `소유자가 직접 기록한 문서(owner_recorded) · 독립 검증 아님 · 병합 ${delivery.merge_revision.slice(0, 12)}`
      + (deployed ? ` · 배포 ${delivery.deployed_revision?.slice(0, 12)}` : " · 배포 기록 없음 · 배포 여부 확인 불가")
      + ` · 기록 시각 ${formatTime(delivery.recorded_at)} · 증거 ${formatNumber(delivery.evidence_refs.length)}건`,
    record: delivery,
  }
}

function shortId(id: string): string {
  return id.length > 20 ? `${id.slice(0, 20)}…` : id
}

function storyJob(job: FleetJob, jobsById: Map<string, FleetJob>): StoryJob {
  const verdict = verdictOf(job.status)
  const dependencyState = dependencyStateOf(job, jobsById)
  const delivery = storyDelivery(job.delivery)
  const remainingParts = [VERDICT_REMAINING[verdict]]
  if (verdict === "queued" && job.reason_code) remainingParts.unshift(`기록된 사유 ${job.reason_code}`)
  if (verdict === "queued" && dependencyState !== "none") remainingParts.push(DEPENDENCY_LABELS[dependencyState])
  // Delivery is a separate owner statement, appended to the verdict rather than replacing it.
  if (delivery.state === "merged" || delivery.state === "deployed") remainingParts.push(delivery.label)
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
    delivery,
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
    accounting: data.accounting,
    sample_calls: {
      reserved: reservedKnown.length ? reservedKnown.reduce((acc, job) => acc + (job.calls.reserved ?? 0), 0) : null,
      settled: settledKnown.length ? settledKnown.reduce((acc, job) => acc + (job.calls.settled ?? 0), 0) : null,
      partial: jobsUnknownCalls > 0,
      jobs_unknown: jobsUnknownCalls,
    },
    policy: [
      "명시적으로 넣은 작업만 실행 · 생성된 백로그 없음",
      "다음 예산은 소유자만 부여 · 자동 상향·재시도 없음",
      `${data.accounting.label} · ${data.accounting.numbers_note}`,
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
  const deliveries = jobs.map((job) => job.delivery)
  const merged = deliveries.filter((delivery) => delivery.state === "merged" || delivery.state === "deployed").length
  const deployed = deliveries.filter((delivery) => delivery.state === "deployed").length
  const deliveryInvalid = deliveries.filter((delivery) => delivery.state === "invalid").length
  if (counts.accepted) {
    remaining.push(`검토 수락 ${formatNumber(counts.accepted)}건 · 후보 수락 · 소유자 병합 기록 ${formatNumber(merged)}건 · 그중 배포 기록 ${formatNumber(deployed)}건 (표본) · 기록 없는 작업은 확인 불가 · 소유자 통합 결정`)
  }
  if (counts.undefined) remaining.push(`정의되지 않은 상태 ${formatNumber(counts.undefined)}건 · 해석하지 않음`)
  if (jobs.length === 0) remaining.push("표본 안에 작업 없음 · 등록됨 · 비어 있음 · 확인 불가 아님")

  const caveats: string[] = []
  if (fleet.freshness !== "fresh") caveats.push(`fleet 관측 ${formatTime(fleet.observed_at)} · ${STATE_LABELS[fleet.freshness]}${fleet.freshness_reason ? ` · ${fleet.freshness_reason}` : ""} · 현재 상태 아님`)
  if (data.truncated) caveats.push(`작업 표본 잘림 · 최근 ${formatNumber(FLEET_SAMPLE_LIMIT)}건까지만 · 건수·팀별 분포는 전체가 아님 · 표본 밖 선행 작업 상태는 알 수 없음`)
  if (control.active_outside_sample.length) caveats.push(`표본 밖 활성 작업: ${control.active_outside_sample.join(", ")} (목록에 없음)`)
  if (jobsUnknownCalls) caveats.push(`호출 예약/정산 확인 불가 작업 ${formatNumber(jobsUnknownCalls)}건 · 표본 합계는 부분 합계`)
  if (jobs.some((job) => job.dependency_state === "unknown")) caveats.push("표본 밖 선행 작업은 알 수 없음 · 미충족으로 세지 않음 · 충족도 아님")
  if (data.accounting.mode === "unknown") caveats.push(`호출 회계 방식 확인 불가 · ${data.accounting.detail} · 기록된 호출 수치를 적용 중인 상한으로 읽지 않음`)
  if (data.accounting.mode === "subscription") caveats.push(`구독 사용량 기록 · ${data.accounting.numbers_note}`)
  caveats.push("단계별 시각·검토 세부 소견·패치·병합·배포 사실은 fleet 출처에 없음 · 표시하지 않음 · 마지막 기록 시각은 생존 신호 아님")
  caveats.push("병합·배포는 소유자가 직접 남긴 기록(owner_recorded)만 표시 · 이 보고서의 독립 검증이 아니며 GitHub·호스트를 확인하지 않음 · '검토 수락'에서 배포를 추론하지 않고, 기록이 없다는 것도 미배포의 증거가 아님")
  if (deliveryInvalid) caveats.push(`계약과 다른 배송 기록 ${formatNumber(deliveryInvalid)}건 · 표시하지 않음 · 확인 불가`)

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
    schema: "zeus-observatory-report.v5",
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
