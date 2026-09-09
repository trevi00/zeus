# Zeus

독립 공개 저장소: **[trevi00/zeus](https://github.com/trevi00/zeus)** · [이슈](https://github.com/trevi00/zeus/issues).
기존 `trevi00/codex-harness`는 다른 컴퓨터의 운영 저장소로 유지합니다.
이 저장소는 로컬 Zeus 작업을 분리한 개발 기준점이며 전체 분석·흡수·운영 승인은 아직 완료되지 않았습니다.
[전수 분석 현황](docs/full-analysis/README.md), [통합 분석 이슈](https://github.com/trevi00/zeus/issues/1),
[로컬 티켓과 GitHub 연결](docs/tickets/README.md)을 함께 확인하세요.

Codex 기반 작업·검수·배포 하네스입니다. Zeus 0.2는 기존 실행 기록의 호환성을 유지하며
버전별 로컬 티켓과 GitHub Issues 연동, Windows/Linux 실행 경로, 배포 검증 환경 분리를 추가합니다.
지휘자 → 연구·고도화 팀장 → 전문 팀원이 육하원칙 JSON으로 협업합니다.
판단은 독립 Codex 세션이, 수집·저장·스케줄링·검증·배포는 Python 스크립트가 처리합니다.

첫 실제 자기 개선은 [PR #1](https://github.com/trevi00/codex-harness/pull/1)입니다.
팀원이 Redis Streams 정리를 구현하고, 팀장·지휘자가 각각 실제 Codex로 검수했습니다.
기존 평가 기준의 통합 테스트와 Docker 안의 실제 Codex 파일 작업 카나리아를 통과한 커밋을 병합·반영했습니다.
`zeus demo`는 별도의 고정 fixture이며 이 실제 검증과 구분합니다.

로컬 Claude 하네스의 파일 목록은 확보했지만 **전체 의미 분석·흡수는 아직 완료되지 않았습니다**.
과거 PR의 실행 증거는 당시 커밋에 한정됩니다. 현재 변경은 [Zeus 작업 기록](docs/zeus/README.md)을 참고하세요.

삼성 Android 휴대폰·태블릿용 [SDD 준비 계층](docs/sdd/README.md)은 엄격 스펙, 티켓 결속,
관측 로그→시나리오 제안, 8단계 검토 보고서와 미실행 replay 초안을 제공합니다.
[시각적 스펙 초안](docs/sdd/review.html)에서 범위를 검토할 수 있습니다.
실기기 실행·사람 인증·8단계 배포 자동화는 아직 미구현입니다.

## 실행

필요: Python 3.12+, uv, Docker Compose v2, 로그인된 Codex CLI 및 GitHub CLI.
Windows는 Docker Desktop의 Linux 컨테이너, Linux/WSL은 해당 환경의 Docker Engine을 사용합니다.
Windows와 WSL 사이에 `.venv`를 공유하지 마세요. 각 환경의 별도 checkout에서 설치합니다.

```powershell
uv sync --frozen
uv run zeus setup
uv run zeus doctor --offline
docker compose up -d --wait postgres redis
uv run zeus init-db
uv run zeus doctor
docker compose --profile agents build conductor
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/start_supervisor.ps1
uv run zeus status
```

Linux/WSL에서 supervisor를 전경 실행하거나 서비스 관리자에 연결할 때:

```bash
uv run --frozen zeus-supervisor --repository "$PWD" --research --releases
# 같은 진입점의 Bash 래퍼:
bash scripts/start_supervisor.sh --research --releases
```

공통 CLI는 `zeus --repository /path/to/zeus ...`로 작업 디렉토리와
독립적으로 실행할 수 있습니다. Supervisor는 `--once` 실패 시 0이 아닌 종료 코드를 반환합니다.
`--releases`는 검수된 후보의 기존 자동 배포 경로를 활성화하는 옵션입니다.

환경변수가 저장소 `.env`보다 우선합니다. `HARNESS_RUNTIME_DIR`의 상대경로는 저장소 기준입니다.
Codex 인증 파일은 `HARNESS_CODEX_AUTH` → `CODEX_HOME/auth.json` → 사용자 홈의
`.codex/auth.json` 순으로 찾습니다. Compose를 직접 실행하면서 `CODEX_HOME`을 쓰는 경우
`HARNESS_CODEX_AUTH`도 지정하세요. 인증 파일이 없으면 디렉토리로 자동 생성하지 않고 실패합니다.
`zeus setup`을 다시 실행해도 기존 DB 비밀번호는 바뀌지 않습니다.

`.env`의 `HARNESS_GITHUB_REPO=owner/repository`가 PR 대상입니다.
DB와 Redis는 localhost의 55432, 56379 포트를 사용합니다. 인증·실행 기록은 Git에 넣지 않습니다.
Windows 호스트 `.venv`와 컨테이너 `/repository/.venv`는 별도 볼륨으로 분리합니다.
supervisor는 호스트에서 실행되며 에이전트에 Docker 소켓을 노출하지 않습니다.
`-InstallStartup`은 현재 사용자의 로그인 시 supervisor를 시작하도록 등록합니다.

## 티켓을 통한 개선 요청

로컬 PostgreSQL 원장이 티켓 내용·수정 이력·검수 의견의 기준입니다. GitHub Issues는 명시적으로
동기화하는 공유 창구입니다. 두 검수자는 같은 티켓 버전과 증거를 보고 각각 의견을 남깁니다.
검수자 이름과 provider는 입력한 주장으로 기록되며 CLI 입력만으로 실제 모델 실행을 인증하지 않습니다.

```powershell
uv run zeus ticket create --file docs/zeus/ticket-example.json --author operator
uv run zeus ticket list
# 아래 ID는 create 결과의 실제 ID로 바꿉니다.
uv run zeus ticket show ZEUS-0123456789ab
uv run zeus ticket review ZEUS-0123456789ab --revision 1 --reviewer Codex --provider codex --verdict question --summary "복구 조건 검토 필요" --evidence "검수 증거 경로 또는 artifact 참조"
uv run zeus ticket sync ZEUS-0123456789ab --repo trevi00/zeus --preview
uv run zeus ticket sync ZEUS-0123456789ab --repo trevi00/zeus
uv run zeus ticket pull ZEUS-0123456789ab --repo trevi00/zeus
uv run zeus ticket dispatch ZEUS-0123456789ab --revision 1
```

`sync`는 실제 이슈를 생성하거나 갱신합니다. `--preview`는 게시 없이 본문을 보여줍니다.
`pull`은 외부 본문·댓글·상태를 관측 증거로 보존합니다. 외부 내용으로 로컬 티켓이나 배포 승인을
변경하지 않습니다. 본문 충돌은 덮어쓰지 않고 중단합니다. 댓글은 보존됩니다.

`update ID --revision N --file ticket.json --reason "수정 사유"`는 새 버전을 추가합니다.
이전 의견은 보존되지만 새 버전의 의견으로 사용되지 않습니다. `dispatch`는 같은 버전에 대해
한 번만 계획 작업을 원장에 등록하며, 실제 실행은 supervisor가 담당합니다. 티켓 피드백은
기존 코드 검수·카나리아·배포 조건을 대신하지 않습니다.

종료 전에는 `zeus ticket review-close ID --packet packet.json --output review.html`로
인수 기준 원문, 실제 관측 증거, 환경, 필요한 서명자와 서명 대상 해시를 함께 확인할 수 있습니다.
화면을 열어도 승인·종료되지 않습니다. [종료·재개 절차](docs/zeus/implementation/ticket-lifecycle-002/README.md)와
[검토 화면 사용법 및 실측 예제](docs/zeus/implementation/ticket-review-001/README.md)를 참고하세요.

## 기존 설치에서 전환

`uv sync --frozen` 후 `zeus`, `zeus-supervisor`, `zeus-monitor`, `python -m zeus`를 사용할 수 있습니다.
`harness`, `harness-supervisor` 별칭과 내부 `codex_harness` 모듈은 유지합니다. 기존 `.env`는
setup 재실행 시 그대로 유지됩니다. 새 설치만 Compose 프로젝트와 Redis namespace를 `zeus`로
초기화합니다. 기존 DB 볼륨·namespace와 저장소 URL은 이름 변경 때문에 바꾸지 않습니다.

Zeus CLI와 supervisor의 설정 우선순위는 프로세스 `ZEUS_*` → 프로세스 `HARNESS_*` → `.env`의 `ZEUS_*` → `.env`의
`HARNESS_*`입니다. 저장소 선택은 명시한 `--repository`가 우선합니다.

Windows 실행기는 설정된 runtime 경로와 `--frozen`을 사용하고 중복 시작을 방지합니다.
자동 시작은 명시적인 `-InstallStartup`으로 등록합니다. 연구·배포 자동 실행은 각각 `-Research`,
`-Releases`(Bash에서는 `--research`, `--releases`)로 활성화합니다. Docker가 먼저 실행되어 있어야 합니다.

배포 후보의 기존·후보 테스트는 임시 Compose 프로젝트의 PostgreSQL·Redis와 무작위 localhost 포트를
사용합니다. 정상·오류 종료 시 해당 컨테이너와 볼륨을 정리합니다. 중단 후 남은 오래된 검증 스택은
supervisor 유지관리에서 정의 해시를 확인하고 정리합니다. 이 분리는 테스트의 운영 서비스 오접속을
막기 위한 것이며 후보 Python 코드를 보안 샌드박스에서 실행한다는 뜻은 아닙니다.

## 자동 운영

GitHub Trending·GeekNews를 6시간마다 수집합니다. 팀원은 한 토픽을 선택하고 연구 팀장과 지휘자가
출처·기존 그래프·Google SRE·arc42 관점에서 검토합니다. 승인된 토픽은 고도화 팀장 계획,
독립 구현 checkout, 팀장 검수, 지휘자 검수, PR·카나리아·병합 순서로 진행됩니다.
main이 바뀌면 자동 rebase 작업을 만들고 새 커밋을 다시 심사합니다.

```powershell
uv run zeus research github
uv run zeus research geeknews
uv run zeus improve "개선 목표" --acceptance "측정 가능한 완료 조건"
uv run zeus inspect tasks
uv run zeus inspect releases
```

동시에 실행하는 Codex 작업은 최대 2개입니다. 같은 원인·범위의 독립 사건이 두 번 확인되면
실행 가능한 필수 훅 작업을 만듭니다. 재발하면 같은 훅을 개선하며 새 검증이 끝날 때까지 이전 버전을 유지합니다.
재시도·재작업·RLM 호출에는 예산이 있고, 차단·실패·정체·취소를 성공으로 기록하지 않습니다.
새로 진단되는 작업의 재시도는 증거를 각각 보존하되 하나의 독립 작업으로 집계합니다.
기존 진단 기록은 소급해서 변경하지 않습니다. 임베딩 생성은 별도 스레드에서 실행하고
실패·회복을 `health/embeddings`에 남겨 모델 다운로드가 작업 기동을 막지 않도록 합니다.

Codex App Server의 현재 컨텍스트 사용량이 70%에 도달하면 진행 중인 도구가 끝나는 지점에서
작업·그래프·출처·도구 결과를 저장하고 새 세션에 인계합니다. 오래된 실행의 저장은 lease와 generation으로 거부합니다.
1시간 동안 일이 없는 에이전트 컨테이너는 종료하고, supervisor가 메시지나 영속 작업을 발견하면 다시 기동합니다.

## 컨텍스트와 SSOT

Git은 조직·정책·스키마·코드 정의의 SSOT이고 PostgreSQL은 작업·사건·검수·세션·배포 사실의 SSOT입니다.
GraphRAG는 이 사실에서 파생합니다. Tree-sitter Python 심볼·import·보수적인 호출 관계와 조직·작업 그래프를 색인합니다.
다국어 로컬 ONNX 임베딩, pgvector, 키워드 검색과 그래프 확장을 함께 사용합니다.

```powershell
uv run zeus index .
uv run zeus project-graph
uv run zeus embed --limit 200
uv run zeus query "세션 인계" --semantic
uv run zeus context "세션 인계" --budget 12000
uv run zeus rlm sha256:ARTIFACT_HASH "자료에서 확인할 질문" --max-calls 8
uv run zeus cleanup
```

큰 자료는 내용 주소로 외부에 보존하고 필요한 범위만 읽습니다. RLM은 범위별 분석과 결과 통합을
깊이·호출 예산 안에서 수행합니다. 컨텍스트 편성의 바이트 예산과 Codex의 실제 토큰 사용량은 구분합니다.
supervisor는 미확인 메시지를 보존하며 스트림을 정리하고, 7일이 지난 미참조 자료만 참조 그래프를 확인해 회수합니다.

## 검증

```powershell
uv run python scripts/check.py --integration
uv run python scripts/verify_runtime.py
uv run python scripts/verify_failed_canary.py
uv run python scripts/verify_rlm.py
```

실제 모델 카나리아는 계정 할당량을 사용합니다. 정상 파일 작업, 네이티브 훅 실행,
새 세션 인계와 제한된 테스트 컨텍스트에서의 70% 감지를 검증합니다.
실패 카나리아는 Codex 실행 파일을 제거한 별도 이미지로 배포 거부와 외부 컨트롤러 롤백을 확인합니다.
운영 배포 포인터는 이 장애 주입 테스트에서 바꾸지 않습니다.

## 구조

로컬 운영 모니터: [http://127.0.0.1:8787](http://127.0.0.1:8787).
`powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/start_monitor.ps1 -InstallStartup`
로 수집기와 웹 서버를 시작하고 사용자 로그인 시 자동 시작을 등록합니다.
웹 서버는 정제된 스냅샷만 읽습니다. 조직·작업·검수·세션·배포·훅·Docker·Redis 상태를
확인할 수 있고 출처별 수집 실패와 오래된 관측값을 표시합니다. 조회 외 조작 API는 없습니다.
5초 갱신 주기는 수집 시간 때문에 더 길어질 수 있습니다.
첫 화면인 **진행 점검**에서는 목표별 계획·구현·독립 검수·카나리아·운영 반영 기록,
마지막 활동 시각, 차단 이유와 참고 저장소 분석 상태를 확인합니다. 단계별 최근 기록을
보여주므로 재작업 시 후보가 다를 수 있습니다. 버튼의 상세 근거와 커밋을 확인하세요.
최근 활동 관측은 성과 검증이 아니며, 구현 완료도 운영 반영 완료를 뜻하지 않습니다.

호스트 MCP는 Playwright 확장 연결과 Context7 로컬 stdio를 사용합니다. Context7 OAuth
콜백 오류는 로컬 stdio 연결로 해소했고 문서 검색을 실측했습니다. Chrome 탭 할당은 확장
연결 시 사용자가 선택해야 합니다. 호스트 MCP 설정은 Docker 에이전트로 자동 전파되지 않습니다.
외부 기능의 채택 기준은 [리서치 검증 계약](docs/research-standard.md)을 따릅니다.

`domain/`은 순수 규칙, `application/`은 상태 전이와 유스케이스, `ports.py`는 내부 계약,
`adapters/`는 Codex·GitHub·Docker·저장소·GraphRAG 구현입니다.
`resources/`에는 조직 JSON, 메시지 Schema, DB 초기 스키마가 있고 `scripts/`는 운영 진입점입니다.

- [전체 설계](docs/design.md)
- [불변 조건·주석·SSOT](docs/contracts.md)
- [검증 범위와 한계](docs/status.md)
- [참고 출처](docs/references.md)
- [로컬 두 하네스 통합 현황과 남은 범위](docs/local-adoption/README.md)
