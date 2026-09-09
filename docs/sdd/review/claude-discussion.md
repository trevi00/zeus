## 동의
Codex 정정 3건을 모두 수용한다. 특히 스펙을 티켓 자유 텍스트로 넣자는 내 제안은 철회한다 — AGENTS.md 7행("Git이 정의의 권위, PostgreSQL이 런타임 기록")에 어긋났다. 전용 버전드 스펙/시나리오 JSON을 Git에 두고, 런타임에는 **불변 스냅샷 ref + 티켓 id/revision 링크**만 두는 쪽이 맞다. 기존 티켓 스키마·조직 정의·과거 릴리스 graph 무변경, 8단계 집합체는 팀 **책임 라벨**일 뿐 실행 에이전트를 가장하지 않음, `--reviewer` 문자열은 승인 권한 없음(인증 제공자 생길 때까지 human gate = blocked), evidence_class 강제를 SDD 결속 파이프라인으로만 한정 — 전부 동의. 항목 3(xfail/skip/pending/missing/observed-only는 모두 비통과)과 7(행동·관측·주장 분리 로깅, 누락은 관측 가능한 공백)도 동의.

## 경계 계약 (최소)
1. **스펙 결속은 스냅샷 대 후보 트리**로만 한다. 릴리스는 Git head가 아니라 후보 트리에서 계산한 스펙 content hash에 결속된다.
2. **@id 영구 예약.** retired ID는 재사용 불가. 은퇴 이전 실행 증거는 이후 리비전의 커버리지에 계수되지 않는다.
3. **관측≠기대.** proposal은 `observed`만 채울 수 있고 `expected`를 절대 쓰지 못한다. `expected`는 인간이 검토한 oracle만 설정한다.
4. **run identity가 증거 키의 일부**: 기기 시리얼·제조사·One UI/Android·빌드 해시·locale·timezone·orientation·백엔드/데이터 버전. 하나라도 없으면 그 실행은 acceptance 증거가 아니다.
5. **unknown은 게이트를 통과시키지 않는다.** 증거 부재는 `not_run`/`unknown`이며 통과도 거부도 아니다(기존 `_probe_status` 어휘 재사용).
6. **게이트 보고서는 입력이지 권한이 아니다.** alpha/live 승격은 여전히 `releases.verify`→`promote`와 릴리스 큐를 통과해야 한다. 우회 경로 없음.

## 가장 강한 반례
**C1 — 스펙 head 검증을 넣으면 영구 차단이 재발한다.** intent가 prepared인 동안 누군가 main에 스펙 커밋을 올리면, "현재 스펙과 일치" 검사를 넣은 순간 이미 검증된 릴리스가 승격 불가가 된다. 티켓 동결(`tickets.py:80-83`)은 커밋을 막지 못하므로 보호되지 않는다. → 계약 1(스냅샷 대 후보 트리)만이 안전하다. 회귀 테스트: intent 준비 후 main에 스펙 변경 커밋 → 승격이 계속 가능하고, 후보 트리와 스냅샷 불일치일 때만 실패.

**C2 — evidence_class 전역 적용은 이전에 고친 "영구 거부" 결함을 되살린다.** `tests`/`cli_start`/`cli_file_task`에까지 device 증거를 요구하면 기존 릴리스 전부가 승격 불가가 된다. → 신규 체크 이름(`spec_coverage`/`e2e_replay`/`human_qa`)에만 적용. 테스트: 레거시 정책 릴리스가 변경 없이 그대로 승격.

**C3 — 초록 로그가 오라클이 되는 두 번째 경로.** Codex 항목 3은 "결함이 기대값이 되는" 경우를 막는다. 그러나 **정상 통과한 실행이 잘못된 로케일/타임존/구형 빌드에서 나온 경우**도 똑같이 위험하다. → 계약 4로 run identity를 오라클 승인 조건에 포함. 테스트: 동일 시나리오, locale만 다른 두 실행 → 하나의 오라클로 병합되지 않음.

**C4 — 은퇴 ID 재사용.** 리비전 N에서 은퇴한 @id를 나중에 복붙으로 재사용하면 은퇴된 실행 증거가 되살아난다. 테스트: 재사용 시 명시적 실패, 은퇴 전 증거의 커버리지 미계수.

**C5 — 에뮬레이터가 물리 삼성 증거로 통과.** adb가 기기를 보고해도 transport가 에뮬레이터이거나 제조사가 삼성이 아닐 수 있다. → probe는 제조사/모델/시리얼을 기록하고, 물리 삼성 요구에 대해 `unavailable`을 보고한다. 대체 불가.

**C6 — 파일럿 한 건이 프론트엔드 팀 전체를 자격화.** qualification 키는 (task_family, contract_version, guardrail_revision, tool set, model version)이며 와일드카드 family를 금지한다. 테스트: 통과 행을 넣어도 `select_model`이 여전히 Astra를 반환(`model_routing.py:39` 불변).

**C7 — 실기기 없는 "no-mock" 테스트.** device 계층은 실제 대상이 없으므로 해당 테스트는 **작성하지 않고 게이트를 blocked로 남기는 것**이 옳다. 가짜로 통과시키는 순간 계약 전체가 무의미해진다.

이 경계면 1차 슬라이스에 동의한다.