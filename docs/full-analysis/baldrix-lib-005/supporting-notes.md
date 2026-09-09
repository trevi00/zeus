# 직접 연결 구간의 판단

supporting-evidence.json의 구간만 이번에 읽었다. 검색 결과는 전문 독해나 새 primary가 아니다. 정확한 구간 밖의 호출·설정·테스트 및 전이는 계속 미완료다.

- milestone_step.py 409~487: Tier1 green이면 변경 Python 파일 중 후보가 많은 한 파일만 변이한다. 미측정은 참고, 점수 0만 blocker, 양수는 참고다. 전체 코드 검출력이나 실제 결함 수가 아니다. 515~583: 실제 dispatch 표시 뒤 자료를 다시 조회하여 view를 만들고 files_unseen으로만 blocker를 추가한다. completeness를 outcome에 넘기지만 gate 본체는 사용하지 않는다. 보낸 바이트/모델이 읽은 바이트를 영수증으로 결속하지 않는다.
- milestone_verdict.py 160~233: 알려진 blocking ID를 먼저 전부 해석하는 방어가 있으나 actor='human'은 CLI가 붙이는 문자열이다. close는 누락된 blocking_item_ids를 []로 바꾸고 전 세대 human_verdicts와 명시 rewind-exhausted override를 받아 closure 이벤트를 기록한다. 실제 사용자 인수 권한이나 요구 전건 확인과 동등하지 않다.
- event_store.py 1~117 전문 지원: constructor가 ensure_dir를 호출하므로 MilestoneSpine을 만드는 liveness의 읽기 전용 표기는 전이 효과를 빠뜨린다. 중간 JSON 손상은 telemetry 쓰기 경로를 부르고 손상 행은 제외한다. 마지막 손상은 침묵한다. 유효 JSON의 schema/actor/hash 재검증은 없고 파일 읽기 예외도 전부 삼키지 않는다. ensure_dir/telemetry 하위 구현은 이번 범위 미독이며 supporting을 primary 완료로 승격하지 않는다.
- endpoint_query.py 70~94: provider availability 뒤 narrate_llm 결과를 grounded로 표시한다. ref membership을 문장 참으로 오해시키는 사용자 출력이다. broad exception은 deterministic fallback으로 바뀌지만 실제 모델 신뢰성 검증이 아니다.
- strike_research_consume.py 282~322: probe와 secret scan을 통과하면 candidate를 stage하고 enable-skill을 기다린다. stage와 활성화는 구분되어 있다. repro_probe.py 1~105 지원에서 Probe.passed는 무조건 True이며 재현 실행이 아니라 분류 객체 생성이다. no_degradation의 probe_passed라는 명칭을 실제 재현/회귀 인수로 흡수하면 안 된다. builder의 나머지 구간은 미독이다.
- mutation_score.py 28~74: 절대 경로나 ../ target을 허용하고 라이브 파일 복원 명령도 노출한다. 오류·낮은 점수·JSON 결과 모두 종료 0이라 CI의 성공 오라클로 쓸 수 없다. survivors가 비면 분모와 무관하게 every injected fault was caught 문구를 표시한다.
- external_jury.py 108~140: model='auto'일 때 heuristic tier를 resolve하고 오류면 provider 기본 모델로 후퇴한다. 동일 모델 자격·성능 보장이 없고 다음 provider.ask는 실제 부작용 가능 경계다.
- session/init.py 392~410, 700~739: mirror와 liveness 예외를 None으로 숨긴다. ABANDONED는 세션 경보에서 제외된다. 이는 실제 해소가 아닌 알림 정책이다. 나머지 hook registration/config는 이번 지원 독해 범위 밖이다.
- harness_health.py 350~378: metrics의 met truthiness 수를 대시보드에 내며 예외는 total_count=0으로 바뀐다. 디렉터리·행 카운트를 실증 완료율이나 인수율로 바꾸지 말아야 한다.
- greenfield_spec_emit.py 118~140: cucumber-js 분기만 node scaffolder를 호출한다. 프레임워크 선택 외 실제 npx 실행·N개 테스트/RED→GREEN 증거는 없다.
- test_mutation_runner.py 1~115: 약한 assertion과 경계 assertion의 비교는 유용한 반사실 오라클 후보다. 임시 파일을 만들고 score_module을 실행하도록 되어 있으나 이번 실행0이며 복원 실패·동시 작성자·timeout 원인 분리를 입증하지 않는다. 함수 main의 나머지 구간은 미독이다.
- test_narration.py 1~111: substring 렌더, ref 소속, FakeProvider를 검사한다. 유효 ref에 거짓 문장을 붙인 경우는 읽은 테스트에 없고 실제 LLM 인수가 아니다. 나머지 테스트는 미독이다.
- test_no_degradation_gate.py 1~85 전문 지원: Probe를 직접 생성하고 True/False secret 플래그를 검사한다. malformed 후보와 예외를 다루지만 unused bad 객체는 실제 검사하지 않는다. 실제 재현이나 수정 효과/모델 자격을 검사하지 않는다.

설정 연결은 기본 CAP/시간/경로·모델 표 및 읽은 CLI 옵션에 한정한다. 외부 license/vendor 문서와 Windows/Linux/WSL 동작, 전체 actual Claude 검토, Zeus 구현 동등성은 미확인이다.
