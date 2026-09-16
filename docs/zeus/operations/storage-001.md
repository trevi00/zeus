# 로컬 작업 공간 정리 — 2026-09-16

홈에 흩어진 Zeus 검토·파일럿 작업 트리 76개를 `D:\workspaces\zeus\worktrees`로 이동했다. Git 연결을 복구하고 등록된 작업 트리 113개 전체의 상태를 이전 기록과 비교해 기존 변경 보존을 확인했다. 본 저장소의 미커밋 분석 자료와 파일럿의 변경도 유지됐다.

- C 여유 공간: 약 234.1 → 237.83 GiB. 실제 확보량 약 3.7 GiB이며, 공유 파일 때문에 폴더의 논리적 용량 합계와 다르다.
- 활성 저장소 `C:\Users\rudtn\zeus`와 사용 여부가 불명확한 별도 Claude 공간 `C:\Users\rudtn\zeus-pr`은 유지했다. 후자는 약 8.5GB이며 이번 이동 범위에 넣지 않았다.
- 첫 실제 실행의 원본 증거는 `D:\workspaces\zeus\artifacts\limited-operation-001`로 이동했다. 기존 `.runtime/limited-operation-001` 경로는 junction으로 연결했고 receipt hash와 작업 복제본 Git 상태를 확인했다.
- 새 실제 실행 자료는 `D:\workspaces\zeus\artifacts\limited-operation-002`에 생성한다.

규칙은 `D:\workspaces\README.md`, 프로젝트 안내는 `D:\workspaces\zeus\README.md`에 두었다. 전역 Codex AGENTS와 저장소 AGENTS에도 반영했다. 새 작업 트리를 홈에 만들지 않고, 같은 작업의 재검토는 재사용한다. 작은 명세·요약·manifest만 Git에, 큰 로그·증거·복제본은 D에 둔다. Windows/WSL 가상환경은 분리하며 이동된 환경은 재생성 후 사용한다.

이동 목록·옛 경로표·검증 결과는 `D:\workspaces\zeus\maintenance\2026-09-16-storage`에 있다. 로컬 자료이며 GitHub에서 내려받을 수 있는 증거라고 주장하지 않는다. 작업 중 복사 후 재귀 삭제가 자동 승인 검토에 차단되어, 나머지는 원본을 보존하는 PowerShell Move-Item 방식으로 옮겼다. 중단된 이동의 잔여물도 maintenance 안에 보관했다. 전역 인증·설정·호출 원장과 운영 컨테이너는 변경하지 않았다.
