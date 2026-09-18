import { useId } from "react"
import { AlertTriangle, ArrowDown, ArrowLeftRight, ArrowRight, CircleHelp, Flag, Layers, Lock, Pause, ShieldCheck, Target, Users, Workflow, type LucideIcon } from "lucide-react"

import { StatusBadge } from "@/components/status-badge"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import type { ReportFleet, Story, StoryControl, StoryJob, StoryTeam, StoryVerdict } from "@/lib/report"
import { STATE_LABELS, formatNumber, formatSeconds, formatTime } from "@/lib/snapshot"
import { freshnessTone, type Tone } from "@/lib/tones"

/**
 * Goal -> team -> verdict -> remaining story of the pinned report (report-background-001, Interface
 * lane). Renders `report.story` and `report.fleet` only: the copy `buildReport` captured from the
 * optional `sources.fleet` envelope at capture time, which the print view and the JSON download
 * also carry. No live snapshot, clock, fetch or control is read here.
 *
 * Truth boundaries kept on the picture itself:
 * - missing / collector failure / off-contract data are 확인 불가 in place, never an empty board;
 *   `registered:false` is 비어 있음; stale or invalid observation time is labelled on the header;
 * - every node carries stored facts only (criterion, id, team/lane, status, reason, calls,
 *   created/updated); the four stages are conceptual, so no per-stage time is shown;
 * - 검토 수락 is a review-accepted candidate: merge and deploy are unknown here, not implied;
 * - ceilings are declared call limits, not a remaining balance; sample sums are not the machine total;
 * - the before/after card is a UI design comparison of this screen, not a measured improvement.
 */
type Props = { story: Story; fleet: ReportFleet }

const VERDICT_TONE: Record<StoryVerdict, Tone> = {
  accepted: "success", dispatching: "warning", queued: "warning", unknown: "unknown",
  rejected: "error", failed: "error", exhausted: "error", undefined: "unknown",
}
const NODE_BORDER: Record<Tone, string> = {
  success: "border-success/50", warning: "border-warning/60", error: "border-error/50", unknown: "border-unknown/50", neutral: "border-border",
}
const STAGE_ICONS: Record<Story["stages"][number]["key"], LucideIcon> = {
  goal: Target, team: Users, verdict: ShieldCheck, remaining: Flag,
}

function Unknown({ children = "확인 불가" }: { children?: React.ReactNode }) {
  return <span className="text-unknown">{children}</span>
}

function callsText(value: number | null): string {
  return value == null ? "확인 불가" : `${formatNumber(value)}회`
}

function Node({ icon: Icon, title, tone, badge, badgeTitle, children }: { icon: LucideIcon; title: string; tone: Tone; badge: React.ReactNode; badgeTitle?: string; children: React.ReactNode }) {
  return (
    <div className={`report-story-node flex min-w-0 flex-col gap-1 rounded-lg border-2 bg-card p-2 text-xs break-words ${NODE_BORDER[tone]}`}>
      <div className="flex min-w-0 items-center gap-1.5 font-medium"><Icon aria-hidden="true" className="size-3.5 shrink-0 text-muted-foreground" /><span className="min-w-0 break-words">{title}</span></div>
      <StatusBadge tone={tone} className="self-start" title={badgeTitle}>{badge}</StatusBadge>
      <div className="flex min-w-0 flex-col gap-0.5 text-muted-foreground">{children}</div>
    </div>
  )
}

function Arrow() {
  return (
    <div aria-hidden="true" className="flex items-center justify-center text-muted-foreground">
      <ArrowDown className="size-4 md:hidden" /><ArrowRight className="hidden size-4 md:block" />
    </div>
  )
}

/** One job as four connected nodes: goal -> team -> verdict -> remaining. Stacked below `md`, one row at `md` and up. */
function JobLanes({ job }: { job: StoryJob }) {
  const tone = VERDICT_TONE[job.verdict]
  const dependencyTone: Tone = job.dependency_state === "confirmed_unmet" ? "error" : job.dependency_state === "unknown" ? "unknown" : job.dependency_state === "all_accepted" ? "success" : "neutral"
  return (
    <li className="report-story-job min-w-0">
      <div className="grid grid-cols-1 gap-1.5 md:grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)_auto_minmax(0,1fr)_auto_minmax(0,1fr)] md:items-stretch">
        <Node icon={Target} title="목표" tone="neutral" badge={<span className="font-mono">{job.short_id}</span>} badgeTitle={job.id}>
          <div className="text-foreground">{job.goal.criterion ?? <Unknown>기준 없음</Unknown>}</div>
          <div className="font-mono break-all">{job.goal.path ?? "경로 없음"}</div>
          <div>운영 ID <span className="font-mono break-all">{job.operation_id ?? "없음"}</span></div>
        </Node>
        <Arrow />
        <Node icon={Users} title="팀 · 레인" tone="neutral" badge={`${job.team ?? "팀 없음"} / ${job.lane ?? "레인 없음"}`}>
          <div>생성 {formatTime(job.created_at)}</div>
          <div>마지막 기록 {formatTime(job.updated_at)} · 생존 신호 아님</div>
          <div>단계별 시각 · 기록 없음</div>
        </Node>
        <Arrow />
        <Node icon={ShieldCheck} title="판정" tone={tone} badge={job.verdict_label} badgeTitle={job.verdict_meaning}>
          <div>{job.verdict_meaning}</div>
          <div>사유 {job.reason_code ?? "없음"}</div>
          <div>호출 예약 {callsText(job.calls.reserved)} · 정산 {callsText(job.calls.settled)}</div>
        </Node>
        <Arrow />
        <Node icon={Flag} title="남은 것" tone={tone} badge={job.verdict === "accepted" ? "후보 수락 · 병합 알 수 없음" : job.verdict === "unknown" ? "소유자 조정 필요" : job.verdict === "queued" ? "대기 · 기록된 사유" : job.verdict === "dispatching" ? "종료 기록 없음" : job.verdict === "undefined" ? "해석 불가" : "소유자 다음 결정"}>
          <div>{job.remaining}</div>
          {job.dependencies.length ? (
            <div className="flex min-w-0 flex-wrap items-center gap-1">
              <StatusBadge tone={dependencyTone} title={job.dependency_label}>{job.dependency_label}</StatusBadge>
              <span className="font-mono break-all">{job.dependencies.map((dep) => `${dep.id} (${dep.sampled ? dep.status : "표본 밖 · 알 수 없음"})`).join(", ")}</span>
            </div>
          ) : null}
        </Node>
      </div>
    </li>
  )
}

function TeamLane({ team }: { team: StoryTeam }) {
  const headingId = useId()
  return (
    <li className="min-w-0 rounded-xl bg-muted/40 p-2 ring-1 ring-foreground/10">
      <div className="flex min-w-0 flex-wrap items-center gap-2 px-1 pb-2">
        <h3 id={headingId} className="inline-flex min-w-0 items-center gap-1.5 text-sm font-medium break-words"><Users aria-hidden="true" className="size-4 shrink-0 text-muted-foreground" />{team.team}</h3>
        <span className="text-xs text-muted-foreground">작업 {formatNumber(team.jobs.length)}건 (표본)</span>
        {team.lanes.length === 0 ? <StatusBadge tone="neutral">등록된 레인 없음 · 작업 기록만</StatusBadge> : team.lanes.map((lane) => (
          <StatusBadge key={lane.id} tone={lane.active_job ? (lane.active_in_sample ? "warning" : "unknown") : "neutral"} title="활성은 dispatching·unknown 예약에서 도출 · 표본 밖 포함">
            {lane.active_job ? <Lock aria-hidden="true" /> : null}<span className="font-mono">{lane.id}</span> · {lane.active_job ? `활성 ${lane.active_job}${lane.active_in_sample ? "" : " (표본 밖)"}` : "비어 있음"}
          </StatusBadge>
        ))}
      </div>
      {team.jobs.length === 0 ? <p className="px-1 pb-1 text-xs text-muted-foreground">이 팀의 작업이 표본 안에 없음 (비어 있음)</p> : (
        <ul aria-labelledby={headingId} className="flex flex-col gap-2">{team.jobs.map((job) => <JobLanes key={job.id} job={job} />)}</ul>
      )}
    </li>
  )
}

function ControlStrip({ control, fleet }: { control: StoryControl; fleet: ReportFleet }) {
  const listId = useId()
  const items: Array<{ key: string; icon: LucideIcon; title: string; value: React.ReactNode; note: string; tone: Tone }> = [
    { key: "admission", icon: control.admission === "paused" ? Pause : Workflow, title: "admission", value: control.admission === "paused" ? "일시 정지" : "열림", note: control.admission === "paused" ? "신규 배정 차단 · 배정된 작업은 완료까지 진행" : "열림 ≠ 서비스 실행 중 · 생존 신호 없음", tone: control.admission === "paused" ? "warning" : "neutral" },
    { key: "lanes", icon: Layers, title: "활성 레인 / 동시 실행 상한", value: `${formatNumber(control.active_lanes)} / ${formatNumber(control.max_parallel)}`, note: `레인 ${formatNumber(control.lanes_total)}개 · 레인당 1개 · 표본 밖 활성 ${formatNumber(control.active_outside_sample.length)}건`, tone: control.active_lanes ? "warning" : "neutral" },
    { key: "budget", icon: ShieldCheck, title: "호출 상한 (호스트당 / 전체)", value: `${formatNumber(control.budget.per_host)} / ${formatNumber(control.budget.total)}`, note: "선언된 호출 수 상한 · 남은 호출·금액·실제 지출 아님 · 기계 장부 없음", tone: "neutral" },
    { key: "calls", icon: Lock, title: "표본 작업 예약 / 정산 합계", value: control.sample_calls.reserved == null && control.sample_calls.settled == null ? <Unknown /> : `${callsText(control.sample_calls.reserved)} / ${callsText(control.sample_calls.settled)}`, note: `표본 ${formatNumber(fleet.sample.count)}건의 합계 · 기계 전체 아님${control.sample_calls.partial ? ` · 확인 불가 ${formatNumber(control.sample_calls.jobs_unknown)}건 제외한 부분 합계` : ""}`, tone: control.sample_calls.partial ? "unknown" : "neutral" },
    { key: "sample", icon: AlertTriangle, title: "표본 · 관측 시각", value: `${formatNumber(fleet.sample.count)}건 · ${fleet.sample.truncated ? "잘림" : "잘리지 않음"}`, note: `최근 ${formatNumber(fleet.sample.limit)}건 상한 · 관측 ${formatTime(fleet.observed_at)} · 경과 ${fleet.age_seconds == null ? "알 수 없음" : formatSeconds(fleet.age_seconds * 1000)} (캡처 기준 · 하트비트 아님)`, tone: fleet.sample.truncated ? "warning" : freshnessTone(fleet.freshness) },
  ]
  return (
    <Card size="sm" className="min-w-0">
      <CardHeader>
        <CardTitle id={listId}>유한 운영 띠</CardTitle>
        <CardDescription className="flex flex-wrap items-center gap-2">
          {control.policy.map((line) => <StatusBadge key={line} tone="neutral">{line}</StatusBadge>)}
        </CardDescription>
      </CardHeader>
      <CardContent>
        <ul aria-labelledby={listId} className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-5">
          {items.map(({ key, icon: Icon, title, value, note, tone }) => (
            <li key={key} className={`flex min-w-0 flex-col gap-0.5 rounded-lg border-2 bg-card p-2 text-xs break-words ${NODE_BORDER[tone]}`}>
              <div className="flex min-w-0 items-center gap-1.5 text-muted-foreground"><Icon aria-hidden="true" className="size-3.5 shrink-0" /><span className="min-w-0 break-words">{title}</span></div>
              <div className="text-lg font-semibold tabular-nums break-words">{value}</div>
              <div className="text-muted-foreground">{note}</div>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  )
}

export function ReportStory({ story, fleet }: Props) {
  const titleId = useId()
  const outcomesId = useId()
  const remainingId = useId()
  const caveatsId = useId()
  const registered = story.state === "registered" && story.control != null
  const headerTone: Tone = story.state === "registered" ? freshnessTone(fleet.freshness) : story.state === "unregistered" ? "neutral" : "unknown"
  const headerBadge = story.state === "registered"
    ? `fleet ${story.fleet_id} · ${STATE_LABELS[fleet.freshness]}${fleet.freshness === "fresh" ? "" : " · 현재 아님"}`
    : story.state === "unregistered" ? "등록된 fleet 없음 · 비어 있음" : story.state === "missing" ? "fleet 출처 없음 · 확인 불가" : story.state === "unavailable" ? "fleet 수집 실패 · 확인 불가" : "fleet 데이터 해석 불가 · 확인 불가"

  return (
    <section aria-labelledby={titleId} className="flex min-w-0 flex-col gap-3">
      <Card size="sm" className="min-w-0">
        <CardHeader>
          <CardTitle id={titleId} className="text-base">이야기로 보는 팀 작업 · {story.title}</CardTitle>
          <CardDescription className="flex flex-wrap items-center gap-2">
            <StatusBadge tone={headerTone}>{headerBadge}</StatusBadge>
            <StatusBadge tone="unknown">{story.stage_label}</StatusBadge>
            <span>관측 {formatTime(fleet.observed_at)} · 캡처 시점에 고정 · 이 보고서의 다른 출처와 독립</span>
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <ol aria-label="이야기 단계" className="grid grid-cols-1 gap-2 md:grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)_auto_minmax(0,1fr)_auto_minmax(0,1fr)] md:items-stretch">
            {story.stages.map((stage, index) => {
              const Icon = STAGE_ICONS[stage.key]
              return (
                <li key={stage.key} className="contents">
                  {index > 0 ? <Arrow /> : null}
                  <div className="flex min-w-0 flex-col gap-1 rounded-lg bg-muted/50 p-2 text-xs break-words">
                    <div className="flex min-w-0 items-center gap-1.5 font-medium"><Icon aria-hidden="true" className="size-3.5 shrink-0 text-primary" /><span className="min-w-0">{stage.title}</span></div>
                    <div className="text-muted-foreground">{stage.note}</div>
                  </div>
                </li>
              )
            })}
          </ol>
          {!registered ? (
            <div className={`flex min-w-0 items-start gap-2 rounded-md border border-dashed px-3 py-2 text-sm break-words ${story.state === "unregistered" ? "text-muted-foreground" : "border-unknown/50 text-unknown"}`}>
              <CircleHelp aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
              <div className="flex min-w-0 flex-col gap-1">
                <div>{story.state_note}</div>
                {fleet.status || fleet.error ? <div className="text-xs">출처 상태 {fleet.status ?? "없음"}{fleet.error ? ` · ${fleet.error}` : ""} · 관측 {formatTime(fleet.observed_at)}</div> : null}
                <div className="text-xs">{story.state === "unregistered" ? "목표·팀·판정·잔여는 비어 있음 (0건 · 확인 불가 아님)" : "목표·팀·판정·잔여는 모두 확인 불가 (0건 아님)"}</div>
              </div>
            </div>
          ) : null}
        </CardContent>
      </Card>

      {registered && story.control ? <ControlStrip control={story.control} fleet={fleet} /> : null}

      {registered ? (
        <Card size="sm" className="min-w-0">
          <CardHeader>
            <CardTitle>팀별 작업 흐름</CardTitle>
            <CardDescription className="flex flex-wrap items-center gap-2">
              <StatusBadge tone="unknown">노드의 값은 저장된 사실 · 화살표는 개념 순서 · 개별 단계 시각 없음</StatusBadge>
              <span>팀 {formatNumber(story.teams.length)}개 · 작업 {formatNumber(fleet.sample.count)}건 · {fleet.sample.truncated ? `최근 ${formatNumber(fleet.sample.limit)}건 표본 · 잘림 · 전체 아님` : "표본 기준 · 잘리지 않음"} · 수집기 순서 그대로</span>
            </CardDescription>
          </CardHeader>
          <CardContent>
            {story.teams.length === 0 ? (
              <p className="rounded-md border border-dashed px-3 py-2 text-sm text-muted-foreground break-words">레인과 작업이 없음 (등록됨 · 비어 있음 · 확인 불가 아님)</p>
            ) : (
              <ul aria-label="팀별 작업 흐름" className="flex flex-col gap-3">{story.teams.map((team) => <TeamLane key={team.team} team={team} />)}</ul>
            )}
          </CardContent>
        </Card>
      ) : null}

      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        <Card size="sm" className="min-w-0">
          <CardHeader>
            <CardTitle id={outcomesId}>결과 (표본)</CardTitle>
            <CardDescription>{registered ? `작업 ${formatNumber(fleet.sample.count)}건의 저장된 상태별 건수 · 검토 수락은 후보 수락 · 병합·배포 아님` : story.state === "unregistered" ? "등록된 fleet 없음 · 비어 있음" : "fleet 출처 확인 불가 · 건수 없음 (0건 아님)"}</CardDescription>
          </CardHeader>
          <CardContent>
            {!registered ? (
              <p className={`rounded-md border border-dashed px-3 py-2 text-sm break-words ${story.state === "unregistered" ? "text-muted-foreground" : "border-unknown/50 text-unknown"}`}>{story.state === "unregistered" ? "0건 · 비어 있음" : "확인 불가 · 0건 아님"}</p>
            ) : story.outcomes.length === 0 ? (
              <p className="rounded-md border border-dashed px-3 py-2 text-sm text-muted-foreground break-words">0건 · 표본 안에 작업 없음 (비어 있음)</p>
            ) : (
              <ul aria-labelledby={outcomesId} className="flex flex-col gap-1.5 text-sm">
                {story.outcomes.map((outcome) => (
                  <li key={outcome.verdict} className="flex min-w-0 flex-wrap items-center gap-2">
                    <StatusBadge tone={VERDICT_TONE[outcome.verdict]}>{outcome.label} {formatNumber(outcome.count)}건</StatusBadge>
                    <span className="min-w-0 text-xs text-muted-foreground break-words">{outcome.remaining}</span>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
        <Card size="sm" className="min-w-0">
          <CardHeader>
            <CardTitle id={remainingId} className="inline-flex items-center gap-2"><Flag aria-hidden="true" className="size-4 text-primary" />무엇이 남았는가</CardTitle>
            <CardDescription>기록된 사실과 다음 결정 주체 · 완료 시점·성공률 예측 아님 · 이 화면에는 제어 없음</CardDescription>
          </CardHeader>
          <CardContent>
            <ul aria-labelledby={remainingId} className="flex flex-col gap-1 text-sm break-words">
              {story.remaining.map((line) => <li key={line} className="flex gap-2"><span aria-hidden="true" className="mt-2 size-1.5 shrink-0 rounded-full bg-primary" /><span className="min-w-0">{line}</span></li>)}
            </ul>
          </CardContent>
        </Card>
      </div>

      <Card size="sm" className="min-w-0">
        <CardHeader>
          <CardTitle id={caveatsId} className="inline-flex items-center gap-2"><AlertTriangle aria-hidden="true" className="size-4 text-warning" />이 이야기의 한계</CardTitle>
          <CardDescription>fleet 출처와 표본이 말해 주지 않는 것 · 항상 표시</CardDescription>
        </CardHeader>
        <CardContent>
          <ul aria-labelledby={caveatsId} className="flex flex-col gap-1 text-sm break-words">
            {story.caveats.map((line) => <li key={line} className="flex gap-2"><span aria-hidden="true" className="mt-2 size-1.5 shrink-0 rounded-full bg-warning" /><span className="min-w-0">{line}</span></li>)}
          </ul>
        </CardContent>
      </Card>

      <Card size="sm" className="min-w-0">
        <CardHeader>
          <CardTitle className="inline-flex items-center gap-2"><ArrowLeftRight aria-hidden="true" className="size-4 text-muted-foreground" />이 보고서 화면의 이전과 현재</CardTitle>
          <CardDescription className="flex flex-wrap items-center gap-2">
            <StatusBadge tone="unknown">{story.comparison.label}</StatusBadge>
            <span className="break-words">{story.comparison.note}</span>
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 gap-2 md:grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] md:items-stretch">
            <div className="flex min-w-0 flex-col gap-1 rounded-lg border-2 border-border bg-card p-2 text-xs break-words">
              <div className="font-medium">이전 · 집계만</div>
              <ul className="flex flex-col gap-1 text-muted-foreground">{story.comparison.before.map((line) => <li key={line} className="flex gap-2"><span aria-hidden="true" className="mt-1.5 size-1 shrink-0 rounded-full bg-muted-foreground" /><span className="min-w-0">{line}</span></li>)}</ul>
            </div>
            <Arrow />
            <div className="flex min-w-0 flex-col gap-1 rounded-lg border-2 border-primary/50 bg-card p-2 text-xs break-words">
              <div className="font-medium">현재 · 목표·팀·결과 연결</div>
              <ul className="flex flex-col gap-1 text-muted-foreground">{story.comparison.after.map((line) => <li key={line} className="flex gap-2"><span aria-hidden="true" className="mt-1.5 size-1 shrink-0 rounded-full bg-primary" /><span className="min-w-0">{line}</span></li>)}</ul>
            </div>
          </div>
        </CardContent>
      </Card>
    </section>
  )
}
