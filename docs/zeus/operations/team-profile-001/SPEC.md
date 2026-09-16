# Claude 팀원 운영 프로필과 실제 작업 완주

2026-09-16. Codex 분석·설계·수용, Claude 구현. 사용자 승인: 로컬 하네스 자산을 팀원 실행에도 적용하고 실제 코드 작업을 검토까지 완료한다. 이전 전체 분석 원장은 유지하며 이번 부분 적용을 전체 흡수 완료로 표시하지 않는다.

## 사실과 적용 결정

- Zeus main 1aed280에 제한 실행 루프가 병합됐다. 실제 Claude 작업 제출은 확인했으나 팀장 호출은 300초 기한 초과로 차단됐다.
- 이전 Claude 테스트 명령은 실행별 허용 규칙과 절대 경로 Python 명령이 달라 거절됐다. 원본 사용자 settings 전체를 상속하는 것으로 해결하지 않는다. 사용자에게 이미 받은 실행 권한 범위에서 팀원 프로필의 Bash 실행을 명시적으로 허용한다. 이는 OS 보안 격리를 제공한다는 주장이 아니다.
- 원본 검토를 재사용한다: docs/full-analysis/entry-agents-root-review.md, baldrix-skill-routing-runtime/resolution.md, guardian/review.md. 새 관측은 D:/workspaces/zeus/artifacts/team-profile-001/sources.json에 commit/blob/working-byte digest로 고정한다. 기존 pinned coverage를 새 revision 완료로 덮어쓰지 않는다.
- Baldrix CLAUDE.md의 설계→구현→검증과 기존 체계 재사용, verification-before-completion의 주장/증거 구분, harness CLAUDE.md의 검증 전 컨텍스트 승격 금지·관리/실작업 분리·주입식 경로를 **내용을 새로 작성하여 adapt**한다. 원본의 매 메시지 재검증·강제 비판 반복은 채택하지 않고 변경 revision과 증거의 결속으로 바꾼다.
- guardian README는 실행/승인 책임 분리의 참고이며 watchdog·복원기·키·토큰·예약 작업은 설치하지 않는다. 원본 코드 실행/배포는 이번 범위 밖이다. 상류 스킬이 명시하는 Jesse Vincent/superpowers MIT 유래는 출처에 남기되 전문 복제하지 않는다.

## 공식 인터페이스 확인

설치 Claude Code 2.1.272의 --help에서 --append-system-prompt, --settings, --restricted 지원을 확인했다. restricted는 명시한 tools 및 --settings는 유지하며 사용자/project/local 설정을 무시한다고 설명한다. 실제 동작은 canary로 확인한다.

- https://code.claude.com/docs/en/hooks : SessionStart, PostToolUse 이벤트와 stdin JSON/command hook. 2026-09-16 열람.
- https://code.claude.com/docs/en/settings : 실행별 설정과 우선순위. 같은 날 열람.
- https://code.claude.com/docs/en/cli-reference : 실행별 prompt/settings 옵션. 같은 날 열람.

## 하나의 구현 경로

1. Git/package 관리 `worker-v1` 프로필을 추가한다. 짧은 역할 지침·검증 스킬 내용을 가진 문서와 manifest(프로필 id/version, 본문 digest, 원본 출처/처분)를 둔다. 원본 홈 디렉터리를 런타임에 읽거나 복제하지 않는다.
2. ClaudeCodeRuntime의 opt-in `runtime.worker_profile = "worker-v1"`만 선택자로 쓴다. 미지정은 기존 동작, 알 수 없는 이름/변조된 profile은 provider 시작 전 거절한다. assignment/model 출력으로 프로필을 고르지 않는다. domain/application에 adapter import를 추가하지 않는다.
3. 선택 시 packaged 문서를 --append-system-prompt로 전달한다. 본문 원문 대신 id/version/digest/출처 digest와 전달 방식을 command receipt에 기록한다. 문서가 전달됐다는 사실과 모델이 준수했다는 판정은 분리한다. 문자 한도 6000; 임의 truncation 금지.
4. 실행별 --settings에 SessionStart와 PostToolUse(Bash) command hook을 합성한다. stdlib 전용 packaged hook을 사용하며 원본 훅은 실행하지 않는다. hook은 session id/event/tool name과 profile digest만 기록한다. prompt·명령·출력·자격증명 원문을 저장하지 않는다. hook 수신 JSON은 크기 제한, 출력 경로는 고정 인자, 파일명은 안전하게 생성한다. 동시 실행의 기록을 분리하고 기존 파일을 덮어쓰지 않는다.
5. hook 산출물은 작업 checkout 밖의 실행별 디렉터리에 보존한다(기본은 지정된 profile_evidence_root 또는 숙주 runtime 아래). run 종료 영수증에 실제 관측된 hook event 수와 provenance를 붙인다. 훅 미실행/쓰기 실패는 관측 불가로 드러내며 설치만으로 실행됐다고 하지 않는다. hook 기록은 승인/완료 권위가 아니다. 무한 stop hook은 넣지 않는다.
6. 프로필 환경은 검증된 숙주 sys.executable의 부모를 PATH 앞에 두고 PYTHONPATH를 작업 cwd/src(존재할 때만)로 구성한다. 임의 부모 PYTHONPATH를 상속하지 않는다. `python -m pytest`, `python -m ruff`가 현재 후보를 대상으로 실행되게 한다. DB/Redis/Zeus 운영 자격증명은 기존대로 자식 환경에서 제외한다. Bash 허용은 프로필에 명시하며 Task/MCP 확장 등 다른 정책은 바꾸지 않는다.
7. Windows/Linux 경로 인용과 실제 hook subprocess 테스트를 포함한다. 기존 Claude protocol fixture에서 profile 미지정 회귀는 유지한다. 프로필 계층의 파일 실행/검증은 모델 대역, 실제 Claude 검증은 운영 canary로 별도 기록한다.

간결한 파일 구조를 사용한다: adapters/worker_profile.py, resources/worker-profile* (manifest, 문서, standalone hook), adapters/claude_cli.py 및 관련 tests/docs/contracts.md. 필요 이상으로 실행기·provider 정책·전역 환경을 바꾸지 않는다. 설치/홈 설정 변경, 별도 daemon, 전체 스킬 라우터, 지식 자동 승격은 제외한다.

## 수용 행렬과 운영 순서

| 경계 | 확인할 결과 |
|---|---|
| 정상 | 올바른 profile digest와 prompt/settings 전달, 실제 hook 수신, 현재 cwd 테스트 |
| 미지정 | 기존 Claude 실행 계약과 protocol tests 유지 |
| 변조/미지정 이름/과대 본문 | provider 시작 전 명확한 거절 |
| 실패/timeout | 기존 종료·차단·로그 유지, hook 없음은 없음으로 기록 |
| 동시 실행/재시작 | hook 산출물 세션별 분리·보존, cycle 한도 유지 |
| 환경 | Windows/Linux 인용 검증, 비밀 원문 미기록, D 산출물 |
| 완료 | 실제 작은 코드 변경의 테스트 성공→Codex 검토 수용→운영자 대기 |

첫 Claude 구현에는 이 명세와 파일 인터페이스만 전달한다. 독립 검토 후 실제 canary는 작은 CLI 개선(상태 조회에 남은 실행 횟수 표시)을 배정한다. profile SessionStart/PostToolUse와 실제 테스트 출력/종료, candidate diff를 관측한다. 팀장 검토 입력은 이 작은 변경과 필요한 증거로 제한한다. 기한 초과의 원인을 입력 크기로 확정하지 않는다. 기존 300초 기한을 유지하고 불필요한 전수 탐색을 요청하지 않는다.

이전 미확정 review는 종료 증거를 확인해 기존 observe reconcile의 discard로 종결한다. 승인/성공으로 고치거나 task를 재큐잉하지 않는다. 새로운 작업은 새 schema/namespace에서 진행하고 옛 원장을 보존한다.

이번 사용자 승인 단계의 실호출 상한: 기존 기계 8 slots 보존, Claude 구현 2회 이내(각 USD8 option, 900초), 작은 canary 1회(USD2 option, 900초), Codex 검토 1회(300초), 총 4회·기계 누적 12. 실제 청구액 보증이 아니다. 자동 증액/재시도 없음. 구현 1회에 끝나면 남은 호출을 소진하지 않는다. 단계별 테스트는 Ruff와 전체 pytest를 포함하며 독립 PG/Redis 검증은 Codex가 수행한다.

## 실행 중 확인한 한계와 처분

첫 구현이 900초에 도달해 보존된 초안에서 두 번째 호출을 진행했다. 반복되는 전체 검증은 Codex에 맡기고 Claude는 집중 검증으로 마무리했다. 실제 canary는 코드·테스트·훅까지 성공했으나 기존 증거 replay 환경과 검토 기록 경로가 운영 수용에 연결되지 않았다. 상세 증거와 다음 한 배치는 `RESULT.md`에 기록한다. 수용 행렬의 자동 완료 행은 미충족으로 남기고 호출 한도를 늘리거나 완료 기준을 낮추지 않는다. 프로필 구현의 독립 수용과 무인 루프 수용을 구분한다.
