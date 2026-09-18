import { ArrowDown, ArrowRight, BookOpen, Lightbulb } from "lucide-react"

import { StatusBadge } from "@/components/status-badge"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Separator } from "@/components/ui/separator"
import type { Explanation } from "@/lib/report"

/**
 * Plain-language section of the pinned report. It only renders `report.explanation`, which
 * `buildReport` computed at capture: no live snapshot, clock, fetch or model call is read here, so
 * screen, print and the JSON download describe the same object. The operation distribution chart
 * and the caveat list of the same `explanation` object are drawn by `ReportVisualSummary` on the
 * first screen, so this prose section can sit behind a disclosure without hiding them.
 */
type Props = { explanation: Explanation }

export function ReportExplainer({ explanation }: Props) {
  return (
    <section aria-label={explanation.title} className="flex min-w-0 flex-col gap-4">
      <Card>
        <CardHeader>
          <CardTitle className="inline-flex items-center gap-2"><Lightbulb aria-hidden="true" className="size-4 text-primary" />{explanation.title}</CardTitle>
          <CardDescription>고정된 보고서 하나를 쉬운 말로 읽은 것 · 아래 상세 카드와 같은 숫자 · 전역 정상 판정 아님</CardDescription>
        </CardHeader>
        <CardContent>
          <ul className="flex flex-col gap-2 text-sm break-words">
            {explanation.summary.map((line) => <li key={line} className="flex gap-2"><span aria-hidden="true" className="mt-2 size-1.5 shrink-0 rounded-full bg-primary" /><span className="min-w-0">{line}</span></li>)}
          </ul>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>기록에서 보고서까지</CardTitle>
          <CardDescription className="flex flex-wrap items-center gap-2"><StatusBadge tone="unknown">{explanation.flow.label}</StatusBadge></CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <ol className="grid grid-cols-1 gap-2 md:grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)_auto_minmax(0,1fr)_auto_minmax(0,1fr)] md:items-stretch">
            {explanation.flow.steps.map((step, index) => (
              <li key={step.key} className="contents">
                {index > 0 ? (
                  <div aria-hidden="true" className="flex items-center justify-center text-muted-foreground">
                    <ArrowDown className="size-4 md:hidden" /><ArrowRight className="hidden size-4 md:block" />
                  </div>
                ) : null}
                <div className="min-w-0 rounded-lg border bg-card p-3 text-sm break-words">
                  <div className="font-medium">{step.title}</div>
                  <p className="mt-1 text-xs text-muted-foreground">{step.description}</p>
                  <dl className="mt-2 flex flex-col gap-1 text-xs">
                    {step.facts.map((item) => (
                      <div key={item.label} className="flex min-w-0 flex-col">
                        <dt className="text-muted-foreground">{item.label}</dt>
                        <dd className={item.known ? "tabular-nums" : "text-unknown"}>{item.value}</dd>
                      </div>
                    ))}
                  </dl>
                </div>
              </li>
            ))}
          </ol>
          <p className="text-xs text-muted-foreground break-words">{explanation.flow.note}</p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="inline-flex items-center gap-2"><BookOpen aria-hidden="true" className="size-4 text-primary" />읽는 법</CardTitle>
          <CardDescription>이 캡처의 한계 목록은 위 그림 요약에 항상 표시됩니다.</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <ul className="flex flex-col gap-2 text-sm break-words">
            {explanation.guide.map((line) => <li key={line} className="flex gap-2"><span aria-hidden="true" className="mt-2 size-1.5 shrink-0 rounded-full bg-muted-foreground" /><span className="min-w-0">{line}</span></li>)}
          </ul>
          <Separator />
          <p className="text-xs text-muted-foreground break-words">
            출처: {explanation.provenance.derived_from} · 생성 {explanation.provenance.generated_at} · 수집 {explanation.provenance.collected_at ?? "없음"} · 관측 로그 출처 {explanation.provenance.observations_status} ({explanation.provenance.observations_observed_at ?? "관측 시각 없음"}) · 연결 {explanation.provenance.transport_state} · {explanation.provenance.computed_by}
          </p>
          <p className="text-xs text-muted-foreground break-words">
            참고: {explanation.provenance.reference.name} @ <span className="font-mono">{explanation.provenance.reference.commit.slice(0, 12)}</span> · {explanation.provenance.reference.role}
          </p>
        </CardContent>
      </Card>
    </section>
  )
}
