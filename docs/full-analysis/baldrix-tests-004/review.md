# tests004 정적 검토

고정 revision cbb5c3e6c9c4af6f86626474f4d7d62fd8e8a6d2의 24개, 193142바이트를 새로 전문 독해했다. 이전 path-ledger의 24개 unreviewed 행과 해시를 별도 스냅샷으로 보존했다. 파일별 판단은 [file-reviews.md](file-reviews.md), 직접 지원의 후속 판단은 [supporting-notes.md](supporting-notes.md)에 있다. 전문 독해 완료와 전체 전이 폐쇄·실제 테스트·흡수 승인은 다르다.

주요 결함은 성공 분모와 권위의 혼동이다. 실제 자료가 없을 때 성공으로 반환하거나 embedded self-check의 True 사례로 집계하는 경로가 있다. DDL/ER는 stdout FAIL과 함수 반환값이 별개이며 endpoint 테스트 두 개는 pytest 단독 경로에서 실패 목록을 assert하지 않는다. 반대로 malformed/unknown·비공허 JOIN·live 최소 분모·같은 세대 충돌·CLI liberal 연결을 확인하려는 구체적인 방어도 존재한다.

Zeus로 옮길 때 gen1 approved의 snapshot 생략, survey에서 사라진 결정을 완료로 간주하는 규칙, surgery 시도 횟수, ack token, provider/model 문자열, 합성 vote와 citation 개수를 실제 승인·모델 자격·사람 인수로 취급하면 안 된다. classifier seed는 확정 스펙이 아니고 endpoint JOIN은 서비스 통합 실행이 아니다. 추출 입력의 누락/상한/손상과 출력 덮어쓰기, 판정 저장 실패, 동시 retry/append를 PG 정본 영수증과 요구사항별 증거로 관리해야 한다.

원본 import/실행/프로브/설치/네트워크 및 live 접근은 모두 0이다. 자체 검사기는 문서의 UTF-8/LF·해시·Git blob·바이트·범위·참조만 검증한다. 원본 코드의 과거 PASS나 설명은 이번 실행 증거가 아니다. 실제 Claude 전체 교차 검토, 라이선스와 외부 링크 원문, OS/모델 자격, 전체 전이 폐쇄, 8단계 SDD의 사람 인수 및 Zeus 채택은 모두 false/pending이다.
