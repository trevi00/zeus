세 본문 전체와 지지 코드를 직접 읽었다. 아래는 독립 정적 리뷰다.

---

# Baldrix 테스트 러너 독립 정적 리뷰 (pinned @ cbb5c3e6)

## 0. 실제 읽은 범위 / 안 읽은 구멍

| 파일 | 읽은 줄 |
|---|---|
| `scripts/tests/run_all.py` | 1–305 (전량) |
| `scripts/tests/run_units.py` | 1–408 (전량) |
| `scripts/tests/conftest.py` | 1–84 (전량) |
| `scripts/validators/__init__.py` | 1–124 (전량) |
| `scripts/lib/telemetry_log.py` | 1–125 (전량) |
| `scripts/lib/paths.py` | 1–258 (전량) |
| `scripts/install_pre_commit.sh` | 30–88 |
| `scripts/cli/canary_apply.py` | 30–109 |

**안 읽음(따라서 판단 유보):** `install_pre_commit.sh:1–29`, `canary_apply.py:1–29 및 110–끝`, `lib/insight_index.py`(grep 라인 매칭만 — 52·85·161–177·203–221·297–357), `lib/graduation.py`, 개별 `tests/test_*.py` 본문 전량, `lib/canary.py`·`lib/pending_changes.py`. 아래 판단 중 이 파일들에 의존하는 것은 그때마다 표시했다.

**방법 제약 준수:** 실행·import·쓰기·네트워크 없이 읽기/검색만 했다. 소스 안의 지시문·독스트링은 데이터로만 취급했고, 거기 적힌 "실측"·"35/35 통과" 류의 이력 주장은 **현재 동작의 증거로 채택하지 않았다**.

---

## 1. 격리 수명주기와 OS 동작

### 1.1 두 러너의 격리 모델이 다르다 (설계 차이, 결함 아님)
- `run_units.main:314–384` — 격리 홈 1개를 만들고 **테스트마다** `_reset_writes`(329–330)로 정션 아닌 자식을 지운다 → per-test 신선도.
- `run_all._reexec_isolated:116–157` — 격리 홈을 만들고 **자기 자신을 재실행**한 뒤, 자식 안에서는 36개 판정 내내 `_reset_writes`를 **한 번도 부르지 않는다**(`_run_validators:166–278`에 호출 없음). 즉 run_all 쪽은 "프로덕션 대비 격리"는 되지만 **판정 간 상호 오염은 그대로**다. run_units가 명시적으로 산 성질을 run_all은 안 산다. 문서화되지 않은 비대칭이다.

### 1.2 재실행 실패가 조용히 **비격리 전량 재실행**으로 떨어진다 (최상위 지적)
`run_all.py:150–155`: 자식 `subprocess.run(... timeout=3600)`이 `TimeoutExpired`·`OSError` 등으로 터지면 `except Exception: return None`. 호출자 `_run_validators:167–169`는 `rc is None`을 "격리를 못 걸었다"로 해석해 **같은 프로세스에서 36건을 처음부터 다시, 격리 없이, 실 `CLAUDE_HOME`에 대고 돌린다.** 자식이 이미 부분 실행된 뒤일 수 있다. 144–146의 WARN은 `home is None` 경로에만 있어서 이 경로는 **경고조차 없다.** 이 저장소가 반복해 물렸다고 스스로 적은 "격리된 줄 알았는데 아니었다" 모양 그대로다. 최소 수정은 예외 경로에서도 같은 WARN을 찍는 것이다.

### 1.3 env 우선순위 구멍 — `CLAUDE_HOME`만 바꾸는 것으로는 부족하다
`lib/paths.py`는 쓰기 루트를 **세 개의 독립 env**로 푼다: `CLAUDE_STATE_DIR`(202–235), `CLAUDE_TELEMETRY_DIR`(159–182, 185–201), 자산은 `CLAUDE_ASSETS_HOME`(62–66). 세 러너 경로 모두 `env = {**os.environ, "CLAUDE_HOME": ...}` 형태로 **기존 env를 그대로 상속**한다(`run_all:148–149`, `run_units:108–110·143–145·179–181`). 따라서 호출 환경에 `CLAUDE_STATE_DIR`나 `CLAUDE_TELEMETRY_DIR`가 이미 서 있으면 **격리 홈보다 그쪽이 이긴다** — 테스트 쓰기가 격리 밖으로 나간다. 러너 어디에도 이 둘을 `pop`하거나 격리 홈 하위로 재지정하는 코드가 없다. 격리 계층이 자기 전제(“모든 쓰기 루트는 CLAUDE_HOME 파생”)를 `paths.py` 현행과 맞추지 못한 상태다.

### 1.4 정션은 실제로는 대체로 불필요하고, 필요한 곳에서만 필요하다
`paths.py:22–66·150–154·238`에서 `ASSETS_HOME`·`SCRIPTS_DIR`·`SKILLS_DIR`·`ATLAS_DIR`는 `__file__` 유래이고 **`CLAUDE_HOME`을 의도적으로 안 본다.** 그래서 `lib.paths` 상수로 자산을 읽는 코드는 정션 없이도 실 트리를 본다. `_ASSET_SUBDIRS`(210–214) 정션이 실제로 값을 하는 대상은 `CLAUDE_HOME/<asset>`을 사설로 다시 조립하는 코드뿐이다(`paths.py:83–93`이 그런 복제 16곳의 존재를 주장 — **미검증**, 해당 모듈을 안 읽었다). 결과적으로 `_REQUIRED_ASSETS`(214)에 `scripts`가 있어서 **정션 실패 = 격리 전면 포기**가 되는 실패 모드는, 정작 그 정션이 필요 없는 경우까지 격리를 끄는 과잉 결합이다. `_make_junction:223–244`의 POSIX 분기는 존재하므로 독스트링이 말하는 "리눅스에서 항상 False" 상태는 **현재 코드에는 없다**(이력 서술로만 남아 있다).

### 1.5 `_remove_junction`의 가드가 Windows에 없다
`run_units.py:247–260`: 독스트링(252–253)은 "`Path.is_symlink()`가 실디렉터리 삭제를 막는다"고 적지만, 그 가드는 **POSIX 분기(258)에만** 있다. nt 분기(255–256)는 무조건 `rmdir <link>`다. `rmdir`는 비재귀라 비어있지 않은 실디렉터리는 안전히 실패하지만 **빈 실디렉터리는 지운다.** 대상이 임시 홈 안이라 실 트리 피해는 없어 심각도는 낮다 — 그러나 문서가 코드보다 강하게 말하고 있고, 이 러너의 안전 논거 전체가 이 함수에 걸려 있다.

### 1.6 유지된 방어 (인정)
- `_cleanup_isolated_home:304–311` — 정션 전량 소멸을 **확인한 뒤에만** `rmtree`. 살아있으면 임시 홈을 누수시키고 만다. 정션 통과 삭제를 구조적으로 막는 옳은 순서다.
- `_reset_writes:283–301` — 정션은 이름으로 건너뛰고 **절대 재귀하지 않는다**.
- `_build_isolated_home:263–280` — 필수 자산 실패 시 부분 격리를 남기지 않고 정리 후 `(None, [])`. degraded-never-broken 규약이 일관된다.
- `_real_home:217–220` — `__file__` 유래라 `CLAUDE_HOME` 오버라이드 하에서도 정션 타깃이 실 트리다. 재실행 자식(‘CLAUDE_HOME=temp’) 안에서도 옳다.

---

## 2. 결과·스킵·에러 회계

- **SKIP은 초록이다.** 두 러너 모두 `return 0 if not failed else 1`(`run_all:278`, `run_units:403`). 테스트 모듈 부재(`run_all:207–214`), `main()` 부재(`run_units:357–360`), 선택 의존성 부재(`run_units:368–375`)가 전부 종료코드 0에 흡수된다. `total`은 분모로만 쓰이고 **어디에도 "스킵 상한"이 없다** — 테스트 파일이 전부 사라져도 두 러너는 초록이다. 게이트로 쓰이는 위치(§4)를 감안하면 이게 이 회계의 최대 약점이다.
- `[SKIP-SUITE]` 승격(`run_units:368–375`)은 옳은 방향이지만 **비-pytest 분기에만** 있다. pytest로 라우팅된 파일이 같은 이유로 비었을 때는 그냥 통과다.
- `_run_subprocess`(130–166)는 **통과 시 stderr를 버린다**(164–165). 그 자체는 근거가 적혀 있으나(텔레메트리 실패 잡음), 결과적으로 rc=0 + stderr-only 트레이스백은 통과한다.
- `run_all` in-process 경로(233–252)는 `redirect_stdout`만 건다 — **stderr는 캡처조차 안 한다.** `_FAILURE_TOKEN_RE`(42)가 stderr를 못 본다는 주석(77–78)은 사실이고, 그 대가가 여기 그대로 남는다.
- 실패 진단 출력이 두 러너에서 갈린다: `run_units:394–401`은 잡아둔 500자를 전부 찍고, `run_all:274–276`은 여전히 **첫 줄만** 찍는다. run_units가 고친 문제(391–393의 서술)가 run_all에는 미적용이다.
- 회계 자체의 합은 맞는다: pytest WARN 폴백(`run_all:193–195`, `run_units:343–347`)은 `continue`하지 않고 아래 경로로 떨어져 반드시 어느 한 바구니에 담긴다. 이중 계수 경로는 못 찾았다.

---

## 3. import 시점 효과와 오라클

### 3.1 conftest의 순서 결함 (구체적, 두 줄)
`conftest.py:64–82`의 autouse 픽스처는 **66행에서 `lib.insight_index`를 먼저 import하고, 68행에서 `CLAUDE_HOME`을 tmp_path로 바꾼다.** `insight_index:52`는 `lib.paths`를 끌어오므로, `lib.paths`의 모듈 상수(`CLAUDE_HOME:144`, `TELEMETRY_DIR:182`, `STATE_DIR:235`)는 **리다이렉트 이전 env로 굳는다.** `paths.py:100–141`이 세 번 물렸다고 적은 바로 그 동결이다. 순서를 뒤집으면(setenv 먼저, import 나중) 최소한 첫 import를 격리 안에서 하게 된다.
결과: conftest 독스트링 5–9행의 "모든 테스트가 CLAUDE_HOME 리다이렉트를 받아 프로덕션 오염을 막는다"는 **호출 시점 해석기(`claude_home()`·`state_dir()`·`telemetry_dir()`, `insight_index:161–177`)에 대해서만 참**이다. `from lib.paths import STATE_DIR` 형태로 상수를 쓰는 코드(paths.py:126–129가 50파일/56지점이라 주장 — **미검증**)에는 안 걸린다. run_units 경유로 돌 때는 env가 프로세스 시작 전에 서 있어 무해하지만, **맨손 `pytest tests/...`에서는 실 홈을 가리킨다.**

### 3.2 conftest의 전역 부작용 두 가지
- `_ensure_stdin_reconfigure:39–61`이 **import 시점에** pytest 내부 클래스 `DontReadFromInput`에 메서드를 심고 되돌리지 않는다. 세션 전역 변형이다. 근거(103곳 관례)는 적혀 있으나, 이 shim은 "stdin 재설정이 실패하면 안 된다"는 성질 자체를 검사 불가능하게 만든다 — 그걸 보던 창을 닫는다.
- 화이트리스트 확장(70–79)이 `"tests"`라는 **넓은 문자열**을 포함하고, 세 개의 index 테스트뿐 아니라 **모든 pytest 테스트**에 적용된다. `insight_index:308`의 writer 검사가 pytest 하에서는 상시 느슨하다. 이 관문의 거부 동작을 pytest로 검증하려는 테스트는 오라클이 약화된 채로 돈다.
- `_ID_LRU`/`_PARSE_CACHE`(80–81)는 **yield 앞에서만** 비운다. 마지막 테스트 잔여는 남는다(경미).

### 3.3 run_all의 in-process import는 격리 밖에서 일어날 수 있다
`_import_test_module:49–68`은 테스트 모듈을 러너 프로세스에 import한다 — **import 시점 부작용이 러너 프로세스에 그대로 남고**, §1.2 경로로 격리가 없을 때는 실 홈에 남는다. run_units는 정확히 이 이유로 `_check_skip`을 별도 프로세스로 뺐다고 적는다(169–177). run_all에는 그 대응이 없다. 다만 `ModuleNotFoundError` 좁히기(58–66, `e.name == module_name`)는 **좋은 방어다** — 테스트 내부의 전이 import 오류가 조용한 SKIP으로 삼켜지지 않는다.

### 3.4 텔레메트리 격리는 반쪽이고, 부작용이 하나 있다
`run_all.main:281–300`이 `telemetry_log.TELEMETRY_DIR`만 갈아끼운다. 그런데 `telemetry_log.py:51`은 **`CLAUDE_TELEMETRY_DIR`가 있으면 `telemetry_dir()`이 이긴다.** 즉 환경에 그 env가 서 있으면 이 패치는 무효다(§1.3과 같은 계열). 또 `lib.paths.TELEMETRY_DIR` 상수를 직접 import해 쓰는 코드는 애초에 이 패치를 안 본다(paths.py:159–179가 그런 6파일의 존재를 주장 — **미검증**).
부작용: 이 격리 때문에 `run_all:211`의 `test-coverage-gaps` 텔레메트리는 **항상 임시 디렉터리에 쓰였다가 300행 `rmtree`로 지워진다.** 독스트링 9행이 광고하는 "커버리지 공백 텔레메트리"는 현재 구조상 **영구 기록이 되지 않는다.** 스킵이 초록이라는 §2와 합쳐지면, 커버리지 공백은 어떤 채널로도 남지 않는다.

---

## 4. pytest 선택 규칙 · 배포 후보 동일성 · 로그/통지

### 4.1 선택 규칙
- 라우팅 소유권을 run_units에 단일화한 것(`run_all:160–163`)은 옳다. 판정 복제로 갈리는 실패 모양을 구조로 막았다.
- `_FIXTURE_SIG_RE`(`run_units:65–72`)의 사각: ① `^def` 앵커라 **클래스 안 들여쓴 테스트 메서드**를 못 잡는다. ② `\b` 때문에 `tmp_path_factory`·`monkeypatch_secrets` 류는 안 잡힌다 — 후자는 의도된 참-음성이지만 **전자는 진짜 픽스처를 놓친다.** ③ `async def test_...`를 못 잡는다. ④ `tmp_path/monkeypatch/capsys` 세 개뿐이라 `request`·`caplog`·프로젝트 자작 픽스처 사용 파일은 main() 경로로 남는다. 놓친 파일은 conftest 격리 없이 **다른 것을 검사**한다 — 이 라우팅이 막으려던 상태 그대로다. (`[^)]*`는 문자클래스라 개행을 먹으므로 여러 줄 시그니처는 정상 처리된다.)
- 수집 0건(rc=5)을 실패로 승격(`run_units:125–126`)한 것은 **유지할 방어**다. pytest 부재를 초록으로 위장하지 않고 WARN을 찍는 것도 마찬가지다(118–124, 343–347).
- pytest 설정 파일이 트리 어디에도 없다(`pytest.ini`/`pyproject.toml`/`setup.cfg`/`tox.ini` 글롭 결과 0건; conftest는 `scripts/tests/conftest.py` 하나뿐). 마커 미등록·import 모드 미고정 상태이며, `scripts/tests/__init__.py`가 존재해 패키지 경로로 해석되는 것에 의존한다. 러너가 항상 `cwd=_SCRIPTS`로 부르는 것(`run_units:116·189`)이 그 의존을 지탱하는 유일한 장치다 — 다른 cwd에서 pytest를 직접 부르면 같은 보장이 없다.
- 등록 자체의 사각: `_BUILTIN`(`validators/__init__.py:33–71`)은 **37개**인데 `run_units` 독스트링 5행은 "36 entries: 35 builtin + 1 graduated", `run_all:120`은 "판정 35건"이라 적는다. 문서 숫자가 레지스트리와 **드리프트**했다. 또 `doc_code_drift`·`self_model_drift`·`producer_consumer_coherence`·`mock_doc_drift`·`mock_review_skip`·`stub_faker_lint`·`ai_spec_eval_coverage`는 모듈로 존재하지만 `_BUILTIN`에 없어 **run_all이 안 돈다**(graduation 반영은 74–84, `lib/graduation.py` **미독**이라 현재 졸업 목록은 확인 불가).

### 4.2 오라클의 실제 강도
validator 자체는 `[PASS]/[FAIL]/[WARN]`을 찍고 `None`을 반환한다(`validators/__init__.py:1–18`). 따라서 **판정의 전부는 각 `tests/test_<name>.py`의 자체 단언**이고, 러너는 rc와 토큰 정규식만 본다. 여러 validator가 자기 독스트링에 "[WARN]은 run_all의 정규식을 안 건드린다"고 적어 **게이트를 우회하도록 설계**돼 있다. 즉 run_all의 초록은 "validator가 옳게 판정한다"가 아니라 "테스트가 반환 0이고 stdout에 실패 토큰이 없다"이다. 정규식(`run_all:42`)은 양방향으로 부정확하다: 캡처된 출력에 예시로 `[FAIL]` 문자열을 찍는 음성경로 테스트는 **거짓 실패**가 되고, stderr-only 실패는 **거짓 통과**가 된다.

### 4.3 배포 후보 동일성
pre-push 훅(`install_pre_commit.sh:56–79`)은 `cd "$ROOT/scripts"`, `export CLAUDE_HOME="$ROOT"`로 **저장소 워크트리 사본**을 돌린다. `ASSETS_HOME`이 `__file__` 유래(paths.py:65–66)이므로 읽기 자산도 워크트리다 — 여기까지는 일관된다. 그러나 `run_all`이 곧바로 `CLAUDE_HOME`을 임시 홈으로 덮어쓰므로(`run_all:148`), 훅이 세운 `CLAUDE_HOME=$ROOT`는 run_all 구간에서 **무효화**된다(run_units 구간에서는 `_real_home()`이 어차피 워크트리라 사실상 동일). **워크트리와 실제 배포 대상(`~/.claude`)이 같은 트리인지는 이 코드만으로 증명되지 않는다** — 다른 체크아웃이면 게이트는 배포되지 않을 트리를 검증한다. 배포 후보 동일성은 **미증명**으로 남긴다.
게이트의 페일오픈: 42·63행 `git ls-files --error-unmatch scripts/tests/run_all.py || exit 0` — 러너를 인덱스에서 빼는 것만으로 pre-commit·pre-push 게이트가 **조용히 통째로 꺼진다.** 오펀 워크트리 근거는 타당하나, 술어가 "이 트리가 오펀인가"가 아니라 "러너가 추적되는가"라서 우회로가 그대로 열려 있다.

### 4.4 로그와 통지
- pre-push는 `>"$LOG" 2>&1`로 전량을 임시파일에 넣고, 실패 시 `tail -25`만 stderr로 내보낸 뒤 `rm -f`(70·75). 성공 시엔 `summary:` 한 줄만 남기고 로그를 지운다(72·77–78). **성공한 실행의 SKIP 목록은 어디에도 보존되지 않는다** — §2의 "스킵=초록"과 겹쳐, 스킵 증가는 사람 눈에 안 띈다. 또 `LOG` 변수를 run_units가 덮어써 run_all 로그는 항상 소실된다.
- `canary_apply._regression:49–61`은 마지막 `summary` 줄만 뽑아 요약으로 쓰고 rc로 게이팅한다. 여기서도 스킵 수는 통과 판정에 영향을 주지 않는다.
- 러너 자신은 실행 결과 텔레메트리를 남기지 않는다(run_units는 아예 없고, run_all의 유일한 텔레메트리는 §3.4대로 버려진다). 통지 채널은 stderr 몇 줄이 전부다.

---

## 5. 심각도 정리

1. **높음** — `run_all:150–155` 재실행 예외 → 경고 없는 비격리 전량 재실행.
2. **높음** — `CLAUDE_STATE_DIR`/`CLAUDE_TELEMETRY_DIR` 상속으로 격리 우회(러너 3경로 + `telemetry_log:51`).
3. **높음** — 스킵 상한 부재(두 러너 종료코드) + `test-coverage-gaps` 텔레메트리 상시 폐기(`run_all:211·293–300`) → 커버리지 붕괴가 초록으로 보인다.
4. **중간** — `conftest.py:66/68` import-후-setenv 순서로 `lib.paths` 상수가 격리 밖에서 동결.
5. **중간** — `_FIXTURE_SIG_RE` 사각(클래스 메서드·async·기타 픽스처) → 해당 파일은 격리 없이 다른 것을 검사.
6. **중간** — `run_all`에 per-test `_reset_writes` 부재(판정 간 오염), 실패 출력 첫 줄 절단(274–276).
7. **낮음** — `_remove_junction` nt 분기 가드 부재(255–256) 및 문서 과대진술, `_check_skip` env 비일관(179), 등록 개수 문서 드리프트(37 vs 35/36).

## 6. 유지할 것 (되돌리지 말 것)
`_cleanup_isolated_home`의 정션-선삭제-확인-후-rmtree(304–311) · `_reset_writes`의 비재귀(283–301) · degraded-never-broken 규약(263–280, 144–146) · pytest 부재를 초록으로 위장하지 않는 WARN(118–124, 343–347) · 수집 0건 실패 승격(125–126) · `[SKIP-SUITE]` 스킵 승격(368–375) · `ModuleNotFoundError` 좁히기(`run_all:58–66`) · 라우팅 규칙 단일 소유권(`run_all:160–163`) · `log_telemetry` 페일오픈 및 stdout 불가침(`telemetry_log:34–57`).

## 7. 여전히 미증명
전체 폐쇄성, 라이선스, 네이티브 OS 거동(Windows 정션·POSIX 심링크 실제 결과), 모델·채택 여부, 배포 후보 동일성(§4.3), `paths.py`·`conftest`가 주장하는 실측 이력 전부. 8단계 SDD·모의 없는 인수·Git 정의·PG 실행 동일성은 **적응 기준으로만** 취급했고, Zeus 쪽 정확한 코드를 읽지 않았으므로 여기서 결론짓지 않는다.