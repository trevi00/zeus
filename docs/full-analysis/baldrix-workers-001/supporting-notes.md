# 직접 지원 독해

- scripts/tests/test_workers.py 1~181 전문: mock registry 선택/실패와 실제 Popen sleep를 시작하도록 작성한 spawn/list/duplicate/kill roundtrip이다. 본문에 실제 실행 코드가 있는 것과 이번 실행 영수증은 별개이며 실행0이다. main은 _PASS/_FAIL assertion 수를 세고 예외도 failure로 기록한다. 기능별 분모와 출력 결과/프로세스 트리/세대 fencing 오라클은 별도 필요하다.
- scripts/tests/test_psmux.py 1~230: import 대상은 lib.psmux로 이 partition의 workers.psmux_adapter가 아니다. 설치 안 된 경우 다수 테스트가 그냥 return하므로 pytest 관점에서 skip로 자동 집계되지 않을 수 있다. typed marker가 pane에 나타나는 것은 명령 실행 결과가 아니라 화면 echo일 수 있다. cleanup은 예외를 무시한다. 나머지 231~342 및 lib.psmux 구현은 이번 미독이므로 직접 adapter 실행 검증으로 승격하지 않는다.
- commands/harness-team.md 20~65: detect_best를 고르라고 하지만 실제 launch 지시는 nohup bash wrapper다. worker transcript/heartbeat와 DONE marker 관찰은 명령 문서의 의도이지 실행 코드 연결 또는 실제 성공 receipt가 아니다. Claude TaskCreate/ORCH_SID/.omc/.claude 경로와 Bash/nohup/tail 가정이 존재한다. source 명령은 실행하지 않았다.
- commands/harness-ultrawork.md 98~108: 재분해가 비결정적이고 resume first-class 아님을 명시하며 내부 Agent를 사용한다고 적는다. test_workers doc의 모든 team+ultrawork pane이 worker registry를 쓴다는 주장과 상충한다. 이 두 문서만으로 실제 실행 closure를 확정하지 않는다.

정확 lib.workers 문자열의 Python 검색은 주로 테스트와 다른 registry 설명 주석을 찾았다. import alias, 동적 호출 및 문서가 생성하는 wrapper는 완전히 닫지 못했다. 넓은 후보 검색의 잘린 출력(e931a9)은 독해 coverage에 넣지 않았다. backend 외부 원문, 설치 자격, 실제 모델/OS 및 인수 미확인. 지원은 모두 이번 새 독해이나 전역 primary를 추가하지 않는다.
