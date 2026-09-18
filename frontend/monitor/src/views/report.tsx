import { useMemo } from "react"
import { Download, Printer } from "lucide-react"

import { KeyValue } from "@/components/stat-card"
import { StatusBadge, freshnessTone, severityTone } from "@/components/status-badge"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Separator } from "@/components/ui/separator"
import { buildReport, downloadJson } from "@/lib/report"
import { CATEGORY_LABELS, SEVERITY_LABELS, formatNumber, formatTime, type Snapshot } from "@/lib/snapshot"

export function ReportView({ snapshot, now }: { snapshot: Snapshot | null; now: number }) {
  // The report is built from the last received snapshot only; the JSON download and the print view
  // share this one object, so counts, times and scope are identical across both outputs.
  const report = useMemo(() => buildReport(snapshot, now), [snapshot, now])
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between no-print">
        <div>
          <h2 className="text-lg font-semibold">보고서</h2>
          <p className="text-sm text-muted-foreground">마지막 수신 스냅샷 하나에서 생성 · 로컬 저장/인쇄만 · 외부 전송 없음</p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={() => window.print()}><Printer aria-hidden="true" />인쇄 / PDF</Button>
          <Button onClick={() => downloadJson(report)} disabled={!snapshot}><Download aria-hidden="true" />JSON 다운로드</Button>
        </div>
      </div>
      {!snapshot ? <Alert variant="destructive"><AlertTitle>스냅샷 없음</AlertTitle><AlertDescription>정상 응답을 받은 뒤에 보고서를 생성할 수 있습니다.</AlertDescription></Alert> : null}

      <Card>
        <CardHeader><CardTitle>범위와 시각</CardTitle><CardDescription>생성 시각, 수집 시각, 출처 관측 시각은 서로 다른 시각입니다.</CardDescription></CardHeader>
        <CardContent>
          <KeyValue items={[
            ["관측 범위", report.scope?.label ?? "라벨 없음"],
            ["생성 시각", formatTime(report.generated_at)],
            ["수집 시각", formatTime(report.collected_at)],
            ["출처", <div className="flex flex-wrap gap-2">{Object.entries(report.sources).map(([name, s]) => <StatusBadge key={name} tone={freshnessTone(s.freshness)}>{name} · {s.freshness} · {formatTime(s.observed_at)}</StatusBadge>)}</div>],
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
            ["마지막 수집", report.completeness.collection?.last_at ? `${formatTime(report.completeness.collection.last_at)} · 지연 ${Math.floor(report.completeness.collection.lag_seconds ?? 0)}초` : "수집 영수증 없음 (알 수 없음)"],
            ["로컬 스풀", !report.completeness.local ? "확인 불가" : report.completeness.local.status !== "ok" ? `확인 불가 · ${report.completeness.local.reason}` : `미확인 ${formatNumber(report.completeness.local.unacknowledged_bytes)} 바이트 · 대기 경보 ${report.completeness.local.pending_alerts} · 로컬 종료 기록 ${report.completeness.local.pending_terminations}`],
          ]} />
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>건수 (샘플)</CardTitle></CardHeader>
        <CardContent>
          <KeyValue items={[
            ["이벤트", formatNumber(report.counts.events_total)],
            ["분류별", report.counts.by_category ? Object.entries(report.counts.by_category).map(([k, v]) => `${CATEGORY_LABELS[k] ?? k} ${v}`).join(" · ") : "—"],
            ["심각도별", report.counts.by_severity ? Object.entries(report.counts.by_severity).map(([k, v]) => `${SEVERITY_LABELS[k] ?? k} ${v}`).join(" · ") : "—"],
            ["경보", report.counts.alerts ? `${report.counts.alerts.recorded} (${Object.entries(report.counts.alerts.by_status).map(([k, v]) => `${k} ${v}`).join(", ") || "없음"})` : "—"],
            ["격리", report.counts.quarantine ? `${report.counts.quarantine.total} (${Object.entries(report.counts.quarantine.by_reason).map(([k, v]) => `${k} ${v}`).join(", ") || "없음"})` : "—"],
            ["종료 기록", report.counts.terminations ? `미확정 ${report.counts.terminations.pending} · ${Object.entries(report.counts.terminations.by_status).map(([k, v]) => `${k} ${v}`).join(", ") || "없음"}` : "—"],
          ]} />
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>운영 결과</CardTitle><CardDescription>작업 성공과 별개인 운영(operation) 결과</CardDescription></CardHeader>
        <CardContent>
          {!report.operations ? "확인 불가" : report.operations.total === 0 ? "샘플 안에 운영 기록 없음" : (
            <ul className="flex flex-col gap-1 text-sm">
              {report.operations.rows.map((row) => <li key={row.id ?? ""} className="flex flex-wrap gap-2 items-center"><StatusBadge tone={row.status === "accepted" ? "success" : row.status === "running" ? "warning" : "error"}>{row.status ?? "unknown"}</StatusBadge><span className="font-mono text-xs">{row.id}</span><span className="text-muted-foreground text-xs">{row.reason_code ?? ""}</span></li>)}
            </ul>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>치명·오류 이벤트</CardTitle><CardDescription>샘플 상위 {report.critical_events.length}건</CardDescription></CardHeader>
        <CardContent>
          {report.critical_events.length === 0 ? <p className="text-sm text-muted-foreground">샘플 안에 치명·오류 이벤트 없음</p> : (
            <ul className="flex flex-col divide-y text-sm">
              {report.critical_events.map((row) => (
                <li key={row.event_id ?? ""} className="py-2 flex flex-wrap gap-2 items-center">
                  <StatusBadge tone={severityTone(row.severity)}>{SEVERITY_LABELS[row.severity] ?? row.severity}</StatusBadge>
                  <span className="font-mono text-xs">{row.event_type}</span>
                  <span className="text-xs text-muted-foreground">{formatTime(row.observed_at)} · {row.outcome}{row.reason_code ? ` · ${row.reason_code}` : ""} · {row.event_id?.slice(0, 16)}</span>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>다음 조치와 근거 ID</CardTitle></CardHeader>
        <CardContent className="flex flex-col gap-3">
          <ol className="list-decimal pl-5 text-sm flex flex-col gap-1">{report.next_actions.map((action) => <li key={action}>{action}</li>)}</ol>
          <Separator />
          <p className="text-xs font-mono break-all">{report.evidence_ids.length ? report.evidence_ids.join(" ") : "근거 참조 없음"}</p>
        </CardContent>
      </Card>
    </div>
  )
}
