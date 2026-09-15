# Windows restricted pilot 001: 실제 Claude 팀원 실행 통과

2026-09-15 Codex가 실제 Zeus 실행 경로로 수행했다. 정책 기준은 별도 시험 브랜치 `codex/windows-restricted-pilot-001`의 `fe65e286ad88cffe0a473374d07b5f40eb89b4dd`다. main/운영 컨테이너에는 이 시험 정책을 적용하지 않았다.

## 실제 연결과 결과

기존 scripts/claude_real_call.py가 lead:improvement→worker:implementation의 implement 작업을 PG Workflow에 직접 배정하고, Executor가 실제 Claude Code를 호출했다. 결과 task.result는 기존 outbox에서 실제 Redis Streams로 전송했다. 입력도 Redis를 거친 양방향 E2E라고 부르지 않는다. 이번에 일한 Claude는 Zeus 실행 어댑터가 시작·관리한 팀원 프로세스다. 과거 PR 제출 세션이 모두 Zeus 관리 세션이었다는 뜻은 아니다.

- 실제 호출 1회, 작업 27.1초, process elapsed 25.641초. 요청/보고 모델 claude-fable-5-1.
- 수정 전 3 failed → 러너가 직접 재실행한 결과 **3 passed**. 변경 파일 slug.py만, test_slug.py 불변.
- --restricted 전달, init/terminal/request session 일치. 부모 정상 자발적 exit 0, Windows Job active_processes=0.
- PG 작업 succeeded, 실제 Redis task.result 1개, 관측 20개 수집, sink failure 0.
- provider 보고 추정 비용 USD 0.35318875. 실제 청구액이나 budget 옵션의 강제 중단 검증이 아니다.
- 기존 구독 인증 유지: provider init api_key_source=none. MCP/플러그인 목록 비어 있음, hook 이벤트 0. custom commands 53개와 agent 정의 5개는 여전히 보고됐다. 상속 완전 차단을 주장하지 않는다.
- 고정 호출 원장 기존 2개 보존, 추가 슬롯 1개로 3개. 추가 호출·자동 재시도 없음.
- 일회용 compose 컨테이너 잔여 0을 직접 조회했다. 임시 작업 폴더는 workdir_removed=false다.

## 판정과 한계

Windows restricted 구성의 작은 수정 작업 실측은 통과다. 이는 모델이 제안한 코드가 이 테스트를 통과했다는 증거이며, 모델 자격 전면 이전·실제품 인수·상시 무인 운영 승인이 아니다. 모델의 테스트 자기보고는 EvidenceInspector에서 incomplete(verified_mismatch=1, checked=0)였고, 이번 통과 근거는 별도 러너 실행 결과다. 자기보고를 검증 완료로 승격하지 않았다.

독립 판정은 `docs/zeus/evidence/windows-restricted-pilot-001/verification.json`에 영수증 hash와 기준 commit으로 고정했다. 권한 밖 경로 접근을 시도한 적대적 시험은 이번 한 번에 포함하지 않았으므로 restricted 파일 차단 전체를 실측했다고 말하지 않는다.

## 다음 실제 Zeus 작업

첫 개선 티켓은 **실측 러너의 증거 보존과 임시 worktree 정리**로 좁힌다. 이번에 재관측한 workdir_removed=false를 재현하고 수정하는 일이다. 구현은 Claude, 분석·수용은 Codex가 맡는다. 작업 명세는 NEXT-CLAUDE-TASK.md에 고정했다. 아직 이 개선 작업의 실제 모델 호출을 시작하거나 기존 1회 한도를 늘리지 않았다.

U003 지식 승격이나 U004 무인 PR 반복을 먼저 완료했다고 표시하지 않는다. 현재 상태는 'Zeus가 Claude 팀원에게 실제 작은 작업을 배정·실행·회수하는 경로 확인'이며, orchestrator/lead/worker 상시 자동 운영과는 구분한다.
