# kha 진입점 한정 검토

`kha-add-phase`부터 `kha-new-workspace`까지 디렉터리명 사전순 범위의 미검토 33개, 118,053바이트를 기록했다. 원본 revision은 `cbb5c3e6c9c4af6f86626474f4d7d62fd8e8a6d2`다. **새 전문 독해 7개, 기존 동일 바이트 전문 지원 독해 재사용 26개**이며 후자는 새 독해로 세지 않는다. 재사용 항목에는 이번 1–24행 선언 보강을 별도로 기록했다. files.json의 각 링크에서 파일별 판단과 원본 receipt·ledger·review 해시를 확인할 수 있다.

주요 발견은 선언과 실제 소비 절차의 차이다. `mutates:no`인 audit/map/summary/forensics도 보고서나 상태를 쓴다. lock·snapshot·확인이라는 단어가 실제 helper의 원자성이나 권한 강제를 입증하지 않는다. seed는 new-milestone 자동 재등장을 약속하지만 확인한 소비 본문에서 연결을 찾지 못했다. debugger에는 새 HYPOTHESIS 계약과 구형 flat 파일·반환 형식이 공존한다. intel refresh의 요구 파일명과 구현 파일명이 다르고, 잘못된 날짜도 fresh로 표시될 수 있다.

AI-SPEC은 1바이트 stub 통과를 실제 평가 적절성으로 해석하지 말라고 명시한다. 직접 validator도 내용·모델 평가·taxonomy 동등성을 검사하지 않는다. manifest 누락은 blocking 실패 분모에 들어가지 않으며 경로 resolve 후 repo containment 검사도 없다. 직접 테스트 1개 파일의 15개 함수는 합성 입력과 tempdir 오라클을 정적으로 읽었을 뿐이다. **원본 실행·import·collection·probe·설치·network·실제 Claude는 모두 0**이다.

Zeus 변형은 사용자의 8단계 정의를 Git에 유지하고 PG에 시도·worker 소유권·실제 검사 결과·사람 인수를 기록하는 방향이다. GSD phase 번호, Markdown checkbox, 모델 승인 문자열, 파일 존재와 mtime는 그 전이 증거를 대신하지 못한다. qualified delegation과 실제 사람 핵심 시나리오를 별도로 확인해야 한다. 문서의 과거 PASS·토론 승인·외부 API·링크 주장은 현재 검증 결과로 승격하지 않았다.

전문 분모는 닫혔지만 전체 호출·설정·테스트 전이 폐쇄는 미완료다. 전체 상류 분석, 실제 Claude 공동 검토, 라이선스, Windows/Linux/WSL 실행, 모델 자격, 사람 인수, 현재 Zeus 동등성 및 채택 승인은 모두 false/pending이다. 자체 검사 성공은 기록의 바이트·참조·범위·UTF-8·공백·Ruff에만 적용한다. 공유 coverage·ticket·runtime·source·stage·commit·push는 변경하지 않았다.
