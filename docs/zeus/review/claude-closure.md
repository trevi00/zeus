## 이전 blocker: 해소됨

**동결 해제 경로가 성립한다.** `deployment.py:238`이 HEAD 정확 일치 대신 `not is_ancestor(candidate.revision, "HEAD")`를 요구하므로, main이 무관한 커밋으로 전진해 `_promote`가 `blocked`을 반환한 상태에서도 후보가 병합되지 않았음을 증명해 `abandon`할 수 있다. intent가 `abandoned`가 되면 `tickets.py:82-83`의 동결이 풀린다. 내가 지적한 "탈출구 없음"은 사라졌다.

**증명의 건전성도 유지된다.**
- `git.py:133-140`: 양쪽을 `rev-parse --verify ...^{commit}`로 먼저 해석하므로 존재하지 않는 ref는 `_git`에서 실패하고, `merge-base --is-ancestor`의 종료코드는 0/1만 수용하며 그 외는 `GitCommandError`로 올린다. 즉 **오류를 "미병합"으로 오독하지 않는다.** fail-closed 성질이 보존됐다.
- 이미 병합된 후보는 `:238`에서 거부(`is_ancestor` 참), 원격 불확실은 `:236-237`의 `external_started`/`merge` 검사로 여전히 거부, 살아 있는 controller는 `:233-235`로 거부된다. 세 보수 조건이 모두 남아 있다.
- dirty worktree 검사 제거는 타당하다. `abandon`은 DB 레코드만 쓰고 Git을 변형하지 않으므로(`:240-246`) 작업 트리 청결은 병합 여부 증명과 무관하다. 다만 이는 "abandon이 Git을 만지지 않는다"는 성질에 의존하므로, 향후 이 함수에 Git 변형이 추가되면 검사를 되살려야 한다는 점을 주석으로 고정해 두면 좋겠다.
- `run()`의 `require(release is not None)`(`:61`)도 반영됐다.

## 잔여 사소 사항 (차단 아님)
`abandon` 내부 `:241-242`는 `tx.get("releases", release_id)` 결과를 검사 없이 언패킹한다. intent는 있는데 릴리스 레코드가 없는 좁은 경우 `TypeError`가 된다. `run()`에 넣은 것과 동일한 `require` 한 줄이면 충분하다.

## 범위
이번 확인은 `git.py:133-140`, `deployment.py:52-64`, `:227-246`의 정적 읽기에 한정한다. 테스트를 실행하지 않았고 보고된 20 passed/5 skipped를 검증하지 않았다. 런타임 동작, 실제 Git/Docker/GitHub 상호작용, 로컬 원본 흡수 수준에 대해서는 어떤 인증도 하지 않는다.