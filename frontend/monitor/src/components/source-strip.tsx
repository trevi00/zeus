import { Clock } from "lucide-react"

import { StatusBadge, freshnessTone } from "@/components/status-badge"
import { FRESH_MS, SOURCE_LABELS, SOURCE_NAMES, STATE_LABELS, formatSeconds, formatTime, freshness, parseTime, type Snapshot } from "@/lib/snapshot"

export function SourceStrip({ snapshot, now }: { snapshot: Snapshot | null; now: number }) {
  const collectedAt = parseTime(snapshot?.collected_at)
  const collectorAge = Number.isFinite(collectedAt) && now - collectedAt >= 0 ? now - collectedAt : null
  return (
    <section aria-label="출처별 관측 시각과 신선도" className="grid gap-2 sm:grid-cols-2 xl:grid-cols-5">
      {SOURCE_NAMES.map((name) => {
        const state = freshness(snapshot, name, now)
        return (
          <div key={name} className="rounded-lg border bg-card px-3 py-2 text-xs">
            <div className="flex items-center justify-between gap-2">
              <span className="font-medium truncate">{SOURCE_LABELS[name]}</span>
              <StatusBadge tone={freshnessTone(state.state)}>{STATE_LABELS[state.state]}</StatusBadge>
            </div>
            <div className="mt-1 text-muted-foreground">
              관측 {formatTime(state.observed_at)} · 경과 {formatSeconds(state.age)}
              {state.reason ? ` · ${state.reason}` : ""}
            </div>
          </div>
        )
      })}
      <div className="rounded-lg border bg-card px-3 py-2 text-xs">
        <div className="flex items-center justify-between gap-2">
          <span className="font-medium inline-flex items-center gap-1"><Clock aria-hidden="true" className="size-3" />수집기</span>
          <StatusBadge tone={collectorAge == null ? "error" : collectorAge < FRESH_MS ? "success" : "warning"}>
            {collectorAge == null ? (snapshot ? "시각 무효" : "응답 없음") : collectorAge < FRESH_MS ? "최신" : "오래됨"}
          </StatusBadge>
        </div>
        <div className="mt-1 text-muted-foreground">수집 {formatTime(snapshot?.collected_at)} · 경과 {formatSeconds(collectorAge)}</div>
      </div>
    </section>
  )
}
