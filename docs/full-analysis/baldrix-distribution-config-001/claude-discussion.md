# 후속 검토 — 정정 수용/반대

원본 영수증(`attempts/d9b82d63392f4a33bfb0e4076a23288c/{receipt,source-check}.json`, `stdout.txt` 8행), `platform-references.md`, 그리고 pinned 원문을 다시 대조했다. 초기 보고서는 그대로 두고 아래를 정정본으로 덧붙인다.

---

## 1. CI 브랜치 주석 — **수용 (역독해 정정)**

내 판독 "실 브랜치가 master"는 철회한다. ci.yml:10 이 `기본 브랜치는 main 이다`라고 먼저 선언하므로 `여기가 master 라`의 "여기"는 저장소가 아니라 **당시의 filter 값**으로 읽는 것이 문단 내 정합적이고, 현재 파일이 실제로 `branches: [main]`(ci.yml:15)인 사실과도 맞는다. 즉 **주석은 수정 전 상태의 사후 기록이고, 필터는 이미 고쳐졌다.**

남은 경계: ci.yml:3 의 `harness (master)` 표기는 그 정정을 따라가지 않아 여전히 낡았다(문구 잔존 지적이지 동작 결함 주장 아님). 과거 실행 이력 2건은 **나도 root도 조회하지 않았으므로** 어느 쪽 근거로도 쓰지 않는다.

## 2. 원본 영수증 vs 내 정적 판단 — **수용 (출처 분리)**

내 초기 표는 전부 **코드 독해에서 유도한 예측**이었다. 이제 지위를 나눈다.

| 경계 | 내 정적 예측 | 원본 영수증 관측 |
|---|---|---|
| baseline(`/source`) | — | rc0, l1 910/249, l2 2/0/20, graduation 2/2 |
| snapshot 부재 | 초록 | rc0, 전 계층 0 |
| 중간 행 파손 | 초록·스킵 | rc0, `brain: 2`(3행 중 1행 소실) |
| 비객체 행(`[] null 42`) | (미예측) | rc0, `brain: 0` |
| schema·id 동시 누락 | 초록 | rc0, `brain: 1` |
| graduation 파손 | 초록 | rc0, graduation 0/0 |
| 버전 불일치(control) | 하드페일 | **rc1**, `SCHEMA MISMATCH ... '999' != '1'` |

`source_files 1648 / source_bytes_unchanged true / container_cleanup_returncode 0`. 예측과 관측이 일치하지만 **일치 자체가 내 판단을 관측으로 승격시키지 않는다** — 관측 권원은 영수증에 있다. `full_skill_match_hook_executed: false` 이므로 7절의 매처 쪽 서술은 여전히 코드 독해다.

## 3. 분모 산수 — **수용 (1182 및 프레이밍 철회)**

- **1182는 오류다.** 나는 `^\{` grep 결과 5개 파일을 합산하면서 `brain/graduation/graduation-state.json`의 1행(JSON 객체 1행, JSONL 레코드 아님)을 JSONL 분모에 섞었다. 정정: **JSONL 레코드 910+249+2+0+20 = 1181**, 영수증 baseline과 일치.
- **"gitignored라 CI에서 항상 0"도 철회.** 영수증 baseline `live_validators: 2`가 반증한다. `.gitignore:88`이 있어도 이미 tracked면 제거되지 않고, 실제로 `state/graduation-state.json`이 pinned 트리에 존재한다(doc_code_drift, self_model_drift). 다만 **JSONL live 0 은 관측으로 유지**된다(baseline 전 계층 live 0).
- **"269건(22.8%) 미검사"라는 프레이밍도 철회.** 산수는 정정 분모에서도 269/1181≈22.8%지만, 프레이밍이 틀렸다. 실측한 레코드 형태:
  - `insight-index-retractions.jsonl:1` → `{reason, retracted_id, ts_unix_ms}`
  - `global-facts-evidence.jsonl:1` → `{added_ts_ms, fact_id, l1_correlation_id, l1_entry_id}`

  둘은 **형식이 서로 다르고 `schema_version`을 갖도록 설계되지 않은 별개 계약**이다. 이질적 계약을 하나의 `schema_version` 분모에 넣어 "커버리지 구멍 22.8%"로 제시한 것은 부당하다. 정정 서술: **버전 게이트는 `schema_version` 보유 레코드(912건)에만 걸리고, 나머지 269건은 필드 계약이 다른 두 파일에 속한다.** 그 269건에 별도 형식 검증이 필요한지는 각 형식의 스키마 계약을 확정하지 않았으므로 **미판정**.
- 내 "리트랙션=부활 방지 근거 데이터 269건" 표현도 철회한다. evidence 20행은 리트랙션이 아니라 fact↔L1 참조 간선이다. **brain 본문 전량·참조 무결성은 이번에 미완료**로 남긴다.

## 4. "유일하게 잡히는 것" — **수용, 단 반증 근거를 재정박**

- **철회:** "유일". 관용 경로는 명시적으로 좁은 것들이다 — `_read_jsonl_pinned`는 `except OSError`(brain_store.py:124)와 `except json.JSONDecodeError`(133)만 잡고, `_load_json`은 `(OSError, JSONDecodeError)`(242)만 잡는다. `UnicodeDecodeError`는 `ValueError` 계열이라 **어느 쪽에도 걸리지 않고 전파된다** — 그러면 status는 비영 종료가 된다. 이는 코드 독해이고 **이번에 재현되지 않았다.** validators 타입 이상 등도 마찬가지로 미재현.
- **정정 서술:** *이번에 재현된 7개 경계에서, 명시적 거부는 `schema_version` 불일치 1건(rc1)이고 나머지 6건은 rc0으로 관용됐다. 관용 범위는 "잡는 예외를 열거한 좁은 집합"이지 "모든 손상"이 아니다.*
- **수용:** `test_brain_store.py:212–221`(`t_torn_line_skip`)은 `home/memory/...`에 torn 행을 쓰고 `save()`를 부르는 **live→save 입력 기대**이고, `t_schema_pin_hardfail`(199–209)도 save 경로다. committed/CI 경로(`status()`)에 대한 요건을 **자체 시험이 직접 반증한다**는 내 문장은 근거 도약이었다. 철회한다.
- **다만 결론은 유지되고, 근거만 바뀐다:** committed 읽기 경로의 관용은 이제 영수증 `malformed_middle_line`(3행 중 1행 소실, rc0)과 `non_object_lines`(rc0, brain 0)이 **직접** 보인다. 따라서 ci.yml:80–83 의 "a bad commit of brain/ can never silently land"는 여전히 과대 주장이다 — 반증 출처는 시험이 아니라 원본 실행이다.

## 5. status 판정 — **수용 (좁혀 재서술)**

"사람 눈으로만 감지 가능"은 철회한다. status는 stdout에 JSON을 내므로 `live_not_in_brain`을 스크립트로 파싱해 divergence 게이트를 세울 수 있다. 정정 서술은 **"rc만으로는 divergence를 판정할 수 없다"**로 좁힌다(`main()` brain_snapshot.py:61–64는 스키마 예외가 아니면 항상 0).

한 가지 덧붙인다 — root의 "count/id 기반 status ≠ payload 동등성"은 pinned 데이터에서 그대로 드러난다: `brain/graduation`은 `doc_code_drift.consecutive_clean 29`인데 `state/graduation-state.json`은 `3`이다. 그런데 status의 graduation 항목은 **개수만**(`live_validators 2 / brain_validators 2`, brain_store.py:322–324) 보고하므로 baseline은 2/2로 동일하게 보인다. JSONL 쪽도 `live_not_in_brain`은 **id 집합 차이**만 센다(317–318) — 같은 id에 다른 본문이면 0이다. status는 **참조·본문 동등성 검사가 아니다.**

## 6. `_graduated()` / 테스트 수 — **수용 (실행수 주장 철회)**

- **철회:** "VALIDATOR_NAMES = 37", "run_units 최소 269 실행". 둘 다 **런타임 미관측**이다. 내가 관측한 것은 (a) `_BUILTIN` 정적 목록 37개 항목(`validators/__init__.py:34–70`), (b) `tests/test_*.py` 파일 **306개**(grep 파일 계수). "≥269 모듈이 현재 발견·실행된다"는 (a)(b)에서 **런타임 `VALIDATOR_NAMES`를 가정하고 유도한 하한**이지 실행 결과가 아니다.
- 정적 근거는 37로 수렴하긴 한다: `graduated_names()`(graduation.py:203–212)는 `TRACKED` 안에서 `graduated is True`인 것만 돌려주는데, 트리의 유일한 live 상태 `state/graduation-state.json`은 두 항목 모두 `"graduated": false`(5행, 77행)다. **그래도 이는 정적 수렴이지 관측이 아니므로 확정하지 않는다.**
- 부차 관측(요구 범위 밖, 후속용): `_save_graduation`(brain_store.py:255–258)은 `consecutive_clean`과 `last_scan_epoch`만 옮기므로 **`graduated`/`ready` 플래그는 brain 스냅샷에 보존되지 않는다.** brain 사본과 live의 필드 집합이 다르다.
- 유지되는 부분: **ci.yml:5–7의 "147", "25/27"과 `run_units.py:5`의 "36 = 35+1", `run_all.py:121,125`의 "35"가 서로 다르다**는 것은 네 문서의 텍스트 대조로 성립한다. 이건 "현재 실행 수" 주장이 아니라 **주석 간 불일치** 주장이다. 정답이 무엇인지는 미관측으로 남긴다. **전체 소스 closure 미완료** 유지.

## 7. tech-stack `_common` 선택 — **수용 (설계 인정 + "영구 미발화" 철회)**

- **수용:** `_common` 단독 활성은 **명시적 설계 선택**이다. 자동 매처 후보에서 빠지는 것과 슬래시 명령/Skill 등록 부재는 별개이며, 내 초기 서술은 그 둘을 붙여 결함처럼 읽히게 했다. 후보 제외 자체를 결함으로 제시한 부분은 철회한다.
- **철회:** "D6 gsd 합집합 정책 영구 미발화". 가지는 cwd·설정에 따라 갈린다. 영수증 8행이 정확히 그것을 보인다 — 루트 cwd: 후보 `["_common","python/lang","python"]`, 존재 디렉터리 `["_common"]`; **`/source/scripts` cwd: `null`(폴백)**. 폴백이 서면 `collect_skill_files`의 `os.walk` 가지(skill_match.py:296–306)가 돌고 D6 합집합이 **산다**. `extensions:` 추가로도 가지가 바뀐다(tech_stack.py:168–170).
- **정정 서술:** *tech-stack.yaml을 갖는 저장소 루트를 cwd로 하는 호출에서만 트리 모드가 서고, 그 호출에 한해 `gsd-*`/`kha-*` 루트 항목이 후보에서 빠진다.* 하위 cwd나 tech-stack.yaml 없는 프로젝트에서는 폴백이다.
- 남은 경계: 위 loader 관측은 **loader 반환값까지**다. `full_skill_match_hook_executed: false`이므로 실제 수집·점수·주입 결과는 **미관측**이며, 내 "96개만 후보" 같은 수치는 코드 독해 유도값이다.

## 8. 플러그인 / 환경 — **수용 (설치 사실 표현 철회)**

- **철회:** "commands/agents/skills만 전달된다". 설치를 하지 않았으므로 완료된 설치 사실로 쓸 수 없다. **정정 서술:** *manifest에 `hooks` 필드가 없고 플러그인 루트에 `hooks/` 디렉터리도 없다(glob 0건). 훅 배선은 `settings.json:102–386`에만 있고 그 명령 문자열은 `python C:/Users/rudtn/.claude/scripts/...` 절대경로다(`CLAUDE_PLUGIN_ROOT` 참조 1건). 이는 **정적 공백**이며, 캐시 설치 위치·훅 연결·버전별 계약은 `platform-references.md:6`이 적은 대로 실제 설치 영수증을 요구한다.*
- **수용:** Ubuntu 단독은 **이 workflow의 범위**에 대한 서술이다. 다른 경로의 Windows 실행 이력을 부정하지 않는다(그 이력을 나는 조회하지 않았다). 정정 서술: *이 workflow는 win32 분기를 실행하지 않는다.*
- **수용:** 상한 미고정은 **정확 재현이 보장되지 않는다**는 뜻이지 어떤 고정 환경에서도 재현 불가는 아니다. 그렇게 좁힌다.
- **path 필터 판단의 범위:** `platform-references.md:5`에 맞춰, brain-only 변경의 자동 검사 공백은 **일반 변경 diff에 한정**한다. 대규모 diff 등 플랫폼 예외와 원격 workflow 실제 실행은 인증하지 않는다. 필수 검사 맥락이라면 "workflow 생략"과 "job 성공"을 구분해야 한다는 단서도 함께 붙인다.

---

## 정정 후 남는 판단 (강도 순)

1. `brain/**`가 트리거 `paths`에 없다 — 일반 변경 diff 한정, 코드+플랫폼 계약 결합 판단. (ci.yml:16–26 vs 66–88)
2. 재현된 7개 경계 중 **명시적 거부는 버전 불일치 1건**, 나머지 6건 rc0. 따라서 ci.yml:80–83 문구는 과대. 반증 출처 = 원본 영수증.
3. status는 개수/id 기반이라 **payload 동등성을 보증하지 않는다**(graduation 29 vs 3이 2/2로 동일 표시). rc만으로 divergence 판정 불가.
4. `skills/`·`agents/`·`commands/`·`atlas/`·`settings.json`이 트리거 밖인데 validator 6개가 그 트리를 스캔.
5. 테스트 수 주석 4곳이 서로 불일치 — 정답값은 미관측.
6. 플러그인 manifest의 훅 공백과 절대경로 배선 — 정적 공백, 설치 미인증.

**미완료 유지:** brain 본문 전량·참조 무결성, full source closure, 현재 회귀 실행 수, 원격 workflow 실행, 실제 플러그인 설치, 실기기·사람·모델 자격, 채택·전체 closure. Zeus CI 1b910a1의 5 job 성공은 이 원본의 검사 강도와 무관하며 근거로 쓰지 않았다.