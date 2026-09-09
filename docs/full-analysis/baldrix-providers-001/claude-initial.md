## 0. 읽은 범위와 확인 한계

전문 5개(정확 줄수): `__init__.py` 69줄, `base.py` 58줄, `anthropic.py` 122줄, `openai.py` 98줄, `ollama.py` 227줄. **19,724 bytes 총합은 확인하지 못했다** — 이 검토는 Read/Glob/Grep만 사용해 파일 크기를 실측할 수단이 없었다. 줄 수와 내용만 근거로 삼는다.

추적한 직접 caller/config/test(필요 구간만):
- `scripts/engine/external_jury.py:25-29, 37-53, 113-129, 132-199, 227-256`
- `scripts/engine/jury_advisory.py:42-74, 143-151`
- `scripts/lib/evaluator_dispatcher.py:104-113, 504-587, 753-803, 806-841, 890-923, 1443-1472, 1874-1884`
- `scripts/lib/research_extractor.py:25-32, 45-50, 200-238`
- `scripts/lib/model_router.py:1-23, 93-125`
- `scripts/lib/narration.py:124-135`, `scripts/cli/endpoint_query.py:79-92`
- `scripts/tests/test_providers_ollama.py` 전문(27줄), `tests/test_external_jury_retry.py:17-116`, `tests/test_seams.py:443-469`, `tests/test_import_graph.py:48-129`
- `docs/subsystems/lib-providers-workers.md` 전문, `commands/harness-ask.md`(grep 구간 2-75)

읽지 않은 부분: `ensemble_evaluator.py` 전문(라인 315/532만 grep), `lib/breakers/*`, `dispatch_retry.py` 본문, `atlas/autopilot/concepts/phase-35-*`, `brain/l1/insight-index.jsonl`, `get-shit-done/bin/lib/core.cjs`. **grep 부재를 전체 호출 0으로 취급하지 않는다** — 특히 markdown/skill 기반 호출(harness-ask 같은 자연어 지시)과 cjs 계층은 정적 grep으로 완결되지 않는다.

원본 실행·import·네트워크·credentials 접근은 0건이다. vendor CLI 옵션/모델 ID/SDK 규격은 온라인 검증하지 않았으므로 아래는 모두 **코드가 주장하는 바**이며 현행 사실로 단정하지 않는다.

## 1. 실행 프로세스 권위

- `anthropic.py:26-38` — 권위 순서는 SDK(ANTHROPIC_API_KEY 존재 + import 성공) → `claude` CLI. `_sdk_ready()`(42-49)는 키 존재만 보고 키 유효성은 확인하지 않으므로, 잘못된 키가 있으면 CLI 경로로 폴백하지 않고 SDK 실패로 확정된다.
- **비대칭 샌드박싱(구조적 위험)**: `openai.py:38`은 `-s read-only` + `--skip-git-repo-check`로 부작용을 차단하고, `evaluator_dispatcher.py:531,552,563`은 `_build_isolated_env()`로 환경을 정화한다. 반면 `_invoke_claude_evaluator`(`evaluator_dispatcher.py:834-841`)는 `AnthropicProvider.ask`를 그대로 호출하고, `anthropic.py:88-101`의 CLI 실행은 **env 정화 없음, 도구/권한 제한 플래그 없음, cwd 지정 없음**이다. `_invoke_ollama_evaluator`(`:776-784`)도 env 정화가 없다(781행 주석은 local-only라 불필요하다고 주장). 즉 prompt isolation(`validate_prompt_isolation`, 771/825행)은 강제되지만 **process isolation은 codex 경로만 강제된다.** claude CLI가 디스크의 debate transcript를 스스로 읽을 수 있는지는 vendor 동작이라 미검증이나, 코드 안에 그것을 막는 방어는 없다.
- **재귀 실행**: 하네스가 Claude 세션 안에서 돌 때 `anthropic.py:90`은 다시 `claude` CLI를 스폰한다. 이 5개 파일 안에 깊이/재귀 가드는 없다(다른 계층의 depth 전파 존재 여부는 이번 범위에서 미확인).
- `ollama.py:46-52`의 가용성 프로브는 `["ollama", "list"]`로 **which()가 돌려준 경로를 쓰지 않는다** — `ask()`(63,95,106)와 규칙이 다르다(§7 참조).

## 2. 모델 선택

- 기본값: anthropic `claude-sonnet-4-6`(`anthropic.py:23`), openai `""`→CLI 자체 기본(`openai.py:25,36,93`에서 표시용으로 `"codex-default"`로 치환), ollama `llama3.1:8b`(`:36`) + `OLLAMA_DEFAULT_MODEL` env 우선(`:67-71`). env 오버라이드는 **ollama만** 지원하고, claude 쪽 env(`CLAUDE_EVALUATOR_MODEL`)는 adapter가 아니라 caller(`evaluator_dispatcher.py:840`)에 있다 — 오버라이드 지점이 계층마다 다르다.
- `model_router.py:96-109`는 anthropic/openai 티어만 매핑하고 ollama는 없다. `JuryMember(provider="ollama", model="auto")`는 `resolve_model_id` None → `_resolve_model`이 `""` 반환(`external_jury.py:122,128`) → provider 기본값으로 조용히 강등된다(실패로 기록되지 않음).
- `model_router.py:121`이 **private `_REGISTRY`를 직접 import**한다. `__init__.py:3-7`의 "No changes anywhere else in the codebase" OCP 주장과 실제가 어긋난다: 새 provider에 `auto` 라우팅을 주려면 `DEFAULT_MODEL_IDS`도 고쳐야 하고, 라우터는 공개 API(`list_aliases`)가 아닌 사설 심볼에 결합돼 있다.
- `model_router.py:103` 주석은 codex가 `-c model="<id>"`로 모델을 받는다고 하고 `openai.py:11`은 `-m`이 더 단순하다고 한다. 두 주장은 코드 내부 기록이며 현행 CLI 사실로 단정하지 않는다. 매핑된 ID들(`gpt-4o-mini`/`gpt-5-codex`/`o3`, `claude-opus-4-7`)의 실재도 미검증이다.

## 3. 인자와 출력 스키마

- `AskRequest`(`base.py:22-27`)의 `max_tokens`/`temperature`는 **SDK 경로에서만 사용된다**(`anthropic.py:57,60-61`). anthropic CLI, openai, ollama는 두 필드를 **조용히 버린다** — 경고도, 예외도 없다. `base.py`의 ABC 계약은 이 무시를 금지하지도 허용하지도 않아, 동일 요청이 provider에 따라 다른 의미를 갖는다. 반면 `system`은 세 경로 모두 처리된다(SDK: `system` kwarg / CLI: `--append-system-prompt` / codex·ollama: `<system>` 인라인 `openai.py:45-50`, `ollama.py:80-85`). 즉 "무시 불가" 취급을 받은 인자는 `system`뿐이다.
- `capabilities`(`base.py:45`, `anthropic.py:24`, `openai.py:26`, `ollama.py:37`)는 **어떤 소비자도 없는 죽은 메타데이터**다. 전 pinned tree grep 결과 소비처는 ollama 자체 self-check(`:159-160`)와 `__main__` 출력(`:224`)뿐이다. anthropic이 선언한 `"json"` 능력을 뒷받침하는 JSON 모드 인자는 SDK/CLI 어느 경로에도 없다.
- 출력 스키마: `AskResponse.raw`는 SDK에서 `{"id": ...}`, CLI에서 `{"stderr_tail": ...}`(200자)로 **키 집합 자체가 다르다**(`anthropic.py:85,118`, `openai.py:94`, `ollama.py:132`). `raw`를 형태 가정 하에 읽는 소비자는 이번 범위에서 발견하지 못했다(부재≠0).
- JSON 파싱 책임은 전부 caller에 있고 구현이 **3중 중복**이다: `external_jury._strip_code_fence/_try_parse_json`(`:79-95`), `_invoke_ollama_evaluator`(`:788-801`), `_invoke_claude_evaluator`(`:844-847` 이후), `_extract_json_object`(codex 전용, `:585`). codex 경로만 `{'_fallback_reason':'parse_empty'}` 센티널을 남기고(`:577-586`), ollama/claude 경로는 파싱 실패를 **빈 dict**로 삼켜 원인이 기록되지 않는다.

## 4. 오류·timeout·재시도 (가장 무거운 결함군)

**P1 — UnicodeDecodeError가 "영구 결함"으로 오분류된다.** 세 adapter 모두 `text=True, encoding="utf-8"`만 쓰고 `errors=`를 지정하지 않는다(`anthropic.py:97-100`, `openai.py:68-81`, `ollama.py:99-113`). 같은 저장소의 다른 subprocess 호출은 거의 전부 `errors="replace"`를 쓰며, `evaluator_dispatcher.py:550`은 "Windows cmd.exe stderr cp949 fallback" 이유를 명시하고 있다 — 즉 **이 실패 양식은 프로젝트가 이미 겪어서 문서화한 것**이다. 비-UTF8 바이트가 오면 `subprocess.run` 내부 디코딩에서 `UnicodeDecodeError`가 나고, 세 adapter의 except 절(`TimeoutExpired`/`OSError`)에 걸리지 않아 그대로 전파된다. `UnicodeDecodeError`는 `ValueError`의 하위 클래스이므로 `external_jury._PERMANENT_EXC`(`:47-49`)에 매칭되어 **`permanent`로 분류**되고(`:52-53`), `_dispatch_with_breaker`(`:174-178`)는 "provider는 도달했으므로 available"이라며 **record_success**를 남긴다. 결과: 실제 가용성 문제가 코드 버그로 위장되고, breaker는 절대 트립하지 않으며, 재시도도 없다. dispatcher 복제본만 이 문제를 고쳤고 adapter 원본은 안 고쳐진 상태다.

**P2 — 반대 방향 오분류.** `anthropic.py:67-72`는 SDK 예외 전부를 `ProviderUnavailableError`로 감싼다(65-66행 주석이 의도를 명시). 그래서 모델 ID 오타/400류 영구 오류도 `transient`가 되어(`_classify_jury` 기본 분기) `call_with_retry`로 재시도되고 breaker failure가 누적된다. 비-소급 오류를 300초 backoff cap(`external_jury.py:38-40`)으로 갚는다.

**P3 — OSError 처리 비대칭.** `anthropic.py:106-109`와 `ollama.py:118-121`은 `OSError`를 `ProviderUnavailableError`로 변환하지만 `openai.py:82`는 `TimeoutExpired`만 잡는다. codex 실행 파일이 exec 불가(WSL에서 Windows 바이너리, 권한 문제 등)일 때 openai만 생 `OSError`를 던진다. `OSError`는 `_PERMANENT_EXC`에 없어 transient로 흐르므로 breaker는 동작하지만, `research_extractor`가 약속한 "`.ask()`가 `ProviderUnavailableError`를 던지면 raw 반환"(`:29-32`) 계약은 이 경로에서 성립하지 않는다.

**P4 — timeout 예산 불일치.** adapter 하드코딩: claude CLI 180s(`anthropic.py:100`), codex 300s(`openai.py:72,80`), ollama 300s(`ollama.py:103,112`), 프로브 5s(`ollama.py:51`). SDK 경로는 **timeout 인자 자체가 없다** — 상한은 SDK 기본값에 위임되고(미검증) adapter에서는 무한으로 보인다. dispatcher는 `SUBAGENT_TIMEOUT_SECONDS=270`을 두고 "codex 300s보다 먼저 발화해야 fallback 사유 분류가 보존된다"고 명시하지만(`:104-113`), 이 값은 codex 격리 경로에만 전달된다(`:532`). ollama(300s)·claude(180s) 경로는 `timeout_seconds` 인자조차 없어 270초 예산이 적용되지 않는다 — 즉 그 근거는 pool의 1/3에만 유효하다. 어떤 timeout도 설정 가능하지 않고 env/config 오버라이드 지점이 없다.

**P5 — 재시도는 provider 안에 없다.** 재시도는 `external_jury._dispatch_with_breaker`(`:169-172`)에만 있고 `evaluator_dispatcher`/`narration`/`research_extractor`/`endpoint_query` 경로에는 없다. 재시도는 전체 프롬프트 재전송이므로 **비용이 곱해지지만 회계는 없다**(§6). `retry_breaker=False`가 기본(`:210-214`)이므로 기본 동작에는 재시도·breaker가 모두 꺼져 있다.

**P6 — 성공 판정이 느슨하다.** `openai.py:91`/`ollama.py:129`/`anthropic.py:115`는 returncode 0이면 `stdout.strip()`이 **빈 문자열이라도 성공**으로 반환한다. `external_jury`는 이를 응답 1건으로 계수해 `if not responses`(`:253`)의 "전원 실패" 예외를 회피시킨다 → 빈 응답 패널이 "가용"으로 보고된다.

**P7 — `get_provider` 계약 위반.** `__init__.py:44-46` docstring과 `docs/subsystems/lib-providers-workers.md:23`은 `get_provider`가 `ProviderUnavailableError`를 던진다고 선언하지만, 실제 함수(`:48-59`)는 가용성 프로브를 전혀 하지 않고 `KeyError`/`RuntimeError`만 낸다. 이를 신뢰한 caller는 ask() 시점까지 실패를 모른다(실제 caller들은 각자 `is_available()`을 호출해 방어 중 — `external_jury.py:135`, `jury_advisory.py:70`, `endpoint_query.py:84-85`, `evaluator_dispatcher.py:517,781,835`). 문서 선언 ≠ 구현 사실의 사례다.

**P8 — 비-str provider 이름.** `__init__.py:48`의 `name.lower()`는 str이 아니면 `AttributeError`다. `external_jury.py:229-232`는 `KeyError`만 잡으므로 YAML/설정에서 온 None/숫자 이름 하나가 "미지 provider는 skip"이라는 명시 계약(`:205`)을 깨고 패널 전체를 죽인다.

## 5. stream / bytes

스트리밍은 어디에도 없다. 세 경로 모두 `capture_output=True`로 stdout/stderr 전량을 메모리 버퍼링한다 — 응답이 커지면 전량 상주하고, 부분 출력·진행 관측·중도 취소가 불가능하다. `communicate()` 기반이므로 파이프 교착은 없다(유효 방어). stderr는 진단용으로 앞 200~300자(`anthropic.py:112`, `openai.py:87`, `ollama.py:125`) 또는 뒤 200자(`raw.stderr_tail`)만 남고 나머지는 폐기된다. `ollama run`의 진행/스피너 출력이 stdout으로 섞이는 경우를 다루는 코드는 없다(파이프 시 vendor 동작은 미검증).

## 6. 토큰·비용 분모

- `tokens_in`/`tokens_out`은 **anthropic SDK 경로에서만** 채워진다(`anthropic.py:83-84`, `usage` 부재 시 None). CLI 3경로는 전부 None이다.
- 전 pinned `scripts/` grep 결과 `tokens_in`/`tokens_out`을 **읽는 소비자는 0건**이다(동명이인 `_canonical_tokens_in`은 무관). 즉 이 슬라이스에는 토큰/비용 원장이 존재하지 않는다 — 재시도·앙상블 다중 호출의 비용 분모가 아예 없다.
- 반면 codex stdout에는 실제 사용량 footer("tokens used / N")가 온다고 dispatcher 주석이 기록하는데(`:578-584`), `_extract_json_object`가 JSON만 뽑고 그 수치는 버린다. **관측 가능한 실측치를 버리고 None을 남기는 구조**다.
- 유일한 비용 대리 지표는 `research_extractor`의 바이트 임계값 `8000 bytes (~2K 토큰)`(`:26`, `:219`에서 `len(raw_blob.encode("utf-8"))`)이다. 이 4 bytes/token 환산은 한국어 등 다바이트 텍스트에서 토큰을 과소 추정한다(한글 1자 3바이트 → 8,000바이트가 2,666자 ≈ 2K 토큰보다 많을 가능성). 바이트 분모를 토큰 분모라고 부르는 지점이다.

## 7. Windows / Linux / WSL

- `.cmd`/`.bat` shim 처리는 `openai.py:55-59,62-72`와 `ollama.py:88-104`에만 있다. `.ps1`은 취급하지 않는다(`shutil.which`가 PATHEXT 순서상 `.cmd`를 먼저 준다는 가정에 의존).
- **`ollama.is_available`의 Windows 결함**: `:46-52`는 shim 분기 없이 `["ollama","list"]`를 arg-list로 실행한다. `ollama`가 `.cmd` shim이면 `OSError`→`False`가 되어(53-54행) 모든 caller가 ollama를 제외한다. 그런데 `ask()`는 shim 처리를 하므로 **"unavailable이라고 보고하지만 ask는 되는"** 모순 상태가 생긴다. 실제 Windows 설치가 `.exe`인지 shim인지는 미검증이므로 영향 범위는 확정하지 않는다. self-check도 이 모순을 잡지 못한다(§8).
- `is_available`은 `which()` 결과를 버리고 이름으로 재실행하므로, `ask()`가 쓰는 경로와 프로브 경로가 다를 수 있다(PATH 변경/여러 설치).
- shell=True 경로에서 `subprocess.list2cmdline`은 **CreateProcess 인용 규칙**으로 인용하고 cmd.exe 메타문자(`&`, `^`, `|`)는 이스케이프하지 않는다. `codex_path`/`ollama_path`에 `&`가 든 디렉터리라면 명령행이 깨진다(좁지만 실재하는 경로). 프롬프트는 stdin으로 가므로 프롬프트 기인 주입은 없다 — 이건 유효한 설계 방어다.
- WSL: `platform.system()=="Linux"`이므로 shim 분기가 꺼지고, `/mnt/c` PATH로 Windows 실행 파일이 잡히면 exec 실패 → ollama/anthropic은 `ProviderUnavailableError`로 정리되지만 openai는 생 `OSError`(P3).
- `ollama.is_available`의 `len(lines) >= 2` 휴리스틱(`:57-60`)은 `ollama list` 헤더 형식·로케일에 결합돼 있고, 5초 타임아웃은 콜드 스타트 서버에서 False를 낼 수 있다. 또 **요청 모델이 설치돼 있는지는 검사하지 않는다** — `OLLAMA_DEFAULT_MODEL` 오타면 `ollama run`이 무엇을 하든(자동 pull 여부는 미검증) 최악 300초를 소모한 뒤 transient로 분류되어 breaker를 트립시킨다.

## 8. 테스트·검증 실태 (실제 runner 영수증 대조)

- 이번 검토에서 원본 실행은 **0건**이며, 이 5개 파일에 대한 Zeus 측 runner 영수증(`*.receipt.json`)은 존재하지 않는다. `docs/full-analysis/baldrix-providers-001/`에는 프롬프트 1개뿐이다. 아래는 코드에 적힌 assert의 존재이며 **현재 PASS가 아니다.**
- 전용 테스트는 `tests/test_providers_ollama.py`(27줄)뿐이고, 그것은 `ollama.py:144-213`의 `_self_check()`를 호출하는 래퍼다. 그 self-check 7개 케이스는 이름/기본모델/capability/dataclass 생성/PROVIDER export/registry 왕복 — 즉 **메타데이터 검사**다. `ask()` 성공 경로 검증은 없다. `is_available()`은 `isinstance(bool)`만 보므로 §7의 Windows 모순을 구조적으로 잡을 수 없고, 마지막 케이스는 ollama가 가용하면 **검사를 건너뛰고 OK로 계수**한다(`:201-203`) — 호스트 상태에 따라 공허하게 통과하는 assert다. 게다가 이 "테스트"는 실제 `ollama list` 서브프로세스를 스폰하는 호스트 의존 프로브다.
- anthropic/openai adapter 전용 테스트는 발견하지 못했다. 간접 커버리지: `test_external_jury_retry.py:27-41`의 `_Fake`가 `get_provider`를 monkeypatch해 분류/breaker/재시도를 검증한다 — provider 계약이 아니라 **jury의 오류 처리**를 검증하는, 명백한 mock 기반 단위 시험이다. `test_seams.py:443-469`는 seam 경로가 `lib.providers`를 import하지 않음을 강제하는 아키텍처 방어(유효)이고, `test_import_graph.py:80-94`는 providers 디렉터리를 **fixture로 합성**해 쓴다(실제 adapter 검증 아님).
- 정리: **실제 vendor 프로세스를 한 번이라도 통과시키는 인수 시험은 이 pinned tree 안에 없다.** P1~P8은 그래서 단위 시험이 통과해도 남는다.

## 9. Zeus 기준 대조

- **PG runtime SSOT / Git 정의**(`docs/tickets/README.md:3`): providers 계층은 실행 결과를 남기는 원장이 없다. jury 실패는 `failures` 문자열 튜플(`external_jury.py:72`)과 axis 이벤트로만 흐르고, provider별 호출/토큰/timeout/재시도 실측은 PG로 갈 스키마 자체가 없다. Zeus에 흡수하려면 이 계층은 **런타임 SSOT 미충족**이다. 반대로 Git 정의 쪽(레지스트리 1줄 + 파일 1개)은 깔끔하다.
- **인간 핵심 시나리오 8단계 SDD / no mocked acceptance**(`docs/full-analysis/README.md:22-27`, `docs/zeus/full-delivery-scope.md:12`): §8 그대로, 사람이 검토 가능한 인수 기준·실측 영수증이 없고 mock/self-check만 있다. 완료 기준 2번("문서 선언·구현 사실·실행 결과 분리")에 걸린다 — P7과 doc drift가 그 위반 사례다.
- **AstraSolTerra 실적 기반 자격 이관 / 완료 기준 6번**: `default_model`·`DEFAULT_MODEL_IDS`·"provider diversity"·"claude 기본 pool 편입" 같은 판단은 원본 하네스의 운영자 결정(`evaluator_dispatcher.py:909` "운영자 결정")이다. 이 자격은 실적 근거 없이 Zeus로 승계될 수 없다. 특히 `_build_default_ensemble_specs`(`:910-922`)가 **호스트에 claude가 있으면 pool을 자동 확장하고 `allow_generator_family`를 자동 완화**하는 구조는, 평가자 독립성 자격이 호스트 환경에 의해 암묵 부여되는 형태다 — Zeus 기준에서는 명시 승인 대상이다.
- 문서 drift 3건(대조용): `lib-providers-workers.md:5`는 provider 4종("recursive Codex wrapper" 포함)을 말하지만 레지스트리는 3종이다(`__init__.py:24-33`). 같은 문서 `:23`은 P7의 잘못된 예외 계약을 반복한다. `commands/harness-ask.md:4,16`은 여전히 `claude|codex`만 인자로 안내해 v15.35.2 ollama 추가가 반영되지 않았다. 반면 같은 문서의 라인 참조(`anthropic.py:122`, `openai.py:98`, `ollama.py:136`, `__init__.py:31-32`, gotcha 44-45의 구간)는 **실제 파일과 일치**한다 — 문서 정확도는 항목별로 갈린다.

## 10. 실재하는 유효 방어 (보존)

레지스트리 lazy import + `PROVIDER` 계약(`__init__.py:53-58`)으로 미설치 SDK가 import 시점에 전체를 죽이지 않는다. 프롬프트는 전 경로 stdin 전달 → shell escaping/주입 회피. codex `-s read-only` + `--skip-git-repo-check`. `_PERMANENT_EXC` 화이트리스트 방식(미지 예외는 transient로 = breaker 쪽으로 fail-toward, `:42-49`)은 명시적으로 논증된 보수적 선택이다. permanent 결함 시 record_success로 breaker 오염 방지(`:155-156, 174-178`). `system` 인라인 폴백으로 CLI에서도 무시되지 않음. `endpoint_query.py:90-91`, `jury_advisory.py:147-151`, `research_extractor.py:234-238`의 fail-soft 강등. `test_seams.py`의 LLM/network import 금지 강제. `_extract_json_object`의 parse_empty 센티널(codex 한정).

## 11. 미검증으로 남기는 것

vendor 모델 ID 실재·CLI 플래그(`--print`, `--append-system-prompt`, `-m`, `-s read-only`, `ollama run` stdin) 실제 동작·SDK 기본 timeout·`ollama run` 미설치 모델 자동 pull 여부 — 전부 코드의 주장으로만 기록. Windows ollama 설치 형태(.exe vs .cmd)에 따른 P7 영향 범위. `ensemble_evaluator` 전문과 breaker/retry 모듈 본문. cjs/markdown 계층의 추가 호출 존재 여부. 19,724 bytes 총합. 전 pinned tree의 provider 간접 호출 전수.

## 12. 판정

**전체 분석: false. 흡수 승인: false.** 근거: (a) P1의 UnicodeDecodeError→permanent 오분류는 이 저장소가 이미 다른 곳에서 고친 실패 양식이 adapter에 남은 것이고, (b) P2/P4는 오류 등급과 timeout 예산이 계층별로 어긋나 재시도·breaker 회계를 왜곡하며, (c) 토큰·비용 분모와 런타임 원장이 부재해 Zeus PG SSOT 요건을 못 채우고, (d) 실제 vendor 프로세스를 통과하는 no-mock 인수 증거가 0건이며, (e) 문서 선언(get_provider 예외 계약, provider 4종, harness-ask 인자)이 구현과 어긋난다. root 독립 검토 후 대조 토론에서 P1·P4·P7·§6을 우선 쟁점으로 올리기를 제안한다.