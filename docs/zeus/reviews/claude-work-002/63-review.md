# PR #63: 변경 요청 / 병합 보류

검토 head: `6c5734010044125e07db98523f22723b121453eb`. Codex 독립 검토입니다.

**[P1] 허용 필드에서 제외한 본문이 모델 입력에 남습니다**

policy.fields={kind:...}로 설정해도 minimize는 content와 project_ref를 input에 항상 넣습니다. 실제 결과가 dropped_fields=[content,project_path]라고 하면서 그 content를 그대로 반환합니다. synthetic sentinel로 확인했으며 실제 사용자 대화나 비밀은 사용하지 않았습니다.

위치: [src/codex_harness/domain/profile_privacy.py:165](https://github.com/trevi00/zeus/blob/6c5734010044125e07db98523f22723b121453eb/src/codex_harness/domain/profile_privacy.py#L165)

수정·재검증 조건: 모델 입력을 승인한 fields로 실제 제한하고 필수 필드 조합이면 정책 단계에서 명시적으로 거절하세요. temporary=none 정책도 scratch write와 일치하도록 검사해야 합니다.

검증: 해당 head의 대상 검사 **11 passed in 0.72s**, Ruff 통과. 개별 대상 검사에 PostgreSQL 통합을 활성화했습니다. 통과 횟수는 파일 간 중복을 포함하므로 고유 테스트 수로 합산하지 않습니다.

실제 모델·사람 인수·실기기·재부팅 검증은 수행하지 않았습니다. PR 수용과 연결 이슈의 완료/종료는 별도입니다.
