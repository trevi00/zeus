# Baldrix CLI 001 — 본문 전수 의미 검토

고정 revision `cbb5c3e6c9c4af6f86626474f4d7d62fd8e8a6d2`의 `baldrix:scripts/cli:001` 23개, 199,004바이트를 전문으로 읽었다. manifest와 23개 SHA-256·크기가 모두 일치한다. 파일별 목적·실제 실행 경로·변형/제외 판단·Claude 의존·Windows/Linux 차이·Zeus 대응·테스트·미해결은 `files.json` 및 한국어 `semantic-notes.json`에 기록했다. 미검토 본문은 0개다.

이는 본문 범위 완료다. 전이 의존 구현과 유효 hook/config 등록, 외부 라이선스·원문, 나머지 테스트는 미완료다. `checkpoint.json`은 `body_coverage_complete=true`, `partition_complete=false`, `adoption_ready=false`를 구분한다. 검색이나 AST import 추출을 의미 검토 대신 사용하지 않았다. supporting 원장의 `full` 11개만 추가 전문 검토이며, 파일별 caller/config/test 검색 줄은 명시적으로 `search_hits_only_not_semantic_review`다.

## 채택을 막는 주요 결함

1. **카나리아 적용과 복원 계약이 지켜지지 않는다.** `canary_apply --no-regression`은 도움말에서 진단용이라고 하지만 실제 변경 적용을 허용한다. `lib.canary.run`은 regression callback의 예외를 잡지 않으므로 subprocess timeout이면 복원 없이 탈출할 수 있다. 복원 반환값을 무시하여 복원이 실패해도 “되돌렸다”고 출력한다. 선언 밖 쓰기 검사는 새 dirty 경로의 차집합만 보므로 기존 dirty 경로 변경과 ignored 파일을 놓친다. callback·경로 confinement·회귀 실행 전체 검토 전 직접 실행하지 않았다.
2. **수렴 event의 한 번 기록은 원자적이지 않다.** `debate_converge_check`는 기존 기록 조회와 append 사이 transaction/unique constraint가 없다. 이미 기록된 판정을 재사용하여 후속 severity invalidate와 충돌 판정을 재평가하지 않는다. `EventStore`는 생성자에서 디렉터리를 만들며 `session_id` 경로 이탈을 차단하지 않는다. payload hash도 replay에서 검증하지 않는다. `debate_stagnation_check`는 인자로 받은 approved를 ledger 확인 없이 신뢰하고, 전체 event를 요청 generation으로 제한하지 않는다.
3. **착지 기록과 writer schema가 어긋난다.** `debate_landing`은 `sha`/`this_sha`를 읽지만 현재 writer는 `snapshot_sha1`을 쓴다. landing 기록의 순서·generation·snapshot 일치도 확인하지 않는다. 기록 유무를 실제 코드 착지 판정과 구분한 방향은 유지하되, 관찰값 자체의 범위부터 바로잡아야 한다.
4. **시각과 미확인 데이터 처리에 모순이 있다.** `debate_doubts --since`는 ISO 문자열과 float를 비교하다 session을 조용히 건너뛸 수 있다. `debate_aggregate`는 이를 다른 방식으로 수용하지만 timezone 정규화 없이 문자열로 날짜를 비교한다. `action_evolver`는 시각 미파싱 event를 시간창에 포함하고 event 키 형태도 다르다. 빈 결과와 읽기 실패·schema 실패가 여러 CLI에서 같은 성공 상태로 나타난다.
5. **Atlas의 읽기 전용·승격 근거 설명이 구현과 다르다.** 검색은 인덱스 갱신과 쿼리 로그 쓰기를 포함한다. 승격 후보의 나이는 Git 이력이 아닌 mtime이며, 첫 scan root 기준 경로 재구성이 다른 프로젝트를 가리킬 수 있다. 같은 id·project basename·debate_sid 존재·오래된 파일은 의미 동등성이나 독립 승인 증거가 아니다.
6. **형식 변환과 지표는 의미 검증을 대신하지 않는다.** kha TODO 채우기는 worker 산문의 의미나 출처를 확인하지 않고 섹션을 교체한다. capability 정규화는 두 substring만으로 기존 계약을 지우거나 추가한다. agent 모니터의 파싱 성공과 dashboard의 섹션/파일 생성 성공은 작업 계약 이행이나 운영 건전성의 증명이 아니다. dashboard 일부 numeric 기대 필드가 escape 없이 HTML에 들어가므로 producer schema 검증도 필요하다.

## 공통 98개 검토와 연결

기존 `../baldrix-common/supporting-evidence.json`의 `lib.debate_convergence`, `commands/harness-debate.md` 전문 검토와 이번 wrapper/EventStore를 연결했다. canonical snapshot hash가 설계 코드 구현과 byte-identical하다는 증명은 아니며, 토론 실적·자동 승급 횟수·literal mutation token은 Zeus 승인 권한이 아니다. `debate_doubts` 재export는 실제 lib 함수를 넘기지만 wrapper의 attribute patch가 함수 globals를 바꾸지는 않는다.

`cucumber_scaffold`의 package 동일성은 standalone caller에게 맡겨져 있고 CLI가 testgen 결과와 비교하지 않는다. 이전 spec bundle TODO/빈 요구 PASS 결함과 함께, 생성 성공을 인수 테스트 성립으로 올리지 않는다. `apply_kha_fills`는 `SKILLS_DIR`에 쓰므로 “읽기 자산에 쓰는 CLI는 promote 하나”라는 paths 문서의 주장에도 반례다. `agents_capability` 역시 자산 agent 파일에 직접 쓴다.

Zeus의 대응 경계는 application workflow/monitoring, domain policy/SDD, skill routing이다. 기존 공통 분석의 소스 검토는 당시 revision 증거이며 현재 HEAD의 모든 변경을 재인증한 것이 아니다. Git은 정의, PostgreSQL은 runtime 권위로 유지하고 CLI에 정책을 복제하지 않는다. six-W·lease/generation·source/current revision·immutable execution receipt로 제안을 묶어 독립 검토해야 한다. 이 파티션은 구현하지 않았다.

## 실제 테스트 실행

소스와 전체 import 의존을 먼저 읽은 다음, 같은 immutable Linux Python 이미지에서 네트워크 없음·읽기 전용 source/root·권한 제거·비특권 사용자·bounded tmpfs/CPU/memory/pids·50초 container deadline으로 독립 실행했다. source scripts 외 사용자 home, credentials, 운영 state/assets는 mount하지 않았다. 컨테이너 이미지 pull은 금지했다.

| upstream 테스트 | 실제 결과 |
|---|---|
| `test_action_evolver_selfcheck.py` | exit 0, 14 assertions PASS |
| `test_agents_capability.py` | exit 0, 11 tests PASS |
| `test_agents_normalize.py` | exit 0, 9 tests PASS |

총 3개 프로세스, 34개 단언/테스트 PASS다. 각 `.receipt.json`은 정확한 argv, 이미지 digest, UTC 시각, 반환값, stdout/stderr 원시 base64 및 SHA-256을 보존한다. 이 영수증은 reviewer 실행 증거이며 Zeus fenced audit runner의 승인 영수증이 아니다. Native Windows·WSL·Claude live hook·production 실행은 하지 않았다. action self-check의 환경변수 복원 결함은 독립 프로세스 안에 제한되었으며, PASS가 그 결함을 없애지는 않는다.

다른 테스트는 not run이다. 특히 landing contract 테스트 전문은 읽었지만 `HOME/state/debates`의 실제 운영 원장을 요구하므로 source-only fixture 실행으로 가장하지 않았다. critic policy 테스트도 전문은 읽었으나 policy와 전이 저장 의존이 미완료라 실행하지 않았다. 나머지 matched 테스트/등록 원본과 pending mutation callback, brain store, calibration proposer, alert/decision/resident backend, Atlas embeddings, cucumber generator의 검토·격리 실행이 남았다. 라이선스·외부 논문/링크·개인 commit 실적도 미확인이다.

현재 지정된 23개 본문 범위에서 중지한다. 기존 공통 98개 raw receipt와 source snapshot, 설정, credentials, 운영 상태는 변경하지 않았다. 새 산출물은 `C:/Users/rudtn/zeus/docs/full-analysis/baldrix-cli-001/`에만 작성했고 구현·commit·push는 하지 않았다.
