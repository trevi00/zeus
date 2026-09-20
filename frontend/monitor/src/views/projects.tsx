import { AlertTriangle, ArrowDown, ArrowRight, CircleHelp, Flag, Lightbulb, ListChecks, ShieldCheck, Target, Workflow, type LucideIcon } from "lucide-react"

import { StatCard } from "@/components/stat-card"
import { StatusBadge } from "@/components/status-badge"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import {
  PORTFOLIO_SAMPLE,
  criterionInfo,
  criterionProgress,
  investigationInfo,
  jobSample,
  jobStatusInfo,
  jobsByCriterion,
  readPortfolio,
  unplacedJobs,
  type ParsedPortfolio,
  type Progress,
} from "@/lib/portfolio"
import { PORTFOLIO_SCHEMA, formatNumber, formatSeconds, formatTime, portfolioFreshness, type PortfolioInvestigation, type PortfolioJob, type PortfolioProject, type Snapshot } from "@/lib/snapshot"
import { freshnessTone, type Tone } from "@/lib/tones"

/**
 * 프로젝트 (operating-portfolio-001 SPEC, interface lane). Read-only projection of the optional
 * `sources.portfolio` envelope: the owner's three authorized goals, the fleet jobs explicitly bound
 * to their criteria, the owner's acceptance records and the repeated-failure investigation queue.
 * Nothing here writes, binds, accepts, retries or dispositions; those are owner-only Python calls.
 *
 * What each state means on this screen, and what it must never become:
 * - no response / envelope absent (older collector) / collector failure / off-contract body /
 *   invalid observation time / stale observation are all "확인 불가" flavours, never 0 and never
 *   an empty portfolio;
 * - a criterion is accepted only where the owner recorded an acceptance. Job status never implies
 *   it, and an acceptance is not "the whole source document was absorbed";
 * - the rendered jobs and investigation job IDs are the collector's latest-50 sample, while the
 *   counts come from all rows: the two numbers are always shown apart;
 * - an investigation row is a coarse (status, reason_code) triage family: a research candidate,
 *   not a confirmed cause, not an executed fix, and `researched`/`deferred` are owner decisions
 *   rather than resolutions;
 * - `unknown` jobs keep fleet ownership and are neither failure nor success here.
 * `portfolio` is not in SOURCE_NAMES, so the source strip, header warnings, the retained map and
 * the pinned report keep their fixed contracts; this view carries its own freshness and notices.
 */
type Props = { snapshot: Snapshot | null; now: number }

function Unknown({ children = "확인 불가" }: { children?: React.ReactNode }) {
  return <span className="text-unknown">{children}</span>
}

const NODE_BORDER: Record<Tone, string> = {
  success: "border-success/50", warning: "border-warning/60", error: "border-error/50", unknown: "border-unknown/50", neutral: "border-border",
}

function FlowNode({ icon: Icon, title, tone, badge, lines }: { icon: LucideIcon; title: string; tone: Tone; badge: string; lines: string[] }) {
  return (
    <div className={`flex min-w-0 flex-col gap-1 rounded-lg border-2 bg-card p-2 text-xs break-words ${NODE_BORDER[tone]}`}>
      <div className="flex min-w-0 items-center gap-1.5 font-medium"><Icon aria-hidden="true" className="size-3.5 shrink-0 text-muted-foreground" /><span className="min-w-0 break-words">{title}</span></div>
      <StatusBadge tone={tone} className="self-start">{badge}</StatusBadge>
      {lines.map((line) => <div key={line} className="text-muted-foreground">{line}</div>)}
    </div>
  )
}

function FlowArrow() {
  return (
    <div aria-hidden="true" className="flex items-center justify-center text-muted-foreground">
      <ArrowDown className="size-4 lg:hidden" /><ArrowRight className="hidden size-4 lg:block" />
    </div>
  )
}

/**
 * Accepted-criteria progress of one project. The bar is drawn only from the owner's acceptance
 * records (wire counts) and only while those counts agree with the criterion rows below it; a
 * disagreement removes the ratio instead of rounding it into a number the screen cannot support.
 */
function ProgressBar({ label, progress }: { label: string; progress: Progress }) {
  const { accepted, total, percent, consistent } = progress
  const ratio = percent == null ? (total === 0 ? "기준 없음" : "비율 확인 불가") : `${percent}%`
  return (
    <div className="flex min-w-0 flex-col gap-1">
      <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
        <span>수용 기록된 기준 <span className="tabular-nums">{formatNumber(accepted)} / {formatNumber(total)}</span></span>
        <span className="text-muted-foreground tabular-nums">{ratio}</span>
      </div>
      <div aria-label={label} aria-valuemax={total} aria-valuemin={0} aria-valuenow={percent == null ? undefined : accepted}
        aria-valuetext={`${formatNumber(accepted)} / ${formatNumber(total)} · ${ratio}`} className="h-2 w-full overflow-hidden rounded-full bg-muted" role="progressbar">
        {/* Unknown must not look like 0%: an unreadable ratio fills the track with the unknown tone,
            while an empty definition (no criteria at all) leaves it empty. */}
        {percent != null ? <div className="h-full bg-success" style={{ width: `${percent}%` }} />
          : total === 0 ? null : <div className="h-full w-full bg-unknown/25" />}
      </div>
      {consistent ? null : (
        <p className="text-xs text-unknown break-words">집계 수치와 아래 기준 행이 일치하지 않아 비율을 표시하지 않습니다 (확인 불가 · 0%가 아님).</p>
      )}
    </div>
  )
}

/** One bound fleet job row. Status meaning is fleet's, and 검토 수락은 병합·배포·기준 수용이 아닙니다. */
function JobRow({ job }: { job: PortfolioJob }) {
  const info = jobStatusInfo(job.status)
  return (
    <li className="flex min-w-0 flex-col gap-1 rounded-md border p-2 text-xs">
      <div className="flex min-w-0 flex-wrap items-center gap-2">
        <StatusBadge tone={info.tone} title={info.note}>{info.label}</StatusBadge>
        <span className="font-mono break-all">{job.id}</span>
      </div>
      <div className="text-muted-foreground break-words">
        레인 {job.lane || "기록 없음"} · 사유 {job.reason_code ?? "없음"} · 마지막 기록 {formatTime(job.updated_at)}
      </div>
    </li>
  )
}

function JobList({ jobs, empty }: { jobs: PortfolioJob[]; empty: string }) {
  if (jobs.length === 0) return <p className="text-xs text-muted-foreground break-words">{empty}</p>
  return <ul className="flex flex-col gap-1">{jobs.map((job) => <JobRow key={job.id} job={job} />)}</ul>
}

function EvidenceRefs({ refs }: { refs: string[] }) {
  if (refs.length === 0) return <span className="text-muted-foreground">증거 참조 없음</span>
  return <span className="font-mono break-all">{refs.join(", ")}</span>
}

/** One authorized goal: full outcome, honest acceptance progress, criteria and their actual jobs. */
function ProjectCard({ project, current }: { project: PortfolioProject; current: boolean }) {
  const progress = criterionProgress(project)
  const sample = jobSample(project)
  const grouped = jobsByCriterion(project)
  const unplaced = unplacedJobs(project)
  const sampleNote = sample.truncated
    ? `작업 표시 ${formatNumber(sample.shown)}건 (최근 ${PORTFOLIO_SAMPLE}건 표본 · 잘림) · 전체 ${formatNumber(sample.total)}건`
    : `작업 표시 ${formatNumber(sample.shown)}건 · 전체 ${formatNumber(sample.total)}건`

  return (
    <Card size="sm" className="min-w-0">
      <CardHeader>
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <StatusBadge tone="neutral" title="소유자 정의 문서의 목표 ID">{project.id}</StatusBadge>
          {current ? null : <StatusBadge tone="unknown">현재 상태 아님</StatusBadge>}
        </div>
        <CardTitle className="break-words">{project.title || <Unknown>제목 없음</Unknown>}</CardTitle>
        <CardDescription className="break-words">{project.outcome || <Unknown>목표 설명 없음</Unknown>}</CardDescription>
      </CardHeader>
      <CardContent className="flex min-w-0 flex-col gap-3">
        <p className="text-xs text-muted-foreground break-all">정의 출처 {project.source_ref || "기록 없음"}</p>
        <ProgressBar label={`${project.title} 수용 기준 진행`} progress={progress} />
        <p className="text-xs text-muted-foreground break-words">{sampleNote} · 작업 수는 전체 기준이고 아래 목록은 표본입니다.</p>
        <details className="min-w-0 rounded-md border">
          <summary className="cursor-pointer px-2 py-1.5 text-xs font-medium">수용 기준 {formatNumber(project.criteria.length)}개와 연결된 작업 보기</summary>
          <div className="flex min-w-0 flex-col gap-2 border-t p-2">
            {project.criteria.length === 0 ? (
              <p className="text-xs text-muted-foreground">정의 문서에 기준이 없습니다 (비어 있음 · 확인 불가 아님).</p>
            ) : project.criteria.map((criterion) => {
              const info = criterionInfo(criterion.status)
              const jobs = grouped.get(criterion.id) ?? []
              return (
                <section key={criterion.id} aria-label={`${project.title} · ${criterion.id}`} className="flex min-w-0 flex-col gap-1 rounded-md border p-2">
                  <div className="flex min-w-0 flex-wrap items-center gap-2">
                    <StatusBadge tone={info.tone} title={info.note}>{info.label}</StatusBadge>
                    <span className="font-mono text-xs break-all">{criterion.id}</span>
                  </div>
                  <p className="text-sm break-words">{criterion.text || <Unknown>기준 문구 없음</Unknown>}</p>
                  <p className="text-xs text-muted-foreground break-words">수용 증거 <EvidenceRefs refs={criterion.evidence_refs} /></p>
                  <p className="text-xs text-muted-foreground">연결된 작업 {formatNumber(jobs.length)}건 (표본 안)</p>
                  <JobList jobs={jobs} empty="표본 안에 이 기준으로 연결된 작업이 없습니다 · 전체에도 없다는 뜻은 아닙니다." />
                </section>
              )
            })}
            {unplaced.length ? (
              <section aria-label={`${project.title} · 기준 밖 작업`} className="flex min-w-0 flex-col gap-1 rounded-md border border-unknown/50 p-2">
                <StatusBadge tone="unknown" className="self-start">기준을 읽지 못한 작업 {formatNumber(unplaced.length)}건</StatusBadge>
                <p className="text-xs text-muted-foreground break-words">수집기가 criterion_id 를 주지 않았거나 정의 문서에 없는 기준을 가리킵니다. 숨기지 않고 따로 표시하며, 어떤 기준의 작업으로도 세지 않습니다.</p>
                <JobList jobs={unplaced} empty="없음" />
              </section>
            ) : null}
          </div>
        </details>
      </CardContent>
    </Card>
  )
}

/** One repeated-failure candidate. Coarse triage family only: never presented as a cause or a fix. */
function InvestigationCard({ investigation }: { investigation: PortfolioInvestigation }) {
  const info = investigationInfo(investigation.state)
  const shown = investigation.job_ids.length
  const idsTruncated = shown < investigation.count
  return (
    <Card size="sm" className="min-w-0">
      <CardHeader>
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <StatusBadge tone={info.tone} title={info.note}>{info.label}</StatusBadge>
          <StatusBadge tone="unknown">유사 증상 조사 후보 · 원인 확정 아님</StatusBadge>
        </div>
        <CardTitle className="text-sm break-words">{jobStatusInfo(investigation.family_status).label} · <span className="font-mono">{investigation.reason_code || "사유 없음"}</span></CardTitle>
        <CardDescription className="break-words">묶음 기준 (상태, 사유 코드) · 같은 사유가 같은 원인이라는 뜻은 아닙니다.</CardDescription>
      </CardHeader>
      <CardContent className="flex min-w-0 flex-col gap-2 text-xs">
        <p className="break-words">해당 작업 <span className="tabular-nums">{formatNumber(investigation.count)}</span>건 (전체 기준 · 중복 없는 작업 ID) · ID 표시 {formatNumber(shown)}건{idsTruncated ? ` (최근 ${PORTFOLIO_SAMPLE}건까지만 표시 · 목록이 전부가 아님)` : ""}</p>
        <p className="font-mono break-all text-muted-foreground">{investigation.job_ids.length ? investigation.job_ids.join(", ") : "작업 ID 없음"}</p>
        <p className="break-words">소유자 판단 증거 <EvidenceRefs refs={investigation.evidence_refs} /></p>
        <p className="text-muted-foreground break-words">후보 ID <span className="font-mono break-all">{investigation.id}</span> · 마지막 기록 {formatTime(investigation.updated_at)}</p>
        <p className="text-muted-foreground break-words">{info.note} · 이 화면에는 재시도·수정 버튼이 없습니다.</p>
      </CardContent>
    </Card>
  )
}

export function ProjectsView({ snapshot, now }: Props) {
  const envelope = snapshot?.sources?.portfolio
  const fresh = portfolioFreshness(snapshot, now)
  const parsed: ParsedPortfolio = envelope && envelope.status === "ok" ? readPortfolio(envelope.data) : { ok: false, reason: "정상 응답 아님" }
  const data = parsed.ok ? parsed.data : null
  const current = fresh.state === "fresh"

  const header = (
    <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
      <div className="min-w-0">
        <h2 className="text-lg font-semibold inline-flex items-center gap-2"><Target aria-hidden="true" className="size-4" />프로젝트</h2>
        <p className="text-sm text-muted-foreground break-words">소유자가 정의한 목표와 명시적으로 연결된 실제 작업의 읽기 전용 투영 · 조회 전용(제어 없음) · 수용은 소유자 기록만</p>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <StatusBadge tone={!envelope && snapshot ? "unknown" : freshnessTone(fresh.state)}>
          {!envelope && snapshot ? "출처 미제공" : fresh.state === "fresh" ? "최신" : fresh.state === "stale" ? "오래됨" : fresh.state === "invalid" ? "시각 무효" : fresh.reason || "수집 실패"}
        </StatusBadge>
        <span className="text-xs text-muted-foreground">관측 {formatTime(fresh.observed_at)} · 경과 {formatSeconds(fresh.age)}</span>
      </div>
    </div>
  )

  // Unknown branches first: each is "확인 불가" with its own cause, never an empty portfolio.
  if (!snapshot) {
    return <div className="flex flex-col gap-4">{header}<Alert variant="destructive"><AlertTitle>응답 없음</AlertTitle><AlertDescription>아직 정상 응답을 받지 못했습니다. 목표·기준·작업 수는 0이 아니라 알 수 없음입니다.</AlertDescription></Alert></div>
  }
  if (!envelope) {
    return (
      <div className="flex flex-col gap-4">{header}
        <Alert><CircleHelp aria-hidden="true" /><AlertTitle>이 스냅샷에는 portfolio 출처가 없습니다</AlertTitle>
          <AlertDescription className="break-words">수집기가 `sources.portfolio` 를 아직 제공하지 않습니다(이전 계약의 스냅샷). 목표가 없다는 뜻이 아니라 확인 불가이며, 다른 화면과 보고서는 영향을 받지 않습니다.</AlertDescription></Alert>
      </div>
    )
  }
  if (fresh.state === "unavailable") {
    return (
      <div className="flex flex-col gap-4">{header}
        <Alert variant="destructive"><AlertTitle>portfolio 출처 수집 실패</AlertTitle>
          <AlertDescription className="break-words">상태 {envelope.status ?? "없음"}{envelope.error ? ` · ${envelope.error}` : ""} · 관측 {formatTime(fresh.observed_at)}. 목표 진행과 조사 후보는 알 수 없음이며 비어 있음이 아닙니다. 이 화면은 마지막 정상 기록을 보존하지 않습니다.</AlertDescription></Alert>
      </div>
    )
  }
  if (!parsed.ok || !data) {
    return (
      <div className="flex flex-col gap-4">{header}
        <Alert variant="destructive"><AlertTitle>portfolio 데이터 해석 불가</AlertTitle>
          <AlertDescription className="break-words">{parsed.ok ? "data 없음" : parsed.reason} · 기대 스키마 {PORTFOLIO_SCHEMA}. 계약과 다른 응답은 표시하지 않습니다(확인 불가 · 빈 목록 아님).</AlertDescription></Alert>
      </div>
    )
  }

  const criteriaTotal = data.projects.reduce((sum, project) => sum + project.counts.criteria_total, 0)
  const criteriaAccepted = data.projects.reduce((sum, project) => sum + project.counts.criteria_accepted, 0)
  const jobsTotal = data.projects.reduce((sum, project) => sum + project.counts.jobs_total, 0)
  const jobsShown = data.projects.reduce((sum, project) => sum + project.jobs.length, 0)
  const sampledJobs = data.projects.flatMap((project) => project.jobs)
  const reviewAccepted = sampledJobs.filter((job) => job.status === "accepted").length
  const reviewNegative = sampledJobs.filter((job) => ["rejected", "failed", "exhausted"].includes(job.status)).length
  const jobsSampled = jobsShown < jobsTotal || data.projects.some((project) => project.jobs_truncated)
  const researchRequired = data.investigations.filter((investigation) => investigation.state === "research_required").length
  // A stale or invalid observation keeps the number it actually read, labelled as not-current
  // instead of being redrawn as today's state.
  const liveCount = (value: number) => (current ? formatNumber(value) : <Unknown>{formatNumber(value)} · 현재 아님</Unknown>)

  return (
    <div className="flex min-w-0 flex-col gap-4">
      {header}

      {fresh.state === "invalid" ? (
        <Alert variant="destructive"><AlertTitle>관측 시각 무효</AlertTitle><AlertDescription className="break-words">{fresh.reason}. 아래 내용은 언제 읽은 것인지 알 수 없으므로 현재 상태로 해석하지 마세요.</AlertDescription></Alert>
      ) : null}
      {fresh.state === "stale" ? (
        <Alert><AlertTriangle aria-hidden="true" /><AlertTitle>오래된 관측</AlertTitle><AlertDescription className="break-words">관측 {formatTime(fresh.observed_at)} · 경과 {formatSeconds(fresh.age)} 기준입니다. 그 뒤의 작업 종료·수용 기록·조사 판단은 반영되지 않았습니다.</AlertDescription></Alert>
      ) : null}

      <div className="grid grid-cols-2 gap-2 lg:grid-cols-4">
        <StatCard title="목표" value={liveCount(data.projects.length)} note="소유자 정의 문서의 목표 · 정의는 진행·완료 주장이 아님" icon={<Target className="size-4" />} />
        <StatCard title="수용 기록된 기준" value={<span>{liveCount(criteriaAccepted)} <span className="text-base font-normal text-muted-foreground">/ {formatNumber(criteriaTotal)}</span></span>} note="소유자의 명시적 수용 기록만 · 작업 상태에서 유추하지 않음" icon={<ShieldCheck className="size-4" />} />
        <StatCard title="연결된 작업" value={liveCount(jobsTotal)} note={`전체 기준 · 화면 표시 ${formatNumber(jobsShown)}건(표본)`} icon={<ListChecks className="size-4" />} />
        <StatCard title="조사 후보" value={liveCount(data.investigations.length)} note={`조사 필요 ${formatNumber(researchRequired)}건 · 원인 확정 아님 · 자동 재시도 없음`} icon={<Lightbulb className="size-4" />} />
      </div>

      <p className="text-xs text-muted-foreground break-all">정의 지문 <span className="font-mono">{data.definition_sha256.slice(0, 16)}</span> · 소유자 정의 문서의 정규 JSON 지문이며 완료·검증 주장이 아닙니다.</p>

      {data.unbound_jobs || data.unclassified_failures ? (
        <Alert><CircleHelp aria-hidden="true" /><AlertTitle>목표에 연결되지 않은 기록</AlertTitle>
          <AlertDescription className="break-words">
            {data.unbound_jobs ? `목표에 연결되지 않은 작업 ${formatNumber(data.unbound_jobs)}건(전체 기준): 소유자가 명시적으로 연결한 작업만 위 카드에 나타나며, 제목·경로로 추측해 연결하지 않습니다. ` : ""}
            {data.unclassified_failures ? `사유 코드가 없어 분류하지 못한 종단 실패 ${formatNumber(data.unclassified_failures)}건: 조사 후보에 들어가지 않았으며, 실패가 없다는 뜻이 아닙니다.` : ""}
          </AlertDescription></Alert>
      ) : null}
      {data.investigations_truncated ? (
        <Alert><AlertTriangle aria-hidden="true" /><AlertTitle>조사 후보 목록이 잘렸습니다</AlertTitle>
          <AlertDescription className="break-words">최근 {PORTFOLIO_SAMPLE}건까지만 읽었습니다. 아래 목록은 표본이며 후보 전체가 아닙니다.</AlertDescription></Alert>
      ) : null}

      <Card size="sm" className="min-w-0">
        <CardHeader>
          <CardTitle>목표 → 작업 → 검토 → 수용 기준</CardTitle>
          <CardDescription className="flex flex-wrap items-center gap-2">
            <StatusBadge tone="unknown">경로 설명 · 개별 작업의 실제 이동을 추적한 것이 아님</StatusBadge>
            <span>{jobsSampled ? `작업 수치는 전체, 상태 분포는 표본 ${formatNumber(jobsShown)}건 기준` : "표본 잘림 없음"}</span>
          </CardDescription>
        </CardHeader>
        <CardContent>
          <ol className="grid grid-cols-1 gap-2 lg:grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)_auto_minmax(0,1fr)_auto_minmax(0,1fr)] lg:items-stretch">
            <li className="contents">
              <FlowNode icon={Target} title="1. 목표 정의" tone="neutral" badge={`목표 ${formatNumber(data.projects.length)}개 · 기준 ${formatNumber(criteriaTotal)}개`}
                lines={["소유자가 작성한 정의 문서", "정의 자체는 진행이나 완료 주장이 아님"]} />
            </li>
            <li className="contents"><FlowArrow />
              <FlowNode icon={Workflow} title="2. 작업 연결" tone={jobsTotal ? "warning" : "neutral"} badge={`연결 ${formatNumber(jobsTotal)}건 (전체)`}
                lines={["소유자가 작업 ID를 기준에 명시적으로 연결", `표시 ${formatNumber(jobsShown)}건 (표본)`, data.unbound_jobs ? `연결되지 않은 작업 ${formatNumber(data.unbound_jobs)}건` : "연결되지 않은 작업 없음"]} />
            </li>
            <li className="contents"><FlowArrow />
              <FlowNode icon={Flag} title="3. 독립 검토" tone={reviewNegative ? "error" : reviewAccepted ? "success" : "neutral"} badge={`수락 ${formatNumber(reviewAccepted)} · 거부·실패 ${formatNumber(reviewNegative)} (표본)`}
                lines={["fleet 종단 상태 그대로", "검토 수락 = 후보 수락 · 병합·배포 아님", "실패·거부는 아래 조사 후보로 모임"]} />
            </li>
            <li className="contents"><FlowArrow />
              <FlowNode icon={ShieldCheck} title="4. 기준 수용 (소유자 기록)" tone={criteriaAccepted ? "success" : "warning"} badge={`수용 ${formatNumber(criteriaAccepted)} / ${formatNumber(criteriaTotal)}`}
                lines={["소유자가 증거와 함께 남긴 기록만", "작업 수락이 기준 수용이 되지 않음", "기준 수용이 원본 전체 흡수는 아님"]} />
            </li>
          </ol>
        </CardContent>
      </Card>

      <section aria-label="목표별 진행" className="flex flex-col gap-3">
        <h3 className="text-base font-semibold">목표별 진행 <span className="text-xs font-normal text-muted-foreground">· 수용 기준은 소유자 기록 · 작업 목록은 표본</span></h3>
        {data.projects.length === 0 ? (
          <p className="text-sm text-muted-foreground border rounded-lg p-4">정의 문서에 목표가 없습니다 (읽었으나 비어 있음 · 확인 불가 아님).</p>
        ) : (
          <div className="grid grid-cols-1 gap-3 xl:grid-cols-2">
            {data.projects.map((project) => <ProjectCard key={project.id} project={project} current={current} />)}
          </div>
        )}
      </section>

      <section aria-label="반복 실패 조사 후보" className="flex flex-col gap-3">
        <h3 className="text-base font-semibold inline-flex items-center gap-2"><Lightbulb aria-hidden="true" className="size-4" />반복 실패 조사 후보 <span className="text-xs font-normal text-muted-foreground">· {formatNumber(data.investigations.length)}건 표시</span></h3>
        <Alert><AlertTriangle aria-hidden="true" /><AlertTitle>유사 증상 조사 후보 · 원인 확정 아님</AlertTitle>
          <AlertDescription className="break-words">같은 (상태, 사유 코드)로 두 건 이상 모인 묶음입니다. 같은 사유가 같은 원인이라는 뜻이 아니고, 수정·재시도가 실행된 것도 아닙니다. 조사·보류 판단은 소유자가 증거와 함께 기록하며 이 화면에는 제어가 없습니다.</AlertDescription></Alert>
        {data.investigations.length === 0 ? (
          <p className="text-sm text-muted-foreground border rounded-lg p-4">후보가 없습니다 (읽었으나 비어 있음). 실패가 없다는 뜻은 아니며, 사유 코드가 없는 실패 {formatNumber(data.unclassified_failures)}건은 여기 포함되지 않습니다.</p>
        ) : (
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            {data.investigations.map((investigation) => <InvestigationCard key={investigation.id} investigation={investigation} />)}
          </div>
        )}
      </section>

      <p className="text-xs text-muted-foreground break-words">
        읽는 법: '확인 불가'는 값을 읽지 못한 것이고 '비어 있음'은 읽었더니 없었다는 뜻입니다. 기준의 '수용 기록됨'은 소유자가 증거와 함께 남긴 기록이며, 작업이 검토 수락되었다는 사실에서 유추하지 않습니다. 검토 수락은 병합·배포가 아니고, 기준 수용은 해당 원본 전체를 흡수했다는 뜻이 아닙니다. 작업 수와 후보 건수는 전체 기준이고 화면의 목록은 최근 {formatNumber(PORTFOLIO_SAMPLE)}건 표본이므로, 목록에 없다고 없는 것이 아닙니다. 조사 후보는 증상이 반복된다는 기록일 뿐 원인·해결이 아니며, 판단 이후의 새 실패도 건수에 계속 반영됩니다.
      </p>
    </div>
  )
}
