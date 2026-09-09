# Baldrix tests 007 독립 정적 검토

<a id="scope"></a>
## 범위와 증거 경계

`baldrix:scripts/tests:007`의 23개 원문, 199800 bytes를 전문 독해했다. 고정 revision은 `cbb5c3e6c9c4af6f86626474f4d7d62fd8e8a6d2`, scope SHA256은 `8efc3be2a990a1a6f88519655c8e234e6472eae5e7fce22d06910dcbc81b4d1b`이다. 시작 Zeus HEAD는 `18c91d6aaebf0ee2105daa822b1027cb73dcab44`이다. manifest의 raw Git blob·bytes·snapshot SHA256과 path-ledger의 원래 unreviewed 행을 대조하고 원본 행 및 그 해시를 files.json에 보존한다. 지원 파일은 supporting-evidence.json의 표시된 구간만 이번에 새로 읽었다. 과거 의미 독해를 재사용하지 않았다.

23개 primary의 manifest snapshot SHA256은 모두 존재한다. 지원 중 `get-shit-done/bin/lib/__tests__/merge-back.test.cjs`, `get-shit-done/bin/gsd-tools.cjs`, `get-shit-done/bin/lib/merge-back.cjs`에는 manifest snapshot SHA256이 없다. 이 세 파일은 raw Git blob/bytes 대조와 별도로 계산한 SHA256을 path-ledger에 대조했으며, 없는 manifest SHA를 존재한다고 세지 않는다.

이 보고서의 테스트 수는 정의와 main 목록을 읽은 정적 분모이며 실행 결과가 아니다. 원본 import·실행·probe·모델·네트워크·설치·실운영 상태·인증정보 접근은 모두 0이다. 차단된 gatewriter ERROR probe는 시도하거나 우회하지 않았다. 원본 문서의 지시와 역사적 실측 주장은 분석 데이터이며 상속하지 않는다. 아래 경로는 별도 표기가 없으면 pinned Baldrix 상대경로다. 실제 사람 인수, 실제 Claude 독립 검토, OS 실행, 라이선스, 전이 호출 전체, Zeus 채택은 완료하지 않았다.

가장 중요한 정적 경로는 L2 중복 근거 행을 세는 판정, 현재 phase 하나만 전달하는 milestone 진행, 변경 후 기존 pass 이월, 마지막 checklist로 한정되는 종결 분모다. 동작 가능성을 코드로 도출했으며 이번 범위에서 재현한 결함 또는 Zeus 현행 결함이라고 선언하지 않는다.

<a id="i01"></a>
## test_jury_advisory.py

9개 함수와 명시적 main 목록이다. env opt-in, 빈 prompt/member, 합성 verdict의 agreement/disagreement, ask 예외의 fail-soft, 두 반환 payload에 수렴 관련 최상위 키가 없는지를 검사한다. SimpleNamespace와 ask/members lambda를 주입하므로 실제 다중 vendor 호출이나 독립 심사 자격을 인증하지 않는다. `_boom`만으로 호출 부재를 증명하는 것이 아니라 반환 skipped_reason도 함께 확인하는 설계다. empty votes는 fixture의 `votes or default` 때문에 기본값으로 바뀐다.

직접 SUT `scripts/engine/jury_advisory.py:35–171`은 default off와 ask 예외를 방어하지만 members resolver 호출 124 및 결과 변환 153–171은 try 밖이다. 따라서 문서의 모든 예외를 삼킨다는 범위보다 실제 보호 구간이 좁다. `commands/harness-debate.md:57–66`은 이벤트 append와 별도 converge CLI 호출을 에이전트에 지시한다. 선언 연결이며 자동 실행 확인은 아니다. Zeus에는 advisory 기록과 Astra 최종 판단·모델 자격을 분리해 대응할 수 있으나 provider/수렴 전체 소비와 실제 Claude는 미검증이다.

<a id="i02"></a>
## test_kha_alias.py

17개 함수가 68개 rename map(단순 24/의미 44), 중복 이름, frontmatter 보존·생성, banner 중복 방지, 임시 SKILLS_DIR와 축소 map으로 alias 생성/재시도/check를 검사한다. 실패는 assert와 main 예외 집계다. `apply_actions(False, ...)`의 False는 dry-run이 아니라 deprecate_source이며 실제 fixture 파일을 쓴다. 이 감사에서는 실행하지 않았다.

SUT `scripts/cli/kha_alias.py:174–272`는 SKILL.md만 생성하고 동일 내용이면 source deprecation 처리 이전에 continue한다. 같은 alias를 먼저 만든 뒤 deprecate 옵션을 켜는 전환이나 하위 자산 복사·상대 참조·도구 권한은 시험하지 않는다. 생성 실패 목록이 있어도 여러 파일을 원자적으로 되돌리는 계약은 없다. Zeus 흡수에서는 이름 변경을 전체 기능 등가로 세지 않고 SDD 문서와 연결 자산을 함께 매핑해야 한다.

<a id="i03"></a>
## test_kha_migrate.py

11개 함수가 agent/skill map, longest-first 치환, 임시 5개 루트의 rename·reference rewrite·기존 alias skip·원본 alias 도구 제외·참조 남음 시 삭제 거절을 검사한다. force 삭제 fixture에는 실제 잔여 참조가 없어 force가 거절을 무효화하는 분기는 직접 잠그지 않는다. main에서 예외를 실패로 센다.

SUT `scripts/cli/kha_migrate.py:145–291`은 파일 쓰기 후 원본 unlink, 대상 텍스트 치환, `gsd-*` 디렉터리 삭제를 수행한다. 참조 세기 257–260에서 읽기 오류를 건너뛰므로 0은 전부 읽었다는 증거가 아니다. dry-run, 중간 실패 복구, symlink·Windows 대소문자·경로 경계·실제 전체 caller는 이 시험 밖이다. Zeus로는 reviewable manifest와 보존된 원본에 기반한 선택 흡수로 대응할 대상이며 이 삭제 절차를 채택하지 않았다.

<a id="i04"></a>
## test_kha_normalize.py

15개 함수가 분류·mutates/long-running 표기·frontmatter와 필수 절 추가·fixture 멱등성을 검사한다. 마지막 함수 151–161은 기본 SKILLS_DIR를 검사하지만 `ok=False`에서 만든 missing_section_issues를 assert하지 않고 issues가 list인지만 확인하며, ok=True에서는 단언이 없다. 이름의 모든 정규화 완료를 입증하지 않는다.

SUT `scripts/cli/kha_normalize.py:296–340`은 수집된 kha SKILL.md만 검사하므로 빈 수집도 issues=[]로 완료된다. 분류 표기의 정확성은 실제 mutation 인가·resume 동작과 다르다. 기본 경로 접근은 임시 fixture에 한정되지 않으며 runner 환경에 따라 의미가 달라진다. Zeus SDD 템플릿 검사에는 기대 파일 분모와 누락을 별도로 요구해야 하고, 여기서는 live 읽기를 수행하지 않았다.

<a id="i05"></a>
## test_l2_facts.py

14개 함수는 canonical value·SPO ID·confidence 공식·writer/reader whitelist·append/query/retract·provenance edge·latest 및 2000개 fixture 조회 성능을 검사한다. `_caller_module_name`을 문자열 lambda로 바꾸므로 실제 호출 provenance나 악의적 접근 경계를 검증하지 않는다. decorator는 CLAUDE_HOME을 임시화하고 일부 sys.modules를 실행 전에 지우지만 실행 뒤 모듈 객체를 복원하지 않는다. 실시간 accessor 덕분에 홈 값의 영구 고정이라고 단정할 수 없고 모듈 참조와 cache 복원은 별도 공백이다.

SUT `scripts/lib/l2_facts.py:126–228,286–359,380–442,474–562`에서 읽기 경로는 디렉터리를 만들지 않고, 쓰기는 append, query는 동일 ID 마지막 행을 택한다. confidence `1-1/(n+1)`은 단조 공식이며 경험적 성공 확률이 아니다. limit=0은 `out[-0:]`여서 전체가 반환되는 정적 경로지만 이 경계값 시험은 없다. edge는 비어 있지 않은 문자열만 검사하고 원본 L1 실재·철회·고유성을 보장하지 않는다. `is_insight_floor`의 support는 edge 행 수이며 철회 필터가 없다. 50회 sample 최댓값을 p99 근사로 부르는 테스트는 조회 건수·기기·콜드/웜 조건을 고정하지 않아 배포 성능 증거가 아니다. Zeus PG의 경험 후보는 provenance·고유 근거·철회 전파·자격 판정을 별도로 요구한다.

<a id="i06"></a>
## test_l2_promoter.py

18개 함수는 합성 L1 dictionary를 통해 active/reserved, 3개 support와 2개 session, group/summary 구분, 순열 비교, ts=0 안정성, evidence mapping, cascade와 재승격 ID 집합을 검사한다. session identity는 합성 correlation_id이고 실제 세션·사람 검토를 확인하지 않는다. shuffle은 seed 없이 한 번 비교한다. schema_version==1 시험은 버전 전이의 단조성을 검증하지 않는다.

직접 SUT `scripts/lib/l2_promoter.py:65–364` 중 원장에 기록한 구간은 source_module/axis/event_type/summary 앞 30자를 키로 쓴다. 같은 30자 뒤에서만 의미가 달라지는 입력은 이 시험 밖이다. ts=0 fallback은 현행 방어이며 과거 결함으로 재보고하지 않는다. 모든 ts가 없는 입력에서는 time.time을 써 동일 입력 결정론의 예외가 남는다. promote_all 301–313은 동일 후보와 모든 edge를 매번 append하고, `l2_facts.evidence_for:504–512`는 중복 edge도 돌려준다. recompute_cascades 346–358은 고유 L1 ID 대신 살아 있는 edge 행을 센다. 예를 들어 동일 3개 근거를 여러 번 승격한 뒤 2개 L1을 철회하면 남은 한 ID의 여러 edge가 threshold를 채울 조건이 있다. 정적 도출이며 재현하지 않았다. 기존 idempotence 시험은 fact ID 집합만 확인해서 이 경로를 잡지 못한다.

실제 소비 `scripts/cron/run_l2_promotion.py:110–185`는 token 함수 뒤 flag를 확인하고 promote_all 반환 후 ack·flag 소비·streak reset을 한다. 성공 counter는 신규 고유 fact 수와 같지 않다. token 구현 자체·스케줄러·동시 writer·실제 reader 주입 전체는 미독이다. Zeus는 반복 경험을 후보로 누적하되 자동 채택/모델 강등 자격으로 해석하지 않아야 한다.

<a id="i07"></a>
## test_l2_promoter_eligibility.py

6개 함수는 AST·inspect 문자열과 상수 집합을 검사한다. sentinel을 참조하는 If 안 어딘가에 Raise가 있는지를 ast.walk로 보므로 실행 조건·도달 가능성·예외 타입 전체를 잠그지 않는다. `_eligible` 문자열에 ELIGIBLE이 있고 RESERVED가 없는지와 STATE_DIR import 모양을 검사하는 것도 동적 접근까지 증명하지 않는다.

현재 SUT `scripts/lib/l2_promoter.py:72–111,178–180`에는 active 2종, reserved 5종, 모듈 로드 시 RuntimeError guard와 active whitelist 술어가 실제 존재한다. 이 방어를 부재라고 주장하지 않는다. 다만 AST 검사의 미래 변이 감도·실제 caller 권한·OS 실행·Astra→Sol→Terra 자격은 미검증이다.

<a id="i08"></a>
## test_ledger_compaction.py

6개 함수가 task_hash별 최신 행, human_override 보존, 키 없는 행·foreign row 보존, 재압축 멱등, 회수 비율을 검사한다. main이 test_ 이름을 동적으로 모아 실패를 집계한다. `scripts/lib/ledger_compaction.py:1–80`은 순수 계획이고 시간은 문자열 정렬, 동률은 뒤 행을 택한다. 빈 override dictionary는 truthy 보존 조건을 만족하지 않으며 이 경계값은 시험하지 않는다.

실제 cron `scripts/cron/run_ledger_compaction.py:70–139`는 archive를 먼저 append한 뒤 임시 파일 replace로 원장을 갱신한다. 순수 unit의 멱등성이 concurrent append·archive와 원장의 원자성·crash 복구까지 보장하지 않는다. 실운영 로그 압축은 실행하지 않았다. Zeus PG 정본은 압축 후 감사 흔적과 transaction/retention 경계를 별도 설계해야 한다.

<a id="i09"></a>
## test_logging_failopen.py

3개 함수는 jsonl_append에 IOError/RuntimeError를 주입하고 None 반환·예외 비전파·stdout 실패 marker 부재를 검사한다. 실제 disk-full/permission·stderr notification 전달·유실 측정 시험은 아니다. SUT `scripts/lib/telemetry_log.py:13–57`은 예외를 stderr로 보낸다. 그러나 append mock 이전에 `ensure_dir(tdir)`를 호출하므로 단독 실행의 전역 telemetry 디렉터리 생성 가능성이 있다. 이 테스트는 telemetry root를 자체 격리하지 않는다.

`run_units:130–166`은 rc0에서 stderr를 숨긴다. 여기서는 의도된 로그 fail-open 계약이지만 사용자 요구의 누락 알림/필수 승인 증적에는 그대로 적용할 수 없다. Zeus에서 비필수 진단 손실과 필수 증거 기록 실패를 나눌 설계 대상으로 기록하며 실제 로그 유실을 관측한 것은 아니다.

<a id="i10"></a>
## test_logical.py

3개 함수가 temp cwd의 없음·정상 markdown·키/인덱스 없는 문서에서 stdout PASS/FAIL을 검사한다. `_run_in`은 logical.main 반환값을 소비하지 않지만 외부 test main은 assert 예외를 rc1로 변환한다. `scripts/validators/logical.py:65–139`는 파일 없음에 PASS(skip), 테이블 구분자/PK/FK/INDEX 키워드와 조건부 ER 엔티티 수 비교를 한다. 실제 DDL 적용·관계 의미·데이터 무결성·결제 트랜잭션을 검증하지 않는다. 이 primary에는 ER 교차 비교 fixture도 없다.

`validators/__init__.py:34–92`의 logical 등록으로 run_units에서 제외되고 run_all validator 경로 대상이다. SDD 설계 정적 힌트에 해당하며 미대상 0건을 기능 PASS와 구분할 필요가 있다.

<a id="i11"></a>
## test_merge_back.py

0개 test_ 함수이며 main이 Node 시험 파일 하나를 실행하는 wrapper다. node 없음은 `[SKIP-SUITE]`와 rc0으로 run_units skipped 집계에 연결되는 현행 방어다. 파일 부재/rc nonzero/timeout은 실패다. 실제 timeout 인자는 50초인데 오류 문구는 180초로 남았다. rc0이면 TAP 일부를 보여주며 검사 개수 0을 별도로 거부하지 않는다.

직접 Node fixture `get-shit-done/bin/lib/__tests__/merge-back.test.cjs:1–245`에서 temp Git/worktree와 command subprocess, FF/non-FF의 JSON 및 HEAD 파일 확인을 읽었다. 원문 Node 전체 444줄 중 나머지는 미독이며 전체 scenario 분모를 주장하지 않는다. setup 이후에야 t.after가 등록되는 경로여서 setup 실패 시 cleanup 공백이 있다. 실제 CLI route `get-shit-done/bin/gsd-tools.cjs:474–481`과 `get-shit-done/bin/lib/merge-back.cjs:205–267`은 worktree 목록을 모아 mergeOneWorktree에 넘기고 결과를 출력한다. 개별 merge/helper·나머지 scenario는 미완료다. 실제 Git을 쓰도록 설계된 시험과 제품 배포/사람 인수는 다르며 이번에는 어느 것도 실행하지 않았다.

<a id="i12"></a>
## test_meta_rules.py

0개 test_ 함수인 wrapper가 `_self_check()`의 int를 반환하고 그 외 타입은 0으로 처리한다. 직접 `scripts/lib/meta_rules.py:274–364`는 registry 존재·동결·상태/버전/계층·supersession 모양을 case helper로 집계하고 실패 시1을 반환한다. 현재 소비는 연결되어 있다. frozen 검사는 모든 예외를 성공 취급하므로 반드시 동결로 실패했는지는 제한된다. registry metadata 확인을 실제 mutation token 인가나 사람 승인 실행으로 세지 않는다. registry 전 항목과 실제 enforcer 연결은 미독이며 Zeus 권한 등가는 pending이다.

<a id="i13"></a>
## test_milestone_checklist.py

7개 함수와 HC._self_check 호출이다. degraded code/template 양방향, fallback 문구, gate reasons→blocking 1:1, clean gate, 45개 중 CAP40 밖 5개의 종결 차단, 참고 항목 제외, prose 없는 rendering을 검사한다. deferred를 분모에서 잃지 않는 현행 회귀는 유용하다. 추가 self-check 본문은 이번에 전문 읽지 않았으므로 별도 assertion 수를 합산하지 않았다.

직접 `scripts/lib/milestone_checklist.py:187–190,292–330,394–450`은 item ID를 source/source_ref/phase로 만들고 HEAD를 포함하지 않는다. pass 이월은 reexec_phase_ids 밖이면 적용되며 blocking_item_ids에는 actionable/deferred만 포함된다. `milestone_step:598–606`은 reexec_phase_ids를 넘기지 않는다. fixture 전건 pass는 실제 사람 승인 증거가 아니고, 변경·재실행 후 같은 ID를 다시 검수해야 하는 경계가 미검증이다. Zeus SDD6 인수는 spec/scenario/commit/attempt에 결속할 설계 대상이다.

<a id="i14"></a>
## test_milestone_close.py

9개 함수가 이전 실패 note 보존, 이유/근거 payload, 어휘, CLI 필수 입력/unknown milestone 거절, dry-run, CLI 2회 멱등, liveness CLOSED 연결을 검사한다. 마지막 test_live_tree_has_no_stalled_milestones는 CLAUDE_STATE_DIR를 잠시 제거하고 기본 루트를 scan한다. main 전체에서만 env 원복을 보장하며 개별 pytest 호출은 앞 함수의 temp env를 남길 수 있다. conftest의 CLAUDE_HOME 격리와 별도 STATE_DIR 우선순위에 따라 의미가 달라진다. 이번 live scan은 수행하지 않았다.

SUT `scripts/cli/milestone_close.py:45–121`의 직접 close()는 docstring과 달리 이미 종결 검사·reason/evidence 필수 검사를 하지 않고 append한다. 방어는 CLI main에 있다. fail 판정을 남겨 둔 채 closure=true를 추가하며 degraded 필드도 없고 actor는 입력 문자열이다. `milestone_liveness:128–130`은 이 closure를 종결로 본다. 이는 운영상 수동 종결이며 제품 인수/라이브 배포 승인으로 재사용해서는 안 된다. 별도 `milestone_verdict close`와 계약이 다르다.

<a id="i15"></a>
## test_milestone_feedback.py

9개 함수가 합성 spine/snapshot에서 rewind 없음의 빈 출력, 여러 round note와 인용 보존, 반복 표시/인용 dedupe, retryable 대상 한정, aborted·사유 없음·snapshot 없음의 무출력, 빈 spine 거절을 검사한다. `actor='human'`도 fixture 문자열이다. main에서만 MS.MILESTONE_DIR를 복원한다.

SUT `scripts/cli/milestone_feedback.py:74–181`은 applied 이벤트의 retryable IDs를 신뢰하고 해당 gen의 마지막 snapshot만 읽는다. `_notes_by_gen`은 result나 actor를 확인하지 않고 마지막 비어 있지 않은 note를 택한다. 따라서 문서의 사람이 fail 준 항목이라는 의미는 upstream writer 계약에 의존한다. missing snapshot이 정상 무출력과 같게 흡수되는 경로도 시험이 의도적으로 수용한다. `commands/harness-milestone.md:50–64,131–148`의 executor prompt 연결은 에이전트 지시이며 실제 재작업 개선율은 미측정이다. Zeus CS→이슈→재설계 자산 후보이지만 누락 상태를 보존해야 한다.

<a id="i16"></a>
## test_milestone_gate.py

6개 함수와 MG._self_check 호출이다. axis 부재/마지막 timestamp/fallback/future since_ts, 3×4×4×2=96개 조합의 action 도메인, 예산 cap을 검사한다. 유한 96조합을 모든 입력의 전수 성질이라고 확장하지 않는다. write helper는 log_axis_event의 bool 반환을 확인하지 않으며 main의 마지막 임시 evaluator 디렉터리 존재 검사로 격리의 일부를 확인한다. main에서만 P.STATE_DIR를 패치한다.

현재 `scripts/lib/axis_scores_log.py:57–166`은 read 경로에 mkdir가 없고 state_dir()는 CLAUDE_STATE_DIR env가 P.STATE_DIR patch보다 우선이다. 과거 주석의 직접상수 읽기/읽기 mkdir를 현행 결함으로 세지 않는다. `milestone_gate:193–225,278–406`은 None/fallback/unknown verdict를 다루지만 completeness는 bool로 변환하고 phase_degraded_codes에서는 검사하지 않는다. evaluate_closure는 존재하는 verdict 값의 허용 enum을 별도로 확인하지 않는다. CLI choices/정상 writer에 의존하는 부분이며 손상된 dict와 실제 사람이 전체 시나리오를 본 사실은 이 시험 밖이다.

<a id="i17"></a>
## test_milestone_liveness.py

10개 함수가 합성 event 시간으로 machine/human/rewind/next-round 지연, closed, abandoned, UTC parse, ts 불명→mtime, scan 전후 spine bytes를 검사한다. mtime fallback은 현행 방어다. read-only 시험은 기존 spine 텍스트만 비교하므로 다른 디렉터리나 telemetry 쓰기 전체를 감시하지 않는다. mock subclass가 events의 ts를 지우며 실제 파일 손상을 재현하지 않는다.

SUT `scripts/lib/milestone_liveness.py:49–69,105–241`은 마지막 closure와 마지막 checklist, gen별 연결 수를 사용한다. 읽을 수 없는 milestone ValueError/OSError는 scan에서 건너뛰어 알림 분모에서 빠질 수 있다. EventStore.replay 58–100은 중간 손상을 telemetry로 알리지만, 마지막 깨진 줄은 조용히 제외한다. 오래된 STALLED가 ABANDONED로 바뀌는 것이 해결됨은 아니다. Zeus CS 모니터링에서는 미관측·유기·운영상 종결과 서비스 정상화를 분리해야 한다.

<a id="i18"></a>
## test_milestone_materials.py

13개 함수와 MM._self_check 호출이다. 실제 temp Git 커밋/범위/diff, planning frontmatter/AC, untracked, 빈 구간·nonrepo/badrev, 한글 경로, diff body·cap, 구조적 자료 누락, unseen 파일과 동적 diff cap을 시험하도록 작성돼 있다. 이름의 binary_and_unicode는 한글 텍스트 fixture이며 binary 파일은 만들지 않는다. self-check 내부 파싱 전체는 미독이다. Git subprocess는 timeout/환경 격리 없이 사용자 Git 설정을 상속하며 fixture는 gpgsign만 끈다.

직접 `scripts/lib/milestone_materials.py:182–288,308–344,383–434,437–480`은 Git 범위의 변경 목록과 현재 작업트리 PLAN/SUMMARY를 결합한다. 문서 read_text에는 OSError를 포괄하는 외부 try가 없어 모든 hostile input에서 예외가 없다는 문구보다 시험 범위가 좁다. diff_text/artifact_text의 cap은 호출 시점 상수지만 tier2_view의 default는 함수 정의 시점 상수다. 상수 변경 시험은 artifact 크기만 비교해서 실제 전달 자료와 보고 view의 동일성까지 잠그지 않는다. files_seen은 diff 헤더 기준이며 본문 전문 읽음이 아니다. Zeus spec→scenario→E2E에서는 AC 텍스트 추출·자료 표시와 실제 시험 관측/승인 identity를 별도로 결속해야 한다.

<a id="i19"></a>
## test_milestone_rewind.py

13개 함수가 temp Git과 STEP(--no-tier2)/VD를 연결하고 missing verdict·no retry·budget·dirty·known-good 범위·revert 이후 파일을 검사한다. 합성 승인과 직접 gate 이벤트를 쓴다. retryable fail의 실제 revert 시험 142–144와 pre-milestone 보존 시험 174–175는 retryable이 없으면 단순 return하여 main이 성공으로 센다. dirty 시험도 no_retryable을 허용한다. 다만 별도의 known-good 네 시험은 실제 retryable fixture를 만들어 결과를 요구하므로 전체 되감기 경로가 전부 무검사라고 주장하지 않는다.

SUT `scripts/cli/milestone_rewind.py:72–107,118–267`은 known-good 실재/HEAD 조상/시작점 후손 방어가 있다. ms_sid의 저장된 repo와 CLI repo 동일성 검사는 읽은 main에 없고, --base-rev는 override로 우선한다. 멱등 가드는 이벤트에 commit 문자열이 있는지만 보고 Git 실재를 재검증하지 않으며 fixture도 cafe123을 직접 심는다. Git revert/commit 후 applied와 next-gen append는 별도 단계여서 그 사이 crash 원자성은 미검증이다. dry-run·conflict·commit 실패 복구·다른 repo·병합 커밋은 이 primary의 직접 시험 밖이다. Zeus PG 시도/예산과 Git commit 효과의 복구 일관성 및 사람이 허용한 되돌림 범위를 별도 검증해야 한다.

<a id="i20"></a>
## test_milestone_spine.py

12개 함수와 MS._self_check 호출이다. append prefix 보존, debates 경로명 불변, gen별 gate/rewind, cross-gen 합성 verdict, 같은 checklist의 mtime, known-good의 fail/blocked/옛 event/여러 snapshot 연결을 검사한다. `does_not_touch_debates`는 경로 문자열·전역 basename만 검사하며 모든 쓰기 감시는 아니다. snapshot mtime은 external corruption·collision·동시 쓰기를 잠그지 않는다.

SUT `scripts/lib/milestone_spine.py:38–58,110–152,169–191,212–355`는 event vocab만 검사하고 actor/payload 승인 실재를 인증하지 않는다. checklist SHA1 12자는 생성 파일명에 쓰지만 read_checklist가 내용을 재해시하지 않는다. human_verdicts는 actor를 보지 않고 ID별 tail-wins다. known_good_rev는 존재하는 non-pass verdict의 phase만 제외하므로 아예 판정이 없는 항목까지 pass를 요구하는 계약은 아니다. latest checkpoint ≠ human-verified artifact라는 경계가 남는다. Zeus에는 PG 권한/증거 snapshot/Git revision을 결속한 상태 전이로 옮길 후보이며 append-only 파일만으로 정본 무결성이 완성됐다고 하지 않는다.

<a id="i21"></a>
## test_milestone_step.py

15개 함수는 temp Git에서 Tier2를 항상 끄고 handoff/continue/fail-closed, 명령의 합성 exit·출력, 0건/8건/unknown 표시, config·spine·round·nonrepo·probe 부재·sanitizer를 검사한다. `8 passed`를 출력하는 Python은 실제 8개 시험이 아니다. `--no-tier2`는 Tier1/probe/mutation까지 끄는 전체 dry-run이 아니다. 현재 fixture들은 --open→executor 커밋→step의 전체 정상 수명주기를 검증하지 않는다. 실제 evaluator 호출/Alpha/Live/UI는 없다.

직접 `scripts/cli/milestone_step.py:103–133,220–627`의 원장 명시 구간에서 `_run_tier1`은 shlex.split과 shell=False, UTF8 replace, 종료코드와 마지막 합친600자를 기록한다. PowerShell/WSL/bash 동등 quoting·프로세스트리 종료·도구 자체 분모는 미검증이다. mutation은 성공 Tier1과 변경 Python 후보에 따라 별도로 실행되는 연결이며 그 구현 전문은 미독이다. 0건·silent·probe 미실행·자료 부족을 blocking으로 표시하는 현행 방어는 존재한다.

현재 step 575–580은 outcomes=[현재 outcome]만 gate에 전달한다. gate 356–360은 planned 중 outcome이 없는 첫 phase를 다음으로 택하므로 planned=1,2에서 step1→2 뒤 step2→1로 돌아갈 정적 조건이 있다. test_incomplete_roadmap은 첫 호출만 검사한다. 또한 checklist에는 현재 items만 들어가고 assemble 600–601에 reexec_phase_ids가 없어 같은 source/ref/phase의 이전 pass가 이월된다. 종결 소비는 마지막 snapshot만 보므로 앞 phase의 별도 blocking 항목이 최종 분모에서 빠질 조건도 확인해야 한다. 이번 원본 실행 0이며 실제 관측이나 채택 판정으로 과장하지 않는다.

<a id="i22"></a>
## test_milestone_verdict.py

13개 함수는 STEP(--no-tier2)에서 만든 실제 fixture snapshot을 써 unknown/짧은 prefix/부분 batch 입력 거절, all-pass·fail·blocked·note·budget override·append·list/close 분기를 검사한다. 합성 set CLI 호출이 사람 검토를 대체한다. 부분 batch all-or-nothing은 입력 사전 검증만 시험하며 append 도중 I/O 실패나 concurrent writer의 transaction을 시험하지 않는다. main에서만 MS/P.STATE_DIR를 복원한다.

SUT `scripts/cli/milestone_verdict.py:85–114,151–227`은 blocked note를 8자·문자 포함으로 검사하고 set 이벤트에 actor='human'을 하드코딩한다. pass note는 의무가 없다. close는 최신 checklist의 blocking IDs, 누적 ID verdict, 이벤트 수 또는 --rewind-exhausted override를 읽는다. degraded closed도 rc0이다. 따라서 rc0 또는 human 문자열로 실제 인수/배포 승인을 판단할 수 없다. 앞 phase/재실행/근거 변경·승인자 인증·PG 원자성 시험은 추가로 필요하다.

<a id="i23"></a>
## test_mirror_drift.py

0개 test_ 함수이며 main 안의 `_check` 분모로 Rust fixture의 regenerate/fingerprint, 주석·들여쓰기·본문·문자열 // 변화, marker 없음, narrative, extractor fallback, fast path, subdir, invalid dict를 검사한다. 기대 fingerprint를 같은 compute_fingerprint 구현으로 재계산하므로 독립 oracle은 아니다. `_PASS/_FAIL`을 main 시작에 reset하지 않아 재호출 시 누적되며 `_check` 실패는 예외를 던지지 않는다. 중간 예외면 마지막 cleanup에 도달하지 못한다. Git 부재는 `[SKIP]`와 rc0이므로 `[SKIP-SUITE]`만 구분하는 run_units에서는 모듈 PASS로 세어질 조건이 있다. Node wrapper의 현행 skip 방어와 구별한다.

`scripts/lib/mirror_drift.py:45–89,113–225,256–284`, mirror_extractors의 원장 지정 구간에서 malformed JSON/빈 dict/포괄 예외는 inert로 돌아가고 status_line은 침묵한다. 정상 dict의 일부 invalid는 표시하는 현행 방어가 있다. normalize는 문자열 내부의 공백도 합치므로 문자 그대로 의미 있는 공백 변화는 fixture의 // 방어로 입증되지 않는다. hash는 경로명이 아닌 정렬된 내용들을 연결하므로 같은 내용 rename의 민감도도 제한된다. dirty 상태 regenerate는 현재 파일로 fingerprint를 만들면서 HEAD를 적고, 이후 같은 HEAD의 clean tree면 재해시 없이 clean을 반환하는 조건을 정적으로 도출했다. 그 전환은 primary에서 시험하지 않는다. `handlers/session/init.py:392–403`에 status_line 연결은 있지만 실제 notification 전달은 미관측이다. Zeus Git/spec drift를 인수 승인 자체로 삼지 않고 변경 후보와 검토 필요 신호로 사용할 대상이다.

<a id="trace"></a>
## 실행 분모·지원 추적

모든 primary 전문 범위와 raw identity는 files.json, 지원의 정확한 실제 독해 범위는 supporting-evidence.json에 있다. grep/AST 위치 발견만 한 구간은 의미 독해로 계상하지 않는다. primary의 test_ 함수 정의 수와 main의 branch/내부 self-check/Node의 시험 수는 서로 다른 분모다. 이 보고서의 0개 test_ wrapper도 본문 전문 검토에서는 한 파일이다.

`scripts/tests/run_units.py:39–194,217–311,314–403`을 새로 읽었다. 현재 unit은 subprocess 또는 특정 fixture 이름 regex로 pytest를 선택한다. main-only에서 conftest autouse는 작동하지 않는다. rc0/stdout marker 조합을 쓰며 일반 `[SKIP]`는 skipped가 아니다. pytest 출력에 `No module named pytest`가 있으면 실제 원인과 무관하게 -1로 바꾸는 문자열 경로는 존재하지만 이번에 실행하지 않았다. Windows junction/POSIX symlink 경로는 현재 구현되어 있으나 필수 asset 링크 실패는 무격리 계속이고, 전달 환경은 CLAUDE_HOME만 override하여 inherited STATE/TELEMETRY 경로가 남는다. 링크가 OS 쓰기 금지 sandbox인 것도 아니다. 두 OS 동작 검증을 주장하지 않는다.

`scripts/tests/conftest.py:1–83`은 pytest마다 CLAUDE_HOME과 L1 writer whitelist/cache를 변경하며 P.STATE_DIR·MS.MILESTONE_DIR·CLAUDE_STATE_DIR 모두를 원복하지 않는다. `scripts/lib/paths.py:12–19,79–141`의 현재 env 우선순위를 반영해, module patch 기반 test_milestone_gate는 inherited STATE_DIR 환경과 별도 대조가 필요하다. read_axis_events의 과거 mkdir 결함은 수정된 현재 코드와 구분했다.

`scripts/tests/run_all.py:166–188,207–258`은 validator test main 반환과 stdout을 소비한다. 전체 entry/import/reexec는 이번 미독이다. parent의 별도 실제 runner 관측을 이번 실행 분모로 합산하지 않았다. `commands/harness-milestone.md`와 `harness-debate.md`의 읽은 구간은 에이전트 실행 지시 연결이고 프로그램 강제/사람 승인 증명은 아니다. 모델과 디바이스를 호출하지 않았다.

<a id="zeus"></a>
## 사용자 요구와 Zeus 대응

| SDD 단계 | 이번 자산에서 얻는 후보 | 추가로 필요한 검증 |
|---|---|---|
| 1. 스펙 논의 | AC/결정 기록, 반대 의견, item 추적 | 실제 사용자 핵심 시나리오와 승인된 범위 |
| 2. 디자인 분석 | 논리 설계 구조·변경 자료 표시 | 인터랙션·토큰·Storybook·접근성의 실제 검토 |
| 3. 코드 작성 | alias/localization과 Git 병합 경험 | 연결 자산·상대경로·인가·실제 컴포넌트 동작 |
| 4. 자체 검증 | fixture oracle, skipped/unknown, 자료 분모, 변이 연결 | 독립 오라클과 실제 도구 receipts, Windows/Linux/WSL |
| 5. 알파 배포 | milestone handoff/자료 수집 | 배포 환경·버전·헬스·롤백 증적 |
| 6. QA 및 증적 | deferred 포함 checklist, verdict·feedback 이력 | 실제 사람, scenario/spec/commit/attempt 결속, 재승인 |
| 7. 라이브 배포 | Git known-good/revert의 일부 회귀 | 실제 승인/점진 배포/금전 흐름/복구 원자성 |
| 8. CS 대응 | liveness·drift·L1→L2·압축 | 누락 알림, 고유 증거·철회·이슈와 개선 효과 |

이 대응은 사용자 요구와의 설계 비교다. 이번 범위에서 Zeus src/PG 구현을 새로 독해하거나 등가를 검증하지 않았다. Git은 선언/소스 revision, PG는 런타임 시도·승인·근거·전이 정본으로 사용하려는 목표에 비추어, JSONL actor 문자열·내용주소 파일명·그린 stdout을 승인 권위로 받아들이지 않는 연결이 필요하다. 로컬 티켓/GitHub Issues로 결함과 검수 토픽을 연결할 수 있으나 이 작업은 티켓을 변경하지 않았다.

Astra 설계/최종 검증, Sol 중요 구현, Terra 단순 구현은 반복 성공 횟수나 confidence 공식으로 자격을 얻는 것이 아니다. 동일 시나리오와 고정 환경에서 guardrail의 검출·실패·복구 증거를 단계별로 쌓아야 한다. 삼성 휴대폰/태블릿 실기기·Device Farm SDK/MCP·live interact·Replay는 유예 상태이며 구현했다고 주장하지 않는다. mock/합성 승인은 실제 사용자 인수 분모에 넣지 않는다.

<a id="unknowns"></a>
## 남은 경계

23개 primary 전문 독해만 완료했다. 전체 호출 closure, Node mergeOneWorktree/나머지 scenario, milestone 내부 self-check 전문, L1/atomic/cache/token/cron scheduler 구현, provider/평가 자격과 자동 prompt 전달, notification 수신, concurrent/중단 복구, source license와 공개 재사용 범위는 미완료다. 동일 snapshot 기존 승인 이월·다중 phase 진행·마지막 checklist·L2 edge 중복·mirror dirty baseline 후보는 별도 독립 검토와 재현 설계가 필요하다. 이번 작업은 그러한 probe를 실행하지 않았다.

자체 검증은 기록기 Ruff, UTF-8/LF 및 한국어 본문 readback, raw blob/bytes/SHA, 범위 상한과 실존 anchor, 산출물 해시만 대상으로 한다. 이것은 원본 시험 PASS가 아니다. actual Claude/OS/model/human/license/adoption은 false를 유지한다. 원본·runtime·src/tests·전역 coverage·티켓·commit/push를 변경하지 않았다.
