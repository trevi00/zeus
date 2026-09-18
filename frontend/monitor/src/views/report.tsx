import { useEffect, useRef, useState } from "react"
import { ChevronDown, Download, Printer, RefreshCw } from "lucide-react"

import { ReportExplainer } from "@/components/report-explainer"
import { ReportStory } from "@/components/report-story"
import { ReportVisualSummary } from "@/components/report-visual-summary"
import { KeyValue } from "@/components/stat-card"
import { StatusBadge } from "@/components/status-badge"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Separator } from "@/components/ui/separator"
import { buildReport, downloadJson, type Report } from "@/lib/report"
import { CATEGORY_LABELS, SEVERITY_LABELS, formatNumber, formatSeconds, formatTime, parseTime, type Snapshot } from "@/lib/snapshot"
import { freshnessTone, severityTone } from "@/lib/tones"
import type { Transport } from "@/lib/use-snapshot"

const TRANSPORT_NOTICE: Record<Transport["state"], string> = {
  pending: "캡처 시점에 첫 응답을 아직 받지 못했습니다.",
  ok: "",
  failed: "캡처 시점에 수집 서버 연결이 실패한 상태였습니다. 아래 내용은 마지막으로 받은 이전 응답입니다.",
  timeout: "캡처 시점에 요청이 시간 초과된 상태였습니다. 아래 내용은 마지막으로 받은 이전 응답입니다.",
  invalid: "캡처 시점에 응답을 해석하지 못한 상태였습니다. 아래 내용은 마지막으로 받은 이전 응답입니다.",
}

type Props = { snapshot: Snapshot | null; transport: Transport; now: number }

function countText(record: Record<string, number> | null, labels: Record<string, string> = {}): string {
  if (!record) return "확인 불가"
  const parts = Object.entries(record).map(([k, v]) => `${labels[k] ?? k} ${v}`)
  return parts.length ? parts.join(" · ") : "없음 (비어 있음)"
}

/**
 * Native `<details>` disclosure for long report records. Closed by default on screen so the
 * first screen stays picture-first; the summary line carries the counts or state so a collapsed
 * section still says what it holds. Printing opens every disclosure (see the beforeprint handler
 * in ReportView and the `.report-details` print rules in index.css).
 */
function Disclosure({ title, state, children }: { title: string; state: string; children: React.ReactNode }) {
  return (
    <details className="report-details group min-w-0 rounded-xl bg-card ring-1 ring-foreground/10">
      <summary className="flex min-w-0 cursor-pointer items-center gap-2 px-4 py-3 text-sm font-medium">
        <ChevronDown aria-hidden="true" className="size-4 shrink-0 text-muted-foreground transition-transform group-open:rotate-180 print:hidden" />
        <span className="min-w-0 break-words">{title}</span>
        <span className="min-w-0 break-words font-normal text-muted-foreground">· {state}</span>
      </summary>
      <div className="flex min-w-0 flex-col gap-4 px-4 pb-4">{children}</div>
    </details>
  )
}

export function ReportView({ snapshot, transport, now }: Props) {
  // The report is pinned: built once when this view is entered and again only on explicit
  // regenerate. Polls and the clock tick do not rebuild it, so the printed page and the JSON
  // download describe the same object, labelled with its own generation time.
  const [report, setReport] = useState<Report>(() => buildReport(snapshot, transport, Date.now()))
  const root = useRef<HTMLDivElement>(null)
  const generatedAt = parseTime(report.generated_at)
  const age = Number.isFinite(generatedAt) && now - generatedAt >= 0 ? now - generatedAt : null
  const newerSnapshot = snapshot != null && (snapshot.collected_at ?? null) !== report.collected_at
  const transportNotice = TRANSPORT_NOTICE[report.transport.state]
  const observationsUnknown = !report.observations.available

  // Print must include every evidence record and limitation: open the disclosures the reader left
  // closed for the duration of printing, then restore them. The CSS `::details-content` print rule
  // covers engines where beforeprint does not fire before layout; neither touches the report data.
  useEffect(() => {
    const opened: HTMLDetailsElement[] = []
    const before = () => {
      root.current?.querySelectorAll<HTMLDetailsElement>("details.report-details:not([open])").forEach((element) => {
        element.open = true
        opened.push(element)
      })
    }
    const after = () => {
      for (const element of opened.splice(0)) element.open = false
    }
    window.addEventListener("beforeprint", before)
    window.addEventListener("afterprint", after)
    return () => {
      window.removeEventListener("beforeprint", before)
      window.removeEventListener("afterprint", after)
    }
  }, [])

  const criticalState = report.critical_events == null ? "확인 불가 · 관측 출처 없음" : report.critical_events.length === 0 ? "샘플 안에서 없음 · 비어 있음" : `상위 ${report.critical_events.length}건 / 샘플 전체 ${report.critical_events_total ?? "?"}건`
  const operationsState = !report.operations ? "확인 불가 · 관측 출처 없음" : report.operations.total === 0 ? "샘플 안에 기록 없음 · 비어 있음" : `${formatNumber(report.operations.total)}건${report.operations.rows_truncated ? " · 목록 일부만" : ""}`

  return (
    <div ref={root} className="flex min-w-0 flex-col gap-4">
      <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between no-print">
        <div className="min-w-0">
          <h2 className="text-lg font-semibold">보고서</h2>
          <p className="text-sm text-muted-foreground">화면 진입 또는 재생성 시점의 스냅샷 하나에서 생성 · 자동 갱신 없음 · 로컬 저장/인쇄만 · 외부 전송 없음 · 팀 작업 이야기와 쉬운 설명은 같은 캡처에서 계산됨</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" onClick={() => setReport(buildReport(snapshot, transport, Date.now()))}><RefreshCw aria-hidden="true" />보고서 재생성</Button>
          <Button variant="outline" onClick={() => window.print()}><Printer aria-hidden="true" />인쇄 / PDF</Button>
          <Button onClick={() => downloadJson(report)} disabled={report.collected_at == null}><Download aria-hidden="true" />JSON 다운로드</Button>
        </div>
      </div>

      <p className="text-sm break-words">
        <span className="font-medium">고정 보고서 · 생성 {formatTime(report.generated_at)}</span>
        <span className="text-muted-foreground"> · {age == null ? "경과 알 수 없음" : `${formatSeconds(age)} 전`} 기준 · 이후 수신된 데이터는 반영되지 않음</span>
        {newerSnapshot ? <span className="text-muted-foreground no-print"> · 화면에는 더 새로운 스냅샷이 있음 · 필요하면 재생성</span> : null}
      </p>

      {transportNotice ? (
        <Alert variant="destructive"><AlertTitle>캡처 시점 연결 상태: {report.transport.state}{report.transport.detail ? ` · ${report.transport.detail}` : ""}</AlertTitle>
          <AlertDescription className="break-words">{transportNotice} 마지막 정상 응답 {report.transport.last_ok_at ? formatTime(report.transport.last_ok_at) : "없음"}. 이 보고서를 정상 상태의 근거로 해석하지 마세요.</AlertDescription></Alert>
      ) : null}
      {report.collected_at == null ? <Alert variant="destructive"><AlertTitle>스냅샷 없음</AlertTitle><AlertDescription>캡처 시점까지 정상 응답을 받지 못했습니다. 응답을 받은 뒤 재생성하세요.</AlertDescription></Alert> : null}
      {report.collected_at != null && observationsUnknown ? (
        <Alert variant="destructive"><AlertTitle>관측 로그 출처 확인 불가</AlertTitle>
          <AlertDescription className="break-words">observations 출처 상태 {report.observations.status}{report.observations.error ? ` · ${report.observations.error}` : ""}. 이벤트·경보·운영 결과는 알 수 없음이며 비어 있음이 아닙니다.</AlertDescription></Alert>
      ) : null}

      {/* Story first (SPEC: before aggregate metrics, never behind a disclosure), then the aggregate picture. */}
      <ReportStory story={report.story} fleet={report.fleet} />

      <ReportVisualSummary report={report} />

      <Disclosure title="쉬운 설명" state="같은 고정 보고서의 요약 · 구조 설명 · 읽는 법">
        <ReportExplainer explanation={report.explanation} />
      </Disclosure>

      <Disclosure title="범위·시각·완전성 한계" state={`수집 ${formatTime(report.collected_at)} · ${report.completeness.sample ? (report.completeness.sample.truncated ? "샘플 잘림" : "샘플 잘리지 않음") : "샘플 확인 불가"}`}>
      <Card>
        <CardHeader><CardTitle>범위와 시각</CardTitle><CardDescription>생성 시각, 수집 시각, 출처 관측 시각은 서로 다른 시각입니다.</CardDescription></CardHeader>
        <CardContent>
          <KeyValue items={[
            ["관측 범위", report.scope?.label ?? "라벨 없음"],
            ["생성 시각", formatTime(report.generated_at)],
            ["수집 시각", formatTime(report.collected_at)],
            ["캡처 시점 연결", `${report.transport.state}${report.transport.detail ? ` · ${report.transport.detail}` : ""} · 마지막 정상 응답 ${report.transport.last_ok_at ? formatTime(report.transport.last_ok_at) : "없음"}`],
            ["출처", <div className="flex flex-wrap gap-2">{Object.entries(report.sources).map(([name, s]) => <StatusBadge key={name} tone={freshnessTone(s.freshness)}>{name} · {s.freshness} · {formatTime(s.observed_at)}</StatusBadge>)}</div>],
            ["fleet 출처 (선택)", <StatusBadge tone={report.fleet.state === "registered" ? freshnessTone(report.fleet.freshness) : report.fleet.state === "unregistered" ? "neutral" : "unknown"}>{report.fleet.state} · {report.fleet.freshness} · {formatTime(report.fleet.observed_at)}</StatusBadge>],
            ["권위", "informational_only · 전역 상태·SLO·자동 수락 판정 아님"],
          ]} />
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>완전성 한계</CardTitle><CardDescription>{report.completeness.note}</CardDescription></CardHeader>
        <CardContent>
          <KeyValue items={[
            ["샘플", report.completeness.sample ? `버킷당 ${report.completeness.sample.limit_per_bucket}행 · ${report.completeness.sample.truncated ? "잘림" : "잘리지 않음"} · ${report.completeness.sample.selection}` : "확인 불가"],
            ["버킷별 읽은 행", report.completeness.sample ? Object.entries(report.completeness.sample.buckets).map(([b, m]) => `${b} ${m.scanned}${m.truncated ? "+" : ""}`).join(" · ") : "확인 불가"],
            ["알 수 없음", report.completeness.unknown ? `심각도 ${report.completeness.unknown.severity} · 분류 ${report.completeness.unknown.category} · 시각 ${report.completeness.unknown.observed_at}` : "확인 불가"],
            ["마지막 수집", !report.completeness.collection ? "확인 불가" : report.completeness.collection.last_at ? `${formatTime(report.completeness.collection.last_at)} · 지연 ${Math.floor(report.completeness.collection.lag_seconds ?? 0)}초` : "수집 영수증 없음 (알 수 없음)"],
            ["로컬 스풀", !report.completeness.local ? "확인 불가" : report.completeness.local.status !== "ok" ? `확인 불가 · ${report.completeness.local.reason}` : `미확인 ${formatNumber(report.completeness.local.unacknowledged_bytes)} 바이트 · 대기 경보 ${report.completeness.local.pending_alerts} · 로컬 종료 기록 ${report.completeness.local.pending_terminations}`],
          ]} />
        </CardContent>
      </Card>
      </Disclosure>

      <Disclosure title="건수 표 (샘플)" state={observationsUnknown ? "확인 불가 · 관측 출처 없음" : `이벤트 ${formatNumber(report.counts.events_total)}건`}>
      <Card>
        <CardHeader><CardTitle>건수 (샘플)</CardTitle>{observationsUnknown ? <CardDescription>관측 로그 출처 확인 불가 · 건수는 알 수 없음</CardDescription> : null}</CardHeader>
        <CardContent>
          <KeyValue items={[
            ["이벤트", report.counts.events_total == null ? "확인 불가" : formatNumber(report.counts.events_total)],
            ["분류별", countText(report.counts.by_category, CATEGORY_LABELS)],
            ["심각도별", countText(report.counts.by_severity, SEVERITY_LABELS)],
            ["경보", report.counts.alerts ? `${report.counts.alerts.recorded} (${countText(report.counts.alerts.by_status)})` : "확인 불가"],
            ["격리", report.counts.quarantine ? `${report.counts.quarantine.total} (${countText(report.counts.quarantine.by_reason)})` : "확인 불가"],
            ["종료 기록", report.counts.terminations ? `미확정 ${report.counts.terminations.pending} · ${countText(report.counts.terminations.by_status)}` : "확인 불가"],
          ]} />
        </CardContent>
      </Card>
      </Disclosure>

      <Disclosure title="운영 결과 목록" state={operationsState}>
      <Card>
        <CardHeader><CardTitle>운영 결과</CardTitle><CardDescription>작업 성공과 별개인 운영(operation) 결과 · 분포 그림은 위 요약</CardDescription></CardHeader>
        <CardContent>
          {!report.operations ? <p className="text-sm text-muted-foreground">확인 불가 · 관측 로그 출처 없음 (비어 있음 아님)</p> : report.operations.total === 0 ? <p className="text-sm text-muted-foreground">샘플 안에 운영 기록 없음 (비어 있음)</p> : (
            <ul className="flex flex-col gap-1 text-sm">
              {report.operations.rows.map((row, index) => <li key={row.id ?? `row-${index}`} className="flex min-w-0 flex-wrap gap-2 items-center"><StatusBadge tone={row.status === "accepted" ? "success" : row.status === "running" ? "warning" : "error"}>{row.status ?? "unknown"}</StatusBadge><span className="font-mono text-xs break-all">{row.id}</span><span className="text-muted-foreground text-xs break-words">{row.reason_code ?? ""}</span></li>)}
            </ul>
          )}
        </CardContent>
      </Card>
      </Disclosure>

      <Disclosure title="치명·오류 이벤트 목록" state={criticalState}>
      <Card>
        <CardHeader><CardTitle>치명·오류 이벤트</CardTitle><CardDescription>{report.critical_events == null ? "확인 불가 · 관측 로그 출처 없음" : `샘플 상위 ${report.critical_events.length}건 · 샘플 전체 ${report.critical_events_total ?? "?"}건`}</CardDescription></CardHeader>
        <CardContent>
          {report.critical_events == null ? (
            <p className="text-sm text-muted-foreground break-words">확인 불가 · 관측 로그 출처 {report.observations.status}{report.observations.error ? ` · ${report.observations.error}` : ""} · 비어 있음이 아니라 알 수 없음</p>
          ) : report.critical_events.length === 0 ? <p className="text-sm text-muted-foreground">샘플 안에 치명·오류 이벤트 없음 (관측 출처 정상 · 비어 있음)</p> : (
            <ul className="flex flex-col divide-y text-sm">
              {report.critical_events.map((row, index) => (
                <li key={row.event_id ?? `event-${index}`} className="py-2 flex min-w-0 flex-wrap gap-2 items-center">
                  <StatusBadge tone={severityTone(row.severity)}>{SEVERITY_LABELS[row.severity] ?? row.severity}</StatusBadge>
                  <span className="font-mono text-xs break-all">{row.event_type}</span>
                  <span className="text-xs text-muted-foreground break-words">{formatTime(row.observed_at)} · {row.outcome}{row.reason_code ? ` · ${row.reason_code}` : ""} · {row.event_id?.slice(0, 16)}</span>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
      </Disclosure>

      <Disclosure title="다음 조치와 근거 ID" state={`조치 ${report.next_actions.length}건 · 근거 참조 ${report.critical_events == null ? "확인 불가" : `${report.evidence_ids.length}개`}`}>
      <Card>
        <CardHeader><CardTitle>다음 조치와 근거 ID</CardTitle></CardHeader>
        <CardContent className="flex flex-col gap-3">
          <ol className="list-decimal pl-5 text-sm flex flex-col gap-1 break-words">{report.next_actions.map((action) => <li key={action}>{action}</li>)}</ol>
          <Separator />
          <p className="text-xs font-mono break-all">{report.critical_events == null ? "근거 참조 확인 불가 (관측 출처 없음)" : report.evidence_ids.length ? report.evidence_ids.join(" ") : "근거 참조 없음"}</p>
        </CardContent>
      </Card>
      </Disclosure>
    </div>
  )
}
