# PR #61: 변경 요청 / 병합 보류

검토 head: `b7c301cf6f7de1133d2ee1be12354f0ad829a703`. Codex 독립 검토입니다.

**[P1] pretty-printed JSON의 dangling reference가 통과합니다**

kind=json 파일은 문서 단위로 유효성 검사하지만 참조 검사는 모든 형식에 대해 줄 단위 json.loads를 합니다. 존재하지 않는 parent를 가진 같은 JSON이 compact에서는 invalid, indent=2에서는 valid/dangling_references=0입니다.

위치: [src/codex_harness/domain/snapshot_integrity.py:155](https://github.com/trevi00/zeus/blob/b7c301cf6f7de1133d2ee1be12354f0ad829a703/src/codex_harness/domain/snapshot_integrity.py#L155)

수정·재검증 조건: 검증한 parsed record 집합을 참조 검사에 재사용하고 json/jsonl을 구분하세요. 중첩/비문자 reference는 예외 누락 대신 명시적 invalid로 처리하는 검사도 필요합니다.

검증: 해당 head의 대상 검사 **10 passed in 0.99s**, Ruff 통과. 개별 대상 검사에 PostgreSQL 통합을 활성화했습니다. 통과 횟수는 파일 간 중복을 포함하므로 고유 테스트 수로 합산하지 않습니다.

실제 모델·사람 인수·실기기·재부팅 검증은 수행하지 않았습니다. PR 수용과 연결 이슈의 완료/종료는 별도입니다.
