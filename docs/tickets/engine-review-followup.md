# Engine 공동 검토 후속 티켓

원격 증거 commit `e79d8d0`에 고정한 engine001의 실제 함수 관측과 공동 토론을 [FA-016 / GitHub #17](https://github.com/trevi00/zeus/issues/17)로 등록했다. 로컬 PG runtime 티켓과 GitHub 본문을 동기화했고, export는 같은 폴더 `FA-016.json`이다.

이 티켓은 과거 generation의 terminal shard가 최신 running 상태를 덮는 현상과 손상 shard가 병합0 후 삭제되는 현상에 한정한다. 원문 보존, event identity/순서, generation fencing, 실제 수집·ack·정리의 crash recovery 및 Windows/Linux/WSL 검증 기준을 포함한다. 티켓 생성은 구현·해소·배포가 아니다.

분리된 writeback 승인·소비·복구 계약은 [FA-015 / GitHub #16](https://github.com/trevi00/zeus/issues/16)에서 추적한다. 67개 신규 검토 기록을 더해 고정 tracked 분모의 707개에 기록이 있고, 2,029개 unreviewed 및 기존 기록의 미완료 의존·실행·인수 검증은 남아 있다.
