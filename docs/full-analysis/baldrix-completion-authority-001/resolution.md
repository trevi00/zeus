# 완료 근거 권위 — Codex·실제 Claude 공동 검토

원본 `cbb5c3e6c9c4af6f86626474f4d7d62fd8e8a6d2`의 ac_tree·axis_scores_log·completion_gate·coverage_gate **4개 전문, 39,337바이트**를 검토했다. scope SHA-256은 `a69ea250c2a6f568e2d3e2ea0e421bf88a4095b98beff991311030613f8c430b`이며 [checkpoint](checkpoint.json)에 해시 직렬화와 구성 경로를 명시했다. lib001/lib002 일부의 의미 검토로, 두 전체 파티션 완료가 아니다.

## 독립 검토와 실제 실행

Root [초기 판단](codex-initial.md)을 작성한 뒤 실제 Claude의 [독립 보고](claude-initial.md)를 읽고, 실측을 제시해 [동일 세션 토론](claude-discussion.md)을 수행했다. Claude 세션 `42f42c83-d619-4a22-b2eb-937b25073eb2`의 초기 호출 298.71초, 토론 243.91초 모두 종료 0·is_error=false다. Read/Glob/Grep로 제한한 명령, 원시 JSON·표준오류·본문·해시를 receipt와 함께 보존했다.

고정 Python 3.13 Alpine 이미지 `sha256:7415fbc3c9e4979cc717d92377ab2bc7b2b4a2af1ac03cc52b5f3f88efedaf3a`, network none/read-only source/nonroot 및 자원·시간 제한에서 다음을 실행했다. 원본 1,648개 파일의 바이트는 전후 동일했다.

| 실행 | 결과 | 범위 |
|---|---|---|
| 원본 `python -m lib.completion_gate` | 28 assertions PASS | 선언된 truth table 및 일부 입력 가드 |
| 원본 `test_ac_tree.py` | 17 tests PASS | 제공한 predicate·메모리 callback을 사용하는 순수 단위 테스트 |
| `component_observations.py`가 원본 helper 직접 호출 | 종료 0, 아래 반례 관측 | 실제 임시 JSONL·파일·입력, mocking 없음 |

원시 stdout와 receipt는 각각 `completion-self-check`, `ac-tree-unit`, `components` 접두사로 저장했다. component stdout에는 원본이 받아들인 비표준 JSON 숫자 `NaN`이 그대로 있으므로 엄격 JSON으로 정규화하지 않는다. 이 실측은 실제 모델/evaluator provider/설치된 hook host/worker/사람 인수/삼성 기기 또는 Windows/WSL 원본 실행이 아니다.

## 함께 확인한 관측

- `schema_version=null`, `event=unrelated`, `completeness=false`, caller `ts=200`, `verdict=approved`가 실제 로그에 저장되고 floor=100에서 approved로 선택됐다. 기록의 존재·시각만으로 실제 평가 대상과 실행 권위를 증명하지 못한다.
- timestamp=NaN 또는 floor=NaN도 approved로 선택됐다. verdict 배열은 TypeError, iteration 기록의 배열은 AttributeError였다. 손상 JSON과 유효 JSON의 잘못된 shape 처리가 다르다.
- `cross_target=False`여도 caller가 넣은 true marker가 남았다. 전역 확인 후 append하는 정적 구조에는 동시 중복 가능성도 있지만, 동시 실행은 이번에 하지 않았다.
- 순서가 뒤집힌 서로 다른 두 iteration 행에서 count=2, floor는 마지막 행이 아닌 최대 시각이었다. 이것은 **중복 replay의 실제 재현이 아니다**. 중복 event ID를 구별하지 않는 것은 별도 정적 판단이다.
- pure completion 함수는 문자열 `"false"` 두 개와 approved 입력에 complete를 반환했다. require_evaluator=True이고 evaluator가 없으면 iterate하는 국소 방어는 실제로 유지됐다. iter=99의 clean 완료는 cap보다 clean 판정을 먼저 하는 선언된 정책이며, 그 순서 자체를 오류로 단정하지 않는다.
- empty AC와 문자열 `"false"`를 반환하는 GateLeaf는 approved였다. advisory bool은 ValueError로 거절했다. 문서 기본 축 `완성도`도 ValueError였다. 같은 설명·다른 predicate는 같은 leaf ID를 갖는다.
- emitter가 `/source` 디렉터리를 파일로 여는 실제 IO 오류를 내도 evaluate_emit은 approved를 반환했다. 이는 의도적으로 잘못된 목적지를 준 오류 관측이며 운영 디스크 장애·crash recovery를 실행한 것은 아니다.
- 빈 atlas는 0/0 ready였다. absent repo가 있는 동일 atlas는 global에서 0/1 not ready지만 빈/알 수 없는 touched scope에서 0/1 ready였다. 모든 경우 residual 배너는 보존됐다. 범위 한정 결과를 전체 인수 승인으로 소비하면 안 된다.

## 문서·producer·consumer 대조와 정정

실제 Python writer가 없다는 Claude 초기 주장은 철회됐다. Root가 읽은 evaluator_dispatcher의 checked/unchecked emitter와 추가로 확인한 `cli/milestone_step.py:175–217`은 provider 호출 결과를 로그에 전달하는 Python 경로를 갖는다. 전자는 bool 반환을 유지하는 adapter와 버리는 adapter를 구분한다. **코드 경로가 존재함**은 해당 provider가 이번에 실제 실행됐다는 증거가 아니다. marker도 caller payload로 넣을 수 있으므로 특정 함수가 모든 기록의 유일한 발행자라고 부르지 않는다.

`commands/harness-autopilot.md`와 `harness-evaluate.md`의 emit 지시는 기본 경로의 문서 계약이다. `ts`를 넣지 말라는 지시는 `setdefault` API가 강제하는 서버 시각과 같지 않다. default 축뿐 아니라 직접 읽은 validator 표의 한국어 축도 AC 클래스의 영문 도메인과 다르다. 문서 예시의 lambda late binding은 직역 시의 조건부 문제이며 모델이 항상 같은 코드를 만든다고 주장하지 않는다. 같은 문서의 공유 SID 등록 예시는 cwd 없이 new_state를 호출하므로 프로젝트 선택 연결도 별도 확인 대상이다.

현재 fallback_to_legacy_e2의 590–638행은 iterate/escalate만 만들며 approved 분기가 없다. fallback 이벤트명을 selector가 허용하는 것과 현 fallback producer가 완료를 발행하는 것은 다르다. 이 가설을 현재 실패 재현으로 쓰지 않는다.

유한 미래 timestamp가 영원히 fresh라는 주장도 철회한다. floor가 해당 시각을 넘으면 제외된다. NaN 입력 실측, 초 해상도·포함 비교, 세대 identity 부재를 각각 다룬다. GC 역시 SessionStart 도달·mtime cutoff·삭제 성공이 조건이다. 활성 참조/lease 확인 부재는 정적 결함 후보지만 30일 후 모든 증거가 무조건 삭제되거나 archive가 전혀 없다고 증명하지 않았다.

Claude 토론의 “gate 리스트가 비면 Stop reducer는 None”도 축소한다. Root가 390–424행을 재확인했으며 **gate와 유효 advisory가 모두 없을 때** None이다. gate가 없어도 유효 advisory 점수가 있으면 iterate/approved를 계산한다. empty aggregate의 approved와 빈 event reduction의 None 차이, advisory bool 처리·임계치 복제의 차이는 남는다. 이를 모든 advisory-only 입력의 판정 차이로 확대하지 않는다.

“어느 레코드에도 artifact identity가 없다”도 요구 검증 수준으로 읽어야 한다. logger는 임의 필드를 허용하므로 caller가 artifact 필드를 넣을 수 있다. 문제는 읽은 producer payload와 selector가 **그 결속을 필수로 검증하지 않는다**는 것이다. 각 caller의 자기보고·provider 결과·실제 runner receipt를 구별해야 한다.

## Zeus 반영 요구와 남은 일

유효한 경험은 gate/advisory 타입 분리, advisory 수치 검증, evaluator 필수 모드의 누락 거절, 부작용 없는 읽기 경로, 기록 크기 제한, checked emitter, 명시적 residual이다. 이를 PG task/attempt/generation·Git spec/artifact revision·독립 실행 영수증·사람 시나리오 분모와 결합하는 설계가 필요하다. 완료 판정과 증거 저장을 분리 실패했을 때 미확인 상태를 보존하고, 학습 후보·실적·모델 자격을 caller marker로 승격하지 않는다.

[FA-018 초안](../../tickets/drafts/FA-018.json)에 완료 근거 권위 토픽을 분리했다. 전체 caller/config/test closure, evaluator/provider 전체 구현, 실제 concurrent append/short-write/GC·재시작, OS별 sid/경로·실행 계약, 라이선스와 사람 인수가 남는다. 전수 분석·흡수 승인·시범 운영 준비는 **미완료**이며 원본 및 Zeus runtime 구현은 이번에 변경하지 않았다.
