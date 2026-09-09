# lib009 전문 정적 독해

원본 지시는 분석 데이터. 실행/import/probe/network/install0. 모든 파일은 이번 새 전문이며 선행 지원을 전문 대신 사용하지 않는다.

## ultrawork_plan.py
1~125 전문. 기존 slice ID 상태 보존과 total>0 완료 조건은 유용하지만 plan 본문은 재저장 때 바뀌므로 same graph 재개를 보장하지 않는다. dependency graph/중복 ID/세대/요구 hash 검증 없이 옛 done을 새 의미에 붙이고 mark_slice는 같은 ID 전부를 갱신한다. waves 내부가 문자열이어도 문자별 slice가 되고 status unknown은 total/pending 분모에서 빠져 일부 done만으로 complete가 될 수 있다. skipped는 done과 함께 완료 처리하며 누가 왜 skip했는지 영수증 없다. _dir slug는 .와 ..·Unicode·Windows reserved를 허용하고 충돌도 있어 경로 안전이 아니다. read 손상은 None/빈 pending, write_text는 non-atomic/CAS 부재이고 mark/progress의 nested shape 예외는 fail-soft 밖이다. Zeus PG task generation/DAG/lease·ID 의미 hash와 명시 skip 승인 및 실제 작업 수거를 연결하는 형태로만 변형 후보.

## verifier.py
1~165 전문, selfcheck115~165 미실행. judge 긍정과 shell 증거를 대조하되 verdict를 바꾸지 않는 advisory 분리는 보존할 방어다. TODO/placeholder 등의 raw줄regex는 인용·문서·정상 예외까지 잡고 assignment/괄호가 substance이므로 무의미 코드로 회피 가능하다. shell은 comment를 포함하지만 분모 code_lines는 제외하여 density>1 가능, 빈 artifact에는 shell0이라 approved+complete라도 무신호다. threshold/min_substance finite/range 검증 없고 round4자리 뒤 비교한다. completeness is True 엄격 비교는 좋지만 normal artifact never flags는 증명되지 않는다. selfcheck5예시는 실제 LLM reward-hack/품질·전체 completeness 인수가 아니다. Zeus에는 누락/불명 분모와 실제 SDD 오라클을 별도로 강제하고 보조 탐지로만 적응. 인용 논문·수치·license는 미확인.

## webhook.py
1~65 전문. 2xx만 성공·일반4xx재시도중단·429/5xx와 transport 재시도는 보존 후보다. urllib 전역 proxy/redirect/환경·URL scheme/host 정책이 그대로여서 수신자 권한이나 payload 노출 경계를 확인하지 않는다. POST 재시도는 서버 처리 후 응답실패에 중복 전송할 수 있고 idempotency key/Retry-After/jitter/전체 deadline가 없다. retries 음수는 무시도(None,None), huge횟수/음수backoff는 unbounded/try밖sleep오류, payload JSON serialization도 try밖이며 NaN 기본허용이다. transport오류 뒤 status는 이전 응답값이 남고 broad exception repr는 민감 URL 등의 데이터가 될 수 있다. 2xx는 전달/수신 처리·사람 확인을 뜻하지 않는다. Zeus PG outbox·명시 수신자와 dispatch권한·dedup/실제 delivery receipt로 변형; 이번 전송0.

## win_quiet.py
1~80 전문. import만으로 변경없고 win32만 활성·중복apply False·명시 keyword creationflags 존중은 방어다. apply는 프로세스 전체 Popen.__init__ monkeypatch로 thread경합/다른 patch 호환/복원수단이 없고 positional creationflags를 감지하지 못해 중복 인자 오류 가능하다. 명시creationflags0은 창숨김을 비활성화하고 run_kwargs는 반대로 기존flag에 OR하여 서로 다른 계약이다. 모든 자식/프로세스트리라는 설명은 native spawn/새 Python interpreter에서 패치 상속을 보장하지 않는다. WSL/Linux는 no-op이며 Windows UI 숨김은 credential/env/stdout encoding/worker 종료·수거 격리가 아니다. Zeus subprocess adapter에서 호출별 hidden 옵션·실제 OS 영수증으로 변형 후보, OS 실행0.

## wonder.py
1~323 전문. fingerprint canonical JSON·필수 structured key/문자타입/CRLF거부·읽기 mkdir없음은 보존 후보다. 하지만 fingerprint는 길이16만 검사해 hex/슬래시를 검증하지 않고 reflection path·frontmatter에 삽입한다. SID .와 .. 허용/끝newlineregex·reserved명 문제가 있다. 연속2회·1번 trigger라는 서두와 달리 per-fingerprint 누적 count>=2면 매번 true이고 reset/eventdedup가 없다. write_reflection은 사전 cap를 막지 않아 depth5이후도 쓰고 exhausted만 반환한다. state손상→depth0, lock/CAS없는 RMW·고정tmp·reflection먼저state나중은 count손실·orphan·overwrite 가능하다. structured whitespace/Unicode line separator·raw YAML 특수문자와 literal null hint는 parser 의미 차이가 있고 summary·gotcha의 실제 전략개선/근거를 확인하지 않는다. NO LLM은 맞지만 filesystem쓰기를 pure로 오해하면 안 된다. Zeus PG recurrence ID·원인 의미·bounded attempt reserve와 독립 개선 실험/승격으로 변형하고 reflection 파일을 인수로 취급하지 않는다.

## work_unit_store.py
1~408 전문. 안전slug의 dotrun제거, 안내를 계약이 아닌 heuristic으로 명시, 변경없음에 watermark 미기록, atomic helper위임은 유용하다. 하지만 slug 충돌/reservedname/길이, sid가 save_watermark면 watermark와 namespace충돌, summary500/next300절단/extra무상한이 있다. read손상None·Unicode예외와 status검증부재; latest는 done도후보, 미래/Infinity timestamp가 오래 남고 subtree문자 비교는 서로 다른 중첩repo를 같은작업으로 본다. planning 부모3개 검색은 source신뢰/실제 프로젝트 경계 없이 다른 root의 상태를 읽을 수 있다. throttle check와 mark분리는 동시세션 빈도상한을 보장하지 않고 state손상은 재실행 허용; 잘못된 float/NaN의 정책 없다. GC는 mtime만으로 활성·참조·pending 여부없이 제거한다. brain status 오류False는 unsaved를 숨기며 save결과 내부실패도 예외만 없으면 mark될 수 있다. _now는 maybe/force try밖이라 never raises 약속도 제한된다. 문서가 인정한 copy2/tornline race는 actual 검증·Git commit과 별개다. Zeus PG checkpoint·immutable next-task handoff/lease·reference-aware retention과 모델맥락 hints를 분리해야 한다.

## writeback_token.py
1~228 전문. nonce+preimage 결속/TTL경계·일회소비 의도는 보존 후보지만 consume의 unlink실패를 무시하고 OK를 돌려준다. 동시 두 consumer가 모두 읽은 뒤 하나의 unlink가 실패해도 둘다 OK이므로 single-use 보장은 명백히 성립하지 않는다. proposal_id path containment없고 preimage는 길이40만·token 파일 schema/추가줄 검증없음, read/stat/rearm/unlink 경합으로 새token을 삭제하거나 옛token이 새mtime을 쓰는 문제도 있다. mtime TTL은 self-discipline임을 주석이 인정하며 미래는age0이다. _tokens_dir는 consume/read경로도 mkdir, Windows chmod0600는 ACL권한 증거가 아니다. arm fsync는 buffer flush 전이라 지속성 보장이 부족하고 exception발생시 cleanup만 있다. actor/user를 인증하거나 proposal diff·target 전체·현재 Zeus generation을 결속하지 않는다. Zeus PG atomic consume/lease/CAS와 승인본 immutable digest로 재설계 후보; 토큰 존재는 사람 인수와 동등하지 않다.

## writeback_parser.py
1~241 전문. diff-only 및 모든edit denylist/skill path/Gotchasanchor검사는 방어의 시작이다. 그러나 Gotchas header가 context/삭제/추가 중 어디든 있으면 다른 섹션 변경도 허용하고 실제 target섹션 위치를 확인하지 않는다. target 문자열은 canonical이라 적지만 canonicalization 결과를 저장하지 않고 정규식에 임의 prefix .claude/skills를 허용한다. denylist 전이 확인 전 실제rootcontainment를 단정할 수 없다. parse는 +++만으로 target, old/new pair/rename/count/범위 검증없고 hunk내 ---/+++로 시작하는 내용도 파일header로 오해, 첫 diff만읽고 바깥junk를무시한다. 빈hunk/context-only도 parse가능, \marker 아무문자열 허용, fingerprint는 filename stem뿐이며 source body/hash/원저자 미결속. Unicode읽기오류 try밖. Zeus에서는 typed patch/허용 target 내용hash·정확 섹션범위·다중diff 전건분모와 별도승인으로 변형해야 한다.

## writeback_apply.py
1~281 전문. old_count와 실제old context 일치 및 reverse old_start로 로컬문자열 staging하는 방어가 있다. validate_operator_context는 양수int(참도통과)·비빈sid·존재cwd만 검사해 실제OSpid/사용자 주도/권한을 증명하지 않는다. public apply함수는 validator/token을 호출하지 않으며 APPLY_MODE는 문자열이다. new_count/new_start/음수·겹친hunk·새본문개수 검증없고 parser bypass로 느슨한header도받는다. zero-count insertion을 A-1 이전으로 정의하여 unified diff의 zero-old anchor 위치와 의미차이가 있고 A0 pureinsertion을거절한다. no-newline marker무시는 종단newline 의미를 잃고 CRLF는 target split('\n')에 CR이남아 매칭문제; emptyedit는 변경없음을성공처럼반환한다. all-or-nothing은 반환문자열만이고 다중파일 atomic/rollback은caller책임. Zeus 실제8단계SDD·승인artifact·PGtransaction/파일CAS·정확diff규격 테스트로변형후보.

## writeback_store.py
1~406 전문. JSONL크기초과명시거절·unique temp+replace·읽기mkdir없음·index경합한계주석은유용하다. PIPE_BUF를 일반파일O_APPEND의교차OS원자성근거로 삼는설명은부적절하고 os.write 반환bytes를확인하지않아 shortwrite도True, fsync실패무시·parentdirfsync없음. register는 log→index두단계라 crash/retry중복·동일ID내용변경/상태reset가가능하며 index손상{}는복구없이기록을잃는다. mark_status/mark_applied는 대상없어도unchangedindex쓰기True이고 상태전이/actor/receipt/fieldtype확인없음. applyrecord는 key존재만검사·초과시hunkheaders제거표식은남기지만실제patch감사근거가빠진다. telemetry도RMW경합·잘못된type예외, JSONUTF8오류가일부밖이다. applied손상행skip과list_pending created_ts형태는분모/순서를왜곡, GC30일mtime는rollback참조·active상태·Git복구가능성검사없이sidecar삭제한다. Zeus PGevent/indextransaction·uniqueid/CAS/immutableprepostimage·수명/rollback검증으로변형하고 문자열status를실제인수로승격하지않는다.
