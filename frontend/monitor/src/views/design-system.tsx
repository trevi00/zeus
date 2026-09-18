import { AlertTriangle, CheckCircle2, CircleHelp, Info, RefreshCw } from "lucide-react"

import { StatusBadge } from "@/components/status-badge"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Separator } from "@/components/ui/separator"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"

const TOKENS: Array<[string, string]> = [
  ["background", "bg-background"], ["card", "bg-card"], ["muted", "bg-muted"], ["primary (teal)", "bg-primary"],
  ["accent", "bg-accent"], ["success", "bg-success"], ["warning", "bg-warning"], ["error", "bg-error"], ["unknown", "bg-unknown"],
]

/** Specimen of the owned shadcn/ui primitives with Zeus tokens. Static examples, no live data. */
export function DesignSystemView() {
  return (
    <div className="flex flex-col gap-6">
      <div>
        <h2 className="text-lg font-semibold">디자인 시스템</h2>
        <p className="text-sm text-muted-foreground">shadcn/ui 소스 컴포넌트 + Lucide 아이콘 · slate/zinc 중립 + teal 강조 · 간격 4/8/12/16/24/32 · 카드 반경 10px · 시스템 글꼴. 아래는 정적 예시이며 운영 수치가 아닙니다.</p>
      </div>
      <Card>
        <CardHeader><CardTitle>색 토큰</CardTitle><CardDescription>의미 토큰은 상태 표현에만 사용합니다.</CardDescription></CardHeader>
        <CardContent className="grid grid-cols-3 gap-3 sm:grid-cols-5">
          {TOKENS.map(([name, cls]) => <div key={name} className="flex flex-col gap-1 text-xs"><div className={`h-10 rounded-lg border ${cls}`} aria-hidden="true" />{name}</div>)}
        </CardContent>
      </Card>
      <Card>
        <CardHeader><CardTitle>상태 배지와 아이콘</CardTitle></CardHeader>
        <CardContent className="flex flex-wrap items-center gap-2">
          <StatusBadge tone="success"><CheckCircle2 aria-hidden="true" />최신</StatusBadge>
          <StatusBadge tone="warning"><AlertTriangle aria-hidden="true" />오래됨</StatusBadge>
          <StatusBadge tone="error"><AlertTriangle aria-hidden="true" />수집 실패</StatusBadge>
          <StatusBadge tone="unknown"><CircleHelp aria-hidden="true" />알 수 없음</StatusBadge>
          <Badge>기본</Badge><Badge variant="secondary">보조</Badge><Badge variant="outline">외곽</Badge>
        </CardContent>
      </Card>
      <Card>
        <CardHeader><CardTitle>버튼 · 입력 · 탭</CardTitle><CardDescription>Tab 키로 이동, 포커스 링 표시</CardDescription></CardHeader>
        <CardContent className="flex flex-col gap-4">
          <div className="flex flex-wrap gap-2">
            <Button><RefreshCw aria-hidden="true" />기본</Button><Button variant="outline">외곽</Button><Button variant="secondary">보조</Button><Button variant="ghost">고스트</Button><Button variant="destructive">위험</Button><Button size="icon" aria-label="정보"><Info /></Button>
          </div>
          <Input placeholder="입력 예시" aria-label="입력 예시" className="max-w-xs" />
          <Tabs defaultValue="a"><TabsList><TabsTrigger value="a">탭 A</TabsTrigger><TabsTrigger value="b">탭 B</TabsTrigger></TabsList><TabsContent value="a" className="text-sm text-muted-foreground pt-2">탭 A 내용</TabsContent><TabsContent value="b" className="text-sm text-muted-foreground pt-2">탭 B 내용</TabsContent></Tabs>
        </CardContent>
      </Card>
      <Card>
        <CardHeader><CardTitle>표 · 경고 · 구분선</CardTitle></CardHeader>
        <CardContent className="flex flex-col gap-4">
          <Table><TableHeader><TableRow><TableHead>열 1</TableHead><TableHead>열 2</TableHead></TableRow></TableHeader><TableBody><TableRow><TableCell>예시</TableCell><TableCell>예시</TableCell></TableRow></TableBody></Table>
          <Separator />
          <Alert><Info aria-hidden="true" /><AlertTitle>안내</AlertTitle><AlertDescription>기본 경고 예시</AlertDescription></Alert>
          <Alert variant="destructive"><AlertTriangle aria-hidden="true" /><AlertTitle>주의</AlertTitle><AlertDescription>위험 경고 예시</AlertDescription></Alert>
        </CardContent>
      </Card>
    </div>
  )
}
