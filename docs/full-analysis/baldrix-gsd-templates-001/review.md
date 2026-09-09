# Baldrix GSD 템플릿 43개 독립 정적 검토

<a id="scope"></a>
## 범위와 판정 경계

`baldrix:get-shit-done/templates:001`과 `:002`의 43개, 226,301 bytes를 이번 작업에서 모두 새로 전문 읽었다. 시작 Zeus HEAD는 `5acaeced22de71ae3eb8584643e00557762745c0`, 원본은 Baldrix `cbb5c3e6c9c4af6f86626474f4d7d62fd8e8a6d2`의 pinned 사본이다. 범위 해시는 각각 `13d2fb78c5c165cb62bba7643505dbd05ce21470e236a388cd08ca8c8d0f1fc5`, `27bbbcb4ae7b0252a6d8449f1d419d413a843c5cca22043511d0408c6a8d9966`이다. 원래 경로 원장의 미검토 행과 행 번호·해시, manifest Git blob·bytes, 별도 원시 SHA-256은 `files.json`에 보존한다. manifest의 SHA 필드가 없는 경우에는 없다고 기록하며 임의로 존재했다고 만들지 않는다.

검토 대상은 문서·설정 템플릿이다. 빈 값, 예제 숫자, 초안 상태 자체는 결함이 아니다. 실제 소비자가 완성된 계약으로 잘못 인정하거나 템플릿과 다른 형식을 요구하는 부분을 구분했다. supporting 27개는 `supporting-evidence.json`에 기록한 구간만 읽었고 primary 전문 분모에 더하지 않는다. 이전 보고서의 역할 요약이나 의미 판정을 재사용하지 않았다. 본문 출력이 잘린 두 파일은 빠진 구간을 다시 표시해 읽었다.

원본 실행·import·collection·probe·네트워크·설치·실제 Claude 호출은 모두 0이다. 차단된 gatewriter ERROR probe를 재시도하거나 우회하지 않았다. 원본의 명령·스킬 지시는 분석 데이터로만 읽었다. 본 보고서와 메타데이터의 자체 검사 외 실행을 하지 않았고, 운영 소스·runtime·전역 coverage·티켓·commit·push를 변경하지 않았다. 전체 호출 폐쇄성, 라이선스, 실제 Claude 교차 검토, OS 실동작, 모델 자격, 실제 사람 인수, Zeus 채택·구현 등가는 모두 미완료다.

<a id="trace"></a>
## 실제 소비 경로에서 확인한 차이

1. **문서 템플릿과 생성 CLI가 같은 원본을 사용하지 않는다.** `template.cjs` 1–222는 Markdown 템플릿을 읽어 채우는 방식 대신 SUMMARY·PLAN 등의 자체 문자열을 만든다. PLAN 기본 출력에는 주 템플릿이 필수로 설명하는 `requirements`, `read_first`, `acceptance_criteria`가 없고 SUMMARY 기본 출력에는 `requirements-completed`가 없다. 전달 fields로 일부 frontmatter를 보충할 수 있으며 기존 파일은 덮어쓰지 않는 방어가 있다. 이것은 생성 기본값의 계약 차이이며 모든 완성 계획이 불완전하다는 뜻은 아니다. summary selector의 `### Task`와 파일명·`decision` 단어 휴리스틱도 XML task 중심 PLAN의 의미와 일치한다고 검증되지 않았다.
2. **UAT 미완료 표기와 감사 파서가 어긋난다.** UAT 템플릿은 `result: [pending]`을 초기값으로 사용한다. `uat.cjs` 1–282의 결과 매칭은 단어형 결과를 받아 이 대괄호 표현을 같은 pending으로 읽지 않는다. `phase.cjs` 652–812도 `result: pending`을 찾는다. 검증 보고서의 사람 확인 항목은 `### 1.` 제목인데 `uat.cjs`의 사람 항목 추출은 일반 번호·bullet·table 형식을 대상으로 한다. 따라서 제공된 형식 그대로는 해당 추출기의 미완료 항목 분모에서 빠질 수 있다는 정적 결론이다. 다른 gap 경로와 상태 경고가 있으므로 전체 gate 우회나 실제 인수 PASS 재현으로 일반화하지 않는다.
3. **완료 명령은 사람 인수 gate와 동의어가 아니다.** `phase.cjs`의 verification gaps/human_needed와 UAT pending/blocked/partial 경고는 명시적으로 비차단이다. phase 존재 검사는 방어이며, 계획/summary 개수는 집계하되 그 집계를 인수 차단 검사로 세지 않는다. `verify-work.md` 250–445는 pending·blocked·skip 사유에 따라 partial 상태를 만들지만 issues 수를 중심으로 후속 경로를 선택해 partial 상태에도 “All passed” 안내가 나올 여지가 있다. 이 workflow 문장을 실제 UI 실행이나 사용자 승인의 증거로 세지 않았다. 같은 파일의 자동 UI 검증 분기는 사람 확인을 대신하도록 지시하는 구간이 있어, Zeus의 실제 사람 인수 요구와는 별도 자격 조건이 필요하다.
4. **SUMMARY 존재·일부 문자열 검사와 요구사항 완료를 분리해야 한다.** `verify.cjs` 1–170의 summary 검사는 일부 파일·commit hash를 점검하지만 최종 `passed`는 missing files와 Self-Check 실패 여부로 계산한다. commit 조회 실패가 errors에 들어가더라도 그 자체는 이 반환식의 실패 조건이 아니다. 파일 추출 결과가 없고 실패 Self-Check가 없는 문서도 이 제한된 오라클을 통과할 수 있다. `commands.cjs` 405–468은 누락된 `requirements-completed`를 빈 배열로 추출한다. `execute-plan.md` 374–435는 요구사항 ID를 SUMMARY에 복사하도록 지시하지만 이 지시가 테스트·사용자 승인과 결속된 실행 영수증은 아니다.
5. **표시용 진척과 권한 있는 상태는 다르다.** `state.cjs` 363–407은 PLAN/SUMMARY 파일 수로 진척을 계산한다. `phase.cjs`의 ROADMAP 요구사항 매칭은 `**Requirements:**` 형식인데 roadmap 템플릿 예시는 `**Requirements**:`이다. 이 분기의 요구사항 갱신 누락 가능성을 기록하며 다른 파서 전체의 결함으로 확대하지 않는다. 두 문서 갱신을 lock으로 감싸는 것과 PG의 단일 트랜잭션·승인 원장은 동등하지 않다. 실제 crash/경합은 실행하지 않았다.
6. **설정 선언·정규화·CLI 접근은 서로 다르다.** `core.cjs` 211–368은 parallelization 객체를 enabled 중심으로 정규화하고 모든 template 키를 그대로 반환하지 않는다. 반면 `config.cjs` 330–405의 `config-get`은 원본 JSON의 dot 경로를 읽는다. 따라서 gates/safety/security가 전역적으로 무시된다고 단정할 수 없다. `config-set`은 알려진 키 검사를 수행하고 `config-new-project`는 별도 기본값 구성기를 사용한다. 템플릿의 확인·안전 flag만으로 실제 도구 권한이 강제됨을 인증할 수 없다.

현행 방어도 확인했다. `plan-phase.md` 580–640은 요구사항 ID와 XML task의 `read_first`·`acceptance_criteria`를 필수로 전달한다. `kha-phase-researcher.md` 383–415, 477–485, 599–623은 Validation Architecture를 생성하도록 지시한다. `kha-debugger.md` 1090–1142는 수리 후 사람 확인 전 해결 완료를 유보한다. `secure-phase.md`는 초안 숫자만 신뢰하지 않고 보안 검토 결과 분류를 요구한다. 이들은 유용한 현행 계약이며, 정적 선언을 실제 강제 구현·실행 성공으로 승격하지 않았다.

직접 테스트 검색은 `scripts/tests`와 `get-shit-done/bin/lib/__tests__`에서 UAT parser, template fill/select, `requirements-completed`, `nyquist_compliant` 등의 식별자로 한정했다. 해당 소비자의 직접 회귀 테스트 본문은 이 검색에서 발견하지 못했다. 이름 기반 전체 파일 목록은 일부 출력이 잘렸고, 잘못된 Windows glob 경로 검색도 있었으므로 이를 전체 테스트 부재 근거로 사용하지 않는다. 테스트 실행과 assertion PASS 분모는 0이다.

<a id="i01"></a>
## 01 — DEBUG.md

증상·재현 기대·실제 결과·오류는 고정하고, 증거와 배제 가설은 추가하며 현재 초점은 교체하는 디버깅 원장이다. 원인 조사와 수정·검증·사람 확인·해결 상태를 분리한다. 131–137의 사람 확인 전 resolved 금지와 실제 debugger 지원 구간은 사용자 CS 단계에 맞는 보존 후보다. 반면 세션 재개를 완벽히 보장한다는 설명은 OS·서비스 상태·소스 해시·실행 영수증까지 보존하는 기계적 재현 보장이 아니다. 빈 가설은 초안이며 실패는 증거·미해결 질문으로 남겨야 한다. 로그에서 시나리오를 만들 때 재현 입력과 실제 사용자의 확인을 함께 연결할 필요가 있다. 원본 디버깅 실행은 하지 않았다.

<a id="i02"></a>
## 02 — SECURITY.md

위협 목록과 ID, 위험·완화·검증, 수용한 위험, ASVS 수준 및 sign-off를 담는 보안 문서다. 초안의 `threats_open: 0`과 예제 행은 채워야 할 placeholder이므로 그 자체를 허위 완료 결함으로 판정하지 않는다. 실제 secure-phase 소비자는 발견을 분류하고 결과에 따라 처리하도록 지시한다. 그러나 체크박스와 verified 문자열에는 승인자·revision·만료·실행 증거가 없고, 수용 위험을 다시 제기하지 말라는 지시는 환경 변경 후 재검토 조건을 포함하지 않는다. 금융 핵심 시나리오의 위협을 요구사항·실제 테스트·사람 승인과 연결할 설계 자산이며 현재 승인 체계로 채택하지 않는다.

<a id="i03"></a>
## 03 — UAT.md

사용자 관찰 기대, 응답 원문, passed/issues/pending/skipped/blocked 분모와 환경·물리 기기 차단 사유를 보존한다. complete는 모든 항목에 결과가 생겼다는 의미와 실제 모두 통과를 구분해야 하며 예제의 diagnosed 상태는 성공 실행 증거가 아니다. `[pending]` 기본 표기와 실제 파서·phase 완료 검사의 차이는 공통 발견 2에 기록했다. resume 지침은 pending/blocked를 대상으로 설명하지만 일부 후속 지침은 pending만 찾는다. 사용자 말에서 severity를 추정하는 색상→cosmetic 같은 예제는 금전 흐름의 중요도를 보장하지 않는다. 실제 사람 응답의 신원·revision·증거 결속과 차단 해제 후 재실행이 Zeus QA에 필요하며 삼성 기기는 유예 상태로 유지한다.

<a id="i04"></a>
## 04 — UI-SPEC.md

디자인 도구·컴포넌트·아이콘·폰트, 간격·타이포·색상, CTA·empty/error·확인 인터랙션과 registry 변경 계약을 담는다. shadcn false, preset none, draft는 선택 전 기본값이다. 공식 registry와 외부 registry diff 요구, 여섯 항목 점검은 디자인 검토 체크리스트 자산이다. 실제 UI researcher/checker 지원 구간은 문서 생성·APPROVED/FLAGS 등 판정을 지시하지만 템플릿 PASS checkbox와 표현이 동일하지 않다. 토큰 생성기, Storybook 사례, 접근성·실제 화면 캡처·상태 전이의 실행 증거는 확인하지 않았다. shadcn/Lucide/색상 변수화를 사용자 결정과 결속할 후보이며 이 파일로 실제 사용자 경험이나 실기기 적합성을 인증할 수 없다.

<a id="i05"></a>
## 05 — VALIDATION.md

요구사항·위협·보안 동작을 task별 테스트 명령·파일 존재·상태에 연결하고 commit/wave/UAT 전 실행 주기를 정한다. draft, Nyquist false, Wave 0 미완료와 테스트 stub 계획은 실행되지 않은 준비 상태다. manual-only 항목도 별도 분모로 남긴다. `plan-phase.md`는 Validation Architecture가 있을 때 이 파일 생성을 다루고 파일 부재 조건을 검사하지만 연구 header가 없을 때는 경고 경로가 있다. 현재 researcher는 그 header를 쓰도록 지시하므로 템플릿 차이만으로 항상 생성되지 않는다고 주장하지 않는다. sign-off는 실제 명령 stdout/exit·환경·revision을 포함한 영수증이 아니다. 자체검증→알파→사람 QA 간의 증거 전달 구조로 검토하되 mock/stub를 인수로 인정하지 않는다.

<a id="i06"></a>
## 06 — claude-md.md

코드베이스 지도와 사용자 profile에서 생성하는 지침의 marker·섹션·출처를 정의한다. 생성 section과 profile section 분리 및 현재 profile-output의 수동 편집 보존 분기는 현행 방어다. 실제 생성기는 이 설명 파일을 읽는 단일 renderer가 아니라 별도 문자열 구현이므로 문서와 생성 출력의 동기화를 추가 검증해야 한다. 출처 파일명은 내용 해시·라이선스·현재 적합성을 대신하지 못한다. GSD를 기본으로 강제하는 지시는 이 검토에서 상속하지 않았고 사용자 지시보다 높은 권한을 갖지 않는다. 프로젝트 지침 생성과 토큰 절약의 후보지만 사용자 프로필 추론을 사람 승인이나 모델 자격으로 바꾸지 않는다.

<a id="i07"></a>
## 07 — codebase/architecture.md

레이어·데이터 흐름·상태·진입점·오류·로깅·횡단 관심사를 경로와 연결하는 지도 형식이다. mapper의 실제 파일 조사 역할과 연결된다. 예제의 CLI·파일 기반 저장·atomic write는 설명 예제이며 Baldrix 또는 Zeus의 실제 전체 아키텍처를 확인한 결과가 아니다. 진입점과 import 추적으로 전반을 요약하는 분모와 모든 실행 경로·트랜잭션의 폐쇄성은 다르다. 사용자 SDD의 설계 검토·온보딩에 유용하지만 PG runtime 권위를 이 Markdown에 이전해서는 안 된다. 프로세스 경계·실패 전파·승인 이벤트와 실제 소비자를 더 검증해야 한다.

<a id="i08"></a>
## 08 — codebase/concerns.md

기술 부채·버그·보안·성능·취약 경로·확장 제한·의존성·누락 기능·테스트 공백을 위치와 근거로 기록한다. 사실 중심, 재현 방법·영향·수정 방향 구분은 이슈 티켓 및 CS→회귀 시나리오의 좋은 입력 구조다. 예제의 결제·webhook race, 수치·비용·버전은 실제 관측이나 현재 기술 권고가 아니다. 일부 본문 출력이 잘린 뒤 해당 구간을 다시 읽었고 전문 분모를 보완했다. 실제 측정 로그·환경·원시 재현 입력·티켓 소비자는 이번 범위에서 확인하지 않았다. 우선순위 문구가 승인 없는 금융 범위 축소를 허용하지 않는다.

<a id="i09"></a>
## 09 — codebase/conventions.md

이름·파일·import·오류·로그·주석·함수 구성·모듈 경계의 실제 관례를 대표 파일과 설정에서 조사하는 템플릿이다. 5–10개 표본 및 약 80%의 공통 패턴을 기준으로 서술하므로 전체 파일 준수 검사 분모가 아니다. 다수 관례가 안전하거나 사용자가 승인한 규칙이라는 보장은 없고 소수의 엄격한 보안 규칙을 통계적으로 제거해서는 안 된다. 구조적 로깅과 상태 변화 기록은 Zeus의 알림·CS 자산 후보다. formatter/linter 실행 및 실제 예외 처리 관측은 0이며, 현재 규칙으로 추천하지 않고 원본 관례 조사 방식으로 기록한다.

<a id="i10"></a>
## 10 — codebase/integrations.md

외부 서비스·SDK·인증 변수 이름·저장소·CI·환경·webhook 연결을 문서화한다. 실제 비밀값을 쓰지 말라는 지침은 보존 후보다. 예제의 서비스 가격·한도·버전·인증 방식은 외부 원문이나 실환경에서 검증하지 않았다. Stripe test mode나 로컬 DB를 하나의 mock/stub 항목에 모아 쓰는 설명만으로 실제 서비스·sandbox·합성 fixture의 증거 수준을 동일시할 수 없다. 금전 시나리오는 idempotency·서명·재시도·잔액 결과의 실제 오라클과 연결되어야 한다. mapper의 문서 생성 지시만 추적했으며 API나 자격증명에 접근하지 않았다.

<a id="i11"></a>
## 11 — codebase/stack.md

언어·runtime·패키지 관리자·lockfile·주요 의존성·개발/운영 플랫폼을 간결하게 정리한다. 중요 의존성 5–10개와 필요한 버전에 집중하는 지도는 전체 SBOM·라이선스·정확한 의존성 closure와 다르다. 예제의 플랫폼 호환성이나 버전은 실제 지원 인증이 아니다. 배포 설계의 환경 목록 출발점으로 쓰되 Windows/PowerShell, Linux/Bash, WSL별 설치·경로·서비스·종료 동작의 실제 영수증이 필요하다. 이 리뷰에서는 해당 플랫폼 실행을 하지 않았다.

<a id="i12"></a>
## 12 — codebase/structure.md

디렉터리 목적, 진입점·설정·핵심 모듈 위치, 새 코드를 둘 곳, generated/committed 경계를 설명한다. 2–3단계 tree와 대표 경로는 전체 분석 원장과 다른 분모다. 예제의 installer 구조를 현행 source 구조로 간주하지 않았다. mapper가 문서를 작성하는 지원 경로는 읽었지만 전체 파일 이동·설치·소비자는 추적하지 않았다. Zeus의 신규 참여자와 spec→구현 파일 연결에 쓸 수 있으나 경로 존재와 코드 의미·실행 동일성을 별도로 확인해야 한다.

<a id="i13"></a>
## 13 — codebase/testing.md

실제 시험 구조·명령·fixture·assertion·coverage·비동기/오류 패턴을 대표 테스트에서 수집하는 문서다. 원본 예제는 fs/process/API/time/DB mocking과 단위·통합 테스트를 설명하며 실제 E2E 부재도 표기한다. 이것은 단위 검증 자산을 조사하는 용도이며 사용자가 요구한 무mock 실제 인수와 동일하지 않다. 대표 3–5개 패턴·약 5개 테스트, 예제의 coverage 80%는 전체 suite 실행이나 승인 정책이 아니다. watch 명령과 환경 변형도 실행하지 않았다. 각 테스트의 실제 SUT·fixture 주입·실패 오라클·실행 분모를 별도 유지하는 Zeus 검증 설계가 필요하다.

<a id="i14"></a>
## 14 — config.json

interactive mode, research/check/verifier/Nyquist/security, auto advance, parallelization·checkpoint·최대 agent, 확인 gates와 안전 flag를 선언한다. 값이 true라고 모든 호출에서 강제된다고 볼 수 없다. 공통 발견 6처럼 loader의 정규화와 raw config-get의 소비 경로가 다르고, config-set의 허용 키와 신규 프로젝트 기본값 구성도 별도 구현이다. 따라서 전역 무시 또는 전역 권한 허용이라는 양쪽 단정을 피한다. 외부·파괴적 동작의 승인 범위와 모델 위임 자격을 실제 도구/상태 전이에 결속해야 한다. 이 JSON을 로컬 설정으로 적용하거나 도구 권한을 변경하지 않았다.

<a id="i15"></a>
## 15 — context.md

scope anchor, 잠긴 결정의 DID, agent 재량, canonical references와 deferred 항목을 분리하여 사람의 의도를 downstream 계획에 전달한다. 사용자 말과 코드 참조를 구분하는 형식은 핵심 시나리오를 보존하는 자산이다. 예제에 새로운 DID 규칙이 모두 반영되지 않은 부분은 설명 세대 차이로 기록하며 런타임 실패를 주장하지 않는다. discuss-phase는 문서 저장·discussion log 생성을 지시하지만 결정자·승인 revision·해시·효력 범위는 이 템플릿만으로 결속되지 않는다. 인간 친화적 검토 VIEW에 연결할 후보이며 파일 존재를 승인으로 대체하지 않는다.

<a id="i16"></a>
## 16 — continue-here.md

현재 task, 완료·잔여 작업, 결정·차단·다음 행동을 압축한 재개 문서다. task 수나 날짜는 예시이며 실측 진행이 아니다. 실제 pause/resume workflow는 HANDOFF.json을 우선하는 경로와 새 blocking constraints를 갖고 있어 이 Markdown만으로 재개 체계를 설명하면 불완전하다. 재개 후 일회성 파일 삭제는 영구 감사 원장과 다르며 별도 보존 없이는 맥락이 사라질 수 있다. 프로세스·서비스·환경 상태를 재현하지 않으므로 “다음 행동” 지침과 실제 재개 성공을 구분한다. Zeus PG 이벤트와 Git revision에 결속한 파생 VIEW로 검토할 대상이다.

<a id="i17"></a>
## 17 — copilot-instructions.md

7줄의 opt-in 라우팅 지침으로 명시적 요청 시 GSD를 쓰고 계속 사용자에게 질문 제안을 하도록 한다. claude-md의 기본 라우팅과 의도가 다르며 사용자의 불필요한 확인을 줄이라는 선호보다 우선할 수 없다. 제한된 JS/CJS/Python 및 이름 기반 workflow 검색에서 직접 설치·복사 소비자는 찾지 못했으나 전체적으로 사용되지 않는다고 단정하지 않는다. agent 실행·권한 강제·독립 검수·인수를 증명하는 파일이 아니다. Zeus에 지시문을 그대로 흡수하지 않고 사용자 선택과 명령 라우팅 구현을 별도 설계해야 한다.

<a id="i18"></a>
## 18 — debug-subagent-prompt.md

문제 맥락·증상·재현·목표를 Task 호출에 전달하고 root-cause-only와 fix 모드를 구분하는 prompt다. 이어받기에서 사용자 응답과 디버그 파일을 제공한다. boolean·본문 placeholder는 의도된 입력 자리다. 실제 debugger의 사람 확인 계약은 별도 지원 구간에서 확인했지만 이 prompt 파일의 구체적인 loader·호출 일치 및 모델 권한 강제는 확인하지 못했다. fresh continuation은 대화 상태 완전 복원이나 실행 재현을 뜻하지 않는다. CS 팀의 작업 경계 후보이며 Astra→Sol→Terra 자격 증거로 세지 않는다.

<a id="i19"></a>
## 19 — dev-preferences.md

생성 시각·프로필 출처와 선호 stack·workflow를 짧게 제공하는 prompt 부품이다. 높은 신뢰 추론을 직접 적용하고 낮은 신뢰는 유보하는 설명은 모델 추론의 처리 방식이며 사용자 승인 사실이 아니다. profile-output 지원 구간은 이 템플릿을 읽고 사용자 홈에 산출물을 쓰는 경로를 보여 준다. 입력 옵션이 없으면 placeholder를 남길 수 있으므로 문서 생성과 충분한 profile 수집을 구분한다. 이번에는 홈·세션·credential에 접근하지 않았다. 토큰 효율에 쓸 후보지만 근거·동의·보존 범위와 충돌 해결이 미검증이다.

<a id="i20"></a>
## 20 — discovery.md

선택지·조사 깊이·권위별 출처·부정 주장 교차 확인·대안·미지 사항을 기록하는 탐색 문서다. 실제 discovery-phase는 깊이에 따라 문서 생성 여부를 다르게 처리하므로 파일 개수만으로 조사 완결성을 계산할 수 없다. 날짜 확인과 검색 순서는 원문 snapshot·version·라이선스·현재 적합성 검증을 대신하지 않는다. 본 리뷰는 외부 URL에 접속하지 않았고 예제 기술을 추천하지 않는다. 사용자 spec 논의에서 불확실성과 추가 확인을 남기는 자산이며 연구 완료/채택 gate는 별도 필요하다.

<a id="i21"></a>
## 21 — discussion-log.md

질문·선택지·선택 결과·사용자 자유응답·재량 위임·보류 결정을 감사용으로 남긴다. downstream prompt에 넣지 않는다는 의도는 원장 보존과 토큰 절약의 분리다. discuss-phase는 CONTEXT와 함께 생성·commit하도록 지시한다. 하지만 기록만으로 응답자의 권한·내용 revision·승인 효력이 증명되지는 않는다. 사용자 멘탈 시나리오를 VIEW에서 검토하는 입력으로 보존할 가치가 있으며 단순 summary가 원 응답을 대체하지 않게 해야 한다. 실제 대화 수집·commit은 하지 않았다.

<a id="i22"></a>
## 22 — milestone-archive.md

완료 phase, 결정·해결/보류 문제·부채를 SHIPPED milestone 문서로 보관한다. 체크된 항목과 SHIPPED는 완성 후 채울 예시이며 그 자체가 배포 사실은 아니다. 실제 complete-milestone은 알려진 gap을 기록하고 진행하는 선택도 제공한다. archive 경로의 문서 설명과 workflow가 만드는 이름도 대조가 필요하다. 화면 증거 정리·삭제 지침은 보존된 다른 증거가 있는지까지 확인해야 하며 이 리뷰에서 삭제나 전체 아카이브 폐쇄성을 검증하지 않았다. alpha/QA/live 승격·rollback 영수증 없이 milestone 종료를 프로덕션 성공으로 세지 않아야 한다.

<a id="i23"></a>
## 23 — milestone.md

출시 milestone의 전달 가치·통계·phase·날짜·Git 범위를 역순으로 정리한다. 원본은 shipped만 기록하라고 하지만 예제 commit 범위에 의미 있는 메시지 표현을 쓰는 것은 immutable object 결속과 다르다. find/xargs 등 Bash 예시는 Windows 경로·공백·종료 코드 계약을 보장하지 않는다. 실제 complete-milestone이 작성하는 이력과 연결되지만 배포·고객 관찰·CS 상태의 독립 검증은 없다. 사용자의 7단계 live 배포와 문서상 milestone 완료를 분리해야 한다. 원본 명령은 실행하지 않았다.

<a id="i24"></a>
## 24 — phase-prompt.md

PLAN frontmatter, wave·dependency·요구사항, XML task, read-first·acceptance criteria, 검증·must-haves 및 checkpoint 유형을 정의한다. 빈 requirements 배열에는 채워야 한다는 명시가 있으므로 초안 값 자체는 결함이 아니다. 일부 오래된 예제는 새 필수 필드가 덜 반영되어 있고 구현 task의 제한된 범위보다 넓은 완료 문구를 쓰지만 실제 완료로 읽지 않았다. 실제 plan-phase의 새 prompt는 해당 필드를 다시 필수로 요구한다. 반면 template fill의 별도 기본 구조·selector 휴리스틱·frontmatter/plan validator의 제한된 presence 검사는 의미적으로 같은 계약이 아니다. task 입력·오라클·사람 확인·환경 영수증을 결속해야 하며 context 예산 비율과 checkpoint 재개 설명은 모델 자격이나 실제 권한의 증거가 아니다.

<a id="i25"></a>
## 25 — planner-subagent-prompt.md

standard/gap 모드의 planning context, 파일 참조, quality gate와 planner 반환 형식을 전달하는 prompt 템플릿이다. 실제 plan-phase 580–640에는 UI-SPEC, 요구사항 ID, cross-AI review 및 필수 XML 세부 필드가 추가되어 있어 이 템플릿 요약만으로 현재 planner 입력을 설명하면 누락된다. 이 파일 자체를 읽는 loader와 모든 continuation 경로는 확인하지 못했다. Task 선언과 품질 checklist가 독립 reviewer 실행 또는 승인 권한을 강제하지 않는다. spec팀→구현팀 입력 계약의 후보이며 actual Claude와 Astra/Sol/Terra 자격 검증은 별도다.

<a id="i26"></a>
## 26 — project.md

사용자 언어로 프로젝트·핵심 가치·Active/Validated/Out of Scope·제약·결정 결과를 유지한다. 핵심 가치와 범위는 사용자의 시나리오를 고정할 중요한 입력이다. 다만 brownfield에서는 기존 코드에서 Validated를 추론하도록 하고 실제 new-project도 이를 지시한다. 코드 존재가 shipped·사용자 가치 확인과 같은 증거 수준은 아니다. Zeus에서는 구현 관찰과 사람 가치 검증을 별도 상태로 남겨야 한다. 이번에는 실제 프로젝트 인터뷰나 요구 승인·배포를 수행하지 않았다.

<a id="i27"></a>
## 27 — requirements.md

원자적 사용자 요구 ID, v1/v2·범위 밖, phase 추적표, 완료 checkbox를 정의한다. 각 v1 요구를 정확히 하나의 phase에 연결하라는 분모 규칙과 수동 확인·구현/검증 후 완료 지침은 유용하다. 그러나 실제 phase complete의 문서 갱신이 그 전체 의미를 실행으로 강제하는지는 별도이며 공통 발견의 요구사항 라벨 매칭 차이도 있다. 체크박스와 Complete 문자열은 real scenario 실행과 승인자 결속을 포함하지 않는다. spec→시나리오→E2E→사람 인수 VIEW의 핵심 ID 후보이나 현재 파일을 PG runtime 권위로 삼지 않는다.

<a id="i28"></a>
## 28 — research-project/ARCHITECTURE.md

도메인의 구성 요소·경계·흐름·폴더·패턴·확장 단계·통합 접점을 출처와 함께 비교한다. new-project가 여러 연구 결과를 합성하는 입력으로 지정하는 것을 확인했다. 도식과 확장 수치·추천 패턴은 원본 연구용 예시이며 actual source 구조·부하 측정·전체 호출 closure가 아니다. 사람 시나리오를 시스템 경계와 연결하는 디자인 분석 자산으로 검토할 수 있으나 현재 최선의 기술 권고로 추천하지 않는다. 외부 원문·라이선스와 환경별 실측은 미완료다.

<a id="i29"></a>
## 29 — research-project/FEATURES.md

기본 기대 기능·차별화·의도적 제외·의존 관계·MVP/후속 버전 우선순위를 비교한다. 경쟁 제품·사용자 기대와 출처는 조사 항목이며 이번 검토가 그 사실을 검증한 것은 아니다. 일반적 사용자 기대를 실제 사용자의 핵심 멘탈 시나리오나 금융 위험 승인으로 대체할 수 없다. new-project의 feature 연구와 합성 입력을 읽었고 실제 인터뷰·경쟁 서비스 이용은 하지 않았다. scope 논의와 토픽별 티켓 분리에 쓰되 보류 결정과 승인 주체를 연결해야 한다.

<a id="i30"></a>
## 30 — research-project/PITFALLS.md

함정의 원인·조기 신호·예방·발생 phase·복구 비용과 허용할 기술 부채를 정리한다. 보안·성능·UX·완료 착각을 함께 다뤄 log→scenario 및 CS 회귀 자산 후보가 된다. 그러나 알려진 패턴 목록이 실제 발생 로그나 재현된 회귀 테스트는 아니다. 경고 threshold·예외 허용·복구 비용 예시는 외부 원문 및 실측을 검증하지 않았다. new-project의 연구 입력까지 추적했으며 실제 notification·이슈 발행·복구 동작은 확인하지 않았다.

<a id="i31"></a>
## 31 — research-project/STACK.md

기술·버전·용도·선택 이유·대안·피할 옵션·설치 명령·출처/검증 항목을 정리한다. 비교 근거를 남기는 구조는 보존 후보지만 URL·권위 이름·명령 목록만으로 현재 버전이나 라이선스·안전성이 검증되지는 않는다. npm install 예제는 모든 의존성을 immutable하게 고정한 배포 계약이 아니다. 실제 new-project의 stack 연구 입력과 연결되며 이번에는 설치나 외부 확인을 하지 않았다. Windows/Linux/WSL의 재현 가능한 환경 정의로 채택하기 전 별도 검증이 필요하다.

<a id="i32"></a>
## 32 — research-project/SUMMARY.md

네 가지 연구를 합쳐 confidence·gaps·권고 phase·심층 조사가 필요한 지점을 요약한다. new-project는 개별 연구 완료 뒤 합성을 요청하는 경로를 가진다. 이는 입력 종합이며 같은 모델 요약을 독립 검수나 외부 확인으로 더할 수 없다. 예제의 ready 표시는 채워야 할 판정 자리다. 출처별 실제 검증 분모와 미지 사항을 유지해야 하며 사용자 scope 결정·실제 인수를 완료시키는 문서가 아니다. 모든 연구 원문과 현재 외부 사실의 closure는 이 범위에서 미완료다.

<a id="i33"></a>
## 33 — research.md

phase 연구에서 사용자 제약·표준 stack·패턴·함정·코드 예제·출처·신뢰도·유효 기간을 기록한다. CONTEXT가 없으면 모든 결정을 Claude 재량으로 보는 문구는 파일 부재와 실제 사용자 제약 부재를 혼동할 수 있어 그대로 상속하지 않는다. 7/30일 유효 기간과 과거 버전·날짜·3D 코드 예제는 현재 사실이나 재현 보장이 아니다. 이 템플릿 본문에는 Validation Architecture 구조가 없지만 현재 researcher는 이를 명시적으로 생성하고 plan-phase/validate-phase가 소비한다. 따라서 문서 세대 간 차이로 기록한다. 스펙에서 테스트 도출할 출발점이며 외부 추천·실행·인수는 모두 미검증이다.

<a id="i34"></a>
## 34 — retrospective.md

milestone 성과·실수·패턴·비용·model mix·품질을 누적하는 회고 양식이다. complete-milestone의 기록 지시와 planner의 최근 회고 일부 읽기 경로를 확인했다. 최근 tail 구간의 읽기는 전체 누적 경험 회수와 같지 않다. 모델 비중이나 여러 milestone에서 검증됐다는 예제 문구에는 실행 분모·baseline·반증·자격 전이 영수증이 없다. 사용자 요구의 자가개선과 토큰 효율에 연결할 후보지만 Astra가 만든 guardrail을 Sol·Terra가 동등하게 통과했다는 자격 증거가 되지는 않는다.

<a id="i35"></a>
## 35 — roadmap.md

정수/소수 phase 순서, 목표·의존·요구사항·성공 조건, milestone과 progress 표를 정의한다. 완료·보류를 구분하는 의미 구조는 유용하다. 요구사항 제목의 bold와 colon 위치가 phase.cjs의 해당 매칭식과 다르다는 정적 발견은 공통 항목에 한정했다. 다른 roadmap 파서의 전체 처리를 검증하지 않았으므로 전역 갱신 실패로 표현하지 않는다. summary 수나 phase 체크는 실제 alpha/QA/live 배포 성공과 다른 분모다. Git 정의와 PG 진행 상태에서 생성되는 VIEW로 검토할 대상이다.

<a id="i36"></a>
## 36 — state.md

현재 위치·최근 성과·작은 결정 집합·blocker·세션 연속성을 약 100줄 안에 유지하는 살아 있는 기억 문서다. 완료 plan/전체 plan 비율이라는 정의는 실제 state.cjs의 파일 개수 기반 갱신과 연결된다. 이 값은 목표 충족·실행 결과·사람 인수율이 아니다. 최근 5개 plan과 짧은 결정만 보존하는 압축은 영구 원장의 대체물이 아니다. Zeus에서는 PG runtime의 승인된 상태를 보여 주는 파생 문서로 사용하고 Git spec revision과 연결하는 설계가 필요하다. 동시성·crash 복원·OS별 실동작은 검증하지 않았다.

<a id="i37"></a>
## 37 — summary-complex.md

복잡한 plan 결과를 의존성·제공 기능·기술·파일·결정·패턴·편차·문제로 상세히 요약한다. 주 summary 템플릿의 `requirements-completed`가 이 변형의 기본 frontmatter에는 없다. 생성·선택 경로가 이를 자동 보완하는지 현재 읽은 구간에서는 확인되지 않았고 extractor는 누락을 빈 배열로 다룬다. 복잡도 선택 휴리스틱은 task 의미·위험의 증명과 다르다. 상세 문장 수를 검증량으로 세지 말고 요구 ID·실제 실행 증거를 공통 필수 필드로 유지할 필요가 있다. 원본 실행은 0이다.

<a id="i38"></a>
## 38 — summary-minimal.md

작은 변경의 결과·핵심 파일·결정을 짧게 남기는 변형이다. 최소화는 유효한 토큰 절약 목적이지만 요구사항 완료 필드와 더 상세한 의존·문제·검증 구조가 기본 형태에서 생략된다. placeholder 자체보다 동일 extractor·후속 상태 소비자가 이 변형을 읽을 때 어떤 필수 의미가 사라지는지가 중요하다. template selector의 단순성 판정은 금융 영향이나 실제 인수 필요성을 보장하지 않는다. 간단한 구현을 Terra에 맡겨도 승인·환경·실패 증거의 필수 계약은 유지해야 한다는 후보 판정이며 자격을 인증하지 않는다.

<a id="i39"></a>
## 39 — summary-standard.md

보통 plan의 결과·결정·편차를 압축하는 중간 변형이다. 다른 축약형처럼 요구사항 완료 배열이 기본 frontmatter에 없고 전체 summary와의 기계적 공통 schema가 템플릿만으로 보장되지 않는다. 실제 selector는 조건이나 오류에 따라 standard로 돌아갈 수 있다. 이 fallback은 의미적 완결성 판정이 아니다. Zeus에서는 설명 길이를 줄이더라도 Git revision·scenario ID·실행·승인 분모를 공통으로 유지할 필요가 있다. 생성 결과를 실행하지 않았고 실제 후속 프로젝트 상태 변화는 미검증이다.

<a id="i40"></a>
## 40 — summary.md

의존·제공·영향·기술·파일·결정·패턴·완료 요구사항·duration, commit·편차·이슈·사용자 설정·다음 준비를 연결한다. execute-plan은 plan의 요구사항 ID를 모두 복사하도록 한다. 복사는 실제 각각의 요구가 테스트되고 사람이 인수했다는 오라클이 아니다. verifySummary는 파일·Self-Check 중심의 제한된 검사이며 commit 확인 오류가 최종 passed 조건과 분리되는 점은 공통 발견 4에 기록했다. 단순 성공 문구와 실행 영수증을 분리하고 실패·미설정·사람 대기를 완료로 승격하지 않아야 한다. 축약형과 생성 CLI 간 schema 일치 및 실제 인수 소비자는 미완료다.

<a id="i41"></a>
## 41 — user-profile.md

여덟 차원의 rating·confidence·directive·evidence와 수집 수·제외를 기록한다. placeholder는 미수집 상태다. profile-output의 실제 생성·redaction·문서 출력 구간을 읽었지만 수집 pipeline 전체와 모든 evidence alias의 처리 폐쇄성을 검증하지 않았으므로 민감정보 유출을 확정하지 않는다. 추론된 선호의 신뢰도는 사용자 승인·권한이나 모델 자격이 아니다. 이번에는 session collection 및 홈/credential 접근을 하지 않았다. 토큰 절약·대화 적응 후보로 삼되 동의·출처·보존·수정권을 확인해야 한다.

<a id="i42"></a>
## 42 — user-setup.md

계정 생성·secret·dashboard 설정처럼 사람이 처리할 항목과 확인 명령을 Incomplete 상태로 남긴다. execute-plan은 이 문서를 생성하는 시점을 지정하고 실제 자동화 가능 작업과 구분하도록 지시한다. 그러나 비밀값을 문서에 넣지 말라는 끝 지침과 달리 예제의 `.env.local` grep 명령은 실제로 실행하면 값까지 출력할 수 있다. 이 리뷰는 명령을 실행하거나 credential을 읽지 않았다. 예제의 빈 callback 400 응답은 정상 서명·결제·재시도 전체 E2E 성공이 아니다. Bash/외부 UI 능력에 대한 과거 설명을 현재 사실로 추천하지 않으며 사람 설정 완료와 alpha/live 인수의 증거 경계를 유지한다.

<a id="i43"></a>
## 43 — verification-report.md

관찰 가능한 truth·artifact·wiring·요구사항·anti-pattern·사람 확인·gap을 별도 표로 보고한다. blocker와 warning을 구분하는 구조는 유용하지만 예제의 frontmatter 점수 2/5와 본문 1/5처럼 내부 분모가 어긋나는 설명 부분이 있다. 사람 확인 `### 1.` 제목이 실제 uat parser의 추출 형식과 맞지 않는 점을 확인했다. passed/gaps_found/human_needed 선언에는 실행 환경·소스 revision·runner receipt·승인자 결속이 자동으로 포함되지 않는다. phase 완료의 경고 소비를 실제 인수 gate로 오인하지 않아야 한다. template fill의 pending 초안 상태는 완성 판정과 구분하며 실제 검증 실행은 0이다.

<a id="zeus"></a>
## Zeus 요구사항과의 대응

| 사용자 단계 | 보존할 후보 | 채택 전에 필요한 별도 증거 |
|---|---|---|
| 1. 스펙 논의 | PROJECT/REQUIREMENTS/CONTEXT/DISCUSSION-LOG의 핵심 가치·ID·원 응답 | 실제 사람의 핵심 시나리오, 승인자·revision·범위, Git 정의의 변경 추적 |
| 2. 디자인 분석 | UI-SPEC·구조/통합 지도·연구의 결정 근거 | shadcn/Lucide 선택, 색상 토큰·Storybook·상태/접근성 시나리오, 외부 원문·라이선스 |
| 3. 코드 작성 | PLAN의 read-first·acceptance criteria·의존성, SUMMARY의 trace | 생성기/변형/template의 공통 schema, 실제 수정 파일·소스 해시·요구 ID 결속 |
| 4. 자체검증 | VALIDATION과 truth/artifact/wiring 분모 | 실제 SUT·fixture/mock 구분, 원시 결과·실패·skip·환경 영수증, 거짓 양성 회귀 검사 |
| 5. 알파 배포 | USER-SETUP의 사람이 할 환경 작업 | 고정 이미지·환경·서비스·배포 revision과 실제 alpha 가용성·rollback 관측 |
| 6. QA 및 증적 | UAT 사용자 기대·응답·blocked/partial, DEBUG 사람 확인 | 실제 사람 인수, 미완료 표기 round trip, 증거 보존, 결제 흐름의 실제 결과 |
| 7. 라이브 배포 | milestone/roadmap의 이력·결정·잔여 위험 | 문서상 complete와 분리된 PG 승격 권한, 점진 배포·관측·되돌리기 영수증 |
| 8. CS 대응 | DEBUG/concerns/retrospective의 증상·원인·회고 | 알림 로그→티켓→시나리오→실제 회귀 연결, 손실 없는 증거 보존·재평가 |

반복은 문서 수를 늘리는 것만으로 달성되지 않는다. Git에는 승인된 정의를 두고 PG에는 권한 있는 runtime 전이·실행·인수 상태를 두며 Markdown과 인간 친화적 VIEW는 해당 기록의 파생 표현으로 연결할 설계 후보다. 이번에는 Zeus 구현이나 PG consumer를 변경·실행하지 않아 등가성을 주장하지 않는다. mock이 포함된 단위 시험은 유용한 다른 분모로 유지하되 사용자의 무mock 실제 인수를 대신하지 않는다. 삼성 휴대폰·태블릿, Device Farm SDK/MCP/live/interact/replay는 유예 상태이며 구축했다고 주장하지 않는다.

Astra의 초기 설계·최종 검증, Sol의 중요 구현, Terra의 단순 구현이라는 사용자 요구에는 모델 이름/비중보다 자격 전이가 필요하다. 이 템플릿의 confidence·cost·context 비율·task 설명은 자격 증거가 아니다. 동일 실제 시나리오에서 Astra의 판단과 guardrail을 Sol이 재현하고, 자격을 얻은 Sol의 절차를 Terra가 재현하는 분모·실패/보류·승격 승인 설계가 추가로 필요하다. 현재 채택 승인과 자격 부여는 하지 않았다.

<a id="unknowns"></a>
## 남은 검증과 불가용 범위

43개 전문 독해만 완료했다. 기록한 지원 구간 외 전이·호출·설정·테스트 전체 폐쇄성, CJS parser의 실제 입력 재현, template 변형 전체 round trip, hook·도구 권한 강제, 배포·복원·동시성·파일 경로의 OS 실동작은 미완료다. Windows glob 오류와 잘린 목록은 성공한 검색/독해로 계상하지 않는다. 직접 테스트를 이번 검색에서 찾지 못한 것과 원본 전체에 테스트가 없다는 주장은 다르다.

외부 출처의 현재 사실·버전·권위·라이선스 검증은 0이다. 연구의 URL과 저자명, 예제 PASS·SHIPPED·verified, 테스트 명령과 fixture는 이 리뷰의 검증 결과가 아니다. 실제 Claude 독립 검토는 root의 별도 범위이며 이 문서 자체의 실행 또는 동의로 합산하지 않는다. 원본 실행·import·probe·collection·network·install·모델 호출·실제 사용자 인수는 모두 0이고, 전체 분석 완료·실기기/OS 검증·라이선스 완료·모델 자격·Zeus 흡수/채택은 모두 false다.
