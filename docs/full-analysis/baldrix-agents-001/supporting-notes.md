# 직접 연결부 정적 검토

<a id="support-all"></a>
모든 지원은 이번에 직접 읽은 구간이다. 정확한 파일별 구간·원시 Git blob·bytes·SHA 및 primary 연결은 supporting-evidence.json에 기록한다. 미기재 본문과 전이 의존은 미검토이며 검색 hit는 독해로 계상하지 않는다. 아래 번호는 support-specs.json 순서다. 원본 실행은 0이다.

1. harness-interview 1–36: analyst 명명 호출과 반환 후 invocation 기록 지시가 있다. sid는 step0에서 만들었다고 설명하지만 읽은 프로토콜은 step1부터다. 전체 명령에서 누락되었다는 결론은 보류한다.
2. harness-debate 24–85: planner에게 3–5개 발췌문을 files_to_read로 주는 계약이 모호하다. fastpath는 critic을 건너뛸 수 있고, cross-provider jury는 기본 꺼짐·advisory이며 수렴을 바꾸지 않는다. CLI 반환코드 분기는 있지만 해당 CLI 본문은 이번 지원 범위 밖이다.
3. harness-ultrawork 16–36: explore 명명 호출과 반환 후 기록을 요구한다. 선언은 실제 호출 영수증이 아니다.
4. harness-team 209–236: DONE worker의 전용 branch들을 git-master로 합치고 QA/tracer를 연결한다. branch 누락·부분 완료와 전체 인수의 폐쇄는 없다.
5. evaluator_dispatcher 201–277,307–385,473–588: 역할 MD를 읽는 대신 정적 prompt template을 사용한다. 허용 경로 설명은 OS capability가 아니다. codex read-only 옵션에도 cwd를 격리하지 않고 HOME/USERPROFILE/APPDATA 등 환경을 남긴다. Windows cmd shell 분기와 POSIX argv가 다르며 timeout 후 자손 종료는 이 구간에서 보장하지 않는다. JSON 관용 추출과 ledger 기록 예외 무시는 엄격한 완료 영수증이 아니다. 호출자 선행 조건 전체는 미확인이다.
6. discuss-phase 550–590: advisor MD를 먼저 읽으라고 하지만 실제 Task 유형은 general-purpose다. 명명된 역할의 도구 제한 적용을 추정할 수 없다. 부모가 빠진 열을 채우고 선택지를 줄이며 결과를 다시 써 독립 원본 보존 여부도 별도 확인해야 한다.
7. discuss-phase-assumptions 245–330: assumptions-analyzer 명명 Task와 사용자 프로필별 깊이 조절, 외부 조사는 general-purpose로 연결된다. confidence 변경은 실제 원문 검증·모델 자격 영수증을 대신하지 못한다.
8. code-review-fix 178–241: fixer Task 실패 때 No fixes applied라지만 일부 commit이 있을 수 있다고도 안내한다. 부분 부작용을 정확히 수집해야 한다.
9. code-review 347–406: Task 실패를 No REVIEW created로 해석해 부분 파일 가능성을 놓친다. LF frontmatter 정규식과 임의 status 문자열 존재 검사는 schema·허용 상태·revision 검증이 아니며 CRLF에서도 차이가 가능하다.
10. map-codebase 99–131,198–245: mapper 명명 Task와 제한시간 결과 수집을 읽었다. 실패한 일부 worker가 있어도 기존 생성 문서로 계속할 수 있고 Task 없는 fallback은 같은 문맥의 순차 작업이다. 다른 spawn과 후속 신선도 검사는 미독이다.
11. diagnose-issues 85–146: diagnose-only prompt의 FIRST ACTION이 merge-base/reset --soft로 기본 mutation 금지 및 Read-first와 충돌한다. goal 문자열 find_root_cause_only도 역할의 복수형과 다르다. 실행하지 않았다.
12. kha-ai-integration-phase 118–148: wave 병렬 researcher, AI-SPEC 섹션 분업 뒤 advisory validator WARN에도 locked로 진행한다. 1byte stub 허용과 제품 golden 실행의 사용자 CI 이관은 이 단계가 실제 AI 기능 인수가 아님을 보여 준다.
13. design-critic-gate 16–75: 독립 Agent가 불가하면 inline 자체 채점으로 대체한다. 여기서는 실 screenshot을 요구해 역할의 code-only 저신뢰 경로보다 엄격하다. 예외 정당화 권한과 수정 후 재검수 폐쇄는 부족하다.
14. external-context 47–77: 산문은 Task, 예시는 Agent다. Context7 필수 설명은 역할 frontmatter의 미선언 도구 문제를 해결하지 않는다. 병렬 상한은 실제 수집 영수증이 아니다.
15. ultraqa 29–57: QA 실패에 architect의 원인 진단·수정 제안을 요청하지만 역할은 제안 심사 전용이라고 한다. 역할 계약이 호출 목적과 다르다.
16. trace 24–116: 세 팀 lane과 반증 가설 분리는 유용하나 읽은 구간에 tracer의 정확한 subagent_type 명명 연결이 없어 실제 라우팅은 미확인이다.
17. requesting-code-review 181–204: simplifier/architect/reviewer 매핑 표는 발견 근거다. simplifier는 변경 도구를 가진 역할이므로 표의 검토 이름만으로 읽기 전용이 되지 않는다. 실제 dispatch 폐쇄는 아니다.
18. test_subagent_isolation_contract 59–137: frontmatter 도구 문자열과 비어 있지 않음을 검사한다. 문서의 금지 경로 5개 설명에 비해 테스트는 3개 문자열을 파일 어디서든 찾는다. 실제 filesystem 격리나 cross-provider 실행은 검사하지 않는다.
19. test_commands_wiring 132–152: record_invocation과 역할 문자열 존재 검사다. 실제 dispatch·실패 전파 검증은 아니다.
20. test_agent_tool_audit 40–97: MD 도구 이름과 합성 frontmatter 예제를 검사한다. 실제 도구 사용 가능성·권한 위반 차단은 별개다.
21. commands.cjs 222–347: commit_docs=false 또는 planning ignored면 일반 source fix도 committed:false로 건너뛴다. branch fallback checkout 및 개별 stage 반환 실패를 강제하지 않고 전체 index commit은 관련 없는 staged 변경을 포함할 수 있다. commit 실패도 nothing_to_commit 이유로 반환한다. fixer의 rev-parse HEAD가 이전 commit을 새 수정으로 오인할 수 있다. output helper의 실제 process exit와 전체 호출자는 미독이다.
22. core.cjs 1291–1339: model override가 우선이고 unknown agent는 전체 alias 변환 전에 sonnet으로 반환한다. 역할 frontmatter 모델을 여기서 읽지 않는다. 명칭은 공급자 모델 자격 검증이 아니다.
23. model-profiles.cjs 1–70 전문: 16개 등록 표의 debugger balanced sonnet, mapper balanced haiku는 역할 MD의 opus/sonnet과 다르다. advisor/AI/assumptions/fixer/reviewer 미등록은 override 없을 때 fallback 경로로 간다.
24. advisory_research_dispatch 42–88: adv:12hex 키를 만들고 HIGH는 첫 발생에도 연구를 보낸다. 읽은 blocklist에는 만료가 보이지 않는다. 반복 임계만 허용한다는 역할 규칙과 다르다.
25. strike_research_consume 60–70,211–285: id 정규식은 colon을 거부해 adv 키와 형식이 다르다. 이 consumer까지 advisory가 연결되는 전체 경로는 미완료다. settings/hooks는 자동 escalation 제외라 역할의 git-master 일반 설명을 그대로 신뢰할 수 없다.
26. agent_tool_audit 33–105: comma 분리 도구 표이며 wildcard 확장·실제 enforcement가 없다. 선언 누락이면 일부 검사도 빈 결과다. 도구 감사 이름이 권한 강제를 뜻하지 않는다.
27. agent_invocation_audit 165–230: Agent만 처리하고 유형 누락은 skip, 선언 도구를 기록한다. Task 호출과 실제 실행 도구 영수증은 대상이 아니며 telemetry/기록 실패는 조용히 끝난다.
28. settings.json 243–252: Agent matcher와 특정 Windows 절대 경로·5초 timeout 설정이다. 설치·Linux/WSL 변환·성공 호출 영수증은 없다. 설정 명령을 실행하지 않았다.
29. gsd-tools.cjs 444–466: resolve-model 및 commit 옵션을 파싱해 위 함수로 전달한다. no-verify 등 옵션의 존재는 승인 정책이 아니다.

추가 탐색에서 agent_output_contract.py와 agent_output_schema.py 예상 경로는 없었다. 이 결과를 validator 부재의 전역 증명으로 쓰지 않는다. scientist 직접 호출, simplifier/designer 실제 dispatch, tracer 정확한 라우팅은 확인하지 못했다. 연구 논문·vendor·외부 링크·라이선스 원문 확인과 실제 모델/OS/사람 인수는 전부 미완료다.
