# 배포 구성과 테스트 009–011 교차 검토

신규 primary는 83개다. Root가 배포 구성 4개/3912바이트를 전문 읽고 실제 Claude 독립 검토와 토론을 수행했다. 세 Codex 검토자는 테스트 79개를 전문 정적 검토했다. Root는 세 보고서와 supporting 설명을 모두 읽었으며 79개 원문을 독립적으로 다시 읽거나 실행했다고 주장하지 않는다.

## 주요 결정

[배포 구성 공동 결론](baldrix-distribution-config-001/resolution.md)은 CI 변경 필터의 대상 누락과 확정 snapshot 검증에 관용적인 live reader를 쓰는 문제를 구분한다. 원본 CLI 7회에서 baseline과 5개 누락/손상 입력은 rc0, 명시 버전 불일치는 rc1이었다. 정확한 입력·argv·환경·출력·실패 및 source 불변·container cleanup 영수증을 보존했다. full matcher, 원본 회귀 suite, 원격 workflow, plugin 설치는 실행하지 않았다.

실제 Claude의 초기 보고서는 현재 브랜치와 과거 설정을 반대로 읽고, graduation JSON 객체 한 줄을 JSONL 분모에 섞었다. Root의 원문/실측 대조 후 후속 답변에서 정정했다. 상태 JSON을 프로그램으로 처리할 수 없다는 주장, 스택의 특정 분기가 영구 미실행이라는 주장, 설치를 관측한 것처럼 읽히는 표현도 철회했다. 이 정정은 검토자를 실제 실행 권위로 승격하지 않으며 원본 영수증이 관측 근거다.

- [tests009](baldrix-tests-009/review.md): 32개 primary·supporting 36개. 출력 존재 기반 pipeline DONE, 재실행 없는 Probe 성공, Ollama 요청 생략의 성공 집계, budget 전송 실패 후 발신됨 표시, quota 읽기의 mkdir와 분리된 increment를 추적했다. 일부 수동 실패를 상위 runner가 포착하는 방어도 구분했다. 원본 실행 0이다.
- [tests010](baldrix-tests-010/review.md): 23개 primary·supporting 51개. resident의 계약 판정 방어와 queue 소비 조건의 차이, 원본 cron 파일과 실패 로그를 변경할 수 있는 fixture, router 평가와 실제 주입의 차이, reflection helper의 no-write 설명과 실제 L1 append를 추적했다. 기존 UTF-8·unknown·priority 방어를 과거 결함과 구분했다. 원본 실행 0이다.
- [tests011](baldrix-tests-011/review.md): 24개 primary·supporting 35개. filename stem 그래프 중복, precision이라는 이름과 실제 음성 시나리오 분모, 어휘/길이 보존과 의미 보존 차이, home 고정 staging guard, quota 예약 비원자성, manifest 덮어쓰기와 사라진 facet 잔존, `or True` 무검사를 기록했다. ID 집합 일치와 실제 시나리오 실행은 별개다. 원본 실행 0이다.

위 정적 후보를 현재 Zeus의 재현된 결함으로 단정하지 않는다. 파서·구조·점수·파일 존재·advisory는 SDD의 보조 관측이다. 사람의 핵심 시나리오, 실제 오라클, spec/source/env/attempt identity와 PG 결정에 결속하기 전에는 완료·승인·모델 자격으로 사용하지 않는다. 삼성 실기기와 Device Farm은 유예된 후속 범위다.

## 검증 경계와 수정

[정체성 검사](distribution-tests-checkpoint-verification.json)는 primary 83개, supporting 131개와 산출물 63개, 실제 Claude 영수증 2개와 원본 실행 영수증 1개를 대조했다. Supporting은 새 primary 분모에 더하지 않는다. Source 1648개 바이트 불변은 관측 범위이며 그 전체의 의미 독해나 인수를 뜻하지 않는다.

첫 root 검증 실행은 UTF-8 stdout을 Windows 기본 cp949로 읽다가 UnicodeDecodeError로 중단했다(도구 chunk `39e0b0`). [당시 코드](distribution-tests-verifier-initial.executed.txt)를 보존하고 새 검증기에 UTF-8을 명시했다. 같은 실제 영수증으로 다시 실행해 통과했다(`2438f3`). 원본 실행을 재시도하거나 실패 영수증을 덮어쓰지 않았다. [로컬 검증 기록](distribution-tests-local-validation.json)에 회귀 테스트와 이 수정의 범위를 연결한다.

전체 분석·전이 closure·라이선스·실제 인수·흡수·운영 전환은 미완료다. 개선 이슈는 해결 구현과 해당 개정의 인수 검증이 끝나기 전까지 열어 둔다. 기존 운영 하네스와 컨테이너는 변경하지 않았다.
