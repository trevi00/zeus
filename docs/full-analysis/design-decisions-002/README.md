# 설계 결정문 002 — 독립 정적 검토

`harness-design:design/decisions:002`의 19개 경로, 103,013바이트 전문을 읽었다. 원본은 `harness-design`의 pinned revision `20147dde412c1f2d84178d5c3665157ced1e7334`이며, SHA-256 19/19 및 Git blob 19/19가 manifest와 일치한다. 전체 경로를 먼저 `inventory.json`에 고정한 뒤 본문을 읽었다. 다른 의미 검토 보고서는 먼저 읽지 않았다. D-050 중복 확인에는 전문 독립 검토 뒤 `design-canon/files.json`의 해당 JSON 행만 읽었다.

19개 모두 `body_reviewed_call_test_trace_pending`이다. 본문 검토 완료는 전체 호출·설정·테스트 추적 완료가 아니다. 실제 읽은 supporting 구간은 `supporting.json`, 파일별 주장·정정·한계는 `review.md`, 전역 집계용 레코드는 `files.json`에 있다. 현재 원본 테스트·프로브 실행은 **0회**이며, 문서와 코드 주석에 적힌 PASS·실측·회귀 수는 역사적 출처 주장으로만 취급했다. 이 검토는 실행이나 원본·구현·운영 원장 수정, 설치, commit, push를 하지 않았다. 저장용 메타데이터 스크립트는 원본 Python을 import하지 않는다.

D-050은 기존 검토와 SHA `c592ee322c82fa3eb284385aadc2c79e4e0ddd967b00acab393be68d99c6285f`가 같다. 기존 disposition 역시 `body_reviewed_call_test_trace_pending`이다. 이번에는 관련 코드 일부를 더 읽었지만 더 강한 primary 완료 상태나 중복 승격을 부여하지 않았다.

## Zeus에 적용할 때의 경계

| 축 | 읽은 근거와 차이 | 제안 처분 — 아직 흡수 승인 아님 |
|---|---|---|
| PostgreSQL runtime 정본 | D-039·040·045와 `harness/config/profile.yaml`은 Git JSONL 정본, Kafka·PG·Redis는 미러/투영이다. | Git에는 정의·버전·리뷰 가능한 정책을 두고, 실행·후보·인계·승인·재시도 상태는 Zeus PostgreSQL의 식별자와 트랜잭션에 맞게 다시 설계한다. 파일 원장과 PG의 이중 쓰기 정본은 승계하지 않는다. |
| 사용자 8단계 SDD | D-045의 나선별 목업 승인, D-048의 도구 구축 3나선, D-049의 view 판정은 8단계 전체가 아니다. Zeus `domain/sdd.py:8–16`은 스펙→디자인→구현→자체 검증→알파→QA·증적→라이브→CS를 별도로 정의한다. | 목업 승인·시각 심판은 디자인 증거로 연결하되, 실제 기기·데이터 초기화·알파/점진 배포·롤백·CS 증거를 대신하지 않는다. |
| 사람 경험 인수 | D-032 PARTIAL, D-044의 문서만 보고 착수하는 사람 확인, D-045의 실제 사용자가 발견한 크레딧 시드 누락이 기계 판정의 한계를 보여 준다. | 관측에서 기대값을 자동 발명하지 않는다. Zeus의 `propose_scenarios`는 proposal_only이고 `gate_report`는 인수·출시 권한을 주지 않는다. 신선한 사용자 판단을 산출물·시나리오·환경 버전에 결속해야 한다. |
| 자가개선 | D-046은 사람 승인에서 자동 게이트 스택으로 개정됐지만 정책·guardian·원장 및 불가침 엔진을 자동 수정 대상으로 열지 않는다. 참조 판정·환경 봉인·승격 대기열까지 각각 별도 계약이다. | 원본 승인 문구를 Zeus의 권한으로 상속하지 않는다. 독립된 기준·패치/기저/테스트/환경 SHA·격리 자원·현재 승인 계약을 갖춘 뒤 구현한다. |
| Windows·Linux·WSL | D-039 환경 주입, D-043 스폰 스탬프·PowerShell 휴리스틱, D-045 Windows 프로세스 종료, D-046 cp949·사용자 site·환경 누출이 OS 의존 이음새다. | 경로와 인코딩만 바꾸어 이식 완료라고 하지 않는다. 설치·실행·종료·환경·DB·복구의 실제 플랫폼 증거가 따로 필요하다. 이 파티션은 그 실행을 하지 않았다. |
| 팀·모델 | D-5b는 단일 스포너의 계획 대행과 비용 절감을 제안한다. D-040 수거는 검증이 아니며, D-041 owns는 수정 권한이 아니다. | 팀·작업·run·attempt·산출물 신원을 결속하고 독립 재검토를 유지한다. 원본 fable/싼 티어 표현을 Astra/Sol/Terra의 자격 증거로 취급하지 않는다. |

## 우선 확인할 이음새

1. **판정 신원**: 외부 판정 소비는 stage+mode로 최신 이벤트를 찾는다. 문장·심판 인증·산출물 hash를 확인하는 코드는 읽은 `gate_runner.py:28–49`에 없다. 카드의 독립 평가 약속만으로 사람 인수를 보장할 수 없다.
2. **재개방과 이력의 서로 다른 수명**: D-050의 일부 후속 코드가 있지만 후보별 냉각 전체는 미확인이다. `cycle_cmd`는 circuit 거부 전에 plan·finished를 기록한다. `tick`의 ERROR 종료 이력은 redo와 별도로 남는다. reader 하나만 고쳐서 해결했다고 하면 안 된다.
3. **완료의 의미**: completion은 경로 존재, workup은 기계 절 재추출·digest·마커 잔존을 판정한다. 빈 의미 절·실제 작업 가능성·인수 성공은 다른 질문이다.
4. **격리의 의미**: counterfactual은 원본 대상을 백업 후 일시 수정하며, sandbox는 `os.environ`과 사용자 site를 상속한다. 주석의 never-destroy·결정론·fail-safe를 보편 보장으로 읽지 않는다. 특히 기존에 자동 보안 검사가 중단한 gate writer probe를 재실행하거나 우회하지 않았다.

`remaining.json`의 미완료는 남겨 둔다. 이 bounded 과제의 전문 검토와 정적 체크포인트 저장만 마쳤으며, 구현·채택·실행 검증은 완료하지 않았다.
