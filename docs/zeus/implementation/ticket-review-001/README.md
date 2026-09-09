# 종료 근거 검토 화면

`zeus ticket review-close TICKET --packet packet.json --output review.html`은
인수 기준 원문과 각 증거의 관측 내용, 환경, 되돌리기 방법, 필요한 승인자를 한 화면에 표시합니다.
`prepare-close`에서 생성한 정확한 원본 JSON 파일을 지정합니다. SHA-256과 바이트 수,
해결 커밋, 고정된 신뢰 정책을 표시하며 원본 파일을 다시 만들거나 서명하지 않습니다.

현재 티켓 개정·작업 주기, 증거 해시·시각·연결 관계, 해결 커밋의 병합 여부와 고정 정책을 확인합니다.
화면 생성은 PostgreSQL 원장, 승인 기록, 아티팩트 저장소를 변경하지 않습니다.
GitHub에 쓰거나 종료 권한을 부여하지도 않습니다. 출력 HTML은 승인 완료 영수증이 아닙니다.

```text
zeus ticket prepare-close TICKET --file acceptance.json --output packet.json
zeus ticket review-close TICKET --packet packet.json --output review.html
```

HTML은 외부 자원이나 JavaScript 없이 파일로 열 수 있습니다. 각 증거와 정확한 서명 대상 JSON은
펼쳐서 확인합니다. 문서별 미리보기는 64 KiB, 전체는 256 KiB로 제한하며 환경 증거를 먼저 확보합니다.
생략된 내용이 있으면 경고와 전체 문서의 해시·바이트 수를 표시합니다. 그런 경우 아티팩트의 전체
원문을 별도로 확인해야 합니다. 제출된 `passed`는 사람의 판단이나 실제 계측의 진실성을 인증하지 않습니다.

만료된 패킷도 읽을 수 있지만 종료에는 사용할 수 없습니다. HTML은 생성 시점의 정적 화면이며,
열어 둔 상태에서 시각이나 원장을 다시 조회하지 않습니다. 종료 요청 시 권한과 유효성을 다시 검증합니다.
동일한 출력 바이트는 같은 경로로 재생성할 수 있습니다. 만료 경과나 표시 변경으로 바이트가 달라지면
기존 파일을 덮어쓰지 않으므로 `review-2.html`처럼 새로운 출력 경로를 사용하세요.

## 실제 화면과 검수

[최종 화면 예제](example-review-responsive.html)는 격리 PostgreSQL에 보존된 실제 종료·재개 이력과
전용 시험 이슈 #34, 기존 개선 이슈 #30의 실제 GitHub 관측으로 생성했습니다.
이 예제의 자동화 시험 정책은 사람 서명을 요구하지 않는다는 점을 화면에 명시합니다.
운영 키 등록, 제품 인수, 사람 승인이 완료됐다는 뜻이 아닙니다. 해당 패킷과 정책은 보존된 시험 증거입니다.

- `actual-cli-export.json`: 최초 실제 CLI 실행과 원장·아티팩트 불변 확인.
- `actual-cli-responsive-export.json`: 같은 원본 패킷으로 태블릿 레이아웃을 개선한 최종 실제 CLI 실행.
- `responsive-browser-receipt.json`: 실제 Chrome에서 1440×1000, 768×1024, 390×844 화면 검사,
  키보드로 증거 펼치기, 전체 증거 표시, 가로 넘침·외부 자원·브라우저 오류 확인.
- `responsive-*.png`: 최종 화면 캡처. 데스크톱 브라우저의 너비 재현이며 삼성 실기기 검증은 아닙니다.
- `claude-design.md`, `claude-implementation.md`, `claude-final.md`: 실제 Claude CLI의 설계·구현·최종 검수.
  환경 증거 표시 예산과 해결 커밋 확인 지적을 반영한 뒤 승인받았습니다.

첫 화면 검증 후 태블릿의 승인 영역이 좁아지는 것을 확인하여 900px 이하에서는 한 열로 표시하도록
조정했습니다. 최초 화면·영수증도 별도로 보존합니다. Windows npm 래퍼에서 JavaScript 인자 인용이
실패한 검사 호출은 제품 실행 결과에 포함하지 않았으며, 도구의 `eval --base64`로 재실행했습니다.
새 브라우저를 여는 npm 자식 프로세스의 출력 파이프가 종료되지 않은 호출은 해당 검사 프로세스만
중단했습니다. 전용 세션의 실제 URL을 확인한 뒤 설치된 동일 버전 실행 파일로 최종 검사를 완료했습니다.

Windows 전체 테스트는 **723 passed, 139 skipped**였습니다. 이 실행 뒤에는 900px 레이아웃 CSS만
조정했습니다. 최종 변경의 실제 격리 PostgreSQL·메모리 종료/검토 테스트는 **94 passed**,
Ruff는 통과했습니다. 이 테스트의 GitHub 전송 fixture와 별도로 보존한 실제 GitHub 관측을 구분합니다.
최종 소스 해시와 검사 범위는 `validation.json`, 세부 실행은 각 `*-tests.log`에 보존합니다.

최종 구현 커밋 `1bd9497e84f93104f0d98b74a8a7dd4ff378cb01`을 별도 WSL Ubuntu checkout에서
다시 설치하여 **729 passed, 133 skipped**를 확인했습니다. Ruff, 패키지 빌드, 검토 CLI 도움말,
변경 없는 lockfile·작업 트리까지 통과했습니다. `wsl/receipt.json`에 정확한 커밋, 환경, 단계별 명령과
출력 해시를 보존합니다. WSL에서는 일반 테스트를 실행했고 실제 PostgreSQL 검사는 위 Windows 실행입니다.

같은 구현 커밋의 [원격 CI 34371488861](https://github.com/trevi00/zeus/actions/runs/34371488861)도
Windows·Ubuntu의 Python 3.12/3.14 네 작업과 실제 서비스 통합 작업까지 **다섯 작업 모두 통과**했습니다.
원시 결과는 `../../ci/34371488861.json`입니다. 뒤따르는 기록 커밋은 이 문서와 검증 증적만 추가하며,
소스·테스트·의존성·CI 정의는 바꾸지 않습니다.

추가 개선 이슈를 만들지 않았습니다. FA-029/#30은 운영 승인자 등록과 인증된 신뢰 정책 교체 등
남은 인수 조건 때문에 열려 있습니다. 전체 하네스의 분석·흡수·운영 준비 완료를 주장하지 않습니다.
