import { Activity, AlertTriangle, Database, HardDrive, ListChecks, Radio, ScrollText } from "lucide-react"

import { KeyValue, StatCard } from "@/components/stat-card"
import { StatusBadge } from "@/components/status-badge"
import { severityTone, statusTone } from "@/lib/tones"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import type { Retained } from "@/lib/use-snapshot"
import { CATEGORY_LABELS, CATEGORY_ORDER, SEVERITY_LABELS, STATE_LABELS, formatNumber, formatSeconds, formatTime, freshness, type DatabaseFacts, type DockerRow, type Observations, type RedisRow, type Snapshot } from "@/lib/snapshot"

type Props = { snapshot: Snapshot | null; retained: Retained; now: number }

function RetainedNote({ live, observedAt }: { live: boolean; observedAt: string | null | undefined }) {
  if (live) return null
  return <StatusBadge tone="warning">보존 기록 · 마지막 정상 관측 {formatTime(observedAt)} · 현재 상태 아님</StatusBadge>
}

export function OverviewView({ snapshot, retained, now }: Props) {
  const obsState = freshness(snapshot, "observations", now)
  const obsLive = obsState.state === "fresh"
  const dbLive = freshness(snapshot, "database", now).state === "fresh"
  const observations = (retained.observations?.data as Observations | undefined) ?? null
  const database = (retained.database?.data as DatabaseFacts | undefined) ?? null
  const docker = (retained.docker?.data as DockerRow[] | undefined) ?? null
  const redis = (retained.redis?.data as RedisRow[] | undefined) ?? null
  const local = observations?.local ?? null
  const localOk = local && local.status === "ok" ? local : null

  return (
    <div className="flex flex-col gap-6">
      {/*
        Two different axes, never one list: what is explicitly recorded as a current condition, and
        what is a stored record of the past. A stored critical/error or alert row does not prove an
        unresolved incident, and its age does not resolve it either; an unreadable or absent source
        stays 확인 불가 instead of 0.
      */}
      <section aria-labelledby="attention-title" className="flex flex-col gap-3">
        <h2 id="attention-title" className="text-lg font-semibold inline-flex items-center gap-2"><AlertTriangle aria-hidden="true" className="size-4" />현재 상태 (명시적 기록)</h2>
        {!observations ? (
          <Alert variant="destructive"><AlertTitle>관측 로그 출처 없음</AlertTitle><AlertDescription>저장된 관측 로그를 아직 받지 못했습니다. 비어 있음이 아니라 확인 불가입니다.</AlertDescription></Alert>
        ) : (
          <>
            <p className="text-sm text-muted-foreground break-words">현재 상태가 명시적으로 기록된 항목만 모았습니다. 과거 이벤트 기록은 아래 '기록 이력'에 그대로 남아 있으며, 여기로 옮기거나 해결로 바꾸지 않습니다.</p>
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
              <StatCard title="미확정 종료 기록" value={formatNumber(observations.terminations.pending)} note="pending_reconciliation·unconfirmed · 해당 작업의 재실행·복구만 차단 · 전체 실행 차단 아님 · 운영자 조정 전까지 유지" icon={<AlertTriangle className="size-4" />} />
              <StatCard title="로컬 대기 경보" value={localOk ? formatNumber(localOk.pending_alerts) : <span className="text-unknown">확인 불가</span>} note={localOk ? "로컬 스풀 파일 기준 · 수집기 재생 전" : `로컬 스풀 확인 불가${local && local.status !== "ok" ? ` · ${local.reason}` : ""} · 0 아님`} />
              <StatCard title="판독 불가 로컬 종료 기록" value={localOk ? formatNumber(localOk.unreadable_terminations) : <span className="text-unknown">확인 불가</span>} note={localOk ? `로컬 종료 기록 ${formatNumber(localOk.pending_terminations)}건 중 · 내용 확인 불가 · 해결 여부 알 수 없음` : "로컬 스풀 확인 불가 · 0 아님"} />
              <StatCard title="관측 로그 신선도" value={obsLive ? "최신" : <span className="text-unknown">{STATE_LABELS[obsState.state] ?? obsState.state}</span>} note={obsLive ? `관측 ${formatTime(obsState.observed_at)}` : `관측 ${formatTime(obsState.observed_at)} · 현재 상태 아님${obsState.reason ? ` · ${obsState.reason}` : ""} · 아래 값은 그 시각 기준`} />
            </div>
          </>
        )}
        {observations?.sample.truncated ? (
          <Alert><AlertTitle>샘플이 잘렸습니다</AlertTitle><AlertDescription>버킷당 {formatNumber(observations.sample.limit_per_bucket)}행까지만 읽었습니다. 합계는 저장 전체가 아닙니다. 보이지 않는 행은 0건이 아니라 알 수 없음입니다.</AlertDescription></Alert>
        ) : null}
        <RetainedNote live={obsLive} observedAt={retained.observations?.observed_at} />
      </section>

      <section aria-labelledby="history-title" className="flex flex-col gap-3">
        <h2 id="history-title" className="text-lg font-semibold inline-flex items-center gap-2"><ScrollText aria-hidden="true" className="size-4" />기록 이력 (샘플)</h2>
        {!observations ? (
          <p className="text-sm text-muted-foreground">확인 불가 · 관측 로그 출처 없음 (0건 아님)</p>
        ) : (
          <>
            <p className="text-sm text-muted-foreground break-words">저장된 과거 기록입니다. 지금도 미해결이라는 뜻이 아니고 해결되었다는 뜻도 아닙니다(결과 미확정 · 알 수 없음). 오래되었다는 이유로 해결로 바꾸지 않으며, 자동 정리도 하지 않습니다.</p>
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
              <StatCard title="치명·오류 이벤트 (기록 이력)" value={formatNumber(observations.events.high_severity_total)} note="심각도 우선 정렬 · 저장 샘플 기준 · 현재 미해결 증거 아님" icon={<AlertTriangle className="size-4" />} />
              <StatCard title="경보 / 격리 (기록 이력)" value={`${formatNumber(observations.alerts.recorded)} / ${formatNumber(observations.quarantine.total)}`} note="기록된 경보 · 격리 행 · 저장된 과거 기록" />
              <StatCard title="운영 결과 (기록 이력)" value={formatNumber(observations.operations.total)} note="저장된 운영 결과 행 · 후속 조치 여부는 이 출처에 없음" icon={<ListChecks className="size-4" />} />
              <StatCard title="알 수 없음 행" value={`${observations.events.unknown.severity} · ${observations.events.unknown.category} · ${observations.events.unknown.observed_at}`} note="심각도 · 분류 · 관측 시각 무효 · 정상으로도 이상으로도 세지 않음" />
            </div>
          </>
        )}
      </section>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="inline-flex items-center gap-2"><ListChecks aria-hidden="true" className="size-4" />운영(operation) 결과</CardTitle>
            <CardDescription>operations 버킷에 저장된 결과(기록 이력)입니다. 작업(task) 성공은 운영 전체 성공이 아니며, '수락됨'은 검토 수락일 뿐 병합·배포가 아닙니다. 소유자의 병합·배포 기록은 이 화면에 연결되어 있지 않습니다.</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            {!observations ? <p className="text-muted-foreground text-sm">확인 불가</p> : observations.operations.total === 0 ? (
              <p className="text-muted-foreground text-sm">샘플 안에 운영 기록 없음 (비어 있음)</p>
            ) : (
              <>
                <div className="flex flex-wrap gap-2">
                  {Object.entries(observations.operations.by_status).map(([status, count]) => (
                    <StatusBadge key={status} tone={statusTone(status)}>{status} {count}</StatusBadge>
                  ))}
                </div>
                <Table>
                  <TableHeader><TableRow><TableHead>운영 ID</TableHead><TableHead>결과</TableHead><TableHead>사유</TableHead><TableHead>팀장 수락</TableHead><TableHead>작업</TableHead></TableRow></TableHeader>
                  <TableBody>
                    {observations.operations.rows.slice(0, 12).map((row, index) => (
                      <TableRow key={row.id ?? `row-${index}`}>
                        <TableCell className="font-mono text-xs max-w-48 truncate" title={row.criterion ?? ""}>{row.id ?? "—"}</TableCell>
                        <TableCell><StatusBadge tone={statusTone(row.status)}>{row.status ?? "unknown"}</StatusBadge></TableCell>
                        <TableCell className="text-xs">{row.reason_code ?? "—"}</TableCell>
                        <TableCell>{row.lead_accepted == null ? "미확인" : row.lead_accepted ? "수락" : "거부"}</TableCell>
                        <TableCell className="font-mono text-xs">{row.task_id ?? "—"}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
                {observations.operations.rows_truncated ? <p className="text-xs text-muted-foreground">표시 행 제한 초과 · 일부만 표시</p> : null}
              </>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="inline-flex items-center gap-2"><Activity aria-hidden="true" className="size-4" />작업(task) 상태</CardTitle>
            <CardDescription>운영 기록 출처(PostgreSQL) · 과거 실패 기록 포함 · SLO 판정 아님</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            {!database ? <p className="text-muted-foreground text-sm">확인 불가</p> : (
              <>
                <RetainedNote live={dbLive} observedAt={retained.database?.observed_at} />
                <KeyValue items={[
                  ["운영 상태", <StatusBadge tone={dbLive ? statusTone(database.operating_status) : "unknown"}>{dbLive ? database.operating_status ?? "unknown" : "확인 불가"}</StatusBadge>],
                  ["작업 건수", Object.entries(database.task_counts ?? {}).map(([k, v]) => `${k} ${v}`).join(" · ") || "기록 없음"],
                  ["실행 중", dbLive ? formatNumber((database.agents ?? []).reduce((sum, agent) => sum + (agent.work?.length ?? 0), 0)) : "확인 불가"],
                  ["운영 커밋", database.active?.revision?.slice(0, 10) ?? "—"],
                ]} />
              </>
            )}
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="inline-flex items-center gap-2"><Database aria-hidden="true" className="size-4" />수집 범위와 완전성</CardTitle>
            <CardDescription>저장된 행은 기대 이벤트가 모두 기록되었다는 증거가 아닙니다.</CardDescription>
          </CardHeader>
          <CardContent>
            {!observations ? <p className="text-muted-foreground text-sm">확인 불가</p> : (
              <KeyValue items={[
                ["샘플 이벤트", `${formatNumber(observations.events.total)} (감사 전용 ${observations.events.record_kinds.audit ?? 0} · 수집 ${observations.events.record_kinds.collected ?? 0} · 양쪽 ${observations.events.record_kinds.both ?? 0})`],
                ["분류별", CATEGORY_ORDER.filter((c) => observations.events.by_category[c]).map((c) => `${CATEGORY_LABELS[c]} ${observations.events.by_category[c]}`).join(" · ") || "없음"],
                ["심각도별", Object.entries(observations.events.by_severity).map(([k, v]) => `${SEVERITY_LABELS[k] ?? k} ${v}`).join(" · ") || "없음"],
                ["마지막 수집", observations.collection.last_at ? `${formatTime(observations.collection.last_at)} · 지연 ${formatSeconds(observations.collection.lag_seconds == null ? null : observations.collection.lag_seconds * 1000)}` : "수집 영수증 없음 (알 수 없음)"],
                ["수집 영수증", `${formatNumber(observations.collection.receipts)}건 · 시각 유효 ${formatNumber(observations.collection.receipts_with_time)}`],
                ["로컬 스풀", !local ? "확인 불가" : local.status !== "ok" ? <StatusBadge tone="unknown">확인 불가 · {local.reason}</StatusBadge> : `세그먼트 ${local.segments} · 미확인 ${formatNumber(local.unacknowledged_bytes)} 바이트 · 대기 경보 ${local.pending_alerts} · 로컬 종료 기록 ${local.pending_terminations}${local.unreadable_terminations ? ` (판독 불가 ${local.unreadable_terminations})` : ""}`],
                ["프로세스 상태 파일", !local || local.status !== "ok" ? "확인 불가" : local.health.length === 0 ? "없음" : local.health.map((h) => `${h.component ?? "?"}: sink ${h.sink ?? "?"}${h.unreadable ? " (판독 불가)" : ""}${Object.values(h.dropped).some((v) => v) ? " · 유실 있음" : ""}`).join(" · ")],
              ]} />
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="inline-flex items-center gap-2"><HardDrive aria-hidden="true" className="size-4" />서비스 자원</CardTitle>
            <CardDescription>컨테이너와 메시지 버스 실측 · 출처별로 독립 판정</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            <div>
              <RetainedNote live={freshness(snapshot, "docker", now).state === "fresh"} observedAt={retained.docker?.observed_at} />
              {!docker ? <p className="text-muted-foreground text-sm">컨테이너 확인 불가</p> : docker.length === 0 ? <p className="text-muted-foreground text-sm">컨테이너 기록 없음</p> : (
                <Table>
                  <TableHeader><TableRow><TableHead>서비스</TableHead><TableHead>상태</TableHead><TableHead>CPU</TableHead><TableHead>메모리 / 제한</TableHead></TableRow></TableHeader>
                  <TableBody>{docker.map((row) => (
                    <TableRow key={row.name ?? row.service}><TableCell>{row.service ?? row.name}</TableCell><TableCell><StatusBadge tone={row.state === "running" ? "success" : "warning"}>{row.state ?? "?"}</StatusBadge></TableCell><TableCell>{row.cpu ?? "—"}</TableCell><TableCell>{row.memory ?? "—"}</TableCell></TableRow>
                  ))}</TableBody>
                </Table>
              )}
            </div>
            <div>
              <RetainedNote live={freshness(snapshot, "redis", now).state === "fresh"} observedAt={retained.redis?.observed_at} />
              {!redis ? <p className="text-muted-foreground text-sm inline-flex items-center gap-1"><Radio aria-hidden="true" className="size-3" />메시지 버스 확인 불가</p> : (
                <Table>
                  <TableHeader><TableRow><TableHead>에이전트</TableHead><TableHead>엔트리</TableHead><TableHead>pending</TableHead><TableHead>lag</TableHead></TableRow></TableHeader>
                  <TableBody>{redis.map((row) => (
                    <TableRow key={row.agent}><TableCell>{row.agent}</TableCell><TableCell>{formatNumber(row.entries)}</TableCell><TableCell>{formatNumber(row.pending)}</TableCell><TableCell>{formatNumber(row.lag)}</TableCell></TableRow>
                  ))}</TableBody>
                </Table>
              )}
            </div>
          </CardContent>
        </Card>
      </div>

      {observations && observations.events.high_severity.length ? (
        <Card>
          <CardHeader><CardTitle>최근 치명·오류 이벤트 (기록 이력)</CardTitle><CardDescription>샘플 상위 {observations.events.high_severity.length}건 · 전체 {observations.events.high_severity_total}건 · 저장된 과거 기록이며 각 행의 결과는 기록된 값 그대로입니다. 현재 미해결 여부는 이 목록으로 알 수 없습니다.</CardDescription></CardHeader>
          <CardContent>
            <ul className="flex flex-col divide-y">
              {observations.events.high_severity.slice(0, 8).map((row) => (
                <li key={row.event_id ?? row.event_type ?? ""} className="py-2 flex flex-wrap items-center gap-2 text-sm">
                  <StatusBadge tone={severityTone(row.severity)}>{SEVERITY_LABELS[row.severity] ?? row.severity}</StatusBadge>
                  <span className="font-mono text-xs">{row.event_type ?? "—"}</span>
                  <span className="text-muted-foreground text-xs">{formatTime(row.observed_at)} · 결과 {row.outcome ?? "기록 없음 · 알 수 없음"}{row.reason_code ? ` · ${row.reason_code}` : ""}</span>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      ) : null}
    </div>
  )
}
