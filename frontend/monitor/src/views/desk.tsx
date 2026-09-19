import { useCallback, useEffect, useId, useRef, useState, type ReactNode } from "react"
import { AlertTriangle, CircleHelp, Inbox, MessageSquare, Plus, RefreshCw, Send, ShieldCheck, Users } from "lucide-react"

import { StatusBadge } from "@/components/status-badge"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import {
  DESK_POLL_MS, DESK_TEXT_MAX, DESK_TITLE_MAX, createSession, listSessions, loadPending, loadPendingCreation,
  loadSelected, newId, readSessionDetail, savePending, savePendingCreation, saveSelected, submitMessage,
  type DeskIntent, type DeskRequest, type DeskResult, type DeskSession, type DeskSessionDetail,
  type PendingCreation, type PendingSubmission,
} from "@/lib/desk"
import { formatTime } from "@/lib/snapshot"
import type { Tone } from "@/lib/tones"

/**
 * 대화 창구 (local-operations-desk-001 Part C). The local front door: the user writes here, the
 * existing conductor/Codex execution path answers, and this screen shows only what the server
 * durably recorded.
 *
 * Boundaries this screen keeps:
 * - a `request` is an ACCEPTED PROPOSAL, never a dispatched implementation. Its successful result
 *   is `needs_spec`: an objective and acceptance criteria that still need the owner's fixed
 *   specification and the existing Fleet admission before any work happens;
 * - a stored answer is unverified conversation context (the server says so in `authority`), not an
 *   approval, a specification or an operation manifest;
 * - nothing is called "sent" or "succeeded" without an authoritative server response. Anything that
 *   is not an explicit 4xx — a rejected fetch, the deadline, a 503 — leaves the outcome unknown, so
 *   BOTH a message (id + body) and a session creation (id + title) are frozen in local storage
 *   before the POST and retried unchanged, and the desk replays its stored row instead of creating
 *   a second request or a second provider call. There is no way to drop an unresolved identity
 *   here: only the server's own answer ends it;
 * - the flow picture marks only stages the server actually recorded; later stages stay 예정/미확인;
 * - no model, base revision, command or budget control exists here. The base revision is the
 *   owner's configured one, captured per request and shown as provenance only;
 * - history reads (poll, manual refresh, post-send) run one at a time on a single chain and each
 *   carries a number, so an older answer can never replace newer history, and an unmounted screen
 *   is never written to.
 */
type Notice = { tone: Tone; title: string; text: string; detail?: string }

/** What is currently shown for one session, kept per session id so a selection never clears it. */
type SessionHistory = { session_id: string; detail: DeskSessionDetail | null; notice: Notice | null }

const STORAGE_NOTICE: Notice = {
  tone: "error",
  title: "보내지 않았습니다",
  text: "이 브라우저가 요청 내용을 저장하지 못해 보내지 않았습니다. 저장을 막는 설정(시크릿 모드·사이트 데이터 차단·저장 공간 부족)을 풀고 다시 시도하세요.",
  detail: "식별자와 내용을 새로고침 후에도 남길 수 없으면, 같은 요청을 다시 보내는 것이 안전하지 않습니다.",
}

const STATUS_INFO: Record<string, { label: string; tone: Tone; note: string }> = {
  queued: { label: "접수됨 · 대기", tone: "warning", note: "PG 에 저장됨 · 창구 실행기가 순서대로 처리 · 자동 재시도 없음" },
  dispatching: { label: "처리 중", tone: "warning", note: "소유 토큰 보유 · 외부 작업 시작 전 구간 포함 · 결과 기록 없음" },
  answered: { label: "답변 완료", tone: "success", note: "상담 답변 · 검증된 사실이 아니라 대화 맥락 · 승인·명세 아님" },
  needs_spec: { label: "요청 접수 · 명세 필요", tone: "success", note: "제안된 목표로 접수됨 · 구현이 배정된 것이 아님 · 소유자 고정 명세와 Fleet admission 이 남음" },
  failed: { label: "실패", tone: "error", note: "고정 사유 코드로 기록됨 · 자동 재시도 없음" },
  needs_reconciliation: { label: "조정 필요", tone: "unknown", note: "정산·발행 증거가 확정되지 않음 · 성공도 실패도 아님 · 소유자 확인 필요" },
}

function statusInfo(status: string) {
  return STATUS_INFO[status] ?? { label: `${status} (정의되지 않은 상태)`, tone: "unknown" as Tone, note: "이 화면이 모르는 상태 값 · 저장된 그대로 표시" }
}

const INTENTS: Array<{ id: DeskIntent; label: string; note: string }> = [
  { id: "consult", label: "상담", note: "질문하고 답변을 받습니다. 작업이 만들어지지 않습니다." },
  { id: "request", label: "요청", note: "하고 싶은 일을 제안으로 접수합니다. 바로 구현되지 않으며 목표·수용 기준 초안을 받습니다." },
]

/** Identifiers, reason codes and server wording live here, out of the plain sentence above them. */
function Details({ children }: { children: ReactNode }) {
  return (
    <details className="mt-1 min-w-0 text-xs text-muted-foreground">
      <summary className="cursor-pointer">자세히</summary>
      <div className="mt-1 flex min-w-0 flex-col gap-1 break-words">{children}</div>
    </details>
  )
}

function NoticeAlert({ notice, icon, live }: { notice: Notice; icon?: ReactNode; live?: boolean }) {
  return (
    <Alert variant={notice.tone === "error" ? "destructive" : "default"} aria-live={live ? "polite" : undefined}>
      {icon}
      <AlertTitle>{notice.title}</AlertTitle>
      <AlertDescription className="break-words">
        {notice.text}
        {notice.detail ? <Details>{notice.detail}</Details> : null}
      </AlertDescription>
    </Alert>
  )
}

/** The five conversation stages; only the first ones are recorded by this desk. */
function Flow({ request }: { request: DeskRequest | null }) {
  const status = request?.status
  const recorded = status != null
  const answered = status === "answered" || status === "needs_spec"
  const stages: Array<{ title: string; state: string; tone: Tone }> = [
    { title: "1. 사용자", state: recorded ? "작성·전송 기록됨" : "작성 중", tone: recorded ? "success" : "neutral" },
    { title: "2. 창구", state: recorded ? "PG 에 저장됨 (접수)" : "미접수", tone: recorded ? "success" : "neutral" },
    { title: "3. 지휘자 검토", state: status === "queued" ? "대기" : status === "dispatching" ? "진행 중" : answered ? "응답 기록됨" : status ? "종료 상태 기록됨" : "미시작", tone: answered ? "success" : status === "queued" || status === "dispatching" ? "warning" : status ? "error" : "neutral" },
    { title: "4. 명세", state: status === "needs_spec" ? "초안 받음 · 소유자 고정 명세 필요" : "이 화면에서 기록하지 않음", tone: "unknown" },
    { title: "5. 팀원 작업", state: "이 창구가 시작하지 않음 · Fleet admission 은 소유자 권한", tone: "unknown" },
  ]
  return (
    <ol className="grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-5" aria-label="대화 흐름">
      {stages.map((stage) => (
        <li key={stage.title} className="min-w-0 rounded-lg border p-2 text-xs">
          <div className="font-medium break-words">{stage.title}</div>
          <StatusBadge tone={stage.tone} className="mt-1">{stage.state}</StatusBadge>
        </li>
      ))}
    </ol>
  )
}

function Provenance({ request }: { request: DeskRequest }) {
  const { base_revision, task_id, execution_ref, correlation_id } = request.provenance
  const value = (text: string | null) => (text ? <span className="font-mono break-all">{text}</span> : <span className="text-unknown">기록 없음</span>)
  return (
    <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-2 gap-y-0.5 text-xs text-muted-foreground">
      <dt>기준 revision</dt><dd className="min-w-0">{value(base_revision ? base_revision.slice(0, 12) : null)}</dd>
      <dt>작업 ID</dt><dd className="min-w-0">{value(task_id)}</dd>
      <dt>실행 기록</dt><dd className="min-w-0">{value(execution_ref)}</dd>
      <dt>상관 ID</dt><dd className="min-w-0">{value(correlation_id)}</dd>
    </dl>
  )
}

function Turn({ request }: { request: DeskRequest }) {
  const info = statusInfo(request.status)
  const answer = request.answer
  return (
    <li className="min-w-0">
      <Card size="sm" className="min-w-0">
        <CardHeader>
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <StatusBadge tone={info.tone} title={info.note}>{info.label}</StatusBadge>
            <StatusBadge tone="neutral">{request.intent === "request" ? "요청 (제안)" : "상담"}</StatusBadge>
            <span className="text-xs text-muted-foreground">{formatTime(request.created_at)}</span>
            {request.reason_code ? <StatusBadge tone="error">사유 {request.reason_code}</StatusBadge> : null}
          </div>
          <CardTitle className="text-sm font-normal whitespace-pre-wrap break-words">{request.text}</CardTitle>
          <CardDescription className="break-words">{info.note}</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-2">
          {answer ? (
            <div className="flex min-w-0 flex-col gap-2 rounded-lg bg-muted/40 p-2">
              <p className="whitespace-pre-wrap break-words text-sm">{answer.answer}</p>
              {answer.objective ? (
                <div className="text-xs"><span className="font-medium">제안된 목표</span> · 구현 배정 아님<p className="whitespace-pre-wrap break-words">{answer.objective}</p></div>
              ) : null}
              {answer.acceptance_criteria.length ? (
                <div className="text-xs"><span className="font-medium">수용 기준 초안</span><ul className="list-disc pl-4">{answer.acceptance_criteria.map((item) => <li key={item} className="break-words">{item}</li>)}</ul></div>
              ) : null}
              {answer.questions.length ? (
                <div className="text-xs"><span className="font-medium">확인이 필요한 질문</span><ul className="list-disc pl-4">{answer.questions.map((item) => <li key={item} className="break-words">{item}</li>)}</ul></div>
              ) : null}
              <p className="text-xs text-unknown break-words">검증되지 않은 대화 맥락 · 승인·명세 아님</p>
            </div>
          ) : (
            <p className="text-xs text-muted-foreground">저장된 답변 없음 {request.status === "queued" || request.status === "dispatching" ? "· 아직 처리 중" : "· 이 요청에는 답변이 기록되지 않았습니다"}</p>
          )}
          {/* Receipt identifiers and the server's own authority wording stay folded away. */}
          <Details>
            {answer?.authority ? <span>{answer.authority}</span> : null}
            <span className="font-mono break-all">요청 ID {request.request_id}</span>
            <Provenance request={request} />
          </Details>
        </CardContent>
      </Card>
    </li>
  )
}

export function DeskView() {
  const titleId = useId()
  const textId = useId()
  const [sessions, setSessions] = useState<DeskSession[] | null>(null)
  const [listNotice, setListNotice] = useState<Notice | null>(null)
  const [selected, setSelected] = useState<string | null>(() => loadSelected())
  const [history, setHistory] = useState<SessionHistory | null>(null)
  const [pending, setPending] = useState<PendingSubmission | null>(() => loadPending())
  const [creation, setCreation] = useState<PendingCreation | null>(() => loadPendingCreation())
  const [notice, setNotice] = useState<Notice | null>(null)
  const [title, setTitle] = useState("")
  const [text, setText] = useState("")
  const [intent, setIntent] = useState<DeskIntent>("consult")
  const [busy, setBusy] = useState(false)

  // Refs are written in effects and handlers only, never while rendering.
  const alive = useRef(true)
  const pendingRef = useRef(pending)
  const creationRef = useRef(creation)
  // Every history read takes the next number and runs after the previous one on this single chain,
  // so reads never overlap and an older answer is dropped instead of replacing newer history.
  const issued = useRef(0)
  const applied = useRef(0)
  const chain = useRef<Promise<void>>(Promise.resolve())

  useEffect(() => { alive.current = true; return () => { alive.current = false } }, [])
  useEffect(() => { pendingRef.current = pending }, [pending])
  useEffect(() => { creationRef.current = creation }, [creation])

  /** Run `task` after every earlier read; it therefore never touches state synchronously. */
  const enqueue = useCallback((task: () => Promise<void>): Promise<void> => {
    const settled = chain.current.then(task, task).catch(() => {})
    chain.current = settled
    return settled
  }, [])

  const refuse = useCallback((result: Extract<DeskResult<unknown>, { ok: false }>, title_: string): Notice => ({
    tone: result.kind === "refused" ? "error" : "unknown",
    title: title_,
    text: result.message,
    detail: `사유 ${result.code} · 상태 ${result.status ?? "응답 없음"}`,
  }), [])

  const loadSessions = useCallback(() => enqueue(async () => {
    const result = await listSessions()
    if (!alive.current) return
    if (result.ok) {
      setSessions(result.value.sessions)
      setListNotice(result.value.truncated ? { tone: "warning", title: "대화 목록이 잘렸습니다", text: "최근 50개까지만 표시합니다. 이전 대화는 서버에 그대로 남아 있습니다." } : null)
      // A creation the server already holds is decided: the frozen identity is released.
      const held = creationRef.current
      if (held && result.value.sessions.some((session) => session.session_id === held.session_id)) {
        savePendingCreation(null)
        creationRef.current = null
        setCreation(null)
      }
      return
    }
    // The previous list stays on screen; it is explicitly marked as not current.
    setListNotice(refuse(result, "대화 목록을 갱신하지 못했습니다"))
  }), [enqueue, refuse])

  const readHistory = useCallback((sessionId: string, signal?: AbortSignal) => {
    const seq = ++issued.current
    return enqueue(async () => {
      if (!alive.current || signal?.aborted || seq <= applied.current) return
      const result = await readSessionDetail(sessionId, signal)
      if (!alive.current || signal?.aborted || seq <= applied.current) return
      applied.current = seq
      if (!result.ok) {
        // The last records stay visible for this session, marked as not current.
        setHistory((previous) => ({ session_id: sessionId, detail: previous?.session_id === sessionId ? previous.detail : null,
          notice: refuse(result, "대화를 갱신하지 못했습니다") }))
        return
      }
      setHistory({ session_id: sessionId, detail: result.value, notice: null })
      // A pending submission that the server already holds is authoritative: stop retrying it.
      const held = pendingRef.current
      if (held && held.session_id === sessionId
        && result.value.requests.some((request) => request.request_id === held.request_id)) {
        savePending(null)
        pendingRef.current = null
        setPending(null)
      }
    })
  }, [enqueue, refuse])

  useEffect(() => { void loadSessions() }, [loadSessions])

  // Poll the selected session only, only while the page is visible. The cleanup aborts the call in
  // flight and stops the timer, so an unmounted or re-selected screen is never written to.
  useEffect(() => {
    if (!selected) return
    const controller = new AbortController()
    let timer: number | undefined
    let stopped = false
    const tick = () => {
      if (stopped) return
      const read = document.hidden ? Promise.resolve() : readHistory(selected, controller.signal)
      void read.then(() => {
        if (stopped) return
        timer = window.setTimeout(tick, DESK_POLL_MS)
      })
    }
    tick()
    return () => { stopped = true; controller.abort(); if (timer !== undefined) window.clearTimeout(timer) }
  }, [selected, readHistory])

  const select = (sessionId: string | null) => {
    setSelected(sessionId)
    saveSelected(sessionId)
    setNotice(null)
  }

  const create = async (submission: PendingCreation) => {
    setBusy(true)
    // Frozen before the POST: id AND title survive a reload while the outcome is unknown.
    if (!savePendingCreation(submission)) {
      setBusy(false)
      setNotice(STORAGE_NOTICE)
      return
    }
    creationRef.current = submission
    setCreation(submission)
    const result = await createSession(submission.session_id, submission.title)
    if (!alive.current) return
    setBusy(false)
    const release = () => { savePendingCreation(null); creationRef.current = null; setCreation(null) }
    if (result.ok) {
      // A 200 replay of the same id and title is the same durable session, not a second one.
      release()
      setTitle("")
      select(result.value.session_id)
      setNotice({ tone: "success", title: result.replayed ? "이미 있는 대화입니다" : "대화를 만들었습니다", text: result.value.title,
        detail: result.replayed ? "같은 식별자의 기록이 재생되었습니다 (새 대화가 생기지 않음)." : undefined })
      void loadSessions()
      return
    }
    if (result.kind === "refused") {
      // Only an explicit 4xx decides it; then the identity is released for a corrected title.
      release()
      setNotice(refuse(result, "대화를 만들지 못했습니다"))
      return
    }
    setNotice({ tone: "unknown", title: "대화가 만들어졌는지 알 수 없습니다",
      text: "같은 이름으로 다시 시도하세요. 서버가 이미 저장했다면 그 대화가 그대로 보이고 두 개가 되지 않습니다.",
      detail: `${result.message} (사유 ${result.code}${result.status != null ? ` · 상태 ${result.status}` : ""}) · 대화 ID ${submission.session_id}` })
  }

  const onCreate = () => {
    if (busy) return
    const held = creationRef.current
    const wanted = held?.title ?? title.trim()
    if (!wanted) return
    void create(held
      ? { ...held, attempts: held.attempts + 1 }
      : { session_id: newId(), title: wanted, attempts: 1, first_attempt_at: new Date().toISOString() })
  }

  const send = async (submission: PendingSubmission) => {
    setBusy(true)
    // Frozen before the POST: a reload during an unknown outcome still finds the identity and body.
    if (!savePending(submission)) {
      setBusy(false)
      setNotice(STORAGE_NOTICE)
      return
    }
    pendingRef.current = submission
    setPending(submission)
    const result = await submitMessage(submission)
    if (!alive.current) return
    setBusy(false)
    const release = () => { savePending(null); pendingRef.current = null; setPending(null) }
    if (result.ok) {
      release()
      setText("")
      setNotice({ tone: "success", title: result.replayed ? "이미 접수된 요청입니다" : "접수되었습니다",
        text: submission.intent === "request" ? "제안으로 접수되었습니다. 구현이 시작된 것은 아니며 목표·수용 기준 초안을 기다립니다." : "상담으로 접수되었습니다. 답변을 기다립니다.",
        detail: `요청 ID ${submission.request_id}${result.replayed ? " · 같은 기록이 재생되었습니다 (새 호출 없음)" : ""}` })
      void readHistory(submission.session_id)
      void loadSessions()
      return
    }
    if (result.kind === "refused") {
      // Authoritative: the server read the body and decided. Nothing is retried under this identity.
      release()
      setNotice(refuse(result, "접수되지 않았습니다"))
      return
    }
    setNotice({ tone: "unknown", title: "전송 결과를 알 수 없습니다",
      text: "저장되었을 수도 있습니다. 아래 버튼으로 같은 내용을 다시 보내면 중복 접수되지 않습니다.",
      detail: `${result.message} (사유 ${result.code}${result.status != null ? ` · 상태 ${result.status}` : ""}) · 요청 ID ${submission.request_id}` })
  }

  const onSend = () => {
    const body = text.trim()
    if (!selected || !body || busy || pending) return
    void send({ session_id: selected, request_id: newId(), intent, text: body,
      attempts: 1, first_attempt_at: new Date().toISOString() })
  }

  const onRetry = () => {
    if (!pending || busy) return
    void send({ ...pending, attempts: pending.attempts + 1 })
  }

  const current = history && history.session_id === selected ? history : null
  const detail = current?.detail ?? null
  const detailNotice = current?.notice ?? null
  const selectedSession = detail?.session ?? sessions?.find((session) => session.session_id === selected) ?? null
  const requests = detail?.requests ?? []
  const latest = requests.length ? requests[requests.length - 1] : null
  const turnOpen = requests.some((request) => request.status === "queued" || request.status === "dispatching")
  const stale = detailNotice != null && detail != null

  return (
    <div className="flex min-w-0 flex-col gap-4">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0">
          <h2 className="text-lg font-semibold inline-flex items-center gap-2"><MessageSquare aria-hidden="true" className="size-4" />대화 창구</h2>
          <p className="text-sm text-muted-foreground break-words">이 컴퓨터에서만 쓰는 창구입니다. 요청은 제안으로 접수될 뿐 바로 구현되지 않으며, 답변은 검증된 사실이 아니라 대화 맥락입니다.</p>
        </div>
        <Button size="sm" variant="outline" onClick={() => { void loadSessions(); if (selected) void readHistory(selected) }} disabled={busy} aria-busy={busy}>
          <RefreshCw aria-hidden="true" />지금 갱신
        </Button>
      </div>

      {pending ? (
        <Alert><AlertTriangle aria-hidden="true" /><AlertTitle>결과가 확정되지 않은 요청이 있습니다</AlertTitle>
          <AlertDescription className="break-words">
            저장되었는지 알 수 없어, 같은 내용으로만 다시 보냅니다. 서버가 이미 받았다면 그 기록이 그대로 보이고 두 번 접수되지 않습니다.
            <span className="mt-2 flex flex-wrap gap-2">
              <Button size="sm" onClick={onRetry} disabled={busy}>같은 요청 다시 보내기</Button>
            </span>
            <Details>
              <span className="font-mono break-all">요청 ID {pending.request_id}</span>
              <span>시도 {pending.attempts}회 · 최초 {formatTime(pending.first_attempt_at)}</span>
              <span>서버가 이 요청을 기록한 것이 확인되면 이 안내는 저절로 사라집니다.</span>
            </Details>
          </AlertDescription></Alert>
      ) : null}
      {notice ? <NoticeAlert notice={notice} live /> : null}
      {listNotice ? <NoticeAlert notice={listNotice} icon={<CircleHelp aria-hidden="true" />} /> : null}

      <div className="grid min-w-0 grid-cols-1 gap-4 lg:grid-cols-[minmax(0,280px)_minmax(0,1fr)]">
        <section aria-label="대화 목록" className="flex min-w-0 flex-col gap-2">
          {creation ? (
            <Alert><AlertTriangle aria-hidden="true" /><AlertTitle>대화가 만들어졌는지 확인되지 않았습니다</AlertTitle>
              <AlertDescription className="break-words">
                같은 이름으로만 다시 시도합니다. 서버가 이미 저장했다면 그 대화가 그대로 보이고 두 개가 되지 않습니다.
                <Details>
                  <span className="font-mono break-all">대화 ID {creation.session_id}</span>
                  <span>제목 {creation.title} · 시도 {creation.attempts}회 · 최초 {formatTime(creation.first_attempt_at)}</span>
                </Details>
              </AlertDescription></Alert>
          ) : null}
          <div className="flex flex-wrap items-end gap-2">
            <div className="min-w-0 flex-1">
              <label htmlFor={titleId} className="text-xs text-muted-foreground">새 대화 제목 (최대 {DESK_TITLE_MAX}자)</label>
              <Input id={titleId} value={creation ? creation.title : title} maxLength={DESK_TITLE_MAX} disabled={creation != null}
                onChange={(event) => setTitle(event.target.value)} placeholder="예: 관측소 화면 정리" />
            </div>
            <Button onClick={onCreate} disabled={busy || (creation == null && !title.trim())} aria-busy={busy}>
              <Plus aria-hidden="true" />{creation ? "다시 만들기" : "만들기"}
            </Button>
          </div>
          {sessions === null ? (
            <p className="rounded-lg border p-3 text-sm text-unknown">대화 목록을 아직 읽지 못했습니다 (0개가 아니라 확인 불가).</p>
          ) : sessions.length === 0 ? (
            <p className="rounded-lg border p-3 text-sm text-muted-foreground"><Inbox aria-hidden="true" className="mr-1 inline size-4" />저장된 대화가 없습니다 (비어 있음).</p>
          ) : (
            <ul className="flex max-h-[28rem] min-w-0 flex-col gap-1 overflow-y-auto">
              {sessions.map((session) => (
                <li key={session.session_id} className="min-w-0">
                  <Button variant={selected === session.session_id ? "secondary" : "ghost"} className="h-auto w-full justify-start py-2 text-left"
                    aria-current={selected === session.session_id ? "true" : undefined} onClick={() => select(session.session_id)}>
                    <span className="flex min-w-0 flex-col">
                      <span className="break-words">{session.title}</span>
                      <span className="text-xs text-muted-foreground">요청 {session.request_count}건 · 마지막 {formatTime(session.updated_at)}</span>
                    </span>
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section aria-label="대화 내용" className="flex min-w-0 flex-col gap-3">
          {!selected ? (
            <Alert><Users aria-hidden="true" /><AlertTitle>대화를 선택하세요</AlertTitle>
              <AlertDescription>왼쪽에서 대화를 고르거나 새 대화를 만들면 여기에서 상담·요청을 보낼 수 있습니다.</AlertDescription></Alert>
          ) : (
            <>
              <div className="flex min-w-0 flex-wrap items-center gap-2">
                <h3 className="text-base font-semibold break-words">{selectedSession?.title ?? "제목 확인 불가"}</h3>
                {stale ? <StatusBadge tone="unknown">이전 응답 · 현재 상태 아님</StatusBadge> : null}
                {detail == null && !detailNotice ? <StatusBadge tone="warning">불러오는 중</StatusBadge> : null}
                {detail?.max_requests != null ? <span className="text-xs text-muted-foreground">요청 {requests.length} / 상한 {detail.max_requests}</span> : null}
              </div>
              {detailNotice ? (
                <NoticeAlert notice={detail
                  ? { ...detailNotice, text: `${detailNotice.text} 아래 내용은 마지막으로 받은 기록이며 현재 상태가 아닙니다.` }
                  : detailNotice} />
              ) : null}

              <Card size="sm" className="min-w-0">
                <CardHeader>
                  <CardTitle className="text-sm inline-flex items-center gap-2"><ShieldCheck aria-hidden="true" className="size-4" />사용자 → 창구 → 지휘자 검토 → 명세 → 팀원 작업</CardTitle>
                  <CardDescription>서버가 실제로 기록한 단계만 표시합니다. 뒤 단계는 이 창구가 시작하지 않습니다.</CardDescription>
                </CardHeader>
                <CardContent><Flow request={latest} /></CardContent>
              </Card>

              {requests.length === 0 && detail ? (
                <p className="rounded-lg border p-3 text-sm text-muted-foreground">이 대화에는 아직 요청이 없습니다 (비어 있음).</p>
              ) : (
                <ul className="flex min-w-0 flex-col gap-2">{requests.map((request) => <Turn key={request.request_id} request={request} />)}</ul>
              )}

              <div className="flex min-w-0 flex-col gap-2 rounded-lg border p-3">
                <fieldset className="flex flex-wrap items-center gap-3">
                  <legend className="text-xs text-muted-foreground">무엇을 보낼지 고르세요</legend>
                  {INTENTS.map((option) => (
                    <label key={option.id} className="inline-flex items-center gap-1.5 text-sm" title={option.note}>
                      <input type="radio" name="desk-intent" value={option.id} checked={intent === option.id} onChange={() => setIntent(option.id)} />
                      <span>{option.label}</span>
                    </label>
                  ))}
                  <span className="text-xs text-muted-foreground break-words">{INTENTS.find((option) => option.id === intent)?.note}</span>
                </fieldset>
                <label htmlFor={textId} className="text-xs text-muted-foreground">내용 (최대 {DESK_TEXT_MAX}자 · 남은 글자 {DESK_TEXT_MAX - text.length})</label>
                <textarea id={textId} value={text} maxLength={DESK_TEXT_MAX} rows={4} onChange={(event) => setText(event.target.value)}
                  className="w-full min-w-0 rounded-md border bg-transparent px-3 py-2 text-base shadow-xs outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50 md:text-sm"
                  placeholder="궁금한 점이나 하고 싶은 일을 적어 주세요." />
                <div className="flex flex-wrap items-center gap-2">
                  <Button onClick={onSend} disabled={busy || !text.trim() || pending != null || turnOpen} aria-busy={busy}><Send aria-hidden="true" />보내기</Button>
                  <span className="text-xs text-muted-foreground break-words">
                    {pending ? "결과가 확정되지 않은 요청이 있어 새 요청을 보내지 않습니다." : turnOpen ? "처리 중인 요청이 끝나야 다음 요청을 받습니다 (대화 순서 유지)." : "한 대화에서 한 번에 하나씩 처리됩니다."}
                  </span>
                </div>
              </div>
            </>
          )}
        </section>
      </div>

      <p className="text-xs text-muted-foreground break-words">
        읽는 법: '접수됨'은 서버에 저장되었다는 뜻이고, '요청 접수 · 명세 필요'는 제안이 받아들여졌다는 뜻이지 구현이 배정되었다는 뜻이 아닙니다. 답변은 검증되지 않은 대화 맥락입니다. 결과가 확정되지 않은 요청은 같은 내용으로만 다시 보내며, 대화 기록은 새로고침 후에도 그대로 남습니다.
      </p>
    </div>
  )
}
