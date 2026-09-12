# Claude에게 전달할 U002 구현 지시

U001은 PR #71에서 수용·병합됐다. main의 `docs/zeus/autonomy/design-002/README.md`를 확정 명세로 읽고 U002를 구현하라.

Codex가 분석·설계·수용 기준·독립 검토·병합/이슈 종료를 맡는다. Claude는 이 명세의 구현·테스트·실행 증거·PR 제출을 맡는다. 별도 브랜치/worktree를 사용하고 현재 미커밋 full-analysis 자료와 원장을 변경하지 말라.

목표는 명시적으로 배정한 worker:implementation 작업을 실제 Claude Code로 실행하고 기존 Redis six-W→PG 예약/감사→실행→독립 증거 검사→outbox 경로에 연결하는 것이다. 기존 Codex 기본 실행을 유지하라. provider factory/port, Claude CLI adapter, 모델·usage·session 결속, 수명/예산/종료, U001 로깅을 함께 연결하라. 작업자가 스스로 검토 승인·병합·지식 승격을 하지 않게 하라.

README의 C01–C10 각각에 구현 위치·테스트·실제 환경·증거·미실행 이유를 매핑하라. 실제 Claude 호출은 README의 총 4회/호스트당 2회/회당 300초·USD 1 설정 한도를 지켜 계약 검사 후에만 수행하라. help/version이나 프로토콜 시험 자식을 실제 모델 실측으로 표현하지 말라. 네이티브 resume는 이번 범위가 아니며 새 세션+권위 있는 checkpoint 복구를 구현하라.

예상 밖의 기존 재사용 경로나 명세 충돌이 발견되면 코드 근거와 필요한 결정만 보고하라. 분석 범위나 제품 목표를 임의 확대하지 말라. U003/U004/U005, 전체 자산 분석, 운영 전환은 착수하지 말라.

PR 본문에는 기준 main, 구현 head, 계약 ID, 수용 표, Windows/WSL·CI 결과, 실패 시도, 남은 항목을 기록하라. `Refs #20 #17 #1 #11`로 연결하되 closing keyword는 넣지 말라. 전체 Ruff/pytest와 실제 PG+Redis 검증을 수행하고 로그·JUnit에서 비밀 유출을 확인하라. PR 제출 후 Codex 검토를 기다리고 병합·이슈 종료는 하지 말라.
