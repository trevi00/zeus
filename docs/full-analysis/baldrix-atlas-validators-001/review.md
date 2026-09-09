# Atlas validator 문서 한정 검토

두 파티션의 **38개, 84,994바이트를 모두 새로 전문 독해**했다. 28개 artifact 카드는 반복 형식이지만 각각 실제 대상과 주장 차이를 검토했으며 생성/중복으로 면제하지 않았다. 동일 바이트의 이전 구현 전문 29개를 명시적으로 재사용하고 새 직접 지원 10파일의 범위를 별도 기록했다. 원본 revision은 `cbb5c3e6c9c4af6f86626474f4d7d62fd8e8a6d2`다.

가장 큰 문제는 문서가 실제 검사를 넓게 표현한다는 점이다. schema·동작·coverage 검사라고 소개한 카드 중 다수는 정규식, 단어, 파일 수나 존재를 검사한다. `test` 카드는 실제 run_units 최소 case 검증과 다르고, `collab`의 HANDOFF/SUMMARY 설명도 구현 대상과 다르다. 누락·읽기 오류·빈 분모가 PASS에 섞이는 경로를 파일별로 남겼다.

등록이 곧 매 cycle 실제 hard gate라는 주장도 성립하지 않는다. 문서의 정렬된 27개 snapshot과 달리 pinned registry는 builtin37개에 graduated를 붙이며 정렬도 달라졌다. CI는 경로 필터와 Ubuntu 범위를 갖고 atlas skip을 허용한다. run_all은 대응 테스트의 결과를 집계하며 skip이 있어도 실패가 없으면 exit0이다. 등록·스케줄·실행·판정·승인은 별개다.

ModuleSpec whitelist라는 설명은 실제 runtime의 forbidden-prefix 검사와 unknown caller fail-open을 과장한다. staging guard는 ModuleSpec 신원이 아니라 경로 containment를 검사하며 모든 쓰기를 가로채지 않고 호출자에게 SHOULD 계약을 둔다. 역사 문서의 토론 승인·동일 hash·0위반·p99 성공은 원시 이벤트·환경·실행 영수증을 확인하지 않아 현재 검증으로 승격하지 않았다.

새로 읽은 테스트 두 파일은 frontmatter 6개와 staging guard 7개 함수다. 후자의 일부 함수는 실패를 print만 하고 수동 main은 예외만 합산한다. **원본 실행·import·collection·probe·network·설치·실제 Claude는 모두 0**이다. 자체 기록 검사는 원본의 행동 PASS가 아니다.

Zeus 변형 후보는 Git의 8단계 정의와 PG의 실행 시도·검사 분모·자격·실제 사람 인수·증거를 연결하는 방식으로 제한한다. 원본 Atlas 카드는 탐색/설명 자료이며 권한·완료 정본이 아니다. 전체 호출·설정·시험 전이 폐쇄, 라이선스, Windows/Linux/WSL, 실제 모델 자격, 사람 핵심 시나리오, 공동 검토와 채택은 미완료다. 소유 폴더 밖의 source/runtime/coverage/ticket/stage/commit/push는 변경하지 않았다.
