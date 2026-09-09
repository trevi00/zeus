# Baldrix agents 003 정적 검토

<a id="scope"></a>
## 범위와 판정

`baldrix:agents:003`의 12개 원문, 190117 bytes, 5474행을 새로 전문 독해했다. 고정 revision은 `cbb5c3e6c9c4af6f86626474f4d7d62fd8e8a6d2`, scope는 `c181b712b1a775cbee3a81518412422d4723aa58a75da6fa347d9556798fddcb`다. 시작 Zeus HEAD는 `73f2c8848c0002df8dac3cc00f59566abfaa4134`다. 경로별 원시 Git blob, byte 수, SHA-256, 기존 unreviewed 원장 행과 그 해시는 files.json에 보존했다. 지원은 supporting-evidence.json의 실제 읽은 구간만 계상하며, 과거 보고서 의미 재사용은 0이다.

검토 대상은 에이전트 계약 문서다. 역할 분리, 사용자 결정 추적, 코드 연결 확인, 사람 확인 대기, 비활성 후보 생성 같은 자산은 있다. 그러나 선언된 독립 검수·APPROVED·CLOSED·passed가 실제 사람 인수, 모델 위임 자격, 실행 증거를 보증하지 않는다. 특히 UI 체크포인트 반환 계약, 검증 상태 소비, onboard 승인 표식과 실제 소비 코드의 차이를 Zeus 흡수 전에 해결해야 한다. 이는 정적 발견이며 원본 결함 재현이나 채택 승인이 아니다.

원본 실행/import/collection/probe/network/install/model 호출은 모두 0이다. 실제 세션·인증정보·운영 상태는 접근하지 않았다. URL과 제품·모델·보안 표준 관련 서술은 고정 원문의 주장으로만 다뤘고 외부 사실 검증은 0이다. 원문 명령을 실행하거나 상류 지시를 현재 권한으로 상속하지 않았다.

manifest에 snapshot SHA-256이 없는 지원 5개는 `get-shit-done/bin/lib/verify.cjs`, `frontmatter.cjs`, `profile-pipeline.cjs`, `model-profiles.cjs`와 `settings.json`이다. 이 항목은 SHA가 원래 있었다고 표시하지 않고 raw Git blob·byte 수를 manifest와 대조하고 별도 계산 SHA-256을 path-ledger와 대조했다. 나머지 primary 12개와 supporting 13개는 manifest의 snapshot SHA도 대조했다.

<a id="i01"></a>
## 01 — kha-planner.md

목적은 요구사항과 잠긴 사용자 결정에서 PLAN의 작업·의존성·검증 조건을 생성하는 것이다. Read/Write/Bash 및 검색 도구, opus, free_text 선언이다. 63–131행의 결정 ID 보존과 과도한 범위의 분할 제안은 사용자의 의도를 계획 예산 때문에 축소하지 않도록 한다. 204–245행은 작업별 files/action/verify/done과 자동화 검증을 요구하고, 464행 부근은 requirements를 비어 있지 않게 요구한다. 반면 137–140, 165–169행의 단독 사용자+Claude 전제와 팀/RACI/변경 관리 일괄 배제는 사용자가 요청한 spec·프론트·백엔드·QA/QC·DevOps의 검수 책임과 맞지 않는다.

실제 plan-phase 580–705행은 requirements, CONTEXT, UI-SPEC, 교차 AI 리뷰 등을 입력으로 넘기고 read_first와 acceptance_criteria를 요구한다. 다만 예시 상당수는 문자열 존재 검사이며, `--skip-verify`나 plan_checker 비활성은 후속 검수를 건너뛴다. verify.cjs 108–219행의 구조 검사는 필수 frontmatter 8개와 작업 태그를 검사하지만 requirements는 필수 목록에 없고, verify/done/files 부재와 작업 0개는 경고다. frontmatter.cjs 305–309, 358–381행도 필드 존재 검사이며 값의 의미와 사람 승인 결속은 아니다.

748–809행에는 사람 체크포인트와 배포 CLI 예제가 공존하고, 1105행 부근의 자동 모드 승인 및 1191행 부근의 커밋 지시도 있다. 자동화 가능성은 현재 프로젝트·환경·배포 범위의 인가를 뜻하지 않는다. Zeus에서는 문서 형식 검증과 SDD 인수 조건을 분리하고, 요구사항→시나리오→실제 실행 증거의 분모를 별도로 보존해야 한다. 주석 처리된 hook 예시는 활성 강제로 세지 않았다. 전체 planner 하위 참조와 실행기 폐쇄는 미완료다.

<a id="i02"></a>
## 02 — kha-project-researcher.md

스택·기능·아키텍처·함정 연구를 파일로 만드는 opus/free_text 역할이다. 출처 우선순위, 불확실성 표시, 검색 부재를 기능 부재로 단정하지 말라는 179–187행의 지침은 보존할 만하다. 그러나 도구나 공식 문서라는 출처 종류를 HIGH/MEDIUM 신뢰도로 바꾸는 규칙은 개별 주장 검증 기록이 아니다. 검색 도구 품질 비교와 학습 시차 수치는 이 고정 문서의 주장으로만 기록한다.

현행 553–565행은 단일 차원 작업자가 자기 파일만 쓰고 SUMMARY와 형제 파일을 건드리지 않게 한다. new-project 630–835행도 4개 차원을 각각 지정하고 모두 완료한 뒤 synthesizer를 호출한다. 따라서 현재 구현을 '모든 작업자가 무조건 같은 SUMMARY를 덮어씀'이라고 해석하지 않는다. 다만 전체 출력 성공 체크리스트와 단일 차원 계약은 문서 내부에서 범위가 다르며, 완료 신호의 파일 revision·출처 snapshot·실제 검증 분모 결속은 읽은 호출 구간에 없다. 질문의 2025 고정 연도도 재사용 시 갱신 대상이다. 연구 결과는 SDD 기획 입력 후보이며 최신 기술 추천이나 채택 승인이 아니다.

<a id="i03"></a>
## 03 — kha-research-synthesizer.md

Read/Write/Bash, opus/free_text로 네 연구 파일을 SUMMARY에 통합하고 연구 폴더를 커밋하는 역할이다. new-project 801–823행은 선행 4개 완료 후 정확한 파일을 넘긴다. 연구 병합 순서에 대한 방어는 있지만 동일 입력의 요약은 출처를 새로 확인한 독립 연구나 반대 검토가 아니다. 자체 웹 도구 선언도 없다.

35, 140–146행의 폴더 단위 커밋 지시는 해당 작업 외 변경 혼입 여부, 네 파일의 동일 실행 묶음, 커밋 실패 시 상태 처리와 별개다. 커밋 헬퍼 전체는 이번에 추적하지 않았다. Zeus에서는 요약과 독립 검토를 다른 증거 종류로 유지하고, 원문 주장·반증·미해결 질문을 Git 정의와 연결하되 런타임 완료 권위를 요약 텍스트에 주지 않아야 한다.

<a id="i04"></a>
## 04 — kha-roadmapper.md

요구사항마다 정확히 하나의 phase를 매핑하고 사용자 관찰 가능한 성공 조건을 도출한다. 100% 매핑은 요구사항 분류의 분모이며 구현·인수 100%가 아니다. 55–69행의 단독 사용자/Claude 전제와 팀·회고 배제는 사용자 조직 요구와 충돌한다. 범위에 맞지 않는 항목을 v2로 미루는 설명도 명시적 범위 결정과 연결해야 한다.

490–502행은 검토 전에 파일을 쓰라고 하고 마지막 성공 조건은 승인 후 쓰기를 말한다. 실제 new-project 1027–1036행은 먼저 ROADMAP/STATE/REQUIREMENTS를 쓰게 하며, 1089–1128행은 interactive에서 커밋 전 승인·수정 루프, auto에서 자동 승인한다. 따라서 '쓰기 전 사람 승인 강제'로 흡수하면 안 된다. Read/Write/Bash 선언인데 본문은 Edit도 지시한다. 실제 플랫폼 도구 제한 적용은 미검증이다.

단계 요약·상세·진행 표에 반복된 Markdown 표현과 UI 키워드 힌트는 사람 검토에 유용할 수 있으나 실제 런타임 정본은 아니다. Zeus의 Git 정의/PG 실행 상태 분리에 맞춰 요구사항 매핑의 버전과 승인 범위를 기록해야 한다. ROADMAP 전체 파서와 변경 동시성은 이번 지원 범위 밖이다.

<a id="i05"></a>
## 05 — kha-security-auditor.md

선언된 위협의 대응을 확인해 SECURITY 보고서를 쓰는 opus/free_text 역할이다. 구현 읽기 전용이라는 본문과 Read/Write/Bash 도구 선언은 경로 강제를 별도로 확인해야 한다. 44–46행의 CLOSED 기준은 mitigate 패턴 존재, accept 항목 존재, transfer 문서 존재다. 실제 공격 방어 효과나 위험 수락자의 권한·대상 revision·만료를 검증한 결과가 아니다. 선언되지 않은 위협은 48행상 정보성으로 남는다. ASVS 수준 표기도 기준별 실제 검사 분모를 대신하지 않는다.

secure-phase 전문은 security 비활성 종료, open 위협 0개이면 auditor 생략, 사용자에게 accept-all 선택 제시, open 잔여가 있으면 차단을 선언한다. 이 현행 차단 지시를 무시하고 항상 통과한다고 주장하지 않는다. 그러나 위협 선언의 완전성과 수락 표식의 인가가 충족되지 않으면 'open 0'도 실제 보안 인수가 아니다. 금전 흐름은 사람 핵심 시나리오와 실행 가능한 위협 오라클, 인가된 위험 수락을 별도 증거로 요구하는 Zeus 계약 후보이며 이번에 구현하거나 시험하지 않았다.

<a id="i06"></a>
## 06 — kha-ui-auditor.md

6개 UI 차원을 1–4점으로 평가하는 sonnet/free_text 역할이다. 64–81행의 현행 mode guard는 기본 audit에서 보고서 외 쓰기와 캡처를 제한하고 capture를 명시적 선택으로 두며 서버가 없으면 aborted_no_server로 종료시킨다. ui-review 74–105행은 mode를 지정하지 않으므로 기본 audit로 해석해야 한다. 이를 실제 캡처 실행이나 실제 스크린샷 검수 완료로 세지 않았다.

다만 본문 후반 실행 순서는 .gitignore와 캡처를 다시 무조건 지시하고, CLI 예제 160–184행은 서버 부재 시 코드 전용 평가로 돌아간다. 캡처 stderr를 버리고 산출물 존재·종료 상태를 검사하지 않은 채 완료를 표시하는 명령 예제도 있다. 이미 추적 중인 파일이나 기존 .gitignore 규칙은 '절대 커밋 안 됨'을 보장하지 않는다. npx registry 조회와 /tmp 파일 쓰기는 audit 제한과 함께 정리해야 한다. 이는 예제의 정적 계약 충돌이며 네트워크·브라우저 실행 결과가 아니다.

grep 기반 상태·색·타이포 탐색과 원격 registry 출력은 실제 설치 버전·렌더링·보조기술·태블릿/폰 경험을 증명하지 않는다. 점수는 검사 가능한 코드 후보를 찾는 보조 자료로 두고 시각적·인터랙션 인수와 분리해야 한다. Storybook 실행, screenshot 원본 hash, 서비스 신원과 환경 재현은 미검증이다.

<a id="i07"></a>
## 07 — kha-ui-checker.md

UI-SPEC의 6개 계약 차원을 읽고 PASS/FLAG/BLOCK으로 판정하는 sonnet/free_text 역할이다. 본문은 읽기 전용이며 Write는 없지만 Bash는 있다. 219행 부근은 모든 차원이 PASS 또는 FLAG이면 APPROVED로 취급한다. 사용자에게 보인 실제 UI 인수와는 다른 문서 적합성 상태다. 301행의 사용자 명시 결정 우선은 보존할 현행 방어다.

간격 허용 목록 147행에는 12가 없는데 수정 제안 158행에는 12가 있어 자체 규칙이 모순된다. 파괴적 행동 확인과 일부 라벨 부재는 FLAG이고, registry 점검은 날짜가 포함된 서술을 소비하며 config false면 차원을 생략한다. 날짜 문자열은 검수자와 대상 설치 버전의 증거가 아니다.

ui-phase 168–265행은 최대 2회 수정, 이후 강제 승인 선택을 안내하면서 최종 출력은 6/6 passed라고 고정한다. FLAG 수락이나 강제 종료의 분모와 '전부 PASS' 표현을 분리해야 한다. 연구자가 draft를 쓰고 checker가 승인 판정을 반환하는 문서 계약은 있으나 승인 metadata를 누가 확정적으로 갱신하는지 읽은 호출부에서 닫히지 않았다.

<a id="i08"></a>
## 08 — kha-ui-researcher.md

기존 결정을 확인하고 디자인 시스템·spacing·type·color·copy·interaction을 UI-SPEC으로 만드는 opus/free_text 역할이다. Read/Write/Bash 및 웹 도구가 있으나 AskUserQuestion은 없다. 현행 314–334행은 질문을 직접 수행하지 않고 UI-SPEC CHECKPOINT로 반환하여 오케스트레이터가 사용자 질문과 continuation을 맡게 한다. 그런데 직접 호출자인 ui-phase 152–158행은 UI-SPEC COMPLETE와 BLOCKED만 처리한다. 새 반환 상태의 전달·재개가 읽은 호출 계약에 빠져 있다.

기존 결정을 반복 질문하지 말라는 지시와 위험 registry를 사용자가 거부하거나 응답하지 않으면 차단한다는 지시는 보존한다. 다만 npx info/init/view 예제에는 설치 버전·lockfile·출력 hash와 오류 구분이 결속되지 않으며 날짜가 찍힌 검수 문구만으로 설치된 component 검수가 되지 않는다. 사용자 지정 shadcn/Lucide·토큰·Storybook을 구체적인 버전과 시나리오로 연결하는 작업은 미완료다. UI-SPEC 생성이나 checker 승인만으로 삼성 실기기·실제 사람 인수를 완료 처리할 수 없다.

<a id="i09"></a>
## 09 — kha-user-profiler.md

Read만 허용하고 sonnet/free_text를 선언하지만 결과는 8차원의 analysis JSON이다. 실제 메시지 인용·민감정보 제외·근거 부족 시 unknown을 요구하는 점은 유용하다. 단, 입력은 이미 길이 제한과 최근성 가중을 거친다고 35–40행에서 설명하면서 83, 169행에서 최근 메시지 약 3배 가중을 다시 적용하도록 한다. profile-pipeline 400–536행은 최근 30일 세션당 10개, 이전은 3개를 뽑고 최신 프로젝트부터 총 한도에 도달하면 중단한다. 따라서 균등한 프로젝트 대표성이나 원시 신호 수의 독립 분모를 가정할 수 없고 재가중 편향을 구분해야 한다.

profile-user 130–225, 240–335행은 샘플→에이전트→JSON 저장→차원 충돌 질문→프로필 저장을 지시한다. 사용자 선택으로 충돌을 해소하고 산출물을 선택하게 하는 방어가 있지만 추론한 선호를 명령형 claude_instruction으로 만드는 것은 현재 사용자 지시를 덮어쓸 권한이 아니다. 민감정보 제외 예시는 포괄적인 Windows/Unix 경로 검증 구현이 아니다. 세션 수집은 수행하지 않았고 샘플링·저장 helper의 미독 구간, 삭제·보존 정책, 실제 개인정보 처리 폐쇄는 미완료다.

<a id="i10"></a>
## 10 — kha-verifier.md

opus/free_text 검수자는 SUMMARY를 신뢰하지 않고 존재·실질 구현·연결·데이터 흐름을 구분하며, 초기 검증에서 ROADMAP 성공 조건을 PLAN must_haves에 합치는 현행 방어가 있다. 그러나 재검증 78–86행은 이전 must_haves를 재사용하고 초기 도출 단계를 생략한다. 입력 정의가 달라졌을 때 이전 통과와 override를 재활용해도 되는지 revision 결속은 별도 확인이 필요하다. 178–190행의 override는 텍스트 유사도와 accepted_by/time을 소비하며 실제 승인 신원을 인증한 결과는 아니다.

verify.cjs 283–402행의 artifact/key-link 검사는 파일·문자열 기반이다. 비객체 항목을 생략할 수 있고 결과 배열이 비면 every로 all_passed가 참이 된다. key-link의 정규식은 source 또는 target 어느 쪽 일치도 인정하며 실제 호출 경로를 실행하지 않는다. 에이전트 본문은 추가 수동 연결 검토를 요구하므로 helper만으로 전체 에이전트 행동을 단정하지 않는다. spot-check 435–479행도 2–4개, 짧은 명령 제한이며 테스트 출력 grep·JSON 비어 있지 않음·산출물 개수 예시는 실제 기능·실패 종료 보존의 충분한 오라클이 아니다.

483–511행은 시각·사용자 흐름·외부 연동의 사람 확인을 별도로 분류하고 human_needed를 우선한다. 이를 '사람 항목이 있는데도 항상 passed'라는 역사적 일반화로 기록하지 않는다. 다만 538행 부근의 뒤 단계 목표에 맞춘 gap→deferred→passed 전환은 새 범위 승인과 결속해야 한다. 실제 execute-phase 989–1058행은 status 문자열을 읽고 human_needed를 UAT pending으로 보존하지만 사용자 approved 뒤 UAT status:partial인 채 update_roadmap으로 이동한다. 단계 진행과 실제 인수 완료가 같은 상태가 아니다. Zeus의 PG 전이에는 검사된 분모·미실행/skip·사람 승인 대상·환경 증거를 보존해야 한다.

<a id="i11"></a>
## 11 — outpos-pr-creator.md

특정 조직 저장소·브랜치·계정 전환·PR 작성 규약을 담은 Read/Grep/Glob/Bash 역할이며 명시 model은 없다. 회사의 커밋 통계 등은 고정 원문 주장이다. 작업 트리 확인, PR 본문 및 관련 이슈 연결은 참고 자산이지만 사용자에게 일반 적용할 전역 규칙은 아니다. 회사명·계정·긴 원문은 이 보고서에 복제하지 않는다.

43행 부근의 고정 Git Bash/사용자 경로, push와 gh 명령, 147행의 merge 뒤 157행 CI 확인 순서는 Zeus의 Windows/Linux/WSL 및 배포 전 증거·승인 계약으로 그대로 이전할 수 없다. 전역 계정 전환과 merge 효과를 PR 문서 작성 권한에 합치면 안 된다. 제한된 workflows/scripts/settings 참조 검색에서 이 역할의 직접 caller는 찾지 못했으며 전체 미사용이라는 주장은 하지 않는다. 실제 GitHub 호출·계정 조회·PR·merge·배포는 수행하지 않았다.

<a id="i12"></a>
## 12 — research-stack-onboarder.md

opus와 Read/Grep/Glob/웹 도구로 스택 연구를 한 YAML에 남기도록 하지만 Write 도구가 선언되지 않는다. output_schema는 이름 `onboard_artifact_yaml`이다. artifact에는 단계 ID와 도구 토큰 기대값이 포함되고 operator_authored:false를 CLI가 강제한다는 설명이 있다. 실제 onboard_stack.py를 연결하면 비활성 candidates 배치와 token 없는 promote 차단은 존재한다. 다만 scaffold는 expected에 setdefault를 사용하여 입력 true를 보존하고, verify_candidate의 oracle_authored는 bool 변환이다. promote는 문자열 token, 구조 round-trip, 이 flag를 소비하며 B oracle 테스트를 실행하거나 출처·승인자·변경 대상 revision을 확인하지 않는다. 상수 token은 인가된 사람 신원의 증명이 아니다.

자동 생성 golden-pin의 B는 stage ID 포함과 직렬화된 텍스트의 tool token 존재를 확인하며 실제 언어 도구·서비스를 실행하지 않는다. operator 미작성 시 `pytest.xfail` 호출로 B 본문을 중단하며 'strict-xfail' 주석이 실제 B 실행을 뜻하지 않는다. promotion은 후보 파일 두 개를 live로 복사하고 선택적으로 원본 registry를 변경한다. 이 실제 운영 효과의 부분 실패·일관성 전체 검증은 미완료다. 원문 문서의 'strict-xfail/사람 oracle/완전 보호' 표현을 실제 인수로 세지 않는다.

test_onboard_stack.py 전문의 분모는 수동 main에 열거된 6개 함수다. tempfile에 paths와 pipeline 모듈 전역을 바꾸고 실제 core YAML을 복사하되 fake 언어 artifact를 넣는다. 비활성 파일·구조 비교·token 부재·flag false 차단·필수값 부재를 검사하며, 성공 경로는 테스트가 flag를 직접 true로 쓴다. 실제 사람 oracle, agent가 처음부터 true를 준 입력, 실제 tool 실행과 OS 인수를 시험한 증거가 아니다. 이 테스트는 실행하지 않았고 읽은 assert를 PASS로 표시하지 않았다.

<a id="trace"></a>
## 직접 소비 및 강제 경계

지원 원장의 모든 파일은 고정 바이트를 새로 읽은 것이다. primary 전문 12개와 supporting 부분 독해를 합산해 전체 source closure라고 표시하지 않는다. new-project, plan-phase, secure-phase, ui-phase, ui-review, execute-phase, profile-user는 모델 호출과 상태 소비를 설명하는 workflow 문서이며 이것 자체가 실행 관측은 아니다.

실제 settings.json 241–277행에는 Agent matcher의 post-tool 감사 hook과 고정 Windows 경로가 있다. agent_outcome_audit.py 1–128, 260–320행은 Agent 이름만 처리하고, free_text나 JSON 객체가 아닌 output_schema 이름은 schema 검사를 활성화하지 않는다. 따라서 11개 free_text와 onboard_artifact_yaml이라는 이름 선언이 타입 강제로 바뀌지 않는다. 자유 텍스트는 _raw_text envelope가 된다. structural.py 175–292행은 schema/evidence/tool_calls가 없으면 각 검사층을 생략하고 ok를 반환할 수 있으며 tool_allowlist는 응답에 기재된 tool_calls를 검사한다. 이 감사는 도구 실행 전의 경로 sandbox나 누락 없는 실제 도구 이벤트 수집 보증이 아니다. 별도 pre-tool 방어 전체와 Agent/Task 명칭의 실제 플랫폼 매핑은 미검증이다.

model-profiles.cjs 전문은 profile별 모델 이름 매핑이고 agents_normalize.py 1–80행의 역할별 기본값과 다르다. 예를 들어 verifier frontmatter와 normalization은 opus지만 profile 표는 sonnet/haiku를 사용한다. 어느 실행 경로에서 최종 값이 적용되는지의 전체 resolve 폐쇄는 남았다. test_agents_normalize.py 전문의 분모는 9개 test 함수로 이름·분포·문자열 삽입/치환/멱등을 검사한다. 실제 모델 호출이나 Astra→Sol→Terra 자격 승계 평가가 아니다. 이번 두 지원 테스트 파일의 15개 함수는 정적 독해 분모이고 실행 분모는 0이다.

<a id="zeus"></a>
## 사용자 SDD 요구와 흡수 조건

| 단계 | 읽은 자산 | Zeus에 남는 검증 및 설계 과제 |
|---|---|---|
| 1 스펙 논의 | planner 결정 ID, roadmapper 요구사항 매핑 | 실제 사람의 핵심 시나리오와 범위 승인, 팀별 검수 책임을 Git 정의에 결속 |
| 2 디자인 분석 | UI-SPEC 연구/문서 checker/UI auditor | 체크포인트 재개 계약, shadcn/Lucide 버전·토큰·Storybook·상태/인터랙션 근거 |
| 3 코드 작성 | 계획 task/interface/wiring | 모델별 위임 자격과 도구·경로 범위, 코드와 요구사항 revision 연결 |
| 4 자체 검증 | verifier·구조 helper·onboard 후보 테스트 | 문자열·fixture·생략 검사를 실제 도구 실행과 구분, 종료/분모/환경 증거 보존 |
| 5 알파 배포 | planner 배포 예제와 PR 흐름 | 환경별 인가, 배포 대상·실행·복구 영수증 및 실패 시 상태 |
| 6 QA/증적 | human_needed·HUMAN-UAT·사용자 응답 | 실제 사람 인수, 금융 핵심 흐름, 미완료/보류/강제 승인과 통과의 분리 |
| 7 라이브 배포 | PR/merge/CI 관련 지시 | 알파/QA 증거를 PG 전이에서 소비, 점진 배포·rollback·서비스 식별 |
| 8 CS/반복 | profiler·이전 SUMMARY·회고 참고 | 개인정보 범위, 실제 로그→시나리오→회귀 테스트, 승인된 개선과 모델 자격의 축적 |

여기서 제안한 연결은 Zeus 구현 등가나 채택 완료가 아니다. Git은 정의와 검토 가능한 변경을, PG는 실행·인가·인수·전이 상태를 맡는 요구와 대조했다. 자동 생성 코드·합성 승인·텍스트 점수는 실제 사람 인수로 계상하지 않는다. 삼성 폰/태블릿 실기기, Device Farm SDK/MCP/live/replay는 유예 상태이며 구축 또는 활용 완료라고 주장하지 않는다.

<a id="unknowns"></a>
## 남은 범위

12개 primary 본문 미독은 없다. 지원 파일의 미기록 구간, 전체 transitive 호출·설정·테스트, tool sandbox 및 pre-tool 인가, 실제 Agent/Task 호환, schema의 다른 validator 연결, Git helper·모델 resolver·PG 소비·승인 신원 검증은 미완료다. Windows/Linux/WSL·브라우저·실제 서비스·금전 흐름·기기·모델 실행은 검증하지 않았다. 외부 출처 원문·최신 사실·라이선스·독립 실제 Claude·사람 인수·전체 흡수는 모두 미완료다.

자체 검증은 metadata의 raw blob/bytes/SHA, read range, 링크 anchor, UTF-8/LF, 기록기 Ruff와 산출물 결속만 포함한다. 상류 코드·테스트·probe·설치·수집·운영 쓰기·공유 coverage·ticket·commit·push는 수행하지 않았다. parent만 종합과 구현을 진행한다.
