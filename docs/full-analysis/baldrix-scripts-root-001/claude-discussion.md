root 산출물 7종과 두 영수증·스트림을 모두 읽고, 각 정정 항목을 소스에서 직접 재확인했습니다.

# 공동 검토 — Baldrix scripts 루트 5종 (2차)

## 0. 이번에 내가 직접 읽은 것 / 인증하지 않는 것

**root 산출물(전문):** `codex-initial.md`, `root-support-notes.md`, `observations.md`, `component_observations.py`, `run_observations.py`, `install-hooks-unit.{receipt.json,stdout.txt,stderr.txt}`, `components.{receipt.json,stdout.txt,stderr.txt}`. (두 stderr는 빈 파일임을 확인.)

**정정 검증을 위해 내가 추가로 읽은 소스 범위:** `reviewer.py` L1–125 및 `SCRIPTS_DIR` 전체 출현(L114, 369, 376, 378), `handlers/**` 파일 목록(Glob), `handlers/session/init.py` L1–21·L67–83·L801–834(grep 문맥).

**내가 인증하지 않는 것:** 영수증의 `stdout_sha256`/`stderr_sha256`/`source_tree_hash_before`/`program_sha256`/이미지 다이제스트 `sha256:39d4f2…`, 그리고 스코프 해시 `88f312…4a34`와 26,711바이트. 나는 어떤 해시도 계산하지 않았고 계산할 수단도 없습니다. 영수증 필드가 **존재하고 서로 형식적으로 일관되다**는 것만 확인했습니다. `source_bytes_unchanged: true`는 같은 프로그램의 자기보고이며, 내가 독립 확인한 것이 아닙니다. 컨테이너가 실제로 그 argv로 실행되었다는 것도 나는 관측하지 않았습니다 — 나에게 root 실행은 **파일로 제출된 기록**이지 관측이 아닙니다.

`component_observations.py`는 전문을 읽었고, `unittest.mock`·몽키패치·가짜 프로세스 결과·가짜 시계가 없음은 **내가 코드에서 직접 확인**했습니다. 입력은 합성 파일이지만 호출 대상은 실제 인터프리터/bash/git입니다. 이 구분은 유효합니다.

**초기 보고서는 원문 그대로 보존합니다.** 아래는 덮어쓰기가 아니라 부기(附記)입니다.

---

## 1. 합의 (재확인 완료)

덮어쓰기, 미사용 `CLAUDE_HOME`/`SCRIPTS`, 현재 워킹트리 검사, 로그 절단, 설치 러너의 rc 단독 판정, 보고/카운터 분모 결손, JaCoCo 요약/상세/제외 불일치, Mermaid 휴리스틱 대 렌더러, 카테고리 라벨 중복 제거와 잘못된 입력의 침묵, `context-bar.sh` 대체 — 모두 합의합니다.

root가 정적으로만 제기했던 **push ref 미바인딩**은 내가 놓친 항목입니다. `install_pre_commit.sh` L56–79의 pre-push 훅은 stdin으로 오는 후보 ref/sha를 읽지 않고 `cd "$ROOT/scripts"` 후 현재 트리를 검사합니다. 통과는 **푸시되는 정확한 리비전이 아니라 로컬 워킹트리 상태**에 대한 것입니다. 채택합니다.

`core.hooksPath` 불일치(관측 stdout L29–31: 설정된 디렉터리의 pre-commit 부재, 기본 `.git/hooks`에만 생성)와 연결 워크트리 실패(L33–34: `.git`이 파일이라 L26 `mkdir -p`가 실패, `set -e`로 rc1)도 내가 놓친 항목입니다. 채택합니다.

---

## 2. 내 초기 보고서 정정

**(1) §1 — 가장 큰 정정. “Mermaid 실패가 통과로 뒤집힌다”는 무조건 서술은 틀렸습니다.**
내가 L376–435만 읽고 정의 상수를 빠뜨렸습니다. `reviewer.py` L114 `SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))`은 `handlers/post_tool/`입니다(L113 주석은 “다른 글로벌 스크립트가 사는 곳”이라 말하지만 사실이 아닙니다). Mermaid는 DAG에서 `project_script=False`(L174, L186)이므로 L377–378의 else 분기로 **오직 `handlers/post_tool/mermaid-validate.py`만** 찾습니다. 핀 트리의 `handlers/post_tool/`에는 5개 `.py`만 있고 그 파일은 없습니다(Glob 확인). 따라서 L380–381에서 `None`이 반환되고 서브프로세스는 시작되지 않습니다.

정정된 서술: **핀 트리 기본 배치에서 Mermaid 게이트는 조회 단계에서 탈락해 아예 실행되지 않을 수 있다.** false PASS는 “스크립트가 해석된 경우에 한해” 성립하는 조건부 매핑이며, 나는 훅을 실행하지 않았고 root도 실행하지 않았으므로 어느 쪽도 현재 기본 훅 동작으로 제시해서는 안 됩니다. 또한 `reviewer.py`가 PostToolUse로 실제 등록되어 있는지는 내가 읽은 `settings.json` L324–349 범위 밖이라 미확인입니다.

“게이트가 실패를 표현할 수단이 없다”도 너무 넓었습니다. L416–421의 `TimeoutExpired`는 `<spec-verify-fail>`을 냅니다. 정확히는 **타임아웃만 실패로 표현되고, 검증기 자신의 판정(rc·stderr)은 표현 경로가 없다**입니다.

**(2) §4 — 범위 진술로 낮춥니다.** “유일한 호출자”, “전용 테스트 없음”은 파일명 grep 결과이지 동적 호출자·테스트 부재의 증명이 아닙니다. `run_all.py` 본문과 상위 자동화는 미독입니다. 따라서 “Windows 경로를 실행하는 자동 경로가 하나도 없다”는 문장을 철회하고 **“내가 읽은 `ci.yml` 텍스트 범위 안에서는 Ubuntu 단일 러너뿐이며, 상위 리포의 현행 실행 인벤토리는 확인하지 않았다”**로 대체합니다. 실제 CI 실행 이력은 어느 쪽도 조회하지 않았습니다.

같은 절의 CI 요약도 부정확했습니다. `ci.yml`은 **두 잡**입니다: `regression`(L34–64)과 `brain-snapshot-integrity`(L66–88). 경로 필터(L16–19, L22–26)도 함께 기술했어야 합니다.

**(3) §7 결론부 — “정규화+basename 조합이 이식성 가드”라고 인정한 것은 틀렸습니다.** `file-changed-handler.py` L61의 정규화는 `categorize_file` **내부 지역 변수**이고, 출력용 basename은 L88에서 **정규화되지 않은 `fp`**에 적용됩니다. 관측 stdout L19가 이를 확증합니다 — Linux에서 `C:\repo\package.json`이 basename으로 경로 전체를 그대로 출력했습니다. 보존 대상 목록에서 이 항목을 뺍니다. (분류는 정규화되고 표시는 안 되는, 반쪽 이식성입니다.)

L25–26 최상위 `reconfigure`가 “유일하게 시끄러운 실패 경로”라는 표현도 과했습니다. SystemExit·시그널·호스트 타임아웃(설정 timeout 5)·출력 전달 실패는 이 스크립트의 `except`와 무관하게 다르게 나타날 수 있습니다. **“try 블록 바깥이라 이 파일의 침묵 처리에 걸리지 않는다”**로 좁힙니다.

**(4) §7 — “감시 경로 갱신 기능은 존재하지 않는다”는 틀렸습니다.** `handlers/session/init.py`를 직접 확인했습니다: L4·L13 헤더, L75 `build_watch_paths`, L809·L825–826·L834에서 SessionStart가 `hookSpecificOutput.watchPaths`를 실제로 방출합니다. 정정: **watchPaths는 SessionStart에 존재하며, `file-changed-handler.py`의 헤더(L16)와 본문(L96–102 `systemMessage`) 사이의 불일치는 그 파일 내부의 문서-코드 드리프트**입니다. 호스트가 두 스키마 중 무엇을 수용하는지는 어느 쪽도 검증하지 않았으므로, “스키마 불일치”와 “살아있는 호스트 계약 위반”은 계속 분리합니다.

**(5) §6 — “무증상 열화”는 틀렸습니다.** 관측 stdout L35: jq 부재 시 `context-bar.sh`는 stderr에 `line 37/38/109/114: jq: command not found`와 `line 163: baseline * 100 / max_context: division by 0`을 내고, stdout에는 부분 상태줄만 찍고 **rc0**입니다. 정정: **stderr는 시끄럽고 rc는 성공이며, stdout에는 unavailable 표식이 없다.** statusLine 맥락에서 그 stderr가 사용자에게 도달하는지는 미검증이므로 주장하지 않습니다. 또한 현재 statusLine은 `hud.py`이므로(settings L343–346) 이는 **현행 statusLine 실패가 아니라 구 선택적 표면의 성질**입니다.

빈 값 산술로 인한 거짓 `synced`(L78)는 여전히 **정적 판단**입니다 — jq가 있는 환경에서 실행되지 않았으므로 관측으로 승격하지 않습니다. WSL 폴백(L27–29)을 “무해”라고 단정한 것도 철회합니다: 그 경로가 `-x` 검사(L30)에서 걸러지는 것은 코드상 그렇다는 것이고, 플랫폼 전반의 무해성은 실행 없이 일반화할 수 없습니다.

**(6) §2·§4 — “테스트가 preservation을 영구히 배제한다”는 과대주장입니다.** `test_install_hooks.py` L69의 부분문자열 `cat > "$HOOK_PATH"` 단언은 그 앞에 백업(`cp`)이나 합성 로직이 오는 것을 **논리적으로 막지 않습니다.** 정정: **현재 설치 스크립트에 보존 로직이 없다**는 사실 진술만 유지하고, 테스트가 개선을 봉쇄한다는 인과 주장은 철회합니다. 아울러 “미사용 `CLAUDE_HOME`/`SCRIPTS` 선언(L15–16)”과 “생성된 훅이 L67에서 `CLAUDE_HOME`을 재설정”은 **별개 관측**입니다 — 설치 스크립트 자신의 셸은 부모 환경을 변형하지 않습니다.

**(7) §8 요약 — “pre-commit/pre-push만 실패를 표현할 수 있다”는 틀렸습니다.** 관측이 반례를 줍니다: Mermaid 빈 블록 → `ERROR 1`, rc1(components L12); JaCoCo `--summary-only` 루트 갭 → rc1(L5), 제외+summary → rc1(L9). 네 층으로 분리해 다시 씁니다:

| 층 | 상태 |
|---|---|
| CLI 능력 | Mermaid·JaCoCo 모두 특정 경로에서 rc1을 낸다 (관측됨) |
| 타입 유효성 | Mermaid의 `PASS`가 공식 문법 유효를 뜻하는지 **미상** |
| 소비자 해석 | `reviewer.py`는 rc를 읽지 않고 `[FAIL]` 문자열만 본다 (정적) |
| 호스트 수신 | FileChanged `systemMessage`의 실제 전달 여부 **미검증** |

**(8) §5 첫 항목 — `<group>` 중첩 가설을 철회합니다.** 나는 인증된 JaCoCo 집계 리포트 문법을 검증하지 않았으므로 그 기제를 주장할 근거가 없었습니다. 관측이 보여준 실제 기제는 다릅니다: 요약(L64–69)은 `counter_of(root, …)`로 **루트의 직계 `<counter>`만** 읽고, 상세(L79–99)는 **메서드 행만** 모읍니다. 둘 사이에 집계가 없습니다. 결과가 두 방향으로 갈립니다 —

- 루트 LINE 갭 + 메서드 행 없음: 요약 `[GAP] LINE 3/5 60%` → 상세 “No coverage gaps”, **rc0**; 같은 입력에 `--summary-only`는 rc1 (components L4–5).
- 클래스 LINE 갭(missed=2) + 루트 카운터 없음: 요약이 `[OK] LINE 0/0 100.00%`로 표시, **두 모드 모두 rc0** (L6–7). 실재하는 갭이 “100%”로 보고됩니다.
- 제외 지정: 상세 rc0, `--summary-only` rc1 (L8–9) — 내가 정적으로 지목한 제외 비대칭이 관측으로 확인.

내 원래 주장(요약/상세 모순, 부재 카운터의 100% 보고)의 **결론은 유지되고 기제는 교체**됩니다.

---

## 3. root 진술에 대한 정정·정밀화

**(a) 합성 XML/MD를 “관측”으로 부르는 범위.** root가 스스로 명시했듯 이들은 합성 형태이며, 인증 JaCoCo 산출물·Java 컴파일·실제 커버리지 측정이 아닙니다. 동의하며, 한 가지 덧붙입니다: `class_gap_without_methods` 픽스처는 클래스에 `<method>`가 없는데, 실제 JaCoCo 출력에서 그 형태가 나타나는지는 **미확인**입니다. 따라서 그 케이스는 “현실 리포트에서 발생한다”가 아니라 **“파서가 그런 입력을 받으면 이렇게 판정한다”**로만 읽어야 합니다.

**(b) “A body not parsed by a grammar still yielded PASS”의 기제 보강.** root는 결과만 기록했는데, 원인은 길이 가드입니다. `mermaid-validate.py` L89·L103의 `len(lines) > 2` 조건 때문에 **2줄짜리 블록은 화살표/상호작용 검사를 통째로 건너뜁니다.** `unparsed_body` 픽스처는 정확히 2줄이라 화살표 검사가 발화하지 않았고, 노드 정규식 `(\w+)\[([^\]"]+)\]`(L109)도 `[]`(빈 내용)에는 매치되지 않아 PASS가 됩니다. 즉 이 PASS는 “검사에 통과”가 아니라 **“검사가 적용되지 않음”**입니다 — 분모 문제로 재분류해야 합니다.

**(c) `printf %b` 항목의 도달 경로 좁히기.** root의 “display/control-sequence handling, not an execution exploit”에 동의합니다. 다만 도달 가능한 입력은 좁습니다: git refname은 백슬래시를 허용하지 않으므로 `branch`는 경로가 아니고, 현실적 통로는 L100의 `single_file`(파일명)과 jq로 뽑은 `model` 표시명입니다. 이 좁힘을 기록합니다.

**(d) “negative percentages are not bounded”.** 코드상 상한만 있고(L143, L164) 하한이 없는 것은 맞지만, 비음수 입력에서 음수 pct는 도달하지 않습니다. **코드 형태의 서술**로 유지하고 결함으로 승격하지 않기를 제안합니다.

**(e) 영수증 표현.** `observations.md` L3의 “Receipts bind argv, image, source and stream hashes”는 필드가 존재한다는 뜻으로만 읽어야 합니다. 나는 어떤 해시도 대조하지 않았고, 저장된 stdout 파일과 `stdout_sha256`의 대응조차 확인하지 않았습니다. 두 stderr가 빈 파일이라는 것과, 두 영수증의 `stderr_sha256`이 동일한 값이라는 **형식적 일관성**만 확인했습니다.

**(f) “every real push exercises installation”.** root-support-notes L3의 지적(소스 주장이지 실행 영수증이 아님)에 동의합니다. 이는 `test_install_hooks.py` L9–10 주석에 대한 정확한 평가입니다.

---

## 4. 유지되는 판정 (양측 독립 확인)

- 설치 스크립트가 기존 pre-commit을 백업 없이 파괴 — 정적 판단(L28)이 스크래치 Git에서 확증(`existing_marker_retained: false`).
- `core.hooksPath`가 설정된 리포에서 설치는 rc0을 내고도 **실효 훅 디렉터리에 아무것도 넣지 않음**. 성공 메시지(L83–86)가 설치 실패를 덮습니다.
- 연결 워크트리에서 rc1로 중단(`.git`이 파일). `install_pre_commit.sh`가 워크트리 `.git` 파일을 해석하지 않음.
- pre-push가 후보 ref를 무시하고 현재 트리를 검사.
- 실패 로그 25줄 절단 후 즉시 삭제(L70, L75).
- 소스 트리 불변: `component_observations.py` L62–64가 Mermaid 실행 전후 해시를 대조하고, 영수증이 트리 불변을 자기보고. 나는 프로그램 텍스트만 확인.

**보존 대상 재확인:** `install_pre_commit.sh` L42/L63의 추적 기반 가드와 이를 잠근 `test_install_hooks.py` L48–63, `context-bar.sh` L59의 GNU/BSD `stat` 이중 폴백. (§2-(3)에 따라 `file-changed-handler.py`의 정규화는 이 목록에서 제외했습니다.)

---

## 5. 유한한 채택 요건

**정확 리비전 게이트** — pre-push는 stdin의 `<local ref> <local sha1> <remote ref> <remote sha1>`을 읽어 각 후보 sha에 대해 격리된 트리(예: 분리 워크트리/아카이브)에서 스위트를 돌려야 합니다. 현재 워킹트리 통과는 푸시 대상에 대한 증거가 아닙니다. 완료 판정: 더러운 워킹트리 + 깨끗한 후보 리비전, 그리고 그 역 조합에서 rc가 후보를 따라가는지.

**검증된 출력과 미상 분모** — 세 값을 분리해 출력해야 합니다: 검사됨/제외됨/측정 불가. JaCoCo는 (i) 루트 카운터 부재를 100%가 아니라 `UNKNOWN`으로, (ii) 요약과 상세를 같은 집계원에서, (iii) `--exclude`를 두 모드에 동일 적용해야 합니다. Mermaid는 `len(lines) > 2` 가드로 건너뛴 블록을 PASS가 아닌 `NOT-CHECKED`로 세고, PASS 카운터를 파일이 아닌 블록 단위로 바꿔야 합니다. 소비자 쪽은 rc+stderr를 읽거나, 검증기들이 리포지토리의 stdout PASS/FAIL 규약을 실제로 따라야 합니다.

**이식 가능한 설치** — 기존 훅 백업 또는 합성, `core.hooksPath` 해석, 워크트리 `.git` 파일 해석, 실효 설치 위치 검증 후에만 `[OK]` 출력. 완료 판정: 기존 훅 있음 / hooksPath 설정됨 / 연결 워크트리 세 시나리오에서 실제 bash+git으로 재실행.

**SDD 인간·비목킹 수용** — 위 항목은 전부 도구 자기검사입니다. 어느 것도 사용자 시나리오, 실제 Mermaid 렌더러, 실제 Gradle/JaCoCo 산출, 인간 QA, 모델 자격을 대체하지 않습니다. 합성 픽스처 통과는 인증 산출물 수용이 아닙니다.

---

## 6. 미해결 (양측)

`run_all.py`·`commit_layer_adjacency.py`·`hud.py` 본문, `settings.json` 전체(따라서 `reviewer.py` 등록 여부), 상위 리포의 현행 CI 실행 인벤토리, 호스트의 hook 출력 스키마 수용, jq 활성 환경에서의 `context-bar.sh` 토큰/동기 표시, 인증 JaCoCo 리포트 문법, 공식 Mermaid 파서 판정. 라이선스·모델·네이티브 OS 동등성·채택도는 전부 미종결이며 어느 쪽도 주장하지 않습니다.