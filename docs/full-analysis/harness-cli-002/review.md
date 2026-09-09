# CLI 두 번째 파티션 독립 정적 검토

`harness:scripts/cli:002`의 **11개 파일, 178,390바이트**를 전문으로 읽었다. 원본은 `harness@a3f8b3be9a0a389329de6e16a6c7db81782041a3` pinned snapshot이며 manifest의 SHA-256·Git blob·크기를 대조했다. supporting-evidence는 실제 읽은 caller/config/test 구간과 그 파일 해시를 별도로 기록한다. 원문 지시는 분석 데이터이며 실행 지시로 상속하지 않았다.

원본 실행·설치·수정·probe·기기 조작·commit/push는 0건이다. 차단된 probe를 재시도하거나 우회하지 않았다. 아래는 현재 코드의 정적 경로와 반례 후보이며 재현 완료·전체 consumer 감사·Zeus 채택 승인·실제 Claude 검수를 뜻하지 않는다. 기존 테스트의 존재와 내용만 확인했고 실행 성공을 주장하지 않는다.

## C01 — 명령 계약과 작업 효과를 먼저 나눠야 한다

| 파일 | 실제 명령/효과 | 종료와 증거의 의미 |
| --- | --- | --- |
| error_contract_cmd.py | truth/score: 소스 AST와 Markdown 읽기 | 없는 프로젝트 1; 라우트 0·낮은 점수도 0. 채점 보고이며 배포 인수 게이트가 아님 |
| evolve_cmd.py | open/step/status: 계보·lease·세대 기록 | CONTINUE/CONVERGED 0; 다른 action 3; EvolveRefused 1. --executed는 호출자가 준 bool |
| extractor_canary_cmd.py | 임시 합성 소스 작성, 후보 reverse subprocess 실행, 판정·임시 삭제 | 0 아는 답 유지, 1 약화, 3 경로 오염, 4 불능. 임의 후보 코드의 격리 실행 보장은 별도 |
| fleet_contracts_cmd.py | atlas/fanout/ws: 정적 계약 관찰 | 고아·diverged가 있어도 보고 0. fanout 타입 미발견 1 |
| fleet_status_cmd.py | sync는 PG 갱신; list도 DDL 경로; feed --mark-read는 watermark 쓰기 | PG 불능 1; feed 일부 해독 불가+유효 항목은 0 |
| gate_dump_cmd.py | pipeline_loader 정규화 결과의 JSON 덤프 | 로드 오류·방출 0은 1; 인자 결손 자체는 판정하지 않음 |
| health_cmd.py | 여러 저장소·정책 판독, 조건부 subprocess | 기본 진단 0; --strict도 정해진 fails만 반영. quick에도 HUD spawn 가능 |
| hollow_cmd.py | 문자열 단언 탐지와 파일별 래칫 | 신규·증가·감소 미갱신 또는 py_targeted=0이면 1 |
| hook_latency_probe.py | bash/dispatch 실 spawn, 임시 state, latency.json 쓰기 | 정상 진단 반환은 0; timeout·인자·표시 예외는 별도 처리되지 않음 |
| hud.py | 상태줄 출력과 hud_render.json 원자 기록 | render 예외도 오류 문자열+0; 마커는 성공 표시·사용자 확인 영수증이 아님 |
| incident_cmd.py | record/resolve/list: 이벤트 원장 쓰기/읽기 | schema 거부·유령/중복 해소 1; 기록 성공이 수리 성공을 뜻하지 않음 |

이 파티션에는 설치기·서비스 등록기·Docker 배포기가 없다. 따라서 배포/서비스 자체를 완료 검수했다고 할 수 없다. 관련 범위는 Bash/Python 선택, 진단의 효과, 상태 위치, 오류 전파, 증거 해석이다. 모든 CLI의 `argv` 규약도 같지 않다. 일부는 `argv[1:]`, health/hollow/latency는 인자 목록 그대로를 받으며 이 차이를 Zeus 공통 dispatcher에서 어댑터로 명시해야 한다.

## C02 — error_contract의 required는 실제 도달 가능성 증명보다 넓다

`error_contract_cmd.py:392–562,790–930`은 AST 전체를 순회하고 호출의 마지막 이름으로 같은 이름의 함수 후보 전부를 연결한다. 이는 기존 이름 충돌에 따른 누락을 줄이는 방어이지만 객체/모듈/실행 조건을 판별하는 호출 그래프는 아니다. 잡혀서 변환되는 예외, 도달하지 않는 분기와 내부 함수의 raise도 required에 들어갈 수 있다. `_raise_info`는 HTTPException에 한정하지 않고 모든 raise-call의 첫 정수 인자를 상태로 해석한다. 예를 들어 도메인 오류 생성자의 숫자가 HTTP status라는 계약은 별도 근거가 필요하다. class status map도 이름 단위이며 테스트 파일을 포함한 전체 py에서 수집하고, 예외 아닌 클래스의 status_code와 동명 정의를 가른다고 볼 수 없다.

설정 기본값 수집은 Settings 타입을 식별하지 않고 모든 클래스의 같은 속성명 중 먼저 본 문자열을 취한다. 실제 환경변수·설정 주입 결과와 같다는 보장이 없다. `_py_files`는 정렬되지 않으며 패키지 이름 충돌과 setdefault의 선택을 source hash만으로 재현 가능하다고 단정하지 않는다. parse 실패는 None으로 빠지고 실패 파일 모집단을 반환하지 않는다. 자동 router 목록은 `APIRouter(` 부분문자열 기준이며 직접 FastAPI 라우트는 제외하고, 그 목록에서 `_is_test`를 적용하지 않는다. 반면 include/middleware 배선 탐색에는 테스트 제외가 있다. 모집단이 다르다.

접두를 파일 단위로 합쳐 같은 파일의 여러 router/app 구분이 사라진다. 동일 router가 여러 접두로 등록되면 경고를 남기는 방어가 있지만 실제 out에는 정렬 마지막 접두 하나를 고른다(651–655행의 '고르지 않고 알린다' 설명과 차이). APIRouter 자체 prefix 해소 실패는 빈 문자열이 된다. `_norm_path`는 대소문자·trailing slash·모든 path parameter 이름/타입을 합쳐 충돌 키가 생기면 뒤 경로가 앞 경로를 덮는다. include 순환에 비어 있지 않은 prefix가 누적되는 입력에서는 `(파일,prefix)` seen 집합이 계속 새 값이 될 수 있어 총 탐색 상한이 필요하다. `_strset_of`도 자기 참조 상수에 대한 깊이/순환 방어가 없다. 이번에 실행하지 않은 정적 종료 위험 후보이다.

함수 호출 depth와 별도로 import 파일은 2단만 펼친다. `--depth`를 늘려도 import 모집단은 늘지 않는다. unresolved_calls는 라우트 함수의 호출만 세고 대문자로 시작하는 이름 등을 제외하므로 모든 깊이의 해소 실패 목록이 아니다. APIRouter dependencies는 같은 파일 모든 router에 공통 합산하며 dependency 탐색의 depth_limited 값은 버린다. 시그니처 dependency가 검증하는 쿼리/body까지 422 판단에 포함한다고 볼 수 없다. required/conditional 분리와 blanket-approximation 라벨은 유용하되 금전·권한 실패 경로의 oracle로 바로 승격할 수 없다.

`score:935–1033`은 제목 상속과 EP 첫 줄 mapping을 사용하지만 상태 코드는 표 행/대문자 토큰이 있는 줄의 4xx/5xx 정규식이다. 부정문·코드블록·다른 엔드포인트 참조의 의미는 판정하지 않는다. 여러 endpoint 제목 아래 코드는 모두에 합산되며 알려진 route에 매칭되지 않는 문서 주장은 분모에 들어가지 않는다. path 정규식이 표현하지 못하는 문법도 있다. 결과에는 입력 revision/hash·상태별 source span·실행 환경 영수증이 없다. 라우트 0은 stderr 경고 뒤 exit 0이고 precision/recall은 분모 0에서 None이므로 caller가 이를 성공 인수로 해석하면 안 된다.

읽은 `test_error_contract.py:232–336`은 두 합성 프로젝트, 같은 함수명 충돌, prefix·상태·문서 점수·프로젝트 부재 CLI를 검사한다. 이 장점과 위 범위 밖을 함께 남긴다. pipelines에서 error_contract_cmd/fleet_contracts_cmd 정확명 검색은 0건이었으며, 간접 호출까지 없는 것은 증명하지 않았다.

## C03 — evolve CLI의 수렴은 실행 품질 자격이 아니다

`evolve_cmd.py:33,58–62`는 --executed와 임의 grade를 그대로 engine에 넘긴다. engine `evolve.py:207–261`은 이전 상태를 lease 취득 전에 읽고 similarity와 executed bool로 CONVERGED를 만든다. CLI나 이 engine 구간에는 실제 테스트 영수증·승인자 신원·동일 후보 해시 대조가 없다. grade는 수렴 조건이 아니며 --grade는 float로 NaN/Infinity를 차단하지 않는다. --frozen은 항목을 `.strip()`해 검사만 하고 원래 공백 포함 문자열을 전달하므로 `a, b`의 두 번째 키는 ` b`가 된다. 새 frozen 목록을 주면 기존 목록 대신 사용한다.

open은 spec 존재를 검사하나 명세 원문·해시를 개설 이벤트에 보존하지 않고 ambiguity와 target만 넘겨 기록한다. step은 후보 JSON dict/schema를 CLI에서 검사하지 않고 JSON/OSError/TypeError를 공통 명령 오류로 변환하지 않는다. 30세대 상태는 기록되지만 다음 호출 자체를 막는 terminal guard와 전체 wall-time/token budget은 이 경로에서 보이지 않는다. 이는 기존 엔진의 제한된 탐색 도구이며 Astra→Sol→Terra 수행 자격을 발급하는 기구가 아니다.

`test_evolve_smoke.py:118–148`은 30세대 action과 같은 후보에 --executed를 주어 CLI CONVERGED가 되는 계약을 검사한다. 실제 사용자 시나리오 실행 또는 자격 증명 검사가 아니다.

## C04 — extractor canary의 강한 부분과 제한

카나리아는 Python 합성 소스에서 산출물 6종의 entries 최소치와 **본문 정규식 여러 축을 독립 재계수**하고 알려진 2방향 import 순환이 FAIL로 나오는지 본다. 자기신고 정수만 믿는 과거 버전과 구분한다. tmp 경로의 tests/fixtures 평면 오염, 후보 reverse 부재·timeout·실행 오류를 별도 rc로 드러내고 finally로 임시 자료를 정리한다. `autoheart._g_canary` 실제 caller는 HEAD 기준선과 후보를 비교하고 기준선 불능/자·계약 변경을 DEFER로 남긴다. 정책 파일에도 카나리아 verifiable/collab_ask가 있으며 이는 **원본 정책 사실**이지 이번 Zeus 보고 작성의 승인 요구가 아니다.

그러나 실행하는 것은 후보 트리의 reverse.py와 그 import 전부이다. tmp source/output만 분리하고 subprocess의 cwd/env·네트워크·다른 파일 접근을 제한하는 OS sandbox는 이 함수에 없다. 후보 실행을 안전한 read-only 검사라고 부를 수 없다. 순환 검출과 최소 정규식 개수는 의미 정확도·누락 모집단·DB/HTTP runtime·TS·컨벤션·실기기·결제 인수를 증명하지 않는다. 정당한 렌더 변경도 실패시킬 수 있다는 caller 설명을 유지한다. 현재 모듈 앞 문서의 known-good 앵커 설명과 실제 caller의 HEAD 기준선도 구별했다.

## C05 — fleet 관측과 배포 계약을 혼동하면 안 된다

`fleet_contracts_cmd.py`는 입력 이름 중복을 dict로 덮고 root 존재·예상 언어 모집단을 CLI에서 검증하지 않는다. ws --server는 client의 `_pairs`와 달리 `=` 검증 없이 분리하여 잘못된 형식에서 `Path('')`를 넘길 수 있다. --alias 형상 오류도 공통 오류로 바꾸지 않는다. client 이름이 server/server_enums 등 출력 메타 키와 겹치면 동일 dict에서 충돌할 수 있다.

`fleet_contracts.py:345–409`의 atlas는 HTTP 메서드+경로 와일드카드와 RPC service+name을 대조한다. base URL 귀속, payload/response schema, auth, 실행 버전, 실제 배포 호환성은 별도이다. RPC 같은 이름의 backend는 마지막 하나가 남는다. 원문이 고아=관찰이고 정상 함대 밖 서버가 있다는 점을 명시하므로 고아를 곧바로 배포 차단으로 분류하지 않는다. CLI는 어긋난 관찰에도 0을 반환하며 atlas/ws JSON에는 실제 실행 영수증이 없다.

fanout --type은 loc_cap만 10,000으로 늘리며 engine의 top 15 carrier/top 5 overall 제한을 풀지 않는다. 정의되고 5회 이상 호출되는 타입도 순위 밖이면 '미만이거나 정의 클래스 아님'으로 표시할 수 있다. --type과 --json을 같이 주어도 타입 분기가 먼저여서 텍스트가 나온다. 긴 locations 출력의 절단 수도 해당 분기에서 표시하지 않는다.

읽은 fleet 계약 테스트에는 합성 텍스트 대조뿐 아니라 `C:/Users/rudtn/outpos/...` 경로가 존재할 때만 도는 실제 소스 카나리아가 있다. 부재 시 건너뛰며 그 테스트도 소스 관측이다. 삼성 기기 실행이나 지급/취소 end-to-end 실적이 아니다. 이 외부 앱 경로를 이번에 읽거나 실행하지 않았다.

## C06 — fleet_status: projection과 읽음 영수증의 경계

`projection_pg.py:25–67`은 원장 기반 PG projection을 트랜잭션으로 재생성한다. list의 summary도 CREATE TABLE IF NOT EXISTS를 호출한다. done은 파이프라인 terminal 집합을 모른 채 관측 단계 전부 DONE인지로 근사한다. 선언되어 있으나 시작하지 않은 단계가 분모에 없을 수 있으므로 이 근사를 보수적 완주 판정이라고 Zeus에 그대로 이식하면 안 된다. run label 재사용은 다른 ledger 내용을 같은 키에 덮는다. 원문은 **파일 원장 정본/PG 비정본**이므로 사용자의 Zeus PG runtime SSOT 요구와 명시적인 변환이 필요하다. PG 실패 1+안내 테스트는 있지만 현재 DB를 접속/확인하지 않았다.

feed는 파일 부재와 빈 저장고를 구분하고 깨진 줄 수를 드러내며 완전 판독 실패에서 watermark를 옮기지 않는다. 외부 텍스트와 injection 표지를 자료로만 보도록 출력하는 장점이 있다. 그러나 유효 JSON scalar/list의 형상 검사와 UnicodeDecodeError 처리는 없어 digest의 `.get`에서 실패할 수 있다. 일부 깨진 줄+정상 항목은 rc 0이며 --mark-read가 최신 timestamp까지 이동한다. 화면에 recent 일부만 보여도 전체 최신 시각을 읽음으로 표시하고, 이후 복구된 과거 줄·동일 timestamp로 뒤늦게 추가된 항목·무시각 항목은 '새 것' 집계에서 빠질 수 있다. timestamp 기준 전역 watermark에는 사용자가 실제 확인한 항목 ID 집합이 없다. 원자 replace는 있지만 read-compare-write 동시성 직렬화는 이 CLI에 없다.

`feed --json --mark-read`는 JSON 뒤 일반 텍스트 읽음 표시를 stdout에 더하여 단일 JSON 계약이 깨진다. `research_digest.digest`는 `since`로 new 수만 가르고 recent는 전체 items 최신 목록에서 고른다. board도 이 digest와 동일 watermark를 사용한다. 다만 자동 연구 큐는 queued_watermark를 별도로 사용하므로 사람이 읽음 처리하면 자동 큐가 함께 소진된다고 주장하지 않는다.

## C07 — gate_dump와 hollow가 증명하는 것은 제한된 검사 계약이다

gate_dump는 로더의 정확한 정규화 결과를 써서 판정 복제를 피하고 structured/derived/all 분모, check_types, load_errors를 내며 0방출을 거부한다. 실제 lint 소비자는 --scope all로 읽고 enum 표를 대조하지만 `_derived_by` 파생 check의 결손은 개수를 알리고 판정 밖에 둔다. 74/106/28 같은 독스트링 과거 수치를 현재 측정치로 재선언하지 않았다. 현재 로더의 해당 코드는 199–221행이며 원문 CLI의 과거 150행 참조는 낡았다. 'structured PASS'는 runtime에서 실행될 모든 check의 실행 가능성을 증명하지 않는다.

hollow는 주석·독스트링 제거 뒤 문자열이 남는지를 분류하는 탐지기다. 신규/증가뿐 아니라 감소 시 freeze 갱신을 요구하고 py_targeted=0을 막는 계약이 있다. 현재 config hollow_freeze={}는 선언이며 이번 실행으로 공허 0을 확인하지 않았다. 파일별 집계 키가 상대 경로가 아닌 basename이라 다른 하위 디렉터리의 test_x.py가 합쳐진다. 같은 파일에서 하나를 지우고 다른 하나를 추가하면 개수는 같으므로 의미별 재발을 보장하지 않는다. parse 실패 테스트는 빈 목록, 파싱 불가 대상은 원문으로 보수적 WEAK가 되며 변수 경로·작은따옴표 경로 등 정적 해소 제한도 있다. ABSENT/WEAK 자체는 CLI 위반으로 접히지 않는다. 기존 테스트가 그 제한과 양방향 래칫을 검사한다는 사실을 함께 기록한다.

## C08 — health의 quick/read-only/strict를 재정의해야 한다

`health_cmd.collect(False)`→`sec_wiring(False)`→`settings_wiring.evaluate(dry_run=False)`는 **항상 check_statusline을 포함**한다. statusLine 선언·bash·runtime pin 조건이 맞으면 HUD 런처를 subprocess로 실행하며 HUD main은 hud_render.json을 쓴다. 이 subprocess에는 임시 HARNESS_STATE_DIR도 주입하지 않는다. quick 설명의 '정형 3겹'과 읽기 전용 설명보다 실제 효과가 크다. sec_safety도 guardian seal verify subprocess와 anchor 판정을 호출한다. `--full`의 temp state는 dispatch 이벤트 부분이며 모든 의존 효과를 격리하지 않는다. 이번 분석에서 health 명령을 호출하지 않은 이유도 이 범위 차이다.

`sec_ledger`가 읽기 오류를 반환해도 이후 sec_stages/sec_debates는 원장을 다시 읽고 예외를 밖으로 보낼 수 있어 전체 collect의 실패 격리가 아니다. `_age_s`는 naive datetime에서 timezone-aware now와 뺄 때의 TypeError를 잡지 않는다. 여러 JSON 경로가 객체 형상을 전제한다. sec_safety의 seal 판정은 rc==1만 tamper로 분류하고 다른 rc의 불능 상태를 명시 필드로 구분하지 않는다. guardian 부재를 `.git` 디렉터리 여부로 expected 처리하므로 export/container/worktree에서 운영상 guardian 필요 여부와 일치하는지 별도 설정 계약이 필요하다.

`_fails:758–785`는 ledger/wiring/safe-mode/tamper/params/anchor/guardian 일부만 접는다. suite의 not_green·진공·침묵 실패, 읽기 불가 alerts, 사람 대기열 오류, ownership/ladder 오류, stale heartbeat/latency는 각 표면에 있더라도 strict 최종 FAIL의 완전한 목록이 아니다. 이는 소프트 진단 설계이며 strict를 전체 서비스 준비/배포 승인으로 해석하면 안 된다. guard 최다 표시는 `max(..., key=-count)`라 빈도가 가장 작은 항목을 고르는 코드이다(930행). 이 역시 정적 발견이다.

`_role_delivery`는 런 원장과 results 주장을 대조하고 최근 10개 창과 누적치를 분리하지만 **텍스트 main 분기에서만 호출**되어 JSON collect에는 없다. ledger/role-runs 안의 디렉터리에서 역할을 찾으므로 legacy 파일만 있으면 제외되고, 손상 run은 조용히 건너뛴다. 결과 경로는 state_dir()가 아닌 home/state 고정이며 중복 request_index가 최근 창에 반복 집계될 수 있다. 서비스/세션 상태는 실제 프로세스 생존·배달 완료와 대조할 별도 계약이 필요하다.

## C09 — latency 생산·판독·갱신·차단의 네 경로가 다르다

probe는 함수 decorator보다 바깥에서 bash+Python+handler wall clock을 재고 temp state의 과소 추정을 명시한다. 단일 이벤트의 floor/body/over_budget을 None으로 표시하는 방어도 있다. 그러나 main 텍스트 출력은 body_est_ms에 `:6.1f`를 적용하므로 단일 --event의 None에서 TypeError가 예상된다. --json 경로는 이 포맷을 지나지 않는다. repeat 0/음수는 빈 samples의 median/max 오류이며 범위 검증과 timeout 예외 변환이 없다. 따라서 독스트링의 '항상 exit 0'은 예외까지 보장하지 않는다.

probe는 `shutil.which('bash')`를 직접 쓰고, wiring의 runtime bash_exe pin·Windows 경로 접근 확인을 재사용하지 않는다. Windows Task Scheduler의 WSL stub/Git Bash 차이를 원문 wiring이 이미 다루는데 측정기는 여전히 다른 선택 경로다. event×repeat의 전체 예산·샘플 배열·OS/shell/interpreter 버전·commit/config hash를 영수증에 담지 않는다. 모든 이벤트 최소 median은 순수 spawn 비용 자체가 아니며 최소 이벤트의 본문 비용까지 차감한다. 측정된 값을 '실제 본문 비용'으로 확정하지 않는다. latency.json은 atomic helper가 아닌 직접 write_text이고 고정 home/var에 쓰는 반면 health는 resolve('var')로 읽으므로 경로 설정 변경 시 분리될 수 있다.

health.sec_latency는 나이 None에서 stale=False/probed=True를 반환한다. 실제 cron/latency_gate는 이를 그대로 믿지 않고 age None을 unknown으로 접으며 오염(rc_nonzero)·산포>=budget 이벤트도 별도 제외한다. 이 방어와 계약 테스트를 확인했으므로 '모든 소비자가 불명 측정을 정상으로 판정'한다고 과장하지 않는다. 그러나 l2_driver._latency_pass는 probed is not False이면 갱신을 건너뛰어 시각 불능 자료가 자동 치유되지 않을 수 있다. 빈 events·부분 events·단일 floor=None의 모집단 최소 요건도 게이트에 보이지 않아 age만 정상이고 over 목록이 비면 '전 이벤트 예산 안'이라는 문구가 과하다. runtime gate는 unknown/stale를 이유와 로그를 남기고 통과시키며 예외도 fail-open; 금융 승인 게이트와 같은 정책으로 이식할 수 없다.

## C10 — HUD를 영수증과 운영 진실로 승격하지 말 것

HUD는 ANSI 스타일/ASCII fallback, UTF-8 LF, JSONL tail 64KB, git 명령별 timeout, 원자 마커 쓰기를 갖춘다. 하지만 마커는 `{ts,model}`뿐이고 main 직접 호출·wiring smoke·render 예외에서도 기록될 수 있어 'CC TUI 실제 호출'이라는 주석을 그대로 신뢰할 수 없다. 실제 사람이 화면을 보거나 오류 없는 UI를 확인한 증거는 없다. statusline 검사도 pinned일 때 rc0+비어 있지 않음만 보므로 `hud error: ...`가 성공 조건에 해당할 수 있다.

run의 P/F는 tail 안의 과거 gate_verdict 사건 수이며 현재 단계 최종 상태·전체 실행 완료·인수 결과가 아니다. lease active 표시는 만료 시각/프로세스 생존을 검사하지 않는다. git은 -uno로 untracked를 빼고 remote fetch 없이 로컬 upstream ref만 비교하며, 실패가 빈 문자열로 접히면 dirty 미관측이 0처럼 보일 수 있다. 같은 이유로 이 표시를 배포 가능성 영수증으로 쓰면 안 된다. context는 최근 사용량 또는 ~20k 추정치이고 token 비용·총 예산·모델 품질 자격이 아니다.

전 세그먼트 fail-soft라는 문구와 달리 collect tuple은 세그먼트를 먼저 평가하여 형상 오류 하나가 전체 render 예외로 이어질 수 있다. parking/크래시 판독 실패를 생략하는 분기도 있어 모든 축이 ?로 표시되는 것은 아니다. 모델명·경로·branch 등 입력의 제어문자 정제 경로는 없다. 기존 smoke는 합성 파일과 문자열 렌더·런처 subprocess를 검사하며 실제 터미널 폰트/폭/사용자 핵심 시나리오 인수와 구분한다.

## C11 — incident는 티켓 후보 원장이며 수리 승인서는 아니다

record는 component 폐쇄 어휘·severity·fingerprint·depth/caused_by·synthetic bool을 판정하고 ledger.append_event는 파일 lock 안에서 append한다. resolve는 알려진 fingerprint와 현재 해소 상태를 검사하고 재record를 재개로 도출한다. 이런 재발 이력은 Zeus 티켓 원장에 흡수할 가치가 있다.

그러나 --note required는 옵션 존재만 강제하므로 빈 문자열/공백도 전달 가능하다. append_event의 추가 검사는 route가 실렸을 때의 어휘이며 incident_resolved의 수리 근거/hash/검증 영수증을 검증하지 않는다. fingerprint는 component와 묶이지 않아 두 컴포넌트 같은 fingerprint가 같은 해소 상태를 공유한다. resolve의 read/check/append 전체를 동일 lock으로 감싸지 않아 동시 resolve 또는 재개와 경합하면 개별 append 원자성만으로 의도한 상태 전이를 보장하지 못한다. _all_events는 깨진 JSON 줄을 건너뛰고 비dict JSON을 검증하지 않는다. list는 과거 사건에 현재 fingerprint 해소 여부를 붙이며 독립 사건별 해결 상태가 아니다.

기존 backlog smoke는 note 옵션 부재·유령 해소·중복 해소·재개를 검사한다. 공백 근거, 동시성, 서로 다른 component의 fingerprint 충돌, 실제 복구·사람 QA는 이번 읽은 구간에서 검증되지 않았다. GitHub Issues 생성/동기/인증/재시도·동일 티켓 idempotency는 이 CLI에 없다. 로컬 티켓+GitHub 연동은 별도 Zeus 구현 과제이다.

## Zeus 대응 및 검토 종료 경계

SDD 1–2단계에는 오류 계약/fleet 정적 관측을 **출처·모집단·미해소 항목이 있는 검토 후보**로 제시한다. 3–4단계는 코드 변경과 독립 oracle의 계약 테스트를 연결하고, canary/hollow 검사 범위와 실제 실행 인수를 분리한다. 5단계 알파와 7단계 라이브는 빌드·배포·환경·서비스 상태·rollback 영수증을 추가해야 한다. 6단계는 실제 인간 시나리오, no-mocked acceptance, reset/기기/금전 실패 및 승인자 확인을 필요로 한다. 8단계 CS에서는 누적/현재/최근을 구분하는 로그, 손상·누락·측정 불능 notification, 재개 가능한 티켓과 회귀 시나리오가 이어져야 한다.

Git 정의/PG runtime SSOT 변환에서 projection의 근사 done, 파일 watermark, 호출자 executed bool, HUD 마커를 runtime 사실로 옮겨서는 안 된다. stdout JSON과 stderr/exit 계약, 관찰·실행·승인별 actor/correlation/revision/environment, idempotency·동시성·기한·예산을 별도로 설계해야 한다. Astra 첫 설계/최종 검증, Sol 중요 구현, Terra 단순 구현의 이관은 실제 수행 결과와 가드레일 자격 증거가 있어야 하며 이 11개 CLI만으로 구현됐다고 볼 수 없다.

전문 읽기와 파일 해시 검증은 완료했다. 현재 공식 문서/라이선스 검토, 전체 consumer 감사, 실제 Claude 교차검수, Windows/WSL/Linux 격리 실행, 원본 테스트 실행, 실제 서비스/금융/기기 인수와 Zeus 채택은 미완료다. 삼성 기기 및 Device Farm SDK/MCP/Replay는 유예이며 이번에 구축하지 않았다. 탐색 출력 1회가 잘렸으나 이를 전문 읽기 증거로 세지 않았고 보고에 사용하는 supporting은 별도 구간을 다시 읽었다.

Supporting `.claude/settings.json`은 manifest에 snapshot_sha256가 없는 항목이다. 원본 2,146바이트와 Git blob `543919592f4bf4b9e0f0e9eb16299c1788b84409` 일치를 검증하고 SHA-256을 이번 supporting 기록에 새로 계산했다. 이를 manifest SHA-256 검증 성공으로 표현하지 않았다. primary 11개에는 모두 manifest SHA-256이 있으며 검증됐다. shared manifest/coverage는 수정하지 않았다.
