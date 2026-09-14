PR #72 U002 독립 1차 검토 완료: 네 항목 수정 요청, 병합 보류입니다.

검토 head `ce49433e6d84570e737e40edd917c117b625d983`. 독립 Windows PG+Redis 220 passed/0 skipped, Ruff 통과, 최종 PR CI 10/10을 확인했습니다. 그러나 실제 임시 자식으로 살아 있는 자손을 종료 확인하는 경로, exit7과 다른 session 결과가 task 성공까지 도달하는 경로를 재현했습니다. 실측 러너의 호스트 한도가 label 변경으로 초기화되는 문제도 확인했습니다.

[검토·수정 지시·설계 결정](https://github.com/trevi00/zeus/pull/72#pullrequestreview-5200446046)

네 결함 수정 후 Windows 단일 작업 제한 운영을 검토합니다. WSL native 모델 미실행은 별도 미충족 분모로 유지하며 Windows 제한 시험의 선행 조건과 분리했습니다. restricted 구성 검증의 추가 1회는 수정 후 별도 캠페인에서만 허용하며 이번 검토에서 모델 호출은 하지 않았습니다.

전체 분석·운영·자격 검증 완료 판정이 아니며 이슈는 OPEN, U003은 미착수입니다. WSL disposable Docker 2/4 실패 보고도 원인 해결로 간주하지 않습니다.
