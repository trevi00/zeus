Codex 수정본 독립 재검토 — **변경 요청 유지**

대상 `60a6fa4c4d17a021321724f21c92245a066055ea`.

원래 지적한 동일 리뷰 재전송은 seq1을 유지하고 revoked를 뒤집지 않아 수정된 것을 확인했습니다. 다만 새 계약의 “재승인은 새 inspection receipt가 필요”는 아직 강제되지 않습니다.

**[P1] 기존 영수증을 그대로 쓰고 평가 문구만 바꾸면 재승인됩니다.** PASS→REJECT→원래 PASS의 `license_assessment` 끝에 공백 하나만 추가한 객체를 제출하면 동일 execution_id로 seq3과 adoption_eligible=true가 됩니다. `research.py:review`의 digest는 전체 문구를 포함하므로 같은 inspection을 새 review identity로 만드는 것은 가능합니다.

요청: 재전송의 내용 digest 검사와 별개로, rejection 이후 acceptance에 새로운 유효 inspection execution을 요구하세요. 동일 execution_id에서 문구만 달라지는 입력을 거부하거나 이전 순서로 처리하는 회귀가 필요합니다. 문구 공백 정규화만으로는 다른 문장으로 같은 우회가 가능합니다. 재현은 격리된 애플리케이션 fixture이며 실제 모델 승인 측정이 아닙니다.
