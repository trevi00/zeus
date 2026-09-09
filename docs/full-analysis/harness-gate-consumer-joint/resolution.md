# 판정 소비·SDD 생성 계약 공동 검토 결과

고정 원본 `harness@a3f8b3be9a0a389329de6e16a6c7db81782041a3`의 5개 파일 52,280바이트를 Codex와 실제 Claude가 각각 읽고 결과를 대조했다. Codex는 직접 연결된 15개 파일의 전문 또는 명시 구간도 읽었다. Claude 세션은 `e5103076-1583-4486-9e50-2a8ced51b43a`이며 초기 검토와 후속 토론의 실제 프로세스 종료 코드 0, is_error=false를 원시 JSON·출력 해시·영수증으로 보존했다. 이는 리뷰 프로세스의 성공이며 **원본 테스트 실행은 0건**이다.

Codex 초기 기록은 Claude 초기 결과 열람 전에 작성했다. Codex는 앞선 Codex 엔진 보고서를 참조하고 원문을 재검토했고, Claude는 다른 보고서를 읽지 않고 독립 분석한 뒤 후속 턴에서 Codex 결과를 읽었다. 원시 보고서의 과장은 수정해서 덮지 않고 이 최종 문서에 정정한다. 전체 하네스 분석·실행 재현·Zeus 채택·운영 승인을 의미하지 않는다.

## 공동으로 확인한 문제와 흡수 조건

| 토픽 | 확인한 구현 연결 | Zeus에서 필요한 조건 |
| --- | --- | --- |
| 문장 귀속 | judge/residual은 statement를 쓰지만 `_external_verdict`는 stage+mode 최신값만 읽음 | 고정 문장 ID와 run/cycle·정의·산출물·환경에 판정을 결속하고 해당 판정만 소비 |
| 부분 검증 | gate_runner/residual은 PARTIAL 대기, tick은 None만 대기 | 공통 미종결 상태와 변경 이벤트에 의한 재개; 동일 입력의 반복 재지시 방지 |
| 철회·컴팩션 | reducers는 tombstone을 접지만 외부 판정/일부 tick 주사는 raw 이벤트; render 원본은 compaction head에서 접힐 수 있음 | 모든 판정 소비의 동일 view 및 소비자가 실제 사용하는 상태의 replay 등가 검증 |
| ERROR·완료 | 정상 writer는 ERROR 때 verdict 없이 finished(error); completed에는 과거 PASS가 남고 tick 완료 검사 순서가 앞섬 | 판정 불능의 유효성 철회와 모든 downstream/완료 소비자의 일치; 기존 FA-005와 연결 |
| 프로세스·관측 | metric/trigger는 종료 코드를 판정에 반영하지 않고 문자열/수치를 봄 | 원본 실행 receipt, 현재 대상·정의·실행 시각과 종료 상태를 함께 검증 |
| 검사 모집단 | loader에서 빈 gate/stages 최소 수 미강제, forbid가 expect를 앞서 반환 | 계획한 필수 검사 분모와 실제 수행 수, 조합 의미를 검증; 의도된 금지0건과 존재 의무 구분 |
| 한도·재시도 | stale 지시가 tick 캡보다 앞, gate_runner는 전체 feedback 수·tick은 REJECT 이후 수를 셈 | 시도·재개방의 수명과 예산을 공통 원장 계약으로 정의; blocker/재개·전체 작업 예산 일치 |
| 정의·환경 변화 | ratchet는 문장 삭제만, 정의 SHA는 payload 미포함, 전제 지문은 실행 후 계산 | 검사 의미·버전·전후 환경과 후보 봉인; 승인된 변경/면제를 별도 검증 |
| 스펙→테스트 | 템플릿은 한 줄 GWT, lint는 토큰 존재, testgen은 개행 구문; 생성은 xfail 골격 | 공통 구조화 시나리오, 안정 ID/원본 revision, 사람 oracle, 실환경 실행 receipt를 분리·연결 |

빈 목록, 수치/명령의 비정상 반환, 다문장 승인, PARTIAL, 원장 철회 등의 결과는 **정적 경로 추론**이다. 현재 운영 인스턴스에서 같은 입력을 관측했다는 주장이 아니다. 현행 모든 파이프라인의 빈 게이트/혼합 옵션 사용 여부도 아직 감사하지 않았다.

## 서로의 발견과 정정

Claude는 Codex와 독립적으로 다문장 판정 소비 누락, PARTIAL, ERROR와 완료 순서, 종료 코드 무시를 찾았다. 추가로 REJECT 후 retry 집계 비대칭과 render 판정의 컴팩션 손실을 구체화했다. Codex는 template→lint→testgen 문법 불일치, 빈 gate/stages, waiver와 실제 정의 해시 미소비를 제시했고 Claude가 원문 대조로 동의했다. Codex가 '앞선 stale 분기에서 결과가 달라질 수 있음'이라고 한 것은 안전해진다는 뜻이 아니다. Claude가 보완한 대로 오류 차단 이전 재게이트 지시로 바뀔 수 있다.

초기 Claude 보고에서 다음을 정정했다.

- HTTP 접속 실패가 반드시 ERROR여야 한다는 주장은 철회했다. SUT 가용성 요구이면 FAIL이 타당할 수 있다. 환경과 제품 오류 귀속은 별도 계약이다.
- Windows 경로를 WSL에서 사용하면 정확히 exit127이라는 주장은 철회했다. 실제 런타임 설정·셸·interop에 따른 이식성 위험이며 미실행이다.
- smoke의 임시 파일·원본 함수 단언을 이번 '실측'으로 표현한 부분을 철회했다. 이번에는 테스트 코드를 읽었고 실행하지 않았다. 직접 subprocess를 호출하는 구현도 명령이 echo/stub이면 무모킹 인수의 증거가 아니다.
- RUNNING/GATING 제외는 이미 관측된 상태의 중복 후보 배제다. 원자 claim이 아니며 동시 dispatch 차단을 증명하지 않는다.
- '항상 무한 루프'는 tick 내부 캡 이전에 재지시가 가능한 경로로 한정했다. reenforce의 25초 tick 호출 제한과 transcript byte cap 등 외곽 통제가 있다. byte cap은 토큰 실측이 아니며 실제 게이트 subprocess의 전체 수명 제한과도 다르다.
- strict=True만 바꾸면 skeleton 문제가 끝나지 않는다. NotImplementedError인 본문은 여전히 XFAIL이므로 실제 수행·인수 분모와 oracle 검증이 필요하다.
- 컴팩션이 이미 완료된 단계를 즉시 pending으로 만든다는 주장을 철회했다. 완료 snapshot은 남고 외부 원본이 사라진 효과는 조건부 재게이트 때 드러난다.

후속 Claude 문서에도 남은 과장은 root가 다음과 같이 제한한다.

1. **'2xx가 아닌 expect_status는 모두 불가능'은 넓다.** 확인한 문제는 urllib가 HTTPError를 내는 기대 오류 응답(대표 404)을 `_http_probe`가 상태 비교 이전 FAIL로 처리하는 경로다. 모든 3xx/비2xx의 동작을 여기서 일반화하지 않는다.
2. **모든 따옴표 입력이 SyntaxError인 것은 아니다.** escaping 없는 docstring 삽입에서 조기 종료 등 특정 문자열이 코드 구조를 바꾸는 위험으로만 기록한다. 후속 보고의 '슬라이스 마지막 따옴표가 닫는 따옴표와 인접한다'는 예시는 BLOCK에 개행이 있으므로 해당 설명 그대로 채택하지 않는다. 생성·수집 재현은 하지 않았다.
3. **cycle redo 뒤 외부 승인이 사라지는 것 자체는 의도된 철회다.** 컴팩션 손실의 회귀 판별은 redo 없는 동일 유효 판정을 유지해야 하는 재검증과 대조해야 한다. 컴팩션 모든 입력이 등가 검사를 통과한다는 뜻도 아니다.
4. **caps 기본 키가 있다는 것과 모든 caps 입력이 유효하다는 것은 다르다.** loader는 키 부재의 기본 dict를 보장하지만 mapping·유한 양수 등의 전체 입력 검증을 입증한 것은 아니다. 단순 KeyError 가설만 철회한다.
5. 초기 'repeat 비정수는 모두 ERROR'도 좁혀야 한다. 원본은 int() 변환을 사용하므로 float/boolean 입력의 엄격한 정수 타입 검증이 아니다. 첫 실패 중단과 1 미만 거부는 실제 있다.

## 구현 순서와 남은 증거

상류의 역할/판정 어휘와 관측 장치를 후보 자산으로 남기되 실행·승인 상태는 승계하지 않는다. Zeus의 기존 SDD는 구조화 스펙, 관측 제안, 검토 VIEW 준비 계층이며 gate_report는 모든 단계 blocked, acceptance_passed=false를 유지한다. **blocked만 계속 반환하는 것은 목표 달성이 아니다.** 전체 분석·채택 논의 후 실제 8단계 전이와 runner/사람 승인·배포·복구·CS 경로를 주 Codex가 구현해야 한다.

새 토픽 초안은 `ticket-drafts.json`의 FA-013(판정 소비)과 FA-014(스펙/인수 생성)에 분리했다. 증거 커밋 게시 후 로컬 PostgreSQL 티켓과 GitHub Issues로 동기화한다. 기존 FA-005와 이번 정적 추적은 이어지지만, 과거 자동 검토가 중단한 정상 gate-writer ERROR probe는 **그대로 미실행**이며 재시도/우회하지 않았다. 정적 토론을 그 실행 영수증으로 대체하지 않는다.

나머지 caller/config/tests 전체 추적, 실제 shell·플랫폼·원장 복구·동시성 실행, 라이선스/의존성, 기기·결제 인수, Astra→Sol→Terra 동등 자격 검증은 남는다. 일부 upstream subprocess나 생성물 PASS는 사용자 경험과 금융 흐름의 실제 검증을 대신하지 않는다.

게시 후 연결: 증거 커밋 `a10ba0e124e2dfbea24ae06562d768143ff7f981`을 고정해 [FA-013 / #14](https://github.com/trevi00/zeus/issues/14), [FA-014 / #15](https://github.com/trevi00/zeus/issues/15)를 로컬 PostgreSQL 원장에서 생성·동기화했다. 15개 전체 티켓의 원격 제목·본문·귀속 marker를 로컬 버전과 대조해 모두 일치함을 확인했다. 티켓 게시를 구현 검수 또는 채택 승인으로 계산하지 않는다.
