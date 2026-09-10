Codex 독립 검토 — **변경 요청 / 병합 보류**

대상: `c06a7746bcb80a6ff2499a80b84d857c88dd9f59`

**[P1] 열린 질문이 있는데 whole_analysis_complete가 true**

위치: `application/research.py:278–279`

tracked path/subsystem coverage를 채운 뒤 partition에 open_questions를 남기면 coverage()는 whole_analysis_complete=true를 반환하지만, 같은 상태의 propose()는 `Open audit questions remain`으로 거절합니다. 독립 반례로 두 결과를 함께 확인했습니다. 사람에게 보여주는 완료 판정과 실제 게이트가 불일치합니다.

수정 요청: 완료 판정에 현재 partition의 열린 질문을 포함하고, 미결 분모를 결과에 보여 주세요. 기존 proposal의 완결성 규칙과 공유하거나 두 경로를 함께 검증하는 테스트를 추가해 주세요. 이 수정도 등록하지 않은 로컬 자산까지 분석 완료했다는 증거가 되어서는 안 됩니다.

제출된 관련 테스트는 독립 실행에서도 통과했지만 위 경계 반례는 포함하지 않습니다. 반례는 격리된 검증 데이터로 실행했으며 운영 인수·실제 모델 실행으로 표시하지 않습니다. 기존 이슈에서 수정해 주세요. 새 이슈를 만들거나 이 PR/연결 이슈를 종료하지 않습니다.

GitHub ??? ???? ?? ?? Request changes? ???? ????. ? ?? ??? ??? ?? ???? ?? ?????.
