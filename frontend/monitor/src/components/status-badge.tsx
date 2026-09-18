import type * as React from "react"

import { Badge } from "@/components/ui/badge"
import { cn } from "@/lib/utils"
import type { Tone } from "@/lib/tones"

const TONES: Record<Tone, string> = {
  success: "bg-success/15 text-success border-success/30",
  warning: "bg-warning/20 text-warning-foreground border-warning/40 dark:text-warning",
  error: "bg-error/15 text-error border-error/30",
  unknown: "bg-unknown/15 text-unknown border-unknown/30",
  neutral: "",
}

type Props = React.ComponentProps<"span"> & { tone?: Tone }

/**
 * Outline badge with a Zeus tone. Accepts every span attribute (title, aria-live, ...). Unlike the
 * generated Badge it may wrap: it never exceeds its container width, so long labels (scope, error
 * detail, timestamps) break onto further lines instead of widening the document on phones.
 */
export function StatusBadge({ tone = "neutral", className, ...props }: Props) {
  return (
    <Badge
      variant="outline"
      className={cn("h-auto min-h-5 max-w-full min-w-0 text-left whitespace-normal break-words", TONES[tone], className)}
      {...props}
    />
  )
}
