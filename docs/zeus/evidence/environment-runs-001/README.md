# 호스트별 실제 실행 증거 — Windows 11과 WSL Ubuntu에서 실제 PostgreSQL·Redis로 전체 검증

2026-09-11. main `e2e3235` 를 두 호스트에서 각각 체크아웃해, CI와 같은 명령을 **실제 PostgreSQL(pgvector pg17)·Redis(7.4)** 일회용
Docker 스택 위에서 실행했습니다. 이 PR 전에도 호스트별 실제 PG·Redis 실행 기록은 있었습니다 —
[outbox-isolation-001](../../implementation/outbox-isolation-001/README.md)은 Windows에서 실제 PG·Redis로 대상 검사 58개 통과와 별도
WSL Ubuntu checkout의 742 passed / 146 skipped 를 기록했고, 이후 FA 기록들은 PG 격리 스키마 검사를 포함했습니다. 이 기록이 **추가**하는
것은 현재 main에서 두 호스트 모두 **전체 스위트를 integration 모드(PG+Redis)로** 실행한 결과와 일회용 Docker 검사(PG 일시정지·재시작·
중단)입니다. 제가 이전에 "Windows 로컬은 Redis가 없어 integration 파일이 실패했다"고 적은 것은 제 세션의 실행 방식(라이브 원장 PG만
연결, Redis 미기동)을 말한 것이지 저장소 전체의 상태가 아니었습니다.

**이 디렉터리의 영수증은 러너 1차 버전(`567d75b`)의 출력이며 원본 그대로 둡니다.** 검토([PR #69 review](https://github.com/trevi00/zeus/pull/69#pullrequestreview-5169858678))에서
그 러너의 한계가 확인됐습니다: 임의 `--project` 이름으로 기존 compose 자산을 `down --volumes` 할 수 있었고, setup/teardown/timeout
실패에도 `passed=true`를 쓸 수 있었으며, 부모 환경의 `ZEUS_*/HARNESS_*`를 상속해 시험이 다른 DB·Redis를 쓰면서 영수증은 새 컨테이너를
적을 수 있었고, `--untracked-files=no`라 당시 미추적이던 러너 자체가 영수증에 결속되지 않았습니다. 이 실행의 부모 환경에는
`ZEUS_*`/`HARNESS_*` 변수가 없었고(같은 셸에서 사후 확인) 시험은 worktree의 `.env`(`harness setup`이 만든 55432/56379)를 읽었으므로 새
스택을 썼을 것으로 판단하지만, **그 결속을 영수증 자체가 증명하지는 않습니다.** 수정된 러너와 결속된 재실행은
[environment-runs-002](../environment-runs-002/README.md)에 있습니다.

## 무엇을 실행했나

각 호스트에서 순서대로:

1. `uv run harness setup` → `docker compose -p <project> up -d --wait postgres redis` (호스트별 별도 프로젝트 이름, 55432/56379 포트를
   공유하므로 순차 실행).
2. `uv run ruff check .`
3. `HARNESS_INTEGRATION=1 uv run python -m pytest -q` — 전체 스위트, PG 격리 스키마·Redis 검사 포함.
4. `HARNESS_INTEGRATION=1 ZEUS_TEST_DOCKER=1 uv run python -m pytest -q tests/test_verification.py tests/test_host_interruption.py` —
   일회용 Docker 스택을 테스트가 직접 만들고 지우는 검사, **PG 컨테이너 일시정지·재시작·중단 중 원장 동작**
   (`test_postgres_pause_is_not_a_clock_step`, `test_postgres_restart_rolls_back_unconfirmed_failure`,
   `test_postgres_outage_cannot_extend_durable_deadline`, `test_host_probe_never_falls_back_to_public_tasks`) 포함.
5. `docker compose -p <project> down --volumes --remove-orphans` (실패 여부와 무관하게 실행, 영수증에 기록).

영수증은 platform·Python·uv·Docker·compose 버전, git head·dirty 여부, 컨테이너 이름/이미지/상태, 단계별 argv·env·exit code·소요 시간·
요약 줄·stdout/stderr sha256, 정리 결과를 담습니다.

## 결과

| 호스트 | 환경 | ruff | 전체 스위트 (PG+Redis) | 일회용 Docker 검사 | 영수증 |
|---|---|---|---|---|---|
| Windows 11 (10.0.26200) | Python 3.12.14, uv 0.12.5, Docker 29.7.2, compose 5.4.0 | 통과 | **1433 passed, 14 skipped** (441s) | **16 passed** (54s) | [windows-11-receipt.json](windows-11-receipt.json) |
| WSL2 Ubuntu 26.04 (kernel 6.18.33.2-microsoft) | Python 3.12.14, uv 0.12.12, Docker 29.7.2, compose 5.4.0 | 통과 | **1439 passed, 8 skipped** (127s) | **16 passed** (47s) | [wsl-ubuntu-26.04-receipt.json](wsl-ubuntu-26.04-receipt.json) |

두 호스트 모두 같은 1447개 검사를 수집했고, skip은 테스트 내부의 환경 판정(예: Windows 전용 PowerShell 런처 검사는 WSL에서, POSIX 전용 격리 검사는 Windows에서 skip)에 따라 Windows 14건·WSL 8건입니다. 두 호스트 모두 스택이 healthy로 올라오고 실행 뒤 컨테이너·볼륨·네트워크가 제거됐습니다(영수증 `stack`/`teardown`). 두 호스트는
같은 Docker Desktop 엔진을 쓰므로 컨테이너 런타임은 공유되고, **파이썬 프로세스·파일시스템·경로·인코딩·프로세스 트리는 각 OS의
것**입니다(Windows NTFS + CRLF 기본, WSL ext4 + LF).

## 이 기록이 채우는 잔여 조건과 채우지 않는 것

이슈 잔여 조건([ticket-closure-001](../../ticket-closure-001/README.md)) 중 "Windows/Linux/WSL의 실제 경로·프로세스·PG·재시작 환경에서
검증" 항목에 대해, **이 PC의 Windows와 WSL Ubuntu 두 호스트에서 실제 PG·Redis·프로세스로 스위트 전체가 통과했다**는 사실을 제공합니다
(#16 다중 파일 crash/lost-ack, #17 pane 로그 수집·중단·재개, #21 PG·프로세스·시계 재시험/동시성, #23 경로·프로세스 트리·PG 재시작·stale
authority, #26 훅 설치·격리 실패 경로, #12 producer→validator→reader 검사의 호스트별 실행 영수증, #18 중 "WSL/Docker 중단 복구"의
PG 컨테이너 일시정지·재시작 부분).

제공하지 않는 것:
- 네이티브 Linux 호스트(WSL2가 아닌 실제 Linux)와 macOS. Linux는 여전히 GitHub Actions(ubuntu-latest) 결과만 있습니다.
- 이 PC의 **절전·재부팅**(#18). 이 작업에서 재부팅하지 않았습니다. 세션이 끊기므로 사용자가 직접 수행해야 하는 항목입니다.
- 사람의 인수, 실제 제품·기기·금전 시나리오, 실제 모델 자격 이전(#13/#14/#15/#19/#20/#24/#25/#27/#28/#29/#31/#32/#33). 테스트 fixture는
  그 증거가 아닙니다.
- 이슈 종료 판정. 종료는 Codex의 서명 정책 경로(PR #68)로만 이루어집니다.
