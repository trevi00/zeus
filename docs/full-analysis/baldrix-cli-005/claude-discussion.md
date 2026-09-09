독립초안, 영수증, 두 타임존 관측을 모두 읽었다. 공동 토론 결과를 보고한다.

# 공동 토론 결과 — baldrix `scripts/cli` 005

## 증거 등급 (이 보고서 전체에 적용)

- **[A] 격리 실행 관측** — root 가 원본 unit module / 원본 함수를 격리 Linux 이미지(network none, read-only bind, cap-drop ALL, non-root)에서 돌린 결과. `scripts/tests/test_telemetry_report.py` 19 PASS(rc=0, stderr 빈 해시), 그리고 UTC0/KST-9 각 1회의 원본 함수 관측. **mock 없음, 임시 입력.**
- **[B] 정적 추론** — 소스 독해만. 실행 아님.
- **[C] 미검증** — 읽지 않았거나 확정 불가.

**원본 실행 범위의 한계(양측 합의)**: A 급은 텔레메트리 리포트 **한 모듈의 원본 유닛 테스트**와 개별 함수 호출뿐이다. E2E 아니고, 인수 아니고, 전체 실행 아니다. 모델 호출·훅 경로·Windows/WSL·live state 는 전혀 건드리지 않았다. 소스 트리 해시 불변(`source_bytes_unchanged: true`)이 확인되어 원본은 변형되지 않았다. **전체 흡수 완료·승인은 여전히 불가.**

---

## 1. 관측이 확정한 것 [A]

| 관측 | UTC0 | KST-9 | 판정 |
|---|---|---|---|
| `_ts_to_epoch("2026-05-01T06:15:35Z")` | 1777616135.0 (delta 0) | 1777583735.0 (**delta −32400**) | UTC 문자열을 로컬로 해석 — 확정 |
| 1분 전 이벤트, `--since` 1시간 | kept 1건 | **kept 0건** | KST 에서 최신 이벤트가 창에서 탈락 — 확정 |
| error-only hook (duration 없음) | `{}` | `{}` | 훅이 리포트에서 **통째로 사라짐** — 확정 |
| `duration_ms=True` | n=1, p50 1.0ms | 동일 | bool 이 측정값으로 계상 — 확정 |
| `ts` 가 숫자 | AttributeError | 동일 | 필터가 예외로 죽음 — 확정 |
| `--since` NaN | 수용 | 수용 | 파싱 단계 통과 — 확정 |
| `package.json` / `pubspec.yaml` 루트 | 발견됨, **results 0, exit 0** | 동일 | 프런트엔드 검증 0건인데 성공 — 확정 |

두 타임존 사이 **차이가 나는 항목은 시간 관련 둘뿐**이고 나머지는 동일하다. 즉 시간대 결함은 격리되어 있고 다른 결함은 환경 독립이다.

---

## 2. 내 초안의 정정 (요청 7건 전부 수용)

**2-1. team_watch NOT_STARTED — 내가 과장했다.** "전면 도달 불가"는 틀렸다. `_refresh` 는 매 프레임 `_classify` 를 다시 부르므로, 발견 후 파일이 지워지거나 접근 불가가 되면 NOT_STARTED 가 실제로 렌더된다. 정확한 진술은 **"시작 시 discovery 에 없던 expected worker 는 영원히 보이지 않는다"** — 즉 결손이 아니라 *미출현* 이 문제다. DONE 경로는 `commands/harness-team.md:160–167` 재확인 결과 rc 무관 최종 `DONE` 이 맞다. 다만 `_exit_code`==1 불가는 **"워커가 래퍼를 완주하고 그 꼬리가 유지된 경우"로 한정**해야 한다 — 워커 산문이 꼬리를 덮어쓰거나, 외부 캡/절단이 걸리거나, 강제 종료로 `DONE` 이 안 붙으면 FAILED 판정은 가능하다. all-FAILED 에서 `--exit-on-done` 이 자동 종료하지 못하는 것은 맞으나 **"영원히"는 틀렸다** — Ctrl+C(`KeyboardInterrupt` 처리 존재, 346)나 외부 종료로 빠져나온다.
*Codex 추가 채택*: `_grid_dims` 는 n>9 에서도 (3,3) 이라 **10번째 이후 워커는 헤더 집계에는 들어가지만 패널이 없다.**

**2-2. telemetry env — 내가 틀렸다.** `paths._resolve_telemetry_root`(178–179)는 실제로 `CLAUDE_TELEMETRY_DIR` 를 본다. 내가 인용한 "상수가 env 를 안 본다"는 **수정 이전 상태를 서술한 과거 주석**이었고, 그걸 현재 코드 진술로 옮긴 것은 오류다. 정확한 잔여 위험은 하나뿐: **import 시점 고정** — 한 프로세스에서 import 이후 env 를 바꾸면 상수(`TELEMETRY_DIR`)와 함수(`telemetry_dir()`)가 갈린다. 별도 프로세스로 뜨는 훅·런처에서는 문제되지 않는다.
서쪽 타임존 진술도 정정: "아무것도 안 걸러진다"는 과장이고, 정확히는 **오프셋만큼 미래로 밀려 경계가 오프셋만큼 어긋나며, 충분히 오래된 이벤트는 여전히 제거된다.**

**2-3. threshold — 반례는 유지, 전이 주장은 철회.**
- NaN 이 `_is_risky` 의 두 비교를 모두 False 로 만들어 **safe 로 분류된다**는 것은 [B] 로 유지(양측 동의).
- 그러나 "모든 call-site 게이트 무력화 / inf 영구 fail-closed"는 **철회한다.** 각 술어의 방향은 호출부마다 다르고 전이 검토를 하지 않았다. 게다가 `threshold_registry.py:62–66` 이 스스로 적는다 — **live 배선이 있는 항목은 `FULL_BODY_MIN_SCORE` 하나뿐이고 나머지 넷은 "override-inert"** 다. 그 하나는 `direction_safety="either"` → 항상 risky → graduate 토큰 + ready-flag 를 요구한다. 즉 **약한 토큰으로 NaN 을 넣을 수 있는 항목들은 현재 배선이 없다.** 도달성은 내가 쓴 것보다 훨씬 낮다.
- 부분 YAML 손상도 정정: `_safe_yaml_load` 는 줄 단위 파서라 **파싱 가능한 남은 키는 유지된다.** "모든 값이 default 로 되돌아간다"는 틀렸다.
- "유일한 non-atomic 정책 writer" 범위도 정정: `critic_policy._save_policy:157` 이 **동일한 `write_text` 패턴**이다. 고립된 결함이 아니라 정책 writer 계열의 공통 패턴이다.
- min/max: `TunableThreshold`(28–43) 전 필드 재확인 결과 **경계 필드는 없다** — 이 진술은 유지. `step` 미적용도 유지.
- 리터럴 토큰: **비밀 유출 주장은 철회한다.** 공개 리터럴은 secret 이 아니고 애초에 그렇게 설계됐다(`docs/subsystems/cli.md:95` 가 "defense-in-depth, not a boundary"라고 명시). 남는 정확한 지적은 **문서는 env 공급(`HARNESS_MUTATION_TOKEN`)이라 하는데 코드는 `--token` argv 로 받는다**는 계약 불일치뿐이다.
- **SSOT 요약에서 writeback 과 threshold 를 섞지 않는다**: writeback 토큰은 `os.urandom(16)` 기반 무작위 minted 토큰이고, threshold 토큰은 소스 리터럴이다. 성질이 다르다.
- *신규 [B], 정밀화*: `_is_risky` 는 **현재 유효값이 아니라 registry `default` 를 기준**으로 방향을 판정한다. `raise_safe` 항목에서 override 가 이미 10(default 3)일 때 10→5 는 실질적으로 위험 방향인데 `5 > 3` 이라 **safe 로 분류되어 약한 토큰만으로 통과**한다. 래칫을 되감는 경로가 열려 있다. (Codex 가 "default 기준 비교"라고 지적한 대상은 no-op 검사가 아니라 이 함수여야 정확하다 — 아래 §3 참조.)

**2-4. trending — 내 가장 큰 오류. "아무것도 고치지 않는다"는 보장을 철회한다.**
`open_gaps()` → `_unapplied_changes()` → `for ch in CHANGES.values(): ch.canary()` 이고, `lib/pending_changes.py` 의 canary 들은 **읽기가 아니다**:
- `_canary_settings_dead_rule`(537) → `_headless`(522) → **`subprocess.run(["claude","-p",...])`** — 실제 헤드리스 모델 호출(timeout 240s), 그리고 보호 경로에 프로브 파일 쓰기를 시도시킨다.
- `_canary_collector_path_keying`(364) → **실 skills 트리에 `zz-canary-probe/SKILL.md` 를 쓰고** 매처를 subprocess 로 돌린다(timeout 180s).
- 다른 canary 들도 `state/` 하위 write, `engine/inventory_scan.py` subprocess 를 포함한다.

따라서 `cli.trending gaps` 와 `enqueue --dry-run` 은 **문서가 말하는 읽기 전용 파생/프롬프트 출력이 아니다.** 초안의 "이 파일의 쓰기는 큐/원장 append 뿐"은 취소한다. 전이 효과의 전체 목록은 [C] 로 남긴다(6개 canary 중 2개만 본문 확인).
*Codex 지적 채택*: `cmd_report` 는 raw 원장 + inline `text`/`artifact` 만 본다. `resident_store` 는 `read_ledger(with_payloads=True)` 와 `_rehydrate`(370)를 제공하지만 trending 은 쓰지 않는다. `PAYLOAD_KEYS=("text","artifact")`, `PAYLOAD_KEEP=20` 이므로 **최근 20행 밖으로 밀린 정상 보고는 "계약 JSON 을 못 뽑았다"로 표시된다** — 성공한 과거 판정이 파싱 실패로 보인다. [B]

**2-5. validate_project — 관측으로 대체.** `ROUTING`(57–71)에 **ts-fe / flutter 할당이 0개**이고, 그 결과 [A] 로 확인된 대로 서브루트를 발견하고도 `results: []`, `counts` 전부 0, **exit 0**. 프런트엔드/Flutter 저장소에서 이 도구는 "통과"를 반환하지만 아무것도 검사하지 않는다. 추가로 `_format_table:201–202` 는 `not summary.results` 일 때 **"(no subroots detected)"** 를 인쇄한다 — 발견했는데 못 찾았다고 말한다. [B]
정정: "main 반환값 무시로 13개 validator 실패가 누락된다"는 **입증하지 않았다.** 코드 경로가 반환값을 버리는 것은 사실이나(157–158), 현재 13개가 실제로 그 경로로 실패를 흘리는지는 전수 확인 안 함 → [C]. root/java-be 중복(`contract`, `ddl`)도 "같은 파일 두 번"이라 단정하려면 각 callee 의 탐색 범위를 읽어야 한다 → [C] 로 강등.

**2-6. writeback — 신용과 결함을 다시 나눈다.**
- **`consume` 의 단일사용 크레딧을 철회한다.** 재독(169–228): read → 검사 → `unlink()` 를 `except OSError: pass` 로 감싼 뒤 **무조건 OK 반환**. 동시 소비자 둘이 같은 파일을 읽고 둘 다 검증 통과, 한쪽 unlink 실패가 삼켜져 **둘 다 OK 를 받는다.** compare-and-swap 이 없다. 주석의 "atomic unlink"는 unlink 한 연산만 원자적이라는 뜻이지 게이트 전체가 원자적이라는 뜻이 아니다. [B]
- **TOCTOU 폐쇄도 부분으로 정정.** 단일 캡처 바이트 재사용(444–456, 484–487)은 *sha 검사와 변형 대상의 불일치* 를 없앤 실제 개선이며 신용을 유지한다. 그러나 **capture→replace 사이의 외부 변경은 여전히 잡히지 않는다.** "전체 TOCTOU 폐쇄"는 틀렸다.
- **CRLF 도 한정한다.** "항상/구조적 불가능"은 과장. 정확히는 `apply_hunk_to_text:212` 가 `split("\n")` 이므로 **old-side 컨텍스트/삭제 줄이 존재하고 대상이 CRLF 인 경우**, LF diff 와 슬라이스 비교가 어긋나 HUNK_MISMATCH 가 된다. `old_count==0` 인 순수 삽입(216–226)은 슬라이스 비교를 하지 않으므로 통과할 수 있다(대신 CRLF 파일에 LF 줄이 섞여 들어간다).
- **denylist "정규화 없음" 주장 금지 — 동의.** `path_denylist.canonicalize`(91–127)는 expanduser/expandvars → realpath → (Windows·존재 시) GetLongPathNameW → normcase 를 하고 실패 시 fail-closed 다. 실재하는 방어다. 정확한 잔여 지적은 **양성(positive) 봉쇄가 문자열 정규식이라는 것**: `_SKILL_TARGET_RE`(163–166)는 파서가 낸 **미해결 경로 문자열**에 `.claude/skills/` 포함 + `.md` 종료 + `_meta` 아님만 본다. `Edit.target_path` 주석(43)은 "canonical file path (post-denylist canonicalization)"라고 적지만 **`_validate_target` 은 정규화된 값을 되돌려 쓰지 않는다** — 데이터가 주석의 주장을 담고 있지 않다. 그리고 apply 시 `_resolve_target_abs` 가 `Path.home()/".claude"` 에 붙여 `.resolve()` 한다 → **자산 루트 하위 봉쇄가 해결경로 기준으로 검사된 적이 없다.** [B]
- *신규 [B]*: `parse_proposal:207–210` 은 `read_text(encoding="utf-8")` 를 **`OSError` 만** 잡는다. 비-UTF8 strike 아티팩트는 `UnicodeDecodeError` 로 `preview/arm/apply` 밖으로 트레이스백을 낸다. 손상 입력 방어가 읽기 경로에는 있고 이 경로에는 없다.
- *Codex 추가 채택*: 토큰이 묶는 것은 (proposal_id, 조인된 preimage 해시)뿐 — **검토된 패치 해시나 정규 대상 신원은 묶이지 않는다.** arm 과 apply 사이에 아티팩트가 바뀌어도 preimage 만 같으면 통과한다. 롤백은 사이드카 바이트를 원본 preimage 해시와 대조하지 않고, 감사된 대상 집합과의 일치도 요구하지 않으며, 부분 복원 후 보상이 없다. 격리(quarantine) 쓰기 성공 여부는 무시된다. `mark_applied` 반환값을 롤백은 무시하고 성공을 인쇄한다.

**2-7. 서술 정정.** 초안에서 "지원 전문(4)"라 쓰고 5개를 나열했다 → **지원 전문은 5개**(`threshold_policy`, `writeback_token`, `telemetry_read`, `axis_scores_log`, `paths`)다. 경로 표기 `tests/` → **`scripts/tests/`**. `test_team_watch*` 파일명 부재는 **"테스트 전무"의 증명이 아니다** — 다른 파일에 포함됐을 수 있다(확인 안 함, [C]). grep 결과와 부분 독해를 커버리지 판정이나 원본 E2E 실행으로 쓰지 않는다.

---

## 3. Codex 초안에 대한 내 정정

1. **`threshold_policy.apply_override` 는 존재하지 않는다.** 실제 이름은 `apply_threshold_override`. `apply_override` 는 `critic_policy` 쪽 이름이다.
2. **"Comparison uses the registry default rather than the effective current override"는 대상이 틀렸다.** no-op 검사(140)는 `resolve_threshold(name, entry.default)` 를 쓰므로 **유효 현재값**을 본다. default 기준 비교라는 지적이 맞는 곳은 `_is_risky`(105–112)이며, 거기서는 실제로 위험 방향 판정이 틀어진다(§2-3 마지막 항목). 지적 자체는 유효하나 위치를 옮겨야 한다.
3. **"미래 타임스탬프도 RUNNING"** — 맞다. 다만 `_format_elapsed(time.time() - mtime)` 이 음수를 받아 `-3s` 같은 표시를 낸다는 점까지 붙이면 정확하다.
4. Codex 의 나머지 항목(에러 전용 훅 은닉, bool 측정값, sid 선집계, 회전 이력, ts-fe/flutter 무배선, consume 동시성, 사이드카 검증 부재, 양성 봉쇄가 정규식)은 **전부 동의**하며 위 관측/재독으로 뒷받침된다.

---

## 4. 양측 합의된 핵심 결론

1. **관측 계층이 관측 대상을 신뢰 가능하게 보고하지 못한다.** telemetry_report 는 시간대(A), 회전(B), 오류 전용 훅 은닉(A), bool 계상(A), 숫자 ts 예외(A)로 분모가 흔들리고, `--evaluator-accuracy` 는 **독립 정답 오라클 없이 자기 신고 verdict 분포**를 accuracy 로 라벨링한다(B, 양측 동의). 토큰 회계는 존재하지 않는다.
2. **"검증됐다"는 신호가 검증 없이 발급된다.** validate_project 는 프런트엔드에서 검사 0건 · exit 0 을 낸다(A). team_watch 는 완주한 실패 워커를 DONE 으로 표시한다(B, 한정).
3. **정책 변경 경로는 사람 확인 의례이지 인가 경계가 아니다** — 이는 원본 문서 스스로의 입장이기도 하다. 원자성은 threshold/critic 정책 writer 계열에서 미확보, writeback 은 상당 수준 확보하되 `consume` 동시성과 롤백 검증에 구멍이 있다.
4. **읽기 전용으로 문서화된 명령이 모델 호출과 실 트리 쓰기를 유발한다**(trending → pending_changes canary). 이 범위에서 문서-행동 괴리가 가장 큰 항목이다.
5. **Zeus 자격**: 이 6개와 확인한 지원 lib 어디에도 PostgreSQL runtime SSOT 접점이 0건이고, Git 리비전을 진실 근거로 쓰는 곳도 0건이다(상태는 JSONL/YAML/JSON/flag/token/sidecar 파일). 사람 인수 흔적은 `HANDOFF.md` 의 DONE 표기뿐이며 그것은 코드 존재의 DONE 이지 동작 인수가 아니다. **Astra→Sol→Terra 승격 근거로 쓸 수 없다.**

---

## 5. 잔여 · 미검증 [C]

- `pending_changes` 6개 canary 중 4개의 본문과 전체 전이 효과 · 실제 소요 시간.
- `ORCH_SID` 와 `~/.omc/team/<sid>` 디렉터리명의 동일성(team_watch 메일박스 패널의 전제).
- import 시점에 cwd 파생 상수를 굳히는 validator 존재 여부, 13개 validator 의 `main` 반환 규약 전수, `contract`/`ddl` 중복 실행의 실제 탐색 범위 중복 여부.
- `resident` 의 스테일 running-마커 GC/멈춤 탐지 구현 위치.
- Windows junction/별칭, 경로 구분자, 동시 변형, 롤백 크래시 복구의 실제 검증.
- team_watch 관련 테스트가 다른 파일에 존재하는지.
- `--since` NaN 이후 `int(nan)` 로 인한 렌더 실패는 [B] (관측은 파싱 수용까지만 기록).
- 전체 테스트 스위트 실행 결과 없음 — A 급은 `test_telemetry_report` 단일 모듈뿐.

**티켓 처리**: writeback 신규 항목은 추가 전에 기존 FA-012(지표/게이트 증거)·FA-009 와 중복 제거가 필요하다(Codex 제안 동의).

**이 문서는 공동 토론 결과이며 전체 분석 완료도, 흡수 승인도 아니다.** 원본은 이 세션에서 변형되지 않았고(트리 해시 불변 확인), A 급 실행은 격리 이미지 안의 원본 유닛/함수 관측으로 한정된다.