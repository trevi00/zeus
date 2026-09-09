# Harness CLI 004 독립 정적 검토

고정 원본 `a3f8b3be9a0a389329de6e16a6c7db81782041a3`의 `harness:scripts/cli:004`, 6개 파일 114,624 bytes를 전문 검토했다. 범위 SHA-256은 `692447cf6d9292349ec60a99ce69a42f452db063a58e5b16d51c8afb7fe1696b`이다. 해시·전문 범위는 `files.json`, 실제 지원 파일의 읽은 구간과 해시는 `supporting-evidence.json`에 기록했다. 다른 리뷰 문서의 결론을 근거로 삼지 않고 원문과 직접 소비자를 확인했다.

원본 실행·테스트·프로브·설치·모델 호출은 모두 0회다. 원문의 지시와 PASS 표시는 분석 데이터다. 아래 조건부 결과는 정적 코드 경로에서 도출했으며 현재 실행 환경에서 재현했다는 뜻이 아니다. 전체 분석 완료·원본과 Zeus 구현의 등가·채택·인수 승인도 주장하지 않는다. 실제 Claude의 독립 교차 검토와 최종 판단은 root가 관리한다.

| 전문 파일 | 행수 | 주요 계약과 결과 |
|---|---:|---|
| `scripts/cli/spiral_cmd.py` | 679 | 개선 후보 순위, 제안·승인·해결 이벤트, 신선도와 배정 표시. S04 |
| `scripts/cli/status_cmd.py` | 163 | 파이프라인 원장 투영과 전역 운영 상태 표시. S06 |
| `scripts/cli/step_cmd.py` | 511 | 단계·분해 계획·위임 이벤트·역할 프롬프트·게이트 호출. S03 |
| `scripts/cli/suite_cmd.py` | 624 | 스크립트 실행, 텍스트 판정, 재확인·기준선·요약. S05 |
| `scripts/cli/testgen_cmd.py` | 49 | GWT 스켈레톤 파일 발급. S01 |
| `scripts/cli/workup_cmd.py` | 54 | 저장소 기계 구간 발급과 문서 정합 검사. S02 |

## S01 — testgen은 스켈레톤 발급이며 인수 테스트 실행이 아니다

CLI는 유스케이스 파일 존재와 GWT 추출 0건을 검사한다. 직접 호출하는 `engine/testgen.py:1–70`은 AC 식별자와 한 줄 Given/When/Then을 정규식으로 추출하고, 단락의 첫 AC 또는 UNANCHORED를 사용한다. 중복 함수명 접미사를 붙이고 각 문장을 120자로 자른다. 여러 줄·복수 AC·긴 사용자 시나리오의 의미 보존은 검증하지 않는다.

생성물은 `pytest.mark.xfail(strict=False)`와 `NotImplementedError`를 가진 함수다. 실제 행동·실서비스 연결·관찰값·assert·사람의 기대 결과는 없다. 구현 후 XPASS도 strict=False 때문에 실패로 강제되지 않는다. CLI가 출력하는 테스트 수 역시 AST나 실행 수가 아닌 문자열 개수다. 이 출력의 성공은 발급 성공이며 사용자 경험 검증 성공으로 소비하면 안 된다.

`testgen_cmd.py:37`은 기존 파일을 무조건 덮어쓴다. 구현한 테스트 보존, 입력과 출력의 동일 경로 방지, 원자적 교체 계약은 없다. 생성기의 소스명과 GWT가 Python 문자열/문서 문자열에 그대로 들어가므로 따옴표·백슬래시 등 문법 경계의 안전한 직렬화도 후속 검증 대상이다. 위험 입력을 생성하거나 실행하지 않았다.

S05의 suite는 파일을 `sys.executable`로 실행한다. 이 생성물에는 함수를 실행하는 진입점이 없어 같은 경로에 놓아 suite로 실행한다고 pytest 함수가 실행되지는 않는다. 현재 suite의 무단언 방어가 이 경우 vacuous를 막는 점은 보존해야 한다. 생성기를 실행 가능한 E2E 파이프라인이라고 흡수할 근거는 없다. 이 범위에서 직접 testgen 테스트 본문은 확인하지 않았으며, 다른 곳의 테스트 부재까지 주장하지 않는다.

## S02 — workup의 정합 PASS와 의미 검토는 다른 계약이다

`workup_cmd.py`는 scaffold 생성 파일을 덮어쓰고 check의 오류 목록이 비면 PASS/0을 반환한다. `engine/workup.py:15–225`는 기계 구간의 키·본문으로 만든 짧은 SHA-256, 최신 저장소에서 다시 만든 구간, 남아 있는 의미 작성 마커를 비교한다. 원문도 의미 판단을 사람의 몫으로 분리한다. 이 제한 자체를 결함이라고 보지는 않는다.

다만 의미 마커를 지우거나 의미 구간을 없애도 비어 있지 않은 근거·올바른 설명·사람 승인 여부를 검사하지 않는다. `test_workup_smoke.py:29–70`도 마커를 같은 문구로 치환해 PASS를 확인한다. 이는 구조 계약의 검사다. 기계 블록 내 분석기의 ERROR 문자열 역시 최신 결과와 같으면 문서 정합성으로 통과할 수 있다. ERROR를 의미 분석 성공으로 바꾸지는 않는다.

분석은 언어 프로파일과 우세 스택에 영향을 받고 HTTP 나열·트리 깊이·표시 개수에 제한이 있다. 제외 디렉터리, 중복 키 처리, 표시 상한과 실제 디렉터리 탐색 비용도 전체 분석 범위와 같지 않다. 저장소를 전부 분석했다는 증거로 이 문서만 쓰면 분모가 사라진다. Zeus에는 포함/제외/절단/오류·미분석 항목을 별도로 보존하고, 사람의 의미 검토를 문서 정합 검사와 다른 상태로 기록하는 후보 설계를 제안한다. 현재 기술적 정답이나 채택 결정으로 확정하지 않는다.

## S03 — step의 기록·안내 표면과 실제 실행·자격 경계

활성 run 및 단계 이름은 확인하지만, dispatch/delegate CLI 분기 자체는 `select_ready`의 의존성·단계 진행 가능 여부를 강제하지 않는다. dispatch와 시작 이벤트도 분리되어 있어 반복 호출과 부분 기록에 대한 검증이 필요하다. 반면 정상 tick 경로는 `select_ready.py:23–99`, `tick.py:112–133,327–350`의 선택 절차를 사용한다. 정상 오케스트레이션에도 아무 방어가 없다는 주장은 아니다.

`shards`는 분해 계획, parallel 허용, 이전 wave의 수거 여부를 보고 준비된 명령을 안내한다. delegate는 역할과 계획 내 shard 소속을 확인하지만 같은 wave 준비 검사를 강제하지 않는다. 계획이 없으면 자유 shard가 가능하다. 명령 문자열은 shell별 안전한 인자 직렬화 계약 없이 출력된다. Windows 경로 공백, PowerShell/Bash 인용, WSL 경로 변환을 실행 검증하지 않았다.

`decomposition.py:45–188`의 collect는 dispatch를 단계로 좁히는 반면 결과를 shard 이름으로 결합하며 단계·cycle·dispatch attempt 식별자의 완전한 결합이 없다. 과거/다른 단계의 같은 shard 수거가 현재 완료 판단에 영향을 줄 수 있는 정적 경로다. `stop/subagent_harvest.py:58–154`와 registry의 SubagentStop 등록도 읽었다. 수거는 완료 신호이며 검증은 게이트 몫이라는 원문 주석은 명확하다. 수거 이벤트를 검증 성공으로 격상하면 안 된다. 실제 동시 실행이나 재시도는 하지 않았다.

delegate는 이벤트와 프롬프트를 남기며 실제 에이전트를 spawn하지 않는다. model·effort·budget 인자가 모델 자격이나 예산 집행의 증거는 아니다. 역할 카드 본문은 frontmatter 제거 후 800자까지 출력한다. 누락/오류는 위임을 막지 않는다. 현재 domain-lead는 전용 계약 테스트에서 길이와 전달 문구를 확인하므로 그 카드가 실제로 잘렸다고 주장하지 않는다. 다른 카드까지 같은 보증을 확장할 수는 없다.

judge 입력에는 비어 있지 않은 evidence와 statement 검사가 있으나 이는 사람 신원·artifact digest·실제 모델 판단의 인증이 아니다. 읽은 `gate_runner.py:100–123`의 소비는 stage+mode를 기준으로 하여 statement 식별자를 끝까지 결합하는 보증이 없다. gate CLI는 FAIL/PENDING_HUMAN도 처리 성공 0으로 반환한다. CLI 종료 0을 단계 승인으로 쓰는 호출자는 별도 verdict 해석이 필요하다.

## S04 — spiral의 승인 표시는 실제 arming 판정보다 약하다

후보는 completion gap·proposal·incident·capture에서 모으고 가중치로 순위를 낸다. 누락 후보·보류·순위 밖 승인 항목을 드러내는 장점이 있다. 다만 없는 원장은 빈 목록이 되고 손상 JSONL 행은 건너뛴다. ‘수집 0’이 ‘실제 사건 0’을 보증하지 않는다. proposal JSON의 shape, 중복 후보, 동시 읽기 일관성은 추가 검증 대상이다.

제안 시 후보·mock 경로·신선도를 확인하지만 mock은 존재 검사이며 승인 대상 내용의 hash/revision이 아니다. 승인의 HMAC도 읽은 `approval_proof.py:64–136`에서 후보 식별자에 결합한다. 구체적 제안 이벤트·내용 버전·mock·만료를 모두 묶는 증거는 아니다. 승인/거절/해결에는 driver-spawned 방어가 있고, 키가 없으면 unsigned 경고가 있다. 실제 키 파일이나 권한은 읽지 않았다.

`spiral_cmd.py:667`의 gate 표시는 latest verdict가 approved인지로 ‘배정 가능’을 결정한다. 직접 소비자인 `arming.py:348–442,577–730`은 비자율 귀속, 승인 증명, 규칙 매칭 및 신선도를 추가 검사한다. `l2_driver.py:1216–1252`와 현재 arming 규칙도 추적했다. 따라서 gate 표시의 충분조건이 실제 arming의 충분조건과 다르다. **현재 arming에 신선도 방어가 없다는 과거 주장을 되풀이하지 않는다.**

신선도는 고정 sibling 저장소 배치, git commit 시간, 로컬 시간 및 캐시에 의존한다. 미커밋 작업의 최신성·동일 후보 내용 변경·장시간 프로세스 캐시·proposal 소실에 대해 버전 결합을 확인해야 한다. `config/policy/evidence-freshness.json` 파일은 이 pinned 트리에 없고 코드의 기본 임계값을 사용한다. resolve는 이유·증거 문자열을 요구하지만 이를 인수 artifact로 검증하지 않는다. 이 원장은 GitHub Issues 연동이나 Zeus 티켓 승인 원장의 구현 증거가 아니다.

## S05 — suite의 분모 방어와 SKIP 소비 불일치

발견 0건, 무단언(vacuous), 단언 수 감소, 실패 파일과 기준선의 drift를 검사하는 방어가 있다. `--allow-vacuous`를 줘도 발견 자체가 0건인 경우는 실패한다. 재확인에서 원래 red가 사라져도 red_unknown으로 남겨 0으로 세탁하지 않는다. 최신 실행 요약은 원자적으로 쓴다. 이 방어를 없는 것처럼 취급해서는 안 된다.

그러나 `test_outcome.py:45–85,90–111,179–253,303–345`의 GREEN에는 pass와 skip이 있다. `suite_cmd.py:358–376`의 no_verdict는 GREEN과 CODE_RED를 제외한다. **모든 발견 파일이 SKIP이고 별도 drift 오류가 없는 경우** suite는 no_verdict=0, vacuous=0, 종료 0이 될 수 있다. `autoheart_cmd.py:129–151`의 `_g_suite`는 종료 코드·vacuous·no_verdict를 보므로 이 개별 게이트를 통과할 수 있다. unverified_axes가 요약에 있어도 이 소비자는 차단 조건으로 사용하지 않는다. 원본 실행 없는 정적 귀결이며 전체 autoheart/배포 게이트를 모두 통과한다는 뜻은 아니다.

기준선이 이전의 양수 단언 수를 알고 있으면 pass→skip 감소를 막는다. 기준선이 없거나 이전 값도 0이면 그 방어의 분모가 없다. `autoheart_cmd.py:678–725`의 evidence 수 방어와 pipeline의 known_good 대비 tests 삭제 검사(`harness-selfimprove.yaml:238–243`)도 별도로 존재한다. 이를 무시해 전체 승격 우회를 확정할 수 없다.

suite는 pytest 수집기가 아니라 각 Python 파일을 직접 실행하고 stdout/stderr의 `ok`/`FAIL` 패턴을 센다. 계약 테스트도 출력 기반 판정을 확인한다. 단언 문구 개수는 사용자 시나리오의 실제 실행·검증 개수와 같지 않다. 파일 basename을 식별자로 사용하여 다른 디렉터리의 동명 파일이 timing/기준선/재확인 매핑에서 충돌할 여지도 있다.

타임아웃은 부분 출력을 잃고 rc124로 처리한다. 하위 프로세스 트리 정리는 확인되지 않았다. 환경은 부모 환경을 복사하므로 HARNESS_STATE_DIR 격리는 각 테스트의 계약에 의존한다. 이번 범위에서 isolate 구현 전체를 확인하지 않았으므로 실제 격리 실패로 단정하지 않는다. 재확인은 같은 실패명 일치를 요구하지 않아 다른 비초록 결과도 재현으로 표현할 수 있다. 기록은 최신 요약 중심이며 소스·runner·환경·기준선 권한·원시 증거를 결합한 지속 receipt가 아니다. CPU로 표시하는 합도 측정한 CPU 시간이 아닌 실행 소요시간 합이다.

## S06 — status의 완료 표시에는 run 신원과 실제 배포 증거가 필요하다

지정 파이프라인과 원장에서 단계를 접지만 ledger가 없으면 빈 상태가 된다. 별도 전역 state_dir의 heartbeat/gate/circuit도 함께 출력하여 run 신원이 동일한지 보장하지 않는다. 오래된 flag·미래 시각·읽기 예외가 실제 프로세스 생존이나 lease 상태를 증명하지 않는다. 원시 이벤트를 세는 spiral 횟수와 상태 fold 사이에는 철회된 이벤트 처리 차이도 있다.

select_ready의 완료 계약에는 PASS뿐 아니라 SKIPPED도 포함된다. status의 완료 표시와 tick의 ‘전 단계 PASS’ 표현을 사람 승인·인수 성공으로 해석하면 의미가 넓어진다. 이상·대기 상태를 보여줘도 status 종료 코드는 0이며 구조화된 판정 API가 아니다. 이 CLI는 alpha/live 실제 배포, rollback, 모니터링 확인서가 아니다.

## Z01 — Zeus의 SDD와 흡수 경계

Zeus의 `domain/sdd.py:8–22,169–202`, `application/sdd.py:159–184`, `domain/model_routing.py:24–39`를 직접 부분 읽었다. 현재 8단계 정의 및 proposal-only/차단 상태는 유지해야 한다. 읽은 경로에서 request_advance는 승인 완료를 발행하지 않으며 모델 배정도 자격 완료로 간주하지 않는다. 이 검토로 이를 통과 상태로 바꾸지 않았다.

| 사용자 단계/요구 | 원본에서 가져올 후보 경험 | 아직 필요한 검증·설계 |
|---|---|---|
| 1 스펙 논의 | AC/GWT 추출, 후보/잔여 표시 | 사람이 승인한 시나리오와 스펙 revision의 결합 |
| 2 디자인·인터랙션 | workup 구조·누락 마커 | 시각 검토, 실제 사용자 기대, 누락/절단 분모 |
| 3 코드 작성 | 역할 카드·분해 계획·wave 안내 | 현재 cycle/attempt로 위임·수거 결합, 실행 주체와 자격 |
| 4 자체 검증 | 발견 0/단언 감소/재현 잔여 방어 | SKIP을 미검증으로 소비, 실제 oracle·환경·로그 |
| 5 alpha 배포 | 단계·게이트 인터페이스 | 배포 adapter, artifact/version/환경 receipt와 rollback |
| 6 QA·증적·사람 승인 | 승인 이벤트·HMAC·pending 표현 | 구체적 변경·시나리오·실측 hash에 묶인 사람 승인 |
| 7 live 점진 배포 | known_good 삭제 방어 등 원문 경험 | 실환경 단계적 확대, 승인·중단 조건과 실측 |
| 8 CS·반복 개선 | incident/capture 후보와 신선도 | 티켓-증거-원인-회귀의 연결, PG runtime 원장·GitHub Issues 동기화 |

Astra→Sol→Terra는 모델 이름이나 budget 프롬프트만으로 자격화되지 않는다. 원본의 역할 분배 경험을 가져오더라도 동일 평가 세트·실제 수행 결과·가드레일 버전·승인 주체에 대한 별도 자격 기록이 필요하다. Zeus PG runtime SSOT에 원본 JSONL/파일 상태를 그대로 추가 원장으로 복제하는 결정도 이 검토에는 없다.

Windows/Linux/WSL에서는 subprocess 실행 방식, shell 인자, 경로·시각·인코딩·원자 쓰기·동시 접근·프로세스 트리 종료를 환경별 검증해야 한다. sys.executable/Path/UTF-8 처리 자체는 유용하지만 3환경 등가의 실행 증거는 아니다. 삼성 휴대폰/태블릿, Device Farm SDK/MCP/live/replay는 유예 상태이며 구현·실기기 인수 완료가 아니다. mocked fixture나 원문 E2E 이름은 사용자 인수 분모에 넣지 않는다.

## 남은 확인과 정확한 종료선

전문 6개 정적 검토만 완료했다. 지원 파일은 명시한 구간만 읽었으며 전체 caller/config/test closure, 실제 GitHub 실패 원인, 실행·동시성·인가 재현, 현재 보안 키/OS 권한, 배포 환경, 실제 Claude 교차 검토는 이 문서가 완료하지 않는다. 후속 실행 계획은 root가 검토한다. 차단된 gatewriter 프로브를 재시도하거나 우회하지 않았다.

원본·runtime·공유 coverage·다른 리뷰어 파일은 변경하지 않았다. 생성한 자체 메타데이터 검사 결과는 `verification.json`에 분리하며 원본 테스트 PASS로 세지 않는다.

2026-09-09 인용 정정: 후속 validator 독해에서 S05의 _g_suite/suite_verdict 위치를 438–480에서 129–151로 바로잡았다. 두 범위는 기존 지원 원장에 이미 기록되어 있었고 root가 pinned 원문 120–160 및 430–480을 직접 재확인했다. 438–480은 reference runner다. 정적 결론과 실행 0은 유지하며 이전 보고는 Git 8e1b557에 보존한다.
