# lib009 정적 검토

고정 revision cbb5c3e6c9c4af6f86626474f4d7d62fd8e8a6d2의 10개, 88,013바이트를 모두 새로 전문 독해했다. 선행 전문 재사용은 0이며 지원 독해는 별도다. 원본 실행·import·probe·설치·네트워크 및 테스트 실행은 모두 0이다. 본문 독해 완료를 전체 분석 완료나 흡수 승인으로 올리지 않는다.

가장 중요한 경계는 writeback이다. 일회 토큰은 unlink 오류를 무시해 성공을 반환하고 동시 소비를 원자적으로 막지 않는다. operator context 형식 검사는 사람 승인을 인증하지 않는다. parser의 Gotchas 표식은 편집 범위를 제한하지 않으며 경로 정규식과 denylist는 허용 루트 및 적용 순간 파일 정체성까지 보장하지 않는다. CLI의 사전 이미지 재사용·복구 시도는 보존할 방어지만 다중 파일 거래와 외부 writer CAS를 대신하지 못한다.

ultrawork의 기존 ID 상태 보존은 의미가 달라진 계획에 과거 done을 붙일 수 있다. verifier의 밀도와 shell 정규식은 보조 신호이며 실제 인수 오라클이 아니다. wonder의 누적 재발은 자가개선 성공을 뜻하지 않고 직접 reflexion caller가 횟수와 cap을 추가 제한한다. work unit의 throttle 및 파일 저장, writeback 로그와 index는 경쟁 및 부분 저장을 별도로 처리해야 한다. webhook의 2xx와 retry도 최종 전달 또는 중복 없는 처리를 입증하지 않는다. win_quiet는 프로세스 생성 표시 설정이며 Windows의 인코딩·종료·ACL 동등성은 미검증이다.

Zeus에서는 8단계 SDD 요구·계획·산출물·검사·사람 인수의 동일 세대를 PG 정본으로 결속해야 한다. 실제 승인 주체와 proposal/target/diff/preimage를 묶은 원자적 소비, generation/CAS/lease, 변경 후 검증 및 감사 실패 복구를 설계한 뒤 적응 후보를 판단한다. 모델의 complete 문자열, mock 테스트, 과거 횟수나 상태 파일을 실제 인수로 승격하지 않는다. 이는 구조적 대응 제안이며 Zeus 구현 동등성 검증 결과가 아니다.

파일별 사실과 예외는 file-reviews.md 및 notes.md, 정확한 지원 구간은 supporting-evidence.json에 있다. 전체 caller/config/test 전이 폐쇄, 원문 라이선스와 외부 주장, 실제 Claude 독립 교차검토, Windows/Linux/WSL 실행, 운영 인수와 채택은 모두 남아 있다.
