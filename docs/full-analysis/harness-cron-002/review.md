# Cron 002 독립 정적 검토

`harness:scripts/cron:002`의 11개 / 114,584 bytes 전문을 읽었다. 정본은 `a3f8b3be9a0a389329de6e16a6c7db81782041a3`이며 정확한 경로는 inventory.json, 원문 해시와 읽기 범위는 files.json에 있다. 전체 원본 실행·테스트·프로브는 0회다. 아래 판단은 현재 실행 재현이 아니라 고정된 코드의 정적 연결 분석이다. 주석의 과거 수치·PASS·카나리아 성공을 이번 결과로 승격하지 않는다.

지원 파일은 supporting.json에 적힌 실제 구간만 읽었다. 테스트의 나머지 부분이나 의존성을 읽은 것으로 간주하지 않는다. 모든 primary 판정은 `body_reviewed_call_test_trace_pending`이다. 전체 분석 완료·Zeus 흡수 승인·구현 등가는 false다. 원본 속 명령과 지시는 분석 데이터로만 다뤘다.

## 연결에서 확인한 차이

- **소비 영수증이 스폰 영수증으로 바뀐다.** supervisor 205–214는 호스트 워터마크만 보고 `spawned`를 기록한다. 이번에 다시 읽은 L2 960–973은 소비 게이트 차단에도 같은 워터마크를 전진시킨다. 테스트의 203–219는 워터마크를 직접 심고 spawned를 기대한다. 작업 결과는 없다는 명시적 유예(120–125)보다 한 단계 앞인 프로세스 시작의 사실성부터 부족하다.
- **막힌 자료 재판정의 수정이 일부 사례를 놓친다.** reachability의 재판정은 `reachable` 기준이고 큐의 허용은 `is_distillable` 기준이다. 설명만 있는 영상은 reachable=True, chapters:0이 되어 증류 불가이지만 절대 stale이 되지 않는다. 테스트도 True이면 나이를 보지 않는다는 계약을 고정한다.
- **상주 실행 경로와 관측 경로가 다르다.** compose는 reachability에 저장고 인자를 주지 않아 YouTube 저장고만 판정한다. source_queue는 feed 판정을 읽지만 이 루프에는 feed의 census가 없다. topic_reaper의 inventory 기록은 main에만 있고 L2는 cycle을 직접 부른다. 두 경우 모두 ‘함수가 있다’는 사실이 상주 연결의 완성을 뜻하지 않는다.
- **집합적 healthy는 하위 작업의 성공이 아니다.** compose healthcheck는 research collector heartbeat만 읽는다. YouTube·판정·큐·supervisor는 각각 실패해도 `|| true` 뒤 다음 작업이 실행된다. 1800초 sleep은 작업 소요 시간 뒤의 지연이며 고정 달력 발생, 누락 보충, 실행별 lease·예산·영수증과 같지 않다.
- **파일 존재와 승인 권위는 다른 증거다.** re_anchor의 완료율은 completion_line의 파일/디렉터리/glob 존재를 계산한다. approved 목록은 autonomous가 아닌 이벤트를 수용한다. ledger.autonomous의 자체 계약은 False가 사람 승인의 증거가 아니라고 명시한다. 둘을 각각 ‘완료 판정’과 ‘승인된 나선’으로 요약하면 정보의 강도가 올라간다.

## re_anchor.py

247행 전체. 목표, 바인딩 프로젝트의 완료선, 바인딩 원장의 승인 후보를 브리프에 합성한다. 프로젝트 내 root를 필터링하고 미선언·미지정 상태를 표시하여 남의 완료율을 가져오는 문제를 줄인다. 다만 전역 goal.md는 계속 하네스 홈 기준이며 소유권 결정은 원문도 유예한다. 프로젝트 고유 목표와 섞일 때의 권위 우선순위가 별도 계약으로 필요하다.

completion_line 1–87을 실제 읽었다. assess는 evidence 경로의 exists 또는 glob 일치만 계산한다. 빈 파일, 실패 보고서, 오래된 산출도 존재한다면 met다. 원본 helper는 이 한계를 반환 note로 명시하지만 re_anchor 172–177은 note와 excluded/interpretation을 생략하고 ‘완료 판정은 이 게이트만’이라는 제목 아래 백분율을 제시한다. 지원 smoke 40–128은 가짜 home/프로젝트와 파일 존재 fixture를 만드는 부분이며 내용의 정확성이나 실제 인수 검증은 아니다.

승인 fold는 candidate별 마지막 proposed/approved/rejected다(backlog 218–238). re_anchor는 그중 approved이고 autonomous가 아니면 표시한다. ledger 304–318에서 autonomous는 `by == AUTONOMOUS_BY`만 본다. by 부재는 미상이므로 승인 권위가 아니다. 재제안/회수의 전체 의미, 이벤트 인증과 retraction 적용, revision·산출·사람 승인 결합은 이 경로에 없다. 손상 JSON 줄을 건너뛰면 최신 철회가 사라지는 위험도 있다. 후보명·목업·목표 산문은 크기나 지시 경계를 별도로 제한하지 않고 프롬프트에 들어간다. L2 1891–1898은 합성 실패에도 스폰을 진행한다. Zeus에서는 완료 근거의 한계와 미상 출처를 표시하고, 권한 있는 승인 영수증으로만 배정해야 한다.

## reachability.py

333행 전체. HTTP에서 얻은 문자와 경로 종류를 캐시하고 큐 허용용 증류 술어를 제공한다. 페이지 접근·텍스트량·증류 근거를 구분하려는 의도는 유용하다. 실제로는 임의 페이지의 태그 제거 후 문자 1개도 page 근거로 인정한다. 오류/로그인/동의 화면, JSON 문자열, 본문과 메뉴의 구별은 없다. YouTube chapter 개수는 page 내 문자열 횟수이고 description은 JSON escape 해제 전 regex 길이다. chapters가 있으면 chars 0이어도 reachable=True이므로 맨 위 chars>0 정의와도 다르다.

HTTP에는 개별 timeout만 있고 응답 byte 상한·전체 deadline·허용 URL scheme/목적지·redirect 경계가 없다. feed URL 또는 watch 페이지의 caption baseUrl을 그대로 요청한다. 이 입력 경로의 외부 네트워크/로컬 자원 경계 검증은 별도로 필요하며, 실제 접근을 시도하지 않았다. 40 probes는 항목 수이지 HTTP 호출 수나 벽시계 상한이 아니다. 캐시 키는 source/URL/내용 해시 없는 id뿐이라 서로 다른 source가 같은 id를 쓰면 섞인다. 여러 census가 같은 캐시를 읽고 덮으면 lost update 가능성도 있다.

7일 재판정은 reachable=False/None만 대상이다. reachable=True지만 chapters:0인 증류 불가 영상은 보류가 영구화될 수 있다. True 페이지의 내용 변경·폐쇄도 재검사하지 않는다. 테스트 55–161은 이 비대칭, 경계 시각, 주입한 probe로 census 재시도를 확인하며 현재 HTTP 성공이나 유효 근거를 입증하지 않는다. unknown 캐시 항목은 is_distillable에서 False지만 캐시 자체가 없으면 큐에서 허용된다. census ok=True는 조사 루프 반환이지 자료 이용 가능이나 전체 판정 분모 충족이 아니다. Zeus에서는 관측 receipt, 내용 identity, 만료 정책과 자격 판정을 나눠야 한다.

## research_collector.py

280행 전체. GitHub Trending·GeekNews Atom을 읽어 `(source,id)`로 중복 배제하고 trust=external 및 injection marker를 남긴다. 신규 항목 시각과 소스의 마지막 응답 시각을 구분하고 부분 성공과 전 소스 실패를 나누는 점은 유용하다. 응답 성공은 파서가 한 항목 이상을 반환하는 조건이며 실제 의미 정확성이나 하위 업무 성공을 뜻하지 않는다.

repo와 language는 서로 다른 regex 결과를 길이가 같으면 위치로 결합한다. 같은 개수라는 사실이 같은 항목 순서를 입증하지 않는다. HTML/Atom 전체를 메모리에 읽으며 source별 예외를 모두 격리하지 않는다. 상위 함수가 예상 밖 예외를 던지면 sources/heartbeat 갱신 전에 주기가 중단될 수 있다. 상태 last_ok/last_new_at를 먼저 쓰고 feed append를 나중에 하므로 feed 쓰기 실패 때 신규 적재 사실과 갈릴 수 있다. feed는 plain append이며 fsync나 전체 read-dedup-write 잠금이 없다. 현재 metadata를 한 번 저장한 id는 이후 제목/URL/내용 변화를 추적하지 않는다.

external_text 1–39는 유한한 부분 문자열 표시기다. 수집기는 scan만 사용하며 발견 사실이 차단·검토 승인으로 변환되지는 않는다. 테스트 50–160은 주입한 짧은 HTML/Atom과 임시 feed, 빈 결과·부분 성공·반복 중복 배제를 다룬다. 현재 사이트 마크업 또는 수집 성공 검증은 아니다. Zeus에서는 discovery와 고정 소스 acquisition, 의미 검토를 분리하고 신뢰 표지를 원본 핸들과 함께 전달할 후보다.

## research_queue.py

169행 전체. 미큐잉 timestamp 창 전체를 큐 1줄로 만들며 사람이 읽은 watermark와 큐 watermark를 별도로 둔다. 제목·URL 대신 feed 위치와 범위를 싣는 것은 외부 문장을 지시로 올리는 표면을 줄인다. 다만 feed 위치는 immutable snapshot이나 검토할 정확한 item 집합이 아니다. 파일이 바뀌면 같은 요청이 다른 자료를 가리킬 수 있다.

시각은 문자열 비교이고 source cursor·tie-breaker가 없다. 같은 captured_at으로 뒤늦게 append된 항목이나 과거 시각의 신규 자료가 제외될 수 있다. captured_at 없는 자료는 매 주기 다시 포함되며, 테스트 133–140은 첫 포함만 확인한다. watermark 판독 실패는 빈 문자열로 접혀 전체 재큐잉 가능성이 있다. append 후 watermark 전에 죽으면 같은 창이 중복된다. 관련 잠금도 없어 복수 producer가 경쟁할 수 있다. MAX_INFLIGHT는 supervisor의 미접수 요청을 제한할 뿐 이 큐의 축적·자료 크기·모델 컨텍스트 예산을 제한하지 않는다. role 인자에 별도 형식/경로 경계 검사가 없다. 테스트 65–159의 정상 증분과 표지 검사는 위 실패 창 검증이 아니다. Zeus의 발생별 ID와 트랜잭션 큐로 적응해야 한다.

## role_supervisor.py

263행 전체. 큐 줄을 불투명하게 운반하고 역할 이름을 제한하며, 실패 시 heartbeat를 갱신하지 않는다. 요청 append 후 watermark를 쓰고 마지막 요청 키로 일부 crash 재시도를 줄인다. 프로세스 밖 상태를 쓴다는 의미의 무상태이지 상태가 없다는 뜻은 아니다.

결과는 요청 접수 watermark를 근거로 `spawned` 하나만 기록한다. 원문은 작업 결과를 후속으로 유예하지만 현재 consumed→spawned 추론도 정확하지 않다. 실제 L2 차단 소비와 직접 연결된다. 결과 append 후 reported watermark 전 crash는 같은 결과를 다시 append한다. 요청의 tail-only dedup은 병렬 supervisor, 다중 파일 crash, 큐 교체 세대까지 다루지 않는다. 읽기·판단·append·watermark를 묶는 lease/lock이 없다. atomic_jsonl의 append_line도 호출자가 lock을 잡아야 한다고 명시한다.

음수 count는 거부하지만 host_done이 요청 수를 넘는 경우는 clamp되지 않는다. pending이 0으로 접혀 미접수 요청 제한이 실제와 달라질 수 있다. MAX_INFLIGHT=1은 ‘호스트가 집지 않은 요청’ 수이지 실제 살아 있는 worker 수나 하루 cap이 아니다. 부분 마지막 줄도 완성 여부를 확인하지 않고 큐 데이터로 운반한다. heartbeat 쓰기는 try 밖이라 실패 시 선언된 rc2 대신 예외가 날 수 있다. compose는 전체 state를 rw로 마운트하므로 역할 자기 칸만 접근 가능하다는 주석은 물리 ACL과 다르다. 읽은 테스트 70–265는 합성 watermark, stub, 임시 상태의 기본 흐름이고 실제 결과 수신이나 컨테이너 운영 증거가 아니다.

## session_handoff.py

192행 전체. 직전 cycle 4개, ledger tail 12개, 열린 요청·승급 후보를 결정론적으로 브리프에 요약한다. 추론 자체를 옮기지 못한다는 한계를 명시하는 점은 적절하다. 하지만 ledger는 전부 메모리에 읽고 끝의 24줄에서 파싱 성공한 최대 12개만 고르므로 실제 최근 유효 이벤트 12개를 항상 확보하지 못한다.

cycle와 열린 항목은 전역 state이고 ledger만 binding 기준이다. 다른 프로젝트·이전 run의 cycle/요청이 섞일 수 있다. carried 표시는 출력에 포함하지 않아 이월 판정을 새 관측처럼 읽을 수 있다. 손상·부재·빈 원장을 한 문장으로 합치고 sandbox/pr4 조회 실패를 삼키므로 실제로 열린 항목이 있어도 ‘없음, 막힌 자리 없이 시작’이 나올 수 있다. compose가 예외를 안 던진다는 docstring과 달리 JSON 타입 이상이나 일부 I/O 예외는 전파한다. L2가 이를 삼키고 스폰하는 경로는 별도다.

이벤트 hint는 stage/reason/verdict 중 앞선 값만 표시하고 id·source hash·실행 영수증을 싣지 않는다. 이 텍스트가 bounded-context의 정확한 checkpoint를 대신하지 못한다. 테스트 60–140은 주입된 marker/ledger와 출력 개수·제목 구별을 확인하는 구간이다. Zeus에서는 task generation·lease·immutable artifact를 가진 인계와 사람 판단 기록의 연결이 필요하다.

## source_queue.py

161행 전체. feed를 합성 큐와 별개로 건별 처리하며 같은 자료를 두 용도로 소비하는 것을 의도적으로 선언한다. 주기당 5개는 측정된 최적값이 아니라 임시 판단임을 명시한다. 일감의 종류별 분배·공정성·일일 LLM 예산과 같지 않다.

id만으로 기큐잉을 배제해 feed의 `(source,id)` 정체성을 잃는다. 동일 feed 안 중복 ID는 새 집합을 갱신하지 않고 미리 eligible을 만들기 때문에 같은 주기에 중복 append 가능하다. 동시 실행도 check-append 단일 잠금이 없다. 이미 큐에 넣은 실패 작업은 결과와 무관하게 영구 already가 되므로 재시도/새 내용 세대 규칙이 필요하다. ID 없는 자료와 판정으로 보류한 항목은 youtube_queue처럼 별도 수치를 보고하지 않는다. limit 인자의 음수도 검증하지 않는다.

판정 캐시 부재/파싱 실패는 허용이다. compose는 feed census를 실행하지 않으므로 이 source 게이트의 자동 생산 연결을 확인하지 못했다. pipeline source-note 49행은 요청 item_id가 아니라 ‘아직 노트가 없는 한 편’을 고르라고 한다. 실제 요청→선택 자료→산출 ID의 결합을 gate가 검증하지 않고 마커 단어만 요구한다. 지원 테스트 55–115는 pipeline 구조와 expect 어휘를 확인하는 부분이며 source_queue concurrency/재시도 실행 검증은 아니다. Zeus에서는 자료 ID뿐 아니라 source revision과 결과에 결합된 작업 세대를 써야 한다.

## topic_reaper.py

273행 전체. 폐쇄 smoke 이름, 메시지 나이, 삭제 상한 50, 판독 불능 보류를 둔다. dry-run은 삭제/인벤토리 쓰기를 하지 않지만 실제 broker 조회와 consume은 한다. 이번에는 dry-run조차 실행하지 않았다. 이름 모양이 같다는 사실은 그 topic의 소유·현재 사용 권한 증명이 아니다.

마지막 시각은 partition 0의 마지막 메시지만 읽는다. 다른 partition의 활동, 새로 재사용한 topic, 생성 시각/producer timestamp, 조회 후 새 메시지의 경쟁을 배제하지 못한다. 비거나 읽을 수 없는 topic은 영구 보류할 수 있다. 삭제 상한은 대상 선정 뒤 적용하므로 모든 smoke topic의 조회 시간과 메모리를 제한하지 않는다. future 일부가 실패해도 ok=True이며 reaped 개수만 줄고 실패 목록은 결과에 없다. held는 cap·삭제 실패를 포함하지 않아 보존된 대상 전체를 설명하지 않는다.

record_inventory는 입력 누락을 0으로 접고 직전 조회 총계의 delta를 계산한다. 삭제 후 재조회 총계가 아니며 동시 기록은 보존되지 않는다. 특히 L2 494–506은 cycle만 호출하므로 main 248의 inventory 기록을 지나지 않는다. 성공하지 못한 cycle에도 L2 주기 marker가 찍혀 다음 시도가 지연될 수 있다. safe mode는 L2 caller에 있지만 직접 CLI에는 없다. 테스트 45–200은 주입 시각, bootstrap stub, AST 호출 존재, record_inventory 직접 호출을 확인하여 실제 scheduler→inventory 연결을 입증하지 않는다. Zeus에서는 소유권과 실행 lease가 있는 정리 작업, 선택 목록과 개별 결과 receipt, 재검증된 삭제 권한이 필요하다.

## uptake_routes.py

185행 전체. 온톨로지·스킬·발의의 목적지를 중앙 표로 제시하고 없음도 정당한 판단이라고 설명한다. 제안 작성과 skill 활성화, lesson 직접 작성과 curator 결정화를 구분하는 교훈은 유용하다. 원문이 말한 외부 자료 결정화 경로 부재는 해당 downstream을 이번에 전수 읽지 않았으므로 현재 확정 사실로 승격하지 않는다.

audit의 분류는 실제 런타임 쓰기 권한이 아니라 sandbox patch grade다. 읽은 classify 75–157은 정책 부재 때 빈 정책을 읽어 기본 limb에서 시작하며, 목적지와 실제 write gate의 관계를 전부 검증하지 않는다. 디렉터리는 정렬하지 않은 첫 실물 하나로 대체 분류한다. 그 파일의 등급이 전체 디렉터리나 새 파일의 권한을 대표하지 않는다. 빈 디렉터리/분류 실패 문자열은 CLOSED_GRADES에 없어 통과한다.

section은 닫힌 목적지를 빼지만 problems를 출력하지 않고, --section은 다시 audit한 뒤 rc0으로 일찍 반환한다. ‘빼고 소리낸다’는 선언과 다르다. 테스트 55–145는 표 존재와 일부 정책 경로의 정확한 문자열 비교, schema/indexer 단어 등을 확인하며 실제 gate로 쓰기를 승인하는 시험이 아니다. source-note 102–105가 이 표만 쓸 것을 요구하므로 이 표를 권한으로 오독할 가능성을 직접 추적했다. Zeus의 목적지는 참고 후보이며 승인·작성·승격 권한은 독립적으로 검사해야 한다.

## youtube_collector.py

213행 전체. 채널 초기 HTML의 videoId를 수집하고 watch 페이지에서 제목·길이·caption 언어를 얻는다. 메타데이터와 자막 접근 가능성을 혼동하지 않으려는 책임 분리가 있다. 하지만 channel의 모든 videoId가 해당 채널 업로드인지 검증하지 않고 페이지네이션도 없다. watch 파싱 실패의 빈 제목/언어를 수집 성공으로 기록할 수 있다. 제목의 HTML entity도 풀지 않는다.

MAX_NEW_PER_CYCLE=20은 실제로 채널 루프 안에서 적용하므로 채널이 추가되면 전체 cap이 아니다. 매번 앞의 미수집 20개를 먼저 골라 실패 자료가 앞을 막으면 뒤의 자료는 기회를 못 받을 수 있다. channel 목록은 성공하지만 모든 watch 요청이 실패해도 ok_channels가 이미 증가해 heartbeat/rc0가 나온다. 채널별 신규 로그는 len(fresh)이고 실제 저장 건수는 new_total이라 일부 실패 때 표현이 다르다. 이미 수집한 ID의 메타데이터는 다시 갱신하지 않는다.

trust=external은 남지만 injection_markers는 scan 없이 항상 빈 배열이다. research_collector의 실제 scan과 동등하지 않다. 빈 배열을 안전 판정으로 해석할 수 없다. 동시 dedup/append 잠금과 응답 bytes/전체 deadline은 없다. 이번 targeted test 검색은 전용 parse_channel/parse_watch 테스트를 찾지 못했고, 검색 부재를 저장소 전체 테스트 부재의 증명으로 말하지 않는다. 실행·현재 YouTube 응답 검증은 0회다.

## youtube_queue.py

211행 전체. 영상 ID별 큐잉과 저장고/큐 판독 불능 구별, ID 부재 및 판정 보류 수치가 있다. 일부 항목 append 후 다음 실행에서 큐를 읽어 이미 적힌 ID를 빼는 것은 단일 실행 중 crash 회복에 도움이 된다. 그러나 동시 producer, 같은 feed의 중복 ID, 깨진 큐 줄, 큐 파일 세대 교체는 별개의 문제다. append_line은 잠금 함수가 아니며 여기서는 잠금을 잡지 않는다.

캐시 없음은 허용, 명시적 reachable=None 항목은 보류, malformed 타입은 예외가 될 수 있다. 이미 큐에 들어간 영상은 차단 소비되어도 queued_ids에 남기 때문에 나중에 판정이 바뀌어도 이 생산자가 새 작업을 만들지 않는다. ‘보류는 버림이 아니며 판정이 바뀌면 다음 주기에 올라간다’는 설명은 아직 큐에 안 들어간 항목에만 해당한다. reachable=True/chapters:0의 재판정 사각도 여기에 이어진다.

상류 20과 하류 1을 이유로 자체 cap을 두지 않지만, backlog 백필과 여러 채널·실행·자료 크기를 제한하는 예산은 아니다. 테스트 60–155는 임시 feed의 건별 큐, 제목 비포함, 반복 실행과 부재/디렉터리 오류를 확인한다. 병렬 dedup·failed result 재시도·실제 모델은 검증하지 않았다. Zeus에서는 enqueued, rejected, started, completed를 별도 수명주기로 유지해야 한다.

## Zeus 비교와 검증 한계

Git 정의·PG runtime SSOT를 채택하려면 위 파일 워터마크와 JSONL 실행 사실을 그대로 권위로 사용해서는 안 된다. 자료 발견은 source identity와 immutable acquisition으로 연결하고, recurrence는 일정 세대 및 발생 ID로, worker는 fenced lease와 자격·예산으로, 결과는 직접 실행기 receipt와 산출 hash로 이어져야 한다. 사람 경험 인수는 읽음 watermark나 텍스트의 ‘카나리아’ 존재로 대신할 수 없다.

읽은 pipeline은 1단 report 또는 2단 note/uptake이고 marker/단어를 요구한다. 사용자 8단계 SDD의 해석·설계·구현·검증·실제 경험 인수와 동일한 승인 사슬이 아니다. 현행 Zeus src 전수 대응과 실제 8단계 실행은 이번에 검증하지 않았다. Linux Alpine compose의 실행 정의는 읽었으나 실제 시작/지속/복구는 미실행이고, Windows Task Scheduler·WSL host lease 및 경로 adapter는 이 파티션에서 확정하지 않았다. stdlib 사용이 운영체제 등가를 증명하지 않는다.

브라우저/네트워크 확인은 하지 않았다. 과거 사이트 자료는 원문 주장으로만 분석했으며 현재 사이트 정책이나 API 동작을 주장하지 않는다. blocked gatewriter probe를 재시도하지 않았다. full supporting, upstream tests, 실행 권한·신선도·동시성·crash·cross-platform 검증과 독립 Claude 검토·채택 판단은 remaining.json으로 남겼다.
