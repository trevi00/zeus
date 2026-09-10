# 프로필 데이터 흐름은 안내가 정책에서 따라 나오는 버전 계약이고, 모델 입력 전에 최소화되며, 검사하지 않은 필드는 안전이 아니다

기존 FA-032 / GitHub [#33](https://github.com/trevi00/zeus/issues/33) / `ZEUS-1c4267ee50b8` 개정 1의 구현·검증 기록입니다.
상류 프로필 기능의 공동 검토([resolution](../../../full-analysis/baldrix-gsd-guidance-002/resolution.md),
[root-followup](../../../full-analysis/baldrix-gsd-guidance-002/root-followup.md))에서 동의 화면이 "외부 미전송·자동 제외"를 약속하지만
코드가 강제하지 않고, 샘플 content/projectPath가 redaction 전에 모델 입력 파일에 쓰이며, 출력 redactor는 `evidence`만 검사하고 렌더러는
`evidence_quotes`·summary·instruction·project를 검사 밖에서 출력하고, 카운터 0을 "None detected"로 표시함이 확인됐습니다. 실제
사용자 대화·자격증명·모델 전송은 이 기록에서도 다루지 않았으며(모든 입력은 합성 sentinel), 새 이슈나 분석 후보는 추가하지 않았습니다.

## Zeus의 현재 상태와 변경

- Zeus에는 프로필 수집 기능이 없습니다. 이 PR은 기능을 활성화하지 않고 **경계 계약과 그 강제 코드**만 넣습니다. 아무 대화도 읽지 않고
  아무 모델도 호출하지 않습니다.
- `domain/profile_privacy.py` (stdlib만):
  - `parse_policy`: version 1, purpose, 수집 fields(record 필드 5종 안에서)와 목적, read_scope(kinds/max_records/max_chars≤4000/projects),
    model(name, transport local|external), retention(temporary run|none, permanent profile_only|none), notice(text + 닫힌 claims).
    **안내는 정책이 강제하는 것만 주장**할 수 있습니다: `no_external_transfer`는 transport local일 때만, `raw_not_retained`는 permanent
    profile_only일 때만. 불일치는 정책 자체를 거절합니다. `policy_hash`가 계약 식별자입니다.
  - `parse_consent`: user·choice(grant/cancel/questionnaire)·policy_hash·at·projects. 다른 정책 해시 거절, read_scope 밖 프로젝트 거절.
    cancel/questionnaire와 프로젝트 없는 grant는 `collect: False`. 추론된 선호는 승인이 아니라는 note.
  - `scan`: private_key / credential(password·passwd·secret·비밀번호·암호) / token(sk-, ghp_, AKIA, xox, JWT) / email / user_path
    (`C:\Users\<u>`, `/home/<u>`, `/Users/<u>`, `/mnt/c/Users/<u>`, `\\wsl$\<d>\home\<u>`) / card_number(Luhn). 종류·위치·길이만 돌려주고
    값은 돌려주지 않습니다. `redact`는 `[REDACTED kind]`로 치환합니다.
  - `minimize(record, policy, consent)`: read_error(예외) / parse_error(비객체·미지원 필드·필수 누락·타입) / out_of_scope / not_consented
    / **blocked**(private_key·credential·token 하나라도 있으면 모델 입력이 되지 않음) / ready. ready는 정책 fields만 남기고 content를
    max_chars로 자른 뒤 스캔·치환하며 project_path는 비가역 `project_ref`로 바꿉니다. 검사하지 못한 필드는 `unchecked_fields`로 이름
    지어지고 원장에는 findings 계수만 남습니다.
  - `normalize_evidence`: `evidence`/`evidence_quotes`(문자열 또는 {quote,source,signal})를 하나의 스키마로; 둘 다 있으면 같아야 하고
    다르면 거절; 미지원 필드 거절.
  - `check_render(profile)`: 모든 차원의 evidence·summary·instruction·project·signal·metadata를 스캔. 텍스트가 아니거나 파싱 실패한
    필드는 `unchecked`로 이름 지어지고 verdict는 `unchecked_fields` / `findings` / `none_detected_in_checked_fields` 셋 중 하나이며
    "none"은 검사한 필드에 대해서만 말합니다.
- `adapters/profile_scratch.py`: 실행별 디렉터리 + owner/lease/digest sidecar. `write`는 원자적(temp+replace), 다른 owner의 실행은
  덮어쓸 수 없음; `read`는 digest 검증(불일치는 보존·미사용); `cleanup`은 owner만; `sweep`은 **만료된 lease만** 지우고 활성 lease와
  sidecar 없는 디렉터리는 이름 지어 보존합니다(시간·접두사로 삭제하지 않음).
- `application/profile_flow.py`: `record_consent` → `prepare_model_input`(사용자·정책 해시의 최신 동의가 grant일 때만; 결과별 계수,
  findings 종류 계수, binding(revision·environment), 번들 파일 참조; **원장 행에는 레코드 텍스트가 없음**) → `render`(check_render
  결과를 실행에 결속, renderable은 unchecked/findings 없음일 때만) → `finish`(owner만 정리).
- `docs/contracts.md`: `INV-PROFILE-001`.

## 재현과 검증

- `tests/test_profile_privacy.py`(7 검사; 합성 sentinel만 사용):
  - 안내 claims 대 정책: external transport에 "외부 미전송" 주장 → 거절, 정직한 external 안내는 통과; permanent none에 "원문 미보존" 거절;
    잘못된 정책 5종 거절.
  - 동의: grant만 collect; cancel/questionnaire/프로젝트 없는 grant는 수집 없음; 다른 정책 해시·범위 확장·미지 choice 거절.
  - 스캔: 영문·한국어 credential 2, token 2, email 1, Windows/Linux/WSL 경로 4, Luhn 통과 카드 1(다른 숫자열은 제외), private key 1;
    평범한 한국어 문장 0; surrogate 문자 포함 텍스트 처리; 슬래시 방향이 달라도 같은 project_ref; bytes 거절.
  - 최소화: email·경로 치환 + 세션 필드 드롭, 값이 원장/입력 어디에도 없음; password 레코드는 `blocked`(입력 없음, 값 없음); 동의 밖
    프로젝트·범위 밖 kind·cancel 동의는 각각 이름; 읽기/파싱 실패 5종은 unchecked_fields 개수와 함께 입력 없음; 300자 cap이 모델 입력
    전에 적용(뒤쪽 password는 잘려 나감을 truncated로 표시).
  - 렌더: quotes 문자열 정규화, 동일 양식 통과, 불일치·미지원 필드·weight 거절; evidence_quotes 경로·summary 비밀번호·project 경로가 각
    필드에서 잡히고 metadata 중첩 객체는 `paths.metadata` unchecked → verdict `unchecked_fields`; 깨끗한 프로필만 `none_detected_in_
    checked_fields`; 충돌 evidence는 parse_error + unchecked.
  - 흐름(MemoryStore + 실제 scratch 디렉터리): 동의 없음 거절; cancel 동의는 `not_consented`·번들 없음; grant 후 계수 {ready 1, blocked 1,
    not_consented 1, read_error 1, parse_error 1}, findings {token 1}, 원장에 텍스트 없음, 번들에는 ready 1건만; 입력 없는 실행은 render
    거절; 경로가 든 summary는 renderable False; 다른 worker의 finish 거절, owner finish로 디렉터리 삭제.
  - scratch(실제 자식 프로세스): 번들을 쓴 뒤 exit 3으로 죽은 자식의 번들이 보존되고 owner만 읽음/재개(2건으로 갱신); 다른 owner의
    write/read/cleanup 거절; sweep은 만료 lease만 삭제, 활성 lease와 sidecar 없는 디렉터리는 보존·이름; 바이트 변조는 digest 불일치로
    보존·미사용; sidecar 없는 디렉터리 cleanup 거절; 없는 실행은 `absent`.
- 음성 대조군([target-tests.json](target-tests.json) `negative_controls`).

| 항목 | 결과 |
|---|---|
| `tests/test_profile_privacy.py` + `test_architecture.py` | 11 passed |
| Windows 전체 `uv run python -m pytest -q` (Python 3.12, PG 검사는 skip; main `1488468` 위에서) | 956 passed, 310 skipped, 1 failed: `test_github_tickets.py::test_remote_manual_close_is_a_conflict_not_local_acceptance[memory]` — 이 PR과 무관한 기존 flaky(단독 3회 24 passed) |
| `uv run ruff check .` | 통과 |

## 남은 범위

- 실제 사용자 대화 수집, 실제 모델 호출·전송, 사용자 안내 화면, 설문 UI, 보존·삭제 정책의 운영 적용은 없습니다. 스캔 패턴은 필요한
  종류를 합성 입력으로 검증했을 뿐 일반 재현율·오탐률을 측정하지 않았고, 이름·주소 같은 자유 텍스트 개인정보는 패턴 범위 밖입니다.
  Windows ACL 권한 오류는 실측하지 않았습니다. 단위 fixture 통과는 사용자 인수·모델 자격·배포 완료가 아닙니다.
- 이슈 종료는 Codex·Claude 독립 검토와 인수 기준 확인 뒤 [#30](https://github.com/trevi00/zeus/issues/30) 범위의 종료
  경로를 따르는 별도 단계이며, 이 기록은 검증 증거이지 배포 승인이 아닙니다.
