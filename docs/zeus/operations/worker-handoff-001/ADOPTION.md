# worker-handoff-002 채택 기록

2026-09-18. 기준 리비전 47ec982288e154f952b5a8d034d5cea8eeabc409. SPEC.md의 Continuation 002가
이 배치의 지시이며, 첫 시도(worker-handoff-001)의 실패 결과와 증거는 그대로 남긴다.

## 무엇을 바꿨는가

- `src/codex_harness/resources/worker-profile-v1.md`: wording.json의 18개 old/new 교체와
  Reporting 절 삽입 1건을 Edit로 순서대로 적용했다. 다른 문구는 고치지 않았다. 결과 5906자
  (LF 정규화), SHA256 `4a353bf3f4745d2203944290738a5c95d207e796189ee6d513bccdd2bd10b991`.
  SPEC와 wording.json이 예고한 값과 같다.
- `src/codex_harness/resources/worker-profile-v1.json`: `document_sha256`만 위 값으로 바꾸고,
  source.json 내용을 9번째 source로 그대로 추가했다. 기존 8개 source, id/version, hook 해시,
  6000자 한도, hooks, permissions, note는 손대지 않았다.
- `tests/test_worker_profile.py`: 기존 source 개수 단언 8 -> 9 한 곳만 바꿨다. 인접한
  permission/hook/manifest 키 순서 단언은 그대로다. 새 테스트는 추가하지 않았다.
- 이 문서(ADOPTION.md) 신규 작성.

## 채택한 원칙과 거부한 원칙

원천: baldrix `skills/_common/handoff-clear-trigger.md`, commit
cbb5c3e6c9c4af6f86626474f4d7d62fd8e8a6d2, blob 0388365162155a528aedc3b1270855028117bf85,
pinned SHA256 a19c8bfc8148b0a5247112398eef14f790f5752542c570406835c172a1a4ec58. 원문 텍스트나
실행물은 복사하지 않았고, 원칙만 worker-v1 문맥으로 다시 썼다.

채택 (Reporting 절의 두 항목):
1. 완료·중단·예산 정지 시 보고가 가능하면 기존 summary 또는 배정된 artifact에 목표/기준,
   검증된 완료와 남은 작업을 분리해 기록한다.
2. 알려진 리비전과 증거 참조, 실패·미실행 검사, 미지 사항을 명시한다. 신원이나 파일을
   지어내지 않는다.
3. 기존 범위 안의 다음 행동 하나와 그 전제·정지 조건을 준다. 막힌 전제는 보고하고, 무관한
   대체 작업이나 예산 갱신으로 바꾸지 않는다.
4. 이어받을 때 효과를 내기 전에 현재 권위 있는 task/state와 대조한다. 오래되거나 충돌하거나
   알 수 없는 상태는 리드에게 넘긴다. 산문은 승인·재제출·예산을 부여하지 않는다. 강제
   clear/reset 없음, 호스트 절대 경로 하드코딩 없음.

거부: 원천의 사설 반복 임계값, 복구 비용 0 주장, 강제 /clear, 대체 작업 발명, 수정 가능한
HANDOFF 파일의 권위. 라이선스는 검증하지 않았다.

## 단일 진실 원천(SSOT)

- 프로필 정의는 Git의 `worker-profile-v1.md`와 manifest이며, 최종 바이트의 유효성은
  `worker_profile.load_profile`과 프로필 테스트가 판정한다. metadata 유틸리티는 관측만 한다.
- 이 산문 지침은 큐 항목, 승인, 예산, PostgreSQL 지식 승격을 만들지 않는다. 런타임, 훅,
  권한, 한도는 바뀌지 않았다.
- 원천 식별은 source.json과 manifest의 9번째 source가 고정한다.

## 실제로 실행한 검사

- `python -m codex_harness.adapters.worker_profile_metadata` 편집 전: exit 0, 5988자, digest
  `3dba9d3b...` 일치. 편집 직후: exit 1 (manifest가 옛 digest라 mismatch), 5906자, digest
  `4a353bf3...`, within_limit true. manifest 갱신 후 재실행: exit 0, status ok,
  digest_matches true, 5906자.
- `python -m pytest tests/test_worker_profile.py -q -p no:cacheprovider`: 20 passed, 실패·skip 0.
- `python -m ruff check .`: All checks passed.
- 실행하지 않은 검사는 통과로 적지 않는다. 전체 pytest 스위트는 실행하지 않았다.

## 한계

- 첫 시도(worker-handoff-001)는 코드 변경 0건으로 실패했고, 원인은 문서 여유(12자) 미배정과
  테스트 파일 미허용이었다. 이번 배치는 그 두 가지를 wording.json과 허용 경로로 고쳤다.
- 이번 실행은 옛(배포된) 프로필 아래에서 이뤄졌다. 새 문구가 실제 워커 행동을 바꾼다는
  주장은 하지 않으며, 이번 호출이 새 지침을 따랐다는 증거도 아니다.
- 전체 pytest 스위트는 이 배치의 지시(focused 명령 2개 + metadata)에 따라 워커가 실행하지
  않았다. 독립 검토와 소유자 수용, PR/CI 릴리스는 별도 단계다.
- 축약된 기존 문구가 원래 안전장치와 의미상 동등한지는 소유자의 매핑 검토에 의존한다.
  글자 수 감소만으로 동등성을 주장하지 않는다.
- 변이 테스트나 추가 행동 canary는 SPEC에 따라 수행하지 않았다.
