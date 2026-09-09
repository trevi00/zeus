# baldrix scripts/lib:008 체크포인트

23개/196,126바이트 primary 전문을 정적으로 검토했다. 기존 primary 중복 3개를 동일 revision·SHA·Git blob와 이전 원장/보고서 해시로 결속했으며 신규 primary 경로는 20개다.

Supporting 23개는 이번 전문 1개·부분 20개와 이전 동일 바이트 전문 재사용 2개로 분리했다. 원본 실행·import·시험·프로브·network·install은 0회다. 자체 메타 기록과 Ruff 결과만 validation.json에 적었다.

- [파일별 의미와 연결 판단](review.md)
- [Primary 원장](files.json)
- [정확한 지원 구간과 재사용 근거](supporting.json)
- [분모와 완료 경계](checkpoint.json)
- [남은 검증](remaining.md)
- [자체 검사 결과](validation.json)

주요 발견은 종료 실패도 killed에 기록하는 팀 CLI, 판정 불가 mutant만 남아도 SURVIVED가 될 수 있는 집계, 최종 주입문과 다른 스킬 축약 검증, 제안값을 읽지 않고 소비하는 threshold ready-flag다. 모두 정적 판단이며 현재 호스트에서 결함을 재현했다는 주장이 아니다.

모든 primary 판정은 `body_reviewed_call_test_trace_pending`이다. 전체 호출 폐쇄·actual Claude·라이선스·모델 자격·Windows/Linux/WSL·사람 인수·Zeus 채택은 미완료다. 지정 폴더 외 수정과 commit/push는 하지 않았다.
