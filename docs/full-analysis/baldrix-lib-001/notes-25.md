# lib001 전문 검토 후속 기록

checkpoint-15.md의 바이트는 보존한다. 그 뒤 새 전문 10개를 읽었다. 새 전문 합계21개, 선행 동일바이트 전문 재사용4개로 대상25개를 설명한다. source 실행/import/probe/test/install0. 아래 판단은 정적 코드 독해이며 실제 장애 재현이 아니다.

## advisory_ack.py
282줄 전문. plaintext ack registry이며 doc만 nonempty로 검사한다. key_field/type/tz 설명의 의미는 강제하지 않는다. 문서의 등록2개와 실제10개가 다르다. bounded plaintext라는 설명과 달리 key 길이/파일크기/보존기간 제한이 없다. key 개행은 load 시 여러 ack가 되고, whitespace key는 load.strip과 append의 불일치로 재기록될 수 있다. ack_many는 기존 set과 비교하지만 같은 batch 내부 중복을 제거하지 않는다. load+append는 잠금이나 CAS가 없어 exactly-once가 아니다. load의 일부 OSError는 빈 set으로 바뀌며 Unicode 오류와 write 실패는 별도다. import 때 STATE_DIR 경로가 고정된다. completed라는 ack 이름은 완료 증거가 아니다. actor/task/generation/artifact/승인 신원이 없다. legacy shim 동일성은 직접 검증하지 않았다. Zeus에서는 승인과 분리된 PG 알림 확인 레코드로 변형 후보.

## alert.py
271줄 전문. source+title SHA1 12자리 fingerprint는 프로젝트/task/detail을 포함하지 않아 다른 사건을 같이 suppress할 수 있다. append 후500행 tail 전체 재쓰기 및 repeat 갱신 전체 재쓰기에 잠금/원자 교체가 없어 손실 가능. _bump_repeat는 전체 재쓰기 하지 않는다는 설명과 반대다. 만료 뒤 새 alert는 repeats0으로 생성되고 _post는 누적 repeats를 보내지 않아 누적 요약 보장도 없다. _post는 webhook.post_json의 (ok,status,err)를 무시하고 예외가 없으면 ok라고 한다. raise_alert의 sent=True도 원격 수신 증거가 아니다. _bump_repeat는 쓰기 실패를 삼킨 뒤 증가 횟수를 반환한다. ack된 레코드 재발과 여러 writer 경합에 주의. title/source 길이 제한, actor별 ack, task identity가 없으며 detail은 local2000/webhook1000으로만 자른다. scalar JSON/Unicode 오류와 timestamp 변환 등 일부 예외는 never-raises 설명 밖으로 나온다. env webhook URL에 외부 POST 가능; 실제 송신0. Zeus outbox+수신결과/실패 상태 분리 필요.

## atlas_embeddings.py
257줄 전문. char_wb 2~5 TF-IDF 검색이며 의미 이해·정답·인수 증거가 아니다. 설명의 BaseSearchIndex/subclass, _fit_vectors/_score_query, SearchIndex.invalidate, .npz와 실제 SearchIndex/module invalidate/.pkl이 다르다. pickle.load는 변경 가능한 cache 바이트를 코드 실행 표면으로 읽는다. 무결성/버전/schema binding이 없고 pkl+metadata가 별도 비원자 쓰기라 matrix 행과 note identity 불일치 가능. vault를 모두 읽어16자리 normalized content SHA로 stale을 판정하며 mtime만 보는 fast path가 아니다. 중복 note id, UTF8 BOM frontmatter, read/stat/Unicode 실패, model 설정 변경은 별도 방어 부족. min_df1/max_df0.95는 문서1개에서 빈 vocabulary/상충 가능. top_k 타입/음수 검증 없다. snippet은 scoring 후 현재 파일을 다시 읽어 점수의 contenthash와 다를 수 있다. 공개 SearchIndex에 임의 metadata path 전달 방어 미확인. activation/권한 필터 없으며100~1000개 품질 주장은 실측 미검증. Zeus 파생 검색 adapter로만 검토; pickle과 권한/버전 결합 수정 전 채택 보류.

## autopilot_kha_bridge.py
295줄 전문. dispatch canonical EventStore와 phase projection을 이중 기록한다. phase append bool을 소비하지 않아 반환 레코드가 projection 성공을 증명하지 않는다. event id에 gen/attempt 결합 부족하며 outbox 원자성이 없다. git log --all과 subject의 phase/plan 표기는 현재 HEAD ancestry/작업자/실제 테스트나 산출물 증거가 아니다. timeout 없는 git, ambient env/config, short SHA/phase regex 한계가 있다. 다른 branch/stale commit도 완료 task로 표시될 수 있다. markdown table의 description pipe escaping 없다. SUMMARY glob은 내용/hash/is_file 검증 없이 존재 여부로 orphan을 판단한다. phase/plan glob/path 특수문자 검증은 부족하다. ack와 escalated projection도 비원자이며 bool 무시 가능. 실제 dispatch는 caller의 Agent 지시이며 이 helper 자체 spawn이 아니다. Zeus PG event+outbox, exact attempt/work receipt 필요.

## autopilot_phase1_merge.py
227줄 전문. payload/prompt 생성과 JSON 형식 판정이며 실제 Git merge가 아니다. worker_branches가 string이면 문자 iterable을 허용할 수 있고 중복/자기 branch/base identity 검증 없다. 임의 branch 문자열이 prompt에 들어간다. ours/theirs 금지와 worker untouched는 문자열 지시다. 마지막 fenced block 추출은 뒤의 무관한 code block을 고를 수 있다. branch/head는 nonempty string일 뿐 SHA/존재/expected branch 검증 없다. merged_workers empty/중복/미요청 항목도 허용하며 요청 집합과 대조하지 않는다. is_clean_merge({})는 get(None) 판정으로 True가 될 수 있어 parser 없이 쓰면 schema 검증이 없다. parsed clean이라도 실제 worker 종료, merge commit/parents/diff, 테스트, 사람 인수는 없다. Zeus typed dispatch와 runner receipt를 분리해 변형.

## bash_tool_routing.py
162줄 전문. 우선순위 regex가 첫 피드백만 반환하는 advisory다. Bash 파서가 아니며 double quotes/일부 heredoc 안 command substitution도 실행될 수 있는데 body stripping으로 가려진다. heredoc 종료 regex의 prefix 오인, -m/--message 계열 문자열을 git 명령에 한정하지 않은 제거, echo의 단일 > 의도가 >> 두번째 문자에 매칭될 가능성이 있다. 먼저 걸린 Read 조언이 Write redirection을 가릴 수 있다. PowerShell/alias/case/tool availability/권한은 입증하지 못한다. rg→Grep 조언은 Zeus 개발자의 rg 우선 규칙과 충돌하며 source 지시를 상속하지 않는다. 기존 reviewer에서 추출했다는 역사/이전본 동등성은 미검증.

## brain_autopush.py
185줄 전문. 외부 git fetch/worktree/orphan commit/push/강제 cleanup을 수행하는 effectful adapter다. 함수 자체 token 검사가 없고 caller authorization에 의존한다. env 전체를 상속하고 interactive만 끄므로 hooks/globalconfig/credentials/remote origin 영향을 받는다. 같은 home의 고정 temp worktree 이름에 lock/lease가 없어 동시 실행 cleanup이 다른 실행을 제거할 수 있다. finally cleanup의 subprocess timeout은 never-raises 보장 밖이다. remote branch 조회 실패를 없음으로 취급하며 -B는 공유 local branch ref를 바꾼다. orphan git rm --cached 및 git add 결과 무시로 code-only exclusion이나 최신 snapshot 보장이 깨질 수 있다. diff quiet0은 실제 push 없이 pushed=True; add 실패가 no-change로 보일 가능성도 남는다. FF-only/no force 방어는 유용하지만 거절 문자열 분류는 넓다. union은 동일id 다른 payload를 검증하지 않고 local overlay가 이긴다. 여러 layer/gradation snapshot은 하나의 atomic bundle이 아니다. 원본 실행/실제 push0. 자동 학습파일 유출/운영권한은 별도 승인 없이 Zeus에 흡수 불가.

## brain_git_status.py
131줄 전문. branch mode는 content diff라는 표현과 달리5개 JSONL의 live ID 집합이 로컬 origin/brain-snapshots ID 집합의 부분집합인지 본다. 동일id payload 변경, 삭제, 비대상 파일/gradation 변경은 모른다. fetch하지 않아 실제 remote 삭제/변경을 확인하지 않는다. malformed JSON skip과 read failure의 clean 취급은 unknown을 숨길 수 있다. fallback status/log 오류가0이 되어 upstream 없는 committed 파일도 not-at-risk일 수 있다. branch gitshow 오류는 remote empty가 되어 live nonempty이면 at-risk이므로 모든 오류가 항상 false라는 일반화도 피한다. Zeus contenthash+원격 immutable receipt, unknown 별도 상태 필요.

## brain_store.py
332줄 전문.5개JSONL와 graduation만 snapshot/restore. schema_version absent/None/문자열1 등 허용하며 record key/유형/hash는 검사하지 않는다. torn 마지막뿐 아니라 모든 잘못된 JSON line을 skip하고 read 오류는[]로 바뀐다. union stringify key는 int1/string1 충돌, 동일id 다른 내용은 overlay 우선. fixed .tmp는 동시 writer collision 가능, fsync/다중파일transaction 없음. timestamp 문자열 정렬은 시간순 보장이 아니다. evidence __line__ count는 dedup 수와 다르고 status divergence는0; 동일id 내용 변화도0이라 trigger가 놓칠 수 있다. 기존 snapshot union은 compacted insight를 되살릴 수 있고 retraction 소비 규칙은 transitive 미검토. graduation clean count와 epoch를 독립 max하면 과거 high count+새 epoch 조합으로 streak가 부풀 수 있다. 현재 live 존재 시 복구 안 함은 empty/corrupt에도 적용; retraction merge는 별도. seed의 _write_jsonl_sorted 자체는 key dedup하지 않는다. _save_graduation은 승인 flag를 직접 복제하지 않는 방어와 실제 자격승인 부재를 구분한다. Zeus PG immutable provenance/기록별 version·retraction·qualification 분리 필요.

## ambiguity_score.py
689줄 전문 및 내부 _self_check455~689 정적 읽음, 실행0. 6W substring keyword 출현률85%, 토큰entropy5%, unknown density10%의 점수다. 질문은 coverage에서 빼지만 entropy/marker에는 넣으므로 질문표현에 따라 종료점수가 달라진다. 'who what when where why how'만으로 coverage0이 되는 코드·내장 테스트는 구체 요구사항/정확한 답변/인수 시나리오를 증명하지 않는다. showing→how/reasonable→reason 오염을 의도적으로 허용한다. 'or so'는 단일 token으로 나오지 않아 EN exact marker에서 잡히지 않는다. TBD는 EN+KO 중복 가능, 추후/추후 결정/약 substring도 density를 중복/오탐시킨다. 코드·URL 제외는 실제 중요한 제약도 제거하고 bilingual 범위 밖 문자는 누락한다. gap0이면 나머지 축 최대 합0.15라 기본0.2에서 marker가 최대여도 PASS한다. bool threshold/weight는 numeric으로 허용; dataclass 직접 생성은 범위 일관성 강제 없음. NaN weight는 w>=0에서 거부되고 NaN threshold도 range에서 거부하므로 NaN 모두 통과라고 주장하지 않는다. 임의 weight/threshold 선택은 인증된 정책 변경이 아니다. 문서의 consumer wiring 별도cycle과 live consumer 주장은 충돌; 직접 harness-interview1~113에서 실제 Python 호출 지시가 있음을 확인했으나 실행 영수증은 없다. 역사8/8/15/15·LOCK·운영자 승인·외부원문 미검증. 내장 self-check는 자체 공식과 keyword fixture의 일관성이지 사람 인수/false-positive corpus 전반 검증이 아니다. Zeus 명확화 보조 신호로만 변형하며 SDD 완료권위로 채택하지 않는다.

## 직접 연결에서 확인한 제한
commands/harness-interview1~113: Python -c에 topic을 triple quote로 직접 치환하는 문서 지시는 안전한 입력 전달이 아니다. answers 경로의 unix_ts 문구와 interview_sid 코드가 다르다. ImportError면 ad-hoc weights로 fallback하므로 동일 gate 의미 유지도 보장하지 않는다. 이 문서를 실행하지 않았다.

commands/harness-autopilot28~96: pane all complete/force remove/Agent response merge는 지시 문서이며 worker 종료 영수증이 아니다. AC 기본 한국어axis와 lambda late binding 위험도 직접 문서 확인했다. source가 EventStore 정본과 projection 우선순위를 선언해도 실제 transaction 증거가 되지는 않는다.

run_brain_push1~123: main에서 환경 literal token을 확인하지만 함수별 authenticated actor는 없다. save 후 ack+flag consume 뒤 autopush하므로 push 실패에도 completed ack/rc0이 가능하다. flag claim을 side effect 전에 원자 예약하지 않는다. check_brain_push65~115는 status/error와 push at_risk 예외를 divergence0/False로 바꿔 조용히 남긴다. .gitattributes1~11의 merge=binary와 -text는 Git 충돌/EOL 정책이며 JSON 의미 merge나 runtime concurrency를 보장하지 않는다.

atlas_index325~382: ImportError와 build RuntimeError만 처리하며 ValueError/search 오류는 이 범위에서 안 잡는다. search query와 top3 id/score를 기본 telemetry로 적어 privacy/retention 검토 필요. webhook1~65: 실제 실패는 False tuple 반환이므로 alert가 그 값을 무시하는 연결 결함이 구체적이다.

strike_dispatcher1~124: HIGH는 threshold1, 일반strike는 공유 threshold, 세션 fingerprint 한도3. should와 record 분리는 원자 예약이 아니며 quota_tracker/runner 전체 closure는 남는다. reviewer469~492는 bash helper import와 main 입력 시작만 확인; 실제 피드백 출력 분기 전체를 읽었다고 하지 않는다. autopilot_continue227~260는 env opt-in compaction 실패를 삼키며 directive만 추가한다. allsolution60~85는 caller가 ok/broke/escalated/skipped를 기록하도록 지시하고 실패는 run을 막지 않는다.

## 테스트 소스 읽음과 미실행
test_brain_autopush1~118: local bare remote fixture의 정상 first push/idempotence/새ID/두clone 서로다른ID union/no-brain를 확인. 같은ID payload 충돌, git add/rm 실패, 동시cleanup, ambient hooks/secret에 대한 검증은 읽은 범위에 없다. test_brain_git_status1~115: 새ID 추가와 직접 fetch 후 quiet를 검사하며 동일ID 내용 변경/실제 remote stale를 검사하지 않는다. nonrepo False를 의도적으로 기대한다. 둘 다 이번 실행0, 파일 꼬리 runner 미독이다.

test_atomic_json130~210: Windows 열린 handle에 의한 replace 실패를 host probe 후 검사하며 POSIX에서는 bare return으로 skip이 명시 pytest skip으로 남지 않을 수 있다. transient test는 시간 sleep에 의존. retry bounded는 상수검사이고 negative tries API 반례는 없다. source scan의 정확한 'tmp . replace (' 문자열 찾기는 모든 writer 우회 검증이 아니다.0~129/211~끝 및 transitive fixture는 미독. 이 테스트 소스를 이번에 실행하지 않았다.

## 전체 제한
후속 quota_tracker1~158 전문 지원 독해로 checkpoint-15의 미확인을 좁혔다. QuotaCounter 생성자는 필드검증/대입만 하므로 _BLOCKLIST 생성 자체의 filesystem side effect는 확인되지 않았다. 반면 path/load가 ensure_dir를 호출하여 read 경로에서 디렉토리를 만든다. sid/subsystem/filename containment 검사는 없고 on_corrupt='raise'라도 OSError/빈 파일은{}다. coerce는 negative/bool과 일부 int 변환을 허용한다. record는 load-increment-write로 경합하고 write_json_atomic bool을 무시한 뒤 증가값을 반환한다. 그러므로 quota 감소/dispatch 예약 성공을 확증하지 못한다. source 실행0이며 선행 checkpoint는 역사 상태로 보존한다.

라이선스 원문·외부 링크·역사 토큰의 권위는 미확인. 모든 primary의 transitive caller/config/test closure는 미완료이며 아래 구간 밖은 읽음으로 승격하지 않는다. 이전 root의 ac_tree/axis_scores/Stop 실행 및 actualClaude 기록은 별도 선행 제한범위 맥락이다. 이번25파일의 실행·actualClaude·영역전체동등성·Windows/Linux/WSL 실동작 검증0. Zeus 현재 대응모듈은 아키텍처 제안이며 구현/흡수 승인 아니다. Git 정의와 PG runtime, source/task/generation/attempt/evidence binding, 모델 자격 및 사람 인수 분리 원칙을 적용해야 한다.
