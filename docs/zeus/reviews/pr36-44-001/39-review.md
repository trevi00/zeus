Codex 독립 검토 — **변경 요청 / 병합 보류**

대상: `aaa180a312d68adee0fb32eea6fef0f529bd943f`

**[P1] 예전 승인 응답 재전송이 최신 거절을 뒤집음**

위치: `application/research.py:312–320`

정상 양측 승인 → conductor 거절(seq2, adoption_eligible=false) → 최초의 동일 accepted review 객체 재전송 순서로 호출하면 기존 digest의 기록을 seq3로 덮어쓰고 adoption_eligible=true가 됩니다. 새로운 검사나 승인 신원이 없어도 오래된 PASS가 최신 거절을 무효화합니다. 독립 반례로 재현했습니다.

수정 요청: 이미 기록된 review digest/실행 신원의 재전송은 idempotent하게 처리해 과거 기록의 순서·시각을 바꾸지 않아야 합니다. 재승인은 새로운 검토 실행/근거에 결속하고 PASS→REJECT→옛 PASS replay에서 계속 거절되는 회귀 테스트를 추가해 주세요.

제출된 관련 테스트는 독립 실행에서도 통과했지만 위 경계 반례는 포함하지 않습니다. 반례는 격리된 검증 데이터로 실행했으며 운영 인수·실제 모델 실행으로 표시하지 않습니다. 기존 이슈에서 수정해 주세요. 새 이슈를 만들거나 이 PR/연결 이슈를 종료하지 않습니다.

GitHub ??? ???? ?? ?? Request changes? ???? ????. ? ?? ??? ??? ?? ???? ?? ?????.
