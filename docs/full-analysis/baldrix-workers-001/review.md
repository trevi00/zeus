# workers 한정 검토

4개 12,006바이트를 새로 전문 독해했다. 고정 revision은 cbb5c3e6c9c4af6f86626474f4d7d62fd8e8a6d2이며 worker/테스트 실행은 0이다.

인터페이스는 spawn/list/kill만 제공한다. 결과·오류 수집과 exit 상태, generation/lease, 프로세스 트리 종료를 보장하지 않는다. 오래된 동일 ID handle이 새 worker에 작용할 수 있다. subprocess의 duplicate lock과 bounded wait는 보존할 방어지만 PG fencing과 격리를 대신하지 못한다.

psmux는 일반 tmux까지 선택하면서 Windows quoting을 사용하고 window 수를 worker 수로 센다. 성공 rc는 실제 작업 완료 또는 자식 트리 종료 영수증이 아니다. 별도 lib.psmux 테스트를 이 adapter의 검증으로 셀 수 없다. team의 nohup 지시와 ultrawork 내부 Agent 설명은 모든 작업이 이 registry를 쓴다는 테스트 주석과도 상충한다.

Zeus는 승인된 argv/cwd/env와 불변 attempt handle, PG lease, 실제 출력·종료 영수증을 연결한 뒤 변형을 검토해야 한다. 문자열 DONE, mock registry, sleep roundtrip은 사용자 SDD 인수가 아니다. 세부는 file-reviews.md와 supporting-evidence.json에 기록했다. 전체 caller/config/test 폐쇄·라이선스·실제 Claude·모델·OS·채택은 미완료다.
