# 예제 그래프와 테스트 분모: root 교차 검토

이번 범위는 새 primary 82개다. 예제 서비스 구성 20개는 root가 전문과 직접 지원 16개를 새로 읽고 실제 Claude 독립 검토와 토론 대상으로 삼았다. Baldrix tests004 24개, tests005 22개, harness unit001 16개는 세 검토 agent가 전문과 기록된 직접 의존 구간을 읽었다. root는 세 보고서 및 tests004 파일별/지원 판단을 읽고 아래 경계를 대조했다. agent의 모든 원본 실행은 0이며 62개에 대한 실제 Claude 전수 교차 검토도 아직 미완료다. root 보고서 검토를 그 소스 전문의 독립 재독으로 세지 않는다.

예제의 계약 차이는 의도된 fixture이며 README도 비배포 대상으로 명시한다. 원본 수동 시험 2/2, graph 26+36, DRIFT 4/OK 2 및 committed artifact의 동일 바이트를 실제 Linux 격리 환경에서 관측했다. 그래프가 같다는 사실은 실제 메시지/결제/사람 경험의 성공을 의미하지 않는다. 기본 gate의 BLOCKED 방어를 유지하면서 미등록 상태 이름과 0개 선언에서의 공허 성공을 문제로 기록한다. 자세한 실행·초기 독립 의견·정정은 [resolution](baldrix-example-fleet-001/resolution.md)에 있다.

[tests004](baldrix-tests-004/review.md)는 없는 자료를 embedded self-check의 True로 합산하거나 stdout FAIL과 반환값을 분리하는 경계를 확인했다. 반대로 같은 세대 hash 충돌, 비공허 JOIN, live 최소 분모와 실제 CLI 연결을 검사하려는 방어도 있다. 발견사항은 정적이며 원문의 과거 PASS나 함수 개수를 현재 실행으로 옮기지 않았다. snapshot 없는 첫 세대 승인·survey에서 사라진 항목·ack token은 사람 인수 권위가 아니다.

[tests005](baldrix-tests-005/review.md)는 실제 replay subprocess의 부수효과, 임시 STATE_DIR 외의 import 시점 홈 결속, 디렉터리 mtime을 이용한 scan 생략, 저장 실패 후 승격 반환을 정적으로 추적했다. 금지된 probe는 수행하지 않았다. greenfield의 pending Steps와 ID 왕복 CLEAN은 first RED/실제 통과가 아니며, flowchart 이름과 flow validator 매핑의 불일치는 형식 검증조차 실제 연결됐는지 확인해야 함을 보여준다. `_ok` 수동 소비와 pytest 경로의 차이는 root 예제 테스트 전문과도 일치한다. root가 수행한 별도 예제 실행을 이 22개 전체의 실행으로 확장하지 않는다.

[harness unit001](harness-unit-tests-001/review.md)은 15개 시험 스크립트와 격리 helper 1개를 다룬다. 출력 패턴만 보는 trigger, 0개 golden case의 true, 압축 후 사라지는 인수 분모, 실제 bundle header를 제외한 문자 예산, 응답자만의 quorum 및 marker 제거로 통과하는 workup을 정적 한계로 기록했다. token 절감이나 점수 향상이 필수 근거 누락에서 발생하지 않는지 확인해야 한다. unknown/null, append 거절, 매개변수화 검색, 작성자 origin 보호 같은 실제 방어도 보존한다. 조건부 실제 호스트 canary는 이번에 실행하지 않았다.

공통 설계 후보는 선언·수집·실행·검사·skip·unknown·통과의 분모를 분리하고 source/scenario/attempt/reviewer 신원을 연결하는 것이다. 사용자 8단계 SDD의 처음은 사람의 핵심 시나리오이며 끝은 실측과 사람 인수다. 모델 등급의 자격 이전이나 자동 개선은 이 사이의 증거를 생략할 수 없다. Git 정의와 PG 런타임 원장은 유지하고 파생 VIEW·JSONL·점수를 별도 정본으로 만들지 않는다.

이 체크포인트는 전체 분석·라이선스·실제 모델 자격·기기·원본 Windows/WSL·사람 인수·Zeus 채택 완료를 주장하지 않는다. 직전 공개 main a98f29e의 CI 34335243370은 Windows/Linux 4축과 integration 모두 성공했으며 그 실제 결과를 docs/zeus/ci에 보존했다. 이 Zeus CI 성공을 원본 하네스 전수 인수로 해석하지 않는다.
