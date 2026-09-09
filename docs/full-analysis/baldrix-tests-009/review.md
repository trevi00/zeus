# Baldrix tests 009 독립 정적 검토

고정 revision의 primary 32개, 197463바이트를 모두 전문 읽었다. 선행 전문 재사용 0개이며 원본 실행/import/시험/설치/네트워크도 모두 0이다. 파일별 의미는 file-reviews.md, 실제 읽은 직접 구현·호출·설정 범위는 supporting-evidence.json과 supporting-notes.md에 기록했다.

가장 큰 차이는 성공 신호와 실제 증거다. pipeline은 출력 중 하나의 존재를 DONE으로 세고, Probe.passed는 재실행 없이 항상 True다. Reflexion의 LIVE 시험은 수제 상태를 helper에 넣는 임시 저장소 roundtrip이며 실제 모델/Stop E2E가 아니다. Ollama selfcheck는 available일 때 ask를 생략하면서 성공으로 집계한다. psmux의 pytest 조기 return과 repo_health의 저장소·네트워크 부재도 skip 분모를 숨길 수 있다.

직접 구현에서는 budget emit 예외에도 전송됨 플래그를 저장하고, quota load가 디렉터리를 만들며 increment는 읽기/쓰기가 분리된다. prompt failopen의 Agent fixture는 subagent_type 누락으로 prompt 처리 전 종료한다. PRD·private leak·coherence validator는 FAIL 출력과 rc 실패 전달이 분리돼 있다. 연구 추출의 structured와 provenance의 discovered는 schema 의미·원문 확인·모델 자격을 보장하지 않는다.

Zeus에는 명시적 부정 사례와 일부 수집/실패 전달 방어를 변형 후보로 남겼다. Git 정의와 PG 런타임 정본, 사용자 8단계 SDD의 실제 오라클·미검사 분모·사람 인수를 결속하기 전에는 채택하지 않는다. 모든 전이 closure, 실제 Claude 공동 검토, 라이선스와 외부 원문, Windows/Linux/WSL 및 모델 실행·실제 인수·흡수 승인은 미완료다.
