# 사용 전 결함 수정 및 검증 — 2026-09-09 KST

대상은 `fix/portable-runtime-and-local-adoption`의 미커밋 작업 트리다.
`hardening-manifest.json`에 이번 검증 대상 파일의 SHA-256을 기록했다.
이전 `verification.md`와 `candidate-manifest.json`은 당시 결과 그대로 보존한다.

## 재현한 문제와 수정

| 문제 | 수정 및 회귀 검증 |
|---|---|
| 진단·검수 중 작업 임대가 만료되거나 교체돼도 incident, 승인, 배포 큐가 먼저 저장됨 | 임대 확인, 부수 효과, 완료 기록을 한 DB 트랜잭션으로 묶음. 정상·만료·교체·완료 저장 실패를 메모리와 실제 PostgreSQL에서 검증 |
| 설치·테스트·CLI 시작 실패 후에도 후속 빌드나 모델 canary 실행 | 실패 단계에서 후보를 거부하고 미실행 단계에 사유와 증거 참조 기록 |
| 이미 검증된 배포 재시도에서 기준 HEAD가 바뀌어도 원격 게시 진행 | 게시 직전 기준 HEAD를 재확인하고 다르면 rebase 작업 요청 |
| 그래프 색인 오류가 대기 작업의 worker 기동을 막음 | 색인·스트림 정리·아티팩트 정리를 하나의 백그라운드 스레드에서 수행하고 작업별 오류 격리. 그래프 실패 상태에서도 worker 기동 검증 |
| 동시 PostgreSQL 초기화에서 extension 생성 충돌; 임시 schema 삭제가 vector extension까지 제거할 수 있음 | 트랜잭션 advisory lock으로 초기화 직렬화, extension과 vector 타입을 public schema에 명시. 병렬 초기화와 임시 schema 삭제 후 생존 검증 |
| 실행 작업이 계속 쌓이면 진단·검수 큐가 처리 기회를 얻지 못함 | 두 큐의 우선순위를 매번 교대하고 한쪽이 비면 즉시 다른 큐 처리. 양쪽 또는 한쪽에 지속적인 작업이 있는 경우 검증 |

## 관측 결과

| 검증 | 결과 |
|---|---|
| Windows Python 3.14.7, `uv run python scripts/check.py --integration` | Ruff 통과; **617 passed, 7 skipped**, 170.33초 |
| Linux 컨테이너 Python 3.13, 전체 pytest 및 실제 PostgreSQL/Redis | **624 passed**, 48.04초 |
| `git diff --check` | 통과 |
| `uv build` | wheel 및 sdist 생성 성공 |
| 최종 Docker 빌드 | `codex-harness:hardening-validation`, `sha256:afd5eccf918a7bd4b47f25aa25f8ab735fcf0df122a9e1fcc724c3434f9c88ac` |

Linux 테스트는 이전 검증 이미지의 의존성을 사용하며 최신 소스와 테스트를
읽기 전용 `/workspace` 마운트로 로드했다. 위 최종 이미지는 마지막 소스 수정 후
별도로 빌드했다. 이번 검증에서는 실제 모델 canary를 반복하지 않았다. 이전
canary 결과가 새 이미지의 모델 실행 검증을 대신한다고 주장하지 않는다.

테스트는 전용 `codex-harness-validation` 프로젝트의 PostgreSQL/Redis를 사용했다.
테스트별 임시 schema를 분리해 두 OS의 통합 테스트를 동시에 실행했다.
상세 로그는 gitignored `.runtime/hardening-final-windows.txt`와
`.runtime/hardening-final-linux.txt`에 있다.

## 남은 검증 범위

- 원격 main 변경과 게시·병합 사이의 경쟁, 프로세스 강제 종료 후 Git/DB 간 복구,
  다중 호스트의 배포·rollback 경쟁은 별도 검증이 필요하다.
- background maintenance의 구성 요소별 상태는 DB health 기록에 남지만 현재
  모니터 화면의 전체 상태에 모두 반영되지는 않는다.
- Windows 로그인 및 Linux 서비스 등록, WSL 장기 실행·재시작·업데이트는 미검증이다.
- 로컬 원본 2,592개 추적 경로의 전수 의미 검토와 기능 흡수는 아직 완료되지 않았다.
- 운영 supervisor 시작, 자동실행 등록, 원격 push/merge 및 실제 릴리스 승격은 수행하지 않았다.
