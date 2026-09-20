// Pure reading of the `sources.portfolio` wire contract (operating-portfolio-001 SPEC, Frontend
// batch). No React, no fetching, no writes: the 프로젝트 view renders only what these functions
// could actually read. Two rules decide every branch here:
// - off-contract data is INVALID, not empty. A missing field, a wrong type or a wrong schema makes
//   the whole projection unreadable with a named reason, instead of a board of zeros;
// - unknown values stay unknown. A criterion status that is not `accepted` is never accepted, an
//   unknown investigation state is never "resolved", and a sample is never a total.

import {
  PORTFOLIO_SCHEMA,
  type PortfolioCriterion,
  type PortfolioData,
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
  return { id, criterion_id: criterionId, lane, status, reason_code: reasonCode, updated_at: updatedAt }
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
  return { id, title, outcome, source_ref: sourceRef, criteria, jobs, counts: totals, jobs_truncated: truncated }
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
    if (!project) return { ok: false, reason: `projects[${index}] 필드 형식 불일치 (id·title·outcome·source_ref·criteria·jobs·counts·jobs_truncated)` }
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
