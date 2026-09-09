# Baldrix GSD references 001 독립 정적 검토

고정 cbb5c3e6c9c4af6f86626474f4d7d62fd8e8a6d2의 32개·178518bytes를 전부 새로 전문 읽었다. 선행 원장의32개 unreviewed 행을 보존했고 과거 독해 재사용은0이다. 직접 지원20개 파일의 지정 구간을 재독했으며 전역 primary로 추가하지 않는다. 원본 import·실행·collection·probe·설치·네트워크·실제 Claude 호출은0이다.

사람 검수 자동 승인과 decision 첫 옵션 자동 선택은 checkpoints 문서와 executor 소비부 모두에 있다. 이것은 사용자8단계 SDD의 실제 사람 핵심 시나리오 인수를 대신할 수 없다. 기존 PASS를 존재/basic sanity만으로 재검사하는 verifier, 현재 요구 gap을 계획 이후 발생했다고 PASS_WITH_NOTES로 처리하는 예시, INFO 무조건 허용과 count만으로 revision 중단도 exact revision의 독립 검수와 분리해야 한다.

구체 구현 대조에서 다음 차이를 확인했다. 모델 문서는 opus→inherit를 설명하지만 core resolver 기본은 alias 그대로 반환한다. context_window_tokens 문서와 실제 context_window 설정이 다르다. loadConfig는 오류에 null 대신 defaults를 주고 migration 중 파일을 쓰며, 모든 subrepo가 사라지면 기존 목록을 지우지 않는다. find-phase는 절대경로 설명과 달리 상대 POSIX 경로를 주고 읽기 오류를 notFound로 합친다. 범용 Task를 금지한 workflow가 advisor를 general-purpose로 호출하는 모순도 확인했다.

유지할 후보는 반증 가설, 실제 동작 중심 시험, 요구별 검증 근거, 명확한 실패·skip·미해결 표시, 수정 범위 제한과 사람 확인이다. Zeus에서는 이를 Git 요구/설계/위임 정책 정의와 PG 실행/검수/사람 승인 사건으로 나누고 source·target revision, 실제 모델 자격, 원시 결과, 미검사 분모를 결속해야 한다. 문서의 완료 배너·commit·출력 marker·모의 예시·교정 날짜는 실행 영수증이 아니다.

primary별 세부 판단은 [file-reviews.md](file-reviews.md), 직접 연결과 남은 범위는 [supporting-notes.md](supporting-notes.md)에 있다. planning-config의 generated 주장은 생성기/동등성이 확인되지 않아 제외하지 않고 전문 검토했다. 관련 시험의 실제 연결·원문 외부 catalog/라이선스·전체 전이 폐쇄·실제 Claude 영역 검수·Windows/Linux/WSL·모델 자격·사람 인수·흡수 승인은 모두 미완료다. 완료된 것은 이번32개 primary 정적 독해뿐이다.
