import { useId } from "react"
import { AlertTriangle, ArrowDown, ArrowRight, Camera, Container, Database, FileText, RadioTower, ScrollText, type LucideIcon } from "lucide-react"

import { StatCard } from "@/components/stat-card"
import { StatusBadge } from "@/components/status-badge"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import type { ExplanationBar, Report } from "@/lib/report"
import { CATEGORY_LABELS, CATEGORY_ORDER, SEVERITY_LABELS, SEVERITY_ORDER, SOURCE_LABELS, SOURCE_NAMES, STATE_LABELS, formatNumber, formatTime, type FreshState, type SourceName } from "@/lib/snapshot"
import { freshnessTone, severityTone, type Tone } from "@/lib/tones"

/**
 * Picture-first head of the pinned report (Sterk #82 adaptation). It renders `report` only: the
 * object `buildReport` pinned at capture, which the print view and the JSON download also describe.
 * Nothing here reads the live snapshot, the clock or a fetch, and no new count is computed: every
 * figure is a field of the report or a percentage of two such fields shown next to both numbers.
 *
 * Truth boundaries kept visible even when the detail disclosures below are collapsed:
 * - unknown (source unusable, value null) renders "확인 불가" and never a zero-height bar at 0;
 * - empty (source ok, zero rows) renders "0건 · 비어 있음";
 * - stale/failed/invalid sources keep their freshness label and observed time on the diagram;
 * - sample truncation, uninterpretable values and capture times sit on the diagram nodes;
 * - the source-to-report path is labelled conceptual: it is not a trace of individual records.
 */
type Props = { report: Report }

type Bar = { key: string; label: string; count: number; tone: Tone; known: boolean }
type Chart = { state: "unknown" | "empty" | "observed"; denominator: number | null; bars: Bar[] }

const BAR_FILL: Record<Tone, string> = {
  success: "bg-success", warning: "bg-warning", error: "bg-error", unknown: "bg-unknown", neutral: "bg-primary",
}
const NODE_BORDER: Record<Tone, string> = {
  success: "border-success/50", warning: "border-warning/60", error: "border-error/50", unknown: "border-unknown/50", neutral: "border-border",
}
const SOURCE_ICONS: Record<SourceName, LucideIcon> = {
  database: Database, observations: ScrollText, docker: Container, redis: RadioTower,
}

/** Ordered bars for a stored count record: known keys first (zero included), undefined keys after, raw. */
function countChart(record: Record<string, number> | null, total: number | null, order: string[], labels: Record<string, string>, toneOf: (key: string) => Tone): Chart {
  if (!record || total == null) return { state: "unknown", denominator: null, bars: [] }
  const bars: Bar[] = order.map((key) => ({ key, label: labels[key] ?? key, count: record[key] ?? 0, tone: toneOf(key), known: true }))
  for (const key of Object.keys(record).filter((k) => !order.includes(k)).sort()) {
    bars.push({ key, label: `${key} (정의되지 않은 값)`, count: record[key], tone: "unknown", known: false })
  }
  return { state: total === 0 ? "empty" : "observed", denominator: total, bars }
}

function operationChart(operations: Report["explanation"]["operations"]): Chart {
  const toneOf = (bar: ExplanationBar): Tone => {
    if (!bar.known_status || bar.status === "unknown") return "unknown"
    if (bar.status === "accepted") return "success"
    if (bar.status === "running") return "warning"
    return "error"
  }
  return {
    state: operations.state,
    denominator: operations.denominator,
    bars: operations.bars.map((bar) => ({ key: bar.status, label: bar.label, count: bar.count, tone: toneOf(bar), known: bar.known_status })),
  }
}

function sumOf(record: Record<string, number> | null): number | null {
  if (!record) return null
  return Object.values(record).reduce((acc, value) => acc + (Number.isFinite(value) ? value : 0), 0)
}

function Unknown({ children = "확인 불가" }: { children?: React.ReactNode }) {
  return <span className="text-unknown">{children}</span>
}

function BarChart({ title, description, chart, footnote }: { title: string; description: React.ReactNode; chart: Chart; footnote?: React.ReactNode }) {
  const headingId = useId()
  const denominator = chart.denominator ?? 0
  return (
    <Card size="sm" className="min-w-0">
      <CardHeader>
        <CardTitle id={headingId}>{title}</CardTitle>
        <CardDescription className="break-words">{description}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-2">
        {chart.state === "unknown" ? (
          <p className="rounded-md border border-dashed border-unknown/50 px-3 py-2 text-sm text-unknown break-words">확인 불가 · 관측 로그 출처를 읽지 못해 분모가 없음 · 0건이 아니라 알 수 없음</p>
        ) : chart.state === "empty" ? (
          <p className="rounded-md border border-dashed px-3 py-2 text-sm text-muted-foreground break-words">0건 · 샘플 안에서 없음 (관측 출처 정상 · 비어 있음 · 알 수 없음 아님)</p>
        ) : (
          <ul aria-labelledby={headingId} className="flex flex-col gap-1.5 text-sm">
            {chart.bars.map((bar) => {
              const percent = denominator > 0 ? Math.round((bar.count / denominator) * 100) : 0
              return (
                <li key={bar.key} className="flex min-w-0 flex-col gap-0.5">
                  <div className="flex min-w-0 flex-wrap items-baseline justify-between gap-x-2">
                    <span className={`min-w-0 break-words text-xs ${bar.known ? "" : "text-unknown"}`}>{bar.label}</span>
                    <span className="tabular-nums text-xs">{formatNumber(bar.count)}건 / {formatNumber(denominator)}건 ({percent}%)</span>
                  </div>
                  <div aria-hidden="true" className="report-bar h-2 w-full overflow-hidden rounded-sm bg-muted print:border">
                    <div className={`h-full rounded-sm ${BAR_FILL[bar.tone]}`} style={{ width: `${percent}%`, minWidth: bar.count > 0 ? "3px" : 0 }} />
                  </div>
                </li>
              )
            })}
          </ul>
        )}
        {footnote ? <p className="text-xs text-muted-foreground break-words">{footnote}</p> : null}
      </CardContent>
    </Card>
  )
}

function Node({ icon: Icon, title, tone, badge, lines }: { icon: LucideIcon; title: string; tone: Tone; badge: string; lines: string[] }) {
  return (
    <div className={`flex min-w-0 flex-col gap-1 rounded-lg border-2 bg-card p-2 text-xs break-words ${NODE_BORDER[tone]}`}>
      <div className="flex min-w-0 items-center gap-1.5 font-medium"><Icon aria-hidden="true" className="size-3.5 shrink-0 text-muted-foreground" /><span className="min-w-0 break-words">{title}</span></div>
      <StatusBadge tone={tone} className="self-start">{badge}</StatusBadge>
      {lines.map((line) => <div key={line} className="text-muted-foreground">{line}</div>)}
    </div>
  )
}

function Arrow() {
  return (
    <div aria-hidden="true" className="flex items-center justify-center text-muted-foreground">
      <ArrowDown className="size-4 sm:hidden" /><ArrowRight className="hidden size-4 sm:block" />
    </div>
  )
}

export function ReportVisualSummary({ report }: Props) {
  const diagramId = useId()
  const caveatsId = useId()
  const unknownObservations = !report.observations.available
  const sample = report.completeness.sample
  const unknownValues = report.completeness.unknown
  const operations = report.explanation.operations
  const transportTone: Tone = report.transport.state === "ok" ? "success" : report.transport.state === "pending" ? "warning" : "error"

  const categoryChart = countChart(report.counts.by_category, report.counts.events_total, CATEGORY_ORDER, CATEGORY_LABELS, () => "neutral")
  const severityChart = countChart(report.counts.by_severity, report.counts.events_total, SEVERITY_ORDER, SEVERITY_LABELS, severityTone)
  const opChart = operationChart(operations)
  const categorySum = sumOf(report.counts.by_category)
  const severitySum = sumOf(report.counts.by_severity)
  const sampleLabel = sample ? `버킷당 ${formatNumber(sample.limit_per_bucket)}행 · ${sample.truncated ? "잘림" : "잘리지 않음"}` : "샘플 한계 확인 불가"

  return (
    <section aria-label="그림으로 보는 고정 보고서" className="flex min-w-0 flex-col gap-3">
      <div className="grid grid-cols-2 gap-2 lg:grid-cols-4">
        <StatCard title="이벤트 (샘플)" value={report.counts.events_total == null ? <Unknown /> : formatNumber(report.counts.events_total)}
          note={unknownObservations ? "관측 출처 확인 불가 · 0 아님" : sampleLabel} />
        <StatCard title="치명·오류" value={report.critical_events_total == null ? <Unknown /> : formatNumber(report.critical_events_total)}
          note={report.critical_events == null ? "확인 불가 · 0 아님" : report.critical_events_total === 0 ? "샘플 안에서 없음 · 비어 있음" : `상위 ${formatNumber(report.critical_events.length)}건 목록은 아래 상세`} />
        <StatCard title="운영 결과" value={operations.denominator == null ? <Unknown /> : formatNumber(operations.denominator)}
          note={operations.state === "unknown" ? "확인 불가 · 0 아님" : operations.state === "empty" ? "샘플 안에 기록 없음 · 비어 있음" : `수락됨 ${formatNumber(operations.bars.find((bar) => bar.status === "accepted")?.count ?? 0)}건 · 작업 완료와 다름`} />
        <StatCard title="경보 기록" value={report.counts.alerts == null ? <Unknown /> : formatNumber(report.counts.alerts.recorded)}
          note={report.counts.alerts == null ? "확인 불가 · 0 아님" : report.counts.alerts.recorded === 0 ? "샘플 안에서 없음 · 비어 있음" : Object.entries(report.counts.alerts.by_status).map(([k, v]) => `${k} ${formatNumber(v)}`).join(" · ")} />
      </div>

      <Card size="sm" className="min-w-0">
        <CardHeader>
          <CardTitle id={diagramId}>출처 상태와 캡처 경로</CardTitle>
          <CardDescription className="flex flex-wrap items-center gap-2">
            <StatusBadge tone="unknown">개념 경로 · 개별 기록의 실제 이동을 추적한 것이 아님</StatusBadge>
            <span>상태·시각은 캡처 시점에 고정된 값</span>
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-2" role="group" aria-labelledby={diagramId}>
          <ul className="grid grid-cols-2 gap-2 sm:grid-cols-4" aria-label="출처별 캡처 시점 상태">
            {SOURCE_NAMES.map((name) => {
              const source = report.sources[name]
              const state = (source?.freshness ?? "unavailable") as FreshState
              const lines = [`관측 ${formatTime(source?.observed_at ?? null)}`]
              if (source?.error) lines.push(`오류 · ${source.error}`)
              if (name === "observations" && sample) lines.push(sampleLabel)
              return (
                <li key={name} className="contents">
                  <Node icon={SOURCE_ICONS[name]} title={SOURCE_LABELS[name]} tone={freshnessTone(state)} badge={`${STATE_LABELS[state] ?? state} · ${source?.status ?? "missing"}`} lines={lines} />
                </li>
              )
            })}
          </ul>
          <Arrow />
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] sm:items-stretch">
            <Node icon={Camera} title="읽기 전용 스냅샷 (수집)" tone={report.collected_at == null ? "error" : "neutral"}
              badge={report.collected_at == null ? "스냅샷 없음 · 정상 응답 없음" : "수집 시각 고정"}
              lines={[`수집 ${formatTime(report.collected_at)}`, `관측 범위 · ${report.scope?.label ?? "라벨 없음"}`]} />
            <Arrow />
            <Node icon={FileText} title="고정 보고서 (이 문서)" tone={transportTone}
              badge={`캡처 시점 연결 ${report.transport.state}${report.transport.detail ? ` · ${report.transport.detail}` : ""}`}
              lines={[`생성 ${formatTime(report.generated_at)}`, `마지막 정상 응답 ${report.transport.last_ok_at ? formatTime(report.transport.last_ok_at) : "없음"}`, "informational_only · 전역 상태·SLO 판정 아님"]} />
          </div>
        </CardContent>
      </Card>

      <div className="grid grid-cols-1 gap-3 lg:grid-cols-3">
        <BarChart title="분류별 이벤트" chart={categoryChart}
          description={categoryChart.state === "observed" ? `분모 이벤트 ${formatNumber(categoryChart.denominator)}건 · 샘플 기준` : categoryChart.state === "empty" ? "이벤트 0건 · 샘플 기준" : "관측 로그 출처 확인 불가"}
          footnote={categorySum != null && categoryChart.denominator != null && categorySum !== categoryChart.denominator ? `분류 합계 ${formatNumber(categorySum)}건 ≠ 이벤트 총 ${formatNumber(categoryChart.denominator)}건 · 저장된 값 그대로 표시` : "분류는 저장된 라벨이며 심각도와 다른 축입니다."} />
        <BarChart title="심각도별 이벤트" chart={severityChart}
          description={severityChart.state === "observed" ? `분모 이벤트 ${formatNumber(severityChart.denominator)}건 · 샘플 기준${unknownValues && unknownValues.severity > 0 ? ` · 해석 불가 심각도 ${formatNumber(unknownValues.severity)}건 포함` : ""}` : severityChart.state === "empty" ? "이벤트 0건 · 샘플 기준" : "관측 로그 출처 확인 불가"}
          footnote={severitySum != null && severityChart.denominator != null && severitySum !== severityChart.denominator ? `심각도 합계 ${formatNumber(severitySum)}건 ≠ 이벤트 총 ${formatNumber(severityChart.denominator)}건 · 저장된 값 그대로 표시` : "치명·오류가 우선순위 위에 옵니다. 0건은 샘플 안에서 보이지 않음입니다."} />
        <BarChart title={operations.label} chart={opChart}
          description={operations.state === "unknown" ? "관측 로그 출처 확인 불가 · 분모 없음 (0건 아님)" : `분모 ${formatNumber(operations.denominator)}건 · ${operations.scope}`}
          footnote={operations.note} />
      </div>

      <Card size="sm" className="min-w-0">
        <CardHeader>
          <CardTitle id={caveatsId} className="inline-flex items-center gap-2"><AlertTriangle aria-hidden="true" className="size-4 text-warning" />이 캡처의 한계</CardTitle>
          <CardDescription>고정 보고서의 출처·연결·샘플 한계 · 상세를 접어도 항상 표시</CardDescription>
        </CardHeader>
        <CardContent>
          <ul aria-labelledby={caveatsId} className="flex flex-col gap-1 text-sm break-words">
            {report.explanation.caveats.map((line) => <li key={line} className="flex gap-2"><span aria-hidden="true" className="mt-2 size-1.5 shrink-0 rounded-full bg-warning" /><span className="min-w-0">{line}</span></li>)}
          </ul>
        </CardContent>
      </Card>
    </section>
  )
}
