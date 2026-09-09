## 세 건 모두 해소됨

**1 해결.** `deployment.py:36-38`에서 125 규칙이 제거되고 데몬 stderr 패턴만 `observation_error`를 결정한다. `_probe_status:247-248`은 성공 시 0, unknown 시 **이전 값 보존**, 실제 실패 시 +1로 삼분되고, `:255`의 `not unknown` 조건으로 unknown이 스스로 롤백을 유발하지 않는다. `test_release_health.py:30-32`가 125 + "executable file not found"를 `executed`로 고정한다.

**2 해결.** `:292`가 `container["Service"]`로 키잉되어 컨테이너 재생성에도 연속 실패가 누적된다. `test_release_health.py:131`의 회전 ID fixture가 이 경로를 겨눈다.

**3 해결.** `:169`가 일반 Git-위치 차단(`:180-181`)보다 먼저 `remote and external_started and not merged`를 판정한다. `test_release_recovery.py:119`가 원격 merge + 로컬 HEAD 전진 후 receipt 누락 사례를 덮는다.

## 남은 차단 요소

**없음.** 다만 수용 가능한 트레이드오프 두 가지를 기록한다.

- `:169`는 publish 성공 후 merge가 *명백히 미수행*으로 끝난 경우(gh 비정상 종료, 원격 효과 없음)도 `blocked_remote`로 종결한다. 안전한 방향이지만 그런 릴리스는 자동 재시도 없이 사람이 조정해야 한다.
- 데몬 판정이 영어 stderr 문자열에 의존하므로 비영어 로케일에서는 데몬 다운이 후보 실패로 분류될 수 있다. 결과는 큐의 3회 재시도 후 `failed`로 경계되며, `releases.verify`를 거치지 않아 검수 상태는 보존된다.

실제 테스트 실행 결과나 하네스 전체는 검증하지 않았다. Windows/Linux 전체 스위트 결과는 별도 확인이 필요하다.