# workers 전문 정적 독해

4개 새 전문, 선행 재사용 0. 원본 실행/import/probe/network/install0. 실제 worker나 backend를 시작하지 않았다.

## __init__.py
1~55 전문. psmux_adapter 다음 subprocess_fallback을 순회하여 is_available True인 첫 인스턴스를 반환한다. 예외는 last_error에 모으지만 단순 False는 이유가 없고 fallback은 항상 True이므로 구성 오류가 조용히 fallback이 된다. get_multiplexer는 registry allowlist를 강제하지 않고 package suffix를 동적 import하며 MULTIPLEXER 존재만 검사하고 실제 ABC/메서드 준수를 검증하지 않는다. 명시 요청과 자동 탐지 정책을 분리할 필요가 있다. zellij는 미래 주석일 뿐 구현이 아니다. scripts Python에서 명시 lib.workers 참조 검색은 테스트/주석 위주이며 동적 caller 부재를 증명하지 않는다. team 문서는 detect_best를 요구하지만 launch는 nohup bash를 별도로 적고 ultrawork는 내부 Agent라고 명시한다. 따라서 모든 실제 작업을 이 registry가 생성한다는 테스트 문서 주장은 미입증이다. Zeus는 backend 기능/OS/환경 자격과 선택 이유를 PG attempt에 기록하고 정적 import 가능성을 실제 worker 실행으로 승격하지 않는다.

## base.py
1~61 전문. frozen WorkerHandle(session,worker_id,backend)와 availability/spawn/list/kill/kill_session ABC다. spawn은 process 존재만, list는 running, kill은 종료 성공을 약속한다. 하지만 handle에는 PID/start identity/generation/attempt/lease가 없고 필드 값 검증이나 session 권한이 없다. result/wait/exitcode/stdout/stderr/timeout/cancel-tree 계약도 없다. OS와 provider 독립 인터페이스인 점은 유용하지만 이를 전체 orchestration으로 채택할 수 없다. 동일 ID 재사용 후 오래된 handle이 새 worker를 종료할 수 있는 계약상 공백이 있다. Zeus의 six-W 메시지와 PG SSOT에 generation/lease 및 승인된 argv/cwd/env를 결속하고 실제 결과 수집 및 종료 영수증을 별도 계약으로 설계해야 한다. Python ABC와 frozen dataclass는 인수/권한의 근거가 아니다. 모든 실제 backend/OS 동등성은 미검증이다.

## psmux_adapter.py
1~161 전문. PATH psmux/pmux/tmux 및 LOCALAPPDATA WinGet 경로를 찾아 -V rc0만 availability로 본다. vendor의 '세 바이너리 동일'은 원문 미확인 주장이고 Linux의 일반 tmux도 선택될 수 있다. which가 찾은 절대 경로 대신 이름을 반환하여 이후 PATH 재해석이 생긴다. Windows list2cmdline을 모든 backend에 적용해 POSIX shell quoting과 다르며 Windows에서도 shell metacharacter 및 선택 shell 계약을 증명하지 않는다. 새 session 생성 rc를 무조건 무시하고 named window를 추가하므로 default shell window가 남고 같은 worker 이름 중복/target 모호성을 막지 않는다. env는 new-window CLI 환경에 merge할 뿐 기존 multiplexer server가 자식에게 원하는 env를 전달하는지는 미검증이다. 생성 성공은 process 건강/결과를 보증하지 않는다.

list는 모든 window 이름을 worker로 반환하고 rc오류/CLI없음은 []로 숨긴다. 예외/timeout은 여러 메서드에서 WorkerUnavailableError로 정규화되지 않는다. kill은 backend 값/권한/정확한 pane identity를 확인하지 않으며 성공 rc만 반환한다. kill_session은 미리 센 window 수를 rc0에 반환하므로 worker 수와 다르고 동시 생성/종료 사이 race가 있다. rc 실패를 0 처리하는 방어는 보존하되 실제 자식 트리 종료를 확인한 것이 아니다. 명시 결과/출력 수집 없음. Zeus는 절대 실행 파일·검증한 backend 종류·OS quoting·고유 handle·process group/job·PG lease·결과 receipt를 필요로 한다. test_psmux는 다른 lib.psmux wrapper를 검사하므로 이 adapter의 실제 검증으로 셀 수 없다. 실제 모델/플랫폼/vendor/채택 pending.

## subprocess_fallback.py
1~95 전문. class-level dict/lock으로 같은 프로세스 안의 중복 live key를 막으며 shell=False argv 목록을 Popen에 전달한다. caller env를 전체 상속/merge하여 비밀 및 실행환경 격리는 없다. stdio 모두 DEVNULL이므로 이 계층 자체는 결과와 오류를 수집할 수 없다. is_available True는 executable/cwd/권한/자원 검사가 아니다. Popen 예외는 WorkerUnavailableError로 감싸지 않는다. list는 dict snapshot 뒤 poll하므로 순간 상태이고 끝난 entry를 정리하지 않는다. 프로세스 재시작 시 registry는 사라지고 자식은 남을 수 있다.

terminate→3초wait→kill→2초wait 및 예외 False는 유용한 bounded 종료 시도다. process group/Windows Job Object가 없어 손자 프로세스 전체를 종료하지 못한다. POSIX SIGTERM과 Windows TerminateProcess는 의미가 다르다. key만 사용해 오래된 handle 또는 다른 backend handle도 현재 같은 key의 새 작업을 죽일 수 있다. lock 밖 종료로 spawn/list와 generation race가 있으며 kill_session snapshot 이후 새 worker는 남는다. 이 반환값은 성공 결과/사용자 인수와 관계없다. Zeus는 불변 attempt handle, PG fencing, 허용된 env, 제한된 출력 영수증, 프로세스 트리 소유와 종료 확인을 추가한 뒤 변형 후보를 판단한다. 읽은 test_workers는 sleep child roundtrip 및 duplicate 거절을 기대하지만 이번 실행0이며 트리 종료/결과/재시작/세대 race 오라클은 없다.
