# 모델 호출 계약 — Codex/Claude 공동 검토 결론

고정 Baldrix `cbb5c3e6c9c4af6f86626474f4d7d62fd8e8a6d2`의 provider 5개, 19,724바이트를 검토했다. scope는 `f946d9363613d41347a188fa65135260ca9c2607b2d30865b7ad0430c481df0f`다. root와 실제 Claude가 먼저 독립적으로 전문을 읽고, root 초기 판단을 저장한 뒤 서로의 발견과 실행 증거를 대조했다. Claude 초기 검토와 토론은 동일 세션 `b09d17bb-44bb-4a39-8a52-9ae99d7e2174`에서 각각 종료 코드 0이었다. 초기 응답·토론·프로세스 영수증은 원문 그대로 남긴다. 초기 보고의 과주장이나 당시 영수증 부재를 사후에 지우지 않는다.

root의 직접 supporting은 7개이며 4개 전문, 3개 명시 구간이다. Claude가 별도로 읽은 supporting은 그 보고서의 범위에 귀속된다. supporting 검색이나 이웃 파티션 검토를 전체 primary 독해나 실제 모델 실행으로 확대하지 않는다.

## 합의한 구현 사실

- `base.py:19–58`의 dataclass/ABC는 내부 port 후보지만 실행 시 자료형·범위, deadline·취소·attempt, 예산·응답 schema를 강제하지 않는다. CLI 세 경로는 `max_tokens`와 `temperature`를 사용하지 않는다. SDK system, Claude CLI append-system, Codex/Ollama의 사용자 텍스트 wrapper는 같은 역할 권위가 아니다.
- `__init__.py:37–59`는 alias를 소문자로 바꾸고 선택 모듈만 import한다. backend 가용성·인터페이스·capability를 검증하지 않는다. docstring의 unavailable 예외 약속과 실제 조회 동작을 통일해야 한다. 라우터가 private registry에 결합하고 concrete adapter를 직접 가져오는 소비자도 있다.
- `anthropic.py:26–86`은 key 존재+SDK import로 SDK를 우선 선택한다. 선택 뒤 오류가 나면 CLI로 재시도하지 않는다. create 호출 예외는 unavailable로 뭉치지만 import·client 생성·결과 추출은 그 catch 밖이다. 명시적 SDK timeout/retry 정책은 없다. `max_tokens=0`은 4096이 되고 음수는 전달될 수 있다.
- `anthropic.py:88–119`, `openai.py:29–95`, `ollama.py:62–133`은 rc0 빈 stdout도 정상 응답으로 만든다. 실제 종료·절단·거절·tool-only를 구분하지 않고 stdout을 strip하며 stderr 일부만 남긴다. `AskResponse.model`은 요청/default 라벨일 수 있어 실제 응답 모델의 증명이 아니다. CLI usage의 None을 0이나 측정된 비용으로 소비할 수 없다.
- OpenAI adapter는 timeout만 통일 오류로 바꾸고 OSError를 그대로 내보낸다. 세 CLI 경로의 strict UTF-8 decoding 예외도 잡지 않는다. `external_jury.py:42–53,132–180`은 ValueError 하위의 decoding 오류를 permanent로 분류하고 breaker success를 기록할 수 있다. 이 경로의 성공 기록은 확인된 응답·모델 추론과 별개다. 연구 추출기는 `research_extractor.py:244–254`에서 unavailable만 잡으므로 모든 실패에 raw fallback이 보장되는 것은 아니다.
- `external_jury.py:195–280`의 call_budget_sec는 사용하지 않는 예약 필드다. adapter timeout, 총 시도 횟수, retry backoff, breaker 회복 대기는 서로 다른 값이다. Claude 토론에서 초기의 300초 retry backoff 주장을 철회했다. 실제 이번에 재시도·대기 시간을 측정한 것은 아니다.
- dispatcher의 Codex 경로는 adapter.ask를 호출하지 않고 subprocess를 중복 구현해 환경 필터와 replacement decoding을 제공한다. HOME/cwd/config 등의 효과와 실제 OS/vendor 격리는 별도 확인 대상이다. Claude/Ollama 경로는 다른 제한·JSON 실패 표현을 사용한다. 기존 기본 pool의 same-family 허용이나 source 모델 ID를 Zeus 자격으로 승계할 수 없다.
- Ollama 가용성은 PATH와 list의 줄 수로 판단하며 요청 모델 준비나 생성 성공을 확인하지 않는다. `ask`는 CLI 존재만 요구한다. endpoint/locality는 이 adapter에서 제한하지 않는다. 실제 현행 vendor의 네트워크 동작을 주장하는 것은 아니다.

## 실제로 실행한 범위

원본을 읽은 뒤 고정 Alpine 이미지 `sha256:7415fbc3c9e4979cc717d92377ab2bc7b2b4a2af1ac03cc52b5f3f88efedaf3a`에서 두 프로그램을 실행했다. network none, source/root read-only, nonroot 65534, capability 제거, 64 PID·256MB·1CPU·64MB scratch와 60초 내부 deadline을 적용했다. 호스트 하네스·인증정보를 마운트하지 않았다. 원본 1,648파일의 실행 전후 바이트는 같았다.

| 실행 | 관측 | 증명하지 않는 것 |
|---|---|---|
| 원본 `scripts/tests/test_providers_ollama.py` | rc0, 8 assertions PASS | 실제 모델 호출, 출력 품질·usage, 설치된 CLI의 성공 경로 |
| `component_observations.py`가 원본 registry/dataclass/provider 함수를 호출 | CLI 3종 없음, 3 provider 모두 instance 반환 후 available false 및 ask unavailable 예외. 대문자 alias 정상화, 공백 alias KeyError, None alias AttributeError, 잘못된 요청 값 그대로 생성 | 실제 SDK/CLI 응답, Windows shim·WSL, deadline·비용·breaker의 실행 결과 |

fake CLI/SDK는 사용하지 않았다. `instance_returned_without_backend` 필드는 프로그램의 상수 설명값이다. 증거는 그 상수 단독이 아니라 원본 getter 반환 뒤 실제 객체의 is_available/ask 호출이 완료된 전체 프로그램과 stdout이다. receipt의 일반적인 fixture 표기는 합성 모델 결과를 뜻하지 않는다. 실행 경계와 원시 프로그램을 함께 확인한다.

Ollama 자체검사는 환경에 따라 다르다. 이번처럼 CLI가 없으면 unavailable에서 바로 끝나지만, CLI가 있고 모델 목록만 없으면 실제 ask/spawn에 도달할 수 있다. 가용한 환경에서는 ask를 건너뛰고 OK로 계수한다. 따라서 이번 8 PASS를 모든 호스트에서 무해한 메타데이터 검사 또는 모델 인수로 일반화하지 않는다.

## 토론에서 정정한 주장과 남은 이견

Claude는 `-s read-only`를 부작용 완전 차단으로, SDK timeout 미지정을 무한으로, Windows/WSL 조건부 위험을 반드시 발생하는 실패로 쓴 초기 표현을 철회했다. source 주석의 token footer를 현재 실측치라고 부른 표현과 한국어 byte/token 비율의 확정적 추정도 철회했다. 전체 pinned tree에 vendor 인수가 없다는 주장 역시 읽은 시험과 확보된 영수증 범위로 좁혔다.

CLI **메인 프롬프트**는 stdin이지만 SDK에는 해당하지 않으며 모델과 Claude system은 argv에 실린다. 이를 모든 입력의 shell 안전성으로 확장하지 않는다. 특정 경로의 cmd 인용이나 WSL 실행 가능성은 이번 CLI-absent Linux 관측으로 어느 쪽도 증명되지 않는다.

추가로 root는 토론의 "추출 예외도 같은 오분류"를 엄밀히 한정한다. SDK 응답을 이미 받은 뒤 추출이 실패한 경우 provider에 도달했을 수 있다. 문제는 exception class만으로 reached/healthy·응답 유효성·비용을 동일하게 기록하는 계약이며, 모든 추출 오류가 네트워크 가용성 장애라는 뜻은 아니다. "SDK가 없었다"의 직접 증거도 CLI 부재와 API key 부재에 비해 약하다. key가 없어서 SDK 경로를 선택하지 않았다는 것이 이번 관측의 정확한 범위다.

capability/usage grep과 일부 시험 독해는 모든 cjs·문서 지시·간접 소비자 부재를 증명하지 않는다. Claude의 추가 시험 제안에 있는 '승인 필요/정책 밖'은 이번 정적 리뷰 세션의 실행 범위 제한에 대한 의견이다. 새 전역 사용자 승인 규칙으로 채택하지 않는다. 본 체크포인트에서는 그 시험을 실행하지 않았으며, 향후 작업은 기존 사용자 권한과 실제 실행 영향에 따라 root가 판단한다.

## Zeus 대응과 남은 작업

lazy registry와 작은 typed port, stdin 메인 프롬프트, nonzero 거절, 명시적 fail-soft 결과, 미상 오류에 대한 보수적 재시도 의도는 변형 후보로 남긴다. 실행 정책·필드 지원 행렬·정확한 원시 스트림·모델 및 사용량 출처·전체 deadline·PG 예약과 실패 회계를 하나의 계약으로 연결해야 한다. FA-019 초안에 모델 자격·실측 비용·호출 의미의 수용 기준을 담았다. FA-018의 완료 권위와 연결하되 토픽은 분리한다.

실제 vendor 규격/버전과 호출, Windows/Linux/WSL 설치·프로세스 종료·Unicode, 동시 예약·crash·비용, 모든 caller/config/test, license 및 사람 시나리오 인수는 남았다. 삼성 기기의 실제 인수는 사용자 지시대로 후속 단계다. 전체 분석·흡수·시범 운영 준비는 완료되지 않았다. 이 분석 묶음에서 source 및 Zeus 운영 runtime을 변경하지 않았다.
