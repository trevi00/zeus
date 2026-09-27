import { SessionsPanel } from "@/components/sessions/sessions-panel"
import { laneSessionsModel } from "@/lib/lane-sessions"
import type { Snapshot } from "@/lib/snapshot"

/**
 * 세션 (INV-LANE-SESSIONS-001). Container only: the data rules live in lib/lane-sessions.ts and the
 * presentation in components/sessions/. It reads the optional `sources.lane_sessions` envelope of the live
 * snapshot, a read-only projection of every registered lane's executions; nothing here mutates, retries
 * or controls a session. `lane_sessions` is not in SOURCE_NAMES, so the source strip, header warnings,
 * retained map and pinned report are unchanged; the panel carries its own freshness and notices.
 */
type Props = { snapshot: Snapshot | null; now: number }

export function SessionsView({ snapshot, now }: Props) {
  return <SessionsPanel model={laneSessionsModel(snapshot, now)} />
}
