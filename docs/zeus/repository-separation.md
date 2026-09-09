# Zeus 독립 저장소

사용자 요청(2026-09-09): 기존 `trevi00/codex-harness`는 다른 컴퓨터가 사용하므로 Zeus는 별도 저장소로 구축한다.

- 새 원격: `https://github.com/trevi00/zeus` (기존 저장소와 동일하게 비공개)
- 새 로컬: `C:/Users/rudtn/zeus`
- 계보 기준: 기존 로컬 HEAD `0548efaf1bc8833c750c80b242de03b5a73d7799`와 그 위의 미커밋 Zeus 작업
- 원본 로컬/원격에 push, merge, reset, 배포를 수행하지 않는다. 기존 원격의 이후 변경은 자동으로 가져오지 않는다.
- 새 저장소의 코드 게시와 이슈 생성은 개발 작업 공유이며 배포·자가개선 활성화가 아니다.
- 과거 보고서/영수증의 원본 경로·커밋·기존 PR 링크는 역사적 증거로 유지한다. 현재 검증이나 새 저장소의 승인으로 바꾸지 않는다.
- `.runtime`, `.env`, 인증·DB 실행 상태는 Git 대상이 아니다. private 분석 snapshot은 새 로컬 `.runtime/absorption`에 이어서 보관한다.

전체 Claude 하네스 분석은 계속 진행한다. 원장과 문서는 아직 미완료 상태를 유지한다. GitHub Issues는 같은 토픽을 검토하기 위한 공유 창구이며, 원본의 trust/occurrences/승인 상태를 Zeus 권한으로 승계하지 않는다.
