# 로그·코드 연결과 미해결 경계

23개 로그의 434개 이벤트를 모두 읽었다. source-note 완료 모양 run 21개와 default-55는 gate_check 107개, gate_verdict 43개를 PASS로 기록하고 22번 disarmed된다. source_note-73은 시작 이벤트 하나뿐이다. **이 수는 원본 문자열 검사 기록이며 이번 테스트 통과가 아니다.** 파일별 이벤트 수·해시와 대상 연결은 mapping.json에 있다.

source_note-50은 openclaude이며 읽기 전용 배정으로 uptake 작성 실패 후 재배정이 명시된다. default-55는 합성 창 여섯 건을 보고하며 마지막 slug가 잘린다. 두 대상 문서 전문은 이 38개 밖이다. 52 protobuf, 53 portless, 54 humanizer, 56 caveman, 57 Memoryfields, 58 pdf-inspector, 59 LWN, 60과 71 skill decay, 61 TrueForge, 62 Krebs, 63 AmbientCSS, 64 Zuzai, 65 ClickHouse, 66 지문 결제, 67 CSS minify, 68 핀테크 VC, 69 YC, 70 Uber, 72 Firefox로 내용상 연결된다. 73에는 기사 식별자가 없어 추측하지 않는다.

57은 이미 처리한 mattpocock 대신 Memoryfields, 58은 openclaude 대신 pdf-inspector, 59는 완료된 pdf-inspector 대신 LWN, 60은 LWN 대신 33140을 골랐다고 명시한다. 이는 queue 원본과 spawn 프롬프트를 최종 결합한 증거가 아니라 로그 본문에 남은 대체 설명이다. 61의 시작~spawn 약 15시간 10분은 실제 검토 시간으로 세지 않는다. 68 dispatch의 양방향 한 축은 잘못된 30.7% 전제를 이어받는다.

특히 60의 uptake 결과는 Write/Edit/Bash가 없어 쓰기·추가·route 실행을 못 했다고 명시하지만 약 3분 뒤 문자열 PASS가 있다. 50과 달리 재배정이나 작성 영수증이 없다. 오래된 파일 재사용 가능성이 있지만 다른 작성자가 있었을 수 있어 실제 재사용으로 단정하지 않는다. 현재 33140 캡처는 71에 대응하는 내용이며 60 당시 바이트는 복구하지 않았다.

추적한 pinned 코드 전문은 pipelines/source-note.yaml, scripts/cron/note_archive.py, scripts/handlers/stop/subagent_harvest.py, tests/contract/test_source_note_contract.py, agents/researcher.md, agents/evaluator.md다. 이 보조 증거는 mapping.json에 해시를 기록하며 61개 분모에 더하지 않는다.

pipeline은 note 세 문자열과 uptake 두 문자열을 고정 출력에서 검사한다. 정확한 기사 ID·산출물 해시·작성 주체·canary 실행을 결합하지 않는다. note_archive는 첫 줄 ID의 고정 이름에 다른 내용을 덮어쓰고 gate 원장이나 별도 버전 이력을 확인하지 않는다. 짧은 해시의 충돌 불가능 주석은 보장되지 않고 일부 긴 정규화 이름은 길이 제한과 어긋날 수 있다. 이는 정적 분석이며 실패 재현은 아니다.

subagent_harvest의 tail은 마지막 assistant 내용의 **앞 400자**다. 44개 결과의 shard는 모두 null이고 session_id는 hook payload의 호스트 값이어서 독립 child 모델의 증거가 아니다. 모델 ID·원본 transcript 해시·child 식별자·명령 exit code가 없다. shard 탐색은 여러 문자열 값을 읽어 신뢰된 dispatch와 원문 내용을 엄격히 나누지 않으며 현재 active_run에 귀속한다. 위험을 지적할 수 있지만 이번 로그에서 실제 공격·오귀속이 있었다고 단정하지 않는다.

researcher는 읽기 전용이고 evaluator도 읽기 전용 역할 문서다. role_source=self_report와 빈 contract는 실제 child 도구 권한이나 모델을 증명하지 않는다. 계약 테스트는 단계·마커·gate 수·안전 이름 일부·queue 표본을 다루지만 오래된 산출물 재사용, 대상 ID·해시 결합, 버전 이력, 실제 쓰기 능력을 증명하지 않는다. **파일만 읽었고 테스트를 실행하지 않았다.**

남은 증거 작업은 실제 proposal 객체·route 소비 결과, queue·spawn 원문, 당시 산출물 해시, 잘리지 않은 transcript, 과거 33140 바이트의 교차 대조다. 따라서 제안 추가와 실험 성공은 역사적 자기 보고로 남는다. Zeus에는 대상 ID·해시·gate 결합, 역할 쓰기 능력 확인, 노트 버전 이력, 정정 계보, 분모 명시, 기록·소비·실험·승격 분리를 요구사항으로 연결한다. 구현 완료를 주장하지 않는다.
