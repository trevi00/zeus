# Zeus 0.2 작업 기록

이 문서는 초기 0.2 구현 당시의 검토·검증 기록이다. 이후 독립 저장소 생성과 실제 GitHub 이슈 11개 연동, Windows/Linux CI를 완료했다. 최신 게시 검증은 [독립 저장소 검증 기록](repository-bootstrap-validation.md), 남은 전체 요청은 [전체 작업 범위](full-delivery-scope.md)를 따른다. 아래의 당시 미실행 표시는 역사적 상태로 보존한다.

사용자가 선택한 구성은 **로컬 티켓 원장 + GitHub Issues 연동**이다. 로컬 PostgreSQL의 기존
documents 저장 계층을 사용하며, 별도의 중복 원장을 만들지 않는다. GitHub 게시와 실행 요청은
명시적인 CLI 명령으로 수행한다. 이 작업 중 운영 supervisor를 기동하거나 실제 이슈를 게시하지 않았다.

## 구현 범위

- `zeus`, `zeus-supervisor`, `zeus-monitor`, `python -m zeus` 진입점과 기존 명령 호환.
- Windows/PowerShell 및 Linux/Bash의 저장소·runtime 경로 정합성, 설정 별칭 우선순위.
- 기존 `.env`, Compose 프로젝트·볼륨, Redis namespace 보존. 신규 설치만 Zeus 기본값 사용.
- 버전·내용 해시에 연결된 티켓, 검수 의견, 한 번만 등록하는 계획 outbox.
- 수정된 요청의 작업·검수 결과는 `superseded`로 보존하고 후속 실행을 차단.
- 이미 수행한 배포 검사도 `superseded_by_ticket_revision`에 실제 결과를 보존.
- GitHub 생성/수정 응답 유실 복구, 검색 반영 지연 중 중복 생성 차단, 외부 본문 충돌 감지.
- 격리된 PostgreSQL·Redis 검증 서비스, 임시 localhost 포트, 실패 시 정리와 고아 스택 회수.

검수 의견은 버전당 최대 20건이며 provider/검수자 이름은 입력한 주장이다. 실제 모델 검수 여부는
실행 증거로 따로 확인한다. 티켓의 `support`는 배포 승인이나 원본 하네스 흡수 승인이 아니다.

## 공동 검수와 수정

Codex가 독립적으로 점검하고 실제 Claude CLI에 읽기 전용 검수를 맡겼다. Claude에는
Read/Glob/Grep만 허용했다. 서로의 발견 사항을 비교한 뒤 Codex가 구현했다.

1. [Codex 발견 사항](review/codex-implementation-review.md)
2. [Claude 구현 검수](review/claude-implementation.md)
3. [반례와 수정 방향 논의](review/claude-implementation-discussion.md)
4. [Claude 후속 검수](review/claude-final.md)
5. [마지막 차단 결함 수정 확인](review/claude-closure.md)
6. [Codex 마무리 기록](review/codex-closure.md)

핵심 논의는 티켓 수정에 따른 기존 작업의 효력이다. 검수 의견을 조언으로 취급하면서도, 변경된
완료 조건에 이전 결과를 그대로 적용하지 않도록 했다. 실행 결과를 보존하고 후속 승격을 차단한다.
승격 의도를 기록하는 트랜잭션에서 티켓 버전을 검사하며, 병합과 DB 포인터 반영 사이에는 티켓 수정을
막는다. 무관한 main 변경으로 정체된 경우에도 실제 Git 조상 관계를 확인하여 안전하게 취소할 수 있다.

[실행 메타데이터](review/receipts.json)는 실제 Claude 세션의 기록이다. Claude의 정적 검수는
Windows/Linux 테스트 실행이나 전체 원본 의미 분석을 인증하지 않는다.

## 운영과 복구 계약

`ticket sync ID --repo owner/name --preview`로 본문을 확인하고 `--preview` 없이 게시한다.
한 번 연결된 이슈는 같은 번호로 갱신한다. 원격 본문·댓글·상태는 `ticket pull`로 내용 주소 기반
관측 증거에 보존한다. 로컬 티켓을 수정하려면 `ticket update`로 새 버전을 만든다.

응답 유실 시 마지막 확인 본문, 전송 예정 본문, 원격에서 실제 관측한 본문의 해시로 재시도한다.
생성 여부가 불확실하고 GitHub 검색에 아직 나타나지 않으면 재생성하지 않는다. 잠시 후 같은 명령으로
재검색한다. 외부 본문 변경은 자동으로 덮어쓰지 않는다. `pull`로 증거를 남긴 후 GitHub에서 변경을
검토·조정해야 한다. 외부 댓글은 동기화에서 지우지 않는다. GitHub 읽기와 쓰기 사이의 외부 편집을
조건부 원자 쓰기로 보호하는 기능은 현재 gh CLI 연동에 없다.

승격이 정체되면 `zeus release-retry RELEASE_ID --reason "복구 사유"`로 기존 검증과 승격 의도를
재사용하는 복구 작업을 등록한다. 진행 중인 컨트롤러가 있으면 거부한다. 후보가 main에 포함되지
않았고 원격 작업·병합 결과도 기록되지 않았다면 `zeus release-abandon RELEASE_ID --reason "취소 사유"`로
취소하고 티켓을 수정할 수 있다. 이 명령은 Git 작업 트리를 변경하지 않는다.

원격 병합 여부가 불확실한 `blocked_remote`는 자동으로 취소하거나 재병합하지 않는다.
GitHub의 실제 병합 커밋과 트리를 확인하여 복구해야 하며, 이 증거를 자동 수집·대조하는 복구 명령은
추가 구현 대상이다. 안전한 복구를 증명하지 못한 상태는 완료로 표시하지 않는다.

## 검증과 남은 범위

정확한 테스트 수, 이미지 ID, 파일 해시는 [검증 기록](verification.json)에 보존한다.
CLI 통합 검증은 별도 PostgreSQL 스키마에서 실행한 후 제거했다. 모델 응답 fixture와 실제 Claude
검수는 별개다. GitHub 저장소 접근과 Issues 활성화는 읽기 전용으로 확인했으며 실제 이슈 쓰기는
mock 기반 장애 주입 테스트로 검증했다. 실계정 게시·수정 왕복 검증은 아직 수행하지 않았다.

Windows/WSL 간 `.venv` 공유는 지원하지 않는다. Windows는 네이티브 Python/PowerShell로,
Linux는 새 Zeus 이미지에서 검증했다. WSL에서는 Bash 실행기 구문을 검사했다.
WSL 배포판 안의 전체 설치·운영 시험을 완료했다는 뜻은 아니다.

이 변경으로 로컬 `.claude`, `harness`, `guardian`의 전체 흡수가 완료되지는 않는다. 기존에 확보한
2,592개 경로의 의미 분석·계약 매핑, 미반영 기능의 구현, 실제 자기 개선 후보의 배포 왕복 검증은
계속 남아 있다. 역사적 검증 자료는 당시 커밋·이미지의 증거로 유지한다.
