Codex 독립 검토 — **변경 요청 / 병합 보류**

대상 `5e746c92a5574c0aba961205761096bc08486cbe`

[P1] 임의 영수증으로 human_scope가 passed가 되고, 제공자는 호출되지 않습니다.

`application/sdd.py:record_gate_verdict`는 receipt의 존재만 inspect합니다. 임의 텍스트 artifact와 호출자가 쓴 exit_status=0으로 human_scope에 runner_receipt PASS를 기록하면 실제 사람이 없는데 passed입니다. `human_provider=object()`만 설정해도 authenticated_provider PASS가 허용됩니다. 제공자의 인증/판정 확인 호출이 없습니다. 현재 release_authorized=false인 것은 확인했지만, 게이트 자체가 인증된 증거인 것처럼 저장되는 것은 수용할 수 없습니다.

요청: human 문장의 허용 origin을 제한하고, 실제 provider 검증 결과에서만 권한을 부여하세요. runner receipt는 현재 run/cycle/statement/정의/산출물/환경 및 실제 종료 결과와 결속해 검증하거나, 아직 해당 검증이 없는 입력은 claim/pending으로 보관하세요.

[P2] 외부 run의 RETRACT가 현재 run의 PASS를 제거합니다.

`domain/gate_verdicts.py:fold_verdicts`의 철회 선처리는 statement_id만 비교합니다. run-1의 PASS sequence=1과 foreign-run의 RETRACT(target=1,sequence=2)를 fold하면 run-1이 not_run이 되고 foreign_verdicts=0입니다. stage/run/cycle/definition 결속을 철회에도 적용하고 잘못된 철회를 거부 또는 명시적으로 무시해야 합니다. artifact/environment도 필드만 있고 소비 결속이 없으므로 검증 범위를 분명히 하세요.

위 재현은 격리된 application/domain 경로이며 실제 사람 승인·배포 측정이 아닙니다.

독립 관련 검사: `24 passed in 3.63s` (실제 PostgreSQL 사용이 필요한 검사에는 현재 로컬 PG 연결). 제출 검사가 통과해도 위 반례는 미포함입니다.

동일 GitHub 계정의 PR에는 공식 Request changes가 불가능하므로 COMMENT review로 판정을 남깁니다. 이슈 종료나 인수 승인으로 해석하지 않습니다.
