# 스킬 텔레메트리의 측정 대상 분리 — 매칭·순위·본문 도달·행동

기존 FA-012 / GitHub [#13](https://github.com/trevi00/zeus/issues/13) / `ZEUS-97f3257c362a` 개정 2의 구현입니다.
상류 평가기의 "precision"은 실제로 음성의 미매칭 비율(TN/(TN+FP))이었고, 양성은 `match AND winner`, 음성은 `match`만
판정해 서로 다른 결정을 한 지표로 섞었습니다. 실제 CLI에서 음성 0건 PASS, 자격 미달 경쟁자가 정상 target을 밀어낸
FAIL_RECALL, 동점 target 우대를 관측했고, 실제 hook은 다른 후보·경로 신호·스택·pipeline boost·본문 예산을 쓰므로 이
평가기 PASS를 모델 입력 도달이나 행동 품질로 볼 수 없습니다([common-quality 공동 검토](../../../full-analysis/cross-review-common-quality/resolution.md),
[skill routing runtime 공동 검토](../../../full-analysis/baldrix-skill-routing-runtime/resolution.md): "로그가 최종 전달 상태를
입증하지 않는다"). 교차검토 합의는 "원시 매칭·후보 순위·본문 도달·실제 행동의 측정 대상을 명시한다"입니다. 새 이슈나
분석 후보는 추가하지 않았습니다.

## Zeus에 있던 같은 틈

Zeus의 라우팅 매니페스트는 스킬별 `tier`(full/pointer/external_pointer/unmatched/legacy)와 `rendered_hash`를 이미
기록하지만, 실행마다 원장에 남는 **관측 이벤트**(`skill_history.events[].top`)는 상류 producer와 같이 점수·차원만
담았습니다. 그래서 감사(`skill_telemetry_audit`)는 "몇 번 매칭됐나"만 셀 수 있었고 "몇 번 전문 본문이 실제로 모델
입력에 들어갔나"는 top5 점수에서 추정해야 했습니다 — 상류의 "telemetry top5·matched_count는 배정 전 후보"와 같은
형태입니다.

## 변경

- `adapters/skill_history._prepare_history`: 관측 `top` 항목에 `tier`와 `rendered_hash`(전문 본문일 때)를 함께 기록.
  관측 지문(fingerprint)은 점수 키만 쓰므로 재전달 중복 제거는 그대로입니다.
- `application/skill_history.record`: `tier`는 정의된 5개 값만, `rendered_hash`는 비어 있지 않은 문자열만 허용.
- `domain/skill_audit.audit_history`: 스킬별 `rank_first_count`(그 관측에서 최고 점수였던 횟수)와
  `delivery{full, pointer, external_pointer, unmatched, legacy, unknown}` 카운트 추가. `unknown`은 tier가 기록되기 전의
  관측입니다. 보고서에 `measurement_targets`(raw_match / rank / body_arrival / behavior="not measured by telemetry")를
  명시하고, 서로 다른 결정을 섞은 비율(precision/recall)은 만들지 않습니다.
- `adapters/skill_audit.render_text`: 스킬마다 `ranked first: m/n; delivered full body: k, pointer: p, tier unknown: u
  (match != delivery != behavior)` 줄 추가.
- `docs/contracts.md`: `INV-SKILL-HISTORY-001`에 측정 대상 분리 문장 추가.

## 재현과 검증

- `tests/test_skill_audit.py::test_match_rank_and_body_arrival_are_separate_counts_not_one_precision`: 두 스킬이 3회
  관측에서 점수 역전·동점을 겪는 입력으로 count/rank_first/delivery가 각각 다른 수(4·3·{full 2, pointer 1, unknown 1} 등)로
  나오고, 보고서에 "precision" 문자열이 없으며, 행동은 미측정으로 표기됨을 확인.
- `::test_recorded_observations_keep_tier_and_reject_unknown_tiers`: 저장된 관측이 tier·해시를 보존하고, 알 수 없는 tier·빈
  해시는 거부, tier만 추가된 같은 선택의 재기록은 새 관측이 아님.
- `tests/test_project_skills.py::test_real_skill_history_annotation_and_recovery_survive_other_task_observation`: fixture
  런타임의 실제 Executor 경로에서 기록된 관측이 `tier`/`rendered_hash`를 갖고 감사 `delivery['full']`이 실제 전문 전달
  횟수와 같음을 확인(기존 검사에 단언 추가).
- 기존 `test_skill_audit`·`test_skill_history`·`test_project_skills`·`test_skill_import`·`test_skill_routing` 통과
  (72 passed, 1 skipped). 기존 감사 CLI 텍스트·JSON 계약은 추가 필드만 늘었습니다.
- 음성 대조: `domain/skill_audit.py`·`adapters/skill_history.py`·`application/skill_history.py`를 수정 전으로 되돌리면
  신규 검사가 실패합니다.

| 항목 | 결과 |
|---|---|
| 스킬 관련 5개 모듈 | 72 passed, 1 skipped |
| Windows 전체 `uv run pytest -q` (Python 3.12.14) | 919 passed, 305 skipped (185s) — 첫 실행에서 무관한 `test_github_tickets` 검사 1건이 실패했고 3회 단독 재실행과 전체 재실행에서 통과(시간 의존 flake) |
| `uv run ruff check .` | 통과 |

## 남은 범위

- "실제 행동"(모델이 스킬 지침을 따랐는가)은 텔레메트리로 잴 수 없다고 명시했을 뿐 측정 수단을 만들지 않았습니다. 그 증거는
  실제 모델 출력·사람 인수에서만 나옵니다(INV-RESEARCH-003).
- 상류 평가기(`skill_trigger_eval`)에 해당하는 목표/기대 라벨 기반 평가는 Zeus에 없으며, 만든다면 실제 선택 규칙과 같은
  후보·매칭·주입 경로로 평가해야 한다는 합의만 계약에 남깁니다.
- 이슈 종료는 Codex·Claude 독립 검토와 해당 개정 인수 기준 확인 뒤 [#30](https://github.com/trevi00/zeus/issues/30)
  범위의 종료 경로를 따르는 별도 단계이며, 이 기록은 구현·검증 증거이지 배포 승인이 아닙니다.
