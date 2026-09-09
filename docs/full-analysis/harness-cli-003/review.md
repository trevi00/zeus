# harness CLI 003 독립 정적 검토

대상은 `harness:scripts/cli:003` 18개, 171,177바이트다. 고정 revision은 `a3f8b3be9a0a389329de6e16a6c7db81782041a3`, partition scope SHA256은 `c653c4b6f02f2d7573f86ef4934a2564e8b85021c25eff0413e4b1e99c399516`이다. 모든 대상 본문을 전문으로 읽었다. 지원 파일은 [supporting-evidence.json](supporting-evidence.json)에 적은 구간만 읽었으며 전수 coverage에 합산하지 않는다. 원본 코드·테스트·프로브·설치 실행은 0회다. 과거 차단된 정상 gate-writer ERROR 프로브를 재시도하거나 우회하지 않았다.

아래는 실행 재현 결과가 아니라 코드 경로의 독립 판독이다. 원문 안의 역사적 실측·PASS·권한 선언은 원문 주장으로 취급했다. 기존 방어와 잔여를 함께 적었으며 전체 하네스 분석 완료, 실제 인수 통과, Zeus 채택·구현 등가는 모두 false다. 다른 검토자의 보고서를 근거로 판정을 만들지 않았다. 실제 Claude 교차 검토와 최종 처분은 root가 담당한다.

## C01 — validator 승격의 기본 카나리아 반환형이 맞지 않는다

`ladder_cmd.py:109–114`는 `pr4.graduate(name)`를 부르고 카나리아 PASS라고 출력한다. 실제 기본 경로 `engine/pr4.py:171–177`은 `canary=golden.gate` 다음 `if not canary()`로 검사한다. 그러나 `engine/golden.py:73–76`은 `(bool, report)` 튜플을 반환한다. 따라서 카나리아가 예외 없이 `(False, report)`를 반환하면 이 조건은 거부하지 않는다. 적격성 조건이 충족된 경우의 정적 반환형 불일치이며 실제 정책 변경·재현은 하지 않았다.

`test_ladder_smoke.py:118–122`의 실패/성공 대조는 주입한 `lambda: False/True`를 사용해 기본 함수의 튜플 계약을 밟지 않는다. 검증기 미등재·미판정 FAIL·FP·streak·강화 방향 tune·seed 강등 거부는 존재한다. 현재 정책은 대부분 blocking이며 유일한 advisory `pattern_decisions`는 `cmd:null`로 스윕 제외라고 명시한다. 따라서 현재 사용자 명령이 실제로 잘못 승격됐다고 단정하지 않는다. Zeus에서는 검사 결과의 `passed`를 명시적으로 소비하고 검사 수, 대상 revision, 정책 hash, 검증기 버전과 승격 상태 전이를 묶어야 한다. 이 사다리는 검증기 등급용이며 Astra→Sol→Terra 수행 자격이 아니다.

## C02 — 사람 승인 입력의 문장 범위가 소비자에서 사라진다

`residual_cmd.py`는 pipeline에 있는 stage·statement·mode를 검증하고 operator `gate_check`를 기록한다. 그러나 지원 소비자 `gate_runner._external_verdict:28–49`는 stage와 mode만 비교한다. `_run_gates:100–123`가 각 human/render 문장마다 같은 함수를 부르므로 같은 단계·방식의 최신 판정 한 건이 다른 문장에도 적용된다. `cycle_started.redo`에 따른 승인 철회는 이미 구현되어 있으므로 “이전 사이클 승인을 항상 재사용한다”는 주장은 하지 않는다.

CLI의 PARTIAL은 proxy와 why_human을 남기는 유용한 미종결 표현이다. 반면 PASS에 실제 기기 실행·증거 hash·인증된 사람 신원·산출물 revision을 요구하는 인자는 없다. `fold_residual`은 human의 None/PARTIAL만 표시하므로 FAIL/REJECT는 잔여 목록에서 빠지지만 실제 게이트에서는 실패로 남는다. 잔여 목록의 비어 있음은 완료가 아니다. 읽은 `test_cli_smoke:127–144`는 한 human 문장의 파킹→CLI 기록→PASS 경로이며 다문장 범위·인증된 사람 검수의 증거가 아니다. Zeus QA는 `(ticket revision, spec hash, scenario/statement, build, environment, reviewer authority)`에 판정을 결속해야 한다.

## C03 — sandbox는 파킹·승인·파일 적용을 제공한다

`sandbox_cmd.py`의 apply는 suite floor 확인과 환경 변수 봉인 후 `engine.sandbox.apply_via_sandbox`를 부른다. approve/reject에는 `is_driver_spawned()` 거부가 있고 `write_boundary`에도 사람 명령 휴리스틱이 있다. `promote`를 같은 방식으로 막지 않는 것은 이미 승인된 상태를 소비하는 의도다. 이를 승인 우회라고 곧바로 분류하지 않는다. 읽은 `write_boundary:837–865`는 직접 writer 호출까지 보호하지 못한다는 한계를 스스로 적고 있으며 `is_driver_spawned`는 환경 변수 존재 여부다. 실제 사람 인증·OS 권한 경계가 증명된 것은 아니다.

`engine/sandbox.py:365–376`의 pending ID는 초 단위 시간이며 report에 files/grades/created를 기록한다. 같은 초의 병렬 제안 충돌을 막는 exclusive 생성이나 내용 hash는 이 경로에서 보이지 않는다. `promotion_verdict:399–415`는 pending ID의 최신 proposed/approved/rejected를 소비한다. `promote:497–533`는 승인, patch 존재, 접촉 파일의 dirty 상태를 확인하고 `git apply` 뒤 원장에 promoted와 `bake_s`를 기록한다. 읽은 함수에는 승인한 patch hash/base revision 재결속, 적용 전 스위트 재실행, 실제 bake 대기·관측이 없다. 따라서 “bake 완료”나 서비스 배포 완료라는 증거로 사용할 수 없다. 적용 성공 후 원장 append 실패도 동일 트랜잭션으로 되돌려지지 않는다.

기존 코드가 격리 worktree, baseline과 suite floor, 불안정 실패의 보류, 자동 승격 대신 제안 파킹을 갖춘 점은 보존 후보다. worktree는 완전한 OS 샌드박스와 같지 않으며 `run_suites` 원문도 venv 완전 분리를 잔여로 적는다. Zeus는 내용 주소 patch/정책/검사 영수증, 승인 actor, PG 트랜잭션·재시도 식별자, 실제 적용·서비스 검증·rollback 단계를 별도로 결속해야 한다. 이 작업에서는 어떤 패치도 생성·적용·삭제하지 않았다.

## C04 — run의 장전·해제는 완료 선언이 아니다

`run_cmd.arm`은 기존 project 확인, pipeline build, optional ID 확인, guardian binding 타입 계약을 거친다. `pipeline_started`와 optional `stage_skipped`를 원장에 쓴 뒤 active_run을 원자 교체한다. 여러 파일/이벤트를 하나의 트랜잭션으로 묶는 경로가 아니며 활성 binding 교체를 잠그는 lease/CAS가 CLI 본문에 없다. optional 선택은 ID 존재만 확인한다. 공백·중복·선택 가능한 optional 여부의 폐쇄 계약은 남는다.

`armed_by`는 pipeline_started에 쓰지만 binding에는 넣지 않는다(`run:111–139`). disarm은 binding의 armed_by를 읽으므로 이 writer만 통한 장전의 귀속이 해제 payload에 복사되지 않는다. `derive_stage_states`는 pipeline_started로 전체 상태를 초기화하지 않고 실제 처음 관측한 stage 순서로 dict를 만든다. 따라서 disarm의 “파이프라인 순서” 설명과 통산 DONE 개수를 새 실행의 성과로 읽는 해석에는 주의가 필요하다. 별도 `cycle_started.redo`가 상태 재개방을 담당한다.

disarm은 기록 후 삭제하며 기계 `strict=True`는 기록 실패 시 binding 유지, 일반 CLI는 긴급 해제를 우선하는 비대칭이 있다. 실제 caller `l2_driver._auto_disarm:673–713`은 strict를 사용한다. 읽고 기록하고 unlink하기 사이에 다른 장전이 생기는 경쟁은 이 CLI에 CAS가 없다. 상태 출력이 파일과 원장 양쪽을 보더라도 project/pipeline/hash 동일성을 모두 증명하지 않는다. 프로세스 종료, lease 폐기, 배포 검증으로 간주할 수 없다. Zeus PG runtime SSOT에서 장전 generation, expected sequence, 현재 ticket/candidate, 실제 실행 상태를 별도 계약으로 가져와야 한다.

## C05 — 심판의 advisory 평결과 축별 기록을 분리해야 한다

`judge_cmd.py`는 기본 Codex 심판과 등록 pool을 사용하고 각 멤버에게 순차 요청한다. pool 중복·생성자 계보 방어, 결정론 gate 우선, 멤버별 인용 가드, 축 값의 issues, 응답 수 축소·사실상 1인·이견 표시가 존재한다. quorum은 배포 승인이 아니며 NO_VERDICT·부정 평결도 advisory 종료 0이다. 기계 gate 자동 경로는 하네스 lint이며 `--gates pass`는 호출자의 주장 입력이다. 실제 산출물/실기기 테스트 결과와 동일시하면 안 된다.

`record:149–157`의 `{**meta, **r}`에서 `AxisScore.as_row`의 verdict가 메타의 guarded verdict를 덮는다. 축 verdict와 심판 최종 verdict가 별개라는 점을 reader가 알아야 하지만 동일 키명이라 가드 강등 전 approved 축이 `guard!=none`과 함께 남을 수 있다. quorum 행은 별도로 올바른 집계값을 남기므로 모든 평결 기록이 잘못됐다고 말하지 않는다. `ontology_match=bool(parsed.get(...))`는 문자열 `"false"`도 true로 취급한다. `_read`는 존재하지 않는 경로를 인라인 본문으로 취급하여 경로 오타를 구분하지 않는다. 전원 부재는 quorum 행을 쓰기 전에 return하며 raw reply·rubric/artifact 내용 hash가 이 기록에 없다.

지원 provider는 stdin 전달, 환경 allowlist, read-only 기본, Windows CMD shim 처리, timeout을 갖춘다. 현재 제품의 지원 모델/권한 안전성을 이 오래된 코드만으로 추천하지 않는다. 요청마다 timeout이 있어도 전체 pool 비용·토큰 상한·수행 자격은 별도다. fenced data와 봉투 정규식은 유용한 데이터 구분이나 실행 환경의 모든 문맥 격리를 증명하지 않는다. 읽은 jury smoke는 가짜 provider 응답을 주입하는 계약 시험이다. 실제 Claude/Codex 교차 실행이나 인수로 세지 않는다.

## C06 — invariant·golden·probe가 측정하는 것의 범위

`invariants_cmd.report`의 declared/used/tested는 텍스트 분석이다. 자기 계측 파일 쌍 제외, clause 전부 AND, 대상 목록 결속, 설계 레포 부재 deferred는 의미 있는 방어다. 그러나 LABEL_RE는 AST call 해석이 아니라 한 줄의 `check(` 이후를 읽으며 주석/문자열·다중 행 경계가 남는다. `_canon_targets`의 첫 등장 정본 선택은 경로 정렬 순서에 의존하고 읽기 오류는 건너뛴다. report 종료 0은 불변식 이행 승인이 아니다.

`bite`는 함수 구역 표기와 mutation 결과를 결합하며 cap과 변이 0인 구역을 화면에 판정 불능으로 표시한다. 하지만 이런 구역은 holes를 늘리지 않아 다른 생존 변이가 없으면 종료 0이다. 또한 함수 구역/변이 재열거는 작업 트리 본문이고 mutation의 실제 실행은 HEAD worktree다. 미커밋 변경이 있는 경우 line 귀속이 다른 내용일 수 있다. mutation이 기준선 적색을 오류로 막는 현행 방어는 확인했다. 역사적 baseline 거짓 만점을 현행 결함으로 재분류하지 않는다.

`quality golden`의 underlying golden은 케이스 0을 허용한다. `quality mutation`은 floor 미달과 판정 오류를 실제 비영 종료로 내므로 “언제나 advisory 0”이라는 옛 docstring을 현재 행동으로 읽지 않는다. `probe live`는 실제 project의 첫 주입 가능한 output을 backup→쓰기→gate→복원→재검사하는 변이 작업이며 읽기 명령이 아니다. 기준선/복원 PASS 확인은 있다. `counterfactual:100–105`는 주입 후 모든 non-PASS를 live로 묶으므로 ERROR도 검출력으로 집계될 수 있다. 이는 정적 분기 분석만 했고 금지된 프로브를 실행하지 않았다. BLINDSPOTS 제목·bullet 존재는 여집합 선언이며 실제 누락 시나리오 검증이 아니다.

## C07 — prompt 반복 분석과 폐기의 증거 수명

`prompts_cmd`는 SQLite의 stat/analyze, 수동 prune, weekly rollup 표면이다. stat/select도 DB와 스키마가 없으면 생성한다. 반복 군집은 문자열 유사도이며 자동 수리의 성공·재발 방지나 토큰 효율을 증명하지 않는다. analyze의 `--json --write`는 JSON 뒤 저장 안내를 출력한다. prune은 기본 dry-run과 `--yes`를 갖추지만 음수 days 방어·요약 필수 계약이 본문에 없고 delete commit 후 VACUUM 실패는 부분 완료다.

rollup은 요약을 먼저 쓰고 폐기하는 방어가 있다. 그러나 `prompt_rollup:130`에서 읽은 행 ID 집합 대신 `:172`에서 cutoff 쿼리를 다시 사용하여, 사이에 같은 cutoff 이전 timestamp의 행이 들어오면 요약되지 않은 행도 삭제될 수 있다. 주석의 “한 번 뽑아 둘 다에 사용”과 구현은 다르다. 완료 판정은 digest 파일명 존재이며 첫 요약 쓰기 후 실패·손상·동시 실행·같은 주 --force 덮어쓰기의 상태를 분리하지 않는다. 이 위험을 실제로 만들지 않았다. 읽은 rollup smoke는 쓰기 실패 전 폐기 0과 단일 실행 보존 기간을 시험한다. Zeus는 원문 보존 정책, 요약에 포함한 정확한 ID/hash, 폐기 트랜잭션·실패 영수증, CS 재발 이슈와 결속해야 한다.

## C08 — recall·mirror·ontology의 조회/완료 의미

`recall index`는 transcript/지식 FTS 인덱스를 생성·갱신한다. `recall.search`도 연결 시 DB 생성 경로이며 NO_HIT은 미색인·진짜 미일치·삭제된 원문 여부를 구분하지 못한다. engine은 mtime/size 증분 판단, 파일별 delete+insert를 하지만 삭제된 파일 목록의 purge는 읽은 루프에 없다. top 음수·상한 방어는 CLI에 없다. 인용 경로와 원문 freshness 확인을 별도로 요구해야 한다. snippet 외부 텍스트 검사는 전체 원문 신뢰나 학습 승인이 아니다.

`mirror gate`는 매번 index와 coverage 파일을 쓰며 wiki 0개는 ready를 막는다. 앵커 orphan·근거 없는 문단·없는 대상도 분리한다. 다만 ready_for_kickoff는 해당 규칙의 온보딩 표현이고 path:line은 파일만 확인하여 line 유효성/주장 진위를 검증하지 않는다. 이것이 사용자 핵심 시나리오의 전문 분석이나 배포 준비 증거가 될 수 없다.

`ontology index`는 build 후 validator를 subprocess로 부르고 return code를 전달한다. build는 nodes/edges를 개별 원자 쓰기하나 세대 전체를 하나로 교체하지 않으며 후속 검증 실패 시 이미 생성된 파일이 남는다. query/edges는 없으면 빈 결과로 종료 0이고 손상 JSON은 포괄 상태 변환이 없다. 조회 조건의 폐쇄 어휘와 freshness/검증 완료 generation 연결은 본문에 없다. 기존 ontology validator의 모든 규칙·호출체인은 이번 bounded 지원 범위 밖이다.

## C09 — 역할 전달·스킬 라우팅·모델 자격은 서로 다르다

`roster_cmd`는 카드 전문과 model_tier/risk_scope/tool_slices 설명을 제공한다. 문자열 callsite 숫자를 실제 호출로 오인하지 않도록 경고하고 dispatch의 자기보고/기계배정을 따로 낸다. 읽은 `_delivery_index`는 모든 ledger JSONL을 합산하여 복사본 중복, 손상 행 스킵, `role_source` 누락/미지 값의 staged 분류가 남는다. JSON consumer는 각주 의미를 별도 처리해야 한다. 스크립트에서 roster의 as_prompt를 부르는 곳은 이 CLI 자체이며 실제 step은 카드를 별도로 읽고 cap으로 자른다(`step_cmd:198–212,457`). 카드 전문 명령이 있다는 사실만으로 모든 실제 dispatch가 같은 계약 전문을 받는다고 세지 않는다.

`skills_cmd`는 frontmatter 계약·중복·용어·corpus 검사를 수행하고 검사 수 0을 거부한다. frontmatter 없는 파일을 별도 표시하는 것은 유용하다. 그러나 `--json` 이후 PASS/FAIL 텍스트가 붙는 본문이 있어 단일 JSON 소비 계약과 다르다. 스킬 내용의 실제 준수·배포 성공·모델 수행 자격을 측정하지 않는다.

`skill_eval_cmd`는 자기 trigger를 구성한 synthetic stage, 선언 해소, 조각 targeting, 실제 stack marker별 라우팅을 비교한다. 알려진 결함 목록의 신규/고정/고아 검출, 자기스택 배달 분모, 순수 JSON 출력은 존재한다. 하지만 import 전에 기존 HARNESS_STATE_DIR가 있으면 존중하므로 그것이 live 경로인 호출에서는 반복 route의 `_record_usage`가 live telemetry에 쓸 수 있다. 임시 변수를 만들었을 때 main finally는 directory를 삭제하지만 환경 값을 되돌리지 않는다. `_all_stages`는 SystemExit만 처리하는데 실제 `PipelineBuildError`는 ValueError다. 빈 평가의 rate/precision None은 human 출력 format에서 예외가 날 수 있다.

`quality skills`는 전체 usage와 gate_verdict를 stage 문자열로 결합한 상관이며 시간·프로젝트·cycle 혼합이 가능하다는 engine 설명이 있다. 효과 결과가 비면 먼저 return하여 전부 NO_HIT인 telemetry의 후속 NO_HIT 분석은 보이지 않는다. 스킬 번들의 예산은 config의 문자 수이며 토큰 실측/수행 결과/모델 자격이 아니다. 실제 step은 누락·전량 예산 절단·stack 탈락을 출력하지만 라우팅 예외는 fail-open으로 dispatch를 유지한다. 핵심 금전 시나리오의 필수 규칙 전달 누락은 Zeus에서는 별도 blocking 후보로 논의해야 한다.

## C10 — scaffold·safety 및 환경·배포 경계

`scaffold_cmd`는 common과 stack 템플릿 우선순위를 적용하고 등록된 type을 발급하며 기존 파일을 거부한다. 알 수 없는 stack은 공통으로 폴백한다. stack의 root 내부 containment 검증은 본문에 없고 exists→write의 동시성 창이 있다. 산출물 placeholder 치환은 SDD 초안 발급이지 요구사항 승인·사용자 경험 테스트가 아니다. 이번 범위에는 템플릿 전문 재검토를 더하지 않았고 읽은 scaffold smoke의 격리 파일 발급/덮어쓰기 거부만 확인했다.

`safety_cmd`는 hook journal의 기간 필터와 분모를 낸다. underlying reader는 손상 JSON을 조용히 제외하고, 요약은 synthetic 제외와 빈 분모 None을 구분한다. ask+Post는 실행 관측의 상관이며 인증된 사람 승인 영수증이 아니다. Post가 없다는 것은 로그 유실·실패·창 경계일 수 있고 마지막 분 pending 휴리스틱이 모두 해결하지 않는다. deny+Post의 우회 지표는 조사 신호이지 원인 판결이 아니다. return 0은 보안 적합성 통과가 아니다.

18개 CLI의 `__main__`에 공통 utf8_streams 소비가 있으나 import 후 main 호출까지 모든 스트림/자식 인코딩을 보장하지 않는다. provider의 Windows shim·stdin, paths 상대 경로, sandbox의 encoding/user-site 보완은 포팅 경험으로 읽었다. shell=True golden 명령의 shell 문법, pathlib의 Windows/WSL mount/path 차이, SQLite 잠금, 프로세스 자식 종료, 충돌 및 실제 서비스 복구는 실행하지 않았다. Linux·Windows·WSL 동작 등가는 미검증이다.

## Z01 — Zeus에서 흡수할 대상과 현재 보유 경계

직접 읽은 Zeus 구간은 supporting에 `working_tree_bytes_not_source_manifest`로 분리했다. `domain/sdd.py`는 사용자가 요구한 8단계를 선언하고 로그 유도 제안을 proposal_only, acceptance false로 둔다. `application/sdd.observe`도 imported_observation_not_verified_execution으로 저장하고 gap/미검증 알림을 남긴다. request_advance는 지금 차단되며 사람·실기기 runner가 연결됐다고 주장하지 않는다. `model_routing.select_model`은 자격 이전까지 Astra를 유지하고 SDD transfer record는 Astra→Sol→Terra 후보의 hash·증거를 요구한다. 이번 CLI의 문자열 모델 tier나 라우팅률로 그 자격을 충족시킬 수 없다.

`application/releases`의 읽은 구간은 ticket/candidate revision, 정책 hash, actor 역할, 검사 bool+증거, expected active 포인터와 store transaction을 사용한다. 이는 원본의 파일/JSONL 계약을 PG runtime SSOT 방향으로 비교할 연결점이다. read 범위에 실제 네트워크 배포나 DB adapter 전문은 없으므로 이름이 release/promote라고 실제 production 점진 배포·rollback 실증을 주장하지 않는다.

| 사용자 단계 | 이번 자산에서 가져올 의미 | 필요한 Zeus 결속 및 아직 없는 증거 |
|---|---|---|
| 스펙 논의 | scaffold 초안, invariant 선언/잔여, mirror 근거 | ticket revision·인간 핵심 시나리오·범위 승인 |
| 디자인 분석 | 역할 카드·스킬 문서의 전달/누락 표면 | 시각 검토·interaction oracle·스토리 승인 |
| 코드 작성 | 스킬 fragment 예산·파킹 패치·actor 귀속 | 자격을 획득한 모델, 내용 hash·격리 적용 |
| 자체 검증 | mutation baseline·cap·분모, golden, 미결 목록 | 실제 환경 identity·reset·기능 증거, ERROR≠검출 성공 |
| 알파 배포 | 장전/상태·패치 반영의 단계를 구분 | 실제 배포 대상·build·health·rollback receipt |
| QA 및 증적 | PARTIAL·이견·기계 gate와 advisory 구분 | 문장별 인증된 사람 승인, no mocked acceptance |
| 라이브 배포 | 승격 조건·정책 변경 이력 | 실제 점진 적용·관측·중단/롤백 증거 |
| CS 대응 | safety 분모·prompt/recall·pollution 감사 | 로그 공백 알림·정확한 보존·재발 이슈와 시나리오 연결 |

## 파일별 처분 지도

| 파일 (scripts/cli/) | 실제 계약/효과 | 주요 검토 |
|---|---|---|
| invariants_cmd.py | 문서 스캔 report; bite는 mutation 실행 | C06 |
| judge_cmd.py | 모델 요청·advisory·축/정족수 JSONL | C05 |
| ladder_cmd.py | 검증기 스윕·정책 승격/강등·ack/tune | C01 |
| mirror_cmd.py | index/coverage 파일 생성·kickoff 기준 | C08 |
| ontology_cmd.py | 인덱스 작성 후 검증·질의 | C08 |
| pollution_cmd.py | 진단·dry-run 기본·tombstone append | C11 |
| probe_cmd.py | 실제 산출물 변이·복원·blindspot 선언 | C06 |
| prompts_cmd.py | DB 집계·반복 후보·원문 폐기 | C07 |
| quality_cmd.py | golden/mutation 실행·skill 상관 집계 | C06, C09 |
| recall_cmd.py | FTS 색인 생성/갱신·검색 | C08 |
| residual_cmd.py | human 잔여·외부 판정 원장 기록 | C02 |
| roster_cmd.py | 역할 카드·호출 문자열·dispatch 집계 | C09 |
| run_cmd.py | pipeline 장전·해제·상태 | C04 |
| safety_cmd.py | hook 판단/실행 짝·기간 지표 | C10 |
| sandbox_cmd.py | patch 검사·파킹·승인·적용·반려 | C03 |
| scaffold_cmd.py | 템플릿 목록·산출물 발급 | C10 |
| skill_eval_cmd.py | synthetic 라우팅/선언/슬라이스 평가 | C09 |
| skills_cmd.py | frontmatter/corpus 계약 감사 | C09 |

## C11 — pollution은 물리 삭제 없이 판정 시야를 바꾼다

detect는 시간 bucket burst, 허용 writer, live 흔적 부재로 `confirmed`를 계산한다. 이는 인증된 오염 판결과 같지 않으며 이름·흔적 존재에 의존하는 휴리스틱이다. retract는 기본 dry-run, 비어 있지 않은 사유, 대상·배치 상한이 있고 tombstone을 append한다. `derive_state.apply_retractions`는 tombstone 자체의 재철회를 무시하여 resurrection을 막는다. 기존 데이터 물리 보존과 도출 시야 복원이라는 경험은 유용하다.

그러나 engine `detect`는 params의 bucket 값을 읽고 `retract`는 detector 메타에 상수 BUCKET_MS/BUCKET_MIN을 기록한다. 실제 설정과 감사 메타가 달라질 수 있다. CLI는 앞 20개 계획만 보여주고 실행은 계획 전체에 적용한다. 사유/operator 문자열, 재검사되지 않은 ID 목록만으로 실행 가능한 경로이므로 승인한 계획의 hash·ledger revision·현재 live 증거·권한을 Zeus에서 묶어야 한다. 이 범위에서 tombstone을 한 건도 쓰지 않았다. 지원 시험은 합성 burst, 사유·상한 거부, 물리 잔존·시야 복원을 읽었으며 실제 오염 판독의 정밀도나 PG 모든 reader 동등성은 측정하지 않았다.

## 미완료와 검증 경계

모든 18개 primary의 byte 수·Git blob·SHA256 대조는 files.json에 남긴다. manifest에 snapshot_sha256이 없는 지원 항목은 없음을 명시하고 Git blob/bytes와 이번 계산 SHA256을 별도로 남긴다. support 구간 밖 호출부, OS별 실행, 데이터베이스 writer의 전체 인가/복구, 모든 suite, 실거래 인수, 기존 source의 현재 실패 재현은 미검증이다. primary에는 몸체를 읽었지만 지원 시험이 선택되지 않은 파일도 있으며 그 사실은 files.json에 구분한다.

Samsung phone/tablet 실기기·Device Farm SDK/MCP·live interact·Replay 단계는 사용자 지시에 따라 유예다. 구현 완료라고 말하지 않는다. 원본 지침은 분석 데이터이고 Zeus의 런타임 정책에 자동 편입하지 않았다. 이번 결과로 전체 분석/채택 플래그를 올리지 않으며 shared coverage, runtime, source, commit, push 변경은 없다.
