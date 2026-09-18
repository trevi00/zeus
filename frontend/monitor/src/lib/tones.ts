// Tone helpers for StatusBadge. Kept out of the component module so the component file only
// exports components (react-refresh/only-export-components).

export type Tone = "success" | "warning" | "error" | "unknown" | "neutral"

export function severityTone(severity: string): Tone {
  if (severity === "critical" || severity === "error") return "error"
  if (severity === "warning") return "warning"
  if (severity === "info" || severity === "debug") return "neutral"
  return "unknown"
}

export function freshnessTone(state: string): Tone {
  if (state === "fresh") return "success"
  if (state === "stale") return "warning"
  if (state === "unavailable" || state === "invalid") return "error"
  return "unknown"
}

export function statusTone(status: string | null | undefined): Tone {
  if (!status) return "unknown"
  if (["healthy", "succeeded", "accepted", "active", "running", "ok", "recorded", "closed", "resolved"].includes(status)) return "success"
  if (["failed", "rejected", "exhausted", "unavailable", "pending_reconciliation", "unconfirmed", "blocked"].includes(status)) return "error"
  if (["pending", "retry", "queued", "stale"].includes(status)) return "warning"
  return "unknown"
}
