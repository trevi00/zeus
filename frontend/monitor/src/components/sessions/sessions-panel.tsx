import type { ReactNode } from "react"
import { Activity, AlertTriangle, ChevronDown, Layers, Monitor, Users } from "lucide-react"

import { KeyValue, StatCard } from "@/components/stat-card"
import { StatusBadge } from "@/components/status-badge"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Card, CardContent, CardHeader } from "@/components/ui/card"
import type { Label, LaneView, SessionRow, SessionsModel } from "@/lib/lane-sessions"
import { formatNumber, formatSeconds, formatTime } from "@/lib/snapshot"

// Presentation only: INV-LANE-SESSIONS-001 labels, ordering and truth states belong to SessionsModel.
const missing = "기록 없음"
const number = (value: number | null) => value === null ? "알 수 없음" : formatNumber(value)
const time = (value: string | null) => value === null ? missing : formatTime(value)

function ModelBadge({ value }: { value: Label }) {
  return <StatusBadge tone={value.tone} title={value.note}>{value.label}</StatusBadge>
}

function DetailGroup({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="min-w-0 rounded-lg border bg-background/60 p-3 [overflow-wrap:anywhere]">
      <h4 className="mb-3 text-sm font-semibold">{title}</h4>
      {children}
    </section>
  )
}

function SessionDetails({ row, screenNotice }: { row: SessionRow; screenNotice: string }) {
  const { operation, invocation, workerSession } = row
  return (
    <div className="grid min-w-0 gap-3 border-t bg-muted/20 p-3 md:grid-cols-2 xl:grid-cols-3">
      <DetailGroup title="실행">
        <KeyValue items={[
          ["실행 ID", <span className="font-mono text-xs">{row.id}</span>],
          ["역할", row.role],
          ["상태", <ModelBadge value={row.status} />],
          ["상태 설명", row.status.note],
          ["결정 판정", row.verdict ? <ModelBadge value={row.verdict} /> : missing],
          ["단계", row.phase ?? missing],
          ["세대 / 시도", `${number(row.lineage.generation)} / ${number(row.lineage.attempt)}`],
          ["경과", row.elapsed.text],
          ["시작 시각", time(row.elapsed.startedAt)],
          ["종료 시각", time(row.elapsed.endedAt)],
          ["소유 리스", <StatusBadge tone={row.liveness.tone} title="소유 리스는 진행 증거가 아님">{row.liveness.label}</StatusBadge>],
          ["리스 기한", time(row.liveness.until)],
        ]} />
        <p className="mt-3 text-xs text-muted-foreground">소유 리스는 진행 증거가 아님</p>
      </DetailGroup>
      <DetailGroup title="활동">
        <KeyValue items={[
          ["마지막 이벤트", row.activity.lastEvent ?? missing],
          ["순번", number(row.activity.sequence)],
          ["마지막 완료", row.activity.lastCompleted ?? missing],
          ["이벤트 시각", time(row.activity.occurredAt)],
          ["수집 시각", time(row.activity.collectedAt)],
          ["기록 경과", row.activity.ageText],
          ["형식 오류 수", number(row.activity.malformed)],
        ]} />
      </DetailGroup>
      <DetailGroup title="작업 (operation)">
        {operation ? <KeyValue items={[
          ["작업 ID", <span className="font-mono text-xs">{operation.id}</span>],
          ["상태", <ModelBadge value={operation.status} />],
          ["상태 설명", operation.status.note],
          ["사유 코드", operation.reasonCode ?? missing],
          ["리드 판정", <ModelBadge value={operation.lead} />],
          ["호출", operation.calls],
          ["인계", operation.handoffText],
        ]} /> : <p className="text-sm text-muted-foreground">{missing}</p>}
      </DetailGroup>
      <DetailGroup title="호출">
        {invocation ? <>
          <KeyValue items={[
            ["제공자", invocation.provider],
            ["전송", invocation.transport ?? missing],
            ["요청 모델", invocation.model],
            ["모델 출처", invocation.modelSource],
            ["응답 모델", invocation.reportedModel],
            ["사용량", invocation.usage],
            ["예약 상태", <ModelBadge value={invocation.statusLabel} />],
            ["단계", invocation.stage ?? missing],
            ["호출 수", number(invocation.count)],
            ["호출 경과", invocation.elapsedText],
          ]} />
          <div className="mt-3 flex min-w-0 flex-wrap gap-1.5" aria-label="호출 상태별 수">
            {invocation.byStatusLabels.map((entry) => <StatusBadge key={entry.status}>{entry.label} · {number(entry.count)}</StatusBadge>)}
          </div>
        </> : <p className="text-sm text-muted-foreground">{missing}</p>}
      </DetailGroup>
      <DetailGroup title="작업 세션">
        {workerSession ? <>
          <KeyValue items={[
            ["상태", <ModelBadge value={workerSession.state} />],
            ["버전", number(workerSession.version)],
            ["소유", workerSession.owner],
            ["다음 소유자", workerSession.nextOwner],
            ["다음 행동", workerSession.nextAction ?? missing],
            ["차단", workerSession.blockedText],
          ]} />
          <h5 className="mb-2 mt-4 text-xs font-medium text-muted-foreground">검토 기록</h5>
          {workerSession.reviews.length ? <ul className="space-y-2">
            {workerSession.reviews.map((review, index) => <li key={index} className="rounded-md border p-2 text-xs">
              <p className="font-mono">{review.decisionId ?? missing}</p>
              <p className="mt-1">{review.phase ?? missing} · {review.outcome ?? missing}</p>
            </li>)}
          </ul> : <p className="text-xs text-muted-foreground">{missing}</p>}
        </> : <p className="text-sm text-muted-foreground">{missing}</p>}
      </DetailGroup>
      <DetailGroup title="화면">
        <Monitor aria-hidden="true" className="mb-3 size-5 text-muted-foreground" />
        <p className="text-sm leading-relaxed text-muted-foreground">{screenNotice}</p>
      </DetailGroup>
    </div>
  )
}

function SessionItem({ row, screenNotice }: { row: SessionRow; screenNotice: string }) {
  return (
    <details className="group/session min-w-0 border-t first:border-t-0">
      <summary aria-label={`${row.kindLabel} ${row.id} 상세 보기`} className="flex min-w-0 cursor-pointer list-none items-start gap-3 p-4 hover:bg-muted/40 focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-ring [&::-webkit-details-marker]:hidden">
        <ChevronDown aria-hidden="true" className="mt-1 size-4 shrink-0 text-muted-foreground transition-transform group-open/session:rotate-180 motion-reduce:transition-none" />
        <div className="grid min-w-0 flex-1 gap-3 lg:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)_minmax(0,0.9fr)] [overflow-wrap:anywhere]">
          <div className="min-w-0 space-y-2">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-xs text-muted-foreground">{row.kindLabel}</span>
              <span className="font-mono text-xs" title={row.id}>{row.shortId}</span>
              <ModelBadge value={row.status} />
            </div>
            <p className="text-sm font-medium">{row.role} <span className="font-normal text-muted-foreground">· {row.phase ?? missing}</span></p>
            <p className="text-xs text-muted-foreground">세대 {number(row.lineage.generation)} · 시도 {number(row.lineage.attempt)}</p>
          </div>
          <div className="min-w-0 space-y-2">
            <StatusBadge tone={row.liveness.tone} title="소유 리스는 진행 증거가 아님">{row.liveness.label}</StatusBadge>
            <p className="text-xs"><span className="text-muted-foreground">마지막 활동 · </span>{row.activity.ageText}</p>
            <p className="text-xs"><span className="text-muted-foreground">경과 · </span>{row.elapsed.text}</p>
          </div>
          <div className="min-w-0 space-y-2">
            {row.operation ? <ModelBadge value={row.operation.lead} /> : <span className="text-xs text-muted-foreground">리드 판정 · {missing}</span>}
            <p className="text-xs text-muted-foreground">{row.invocation ? <>{row.invocation.provider} · {row.invocation.model}</> : missing}</p>
            <span className="text-xs text-muted-foreground underline decoration-dotted underline-offset-4">상세 보기</span>
          </div>
        </div>
      </summary>
      <SessionDetails row={row} screenNotice={screenNotice} />
    </details>
  )
}

function LaneSection({ lane, screenNotice }: { lane: LaneView; screenNotice: string }) {
  return (
    <section aria-label={`${lane.team} · ${lane.id}`} className="min-w-0">
      <Card className="min-w-0 gap-0 py-0">
        <CardHeader className="gap-3 border-b bg-muted/20 py-4 [overflow-wrap:anywhere]">
          <div className="flex min-w-0 flex-wrap items-start justify-between gap-3">
            <div className="min-w-0">
              <p className="mb-1 flex items-center gap-2 text-xs text-muted-foreground"><Users aria-hidden="true" className="size-3.5 shrink-0" />{lane.team}</p>
              <h3 className="font-mono text-base font-semibold">{lane.id}</h3>
            </div>
            <div className="min-w-0 space-y-1 text-xs">
              <ModelBadge value={lane.statusLabel} />
              <p className="text-muted-foreground">관측 {time(lane.observedAt)}</p>
            </div>
          </div>
          {lane.status === "ok" ? <div className="flex min-w-0 flex-wrap gap-1.5" aria-label="레인 상태별 수">
            {lane.counts.map((entry) => <StatusBadge key={entry.key}>{entry.label} · {number(entry.count)}</StatusBadge>)}
          </div> : null}
        </CardHeader>
        {lane.status === "unavailable" ? <CardContent className="py-4">
          <Alert><AlertTitle>확인 불가</AlertTitle><AlertDescription className="[overflow-wrap:anywhere]">{lane.error ?? missing}</AlertDescription></Alert>
        </CardContent> : <>
          {lane.truncated ? <p className="border-b bg-muted/30 px-4 py-2 text-xs text-muted-foreground">{number(lane.shown)}/{number(lane.total)} 표시 · 활성 우선 후 최근 활동 순</p> : null}
          {lane.rows.length ? lane.rows.map((row) => <SessionItem key={row.key} row={row} screenNotice={screenNotice} />) : <p className="p-4 text-sm text-muted-foreground">{missing}</p>}
        </>}
      </Card>
    </section>
  )
}

export function SessionsPanel({ model }: { model: SessionsModel }) {
  return (
    <div className="flex min-w-0 flex-col gap-4 [overflow-wrap:anywhere]">
      <header className="flex min-w-0 flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="flex items-center gap-2 text-lg font-semibold"><Activity aria-hidden="true" className="size-5 shrink-0" />세션</h2>
          <p className="mt-1 text-sm text-muted-foreground">레인별 실행과 작업 세션의 읽기 전용 관측</p>
        </div>
        <div className="min-w-0 space-y-1 text-xs">
          <ModelBadge value={model.freshnessLabel} />
          <p className="text-muted-foreground">관측 {time(model.freshness.observed_at)} · 경과 {formatSeconds(model.freshness.age)}</p>
          <p className="text-muted-foreground">{model.freshness.reason}</p>
        </div>
      </header>
      <div className="grid min-w-0 grid-cols-1 gap-2 sm:grid-cols-3">
        <StatCard title="등록 레인" value={number(model.coverage?.registered ?? null)} icon={<Layers className="size-4" />} />
        <StatCard title="관측 레인" value={number(model.coverage?.observed ?? null)} icon={<Activity className="size-4" />} />
        <StatCard title="확인 불가 레인" value={number(model.coverage?.unavailable ?? null)} icon={<Layers className="size-4" />} />
      </div>
      <Alert>
        <AlertTitle>관측 범위 밖</AlertTitle>
        <AlertDescription className="min-w-0 [overflow-wrap:anywhere]">
          <p>{model.coverageNotice}</p>
          {model.coverage?.uninstrumented.map((line, index) => <p key={index} className="text-xs text-muted-foreground">{line}</p>)}
        </AlertDescription>
      </Alert>
      {model.staleWarning !== null ? <Alert className="border-warning/40 bg-warning/10">
        <AlertTriangle aria-hidden="true" />
        <AlertTitle>관측 주의</AlertTitle>
        <AlertDescription className="[overflow-wrap:anywhere]">{model.staleWarning}</AlertDescription>
      </Alert> : null}
      {model.state !== "ready" ? <Alert>
        <AlertTitle>{model.state === "unregistered" ? "등록된 레인 없음" : "확인 불가"}</AlertTitle>
        <AlertDescription className="[overflow-wrap:anywhere]">{model.reason}</AlertDescription>
      </Alert> : model.lanes.map((lane) => <LaneSection key={lane.id} lane={lane} screenNotice={model.screenNotice} />)}
      <p className="text-xs leading-relaxed text-muted-foreground">{model.authority}</p>
    </div>
  )
}
