# Windows restricted pilot 001

Codex 운영 구성·수용 시험. 기준 main 9dffcb4, U002 merge c6ceff0. 사용자 '다음단계 진행' 및 claude-work-017의 추가 1회 결정에 따른 실행이다.

이 브랜치는 시험 구성만 바꾼다. restricted=true, 고정 원장의 기존 사용 2개를 보존하고 누적 상한을 3으로 정해 추가 호출 1개만 허용한다. 원장 삭제·새 label로 예산 우회·자동 재시도는 없다. 300초, USD 1 provider 선언 한도. 현재 Windows만 실행하며 global multi-host 예산을 주장하지 않는다.

기존 scripts/claude_real_call.py --compose를 사용해 일회용 PG/Redis와 임시 저장소의 slug.py 수정 작업을 실제 Claude worker:implementation에 배정한다. 원장 수락·예약·관측·독립 테스트·six-W 결과 전송을 검증한다. 이 러너는 입력 배정을 PG Workflow에 직접 제출하고 결과를 Redis로 발행하므로 양방향 Redis E2E를 통과했다고 표현하지 않는다.

통과 기준: 작업 succeeded, 전 테스트 3 failed에서 후 3 passed, test_slug.py 불변·변경 경로 slug.py만, --restricted 전달, provider session 결속, 정상 부모/트리 종료, PG 정산과 관측 수집, Redis task.result 전달, 기존 인증 유지, 호출 슬롯 2→3. 실패는 보존하고 재호출하지 않는다.

시험 통과는 이 구성의 작은 작업에 대한 실측이다. 상시 운영·무인 PR 반복·U003 지식 승격 완료가 아니다. 이 구성은 자동으로 main이나 운영 컨테이너에 반영하지 않는다. 이후 Zeus 개선 티켓을 돌릴 경우 별도 한도와 구체적 작업 명세를 확정한다.
