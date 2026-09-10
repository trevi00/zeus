Codex 독립 검토 — **변경 요청 / 병합 보류**

대상 `bc0808946fabd7f481c66aee9bcae8f0fc835335`

[P1] 서로 다른 로컬 저장소가 같은 canonical target으로 취급됩니다.

`adapters/git.py:target_identity`는 remote가 없으면 모든 저장소에 문자열 local을 반환합니다. 실제 격리 Git 저장소 A에서 후보를 capture하고, A를 별도 경로 B로 clone한 뒤 B의 adapter.merge(candidate)를 실행하면 require_target과 patch 검사를 모두 통과하고 B에 변경이 병합됩니다. `different_repository=true`, `repository=local`, `merged_into_second.merged=true`로 재현했습니다. GitHub에는 이 반례의 push/merge를 하지 않았습니다.

요청: 로컬 대상도 저장소별 정규 identity(검증되는 Git 공통 디렉터리/명시적 안정 ID와 정책 등)에 결속하고, 원격 slug도 정규화 및 실제 대상 검증 규칙을 정의하세요. A의 승인이 B에 소비되지 않는 회귀를 추가하세요. 레거시 필드 생략을 무조건 허용하는 호환 경로는 새 계약 보장의 예외임을 명시하고 실제 승격에는 재검토/이행 규칙을 두는 것이 필요합니다.

독립 관련 검사: `28 passed in 25.29s` (실제 PostgreSQL 사용이 필요한 검사에는 현재 로컬 PG 연결). 제출 검사가 통과해도 위 반례는 미포함입니다.

동일 GitHub 계정의 PR에는 공식 Request changes가 불가능하므로 COMMENT review로 판정을 남깁니다. 이슈 종료나 인수 승인으로 해석하지 않습니다.
