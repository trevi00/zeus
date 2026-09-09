# Baldrix tests 012 정적 검토

고정 revision cbb5c3e6c9c4af6f86626474f4d7d62fd8e8a6d2의 24개 시험 파일, 193879바이트를 모두 이번에 전문으로 읽었다. prior-path-ledger.json의 미검토 24행을 보존했으며 과거 독해를 새 독해로 재사용한 수는 0이다. 직접 지원 38개는 지정한 구간만 읽고 별도 원장에 남겼다. 원본 import·수집·시험·프로브·설치·네트워크 실행은 모두 0이다. 자체 검사 성공은 원본 시험 통과를 뜻하지 않는다.

가장 중요한 발견은 다음과 같다.

1. team 정책 CLI는 죽은 프로세스를 응답 완료로 세고, 종료 요청이 실패해도 killed 상태를 저장한다. echo worker는 실제 모델을 호출하지 않으며 문서의 SIGTERM/EOF 처리를 구현하지 않는다. 종료·결과 회수·모델 자격·사람 인수를 별도로 확인해야 한다.
2. 임계치 ready 파일의 값과 revision을 apply가 확인하지 않는다. 파일 쓰기와 ready 소비는 원자적이지 않다. 개선 지표도 실제 정답 기반 precision가 아닌 임계치 경계 비율이며 표본이 없으면 1.0이다. 제안 성공과 승인·배포를 분리해야 한다.
3. stub-faker 시험의 전역 실패 리스트는 pytest에서 assertion으로 전파되지 않는다. surgery에는 or True인 무조건 통과 검사가 있다. test-depth는 문자열/함수 이름만으로 깊은 검사라고 분류하며 빈 Java 시험 클래스·테스트 ID 일치도 PASS/coverage로 보인다. 이들 표식은 무 mock 인수의 오라클이 아니다.
4. telemetry_report는 UTC의 Z를 버리고 지역 시간으로 해석한다. timefmt의 보정과 불일치하고 해당 시험은 오래된 이벤트의 실제 제거를 주장하지 않는다. 일부 시험은 기본 telemetry/ACK 또는 psmux 상태 경로에 접근할 수 있어 실행 전 추가 격리 검토가 필요하다.
5. 형식 검사와 agent frontmatter의 tools 선언은 파일 존재·이름을 검사한다. 실제 도구 사용 영수증·OS 권한·모델 자격을 입증하지 않는다. 누락·구문 오류·skip가 통과와 섞이는 분모를 보존해야 한다.

파일별 충분한 판단은 [file-reviews.md](file-reviews.md), 직접 구현·호출·설정 대조는 [supporting-notes.md](supporting-notes.md)에 있다. files.json과 supporting-evidence.json은 원시 Git blob·바이트·SHA·행 범위와 실제 문서 anchor를 결속한다. 원본 전문이나 민감한 운영 데이터는 보고서에 복제하지 않았다.

이 한정 범위의 primary 정적 독해만 완료했다. 전체 전이 의존성/호출 폐쇄, 실제 Claude의 전체 영역 공동 검토, 라이선스·외부 주장, Windows/Linux/WSL 실행, 모델 자격, Zeus PG/Git 정본과 8단계 SDD의 실제 동등성, 사람 인수 및 흡수 승인은 모두 미완료다. 구현·운영 상태·공유 원장·티켓·commit/push는 변경하지 않았다.
