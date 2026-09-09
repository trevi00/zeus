# 다음 의사결정 복구 구현의 대조 결과

실제 Claude 독립 검토와 루트의 현재 코드 추적으로 다음 계약을 확인했습니다. 아직 구현 증거는 아닙니다.

- diagnose는 `_fail_task`가 만든 원본 실패 아티팩트와 occurrence ID로 결속합니다. 원래 작업의
  최신 attempt/status 전체를 해시하면 정상적인 후속 재시도까지 과거 진단을 무효화하므로 사용하지 않습니다.
- review_lead와 review_conductor는 원래 workflow_inbox 보고서, source task/decision의 검증된 결과,
  후보·기존 release·hook·관련 improvement loop를 대조해야 합니다. 이미 해당 리뷰가 기록됐거나
  release_queue로 넘어간 상태는 다시 리뷰시키지 않습니다.
- audit_review는 기존 audit_gate.binding을 재사용하고 현재 actor의 기존 리뷰와 최종 approval을
  검사합니다. 검증 중 새로 생성되는 inspection receipt 전체를 고정하면 정상 실행도 무효화되므로
  기존 binding이 지정한 근거만 결속합니다.
- research_lead/proposal은 현재 require_dispatch가 의도적으로 막는 과거 경로입니다. 복구 명령이
  이 제한을 해제할 수 없으며, 명시적인 deferred 원인을 유지해야 합니다.
- 복구 시점의 관련 상태 검사는 claim 직전과 효과를 기록하기 직전에도 필요합니다. 마지막 검사는
  각 native commit 경계에 두어 자신의 정상적인 상태 변경을 stale로 오판하지 않아야 합니다.

원격 CI의 두 번째 동률 시각 테스트 실패를 먼저 수정·검증한 뒤 이 계약의 구현을 이어갑니다.
