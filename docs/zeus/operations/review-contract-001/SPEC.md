# 실제 검토 실행 계약 정합화

2026-09-16. 사용자 `진행하자`에 따른 다음 한 배치. Codex 분석·설계·독립 검증·수용, Claude 구현. 이전 team-profile-001 실패와 원장은 보존한다.

## 목표와 완료 조건

선정된 worker-v1을 적용한 작은 실제 Claude 변경이 command evidence replay와 실제 Codex 검토를 거쳐 PG 수용, cycle awaiting_operator(2/2), release_queue 0에 도달한다. 운영자의 검토 입력 보충·성공 상태 덮어쓰기·자동 재호출은 하지 않는다. 구현·정상/반례 테스트·실측·PR/CI를 한 배치로 마친다. 전체 로컬 자산 분석, 모델 자격 자동 이전, 배포·병합 자동화는 제외한다.

## 확인한 경로와 근거

- worker-v1 → Claude CLI → IMPLEMENTATION.tests(strings) → EvidenceInspections.snapshot/identity → EvidenceInspector policy authorization → Popen → observation → task.result → review_lead → AppServer developerInstructions → checkout clean check → PG decision/release → LocalCycle.
- 이전 canary의 실제 replay stderr는 `C:/Python314/python.exe: No module named pytest/ruff`이다. 실제 worker와 별도 venv 검증은 통과했다.
- Python 3.14.7 공식 subprocess 문서(2026-09-16 열람)는 Windows shell=False에서 env PATH로 실행 파일 탐색을 바꿀 수 없음을 설명하며 sys.executable/절대 경로를 권장한다: https://docs.python.org/3/library/subprocess.html#popen-constructor . 이는 이전 관측의 환경 차이를 설명하며 모든 호스트 오류의 원인이라는 주장은 아니다.
- 실제 Codex reviewer는 accepted=true를 반환했지만 checkout에 프레임·로그 세 개를 만들었다. AppServer의 developerInstructions는 tracked source만 금지하고 executor는 untracked도 거절했다. 전역 프레임 파일 지침과 모순되는 경계였다.
- Codex 공식 문서의 글로벌/프로젝트 AGENTS 지침 합성: https://learn.chatgpt.com/docs/agent-configuration/agents-md (같은 날 열람). 프로젝트의 구체적 readonly 지침과 transport developerInstructions를 일치시킨다. 현재 CLI 모델/권한/timeout은 바꾸지 않는다.
- 이전 worker tests 문자열에는 `-> 23 passed`와 `Full suite not run`까지 들어 있었다. parse_claim은 그 전체를 argv로 읽는다. 결과 설명을 지우거나 성공으로 재해석하지 않고, 생성 계약에서 tests에는 실행한 원문 명령만, 설명은 summary로 분리한다.

## 설계: 하나의 검증 컨텍스트

1. EvidenceInspector는 Python replay의 실행 파일을 신뢰된 숙주 sys.executable의 존재하는 절대 경로로 고정한다. 원래 claim argv에 먼저 기존 policy authorization을 수행한 뒤, 승인된 `python -m ...`의 첫 토큰만 정해진 interpreter로 바꾼다. 임의 model executable을 신뢰하지 않는다. 원래 argv와 실제 replay argv 및 argv_identical=false/변환 이유를 보존한다. 다른 명령은 기존 승인 의미를 유지한다. 권한 prefix를 넓히지 않는다.
2. cwd별 snapshot에 검증 interpreter, 정규화 cwd, 후보 cwd/src가 있을 때만 PYTHONPATH, 환경 값 digest를 결속한다. 부모 PYTHONPATH·Zeus/DB/Redis 비밀은 제외한다. snapshot을 만든 뒤 실제 replay까지 같은 값과 interpreter를 사용한다. 캐시 키도 그 컨텍스트를 포함하고 이전 row는 덮어쓰지 않는다. 필요하면 snapshot(cwd=None) 인터페이스와 application 호출·관련 fixture를 함께 갱신한다. domain/application에 adapter import 금지.
3. IMPLEMENTATION.tests는 기존 strings schema를 유지하되 schema 설명/implement 지침과 worker-v1 Reporting에 **실제로 실행한 재현 가능한 명령만, 설명/화살표/통과 수/미실행 항목 금지**를 명시한다. summary에는 실제 결과·skip·미실행을 정직하게 쓴다. 과거 claims 파서는 관대하게 고치지 않는다. profile 본문 digest를 재고정한다.
4. AppServer read_only developerInstructions와 repo AGENTS.md에 검토 기록 규칙을 맞춘다: tracked/untracked 모두 검토 checkout에 생성/수정 금지. 하나의 간결한 프레임·판정은 응답/도구 stdout에 기록하고 Zeus가 기존 D 외부 artifact store에 보존한다. 테스트 출력은 리다이렉트 파일 없이 수집한다. 추가 frame 파일/로그를 만들지 않는다. 검토 입력의 허용된 범위만 검사하며 전체 재검증은 명시된 소유자/CI에 맡긴다. 기존 clean/HEAD 검사를 완화하거나 파일을 자동 삭제하지 않는다. 모델 run 설정의 권한을 격리 보장으로 주장하지 않는다.
5. reviewer context에 trusted host interpreter와 review cwd/src를 보여 줘 테스트가 현재 후보를 검사하게 한다. 이 정보는 모델에서 받지 않고 host가 구성한다. 검토 프레임을 위한 전역 홈 설정 수정이나 임의 외부 파일 쓰기 권한은 추가하지 않는다. 기존 응답/도구 artifact가 검토 증거 경로다.

## 범위와 검증 행렬

허용: adapters/evidence_inspection.py, application/evidence_inspection.py, adapters/executor.py, adapters/app_server.py, worker-profile-v1.md/json, AGENTS.md, 관련 tests, docs/contracts.md, 이 작업 문서. 그 외 발견은 기록 후 이번 수용과 분리한다.

| 조건 | 수용 증거 |
|---|---|
| 실제 Python replay | 후보 src 전용 모듈을 가져오는 실제 subprocess, 잘못된 PATH/부모 PYTHONPATH가 있어도 올바른 sys.executable; 기록은 변환 사실을 명시 |
| 비허용/없는 interpreter | 승인 범위가 넓어지지 않음, 실행 전 명확한 실패 |
| cache/snapshot | cwd·환경값·interpreter 변경 시 이전 pass 재사용 금지; snapshot 뒤 부모 환경 변경에도 동일 replay |
| 실패/기한 | 기존 exit 불일치·timeout·출력 한도·원문 영수증 회귀 유지 |
| reviewer | start/resume의 readonly instructions가 tracked/untracked 금지와 stdout 기록을 명시; dirty checkout 거절 회귀 유지 |
| reporting | tests 명령과 summary 설명의 분리, profile digest 검사 유지 |
| Windows/Linux | 관련 fixture 실제 subprocess 테스트 + 최종 CI; Windows 실제 model cycle, Linux model 실행으로 확대 주장 금지 |
| 실제 완료 | worker 명령 replay checked, 실제 reviewer 반환 및 PG 수용 성공, cycle awaiting_operator, 2/2, 배포큐 0, 재기동 객체도 한도 유지 |

Claude는 집중 테스트와 Ruff만 실행한다. 전체 pytest(PG/Redis)와 CI는 Codex가 소유한다. 반복 전체 실행으로 900초를 소진하지 않는다. 테스트에서 protocol/model fixture와 실제 provider 실행을 구분한다. 실제 canary는 `cycle status`의 상태 조회 예제를 짧게 추가하는 문서 개선으로 제한해 review 계약만 검증한다.

이번 재승인 단계의 상한: 기존 기계 12 slots 보존 + Claude 구현 최대 2회(각 USD8 옵션/900초) + 실제 작은 Claude canary 1회(USD2/900초) + Codex 검토 1회(300초), 총 최대 4회/누적 16. 성공하면 여분을 쓰지 않는다. 이는 provider option이며 청구액 보증이 아니다. 자동 증액·자동 반복 없음. 운영 PG/Redis 및 기존 실패 schema는 유지하고 새 schema/namespace에서 실행한다.
