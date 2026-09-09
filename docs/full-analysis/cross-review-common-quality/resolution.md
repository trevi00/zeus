# Common 스킬 품질 — Codex·Claude 공동 검토

고정 Baldrix `cbb5c3e6c9c4af6f86626474f4d7d62fd8e8a6d2`의 스킬 절차 2개와 평가·검사 코드 2개에 한정한 검토다. 전체 하네스 분석·흡수·인수·배포 승인은 아니다. 원본 파일과 Zeus 실행 코드는 수정하지 않았다.

## 독립 판단과 토론

Codex는 네 원문과 직접 scorer/parser를 전문으로 읽고 `codex-initial.md`를 작성한 뒤 Claude 결과를 읽었다. 실제 Claude 세션 `22543b32-5bc8-4897-abca-dcffe1d90d6b`의 1차 보고는 `claude-initial.md`, 원본 JSON·실행 영수증은 같은 이름의 JSON 파일에 있다. Claude는 Read/Glob/Grep만 허용된 읽기 전용 세션에서 독립 판단했다. 2차에는 서로의 발견과 Codex가 실행한 테스트 증거를 제공했고 `claude-discussion.md`로 정정·합의·잔여 이견을 받았다. 두 Claude 호출은 모두 exit 0, is_error=false다. raw 보고서는 오류까지 포함한 원래 발언으로 보존하며 아래 판정을 우선한다.

Codex의 전문 읽기 17개와 각 SHA/의미/미해결은 `supporting-evidence.json`에 기록했다. 그중 새 primary 2개만 `files.json`에 반영한다. 다른 문서·의존성·테스트는 supporting이며 기존 primary 커버리지를 중복 승격하지 않는다. 읽은 범위와 실행한 범위도 같지 않다.

## 실제 실행

`run_evidence.py`는 캐시된 불변 Python 이미지 `sha256:7415fbc3c9e4979cc717d92377ab2bc7b2b4a2af1ac03cc52b5f3f88efedaf3a`에서 원본을 읽기 전용 마운트했다. 네트워크 없음, 비특권 uid, capability 제거, read-only 루트, 제한된 tmpfs·메모리·CPU·프로세스·기한을 적용했다. 호스트 라이브 설정·인증정보·실제 사용자 세션을 전달하지 않았다. 원본 1,648개 파일의 실행 전후 바이트 해시가 일치한다.

| 실행 | 실제 결과 | 증거 |
|---|---|---|
| 원본 `tests.test_skill_trigger_eval` | 6개 PASS, exit 0 | `upstream-trigger.receipt.json`, `.stdout.txt`, `.stderr.txt` |
| 원본 `tests.test_skill_quality_axes` | 9개 PASS, exit 0 | `upstream-quality.receipt.json`, `.stdout.txt`, `.stderr.txt` |
| 검토자 입력 관측 프로그램 | 8개 결과 묶음 수집, 프로세스 exit 0 | `reviewer-observations.receipt.json`, `.stdout.txt`, `.stderr.txt`, `observe_quality.py` |

원본 단위 테스트는 임시 입력 fixture와 SKILLS_DIR 설정 재지정을 사용한다. 실제 서비스·에이전트·사용자 인수 검증으로 부르지 않는다. qa-boundary 테스트는 원본이 기대하는 HOME 경로에 pinned 자산을 마운트해 파일 부재 때의 조용한 return을 피했다. 이는 해당 고정 자산으로 테스트를 실행했다는 증거다. 파일 부재 분기 자체를 이번에 따로 실행한 증거는 아니다.

## 합의된 발견과 범위

| 항목 | 관측 또는 정적 근거 | Zeus 적응 시 요구 |
|---|---|---|
| 인라인 주석이 opt-in을 끔 | 문서의 `quality_axes_enforced: true   # ...`를 그대로 복사한 입력이 문자열 전체로 파싱되고 enforced=false, 실제 CLI가 inspected=0 PASS 출력 | 명확한 입력 스키마·파서, 복사 가능한 예시 검증, 미검사와 PASS 구분 |
| 음성 사례 부재에도 PASS | 양성 1개·음성 0개 실제 CLI가 PASS/exit 0 | 검토된 시나리오 집합·분모·입력 유효성 기록. 문서의 7+/5+도 현행 코드 미강제이며 모든 Zeus 작업의 보편 상수로 복사하지 않음 |
| 무자격 경쟁자가 승자 | min_score99인 rival의 score2가 target1을 밀어내 실제 FAIL_RECALL/exit2 | 실제 운영 선택 규칙과 같은 후보·매칭·주입 경로로 평가 |
| 동점 target 우대 | 동점 score1에서 target이 이겨 PASS | 실제 선택 정책을 명시하고 동일하게 재현. 임의로 target을 무조건 지게 하는 정책만 추가해 운영 등가라고 하지 않음 |
| 지표 이름·판정 규칙 불일치 | 음성의 미매칭 비율 TN/(TN+FP)을 precision으로 표기. 양성은 match AND winner, 음성은 match만 판정 | 원시 매칭·순위·본문 도달 중 무엇을 측정하는지 먼저 정의. 각 혼동행렬·분모·선택 이력을 분리 |
| 리스트 파서 불일치 | `[a, b]`와 `[any]`가 G9/G8 오류로 실제 보고됨 | 공유 스키마로 producer/template/validator/router 연결 |
| 줄 경계 1줄 초과 계산 | 실제 250줄 LF/CRLF 입력 모두 line_count251로 실패 | 줄수 정의와 끝 개행 경계 시험. 아래 CRLF 정정과 구분 |
| 형식 검사와 실제 품질은 다름 | Source 하이픈·품질 축 substring, 실제 동작·인용 정확성·인수 결과는 검사하지 않음 | 형식/출처 대조/실행/독립 검토/사람 인수를 각각 증거로 연결 |
| 운영 주입 경로와 평가기 다름 | evaluator는 빈 detected_paths/cache, 별도 후보 탐색. 실제 hook은 stack 필터·pipeline boost·matched 필터·본문 예산·pointer를 적용 | 동일 후보 해시·설정·실행 환경·최종 모델 입력을 관측. Astra→Sol→Terra 자격을 축약 점수로 승계하지 않음 |

숫자 관측은 의도적으로 양성과 음성에 같은 토큰을 넣은 반례다. TP1·FP1·TN3인 경쟁자 없는 입력에서 보고값0.75, 원시 match의 precision0.5다. 모집단 성능 추정치가 아니며 모순 라벨을 거부하지 않는 입력 검사 공백도 보여준다. 고정 FP 정의·양성 통과 기준을 유지하면 임계1.0은 FP0 여부와 동치다. **측정 대상 자체가 다른 실제 매처와 모든 verdict가 동치라는 일반화는 하지 않는다.** 현재 이름 오류 하나로 모든 기존 PASS가 뒤집힌다고도 주장하지 않는다.

현재 pinned 코퍼스 안에서 inline-comment opt-in을 사용하는 스킬의 수와 실제 운영 누락은 조사하지 않았다. 복사 가능한 템플릿의 실패 재현을 현재 전체 운영 장애로 확대하지 않는다. FAIL stdout과 CLI exit 계약도 기존 consumer까지 확인해야 하며, standalone exit0만으로 정상 집계 경로가 무조건 실패를 놓친다고 단정하지 않는다.

## 정정과 남은 이견

- Claude의 CRLF 바이트 판정 차이 주장은 철회됐다. `Path.read_text()`의 universal newlines로 raw550/800바이트 입력의 gaps가 같다. Linux에서 관측한 이 성질을 Windows·WSL 실행 완료로 표시하지 않는다.
- Claude의 lint 문서 G1/G7 다발 실패 예측은 철회됐다. 직접 `_check_quality_axes` 호출 결과는 G2·G3·G4 세 건·G8의 6개 메시지다. 이 호출은 enforce 필터를 건너뛰므로 현재 main의 검사 대상으로 승격했다는 증거가 아니다.
- 원래 Windows 절대경로 인용은 비이식적이지만 pinned 상대경로 대응으로 원문을 대조할 수 있다. ‘원리적으로 검증 불가’는 철회됐다. 외부 링크 진위·라이선스·인용문·수치는 여전히 검증하지 않았다.
- 검사기는 `CLAUDE_ASSETS_HOME` 또는 설치 트리, hook은 USERPROFILE 또는 HOME의 `.claude/skills`를 사용한다. 항상 사용자 홈 또는 cwd를 봐야 한다는 일반화는 철회됐다. **이번 컨테이너에서는 HOME과 ASSETS_HOME이 같은 pinned skills를 가리킨다.** CLAUDE_HOME을 scratch로 돌린 것은 상태 격리이며, Claude 2차의 ‘이 영수증이 evaluator/hook 트리 불일치 실례’라는 표현은 부정확하다. resolver가 다르다는 정적 발견만 유지한다.
- Claude 2차 잔여 목록의 `skill_match.py 미열람`은 1차 전문 읽기 목록과 모순이다. 정확한 상태는 양측 전문 읽음·실제 hook 미실행이다. token_budget·threshold·pipeline·tech_stack 등 전체 transitive 경로는 아직 미완료다.
- Claude 2차는 8534바이트 lint 문서만 측정했다고 썼다. 이후 root 원문 측정에서 lint의 raw/정규화 UTF-8 모두8534, distillation 모두7946이었다. 바이트 수는 코드의 8192 임계 대조이며 8KB의 사용자 체감 토큰·성능 기준을 증명하지 않는다.

## 미완료와 다음 연결

이 검토의 채택 상태는 `not_approved_not_incorporated`다. 두 primary 코드도 `body_reviewed_call_test_trace_pending`으로 남긴다. 검증기 stdout 실제 집계 소비자, 운영 hook 전체 의존·설정·테스트, 외부 인용·라이선스, Windows/WSL 해당 원본 실행, 실제 모델 행동·인수는 남았다. `lib/graduation.py`의 directory-mtime 재사용·restore 캐시 우려는 supporting 정적 발견이고 이번 실행 대상이 아니다.

이 결과는 ‘자가개선 후보의 품질을 무엇으로 입증하는가’와 ‘모델 하향 자격을 같은 실제 경로에서 검증하는가’라는 두 티켓으로 나눈다. 원본 PASS·과거 성과·모델 이름을 새 Zeus의 승인으로 복사하지 않는다. 주 Codex가 전체 분석·독립 검토를 이어가고 이후 합의한 동작을 Zeus 계약에 맞춰 구현한다.
