# Ubuntu WSL2 네이티브 검증

2026-09-09 UTC 04:30:22–04:32:17, published commit `4cb7d02df13d7621d47f0324ae121649982db7b2`를 Ubuntu WSL2에서 검증했다. Python 3.14.4, Linux 6.18.33.2-microsoft-standard-WSL2, glibc 2.43이다. Docker 컨테이너 결과가 아니다. 현재 작업 트리의 후속 변경은 이 결과에 포함되지 않는다.

| 실행 | 결과 |
|---|---|
| uv 0.12.2 설치 및 버전 | 성공 |
| `uv sync --frozen` | 성공 |
| `uv run --frozen ruff check .` | 성공 |
| `uv run --frozen pytest -q -ra` | 666 passed, 62 skipped, 19.48초 |
| `uv build` | sdist 및 wheel 생성 성공 |
| `uv run --frozen zeus --version` | Zeus 0.2.0 |
| `uv run --frozen python -m zeus ticket --help` | 성공 |
| harness-supervisor 및 zeus-monitor 도움말 | 성공 |

전체 Git 이력을 가진 로컬 clone을 사용했다. shallow=false 및 과거 schema 기준 `09c1d58298b22337125f29842382d2aef960c7d2` 존재를 확인했다. Git hooks와 global/system config를 비활성화했다. HOME/TMPDIR/uv cache/project venv는 `/tmp/zeus-wsl-46nigh1h/` 아래로 분리했고, 자식 환경에는 명시적인 최소 변수만 전달했다. secrets, `.env`, 실제 PostgreSQL/Redis 접속 환경은 전달하지 않았다. 운영 서비스는 기동하지 않았다. Windows `.venv`나 원본 source에 쓰지 않았다.

`uv.lock` 실행 전후 SHA-256은 모두 `48be7d2bc5a3e2167fc9acac6c6ee0dea904c5a088604a30d99f7045f1dc6b25`이다. 종료 시 `git status --porcelain` 출력이 비어 있다. 실행 대상은 clone의 고정 commit이며, 검증 프로그램 자체는 docs 증거 경로에서 실행했다.

처음 `/usr/bin/python3 -m venv`는 ensurepip 부재로 exit 1이었다. 이를 시스템 apt/Python 변경 없이 우회했다. PyPI의 uv 0.12.2 Linux x86_64 wheel을 받아 PyPI 메타데이터의 SHA-256과 비교하고, uv 실행파일만 전용 디렉터리에 추출했다. wheel SHA-256은 `3a8d93d1fe019561b70494a8e1332492afb5f14dadc33d5239569d0964164d10`이다. 이는 다운로드 무결성 확인이며 공급망 전체 인증은 아니다. uv가 프로젝트 venv를 만들었다.

초기 프로세스 종료 후 다음 실행에서는 이전 `/tmp/zeus-wsl-oi748ewj`가 존재하지 않아, 재개 프로그램이 디렉터리를 열 때 FileNotFoundError로 종료했다. `/tmp` 소멸 원인은 확정하지 않았다. 새 full clone에서 설치부터 최종 검사까지 한 프로세스로 이어서 성공했다. 초기 venv 실패 원시 출력·영수증·실행 프로그램은 별도 이름으로 보존했다. 재개 실패는 도구 출력에서 확인했으며 subprocess 원시 파일은 생성되기 전이었다(`orchestration-events.json`).

62개 skip의 위치와 이유는 `pytest.stdout` 전문에 있다. 서비스 통합 관련 60개, disposable Docker 1개, native PowerShell 1개다. mock 기반 단위 테스트의 성공을 실제 서비스 인수나 운영 배포 성공으로 해석하지 않는다. WSL Python 3.12/3.13, 별도 PG/Redis 통합 서비스, Windows launcher 동작, 빌드 wheel을 새 환경에 설치하는 검증은 이 실행 범위에 없다. 설치·동기화는 네트워크를 사용했고, 네트워크 차단 테스트는 아니다.

`receipt.json`은 단계별 argv/cwd/PID/start/end/exit code와 stdout·stderr SHA-256을 기록한다. 설치 PID 458, sync PID 460, pytest PID 568, 오케스트레이터 도구 session 39995는 종료 확인했다. 원시 출력은 `.stdout`/`.stderr` 파일이며, `artifact-hashes.json`은 최종 증거 파일들의 SHA-256 목록이다. 어떤 실패도 테스트 기준을 낮추거나 source를 수정해 해결하지 않았다.
