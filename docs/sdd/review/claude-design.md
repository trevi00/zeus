## 관측 vs 주장 vs 승인 (전제)
- **관측**: 실기기 로그·스크린샷·프로세스 exit code·커버리지 수치.
- **주장**: 모델이 만든 후보 시나리오·오라클 초안·요약.
- **승인**: 인간 QA 기록과 독립 리뷰. 관측도 주장도 자동으로 승인이 되지 않는다.
이 분리는 이미 있는 어휘와 동형이다: `tickets.py`의 `authority: advisory_only`/`claimed_reviewer`, `deployment.py:69-75`의 `not_run` skipped, contracts.md 20행("validation is not authentication").

## 구체적 결함/공백

**G1. SDD 8단계 중 4개가 durable 상태를 갖지 못한다.** 현재 액션 어휘는 plan/implement/rebase/research/audit_*뿐이고(`executor.py:310-412`), 릴리스 상태는 candidate→reviewed→verified→active뿐이다(`releases.py:92-137`). 1(스펙)·2(설계)·5(알파)·6(인간 QA)·8(인시던트 피드백)에 대응하는 레코드·게이트가 없다. 지금 SDD를 얹으면 3·4·7만 강제되고 나머지는 문서상 약속으로 남는다.

**G2. 티켓은 스펙이 아니다.** `tickets.py:7-8`의 필드는 자유 텍스트라 @id 시나리오·오라클을 담을 수 없다. 반면 Baldrix `spec_bundle.py:54-64`는 **시나리오 @id 유일성 = round-trip 키**를, `spec_roundtrip.py:9-12`는 MISSING/ORPHAN 드리프트를 이미 정확히 정의한다. Zeus에 필요한 계약이 외부 검증기에만 존재하고 하네스 도메인에는 없다.

**G3. "mock 금지"를 기계적으로 강제할 지점이 없다.** `deployment._check`는 exit code와 stdout만 본다. 증거의 **출처**(실기기 세션인지 fixture인지)를 구분하는 필드가 없으므로 stub 실행도 통과한다. `ai_spec_eval_coverage.py:50-55`가 경고하는 바로 그 실패 모드다 — "1바이트 stub이 M6를 통과하지만 adequacy를 증명하지 않는다". 참조 무결성 통과가 커버리지 충족으로 읽히면 안 된다.

**G4. 역할 분리(spec/frontend/backend/QA/devops) 추가가 감사 파이프라인을 정지시킬 수 있다.** `organization.json`에 에이전트를 추가하면 `digest({k: asdict(v) ...})`가 바뀌고, 이 값은 `research_control.graph`에 기록된다(`releases.py:40-42`, `:125-127`). `audit_gate.binding`은 graph를 결속에 포함하므로(`audit_gate.py:20-22`), **기존 승인들이 일괄 무효화**되고 `require_adoption`이 전부 거부된다. 조직 확장은 "이름 추가"가 아니라 재승인이 필요한 변경이다.

**G5. 모델 전이 전제가 문서와 충돌한다.** `model_routing.py:39`는 워크로드와 무관하게 Astra를 반환하고 `SIMPLE_IMPLEMENTATION_MODEL`/`IMPORTANT_IMPLEMENTATION_MODEL`(`:9-10`)은 미사용이다. `progressive-model-handoff.md:32-35,54`가 qualification registry와 승격/폴백 게이트 미구현을 명시한다. SDD가 "Sol 구현/Terra 단순"을 전제로 설계되면 미구현 게이트를 가정하게 된다.

**G6. 디바이스/앱/알파 인프라가 저장소에 없다.** Android 앱, Device Farm, Storybook, shadcn/토큰 자산이 없고, 파이프라인의 Flutter/Node overlay는 `incomplete_definition=true`로 ID만 있다(`baldrix-pipeline.md:26-31`). 5~7단계는 현재 **관측 불가**다.

## 최소 일관 구현 경계 (1차)

**범위: 1·2단계의 불변 산출물 + 4단계 오라클 결속까지. 5~8은 계약과 상태만 정의하고 실행은 blocker로 남긴다.**

- **INV-SPEC-001(제안).** 스펙은 티켓 리비전의 한 필드로 저장한다(`ticket_revisions` 재사용 — 이미 불변·content_hash 결속이 있다). 시나리오 @id는 전역 유일하고 리비전 간 안정하며, 삭제 대신 `retired`로만 표기한다. 스펙 변경은 기존 동결/supersede 메커니즘을 그대로 상속한다(`tickets.py:80-93`).
- **INV-ORACLE-001(제안).** 후보 시나리오는 `source: device_session` + 세션 아티팩트 ref가 있어야 생성되고, 인간 리뷰를 거친 것만 `oracle_status: reviewed`가 된다. **reviewed 오라클만 acceptance에 계수된다.** 모델이 만든 오라클은 주장일 뿐 승인이 아니다.
- **INV-EVIDENCE-CLASS-001(제안).** 모든 검증 증거에 `evidence_class ∈ {device, emulator, fixture}`를 필수화하고, `fixture`는 어떤 acceptance도 만족시키지 못한다. `_check` 결과에 이 필드를 추가하고, 없으면 `not_run`으로 취급(합성 pass 금지, `deployment.py:69-75` 어휘 재사용).
- **커버리지는 기계적으로만.** spec @id ↔ 실행된 E2E 산출물 @id의 MISSING/ORPHAN만 계산하고, 의미적 적정성 판정은 **명시적으로 descope**한다(ai_spec_eval_coverage의 태도를 그대로 채택). "manifest validates ≠ coverage adequate"를 계약 문구로 못 박는다.
- **채널 분리.** `deployment` 포인터를 `deployment:alpha`/`deployment:live`로 나누고, live 승격은 alpha 증거 + human QA 레코드를 요구한다. 기존 `promote`의 expected_active CAS(`releases.py:116`)를 채널별로 확장하되 롤백 계약은 유지.
- **릴리스 정책 확장.** policy checks에 `spec_coverage`, `e2e_replay`, `human_qa`를 추가한다. 증거가 없으면 pass도 fail도 아닌 `not_run`이고, 릴리스는 승격되지 않는다.
- **모델 전이는 기록만.** qualification registry를 **데이터 구조 + 전이 증거 기록**으로만 먼저 만들고, `select_model`의 반환값은 계속 Astra 고정. registry가 비어 있으면 라우팅 변경 금지를 테스트로 고정한다.

## 지금 실제로 가능한 검증 (mock 아님)
기기 없이도 실행 가능: ① 스펙 왕복(@id 유일·리비전 간 안정·retired 보존), ② MISSING/ORPHAN 계산의 정확성, ③ `evidence_class: fixture` 증거가 acceptance를 만족시키지 못함, ④ 증거 부재 시 `not_run`이며 승격 불가, ⑤ 채널 승격 CAS와 alpha 미존재 시 live 차단, ⑥ registry가 비어 있을 때 `select_model`이 여전히 Astra를 반환, ⑦ 조직 확장이 graph digest를 바꾸어 기존 승인을 무효화함을 **명시적으로 재현**(G4를 테스트로 고정).
기기 도입 이후에만 가능: 실기기 세션 → 후보 시나리오 → 인간 리뷰 → E2E 재생 1건의 왕복.

## 안전한 blocker (fail-closed)
- Device Farm/앱 빌드/Storybook 부재 → `spec_coverage`/`e2e_replay`/`human_qa`는 `not_run` + 사유. **rejected가 아니라 미실행**이며 승격만 막는다(정상 후보를 영구 거부하지 않도록, 이전 라운드 계약과 동일).
- 알파 채널 미구성 → live 승격은 `blocked: alpha evidence unavailable`, 재조정 경로를 결과에 담는다.
- 조직 역할 확장 → graph digest 변경이므로 재승인 절차를 거치기 전에는 병합 금지.
- 모델 전이 → registry가 실제 전이 증거를 갖기 전에는 라우팅 하향 금지.

## 인증하지 않는 것
삼성 실기기/태블릿 동작, Device Farm·MCP·Storybook 도입 가능성, 알파 배포 준비도, 그리고 2,592개 로컬 원본 경로의 의미 흡수 — 어느 것도 이 검토로 인증되지 않는다. Codex 조사 결과와 대조 후 1차 경계를 합의하자.