import { useCallback, useEffect, useRef, useState } from "react"

import { POLL_MS, REQUEST_TIMEOUT_MS, SOURCE_NAMES, type Envelope, type Snapshot, type SourceName } from "./snapshot"

export type TransportState = "pending" | "ok" | "failed" | "timeout" | "invalid"
export type Transport = { state: TransportState; ok_at: string | null; detail: string }
export type Retained = Partial<Record<SourceName, { data: unknown; observed_at: string | null }>>

/**
 * Accepted refresh contract: one in-flight request shared by button, timer and visibility resume;
 * 5s timeout; polling paused while hidden; the last good envelope per source is retained and
 * later failures never delete it. State updates replace values, so filters and views are not reset.
 */
export function useSnapshot() {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null)
  const [retained, setRetained] = useState<Retained>({})
  const [transport, setTransport] = useState<Transport>({ state: "pending", ok_at: null, detail: "" })
  const [inflight, setInflight] = useState(false)
  const [now, setNow] = useState(() => Date.now())
  const pending = useRef<Promise<void> | null>(null)

  const request = useCallback(async () => {
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS)
    try {
      const response = await fetch("/api/status", { cache: "no-store", signal: controller.signal })
      if (!response.ok) throw Object.assign(new Error(`HTTP ${response.status}`), { kind: "failed" })
      let body: unknown
      try {
        body = await response.json()
      } catch (error) {
        if (error instanceof Error && error.name === "AbortError") throw error
        throw Object.assign(new Error("JSON"), { kind: "invalid" })
      }
      if (!body || typeof body !== "object" || !("sources" in body) || typeof (body as Snapshot).sources !== "object") {
        throw Object.assign(new Error("sources 누락"), { kind: "invalid" })
      }
      const next = body as Snapshot
      setSnapshot(next)
      setRetained((previous) => {
        const merged: Retained = { ...previous }
        for (const name of SOURCE_NAMES) {
          const source: Envelope | undefined = next.sources?.[name]
          if (source && typeof source === "object" && source.status === "ok" && source.data != null) {
            merged[name] = { data: source.data, observed_at: source.observed_at ?? null }
          }
        }
        return merged
      })
      setTransport({ state: "ok", ok_at: new Date().toISOString(), detail: "" })
    } catch (error) {
      const aborted = error instanceof Error && error.name === "AbortError"
      const kind = (error as { kind?: TransportState }).kind
      setTransport((previous) => ({
        state: aborted ? "timeout" : kind ?? "failed",
        ok_at: previous.ok_at,
        detail: aborted ? "" : error instanceof Error ? error.message : String(error),
      }))
    } finally {
      clearTimeout(timer)
    }
  }, [])

  const refresh = useCallback(() => {
    if (pending.current) return pending.current
    setInflight(true)
    pending.current = request().finally(() => {
      pending.current = null
      setInflight(false)
    })
    return pending.current
  }, [request])

  useEffect(() => {
    void refresh()
    const poll = setInterval(() => {
      if (!document.hidden) void refresh()
    }, POLL_MS)
    const tick = setInterval(() => setNow(Date.now()), 1000)
    const onVisible = () => {
      if (!document.hidden) void refresh()
    }
    document.addEventListener("visibilitychange", onVisible)
    return () => {
      clearInterval(poll)
      clearInterval(tick)
      document.removeEventListener("visibilitychange", onVisible)
    }
  }, [refresh])

  return { snapshot, retained, transport, inflight, now, refresh }
}
