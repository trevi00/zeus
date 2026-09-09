# Harness contract 시험 001 — 정적 검토

정본은 harness `a3f8b3be9a0a389329de6e16a6c7db81782041a3`이다. partition `harness:tests/contract:001`의 11개, 195,089 bytes 전문을 읽었다. inventory.json은 정확한 경로 분모이고 files.json은 각 원본의 SHA-256/Git blob/행/판단 연결이다. 지원 원본은 supporting.json에 기록한 구간만 읽었다. 모든 primary는 `body_reviewed_call_test_trace_pending`이며 시험 존재를 실행으로 세지 않았다. 원본 실행·import·probe·network·install은 0회다. 이 문서의 명령 문자열은 분석 자료이며 수행 지시가 아니다.

## 공통 오라클와 실행 분모

시험은 대체로 `check()`가 출력하는 `  ok`/`  FAIL` 행과 프로세스 종료값으로 집계된다. test_outcome 96–101, 189–251과 suite_cmd 75–150, 341–376을 직접 읽었다. rc=0이어도 실패 단언이면 silent_fail, 단언 0이면 ^SKIP: 선언 또는 vacuous로 구별한다. SKIP-AXIS는 별도 목록에 실리지만 다른 단언이 통과하면 suite 상태는 pass다. 따라서 suite pass는 모든 축의 검증이나 채택 승인과 같지 않다. 출력 문자열 개수는 독립 시나리오·실제 시스템 동작 개수와도 다르다. freshness/grade의 probes 내부 실패 목록은 외부 check 한 번으로 모이므로 많은 조건을 하나의 단언으로 셀 수 있다. mutation 루프는 표적 개수 검사와 변이 적발을 따로 출력하며 실제 mutation 실행 분모와 assertion 분모가 다르다.

tests/_isolate 47–107은 HARNESS_L2_SPAWN/HARNESS_HOME을 제거하고 STATE_DIR만 임시 위치 또는 기존 주입값으로 돌린다. 이는 OS sandbox가 아니며 원본 트리·guardian·네트워크 접근을 봉쇄하지 않는다. 이 파티션 시험을 현재 실행하지 않은 이유다. live_axis는 입력 지문이 달라지면 skip_axis를 내고 호출자가 단언을 생략하게 한다. 지문 원리의 한계 및 입력 탐침 전체는 별도 폐쇄가 필요하다.

## f01

`tests/contract/_isolate.py` 1–20: 정본 tests/_isolate.py를 importlib로 실행하고 __all__을 재수출하는 shim이다. 자체 assertion/실행 분모가 없으며 runner의 test_*.py 패턴에 해당하지 않는 지원 모듈이다. 수동 export 목록의 드리프트를 줄이는 방어는 유효하지만 loader 실패나 잘못된 __all__은 import 단계에 전파된다. 원본 정본의 환경 변경·atexit cleanup을 상속한다. Zeus에서는 격리 환경 설정과 실제 실행 backend를 분리하고 shim 존재를 안전한 실행의 증거로 삼지 않아야 한다. supporting s01/s02/s03 참조. 과거 2026-08-27 ImportError 설명은 역사적 주장이다.

## f02

`test_acceptance_coverage_contract.py` 1–351: acceptance 탑재를 완료 판정의 차단 조건과 분리하는 가산 관측 계약이다. 합성 dispatch에서 PRESENT/ABSENT/INDETERMINATE, 빈 값/손상 contract, 비위임 제외, 동일 stage 재위임의 분모 보존을 검사한다. 같은 stage를 dict key로 합쳐 ratio 1.0이 됐다는 과거 수리 이유는 fixture에 ABSENT+PRESENT 두 건으로 반영됐다. 이 방어와 0/0=None은 보존 후보다.

실제 구현 derive_state 365–417은 nonempty list이면 refs 항목의 schema·좌표·실제 판정 기준 내용 없이 PRESENT로 친다. compaction을 하나라도 만나면 모든 남은 항목을 INDETERMINATE로 바꾼다. 이때 total>0이면 ratio는 0.0이므로 소비자가 ratio만 보면 '모름'과 실제 미탑재를 다시 섞는다. 시험은 이 조합의 ratio를 확인하지 않는다. runtime 단계 상태 86–95는 ERROR를 FAILED로 처리하지만 완료 fold 163–165는 PASS/FAIL만 갱신한다. 따라서 과거 PASS 뒤 ERROR만 온 경로에서 상태와 completed가 갈릴 수 있는 정적 분기가 있다. 이 시험의 가산 불변성 검사는 그 상태 축을 검증하지 않는다.

93–119의 소스 문자열/4함수 개수/직접 함수명 검색은 간접 호출·alias를 배제하지 못하며 관측 소비자 추가도 무조건 실패시킬 수 있다. 210–319의 실제 role-runs 집계는 고정 fixture가 아니라 당시 데이터에 의존한다. tot>=21, pres==0, 파일>=10, 다중 run 존재를 잠그므로 올바른 acceptance 증가가 오히려 red가 되는 역사적 감시 계약이다. 마지막 run 필드 부재 확인은 runs[:1]만 읽고 빈 항목이면 all이 자명하게 참이다. 현재 그 role-run 원본을 전수 읽거나 이 수치를 재측정하지 않았다. Zeus SDD에서는 위임 ID/실행 generation/불변 acceptance handle을 PG에 보존하고 내용 검증과 관측 비율을 별도 축으로 둬야 한다.

## f03

`test_arm_reopens_cycle_contract.py` 1–282: 실제 selfimprove YAML/lexicon/paths 및 validators를 임시 home에 복사하고 모든 stage에 PASS event를 심어 DONE→새 candidate 재개방→PENDING, attempts 보존, cycle event/계획 파일 존재를 검사한다. 진행 중인 cycle을 열지 않는 음성 대조군도 있다. 실제 candidate dispatch나 작업 성공이 아니라 직접 helper 호출과 합성 원장이다. _try_arm의 호출·로그 순서와 autocompact는 inspect 문자열 검사이므로 실제 CLI 옵션 수용·모델 컨텍스트·복원 품질을 증명하지 않는다.

문서 첫 부분의 '두 수리'와 달리 64–81은 already_armed 변경을 되돌렸으며 스폰 실패 시 후보 소진이 남았다고 명시한다. SUT arming 422–434는 external_action 키를 영구 제외하고 l2_driver 1297–1337은 키를 쓴 뒤 run_cmd.arm/재개방을 호출한다. rc 실패 통지는 있어도 자동 재시도는 복구하지 않는다. 재개방 SUT 743–778은 전체 pipeline stage의 DONE을 확인하며 failure는 incident로 시도한다. 기록기 자체 실패는 로그로 끝난다. 시험의 마지막 canary는 기록 함수를 제거하고 비어 있는 원장/없는 pipeline으로 검사하여 incident 경로 한정이며 실제 후보 복원·lease 경쟁은 다루지 않는다. 계획은 초 단위 파일명이라 충돌 여지도 미시험이다. Zeus는 후보 ID와 cycle generation을 구분하고 재개방/소진/실패를 PG transaction 및 실제 receipt로 결속해야 한다. 사용자 8단계 재개방 정책은 이 5단계 YAML에서 자동 상속할 수 없다.

## f04

`test_arming_freshness_contract.py` 1–475: grade를 limb, 승인을 제외한 합성 규칙으로 고정해 freshness만 움직인다. stale/fresh 양방향, None 적용 범위 밖, 미주입/예외/비객체, 다중 배제와 사유·분모, grade 우선, 미측정 census를 검사한다. frozen date와 assess 실제 함수 반환을 사용하지만 git 조회나 사람 승인·실제 arm은 수행하는 시험이 아니다. 10개 내장 mutation은 소스 literal 한 번 교체 후 compile/exec하는 자체 리그다. 임의 예외도 '적발'로 세므로 의미 오라클가 변이를 잡았는지와 실행 불능을 별도 구분할 필요가 있다. 이번에는 그 리그도 실행하지 않았다.

arming 618–638은 미주입/예외를 차단하며 None 반환은 통과한다. 직접 caller spiral_cmd 273–278은 prop가 아니거나 **prop 파일을 못 찾은 때도** None을 반환한다. 순위 산출 후 파일 소실/불일치가 '적용 범위 밖'으로 통과할 가능성은 이 fixture가 다루지 않는다. assess 170–217은 문서의 측정일/시각과 주입된 변경일에 의존한다. 음수 나이(미래 측정), 원본 SHA·실제 실행 receipt·허위 측정일은 이 범위 시험 밖이다. 시각의 진실을 사람 diff 검토에 둔 주석은 실행 증거가 아니다. Zeus에는 승인 당시와 dispatch 당시 artifact identity 재검증 및 불능/비적용의 별도 타입이 필요하다.

## f05

`test_arming_grade_axis_contract.py` 1–593: 불가침-only 차단, 혼합 허용/표시, 경로 없음·미주입·부분 dict, N>1 배제·굶김·타 트리·exclude, 예외형 보존, 실제 sandbox.classify 주입과 dotfile/경로 정박을 다룬다. 단일 원소 fixture가 외부 mutation 9/10을 놓쳤다는 역사는 다중 fixture로 보강됐지만 현재 재현 결과는 아니다. 내장 mutation 7종은 수리와 같은 패치에서 작성됐다고 스스로 적는다. independent preregistration과 동일시하지 않는다.

승인 축은 186–224에서 guardian 키가 있으면 실제 sign 함수로 **합성 human event**를 만든다. 없으면 SKIP-AXIS이고 probes 바깥의 통과 단언은 남는다. HMAC 계산 실물은 사람 의사 확인의 실물이 아니다. approval_proof 111–136의 서명 대상은 candidate 문자열뿐이며 source/current revision·근거·scope·유효기간은 여기에 결속되지 않는다. isolate는 GUARDIAN_HOME을 지우지 않아 외부 키 위치를 읽을 수 있지만 이번에는 키 파일을 읽지 않았다.

SUT _grade_gate 558–574의 try는 grade_fn 호출만 감싼다. 반환이 dict가 아니면 이후 .get에서 예외가 날 수 있고, 미지 grade 문자열은 inviolable와 같지 않아 허용되는 길이 있다. 주석의 '미지 값 fail-closed'보다 약하며 시험은 partial dict와 throw를 다루지만 미지 값/비dict 반환을 다루지 않는다. real sandbox.classify는 정책 grade를 allowlist로 정규화하므로 현행 직접 caller에서는 방어가 있지만 주입 계약 전체를 닫지는 않는다. 혼합 후보의 auto는 불가침 패치 적용 승인과 다르다. Zeus는 typed grade, 완전한 반환 schema, 실행 대상 diff 전체/자격/사람 결정을 별도 검증해야 한다.

## f06

`test_artifact_type_registry_contract.py` 1–412: schema enum 29종과 외부 design O-4 집합, loader의 declared value 차단/미선언 허용, indexer 전달, jsonschema 검사, 전체 YAML 빌드, 이름 기반 파생 및 plane 고정·classifier 어휘를 검사한다. enum/인덱서 직접 SUT 및 schema 구간을 읽었다. 외부 design 경로는 HOME.parent/harness-design이므로 격리 snapshot에서 관계가 보존된다는 보장이 없고 이번에는 그 외부 문서 전문을 새로 읽지 않았다. 54/9 경로·산문 개수는 당시 파이프라인 내용에 결박된 회귀 수치다. .yaml 한 계층만 scan하므로 저장소의 모든 설정을 빌드한 것이 아니다.

**미검증 집계 누락:** design 부재는 skip_axis로 올바르게 선언하나 jsonschema ImportError 230은 `  SKIP:`라 suite의 ^SKIP:/^SKIP-AXIS: 둘 다 맞지 않는다. 나머지 assertion이 성공하면 missing validator 축 없이 pass로 요약될 수 있다. 218–220은 truthy typed 노드와 빈 문자열만 검사해 '형 없는 노드는 키 자체가 없다'는 표현보다 약하고 null/다른 falsy 값을 놓친다. indexer 160–163은 빌드 실패 pipeline을 조용히 제외하지만 별도 t_real_pipelines가 일부 보완한다. indexer는 plane=design, provenance created_by=user를 정적으로 붙여 실제 저자·승인 증거가 아니다. Zeus 8단계 산출물의 enum 정의는 Git 관리 후보이고 인스턴스 증거/완료는 PG에서 별도로 결속해야 한다.

## f07

`test_board_publisher_smoke.py` 1–485: 실제 generator로 렌더링한 판의 시간 정규화, 상태 변화 구별, drift 최초 시각, mark-published, lock 및 소스 규율을 다룬다. STATE/LOCK/BOARD는 임시 경로로 바꾸지만 generator subprocess에서 HARNESS_HOME/STATE_DIR을 제거하고 실제 source home 입력·guardian token·PowerShell scheduler를 읽는다. tmp 출력만 격리한 시험이며 단순 offline fixture가 아니다. Windows Get-ScheduledTask 가정과 살아 있는 데이터 칩·마커 전제가 있어 Linux/WSL 이식성 성공을 주장할 수 없다.

clock shift는 `_left`가 짧을 때도 max(60, ...)을 적용하므로 '만료 경계를 안 넘는다'는 설명을 항상 보장하지 않는다. 첫 a 생성 뒤 live_axis를 열어 생성기의 실제 읽기 시점과 fingerprint 창이 일치하지 않는 공백을 문서가 인정한다. ①-b의 clock-shift 비교에는 같은 live_axis가 없고, 숫자 칩 부재 341의 상태 문구는 SKIP-AXIS가 아니라 집계 밖이다. '전수 봉인'은 전체 시간 경계 증명이 아니다.

lock 시험은 순차 acquire/재획득/mtime stale만 본다. SUT 208–217은 exists→write여서 원자 획득이 아니며 release는 소유자 검증 없이 unlink한다. save_state의 os.replace 문자열 존재는 crash/durability/동시 writer 시험이 아니다. --mark-published는 실제 remote 게시 확인을 요구하지 않고 현재 local hash를 기록한다(252–260). 시험의 mark-published 성공도 remote 게시 성공이 아니다. Zeus는 관측 UI 상태와 실제 publication receipt를 분리하고 PG lease/소유권/인수 증거를 사용해야 한다.

## f08

`test_boundary_corpus_smoke.py` 1–184: 작은 JSONL 합성 corpus에서 shell 명령 추출·중복 제거·손상 허용, 보호 경로 deny/일반 allow, missing/empty corpus exit2, 변경 방향 exit1을 검사한다. 이후 git_flow.read_settings만 대체하여 gate 명령 실행을 막고 cwd 해석은 보존한다. spy로 실제 decide가 그 wrapper를 쓰는지 확인하는 보강은 단순 문자열보다 강하다. 그러나 선언 의존 push gate를 의도적으로 측정하지 않으며 --as-unattended 상태/두 project 배치도 이 시험에서 호출하지 않는다. fixture가 제공하는 'PowerShell' 명령은 harvest 뒤 command 문자열만 남아 SUT decide가 tool_name=Bash로 재포장한다. 서로 다른 shell parser 계약의 등가는 미검증이다.

SUT 176–260은 corpus 자체 0을 거부하지만 baseline과 공통 명령 0은 허용하여 변화 0/rc0이 될 수 있다. 예외는 ERR로 표시하지만 snapshot/denies는 rc0이고 diff도 일부 ERR을 실패로 만들지 못한다. fixture는 malformed JSON row를 제외하는 손실 분모·외부 read 실패·동일 command의 서로 다른 cwd/user·빈 공통집합을 다루지 않는다. 과거 미탐19건/1416배는 문서 주장이고 산술·실측을 이번에 재검증하지 않았다. Zeus에는 명령+shell+cwd+권한 context와 생략/불능 분모를 묶어야 한다. 원문에 적힌 gate 무력화 코드는 분석만 했으며 차단 probe를 실행하거나 우회하지 않았다.

## f09

`test_bus_tailer_contract.py` 1–242: 가짜 confluent_kafka 모듈을 sys.modules에 넣고 produce payload/key와 flush 호출, solo 무동작, 부분 JSON 보류/완성 후 발행, 증분 watermark와 corrupt key를 검사한다. 가짜 producer는 delivery callback을 호출하지 않으며 전송 성공을 모사하지 않는다고 명시한다. 실제 Kafka ACK/토픽 보존/재생/접속 권한의 증거가 아니다. 가짜 모듈을 복원하지 않아 같은 process suite 실행에서는 후속 진짜 Kafka import도 가짜가 될 수 있다. 현재 suite_cmd의 별도 process 실행이 이 오염을 격리하는 전제다. state 경로 prefix 문자열 검사는 기존 STATE_DIR 주입을 존중하는 isolate 계약과 항상 일치하지 않는다.

l2 cycle co_names 검사는 호출의 존재 힌트이고 실제 스케줄 실행이 아니다. safe mode 존재 시 _bus_pass는 일찍 반환하므로 직접 예외 주입 축은 외부 safe mode 상태에 영향받을 수 있다. **연결 공백:** bus_tailer 118–123은 배달 실패를 published=0/held/failed로 정상 반환한다. l2_driver 549–557은 skipped/양수 published/예외만 로그하며 이 정상 실패 반환은 침묵한다. 시험 199–212는 RuntimeError만 주입하므로 이를 못 본다. Zeus PG outbox→버스 미러는 전송 결과별 receipt와 별도 실패 상태를 보존하고 '큐에 넣음'을 배달로 세지 않아야 한다.

## f10

`test_bus_topic_order_contract.py` 1–321: collab 문자열이 있으면 정확한 decision line을 요구하고 이후 kind 어휘를 3 queue KIND와 ROLE_PIPELINES 양방향으로 비교한다. 합성 tree의 hyphen/placeholder/부정 문구 대조군과 결정 착지 유지 assertion을 보존할 수 있다. 실제 결정 보고서 108행과 queue 상수 및 driver mapping을 읽어 현재 고정 바이트의 연결을 확인했다. 보고서의 심판 승인·독립 재확인 불가·역사 수치는 현재 Claude 검토나 사용자 승인이 아니다.

scanner는 scripts/pipelines/infra의 py/yaml/yml 행에서 regex를 찾을 뿐 AST code와 comment/docstring을 구분하지 않는다. 따옴표 없는 prose fixture만 제외하므로 quoted 주석은 오탐 가능하고 문자열 동적 조립·외부 config·unquoted YAML은 누락 가능하다. exact decision line도 fence 안 복사된 줄의 진정성/승인 주체를 검증하지 않는다. QUEUE_WRITERS 목록은 손으로 고정된 세 모듈이라 신규 writer 발견 전체를 보장하지 않는다. 실제 Kafka partition order·consumer offset·재파티셔닝 시험은 0이다. Zeus에는 kind 정의를 Git schema로, 메시지 ID/lineage/전달 상태를 PG 권위로 두고 8단계 인계와 조직 role을 혼동하지 않아야 한다.

## f11

`test_bus_watermark_contract.py` 1–262: 실제 confluent_kafka 라이브러리와 127.0.0.1:59999가 비어 있다는 가정으로 timeout 잔량 및 영구 실패 callback을 검사한다. 의존성 부재는 줄 시작 SKIP: 후 0이며 러너가 full skip으로 분류하는 정당한 경로다. 설치된 library가 있으면 실제 socket 통신을 시도하므로 network 없는 정적 검토가 실행했다고 말할 수 없다. 모든 원본 실행을 하지 않았다. 환경 STATE_DIR을 덮었다가 pop하므로 기존 주입값 복원은 안 되며 단독 process/축별 상태 설정에 기대고 있다.

5건 seed, unflushed>0 재시도, failed>0/left0 반환은 음성 배달 경우에 강한 oracle다. 하지만 성공 대조군은 브로커 성공 실행이 아니라 AST `left or failed`/대입식/keyword 존재 검사다. 실제 ACK·consume 결과·exactly-once를 증명하지 않는다. 173–178의 fail-open 검사에는 `i < 0`이면 통과하는 분기가 있어 caller 삭제를 이 축만으로 막지 못한다(형제 co_names 축이 일부 보완). SUT watermark는 ledger path만 key로 사용하고 topic/bootstrap/토픽 generation·파일 identity를 포함하지 않는다. 따라서 같은 ledger를 다른 topic에 보내기나 topic reset·압축/교체 후 offset 재조정은 미검증이다. 한 묶음 일부 성공 후 전체 보류는 중복 재발행을 허용하며 session 접두 key만으로 event dedup의 정확성을 보장하지 않는다. 순서 보장과 배달 보장은 각각 남는다.

## Zeus 대응과 종료 경계

이 파티션은 SDD 8단계 각각의 acceptance를 명시하고 실제 fixture/실행/환경/승인 분모를 나누는 검토 방식에 유용하다. 원본 selfimprove는 triage/research/repair/verify/report라는 별도의 5단계이고 REPRO:/CONTROL:/DENOMINATOR:/RERUN:/MUTATION:/RESIDUAL: 문자열 gate가 포함된다. 문자열 존재는 내용의 사실성을 판정하지 않는다고 YAML 자신도 말한다. 따라서 이 pipeline과 contract 시험 개수로 사용자의 8단계 설계·요구 인수·실제 경험·모델 자격을 완료 처리할 수 없다. Zeus의 구체적 8단계 구현 전수는 이번 범위에서 새로 읽지 않았다.

원본은 Git JSONL runtime 원장과 Kafka/PG projection 방향을 명시한다(config/profile 및 bus_tailer). Zeus는 Git 정의/PG runtime 권위이므로 원본 방향을 그대로 흡수하면 SSOT가 역전된다. 후보·위임·cycle·실행 generation·artifact hash·승인/만료·배달 receipt를 PG의 명시 상태로 옮기는 적응 설계가 필요하다. 이는 제안이며 구현·흡수 승인·현재 동작 등가를 의미하지 않는다.

전체 호출·설정·시험 폐쇄, 원본 실행, 외부 설계 원문 대조, 라이선스와 dependency closure, actual Claude 공동 판정, Windows/Linux/WSL 실행, 실제 사람 경험 인수·모델 자격·채택은 미완료다. 역사 주장의 실측 수치를 재현하지 않았으며 실제 운영 키/브로커/라이브 원장을 열어 사실성을 확인하지 않았다. 지원 문서/코드는 원장에 명시한 구간을 넘겨 reviewed로 세지 않았다.
## supporting

지원 원문 29개는 supporting.json의 SHA-256, Git blob, 정확한 줄 구간으로 결속한다. s01–s03은 격리와 시험 집계, s04는 상태 및 acceptance fold, s05–s06은 버스 배달과 드라이버 호출, s07–s10은 arming·승인·신선도, s11–s14는 pipeline·ontology·등급 판정, s15–s16은 실제 freshness 호출과 원장, s17–s19는 board 및 boundary corpus, s20–s24는 큐 생산자·토픽 선언·프로필, s25–s29는 arming 규칙·쓰기 경계·준비 단계 선택·selfimprove 파이프라인이다. files.json의 supporting_ids가 파일별 연결을 지정한다. 전문과 부분 구간을 구분하며 지원 파일을 primary 수에 더하지 않는다. 검색 결과만 본 파일은 이 목록에 포함하지 않았다. 프로필의 로컬 연결 설정은 원문의 환경 의존성으로만 판단했으며 현재 연결 성공이나 자격 증거가 아니다.
