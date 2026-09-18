import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"

export function StatCard({ title, value, note, icon }: { title: string; value: React.ReactNode; note?: React.ReactNode; icon?: React.ReactNode }) {
  return (
    <Card size="sm" className="min-w-0">
      <CardHeader className="flex flex-row items-center justify-between gap-2">
        <CardTitle className="text-sm text-muted-foreground font-normal">{title}</CardTitle>
        {icon ? <span aria-hidden="true" className="text-muted-foreground">{icon}</span> : null}
      </CardHeader>
      <CardContent>
        <div className="text-2xl font-semibold tabular-nums break-words">{value}</div>
        {note ? <CardDescription className="mt-1">{note}</CardDescription> : null}
      </CardContent>
    </Card>
  )
}

export function KeyValue({ items }: { items: Array<[string, React.ReactNode]> }) {
  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
      {items.map(([key, value]) => (
        <div key={key} className="contents">
          <dt className="text-muted-foreground">{key}</dt>
          <dd className="min-w-0 break-words">{value}</dd>
        </div>
      ))}
    </dl>
  )
}
