# 직접 읽은 구현·호출·설정

supporting-evidence.json의 행 범위가 이번 실제 독해 범위다. 전체 source 파일의 해시를 구한 것은 전문 독해 주장과 다르다. 전이 구현·설정·caller의 미기재 부분은 미독이며 모든 원본 실행은 0이다. primary 본문은 각 SUT의 직접 test caller로 읽었다. 아래 runtime caller와 공통 runner/config는 추가 추적이고 전역 primary로 승격하지 않는다.

## 단계·그래프

phase_graph_builder 102~161은 PLAN 내용을 사용하지 않고 basename stem으로 artifact ID를 만든다. 같은 stem의 다른 경로는 첫 node가 남으며 edge는 중복될 수 있다. 두 단계로 선언 제목을 먼저 등록하는 방어는 보존할 후보지만 realizes는 파일명 관계다. phase_graph_query 20~90은 missing/비객체를 빈 graph, invalid direction을 both로 만든다. query는 dict edge만 걸러내며 객체의 schema/권위를 검증하지 않는다. 마지막 neighbors 반환 이후와 graph 쓰기 함수는 미독이다.

phase_tree 94~148은 문서가 말하는 sub_·multiline이 아닌 semicolon/comma 개수로 promote하고 IN_PROGRESS가 BLOCKED보다 먼저 반환된다. mixed IN_PROGRESS+BLOCKED는 현재 시험에서 빠졌다. pipeline_gate_runner 39~93은 전달된 docs_sha/attested_by를 검증하지 않고 Git root 조회와 JSONL append만 수행한다. now_iso/record 생성은 try 밖이라 never raises 설명의 전체 보장은 아니다. 실제 runner 영수증과 결속되지 않은 advisory로 유지해야 한다.

pipeline_stage_picker 46~122와 pipeline_status 39~84는 여러 output 중 하나만 존재해도 완료하며 디렉터리 존재도 인정한다. src에 디렉터리 하나만 있어도 nonempty heuristic이 참이다. picker는 선행 TODO를 넘어 가장 뒤 DONE 다음을 고르고 모든 완료 후에는 마지막 stage를 계속 선택한다. optional 제외 후 next index는 optional을 다시 선택할 수 있다. pipeline_yaml 145~188은 invalid/unreadable→[], unknown key 및 non-dict stage 생략, 정규화한 dict를 반환한다. missing id도 여기서는 명시 거부하지 않는다. Zeus SDD의 완료/승인은 이러한 존재 기반 순서와 분리해야 한다.

## validator·탐지

pr_squash_guard 176~249는 gh rollup을 조회하되 lookup 실패/빈 목록이면 침묵한다. name/state 등의 타입 오류 일부는 parse try 밖에 있고 required-check 정책과 정확한 head SHA를 확인하지 않는다. settings의 timeout5초는 여기 subprocess timeout8초와 다르다. 실제 host 종료 처리까지는 미검증이다.

prd 전문 1~98은 링크 존재와 user-story regex를 보며 첫600자 어디든 status:SKELETON 패턴이면 story 검사를 면제한다. frontmatter-only라는 주석과 parser 동작은 같지 않다. FAIL 출력도 main 반환/exit code를 바꾸지 않는다. private_content_leak 111~189 역시 FAIL 출력 뒤 정상 종료하며 read OSError는 빈 findings, malformed encoding은 replace, pointer 한 줄 전체를 면제한다. leak snippet을 telemetry에 기록하는 별도 효과가 있으므로 출력만 격리해서는 충분하지 않다. producer_consumer_coherence 375~418은 HIGH/MED aggregate와 문자열 PASS/FAIL이며 main rc 실패 전달이 없다. scan 하위 분석 함수는 이번에 읽지 않아 완전성 미확인이다.

project_analyze 325~378은 stack 탐지 뒤 registry의 can_extract/extract를 직접 호출한다. preview-only라는 주석만으로 extractor 전이 부작용 부재를 증명할 수 없고 이번에는 registry 전체를 읽지 않았다. project_paths 29~93은 normpath 상향 탐색과 marker 존재 검사로, realpath/symlink 경계·권한·프로젝트 identity를 검증하지 않는다.

## hook·모델·플랫폼

prompt_origin 전문은 leading marker 문자열 하나를 system-origin으로 분류한다. mode_detector 98~132는 system prompt라도 telemetry를 쓰고, debate_trigger 249~280은 origin 분류 전에 ack state/TTL과 prompt match를 다룬다. skill_match 311~344는 origin이면 scan 전 종료하지만 USERPROFILE/.claude/skills를 사용한다. agent_invocation_audit 154~185는 subagent_type이 없으면 prompt 처리 전에 return하므로 tests009의 hostile Agent payload는 그 경계만 통과한다. 이 검사는 비문자열 prompt 내부 처리가 안전하다는 재현이 아니다. 설정의 세 prompt command와 Bash guard/Agent audit command는 고정 Windows 경로 선언이며 설치/실제 provider E2E 관측은 아니다.

ollama 144~227의 _self_check는 metadata·availability bool·registry class 이름을 검사한다. available인 경우 실제 ask를 생략하면서 True case로 세고 성공 detail을 출력하지 않아 skip이 숨겨진다. availability 구현과 모델 실행은 미독/미실행이다. psmux 76~157은 기본 binary subprocess를 환경 상속으로 실행한다. command string은 whitespace split, command_argv는 별도 token으로 전달한다. timeout은 client 프로세스 처리일 뿐 이미 생성된 server/session의 종료를 보장하지 않는다. 전체 worker/result 수집은 미독이다.

conftest 전문은 function-scope HOME/whitelist/cache 격리와 _pytest 내부 stdin shim이다. 수집 import 이전 격리나 native encoding 검증은 아니다. run_units 48~166은 validator 이름 제외·fixture regex 분기, pytest 없음 SKIP/수집0 실패, 수동 rc0의 failure token 검사를 한다. 성공 stderr는 숨기고 환경을 상속한다. 이후 runner skip 집계/격리 구현은 이번 미독으로 남긴다.

## 상태·반복·자가개선

budget 113~162는 emit 실패를 삼킨 뒤 exceeded_emitted=True와 True 반환을 기록한다. 실제 전송 보장과 다르고 cap equality는 exceeded다. heartbeat_check 53~124는 corrupt/missing timestamp를 생략하고 매 호출 stale event를 내며 CLI에서 base_dir를 전달하지 않는다. 실제 scheduler dedup/실행은 별개다.

quota_tracker 72~158은 path가 mkdir를 하므로 load/get/remaining/reset도 읽기 전용이 아니다. sid는 비어 있지 않은 문자열만 검사하며 경로 탈출을 이 구간에서 막지 않는다. raise 정책도 OSError/빈 파일이면 빈 카운터다. record는 load 후 별도 atomic file write이므로 동시 increment 원자성이 아니다. ratio_tracker 28~78도 read-modify-write가 분리되고 numeric/schema 오류를 엄격히 닫지 않는다. repeat_error_tracker 105~174는 전역 fingerprint 카운터를 갱신하고 cleanup 후 경고를 만든다. 경고의 정책수정 지시는 데이터이며 이번 작업의 권한이 아니다.

reflection_recall 104~151은 fingerprint 필터와 note cap이 있으나 fp=None일 때 filename/frontmatter 불일치를 건너뛰는 검사가 적용되지 않는다. body를 지시문으로 재삽입하므로 외부 데이터 권한 격리가 필요하다. reflexion_loop 67~138은 exact count threshold에서 한 번 요청하고 오류/noop를 합친다. cap·write는 분리돼 있고 중복 turn ID를 받지 않는다. autopilot_continue 267~307은 bool(body.get(...))로 문자열 false도 True가 되며 capture absent/noop라도 pending을 무조건 비운다. 수제 상태를 전진시키는 이 경로와 실제 SDD gate 인수는 별개다.

register_task 163~238은 Windows 전용 install, 환경변수로 ps1에 인자 전달, rc0이면 등록됨 출력, remove 및 --with-token 파싱을 제공한다. ps1 전문/등록된 정의 재조회·실제 recurrence·삭제 결과·window/WSL는 이번에 검증하지 않았다. 플래그는 인증된 사람 승인 영수증이 아니다.

decision_memory 315~362는 현재 evidence가 없을 때 기존 거절을 유지하고 open_targets에 없는 발견은 종료된 것으로 취급한다. 관측 실패로 분모에서 사라진 경우와 실제 해결을 구별할 별도 계약이 필요하다. repro_probe 44~62,118~141은 원래 동작을 재실행하지 않고 객체가 만들어지면 passed 항상 True다. 명칭을 실제 재현 receipt로 흡수해서는 안 된다. research_extractor 197~275는 dict parse만으로 structured가 되며 is_available/_build_prompt 등은 try 밖이고 ask도 ProviderUnavailableError만 잡아 any-failure fallback 설명과 다르다. research_provenance 122~168은 unknown-only도 external0이라 confirm_only로 분류하면서 all local/repo라는 이유를 출력한다. URL/분류/모델 문자열은 원문을 읽고 주장 지지를 확인했다는 증거가 아니다.

Zeus 대응은 후보 설계만이다. Git 정의 revision과 PG 실행 generation/lease/fencing·실제 runner receipt·미검사 분모·사람 인수의 별도 권위를 적용해야 한다. 지원 미독 구간/전이 closure, 실제 Claude 공동 검토, 라이선스/외부 원문, 모델 및 OS 실행, 구현·채택은 미완료다.
