# 설정·파이프라인·역할 계약 검토

지정한 일곱 파티션 **61경로, 281,967바이트를 전부 읽고 SHA-256을 대조했다**. 전달 당시 약 232KB라는 추정과 달리 고정 partition 합계는 약 282KB다. 원문 revision은 `a3f8b3be9a0a389329de6e16a6c7db81782041a3`이며 이 61개에는 별도 observed delta가 없다. glossary는 root의 기존 검토와 중복임을 표시하고 승격을 중복 계산하지 않았다.

파일별 판정은 [review.md](review.md)와 [files.json](files.json), 입력·출력·gate·역할의 원문 선언 데이터는 [contracts.json](contracts.json)에 있다. [supporting.json](supporting.json)은 보조 원문 17개와 Zeus 4개의 실제 읽은 범위·해시를 기록한다. 일부 보조 파일은 지정 구간만 읽었으며 전체 호출망 검토로 확대하지 않았다. [validation.json](validation.json)은 경로·해시·정적 계수 결과다.

**이번 upstream 테스트·원본 명령 실행은 0건이다.** 원본 코드 import, gate 실행, writer probe, 설치·복원·운영 원장 쓰기는 하지 않았다. 이전 자동 보안 검사로 중단된 probe를 우회하거나 재시도하지 않았다. 실행한 build-index.py는 이 디렉터리의 검토용 메타데이터 생성기이며 캡처를 데이터로 읽어 JSON/YAML 파싱·해시 확인만 한다. 이것을 upstream 테스트로 계산하지 않는다.

## 판정 권한에서 확인한 차이

1. **완료선의 100%는 증거 경로 존재다.** `completion_line.assess`는 exists 또는 glob으로 디렉터리도 충족시킨다. 내용·판정·실행 성공·revision·작성자를 확인하지 않는다. `completion_cmd assess`는 기본 모드에서 미충족이어도 exit 0이고 `--strict`만 이를 1로 바꾼다. `list`도 선언 오류를 출력한 뒤 0을 반환한다. 이 완료선은 목표 범위를 남기는 문서로 활용할 수 있지만 Zeus의 인수·배포 승인으로 채택할 수 없다.
2. **문장 의미와 실제 검사가 다르다.** core의 ‘모든 요구 고유 ID’, ‘모든 persona’, ‘각 endpoint JSON 예시’는 각각 문자열 한 번으로 판정될 수 있다. `checks._file_content`는 파일들을 합쳐 찾는다. `graph_queries._coverage`는 앵커 0건을 거부하지만 target에서는 경계 없는 substring을 찾으므로 REQ-1/REQ-10처럼 다른 ID를 혼동할 정적 가능성이 있다. 실제 충돌 시험은 수행하지 않았다.
3. **기계 실행도 종료코드와 출력의 권한을 구별해야 한다.** `_metric_threshold`는 `_source_text`의 비영 종료코드를 판정 조건에 넣지 않고 추출한 숫자를 평가한다. `_trigger_effect`도 관측 명령의 종료코드를 확인하지 않고 stdout+stderr regex를 본다. 반면 `_db_query`와 `_exit_code`는 비영 종료를 실패로 처리한다. `step_cmd gate`는 gate FAIL이나 PENDING_HUMAN이어도 CLI exit 0이므로 상위 자동화가 그 exit만으로 합격을 읽어서는 안 된다. 모두 정적 코드 근거이며 이번 재현 성공 주장으로 쓰지 않는다.
4. **외부 판정의 작성과 소비 계약이 갈린다.** `step_cmd judge`는 render 문장 선택과 비어 있지 않은 인용을 요구하지만 `gate_runner._external_verdict`는 stage+mode의 최신값만 소비한다. 문장별 인용·actor·산출물 해시·pipeline revision을 그 함수에서 재검증하지 않는다. cycle redo에서는 철회하지만 새로운 pipeline_started 경계는 이 함수의 철회 조건이 아니다. 다른 writer·보호 경로 전체는 이번에 실행 검증하지 않았으므로 실제 위조 가능성이나 공격 성공으로 단정하지 않는다.
5. **역할 이름·소유·도구 선언은 실행 권한 인증이 아니다.** ownership lint는 카드가 components에 정확히 한 번 owns하는지, verifier 심볼이 존재하는지 검사한다. agent card lint는 필수 키와 금지 도구·tier를 대조한다. 실제 Bash 명령의 부작용이나 child 모델·독립 context는 인증하지 않는다. researcher/evaluator/intent-interviewer/onboarder의 읽기 전용 선언과 파일 산출 요구는 writer 위임이 분리돼야 한다. 이전 연구 run50/60의 작성 실패 기록은 이 계약 차이의 역사적 자료이며 이번 실행 결과가 아니다.
6. **자가개선의 보호가 모든 pipeline에 동일하게 전파되지는 않았다.** selfimprove는 5단계21gate로 후보 ID 대조를 추가했다. 연구 노트는 2단계5마커이고 정확한 후보 ID·문서 해시 대조가 없다. selfimprove의 verify 입력에는 repair가 없고 core e2e 입력에도 implementation이 없다. 표시 seq 대신 input DAG가 순서의 정본이므로 명시되지 않은 선후관계를 완료 보장으로 읽지 않는다. research의 git diff 검사 역시 staged/untracked와 보호 경로 전체를 포괄하지 않는다.
7. **정책 자체의 옛 설명을 현재 동작으로 읽으면 안 된다.** arming의 꺼진 high-score 자동 승인 규칙은 주석상 결정문 개정만 남았다고 하지만 현재 validate는 활성 auto에 approved=true를 요구하고 approve=true 조합을 거부한다. 단순 enabled 전환만으로 합법화되지 않는다. 역할 목표는 Git JSONL 정본·PG projection이며 Zeus의 PostgreSQL 런타임 정본과 다르다. 별도 변경 설계가 필요하다.

## 사용자 8단계 SDD와의 대응

Zeus `domain/sdd.py` 전문과 현재 SDD README·전체 범위 문서를 읽었다. `gate_report`는 구조 검사 외 검증을 not_run으로 표시하고 여덟 단계 모두 blocked, acceptance_passed=false, release_authorized=false로 남긴다. 이는 준비 계층의 구현이며 아래 실제 실행 요구가 충족됐다는 뜻이 아니다.

| 사용자 단계 | 원본에서 참고할 계약 | 그대로 승계할 수 없는 것 / Zeus에 필요한 연결 |
|---|---|---|
| 스펙 논의 | requirements·usecase·GWT·human gate | 문자열 REQ와 persona는 전칭 검증이 아니다. 엄격한 스키마·안정 ID·검토된 기대값과 인증된 사람 결정을 결속해야 한다. |
| 디자인 분석 | wireframe·ui-flow·view·design-critic | ‘render’ 역할 이름만으로 실렌더가 아니다. 토큰·컴포넌트·Storybook과 실제 viewport/접근성 증거가 필요하다. |
| 코드 작성 | generator·domain-lead·DAG·scope | Java Controller/Service/Mapper 관례를 Zeus domain/application에 그대로 옮기지 않는다. 후보 트리·팀별 책임·쓰기 범위를 실권한과 결합한다. |
| 자체 검증 | evaluator·E2E·unit·reliability | source test 존재·marker·exit0·round-trip만으로 실제 기기·환경·초기화·비즈니스 동작을 승인하지 않는다. |
| 알파 배포 | core optional CD의 trigger/effect 구분 | 원본에는 명시적 alpha gate가 없다. 후보 revision과 배포 환경·실행 영수증을 결합한 필수 단계가 필요하다. |
| QA·증적·사람 승인 | human/render와 판정 원장 분리 | stage/mode 최신값이나 actor 문자열은 승인 인증이 아니다. 구체적 시나리오·oracle·증적 해시와 사람 인수 결정을 연결한다. |
| 점진적 라이브 배포 | 운영·CD·전제 지문·실패 회귀 | 원본 CD는 optional이며 점진 배포·rollback 영수증은 이 계약에서 완성되지 않았다. 기존 Zeus release 권한 경로를 사용해야 한다. |
| CS·모니터링 | incident→repair→lesson, monitoring | 원본에 SDD CS 단계가 없다. 실제 장애 관측을 새 스펙·티켓·회귀 자산으로 연결하고 누락·실패·재발을 보존한다. |

core는 31단계이며 overnight-python의 8단계는 todo CLI 시험이다. 어느 쪽도 단계 수만 맞춰 사용자의 8단계와 같다고 할 수 없다. 현재 Zeus organization.json은 conductor·research/improvement lead·worker 여섯 항목이며 SDD의 spec/frontend/backend/qa_qc/devops 책임 이름이 모두 실행 팀으로 구성된 상태를 입증하지 않는다. 모델 카드의 fable/opus 같은 과거 표기도 Astra/Sol/Terra의 검증 자격으로 승계하지 않는다.

## 플랫폼과 채택 경계

원본 selfimprove의 cmd.exe `set`·`%CD%`·`&&`와 상대 형제 경로, 머신별 runtime interpreter, Kafka 9092·PG 5434는 Zeus의 Windows/Linux/WSL 공통 계약으로 복사하면 안 된다. PyYAML·jsonschema·Java/tree-sitter·Gradle·npm·브라우저·DB·guardian 등은 역할마다 다른 외부 의존이다. 이 파티션은 현재 설치 상태나 WSL 실행 가능성을 검사하지 않았다. `paths.resolve`와 state_dir의 차이, HOME 변경 후 캐시, 경로 대소문자·symlink·shell 인용은 플랫폼별 후속 검증 대상이다.

채택 후보는 선언된 범위와 제외 범위, 판정 불능을 별도 상태로 남기는 방식, 후보 ID·신선도 대조, 입력 DAG, 소유와 변경 권한 분리, 원본 provenance와 정정 이력이다. **파일 존재를 완료로 승격하는 방식, 무검증 모델 평결, 원문 역할·정책 권한은 채택하지 않는다.** 독립 공동 검토와 실제 실행 증거가 남아 있어 이 파티션의 정적 전수 검토 완료를 전체 분석·흡수 완료로 표시하지 않는다.

이 bounded 작업은 완료됐으며 구현·commit·push 없이 중지한다. 후속은 정확한 revision에서의 독립 검토, 관련 tests/통과·실패·미실행 증거 연결, 승인된 격리 환경의 실행, 현재 Zeus 계약에 맞춘 구현과 검증이다.
