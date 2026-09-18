import { useState } from "react"
import { ExternalLink, FileText, LayoutDashboard, Palette, RefreshCw, ScrollText, type LucideIcon } from "lucide-react"

import { SourceStrip } from "@/components/source-strip"
import { StatusBadge } from "@/components/status-badge"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import { SOURCE_NAMES, STATE_LABELS, freshness } from "@/lib/snapshot"
import { useSnapshot, type TransportState } from "@/lib/use-snapshot"
import { DesignSystemView } from "@/views/design-system"
import { LogsView } from "@/views/logs"
import { OverviewView } from "@/views/overview"
import { ReportView } from "@/views/report"

type ViewName = "overview" | "logs" | "report" | "design"
const VIEWS: Array<{ id: ViewName; label: string; icon: LucideIcon }> = [
  { id: "overview", label: "개요", icon: LayoutDashboard },
  { id: "logs", label: "로그", icon: ScrollText },
  { id: "report", label: "보고서", icon: FileText },
  { id: "design", label: "디자인 시스템", icon: Palette },
]
const TRANSPORT: Record<TransportState, [string, "success" | "warning" | "error"]> = {
  pending: ["연결 확인 중", "warning"], ok: ["페이지 연결 정상", "success"], failed: ["수집 서버 연결 실패", "error"],
  timeout: ["요청 시간 초과 · 5초", "error"], invalid: ["응답 해석 실패", "error"],
}

export function App() {
  const [view, setView] = useState<ViewName>("overview")
  const { snapshot, retained, transport, inflight, now, refresh } = useSnapshot()
  const [transportText, transportTone] = TRANSPORT[transport.state]
  const warnings: string[] = []
  if (transport.state !== "ok" && transport.state !== "pending") warnings.push("최신 상태를 가져오지 못했습니다. 화면의 기록은 이전 응답이며 정상 상태로 해석하지 마세요.")
  if (snapshot) for (const name of SOURCE_NAMES) {
    const state = freshness(snapshot, name, now)
    if (state.state !== "fresh") warnings.push(`${name}: ${STATE_LABELS[state.state]}${state.reason ? ` (${state.reason})` : ""}`)
  }

  const nav = (
    <nav aria-label="주요 화면" className="flex lg:flex-col gap-1">
      {VIEWS.map(({ id, label, icon: Icon }) => (
        <Button key={id} variant={view === id ? "secondary" : "ghost"} aria-current={view === id ? "page" : undefined}
          className="justify-start flex-1 lg:flex-none" onClick={() => setView(id)}>
          <Icon aria-hidden="true" />
          <span>{label}</span>
        </Button>
      ))}
      <Button variant="ghost" asChild className="justify-start flex-1 lg:flex-none">
        <a href="/legacy"><ExternalLink aria-hidden="true" /><span>기존 상세 화면</span></a>
      </Button>
    </nav>
  )

  return (
    <div className="min-h-svh lg:grid lg:grid-cols-[220px_1fr]">
      <aside className="hidden lg:flex flex-col gap-6 border-r bg-sidebar text-sidebar-foreground p-4 no-print">
        <div>
          <p className="text-xs text-muted-foreground">ZEUS / LOCAL OBSERVATORY</p>
          <h1 className="text-base font-semibold">관측소 · 운영 모니터</h1>
        </div>
        {nav}
        <p className="mt-auto text-xs text-muted-foreground">조회 전용 · 페이지 연결 정상은 하네스 정상 판정과 다릅니다. 출처가 최신(20초 미만)일 때만 현재 상태를 주장합니다.</p>
      </aside>
      <div className="flex min-w-0 flex-col">
        <header className="sticky top-0 z-10 flex flex-col gap-3 border-b bg-background/95 px-4 py-3 backdrop-blur no-print lg:px-8">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="lg:hidden">
              <p className="text-xs text-muted-foreground">ZEUS / LOCAL OBSERVATORY</p>
              <h1 className="text-base font-semibold">관측소 · 운영 모니터</h1>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <StatusBadge tone="neutral">조회 전용</StatusBadge>
              <StatusBadge tone="neutral" title="관측 범위 라벨 · 상태나 성공 판정이 아닙니다">관측 범위 · {typeof snapshot?.scope?.label === "string" && snapshot.scope.label ? snapshot.scope.label : "라벨 없음"}</StatusBadge>
              <StatusBadge tone={transportTone} aria-live="polite">{transportText}{transport.detail ? ` · ${transport.detail}` : ""}</StatusBadge>
              <Button size="sm" variant="outline" onClick={() => void refresh()} disabled={inflight} aria-busy={inflight}>
                <RefreshCw aria-hidden="true" className={cn(inflight && "animate-spin")} />{inflight ? "갱신 중…" : "지금 갱신"}
              </Button>
            </div>
          </div>
          <div className="lg:hidden overflow-x-auto">{nav}</div>
        </header>
        <main className="flex flex-col gap-6 p-4 lg:p-8">
          <SourceStrip snapshot={snapshot} now={now} />
          {warnings.length ? (
            <Alert variant="destructive" className="no-print"><AlertDescription>{warnings.join(" · ")}</AlertDescription></Alert>
          ) : null}
          {view === "overview" ? <OverviewView snapshot={snapshot} retained={retained} now={now} /> : null}
          {view === "logs" ? <LogsView snapshot={snapshot} retained={retained} now={now} /> : null}
          {view === "report" ? <ReportView snapshot={snapshot} now={now} /> : null}
          {view === "design" ? <DesignSystemView /> : null}
          <footer className="text-xs text-muted-foreground">
            마지막 정상 응답 {transport.ok_at ? new Date(transport.ok_at).toLocaleTimeString("ko-KR") : "없음"} · 화면 {new Date(now).toLocaleTimeString("ko-KR")} · 5초마다 새로고침, 숨김 상태에서는 중단
          </footer>
        </main>
      </div>
    </div>
  )
}

export default App
