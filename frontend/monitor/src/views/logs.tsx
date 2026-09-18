import { useMemo, useState } from "react"
import { ChevronDown, ChevronRight, Filter } from "lucide-react"

import { StatusBadge, severityTone } from "@/components/status-badge"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"
import type { Retained } from "@/lib/use-snapshot"
import { CATEGORY_LABELS, CATEGORY_ORDER, SEVERITY_LABELS, SEVERITY_ORDER, formatNumber, formatTime, freshness, type EventRow, type Observations, type Snapshot } from "@/lib/snapshot"

type Props = { snapshot: Snapshot | null; retained: Retained; now: number }

function matches(row: EventRow, query: string) {
  if (!query) return true
  const haystack = [row.event_id, row.event_type, row.outcome, row.reason_code, row.execution.task_id, row.execution.role, row.component, row.correlation_id]
    .filter(Boolean).join(" ").toLowerCase()
  return haystack.includes(query)
}

export function LogsView({ snapshot, retained, now }: Props) {
  const [category, setCategory] = useState("all")
  const [severity, setSeverity] = useState("all")
  const [query, setQuery] = useState("")
  const [open, setOpen] = useState<string | null>(null)
  const observations = (retained.observations?.data as Observations | undefined) ?? null
  const state = freshness(snapshot, "observations", now)
  const rows = useMemo(() => {
    if (!observations) return []
    const needle = query.trim().toLowerCase()
    return observations.events.rows.filter((row) =>
      (category === "all" || row.category === category) && (severity === "all" || row.severity === severity) && matches(row, needle))
  }, [observations, category, severity, query])

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex flex-col gap-2">
          <h2 className="text-lg font-semibold">관측 로그</h2>
          <p className="text-sm text-muted-foreground">심각도 → 분류(운영·개발·일반) → 관측 시각 순 · 감사 행과 수집 행은 event_id로 병합</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <StatusBadge tone={state.state === "fresh" ? "success" : state.state === "stale" ? "warning" : "error"}>
            {state.state === "fresh" ? "최신" : state.state === "stale" ? "오래됨" : state.reason || "수집 실패"}
          </StatusBadge>
          {observations ? <span className="text-xs text-muted-foreground">샘플 {formatNumber(observations.events.total)}건 · 표시 상한 {observations.events.rows_limit}</span> : null}
        </div>
      </div>

      {!observations ? (
        <Alert variant="destructive"><AlertTitle>관측 로그 확인 불가</AlertTitle><AlertDescription>아직 정상 응답을 받지 못했습니다. 비어 있음과 다릅니다.</AlertDescription></Alert>
      ) : null}
      {observations && state.state !== "fresh" ? (
        <Alert><AlertTitle>보존 기록</AlertTitle><AlertDescription>마지막 정상 관측 {formatTime(retained.observations?.observed_at)} 기준입니다. 현재 상태가 아닙니다.</AlertDescription></Alert>
      ) : null}
      {observations?.sample.truncated || observations?.events.rows_truncated ? (
        <Alert><AlertTitle>잘린 샘플</AlertTitle><AlertDescription>
          {observations.sample.truncated ? `버킷당 ${observations.sample.limit_per_bucket}행 상한에 도달했습니다. ` : ""}
          {observations.events.rows_truncated ? `표시 상한 ${observations.events.rows_limit}행을 넘는 낮은 우선순위 행은 제외되었습니다.` : ""}
        </AlertDescription></Alert>
      ) : null}

      <div className="flex flex-col gap-3 md:flex-row md:items-center" role="group" aria-label="로그 필터">
        <Tabs value={category} onValueChange={setCategory}>
          <TabsList aria-label="분류 필터">
            <TabsTrigger value="all">전체</TabsTrigger>
            {CATEGORY_ORDER.map((c) => <TabsTrigger key={c} value={c}>{CATEGORY_LABELS[c]}{observations?.events.by_category[c] ? ` ${observations.events.by_category[c]}` : ""}</TabsTrigger>)}
          </TabsList>
        </Tabs>
        <Tabs value={severity} onValueChange={setSeverity}>
          <TabsList aria-label="심각도 필터">
            <TabsTrigger value="all">전체</TabsTrigger>
            {SEVERITY_ORDER.map((s) => <TabsTrigger key={s} value={s}>{SEVERITY_LABELS[s]}{observations?.events.by_severity[s] ? ` ${observations.events.by_severity[s]}` : ""}</TabsTrigger>)}
          </TabsList>
        </Tabs>
        <label className="flex items-center gap-2 md:ml-auto md:w-72">
          <Filter aria-hidden="true" className="size-4 text-muted-foreground" />
          <span className="sr-only">텍스트 검색</span>
          <Input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="event_type · task · 사유 검색" />
        </label>
      </div>

      {observations && rows.length === 0 ? (
        <p className="text-sm text-muted-foreground border rounded-lg p-4">{observations.events.total === 0 ? "샘플 안에 저장된 이벤트가 없습니다 (비어 있음 · 완전성 증거 아님)" : "필터 조건에 맞는 행이 없습니다"}</p>
      ) : null}
      {rows.length ? (
        <Table>
          <TableHeader>
            <TableRow><TableHead className="w-8"><span className="sr-only">상세</span></TableHead><TableHead>심각도</TableHead><TableHead>분류</TableHead><TableHead>이벤트</TableHead><TableHead>결과</TableHead><TableHead>관측 시각</TableHead><TableHead>실행</TableHead><TableHead>기록</TableHead></TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((row) => {
              const key = row.event_id ?? `${row.event_type}-${row.observed_at}`
              const expanded = open === key
              return (
                <RowGroup key={key} row={row} expanded={expanded} onToggle={() => setOpen(expanded ? null : key)} />
              )
            })}
          </TableBody>
        </Table>
      ) : null}
    </div>
  )
}

function RowGroup({ row, expanded, onToggle }: { row: EventRow; expanded: boolean; onToggle: () => void }) {
  return (
    <>
      <TableRow>
        <TableCell>
          <Button variant="ghost" size="icon-xs" aria-expanded={expanded} aria-label={expanded ? "상세 닫기" : "상세 열기"} onClick={onToggle}>
            {expanded ? <ChevronDown aria-hidden="true" /> : <ChevronRight aria-hidden="true" />}
          </Button>
        </TableCell>
        <TableCell><StatusBadge tone={severityTone(row.severity)}>{SEVERITY_LABELS[row.severity] ?? row.severity}</StatusBadge></TableCell>
        <TableCell>{CATEGORY_LABELS[row.category] ?? row.category}</TableCell>
        <TableCell className="font-mono text-xs max-w-64 truncate" title={row.event_type ?? ""}>{row.event_type ?? "—"}</TableCell>
        <TableCell className="text-xs">{row.outcome ?? "—"}{row.reason_code ? <span className="text-muted-foreground"> · {row.reason_code}</span> : null}</TableCell>
        <TableCell className="text-xs">{row.observed_at_valid ? formatTime(row.observed_at) : <StatusBadge tone="unknown">시각 무효</StatusBadge>}</TableCell>
        <TableCell className="text-xs font-mono">{row.execution.task_id ?? (row.execution.kind === "system" ? "system" : "—")}</TableCell>
        <TableCell className="text-xs">{row.record_kind === "audit" ? "감사 전용" : row.record_kind === "both" ? "감사+수집" : "수집"}</TableCell>
      </TableRow>
      {expanded ? (
        <TableRow>
          <TableCell colSpan={8} className="whitespace-normal bg-muted/40">
            <dl className="grid gap-x-4 gap-y-1 text-xs sm:grid-cols-2 lg:grid-cols-3">
              <Detail k="event_id" v={row.event_id} mono />
              <Detail k="관측 시각 (observed_at)" v={row.observed_at ?? "무효"} />
              <Detail k="발생 시각 (occurred_at)" v={row.occurred_at ?? "기록 없음"} />
              <Detail k="수집 시각 (collected_at)" v={row.collected_at ?? "수집 행 아님"} />
              <Detail k="감사 확인" v={row.audit_confirmed == null ? "해당 없음" : row.audit_confirmed ? "확인" : "미확인"} />
              <Detail k="구성 요소" v={row.component} />
              <Detail k="역할 / 종류" v={`${row.execution.role ?? "—"} / ${row.execution.kind ?? "—"}`} />
              <Detail k="작업 · 시도 · 세대" v={`${row.execution.task_id ?? "—"} · ${row.execution.attempt ?? "—"} · ${row.execution.generation ?? "—"}`} />
              <Detail k="process_run_id" v={row.execution.process_run_id} mono />
              <Detail k="invocation_id" v={row.execution.invocation_id} mono />
              <Detail k="correlation_id" v={row.correlation_id} mono />
              <Detail k={`근거 참조 (${row.evidence_refs.length}/${row.evidence_refs_total})`} v={row.evidence_refs.join(", ") || "없음"} mono />
            </dl>
          </TableCell>
        </TableRow>
      ) : null}
    </>
  )
}

function Detail({ k, v, mono }: { k: string; v: string | null | undefined; mono?: boolean }) {
  return (
    <div className="min-w-0">
      <dt className="text-muted-foreground">{k}</dt>
      <dd className={mono ? "font-mono break-all" : "break-words"}>{v ?? "—"}</dd>
    </div>
  )
}
