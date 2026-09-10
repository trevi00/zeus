# PR #56: 변경 요청 / 병합 보류

검토 head: `9ba590b1d7891048244a208fdd27ded92dd4df6c`. Codex 독립 검토입니다.

**[P1] Python enum 멤버 누락을 HIGH로 표시합니다**

실제 파일의 class Status(Enum): A=1; B: int=2를 추출하면 A만 남고 fidelity=HIGH, symbols_found=1, unresolved=0입니다. B도 실제 enum 멤버인데 AnnAssign을 조용히 건너뜁니다.

위치: [src/codex_harness/adapters/seam_extraction.py:66](https://github.com/trevi00/zeus/blob/9ba590b1d7891048244a208fdd27ded92dd4df6c/src/codex_harness/adapters/seam_extraction.py#L66)

수정·재검증 조건: AnnAssign 등 지원할 syntax를 추출하고 미지원 멤버 후보는 분모/unresolved에 포함하세요. 이름이 Enum인 일반 class를 enum으로 오인하는 import/base 해석 범위도 명시해야 합니다.

검증: 해당 head의 대상 검사 **11 passed in 1.00s**, Ruff 통과. 개별 대상 검사에 PostgreSQL 통합을 활성화했습니다. 통과 횟수는 파일 간 중복을 포함하므로 고유 테스트 수로 합산하지 않습니다.

실제 모델·사람 인수·실기기·재부팅 검증은 수행하지 않았습니다. PR 수용과 연결 이슈의 완료/종료는 별도입니다.
