import { AlertTriangle, ArrowDown, ArrowRight, CircleHelp, GitBranch, Layers, ListChecks, Lock, Pause, ShieldCheck, Users, Workflow, type LucideIcon } from "lucide-react"

import { KeyValue, StatCard } from "@/components/stat-card"
import { StatusBadge } from "@/components/status-badge"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { ACCOUNTING_TITLE, accountingDisplay, interpretAccounting } from "@/lib/accounting"
import { FLEET_SCHEMA, fleetFreshness, formatNumber, formatSeconds, formatTime, readDelivery, type FleetData, type FleetDelivery, type FleetJob, type FleetLane, type FleetRegistered, type Snapshot } from "@/lib/snapshot"
import { freshnessTone, type Tone } from "@/lib/tones"

/**
 * 팀 작업 (fleet-001 SPEC, UI lane). Renders only the optional `sources.fleet` envelope of the live
 * snapshot: a read-only projection of the central fleet store. Nothing here mutates, retries,
 * merges, reserves budget or infers liveness. Distinct truth states, each with its own copy:
 * - no response / envelope absent (older collector) / collector failure / uninterpretable data /
 *   invalid observation time / stale observation are all "확인 불가" flavours, never zero;
 * - `registered:false` is empty (등록 없음), not unknown;
 * - job `unknown` retains ownership and exclusion; `accepted` means review accepted, not deployed.
 *   Delivery comes only from the optional owner-recorded `delivery` document of that same job:
 *   merge and deploy stay separate, no record is unknown (never 미배포), and nothing here verifies
 *   GitHub or a deployment independently;
 * - the usage-accounting mode comes from the shared reading of lib/accounting.ts: subscription is
 *   never drawn as an active call ceiling, and a contradictory or off-contract mode is unknown;
 * - `truncated` bounds every count to the sample of at most 100 jobs;
 * - `updated_at` is the last recorded execution fact, never a heartbeat.
 * Fleet is not in SOURCE_NAMES, so the source strip, header warnings, retained map and the pinned
 * report are unchanged; this view carries its own freshness badge and notices.
 */
type Props = { snapshot: Snapshot | null; now: number }

type JobStatusInfo = { label: string; tone: Tone; note: string }

/** Labels for the fleet job states of INV-FLEET-001; anything else renders raw and is flagged. */
const JOB_STATUS: Record<string, JobStatusInfo> = {
  queued: { label: "대기", tone: "warning", note: "admission 전 · 상한·레인·의존성·경로 충돌 검사 대기" },
  dispatching: { label: "배정됨", tone: "warning", note: "소유 토큰 보유 · 프로세스 생성 전 구간 포함 · 실행 중일 수 있음" },
  accepted: { label: "검토 수락", tone: "success", note: "독립 검토가 후보를 수락함 · 병합·배포 아님" },
  rejected: { label: "검토 거부", tone: "error", note: "독립 검토가 후보를 거부함" },
  failed: { label: "실패", tone: "error", note: "정확한 실패 기록 · 자동 재시도 없음" },
  exhausted: { label: "예산 소진", tone: "error", note: "예산 소진으로 기록된 상태 · 기록 당시 기준 · 자동 상향 없음" },
  unknown: { label: "알 수 없음", tone: "unknown", note: "시작·종료·PG 읽기 불확실 · 예약·용량·경로 배제 유지 · 자동 인계 없음" },
}
const JOB_STATUS_ORDER = ["queued", "dispatching", "accepted", "rejected", "failed", "exhausted", "unknown"]
const OWNED_STATUSES = new Set(["dispatching", "unknown"])

function jobStatus(status: string): JobStatusInfo {
  return JOB_STATUS[status] ?? { label: `${status} (정의되지 않은 상태)`, tone: "unknown", note: "이 화면이 모르는 상태 값 · 저장된 그대로 표시" }
}

type Parsed = { ok: true; data: FleetData } | { ok: false; reason: string }

/** Narrow `envelope.data` to the SPEC shape without inventing values; anything off-contract is invalid, not empty. */
function readFleet(data: unknown): Parsed {
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
      // Both mode statements are read here, never discarded: an off-contract or contradictory mode
      // is `unknown` in the shared reading and still renders the rest of the projection.
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
        // Optional owner-recorded delivery. Absent stays unknown; an off-contract record is shown
        // as unreadable instead of being rendered as merge or deployment facts.
        delivery: readDelivery(job.delivery),
      })),
      truncated: record.truncated,
    },
  }
}

function callsText(value: number | null): string {
  return value == null ? "확인 불가" : `${formatNumber(value)}회`
}

/**
 * Dependency verdict for one job from the sampled jobs only (SPEC "Consolidated follow-up", UI correction):
 * - `confirmed_unmet`: at least one prerequisite is in the sample and is not `accepted` (wins even if another is absent);
 * - `unknown`: no confirmed non-accepted prerequisite, but at least one prerequisite is outside the sample, so
 *   its status cannot be read here and is never inferred as unmet;
 * - `all_accepted`: every prerequisite is in the sample and `accepted`;
 * - `none`: the job has no dependencies.
 */
type DependencyState = "none" | "confirmed_unmet" | "unknown" | "all_accepted"

function dependencyState(job: FleetJob, jobsById: Map<string, FleetJob>): DependencyState {
  if (job.dependencies.length === 0) return "none"
  const sampled = job.dependencies.map((dep) => jobsById.get(dep))
  if (sampled.some((prerequisite) => prerequisite && prerequisite.status !== "accepted")) return "confirmed_unmet"
  if (sampled.some((prerequisite) => !prerequisite)) return "unknown"
  return "all_accepted"
}

const DEPENDENCY_STATE: Record<DependencyState, { label: string; tone: Tone; note: string }> = {
  none: { label: "없음", tone: "neutral", note: "의존성 없음" },
  confirmed_unmet: { label: "미충족 확인", tone: "error", note: "표본 안 선행 작업이 검토 수락이 아님 · 이 작업만 막힘" },
  unknown: { label: "표본 밖 · 알 수 없음", tone: "unknown", note: "선행 작업이 표본 밖이라 상태를 읽지 못함 · 미충족으로 세지 않음 · 충족도 아님" },
  all_accepted: { label: "모두 검토 수락 (표본)", tone: "success", note: "표본 안 선행 작업이 모두 검토 수락 · admission 은 별도" },
}

function countBy(jobs: FleetJob[]): Record<string, number> {
  const counts: Record<string, number> = {}
  for (const job of jobs) counts[job.status] = (counts[job.status] ?? 0) + 1
  return counts
}

function statusSummary(jobs: FleetJob[]): string {
  const counts = countBy(jobs)
  const keys = [...JOB_STATUS_ORDER.filter((k) => counts[k]), ...Object.keys(counts).filter((k) => !JOB_STATUS_ORDER.includes(k)).sort()]
  return keys.length ? keys.map((k) => `${jobStatus(k).label} ${formatNumber(counts[k])}`).join(" · ") : "표본 안에 작업 없음 (비어 있음)"
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

function Unknown({ children = "확인 불가" }: { children?: React.ReactNode }) {
  return <span className="text-unknown">{children}</span>
}

function shortRevision(revision: string): string {
  return revision.slice(0, 12)
}

/**
 * One job's owner-recorded delivery. Only what the owner wrote is shown, labelled as owner report:
 * merge and deploy stay separate lines, a null deployed revision is 확인 불가 (not 미배포), and no
 * record at all is unknown. Nothing here is independent verification of GitHub or of a deployment.
 */
function Delivery({ delivery }: { delivery: FleetDelivery | null | false }) {
  if (delivery === false) {
    return <span className="text-xs text-unknown break-words">기록 형식 불일치 · 계약(urn:zeus:owner-delivery:1)과 달라 표시하지 않음 · 확인 불가</span>
  }
  if (delivery === null) {
    return <span className="text-xs text-muted-foreground break-words">소유자 기록 없음 · 병합·배포 여부 확인 불가 (미배포 증거 아님)</span>
  }
  return (
    <div className="flex flex-col gap-1 text-xs break-words">
      <StatusBadge tone="neutral" className="self-start" title="소유자가 보존된 증거를 확인하고 직접 기록한 문서 · 독립 검증 아님">소유자 기록 (owner_recorded)</StatusBadge>
      <span>후보 <span className="font-mono">{shortRevision(delivery.candidate_revision)}</span> · 병합 <span className="font-mono">{shortRevision(delivery.merge_revision)}</span></span>
      <span>배포 {delivery.deployed_revision ? <span className="font-mono">{shortRevision(delivery.deployed_revision)}</span> : <Unknown>기록 없음 · 배포 여부 확인 불가</Unknown>}</span>
      <span className="text-muted-foreground">기록 시각 {formatTime(delivery.recorded_at)} · 증거 {formatNumber(delivery.evidence_refs.length)}건</span>
      {delivery.report_url ? (
        <a className="underline break-all" href={delivery.report_url} rel="noreferrer noopener" target="_blank">{delivery.report_url}</a>
      ) : <span className="text-muted-foreground">보고 링크 없음</span>}
    </div>
  )
}

export function FleetView({ snapshot, now }: Props) {
  const envelope = snapshot?.sources?.fleet
  const fresh = fleetFreshness(snapshot, now)
  const parsed: Parsed = envelope && envelope.status === "ok" ? readFleet(envelope.data) : { ok: false, reason: "정상 응답 아님" }
  const data = parsed.ok ? parsed.data : null
  const registered: FleetRegistered | null = data && data.registered ? data : null
  const current = fresh.state === "fresh"

  const header = (
    <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
      <div className="min-w-0">
        <h2 className="text-lg font-semibold inline-flex items-center gap-2"><Users aria-hidden="true" className="size-4" />팀 작업</h2>
        <p className="text-sm text-muted-foreground break-words">fleet 제어면의 읽기 전용 투영 · 소유자가 넣은 운영(operation)만 · 조회 전용(제어 없음) · 등록 여부는 서비스 생존과 다름</p>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <StatusBadge tone={!envelope && snapshot ? "unknown" : freshnessTone(fresh.state)}>
          {!envelope && snapshot ? "출처 미제공" : fresh.state === "fresh" ? "최신" : fresh.state === "stale" ? "오래됨" : fresh.state === "invalid" ? "시각 무효" : fresh.reason || "수집 실패"}
        </StatusBadge>
        <span className="text-xs text-muted-foreground">관측 {formatTime(fresh.observed_at)} · 경과 {formatSeconds(fresh.age)}</span>
      </div>
    </div>
  )

  // Unknown branches first: each is "확인 불가" with its own cause, never an empty board.
  if (!snapshot) {
    return <div className="flex flex-col gap-4">{header}<Alert variant="destructive"><AlertTitle>응답 없음</AlertTitle><AlertDescription>아직 정상 응답을 받지 못했습니다. 팀·작업 수는 0이 아니라 알 수 없음입니다.</AlertDescription></Alert></div>
  }
  if (!envelope) {
    return (
      <div className="flex flex-col gap-4">{header}
        <Alert><CircleHelp aria-hidden="true" /><AlertTitle>이 스냅샷에는 fleet 출처가 없습니다</AlertTitle>
          <AlertDescription className="break-words">수집기가 `sources.fleet` 를 아직 제공하지 않습니다(이전 계약의 스냅샷). 비어 있음이나 수집 실패가 아니라 확인 불가이며, 다른 화면과 보고서는 영향을 받지 않습니다.</AlertDescription></Alert>
      </div>
    )
  }
  if (fresh.state === "unavailable") {
    return (
      <div className="flex flex-col gap-4">{header}
        <Alert variant="destructive"><AlertTitle>fleet 출처 수집 실패</AlertTitle>
          <AlertDescription className="break-words">상태 {envelope.status ?? "없음"}{envelope.error ? ` · ${envelope.error}` : ""} · 관측 {formatTime(fresh.observed_at)}. 팀·작업 상태는 알 수 없음이며 비어 있음이 아닙니다. 이 화면은 마지막 정상 fleet 기록을 보존하지 않습니다.</AlertDescription></Alert>
      </div>
    )
  }
  if (!parsed.ok || !data) {
    return (
      <div className="flex flex-col gap-4">{header}
        <Alert variant="destructive"><AlertTitle>fleet 데이터 해석 불가</AlertTitle>
          <AlertDescription className="break-words">{parsed.ok ? "data 없음" : parsed.reason} · 기대 스키마 {FLEET_SCHEMA}. 계약과 다른 응답은 표시하지 않습니다(확인 불가).</AlertDescription></Alert>
      </div>
    )
  }

  const notices = (
    <>
      {fresh.state === "invalid" ? (
        <Alert variant="destructive"><AlertTitle>관측 시각 무효</AlertTitle><AlertDescription className="break-words">{fresh.reason}. 아래 내용은 언제 읽은 것인지 알 수 없으므로 현재 상태로 해석하지 마세요.</AlertDescription></Alert>
      ) : null}
      {fresh.state === "stale" ? (
        <Alert><AlertTriangle aria-hidden="true" /><AlertTitle>오래된 관측</AlertTitle><AlertDescription className="break-words">관측 {formatTime(fresh.observed_at)} · 경과 {formatSeconds(fresh.age)} 기준입니다. 현재 상태가 아니며, 그 뒤의 admission·종료는 반영되지 않았습니다.</AlertDescription></Alert>
      ) : null}
    </>
  )

  if (!registered) {
    return (
      <div className="flex flex-col gap-4">{header}{notices}
        <Alert><AlertTitle>등록된 fleet 없음</AlertTitle><AlertDescription className="break-words">중앙 저장소에 fleet 정의가 없습니다(비어 있음 · 확인 불가 아님). `zeus fleet register` 는 소유자가 호스트에서 실행하며 이 화면에는 제어가 없습니다.</AlertDescription></Alert>
      </div>
    )
  }

  const jobsById = new Map(registered.jobs.map((job) => [job.id, job]))
  const activeLanes = registered.lanes.filter((lane) => lane.active_job != null)
  const ownedJobs = registered.jobs.filter((job) => OWNED_STATUSES.has(job.status))
  const activeOutsideSample = activeLanes.filter((lane) => lane.active_job != null && !jobsById.has(lane.active_job))
  const counts = countBy(registered.jobs)
  const teams = [...new Set([...registered.lanes.map((lane) => lane.team), ...registered.jobs.map((job) => job.team)])].sort()
  const sampleNote = registered.truncated ? "최근 100건 표본 · 잘림 · 전체 아님" : "표본 기준 · 잘리지 않음"
  // Consolidated follow-up: a prerequisite outside the sample has unknown status here. Only a sampled
  // non-accepted prerequisite confirms "unmet"; absence alone is never counted as unmet.
  const queuedDependencyStates = registered.jobs.filter((job) => job.status === "queued" && job.dependencies.length).map((job) => dependencyState(job, jobsById))
  const confirmedUnmet = queuedDependencyStates.filter((state) => state === "confirmed_unmet").length
  const dependencyUnknown = queuedDependencyStates.filter((state) => state === "unknown").length
  // One shared reading for the strip, the notice and the reading guide below: the numbers are the
  // wire values in every mode, but only finite mode calls them ceilings.
  // Owner delivery is decoded per job; a job without a record stays unknown and is not counted here.
  // `null` (no record) and `false` (off-contract) are both falsy, so a truthy `delivery` is the
  // readable record itself; the unreadable ones are counted separately below.
  const deliveryRecorded = registered.jobs.filter((job) => job.delivery).length
  const deliveryDeployed = registered.jobs.filter((job) => job.delivery && job.delivery.deployed_revision).length
  const deliveryUnreadable = registered.jobs.filter((job) => job.delivery === false).length
  const accounting = registered.accounting
  const budgetNumbers = `${formatNumber(registered.budget.per_host)} / ${formatNumber(registered.budget.total)}`
  const accountingCard = accountingDisplay(accounting, budgetNumbers)

  return (
    <div className="flex min-w-0 flex-col gap-4">
      {header}
      {notices}

      {registered.paused ? (
        <Alert><Pause aria-hidden="true" /><AlertTitle>admission 일시 정지</AlertTitle>
          <AlertDescription className="break-words">새 작업은 배정되지 않습니다. 이미 배정된(dispatching) 작업은 완료까지 진행되며 강제 종료되지 않습니다. 재개는 소유자의 `zeus fleet resume` 이며 이 화면에는 제어가 없습니다.</AlertDescription></Alert>
      ) : null}
      {ownedJobs.length || activeLanes.length ? (
        <Alert variant={ownedJobs.some((job) => job.status === "unknown") ? "destructive" : "default"}><Lock aria-hidden="true" />
          <AlertTitle>소유권 보유 중 · 레인 {formatNumber(activeLanes.length)} · 표본 안 {formatNumber(ownedJobs.length)}건</AlertTitle>
          <AlertDescription className="break-words">
            배정됨·알 수 없음 작업은 레인·용량·경로 예약을 유지합니다. 자동 시간 초과, 인계, 재시도는 없습니다.
            {ownedJobs.some((job) => job.status === "unknown") ? " 알 수 없음은 시작·종료·PG 읽기가 불확실한 상태이며 실패도 성공도 아닙니다. 서비스 재시작 후에는 reconciliation_required 로 보고되고 여기서는 해제되지 않습니다." : ""}
            {activeOutsideSample.length ? ` 표본 밖 활성 작업: ${activeOutsideSample.map((lane) => `${lane.id} → ${lane.active_job}`).join(", ")} (목록에 없음).` : ""}
          </AlertDescription></Alert>
      ) : null}
      {accounting.mode === "unknown" ? (
        <Alert><CircleHelp aria-hidden="true" /><AlertTitle>호출 회계 방식 확인 불가</AlertTitle>
          <AlertDescription className="break-words">{accounting.detail} 아래 호출 수치를 적용 중인 상한으로 읽지 마세요. 확인 불가이며 상한 없음도 아닙니다. 다른 항목(admission·레인·작업)은 그대로 표시합니다.</AlertDescription></Alert>
      ) : null}
      {registered.truncated ? (
        <Alert><AlertTriangle aria-hidden="true" /><AlertTitle>작업 목록이 잘렸습니다</AlertTitle><AlertDescription>최근 100건까지만 읽었습니다. 아래 건수와 팀별 분포는 표본 기준이며 전체 합계가 아닙니다. 레인의 활성 작업은 표본 밖도 포함합니다. 표본 밖 선행 작업의 상태는 알 수 없음이며 의존성 미충족으로 세지 않습니다.</AlertDescription></Alert>
      ) : null}

      <div className="grid grid-cols-2 gap-2 lg:grid-cols-4">
        <StatCard title="admission" value={registered.paused ? "일시 정지" : "열림"} note={registered.paused ? "신규 배정 차단 · 실행 중 완료 허용" : "열림 ≠ 서비스 실행 중 · 생존 신호 없음"} icon={registered.paused ? <Pause className="size-4" /> : <Workflow className="size-4" />} />
        <StatCard title="동시 실행 상한" value={`${formatNumber(activeLanes.length)} / ${formatNumber(registered.max_parallel)}`} note={`활성 레인 / max_parallel · 레인 ${formatNumber(registered.lanes.length)}개`} icon={<Layers className="size-4" />} />
        <StatCard title={`${ACCOUNTING_TITLE} · ${accounting.label}`} value={accountingCard.value ?? <Unknown>회계 방식 확인 불가</Unknown>} note={accountingCard.note} icon={<ShieldCheck className="size-4" />} />
        <StatCard title="검토 수락 (표본)" value={current ? formatNumber(counts.accepted ?? 0) : <Unknown>{formatNumber(counts.accepted ?? 0)} · 현재 아님</Unknown>} note={`독립 검토 수락 · 병합·배포·완료 아님 · 소유자 병합 기록 있는 작업 ${formatNumber(deliveryRecorded)}건 (표본) · 나머지는 확인 불가이며 미배포 증거 아님`} icon={<ListChecks className="size-4" />} />
      </div>

      <Card size="sm" className="min-w-0">
        <CardHeader>
          <CardTitle>소유자 → 레인 → 검토 경로</CardTitle>
          <CardDescription className="flex flex-wrap items-center gap-2">
            <StatusBadge tone="unknown">개념 경로 · 개별 작업의 실제 이동을 추적한 것이 아님</StatusBadge>
            <span>fleet {registered.id} · {sampleNote}</span>
          </CardDescription>
        </CardHeader>
        <CardContent>
          <ol className="grid grid-cols-1 gap-2 lg:grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)_auto_minmax(0,1fr)_auto_minmax(0,1fr)_auto_minmax(0,1fr)] lg:items-stretch">
            <li className="contents">
              <FlowNode icon={Users} title="1. 소유자 등록·투입" tone="neutral" badge="명시적 enqueue 만" lines={[`레인 ${formatNumber(registered.lanes.length)}개 · 팀 ${formatNumber(teams.length)}개`, "생성된 백로그 없음 · 매니페스트는 소유자 설계"]} />
            </li>
            <li className="contents"><FlowArrow />
              <FlowNode icon={Workflow} title="2. admission" tone={registered.paused ? "warning" : "neutral"} badge={registered.paused ? "일시 정지 · 신규 차단" : "열림"} lines={[`상한 ${formatNumber(registered.max_parallel)} · 레인당 1개 · 경로 충돌 배제`, `대기 ${formatNumber(counts.queued ?? 0)}건 (표본)`, `의존성 미충족 확인 ${formatNumber(confirmedUnmet)}건 · 표본 밖 의존성(알 수 없음) ${formatNumber(dependencyUnknown)}건`, "확인 = 표본 안 선행 작업이 검토 수락 아님 · 표본 밖은 미충족으로 세지 않음"]} />
            </li>
            <li className="contents"><FlowArrow />
              <FlowNode icon={GitBranch} title="3. 레인 실행" tone={activeLanes.length ? "warning" : "neutral"} badge={`활성 레인 ${formatNumber(activeLanes.length)} / ${formatNumber(registered.max_parallel)}`} lines={["기존 `zeus operate run` · 격리 컨테이너 · 소유 토큰", "자식 출력만으로 수락 판정 없음"]} />
            </li>
            <li className="contents"><FlowArrow />
              <FlowNode icon={ShieldCheck} title="4. 독립 검토 → 종단 상태" tone={counts.unknown ? "unknown" : (counts.failed || counts.rejected || counts.exhausted) ? "error" : counts.accepted ? "success" : "neutral"} badge={statusSummary(registered.jobs.filter((job) => !["queued", "dispatching"].includes(job.status)))} lines={["수락 = 종료 코드 0 + 레인 운영 기록 일치 + 검토 수락", "병합·배포 아님 · 자동 재시도 없음", `소유자 병합 기록 ${formatNumber(deliveryRecorded)}건 · 그중 배포 기록 ${formatNumber(deliveryDeployed)}건 (표본) · 기록 없는 작업은 확인 불가`]} />
            </li>
            <li className="contents"><FlowArrow />
              <FlowNode icon={ListChecks} title="5. 읽기 전용 투영 (이 화면)" tone={freshnessTone(fresh.state)} badge={fresh.state === "fresh" ? "최신" : fresh.state === "stale" ? "오래됨 · 현재 아님" : "시각 무효"} lines={[`관측 ${formatTime(fresh.observed_at)}`, "PG 만 읽음 · 쓰기·예약·제공자 연결 없음"]} />
            </li>
          </ol>
        </CardContent>
      </Card>

      <section aria-label="팀별 현황" className="flex flex-col gap-3">
        <h3 className="text-base font-semibold">팀별 현황 <span className="text-xs font-normal text-muted-foreground">· {sampleNote}</span></h3>
        {teams.length === 0 ? <p className="text-sm text-muted-foreground border rounded-lg p-4">레인이 없습니다 (등록됨 · 비어 있음)</p> : (
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
            {teams.map((team) => {
              const lanes = registered.lanes.filter((lane) => lane.team === team)
              const jobs = registered.jobs.filter((job) => job.team === team)
              return (
                <Card key={team} size="sm" className="min-w-0">
                  <CardHeader>
                    <CardTitle className="inline-flex items-center gap-2 break-words"><Users aria-hidden="true" className="size-4 shrink-0 text-muted-foreground" />{team}</CardTitle>
                    <CardDescription className="break-words">{statusSummary(jobs)}</CardDescription>
                  </CardHeader>
                  <CardContent className="flex flex-col gap-2">
                    {lanes.length === 0 ? <p className="text-xs text-muted-foreground">이 팀에 등록된 레인 없음 · 작업 기록만 있음</p> : (
                      <ul className="flex flex-col gap-1 text-xs">
                        {lanes.map((lane) => (
                          <li key={lane.id} className="flex min-w-0 flex-wrap items-center gap-2">
                            <span className="font-mono break-all">{lane.id}</span>
                            {lane.active_job ? (
                              <StatusBadge tone={jobsById.get(lane.active_job)?.status === "unknown" ? "unknown" : "warning"} title="dispatching·unknown 예약에서 도출 · 표본 밖 포함">
                                <Lock aria-hidden="true" />활성 · {lane.active_job}{jobsById.has(lane.active_job) ? "" : " (표본 밖)"}
                              </StatusBadge>
                            ) : <StatusBadge tone="neutral">비어 있음</StatusBadge>}
                          </li>
                        ))}
                      </ul>
                    )}
                  </CardContent>
                </Card>
              )
            })}
          </div>
        )}
      </section>

      <section aria-label="작업 목록" className="flex flex-col gap-3">
        <h3 className="text-base font-semibold">작업 목록 <span className="text-xs font-normal text-muted-foreground">· {formatNumber(registered.jobs.length)}건 · {sampleNote} · 수집기 순서 그대로</span></h3>
        {registered.jobs.length === 0 ? (
          <p className="text-sm text-muted-foreground border rounded-lg p-4">표본 안에 작업이 없습니다 (등록됨 · 비어 있음 · 확인 불가 아님)</p>
        ) : (
          <ul className="grid grid-cols-1 gap-3 md:grid-cols-2">
            {registered.jobs.map((job) => {
              const info = jobStatus(job.status)
              const missingDeps = job.dependencies.filter((dep) => !jobsById.has(dep))
              const depState = dependencyState(job, jobsById)
              const depInfo = DEPENDENCY_STATE[depState]
              const depRow: Array<[string, React.ReactNode]> = job.status === "queued" && job.dependencies.length
                ? [["의존성 판정", <StatusBadge tone={depInfo.tone} title={depInfo.note}>{depInfo.label}</StatusBadge>]]
                : []
              return (
                <li key={job.id} className="min-w-0">
                  <Card size="sm" className="min-w-0 h-full">
                    <CardHeader>
                      <div className="flex min-w-0 flex-wrap items-center gap-2">
                        <StatusBadge tone={info.tone} title={info.note}>{info.label}</StatusBadge>
                        <span className="font-mono text-xs break-all">{job.id}</span>
                        <span className="text-xs text-muted-foreground break-words">{job.team || "팀 없음"} / {job.lane || "레인 없음"}</span>
                      </div>
                      <CardTitle className="text-sm break-words">{job.goal.criterion || <Unknown>기준 없음</Unknown>}</CardTitle>
                      <CardDescription className="font-mono text-xs break-all">{job.goal.path || "경로 없음"}</CardDescription>
                    </CardHeader>
                    <CardContent>
                      <KeyValue items={[
                        ["상태 뜻", <span className="text-xs">{info.note}</span>],
                        ["운영 ID", <span className="font-mono text-xs break-all">{job.operation_id || <Unknown>없음</Unknown>}</span>],
                        ["사유", job.reason_code ?? "없음"],
                        ["의존성", job.dependencies.length === 0 ? "없음" : <span className="font-mono text-xs break-all">{job.dependencies.map((dep) => {
                          const prerequisite = jobsById.get(dep)
                          return `${dep} (${prerequisite ? jobStatus(prerequisite.status).label : "표본 밖"})`
                        }).join(", ")}</span>],
                        ...depRow,
                        ["호출 예약 / 정산", `${callsText(job.calls.reserved)} / ${callsText(job.calls.settled)}`],
                        ["소유자 병합·배포 기록", <Delivery delivery={job.delivery} />],
                        ["생성", formatTime(job.created_at)],
                        ["마지막 기록", `${formatTime(job.updated_at)} · 마지막 실행 사실 · 생존 신호 아님`],
                      ]} />
                      {job.status === "queued" && job.dependencies.length ? (
                        <p className="mt-2 text-xs text-muted-foreground break-words">
                          {missingDeps.length ? `표본 밖 의존성 ${formatNumber(missingDeps.length)}건은 여기서 상태를 알 수 없으며 미충족으로 세지 않습니다. ` : ""}
                          {depState === "confirmed_unmet" ? "표본 안 선행 작업 중 검토 수락이 아닌 것이 있어 미충족으로 확인됩니다. " : ""}
                          의존성이 모두 검토 수락일 때만 배정됩니다. 실패·거부·알 수 없음 의존성은 이 작업만 막고 독립 레인은 계속 진행됩니다. 수락은 후보 수락이며 기준 base 는 바뀌지 않습니다.
                        </p>
                      ) : null}
                    </CardContent>
                  </Card>
                </li>
              )
            })}
          </ul>
        )}
      </section>

      <p className="text-xs text-muted-foreground break-words">
        읽는 법: '확인 불가'는 값을 읽지 못한 것이고 '비어 있음'은 읽었더니 없었다는 뜻입니다. '검토 수락'은 독립 검토가 후보를 수락했다는 뜻이며 병합·배포·완료가 아닙니다. 소유자 병합·배포 기록은 소유자가 직접 남긴 문서이며(owner_recorded) 이 화면의 독립 검증이 아닙니다. 병합과 배포는 따로 표시하고, 기록이 없으면 확인 불가이며 미배포의 증거가 아닙니다. '알 수 없음'은 0건이 아니며 소유권과 예약을 그대로 유지합니다. 마지막 기록 시각은 하트비트가 아닙니다.
        {deliveryUnreadable ? ` 계약과 다른 배송 기록 ${formatNumber(deliveryUnreadable)}건은 표시하지 않았습니다(확인 불가).` : ""}
        {accounting.mode === "finite"
          ? " 이 fleet 은 유한 회계이므로 호출 수치는 실제 호출 수 상한이며 남은 금액이 아닙니다."
          : accounting.mode === "subscription"
            ? " 이 fleet 은 구독 사용량 기록이므로 호출 수 상한이 적용되지 않습니다. 표시된 수치는 보존된 이관 메타데이터이며 남은 호출·금액이나 제공자 허용량이 아닙니다."
            : " 회계 방식을 확정하지 못했으므로 표시된 호출 수치가 상한인지 알 수 없습니다."}
      </p>
    </div>
  )
}
