# SUT·호출·설정 직접 독해

supporting-evidence.json에 아래 실제 독해 구간의 raw hash를 남긴다. 전부 이번 새 지원 독해이며 선행 지원을 primary 전문 대신 재사용하지 않았다. 원문 전체 전이 폐쇄는 아니다. notes.md의 지원 pending은 아래 지정 구간까지만 보완됐으며 나머지 caller/helper는 여전히 미완료다.

- insight_index 85~142,161~188: writer whitelist 및 caller module forbidden set, spec미확인 fail-open, lazy HOME/state 위임을 확인했다. pytest whitelist 확장은 실제 권한검사와 다르다. ModuleSpec을 immutable이라 부르는 주석은 이 검토가 보증하지 않는다.
- intent_doc_floor 32~69: YAML parser 대신 정규식으로 signal/provenance를 세며 실제 파일/line 내용 검증이 없다. 첫 fence pair만 본다. skeleton clean은 의미 인수가 아니다.
- ac_tree 101~146: advisory는 strict int이지만 gate는 bool(predicate)여서 truthy 문자열도 통과한다. 빈 leaf approved도 구현에 있다. 테스트가 빠뜨린 strict gate 반환 오라클을 추가 후보로 남긴다.
- action_evolver 375~509: 자기검사는 고정 clock과 synthetic event JSONL로 bigram/skew/silent/composite 이름을 검사한다. HOME를 여러 temp로 바꾸고 복원하지 않으며 clock복원도 finally가 아니다. 실제 반사·rewind 효능을 검사하지 않는다.
- ambiguity_score 455~689: self-check는 첫 실패 sys.exit1, 성공 None이라 wrapper의 비int0 정책과 연결된다. 6W 키워드 나열/반복어휘로 gate pass를 기대하며 실제 요구 명확성 calibration이 아니다. 원래 compute 본문 전체는 미독이다.
- advisory_ack 47~113 및 alias CLI38~60: load 오류는 empty, check-then-append에는 lock/CAS 없고 whitespace/newline key가 다중항목을 만들 수 있다. ack_many 입력중복도 개별 new를 제거하지 않는다. alias는 두 하위 main에 위임하며 테스트 happy path는 그중 하나를 fake로 바꾼다.
- advisory_research_dispatch 42~88: 소문자/공백 정규화 해시, HIGH와 blocklist/strike quota 뒤 별도 record이다. 임계치 검사와 소비를 원자화하지 않는다. strike store 전이는 미독이다.
- agent_tool_audit 36~106 및 세 agent 문서1~12: 실제 선언은 예상 도구 문자열이다. missing/빈 toolset에서 overclaim=[]이며 YAML parse/플랫폼 자격의 전이는 미확인이다. 원문 role 지시는 데이터로만 읽었다.
- agents_capability 51~118, agents_normalize78~112: regex frontmatter 텍스트 치환이며 모델 첫줄만 치환할 수 있다. YAML full roundtrip 및 실제 filesystem write를 이 테스트들이 검증하지 않는다.
- ai_spec_eval_coverage124~176: 범위 비교로 NaN/Inf는 거절되지만 path는 resolve 후 is_file/size만 검사하고 base containment가 없다. 전체 golden 사례 및 test 실행 분모는 세지 않는다.
- allsolution_metrics80~112: reached는 '도달한 run 수'라는 주석과 달리 각 유효 event row마다 증가하여 동일 run 반복 기록을 중복계수한다. synthetic fixture는 run/phase당 한 건이라 이를 놓친다.
- ambiguity_report20~45: score의 passes_gate를 bool로 사용하고 weight/value finite/type의 엄격한 검증이 없다. rounded contribution으로 dominant를 고른다.
- paths12~110,145~158: HOME와 ASSETS_HOME 분리 및 env 우선순위다. read-only는 분류 설명이며 write 권한을 제한하지 않는다. state_dir 본문 후반 및 telemetry 별도 override는 이번 미독이다.
- atlas_frontmatter60~142: 테스트 범위 밖 deprecated metadata/decision Consequences/supersedes 경고가 있다. 날짜는 정규식이고 supersedes는 수동 확인 요청이지 실제 링크 확인이 아니다.
- atlas_structure65~95: rglob 결과가 file인지 검사하지 않고 base_depth 인수가 쓰이지 않는다. ATLAS_DIR부재는 PASS(skip) 문구와 None 반환이다. 두 atlas는 validators registry1~83에서 builtin으로 확인하여 test doc의 run_units 발견 주장과 불일치한다.
- atomic_json30~127: temp random 이름/flush/replace retry는 보존할 방어지만 fsync오류를 무시하고 directory fsync/CAS가 없다. tries<=0일 때 max(1,tries) 반복과 i==tries-1의 불일치로 OSError 후 함수가 정상 반환할 수 있다. 기본값 시험만으로 모든 인수 방어를 보장하지 않는다.
- autopilot_compaction26~58 및 Stop238~249: every 타입/strict bool guard가 없고 sid를 directive에 직접 넣는다. 실제 Stop은 parts.append인데 테스트 simulation은 insert(0)여서 순서 동등성을 확인하지 않는다. env parsing 실패도 조용히 무시한다.
- autopilot_flip_policy32~67: default0과 관찰 write이며 자동 flip 아니다. extra가 record.update로 병합되고 실제 telemetry 실패 확인은 하위에 위임한다.
- autopilot_kha_bridge81~143: EventStore 먼저 append 후 projection append의 반환은 버리므로 두 파일 fixture 성공이 partial-write 방어를 입증하지 않는다. 이 범위 밖 commit/orphan helper 전체와 event store는 미독이다.
- agent_invocation_audit97~221: ORCH_SID 우선, regex SID 및 prompt head/tail hash, expected_tools 실패시[]로 기록한다. 완전 입력 read/regex/UTF8변환이 cap보다 앞이라 cap은 입력 메모리 상한이 아니다. parse 못한 경우와 logging 실패는 관찰 누락일 수 있다.
- agent_outcome_audit260~355,375~452: structural/evidence 검사와 advisory semantic/crossref를 분리하고 budget/heartbeat는 safe-call로 기록한다. critic_invoked는 env문자열로 계산한다. ledger success는 failure_mode None이라는 분류이며 실제 인수 결과가 아니다. 나머지 resolver/write/helper 전이는 미독이다.
- Stop627~701: shared-sid 판별 뒤 helper예외는 iterate이나 판별 전 실패는 legacy inline bool fallback이다. 테스트는 confirmed 뒤 실패만 확인한다. state done 저장은 실제 receipt 재검증/PG transaction이 아니다.
- settings.json242~254,262~274,294~306: 두 Agent hook과 Stop command는 사용자별 Windows 절대 Python 경로다. invocation 설정timeout5초와 테스트15초, outcome설정10초와 테스트20초가 달라 테스트가 실사용 timeout자격을 증명하지 않는다. 실제 등록·실행 확인0이며 다른 설정/인증정보는 열지 않았다.

primary 상호 호출: run_all은 run_units helper, run_units는 validator registry와 각 test main, pytest는 conftest를 이용한다. 이 primary 연결은 별도 지원 coverage로 중복 계산하지 않는다. 모든 source 실행/설치/네트워크/프로브0이며 남은 원문 라이선스·독립 Claude·OS·모델·인수·채택은 false다.
