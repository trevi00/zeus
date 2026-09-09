# 미폐쇄 범위

Primary 본문 미독해 0개. inventory는 정확히 23개이고 supporting은 신규 primary로 계상하지 않는다. 이전 primary 3개는 전문 재독해했지만 coverage 증가가 아니다. quota_tracker와 psmux 2개는 lib:006 전문의 동일 바이트 재사용이며 fresh read로 기록하지 않았다.

지원 자료는 원장의 명시 구간만 읽었다. spec validator와 Java/DDL extractor 전체, mutation runner 복원 전체와 실제 runner 실행, staging의 모든 writer 및 동적 호출, researcher runner/timeout/모든 strike 소비자, 실제 모델 worker adapter, team CLI 상태 저장의 전체 수명주기, threshold metric/holdout 전체 및 모든 resolve 소비자는 미폐쇄다. 직접 시험을 읽지 않은 primary도 현재 시험 통과로 승격하지 않았다.

시험 증거의 종류를 구분한다. mutation 시험은 _run fake를 주입한다. team policy 시험의 terminate callback은 True를 반환한다. testgen 시험은 문자열과 ID 왕복 일치다. staging 시험의 일부 실패는 print만 하므로 함수가 예외를 내지 않았다는 결과와 구분해야 한다. 어떤 시험도 이번에 실행하지 않았다. 과거 실측·PASS·승인 문구는 현재 receipt가 아니다.

후속 검증 대상은 종료 요청/실제 종료 상태 분리, message replay·중복·부분 JSON, mutation의 판정 가능 분모와 runner 오류, 최종 주입문 의미 보존, threshold 제안값/TTL/정책 해시 결속, telemetry 누락과 시간창이다. 이 목록은 원본 실행·설치·거절된 probe 재시도 승인이 아니다.

사용자가 정의한 8단계 SDD와 실제 사람 인수, PG runtime/Git 정의 분리, 모델 자격·actual Claude 공동 검토, 라이선스, vendor 현행 사실, Windows/Linux/WSL 호스트 및 채택 승인은 아직 검증하지 않았다. 최종 흡수·구현 판단은 root의 후속 범위다.
