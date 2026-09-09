# Baldrix tests 006 정적 검토

고정 partition의 24개, 198562바이트를 모두 전문 읽고 파일별 의미를 file-reviews.md에 기록했다. 새 전문 독해 24개, 선행 전문 재사용 0개다. 원본 실행·import·테스트·설치·네트워크는 모두 0이다. 본문 독해 완료와 실제 시험 성공을 분리한다.

주요 발견은 검증 분모와 성공 신호의 차이다. inventory_drift는 pytest에서 _ok의 False를 assert하지 않는다. heartbeat traversal 시험은 예외가 없어도 실패하지 않는다. harness_health의 수동 main은 pytest 전용 시험 하나를 포함하지 않는다. hook E2E는 잘못된 JSON을 무출력으로 취급하고 파괴 명령 차단을 필수로 요구하지 않으며, clean Stop 입력은 실제 응답 검사를 시작하지 않는다.

직접 구현에서는 bridge section 전체 삭제/빈 상태가 과거 이력 검증 전에 PASS하고, 캐시가 최신 commit이면 현재 상태 검사가 생략될 수 있다. pollution detector는 개별 retract 실패에도 ready flag를 삭제하고 0을 반환한다. 임시 HOME 격리는 고정 USERPROFILE 경로, fixture 전 import, 환경 상속을 모두 막지 못한다. 설치 문자열과 과거 PASS, 빈 디렉터리, synthetic 지표는 실제 hook 실행이나 사람 인수의 증거가 아니다.

유지할 후보는 명시적 부정 사례, schema 경계, 일부 history 삭제 검사, pytest 수집0 실패, 수동 main의 failure token 전파다. Zeus에는 그대로 채택하지 않고 Git 정의와 PG 런타임 정본, 사용자 8단계 SDD의 요구·증거·사람 인수를 결속하는 방식으로 변형해야 한다. 형식 통과·빈 대상·SKIP·부분 실패를 실제 승인과 구별해야 한다.

정확한 primary와 supporting 범위 및 해시는 files.json과 supporting-evidence.json, 진척은 checkpoint.json에 있다. 미기재 caller/config/test 구간과 전체 전이 의존성, 실제 Claude 독립 공동 검토, 라이선스/외부 원문, 모델 자격, Windows/Linux/WSL 실행, Zeus 구현·인수·채택은 미완료다. 전체 분석 완료 또는 흡수 승인을 주장하지 않는다.
