# 직접 연결 독해

지원은 전역 primary coverage를 늘리지 않는다. 아래 범위만 이번에 읽었으며 테스트 실행은 0이다. 범위별 원시 바이트 해시는 supporting-evidence.json에 결속한다.

- path_denylist.py 1~167 전문: HOME 기반 금지 prefix와 realpath/normcase, Windows 긴 경로 정규화는 유지할 방어다. 허용 루트 containment와 적용 순간의 동일 파일 보증은 아니다. parser의 raw skill 경로 정규식과 별도로 검증하므로 traversal 및 symlink 변경 폐쇄가 남는다.
- writeback_inspect.py 84~125, 405~582: operator context를 현재 PID/cwd와 환경 SID 또는 cli-direct로 구성한다. 이는 사람 승인을 증명하지 않는다. 상대 target은 HOME/.claude 아래에서 resolve하므로 parser의 상대 .claude/skills 표현과 루트 계약도 재검토해야 한다. 읽은 사전 이미지 바이트를 토큰 검사와 적용에 재사용하지만 target 이름과 diff 본문까지 승인에 결속하지 않는다. 토큰 소비 이후 decode/apply 실패도 가능하다. sidecar 저장 후 순차 replace하고 실패 시 역복구한다. 다른 writer와 CAS가 없고 post hash는 실제 재독해가 아니라 의도한 텍스트다. 복구 실패 시 quarantine 저장 성공을 보장하지 못하며 audit 실패는 이미 적용된 뒤 수동 조정을 요구한다. atomic helper 전체 구현 및 나머지 CLI는 미독이다.
- reflexion_loop.py 70~137: wonder API의 누적 count>=2와 달리 이 caller는 count==2에서만 trigger한다. capture는 pending driver 일치 및 depth cap을 검사한다. cap 초과에서는 noop이며 여기서 강제 escalation을 하지 않는다. 전체 loop와 다른 caller 폐쇄는 미완료다.
- evaluator_dispatcher.py 1190~1224: verifier는 ledger 뒤 보조 기록이며 기본 artifact None이면 호출되지 않는다. completeness는 vote의 truthiness를 all로 모으므로 비어 있지 않은 문자열도 참이 될 수 있다. 의심 결과를 verdict 자체의 강제 차단으로 사용하지 않으며 예외는 무시한다.
- notification/dispatcher.py 1~50: Slack/Discord URL 및 Telegram token URL로 post_json을 호출하고 오류 문자열을 반환한다. 실제 설정의 권한, 알림 도달, retry 중복 방지는 확인하지 않았다.
- scheduler_driver.py 675~692: main이 인수 파싱 후 win_quiet.apply를 호출하고 run_pass에 진입한다. patch 결과를 검사하지 않으며 Windows 자식 프로세스 전체에 대한 실증은 없다.
- stop/autopilot_continue.py 455~485: Stop 입력의 SID와 planning metadata 일부 hash로 work unit을 기록하고 maybe_autosave를 시도한다. 예외는 삼킨다. 기록 성공과 실제 작업 완료/인수는 별개다.
- commands/harness-ultrawork.md 26~58: save_plan, pending 재개, model_router waves 병렬 실행을 문서에서 요구한다. 실제 worker 종료 및 결과 수집 영수증이 아니다. 문서 명령은 실행하지 않았다.
- scripts/tests/test_writeback_token.py 65~137: 정상 consume 삭제, mismatch, drift 보존, expiry 삭제를 assert한다. 이름과 달리 mode 검사 테스트 본문은 파일 및 내용만 검사한다. 동시 소비와 unlink 실패 오라클은 이 범위에 없다.
- scripts/tests/test_writeback_apply.py 28~97, 129~185: 임의 양수 PID와 임시 cwd를 real operator로 통과시키는 테스트이며 사람 인증이 아니다. pure insertion의 old_start 앞 삽입과 newline marker 무시를 그대로 기대하므로 표준 diff 동등성을 증명하지 않는다. 내용 불일치 거절은 유효한 방어다.

독해 중 tests/test_writeback_token.py라는 잘못된 경로를 요청한 inert reader가 FileNotFoundError로 끝났다(tool chunk c32c4e). 앞선 CLI 범위는 읽혔으나 테스트는 읽히지 않았고, 정확한 scripts/tests 경로로 다시 읽었다(5e06e1). 이 실패는 upstream 실행이 아니다. test_win_quiet.py라는 이름의 후보 부재는 관련 테스트 전체 부재를 뜻하지 않는다. 원문 링크/라이선스, 실제 모델, Windows/Linux/WSL 동작, 전체 전이 폐쇄 및 Zeus 채택은 미확인이다.
