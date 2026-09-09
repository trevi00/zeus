# 전수 분석에서 분리한 이슈 초안

분석 당시 만든 초안의 근거 목록이다. 이후 사용자 요청으로 독립 `trevi00/zeus` 저장소를 만들고 통합 분석 1개와 아래 10개 토픽을 로컬 PostgreSQL 티켓 원장 및 GitHub Issues에 등록했다. [티켓 연결 목록](../tickets/README.md)을 참고한다. 등록은 검수·구현·배포 승인이 아니다. 상세 보고서가 갱신되면 아래 요약도 대조한다.

| ID | 토픽 | 확인 수준 | Zeus 처분 후보 |
|---|---|---|---|
| FA-001 | Windows Python 자식 출력 인코딩 계약 누락 | 현재 Windows 실제 프로세스 실패, UTF-8 대조군 PASS | Python 기계 채널에 명시 계약; parent decoder만으로 처리하지 않음 |
| FA-002 | 경험 수집 횟수와 독립 검증 횟수 혼동 | curator 코드·25개 observed lesson·원장 대조 | 원본 주장을 보존하되 검증/자격으로 승계 금지; 독립 occurrence 재계산 |
| FA-003 | lease epoch 재사용으로 이전 소유자 권한 부활 | 격리 edge probe 실제 재현 | 단조 fencing·owner·generation·CAS를 묶고 source 파일 lease 직접 이식 거절 |
| FA-004 | 중복 방지 검사와 기록 사이 동시 실행 경쟁 | 격리 barrier probe에서 같은 키 둘 다 True·2event | PG 트랜잭션과 실행 멱등키, 외부 side effect lost-ack 별도 설계 |
| FA-005 | PASS 이후 ERROR를 완료 helper가 무시 | 격리 probe에서 stage FAILED지만 completed 유지 | 최신 판정·revision·ERROR/PARTIAL/REJECT를 읽기 경로 전체에서 일관 처리 |
| FA-006 | malformed 알림이 전체 릴레이 중단 | Guardian pinned/observed JSON 배열 probe 재현 | schema 검사·문제 레코드 격리·처리/전달 receipt와 재시도 |
| FA-007 | 신규 compaction sidecar로 봉인 파손 판정 강등 | Guardian probe TAMPER→RESEAL_REQUIRED 재현 | compaction 전후 관계 증명, unknown을 healthy로 축약하지 않음 |
| FA-008 | 기술 스택 템플릿과 실제 라우터 불일치 | upstream 17tests PASS 후 별도 inline-comment probe 재현 | 엄격 파서/유효 스택 enum/상속·경로 수집 회귀; 문서만 복사하지 않음 |
| FA-009 | 테스트의 배선 문자열 검사와 실제 동작 혼동 | 여러 소스·원본 테스트의 구체적 조건 대조 | API/행동·부정/긍정 대조군으로 자산화; 문자열 존재를 E2E PASS로 승계 금지 |
| FA-010 | Git 추적 밖 경험·플러그인·미커밋 노트의 분석 누락 | 로컬 메타 9,420항목 및 추가 3,434자산 캡처 | tracked/observed/캐시/사적 세션/중첩 저장소를 별도 원장으로 완전성 관리 |

## 근거

- FA-001: `cross-review/windows-encoding-probe.json`, `cross-review/resolution.md`; 현 Zeus commands/verification source SHA와 실제 argv 포함. 배포 전체를 실행한 증거는 아님.
- FA-002: `harness-experience/trace.md`, `analysis.json`, `ledger-evidence.json`; `cross-review/claude-initial.md`와 후속 논의. occurrences 상승은 관측, 독립 성공 횟수는 미입증.
- FA-003~005: `harness-lib/review-probes.receipt.json`와 `review.md`; probe rc0는 결함 관측 성공이지 안전 판정 PASS가 아님. library 전체 호출/테스트 추적은 진행 중.
- FA-006~007: `guardian/review.md`, `execution-index.json`, 추가 review-probes receipt. 운영 webhook/Windows scheduler/실제 사용자 승인 경로는 별도 미검증.
- FA-008: `baldrix-common/test-tech-stack-receipt.json`, `template-inline-comment-probe.json`, `REVIEW.md`. 순수 라우팅 시험이며 실제 frontend/device 인수 테스트가 아님.
- FA-009: `design-canon/review.md`의 cohesion·context-coupling·마스터 설계서 대조, `harness-experience` 원장/후속 수정 근거. 가동 표시·file_exists·테스트 이름만으로 의미 검증을 대체하지 않음.
- FA-010: `coverage.json`, `path-ledger.json`, `local-surface-summary.json`, `local-assets-status.json`. 9,420는 파일뿐 아니라 중첩 저장소 디렉터리도 포함한 메타 항목 수다. 캡처·SHA 검증은 의미 검토가 아님.

## 구현으로 옮길 때의 공통 조건

각 이슈는 사용자 시나리오/계약, 현재 결함 재현, 수정 후 같은 재현의 기대 결과, 기존 정상 시나리오 회귀, Windows/Linux 차이, 모델·승인 경계 영향을 함께 가진다. 과거 승인이나 상류 PASS는 새 후보의 승인으로 재사용하지 않는다. 티켓 등록·공유는 완료했으며 전체 분석 및 해당 구현·검증은 계속 남아 있다.
