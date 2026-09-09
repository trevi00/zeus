# Harness contract tests 001

고정 revision `a3f8b3be9a0a389329de6e16a6c7db81782041a3`의 primary 11개, 195,089 bytes를 전문 검토했다. [review.md](review.md)는 파일별 판단, [files.json](files.json)은 원문 해시와 판단 연결, [supporting.json](supporting.json)은 직접 읽은 지원 구간, [checkpoint.json](checkpoint.json)은 집계와 경계다.

원본 시험·import·probe·network·install은 실행하지 않았다. 자체 metadata recorder와 Ruff의 결과만 validation.json에 별도 기록한다. 문서의 과거 PASS와 합성 fixture는 현재 운영 성공이 아니다. 실제 Claude 공동 검토, 전체 호출 폐쇄, 라이선스, Windows/Linux/WSL, 사람의 인수와 모델 자격, Zeus 구현 등가성 및 채택은 미완료다.

지원 자료는 primary 수에 합산하지 않았다. 기존 보고서의 의미 판단을 재사용하지 않고 이번에 읽은 원문 구간을 기록했다. 공유 coverage와 원본·runtime·구현은 변경하지 않았다.
