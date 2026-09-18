import { cn } from "@/lib/utils"
import { Badge } from "@/components/ui/badge"

export type Tone = "success" | "warning" | "error" | "unknown" | "neutral"

const TONES: Record<Tone, string> = {
  success: "bg-success/15 text-success border-success/30",
  warning: "bg-warning/20 text-warning-foreground border-warning/40 dark:text-warning",
  error: "bg-error/15 text-error border-error/30",
  unknown: "bg-unknown/15 text-unknown border-unknown/30",
  neutral: "",
}

export function StatusBadge({ tone = "neutral", children, className }: { tone?: Tone; children: React.ReactNode; className?: string }) {
  return (
    <Badge variant="outline" className={cn(TONES[tone], className)}>
      {children}
    </Badge>
  )
}

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
