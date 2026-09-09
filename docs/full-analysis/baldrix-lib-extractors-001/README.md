# Extractors 정적 검토 체크포인트

고정 baldrix revision의 12개 원본 전문(86,101 bytes)과 직접 지원 13개 경로의 명시 구간을 읽었다. [파일별 분석](review.md), [원본 원장](files.json), [지원 원장](supporting.json), [체크포인트](checkpoint.json), [남은 검증](remaining.json)을 구분해 보관한다. 이전 보고서의 전문을 재사용하지 않았고, 지원 구간은 primary 신규 수에 넣지 않았다.

주요 발견은 flowchart validator 이름 불일치와 미호출 검사에 대한 PASS 표시 가능성, 원문 내용 대신 출처 개수만 검사하는 floor, 주석 제거로 바뀌는 출처 행, 추정 관계·인용·신뢰도 표기의 의미 차이다. 이는 정적 연결 분석이며 현재 결함 재현이나 실행 성공 판정이 아니다.

원본 실행·import·시험·probe·network·install은 모두 0회다. 자체 메타데이터 기록기와 Ruff 결과는 validation.json에만 기록한다. 전체 호출 폐쇄, 실제 Claude, 라이선스, Windows/Linux/WSL, 사람의 경험 인수, 모델 자격 및 채택 승인은 미완료다. 기존 lib007과 공유 coverage, source/runtime/구현/commit/push는 변경하지 않았다.
