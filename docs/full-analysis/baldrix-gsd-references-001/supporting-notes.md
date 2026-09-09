# 직접 지원 검토

<a id="support-all"></a>
20개 지원 파일의 명시 구간을 이번에 새로 읽었다. supporting-evidence.json의 원시 blob·bytes·SHA·구간 hash와 각 primary 연결이 정본이다. 아래 번호는 support-specs 순서다. 일부 구간은 이전 partition에서도 다루었지만 이번에는 직접 재독했으며 지원을 전역 primary로 올리지 않는다. 소스 실행·시험0.

1. execute-phase1–36,350–390: agent-contracts/context-budget/gates를 요구하고 executor에게 checkpoints/tdd를 전달한다. Task 없는 runtime의 inline fallback과 완료 신호 미수신 시 SUMMARY/commit spot-check 성공 추정은 독립 실행 receipt와 다르다. rebase 실패를 `|| true`로 삼킨 뒤 reset --soft를 지시하고 parallel --no-verify를 반복한다. 후속 hook 검사·worker 종료는 미독이다.
2. plan-phase1–25: UI/revision/gate/agent-contracts를 명시 include하고 Research→Plan→Verify→Done을 선언한다. 실제 loop·상태 parser 전체는 미독으로 남긴다.
3. execute-plan1–18,226–252,316–355: git-integration/tdd/checkpoints 직접 소비. empty suite 검증과 parallel hook 우회를 반복한다. checkpoint 실제 응답 대기는 reference auto 승인 예외와 함께 해석해야 한다. config-get 실패 시 node_repair=true fallback으로 RETRY/DECOMPOSE/PRUNE 자동 경로가 열리며 skip은 incomplete로 기록하라고 한다. repair의 실효·최종 분모는 미확인이다.
4. debugger958–992: thinking-debug를 사용하고 knowledge keyword2개 매칭은 가설 후보로만 취급하며 관련 파일 전문 독해·실제 관측을 요구한다. common-bug-patterns는 초기 증거 뒤 candidate 생성에 사용하므로 빈도 주장이 실제 diagnosis가 되는 것은 아니다. 원문 실행은 하지 않았다.
5. resume-project1–25: continuation-format 직접 include와 init resume/@file 경로 읽기다. 즉시 full context 복원을 주장하지만 이 구간에는 immutable handoff/hash·세대 검증이 없다.
6. discuss-phase1–20,550–575,603–634: universal-anti-patterns를 include하면서 advisor를 general-purpose Task로 띄우고 역할 MD를 직접 읽힌다. 원문의 non-KHA 금지/역할 MD 금지와 같은 workflow 안에서 충돌한다. 선택을 locked로 기록한 뒤 thinking partner가 before lock 질문을 하는 순서도 모호하다. 신호·3–5bullet은 실제 extended-thinking 모델 설정이 아니다.
7. plan-checker25–36,81–105: gates/fewshot/planning reasoning 직접 소비. 계획 WILL 달성이라는 주장은 실행 전 예측이며 requirement ID가 frontmatter에 최소1개 나타나는 검사도 의미·실제 인수를 증명하지 못한다. 나머지 dimension과 실행은 미독이다.
8. verifier52–108: 존재/실질/연결 distinction과 fewshot/verification reasoning 연결. 이전 gaps가 있으면 passed item은 existence/basic sanity로만 재검사해 source 변화에 결속한 재승인 폐쇄가 없다. REQUIREMENTS grep의 `^| ...`는 모든 줄을 매칭할 수 있다. 전체 출력/후속 성공 판단은 미독이다.
9. research-phase1–55: model-profile-resolution/phase-argument 직접 include. found false만 실패로 다루고 기존 RESEARCH 경로는 prefix 없는 파일명, init phase-op은 별도 조회다. 실제 실패/빈출력 처리·최종 Task 완료는 미독이다.
10. model-profiles.cjs1–70 전문:17개 역할 표와 표 생성기가 있다. reference는12개만 다루므로 전체 동등한 자동 생성물은 아니다. VALID_PROFILES는 planner의4개 key만 가져오며 inherit는 여기 표에서 다루지 않는다. 잘못된 profile의 formatter는 undefined를 넘길 수 있으나 호출자 검증은 미독이다. mapper 표가 실제 역할 자격 평가라는 증거는 없다.
11. planner876–924,1025–1042: gap/revision/reviews를 조건부로 읽고 standard에는 안 읽는다. STATE가 없으면 continue without을 허용한다. thinking-planning 호출과 LOW/HIGH 설정은 선언적 계약이며 실제 독립 검수는 아니다.
12. explore1–50: questioning/domain-probes 직접 소비와2–5교환,영어 tradeoff 신호를 사용한다. 질문 후보 선택이 전체 요구 분모 검토와 같지 않다. thinking-partner의 #1729 예정 연결과 여기 explore 존재만으로 해당 기능이 구현되었다고 단정하지 않는다.
13. executor104–123,222–277: 완료 commit 존재를 확인해 이어가고 auth 오류를 gate로 분류한다. auto config는 workflow chain/auto_advance에서 읽어 yolo만 쓰라는 universal 문서와 다르다. human-verify 자동 승인·decision 첫 선택은 이 실제 역할 소비부에도 존재한다. chain/Cfg를 합친 결과를 저장하라는 산문과 아래 AUTO_CFG 변수 표현은 명확한 실행 코드가 아니다.
14. phase-researcher453–484: research reasoning 직접 include,30/7일 validity 추정과 요구 ID·init/config를 사용한다. 기간·confidence는 취득 원문/실제 모델 검증을 대신하지 않는다.
15. core225–405,874–900,1002–1065,1291–1339: loadConfig는 depth/subrepos migration을 쓰고 예외를 무시하며 invalid JSON일 때 null이 아니라 defaults를 반환한다. subrepo 동기화는 기존 목록과 detected가 모두 nonempty일 때만 갱신해 전체 삭제는 제거되지 않는다. context_window만 읽고 context_window_tokens는 없다. 명시 commit_docs는 load에서 우선하나 cmdCommit은 ignore를 다시 차단한다. normalizePhaseName regex는 prefix만 맞추고 trailing junk를 버릴 수 있으며 custom ID는 그대로 반환한다. archive 탐색 newest는 문자열 역순이라 숫자 version 순서와 다를 수 있다. 모델 기본 resolve는 opus alias 그대로 반환하고 truthy resolve_model_ids만 full ID로 바꾼다. 따라서 reference의 opus→inherit 일반 주장은 구현과 다르다. unknown agent는 inherit 분기보다 먼저 sonnet으로 돌아간다. 전이 helpers/OS/모델 자격은 미완료다.
16. commands243–347: commit_docs false/ignore는 파일 유형과 무관하게 skip, stage 및 checkout fallback 실패는 별도 강제하지 않는다. --amend는 기존 index·기존 commit을 바꾸며 오류도 raw nothing으로 반환할 수 있다. --no-verify를 실제 argv에 넣는다. 성공은 short hash만 기록해 full evidence identity가 아니다. output/execGit/security의 전이 본문은 미독이며 실제 실패 exit는 미실행이다.
17. phase87–210: next-decimal은 base 미존재에도 next를 반환하고 readonly 계산이라 예약/중복 방지가 없다. normalized를 escape하지 않은 regex에 넣고 첫 소수 segment를 parse해 중첩 decimal/custom ID 처리에 모호함이 있다. find-phase는 directory를 절대경로라고 설명한 reference와 달리 cwd 상대 POSIX path로 반환한다. 읽기 예외를 notFound로 합치고 PLAN.md/SUMMARY.md 단독명도 허용해 universal의 exact pattern 필수와 다르다. 파일 내용/실제 phase goal 검증은 아니다.
18. gsd-tools660–671: next-decimal 명령을 위 함수로 전달하는 직접 entry다. --pick 공통 처리와 전체 argv 검증은 미독이다.
19. config1–62: VALID_CONFIG_KEYS에 context는 있으나 context_window/resolve_model_ids는 없고 core는 별도 internal key로 허용한다. features 동적 namespace는 임의 이름을 허용해 feature 존재를 검증하지 않는다. 생성기나 완전한 schema와 문서의 동등성은 입증되지 않았다.
20. pause-work160–178: METHODOLOGY를 required reading 템플릿에 넣는 실제 소비 연결을 확인했다. 내용 적용·결정 진실성·immutable evidence 보존은 별개다.

정확 경로 탐색에서 tests/ 디렉터리와 get-shit-done/bin/lib/config-schema.json은 없었다. scripts/tests의 reference basename/next-decimal/checkpoints/model-profiles/planning-config 문자열에서는 직접 관련 시험 연결을 찾지 못했다. 이는 전역 시험 부재 증명이 아니다. 시험 전문을 읽거나 실행했다고 계상하지 않았다. artifact-types/decimal/git-planning-commit/planning-config의 직접 문서 include도 지정 탐색 범위에서 확인되지 않아 구현/선언 관계와 실제 include를 구분한다. 원문 vendor/catalog/외부 링크·라이선스, 전체 caller/config/시험/인수 폐쇄는 남아 있다.
