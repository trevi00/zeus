// Pure reading of the `sources.lane_sessions` wire contract (INV-LANE-SESSIONS-001) into the view model
// the 세션 view renders. This module owns the data rules; the presentational components under
// components/sessions/ only arrange what it returns.
//
// Truth rules kept here (and nowhere else):
// - the envelope's absence (older collector), a failed collection, an off-contract body and an invalid
//   observation time are distinct "확인 불가" states, never an empty list;
// - `registered:false` is empty (등록된 레인 없음), not unknown; an unavailable lane stays in the list;
// - `lease_until` is ownership liveness only, never progress; no hang/stall is ever inferred from time;
// - a progress record's event time and collection time stay apart; age is measured from collection;
// - usage without a named measured source is 알 수 없음, never 0;
// - operation call counts are written at finalization, so a running operation has none yet;
// - an execution status, a review verdict and a worker-session review outcome are separate facts;
// - `coverage.uninstrumented` is shown verbatim: sessions outside Zeus task ownership are not observed.
// Nothing here reads the network or writes anything; `now` is passed in so a render is reproducible.

import { STATE_LABELS, formatNumber, laneSessionsFreshness, parseTime, type Freshness, type Snapshot } from "./snapshot"
import { freshnessTone, type Tone } from "./tones"

export const LANE_SESSIONS_SCHEMA = "urn:zeus:lane-sessions:1"

// ----- wire ------------------------------------------------------------------------------------------
export type WireOperation = {
  id: string
  status: string | null
  reason_code: string | null
  decision_id: string | null
  lead_accepted: boolean | null
  calls: { reserved: number | null; settled: number | null } | null
  owner_handoff: boolean
  claimed_at: string | null
  updated_at: string | null
  finished_at: string | null
}
export type WireProgress = {
  sequence: number | null
  generation: number | null
  attempt: number | null
  provider: string | null
  occurred_at: string | null
  collected_at: string | null
  last_event: string | null
  last_completed: { type: string | null; status: string | null; sequence: number | null; occurred_at: string | null; evidence: string | null } | null
  malformed_events: number
}
export type WireInvocation = {
  stage: string | null
  status: string | null
  outcome: string | null
  reason: string | null
  generation: number | null
  attempt: number | null
  invocation: number | null
  provider: string | null
  identity: string | null
  transport: string | null
  model_source: string | null
  requested_model: string | null
  reported_model: string | null
  usage_source: string
  total_tokens: number | null
  reserved_at: string | null
  settled_at: string | null
  elapsed_seconds: number | null
  within_budget: boolean | null
}
export type WireWorkerSession = {
  state: string | null
  version: number | null
  reviews: Array<{ decision_id: string | null; phase: string | null; outcome: string | null }>
  next_owner: string | null
  next_action: string | null
  blocked: boolean | null
  reason: string | null
  owner: { generation: number | null; attempt: number | null } | null
}
export type WireExecution = {
  kind: "task" | "decision"
  id: string
  agent: string | null
  status: string | null
  phase: string | null
  generation: number | null
  attempt: number | null
  lease_until: string | null
  created_at: string | null
  completed_at: string | null
  accepted: boolean | null
  operation: WireOperation | null
  progress: WireProgress | null
  invocations: { count: number; by_status: Record<string, number>; latest: WireInvocation | null }
  worker_session: WireWorkerSession | null
}
export type WireLane =
  | { lane: string; team: string | null; observed_at: string | null; status: "unavailable"; error: string | null }
  | {
      lane: string
      team: string | null
      observed_at: string | null
      status: "ok"
      executions: WireExecution[]
      total: number
      truncated: boolean
      counts: Record<string, number>
      invocations: Record<string, number>
      worker_sessions: Record<string, number>
    }
export type WireLaneSessions = {
  schema: string
  registered: boolean
  authority: string
  lanes: WireLane[]
  coverage: { lanes_registered: number; lanes_observed: number; lanes_unavailable: number; uninstrumented: string[] }
}

type Parsed = { ok: true; data: WireLaneSessions } | { ok: false; reason: string }

const isRecord = (value: unknown): value is Record<string, unknown> => !!value && typeof value === "object" && !Array.isArray(value)
const str = (value: unknown): string | null => (typeof value === "string" ? value : null)
const int = (value: unknown): number | null => (typeof value === "number" && Number.isInteger(value) ? value : null)
const num = (value: unknown): number | null => (typeof value === "number" && Number.isFinite(value) ? value : null)
const bool = (value: unknown): boolean | null => (typeof value === "boolean" ? value : null)
const counts = (value: unknown): Record<string, number> | null => {
  if (!isRecord(value)) return null
  const out: Record<string, number> = {}
  for (const [key, count] of Object.entries(value)) {
    if (int(count) === null) return null
    out[key] = count as number
  }
  return out
}

function readOperation(value: unknown): WireOperation | null | false {
  if (value === null || value === undefined) return null
  if (!isRecord(value) || typeof value.id !== "string") return false
  const calls = value.calls === null ? null : isRecord(value.calls) ? { reserved: int(value.calls.reserved), settled: int(value.calls.settled) } : false
  if (calls === false) return false
  return {
    id: value.id, status: str(value.status), reason_code: str(value.reason_code), decision_id: str(value.decision_id),
    lead_accepted: bool(value.lead_accepted), calls, owner_handoff: value.owner_handoff === true,
    claimed_at: str(value.claimed_at), updated_at: str(value.updated_at), finished_at: str(value.finished_at),
  }
}

function readProgress(value: unknown): WireProgress | null | false {
  if (value === null || value === undefined) return null
  if (!isRecord(value)) return false
  const completed = value.last_completed
  if (!(completed === null || completed === undefined || isRecord(completed))) return false
  return {
    sequence: int(value.sequence), generation: int(value.generation), attempt: int(value.attempt), provider: str(value.provider),
    occurred_at: str(value.occurred_at), collected_at: str(value.collected_at), last_event: str(value.last_event),
    last_completed: isRecord(completed) ? {
      type: str(completed.type), status: str(completed.status), sequence: int(completed.sequence),
      occurred_at: str(completed.occurred_at), evidence: str(completed.evidence),
    } : null,
    malformed_events: int(value.malformed_events) ?? 0,
  }
}

function readInvocation(value: unknown): WireInvocation | null | false {
  if (value === null || value === undefined) return null
  if (!isRecord(value) || typeof value.usage_source !== "string") return false
  const tokens = value.total_tokens
  // INV-INVOCATION-001: unknown usage carries no count. A count beside `unknown` is off-contract.
  if (value.usage_source === "unknown" ? tokens !== null : !(tokens === null || int(tokens) !== null)) return false
  return {
    stage: str(value.stage), status: str(value.status), outcome: str(value.outcome), reason: str(value.reason),
    generation: int(value.generation), attempt: int(value.attempt), invocation: int(value.invocation),
    provider: str(value.provider), identity: str(value.identity), transport: str(value.transport),
    model_source: str(value.model_source), requested_model: str(value.requested_model),
    reported_model: str(value.reported_model), usage_source: value.usage_source, total_tokens: int(tokens),
    reserved_at: str(value.reserved_at), settled_at: str(value.settled_at),
    elapsed_seconds: num(value.elapsed_seconds), within_budget: bool(value.within_budget),
  }
}

function readWorkerSession(value: unknown): WireWorkerSession | null | false {
  if (value === null || value === undefined) return null
  if (!isRecord(value)) return false
  const owner = value.owner
  if (!(owner === null || owner === undefined || isRecord(owner))) return false
  // The wire never carries the owning execution's id; an owner object with more than lineage is off-contract.
  if (isRecord(owner) && Object.keys(owner).some((key) => key !== "generation" && key !== "attempt")) return false
  const reviews = Array.isArray(value.reviews) ? value.reviews : []
  return {
    state: str(value.state), version: int(value.version),
    reviews: reviews.filter(isRecord).map((review) => ({
      decision_id: str(review.decision_id), phase: str(review.phase), outcome: str(review.outcome) })),
    next_owner: str(value.next_owner), next_action: str(value.next_action), blocked: bool(value.blocked),
    reason: str(value.reason),
    owner: isRecord(owner) ? { generation: int(owner.generation), attempt: int(owner.attempt) } : null,
  }
}

function readExecution(value: unknown): WireExecution | false {
  if (!isRecord(value) || (value.kind !== "task" && value.kind !== "decision") || typeof value.id !== "string") return false
  const operation = readOperation(value.operation)
  const progress = readProgress(value.progress)
  const invocations = value.invocations
  if (operation === false || progress === false || !isRecord(invocations)) return false
  const latest = readInvocation(invocations.latest)
  const byStatus = counts(invocations.by_status)
  const session = readWorkerSession(value.worker_session)
  if (latest === false || byStatus === null || int(invocations.count) === null || session === false) return false
  return {
    kind: value.kind, id: value.id, agent: str(value.agent), status: str(value.status), phase: str(value.phase),
    generation: int(value.generation), attempt: int(value.attempt), lease_until: str(value.lease_until),
    created_at: str(value.created_at), completed_at: str(value.completed_at), accepted: bool(value.accepted),
    operation, progress, invocations: { count: invocations.count as number, by_status: byStatus, latest },
    worker_session: session,
  }
}

function readLane(value: unknown): WireLane | false {
  if (!isRecord(value) || typeof value.lane !== "string") return false
  const base = { lane: value.lane, team: str(value.team), observed_at: str(value.observed_at) }
  if (value.status === "unavailable") return { ...base, status: "unavailable", error: str(value.error) }
  if (value.status !== "ok" || !Array.isArray(value.executions)) return false
  const executions = value.executions.map(readExecution)
  const laneCounts = counts(value.counts), invocations = counts(value.invocations), sessions = counts(value.worker_sessions)
  if (executions.some((row) => row === false) || int(value.total) === null || typeof value.truncated !== "boolean"
      || laneCounts === null || invocations === null || sessions === null) return false
  return { ...base, status: "ok", executions: executions as WireExecution[], total: value.total as number,
    truncated: value.truncated, counts: laneCounts, invocations, worker_sessions: sessions }
}

/** Narrow `envelope.data` to the INV-LANE-SESSIONS-001 shape; anything off-contract is invalid, not empty. */
export function readLaneSessions(data: unknown): Parsed {
  if (!isRecord(data)) return { ok: false, reason: "data 없음" }
  if (data.schema !== LANE_SESSIONS_SCHEMA) {
    return { ok: false, reason: `schema ${typeof data.schema === "string" ? data.schema : "없음"} ≠ ${LANE_SESSIONS_SCHEMA}` }
  }
  if (typeof data.registered !== "boolean" || !Array.isArray(data.lanes) || !isRecord(data.coverage)) {
    return { ok: false, reason: "registered/lanes/coverage 형식 아님" }
  }
  const coverage = data.coverage
  const uninstrumented = Array.isArray(coverage.uninstrumented) && coverage.uninstrumented.every((line) => typeof line === "string")
    ? (coverage.uninstrumented as string[]) : null
  const [registered, observed, unavailable] = [int(coverage.lanes_registered), int(coverage.lanes_observed), int(coverage.lanes_unavailable)]
  if (uninstrumented === null || registered === null || observed === null || unavailable === null) {
    return { ok: false, reason: "coverage 형식 아님" }
  }
  const lanes = data.lanes.map(readLane)
  if (lanes.some((lane) => lane === false)) return { ok: false, reason: "레인 항목 형식 아님" }
  return { ok: true, data: {
    schema: LANE_SESSIONS_SCHEMA, registered: data.registered, authority: str(data.authority) ?? "",
    lanes: lanes as WireLane[],
    coverage: { lanes_registered: registered, lanes_observed: observed, lanes_unavailable: unavailable, uninstrumented },
  } }
}

// ----- view model ------------------------------------------------------------------------------------
export type Label = { label: string; tone: Tone; note: string }

/** Execution statuses (domain/council.py TASK_STATUSES); anything else renders raw and is flagged. */
const EXECUTION_STATUS: Record<string, Label> = {
  queued: { label: "대기", tone: "warning", note: "실행 전 · 배정 대기" },
  pending: { label: "대기", tone: "warning", note: "실행 전 · 배정 대기" },
  retry: { label: "재시도 대기", tone: "warning", note: "이전 시도 이후 다음 시도 대기" },
  running: { label: "실행 중", tone: "neutral", note: "실행 소유 중 · 진행 여부는 진행 기록으로만 판단" },
  succeeded: { label: "실행 종료", tone: "success", note: "실행이 결과를 냈음 · 검토 수락과 다름" },
  failed: { label: "실패", tone: "error", note: "기록된 실패" },
  blocked: { label: "차단", tone: "error", note: "기록된 차단" },
  expired: { label: "만료", tone: "error", note: "리스 만료로 종료" },
  superseded: { label: "대체됨", tone: "neutral", note: "이후 시도로 대체" },
  inspection_blocked: { label: "검사 차단", tone: "error", note: "검사 단계에서 차단" },
  cancelled: { label: "취소", tone: "neutral", note: "기록된 취소" },
}
const ACTIVE = new Set(["queued", "pending", "retry", "running"])

const OPERATION_STATUS: Record<string, Label> = {
  running: { label: "작업 진행 중", tone: "neutral", note: "레인 작업이 종료되지 않음" },
  accepted: { label: "작업 수락", tone: "success", note: "리드 검토가 후보를 수락 · 병합·배포 아님" },
  rejected: { label: "작업 거부", tone: "error", note: "리드 검토가 후보를 거부" },
  failed: { label: "작업 실패", tone: "error", note: "결정 없이 종료된 실패" },
  unknown: { label: "알 수 없음", tone: "unknown", note: "종료 상태 불확실" },
  exhausted: { label: "예산 소진", tone: "error", note: "예산 소진으로 종료" },
}

const SESSION_STATE: Record<string, Label> = {
  active: { label: "활성", tone: "neutral", note: "실행이 세션을 사용 중일 수 있음" },
  checkpointed: { label: "체크포인트", tone: "neutral", note: "보관 기록 있음 · 재개 가능 여부는 소유자 판단" },
  awaiting_review: { label: "검토 대기", tone: "warning", note: "독립 검토 대기" },
  correction_ready: { label: "수정 준비", tone: "warning", note: "검토 후 수정 대기" },
  accepted: { label: "수락", tone: "success", note: "검토 수락 · 증거 승격 대기일 수 있음" },
  archival_pending: { label: "보관 대기", tone: "neutral", note: "세션 보관 대기" },
  closed: { label: "종료", tone: "neutral", note: "세션 종료" },
  archive_missing: { label: "보관 누락", tone: "error", note: "운영자 확인 필요" },
  archive_corrupt: { label: "보관 손상", tone: "error", note: "운영자 확인 필요" },
  incompatible: { label: "호환 불가", tone: "error", note: "운영자 확인 필요" },
  unresolved: { label: "미해결", tone: "unknown", note: "운영자 확인 필요" },
}
const NEXT_OWNER: Record<string, string> = {
  execution: "실행", conductor: "지휘자", independent_review: "독립 검토", evidence_promotion: "증거 승격",
  session_owner: "세션 소유자", operator: "운영자", none: "없음",
}
const MODEL_SOURCE: Record<string, string> = {
  explicit_setting: "명시 설정", model_routing: "모델 라우팅", manifest: "매니페스트",
}

function lookup(table: Record<string, Label>, raw: string | null): Label {
  if (raw === null) return { label: "기록 없음", tone: "unknown", note: "상태 값이 없음" }
  return table[raw] ?? { label: `${raw} (정의되지 않은 상태)`, tone: "unknown", note: "이 화면이 모르는 상태 값 · 저장된 그대로 표시" }
}

export type Liveness = { state: "lease_live" | "lease_expired" | "no_lease" | "invalid"; label: string; tone: Tone; until: string | null }
export type SessionRow = {
  /** Lane-namespaced key: equal ids in two lanes stay distinct rows. */
  key: string
  lane: string
  kind: "task" | "decision"
  kindLabel: string
  id: string
  shortId: string
  role: string
  phase: string | null
  status: Label & { raw: string | null; active: boolean }
  lineage: { generation: number | null; attempt: number | null }
  liveness: Liveness
  /** Progress: collection time and event time kept apart; `ageMs` is measured from collection. */
  activity: {
    recorded: boolean
    collectedAt: string | null
    occurredAt: string | null
    ageMs: number | null
    lastEvent: string | null
    sequence: number | null
    lastCompleted: string | null
    malformed: number
    /** `ageMs` as display text ("12분 5초 전"), or "진행 기록 없음". */
    ageText: string
  }
  elapsed: { startedAt: string | null; endedAt: string | null; ms: number | null; running: boolean; text: string }
  verdict: Label | null
  operation: null | { id: string; status: Label; reasonCode: string | null; lead: Label; calls: string; handoff: boolean
    handoffText: string }
  invocation: null | {
    count: number
    byStatus: Array<{ status: string; count: number }>
    provider: string
    transport: string | null
    model: string
    modelSource: string
    reportedModel: string
    usage: string
    usageKnown: boolean
    status: string | null
    stage: string | null
    elapsedSeconds: number | null
    /** Korean label of the latest reservation's status and the by-status chips. */
    statusLabel: Label
    byStatusLabels: Array<{ status: string; label: string; count: number }>
    elapsedText: string
  }
  workerSession: null | {
    state: Label
    version: number | null
    owner: string
    nextOwner: string
    nextAction: string | null
    blocked: boolean
    blockedText: string
    reviews: Array<{ decisionId: string | null; phase: string | null; outcome: string | null }>
  }
}
export type LaneView =
  | { id: string; team: string; status: "unavailable"; statusLabel: Label; error: string | null; observedAt: string | null }
  | { id: string; team: string; status: "ok"; statusLabel: Label; observedAt: string | null; total: number; shown: number;
      truncated: boolean; counts: Array<{ key: string; label: string; count: number }>; rows: SessionRow[] }
/**
 * Every lane execution is a headless provider run (`claude -p` stream-json or `codex exec`): there is no
 * interactive terminal or desktop screen to show. The emitted-event activity pane is a later slice (S2);
 * browser screenshots exist only for Zeus-owned test sessions and are not part of this source.
 */
export const SCREEN_NOTICE = "CLI 전용 실행 · 대화형 터미널·화면 없음 (headless). 방출 이벤트 활동 창은 이후 단계에서 제공되며, 브라우저 화면은 Zeus 소유 테스트 세션에만 해당합니다."

/**
 * The fixed coverage boundary in Korean. The collector's `coverage.uninstrumented` statements stay verbatim
 * beside it; this notice is shown even when no coverage record could be read.
 */
export const COVERAGE_NOTICE = "Zeus 작업 소유 밖에서 시작된 세션(외부 조율자·보조 프로세스 등)은 이 화면에서 관측되지 않으며, 유닛 이름이나 프로세스 번호로 추정해 표시하지 않습니다."

export type SessionsModel = {
  freshness: Freshness
  /** Korean label and tone of `freshness.state`. */
  freshnessLabel: Label
  /** Set when rows are shown from an observation that is not fresh: they may not be the current state. */
  staleWarning: string | null
  /** Always shown: what this view cannot see (see COVERAGE_NOTICE). */
  coverageNotice: string
  /** What a session "screen" can truthfully be here; shown with every session detail. */
  screenNotice: string
  /** Why the lanes cannot be shown; `ready` and `unregistered` are the two states with a truthful body. */
  state: "no_response" | "absent" | "unavailable" | "invalid" | "unregistered" | "ready"
  reason: string
  coverage: null | { registered: number; observed: number; unavailable: number; uninstrumented: string[] }
  lanes: LaneView[]
  authority: string
}

function liveness(until: string | null, now: number): Liveness {
  if (until === null) return { state: "no_lease", label: "리스 없음", tone: "neutral", until }
  const at = parseTime(until)
  if (!Number.isFinite(at)) return { state: "invalid", label: "리스 시각 해석 불가", tone: "unknown", until }
  return at > now
    ? { state: "lease_live", label: "소유 리스 유효", tone: "neutral", until }
    : { state: "lease_expired", label: "소유 리스 만료", tone: "warning", until }
}

function age(value: string | null, now: number): number | null {
  const at = parseTime(value)
  return Number.isFinite(at) ? Math.max(0, now - at) : null
}

/** Recorded times only: a finished row counts to its completion, an active one to `now`; otherwise unknown. */
function elapsedMs(started: number, ended: number, active: boolean, now: number): number | null {
  if (!Number.isFinite(started)) return null
  const end = Number.isFinite(ended) ? ended : active ? now : NaN
  return Number.isFinite(end) ? Math.max(0, end - started) : null
}

/** Milliseconds as Korean display text; null stays unknown. Formatting only: no hang/stall judgement. */
export function formatDuration(ms: number | null): string {
  if (ms === null || !Number.isFinite(ms)) return "알 수 없음"
  const total = Math.floor(ms / 1000)
  const hours = Math.floor(total / 3600), minutes = Math.floor((total % 3600) / 60), seconds = total % 60
  if (hours > 0) return `${hours}시간 ${minutes}분`
  if (minutes > 0) return `${minutes}분 ${seconds}초`
  return `${seconds}초`
}

const RESERVATION_STATUS: Record<string, Label> = {
  reserved: { label: "예약됨", tone: "neutral", note: "호출이 진행 중이거나 아직 정산되지 않음" },
  settled: { label: "정산됨", tone: "success", note: "호출이 끝나고 결과와 사용량 출처가 기록됨" },
  unsettled_unknown: { label: "미정산 · 알 수 없음", tone: "unknown", note: "정산되지 못한 호출 · 사용량은 0이 아니라 알 수 없음" },
}

const LANE_STATUS: Record<"ok" | "unavailable", Label> = {
  ok: { label: "관측됨", tone: "success", note: "이 레인의 저장소를 읽음 · 진행이나 수락의 증거는 아님" },
  unavailable: { label: "확인 불가", tone: "error", note: "이 레인의 저장소를 읽지 못함 · 비어 있다는 뜻이 아님" },
}

function shortId(id: string): string {
  return id.length > 16 ? `${id.slice(0, 8)}…${id.slice(-4)}` : id
}

function row(lane: string, wire: WireExecution, now: number): SessionRow {
  const status = lookup(EXECUTION_STATUS, wire.status)
  const active = wire.status !== null && ACTIVE.has(wire.status)
  const started = parseTime(wire.created_at)
  const ended = parseTime(wire.completed_at)
  const latest = wire.invocations.latest
  const progress = wire.progress
  const operation = wire.operation
  const lead: Label = operation?.lead_accepted === true ? { label: "리드 수락", tone: "success", note: "리드 검토 판정" }
    : operation?.lead_accepted === false ? { label: "리드 거부", tone: "error", note: "리드 검토 판정" }
    : { label: "리드 판정 없음", tone: "unknown", note: "아직 판정이 기록되지 않음" }
  return {
    key: `${lane}/${wire.kind}/${wire.id}`,
    lane,
    kind: wire.kind,
    kindLabel: wire.kind === "task" ? "작업 실행" : "검토 결정",
    id: wire.id,
    shortId: shortId(wire.id),
    role: wire.agent ?? "역할 기록 없음",
    phase: wire.phase,
    status: { ...status, raw: wire.status, active },
    lineage: { generation: wire.generation, attempt: wire.attempt },
    liveness: liveness(wire.lease_until, now),
    activity: {
      recorded: progress !== null,
      collectedAt: progress?.collected_at ?? null,
      occurredAt: progress?.occurred_at ?? null,
      ageMs: age(progress?.collected_at ?? null, now),
      lastEvent: progress?.last_event ?? null,
      sequence: progress?.sequence ?? null,
      lastCompleted: progress?.last_completed
        ? [progress.last_completed.type, progress.last_completed.status].filter(Boolean).join(" · ") || null : null,
      malformed: progress?.malformed_events ?? 0,
      ageText: progress === null ? "진행 기록 없음" : age(progress.collected_at, now) === null ? "수집 시각 해석 불가"
        : `${formatDuration(age(progress.collected_at, now))} 전`,
    },
    elapsed: {
      startedAt: wire.created_at,
      endedAt: wire.completed_at,
      // Recorded times only: an active row counts to `now`, a finished one to its completion.
      ms: elapsedMs(started, ended, active, now),
      running: active,
      text: formatDuration(elapsedMs(started, ended, active, now)),
    },
    verdict: wire.kind !== "decision" ? null
      : wire.accepted === true ? { label: "검토 수락", tone: "success", note: "이 결정의 판정" }
      : wire.accepted === false ? { label: "검토 거부", tone: "error", note: "이 결정의 판정" }
      : { label: "판정 없음", tone: "unknown", note: "판정이 기록되지 않음" },
    operation: operation === null ? null : {
      id: operation.id,
      status: lookup(OPERATION_STATUS, operation.status),
      reasonCode: operation.reason_code,
      lead,
      calls: operation.calls === null ? "종료 시 기록 (진행 중)"
        : `예약 ${formatNumber(operation.calls.reserved)} · 정산 ${formatNumber(operation.calls.settled)}`,
      handoff: operation.owner_handoff,
      handoffText: operation.owner_handoff ? "소유자 인계 기록 있음 (팀 작업 화면에서 확인)" : "인계 기록 없음",
    },
    invocation: latest === null ? null : {
      count: wire.invocations.count,
      byStatus: Object.entries(wire.invocations.by_status).map(([key, count]) => ({ status: key, count })),
      provider: latest.provider ?? "제공자 기록 없음",
      transport: latest.transport,
      model: latest.requested_model ?? "요청 모델 기록 없음",
      modelSource: latest.model_source === null ? "출처 기록 없음" : MODEL_SOURCE[latest.model_source] ?? latest.model_source,
      reportedModel: latest.reported_model === "not_projected" || latest.reported_model === null
        ? "응답 모델은 실행 영수증에만 있음 (여기서 읽지 않음)" : latest.reported_model,
      usage: latest.usage_source === "unknown" || latest.total_tokens === null
        ? "알 수 없음 (측정 없음)" : `${formatNumber(latest.total_tokens)} 토큰 · ${latest.usage_source}`,
      usageKnown: latest.usage_source !== "unknown" && latest.total_tokens !== null,
      status: latest.status,
      stage: latest.stage,
      elapsedSeconds: latest.elapsed_seconds,
      statusLabel: lookup(RESERVATION_STATUS, latest.status),
      byStatusLabels: Object.entries(wire.invocations.by_status).map(([key, count]) => (
        { status: key, label: lookup(RESERVATION_STATUS, key).label, count })),
      elapsedText: latest.elapsed_seconds === null ? "정산 전 · 알 수 없음" : formatDuration(latest.elapsed_seconds * 1000),
    },
    workerSession: wire.worker_session === null ? null : {
      state: lookup(SESSION_STATE, wire.worker_session.state),
      version: wire.worker_session.version,
      owner: wire.worker_session.owner === null ? "소유 없음"
        : `실행이 소유 중 · 세대 ${wire.worker_session.owner.generation ?? "?"} · 시도 ${wire.worker_session.owner.attempt ?? "?"}`,
      nextOwner: wire.worker_session.next_owner === null ? "기록 없음"
        : NEXT_OWNER[wire.worker_session.next_owner] ?? wire.worker_session.next_owner,
      nextAction: wire.worker_session.next_action,
      blocked: wire.worker_session.blocked === true,
      blockedText: wire.worker_session.blocked === true ? "차단됨 · 운영자 확인 필요"
        : wire.worker_session.blocked === false ? "차단 아님" : "기록 없음",
      reviews: wire.worker_session.reviews.map((review) => ({ decisionId: review.decision_id, phase: review.phase, outcome: review.outcome })),
    },
  }
}

const COUNT_LABELS: Record<string, string> = { task: "작업", decision: "결정" }

function lane(wire: WireLane, now: number): LaneView {
  const base = { id: wire.lane, team: wire.team ?? "팀 기록 없음", observedAt: wire.observed_at }
  if (wire.status === "unavailable") return { ...base, status: "unavailable", statusLabel: LANE_STATUS.unavailable, error: wire.error }
  return {
    ...base,
    status: "ok",
    statusLabel: LANE_STATUS.ok,
    total: wire.total,
    shown: wire.executions.length,
    truncated: wire.truncated,
    counts: Object.entries(wire.counts).sort(([a], [b]) => a.localeCompare(b)).map(([key, count]) => {
      const [kind, status] = key.split(":")
      return { key, label: `${COUNT_LABELS[kind] ?? kind} · ${status ? lookup(EXECUTION_STATUS, status).label : "?"}`, count }
    }),
    rows: wire.executions.map((execution) => row(wire.lane, execution, now)),
  }
}

/** The whole 세션 view model for one snapshot at one moment. */
export function laneSessionsModel(snapshot: Snapshot | null, now: number): SessionsModel {
  const freshness = laneSessionsFreshness(snapshot, now)
  const common = {
    freshnessLabel: { label: STATE_LABELS[freshness.state], tone: freshnessTone(freshness.state), note: freshness.reason },
    coverageNotice: COVERAGE_NOTICE, screenNotice: SCREEN_NOTICE,
  }
  const empty = { ...common, staleWarning: null, coverage: null, lanes: [], authority: "" }
  if (!snapshot) return { freshness, state: "no_response", reason: "응답 없음", ...empty }
  const envelope = snapshot.sources?.lane_sessions
  if (!envelope) return { freshness, state: "absent", reason: "이 수집기는 레인 세션을 수집하지 않음 (이전 버전)", ...empty }
  if (envelope.status !== "ok") {
    return { freshness, state: "unavailable", reason: envelope.error ? `수집 실패 · ${envelope.error}` : "수집 실패", ...empty }
  }
  const parsed = readLaneSessions(envelope.data)
  if (!parsed.ok) return { freshness, state: "invalid", reason: `형식 해석 불가 · ${parsed.reason}`, ...empty }
  const data = parsed.data
  const coverage = { registered: data.coverage.lanes_registered, observed: data.coverage.lanes_observed,
    unavailable: data.coverage.lanes_unavailable, uninstrumented: data.coverage.uninstrumented }
  if (!data.registered) {
    return { ...common, freshness, state: "unregistered", reason: "등록된 Fleet 레인 없음", staleWarning: null, coverage,
      lanes: [], authority: data.authority }
  }
  return { ...common, freshness, state: "ready", reason: "", coverage, lanes: data.lanes.map((item) => lane(item, now)),
    authority: data.authority,
    staleWarning: freshness.state === "fresh" ? null
      : `${STATE_LABELS[freshness.state]} 관측 · 아래 기록은 현재 상태가 아닐 수 있습니다${freshness.reason ? ` (${freshness.reason})` : ""}` }
}
