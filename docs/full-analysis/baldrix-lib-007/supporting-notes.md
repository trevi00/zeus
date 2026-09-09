# 직접 연결과 미완료

supporting-evidence.json에 실제 읽은 범위와 raw 구간 SHA를 기록한다. 검색 hit는 독해 범위가 아니다. primary끼리의 roles→각 role, router_eval→skill_score, lint report/shape 연결은 전문 독해 범위다.

- cli/role.py 35~115: role.survey와 prompt를 호출해 resident enqueue로 넘긴다. 조사 []이면 판단할 것 없음으로 건너뛰며 DBA/보안에도 예산 초과 없음 문구를 쓰는 불일치가 있다. dry-run도 survey의 I/O는 이미 실행한다. 검토된 4역할의 제안은 enqueue일 뿐 인수·적용이 아니다.
- cli/resident.py 70~91: resident_store 함수의 재export를 확인했다. 실제 append/compaction 실행부와 worker 종료·수거의 전이 폐쇄는 이번 미독이다.
- cli/router_eval.py 30~100: 빈 시나리오는 EXIT_NOTHING으로 막지만 baseline이 없거나 {}면 회귀 없음으로 처리하고 --record-baseline은 실패 결과도 새 기준으로 덮어써0이다. 본문 나머지 종료 경로는 이번 읽지 않았다.
- post_tool/skill_candidate_extractor.py 1~54 전문 지원: env 정확히1일 때만 stdin을 넘기고 장애를0으로 삼킨다. 활성화 등록 상태는 읽지 않았다. 실제 enable-skill 승격 권한은 이 dispatch와 다르다.
- post_tool/reviewer.py 610~627, 681~708: Write/Edit/MultiEdit markdown·content-change 조건에서 telemetry만 호출하고 cooldown 아래 review reminder를 additionalContext에 붙인다. 결과는 실제 검증이 아닌 지시형 문구다. 실패는0으로 사라진다.
- prompt/skill_match.py 430~471, 536~573: 별도 body cap/truncation과 full/pointer가 있고 cross references는 그 뒤 추가된다. router_eval의 score threshold 집계가 실제 renderer 전 범위를 대체하지 못한다. 전이 budget 설정·collector는 미독이다.
- pending_changes.py 543~572: settings_guard.remove_rule를 적용 함수가 부른다. canary는 headless 응답의 BLOCKED 존재/WROTE 부재와 경고 문구 부재를 bool로 취급한다. 읽은 부분에는 실제 권한 거절 영수증·파일 미변경 대조가 없다. 실제 실행0이고 보호 경로 probe를 재시도하지 않았다.
- promote_skill.py 264~295: structure_depth는 경고4건 표시와 broad exception만 있고 promotion을 막지 않는다. depth bar라는 명칭과 실제 승격 방어를 구분해야 한다.
- engine/debate.py 72~91: similarity는 similarity_log 이벤트로 기록하며 이 함수는 convergence를 판정하지 않는다. 모든 소비자가 비차단인지 전이 폐쇄는 별도다.
- greenfield_spec_emit.py 128~140: cucumber-rs 선택일 때 Rust scaffolder를 호출한다. 생성 결과가 실제 cargo 실행에 도달했는지는 미검증이다.
- debate_aggregate.py 640~692: citation provenance는 최소 표본 조건 아래 숨겨지고 advisory라고 명시하지만 citation_grounded/discovery라는 문구를 붙인다. 인용 문자열 존재가 원문 취득·검증을 뜻하지 않는다.
- test_settings_guard.py 1~95: 같은 Edit 경로 존속과 다른 도구/경로/allow/없는rule 거절 assertions를 읽었다. 실제 쓰기 테스트는 시작만 포함되어 body 전부를 읽었다고 주장하지 않는다. vendor policy 효과나 실제 headless 인수는 아니다.
- test_research_extractor.py 1~95: env 경계와 JSON object/fence parser assertions를 읽었다. 원 env값을 pop하는 테스트여서 live환경에서 실행하면 상태를 바꿀 수 있다. FakeProvider 정의 시작만 읽었고 실제 모델 테스트가 아니다.
- agents/harness-researcher.md 136~148: extract_structured는 agent 문서상 호출 계약이다. 이번 구체 Python caller 검색에서 운영 호출을 확인하지 못했다. 문서 권한/원문을 요약만 보라는 규율은 Zeus 전수 전문 독해를 대체하지 않는다.
- commands/harness-reverse-prd.md 72~86: checkpoint는 4릴리즈 문서의 imperative 호출 계약이다. 실제 자동 연결/실행 영수증은 미확인이다. spec_bundle advisory와 test stub round-trip이 실제 SDD 인수가 아니다.

rewind_session은 좁힌 Python 검색에서 primary의 selfcheck 외 외부 호출을 찾지 못했다. 미등록/미사용으로 확정하지 않고 다른 dynamic/doc caller를 pending으로 남긴다. 실제 설정 파일, 외부 라이선스·vendor 원문, Windows/Linux/WSL 실행, 전체 actual Claude 및 Zeus 채택은 미확인이다. 모든 source/import/probe/test/network/install 실행0.
