# tests001 한정 정적 검토

26개, 191,653바이트의 전문을 새로 읽었다. 빈 package marker도 포함한 파일 분모이며 실제 실행 테스트 수가 아니다. 원본 실행·import·probe·network·install 및 테스트 실행은 0이다. 고정 revision은 cbb5c3e6c9c4af6f86626474f4d7d62fd8e8a6d2다.

가장 중요한 발견은 검사 결과의 의미와 격리 경계다. run_all/run_units는 격리 실패 후 원래 환경에서 계속할 수 있고 링크된 자산은 실제 read-only가 아니다. 모든 skip도 rc0이며 pytest 라우팅은 일부 fixture 이름의 정규식에 의존한다. compaction 테스트는 실패를 global list에 넣어 main만 rc1로 반영하므로 pytest 직접 실행 시 검사 실패가 PASS로 보일 수 있다.

여러 happy path는 실제 인수를 증명하지 않는다. 빈 AC tree approved, 1바이트 평가 stub, free-text Agent success, 환경변수의 critic_invoked, 직접 쓴 evaluator verdict 및 '# done' summary는 각각 형식·상태·관찰 fixture다. fresh/stale 차단, bool 타입 거절, duplicate 처리와 bounded retry 등 보존할 방어는 있지만 독립 모델 검토와 사람 승인 영수증을 대체하지 못한다.

직접 SUT에서 추가로 확인한 차이는 gate predicate truthiness, event를 run 수로 세는 metrics, compaction prepend simulation과 실제 append, 원래 hook보다 긴 테스트 timeout, confirmed shared sid 이전 실패의 inline fallback이다. 구체 근거와 미검사 항목은 file-reviews.md 및 supporting-notes.md에 있다.

Zeus 변형 후보는 Git 정의·PG runtime 정본, generation/lease/CAS와 정확한 실행 영수증, 요구·검사·사람 인수의 분리다. 전체 전이 폐쇄·실제 Claude 교차검토·라이선스·Windows/Linux/WSL·모델 자격·인수 및 채택은 미완료다. 공개 산출물에는 긴 원본과 인증정보를 복제하지 않고 고정 경로·구간·해시로 근거를 남겼다.
