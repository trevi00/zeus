# Zeus SDD · 삼성 Android 휴대폰과 태블릿

현재 구현은 **스펙·증적 준비와 검토 원장**이다. 8단계 실행 엔진, 사람 인증, 실기기 인수, 알파/라이브 배포를 완료한 상태가 아니다. `zeus-sdd.spec.json`은 사용자가 요청한 하네스 기능의 검토 초안이다. 실제 앱의 업무 시나리오는 앱과 핵심 사용자 경험이 정해진 뒤 별도 스펙으로 작성한다.

## 현재 사용 가능한 흐름

```powershell
uv run zeus sdd inspect docs/sdd/zeus-sdd.spec.json
uv run zeus sdd view docs/sdd/zeus-sdd.spec.json --output .runtime/sdd/review.html
uv run zeus sdd device-check
```

위 명령은 DB를 시작하지 않는다. `view` 결과는 네트워크 요청 없는 독립 HTML이며 삼성 휴대폰/태블릿 필터, GWT, 금전 위험 표시, 디자인·환경 계약과 8단계 미충족 근거를 표시한다. 같은 경로에 다른 내용을 덮어쓰지 않으므로 스펙 변경 후 새 출력 경로를 사용한다. 브라우저에서 문서를 보는 것과 해당 기기에서 앱을 인수 테스트하는 것은 서로 다른 검증이다.

이미 초기화된 Zeus PostgreSQL과 로컬 티켓이 있을 때:

```text
zeus sdd register SPEC.json --ticket TICKET_ID --ticket-revision N
zeus sdd status ITERATION_ID
zeus sdd import-log ITERATION_ID --environment ENVIRONMENT.json --events EVENTS.json --source SOURCE_NAME
zeus sdd propose ITERATION_ID --observation OBSERVATION_ID
zeus sdd view-iteration ITERATION_ID --output REVIEW.html
zeus sdd advance ITERATION_ID --sequence N
```

`register`는 현재 티켓 리비전에 결속하고 불변 스펙 아티팩트와 해시 연결 이벤트를 저장한다. `--git-revision COMMIT`을 추가하면 지정된 Git 트리에서 읽는다. 생략하면 `working_tree_draft`로 남는다. 정의의 원장은 Git이고 PostgreSQL은 반복 실행·관측·알림 원장이다. 다른 내용의 스펙 등록은 새 리비전이 되며 이전 반복의 증적 추가는 차단된다. 기존 티켓의 GitHub Issues 투영 기능을 그대로 사용한다.

`advance`는 현재 **blocked 결과를 기록**한다. 사람의 이름을 입력하거나 로그에 `passed`를 넣어도 다음 단계를 승인하지 않는다. 인증된 사람의 결정을 받는 제공자와 실행 증적 검증기가 구현될 때 실제 전이를 연결한다. alpha/live는 기존 release 검증·승격 경로를 사용해야 한다.

## 계약

스키마의 실행 기준은 `src/codex_harness/domain/sdd.py`이다. 알 수 없는 필드·빠진 시나리오·중복 ID·참조 없는 요구사항·삭제된 시나리오 ID·은퇴 ID 재사용을 거부한다. 은퇴 시나리오는 `status: retired`로 보존한다.

환경 JSON은 다음 필드를 모두 가진다:

```text
device_id manufacturer model form_factor platform os_version one_ui_version
webview_version app_build_hash locale timezone orientation backend_revision
data_revision reset_receipt physical_device
```

`physical_device`는 boolean, 나머지는 문자열이다. `form_factor`는 phone/tablet/desktop/unknown, `orientation`은 portrait/landscape/unknown이다. 가져온 환경은 주장된 데이터이며 실제 기기 인증이 아니다. 민감한 원본 시리얼 대신 일관된 가명 식별자를 사용하고 토큰·계정 정보는 가져오기 전에 제거한다.

이벤트 JSON은 배열이며 각 항목의 정확한 필드는 `sequence, scenario_id, kind, name, observed, source_ref, timestamp, observed_timestamp`이다. `kind`는 action/observation/assertion/gap, 순번은 양의 정수이며 증가해야 한다. 시간은 시간대가 있는 ISO8601이고 원본 시간이 없으면 `timestamp: null`로 기록한다. 수집 시각은 필수다. 연속 번호가 아니거나 gap이 있으면 공백 알림을 남긴다. `source_ref`는 출처를 설명하며, 문자열 자체가 출처의 진실성을 인증하지 않는다.

로그로 만든 proposal은 관측과 구조적 coverage만 반환한다. 기대 결과는 원래 스펙의 인간 검토 대상이며 관측으로 자동 채워지지 않는다. 알림은 PostgreSQL `sdd_notifications`에 로컬 저장되고 `status`/`view-iteration`에서 확인한다. 동일 반복·코드별 횟수를 누적한다. 전체 하네스의 OpenTelemetry 계측 및 외부 알림 발송은 아직 구현되지 않았다.

## Replay와 모델 이전

출력 어댑터에서 검토 문서는 `.html`, 재생 초안은 `.py.review` 확장자를 요구해 일반 테스트 자동 수집을 방지한다. 시나리오별 초기화 통합이 아직 없으므로 활성 시나리오가 둘 이상이면 replay 생성을 거부한다. 단일 시나리오 생성도 전제 조건·초기화의 실제 검증을 대체하지 않는다. 요구사항은 `status: active/retired`를 갖고, 기존 ID의 의미(statement/risk)를 변경하려면 새 ID로 만들고 이전 ID를 은퇴시킨다.

`zeus sdd export-replay SPEC.json --output test_replay.py.review`는 구체적인 Android 앱·빌드와 모든 기대 결과의 명시적 selector/assertion 바인딩이 있을 때만 Appium Python 코드를 생성한다. web/PWA/WebView 컨텍스트 전환, 실제 초기화 수행·검증, 공급자 서명 검증은 미구현이다. 생성물은 미실행 코드이며 실기기 테스트 완료 증거가 아니다. 금융 요구사항은 백엔드 정산 통합이 준비되기 전까지 생성도 차단한다. 입력값은 `ZEUS_TEST_*` 환경 변수 참조로 전달한다.

`zeus sdd transfer-record ITERATION_ID --file TRANSFER.json`의 정확한 키는 `task_family, contract_hash, guardrail_hash, toolchain_hash, source_model, target_model, evidence_refs`이다. hash는 64자리 소문자 SHA256, 증적은 실제 로컬 `sha256:` 아티팩트 참조이다. Astra→Sol 또는 Sol→Terra 단계만 기록하며 와일드카드 작업군을 거부한다. 등록 결과는 `recorded_unqualified`; 기존 모델 라우팅을 변경하지 않는다. 재현 평가·오류 허용 기준·실측 비용·자격 만료와 회수까지 구현해야 자동 이전을 활성화할 수 있다.

## 다음 구현 티켓

| 토픽 | 완료 판정에 필요한 증거 |
|---|---|
| 실제 앱 스펙과 사람 승인 | 앱 저장소·핵심 여정·인증 주체·스펙 및 증적 해시에 결속된 결정 |
| 삼성 실기기 세션 | 정확한 phone/tablet 모델, 실제 세션·빌드·버전·초기화 확인, 종료 및 장애 복구 |
| Device live / interact / MCP | 같은 세션에서 에이전트와 REPL이 순서를 공유하고 모든 행동·실패를 기록 |
| 관측 → 실제 Replay | 출처 바인딩·명시적 전제 조건·검토된 oracle·초기화·반복 실측·회귀 실패 검출 |
| 금전 흐름 | 실제 격리 백엔드의 멱등 처리·거래 상태·취소·정산 대조와 사람 인수 |
| 8단계 실행 및 팀 구성 | 역할 권한, 후보 트리 결속, alpha/live 증적, 점진 배포와 rollback, CS 재진입 |
| 디자인 자산 | 대상 앱의 shadcn/Lucide/토큰과 실제 Storybook 상태·접근성 검증 |
| 전체 관측과 모델 이전 | 명령/작업/모델 호출 trace, 누락 알림, 재현 가능한 버전별 qualification |

위 목록은 아직 등록·발행하지 않은 티켓 토픽이다. 전체 Baldrix/harness 흡수나 Device Farm 구축 완료를 의미하지 않는다. 조사 근거와 채택 범위는 [research.md](research.md)를 참고한다.
