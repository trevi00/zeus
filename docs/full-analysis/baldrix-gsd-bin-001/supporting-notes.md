# 직접 지원의 실제 읽은 범위

<a id="support-all"></a>
6개 지원 파일을 새로 읽었으며 이전 지원 독해를 재사용하지 않았다. raw Git blob·bytes·SHA와 각 범위 SHA는 supporting-evidence.json에 결속한다. 지원은 전역 primary 완료 증가가 아니며 원본 실행은 0이다.

merge-back.cjs 1–267행 전문(a42d08)은 primary 시험의 직접 SUT다. preMergeHead를 각 worktree merge 전에 잡고 detached SHA의 ancestor 확인, blob 기반 drift 검사, non-amend reconcile을 하는 방어가 있다. 하지만 expectedBase 옵션은 문서와 CLI가 전달해도 **사용하지 않는다**. 모든 linked worktree를 열거해 임무 소유 여부 없이 merge하고 강제 제거/branch -D를 한다. dirty/활성 worker/lease 확인은 없다. rm·checkout·add 실패를 무시하고 reconcile commit 실패 뒤에도 cleanup과 merged=true로 간다. removed와 branch_deleted는 별도 flags지만 merged의 필수 조건이 아니며 summary/plan 존재도 필수 조건이 아니다. 충돌은 abort 실패 자체를 확인하지 않고 해당 worktree를 남기지만 이후 worker를 계속 처리한다. 순차 처리라 원자 transaction이라는 주석은 보장되지 않는다. code SHA는 마지막 SUMMARY 커밋이 .planning만 변경했을 때 단 한 parent를 고르는 휴리스틱으로, 복수 docs-only tip이나 root/merge 커밋 전체 의미는 닫히지 않는다. source 주장 debate/승인 원문은 미확인이다.

model-profiles.cjs 1–70행 전문(a42d08)은 kha-* 17역할의 quality/balanced/budget/adaptive 표다. VALID_PROFILES는 planner 키에서 만들므로 inherit는 dedicated config에서 거부되지만 core는 지원한다. 표 문자열은 실제 가용 모델·권한·정확 revision·자격 시험의 증거가 아니다. 모르는 profile 조회는 각 역할 undefined로 돌아가고 별도 검증은 없다. display table은 값이 문자열이라는 가정이며 원본 실행은 하지 않았다.

docs-update.md 1–65행(a42d08)은 HOME/.claude의 Node docs-init와 agent-skills를 Bash로 호출하고 @file 결과를 cat한다. source `doc_writer_model`로 Agent를 배정한다는 선언과 프로젝트 분류·문서 queue 생성이며 실제 dispatch/verification receipt는 아니다. marker·LICENSE 존재·has_tests 신호를 인수 상태로 승격하면 안 된다. 문서 66행 이후의 생성·검증 전체 흐름은 이번 지원 범위 밖이다.

verify.cjs 272–390행(267b3d)은 이전 함수의 hashes total/invalid 비교 tail와 cmdVerifyArtifacts 전체, cmdVerifyKeyLinks의 집계 직전까지다. artifact 원문 배열의 문자열/path 없는 항목을 skip해서 결과가 비어도 0===0으로 all_passed가 될 수 있다. key link의 빈 to는 includes('') true, regex가 target에만 있어도 통과하며 실제 의존 호출 효과를 보장하지 않는다. 391행 이후를 읽었다고 계상하지 않았다. 형식·파일 존재·문자열 검사는 SDD의 실제 실행·사람 인수와 다르다.

quick.md 615–660행(267b3d)은 worktree executor 뒤 expected-base를 전달하고 conflict JSON은 정상 merge로 취급하지 말라는 caller 선언이다. CLI는 expectedBase를 전달하지만 SUT는 무시한다. 문서는 특정 런타임 오류를 SUMMARY/commit 존재로 성공 처리하라고 하며 FULL_MODE=false나 config false면 code review를 skip한다. 이는 검수·실패 원인·사람 인수를 완성하지 못한다. 실제 Claude 버그라는 외부 주장은 원문 데이터이며 검증하지 않았다. Bash/Claude HOME 경로는 Windows/WSL 포팅 전제가 다르다.

security.cjs 1–503행 전문(e181b3)은 commands가 쓰는 sanitizeForPrompt와 CLI safeJsonParse의 직접 지원이다. canonical path containment·절대경로 opt-in·NUL 거부는 유용하지만 대상과 부모 둘 다 미존재면 더 높은 symlink ancestor를 확인하지 않고 check/use 경쟁과 Windows case 차이도 남는다. 더구나 primary의 path 명령과 frontmatter CRUD는 이 helper를 사용하지 않는다. 영어 injection 패턴과 entropy/태그 heuristic은 데이터/지시 권한 경계가 아니며 non-string을 clean으로 취급한다. sanitizer는 일부 문자/태그만 바꾸고 안전 승인이나 shell escaping을 하지 않는다. validateShellArg도 NUL와 일부 substitution만 거부한다. safeJsonParse는 1MiB라고 쓰지만 JS 문자 수이며 구조/깊이/키 schema를 검증하지 않는다. prompt structure는 opening tag 이름만 보고 닫힘·중첩·속성을 검사하지 않는다. entropy는 for-of code point 개수와 UTF-16 length 분모가 달라 supplementary 문자를 정확한 확률로 다루지 못하며 다국어/정상 데이터 오탐이 미검사다. helper 존재를 전체 호출 경로의 강제 방어로 주장하지 않는다.

Primary 간 직접 연결은 이미 fresh 전문에 포함된다: CLI 159–177행 eager imports, 474–478행 merge-back, 523–538행 frontmatter 분기, 1017행 docs-init; commands 7–9행 core/frontmatter/model-profiles, 258행 sanitizer; docs 11행 core, 248–264행 소비; frontmatter 7행 core. 이 구간은 중복 primary나 별도 신규 지원 파일로 세지 않는다. merge-back.test.cjs의 13개 node:test 본문은 읽었지만 collector/CI/package 설정 전체와 다른 core/config/docs/frontmatter 회귀시험은 미확인이다. 좁은 filename 검색 결과 부재를 시험 전체 부재로 확대하지 않았다.
