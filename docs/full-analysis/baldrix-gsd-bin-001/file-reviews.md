# 파일별 독립 정적 검토

<a id="file-01"></a>
## get-shit-done/bin/gsd-tools.cjs

1–1055 전문 fresh read(a0e95f,624425,669c63,db29b4). CommonJS main이 import 즉시 실행되며 core/state/phase/verify/config/template/milestone/commands/init/frontmatter/profile/workstream/docs/learnings를 eager require한다. help/version도 거부하므로 도움말 조회가 inert하다고 가정할 수 없다. cwd 존재/디렉터리 검사와 ws 문자 제한은 유지 후보지만 cwd는 임의 절대경로를 허용하고 worktree root→project root 자동 변경으로 의도한 격리 경계를 벗어날 수 있다. ws를 project root 이동 전에 결정하고 env에 저장하는 순서, intel의 직접 `.planning` 경로는 workstream 정본과 불일치 가능성이 있다.

parseNamedArgs는 첫 flag만 읽고 다음 --값은 null, 숫자 parseInt/NaN·중복/알 수 없는 flag의 공통 schema 검증이 없다. NEVER_VALID_FLAGS는 안전 오작동 일부를 막지만 command 값이 --help인 경우도 거부하며 다른 unknown flag는 mutation 앞에서 일반 차단하지 않는다. state 알 수 없는 subcommand는 load로 fallback한다. --pick는 fs.writeSync stdout만 가로채고 @file을 읽어 JSON을 파싱하며 실패하면 원래 문자열을 그대로 낸다. null/undefined는 빈 문자열, object는 String 객체 출력으로 손실되고 inherited property 접근도 가능해 신뢰할 수 있는 typed accessor가 아니다. --raw와 함께 쓰면 scalar JSON 해석 차이가 생긴다.

commit는 --files 이후 모든 nonflag token을 파일로 묶어 다른 flag의 값까지 포함할 수 있고 mutation권한/approved revision을 검사하지 않는다. requirements mark-complete, phase complete/remove-force, validate repair, milestones archive, learnings prune/delete, global profile, intel snapshot/patch가 모두 같은 무권한 router에서 연결된다. verify 명령은 검증기 호출이지 실제 사람 인수가 아니다. source argv 경로·프로파일링/live 세션 수집은 이 검토에서 실행하지 않았다. Zeus는 CLI를 use-case adapter로 유지하되 Git 정의와 PG runtime lease/승인 guard를 분리하고 exact argv·source/target revision·실제 실패/skip·핵심 사람 시나리오를 결속해야 한다. 본 파일 전문 완료와 eager/lazy 의존 전체 closure는 다르며 직접 지원 외 모듈·OS·모델·라이선스·인수는 미완료다.

<a id="file-02"></a>
## get-shit-done/bin/lib/__tests__/merge-back.test.cjs

1–444 전문 fresh read(db29b4,511f49). node:test13개 사례가 각각 temp Git repo와 worktree를 만들고 실제 CLI subprocess를 호출하도록 작성되었다. FF/nonFF/여러codecommit/전체artifact/REVIEW없음/foreign planning복원/same-dir junk/detached/conflict/multiple worker/STATE drift/CRLF/no-worker를 검사한다. 원문이 실제 Git 테스트라고 설명해도 이번 실행은0이며 과거 debate 승인·4번 시뮬레이션 실패 주장은 원시 증거 미확인이다.

유지할 oracle은 blob 내용 비교·executor code SHA와 SUMMARY tip 구분·conflict 뒤 원래 HEAD/clean tree/worktree 보존·CRLF시 불필요 reconcile 없음이다. 그러나 몇 사례는 exit code를 검사하지 않고 JSON merged만 보며 실제 conflict도 exit0를 의도한다. --full artifact는 비어 있거나 짧은 marker파일이라 기능·검수 내용은 인수하지 않는다. missing REVIEW를 허용하는 사례도 검수 완료 증거가 아니다. multi-worktree는 모두 clean이고 부분 성공+뒤 conflict의 aggregate 의미, 잘못된 base/dirty main/활성 worker·동시 mutation·악성 path·reconcile 실패·권한·huge출력은 미검사다.

spawnSync timeout/maxBuffer/격리 env가 없고 Git global config/hooks·기본 branch명·Node PATH를 상속한다. init main을 강제하지 않아 main 표현은 가정이다. makeBase/addWorktree가 t.after 등록 전에 실패하면 teardown이 등록되지 않아 leak 가능하고 teardown의 worktree remove/prune 실패는 checkfalse/예외 삼킴으로 최종 rmRetry만 남는다. Windows retry는150ms×6 제한이나 실제 OS 검증은 아니다. Zeus는 이 사례들을 격리된 Git 통합시험 후보로만 변형하고 소스 수정·실행·사람 인수 및 qualified reviewer 영수증과 구분한다. 직접 SUT와 workflow caller 추적은 supporting에 기록하며 전체 closure/채택은 미완료다.
<a id="file-03"></a>
## get-shit-done/bin/lib/commands.cjs

1–1013 전문 fresh read(78be00,ce2e07,f1042c,6ac2aa). slug/time/todo/path/history/model/commit/subrepo/summary/websearch/progress/scaffold/stats/commitguard를 모은다. 진행 상태는 SUMMARY 수가 PLAN 이상이고 첫 VERIFICATION 파일 본문 어디든 status:passed가 있으면 Complete다. YAML frontmatter·정확 plan매칭·revision·증거·사람 인수는 검사하지 않는다. read failure/손상 summary는 silent skip되어 분모가 축소되고 progress는100% cap으로 orphan summary를 감춘다. stats와 progress의 milestone/custom phase 필터도 다르며 requirements는 특정 체크박스 형식만 센다. history는 milestone 경계를 phaseNum 키에 보존하지 않아 같은 번호가 합쳐지고 앞서 부분 반영된 malformed summary도 남을 수 있다.

commit의 sanitizeForPrompt는 승인이나 Git 옵션/path 제한이 아니다. commit_docs/ignore이면 source 파일도 skip, checkout fallback/stage 실패를 강제하지 않고 전체 index를 commit하며 real error도 nothing_to_commit/raw nothing으로 정상 반환한다. cmdCheckCommit는 strictfalse만 막아 falsy config 처리와 다르고 Git diff 실패는 allow다. core.error가 process.exit1이므로 이 호출 자체가 catch에 삼켜진다고 주장하지 않는다. subrepo는 첫 prefix 매칭·미매칭 경고·각 repo stage결과 무시·some(success)를 top committed로 합쳐 부분 실패를 전체 성공처럼 읽기 쉽다. full SHA·atomic multi-repo rollback·stale base·권한 검증이 없다.

verify-path-exists 주석은 traversal 검증을 주장하지만 NUL만 거절하고 absolute/../symlink 접근을 허용한다. todo complete는 임의 filename join→write후unlink로 경계/원자성/overwrite 방어가 없다. scaffold는 exists후write라 경쟁 overwrite, phase-dir는 이미 있어도 createdtrue이며 name을 template/YAML에 escape하지 않는다. ASCII slug60과 timestamp초 단위는 충돌·한국어 소실을 보존해야 한다. todo relevance는 ASCII·본문200자·중복 keyword 점수·substring 파일 유사도다. core의 found:true 반환을 직접 읽어 findPhaseInternal.found 조건은 유효함을 확인했다. Brave검색은 env key만 사용하고 limit||10·영어/US고정·timeout/출력 bound 없음·오류 raw빈문자라 전체 원문 조사와 다르다. Zeus에서는 파생 진척과 PG 실제 완료/검수/사람 인수를 분리하고 Git definition pin·scope·lease·실패분모를 강제하는 use-case로 변형해야 한다. 원본 실행/네트워크/운영 쓰기0, 전체 의존·시험·라이선스·OS·채택 미완료다.

<a id="file-04"></a>
## get-shit-done/bin/lib/config.cjs

1–471 전문 fresh read(6ac2aa,6f8cab). new/ensure/set/get/profile명령과 settings key whitelist를 정의한다. 알려진 typo 제안·새 config exists시 미덮어쓰기·context enum은 유지 후보지만 대부분 키의 type/range/enum 검증이 없다. 일반 config-set model_profile은 임의값을 저장하고 특수 set-model-profile은 VALID_PROFILES로 제한한다. features/agent_skills의 dynamic key는 실제 feature/agent 존재·모델 자격을 증명하지 않는다. undefined값을 지정하면 JSON serialization에서 속성이 사라지고 malformedJSON 배열/객체 입력은 문자열로 보존된다. context_window/resolve_model_ids는 whitelist에 없지만 core에서 소비하는 설정이다.

buildNewProjectConfig는 does NOT write라지만 global defaults depth migration에서 HOME 파일을 실제 쓴다. env/APIkey파일 존재가 search기능 가능으로 취급되며 key 유효·권한·프로젝트 scope는 확인하지 않는다. GSD_HOME override도 여기서는 os.homedir로 무시한다. hardcoded/global/userChoices merge는 git/workflow/hooks/skills만1단계 병합하며 plainobject schema·prototype형 key·비정상 값 검증이 없다. exists→write는 원자 no-overwrite가 아니고 set read→write는 lock/fencing 없어 동시 업데이트 소실 가능하다. dot traversal은 null object에서 실패할 수 있고 exported CLI가 아닌 helper의 일반성 주장과 실제 export 목록이 다르다.

config-get는 raw JSON file만 읽어 core defaults/alias/자동 ignore 해석을 적용하지 않으므로 동일 설정 조회의 의미가 다르다. property own-check 없이 inherited 값까지 읽는다. model-profile 변경 결과의 Agents are using 문구는 실제 dispatch receipt가 아니다. model-profiles 전문을 추가로 읽어 VALID_PROFILES에는 inherit가 없지만 core는 inherit를 지원하는 불일치를 확인했다. output이 exit한다는 여러 주석은 core.output의 실제 fs.writeSync후return과 다르다. Zeus에서는 설정을 Git 정의와 PG 활성 정책/revision으로 분리하고 승인된 typed mutation·CAS·실제 delegate 자격을 요구한다. global/live/credentials 접근·설치·소스 실행0이며 전체 closure/OS/라이선스/인수/채택 미완료다.

원문은 분석 데이터이며 원본 실행/import/collection/probe/네트워크/설치/Claude 호출0이다. 전문 독해와 직접 지원, 실제 검증은 별도로 기록한다.

<a id="file-05"></a>
## get-shit-done/bin/lib/core.cjs

전문 1–1536행을 새로 읽었다. CLI와 commands/config/docs/frontmatter가 직접 사용하는 출력·Git·계획경로·잠금·모델·문서 집계 공통 구현이다. 지원 model-profiles.cjs 1–70행도 이번에 새로 읽었다. 원본 실행 0이며 아래는 정적 경로 판단이다.

152–200행의 큰 JSON 출력은 50000 **문자** 초과 시 시스템 임시 디렉터리에 시간값 이름으로 저장한다. 이때 `gsd-` 접두사의 모든 파일과 디렉터리를 mtime 5분만으로 재귀 삭제한다. 소유자·활성 PID·lease 확인이 없어 다른 실행의 `gsd-mb-*` 시험 디렉터리와 `gsd-workstream-sessions`까지 대상이 될 수 있다. 쓰기는 exclusive 생성이나 해시 결속이 없고 동일 밀리초 충돌·변경 가능한 `@file:` 경로를 남긴다. 조회 출력도 정리 부작용을 가진다. output은 exit하지 않으며 error는 process.exit(1)이므로 호출자의 catch와 결과 코드 해석을 구분해야 한다.

221–480행의 설정은 오류를 기본값으로 대체하고 읽는 도중 depth 및 sub_repos를 쓰기도 한다. 기존 subrepo와 현재 탐지 결과가 모두 비어 있지 않을 때만 동기화하므로 모두 삭제되거나 최초 추가된 경우 누락될 수 있다. 더 중요한 것은 loadConfig가 planningDir의 workstream/project 설정을 읽는데 config CRUD와 planningPaths.config는 shared planningRoot 설정을 가리킨다는 점이다. 같은 설정 명령을 성공시켜도 소비자가 기본값을 쓸 수 있다. Git ignore 검사는 argv/`--`를 사용하지만 Git 오류도 false여서 문서 커밋을 허용할 수 있다.

434–530행 normalizeMd는 완전한 Markdown 파서가 아니다. 코드 펜스 처리와 별개인 제목/목록 공백 삽입, 전역 연속 개행 축소는 코드·YAML scalar 본문도 바꿀 수 있다. 531–542행 Git 실행은 argv로 shell 해석을 피하지만 timeout/출력 한계/환경·hook 격리를 지정하지 않고 spawn error 상세를 반환하지 않으며 stdout/stderr를 trim한다. 548–578행 root 탐지는 `.git`의 배치를 가정하고 `.planning`의 디렉터리 여부를 일부 경로에서 확인하지 않는다.

583–628행 잠금은 `wx` 생성이라는 유용한 방어가 있지만 30초 mtime만으로 활성 lock을 지울 수 있고, 10초 대기 뒤에는 lock을 지운 후 **재취득 없이 fn을 실행**한다. owner PID는 확인하지 않는다. fn이 EEXIST를 던지면 바깥 catch가 잠금 충돌로 처리하여 fn을 재실행할 수 있고 Promise 반환이면 작업이 끝나기 전에 finally로 해제된다. 소유권 결속 없는 unlink는 다른 실행의 lock도 지울 수 있다. Zeus에서는 PG 트랜잭션/lease 소유권과 실패 종료가 필요하며 이 잠금을 승인 방어로 흡수하면 안 된다.

648–872행 경로와 세션은 separator 및 `..` 일부 거부, canonical root 해시, stable session key를 제공한다. 다만 OS 예약 이름·환경값의 권한은 검증하지 않으며 ASCII 치환/160자 절단 키 충돌, 프로젝트와 workstream 경로의 상이한 기준, 세션 포인터 읽기 중 삭제 및 비원자적 쓰기가 남는다. 안정 키가 있으면 포인터가 없을 때 legacy fallback을 하지 않는다. 873–1072행 phase 탐색은 PLAN/SUMMARY ID 집합을 대조하고 found:true를 반환하므로 commands의 `.found` 사용은 맞다. 내용 검증은 아니며 custom 이름 정규화 충돌, archived milestone의 문자열 역순, shared archive 경로, 읽기 실패→null/빈 목록 때문에 누락을 숨길 수 있다.

1082–1185행 현재 milestone 추출은 STATE의 본문 어디든 milestone 줄을 사용하고 version 경계가 엄밀하지 않다. 선택 section 이전 내용도 details만 제거한 채 포함하여 이전 milestone이 남을 수 있다. 쓰기 함수는 같은 선택 로직이 아니라 마지막 소문자 `</details>` 이후만 바꿔 읽기/쓰기 범위가 불일치한다. 1253–1287행 agent 설치는 .md/.agent.md 경로 존재만 확인하므로 내용·실행 가능성·모델 자격을 증명하지 않는다. 모델 표의 실제 키는 kha-*라 gsd→kha 주석은 낡았지만 해당 replace는 현재 키를 그대로 둔다. 1303–1333행 override는 타입 검증 없이 그대로, omit은 빈 문자열, 알 수 없는 agent는 sonnet으로 반환하여 ID 변환 분기도 건너뛴다. inherit 지원은 dedicated config의 VALID_PROFILES와 다르다. 모델명 문자열은 위임 자격 증거가 아니다.

1336–1536행 요약 추출은 LF 전제인 부분이 있고, pathExists는 cwd 외부도 허용한다. milestone 파싱 실패는 v1.0/milestone 또는 pass-all 필터로 바뀐다. custom phase 필터의 greedy 이름 캡처는 설명 suffix까지 포함해 정상 phase를 제외할 수 있다. 파일 통계는 파일명 목록과 존재만 보고 완료를 판단하지 못한다. Zeus의 8단계 SDD에는 요구 ID·정본 revision·분모·실제 검사 영수증·사람 핵심 시나리오를 별개로 저장하고, Git 정의/PG runtime 간 경로와 상태 권위를 통일해야 한다. 전체 호출자·잠금 경쟁·native OS·실제 모델·인수·라이선스·채택은 미완료다.

<a id="file-06"></a>
## get-shit-done/bin/lib/docs.cjs

전문 1–267행 fresh 독해. CLI docs-init와 docs-update.md 1–65행이 직접 호출한다. cmdDocsInit는 core 설정/모델/설치 검사와 프로젝트의 Markdown·tooling·workspace 신호를 모아 JSON으로 출력한다. 실제 문서 생성이나 검증 실행은 하지 않는다. core.output 및 loadConfig를 통해 큰 출력 정리와 설정 migration 쓰기 부작용은 상속한다.

32–42행 marker 검사는 시작 500바이트 **안에 포함**되면 true여서 'begins with' 주석보다 넓다. 읽기 오류 시 fd close가 finally가 아니어서 누수 가능성이 있으며 false는 무표식과 오류를 구별하지 않는다. 51–111행은 root Markdown와 docs 4단계만, 소문자 변환 확장자만 대상으로 하며 디렉터리 내부 symlink는 Dirent 조건으로 따라가지 않는다. docs 경로가 파일이거나 읽기 불가라도 stat이 성공하면 documentation/doc fallback은 하지 않는다. 빈 결과는 전체 문서 없음의 증거가 아니다.

120–193행 has_tests는 디렉터리나 devDependency 이름 존재이고 is_open_source는 LICENSE 파일 존재뿐이다. 실행 가능한 시험·유효 라이선스·실제 API/배포·toolchain 인수가 아니다. monorepo는 package.workspaces 객체 형식을 놓치며 workspace 추출은 pnpm YAML의 모든 list 줄을 읽어 packages 이외 항목도 포함한다. 203–233행은 glob의 실제 해석이나 경로 안전성을 확인하지 않고 첫 비어 있지 않은 형식을 반환한다. 248–264행 agent 설치 신호는 doc writer/verifier 둘만의 준비 상태가 아니라 표 전체 파일 존재 결과다. model-profiles.cjs 25–26행을 통해 kha-doc-writer 키는 실제로 존재함을 확인했다.

Zeus 적용 후보는 범위와 제외/오류를 명시한 문서 inventory다. marker만으로 덮어쓰기 권한을 부여하면 안 되며 Git 정의와 PG 작업 상태, 실제 변경 diff·원본 해시·사람 승인 경계를 결속해야 한다. 문서의 문장 정확성은 별도 오라클과 실제 시나리오로 검사한다. 테스트 직접 구현은 이 bounded 검색에서 확인하지 못했고 전체 부재를 뜻하지 않는다. 원본 실행·OS·모델·라이선스·인수·채택 0/미완료다.

<a id="file-07"></a>
## get-shit-done/bin/lib/frontmatter.cjs

전문 1–381행 fresh 독해. CLI frontmatter 명령과 commands의 요약 소비, verify.cjs 283–390행의 must_haves 소비를 직접 연결했다. 범용 YAML 라이브러리가 아니라 정규식·indent stack의 제한 파서이며 CRUD는 cwd 바깥 절대/상대 경로에도 쓰기가 가능하다. NUL 거부는 일부 get/set에만 있고 traversal guard라는 주석과 달리 경로 권한 방어는 아니다.

15–40행 inline array는 인용부호를 지우며 escape/doubled quote·빈 문자열을 보존하지 않는다. 43–119행은 시작 블록만이라는 주석과 달리 본문 전체 `---` 블록 중 **마지막** 것을 선택한다. fenced 예시나 뒤쪽 다른 블록이 정본을 덮어쓸 수 있다. scalar는 문자열이며 boolean/null/숫자·주석·multiline·nested array object 의미를 온전히 처리하지 않는다. 일반 객체에 `__proto__` 같은 key를 대입하며 키 제한 방어가 없다. 122–184행 serializer는 작은 문자열 배열의 쉼표/따옴표를 escape하지 않고 제한 깊이 이후 객체를 문자열화한다. null/undefined를 지우고 개행·quote도 제대로 escape하지 않아 roundtrip 의미 보존이 없다.

186–193행 splice는 **첫 시작 블록**만 교체하지만 extract는 마지막 블록을 읽는다. 복수 블록에 set/merge 성공을 반환해도 다음 read가 뒤쪽 옛 값을 다시 볼 수 있다. 빈 블록·BOM 처리도 다르다. normalizeMd 호출은 본문까지 변경하고 쓰기는 무잠금·비원자적이며 이전 bytes/hash 확인이 없다. 195–301행 must_haves parser는 blockName 정규식을 escape하지 않고 전체 YAML에서 일치하는 block을 찾아 실제 must_haves subtree 소속인지 위치 관계를 확인하지 않는다. 일부 형식 실패는 warning 뒤 빈 배열 반환이며 문서에 적힌 LLM 추론 fallback은 요구 누락을 허용하는 방향이다.

305–368행 validate의 분모는 plan 8, summary 6, verification 4개 **필수 키 존재**뿐이다. 빈 객체/빈 문자열·의미 없는 status/score도 존재하면 통과하고 문서 내 임의 마지막 블록으로 충족할 수 있다. missing 파일·field는 JSON error를 출력하고 정상 반환하므로 프로세스 성공과 valid를 혼동하면 안 된다. schema 조회도 own-property 확인이 없어 상속 이름 입력은 별도 예외가 가능하다. mergeData는 객체 schema 검증 없이 Object.assign하며 null·array·primitive 형태의 결과/예외를 구분하지 않는다.

직접 지원 verify.cjs 289–335행은 string artifact/path 없는 object를 skip하고 남은 results의 passed===length를 사용하므로 비어 있지 않은 원문 배열을 전부 skip하면 0/0 all_passed=true가 가능하다. 검사 내용도 min_lines/부분문자열/exports 문자열이지 실제 코드 효과가 아니다. 344–390행 key link는 string skip, regex source/target 일치나 단순 includes를 사용하며 to 누락 시 빈 문자열 포함이 true가 될 수 있다. 전체 함수 후반부는 지원 미독으로 별도 남겼다. Zeus는 canonical schema/type/ID와 전체 원문 분모를 고정하고 파싱 실패·skip을 fail-closed로 기록해야 한다. SDD 테스트 명세와 실제 영수증, 사람 핵심 시나리오, 모델 자격은 이 format validator로 대신할 수 없다. 실행·전체 closure·OS·라이선스·채택은 미완료다.
