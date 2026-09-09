# 파일별 독립 정적 검토

<a id="file-01"></a>
## agents/harness-analyst.md

1–76 전문. sonnet과 Read/Grep/Glob만 선언하는 요구 분석 역할이다. 구현 가능성·모호성·범위·가정·검증 가능한 인수 조건을 planner 앞에서 정리한다. market 판단·계획 작성·기존 계획 비판의 역할 분리는 유지 후보다. 하지만 free_text 출력, 모든 질문을 찾는다는 완전성 선언 및 100배 비용 주장은 기계 검증/원문 근거가 없다. 요구 ID·사용자 승인·revision·미답 질문에 따른 차단·핵심 시나리오 실제 사람 인수는 명시적 상태 계약이 아니다. Zeus에서는 SDD 요구 정의 후보로만 사용하고 Git 정의/PG 검토 상태 및 독립 승인에 결속한다. 원본 실행0.

<a id="file-02"></a>
## agents/harness-architect.md

1–195 전문. opus/xhigh, 읽기와 WebFetch를 선언하는 설계 토론 판정자다. planner/critic 입력을 비교해 accepted/rejected/conditional·근거·ADR·ATAM·ontology snapshot을 JSON으로 출력하라고 하지만 frontmatter output_schema는 free_text다. 반대 근거와 비용·조건부 non-risk·잔여 결함을 기록하는 방법은 유용하다. 1세대 approved 즉시 수렴과 이후 동일 snapshot 2회 수렴은 의미 타당성·실제 구현/시험/인수를 보장하지 않는다. schema는 fields에 id/type/value를 제시하지만 prior LOCK이 다른 shape여도 byte-identical 재현하라는 지시가 있어 구조 정합과 충돌할 수 있다. 새로운 설계 금지와 critic counter-proposal 반영의 경계도 별도다. C4/ISO/arc42/ATAM 외부 사실·문헌 원문은 미검증이다. Zeus에서는 판정 산문 대신 source/target revision과 독립 lease 및 증거 closure를 요구하며 사람이 핵심 시나리오를 확인하기 전 승인 완료로 승격하지 않는다. 실행0.

<a id="file-03"></a>
## agents/harness-code-simplifier.md

1–72 전문. sonnet, Edit/Bash를 포함해 실제 변경 권한이 넓다. 세션 변경 파일만 단순화하고 기능 보존·의심 시 미변경·새 기능/시험 금지를 요구한다. 타입 검사/lint만으로 정확한 기능 보존을 입증할 수 없고 Bash는 선언된 파일 범위를 강제하지 않는다. exported signature 등 위험을 구체화한 점은 유지 후보다. 독립 behavioral oracle·전후 revision·동시 변경·rollback은 산출물에 없다. Zeus에서는 제한된 변경 제안/작업 권한과 incumbent 시험·인수 영수증을 별도로 결속해야 한다. 원문 명령 실행0.

<a id="file-04"></a>
## agents/harness-critic.md

1–75 전문. opus/xhigh, Read/Grep/Glob/WebFetch. 설계의 가정·실패·단순화만 공격하고 구현 없음 자체를 blocker로 삼지 말라는 DGE 구분은 유용하다. 반면 credible failure 하나라도 blocker를 요구해 위험 크기/수용 조건과 우선순위가 과대해질 수 있다. JSON 단일 객체 요구와 free_text frontmatter가 다르며 evidence는 path/사건/측정 가능성 문자열이어서 실제 읽기·독립성·hash·재현을 강제하지 않는다. files_to_read 전부 읽기 및 citation freshness는 선언만으로 확인되지 않는다. Zeus의 독립 설계 검토와 실행·사람 인수는 다른 단계로 유지해야 한다. 원본 실행0.

<a id="file-05"></a>
## agents/harness-design-critic.md

1–63 전문. sonnet, Bash와 Playwright navigate/screenshot/snapshot/console/resize/evaluate를 선언한다. read-only 산문과 달리 Bash·browser evaluate는 쓰기/외부 상태 변경까지 가능한 도구다. 375/768/1280 렌더링·콘솔·가시성 확인, generator와 별개 검토, 잔여 위험은 유지 후보다. URL 부재 시 코드 검토로 신뢰도만 낮추며 approved 조건에 실제 렌더링 필수성이 분명하지 않다. lint finding 0 또는 justified는 정당화 권위가 없고 7개 점수는 모델 평가다. 디자인 루브릭/스크린샷으로 실제 사람 시나리오·실장치 a11y·데이터 무결성을 대체할 수 없다. Zeus는 UI observation과 사용자 인수 영수증을 분리한다. 실행0.

<a id="file-06"></a>
## agents/harness-designer.md

1–102 전문. sonnet, Bash/Write/Edit. 디자인 구현·interaction·loading/empty/error/focus·responsive와 independent critic 루프를 요구한다. 다만 Agent 도구나 Playwright 도구가 목록에 없는데 critic dispatch와 screenshot 확인을 지시한다. Bash로 우회 가능한가와 정식 capability routing은 직접 호출 검토가 필요하다. 한국어 우선 skill은 line-height1.5라 소개하면서 acceptance bar는1.2–1.45로 고정하고, 기존 프로젝트 존중과 font/8pt/600 ceiling 등 보편 금지가 충돌할 수 있다. 의미 검토 없이 숫자 취향을 합격 기준으로 굳히지 않아야 한다. 사용자 live 확인 최종 판단 문구는 유지하되 상태를 강제하는 계약은 아니다. Zeus SDD에서는 디자인 조건의 사용자 승인, 실제 브라우저·핵심 사람 시나리오와 revision 결속을 요구한다. 외부 기준 원문/법적 주장 미검증, 실행0.

<a id="file-07"></a>
## agents/harness-document-specialist.md

1–81 전문. sonnet, Read/Glob/Grep/Bash/WebFetch/WebSearch. 로컬 문서→Context7→공식 문서 순서·버전·출처를 요구한다. 그러나 Context7 MCP는 tools 목록에 없고 library ID만으로 원문을 대신할 수 있는 출력 계약이다. 로컬 README 우선은 프로젝트 정의 탐색에는 유용하지만 구현 사실의 정본 검증을 대체하지 못한다. 2년 기준은 도메인별 최신성 증거가 아니며 Bash의 부작용 제한도 없다. Zeus 흡수는 discovery와 원문 pin/전수 독해/독립 검수/라이선스/인수를 분리해야 한다. 실제 검색·원문 링크 확인·실행0.

<a id="file-08"></a>
## agents/harness-evaluator.md

1–159 전문. model 필드가 없으며 Read/Grep/WebSearch/WebFetch만 선언한다. 본문은 OpenAIProvider/codex subprocess로 cross-provider를 보장한다고 주장하면서 Claude frontmatter가 Bash/Glob를 강제 차단한다고도 말한다. 어떤 runner가 이 도구 선언을 소비하는지 직접 대조가 필요하다. prompt의 경로 금지 regex와 Read/Grep 산문 제한은 OS 격리가 아니다. test_pass·citation3·ontology_match 및 validators/units100%·known_defects0를 신뢰하되 모순 시 escalate 요구는 유지 후보다. 그러나 Tier1 absence를 감점하지 말라는117행과 신규 surface 시험 없음은 stability≤2/completenessFalse인147행이 충돌한다. citation 개수·boolean은 실제 독립 검증이나 사람 인수와 다르다. score1–5와 completeness gate, ensemble 다수결도 모델 자격을 증명하지 않는다. Zeus에서는 실제 runner receipt와 증거 provenance, PG lease/세대, Git 정의 및 사람 핵심 시나리오를 분리한다. 실행0.

<a id="file-09"></a>
## agents/harness-explore.md

1–67 전문. sonnet, Bash 포함이지만 read-only/no-files를 산문으로 지시한다. 절대 경로·명명 변종·연결 관계는 유용한 탐색 계약이다. ALL relevant matches 주장과 2라운드 후 중단/큰 파일 outline·부분 독해는 완전성 면에서 맞지 않으며 부모의 전수 의미 검토를 이 역할 결과로 대체할 수 없다. 메시지로만 반환하는 방식은 증거 immutable handle·hash·읽은 범위가 없어 컨텍스트 유실에 취약하다. Zeus에서는 탐색 지도를 provisional로 두고 실제 전문 독해/미검토 원장과 분리한다. 원본 실행0.

<a id="file-10"></a>
## agents/harness-git-master.md

1–115 전문. sonnet, Bash로 commit/rebase/stash/cherry-pick을 수행하도록 선언한다. 파일 수에 비례한 최소 commit 수는 논리적 원자성·빌드 독립성과 다르다. git log 확인은 변경 테스트가 아니다. force-with-lease는 push 옵션인데 rebase의 사용처럼 표현되어 있고 읽은 remote ref에 결속한 lease는 없다. team merge는 DONE 뒤 worker branch 순서대로 head/range cherry-pick, 충돌 중단/원본 branch 보존을 요구한다. worker missing/already merged는 skip으로 진행해 전체 N 완료 주장과 충돌하며 base_ref가 움직이거나 worker 다중 commit 공유 조상이 달라도 정확한 commit 집합 확인이 없다. Zeus Git 정의 변경은 권한·불변 base/worker SHA·실제 통합 시험·rollback·사람 인수에 결속해야 한다. PG runtime 정본을 Git history로 대체하지 않는다. 모든 원문 Git 명령 실행0.
<a id="file-11"></a>
## agents/harness-planner.md

1–94 전문. opus/high, 읽기와 검색만 선언하며 세대당 최대7개 결정·안정 ID·구체 value·대안·citation의 의존 결정 ID를 JSON으로 요구한다. free_text 설정은 이 형식을 강제하지 않는다. rejected value를 절대 재제출하지 말라는 문구는 반증으로 기존 설계가 회복된 경우까지 막고, rationale no hedging은 명시 불확실성 보고와 긴장한다. source URL/claim은 버전·취득 hash·실제 읽은 범위를 담지 않는다. planner/critic/architect 역할 분리는 유지하되 동일 모델 계열·공유 context에서 독립 검수 자격이 성립하는지는 별도다. Zeus의 Git 요구/설계 정의와 PG 세대별 검토·미해결, 실제 인수 전 상태를 분리한다. 실행0.

<a id="file-12"></a>
## agents/harness-qa-tester.md

1–87 전문. sonnet/Bash로 psmux/tmux 서비스 시작·입력·출력 캡처·준비 poll·teardown을 수행하도록 한다. 기대/실제/명령/PASS·분모를 남기는 습관은 유지 후보다. 그러나 산문뿐인 cleanup YES는 프로세스 트리 종료 영수증이 아니고 초 단위 session 이름은 병렬 충돌할 수 있다. 출력 패턴/port readiness는 다른 프로세스나 오래된 출력도 만족할 수 있으며 서비스 identity·revision·deadline·stderr·exit code·남은 자식·포트 소유권이 없다. Windows 경로와 POSIX nc/shell, fallback serial의 실제 동등성이 미검증이다. 실제 핵심 사용자 흐름과 사람 확인을 CLI 캡처만으로 대체하지 않는다. 원본 서비스/명령 실행0.

<a id="file-13"></a>
## agents/harness-researcher.md

1–152 전문. opus와 Bash/Edit·Context7/Playwright wildcard로 조사 artifact를 작성한다. Edit만 연구 경로에 허용한다는 산문은 Bash/MCP 우회 권한을 막지 않으며 Write 없는 신규 artifact 생성 방법도 명확하지 않다. 앞에서는 threshold2 전용이라 하고 후반에는 advisory HIGH 첫 발생을 이미 확인된 결함으로 취급한다. static HIGH는 실제 결함 재현과 다르다. adv:<sha1> fingerprint는 Windows 파일명 콜론 및 consume 경로 regex와 충돌할 여지가 있다. source 연결·no_research_available·재실행 금지는 유용하지만 결과→git-master commit 주장은 소비자의 staging/escalation 정책과 대조해야 한다. normalized 외부 본문은 원문 전수 분석을 대체하지 못하고 no research의 영구 blocklist는 새 revision/지식 변화의 재검토를 막을 수 있다. Zeus는 recurrence 세대·증거 hash·유효기간·자가개선 제안과 독립 승인/인수를 분리한다. 외부 도메인/모델/anti-bot 설명은 검증된 사실로 채택하지 않았고 실행0이다.

<a id="file-14"></a>
## agents/harness-scientist.md

1–64 전문. sonnet/Bash Python 분석과 보고서/그림 저장, 설치 금지·venv·Agg·표본/효과/CI/한계를 요구한다. STAT 하나가 sample size만이어도 성공 조건을 충족하지만 본문은 모든 finding에 CI 등 모두를 요구해 오라클 강도가 다르다. 표본 수나 p값 문자열만으로 통계 가정·선택 편향·독립성·다중 비교·인과성이 검증되지 않는다. 설치 금지와 matplotlib 존재는 별도이며 미설치 명시 방어는 유지 후보다. 데이터 provenance/접근 권한·스키마·시드/분석 hash·실행 영수증은 출력 계약에 없다. Zeus에서는 분석 산출물과 모델 자격·핵심 사용자 인수/운영 승인 분리, PG 관측과 Git 분석 정의 결속이 필요하다. 실행0.

<a id="file-15"></a>
## agents/harness-tracer.md

1–98 전문. opus/Bash, 관측/추론/미지 분리·경쟁 가설·반증·통제 실험 우선·다음 구별 가능한 probe를 요구한다. 근거 강도 계층과 가짜 수렴 배제는 유지 후보지만 confidence H/M/L은 보정된 확률이 아니다. 명령 실행 권한·격리·프로브 승인·원시 영수증 결속이나 증거 재사용 무효화가 없다. probe 추천은 실제 수행이 아니며 수정하지 않는 역할 선언도 Bash를 제한하지 않는다. Zeus에서는 안전한 실행 요청과 receipt를 PG lease/세대로 결속하고 source/revision별 추론을 잠정 상태로 유지한다. 원본 probe0.

<a id="file-16"></a>
## agents/kha-advisor-researcher.md

1–106 전문. opus/Bash/웹/Context7, discuss-phase Task 호출의 회색 영역 하나를 비교표로 반환한다. 영향 범위/위험·가능한 대안만 제시하는 규칙은 유용하다. minimal_decisive는 단일 추천을 요구하지만 공통 규칙과 anti-pattern은 단일 우승자/순위를 금지한다. stars·나이·생태계는 자격/안전/현재 유지보수 증거가 아니다. 표5열+한 단락 제한에는 citation/읽은 범위/미해결 전용 필드가 없어 원문 근거가 소실될 수 있다. Zeus에서는 비교를 discovery/설계 제안으로만 받고 Git 정의/PG 검토·모델 자격/인수는 별도다. 호출명 Task의 실제 routing과 도구 whitelist는 미확인, 실행0.

<a id="file-17"></a>
## agents/kha-ai-researcher.md

1–69 전문. opus/Write/Bash/웹, AI-SPEC §2 및 §5 draft·§4 failure mode 후보를 작성하고 후속 debate가 잠근다. VERIFIED/CITED/ASSUMED 구별과 judge 역할 금지는 유지 후보다. 하지만 tool/source 태그는 실제 취득 영수증이 아니며 `.planning/` expects_paths는 권한 경계가 아니다. 병렬 section 소유 산문만으로 같은 AI-SPEC 파일의 충돌·stale write를 막지 못한다. golden_set_size≥1과 fail_rate0–1 범위만 검사해 1.0 전부 실패 허용도 가능하며 대표성/실제 모델 자격·사람 핵심 시나리오를 보장하지 않는다. artifact_path coverage는 실행/의미 검증과 분리해야 한다. lineage/approved 흡수 주장·외부 버전 사실 미검증, 원문 지시 상속/실행0.

<a id="file-18"></a>
## agents/kha-assumptions-analyzer.md

1–108 전문. opus/Bash, roadmap/context와5–15개 관련 파일을 읽고 phase 가정·틀릴 경우 결과·신뢰도를 반환한다. prior decision이 잠겼으면 Confident로 올리라는98행은 승인 상태와 사실의 참을 혼동한다. tier에 따라 path만 남기는 출력은 원문 범위/hash를 보존하지 못하고 5–15개 상한은 전체 의존성 검토가 아니다. 외부 조사 필요 표시·미독 가정 금지는 유지 후보다. Bash의 외부 도구/쓰기 권한 제한은 산문뿐이다. Zeus에서는 잠긴 사용자 결정과 실증된 사실을 별도 필드로 기록하며 실제 검증과 사람 인수 전 미해결을 유지한다. 실행0.

<a id="file-19"></a>
## agents/kha-code-fixer.md

1–552 전문. 471676의 중간 출력 절단을270–500 재독(e3e4e7)으로 보완했다. sonnet/Edit/Write/Bash, REVIEW findings를 순차 수정·개별 commit 후 REVIEW-FIX를 작성한다. dirty per-file preflight·source 재확인·fence-aware parser·멀티파일 원자 commit·skip 이유는 유지 후보다. 그러나 pre-capture 불필요/checkout atomic 주장으로 새 파일·동시 변경·index 변경·symlink·실패한 commit의 부분 staging/commit 상태를 닫지 않는다. 다른 파일 타입 오류를 pre-existing으로 추정해 무시하는 규칙은 바뀐 API가 caller 오류를 만든 경우 놓친다. 최소 검증이 수정 문구 재독이고 lint 부재도 commit 가능하므로 logic fix는 human verification 필요라고 표시하지만 결과 schema/status는 fixed/skipped 또는 all_fixed다. flow338의 모든 syntax 실패 rollback과 앞부분 fallback 예외도 상충한다. GSD commit 도구의 실제 cwd/ignore/hook/exit 처리 검토가 필요하다. Zeus에서는 격리 branch·정확 preimage·권한·독립 실제 회귀/핵심 사람 시나리오·PG receipt와 Git SHA를 묶고 fixed를 인수로 올리지 않는다. 원문 명령 실행0.

<a id="file-20"></a>
## agents/kha-code-reviewer.md

1–358 전문. sonnet/Write/Bash로 REVIEW를 작성하되 source 쓰기는 금지한다. quick는 regex만, standard는 changed file 전문, deep은 호출 추적을 요구한다. 명시 scope 없으면 fail closed, files_reviewed_list 보존, empty→skipped는 유지 후보다. lock/generated/planning/ignored 파일 제외는 전수 소스 감사와 다르고 quick clean은 의미 검토가 아니다. 시간 목표/함수50행/중첩4 같은 휴리스틱은 결함 oracle이 아니다. 위험함수 문자열을 Critical로 곧바로 분류해 오탐·실제 데이터흐름 검증 경계가 남는다. source hash/revision/읽은 구간·검사 실행·독립 모델 자격이 출력 계약에 없고 before_write hook은 주석이다. Zeus는 변경 리뷰와 전수 흡수 감사, 실제 인수를 분리하고 미검사 분모를 보존해야 한다. 실행0.

아래 원문 명령은 실행하지 않았다. 각 파일은 명시된 전 범위를 fresh read했으며 actual Claude·모델 자격·OS·라이선스·사람 인수·전체 폐쇄·Zeus 채택은 미완료다. 출력 스키마/역할 선언은 실제 강제가 아니며 필요한 직접 지원 대조는 별도 기록한다.

<a id="file-21"></a>
## agents/kha-codebase-mapper.md

1–773 전문 fresh read(ded2d4,186277). sonnet/Write/Bash, tech/arch/quality/concerns에 따라7종 지도 문서를 작성하고 짧은 확인만 반환한다. 대부분 분량은 구체 템플릿이며 생성 실행물이 아니라 이후 모델의 작성 계약이다. 실제 파일 경로·mock/실제 시험 구분·known bugs/미검사 영역·비밀 파일 읽기 금지는 유지 후보다. 하지만 head로 잘린 검색과 일부 key file 독해 뒤 Mapping Complete, not detected/not applicable 출력은 전수 분모·미독 상태를 보존하지 않는다. 날짜만 있고 source revision/hash/범위·원시 출력이 없으며 현재 관찰을 prescriptive rule로 바꾸는 과정에 승인 단계가 없다. temporal language 금지는 과거 결함/유효기간 추적을 약화한다. Write 범위는 산문이며 PostToolUse hook은 주석이다. Zeus에서는 지도를 파생 인덱스로만 두고 Git 정의/PG 실제 사건 및 전수 감사 원장을 대신하지 않게 해야 한다. 원문 명령/파일·비밀 접근0.

<a id="file-22"></a>
## agents/kha-debugger.md

1–1394 전문 fresh read(186277,bcab5f,96f97c,e864ef). opus/Write/Edit/Bash/WebSearch, 관측·반증·통제 재현·환경/회귀/안정성 확인과 지속 debug 파일을 관리한다. 최근 모드 정의는 기본 diagnose-only, fix는 hypothesis_id 명시, dirty tree 거절·실제 사용자 확인 뒤 resolved/knowledge 기록을 요구해 Zeus에 유지할 방어 후보다. 그러나 앞부분은 confirmed root cause를 단일 ROOT CAUSE FOUND로 반환하고 status diagnosed를 써서 declared status enum/resume 목록에 없는 상태가 된다. 마지막 모드는 별도 HYPOTHESIS.md/ROOT CAUSE CANDIDATES를 요구한다. fix 실패 시 investigation_loop로 돌아가라는1087행과 같은 가설 유지/실패 checkpoint인1375행이 상충한다. 기본 mutation forbidden인데 진단 기법은 logging 편집·comment-out·bisect를 지시하며 read-only 강제는 없다. 증거 append와 status/current focus overwrite는 파일 규칙뿐이며 동일 slug30자 충돌·stale write·중단된 명령/세대 lease/비밀 출력 억제가 없다. 반복 npm 시험 예시는 실패를 echo로 삼켜 shell 최종 성공이 가능하고 Promise.all 예시는 assertion이 없다. production 실행 체크리스트는 권한·격리 허가가 아니다. user confirmation도 exact code/evidence revision·시나리오·확인자 identity를 결속하지 않는다. Zeus는 Git 가설/수정 정의와 PG 실행·인수 사건을 분리하고 immutable receipt·명시 승인으로 변형해야 한다. 원문 실행/probe0, 모델/OS/라이선스·전체 closure 미완료다.
