# Codex 표준 자산과 Zeus 무인운영 통합 설계

작성: 2026-09-16. 상태: **Codex가 정한 통합 경계와 구현 수용 조건**. 자산 전체의 의미 분석·흡수·운영 활성화 완료를 뜻하지 않는다.

## 목표와 종료 조건

D드라이브의 경험 자산을 현재 Codex에서 사용하면서, Zeus가 오케스트레이터 → 팀장 → 팀원의 장기 작업을 유일하게 관리하도록 한다. Codex는 조사·설계·선정·독립 검토, Claude는 확정 명세의 구현·검증, 사용자는 제품 방향·실사용 인수를 맡는다.

최종 종료 조건은 선정 자산의 출처·의미·라이선스·의존성 검토, 표준 패키지 생성, Windows/WSL 실제 로딩, Zeus 실제 작업과 증거 연결, 카나리아/되돌리기 검증이다. 이번 문서는 그 전체 틀을 고정한다. 미검토 자산의 복사나 이름 변환만으로 흡수 완료를 선언하지 않는다.

## 확인된 현재 상태

- 원본: `D:/old-projects/codex-harness`, remote `trevi00/dks-codex-harness`, HEAD `09c23939fa1454edf5205b2cdb8fa6881933c10d`. working tree가 HEAD와 다르고 미추적 자산도 많다. `inventory.json`은 Git 객체 식별자와 실제 파일 해시를 구분한다.
- 원본 AGENTS는 이미 Codex-native 구조를 선언한다. `.agents/skills`, `.codex/agents`, plugin hooks가 존재한다. 재변환의 핵심은 API/실행 계약과 운영 권한이다.
- 읽은 `harness-team` 스킬은 durable team을 GSD에 만들고 provider를 Codex/OpenAI로 제한한다. 이는 Claude 팀원을 사용하는 Zeus와 직접 충돌한다. 오래된 `C:/Users/user/...` 예제도 있다.
- 원본 전역 installer는 사용자 지침·스킬을 쓰며, 역할/config/rules는 별도 검토 묶음을 만든다. 이번 조사에서 installer는 실행하지 않았다.
- 기존 plugin의 9종 이벤트에 Stop과 SubagentStop이 포함되어 있다. 각 handler의 내부 효과는 아직 모두 검토하지 않았으므로 자동 계속 동작을 단정하거나 활성화하지 않는다.
- 방금 설치한 개인 `whole-task` 지침과 두 안내 훅은 임시로 유지한다. 최종 패키지의 같은 정책과 이중 등록하지 않는다.

원본 파일 목록은 의미 분석이 아니다. 부분적으로 읽은 파일도 inventory에서는 보수적으로 unreviewed로 둔다. 전체 분석 완료 수치를 만들지 않는다.

## 하나의 운영 구조

```text
사람의 요청 / 제품 인수
          ↓
Codex 표준 인터페이스: AGENTS · skills · native hooks · 선택적 MCP
          ↓ (Zeus 계약을 검증하는 어댑터)
Zeus 오케스트레이터 → 팀장(Codex) → 팀원(Claude 등)
          ↕ six-W 메시지 / Redis Streams
PostgreSQL: 작업·attempt·lease·판정·승격의 권위 있는 상태
Git: 명세·정책·자산 정의 / artifact 저장소: 실행 증거
검증 전 후보 컨텍스트 → 독립 검증·채택 → 지식 DB의 온톨로지·토폴로지
```

Redis는 전달 경로다. PostgreSQL 커밋 뒤 ACK, 중복 전달·충돌·stale writer 처리는 Zeus 계약을 따른다. 큐 수신이나 모델의 완료 문장을 작업 성공으로 승격하지 않는다. 검증 전 후보를 DB에 보관할 수는 있지만 accepted knowledge와 같은 권한으로 사용하지 않는다. U003 이후 필요한 지식 승격 연결이 구현되지 않았다면 명시적으로 미지원 상태로 둔다.

## 자산별 선정 기준

| 원본 자산 | 목표 | 보존할 경험 / 바꿀 책임 |
|---|---|---|
| AGENTS·계획/검토 템플릿 | 짧은 공통 지침 + 프로젝트 명세 | 큰그림·근거·수용 표·종료 기준을 공통 정책으로. legacy 실행 지시는 제거 |
| `.agents/skills`, commands, skills | Codex SKILL.md 및 참조 자료, 검토 후 plugin 배포 | 명령 이름 교체가 아니라 입력·출력·실패·의존성까지 확인. 중복 원본과 생성물을 묶음 |
| `.codex/agents`, agents | 검토한 역할 정의 | Codex 팀장/Claude 팀원 역할 유지. 짧은 서브에이전트와 durable Zeus 세션을 구별 |
| native hooks / bridge | 현재 Codex event/output 계약 | 안내·관측·국소 검증. durable 작업 생성·재시도·승격은 Zeus use case로 요청 |
| GSD planning/SDD | Zeus 명세·시나리오·검증 artifact | 프론트 8단계 반복과 사람 인수 포함. 파일은 명세/증거이며 별도 작업 원장 아님 |
| GSD team/mailbox/ralph/autonomous | Zeus 워크플로 어댑터 | 파일 기반 팀·메일박스·무한 반복 제어를 두 번째 운영 계통으로 켜지 않음 |
| session learn/memory/ontology | 후보 지식과 provenance | 자기보고/요약은 후보. 독립 검증과 채택 기록이 있는 것만 승인된 그래프에 반영 |
| 테스트·장애 기록·회귀 | 출처가 결속된 검증 자산 | 테스트의 실행 여부·실제 환경·주입 경계를 표시. 과거 green을 현재 운영 증거로 재사용하지 않음 |
| Codex Rust 패치 | 호환성 자료, 기본 배포 제외 | 현재 stock Codex에서 여전히 필요한지 별도 확인. 바이너리/PATH 교체 없이 기본 기능으로 구성 |
| 글로벌 installer | 소유 파일만 관리하는 배포 도구 | 사용자명/드라이브 독립, dry-run diff, 충돌 보고, 원복. 전체 config/rules 덮어쓰기 금지 |

표는 설계상 경로이며 각 파일의 채택 승인이 아니다. 원본 plugin은 Proprietary로 표기되어 있어 vendor/개별 파일의 권리와 출처를 확인한 뒤 공개 저장소에 배포한다.

## Codex 표준 적용

공식 문서에서 확인한 표면은 전역 `~/.codex/AGENTS.md`, 프로젝트 `.agents/skills`, 사용자 `~/.agents/skills`, 설정 계층의 hooks.json이다. 배포는 검토된 plugin 한 벌을 기준으로 하고, 같은 이름의 스킬을 여러 경로에 중복 설치하지 않는다. 기존 `~/.codex/skills` 호환 경로가 존재한다고 해서 새 표준의 유일한 경로로 가정하지 않는다.

훅은 여러 설정 계층에서 병합되어 실행되므로, 새 plugin을 설치하면 기존 개인 훅을 자동으로 대체한다고 가정하지 않는다. 정책 ID와 설치 소유권 manifest로 겹침을 찾아, 해당 두 항목만 전환한다. 다른 plugin/사용자 훅은 보존한다. 동일 이벤트 내 순서가 필요하면 검토한 하나의 dispatcher 안에서 정하며, 병렬 실행되는 별도 훅의 순서에 기대지 않는다.

일반 개인 세션은 조사·설계·검토 도구를 사용할 수 있다. Zeus 관리 실행은 검증된 assignment/lease/context로 식별한다. cwd나 환경변수 하나만으로 운영 권한을 부여하지 않는다. 관리 실행에서 Zeus 연결이 끊겨도 GSD 로컬 팀을 대신 시작하지 않는다. 실패/차단을 기록하고 기존 복구 흐름을 따른다.

## 작업 및 컨텍스트 전이

```text
조사 → 단일 작업 틀 확정 → 구현 → 전체 수용 표 검증 → 수용/병합 → 카나리아 → 활성화
                   ↑            │
                   └─ 가정이 깨진 경우 틀 전체 갱신 ─┘
```

같은 실패 계열을 패치로 반복하거나 범위를 벗어나는 발견이 나오면 Codex가 기존 문서의 상태·소유권·수용 표를 함께 수정한다. 단순 실패 재시도와 설계 변경은 구분한다. accepted evidence는 유지하고, 실제로 영향을 받는 행만 다시 검증한다. 완료 조건 충족 후 근거 없는 추가 검토를 만들지 않는다.

새 세션은 생성되었다는 이유로 운영 세션이 되지 않는다. 후보 버전·역할·인수 조건·검증 결과가 결속되어야 하며, 활성화 시 새 generation/lease를 부여하고 이전 세션의 쓰기를 차단한다. 카나리아 실패 시 이전 검증 버전으로 복구한다. Git 배포, 파일 설치, DB 전환이 하나의 원자 트랜잭션이라고 주장하지 않고 준비→검증→전환→실패 보상 단계를 기록한다.

## 로그 계약

- 일반 로그: 요청·세션·작업 상관관계, 상태 전이, 사용자에게 필요한 요약.
- 개발 로그: 선택한 설계/수용 기준, 수정 revision, 테스트·실패 재현, 채택 근거.
- 운영 로그: 큐 전달/중복, lease/generation, 예약·정산, 장애·복구·카나리아·롤백.

원문 프롬프트·자격증명을 무조건 로그로 수집하지 않는다. 필드 허용 목록/redaction/증거 참조를 사용한다. 감사가 필요한 전이는 기존 PG 트랜잭션 계약에 연결하고, 진단은 기존 durable spool/notification 경로를 따른다. 관측 JSON과 six-W 명령은 서로 다른 계약이며, 관측 수신이 권한 있는 명령 실행을 뜻하지 않는다. 재부팅/절전은 사용자가 실제 수행한 증거가 있어야 별도 수용한다.

## 한 번에 검토할 수용 표

| ID | 필수 조건 | 결정할 증거 |
|---|---|---|
| A01 | 원본 누락 없이 추적, dirty/untracked 구분 | Git tree/OID와 working 해시, 생성물 원본 연결, 파일별 의미 검토 상태 |
| A02 | 선정 자산이 현재 Codex에서 로드 | 실제 skills/hooks 발견, 정확한 신뢰 hash, 실행 이벤트. 설정 파일 존재만으로 통과하지 않음 |
| A03 | 기존 전역 구성 보존·중복 없음 | 설치 전후 diff/해시, 재설치 멱등성, 임시 정책 이중 주입 없음, 소유 범위 원복 |
| A04 | Windows/WSL 경로·인코딩·종료 동일 | 공백/비ASCII 경로, 양쪽 실제 subprocess·훅 실행, 실패·종료 증거 |
| A05 | Zeus 단일 작업 권위 | 실제 PG+Redis로 중복/충돌/ACK 순서, stale lease 거절, 연결 단절 시 로컬 fallback 없음 |
| A06 | Codex→Claude→검토 흐름 | 기존 provider adapter로 실제 assignment/실행/증거/검토 결속. fixture는 실제 모델 증거를 대체 못함 |
| A07 | 검증 전 지식은 승인 권한 없음 | 후보·검토·채택 분리, 거절/오래된 spec/다른 task 증거로 승격 불가 |
| A08 | 로그와 장애 처리 유계 | 감사 실패 시 실행 계약, 진단 손실 통지, 비밀 미노출, 재시작 후 누락/중복 처리 |
| A09 | 카나리아·세션 교체·롤백 | exact revision, 실패 시 승격 없음, 이전 writer 차단, 롤백 후 상태 일치 |
| A10 | 반복을 줄이는 작업 방식 | 한 명세·수용 표·일괄 검토 기록, 재설계 근거, 완료 후 추가 작업의 명시적 이유 |

A06/A09를 실측하지 않은 패키지는 배포 후보일 뿐 무인운영 완료가 아니다. 전체 원본 분석과 첫 선정 묶음의 완료도 별도로 표시한다. 신규 제품·기기·금전 시나리오의 사람 인수는 이 마이그레이션으로 대체되지 않는다.

## 구현 인계

Claude는 진행 중인 PR #101의 수정과 혼합하지 않는다. 이 명세를 바탕으로 첫 통합 PR에서는 **소스 추적/선정 manifest, Codex 패키지·설치 계획, Zeus 어댑터 경계와 검증**을 함께 제시한다. Codex가 의미 검토한 자산만 enabled로 내보내고 나머지는 pending으로 유지한다. 기존 team/autonomous/Stop 제어는 Zeus 연동이 확인될 때까지 실행 경로에 포함하지 않는다. 하나의 수용 표에 모든 변경과 증거를 매핑한다.

Codex의 남은 분석은 inventory의 미검토 파일·subsystem을 기존 reference adoption 계약에 따라 읽고 선정하는 것이다. Claude에게 이 선정 판단을 떠넘기지 않는다. 큰 범위 전체를 분석했다고 표시하지 않은 상태에서 생성된 구조를 곧바로 운영에 켜지 않는다.

## 근거

- 원본: AGENTS.md, docs/install/global-install.md, scripts/sync_global_harness.py(부분), plugin manifest/hooks.json, harness-team/autopilot SKILL.md, harness-planner.toml. 일부 역할·스킬 지시와 설치 구조를 확인한 범위다.
- Zeus: docs/research-standard.md, docs/contracts.md의 INV-MESSAGE-001 / CONTEXT / SESSION / RELEASE / RESEARCH, application/workflow.py의 submit 권한·작업 결속. 구현 전체의 재검증을 뜻하지 않는다.
- 공식 Codex 지침: https://learn.chatgpt.com/docs/agent-configuration/agents-md
- 공식 스킬 표면: https://learn.chatgpt.com/docs/build-skills
- 공식 훅 계약: https://learn.chatgpt.com/docs/hooks
- 열람 2026-09-16. 원본의 0.144/0.145 호환성 기록은 현재 0.154.0의 검증 증거가 아니다.
