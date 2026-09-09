# 배포 플랫폼 문서 대조

2026-09-09 공식 문서를 조회했다. 이는 pinned 원본 코드 분석의 보조 근거이며 원본 GitHub workflow 실행이나 Claude 플러그인 설치 영수증이 아니다.

- GitHub는 경로와 브랜치 필터를 함께 만족해야 실행하며, paths에 일치하는 변경이 있어야 일반적인 변경 기반 실행을 한다. 따라서 원본의 필터에 없는 brain-only 변경의 자동 검사 공백은 코드와 플랫폼 계약을 결합한 판단이다. 큰 diff 등 플랫폼 예외를 포함한 모든 이벤트를 이번에 재현하지 않았다. 필수 검사라면 workflow 생략과 job 성공도 구분해야 한다. [GitHub workflow syntax](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#onpushpull_requestpull_request_targetpathspaths-ignore).
- Claude marketplace 플러그인은 보통 캐시에 복사되며 플러그인 루트 변수로 번들 자원을 참조한다. 이름·버전 metadata만으로 캐시 설치 위치, 훅 연결, 의존성 설치와 실제 동작을 입증할 수 없다. 이 원본을 플러그인으로 설치하지 않았다. [Claude plugins reference](https://code.claude.com/docs/en/plugins-reference), [Marketplace 배포](https://code.claude.com/docs/en/plugin-marketplaces).

Zeus 변형에서는 설치 번들·런타임 쓰기 경로·기존 사용자 자산을 구분하고 실제 설치/업데이트/롤백 영수증을 요구한다. 이 문서의 플랫폼 설명은 조회 당시 기준이며 도입 시 사용 버전과 다시 결속한다.
