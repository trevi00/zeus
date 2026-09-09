# 로컬 하네스 통합 작업

기준 대상: `codex-harness` 원격 HEAD `0548efa`에서 만든
`fix/portable-runtime-and-local-adoption` 브랜치. 이번 입력은 `.claude` 하나와
`harness` + `guardian` 조합 하나다. 기존 `migration-sequence.json`의
oh-my-codex/Ouroboros는 이번 두 로컬 하네스의 대체물이 아니다.

## 원본 고정과 범위

| 입력 | 현재 HEAD | 추적 파일 | 상태 |
|---|---|---:|---|
| `.claude` / Baldrix | `cbb5c3e6c9c4af6f86626474f4d7d62fd8e8a6d2` | 1,648 | 미커밋 변경 있음 |
| `harness` | `a3f8b3be9a0a389329de6e16a6c7db81782041a3` | 931 | 미커밋 변경 있음 |
| `guardian` | `e7ced4a632a38726dca44e84fa0a00b8e1f0b6f4` | 13 | 미커밋 변경 있음 |

`inventories/*.json`은 모든 Git 추적 경로의 mode/type/object/size와 관측된 로컬
파일 SHA-256을 남긴다. 비정상 인코딩 경로도 base64로 보존한다. 심볼릭 링크는
따라가지 않으며 서브모듈·읽기 실패는 명시한다. 미커밋 파일 해시는 관측값이며
원자적 스냅샷이나 해당 커밋의 내용이라고 주장하지 않는다. 원본 파일 내용,
인증 정보, 미추적 실행 로그는 가져오지 않았다. 원본 트리를 수정하지 않았다.

**2,592개 경로의 인벤토리이며 전체 의미 분석·이식 완료가 아니다.** 모든 경로의
`disposition`은 아직 `unreviewed`다. 아래 제한된 코드 관찰은 경로 전체에 대한
검토 완료를 대신하지 않는다. 원본의 실행 테스트도 이번 작업에서 수행하지 않았다.

## 확인한 결함과 이번 수정

| 문제 | 근거 | 수정 |
|---|---|---|
| Linux 호스트의 `USERPROFILE` KeyError | 기존 `scripts/supervise.py:deploy_queued`, `tick` | 공통 인증 경로 해석; `CODEX_HOME` 및 명시 경로 지원 |
| 현재 디렉토리에 따른 DB 설정 누락; Redis `.env` 무시 | 기존 `bootstrap.py:database_url`, `redis_url` | 공통 리터럴 `.env` 파서; 환경변수 우선; `--repository` |
| fresh checkout에서 supervisor lock 디렉토리 부재 | 기존 supervisor main | 상태 폴더 선생성, 실패한 `--once`는 비정상 종료 |
| 호스트 supervisor가 wheel에 포함되지 않음 | 기존 `pyproject.toml`, `scripts/supervise.py` | 패키지 모듈 및 `harness-supervisor` 진입점, 기존 래퍼 유지 |
| 임베딩 다운로드가 작업 기동 앞에서 동기 실행 | 기존 `tick` | 단일 별도 스레드 및 실패/회복 상태 기록 |
| 동일 작업 재시도를 독립 재발로 집계 | `executor.execute_one`의 task+attempt ID → `record_incident` | 증거별 ID 유지, 독립 task 기준 재발 집계 |
| 첫 원인 진단 결과가 다음 진단의 알려진 원인에 안 들어감 | `known_causes`가 생성된 hooks만 조회 | 이미 확인된 incidents에서 원인 참조 |
| Windows CP949에서 한글 테스트 데이터 해석 실패 | baseline pytest: 3 failed / 545 passed / 34 skipped | UTF-8 파일 및 subprocess 출력 명시 |
| Windows/Linux 회귀 검증 자동화 부재 | `.github/workflows` 없음 | 두 OS × Python 3.12/3.14 및 Linux PG/Redis 통합 CI 정의 |

이번 변경은 재현 가능한 로컬 결함의 수정이다. 독립 모델 검수, 실제 후보 배포,
원본의 모든 기능 흡수 완료를 주장하지 않는다. 원격 push/merge와 운영 자동실행
등록은 수행하지 않았다.

## 기능별 흡수 지도와 남은 작업

| 원본 영역 | 현재 대상에서 확인할 위치 | 다음 검토/구현 범위 |
|---|---|---|
| Baldrix 스킬·스택 감지·파이프라인 | `project_detection`, `project_skills`, `project_pipeline`, `skill_import` | 기존 일부 이식과 원본 전체 스킬/에이전트/커맨드의 누락 대조, 출처·의존·라이선스 기록 |
| Baldrix 2-strike·research dispatch·repro probe | `executor`, `service`, `workflow`, `hooks` | advisory와 강제 훅 분리, 실제 도구 실패 수집 범위, 재현/정상 사례 연결 |
| Baldrix calibration·threshold proposer·no-degradation | `threshold_*`, `runtime_thresholds` | 수집→제안→시간 분할 재생→독립 검수→활성화의 자동 기동과 복구 추적 |
| Baldrix brain·insight·curator·graduation | `knowledge`, `skill_history`, `skill_guidance` | 검증된 교훈만 다음 실행에 전달; 오염·철회·퇴화 방지; 지식 보존/재색인 |
| Baldrix debate·ralph·orchestrator·team mailbox | `workflow`, `bus`, `releases`, `rlm` | 의미별 동등성, 취소/예산/인계/중복 실행 검증; Claude 이벤트를 Codex 계약으로 변환 |
| harness 원장·derive_state·lease·arming | PostgreSQL Store, `workflow`, `scheduling` | 파일 원장을 복사하지 않고 이벤트 의미와 상태 불변식 대조 |
| harness pipelines·gate runner·evolve·sandbox·curator | `project_pipeline`, `research`, `releases`, `audit_*` | 게이트·자가수정 격리·승격 기준·작업 완료선·잔여 파킹의 기능 대조 |
| harness recall·ontology·seams·ownership·fleet | `knowledge`, `research`, `monitoring` | 그래프/역설계/역할 소유·함대 계약의 누락 추적 |
| guardian watchdog·restorer·seal·operator console | 호스트 supervisor, `deployment`, `releases` | 생존 신호와 실질 전진 분리, 알려진 정상판 복구, 재시도 상한, 원장 보존, 감시기의 별도 권한/수명 |
| 두 하네스 설치·훅·CLI·daemon·cron | 공통 configuration, supervisor, Compose, CI | Codex 네이티브 hooks/app-server 실제 검증, Windows 로그인/Linux 서비스 재시작·중복기동·업데이트·복원 |

위 표는 전수 의미 검토 결과가 아니라 작업 분할이다. 모든 파일과 하위 시스템을
`docs/research-standard.md`에 따라 검토하고, 테스트 실행 영수증과 대상 구현 매핑을
연결해야 전체 흡수 완료를 주장할 수 있다. README에 기능명이 있다는 이유만으로
그 기능이 작동하거나 흡수되었다고 계산하지 않는다.

## 재현

```powershell
uv run python scripts/inventory_local_sources.py --source baldrix=C:\Users\rudtn\.claude --source harness=C:\Users\rudtn\harness --source guardian=C:\Users\rudtn\guardian --output .runtime/new-source-inventory
uv run python scripts/check.py --integration
```

인벤토리 생성기는 기존 결과를 덮어쓰지 않는다. 재관측은 새 출력 폴더를 사용한다.
첫 이식 검증 결과와 한계는 `verification.md`, 후속 상태 저장·배포·대기열 결함
수정과 최신 검증은 `hardening.md`에 기록한다. 각 검증의 파일 해시는 별도
manifest로 보존한다.

Claude와 각자 검토하고 의견을 교환한 후 Codex가 구현한 후속 변경은
[공동 검토 기록](joint-review/README.md)에 정리했다.
