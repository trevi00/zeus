## 검토 범위 (실제 읽은 것)

**대상 11개 전량 정독** (`.runtime/absorption/sources/baldrix/pinned/scripts/engine/`):
`__init__.py`(37L) · `cli.py`(72L) · `debate.py`(91L) · `dispatch_retry.py`(70L) · `external_jury.py`(280L) · `inventory_scan.py`(277L) · `jury_advisory.py`(171L) · `orchestrator.py`(655L) · `prompts.py`(73L) · `ralph.py`(234L) · `trigger_summary.py`(214L) — 합계 약 2,174행.

**추적한 동일 pinned tree 내 필요 구간만**: `lib/event_store.py`(전문) · `lib/completion_gate.py`(전문) · `lib/providers/__init__.py`+`openai.py`(전문) · `lib/model_router.py`(93–126) · `lib/telemetry_log.py`(23–49) · `lib/paths.py`(grep) · `lib/breakers/{config,composite}.py`(grep) · `handlers/stop/autopilot_continue.py`(560–689) · `tests/run_units.py`(300–408, grep) · `tests/test_jury_advisory.py`(grep) · `.github/workflows/ci.yml`(전문) · `commands/harness-debate.md`(55–61) · `validators/producer_consumer_coherence.py`(1–45).

**미이행/불가**: 원본 실행 0, 쓰기 0, 네트워크 0, credentials·live 상태 접근 0. **바이트 총계 80,138은 확인 못 했다** — 실행 없이 stat 할 수단이 없어 행수로만 범위를 보고한다. source의 AGENTS/CLAUDE/주석 지시는 전부 데이터로만 취급했다(그 자체가 이 보고의 검증 대상).

---

## 1. `__init__.py` — 의미와 실재

패키지 재수출 5+3개. 문서화된 "레거시 `engine.convergence` 제거" 서사는 코드로 확인 불가(제거된 것은 읽을 수 없다). 실질적으로 이 파일이 하는 유일한 일은 `debate`/`prompts`를 import 시점에 강제 로드하는 것. **방어 없음, 위험 없음.**

## 2. `cli.py` — 사후 조회 전용

`list`/`show`/`last-verdict` 3개. `_show`는 이벤트 없으면 exit 1. **정적 반례 없음.** 다만 모듈 docstring이 "orchestration에 쓰이지 않는다"고 명시하고, `engine/__init__.py`는 "결정론적 수렴 규칙은 `cli.debate_converge_check`가 소비한다"고 쓰는데 — **그 `cli`는 이 파일(`engine.cli`)이 아니라 별도 최상위 `scripts/cli/` 패키지다.** docstring 안에서 같은 이름 두 개가 섞여 있어 오독을 유발한다(문서 결함, 코드 무해).

## 3. `debate.py` — 독립검수의 실제 강도

- `is_fast_path_eligible`: Critic **우회** 규칙. `critic_feedback` 없음 + `open_questions` 없음 + strict-design 키워드 → **1세대에서 비평 없이 Architect로 직행.** 즉 "독립 검수"는 조건부로 꺼진다. 이 판정의 입력 `proposal.get("open_questions")`는 **Planner 자신이 쓴 필드**다 — 검수를 건너뛸지를 피검수자가 결정한다. 이건 구조적 self-grading이고, 정적으로 반례가 필요 없다: `{"open_questions": []}`를 내면 항상 우회된다.
- `log_similarity_backup`: 스스로 "backup signal — not used for convergence"라고 이벤트에 적는다. 즉 유사도는 **아무 것도 막지 않는다.**
- `load_history_snapshots`: docstring은 "현재 gen 제외"라 하지만 코드는 `store.replay()` 전량에서 verdict를 긁는다 — **호출 시점에 이번 gen verdict가 이미 append돼 있으면 포함된다.** `log_similarity_backup(history_including_current)`의 인자명이 그 사실을 인정하므로 실호출은 아마 맞겠지만, **docstring과 코드가 서로 다른 계약을 말한다.**

## 4. `dispatch_retry.py` — 재시도

순수하고 주입 가능(`sleep_fn`/`jitter`). `max_attempts`가 총 시도 수라는 계약도 코드와 일치(`for k in range(attempts)`, `k >= attempts-1`이면 재raise).

**정적 반례 1 (실질적):** `except BaseException` + `classify` 분류. `external_jury._classify_jury`는 `_PERMANENT_EXC` 목록에 없으면 전부 `transient`다. **`KeyboardInterrupt`와 `SystemExit`은 목록에 없다** → Ctrl-C가 "일시적 장애"로 분류돼 backoff sleep 후 재시도된다. 운영자 중단이 최대 3회 재시도 + 지연으로 삼켜진다. 수정은 한 줄: `_PERMANENT_EXC`에 `KeyboardInterrupt, SystemExit` 추가하거나 `except Exception`으로 좁히기.

## 5. `external_jury.py` — 정체성·모집단·모델자격의 핵심 결함

**모집단(누가 배심인가):**
- `_tally`는 파싱 성공한 표만 센다. `agreement = votes[consensus]/total`의 `total`도 **파싱된 표만의 합**이다. → 배심 3명 중 2명이 non-JSON을 뱉으면 **1표로 `agreement=1.0`, "만장일치"**가 된다. 실패자(`failures`)와 파싱실패자는 분모에서 사라진다. **정족수(quorum) 하한이 코드에 없다.** "PANEL — N vendors, majority rule"이라는 docstring은 N≥2를 보장하지 않는다.
- `single` 모드는 첫 성공자 1명 → `agreement`는 항상 1.0. 이 값이 그대로 원장 이벤트에 실린다.

**정체성(그 배심이 누구인가):**
- `default_members()`(jury_advisory)가 만드는 멤버는 `model=None`. `OpenAIProvider.ask`는 `model=""`이면 `-m`을 안 붙이고 응답 model을 문자열 **`"codex-default"`** 로 기록한다. 즉 원장에 남는 배심원 정체성은 `openai/codex-default` — **실제로 어떤 모델이 판단했는지 기록되지 않는다.**
- `is_available()`은 `shutil.which("codex") is not None`, 그게 전부다. **PATH에 `codex`라는 이름의 실행파일이 있으면 "비-Claude 벤더"로 인정된다.** 그 CLI가 무엇으로 백엔드되는지(로컬 설정에 따라 Claude 계열일 수도) 확인하는 코드가 없다. "cross-vendor bias 제거"라는 이 모듈의 존재 이유가 **PATH 이름 하나에 걸려 있다.**
- `_resolve_model`는 `m.model == "auto"`일 때만 라우팅한다. `lib/model_router.DEFAULT_MODEL_IDS`의 anthropic 항목은 `claude-sonnet-4-6`/`claude-opus-4-7`로 **현행 모델 세대와 어긋난다**(Zeus 환경 기준 최신은 Claude 5 계열/Haiku 4.5). 다만 advisory 경로는 `auto`를 안 쓰므로 **현재는 사문**이다 — 켜는 순간 잘못된 모델 id로 나간다.

**차단기/예산:**
- `call_budget_sec=20.0`은 **완전히 미사용 인자**다. docstring은 "max_attempts가 wall-time을 초 단위로 묶으니 예산이 걸릴 일 없다"고 단언하는데, `OpenAIProvider.ask`의 subprocess timeout은 **300초**다. 3회 시도면 **최악 900초 + backoff**. "초 단위"라는 근거 문장이 사실과 반대다. 이 함수는 `jury_advisory`를 통해 토론 루프 안에서 호출되도록 설계돼 있다.
- `_dispatch_with_breaker`의 `finally`: `BaseException`(KeyboardInterrupt 등)이 `except Exception`을 통과해 밖으로 나갈 때도 `outcome="failure"`가 남아 **record_failure**가 찍힌다 → 운영자 중단이 벤더 장애로 원장에 기록되고 차단기를 민다.
- "permanent 후 record_success"(도달했으니 available) 논리는 일관되고 방어적으로 타당하다. 이건 실재하는 설계다.

## 6. `jury_advisory.py` — "빌드했으나 미배선"의 한 층 이동

`ADVISORY_ONLY=True`, 페이로드에 `ontology_snapshot`/`sha`/`converged` 없음, 예외 전량 흡수 — 계약은 코드와 일치한다. 여기까지는 실재하는 방어다.

**그러나 호출자가 없다.** pinned tree 전체에서 `jury_advisory(` 호출은 `tests/test_jury_advisory.py`뿐이고, 유일한 "프로덕션 호출자"는 `commands/harness-debate.md:61`의 **산문 지시**다("AFTER appending verdict, call `engine.jury_advisory.jury_advisory(...)`"). 같은 트리의 `validators/producer_consumer_coherence.py:9`가 **"bug#3 external_jury: 0 callers (built-but-unwired)"** 를 자기 사례로 적어놓았는데, 그 결함은 `external_jury` → `jury_advisory`로 **한 칸 올라갔을 뿐 닫히지 않았다.** 게다가 기본값 `DEBATE_EXT_JURY` 미설정 → `opt_out`이라, 켜져 있어도 아무 일도 안 일어난다.

테스트는 전부 `ask_fn`/`members_fn` 주입 fake다 — **실제 교차벤더 디스패치는 단 한 번도 실행 경로로 검증된 적이 없다**(테스트로서는 정당하지만, "교차벤더 검수가 작동한다"의 근거는 되지 못한다).

## 7. `prompts.py` — 프롬프트 권한

문자열 조립뿐. **권한 관련 실재 방어 0.** 세 프롬프트 모두 "역할 파일에 있는 스키마대로 JSON만"이라고 서브에이전트에게 위임하는데, **스키마도 도구 권한도 이 파일에 없다.** 특히 `architect_prompt`는 critique가 없으면 `"(no critique — fast-path)"`를 넣어 **비평 부재를 정상 상태로 정규화**한다. 반환 JSON의 검증(스키마/필드 존재)은 이 모듈 어디에도 없고, 호출자도 산문 지시다. `harness-debate.md:59`가 실측으로 기록한 사실 — **verdict 85건 중 55건이 `ontology_snapshot` 결손** — 이 그대로 그 증거다. 산문으로 지시된 단계는 65% 확률로 지켜지지 않았다.

## 8. `orchestrator.py` — 원장 SSOT의 실제 상태

**(a) 문서화된 명령이 존재하지 않는다.** `list_sessions` docstring은 `python -m engine.orchestrator list-sessions`를 "operator surface"로 제시하지만, **이 파일에 `main()`도 `if __name__ == "__main__"`도 argparse도 없다.** 그 명령은 실행 즉시 아무것도 하지 않는다(모듈은 `-m`으로 import만 되고 종료). autopilot `--resume` 실패 경로가 사용자에게 이 명령을 안내하도록 설계돼 있다면, **사용자에게 죽은 명령을 안내한다.**

**(b) `list_sessions`의 `phase_id`는 두 겹으로 틀렸다.**
```python
for e in reversed(events):
    if t in ("phase_update","phase_complete"):
        phase_id = e["payload"].get("phase_id") or e.get("phase","") or phase_id
```
- reversed 순회인데 `break`가 없다 → 최신값을 잡은 뒤 **더 오래된 이벤트가 덮어쓴다.** 결과는 "most recent"가 아니라 **최초 phase_update**다(docstring과 반대).
- 그리고 `update_phase`가 쓰는 payload는 `{phase_yaml, status}`뿐 — **`phase_id` 키를 애초에 안 쓴다.** 그래서 실무상 항상 `""`. 죽은 필드 위의 죽은 정렬 로직.
- `status`는 `autopilot_run_complete`에서만 갱신되는데 그 이벤트를 append하는 코드가 이 파일에 없다 → 항상 `"in_progress"`.

**(c) 원장이 시각을 파괴한다.** `merge_pane_shards`:
```python
jsonl_append(canonical, {"type":..., "sid":..., "payload":{k:v for k,v in ev.items() if k != "ts"}})
```
`ts`를 payload에서 **제외**하고, `jsonl_append`는 `{"ts": now_iso(), **record}`로 **머지 시각**을 찍는다. → 병합된 pane 이벤트의 원래 발생 시각은 **복구 불가능하게 소멸**하고 원장에는 머지 시각이 남는다. append-only 원장의 SSOT 주장과 정면 충돌한다. 그리고 `replay_pane_state`는 `ev.get("ts","")`로 정렬하므로 병합 후 순서 근거가 바뀐다. 수정은 쉽다: `payload`에 `ts`를 `orig_ts`로 보존.

**(d) 상수 대 지연 해석의 SSOT 분열.** `ORCHESTRATOR_DIR = STATE_DIR / "orchestrator"`는 **import 시점 고정**인데, 같은 경로를 읽는 `lib/completion_gate.count_orchestrator_iterations`는 의도적으로 **호출 시점 지연 해석**(docstring이 그 이유를 명시)이다. 같은 원장을 쓰는 두 모듈이 기준이 다르다 → CLAUDE_HOME/STATE_DIR 격리 시 **쓰는 곳과 읽는 곳이 갈릴 수 있다.** `tests/test_orchestrator.py:160`이 `ORCHESTRATOR_DIR`를 따로 잡아야 했던 것이 그 흔적이다.

**(e) 주석/코드 드리프트:** `merge_pane_shards` 위 블록 주석은 종결 상태를 `{exited, killed}`라 하고, 상수는 `{"exited","killed","failed"}`다.

**(f) 실재하는 방어(인정할 것):** `child_sids.json` JSONDecodeError → fail-closed raise, 원자적 쓰기, `confirm_resume_or_new`의 non-tty 기본값, `evaluate_completion`의 insight 기록이 절대 루프를 깨지 않는 것. 이건 진짜다. 단 `_persist_phase_tree`는 `write_text` 직접 호출로 **비원자적** — child_sids만 원자적인 비대칭.

## 9. 종료 판정과 "no mocked acceptance" — 가장 큰 간극

`evaluate_completion`은 `lib.completion_gate.decide_completion`의 얇은 래퍼이고 **`require_evaluator=False`가 기본값**이다. 그 경로의 완료 조건은:

```python
if not require_evaluator and evaluator_verdict is None and validators_passed and tests_passed:
    return "complete"
```

`validators_passed`/`tests_passed`는 **불리언 인자**다. 실제 공급자를 끝까지 따라가면(`handlers/stop/autopilot_continue.py:581-582`):

```python
validators_passed = bool(body.get("validators_passed", False))
tests_passed      = bool(body.get("tests_passed", False))
```

— **모델이 자기 transcript의 `<iteration-result>` 태그에 직접 써 넣은 값**이다. 같은 파일 645–650행 주석이 이 위험을 정확히 인지하고 있다("agent-controlled body is deliberately NOT a completion source — hallucinatable"), 그래서 **shared-sid 경로에서만** `require_evaluator=True`로 durable한 axis_scores 로그를 요구한다. 그런데 `count_orchestrator_iterations(sid)`가 `None`(= `state/orchestrator/<sid>/events.jsonl` 부재, 즉 cold-start)이면 그 강제가 통째로 건너뛰어지고 687행 `inline_pass = validators_passed and tests_passed and blocking_q == 0`로 **자기신고만으로 run이 complete 처리된다.**

즉 Zeus 기준으로: **"테스트를 실제로 돌렸다"는 사실이 어디에도 요구되지 않는 종료 경로가 남아 있다.** 그리고 `engine.orchestrator.evaluate_completion`을 직접 부르는 모든 호출자는 기본값이 `require_evaluator=False`이므로 항상 그 경로다. 엄격 재현/실사용자 수용과의 차이는 여기서 최대다.

## 10. `ralph.py` — 검증 루프의 실제 효과

- `passed = (returncode == 0) and "[FAIL]" not in stdout`. **아무것도 출력하지 않고 0으로 끝나는 검증기는 PASS**다. `[SKIP]`/`[WARN]`/빈 출력의 구분이 없다 → **skip이 PASS로 접힌다.** `check_iteration`은 `outcomes`가 비면 `all_passed=False`(fail-closed, 이건 옳다).
- `subprocess.run([sys.executable, str(script)])` — **argv를 전혀 넘기지 않는다.** `producer_consumer_coherence.py` 같은 검증기의 `--all`(MED 전수 스캔)은 ralph 경로에서 **구조적으로 절대 실행되지 않는다.** 즉 ralph의 "validators 통과"는 각 검증기의 기본(값싼) 모드만을 의미한다.
- `cwd` 인자는 subprocess의 CWD만 바꾼다. `VALIDATORS_DIR`을 비롯한 자산 경로는 `lib/paths`가 **ASSETS_HOME 기준으로 import 시점에 고정**하며 CLAUDE_HOME조차 의도적으로 보지 않는다(paths.py:23–48). 따라서 사용자 프로젝트를 `cwd`로 넘겨도 **하네스 자신을 검사하는 검증기는 여전히 하네스를 검사한다.** "프로젝트가 검증됐다"로 읽으면 오독이다.
- `ralph_store`는 `EventStore.__new__`로 `__init__`을 우회해 필드 3개를 손으로 심는다. **그런데 `EventStore.__init__`에는 이미 `base_dir=` 파라미터가 있다**(event_store.py:35). 지원되는 API를 두고 우회 생성자를 쓰는 것이라, `__init__`에 필드가 하나만 추가돼도 ralph 세션에서만 AttributeError가 난다. 현재는 `session_id/dir/path`만 쓰이므로 **동작은 한다** — 잠재 지뢰. 수정 1줄: `EventStore(session_id, base_dir=RALPH_DIR)`.
- **테스트 0.** `run_validators`/`check_iteration`/`build_fix_prompt`/`ralph_store`를 참조하는 파일은 tree 전체에서 `ralph.py` 자신뿐이다(grep 전수). `engine/prompts.py`, `engine/debate.py`, `engine/cli.py`도 동일하게 **호출자·테스트 0**(`__init__` 재수출 제외). "테스트 파일이 306개 존재"는 이 5개 파일에 대해 **아무 것도 뜻하지 않는다.**

## 11. `inventory_scan.py` — 유일하게 정직한 파일

D6 이후 런타임 상태(telemetry/세션/절대경로)를 커밋 산출물에서 **제거**하고, 그 이유를 코드 주석에 실측과 함께 남겼다("2026-09-01 CI 첫 실행에서 확인 — 신선한 체크아웃에서 자산이 안 바뀌어도 항상 빨갛다"). `--check` 실패 시 unified diff 80줄 출력. **이건 실재하는 방어다.**

한계: `_count_*`는 **파일 개수**만 센다. "engine/ 10 .py"는 그 10개가 호출되는지에 대해 아무 말도 하지 않는다 — 위 §10의 호출자 0 파일 5개가 그대로 카운트에 들어간다. 인벤토리를 완료도로 읽으면 안 된다는 원칙의 정확한 실례다. 부수: `_count_skills`가 `SKILLS_DIR.iterdir()`을 **존재 확인 없이** 호출한다(`_md_files`는 `is_dir()` 가드가 있는데 여기만 없음) → SKILLS_DIR 부재 시 `--check`가 FAIL이 아니라 **FileNotFoundError로 크래시**한다.

## 12. `trigger_summary.py` — 조회 표면

`--json` 스키마 안정 출력, ack 3종, JSONL 파싱 실패는 라인 단위 skip. 순수 읽기(ack 제외). `main()`의 `stdout.reconfigure` 가드는 StringIO 리다이렉트를 고려한 실제 방어.

한계: `summarize_data`의 `pending`/`acknowledged`는 **사람이 읽었다**가 아니라 **`--acknowledge-all`이 실행됐다**만 뜻한다. `_ack_all()`은 전 레코드를 무조건 seen 처리한다 — **검토 없는 일괄 소거 버튼**이고, 이후 SessionStart advisory는 조용해진다. "pending=0"을 검토 완료 신호로 쓰면 안 된다.

## 13. Windows / Linux / WSL

- **CI는 `ubuntu-latest` 단독**(ci.yml:35, 67). 이 하네스의 Windows 전용 분기 — `OpenAIProvider`의 `.cmd/.bat` shim `shell=True` 경로(openai.py:52–72), pane 병합이 근거로 드는 Windows 파일락 문제(orchestrator.py:328–331), junction 기반 격리(run_units.py:304–311) — 는 **CI에서 단 한 줄도 실행되지 않는다.**
- ci.yml 주석 자신이 기록: 기본 브랜치가 `main`인데 워크플로가 `master`에 있어 **push 트리거가 한 번도 발화한 적 없고, 기본 브랜치 CI 상태는 측정된 적이 없다.**
- `ralph.run_validators`는 자식 stdout을 `encoding="utf-8"`, `errors` 미지정으로 디코드한다. 검증기 다수가 한국어/기호를 출력하는데 Windows에서 자식의 콘솔 인코딩이 cp949면 (a) 자식이 UnicodeEncodeError로 비정상 종료 → `[FAIL]`로 계수, 또는 (b) 부모 디코드 실패 → `except Exception` → `"[FAIL] validator exception"`. **정상 코드가 플랫폼 때문에 FAIL로 뒤집혀 fix agent에게 먹여진다.** — **미검증 가설**이다(실행 금지). 반증하려면 `PYTHONIOENCODING`을 세팅하는 상위 경로가 있는지 확인이 필요하고, 나는 그 경로를 찾지 못했다.

## 14. 오류 / 누락 / skip / PASS 회계

- `run_units.py`는 pytest 부재 시 `[WARN] ... main()로 폴백`만 찍고 **`failed`에 넣지 않는다** → 그 파일은 사실상 미검증인데 요약의 failed=0을 유지한다. 반대로 `[SKIP-SUITE]`/`no main()`은 `skipped`로 분리 계상한다(이건 정직한 설계). 즉 **skip 회계는 대체로 정직하나 pytest-부재 구멍 하나가 남아 있다.**
- 위 §10대로, **이 11개 중 5개(`prompts`, `debate`, `cli`, `ralph`, `__init__`)는 테스트·호출자가 0**이고, 나머지 6개 중 `external_jury`/`dispatch_retry`/`jury_advisory` 테스트는 전부 fake 주입이다. 실제 프로바이더 왕복은 어떤 자동 검사에도 없다.

---

## 결론

**전체 분석 완료 아님. 흡수 승인 아님.** 위는 root 독립 정적 검토 결과이고, 다른 reviewer 보고는 읽지 않았다.

Zeus 요구 대비 가장 큰 간극 세 가지, 수정 가능한 형태로:

1. **종료 판정에 실행 증거가 없다** (§9). `decide_completion`의 `require_evaluator` 기본값이 `False`이고, cold-start Stop 경로는 모델 자기신고 불리언만으로 complete를 낸다. `engine.orchestrator.evaluate_completion`의 기본값을 `True`로 뒤집고, cold-start에서 `inline_pass` 폴백을 제거하는 것이 최소 수정이다.
2. **교차벤더 독립검수가 이름 검사 위에 서 있고, 호출자가 산문이다** (§5, §6). `shutil.which("codex")`가 벤더 정체성의 전부이며, 모델은 `codex-default`로 원장에 남고, 정족수 하한이 없어 1표가 `agreement=1.0`이 된다. 그리고 유일한 호출자는 markdown 지시다 — 같은 트리의 실측(verdict 85건 중 55건 스냅샷 결손)이 산문 프로토콜의 준수율을 이미 반증했다.
3. **원장이 SSOT를 자칭하지만 시각을 파괴하고 죽은 명령을 안내한다** (§8). `merge_pane_shards`의 `ts` 소멸, `list_sessions`의 역방향 덮어쓰기 + 존재하지 않는 `phase_id` 키, 그리고 `python -m engine.orchestrator list-sessions`라는 **엔트리포인트 없는 명령**. 셋 다 국소 수정이 가능하다.

Astra→Sol→Terra 가드레일 이관 관점에서는, 이 engine 계층에서 실제로 이관 가치가 있는 방어는 `inventory_scan`의 머신종속 배제 결정(§11), `dispatch_retry`의 순수·주입가능 재시도(§4), orchestrator의 sidecar fail-closed(§8f) 셋이고 — 나머지 "가드레일"은 markdown 산문에 위임돼 있어 이관 대상이 아니라 **재구현 대상**이다.

**미검증으로 남긴 것**: 바이트 총계 80,138, Windows 인코딩 가설(§13), `lib/breakers/composite.py` 본문 전체(grep만), `lib/debate_convergence.snapshot_sha1`과 `cli.debate_converge_check` 실물, `lib/phase_tree`·`lib/strike_dispatcher` 실물. 상호 토론에서 이 다섯 개가 쟁점이 되면 그때 해당 구간만 추가로 열겠다.