# lib007 정적 전문 검토

고정 revision `cbb5c3e6c9c4af6f86626474f4d7d62fd8e8a6d2`의 21개, 197444바이트를 모두 전문 독해했다. 선행 전문이 있는 4개도 새로 재독했으며 전역 신규 coverage와 구분한다. 실행·import·프로브·설치·네트워크·테스트 실행은 0회다.

가장 큰 차이는 관찰·문구와 검증의 구분이다. research_extractor와 resident_store는 JSON dict가 파싱되면 schema와 실제 업무 성과를 검사하지 않고 structured/contract_ok로 인정한다. research_provenance의 URL 존재는 원문 취득이나 새 사실 발견을 입증하지 않는다. router_eval은 점수 임계값을 세므로 실제 본문 주입·잘림·포인터 잡음을 모두 검증하지 못한다. 빈 lint 표본도 P1-ready가 될 수 있다.

쓰기·보존 경계도 그대로 흡수할 수 없다. skill_candidate_detector는 고정 ~/.claude 경로, 성공과 무관한 반복 집계, 느슨한 candidate ID, 분리된 JSON/MD 쓰기와 scan-before-write 미강제 경로를 가진다. pure라 설명한 reflection adapter가 insight index를 쓴다. resident compaction은 원본 내용의 불변 hash와 동시 append/GC 결속이 없고, rewind는 실제 작업 트리 rollback이 아닌 이벤트 fork다. settings_guard는 좁은 구조 검사 방어가 있지만 vendor 정책의 실효성과 별도 쓰기 CAS·복원 검증은 미완료다.

보존 후보는 역할별 조사 범위와 표시 생략 분모, 권한 변경의 좁은 허용 조건, 원본 parent 보존, 후보와 활성화 분리다. Zeus에서는 Git 정의와 PG 정본의 generation·lease·CAS, immutable artifact, 독립 승인과 실제 인수 영수증으로 변형해야 한다. reminder·모델 판정·반복 횟수·형식 lint는 사용자의 8단계 SDD와 no-mocked acceptance를 대신하지 않는다.

[파일별 검토](file-reviews.md), [직접 연결](supporting-notes.md), [진척](checkpoint.json), [선행 중복 결속](prior-overlap.json)을 참조한다. 전이 caller/config/test 폐쇄, 라이선스·외부 원문, 실제 모델·OS, 전체 actual Claude 공동 검토와 채택은 pending이다. 본문 독해 완료는 전체 분석 완료나 흡수 승인이 아니다.
