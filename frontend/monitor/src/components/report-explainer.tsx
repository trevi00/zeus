import { AlertTriangle, ArrowDown, ArrowRight, BookOpen, Lightbulb } from "lucide-react"

import { StatusBadge } from "@/components/status-badge"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Separator } from "@/components/ui/separator"
import type { Explanation, ExplanationBar } from "@/lib/report"
import type { Tone } from "@/lib/tones"

/**
 * Plain-language section of the pinned report. It only renders `report.explanation`, which
 * `buildReport` computed at capture: no live snapshot, clock, fetch or model call is read here, so
 * screen, print and the JSON download describe the same object. Every colour has a text
 * equivalent; every bar carries its exact count and denominator as text.
 */
type Props = { explanation: Explanation }

function barTone(bar: ExplanationBar): Tone {
  if (!bar.known_status || bar.status === "unknown") return "unknown"
  if (bar.status === "accepted") return "success"
  if (bar.status === "running") return "warning"
  return "error"
}

const BAR_FILL: Record<Tone, string> = {
  success: "bg-success", warning: "bg-warning", error: "bg-error", unknown: "bg-unknown", neutral: "bg-muted-foreground",
}

export function ReportExplainer({ explanation }: Props) {
  const { operations } = explanation
  const denominator = operations.denominator

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
          <CardTitle>{operations.label}</CardTitle>
          <CardDescription className="break-words">
            {operations.state === "unknown" ? "확인 불가 · 관측 로그 출처를 읽지 못해 분모가 없음 (0건 아님)" : `분모 ${denominator}건 · ${operations.scope}`}
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          {operations.state === "unknown" ? (
            <p className="text-sm text-muted-foreground">막대를 그릴 값이 없습니다. 비어 있음이 아니라 알 수 없음입니다.</p>
          ) : operations.state === "empty" ? (
            <p className="text-sm text-muted-foreground">샘플 안에 운영 기록 0건 (관측 출처 정상 · 비어 있음). 모든 상태가 0건입니다.</p>
          ) : (
            <ul className="flex flex-col gap-2 text-sm" aria-label="상태별 운영 결과 건수">
              {operations.bars.map((bar) => {
                const tone = barTone(bar)
                const percent = denominator && denominator > 0 ? Math.round((bar.count / denominator) * 100) : 0
                return (
                  <li key={bar.status} className="flex min-w-0 flex-col gap-1">
                    <div className="flex min-w-0 flex-wrap items-center gap-2">
                      <StatusBadge tone={tone}>{bar.label}</StatusBadge>
                      <span className="tabular-nums">{bar.count}건 / {denominator}건{bar.count > 0 ? ` (${percent}%)` : ""}</span>
                      <span className="font-mono text-xs text-muted-foreground break-all">{bar.status}</span>
                    </div>
                    <div aria-hidden="true" className="h-2 w-full overflow-hidden rounded-sm bg-muted print:border">
                      <div className={`h-full rounded-sm ${BAR_FILL[tone]}`} style={{ width: `${percent}%` }} />
                    </div>
                  </li>
                )
              })}
            </ul>
          )}
          <p className="text-xs text-muted-foreground break-words">{operations.note}</p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="inline-flex items-center gap-2"><BookOpen aria-hidden="true" className="size-4 text-primary" />읽는 법</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <ul className="flex flex-col gap-2 text-sm break-words">
            {explanation.guide.map((line) => <li key={line} className="flex gap-2"><span aria-hidden="true" className="mt-2 size-1.5 shrink-0 rounded-full bg-muted-foreground" /><span className="min-w-0">{line}</span></li>)}
          </ul>
          <Separator />
          <div>
            <h3 className="inline-flex items-center gap-2 text-sm font-medium"><AlertTriangle aria-hidden="true" className="size-4 text-warning" />이 캡처의 한계</h3>
            <ul className="mt-2 flex flex-col gap-1 text-sm break-words">
              {explanation.caveats.map((line) => <li key={line} className="flex gap-2"><span aria-hidden="true" className="mt-2 size-1.5 shrink-0 rounded-full bg-warning" /><span className="min-w-0">{line}</span></li>)}
            </ul>
          </div>
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
