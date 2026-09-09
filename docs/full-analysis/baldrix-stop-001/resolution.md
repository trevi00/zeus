# Baldrix Stop001 — Codex·실제 Claude 공동 판단

고정 원본 `cbb5c3e6c9c4af6f86626474f4d7d62fd8e8a6d2`, `baldrix:scripts/handlers/stop:001`의 6개 전문·66,844바이트를 검토했다. 범위 해시는 `a5c82a94afd575c556e9ab8c0add3747d4cb12611a52f59e739a85080d964332`이다. [files.json](files.json)의 본문 검토와 [supporting-evidence.json](supporting-evidence.json)의 root 지원 19개(전문 16, 부분 3)를 구분한다. 지원 7개에는 이전 동일 바이트의 독해를 명시적으로 재사용했다. Claude의 추가 독해는 해당 원시 보고의 자체 범위이며 root의 독해 범위를 늘리지 않는다.

## 독립 판단과 토론

Root는 [독립 보고](codex-initial.md)를 먼저 작성했다. 실제 `claude.exe`의 읽기 전용 독립 응답은 [초기 보고](claude-initial.md), 같은 세션 `0e0cc292-7d78-4627-ad30-7d81d2d56c66`의 대조 응답은 [토론](claude-discussion.md)에 원문 그대로 보존한다. 초기 호출 377.75초, 토론 305.73초 모두 종료 0·`is_error=false`였으며 JSON/표준오류/명령/해시를 각각의 receipt에 남겼다. 이는 실제 Claude 검토 실행의 증거이며 원본 hook의 실운영 인수가 아니다.

양측은 상태 재구성의 필드 누락, 저장 성공 미확인, 파서와 결과 권위의 분리 부족, 학습 후보의 출처·수렴 검증 부족에 동의했다. 초기 칭찬·과장·철회도 보존하며, 최종 해석은 이 문서의 범위와 아래 정정을 따른다. 구현·흡수 승인은 아직 없다.

## 실제 실행으로 확인한 것

`run_observations.py`는 고정 Python 3.13 Alpine 이미지 `sha256:7415fbc3c9e4979cc717d92377ab2bc7b2b4a2af1ac03cc52b5f3f88efedaf3a`에서 network none, read-only 원본/루트, nonroot 65534, capability 제거와 시간·CPU·메모리 제한으로 실행했다. 원본 1,648파일 바이트는 전후 동일했다. 실제 임시 파일과 JSON 입력을 사용했고 함수 대체나 mocking은 하지 않았다. `work_unit_store.mark("save")`로 실제 watermark를 미리 기록해 autosave를 이번 관측에서 제외했다.

| 실행 | 관측 | 증거 |
|---|---|---|
| 원본 `lib.calendar_gate --self-check` | 24 assertions PASS, 종료 0 | `calendar-lib-self-check.stdout.txt`, `.receipt.json` |
| 원본 `handlers.stop.calendar_gate_emitter --self-check` | 12 assertions PASS, 종료 0 | `calendar-emitter-self-check.stdout.txt`, `.receipt.json` |
| 원본 Stop CLI, 태그 누락 2회 | 첫 호출이 block을 출력하지만 cwd/pending_fp가 null, 회고 카운터 3/5가 0/0. 다음 cwd 선택은 빈 목록. 두 번째 호출은 종료 0·출력 없음, retry=1·in_progress 유지 | `components.stdout.txt`의 `retry_cases.tag_miss` |
| 원본 Stop CLI, JSON 오류 2회 | 위와 동일한 필드 유실·재선택 실패, json_error_count=1 유지 | `components.stdout.txt`의 `retry_cases.json_error` |
| 원본 parser/helper | sid/iter 속성 태그 거부, advisory mode와 다른 태그 body 혼합, 빈 execute body 우선 | 같은 파일 `parser` |
| 원본 learner/helper | 이벤트 1건의 error 단어 3회가 후보 count=3, goal_reached=false도 convergence=true. JSON 배열 행은 후속 처리에서 AttributeError | `learner_single_event`, `learner_wrong_shape` |
| 손상 달력·정상 계획 문장 | scanner errors=1인데 adapter payload=null. 합법 Phase 2 문장은 warn 1건 | `calendar_all_corrupt`, `legitimate_phase_plan_analysis` |

세 실행 영수증 안의 component 프로그램에는 원본 CLI 자식 4개의 argv·입력 해시·출력·해시·종료 코드가 따로 있다. 이를 독립 설치 훅 4건이나 사람 인수 4건으로 세지 않는다. `test_autopilot_continue.py`는 부분 독해만 했고 실행하지 않았다. 실제 host의 Stop 재진입, evaluator/model/worker, brain autosave, 삼성 실기기, Windows/WSL의 원본 실행은 미검증이다.

## 합의한 결함과 적용 방향

1. **재시도 뒤 정상 cwd 경로에서 재개 누락.** `autopilot_continue.py`의 두 오류 분기는 새 상태를 만들면서 `cwd`, `pending_fp`, 두 회고 카운터를 전달하지 않는다. `list_active_sids(cwd_filter=...)`는 cwd가 없는 행을 제외한다. `advance_iter`는 보존하므로 분기별 결함이다. 파일 자체가 삭제된 것은 아니며 무스코프 조회·외부 복구 가능성은 남는다. Zeus는 PG task/attempt/generation에 결속된 단일 갱신으로 보존 필드와 카운터를 검증해야 한다.
2. **판정·저장·실제 실행의 권위 분리.** handler는 `write_state`의 bool을 확인하지 않고 출력할 수 있다. session_id 대신 cwd와 heartbeat로 고르는 경로는 동시 세션을 혼동할 수 있다. 실제 쓰기 실패·경합은 이번에 실행하지 않았다. `decision=block` 출력만으로 워커 종료·사람 승인·기능 성공을 확정하지 않는다.
3. **파서와 완료 근거의 타입·귀속.** mode를 반환하지만 main이 소비하지 않으며 태그 mode/body 검색이 분리되어 있다. cold-start 자기보고와 detected shared-sid evaluator 기록 요구를 구분해야 한다. 후자의 freshness는 실제 실행기/작성자 신원 검증과 동일하지 않다. 입력 `ac_verdict`가 축약을 생략해도 이후 evaluator까지 모두 우회한다는 주장은 하지 않는다. 축약의 세션 전체 leaf 집합에는 iteration/spec/expected leaf 분모가 없다.
4. **학습 후보를 수렴·자격으로 승격하지 않는다.** 반복 단어·이벤트, 실제 실패·수정·재발 관측은 서로 다르다. learner의 predicate는 payload를 무시한다. 정확한 원문 ID/hash와 결과·검증·작성자 귀속, 중복 방지·재처리 계약이 필요하다. 저장된 후보를 Astra→Sol→Terra 자격이나 자동 개선 성공으로 세지 않는다.
5. **미검사·손상·오류를 알림 가능한 상태로 분리.** 달력 adapter가 errors를 누락하면 손상과 정상 무부채가 동일해진다. 이 모듈은 pinned Stop 등록에 없으므로 현재 운영 훅 장애로 확대하지 않는다. 입력에 독립적으로 전역을 스캔하는 것은 명시된 설계이며, 이를 Zeus의 프로젝트/재진입 정책에 맞출지는 별도 설계 결정이다.
6. **문장 검사와 사용자 SDD 인수를 분리.** Phase 2 warn 오탐은 실측했지만 모든 계획·사람 승인 요청을 차단하는 것은 아니다. 길이·인용 제거·쿨다운·분기 조건이 있다. 90초 전역 쿨다운이 다른 프로젝트의 높은 등급을 억제할 수 있는 정적 경로는 남는다. 8단계 SDD의 실제 시나리오와 사람 판단을 regex PASS로 대체하지 않는다.

## 초기 보고 및 토론의 최종 정정

- learner는 stdout block을 내지 않는다. 등록 3개가 모두 block 채널이라는 초기 문장은 철회한다. 실행 모듈의 top-level import도 존재하므로 다른 파일이 모두 lazy import라는 주장 역시 철회한다.
- iteration 번호의 오프바이원은 입증되지 않았다. 두 분기 모두 persisted iter+1을 출력하며 완료 횟수로 해석하면 정합적이다. 전진 경로의 실제 실행은 이번에 없다.
- 재시도 후 영구 복구 불가, 모든 자가개선 측정 불가, 어떤 방법으로도 원문 추적 불가로 확대하지 않는다. 각각 정상 cwd 선택 누락, 해당 snapshot의 필드 유실, 정확한 원문 포인터 부재다.
- Claude 토론의 “미래 started_ts와 NaN 모두 영구히 wallclock cap을 연다”는 추가 일반화는 채택하지 않는다. 유한한 미래 시각은 시간이 따라잡으면 경과가 진행하므로 영구가 아니다. NaN/비유한 입력은 타입 검증 결함 후보이며 이번 실행으로 관측하지 않았다. Root 초기의 “경과 검사를 약화할 수 있다”를 유지한다.
- Claude가 표시한 미독 목록은 Claude 자신의 범위다. root가 직접/이전 동일 바이트로 읽은 reflexion_loop, compaction, atomic_json, orchestrator까지 양측 공통 미독이라고 부르지 않는다. 정확한 구간은 지원 원장에 따른다.
- `[]`가 learner helper를 실패시킨 실측을 무조건 매 턴 host 장애로 확대하지 않는다. 실제 선택된 최근 이력에 해당 형태가 포함되고 같은 경로가 실행되는 조건과 host 동작이 필요하다.
- 복구 안내의 status 변경만으로 소진된 카운터·시간 제한을 되돌릴 수 없다는 정적 판단은 유지한다. 그러나 정상 한 번의 재시도와 모든 terminal 분기를 동일 실측으로 세지 않는다.

## 남은 분석과 인수

전체 caller/config/test closure, 실제 등록 병합과 host 계약, evaluator 작성·소비 provenance, autosave/메모리 수명·동시성·실패 복구, 라이선스, Windows/Linux/WSL 등가와 인간 시나리오 인수가 남는다. 원본 6개 전문의 부분 공동 검토는 끝났지만 전체 하네스 분석·흡수·운영 준비는 미완료다. 이 결함은 별도 재시도 토픽 FA-017 초안에 연결하며 구현은 전체 분석 후 root가 맡는다.
