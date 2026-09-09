# Claude 독립 정적 검토 — baldrix pinned skill-routing 런타임 6파일

원본: `cbb5c3e6c9c4af6f86626474f4d7d62fd8e8a6d2`, 경로 `.runtime/absorption/sources/baldrix/pinned/`.
실행·쓰기 없음. Read/Glob/Grep만 사용. 다른 리뷰 보고서(Codex/Claude 기존 산출물)는 열지 않았다.

---

## 1. 전문 읽은 파일과 주요 심볼

**지정 6개(전문)**

| 파일 | 주요 심볼 |
|---|---|
| `scripts/lib/skill_token_budget.py` | `MAX_CONTEXT_CHARS=4000`, `PER_BODY_CAP=3000`, `FULL_BODY_TOP_K=3`, `TRUNCATION_MARKER`, `PARTIAL_MARKER`, `MIN_FILL_CHARS=200`, `truncate_skill_content`, `fit_top_skill`, `_fill_remaining`, `apply_token_budget` |
| `scripts/lib/threshold_policy.py` | `POLICY_PATH`, `TOKEN_RISKY/TOKEN_SAFE`, `_coerce_num`, `_safe_yaml_load/_dump`, `load_policy`, `resolve_threshold`, `_ready_flag_path`, `_is_risky`, `_append_history`, `apply_threshold_override` |
| `scripts/lib/tech_stack.py` | `_LANG_BLOCKS`, `_candidate_paths`, `_parse_yaml`, `load_tech_stack`, `read_language` |
| `scripts/lib/pipeline_stage_picker.py` | `SEARCH_DIRS_REL`, `_stage_done`, `_parse_skill_list`, `detect_pipeline_skills` |
| `scripts/lib/skill_match_render.py` | `PROMPT_TOOL_ROUTING_HINTS`, `_PHASE_NAMES/_PHASE_GUIDANCE`, `build_cross_references`, `build_phase_guidance`, `detect_tool_routing_hints`, `build_sensor_reminder` |
| `scripts/handlers/prompt/skill_match.py` | `extract_paths_from_prompt`, `_user_home_dir`, `_paths_match_home`, `_resolve_project_scan_root`, `detect_project_type`, `match_skill`, `apply_token_budget`(래퍼), `collect_skill_files`, `main` |

**범위 확정을 위해 추가로 읽은 실제 의존/데이터(전문 또는 해당부)**
`lib/skill_score.py`(전문), `lib/frontmatter.py`(전문), `lib/pipeline_yaml.py`(전문), `lib/pipeline_overlay.py`(전문), `lib/calibration/threshold_registry.py`(전문), `lib/project_paths.py`(전문), `skills/_pipeline/stages.yaml`(헤더+`output/skills/optional` 전량 grep), `skills/_pipeline/stages.core.yaml`(선두 70줄), `overlays/*.yaml`(키 grep), `tests/test_skill_token_budget.py`(전문), `tests/{test_tech_stack,test_pipeline_stage_picker,test_threshold_tuning}.py`(테스트 함수명 전량).

---

## 2. 파일별 목적과 의미

1. **`skill_token_budget.py`** — 매칭된 스킬 본문을 **문자수 예산** 안에 넣는 순수 함수층. 역사적으로 두 번 수정됐다: (a) `MAX_CONTEXT_CHARS` 이중 상수(lib 8000 / 호출부 4000) 통합, (b) "1위는 예산 우회" 규격을 폐기하고 `fit_top_skill` 사다리(전문 → 레벨1 → 레벨2+잔여 채움 → 하드슬라이스) 도입. 드롭은 2위 이하에만 허용한다.
2. **`threshold_policy.py`** — 등록된 tunable 임계값의 config 오버라이드 해석기 + 토큰 게이트 기록기. `resolve_threshold`는 fail-soft 읽기, `apply_threshold_override`는 방향(risky/safe)별 토큰 + risky일 때 ready-flag 소모 + LOCKED 재검사 + JSONL 포렌식.
3. **`tech_stack.py`** — PyYAML 없는 최소 파서로 `.claude/tech-stack.yaml`을 읽어 **후보 스킬 서브트리 목록**을 만든다(most-specific first, 존재 검사는 소비자에게 위임). `read_language`는 파이프라인 변형 선택용 첫 언어.
4. **`pipeline_stage_picker.py`** — 산출물 존재 여부로 완료 단계를 추정해 **다음 단계**의 스킬/DGE/단계명을 돌려준다. 코어+오버레이 병합 경로와 레거시 파싱 경로가 공존한다.
5. **`skill_match_render.py`** — 결과를 사람이 읽는 조언 문자열로 바꾸는 순수 렌더 계층(교차참조, phase 안내, 도구 라우팅 힌트, 센서 리마인더).
6. **`handlers/prompt/skill_match.py`** — UserPromptSubmit 훅 본체. 후보수집 → stack/phase/pipeline → scoring → 전문/포인터 계층 분리 → 예산 → per-body cap → telemetry → `additionalContext` 출력까지의 **유일한 조립 지점**.

---

## 3. 중요 발견 (근거 + 정적 반례 설계)

### F1. 예산과 per-body cap의 **순서 역전** — 예산을 버리면서 스킬을 잃는다 (High)
`skill_match.py:418`에서 `apply_token_budget`(4000)을 먼저 돌리고, `:424-436`에서 `PER_BODY_CAP=3000`을 **나중에** 적용한다. 1위가 3900자로 fit되면 `remaining_budget=100`이라 2위가 드롭되고(`skill_token_budget.py:172-193`), 그 **뒤에** 1위가 3000 이하로 다시 잘린다.
반례(순수 함수 조합, 실행 불필요): 1위 = `## 의사결정 트리`(3900자)+`## Other`(20000자), 2위 = 800자.
→ `fit_top_skill` = lvl1 3900 ≤ 4000 채택, remaining 100 → 2위 드롭 → cap 단계에서 1위 다시 ~3900>3000이라 재절단. 최종 주입 ≤3000, **잔여 1000자를 놀리면서 800자짜리 2위를 잃었다.** cap을 예산 앞에 두면 둘 다 산다.

### F2. cap 경로가 `TRUNCATION_MARKER`를 지운다 (Medium)
`fit_top_skill`이 절이 없는 본문을 하드슬라이스하면 끝에 `TRUNCATION_MARKER`가 붙는다(`skill_token_budget.py:104-105`). 그 결과가 3000자를 넘으면 `skill_match.py:427-433`에서 레벨1/2 추출이 모두 `""`가 되어 `_c[:3000] + "\n…(생략 — 토큰 절약)"`로 **표식이 잘려나간다**. 표식의 존재 이유("조용히 자르면 문서가 거기서 끝난 줄 안다", `:61-63`)가 이 경로에서만 무효화된다.
반례: `"x"*20000`(헤딩 없음) 1위 단독, 예산 4000 → fitted 4000(마커 포함) → cap → `"x"*3000 + "…(생략)"`.

### F3. 코드 주석이 **현재 동작과 반대**로 남아 있다 (Medium, 문서-코드 불일치)
`skill_match.py:68-71`과 `:420-423`은 여전히 "apply_token_budget keeps the top-ranked skill at FULL length **ignoring max_chars**"라고 적혀 있다. 이는 `fit_top_skill` 도입 **이전** 규격이며, `skill_token_budget.py:66-85`가 그 서술을 명시적으로 폐기했다. 즉 F1의 원인 주석이 그대로 살아 있어 다음 독자를 같은 방향으로 오도한다. (원문이 자기 역사에서 "이중 상수가 두 번 사람을 속였다"고 기록한 바로 그 패턴의 재발이다.)

### F4. `filename` vs `_disp` 키 불일치 — 파이프라인 부스트와 교차참조가 `SKILL.md` 스킬에 닿지 않는다 (High)
`skill_match.py:375-379`에서 `<dir>/SKILL.md`는 표시명 `_disp`(frontmatter name 또는 디렉터리명, **`.md` 없음**)로 키잉된다. 그런데
- 파이프라인 부스트는 `if filename in pipeline_skills`(`:387`)로 **원본 파일명**을 쓴다 → `SKILL.md` 형식 스킬은 `backend.md` 같은 단계 스킬명과 절대 일치하지 않아 **+3 부스트를 영원히 못 받는다.**
- `build_cross_references`는 `req_file = f"{req}.md"`가 `all_skills_meta`에 있는지 본다(`skill_match_render.py:90-91`) → `_disp`가 `.md` 없이 들어간 스킬은 `requires:` 대상이 되어도 **추천이 생성되지 않는다.**
반례: `skills/_common/backend/SKILL.md`(name: backend) + 현재 단계 `skills: [backend]` → `pipeline_skills=['backend.md']`, `filename='SKILL.md'` → 불일치. 반대로 `skills/gsd-x/backend.md`처럼 **basename만 같은 무관한 파일**은 부스트를 받는다(경로 무시 매칭).

### F5. 한 훅 실행 안에 **프로젝트 루트 정의가 두 개** 있다 (High)
`detect_project_type`은 `find_claude_dir`(최대 5단계 **walk-up**, `project_paths.py:51-75`)를 쓰는데, `load_tech_stack`/`read_language`/`resolve_stages_path`/`_stage_done`은 전부 `Path(cwd)/".claude"/…`로 **cwd 정확일치**만 본다(`tech_stack.py:146`, `pipeline_yaml.py:55`, `pipeline_stage_picker.py:52`).
반례: cwd = `<proj>/src/main/java`. → project-context는 정상 감지되지만 tech-stack 필터는 `None`으로 떨어져 **전체 트리 폴백**(원문 실측 기준 후보 95→285)으로 바뀌고 파이프라인 감지는 완전히 꺼진다. 즉 **서브디렉터리에서 프롬프트를 쓰면 라우팅 특성이 조용히 바뀐다.**

### F6. `tech-stack.yaml`의 **BOM 한 개**가 전체 필터를 무력화한다 (High, Windows 특이)
`tech_stack.py:151`은 `encoding="utf-8"`이다. BOM이 붙으면 첫 키가 `"\ufeffstack"`이 되어 `_LANG_BLOCKS`와 불일치 → `active == ["_common"]` → `len(active) > 1` 실패 → `None` 반환 → 전체 트리 폴백. `read_language`도 같이 `None` → 파이프라인 단계 감지도 꺼진다.
결정적 근거: 같은 저장소의 `frontmatter.py:33-35`는 **정확히 이 사고를 막으려고** `utf-8-sig`를 쓰고 그 이유를 주석으로 남겼다. 즉 규약이 있는데 이 파일만 안 따랐다. Windows 메모장/일부 에디터의 기본 저장이 BOM이라 재현 확률이 낮지 않다.
부수: 줄끝 주석(`version: "3.2"  # note`)은 `val_clean`에 그대로 남아 `java/springboot-3.2"  # note` 같은 후보를 만든다 — isdir 실패로 조용히 덜 구체적인 경로로 강등된다(크래시는 없음). CRLF는 `strip()`으로 무해하다.

### F7. `stages.yaml` 전역 기본값이 **Java/Spring 전용**인데 미등록 스택 전부가 그것을 받는다 (High)
`resolve_stages_path`는 `stages-{lang}.yaml` → 없으면 전역 `stages.yaml`으로 떨어진다(`pipeline_yaml.py:63-69`). 현재 pinned 트리의 오버레이는 `dart/flutter/java/node/rust` 5개뿐이고, 전역 `stages.yaml`은 `build.gradle`, `mybatis`, `JaCoCo`, `SpringDoc`이 박힌 Java 파이프라인이다(grep 근거: `skills:[backend, mybatis, redis, auth-jwt-oauth]`, `output: "build.gradle + application.yml + 공통 클래스"`).
반례: `language: python` 프로젝트 → `has_overlay('python')=False` → Java 단계표 로드 → 해당 단계 스킬이 `is_match=True`로 **강제 매칭(+3)**되어 매 프롬프트마다 무관한 백엔드/마이바티스 스킬이 포인터로 올라온다.

### F8. `src/` 휴리스틱이 **단계 순서를 건너뛴다** (High)
`_stage_done`은 `"src/" in output`이고 `src/`가 비어있지 않으면 완료로 친다(`pipeline_stage_picker.py:59-63`). 전역 `stages.yaml`에서 그 조건에 걸리는 단계는 뒤쪽의 단위테스트 단계(`output: "src/test/ 테스트 클래스 + JaCoCo 리포트"`, 305행)다. 그리고 `last_done_idx`는 **최대 인덱스**만 취한다(`:106-110`).
반례: `src/main/java/App.java` 하나만 있는 신규 프로젝트 → 단위테스트 단계 done → `next_idx`가 신뢰성테스트 단계 → `dge=evaluator` → `detected_phases`에 `"review"`가 추가(`skill_match.py:356-357`)되어 **설계도 구현도 안 끝난 상태에서 리뷰 phase 안내·센서 리마인더가 나간다.**
부수 2건: (a) 다수 단계의 output이 `"build.gradle + application.yml + 공통 클래스"`, `"domain/{도메인명}.md"` 같은 **경로가 아닌 산문**이라 `os.path.exists`가 영구히 False다 — 감지 불능 단계다. (b) `optional` 단계는 done 판정에서만 제외되고 인덱스는 그대로라 `next_idx`가 optional 단계에 착지할 수 있다.

### F9. `skills`/`output`이 **블록 시퀀스**면 훅 전체가 조용히 죽는다 (High)
`pipeline_yaml.normalize_value`는 flow가 아닌 리스트를 **네이티브 리스트로 보존**하고(`:127-142`), 오버레이 경로의 `_normalize_field`는 `output`을 flow 키로 취급하지 않는다(`pipeline_overlay.py:41,79`). 소비자는 `skills_raw.strip("[]")`(`pipeline_stage_picker.py:71`)와 `output.startswith("[")`(`pipeline_yaml.py:181`)로 **문자열을 가정**한다.
반례: 프로젝트 `.claude/stages.yaml`에 
```
- id: impl
  skills:
    - backend
```
(블록 표기) → `AttributeError: 'list' object has no attribute 'strip'` → `skill_match.main`의 최상위 `except Exception: pass`(`:611-612`)가 삼킴 → **그 프롬프트의 `<activated-skills>` 전체가 사라진다.** 실패도, telemetry도, stderr도 없다. 플로우 표기 `skills: [backend]`만 우연히 살아 있는 상태다.

### F10. 실패 관측 부재 — 광역 `except`가 부분 실패를 전면 무음화한다 (High)
`main()` 전체가 하나의 `try/except Exception: pass`다. F9뿐 아니라 스킬 디렉터리 권한 오류, 파서 예외, `json.load` 실패 모두 **정상 종료(exit 0) + 빈 출력**과 구분되지 않는다. 반면 `scan_root_unresolved`만은 telemetry를 남긴다(`:203-208`) — 즉 관측 규약이 존재하는데 가장 치명적인 경로에만 없다.
추가: `sys.stdin.reconfigure`(`:26-27`)는 try **밖**이라 stdin이 TextIOWrapper가 아닌 실행 형태에서는 트레이스백으로 하드 실패한다.

### F11. 드롭된 전문 스킬은 **어디에도 나타나지 않는다** (Medium)
`apply_token_budget`이 2위 이하를 드롭하면 `was_truncated=True`만 남고, 출력 문구는 "일부 스킬이 **축약**되었습니다"(`:566`)다. `pointer_skills`는 예산 이전에 확정되므로(`:407-416`) 드롭된 스킬은 포인터로도 강등되지 않는다. 포인터 초과분은 `(+N개 생략)`으로 정직하게 알리는데(`:539-540`), 전문 드롭만 비대칭적으로 은폐된다. telemetry의 `pointer_count`도 이들을 세지 않는다.

### F12. 단위 혼동: **문자 ≠ 토큰 ≠ 바이트** (Medium)
모듈명·주석·사용자 문구는 전부 "토큰 예산/토큰 절약"인데 구현은 전부 `len(str)` = **유니코드 문자수**다. telemetry 필드만 `body_chars`로 정직하다(`:450`). 결과적으로 동일한 4000 "예산"이 ASCII 본문과 한글 본문 사이에서 실제 토큰 비용이 배수로 갈린다(한글은 문자당 토큰이 ASCII보다 크다). 바이트 개념은 어디에도 없고 UTF-8 저장 크기와도 무관하다. 또한 예산이 지배하는 것은 **전문 본문 합계뿐**이며 포인터·교차참조·phase 안내·advisory는 예산 밖이다 — 특히 `build_cross_references`는 **상한이 없다**(포인터는 `MAX_POINTERS=8`로 제한되는데 교차참조는 무제한). 즉 "4000자 예산"은 실제 주입량의 상한이 아니다.

### F13. `threshold_policy`의 값 검증 공백 (Medium)
`apply_threshold_override`는 등록 여부·LOCKED·방향 토큰·ready-flag는 검사하지만 **값의 타입/범위는 검사하지 않는다**. `POLICY_PATH`에 `f"  {k}: {value}"`로 그대로 쓰고(`:74-77`), 읽을 때 `_coerce_num`이 실패하면 그 키를 **조용히 버린다**(`:68-69`).
반례: `apply_threshold_override("skill_match.FULL_BODY_MIN_SCORE", "high", token=TOKEN_RISKY)` → True 반환 + 히스토리에 성공 기록 + ready-flag 소모 → 다음 프롬프트에서 `resolve_threshold`는 기본값 3을 돌려준다. **포렌식은 적용됐다고 말하고 런타임은 적용 안 된 상태**로 갈린다(anti-replay 플래그까지 소모돼 재시도도 막힌다). 또 `0`이나 음수도 게이트만 통과하면 허용되어 전문 주입 문턱이 사실상 사라진다(상한은 `FULL_BODY_TOP_K=3`이 잡아준다).
Windows 특이: `_ready_flag_path`는 `/`와 `\`만 치환한다. 레지스트리 이름에 `:`가 들어오면 NTFS에서 대체 데이터 스트림 경로가 되고, 대소문자만 다른 두 이름은 같은 플래그 파일을 공유한다(현재 레지스트리에는 해당 이름이 없다 — 잠재 위험).

### F14. 스코어링 쪽 부수 관찰 (Low~Medium, 범위 확장분)
- `_disp` 충돌: 서로 다른 디렉터리의 `SKILL.md`가 같은 `name`을 선언하면 `all_skills_meta`/`base_scores`가 덮어써져 포인터 설명이 **다른 스킬 것**으로 표시될 수 있다(`collect_skill_files`는 상대경로 키로 중복 제거하므로 둘 다 수집된다).
- `detect_tool_routing_hints`는 순수 부분문자열이라 `"concat file"`이 `"cat "` 규칙에 걸린다. 조언 성격이라 영향은 작다.
- `score_skill`의 `HIGH_DF_INTENT`는 **폐쇄 목록**이고 드리프트 감지를 테스트에 의존한다 — 코퍼스가 Zeus로 바뀌면 즉시 낡는다(원문도 이를 명시).

### 테스트 커버리지의 실제 경계 (문서 주장 아님, 파일 근거)
- `test_skill_token_budget.py`는 **모두 `max_chars=8000`**으로 돈다. 프로덕션 값 4000과 `PER_BODY_CAP=3000`의 **상호작용(F1/F2)은 어떤 테스트도 건드리지 않는다** — 그 조립은 `skill_match.main` 안에만 있고 main 단위 테스트가 없다.
- `test_pipeline_stage_picker.py`의 `detect_pipeline_skills` 테스트는 `no_cwd`/`no_pipeline` 2개뿐 — 실제 `stages.yaml`을 통과하는 경로(F7/F8/F9)는 미검증.
- `test_tech_stack.py`에 BOM/주석/중첩깊이 케이스 없음(F6).
- `test_threshold_tuning.py`에 값 타입/범위 케이스 없음(F13).

---

## 4. Zeus 적응 후보 (설계 제안 — 채택·승인 아님)

**PostgreSQL 런타임 SSOT vs Git 정의 분리 관점**
- **Git(정의)**: `MAX_CONTEXT_CHARS`, `PER_BODY_CAP`, `FULL_BODY_TOP_K`, `MAX_POINTERS`, 레지스트리 스키마, LOCKED_DENY. → 코드 리뷰를 거치는 불변 정의.
- **PG(런타임 SSOT)**: `threshold-overrides.yaml` + `threshold-ready/*.flag` + `threshold-policy-history.jsonl`의 **3중 파일 상태**를 단일 테이블 트랜잭션으로 대체. 현재 구조는 "yaml 쓰기 성공 → 플래그 unlink → 히스토리 append"가 원자적이지 않아 중간 실패 시 상태가 갈린다(F13과 결합하면 포렌식이 거짓말한다). PG면 `apply`가 한 트랜잭션이고 flag 소모가 `UPDATE … WHERE consumed_at IS NULL`로 자연스러운 anti-replay가 된다.
- **경계 규칙 제안**: "값은 PG, 허용 집합(레지스트리·LOCKED)은 Git" — 즉 PG는 Git 정의의 부분집합만 저장할 수 있고, 읽기는 항상 Git 기본값으로 fail-soft(현재 `resolve_threshold` 계약 유지).

**실제 시나리오 인수 조건 후보(예산·라우팅)**
1. cwd가 프로젝트 서브디렉터리여도 tech-stack/파이프라인 해석이 루트와 동일하다(F5).
2. BOM/CRLF/줄끝주석이 붙은 tech-stack에서 후보 집합이 동일하다(F6).
3. 미등록 스택(python 등)은 타 스택 파이프라인을 상속하지 않고 **파이프라인 없음**으로 떨어진다(F7).
4. 산출물 감지가 단계 순서를 역행 승격시키지 않는다(F8).
5. 블록/플로우 YAML 표기 차이가 라우팅 결과를 바꾸지 않고, 파서 실패가 **관측 가능**하다(F9/F10).
6. 최종 주입량이 선언된 예산의 상한 안에 있고, 드롭은 출력에 명시된다(F1/F11/F12).

**자격검증 배분 제안**
- **Astra(설계)**: ① 예산 파이프라인 단일화 — cap을 예산 **이전**으로 옮기고 `apply_token_budget`이 per-body cap을 인자로 받는 단일 함수 계약으로 재설계(F1/F2/F3). ② 프로젝트 루트 해석기 1개로 통일(F5). ③ 임계 오버라이드의 PG SSOT 전환 + 값 도메인(타입·범위) 선언(F13).
- **Sol(중요 구현 자격검증)**: F1, F4, F5, F7, F8, F9, F10, F13 — 라우팅 결과 자체가 바뀌거나 무음 실패를 만드는 것들. 각각 정적 반례를 **회귀 테스트로 먼저 실패시키는** 것을 자격 조건으로 삼을 만하다(특히 F9는 예외를 삼키지 않는 관측 경로가 함께 필요).
- **Terra(단순 구현 자격검증)**: F6(`utf-8-sig` 한 줄), F2(마커 보존), F3(주석 정정), F11(드롭 카운트 노출 + 문구 수정), F12(명칭을 `*_CHARS`로 정정하고 교차참조에 상한 부여), F14의 `_disp` 충돌 경고. 각각 단일 파일·단일 함수 범위다.

---

## 5. 미검증 / 명시적 한계

- **실행을 하지 않았다.** 위 반례는 전부 **정적으로 설계한 것**이며, 실제 실행 결과가 아니다. 원문 주석에 적힌 실측치(65,727자, 311개 중 66개, 후보 95/112/285 등)와 테스트 파일의 PASS 서술도 **문서 주장으로만 취급**했고 재현하지 않았다.
- 개인 설정·라이브 세션·자격증명·외부 웹을 열지 않았으므로 `~/.claude/config/threshold-overrides.yaml`, `state/threshold-ready/`, 실제 telemetry의 **현재 값은 모른다**. 따라서 `FULL_BODY_MIN_SCORE`의 런타임 실효값(기본 3인지 오버라이드된 값인지)은 미확인이다.
- `skills/` 실제 코퍼스(파일 수, `SKILL.md` 형식 비율, `requires:` 사용률)를 세지 않아 **F4의 실제 영향 규모는 미측정**이다. 존재 여부는 확인했으나 열지 않은 파일이 다수다.
- Windows/Linux/WSL/root 차이는 **코드 경로 기준 추론**이다. `os.path.samefile`, `USERPROFILE`/`HOME` 동시 설정, WSL 마운트 경로에서의 실제 동작은 실행 검증이 필요하다.
- `lib/thin_skill_advisor.py`, `lib/telemetry_read.py`, `lib/phase_detector.py`, `lib/frontmatter_norm.py`, `lib/skill_surgery.py`는 읽지 않았다 — advisory·phase 감지 관련 판단은 그만큼 불완전하다.
- 하네스 전체의 완료·채택·운영 승인 여부에 대해서는 **아무 주장도 하지 않는다.** 위는 6파일과 그 직접 의존/데이터에 한정된 독립 정적 소견이다.

---

준비됐다. Codex의 독립 발견과 실제 테스트 결과를 주면, 특히 **F1/F2(예산×cap 순서)**, **F9(블록 시퀀스 무음 사망)**, **F13(적용 성공 기록 vs 미적용)** 세 건을 우선 대조해 어느 쪽 반례가 실행에서 재현되는지 좁혀보자.