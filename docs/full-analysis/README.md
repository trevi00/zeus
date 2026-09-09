# 로컬 Claude 하네스 전수 분석 — 진행 중

사용자 요청은 일부 기능의 선별 검토가 아니라 **전체 분석 후 Zeus 흡수**이다. 작업을 파티션으로 나누되 파티션 완료를 전체 완료로 대체하지 않는다. 현재 신규 경험 유입 기능 구현은 보류하고 전수 분석을 먼저 진행한다.

## 고정 범위

| 저장소 | 커밋 | 추적 파일 |
|---|---|---:|
| Baldrix (`.claude`) | cbb5c3e6c9c4af6f86626474f4d7d62fd8e8a6d2 | 1648 |
| harness | a3f8b3be9a0a389329de6e16a6c7db81782041a3 | 931 |
| guardian | e7ced4a632a38726dca44e84fa0a00b8e1f0b6f4 | 13 |
| harness-design (구현이 직접 참조하는 설계 정본) | 20147dde412c1f2d84178d5c3665157ced1e7334 | 144 |

원래 세 저장소 2,592개, 필수 설계 의존성 포함 2,736개다. `.runtime/absorption/sources`에 Git 객체에서 얻은 원문과 인벤토리를 보존했다. 현재 로컬 변경은 별도의 observed/observed-deltas 해시로 결속하며 커밋의 내용이라고 표시하지 않는다. Git 밖 실제 Baldrix L1 메모리도 별도로 보존했다. credentials·승인 비밀키·브라우저 프로필·다른 프로젝트의 사적 대화 전체는 이 소스 분석의 대상이 아니다. 그 값을 Zeus로 복사하지 않는다.

**범위 보강:** 위 숫자는 Git 추적 경로의 분모이며 로컬 전체 파일 수가 아니다. Git untracked/ignored 메타데이터를 추가 조사해 Baldrix 8,747항목, harness 656항목, guardian 17항목을 발견했다. 중첩 저장소 디렉터리도 포함하므로 이 수를 파일 수라고 부르지 않는다. 작업별 시험 스크립트/기록, 플러그인, 미커밋 연구 노트, 원장과 런타임 경험도 별도 분석 대상이다. 현재 3,434개 추가 자산을 observed-extra에 바이트·시각·해시로 고정했고 일부 연구 노트·역할 로그부터 의미 검토하고 있다. 이 추가 자산의 파일별 검토 기록은 각 파티션의 `local-files.json`에 두며 추적 경로 집계에 섞지 않는다. 캐시/사적 세션/인증정보/중첩 저장소/대형 인덱스의 취득 상태·처분과 미해결은 `local-assets-status.json` 및 private local-assets 원장에 남겼다. 캐시는 자동으로 의미 검토 완료에 합산하지 않는다.

고정 인벤토리는 `path-ledger.json`, 검토 상태 집계는 `coverage.json`, 로컬 추가 범위는 `local-surface-summary.json`과 `local-assets-status.json`을 본다. 이 원장들도 inventory가 semantic review를 대신하지 않음을 명시한다.

## 완료 기준

1. 각 추적 파일에 목적·내용 의미·호출자·의존성·실패 처리·검증·Zeus 대응·채택/변형/제외 판단을 연결한다.
2. 문서의 선언, 구현 사실, 실제 실행 결과를 분리한다. README·파일 목록·AST 색인·문자열 hit만으로 의미 검토 완료를 표시하지 않는다.
3. 생성물·중복은 원본/생성자와 동등성 근거를 남긴다. 미검토/불가용 경로를 분모에서 지우지 않는다.
4. 원본 테스트는 실행 전에 읽고 실제 사용자 하네스를 마운트하지 않는 격리 환경에서 실행한다. 기존 테스트가 통과해도 별도 반례·모순은 남긴다.
5. Codex 분석과 실제 Claude의 독립 검토를 비교하고 논의한다. 구현은 주 Codex가 맡는다.
6. 전체 분석과 전체 흡수는 다른 완료선이다. 실행 의존·라이선스·미해결 결함이 남은 기능을 무조건 활성화하거나 원본의 승인/자격을 Zeus로 승계하지 않는다.

## 현재 파티션

- guardian: 전체 13개 및 pinned/observed 차이, 복원·감시·알림·봉인·토큰과 Zeus 매핑.
- Baldrix common skills: `_common` 전체 98개 및 실제 라우팅·호출 의존.
- harness experience: lessons 25, reports 25, trials 16, archive 22, root 회고 5개 = 93개 및 현재 lesson 변경.
- 주 Codex: 원본 정책/구성/토폴로지, 전체 커버리지 조정, 나머지 파티션 연결과 교차 검토.
- harness lib: 43개 공통 라이브러리의 원장·lease·중복 방지·판정 도출 등 구현/호출/테스트.
- harness-local-research: Git 밖 연구 노트 38개와 역할 로그 23개의 과거 판단·정정·제안 연결. 추가 자산 분모이며 현재 실행 테스트와 구분한다.
- design-canon: 설계 정본의 범위·용어·SSOT·런타임·컨텍스트 계약과 구현 차이. 아직 부분 검토.
- [Baldrix CLI 001](baldrix-cli-001/review.md), [002](baldrix-cli-002/review.md), [003](baldrix-cli-003/review.md), [004](baldrix-cli-004/review.md): 78개 전문 기록과 직접 의존. 중복 경로는 전체 분모에서 한 번만 센다. 001의 원본 테스트 34개만 실제 실행했으며 002·003·004는 정적 검토다.
- [프론트·SDD 자산](frontend-assets/review.md), [백엔드·데이터·DevOps](backend-assets/review.md), [다이어그램·모바일·역설계](diagram-mobile-assets/review.md): 88개 전문. 서로 다른 프로젝트의 관례와 사용자 요구를 구분하고 화살표 해석의 반증도 정정했다.
- [파이프라인·역할·완료선](harness-pipeline-contracts/README.md): 61개 전문. 사용자 8단계 SDD, 실제 판정 소비, 실행 권한과 문서 선언을 대조했다.
- [설계 결정문 001](design-decisions-001/review.md), [002](design-decisions-002/README.md): 추가 48개 전문 읽기 기록(D-050 기존 기록과 중복 1개 포함). 구현·호출·시험 추적은 미완료다.
- [Common 품질 공동 검토](cross-review-common-quality/resolution.md): 실제 Claude와 Codex 독립 판단·토론·정정, 원본 단위 테스트 15개 및 별도 입력 관측. 스킬 품질과 실제 선택·주입을 두 토픽으로 분리했다.
- [핵심 실행기 001](harness-engine-001/review.md), [002](harness-engine-002/README.md): 34개 전문과 직접 호출·설정·테스트 대조. 기존 검토 중복을 제외해 집계하며 상류 실행·채택은 미완료다.
- [스킬 라우팅 런타임 공동 검토](baldrix-skill-routing-runtime/resolution.md): 6개 전문과 명시한 의존성, 실제 Claude 독립 판단·토론·정정, 원본 단위 테스트57개와 단계 추천·YAML·예산·교차참조 입력 관측. 실제 hook과 모델 인수는 남았다.
- [추출기](harness-engine-extractors/review.md): 10개 전문. 순번 ID와 의미 보존, 정적 호출과 실제 사용자 시나리오, Python 모델 관계·TS 그래프 소비 범위를 대조했다. 실행·채택은 미완료다.
- [Harness CLI 001](harness-cli-001/review.md): 13개 전문. 자가개선 검증 대상, 실제 부작용·반환 상태, 완료선·관측·배포 경계와 원본 테스트의 의미를 연결했다. 실행은 0건이다.
- [게이트 소비·SDD 생성 공동 검토](harness-gate-consumer-joint/resolution.md): 기존 엔진 5개와 supporting 15개를 root가 재검토하고 실제 Claude와 독립 검토·토론·정정을 수행했다. 문장 귀속·PARTIAL·철회·ERROR·검사 분모 및 템플릿→lint→testgen 불일치를 확인했다. 정적 검토이며 원본 실행은 0건이다.
- [Baldrix CLI 005 공동 검토](baldrix-cli-005/resolution.md): 6개 전문과 root supporting 17개, 실제 Claude 독립 판단·토론·정정. 원본 텔레메트리 테스트 19개와 UTC/KST 원본 함수 관측을 실행했다. 시간대·지표 분모·미검사 frontend exit 0·worker DONE·writeback 적용/복구 계약을 대조했다.
- [Baldrix cron 001](baldrix-cron-001/review.md): 19개 전문. Windows 예약 등록, 중복 실행 lock, worker timeout, 실패 수술의 commit, 압축 원문 보존을 추적했다. 원본 실행과 실제 예약 설치는 0건이다.
- [Harness CLI 002](harness-cli-002/review.md): 11개 전문. health/HUD 부작용, 오류 계약 모집단, latency의 Bash 선택, feed 커서와 incident 해소 상태를 추적했다. 정적 검토이며 원본 실행은 0건이다.
- [Harness cron 001](harness-cron-001/review.md): 11개 전문. 소비 거절이 spawned 기록으로 바뀌는 경로, safe-mode 후처리, 스폰·회계 원자성, DBA 빈 projection heartbeat를 대조했다. 정적 검토이며 원본 실행은 0건이다.

- [Baldrix engine 001 공동 검토](baldrix-engine-001/resolution.md): 11개 전문, root 지원 24개, 실제 Claude 독립 검토·토론·정정. 원본 retry 단위 테스트 6개 및 격리 원본 함수 관측으로 shard 세대 역행·손상 원문 삭제·phase/ack 계약 불일치를 확인했다. 최초 의존성 import 실패도 보존했다.
- [Baldrix validators 001](baldrix-validators-001/review.md): 27개 전문. 호출자의 반환값/skip 처리, bridge 전체 삭제·warm cache, 명세 누락 PASS, 의미 검사와 문자열 검사 범위를 추적했다. 정적 검토이며 원본 실행 0건이다.
- [Harness CLI 003](harness-cli-003/review.md): 18개 전문. 카나리아 튜플 반환형, 판정 문장 귀속, patch 승인 identity, judge 기록, prompt 원문 폐기와 모델 자격을 추적했다. 정적 검토이며 원본 실행 0건이다.
- [Harness cron 002](harness-cron-002/review.md): 11개 전문. consumed→spawned, reachable/distillable 재판정, 실제 compose/cycle 배선, 파일 존재 완료율·미상 승인 귀속을 추적했다. 정적 검토이며 원본 실행 0건이다.

- [Baldrix Stop001 공동 검토](baldrix-stop-001/resolution.md): 6개 전문·지원 19개, 실제 Claude 독립 검토·토론·정정. 원본 달력 자체검사 36 assertions 및 원본 Stop CLI 4회 관측으로 첫 재시도 뒤 cwd/회고 필드 유실과 재선택 누락을 확인했다. 설치된 hook host 인수는 남았다.
- [Baldrix validators 002](baldrix-validators-002/review.md): 24개 전문. 검사 졸업 등록 불일치, staging 경계, feature ID 왕복과 실제 행동 검사 차이, 검사 소비 분모를 대조했다. 원본 실행 0건이다.
- [Harness CLI 004](harness-cli-004/review.md): 6개 전문. SKIP 소비, 위임·수거 귀속, 스켈레톤/문서 PASS와 실제 사람 인수 경계를 추적했다. 원본 실행 0건이다.
- [Harness handlers 001](harness-handlers-001/review.md): 20개 전문. posthoc 시간 예산, host timeout, 전역 heartbeat, 요약/삭제 집합 경합, harvest 단계 귀속을 대조했다. 원본 실행 0건이다.

- [완료 근거 권위 공동 검토](baldrix-completion-authority-001/resolution.md): lib 4개 전문과 지원 11개. 실제 Claude와 독립 검토·토론·정정, 원본 self-check 28 assertions 및 AC unit 17 tests, 타입·시각·범위·증거 저장의 별도 실측. 실제 evaluator/host 인수는 남았다.
- [Baldrix pretool](baldrix-pretool-001/review.md): 16개 전문. critic 결정/실행 혼동, 깊이 전파, PR 검사와 timeout, 알림 전달 범위를 대조했다. 원본 실행 0건이다.
- [Baldrix session hooks](baldrix-session-hooks-001/review.md): 13개 전문. 검사 없음의 success 기록, 반환코드 미검사, 후보·주입·세션 복원과 실제 완료를 구분했다. 원본 실행 0건이다.
- [Harness validators](harness-validators-001/review.md): 15개 전문. 검사 분모와 skip, 실제 배선 여부, 산출 귀속 및 형식 검사와 인간 시나리오 인수의 차이를 추적했다. 원본 실행 0건이다.

- [모델 호출 계약 공동 검토](baldrix-providers-001/resolution.md): 5개 전문·root 지원 7개, 실제 Claude 독립 판단·토론·정정. 원본 Ollama wrapper 8 assertions와 CLI 부재 registry/dataclass/unavailable 실측을 기록했다. 실제 모델 호출·토큰 측정·Windows/WSL upstream 인수는 없다.
- [Baldrix lib 001](baldrix-lib-001/review.md): 25개 전문 범위(새 전문21·선행 동일바이트4)와 지원15개. 알림 전송/저장 성공, brain 원격 내용 보존, quota·pane·merge 응답과 실제 실행의 차이를 추적했다. 원본 실행0이다.
- [Baldrix lib 003](baldrix-lib-003/review.md): 10개 전문·지원17개. 평가 성공과 객관 completeness, event emitter 연결, frontmatter·권한·지표의 unknown 상태를 대조했다. 원본 실행0이다.
- [Harness 통합 테스트 001](harness-integration-tests-001/review.md): 10개 전문·지원27개. inherited guardian 경로, state 밖 ontology 쓰기, 상수/약한 오라클, 사람 승인·모델 인수와 fixture 결과를 구분했다. 원본 실행0이다.

- [차단기 공동 검토](baldrix-breakers-001/resolution.md): 3개 전문·지원7개, 실제 Claude 독립 검토·토론·정정. 원본 단위 테스트34개와 실제 격리 파일/권한 관측을 기록했다. 저장 실패 후 admission, 이전 객체 결과의 새 예약 해제, 순서·중복에 따른 판정 차이가 확인됐다. 실제 프로세스 경쟁·모델·OS 인수는 남았다.
- [Baldrix lib 002](baldrix-lib-002/review.md): 23개 전문 범위(새 전문20·동일바이트 선행3)·지원13개. canary rollback 응답, 토큰 사용량/알림, 수렴·기억 승급과 실제 인수의 차이를 추적했다. 원본 실행0이다.
- [Baldrix lib 004](baldrix-lib-004/review.md): 19개 전문·지원26개. 졸업 epoch/ready, 중복 학습 증거, 설정 적용·event emitter·probe 실패 근거를 대조했다. 원본 실행0이다.
- [Harness 통합 테스트 002](harness-integration-tests-002/review.md): 17개 전문·지원36개. 실제 HOME/서비스 영향, 동일 증거 승급, 승인 fixture·skip 분모·Bash 선택 차이를 추적했다. 원본 실행0이다.

- [평가 보정 공동 검토](baldrix-calibration-001/resolution.md): 6개 전문·지원6개, 실제 Claude 독립 검토·토론·정정. 원본 단위16개와 실제 격리 파일 관측으로 승인값 불일치, 손상/빈 준비 파일, NaN 정책, 미분류 성공률과 실제 소비자/평가 차이를 대조했다. 합성 telemetry와 실제 사람·모델 인수는 구별한다.
- [Baldrix lib 005](baldrix-lib-005/review.md): 13개 전문·지원14개. milestone 요구/내용/판정 결속, diff 검토 범위, narration 사실성, 변이 검사 복원·분모를 추적했다. 원본 실행0이다.
- [Baldrix lib 006](baldrix-lib-006/review.md): 24개 전문·지원21개. quota 저장·원자성, 산출물 존재 기반 단계 판단, 재현 없이 True인 probe, 경로·회고·pane 입력 결과를 대조했다. 원본 실행0이다.
- [Harness 통합 테스트 003](harness-integration-tests-003/review.md): 14개 전문·지원42개. 기본 카나리아의 tuple/bool 불일치, HUD 상태 쓰기, 로그 승인 추정·동시성, 실제 서비스/부분 SKIP·순차 멱등 시험의 범위를 확인했다. 원본 실행0이다.

- [증거 감지 공동 검토](baldrix-observers-001/resolution.md): 2개 전문·지원4개, 실제 Claude 독립 검토·토론·정정. 원본 단위11개 및 격리 파일·권한·자식 관측으로 cwd 오판, 미검사 CLEAN, 자식 쓰기와 인코딩 예외를 확인했다. 실제 과거 위조나 사람 인수의 증명은 아니다.
- [Baldrix lib 007](baldrix-lib-007/review.md): 21개 전문·지원15개. 구조화 추출·거주 메모리·후보 쓰기·실제 주입과 평가 차이를 추적했다. 원본 실행0이다.
- [Baldrix lib 008](baldrix-lib-008/review.md): 23개 전문·지원23개. 스펙/테스트 생성, 변이 분모, 팀 종료/메일함, telemetry 손실과 승인값을 대조했다. 원본 실행0이다.
- [Harness 통합 테스트 004](harness-integration-tests-004/review.md): 17개 전문·지원56개. 브리프 승인/HMAC 장전, query-hit 지표/실제 검색 소비, 카드 전문/실제 step 전달과 로그 보존 시험 경계를 확인했다. 원본 실행0이다.

- [구조·어휘 검증기 공동 검토](baldrix-lib-validators-001/resolution.md): 5개 전문·root 지원7개, 실제 Claude 독립 검토·토론·정정. 원본 단위61개와 실제 격리 파일 관측으로 미검사 ok, 중복 경로 분모, 부분 오류와 CLEAN, 읽기 상한·판정 소비 차이를 확인했다.
- [Baldrix lib 009](baldrix-lib-009/review.md): 10개 전문·지원10개. writeback 단일 소비·경로·변경 대상, 계획 ID 의미와 상태 재사용, worker/통지 실제 효과를 추적했다. 원본 실행0이다.
- [Baldrix 추출기](baldrix-lib-extractors-001/review.md): 12개 전문·지원13개. flowchart/flow 검증 연결, 생성 PASS, 변환 후 원문 행·출처 유실과 실제 스펙 의미를 대조했다. 원본 실행0이다.
- [Harness 통합 테스트 005](harness-integration-tests-005/review.md): 9개 전문·지원47개. sandbox rc-only와 SKIP, seams 자동승급/CLI 카나리아, 합성 승인·통지·스켈레톤의 인수 경계를 추적했다. 원본 실행0이다.

- [계약 추출 공동 검토](baldrix-seams-001/resolution.md): 7개 전문·root 지원10개, 실제 Claude 독립 검토·토론·정정. 최초 yaml 부재22/26 실패를 보존하고 별도 기존 이미지에서 원본26/26 통과를 확인했다. 원본 함수 관측으로 변환 충돌 OK·HIGH 누락·원장 손상 뒤 감사 누락을 기록했다.
- [Baldrix mirror 추출기](baldrix-mirror-extractors-001/review.md): 4개 전문·지원2개. 정규화 hash의 의미·원시 바이트·경로·읽기 실패 및 구조 추출 경계를 추적했다. 원본 실행0이다.
- [Baldrix workers](baldrix-workers-001/review.md): 4개 전문·지원4개. worker 신원·세대·실제 출력/종료·OS quoting과 registry/문서 실행 경로를 대조했다. 원본 실행0이다.
- [Harness 계약 테스트001](harness-contract-tests-001/review.md): 11개 전문·지원29개. acceptance 탑재/인수, 후보 소진, 버스 held 실패 로그 및 실제 승인·전송 분모를 구분했다. 원본 실행0이다.
- [Harness 계약 테스트002](harness-contract-tests-002/review.md): 19개 전문·지원33개. projection heartbeat 조건, env 복원, 실제 reconfirmation 방어와 fixture/선언/실행 증거의 경계를 대조했다. 원본 실행0이다.

현재 고정 2,736개 중 1,512개에 검토 기록이 있으며 **1,224개는 아직 unreviewed**다. 이번 묶음은 배포 구성 4개와 테스트 79개로 새 primary 83개다. supporting은 새 파일 수에 더하지 않는다. 1,512개에도 본문만 읽었거나 실행·호출 추적이 남은 상태가 포함된다. 이것을 의미 분석 완료율이나 흡수 완료 수로 쓰지 않는다. 정확한 처분별 수는 `coverage.json`과 [root 검토](distribution-tests-root-review.md)를 따른다.

이번 [배포 구성 공동 검토](baldrix-distribution-config-001/resolution.md)는 실제 Claude 독립 검토·토론과 원본 status CLI 7회 관측을 포함한다. CI의 변경 필터와 snapshot 검증 대상의 불일치, 손상/누락 입력의 성공 반환, root/하위 cwd 스택 선택 차이를 기록했다. [tests009](baldrix-tests-009/review.md), [tests010](baldrix-tests-010/review.md), [tests011](baldrix-tests-011/review.md)은 79개 전문 정적 검토이며 원본 실행은 0이다. 83개 모두 직전 원장에서 unreviewed였으며 supporting 131개와 산출물 63개의 정체성을 확인했다. 기록기의 Windows cp949 독해 오류도 보존하고 UTF-8 지정 후 같은 영수증으로 검증했다. 실제 설치·서비스·기기·사람 인수·채택은 미완료다.

직전 [synthetic fleet 공동 검토](baldrix-synthetic-fleet-001/resolution.md)는 실제 Claude 독립 검토·토론, 원본 ontology 수동 테스트 5/5와 별도 parser 관측을 포함한다. proto 타입/RPC 및 응답 봉투 변경이 좁은 enum/필드 집합 검사에 드러나지 않는 경계를 기록했다. [tests006](baldrix-tests-006/review.md), [tests007](baldrix-tests-007/review.md), [tests008](baldrix-tests-008/review.md)은 73개 전문 정적 검토이며 원본 실행은 0이다. 111개 모두 당시 직전 원장에서 unreviewed였으며 supporting 120개와 산출물 65개의 정체성을 확인했다. 실제 서비스·기기·사람 인수와 채택은 미완료다.

직전 [예제 구성 공동 검토](baldrix-example-fleet-001/resolution.md)는 실제 Claude와 root의 독립 판단·토론·정정, 원본 수동 테스트 2/2 및 별도 CLI 6회 관측을 포함한다. [tests004](baldrix-tests-004/review.md), [tests005](baldrix-tests-005/review.md), [harness unit001](harness-unit-tests-001/review.md)은 62개 전문 정적 검토이며 실행은 0이다. 전체 82개는 직전 원장에서 모두 unreviewed였음을 별도로 대조했다. 119개 supporting 기록과 실행 영수증의 바이트 정체성을 확인했으며, 실제 서비스·기기·모델·사람 인수와 채택은 아직 완료되지 않았다.

- [실행기 공동 재검토](baldrix-test-runners-001/resolution.md): 기존 3개 전문·지원 10개, 실제 Claude 독립 검토와 토론. 원본 compaction 수동 6개 통과와 실제 helper 관측으로 pytest 실패 오분류·검사 분모·링크 쓰기를 확인했다. Claude가 지적한 root 기록기 결함도 수정하고 실제 타임아웃/오류/재시도 보존을 검증했다.
- [Baldrix tests 002](baldrix-tests-002/review.md), [003](baldrix-tests-003/review.md): 45개 전문·지원 83개. 수동 목록 누락·다른 pytest 오라클, 합성 E2E, 내구성/승인 근거와 실제 효과를 구분했다. 원본 실행 0건이다.
- [Harness contract 005](harness-contract-tests-005/review.md), [006](harness-contract-tests-006/review.md): 18개 전문·지원 42개. suite와 sandbox 판정 차이, 승인 표시/arming, 재실행·측정·queue 상태의 귀속을 대조했다. 원본 실행 0건이다.

- [루트 스크립트 공동 검토](baldrix-scripts-root-001/resolution.md): 5개 전문·지원 6개, 실제 Claude 독립 검토와 토론. 원본 설치기 정적 단위 5개 통과와 별도 실제 Git/CLI 격리 관측으로 훅 덮어쓰기, hooksPath 불일치, worktree 실패, 검사 누락과 반환값 모순을 기록했다.
- [Baldrix tests 001](baldrix-tests-001/review.md): 26개 전문·지원 29개. runner 격리 실패 후 지속, skip 집계, compaction 실패 전달, 합성 성공과 실제 인수를 구분했다. 원본 실행 0건이다.
- [Harness contract 003](harness-contract-tests-003/review.md), [004](harness-contract-tests-004/review.md): 30개 전문·지원 65개. 실제 설정과 검사 fixture, 측정 unknown과 재실행, 원장 watermark, repair/delivery 근거의 귀속을 대조했다. 원본 실행 0건이다.

Zeus 자체의 [Ubuntu WSL2 네이티브 검증](../zeus/wsl-validation/review.md)은 published `4cb7d02`에서 666 passed/62 skipped다. 원본 하네스 검증과 다른 범위이며 서비스 통합·인수·운영 배포는 포함하지 않는다.

Guardian의 전체 13개 의미 검토 및 pinned/observed 각 5스위트 실행은 `guardian/review.md`에 있다. 실제 Claude와의 합의·정정, 현재 Windows Python 자식 인코딩 실패 실측은 `cross-review/resolution.md`에 연결한다. 작은 저장소의 완료나 기존 스모크 PASS를 큰 저장소·실 운영 검증으로 확대하지 않는다.

harness lib의 정상 gate writer 추가 분석은 검토 도구의 자동 보안 검사로 중단됐다. 그 중단을 테스트 결과로 취급하지 않으며 기존 FA-005의 미검증 범위는 유지한다. `harness-lib/continuation-status.md`에 중단과 미실행 초안을 기록했다.

분석 결과는 각 폴더의 `files.json`과 리뷰 문서에 연결한다. 현재 전체 의미 분석은 **미완료**다. 아직 처리하지 않은 파일과 하위 시스템을 후속 파티션으로 계속 분석한다. 사용자 요청에 따라 독립 `trevi00/zeus` 저장소를 만들고 [GitHub Issues](../tickets/README.md)를 로컬 PostgreSQL 원장과 연동했다. Common 품질 공동 검토는 [미검사 PASS #12](https://github.com/trevi00/zeus/issues/12)와 [평가·실제 주입 불일치 #13](https://github.com/trevi00/zeus/issues/13)에, 후속 게이트 공동 검토는 [판정 귀속·PARTIAL #14](https://github.com/trevi00/zeus/issues/14)와 [스펙·인수 생성 계약 #15](https://github.com/trevi00/zeus/issues/15)에 연결했다. CLI005 writeback 공동 검토는 [승인 대상·단일 소비·복구 #16](https://github.com/trevi00/zeus/issues/16)으로, engine001 실측은 [pane 세대 역행·원문 소실 #17](https://github.com/trevi00/zeus/issues/17)로 분리했다. Stop001 실측은 [첫 재시도 뒤 재개·회고 상태 유실 #18](https://github.com/trevi00/zeus/issues/18)에 연결했다. 완료 근거 공동 검토는 [실제 평가·대상·시도 신원 결속 #19](https://github.com/trevi00/zeus/issues/19)에 연결했다. 이는 운영 배포나 기능 도입 승인이 아니다. 이후 작업 루트는 `C:/Users/rudtn/zeus`이며 과거 증거의 원본 경로는 당시 사실로 유지한다.

모델 호출 공동 검토는 [호출 계약·실측 사용량·모델 자격 #20](https://github.com/trevi00/zeus/issues/20)에 연결했다. 로컬 PostgreSQL 원장과 GitHub 20개 항목의 본문·제목·revision marker 일치를 확인했다.

차단기 공동 검토는 [단일 재시험 소유권·저장·정책 #21](https://github.com/trevi00/zeus/issues/21)에 연결했다. 근거는 `315e368`에 고정되어 있으며, 현재 로컬 PostgreSQL 원장과 GitHub 21개 항목의 본문·제목·marker 일치를 확인했다.

평가 보정 공동 검토는 [실제 평가 분모·소비자 동등성·승인값 #22](https://github.com/trevi00/zeus/issues/22)에 연결했다. 근거는 `0737d07`에 고정했으며 로컬 PostgreSQL 원장과 GitHub 22개 항목의 본문·제목·marker 일치를 확인했다.

증거 감지 공동 검토는 [검사 unknown·재실행 동일성·실행 권한 #23](https://github.com/trevi00/zeus/issues/23)에 연결했다. 근거는 `c99da02`에 고정했으며 로컬 PostgreSQL 원장과 GitHub 23개 항목의 본문·제목·marker 일치를 확인했다.

구조·어휘 검증기 공동 검토는 [실제 검사 분모와 인수 권위 #24](https://github.com/trevi00/zeus/issues/24)에 연결했다. 근거는 `60593c6`에 고정했으며 로컬 PostgreSQL 원장과 GitHub 24개 항목의 본문·제목·marker 일치를 확인했다.

계약 추출 공동 검토는 [누락·변환 충돌·판정 권위 #25](https://github.com/trevi00/zeus/issues/25)에 연결했다. 근거는 `9929b04`에 고정했다. 저장소는 사용자 요청으로 공개 전환했으며 서비스 운영 배포와는 별개다.

예제 구성·테스트 분모 검토는 [선언 그래프·실측 시나리오·필수 검사 분모 #28](https://github.com/trevi00/zeus/issues/28)에 연결했다. 근거는 `1f3851212d3725811868b75ac9d2fa9b7270c9d5`에 고정했으며 PostgreSQL 원장과 GitHub 28개 티켓의 제목·본문·연결 marker가 일치한다.

Synthetic fleet 검토는 [봉투·RPC·실제 인수 범위 #29](https://github.com/trevi00/zeus/issues/29), 사용자 종료 기준과 Zeus의 구현 공백은 [증거 기반 종료·재개·상태 조정 #30](https://github.com/trevi00/zeus/issues/30)에 연결했다. 근거는 `6fca1d49e39f2a57dc2f94922adc117c91d06b5f`에 고정했고 PG/GitHub 30개 티켓의 제목·본문·marker 일치를 확인했다. [별도 상태 관측](../tickets/lifecycle-observations.json) 당시 모두 OPEN이며 로컬도 미해결 상태다. 이는 종료 동기화 기능 검증이 아니며 해결 구현과 인수 검증이 남은 이슈를 닫지 않았다.

배포 구성·스냅샷 원본 실측은 [변경 분모와 엄격한 무결성 검사 #31](https://github.com/trevi00/zeus/issues/31)에 연결했다. 근거는 `87238e303b17d5bf2e8827a4fc3807ffac87cdf7`에 고정했으며 PG/GitHub 31개 티켓의 제목·본문·marker 일치를 확인했다. 최신 별도 상태 관측에서도 모두 미해결/OPEN이며 구현·인수 전 이슈 종료는 하지 않았다.
