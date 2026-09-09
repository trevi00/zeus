# 실행기 002 독립 정적 검토

원본 16개 전문을 읽었으며 실행은 0회다. 아래는 코드에서 확인한 조건과 정적 위험 분석이다. 주석의 과거 실측·PASS·뮤테이션 결과는 당시 작성자의 주장으로만 다루며 이번 재현 결과가 아니다. supporting.json의 구간 밖은 미검증이다.

## ontology_index.py

원본 `scripts/engine/ontology_index.py` 전체 1–288행. SHA256 `b0270420b01efe00615a10c479067e450ba9163b09b562b2c04c08b75997c2d6`.

온톨로지 검색용 그래프를 생성한다. frontmatter와 파이프라인에서 노드·엣지를 만들며 코드 노드는 AST가 아니라 .py 파일 단위다. build(home)의 일부 경로는 전역 HOME을 사용해 서로 다른 루트가 섞일 수 있다. 작성자 user와 design 평면 등 기본값은 실제 작성·검증 증거가 아니다. 파이프라인 로드 예외를 삼켜 누락을 감추며 같은 산출물의 첫 타입이 유지된다. 노드와 엣지를 각각 원자적으로 기록해도 그래프 전체가 한 트랜잭션은 아니다.

ontology CLI는 인덱스를 쓴 뒤 validator를 실행한다. ontology 테스트 49–53행은 카드 전량을 설명하지만 실제 단언은 >= 15이며 계산한 카드 수를 비교하지 않는다. SHA 결속, 중복 ID, 누락 오류, 그래프 세대 일치가 남는다.

실제 읽은 연결: `config/paths.yaml`, `scripts/cli/ontology_cmd.py`, `tests/contract/test_ontology_smoke.py`. 구간·해시는 supporting.json에 있다.

판정: 전문 의미 검토 완료, 호출·시험 전체 추적과 실행은 미완료. 채택 승인 없음.

## pipeline_loader.py

원본 `scripts/engine/pipeline_loader.py` 전체 1–467행. SHA256 `8731d0d2325e1cc293269a27f8e21eeb58ed8555cacecab130c27460a2ea601c`.

YAML을 단계·의존·게이트·피드백 계약으로 변환한다. 단계 ID 중복은 거부하지만 YAML 중복 키와 같은 산출물의 복수 생산자는 같은 수준으로 거부하지 않는다. 문자열/정규식 게이트 경로는 구조화 게이트의 검증을 모두 거치지 않는다. 비어 있는 단계·게이트와 타입별 인수, 피드백 재시도 및 예산 범위는 별도 엄격한 스키마가 필요하다. 의존 state와 dispatcher model 문자열은 실행 의미·모델 자격을 보증하지 않는다. pipeline SHA16에는 lexicon·catalog·config 변경이 결속되지 않는다.

engine smoke의 machine 실행부 존재 단언과 미니 파이프라인 호출을 읽었다. 전체 설정 조합, 알 수 없는 상태, 빈 단계, 중복 출력, 의미 변경 및 모델 자격 음성 테스트는 미추적이다.

실제 읽은 연결: `scripts/engine/gate_runner.py`, `tests/integration/test_engine_smoke.py`. 구간·해시는 supporting.json에 있다.

판정: 전문 의미 검토 완료, 호출·시험 전체 추적과 실행은 미완료. 채택 승인 없음.

## pollution.py

원본 `scripts/engine/pollution.py` 전체 1–121행. SHA256 `9b7dd3b7ce55e9faec1a78a3d61afd965951ced3640050edbac5921e6c743b2e`.

짧은 시간 버킷의 이벤트 수와 writer 접두어·seed 흔적으로 오염 후보를 분류한다. 빠른 정상 실행과 제거된 live 흔적은 오탐, 허용 writer 표식은 미탐 가능성이 있다. detect가 호출하는 params.get은 fallback 마커 생성·삭제를 할 수 있어 전체 호출이 순수 읽기는 아니다. retract는 전달된 ID와 이유로 철회 이벤트를 쓰며 탐지 증거·권한·버전 결속을 자체 강제하지 않는다. 기록한 버킷 상수와 동적으로 읽은 실제 파라미터가 다를 수 있다.

pollution CLI의 --execute 분기와 smoke의 합성 이벤트 구간을 읽었다. 실제 역사적 오염 확정·철회 정당성은 확인하지 않았다. PG에는 원문 이벤트와 인증된 철회 근거를 함께 보존해야 한다.

실제 읽은 연결: `scripts/cli/pollution_cmd.py`, `tests/integration/test_pollution_smoke.py`, `scripts/lib/params.py`. 구간·해시는 supporting.json에 있다.

판정: 전문 의미 검토 완료, 호출·시험 전체 추적과 실행은 미완료. 채택 승인 없음.

## pr4.py

원본 `scripts/engine/pr4.py` 전체 1–224행. SHA256 `1faa167746d59086af48ab3125c9d2fca4c44384f4c7aa0218a8790fe3d37405`.

validator 정책은 JSON, 승급 실험은 JSONL, 변경 감사는 다른 기록으로 나뉜다. sweep은 명령 인수를 각각 HOME과 결합하며 파일별 300초 제한을 두지만 출력은 전체 수집한다. 손상된 JSONL 행을 건너뛰므로 실패 기록 손실이 항상 보수적이지 않다. ack는 특정 판정 ID보다 pending 수에 결합하고 validator 버전별 streak가 아니다. graduate는 정책 저장 후 감사를 쓰므로 원자적 승격이 아니며 demote와 tune도 별도의 인증·승인 경계가 필요하다.

현재 읽은 policy의 advisory 대상 pattern_decisions에는 cmd가 없다. 대상 0 또는 실행 0을 건강한 canary로 볼 수 없다. ladder CLI와 합성 smoke 일부만 추적했다. canary의 후보·시험 버전 결속, 권한 및 동시 승급은 남는다.

실제 읽은 연결: `config/policy/validator-ladder.json`, `scripts/cli/ladder_cmd.py`, `tests/integration/test_ladder_smoke.py`. 구간·해시는 supporting.json에 있다.

판정: 전문 의미 검토 완료, 호출·시험 전체 추적과 실행은 미완료. 채택 승인 없음.

## projection_pg.py

원본 `scripts/engine/projection_pg.py` 전체 1–67행. SHA256 `121dbbe308159d3663c4e2ddebce514b68611bd43eddd25f735a680d88ea7b42`.

문서와 구현의 PG는 원장 투영이다. 관측된 단계가 모두 DONE이면 done을 추론할 수 있어 필요한 전체 단계가 원장에 나타났다는 분모가 없다. fleet CLI는 명시적 done을 전달하지 않는다. run 이름을 upsert하고 단계를 삭제·재삽입하지만 source revision/CAS를 보지 않아 오래된 투영의 덮어쓰기를 막지 않는다. summary에도 DDL이 있어 이름만으로 읽기 전용이라 할 수 없다.

fleet 테스트의 일부는 localhost Kafka와 PG를 사용하고 시험 접두어 데이터를 지운다. 본 작업에서는 실행하지 않았다. Zeus의 PG runtime SSOT와 방향이 반대여서 이 테이블을 그대로 권위 있는 runtime으로 승격할 수 없다.

실제 읽은 연결: `config/profile.yaml`, `scripts/cli/fleet_status_cmd.py`, `tests/integration/test_fleet_smoke.py`. 구간·해시는 supporting.json에 있다.

판정: 전문 의미 검토 완료, 호출·시험 전체 추적과 실행은 미완료. 채택 승인 없음.

## recall.py

원본 `scripts/engine/recall.py` 전체 1–147행. SHA256 `35ced88a586c08e3979d5ec5ae1c0a86e3916553bc0cea3721e9c8a2b6b937c0`.

SQLite FTS5 trigram 인덱스에 세션·지식의 잘린 본문을 저장한다. mtime/size 갱신은 내용 SHA가 아니며 삭제된 파일을 인덱스에서 제거하지 않는다. 전체 파일을 먼저 읽기 때문에 저장 2,000자 제한이 메모리 제한은 아니다. 검색 결과의 basename은 전체 경로·세션·원문 해시를 충분히 보존하지 않는다. 검색도 DB 생성·DDL 부작용을 가질 수 있다.

recall CLI는 external_text 경계를 붙이지만 검색 결과의 사실성과 권한을 인증하지 않는다. recall smoke의 검색 단언 일부만 읽었다. 삭제·변경·동명이인 문서·오래된 경험 철회 및 prompt 출처 결속은 남는다.

실제 읽은 연결: `scripts/cli/recall_cmd.py`, `tests/unit/test_recall_smoke.py`. 구간·해시는 supporting.json에 있다.

판정: 전문 의미 검토 완료, 호출·시험 전체 추적과 실행은 미완료. 채택 승인 없음.

## reflect.py

원본 `scripts/engine/reflect.py` 전체 1–73행. SHA256 `c1f4f56fb465133a5e3d57a249855d8c0c815e10351348a406a15bf2b2b31459`.

미해소 반복 실패 또는 anomaly를 결정론적으로 요약하여 proposed 메모를 쓴다. 반복 횟수는 독립 실행 증거 수와 같지 않다. stage/statement 참조만으로 원문 이벤트와 run 버전을 봉인하지 않는다. missing ledger도 신호 없음으로 끝날 수 있다. 이것은 검증된 교훈 생성이나 자동 승격이 아니다.

reflector_fork는 해소된 조사 tier도 fork 신호로 삼지만 본체 digest는 미해소 반복 실패만 받는다. fork 성공 직후 완료 이전 watermark를 올리고 전역 event 수를 사용하므로 무신호·실패·다른 원장·압축 경계를 재검토해야 한다. 본체를 검증하는 테스트 전문은 이 범위에서 추적하지 못했다.

실제 읽은 연결: `scripts/handlers/stop/reflector_fork.py`. 구간·해시는 supporting.json에 있다.

판정: 전문 의미 검토 완료, 호출·시험 전체 추적과 실행은 미완료. 채택 승인 없음.

## reverse.py

원본 `scripts/engine/reverse.py` 전체 1–263행. SHA256 `0b3f0c9e9512a071c89d83005857d5a1a2f85501e0f68aeea6599f6cbb5c0f55`.

언어별 추출기를 호출해 문서를 쓰고 같은 추출기로 verify한다. HEAD 앞 12자는 dirty/untracked 입력의 해시가 아니다. language_profile의 파일 수 비율은 의미 추출 커버리지가 아니며 디렉터리 제외는 프로젝트 상위 경로의 이름에도 영향을 받을 수 있다. origin이 명시된 비추출 문서는 보호하지만 origin 없는 기존 문서는 덮어쓸 수 있다. 추출 None은 verify에서 비교하지 않아 공허한 성공 가능성을 남긴다. 고정 confidence 0.9는 실측 정확도가 아니다.

reverse smoke 1–100행의 Python 합성 fixture와 API/엔티티 단언을 읽었다. 개별 추출기 구현은 읽지 않았으므로 언어별 구현 등가를 주장하지 않는다. 인간 의도·인수 조건을 코드에서 발명하지 않는 방향만 후보로 남긴다.

실제 읽은 연결: `tests/unit/test_reverse_smoke.py`. 구간·해시는 supporting.json에 있다.

판정: 전문 의미 검토 완료, 호출·시험 전체 추적과 실행은 미완료. 채택 승인 없음.

## rlm_kernel.py

원본 `scripts/engine/rlm_kernel.py` 전체 1–237행. SHA256 `6281f0f50d05f8a63dd1928340595d3ac11af05587e64c33054f9eb3fb0634ae`.

import 시 특정 이름의 환경변수를 삭제하고 파일 검색·chunk·Python eval/exec를 MCP stdio로 노출한다. 이름 기반 비밀 제거는 파일·프로세스·네트워크 격리가 아니다. eval/exec는 현재 프로세스 권한을 사용하며 실행 시간·메모리 상한이 없다. 입력 전체 적재, 정규식 검색, 출력 수집 이후 절단도 자원 사용 상한을 보장하지 않는다. chunk 목적지·Python 코드·schema 인수의 실제 경계 검증이 부족하다.

MCP config와 Bash launcher 및 직접 stdio smoke 일부를 읽었다. smoke는 가짜 KEY/TOKEN 제거를 검사하며 실제 MCP 등록, 네트워크 차단, credential 파일 격리나 OS 자격 시험은 아니다. 이 원본을 import하거나 실행하지 않았다.

실제 읽은 연결: `.mcp.json`, `scripts/handlers/rlm_launcher.sh`, `tests/integration/test_rlm_smoke.py`. 구간·해시는 supporting.json에 있다.

판정: 전문 의미 검토 완료, 호출·시험 전체 추적과 실행은 미완료. 채택 승인 없음.

## sandbox.py

원본 `scripts/engine/sandbox.py` 전체 1–551행. SHA256 `546fef7acd39664d6b73eae74688cd824ef005da59e679939c4e3d1e3b2c5a9f`.

HEAD worktree에서 패치를 적용하고 시험 파일을 실행한 뒤 패치·보고서를 보관하고 승격한다. worktree와 환경 복사는 프로세스·네트워크 격리가 아니다. dirty 조회는 -uno로 untracked를 제외하고 정책 부재는 약한 기본 정책이 된다. 파일별 600초 제한은 총예산·자손 프로세스·출력 메모리·실제 단언 수를 보증하지 않는다. 처음 실패와 세 차례 재실행 실패의 교집합을 쓰므로 주석의 한 번이라도 다시 붉으면 거부와 실제 조건이 다르다. 혼합 결과는 deferred이며 검증 성공이 아니다.

reconfirm 계약 테스트는 교집합 계산을 재작성하거나 AST를 검사하며 실제 전체 worktree 흐름을 입증하지 않는다. CLI 승인에서 driver stamp와 human 문자열이 보이지만 인증된 사람 인수로 승격할 수 없다. 보관 패치·기준 HEAD·시험 분모·승인 이벤트의 해시 결속 및 원자적 적용이 없다. 과거 보안 차단 probe는 재시도하지 않았고 현재 결함 재현도 없다.

실제 읽은 연결: `scripts/cli/sandbox_cmd.py`, `tests/contract/test_entrance_reconfirm_contract.py`. 구간·해시는 supporting.json에 있다.

판정: 전문 의미 검토 완료, 호출·시험 전체 추적과 실행은 미완료. 채택 승인 없음.

## select_ready.py

원본 `scripts/engine/select_ready.py` 전체 1–99행. SHA256 `97a8ceb28f55ee4d239c0b236eca569db7a285c9cd6aed1822b4619b7cf2dcb2`.

완료 fold, 단계 의존, premise 존재와 optional 선택으로 다음 단계를 고른다. 산출물 파일 존재만으로 완료하지 않는 점은 유효하다. 반면 SKIPPED는 is_done에서 끝난 단계이지만 downstream completed에는 들지 않아 계약에 따라 막힐 수 있다. running 의존은 별도 probe가 필요하나 tick은 이를 전달하지 않는다. 빈 단계 또는 선택되지 않은 optional만 있는 경우의 done은 사용자 인수가 아니다.

engine smoke 240–253행은 PASS 제거와 복원, 파일 존재를 비교하는 의미 있는 차단 방향 단언이다. 실행하지 않았다. 동시 claim/중복 dispatch, run/cycle identity, running probe와 skip 전파는 추가 추적·시험이 필요하다.

실제 읽은 연결: `tests/integration/test_engine_smoke.py`. 구간·해시는 supporting.json에 있다.

판정: 전문 의미 검토 완료, 호출·시험 전체 추적과 실행은 미완료. 채택 승인 없음.

## skill_router.py

원본 `scripts/engine/skill_router.py` 전체 1–397행. SHA256 `8ddc0a6a20ede4207905acd5a5ad6fb86edf8c5a5947824d3d353e0f604b1ee9`.

스택·키워드·명시 스킬 점수로 본문과 lesson을 번들링한다. 루트 marker 발견 시 하위 스택 스캔이 생략되어 혼합 스택을 놓칠 수 있다. lesson trust는 문자열 형태에 민감하고 스킬 본문 provenance·lifecycle·권한을 인증하지 않는다. 점수·예약 순서 때문에 공통→특화 설명이 모든 입력에서 보장되지 않는다. budget 계산에는 최종 헤더·구분자 비용이 모두 포함되지 않는다.

router smoke는 대표 조합과 r_small.chars <= 600을 검사하지만 최종 bundle 길이 자체 단언은 읽은 구간에 없다. telemetry는 배달·관측이며 소비 성공이나 인과 효과가 아니다. stage 이름만으로 과거 판정을 연결하는 효과 집계와 경험 승격을 분리해야 한다.

실제 읽은 연결: `config/retriever.yaml`, `scripts/cli/step_cmd.py`, `tests/unit/test_router_smoke.py`. 구간·해시는 supporting.json에 있다.

판정: 전문 의미 검토 완료, 호출·시험 전체 추적과 실행은 미완료. 채택 승인 없음.

## staleness.py

원본 `scripts/engine/staleness.py` 전체 1–46행. SHA256 `b3ea2f71bc30b3617e6d7ec3ad9e7c29fdf863461900f854f20b8fbc13e9c501`.

완료 단계의 기록 전제와 현재 값을 비교해 재게이트를 권한다. 기록 조회는 raw 최신 verdict를 읽고 완료 fold와 같은 철회·cycle 의미가 보장되지 않는다. preconditions.changed는 이전 기록이 없으면 차이 없음으로 처리하며 unknown 문법도 동일 sentinel이면 계속 같을 수 있다. tick은 scan 오류를 삼키고 재게이트를 예산 검사보다 먼저 반환한다.

preconditions 본체 전문과 변경→STALE→재판정 smoke 일부를 읽었다. 부분 fixture가 과거 실제 미디어 환경을 재현했다는 증거는 아니다. PG에서는 전제 미상·변경을 명시 상태로 보존하고 재검증도 동일 총예산에 들어가야 한다.

실제 읽은 연결: `scripts/lib/preconditions.py`, `tests/integration/test_preconditions_smoke.py`. 구간·해시는 supporting.json에 있다.

판정: 전문 의미 검토 완료, 호출·시험 전체 추적과 실행은 미완료. 채택 승인 없음.

## testgen.py

원본 `scripts/engine/testgen.py` 전체 1–70행. SHA256 `c2b7c3a6a902bd6297e47904d65032a940a8a4b21a0eab659a2570af517d5344`.

GWT 문장을 추출해 xfail(strict=False) 및 NotImplementedError 골격을 생성한다. 이것은 행동 oracle을 구현하지 않으며 전체 AC 의미나 실패 경계를 검증하지 않는다. 입력을 Python 삼중 따옴표 docstring에 안전한 리터럴 인코딩 없이 삽입하므로 특수 입력에서 잘못된 코드가 나올 가능성이 있다. 파일 출력은 기존 테스트를 덮어쓸 수 있다.

testgen CLI와 small_batch 738–752행은 개수·문자열·결정론을 검사한다. xfail 골격만으로 테스트 프로세스가 성공 종료할 수 있으므로 구현 전 green 금지라는 설명을 기계적으로 달성하지 않는다. 생성 코드 실행·입력 공격 재현은 하지 않았다.

실제 읽은 연결: `scripts/cli/testgen_cmd.py`, `tests/integration/test_small_batch_smoke.py`. 구간·해시는 supporting.json에 있다.

판정: 전문 의미 검토 완료, 호출·시험 전체 추적과 실행은 미완료. 채택 승인 없음.

## tick.py

원본 `scripts/engine/tick.py` 전체 1–379행. SHA256 `108a2f93e5a85a98d67cbb0dfeefde2b3f38f6f29e7a6a8e6e9620b2fc07506d`.

원장·파이프라인·현재 파일·시각을 읽고 지시를 반환한다. 순수 원장 함수라는 설명보다 실제 의존 범위가 넓고 params 조회 부작용도 고려해야 한다. staleness와 ratchet 오류는 fail-open이며 stale 재지시는 TTL·iteration·delegation cap보다 앞선다. 외부 판정 대기는 None만 검사하지만 gate_runner는 PARTIAL도 pending으로 유지해 같은 상태를 다르게 다룬다. tick의 피드백 재시도 집계 경계와 gate_runner의 전체 역사 집계가 다르다.

reenforce, l2_driver, engine smoke의 호출을 읽었다. tick의 directive model 문자열은 실제 spawn·자격 인증이 아니다. 예외를 halt JSON으로 돌려도 CLI rc0일 수 있어 caller의 outcome 해석이 필요하다. run/cycle/재개방·PARTIAL·예산·동시 claim 교차 상태는 아직 실행 검증되지 않았다.

실제 읽은 연결: `scripts/cron/l2_driver.py`, `scripts/handlers/stop/reenforce.py`, `scripts/engine/gate_runner.py`, `tests/integration/test_engine_smoke.py`, `scripts/lib/params.py`. 구간·해시는 supporting.json에 있다.

판정: 전문 의미 검토 완료, 호출·시험 전체 추적과 실행은 미완료. 채택 승인 없음.

## workup.py

원본 `scripts/engine/workup.py` 전체 1–225행. SHA256 `7e6135654797e2f50fec23cc152255f4b9d5ddddfc81a157c34dfdc90c83b867`.

트리·언어·추출 결과를 모아 역분석 산문 골격과 재추출 digest를 검사한다. 폴더 표시 cap은 재귀 계산 비용 상한이 아니다. Java 검사 결과를 문서에 담는 것과 프로젝트 인수 실패 처리는 다르다. Python reverse 존재가 workup의 Python 지원으로 연결되지 않고 TS 지원 설명도 registry와 범위 차이가 있다. semantic 블록 여섯 개의 존재는 내용의 참·충분성을 보장하지 않는다.

workup CLI와 smoke 일부는 일반 근거 산문으로 구조 검사를 통과시키며 외부 프로젝트 경로가 없으면 조건부 skip한다. 해당 외부 프로젝트를 열거나 실행하지 않았다. 입력 repo hash·사람 분석·8단계 SDD 인수 증거를 별도로 연결해야 한다.

실제 읽은 연결: `scripts/cli/workup_cmd.py`, `tests/unit/test_workup_smoke.py`. 구간·해시는 supporting.json에 있다.

판정: 전문 의미 검토 완료, 호출·시험 전체 추적과 실행은 미완료. 채택 승인 없음.
