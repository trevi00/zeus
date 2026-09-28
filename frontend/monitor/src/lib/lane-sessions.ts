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
// - `coverage.uninstrumented` is shown verbatim: sessions outside Zeus task ownership are not observed;
// - the activity pane (S2a) is an emitted-event log of the RETAINED progress receipts, never a terminal, a
//   screen or a transcript; a collector without it is "수집 안 함", never an empty log; every entry that
//   failed stays listed with its fixed reason; sequence and collection time exist only for the last record.
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
/**
 * One retained activity record, projected by the collector's fixed allowlist (FLEET-S2-SPEC §4, FLEET-S2B-SPEC §4).
 * `source` names which ring it came from: the compact `activity_receipt` (S2b, its own sequence, collection time
 * and lineage) or the legacy `progress_receipt` (S2a, only the last record carries sequence/collection time).
 */
export type WireActivityEntry = {
  receipt_ref: string | null
  source: "activity_receipt" | "progress_receipt"
  state: "ok" | "unavailable" | "unreadable" | "malformed"
  error_type: string | null
  event_label: string | null
  tool_name: string | null
  item_type: string | null
  status: string | null
  sequence: number | null
  occurred_at: string | null
  collected_at: string | null
  malformed: boolean | null
  /** Compact entries only (null on legacy ones). */
  activity_sequence: number | null
  generation: number | null
  attempt: number | null
  raw_ref: string | null
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
  /** Both null: the collector predates the activity pane (never an empty log). */
  activity_status: string | null
  activity: WireActivityEntry[] | null
  /** Recorded activity drops (S2b); null when never recorded (an older producer or collector), never 0 by default. */
  activity_dropped: number | null
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

/**
 * Off-contract wire: one malformed supplied value makes the whole body invalid. A key that is absent or
 * `null` is a legitimate unknown; a value of the wrong type, a negative count, a non-list collection or a
 * contradictory shape is never defaulted to "none" or 0 (that would turn untrustworthy data into facts).
 */
class OffContract extends Error {}
const fail = (field: string): never => { throw new OffContract(field) }
const isRecord = (value: unknown): value is Record<string, unknown> => !!value && typeof value === "object" && !Array.isArray(value)
const absent = (value: unknown) => value === null || value === undefined
const str = (value: unknown, field: string): string | null => absent(value) ? null : typeof value === "string" ? value : fail(field)
const bool = (value: unknown, field: string): boolean | null => absent(value) ? null : typeof value === "boolean" ? value : fail(field)
/** A non-negative integer (counts, generations, sequences). */
const count = (value: unknown, field: string): number | null =>
  absent(value) ? null : typeof value === "number" && Number.isInteger(value) && value >= 0 ? value : fail(field)
const seconds = (value: unknown, field: string): number | null =>
  absent(value) ? null : typeof value === "number" && Number.isFinite(value) && value >= 0 ? value : fail(field)
const requiredCount = (value: unknown, field: string): number => count(value, field) ?? fail(field)
const counts = (value: unknown, field: string): Record<string, number> => {
  if (!isRecord(value)) return fail(field)
  return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, requiredCount(item, `${field}.${key}`)]))
}
const record = (value: unknown, field: string): Record<string, unknown> | null => absent(value) ? null : isRecord(value) ? value : fail(field)

function readOperation(value: unknown): WireOperation | null {
  const row = record(value, "operation")
  if (row === null) return null
  const status = str(row.status, "operation.status")
  const callRow = record(row.calls, "operation.calls")
  // INV-LANE-SESSIONS-001: call counts are written at finalization, so a running operation carries none.
  if (status === "running" && callRow !== null) fail("operation.calls (running)")
  return {
    id: str(row.id, "operation.id") ?? fail("operation.id"), status, reason_code: str(row.reason_code, "operation.reason_code"),
    decision_id: str(row.decision_id, "operation.decision_id"), lead_accepted: bool(row.lead_accepted, "operation.lead_accepted"),
    calls: callRow === null ? null : { reserved: count(callRow.reserved, "operation.calls.reserved"),
                                       settled: count(callRow.settled, "operation.calls.settled") },
    owner_handoff: bool(row.owner_handoff, "operation.owner_handoff") === true,
    claimed_at: str(row.claimed_at, "operation.claimed_at"), updated_at: str(row.updated_at, "operation.updated_at"),
    finished_at: str(row.finished_at, "operation.finished_at"),
  }
}

function readProgress(value: unknown): WireProgress | null {
  const row = record(value, "progress")
  if (row === null) return null
  const completed = record(row.last_completed, "progress.last_completed")
  return {
    sequence: count(row.sequence, "progress.sequence"), generation: count(row.generation, "progress.generation"),
    attempt: count(row.attempt, "progress.attempt"), provider: str(row.provider, "progress.provider"),
    occurred_at: str(row.occurred_at, "progress.occurred_at"), collected_at: str(row.collected_at, "progress.collected_at"),
    last_event: str(row.last_event, "progress.last_event"),
    last_completed: completed === null ? null : {
      type: str(completed.type, "progress.last_completed.type"), status: str(completed.status, "progress.last_completed.status"),
      sequence: count(completed.sequence, "progress.last_completed.sequence"),
      occurred_at: str(completed.occurred_at, "progress.last_completed.occurred_at"),
      evidence: str(completed.evidence, "progress.last_completed.evidence"),
    },
    // Absent means no malformed event was recorded; a supplied non-count is corrupt, never a clean 0.
    malformed_events: count(row.malformed_events, "progress.malformed_events") ?? 0,
  }
}

function readInvocation(value: unknown): WireInvocation | null {
  const row = record(value, "invocations.latest")
  if (row === null) return null
  const source = str(row.usage_source, "invocations.latest.usage_source") ?? fail("invocations.latest.usage_source")
  const tokens = count(row.total_tokens, "invocations.latest.total_tokens")
  // INV-INVOCATION-001: unknown usage carries no count. A count beside `unknown` is off-contract.
  if (source === "unknown" && tokens !== null) fail("invocations.latest.total_tokens (unknown usage)")
  return {
    stage: str(row.stage, "invocations.latest.stage"), status: str(row.status, "invocations.latest.status"),
    outcome: str(row.outcome, "invocations.latest.outcome"), reason: str(row.reason, "invocations.latest.reason"),
    generation: count(row.generation, "invocations.latest.generation"), attempt: count(row.attempt, "invocations.latest.attempt"),
    invocation: count(row.invocation, "invocations.latest.invocation"), provider: str(row.provider, "invocations.latest.provider"),
    identity: str(row.identity, "invocations.latest.identity"), transport: str(row.transport, "invocations.latest.transport"),
    model_source: str(row.model_source, "invocations.latest.model_source"),
    requested_model: str(row.requested_model, "invocations.latest.requested_model"),
    reported_model: str(row.reported_model, "invocations.latest.reported_model"), usage_source: source, total_tokens: tokens,
    reserved_at: str(row.reserved_at, "invocations.latest.reserved_at"), settled_at: str(row.settled_at, "invocations.latest.settled_at"),
    elapsed_seconds: seconds(row.elapsed_seconds, "invocations.latest.elapsed_seconds"),
    within_budget: bool(row.within_budget, "invocations.latest.within_budget"),
  }
}

function readWorkerSession(value: unknown): WireWorkerSession | null {
  const row = record(value, "worker_session")
  if (row === null) return null
  const owner = record(row.owner, "worker_session.owner")
  // The wire never carries the owning execution's id; an owner object with more than lineage is off-contract.
  if (owner !== null && Object.keys(owner).some((key) => key !== "generation" && key !== "attempt")) fail("worker_session.owner")
  if (!absent(row.reviews) && !Array.isArray(row.reviews)) fail("worker_session.reviews")
  const reviews = (Array.isArray(row.reviews) ? row.reviews : []).map((review) => {
    if (!isRecord(review)) return fail("worker_session.reviews[]")
    return { decision_id: str(review.decision_id, "worker_session.reviews[].decision_id"),
             phase: str(review.phase, "worker_session.reviews[].phase"), outcome: str(review.outcome, "worker_session.reviews[].outcome") }
  })
  return {
    state: str(row.state, "worker_session.state"), version: count(row.version, "worker_session.version"), reviews,
    next_owner: str(row.next_owner, "worker_session.next_owner"), next_action: str(row.next_action, "worker_session.next_action"),
    blocked: bool(row.blocked, "worker_session.blocked"), reason: str(row.reason, "worker_session.reason"),
    owner: owner === null ? null : { generation: count(owner.generation, "worker_session.owner.generation"),
                                     attempt: count(owner.attempt, "worker_session.owner.attempt") },
  }
}

/** The executor retains at most six progress receipts per execution (FLEET-S2-SPEC §4). */
export const ACTIVITY_LIMIT = 6
const ENTRY_STATES = new Set(["ok", "unavailable", "unreadable", "malformed"])
/** Activity statuses whose list is empty by definition; `ok` needs a readable entry, `unavailable` has none. */
const EMPTY_ACTIVITY = new Set(["not_selected", "empty", "lineage_unconfirmed", "malformed_not_in_recent"])
const RECEIPT_REF = /^sha256:[0-9a-f]{64}$/

function readActivityEntry(value: unknown): WireActivityEntry {
  if (!isRecord(value)) return fail("activity[]")
  const state = typeof value.state === "string" && ENTRY_STATES.has(value.state)
    ? value.state as WireActivityEntry["state"] : fail("activity[].state")
  const errorType = str(value.error_type, "activity[].error_type")
  // Each failed ref names its fixed reason; a readable one has none.
  if (state === "ok" ? errorType !== null : (state === "unavailable" || state === "unreadable") && errorType === null) {
    fail("activity[].error_type")
  }
  const ref = str(value.receipt_ref, "activity[].receipt_ref")
  if (ref !== null && !RECEIPT_REF.test(ref)) fail("activity[].receipt_ref")
  if (state === "ok" && ref === null) fail("activity[].receipt_ref (ok)")
  // An older collector sends no source: its entries are legacy progress receipts. Any other value is off-contract.
  const source = absent(value.source) ? "progress_receipt"
    : value.source === "activity_receipt" || value.source === "progress_receipt" ? value.source : fail("activity[].source")
  const compact = {
    activity_sequence: count(value.activity_sequence, "activity[].activity_sequence"),
    generation: count(value.generation, "activity[].generation"), attempt: count(value.attempt, "activity[].attempt"),
    raw_ref: str(value.raw_ref, "activity[].raw_ref"),
  }
  if (compact.raw_ref !== null && !RECEIPT_REF.test(compact.raw_ref)) fail("activity[].raw_ref")
  if (source === "progress_receipt" && Object.values(compact).some((field) => field !== null)) fail("activity[] (legacy with compact fields)")
  // A readable compact entry carries its own activity sequence and collection time.
  if (source === "activity_receipt" && state === "ok" && (compact.activity_sequence === null || absent(value.collected_at))) {
    fail("activity[] (compact without its metadata)")
  }
  return {
    ...compact, source,
    receipt_ref: ref, state, error_type: errorType, event_label: str(value.event_label, "activity[].event_label"),
    tool_name: str(value.tool_name, "activity[].tool_name"), item_type: str(value.item_type, "activity[].item_type"),
    status: str(value.status, "activity[].status"), sequence: count(value.sequence, "activity[].sequence"),
    occurred_at: str(value.occurred_at, "activity[].occurred_at"), collected_at: str(value.collected_at, "activity[].collected_at"),
    malformed: bool(value.malformed, "activity[].malformed"),
  }
}

function readActivity(statusValue: unknown, listValue: unknown): { activity_status: string | null; activity: WireActivityEntry[] | null } {
  // An older collector sends neither; one without the other is a contradictory shape.
  if (absent(statusValue) && absent(listValue)) return { activity_status: null, activity: null }
  const status = str(statusValue, "execution.activity_status") ?? fail("execution.activity_status")
  if (!Array.isArray(listValue)) return fail("execution.activity")
  if (listValue.length > ACTIVITY_LIMIT) return fail("execution.activity (over the retention bound)")
  const entries = listValue.map(readActivityEntry)
  // One list comes from ONE ring: the collector never merges the compact and legacy rings.
  if (new Set(entries.map((entry) => entry.source)).size > 1) fail("execution.activity (mixed sources)")
  const readable = entries.some((entry) => entry.state === "ok")
  if ((EMPTY_ACTIVITY.has(status) && entries.length > 0) || (status === "ok" && !readable) || (status === "unavailable" && readable)) {
    fail(`execution.activity (${status})`)
  }
  return { activity_status: status, activity: entries }
}

function readExecution(value: unknown): WireExecution {
  if (!isRecord(value)) return fail("execution")
  if (value.kind !== "task" && value.kind !== "decision") return fail("execution.kind")
  const invocations = isRecord(value.invocations) ? value.invocations : fail("execution.invocations")
  return {
    kind: value.kind, id: str(value.id, "execution.id") ?? fail("execution.id"), agent: str(value.agent, "execution.agent"),
    status: str(value.status, "execution.status"), phase: str(value.phase, "execution.phase"),
    generation: count(value.generation, "execution.generation"), attempt: count(value.attempt, "execution.attempt"),
    lease_until: str(value.lease_until, "execution.lease_until"), created_at: str(value.created_at, "execution.created_at"),
    completed_at: str(value.completed_at, "execution.completed_at"), accepted: bool(value.accepted, "execution.accepted"),
    operation: readOperation(value.operation), progress: readProgress(value.progress),
    invocations: { count: requiredCount(invocations.count, "invocations.count"), by_status: counts(invocations.by_status, "invocations.by_status"),
                   latest: readInvocation(invocations.latest) },
    worker_session: readWorkerSession(value.worker_session),
    ...readActivity(value.activity_status, value.activity),
    activity_dropped: count(value.activity_dropped, "execution.activity_dropped"),
  }
}

function readLane(value: unknown): WireLane {
  if (!isRecord(value)) return fail("lane")
  const base = { lane: str(value.lane, "lane.lane") ?? fail("lane.lane"), team: str(value.team, "lane.team"),
                 observed_at: str(value.observed_at, "lane.observed_at") }
  if (value.status === "unavailable") return { ...base, status: "unavailable", error: str(value.error, "lane.error") }
  if (value.status !== "ok") return fail("lane.status")
  if (!Array.isArray(value.executions)) return fail("lane.executions")
  if (typeof value.truncated !== "boolean") return fail("lane.truncated")
  return { ...base, status: "ok", executions: value.executions.map(readExecution), total: requiredCount(value.total, "lane.total"),
    truncated: value.truncated, counts: counts(value.counts, "lane.counts"), invocations: counts(value.invocations, "lane.invocations"),
    worker_sessions: counts(value.worker_sessions, "lane.worker_sessions") }
}

/** Narrow `envelope.data` to the INV-LANE-SESSIONS-001 shape; anything off-contract is invalid, not empty. */
export function readLaneSessions(data: unknown): Parsed {
  if (!isRecord(data)) return { ok: false, reason: "data 없음" }
  if (data.schema !== LANE_SESSIONS_SCHEMA) {
    return { ok: false, reason: `schema ${typeof data.schema === "string" ? data.schema : "없음"} ≠ ${LANE_SESSIONS_SCHEMA}` }
  }
  try {
    if (typeof data.registered !== "boolean") fail("registered")
    if (!Array.isArray(data.lanes)) fail("lanes")
    const coverage = isRecord(data.coverage) ? data.coverage : fail("coverage")
    const uninstrumented = Array.isArray(coverage.uninstrumented) && coverage.uninstrumented.every((line) => typeof line === "string")
      ? (coverage.uninstrumented as string[]) : fail("coverage.uninstrumented")
    return { ok: true, data: {
      schema: LANE_SESSIONS_SCHEMA, registered: data.registered as boolean, authority: str(data.authority, "authority") ?? "",
      lanes: (data.lanes as unknown[]).map(readLane),
      coverage: { lanes_registered: requiredCount(coverage.lanes_registered, "coverage.lanes_registered"),
                  lanes_observed: requiredCount(coverage.lanes_observed, "coverage.lanes_observed"),
                  lanes_unavailable: requiredCount(coverage.lanes_unavailable, "coverage.lanes_unavailable"), uninstrumented },
    } }
  } catch (error) {
    if (error instanceof OffContract) return { ok: false, reason: `형식 아님 · ${error.message}` }
    throw error
  }
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
    /** Set for a Claude `result · success` whose provenance cannot establish the S2b status rule (legacy rows). */
    lastCompletedNote: string | null
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
  /** The activity pane: the retained emitted events of this execution (see EventLog). */
  events: EventLog
}
export type EventEntry = {
  /** Unique within the row (position in retention order). */
  key: string
  /** The receipt ref as plain evidence text to copy, never a link; null when the ref itself was invalid. */
  ref: string | null
  refShort: string | null
  state: Label & { raw: WireActivityEntry["state"] }
  /** Korean reason of a failed entry; null when readable. */
  error: string | null
  event: Label & { raw: string | null }
  /** A built-in tool name only (tool starts); a Claude tool completion never carries one. */
  tool: string | null
  item: string | null
  outcome: Label | null
  occurredAt: string | null
  /** "발생 시각 기록 없음" when the event carries no time (Claude events never do). */
  occurredText: string
  source: WireActivityEntry["source"]
  /**
   * What the metadata line means: `activity_receipt` — this entry's own activity order, raw progress order (null
   * for a tool start), executor collection time and event lineage; `legacy_last_record` — the legacy row's
   * sequence and collection time, which belong to the LAST record only; `none` — no metadata to show.
   */
  metadataKind: "none" | "legacy_last_record" | "activity_receipt"
  /** Labelled metadata in display order; values are model text (times stay ISO, formatted by the component). */
  metadata: Array<{ key: string; label: string; value: string; time: string | null }>
  sequence: number | null
  collectedAt: string | null
  /** True only for the legacy last record (kept for older consumers; use `metadataKind`). */
  isLastRecord: boolean
}
export type EventLog = {
  /** false: the collector predates the activity pane; `status` then says so and `entries` is empty. */
  collected: boolean
  status: Label & { raw: string | null }
  /** Retention order, oldest first (a log, not a feed). */
  entries: EventEntry[]
  /** Why the list is empty or has unreadable entries; null when every retained entry was read. */
  gapText: string | null
  /** Always shown with the pane; `qualification` depends on the ring (compact or legacy). */
  notices: { log: string; retention: string; qualification: string; legacyResult: string | null }
  /** Recorded activity drops; `text` null when none are recorded, and an unknown count is never shown as 0. */
  dropped: { count: number | null; text: string | null }
}
export type LaneView =
  | { id: string; team: string; status: "unavailable"; statusLabel: Label; error: string | null; observedAt: string | null }
  | { id: string; team: string; status: "ok"; statusLabel: Label; observedAt: string | null; total: number; shown: number;
      truncated: boolean; counts: Array<{ key: string; label: string; count: number }>; rows: SessionRow[] }
/**
 * Every lane execution is a headless provider run (`claude -p` stream-json or `codex exec`): there is no
 * interactive terminal or desktop screen to show. The activity pane is the emitted-event log (S2a);
 * browser screenshots exist only for Zeus-owned test sessions and are not part of this source.
 */
export const SCREEN_NOTICE = "CLI 전용 실행 · 대화형 터미널·화면 없음 (headless). 활동 창은 방출 이벤트 로그이며, 브라우저 화면은 Zeus 소유 테스트 세션에만 해당합니다."

/** The pane's fixed notices (FLEET-S2-SPEC §6 and its D1 correction); shown whenever the pane is. */
export const EVENT_LOG_NOTICES = {
  log: "방출 이벤트 로그 · 터미널/화면 아님",
  retention: "최근 6개 이벤트만 보관 (executor retention)",
  qualification: "진행 기록으로 보관된 이벤트만 표시 · 시작/메시지 이벤트는 없을 수 있음",
} as const
/** FLEET-S2B-SPEC §6: the compact ring's coverage note, and the legacy Claude-result caveat. */
export const COMPACT_QUALIFICATION = "최근 활동 이벤트만 표시 · 도구 시작 포함 · 완료와 연결하지 않음 · 새 이벤트가 이전 이벤트를 밀어낼 수 있음"
export const LEGACY_RESULT_NOTE = "이전 형식의 Claude 결과 success는 기록된 subtype이며 실제 성공을 보증하지 않음"

const ACTIVITY_STATUS: Record<string, Label> = {
  ok: { label: "보관 이벤트", tone: "neutral", note: "보관된 진행 이벤트를 읽음 · 진행이나 수락의 증거는 아님" },
  empty: { label: "보관 이벤트 없음", tone: "neutral", note: "이 실행에 보관된 진행 이벤트가 없음" },
  not_selected: { label: "표시 대상 아님", tone: "neutral",
    note: "실행 중이 아니고 최근 종료 창(기본 10분) 밖이거나 상태를 알 수 없는 실행은 이벤트를 읽지 않음" },
  lineage_unconfirmed: { label: "계보 불일치", tone: "warning", note: "진행 기록의 세대·시도가 이 실행과 달라 표시하지 않음" },
  malformed_not_in_recent: { label: "형식 오류 이벤트만 있음", tone: "warning",
    note: "보관 목록이 비어 있고 형식 오류 이벤트만 기록됨 · 그 내용은 읽지 않음" },
  unavailable: { label: "확인 불가", tone: "error", note: "보관 이벤트를 읽지 못함 · 비어 있다는 뜻이 아님" },
}
const ENTRY_STATE: Record<WireActivityEntry["state"], Label> = {
  ok: { label: "기록됨", tone: "neutral", note: "영수증을 읽고 허용 목록만 표시" },
  unavailable: { label: "확인 불가", tone: "unknown", note: "영수증에 닿지 못함 · 없다는 뜻이 아님" },
  unreadable: { label: "읽을 수 없음", tone: "error", note: "영수증을 안전하게 읽지 못함" },
  malformed: { label: "형식 오류", tone: "warning", note: "기록된 이벤트의 형식이 계약과 다름 · 내용은 표시하지 않음" },
}
const ENTRY_ERROR: Record<string, string> = {
  missing_artifact: "영수증 파일 없음", runtime_unavailable: "레인 런타임 저장소 없음", invalid_ref: "잘못된 참조",
  foreign_ref: "이 실행에 속하지 않는 참조", too_large: "크기 한도 초과 (64 KiB)", integrity_failure: "무결성 불일치",
  invalid_json: "JSON 해석 불가", invalid_shape: "형식 불일치", io_error: "읽기 오류",
  binding_mismatch: "다른 실행의 기록 (표시하지 않음)",
}
const EVENT_LABEL: Record<string, Label> = {
  tool_started: { label: "도구 시작", tone: "neutral", note: "Claude 도구 호출 시작" },
  tool_completed: { label: "도구 완료", tone: "neutral", note: "Claude 도구 호출 완료 · 도구 이름은 기록되지 않음" },
  session_started: { label: "세션 시작", tone: "neutral", note: "Claude 세션 시작" },
  permission_denied: { label: "권한 거부", tone: "warning", note: "도구 사용 권한이 거부됨" },
  message: { label: "메시지", tone: "neutral", note: "메시지 이벤트 · 내용은 표시하지 않음" },
  result: { label: "실행 결과", tone: "neutral", note: "Claude 실행의 최종 결과 이벤트" },
  item_completed: { label: "항목 완료", tone: "neutral", note: "Codex 항목 완료" },
  token_usage_updated: { label: "토큰 사용량 갱신", tone: "neutral", note: "Codex 사용량 갱신 이벤트 · 값은 표시하지 않음" },
  unknown: { label: "알 수 없는 이벤트", tone: "unknown", note: "허용 목록 밖의 이벤트 종류 · 이름은 표시하지 않음" },
  malformed: { label: "형식 오류", tone: "warning", note: "이벤트를 해석하지 못함" },
}
const ITEM_TYPE: Record<string, string> = {
  commandExecution: "명령 실행", fileChange: "파일 변경", mcpToolCall: "MCP 도구 호출", agentMessage: "에이전트 메시지",
  reasoning: "추론 항목 (내용 없음)", unknown: "알 수 없는 항목",
}
const EVENT_STATUS: Record<string, Label> = {
  started: { label: "시작", tone: "neutral", note: "" },
  completed: { label: "완료", tone: "success", note: "이벤트가 완료로 기록됨 · 작업 수락과 다름" },
  failed: { label: "실패", tone: "error", note: "이벤트가 실패로 기록됨" },
  denied: { label: "거부", tone: "warning", note: "권한 거부" },
  emitted: { label: "방출", tone: "neutral", note: "" },
  success: { label: "성공", tone: "success", note: "실행 결과가 성공으로 기록됨 · 검토 수락과 다름" },
  error: { label: "오류", tone: "error", note: "실행 결과가 오류로 기록됨" },
  unknown: { label: "알 수 없음", tone: "unknown", note: "허용 목록 밖의 상태 값" },
}

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

function eventEntry(entry: WireActivityEntry, index: number, now: number): EventEntry {
  const occurred = age(entry.occurred_at, now)
  return {
    key: String(index),
    ref: entry.receipt_ref,
    refShort: entry.receipt_ref === null ? null : `${entry.receipt_ref.slice(0, 15)}…${entry.receipt_ref.slice(-4)}`,
    state: { ...ENTRY_STATE[entry.state], raw: entry.state },
    error: entry.error_type === null ? null : ENTRY_ERROR[entry.error_type] ?? `${entry.error_type} (정의되지 않은 사유)`,
    event: entry.event_label === null
      ? { label: entry.state === "ok" ? "기록 없음" : "읽지 못함", tone: "unknown", note: "이벤트 종류를 알 수 없음", raw: null }
      : { ...lookup(EVENT_LABEL, entry.event_label), raw: entry.event_label },
    tool: entry.tool_name,
    item: entry.item_type === null ? null : ITEM_TYPE[entry.item_type] ?? `${entry.item_type} (정의되지 않은 항목)`,
    outcome: entry.status === null ? null : lookup(EVENT_STATUS, entry.status),
    occurredAt: entry.occurred_at,
    occurredText: entry.occurred_at === null ? "발생 시각 기록 없음"
      : occurred === null ? "발생 시각 해석 불가" : `${formatDuration(occurred)} 전 발생`,
    source: entry.source,
    ...entryMetadata(entry),
    sequence: entry.sequence,
    collectedAt: entry.collected_at,
    isLastRecord: entry.source === "progress_receipt" && (entry.sequence !== null || entry.collected_at !== null),
  }
}

/** The metadata line of one entry; never inferred, only what the collector projected for this entry's ring. */
function entryMetadata(entry: WireActivityEntry): Pick<EventEntry, "metadataKind" | "metadata"> {
  if (entry.source === "activity_receipt") {
    if (entry.state !== "ok") return { metadataKind: "none", metadata: [] }
    const lineage = entry.generation === null && entry.attempt === null ? "리스 없음"
      : `세대 ${entry.generation ?? "?"} · 시도 ${entry.attempt ?? "?"}`
    return { metadataKind: "activity_receipt", metadata: [
      { key: "activity_sequence", label: "활동 순번", value: String(entry.activity_sequence), time: null },
      { key: "progress_sequence", label: "진행 순번", value: entry.sequence === null ? "없음 (도구 시작)" : String(entry.sequence), time: null },
      { key: "collected_at", label: "실행기 수집 시각", value: entry.collected_at ?? "기록 없음", time: entry.collected_at },
      { key: "lineage", label: "이벤트 세대/시도", value: lineage, time: null },
    ] }
  }
  if (entry.sequence === null && entry.collected_at === null) return { metadataKind: "none", metadata: [] }
  return { metadataKind: "legacy_last_record", metadata: [
    { key: "sequence", label: "순번", value: entry.sequence === null ? "기록 없음" : String(entry.sequence), time: null },
    { key: "collected_at", label: "수집 시각", value: entry.collected_at ?? "기록 없음", time: entry.collected_at },
  ] }
}

function droppedText(count: number | null): EventLog["dropped"] {
  return { count, text: count === null || count === 0 ? null
    : `기록되지 못한 활동 이벤트 ${formatNumber(count)}개 · 표시 기록일 뿐이며 전체 이벤트 손실 수치가 아님` }
}

function eventLog(wire: WireExecution, now: number): EventLog {
  const legacyNotices = { ...EVENT_LOG_NOTICES, legacyResult: null }
  if (wire.activity_status === null || wire.activity === null) {
    return { collected: false, status: { label: "수집 안 함", tone: "unknown", raw: null,
      note: "이 수집기는 활동 이벤트를 수집하지 않음 (이전 버전) · 비어 있다는 뜻이 아님" },
      entries: [], gapText: "이 수집기는 활동 이벤트를 수집하지 않음 (이전 버전)", notices: legacyNotices,
      dropped: droppedText(wire.activity_dropped) }
  }
  const entries = wire.activity.map((entry, index) => eventEntry(entry, index, now))
  const status = { ...lookup(ACTIVITY_STATUS, wire.activity_status), raw: wire.activity_status }
  const failed = entries.filter((entry) => entry.state.raw !== "ok").length
  const compact = wire.activity.some((entry) => entry.source === "activity_receipt")
  const legacyResult = !compact && wire.activity.some((entry) => entry.event_label === "result" && entry.status === "success")
  return {
    collected: true, status, entries, dropped: droppedText(wire.activity_dropped),
    notices: { ...EVENT_LOG_NOTICES, qualification: compact ? COMPACT_QUALIFICATION : EVENT_LOG_NOTICES.qualification,
               legacyResult: legacyResult ? LEGACY_RESULT_NOTE : null },
    gapText: entries.length === 0 ? status.note
      : failed > 0 ? `${entries.length}개 중 ${failed}개 항목을 읽지 못함 · 항목마다 사유 표시` : null,
  }
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
      // Only a row shown from the compact ring proves the S2b producer (whose result status uses is_error) wrote it.
      lastCompletedNote: progress?.last_completed?.type === "result" && progress.last_completed.status === "success"
        && !(wire.activity ?? []).some((entry) => entry.source === "activity_receipt") ? LEGACY_RESULT_NOTE : null,
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
      calls: operation.calls === null || operation.status === "running" ? "종료 시 기록 (진행 중)"
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
    events: eventLog(wire, now),
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
