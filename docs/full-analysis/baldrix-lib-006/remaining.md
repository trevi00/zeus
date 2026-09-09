# 남은 범위와 시험 한계

Primary 본문 누락은 0개다. inventory의 24개만 분모로 삼고 supporting 21개는 별도 집계한다. supporting 중 test_repro_probe.py와 atomic_json.py만 전문이며 나머지는 기록한 부분 구간이다. 직접 호출자가 없는 것과 이번에 추적하지 않은 것은 다르다.

optimize_baseline, phase_tree, pipeline_gate_runner, project_paths의 직접 외부 caller/test 구간은 이번 범위에서 읽지 않았다. phase_detector와 prompt_origin의 모든 소비자, pipeline_overlay의 언어 출처와 모든 config 변형, pending_changes의 CN.run 및 rollback 전체, operator 원장의 breaker 소비와 실제 압축 복원, wonder의 쓰기/읽기 closure, repro_probe 이후 실제 staging/write 경로도 미폐쇄다.

시험 본문은 기대값·fixture·skip 의미만 읽었다. test_repro_probe는 텍스트 분류를 검증하는 오라클이고 실제 재현 시험이 아니다. quota 시험의 순차 increment는 병렬 reservation 시험이 아니다. psmux 시험의 미설치 skip은 호스트 round-trip 성공이 아니다. pipeline picker의 빈 src 시험은 src/main.py 출력 경로를 사용한다. 과거 주석의 PASS·실험 수치·완료 문구는 현재 실행 증거가 아니다.

향후 검증 대상으로 동시 quota 예약/저장 실패, 부분 append와 투영 누락, 세대·작업 fencing, phase hole 및 고정 분모, malformed YAML, 회고의 출처·크기·경로 경계, 실제 multiplexer 결과 영수증을 남긴다. 이 목록은 원본 시험·프로브 실행 승인이나 차단된 probe 우회 요청이 아니다.

사람이 정의한 8단계 SDD의 실제 승인 및 인수 계약, PG runtime migration/replay, Git 정의 해시의 runtime 결속, 모델 자격·actual Claude, 라이선스, vendor 현행 사실, Windows/Linux/WSL 실제 호환과 전체 채택은 미검증이다. 루트의 후속 공동 검토·구현 판단이 필요하다.
