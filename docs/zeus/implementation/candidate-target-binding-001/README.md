# 후보 적용 계약: 대상 저장소·패치 해시·preimage/postimage 결속

기존 FA-015 / GitHub [#16](https://github.com/trevi00/zeus/issues/16) / `ZEUS-39d3d0633060` 개정 1의 구현입니다.
Baldrix CLI005 공동 검토에서 writeback token은 proposal ID와 preimage 해시만 묶고 검토한 patch hash·정규 target
identity를 묶지 않았고, consume은 read/check/unlink를 직렬화하지 않은 채 unlink 오류를 삼켰으며, rollback은 감사된
대상 집합과 sidecar 선언·preimage 일치를 요구하지 않았습니다([CLI-005 공동 검토](../../../full-analysis/baldrix-cli-005/resolution.md)).
교차검토 합의는 "개선 제안 적용 계약에 immutable proposal/patch/revision/환경/정규 대상 ID와 preimage/postimage 해시를
결속"입니다. 새 이슈나 분석 후보는 추가하지 않았습니다.

## Zeus 상태와 변경

Zeus의 적용 단위는 파일 writeback이 아니라 Git 후보(`revision`·`base`·`tree`)의 검토·검증·병합·승격입니다. 이미 리뷰는
revision에, 검증은 revision+policy hash에, 승격 intent는 candidate 해시·이미지·remote에, 배포 포인터는 CAS에 결속되고
병합 전후 tree를 확인합니다. 남아 있던 틈 둘:

1. 후보 자체가 **대상 저장소**를 갖지 않아, 리뷰와 승격 사이에 `HARNESS_GITHUB_REPO`가 바뀌면 같은 revision의 리뷰가 다른
   저장소로 소비될 수 있었습니다(승격 intent는 그 시점의 remote만 기록).
2. **패치 내용**은 commit 해시에 암묵적으로만 묶여 있었고, 런너의 `inspect`가 다시 계산한 diff는 tree 비교에만 쓰였습니다.

- `adapters/git.capture()`: 후보에 `repository`(설정된 GitHub slug, 없으면 `local`)와 `diff_hash`(base→revision diff의
  SHA-256)를 넣습니다. 이 값은 후보 identity(`digest(candidate)`)에 포함되어 리뷰·검증·승격 intent가 함께 결속됩니다.
- `git.merge()`/`git.publish()`: `require_target` — 다른 저장소용 후보는 거부. `merge`는 diff 해시도 재계산해 비교.
- `deployment.ReleaseRunner._run`: `inspect`의 diff 해시가 후보의 `diff_hash`와 다르면 `Candidate patch mismatch`;
  후보 저장소가 현재 remote와 다르면 검사·카나리아 전에 거부. `_promote`도 같은 검사를 수행합니다.
- 필드가 없는 기존 후보(FA-015 이전 캡처)는 그대로 처리됩니다(호환).
- `docs/contracts.md`: `INV-RELEASE-001`에 문장 추가.

## 재현과 검증

- `tests/test_git_workspace.py::test_capture_binds_target_repository_and_patch_hash_and_merge_rechecks_them`: 실제 Git
  저장소에서 캡처한 후보가 `repository=local`·`diff_hash=digest(inspect.diff)`를 갖고, remote가 설정된 어댑터의 merge/publish는
  거부, 변조된 diff_hash는 `Candidate patch changed`, 거부 경로는 main을 건드리지 않음, 레거시 후보는 병합 가능.
- `tests/test_release_runner.py::test_runner_refuses_reviewed_candidate_whose_patch_or_target_drifted[patch|repository]`:
  두 리뷰가 승인된 release라도 diff 해시 불일치 / 저장소 불일치면 검사 실행 전에 거부하고 release는 `reviewed`로, intent·
  배포 포인터는 생성되지 않음.
- 기존 `test_release_recovery`의 원격 시나리오 두 건은 remote를 캡처 **전**에 설정하도록 fixture를 고쳤습니다(캡처 후 remote
  변경은 이제 정확히 거부되는 drift입니다).
- 음성 대조: `git.py`·`deployment.py`를 수정 전으로 되돌리면 신규 검사가 실패합니다.

| 항목 | 결과 |
|---|---|
| git workspace + release 5개 모듈 + ticket execution | 47 passed, 31 skipped(PG/integration) |
| Windows 전체 `uv run pytest -q` (Python 3.12.14) | 920 passed, 305 skipped (169s) |
| `uv run ruff check .` | 통과 |

## 검토 반영 (PR #48, P1: 서로 다른 로컬 저장소가 같은 `local` 대상으로 취급됨)

- `adapters/git.target_identity()`: remote가 있으면 `canonical_remote()`로 정규화한 `github:owner/repo`
  (slug·https·ssh·`.git`·대소문자 무관, GitHub 외 호스트는 거절), 없으면 `git rev-parse --git-common-dir`를 매번
  다시 읽은 절대 경로 `local:<common-dir>`입니다. A를 B로 clone하면 identity가 달라 B의 `merge()`는 `Candidate
  target repository changed since review`로 거절되고 B는 손대지 않습니다.
- `require_target()`은 `verified`/`legacy_unverified`를 돌려주고 merge 결과에 `target`으로 남깁니다. `repository`가
  없는 레거시 후보는 계약의 명시적 예외이며 검증된 대상이 아닙니다(실제 승격 전 재검토 대상). `deployment.py`는
  `git.target_identity()`를 그대로 사용합니다.
- 회귀: `test_another_local_repository_is_another_target`(실제 Git clone), `test_remote_spellings_normalize_to_one_
  target`, 기존 검사의 `local` 문자열 기대를 identity 값으로 갱신, release runner 드리프트 검사는 정규화된 identity
  사용.

## 남은 범위

- 상류의 단일 소비 토큰(consume의 read/check/unlink 직렬화)은 Zeus에 대응물이 없습니다 — 승격 intent는 PG 트랜잭션 안의
  CAS로 한 번만 만들어집니다(FA-004 계약). 다중 파일 부분 변경은 Git commit 단위라 발생하지 않습니다.
- rollback은 `INV-RECOVERY-001`의 외부 컨트롤러·known-good 이미지 경로이며 이번 변경 밖입니다.
- 이슈 종료는 Codex·Claude 독립 검토와 해당 개정 인수 기준 확인 뒤 [#30](https://github.com/trevi00/zeus/issues/30)
  범위의 종료 경로를 따르는 별도 단계이며, 이 기록은 구현·검증 증거이지 배포 승인이 아닙니다.
