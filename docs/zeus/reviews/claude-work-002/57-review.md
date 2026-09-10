# PR #57: 변경 요청 / 병합 보류

검토 head: `f6acba25b9379328ab32bec522a1072b3745653c`. Codex 독립 검토입니다.

**[P1] 검증 서비스의 이중 __enter__로 배포 검사가 실패합니다**

endpoints=services.__enter__() 후 with services가 다시 __enter__를 호출합니다. 실제 임시 PostgreSQL/Redis Docker stack에서 첫 진입은 성공, 두 번째는 directory.mkdir의 FileExistsError로 실패했습니다. 두 번째 with 진입 실패는 __exit__를 호출하지 않아 stack도 남습니다. 검수 중 만든 stack은 직접 정상 정리했습니다.

위치: [src/codex_harness/adapters/deployment.py:151](https://github.com/trevi00/zeus/blob/f6acba25b9379328ab32bec522a1072b3745653c/src/codex_harness/adapters/deployment.py#L151)

수정·재검증 조건: 컨텍스트는 정확히 한 번 진입하고 진입 실패와 본문 실패의 cleanup을 모두 검증하세요. 실제 _run의 서비스 시작→incumbent/candidate test→종료까지 재실측해야 합니다.

검증: 해당 head의 대상 검사 **9 passed in 7.83s**, Ruff 통과. 개별 대상 검사에 PostgreSQL 통합을 활성화했습니다. 통과 횟수는 파일 간 중복을 포함하므로 고유 테스트 수로 합산하지 않습니다.

실제 모델·사람 인수·실기기·재부팅 검증은 수행하지 않았습니다. PR 수용과 연결 이슈의 완료/종료는 별도입니다.
