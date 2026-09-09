새 증거와 root 보고를 모두 읽었다. 아래는 초기 보고를 이 체크포인트 기준으로 정정한 대조 검토다.

## 0. 이번 체크포인트의 실행 증거 (초기 보고의 "영수증 0건" 서술 갱신)

초기 보고의 "runner 영수증 없음"은 **작성 시점 사실**이었고 현재 상태가 아니다. 지금 확보된 것:

- `ollama-unit.receipt.json`: 원본 `scripts/tests/test_providers_ollama.py`(sha256 `25d5b99…`)를 immutable·`--network none`·`--read-only`·`--cap-drop ALL`·nonroot(65534)·pids 64·mem 256m Alpine 이미지(`sha256:7415fbc3…`)에서 실행, rc0, 0.75초. `ollama-unit.stdout.txt`: **8 assertions [OK]**, 그중 `ask_raises_when_unavailable`이 **실제 unavailable 분기**를 통과했다.
- `components.receipt.json` + `components.stdout.txt`: `installed_cli` 3종 전부 null, `ANTHROPIC_API_KEY` 없음(`component_observations.py:18-20`의 assert가 이를 강제). 실제 `get_provider`/`is_available`/`ask` 호출로 세 adapter의 `ProviderUnavailableError` 메시지를 원문 그대로 관측.
- 두 영수증 모두 `source_bytes_unchanged: true`, tree hash `91a6454…`, fake CLI/SDK 없음, 실제 모델 호출·토큰 측정 없음이 `limits`에 명시.
- 19,724 bytes는 **root manifest/raw-byte 증거**로 수용한다. 내 측정치가 아니라는 표시를 유지한다(초기 보고에서 "확인 못했다"고 쓴 것은 내 측정 한계 서술로만 유효).

이 실행으로 **가설에서 관측으로 승격된 것 3건**: (a) `get_provider`는 backend 없이도 인스턴스를 돌려준다 — 세 provider 모두 `is_available: false`이면서 인스턴스 반환(내 P7). 단, receipt의 `instance_returned_without_backend: true` 키 자체는 `component_observations.py:27`의 **하드코딩 상수**이고, 실증은 "객체가 반환되고 그 `is_available()`이 false"라는 관측이다. (b) 비-str 이름 → `AttributeError`(`"'NoneType' object has no attribute 'lower'"`), 즉 내 P8은 이제 관측 사실이다. (c) `" codex "` → `KeyError`(트림 없음), `AskRequest(prompt=None, model=123, max_tokens=-1, temperature="invalid", system=[])`가 **검증 없이 생성**됨 — root의 "AskRequest has no runtime validation"(codex-initial.md:9)이 실측으로 뒷받침된다.

## 1. root와 합의하는 부분

- 레지스트리/ABC의 의존성 역전 가치, 그리고 `get_provider`의 가용성·인터페이스·capability 미검증(root :7 ↔ 내 P7). root가 지적한 "concrete import는 보편적이지 않다"에 **한 건 추가**한다: `lib/model_router.py:121`이 공개 API가 아닌 **private `_REGISTRY`를 직접 import**한다. 즉 `__init__.py:3-7`의 "No changes anywhere else" 문구를 깨는 사례가 `evaluator_dispatcher`·ollama 테스트 외에 라우터에도 있다.
- `AskRequest`에 deadline/취소/시도/idempotency/스키마/예산이 없고 `max_tokens`/`temperature`/`system`의 실제 의미가 backend마다 다름(root :9 ↔ 내 §3).
- `AskResponse.model`이 "resolved concrete model"을 자칭하지만 실제 응답 모델을 증명하지 않음(root :9). 내 초기 보고는 `raw` 키 불일치만 지적했다 — root의 지적이 더 강하고 수용한다.
- SDK 우선 선택 후 실패 시 CLI 폴백이 없다(root :13). 내 보고에 없던 유효 지적.
- `request.max_tokens or 4096`(`anthropic.py:57`) → **0이 4096으로 바뀌고 -1은 그대로 전달**(root :13). components 관측이 `-1` 생성 가능을 뒷받침한다. 수용·추가.
- CLI가 resolved path가 아니라 bare `"claude"`를 실행(`anthropic.py:90`) — openai/ollama는 `which()` 경로를 쓰는데(`openai.py:32,63,74`, `ollama.py:63,95,106`) anthropic만 다르다(root :15). 내 보고에 없던 비대칭. 수용.
- 응답 추출이 text 블록만 이어붙이고 stop/truncation/refusal 구분을 버림(root :13, `anthropic.py:73-77`).
- `UnicodeDecodeError`(=`ValueError` 하위) → permanent → breaker success 경로(root :31 ↔ 내 P1). 두 검토가 독립적으로 같은 결론에 도달했다.
- 빈 rc0 응답이 정상 응답으로 계수됨(root :15,:27 ↔ 내 P6).
- `-s read-only`/"local-only"/"no side effects" 문서 주장이 코드가 증명하는 범위보다 넓다(root :21,:27,:33).
- Astra→Sol→Terra 자격은 이 adapter 추상화로 승계되지 않는다(root :9,:39 ↔ 내 §9).

## 2. 내 초기 보고 정정 (요청 10건)

1. **`-s read-only`** — "부작용을 차단한다"·"codex 경로만 process isolation을 강제한다"는 과주장이므로 철회한다. 정확히는 *의도를 선언하는 옵션*이며 vendor 실효는 미검증이다. 게다가 `_build_isolated_env`(`evaluator_dispatcher.py:347-354`)는 접두사 제거 + allowlist 방식으로 **`PATH`,`HOME`,`USERPROFILE`,`TEMP`,`APPDATA`,`LOCALAPPDATA`,`HOMEDRIVE/HOMEPATH`를 의도적으로 유지**하고(`:360-369`), `subprocess.run`에 `cwd=`를 주지 않으므로 부모 작업디렉터리도 그대로다. 소스 자신의 `:486-487` "codex CLI는 부모 파일시스템에 Read/Grep/Bash가 없다"도 **미검증 vendor 주장**이다. 따라서 claude 경로와의 차이는 "선언된 격리 정책·env allowlist의 유무" 차이로 축소하고, "claude CLI가 transcript를 읽는다"는 것도 "codex는 못 읽는다"는 것도 **양쪽 다 미검증**으로 남긴다.
2. **SDK timeout/retry** — "adapter에서는 무한으로 보인다"를 철회한다. 정확히는 *adapter가 timeout·retry 정책을 명시하지 않아 상한과 SDK 내부 재시도 유무가 이 코드로는 알 수 없다*(무한도 아니고 재시도 0도 아니다). 또 try 범위는 `client.messages.create` 한 호출뿐이다(`anthropic.py:67-72`) → `import anthropic`(:52), `anthropic.Anthropic()`(:53), 그리고 추출부(:73-86)는 **catch 밖**이다. 추출부 예외는 `AttributeError`/`TypeError`류가 되어 `_PERMANENT_EXC`(`external_jury.py:47-49`)에 걸리므로 P1과 **같은 오분류 경로**로 흐른다 — 이건 root :13과 합쳐 보강한다.
3. **예산 구분** — `call_budget_sec=20.0`(`external_jury.py:199`)는 docstring `:215-216`이 스스로 "reserved(D1이 명시 deadline을 버렸다)"라고 적고 본문에서 사용되지 않는다. 4층을 분리해 다시 쓴다: ① adapter timeout = claude CLI 180s(`anthropic.py:100`), codex 300s(`openai.py:72,80`), ollama 300s(`ollama.py:103,112`), 프로브 5s(`:51`), SDK는 미지 ② 실제 caller deadline = **없음**(예산 미사용) ③ `max_attempts` = 총 시도 3 기본(`external_jury.py:198`, `dispatch_retry.py:38,51`) ④ retry backoff = full-jitter, base 0.5s / cap **8.0s**(`dispatch_retry.py:39-40,65`)이고, `JURY_THRESHOLDS.backoff_cap_sec=300`(`external_jury.py:40`)은 **breaker의 회복 대기 상한**이다. 초기 보고의 "300초 backoff cap으로 갚는다"는 ④의 두 개념을 뒤섞은 오독이므로 철회한다. **300초 backoff가 실제 발생했다는 측정은 없다.**
4. **Windows/`&`/WSL** — 모두 조건부 가설로 하향한다. `subprocess.list2cmdline`은 CreateProcess 인용 규칙 직렬화이므로 cmd.exe 인용 정합성을 **증명하지도**, 특정 메타문자 경로가 **반드시 깨짐을 증명하지도** 않는다. WSL도 "항상 실패"가 아니라 PATH가 무엇을 해석하느냐에 달린 조건부다. 사실로 유지하는 것은 **코드 비대칭 자체**뿐이다: `ollama.is_available`은 bare `["ollama","list"]`(`:46-52`)로 `ask()`의 shim 분기(`:88-113`)를 적용하지 않고, `openai.py:82`는 `TimeoutExpired`만 잡아 `OSError`를 `anthropic.py:106`·`ollama.py:118`과 달리 통일 오류로 변환하지 않는다. 이번 Alpine 실행은 `which()`가 None이어서 shim 경로에 대한 증거를 **어느 방향으로도** 제공하지 않는다.
5. **토큰 지표** — codex stdout의 "tokens used" 언급은 `evaluator_dispatcher.py:578-584`의 **역사적 소스 주석**이며 현재 관측된 metric이 아니다("버려진 실측치"라는 표현 철회). 두 영수증 모두 `limits`에 토큰 측정 없음을 명시한다. 8,000바이트 임계의 **한국어 과소추정 확정도 철회**한다 — 바이트/토큰 비율은 모델·토크나이저 의존이며 미측정이다. 사실로 남는 것은 `research_extractor.py:219`가 `len(raw_blob.encode("utf-8"))`, 즉 **바이트 기준 임계**이고 `:26` 주석이 이를 "~2K 토큰"이라 부른다는 **주석과 단위의 불일치**뿐이다.
6. **인수 부재 범위** — "pinned tree 전체에 실제 vendor 인수가 없다"는 읽기 범위를 초과하므로 철회한다. 대신 이렇게 보고한다. *검토한 시험*: `test_providers_ollama.py` 전문, `test_external_jury_retry.py:17-116`, `test_seams.py:443-469`, `test_import_graph.py:48-129`. *이 체크포인트에서 확보된 실행 증거*: 위 두 영수증(자체검사 8건, unavailable 경로 관측). *여전히 없는 증거*: 실제 vendor 프로세스/모델 호출, Windows·WSL 실행, 토큰·비용, 사람 인수. `test_external_jury_retry.py:27-41`의 `_Fake`는 jury의 분류/breaker를 검증하며 **adapter 실행을 증언하지 않는다**. grep으로 간접 caller/test의 전면 부재를 증명할 수 없다.
7. **stdin 주장** — "전 경로 stdin이라 주입 회피"를 철회한다. 정확히는 **CLI 메인 프롬프트 채널만 stdin**이다(`anthropic.py:95-96`, `openai.py:66,76`, `ollama.py:99,109`) → 긴 프롬프트의 셸 인용 문제를 그 채널에서 회피한다. 반면 **모델·시스템은 argv**로 간다(`anthropic.py:90-92`의 `--model`/`--append-system-prompt`, `openai.py:40`의 `-m`, `ollama.py:75`의 `run <model>`). SDK 경로는 stdin과 무관하다. 그리고 codex/ollama의 `<system>` 래퍼(`openai.py:45-50`, `ollama.py:80-85`)는 **사용자 텍스트일 뿐 role 권위가 아니고 `</system>` 등의 이스케이프도 없다** — root :21,:27과 같은 결론이다.
8. **ollama self-check** — "모든 호스트에서 무해한 메타데이터 전용"을 철회하고 3분기로 다시 쓴다. ① **CLI 부재**(이번 이미지): `ask()`가 `which()` None에서 즉시 raise(`:63-65`) → 비침습, 8/8 통과가 이 조건의 증거다. ② **CLI 있고 모델 목록 없음**: `is_available` False(`:55-60`)인데 unavailable 분기가 **실제 `ask()`를 호출**하고 `ask()`는 which()만 요구하므로 **실제 `ollama run` 스폰이 가능**하다 — 자체검사 주석 `:189-191`의 "모델 스폰 회피"는 이 조건에서 보장되지 않는다(root :25와 일치). ③ **가용 호스트**: skipped ask를 `[OK]`로 계수하고 성공 시 detail을 숨긴다(`:201-203, 206-208`) → 공허 통과.
9. **breaker record_success** — 의도된 방어는 유지 인정한다: permanent 결함(코드/설정 버그)이 breaker를 오염시켜 교차-vendor 다양성을 죽이는 것을 막으려는 명시적 논증이다(`external_jury.py:152-156, 174-178`). 다만 "provider가 도달했다=available"은 **실제 응답을 확인하지 않은 추론**이므로 "추론에 도달했다"고 서술하지 않는다. 결함 주장은 유지한다: P1/정정2의 경로에서 디코딩·추출 실패가 **healthy 이벤트로 기록**된다.
10. **capabilities / cross-tree** — 읽기 경계를 명시한다. "소비자 0건"의 근거는 `.runtime/absorption/sources/baldrix/pinned/scripts` 하위에 대한 `capabilities` 및 `tokens_in|tokens_out` grep 결과이며, 문서·`get-shit-done/*.cjs`·markdown/skill 지시·중첩 저장소·내가 본문을 읽지 않은 모듈(`ensemble_evaluator.py` 전문, breaker 계열 등)은 **포함하지 않는다**. **미지의 추가 소비자 가능성은 열려 있다.**

## 3. 이견 / 조정

- 큰 이견은 없다. root 보고에 **없고 내가 유지하는 항목**: (a) timeout 예산 비대칭 — `SUBAGENT_TIMEOUT_SECONDS=270`의 논거(`evaluator_dispatcher.py:104-113`)는 codex 격리 경로(`:532`)에만 전달되고 `_invoke_ollama_evaluator`(`:753-803`)·`_invoke_claude_evaluator`(`:806-841`)에는 timeout 인자가 없어 adapter 하드코딩값이 그대로 쓰인다. (b) `model_router` — ollama 티어 미등록(`:96-109`)으로 `model="auto"`가 실패 기록 없이 기본값으로 강등(`external_jury.py:122,128`), 그리고 private `_REGISTRY` 결합(`:121`). (c) jury 합의 분모 — `_tally`(`:98-110`)의 `total`은 파싱 성공 verdict만 세는데 `members`/`raw_texts`에는 파싱 실패 멤버가 들어가므로(`:240-248`) `agreement`(`:260`)의 분모가 참여 멤버 수와 다르다. (d) 문서 drift 3건: `docs/subsystems/lib-providers-workers.md:5`의 provider 4종(레지스트리는 3종, `__init__.py:24-33`), 같은 문서 `:23`이 P7의 잘못된 예외 계약을 반복, `commands/harness-ask.md:4,16`이 ollama 미반영. 반면 같은 문서의 라인 참조(`anthropic.py:122`, `openai.py:98`, `ollama.py:136`, `__init__.py:31-32`)는 실제와 일치한다.
- root :27의 "local-only는 코드가 강제하지 않는다"에 근거 하나 추가: `ollama.py` 전문에 `OLLAMA_HOST` 등 엔드포인트 관련 참조가 없다(파일 내 env 참조는 `OLLAMA_DEFAULT_MODEL` 하나, `:69`). 즉 지역성은 **코드가 검사하지 않는 전제**다. 현행 vendor 동작은 주장하지 않는다.

## 4. 유지할 유효 방어

레지스트리 lazy import + `PROVIDER` 계약(`__init__.py:53-58`)으로 미설치 SDK가 import 시점에 전체를 죽이지 않음 — 이번 실행이 실증(CLI 3종 부재 이미지에서 세 모듈 모두 로드·인스턴스화 성공). CLI 메인 프롬프트의 stdin 채널(정정7 범위). codex의 read-only/`--skip-git-repo-check` **의도 선언**과 dispatcher의 env allowlist + `errors="replace"`(`:550,561`) — 원본 adapter보다 강화된 방향. `_PERMANENT_EXC` 화이트리스트 방식(미지 예외를 transient로 두어 breaker 쪽으로 fail-toward, `:42-49`)의 보수적 선택. permanent 시 breaker 오염 방지 의도(정정9 조건부). `system`이 세 CLI 경로에서 최소한 무시되지는 않음. `_extract_json_object`의 `parse_empty` 센티널(codex 한정, `:577-586`). `endpoint_query.py:90-91`, `jury_advisory.py:147-151`, `research_extractor.py:234-238`의 fail-soft 강등. `test_seams.py:443-469`의 LLM/network import 금지 강제. `dispatch_retry`의 full-jitter + "총 시도 수" 명시(`:51`).

## 5. 흡수(적용) 요건 — 승인 아님

root :39에 동의하며 실행 가능한 형태로 좁힌다. ① 오류 분류를 정규화(decode / auth / quota / invalid-argument / timeout / unavailable)해 `ValueError` 계열이 "healthy"로 흐르지 않게 하고, 분류 근거를 원장에 남긴다. ② decode 정책을 adapter에 명시(`errors=` + 원시 바이트 보존)하고 dispatcher 복제본과 단일화한다. ③ caller 측 **실제 deadline**을 도입하고 adapter timeout·max_attempts·backoff·breaker cap 4층을 분리 기록한다(`call_budget_sec` 같은 reserved 필드는 제거하거나 결속한다). ④ `AskRequest` 런타임 검증(components 관측이 필요성을 실증) + `max_tokens`/`temperature` 지원/미지원 행렬을 명시하고 미지원 시 조용히 버리지 않는다. ⑤ `capabilities`는 강제하거나 삭제한다. ⑥ `get_provider`가 가용성을 함의하지 않음을 문서·코드에서 통일하고, 이름 정규화(트림/타입)를 단일 오류로 수렴시킨다. ⑦ resolved executable/version, 종료 원인, argv/stdin 채널, usage provenance, request/artifact identity를 응답에 실어 PG runtime 원장으로 보낸다(현재 이 계층에는 원장 스키마가 없다). ⑧ 모델 자격은 실제 비교 가능한 시나리오 영수증으로만 부여하며, 원본의 운영자 결정(`evaluator_dispatcher.py:909-922`의 호스트 조건 pool 확장 + `allow_generator_family` 자동 완화)을 자격 승계로 쓰지 않는다.

## 6. 남은 시험 (미실행)

(a) 비-UTF8 바이트를 내는 **디코더 픽스처**(vendor mock이 아니라 바이트 방출 프로그램)로 P1의 permanent 오분류를 실측 — fake CLI 금지 정책과의 경계는 운영자 판단 필요. ① adapter 3종의 `errors=` 미지정 경로, ② `_classify_jury` 귀결, ③ breaker 기록값까지 한 번에 관측. (b) 추출부(`anthropic.py:73-86`) 예외의 분류 실측(정정2). (c) 실제 Windows 호스트에서 `ollama`/`codex` 설치 형태(.exe vs .cmd) 확인 후 `is_available` vs `ask` 비대칭 실측(정정4). (d) `&` 포함 경로 및 WSL PATH 해석 행렬의 실제 프로세스 시험. (e) ollama CLI 설치 + 모델 목록 비어 있는 이미지에서 self-check 분기 ②의 실제 스폰 여부(정정8) — 침습성 때문에 사전 승인 필요. (f) 빈 rc0 응답이 jury `responses`에 들어가 "전원 실패" 예외를 회피하는 경로(P6)의 실측. (g) `agreement` 분모 실측(파싱 실패 멤버 포함/제외). (h) SDK timeout·내부 재시도, 실제 토큰/비용, `--print`/`-s read-only`의 실효는 credential·네트워크가 필요해 **현 정책 밖**이며 미검증으로 유지한다. (i) 미읽은 소비자(`ensemble_evaluator` 전문, cjs 계층, markdown 지시 경로)의 추적.

## 7. 판정 경계

전체 분석 완료 아님, 흡수 승인 아님, 운영 준비 주장 아님. 이번 체크포인트가 늘린 것은 **unavailable 경로와 레지스트리/데이터클래스 계약에 대한 실측 8+관측 1건**이며, 실제 vendor 실행·Windows/WSL·토큰·사람 인수는 여전히 공백이다. 나는 독립 검토자로서 위 정정을 내 초기 보고에 우선하는 판단으로 남기고, 구현은 전체 분석 화해 이후 root가 수행한다.