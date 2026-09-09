# Baldrix engine 001 — 공동 검토와 원본 함수 관측

정본 `cbb5c3e6c9c4af6f86626474f4d7d62fd8e8a6d2`의 engine 11개·80,138바이트를 Codex와 실제 Claude가 독립적으로 읽었다. Codex의 [최초 판단](codex-initial.md)은 Claude 응답을 읽기 전에 기록했다. [Claude 최초 응답](claude-initial.md)은 원본 그대로 보존하며, 그 안의 주장 전부가 최종 합의는 아니다. 파일별 의미는 Codex 최초 문서와 아래 정정을 함께 읽는다. `files.json`은 11개 전문, `supporting-evidence.json`은 root가 읽은 지원 24개(전문 19, 부분 5)를 원문 해시에 결속한다. 전문 3개는 직전 CLI005 독해를 재사용했음을 명시했다.

전체 분석·흡수 승인·Zeus 운영 구현은 미완료다. 이 파티션의 실행은 Linux 격리 컨테이너에서 아래에 적은 원본 함수와 원본 단위 테스트로 한정된다.

## 실제 관측과 그 한계

`test_dispatch_retry` 원본 **6개 단위 테스트가 통과**했다. 테스트는 주입한 callback, sleep, jitter를 사용하는 단위 시험이며 실제 모델 왕복이나 no-mock 인수 시험이 아니다. 최초 component 실행은 bare Alpine 이미지에서 PyYAML import 실패로 종료1이었다. 이때 원본 기능까지 도달하지 않았다. 실패 stdout/stderr/receipt와 당시 program/runner를 `components-missing-pyyaml.*`로 보존했다. 원래 receipt의 argv 경로는 실행 당시 경로이며, program SHA는 보존한 `.program.py`와 일치한다. receipt의 예정된 관측 설명보다 실제 returncode와 traceback을 우선한다.

이후 기존 고정 이미지 `sha256:39d4f226fa8b1ae6087b283b16d0176e9181f8aaf31dcbf0c9145e513453725a`의 PyYAML6.0.3으로 실행했다. 이미지 기본 entrypoint 대신 timeout과 `/app/.venv/bin/python`을 명시했다. network none, read-only root/source, nonroot, 임시 `/tmp` 입력에서 원본 함수를 직접 호출했고 mocking은 하지 않았다. 원문 1,648개 바이트는 전후 동일했다. 이는 사용자 운영 세션·원본 하네스 설치·모델·validator·Stop hook·실기기·Windows/WSL 실행이 아니다.

| 원본 함수 입력 | 실제 결과 | 의미 |
|---|---|---|
| architectural topic, 빈 proposal `{}`, feedback 없음 | fast path true | 제안 schema·세대·독립 비평 존재를 이 함수는 강제하지 않음 |
| gen1·gen2 verdict snapshot을 저장한 history | 둘 다 반환 | 현재 세대 제외라는 docstring을 함수가 구현하지 않음 |
| new_session 다음 update_phase | list_sessions phase_id 빈 문자열 | writer와 summary가 기대하는 필드 불일치 |
| child_sids.json에 유효 JSON `[]` | load_session.child_sids가 list | syntax fail-closed와 shape 검증은 별개 |
| gen2 running 정본 뒤 과거 gen1 exited shard 병합 | 최종 상태 gen1 exited | 재사용 pane의 세대 역행; 원래 발생 시각 대신 병합 시각 기록 |
| `not-json`만 있는 shard | 병합0, 파일 삭제 | 조사해야 할 손상 원문이 보존되지 않음 |
| `--json --ack-ts ...` | rc0 보고서, ack 파일 없음 | 옵션 조합이 ack 요청을 수행하지 않음 |
| 동일 키 두 개로 ack_many | count2, unique key1 | 보고된 처리 수와 고유 acknowledgement 수가 다름 |

전체 raw 출력은 [components-UTC0.stdout.txt](components-UTC0.stdout.txt), 실행 식별자는 대응 receipt에 있다. 출력에 존재하는 현재 시각·session ID는 테스트 입력/실행 식별자다. 불변 출력 snapshot이나 모든 환경의 동일 결과를 주장하지 않는다. crash·동시성·실제 프로세스 종료는 실행하지 않았다.

## 호출과 계약을 추가로 확인한 내용

`commands/harness-ralph.md`는 실제 Agent에게 전달되는 프로토콜이며 `run_validators`, `check_iteration`, `ralph_store`, `build_fix_prompt` 호출을 명시한다. “호출자가 없다”는 단정은 철회해야 한다. 다만 산문에 적힌 호출과 실제 실행 영수증은 다르다. 이 명령은 validator PASS를 완료선으로 삼고 reviewer sign-off를 non-goal로 둔다. 사용자 핵심 시나리오·SDD·사람 QA 요구에 그대로 채택할 수 없다. 같은 문서의 fix 오류 처리도 한 곳은 두 번째 실패에 escalate, 다른 곳은 다음 iteration으로 진행하므로 결정론적인 상태 계약이 필요하다.

`harness-autopilot.md` 287–305의 실제 프로토콜은 `require_evaluator=True`를 넘긴다. 따라서 wrapper 기본값 False를 근거로 모든 호출이 평가를 생략한다고 말할 수 없다. 반면 Stop handler 560–711은 shared sid를 확인한 뒤 실패하면 iterate로 막지만, 확인 전 오류/cold-start에는 모델 본문의 bool을 소비하는 inline 완료 경로를 남긴다. `bool("false")`도 참이 되는 coercion이나 실행 증거 없는 완료의 가능성을 실제 hook에서 재현한 것은 아니다. root는 이 연결을 정적으로 확인했으며 phase root의 exit_condition과 실제 인수 영수증을 wrapper가 검사하지 않는다는 범위를 유지한다.

`lib/quota_tracker.py` 전문과 strike_dispatcher를 추가로 읽었다. write_json_atomic은 파일의 반쪽 쓰기를 줄이지만 load→increment→write 전체의 lock/CAS가 아니다. record는 writer의 성공 bool도 확인하지 않는다. OSError 읽기는 strike의 on_corrupt=raise에서도 빈 counter로 돌아가며, coerce 모드는 음수·bool을 받아들인다. engine wrapper의 should_dispatch→record_dispatch 분리를 원자적 quota 획득으로 취급하지 않는다. 별도 CLI가 외부 lock을 제공할 수 있으므로 이 결함을 모든 caller로 확대하지 않는다. 또한 research_dispatched는 실제 Agent spawn보다 앞선 claim 기록이라는 명령 문서 자체의 한계를 보존해야 한다.

OpenAI provider 전문은 개별 subprocess timeout300초, 요청 모델이 없으면 `codex-default`라는 표지를 기록한다. Anthropic provider는 CLI180초이며 SDK 호출에 이 함수가 explicit timeout을 전달하지 않는다. 외부 SDK 기본값/재시도는 이번 검토에서 검증하지 않았다. engine의 `call_budget_sec` 미사용과 attempts 제한을 전체 deadline으로 읽는 것은 잘못이다. 실제 비용·model response identity·취소·자식 종료 영수증이 필요하다. PATH 존재는 실행 후보 발견이며 실제 vendor/model 증명은 아니다.

## 독립 보고를 읽을 때 적용할 정정

- Claude가 쓴 “최신 Claude 5”, 기존 모델 ID가 틀렸다는 주장은 외부 검증이 없으므로 철회 대상이다. 여기서는 pinned 문자열·선택 코드·영수증에 남는 identity만 판단한다.
- fast path는 keyword/feedback/proposal 조건을 함께 본다. open_questions 빈 배열 하나가 모든 주제를 우회시키거나 함수가 generation1을 강제한다는 뜻은 아니다.
- jury는 유효 표만 분모로 세고 plurality를 택한다. 2/1/1은 과반 없는 approved가 가능하며, 한 표 agreement1과 configured quorum을 분리해야 한다. 이는 인수 승인이 아니라 advisory의 강도 문제다.
- advisory의 try 밖 import/member resolution/result shaping과 permanent TypeError의 로컬 실패 가능성을 포함하면 “모든 예외 흡수”, “permanent=실제로 API 도달”은 보장되지 않는다.
- `list_sessions`의 phase_id 오류는 실측했지만 status event의 writer가 이 파일 밖에 있을 수 있으므로 “항상 in_progress”는 결론으로 사용하지 않는다. 문서가 안내한 `python -m engine.orchestrator list-sessions`의 entrypoint 부재는 원본 본문 정적 사실이며 해당 CLI를 실행하지 않았다.
- import 이전 CLAUDE_HOME 설정은 paths에 반영된다. import 이후 STATE_DIR 재결속과 정상 실행 격리를 섞어 모든 환경 격리가 깨진다고 말하지 않는다.
- 과거 snapshot55/85·CI 주석은 당시 원문 기록이다. 현재 빈도·미래 실패 확률·역사상 호출0·현행 CI 실패로 바꾸어 말하지 않는다. 현재 Zeus CI와 원본 workflow는 다른 검증이다.

## 공동 토론 상태

실제 Claude session `af04821f-f039-4790-97d8-5e72733fce0d`의 최초 독립 검토(365.23초)와 동일 session [토론](claude-discussion.md)(236.78초)은 모두 종료0/is_error=false다. 각 JSON 응답·stderr·usage/cost·SHA receipt를 보존했다. Claude는 모델 세대/대체 backend 추측, 호출자0, 과거55/85의 확률 해석, 예외 전량흡수, 모든 호출의 평가 생략, 정상 import 전 환경 격리의 오해 등을 정정했다. 재현된 상태 역행·손상 shard 삭제·ack 불일치를 수용했다.

root 최종 검토에서도 토론 원문의 다음 과장은 그대로 채택하지 않는다. `_tally`의 `if v in votes`는 list/dict verdict에서 TypeError를 낼 수 있으므로 “비문자열이면 조용히 무표 처리”가 아니다. fast path는 open_questions의 falsy 조건도 포함하며 토론의 3조건 요약은 이를 빠뜨렸다. 병합 시각이 항상 모든 기존 timestamp보다 크다는 보장은 없다. 이번 fixture에서 최신 상태가 덮인 사실과 future timestamp 등 다른 입력을 구분한다. 또한 토론의 “비테스트 caller가 트리에 없다”는 표현도 Python 문자열 검색 범위로만 남긴다. root가 직접 읽은 `harness-autopilot.md`에는 wrapper 호출과 `require_evaluator=True`가 실제로 적혀 있다. 유효한 산문 배선과 실행 보증은 다른 증거다.

남긴 이견은 argv 없는 ralph 기본 검사 범위, Windows 인코딩 가설의 미실행, 문서가 안내한 list-sessions entrypoint 부재다. 첫째와 셋째는 정적 사실이며 root 분석과 충돌하지 않는다. 둘째는 Linux 실행으로 입증하거나 반증하지 않았고 운영 결함 확정으로 올리지 않는다. Claude의 과거 발언 재서술이나 요약 건수보다 보존한 최초 응답·토론·원본 코드·실측 자체를 우선한다.

## Zeus 흡수 방향과 남은 일

보존할 경험은 순수한 재시도 계산, 판정과 advisory 분리, missing validator/empty outcomes 거부, stderr 보존, runtime inventory와 Git 정의 분리다. 수정해서 가져올 계약은 PG task/attempt/generation·실행 권한, event ID/순서/손상 quarantine, atomic claim·bounded budget·취소, schema와 model identity, 실제 실행과 사람 판단 영수증이다. sidecar snapshot이나 원본의 과거 PASS를 Zeus 승인으로 승계하지 않는다.

연결 이슈는 [실행 증거와 수집 횟수 #3](https://github.com/trevi00/zeus/issues/3), [동시 실행 #5](https://github.com/trevi00/zeus/issues/5), [완료 소비 #6](https://github.com/trevi00/zeus/issues/6), [배선과 실제 동작 #10](https://github.com/trevi00/zeus/issues/10)이다. 이는 토픽 연결이며 기존 이슈가 이번 발견을 구현·검증·해소했다는 뜻은 아니다. shard 원문 보존/세대 역행은 별도 구체적 티켓으로 이어갈 대상이다.

미완료: 전체 transitive caller/config/test, breaker/convergence/evaluator/phase의 전 경로, crash/concurrency 재현, 실제 hook/vendor, Windows/Linux/WSL 운영 등가, 라이선스·출처 처분, 모델 수행 자격 이전, 최종 Zeus 구현 및 실제 시나리오 인수. 사용자 유예에 따라 Samsung 실기기 단계는 수행하지 않았다.
