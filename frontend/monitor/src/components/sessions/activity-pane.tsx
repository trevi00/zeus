import { StatusBadge } from "@/components/status-badge"
import type { EventEntry, EventLog } from "@/lib/lane-sessions"
import { formatTime } from "@/lib/snapshot"

function EventLine({ entry }: { entry: EventEntry }) {
  return (
    <li className="min-w-0 space-y-2 px-3 py-3 [overflow-wrap:anywhere]">
      <div className="flex min-w-0 flex-wrap items-center gap-2">
        <StatusBadge tone={entry.state.tone} title={entry.state.note}>{entry.state.label}</StatusBadge>
        <span className="font-medium" title={entry.event.note}>{entry.event.label}</span>
        {entry.tool !== null ? <code className="rounded bg-muted px-1.5 py-0.5">{entry.tool}</code> : null}
        {entry.item !== null ? <span>{entry.item}</span> : null}
        {entry.outcome !== null ? <StatusBadge tone={entry.outcome.tone} title={entry.outcome.note}>{entry.outcome.label}</StatusBadge> : null}
      </div>
      {entry.error !== null ? <p className="border-l-2 border-warning pl-2 font-sans font-medium">{entry.error}</p> : null}
      <div className="flex min-w-0 flex-wrap items-start justify-between gap-x-4 gap-y-2 text-muted-foreground">
        <span title={entry.occurredAt === null ? undefined : formatTime(entry.occurredAt)}>{entry.occurredText}</span>
        {entry.ref !== null ? <details className="min-w-0 max-w-full">
          <summary aria-label="전체 근거 참조 보기" className="cursor-pointer rounded underline decoration-dotted underline-offset-4 focus-visible:outline-2 focus-visible:outline-ring">
            <code title={entry.ref}>{entry.refShort}</code>
          </summary>
          <code tabIndex={0} aria-label="근거 참조 텍스트" className="mt-2 block select-all rounded border bg-background p-2 focus-visible:outline-2 focus-visible:outline-ring">{entry.ref}</code>
        </details> : null}
      </div>
      {entry.metadataKind !== "none" ? <dl className="flex min-w-0 flex-wrap gap-x-4 gap-y-2 border-t border-dashed pt-2 text-muted-foreground">
        {entry.metadata.map((item) => <div key={item.key} className="min-w-0">
          <dt className="font-sans">{item.label}</dt>
          <dd title={item.time === null ? undefined : formatTime(item.time)}>{item.value}</dd>
        </div>)}
      </dl> : null}
    </li>
  )
}

// INV-LANE-SESSIONS-001: model-owned labels and retention order only; no inferred activity or screen.
export function ActivityPane({ events }: { events: EventLog }) {
  return (
    <section aria-label="활동 이벤트" className="min-w-0 rounded-lg border bg-background/60 p-3 [overflow-wrap:anywhere]">
      <header className="mb-3 space-y-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h4 className="text-sm font-semibold">활동 이벤트</h4>
          <StatusBadge tone={events.status.tone} title={events.status.note}>{events.status.label}</StatusBadge>
        </div>
        <p className="text-sm">{events.notices.log}</p>
        <div className="space-y-1 text-xs leading-relaxed text-muted-foreground">
          <p>{events.notices.retention}</p>
          <p>{events.notices.qualification}</p>
          {events.notices.legacyResult !== null ? <p>{events.notices.legacyResult}</p> : null}
        </div>
      </header>
      {events.dropped.text !== null ? <p className="mb-3 border-l-2 border-border bg-muted/20 px-3 py-2 text-sm leading-relaxed text-muted-foreground">{events.dropped.text}</p> : null}
      {events.gapText !== null ? <p className="mb-3 rounded-md border bg-muted/30 p-3 text-sm leading-relaxed">{events.gapText}</p> : null}
      {events.entries.length > 0 ? <ol aria-label="보관 순서의 활동 이벤트" className="min-w-0 divide-y rounded-md border bg-muted/10 font-mono text-xs leading-relaxed">
        {events.entries.map((entry) => <EventLine key={entry.key} entry={entry} />)}
      </ol> : null}
    </section>
  )
}
