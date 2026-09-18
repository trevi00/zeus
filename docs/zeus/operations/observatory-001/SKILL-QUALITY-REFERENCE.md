# 외부 스킬 품질 기준 — 참고 조사와 Zeus 적용 판단

2026-09-18 Codex. 사용자가 제공한 두 자료를 읽고 현재 Zeus의 SSOT와 대조했다.
이번 작업은 참고 조사와 설계 기록이다. 플러그인 설치·평가기 실행·품질 등급 부여·PG 승격을
실행했다고 주장하지 않는다. 보고서 도해의 실제 구현과는 별도 증거 단계다.

## 확인한 자료

- [Toss Tech, 2026-06-08](https://toss.tech/article/skill-quality-rubric): 6영역 30항목,
  규칙17/모델13으로 책임을 나누고, 등급보다 차단 여부를 단순화하며 한 번에 결함을 전달한다.
- [rubric-evaluator](https://github.com/halfmoon-mind/rubric-evaluator/tree/ff54b11fddf9249e6745f29b39bee41b6688cf1e):
  6영역 31항목. README, SKILL.md, model-rubric.md, check_rules.py를 확인했다.
  규칙 검사/의미 평가/결정적 등급 계산이 구분된다. 모델 참조에는 description만 보고 양성3·음성2
  프롬프트를 판단하는 항목이 추가되어 있다. 이는 실제 host 호출 시험과 다르다.
  MINOR는 등급을 바꾸지 않는다. 규칙 검사만의 등급을 최종 평가로 오해하면 안 된다.
- 스크립트의 frontmatter parser는 자체 구현한 제한된 YAML 형태이며 허용 키는 관측 기반이다.
  모든 Codex/Claude 버전의 공식 로더와 동등하다는 근거는 없다. 이 규칙을 Zeus 전역 강제 규칙으로
  그대로 가져오기보다 대상 호스트/버전과 실제 로더 결과에 맞춰야 한다.

## 기존 SSOT와 연결

- `docs/zeus/implementation/skill-measurement-targets-001/README.md`
- `src/codex_harness/application/skill_import.py`
- `src/codex_harness/domain/skill_audit.py`
- `adapters/skill_history.finalize_delivery()` 및 INV-SKILL-HISTORY-001

기존 기록은 선택된 스킬과 최종 봉인 컨텍스트에 포함된 스킬을 구분하며, 제공자 호출 전의
본문 포함이 실제 모델 행동을 증명하지 않는다고 이미 명시한다. 새 루브릭을 이 감사와
동일한 점수로 섞거나 별도 중복 SSOT를 만들 이유가 없다.

## 채택할 틀

| 단계 | 증거 | 주장할 수 없는 것 |
|---|---|---|
| 기존 자산/중복 확인 | source revision, skill id/hash, 기존 기능과 차이 | 설치 필요성 자동 확정 |
| 규칙 검사 | host profile, checker revision, 항목별 pass/fail/not-run | 의미 품질/실제 호출 |
| 의미 검토 | 기준 버전, reviewer, 근거와 수정안, 하나의 종합 검토 | 실행되지 않은 트리거 성공 |
| 실제 선택·컨텍스트 | 기존 routing manifest와 compiled packet hash | 모델 준수/사용자 가치 |
| 실행·인수 | 대상 시나리오, 모델·환경, 출력·비용·시간·실패, 인수 판단 | 다른 제품·환경의 일반적 성공 |
| 반영 | 검증된 버전과 승인 근거를 기존 저장 경로에 결속 | 미검증 캐시의 지식 승격 |

형식 위반은 대상 로더에서 실제로 거절되거나 계약을 깨뜨린 경우, 보안/권한/데이터 손실은
도달 가능한 경로와 근거가 있는 경우 차단한다. 단순 문구·범용성·스타일 개선은 별도 권고다.
S등급을 목표로 반복 수정을 강제하지 않는다. 미실행/불가/판단 보류는 통과와 구분한다.
평가 보고서는 검사 버전·skill hash·대상 host·전체 항목 결과·근거·한계·다음 조치를 보존한다.

현재 ELI5 활용은 스킬 설치가 아니라 보고서 설명 방식의 참고다. 그러므로 ELI5가 모델에
호출되었다거나 루브릭을 통과했다고 기록하지 않는다. 고정 보고서의 쉬운 설명·도해가 수치와
한계를 보존하는지 실제 화면/JSON/PDF에서 확인한다.

후속 런타임 통합은 실제 스킬 흡수 작업의 명세에서 이 틀을 기존 import/audit 경로에 결속해
구현·검증해야 한다. 이번 참고 요청을 무관한 평가 플랫폼 구축으로 확대하지 않는다.
