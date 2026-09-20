// Pure reading of the `sources.portfolio` wire contract (operating-portfolio-001 SPEC, Frontend
// batch). No React, no fetching, no writes: the 프로젝트 view renders only what these functions
// could actually read. Two rules decide every branch here:
// - off-contract data is INVALID, not empty. A missing field, a wrong type or a wrong schema makes
//   the whole projection unreadable with a named reason, instead of a board of zeros;
// - unknown values stay unknown. A criterion status that is not `accepted` is never accepted, an
//   unknown investigation state is never "resolved", and a sample is never a total.

import {
  PORTFOLIO_SCHEMA,
  type PortfolioActivity,
  type PortfolioCriterion,
  type PortfolioData,
  type PortfolioFollowUp,
  type PortfolioInvestigation,
  type PortfolioJob,
  type PortfolioProject,
} from "./snapshot"
import type { Tone } from "./tones"

/** Collector bound for the per-project job sample and the investigation rows/job IDs (SPEC). */
export const PORTFOLIO_SAMPLE = 50

export type ParsedPortfolio = { ok: true; data: PortfolioData } | { ok: false; reason: string }

function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === "object" && !Array.isArray(value)
}

function isText(value: unknown): value is string {
  return typeof value === "string"
}

/** Wire counts are non-negative finite integers; anything else is off-contract, never 0. */
function isCount(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value) && value >= 0
}

/** A wire list of opaque references: every row must be a string, or the whole list is off-contract. */
function readStrings(value: unknown): string[] | null {
  if (!Array.isArray(value)) return null
  const items: string[] = []
  for (const item of value) {
    if (!isText(item)) return null
    items.push(item)
  }
  return items
}

function readCriterion(value: unknown): PortfolioCriterion | null {
  if (!isRecord(value)) return null
  const { id, text, status } = value
  const evidence = readStrings(value.evidence_refs)
  if (!isText(id) || !id || !isText(text) || !isText(status) || !evidence) return null
  return { id, text, status, evidence_refs: evidence }
}

/**
 * One owner follow-up link, or `undefined` for off-contract (which invalidates the job, like every
 * other wrong type here). An ABSENT key is not off-contract: it means the owner recorded no link.
 */
function readFollowUp(value: unknown): PortfolioFollowUp | undefined {
  if (!isRecord(value)) return undefined
  const { successor_job_id: successor, successor_status: status, state, reason, recorded_at: at } = value
  const evidence = readStrings(value.evidence_refs)
  if (!isText(successor) || !successor || !isText(state) || !evidence) return undefined
  if (!(status === null || isText(status))) return undefined
  if (!(reason === null || isText(reason))) return undefined
  if (!(at === null || isText(at))) return undefined
  return { successor_job_id: successor, successor_status: status, state, reason, evidence_refs: evidence, recorded_at: at }
}

function readJob(value: unknown): PortfolioJob | null {
  if (!isRecord(value)) return null
  const { id, lane, status, updated_at: updatedAt } = value
  // `criterion_id` is a string on contract (a binding always names its target). `null` is tolerated
  // and rendered as unknown rather than dropped, so a collector gap stays visible.
  const criterionId = value.criterion_id
  const reasonCode = value.reason_code
  if (!isText(id) || !id || !isText(lane) || !isText(status) || !isText(updatedAt)) return null
  if (!(criterionId === null || isText(criterionId))) return null
  if (!(reasonCode === null || isText(reasonCode))) return null
  // Optional and additive: absent or explicitly null means "no link recorded for this job".
  const raw = value.follow_up
  const absent = raw === undefined || raw === null
  const followUp = absent ? null : readFollowUp(raw)
  if (followUp === undefined) return null
  return { id, criterion_id: criterionId, lane, status, reason_code: reasonCode, updated_at: updatedAt, follow_up: followUp }
}

/**
 * The full-population activity summary, `null` for an older collector that does not send one, or
 * `undefined` for off-contract. A missing summary is "확인 불가": the sample below must never be
 * counted to reconstruct it.
 */
function readActivity(value: unknown): PortfolioActivity | null | undefined {
  if (value === undefined || value === null) return null
  if (!isRecord(value)) return undefined
  const mode = value.mode
  if (!isText(mode) || !mode) return undefined
  const names = ["running", "queued", "unknown", "accepted", "unresolved_failed", "historical_failed"] as const
  const counts: Record<string, number> = {}
  for (const name of names) {
    const count = value[name]
    if (!isCount(count)) return undefined
    counts[name] = count
  }
  return {
    mode,
    running: counts.running,
    queued: counts.queued,
    unknown: counts.unknown,
    accepted: counts.accepted,
    unresolved_failed: counts.unresolved_failed,
    historical_failed: counts.historical_failed,
  }
}

function readProject(value: unknown): PortfolioProject | null {
  if (!isRecord(value)) return null
  const { id, title, outcome, source_ref: sourceRef, counts, jobs_truncated: truncated } = value
  if (!isText(id) || !id || !isText(title) || !isText(outcome) || !isText(sourceRef)) return null
  if (typeof truncated !== "boolean") return null
  if (!isRecord(counts) || !isCount(counts.criteria_total) || !isCount(counts.criteria_accepted) || !isCount(counts.jobs_total)) return null
  const totals = { criteria_total: counts.criteria_total, criteria_accepted: counts.criteria_accepted, jobs_total: counts.jobs_total }
  if (!Array.isArray(value.criteria) || !Array.isArray(value.jobs)) return null
  const criteria: PortfolioCriterion[] = []
  for (const row of value.criteria) {
    const criterion = readCriterion(row)
    if (!criterion) return null
    criteria.push(criterion)
  }
  const jobs: PortfolioJob[] = []
  for (const row of value.jobs) {
    const job = readJob(row)
    if (!job) return null
    jobs.push(job)
  }
  const activity = readActivity(value.activity)
  if (activity === undefined) return null
  return { id, title, outcome, source_ref: sourceRef, criteria, jobs, counts: totals, activity, jobs_truncated: truncated }
}

function readInvestigation(value: unknown): PortfolioInvestigation | null {
  if (!isRecord(value)) return null
  const { id, family_status: family, reason_code: reason, state, count, updated_at: updatedAt } = value
  const jobIds = readStrings(value.job_ids)
  const evidence = readStrings(value.evidence_refs)
  if (!isText(id) || !id || !isText(family) || !isText(reason) || !isText(state)) return null
  if (!isCount(count) || !jobIds || !evidence || !isText(updatedAt)) return null
  return { id, family_status: family, reason_code: reason, state, count, job_ids: jobIds, evidence_refs: evidence, updated_at: updatedAt }
}

/**
 * Narrow `envelope.data` to the portfolio wire contract without inventing values. The reason text
 * names fields only: no raw payload, path, credential or error string is echoed back to the screen.
 */
export function readPortfolio(data: unknown): ParsedPortfolio {
  if (!isRecord(data)) return { ok: false, reason: "data 없음" }
  const {
    definition_sha256: digest,
    investigations_truncated: investigationsTruncated,
    unbound_jobs: unbound,
    unclassified_failures: unclassified,
  } = data
  if (data.schema !== PORTFOLIO_SCHEMA) {
    return { ok: false, reason: `schema ${isText(data.schema) ? data.schema : "없음"} ≠ ${PORTFOLIO_SCHEMA}` }
  }
  if (!isText(digest) || !digest) return { ok: false, reason: "definition_sha256 형식 불일치" }
  if (!Array.isArray(data.projects)) return { ok: false, reason: "projects 배열 아님" }
  if (!Array.isArray(data.investigations)) return { ok: false, reason: "investigations 배열 아님" }
  if (typeof investigationsTruncated !== "boolean") return { ok: false, reason: "investigations_truncated 불리언 아님" }
  if (!isCount(unbound) || !isCount(unclassified)) {
    return { ok: false, reason: "unbound_jobs·unclassified_failures 수치 형식 불일치" }
  }
  const projects: PortfolioProject[] = []
  for (const [index, row] of data.projects.entries()) {
    const project = readProject(row)
    if (!project) return { ok: false, reason: `projects[${index}] 필드 형식 불일치 (id·title·outcome·source_ref·criteria·jobs·counts·activity·jobs_truncated)` }
    projects.push(project)
  }
  const investigations: PortfolioInvestigation[] = []
  for (const [index, row] of data.investigations.entries()) {
    const investigation = readInvestigation(row)
    if (!investigation) return { ok: false, reason: `investigations[${index}] 필드 형식 불일치 (id·family_status·reason_code·state·count·job_ids·evidence_refs·updated_at)` }
    investigations.push(investigation)
  }
  return {
    ok: true,
    data: {
      schema: PORTFOLIO_SCHEMA,
      definition_sha256: digest,
      projects,
      investigations,
      investigations_truncated: investigationsTruncated,
      unbound_jobs: unbound,
      unclassified_failures: unclassified,
    },
  }
}

export type CriterionInfo = { label: string; tone: Tone; note: string; accepted: boolean }

/**
 * Criterion status meaning. `accepted` is exactly one thing: the owner recorded an acceptance for
 * this criterion with evidence. It is never inferred from a job, and it does not mean the project,
 * the source document or the absorption behind it is finished. Any other value is unknown.
 */
export function criterionInfo(status: string): CriterionInfo {
  if (status === "accepted") {
    return { label: "수용 기록됨", tone: "success", note: "소유자가 증거와 함께 남긴 명시적 수용 기록 · 작업 상태에서 유추하지 않음 · 원본 전체 흡수 완료를 뜻하지 않음", accepted: true }
  }
  if (status === "pending") {
    return { label: "미수용", tone: "warning", note: "수용 기록 없음 · 작업이 진행 중이어도 기준은 수용되지 않음", accepted: false }
  }
  return { label: `${status} (정의되지 않은 값)`, tone: "unknown", note: "이 화면이 모르는 상태 값 · 저장된 그대로 표시 · 수용으로 세지 않음", accepted: false }
}

export type InvestigationInfo = { label: string; tone: Tone; note: string }

/**
 * Investigation state meaning. Every state stays a candidate: `researched` says an owner recorded a
 * bounded research disposition with evidence, not that a cause was confirmed, a fix ran or the
 * failures stopped. Unknown values are shown raw and never read as resolved.
 */
export function investigationInfo(state: string): InvestigationInfo {
  if (state === "research_required") {
    return { label: "조사 필요", tone: "warning", note: "반복 증상으로 모인 후보 · 소유자 판단 대기 · 자동 재시도 없음" }
  }
  if (state === "researched") {
    return { label: "조사 기록됨", tone: "neutral", note: "소유자가 증거와 함께 남긴 한정된 조사 판단 · 원인 확정·수정 완료가 아님" }
  }
  if (state === "deferred") {
    return { label: "보류", tone: "unknown", note: "소유자가 증거와 함께 보류로 기록함 · 해결된 것이 아니며 이후 실패는 계속 집계됨" }
  }
  return { label: `${state} (정의되지 않은 값)`, tone: "unknown", note: "이 화면이 모르는 상태 값 · 저장된 그대로 표시 · 해결로 읽지 않음" }
}

export type JobStatusInfo = { label: string; tone: Tone; note: string }

/**
 * Fleet job states as they appear in a portfolio binding. Same meanings as the 팀 작업 view
 * (fleet-001): that view owns its own copy and stays the authority for its screen; this one is kept
 * separate so the 프로젝트 lane cannot change it. `accepted` is a review acceptance only.
 */
const JOB_STATUS: Record<string, JobStatusInfo> = {
  queued: { label: "대기", tone: "warning", note: "admission 전 · 상한·레인·의존성·경로 충돌 검사 대기" },
  dispatching: { label: "배정됨", tone: "warning", note: "소유 토큰 보유 · 실행 중일 수 있음" },
  accepted: { label: "검토 수락", tone: "success", note: "독립 검토가 후보를 수락함 · 병합·배포 아님 · 기준 수용과도 별개" },
  rejected: { label: "검토 거부", tone: "error", note: "독립 검토가 후보를 거부함" },
  failed: { label: "실패", tone: "error", note: "정확한 실패 기록 · 자동 재시도 없음" },
  exhausted: { label: "예산 소진", tone: "error", note: "예산 소진으로 기록된 상태 · 기록 당시 기준" },
  unknown: { label: "알 수 없음", tone: "unknown", note: "시작·종료·PG 읽기 불확실 · 실패도 성공도 아님 · 소유권 유지" },
}

export function jobStatusInfo(status: string): JobStatusInfo {
  return JOB_STATUS[status] ?? { label: `${status} (정의되지 않은 상태)`, tone: "unknown", note: "이 화면이 모르는 상태 값 · 저장된 그대로 표시" }
}

/**
 * Accepted-criteria progress of one project. `accepted`/`total` are the wire counts over ALL rows.
 * `percent` is offered only when those counts agree with the criterion rows actually rendered:
 * when they do not, the bar shows nothing rather than a number the screen cannot support.
 */
export type Progress = {
  accepted: number
  total: number
  percent: number | null
  /** Wire counts and rendered criterion rows agree. */
  consistent: boolean
}

/**
 * Rounding that cannot lie in either direction: only every criterion accepted reaches 100%, and a
 * single acceptance among many never rounds down to an empty 0% bar.
 */
function percentage(accepted: number, total: number): number {
  if (accepted >= total) return 100
  const raw = Math.round((accepted / total) * 100)
  return Math.min(99, Math.max(accepted > 0 ? 1 : 0, raw))
}

export function criterionProgress(project: PortfolioProject): Progress {
  const { criteria_accepted: accepted, criteria_total: total } = project.counts
  const rendered = project.criteria.filter((criterion) => criterionInfo(criterion.status).accepted).length
  const consistent = accepted <= total && project.criteria.length === total && rendered === accepted
  return { accepted, total, percent: consistent && total > 0 ? percentage(accepted, total) : null, consistent }
}

/** Jobs of one project grouped by the criterion they were explicitly bound to. */
export function jobsByCriterion(project: PortfolioProject): Map<string, PortfolioJob[]> {
  const grouped = new Map<string, PortfolioJob[]>()
  for (const criterion of project.criteria) grouped.set(criterion.id, [])
  for (const job of project.jobs) {
    if (job.criterion_id == null) continue
    const bucket = grouped.get(job.criterion_id)
    if (bucket) bucket.push(job)
  }
  return grouped
}

/**
 * Sampled jobs whose criterion cannot be shown under a criterion above: the collector omitted the
 * target, or it names a criterion that is not in the definition document. These are displayed
 * separately instead of being hidden, and they are never counted as a criterion's work.
 */
export function unplacedJobs(project: PortfolioProject): PortfolioJob[] {
  const defined = new Set(project.criteria.map((criterion) => criterion.id))
  return project.jobs.filter((job) => job.criterion_id == null || !defined.has(job.criterion_id))
}

export type JobSample = { shown: number; total: number; truncated: boolean }

/** Displayed rows vs. all rows for one project's jobs; the two numbers are never merged. */
export function jobSample(project: PortfolioProject): JobSample {
  return { shown: project.jobs.length, total: project.counts.jobs_total, truncated: project.jobs_truncated }
}

export type FollowUpInfo = { label: string; tone: Tone; note: string; linked: boolean }

/**
 * What an owner follow-up link means on screen. `linked` is one fact only: the owner recorded an
 * accepted successor job for this preserved failure, with evidence. It is not "the incident is
 * fixed", not criterion acceptance, not a merge and not a deployment — and every other state is
 * unknown, so a link the current rows no longer support never reads as history that was handled.
 */
export function followUpInfo(followUp: PortfolioFollowUp): FollowUpInfo {
  if (followUp.state === "linked") {
    return { label: "후속 작업 연결됨", tone: "neutral", linked: true, note: "소유자가 증거와 함께 연결한 수락된 후속 작업 · 원인 해결·기준 수용·병합·배포를 뜻하지 않음 · 실패 기록은 그대로 보존됨" }
  }
  if (followUp.state === "unknown") {
    const reasons: Record<string, string> = {
      successor_missing: "연결된 후속 작업을 현재 저장소에서 찾지 못함",
      successor_not_accepted: "후속 작업이 아직 검토 수락 상태가 아님(대기·배정·알 수 없음 포함)",
      binding_missing: "원본 또는 후속 작업의 기준 연결이 현재 없음",
      target_mismatch: "후속 작업이 다른 목표·기준에 연결되어 있음",
    }
    const why = followUp.reason ? (reasons[followUp.reason] ?? `사유 ${followUp.reason} (이 화면이 모르는 값)`) : "사유 기록 없음"
    return { label: "연결 확인 불가", tone: "unknown", linked: false, note: `${why} · 기록은 남아 있으나 지금은 해결로 읽지 않음` }
  }
  return { label: `${followUp.state} (정의되지 않은 값)`, tone: "unknown", linked: false, note: "이 화면이 모르는 연결 상태 · 저장된 그대로 표시 · 해결로 읽지 않음" }
}

export type ActivityInfo = { label: string; tone: Tone; note: string }

/**
 * The headline of a project's CURRENT work. These are activity labels over fleet job states, never
 * criterion completion: `현재 실행 없음` says no job is active right now, not that the goal is
 * done, and acceptance keeps its own separate row above.
 */
export function activityInfo(mode: string): ActivityInfo {
  const known: Record<string, ActivityInfo> = {
    running: { label: "진행 중", tone: "warning", note: "배정된 작업이 있음 · 실행 중일 수 있음 · 완료·수용과는 별개" },
    queued: { label: "배정 대기", tone: "warning", note: "대기 중인 작업이 있고 배정된 작업은 없음" },
    unknown: { label: "확인 필요", tone: "unknown", note: "시작·종료가 불확실한 작업이 있음 · 실패도 성공도 아님 · 다른 상태보다 먼저 표시됨" },
    needs_attention: { label: "조치 필요", tone: "error", note: "후속 작업이 연결되지 않은 실패·거부·예산 소진 기록이 남아 있음 · 현재 실행 중인 작업은 없음" },
    idle: { label: "현재 실행 없음", tone: "neutral", note: "진행·대기·미해결 실패가 모두 없음 · 기준이 수용되었다는 뜻은 아님" },
    not_started: { label: "미착수", tone: "neutral", note: "이 목표에 연결된 작업이 아직 없음 (읽었으나 비어 있음)" },
  }
  return known[mode] ?? { label: `${mode} (정의되지 않은 값)`, tone: "unknown", note: "이 화면이 모르는 활동 값 · 저장된 그대로 표시" }
}

export type ActivitySummary = {
  /** `null` when the collector sent no summary: unavailable, never reconstructed from the sample. */
  activity: PortfolioActivity | null
  /** Needs a look now: running, queued, uncertain and unresolved failures over ALL rows. */
  attention: number
  /** Already settled records: review-accepted work and failures with a link that still holds. */
  settled: number
  /** The six disjoint counts add up to `counts.jobs_total`; if not, they are shown as unreliable. */
  consistent: boolean
}

/** Full-population activity of one project. The latest-50 sample is never counted to fill a gap. */
export function projectActivity(project: PortfolioProject): ActivitySummary {
  const activity = project.activity
  if (!activity) return { activity: null, attention: 0, settled: 0, consistent: false }
  const attention = activity.running + activity.queued + activity.unknown + activity.unresolved_failed
  const settled = activity.accepted + activity.historical_failed
  return { activity, attention, settled, consistent: attention + settled === project.counts.jobs_total }
}

export type JobGroups = {
  /** Sampled jobs that need a look: active, waiting, uncertain, or failed with no holding link. */
  attention: PortfolioJob[]
  /** Sampled review-accepted work. */
  accepted: PortfolioJob[]
  /** Sampled preserved failures whose owner link currently reads `linked`. */
  history: PortfolioJob[]
}

const FAILURE_STATUSES = ["failed", "rejected", "exhausted"]

/**
 * Split the project's job SAMPLE into the three areas the screen shows apart. A failure moves to
 * 이력 only while its link reads `linked`; an unknown link keeps it in 현재 확인 필요. A status this
 * screen does not know stays in 현재 확인 필요 rather than disappearing into history.
 */
export function groupJobs(jobs: PortfolioJob[]): JobGroups {
  const groups: JobGroups = { attention: [], accepted: [], history: [] }
  for (const job of jobs) {
    if (job.status === "accepted") groups.accepted.push(job)
    else if (FAILURE_STATUSES.includes(job.status)) {
      const linked = job.follow_up != null && followUpInfo(job.follow_up).linked
      groups[linked ? "history" : "attention"].push(job)
    } else groups.attention.push(job)   // queued, dispatching, unknown and any value we do not know
  }
  return groups
}
