# Baldrix 배포/설정 정적 리뷰 (pinned cbb5c3e6)

## 0. 읽은 범위 / 안 읽은 범위

**전문 정독:** `.github/workflows/ci.yml`(1–89), `.claude-plugin/marketplace.json`(1–12), `.claude-plugin/plugin.json`(1–6), `.claude/tech-stack.yaml`(1–11), `scripts/cli/brain_snapshot.py`(1–68), `scripts/lib/brain_store.py`(1–333), `scripts/lib/paths.py`(1–258), `scripts/lib/tech_stack.py`(1–195), `scripts/handlers/prompt/skill_match.py`(1–618), `scripts/tests/run_units.py`(1–407), `scripts/tests/run_all.py`(1–304), `requirements.txt`(1–10), `package.json`(1), `.gitignore`(1–152).

**부분만 읽음(정확한 미독 구간):**
- `settings.json` (전체 386행) — 1–80 정독. **81–386 미독**, 그중 102–386의 `"hooks"`/`"command"` 라인만 grep으로 확인.
- `scripts/validators/__init__.py` (전체 123행) — **1–27, 83 미독**, 28–82·84–123 확인.
- `scripts/tests/test_brain_store.py`, `test_tech_stack.py` — **전 구간 미독**, grep 히트 라인만 확인.
- `brain/**` 5개 파일 — **본문 전량 미독**, 행 수·`schema_version` 출현 수만 계수.
- `skills/` 216개 중 100개 경로만 열거(내용 0건 읽음), `agents/`·`commands/`는 파일명만.
- `.gitattributes`, `CLAUDE.md`, `HANDOFF.md` 등 루트 문서 — 미독(지시대로 초기 판단 전 미열람).

---

## 1. CI 트리거 범위 vs 실제로 지켜야 할 자산 — **불일치가 구조적**

트리거 `paths`(ci.yml:16–26)는 `scripts/**`, `get-shit-done/**`, `.github/workflows/ci.yml`, `requirements.txt` 4개뿐이다.

- **`brain/**` 가 트리거에 없다.** 그런데 `brain-snapshot-integrity` 잡(ci.yml:66–88)이 지키려는 대상이 정확히 `brain/` 이다. `brain_store` 문서(brain_store.py:212–213, brain_snapshot.py:13–14)가 규정한 운영 흐름은 "`save` → `brain/` 커밋 → push"다. **`brain/` 만 바뀐 커밋·PR은 CI를 아예 발화시키지 않으므로, 무결성 잡은 자기가 지키는 자산의 변경 시에 실행되지 않는다.** ci.yml:80–83 주석의 "a bad commit of brain/ can never silently land"는 트리거 범위만으로도 성립하지 않는다.
- **`skills/`·`agents/`·`commands/`·`atlas/` 도 트리거에 없다.** 그런데 `run_all` 이 도는 validator 중 `skill_frontmatter`, `skill_quality_axes`, `skill_source_liveness`, `atlas_frontmatter`, `atlas_structure`, `doc_code_drift` 6개가 `SKILLS_DIR/AGENTS_DIR/ATLAS_DIR/COMMANDS_DIR`(paths.py:150–154, `ASSETS_HOME` = `__file__` 유래 = 체크아웃 트리)를 스캔한다. **검사기는 있는데, 검사 대상 트리를 고치는 커밋이 검사기를 부르지 못한다.**
- `settings.json`(추적 대상, .gitignore에 `settings.local.json` 만 제외) 변경도 무검증. 훅 배선 전체가 여기 있다.
- 반대로 필요한 것은 덮여 있다: `merge-back.test.cjs` 는 `get-shit-done/bin/lib/__tests__/` 에 실재하므로 ci.yml:7–8 의 Node 근거는 맞다.

`push.branches: [main]` 과 ci.yml:10–12 의 자체 주석(실 브랜치가 `master` 라 push 트리거 미발화, 실행 이력 2건 전부 pull_request)은 **파일 안에 자백으로 남아 있고 수정되지 않았다.** 나는 원격 브랜치/실행 이력을 확인할 수단이 없으므로 이 부분은 **저자 진술의 인용이지 내 검증이 아니다.**

---

## 2. 무결성 검사기의 실제 강도 — **주장보다 훨씬 약하다**

`brain-snapshot-integrity` 는 `python -m cli.brain_snapshot status` 하나다. `status()`(brain_store.py:305–332)가 실제로 하는 일과 통과시키는 것:

| 실패 유형 | `status()` 거동 | 결과 |
|---|---|---|
| `schema_version` 드리프트 | `_read_jsonl_pinned` L139–144에서 `BrainSchemaError` | **잡힘** (유일하게 잡히는 것) |
| JSON 파싱 불가 라인 | L133–137 `except JSONDecodeError: continue` | **조용히 스킵, 초록** |
| 파일 통째 손실/삭제 | L120 `if not path.is_file(): return []` | **조용히 0건, 초록** |
| 읽기 OSError | L124–126 `return []` | **조용히 초록** |
| `id`/`retracted_id` 누락 레코드 | 검사 없음. `_union_by_key` L189–198에서 `k is None` → **다음 save 때 소리 없이 소실** | 초록 |
| `graduation-state.json` 파손 | `_load_json` L242–243이 `JSONDecodeError` 삼키고 `{"validators": {}}` | **초록** |

게다가 **버전 검사조차 전량에 걸리지 않는다.** pinned `brain/` 실측: 전체 1,182 레코드 중 `schema_version` 보유 912건(l1/insight-index 910, l2/global-facts 2). **`l1/insight-index-retractions.jsonl` 249건과 `l2/global-facts-evidence.jsonl` 20건, 총 269건(22.8%)은 필드 자체가 없어 L140의 `sv is not None` 가드에 걸려 검사 대상에서 빠진다.** 이 269건이 곧 "리트랙션 = 부활 방지"의 근거 데이터인데, 무결성 잡이 손대지 않는 부분이다.

torn-line 스킵은 실수가 아니라 **의도이며 테스트로 고정돼 있다**(test_brain_store.py:221 `"torn-line: JSONDecodeError-skip keeps good record, drops torn (no crash)"`). 즉 "bad commit of brain/ 은 절대 조용히 착지 못한다"는 ci.yml:80–83 주장은 **자기 테스트가 반증한다.** 정확한 주장은 "`schema_version` 을 가진 레코드의 버전 드리프트만 하드페일한다"이다.

부수: CI에서 `memory/` 는 gitignore(.gitignore:105) 되어 없으므로 `status()` 의 live 카운트는 항상 0이고, `state/graduation-state.json` 도 gitignore(.gitignore:88) 되어 live_validators 0이다. **divergence 값 자체는 CI에서 의미가 없다** — 그리고 divergence가 아무리 커도 `status()` 는 exit 0 이다.

---

## 3. 설치/패키징 주장 — **플러그인 메타데이터가 실제 설치를 보증하지 않는다**

`plugin.json`(4행)과 `marketplace.json`(source `"./"`)이 선언하는 것은 이름·버전·설명·소유자뿐이다. 실측:

- 플러그인 루트에 **`hooks/` 디렉터리가 없다**(glob 0건). `plugin.json` 에 `hooks` 필드도 없다.
- 이 하네스의 동작 실체는 `settings.json:102–386` 의 훅 배선이며, 명령 문자열이 **`python C:/Users/rudtn/.claude/scripts/handlers/prompt/skill_match.py` 처럼 절대 Windows 경로로 하드코딩**돼 있다(102–386 중 grep 확인). `CLAUDE_PLUGIN_ROOT` 참조는 파일 전체에서 **1건뿐**이다.
- 결론(범위 한정): **마켓플레이스 설치 경로로는 `commands/`·`agents/`·`skills/` 만 전달되고 훅 층은 전달되지 않는다.** 그리고 `settings.json` 을 수동 복사해도 경로가 `C:/Users/rudtn/...` 에 고정돼 다른 사용자·다른 홈에서 동작하지 않는다. 나는 실제 설치를 실행하지 않았으므로 이는 **선언 파일과 경로 문자열에서 도출한 정적 판단**이며, 설치 성공/실패를 관측한 결과가 아니다.
- 이름 드리프트: 플러그인/마켓플레이스는 `khaness`, 스킬 접두어는 `kha-`, 자체 스택 선언(tech-stack.yaml:1)과 `run_all.py:112` 의 플래그는 `Baldrix`/`BALDRIX_RUNALL_ISOLATED`. 배포 표면과 내부 식별자가 갈려 있다.

---

## 4. OS / 환경 재현성

- 두 잡 모두 `ubuntu-latest` 단독(ci.yml:35, 67). 그런데 코드베이스에는 win32 전용 분기가 load-bearing으로 깔려 있다: `skill_match.py:25–27`(cp949 reconfigure), `brain_snapshot.py:32–34`(cp949 인코딩 회피), `paths.py:16–18, 88–93`(USERPROFILE 분기와 "POSIX 인터프리터에서는 갈린다"는 자체 경고), `run_units.py:235–241`(`mklink /J` vs symlink). **이 분기들의 nt 경로는 CI에서 한 번도 실행되지 않는다.** run_units.py:228–232 주석이 정확히 그 역방향 사고(POSIX 분기 부재로 CI에서 격리가 통째로 꺼져 있었음)를 기록한다 — 반대 방향 사각은 지금 열려 있다.
- `requirements.txt` 는 "Python 3.10+"라고 적는데 CI는 3.13 하나만 돈다(ci.yml:43). 하한 3.10의 호환성은 미측정.
- 의존성이 `PyYAML>=6.0`, `rich>=13.0`, `pytest>=8.0` 개방 상한이고 락파일이 없다. `pip install -r` 만으로는 재현 불가 — 이 저장소가 `skills/_common/toolchain-reproducibility.md` 를 두고 있는 것과 어긋난다.
- 액션이 태그 핀(`@v4`/`@v5`)이라 커밋 SHA 고정이 아니다. `permissions:` 블록이 없어 GITHUB_TOKEN 권한이 리포지터리 설정에 의존하는데, 그 설정은 정적으로 확인 불가 — **미검증으로 남긴다.**

---

## 5. 테스트 수 주석 — **현재 트리와 맞지 않음 (역사적 수치를 현재 테스트로 등치 금지)**

ci.yml:5–7의 `run_units 147`, `run_all 25/27` 은 실측과 다르고, 저장소 내부에서도 서로 어긋난다:

- `scripts/tests/test_*.py` **실측 306개**. `run_units._discover_unit_tests`(run_units.py:48–62)는 이 중 이름이 VALIDATOR_NAMES에 든 것만 제외하므로 **최소 269개**를 발견한다. ci.yml의 147은 약 절반 수준의 낡은 값이다.
- `validators/__init__.py:33–71` 의 `_BUILTIN` 은 **37개**(34–70행, 1행 1엔트리). `_graduated()` 는 flip 전까지 비어 있으므로(주석 28–32) 현재 `VALIDATOR_NAMES` == 37.
- 같은 사실에 대해 저장소 안에 네 개의 값이 공존한다: ci.yml "25/27", `run_units.py:5` "36 entries: 35 builtin + 1 graduated", `run_all.py:121,125` "판정 35건", 실제 37. **`run_all` 은 `len(VALIDATOR_NAMES)` 를 런타임에 출력하므로 코드는 옳고 주석 4곳이 전부 낡았다.**
- 판정 강도 관련 사실(주장이 아니라 코드): `run_units.main`(387, 403)은 SKIP을 실패로 세지 않고 `0 if not failed` 를 돌린다. `[SKIP-SUITE]`(368–375)와 `_check_skip`(357–360)로 빠진 모듈이 몇 개인지는 **실행 없이는 알 수 없으므로 미측정**이다. 즉 "0-fail"은 "0 실패"이지 "N건 실행됨"이 아니다.

---

## 6. tech-stack 선택 vs 폴백 — **주석 주장은 성립, 다만 부작용이 문서화되지 않았다**

`.claude/tech-stack.yaml` 은 `stack.language: python` 하나. 추적하면:

1. `load_tech_stack`(tech_stack.py:157–172) → `_candidate_paths("python","","")`(51–77) → `active = ['_common', 'python/lang', 'python']`, `len(active) > 1` 이므로 **None 폴백으로 안 떨어진다.** ✅ 파일 7–9행 주장대로.
2. 소비자 `collect_skill_files`(skill_match.py:288–295)가 `os.path.isdir` 필터. **실측: `skills/python*` 0건**이므로 `python/lang`·`python` 은 탈락하고 `_common` 만 남는다. ✅ 3–6행 주장대로.

주장은 근거를 갖는다. 다만 **주석이 말하지 않는 대가**가 있다:

- 트리 모드는 `active_paths` 에 든 디렉터리만 훑는다. 따라서 `skills/` 루트의 **`kha-*` 74개 `SKILL.md`, `gsd-skill-promotion-runbook`, `register-to-artifacthub`, `_outpos/` 가 전부 스캔에서 빠진다.** `collect_skill_files` 독스트링(skill_match.py:262–268)이 규정한 **D6 "gsd-* ∪ _gsd/" 합집합 정책은 폴백(`else`, 296–306) 가지에만 구현돼 있어 이 저장소에서는 영구 미발화**다.
- tech-stack.yaml:6 의 "이것이 이 저장소에 정확한 활성 집합이다"는 따라서 **"`_common` 96개만이 매처 후보"라는 선택**이지, 하네스 자체 스킬을 포함한다는 뜻이 아니다. 그 선택이 옳다는 근거(kha-* 대부분이 매처 필드 없는 슬래시 명령이라 점수 0)는 skill_match.py:280–283에 있으나 **폴백 모드에서 측정된 값**이고, 트리 모드 전환 후 재측정 기록은 이 4파일 어디에도 없다.
- `.claude/**` 가 CI 트리거에 없으므로 이 파일을 잘못 고쳐 폴백으로 떨어뜨려도(예: `language:` 제거 → 172행에서 None) CI는 발화하지 않는다. `test_tech_stack.py:199–204` 가 그 케이스를 테스트하지만, 트리거되지 않으면 돌지 않는다.

---

## 7. 사용자 SDD / 실수용 관점

- `brain_snapshot` CLI 자체는 계약이 명료하다. `--merge` 파싱(brain_snapshot.py:55)은 `argv[1:]` 만 보므로 `restore` 위치 고정이고, 미지 인자는 조용히 무시된다(예: `restore --merg` 오타 → 경고 없이 non-merge 실행). 47행의 화이트리스트는 첫 인자에만 걸린다.
- `status` 는 divergence가 커도 exit 0 이라 **오퍼레이터가 "저장 안 된 상태"를 스크립트로 감지할 수 없다.** 사람 눈으로 JSON을 읽어야 한다.
- `restore` 는 수동이라고 문서가 명시(2–17행)하며, 그 자체는 INV-save와 일관된다.

**나는 다음을 주장하지 않는다:** 이슈 종결 여부, 라이선스 적합성, 특정 OS/모델/사람의 능력, 채택률, 그리고 "플러그인이 설치된다/안 된다"의 실측. 3절은 선언 파일과 경로 문자열에 한정된 정적 추론이고, 1절의 브랜치·실행 이력 부분은 ci.yml 저자 주석의 인용이다.

---

## 요약 (심각도 순)

1. **`brain/**` 가 CI 트리거 밖** → 무결성 잡이 자기 대상의 변경 시 실행되지 않음. (ci.yml:16–26 vs 66–88)
2. **무결성 검사가 사실상 `schema_version` 드리프트 단일 검사**이고, 그마저 pinned 데이터의 77.2%(912/1182)에만 적용. 파싱 실패·파일 소실·graduation 파손은 전부 초록. ci.yml:80–83 주장 과대.
3. **`skills/`·`agents/`·`commands/`·`atlas/`·`settings.json` 이 트리거 밖**인데 validator 6개가 그 트리를 검사 대상으로 삼음.
4. **플러그인 패키지에 훅 층이 없고**, 훅 명령이 단일 머신 절대경로에 고정 — 배포 메타데이터와 실제 동작 사이 간극.
5. **테스트 수 주석 4곳이 전부 낡음** (147 vs ≥269, 25/27·36·35 vs 37).
6. **CI가 ubuntu 단독**이라 win32 전용 분기(cp949·mklink·USERPROFILE) 무커버리지. 의존성 상한 미고정.
7. tech-stack 선택은 근거 있으나, **D6 gsd 합집합 정책 영구 미발화**와 `kha-*` 전량 후보 제외라는 대가가 미문서화.