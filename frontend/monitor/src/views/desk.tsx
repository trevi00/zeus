import { useCallback, useEffect, useId, useRef, useState } from "react"
import { AlertTriangle, CircleHelp, Inbox, MessageSquare, Plus, RefreshCw, Send, ShieldCheck, Users } from "lucide-react"

import { StatusBadge } from "@/components/status-badge"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import {
  DESK_POLL_MS, DESK_TEXT_MAX, DESK_TITLE_MAX, createSession, listSessions, loadPending, loadSelected,
  newId, readSessionDetail, savePending, saveSelected, submitMessage,
  type DeskIntent, type DeskRequest, type DeskResult, type DeskSession, type DeskSessionDetail, type PendingSubmission,
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
 * - nothing is called "sent" or "succeeded" without an authoritative server response. A rejected
 *   or timed-out fetch keeps its identity and body locally and is retried with the SAME id, so the
 *   desk replays the stored row instead of creating a second request or a second provider call;
 * - the flow picture marks only stages the server actually recorded; later stages stay 예정/미확인;
 * - no model, base revision, command or budget control exists here. The base revision is the
 *   owner's configured one, captured per request and shown as provenance only.
 */
type Notice = { tone: Tone; title: string; text: string }

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
              <p className="text-xs text-unknown break-words">{answer.authority || "모델 답변 · 검증되지 않은 대화 맥락 · 승인·명세 아님"}</p>
            </div>
          ) : (
            <p className="text-xs text-muted-foreground">저장된 답변 없음 {request.status === "queued" || request.status === "dispatching" ? "· 아직 처리 중" : "· 이 요청에는 답변이 기록되지 않았습니다"}</p>
          )}
          <Provenance request={request} />
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
  const [detail, setDetail] = useState<DeskSessionDetail | null>(null)
  const [detailNotice, setDetailNotice] = useState<Notice | null>(null)
  const [pending, setPending] = useState<PendingSubmission | null>(() => loadPending())
  const [notice, setNotice] = useState<Notice | null>(null)
  const [title, setTitle] = useState("")
  const [text, setText] = useState("")
  const [intent, setIntent] = useState<DeskIntent>("consult")
  const [busy, setBusy] = useState(false)
  // Stable identities: the same id is reused for every attempt of the same content, so an uncertain
  // submission is repeated, never duplicated. A new id is minted only after an authoritative outcome.
  const requestIdRef = useRef(pending?.request_id ?? newId())
  const sessionIdRef = useRef(newId())
  // The selection a response must still match before it is written into the screen.
  const selectedRef = useRef(selected)
  selectedRef.current = selected
  // The unresolved submission as the async callbacks must see it, without stale closures.
  const pendingRef = useRef(pending)
  pendingRef.current = pending

  const refuse = useCallback((result: Extract<DeskResult<unknown>, { ok: false }>, title_: string): Notice => ({
    tone: result.kind === "refused" ? "error" : "unknown",
    title: `${title_} · ${result.status ?? "응답 없음"}`,
    text: result.kind === "refused" ? `${result.message} (사유 ${result.code})` : `${result.message} 서버가 저장했는지 알 수 없습니다.`,
  }), [])

  const loadSessions = useCallback(async () => {
    const result = await listSessions()
    if (result.ok) {
      setSessions(result.value.sessions)
      setListNotice(result.value.truncated ? { tone: "warning", title: "대화 목록이 잘렸습니다", text: "최근 50개까지만 표시합니다. 이전 대화는 서버에 그대로 남아 있습니다." } : null)
      return
    }
    // The previous list stays on screen; it is explicitly marked as not current.
    setListNotice(refuse(result, "대화 목록을 갱신하지 못했습니다"))
  }, [refuse])

  const loadDetail = useCallback(async (sessionId: string, signal?: AbortSignal) => {
    const result = await readSessionDetail(sessionId, signal)
    if (selectedRef.current !== sessionId) return
    if (result.ok) {
      setDetail(result.value)
      setDetailNotice(null)
      // A pending submission that the server already holds is authoritative: stop retrying it.
      const current = pendingRef.current
      if (current && current.session_id === sessionId
        && result.value.requests.some((request) => request.request_id === current.request_id)) {
        savePending(null)
        setPending(null)
        requestIdRef.current = newId()
      }
      return
    }
    setDetailNotice(refuse(result, "대화를 갱신하지 못했습니다"))
  }, [refuse])

  useEffect(() => { void loadSessions() }, [loadSessions])

  // Poll the selected session only, only while the page is visible, and abort on a changed
  // selection so a stale response can never overwrite a newer one.
  useEffect(() => {
    if (!selected) { setDetail(null); setDetailNotice(null); return }
    const controller = new AbortController()
    let timer: number | undefined
    let cancelled = false
    const tick = async () => {
      if (cancelled) return
      // One call at a time: the next tick is scheduled only after this one settles, so polls
      // never overlap, and after the cleanup nothing is scheduled at all.
      if (!document.hidden) await loadDetail(selected, controller.signal)
      if (cancelled) return
      timer = window.setTimeout(() => void tick(), DESK_POLL_MS)
    }
    void tick()
    return () => { cancelled = true; controller.abort(); if (timer) window.clearTimeout(timer) }
  }, [selected, loadDetail])

  const select = (sessionId: string | null) => {
    setSelected(sessionId)
    saveSelected(sessionId)
    setDetail(null)
    setNotice(null)
  }

  const onCreate = async () => {
    const wanted = title.trim()
    if (!wanted || busy) return
    setBusy(true)
    const result = await createSession(sessionIdRef.current, wanted)
    setBusy(false)
    if (result.ok) {
      // A 200 replay of the same id and title is the same durable session, not a second one.
      sessionIdRef.current = newId()
      setTitle("")
      select(result.value.session_id)
      setNotice({ tone: "success", title: result.replayed ? "이미 있는 대화입니다 (같은 기록 재생)" : "대화를 만들었습니다", text: `${result.value.title} · 서버에 저장됨` })
      void loadSessions()
      return
    }
    // The id is kept on an uncertain outcome so the retry is the same creation, not a new one.
    if (result.kind === "refused") sessionIdRef.current = newId()
    setNotice(refuse(result, "대화를 만들지 못했습니다"))
  }

  const send = async (submission: PendingSubmission) => {
    setBusy(true)
    // Persisted BEFORE the call: a reload during an unknown outcome still finds the identity and body.
    savePending(submission)
    setPending(submission)
    const result = await submitMessage(submission)
    setBusy(false)
    if (result.ok) {
      savePending(null)
      setPending(null)
      requestIdRef.current = newId()
      setText("")
      setNotice({ tone: "success", title: result.replayed ? "이미 접수된 요청입니다 (같은 기록 재생)" : "접수되었습니다", text: submission.intent === "request" ? "제안으로 접수되었습니다. 구현이 시작된 것이 아니며, 목표·수용 기준 초안을 기다립니다." : "상담으로 접수되었습니다. 답변을 기다립니다." })
      void loadDetail(submission.session_id)
      void loadSessions()
      return
    }
    if (result.kind === "refused") {
      // Authoritative: the server decided. Nothing is retried under this identity.
      savePending(null)
      setPending(null)
      if (result.code === "request_conflict") requestIdRef.current = newId()
      setNotice(refuse(result, "접수되지 않았습니다"))
      return
    }
    setNotice({ tone: "unknown", title: "전송 결과를 알 수 없습니다",
      text: `${result.message} 같은 식별자와 같은 내용으로만 다시 보낼 수 있습니다. 서버가 이미 저장했다면 같은 기록이 재생되고 새 호출은 생기지 않습니다.` })
  }

  const onSend = () => {
    const body = text.trim()
    if (!selected || !body || busy) return
    void send({ session_id: selected, request_id: requestIdRef.current, intent, text: body,
      attempts: 1, first_attempt_at: new Date().toISOString() })
  }

  const onRetry = () => {
    if (!pending || busy) return
    void send({ ...pending, attempts: pending.attempts + 1 })
  }

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
          <p className="text-sm text-muted-foreground break-words">이 컴퓨터에서만 쓰는 창구입니다. 요청은 제안으로 접수될 뿐 바로 구현되지 않으며, 답변은 검증된 사실이 아니라 대화 맥락입니다. 모델·기준·명령·예산을 고르는 항목은 없습니다.</p>
        </div>
        <Button size="sm" variant="outline" onClick={() => { void loadSessions(); if (selected) void loadDetail(selected) }} disabled={busy} aria-busy={busy}>
          <RefreshCw aria-hidden="true" />지금 갱신
        </Button>
      </div>

      {pending ? (
        <Alert><AlertTriangle aria-hidden="true" /><AlertTitle>보낸 결과가 확정되지 않은 요청이 있습니다</AlertTitle>
          <AlertDescription className="break-words">
            이 요청은 저장되었을 수도, 되지 않았을 수도 있습니다. 같은 식별자와 같은 내용으로만 다시 보냅니다 (시도 {pending.attempts}회 · 최초 {formatTime(pending.first_attempt_at)}).
            <span className="mt-2 flex flex-wrap gap-2">
              <Button size="sm" onClick={onRetry} disabled={busy}>같은 요청 다시 보내기</Button>
              <Button size="sm" variant="outline" onClick={() => { savePending(null); setPending(null) }} disabled={busy}>이 화면에서 지우기 (서버 상태는 그대로)</Button>
            </span>
          </AlertDescription></Alert>
      ) : null}
      {notice ? (
        <Alert variant={notice.tone === "error" ? "destructive" : "default"} aria-live="polite">
          <AlertTitle>{notice.title}</AlertTitle><AlertDescription className="break-words">{notice.text}</AlertDescription></Alert>
      ) : null}
      {listNotice ? (
        <Alert variant={listNotice.tone === "error" ? "destructive" : "default"}><CircleHelp aria-hidden="true" />
          <AlertTitle>{listNotice.title}</AlertTitle><AlertDescription className="break-words">{listNotice.text}</AlertDescription></Alert>
      ) : null}

      <div className="grid min-w-0 grid-cols-1 gap-4 lg:grid-cols-[minmax(0,280px)_minmax(0,1fr)]">
        <section aria-label="대화 목록" className="flex min-w-0 flex-col gap-2">
          <div className="flex flex-wrap items-end gap-2">
            <div className="min-w-0 flex-1">
              <label htmlFor={titleId} className="text-xs text-muted-foreground">새 대화 제목 (최대 {DESK_TITLE_MAX}자)</label>
              <Input id={titleId} value={title} maxLength={DESK_TITLE_MAX} onChange={(event) => setTitle(event.target.value)} placeholder="예: 관측소 화면 정리" />
            </div>
            <Button onClick={() => void onCreate()} disabled={busy || !title.trim()} aria-busy={busy}><Plus aria-hidden="true" />만들기</Button>
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
                <Alert variant={detailNotice.tone === "error" ? "destructive" : "default"}>
                  <AlertTitle>{detailNotice.title}</AlertTitle>
                  <AlertDescription className="break-words">{detailNotice.text}{detail ? " 아래 내용은 마지막으로 받은 기록이며 현재 상태가 아닙니다." : ""}</AlertDescription></Alert>
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
        읽는 법: '접수됨'은 서버에 저장되었다는 뜻이고 '요청 접수 · 명세 필요'는 제안이 받아들여졌다는 뜻이지 구현이 배정되었다는 뜻이 아닙니다. 답변은 검증되지 않은 대화 맥락이며 승인·명세·지식이 되지 않습니다. 전송 결과가 확정되지 않은 경우에는 같은 식별자와 같은 내용으로만 다시 보내며, 새로 호출하지 않습니다. 대화 기록은 PG 에 남아 새로고침 후에도 그대로 보입니다.
      </p>
    </div>
  )
}
