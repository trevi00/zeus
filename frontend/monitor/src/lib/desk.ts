/**
 * Client of the local desk contract (`adapters/frontdesk_http.py`, local-operations-desk-001 Part B).
 *
 * Exactly the four implemented routes, nothing invented:
 * - `GET  /api/desk`                    -> `{schema, sessions[], truncated}`
 * - `GET  /api/desk/session/<uuid>`     -> `{schema, session, requests[], bounds}`
 * - `POST /api/desk/sessions`           -> 201 created, 200 replay
 * - `POST /api/desk/messages`           -> 202 accepted, 200 replay
 * Errors are the fixed `{schema, error:<code>}` documents with their status; no other shape is
 * accepted as success, and a body this client cannot read is a protocol failure, not an answer.
 *
 * Every POST proves local intent exactly as the server demands: JSON content type and the custom
 * `X-Zeus-Desk: 1` header (the browser itself sends the same-origin `Origin`, which the server
 * matches against its loopback host). The identities are client-generated UUIDs, so an uncertain
 * submission can be repeated with the SAME id and body: the server replays the stored row instead
 * of creating a second request, and no provider call is made twice. Following the MDN Fetch rule
 * consulted in the SPEC, a rejected or aborted fetch is NOT a failed submission: it is uncertain,
 * kept in local storage with its identity and body until an authoritative answer exists.
 *
 * What counts as an authoritative refusal is narrow: only an explicit 4xx (validation or conflict)
 * decides a submission. A 5xx with a fixed code — `desk_unavailable` above all — may still have
 * committed before the answer was lost, so it is uncertainty: the identity is kept, never cleared,
 * and never replaced with a fresh one. The deadline and the caller's cancellation stay connected
 * through reading and parsing the body, so a stalled response cannot hang a call forever.
 *
 * Nothing here sends a model, base revision, command or budget: the server owns all of those.
 * User text is never written to the console.
 */

export const DESK_SCHEMA = "urn:zeus:desk:1"
export const DESK_TEXT_MAX = 6000
export const DESK_TITLE_MAX = 200
/** Client-side deadline for one desk call; the server's own body read timeout is 5s. */
export const DESK_TIMEOUT_MS = 8_000
export const DESK_POLL_MS = 3_000
const PENDING_KEY = "zeus.desk.pending.v1"
const CREATION_KEY = "zeus.desk.creation.v1"
const SELECTED_KEY = "zeus.desk.selected.v1"

export type DeskIntent = "consult" | "request"
export type DeskStatus = "queued" | "dispatching" | "answered" | "needs_spec" | "failed" | "needs_reconciliation"

export type DeskSession = {
  session_id: string
  title: string
  request_count: number
  created_at: string
  updated_at: string
}

export type DeskAnswer = {
  answer: string
  objective: string | null
  acceptance_criteria: string[]
  questions: string[]
  /** The server's own authority label: unverified conversation context, never an approval. */
  authority: string
}

export type DeskRequest = {
  request_id: string
  session_id: string
  intent: DeskIntent
  text: string
  originator: string
  status: string
  reason_code: string | null
  sequence: number
  answer: DeskAnswer | null
  provenance: { base_revision: string | null; task_id: string | null; execution_ref: string | null; correlation_id: string | null }
  created_at: string
  updated_at: string
  dispatched_at: string | null
  finished_at: string | null
}

export type DeskSessionDetail = { session: DeskSession; requests: DeskRequest[]; max_requests: number | null }

/**
 * Outcome of one desk call.
 * - `ok`: an authoritative response of the expected shape;
 * - `refused`: the server answered with a fixed error code, so the submission is durably decided;
 * - `uncertain`: no authoritative answer exists (rejected fetch, abort, timeout, unreadable or
 *   off-contract body). A write in this state may or may not have been stored, so it is retried
 *   with the same identity instead of being reported as sent or as failed.
 */
export type DeskResult<T> =
  | { ok: true; value: T; status: number; replayed: boolean }
  | { ok: false; kind: "refused"; status: number; code: string; message: string }
  | { ok: false; kind: "uncertain"; status: number | null; code: string; message: string }

/** A submission held locally until the server states its outcome; the body is kept byte-identical. */
export type PendingSubmission = {
  session_id: string
  request_id: string
  intent: DeskIntent
  text: string
  /** Bookkeeping only; the retry never changes any field above. */
  attempts: number
  first_attempt_at: string
}

/** A session creation held locally in the same way: the id AND the title are frozen until decided. */
export type PendingCreation = {
  session_id: string
  title: string
  attempts: number
  first_attempt_at: string
}

const ERROR_TEXT: Record<string, string> = {
  desk_unavailable: "창구 저장소(PG)에 연결하지 못했습니다.",
  origin_refused: "브라우저가 보낸 출처가 서버의 루프백 권한과 일치하지 않아 거부되었습니다.",
  content_type_refused: "요청 형식이 JSON 이 아니어서 거부되었습니다.",
  desk_header_required: "로컬 의도 확인 헤더가 없어 거부되었습니다.",
  content_length_required: "요청 길이 표기가 올바르지 않아 거부되었습니다.",
  body_too_large: "본문이 32KiB 상한을 넘어 거부되었습니다.",
  invalid_json: "본문을 JSON 으로 읽지 못했습니다.",
  invalid_body: "본문 형식이 계약과 다릅니다.",
  invalid_id: "식별자 형식이 올바르지 않습니다.",
  invalid_intent: "의도 값이 consult·request 가 아닙니다.",
  invalid_text: "제어 문자가 포함되어 있거나 문자열이 아닙니다.",
  text_out_of_bounds: `글자 수가 범위를 벗어났습니다 (1–${DESK_TEXT_MAX}자).`,
  session_conflict: "같은 ID 의 대화에 다른 제목이 이미 저장되어 있습니다 (충돌).",
  request_conflict: "같은 요청 ID 로 다른 내용이 이미 저장되어 있습니다 (충돌). 내용을 바꾸려면 새 요청으로 보내세요.",
  session_busy: "이 대화에 아직 처리 중인 요청이 있습니다. 순서를 지키기 위해 끝난 뒤에 다음 요청을 받습니다.",
  session_full: "이 대화의 요청 수 상한에 도달했습니다. 기록은 지워지지 않으며 새 대화를 여세요.",
  session_unknown: "그 대화를 서버에서 찾지 못했습니다.",
  request_unknown: "그 요청을 서버에서 찾지 못했습니다.",
  unknown: "서버가 고정된 사유 코드만 알려주었습니다.",
}

export function errorText(code: string): string {
  return ERROR_TEXT[code] ?? "서버가 이 화면이 모르는 사유 코드를 돌려주었습니다."
}

/** A client-generated identity; `crypto.randomUUID` is required by the server's UUID grammar. */
export function newId(): string {
  return crypto.randomUUID()
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === "object" && !Array.isArray(value)
}

function readSession(value: unknown): DeskSession | null {
  if (!isRecord(value)) return null
  const { session_id, title, request_count, created_at, updated_at } = value
  if (typeof session_id !== "string" || typeof title !== "string" || typeof request_count !== "number") return null
  return { session_id, title, request_count,
    created_at: typeof created_at === "string" ? created_at : "",
    updated_at: typeof updated_at === "string" ? updated_at : "" }
}

function readAnswer(value: unknown): DeskAnswer | null {
  if (!isRecord(value)) return null
  if (typeof value.answer !== "string") return null
  const list = (field: unknown) => (Array.isArray(field) ? field.filter((item): item is string => typeof item === "string") : [])
  return {
    answer: value.answer,
    objective: typeof value.objective === "string" ? value.objective : null,
    acceptance_criteria: list(value.acceptance_criteria),
    questions: list(value.questions),
    authority: typeof value.authority === "string" ? value.authority : "",
  }
}

function readRequest(value: unknown): DeskRequest | null {
  if (!isRecord(value)) return null
  const { request_id, session_id, intent, text, status, sequence } = value
  if (typeof request_id !== "string" || typeof session_id !== "string" || typeof text !== "string") return null
  if (intent !== "consult" && intent !== "request") return null
  if (typeof status !== "string" || typeof sequence !== "number") return null
  const provenance = isRecord(value.provenance) ? value.provenance : {}
  const text_of = (field: unknown) => (typeof field === "string" ? field : null)
  return {
    request_id, session_id, intent, text, status, sequence,
    originator: typeof value.originator === "string" ? value.originator : "local_user",
    reason_code: text_of(value.reason_code),
    answer: readAnswer(value.answer),
    provenance: {
      base_revision: text_of(provenance.base_revision), task_id: text_of(provenance.task_id),
      execution_ref: text_of(provenance.execution_ref), correlation_id: text_of(provenance.correlation_id),
    },
    created_at: typeof value.created_at === "string" ? value.created_at : "",
    updated_at: typeof value.updated_at === "string" ? value.updated_at : "",
    dispatched_at: text_of(value.dispatched_at), finished_at: text_of(value.finished_at),
  }
}

const UNCERTAIN = (code: string, message: string, status: number | null = null): DeskResult<never> =>
  ({ ok: false, kind: "uncertain", status, code, message })

const CANCELLED_TEXT = "요청이 취소되었습니다. 전송 여부는 알 수 없습니다."
const TIMEOUT_TEXT = `응답이 ${DESK_TIMEOUT_MS / 1000}초 안에 끝나지 않았습니다. 전송 여부는 알 수 없습니다.`
const NO_ANSWER_TEXT = "응답을 받지 못했습니다 (연결 실패). 전송 여부는 알 수 없습니다."

/**
 * One desk call with its own deadline. `external` lets a caller abort on unmount or on a changed
 * selection, so a stale response can never be written into a newer selection.
 *
 * The deadline covers the WHOLE call, body included: a response whose stream never finishes is
 * aborted at `DESK_TIMEOUT_MS` instead of waiting forever, and an external abort keeps working
 * after the headers arrive. An already-aborted caller never opens a connection at all, and the
 * timer and the listener are released in one outer `finally` on every path.
 */
async function call<T>(path: string, init: RequestInit, external: AbortSignal | undefined,
                       read: (envelope: unknown) => T | null): Promise<DeskResult<T>> {
  const controller = new AbortController()
  let timedOut = false
  const onTimeout = () => { timedOut = true; controller.abort() }
  const onAbort = () => controller.abort()
  const timer = setTimeout(onTimeout, DESK_TIMEOUT_MS)
  if (external?.aborted) controller.abort()
  else external?.addEventListener("abort", onAbort)
  try {
    if (controller.signal.aborted) return UNCERTAIN("transport_uncertain", CANCELLED_TEXT)
    let response: Response
    try {
      response = await fetch(path, { ...init, signal: controller.signal, cache: "no-store", credentials: "same-origin" })
    } catch {
      // A rejected or aborted fetch is not a refusal and not a delivery: the outcome is unknown.
      return UNCERTAIN("transport_uncertain", timedOut ? TIMEOUT_TEXT : controller.signal.aborted ? CANCELLED_TEXT : NO_ANSWER_TEXT)
    }
    let envelope: unknown
    try {
      // Still under the same deadline and the same cancellation: aborting errors the body stream.
      envelope = await response.json()
    } catch {
      if (timedOut) return UNCERTAIN("transport_uncertain", TIMEOUT_TEXT, response.status)
      if (controller.signal.aborted) return UNCERTAIN("transport_uncertain", CANCELLED_TEXT, response.status)
      return UNCERTAIN("body_unreadable", "응답 본문을 읽지 못했습니다. 전송 여부는 알 수 없습니다.", response.status)
    }
    if (!isRecord(envelope) || envelope.schema !== DESK_SCHEMA) {
      return UNCERTAIN("schema_mismatch", `응답이 ${DESK_SCHEMA} 계약과 다릅니다.`, response.status)
    }
    if (typeof envelope.error === "string") {
      const code = envelope.error
      // Only an explicit 4xx decides the submission: the server read the body and rejected it.
      if (response.status >= 400 && response.status < 500) {
        return { ok: false, kind: "refused", status: response.status, code, message: errorText(code) }
      }
      // Any other status with a fixed code (503 above all) may have committed before answering.
      return UNCERTAIN(code, `${errorText(code)} 저장 여부는 알 수 없습니다.`, response.status)
    }
    if (!response.ok) return UNCERTAIN("status_unexpected", "서버가 사유 코드 없이 오류 상태를 돌려주었습니다.", response.status)
    const value = read(envelope)
    if (value === null) return UNCERTAIN("shape_unexpected", "응답 내용이 계약과 다릅니다.", response.status)
    return { ok: true, value, status: response.status, replayed: envelope.replayed === true }
  } finally {
    clearTimeout(timer)
    external?.removeEventListener("abort", onAbort)
  }
}

function postInit(body: unknown): RequestInit {
  return {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Zeus-Desk": "1" },
    body: JSON.stringify(body),
  }
}

export function listSessions(signal?: AbortSignal): Promise<DeskResult<{ sessions: DeskSession[]; truncated: boolean }>> {
  return call("/api/desk", { method: "GET" }, signal, (envelope) => {
    const record = envelope as Record<string, unknown>
    if (!Array.isArray(record.sessions)) return null
    const sessions = record.sessions.map(readSession)
    if (sessions.some((session) => session === null)) return null
    return { sessions: sessions as DeskSession[], truncated: record.truncated === true }
  })
}

export function readSessionDetail(sessionId: string, signal?: AbortSignal): Promise<DeskResult<DeskSessionDetail>> {
  return call(`/api/desk/session/${encodeURIComponent(sessionId)}`, { method: "GET" }, signal, (envelope) => {
    const record = envelope as Record<string, unknown>
    const session = readSession(record.session)
    if (!session || !Array.isArray(record.requests)) return null
    const requests = record.requests.map(readRequest)
    if (requests.some((request) => request === null)) return null
    const bounds = isRecord(record.bounds) ? record.bounds : {}
    return { session, requests: requests as DeskRequest[],
      max_requests: typeof bounds.max_requests === "number" ? bounds.max_requests : null }
  })
}

/** Idempotent by id and title: the same document is a 200 replay, a different title is a conflict. */
export function createSession(sessionId: string, title: string, signal?: AbortSignal): Promise<DeskResult<DeskSession>> {
  return call("/api/desk/sessions", postInit({ session_id: sessionId, title }), signal,
    (envelope) => readSession((envelope as Record<string, unknown>).session))
}

/** Idempotent by request id and exact body; a changed body under the same id is refused, not stored. */
export function submitMessage(submission: PendingSubmission, signal?: AbortSignal): Promise<DeskResult<DeskRequest>> {
  const body = { session_id: submission.session_id, request_id: submission.request_id,
                 intent: submission.intent, text: submission.text }
  return call("/api/desk/messages", postInit(body), signal,
    (envelope) => readRequest((envelope as Record<string, unknown>).request))
}

/* ----- local persistence: identity and body survive a reload, nothing else does ----- */

function readStored<T>(key: string, accept: (value: unknown) => T | null): T | null {
  try {
    const raw = window.localStorage.getItem(key)
    return raw ? accept(JSON.parse(raw)) : null
  } catch {
    return null
  }
}

/**
 * Write and read back. `true` only if the value is really there afterwards: a storage that throws,
 * that is full or that silently drops the write is NOT durable, and the caller must then refuse the
 * submission instead of keeping the identity in memory only, where a reload would lose it.
 */
function write(key: string, value: unknown): boolean {
  try {
    if (value === null) {
      window.localStorage.removeItem(key)
      return window.localStorage.getItem(key) === null
    }
    const raw = JSON.stringify(value)
    window.localStorage.setItem(key, raw)
    return window.localStorage.getItem(key) === raw
  } catch {
    return false
  }
}

function attemptsOf(value: Record<string, unknown>): Pick<PendingSubmission, "attempts" | "first_attempt_at"> {
  return {
    attempts: typeof value.attempts === "number" ? value.attempts : 1,
    first_attempt_at: typeof value.first_attempt_at === "string" ? value.first_attempt_at : "",
  }
}

export function loadPending(): PendingSubmission | null {
  return readStored(PENDING_KEY, (value) => {
    if (!isRecord(value)) return null
    const { session_id, request_id, intent, text } = value
    if (typeof session_id !== "string" || typeof request_id !== "string" || typeof text !== "string") return null
    if (intent !== "consult" && intent !== "request") return null
    return { session_id, request_id, intent, text, ...attemptsOf(value) }
  })
}

export function savePending(pending: PendingSubmission | null): boolean {
  return write(PENDING_KEY, pending)
}

export function loadPendingCreation(): PendingCreation | null {
  return readStored(CREATION_KEY, (value) => {
    if (!isRecord(value)) return null
    const { session_id, title } = value
    if (typeof session_id !== "string" || typeof title !== "string") return null
    return { session_id, title, ...attemptsOf(value) }
  })
}

export function savePendingCreation(creation: PendingCreation | null): boolean {
  return write(CREATION_KEY, creation)
}

export function loadSelected(): string | null {
  return readStored(SELECTED_KEY, (value) => (typeof value === "string" ? value : null))
}

export function saveSelected(sessionId: string | null): void {
  write(SELECTED_KEY, sessionId)
}
